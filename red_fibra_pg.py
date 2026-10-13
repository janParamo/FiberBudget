"""Visio network in PostgreSQL (schema red_fibra): nearest network node and the "origen" block.

The KMZ data (red_puntos in DB_*) still decides the connection point. This database backs it
up: it confirms the KMZ point exists in the diagrams, and supplies the connection point when
the KMZ has nothing near the client. A failure here never blocks a budget.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

import psycopg

from config import get_settings

log = logging.getLogger(__name__)

SIN_CONEXION = "sin_conexion_bd"
PREFERRED_TIPOS = ("MUFA", "NODO")
PREFERENCE_MARGIN_M = 50.0      # a MUFA/NODO this much farther still beats a MINI_NODO/ODF
MAX_ALTERNATIVAS = 4

_CANDIDATOS_SQL = """
SELECT id, nombre, tipo, propietario, lat, lon, fuente_coord, zona, notas, distancia_m, enlaces, clientes
FROM red_fibra.nodos_cercanos(%(lat)s, %(lon)s, %(radio_m)s, %(n)s, false)
"""
_FECHA_RED_SQL = "SELECT fecha FROM red_fibra.v_ultima_importacion"


def enabled() -> bool:
    return bool(get_settings().visio_db_name)


def connect() -> psycopg.Connection:
    """Read-only connection with 5 s connect and statement timeouts; tables resolve in red_fibra."""
    s = get_settings()
    conn = psycopg.connect(
        host=s.visio_db_host, port=s.visio_db_port, dbname=s.visio_db_name,
        user=s.visio_db_user, password=s.visio_db_password, connect_timeout=5,
        options="-c statement_timeout=5000 -c search_path=red_fibra,public",
    )
    conn.read_only = True
    conn.autocommit = True
    return conn


def connect_or_none() -> psycopg.Connection | None:
    """Connection, or None (logged) when disabled or unreachable."""
    if not enabled():
        return None
    try:
        return connect()
    except psycopg.Error as exc:
        log.error("Visio PostgreSQL unreachable (%s): %s", type(exc).__name__, str(exc).strip()[:200])
        return None


def requiere_revision(nodo: dict[str, Any]) -> bool:
    """Rule c: VALIDAR in the notes, or a coordinate estimated from its neighbours."""
    return "VALIDAR" in (nodo.get("notas") or "").upper() or nodo.get("fuente_coord") == "estimada_vecinos"


def elegir_candidato(candidatos: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(chosen node, up to 4 alternatives) from candidates sorted by distance.

    a) Estimated coordinates are dropped when at least one candidate has a real one.
    b) A MUFA/NODO is preferred over a MINI_NODO/ODF less than 50 m closer.
    """
    if not candidatos:
        return None, []
    reales = [c for c in candidatos if c.get("fuente_coord") != "estimada_vecinos"]
    pool = reales or candidatos
    elegido = pool[0]
    if elegido["tipo"] not in PREFERRED_TIPOS:
        preferido = next((c for c in pool if c["tipo"] in PREFERRED_TIPOS
                          and c["distancia_m"] - elegido["distancia_m"] < PREFERENCE_MARGIN_M), None)
        elegido = preferido or elegido
    alternativas = [c for c in candidatos if c is not elegido][:MAX_ALTERNATIVAS]
    return elegido, alternativas


@dataclass
class BusquedaVisio:
    fuente: str                        # red_fibra | sin_conexion_bd
    radio_m: float
    nodo: dict[str, Any] | None = None
    alternativas: list[dict[str, Any]] = field(default_factory=list)
    fecha_red: str | None = None

    @property
    def encontrado(self) -> bool:
        return self.nodo is not None


def buscar_origen(lat: float, lon: float, radio_m: float | None = None,
                  conn: psycopg.Connection | None = None) -> BusquedaVisio:
    """Nearest Visio node to (lat, lon); never raises. conn=None means no database."""
    s = get_settings()
    radio = float(radio_m or s.radio_busqueda_m)
    if conn is None:
        return BusquedaVisio(fuente=SIN_CONEXION, radio_m=radio)
    try:
        cur = conn.execute(_CANDIDATOS_SQL, {"lat": lat, "lon": lon, "radio_m": radio,
                                             "n": max(s.max_candidatos, MAX_ALTERNATIVAS + 1)})
        columns = [column.name for column in cur.description]
        candidatos = [dict(zip(columns, row)) for row in cur.fetchall()]
        fecha = conn.execute(_FECHA_RED_SQL).fetchone()
    except psycopg.Error as exc:
        log.error("Visio nearest-node query failed (%s): %s", type(exc).__name__, str(exc).strip()[:200])
        return BusquedaVisio(fuente=SIN_CONEXION, radio_m=radio)
    nodo, alternativas = elegir_candidato(candidatos)
    return BusquedaVisio(fuente="red_fibra", radio_m=radio, nodo=nodo, alternativas=alternativas,
                         fecha_red=fecha[0].isoformat(sep=" ", timespec="seconds") if fecha and fecha[0] else None)


def _resumen(nodo: dict[str, Any]) -> dict[str, Any]:
    return {"nombre": nodo["nombre"], "tipo": nodo["tipo"], "distancia_m": nodo["distancia_m"],
            "notas": nodo.get("notas")}


def bloque_origen(*, busqueda: BusquedaVisio, punto: dict[str, Any] | None, desde_visio: bool,
                  verificacion: dict[str, Any] | None, distancia_ruta_m: float | None,
                  radio_kmz_m: float) -> dict[str, Any]:
    """The response's "origen" block: the connection point the route starts from.

    punto: the KMZ connection point (nombre, tipo, lat, lon, distancia_m) when desde_visio is
    False. verificacion: whether that KMZ point exists in the diagrams (from origen.py).
    """
    nodo = busqueda.nodo
    if desde_visio and nodo is not None:
        usado = {"nombre": nodo["nombre"], "tipo": nodo["tipo"], "lat": nodo["lat"], "lon": nodo["lon"],
                 "distancia_lineal_m": nodo["distancia_m"], "fuente_coord": nodo.get("fuente_coord"),
                 "notas": nodo.get("notas")}
        revision = requiere_revision(nodo)
        fuente = "red_fibra"
        alternativas = busqueda.alternativas
    else:
        usado = {"nombre": punto.get("nombre") if punto else None, "tipo": punto.get("tipo") if punto else None,
                 "lat": punto.get("lat") if punto else None, "lon": punto.get("lon") if punto else None,
                 "distancia_lineal_m": round(punto["distancia_m"], 1) if punto else None,
                 "fuente_coord": "kmz", "notas": None}
        fuente = SIN_CONEXION if busqueda.fuente == SIN_CONEXION else "metodo_anterior"
        # The KMZ point must also exist in the diagrams; a KMZ point beyond its own search
        # radius (nothing better in the diagrams either) is a guess as well.
        revision = bool((verificacion is not None and verificacion.get("coincide") is False)
                        or (punto and punto["distancia_m"] > radio_kmz_m))
        alternativas = ([nodo] if nodo else []) + busqueda.alternativas
    sin_punto_cercano = not busqueda.encontrado and (punto is None or punto["distancia_m"] > radio_kmz_m)
    if busqueda.fuente == SIN_CONEXION:
        mensaje = "sin conexión a la base de la red (Visio); se usó el método anterior"
    elif not busqueda.encontrado:
        mensaje = "sin nodo de red cercano"
    else:
        mensaje = None
    return {
        "encontrado": busqueda.encontrado,
        **usado,
        "distancia_ruta_m": round(distancia_ruta_m, 1) if distancia_ruta_m is not None else None,
        "requiere_revision": revision,
        "fuente": fuente,
        "alternativas": [_resumen(c) for c in alternativas[:MAX_ALTERNATIVAS]],
        "fecha_red": busqueda.fecha_red,
        "radio_busqueda_m": busqueda.radio_m,
        "mensaje": mensaje,
        "sin_punto_cercano": sin_punto_cercano,
        "nodo_red_mas_cercano": ({**_resumen(nodo), "lat": nodo["lat"], "lon": nodo["lon"],
                                  "fuente_coord": nodo.get("fuente_coord")} if nodo else None),
        "verificacion_kmz": verificacion,
    }


def leyenda_punto_conexion(bloque: dict[str, Any]) -> str:
    """Text appended to "Punto de conexión" in the Excel, or "" when nothing to flag."""
    if bloque["sin_punto_cercano"]:
        return (f" (No se encontró nodo de red a menos de {bloque['radio_busqueda_m']:.0f} m; "
                "validar con Planta Externa)")
    if bloque["requiere_revision"]:
        return " (Coordenada estimada / validar en campo)"
    return ""
