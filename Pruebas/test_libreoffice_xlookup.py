"""La plantilla usa XLOOKUP (codigos y precios): LibreOffice solo la calcula desde la 24.8. Con la 7.4 de Debian «bookworm» el PDF salia con #NAME? y sin precios.

herramientas/comprobar_libreoffice.py lo comprueba (el Dockerfile lo corre al construir la imagen: si falla, la imagen no se crea).
"""
import re
import sys
from pathlib import Path

import pytest

import recalc

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas"))
import comprobar_libreoffice  # noqa: E402

SOFFICE = recalc.find_soffice(None)


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice not installed")
def test_the_libreoffice_of_this_computer_calculates_the_xlookup_of_the_template():
    ok, texto = comprobar_libreoffice.comprobar(SOFFICE)
    assert ok, texto


def test_an_old_libreoffice_that_answers_name_errors_is_detected(monkeypatch):
    """LibreOffice 7.4 converts the book but answers #NAME? for XLOOKUP: the check must fail (and say why)."""
    def falso(comando, **kw):
        salida = Path(comando[comando.index("--outdir") + 1])
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "prueba.csv").write_text("b,#NAME?\nzzz,#NAME?\n,20\n", encoding="utf-8")

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(comprobar_libreoffice.subprocess, "run", falso)
    ok, texto = comprobar_libreoffice.comprobar("soffice")
    assert ok is False and "XLOOKUP" in texto and "24.8" in texto


def test_a_libreoffice_that_calculates_something_else_is_also_refused(monkeypatch):
    def falso(comando, **kw):
        salida = Path(comando[comando.index("--outdir") + 1])
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "prueba.csv").write_text("b,10\nzzz,Verificar\n,20\n", encoding="utf-8")

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(comprobar_libreoffice.subprocess, "run", falso)
    ok, texto = comprobar_libreoffice.comprobar("soffice")
    assert ok is False and "distinto" in texto


def test_the_image_uses_a_debian_with_a_libreoffice_that_knows_xlookup_and_checks_it_when_building():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13-slim-trixie" in dockerfile and "bookworm" not in re.sub(r"#.*", "", dockerfile)          # Debian 13: LibreOffice 25.2 (bookworm brings the 7.4)
    assert "trixie-pgdg" in dockerfile and "python herramientas/comprobar_libreoffice.py" in dockerfile
