"""Pilot fusion extraction (red_fibra/fusiones.py), its report/metrics script and the new table."""
import csv
import math
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

RED_FIBRA = Path(__file__).resolve().parent.parent / "red_fibra"
sys.path.insert(0, str(RED_FIBRA))
import fusiones  # noqa: E402
import piloto_fusiones  # noqa: E402

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"')


def _estilo(nombre, color, flechas=False):
    marcas = ' draw:marker-start="Arrow" draw:marker-end="Arrow"' if flechas else ''
    return (f'<style:style style:name="{nombre}" style:family="graphic"><style:graphic-properties draw:stroke="solid" '
            f'svg:stroke-color="{color}" svg:stroke-width="0.035cm"{marcas}/></style:style>')


def _marco(x, y, w, h, *parrafos):
    ps = "".join(f"<text:p>{p}</text:p>" for p in parrafos)
    return (f'<draw:frame svg:x="{x}cm" svg:y="{y}cm" svg:width="{w}cm" svg:height="{h}cm">'
            f'<draw:text-box>{ps}</draw:text-box></draw:frame>')


# Numbering blocks: "1 2 3 4" at x 2..6 and "4 3 2 1" at x 10..14 (y 5..5.5). A number's centre is
# at its character position: left 1 2 3 4 -> x 2.2857 3.4286 4.5714 5.7143; right 4 3 2 1 ->
# x 10.2857 11.4286 12.5714 13.7143; y = 5.25.
CONTENIDO = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS}><office:automatic-styles>
{_estilo("verde", "#00b050", flechas=True)}{_estilo("rojo", "#ff0000")}{_estilo("cable", "#404040")}
</office:automatic-styles><office:body><office:drawing><draw:page draw:name="p1">
{_marco(2, 5, 4, 0.5, "1 2 3 4")}
{_marco(10, 5, 4, 0.5, "4 3 2 1")}
{_marco(1.5, 8.2, 3, 0.5, "SPL 1X8 PUERTO 2")}
{_marco(18, 12, 3, 0.5, "FO 12H (6 BUFFER DE 2H)")}
<draw:polyline draw:style-name="verde" svg:x="4.5714cm" svg:y="3cm" svg:width="6.8572cm" svg:height="2.25cm"
  svg:viewBox="0 0 68572 22500" draw:points="0,22500 0,0 68572,0 68572,22500"/>
<draw:line draw:style-name="rojo" svg:x1="3.4286cm" svg:y1="5.25cm" svg:x2="3.4286cm" svg:y2="2cm"/>
<draw:polyline draw:style-name="rojo" svg:x="3.4286cm" svg:y="2cm" svg:width="9.1428cm" svg:height="3.25cm"
  svg:viewBox="0 0 91428 32500" draw:points="0,0 91428,0 91428,32500"/>
<draw:line draw:style-name="rojo" svg:x1="2.2857cm" svg:y1="5.25cm" svg:x2="2.2857cm" svg:y2="8.0cm"/>
<draw:line draw:style-name="cable" svg:x1="0cm" svg:y1="5.6cm" svg:x2="20cm" svg:y2="5.6cm"/>
</draw:page></office:drawing></office:body></office:document-content>"""

ESTILOS = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {NS}><office:automatic-styles><style:page-layout style:name="PM1">
<style:page-layout-properties fo:page-width="30cm" fo:page-height="20cm"/></style:page-layout>
</office:automatic-styles></office:document-styles>"""


@pytest.fixture
def odg(tmp_path):
    ruta = tmp_path / ("f" * 32 + ".odg")
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("content.xml", CONTENIDO)
        z.writestr("styles.xml", ESTILOS)
    return ruta


def test_colores_tia_598_y_color_esperado_por_buffer():
    assert fusiones.color_tia("#7030a0")[:2] == (10, "violeta")
    assert fusiones.color_tia("#00b0f0")[:2] == (12, "aqua")
    assert fusiones.color_tia("#d26d19")[:2] == (2, "naranja")
    assert fusiones.color_tia("#ff33cc")[:2] == (11, "rosa")
    assert fusiones.color_tia("#00b050")[:2] == (3, "verde")
    assert fusiones.color_tia("sin color")[:2] == (None, "otro")
    assert fusiones.color_esperado(14, 12) == (2, 2)          # hilo 14 = naranja del buffer 2
    assert fusiones.color_esperado(5, 2) == (1, 3)            # buffers de 2 hilos
    assert fusiones.color_esperado(7, 6) == (1, 2)            # buffers de 6 hilos


def test_transform_de_odf_rota_y_traslada():
    f = fusiones._transformacion("rotate (1.5707963267949) translate (2cm 3cm)")
    x, y = f(1, 0)
    assert math.isclose(x, 2, abs_tol=1e-6) and math.isclose(y, 2, abs_tol=1e-6)


def test_posicion_de_cada_numero_en_el_cuadro(odg):
    dibujo = fusiones.leer_dibujo(odg)[0]
    numeros = {(n["numero"], round(n["x"], 2)) for n in fusiones.numeros_de_hilo(dibujo["textos"])}
    assert {(3, 4.57), (1, 2.29), (3, 11.43), (1, 13.71)} <= numeros


def test_extrae_puentes_tramos_unidos_y_salida_a_splitter(odg):
    detectadas = fusiones.extraer_fusiones(odg)
    assert len(detectadas) == 3                                 # the cable line touches no number
    por_hilos = {(f["hilo_entrada"], f["hilo_salida"]): f for f in detectadas}

    verde = por_hilos[(3, 3)]
    assert verde["color_tia"] == "3 verde" and verde["confianza"] >= 0.9
    assert "color verde = hilo 3" in verde["motivo"] and "con flechas" in verde["motivo"]
    assert verde["entrada"].startswith("hilo 3 (buffer 1, verde)")
    assert verde["salida"].startswith("hilo 3 (buffer 2, azul)")   # right cable: buffers of 2 hilos

    dos_piezas = por_hilos[(2, 2)]                               # line + polyline joined into one fusion
    assert "no corresponde al número de hilo" in dos_piezas["motivo"]
    assert dos_piezas["confianza"] < verde["confianza"]
    assert len(eval(dos_piezas["puntos"])) == 4

    splitter = por_hilos[(1, None)]
    assert splitter["salida"] == "puerto/cliente: SPL 1X8 PUERTO 2"
    assert splitter["x2_cm"] == pytest.approx(2.2857, abs=1e-3) and splitter["y2_cm"] == pytest.approx(8.0)
    assert all(0 <= f["confianza"] <= 1 for f in detectadas)


MINIMO = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS}><office:automatic-styles>
{_estilo("azul", "#0070c0")}{_estilo("naranja", "#ed7d31")}
</office:automatic-styles><office:body><office:drawing><draw:page draw:name="p1">
{_marco(2, 5, 3, 0.5, "1 2")}
{_marco(10, 5, 3, 0.5, "1 2")}
<draw:line draw:style-name="azul" svg:x1="2.5cm" svg:y1="5.25cm" svg:x2="10.5cm" svg:y2="5.25cm"/>
<draw:polyline draw:style-name="naranja" svg:x="4.5cm" svg:y="3cm" svg:width="8cm" svg:height="2.25cm"
  svg:viewBox="0 0 8000 2250" draw:points="0,2250 0,0 8000,0 8000,2250"/>
</draw:page></office:drawing></office:body></office:document-content>"""


def test_odg_minimo_dos_lineas_dos_pares_con_su_color_tia(tmp_path):
    # Two numbering texts "1 2" (centres x 2.5 / 4.5 and 10.5 / 12.5, y 5.25); a blue line joins the
    # two hilo 1 and an orange bridge joins the two hilo 2.
    ruta = tmp_path / "minimo.odg"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("content.xml", MINIMO)
        z.writestr("styles.xml", ESTILOS)
    pares = sorted((f["hilo_entrada"], f["hilo_salida"], f["color_tia"]) for f in fusiones.extraer_fusiones(ruta))
    assert pares == [(1, 1, "1 azul"), (2, 2, "2 naranja")]


def test_tolerancia_configurable(odg):
    # the drawn ends are ~0.00003 cm from the estimated number centres and 0.2 cm from the splitter text
    assert len(fusiones.extraer_fusiones(odg, {"hilo": 0.001})) == 3
    assert fusiones.extraer_fusiones(odg, {"hilo": 0.000001, "texto": 0.000001}) == []


def test_guardar_reemplaza_las_fusiones_del_archivo_y_coincide_con_schema(odg, tmp_path):
    con = sqlite3.connect(tmp_path / "rf.db")
    con.executescript((RED_FIBRA / "schema.sql").read_text(encoding="utf-8"))
    columnas_schema = [r[1] for r in con.execute("PRAGMA table_info(fusiones_piloto)")]
    con.execute("INSERT INTO importaciones(id, fecha, carpeta_origen) VALUES (1, 'x', 'x')")
    con.execute("INSERT INTO archivos(id, importacion_id, ruta_relativa, nombre, formato, md5, estado) "
                "VALUES (7, 1, 'x.vsd', 'x.vsd', 'vsd', ?, 'ok')", ("f" * 32,))
    detectadas = fusiones.extraer_fusiones(odg)
    fusiones.guardar(con, 7, detectadas)
    fusiones.guardar(con, 7, detectadas)                      # re-run: replaced, not duplicated
    assert con.execute("SELECT count(*) FROM fusiones_piloto WHERE archivo_id = 7").fetchone()[0] == 3
    otra = sqlite3.connect(":memory:")
    otra.executescript(fusiones.DDL_SQLITE)                    # same table when created by the pilot
    assert [r[1] for r in otra.execute("PRAGMA table_info(fusiones_piloto)")] == columnas_schema
    assert fusiones.tamano_pagina_cm(odg) == (30.0, 20.0)


def test_publicar_postgres_solo_carga_fusiones_si_la_tabla_existe():
    publicar = pytest.importorskip("publicar_postgres")
    assert "fusiones_piloto" not in publicar.tablas_a_publicar({"archivos", "nodos"})
    assert publicar.tablas_a_publicar({"fusiones_piloto"})[-1] == "fusiones_piloto"
    assert publicar.tablas_a_publicar(set())[:7] == ["archivos", "nodos", "nodo_apariciones", "enlaces",
                                                     "servicios", "anillo_tramos", "textos_crudos"]
    assert "fusiones_piloto" in (RED_FIBRA / "schema_postgres.sql").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- piloto_fusiones.py

def test_buscar_diagrama_por_md5_nombre_o_ruta(tmp_path):
    con = sqlite3.connect(tmp_path / "rf.db")
    con.executescript((RED_FIBRA / "schema.sql").read_text(encoding="utf-8"))
    con.execute("INSERT INTO importaciones(id, fecha, carpeta_origen) VALUES (1, 'x', 'x')")
    con.executemany("INSERT INTO archivos(id, importacion_id, ruta_relativa, nombre, formato, tipo_diagrama, md5, estado) "
                    "VALUES (?, 1, ?, ?, ?, ?, ?, 'ok')",
                    [(1, "Z/RED.vsd", "RED.vsd", "vsd", "red", "1" * 32),
                     (2, "Z/3 Mufa Piero.vsd", "3 Mufa Piero.vsd", "vsd", "mufa", "2" * 32)])
    con.execute("INSERT INTO nodos(id, nombre, nombre_normalizado, tipo) VALUES (5, 'MF PIERO', 'MUFA PIERO', 'MUFA')")
    con.executemany("INSERT INTO nodo_apariciones(nodo_id, archivo_id, rol) VALUES (5, ?, ?)", [(1, "red"), (2, "principal")])
    assert piloto_fusiones.buscar_diagrama(con, "2" * 32)[:2] == (2, "2" * 32)
    assert piloto_fusiones.buscar_diagrama(con, "mf piero") == (2, "2" * 32, "Z/3 Mufa Piero.vsd", "MF PIERO")
    assert piloto_fusiones.buscar_diagrama(con, "RED.vsd")[0] == 1
    assert piloto_fusiones.buscar_diagrama(con, "NO EXISTE") is None


def test_metricas_precision_y_cobertura(tmp_path, capsys):
    carpeta = tmp_path / "marcas"
    carpeta.mkdir()
    campos = ["archivo_id", "md5", "mufa", "fusion_id", "confianza", "entrada", "salida", "color_tia", "marca",
              "reales_en_diagrama"]
    with open(carpeta / "marcas_1.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(campos)
        for i, (conf, marca) in enumerate([(0.9, "correcto"), (0.8, "correcto"), (0.5, "incorrecto"), (0.2, "")], 1):
            w.writerow([1, "a", "MF UNO", i, conf, "e", "s", "3 verde", marca, 5])
    with open(carpeta / "marcas_2.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(campos)
        w.writerow([2, "b", "MF DOS", "", "", "", "", "", "", 3])    # nothing detected, 3 real fusions

    resumen = piloto_fusiones.metricas(piloto_fusiones.leer_marcas([str(carpeta)]))
    assert resumen["total"] == {"det": 4, "marc": 3, "corr": 2, "reales": 8}
    u07 = next(u for u in resumen["por_umbral"] if u["umbral"] == 0.7)
    assert (u07["detectadas"], u07["correctas"], u07["precision"], u07["cobertura"]) == (2, 2, 1.0, 0.25)
    assert "1 fusiones detectadas todavía sin marcar" in capsys.readouterr().out


def test_reporte_html_no_rompe_el_script_con_textos_raros(odg, tmp_path):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(fusiones.DDL_SQLITE)
    detectadas = fusiones.extraer_fusiones(odg)
    detectadas[0]["entrada"] = "cliente </script><b>x</b>"
    fusiones.guardar(con, 1, detectadas)
    filas = con.execute("SELECT * FROM fusiones_piloto").fetchall()
    destino = tmp_path / "r.html"
    piloto_fusiones.reporte_html(destino, "MF <PRUEBA>", (1, "f" * 32, "Z/x.vsd"), filas, "img/x.png",
                                 (6000, 4000), (30.0, 20.0))
    texto = destino.read_text(encoding="utf-8")
    assert texto.count("</script>") == 1 and "<\\/script>" in texto
    assert "MF &lt;PRUEBA&gt;" in texto and 'viewBox="0 0 30.000 20.000"' in texto
