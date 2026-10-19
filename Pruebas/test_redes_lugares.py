"""Visor v2, fase 3: Mis lugares (visor_rutas/redes/lugares.py, lugares_kmz.py, lugares_iconos.py) — carpetas y elementos propios,
geometría y estilo validados, orden manual, permisos y compartir, descripciones con imágenes, y KMZ de ida y vuelta."""
import base64
import io
import re
import zipfile

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, lugares, lugares_iconos, lugares_kmz, usuarios
from visor_rutas.redes.api import METODOS

PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _punto(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def _linea(*pts):
    return {"type": "LineString", "coordinates": [list(p) for p in pts]}


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    ana = usuarios.identificar(con, persona_visor="ana")                      # created on first use, as a reader
    luis = usuarios.identificar(con, persona_visor="luis")
    return con, admin, ana, luis


def _carpeta(con, actor, nombre, padre=None):
    arbol = lugares.guardar_carpeta(con, actor, nombre=nombre, padre_id=padre)
    return arbol["id"], arbol


def _marca(con, actor, carpeta, nombre="Marca", lon=-86.3, lat=12.1, **kw):
    return lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="marca", nombre=nombre, geom=_punto(lon, lat), **kw)["lugar"]


def test_folders_and_elements_roundtrip_with_geometry_style_and_view(mundo):
    con, admin, *_ = mundo
    raiz, _ = _carpeta(con, admin, "  Trabajo   de   campo ")
    sub, arbol = _carpeta(con, admin, "Ruta norte", raiz)
    assert [c["nombre"] for c in arbol["carpetas"]] == ["Trabajo de campo", "Ruta norte"]        # spaces collapsed
    m = _marca(con, admin, sub, "Cliente Pérez", estilo={"icono": {"tipo": "letra", "id": "A", "color": "#E53935", "escala": 9, "opacidad": 2},
                                                       "etiqueta": {"color": "#ffffff", "escala": 1.2}, "basura": 1},
               vista={"lat": 12.1, "lon": -86.3, "zoom": 17.4}, descripcion_html="<p>Casa <b>azul</b><script>alert(1)</script></p>")
    assert m["estilo"]["icono"] == {"tipo": "letra", "id": "A", "color": "#E53935", "escala": 4.0, "opacidad": 1.0}     # clamped
    assert "basura" not in m["estilo"] and m["vista"] == {"lat": 12.1, "lon": -86.3, "zoom": 17.4}
    assert m["descripcion_html"] == "<p>Casa <b>azul</b></p>" and m["geom"] == {"type": "Point", "coordinates": [-86.3, 12.1]}
    r = lugares.guardar_lugar(con, admin, carpeta_id=sub, tipo="ruta", nombre="Tramo", geom=_linea((-86.3, 12.1), (-86.31, 12.11), (-86.32, 12.12)),
                              estilo={"linea": {"color": "#00ff00", "grosor": 50, "opacidad": 0.5}})["lugar"]
    assert r["estilo"]["linea"] == {"color": "#00ff00", "grosor": 20.0, "opacidad": 0.5}
    anillo = [[-86.3, 12.1], [-86.31, 12.1], [-86.31, 12.11]]                                      # an open ring is closed
    p = lugares.guardar_lugar(con, admin, carpeta_id=sub, tipo="poligono", nombre="Zona", geom={"type": "Polygon", "coordinates": [anillo]})["lugar"]
    assert p["geom"]["coordinates"][0][0] == p["geom"]["coordinates"][0][-1] and len(p["geom"]["coordinates"][0]) == 4
    arbol = lugares.arbol(con, admin)
    assert {e["tipo"] for e in arbol["elementos"]} == {"marca", "ruta", "poligono"}
    assert all("descripcion_html" not in e for e in arbol["elementos"])                              # the tree is light
    # update with the version: rename, move the pin; a stale version is a conflict
    n = lugares.guardar_lugar(con, admin, id=m["id"], nombre="Cliente Pérez 2", geom=_punto(-86.4, 12.2), version=m["version"])["lugar"]
    assert (n["nombre"], n["geom"]["coordinates"], n["version"]) == ("Cliente Pérez 2", [-86.4, 12.2], m["version"] + 1)
    with pytest.raises(db.ConflictoVersion):
        lugares.guardar_lugar(con, admin, id=m["id"], nombre="otra", version=m["version"])
    c = lugares.guardar_carpeta(con, admin, id=sub, nombre="Ruta sur", version=arbol["carpetas"][1]["version"])
    assert "Ruta sur" in [x["nombre"] for x in c["carpetas"]]
    historial = con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad IN ('lugar', 'lugar_carpeta')").fetchone()["n"]
    assert historial >= 7


def test_geometry_and_names_are_validated(mundo):
    con, admin, *_ = mundo
    f, _ = _carpeta(con, admin, "F")
    for tipo, geo in (("marca", _linea((-86, 12), (-86.1, 12.1))), ("ruta", _linea((-86, 12))), ("ruta", _punto(-86, 12)),
                      ("poligono", {"type": "Polygon", "coordinates": [[[-86, 12], [-86.1, 12.1]]]}), ("marca", _punto(-86, 95)),
                      ("marca", _punto("x", 12)), ("marca", None), ("raro", _punto(-86, 12))):
        with pytest.raises(db.DatosInvalidos):
            lugares.guardar_lugar(con, admin, carpeta_id=f, tipo=tipo, nombre="x", geom=geo)
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_lugar(con, admin, carpeta_id=f, tipo="marca", nombre="   ", geom=_punto(-86, 12))
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_carpeta(con, admin, nombre="  ")
    # the type is not changed by an update: the geometry must stay of its kind
    m = _marca(con, admin, f)
    with pytest.raises(db.DatosInvalidos):
        lugares.guardar_lugar(con, admin, id=m["id"], geom=_linea((-86, 12), (-86.1, 12.1)), version=m["version"])


def test_manual_order_move_and_cycles(mundo):
    con, admin, *_ = mundo
    a, _ = _carpeta(con, admin, "A")
    b, _ = _carpeta(con, admin, "B")
    c, _ = _carpeta(con, admin, "C", a)
    m1, m2 = _marca(con, admin, a, "m1"), _marca(con, admin, a, "m2")
    nombres = lambda arbol, carpeta: [x["nombre"] for x in sorted(
        [*(k for k in arbol["carpetas"] if k["padre_id"] == carpeta), *(e for e in arbol["elementos"] if e["carpeta_id"] == carpeta)], key=lambda x: x["orden"])]
    assert nombres(lugares.arbol(con, admin), a) == ["C", "m1", "m2"]
    # m2 before the subfolder C, in the same folder
    arbol = lugares.mover(con, admin, items=[{"tipo": "lugar", "id": m2["id"]}], destino_id=a, antes_de={"tipo": "carpeta", "id": c})
    assert nombres(arbol, a) == ["m2", "C", "m1"]
    # m1 into B, C into B before nothing (end)
    arbol = lugares.mover(con, admin, items=[{"tipo": "lugar", "id": m1["id"]}, {"tipo": "carpeta", "id": c}], destino_id=b)
    assert nombres(arbol, b) == ["C", "m1"] or nombres(arbol, b) == ["m1", "C"]
    assert nombres(arbol, a) == ["m2"]
    # a folder cannot go inside itself or its own child; an element cannot go to the root
    with pytest.raises(db.DatosInvalidos):
        lugares.mover(con, admin, items=[{"tipo": "carpeta", "id": b}], destino_id=c)
    with pytest.raises(db.DatosInvalidos):
        lugares.mover(con, admin, items=[{"tipo": "carpeta", "id": b}], destino_id=b)
    with pytest.raises(db.DatosInvalidos):
        lugares.mover(con, admin, items=[{"tipo": "lugar", "id": m1["id"]}], destino_id=None)
    arbol = lugares.mover(con, admin, items=[{"tipo": "carpeta", "id": c}], destino_id=None)           # a subfolder becomes a root folder
    assert next(k for k in arbol["carpetas"] if k["id"] == c)["padre_id"] is None


def test_visibility_boxes_and_deleting(mundo):
    con, admin, *_ = mundo
    a, _ = _carpeta(con, admin, "A")
    b, _ = _carpeta(con, admin, "B", a)
    m1, m2 = _marca(con, admin, a, "m1"), _marca(con, admin, b, "m2")
    r = lugares.visibilidad(con, admin, carpetas=[a], visible=False)
    assert set(r["elementos"]) == {m1["id"], m2["id"]} and set(r["carpetas"]) == {a, b}
    assert {e["visible"] for e in lugares.arbol(con, admin)["elementos"]} == {False}
    lugares.visibilidad(con, admin, elementos=[m2["id"]], visible=True)
    assert {e["id"]: e["visible"] for e in lugares.arbol(con, admin)["elementos"]} == {m1["id"]: False, m2["id"]: True}
    # delete a folder: its subfolders and elements go with it (logical delete: still in the table)
    arbol = lugares.eliminar_carpeta(con, admin, id=a)
    assert arbol["carpetas"] == [] and arbol["elementos"] == []
    assert con.execute("SELECT count(*) AS n FROM redes.lugares_elementos WHERE borrado_en IS NOT NULL").fetchone()["n"] == 2
    with pytest.raises(db.NoEncontrado):
        lugares.obtener(con, admin, id=m1["id"])
    f, _ = _carpeta(con, admin, "F")
    z = _marca(con, admin, f, "z")
    lugares.eliminar_lugar(con, admin, id=z["id"])
    assert lugares.arbol(con, admin)["elementos"] == []


def test_permissions_and_sharing(mundo):
    con, admin, ana, luis = mundo
    f, _ = _carpeta(con, admin, "Privada")
    sub, _ = _carpeta(con, admin, "Dentro", f)
    m = _marca(con, admin, sub, "secreto")
    # nobody else sees it, not even an administrator's data to a reader
    for otro in (ana, luis):
        assert lugares.arbol(con, otro) == {"carpetas": [], "elementos": []}
        with pytest.raises(db.NoEncontrado):
            lugares.obtener(con, otro, id=m["id"])
        with pytest.raises(db.NoEncontrado):
            lugares.guardar_lugar(con, otro, carpeta_id=f, tipo="marca", nombre="x", geom=_punto(-86, 12))
    # share with Ana read-only and with Luis for editing; subfolders come with it
    comp = lugares.compartir(con, admin, carpeta_id=f, compartir_con=[{"usuario_id": ana["id"], "puede_editar": False},
                                                                      {"usuario_id": luis["id"], "puede_editar": True},
                                                                      {"usuario_id": admin["id"], "puede_editar": True}])["compartidos"]
    assert {(c["nombre"], c["puede_editar"]) for c in comp} == {("ana", False), ("luis", True)}                  # the owner is not listed
    a_arbol = lugares.arbol(con, ana)
    assert {c["nombre"] for c in a_arbol["carpetas"]} == {"Privada", "Dentro"} and len(a_arbol["elementos"]) == 1
    privada = next(c for c in a_arbol["carpetas"] if c["nombre"] == "Privada")
    assert (privada["propia"], privada["puede_editar"], privada["raiz_compartida"], privada["padre_id"]) == (False, False, True, None)
    assert lugares.obtener(con, ana, id=m["id"])["lugar"]["puede_editar"] is False
    with pytest.raises(db.SinPermiso):                                                                       # read only
        lugares.guardar_lugar(con, ana, id=m["id"], nombre="x", version=m["version"])
    with pytest.raises(db.SinPermiso):
        lugares.eliminar_carpeta(con, ana, id=sub)
    # Luis edits; what he creates inside belongs to the owner
    nuevo = lugares.guardar_lugar(con, luis, carpeta_id=sub, tipo="marca", nombre="de Luis", geom=_punto(-86.2, 12.2))["lugar"]
    assert con.execute("SELECT usuario_id FROM redes.lugares_carpetas WHERE id = %s", (sub,)).fetchone()["usuario_id"] == admin["id"]
    assert {e["nombre"] for e in lugares.arbol(con, admin)["elementos"]} == {"secreto", "de Luis"}
    lugares.guardar_lugar(con, luis, id=nuevo["id"], nombre="de Luis 2", version=nuevo["version"])
    # only the owner shares, moves a shared root or sets its visibility boxes; moving across owners is refused
    with pytest.raises(db.SinPermiso):
        lugares.compartir(con, luis, carpeta_id=f, compartir_con=[])
    with pytest.raises(db.SinPermiso):
        lugares.eliminar_carpeta(con, luis, id=f)
    propia, _ = _carpeta(con, luis, "Mía de Luis")
    with pytest.raises(db.DatosInvalidos):
        lugares.mover(con, luis, items=[{"tipo": "lugar", "id": nuevo["id"]}], destino_id=propia)
    assert lugares.visibilidad(con, luis, carpetas=[f], visible=False)["carpetas"] == []                     # not his own: nothing changes
    # stop sharing
    lugares.compartir(con, admin, carpeta_id=f, compartir_con=[])
    assert lugares.arbol(con, ana) == {"carpetas": [], "elementos": []}
    # a deactivated user is refused before any of this (identificar), so nothing to test here beyond the shares being data


def test_description_images_are_stored_apart_and_checked(mundo):
    con, admin, ana, _ = mundo
    f, _ = _carpeta(con, admin, "F")
    cuerpo = '<p>Foto: <img data-nuevo="t1" src="data:image/png;base64,AAAA"> y <img src="http://malo/x.png" onerror="x()"> <a href="javascript:alert(1)">x</a></p>'
    m = _marca(con, admin, f, "con foto", descripcion_html=cuerpo, imagenes=[{"ref": "t1", "nombre": "pared.png", "datos": base64.b64encode(PNG_1X1).decode()}])
    assert len(m["adjuntos"]) == 1 and m["adjuntos"][0]["nombre"] == "pared.png"
    aid = m["adjuntos"][0]["id"]
    assert m["descripcion_html"] == f'<p>Foto: <img data-adj="{aid}"> y  x</p>'              # the web image and the script link are gone
    img = lugares.adjunto(con, admin, id=aid)["adjunto"]
    assert (img["tipo"], base64.b64decode(img["datos"])) == ("image/png", PNG_1X1)
    with pytest.raises(db.NoEncontrado):                                                       # another user cannot read it
        lugares.adjunto(con, ana, id=aid)
    # editing keeps an existing image only if the HTML still has it; the others are dropped
    n = lugares.guardar_lugar(con, admin, id=m["id"], descripcion_html=f'<p>Sigue <img data-adj="{aid}"></p><p><img data-adj="99999"></p>', version=m["version"])["lugar"]
    assert n["descripcion_html"] == f'<p>Sigue <img data-adj="{aid}"></p><p></p>' and len(n["adjuntos"]) == 1
    n = lugares.guardar_lugar(con, admin, id=m["id"], descripcion_html="<p>Sin foto</p>", version=n["version"])["lugar"]
    assert n["adjuntos"] == []
    # bad images are refused
    for datos in (base64.b64encode(b"no soy una imagen").decode(), base64.b64encode(PNG_1X1 + b"0" * (3 * 1024 * 1024)).decode(), "###"):
        with pytest.raises(db.DatosInvalidos):
            _marca(con, admin, f, "mala", descripcion_html='<img data-nuevo="x">', imagenes=[{"ref": "x", "nombre": "a.png", "datos": datos}])


def test_icons_png_and_cleaning():
    for ic in ({"tipo": "pushpin", "color": "#f7d117"}, {"tipo": "letra", "id": "Z", "color": "#e53935"}, {"tipo": "numero", "id": "10", "color": "#ffffff"},
               *({"tipo": "figura", "id": f, "color": "#2f6bff", "opacidad": 0.5} for f in lugares_iconos.FIGURAS)):
        png = lugares_iconos.icono_png(ic)
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 80, ic
    assert lugares_iconos.limpiar_icono({"tipo": "letra", "id": "AA"}) is None and lugares_iconos.limpiar_icono({"tipo": "figura", "id": "x"}) is None
    assert lugares_iconos.limpiar_icono({"tipo": "pushpin", "color": "rojo"})["color"] == lugares_iconos.COLOR_POR_DEFECTO
    assert lugares_iconos.desde_href("http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png")["color"] == "#e53935"
    assert lugares_iconos.desde_href("files/icono.png") is None


def test_kmz_roundtrip_keeps_everything(mundo):
    con, admin, ana, _ = mundo
    raiz, _ = _carpeta(con, admin, "Visita Nandaime")
    sub, _ = _carpeta(con, admin, "Postes", raiz)
    m = _marca(con, admin, sub, "Poste 1 <b>&</b>", estilo={"icono": {"tipo": "numero", "id": "7", "color": "#2f6bff", "escala": 1.5, "opacidad": 1},
                                                          "etiqueta": {"color": "#ffff00", "escala": 1.2, "visible": True}},
               vista={"lat": 12.1, "lon": -86.3, "zoom": 18}, descripcion_html='<p>Hay <b>un cable</b> <img data-nuevo="a"></p>',
               imagenes=[{"ref": "a", "nombre": "f.png", "datos": base64.b64encode(PNG_1X1).decode()}])
    lugares.guardar_lugar(con, admin, carpeta_id=raiz, tipo="ruta", nombre="Camino", geom=_linea((-86.3, 12.1), (-86.31, 12.11)),
                          estilo={"linea": {"color": "#ff0000", "grosor": 5, "opacidad": 0.5}})
    lugares.guardar_lugar(con, admin, carpeta_id=raiz, tipo="poligono", nombre="Lote", geom={"type": "Polygon", "coordinates": [[[-86.3, 12.1], [-86.31, 12.1], [-86.31, 12.11]]]},
                          estilo={"linea": {"color": "#00ff00", "grosor": 2, "opacidad": 1}, "relleno": {"activo": False, "color": "#0000ff", "opacidad": 0.4}})
    lugares.guardar_lugar(con, admin, carpeta_id=raiz, tipo="mufa", nombre="MF Nueva", geom=_punto(-86.35, 12.15),       # a network element of phase 4
                          propiedades={"subtipo": "empalme", "capacidad": 48})
    e = lugares_kmz.exportar(con, admin, carpeta_id=raiz)
    assert e["tipo"] == "kmz" and e["resumen"] == {"carpetas": 2, "lugares": 4}
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(e["datos"])))
    nombres = z.namelist()
    kml = z.read("doc.kml").decode("utf-8")
    assert any(n.startswith("files/numero-7-2f6bff") and n.endswith(".png") for n in nombres)             # the icon of the pin is in the file
    assert any(re.fullmatch(r"files/adj_\d+\.png", n) for n in nombres)                                    # and the image of the description
    assert "<name>Poste 1 &lt;b&gt;&amp;&lt;/b&gt;</name>" in kml and "<LookAt>" in kml and "ideay_tipo" in kml
    assert "<Polygon>" in kml and "<LineString>" in kml and kml.count("<Folder>") == 2                      # Document > Folder(root) > Folder(sub)
    # importing it again (into another folder) gives the same
    destino, _ = _carpeta(con, admin, "Importadas")
    r = lugares_kmz.importar(con, admin, datos=e["datos"], nombre="Visita.kmz", carpeta_id=destino)
    assert r["importados"] == {"carpetas": 2, "lugares": 4, "omitidos": 0}
    nueva = next(c for c in r["carpetas"] if c["id"] == r["carpeta_id"])
    assert (nueva["nombre"], nueva["padre_id"]) == ("Visita Nandaime", destino)
    por_nombre = {x["nombre"]: x for x in r["elementos"] if x["carpeta_id"] in {c["id"] for c in r["carpetas"] if c["id"] != destino}}
    assert set(por_nombre) == {"Poste 1 <b>&</b>", "Camino", "Lote", "MF Nueva"}
    p = por_nombre["Poste 1 <b>&</b>"]
    assert p["estilo"]["icono"] == {"tipo": "numero", "id": "7", "color": "#2f6bff", "escala": 1.5, "opacidad": 1.0}
    assert p["estilo"]["etiqueta"]["color"] == "#ffff00" and p["vista"]["zoom"] == pytest.approx(18, abs=0.2)
    full = lugares.obtener(con, admin, id=p["id"])["lugar"]
    assert len(full["adjuntos"]) == 1 and re.fullmatch(r'<p>Hay <b>un cable</b> <img data-adj="\d+"></p>', full["descripcion_html"])
    assert lugares.adjunto(con, admin, id=full["adjuntos"][0]["id"])["adjunto"]["tipo"] == "image/png"
    assert por_nombre["Camino"]["estilo"]["linea"] == {"color": "#ff0000", "grosor": 5.0, "opacidad": 0.5}
    assert por_nombre["Lote"]["estilo"]["relleno"] == {"activo": False, "color": "#0000ff", "opacidad": 0.4}
    assert (por_nombre["MF Nueva"]["tipo"], por_nombre["MF Nueva"]["propiedades"]) == ("mufa", {"subtipo": "empalme", "capacidad": 48})
    # a folder somebody shared with you can be exported by you, not one you cannot see
    with pytest.raises(db.NoEncontrado):
        lugares_kmz.exportar(con, ana, carpeta_id=raiz)


def test_import_google_earth_kml_and_bad_files(mundo):
    con, admin, *_ = mundo
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://earth.google.com/kml/2.1"><Document><name>Mi viaje</name>
 <StyleMap id="m"><Pair><key>normal</key><styleUrl>#n</styleUrl></Pair></StyleMap>
 <Style id="n"><IconStyle><scale>1.3</scale><Icon><href>http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png</href></Icon></IconStyle>
  <LineStyle><color>ff0000ff</color><width>4</width></LineStyle></Style>
 <Folder><name>Día 1</name>
  <Placemark><name>Hotel</name><description><![CDATA[<b>Cuarto 3</b><script>x()</script>]]></description><styleUrl>#m</styleUrl><Point><coordinates>-86.25,12.13,0</coordinates></Point></Placemark>
  <Placemark><name>Camino</name><styleUrl>#n</styleUrl><LineString><coordinates>-86.25,12.13,0 -86.26,12.14,0</coordinates></LineString></Placemark>
  <Placemark><name>Sin forma</name></Placemark>
 </Folder>
 <Placemark><name>Suelto</name><Point><coordinates>-86.2,12.1</coordinates></Point></Placemark>
</Document></kml>"""
    r = lugares_kmz.importar(con, admin, datos=base64.b64encode(kml.encode()).decode(), nombre="viaje.kml")
    assert r["importados"] == {"carpetas": 2, "lugares": 3, "omitidos": 1} and r["omitidos"] == ["Sin forma"]
    por = {e["nombre"]: e for e in r["elementos"]}
    assert por["Hotel"]["estilo"]["icono"]["color"] == "#e53935" and por["Hotel"]["estilo"]["icono"]["escala"] == 1.3        # Google's red pushpin
    assert por["Camino"]["estilo"]["linea"] == {"color": "#ff0000", "opacidad": 1.0, "grosor": 4.0}                          # aabbggrr -> #rrggbb
    assert lugares.obtener(con, admin, id=por["Hotel"]["id"])["lugar"]["descripcion_html"] == "<b>Cuarto 3</b>"
    assert {c["nombre"] for c in r["carpetas"]} == {"Mi viaje", "Día 1"}
    for malo in (b"", b"no es xml", b"PK\x03\x04roto", b"<kml><Document>" + b"x" * 10):
        with pytest.raises(db.DatosInvalidos):
            lugares_kmz.importar(con, admin, datos=base64.b64encode(malo).decode(), nombre="x.kml")
    with pytest.raises(db.DatosInvalidos):
        lugares_kmz.importar(con, admin, datos="###", nombre="x.kml")
    # a failure in the middle leaves nothing behind (all or nothing)
    antes = lugares.arbol(con, admin)
    roto = kml.replace("</Folder>", "</Folder><Placemark><name>mal</name><Point><coordinates>999,999</coordinates></Point></Placemark>")
    with pytest.raises(db.DatosInvalidos):
        lugares_kmz.importar(con, admin, datos=base64.b64encode(roto.encode()).decode(), nombre="x.kml")
    assert lugares.arbol(con, admin) == antes


def test_service_methods_exist_and_names_fit_the_remote_route():
    esperados = {"lugares", "lugar", "guardar_lugar", "eliminar_lugar", "adjunto_lugar", "guardar_carpeta_lugares", "eliminar_carpeta_lugares",
                 "mover_lugares", "visibilidad_lugares", "compartidos_lugares", "compartir_lugares", "exportar_lugares_kmz", "importar_lugares_kmz"}
    assert esperados <= set(METODOS)
    assert all(re.fullmatch(r"[a-z_]{1,40}", m) for m in esperados)               # visor_rutas/remoto.py only forwards these names
