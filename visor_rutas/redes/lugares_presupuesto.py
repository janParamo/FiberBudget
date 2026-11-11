"""La ruta de cada presupuesto generado, guardada en «Mis lugares» de quien lo generó, para verla en el mapa, editarla o modificarla.

Una carpeta «Presupuestos» (en la raíz de los lugares del usuario) con UNA CARPETA POR PRESUPUESTO, llamada `<código del cliente>_<nombre del cliente>`, que guarda
todo lo que el presupuesto usó, para no tener que volver a dibujarlo:
- la **ruta** (la misma línea que va en el Excel, de la mufa de conexión al cliente), con el mismo nombre que la carpeta;
- el **punto del cliente**, en su coordenada exacta (un elemento «cliente» de la red);
- la **acometida** del cliente: del final de la ruta (donde Google la deja en la calle) al cliente (un cable de clase acometida que termina en el cliente);
- los **postes nuevos** que la ruta necesita (elementos «poste»), uno por poste.
Los números del presupuesto (metraje final, reserva, postes existentes…) quedan en las propiedades de la ruta.

Al generar otra vez el mismo presupuesto:
- si la ruta guardada no se tocó, se reemplaza todo por lo nuevo (los postes nuevos de antes se borran y se crean los de ahora);
- si alguien la editó (cambió sus puntos), se respeta y lo nuevo se guarda al lado como «… (2)», «… (3)».
Al EDITAR la ruta guardada (Mis lugares), `al_editar_ruta` la deja coherente: la acometida sigue al final de la ruta y los postes nuevos que la ruta ya no usa se borran
solos. `resumen_ruta` da los números de la ruta que se está editando (como al medir) sin guardar nada.
Nunca bloquea el presupuesto: quien llama atrapa cualquier error.
"""
import hashlib
import json
import logging
import math
import re
import threading
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import lugares, repositorio

log = logging.getLogger(__name__)

CARPETA_POSTES = "Postes nuevos"
CARPETA = "Presupuestos"
ESTILO_RUTA = {"linea": {"color": "#ffd400", "grosor": 5, "opacidad": 1}}
SUBTIPO_POSTE_NUEVO = "ideay_8_120"      # the new poles of a budget are the 8 m ones (new_pole_row_label of the rules)
MIN_PUNTOS = 2
ACOMETIDA_MIN_M = 1.0                    # a drop shorter than this is not drawn (the viewer's DROP_MIN_M)
POSTE_USADO_M = 25.0                     # a saved new pole farther than this from the route is not used by it (poles.existing_pole_search_buffer_m of the rules)
_CODIGO_CLIENTE = re.compile(r"^C\d{3,8}$", re.I)

_servicio: Any = None
_candado = threading.Lock()


# --------------------------------------------------------------------------- geometría

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


def _metros(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(min(1.0, h)))


def distancia_a_linea_m(punto: tuple[float, float], linea: list[tuple[float, float]]) -> float:
    """Metres from a (lat, lon) point to the nearest place of a polyline of (lat, lon) points (local flat approximation: exact enough for tens of metres)."""
    if not linea:
        return math.inf
    kx = 111320.0 * math.cos(math.radians(punto[0]))
    ky = 110574.0
    mejor = math.inf
    xy = [((lon - punto[1]) * kx, (lat - punto[0]) * ky) for lat, lon in linea]
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]) if len(xy) > 1 else [(xy[0], xy[0])]:
        dx, dy = x2 - x1, y2 - y1
        largo2 = dx * dx + dy * dy
        t = 0.0 if largo2 == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / largo2))
        mejor = min(mejor, math.hypot(x1 + t * dx, y1 + t * dy))
    return mejor


def _linea_de(geojson: str) -> list[tuple[float, float]]:
    return [(float(lat), float(lon)) for lon, lat in json.loads(geojson)["coordinates"]]


def umbral_poste_usado_m() -> float:
    """How far a saved new pole may be from the route and still be used by it: the pole search buffer of the business rules (25 m)."""
    try:
        from config import get_settings, load_rules
        return float(load_rules(get_settings().rules_path)["poles"]["existing_pole_search_buffer_m"])
    except Exception:                                          # noqa: BLE001 - without the rules the default is the same number
        return POSTE_USADO_M


# --------------------------------------------------------------------------- nombres y carpetas

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


def _carpeta_postes(con: Any, actor: dict[str, Any], carpeta: int) -> int:
    """The «Postes nuevos» folder inside the budget folder (made when missing): the client's folder holds the route, the drop, the client point and this one."""
    fila = con.execute("SELECT id FROM redes.lugares_carpetas WHERE padre_id = %s AND usuario_id = %s AND lower(nombre) = lower(%s) AND borrado_en IS NULL ORDER BY id LIMIT 1",
                       (carpeta, actor["id"], CARPETA_POSTES)).fetchone()
    return fila["id"] if fila else lugares.guardar_carpeta(con, actor, nombre=CARPETA_POSTES, padre_id=carpeta)["id"]


def _borrar(con: Any, actor: dict[str, Any], ids: list[int]) -> None:
    """Logical delete of places that nothing else hangs from (a pole of a budget, its drop, its client point)."""
    for ident in ids:
        try:
            lugares.eliminar_lugar(con, actor, id=int(ident), con_cables=True)
        except Exception as exc:                               # noqa: BLE001 - already deleted by hand, or no longer ours: nothing to clean
            log.info("Presupuestos: no se pudo borrar el lugar %s (%s)", ident, type(exc).__name__)


# --------------------------------------------------------------------------- guardar la ruta con lo que usa

def _crear_acompanantes(con: Any, actor: dict[str, Any], carpeta: int, nombre: str, coordenadas: list[list[float]], cliente: dict[str, Any] | None,
                        postes_nuevos: list[tuple[float, float]]) -> dict[str, Any]:
    """The client point, the drop and the new poles of the budget inside its folder. {"cliente_id", "acometida_id", "acometida_m", "postes_nuevos": [ids]}."""
    hecho: dict[str, Any] = {"cliente_id": None, "acometida_id": None, "acometida_m": 0.0, "postes_nuevos": []}
    carpeta_postes = _carpeta_postes(con, actor, carpeta) if postes_nuevos else carpeta         # the new poles in their own folder: one box turns them all off
    for n, (lat, lon) in enumerate(postes_nuevos, 1):
        lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta_postes, tipo="poste", nombre=f"Poste nuevo {n}", geom={"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                                      propiedades={"subtipo": SUBTIPO_POSTE_NUEVO})
        hecho["postes_nuevos"].append(lugar["lugar"]["id"])
    if not cliente or cliente.get("lat") is None or cliente.get("lon") is None:
        return hecho
    clat, clon = float(cliente["lat"]), float(cliente["lon"])
    codigo = str(cliente.get("codigo") or "").strip().upper()
    lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="cliente", nombre=(str(cliente.get("nombre") or "").strip() or nombre)[:lugares.MAX_NOMBRE],
                                  geom={"type": "Point", "coordinates": [round(clon, 7), round(clat, 7)]},
                                  propiedades={"codigo": codigo} if _CODIGO_CLIENTE.match(codigo) else {})
    hecho["cliente_id"] = lugar["lugar"]["id"]
    fin = coordenadas[-1]
    hecho["acometida_m"] = round(_metros((fin[1], fin[0]), (clat, clon)), 1)
    if hecho["acometida_m"] >= ACOMETIDA_MIN_M:
        hecho["acometida_id"] = _crear_acometida(con, actor, carpeta, fin, hecho["cliente_id"], clat, clon)
    return hecho


def _crear_acometida(con: Any, actor: dict[str, Any], carpeta: int, fin: list[float], cliente_id: int, clat: float, clon: float) -> int:
    lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="cable", nombre="Acometida", geom={"type": "LineString", "coordinates": [fin, [round(clon, 7), round(clat, 7)]]},
                                  propiedades={"clase": "acometida", "tipo": "FLAT", "hilos": 2, "hilos_por_buffer": 2, "color": "#00e65a", "destino_id": cliente_id})
    return lugar["lugar"]["id"]


def guardar_ruta(con: Any, actor: dict[str, Any], *, nombre: str, puntos: list[tuple[float, float]], descripcion: str = "",
                 propiedades: dict[str, Any] | None = None, cliente: dict[str, Any] | None = None,
                 postes_nuevos: list[tuple[float, float]] | None = None) -> dict[str, Any]:
    """Creates or refreshes the budget folder `nombre` in the user's «Presupuestos» folder: the route, the client point, the drop and the new poles.
    {"id" (of the route), "nombre", "accion": "creada|actualizada|aparte", "carpeta_id", "postes_nuevos": n}."""
    coordenadas = _coordenadas(puntos)
    if len(coordenadas) < MIN_PUNTOS:
        raise lugares.DatosInvalidos({"ruta": "La ruta no tiene dos puntos distintos"})
    huella = _huella(coordenadas)
    html = f"<p>{descripcion}</p>" if descripcion else None
    linea = {"type": "LineString", "coordinates": coordenadas}
    nuevos = [(float(a), float(b)) for a, b in (postes_nuevos or [])]
    with con.transaction():
        raiz = _carpeta(con, actor)
        patron = nombre.replace("%", r"\%").replace("_", r"\_") + r" (%)"
        carpetas = con.execute("SELECT id, nombre FROM redes.lugares_carpetas WHERE padre_id = %s AND usuario_id = %s AND borrado_en IS NULL AND (nombre = %s OR nombre LIKE %s) "
                               "ORDER BY id", (raiz, actor["id"], nombre, patron)).fetchall()
        igual = next((c for c in carpetas if c["nombre"] == nombre), None)
        ruta = None
        if igual is not None:
            ruta = con.execute("SELECT id, version, propiedades, ST_AsGeoJSON(geom, 8) AS g FROM redes.lugares_elementos WHERE carpeta_id = %s AND tipo = 'ruta' AND borrado_en IS NULL "
                               "ORDER BY id LIMIT 1", (igual["id"],)).fetchone()
        if igual is not None and ruta is not None:
            guardada = _huella([[round(lon, 7), round(lat, 7)] for lon, lat in json.loads(ruta["g"])["coordinates"]])
            if guardada == (ruta["propiedades"] or {}).get("huella") or guardada == huella:   # untouched since it was generated, or the budget was made again from this very route: all of it is refreshed
                previos = [i for i in [(ruta["propiedades"] or {}).get("acometida_id"), (ruta["propiedades"] or {}).get("cliente_id"), *((ruta["propiedades"] or {}).get("postes_nuevos") or [])] if i]
                _borrar(con, actor, previos)
                hecho = _crear_acompanantes(con, actor, igual["id"], nombre, coordenadas, cliente, nuevos)
                props = {**(propiedades or {}), "origen": "presupuesto", "huella": huella, **_propiedades_ruta(hecho, cliente)}
                lugar = lugares.guardar_lugar(con, actor, id=ruta["id"], version=ruta["version"], geom=linea, propiedades=props, descripcion_html=html or "")
                return {"id": lugar["lugar"]["id"], "nombre": nombre, "accion": "actualizada", "carpeta_id": igual["id"], "postes_nuevos": len(hecho["postes_nuevos"])}
        usados = {c["nombre"] for c in carpetas}                                            # an edited one stays: the new one goes beside it
        titulo, accion = nombre, "creada"
        if igual is not None:
            n = 2
            while f"{nombre} ({n})" in usados:
                n += 1
            titulo, accion = f"{nombre} ({n})", "aparte"
        carpeta = lugares.guardar_carpeta(con, actor, nombre=titulo, padre_id=raiz)["id"]
        hecho = _crear_acompanantes(con, actor, carpeta, titulo, coordenadas, cliente, nuevos)
        props = {**(propiedades or {}), "origen": "presupuesto", "huella": huella, **_propiedades_ruta(hecho, cliente)}
        lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="ruta", nombre=titulo, estilo=ESTILO_RUTA, propiedades=props, geom=linea, descripcion_html=html)
        return {"id": lugar["lugar"]["id"], "nombre": titulo, "accion": accion, "carpeta_id": carpeta, "postes_nuevos": len(hecho["postes_nuevos"])}


def _propiedades_ruta(hecho: dict[str, Any], cliente: dict[str, Any] | None) -> dict[str, Any]:
    """What the route remembers of what was saved with it (ids of its companions, the exact client point)."""
    salida: dict[str, Any] = {"cliente_id": hecho["cliente_id"], "acometida_id": hecho["acometida_id"], "acometida_m": hecho["acometida_m"], "postes_nuevos": hecho["postes_nuevos"]}
    if cliente and cliente.get("lat") is not None and cliente.get("lon") is not None:
        salida["cliente_punto"] = {"lat": round(float(cliente["lat"]), 7), "lon": round(float(cliente["lon"]), 7)}
    return salida


# --------------------------------------------------------------------------- editar la ruta guardada

def _ruta(con: Any, ruta_id: int) -> dict[str, Any] | None:
    f = con.execute("SELECT id, nombre, carpeta_id, version, propiedades, ST_AsGeoJSON(geom, 8) AS g FROM redes.lugares_elementos "
                    "WHERE id = %s AND tipo = 'ruta' AND borrado_en IS NULL", (int(ruta_id),)).fetchone()
    return dict(f) if f and (f["propiedades"] or {}).get("origen") == "presupuesto" else None


def _postes_guardados(con: Any, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    filas = con.execute("SELECT id, nombre, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM redes.lugares_elementos WHERE id = ANY(%s) AND tipo = 'poste' AND borrado_en IS NULL ORDER BY id",
                        (list(ids),)).fetchall()
    return [dict(f) for f in filas]


def _clasificar_postes(postes: list[dict[str, Any]], linea: list[tuple[float, float]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(used, unused) saved new poles for a route: used = within the pole buffer of it."""
    umbral = umbral_poste_usado_m()
    usados, sin_uso = [], []
    for p in postes:
        (usados if distancia_a_linea_m((p["lat"], p["lon"]), linea) <= umbral else sin_uso).append(p)
    return usados, sin_uso


def al_editar_ruta(con: Any, actor: dict[str, Any], ruta_id: int) -> dict[str, Any] | None:
    """After the geometry of a budget route was saved: its drop follows the new end of the route, and the saved new poles it no longer uses are deleted.
    None when it is not a route of a budget. {"postes_borrados": n, "acometida_m": m}. Runs inside the caller's transaction."""
    ruta = _ruta(con, ruta_id)
    if ruta is None:
        return None
    props = dict(ruta["propiedades"] or {})
    linea = _linea_de(ruta["g"])
    usados, sin_uso = _clasificar_postes(_postes_guardados(con, props.get("postes_nuevos") or []), linea)
    _borrar(con, actor, [p["id"] for p in sin_uso])
    cambios: dict[str, Any] = {"postes_nuevos": [p["id"] for p in usados]}
    cliente = props.get("cliente_punto")
    if cliente and props.get("cliente_id"):
        clat, clon = float(cliente["lat"]), float(cliente["lon"])
        fin = [linea[-1][1], linea[-1][0]]
        metros = round(_metros(linea[-1], (clat, clon)), 1)
        cambios["acometida_m"] = metros
        acometida = con.execute("SELECT id, version FROM redes.lugares_elementos WHERE id = %s AND tipo = 'cable' AND borrado_en IS NULL", (props.get("acometida_id") or 0,)).fetchone()
        if metros >= ACOMETIDA_MIN_M and acometida is not None:
            lugares.guardar_lugar(con, actor, id=acometida["id"], version=acometida["version"], geom={"type": "LineString", "coordinates": [fin, [clon, clat]]},
                                  propiedades={"clase": "acometida", "tipo": "FLAT", "hilos": 2, "hilos_por_buffer": 2, "color": "#00e65a", "destino_id": props["cliente_id"]})
        elif metros >= ACOMETIDA_MIN_M:
            cambios["acometida_id"] = _crear_acometida(con, actor, ruta["carpeta_id"], fin, props["cliente_id"], clat, clon)
        elif acometida is not None:                                                        # the route now ends on the client: there is no drop
            _borrar(con, actor, [acometida["id"]])
            cambios["acometida_id"] = None
    repositorio.actualizar(con, "lugares_elementos", ruta["id"], ruta["version"], {"propiedades": Jsonb({**props, **cambios})}, actor["id"])
    return {"postes_borrados": len(sin_uso), "acometida_m": cambios.get("acometida_m", props.get("acometida_m"))}


def resumen_ruta(con: Any, actor: dict[str, Any], *, id: int, puntos: list[list[float]] | None = None) -> dict[str, Any]:
    """The numbers of a budget route as they would be with `puntos` ([lat, lon] of the edit in progress; the saved ones without it), like when a line is measured:
    length, reserve, final metres, drop to the client, total, existing poles on the way, new poles the rules ask for and which of the saved new poles are still used.
    Nothing is written. {"ok": true, "resumen": {...}} or an error."""
    lugares._del_elemento(con, actor, int(id))                                              # it must be visible to the user
    ruta = _ruta(con, id)
    if ruta is None:
        raise lugares.DatosInvalidos({"ruta": "No es la ruta de un presupuesto"})
    props = ruta["propiedades"] or {}
    linea = [(float(p[0]), float(p[1])) for p in puntos] if puntos else _linea_de(ruta["g"])
    if len(linea) < MIN_PUNTOS:
        raise lugares.DatosInvalidos({"ruta": "La ruta necesita al menos dos puntos"})
    resumen: dict[str, Any] = {"distancia_m": round(sum(_metros(a, b) for a, b in zip(linea, linea[1:])), 2)}
    cliente = props.get("cliente_punto")
    resumen["acometida_m"] = round(_metros(linea[-1], (float(cliente["lat"]), float(cliente["lon"]))), 1) if cliente else 0.0
    if resumen["acometida_m"] < ACOMETIDA_MIN_M:
        resumen["acometida_m"] = 0.0
    try:
        from visor_rutas import medicion
        vista = medicion.calcular([[a, b] for a, b in linea])
        resumen.update({"reserva_m": vista["reserva_m"], "metraje_final_m": vista["metraje_final_m"], "tipo_cable": vista["tipo_cable"],
                        "postes_existentes": vista["postes"]["existentes"], "postes_nuevos_necesarios": vista["postes"]["nuevos"], "postes_requeridos": vista["postes"]["requeridos"]})
        resumen["metraje_total_m"] = round(vista["metraje_final_m"] + resumen["acometida_m"], 2)
        if vista.get("avisos"):
            resumen["avisos"] = vista["avisos"]
    except Exception as exc:                                                                 # noqa: BLE001 - the saved data is still shown without the rules
        log.info("Presupuestos: el resumen de la ruta %s no pudo usar las reglas (%s)", id, type(exc).__name__)
        resumen["avisos"] = ["No se pudo calcular el metraje final ni los postes con las reglas del presupuesto"]
    guardados = _postes_guardados(con, props.get("postes_nuevos") or [])
    usados, sin_uso = _clasificar_postes(guardados, linea)
    resumen["puede_rehacer"] = bool(props.get("solicitud") and props.get("presupuesto"))        # the budget can be made again over its Excel from this route (its form data and file name were kept)
    resumen["postes_guardados"] = len(guardados)
    resumen["postes_guardados_usados"] = len(usados)
    resumen["postes_a_borrar"] = [{"id": p["id"], "nombre": p["nombre"]} for p in sin_uso]
    return {"resumen": resumen}


# --------------------------------------------------------------------------- quien llama

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
