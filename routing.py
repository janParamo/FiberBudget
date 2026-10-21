"""Google Directions API client (plain REST via requests)."""
import logging
import math
from dataclasses import dataclass
from typing import Any
from functools import lru_cache
from pathlib import Path

import polyline
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import get_settings

log = logging.getLogger(__name__)

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

# Statuses that are usually temporary -> worth retrying.
_TRANSIENT_STATUSES = {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}


class RoutingError(Exception):
    """Directions API failed (network, quota, denied key, bad request...)."""


class RouteNotFound(Exception):
    """Google could not find a drivable route between the two points."""


class _TransientError(Exception):
    """Internal marker: retry this call."""


@dataclass
class Route:
    distance_m: float
    duration_s: float
    points: list[tuple[float, float]]   # (lat, lon) along the street route
    modo: str = "driving"               # driving | walking | directa (see calibrar)
    aviso: str | None = None            # why the route is not the plain driving one: the viewer / budget show it


# Retry with exponential backoff (1s, 2s, ...) because the Directions API
# occasionally returns 5xx / UNKNOWN_ERROR / rate-limit responses that succeed
# on a second attempt. Permanent errors (REQUEST_DENIED, ZERO_RESULTS) do not retry.
@retry(
    retry=retry_if_exception_type(_TransientError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _call_api(params: dict) -> dict:
    """One HTTP call to Directions; raises _TransientError for retryable failures."""
    try:
        resp = requests.get(
            DIRECTIONS_URL,
            params=params,
            timeout=get_settings().request_timeout_seconds,
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        log.warning("Directions network error (%s)", type(exc).__name__)
        raise _TransientError(str(exc)) from exc
    if resp.status_code >= 500:
        log.warning("Directions HTTP %s", resp.status_code)
        raise _TransientError(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise RoutingError(f"Directions HTTP {resp.status_code}")
    data = resp.json()
    if data.get("status") in _TRANSIENT_STATUSES:
        log.warning("Directions transient status %s", data["status"])
        raise _TransientError(data["status"])
    return data


POR_DEFECTO = {"enabled": True, "detour_factor": 2.0, "min_extra_m": 150, "walking_gain": 0.85, "direct_max_m": 150, "direct_detour_factor": 3.0}


@lru_cache(maxsize=4)
def _calibracion_de(ruta: str, mtime: float) -> dict:
    import yaml
    datos = (yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}).get("route_calibration") or {}
    return {**POR_DEFECTO, **{k: v for k, v in datos.items() if k in POR_DEFECTO}}


def calibracion() -> dict:
    """The `route_calibration` section of business_rules.yaml over the defaults (re-read when the file changes)."""
    try:
        ruta = Path(get_settings().rules_path)
        return _calibracion_de(str(ruta), ruta.stat().st_mtime)
    except Exception:                                                # noqa: BLE001 - the defaults are fine
        return dict(POR_DEFECTO)


def _recta_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line metres between two (lat, lon)."""
    f1, f2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((f2 - f1) / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def calibrar(ruta: Route, origin: tuple[float, float], destination: tuple[float, float], caminando: Any = None,
             cfg: dict | None = None) -> Route:
    """A fibre cable does not need a drivable road. Google's driving route snaps both ends to a street and goes round the block (one-way streets,
    a client on a footpath), so a client 40 m away can come back as 700 m. When the route is longer than `detour_factor` x the straight line
    (and `min_extra_m` more), the WALKING route is asked (paths and footways) and used if it is clearly shorter (`walking_gain`); if the client is
    still close (`direct_max_m`) and the route is `direct_detour_factor` x the straight line, the straight line is used (a drop across the block).
    The reason goes in `aviso`. `caminando(origin, destination)` returns the walking Route or raises (a failure leaves the driving route)."""
    cfg = cfg or calibracion()
    recta = _recta_m(origin, destination)
    if not cfg.get("enabled", True) or ruta.distance_m <= cfg["detour_factor"] * recta + cfg["min_extra_m"]:
        return ruta
    mejor = ruta
    if caminando is not None:
        try:
            a_pie = caminando(origin, destination)
            if a_pie.distance_m < ruta.distance_m * cfg["walking_gain"]:
                mejor = Route(a_pie.distance_m, a_pie.duration_s, a_pie.points, "walking",
                              f"Ruta por calles de Google (en auto) de {ruta.distance_m:.0f} m para {recta:.0f} m en línea recta; se usó el camino a pie "
                              f"({a_pie.distance_m:.0f} m): validar el trazado")
        except (RoutingError, RouteNotFound) as exc:
            log.info("Walking route not available for the calibration (%s)", type(exc).__name__)
    if recta <= cfg["direct_max_m"] and mejor.distance_m > cfg["direct_detour_factor"] * recta + cfg["min_extra_m"]:
        return Route(recta, 0.0, [origin, destination], "directa",
                     f"Google daba {ruta.distance_m:.0f} m por calles para {recta:.0f} m en línea recta; se usó la línea recta (cliente muy cerca): "
                     "validar el trazado en el mapa")
    return mejor


def _pedir(origin: tuple[float, float], destination: tuple[float, float], modo: str) -> Route:
    """One Directions call in `modo` (driving / walking)."""
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "mode": modo,
        "key": get_settings().google_api_key,
    }
    try:
        data = _call_api(params)
    except _TransientError as exc:
        raise RoutingError(f"Directions API unavailable after retries: {exc}") from exc
    except requests.RequestException as exc:
        raise RoutingError(str(exc)) from exc

    status = data.get("status")
    if status == "ZERO_RESULTS" or status == "NOT_FOUND":
        raise RouteNotFound(f"No route found ({status})")
    if status != "OK":
        # Never log the key; the message from Google is safe to log.
        raise RoutingError(f"Directions status {status}")

    route = data["routes"][0]
    legs = route["legs"]
    distance_m = float(sum(leg["distance"]["value"] for leg in legs))
    duration_s = float(sum(leg["duration"]["value"] for leg in legs))

    # Step polylines are more detailed than overview_polyline (better corner detection).
    points: list[tuple[float, float]] = []
    for leg in legs:
        for step in leg["steps"]:
            points.extend(polyline.decode(step["polyline"]["points"]))
    if not points:
        points = polyline.decode(route["overview_polyline"]["points"])

    log.info("Route (%s): %.0f m, %.0f s, %d points", modo, distance_m, duration_s, len(points))
    return Route(distance_m=distance_m, duration_s=duration_s, points=points, modo=modo)


def get_route(origin: tuple[float, float], destination: tuple[float, float]) -> Route:
    """Get the route origin -> destination following streets (driving), calibrated against the straight line (see `calibrar`).

    Both arguments are (latitude, longitude) tuples. COORDINATE ORDER: the
    Directions API expects the string "lat,lng" (latitude first, the opposite
    of PostGIS ST_MakePoint). Origin = connection point on the network,
    destination = client.
    """
    return calibrar(_pedir(origin, destination, "driving"), origin, destination, lambda o, d: _pedir(o, d, "walking"))
