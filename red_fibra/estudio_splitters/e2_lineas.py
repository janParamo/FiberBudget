"""Estudio 2b: ¿qué tienen en común los extremos que NO coinciden? (anidados en grupos / pegados a otra forma / rotados / un solo extremo)"""
import sys, zipfile, math, statistics, collections
from pathlib import Path
from lxml import etree
sys.path.insert(0, str(Path(__file__).parent))
import odgtools as T

VS = Path(__file__).parent / "vsdx"
V = "http://schemas.microsoft.com/office/visio/2012/main"
NS = {"v": V}
CM = 2.54


def celda(sh, n, d=None):
    for c in sh.findall("v:Cell", NS):
        if c.get("N") == n:
            try:
                return float(c.get("V"))
            except (TypeError, ValueError):
                return d
    return d


def formula(sh, n):
    for c in sh.findall("v:Cell", NS):
        if c.get("N") == n:
            return c.get("F") or ""
    return ""


def conectores(pagina, alto):
    sal = []

    def rec(nodo, ox, oy, nivel, angulo_grupo):
        for sh in nodo.findall("v:Shapes/v:Shape", NS):
            px, py, lpx, lpy = celda(sh, "PinX", 0), celda(sh, "PinY", 0), celda(sh, "LocPinX", 0), celda(sh, "LocPinY", 0)
            bx, by, ex, ey = (celda(sh, k) for k in ("BeginX", "BeginY", "EndX", "EndY"))
            ang = celda(sh, "Angle", 0) or 0
            if None not in (bx, by, ex, ey) and sh.get("Type") != "Group":
                sal.append({"b": ((ox + bx) * CM, (alto - (oy + by)) * CM), "e": ((ox + ex) * CM, (alto - (oy + ey)) * CM), "nivel": nivel,
                            "pegado_b": "GLUE" in formula(sh, "BeginX").upper() or "PNT" in formula(sh, "BeginX").upper(),
                            "pegado_e": "PNT" in formula(sh, "EndX").upper() or "GLUE" in formula(sh, "EndX").upper(),
                            "maestro": sh.get("NameU") or "", "grupo_angulo": angulo_grupo})
            rec(sh, ox + px - lpx, oy + py - lpy, nivel + 1, angulo_grupo or abs(ang) > 1e-6)
    rec(pagina, 0.0, 0.0, 0, False)
    return sal


class Indice:
    def __init__(self, puntos, c=2.0):
        self.c = c; self.g = collections.defaultdict(list)
        for x, y in puntos:
            self.g[(int(x // c), int(y // c))].append((x, y))

    def cercano(self, x, y, max_cm=6.0):
        mejor = None; r = int(max_cm // self.c) + 1; cx, cy = int(x // self.c), int(y // self.c)
        for i in range(-r, r + 1):
            for j in range(-r, r + 1):
                for px, py in self.g.get((cx + i, cy + j), ()):
                    d = math.hypot(px - x, py - y)
                    if mejor is None or d < mejor[0]:
                        mejor = (d, px - x, py - y)
        return mejor


filas = []
for f in sorted(VS.glob("*.vsdx")):
    md5 = f.stem
    z = zipfile.ZipFile(f)
    pagina = etree.fromstring(z.read("visio/pages/page1.xml"))
    meta = etree.fromstring(z.read("visio/pages/pages.xml"))
    alto = float(next((c.get("V") for c in meta.iter("{%s}Cell" % V) if c.get("N") == "PageHeight"), 0) or 0)
    odg = T.leer_odg(md5)
    idx = Indice([p for l in odg["lineas"] for p in (l["pts"][0], l["pts"][-1])])
    for c in conectores(pagina, alto):
        rb, re_ = idx.cercano(*c["b"]), idx.cercano(*c["e"])
        filas.append({**c, "db": rb[0] if rb else 99, "de": re_[0] if re_ else 99, "vb": rb[1:] if rb else (0, 0), "ve": re_[1:] if re_ else (0, 0), "md5": md5[:8]})
n = len(filas)
print("conectores:", n)
mal = lambda d: d > 0.5
def pct(lista, cond): return f"{round(sum(1 for x in lista if cond(x)) / max(1, len(lista)) * 100, 1)} % de {len(lista)}"
print("--- por extremo ---")
print("inicio  > 0.5 cm:", pct(filas, lambda x: mal(x["db"])), "| fin > 0.5 cm:", pct(filas, lambda x: mal(x["de"])))
print("--- por nivel de anidamiento (0 = suelto en la página) ---")
for nv in sorted({f["nivel"] for f in filas}):
    sub = [f for f in filas if f["nivel"] == nv]
    print(" nivel", nv, ":", pct(sub, lambda x: mal(x["db"]) or mal(x["de"])), "con algún extremo desplazado")
print("--- pegados a otra forma (fórmula con GLUE/PNT) ---")
pegados = [f for f in filas if f["pegado_b"] or f["pegado_e"]]; libres = [f for f in filas if not (f["pegado_b"] or f["pegado_e"])]
print(" pegados:", pct(pegados, lambda x: mal(x["db"]) or mal(x["de"])), "| sueltos:", pct(libres, lambda x: mal(x["db"]) or mal(x["de"])))
print("--- dentro de un grupo con ángulo ---")
rot = [f for f in filas if f["grupo_angulo"]]; sin = [f for f in filas if not f["grupo_angulo"]]
print(" con grupo rotado:", pct(rot, lambda x: mal(x["db"]) or mal(x["de"])), "| sin:", pct(sin, lambda x: mal(x["db"]) or mal(x["de"])))
print("--- por tipo de conector (nombre) los 6 con más desplazados ---")
cont = collections.Counter(); tot = collections.Counter()
for f in filas:
    k = f["maestro"].split(".")[0]; tot[k] += 1
    if mal(f["db"]) or mal(f["de"]): cont[k] += 1
for k, v in cont.most_common(6): print(" ", k, v, "de", tot[k])
desp = [f for f in filas if mal(f["db"]) or mal(f["de"])]
print("--- los desplazados: ¿un solo extremo o los dos? ---")
print(" solo inicio:", sum(1 for f in desp if mal(f["db"]) and not mal(f["de"])), "| solo fin:", sum(1 for f in desp if mal(f["de"]) and not mal(f["db"])), "| los dos:", sum(1 for f in desp if mal(f["de"]) and mal(f["db"])))
mags = sorted(max(f["db"], f["de"]) for f in desp)
print(" magnitud del desplazamiento (cm) percentiles 25/50/75/90:", [round(mags[int(len(mags) * q)], 1) for q in (0.25, 0.5, 0.75, 0.9)] if mags else None)
