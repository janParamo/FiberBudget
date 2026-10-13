"""Capas de la red completa para el visor (como el KMZ en Google Earth), por zona visible.

  - KMZ (PostGIS, tablas red_puntos / red_lineas del DB_* del .env): mufas, reservas, postes y
    líneas (cables) tal como se importaron del KMZ.
  - Visio (red_fibra: PostgreSQL si hay conexión, si no red_fibra.db): nodos y enlaces lógicos.

Solo lectura. Nada se consulta hasta que el usuario enciende una capa, y cada consulta trae solo
lo que cae en el rectángulo visible del mapa (índice espacial), con un máximo de elementos y
las líneas simplificadas según el zoom, para que el visor no se ponga lento.
"""
import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import Any

import psycopg

from config import get_settings, load_rules
from origen import _PgAdapter

log = logging.getLogger(__name__)

# capa -> (origen, zoom mínimo, máximo de elementos por consulta, descripción)
CAPAS: dict[str, dict[str, Any]] = {
    "kmz_lineas":    {"origen": "kmz",   "zoom_min": 13, "max": 4000, "nombre": "líneas del KMZ"},
    "kmz_mufas":     {"origen": "kmz",   "zoom_min": 13, "max": 4000, "nombre": "mufas del KMZ"},
    "kmz_reservas":  {"origen": "kmz",   "zoom_min": 14, "max": 3000, "nombre": "reservas del KMZ"},
    "kmz_postes":    {"origen": "kmz",   "zoom_min": 16, "max": 5000, "nombre": "postes del KMZ"},
    "visio_nodos":   {"origen": "visio", "zoom_min": 12, "max": 4000, "nombre": "nodos Visio"},
    "visio_enlaces": {"origen": "visio", "zoom_min": 12, "max": 4000, "nombre": "enlaces Visio"},
}
_TIPOS_PUNTO = {"kmz_mufas": "mufa%", "kmz_reservas": "reserva%", "kmz_postes": "poste%"}
MAX_DESCRIPCION = 300


class CapaNoValida(ValueError):
    """Unknown layer name or a malformed map rectangle."""


def _rectangulo(oeste: float, sur: float, este: float, norte: float) -> tuple[float, float, float, float]:
    try:
        o, s, e, n = (float(v) for v in (oeste, sur, este, norte))
    except (TypeError, ValueError):
        raise CapaNoValida("Rectángulo del mapa no válido") from None
    if not all(math.isfinite(v) for v in (o, s, e, n)) or o >= e or s >= n:
        raise CapaNoValida("Rectángulo del mapa no válido")
    return max(o, -180.0), max(s, -90.0), min(e, 180.0), min(n, 90.0)


def _tolerancia_grados(zoom: int) -> float:
    """About one screen pixel at this zoom, in degrees: line detail below it is not visible."""
    return 360.0 / (256 * 2 ** max(0, min(int(zoom), 22)))


def _excluido(tipo: str | None, palabras: list[str]) -> bool:
    t = (tipo or "").casefold()
    return any(p.casefold() in t for p in palabras)


def _corto(texto: Any) -> str | None:
    texto = " ".join(str(texto or "").split())
    return (texto[:MAX_DESCRIPCION] + "…") if len(texto) > MAX_DESCRIPCION else (texto or None)


# --------------------------------------------------------------------------- KMZ (PostGIS)

def conectar_kmz() -> psycopg.Connection:
    """Read-only connection to the KMZ PostGIS database (same DB_* settings as the budget)."""
    s = get_settings()
    conn = psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user,
                           password=s.db_password, connect_timeout=5,
                           options="-c statement_timeout=15000")
    conn.read_only = True
    conn.autocommit = True
    return conn


_SQL_PUNTOS = """
SELECT id, tipo, nombre, descripcion, ST_Y(geom) AS lat, ST_X(geom) AS lon
FROM red_puntos
WHERE geom IS NOT NULL AND tipo ILIKE %(tipo)s
  AND geom && ST_MakeEnvelope(%(o)s, %(s)s, %(e)s, %(n)s, 4326)
LIMIT %(limite)s
"""

_SQL_LINEAS = """
SELECT id, tipo, nombre, descripcion,
       ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, %(tol)s), 6) AS geo
FROM red_lineas
WHERE geom IS NOT NULL
  AND geom && ST_MakeEnvelope(%(o)s, %(s)s, %(e)s, %(n)s, 4326)
LIMIT %(limite)s
"""


def _lineas_geojson(geo: str | None) -> list[list[list[float]]]:
    """GeoJSON (Multi)LineString -> list of lines of [lat, lon]."""
    if not geo:
        return []
    g = json.loads(geo)
    partes = [g["coordinates"]] if g["type"] == "LineString" else (g["coordinates"] if g["type"] == "MultiLineString" else [])
    return [[[round(lat, 6), round(lon, 6)] for lon, lat, *_ in parte] for parte in partes if len(parte) > 1]


def capa_kmz(conn: Any, capa: str, rect: tuple[float, float, float, float], zoom: int,
             excluidas: list[str]) -> tuple[list[dict[str, Any]], bool]:
    o, s, e, n = rect
    limite = CAPAS[capa]["max"]
    params = {"o": o, "s": s, "e": e, "n": n, "limite": limite + 1}
    if capa == "kmz_lineas":
        filas = conn.execute(_SQL_LINEAS, {**params, "tol": _tolerancia_grados(zoom)}).fetchall()
        elementos = [{"id": f[0], "tipo": f[1], "nombre": f[2], "descripcion": _corto(f[3]),
                      "lineas": _lineas_geojson(f[4]), "excluida": _excluido(f[1], excluidas)}
                     for f in filas[:limite]]
        elementos = [x for x in elementos if x["lineas"]]
    else:
        filas = conn.execute(_SQL_PUNTOS, {**params, "tipo": _TIPOS_PUNTO[capa]}).fetchall()
        elementos = [{"id": f[0], "tipo": f[1], "nombre": f[2], "descripcion": _corto(f[3]),
                      "lat": round(float(f[4]), 7), "lon": round(float(f[5]), 7),
                      "excluida": _excluido(f[1], excluidas)} for f in filas[:limite]]
    return elementos, len(filas) > limite


# --------------------------------------------------------------------------- Visio (red_fibra)

def _visio(visio_con: Any, archivo_sqlite: Path | None) -> tuple[Any, sqlite3.Connection | None]:
    """(query object with sqlite-style "?" placeholders, SQLite connection to close or None)."""
    if visio_con is not None:
        return _PgAdapter(visio_con), None
    if archivo_sqlite is None or not Path(archivo_sqlite).is_file():
        raise FileNotFoundError("base de diagramas no disponible")
    con = sqlite3.connect(f"{Path(archivo_sqlite).resolve().as_uri()}?mode=ro", uri=True)
    return con, con


def capa_visio(visio_con: Any, archivo_sqlite: Path | None, capa: str,
               rect: tuple[float, float, float, float]) -> tuple[list[dict[str, Any]], bool]:
    o, s, e, n = rect
    limite = CAPAS[capa]["max"]
    try:
        db, propia = _visio(visio_con, archivo_sqlite)
    except FileNotFoundError:
        raise
    try:
        if capa == "visio_nodos":
            filas = db.execute(
                "SELECT id, nombre, tipo, lat, lon, fuente_coord, notas FROM nodos "
                "WHERE tipo IN ('MUFA', 'NODO', 'MINI_NODO', 'ODF', 'RESERVA') AND lat IS NOT NULL "
                "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT ?", (s, n, o, e, limite + 1)).fetchall()
            elementos = [{"id": f[0], "nombre": f[1], "tipo": f[2], "lat": float(f[3]), "lon": float(f[4]),
                          "estimada": f[5] == "estimada_vecinos", "descripcion": _corto(f[6])}
                         for f in filas[:limite]]
        else:
            filas = db.execute(
                "SELECT e.id, a.nombre, b.nombre, a.lat, a.lon, b.lat, b.lon, e.fuente, e.confianza, "
                "e.hilos_cable, e.enlace_logico FROM enlaces e "
                "JOIN nodos a ON a.id = e.nodo_a_id JOIN nodos b ON b.id = e.nodo_b_id "
                "WHERE a.lat IS NOT NULL AND b.lat IS NOT NULL "
                "AND ((a.lat BETWEEN ? AND ? AND a.lon BETWEEN ? AND ?) OR (b.lat BETWEEN ? AND ? AND b.lon BETWEEN ? AND ?)) "
                "LIMIT ?", (s, n, o, e, s, n, o, e, limite + 1)).fetchall()
            elementos = [{"id": f[0], "nombre": f"{f[1]} ↔ {f[2]}", "lineas": [[[float(f[3]), float(f[4])],
                                                                                [float(f[5]), float(f[6])]]],
                          "fuente": f[7], "confianza": f[8], "hilos": f[9], "tipo": f[10] or f[7]}
                         for f in filas[:limite]]
    finally:
        if propia is not None:
            propia.close()
    return elementos, len(filas) > limite


# --------------------------------------------------------------------------- API

def consultar(capa: str, oeste: float, sur: float, este: float, norte: float, zoom: int,
              kmz_con: Any = None, visio_con: Any = None, archivo_sqlite: Path | None = None) -> dict[str, Any]:
    """Elements of one network layer inside the visible map rectangle.

    {"capa", "elementos", "truncado", "zoom_min", "debajo_del_zoom"}: below the layer's minimum
    zoom nothing is queried (debajo_del_zoom=True) so a zoomed-out map never loads the whole network.
    """
    if capa not in CAPAS:
        raise CapaNoValida(f"Capa desconocida: {capa}")
    config = CAPAS[capa]
    zoom = int(zoom)
    respuesta = {"capa": capa, "elementos": [], "truncado": False, "zoom_min": config["zoom_min"],
                 "debajo_del_zoom": zoom < config["zoom_min"]}
    if respuesta["debajo_del_zoom"]:
        return respuesta
    rect = _rectangulo(oeste, sur, este, norte)
    if config["origen"] == "kmz":
        if kmz_con is None:
            raise ConnectionError("sin conexión a la base del KMZ")
        excluidas = load_rules(get_settings().rules_path).get("excluded_tipo_keywords", [])
        respuesta["elementos"], respuesta["truncado"] = capa_kmz(kmz_con, capa, rect, zoom, excluidas)
    else:
        if archivo_sqlite is None:
            archivo_sqlite = get_settings().red_fibra_db
        respuesta["elementos"], respuesta["truncado"] = capa_visio(visio_con, archivo_sqlite, capa, rect)
    return respuesta
