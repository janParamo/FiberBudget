"""PDF copy of a generated budget, made by LibreOffice headless.

Only the visible sheets at the front of the workbook are exported ("Ruta proyectada" and
"Presupuesto", one page each by the template's own print setup). LibreOffice would also
print the hidden price catalogs (COSTOS, MATERIALES, ...), so the export is limited to
those pages. The PDF is saved next to the Excel and reused while it is newer than it.
"""
import logging
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


def xlsx_a_pdf(xlsx_path: Path, soffice: str, timeout_s: float = 120) -> Path:
    """PDF next to the Excel (same name, .pdf); reused while newer than the Excel."""
    pdf_path = xlsx_path.with_suffix(".pdf")

    def is_current() -> bool:
        return pdf_path.is_file() and pdf_path.stat().st_mtime >= xlsx_path.stat().st_mtime

    if is_current():
        return pdf_path
    with _lock:
        if is_current():            # converted by another request while this one waited
            return pdf_path
        pages = _leading_visible_sheets(xlsx_path)
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp, "out")
            # Own profile (a LibreOffice the user has open does not interfere), set to
            # recalculate on load so the PDF never shows stale cached values.
            profile_dir = Path(tmp, "profile")
            (profile_dir / "user").mkdir(parents=True)
            (profile_dir / "user" / "registrymodifications.xcu").write_text(
                _ALWAYS_RECALC_PROFILE, encoding="utf-8")
            # Template cell notes would show as note icons on the page: not exported.
            export = (f'pdf:calc_pdf_Export:{{"PageRange":{{"type":"string","value":"1-{pages}"}},'
                      f'"ExportNotes":{{"type":"boolean","value":"false"}}}}')
            command = [soffice, f"-env:UserInstallation={profile_dir.as_uri()}", "--headless", "--norestore",
                       "--convert-to", export, "--outdir", str(out_dir), str(xlsx_path)]
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
    log.info("PDF generated: %s (%d pages)", pdf_path.name, pages)
    return pdf_path
