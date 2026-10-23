#!/usr/bin/env python3
"""
Mide la precisión de la extracción geométrica de fusiones (fusiones.py) usando como verdad el Excel de
anillos (tabla anillo_tramos): en cada mufa del anillo que tiene diagrama propio, compara los pares de
hilos "entrante ↔ saliente" del Excel con los pares hilo↔hilo que lee la geometría.

    .venv\\Scripts\\python.exe red_fibra\\medir_fusiones_anillo.py [--db red_fibra\\red_fibra.db]

Solo lee (la base se abre de solo lectura; no escribe fusiones_piloto). Resultado de la medición del
2026-10-13 en docs/bitacora/2026-10-13/LEEME.md: la precisión no llega ni al 5 %, así que
business_rules.yaml → migracion_visio.fusiones_geometria.usar sigue en false.
Límite: el Excel solo lista los hilos del anillo; la precisión real es mayor que la medida si el
diagrama dibuja otras fusiones reales, pero la cobertura de los pares del Excel con confianza ≥ 0.7
(3,9 %) no depende de eso.
"""
import argparse
import os
import re
import sqlite3
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import fusiones  # noqa: E402


def _numeros(texto):
    return [int(x) for x in re.findall(r"\d+", texto or "")]


def verdad_del_anillo(con):
    """nodo_id -> {frozenset({hilo_a, hilo_b})} que el Excel de anillos da como empalmados en esa mufa."""
    verdad = {}
    for nodo_id, entrante, saliente in con.execute(
            "SELECT nodo_id, hilo_entrante, hilo_saliente FROM anillo_tramos WHERE nodo_id IS NOT NULL"):
        a, b = _numeros(entrante), _numeros(saliente)
        if a and len(a) == len(b):                       # the lists may be written in either order
            pares = verdad.setdefault(nodo_id, set())
            pares.update(frozenset(p) for p in zip(a, b))
            pares.update(frozenset(p) for p in zip(a, reversed(b)))
    return verdad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.path.join(AQUI, "red_fibra.db"))
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(a.db).replace("\\", "/"), uri=True)
    medidas = []
    for nodo_id, pares in verdad_del_anillo(con).items():
        d = con.execute("SELECT f.md5 FROM nodo_apariciones a JOIN archivos f ON f.id = a.archivo_id WHERE a.nodo_id = ? AND a.rol = 'principal' "
                        "AND f.tipo_diagrama = 'mufa' AND f.estado = 'ok' LIMIT 1", (nodo_id,)).fetchone()
        odg = os.path.join(os.path.dirname(AQUI), "datos", "cache", "odg", d[0] + ".odg") if d else None
        if odg and os.path.exists(odg):
            detectadas = [f for f in fusiones.extraer_fusiones(odg) if f["hilo_entrada"] is not None and f["hilo_salida"] is not None]
            medidas.append((pares, detectadas))
    reales = sum(len({tuple(sorted(p)) for p in pares}) for pares, _ in medidas)
    print("mufas del anillo con diagrama propio: %d · pares reales del Excel: %d" % (len(medidas), reales))
    for u in (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9):
        det = ok = cubiertos = 0
        for pares, detectadas in medidas:
            sel = [f for f in detectadas if f["confianza"] >= u]
            claves = [frozenset((f["hilo_entrada"], f["hilo_salida"])) for f in sel]
            det += len(sel)
            ok += sum(c in pares for c in claves)
            cubiertos += len(set(claves) & pares)
        print("confianza >= %.2f: detectadas %5d · coinciden %4d · precisión %5.1f %% · cobertura %5.1f %%"
              % (u, det, ok, 100 * ok / det if det else 0, 100 * cubiertos / (reales or 1)))


if __name__ == "__main__":
    main()
