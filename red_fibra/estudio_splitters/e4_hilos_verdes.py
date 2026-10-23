"""Estudio: los «hilos verdes» (continuidad) en los diagramas de Visio convertidos.

Regla 7 de Jan: la ruta de fusión debe usar un splitter secundario con puertos libres Y hilos libres entre mufas. En los diagramas, un hilo verde que
atraviesa una mufa sin empalmarse se toma como continuidad («no se toca»). Este script mide qué se puede leer de eso con el color del trazo (mismo método
que el piloto de fusiones: `fusiones.leer_dibujo` y `color_tia`):

  - cuántas líneas hay de cada color del código TIA-598 y cuántas llevan flechas (los puentes de fusión las llevan; una continuidad no debería);
  - en cuántos diagramas aparece alguna línea verde, y cuántas son «candidatas a continuidad» (verdes, sin flechas, largas);
  - cuántas de esas están en diagramas que también tienen splitters (donde la regla 7 las necesitaría);
  - si lo verde se distingue del resto por el grosor o el largo (si no, el color solo no sirve para separar una continuidad de un hilo número 3 de un buffer).

No escribe nada: imprime el resumen (y un CSV con una fila por diagrama si se indica --csv).

    python red_fibra/estudio_splitters/e4_hilos_verdes.py [--csv salida.csv] [--limite N]
"""
import argparse
import collections
import csv
import statistics
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(AQUI.parent))

import fusiones  # noqa: E402
from visor_rutas import almacen_archivos  # noqa: E402

CACHE = RAIZ / "datos" / "cache" / "odg"
LARGO_MINIMO_CM = 2.0            # a continuity line crosses a mufa: shorter strokes are decoration or the end of a bridge


def largo(puntos):
    return sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(puntos, puntos[1:]))


def medir(odg):
    """Per diagram: {color: {n, flechas, largos, anchos}} and the splitter texts it has."""
    colores = collections.defaultdict(lambda: {"n": 0, "flechas": 0, "largos": [], "anchos": []})
    splitters = 0
    for pagina in fusiones.leer_dibujo(odg).values():
        for linea in pagina["lineas"]:
            nombre = fusiones.color_tia(linea["color"])[1]
            c = colores[nombre]
            c["n"] += 1
            c["flechas"] += 1 if linea["flechas"] else 0
            c["largos"].append(largo(linea["puntos"]))
            if linea["ancho"]:
                c["anchos"].append(linea["ancho"])
        splitters += sum(1 for t in pagina["textos"] if t["texto"].upper().lstrip().startswith("SPL"))
    return colores, splitters


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", type=Path, help="una fila por diagrama")
    ap.add_argument("--limite", type=int, default=None, help="solo los primeros N diagramas (prueba rápida)")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    escritos = almacen_archivos.restaurar_espacio("odg", CACHE)
    archivos = sorted(CACHE.glob("*.odg"))[: args.limite]
    print(f"{len(archivos)} diagramas ({escritos} escritos desde la base)")
    total = collections.defaultdict(lambda: {"n": 0, "flechas": 0, "largos": [], "anchos": [], "diagramas": 0})
    filas, con_verde, con_candidatas, candidatas_con_spl, con_spl = [], 0, 0, 0, 0
    for i, odg in enumerate(archivos, 1):
        try:
            colores, splitters = medir(odg)
        except Exception as exc:                                    # noqa: BLE001 - a damaged drawing is only skipped
            print(f"  {odg.name}: no se pudo leer ({type(exc).__name__})")
            continue
        for nombre, c in colores.items():
            t = total[nombre]
            t["n"] += c["n"]; t["flechas"] += c["flechas"]; t["largos"] += c["largos"]; t["anchos"] += c["anchos"]; t["diagramas"] += 1
        verde = colores.get("verde")
        candidatas = sum(1 for l in (verde["largos"] if verde else []) if l >= LARGO_MINIMO_CM) - (verde["flechas"] if verde else 0)
        candidatas = max(0, candidatas)
        con_spl += 1 if splitters else 0
        if verde:
            con_verde += 1
        if candidatas:
            con_candidatas += 1
            candidatas_con_spl += 1 if splitters else 0
        filas.append({"md5": odg.stem, "lineas": sum(c["n"] for c in colores.values()), "verdes": verde["n"] if verde else 0,
                      "verdes_con_flecha": verde["flechas"] if verde else 0, "candidatas_continuidad": candidatas, "splitters": splitters})
        if i % 50 == 0:
            print(f"  {i}/{len(archivos)}")

    n = len(filas)
    print(f"\nDiagramas leídos: {n}; con algún splitter: {con_spl} ({100 * con_spl / max(n, 1):.0f} %)")
    print("\nLíneas por color (código TIA-598 más cercano):")
    print(f"  {'color':10} {'líneas':>8} {'con flechas':>12} {'diagramas':>10} {'largo mediano cm':>17} {'grosor mediano':>15}")
    for nombre, t in sorted(total.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {nombre:10} {t['n']:8} {100 * t['flechas'] / t['n']:11.0f}% {t['diagramas']:10} {statistics.median(t['largos']):17.2f} "
              f"{(statistics.median(t['anchos']) if t['anchos'] else 0):15.3f}")
    print(f"\nHilos verdes: {con_verde} diagramas ({100 * con_verde / max(n, 1):.0f} %) tienen alguna línea verde.")
    print(f"Candidatas a continuidad (verde, sin flechas, ≥ {LARGO_MINIMO_CM:g} cm): {con_candidatas} diagramas ({100 * con_candidatas / max(n, 1):.0f} %), "
          f"{candidatas_con_spl} de ellos con splitters.")
    v = total.get("verde")
    if v and v["largos"]:
        otros = [l for k, t in total.items() if k != "verde" for l in t["largos"]]
        print(f"El largo mediano de una línea verde es {statistics.median(v['largos']):.2f} cm contra {statistics.median(otros):.2f} cm de las demás: "
              + ("se distinguen por el largo." if abs(statistics.median(v['largos']) - statistics.median(otros)) > 1 else "no se distinguen por el largo."))
        print(f"{100 * v['flechas'] / v['n']:.0f} % de las verdes llevan flechas (de un puente de fusión), contra "
              f"{100 * sum(t['flechas'] for k, t in total.items() if k != 'verde') / max(sum(t['n'] for k, t in total.items() if k != 'verde'), 1):.0f} % de las demás.")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else ["md5"])
            w.writeheader()
            w.writerows(filas)
        print(f"\nCSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
