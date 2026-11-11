"""Comprueba que el LibreOffice instalado calcula las formulas de la plantilla de presupuestos.

La plantilla usa XLOOKUP en 123 celdas (los codigos y los precios de los materiales). LibreOffice solo la entiende desde la version 24.8: con una anterior (la 7.4 de
Debian «bookworm») el Excel y sobre todo el PDF salen con `#NAME?` en los codigos y sin precios, y el total sale mal.

Crea un libro pequeno con XLOOKUP y VLOOKUP, lo convierte con LibreOffice (sin ventana) y verifica que los resultados sean los numeros esperados y no `#NAME?`. Termina con
codigo 1 si no. Lo corre el Dockerfile al construir la imagen (si falla, la imagen no se crea) y se puede correr a mano:

    python herramientas/comprobar_libreoffice.py                      usa el soffice que haya en el PATH
    python herramientas/comprobar_libreoffice.py --soffice "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
"""
import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook


def comprobar(soffice: str, timeout_s: int = 120) -> tuple[bool, str]:
    """(ok, text): LibreOffice calculates XLOOKUP and VLOOKUP of a small book."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        libro = base / "prueba.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"], ws["A2"] = "b", "zzz"
        ws["C1"], ws["C2"] = "a", "b"
        ws["D1"], ws["D2"] = 10, 20
        ws["B1"] = '=_xlfn.XLOOKUP(A1,C1:C2,D1:D2,"Verificar")'            # 20
        ws["B2"] = '=_xlfn.XLOOKUP(A2,C1:C2,D1:D2,"Verificar")'            # «Verificar» (not found: the fourth argument)
        ws["B3"] = '=IFERROR(VLOOKUP(A1,C1:D2,2,0),"")'                    # 20
        wb.save(libro)
        perfil = (base / "perfil").as_uri()
        try:
            subprocess.run([soffice, f"-env:UserInstallation={perfil}", "--headless", "--norestore", "--convert-to", "csv", "--outdir", str(base / "salida"), str(libro)],
                           capture_output=True, timeout=timeout_s, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"LibreOffice no pudo convertir el libro de prueba ({type(exc).__name__})"
        csv_ = base / "salida" / "prueba.csv"
        if not csv_.is_file():
            return False, "LibreOffice no genero el resultado"
        filas = list(csv.reader(csv_.read_text(encoding="utf-8").splitlines()))
    valores = [fila[1] if len(fila) > 1 else "" for fila in filas[:3]]
    if any("#NAME" in v or "Err:" in v for v in valores):
        return False, f"LibreOffice no entiende alguna funcion de la plantilla (XLOOKUP necesita la version 24.8 o posterior): {valores}"
    if valores != ["20", "Verificar", "20"]:
        return False, f"LibreOffice calculo algo distinto de lo esperado: {valores} (esperado ['20', 'Verificar', '20'])"
    return True, f"LibreOffice calcula XLOOKUP y VLOOKUP: {valores}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Comprueba que LibreOffice calcula las formulas de la plantilla (XLOOKUP)")
    ap.add_argument("--soffice", default=None, help="ruta de soffice (por defecto el del PATH)")
    args = ap.parse_args()
    soffice = args.soffice or shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("No se encontro soffice (LibreOffice).")
        return 1
    try:
        version = subprocess.run([soffice, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = "(version desconocida)"
    ok, texto = comprobar(soffice)
    print(f"{version}\n{'OK' if ok else 'FALLO'}: {texto}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
