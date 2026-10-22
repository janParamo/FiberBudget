"""Las cuadrillas (rol «tecnico»): ven los postes y mufas existentes pero no los editan ni ven nada más de la red; y los tipos de poste son los de la lista de Jan:
Ideay tubular, Ideay 8/120, Ideay 9/120, Madera y Concreto."""
import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import LAT, LON, punto
from test_campo_revision import crear_proyecto, mundo  # noqa: F401
from test_campo_trazos import api, poste_en  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import campo, db, red

POSTES = {"ideay_tubular": "Ideay tubular", "ideay_8_120": "Ideay 8/120", "ideay_9_120": "Ideay 9/120", "madera": "Madera", "concreto": "Concreto"}


# ------------------------------------------------------------------ the types of pole

def test_the_types_of_pole_are_the_five_of_the_list_and_are_stored_as_slugs(mundo):
    con, g = mundo
    assert campo.POSTES == POSTES and list(campo.SUBTIPOS_POSTE) == list(POSTES)
    for etiqueta, clave in (("Ideay tubular", "ideay_tubular"), ("Ideay 8/120", "ideay_8_120"), ("IDEAY 9/120", "ideay_9_120"), ("madera", "madera"),
                            ("Concreto", "concreto"), ("ideay_8_120", "ideay_8_120"), ("  Ideay  tubular ", "ideay_tubular")):
        r = campo.guardar_puntos(con, g["juan"], puntos=[punto(subtipo=etiqueta)])["resultados"][0]
        assert r["ok"] and r["punto"]["subtipo"] == clave, etiqueta
    # the old list is not offered any more: a new point cannot be «ideay» alone, «metal» or «cliente»
    for viejo in ("ideay", "metal", "cliente", "plástico", "Ideay 10/120"):
        r = campo.guardar_puntos(con, g["juan"], puntos=[punto(subtipo=viejo)])["resultados"][0]
        assert r["ok"] is False and "Ideay tubular" in r["errores"]["subtipo"] and "Concreto" in r["errores"]["subtipo"], viejo
    # editing a pending point: the same rule
    p = campo.guardar_puntos(con, g["juan"], puntos=[punto(subtipo="madera")])["resultados"][0]["punto"]
    e = campo.editar_punto(con, g["juan"], id=p["id"], version=p["version"], cambios={"subtipo": "Ideay 9/120"})["punto"]
    assert e["subtipo"] == "ideay_9_120"
    with pytest.raises(db.DatosInvalidos):
        campo.editar_punto(con, g["juan"], id=p["id"], version=e["version"], cambios={"subtipo": "metal"})
    # the other kinds of point do not use these types; a mufa keeps its own (48 / 96, domo / horizontal)
    assert campo.guardar_puntos(con, g["juan"], puntos=[punto(tipo="mufa", subtipo="Ideay tubular")])["resultados"][0]["ok"] is False


def test_an_approved_pole_keeps_its_type_when_it_is_edited_in_the_network_editor(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    p = campo.guardar_puntos(con, g["juan"], puntos=[punto(subtipo="Ideay 8/120", nombre="PT 8/120")])["resultados"][0]["punto"]
    r = campo.aprobar(con, g["edu"], ids=[p["id"]], destino="red")["resultados"][0]
    el = con.execute("SELECT id, subtipo, version FROM redes.elementos WHERE id = %s", (r["elemento_id"],)).fetchone()
    assert el["subtipo"] == "ideay_8_120"
    # the editor saves the element again with its own type: it is not turned into another one
    red.guardar(con, g["admin"], proyecto_id=base, cambios={"elementos": [{"id": el["id"], "version": el["version"], "tipo": "poste", "subtipo": "ideay_8_120", "nombre": "PT 8/120",
                                                                           "lat": LAT, "lon": LON}]})
    assert con.execute("SELECT subtipo FROM redes.elementos WHERE id = %s", (el["id"],)).fetchone()["subtipo"] == "ideay_8_120"
    # the poles drawn before the list changed keep theirs
    antiguo = poste_en(con, base, "VIEJO", LAT + 0.01, LON)
    con.execute("UPDATE redes.elementos SET subtipo = 'metal' WHERE id = %s", (antiguo,))
    fila = con.execute("SELECT version FROM redes.elementos WHERE id = %s", (antiguo,)).fetchone()
    red.guardar(con, g["admin"], proyecto_id=base, cambios={"elementos": [{"id": antiguo, "version": fila["version"], "tipo": "poste", "subtipo": "metal", "nombre": "VIEJO", "lat": LAT + 0.01, "lon": LON}]})
    assert con.execute("SELECT subtipo FROM redes.elementos WHERE id = %s", (antiguo,)).fetchone()["subtipo"] == "metal"


# ------------------------------------------------------------------ what the crews see of the existing network

def test_the_crews_see_only_poles_and_mufas_of_the_base_network_and_no_lines(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    a, b = poste_en(con, base, "PT-1", LAT, LON), poste_en(con, base, "MF-1", LAT + 0.0005, LON, tipo="mufa")
    poste_en(con, base, "NODO-1", LAT + 0.0003, LON, tipo="nodo")
    poste_en(con, base, "ODF-1", LAT + 0.0004, LON, tipo="odf")
    con.execute("INSERT INTO redes.cables (proyecto_id, nombre, origen_id, destino_id, vertices, geom) VALUES (%s, 'Cable A', %s, %s, '[]'::jsonb, %s)",
                (base, a, b, f"SRID=4326;LINESTRING({LON} {LAT}, {LON} {LAT + 0.0005})"))
    zona = dict(oeste=LON - 0.01, sur=LAT - 0.01, este=LON + 0.01, norte=LAT + 0.01)
    r = campo.red_referencia(con, g["juan"], **zona)
    assert {p["n"] for p in r["puntos"]} == {"PT-1", "MF-1"} and r["lineas"] == []                       # no nodes, no ODF, no lines
    assert campo.configuracion()["red_tipos"] == ["poste", "mufa"] and campo.configuracion()["red_lineas"] is False


def test_the_lines_come_back_with_one_setting(mundo, monkeypatch):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    a, b = poste_en(con, base, "PT-1", LAT, LON), poste_en(con, base, "MF-1", LAT + 0.0005, LON, tipo="mufa")
    con.execute("INSERT INTO redes.cables (proyecto_id, nombre, origen_id, destino_id, vertices, geom) VALUES (%s, 'Cable A', %s, %s, '[]'::jsonb, %s)",
                (base, a, b, f"SRID=4326;LINESTRING({LON} {LAT}, {LON} {LAT + 0.0005})"))
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "red_lineas": True})
    r = campo.red_referencia(con, g["juan"], oeste=LON - 0.01, sur=LAT - 0.01, este=LON + 0.01, norte=LAT + 0.01)
    assert [x["n"] for x in r["lineas"]] == ["Cable A"]


def test_the_kmz_part_of_the_zone_asks_only_for_poles_and_mufas(api, monkeypatch):
    c, con = api
    import db as presupuesto
    recibido = {}

    def falso(o, s, e, n, max_puntos, max_lineas, prefijos=None):
        recibido.update(max_lineas=max_lineas, prefijos=prefijos)
        return {"puntos": [{"id": "k1", "n": "poste de concreto", "t": "poste de concreto", "lat": LAT, "lon": LON}], "lineas": [], "truncado": False}
    monkeypatch.setattr(presupuesto, "find_red_en_bbox", falso)
    r = c.get(f"/visor/campo/red?bbox={LON - 0.005},{LAT - 0.005},{LON + 0.005},{LAT + 0.005}", headers=JAN).json()
    assert r["ok"] and recibido == {"max_lineas": 0, "prefijos": ["poste", "mufa"]} and r["lineas"] == []


def test_the_budget_database_query_filters_by_type_prefix():
    """The real SQL: the prefixes become «tipo ILIKE 'poste%'» and no lines are read when asked for none (the connection is a stub)."""
    import db as presupuesto
    consultas = []

    class Con:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            consultas.append((sql, params))

            class R:
                def fetchall(self_):
                    return []
            return R()
    original = presupuesto.psycopg.connect
    presupuesto.psycopg.connect = lambda **k: Con()
    try:
        r = presupuesto.find_red_en_bbox(-86.3, 12.1, -86.2, 12.2, 100, 0, ["poste", "mufa"])
        presupuesto.find_red_en_bbox(-86.3, 12.1, -86.2, 12.2, 100, 50)
    finally:
        presupuesto.psycopg.connect = original
    assert r == {"puntos": [], "lineas": [], "truncado": False}
    assert len(consultas) == 3                                                        # first call: points only; second call: points and lines
    assert consultas[0][1]["pat"] == ["poste%", "mufa%"] and consultas[1][1]["pat"] is None and "ST_AsGeoJSON" in consultas[2][0] and "red_lineas" in consultas[2][0]


# ------------------------------------------------------------------ the crews cannot edit

def test_a_crew_cannot_use_the_network_module_only_the_field_app(api):
    c, con = api                                                                     # jan and maria are «tecnico» here
    base = crear_proyecto(con, "RB", base=True)
    pid = poste_en(con, base, "PT-1", LAT, LON)
    for metodo, args in (("proyectos", {}), ("red_proyecto", {"proyecto_id": base}), ("usuarios", {}),
                         ("guardar_red", {"proyecto_id": base, "cambios": {"elementos": [{"id": pid, "version": 1, "tipo": "poste", "subtipo": "madera", "nombre": "CAMBIADO",
                                                                                           "lat": LAT, "lon": LON}]}}),
                         ("campo_aprobar", {"ids": [1], "destino": "red"}), ("campo_ubicaciones", {})):
        r = c.post(f"/visor/redes/{metodo}", json={"args": args}, headers=JAN).json()
        assert r["ok"] is False and "técnico de campo" in r["error"], metodo
    fila = con.execute("SELECT nombre, subtipo FROM redes.elementos WHERE id = %s", (pid,)).fetchone()
    assert fila["nombre"] == "PT-1" and fila["subtipo"] is None                      # nothing was changed
    assert c.post("/visor/redes/estado", json={"args": {}}, headers=JAN).json()["ok"] is True      # who it is: allowed
    # the field app keeps working for them
    assert c.get("/visor/campo/config", headers=JAN).json()["ok"] is True
    assert c.post("/visor/campo/puntos", json={"puntos": [punto()]}, headers=JAN).json()["resultados"][0]["ok"] is True
    # and the reviewers (editors) are not affected
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'jan'")
    assert c.post("/visor/redes/proyectos", json={"args": {}}, headers=JAN).json()["ok"] is True
