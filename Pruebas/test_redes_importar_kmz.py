"""Visor v2, fase 5: importar un KMZ a la red (visor_rutas/redes/importar_kmz.py, migración 013) — leer, comparar con el KMZ vigente (con sus
cambios), revisar (aceptar / rechazar), aplicar, revertir la última y publicar en red_puntos / red_lineas (en una base de prueba) y revertirlo."""
import base64
import io
import zipfile

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas import kmz_capas
from visor_rutas.redes import db, importar_kmz, kmz_cambios, usuarios
from visor_rutas.redes.api import METODOS


def _pm(nombre, lon, lat, desc=""):
    return (f"<Placemark><name>{nombre}</name><description>{desc}</description><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>")


def _linea(nombre, *pts):
    c = " ".join(f"{lon},{lat},0" for lon, lat in pts)
    return f"<Placemark><name>{nombre}</name><LineString><coordinates>{c}</coordinates></LineString></Placemark>"


def hacer_kmz(carpetas: dict[str, list[str]], documento="RED") -> bytes:
    cuerpo = "".join(f"<Folder><name>{n}</name>{''.join(pms)}</Folder>" for n, pms in carpetas.items())
    kml = f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{documento}</name>{cuerpo}</Document></kml>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
    return b.getvalue()


def b64(crudo: bytes) -> str:
    return base64.b64encode(crudo).decode("ascii")


RED_ACTUAL = {
    "MUFAS": [_pm("MF UNO", -86.250, 12.130, "Mufa uno"), _pm("MF DOS", -86.260, 12.140), _pm("MF TRES", -86.270, 12.150)],
    "FIBRA OPTICA": [_linea("L1", (-86.250, 12.130), (-86.255, 12.135), (-86.260, 12.140))],
    "POSTES DE CONCRETO": [_pm("P1", -86.251, 12.131), _pm("P2", -86.252, 12.132)],
}


@pytest.fixture(autouse=True)
def _nunca_el_presupuesto_real(monkeypatch):
    """No test can publish into the real budget database: only the `presupuesto` fixture (a throw-away database) replaces this."""
    def prohibido():
        raise AssertionError("conectar_presupuesto sin la base de prueba")
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", prohibido)


@pytest.fixture
def mundo(con_redes, tmp_path, monkeypatch):
    """(con, admin, editor, lector) with the KMZ of RED_ACTUAL as the network in force (its cache built in a temporary folder)."""
    kmz = tmp_path / "red.kmz"
    kmz.write_bytes(hacer_kmz(RED_ACTUAL))
    cache = tmp_path / "datos_kmz"
    kmz_capas.importar(kmz, cache, descargar_iconos=False)
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", cache)
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    editor = usuarios.identificar(con, persona_visor="ed")
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE id = %s", (editor["id"],))
    editor = usuarios.identificar(con, persona_visor="ed")
    lector = usuarios.identificar(con, persona_visor="lec")
    return con, admin, editor, lector


ACTUALIZACION = {
    "MUFAS": [_pm("MF UNO", -86.250, 12.130, "Mufa uno"),                      # no change
              _pm("MF DOS", -86.2603, 12.1403),                                  # moved ~45 m
              _pm("MF TRES RENOMBRADA", -86.270, 12.150),                        # same place, other name
              _pm("MF CUATRO", -86.280, 12.160)],                                # new
    "FIBRA OPTICA": [_linea("L1", (-86.250, 12.130), (-86.256, 12.137), (-86.260, 12.140))],      # same ends, other trace
    "POSTES DE CONCRETO": [_pm("P1", -86.251, 12.131)],                          # P2 is gone
}


def test_the_file_is_read_with_the_folder_paths_of_the_kmz_cache(mundo):
    items = importar_kmz.leer(hacer_kmz(ACTUALIZACION))
    assert len(items) == 6 and {i["ruta"] for i in items} == {"RED/MUFAS", "RED/FIBRA OPTICA", "RED/POSTES DE CONCRETO"}
    assert [i["tipo"] for i in items if i["ruta"] == "RED/FIBRA OPTICA"] == ["linea"]
    con, *_ = mundo
    actuales = importar_kmz.actuales_kmz(con)
    assert {a["ruta"] for a in actuales} == {i["ruta"] for i in items} and len(actuales) == 6
    # the key is the one the page builds: folder | name without accents / case | first point with 5 decimals
    assert importar_kmz.clave_kmz("RED/MUFAS", "  MF Ünó ", 12.13, -86.25) == "RED/MUFAS|mf uno|12.13000,-86.25000"
    assert next(a for a in actuales if a["nombre"] == "MF UNO")["clave"] == "RED/MUFAS|mf uno|12.13000,-86.25000"
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.leer(b"PK\x03\x04roto")


def test_compare_classifies_new_modified_unchanged_and_removed(mundo):
    con, *_ = mundo
    filas, conteos = importar_kmz.comparar(importar_kmz.leer(hacer_kmz(ACTUALIZACION)), importar_kmz.actuales(con))
    assert conteos["por_clase"] == {"nuevo": 1, "modificado": 3, "sin_cambios": 2, "eliminado": 1}
    por_nombre = {f["nombre"]: f for f in filas}
    assert por_nombre["MF CUATRO"]["clase"] == "nuevo" and por_nombre["MF CUATRO"]["aceptado"] is True
    assert por_nombre["MF DOS"]["props"]["cambios"] == ["posicion"] and 30 < por_nombre["MF DOS"]["props"]["dist_m"] < 60
    assert por_nombre["MF TRES RENOMBRADA"]["props"]["cambios"] == ["nombre"] and por_nombre["MF TRES RENOMBRADA"]["props"]["nombre_actual"] == "MF TRES"
    assert por_nombre["L1"]["props"]["cambios"] == ["trazo"]
    assert por_nombre["P2"]["clase"] == "eliminado" and por_nombre["P2"]["aceptado"] is False                # removed ones are never accepted by default
    assert "MF UNO" not in por_nombre and "P1" not in por_nombre                                          # unchanged: only counted
    assert conteos["por_tipo"]["punto"]["nuevo"] == 1 and conteos["carpetas"]["RED/MUFAS"]["modificado"] == 2
    # a different description is a change too, a same name in another folder is not the same element
    otra = {"MUFAS": [_pm("MF UNO", -86.250, 12.130, "Mufa uno CAMBIADA")], "OTRA": [_pm("MF DOS", -86.260, 12.140)]}
    f2, c2 = importar_kmz.comparar(importar_kmz.leer(hacer_kmz(otra)), importar_kmz.actuales(con))
    assert {f["nombre"]: f["props"].get("cambios") for f in f2 if f["clase"] != "eliminado"} == {"MF UNO": ["descripcion"], "MF DOS": None}


def test_the_mode_is_suggested_from_how_much_of_the_file_is_already_in_the_network(mundo):
    con, admin, *_ = mundo
    r = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ACTUALIZACION)), nombre="red_nueva.kmz")["importacion"]
    assert (r["modo"], r["modo_sugerido"], r["estado"]) == ("actualizacion", "actualizacion", "pendiente") and r["archivo"] == "red_nueva.kmz"
    ruta_nueva = {"POSTES DE CONCRETO": [_pm("N1", -86.5, 12.5), _pm("N2", -86.501, 12.501)]}
    n = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ruta_nueva)), nombre="ruta.kmz")["importacion"]
    assert n["modo"] == "nueva" and n["conteos"]["por_clase"]["nuevo"] == 2
    forzado = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ruta_nueva)), nombre="ruta.kmz", modo="actualizacion")["importacion"]
    assert forzado["modo"] == "actualizacion" and forzado["modo_sugerido"] == "nueva" and forzado["conteos"]["avisos"]     # it would remove the whole network
    assert [i["id"] for i in importar_kmz.listar(con, admin)["importaciones"]] == [forzado["id"], n["id"], r["id"]]


def test_review_filters_accepts_and_rejects(mundo):
    con, admin, *_ = mundo
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ACTUALIZACION)), nombre="a.kmz")["importacion"]
    todo = importar_kmz.detalle(con, admin, id=imp["id"])
    assert todo["total"] == 5 and todo["aceptados"] == 4                                                  # the removed one is not accepted yet
    assert [f["nombre"] for f in importar_kmz.detalle(con, admin, id=imp["id"], clase="modificado", carpeta="RED/MUFAS")["filas"]] == ["MF DOS", "MF TRES RENOMBRADA"]
    assert [f["nombre"] for f in importar_kmz.detalle(con, admin, id=imp["id"], texto="cuatro")["filas"]] == ["MF CUATRO"]
    m = importar_kmz.mapa(con, admin, id=imp["id"], clase="nuevo")
    assert [e["clase"] for e in m["elementos"]] == ["nuevo"] and m["elementos"][0]["geom"]["type"] == "Point" and m["truncado"] is False
    r = importar_kmz.aceptar(con, admin, id=imp["id"], aceptado=False, clase="modificado")
    assert r["cambiados"] == 3
    r = importar_kmz.aceptar(con, admin, id=imp["id"], aceptado=True, ids=[next(f["id"] for f in todo["filas"] if f["nombre"] == "P2")])
    assert r["cambiados"] == 1 and importar_kmz.detalle(con, admin, id=imp["id"], aceptado=True)["total"] == 2
    # «nueva» mode hides the removed ones everywhere
    importar_kmz.cambiar_modo(con, admin, id=imp["id"], modo="nueva")
    assert importar_kmz.detalle(con, admin, id=imp["id"])["total"] == 4 and importar_kmz.detalle(con, admin, id=imp["id"], clase="eliminado")["total"] == 0
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.cambiar_modo(con, admin, id=imp["id"], modo="otro")


def test_apply_changes_the_network_in_force_and_importing_the_same_file_again_finds_nothing_new(mundo):
    con, admin, editor, _ = mundo
    imp = importar_kmz.importar(con, editor, datos=b64(hacer_kmz(ACTUALIZACION)), nombre="a.kmz")["importacion"]
    importar_kmz.aceptar(con, editor, id=imp["id"], aceptado=True, clase="eliminado")
    r = importar_kmz.aplicar(con, editor, id=imp["id"])
    assert r["aplicados"] == {"nuevo": 1, "modificado": 3, "eliminado": 1} and r["importacion"]["estado"] == "aplicada"
    cambios = {c["clave"]: c for c in kmz_cambios.listar(con, editor)["cambios"]}
    assert len(cambios) == 4 and cambios["RED/MUFAS|mf dos|12.14000,-86.26000"]["despues"]["lon"] == -86.2603
    assert cambios["RED/MUFAS|mf tres|12.15000,-86.27000"]["despues"]["nombre"] == "MF TRES RENOMBRADA"
    assert cambios["RED/POSTES DE CONCRETO|p2|12.13200,-86.25200"]["accion"] == "borrar"
    assert cambios["RED/FIBRA OPTICA|l1|12.13000,-86.25000"]["despues"]["coords"][1] == [-86.256, 12.137]
    vigentes = importar_kmz.actuales(con)
    assert sorted(a["nombre"] for a in vigentes) == ["L1", "MF CUATRO", "MF DOS", "MF TRES RENOMBRADA", "MF UNO", "P1"]         # P2 gone, MF CUATRO in
    assert [e["nombre"] for e in importar_kmz.capa(con, editor)["elementos"]] == ["MF CUATRO"]
    # the same file again: everything is already in the network
    otra = importar_kmz.importar(con, editor, datos=b64(hacer_kmz(ACTUALIZACION)), nombre="a2.kmz")["importacion"]
    assert otra["conteos"]["por_clase"] == {"nuevo": 0, "modificado": 0, "sin_cambios": 6, "eliminado": 0}
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.aplicar(con, editor, id=imp["id"])                                                  # already applied
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.aplicar(con, editor, id=otra["id"])                                                 # nothing accepted to apply


def test_revert_undoes_the_last_applied_import_and_keeps_what_was_there_before(mundo):
    con, admin, *_ = mundo
    # someone renamed MF DOS in the viewer before the import
    kmz_cambios.editar(con, admin, clave="RED/MUFAS|mf dos|12.14000,-86.26000", carpeta="RED/MUFAS", tipo="punto",
                       antes={"nombre": "MF DOS", "lat": 12.14, "lon": -86.26}, nombre="MF DOS (A MANO)")
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz({"MUFAS": [_pm("MF DOS (A MANO)", -86.2603, 12.1403), _pm("MF NUEVA", -86.9, 12.9)]})), nombre="b.kmz")
    id1 = imp["importacion"]["id"]
    assert imp["importacion"]["conteos"]["por_clase"]["modificado"] == 1
    importar_kmz.aplicar(con, admin, id=id1)
    despues = {c["clave"]: c for c in kmz_cambios.listar(con, admin)["cambios"]}["RED/MUFAS|mf dos|12.14000,-86.26000"]
    assert despues["despues"]["nombre"] == "MF DOS (A MANO)" and despues["despues"]["lon"] == -86.2603
    segunda = importar_kmz.importar(con, admin, datos=b64(hacer_kmz({"MUFAS": [_pm("MF OTRA", -86.7, 12.7)]})), nombre="c.kmz")["importacion"]["id"]
    importar_kmz.aplicar(con, admin, id=segunda)
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.revertir(con, admin, id=id1)                                                         # only the last one
    importar_kmz.revertir(con, admin, id=segunda)
    assert [e["nombre"] for e in importar_kmz.capa(con, admin)["elementos"]] == ["MF NUEVA"]
    importar_kmz.revertir(con, admin, id=id1)
    antes = {c["clave"]: c for c in kmz_cambios.listar(con, admin)["cambios"]}["RED/MUFAS|mf dos|12.14000,-86.26000"]
    assert antes["despues"] == {"nombre": "MF DOS (A MANO)", "lat": 12.14, "lon": -86.26} and importar_kmz.capa(con, admin)["elementos"] == []     # as it was
    assert [i["estado"] for i in importar_kmz.listar(con, admin)["importaciones"]] == ["revertida", "revertida"]
    # a reverted import cannot be applied or discarded; a pending one can be discarded
    pendiente = importar_kmz.importar(con, admin, datos=b64(hacer_kmz({"MUFAS": [_pm("MF X", -86.1, 12.1)]})), nombre="d.kmz")["importacion"]["id"]
    importar_kmz.descartar(con, admin, id=pendiente)
    with pytest.raises(db.NoEncontrado if False else db.DatosInvalidos):
        importar_kmz.descartar(con, admin, id=id1)


def test_permissions(mundo):
    con, admin, editor, lector = mundo
    datos = b64(hacer_kmz(ACTUALIZACION))
    with pytest.raises(db.SinPermiso):
        importar_kmz.importar(con, lector, datos=datos, nombre="x.kmz")
    imp = importar_kmz.importar(con, editor, datos=datos, nombre="x.kmz")["importacion"]
    with pytest.raises(db.SinPermiso):
        METODOS["aplicar_importacion_kmz"](con, lector, id=imp["id"])
    importar_kmz.aplicar(con, editor, id=imp["id"])
    with pytest.raises(db.SinPermiso):
        importar_kmz.publicar(con, editor, id=imp["id"])                                                   # only administrators publish
    for malo in ("", "no es base64 !!", b64(b"")):
        with pytest.raises(db.DatosInvalidos):
            importar_kmz.importar(con, admin, datos=malo, nombre="x.kmz")
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.importar(con, admin, datos=datos, nombre="x.kmz", modo="otro")
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.importar(con, admin, datos=b64(hacer_kmz({"VACIA": []})), nombre="x.kmz")


# --------------------------------------------------------------------------- publicar en PostGIS

@pytest.fixture
def presupuesto(base_redes, con_redes, monkeypatch):
    """red_puntos / red_lineas in a test database (the budget's tables) and importar_kmz pointed at it."""
    _, params = base_redes
    pg = db.conectar(params=params)
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.execute("CREATE TABLE public.red_puntos (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    pg.execute("CREATE TABLE public.red_lineas (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    pg.execute("INSERT INTO public.red_puntos (tabla_origen, categoria, nombre, geom, tipo) VALUES "
               "('mufa', 'mufa', 'MF UNO', ST_SetSRID(ST_MakePoint(-86.250, 12.130), 4326), 'mufa'),"
               "('mufa', 'mufa', 'MF DOS', ST_SetSRID(ST_MakePoint(-86.260, 12.140), 4326), 'mufa'),"
               "('mufa', 'mufa', 'MF TRES', ST_SetSRID(ST_MakePoint(-86.270, 12.150), 4326), 'mufa'),"
               "('postes de concreto', 'postes de concreto', 'P1', ST_SetSRID(ST_MakePoint(-86.251, 12.131), 4326), 'poste de concreto'),"
               "('postes de concreto', 'postes de concreto', 'P2', ST_SetSRID(ST_MakePoint(-86.252, 12.132), 4326), 'poste de concreto')")
    pg.execute("INSERT INTO public.red_lineas (tabla_origen, categoria, nombre, geom, tipo) VALUES "
               "('fibra optica', 'fibra optica', 'L1', ST_SetSRID(ST_GeomFromText('LINESTRING(-86.250 12.130, -86.255 12.135, -86.260 12.140)'), 4326), 'fibra óptica')")
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", lambda: db.conectar(params=params))
    yield pg
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.close()


def _filas(pg, tabla):
    return {f["nombre"]: f for f in pg.execute(f"SELECT id, tabla_origen, categoria, nombre, tipo, ST_X(ST_StartPoint(ST_LineMerge(geom))) AS x_linea, ST_AsText(geom) AS wkt FROM public.{tabla}").fetchall()} \
        if tabla == "red_lineas" else {f["nombre"]: f for f in pg.execute("SELECT id, tabla_origen, categoria, nombre, tipo, ST_AsText(geom) AS wkt FROM public.red_puntos").fetchall()}


def test_publish_inserts_updates_deletes_in_the_budget_tables_and_reverts_exactly(mundo, presupuesto):
    con, admin, *_ = mundo
    pg = presupuesto
    antes_p, antes_l = _filas(pg, "red_puntos"), _filas(pg, "red_lineas")
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ACTUALIZACION)), nombre="a.kmz")["importacion"]
    importar_kmz.aceptar(con, admin, id=imp["id"], aceptado=True, clase="eliminado")
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.publicar(con, admin, id=imp["id"])                                                    # apply first
    importar_kmz.aplicar(con, admin, id=imp["id"])
    r = importar_kmz.publicar(con, admin, id=imp["id"])
    assert r["resumen"]["insertados"] == 1 and r["resumen"]["modificados"] == 3 and r["resumen"]["eliminados"] == 1
    assert r["resumen"]["no_encontrados"] == [] and r["resumen"]["sin_categoria"] == [] and r["importacion"]["publicada"] is True
    puntos = _filas(pg, "red_puntos")
    assert set(puntos) == {"MF UNO", "MF DOS", "MF TRES RENOMBRADA", "MF CUATRO", "P1"}                       # P2 deleted, MF TRES renamed, MF CUATRO added
    assert (puntos["MF CUATRO"]["tabla_origen"], puntos["MF CUATRO"]["categoria"], puntos["MF CUATRO"]["tipo"]) == ("visor", "mufa", "mufa")   # the budget sees it as a mufa
    assert puntos["MF DOS"]["wkt"] == "POINT(-86.2603 12.1403)"
    assert "-86.256 12.137" in _filas(pg, "red_lineas")["L1"]["wkt"]
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.publicar(con, admin, id=imp["id"])
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.revertir(con, admin, id=imp["id"])                                                    # revert the publication first
    importar_kmz.revertir_publicacion(con, admin, id=imp["id"])
    assert _filas(pg, "red_puntos") == antes_p and _filas(pg, "red_lineas") == antes_l                       # exactly as it was, ids included
    assert importar_kmz.listar(con, admin)["importaciones"][0]["publicada"] is False
    importar_kmz.revertir(con, admin, id=imp["id"])                                                         # now it can be reverted


def test_publish_reports_what_it_cannot_place_and_leaves_the_rest(mundo, presupuesto):
    con, admin, *_ = mundo
    pg = presupuesto
    pg.execute("DELETE FROM public.red_puntos WHERE nombre = 'MF DOS'")                                     # the budget's table does not have it
    archivo = {"MUFAS": [_pm("MF DOS", -86.2603, 12.1403), _pm("MF NUEVA", -86.9, 12.9)], "ZONA DESCONOCIDA": [_pm("X", -86.8, 12.8)]}
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(archivo)), nombre="b.kmz")["importacion"]
    importar_kmz.aplicar(con, admin, id=imp["id"])
    r = importar_kmz.publicar(con, admin, id=imp["id"])["resumen"]
    assert r["insertados"] == 1 and r["no_encontrados"] == ["MF DOS"] and r["sin_categoria"] == ["ZONA DESCONOCIDA"] and r["modificados"] == 0
    assert set(_filas(pg, "red_puntos")) == {"MF UNO", "MF TRES", "P1", "P2", "MF NUEVA"}
    assert importar_kmz.categoria_para("RED/POSTES DE MADERA", "red_puntos", {}) == ("postes de madera", "poste de madera")
    assert importar_kmz.categoria_para("RED/MUFAS SIN INFO", "red_puntos", {}) == ("mufa", "mufa")
    assert importar_kmz.categoria_para("RED/FIBRA", "red_lineas", {}) is None
