#!/usr/bin/env python3
"""
PILOTO: extracción automática de fusiones desde los diagramas convertidos (cache_odg/<md5>.odg).

No lo llama el importador todavía; lo usa piloto_fusiones.py para medir precisión y cobertura.

Cómo están dibujadas las fusiones (revisado en los diagramas reales):
  - En los .odg no hay conectores: cada fusión es una línea suelta (draw:line, draw:polyline o
    draw:path), casi siempre un "puente" en ángulo recto con flechas, que va del número de un
    hilo de un cable al número de un hilo de otro cable (o a un splitter / cliente).
  - Los números de hilo están en UN cuadro de texto por cable ("1 2 3 ... 24" o "6 / 5 / 4"):
    la posición de cada número se estima repartiendo el cuadro.
  - El color del trazo es el color del hilo en código TIA-598 (1 azul ... 12 aqua), dentro de su
    buffer; los buffers pueden ser de 12, 6, 2... hilos (etiqueta del cable: "4BUFFER DE 6H").

Cada fusión detectada se guarda en la tabla fusiones_piloto con una confianza 0-1 y el motivo.
"""
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
import zipfile

from lxml import etree  # type: ignore[attr-defined]

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)
import importador  # noqa: E402  (reuses _cm and _vertices_path)

NS_D = 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0'
NS_S = 'urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0'
NS_ST = 'urn:oasis:names:tc:opendocument:xmlns:style:1.0'
NS_T = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
NS_FO = 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'

# Tolerancias (cm en el dibujo) - configurables por parámetro en extraer_fusiones()
TOLERANCIAS = {
    'hilo': 0.45,          # punta de la línea -> centro estimado del número de hilo
    'union': 0.08,         # puntas de dos tramos del mismo color que forman una sola línea
    'texto': 0.8,          # punta de la línea -> borde del texto de un splitter / cliente
    'cable': 6.0,          # cuadro de numeración -> etiqueta del cable o de la mufa vecina
    'buffer': 12.0,        # cuadro de numeración -> texto "4BUFFER DE 6H"
}
UMBRAL_COLOR_DELTA_E = 32.0    # más lejos de cualquier color TIA -> "otro"

# Código TIA-598 de 12 colores, con los tonos que usan los diagramas (paleta de Office)
TIA_598 = [
    (1, 'azul', ['#0000ff', '#0070c0', '#0066cc', '#3366ff', '#2f5597', '#4472c4']),
    (2, 'naranja', ['#ff8000', '#ffa500', '#ff6600', '#ed7d31', '#d26d19', '#f4b183', '#c55a11']),
    (3, 'verde', ['#00b050', '#00ff00', '#008000', '#70ad47', '#92d050', '#00a933']),
    (4, 'café', ['#8b4513', '#996633', '#a0522d', '#7f6000', '#843c0c', '#806000']),
    (5, 'gris', ['#808080', '#7f7f7f', '#a6a6a6', '#595959', '#999999']),
    (6, 'blanco', ['#ffffff', '#f2f2f2', '#d9d9d9']),
    (7, 'rojo', ['#ff0000', '#c00000', '#e60000', '#c9211e']),
    (8, 'negro', ['#000000', '#262626', '#404040', '#1a1a1a']),
    (9, 'amarillo', ['#ffff00', '#ffc000', '#ffd966', '#ffde59']),
    (10, 'violeta', ['#7030a0', '#800080', '#9933ff', '#7f3f98', '#8064a2']),
    (11, 'rosa', ['#ff33cc', '#ff66cc', '#ff00ff', '#ff99cc', '#ff40ff']),
    (12, 'aqua', ['#00b0f0', '#00ffff', '#33cccc', '#00b7c3', '#5bc0eb']),
]

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS fusiones_piloto (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    pagina          INTEGER NOT NULL DEFAULT 0,
    entrada         TEXT    NOT NULL,              -- cable / buffer / hilo de entrada
    salida          TEXT    NOT NULL,              -- cable / buffer / hilo de salida, o puerto de splitter / cliente
    hilo_entrada    INTEGER,
    hilo_salida     INTEGER,
    color           TEXT,                          -- color real del trazo (#rrggbb)
    color_tia       TEXT,                          -- "10 violeta" | "otro"
    confianza       REAL    NOT NULL,              -- 0 a 1
    motivo          TEXT,
    x1_cm REAL, y1_cm REAL, x2_cm REAL, y2_cm REAL, -- extremos del trazo en el dibujo
    puntos          TEXT,                          -- JSON [[x, y], ...] en cm (para dibujarla encima)
    creado          TEXT
);
CREATE INDEX IF NOT EXISTS ix_fusiones_archivo ON fusiones_piloto(archivo_id);
"""

RE_NUMERACION = re.compile(r'^[\d\s/\-–,.]+$')
RE_NUMERO = re.compile(r'\d+')
RE_DESTINO_TEXTO = re.compile(r'\bSPL|\bSPLIT|\b1\s*[X/*]\s*(2|4|8|16|32|64)\b|\bPUERTO|\bOLT\b|\bC\s?\d{4,6}\b|\bID\s*\d{5,7}\b|\bODF\b', re.I)
RE_BUFFER = re.compile(r'(\d+)\s*BUFFER\w*\s*(?:DE\s*)?(\d+)\s*H', re.I)
RE_CABLE_HILOS = re.compile(r'(?<![\w.])(\d{1,3})\s*H(?:ILOS)?\b', re.I)


# --------------------------------------------------------------------------- colores

def _hex_a_lab(color):
    color = color.lstrip('#')
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in (r, g, b)]
    x = (lin[0] * 0.4124 + lin[1] * 0.3576 + lin[2] * 0.1805) / 0.95047
    y = lin[0] * 0.2126 + lin[1] * 0.7152 + lin[2] * 0.0722
    z = (lin[0] * 0.0193 + lin[1] * 0.1192 + lin[2] * 0.9505) / 1.08883
    f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (x, y, z)]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


_LAB_TIA = [(num, nombre, _hex_a_lab(h)) for num, nombre, tonos in TIA_598 for h in tonos]


def color_tia(color):
    """(número 1-12 o None, nombre, delta E) del color TIA-598 más cercano a '#rrggbb'."""
    if not color or not re.match(r'^#[0-9a-fA-F]{6}$', color):
        return None, 'otro', None
    lab = _hex_a_lab(color)
    num, nombre, d = min(((n, nom, math.dist(lab, l)) for n, nom, l in _LAB_TIA), key=lambda t: t[2])
    if d > UMBRAL_COLOR_DELTA_E:
        return None, 'otro', round(d, 1)
    return num, nombre, round(d, 1)


def color_esperado(hilo, hilos_por_buffer=12):
    """(número TIA esperado, número de buffer) del hilo `hilo` (1..N) con buffers de `hilos_por_buffer`."""
    b = hilos_por_buffer if hilos_por_buffer and 0 < hilos_por_buffer <= 12 else 12
    return (hilo - 1) % b + 1, (hilo - 1) // b + 1


# --------------------------------------------------------------------------- geometría del .odg

def _estilos(z):
    props, padre = {}, {}
    for archivo in ('styles.xml', 'content.xml'):
        try:
            raiz = etree.fromstring(z.read(archivo))
        except KeyError:
            continue
        for st in raiz.iter('{%s}style' % NS_ST):
            nombre = st.get('{%s}name' % NS_ST)
            padre[nombre] = st.get('{%s}parent-style-name' % NS_ST)
            gp = st.find('{%s}graphic-properties' % NS_ST)
            d = {}
            if gp is not None:
                for clave, attr in (('stroke', '{%s}stroke' % NS_D), ('color', '{%s}stroke-color' % NS_S),
                                    ('ancho', '{%s}stroke-width' % NS_S), ('marker_start', '{%s}marker-start' % NS_D),
                                    ('marker_end', '{%s}marker-end' % NS_D)):
                    if gp.get(attr) is not None:
                        d[clave] = gp.get(attr)
            props[nombre] = d

    def resolver(nombre):
        res, vistos = {}, set()
        while nombre and nombre not in vistos:
            vistos.add(nombre)
            for k, v in props.get(nombre, {}).items():
                res.setdefault(k, v)
            nombre = padre.get(nombre)
        return res
    return resolver


def _longitud(v):
    return importador._cm(v) or 0.0


def _transformacion(cadena):
    """Función (x, y) -> (x, y) en cm para un draw:transform de ODF ("rotate (a) translate (x y)").

    Las operaciones se aplican en el orden escrito; rotate usa radianes, positivo = antihorario
    en pantalla (y hacia abajo).
    """
    ops = re.findall(r'(rotate|translate|scale|skewX|skewY|matrix)\s*\(([^)]*)\)', cadena or '')
    if not ops:
        return None

    def aplicar(x, y):
        for op, args in ops:
            a = args.replace(',', ' ').split()
            if op == 'rotate':
                t = float(a[0])
                x, y = x * math.cos(t) + y * math.sin(t), -x * math.sin(t) + y * math.cos(t)
            elif op == 'translate':
                x, y = x + _longitud(a[0]), y + (_longitud(a[1]) if len(a) > 1 else 0.0)
            elif op == 'scale':
                sx = float(a[0])
                x, y = x * sx, y * (float(a[1]) if len(a) > 1 else sx)
            elif op == 'skewX':
                x = x + y * math.tan(float(a[0]))
            elif op == 'skewY':
                y = y + x * math.tan(float(a[0]))
            elif op == 'matrix' and len(a) == 6:
                m = [float(a[0]), float(a[1]), float(a[2]), float(a[3]), _longitud(a[4]), _longitud(a[5])]
                x, y = m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]
        return x, y
    return aplicar


def _ubicador(el):
    """Función local -> página (cm) para una figura: con draw:transform o con svg:x/svg:y."""
    trans = _transformacion(el.get('{%s}transform' % NS_D))
    if trans:
        return trans
    x = importador._cm(el.get('{%s}x' % NS_S)) or 0.0
    y = importador._cm(el.get('{%s}y' % NS_S)) or 0.0
    return lambda px, py: (x + px, y + py)


def _trazos(el, nombre):
    """Listas de vértices (cm, coordenadas de página) de una línea, polilínea o path."""
    g = lambda a: importador._cm(el.get('{%s}%s' % (NS_S, a)))
    if nombre == 'line':
        p = [(g('x1'), g('y1')), (g('x2'), g('y2'))]
        if any(None in q for q in p):
            return []
        trans = _transformacion(el.get('{%s}transform' % NS_D))
        return [[trans(*q) for q in p] if trans else p]
    w, h = g('width'), g('height')
    if w is None or h is None:
        return []
    try:
        vx, vy, vw, vh = [float(v) for v in (el.get('{%s}viewBox' % NS_S) or '').split()]
    except ValueError:
        return []
    ubicar = _ubicador(el)
    sx, sy = (w / vw if vw else 1.0), (h / vh if vh else 1.0)
    escala = lambda px, py: ubicar((px - vx) * sx, (py - vy) * sy)
    if nombre == 'polyline':
        try:
            pts = [escala(*map(float, p.split(','))) for p in (el.get('{%s}points' % NS_D) or '').split()]
        except ValueError:
            return []
        return [pts] if len(pts) > 1 else []
    return importador._vertices_path(el.get('{%s}d' % NS_S), escala)


def _texto(el):
    parrafos = [''.join(p.itertext()).strip() for p in el.iter('{%s}p' % NS_T)]
    return [p for p in parrafos if p]


def leer_dibujo(odg):
    """{pagina: {'lineas': [...], 'textos': [...]}} con coordenadas de página en cm."""
    z = zipfile.ZipFile(odg)
    resolver = _estilos(z)
    raiz = etree.fromstring(z.read('content.xml'))
    paginas = {}
    for pi, pagina in enumerate(raiz.iter('{%s}page' % NS_D)):
        lineas, textos = [], []
        for el in pagina.iter():
            if not isinstance(el.tag, str) or etree.QName(el).namespace != NS_D:
                continue
            nombre = etree.QName(el).localname
            if nombre in ('line', 'polyline', 'path'):
                st = resolver(el.get('{%s}style-name' % NS_D))
                if st.get('stroke') == 'none':
                    continue
                for pts in _trazos(el, nombre):
                    lineas.append({'puntos': pts, 'color': (st.get('color') or '#000000').lower(),
                                   'flechas': bool(st.get('marker_start') or st.get('marker_end')),
                                   'ancho': _longitud(st.get('ancho'))})
            if nombre in ('frame', 'custom-shape', 'rect', 'ellipse', 'line', 'polyline', 'path'):
                if any(etree.QName(c).localname in ('frame', 'custom-shape') for c in el.iterdescendants()
                       if isinstance(c.tag, str)):
                    continue
                parrafos = _texto(el)
                if not parrafos:
                    continue
                g = lambda a: importador._cm(el.get('{%s}%s' % (NS_S, a)))
                w, h = g('width'), g('height')
                if w is None or h is None:
                    x1, y1, x2, y2 = g('x1'), g('y1'), g('x2'), g('y2')
                    if None in (x1, y1, x2, y2):
                        continue
                    ubicar, w, h = (lambda px, py, x=min(x1, x2), y=min(y1, y2): (x + px, y + py)), abs(x2 - x1), abs(y2 - y1)
                else:
                    ubicar = _ubicador(el)
                esquinas = [ubicar(0, 0), ubicar(w, 0), ubicar(0, h), ubicar(w, h)]
                textos.append({'parrafos': parrafos, 'texto': ' / '.join(parrafos), 'w': w, 'h': h, 'ubicar': ubicar,
                               'caja': (min(p[0] for p in esquinas), min(p[1] for p in esquinas),
                                        max(p[0] for p in esquinas), max(p[1] for p in esquinas))})
        paginas[pi] = {'lineas': lineas, 'textos': textos}
    return paginas


# --------------------------------------------------------------------------- números de hilo

def numeros_de_hilo(textos):
    """Posición estimada de cada número de los cuadros de numeración.

    Un párrafo "1 2 3 ... 24": los números se reparten a lo ancho según su posición en el texto.
    Varios párrafos ("6", "5", "4"... o "6 / 5 / 4"): un párrafo por renglón, repartidos a lo alto.
    """
    salida = []
    for b, t in enumerate(textos):
        if not RE_NUMERACION.match(t['texto']) or not RE_NUMERO.search(t['texto']):
            continue
        parrafos = t['parrafos']
        for i, parrafo in enumerate(parrafos):
            largo = max(len(parrafo), 1)
            for m in RE_NUMERO.finditer(parrafo):
                fx = (m.start() + m.end()) / 2 / largo
                fy = (i + 0.5) / len(parrafos)
                x, y = t['ubicar'](t['w'] * fx, t['h'] * fy)
                salida.append({'numero': int(m.group()), 'x': x, 'y': y, 'bloque': b})
    return salida


def _dist_caja(x, y, caja):
    x0, y0, x1, y1 = caja
    return math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))


def _etiqueta_de_bloque(textos, bloque, tol):
    """Texto más cercano al cuadro de numeración que no sea numeración: cable o mufa vecina."""
    caja = textos[bloque]['caja']
    cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
    mejor = None
    for i, t in enumerate(textos):
        if i == bloque or RE_NUMERACION.match(t['texto']) or len(t['texto']) < 3:
            continue
        d = _dist_caja(cx, cy, t['caja']) - max(caja[2] - caja[0], caja[3] - caja[1]) / 2
        if d <= tol and (mejor is None or d < mejor[0]):
            mejor = (d, t['texto'])
    return mejor[1] if mejor else None


def _hilos_por_buffer(textos, bloque, tol):
    caja = textos[bloque]['caja']
    cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
    cand = []
    for t in textos:
        m = RE_BUFFER.search(t['texto'])
        if m:
            cand.append((_dist_caja(cx, cy, t['caja']), int(m.group(2))))
    cand = [c for c in cand if c[0] <= tol]
    return min(cand)[1] if cand else 12


# --------------------------------------------------------------------------- líneas -> fusiones

def _unir_tramos(lineas, tol, numeros, tol_hilo):
    """Une tramos del mismo color cuyas puntas coinciden (una fusión dibujada en varias piezas),
    salvo que la punta común esté sobre un número de hilo (ahí terminan dos fusiones distintas)."""
    sobre_numero = lambda p: any(math.hypot(p[0] - n['x'], p[1] - n['y']) <= tol_hilo for n in numeros)
    tramos = [dict(l, puntos=list(l['puntos'])) for l in lineas if len(l['puntos']) > 1]
    cambio = True
    while cambio:
        cambio = False
        for i in range(len(tramos)):
            a = tramos[i]
            if a is None:
                continue
            for j in range(i + 1, len(tramos)):
                b = tramos[j]
                if b is None or b['color'] != a['color']:
                    continue
                for pa, pb, nuevo in ((a['puntos'][-1], b['puntos'][0], lambda: a['puntos'] + b['puntos'][1:]),
                                      (a['puntos'][-1], b['puntos'][-1], lambda: a['puntos'] + b['puntos'][-2::-1]),
                                      (a['puntos'][0], b['puntos'][-1], lambda: b['puntos'] + a['puntos'][1:]),
                                      (a['puntos'][0], b['puntos'][0], lambda: b['puntos'][::-1] + a['puntos'][1:])):
                    if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= tol and not sobre_numero(pa):
                        a['puntos'] = nuevo()
                        a['flechas'] = a['flechas'] or b['flechas']
                        tramos[j] = None
                        cambio = True
                        break
        tramos = [t for t in tramos if t is not None]
    return tramos


def _extremo(p, numeros, textos, tol):
    """Lo que hay en la punta p: el número de hilo más cercano o un texto de splitter / cliente."""
    cerca = min(((math.hypot(p[0] - n['x'], p[1] - n['y']), n) for n in numeros), key=lambda t: t[0], default=None)
    if cerca and cerca[0] <= tol['hilo']:
        return {'tipo': 'hilo', 'numero': cerca[1]['numero'], 'bloque': cerca[1]['bloque'], 'd': cerca[0]}
    destino = min(((_dist_caja(p[0], p[1], t['caja']), t) for t in textos if RE_DESTINO_TEXTO.search(t['texto'])),
                  key=lambda t: t[0], default=None)
    if destino and destino[0] <= tol['texto']:
        return {'tipo': 'texto', 'texto': destino[1]['texto'], 'd': destino[0]}
    return None


def _describir(ext, etiquetas, buffers):
    if ext['tipo'] == 'texto':
        return 'puerto/cliente: ' + ext['texto'][:120]
    color_num, buffer = color_esperado(ext['numero'], buffers[ext['bloque']])
    nombre_color = next(n for num, n, _ in TIA_598 if num == color_num)
    cable = etiquetas[ext['bloque']]
    # The nearest text is the cable or neighbour-mufa label when there is one, but often a client
    # name: it is shown as "cerca de", not as the cable.
    return 'hilo %d (buffer %d, %s)%s' % (ext['numero'], buffer, nombre_color,
                                         (' · cerca de: ' + cable[:80]) if cable else '')


def extraer_fusiones(odg, tolerancias=None):
    """Fusiones detectadas en un .odg: lista de dicts listos para guardar en fusiones_piloto."""
    tol = dict(TOLERANCIAS, **(tolerancias or {}))
    resultado = []
    for pagina, dibujo in leer_dibujo(odg).items():
        textos, numeros = dibujo['textos'], numeros_de_hilo(dibujo['textos'])
        if not numeros:
            continue
        bloques = {n['bloque'] for n in numeros}
        etiquetas = {b: _etiqueta_de_bloque(textos, b, tol['cable']) for b in bloques}
        buffers = {b: _hilos_por_buffer(textos, b, tol['buffer']) for b in bloques}
        for tramo in _unir_tramos(dibujo['lineas'], tol['union'], numeros, tol['hilo']):
            a, b = tramo['puntos'][0], tramo['puntos'][-1]
            ea, eb = _extremo(a, numeros, textos, tol), _extremo(b, numeros, textos, tol)
            if ea is None or eb is None or (ea['tipo'] == 'texto' and eb['tipo'] == 'texto'):
                continue
            if ea['tipo'] == 'hilo' and eb['tipo'] == 'hilo' and (ea['numero'], ea['bloque']) == (eb['numero'], eb['bloque']):
                continue
            if ea['tipo'] == 'texto':                       # the splitter / client end is the output
                ea, eb, a, b = eb, ea, b, a
            confianza, motivo = 0.0, []
            for nombre, e in (('A', ea), ('B', eb)):
                if e['tipo'] == 'hilo':
                    confianza += 0.3 * (1 - e['d'] / tol['hilo'])
                    motivo.append('extremo %s a %.2f cm del hilo %d' % (nombre, e['d'], e['numero']))
                else:
                    confianza += 0.2 * (1 - e['d'] / tol['texto'])
                    motivo.append('extremo %s a %.2f cm de "%s"' % (nombre, e['d'], e['texto'][:40]))
            num_tia, nombre_tia, delta = color_tia(tramo['color'])
            esperados = [color_esperado(e['numero'], buffers[e['bloque']])[0] for e in (ea, eb) if e['tipo'] == 'hilo']
            if num_tia is None:
                motivo.append('color %s fuera del código TIA' % tramo['color'])
            elif num_tia in esperados:
                confianza += 0.25
                motivo.append('color %s = hilo %s del buffer' % (nombre_tia, ', '.join(
                    str(e['numero']) for e in (ea, eb) if e['tipo'] == 'hilo'
                    and color_esperado(e['numero'], buffers[e['bloque']])[0] == num_tia)))
            else:
                confianza -= 0.15
                motivo.append('color %s no corresponde al número de hilo' % nombre_tia)
            if tramo['flechas']:
                confianza += 0.05
                motivo.append('con flechas')
            if ea['tipo'] == 'hilo' and eb['tipo'] == 'hilo':
                if ea['bloque'] != eb['bloque']:
                    confianza += 0.1
                    motivo.append('une cables distintos')
                else:
                    confianza -= 0.1
                    motivo.append('ambos extremos en el mismo cable')
            resultado.append({
                'pagina': pagina,
                'entrada': _describir(ea, etiquetas, buffers),
                'salida': _describir(eb, etiquetas, buffers),
                'hilo_entrada': ea.get('numero'), 'hilo_salida': eb.get('numero'),
                'color': tramo['color'],
                'color_tia': ('%d %s' % (num_tia, nombre_tia)) if num_tia else 'otro',
                'confianza': round(min(max(confianza, 0.0), 1.0), 2),
                'motivo': '; '.join(motivo),
                'x1_cm': round(a[0], 3), 'y1_cm': round(a[1], 3), 'x2_cm': round(b[0], 3), 'y2_cm': round(b[1], 3),
                'puntos': json.dumps([[round(x, 3), round(y, 3)] for x, y in tramo['puntos']]),
            })
    return resultado


# --------------------------------------------------------------------------- guardar

COLUMNAS = ('pagina', 'entrada', 'salida', 'hilo_entrada', 'hilo_salida', 'color', 'color_tia', 'confianza',
            'motivo', 'x1_cm', 'y1_cm', 'x2_cm', 'y2_cm', 'puntos')


def guardar(con, archivo_id, fusiones):
    """Reemplaza las fusiones piloto de un archivo (la tabla se crea si la base es anterior)."""
    con.executescript(DDL_SQLITE)
    con.execute('DELETE FROM fusiones_piloto WHERE archivo_id = ?', (archivo_id,))
    ahora = dt.datetime.now().isoformat(timespec='seconds')
    con.executemany('INSERT INTO fusiones_piloto(archivo_id, %s, creado) VALUES (?, %s, ?)'
                    % (', '.join(COLUMNAS), ', '.join('?' * len(COLUMNAS))),
                    [(archivo_id,) + tuple(f[c] for c in COLUMNAS) + (ahora,) for f in fusiones])
    con.commit()


def tamano_pagina_cm(odg):
    """(ancho, alto) de la página en cm, de styles.xml."""
    estilos = zipfile.ZipFile(odg).read('styles.xml').decode('utf-8', 'ignore')
    ancho = re.search(r'fo:page-width="([\d.]+(?:cm|mm|in))"', estilos)
    alto = re.search(r'fo:page-height="([\d.]+(?:cm|mm|in))"', estilos)
    if not (ancho and alto):
        return 29.7, 21.0
    return importador._cm(ancho.group(1)), importador._cm(alto.group(1))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Extrae fusiones de un .odg (prueba rápida, sin guardar)')
    ap.add_argument('odg')
    args = ap.parse_args()
    for f in extraer_fusiones(args.odg):
        print('%.2f  %-50s -> %-50s  %s' % (f['confianza'], f['entrada'][:50], f['salida'][:50], f['color_tia']))
