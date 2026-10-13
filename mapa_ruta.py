"""Satellite image of the recommended route (connection point -> client) for the Excel budget.

Esri World Imagery tiles, with Esri's transportation labels on top, drawn with staticmap
(tile download) and Pillow (route, icons, legend). Any failure returns None: a budget
never fails because of the map.
"""
import logging
import math
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image, ImageDraw, ImageFont
from staticmap import StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

log = logging.getLogger(__name__)

IMAGERY_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
LABELS_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/"
              "World_Transportation/MapServer/tile/{z}/{y}/{x}")
USER_AGENT = "IDEAY-fiber-budget/1.0 (presupuestos FO)"
# Same proportions as the template's "ESQUEMA DE RUTA PROYECTADA" box (691 x 590 px on screen),
# rendered larger so Excel only scales it down into the box.
SIZE = (1000, 854)
PADDING_PX = 60
MAX_ZOOM = 19              # Esri has zoom 19 in Managua; elsewhere it falls back to 18
ALWAYS_AVAILABLE_ZOOM = 18
TILE_SIZE = 256

ROUTE_COLOR, ROUTE_APPROX_COLOR, ROUTE_EDGE = (255, 221, 0), (255, 140, 0), (0, 0, 0)
ORIGIN_COLOR, CLIENT_COLOR = (0, 200, 70), (230, 30, 30)
ALTERNATIVE_COLOR, POLE_COLOR = (40, 120, 255), (255, 255, 255)
DROP_COLOR = (0, 230, 90)   # last street point of the route -> the client's coordinate
DROP_MIN_M = 1.0            # closer than this the route already reaches the client
HALO, OUTLINE = (255, 255, 255), (0, 0, 0)

LatLon = tuple[float, float]
Draw = ImageDraw.ImageDraw


def _font(size: int) -> Any:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _distance_m(a: LatLon, b: LatLon) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _zoom_for(points: list[LatLon], width: int, height: int, max_zoom: int) -> int:
    """Highest zoom (<= max_zoom) at which every point fits inside the padded canvas."""
    for zoom in range(max_zoom, -1, -1):
        xs = [_lon_to_x(lon, zoom) * TILE_SIZE for _, lon in points]
        ys = [_lat_to_y(lat, zoom) * TILE_SIZE for lat, _ in points]
        if max(xs) - min(xs) <= width - 2 * PADDING_PX and max(ys) - min(ys) <= height - 2 * PADDING_PX:
            return zoom
    return 0


# --- icons (x, y = the point on the map; s = half size in px) ---------------------------------

def _edge(s: float) -> int:
    """Border width in proportion to the icon (thin in the legend, bold on the map)."""
    return max(1, round(s / 7))


def _mufa_icon(draw: Draw, x: float, y: float, s: float, fill: tuple) -> None:
    """Bow tie, the mufa symbol of the Visio diagrams."""
    for side in (-1, 1):
        triangle = [(x + side * s, y - 0.75 * s), (x, y), (x + side * s, y + 0.75 * s)]
        draw.polygon(triangle, fill=fill, outline=HALO if s > 12 else OUTLINE, width=_edge(s))
    dot = max(1.5, s / 7)
    draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=OUTLINE)


def _pole_icon(draw: Draw, x: float, y: float, s: float) -> None:
    """Utility pole: post with a cross-arm."""
    edge = 2 if s > 12 else 1
    draw.rectangle((x - 0.2 * s, y - s, x + 0.2 * s, y + s), fill=POLE_COLOR, outline=OUTLINE, width=edge)
    draw.rectangle((x - 0.75 * s, y - 0.8 * s, x + 0.75 * s, y - 0.45 * s), fill=POLE_COLOR, outline=OUTLINE,
                   width=edge)


def _house_icon(draw: Draw, x: float, y: float, s: float, fill: tuple) -> None:
    """Client's house, its base on the point."""
    edge, halo = _edge(s), HALO if s > 12 else OUTLINE
    body = (x - 0.7 * s, y - 1.1 * s, x + 0.7 * s, y)
    roof = [(x - s, y - 1.05 * s), (x, y - 2 * s), (x + s, y - 1.05 * s)]
    draw.polygon(roof, fill=fill, outline=halo, width=edge)
    draw.rectangle(body, fill=fill, outline=halo, width=edge)
    draw.rectangle((x - 0.2 * s, y - 0.6 * s, x + 0.2 * s, y - edge), fill=HALO)


def _line_icon(color: tuple) -> Callable[[Draw, float, float], None]:
    def icon(draw: Draw, x: float, y: float) -> None:
        draw.line((x - 9, y, x + 9, y), fill=ROUTE_EDGE, width=8)
        draw.line((x - 8, y, x + 8, y), fill=color, width=4)
    return icon


class _TileLayer(StaticMap):
    """staticmap's tile download (timeout, retries) onto a canvas we already positioned."""

    def get(self, url: str, **kwargs: Any) -> tuple[int, bytes]:
        response = _session.get(url, **kwargs)
        return response.status_code, response.content

    def draw(self, image: Image.Image, zoom: int, x_center: float, y_center: float) -> None:
        self.zoom, self.x_center, self.y_center = zoom, x_center, y_center
        self._draw_base_layer(image)


_session = requests.Session()   # one keep-alive connection for all tiles (a TLS handshake each is slow)


def _tiles(url: str, zoom: int, x_center: float, y_center: float, timeout_s: float) -> Image.Image:
    width, height = SIZE
    layer = _TileLayer(width, height, url_template=url, tile_request_timeout=timeout_s,
                       headers={"User-Agent": USER_AGENT})
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    layer.draw(image, zoom, x_center, y_center)
    return image


def _has_imagery(url: str, zoom: int, lat: float, lon: float, timeout_s: float) -> bool:
    """False when Esri answers with its flat "Map data not yet available" tile at this zoom."""
    from io import BytesIO
    response = _session.get(url.format(z=zoom, x=int(_lon_to_x(lon, zoom)), y=int(_lat_to_y(lat, zoom))),
                            timeout=timeout_s, headers={"User-Agent": USER_AGENT})
    if response.status_code != 200:
        return False
    colors = Image.open(BytesIO(response.content)).convert("RGB").getcolors(maxcolors=512)
    return colors is None          # more than 512 colours: a photo, not the placeholder


def generar_mapa_ruta(
    ruta_puntos: list[LatLon],
    origen: dict[str, Any],
    cliente: dict[str, Any],
    alternativas: list[dict[str, Any]],
    ruta_aproximada: bool,
    salida_png: Path,
    *,
    postes: list[LatLon] = (),
    distancia_ruta_m: float | None = None,
    imagery_url: str | None = None,
    labels_url: str | None = None,
    timeout_s: float = 10,
    max_zoom: int = MAX_ZOOM,
) -> Path | None:
    """Draw the route and save the PNG; None (logged) when tiles cannot be downloaded.

    origen / cliente: {"nombre", "lat", "lon"}; alternativas: up to 4 nodes {"nombre", "lat", "lon"}.
    Tile URLs default to IMAGERY_URL / LABELS_URL (read at call time).
    """
    imagery_url = imagery_url or IMAGERY_URL
    labels_url = labels_url if labels_url is not None else LABELS_URL
    try:
        width, height = SIZE
        alternativas = [a for a in alternativas if a.get("lat") is not None][:4]
        route = list(ruta_puntos) or [(origen["lat"], origen["lon"]), (cliente["lat"], cliente["lon"])]
        # The zoom frames the route itself; nearby network nodes are drawn only if they fall inside.
        frame = route + [(origen["lat"], origen["lon"]), (cliente["lat"], cliente["lon"])] + list(postes)
        lats, lons = [p[0] for p in frame], [p[1] for p in frame]
        zoom = _zoom_for(frame, width, height, max_zoom)
        center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
        while zoom > ALWAYS_AVAILABLE_ZOOM and not _has_imagery(imagery_url, zoom, *center, timeout_s):
            zoom -= 1
        x_center = (_lon_to_x(min(lons), zoom) + _lon_to_x(max(lons), zoom)) / 2
        y_center = (_lat_to_y(max(lats), zoom) + _lat_to_y(min(lats), zoom)) / 2

        canvas = Image.new("RGBA", SIZE, (40, 40, 40, 255))
        canvas.alpha_composite(_tiles(imagery_url, zoom, x_center, y_center, timeout_s))
        if labels_url:
            try:   # street labels are a nice-to-have: the satellite image alone is enough
                canvas.alpha_composite(_tiles(labels_url, zoom, x_center, y_center, timeout_s))
            except Exception as exc:
                log.warning("Map street-label tiles unavailable (%s); satellite only", exc)

        def px(point: LatLon) -> tuple[float, float]:
            return ((_lon_to_x(point[1], zoom) - x_center) * TILE_SIZE + width / 2,
                    (_lat_to_y(point[0], zoom) - y_center) * TILE_SIZE + height / 2)

        draw = ImageDraw.Draw(canvas)
        line = [px(p) for p in route]
        draw.line(line, fill=ROUTE_EDGE, width=10, joint="curve")
        draw.line(line, fill=ROUTE_APPROX_COLOR if ruta_aproximada else ROUTE_COLOR, width=6, joint="curve")
        # Drop to the client: the street route ends where Google snaps it to the road.
        client_point = (cliente["lat"], cliente["lon"])
        drop_m = _distance_m(route[-1], client_point)
        if drop_m >= DROP_MIN_M:
            drop = [px(route[-1]), px(client_point)]
            draw.line(drop, fill=ROUTE_EDGE, width=9)
            draw.line(drop, fill=DROP_COLOR, width=5)

        for pole in postes:
            _pole_icon(draw, *px(pole), 13)
        for alternativa in alternativas:
            _mufa_icon(draw, *px((alternativa["lat"], alternativa["lon"])), 14, ALTERNATIVE_COLOR)
        _mufa_icon(draw, *px((origen["lat"], origen["lon"])), 22, ORIGIN_COLOR)
        _house_icon(draw, *px(client_point), 18, CLIENT_COLOR)

        route_color = ROUTE_APPROX_COLOR if ruta_aproximada else ROUTE_COLOR
        _legend(canvas, [
            (lambda d, x, y: _mufa_icon(d, x, y, 10, ORIGIN_COLOR),
             f"Mufa de conexión: {origen.get('nombre') or 'sin nombre'}"),
            (lambda d, x, y: _house_icon(d, x, y + 9, 8, CLIENT_COLOR), f"Cliente: {cliente.get('nombre') or ''}"),
            (_line_icon(route_color),
             f"Ruta: {distancia_ruta_m:,.0f} m" if distancia_ruta_m is not None else "Ruta"),
            *([(_line_icon(DROP_COLOR), f"Acometida al cliente: {drop_m:,.0f} m")] if drop_m >= DROP_MIN_M else []),
            *([(_line_icon(ROUTE_APPROX_COLOR), "Ruta aproximada (línea recta)")] if ruta_aproximada else []),
            *([(lambda d, x, y: _mufa_icon(d, x, y, 8, ALTERNATIVE_COLOR), "Otras mufas / nodos de la red")]
              if alternativas else []),
            *([(lambda d, x, y: _pole_icon(d, x, y, 9), "Postes existentes")] if postes else []),
            (None, "Imagen: Esri World Imagery"),
        ])
        salida_png.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(salida_png, "PNG", optimize=True)
        log.info("Route map saved: %s (zoom %d)", salida_png, zoom)
        return salida_png
    except Exception as exc:
        log.error("Route map not generated (%s: %s)", type(exc).__name__, str(exc)[:300])
        return None


def _legend(canvas: Image.Image, rows: list[tuple[Callable[[Draw, float, float], None] | None, str]]) -> None:
    """Legend box in the bottom-left corner on a semi-transparent white background."""
    # Sizes for the 1000 px canvas, which Excel shows at ~691 px (text ~13 px on screen).
    font, small = _font(19), _font(15)
    line_h, pad, icon_w = 28, 11, 24
    measure = ImageDraw.Draw(canvas)
    text_w = max(measure.textlength(text, font=small if icon is None else font) for icon, text in rows)
    box_w, box_h = int(text_w + icon_w + 3 * pad), line_h * len(rows) + 2 * pad
    x0, y0 = 12, canvas.height - box_h - 12
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=8,
                                              fill=(255, 255, 255, 215))
    canvas.alpha_composite(overlay)
    draw = ImageDraw.Draw(canvas)
    for i, (icon, text) in enumerate(rows):
        y = y0 + pad + i * line_h
        if icon is not None:
            icon(draw, x0 + pad + icon_w / 2, y + line_h / 2 - 1)
        draw.text((x0 + 2 * pad + icon_w, y + (4 if icon is None else 2)), text,
                  fill=(60, 60, 60) if icon is None else (0, 0, 0), font=small if icon is None else font)
