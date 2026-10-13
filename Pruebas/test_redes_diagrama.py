"""Network design module, phase 6: the logical network diagram (generation from the saved
connections, saved diagrams, permissions, duplication)."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, diagrama, mufa, proyectos, red, usuarios


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def red_diagrama(con_redes):
    """Nodo Central -(Troncal 48)-> MF Norte -(Distribución 24)-> FAT 1 -(Acometida 12)-> Casa Pérez
                                     MF Norte -(Distribución Sur 24)-> MF Sur

    MF Norte: Troncal 2 -> Splitter 1 (1x8) entrada; salidas 1 y 2 -> Distribución 1 y 2; Troncal 5 fused
              with Distribución Sur 5 (not through the splitter).
    FAT 1:    Distribución 1 -> Conector A -> Acometida 1."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Los Robles", "codigo": "RLR"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "n", "tipo": "nodo", "nombre": "Nodo Central", "lat": 12.0950, "lon": -86.3000},
                      {"id": "m1", "tipo": "mufa", "subtipo": "distribucion", "nombre": "MF Norte", "lat": 12.1000, "lon": -86.3000},
                      {"id": "m2", "tipo": "mufa", "subtipo": "terminal", "nombre": "FAT 1", "lat": 12.1020, "lon": -86.3000},
                      {"id": "m3", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Sur", "lat": 12.0990, "lon": -86.3010},
                      {"id": "c1", "tipo": "cliente", "nombre": "Casa Pérez", "codigo": "C12345", "lat": 12.1021, "lon": -86.2995,
                       "propiedades": {"id_servicio": "ID418400"}}],
        "cables": [{"id": "k0", "nombre": "Troncal", "clase": "troncal", "hilos": 48, "origen_id": "n", "destino_id": "m1",
                    "vertices": [_v(12.0950, -86.3000), _v(12.1000, -86.3000)]},
                   {"id": "k1", "nombre": "Distribución", "hilos": 24, "hilos_por_buffer": 8, "origen_id": "m1", "destino_id": "m2",
                    "vertices": [_v(12.1000, -86.3000), _v(12.1020, -86.3000)]},
                   {"id": "k3", "nombre": "Distribución Sur", "hilos": 24, "origen_id": "m1", "destino_id": "m3",
                    "vertices": [_v(12.1000, -86.3000), _v(12.0990, -86.3010)]},
                   {"id": "k2", "nombre": "Acometida", "clase": "acometida", "tipo": "FLAT", "hilos": 12, "origen_id": "m2",
                    "destino_id": "c1", "vertices": [_v(12.1020, -86.3000), _v(12.1021, -86.2995)]}]})
    ids = r["ids"]
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    h = lambda vista, cable, n: next(f for c in vista["cables"] if c["nombre"] == cable for f in c["fibras"] if f["numero"] == n)["id"]
    r1 = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "splitters": [{"id": "s", "nombre": "Splitter 1", "salidas": 8}],
        "conexiones": [{"id": "a", "a": {"hilo": h(norte, "Troncal", 2)}, "b": {"splitter": "s", "lado": "entrada"}},
                       {"id": "b", "a": {"splitter": "s", "lado": "salida", "numero": 1}, "b": {"hilo": h(norte, "Distribución", 1)}},
                       {"id": "c", "a": {"splitter": "s", "lado": "salida", "numero": 2}, "b": {"hilo": h(norte, "Distribución", 2)}},
                       {"id": "d", "a": {"hilo": h(norte, "Troncal", 5)}, "b": {"hilo": h(norte, "Distribución Sur", 5)}}]})
    fat = mufa.leer(con, admin, mufa_id=ids["m2"])
    mufa.guardar(con, admin, mufa_id=ids["m2"], cambios={
        "conectores": [{"id": "k", "nombre": "Conector A"}],
        "conexiones": [{"id": "a", "a": {"hilo": h(fat, "Distribución", 1)}, "b": {"conector": "k", "lado": "entrada"}},
                       {"id": "b", "a": {"conector": "k", "lado": "salida"}, "b": {"hilo": h(fat, "Acometida", 1)}}]})
    return con, admin, p, {**ids, "s": r1["ids"]["s"]}


def _caja(d, nombre):
    return next(c for c in d["cajas"] if c["nombre"] == nombre)


def test_generated_from_a_mufa_forward(red_diagrama):
    """Acceptance case of the phase (the PDF export is made by the page): generated from a mufa."""
    con, admin, p, ids = red_diagrama
    d = diagrama.generar(con, admin, proyecto_id=p["id"], inicio=f"e:{ids['m1']}")
    assert [(c["nombre"], c["nivel"], c["simbolo"]) for c in d["cajas"]] == [
        ("MF Norte", 0, "fdt"), ("FAT 1", 1, "fat"), ("MF Sur", 1, "sc")]              # forward only: not the node
    norte = _caja(d, "MF Norte")
    assert norte["etiqueta"] == "MF Norte (1x8)" and norte["entrada"] is None
    assert sorted(norte["salidas"]) == sorted([ids["k1"], ids["k3"]])
    lineas = {(l["de"], l["a"]): l["hilos"] for l in norte["lineas"]}
    assert lineas == {(f"splitter:{ids['s']}:salida", f"salida:{ids['k1']}"): 2}     # Troncal is outside: its lines are not drawn
    fat = _caja(d, "FAT 1")
    assert fat["entrada"] == ids["k1"] and fat["clientes_omitidos"] == 1 and [k["nombre"] for k in fat["conectores"]] == ["Conector A"]
    assert {(l["de"], l["a"]) for l in fat["lineas"]} == {("entrada", f"conector:{fat['conectores'][0]['id']}:entrada")}
    cables = {k["nombre"]: k for k in d["cables"]}
    assert set(cables) == {"Distribución", "Distribución Sur"}
    assert (cables["Distribución"]["usados"], cables["Distribución"]["color"]) == (2, diagrama.COLORES_POR_DEFECTO[24])
    assert d["titulo"] == "Los Robles | MF Norte (FDT)" and d["leyenda"]["colores"][0] == {"hilos": 144, "color": "#e53935"}


def test_from_the_node_with_clients(red_diagrama):
    con, admin, p, ids = red_diagrama
    d = diagrama.generar(con, admin, proyecto_id=p["id"], inicio=f"e:{ids['n']}", incluir_clientes=True, direccion="izquierda")
    assert [c["nombre"] for c in d["cajas"]] == ["Nodo Central", "MF Norte", "FAT 1", "MF Sur", "Casa Pérez"]
    norte = _caja(d, "MF Norte")
    lineas = {(l["de"], l["a"]): l["hilos"] for l in norte["lineas"]}
    assert lineas[("entrada", f"splitter:{ids['s']}:entrada")] == 1
    assert lineas[("entrada", f"salida:{ids['k3']}")] == 1                             # the fusion Troncal 5 -> Distribución Sur 5
    casa = _caja(d, "Casa Pérez")
    assert (casa["simbolo"], casa["codigo"], casa["id_servicio"], casa["nivel"]) == ("cliente", "C12345", "ID418400", 3)
    troncal = next(k for k in d["cables"] if k["nombre"] == "Troncal")
    assert troncal["color"] == "#8e24aa" and d["direccion"] == "izquierda"            # 48 hilos: purple, as in the legend
    assert "cliente" in [s["simbolo"] for s in d["leyenda"]["simbolos"]]


def test_from_a_splitter_only_its_cables(red_diagrama):
    con, admin, p, ids = red_diagrama
    d = diagrama.generar(con, admin, proyecto_id=p["id"], inicio=f"s:{ids['s']}")
    assert [c["nombre"] for c in d["cajas"]] == ["MF Norte", "FAT 1"]                  # not MF Sur (fused, not from the splitter)
    assert [s["nombre"] for s in _caja(d, "MF Norte")["splitters"]] == ["Splitter 1"]
    assert d["inicio"]["texto"] == "Splitter 1 (1x8) · MF Norte"


def test_saved_diagrams_versions_history_and_duplicate(red_diagrama):
    con, admin, p, ids = red_diagrama
    with pytest.raises(db.DatosInvalidos) as e:
        diagrama.guardar(con, admin, proyecto_id=p["id"], datos={"titulo": "", "inicio": f"e:{ids['c1']}"})
    assert set(e.value.errores) == {"titulo", "inicio"}                               # a client is not a start point
    r = diagrama.guardar(con, admin, proyecto_id=p["id"], datos={"titulo": "Norte", "inicio": f"s:{ids['s']}", "direccion": "izquierda"})
    d = r["diagramas"][0]
    assert (d["titulo"], d["elemento"], d["caja"], d["direccion"], d["incluir_clientes"]) == ("Norte", "Splitter 1", "MF Norte", "izquierda", False)
    assert {i["clave"] for i in r["inicios"]} >= {f"e:{ids['n']}", f"e:{ids['m1']}", f"s:{ids['s']}"}
    assert f"e:{ids['c1']}" not in {i["clave"] for i in r["inicios"]}
    g = diagrama.generar(con, admin, diagrama_id=d["id"])
    assert g["titulo"] == "Norte" and g["direccion"] == "izquierda" and len(g["cajas"]) == 2
    r2 = diagrama.guardar(con, admin, proyecto_id=p["id"], datos={**d, "titulo": "Norte 2", "incluir_clientes": True})
    with pytest.raises(db.ConflictoVersion):
        diagrama.guardar(con, admin, proyecto_id=p["id"], datos={**d, "titulo": "viejo"})          # old version
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    assert [x["titulo"] for x in diagrama.listar(con, admin, proyecto_id=copia["id"])["diagramas"]] == ["Norte 2"]
    acciones = {(h["entidad"], h["accion"]) for h in proyectos.historial(con, admin, id=p["id"])["historial"]}
    assert {("diagrama", "crear"), ("diagrama", "editar")} <= acciones
    final = r2["diagramas"][0]
    assert diagrama.eliminar(con, admin, id=final["id"], version=final["version"])["diagramas"] == []
    with pytest.raises(db.NoEncontrado):
        diagrama.generar(con, admin, diagrama_id=final["id"])


def test_readers_and_deleted_start(red_diagrama):
    con, admin, p, ids = red_diagrama
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    lector = con.execute("SELECT * FROM redes.usuarios WHERE id = %s", (lector["id"],)).fetchone()
    with pytest.raises(db.SinPermiso):
        diagrama.listar(con, lector, proyecto_id=p["id"])                              # not assigned
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], lector["id"]]})
    assert diagrama.listar(con, lector, proyecto_id=p["id"])["proyecto"]["puede_editar"] is False
    assert len(diagrama.generar(con, lector, proyecto_id=p["id"], inicio=f"e:{ids['m1']}")["cajas"]) == 3
    with pytest.raises(db.SinPermiso):
        diagrama.guardar(con, lector, proyecto_id=p["id"], datos={"titulo": "x", "inicio": f"e:{ids['m1']}"})
    d = diagrama.guardar(con, admin, proyecto_id=p["id"], datos={"titulo": "Desde Sur", "inicio": f"e:{ids['m3']}"})["diagramas"][0]
    mapa = red.red(con, admin, proyecto_id=p["id"])
    sur = next(e for e in mapa["elementos"] if e["nombre"] == "MF Sur")
    cable_sur = next(c for c in mapa["cables"] if c["nombre"] == "Distribución Sur")
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**cable_sur, "eliminar": True}], "elementos": [{**sur, "eliminar": True}]})
    lista = diagrama.listar(con, admin, proyecto_id=p["id"])["diagramas"]
    assert lista[0]["inicio_eliminado"] is True
    with pytest.raises(db.NoEncontrado, match="ya no existe"):
        diagrama.generar(con, admin, diagrama_id=d["id"])


def test_capacity_colours():
    colores = diagrama.COLORES_POR_DEFECTO
    assert diagrama.color_de(144, colores) == "#e53935" and diagrama.color_de(48, colores) == "#8e24aa"
    assert diagrama.color_de(36, colores) == colores[48] and diagrama.color_de(288, colores) == colores[144]


def test_export_png_and_pdf(tmp_path, monkeypatch):
    """Api.guardar_imagen: the page's PNG saved as PNG or as a one-page PDF (Pillow), via the save dialog."""
    import base64
    import io
    import sys
    import types

    from PIL import Image

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1)))
    from visor_rutas.ventana_web import Api
    imagen = Image.new("RGBA", (600, 300), (255, 255, 255, 0))
    imagen.putpixel((10, 10), (142, 36, 170, 255))
    buf = io.BytesIO()
    imagen.save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    pedidos = []

    class Ventana:
        def create_file_dialog(self, *args, **kwargs):
            pedidos.append(kwargs)
            return (str(tmp_path / "diagrama"),)

    api = Api.__new__(Api)
    api._ventana = Ventana()
    r = api.guardar_imagen("Los Robles | MF Norte", url, "pdf")
    assert r["ok"] and (tmp_path / "diagrama.pdf").read_bytes().startswith(b"%PDF")
    assert pedidos[0]["save_filename"] == "Los Robles _ MF Norte.pdf"                  # no characters Windows rejects
    assert api.guardar_imagen("x", url, "png")["ok"] and (tmp_path / "diagrama.png").read_bytes().startswith(b"\x89PNG")
    assert api.guardar_imagen("x", "data:image/png;base64,AAAA", "png")["ok"] is False


def test_service_methods(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS
    assert {"diagramas", "guardar_diagrama", "eliminar_diagrama", "generar_diagrama"} <= set(METODOS)
