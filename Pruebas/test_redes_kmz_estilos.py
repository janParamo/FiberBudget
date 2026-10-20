"""Visor v2, fase 9: ícono / color propio de lo que sale del KMZ (visor_rutas/redes/kmz_estilos.py, migración 014): por elemento o por carpeta, solo
administradores y editores, validado, un estilo activo por clave, quitar lo deja como el KMZ."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, kmz_estilos, usuarios
from visor_rutas.redes.api import METODOS

CLAVE = "RED/MUFAS|mf uno|12.13000,-86.25000"
CARPETA = "RED/POSTES DE CONCRETO|*|"
ICONO = {"tipo": "figura", "id": "estrella", "color": "#E53935", "escala": 1.5, "opacidad": 0.9}


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    editor = usuarios.identificar(con, persona_visor="ed")
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE id = %s", (editor["id"],))
    editor = usuarios.identificar(con, persona_visor="ed")
    lector = usuarios.identificar(con, persona_visor="lec")
    return con, admin, editor, lector


def test_save_list_replace_and_remove_a_style(mundo):
    con, admin, editor, lector = mundo
    r = kmz_estilos.guardar(con, editor, clave=CLAVE, alcance="elemento", carpeta="RED/MUFAS", nombre="MF UNO", icono=ICONO)
    assert r["estilo"]["estilo"]["icono"] == {"tipo": "figura", "id": "estrella", "color": "#e53935", "escala": 1.5, "opacidad": 0.9}      # color normalised
    kmz_estilos.guardar(con, admin, clave=CARPETA, alcance="carpeta", carpeta="RED/POSTES DE CONCRETO", linea={"color": "#0000ff", "grosor": 4})
    # anyone (a reader too) sees them: it is how the page paints the network
    vistos = kmz_estilos.listar(con, lector)["estilos"]
    assert {e["clave"]: e["alcance"] for e in vistos} == {CLAVE: "elemento", CARPETA: "carpeta"}
    # saving again replaces (one active style per key), it does not add a second one
    nuevo = dict(ICONO, color="#00ff00")
    kmz_estilos.guardar(con, editor, clave=CLAVE, alcance="elemento", carpeta="RED/MUFAS", nombre="MF UNO", icono=nuevo)
    vistos = kmz_estilos.listar(con, lector)["estilos"]
    assert len(vistos) == 2 and next(e for e in vistos if e["clave"] == CLAVE)["estilo"]["icono"]["color"] == "#00ff00"
    assert next(e for e in vistos if e["clave"] == CLAVE)["version"] == 2
    assert kmz_estilos.quitar(con, editor, clave=CLAVE) == {"clave": CLAVE}
    assert [e["clave"] for e in kmz_estilos.listar(con, lector)["estilos"]] == [CARPETA]
    with pytest.raises(db.NoEncontrado):
        kmz_estilos.quitar(con, editor, clave=CLAVE)
    # after removing it a new style can be saved with the same key
    kmz_estilos.guardar(con, editor, clave=CLAVE, alcance="elemento", carpeta="RED/MUFAS", icono=ICONO)
    assert len(kmz_estilos.listar(con, lector)["estilos"]) == 2


def test_only_administrators_and_editors_change_styles(mundo):
    con, admin, editor, lector = mundo
    with pytest.raises(db.SinPermiso):
        kmz_estilos.guardar(con, lector, clave=CLAVE, alcance="elemento", carpeta="x", icono=ICONO)
    kmz_estilos.guardar(con, editor, clave=CLAVE, alcance="elemento", carpeta="x", icono=ICONO)
    with pytest.raises(db.SinPermiso):
        kmz_estilos.quitar(con, lector, clave=CLAVE)
    assert len(kmz_estilos.listar(con, lector)["estilos"]) == 1
    for nombre in ("estilos_kmz", "guardar_estilo_kmz", "quitar_estilo_kmz"):
        assert nombre in METODOS


@pytest.mark.parametrize("cambio", [
    {"tipo": "estrella"}, {"id": "no-existe"}, {"color": "rojo"}, {"color": "#12345"}, {"escala": 9}, {"escala": "grande"}, {"opacidad": 2},
    {"tipo": "letra", "id": "AA"}, {"tipo": "numero", "id": "11"}])
def test_a_wrong_icon_is_refused_not_silently_fixed(mundo, cambio):
    con, admin, *_ = mundo
    with pytest.raises(db.DatosInvalidos):
        kmz_estilos.guardar(con, admin, clave=CLAVE, alcance="elemento", carpeta="x", icono={**ICONO, **cambio})
    assert kmz_estilos.listar(con, admin)["estilos"] == []


def _png_datos(ancho=200, alto=100):
    import base64
    import io

    from PIL import Image
    b = io.BytesIO()
    Image.new("RGBA", (ancho, alto), (220, 30, 30, 255)).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def test_own_image_and_text_icons_are_stored_and_exported(mundo):
    import io

    from PIL import Image

    from visor_rutas.redes import lugares_iconos
    con, admin, *_ = mundo
    datos = _png_datos()
    r = kmz_estilos.guardar(con, admin, clave=CLAVE, alcance="elemento", carpeta="x", icono={"tipo": "imagen", "id": "lo-que-sea", "datos": datos, "color": "#F7D117", "escala": 1.6})
    guardado = r["estilo"]["estilo"]["icono"]
    assert guardado["tipo"] == "imagen" and guardado["id"] == "imagen" and guardado["datos"] == datos            # the picture travels with the style
    r = kmz_estilos.guardar(con, admin, clave=CARPETA, alcance="carpeta", carpeta="x", icono={"tipo": "texto", "id": " 5G ", "color": "#2f6bff"})
    assert r["estilo"]["estilo"]["icono"]["id"] == "5G"
    kmz_estilos.guardar(con, admin, clave="otro|clave|", alcance="elemento", carpeta="x", icono={"tipo": "texto", "id": "🔌", "color": "#2f6bff"})
    # the same catalogue draws them as PNG for the exported KMZ (Mis lugares), the picture fitted in a square, the text in a circle
    for icono, tamano in (({"tipo": "imagen", "datos": datos}, (40, 40)), ({"tipo": "texto", "id": "OLT", "color": "#2f6bff"}, (40, 40)), ({"tipo": "texto", "id": "🔌", "color": "#2f6bff"}, (40, 40))):
        assert Image.open(io.BytesIO(lugares_iconos.icono_png(icono))).size == tamano
    assert lugares_iconos.clave({"tipo": "imagen", "datos": datos}).startswith("imagen-") and lugares_iconos.clave({"tipo": "texto", "id": "5G"}).startswith("texto-")
    assert not any(c in lugares_iconos.clave({"tipo": "texto", "id": "🔌"}) for c in "🔌/\\ ")                  # a name safe for the files of the KMZ
    # a picture that cannot be decoded exports as the default pushpin instead of stopping the export
    roto = {"tipo": "imagen", "datos": "data:image/png;base64,AAAA"}
    assert Image.open(io.BytesIO(lugares_iconos.icono_png(roto))).size[1] == 40


@pytest.mark.parametrize("icono", [
    {"tipo": "imagen", "datos": "data:text/html;base64,AAAA", "color": "#ffffff"},                       # not an image
    {"tipo": "imagen", "datos": "data:image/svg+xml;base64,AAAA", "color": "#ffffff"},                   # SVG can carry scripts: not accepted
    {"tipo": "imagen", "datos": "http://example.com/logo.png", "color": "#ffffff"},                       # nothing is loaded from outside
    {"tipo": "imagen", "color": "#ffffff"},
    {"tipo": "imagen", "datos": "data:image/png;base64," + "A" * 90000, "color": "#ffffff"},               # too big
    {"tipo": "texto", "id": "", "color": "#ffffff"}, {"tipo": "texto", "id": "ABCD", "color": "#ffffff"}, {"tipo": "texto", "id": "<b>", "color": "#ffffff"}])
def test_a_wrong_image_or_text_icon_is_refused(mundo, icono):
    con, admin, *_ = mundo
    with pytest.raises(db.DatosInvalidos):
        kmz_estilos.guardar(con, admin, clave=CLAVE, alcance="elemento", carpeta="x", icono=icono)
    assert kmz_estilos.listar(con, admin)["estilos"] == []


def test_icons_of_the_viewers_own_layers_are_shared_and_only_the_known_ones(mundo):
    con, admin, editor, lector = mundo
    r = kmz_estilos.guardar(con, editor, clave="capa|poste|", alcance="capa", carpeta="visor", nombre="Poste existente", icono=ICONO)
    assert r["estilo"]["alcance"] == "capa" and r["estilo"]["estilo"]["icono"]["id"] == "estrella"
    assert [e["clave"] for e in kmz_estilos.listar(con, lector)["estilos"]] == ["capa|poste|"]                      # everyone sees it
    for clave in kmz_estilos.CAPAS_VISOR:
        kmz_estilos.guardar(con, admin, clave=f"capa|{clave}|", alcance="capa", carpeta="visor", icono=ICONO)
    assert len(kmz_estilos.listar(con, lector)["estilos"]) == len(kmz_estilos.CAPAS_VISOR)
    with pytest.raises(db.SinPermiso):
        kmz_estilos.guardar(con, lector, clave="capa|nodo|", alcance="capa", carpeta="visor", icono=ICONO)
    for malo in ({"clave": "capa|inventada|"}, {"clave": CLAVE}, {"clave": "capa|poste|", "icono": None, "linea": {"color": "#0000ff"}},
                 {"clave": "capa|poste|", "linea": {"color": "#0000ff"}}):
        with pytest.raises(db.DatosInvalidos):
            kmz_estilos.guardar(con, admin, **{"alcance": "capa", "carpeta": "visor", "icono": ICONO, **malo})
    kmz_estilos.quitar(con, editor, clave="capa|poste|")                                                          # «Restablecer»
    assert "capa|poste|" not in {e["clave"] for e in kmz_estilos.listar(con, lector)["estilos"]}


def test_other_wrong_requests(mundo):
    con, admin, *_ = mundo
    ok = {"carpeta": "x", "icono": ICONO}
    for malo in ({"clave": "  ", "alcance": "elemento"}, {"clave": "x" * 700, "alcance": "elemento"}, {"clave": CLAVE, "alcance": "todo"},
                 {"clave": CLAVE, "alcance": "carpeta"},                              # a folder key ends in |*|
                 {"clave": CLAVE, "alcance": "elemento", "icono": None}):               # nothing to save
        with pytest.raises(db.DatosInvalidos):
            kmz_estilos.guardar(con, admin, **{**ok, **malo})
    with pytest.raises(db.DatosInvalidos):
        kmz_estilos.guardar(con, admin, clave=CLAVE, alcance="elemento", carpeta="x", linea={"color": "#0000ff", "grosor": 50})
    assert kmz_estilos.listar(con, admin)["estilos"] == []
    # a valid line style, with its defaults
    r = kmz_estilos.guardar(con, admin, clave=CLAVE, alcance="elemento", carpeta="x", linea={"color": "#FF0000"})
    assert r["estilo"]["estilo"]["linea"] == {"color": "#ff0000", "grosor": 3.0, "opacidad": 1.0}
