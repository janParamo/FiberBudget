#!/usr/bin/env python3
"""
Importador de diagramas de red de fibra óptica (Visio .vsd/.vsdx + Excel de anillos)
hacia una base SQLite.

Uso:
    python importador.py --origen "C:/Users/.../DIAGRAMAS ACTUALIZADOS" --db red_fibra.db
    python importador.py --origen ... --db ... --soffice "C:/LibreOfficePortable/App/libreoffice/program/soffice.exe"

Cómo funciona:
  1. Recorre la carpeta y calcula el MD5 de cada archivo (los idénticos se marcan duplicados).
  2. Convierte cada Visio a .odg con LibreOffice (headless). La conversión se guarda en una
     caché por MD5, así que en ejecuciones siguientes solo se convierten archivos nuevos o cambiados.
  3. Extrae los textos con su posición y los clasifica: nodo con coordenadas, cable (24H / 200MTS),
     cliente (C12345 ... ID123456), numeración de hilos, otros.
  4. Une las apariciones del mismo nodo entre archivos y arma los enlaces.
  5. Lee el Excel de anillos (recorridos mufa a mufa con hilos).
  6. Reconstruye la base completa en cada ejecución (siempre refleja el estado de la carpeta).

Requisitos: Python 3.8+, lxml, openpyxl, LibreOffice (solo para convertir; sirve la versión portable).
"""
import argparse
import datetime as dt
import hashlib
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections import defaultdict, Counter

try:
    from lxml import etree  # type: ignore[attr-defined]  # módulo compilado: el editor no ve sus símbolos
except ImportError:
    sys.exit("Falta lxml:  pip install lxml")

AQUI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
NS_D = 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0'
NS_S = 'urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0'
NS_T = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'

# Caja geográfica de Nicaragua (con margen)
LAT_MIN, LAT_MAX = 10.5, 15.2
LON_MIN, LON_MAX = -88.0, -82.5


def md5_archivo(ruta):
    h = hashlib.md5()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1 << 20), b''):
            h.update(bloque)
    return h.hexdigest()


def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


STOP = {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y', 'A', 'AL', 'EN', 'FTE', 'FRENTE'}


def normalizar(nombre):
    s = sin_acentos(nombre or '').upper()
    s = re.sub(r'\bMF\b|\bMC\b|\bMUFAS?\b', ' MUFA ', s)
    s = re.sub(r'\bMN\b', ' MINI NODO ', s)
    s = re.sub(r'#\s*', '', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    toks = [t for t in s.split() if t not in STOP]
    return ' '.join(toks)


# Palabras que describen el TIPO de mufa, no su ubicación. Un nombre hecho solo de estas
# palabras ("MF DE CORTE AEREA", "MUFA PEQUEÑA 3M") no identifica una mufa concreta.
TOKENS_GENERICOS = {'MUFA', 'CORTE', 'CONTINUIDAD', '3M', 'AEREA', 'PEQUENA', 'CHATELA', 'FOSC', 'PLANA',
                    'TECHO', 'POSTE', 'PARALELA', 'NUEVA', 'VIEJA', 'INTERNA', 'EXTERNA', 'SANGRIA', 'RVA',
                    'RESERVA', 'ODF', 'A', 'B', 'IDEAY', 'UFINET', 'SIN', 'NOMBRE', 'NODO', 'MINI', 'OVAL',
                    'OVALADA', 'DOMO', 'HORIZONTAL', 'VERTICAL', 'SATURADA', 'SPLITTER', 'SPL'}


def es_generico(norm):
    toks = [t for t in norm.split() if not t.isdigit()]
    return (not toks) or set(toks) <= TOKENS_GENERICOS or len(norm) < 4


def tipo_nodo(nombre):
    n = sin_acentos(nombre).upper()
    if RE_CLIENTE.search(nombre) or RE_ID.search(nombre):
        return 'CLIENTE'          # ubicación de un cliente (con coordenadas), no es un nodo de la red
    if re.match(r'^\s*(RVA|RESERVA)\b', n):
        return 'RESERVA'
    if re.search(r'\bODF\b', n):
        return 'ODF'
    if re.search(r'\bSPL', n):
        return 'SPLITTER'
    if re.search(r'\b(MN|MINI ?NODO)\b', n):
        return 'MINI_NODO'
    if re.search(r'\b(MUFA|MF|MC|FOSC)\b', n):
        return 'MUFA'
    if re.search(r'\bNODO\b|\bDATA\b|\bOLT\b', n):
        return 'NODO'
    return 'OTRO'


def propietario(nombre):
    n = sin_acentos(nombre).upper()
    for p in ('IDEAY', 'UFINET', 'ENATREL', 'UNION FENOSA', 'ENEL', 'NICAPHONE', 'CLARO', 'MOVISTAR', 'ACCEDO'):
        if p in n:
            return 'UNION FENOSA/ENEL' if p in ('UNION FENOSA', 'ENEL') else p
    return None


def dist_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Coordenadas: "12.123°, -86.123°", "12.123,-86.123", "11.848783N 86.194096W", "12.888694°-86.539785°"
RE_COORD = re.compile(
    r'(-?\d{1,2}[.,]\d{3,})\s*°?\s*([NS])?\s*[,;/ ]?\s*(-?\s?\d{1,3}[.,]\d{3,})\s*°?\s*([EWO])?',
    re.I)


def parse_coord(texto):
    """Devuelve (lat, lon, inicio, fin) o None. Valida que caiga en Nicaragua."""
    for m in RE_COORD.finditer(texto):
        a = float(m.group(1).replace(',', '.'))
        b = float(m.group(3).replace(',', '.').replace(' ', ''))
        if (m.group(4) or '').upper() in ('W', 'O') and b > 0:
            b = -b
        if (m.group(2) or '').upper() == 'S' and a > 0:
            a = -a
        cand = [(a, b), (b, a), (a, -abs(b)), (b, -abs(a))]
        for lat, lon in cand:
            if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
                return lat, lon, m.start(), m.end()
    return None


RE_CABLE = re.compile(r'(?<![\w.])(\d{1,3})\s*H(?:ILOS)?\b', re.I)
RE_METROS = re.compile(r'(\d[\d.,]*)\s*(MTS|MTRS|MT|M)\b', re.I)
RE_CLIENTE = re.compile(r'\bC\s?(\d{4,6})\b')
RE_ID = re.compile(r'\bID\s*:?\s*(\d{5,7})\b', re.I)
RE_SOLO_NUM = re.compile(r'^[\d\s/\-–,.]+$')
RE_NOMBRE_NODO = re.compile(r'^\s*(MUFAS?|MF|NODO|MINI\s*NODO|MN|ODF|DATA|FOSC)\b', re.I)
NOTAS_CLAVE = ['SANGRIA', 'VALIDAR', 'NO PROYECTAR', 'ANULADA', 'NO USAR', 'SALIO DE USO', 'CORTADO']


def limpiar_nombre(s):
    s = re.sub(r'\s+', ' ', s.replace('\n', ' ')).strip(' -/,:;')
    return s


def notas_de(texto):
    t = sin_acentos(texto).upper()
    return [n for n in NOTAS_CLAVE if n in t]


# ---------------------------------------------------------------------------
# Conversión con LibreOffice y extracción de textos
# ---------------------------------------------------------------------------
def buscar_soffice(ruta_cfg):
    if ruta_cfg:
        return ruta_cfg
    for c in ('soffice', 'libreoffice',
              r'C:\Program Files\LibreOffice\program\soffice.exe',
              r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'):
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def extension_real(ruta):
    """Algunos .vsdx son en realidad .vsd binarios renombrados."""
    with open(ruta, 'rb') as f:
        cab = f.read(8)
    if cab[:2] == b'PK':
        return '.vsdx'
    if cab[:4] == b'\xd0\xcf\x11\xe0':
        return '.vsd'
    return os.path.splitext(ruta)[1].lower()


def convertir_lote(soffice, pendientes, cache):
    """pendientes: lista de (ruta, md5). Convierte en lotes de 15 a cache/<md5>.odg"""
    for i in range(0, len(pendientes), 15):
        lote = pendientes[i:i + 15]
        tmp = tempfile.mkdtemp()
        perfil = tempfile.mkdtemp()
        entradas = []
        for ruta, h in lote:
            destino = os.path.join(tmp, h + extension_real(ruta))
            shutil.copy(ruta, destino)
            entradas.append(destino)
        cmd = [soffice, '-env:UserInstallation=file:///' + perfil.replace('\\', '/'),
               '--headless', '--convert-to', 'odg', '--outdir', cache] + entradas
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(perfil, ignore_errors=True)
        print('   convertidos %d/%d' % (min(i + 15, len(pendientes)), len(pendientes)), flush=True)


def _cm(v):
    if not v:
        return None
    m = re.match(r'(-?[\d.]+)(cm|mm|in|pt)?', v)
    if not m:
        return None
    return float(m.group(1)) * {'cm': 1, 'mm': .1, 'in': 2.54, 'pt': 2.54 / 72, None: 1}[m.group(2)]


def extraer_textos(odg):
    raiz = etree.fromstring(zipfile.ZipFile(odg).read('content.xml'))
    formas = ('frame', 'custom-shape', 'connector', 'line', 'polyline', 'path', 'rect', 'ellipse', 'polygon')
    salida = []
    for pi, pagina in enumerate(raiz.iter('{%s}page' % NS_D)):
        for el in pagina.iter():
            if etree.QName(el).localname not in formas:
                continue
            if any(etree.QName(c).localname in ('frame', 'custom-shape') for c in el.iterdescendants()):
                continue
            parrafos = [''.join(p.itertext()).strip() for p in el.iter('{%s}p' % NS_T)]
            parrafos = [p for p in parrafos if p]
            if not parrafos:
                continue
            g = lambda a: _cm(el.get('{%s}%s' % (NS_S, a)))
            x, y, w, h = g('x'), g('y'), g('width'), g('height')
            x1, x2, y1, y2 = g('x1'), g('x2'), g('y1'), g('y2')
            if x is None and x1 is not None and x2 is not None and y1 is not None and y2 is not None:
                x, y, w, h = (x1 + x2) / 2, (y1 + y2) / 2, 0, 0
            if x is None or y is None:
                continue
            salida.append({'pagina': pi, 'x': x + (w or 0) / 2, 'y': y + (h or 0) / 2,
                           'texto': '\n'.join(parrafos)})
    return salida


# ---------------------------------------------------------------------------
# Geometría del dibujo: íconos de mufa y líneas de cable
# ---------------------------------------------------------------------------
# En los diagramas las líneas casi nunca están "pegadas" a las mufas, así que la unión se
# deduce por posición: una línea de cable que pasa por (o termina en) el ícono de dos mufas
# las une. Ícono de mufa = moño (dos triángulos enfrentados). Cable = trazo sólido oscuro;
# las líneas punteadas de color son hilos/buffers dentro de la mufa y no cuentan.
TOLERANCIA_LINEA_CM = 0.35
DISTANCIA_ETIQUETA_CM = 12      # etiqueta con coordenadas -> ícono de su mufa
DISTANCIA_SERVICIO_CM = 15      # texto de servicio (SPL ... OLT ...) -> ícono más cercano
NS_ST = 'urn:oasis:names:tc:opendocument:xmlns:style:1.0'
RE_COLOR_OSCURO = re.compile(r'#[0-6][0-9a-f][0-6][0-9a-f][0-6][0-9a-f]$', re.I)
_ARGS_PATH = {'m': 2, 'l': 2, 'h': 1, 'v': 1, 'c': 6, 's': 4, 'q': 4, 't': 2, 'a': 7, 'z': 0}


def _vertices_path(d, escala):
    """Tramos (listas de vértices) de un path SVG; de las curvas solo interesan sus extremos."""
    tramos, actual, cx, cy, cmd = [], [], 0.0, 0.0, None
    toks = re.findall(r'[A-Za-z]|-?\d*\.?\d+(?:[eE]-?\d+)?', d or '')
    i = 0
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in 'zZ':
                if actual:
                    actual.append(actual[0])
                continue
        if cmd is None or cmd.lower() not in _ARGS_PATH:
            break
        n = _ARGS_PATH[cmd.lower()]
        args = [float(t) for t in toks[i:i + n]]
        i += n
        if len(args) < n:
            break
        rel, c = cmd.islower(), cmd.lower()
        if c == 'h':
            cx = cx + args[0] if rel else args[0]
        elif c == 'v':
            cy = cy + args[0] if rel else args[0]
        else:
            cx, cy = (cx + args[-2], cy + args[-1]) if rel else (args[-2], args[-1])
        if c == 'm':
            if len(actual) > 1:
                tramos.append(actual)
            actual = []
            cmd = 'l' if rel else 'L'      # coordenadas siguientes a un moveto son lineto
        actual.append(escala(cx, cy))
    if len(actual) > 1:
        tramos.append(actual)
    return tramos


def extraer_geometria(odg):
    """Íconos de mufa {pagina, x, y, mw, mh} (centro y medio ancho/alto, cm) y líneas de cable
    (pagina, [(x, y), ...])."""
    raiz = etree.fromstring(zipfile.ZipFile(odg).read('content.xml'))
    estilos_cable = set()
    for st in raiz.iter('{%s}style' % NS_ST):
        gp = st.find('{%s}graphic-properties' % NS_ST)
        if gp is None:
            continue
        trazo = gp.get('{%s}stroke' % NS_D)
        color = gp.get('{%s}stroke-color' % NS_S) or ''
        ancho = _cm(gp.get('{%s}stroke-width' % NS_S)) or 0
        if trazo == 'solid' and RE_COLOR_OSCURO.match(color) and ancho >= 0.02:
            estilos_cable.add(st.get('{%s}name' % NS_ST))

    iconos, lineas = [], []
    for pi, pagina in enumerate(raiz.iter('{%s}page' % NS_D)):
        triangulos = set()
        for el in pagina.iter():
            if el.get('{%s}transform' % NS_D):
                continue                    # figuras giradas: sin posición directa
            nombre = etree.QName(el).localname
            g = lambda a: _cm(el.get('{%s}%s' % (NS_S, a)))
            if nombre == 'polygon':
                x, y, w, h = g('x'), g('y'), g('width'), g('height')
                if (len((el.get('{%s}points' % NS_D) or '').split()) == 3 and None not in (x, y, w, h)
                        and 0.3 < w < 3 and 0.3 < h < 3):
                    triangulos.add((round(x, 3), round(y, 3), round(w, 3), round(h, 3)))
                continue
            if el.get('{%s}style-name' % NS_D) not in estilos_cable:
                continue
            if nombre == 'line':
                pts = [(g('x1'), g('y1')), (g('x2'), g('y2'))]
                if all(None not in p for p in pts):
                    lineas.append((pi, pts))
            elif nombre in ('polyline', 'path'):
                x, y, w, h = g('x'), g('y'), g('width'), g('height')
                if None in (x, y, w, h):
                    continue
                try:
                    vx, vy, vw, vh = [float(v) for v in (el.get('{%s}viewBox' % NS_S) or '').split()]
                except ValueError:
                    continue
                escala = (lambda px, py, x=x, y=y, vx=vx, vy=vy, sx=w / vw if vw else 1, sy=h / vh if vh else 1:
                          (x + (px - vx) * sx, y + (py - vy) * sy))
                if nombre == 'polyline':
                    try:
                        pts = [escala(*map(float, p.split(','))) for p in el.get('{%s}points' % NS_D).split()]
                    except (ValueError, TypeError):
                        continue
                    if len(pts) > 1:
                        lineas.append((pi, pts))
                else:
                    lineas.extend((pi, t) for t in _vertices_path(el.get('{%s}d' % NS_S), escala))
        # moño = dos triángulos a la misma altura, uno a continuación del otro
        tri = sorted(triangulos)
        usados = set()
        for a, (x, y, w, h) in enumerate(tri):
            if a in usados:
                continue
            for b in range(a + 1, len(tri)):
                bx, by, bw, bh = tri[b]
                if b not in usados and abs(by - y) < 0.2 and abs(bh - h) < 0.2 and abs(bx - (x + w)) < 0.3:
                    usados.update((a, b))
                    x0, y0, x1, y1 = x, min(y, by), bx + bw, max(y + h, by + bh)
                    iconos.append({'pagina': pi, 'x': (x0 + x1) / 2, 'y': (y0 + y1) / 2,
                                   'mw': (x1 - x0) / 2, 'mh': (y1 - y0) / 2})
                    break
    return iconos, lineas


def _distancia_tramo_icono(p, q, ic):
    """Distancia mínima (cm) del tramo p-q al rectángulo del ícono y posición (0-1) en el tramo."""
    mejor = (float('inf'), 0.0)
    for k in range(21):
        t = k / 20
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        d = math.hypot(max(abs(x - ic['x']) - ic['mw'], 0), max(abs(y - ic['y']) - ic['mh'], 0))
        if d < mejor[0]:
            mejor = (d, t)
    return mejor


def enlaces_por_lineas(iconos, lineas, tol=TOLERANCIA_LINEA_CM):
    """Pares de íconos (índices) consecutivos a lo largo de una misma línea de cable."""
    pares = set()
    for pi, pts in lineas:
        toques, recorrido = [], 0.0
        for p, q in zip(pts, pts[1:]):
            largo = math.hypot(q[0] - p[0], q[1] - p[1])
            x0, x1 = min(p[0], q[0]) - 4, max(p[0], q[0]) + 4
            y0, y1 = min(p[1], q[1]) - 4, max(p[1], q[1]) + 4
            for k, ic in enumerate(iconos):
                if ic['pagina'] != pi or not (x0 <= ic['x'] <= x1 and y0 <= ic['y'] <= y1):
                    continue
                d, t = _distancia_tramo_icono(p, q, ic)
                if d <= tol:
                    toques.append((recorrido + t * largo, k))
            recorrido += largo
        orden = []
        for _, k in sorted(toques):
            if k not in orden:
                orden.append(k)
        pares.update((min(a, b), max(a, b)) for a, b in zip(orden, orden[1:]))
    return pares


def nombrar_iconos(iconos, nodos, max_cm=DISTANCIA_ETIQUETA_CM):
    """{índice de ícono: índice en nodos}: cada etiqueta con coordenadas se asigna a un ícono
    distinto, empezando por los pares más cercanos."""
    pares = sorted((math.hypot(n['x'] - ic['x'], n['y'] - ic['y']), j, k)
                   for j, n in enumerate(nodos) for k, ic in enumerate(iconos) if ic['pagina'] == n['pagina'])
    asignado, tomados = {}, set()
    for d, j, k in pares:
        if d > max_cm:
            break
        if j not in tomados and k not in asignado:
            asignado[k] = j
            tomados.add(j)
    return asignado


def enlaces_entre_nodos(pares, nombre_icono):
    """Une las mufas con nombre; un ícono sin etiqueta en medio se atraviesa (no se puede
    identificar, pero el cable sigue por él)."""
    vecinos = defaultdict(set)
    for a, b in pares:
        vecinos[a].add(b)
        vecinos[b].add(a)
    salida = set()
    for inicio in nombre_icono:
        vistos, pila = {inicio}, [inicio]
        while pila:
            for v in vecinos[pila.pop()]:
                if v in vistos:
                    continue
                vistos.add(v)
                if v in nombre_icono:
                    a, b = nombre_icono[inicio], nombre_icono[v]
                    salida.add((min(a, b), max(a, b)))
                else:
                    pila.append(v)
    return salida


# ---------------------------------------------------------------------------
# Interpretación de un diagrama
# ---------------------------------------------------------------------------
RE_ARCHIVO_RED = re.compile(r'^\s*(RED|MUFAS\s+RED|MUFAS\b|DIAGRAMA|ANILLO|ENLACE|FIBRA OSCURA|FO OSCURA|FUSIONES|MIGRACION|REPCA|ODF)', re.I)


def nombre_desde_archivo(nombre):
    base = os.path.splitext(nombre)[0]
    # quita la numeración inicial: "3 - 1 ", "8 b-", "9 D-", "7.1.2 - ", "2-0-", "4. 2-"
    base = re.sub(r'^\s*(\d+[\s.\-–+]*)+([a-dA-D](?=[\s\-]))?[\s.\-–]*', '', base)
    return limpiar_nombre(base)


def tipo_diagrama(nombre_archivo):
    base = nombre_desde_archivo(nombre_archivo)
    if RE_ARCHIVO_RED.match(base):
        return 'red'
    if len(re.findall(r'\b(MUFA|MF)\b', base, re.I)) >= 2:
        return 'red'
    return 'mufa'


def clasificar(texto):
    plano = texto.replace('\n', ' / ')
    if parse_coord(plano):
        return 'nodo'
    if RE_SOLO_NUM.match(plano):
        return 'numeracion'
    if RE_CLIENTE.search(plano) or RE_ID.search(plano):
        return 'cliente'
    if RE_CABLE.search(plano) and len(plano) < 40:
        return 'cable'
    if re.search(r'\bSPL', plano, re.I):
        return 'splitter'
    if RE_NOMBRE_NODO.match(plano):
        return 'nodo_sin_coord'
    return 'otro'


def interpretar(textos, nombre_archivo):
    """Devuelve dict con nodos, cables, clientes, principal."""
    nodos, cables, clientes, sin_coord = [], [], [], []
    for t in textos:
        t['clase'] = clasificar(t['texto'])
        plano = t['texto'].replace('\n', ' / ')
        if t['clase'] == 'nodo':
            coord = parse_coord(plano)
            assert coord is not None   # clasificar() devolvió 'nodo' porque encontró la coordenada
            lat, lon, i, j = coord
            nombre = limpiar_nombre(plano[:i]) or limpiar_nombre(plano[j:])
            nombre = re.sub(r'\b(SANGRI.A|VALIDAR.*|No proyectar.*)$', '', nombre, flags=re.I).strip(' /-')
            nodos.append({'nombre': nombre, 'lat': lat, 'lon': lon, 'x': t['x'], 'y': t['y'],
                          'pagina': t['pagina'], 'texto': t['texto'], 'notas': notas_de(plano)})
        elif t['clase'] == 'cable':
            mh = RE_CABLE.search(plano)
            assert mh is not None      # clasificar() devolvió 'cable' porque RE_CABLE coincidió
            mm = RE_METROS.search(plano)
            metros = None
            if mm:
                try:
                    metros = float(mm.group(1).replace(',', ''))
                except ValueError:
                    metros = None
            cables.append({'hilos': int(mh.group(1)), 'metros': metros, 'x': t['x'], 'y': t['y'],
                           'pagina': t['pagina'], 'texto': t['texto']})
        elif t['clase'] in ('cliente', 'splitter'):
            for linea in re.split(r'\n|(?=\b\d+[.\-]\s*C\d{4,6})', t['texto']):
                linea = limpiar_nombre(linea)
                if not linea:
                    continue
                mc, mi = RE_CLIENTE.search(linea), RE_ID.search(linea)
                tipo = 'splitter' if re.search(r'\bSPL', linea, re.I) else ('cliente' if (mc or mi) else 'otro')
                clientes.append({'tipo': tipo, 'codigo': ('C' + mc.group(1)) if mc else None,
                                 'id': ('ID' + mi.group(1)) if mi else None, 'texto': linea,
                                 'x': t['x'], 'y': t['y'], 'pagina': t['pagina']})
        elif t['clase'] == 'nodo_sin_coord':
            sin_coord.append({'nombre': limpiar_nombre(plano), 'x': t['x'], 'y': t['y'],
                              'pagina': t['pagina'], 'texto': t['texto']})

    # Nodos con coordenadas pero sin nombre: toma el texto de nodo más cercano sin coordenadas
    for n in nodos:
        if not n['nombre'] or RE_SOLO_NUM.match(n['nombre']):
            cerca = [s for s in sin_coord if s['pagina'] == n['pagina']]
            cerca.sort(key=lambda s: math.hypot(s['x'] - n['x'], s['y'] - n['y']))
            if cerca and math.hypot(cerca[0]['x'] - n['x'], cerca[0]['y'] - n['y']) < 2.5:
                n['nombre'] = cerca[0]['nombre']
                cerca[0]['usado'] = True
            else:
                n['nombre'] = 'SIN NOMBRE (%.5f, %.5f)' % (n['lat'], n['lon'])

    tipo = tipo_diagrama(nombre_archivo)
    # Un diagrama "de mufa" con muchos nodos georreferenciados es en realidad la subred que
    # sale de esa mufa: no se une la mufa con todos, se arma como diagrama de red.
    if tipo == 'mufa' and len(nodos) > 6:
        tipo = 'subred'
    principal = None
    if tipo in ('mufa', 'subred'):
        esperado = normalizar(nombre_desde_archivo(nombre_archivo))
        tok_esp = set(esperado.split())
        mejor, puntaje = None, 0.0
        for grupo, umbral in ((sin_coord, 0.34), (nodos, 0.6)):   # primero el título del diagrama
            for s in grupo:
                tok = set(normalizar(s['nombre']).split()) - {'MUFA'}
                te = tok_esp - {'MUFA'}
                if not tok or not te:
                    continue
                p = len(tok & te) / max(len(tok | te), 1)
                if p >= umbral and p > puntaje:
                    mejor, puntaje = s, p
            if mejor is not None:
                break
        if mejor is not None:
            principal = dict(mejor)
        else:
            principal = {'nombre': nombre_desde_archivo(nombre_archivo), 'x': None, 'y': None,
                         'pagina': 0, 'texto': nombre_archivo}
    return {'tipo': tipo, 'nodos': nodos, 'cables': cables, 'clientes': clientes,
            'sin_coord': [s for s in sin_coord if not s.get('usado')], 'principal': principal}


# ---------------------------------------------------------------------------
# Registro de nodos (une apariciones entre archivos)
# ---------------------------------------------------------------------------
class Registro:
    def __init__(self):
        self.nodos = []          # dicts
        self.por_nombre = defaultdict(list)

    def obtener(self, nombre, lat=None, lon=None, zona=None):
        norm = normalizar(nombre)
        generico = es_generico(norm)
        candidatos = []
        if not generico:
            for idx in self.por_nombre.get(norm, []):
                n = self.nodos[idx]
                if lat is None or n['lat_ref'] is None:
                    candidatos.append((0, idx))
                else:
                    d = dist_m(lat, lon, n['lat_ref'], n['lon_ref'])
                    if d <= 500:
                        candidatos.append((d, idx))
        elif lat is not None:
            for idx in self.por_nombre.get(norm, []):
                n = self.nodos[idx]
                if n['lat_ref'] is not None and dist_m(lat, lon, n['lat_ref'], n['lon_ref']) <= 15:
                    candidatos.append((0, idx))
        if candidatos:
            idx = sorted(candidatos)[0][1]
        else:
            idx = len(self.nodos)
            self.nodos.append({'nombre': nombre, 'norm': norm, 'tipo': tipo_nodo(nombre),
                               'propietario': propietario(nombre), 'coords': [], 'lat_ref': None,
                               'lon_ref': None, 'zonas': Counter(), 'notas': set(), 'apariciones': []})
            self.por_nombre[norm].append(idx)
        n = self.nodos[idx]
        if lat is not None and n['lat_ref'] is None:
            n['lat_ref'], n['lon_ref'] = lat, lon
        if zona:
            n['zonas'][zona] += 1
        return idx


# ---------------------------------------------------------------------------
# Excel de anillos
# ---------------------------------------------------------------------------
def num_o_none(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace('°', '').strip().replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def leer_excel_anillos(ruta):
    import openpyxl
    wb = openpyxl.load_workbook(ruta, data_only=True)
    tramos = []
    for ws in wb:
        enlace_actual = None
        en_bloque = False
        for fila in ws.iter_rows(values_only=True):
            celdas = list(fila) + [None] * 11
            if isinstance(celdas[0], str) and celdas[0].strip().upper() == 'EN MUFA':
                en_bloque = True
                continue
            if not en_bloque or not celdas[0] or celdas[0] == 0:
                continue
            lat, lon = num_o_none(celdas[1]), num_o_none(celdas[2])
            if lat is not None and lon is not None and not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                lat = lon = None
            enlace_actual = celdas[8] or enlace_actual
            tramos.append({'hoja': ws.title, 'enlace': enlace_actual, 'orden': celdas[3],
                           'en_mufa': limpiar_nombre(str(celdas[0])), 'lat': lat, 'lon': lon,
                           'de_mufa': celdas[4], 'hilo_entrante': celdas[5], 'hacia_mufa': celdas[6],
                           'hilo_saliente': celdas[7], 'nota': celdas[9]})
    return tramos


# ---------------------------------------------------------------------------
# Proceso principal
# ---------------------------------------------------------------------------
def pg_del_env():
    """Cadena de conexión a la base Visio (VISIO_DB_* del .env del proyecto), o None si no está configurada."""
    try:
        from urllib.parse import quote
        from dotenv import dotenv_values
        v = dotenv_values(os.path.join(os.path.dirname(AQUI), '.env'))
        if not v.get('VISIO_DB_NAME'):
            return None
        return 'postgresql://%s:%s@%s:%s/%s' % (quote(v.get('VISIO_DB_USER') or 'postgres', safe=''), quote(v.get('VISIO_DB_PASSWORD') or '', safe=''),
                                                v.get('VISIO_DB_HOST') or 'localhost', v.get('VISIO_DB_PORT') or '5432', v['VISIO_DB_NAME'])
    except Exception:
        return None


def subir_diagramas(cache):
    """Los .odg convertidos también quedan en la base (almacén de archivos), para que el visor los encuentre sin esta carpeta."""
    try:
        sys.path.insert(0, os.path.dirname(AQUI))
        from visor_rutas import almacen_archivos
        r = almacen_archivos.subir_carpeta('odg', cache, patron='*.odg')
        print('Diagramas en la base: %d subidos, %d ya estaban, %d fallidos' % (r['subidos'], r['iguales'], r['fallidos']))
    except Exception as exc:
        print('Aviso: no se pudieron guardar los diagramas en la base (%s)' % exc)


def main():
    ap = argparse.ArgumentParser(description='Importa diagramas Visio y Excel de anillos a SQLite')
    ap.add_argument('--origen', required=True, help='Carpeta raíz de los diagramas')
    ap.add_argument('--db', default=None,
                    help='Archivo SQLite de trabajo. Si se omite y hay PostgreSQL, se usa un archivo temporal que se borra al publicar '
                         '(la base de verdad es PostgreSQL); sin PostgreSQL, red_fibra.db')
    ap.add_argument('--cache', default=None, help='Carpeta de caché de conversiones (por defecto datos/cache/odg)')
    ap.add_argument('--soffice', default=None, help='Ruta a soffice(.exe) de LibreOffice')
    ap.add_argument('--pg', default=os.environ.get('RED_FIBRA_PG'),
                    help='Si se indica (o existe RED_FIBRA_PG), al terminar publica la base en PostgreSQL. '
                         'Ej.: postgresql://usuario:clave@servidor:5432/ideay')
    args = ap.parse_args()
    if not args.pg:
        args.pg = pg_del_env()
    temporal = None
    if args.db is None:
        if args.pg:
            temporal = tempfile.mkdtemp(prefix='red_fibra_')
            args.db = os.path.join(temporal, 'red_fibra.db')
        else:
            args.db = 'red_fibra.db'

    origen = os.path.abspath(args.origen)
    cache = args.cache or os.path.join(os.path.dirname(AQUI), 'datos', 'cache', 'odg')
    os.makedirs(cache, exist_ok=True)

    # 1. Inventario
    print('1/5 Inventario de archivos...')
    archivos = []
    for raiz, _, nombres in os.walk(origen):
        for n in sorted(nombres):
            ext = os.path.splitext(n)[1].lower()
            if n.startswith('~$') or ext not in ('.vsd', '.vsdx', '.xlsx'):
                continue
            ruta = os.path.join(raiz, n)
            archivos.append({'ruta': ruta, 'rel': os.path.relpath(ruta, origen).replace('\\', '/'),
                             'nombre': n, 'carpeta': os.path.basename(raiz), 'formato': ext[1:],
                             'tam': os.path.getsize(ruta), 'md5': md5_archivo(ruta),
                             'mod': dt.datetime.fromtimestamp(os.path.getmtime(ruta)).isoformat(timespec='seconds')})
    print('   %d archivos (%d Visio, %d Excel)' % (len(archivos),
          sum(a['formato'] != 'xlsx' for a in archivos), sum(a['formato'] == 'xlsx' for a in archivos)))

    # 2. Conversión (solo lo que no está en caché)
    vistos = {}
    pendientes = []
    for a in archivos:
        if a['formato'] == 'xlsx' or a['md5'] in vistos:
            continue
        vistos[a['md5']] = a
        if a['formato'] == 'vsdx' and not zipfile.is_zipfile(a['ruta']):
            continue   # .vsdx dañado: se registra como error más adelante, no se intenta convertir
        if not os.path.exists(os.path.join(cache, a['md5'] + '.odg')):
            pendientes.append((a['ruta'], a['md5']))
    print('2/5 Conversión Visio -> ODG: %d pendientes (%d en caché)' % (len(pendientes), len(vistos) - len(pendientes)))
    if pendientes:
        soffice = buscar_soffice(args.soffice)
        if soffice:
            convertir_lote(soffice, pendientes, cache)
        else:
            print('   AVISO: no se encontró LibreOffice (use --soffice). Los %d archivos pendientes '
                  'quedarán con error en esta carga.' % len(pendientes))

    # 3. Base nueva
    print('3/5 Creando base %s ...' % args.db)
    if os.path.exists(args.db):
        os.remove(args.db)
    con = sqlite3.connect(args.db)
    with open(os.path.join(AQUI, 'schema.sql'), encoding='utf-8') as f:
        con.executescript(f.read())
    cur = con.cursor()
    cur.execute('INSERT INTO importaciones(fecha, carpeta_origen) VALUES (?,?)',
                (dt.datetime.now().isoformat(timespec='seconds'), origen))
    imp_id = cur.lastrowid

    reg = Registro()
    enlaces, servicios, apariciones, tramos_excel = [], [], [], []
    md5_a_id = {}
    stats = Counter()

    print('4/5 Leyendo diagramas...')
    for a in archivos:
        dup = md5_a_id.get(a['md5'])
        tipo = 'excel_anillos' if a['formato'] == 'xlsx' else tipo_diagrama(a['nombre'])
        cur.execute('''INSERT INTO archivos(importacion_id, ruta_relativa, carpeta, nombre, formato, tipo_diagrama,
                       tamano_bytes, md5, modificado, estado, duplicado_de) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (imp_id, a['rel'], a['carpeta'], a['nombre'], a['formato'], tipo, a['tam'], a['md5'],
                     a['mod'], 'duplicado' if dup else 'pendiente', dup))
        a['id'] = cur.lastrowid
        if dup:
            stats['duplicados'] += 1
            continue
        md5_a_id[a['md5']] = a['id']
        zona = a['carpeta']
        try:
            if a['formato'] == 'xlsx':
                tramos = leer_excel_anillos(a['ruta'])
                for t in tramos:
                    t['archivo_id'] = a['id']
                    t['nodo'] = reg.obtener(t['en_mufa'], t['lat'], t['lon'], zona='ANILLOS')
                    apariciones.append((t['nodo'], a['id'], 'excel', t['en_mufa'], t['lat'], t['lon'], None))
                tramos_excel.extend(tramos)
                # enlaces consecutivos dentro de cada enlace lógico
                for t1, t2 in zip(tramos, tramos[1:]):
                    if t1['hoja'] == t2['hoja'] and t1['enlace'] == t2['enlace'] and t1['nodo'] != t2['nodo']:
                        enlaces.append({'a': t1['nodo'], 'b': t2['nodo'], 'hilos': None, 'metros': None,
                                        'usados': t1['hilo_saliente'], 'logico': t1['enlace'],
                                        'fuente': 'excel', 'confianza': 'alta', 'archivo': a['id'],
                                        'texto': '%s -> %s' % (t1['en_mufa'], t2['en_mufa'])})
                cur.execute('UPDATE archivos SET estado=?, nodos_detectados=? WHERE id=?', ('ok', len(tramos), a['id']))
                stats['ok'] += 1
                continue

            odg = os.path.join(cache, a['md5'] + '.odg')
            if not os.path.exists(odg):
                if a['formato'] == 'vsdx' and not zipfile.is_zipfile(a['ruta']):
                    raise RuntimeError('Archivo dañado o incompleto (el .vsdx no es un ZIP válido). Abrirlo en Visio y volver a guardarlo.')
                raise RuntimeError('LibreOffice no pudo convertir el archivo')
            textos = extraer_textos(odg)
            info = interpretar(textos, a['nombre'])
            cur.executemany('INSERT INTO textos_crudos(archivo_id,pagina,x_cm,y_cm,texto,clasificacion) VALUES (?,?,?,?,?,?)',
                            [(a['id'], t['pagina'], round(t['x'], 2), round(t['y'], 2), t['texto'], t['clase']) for t in textos])

            idx_nodos = []
            for n in info['nodos']:
                i = reg.obtener(n['nombre'], n['lat'], n['lon'], zona)
                reg.nodos[i]['coords'].append((n['lat'], n['lon'], 'visio'))
                reg.nodos[i]['notas'].update(n['notas'])
                apariciones.append((i, a['id'], 'vecino' if info['tipo'] == 'mufa' else 'red',
                                    n['nombre'], n['lat'], n['lon'], n['texto']))
                idx_nodos.append((i, n))

            principal_idx = None
            if info['principal']:
                p = info['principal']
                if p.get('lat') is not None:
                    principal_idx = reg.obtener(p['nombre'], p['lat'], p['lon'], zona)
                else:
                    principal_idx = reg.obtener(p['nombre'], None, None, zona)
                apariciones.append((principal_idx, a['id'], 'principal', p['nombre'], p.get('lat'), p.get('lon'), p['texto']))

            # Enlaces
            if info['tipo'] == 'mufa' and principal_idx is not None:
                for i, n in idx_nodos:
                    if i == principal_idx:
                        continue
                    cab = [c for c in info['cables'] if c['pagina'] == n['pagina']]
                    cab.sort(key=lambda c: math.hypot(c['x'] - n['x'], c['y'] - n['y']))
                    c = cab[0] if cab and math.hypot(cab[0]['x'] - n['x'], cab[0]['y'] - n['y']) < 12 else None
                    enlaces.append({'a': principal_idx, 'b': i, 'hilos': c['hilos'] if c else None,
                                    'metros': c['metros'] if c else None, 'usados': None, 'logico': None,
                                    'fuente': 'visio_mufa', 'confianza': 'media', 'archivo': a['id'],
                                    'texto': c['texto'] if c else None})
            else:
                # Red: cada etiqueta de cable une los dos nodos entre los que está dibujada
                for c in info['cables']:
                    cand = [(i, n) for i, n in idx_nodos if n['pagina'] == c['pagina']]
                    mejor = None
                    for k1 in range(len(cand)):
                        for k2 in range(k1 + 1, len(cand)):
                            (i1, n1), (i2, n2) = cand[k1], cand[k2]
                            if i1 == i2:
                                continue
                            d12 = math.hypot(n1['x'] - n2['x'], n1['y'] - n2['y'])
                            d1 = math.hypot(n1['x'] - c['x'], n1['y'] - c['y'])
                            d2 = math.hypot(n2['x'] - c['x'], n2['y'] - c['y'])
                            desvio = d1 + d2 - d12
                            if desvio < 0.25 * d12 + 1.0 and (mejor is None or desvio < mejor[0]):
                                mejor = (desvio, i1, i2)
                    if mejor:
                        enlaces.append({'a': mejor[1], 'b': mejor[2], 'hilos': c['hilos'], 'metros': c['metros'],
                                        'usados': None, 'logico': None, 'fuente': 'visio_red',
                                        'confianza': 'baja', 'archivo': a['id'], 'texto': c['texto']})
                # y cada línea de cable dibujada une las mufas por las que pasa
                iconos, lineas = extraer_geometria(odg)
                icono_nodo = nombrar_iconos(iconos, info['nodos'])
                for j1, j2 in enlaces_entre_nodos(enlaces_por_lineas(iconos, lineas), icono_nodo):
                    if idx_nodos[j1][0] != idx_nodos[j2][0]:
                        enlaces.append({'a': idx_nodos[j1][0], 'b': idx_nodos[j2][0], 'hilos': None,
                                        'metros': None, 'usados': None, 'logico': None, 'fuente': 'visio_linea',
                                        'confianza': 'media', 'archivo': a['id'], 'texto': None})

            # Servicios: en diagramas de mufa van a la mufa del diagrama; en subred/red, a la
            # mufa cuyo ícono está más cerca del texto (o a la etiqueta de nodo más cercana).
            for s in info['clientes']:
                destino = principal_idx
                if destino is None or info['tipo'] in ('red', 'subred'):
                    destino = None
                    if info['tipo'] != 'mufa':
                        cerca = [(math.hypot(ic['x'] - s['x'], ic['y'] - s['y']), k)
                                 for k, ic in enumerate(iconos) if ic['pagina'] == s['pagina']]
                        if cerca and min(cerca)[0] <= DISTANCIA_SERVICIO_CM and min(cerca)[1] in icono_nodo:
                            destino = idx_nodos[icono_nodo[min(cerca)[1]]][0]
                    if destino is None:
                        cand = [(math.hypot(n['x'] - s['x'], n['y'] - s['y']), i) for i, n in idx_nodos if n['pagina'] == s['pagina']]
                        destino = min(cand)[1] if cand else principal_idx
                servicios.append((destino, a['id'], s['tipo'], s['codigo'], s['id'], s['texto']))

            cur.execute('UPDATE archivos SET estado=?, textos=?, nodos_detectados=?, tipo_diagrama=? WHERE id=?',
                        ('ok', len(textos), len(info['nodos']), info['tipo'], a['id']))
            stats['ok'] += 1
        except Exception as e:  # el archivo queda registrado con su error
            cur.execute('UPDATE archivos SET estado=?, error=? WHERE id=?', ('error', str(e)[:500], a['id']))
            stats['error'] += 1

    # 5. Consolidar nodos
    print('5/5 Consolidando nodos y enlaces...')
    for t in tramos_excel:
        if t['lat'] is not None:
            reg.nodos[t['nodo']]['coords'].append((t['lat'], t['lon'], 'excel'))
        if t['nota']:
            reg.nodos[t['nodo']]['notas'].add(str(t['nota']).upper())

    # coordenadas finales (mediana) y dispersión
    for n in reg.nodos:
        n['lat'] = n['lon'] = n['fuente'] = n['disp'] = None
        n['revision'] = []
        if n['coords']:
            lats = sorted(c[0] for c in n['coords'])
            lons = sorted(c[1] for c in n['coords'])
            n['lat'], n['lon'] = lats[len(lats) // 2], lons[len(lons) // 2]
            n['fuente'] = '+'.join(sorted({c[2] for c in n['coords']}))
            n['disp'] = max(dist_m(n['lat'], n['lon'], c[0], c[1]) for c in n['coords'])
            if n['disp'] > 150:
                n['revision'].append('coordenadas distintas entre archivos (%.0f m)' % n['disp'])

    # nodos sin coordenadas: estimar con el promedio de sus vecinos
    # Validación geográfica de enlaces: la longitud escrita en la etiqueta del cable debe
    # ser compatible con la distancia en línea recta entre los dos nodos.
    #  - visio_red: la unión se deduce por la posición de la etiqueta en el dibujo; si no se
    #    puede validar o no cuadra, se descarta (es la parte menos confiable).
    #  - visio_mufa: el vecino sí es correcto (aparece en el diagrama de esa mufa); si la
    #    longitud no cuadra, solo se borra la longitud.
    validos = []
    for e in enlaces:
        na, nb = reg.nodos[e['a']], reg.nodos[e['b']]
        d = None
        if na['lat'] is not None and nb['lat'] is not None:
            d = dist_m(na['lat'], na['lon'], nb['lat'], nb['lon'])
        coherente = d is not None and e['metros'] and d <= 1.3 * e['metros'] + 150
        if e['fuente'] == 'visio_red':
            if coherente:
                e['confianza'] = 'media'
                validos.append(e)
            else:
                stats['enlaces_red_descartados'] += 1
            continue
        if e['fuente'] == 'visio_mufa' and e['metros'] and d is not None and not coherente:
            e['texto'] = (e['texto'] or '') + ' [longitud descartada: no coincide con %.0f m en línea recta]' % d
            e['metros'] = None
        validos.append(e)
    enlaces = validos

    vecinos = defaultdict(set)
    for e in enlaces:
        vecinos[e['a']].add(e['b'])
        vecinos[e['b']].add(e['a'])
    for i, n in enumerate(reg.nodos):
        if n['lat'] is None:
            pts = [(reg.nodos[v]['lat'], reg.nodos[v]['lon']) for v in vecinos[i]
                   if reg.nodos[v]['lat'] is not None and reg.nodos[v]['fuente'] != 'estimada_vecinos']
            if pts:
                n['lat'] = sum(p[0] for p in pts) / len(pts)
                n['lon'] = sum(p[1] for p in pts) / len(pts)
                n['fuente'] = 'estimada_vecinos'
                n['revision'].append('coordenada estimada con %d vecino(s)' % len(pts))
            else:
                n['revision'].append('sin coordenadas')

    id_bd = {}
    for i, n in enumerate(reg.nodos):
        zona = n['zonas'].most_common(1)[0][0] if n['zonas'] else None
        cur.execute('''INSERT INTO nodos(nombre, nombre_normalizado, tipo, propietario, lat, lon, fuente_coord,
                       coord_dispersion_m, zona, notas, requiere_revision, motivo_revision)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (n['nombre'], n['norm'], n['tipo'], n['propietario'],
                     round(n['lat'], 7) if n['lat'] is not None else None,
                     round(n['lon'], 7) if n['lon'] is not None else None,
                     n['fuente'], round(n['disp'], 1) if n['disp'] is not None else None, zona,
                     ', '.join(sorted(n['notas'])) or None, 1 if n['revision'] else 0,
                     '; '.join(n['revision']) or None))
        id_bd[i] = cur.lastrowid

    cur.executemany('''INSERT INTO nodo_apariciones(nodo_id, archivo_id, rol, nombre_original, lat, lon, texto_original)
                       VALUES (?,?,?,?,?,?,?)''', [(id_bd[x[0]],) + tuple(x[1:]) for x in apariciones])
    cur.execute('''UPDATE nodos SET num_apariciones =
                   (SELECT COUNT(DISTINCT archivo_id) FROM nodo_apariciones a WHERE a.nodo_id = nodos.id)''')

    # enlaces: un registro por par de nodos y fuente (se conserva el más informativo)
    unicos = {}
    for e in enlaces:
        if e['a'] == e['b']:
            continue
        k = (min(e['a'], e['b']), max(e['a'], e['b']), e['fuente'])
        prev = unicos.get(k)
        if prev is None or (prev['hilos'] is None and e['hilos'] is not None):
            unicos[k] = e
    cur.executemany('''INSERT INTO enlaces(nodo_a_id, nodo_b_id, hilos_cable, longitud_m, hilos_usados, enlace_logico,
                       fuente, confianza, archivo_id, texto_original) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    [(id_bd[e['a']], id_bd[e['b']], e['hilos'], e['metros'],
                      str(e['usados']) if e['usados'] else None, e['logico'], e['fuente'], e['confianza'],
                      e['archivo'], e['texto']) for e in unicos.values()])
    cur.executemany('''INSERT INTO servicios(nodo_id, archivo_id, tipo, codigo_cliente, id_servicio, descripcion)
                       VALUES (?,?,?,?,?,?)''',
                    [(id_bd[s[0]] if s[0] is not None else None,) + tuple(s[1:]) for s in servicios])
    cur.executemany('''INSERT INTO anillo_tramos(archivo_id, hoja, enlace, orden, nodo_id, en_mufa, lat, lon, de_mufa,
                       hilo_entrante, hacia_mufa, hilo_saliente, nota) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    [(t['archivo_id'], t['hoja'], t['enlace'], t['orden'], id_bd[t['nodo']], t['en_mufa'], t['lat'],
                      t['lon'], str(t['de_mufa']) if t['de_mufa'] else None,
                      str(t['hilo_entrante']) if t['hilo_entrante'] else None,
                      str(t['hacia_mufa']) if t['hacia_mufa'] else None,
                      str(t['hilo_saliente']) if t['hilo_saliente'] else None,
                      str(t['nota']) if t['nota'] else None) for t in tramos_excel])

    nota = ('%d enlaces de diagramas de red descartados por no coincidir con la geografía; '
            '%d enlaces deducidos de las líneas de cable dibujadas'
            % (stats['enlaces_red_descartados'], sum(e['fuente'] == 'visio_linea' for e in unicos.values())))
    cur.execute('''UPDATE importaciones SET archivos_total=?, archivos_ok=?, archivos_error=?, archivos_duplicados=?,
                   nodos=(SELECT COUNT(*) FROM nodos), enlaces=(SELECT COUNT(*) FROM enlaces),
                   servicios=(SELECT COUNT(*) FROM servicios), notas=? WHERE id=?''',
                (len(archivos), stats['ok'], stats['error'], stats['duplicados'], nota, imp_id))
    con.commit()

    r = cur.execute('SELECT archivos_total, archivos_ok, archivos_error, archivos_duplicados, nodos, enlaces, servicios '
                    'FROM importaciones WHERE id=?', (imp_id,)).fetchone()
    con_coord = cur.execute("SELECT COUNT(*) FROM nodos WHERE lat IS NOT NULL AND fuente_coord!='estimada_vecinos'").fetchone()[0]
    print('\nListo: %d archivos (%d ok, %d con error, %d duplicados)' % r[:4])
    print('       %d nodos (%d con coordenadas reales), %d enlaces, %d servicios' % (r[4], con_coord, r[5], r[6]))
    print('       ' + nota)
    con.close()

    if args.pg:
        print('\nPublicando en PostgreSQL...')
        from publicar_postgres import publicar
        publicar(args.db, args.pg)


if __name__ == '__main__':
    main()
