"""Fibra Metro: the client is taken to the nearest NODO, not to the nearest mufa.

GPON hangs the client from the nearest mufa and intervenes every mufa up to the splitter. Metro
differs in two things (rule of 2026-11-17):
  * the connection point is the nearest NODO of the Visio network (tipo NODO); the route goes from
    that node to the client along the existing poles, with new poles where there are none (the
    same pole rules as GPON);
  * only ONE mufa is intervened: the mufa nearest to the node (never the ones found along the
    route or up the chain).
Nothing here changes the GPON path: main.py and visor_rutas/calculo.py call this module only when
the technology is metro.
"""
import logging
import math
import sqlite3
from typing import Any, Callable

import psycopg

import db
import origen
import red_fibra_pg
import reglas_mufas
from config import get_settings

log = logging.getLogger(__name__)

MUFA_RADIUS_M = 1000.0          # a mufa farther than this from the node is not "the one next to it"
MAX_CANDIDATES = 5
MUFA_COUNT_SOURCE = "metro_nodo"


class SinNodo(Exception):
    """The Visio network has no NODO with coordinates (or cannot be read)."""


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _filas_nodos(visio_con: Any) -> list[tuple]:
    """(id, nombre, propietario, lat, lon, fuente_coord, zona, notas) of every NODO with coordinates: PostgreSQL, else the SQLite file."""
    sql = ("SELECT id, nombre, propietario, lat, lon, fuente_coord, zona, notas FROM nodos "
           "WHERE tipo = 'NODO' AND lat IS NOT NULL AND lon IS NOT NULL")
    if visio_con is not None:
        try:
            return list(visio_con.execute(sql).fetchall())
        except psycopg.Error as exc:
            log.warning("Visio NODO query on PostgreSQL failed (%s); using the SQLite file", type(exc).__name__)
    archivo = get_settings().red_fibra_db
    if not archivo.is_file():
        return []
    try:
        con = sqlite3.connect(f"{archivo.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return list(con.execute(sql).fetchall())
        finally:
            con.close()
    except sqlite3.Error as exc:
        log.warning("Visio NODO query on SQLite failed (%s)", type(exc).__name__)
        return []


def nodo_mas_cercano(lat: float, lon: float, visio_con: Any) -> dict[str, Any] | None:
    """The NODO of the Visio network nearest (straight line) to (lat, lon), as the dicts of red_fibra_pg (None: there is none).

    Coordinates estimated from neighbours lose against a real one, as in red_fibra_pg.elegir_candidato."""
    nodos = []
    for id_, nombre, propietario, nlat, nlon, fuente, zona, notas in _filas_nodos(visio_con):
        nodos.append({"id": id_, "nombre": nombre, "tipo": "NODO", "propietario": propietario, "lat": float(nlat), "lon": float(nlon),
                      "fuente_coord": fuente, "zona": zona, "notas": notas,
                      "distancia_m": round(_distance_m(lat, lon, float(nlat), float(nlon)), 1)})
    reales = [n for n in nodos if n["fuente_coord"] != "estimada_vecinos"]
    return min(reales or nodos, key=lambda n: n["distancia_m"], default=None)


def resolver_nodo(lat: float, lon: float, rules: dict[str, Any], visio_con: Any,
                  ) -> tuple[db.Segment, red_fibra_pg.BusquedaVisio]:
    """(connection point = the nearest NODO, the Visio search that stands for it). Raises SinNodo."""
    nodo = nodo_mas_cercano(lat, lon, visio_con)
    if nodo is None:
        raise SinNodo("No se encontró un nodo de la red (tipo NODO) para llevar el cliente de Fibra Metro")
    log.info("Metro connection point: node %s at %.1f m", nodo["nombre"], nodo["distancia_m"])
    seg = db.Segment(id=f"visio:{nodo['id']}", tipo="nodo (visio)", lat=nodo["lat"], lon=nodo["lon"],
                     distance_m=nodo["distancia_m"], is_mufa=False, nombre=nodo["nombre"])
    busqueda = red_fibra_pg.BusquedaVisio(fuente="red_fibra" if visio_con is not None else red_fibra_pg.SIN_CONEXION,
                                          radio_m=nodo["distancia_m"], nodo=nodo)
    return seg, busqueda


def mufa_del_nodo(nodo: db.Segment, rules: dict[str, Any], no_disponible: Callable[[db.Segment], str | None],
                  ) -> tuple[db.Segment | None, list[str]]:
    """(the mufa to intervene, warnings): the KMZ mufa nearest to the node, skipping those marked without hilos (ELIMINADA / SATURADA).

    No mufa within `metro.mufa_radius_m` -> (None, a warning): the budget intervenes none and says so."""
    config = rules.get("metro") or {}
    radio = float(config.get("mufa_radius_m", MUFA_RADIUS_M))
    cantidad = int(config.get("max_candidates", MAX_CANDIDATES))
    try:
        candidatas = db.find_connection_candidates(
            nodo.lat, nodo.lon, rules["excluded_tipo_keywords"], radio, cantidad,
            excluded_names=reglas_mufas.patrones_sql(reglas_mufas.configuracion(rules)))
    except db.DatabaseError:
        return None, ["No se pudo consultar la mufa más cercana al nodo (el presupuesto no cuenta ninguna mufa intervenida)"]
    if not candidatas:
        return None, [f"No hay mufa a menos de {radio:.0f} m del nodo {nodo.nombre}: validar con Planta Externa"]
    motivos = {c.id: no_disponible(c) for c in candidatas}
    elegida = next((c for c in candidatas if motivos[c.id] is None), candidatas[0])
    avisos = []
    if elegida is not candidatas[0]:
        avisos.append(f"Mufa {candidatas[0].nombre or candidatas[0].id} (la más cercana al nodo) marcada {motivos[candidatas[0].id]}: "
                      f"se interviene {elegida.nombre or elegida.id}")
    elif motivos[elegida.id]:
        avisos.append(f"Mufa {elegida.nombre or elegida.id} marcada {motivos[elegida.id]} y no hay otra cerca del nodo: validar con Planta Externa")
    return elegida, avisos


def origen_trafico(nodo: db.Segment) -> origen.TrafficOrigin:
    """Origen de tráfico of a Metro client: the node itself (nothing to read from the diagrams)."""
    return origen.TrafficOrigin(node=nodo.nombre, confidence="alta", reason=None)
