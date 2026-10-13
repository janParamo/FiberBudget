"""Network design module, phase 3: the map editor's network (elements, cables, notes), saved in
one transaction with temporary ids, optimistic locking and history; metraje with diseno_red;
safe note HTML; duplicating a project copies its network."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, metraje, proyectos, red, texto, usuarios

REGLA = metraje.reglas(None)          # the decided values: the budget's route rules


@pytest.fixture
def proyecto(con_redes):
    admin = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    p = proyectos.guardar(con_redes, admin, datos={"nombre": "Los Robles", "codigo": "RLR"})["proyecto"]
    return con_redes, admin, p


def _tramo():
    """Two mufas, a pole in between and a client; a cable mufa -> pole -> mufa and a drop."""
    return {"elementos": [
        {"id": "m1", "tipo": "mufa", "subtipo": "distribucion", "nombre": "MF Norte", "lat": 12.1000, "lon": -86.3000,
         "propiedades": {"capacidad": 48, "bandejas": 4}},
        {"id": "p1", "tipo": "poste", "subtipo": "concreto", "nombre": "P-01", "lat": 12.1010, "lon": -86.3000},
        {"id": "m2", "tipo": "mufa", "subtipo": "terminal", "nombre": "FAT 1", "lat": 12.1020, "lon": -86.3000},
        {"id": "c1", "tipo": "cliente", "nombre": "Casa Pérez", "codigo": "c12345", "lat": 12.1021, "lon": -86.2995,
         "propiedades": {"id_servicio": "ID418400"}}],
        "cables": [
        {"id": "k1", "nombre": "Troncal Norte", "clase": "troncal", "tipo": "ADSS", "hilos": 48, "hilos_por_buffer": 12,
         "color": "#FF0000", "origen_id": "m1", "destino_id": "m2", "cruces": 1,
         "vertices": [{"lat": 0, "lon": 0}, {"lat": 12.1011, "lon": -86.3001, "elemento_id": "p1"}, {"lat": 0, "lon": 0}]},
        {"id": "k2", "nombre": "Acometida Pérez", "clase": "acometida", "tipo": "FLAT", "hilos": 12, "hilos_por_buffer": 8,
         "color": "#00aa00", "origen_id": "m2", "destino_id": "c1",
         "vertices": [{"lat": 12.1020, "lon": -86.3000}, {"lat": 12.1021, "lon": -86.2995}]}],
        "notas": [{"id": "n1", "html": "<p><strong>Ojo</strong> poste dañado<script>alert(1)</script></p>", "elemento_id": "p1"}]}


# --------------------------------------------------------------------------- metraje

def test_metraje_uses_the_budget_rules():
    d = metraje.calcular(197.0, ["mufa", "mufa"], 1, REGLA)
    assert d["distancia_lineal_m"] == 197.0 and d["contingencia_m"] == 0
    assert d["reservas_mufa"] == {"cantidad": 2, "unidad_m": 35.0, "total_m": 70.0}
    assert d["reservas_tendido"]["cantidad"] == 1 and d["reservas_tendido"]["total_m"] == 60.0     # ceil(197/300) x 300 x 20 %
    assert d["reservas_cruce"]["total_m"] == 0
    assert d["metraje_m"] == 327                                                                 # 197 + 70 + 60
    assert metraje.calcular(301, ["mufa", "cliente"], 0, REGLA)["metraje_m"] == 301 + 35 + 120
    otra = metraje.reglas({"diseno_red": {"reserva_por_cruce_m": 60, "contingencia_porcentaje": 0.1}})
    assert metraje.calcular(100, ["poste", "poste"], 2, otra)["metraje_m"] == 100 + 10 + 60 + 120
    assert metraje.longitud_m([(12.1, -86.3), (12.101, -86.3)]) == pytest.approx(111.2, abs=0.5)


def test_note_html_is_made_safe():
    limpio = texto.limpiar_html('<p class="ql-align-center x"><strong>Hola</strong> <span style="color: rgb(230, 0, 0); '
                                'position: fixed" onclick="x()">rojo</span><img src=x onerror=alert(1)></p>'
                                '<ol><li>uno</li></ol><a href="javascript:alert(1)">mal</a><a href="https://ideay.net">bien</a>')
    assert "<strong>Hola</strong>" in limpio and 'class="ql-align-center"' in limpio
    assert 'style="color: rgb(230, 0, 0)"' in limpio and "position" not in limpio and "onclick" not in limpio
    assert "<img" not in limpio and "javascript" not in limpio and 'href="https://ideay.net"' in limpio and "<ol>" in limpio
    assert texto.limpiar_html("<p><br></p>") == "" and texto.limpiar_html("<script>x</script>") == ""


# --------------------------------------------------------------------------- guardar

def test_save_a_section_with_temporary_ids(proyecto):
    con, admin, p = proyecto
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios=_tramo())
    assert set(r["ids"]) == {"m1", "p1", "m2", "c1", "k1", "k2", "n1"}
    por_nombre = {e["nombre"]: e for e in r["elementos"]}
    assert por_nombre["MF Norte"]["propiedades"] == {"capacidad": 48, "bandejas": 4}
    assert por_nombre["Casa Pérez"]["codigo"] == "C12345" and por_nombre["P-01"]["subtipo"] == "concreto"
    troncal = next(c for c in r["cables"] if c["nombre"] == "Troncal Norte")
    assert (troncal["origen_id"], troncal["destino_id"]) == (r["ids"]["m1"], r["ids"]["m2"])
    v = troncal["vertices"]
    assert (v[0]["lat"], v[-1]["lat"]) == (12.1, 12.102)                 # ends snapped to the mufas
    assert (v[1]["lat"], v[1]["lon"], v[1]["elemento_id"]) == (12.101, -86.3, r["ids"]["p1"])   # vertex on the pole
    assert troncal["longitud_m"] == pytest.approx(222.4, abs=1)
    assert troncal["metraje"]["metraje_m"] == metraje.calcular(troncal["longitud_m"], ["mufa", "mufa"], 1, REGLA)["metraje_m"]
    assert troncal["color"] == "#ff0000" and troncal["hilos_por_buffer"] == 12
    assert r["notas"][0]["html"] == "<p><strong>Ojo</strong> poste dañado</p>" and r["notas"][0]["elemento_id"] == r["ids"]["p1"]
    acciones = {(h["entidad"], h["accion"]) for h in proyectos.historial(con, admin, id=p["id"])["historial"]}
    assert {("elemento", "crear"), ("cable", "crear"), ("nota", "crear")} <= acciones
    # the clients of the project form are the same elements
    assert [c["nombre"] for c in proyectos.obtener(con, admin, id=p["id"])["proyecto"]["clientes"]] == ["Casa Pérez"]


def test_moving_a_pole_moves_the_cable_and_recomputes_the_metraje(proyecto):
    con, admin, p = proyecto
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios=_tramo())
    poste = next(e for e in r["elementos"] if e["nombre"] == "P-01")
    antes = next(c for c in r["cables"] if c["nombre"] == "Troncal Norte")
    r2 = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**poste, "lon": -86.2990}]})
    despues = next(c for c in r2["cables"] if c["nombre"] == "Troncal Norte")
    assert despues["vertices"][1]["lon"] == -86.299 and despues["longitud_m"] > antes["longitud_m"]
    assert despues["version"] == antes["version"] + 1
    assert despues["metraje"]["metraje_m"] >= antes["metraje"]["metraje_m"]


def test_validation_conflicts_and_deleting_elements_with_cables(proyecto):
    con, admin, p = proyecto
    with pytest.raises(db.DatosInvalidos, match="falta el nombre"):
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{"id": "x", "tipo": "poste", "nombre": "", "lat": 12, "lon": -86}]})
    with pytest.raises(db.DatosInvalidos, match="cantidad de hilos"):
        malo = _tramo()
        malo["cables"][0]["hilos"] = 30
        red.guardar(con, admin, proyecto_id=p["id"], cambios=malo)
    with pytest.raises(db.DatosInvalidos, match="elementos del proyecto"):
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**_tramo()["cables"][1], "origen_id": 999999, "destino_id": 999998}]})
    assert red.red(con, admin, proyecto_id=p["id"])["elementos"] == []          # nothing half-saved
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios=_tramo())
    mufa = next(e for e in r["elementos"] if e["nombre"] == "MF Norte")
    with pytest.raises(db.DatosInvalidos, match="tiene cables conectados \\(Troncal Norte\\)"):
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**mufa, "eliminar": True}]})
    troncal = next(c for c in r["cables"] if c["nombre"] == "Troncal Norte")
    r2 = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**mufa, "eliminar": True}],
                                                                "cables": [{**troncal, "eliminar": True}]})
    assert "MF Norte" not in {e["nombre"] for e in r2["elementos"]} and len(r2["cables"]) == 1
    assert con.execute("SELECT count(*) AS n FROM redes.elementos WHERE nombre = 'MF Norte' AND borrado_en IS NOT NULL").fetchone()["n"] == 1
    poste = next(e for e in r2["elementos"] if e["nombre"] == "P-01")
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**poste, "nombre": "P-01 bis"}]})
    with pytest.raises(db.ConflictoVersion, match="P-01"):                       # someone saved since
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**poste, "nombre": "P-01 otra"}]})
    with pytest.raises(db.DatosInvalidos, match="tipo"):
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**poste, "version": poste["version"] + 1, "tipo": "mufa"}]})


def test_permissions_and_duplicate_copies_the_network(proyecto):
    con, admin, p = proyecto
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    lector = con.execute("SELECT * FROM redes.usuarios WHERE id = %s", (lector["id"],)).fetchone()
    p = proyectos.guardar(con, admin, datos={**p, "usuarios": [admin["id"], lector["id"]]})["proyecto"]
    assert red.red(con, lector, proyecto_id=p["id"])["proyecto"]["puede_editar"] is False
    with pytest.raises(db.SinPermiso):
        red.guardar(con, lector, proyecto_id=p["id"], cambios=_tramo())
    red.guardar(con, admin, proyecto_id=p["id"], cambios=_tramo())
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    r = red.red(con, admin, proyecto_id=copia["id"])
    assert len(r["elementos"]) == 4 and len(r["cables"]) == 2 and len(r["notas"]) == 1
    ids = {e["id"] for e in r["elementos"]}
    assert all(c["origen_id"] in ids and c["destino_id"] in ids for c in r["cables"])
    assert all(v["elemento_id"] in ids or v["elemento_id"] is None for c in r["cables"] for v in c["vertices"])
    assert r["notas"][0]["elemento_id"] in ids


def test_service_methods(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS, ServicioRedes
    assert {"red_proyecto", "guardar_red"} <= set(METODOS)
    servicio = ServicioRedes(conectar=lambda: db.conectar(params=base_redes[1]))
    try:
        p = servicio.llamar("guardar_proyecto", {"datos": {"nombre": "Uno", "codigo": "U1"}}, usuario_windows="jgutierrez")["proyecto"]
        r = servicio.llamar("guardar_red", {"proyecto_id": p["id"], "cambios": _tramo()}, usuario_windows="jgutierrez")
        assert r["ok"] and len(r["cables"]) == 2 and r["reglas_metraje"]["reserva_por_mufa_m"] == 35
        mal = servicio.llamar("guardar_red", {"proyecto_id": p["id"], "cambios": {"elementos": [{"id": "z", "tipo": "x"}]}},
                              usuario_windows="jgutierrez")
        assert mal["ok"] is False and "tipo de elemento" in mal["error"]
        assert 4 in servicio.llamar("estado", usuario_windows="jgutierrez")["migraciones"]
    finally:
        servicio.cerrar()
