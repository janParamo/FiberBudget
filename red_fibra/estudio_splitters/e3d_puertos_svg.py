"""Estudio 3e: posiciones EXACTAS de cada número de puerto (SVG de LibreOffice) y las líneas del .odg: ¿se separan los puertos libres de los ocupados?"""
import sys, re, math, collections, statistics, pickle
from pathlib import Path
from lxml import etree
sys.path.insert(0, str(Path(__file__).parent))
import e3b_puertos_listas as E

SVG = "{http://www.w3.org/2000/svg}"
CACHE = Path(__file__).resolve().parents[1] / "cache_diagramas"
datos = E.datos


def num(v):
    m = re.match(r"-?[\d.]+", v or "")
    return float(m.group(0)) if m else 0.0


def cm_svg(v):
    return v / 1000.0                                  # viewBox in 1/100 mm


def parrafos(md5):
    """[(frame_id, x_cm, y_cm, ancho_cm, texto, fill)] one per paragraph (line of text) of the SVG, with the centre of the line."""
    raiz = etree.parse(str(CACHE / f"{md5}_0.svg")).getroot()
    sal = []
    for fid, tx in enumerate(raiz.iter(SVG + "text")):
        for pos in tx.iter(SVG + "tspan"):
            if pos.get("class") != "TextPosition":
                continue
            x, y = pos.get("x"), pos.get("y")
            if x is None:
                continue
            texto = "".join(pos.itertext())
            fs = 0.0; ancho = 0.0; fill = None
            for h in pos.iter(SVG + "tspan"):
                if h.get("font-size"):
                    fs = max(fs, num(h.get("font-size")))
                if h.get("textLength"):
                    ancho += num(h.get("textLength"))
                if h.get("fill") and not fill:
                    fill = h.get("fill")
            sal.append((fid, cm_svg(float(x)) + cm_svg(ancho) / 2, cm_svg(float(y)) - cm_svg(fs) * 0.32, cm_svg(ancho), texto, fill))
    return sal


def a_hex(fill):
    m = re.match(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", fill or "")
    return "#%02x%02x%02x" % tuple(int(v) for v in m.groups()) if m else (fill or "").lower()


def puertos_svg(md5):
    """{frame: [(x,y,n,color)]} of the frames whose paragraphs are only port numbers (one per line, or several on one line)."""
    por_frame = collections.defaultdict(list)
    for fid, x, y, w, texto, fill in parrafos(md5):
        por_frame[fid].append((x, y, w, texto.strip(), a_hex(fill)))
    sal = []
    for fid, ps in por_frame.items():
        if all(re.fullmatch(r"\d{1,2}", p[3]) for p in ps) and len(ps) >= 3:
            sal.append([(p[0], p[1], int(p[3]), p[4]) for p in ps])
        elif len(ps) == 1 and re.fullmatch(r"(\d{1,2}\s+){2,}\d{1,2}", ps[0][3]):
            x, y, w, t, col = ps[0]
            toks = [(m.start(), m.end(), int(m.group(0))) for m in re.finditer(r"\d+", t)]
            L = len(t)
            sal.append([(x - w / 2 + w * (a + b) / 2 / L, y, n, col) for a, b, n in toks])
    return sal


def analizar_svg():
    splitters, gt = E.analizar()
    por_md5 = {}
    cuentas = collections.Counter()
    gt2 = []
    for g in gt:
        md5 = g["split"]["md5"]
        if not (CACHE / f"{md5}_0.svg").is_file():
            continue
        if md5 not in por_md5:
            por_md5[md5] = puertos_svg(md5)
        e = g["split"]["etiqueta"]
        # the port frame of this splitter: the nearest one (to the label) with the label's colour
        mejor = None
        for fr in por_md5[md5]:
            cx = statistics.mean(p[0] for p in fr); cy = statistics.mean(p[1] for p in fr)
            col = fr[0][3]
            d = math.hypot(cx - e["x"], cy - e["y"])
            if d <= 8 and col.lower() == (e["color"] or "").lower() and (mejor is None or d < mejor[0]):
                mejor = (d, fr)
        if mejor:
            gt2.append({"lista": g["lista"], "ports": [(x, y, n) for x, y, n, _ in mejor[1]], "lineas": datos[md5]["lineas"]})
        else:
            cuentas["sin cuadro de puertos en el SVG"] += 1
    return gt2, cuentas


def cuenta(x, y, lineas, r, con_flecha):
    n = 0
    for l in lineas:
        pts = l["pts"]
        for p, f in ((pts[0], l["flecha_ini"]), (pts[-1], l["flecha_fin"])):
            if math.hypot(p[0] - x, p[1] - y) <= r and (f or not con_flecha):
                n += 1
    return n


if __name__ == "__main__":
    gt2, cu = analizar_svg()
    filas = []
    for g in gt2:
        for x, y, n in g["ports"]:
            if n in g["lista"]:
                filas.append((bool(g["lista"][n]), x, y, g["lineas"]))
    print("splitters con puertos exactos:", len(gt2), cu, "| puertos comparados:", len(filas), "| libres:", sum(1 for f in filas if not f[0]))
    for con_flecha in (True, False):
        for r in (0.15, 0.25, 0.4, 0.6):
            feats = [(f[0], cuenta(f[1], f[2], f[3], r, con_flecha)) for f in filas]
            du = collections.Counter(min(c, 4) for u, c in feats if u); dl = collections.Counter(min(c, 4) for u, c in feats if not u)
            print(f"\n{'flechas' if con_flecha else 'lineas'} r={r} nº de extremos en el puerto: usados {dict(sorted(du.items()))} | libres {dict(sorted(dl.items()))}")
            for k in (0, 1):
                tp = sum(1 for u, c in feats if not u and c <= k); fp = sum(1 for u, c in feats if u and c <= k); nl = sum(1 for u, c in feats if not u)
                print(f"   libre si <= {k}: libres detectados {tp} de {nl} ({100 * tp / max(1, nl):.0f} %), usados tomados por libres {fp} de {sum(1 for u, c in feats if u)} -> precision {100 * tp / max(1, tp + fp):.0f} %")
