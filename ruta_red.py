"""Routes guided by the fibre lines that already exist in the KMZ (red_lineas).

Google's route follows streets for a car: one-way streets and blocks send a client that is 80 m from a fibre line round three sides of a block.
The fibre goes where the network already goes (the poles are there), so before the budget takes Google's route it is compared with the shortest path
THROUGH the existing lines: from the connection point along the lines of the KMZ, and a drop from the line to the client. When that path is not
clearly longer than Google's (`route_guidance.max_ratio`) it replaces it, and the budget says so. Without lines near, or when the client is too far
from them, nothing changes: Google's route stays.

The lines are joined where they share a vertex or where a vertex of one lies on another within `snap_m` (a T junction drawn without a shared point).
"""
import heapq
import logging
import math
from typing import Any, Callable

import db
import routing

log = logging.getLogger(__name__)

POR_DEFECTO = {
    "enabled": True,
    "max_ratio": 1.10,            # the guided route replaces Google's when it is at most this times as long
    "snap_m": 6.0,                # vertices this close are one point; a vertex this close to another line joins it
    "attach_origin_m": 60.0,      # the connection point must be this close to a line
    "attach_client_m": 80.0,      # the client's drop to the nearest line, at most
    "margin_m": 150.0,            # lines are read this far around the route
    "max_straight_m": 4000.0,     # farther than this (straight line) nothing is guided
    "max_lines": 3000,
}
_M_POR_GRADO = 111320.0

LatLon = tuple[float, float]


def configuracion(rules: dict[str, Any] | None) -> dict[str, Any]:
    return {**POR_DEFECTO, **{k: v for k, v in ((rules or {}).get("route_guidance") or {}).items() if k in POR_DEFECTO}}


class _Plano:
    """Metres on a plane around a point (enough for a few km)."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0, self.k = lat0, lon0, math.cos(math.radians(lat0))

    def xy(self, p: LatLon) -> tuple[float, float]:
        return ((p[1] - self.lon0) * self.k * _M_POR_GRADO, (p[0] - self.lat0) * _M_POR_GRADO)

    def latlon(self, x: float, y: float) -> LatLon:
        return (self.lat0 + y / _M_POR_GRADO, self.lon0 + x / (self.k * _M_POR_GRADO))


def _proyectar(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float, float]:
    """(t, x, y, distance) of the point of segment a-b nearest to (px, py); t in [0, 1] along a -> b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / largo2))
    x, y = a[0] + t * dx, a[1] + t * dy
    return t, x, y, math.hypot(px - x, py - y)


class _Grafo:
    def __init__(self, plano: _Plano, lineas: list[list[LatLon]], snap_m: float):
        self.snap = max(0.5, snap_m)
        self.coords: list[tuple[float, float]] = []
        self.adj: list[list[tuple[int, float, list[tuple[float, float]]]]] = []        # node -> [(node, metres, intermediate points)]
        celdas: dict[tuple[int, int], list[int]] = {}
        self._celdas = celdas
        segmentos: list[tuple[int, int]] = []                                          # (node a, node b)
        for linea in lineas:
            anterior = None
            for p in linea:
                x, y = plano.xy(p)
                n = self._nodo(x, y)
                if anterior is not None and anterior != n:
                    segmentos.append((anterior, n))
                anterior = n
        self.segmentos = segmentos
        self._unir_vertices_con_segmentos()

    def _nodo(self, x: float, y: float) -> int:
        cx, cy = int(x // self.snap), int(y // self.snap)
        for i in range(cx - 1, cx + 2):
            for j in range(cy - 1, cy + 2):
                for n in self._celdas.get((i, j), ()):
                    if math.hypot(self.coords[n][0] - x, self.coords[n][1] - y) <= self.snap:
                        return n
        n = len(self.coords)
        self.coords.append((x, y))
        self.adj.append([])
        self._celdas.setdefault((cx, cy), []).append(n)
        return n

    def _unir_vertices_con_segmentos(self) -> None:
        """Edges of every segment, cut at the vertices of other lines that lie on it (within snap_m)."""
        tam = max(self.snap * 4, 25.0)
        indice: dict[tuple[int, int], list[int]] = {}
        for k, (a, b) in enumerate(self.segmentos):
            (ax, ay), (bx, by) = self.coords[a], self.coords[b]
            for i in range(int(min(ax, bx) // tam) - 0, int(max(ax, bx) // tam) + 1):
                for j in range(int(min(ay, by) // tam) - 0, int(max(ay, by) // tam) + 1):
                    indice.setdefault((i, j), []).append(k)
        cortes: dict[int, list[tuple[float, int]]] = {}
        for n, (x, y) in enumerate(self.coords):
            vistos: set[int] = set()
            for i in (int((x - self.snap) // tam), int((x + self.snap) // tam)):
                for j in (int((y - self.snap) // tam), int((y + self.snap) // tam)):
                    for k in indice.get((i, j), ()):
                        if k in vistos:
                            continue
                        vistos.add(k)
                        a, b = self.segmentos[k]
                        if n in (a, b):
                            continue
                        t, _, _, d = _proyectar(x, y, self.coords[a], self.coords[b])
                        if d <= self.snap and 0.0 < t < 1.0:
                            cortes.setdefault(k, []).append((t, n))
        for k, (a, b) in enumerate(self.segmentos):
            cadena = [a] + [n for _, n in sorted(cortes.get(k, []))] + [b]
            for u, v in zip(cadena, cadena[1:]):
                if u != v:
                    self._arista(u, v, math.hypot(self.coords[u][0] - self.coords[v][0], self.coords[u][1] - self.coords[v][1]), [])

    def _arista(self, u: int, v: int, metros: float, via: list[tuple[float, float]]) -> None:
        self.adj[u].append((v, metros, via))
        self.adj[v].append((u, metros, list(reversed(via))))

    def _mas_cercano(self, x: float, y: float) -> tuple[int, float, float, float] | None:
        """(segment, x, y, distance) of the point of the network nearest to (x, y)."""
        mejor = None
        for k, (a, b) in enumerate(self.segmentos):
            _, px, py, d = _proyectar(x, y, self.coords[a], self.coords[b])
            if mejor is None or d < mejor[3]:
                mejor = (k, px, py, d)
        return mejor

    def anclar(self, punto: tuple[float, float], max_m: float) -> tuple[int, int, float, float, float] | None:
        """Joins a free point (the connection point, the client) to the nearest line: (node, segment, px, py, distance) or None when none is close."""
        cerca = self._mas_cercano(*punto)
        if cerca is None or cerca[3] > max_m:
            return None
        k, px, py, d = cerca
        a, b = self.segmentos[k]
        n = len(self.coords)
        self.coords.append(punto)
        self.adj.append([])
        for extremo in (a, b):
            ex, ey = self.coords[extremo]
            self._arista(n, extremo, d + math.hypot(px - ex, py - ey), [(px, py)])
        return n, k, px, py, d

    def camino(self, desde: int, hasta: int) -> tuple[float, list[tuple[float, float]]] | None:
        dist = {desde: 0.0}
        previo: dict[int, tuple[int, list[tuple[float, float]]]] = {}
        cola = [(0.0, desde)]
        while cola:
            d, u = heapq.heappop(cola)
            if u == hasta:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, m, via in self.adj[u]:
                nd = d + m
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    previo[v] = (u, via)
                    heapq.heappush(cola, (nd, v))
        if hasta not in dist:
            return None
        puntos = [self.coords[hasta]]
        n = hasta
        while n != desde:
            u, via = previo[n]
            puntos.extend(reversed(via))
            puntos.append(self.coords[u])
            n = u
        puntos.reverse()
        return dist[hasta], puntos


def ruta_por_lineas(origen: LatLon, destino: LatLon, lineas: list[list[LatLon]], cfg: dict[str, Any] | None = None) -> tuple[float, list[LatLon]] | None:
    """(metres, points) of the shortest path from `origen` to `destino` through the lines (plus the two drops), or None when the lines do not connect them."""
    cfg = cfg or POR_DEFECTO
    if not lineas:
        return None
    plano = _Plano(origen[0], origen[1])
    grafo = _Grafo(plano, lineas, float(cfg["snap_m"]))
    if not grafo.segmentos:
        return None
    o = grafo.anclar(plano.xy(origen), float(cfg["attach_origin_m"]))
    d = grafo.anclar(plano.xy(destino), float(cfg["attach_client_m"]))
    if o is None or d is None:
        return None
    if o[1] == d[1]:        # both drops land on the same segment: along it, without going through its ends
        (on, _, opx, opy, od), (dn, _, dpx, dpy, dd) = o, d
        grafo._arista(on, dn, od + math.hypot(opx - dpx, opy - dpy) + dd, [(opx, opy), (dpx, dpy)])
    hallado = grafo.camino(o[0], d[0])
    if hallado is None:
        return None
    metros, xy = hallado
    puntos: list[LatLon] = []
    for x, y in xy:
        p = plano.latlon(x, y)
        if not puntos or puntos[-1] != p:
            puntos.append(p)
    puntos[0], puntos[-1] = origen, destino
    return metros, puntos


def mejorar(ruta: routing.Route, origen: LatLon, destino: LatLon, cfg: dict[str, Any],
            lineas_en_caja: Callable[..., list[list[LatLon]]]) -> routing.Route:
    """`ruta` (Google's), or the route through the existing lines when it is not clearly longer."""
    if routing._recta_m(origen, destino) > float(cfg["max_straight_m"]):
        return ruta
    lats = [origen[0], destino[0]] + [p[0] for p in ruta.points]
    lons = [origen[1], destino[1]] + [p[1] for p in ruta.points]
    margen = float(cfg["margin_m"]) / _M_POR_GRADO
    margen_lon = margen / max(0.2, math.cos(math.radians(origen[0])))
    lineas = lineas_en_caja(min(lons) - margen_lon, min(lats) - margen, max(lons) + margen_lon, max(lats) + margen, int(cfg["max_lines"]))
    if len(lineas) >= int(cfg["max_lines"]):          # the box is too full to trust: leave Google's route
        return ruta
    hallado = ruta_por_lineas(origen, destino, lineas, cfg)
    if hallado is None:
        return ruta
    metros, puntos = hallado
    if metros > ruta.distance_m * float(cfg["max_ratio"]):
        return ruta
    log.info("Route guided by the KMZ lines: %.0f m instead of %.0f m (%s)", metros, ruta.distance_m, ruta.modo)
    return routing.Route(distance_m=metros, duration_s=ruta.duration_s, points=puntos, modo="red",
                         aviso=f"Ruta guiada por las líneas de fibra existentes del KMZ: {metros:.0f} m en lugar de los {ruta.distance_m:.0f} m de la ruta "
                               "de calles de Google; validar el trazado")


def con_red_existente(get_route: Callable[..., routing.Route], rules: dict[str, Any] | None) -> Callable[..., routing.Route]:
    """`get_route` (same signature) that answers with the route through the KMZ lines when there is one worth taking. The route the user drew by
    hand (it has `fija`) is never replaced; any failure of the lines leaves Google's route."""
    cfg = configuracion(rules)
    if not cfg["enabled"] or getattr(get_route, "fija", False):
        return get_route

    def guiada(origin: Any = None, destination: Any = None) -> routing.Route:
        ruta = get_route(origin=origin, destination=destination)
        try:
            return mejorar(ruta, tuple(origin), tuple(destination), cfg, db.find_lineas_en_caja)
        except Exception as exc:                                    # noqa: BLE001 - the lines never block a budget
            log.warning("Route guidance failed (%s: %s); Google's route is used", type(exc).__name__, exc)
            return ruta

    return guiada
