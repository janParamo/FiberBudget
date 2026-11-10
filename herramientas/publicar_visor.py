"""Publica el visor en el servidor para que las personas lo reciban SOLO al abrirlo (actualización automática, visor_rutas/actualizador.py).

Uso (lo llama herramientas\\publicar_visor.bat):
    .venv\\Scripts\\python.exe herramientas\\publicar_visor.py                  arma el paquete (como build_visor.bat) y lo sube
    .venv\\Scripts\\python.exe herramientas\\publicar_visor.py --sin-empaquetar  sube el VisorRutas.zip que ya existe

Qué hace:
  1. Arma dist\\VisorRutas y VisorRutas.zip (herramientas\\empaquetar_visor.py), que lleva version.json junto al .exe.
  2. Calcula el tamaño y la suma SHA-256 del zip y escribe actualizaciones\\version.json (esta carpeta no se sube a Git).
  3. Los copia por scp a la carpeta ``actualizaciones`` de la VM (VisorRutas.zip primero, version.json al final: el servidor solo ofrece la versión cuando el
     paquete ya está completo). Pide la contraseña de la VM una vez.
Después cada persona recibe la versión nueva la próxima vez que abra el visor. No hace falta tocar nada en la VM (el servicio lee esa carpeta en cada consulta).

El destino se cambia con --destino / --puerto / --carpeta, o con las variables VISOR_PUBLICAR_DESTINO, VISOR_PUBLICAR_PUERTO y VISOR_PUBLICAR_CARPETA.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ZIP = RAIZ / "VisorRutas.zip"
SALIDA = RAIZ / "actualizaciones"

DESTINO = "jparamo@10.0.40.154"                  # usuario@VM
PUERTO = "5730"                                  # puerto SSH de la VM
CARPETA = "~/fiber_budget/actualizaciones"       # carpeta de la VM que el servicio ofrece a los visores


def version_del_zip(zip_: Path) -> str:
    """The version written next to the .exe inside the package (VisorRutas/version.json)."""
    with zipfile.ZipFile(zip_) as z:
        try:
            datos = json.loads(z.read("VisorRutas/version.json").decode("utf-8"))
        except KeyError:
            raise SystemExit("El paquete no trae version.json: vuelva a armarlo con herramientas\\build_visor.bat")
    return str(datos["version"])


def preparar(zip_: Path, salida: Path) -> dict:
    """actualizaciones\\version.json (version, size, SHA-256) and the zip next to it, ready to upload."""
    salida.mkdir(exist_ok=True)
    sha, tamano = hashlib.sha256(), 0
    with open(zip_, "rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(trozo)
            tamano += len(trozo)
    datos = {"version": version_del_zip(zip_), "sha256": sha.hexdigest(), "tamano": tamano, "creado": time.strftime("%Y-%m-%dT%H:%M:%S")}
    shutil.copyfile(zip_, salida / "VisorRutas.zip")
    (salida / "version.json").write_text(json.dumps(datos, indent=2), encoding="utf-8")
    return datos


def subir(salida: Path, destino: str, puerto: str, carpeta: str) -> None:
    scp = shutil.which("scp")
    if not scp:
        raise SystemExit("No se encontró scp (viene con OpenSSH de Windows). Copie a mano actualizaciones\\VisorRutas.zip y luego actualizaciones\\version.json a la VM.")
    comando = [scp, "-P", str(puerto), str(salida / "VisorRutas.zip"), str(salida / "version.json"), f"{destino}:{carpeta}/"]
    print("Subiendo a", f"{destino}:{carpeta}/", "(pedirá la contraseña de la VM)")
    subprocess.run(comando, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Publica el visor en el servidor (actualización automática)")
    ap.add_argument("--sin-empaquetar", action="store_true", help="no vuelve a armar el paquete: sube el VisorRutas.zip que ya existe")
    ap.add_argument("--destino", default=os.getenv("VISOR_PUBLICAR_DESTINO", DESTINO), help="usuario@host de la VM")
    ap.add_argument("--puerto", default=os.getenv("VISOR_PUBLICAR_PUERTO", PUERTO), help="puerto SSH")
    ap.add_argument("--carpeta", default=os.getenv("VISOR_PUBLICAR_CARPETA", CARPETA), help="carpeta de la VM")
    ap.add_argument("--solo-preparar", action="store_true", help="solo escribe actualizaciones\\version.json (no sube nada)")
    args = ap.parse_args()
    if not args.sin_empaquetar:
        subprocess.run([sys.executable, str(RAIZ / "herramientas" / "empaquetar_visor.py")], cwd=RAIZ, check=True)
    if not ZIP.is_file():
        raise SystemExit(f"No existe {ZIP}: arme el paquete primero (herramientas\\build_visor.bat)")
    datos = preparar(ZIP, SALIDA)
    print(f"Versión {datos['version']} · {datos['tamano'] / 1e6:.1f} MB · SHA-256 {datos['sha256'][:12]}…")
    if args.solo_preparar:
        print("Preparado en", SALIDA)
        return
    subir(SALIDA, args.destino, args.puerto, args.carpeta)
    print(f"\nPublicado: la versión {datos['version']} llegará a cada persona la próxima vez que abra el visor.")


if __name__ == "__main__":
    main()
