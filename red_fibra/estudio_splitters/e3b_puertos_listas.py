"""Estudio 3b: puertos ocupados leídos del dibujo (líneas que llegan al número) contra las listas de clientes por puerto (verdad conocida en el 13 %)."""
import sys, pickle, re, math, collections, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
datos = pickle.load(open(Path(__file__).parent / "odg_cache.pkl", "rb"))

RE_SPL = re.compile(r"\bSPL\b|\bSPL\d|SPLITTER", re.I)
MORADO = {"#7030a0"}
DORADO = {"#d26d19", "#ea700d", "#966115", "#ea9651", "#ffc000", "#c55a11"}


def clase_color(c):
    c = (c or "").lower()
    return "secundario" if c in MORADO else "principal" if c in DORADO else "otro"


def secuencia(texto):
    """Port numbers of a frame that is only numbers: ('v', [8,7,...]) one per line, ('h', [1,2,...]) separated by spaces; None otherwise."""
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    if not lineas:
        return None
    if all(re.fullmatch(r"\d{1,2}", l) for l in lineas) and len(lineas) >= 2:
        return "v", [int(l) for l in lineas]
    if len(lineas) == 1:
        toks = lineas[0].split()
        if len(toks) >= 2 and all(re.fullmatch(r"\d{1,2}", t) for t in toks):
            return "h", [int(t) for t in toks]
    return None


def posiciones(t, orient, nums):
    n = len(nums)
    if orient == "v":
        top = t["y"] - t["h"] / 2
        return [(t["x"], top + (i + 0.5) * t["h"] / n, nums[i]) for i in range(n)]
    left = t["x"] - t["w"] / 2
    return [(left + (i + 0.5) * t["w"] / n, t["y"], nums[i]) for i in range(n)]


def dist_seg(px, py, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distancia_a_lineas(px, py, lineas, solo_extremos=True):
    mejor = 99.0
    for l in lineas:
        pts = l["pts"]
        if solo_extremos:
            for p in (pts[0], pts[-1]):
                d = math.hypot(p[0] - px, p[1] - py)
                if d < mejor:
                    mejor = d
        else:
            for a, b in zip(pts, pts[1:]):
                d = dist_seg(px, py, a, b)
                if d < mejor:
                    mejor = d
    return mejor


def analizar():
    splitters, lista_gt = [], []
    for md5, d in datos.items():
        textos, lineas = d["textos"], d["lineas"]
        etiquetas = [t for t in textos if RE_SPL.search(t["texto"]) and len(t["texto"]) < 160 and not re.search(r"^\s*\d+\s*[-.)]", t["texto"], re.M)]
        puertos = [(t, secuencia(t["texto"])) for t in textos]
        puertos = [(t, s) for t, s in puertos if s]
        listas = [t for t in textos if RE_SPL.search(t["texto"]) and len(re.findall(r"^\s*(\d{1,2})\s*[-.)]", t["texto"], re.M)) >= 2]
        for e in etiquetas:
            col = clase_color(e["color"])
            # port frame: the nearest frame of numbers within 8 cm whose colour is the label's (black only when the label is black)
            cand = [(math.hypot(t["x"] - e["x"], t["y"] - e["y"]), t, s) for t, s in puertos
                    if math.hypot(t["x"] - e["x"], t["y"] - e["y"]) <= 8 and (t["color"] or "").lower() == (e["color"] or "").lower() and len(s[1]) >= 3]
            if not cand:
                splitters.append({"md5": md5, "etiqueta": e, "color": col, "ports": None})
                continue
            cand.sort(key=lambda c: c[0])
            _, t, (orient, nums) = cand[0]
            splitters.append({"md5": md5, "etiqueta": e, "color": col, "frame": t, "orient": orient, "nums": nums, "ports": posiciones(t, orient, nums), "lineas": lineas})
        for g in listas:
            lst = dict((int(n), v.strip()) for n, v in re.findall(r"^\s*(\d{1,2})\s*[-.)]\s*(.*)$", g["texto"], re.M))
            cerca = [(math.hypot(s["etiqueta"]["x"] - g["x"], s["etiqueta"]["y"] - g["y"]), s) for s in splitters if s["md5"] == md5 and s.get("ports")]
            cerca = [c for c in cerca if c[0] <= 10]
            if cerca:
                cerca.sort(key=lambda c: c[0])
                lista_gt.append({"lista": lst, "split": cerca[0][1], "d": cerca[0][0], "texto": g["texto"]})
    return splitters, lista_gt


if __name__ == "__main__":
    splitters, gt = analizar()
    print("etiquetas de splitter:", len(splitters), "| con cuadro de números de puerto del mismo color a <= 8 cm:", sum(1 for s in splitters if s["ports"]))
    print("por color:", collections.Counter((s["color"], bool(s["ports"])) for s in splitters))
    print("listas de clientes por puerto con su splitter dibujado:", len(gt))
    # per-port comparison for several radii
    for modo, solo_ext in (("extremos", True), ("segmentos", False)):
        for r in (0.3, 0.5, 0.8, 1.2):
            tp = fp = fn = tn = 0
            for g in gt:
                s = g["split"]
                for x, y, n in s["ports"]:
                    if n not in g["lista"]:
                        continue
                    usado_gt = bool(g["lista"][n])
                    usado = distancia_a_lineas(x, y, s["lineas"], solo_ext) <= r
                    if usado and usado_gt: tp += 1
                    elif usado and not usado_gt: fp += 1
                    elif not usado and usado_gt: fn += 1
                    else: tn += 1
            tot = tp + fp + fn + tn
            print(f"{modo:9} r={r}: ports compared {tot} | accuracy {100 * (tp + tn) / max(1, tot):.0f} % | free ports: precision {100 * tn / max(1, tn + fn):.0f} % recall {100 * tn / max(1, tn + fp):.0f} % (tn={tn} fn={fn} fp={fp})")
    # distribution of the distance of a port to the nearest line end, used vs free (ground truth)
    du, df = [], []
    for g in gt:
        for x, y, n in g["split"]["ports"]:
            if n in g["lista"]:
                (du if g["lista"][n] else df).append(distancia_a_lineas(x, y, g["split"]["lineas"], True))
    q = lambda v: [round(statistics.quantiles(v, n=10)[i], 2) for i in (0, 2, 4, 6, 8)] if len(v) > 10 else v
    print("distance port -> nearest line end, ground-truth USED ports (n=%d) deciles 10/30/50/70/90:" % len(du), q(du))
    print("distance port -> nearest line end, ground-truth FREE ports (n=%d) deciles 10/30/50/70/90:" % len(df), q(df))
