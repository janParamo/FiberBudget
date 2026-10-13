"""Cache formula results in a generated workbook so readers that do not recalculate
(n8n, pandas, openpyxl data_only, previews) see real totals instead of zeros.

LibreOffice only computes: it converts a copy of the file headless, the computed
values are read from that copy, and they are written as cached <v> values into the
original package. The original package (styles, drawings, validations) is kept;
Excel still recalculates everything on open (fullCalcOnLoad).
"""
import logging
import shutil
import subprocess
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any
from xml.etree import ElementTree

from openpyxl import load_workbook

from excel_generator import MAIN_NS, NS, _sheet_paths

log = logging.getLogger(__name__)

_COMMON_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
_EXCEL_ERRORS = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"}
# By default LibreOffice trusts the cached values stored in an .xlsx and does not recompute
# them, so the template's stale zeros would survive. RecalcMode 0 = always recalculate on load.
_ALWAYS_RECALC_PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""
_EXCEL_EPOCH = datetime(1899, 12, 30)


class RecalcError(Exception):
    """LibreOffice could not recalculate the workbook."""


def find_soffice(configured: str = "", autodetect_fallback: bool = True) -> str | None:
    """Configured path, else soffice on PATH, else the usual install locations.

    A configured path that does not exist is logged and, by default, autodetection is tried.
    """
    if configured:
        if Path(configured).is_file():
            return configured
        log.warning("LIBREOFFICE_PATH does not exist (%s); looking for LibreOffice elsewhere", configured)
        if not autodetect_fallback:
            return None
    found = shutil.which("soffice")
    if found:
        return found
    return next((path for path in _COMMON_SOFFICE_PATHS if Path(path).is_file()), None)


def _cached_value(cell: ElementTree.Element, value: Any) -> None:
    """Replace a formula cell's cached <v> and its type attribute with `value`."""
    for child in list(cell):
        if child.tag == f"{{{MAIN_NS}}}v":
            cell.remove(child)
    if isinstance(value, bool):
        cell.attrib["t"], text = "b", "1" if value else "0"
    elif isinstance(value, (int, float)):
        cell.attrib.pop("t", None)
        text = repr(value)
    elif isinstance(value, (datetime, date, time)):
        if isinstance(value, time):
            value = datetime.combine(_EXCEL_EPOCH.date(), value)
        elif not isinstance(value, datetime):
            value = datetime.combine(value, time())
        cell.attrib.pop("t", None)
        text = repr((value - _EXCEL_EPOCH).total_seconds() / 86400)
    elif isinstance(value, str) and value in _EXCEL_ERRORS:
        cell.attrib["t"], text = "e", value
    else:
        cell.attrib["t"], text = "str", "" if value is None else str(value)
    ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = text


def cache_formula_values(xlsx_path: Path, sheet_names: list[str], soffice: str,
                         timeout_s: float = 120) -> int:
    """Recalculate with LibreOffice and store results for every formula in `sheet_names`.

    Returns the number of formula cells updated. Raises RecalcError on failure.
    """
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp, "out")
        # Own profile so a LibreOffice the user has open does not block or share state,
        # configured to recalculate every formula on load.
        profile_dir = Path(tmp, "profile")
        (profile_dir / "user").mkdir(parents=True)
        (profile_dir / "user" / "registrymodifications.xcu").write_text(_ALWAYS_RECALC_PROFILE, encoding="utf-8")
        profile = profile_dir.as_uri()
        command = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                   "--calc", "--convert-to", "xlsx", "--outdir", str(out_dir), str(xlsx_path)]
        try:
            subprocess.run(command, capture_output=True, timeout=timeout_s, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RecalcError(f"LibreOffice failed ({type(exc).__name__})") from exc
        converted = out_dir / xlsx_path.name
        if not converted.is_file():
            raise RecalcError("LibreOffice produced no output file")
        computed = load_workbook(converted, data_only=True)
        values = {name: computed[name] for name in sheet_names}

        updated = 0
        with NamedTemporaryFile(suffix=".xlsx", delete=False, dir=xlsx_path.parent) as tmp_file:
            temp_path = Path(tmp_file.name)
        try:
            with zipfile.ZipFile(xlsx_path) as source, zipfile.ZipFile(temp_path, "w") as target:
                paths = _sheet_paths(source)
                targets = {paths[name]: name for name in sheet_names}
                for item in source.infolist():
                    content = source.read(item.filename)
                    if item.filename in targets:
                        sheet = values[targets[item.filename]]
                        root = ElementTree.fromstring(content)
                        for cell in root.iterfind(".//main:c", NS):
                            if cell.find("main:f", NS) is not None:
                                _cached_value(cell, sheet[cell.attrib["r"]].value)
                                updated += 1
                        content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
                    target.writestr(item, content)
            # Replace only after both archives are closed (Windows cannot replace an open file).
            temp_path.replace(xlsx_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    log.info("Cached %d formula values in %s", updated, xlsx_path.name)
    return updated
