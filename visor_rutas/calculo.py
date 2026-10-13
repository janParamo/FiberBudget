"""Cálculo del visor de rutas: mismo punto de conexión, ruta, postes y mufas que el presupuesto.

Llama a las funciones del servicio (main.py y sus módulos) sin modificarlas y con las mismas
reglas de business_rules.yaml. No genera Excel, PDF ni mapas, y no escribe en output/.

Diferencias con POST /presupuesto, solo para que el visor siempre muestre algo:
  - Sin Google (falla, sin internet o sin ruta): línea recta conexión -> cliente y un aviso.
  - Si falla la consulta de postes, mufas o cadena: se sigue con un aviso (el presupuesto
    respondería 500 en ese caso).
"""
import logging
import math
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import psycopg
import requests
from fastapi import HTTPException

import db
import main
import presupuesto
import red_fibra_pg
import routing
from config import NI_LAT_MAX, NI_LAT_MIN, NI_LON_MAX, NI_LON_MIN
from origen import _distance_m
from visor_rutas import fusion

log = logging.getLogger(__name__)

AVISO_SIN_GOOGLE = "Ruta aproximada (sin Google)"
LatLon = tuple[float, float]


class VisorError(Exception):
    """Error que se muestra tal cual en la barra del visor."""


class CoordenadaInvalida(VisorError):
    """Texto que no es una coordenada, o coordenada fuera de Nicaragua."""


class SinPuntoConexion(VisorError):
    """No hay mufa, reserva ni nodo Visio para conectar al cliente."""


# --------------------------------------------------------------------------- coordenadas

def _en_nicaragua(lat: float, lon: float) -> bool:
    return NI_LAT_MIN <= lat <= NI_LAT_MAX and NI_LON_MIN <= lon <= NI_LON_MAX


def validar_coordenadas(lat: float, lon: float) -> None:
    """Lanza CoordenadaInvalida si (lat, lon) cae fuera de Nicaragua (avisa si parecen invertidas)."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise CoordenadaInvalida("Coordenada no válida")
    if _en_nicaragua(lat, lon):
        return
    if _en_nicaragua(lon, lat):
        raise CoordenadaInvalida(
            f"Las coordenadas parecen invertidas: ({lat}, {lon}). "
            f"Escriba primero la latitud y luego la longitud, por ejemplo {lon}, {lat}")
    raise CoordenadaInvalida(
        f"La coordenada ({lat}, {lon}) está fuera de Nicaragua "
        f"(latitud {NI_LAT_MIN}..{NI_LAT_MAX}, longitud {NI_LON_MIN}..{NI_LON_MAX})")


def parsear_coordenadas(texto: str) -> LatLon:
    """'12.153328, -86.263438' -> (12.153328, -86.263438). Separador: coma, espacio o punto y coma."""
    limpio = (texto or "").strip().strip("()[]")
    partes = [p for p in re.split(r"[,;\s]+", limpio) if p]
    if len(partes) != 2:
        raise CoordenadaInvalida(
            "Escriba latitud y longitud separadas por coma, espacio o punto y coma "
            "(ejemplo: 12.153328, -86.263438)")
    try:
        lat, lon = float(partes[0]), float(partes[1])
    except ValueError:
        raise CoordenadaInvalida(f"No se reconoce la coordenada: {texto.strip()!r}") from None
    validar_coordenadas(lat, lon)
    return lat, lon


# --------------------------------------------------------------------------- geometría

def _longitudes_acumuladas(puntos: list[LatLon]) -> list[float]:
    acumulada = [0.0]
    for a, b in zip(puntos, puntos[1:]):
        acumulada.append(acumulada[-1] + _distance_m(a[0], a[1], b[0], b[1]))
    return acumulada


def _punto_en_ruta(puntos: list[LatLon], acumulada: list[float], fraccion: float) -> LatLon:
    """Punto a `fraccion` (0..1) de la longitud de la ruta, interpolado linealmente."""
    objetivo = max(0.0, min(1.0, fraccion)) * acumulada[-1]
    for i in range(1, len(puntos)):
        if acumulada[i] >= objetivo:
            tramo = acumulada[i] - acumulada[i - 1]
            t = 0.0 if tramo <= 0 else (objetivo - acumulada[i - 1]) / tramo
            (lat1, lon1), (lat2, lon2) = puntos[i - 1], puntos[i]
            return lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t
    return puntos[-1]


def posiciones_postes_nuevos(distance_m: float, spacing_m: float, existing_positions_m: list[float],
                             max_span_m: float | None = None) -> list[float]:
    """Metro de la ruta de cada poste nuevo por huecos.

    Es presupuesto.new_pole_positions_by_gaps, el mismo recorrido que cuenta los postes nuevos
    (sin los postes extra por esquina, que no tienen posición); el visor comprueba que la
    cantidad coincida. Esos metros identifican el poste que se marca como existente en el mapa.
    """
    return presupuesto.new_pole_positions_by_gaps(distance_m, spacing_m, existing_positions_m, max_span_m)


# --------------------------------------------------------------------------- consultas

def _coords_visio_por_nombre(nombres: list[str], visio_con: Any, cerca_de: LatLon) -> dict[str, LatLon]:
    """Coordenadas de mufas de los diagramas por nombre (la más cercana si se repite)."""
    if not nombres:
        return {}
    rows = None
    if visio_con is not None:
        try:
            rows = visio_con.execute(
                "SELECT nombre, lat, lon FROM nodos WHERE nombre = ANY(%s) AND lat IS NOT NULL",
                (list(nombres),)).fetchall()
        except psycopg.Error as exc:
            log.warning("Visio mufa coordinates query failed (%s)", type(exc).__name__)
    if rows is None:
        archivo = main.settings.red_fibra_db
        if archivo.is_file():
            try:
                con = sqlite3.connect(f"{archivo.resolve().as_uri()}?mode=ro", uri=True)
                try:
                    marcas = ",".join("?" * len(nombres))
                    rows = con.execute(
                        f"SELECT nombre, lat, lon FROM nodos WHERE nombre IN ({marcas}) AND lat IS NOT NULL",
                        list(nombres)).fetchall()
                finally:
                    con.close()
            except sqlite3.Error as exc:
                log.warning("SQLite mufa coordinates query failed (%s)", type(exc).__name__)
    coords: dict[str, LatLon] = {}
    for nombre, lat, lon in rows or []:
        punto = (float(lat), float(lon))
        actual = coords.get(nombre)
        if actual is None or (_distance_m(*cerca_de, *punto) < _distance_m(*cerca_de, *actual)):
            coords[nombre] = punto
    return coords


def _resolver(lat: float, lon: float, rules: dict[str, Any], visio_con: Any,
              avisos: list[str]) -> tuple[db.Segment | None, red_fibra_pg.BusquedaVisio, bool]:
    """main._resolver_conexion; si la base KMZ falla se repite con tolerancia y se avisa."""
    try:
        return main._resolver_conexion(lat, lon, rules, visio_con)
    except HTTPException:
        avisos.append("La base KMZ (PostGIS) no respondió: el punto de conexión sale solo de la red Visio")
        return main._resolver_conexion(lat, lon, rules, visio_con, tolerate_kmz_errors=True)


def _tipo_conexion(seg: db.Segment, desde_visio: bool) -> str:
    if desde_visio:
        return "nodo Visio"
    if seg.is_mufa:
        return "mufa"
    if seg.is_reserve:
        return "reserva"
    return seg.tipo or "punto de red"


# --------------------------------------------------------------------------- cálculo

# Route function for the current call only (the viewer's per-session cache); set with usando_rutas().
_get_route_activo: ContextVar[Any] = ContextVar("get_route_visor", default=None)


@contextmanager
def usando_rutas(get_route: Any) -> Iterator[None]:
    """Within this block calcular_ruta() uses `get_route` (e.g. the viewer's route cache)."""
    token = _get_route_activo.set(get_route)
    try:
        yield
    finally:
        _get_route_activo.reset(token)


def calcular_ruta(lat: float, lon: float, get_route: Any = None) -> dict[str, Any]:
    """Punto de conexión, ruta, postes, mufas y origen de tráfico para el cliente (lat, lon).

    get_route: routing.get_route, o el caché de rutas del visor (presupuesto_visor.CacheRutas)
    para que el presupuesto aproximado de la misma coordenada no vuelva a llamar a Google.
    Sin argumento se usa el que esté activo con usando_rutas(), si hay uno.
    """
    get_route = get_route or _get_route_activo.get()
    validar_coordenadas(lat, lon)
    rules = main.load_rules(main.settings.rules_path)
    avisos: list[str] = []
    visio_con = red_fibra_pg.connect_or_none()
    if visio_con is None:
        avisos.append("Base Visio no disponible: se usó solo el KMZ" if red_fibra_pg.enabled()
                      else "Base Visio desactivada (VISIO_DB_NAME vacío): se usó solo el KMZ")
    try:
        return _calcular(lat, lon, rules, visio_con, avisos, get_route or routing.get_route)
    finally:
        if visio_con is not None:
            visio_con.close()


def _calcular(lat: float, lon: float, rules: dict[str, Any], visio_con: Any,
              avisos: list[str], get_route: Any = None) -> dict[str, Any]:
    get_route = get_route or routing.get_route
    log.info("Visor: route for (%.6f, %.6f)", lat, lon)

    # 1) Punto de conexión (misma función que el presupuesto).
    seg, busqueda, desde_visio = _resolver(lat, lon, rules, visio_con, avisos)
    if busqueda.fuente == red_fibra_pg.SIN_CONEXION and visio_con is not None:
        avisos.append("La consulta a la base Visio falló: se usó solo el KMZ")
    if seg is None:
        raise SinPuntoConexion("No se encontró mufa, reserva ni nodo de red para esta coordenada")

    # 2) Ruta por calle; sin Google, línea recta.
    aproximada = False
    try:
        route = get_route(origin=(seg.lat, seg.lon), destination=(lat, lon))
        puntos, distancia_m = list(route.points), route.distance_m
    except (routing.RoutingError, routing.RouteNotFound, requests.RequestException) as exc:
        log.warning("Visor: Directions unavailable (%s: %s); straight line", type(exc).__name__, exc)
        aproximada = True
        puntos = [(seg.lat, seg.lon), (lat, lon)]
        distancia_m = _distance_m(seg.lat, seg.lon, lat, lon)
        detalle = "Google no encontró ruta" if isinstance(exc, routing.RouteNotFound) else \
            "Google no respondió o no hay internet"
        avisos.append(f"{AVISO_SIN_GOOGLE}: {detalle}; se muestra la línea recta y el metraje real será mayor")
    # Igual que el presupuesto: si la más cercana da mucha vuelta por calle o no tiene hilos, se
    # comparan las mufas cercanas por metraje de ruta (sin Google no se puede comparar).
    seleccion = None
    if not aproximada:
        seg, route, seleccion = main._elegir_por_ruta(seg, desde_visio, lat, lon, rules, visio_con, route,
                                                      get_route)
        puntos, distancia_m = list(route.points), route.distance_m
    elif not desde_visio and (motivo := main._no_disponible(seg, rules, visio_con)):
        avisos.append(f"Punto de conexión {seg.nombre or seg.id} marcado {motivo}: validar con Planta Externa")
    if (aviso := main._aviso_seleccion(seleccion)) is not None:
        avisos.append(aviso)
    if len(puntos) < 2:
        puntos = [(seg.lat, seg.lon), (lat, lon)]
    route_wkt = main._route_linestring_wkt(puntos)

    # 3) Mufas sobre la ruta.
    try:
        route_mufas = db.find_mufas_near_route(
            route_wkt, rules.get("fixed_events", {}).get("route_mufa_search_buffer_m", 15),
            rules["excluded_tipo_keywords"])
    except db.ExistingPolesQueryError:
        route_mufas = []
        avisos.append("No se pudieron consultar las mufas de la ruta (el presupuesto fallaría)")

    # 4) Cadena aguas arriba y origen de tráfico: igual que main._generar_presupuesto_con.
    distribution_reason = None
    if desde_visio:
        chain = [db.ChainMufa(seg.id, seg.nombre)]
    elif seg.is_mufa:
        try:
            chain = db.find_upstream_mufa_chain(
                seg.id, seg.nombre, rules["excluded_tipo_keywords"],
                rules["connection"].get("upstream_chain", {}))
            distribution_reason = chain[-1].distribution_reason
        except db.DatabaseError:
            chain = [db.ChainMufa(seg.id, seg.nombre)]
            avisos.append("No se pudo consultar la cadena de mufas aguas arriba (el presupuesto fallaría)")
    else:
        chain = []
    origin, _ = main._traffic_origin(seg, chain[:1] if desde_visio else chain, rules, visio_con)

    # Mufas intervenidas: copia de main._generar_presupuesto_con (test_visor_rutas compara ambos).
    intervened: dict[Any, str | None] = {}
    use_diagram_path = (seg.is_mufa and origin.path_traced
                        and rules.get("traffic_origin", {}).get("count_path_mufas", True))
    if use_diagram_path:
        intervened[seg.id] = seg.nombre
        intervened.update((f"diagrama:{name}", name) for name in origin.path[1:])
        mufa_count_source = "diagramas"
    else:
        intervened.update((mufa.id, mufa.nombre) for mufa in chain)
        mufa_count_source = "postgis" if seg.is_mufa else None
    for mufa in route_mufas:
        intervened.setdefault(mufa.id, mufa.nombre)

    # 5) Postes existentes y cantidades (mismas funciones que el presupuesto).
    try:
        poles = db.deduplicate_existing_poles(db.find_existing_poles_near_route(
            route_wkt, rules["poles"]["existing_pole_search_buffer_m"]))
    except db.ExistingPolesQueryError:
        poles = []
        avisos.append("No se pudieron consultar los postes existentes; se asumen 0 (el presupuesto fallaría)")
    pole_positions_m = [pole.route_position_m for pole in poles]
    quantities = presupuesto.calcular_presupuesto(
        distancia_m, puntos, rules,
        existing_poles=len(poles),
        existing_pole_positions_m=pole_positions_m,
        connection_is_mufa=seg.is_mufa,
        connection_is_reserve=seg.is_reserve,
        mufa_count=len(intervened),
        new_connections=1,
    )
    poles_rules = rules["poles"]
    nuevos = quantities[poles_rules["new_pole_row_label"]]
    final_m = presupuesto.calcular_metraje_final(distancia_m, rules)
    materials = presupuesto.calcular_materiales(final_m, len(poles) + nuevos, rules)

    # Posiciones aproximadas de los postes nuevos sobre la ruta.
    turns = presupuesto.count_turns(puntos, poles_rules["corner_angle_deg"])
    extra_esquinas = turns * poles_rules["extra_poles_per_corner"]
    metros = posiciones_postes_nuevos(distancia_m, poles_rules["spacing_m"], pole_positions_m,
                                      poles_rules.get("max_span_m"))
    posiciones: list[LatLon] = []
    metros_mapa: list[float] = []
    if len(metros) + extra_esquinas == nuevos and distancia_m > 0:
        acumulada = _longitudes_acumuladas(puntos)
        if acumulada[-1] > 0:
            posiciones = [_punto_en_ruta(puntos, acumulada, m / distancia_m) for m in metros]
            metros_mapa = [round(m, 2) for m in metros]
        if extra_esquinas:
            avisos.append(f"{extra_esquinas} poste(s) nuevo(s) por esquina sin posición en el mapa")
    elif nuevos:
        avisos.append("No se pudo ubicar los postes nuevos en el mapa; solo se muestra la cantidad")

    # 6) Bloque "origen" del presupuesto: revisión, notas y nodos Visio.
    origen_block = main._origen_block(seg, busqueda, desde_visio, origin, rules, distancia_m)
    leyenda = red_fibra_pg.leyenda_punto_conexion(origen_block).strip(" ()")
    notas = [n for n in (origen_block.get("notas"), leyenda or None) if n]
    if seleccion and seleccion.get("cambiada"):
        otras = ", ".join(f"{e['nombre']} {e['ruta_m']:.0f} m" if e["ruta_m"] is not None
                          else f"{e['nombre']}: {e['motivo']}" for e in seleccion["evaluados"]
                          if e["id"] != seg.id)
        notas.insert(0, f"Elegida por ruta más corta ({distancia_m:.0f} m); comparadas: {otras}")
    if origen_block["requiere_revision"] or origen_block["sin_punto_cercano"]:
        avisos.append("Punto de conexión: " + (leyenda or "requiere revisión"))
    if origen_block.get("mensaje") and busqueda.fuente != red_fibra_pg.SIN_CONEXION:
        avisos.append(f"Red Visio: {origen_block['mensaje']}")

    # Origen de tráfico (el motivo ya trae el diagnóstico cuando no hubo mufa por coordenada).
    if origin.node is None:
        avisos.append(f"Origen de tráfico no encontrado ({origin.reason or 'sin motivo'})")
    elif origin.match_method in ("c", "d"):
        archivo = (origin.name_match or {}).get("archivo")
        avisos.append("Origen de tráfico con confianza baja: mufa de conexión emparejada por nombre"
                      + (f" en el diagrama {archivo}" if archivo else "") + "; validar")
    elif origin.confidence == "baja":
        avisos.append("Origen de tráfico con confianza baja: validar")
    if origin.saturated_mufas:
        avisos.append("Mufas marcadas SATURADA en el camino al nodo: " + ", ".join(origin.saturated_mufas))

    umbral_km = float(rules.get("budget_alerts", {}).get("distance_threshold_km", 5.0))
    if distancia_m / 1000 > umbral_km:
        avisos.append(f"La ruta supera {umbral_km:g} km")

    # Coordenadas de las mufas intervenidas, cuando existen.
    coords: dict[Any, LatLon] = {seg.id: (seg.lat, seg.lon)}
    coords.update({m.id: (m.lat, m.lon) for m in route_mufas})
    ids_postgis = [mid for mid in intervened if mid not in coords and not str(mid).startswith(("diagrama:", "visio:"))]
    try:
        coords.update(db.find_point_coords(ids_postgis))
    except db.DatabaseError:
        pass
    por_nombre = _coords_visio_por_nombre(
        [n for mid, n in intervened.items() if str(mid).startswith("diagrama:") and n], visio_con, (seg.lat, seg.lon))
    nombres_cadena = {m.id: m.nombre for m in chain}

    def nombre_mufa(mid: Any) -> str | None:
        return intervened.get(mid) or nombres_cadena.get(mid)

    mufas_intervenidas = []
    for mid, nombre in intervened.items():
        punto = coords.get(mid) or (por_nombre.get(nombre) if nombre else None)
        mufas_intervenidas.append({"id": mid, "nombre": nombre or f"Mufa {mid}",
                                   "lat": punto[0] if punto else None, "lon": punto[1] if punto else None})

    # Nodos Visio cercanos, sin el que ya es el punto de conexión.
    same_point_m = float(rules.get("route_map", {}).get("same_point_m", 15))
    candidatos = busqueda.alternativas if desde_visio else [n for n in [busqueda.nodo] if n] + busqueda.alternativas
    nodos = [{"nombre": n["nombre"], "tipo": n["tipo"], "lat": float(n["lat"]), "lon": float(n["lon"]),
              "distancia_m": round(float(n["distancia_m"]), 1), "notas": n.get("notas")}
             for n in candidatos
             if _distance_m(seg.lat, seg.lon, float(n["lat"]), float(n["lon"])) > same_point_m]

    resultado = {
        "cliente": {"lat": lat, "lon": lon},
        "conexion": {
            "nombre": seg.nombre or seg.tipo or f"Punto {seg.id}",
            "tipo": _tipo_conexion(seg, desde_visio),
            "tipo_detalle": seg.tipo,
            "id": seg.id,
            "lat": seg.lat,
            "lon": seg.lon,
            "distancia_lineal_m": round(seg.distance_m, 1),
            "fuente": "red_fibra" if desde_visio else "kmz",
            "requiere_revision": bool(origen_block["requiere_revision"] or origen_block["sin_punto_cercano"]),
            "notas": "; ".join(notas) or None,
        },
        "ruta": {
            "puntos": puntos,
            "distancia_m": round(distancia_m, 2),
            "metraje_final_m": final_m,
            "reserva_m": round(final_m - distancia_m, 2),
            "tipo_cable": materials["cable_type"],
            "aproximada": aproximada,
            # Drop from where Google snaps the route to the road to the client's coordinate
            # (drawn like mapa_ruta.py does in the Excel map; not part of the route metres).
            "acometida_m": round(_distance_m(puntos[-1][0], puntos[-1][1], lat, lon), 1),
        },
        "postes_existentes": [(pole.id, pole.lat, pole.lon) for pole in poles],
        # metros: route position of each pole in posiciones (it identifies the poles marked as
        # existing on the map when the budget is generated: presupuesto.match_marked_poles)
        "postes_nuevos": {"cantidad": nuevos, "posiciones": posiciones, "metros": metros_mapa,
                          "spacing_m": poles_rules["spacing_m"]},
        "mufas_en_ruta": [{"id": m.id, "nombre": nombre_mufa(m.id) or f"Mufa {m.id}", "tipo": m.tipo,
                           "lat": m.lat, "lon": m.lon, "distancia_m": round(m.distance_m, 1),
                           "troncal": m.is_backbone} for m in route_mufas],
        "mufas_intervenidas": mufas_intervenidas,
        "mufas_intervenidas_fuente": mufa_count_source,
        "distribution_reason": distribution_reason,
        "nodos_visio_cercanos": nodos,
        "origen_trafico": {"nodo": origin.node, "mf": origin.origin_mufa, "confianza": origin.confidence,
                           "camino": list(origin.path), "motivo": origin.reason,
                           # added for the fusion route: the diagram text the node was read from
                           "etiqueta": origin.label, "mufa_etiquetada": origin.labelled_mufa,
                           # how the connection mufa was matched (a..e), and why not by coordinate
                           "metodo": origin.match_method, "emparejamiento": origin.name_match,
                           "diagnostico": origin.diagnostico},
        "avisos": avisos,
    }

    # 7) Ruta de fusión (solo datos de la base de diagramas); nunca rompe el cálculo de la ruta.
    try:
        resultado["ruta_fusion"] = fusion.ruta_fusion(resultado["origen_trafico"], resultado["conexion"],
                                                      visio_con=visio_con, archivo_sqlite=main.settings.red_fibra_db,
                                                      avisos=avisos)
    except Exception as exc:
        log.warning("Visor: fusion route failed (%s: %s)", type(exc).__name__, exc)
        resultado["ruta_fusion"] = []
        avisos.append(f"No se pudo armar la ruta de fusión ({type(exc).__name__})")
    return resultado
