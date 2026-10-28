"""Datos del cliente y del vendedor escritos en el comentario de un ticket («Código cliente: C35307», «Contacto: Juan Pérez», «Teléfono: 8599 9439»...).

`extraer_campos(texto)` devuelve los campos de la solicitud de presupuesto (los de la primera página del Excel: código de cliente, contacto, teléfono,
ejecutivo de ventas, además del nombre del cliente y el ticket) que el comentario trae. El plan y el ancho de banda NO se leen: no cambian el presupuesto. Reconoce «Campo: valor» con o sin
viñeta (*, -, •), uno por línea o varios en la misma línea, sin importar mayúsculas ni tildes. Lo que el comentario no trae no aparece en el resultado.
"""
import re
import unicodedata

# campo de la solicitud -> encabezados que se aceptan (sin tildes, en minúsculas)
ETIQUETAS: dict[str, tuple[str, ...]] = {
    "client_code": ("codigo del cliente", "codigo de cliente", "codigo cliente", "cod. cliente", "cod cliente", "id cliente", "id del cliente",
                    "numero de cliente", "no. cliente", "no cliente", "n° cliente", "cuenta cliente", "codigo"),
    "contact_name": ("nombre de contacto", "nombre del contacto", "nombre contacto", "persona de contacto", "contactos", "contacto"),
    "contact_phone": ("telefonos de contacto", "telefono de contacto", "telefonos contacto", "telefono contacto", "numero de contacto", "numero contacto", "telefonos", "telefono",
                      "celulares", "celular", "movil", "whatsapp", "tel.", "cel.", "tel", "cel"),
    "sales_exec": ("ejecutivo de ventas", "ejecutivo de venta", "ejecutivo comercial", "asesor comercial", "ejecutivo", "vendedor", "asesor"),
    "client_name": ("nombre del cliente", "nombre de cliente", "nombre cliente", "razon social", "cliente", "empresa"),
    "ticket_id": ("numero de ticket", "no. ticket", "no ticket", "ticket", "caso"),
}
# Lo que se lee de un ticket de Kayako para HACER el presupuesto (la lista ampliada): además de lo de arriba, el servicio, la velocidad, el medio, el correo y la dirección,
# y las formas que usan las ventas («Nombre:», «Código:», «teléfonos:»). Las masivas usan solo la lista de arriba (ellas no leen el plan ni el ancho de banda).
ETIQUETAS_PRESUPUESTO: dict[str, tuple[str, ...]] = {
    "client_code": ETIQUETAS["client_code"],
    "contact_name": ETIQUETAS["contact_name"],
    "contact_phone": ("telefonos de contacto", "telefono de contacto", "telefonos contacto", "telefono contacto", "numero de contacto", "numero contacto", "telefonos", "telefono",
                      "celulares", "celular", "movil", "whatsapp", "tel.", "cel.", "tel", "cel"),
    "sales_exec": ETIQUETAS["sales_exec"],
    "client_name": ("nombre del cliente", "nombre de cliente", "nombre cliente", "razon social", "nombre", "cliente", "empresa"),
    "ticket_id": ETIQUETAS["ticket_id"],
    "client_email": ("correo electronico", "correo", "e-mail", "email"),
    "address": ("direccion de instalacion", "direccion del cliente", "direccion", "ubicacion"),
    "service": ("tipo de servicio", "plan a contratar", "tipo de plan", "servicio", "plan"),
    "bandwidth": ("ancho de banda", "velocidad"),
    "medium": ("medio de servicio", "medio"),
}


def _compilar(etiquetas: dict[str, tuple[str, ...]]) -> tuple[re.Pattern[str], dict[str, str]]:
    por_etiqueta = {e: campo for campo, es in etiquetas.items() for e in es}
    return (re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(e) for e in sorted(por_etiqueta, key=len, reverse=True)) + r")[ \t]*[:=][ \t]*", re.I), por_etiqueta)


_POR_ETIQUETA = {e: campo for campo, es in ETIQUETAS.items() for e in es}
_ETIQUETA = _compilar(ETIQUETAS)[0]
_ETIQUETA_PRESUPUESTO, _POR_ETIQUETA_PRESUPUESTO = _compilar(ETIQUETAS_PRESUPUESTO)
_TELEFONO = re.compile(r"\+?\(?\d[\d\s().\-]{5,}\d")
_VIÑETA = re.compile(r"^[\s*\-–•·>]+|[\s,;|]+$")


def _plano(texto: str) -> str:
    """Same length as the text: every accented letter becomes its plain letter, lower case (so offsets of the match fit the original)."""
    return "".join((unicodedata.normalize("NFD", c)[0] if unicodedata.combining(unicodedata.normalize("NFD", c)[-1]) else c).lower() for c in texto)


def _limpio(campo: str, valor: str) -> str:
    valor = _VIÑETA.sub("", valor).strip()
    if campo == "contact_phone":
        m = _TELEFONO.search(valor)
        return re.sub(r"\s{2,}", " ", m.group(0)).strip() if m else ""
    if campo == "client_code":
        return valor.split()[0].strip(".,;:") if valor.split() else ""
    return re.sub(r"\s{2,}", " ", valor)


_ANCHO = re.compile(r"ancho\s+de\s+banda\s*[:=]\s*(\d+(?:[.,]\d+)?)\s*([kmg])?", re.I)


def ancho_de_banda_mbps(texto: str) -> float | None:
    """The bandwidth the comment writes («Ancho de Banda: 20M», «200 mbps», «1G»), in Mbps; None when it does not write one."""
    m = _ANCHO.search(_plano(str(texto or "")))
    if not m:
        return None
    valor = float(m.group(1).replace(",", "."))
    return valor * {"k": 0.001, "g": 1000}.get((m.group(2) or "m").lower(), 1)


def extraer_campos(texto: str, para_presupuesto: bool = False) -> dict[str, str]:
    """{"client_code": "C35307", "contact_phone": "8599 9439", ...}: the first value of each field the comment writes.
    `para_presupuesto`: the wider list of a Kayako ticket (service, speed, medium, e-mail, address; see ETIQUETAS_PRESUPUESTO)."""
    texto = str(texto or "")
    plano = _plano(texto)
    regex, por_etiqueta = (_ETIQUETA_PRESUPUESTO, _POR_ETIQUETA_PRESUPUESTO) if para_presupuesto else (_ETIQUETA, _POR_ETIQUETA)
    marcas = list(regex.finditer(plano))
    campos: dict[str, str] = {}
    for i, m in enumerate(marcas):
        campo = por_etiqueta[m.group(1).lower()]
        fin_linea = texto.find("\n", m.end())
        fin = len(texto) if fin_linea < 0 else fin_linea
        if i + 1 < len(marcas):
            fin = min(fin, marcas[i + 1].start())                  # several fields on one line
        valor = _limpio(campo, texto[m.end():fin])
        if valor and campo not in campos:
            campos[campo] = valor
    return campos
