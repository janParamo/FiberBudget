"""Genera visor_rutas/web/tema_oscuro.css: la versión oscura de los colores escritos a mano en las hojas de estilo del visor.

Las hojas (visor.css, redes/redes.css, lugares/mis_lugares.css, tema.css) tienen muchos colores fijos (fondos blancos, textos oscuros, pastillas pastel). En vez de
reescribir cada regla, este programa las lee y, por cada declaración de color clara u oscura, escribe la misma regla bajo `body.tema-oscuro` con el color pasado
al tema oscuro (se invierte la luminosidad y se conserva el tono; los grises toman el azul marino del menú). Lo que ya es oscuro (menú, barra inferior, avisos del
mapa), los colores de acento (botones, alertas) y los textos claros se dejan como están.

Las variables (`--fondo`, `--texto`…) y los ajustes finos del tema oscuro están en tema.css (bloque «tema oscuro»), que se carga después y manda.

Correr después de cambiar colores en esas hojas:

    python herramientas/generar_tema_oscuro.py
"""
import colorsys
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "visor_rutas" / "web"
HOJAS = ["visor.css", "redes/redes.css", "lugares/mis_lugares.css", "tema.css"]
SALIDA = WEB / "tema_oscuro.css"
PREFIJO = "body.tema-oscuro"
MARCA_INICIO, MARCA_FIN = "/* <tema-oscuro> */", "/* </tema-oscuro> */"       # in tema.css: what is already written for the dark theme (not read here)

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^()]*\)|\bwhite\b|\bblack\b")
PROPIEDADES_FONDO = ("background", "background-color", "background-image")
PROPIEDADES_BORDE = ("border", "border-color", "border-top", "border-right", "border-bottom", "border-left", "border-top-color", "border-right-color",
                     "border-bottom-color", "border-left-color", "outline", "outline-color")
PROPIEDADES_TEXTO = ("color", "fill", "stroke")
# never touched: what is drawn over the map or the diagrams (their colours mean something there) and the pieces that are dark in both themes
SIN_TOCAR = re.compile(r"\.etiqueta|\.leaflet-|\.icono|\.cluster-|\.tooltip-|\.anillo-|\.kc-pin|\.ms-num|\.campo-marca|\.er-problema|\.menu-lateral|\.menu-item|\.menu-pie|"
                       r"\.menu-plegar|\.menu-insignia|\.menu-separador|\.barra\b|\.barra-|\.bh-|\.paleta|\.medir-ayuda|\.ml-ayuda|\.er-ayuda|\.aviso-captura|\.lg-foto-grande|"
                       r"\.hoja-excel|\.diagrama-lienzo|\.dg-lienzo|table\.xl|\.vista-icono|\.avatar|\.estado-modo|kbd|\.pr-cabecera|\.muestra|\.lg-muestra|\.lg-color|\.sup-punto|\.mu-leyenda|\.dg-bus-mufa")


def _rgba(texto: str) -> tuple[float, float, float, float] | None:
    t = texto.strip().lower()
    if t == "white":
        return 1, 1, 1, 1
    if t == "black":
        return 0, 0, 0, 1
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        v = [int(h[i:i + 2], 16) / 255 for i in range(0, len(h), 2)]
        return v[0], v[1], v[2], (v[3] if len(v) == 4 else 1)
    partes = [p for p in re.split(r"[,\s/]+", t[t.index("(") + 1:-1].strip()) if p]
    if len(partes) < 3:
        return None
    try:
        r, g, b = (float(p.rstrip("%")) * (2.55 if p.endswith("%") else 1) / 255 for p in partes[:3])
        a = float(partes[3].rstrip("%")) / (100 if partes[3].endswith("%") else 1) if len(partes) > 3 else 1
    except ValueError:
        return None
    return r, g, b, a


def _texto(r: float, g: float, b: float, a: float) -> str:
    r, g, b = (max(0, min(255, round(c * 255))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}" if a >= 0.999 else f"rgba({r}, {g}, {b}, {round(a, 2)})"


def oscuro(color: str, uso: str) -> str | None:
    """The colour for the dark theme, or None when it stays (`uso`: fondo | borde | texto)."""
    c = _rgba(color)
    if c is None:
        return None
    r, g, b, a = c
    if a < 0.5:                                              # veils and soft shadows: the same in both themes
        return None
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if uso == "texto" and l > 0.6:                           # light text is over something dark or coloured already
        return None
    if uso != "texto" and 0.32 <= l <= 0.68 and s >= 0.35:   # an accent (a button, an alert, a mark): the same
        return None
    if uso == "fondo" and l < 0.32:                          # dark surfaces are dark already
        return None
    if uso == "borde" and l < 0.45:                          # dark outlines (of a swatch, of a mark) are kept
        return None
    l2 = 0.115 + (1 - l) * 0.80 if uso != "texto" else 0.22 + (1 - l) * 0.72
    if s < 0.18:                                             # greys take the navy of the menu
        h, s2 = 222 / 360, (0.24 if l2 < 0.5 else 0.20)
    else:
        s2 = min(s, 0.62 if l2 < 0.5 else 0.85)
    return _texto(*colorsys.hls_to_rgb(h, l2, s2), a)


def _reglas(css: str):
    """(media | None, selector, cuerpo) of each rule; one level of @media, no @keyframes."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    i, n, media = 0, len(css), None
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        cierre = css.find("}", i)
        if media is not None and 0 <= cierre < j:            # the @media block ends
            media, i = None, cierre + 1
            continue
        cabeza = css[i:j].strip()
        if cabeza.startswith("@media") or cabeza.startswith("@supports"):
            media, i = cabeza, j + 1
            continue
        if cabeza.startswith("@"):                           # @keyframes and the like: skipped whole
            nivel, k = 1, j + 1
            while k < n and nivel:
                nivel += {"{": 1, "}": -1}.get(css[k], 0)
                k += 1
            i = k
            continue
        k = css.find("}", j)
        if k < 0:
            break
        yield media, cabeza, css[j + 1:k]
        i = k + 1


def _selectores(lista: str) -> list[str]:
    partes, nivel, actual = [], 0, ""
    for ch in lista:
        nivel += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and nivel == 0:
            partes.append(actual.strip())
            actual = ""
        else:
            actual += ch
    return [p for p in partes + [actual.strip()] if p]


def _con_prefijo(selector: str) -> str | None:
    if selector.startswith((":root", "html", "*")) or SIN_TOCAR.search(selector):
        return None
    if selector.startswith("body"):
        return PREFIJO + selector[4:]
    return f"{PREFIJO} {selector}"


def _declaraciones(cuerpo: str) -> list[str]:
    salida = []
    for decl in re.split(r";(?![^()]*\))", cuerpo):
        if ":" not in decl:
            continue
        prop, valor = (x.strip() for x in decl.split(":", 1))
        prop = prop.lower()
        uso = "fondo" if prop in PROPIEDADES_FONDO else "borde" if prop in PROPIEDADES_BORDE else "texto" if prop in PROPIEDADES_TEXTO else None
        if uso is None or "url(" in valor:
            continue
        cambio = False

        def reemplazo(m: re.Match) -> str:
            nonlocal cambio
            nuevo = oscuro(m.group(0), uso)
            if nuevo is None:
                return m.group(0)
            cambio = True
            return nuevo

        nuevo_valor = COLOR.sub(reemplazo, valor)
        if cambio:
            salida.append(f"{prop}: {nuevo_valor}")
    return salida


def generar() -> str:
    lineas = ["/* GENERADO por herramientas/generar_tema_oscuro.py: no editar a mano (los ajustes del tema oscuro van en tema.css). */"]
    for hoja in HOJAS:
        css = (WEB / hoja).read_text(encoding="utf-8")
        if MARCA_INICIO in css:
            css = css[:css.index(MARCA_INICIO)] + css[css.index(MARCA_FIN) + len(MARCA_FIN):]
        lineas.append(f"\n/* ---- {hoja} */")
        media_abierta = None
        for media, selector, cuerpo in _reglas(css):
            decls = _declaraciones(cuerpo)
            sels = [s for s in (_con_prefijo(x) for x in _selectores(selector)) if s]
            if not decls or not sels:
                continue
            if media != media_abierta:
                if media_abierta:
                    lineas.append("}")
                if media:
                    lineas.append(media + " {")
                media_abierta = media
            lineas.append(f"{', '.join(sels)} {{ {'; '.join(decls)}; }}")
        if media_abierta:
            lineas.append("}")
    return "\n".join(lineas) + "\n"


if __name__ == "__main__":
    texto = generar()
    SALIDA.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{SALIDA.relative_to(WEB.parents[1])}: {texto.count('{')} reglas")
