"""Capas del KMZ de la red para el panel "Lugares" del visor (como en Google Earth).

Convierte el KMZ (KMZ_PATH del .env: el archivo, o la carpeta donde está) en una caché que el
visor dibuja sin internet, en visor_rutas/datos_kmz/:

  arbol.json            carpetas (id estable, nombre, ruta, hijos, conteos, geometría, bbox,
                        estilo para la leyenda, troncal, familia...) + md5 del KMZ
  capas/<id>.geojson    los elementos directos de cada carpeta, con su estilo resuelto
  indice.json           nombre y texto de la descripción de cada elemento, por carpeta (buscador)
  iconos/               íconos usados (files/ del KMZ, pushpins/shapes de Google descargados una
                        vez y teñidos con el color del estilo, o SVG equivalentes sin internet)
  fotos/                imágenes de files/ referenciadas en las descripciones

Solo sirve para VER la red: el cálculo de ruta y presupuesto sigue usando PostGIS
(red_lineas / red_puntos), que este módulo no toca. Se regenera solo si cambia el md5 del KMZ.

    .\\.venv\\Scripts\\python.exe -m visor_rutas.kmz_capas [--kmz "<ruta>"] [--forzar]
"""
import argparse
import hashlib
import html
import io
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from lxml import etree
from lxml import html as lhtml

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_DATOS = Path(__file__).resolve().parent / "datos_kmz"
VERSION_FORMATO = 2
Progreso = Callable[[float, str], None]

# High-contrast palette for the "distinctive colours" of trunk lines (stable by name).
PALETA_TRONCALES = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6",
    "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#ff69b4", "#00ced1", "#ff4500", "#7fff00", "#1e90ff",
]
_TRONCAL = re.compile(r"TRUNK|TRONCAL|PRINCIPALES|ENLACE\s+REDUNDANTE", re.I)
_ENCENDIDA = re.compile(r"^(TRUNK\s+GPON|TRUNK\s+METRO|PRINCIPALES|TRONCAL.*)$", re.I)
_POSTES = re.compile(r"POSTE|POZO", re.I)
_NODOS = re.compile(r"\bNODOS?\b", re.I)

# Google Earth icons: base colour of the image (for the SVG fallback) and anchor.
_ICONOS_GOOGLE = {
    "ylw-pushpin": ("pin", "#f7d117"), "blue-pushpin": ("pin", "#2f6bff"), "red-pushpin": ("pin", "#e53935"),
    "grn-pushpin": ("pin", "#2e9c3a"), "ltblu-pushpin": ("pin", "#6fc3ff"), "wht-pushpin": ("pin", "#ffffff"),
    "pink-pushpin": ("pin", "#ff77c8"), "purple-pushpin": ("pin", "#8e44ad"),
    "homegardenbusiness": ("casa", "#ffffff"), "shaded_dot": ("circulo", "#d9d9d9"),
    "placemark_circle": ("circulo", "#ffffff"), "placemark_circle_highlight": ("circulo", "#ffffff"),
    "placemark_square": ("cuadrado", "#ffffff"), "placemark_square_highlight": ("cuadrado", "#ffffff"),
    "flag": ("bandera", "#ff4040"),
}
_CIRCULO_POR_DEFECTO = {"shaded_dot": "#d9d9d9", "flag": "#ff4040"}
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

_lock = threading.Lock()
_progreso: dict[str, Any] = {"activo": False, "fraccion": 0.0, "texto": ""}


class KmzNoEncontrado(FileNotFoundError):
    """No KMZ at KMZ_PATH (and no cache to fall back on)."""


# --------------------------------------------------------------------------- utilidades

def _local(e: Any) -> str:
    """Local tag name; also for undeclared prefixes such as 'gpstestkml:accuracy'."""
    return e.tag.rsplit("}", 1)[-1].split(":")[-1] if isinstance(e.tag, str) else ""


def _hijo(e: Any, nombre: str) -> Any:
    return next((c for c in e if _local(c) == nombre), None)


def _texto(e: Any, nombre: str) -> str:
    c = _hijo(e, nombre) if e is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def color_kml(valor: str | None, defecto: str = "ffffffff") -> tuple[str, float]:
    """KML 'aabbggrr' -> ('#rrggbb', opacity 0..1)."""
    v = re.sub(r"[^0-9a-fA-F]", "", valor or "")
    if len(v) != 8:
        v = defecto
    a, b, g, r = v[0:2], v[2:4], v[4:6], v[6:8]
    return f"#{r}{g}{b}".lower(), round(int(a, 16) / 255, 3)


def color_distintivo(nombre: str) -> str:
    """Palette colour for a trunk line: the same name always gives the same colour."""
    clave = " ".join(str(nombre or "").upper().split())
    return PALETA_TRONCALES[int(hashlib.md5(clave.encode("utf-8")).hexdigest(), 16) % len(PALETA_TRONCALES)]


def id_carpeta(ruta: list[str]) -> str:
    """Stable id: hash of the folder path (names from the Document down)."""
    return hashlib.sha1("/".join(ruta).encode("utf-8")).hexdigest()[:12]


def md5_archivo(ruta: Path) -> str:
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def ruta_kmz(valor: str | os.PathLike | None = None) -> Path:
    """The KMZ: KMZ_PATH (a .kmz file, or a folder: its newest .kmz), default red_kmz/."""
    texto = str(valor or os.getenv("KMZ_PATH") or "red_kmz").strip().strip('"')
    ruta = Path(texto)
    if not ruta.is_absolute():
        ruta = RAIZ / ruta
    if ruta.is_dir():
        candidatos = sorted(ruta.glob("*.kmz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            raise KmzNoEncontrado(f"No hay ningún .kmz en {ruta}")
        return candidatos[0]
    if not ruta.is_file():
        raise KmzNoEncontrado(f"No se encontró el KMZ: {ruta}")
    return ruta


def _longitud_km(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, a)))
    return total


# --------------------------------------------------------------------------- descripciones

_ETIQUETAS_OK = {"b", "i", "u", "strong", "em", "br", "p", "div", "span", "a", "ul", "ol", "li",
                 "table", "tbody", "thead", "tr", "td", "th", "font", "h1", "h2", "h3", "h4", "hr", "small"}
_ETIQUETAS_FUERA = {"script", "style", "iframe", "object", "embed", "form", "input", "button", "link",
                    "meta", "svg", "math", "noscript", "template", "textarea", "select"}
_LINEA_EXLYO = re.compile(r"^\s*com_exlyo\w*\s*:", re.I)
_EXLYO_EN_LINEA = re.compile(r"com_exlyo\w*\s*:\s*", re.I)
_LINEA_VACIA = re.compile(r"^\s*[\w áéíóúñÁÉÍÓÚÑ.-]{1,40}:\s*$")
_BR = re.compile(r"<br\s*/?>|\r?\n", re.I)


def limpiar_descripcion(texto: str | None) -> tuple[str, list[str]]:
    """Safe HTML of a KML description and the files/ images it shows.

    Drops scripts and event handlers, the leftovers of the "com.exlyo.mapmarker" app and
    'key:' lines with no value; keeps text, line breaks and http(s)/mailto links. Images are
    returned apart (the popup shows them as thumbnails).
    """
    if not texto or not texto.strip():
        return "", []
    lineas = []
    for linea in _BR.split(texto):
        if _LINEA_EXLYO.match(linea):
            continue
        linea = _EXLYO_EN_LINEA.sub("", linea)           # "Descripción: com_exlyo_x: " -> "Descripción: "
        if linea.strip() and not _LINEA_VACIA.match(linea) and (not lineas or lineas[-1] != linea):
            lineas.append(linea)
    if not lineas:
        return "", []
    try:
        raiz = lhtml.fragment_fromstring("<br>".join(lineas), create_parent="div")
    except (etree.ParserError, ValueError):
        return html.escape(" ".join(lineas)), []
    fotos: list[str] = []
    for e in list(raiz.iter()):
        if e is raiz or not isinstance(e.tag, str):
            if not isinstance(e.tag, str) and e.getparent() is not None:   # comments, PIs
                e.drop_tree()
            continue
        etiqueta = e.tag.lower()
        if etiqueta == "img":
            src = (e.get("src") or "").strip()
            if src.lower().startswith("files/") and src.lower().endswith(_IMG_EXT):
                fotos.append(Path(src).name)
            e.drop_tree()
            continue
        if etiqueta in _ETIQUETAS_FUERA:
            e.drop_tree()
            continue
        href = (e.get("href") or "").strip() if etiqueta == "a" else ""
        for atributo in list(e.attrib):
            del e.attrib[atributo]
        if etiqueta == "a":
            if re.match(r"^(https?:|mailto:)", href, re.I):
                e.set("href", href)
                e.set("target", "_blank")
                e.set("rel", "noopener")
            else:
                e.drop_tag()
                continue
        if etiqueta not in _ETIQUETAS_OK:
            e.drop_tag()
    salida = etree.tostring(raiz, encoding="unicode", method="html")
    salida = re.sub(r"^<div>|</div>$", "", salida.strip())
    salida = re.sub(r"(<br>\s*){3,}", "<br><br>", salida).strip()
    salida = re.sub(r"^(<br>\s*)+|(<br>\s*)+$", "", salida).strip()
    texto_plano = re.sub(r"<[^>]+>", "", salida).strip()
    return (salida if texto_plano else ""), fotos


def _datos_extendidos(pm: Any) -> dict[str, str]:
    datos: dict[str, str] = {}
    ed = _hijo(pm, "ExtendedData")
    if ed is None:
        return datos
    for d in ed.iter():
        if _local(d) == "Data" and d.get("name"):
            nombre = d.get("name").strip()
            valor = _texto(d, "value")
            if valor and not nombre.lower().startswith(("com_exlyo", "gx_media")):
                datos[nombre] = valor
        elif _local(d) == "SimpleData" and d.get("name") and (d.text or "").strip():
            datos[d.get("name").strip()] = d.text.strip()
    return datos


# --------------------------------------------------------------------------- estilos

def _leer_estilo(st: Any) -> dict[str, Any]:
    """The parts of a <Style> the viewer uses."""
    estilo: dict[str, Any] = {}
    if st is None:
        return estilo
    for parte in st:
        nombre = _local(parte)
        if nombre == "LineStyle":
            estilo["linea_color"] = _texto(parte, "color") or None
            estilo["linea_ancho"] = _texto(parte, "width") or None
        elif nombre == "PolyStyle":
            estilo["relleno_color"] = _texto(parte, "color") or None
            estilo["relleno"] = _texto(parte, "fill") != "0"
        elif nombre == "IconStyle":
            estilo["icono_color"] = _texto(parte, "color") or None
            estilo["icono_escala"] = _texto(parte, "scale") or None
            icono = _hijo(parte, "Icon")
            estilo["icono_href"] = _texto(icono, "href") if icono is not None else None
    return {k: v for k, v in estilo.items() if v is not None}


class Estilos:
    """Shared Styles and StyleMaps (pair "normal") of the document, resolved by styleUrl."""

    def __init__(self, raiz: Any):
        self._estilos = {e.get("id"): e for e in raiz.iter() if _local(e) == "Style" and e.get("id")}
        self._mapas = {e.get("id"): e for e in raiz.iter() if _local(e) == "StyleMap" and e.get("id")}
        self._cache: dict[str, dict[str, Any]] = {}

    def resolver(self, url: str, profundidad: int = 0) -> dict[str, Any]:
        clave = (url or "").split("#")[-1]
        if not clave or profundidad > 5:
            return {}
        if clave in self._cache:
            return self._cache[clave]
        if clave in self._mapas:
            resultado: dict[str, Any] = {}
            for par in self._mapas[clave]:
                if _local(par) == "Pair" and _texto(par, "key") == "normal":
                    estilo_en_linea = _hijo(par, "Style")
                    resultado = (_leer_estilo(estilo_en_linea) if estilo_en_linea is not None
                                 else self.resolver(_texto(par, "styleUrl"), profundidad + 1))
                    break
        else:
            resultado = _leer_estilo(self._estilos.get(clave))
        self._cache[clave] = resultado
        return resultado

    def de_placemark(self, pm: Any) -> dict[str, Any]:
        """Shared style (styleUrl) with the inline <Style> on top, as Google Earth does."""
        estilo = dict(self.resolver(_texto(pm, "styleUrl")))
        en_linea = _hijo(pm, "Style")
        if en_linea is not None:
            estilo.update(_leer_estilo(en_linea))
        return estilo


# --------------------------------------------------------------------------- íconos

def _nombre_google(href: str) -> str | None:
    m = re.search(r"maps\.google\.com/mapfiles/kml/(?:pushpin|shapes|paddle|pal\d)/([\w-]+)\.png", href or "")
    return m.group(1) if m else None


def _svg_icono(forma: str, color: str) -> str:
    borde = "#1a1a1a"
    if forma == "pin":
        cuerpo = (f'<line x1="22" y1="34" x2="10" y2="62" stroke="{borde}" stroke-width="3"/>'
                  f'<circle cx="30" cy="20" r="16" fill="{color}" stroke="{borde}" stroke-width="2.5"/>'
                  f'<circle cx="25" cy="15" r="5" fill="#ffffff" opacity=".7"/>')
    elif forma == "casa":
        cuerpo = (f'<path d="M8 30 L32 8 L56 30 L50 30 L50 56 L14 56 L14 30 Z" fill="{color}" stroke="{borde}" stroke-width="3"/>'
                  f'<rect x="26" y="38" width="12" height="18" fill="{borde}" opacity=".5"/>')
    elif forma == "cuadrado":
        cuerpo = f'<rect x="14" y="14" width="36" height="36" fill="{color}" stroke="{borde}" stroke-width="3"/>'
    elif forma == "bandera":
        cuerpo = (f'<line x1="16" y1="8" x2="16" y2="60" stroke="{borde}" stroke-width="4"/>'
                  f'<path d="M18 10 L54 20 L18 32 Z" fill="{color}" stroke="{borde}" stroke-width="2"/>')
    else:
        cuerpo = f'<circle cx="32" cy="32" r="20" fill="{color}" stroke="{borde}" stroke-width="3"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">{cuerpo}</svg>'


def _teñir_png(datos: bytes, color: str, opacidad: float) -> bytes:
    """Google Earth tints an icon by multiplying its pixels by the style colour."""
    from PIL import Image
    imagen = Image.open(io.BytesIO(datos)).convert("RGBA")
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    canales = imagen.split()
    teñidos = [canales[0].point(lambda v: v * r // 255), canales[1].point(lambda v: v * g // 255),
               canales[2].point(lambda v: v * b // 255), canales[3].point(lambda v: int(v * opacidad))]
    salida = io.BytesIO()
    Image.merge("RGBA", teñidos).save(salida, "PNG")
    return salida.getvalue()


class Iconos:
    """Icon files for the cache: one per (icon, colour)."""

    def __init__(self, kmz: zipfile.ZipFile, destino: Path, base: Path, descargar: bool):
        self._kmz = kmz
        self._destino = destino
        self._base = base                     # downloaded Google icons, kept between imports
        self._descargar = descargar
        self._hechos: dict[tuple[str, str, float], str | None] = {}
        self._originales: dict[str, bytes | None] = {}
        self._fallo_red = False
        self.descargados = 0
        self.svg = 0

    def _original(self, href: str) -> bytes | None:
        if href in self._originales:
            return self._originales[href]
        datos = None
        nombre_g = _nombre_google(href)
        if href.lower().startswith("files/"):
            try:
                datos = self._kmz.read(href)
            except KeyError:
                datos = None
        elif nombre_g:
            archivo = self._base / f"{nombre_g}.png"
            if archivo.is_file():
                datos = archivo.read_bytes()
            elif self._descargar and not self._fallo_red:
                try:
                    import requests
                    r = requests.get(href.replace("http://", "https://"), timeout=6)
                    if r.ok and r.content[:8] == b"\x89PNG\r\n\x1a\n":
                        datos = r.content
                        self._base.mkdir(parents=True, exist_ok=True)
                        archivo.write_bytes(datos)
                        self.descargados += 1
                except Exception as exc:          # no internet: SVG equivalents from now on
                    log.info("KMZ: Google icons not downloadable (%s); SVG equivalents", type(exc).__name__)
                    self._fallo_red = True
        self._originales[href] = datos
        return datos

    def archivo(self, href: str, color: str, opacidad: float) -> str | None:
        """File name in iconos/ for this icon tinted with `color` (None: no icon)."""
        if not href:
            return None
        clave = (href, color, opacidad)
        if clave in self._hechos:
            return self._hechos[clave]
        nombre_g = _nombre_google(href)
        base = nombre_g or re.sub(r"[^\w.-]", "_", Path(href).stem)[:60]
        blanco = color == "#ffffff" and opacidad >= 0.999
        sufijo = "" if blanco else f"_{color[1:]}" + ("" if opacidad >= 0.999 else f"_{int(opacidad * 100)}")
        datos = self._original(href)
        nombre: str | None
        try:
            if datos is not None:
                nombre = f"{base}{sufijo}.png"
                contenido = datos if blanco else _teñir_png(datos, color, opacidad)
            elif nombre_g in _ICONOS_GOOGLE:
                forma, base_color = _ICONOS_GOOGLE[nombre_g]
                nombre = f"{base}{sufijo}.svg"
                contenido = _svg_icono(forma, base_color if blanco else color).encode("utf-8")
                self.svg += 1
            else:
                nombre = None
                contenido = b""
        except Exception as exc:
            log.warning("KMZ: icon %s failed (%s)", href, exc)
            nombre, contenido = None, b""
        if nombre:
            self._destino.mkdir(parents=True, exist_ok=True)
            (self._destino / nombre).write_bytes(contenido)
        self._hechos[clave] = nombre
        return nombre


# --------------------------------------------------------------------------- geometría

def _coordenadas(texto: str | None) -> list[list[float]]:
    puntos = []
    for tupla in (texto or "").split():
        partes = tupla.split(",")
        if len(partes) < 2:
            continue
        try:
            lon, lat = float(partes[0]), float(partes[1])
        except ValueError:
            continue
        if math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            puntos.append([round(lon, 6), round(lat, 6)])
    return puntos


def _geometrias(e: Any) -> list[dict[str, Any]]:
    """GeoJSON geometries of a KML geometry element (MultiGeometry -> its parts)."""
    nombre = _local(e)
    if nombre == "Point":
        c = _coordenadas(_texto(e, "coordinates"))
        return [{"type": "Point", "coordinates": c[0]}] if c else []
    if nombre in ("LineString", "LinearRing"):
        c = _coordenadas(_texto(e, "coordinates"))
        return [{"type": "LineString", "coordinates": c}] if len(c) > 1 else []
    if nombre == "Polygon":
        anillos = []
        for borde in e.iter():
            if _local(borde) == "LinearRing":
                c = _coordenadas(_texto(borde, "coordinates"))
                if len(c) > 3:
                    anillos.append(c)
        return [{"type": "Polygon", "coordinates": anillos}] if anillos else []
    if nombre == "MultiGeometry":
        partes: list[dict[str, Any]] = []
        for hijo in e:
            partes.extend(_geometrias(hijo))
        return partes
    return []


def _geometria(pm: Any) -> dict[str, Any] | None:
    partes: list[dict[str, Any]] = []
    for hijo in pm:
        if _local(hijo) in ("Point", "LineString", "LinearRing", "Polygon", "MultiGeometry"):
            partes.extend(_geometrias(hijo))
    if not partes:
        return None
    if len(partes) == 1:
        return partes[0]
    tipos = {p["type"] for p in partes}
    if tipos == {"LineString"}:
        return {"type": "MultiLineString", "coordinates": [p["coordinates"] for p in partes]}
    if tipos == {"Point"}:
        return {"type": "MultiPoint", "coordinates": [p["coordinates"] for p in partes]}
    return {"type": "GeometryCollection", "geometries": partes}


def _tipo_geometria(geo: dict[str, Any]) -> str:
    t = geo["type"]
    if t in ("Point", "MultiPoint"):
        return "punto"
    if t in ("LineString", "MultiLineString"):
        return "linea"
    if t == "Polygon":
        return "poligono"
    return "mixta"


def _coords_planas(geo: dict[str, Any]) -> list[list[float]]:
    t = geo["type"]
    if t == "Point":
        return [geo["coordinates"]]
    if t in ("LineString", "MultiPoint"):
        return geo["coordinates"]
    if t in ("MultiLineString", "Polygon"):
        return [c for parte in geo["coordinates"] for c in parte]
    if t == "GeometryCollection":
        return [c for g in geo["geometries"] for c in _coords_planas(g)]
    return []


def _lineas(geo: dict[str, Any]) -> list[list[list[float]]]:
    t = geo["type"]
    if t == "LineString":
        return [geo["coordinates"]]
    if t == "MultiLineString":
        return geo["coordinates"]
    if t == "GeometryCollection":
        return [l for g in geo["geometries"] for l in _lineas(g)]
    return []


def _unir_bbox(a: list[float] | None, b: list[float] | None) -> list[float] | None:
    """bbox [oeste, sur, este, norte]."""
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _bbox(coords: list[list[float]]) -> list[float] | None:
    if not coords:
        return None
    lons, lats = [c[0] for c in coords], [c[1] for c in coords]
    return [min(lons), min(lats), max(lons), max(lats)]


# --------------------------------------------------------------------------- importación

def _estilo_visor(estilo: dict[str, Any], tipo: str, postes: bool, iconos: Iconos) -> dict[str, Any]:
    """What the page draws: a line, a circle (posts and wells) or an icon."""
    if tipo in ("linea", "poligono") or (tipo == "mixta" and "linea_color" in estilo):
        color, opacidad = color_kml(estilo.get("linea_color"))
        try:
            grosor = max(0.5, min(12.0, float(estilo.get("linea_ancho") or 1)))
        except ValueError:
            grosor = 1.0
        salida = {"tipo": "linea", "color": color, "opacidad": opacidad, "grosor": grosor}
        if tipo == "poligono":
            relleno, opac_relleno = color_kml(estilo.get("relleno_color"), "40ffffff")
            salida.update(relleno=relleno, relleno_opacidad=opac_relleno if estilo.get("relleno", True) else 0)
        return salida
    color, opacidad = color_kml(estilo.get("icono_color"))
    href = estilo.get("icono_href") or ""
    try:
        escala = max(0.3, min(4.0, float(estilo.get("icono_escala") or 1)))
    except ValueError:
        escala = 1.0
    nombre_g = _nombre_google(href) or ""
    if postes:
        if color == "#ffffff" and nombre_g in _CIRCULO_POR_DEFECTO:
            color = _CIRCULO_POR_DEFECTO[nombre_g]
        return {"tipo": "circulo", "color": color, "opacidad": max(opacidad, 0.6),
                "radio": round(max(3.0, min(7.0, 4.5 * escala)), 1)}
    archivo = iconos.archivo(href, color, opacidad) if href else None
    if archivo is None:
        return {"tipo": "circulo", "color": color, "opacidad": max(opacidad, 0.6), "radio": 6.0}
    forma = _ICONOS_GOOGLE.get(nombre_g, ("", ""))[0]
    return {"tipo": "icono", "icono": archivo, "tam": round(max(14, min(48, 28 * escala))),
            "ancla": "pin" if forma == "pin" else ("bandera" if forma == "bandera" else "centro"),
            "color": color}


def _familia(ruta_carpeta: str, nombre: str) -> str:
    texto = f"{ruta_carpeta}/{nombre}".upper()
    if "UFINET" in nombre.upper():
        return "ufinet"
    if "TRUNK GPON" in texto:
        return "gpon"
    if "TRUNK METRO" in texto:
        return "metro"
    if "ENLACE REDUNDANTE" in texto:
        return "redundante"
    return "troncal"


def _texto_busqueda(props: dict[str, Any]) -> str:
    """Plain text of the description, notes and descripción (search box, "also in descriptions")."""
    partes = [re.sub(r"<[^>]+>", " ", props.get("d", "")), props.get("notes", ""), props.get("desc", "")]
    texto = html.unescape(" ".join(" ".join(p.split()) for p in partes if p)).strip()
    return texto[:240]


def _renombrar(origen: Path, destino: Path, intentos: int = 20) -> None:
    """Folder rename that waits for the antivirus / indexer, which on Windows briefly hold
    freshly written files (PermissionError "Acceso denegado")."""
    for intento in range(intentos):
        try:
            origen.rename(destino)
            return
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(0.25)


def _escribir_json(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def importar(kmz: Path, destino: Path | None = None, progreso: Progreso | None = None,
             descargar_iconos: bool = True) -> dict[str, Any]:
    """Builds the cache for `kmz` in `destino` (default visor_rutas/datos_kmz) and returns the tree."""
    destino = Path(destino or CARPETA_DATOS)
    avisar = progreso or (lambda f, t: None)
    inicio = time.monotonic()
    avisar(0.02, "Calculando md5 del KMZ…")
    md5 = md5_archivo(kmz)
    temporal = destino.with_name(destino.name + ".nuevo")
    if temporal.exists():
        shutil.rmtree(temporal)
    (temporal / "capas").mkdir(parents=True)
    avisar(0.05, "Leyendo el KMZ…")
    with zipfile.ZipFile(kmz) as z:
        nombres = z.namelist()
        kml = next((n for n in nombres if n.lower() == "doc.kml"), None) or next(
            (n for n in nombres if n.lower().endswith(".kml")), None)
        if kml is None:
            raise ValueError(f"{kmz.name} no contiene ningún .kml")
        parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
        raiz = etree.fromstring(z.read(kml), parser)
        if raiz is None:
            raise ValueError(f"No se pudo leer {kml} del KMZ")
        estilos = Estilos(raiz)
        iconos = Iconos(z, temporal / "iconos", destino.parent / "datos_kmz_iconos_google", descargar_iconos)
        documento = next((e for e in raiz.iter() if _local(e) == "Document"), raiz)
        total_pm = sum(1 for e in raiz.iter() if _local(e) == "Placemark") or 1
        hechos = [0]
        carpetas: dict[str, dict[str, Any]] = {}
        fotos_usadas: set[str] = set()
        colores_troncales: Counter = Counter()
        lineas_troncales: list[tuple[str, dict[str, Any]]] = []     # (folder id, feature)
        features_por_carpeta: dict[str, list[dict[str, Any]]] = {}
        estilos_por_carpeta: dict[str, list[dict[str, Any]]] = {}

        def recorrer(nodo: Any, ruta: list[str], padre: str | None, troncal: bool) -> str:
            nombre = _texto(nodo, "name") or ("(sin nombre)" if _local(nodo) == "Folder" else "Documento")
            ruta_nodo = ruta + [nombre]
            cid = id_carpeta(ruta_nodo)
            n = 2
            while cid in carpetas:                     # two sibling folders with the same name
                cid = id_carpeta(ruta_nodo[:-1] + [f"{nombre}#{n}"])
                n += 1
            es_troncal = troncal or bool(_TRONCAL.search(nombre))
            postes = bool(_POSTES.search(nombre))
            carpeta = {"id": cid, "nombre": nombre, "ruta": "/".join(ruta_nodo), "padre": padre, "hijos": [],
                       "directos": 0, "total": 0, "geometria": None, "bbox": None, "estilo": None,
                       "troncal": es_troncal, "postes": postes,
                       "visible": bool(_ENCENDIDA.match(nombre.strip())) or (troncal and padre is not None
                                                                                 and carpetas[padre]["visible"]),
                       "etiquetas": es_troncal or bool(_NODOS.search(nombre)),
                       "visibilidad_kml": _texto(nodo, "visibility") or None}
            carpetas[cid] = carpeta
            ruta_texto = "/".join(ruta_nodo)
            features: list[dict[str, Any]] = []
            tabla: list[dict[str, Any]] = []
            indice_estilo: dict[str, int] = {}
            tipos: Counter = Counter()
            uso_estilos: Counter = Counter()
            for hijo in nodo:
                etiqueta = _local(hijo)
                if etiqueta in ("Folder", "Document"):
                    carpeta["hijos"].append(recorrer(hijo, ruta_nodo, cid, es_troncal))
                elif etiqueta == "Placemark":
                    hechos[0] += 1
                    if hechos[0] % 2000 == 0:
                        avisar(0.08 + 0.8 * hechos[0] / total_pm, f"Procesando elementos {hechos[0]:,} de {total_pm:,}…")
                    geo = _geometria(hijo)
                    if geo is None:
                        continue
                    tipo = _tipo_geometria(geo)
                    nombre_pm = _texto(hijo, "name")
                    estilo = _estilo_visor(estilos.de_placemark(hijo), tipo, postes, iconos)
                    clave = json.dumps(estilo, sort_keys=True)
                    if clave not in indice_estilo:
                        indice_estilo[clave] = len(tabla)
                        tabla.append(estilo)
                    descripcion, fotos = limpiar_descripcion(_texto(hijo, "description"))
                    extra = _datos_extendidos(hijo)
                    props: dict[str, Any] = {"n": nombre_pm, "e": indice_estilo[clave]}
                    if descripcion:
                        props["d"] = descripcion
                    notes = extra.pop("notes", "")
                    desc_ed = extra.pop("descripción", "") or extra.pop("Descripción", "") or extra.pop("descripcion", "")
                    if notes:
                        props["notes"] = notes
                    if desc_ed:
                        props["desc"] = desc_ed
                    extra.pop("rating", None)
                    if extra:
                        props["datos"] = extra
                    fotos = [f for f in dict.fromkeys(fotos) if f"files/{f}" in nombres]
                    if fotos:
                        props["fotos"] = fotos
                        fotos_usadas.update(fotos)
                    lineas = _lineas(geo)
                    if lineas:
                        props["km"] = round(sum(_longitud_km(l) for l in lineas), 3)
                    feature = {"type": "Feature", "geometry": geo, "properties": props}
                    if es_troncal and tipo == "linea":
                        props["f"] = _familia(ruta_texto, nombre_pm)
                        colores_troncales[(cid, estilo.get("color"))] += 1
                        lineas_troncales.append((cid, feature))
                    features.append(feature)
                    tipos[tipo] += 1
                    uso_estilos[indice_estilo[clave]] += 1
                    carpeta["bbox"] = _unir_bbox(carpeta["bbox"], _bbox(_coords_planas(geo)))
            carpeta["directos"] = len(features)
            carpeta["total"] = len(features) + sum(carpetas[h]["total"] for h in carpeta["hijos"])
            for h in carpeta["hijos"]:
                carpeta["bbox"] = _unir_bbox(carpeta["bbox"], carpetas[h]["bbox"])
            if tipos:
                carpeta["geometria"] = tipos.most_common(1)[0][0] if len(tipos) == 1 else (
                    tipos.most_common(1)[0][0] if tipos.most_common(1)[0][1] >= 0.9 * sum(tipos.values()) else "mixta")
                carpeta["estilo"] = tabla[uso_estilos.most_common(1)[0][0]]
            else:
                hijos_con_datos = [carpetas[h] for h in carpeta["hijos"] if carpetas[h]["total"]]
                geos = {h["geometria"] for h in hijos_con_datos}
                carpeta["geometria"] = geos.pop() if len(geos) == 1 else ("mixta" if geos else None)
                carpeta["estilo"] = next((h["estilo"] for h in hijos_con_datos if h["estilo"]), None)
            if features:
                features_por_carpeta[cid] = features
                estilos_por_carpeta[cid] = tabla
            return cid

        raiz_id = recorrer(documento, [], None, False)

        # Distinctive colours: trunk lines whose original colour is repeated in their own folder
        # (MANAGUA/TRONCAL, TRONCAL NUEVAS...). Folders where each line has its colour keep it.
        for _cid, feature in lineas_troncales:
            props = feature["properties"]
            if colores_troncales[(_cid, estilos_por_carpeta[_cid][props["e"]].get("color"))] > 1:
                props["cd"] = color_distintivo(props["n"])

        avisar(0.9, "Escribiendo las capas…")
        indice: dict[str, list[list[str]]] = {}
        for cid, features in features_por_carpeta.items():
            _escribir_json(temporal / "capas" / f"{cid}.geojson", {
                "type": "FeatureCollection", "carpeta": cid, "estilos": estilos_por_carpeta[cid],
                "features": features})
            indice[cid] = [[f["properties"]["n"], _texto_busqueda(f["properties"])] for f in features]
        _escribir_json(temporal / "indice.json", indice)
        if fotos_usadas:
            (temporal / "fotos").mkdir(parents=True, exist_ok=True)
            for foto in sorted(fotos_usadas):
                (temporal / "fotos" / foto).write_bytes(z.read(f"files/{foto}"))
    for c in carpetas.values():
        c["bbox"] = [round(v, 6) for v in c["bbox"]] if c["bbox"] else None
    arbol = {
        "version": VERSION_FORMATO, "md5": md5, "kmz": kmz.name, "kml": kml,
        "importado": time.strftime("%Y-%m-%d %H:%M:%S"), "raiz": raiz_id, "carpetas": carpetas,
        "elementos": sum(c["directos"] for c in carpetas.values()),
        "iconos": sorted(p.name for p in (temporal / "iconos").glob("*")) if (temporal / "iconos").is_dir() else [],
        "fotos": sorted(fotos_usadas), "paleta_troncales": PALETA_TRONCALES,
        "iconos_svg": iconos.svg, "errores_xml": len(parser.error_log),
    }
    _escribir_json(temporal / "arbol.json", arbol)
    # Swap the folders (the old cache stays until the new one is complete).
    viejo = destino.with_name(destino.name + ".viejo")
    if viejo.exists():
        shutil.rmtree(viejo, ignore_errors=True)
    if destino.exists():
        _renombrar(destino, viejo)
    _renombrar(temporal, destino)
    shutil.rmtree(viejo, ignore_errors=True)
    avisar(1.0, f"Red KMZ lista: {arbol['elementos']:,} elementos")
    log.info("KMZ imported: %s (%d elements, %d folders, %d icons, %d SVG, %.1fs)", kmz.name, arbol["elementos"],
             len(carpetas), len(arbol["iconos"]), iconos.svg, time.monotonic() - inicio)
    return arbol


# --------------------------------------------------------------------------- caché

def leer_arbol(destino: Path | None = None) -> dict[str, Any] | None:
    archivo = Path(destino or CARPETA_DATOS) / "arbol.json"
    try:
        arbol = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return arbol if arbol.get("version") == VERSION_FORMATO else None


def progreso_actual() -> dict[str, Any]:
    return dict(_progreso)


def asegurar(kmz: Path | str | None = None, destino: Path | None = None,
             progreso: Progreso | None = None) -> dict[str, Any]:
    """The tree of the current cache, importing first when it is missing or the KMZ changed.

    Without a KMZ the existing cache is used (with "aviso"); KmzNoEncontrado if there is neither.
    """
    destino = Path(destino or CARPETA_DATOS)

    def avisar(fraccion: float, texto: str) -> None:
        _progreso.update(activo=fraccion < 1, fraccion=round(fraccion, 3), texto=texto)
        if progreso:
            progreso(fraccion, texto)

    with _lock:
        arbol = leer_arbol(destino)
        try:
            archivo = ruta_kmz(kmz)
        except KmzNoEncontrado as exc:
            if arbol is not None:
                return {**arbol, "aviso": f"{exc}: se muestra la última red importada ({arbol.get('importado')})"}
            raise
        if arbol is not None and arbol.get("md5") == md5_archivo(archivo):
            return arbol
        try:
            return importar(archivo, destino, avisar)
        finally:
            _progreso.update(activo=False)


def archivo_seguro(relativa: str, destino: Path | None = None) -> Path:
    """iconos/<name> or fotos/<name> inside the cache (FileNotFoundError otherwise)."""
    destino = Path(destino or CARPETA_DATOS).resolve()
    if not re.fullmatch(r"(iconos|fotos)/[\w .()-]{1,160}\.(png|svg|jpe?g|gif|webp|bmp)", relativa or "", re.I):
        raise FileNotFoundError("Archivo no válido")
    ruta = (destino / relativa).resolve()
    if destino not in ruta.parents or not ruta.is_file():
        raise FileNotFoundError("Archivo no encontrado")
    return ruta


def archivo_indice(destino: Path | None = None) -> Path:
    ruta = Path(destino or CARPETA_DATOS) / "indice.json"
    if not ruta.is_file():
        raise FileNotFoundError("Índice de búsqueda no encontrado")
    return ruta


def archivo_capa(cid: str, destino: Path | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", cid or ""):
        raise FileNotFoundError("Capa no válida")
    ruta = Path(destino or CARPETA_DATOS) / "capas" / f"{cid}.geojson"
    if not ruta.is_file():
        raise FileNotFoundError("Capa no encontrada")
    return ruta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Caché del KMZ de la red para el panel Lugares del visor")
    parser.add_argument("--kmz", help="Archivo .kmz o carpeta (por defecto KMZ_PATH del .env)")
    parser.add_argument("--forzar", action="store_true", help="Regenerar aunque el md5 no haya cambiado")
    parser.add_argument("--sin-descargar", action="store_true", help="No descargar íconos de Google (usar SVG)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ImportError:
        pass
    archivo = ruta_kmz(args.kmz)
    print(f"KMZ: {archivo}")
    actual = leer_arbol()
    if not args.forzar and actual and actual.get("md5") == md5_archivo(archivo):
        print(f"La caché ya está al día ({actual['elementos']:,} elementos, importada {actual['importado']}).")
        return 0
    arbol = importar(archivo, progreso=lambda f, t: print(f"[{f * 100:5.1f}%] {t}"),
                     descargar_iconos=not args.sin_descargar)
    print(f"Listo: {arbol['elementos']:,} elementos, {len(arbol['carpetas'])} carpetas, "
          f"{len(arbol['iconos'])} íconos ({arbol['iconos_svg']} SVG), {len(arbol['fotos'])} fotos -> {CARPETA_DATOS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
