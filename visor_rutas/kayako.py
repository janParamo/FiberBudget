"""Lectura de los tickets de Kayako desde su base de datos (MySQL, la réplica que se actualiza en milisegundos). SOLO LECTURA.

Nunca escribe en Kayako: la conexión se abre en modo «solo lectura» (`SET SESSION TRANSACTION READ ONLY`), el único SQL que corre es un SELECT y el
usuario de la base debería tener solo permiso de SELECT. Los datos de la conexión van en el .env (KAYAKO_DB_HOST, KAYAKO_DB_PORT, KAYAKO_DB_NAME,
KAYAKO_DB_USER, KAYAKO_DB_PASSWORD), nunca en el código. Los filtros (departamento, tipo, estados, campo del ejecutivo) están en business_rules.yaml, sección `kayako`.

La consulta es la que ya usa n8n: el ticket, su primer y último comentario, el ejecutivo de cuenta (campo personalizado) y la última actividad.
De cada ticket se sacan, del texto del comentario, los datos del cliente («Código de cliente: …», «Persona de contacto: …», «Teléfono: …») con el mismo
lector que las coordenadas masivas (comentario_ticket) y las coordenadas que traiga escritas.
"""
import html
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger(__name__)

POR_DEFECTO = {"departamento_like": "%Fibra%Optica%", "tipo_like": "%", "estados": ["Abierto"], "campo_ejecutivo_id": 64, "dias_atras": 30,
               "campos_personalizados": ["Código de Cliente", "Sucursal", "Ejecutivo de Cuenta", "Tipo de Cliente", "Servicio Asociado", "Medio", "Coordenadas"]}
_RE_ETIQUETA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def configuracion() -> dict[str, Any]:
    """The `kayako` section of business_rules.yaml over the defaults."""
    try:
        from pathlib import Path

        import yaml
        from config import get_settings
        datos = (yaml.safe_load(Path(get_settings().rules_path).read_text(encoding="utf-8")) or {}).get("kayako") or {}
    except Exception:                                                # noqa: BLE001 - the defaults are the query of n8n
        datos = {}
    return {**POR_DEFECTO, **{k: v for k, v in datos.items() if k in POR_DEFECTO}}


def _entorno() -> dict[str, str]:
    import config  # noqa: F401  (loads the .env)
    return {"host": os.getenv("KAYAKO_DB_HOST", "").strip(), "puerto": os.getenv("KAYAKO_DB_PORT", "3306").strip() or "3306", "base": os.getenv("KAYAKO_DB_NAME", "kayako_fusion").strip() or "kayako_fusion",
            "usuario": os.getenv("KAYAKO_DB_USER", "").strip(), "clave": os.getenv("KAYAKO_DB_PASSWORD", "")}


def configurada() -> bool:
    e = _entorno()
    return bool(e["host"] and e["usuario"] and e["clave"])


def conectar() -> Any:
    """A read-only connection to the Kayako database (dictionary rows). The caller closes it."""
    import pymysql
    e = _entorno()
    if not (e["host"] and e["usuario"] and e["clave"]):
        raise RuntimeError("Falta la conexión de Kayako en el .env (KAYAKO_DB_HOST, KAYAKO_DB_USER y KAYAKO_DB_PASSWORD)")
    con = pymysql.connect(host=e["host"], port=int(e["puerto"]), user=e["usuario"], password=e["clave"], database=e["base"], charset="utf8mb4",
                          connect_timeout=8, read_timeout=30, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    with con.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return con


def consulta(base: str, estados: int, con_tipo: bool = True) -> str:
    """The SELECT of the tickets (the query of n8n plus what Kayako's own list shows: priority, organization, last replier, replies, owner and due time; the dates stay
    as Unix numbers and are converted here). `estados`: how many status placeholders; `con_tipo`: filter by the ticket type (with «%» every type is wanted)."""
    if not _RE_ETIQUETA.match(base):
        raise ValueError("Nombre de base no válido")
    ultima = ("GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0))")
    return f"""
SELECT T.ticketid AS id, T.ticketmaskid AS ticket, T.subject AS asunto, T.fullname AS cliente, CFO.optionvalue AS ejecutivo,
       T.departmenttitle AS departamento, T.tickettypetitle AS tipo, T.ticketstatustitle AS estado, T.ownerstaffname AS owner, T.dateline AS creado,
       TP.contents AS primer_comentario, TP.ishtml AS primer_html,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.contents ELSE NULL END AS ultimo_comentario,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.ishtml ELSE NULL END AS ultimo_html,
       {ultima} AS ultima_actividad, T.prioritytitle AS prioridad, ORG.organizationname AS organizacion, T.lastreplier AS ultimo_respondedor,
       T.totalreplies AS respuestas, T.duetime AS vence
FROM {base}.swtickets AS T
  LEFT JOIN {base}.swusers AS U ON U.userid = T.userid
  LEFT JOIN {base}.swuserorganizations AS ORG ON ORG.userorganizationid = U.userorganizationid
  LEFT JOIN {base}.swticketposts AS TP ON TP.ticketpostid = T.firstpostid
  LEFT JOIN {base}.swticketposts AS TL ON TL.ticketpostid = T.lastpostid
  LEFT JOIN {base}.swcustomfieldvalues AS CFV ON CFV.typeid = T.ticketid AND CFV.customfieldid = %s
  LEFT JOIN {base}.swcustomfieldoptions AS CFO ON CFO.customfieldoptionid = CFV.fieldvalue
WHERE T.departmenttitle LIKE %s{" AND T.tickettypetitle LIKE %s" if con_tipo else ""} AND T.ticketstatustitle IN ({", ".join(["%s"] * estados)}) AND {ultima} >= %s
ORDER BY {ultima} DESC
LIMIT %s"""


def consulta_personalizados(base: str, tickets: int, titulos: int) -> str:
    """The additional fields of the tickets («Código de Cliente», «Sucursal», «Servicio Asociado»…): the typed text, or the text of the option chosen in a list."""
    if not _RE_ETIQUETA.match(base):
        raise ValueError("Nombre de base no válido")
    return f"""
SELECT V.typeid AS ticketid, F.title AS titulo, COALESCE(O.optionvalue, V.fieldvalue) AS valor
FROM {base}.swcustomfieldvalues AS V
  JOIN {base}.swcustomfields AS F ON F.customfieldid = V.customfieldid
  LEFT JOIN {base}.swcustomfieldoptions AS O ON O.customfieldid = V.customfieldid AND O.customfieldoptionid = V.fieldvalue
WHERE V.typeid IN ({", ".join(["%s"] * tickets)}) AND F.title IN ({", ".join(["%s"] * titulos)})"""


def tickets(desde_unix: int, limite: int = 500, abrir: Callable[[], Any] = conectar) -> list[dict[str, Any]]:
    """The tickets of the filters (business_rules.yaml, `kayako`) with activity since `desde_unix`, newest activity first. Read only.
    Each one also carries `personalizados` ({title: value} of its additional fields); if that second query fails the tickets still come, without them."""
    cfg = configuracion()
    estados = [str(e) for e in cfg["estados"]] or ["Abierto"]
    con = abrir()
    try:
        with con.cursor() as cur:
            con_tipo = str(cfg["tipo_like"] or "%").strip() not in ("", "%")
            cur.execute(consulta(_entorno()["base"], len(estados), con_tipo),
                        (int(cfg["campo_ejecutivo_id"]), cfg["departamento_like"], *([cfg["tipo_like"]] if con_tipo else []), *estados, int(desde_unix), max(1, min(int(limite), 5000))))
            filas = list(cur.fetchall())
            titulos = [str(t) for t in cfg["campos_personalizados"] or []]
            por_ticket: dict[Any, dict[str, str]] = {}
            if filas and titulos:
                try:
                    cur.execute(consulta_personalizados(_entorno()["base"], len(filas), len(titulos)), (*[f["id"] for f in filas], *titulos))
                    for v in cur.fetchall():
                        if v["valor"] not in (None, ""):
                            por_ticket.setdefault(v["ticketid"], {}).setdefault(str(v["titulo"]), str(v["valor"]).strip())
                except Exception as exc:                          # noqa: BLE001 - the names of those tables are not ours: the tickets are still useful without them
                    log.warning("Kayako: the additional fields could not be read (%s: %s)", type(exc).__name__, str(exc)[:120])
            for f in filas:
                f["personalizados"] = por_ticket.get(f["id"], {})
            return filas
    finally:
        con.close()


def a_texto(contenido: Any, es_html: Any) -> str:
    """The text of a comment: HTML turned into lines (breaks and paragraphs become new lines), entities decoded, blank lines squeezed."""
    texto = str(contenido or "")
    if es_html or re.search(r"<\s*(br|p|div|li|table|tr)\b", texto, re.I):
        texto = re.sub(r"<\s*br\s*/?\s*>|</\s*(p|div|li|tr|h\d)\s*>", "\n", texto, flags=re.I)
        texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto).replace("\xa0", " ").replace("\r", "")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linea.rstrip() for linea in texto.split("\n"))).strip()


def _fecha(unix: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(unix)).isoformat(timespec="seconds") if unix else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def velocidad_en_mbps(texto: Any) -> str:
    """«25mbps» -> «25 Mbps»; «1G» -> «1000 Mbps»; «Transmisión de datos Departamental 25 Mbps» -> «25 Mbps»; empty when there is no speed in the text."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([kmg])\s*(?:b|bps|bit|bits)?\b", str(texto or ""), re.I)
    if not m:
        return ""
    n = float(m.group(1).replace(",", ".")) * {"k": 0.001, "m": 1, "g": 1000}[m.group(2).lower()]
    return f"{n:g} Mbps"


def sugerencia_presupuesto(t: dict[str, Any]) -> dict[str, Any]:
    """What the form of «Nuevo presupuesto» can be filled with from a ticket (already parsed by datos_del_ticket): ticket, client, code, executive, contact, phone,
    coordinate, speed, medium and the service as the ticket says it (the page matches it with its own list). Empty text = the ticket does not say."""
    c, p = t["campos_presupuesto"], t["personalizados"]
    nombre = c.get("client_name") or ("" if "@" in t["cliente"] else t["cliente"]) or t["asunto"]
    servicio = c.get("service") or p.get("Servicio Asociado", "")
    lugares = t["coordenadas"] or []
    if not lugares and p.get("Coordenadas"):                       # the additional field «Coordenadas», when the comment has none
        lugares = _coordenadas_de(p["Coordenadas"])
    return {"ticket_id": t["ticket"], "client_name": nombre, "client_code": c.get("client_code") or p.get("Código de Cliente", ""),
            "sales_exec": t["ejecutivo"] or p.get("Ejecutivo de Cuenta", "") or c.get("sales_exec", ""), "contact_name": c.get("contact_name", ""),
            "contact_phone": c.get("contact_phone", ""), "coordenadas": [f"{la:.6f}, {lo:.6f}" for la, lo in lugares], "servicio": servicio,
            "bandwidth": velocidad_en_mbps(c.get("bandwidth")) or velocidad_en_mbps(servicio), "medium": c.get("medium") or p.get("Medio", ""),
            "direccion": c.get("address", "") or p.get("Sucursal", ""), "correo": c.get("client_email", ""), "sucursal": p.get("Sucursal", ""), "tipo_cliente": p.get("Tipo de Cliente", "")}


def _coordenadas_de(texto: str) -> list[tuple[float, float]]:
    from visor_rutas import masivas
    try:
        return [(p["lat"], p["lon"]) for p in masivas.extraer("ticket.txt", str(texto).encode("utf-8"))["puntos"] if p["estado"] == masivas.OK]
    except ValueError:
        return []


def datos_del_ticket(fila: dict[str, Any]) -> dict[str, Any]:
    """A ticket of the query, ready for planning: its fields, the text of its comments, the client data written in them and the coordinates written in them."""
    from visor_rutas import comentario_ticket, masivas
    primero = a_texto(fila.get("primer_comentario"), fila.get("primer_html"))
    ultimo = a_texto(fila.get("ultimo_comentario"), fila.get("ultimo_html"))
    campos = {**comentario_ticket.extraer_campos(ultimo), **comentario_ticket.extraer_campos(primero)}      # the first comment (the request) wins over the last
    coordenadas: list[list[float]] = []
    for texto in (primero, ultimo):
        try:
            puntos = masivas.extraer("ticket.txt", texto.encode("utf-8"))["puntos"] if texto else []
        except ValueError:                                                                                 # no coordinate in that text
            puntos = []
        for p in puntos:
            if p["estado"] == masivas.OK and [p["lat"], p["lon"]] not in coordenadas:
                coordenadas.append([p["lat"], p["lon"]])
    vence = fila.get("vence")
    datos = {"prioridad": str(fila.get("prioridad") or ""), "organizacion": str(fila.get("organizacion") or ""), "ultimo_respondedor": str(fila.get("ultimo_respondedor") or ""),
             "respuestas": int(fila.get("respuestas") or 0), "vence": _fecha(vence), "vencido": bool(vence and int(vence) < time.time()), "kayako_id": fila.get("id"), "ticket": str(fila.get("ticket") or ""), "asunto": str(fila.get("asunto") or ""), "cliente": str(fila.get("cliente") or ""),
             "ejecutivo": str(fila.get("ejecutivo") or ""), "departamento": fila.get("departamento"), "tipo": fila.get("tipo"), "estado": fila.get("estado"),
             "owner": fila.get("owner"), "creado": _fecha(fila.get("creado")), "ultima_actividad": _fecha(fila.get("ultima_actividad")),
             "comentario": primero, "ultimo_comentario": ultimo, "campos": campos, "coordenadas": coordenadas, "personalizados": dict(fila.get("personalizados") or {}),
             "campos_presupuesto": {**comentario_ticket.extraer_campos(ultimo, True), **comentario_ticket.extraer_campos(primero, True)}}
    datos["sugerencia"] = sugerencia_presupuesto(datos)
    return datos


def vista_previa(dias: float | None = None, limite: int = 50, abrir: Callable[[], Any] = conectar) -> list[dict[str, Any]]:
    """The tickets that would reach planning (last `dias` days of activity), parsed. Reads only; creates nothing anywhere."""
    dias = float(dias if dias is not None else configuracion()["dias_atras"])
    return [datos_del_ticket(f) for f in tickets(int(time.time() - dias * 86400), limite, abrir)]
