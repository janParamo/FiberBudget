"""Splitters de los diagramas de Visio: clase, puertos y estado, y su guardado cada vez que se genera una ruta de fusión.

Lo que se lee (docs/modulo_redes/ESTUDIO_SPLITTERS.md) es de confianza alta: la clase por el color del texto (morado = secundario, dorado =
principal; si es negro, por la palabra SECUNDARIO / PRINCIPAL; si no, «por confirmar») y los puertos de la lista «1- cliente … 8-» cuando existe
(un renglón en blanco es un puerto libre). Los puertos de un splitter sin lista quedan «desconocido»: las líneas del dibujo no alcanzan para
decirlo, así que una persona los confirma en pantalla y lo confirmado se guarda y gana sobre lo automático. Nada de esto rompe una ruta: si falta
el diagrama o la base de redes, la parada simplemente no trae splitters.
"""
import logging
import math
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from lxml import etree

from visor_rutas import almacen_archivos

log = logging.getLogger(__name__)

CACHE_ODG = Path(__file__).resolve().parents[1] / "datos" / "cache" / "odg"
MORADO = frozenset({"#7030a0"})
DORADO = frozenset({"#d26d19", "#ea700d", "#966115", "#ea9651", "#ffc000", "#c55a11"})
RADIO_PUERTOS_CM = 8.0            # the frame of port numbers of a splitter is within this distance of its label
RADIO_LISTA_CM = 10.0             # so is its «1- cliente 2- …» list
RADIO_MUFA_CM = 45.0              # splitters shown for a mufa: those this close to where the mufa is drawn
MAX_POR_PARADA = 8
RE_SPL = re.compile(r"\bSPL\b|\bSPL\d|SPLITTER", re.I)
RE_RATIO = re.compile(r"\b1\s*[x/]\s*(2|4|8|16|32)\b", re.I)
RE_ITEM = re.compile(r"^[ \t]*(\d{1,2})[ \t]*[-.)][ \t]*(.*)$", re.M)     # [ \t], not \s: a blank item must not swallow the next line
_DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
_SVG = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
_FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
ESTADOS = ("libre", "ocupado")


def _cm(valor: Any) -> float | None:
    m = re.match(r"^(-?[\d.]+)\s*(cm|mm|in|pt)?$", str(valor or "").strip())
    if not m:
        return None
    return float(m.group(1)) * {"cm": 1, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, None: 1}[m.group(2)]


def _colores(raiz: Any) -> dict[str, str]:
    salida: dict[str, str] = {}
    for st in raiz.iter("{%s}style" % _STYLE):
        for hijo in st:
            color = hijo.get("{%s}color" % _FO)
            if color:
                salida[st.get("{%s}name" % _STYLE)] = color.lower()
    return salida


def textos_odg(md5: str, carpeta: Path | None = None) -> list[dict[str, Any]]:
    """The text frames of a converted diagram in absolute cm: {x, y, w, h, texto, color} (x, y = the centre of the frame)."""
    archivo = (carpeta or CACHE_ODG) / f"{md5}.odg"
    if carpeta is None and not archivo.is_file() and re.fullmatch(r"[0-9a-f]{32}", str(md5)):
        almacen_archivos.restaurar("odg", archivo.name, archivo)     # the database store holds the converted diagrams
    if not archivo.is_file():
        return []
    z = zipfile.ZipFile(archivo)
    contenido = etree.fromstring(z.read("content.xml"))
    colores = _colores(contenido)
    try:
        colores = {**_colores(etree.fromstring(z.read("styles.xml"))), **colores}
    except KeyError:
        pass
    salida = []
    for e in contenido.iter("{%s}frame" % _DRAW):
        caja = e.find("{%s}text-box" % _DRAW)
        if caja is None:
            continue
        x, y, w, h = (_cm(e.get("{%s}%s" % (_SVG, k))) for k in ("x", "y", "width", "height"))
        texto = "\n".join("".join(p.itertext()) for p in caja.iter("{%s}p" % _TEXT)).strip()
        color = next((colores[n] for n in (s.get("{%s}style-name" % _TEXT) for s in list(caja.iter("{%s}span" % _TEXT)) + list(caja.iter("{%s}p" % _TEXT)))
                      if n in colores), None)
        if texto and None not in (x, y, w, h):
            salida.append({"x": x + w / 2, "y": y + h / 2, "w": w, "h": h, "texto": texto, "color": color})
    return salida


def clase_por_color(color: str | None) -> str | None:
    color = (color or "").lower()
    return "secundario" if color in MORADO else "principal" if color in DORADO else None


def clase_por_palabra(texto: str) -> str | None:
    t = texto.upper()
    sec, pri = "SECUNDARIO" in t, "PRINCIPAL" in t
    return "secundario" if sec and not pri else "principal" if pri and not sec else None


def secuencia(texto: str) -> list[int] | None:
    """Port numbers of a frame that is only numbers («8\\n7\\n…\\n1» or «1 2 3 … 8»), in the order they are drawn."""
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    if len(lineas) >= 2 and all(re.fullmatch(r"\d{1,2}", l) for l in lineas):
        return [int(l) for l in lineas]
    if len(lineas) == 1:
        toks = lineas[0].split()
        if len(toks) >= 2 and all(re.fullmatch(r"\d{1,2}", t) for t in toks):
            return [int(t) for t in toks]
    return None


def _distancia(a: dict[str, Any], b: dict[str, Any]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def leer(md5: str, carpeta: Path | None = None) -> list[dict[str, Any]]:
    """Every splitter drawn in the diagram: {clave, etiqueta, x_cm, y_cm, clase, clase_fuente, ratio, puertos: {n: {estado, cliente}} , fuente_puertos}."""
    textos = textos_odg(md5, carpeta)
    etiquetas = [t for t in textos if RE_SPL.search(t["texto"]) and len(t["texto"]) < 160 and not RE_ITEM.search(t["texto"])]
    cuadros = [(t, secuencia(t["texto"])) for t in textos]
    cuadros = [(t, s) for t, s in cuadros if s and len(s) >= 3]
    listas = [t for t in textos if RE_SPL.search(t["texto"]) and len(RE_ITEM.findall(t["texto"])) >= 2]
    salida, vistos = [], set()
    for e in etiquetas:
        clave = f"{e['x']:.1f},{e['y']:.1f}"
        if clave in vistos:
            continue
        vistos.add(clave)
        etiqueta = " ".join(e["texto"].split())
        clase, fuente = clase_por_color(e["color"]), "color"
        if clase is None:
            clase, fuente = clase_por_palabra(etiqueta), "palabra"
        if clase is None:
            clase, fuente = "por_confirmar", "sin_dato"
        cerca = sorted(((_distancia(t, e), t, s) for t, s in cuadros
                        if (t["color"] or "") == (e["color"] or "") and _distancia(t, e) <= RADIO_PUERTOS_CM), key=lambda c: c[0])
        numeros = sorted(set(cerca[0][2])) if cerca else []
        puertos = {n: {"estado": "desconocido", "cliente": None} for n in numeros}
        fuente_puertos = "sin_dato"
        lista = sorted(((_distancia(t, e), t) for t in listas if _distancia(t, e) <= RADIO_LISTA_CM), key=lambda c: c[0])
        if lista:
            items = {int(n): v.strip() for n, v in RE_ITEM.findall(lista[0][1]["texto"])}
            numeros = sorted(set(numeros) | set(items))
            puertos = {n: ({"estado": "ocupado", "cliente": items[n]} if items.get(n) else {"estado": "libre", "cliente": None}) if n in items
                       else {"estado": "desconocido", "cliente": None} for n in numeros}
            fuente_puertos = "lista"
        ratio = RE_RATIO.search(etiqueta)
        salida.append({"clave": clave, "etiqueta": etiqueta[:160], "x_cm": round(e["x"], 2), "y_cm": round(e["y"], 2), "clase": clase, "clase_fuente": fuente,
                       "ratio": f"1/{ratio.group(1)}" if ratio else None, "puertos": {str(n): p for n, p in puertos.items()},
                       "fuente_puertos": fuente_puertos})
    return salida


def combinar(auto: dict[str, Any], confirmado: dict[str, Any] | None) -> dict[str, Any]:
    """What is shown for a splitter: the automatic reading with what a person confirmed on top. Adds `libres`, `desconocidos` and `confirmado`."""
    puertos = {n: dict(p, fuente=auto.get("fuente_puertos", "sin_dato") if p["estado"] != "desconocido" else "sin_dato")
               for n, p in (auto.get("puertos") or {}).items()}
    clase, clase_fuente = auto.get("clase", "por_confirmar"), auto.get("clase_fuente", "sin_dato")
    if confirmado:
        if confirmado.get("clase") in ("secundario", "principal"):
            clase, clase_fuente = confirmado["clase"], "confirmado"
        for n, estado in (confirmado.get("puertos") or {}).items():
            if estado in ESTADOS:
                puertos[str(n)] = dict(puertos.get(str(n)) or {"cliente": None}, estado=estado, fuente="confirmado")
    orden = sorted(puertos, key=int)
    return {**{k: v for k, v in auto.items() if k not in ("puertos", "clase", "clase_fuente")}, "clase": clase, "clase_fuente": clase_fuente,
            "puertos": {n: puertos[n] for n in orden}, "libres": sum(1 for p in puertos.values() if p["estado"] == "libre"),
            "desconocidos": sum(1 for p in puertos.values() if p["estado"] == "desconocido"), "confirmado": bool(confirmado)}


def preferido(splitters: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one to use in a mufa: a secondary with free ports first (confirmed before read), then a secondary to confirm, then a primary."""
    def puntos(s: dict[str, Any]) -> tuple:
        return (s["clase"] == "secundario", s["libres"] > 0, s["confirmado"], s["desconocidos"] > 0, s["clase"] != "por_confirmar")
    utiles = [s for s in splitters if s["clase"] != "por_confirmar" or s["libres"] or s["desconocidos"]]
    return max(utiles, key=puntos) if utiles else None


def descripcion(s: dict[str, Any]) -> str:
    """One line for the plan: «Splitter secundario 1/8 (SPL …): 2 puertos libres (confirmado)»."""
    base = f"Splitter {s['clase'].replace('_', ' ')}{' ' + s['ratio'] if s.get('ratio') else ''}"
    if s["libres"]:
        return f"{base}: {s['libres']} puerto(s) libre(s)" + (" (confirmado)" if s["confirmado"] else " (según la lista del diagrama)")
    if s["desconocidos"] and not any(p["estado"] == "ocupado" for p in s["puertos"].values()):
        return f"{base}: puertos por confirmar en el diagrama"
    return f"{base}: sin puertos libres" if s["puertos"] else f"{base}: sin puertos leídos"


@lru_cache(maxsize=64)
def _leer_cache(md5: str) -> tuple:
    return tuple(leer(md5))


def de_parada(parada: dict[str, Any]) -> list[dict[str, Any]]:
    """Splitters of a fusion-route stop: those drawn near the mufa in each of its diagrams (all of them when its position is unknown)."""
    cercanos = []
    for a in (parada.get("archivos") or []):
        if not a.get("diagrama") or not a.get("md5"):
            continue
        ancla = a.get("ancla")
        for s in _leer_cache(a["md5"]):
            d = math.hypot(s["x_cm"] - ancla["x_cm"], s["y_cm"] - ancla["y_cm"]) if ancla else 0.0
            if d <= RADIO_MUFA_CM:
                cercanos.append((d, dict(s, md5=a["md5"], archivo=a.get("nombre"))))
    cercanos.sort(key=lambda c: c[0])
    return [s for _, s in cercanos[:MAX_POR_PARADA]]


def enriquecer(paradas: list[dict[str, Any]], guardar: Callable[[list[dict[str, Any]]], dict[tuple[str, str], dict[str, Any]]] | None = None) -> None:
    """Adds `splitters_diagrama` to every stop, in place. `guardar` stores what was read and returns what people confirmed, by (md5, clave) with
    the row `id`, `version` and `confirmado`; without it nothing is stored. A failure leaves the stop without splitters."""
    for p in paradas:
        try:
            leidos = de_parada(p)
            guardados = guardar(leidos) if guardar and leidos else {}
        except Exception as exc:                                    # noqa: BLE001 - never break a route
            log.warning("Splitters of the diagrams of %s could not be read (%s: %s)", p.get("nombre"), type(exc).__name__, exc)
            leidos, guardados = [], {}
        lista = []
        for s in leidos:
            fila = guardados.get((s["md5"], s["clave"])) or {}
            lista.append(dict(combinar(s, fila.get("confirmado")), id=fila.get("id"), version=fila.get("version")))
        p["splitters_diagrama"] = lista


def guardar_en_redes(splitters: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Stores the splitters read in the redes database (its own short connection; a missing table or database is skipped, logged)."""
    from visor_rutas.redes import db, splitters as almacen
    import psycopg
    try:
        con = db.conectar()
    except Exception as exc:                                        # noqa: BLE001 - redes not configured / unreachable
        log.info("Splitters not stored (redes unavailable: %s)", type(exc).__name__)
        return {}
    try:
        return almacen.registrar(con, splitters)
    except psycopg.Error as exc:
        log.warning("Splitters not stored (%s): %s", type(exc).__name__, str(exc).strip()[:160])
        return {}
    finally:
        con.close()

