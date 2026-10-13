"""Panel "Lugares" of the viewer: KMZ importer (visor_rutas/kmz_capas.py), local Api, remote
endpoints /visor/kmz/* and the remote client cache. The KMZ is only for VIEWING: the route and
budget keep using PostGIS (red_lineas / red_puntos)."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from test_visor_api import JAN, _api_remota, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas import kmz_capas

ROJO_KML = "ff0000ff"          # aabbggrr -> #ff0000
AZUL_KML = "ffff0000"          # -> #0000ff


def _png(color=(255, 255, 255, 255)) -> bytes:
    salida = io.BytesIO()
    Image.new("RGBA", (8, 8), color).save(salida, "PNG")
    return salida.getvalue()


KML = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document><name>RED PRUEBA</name>
  <Style id="troncal_n"><LineStyle><color>{AZUL_KML}</color><width>2</width></LineStyle></Style>
  <Style id="troncal_h"><LineStyle><color>ff00ff00</color><width>6</width></LineStyle></Style>
  <StyleMap id="troncal"><Pair><key>normal</key><styleUrl>#troncal_n</styleUrl></Pair>
    <Pair><key>highlight</key><styleUrl>#troncal_h</styleUrl></Pair></StyleMap>
  <Style id="mufa"><IconStyle><color>ff00aaff</color><scale>1</scale>
    <Icon><href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href></Icon></IconStyle></Style>
  <Style id="corte"><IconStyle><Icon><href>files/icon-corte.png</href></Icon></IconStyle></Style>
  <Style id="poste"><IconStyle><color>ff0000ff</color>
    <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle></Style>
  <Folder><name>RED PRUEBA</name><visibility>0</visibility>
    <Folder><name>MANAGUA</name><visibility>0</visibility>
      <Folder><name>TRONCAL</name><visibility>0</visibility>
        <Placemark><name>TRONCAL UNO</name><styleUrl>#troncal</styleUrl>
          <LineString><coordinates>-86.30,12.10,0 -86.29,12.11,0</coordinates></LineString></Placemark>
        <Placemark><name>TRONCAL DOS</name><styleUrl>#troncal</styleUrl>
          <LineString><coordinates>-86.28,12.10 -86.27,12.12</coordinates></LineString></Placemark>
        <Placemark><name>TRONCAL UFINET TRES</name>
          <Style><LineStyle><color>{ROJO_KML}</color><width>4</width></LineStyle></Style>
          <MultiGeometry><LineString><coordinates>-86.26,12.10 -86.25,12.11</coordinates></LineString>
            <LineString><coordinates>-86.25,12.11 -86.24,12.12</coordinates></LineString></MultiGeometry></Placemark>
      </Folder>
      <Folder><name>MUFA</name><visibility>0</visibility>
        <Placemark><name>MF CASA</name><styleUrl>#mufa</styleUrl>
          <description><![CDATA[com_exlyo_mapmarker_piniconcode: <br>Descripción: com_exlyo_mapmarker_x: <br>FO 24H<br><script>alert(1)</script><b onclick="x()">SPL 1</b><br><a href="javascript:alert(2)">malo</a> <a href="https://ideay.net">bueno</a><br><img src="files/foto.jpg">]]></description>
          <ExtendedData><Data name="notes"><value>nota de campo</value></Data>
            <Data name="com_exlyo_mapmarker_customfields"><value>basura</value></Data>
            <Data name="descripción"><value>mufa de prueba</value></Data></ExtendedData>
          <gpstestkml:accuracy>5</gpstestkml:accuracy>
          <Point><coordinates>-86.25,12.13,0</coordinates></Point></Placemark>
        <Placemark><name>MF CORTE</name><styleUrl>#corte</styleUrl><Point><coordinates>-86.24,12.13</coordinates></Point></Placemark>
      </Folder>
      <Folder><name>POSTES DE CONCRETO</name>
        <Placemark><name>P1</name><styleUrl>#poste</styleUrl><Point><coordinates>-86.25,12.14</coordinates></Point></Placemark>
      </Folder>
      <Folder><name>MUFA ENATREL</name></Folder>
    </Folder>
  </Folder>
</Document></kml>"""


def crear_kmz(ruta: Path, kml: str = KML) -> Path:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("doc.kml", kml)
        z.writestr("files/icon-corte.png", _png((0, 200, 0, 255)))
        z.writestr("files/foto.jpg", b"\xff\xd8\xff\xe0 foto")
    return ruta


@pytest.fixture
def sin_internet(monkeypatch):
    """Google icons cannot be downloaded: SVG equivalents (and no real network in tests)."""
    import requests

    def falla(*a, **k):
        raise requests.ConnectionError("sin internet")
    monkeypatch.setattr(requests, "get", falla)


@pytest.fixture
def importado(tmp_path, sin_internet):
    kmz = crear_kmz(tmp_path / "red.kmz")
    destino = tmp_path / "datos_kmz"
    arbol = kmz_capas.importar(kmz, destino)
    return arbol, destino, kmz


def _por_nombre(arbol, nombre):
    return next(c for c in arbol["carpetas"].values() if c["nombre"] == nombre)


def _capa(destino, carpeta):
    return json.loads((destino / "capas" / f"{carpeta['id']}.geojson").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- importador

def test_tree_counts_and_hierarchy(importado):
    arbol, destino, kmz = importado
    raiz = arbol["carpetas"][arbol["raiz"]]
    assert raiz["nombre"] == "RED PRUEBA" and raiz["total"] == 6 and arbol["elementos"] == 6
    managua = _por_nombre(arbol, "MANAGUA")
    assert managua["ruta"] == "RED PRUEBA/RED PRUEBA/MANAGUA" and managua["directos"] == 0 and managua["total"] == 6
    assert [arbol["carpetas"][h]["nombre"] for h in managua["hijos"]] == ["TRONCAL", "MUFA", "POSTES DE CONCRETO", "MUFA ENATREL"]
    assert _por_nombre(arbol, "MUFA ENATREL")["total"] == 0                       # empty folder (grey)
    troncal = _por_nombre(arbol, "TRONCAL")
    assert (troncal["directos"], troncal["geometria"], troncal["troncal"], troncal["visible"]) == (3, "linea", True, True)
    assert _por_nombre(arbol, "MUFA")["visible"] is False and _por_nombre(arbol, "POSTES DE CONCRETO")["postes"] is True
    assert troncal["bbox"] == [-86.3, 12.1, -86.24, 12.12]
    assert arbol["md5"] == kmz_capas.md5_archivo(kmz) and arbol["errores_xml"] >= 1   # undeclared prefix recovered


def test_colors_aabbggrr_stylemap_normal_and_inline_style(importado):
    arbol, destino, _ = importado
    assert kmz_capas.color_kml("ff0000ff") == ("#ff0000", 1.0)
    assert kmz_capas.color_kml("80ff8800") == ("#0088ff", 0.502)
    capa = _capa(destino, _por_nombre(arbol, "TRONCAL"))
    estilos = [capa["estilos"][f["properties"]["e"]] for f in capa["features"]]
    assert estilos[0] == {"tipo": "linea", "color": "#0000ff", "opacidad": 1.0, "grosor": 2.0}    # StyleMap "normal"
    assert estilos[2]["color"] == "#ff0000" and estilos[2]["grosor"] == 4.0                      # inline Style
    assert capa["features"][2]["geometry"]["type"] == "MultiLineString"
    assert capa["features"][0]["properties"]["km"] == pytest.approx(1.55, abs=0.05)


def test_trunk_families_and_distinctive_colors(importado):
    arbol, destino, _ = importado
    props = [f["properties"] for f in _capa(destino, _por_nombre(arbol, "TRONCAL"))["features"]]
    assert [p["f"] for p in props] == ["troncal", "troncal", "ufinet"]
    # UNO and DOS share their colour in the folder: distinctive colour; TRES has its own colour.
    assert props[0]["cd"] == kmz_capas.color_distintivo("TRONCAL UNO") and "cd" not in props[2]
    assert kmz_capas.color_distintivo("TRONCAL UNO") == kmz_capas.color_distintivo("  troncal   uno ")
    assert kmz_capas.color_distintivo("TRONCAL UNO") in kmz_capas.PALETA_TRONCALES


def test_description_is_safe_without_exlyo_and_photos_are_copied(importado):
    arbol, destino, _ = importado
    p = _capa(destino, _por_nombre(arbol, "MUFA"))["features"][0]["properties"]
    d = p["d"]
    assert "exlyo" not in d and "<script" not in d.lower() and "alert" not in d and "onclick" not in d
    assert "FO 24H" in d and "<b>SPL 1</b>" in d and 'href="https://ideay.net"' in d and "javascript" not in d
    assert (p["notes"], p["desc"]) == ("nota de campo", "mufa de prueba") and "datos" not in p
    assert p["fotos"] == ["foto.jpg"] and (destino / "fotos" / "foto.jpg").read_bytes().startswith(b"\xff\xd8")
    assert json.loads((destino / "indice.json").read_text(encoding="utf-8"))[_por_nombre(arbol, "MUFA")["id"]][0][0] == "MF CASA"


def test_icons_files_tinted_and_svg_without_internet(importado):
    arbol, destino, _ = importado
    capa = _capa(destino, _por_nombre(arbol, "MUFA"))
    pin, corte = (capa["estilos"][f["properties"]["e"]] for f in capa["features"])
    assert pin["tipo"] == "icono" and pin["icono"] == "ylw-pushpin_ffaa00.svg" and pin["ancla"] == "pin"
    assert "#ffaa00" in (destino / "iconos" / pin["icono"]).read_text(encoding="utf-8")
    assert corte["icono"] == "icon-corte.png" and (destino / "iconos" / "icon-corte.png").is_file()
    poste = _capa(destino, _por_nombre(arbol, "POSTES DE CONCRETO"))["estilos"][0]
    assert poste["tipo"] == "circulo" and poste["color"] == "#ff0000"           # posts: canvas circles
    assert set(arbol["iconos"]) == {"ylw-pushpin_ffaa00.svg", "icon-corte.png"}


def test_folder_ids_are_stable_between_imports(tmp_path, sin_internet):
    kmz = crear_kmz(tmp_path / "red.kmz")
    a = kmz_capas.importar(kmz, tmp_path / "uno")
    b = kmz_capas.importar(kmz, tmp_path / "dos")
    assert list(a["carpetas"]) == list(b["carpetas"])
    assert sorted(p.name for p in (tmp_path / "uno" / "capas").iterdir()) == sorted(p.name for p in (tmp_path / "dos" / "capas").iterdir())
    assert _por_nombre(a, "TRONCAL")["id"] == kmz_capas.id_carpeta(["RED PRUEBA", "RED PRUEBA", "MANAGUA", "TRONCAL"])


def test_cache_regenerates_only_when_the_kmz_md5_changes(tmp_path, sin_internet, monkeypatch):
    kmz = crear_kmz(tmp_path / "red.kmz")
    destino = tmp_path / "datos"
    llamadas = []
    original = kmz_capas.importar
    monkeypatch.setattr(kmz_capas, "importar", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    primero = kmz_capas.asegurar(kmz, destino)
    assert kmz_capas.asegurar(tmp_path, destino)["md5"] == primero["md5"] and len(llamadas) == 1   # folder: its .kmz
    crear_kmz(kmz, KML.replace("TRONCAL DOS", "TRONCAL DOS B"))
    assert kmz_capas.asegurar(kmz, destino)["md5"] != primero["md5"] and len(llamadas) == 2
    (kmz).unlink()
    sin_kmz = kmz_capas.asegurar(tmp_path / "no_existe.kmz", destino)
    assert "última red importada" in sin_kmz["aviso"]
    with pytest.raises(kmz_capas.KmzNoEncontrado):
        kmz_capas.asegurar(tmp_path / "no_existe.kmz", tmp_path / "vacia")


def test_only_cache_files_can_be_served(importado):
    _, destino, _ = importado
    assert kmz_capas.archivo_seguro("fotos/foto.jpg", destino).is_file()
    for malo in ("../red.kmz", "fotos/../../red.kmz", "capas/x.geojson", "iconos/no.png", "fotos/foto.exe", "/etc/passwd"):
        with pytest.raises(FileNotFoundError):
            kmz_capas.archivo_seguro(malo, destino)
    with pytest.raises(FileNotFoundError):
        kmz_capas.archivo_capa("../arbol", destino)


def test_the_kmz_is_only_for_viewing():
    raiz = Path(kmz_capas.__file__).resolve().parent.parent
    fuente = Path(kmz_capas.__file__).read_text(encoding="utf-8")
    assert "red_lineas" not in fuente.split('"""', 2)[2] and "psycopg" not in fuente and "import db" not in fuente
    for modulo in ("main.py", "db.py", "presupuesto.py", "routing.py", "origen.py", "visor_rutas/calculo.py"):
        assert "kmz_capas" not in (raiz / modulo).read_text(encoding="utf-8"), modulo


# --------------------------------------------------------------------------- Api local, API remota y cliente remoto

def test_local_api_and_saved_panel_state(importado, monkeypatch, tmp_path):
    arbol, destino, kmz = importado
    from visor_rutas import ventana_web
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", destino)
    monkeypatch.setenv("KMZ_PATH", str(kmz))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    api = ventana_web.Api()
    r = api.kmz_arbol()
    assert r["ok"] and r["arbol"]["md5"] == arbol["md5"]
    assert r["iconos"]["icon-corte.png"].startswith("data:image/png;base64,")
    troncal = _por_nombre(arbol, "TRONCAL")
    assert len(api.kmz_capa(troncal["id"])["capa"]["features"]) == 3
    assert api.kmz_capa("../x")["ok"] is False
    assert api.kmz_foto("foto.jpg")["data_url"].startswith("data:image/jpeg;base64,")
    assert api.kmz_indice()["ok"]
    assert api.capas_estado() == {"ok": True, "estado": None}
    assert api.guardar_capas_estado({"version": 1, "marcadas": [troncal["id"]]}) == {"ok": True}
    assert api.capas_estado()["estado"]["marcadas"] == [troncal["id"]]
    assert (tmp_path / "appdata" / "VisorRutas" / "capas.json").is_file()


def test_remote_endpoints_need_the_key_skip_the_limit_and_feed_the_client_cache(importado, entorno, monkeypatch, tmp_path):
    arbol, destino, kmz = importado
    main, _, cliente, _, _ = entorno
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", destino)
    monkeypatch.setenv("KMZ_PATH", str(kmz))
    monkeypatch.setenv("VISOR_RATE_LIMIT_PER_HOUR", "1")
    assert cliente.get("/visor/kmz/arbol").status_code == 401
    for _ in range(3):                                  # read-only files: no hourly limit
        r = cliente.get("/visor/kmz/arbol", headers={**JAN, "Accept-Encoding": "gzip"})
        assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip" and r.json()["md5"] == arbol["md5"]
    crudo = cliente.get("/visor/kmz/arbol", headers={**JAN, "Accept-Encoding": "identity"})
    assert "content-encoding" not in crudo.headers and crudo.json()["md5"] == arbol["md5"]
    troncal = _por_nombre(arbol, "TRONCAL")
    assert len(cliente.get(f"/visor/kmz/capa/{troncal['id']}", headers=JAN).json()["features"]) == 3
    assert cliente.get("/visor/kmz/capa/zzz", headers=JAN).status_code == 422
    assert cliente.get("/visor/kmz/archivo/fotos/foto.jpg", headers=JAN).content.startswith(b"\xff\xd8")
    assert cliente.get("/visor/kmz/archivo/fotos/..%2F..%2Fred.kmz", headers=JAN).status_code == 404
    assert cliente.get("/visor/kmz/indice", headers=JAN).status_code == 200

    remota = _api_remota(main, tmp_path)
    r = remota.kmz_arbol()
    assert r["ok"] and set(r["iconos"]) == set(arbol["iconos"])
    cache = tmp_path / "descargas_remotas" / "kmz_cache" / arbol["md5"]
    assert (cache / "arbol.json").is_file() and (cache / "iconos" / "icon-corte.png").is_file()
    assert len(remota.kmz_capa(troncal["id"])["capa"]["features"]) == 3
    assert (cache / "capas" / f"{troncal['id']}.geojson").is_file()             # cached: no second request
    assert remota.kmz_foto("foto.jpg")["data_url"].startswith("data:image/jpeg;base64,")
    assert remota.kmz_indice()["ok"] and remota.kmz_capa("../x")["ok"] is False
    # The limited endpoints still count: the 2nd route of the hour is refused.
    cliente.post("/visor/ruta", json={"texto": "12.1364, -86.2514"}, headers=JAN)
    assert cliente.post("/visor/ruta", json={"texto": "12.1364, -86.2514"}, headers=JAN).status_code == 429
