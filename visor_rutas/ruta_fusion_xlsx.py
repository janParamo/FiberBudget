"""Agrega una franja al libro de rutas de fusión (visor v2, fase 4B), el del ejemplo y no uno nuevo.

El libro pesa varios MB (una hoja de 30 MB de XML), tiene comentarios en hilo, dibujos e imágenes. Regrabarlo con openpyxl los perdería,
así que la franja se escribe **a nivel XML**: se lee el .xlsx como zip, se agregan las filas al final de la hoja "2025 - 2026" (con las mismas
cajas, colores, bordes y celdas combinadas de la franja más reciente: se usan los mismos estilos del libro, no se crea ninguno), y el resto
de las partes del zip se copian tal cual. Lo que ya existe no se toca. Antes de reemplazar el archivo:
  - se avisa si está abierto en Excel (archivo bloqueado o `~$nombre.xlsx` al lado): entonces no se escribe;
  - se guarda un respaldo del libro (los últimos N) y se escribe en un archivo temporal, que se verifica (zip íntegro, XML bien formado,
    filas y combinadas nuevas, partes intactas) antes de reemplazar con un cambio atómico.

La franja (bloque izquierdo A–D): barra verde con la fecha, Cliente (vacío si el presupuesto fue a mano), Diagramas y Cuadrilla (vacías: no
se tocan), una caja blanca por mufa a intervenir (del cliente hacia la potencia), avisos en rojo, "COMPARTIR POTENCIA DEL SP" si aplica y
"RUTA SUGERIDA" (con el mapa de la ruta debajo, si se pasa). Siempre se agrega una franja nueva al final de la hoja.
"""
import io
import logging
import math
import os
import re
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

HOJA = "2025 - 2026"
FILAS_ENTRE_FRANJAS = 2
COLUMNAS_FRANJA = "ABCDEFGHI"
# style ids of the workbook's own cellXfs (read from its latest strips)
ESTILO = {"fecha": 398, "etiqueta": 202, "cliente": (383, 384, 385), "diagramas": (346, 347, 348), "cuadrilla": (316, 303, 91, 303),
          "separador": (331, 332, 332, 333), "caja_arriba": (371, 372, 372, 373), "caja_medio": (374, 375, 375, 376),
          "caja_abajo": (434, 435, 435, 436), "aviso": 1012, "compartir": (377, 378, 378, 379), "ruta": (380, 381, 381, 382)}
EMU_FILA = 15 * 12700
ANCHO_IMAGEN_EMU = 5095875
MAX_FILAS_IMAGEN = 24
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}


class ExcelAbierto(Exception):
    """The workbook is open in Excel (or cannot be written): nothing was changed."""


class LibroNoValido(Exception):
    """The file is not a workbook this module can add a strip to."""


# --------------------------------------------------------------------------- piezas de la hoja

def serie_fecha(f: date) -> int:
    return (f - date(1899, 12, 30)).days


def _celda(ref: str, estilo: int, texto: str | None = None, numero: int | None = None) -> str:
    if numero is not None:
        return f'<c r="{ref}" s="{estilo}"><v>{numero}</v></c>'
    if texto:
        return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{escape(texto)}</t></is></c>'
    return f'<c r="{ref}" s="{estilo}"/>'


def _fila(n: int, celdas: list[str], alto: float = 15, fijo: bool = False) -> str:
    atributos = f'r="{n}" spans="1:9" ht="{alto:g}"' + (' customHeight="1"' if fijo else "")
    return f"<row {atributos}>{''.join(celdas)}</row>" if celdas else f"<row {atributos}/>"


def _filas_de_caja(n0: int, filas: int, texto: str, estilo_aviso: bool = False) -> list[str]:
    """A box of the strip: `filas` rows merged A:D, the text centred; borders from the workbook's outline styles."""
    salida = []
    for i in range(filas):
        if estilo_aviso:
            e = (ESTILO["aviso"],) * 4
        elif i == 0:
            e = ESTILO["caja_arriba"]
        elif i == filas - 1:
            e = ESTILO["caja_abajo"]
        else:
            e = ESTILO["caja_medio"]
        n = n0 + i
        salida.append(_fila(n, [_celda(f"{c}{n}", e[k], texto if (k == 0 and i == 0) else None) for k, c in enumerate("ABCD")], 15, fijo=True))
    return salida


def filas_necesarias(texto: str) -> int:
    """2 rows for a short text, 4 or 6 for a longer one (a box is ~80 characters wide)."""
    lineas = math.ceil(max(1, len(texto)) / 78)
    return 2 if lineas <= 2 else (4 if lineas <= 4 else (6 if lineas <= 6 else 8))


def construir_franja(inicio: int, fecha: date, cliente: str | None, lineas: list[str], avisos: list[str], compartir: bool,
                     filas_imagen: int = 0) -> dict[str, Any]:
    """The XML of the strip starting at row `inicio`: {"filas": "<row…>", "combinadas": [refs], "ultima": last row used,
    "fila_ruta": row of RUTA SUGERIDA}."""
    filas: list[str] = []
    combinadas: list[str] = []
    r = inicio
    filas.append(_fila(r, [_celda(f"{c}{r}", ESTILO["fecha"], numero=serie_fecha(fecha) if c == "A" else None) for c in COLUMNAS_FRANJA]))
    filas.append(_fila(r + 1, [_celda(f"{c}{r + 1}", ESTILO["fecha"]) for c in COLUMNAS_FRANJA]))
    combinadas.append(f"A{r}:I{r + 1}")
    filas.append(_fila(r + 2, []))
    r += 3
    e = ESTILO["cliente"]
    filas.append(_fila(r, [_celda(f"A{r}", ESTILO["etiqueta"], "Cliente"), _celda(f"B{r}", e[0], cliente or None), _celda(f"C{r}", e[1]), _celda(f"D{r}", e[2])], 15.75))
    combinadas.append(f"B{r}:D{r}")
    e = ESTILO["diagramas"]
    filas.append(_fila(r + 1, [_celda(f"A{r + 1}", ESTILO["etiqueta"], "Diagramas")] + [_celda(f"{c}{r + 1}", e[k]) for k, c in enumerate("BCD")], 15.75))
    e = ESTILO["cuadrilla"]
    filas.append(_fila(r + 2, [_celda(f"A{r + 2}", e[0], "Cuadrilla")] + [_celda(f"{c}{r + 2}", e[k + 1]) for k, c in enumerate("BCD")]))
    e = ESTILO["separador"]
    filas.append(_fila(r + 3, [_celda(f"{c}{r + 3}", e[k]) for k, c in enumerate("ABCD")]))
    r += 4
    for texto in lineas:
        n = filas_necesarias(texto)
        filas += _filas_de_caja(r, n, texto)
        combinadas.append(f"A{r}:D{r + n - 1}")
        r += n
    for texto in avisos:
        n = filas_necesarias(texto)
        filas += _filas_de_caja(r, n, texto, estilo_aviso=True)
        combinadas.append(f"A{r}:D{r + n - 1}")
        r += n
    if compartir:
        e = ESTILO["compartir"]
        filas.append(_fila(r, [_celda(f"{c}{r}", e[k], "COMPARTIR POTENCIA DEL SP" if k == 0 else None) for k, c in enumerate("ABCD")]))
        combinadas.append(f"A{r}:D{r}")
        r += 1
    e = ESTILO["ruta"]
    filas.append(_fila(r, [_celda(f"{c}{r}", e[k], "RUTA SUGERIDA" if k == 0 else None) for k, c in enumerate("ABCD")]))
    combinadas.append(f"A{r}:D{r}")
    return {"filas": "".join(filas), "combinadas": combinadas, "ultima": r + filas_imagen, "fila_ruta": r}


# --------------------------------------------------------------------------- partes del libro

def _hoja_y_relaciones(partes: dict[str, bytes], hoja: str) -> tuple[str, str | None, str | None]:
    """(path of the sheet's XML, path of its drawing or None, path of the drawing's rels or None)."""
    libro = partes["xl/workbook.xml"].decode("utf-8")
    m = re.search(r'<sheet [^>]*name="%s"[^>]*r:id="([^"]+)"' % re.escape(escape(hoja)), libro)
    if not m:
        raise LibroNoValido(f"El libro no tiene la hoja «{hoja}»")
    rels = partes["xl/_rels/workbook.xml.rels"].decode("utf-8")
    t = re.search(r'<Relationship [^>]*Id="%s"[^>]*Target="([^"]+)"' % re.escape(m.group(1)), rels) or \
        re.search(r'<Relationship [^>]*Target="([^"]+)"[^>]*Id="%s"' % re.escape(m.group(1)), rels)
    if not t:
        raise LibroNoValido("No se encontró la parte de la hoja en el libro")
    hoja_xml = "xl/" + t.group(1).lstrip("/").removeprefix("xl/")
    rels_hoja = hoja_xml.replace("worksheets/", "worksheets/_rels/") + ".rels"
    dibujo = rels_dibujo = None
    if rels_hoja in partes:
        r = partes[rels_hoja].decode("utf-8")
        d = re.search(r'<Relationship [^>]*Target="([^"]*drawings/[^"]+)"[^>]*Type="[^"]*/drawing"|<Relationship [^>]*Type="[^"]*/drawing"[^>]*Target="([^"]+)"', r)
        if d:
            destino = d.group(1) or d.group(2)
            dibujo = "xl/drawings/" + destino.rsplit("/", 1)[-1]
            rels_dibujo = f"xl/drawings/_rels/{destino.rsplit('/', 1)[-1]}.rels"
    return hoja_xml, dibujo, rels_dibujo


def ultima_fila_con_datos(xml: str) -> int:
    """The last row of the sheet that holds a value (styled empty rows do not count)."""
    inicio = xml.index("<sheetData>")
    fin = xml.index("</sheetData>")
    cuerpo = xml[inicio:fin]
    posiciones = [(m.start(), int(m.group(1))) for m in re.finditer(r'<row r="(\d+)"', cuerpo)]
    for k in range(len(posiciones) - 1, -1, -1):
        desde = posiciones[k][0]
        hasta = posiciones[k + 1][0] if k + 1 < len(posiciones) else len(cuerpo)
        trozo = cuerpo[desde:hasta]
        if "<v>" in trozo or "<is>" in trozo:
            return posiciones[k][1]
    return 0


def _ultima_fila_de_imagenes(dibujo: bytes | None) -> int:
    if not dibujo:
        return 0
    filas = [int(x) for x in re.findall(r"<xdr:to>.*?<xdr:row>(\d+)</xdr:row>", dibujo.decode("utf-8"), re.S)]
    return max(filas) + 1 if filas else 0


def _agregar_imagen(partes: dict[str, bytes], dibujo: str, rels_dibujo: str, png: bytes, fila_ruta: int, filas: int, alto_emu: int, nombre: str) -> None:
    d = partes[dibujo].decode("utf-8")
    rels = partes[rels_dibujo].decode("utf-8") if rels_dibujo in partes else \
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
    numero = max([int(x) for x in re.findall(r'Id="rId(\d+)"', rels)] + [0]) + 1
    media = max([int(x) for x in re.findall(r"media/image(\d+)\.", " ".join(partes))] + [0]) + 1
    ident = max([int(x) for x in re.findall(r'<xdr:cNvPr id="(\d+)"', d)] + [1]) + 1
    ruta_media = f"xl/media/image{media}.png"
    partes[ruta_media] = png
    nueva = (f'<Relationship Id="rId{numero}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image{media}.png"/>')
    partes[rels_dibujo] = rels.replace("</Relationships>", nueva + "</Relationships>").encode("utf-8")
    ancla = (f'<xdr:twoCellAnchor editAs="oneCell"><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{fila_ruta}</xdr:row><xdr:rowOff>9525</xdr:rowOff></xdr:from>'
             f'<xdr:to><xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{fila_ruta + filas}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
             f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{ident}" name="{escape(nombre)}"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
             f'<xdr:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rId{numero}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
             f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{ANCHO_IMAGEN_EMU}" cy="{alto_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:twoCellAnchor>')
    partes[dibujo] = d.replace("</xdr:wsDr>", ancla + "</xdr:wsDr>").encode("utf-8")


def _medidas_png(png: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(png)) as im:
        return im.size


# --------------------------------------------------------------------------- escritura segura

def _exigir_cerrado(xlsx: Path) -> None:
    candado = xlsx.parent / f"~${xlsx.name}"
    if candado.exists():
        raise ExcelAbierto(f"El libro está abierto en Excel ({candado.name}): ciérrelo y vuelva a exportar")
    try:
        with open(xlsx, "r+b"):
            pass
    except PermissionError as exc:
        raise ExcelAbierto("El libro está abierto en Excel o no se puede escribir: ciérrelo y vuelva a exportar") from exc


def _verificar(destino: Path, partes_originales: dict[str, bytes], tocadas: set[str], hoja_xml: str, esperado: dict[str, Any]) -> None:
    with zipfile.ZipFile(destino) as z:
        if z.testzip() is not None:
            raise LibroNoValido("El archivo escrito no pasó la verificación del zip")
        nombres = set(z.namelist())
        faltan = set(partes_originales) - nombres
        if faltan:
            raise LibroNoValido(f"Faltan partes en el archivo escrito: {sorted(faltan)[:3]}")
        for nombre in set(partes_originales) - tocadas:
            if z.read(nombre) != partes_originales[nombre]:
                raise LibroNoValido(f"Una parte que no debía cambiar cambió: {nombre}")
        filas = fusionadas = 0
        ultima = 0
        with z.open(hoja_xml) as f:
            for evento, el in ET.iterparse(f, events=("end",)):
                etiqueta = el.tag.rsplit("}", 1)[-1]
                if etiqueta == "row":
                    filas += 1
                    numero = int(el.get("r"))
                    if numero <= ultima:
                        raise LibroNoValido(f"Fila repetida o desordenada en la hoja escrita: {numero}")
                    ultima = numero
                    el.clear()
                elif etiqueta == "mergeCell":
                    fusionadas += 1
        if filas != esperado["filas"] or fusionadas != esperado["combinadas"] or ultima != esperado["ultima_fila"]:
            raise LibroNoValido(f"La hoja escrita no coincide con lo esperado ({filas} filas, {fusionadas} combinadas, última {ultima})")


def agregar_franja(xlsx: Path, *, fecha: date | None = None, cliente: str | None = None, lineas: list[str], avisos: list[str] | None = None,
                   compartir: bool = False, imagen: bytes | None = None, respaldos: Path | None = None, conservar: int = 10,
                   hoja: str = HOJA) -> dict[str, Any]:
    """Appends the strip of a fusion route to the sheet `hoja` of `xlsx`. Returns {"hoja", "fila_inicial", "fila_final", "respaldo", "avisos"}.
    ExcelAbierto when the workbook is open in Excel; LibroNoValido when it is not the expected workbook. Nothing is changed on failure."""
    xlsx = Path(xlsx)
    if not xlsx.is_file():
        raise LibroNoValido(f"No se encontró el libro de rutas de fusión: {xlsx}")
    if not [l for l in lineas if str(l).strip()]:
        raise LibroNoValido("La ruta de fusión no tiene pasos que escribir")
    _exigir_cerrado(xlsx)
    fecha = fecha or date.today()
    with zipfile.ZipFile(xlsx) as z:
        informacion = {i.filename: i for i in z.infolist()}
        orden = list(informacion)
        partes = {n: z.read(n) for n in orden}
    originales = dict(partes)
    hoja_xml, dibujo, rels_dibujo = _hoja_y_relaciones(partes, hoja)
    xml = partes[hoja_xml].decode("utf-8")
    if "<sheetData>" not in xml or "</sheetData>" not in xml or "<mergeCells" not in xml:
        raise LibroNoValido("La hoja no tiene la estructura esperada (datos y celdas combinadas)")
    ultima_imagen = _ultima_fila_de_imagenes(partes.get(dibujo)) if dibujo else 0
    inicio = _fila_de_inicio(xml, ultima_imagen)
    filas_imagen = alto_emu = 0
    avisos_salida: list[str] = []
    if imagen:
        if not dibujo or not rels_dibujo:
            avisos_salida.append("La hoja no tiene capa de dibujos: se agregó la franja sin el mapa de la ruta")
            imagen = None
        else:
            ancho, alto = _medidas_png(imagen)
            alto_emu = int(ANCHO_IMAGEN_EMU * alto / max(1, ancho))
            filas_imagen = min(MAX_FILAS_IMAGEN, math.ceil(alto_emu / EMU_FILA) + 1)
            alto_emu = min(alto_emu, (filas_imagen - 1) * EMU_FILA)
    franja = construir_franja(inicio, fecha, cliente, [str(l) for l in lineas], [str(a) for a in (avisos or [])], compartir, filas_imagen)
    # sheetData
    cierre = xml.index("</sheetData>")
    xml = xml[:cierre] + franja["filas"] + xml[cierre:]
    # mergeCells
    m = re.search(r'<mergeCells count="(\d+)">', xml)
    if not m:
        raise LibroNoValido("No se encontró la lista de celdas combinadas")
    cuenta = int(m.group(1))
    xml = xml.replace(m.group(0), f'<mergeCells count="{cuenta + len(franja["combinadas"])}">', 1)
    cierre_m = xml.index("</mergeCells>")
    xml = xml[:cierre_m] + "".join(f'<mergeCell ref="{r}"/>' for r in franja["combinadas"]) + xml[cierre_m:]
    # dimension (keeps the columns it has; only the last row grows)
    d = re.search(r'<dimension ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"/>', xml)
    if d and int(d.group(4)) < franja["ultima"]:
        xml = xml.replace(d.group(0), f'<dimension ref="{d.group(1)}{d.group(2)}:{d.group(3)}{franja["ultima"]}"/>', 1)
    partes[hoja_xml] = xml.encode("utf-8")
    tocadas = {hoja_xml}
    if imagen:
        _agregar_imagen(partes, dibujo, rels_dibujo, imagen, franja["fila_ruta"], filas_imagen - 1, alto_emu, f"Ruta sugerida {fecha:%Y%m%d}")
        tocadas |= {dibujo, rels_dibujo} | {n for n in partes if n not in originales}
    # temp file, verification, backup, atomic replace
    temporal = xlsx.with_name(f".{xlsx.stem}.nuevo.tmp")
    try:
        with zipfile.ZipFile(temporal, "w") as z:
            for nombre in orden + [n for n in partes if n not in informacion]:
                info = informacion.get(nombre)
                nuevo = zipfile.ZipInfo(nombre, date_time=info.date_time if info else datetime.now().timetuple()[:6])
                nuevo.compress_type = zipfile.ZIP_DEFLATED
                nuevo.external_attr = info.external_attr if info else 0
                z.writestr(nuevo, partes[nombre], compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        original = originales[hoja_xml].decode("utf-8")
        nuevas = [int(x) for x in re.findall(r'<row r="(\d+)"', franja["filas"])]
        _verificar(temporal, originales, tocadas, hoja_xml,
                   {"filas": len(re.findall(r"<row ", original)) + len(nuevas), "combinadas": cuenta + len(franja["combinadas"]),
                    "ultima_fila": max(ultima_fila_xml(original), max(nuevas))})
        respaldo = None
        if respaldos is not None:
            respaldos.mkdir(parents=True, exist_ok=True)
            respaldo = respaldos / f"{xlsx.stem}.{datetime.now():%Y%m%d-%H%M%S}{xlsx.suffix}"
            shutil.copy2(xlsx, respaldo)
            for viejo in sorted(respaldos.glob(f"{xlsx.stem}.*{xlsx.suffix}"))[:-max(1, conservar)]:
                viejo.unlink(missing_ok=True)
        try:
            os.replace(temporal, xlsx)
        except PermissionError as exc:
            raise ExcelAbierto("El libro está abierto en Excel o no se puede escribir: ciérrelo y vuelva a exportar") from exc
    finally:
        temporal.unlink(missing_ok=True)
    log.info("Fusion route strip added to %s (%s rows %d-%d)", xlsx.name, hoja, inicio, franja["ultima"])
    return {"hoja": hoja, "fila_inicial": inicio, "fila_final": franja["ultima"], "fila_ruta": franja["fila_ruta"], "respaldo": str(respaldo) if respaldo else None,
            "archivo": str(xlsx), "avisos": avisos_salida}


def _fila_de_inicio(xml: str, ultima_imagen: int) -> int:
    """First row of the new strip: after EVERY existing row (also the empty, pre-formatted ones: nothing that exists is overwritten or
    removed) and after the last picture, leaving FILAS_ENTRE_FRANJAS empty rows from the previous strip (empty rows at the end count)."""
    ultima = ultima_fila_xml(xml)
    if ultima_imagen > ultima:                      # a picture reaches below the last row: the gap starts after it
        return ultima_imagen + 1 + FILAS_ENTRE_FRANJAS
    cuerpo = xml[:xml.index("</sheetData>")][-4000:]
    vacias = 0
    for n in range(ultima, ultima - FILAS_ENTRE_FRANJAS, -1):
        if re.search(r'<row r="%d"[^>]*/>' % n, cuerpo):
            vacias += 1
        else:
            break
    return ultima + 1 + max(0, FILAS_ENTRE_FRANJAS - vacias)


def ultima_fila_xml(xml: str) -> int:
    """The highest row number in the sheet (empty rows included)."""
    i = xml.index("</sheetData>")
    m = list(re.finditer(r'<row r="(\d+)"', xml[max(0, i - 400):i]))
    if m:
        return int(m[-1].group(1))
    return max(int(x) for x in re.findall(r'<row r="(\d+)"', xml[:i]))
