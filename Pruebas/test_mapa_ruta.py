"""Route map rendering without network: tiles come from a fake HTTP session."""
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from PIL import Image

import mapa_ruta
from excel_generator import PictureAnchor, _insert_picture

ORIGEN = {"nombre": "MF LOYOLA #2", "lat": 12.153673, "lon": -86.263960}
CLIENTE = {"nombre": "Cliente", "lat": 12.153328, "lon": -86.263438}
ROUTE = [(12.153673, -86.263960), (12.1535, -86.2637), (12.153328, -86.263438)]


class _FakeResponse:
    def __init__(self, status: int, content: bytes = b""):
        self.status_code, self.content = status, content


def _tile_bytes(color=(30, 90, 30, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (256, 256), color).save(buffer, "PNG")
    return buffer.getvalue()


def test_map_is_drawn_from_tiles_with_route_and_markers(tmp_path, monkeypatch):
    requested = []

    def fake_get(url, **kwargs):
        requested.append((url, kwargs))
        return _FakeResponse(200, _tile_bytes())

    monkeypatch.setattr(mapa_ruta._session, "get", fake_get)
    out = mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [{"nombre": "ALT", "lat": 12.1535, "lon": -86.2648}],
                                      False, tmp_path / "mapas" / "T1.png", postes=[(12.1536, -86.2638)],
                                      distancia_ruta_m=95.0)
    assert out == tmp_path / "mapas" / "T1.png"
    image = Image.open(out).convert("RGB")
    assert image.size == mapa_ruta.SIZE
    assert any("World_Imagery/MapServer/tile/18/" in url for url, _ in requested)      # zoom capped at 18
    assert any("World_Transportation" in url for url, _ in requested)
    assert all(kwargs["timeout"] == 10 and "User-Agent" in kwargs["headers"] for _, kwargs in requested)
    colors = {color for _, color in image.getcolors(maxcolors=image.width * image.height)}
    assert mapa_ruta.ROUTE_COLOR in colors and mapa_ruta.ORIGIN_COLOR in colors and mapa_ruta.CLIENT_COLOR in colors


def test_zoom_19_where_esri_has_imagery_else_18(tmp_path, monkeypatch):
    import random
    rng = random.Random(1)
    photo = Image.new("RGB", (256, 256))
    photo.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(256 * 256)])
    buffer = io.BytesIO()
    photo.save(buffer, "PNG")
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return _FakeResponse(200, buffer.getvalue())

    monkeypatch.setattr(mapa_ruta._session, "get", fake_get)
    assert mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [], False, tmp_path / "z19.png") is not None
    assert any("World_Imagery/MapServer/tile/19/" in url for url in requested)
    # A flat placeholder tile ("Map data not yet available") at 19 drops the map to 18.
    requested.clear()
    monkeypatch.setattr(mapa_ruta._session, "get", lambda url, **k: (requested.append(url), _FakeResponse(
        200, _tile_bytes()))[1])
    assert mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [], False, tmp_path / "z18.png") is not None
    assert not any("/tile/19/" in url for url in requested[1:]) and any("/tile/18/" in url for url in requested)


def _colors(path: Path) -> set:
    image = Image.open(path).convert("RGB")
    return {color for _, color in image.getcolors(maxcolors=image.width * image.height)}


def test_drop_line_joins_route_end_to_client_only_when_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(mapa_ruta._session, "get", lambda url, **k: _FakeResponse(200, _tile_bytes()))
    # Google snaps the route to the street ~25 m from the client: the drop is drawn.
    snapped = ROUTE[:-1] + [(12.153550, -86.263400)]
    apart = mapa_ruta.generar_mapa_ruta(snapped, ORIGEN, CLIENTE, [], False, tmp_path / "apart.png")
    assert mapa_ruta.DROP_COLOR in _colors(apart)
    # The route already ends on the client: no drop.
    joined = mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [], False, tmp_path / "joined.png")
    assert mapa_ruta.DROP_COLOR not in _colors(joined)


def test_tile_failure_returns_none_and_never_raises(tmp_path, monkeypatch):
    def offline(url, **kwargs):
        raise ConnectionError("no internet")

    monkeypatch.setattr(mapa_ruta._session, "get", offline)
    assert mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [], False, tmp_path / "m.png") is None
    assert not (tmp_path / "m.png").exists()


def test_missing_street_labels_still_give_a_satellite_map(tmp_path, monkeypatch):
    monkeypatch.setattr(mapa_ruta._session, "get", lambda url, **k: _FakeResponse(
        404 if "World_Transportation" in url else 200, _tile_bytes()))
    assert mapa_ruta.generar_mapa_ruta(ROUTE, ORIGEN, CLIENTE, [], True, tmp_path / "m.png") is not None


REAL_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PlantilaEjemploPresupuesto.xlsx"


@pytest.mark.skipif(not REAL_TEMPLATE.is_file(), reason="company template not available")
def test_picture_joins_the_real_template_drawing_without_losing_its_logos(tmp_path):
    copy = tmp_path / "t.xlsx"
    copy.write_bytes(REAL_TEMPLATE.read_bytes())
    png = tmp_path / "m.png"
    Image.new("RGB", (1000, 700), (0, 0, 255)).save(png)
    with zipfile.ZipFile(copy) as archive:
        before = archive.read("xl/drawings/drawing1.xml").decode()
    _insert_picture(copy, "xl/worksheets/sheet1.xml", PictureAnchor(2, 2, 17, 2, 7, 80, 51, 15, 720, 590), png)

    with zipfile.ZipFile(copy) as archive:
        drawing = archive.read("xl/drawings/drawing1.xml").decode()
        rels = archive.read("xl/drawings/_rels/drawing1.xml.rels").decode()
        assert archive.read("xl/media/mapa_ruta.png") == png.read_bytes()
    assert drawing.count("<xdr:pic>") + drawing.count("<xdr:pic ") == before.count("<xdr:pic>") + 1
    assert all(shape in drawing for shape in ("image1.png", "image2.png", "Shape 3"))
    assert "../media/mapa_ruta.png" in rels
    # The map is the first (bottom) layer, so the template's north arrow stays in front of it.
    assert drawing.index("Mapa ruta recomendada") < min(drawing.index(n) for n in ("image1.png", "image2.png"))
    workbook = load_workbook(copy)
    assert len(workbook["Ruta proyectada"]._images) == 3     # two logos + the map
