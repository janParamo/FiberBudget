"""La ruta de cada presupuesto generado, guardada en «Mis lugares» de quien lo generó, para verla en el mapa, editarla o modificarla.

Una carpeta «Presupuestos» (en la raíz de los lugares del usuario) con una ruta por presupuesto, llamada `<código del cliente>_<nombre del cliente>`:
la misma línea que va en el Excel (de la mufa de conexión al cliente). Al generar otra vez el mismo presupuesto:
- si la ruta guardada no se tocó, se reemplaza por la nueva;
- si alguien la editó (cambió sus puntos), se respeta y la nueva se guarda al lado como «… (2)», «… (3)».
Nunca bloquea el presupuesto: quien llama atrapa cualquier error.
"""
import hashlib
import json
import logging
import re
import threading
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import lugares

log = logging.getLogger(__name__)

CARPETA = "Presupuestos"
ESTILO_RUTA = {"linea": {"color": "#ffd400", "grosor": 5, "opacidad": 1}}
MIN_PUNTOS = 2

_servicio: Any = None
_candado = threading.Lock()


def _huella(coordenadas: list[list[float]]) -> str:
    """Identifies a route by its points (rounded to ~1 cm): the same one generated again, or one that was edited."""
    texto = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in coordenadas)
    return hashlib.md5(texto.encode("ascii")).hexdigest()


def _coordenadas(puntos: list[tuple[float, float]]) -> list[list[float]]:
    """(lat, lon) -> [lon, lat] without consecutive repeats (a line needs two different points)."""
    salida: list[list[float]] = []
    for lat, lon in puntos:
        par = [round(float(lon), 7), round(float(lat), 7)]
        if not salida or salida[-1] != par:
            salida.append(par)
    return salida


def nombre_ruta(codigo: str, cliente: str) -> str:
    """<código>_<cliente> (only one of them when the other is empty or both are the same)."""
    limpio = lambda t: " ".join(re.sub(r"[\x00-\x1f]", " ", str(t or "")).split())
    codigo, cliente = limpio(codigo), limpio(cliente)
    if not codigo or not cliente or codigo.lower() == cliente.lower():
        return (codigo or cliente)[:lugares.MAX_NOMBRE]
    return f"{codigo}_{cliente}"[:lugares.MAX_NOMBRE]


def _carpeta(con: Any, actor: dict[str, Any]) -> int:
    fila = con.execute("SELECT id FROM redes.lugares_carpetas WHERE usuario_id = %s AND padre_id IS NULL AND lower(nombre) = lower(%s) AND borrado_en IS NULL "
                       "ORDER BY id LIMIT 1", (actor["id"], CARPETA)).fetchone()
    return fila["id"] if fila else lugares.guardar_carpeta(con, actor, nombre=CARPETA)["id"]


def guardar_ruta(con: Any, actor: dict[str, Any], *, nombre: str, puntos: list[tuple[float, float]], descripcion: str = "",
                 propiedades: dict[str, Any] | None = None) -> dict[str, Any]:
    """Creates or refreshes the route `nombre` in the user's «Presupuestos» folder. {"id", "nombre", "accion": "creada|actualizada|aparte"}."""
    coordenadas = _coordenadas(puntos)
    if len(coordenadas) < MIN_PUNTOS:
        raise lugares.DatosInvalidos({"ruta": "La ruta no tiene dos puntos distintos"})
    huella = _huella(coordenadas)
    props = {**(propiedades or {}), "origen": "presupuesto", "huella": huella}
    html = f"<p>{descripcion}</p>" if descripcion else None
    with con.transaction():
        carpeta = _carpeta(con, actor)
        existentes = con.execute("SELECT id, nombre, version, propiedades, ST_AsGeoJSON(geom, 8) AS g FROM redes.lugares_elementos "
                                 "WHERE carpeta_id = %s AND tipo = 'ruta' AND borrado_en IS NULL AND (nombre = %s OR nombre LIKE %s) ORDER BY id",
                                 (carpeta, nombre, nombre.replace("%", r"\%").replace("_", r"\_") + r" (%)")).fetchall()
        igual = next((e for e in existentes if e["nombre"] == nombre), None)
        linea = {"type": "LineString", "coordinates": coordenadas}
        if igual is None:
            lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="ruta", nombre=nombre, estilo=ESTILO_RUTA, propiedades=props, geom=linea,
                                          descripcion_html=html)
            return {"id": lugar["lugar"]["id"], "nombre": nombre, "accion": "creada"}
        guardada = _huella([[round(lon, 7), round(lat, 7)] for lon, lat in json.loads(igual["g"])["coordinates"]])
        if guardada == (igual["propiedades"] or {}).get("huella"):                          # untouched since it was generated: refreshed
            lugar = lugares.guardar_lugar(con, actor, id=igual["id"], version=igual["version"], geom=linea, propiedades=props, descripcion_html=html or "")
            return {"id": lugar["lugar"]["id"], "nombre": nombre, "accion": "actualizada"}
        usados = {e["nombre"] for e in existentes}                                          # an edited one stays: the new one goes beside it
        n = 2
        while f"{nombre} ({n})" in usados:
            n += 1
        lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="ruta", nombre=f"{nombre} ({n})", estilo=ESTILO_RUTA, propiedades=props, geom=linea,
                                      descripcion_html=html)
        return {"id": lugar["lugar"]["id"], "nombre": f"{nombre} ({n})", "accion": "aparte"}


def _servicio_redes() -> Any:
    global _servicio
    with _candado:
        if _servicio is None:
            from visor_rutas.redes.api import ServicioRedes
            _servicio = ServicioRedes()
        return _servicio


def guardar_de(quien: dict[str, str], *, servicio: Any = None, **datos: Any) -> dict[str, Any]:
    """`guardar_ruta` for whoever generated the budget: `quien` = {"persona_visor": …} or {"usuario_windows": …} (the user is created if new)."""
    servicio = servicio or _servicio_redes()
    return servicio.ejecutar(lambda con, actor, **kw: guardar_ruta(con, actor, **kw), datos, persona_visor=quien.get("persona_visor"),
                             usuario_windows=quien.get("usuario_windows"))
