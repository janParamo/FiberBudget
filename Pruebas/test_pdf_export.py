"""Real PDF conversion with LibreOffice and the company template (skipped if either is missing)."""
import os
import time
from pathlib import Path

import pytest
import yaml
from pypdf import PdfReader

import pdf_export
import recalc
from excel_generator import generar_excel

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "PlantilaEjemploPresupuesto.xlsx"
SOFFICE = recalc.find_soffice()
pytestmark = pytest.mark.skipif(SOFFICE is None or not TEMPLATE.is_file(),
                                reason="LibreOffice or the company template not available")
ROUTE_LABEL = "Instalacion de Fibra Optica Aerea ADSS-FLAT/FTTH (6H - 12H)"


def _budget(tmp_path: Path) -> Path:
    rules = yaml.safe_load((ROOT / "business_rules.yaml").read_text(encoding="utf-8"))
    data = {"budget_id": "pdf1", "ticket_id": "T-PDF", "client_name": "Cliente PDF", "raw_comment": "",
            "quantities": {ROUTE_LABEL: 100}, "materials": {}, "hardware": {}, "route_fields": {}}
    return generar_excel(data, rules, TEMPLATE, tmp_path).path


def test_pdf_has_route_and_budget_pages_with_computed_totals(tmp_path):
    xlsx = _budget(tmp_path)
    pdf = pdf_export.xlsx_a_pdf(xlsx, SOFFICE)

    assert pdf == xlsx.with_suffix(".pdf") and pdf.read_bytes().startswith(b"%PDF")
    reader = PdfReader(pdf)
    assert len(reader.pages) == 2                      # hidden price catalogs are not exported
    route_page, budget_page = (page.extract_text() for page in reader.pages)
    assert "ESQUEMA DE RUTA PROYECTADA" in route_page and "PRESUPUESTO DE OBRA - Cliente PDF" in route_page
    assert "MANO DE OBRA" in budget_page and "MATERIALES" in budget_page
    assert "842.00" in budget_page                     # 100 m x C$ 8.42, computed by the template formulas


def test_pdf_is_reused_until_the_excel_changes(tmp_path):
    xlsx = _budget(tmp_path)
    pdf = pdf_export.xlsx_a_pdf(xlsx, SOFFICE)
    first = pdf.stat().st_mtime_ns
    assert pdf_export.xlsx_a_pdf(xlsx, "no-soffice-needed.exe").stat().st_mtime_ns == first
    later = time.time() + 5
    os.utime(xlsx, (later, later))                     # the Excel is newer: convert again
    with pytest.raises(pdf_export.PdfExportError):
        pdf_export.xlsx_a_pdf(xlsx, str(tmp_path / "missing-soffice.exe"))
