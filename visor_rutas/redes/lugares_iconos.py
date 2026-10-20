"""Íconos propios de "Mis lugares" (visor v2, fase 3), sin depender de Google: pushpins de colores, letras A–Z, números 1–10
y figuras. La página los dibuja en SVG (web/lugares/iconos.js, mismo catálogo y mismas formas); aquí se dibujan en PNG para
que el KMZ exportado se vea igual en Google Earth, sin internet.

Un ícono es {"tipo": "pushpin" | "letra" | "numero" | "figura" | "ninguno", "id": "A" | "7" | "estrella" | …, "color": "#rrggbb",
"escala": 1.1, "opacidad": 1.0}. Los pushpins, letras y números son una gota con la punta en el punto; las figuras se centran.
"""
import io
import math
import re
from typing import Any

FIGURAS = ("circulo", "cuadrado", "rombo", "estrella", "triangulo", "cruz", "hexagono", "anillo")
LETRAS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
NUMEROS = tuple(str(n) for n in range(1, 11))
TIPOS_ICONO = ("pushpin", "letra", "numero", "figura", "ninguno", "imagen", "texto")
MAX_IMAGEN = 80_000                      # characters of the data URL: the page shrinks the picture to 96 px before sending it
_IMAGEN = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$")
_TEXTO_PROHIBIDO = set('<>&"\'\\')
COLOR_POR_DEFECTO = "#f7d117"
ICONO_POR_DEFECTO = {"tipo": "pushpin", "id": "pushpin", "color": COLOR_POR_DEFECTO, "escala": 1.1, "opacidad": 1.0}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# Google Earth's own pushpin names, for the files imported from it
PUSHPIN_GOOGLE = {"ylw": "#f7d117", "blue": "#2f6bff", "blu": "#2f6bff", "grn": "#2ca02c", "ltblu": "#1ec8e8", "pink": "#ff6fb5",
                  "purple": "#8e44ad", "red": "#e53935", "wht": "#ffffff", "orange": "#fb8c00"}


def es_gota(icono: dict[str, Any]) -> bool:
    """Drop-shaped icons point with their tip; figures point with their centre."""
    return icono.get("tipo") in ("pushpin", "letra", "numero")


def limpiar_icono(valor: Any) -> dict[str, Any] | None:
    """The icon style with only what is valid (None when it is not a valid icon)."""
    if not isinstance(valor, dict) or valor.get("tipo") not in TIPOS_ICONO:
        return None
    tipo, ident = valor["tipo"], str(valor.get("id") or "")
    if tipo == "letra" and ident not in LETRAS or tipo == "numero" and ident not in NUMEROS or tipo == "figura" and ident not in FIGURAS:
        return None
    datos = None
    if tipo == "imagen":                                       # a picture of the user's own, as a small data URL
        datos = valor.get("datos")
        if not isinstance(datos, str) or len(datos) > MAX_IMAGEN or not _IMAGEN.match(datos):
            return None
        ident = "imagen"
    elif tipo == "texto":                                      # up to three characters (an emoji, "OLT", "5G")
        ident = ident.strip()[:3]
        if not ident or any(c in _TEXTO_PROHIBIDO or ord(c) < 32 for c in ident):
            return None
    color = str(valor.get("color") or COLOR_POR_DEFECTO)
    try:
        escala = min(4.0, max(0.3, float(valor.get("escala", 1.1))))
        opacidad = min(1.0, max(0.0, float(valor.get("opacidad", 1.0))))
    except (TypeError, ValueError):
        return None
    salida = {"tipo": tipo, "id": ident if tipo != "pushpin" else "pushpin", "color": color if _COLOR.match(color) else COLOR_POR_DEFECTO,
              "escala": round(escala, 2), "opacidad": round(opacidad, 2)}
    if datos is not None:
        salida["datos"] = datos
    return salida


def _rgb(color: str) -> tuple[int, int, int]:
    h = (color if _COLOR.match(color or "") else COLOR_POR_DEFECTO).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _oscuro(rgb: tuple[int, int, int]) -> tuple[int, int, int, int]:
    return tuple(int(c * 0.45) for c in rgb) + (255,)           # type: ignore[return-value]


def _gota(d: Any, k: float, relleno: tuple[int, int, int, int], borde: tuple[int, int, int, int]) -> None:
    """The drop of the viewer's icons (viewBox 30 x 42, tip at (15, 41)); k = pixels per unit."""
    d.ellipse((2 * k, 2 * k, 28 * k, 28 * k), fill=relleno, outline=borde, width=max(1, int(1.6 * k)))
    d.polygon([(3.4 * k, 20.5 * k), (26.6 * k, 20.5 * k), (15 * k, 41 * k)], fill=relleno)
    d.line([(3.4 * k, 20.5 * k), (15 * k, 41 * k), (26.6 * k, 20.5 * k)], fill=borde, width=max(1, int(1.6 * k)), joint="curve")
    d.ellipse((3.2 * k, 3.2 * k, 26.8 * k, 26.8 * k), fill=relleno)       # hides the seam between the circle and the cone


def _estrella(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    puntos = []
    for i in range(10):
        radio = r if i % 2 == 0 else r * 0.42
        ang = -math.pi / 2 + i * math.pi / 5
        puntos.append((cx + radio * math.cos(ang), cy + radio * math.sin(ang)))
    return puntos


def icono_png(icono: dict[str, Any], lado: int = 40) -> bytes:
    """PNG (transparent background) of an icon, `lado` px high for a drop and wide/high for a figure."""
    from PIL import Image, ImageDraw, ImageFont
    s = 4                                                     # supersampling: smooth edges
    ic = limpiar_icono(icono) or ICONO_POR_DEFECTO
    rgb = _rgb(ic["color"])
    relleno, borde = rgb + (255,), _oscuro(rgb)
    if ic["tipo"] == "imagen":
        salida = _imagen_png(ic, lado)
    elif es_gota(ic):
        ancho, alto = round(lado * 30 / 42), lado
        k = alto * s / 42
        img = Image.new("RGBA", (int(30 * k), int(42 * k)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        _gota(d, k, relleno, borde)
        if ic["tipo"] == "pushpin":
            d.ellipse((9.5 * k, 9.5 * k, 20.5 * k, 20.5 * k), fill=(255, 255, 255, 255), outline=borde, width=max(1, int(1.2 * k)))
        else:
            try:
                fuente = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", int(15 * k))
            except OSError:
                fuente = ImageFont.load_default(size=int(15 * k))
            claro = (255, 255, 255, 255) if sum(rgb) < 560 else (30, 30, 30, 255)
            d.text((15 * k, 15.5 * k), ic["id"], font=fuente, fill=claro, anchor="mm")
        salida = img.resize((ancho, alto), Image.LANCZOS)
    else:
        img = Image.new("RGBA", (lado * s, lado * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c, r, g = lado * s / 2, lado * s * 0.42, max(2, lado * s // 12)
        f = ic["id"]
        if ic["tipo"] == "texto":
            d.ellipse((c - r, c - r, c + r, c + r), fill=relleno, outline=borde, width=g)
            _texto_en(img, ic["id"], c, int(r * (1.25 if len(ic["id"]) == 1 else 1.0)), rgb)
        elif f == "circulo":
            d.ellipse((c - r, c - r, c + r, c + r), fill=relleno, outline=borde, width=g)
        elif f == "anillo":
            d.ellipse((c - r, c - r, c + r, c + r), outline=relleno, width=g * 2)
        elif f == "cuadrado":
            d.rectangle((c - r * 0.85, c - r * 0.85, c + r * 0.85, c + r * 0.85), fill=relleno, outline=borde, width=g)
        elif f == "rombo":
            d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=relleno, outline=borde, width=g)
        elif f == "triangulo":
            d.polygon([(c, c - r), (c + r, c + r * 0.8), (c - r, c + r * 0.8)], fill=relleno, outline=borde, width=g)
        elif f == "hexagono":
            d.polygon([(c + r * math.cos(math.pi / 3 * i), c + r * math.sin(math.pi / 3 * i)) for i in range(6)], fill=relleno, outline=borde, width=g)
        elif f == "estrella":
            d.polygon(_estrella(c, c, r * 1.1), fill=relleno, outline=borde, width=g)
        elif f == "cruz":
            a = r * 0.3
            d.polygon([(c - a, c - r), (c + a, c - r), (c + a, c - a), (c + r, c - a), (c + r, c + a), (c + a, c + a), (c + a, c + r),
                       (c - a, c + r), (c - a, c + a), (c - r, c + a), (c - r, c - a), (c - a, c - a)], fill=relleno, outline=borde, width=g)
        salida = img.resize((lado, lado), Image.LANCZOS)
    if ic["opacidad"] < 1:
        alfa = salida.getchannel("A").point(lambda v: int(v * ic["opacidad"]))
        salida.putalpha(alfa)
    datos = io.BytesIO()
    salida.save(datos, "PNG")
    return datos.getvalue()


def _imagen_png(ic: dict[str, Any], lado: int) -> Any:
    """The user's picture fitted in a square of `lado` px (transparent around it); a broken picture gives the default pushpin."""
    import base64
    from PIL import Image
    try:
        crudo = base64.b64decode(ic["datos"].split(",", 1)[1], validate=True)
        img = Image.open(io.BytesIO(crudo)).convert("RGBA")
        img.thumbnail((lado, lado), Image.LANCZOS)
    except Exception:                                          # noqa: BLE001 - a bad picture must not stop the export
        return Image.open(io.BytesIO(icono_png(ICONO_POR_DEFECTO, lado))).convert("RGBA")
    lienzo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    lienzo.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2), img)
    return lienzo


def _texto_en(img: Any, texto: str, centro: float, tam: int, rgb: tuple[int, int, int]) -> None:
    """`texto` (letters or an emoji) in the middle of the circle; emoji use Windows' colour emoji font when it is there."""
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(img)
    tam = max(8, tam)
    color = (255, 255, 255, 255) if sum(rgb) < 560 else (30, 30, 30, 255)
    for ruta, a_color in ((r"C:\Windows\Fonts\seguiemj.ttf", True), (r"C:\Windows\Fonts\arialbd.ttf", False)):
        try:
            fuente = ImageFont.truetype(ruta, tam)
            d.text((centro, centro), texto, font=fuente, fill=color, anchor="mm", embedded_color=a_color)
            return
        except (OSError, ValueError):
            continue
    d.text((centro, centro), texto, font=ImageFont.load_default(size=tam), fill=color, anchor="mm")


def clave(icono: dict[str, Any]) -> str:
    """Stable name of an icon (for files and styles): tipo-id-rrggbb (a picture: the start of its hash; a text: its characters in hex)."""
    import hashlib
    ic = limpiar_icono(icono) or ICONO_POR_DEFECTO
    ident = hashlib.sha1(ic["datos"].encode()).hexdigest()[:12] if ic["tipo"] == "imagen" else ic["id"].encode().hex() if ic["tipo"] == "texto" else ic["id"]
    return f"{ic['tipo']}-{ident}-{ic['color'].lstrip('#').lower()}"


def desde_href(href: str | None) -> dict[str, Any] | None:
    """The icon of an imported Google Earth file by the name of its pushpin (ylw-pushpin.png, red-pushpin, blue-pushpin…)."""
    m = re.search(r"/?([a-z]+)-pushpin", (href or "").lower())
    if m and m.group(1) in PUSHPIN_GOOGLE:
        return {**ICONO_POR_DEFECTO, "color": PUSHPIN_GOOGLE[m.group(1)]}
    return None
