"""HTML seguro para las notas con formato (editor Quill de la página).

Se conserva lo que el editor produce (negrita, cursiva, subrayado, tachado, listas, títulos,
saltos de línea, tamaño y tipo de letra de Quill, color y fondo) y se quita todo lo demás:
scripts, eventos on*, estilos que no sean color, enlaces que no sean http(s) / mailto.
"""
import re

from lxml import etree
from lxml import html as lhtml

MAX_HTML = 60_000
_ETIQUETAS = {"p", "br", "strong", "b", "em", "i", "u", "s", "ol", "ul", "li", "h1", "h2", "h3", "span", "a", "div"}
_FUERA = {"script", "style", "iframe", "object", "embed", "form", "input", "button", "link", "meta", "svg", "math",
          "img", "video", "audio", "textarea", "select", "template", "noscript"}
_CLASE_QUILL = re.compile(r"^ql-(size-(small|large|huge)|font-(serif|monospace)|align-(center|right|justify)|indent-[1-8])$")
_COLOR = re.compile(r"^\s*(background-color|color)\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.\s,%]+\)|[a-zA-Z]{3,20})\s*$")


def limpiar_html(texto: str | None) -> str:
    """Safe HTML of a note ("" when there is no visible text)."""
    texto = str(texto or "")[:MAX_HTML]
    if not texto.strip():
        return ""
    try:
        raiz = lhtml.fragment_fromstring(texto, create_parent="div")
    except (etree.ParserError, ValueError):
        return ""
    for e in list(raiz.iter()):
        if e is raiz:
            continue
        if not isinstance(e.tag, str):                      # comments, processing instructions
            e.drop_tree()
            continue
        etiqueta = e.tag.lower()
        if etiqueta in _FUERA:
            e.drop_tree()
            continue
        href = (e.get("href") or "").strip() if etiqueta == "a" else ""
        clases = [c for c in (e.get("class") or "").split() if _CLASE_QUILL.match(c)]
        estilos = [s.strip() for s in (e.get("style") or "").split(";") if _COLOR.match(s)]
        for atributo in list(e.attrib):
            del e.attrib[atributo]
        if etiqueta not in _ETIQUETAS:
            e.drop_tag()
            continue
        if clases:
            e.set("class", " ".join(clases))
        if estilos:
            e.set("style", "; ".join(estilos))
        if etiqueta == "a":
            if re.match(r"^(https?:|mailto:)", href, re.I):
                e.set("href", href)
                e.set("target", "_blank")
                e.set("rel", "noopener")
            else:
                e.drop_tag()
    salida = etree.tostring(raiz, encoding="unicode", method="html").strip()
    salida = re.sub(r"^<div>|</div>$", "", salida).strip()
    visible = re.sub(r"<[^>]+>", "", salida).replace("&nbsp;", " ").strip()
    return salida if visible else ""
