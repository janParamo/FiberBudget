"""El icono de Fiber Budget: un cuadrado azul con el monograma «FB» y un hilo de fibra óptica con su pulso de luz.

Se dibuja con Pillow (sin archivos de imagen de por medio), así que se puede regenerar o ajustar aquí:

    .venv\\Scripts\\python.exe herramientas\\icono_fiber_budget.py            -> visor_rutas\\web\\fiber_budget.ico (el que usan la ventana y el acceso directo)

Lo usa también herramientas\\empaquetar_visor.py para el icono de VisorRutas.exe.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "visor_rutas" / "web" / "fiber_budget.ico"
TAMANOS = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
FUENTES = (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")


def _fuente(tamano: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for ruta in FUENTES:
        try:
            return ImageFont.truetype(ruta, tamano)
        except OSError:
            continue
    return ImageFont.load_default()


def dibujar(lado: int = 256) -> Image.Image:
    """The icon at `lado` pixels (drawn 4 times bigger and shrunk, so the edges are smooth)."""
    g = lado * 4
    imagen = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    # background: rounded square, deep blue to bright blue from the bottom up
    fondo = Image.new("RGBA", (g, g))
    pintor = ImageDraw.Draw(fondo)
    for y in range(g):
        t = y / (g - 1)
        pintor.line([(0, y), (g, y)], fill=(int(8 + 22 * (1 - t)), int(52 + 70 * (1 - t)), int(128 + 107 * (1 - t)), 255))
    mascara = Image.new("L", (g, g), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((g * 0.03, g * 0.03, g * 0.97, g * 0.97), radius=int(g * 0.21), fill=255)
    imagen.paste(fondo, (0, 0), mascara)
    # the fibre: an S curve from the bottom left to the right, with a glow; the pulse of light at its end
    p0, p1, p2, p3 = (0.13, 0.84), (0.38, 0.62), (0.58, 0.96), (0.87, 0.74)           # a smooth cubic curve
    puntos = []
    for i in range(0, 121):
        t = i / 120
        c = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3)
        puntos.append((g * sum(w * p[0] for w, p in zip(c, (p0, p1, p2, p3))), g * sum(w * p[1] for w, p in zip(c, (p0, p1, p2, p3)))))
    brillo = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    ImageDraw.Draw(brillo).line(puntos, fill=(60, 220, 255, 200), width=int(g * 0.075), joint="curve")
    imagen.alpha_composite(brillo.filter(ImageFilter.GaussianBlur(g * 0.03)))
    trazo = ImageDraw.Draw(imagen)
    trazo.line(puntos, fill=(120, 235, 255, 255), width=int(g * 0.035), joint="curve")
    trazo.line(puntos, fill=(235, 252, 255, 255), width=int(g * 0.012), joint="curve")
    x, y = puntos[-1]
    r = g * 0.045
    pulso = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    ImageDraw.Draw(pulso).ellipse((x - r * 1.9, y - r * 1.9, x + r * 1.9, y + r * 1.9), fill=(120, 240, 255, 170))
    imagen.alpha_composite(pulso.filter(ImageFilter.GaussianBlur(g * 0.02)))
    ImageDraw.Draw(imagen).ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 255))
    # the monogram, centred over the fibre
    letra = _fuente(int(g * 0.46))
    caja = trazo.textbbox((0, 0), "FB", font=letra)
    ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    sombra = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    posicion = ((g - ancho) / 2 - caja[0], g * 0.14 - caja[1])
    ImageDraw.Draw(sombra).text((posicion[0], posicion[1] + g * 0.015), "FB", font=letra, fill=(0, 20, 60, 140))
    imagen.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(g * 0.012)))
    ImageDraw.Draw(imagen).text(posicion, "FB", font=letra, fill=(255, 255, 255, 255))
    return imagen.resize((lado, lado), Image.LANCZOS)


def guardar(ruta: Path | str = DESTINO) -> Path:
    """Writes the .ico with every size Windows uses (taskbar, title bar, desktop, Alt+Tab)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    dibujar(256).save(ruta, format="ICO", sizes=TAMANOS)
    return ruta


if __name__ == "__main__":
    destino = guardar(sys.argv[1] if len(sys.argv) > 1 else DESTINO)
    print("Icono guardado en", destino)
