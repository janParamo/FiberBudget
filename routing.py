"""Google Directions API client (plain REST via requests)."""
import logging
from dataclasses import dataclass

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


def get_route(origin: tuple[float, float], destination: tuple[float, float]) -> Route:
    """Get the driving route origin -> destination following streets.

    Both arguments are (latitude, longitude) tuples. COORDINATE ORDER: the
    Directions API expects the string "lat,lng" (latitude first, the opposite
    of PostGIS ST_MakePoint). Origin = connection point on the network,
    destination = client.
    """
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "mode": "driving",
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

    log.info("Route: %.0f m, %.0f s, %d points", distance_m, duration_s, len(points))
    return Route(distance_m=distance_m, duration_s=duration_s, points=points)
