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

POR_DEFECTO = {"departamento_like": "%Fibra%Optica%", "tipo_like": "%Presupuesto%FO%", "estados": ["Abierto", "En Espera"], "campo_ejecutivo_id": 64, "dias_atras": 30}
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


def consulta(base: str, estados: int) -> str:
    """The SELECT of the tickets (the query of n8n; the dates stay as Unix numbers and are converted here). `estados`: how many status placeholders."""
    if not _RE_ETIQUETA.match(base):
        raise ValueError("Nombre de base no válido")
    ultima = ("GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0))")
    return f"""
SELECT T.ticketid AS id, T.ticketmaskid AS ticket, T.subject AS asunto, T.fullname AS cliente, CFO.optionvalue AS ejecutivo,
       T.departmenttitle AS departamento, T.tickettypetitle AS tipo, T.ticketstatustitle AS estado, T.ownerstaffname AS owner, T.dateline AS creado,
       TP.contents AS primer_comentario, TP.ishtml AS primer_html,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.contents ELSE NULL END AS ultimo_comentario,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.ishtml ELSE NULL END AS ultimo_html,
       {ultima} AS ultima_actividad
FROM {base}.swtickets AS T
  LEFT JOIN {base}.swticketposts AS TP ON TP.ticketpostid = T.firstpostid
  LEFT JOIN {base}.swticketposts AS TL ON TL.ticketpostid = T.lastpostid
  LEFT JOIN {base}.swcustomfieldvalues AS CFV ON CFV.typeid = T.ticketid AND CFV.customfieldid = %s
  LEFT JOIN {base}.swcustomfieldoptions AS CFO ON CFO.customfieldoptionid = CFV.fieldvalue
WHERE T.departmenttitle LIKE %s AND T.tickettypetitle LIKE %s AND T.ticketstatustitle IN ({", ".join(["%s"] * estados)}) AND {ultima} >= %s
ORDER BY {ultima} DESC
LIMIT %s"""


def tickets(desde_unix: int, limite: int = 500, abrir: Callable[[], Any] = conectar) -> list[dict[str, Any]]:
    """The tickets of the filters (business_rules.yaml, `kayako`) with activity since `desde_unix`, newest activity first. Read only."""
    cfg = configuracion()
    estados = [str(e) for e in cfg["estados"]] or ["Abierto"]
    con = abrir()
    try:
        with con.cursor() as cur:
            cur.execute(consulta(_entorno()["base"], len(estados)),
                        (int(cfg["campo_ejecutivo_id"]), cfg["departamento_like"], cfg["tipo_like"], *estados, int(desde_unix), max(1, min(int(limite), 5000))))
            return list(cur.fetchall())
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
    return {"kayako_id": fila.get("id"), "ticket": str(fila.get("ticket") or ""), "asunto": str(fila.get("asunto") or ""), "cliente": str(fila.get("cliente") or ""),
            "ejecutivo": str(fila.get("ejecutivo") or ""), "departamento": fila.get("departamento"), "tipo": fila.get("tipo"), "estado": fila.get("estado"),
            "owner": fila.get("owner"), "creado": _fecha(fila.get("creado")), "ultima_actividad": _fecha(fila.get("ultima_actividad")),
            "comentario": primero, "ultimo_comentario": ultimo, "campos": campos, "coordenadas": coordenadas}


def vista_previa(dias: float | None = None, limite: int = 50, abrir: Callable[[], Any] = conectar) -> list[dict[str, Any]]:
    """The tickets that would reach planning (last `dias` days of activity), parsed. Reads only; creates nothing anywhere."""
    dias = float(dias if dias is not None else configuracion()["dias_atras"])
    return [datos_del_ticket(f) for f in tickets(int(time.time() - dias * 86400), limite, abrir)]
