"""Satellite image of the recommended route (connection point -> client) for the Excel budget.

Esri World Imagery tiles drawn with staticmap (tile download) and Pillow (route, pins and dots, like the example of 2026-10-28: green pin at the
connection mufa, red pin at the client with the word Cliente and its coordinate, white dots for existing poles, grey dots for new ones; no legend). Any failure returns None:
a budget never fails because of the map.
"""
import logging
import math
from pathlib import Path
from typing import Any

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

# The colours and the thickness of the route are those of the viewer's own route (visor.js: yellow #FFD400 weight 7 over a #1a1a1a border of weight 11 at 85 %), scaled by
# 1000 / 691 because Excel shows this picture at about 691 px: so the line looks in the Excel as thick as in the viewer.
ROUTE_COLOR, ROUTE_APPROX_COLOR, ROUTE_EDGE = (255, 212, 0), (255, 140, 0), (26, 26, 26)
ROUTE_WIDTH, ROUTE_EDGE_WIDTH, ROUTE_EDGE_ALPHA = 10, 16, 217
ORIGIN_COLOR, CLIENT_COLOR = (0, 200, 70), (230, 30, 30)          # the connection mufa (green pin) and the client (red pin)
ORIGIN_TEXT_COLOR = (0, 170, 60)
POLE_COLOR, NEW_POLE_COLOR = (255, 255, 255), (154, 154, 154)       # existing poles (white dots) and new ones (grey dots)
PIN_R = 20                  # radius of the head of the pins (px of the 1000 px picture)
DROP_COLOR = (0, 230, 90)      # last street point of the route -> the client's coordinate: a dotted green line, as the viewer's acometida
DROP_DASH, DROP_GAP = 18, 14   # px of line / px of gap
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


# --- markers (x, y = the point on the map) -----------------------------------------------------

def _dashed(draw, a, b, fill, width):
    """Dashed straight line from a to b (DROP_DASH px on, DROP_GAP px off)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    pos = 0.0
    while pos < length:
        end = min(pos + DROP_DASH, length)
        draw.line([(a[0] + ux * pos, a[1] + uy * pos), (a[0] + ux * end, a[1] + uy * end)], fill=fill, width=width)
        pos += DROP_DASH + DROP_GAP


def _pin(draw: Draw, x: float, y: float, r: float, fill: tuple) -> None:
    """Map pin (teardrop): its tip on the point, the round head above it with a white hole."""
    cy = y - 2.1 * r
    tangent = math.asin(r / (2.1 * r))
    dx = r * math.cos(tangent)
    dy = r * math.sin(tangent)
    draw.polygon([(x - dx, cy + dy), (x + dx, cy + dy), (x, y)], fill=fill, outline=OUTLINE, width=2)
    draw.ellipse((x - r, cy - r, x + r, cy + r), fill=fill, outline=OUTLINE, width=3)
    draw.polygon([(x - dx + 2, cy + dy - 1), (x + dx - 2, cy + dy - 1), (x, y - 3)], fill=fill)      # hides the join between head and tip
    hole = 0.42 * r
    draw.ellipse((x - hole, cy - hole, x + hole, cy + hole), fill=HALO, outline=OUTLINE, width=1)


def _label(draw: Draw, canvas_width: int, x: float, y: float, text: str, fill: tuple, halo: tuple, size: int, side: str = "right") -> None:
    """Text with a thick halo (readable over a satellite image), to the right / left of the point or centred on it; kept inside the picture."""
    font = _font(size)
    width = draw.textlength(text, font=font)
    left = x if side == "right" else x - width if side == "left" else x - width / 2
    left = max(6.0, min(left, canvas_width - width - 6))
    draw.text((left, y), text, font=font, fill=fill, stroke_width=3, stroke_fill=halo, anchor="lm")


def _dot(draw: Draw, x: float, y: float, fill: tuple, r: float = 8) -> None:
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=OUTLINE, width=2)


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
    postes_nuevos: list[LatLon] = (),
    distancia_ruta_m: float | None = None,
    imagery_url: str | None = None,
    labels_url: str | None = None,
    timeout_s: float = 10,
    max_zoom: int = MAX_ZOOM,
) -> Path | None:
    """Draw the route and save the PNG; None (logged) when tiles cannot be downloaded.

    The picture of the budget: satellite imagery, the route in yellow, a green pin at the connection mufa (with its name), a yellow pin at the client (with the
    coordinate), white dots for the poles that already stand and grey dots for the new ones. No legend, no other mufas (`alternativas` is kept for the callers
    and ignored). origen / cliente: {"nombre", "lat", "lon"}. The imagery URL defaults to IMAGERY_URL (read at call time); street labels only if `labels_url` is given.
    """
    imagery_url = imagery_url or IMAGERY_URL
    labels_url = labels_url or ""
    try:
        width, height = SIZE
        route = list(ruta_puntos) or [(origen["lat"], origen["lon"]), (cliente["lat"], cliente["lon"])]
        # The zoom frames the route itself; nearby network nodes are drawn only if they fall inside.
        frame = route + [(origen["lat"], origen["lon"]), (cliente["lat"], cliente["lon"])] + list(postes) + list(postes_nuevos)
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

        line = [px(p) for p in route]
        border = Image.new("RGBA", canvas.size, (0, 0, 0, 0))                  # the dark border is semi-transparent, as in the viewer
        border_draw = ImageDraw.Draw(border)
        border_draw.line(line, fill=ROUTE_EDGE + (ROUTE_EDGE_ALPHA,), width=ROUTE_EDGE_WIDTH, joint="curve")
        for x, y in (line[0], line[-1]):                                       # round ends
            border_draw.ellipse((x - ROUTE_EDGE_WIDTH / 2, y - ROUTE_EDGE_WIDTH / 2, x + ROUTE_EDGE_WIDTH / 2, y + ROUTE_EDGE_WIDTH / 2), fill=ROUTE_EDGE + (ROUTE_EDGE_ALPHA,))
        canvas.alpha_composite(border)
        draw = ImageDraw.Draw(canvas)
        route_color = ROUTE_APPROX_COLOR if ruta_aproximada else ROUTE_COLOR
        draw.line(line, fill=route_color, width=ROUTE_WIDTH, joint="curve")
        for x, y in (line[0], line[-1]):
            draw.ellipse((x - ROUTE_WIDTH / 2, y - ROUTE_WIDTH / 2, x + ROUTE_WIDTH / 2, y + ROUTE_WIDTH / 2), fill=route_color)
        # Drop to the client: the street route ends where Google snaps it to the road.
        client_point = (cliente["lat"], cliente["lon"])
        drop_m = _distance_m(route[-1], client_point)
        if drop_m >= DROP_MIN_M:
            drop = [px(route[-1]), px(client_point)]
            _dashed(draw, drop[0], drop[1], ROUTE_EDGE, 9)
            _dashed(draw, drop[0], drop[1], DROP_COLOR, 6)

        for pole in postes_nuevos:                      # grey: new poles to install
            _dot(draw, *px(pole), NEW_POLE_COLOR)
        for pole in postes:                             # white: poles that already stand
            _dot(draw, *px(pole), POLE_COLOR)
        mx, my = px((origen["lat"], origen["lon"]))
        cx, cy = px(client_point)
        _pin(draw, mx, my, PIN_R, ORIGIN_COLOR)
        _pin(draw, cx, cy, PIN_R, CLIENT_COLOR)
        if origen.get("nombre"):                         # the name above the mufa's pin, the coordinate beside the client's
            _label(draw, width, mx, my - 2.1 * PIN_R - PIN_R - 20, str(origen["nombre"]), ORIGIN_TEXT_COLOR, HALO, 24, "center")
        _label(draw, width, cx, cy - 2.1 * PIN_R - PIN_R - 20, "Cliente", CLIENT_COLOR, HALO, 24, "center")        # the word above the red pin, the coordinate beside it
        _label(draw, width, cx + PIN_R + 8, cy - 2.1 * PIN_R, f"{client_point[0]:.6f}, {client_point[1]:.6f}", HALO, OUTLINE, 22)
        salida_png.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(salida_png, "PNG", optimize=True)
        log.info("Route map saved: %s (zoom %d)", salida_png, zoom)
        return salida_png
    except Exception as exc:
        log.error("Route map not generated (%s: %s)", type(exc).__name__, str(exc)[:300])
        return None
