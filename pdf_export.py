"""PDF copy of a generated budget, made by LibreOffice headless.

Only the sheets of the budget itself are exported: "Ruta proyectada" and "Presupuesto" (HOJAS_DEL_PDF), however many pages each one prints.
The price catalogs (COSTOS, MATERIALES, "Variación de costos"...) are never in the PDF, whether the template hides them (the old one) or leaves
them visible (the current one): the conversion is made on a temporary copy of the workbook where every other sheet is hidden, and LibreOffice
does not print hidden sheets. A template without those two sheets falls back to the old rule: the visible sheets at the front, one page each.
The PDF is saved next to the Excel and reused while it is newer than it.
"""
import logging
import re
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from excel_generator import NS
from recalc import _ALWAYS_RECALC_PROFILE

log = logging.getLogger(__name__)
_lock = threading.Lock()   # one LibreOffice conversion at a time
HOJAS_DEL_PDF = ("Ruta proyectada", "Presupuesto")
_RE_HOJA = re.compile(r"<sheet\b[^>]*?/>")


class PdfExportError(Exception):
    """LibreOffice could not convert the workbook to PDF."""


def _leading_visible_sheets(xlsx_path: Path) -> int:
    """How many sheets are visible before the first hidden one (each prints as one page)."""
    with zipfile.ZipFile(xlsx_path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    sheets = workbook.find("main:sheets", NS)
    count = 0
    for sheet in sheets if sheets is not None else []:
        if sheet.attrib.get("state", "visible") != "visible":
            break
        count += 1
    return max(count, 1)


def _copia_con_solo_las_hojas(xlsx_path: Path, destino: Path, hojas: tuple[str, ...] = HOJAS_DEL_PDF) -> int | None:
    """Writes a copy of the workbook where every sheet but `hojas` is hidden; returns how many sheets stay visible, or None when the
    workbook has none of them (the caller then converts the original with the old page-range rule). The original is never touched."""
    quedan = {h.casefold() for h in hojas}
    with zipfile.ZipFile(xlsx_path) as origen:
        texto = origen.read("xl/workbook.xml").decode("utf-8")
        visibles = 0

        def ocultar(m: re.Match) -> str:
            nonlocal visibles
            tag = m.group(0)
            nombre = re.search(r'\bname="([^"]*)"', tag)
            es_de_ellas = nombre is not None and nombre.group(1).replace("&amp;", "&").casefold() in quedan
            if es_de_ellas:
                visibles += 1
                return re.sub(r'\sstate="[^"]*"', "", tag)                # visible even if the template hid it
            tag = re.sub(r'\sstate="[^"]*"', "", tag)
            return tag[:-2].rstrip() + ' state="hidden"/>'
        nuevo = _RE_HOJA.sub(ocultar, texto)
        if not visibles:
            return None
        # the active tab must be a visible sheet
        nuevo = re.sub(r'\sactiveTab="\d+"', "", nuevo)
        nuevo = re.sub(r'\sfirstSheet="\d+"', "", nuevo)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as copia:
            for item in origen.infolist():
                copia.writestr(item, nuevo.encode("utf-8") if item.filename == "xl/workbook.xml" else origen.read(item.filename))
    return visibles


def xlsx_a_pdf(xlsx_path: Path, soffice: str, timeout_s: float = 120, carpeta_pdf: Path | None = None) -> Path:
    """PDF next to the Excel (same name, .pdf) or, with `carpeta_pdf`, in that folder (created); reused while newer than the Excel."""
    pdf_path = (Path(carpeta_pdf) / xlsx_path.with_suffix(".pdf").name) if carpeta_pdf else xlsx_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    def is_current() -> bool:
        return pdf_path.is_file() and pdf_path.stat().st_mtime >= xlsx_path.stat().st_mtime

    if is_current():
        return pdf_path
    with _lock:
        if is_current():            # converted by another request while this one waited
            return pdf_path
        with TemporaryDirectory() as tmp:
            fuente = Path(tmp, "src", xlsx_path.name)
            fuente.parent.mkdir()
            pages = _copia_con_solo_las_hojas(xlsx_path, fuente)
            rango = ""
            if pages is None:                                  # not the usual template: the old rule, the visible sheets at the front
                shutil.copyfile(xlsx_path, fuente)
                pages = _leading_visible_sheets(xlsx_path)
                rango = f'"PageRange":{{"type":"string","value":"1-{pages}"}},'
            out_dir = Path(tmp, "out")
            # Own profile (a LibreOffice the user has open does not interfere), set to
            # recalculate on load so the PDF never shows stale cached values.
            profile_dir = Path(tmp, "profile")
            (profile_dir / "user").mkdir(parents=True)
            (profile_dir / "user" / "registrymodifications.xcu").write_text(
                _ALWAYS_RECALC_PROFILE, encoding="utf-8")
            # Template cell notes would show as note icons on the page: not exported.
            export = f'pdf:calc_pdf_Export:{{{rango}"ExportNotes":{{"type":"boolean","value":"false"}}}}'
            command = [soffice, f"-env:UserInstallation={profile_dir.as_uri()}", "--headless", "--norestore",
                       "--convert-to", export, "--outdir", str(out_dir), str(fuente)]
            try:
                subprocess.run(command, capture_output=True, timeout=timeout_s, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise PdfExportError(f"LibreOffice failed ({type(exc).__name__})") from exc
            produced = out_dir / f"{xlsx_path.stem}.pdf"
            if not produced.is_file() or produced.stat().st_size == 0:
                raise PdfExportError("LibreOffice produced no PDF")
            partial = pdf_path.with_suffix(".pdf.tmp")
            shutil.move(str(produced), partial)
            partial.replace(pdf_path)
    log.info("PDF generated: %s (%d sheets)", pdf_path.name, pages)
    return pdf_path
