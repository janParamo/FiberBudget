"""PostGIS access: nearest usable connection point and route assets."""
import logging
import math
import re
from dataclasses import dataclass

import psycopg

from config import get_settings

log = logging.getLogger(__name__)


class DatabaseError(Exception):
    """The database could not be reached or the query failed."""


class NoSegmentFound(Exception):
    """No eligible segment exists in red_lineas."""


class ExistingPolesQueryError(Exception):
    """The existing-pole lookup could not be completed."""


@dataclass
class Segment:
    id: int | str
    tipo: str | None
    lat: float            # selected connection point
    lon: float
    distance_m: float     # straight-line distance client -> segment (informational)
    is_mufa: bool = False
    is_reserve: bool = False
    nombre: str | None = None
    descripcion: str | None = None   # KMZ description ("MF ELIMINADA", "MF SATURADA", "SPL 1/4"...)


@dataclass
class ExistingPole:
    id: int | str
    lat: float
    lon: float
    route_position_m: float


@dataclass
class RouteMufa:
    id: int | str
    tipo: str | None
    lat: float
    lon: float
    distance_m: float
    is_backbone: bool
    nombre: str | None = None


def deduplicate_existing_poles(poles: list[ExistingPole], same_pole_m: float = 2.0) -> list[ExistingPole]:
    """Keep one record per physical pole: records less than same_pole_m apart are one pole.

    Compared by location, not by route position: two real poles beyond the route's end
    both project onto its last point and must still count twice.
    """
    unique: list[ExistingPole] = []
    for pole in poles:
        if all(_distance_m(pole.lat, pole.lon, kept.lat, kept.lon) >= same_pole_m for kept in unique):
            unique.append(pole)
    return unique


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


def check_connection() -> None:
    """Verify PostgreSQL is reachable without exposing connection details."""
    s = get_settings()
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        log.error("PostgreSQL health check failed (%s)", type(exc).__name__)
        raise DatabaseError("Database health check failed") from exc


# COORDINATE ORDER: ST_MakePoint(x, y) == ST_MakePoint(LONGITUDE, LATITUDE).
# The API receives (latitude, longitude), so we pass lon first below.
# ST_Y() returns latitude, ST_X() returns longitude.
#
# `ORDER BY geom <-> pt` uses the GiST index (KNN) and ranks in planar degrees;
# at Nicaragua's latitudes this is accurate enough to pick the nearest segment.
# The reported distance uses ::geography, so it is in real meters.
# Nearest mufa/reserva point. `tipos` holds ILIKE patterns; a NULL radius means no limit.
_CONNECTION_POINT_SQL = """
WITH pt AS (
        SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS g
)
SELECT p.id,
             p.tipo,
             ST_Y(p.geom) AS lat,
             ST_X(p.geom) AS lon,
             ST_Distance(p.geom::geography, pt.g::geography) AS dist_m,
             p.nombre,
             p.descripcion
FROM red_puntos p, pt
WHERE p.geom IS NOT NULL
    AND p.tipo ILIKE ANY(%(tipos)s)
    AND NOT (p.tipo ILIKE ANY(%(excluded)s))
    AND (%(nombre_excluida)s::text IS NULL OR NOT (coalesce(p.nombre, '') ~* %(nombre_excluida)s::text
         AND NOT (%(nombre_excepcion)s::text IS NOT NULL AND coalesce(p.nombre, '') ~* %(nombre_excepcion)s::text)))
    AND (%(radius_m)s::float8 IS NULL
         OR ST_DWithin(p.geom::geography, pt.g::geography, %(radius_m)s::float8))
ORDER BY p.geom <-> pt.g
LIMIT %(limit)s
"""
_MUFA_TIPOS = ["mufa%"]
_RESERVE_TIPOS = ["reserva%"]

_ROUTE_MUFAS_SQL = """
WITH ruta AS (
    SELECT ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326) AS geom
), mufas AS (
    SELECT p.id, p.tipo, p.geom, p.nombre
    FROM red_puntos p, ruta
    WHERE p.geom IS NOT NULL
      AND p.tipo ILIKE 'mufa%%'
      AND NOT (p.tipo ILIKE ANY(%(excluded)s))
      AND (%(nombre_excluida)s::text IS NULL OR NOT (coalesce(p.nombre, '') ~* %(nombre_excluida)s::text
           AND NOT (%(nombre_excepcion)s::text IS NOT NULL AND coalesce(p.nombre, '') ~* %(nombre_excepcion)s::text)))
      AND ST_DWithin(p.geom::geography, ruta.geom::geography, %(buffer_m)s)
), classified AS (
    SELECT m.id, m.tipo, m.geom, m.nombre,
           EXISTS (
               SELECT 1
               FROM red_lineas l
               WHERE l.geom IS NOT NULL
                 AND l.tipo IS NOT NULL
                 AND (l.tipo ILIKE '%%backbone%%' OR l.tipo ILIKE '%%troncal%%')
                 AND ST_DWithin(l.geom::geography, m.geom::geography, %(buffer_m)s)
           ) AS is_backbone
    FROM mufas m
)
SELECT id, tipo, ST_Y(geom) AS lat, ST_X(geom) AS lon,
       ST_Distance(geom::geography, ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326)::geography) AS distance_m,
       is_backbone, nombre
FROM classified
ORDER BY distance_m, id
"""


# Mufas linked to a mufa by an existing fiber line: the line passes within `tol_m` of both.
_MUFA_NEIGHBORS_SQL = """
WITH src AS (
    SELECT geom FROM red_puntos WHERE id = %(mufa_id)s
), touching AS (
    SELECT l.geom
    FROM red_lineas l, src
    WHERE l.geom IS NOT NULL
      AND ST_DWithin(l.geom::geography, src.geom::geography, %(tol_m)s)
)
SELECT DISTINCT p.id, p.nombre, ST_Distance(p.geom::geography, src.geom::geography) AS dist_m
FROM red_puntos p, touching t, src
WHERE p.id <> %(mufa_id)s
  AND p.geom IS NOT NULL
  AND p.tipo ILIKE 'mufa%%'
  AND NOT (p.tipo ILIKE ANY(%(excluded)s))
  AND ST_DWithin(p.geom::geography, t.geom::geography, %(tol_m)s)
"""

# Distribution mufas and the first rule that marks them, checked in this order:
#   cable_24h     - a line labelled with >= min_fibers hilos ("FO 24H") passes the mufa
#   linea_troncal - a trunk-type line, or one whose name/description says TRONCAL/BACKBONE
#   mufa_troncal  - the mufa's own description says TRONCAL/BACKBONE
_DISTRIBUTION_MUFAS_SQL = r"""
SELECT id, reason FROM (
    SELECT p.id,
           CASE
               WHEN EXISTS (
                   SELECT 1
                   FROM red_lineas l,
                        regexp_matches(coalesce(l.nombre, '') || ' ' || coalesce(l.descripcion, ''),
                                       '(\d+)\s*H\M', 'gi') AS m(g)
                   WHERE l.geom IS NOT NULL
                     AND ST_DWithin(l.geom::geography, p.geom::geography, %(tol_m)s)
                     AND m.g[1]::numeric >= %(min_fibers)s) THEN 'cable_24h'
               WHEN EXISTS (
                   SELECT 1
                   FROM red_lineas l
                   WHERE l.geom IS NOT NULL
                     AND ST_DWithin(l.geom::geography, p.geom::geography, %(tol_m)s)
                     AND (l.tipo ILIKE ANY(%(trunk_tipos)s)
                          OR coalesce(l.nombre, '') || ' ' || coalesce(l.descripcion, '')
                             ~* %(trunk_words)s)) THEN 'linea_troncal'
               WHEN coalesce(p.descripcion, '') ~* %(trunk_words)s THEN 'mufa_troncal'
           END AS reason
    FROM red_puntos p
    WHERE p.id = ANY(%(ids)s)
) marked
WHERE reason IS NOT NULL
"""


@dataclass
class ChainMufa:
    id: int | str
    nombre: str | None
    distribution_reason: str | None = None   # set on the distribution mufa that ends the chain


def find_upstream_mufa_chain(
    mufa_id: int | str,
    mufa_nombre: str | None,
    excluded_keywords: list[str],
    chain_rules: dict,
) -> list[ChainMufa]:
    """Mufas a new hilo crosses from the nearest distribution mufa down to the connection mufa.

    Walks existing fiber lines mufa by mufa (fewest hops, then nearest) until it reaches a
    mufa on a trunk or >= N-hilos cable. The connection mufa is always first. If no
    distribution mufa is found within max_hops, only the connection mufa is returned.
    """
    s = get_settings()
    patterns = [f"%{keyword}%" for keyword in excluded_keywords]
    tol_m = float(chain_rules.get("line_tolerance_m", 5))
    max_hops = int(chain_rules.get("max_hops", 6))
    keywords = chain_rules.get("distribution_keywords", ["TRONCAL", "BACKBONE"])
    distribution_params = {
        "tol_m": tol_m,
        "trunk_tipos": list(chain_rules.get("distribution_line_tipos", [])),
        "min_fibers": int(chain_rules.get("distribution_min_fibers", 24)),
        # PostgreSQL word boundaries (\m \M) so "TRONCAL" does not match inside other words.
        "trunk_words": r"\m(" + "|".join(re.escape(word) for word in keywords) + r")\M",
    }
    start = ChainMufa(id=mufa_id, nombre=mufa_nombre)
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            def distribution_ids(ids: list) -> dict:
                rows = conn.execute(_DISTRIBUTION_MUFAS_SQL, {**distribution_params, "ids": ids}).fetchall()
                return {row[0]: row[1] for row in rows}

            reason = distribution_ids([mufa_id]).get(mufa_id)
            if reason:
                start.distribution_reason = reason
                return [start]
            parents: dict = {mufa_id: None}
            names = {mufa_id: mufa_nombre}
            level = [mufa_id]
            for _ in range(max_hops):
                candidates: dict = {}   # neighbor id -> (distance to parent, parent id)
                for current in level:
                    for neighbor_id, nombre, dist_m in conn.execute(
                            _MUFA_NEIGHBORS_SQL,
                            {"mufa_id": current, "tol_m": tol_m, "excluded": patterns}).fetchall():
                        if neighbor_id in parents:
                            continue
                        names[neighbor_id] = (nombre or "").strip() or None
                        if neighbor_id not in candidates or dist_m < candidates[neighbor_id][0]:
                            candidates[neighbor_id] = (float(dist_m), current)
                if not candidates:
                    break
                for neighbor_id, (_, parent) in candidates.items():
                    parents[neighbor_id] = parent
                found = distribution_ids(list(candidates))
                if found:
                    target = min(found, key=lambda mid: candidates[mid][0])
                    chain = [ChainMufa(id=target, nombre=names.get(target), distribution_reason=found[target])]
                    target = parents[target]
                    while target is not None:
                        chain.append(ChainMufa(id=target, nombre=names.get(target)))
                        target = parents[target]
                    return chain[::-1]
                level = sorted(candidates, key=lambda mid: candidates[mid][0])
    except psycopg.Error as exc:
        log.error("Upstream mufa chain query failed (%s)", type(exc).__name__)
        raise DatabaseError(str(exc)) from exc
    log.warning("No distribution mufa within %d hops of mufa %s; counting only it", max_hops, mufa_id)
    return [start]


def find_point_coords(ids: list) -> dict:
    """(lat, lon) of red_puntos rows by id; ids without geometry are left out."""
    if not ids:
        return {}
    s = get_settings()
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            rows = conn.execute(
                "SELECT id, ST_Y(geom), ST_X(geom) FROM red_puntos WHERE id = ANY(%(ids)s) AND geom IS NOT NULL",
                {"ids": list(ids)}).fetchall()
    except psycopg.Error as exc:
        log.error("Point coordinate query failed (%s)", type(exc).__name__)
        raise DatabaseError(str(exc)) from exc
    return {row[0]: (float(row[1]), float(row[2])) for row in rows}


def _nombres(excluded_names: tuple[str | None, str | None] | None) -> dict[str, str | None]:
    """Query parameters of the mufa names that cannot be used (reglas_mufas.patrones_sql): the regex of the names and of its exceptions."""
    excluida, excepcion = excluded_names or (None, None)
    return {"nombre_excluida": excluida, "nombre_excepcion": excepcion}


def _connection_point_from_row(row: tuple) -> Segment:
    seg_id, tipo, seg_lat, seg_lon, dist, nombre, *rest = row
    kind = (tipo or "").casefold()
    return Segment(id=seg_id, tipo=tipo, lat=float(seg_lat), lon=float(seg_lon),
                   distance_m=float(dist), is_mufa=kind.startswith("mufa"),
                   is_reserve=kind.startswith("reserva"),
                   nombre=(nombre or "").strip() or None,
                   descripcion=(rest[0] or "").strip() or None if rest else None)


def find_connection_candidates(
    lat: float,
    lon: float,
    excluded_keywords: list[str],
    radius_m: float,
    limit: int,
    include_reserves: bool = False,
    excluded_names: tuple[str | None, str | None] | None = None,
) -> list[Segment]:
    """The `limit` KMZ mufas (and reservas if asked) nearest to the client within radius_m,
    nearest first, to compare them by street-route length."""
    s = get_settings()
    tipos = _MUFA_TIPOS + (_RESERVE_TIPOS if include_reserves else [])
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            rows = conn.execute(
                _CONNECTION_POINT_SQL,
                {"lat": lat, "lon": lon, "tipos": tipos, "radius_m": radius_m, "limit": int(limit),
                 "excluded": [f"%{keyword}%" for keyword in excluded_keywords], **_nombres(excluded_names)},
            ).fetchall()
    except psycopg.Error as exc:
        log.error("PostGIS connection-candidates query failed (%s)", type(exc).__name__)
        raise DatabaseError(str(exc)) from exc
    return [_connection_point_from_row(row) for row in rows]


def find_nearest_connection_point(
    lat: float,
    lon: float,
    excluded_keywords: list[str],
    mufa_search_radius_m: float = 500,
    excluded_names: tuple[str | None, str | None] | None = None,
) -> Segment:
    """Select the connection point from existing network points, never a line projection.

    Order: nearest mufa within the radius, then nearest reserva within the radius,
    then the nearest mufa or reserva at any distance.
    """
    if mufa_search_radius_m < 0:
        raise ValueError("mufa_search_radius_m must be >= 0")

    s = get_settings()
    patterns = [f"%{keyword}%" for keyword in excluded_keywords]
    searches = [
        (_MUFA_TIPOS, mufa_search_radius_m),
        (_RESERVE_TIPOS, mufa_search_radius_m),
        (_MUFA_TIPOS + _RESERVE_TIPOS, None),
    ]
    row = None
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            for tipos, radius_m in searches:
                row = conn.execute(
                    _CONNECTION_POINT_SQL,
                    {"lat": lat, "lon": lon, "tipos": tipos, "excluded": patterns,
                     "radius_m": radius_m, "limit": 1, **_nombres(excluded_names)},
                ).fetchone()
                if row is not None:
                    break
    except psycopg.Error as exc:
        log.error("PostGIS connection-point query failed (%s)", type(exc).__name__)
        raise DatabaseError(str(exc)) from exc

    if row is None:
        raise NoSegmentFound("No eligible mufa or reserva found")
    result = _connection_point_from_row(row)
    log.info("Connection point id=%s tipo=%s nombre=%s at %.1f m", result.id, result.tipo,
             result.nombre, result.distance_m)
    return result


def find_mufas_near_route(
    route_linestring_wkt: str,
    buffer_m: float,
    excluded_keywords: list[str],
    excluded_names: tuple[str | None, str | None] | None = None,
) -> list[RouteMufa]:
    """Return valid mufas near the actual street route, classified by backbone proximity."""
    if buffer_m < 0:
        raise ValueError("buffer_m must be >= 0")
    s = get_settings()
    patterns = [f"%{keyword}%" for keyword in excluded_keywords]
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            rows = conn.execute(
                _ROUTE_MUFAS_SQL,
                {"route_wkt": route_linestring_wkt, "buffer_m": buffer_m,
                 "excluded": patterns, **_nombres(excluded_names)},
            ).fetchall()
    except psycopg.Error as exc:
        log.error("Route mufa query failed (%s)", type(exc).__name__)
        raise ExistingPolesQueryError(str(exc)) from exc
    return [RouteMufa(id=row[0], tipo=row[1], lat=float(row[2]), lon=float(row[3]),
                      distance_m=float(row[4]), is_backbone=bool(row[5]),
                      nombre=((row[6] or "").strip() or None) if len(row) > 6 else None) for row in rows]


_ROUTE_POZOS_SQL = """
WITH route AS (
    SELECT ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326) AS geom,
           ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326)::geography AS geog
)
SELECT ST_LineLocatePoint(route.geom, p.geom) * ST_Length(route.geog) AS route_position_m
FROM red_puntos p, route
WHERE p.geom IS NOT NULL
  AND p.tipo ILIKE 'pozo%%'
  AND ST_DWithin(p.geom::geography, route.geog, %(buffer_m)s)
ORDER BY route_position_m
"""


def find_pozos_near_route(route_linestring_wkt: str, buffer_m: float) -> list[float]:
    """Positions (metres from the start of the route) of the wells (pozos) within `buffer_m` of the route, sorted."""
    if buffer_m < 0:
        raise ValueError("buffer_m must be >= 0")
    s = get_settings()
    try:
        with psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password, connect_timeout=5) as conn:
            rows = conn.execute(_ROUTE_POZOS_SQL, {"route_wkt": route_linestring_wkt, "buffer_m": buffer_m}).fetchall()
    except psycopg.Error as exc:
        log.error("Route wells query failed (%s)", type(exc).__name__)
        raise ExistingPolesQueryError(str(exc)) from exc
    return [float(row[0]) for row in rows]


_RESERVAS_SQL = """
WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS g)
SELECT p.id, p.tipo, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon, ST_Distance(p.geom::geography, pt.g::geography) AS dist_m, p.nombre
FROM red_puntos p, pt
WHERE p.geom IS NOT NULL
  AND ST_DWithin(p.geom::geography, pt.g::geography, %(radius_m)s)
  AND (p.tipo ILIKE 'reserva%%' OR coalesce(p.nombre, '') ~* %(palabras)s)
  AND NOT (p.tipo ILIKE ANY(%(excluded)s))
ORDER BY p.geom <-> pt.g
LIMIT %(limit)s
"""


def find_reservas_cercanas(lat: float, lon: float, radius_m: float, palabras_regex: str, excluded_keywords: list[str] | None = None,
                           limit: int = 3) -> list[Segment]:
    """The reservas nearest to a point: points of the folder «reserva» and poles / points whose name says RSV, RVA or RESERVA
    (`palabras_regex`: reglas_mufas.regex_palabras). Nearest first. Where a splitter can be installed in a new mufa."""
    s = get_settings()
    try:
        with psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password, connect_timeout=5) as conn:
            rows = conn.execute(_RESERVAS_SQL, {"lat": lat, "lon": lon, "radius_m": radius_m, "palabras": palabras_regex, "limit": int(limit),
                                                "excluded": [f"%{k}%" for k in (excluded_keywords or [])] or ["%sin-coincidencia-posible%"]}).fetchall()
    except psycopg.Error as exc:
        log.error("PostGIS reservas query failed (%s)", type(exc).__name__)
        raise DatabaseError(str(exc)) from exc
    return [Segment(id=r[0], tipo=r[1], lat=float(r[2]), lon=float(r[3]), distance_m=float(r[4]), is_mufa=False, is_reserve=True,
                    nombre=(r[5] or "").strip() or None) for r in rows]


def find_existing_poles_near_route(route_linestring_wkt: str, buffer_m: float) -> list[ExistingPole]:
    """Return existing poles near a route, ordered by distance along the route.

    The route WKT must use SRID 4326 coordinates. PostGIS projects every pole
    onto the route and converts its fractional position to real meters using
    geography length, so the caller can calculate each gap accurately.
    """
    if buffer_m < 0:
        raise ValueError("buffer_m must be >= 0")
    sql = """
    WITH route AS (
                SELECT ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326) AS geom,
                             ST_SetSRID(ST_GeomFromText(%(route_wkt)s), 4326)::geography AS geog
    )
        SELECT DISTINCT p.id,
            ST_Y(p.geom) AS lat,
            ST_X(p.geom) AS lon,
            ST_LineLocatePoint(route.geom, p.geom) * ST_Length(route.geog) AS route_position_m
    FROM red_puntos p, route
    WHERE p.geom IS NOT NULL
    AND (p.tipo ILIKE 'poste%%' OR p.tipo ILIKE 'reserva%%')
            AND ST_DWithin(p.geom::geography, route.geog, %(buffer_m)s)
        ORDER BY route_position_m, p.id
    """
    s = get_settings()
    try:
        with psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name,
            user=s.db_user, password=s.db_password, connect_timeout=5,
        ) as conn:
            rows = conn.execute(sql, {"route_wkt": route_linestring_wkt, "buffer_m": buffer_m}).fetchall()
    except psycopg.Error as exc:
        log.error("Existing-pole PostGIS query failed (%s)", type(exc).__name__)
        raise ExistingPolesQueryError(str(exc)) from exc
    return [ExistingPole(id=row[0], lat=float(row[1]), lon=float(row[2]),
                         route_position_m=float(row[3])) for row in rows]
