"""Estudio 1: ¿la conversión (LibreOffice) mueve cosas respecto al Visio original? Con los .vsdx (leibles nativamente) se comparan las posiciones de los
textos del Visio con las del .odg convertido (textos_crudos)."""
import sys, zipfile, re, statistics, math, sqlite3, collections
from pathlib import Path
from lxml import etree
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import main  # noqa
from config import get_settings

VS = Path(__file__).parent / "vsdx"          # the .vsdx of the study (see ../estudio_splitters.md), each named <md5>.vsdx
NS = {"v": "http://schemas.microsoft.com/office/visio/2012/main"}
CM = 2.54


def celda(sh, nombre, defecto=0.0):
    for c in sh.findall("v:Cell", NS):
        if c.get("N") == nombre:
            try:
                return float(c.get("V"))
            except (TypeError, ValueError):
                return defecto
    return defecto


def texto(sh):
    t = sh.find("v:Text", NS)
    return "".join(t.itertext()).strip() if t is not None else ""


def formas(pagina):
    """[(texto, x_in, y_in)] with the absolute position of the centre of each text (no rotation: only translations of the groups)."""
    salida = []

    def rec(nodo, ox, oy):
        for sh in nodo.findall("v:Shapes/v:Shape", NS):
            px, py = celda(sh, "PinX"), celda(sh, "PinY")
            lpx, lpy = celda(sh, "LocPinX"), celda(sh, "LocPinY")
            w, h = celda(sh, "Width"), celda(sh, "Height")
            ax, ay = ox + px, oy + py                      # absolute pin
            t = texto(sh)
            if t:
                # text block centre: TxtPinX/TxtLocPinX when given, else the middle of the shape
                tx = ox + px - lpx + celda(sh, "TxtPinX", w / 2) if False else ox + px - lpx + w / 2
                ty = oy + py - lpy + h / 2
                salida.append((t, tx, ty))
            rec(sh, ox + px - lpx, oy + py - lpy)
    raiz = pagina
    rec(raiz, 0.0, 0.0)
    return salida


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip().upper()


def main_():
    c = sqlite3.connect(get_settings().red_fibra_db)
    resumen = []
    for f in sorted(VS.glob("*.vsdx")):
        md5 = f.stem
        z = zipfile.ZipFile(f)
        paginas = sorted(n for n in z.namelist() if re.match(r"visio/pages/page\d+\.xml", n))
        if not paginas:
            continue
        pag = etree.fromstring(z.read(paginas[0]))
        # page size
        meta = etree.fromstring(z.read("visio/pages/pages.xml"))
        alto = float(next((cc.get("V") for cc in meta.iter("{%s}Cell" % NS["v"]) if cc.get("N") == "PageHeight"), 0) or 0)
        ancho = float(next((cc.get("V") for cc in meta.iter("{%s}Cell" % NS["v"]) if cc.get("N") == "PageWidth"), 0) or 0)
        v = [(norm(t), x * CM, (alto - y) * CM) for t, x, y in formas(pag) if norm(t)]
        odg = c.execute("SELECT x_cm, y_cm, texto FROM textos_crudos WHERE archivo_id IN (SELECT id FROM archivos WHERE md5 = ?)", (md5,)).fetchall()
        o = collections.defaultdict(list)
        for x, y, t in odg:
            if x is not None:
                o[norm(t)].append((x, y))
        difs = []
        for t, x, y in v:
            if len(t) >= 3 and len(o.get(t, [])) == 1:
                ox, oy = o[t][0]
                difs.append((ox - x, oy - y))
        if len(difs) < 5:
            resumen.append((md5[:8], len(v), len(odg), len(difs), None))
            continue
        dx = [d[0] for d in difs]; dy = [d[1] for d in difs]
        mx, my = statistics.median(dx), statistics.median(dy)
        resid = [math.hypot(a - mx, b - my) for a, b in difs]
        resumen.append((md5[:8], len(v), len(odg), len(difs), (round(mx, 2), round(my, 2), round(statistics.median(resid), 2), round(max(resid), 1),
                                                       round(sum(1 for r in resid if r > 0.5) / len(resid) * 100))))
    print("md5      textos_vsdx textos_odg emparejados | traslacion(dx,dy) cm | residuo mediano cm | maximo cm | % con residuo > 0.5 cm")
    for r in resumen:
        print(r)


main_()
