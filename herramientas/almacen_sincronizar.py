"""Almacén de archivos en PostgreSQL: subir lo que hay en las carpetas del proyecto, ver qué guarda y comprobar que coincide.

    .\\.venv\\Scripts\\python.exe herramientas\\almacen_sincronizar.py resumen
    .\\.venv\\Scripts\\python.exe herramientas\\almacen_sincronizar.py subir            # los cinco espacios
    .\\.venv\\Scripts\\python.exe herramientas\\almacen_sincronizar.py subir odg kmz    # solo esos
    .\\.venv\\Scripts\\python.exe herramientas\\almacen_sincronizar.py verificar        # tamaño y md5 de cada archivo local contra la base

Espacios y carpetas (las carpetas locales son una copia desechable: lo que está en la base se vuelve a escribir cuando el visor lo pide):
    visor      output/visor              (sin mapas/)
    odg        datos/cache/odg           (*.odg)
    diagramas  datos/cache/diagramas
    kmz        KMZ_PATH (datos/kmz)      (*.kmz, sin anteriores/)
    datos_kmz  datos/cache/kmz           (capas, íconos, fotos, sincronizaciones)
"""
import argparse
import hashlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from config import get_settings  # noqa: E402
from visor_rutas import almacen_archivos as alm  # noqa: E402
from visor_rutas import kmz_capas  # noqa: E402


def carpetas() -> dict[str, tuple[Path, str, tuple[str, ...]]]:
    """espacio -> (carpeta local, patrón, subcarpetas que no se suben)"""
    kmz = kmz_capas.ruta_kmz(restaurar=False).parent if _hay_kmz() else Path(RAIZ / "datos" / "kmz")
    return {
        "visor": (get_settings().output_dir / "visor", "**/*", ("mapas",)),
        "odg": (RAIZ / "datos" / "cache" / "odg", "*.odg", ()),
        "diagramas": (RAIZ / "datos" / "cache" / "diagramas", "*", ()),
        "kmz": (kmz, "*.kmz", ("anteriores",)),
        "datos_kmz": (kmz_capas.CARPETA_DATOS, "**/*", ()),
    }


def _hay_kmz() -> bool:
    try:
        kmz_capas.ruta_kmz(restaurar=False)
        return True
    except kmz_capas.KmzNoEncontrado:
        return False


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


def resumen() -> None:
    datos = alm.resumen()
    if not datos:
        print("El almacén no responde o está vacío (¿migración 019 aplicada? ¿VISIO_DB_NAME en el .env?)")
        return
    for espacio in alm.ESPACIOS:
        d = datos.get(espacio, {"archivos": 0, "bytes": 0})
        print(f"  {espacio:10} {d['archivos']:6} archivos  {_mb(d['bytes'])}")


def subir(espacios: list[str]) -> int:
    fallos = 0
    for espacio in espacios:
        carpeta, patron, excluir = carpetas()[espacio]
        r = alm.subir_carpeta(espacio, carpeta, patron, excluir)
        print(f"  {espacio:10} subidos {r['subidos']}, ya estaban {r['iguales']}, fallidos {r['fallidos']}   ({carpeta})")
        fallos += r["fallidos"]
    return fallos


def verificar(espacios: list[str]) -> int:
    """Every local file must be in the database with the same size and md5. Returns how many differ."""
    distintos = 0
    for espacio in espacios:
        carpeta, patron, excluir = carpetas()[espacio]
        guardados = {f["clave"]: f for f in alm.listar(espacio)}
        ok = faltan = 0
        if carpeta.is_dir():
            for archivo in sorted(p for p in carpeta.glob(patron) if p.is_file()):
                clave = archivo.relative_to(carpeta).as_posix()
                if any(clave == e or clave.startswith(e + "/") for e in excluir) or archivo.name.startswith("~$") or archivo.suffix == ".tmp":
                    continue
                f = guardados.get(clave)
                if f is not None and f["tamano"] == archivo.stat().st_size and f["md5"] == hashlib.md5(archivo.read_bytes()).hexdigest():
                    ok += 1
                else:
                    faltan += 1
                    print(f"    DIFERENTE o falta: {espacio}/{clave}")
        print(f"  {espacio:10} coinciden {ok}, distintos o ausentes {faltan}")
        distintos += faltan
    return distintos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("accion", choices=("resumen", "subir", "verificar"))
    ap.add_argument("espacios", nargs="*", choices=alm.ESPACIOS)
    args = ap.parse_args()
    espacios = args.espacios or list(alm.ESPACIOS)
    if not alm.habilitado():
        print("El almacén no está disponible: revise VISIO_DB_* en el .env")
        return 2
    if args.accion == "resumen":
        resumen()
        return 0
    if args.accion == "subir":
        fallos = subir(espacios)
        resumen()
        return 1 if fallos else 0
    return 1 if verificar(espacios) else 0


if __name__ == "__main__":
    raise SystemExit(main())

