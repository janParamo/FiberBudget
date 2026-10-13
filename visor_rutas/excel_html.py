"""Una hoja de un presupuesto generado (.xlsx) como tabla HTML, para verla dentro del visor.

Muestra VALORES, nunca fórmulas: los que dejó recalc.py (LibreOffice) en el archivo. Sin
LibreOffice (calculado=False) las celdas con fórmula se muestran "—", porque el valor guardado
sería el de la plantilla vacía. Respeta anchos de columna, altos de fila, celdas combinadas,
filas/columnas ocultas, fuente (negrita, cursiva, subrayado, tamaño, color), relleno, bordes,
alineación y formatos de número/moneda/porcentaje/fecha básicos. Las imágenes de la hoja (logo,
mapa de la ruta) se colocan en su ancla como <img> con data URL.
"""
import base64
import colorsys
import html
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

MAX_FILAS = 250
MAX_COLUMNAS = 30
EMU_POR_PX = 9525
ANCHO_DEFECTO = 8.43                 # Excel's default column width (characters)
ALTO_DEFECTO_PT = 15.0
PX_POR_CARACTER = 7                  # Calibri 11 / Arial 10 digit width, as excel_generator._column_px
_BORDES = {"thin": "1px solid", "hair": "1px solid", "medium": "2px solid", "thick": "3px solid",
           "dashed": "1px dashed", "mediumDashed": "2px dashed", "dotted": "1px dotted", "double": "3px double",
           "dashDot": "1px dashed", "mediumDashDot": "2px dashed", "dashDotDot": "1px dotted",
           "mediumDashDotDot": "2px dotted", "slantDashDot": "2px dashed"}
_TEMA_POR_DEFECTO = ["FFFFFF", "000000", "EEECE1", "1F497D", "4F81BD", "C0504D", "9BBB59", "8064A2",
                     "4BACC6", "F79646", "0000FF", "800080"]
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


# --------------------------------------------------------------------------- colores

def _colores_tema(libro: Any) -> list[str]:
    """Theme colors in Excel's index order (lt1, dk1, lt2, dk2, accent1..6, hlink, folHlink)."""
    try:
        raiz = ElementTree.fromstring(libro.loaded_theme)
        esquema = raiz.find(f".//{_A}clrScheme")
        colores = []
        for nodo in list(esquema):
            hijo = list(nodo)[0]
            colores.append(hijo.get("lastClr") or hijo.get("val") or "000000")
        if len(colores) >= 12:
            dk1, lt1, dk2, lt2, *resto = colores
            return [lt1, dk1, lt2, dk2, *resto]
    except Exception:
        pass
    return list(_TEMA_POR_DEFECTO)


def _aplicar_tinte(rgb: str, tinte: float) -> str:
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1 + tinte) if tinte < 0 else l * (1 - tinte) + tinte
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), s)
    return "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def _css_color(color: Any, tema: list[str]) -> str | None:
    if color is None:
        return None
    try:
        tipo = color.type
        if tipo == "rgb" and isinstance(color.rgb, str) and len(color.rgb) >= 6:
            return "#" + color.rgb[-6:]               # ARGB: the alpha byte is ignored, as Excel does
        if tipo == "theme" and color.theme is not None and color.theme < len(tema):
            rgb = tema[color.theme]
            return "#" + (_aplicar_tinte(rgb, float(color.tint or 0)) if color.tint else rgb)
        if tipo == "indexed" and color.indexed is not None and color.indexed < len(COLOR_INDEX):
            if color.indexed in (64, 65):             # system foreground / background
                return None
            return "#" + COLOR_INDEX[color.indexed][-6:]
    except (AttributeError, TypeError, ValueError):
        return None
    return None


# --------------------------------------------------------------------------- números

def _es_formula(valor: Any) -> bool:
    return isinstance(valor, ArrayFormula) or (isinstance(valor, str) and valor.startswith("="))


def _seccion_formato(formato: str, valor: float) -> str:
    partes = formato.split(";")
    if valor < 0 and len(partes) > 1:
        return partes[1]
    if valor == 0 and len(partes) > 2:
        return partes[2]
    return partes[0]


def _simbolo(formato: str) -> tuple[str, str]:
    """(prefix, suffix) currency/literal text of a number format section."""
    texto = re.sub(r"\[\$([^\]-]*)(?:-[^\]]*)?\]", lambda m: f'"{m.group(1)}"', formato)
    texto = re.sub(r"\[[^\]]*\]", "", texto)          # colors / conditions
    texto = re.sub(r"_.|\*.", "", texto)               # padding
    numero = re.search(r"[#0?][#0?,.\s]*", texto)
    if not numero:
        return "", ""
    limpiar = lambda s: re.sub(r'["\\]', "", s).replace("(", "").replace(")", "").strip()
    return limpiar(texto[:numero.start()]), limpiar(texto[numero.end():].replace("%", ""))


def formatear_numero(valor: float, formato: str | None) -> str:
    formato = (formato or "General").strip()
    if formato.lower() == "general" or not re.search(r"[0#?]", formato):
        if float(valor).is_integer():
            return f"{int(valor):,}".replace(",", " ") if abs(valor) >= 10000 else str(int(valor))
        return f"{valor:.10g}"
    seccion = _seccion_formato(formato, valor)
    signo_propio = ";" in formato and valor < 0          # the negative section writes the sign itself
    limpio = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", seccion)   # literals, colors, padding
    if not re.search(r"[0#]", limpio):        # e.g. the accounting zero section _-"C$"* "-"??_- -> "C$ -"
        return " ".join(re.findall(r'"([^"]*)"', seccion)) or "0"
    porcentaje = "%" in limpio
    numero = (abs(valor) if signo_propio else valor) * (100 if porcentaje else 1)
    decimal = re.search(r"\.([0#?]+)", limpio)
    decimales = len(decimal.group(1)) if decimal else 0
    miles = bool(re.search(r"[#0?],[#0?]", limpio))
    texto = f"{numero:,.{decimales}f}" if miles else f"{numero:.{decimales}f}"
    if porcentaje:
        texto += "%"
    prefijo, sufijo = _simbolo(seccion)
    if prefijo:
        texto = f"{prefijo}{' ' if len(prefijo) > 1 else ''}{texto}"     # "$1,234.00", "C$ 1,234.00"
    if sufijo:
        texto = f"{texto} {sufijo}"
    if signo_propio and "(" in seccion:
        texto = f"({texto})"
    elif signo_propio and "-" in limpio:
        texto = f"-{texto}"
    return texto


def _formatear(valor: Any, formato: str | None) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "VERDADERO" if valor else "FALSO"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y") if valor.time() == time() else valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, (int, float)):
        return formatear_numero(float(valor), formato)
    return str(valor)


# --------------------------------------------------------------------------- hoja

def _dimensiones_columnas(hoja: Any, columnas: int) -> tuple[list[int], list[bool]]:
    anchos = [round(ANCHO_DEFECTO * PX_POR_CARACTER + 5)] * (columnas + 1)
    ocultas = [False] * (columnas + 1)
    defecto = hoja.sheet_format.defaultColWidth
    if defecto:
        anchos = [round(defecto * PX_POR_CARACTER + 5)] * (columnas + 1)
    for clave, dim in hoja.column_dimensions.items():
        desde = dim.min or hoja[f"{clave}1"].column
        hasta = dim.max or desde
        for i in range(desde, min(hasta, columnas) + 1):
            if dim.width:
                anchos[i] = round(dim.width * PX_POR_CARACTER + 5)
            ocultas[i] = bool(dim.hidden)
    return anchos, ocultas


def _alto_fila(hoja: Any, fila: int) -> tuple[int, bool]:
    dim = hoja.row_dimensions.get(fila) if hasattr(hoja.row_dimensions, "get") else hoja.row_dimensions[fila]
    alto = (dim.ht if dim is not None and dim.ht else None) or hoja.sheet_format.defaultRowHeight or ALTO_DEFECTO_PT
    return round(alto * 96 / 72), bool(dim is not None and dim.hidden)


def _rango_usado(hoja_f: Any, imagenes: list[Any]) -> tuple[int, int]:
    filas = columnas = 1
    for fila in hoja_f.iter_rows():
        for celda in fila:
            if celda.value not in (None, ""):
                filas, columnas = max(filas, celda.row), max(columnas, celda.column)
    for rango in hoja_f.merged_cells.ranges:
        if hoja_f.cell(rango.min_row, rango.min_col).value not in (None, ""):
            filas, columnas = max(filas, rango.max_row), max(columnas, rango.max_col)
    for imagen in imagenes:
        ancla = getattr(imagen.anchor, "to", None) or getattr(imagen.anchor, "_from", None)
        if ancla is not None:
            filas, columnas = max(filas, ancla.row + 1), max(columnas, ancla.col + 1)
    return min(filas, MAX_FILAS), min(columnas, MAX_COLUMNAS)


def _estilo_celda(celda: Any, tema: list[str]) -> str:
    estilos = []
    fuente = celda.font
    if fuente is not None:
        if fuente.b:
            estilos.append("font-weight:700")
        if fuente.i:
            estilos.append("font-style:italic")
        if fuente.u:
            estilos.append("text-decoration:underline")
        if fuente.sz:
            estilos.append(f"font-size:{float(fuente.sz) * 96 / 72:.1f}px")
        color = _css_color(fuente.color, tema)
        if color and color.upper() != "#000000":
            estilos.append(f"color:{color}")
    relleno = celda.fill
    if relleno is not None and relleno.fill_type == "solid":
        color = _css_color(relleno.fgColor, tema)
        if color:
            estilos.append(f"background:{color}")
    borde = celda.border
    if borde is not None:
        for lado, css in (("top", "top"), ("right", "right"), ("bottom", "bottom"), ("left", "left")):
            linea = getattr(borde, lado)
            if linea is not None and linea.style:
                color = _css_color(linea.color, tema) or "#000000"
                estilos.append(f"border-{css}:{_BORDES.get(linea.style, '1px solid')} {color}")
    alineacion = celda.alignment
    horizontal = alineacion.horizontal if alineacion is not None else None
    if horizontal in ("center", "centerContinuous"):
        estilos.append("text-align:center")
    elif horizontal == "right":
        estilos.append("text-align:right")
    elif horizontal in ("left", "justify", "fill", "distributed"):
        estilos.append("text-align:left")
    elif isinstance(celda.value, (int, float)) and not isinstance(celda.value, bool):
        estilos.append("text-align:right")
    vertical = alineacion.vertical if alineacion is not None else None
    estilos.append({"top": "vertical-align:top", "center": "vertical-align:middle"}.get(vertical,
                                                                                         "vertical-align:bottom"))
    if alineacion is not None and alineacion.wrap_text:
        estilos.append("white-space:pre-wrap")
    return ";".join(estilos)


def _imagen_html(imagen: Any, x_col: list[int], y_fila: list[int]) -> str | None:
    """<img> placed at its anchor (pixels from the table's top-left corner)."""
    try:
        datos = imagen._data()
    except Exception:
        return None
    ancla = imagen.anchor
    desde = getattr(ancla, "_from", None)
    if desde is None:
        return None

    def punto(marca: Any) -> tuple[float, float]:
        col = min(marca.col, len(x_col) - 1)
        fila = min(marca.row, len(y_fila) - 1)
        return x_col[col] + marca.colOff / EMU_POR_PX, y_fila[fila] + marca.rowOff / EMU_POR_PX

    x, y = punto(desde)
    hasta = getattr(ancla, "to", None)
    if hasta is not None:
        x2, y2 = punto(hasta)
        ancho, alto = x2 - x, y2 - y
    else:
        extension = getattr(ancla, "ext", None)
        ancho = (extension.width if extension is not None else imagen.width * EMU_POR_PX) / EMU_POR_PX
        alto = (extension.height if extension is not None else imagen.height * EMU_POR_PX) / EMU_POR_PX
    if ancho <= 0 or alto <= 0:
        return None
    formato = (getattr(imagen, "format", None) or "png").lower()
    tipo = "image/jpeg" if formato in ("jpg", "jpeg") else f"image/{formato}"
    return (f'<img class="xl-img" alt="" style="left:{x:.0f}px;top:{y:.0f}px;width:{ancho:.0f}px;height:{alto:.0f}px" '
            f'src="data:{tipo};base64,{base64.b64encode(datos).decode("ascii")}">')


def hoja_a_html(xlsx: Path, nombre_hoja: str, calculado: bool) -> str:
    """HTML (<div class="hoja-excel">) de una hoja, con valores y sin fórmulas."""
    libro_v = load_workbook(xlsx, data_only=True)
    libro_f = load_workbook(xlsx, data_only=False)
    if nombre_hoja not in libro_f.sheetnames:
        raise KeyError(f"El Excel no tiene la hoja {nombre_hoja}")
    hoja_v, hoja_f = libro_v[nombre_hoja], libro_f[nombre_hoja]
    tema = _colores_tema(libro_f)
    imagenes = list(getattr(hoja_f, "_images", []))
    filas, columnas = _rango_usado(hoja_f, imagenes)
    anchos, col_ocultas = _dimensiones_columnas(hoja_f, columnas)

    # Merged ranges: anchor -> (rowspan, colspan) over visible rows/cols; covered cells skipped.
    altos = {}
    fila_oculta = {}
    for r in range(1, filas + 1):
        altos[r], fila_oculta[r] = _alto_fila(hoja_f, r)
    cubiertas: set[tuple[int, int]] = set()
    combinadas: dict[tuple[int, int], tuple[int, int]] = {}
    for rango in hoja_f.merged_cells.ranges:
        if rango.min_row > filas or rango.min_col > columnas:
            continue
        r2, c2 = min(rango.max_row, filas), min(rango.max_col, columnas)
        span_f = sum(1 for r in range(rango.min_row, r2 + 1) if not fila_oculta[r])
        span_c = sum(1 for c in range(rango.min_col, c2 + 1) if not col_ocultas[c])
        combinadas[(rango.min_row, rango.min_col)] = (max(span_f, 1), max(span_c, 1))
        for r in range(rango.min_row, r2 + 1):
            for c in range(rango.min_col, c2 + 1):
                if (r, c) != (rango.min_row, rango.min_col):
                    cubiertas.add((r, c))

    # Pixel position of every column / row start (hidden ones have no width) for the images.
    x_col = [0] * (columnas + 2)
    for c in range(1, columnas + 1):
        x_col[c] = x_col[c - 1] + (0 if col_ocultas[c] else anchos[c])
    x_col = [0] + x_col[:-1]            # x_col[i] = start of 0-based column i
    y_fila = [0] * (filas + 2)
    for r in range(1, filas + 1):
        y_fila[r] = y_fila[r - 1] + (0 if fila_oculta[r] else altos[r])
    y_fila = [0] + y_fila[:-1]

    partes = ['<colgroup>'] + [f'<col style="width:{anchos[c]}px">' for c in range(1, columnas + 1)
                                if not col_ocultas[c]] + ['</colgroup>']
    for r in range(1, filas + 1):
        if fila_oculta[r]:
            continue
        partes.append(f'<tr style="height:{altos[r]}px">')
        for c in range(1, columnas + 1):
            if col_ocultas[c] or (r, c) in cubiertas:
                continue
            celda_f = hoja_f.cell(r, c)
            atributos = ""
            if (r, c) in combinadas:
                span_f, span_c = combinadas[(r, c)]
                atributos += (f' rowspan="{span_f}"' if span_f > 1 else "") + (f' colspan="{span_c}"' if span_c > 1 else "")
            if _es_formula(celda_f.value) and not calculado:
                texto, clase = "—", ' class="sin-calculo" title="Se calcula al abrir en Excel (falta LibreOffice)"'
            else:
                valor = hoja_v.cell(r, c).value
                if _es_formula(valor):          # never show a formula, whatever is stored
                    valor = None
                texto, clase = _formatear(valor, celda_f.number_format), ""
            contenido = html.escape(texto).replace("\n", "<br>")
            partes.append(f'<td{atributos}{clase} style="{_estilo_celda(celda_f, tema)}">{contenido}</td>')
        partes.append("</tr>")
    ancho_total = sum(anchos[c] for c in range(1, columnas + 1) if not col_ocultas[c])
    imagenes_html = "".join(i for i in (_imagen_html(img, x_col, y_fila) for img in imagenes) if i)
    return (f'<div class="hoja-excel" style="width:{ancho_total}px">'
            f'<table class="xl" style="width:{ancho_total}px">{"".join(partes)}</table>{imagenes_html}</div>')
