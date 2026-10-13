"""Fill the company's Excel template while preserving its package contents."""
import logging
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.formula import ArrayFormula

log = logging.getLogger(__name__)

PROTECTED_SHEETS = {"COSTOS", "MATERIALES", "Variación de costos"}
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"main": MAIN_NS, "rel": REL_NS, "package": PACKAGE_REL_NS}
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Text cells on "Presupuesto" outside Mano de Obra are located in the template, not
# hard-coded, so inserted rows do not break them: the client name goes to the cell the
# "PRESUPUESTO DE OBRA - <cliente>" title formula reads, the comment to the merged box
# right below the "Comentarios:" label.
TITLE_TEXT = "PRESUPUESTO DE OBRA"
COMMENT_LABEL = "comentarios"
COMMENT_SEPARATOR = "--- Comentario original del ticket ---"
PREPARED_BY = "Fiber_Budget"
EXCEL_CELL_MAX_CHARS = 32767
# TEXT() date codes depend on Excel's language (Spanish Excel expects "aaaa", so "yyyy"
# prints literally). Such calls are rewritten with DAY/MONTH/YEAR, which work in any locale.
_LOCALE_DATE_TEXT = re.compile(r'TEXT\(((?:[^(),"]|\([^()]*\))+),"DD/MM/YYYY"\)', re.IGNORECASE)
# Characters XML 1.0 forbids; a ticket comment containing one would corrupt the workbook.
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


class Formula(str):
    """Marks a value to be written as a formula (without the leading "=")."""


def _locale_independent_date_formulas(ws: Any) -> dict[str, Formula]:
    """Rewrite TEXT(x,"DD/MM/yyyy") formulas so the year renders in any Excel language."""
    assignments = {}
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("=") and _LOCALE_DATE_TEXT.search(cell.value):
                rewritten = _LOCALE_DATE_TEXT.sub(
                    lambda m: (f'TEXT(DAY({m[1]}),"00")&"/"&TEXT(MONTH({m[1]}),"00")&"/"&YEAR({m[1]})'),
                    cell.value)
                assignments[cell.coordinate] = Formula(rewritten[1:])
    return assignments


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def _safe_file_stem(client_name: Any) -> str:
    """Turn a client name into a Windows-safe file-name prefix."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(client_name or ""))
    text = re.sub(r"\s+", "_", text.strip())
    return text[:100].strip("._") or "presupuesto"


def _find_required_sheet_name(wb: Any, expected: str) -> str | None:
    expected_normalized = _normalized(expected)
    for sheet_name in wb.sheetnames:
        actual_normalized = _normalized(sheet_name)
        if actual_normalized == expected_normalized:
            return sheet_name
        if expected_normalized == _normalized("Variación de costos") and actual_normalized.startswith(
                f"{expected_normalized} "):
            return sheet_name
    return None


def _find_exact_label_row(ws: Any, label: str, column: int = 5) -> int | None:
    for row in range(1, ws.max_row + 1):
        if ws.cell(row, column).value == label:
            return row
    return None


def _find_route_label(ws: Any, labels: list[str]) -> Any:
    expected = {_normalized(label) for label in labels}
    for row in ws.iter_rows():
        for cell in row:
            normalized_value = _normalized(cell.value)
            if normalized_value in expected or any(
                    normalized_value.startswith(f"{label}:")
                    or normalized_value.startswith(f"{label} ")
                    for label in expected):
                return cell
    raise ValueError(f"Route-sheet label not found: {labels[0]}")


def _route_assignment(ws: Any, labels: list[str], value: Any) -> tuple[str, Any]:
    label_cell = _find_route_label(ws, labels)
    current_value = str(label_cell.value or "")
    if ":" in current_value:
        prefix = current_value.split(":", 1)[0].rstrip()
        return label_cell.coordinate, f"{prefix}: {value}"
    for column in range(label_cell.column + 1, ws.max_column + 6):
        cell = ws.cell(label_cell.row, column)
        if isinstance(cell, MergedCell):
            continue
        if cell.value is None:
            return cell.coordinate, value
    raise ValueError(f"No writable cell found beside route-sheet label: {labels[0]}")


def _quantity_assignments(ws: Any, quantities: dict[str, int], manual_labels: set[str]) -> dict[str, Any]:
    assignments = {f"G{row}": 0 for row in range(12, 33)}
    for label, quantity in quantities.items():
        row = _find_exact_label_row(ws, label, column=5)
        if row is None:
            if label in manual_labels:
                continue
            raise ValueError(f"Budget row label not found in column E: {label}")
        assignments[f"G{row}"] = int(quantity)
    return assignments


def _client_name_cell(ws: Any) -> str:
    """Cell the "PRESUPUESTO DE OBRA - <cliente>" title formula takes the client name from."""
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if isinstance(value, str) and value.startswith("=") and TITLE_TEXT in value.upper():
                match = re.search(r"\$?([A-Z]{1,3})\$?(\d+)\s*\)\s*$", value)
                if match:
                    return f"{match[1]}{match[2]}"
    raise ValueError(f'No "{TITLE_TEXT}" title formula with a client-name cell found')


def _box_below_label(ws: Any, label: str) -> Any:
    """The merged box that starts right below the cell whose text starts with `label`."""
    for row in ws.iter_rows():
        for cell in row:
            if _normalized(cell.value).startswith(label):
                below = ws.cell(cell.row + 1, cell.column).coordinate
                box = next((rng for rng in ws.merged_cells.ranges if below in rng), None)
                if box is None or box.min_row != cell.row + 1:
                    raise ValueError(f"No merged box starts right below {cell.coordinate}")
                return box
    raise ValueError(f'"{label}" label not found')


PREPARED_BY_LABEL = "elaborado por"


def _prepared_by_cell(ws: Any) -> str | None:
    """Empty cell right of the "Elaborado por:" label (past its merged range), or None."""
    for row in ws.iter_rows():
        for cell in row:
            if _normalized(cell.value).startswith(PREPARED_BY_LABEL):
                label = next((rng for rng in ws.merged_cells.ranges if cell.coordinate in rng), None)
                column = (label.max_col if label else cell.column) + 1
                target = ws.cell(cell.row, column)
                return target.coordinate if target.value in (None, "") else None
    return None


def _comment_cell(ws: Any) -> str:
    """Anchor of the merged comment box directly below the "Comentarios:" label."""
    box = _box_below_label(ws, COMMENT_LABEL)
    return ws.cell(box.min_row, box.min_col).coordinate


# --- Route map picture ----------------------------------------------------------------------
# The map goes inside the "ESQUEMA DE RUTA PROYECTADA" box of the route sheet, where the
# technicians paste it by hand. It is added to the package directly (media, drawing,
# relationships, content types) so the template's own drawings stay untouched.
ROUTE_MAP_LABEL = "esquema de ruta proyectada"
MAP_UNAVAILABLE_TEXT = "Mapa no disponible"
EMU_PER_PX = 9525
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_DRAWING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


@dataclass
class PictureAnchor:
    """Picture pinned to two cell corners (0-based col/row plus pixel offsets): Excel stretches
    it between them, so it always fills the box whatever the cells' real pixel size.
    width_px/height_px are only the initial size hint."""
    col: int
    col_off_px: int
    row: int
    row_off_px: int
    to_col: int
    to_col_off_px: int
    to_row: int
    to_row_off_px: int
    width_px: int
    height_px: int


def _column_px(ws: Any, col: int, max_digit_px: int = 7) -> int:
    """Column width in screen pixels, as Excel computes it (7 px digits: Arial 10 / Calibri 11)."""
    from openpyxl.utils import get_column_letter
    width = ws.column_dimensions[get_column_letter(col)].width
    if not width:
        width = ws.sheet_format.defaultColWidth or (ws.sheet_format.baseColWidth or 8) + 0.43
    return int((256 * width + int(128 / max_digit_px)) / 256 * max_digit_px)


def _row_px(ws: Any, row: int) -> int:
    height = ws.row_dimensions[row].height or ws.sheet_format.defaultRowHeight or 15
    return int(round(height * 96 / 72))


def _box_anchor(ws: Any, box: Any, inset_px: int = 2) -> PictureAnchor:
    """Anchor filling the merged box corner to corner.

    The bottom-right corner is the start of the cell after the box (offset 0), not an
    offset inside its last column: Excel and LibreOffice (which makes the PDF) give
    columns different pixel widths, and an offset would leave a gap or overflow in one
    of them. The map is rendered with the box's proportions, so filling it does not distort it.
    """
    width = sum(_column_px(ws, c) for c in range(box.min_col, box.max_col + 1)) - inset_px
    height = sum(_row_px(ws, r) for r in range(box.min_row, box.max_row + 1)) - inset_px
    return PictureAnchor(box.min_col - 1, inset_px, box.min_row - 1, inset_px,
                         box.max_col, 0, box.max_row, 0, width, height)


def _next_rel_id(rels_xml: str) -> str:
    used = {int(n) for n in re.findall(r'Id="rId(\d+)"', rels_xml)}
    return f"rId{max(used, default=0) + 1}"


def _add_relationship(rels_xml: str | None, rel_type: str, target: str) -> tuple[str, str]:
    rels_xml = rels_xml or (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                            f'<Relationships xmlns="{PACKAGE_REL_NS}"></Relationships>')
    rel_id = _next_rel_id(rels_xml)
    entry = f'<Relationship Id="{rel_id}" Type="{rel_type}" Target="{target}"/>'
    return rels_xml.replace("</Relationships>", entry + "</Relationships>"), rel_id


def _rels_path(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", f"{name}.rels")


def _picture_anchor_xml(prefix: str, anchor: PictureAnchor, rel_id: str, shape_id: int) -> str:
    p = f"{prefix}:" if prefix else ""
    cx, cy = anchor.width_px * EMU_PER_PX, anchor.height_px * EMU_PER_PX
    def corner(tag: str, col: int, col_off: int, row: int, row_off: int) -> str:
        return (f"<{p}{tag}><{p}col>{col}</{p}col><{p}colOff>{col_off * EMU_PER_PX}</{p}colOff>"
                f"<{p}row>{row}</{p}row><{p}rowOff>{row_off * EMU_PER_PX}</{p}rowOff></{p}{tag}>")

    # editAs="twoCell": the picture spans from/to. With "oneCell" LibreOffice (the PDF) keeps
    # the stored size instead and leaves a gap where its columns are wider than Excel's.
    return (
        f'<{p}twoCellAnchor editAs="twoCell">'
        + corner("from", anchor.col, anchor.col_off_px, anchor.row, anchor.row_off_px)
        + corner("to", anchor.to_col, anchor.to_col_off_px, anchor.to_row, anchor.to_row_off_px) +
        f'<{p}pic xmlns:a="{_A_NS}" xmlns:r="{REL_NS}"><{p}nvPicPr>'
        f'<{p}cNvPr id="{shape_id}" name="Mapa ruta recomendada" descr="Ruta recomendada"/>'
        f'<{p}cNvPicPr><a:picLocks noChangeAspect="1"/></{p}cNvPicPr></{p}nvPicPr>'
        f'<{p}blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></{p}blipFill>'
        f'<{p}spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></{p}spPr></{p}pic><{p}clientData/></{p}twoCellAnchor>'
    )


def _insert_picture(xlsx_path: Path, sheet_part: str, anchor: PictureAnchor, png_path: Path) -> None:
    """Add a PNG to a worksheet's drawing (creating the drawing if the sheet has none)."""
    with zipfile.ZipFile(xlsx_path, "r") as source:
        parts = {name: source.read(name) for name in source.namelist()}

    def text(name: str) -> str:
        return parts[name].decode("utf-8")

    def optional_text(name: str) -> str | None:
        return text(name) if name in parts else None

    media = "xl/media/mapa_ruta.png"
    index = 1
    while media in parts:
        index += 1
        media = f"xl/media/mapa_ruta{index}.png"
    parts[media] = png_path.read_bytes()

    sheet_rels_part = _rels_path(sheet_part)
    sheet_rels = optional_text(sheet_rels_part)
    drawing_target = None
    if sheet_rels:
        match = re.search(rf'<Relationship\b[^>]*Type="{re.escape(_DRAWING_REL)}"[^>]*/>', sheet_rels)
        target = re.search(r'Target="([^"]+)"', match.group(0)) if match else None
        drawing_target = target.group(1) if target else None
    if drawing_target:
        drawing_part = posixpath.normpath(posixpath.join(posixpath.dirname(sheet_part), drawing_target))
    else:
        number = 1
        while f"xl/drawings/drawing{number}.xml" in parts:
            number += 1
        drawing_part = f"xl/drawings/drawing{number}.xml"
        parts[drawing_part] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                               f'<xdr:wsDr xmlns:xdr="{_DRAWING_NS}" xmlns:a="{_A_NS}"></xdr:wsDr>').encode()
        sheet_rels, sheet_rel_id = _add_relationship(sheet_rels, _DRAWING_REL, f"../drawings/drawing{number}.xml")
        parts[sheet_rels_part] = sheet_rels.encode("utf-8")
        sheet = text(sheet_part)
        prefix_match = re.search(r"<(?:(\w+):)?worksheet\b", sheet)
        p = f"{prefix_match.group(1)}:" if prefix_match and prefix_match.group(1) else ""
        element = f'<{p}drawing xmlns:r="{REL_NS}" r:id="{sheet_rel_id}"/>'
        # CT_Worksheet order: drawing precedes these elements.
        later = re.search(rf"<{p}(?:legacyDrawing|legacyDrawingHF|drawingHF|picture|oleObjects|controls|"
                          rf"webPublishItems|tableParts|extLst)\b|</{p}worksheet>", sheet)
        if later is None:
            raise ValueError(f"{sheet_part} has no closing worksheet element")
        parts[sheet_part] = f"{sheet[:later.start()]}{element}{sheet[later.start():]}".encode("utf-8")
        types = text("[Content_Types].xml")
        types = types.replace("</Types>", f'<Override PartName="/{drawing_part}" ContentType='
                                          f'"application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>')
        parts["[Content_Types].xml"] = types.encode("utf-8")

    drawing_rels_part = _rels_path(drawing_part)
    drawing_rels, image_rel_id = _add_relationship(
        optional_text(drawing_rels_part), _IMAGE_REL, posixpath.relpath(media, posixpath.dirname(drawing_part)))
    parts[drawing_rels_part] = drawing_rels.encode("utf-8")

    drawing = text(drawing_part)
    root = re.search(r"<(?:(\w+):)?wsDr\b", drawing)
    prefix = root.group(1) if root and root.group(1) else ""
    shape_id = max((int(n) for n in re.findall(r'cNvPr\s+id="(\d+)"', drawing)), default=0) + 1
    # First anchor = bottom layer: the template's own pictures (the north arrow over the map box)
    # stay in front of the map.
    root_open = re.search(r"<(?:\w+:)?wsDr\b[^>]*>", drawing)
    if root_open is None:
        raise ValueError(f"{drawing_part} has no wsDr element")
    picture = _picture_anchor_xml(prefix, anchor, image_rel_id, shape_id)
    drawing = f"{drawing[:root_open.end()]}{picture}{drawing[root_open.end():]}"
    parts[drawing_part] = drawing.encode("utf-8")

    types = text("[Content_Types].xml")
    if not re.search(r'<Default\s+Extension="png"', types, re.IGNORECASE):
        parts["[Content_Types].xml"] = types.replace(
            "<Override", '<Default Extension="png" ContentType="image/png"/><Override', 1).encode("utf-8")

    with NamedTemporaryFile(suffix=".xlsx", delete=False, dir=xlsx_path.parent) as tmp:
        temp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            for name, content in parts.items():
                target.writestr(name, content)
        temp_path.replace(xlsx_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _comment_text(existing: Any, raw_comment: str) -> str:
    """Keep the template's comment text and append the ticket comment verbatim."""
    block = f"{COMMENT_SEPARATOR}\n{raw_comment}"
    text = f"{existing}\n\n\n{block}" if existing not in (None, "") else block
    if len(text) > EXCEL_CELL_MAX_CHARS:
        raise ValueError(f"Comment cell exceeds Excel's {EXCEL_CELL_MAX_CHARS}-character limit")
    return text


def _validate_labor_assignments(assignments: dict[str, Any], text_cells: set[str]) -> None:
    """Prevent budget writes from reaching the workbook's formula-driven materials."""
    for coordinate, value in assignments.items():
        # Formula values only come from the date rewrite, which keeps the template's formula.
        if coordinate in text_cells or isinstance(value, Formula):
            continue
        match = re.fullmatch(r"[A-Z]+(\d+)", coordinate)
        if match is None or not 12 <= int(match.group(1)) <= 32:
            raise ValueError(f"Presupuesto write outside Mano de Obra rows 12-32: {coordinate}")


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall("package:Relationship", NS)
    }
    sheets = workbook.find("main:sheets", NS)
    if sheets is None:
        raise ValueError("Workbook has no sheets element")
    paths = {}
    for sheet in sheets:
        relation_id = sheet.attrib[f"{{{REL_NS}}}id"]
        target = targets[relation_id].lstrip("/")
        paths[sheet.attrib["name"]] = posixpath.normpath(
            target if target.startswith("xl/") else posixpath.join("xl", target))
    return paths


def _set_xml_cell(root: ElementTree.Element, coordinate: str, value: Any) -> None:
    cell = root.find(f".//main:c[@r='{coordinate}']", NS)
    if cell is None:
        sheet_data = root.find("main:sheetData", NS)
        if sheet_data is None:
            raise ValueError(f"Worksheet has no sheetData for cell {coordinate}")
        row_match = re.search(r"\d+", coordinate)
        if row_match is None:
            raise ValueError(f"Invalid worksheet cell coordinate: {coordinate}")
        row_number = int(row_match.group(0))
        row = next((item for item in sheet_data.findall("main:row", NS)
                    if int(item.attrib["r"]) == row_number), None)
        if row is None:
            row = ElementTree.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)})
        cell = ElementTree.SubElement(row, f"{{{MAIN_NS}}}c", {"r": coordinate})

    for child in list(cell):
        if child.tag in {f"{{{MAIN_NS}}}v", f"{{{MAIN_NS}}}f", f"{{{MAIN_NS}}}is"}:
            cell.remove(child)
    if isinstance(value, Formula):
        # No cached value: fullCalcOnLoad makes Excel compute it when the file opens.
        cell.attrib["t"] = "str"
        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}f").text = str(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.attrib["t"] = "n"
        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = str(value)
    else:
        text = _INVALID_XML_CHARS.sub("", str(value))
        cell.attrib["t"] = "inlineStr"
        inline = ElementTree.SubElement(cell, f"{{{MAIN_NS}}}is")
        text_element = ElementTree.SubElement(inline, f"{{{MAIN_NS}}}t")
        text_element.text = text
        if text != text.strip():
            text_element.set(f"{{{XML_NS}}}space", "preserve")


def _enable_full_calc_on_load(workbook_xml: bytes) -> bytes:
    """Make Excel recalculate every formula (including TODAY()) when the file opens.

    Patched as text instead of through ElementTree so workbook.xml keeps its
    namespace prefixes, which mc:Ignorable refers to by name.
    """
    text = workbook_xml.decode("utf-8")
    calc_pr = re.search(r"<calcPr\b[^>]*?/?>", text)
    if calc_pr is None:
        # CT_Workbook order: calcPr must precede these elements.
        anchor = re.search(r"<(?:oleSize|customWorkbookViews|pivotCaches|smartTagPr|smartTagTypes|"
                           r"webPublishing|fileRecoveryPr|webPublishObjects|extLst)\b|</workbook>", text)
        if anchor is None:
            raise ValueError("workbook.xml has no closing workbook element")
        text = f'{text[:anchor.start()]}<calcPr fullCalcOnLoad="1"/>{text[anchor.start():]}'
    else:
        tag = re.sub(r'\s+fullCalcOnLoad="[^"]*"', "", calc_pr.group(0))
        tag = re.sub(r"^<calcPr\b", '<calcPr fullCalcOnLoad="1"', tag)
        text = f"{text[:calc_pr.start()]}{tag}{text[calc_pr.end():]}"
    return text.encode("utf-8")


def _write_cells_preserving_package(template_path: Path, output_path: Path,
                                    assignments: dict[str, dict[str, Any]]) -> None:
    with zipfile.ZipFile(template_path, "r") as source, NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(template_path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
            for name in source.namelist():
                content = source.read(name)
                if name in assignments:
                    root = ElementTree.fromstring(content)
                    for coordinate, value in assignments[name].items():
                        _set_xml_cell(root, coordinate, value)
                    content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
                if name == "xl/workbook.xml":
                    content = _enable_full_calc_on_load(content)
                target.writestr(name, content)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _is_formula(value: Any) -> bool:
    return isinstance(value, ArrayFormula) or (isinstance(value, str) and value.startswith("="))


def _material_rows(ws: Any) -> dict[str, int]:
    """Normalized column-E label -> row, for the rows below the MATERIALES header."""
    header_row = next((row for row in range(1, ws.max_row + 1)
                       if _normalized(ws.cell(row, 3).value) == "materiales"), None)
    if header_row is None:
        raise ValueError("MATERIALES header not found in column C of Presupuesto")
    return {_normalized(ws.cell(row, 5).value): row for row in range(header_row + 1, ws.max_row + 1)
            if ws.cell(row, 5).value}


def _material_assignments(ws: Any, quantities: dict[str, int]) -> tuple[dict[str, int], list[str]]:
    """Map material labels to their quantity cells; return (assignments, labels with no row)."""
    rows = _material_rows(ws)
    assignments, missing = {}, []
    for label, quantity in quantities.items():
        row = rows.get(_normalized(label))
        if row is None:
            missing.append(label)
        else:
            assignments[f"G{row}"] = int(quantity)
    return assignments, missing


def _hardware_assignments(ws: Any, hardware: dict[str, Any]) -> dict[str, Any]:
    """Hanging-hardware rule for the route's cable type (cable.hardware_by_cable_type).

    A number is written as is; {"same_as": label} becomes a live formula pointing at that
    material's quantity cell, {"same_as_install": label} at that MANO DE OBRA row's quantity.
    These rows may replace template formulas: the rule asks for it.
    """
    rows = _material_rows(ws)

    def row_of(label: str) -> int:
        row = rows.get(_normalized(label))
        if row is None:
            raise ValueError(f"Hardware rule label not found in MATERIALES: {label}")
        return row

    def install_row_of(label: str) -> int:
        row = _find_exact_label_row(ws, label, column=5)
        if row is None:
            raise ValueError(f"Hardware rule label not found in MANO DE OBRA: {label}")
        return row

    assignments = {}
    for label, value in hardware.items():
        target = f"G{row_of(label)}"
        if isinstance(value, dict) and "same_as_install" in value:
            assignments[target] = Formula(f"G{install_row_of(value['same_as_install'])}")
        elif isinstance(value, dict):
            assignments[target] = Formula(f"G{row_of(value['same_as'])}")
        else:
            assignments[target] = int(value)
    return assignments


def _drop_formula_overwrites(ws: Any, assignments: dict[str, Any], allowed: set[str],
                             warnings: list[str]) -> None:
    """Never replace a template formula with a value unless a rule explicitly allows that cell."""
    for coordinate in list(assignments):
        if coordinate not in allowed and _is_formula(ws[coordinate].value):
            message = f"Template formula kept in {ws.title}!{coordinate}; value {assignments[coordinate]!r} not written"
            log.warning(message)
            warnings.append(message)
            del assignments[coordinate]


def _note_cell(ws: Any, column: str, rows_below_last: int) -> str:
    """Cell `rows_below_last` rows under the sheet's last cell with content, in `column`.

    A merged box (e.g. Comentarios) counts down to its last row: a value inside it would be hidden.
    """
    last_row = max((cell.row for row in ws.iter_rows() for cell in row if cell.value not in (None, "")),
                   default=0)
    last_row = max([last_row, *(merged.max_row for merged in ws.merged_cells.ranges)])
    return f"{column}{last_row + max(1, int(rows_below_last))}"


def _note_assignments(wb: Any, sheet_names: list[str], note: dict[str, Any] | None,
                      assignments_by_sheet: dict[str, dict[str, Any]], warnings: list[str]) -> None:
    """budget_note: the same text at the bottom of every printed sheet (never over a filled cell)."""
    note = note or {}
    text = str(note.get("text") or "").strip()
    if not text:
        return
    for sheet_name in sheet_names:
        ws = wb[sheet_name]
        column = str((note.get("columns") or {}).get(sheet_name) or note.get("column") or "C")
        coordinate = _note_cell(ws, column, note.get("rows_below_last", 2))
        if coordinate in assignments_by_sheet.setdefault(sheet_name, {}):
            warnings.append(f"Budget note not written on {sheet_name}: {coordinate} already filled")
            continue
        assignments_by_sheet[sheet_name][coordinate] = text


@dataclass
class GeneratedExcel:
    path: Path
    missing_materials: list[str] = field(default_factory=list)   # labels with no template row
    warnings: list[str] = field(default_factory=list)


def generar_excel(data: dict[str, Any], rules: dict[str, Any], template_path: Path,
                  output_dir: Path) -> GeneratedExcel:
    """Fill quantities and route fields without rewriting the Excel package.

    openpyxl locates labels, while the original ZIP package is copied and only
    target worksheet cells are patched. Pricing tables, formulas and drawings
    therefore remain byte-for-byte untouched. Template formulas are never replaced
    unless a rule names the cell (date rewrite, hardware_by_cable_type).
    """
    warnings: list[str] = []
    wb = load_workbook(template_path, data_only=False)
    for sheet_name in PROTECTED_SHEETS:
        if _find_required_sheet_name(wb, sheet_name) is None:
            raise ValueError(f"Required pricing sheet is missing: {sheet_name}")

    budget_sheet = wb["Presupuesto"]
    quantities = data.get("quantities", {})
    assignments_by_sheet = {"Presupuesto": _quantity_assignments(
        budget_sheet, quantities, set(rules.get("manual_zero_row_labels", [])))}
    # Anchor cells only; the title formulas read the client name from that one cell.
    client_name_cell, comment_cell = _client_name_cell(budget_sheet), _comment_cell(budget_sheet)
    assignments_by_sheet["Presupuesto"][client_name_cell] = data["client_name"]
    assignments_by_sheet["Presupuesto"].update(_locale_independent_date_formulas(budget_sheet))
    if data.get("raw_comment"):
        assignments_by_sheet["Presupuesto"][comment_cell] = _comment_text(
            budget_sheet[comment_cell].value, data["raw_comment"])

    # "Elaborado por:" on the budget sheet, as on the route sheet.
    prepared_by_cell = _prepared_by_cell(budget_sheet)
    if prepared_by_cell:
        assignments_by_sheet["Presupuesto"][prepared_by_cell] = PREPARED_BY
    else:
        warnings.append('"Elaborado por:" not filled on Presupuesto (label or empty cell not found)')

    _validate_labor_assignments(assignments_by_sheet["Presupuesto"],
                                {client_name_cell, comment_cell} | ({prepared_by_cell} - {None}))
    material_cells, missing_materials = _material_assignments(budget_sheet, data.get("materials", {}))
    assignments_by_sheet["Presupuesto"].update(material_cells)
    if missing_materials:
        log.warning("Materials without a template row: %s", missing_materials)
    hardware_cells = _hardware_assignments(budget_sheet, data.get("hardware", {}))
    assignments_by_sheet["Presupuesto"].update(hardware_cells)
    rule_formulas = {coord for coord, value in assignments_by_sheet["Presupuesto"].items()
                     if isinstance(value, Formula)}
    _drop_formula_overwrites(budget_sheet, assignments_by_sheet["Presupuesto"],
                             set(hardware_cells) | rule_formulas, warnings)

    route_config = rules["route_sheet"]
    route_sheet_name = route_config["sheet"]
    if route_sheet_name not in wb.sheetnames:
        raise ValueError(f"Required route sheet is missing: {route_sheet_name}")
    route_sheet = wb[route_sheet_name]
    route_assignments = {}
    route_fields = {"prepared_by": PREPARED_BY, **data.get("route_fields", {})}
    for field_name, value in route_fields.items():
        if field_name not in route_config["fields"]:
            raise ValueError(f"Unknown route-sheet field: {field_name}")
        coordinate, assigned_value = _route_assignment(
            route_sheet, route_config["fields"][field_name], value)
        if coordinate in route_assignments:
            raise ValueError(f"Route-sheet fields resolve to the same cell {coordinate}: {field_name}")
        route_assignments[coordinate] = assigned_value
    # Route map: the picture goes into the "ESQUEMA DE RUTA PROYECTADA" box after the cells
    # are written; without a map the box says so. "route_map_png" absent = not requested.
    map_anchor = None
    if "route_map_png" in data:
        try:
            map_box = _box_below_label(route_sheet, ROUTE_MAP_LABEL)
        except ValueError as exc:
            warnings.append(f"Route map not placed: {exc}")
        else:
            png = data["route_map_png"]
            if png is None:
                route_assignments[route_sheet.cell(map_box.min_row, map_box.min_col).coordinate] = (
                    MAP_UNAVAILABLE_TEXT)
            else:
                map_anchor = _box_anchor(route_sheet, map_box)
    _drop_formula_overwrites(route_sheet, route_assignments, set(), warnings)
    assignments_by_sheet[route_sheet_name] = route_assignments
    _note_assignments(wb, [route_sheet_name, "Presupuesto"], rules.get("budget_note"),
                      assignments_by_sheet, warnings)

    with zipfile.ZipFile(template_path, "r") as archive:
        paths = _sheet_paths(archive)
    package_assignments = {paths[sheet]: values for sheet, values in assignments_by_sheet.items()}

    safe_id = str(data.get("budget_id", data["ticket_id"]))
    if not re.fullmatch(r"[A-Za-z0-9]+", safe_id):
        raise ValueError("budget_id must be alphanumeric")
    # The budget_id suffix keeps names unique and lets the download route find the file.
    name = f"{_safe_file_stem(data.get('client_name'))}_{safe_id}.xlsx"
    out = output_dir / name
    _write_cells_preserving_package(template_path, out, package_assignments)
    if map_anchor is not None:
        _insert_picture(out, paths[route_sheet_name], map_anchor, Path(data["route_map_png"]))
    log.info("Excel generated from preserved template package: %s", out)
    return GeneratedExcel(path=out, missing_materials=missing_materials, warnings=warnings)
