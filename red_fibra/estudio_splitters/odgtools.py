"""Reading helpers for the study of the splitters: lines / texts of a converted .odg in absolute cm, and the shapes of a .vsdx in the same coordinates."""
import re, zipfile, math, collections
from pathlib import Path
from lxml import etree

DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
SVG = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
CACHE = Path(__file__).resolve().parents[1] / "cache_odg"


def cm(v):
    m = re.match(r"^(-?[\d.]+)\s*(cm|mm|in|pt)?$", str(v or "").strip())
    if not m:
        return None
    return float(m.group(1)) * {"cm": 1, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, None: 1}[m.group(2)]


def estilos(raiz_content, raiz_styles=None):
    """{style-name: {stroke, stroke-width, fill, fill-color, color(text), dash, marker-end/start}} from automatic styles (and the common ones)."""
    salida = {}
    for raiz in [r for r in (raiz_content, raiz_styles) if r is not None]:
        for st in raiz.iter("{%s}style" % STYLE):
            nombre = st.get("{%s}name" % STYLE)
            d = salida.setdefault(nombre, {})
            for hijo in st:
                for k, v in hijo.attrib.items():
                    d[etree.QName(k).localname] = v
    return salida


def puntos_polilinea(e):
    vb = e.get("{%s}viewBox" % SVG)
    pts = e.get("{%s}points" % DRAW)
    x, y, w, h = (cm(e.get("{%s}%s" % (SVG, k))) for k in ("x", "y", "width", "height"))
    if not (vb and pts and None not in (x, y, w, h)):
        return []
    vx, vy, vw, vh = (float(t) for t in vb.split())
    salida = []
    for par in pts.split():
        a, b = par.split(",")
        salida.append((x + (float(a) - vx) / (vw or 1) * w, y + (float(b) - vy) / (vh or 1) * h))
    return salida


def puntos_ruta(e):
    """Only M / L / Z paths (a curve is approximated by its end points)."""
    d = e.get("{%s}d" % SVG)
    vb = e.get("{%s}viewBox" % SVG)
    x, y, w, h = (cm(e.get("{%s}%s" % (SVG, k))) for k in ("x", "y", "width", "height"))
    if not (d and vb and None not in (x, y, w, h)):
        return []
    vx, vy, vw, vh = (float(t) for t in vb.split())
    pares = anclas_svg(d)
    return [(x + (a - vx) / (vw or 1) * w, y + (b - vy) / (vh or 1) * h) for a, b in pares]


def anclas_svg(d):
    """The anchor points (where each segment ends) of an SVG path: M L H V C S Q T A Z, absolute or relative. Curves (the little hops where
    two lines cross) contribute their end point only."""
    fichas = re.findall(r"([MLHVCSQTAZmlhvcsqtaz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)", d)
    cmd, args, cur, ini, salida = None, [], (0.0, 0.0), (0.0, 0.0), []
    n_args = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}

    def aplicar(c, a):
        nonlocal cur, ini
        rel = c.islower()
        u = c.upper()
        if u in ("M", "L", "T"):
            p = (a[0] + (cur[0] if rel else 0), a[1] + (cur[1] if rel else 0))
        elif u == "H":
            p = (a[0] + (cur[0] if rel else 0), cur[1])
        elif u == "V":
            p = (cur[0], a[0] + (cur[1] if rel else 0))
        else:                                              # C S Q A: the last pair is where the segment ends
            p = (a[-2] + (cur[0] if rel else 0), a[-1] + (cur[1] if rel else 0))
        cur = p
        if u == "M":
            ini = p
        salida.append(p)

    for letra, numero in fichas:
        if letra:
            cmd, args = letra, []
            if cmd.upper() == "Z":
                cur = ini
                salida.append(ini)
            continue
        if cmd is None:
            continue
        args.append(float(numero))
        n = n_args[cmd.upper()]
        if n and len(args) == n:
            aplicar(cmd, args)
            args = []
            if cmd == "M":
                cmd = "L"
            elif cmd == "m":
                cmd = "l"
    return salida


def leer_odg(md5):
    """lineas: [{pts:[(x,y)...], estilo:{...}, tipo}], textos: [{x,y,w,h,texto, estilo_texto}] in absolute cm."""
    z = zipfile.ZipFile(CACHE / f"{md5}.odg")
    c = etree.fromstring(z.read("content.xml"))
    try:
        s = etree.fromstring(z.read("styles.xml"))
    except KeyError:
        s = None
    st = estilos(c, s)
    # colour of each text style (span / paragraph)
    lineas, textos, poligonos = [], [], []
    for e in c.iter():
        if not isinstance(e.tag, str):
            continue
        n = etree.QName(e).localname
        if etree.QName(e).namespace != DRAW:
            continue
        estilo = st.get(e.get("{%s}style-name" % DRAW), {})
        if n == "line":
            pts = [(cm(e.get("{%s}x1" % SVG)), cm(e.get("{%s}y1" % SVG))), (cm(e.get("{%s}x2" % SVG)), cm(e.get("{%s}y2" % SVG)))]
            if None not in [v for p in pts for v in p]:
                lineas.append({"pts": pts, "estilo": estilo, "tipo": "line"})
        elif n == "polyline":
            pts = puntos_polilinea(e)
            if len(pts) >= 2:
                lineas.append({"pts": pts, "estilo": estilo, "tipo": "polyline"})
        elif n == "path":
            pts = puntos_ruta(e)
            if len(pts) >= 2:
                lineas.append({"pts": pts, "estilo": estilo, "tipo": "path"})
        elif n == "polygon":
            pts = puntos_polilinea(e)
            if pts:
                poligonos.append({"pts": pts, "estilo": estilo})
        elif n == "frame":
            tb = e.find("{%s}text-box" % DRAW)
            if tb is None:
                continue
            x, y, w, h = (cm(e.get("{%s}%s" % (SVG, k))) for k in ("x", "y", "width", "height"))
            t = "\n".join("".join(p.itertext()) for p in tb.iter("{%s}p" % TEXT)).strip()
            # colour of the first span / paragraph
            color = None
            for sp in list(tb.iter("{%s}span" % TEXT)) + list(tb.iter("{%s}p" % TEXT)):
                nombre = sp.get("{%s}style-name" % TEXT)
                if nombre and st.get(nombre, {}).get("color"):
                    color = st[nombre]["color"]
                    break
            if t and None not in (x, y, w, h):
                textos.append({"x": x + w / 2, "y": y + h / 2, "w": w, "h": h, "texto": t, "color": color})
    return {"lineas": lineas, "textos": textos, "poligonos": poligonos, "estilos": st}
