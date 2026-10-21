"""Estudio 3d: un clasificador simple de «puerto libre» por cuántas líneas (con flecha) llegan al número; sensibilidad y precisión contra las listas."""
import sys, math, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import e3b_puertos_listas as E

splitters, gt = E.analizar()


def cuenta(x, y, lineas, r, con_flecha):
    n = 0
    for l in lineas:
        pts = l["pts"]
        for p, f in ((pts[0], l["flecha_ini"]), (pts[-1], l["flecha_fin"])):
            if math.hypot(p[0] - x, p[1] - y) <= r and (f or not con_flecha):
                n += 1
    return n


filas = []
for g in gt:
    for x, y, n in g["split"]["ports"]:
        if n in g["lista"]:
            filas.append((bool(g["lista"][n]), x, y, g["split"]["lineas"], g["split"]))
print("puertos con verdad conocida:", len(filas), "| libres:", sum(1 for f in filas if not f[0]), "| usados:", sum(1 for f in filas if f[0]))
for con_flecha in (True, False):
    for r in (0.4, 0.6, 0.9):
        feats = [(f[0], cuenta(f[1], f[2], f[3], r, con_flecha)) for f in filas]
        dist_u = collections.Counter(min(c, 5) for u, c in feats if u)
        dist_l = collections.Counter(min(c, 5) for u, c in feats if not u)
        print(f"\n{'flechas' if con_flecha else 'lineas'} r={r}  nº de extremos en el puerto: usados {dict(sorted(dist_u.items()))} | libres {dict(sorted(dist_l.items()))}")
        for k in (0, 1, 2):
            tp = sum(1 for u, c in feats if not u and c <= k); fp = sum(1 for u, c in feats if u and c <= k)
            nl = sum(1 for u, c in feats if not u)
            print(f"   libre si <= {k}: libres detectados {tp} de {nl} ({100 * tp / nl:.0f} %), pero {fp} usados tomados por libres -> precision {100 * tp / max(1, tp + fp):.0f} %")
# how many splitters (not ports) the rule would flag as having a free port, with the same rule, vs the lists
print("\n(los libres de la lista son pocos: 52 puertos en %d splitters; la lista vacía puede ser también «aún no escrito»)" % len({id(f[4]) for f in filas if not f[0]}))
