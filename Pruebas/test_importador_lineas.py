"""Links deduced from the cable lines drawn in a diagram (red_fibra/importador.py)."""
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "red_fibra"))
import importador as imp  # noqa: E402

from origen import _AliasMatcher  # noqa: E402

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
STYLES = """<office:automatic-styles>
  <style:style style:name="cable"><style:graphic-properties draw:stroke="solid" svg:stroke-width="0.035cm" svg:stroke-color="#404040"/></style:style>
  <style:style style:name="hilo"><style:graphic-properties draw:stroke="dash" svg:stroke-width="0.035cm" svg:stroke-color="#ff33cc"/></style:style>
</office:automatic-styles>"""


def _bow_tie(x: float, y: float) -> str:
    """The Visio mufa icon: two triangles side by side (0.93 x 1.21 cm each)."""
    return (f'<draw:polygon draw:style-name="icono" svg:x="{x}cm" svg:y="{y}cm" svg:width="0.934cm" '
            f'svg:height="1.212cm" draw:points="0,1213 935,607 0,0"/>'
            f'<draw:polygon draw:style-name="icono" svg:x="{x + 0.89}cm" svg:y="{y}cm" svg:width="0.962cm" '
            f'svg:height="1.212cm" draw:points="963,0 0,607 963,1213"/>')


def _odg(tmp_path: Path, shapes: str) -> Path:
    content = (f'<office:document-content {NS}>{STYLES}<office:body><office:drawing>'
               f'<draw:page>{shapes}</draw:page></office:drawing></office:body></office:document-content>')
    path = tmp_path / "diagrama.odg"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content)
    return path


def test_line_through_icons_links_consecutive_mufas(tmp_path):
    # Three mufas on one horizontal cable (icons centred at y=10.6), not glued to the line.
    shapes = (_bow_tie(10, 10) + _bow_tie(30, 10) + _bow_tie(50, 10)
              + '<draw:line draw:style-name="cable" svg:x1="5cm" svg:y1="10.62cm" svg:x2="49.9cm" svg:y2="10.6cm"/>')
    iconos, lineas = imp.extraer_geometria(_odg(tmp_path, shapes))
    assert len(iconos) == 3
    pares = imp.enlaces_por_lineas(iconos, lineas)
    orden = sorted(range(3), key=lambda k: iconos[k]["x"])
    assert pares == {tuple(sorted((orden[0], orden[1]))), tuple(sorted((orden[1], orden[2])))}


def test_dashed_hilo_lines_and_lone_triangles_are_ignored(tmp_path):
    shapes = (_bow_tie(10, 10) + _bow_tie(30, 10)
              + '<draw:line draw:style-name="hilo" svg:x1="10cm" svg:y1="10.6cm" svg:x2="31cm" svg:y2="10.6cm"/>'
              + '<draw:polygon draw:style-name="icono" svg:x="60cm" svg:y="10cm" svg:width="0.9cm" '
                'svg:height="1.2cm" draw:points="0,1213 935,607 0,0"/>')
    iconos, lineas = imp.extraer_geometria(_odg(tmp_path, shapes))
    assert len(iconos) == 2
    assert imp.enlaces_por_lineas(iconos, lineas) == set()


def test_polyline_and_path_cables(tmp_path):
    # An L-shaped polyline from mufa A down to mufa B, and a path (with a line-jump curve) to mufa C.
    shapes = (_bow_tie(10, 10) + _bow_tie(10, 30) + _bow_tie(40, 30)
              + '<draw:polyline draw:style-name="cable" svg:x="10.9cm" svg:y="11cm" svg:width="1cm" '
                'svg:height="19cm" svg:viewBox="0 0 1000 19000" draw:points="0,0 0,19000"/>'
              + '<draw:path draw:style-name="cable" svg:x="11.8cm" svg:y="30.5cm" svg:width="28.3cm" '
                'svg:height="0.2cm" svg:viewBox="0 0 28300 200" '
                'svg:d="M0 100l10000 0c0-50 50-100 100-100 50 0 100 50 100 100l18100 0"/>')
    iconos, lineas = imp.extraer_geometria(_odg(tmp_path, shapes))
    pares = imp.enlaces_por_lineas(iconos, lineas)
    k = {(round(ic["x"]), round(ic["y"])): i for i, ic in enumerate(iconos)}
    a, b, c = k[(11, 11)], k[(11, 31)], k[(41, 31)]
    assert pares == {tuple(sorted((a, b))), tuple(sorted((b, c)))}


def test_labels_name_icons_and_unnamed_icons_are_crossed():
    iconos = [{"pagina": 0, "x": x, "y": 10, "mw": 0.9, "mh": 0.6} for x in (10, 30, 50)]
    nodos = [{"pagina": 0, "x": 9, "y": 4, "nombre": "MF A"}, {"pagina": 0, "x": 52, "y": 16, "nombre": "MF C"}]
    nombres = imp.nombrar_iconos(iconos, nodos)
    assert nombres == {0: 0, 2: 1}            # the middle icon has no label with coordinates
    # A - (unnamed) - C: the cable continues through the unnamed mufa
    assert imp.enlaces_entre_nodos({(0, 1), (1, 2)}, nombres) == {(0, 1)}


def test_las_colinas_abbreviation_is_recognised():
    rules = yaml.safe_load((Path(__file__).resolve().parent.parent / "business_rules.yaml").read_text(encoding="utf-8"))
    config = rules["traffic_origin"]
    matcher = _AliasMatcher(config["nodes"], config["ignore_label_words"])
    assert matcher.node_in("SPL 1X16 SECUNDARIO PUERTO 0/2/5 OLT L. COLINAS -19.92 dBm") == "OLT LAS COLINAS"
