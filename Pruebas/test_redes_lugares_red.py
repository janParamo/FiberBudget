"""Visor v2, fase 4: red dibujada en una carpeta de Mis lugares (visor_rutas/redes/lugares_red.py) — datos y estilo de cada tipo,
cables unidos a sus elementos con metraje, cables que siguen al elemento, borrar con cables y "Guardar como proyecto"."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, lugares, lugares_kmz, usuarios
from visor_rutas.redes.api import METODOS


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    ana = usuarios.identificar(con, persona_visor="ana")                      # a reader
    return con, admin, ana


def _punto(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def _red(con, actor, carpeta, tipo, nombre, lon, lat, **propiedades):
    return lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo=tipo, nombre=nombre, geom=_punto(lon, lat), propiedades=propiedades)["lugar"]


def _cable(con, actor, carpeta, a, b, medio=(), **propiedades):
    pts = [a["geom"]["coordinates"], *[list(p) for p in medio], b["geom"]["coordinates"]]
    return lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="cable", nombre="Cable 1", geom={"type": "LineString", "coordinates": pts},
                                 propiedades={"origen_id": a["id"], "destino_id": b["id"], **propiedades})["lugar"]


def _carpeta(con, actor, nombre="Red nueva"):
    return lugares.guardar_carpeta(con, actor, nombre=nombre)["id"]


def test_each_type_gets_its_data_and_the_icon_of_its_subtype(mundo):
    con, admin, _ = mundo
    f = _carpeta(con, admin)
    m = _red(con, admin, f, "mufa", "MF-1", -86.25, 12.13, subtipo="terminal", capacidad="48", bandejas=4, basura=1)
    assert m["propiedades"] == {"subtipo": "terminal", "capacidad": 48, "bandejas": 4}
    assert m["estilo"]["icono"]["id"] == "anillo" and m["estilo"]["icono"]["color"] == "#d6249f"
    p = _red(con, admin, f, "poste", "P-1", -86.251, 12.13, subtipo="raro")                      # unknown subtype -> the first one
    assert p["propiedades"] == {"subtipo": "ideay"} and p["estilo"]["etiqueta"]["visible"] is False        # posts: no label
    c = _red(con, admin, f, "cliente", "Casa", -86.252, 12.13, codigo="c12345", id_servicio="  S 9 ")
    assert c["propiedades"] == {"codigo": "C12345", "id_servicio": "S 9"} and c["estilo"]["icono"]["id"] == "rombo"
    assert _red(con, admin, f, "nodo", "OLT", -86.26, 12.13, subtipo="olt")["estilo"]["icono"]["id"] == "triangulo"
    assert _red(con, admin, f, "odf", "ODF 1", -86.26, 12.131)["propiedades"] == {}
    # the icon follows the subtype when it changes, and cannot be set by hand
    n = lugares.guardar_lugar(con, admin, id=m["id"], version=m["version"], propiedades={"subtipo": "distribucion"},
                              estilo={"icono": {"tipo": "letra", "id": "Z", "color": "#000000"}})["lugar"]
    assert n["estilo"]["icono"]["id"] == "cuadrado"
    for malo in ({"codigo": "XX"}, ):
        with pytest.raises(db.DatosInvalidos):
            _red(con, admin, f, "cliente", "Mala", -86.3, 12.1, **malo)
    with pytest.raises(db.DatosInvalidos):
        _red(con, admin, f, "mufa", "Mala", -86.3, 12.1, capacidad=5000)
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="mufa", nombre="X", geom={"type": "LineString", "coordinates": [[0, 0], [1, 1]]})


def test_a_cable_joins_two_elements_snaps_its_ends_and_has_metraje(mundo):
    con, admin, _ = mundo
    f = _carpeta(con, admin)
    a = _red(con, admin, f, "nodo", "OLT", -86.25, 12.13, subtipo="olt")
    b = _red(con, admin, f, "cliente", "Casa", -86.25, 12.14)
    c = lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="cable", nombre="Troncal 1", propiedades={"origen_id": a["id"], "destino_id": b["id"], "clase": "troncal", "hilos": 24},
                              geom={"type": "LineString", "coordinates": [[-86.2502, 12.1301], [-86.2501, 12.135], [-86.2499, 12.1399]]})["lugar"]
    p = c["propiedades"]
    assert (p["clase"], p["tipo"], p["hilos"], p["origen_id"], p["destino_id"]) == ("troncal", "ADSS", 24, a["id"], b["id"])
    assert c["geom"]["coordinates"][0] == [-86.25, 12.13] and c["geom"]["coordinates"][-1] == [-86.25, 12.14]       # the ends take the elements' position
    assert 1100 < p["longitud_m"] < 1115 and p["metraje"]["metraje_m"] >= p["longitud_m"]
    assert p["metraje"]["reservas_cliente"]["cantidad"] == 1 and c["estilo"]["linea"]["grosor"] == 5
    # same ends -> refused; an end that is not a network element -> refused
    for origen, destino in ((a["id"], a["id"]), (a["id"], 999999)):
        with pytest.raises(db.DatosInvalidos):
            lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="cable", nombre="X", propiedades={"origen_id": origen, "destino_id": destino},
                                  geom={"type": "LineString", "coordinates": [[-86.25, 12.13], [-86.25, 12.14]]})
    marca = lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="marca", nombre="M", geom=_punto(-86.3, 12.2))["lugar"]
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="cable", nombre="X", propiedades={"origen_id": a["id"], "destino_id": marca["id"]},
                              geom={"type": "LineString", "coordinates": [[-86.25, 12.13], [-86.3, 12.2]]})
    # another person's elements cannot be joined
    otra = _carpeta(con, mundo[2], "De Ana")
    ajeno = _red(con, mundo[2], otra, "poste", "Ajeno", -86.2, 12.1)
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="cable", nombre="X", propiedades={"origen_id": a["id"], "destino_id": ajeno["id"]},
                              geom={"type": "LineString", "coordinates": [[-86.25, 12.13], [-86.2, 12.1]]})


def test_moving_an_element_moves_the_end_of_its_cables(mundo):
    con, admin, _ = mundo
    f = _carpeta(con, admin)
    a = _red(con, admin, f, "nodo", "OLT", -86.25, 12.13)
    b = _red(con, admin, f, "cliente", "Casa", -86.25, 12.14)
    c = _cable(con, admin, f, a, b, medio=[(-86.2505, 12.135)])
    antes = c["propiedades"]["longitud_m"]
    lugares.guardar_lugar(con, admin, id=b["id"], version=b["version"], geom=_punto(-86.25, 12.15))
    despues = lugares.obtener(con, admin, id=c["id"])["lugar"]
    assert despues["geom"]["coordinates"][-1] == [-86.25, 12.15] and despues["geom"]["coordinates"][1] == [-86.2505, 12.135]
    assert despues["propiedades"]["longitud_m"] > antes and despues["version"] == c["version"] + 1
    # the cable is not changed if it is the element's rename only
    lugares.guardar_lugar(con, admin, id=a["id"], version=a["version"], nombre="OLT 2")
    assert lugares.obtener(con, admin, id=c["id"])["lugar"]["version"] == despues["version"]


def test_deleting_an_element_with_cables_needs_the_cables_too(mundo):
    con, admin, _ = mundo
    f = _carpeta(con, admin)
    a = _red(con, admin, f, "poste", "P1", -86.25, 12.13)
    b = _red(con, admin, f, "poste", "P2", -86.25, 12.14)
    c = _cable(con, admin, f, a, b)
    with pytest.raises(db.DatosInvalidos) as exc:
        lugares.eliminar_lugar(con, admin, id=a["id"])
    assert "Cable 1" in str(exc.value.errores)
    lugares.eliminar_lugar(con, admin, id=a["id"], con_cables=True)
    ids = {e["id"] for e in lugares.arbol(con, admin)["elementos"]}
    assert ids == {b["id"]} and c["id"] not in ids


def test_save_the_folder_as_a_project_with_its_cables(mundo):
    con, admin, ana = mundo
    f = _carpeta(con, admin, "Red de prueba")
    sub = lugares.guardar_carpeta(con, admin, nombre="Sub", padre_id=f)["id"]
    olt = _red(con, admin, f, "nodo", "OLT 1", -86.25, 12.13, subtipo="olt")
    poste = _red(con, admin, sub, "poste", "P1", -86.25, 12.135, subtipo="ideay")
    mufa = _red(con, admin, sub, "mufa", "MF-9", -86.25, 12.14, subtipo="empalme", capacidad=48)
    casa = _red(con, admin, f, "cliente", "Casa", -86.25, 12.145, codigo="C777")
    _cable(con, admin, f, olt, mufa, medio=[(-86.25, 12.135)], clase="troncal", hilos=48)                     # passes through the post
    _cable(con, admin, f, mufa, casa, clase="acometida", tipo="FLAT", hilos=2)
    lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="marca", nombre="Una marca", geom=_punto(-86.3, 12.2))
    lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="cable", nombre="Cable suelto", geom={"type": "LineString", "coordinates": [[-86.2, 12.1], [-86.21, 12.1]]})
    r = METODOS["lugares_a_proyecto"](con, admin, carpeta_id=f)
    assert r["resumen"] == {"elementos": 4, "cables": 2, "cables_omitidos": ["Cable suelto"], "fuera_de_la_red": 1, "ids": 6}
    assert r["proyecto"]["nombre"] == "Red de prueba" and r["proyecto"]["codigo"].startswith("LUG-")
    pid = r["proyecto"]["id"]
    elementos = {x["nombre"]: x for x in con.execute("SELECT * FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL", (pid,)).fetchall()}
    assert set(elementos) == {"OLT 1", "P1", "MF-9", "Casa"} and elementos["Casa"]["codigo"] == "C777"
    assert elementos["P1"]["subtipo"] == "ideay" and elementos["MF-9"]["propiedades"] == {"capacidad": 48}
    assert con.execute("SELECT count(*) AS n FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL", (pid,)).fetchone()["n"] == 2
    troncal = con.execute("SELECT * FROM redes.cables WHERE proyecto_id = %s AND clase = 'troncal'", (pid,)).fetchone()
    assert troncal["origen_id"] == elementos["OLT 1"]["id"] and troncal["destino_id"] == elementos["MF-9"]["id"] and troncal["hilos"] == 48
    assert [v["elemento_id"] for v in troncal["vertices"]] == [elementos["OLT 1"]["id"], elementos["P1"]["id"], elementos["MF-9"]["id"]]  # the post is anchored
    assert con.execute("SELECT count(*) AS n FROM redes.hilos WHERE cable_id = %s", (troncal["id"],)).fetchone()["n"] == 48
    # the folder stays as it was; a second call makes a second project with another code
    assert len(lugares.arbol(con, admin)["elementos"]) == 8
    r2 = METODOS["lugares_a_proyecto"](con, admin, carpeta_id=f, nombre="Segunda")
    assert r2["proyecto"]["codigo"] != r["proyecto"]["codigo"] and r2["proyecto"]["nombre"] == "Segunda"
    # a reader cannot create projects; a folder with no network is refused
    ajena = _carpeta(con, ana, "De Ana")
    _red(con, ana, ajena, "poste", "P", -86.2, 12.1)
    with pytest.raises(db.SinPermiso):
        METODOS["lugares_a_proyecto"](con, ana, carpeta_id=ajena)
    vacia = _carpeta(con, admin, "Solo marcas")
    lugares.guardar_lugar(con, admin, carpeta_id=vacia, tipo="marca", nombre="M", geom=_punto(-86.3, 12.2))
    with pytest.raises(db.DatosInvalidos):
        METODOS["lugares_a_proyecto"](con, admin, carpeta_id=vacia)


def test_the_network_goes_through_the_kmz_and_back(mundo):
    con, admin, _ = mundo
    f = _carpeta(con, admin, "Para exportar")
    a = _red(con, admin, f, "mufa", "MF-A", -86.25, 12.13, subtipo="reserva")
    b = _red(con, admin, f, "poste", "P-B", -86.25, 12.14, subtipo="madera")
    _cable(con, admin, f, a, b, clase="troncal")
    kmz = lugares_kmz.exportar(con, admin, carpeta_id=f)
    importado = lugares_kmz.importar(con, admin, datos=kmz["datos"], nombre="red.kmz")
    tipos = sorted(e["tipo"] for e in lugares.arbol(con, admin)["elementos"] if e["carpeta_id"] == importado["carpeta_id"])
    assert tipos == ["cable", "mufa", "poste"]
