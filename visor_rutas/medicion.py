"""Metraje y total de una medida hecha en el mapa (botón Medir del visor).

Una medida es una línea de dos o más puntos. Con las reglas de negocio de `business_rules.yaml` (las mismas del presupuesto) se
calcula, sin pedir nada a Google:
  - `calcular`: distancia, **metraje final** (con la reserva de conexión y el 20 % de cada bloque de 300 m), tipo de cable (Flat o
    ADSS según el umbral), postes existentes (los de `red_puntos` cerca de la línea) y nuevos, y las cantidades. Es instantáneo.
  - `estimar`: además llena la **misma plantilla de Excel** del presupuesto y la recalcula con LibreOffice, así que el **total** es
    exactamente el que daría un presupuesto con esas cantidades (los precios viven solo en la plantilla). Tarda unos segundos.

Qué se supone de una medida (`visor_medicion` en business_rules.yaml): la línea va de un punto a otro sin pasar por una mufa
(`mufas_intervenidas: 0`) y termina en una conexión de cliente (`conexiones_nuevas: 1`: un empalme, un ODF, rotulado y OTDR).
Servicio, ancho de banda y equipo son los de `visor_estimacion` (10 Mbps, GPON; Residencial hasta el umbral y Empresarial por
encima), como el presupuesto aproximado. Con la medida el visor no conoce un cliente ni un punto de conexión: el Excel lo dice.
"""
import logging
import math
import secrets
from datetime import datetime
from typing import Any

import main
from origen import _distance_m
from visor_rutas import presupuesto_visor

log = logging.getLogger(__name__)
MAX_PUNTOS = 500
POR_DEFECTO = {"conexiones_nuevas": 1, "mufas_intervenidas": 0}
LatLon = tuple[float, float]


class MedicionError(ValueError):
    """Medida no válida (se muestra tal cual en el visor)."""


def validar_puntos(puntos: Any) -> list[LatLon]:
    if not isinstance(puntos, (list, tuple)) or len(puntos) < 2:
        raise MedicionError("Una medida necesita al menos dos puntos")
    if len(puntos) > MAX_PUNTOS:
        raise MedicionError(f"Una medida puede tener hasta {MAX_PUNTOS} puntos")
    salida: list[LatLon] = []
    for p in puntos:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError, KeyError):
            raise MedicionError("Un punto de la medida no es válido") from None
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise MedicionError(f"Un punto de la medida está fuera del mundo: {lat}, {lon}")
        salida.append((lat, lon))
    return salida


def longitud_m(puntos: list[LatLon]) -> float:
    return sum(_distance_m(a[0], a[1], b[0], b[1]) for a, b in zip(puntos, puntos[1:]))


def _reglas() -> dict[str, Any]:
    return main.load_rules(main.settings.rules_path)


def _datos(puntos: list[LatLon], reglas: dict[str, Any]) -> dict[str, Any]:
    """Everything the rules give for the line (no Excel): the viewer's numbers and the quantities for the template."""
    avisos: list[str] = []
    distancia = longitud_m(puntos)
    final = main.calcular_metraje_final(distancia, reglas)
    supuestos = presupuesto_visor.supuestos_estimacion(final, reglas)
    config = {**POR_DEFECTO, **(reglas.get("visor_medicion") or {})}
    try:
        registros = main.db.deduplicate_existing_poles(main.db.find_existing_poles_near_route(
            main._route_linestring_wkt(puntos), reglas["poles"]["existing_pole_search_buffer_m"]))
    except (main.db.ExistingPolesQueryError, main.db.DatabaseError):
        registros = []
        avisos.append("No se pudieron consultar los postes existentes: se cuentan todos como nuevos")
    posiciones = [p.route_position_m for p in registros]
    cantidades = main.calcular_presupuesto(
        distancia, puntos, reglas, service_type=supuestos["service_type"], bandwidth=supuestos["bandwidth"],
        existing_poles=len(registros), existing_pole_positions_m=posiciones, connection_is_mufa=False, connection_is_reserve=False,
        mufa_count=int(config["mufas_intervenidas"]), new_connections=int(config["conexiones_nuevas"]))
    etiqueta_nuevo = reglas["poles"]["new_pole_row_label"]
    nuevos = cantidades[etiqueta_nuevo]
    requeridos = len(registros) + nuevos
    materiales = main.calcular_materiales(final, requeridos, reglas)
    if distancia / 1000 > float(reglas.get("budget_alerts", {}).get("distance_threshold_km", 5.0)):
        avisos.append("La medida supera los 5 km")
    return {
        "puntos": puntos, "distancia": distancia, "final": final, "supuestos": supuestos, "config": config, "cantidades": cantidades,
        "materiales": materiales, "nuevos": nuevos, "registros": registros, "avisos": avisos,
        "vista": {
            "distancia_m": round(distancia, 2), "metraje_final_m": round(final, 2), "reserva_m": round(final - distancia, 2),
            "tipo_cable": materiales["cable_type"], "umbral_m": reglas["cable"]["adss_threshold_m"],
            "postes": {"existentes": len(registros), "nuevos": nuevos, "requeridos": requeridos,
                       "separacion_m": reglas["poles"]["spacing_m"], "giros": main.count_turns(puntos, reglas["poles"]["corner_angle_deg"])},
            "supuestos": {"servicio": supuestos["service_type"], "ancho_de_banda": supuestos["bandwidth"],
                          "conexiones_nuevas": int(config["conexiones_nuevas"]), "mufas_intervenidas": int(config["mufas_intervenidas"])},
            "avisos": avisos,
        },
    }


def calcular(puntos: Any) -> dict[str, Any]:
    """Metraje final, cable y postes de la línea (instantáneo, sin Excel ni Google)."""
    pts = validar_puntos(puntos)
    return _datos(pts, _reglas())["vista"]


def estimar(puntos: Any, ahora: datetime | None = None) -> dict[str, Any]:
    """Lo mismo y además el total: llena la plantilla de Excel y la recalcula (LibreOffice). Devuelve
    {"medicion", "supuestos" (como el presupuesto aproximado), "resultado" (lo de presupuesto_visor.resultado_para_visor)}."""
    pts = validar_puntos(puntos)
    ahora = ahora or datetime.now()
    reglas = _reglas()
    d = _datos(pts, reglas)
    supuestos, cantidades, materiales = d["supuestos"], d["cantidades"], d["materiales"]
    tecnologia, _ = main.seleccionar_tecnologia(supuestos["bandwidth"], None, "", reglas)
    equipos = main.calcular_equipos(tecnologia, None, reglas)
    supuestos = {**supuestos, "technology": tecnologia, "cable": materiales["cable_type"]}
    inicio, fin = pts[0], pts[-1]
    ticket = f"MEDICION-{ahora:%Y%m%d-%H%M%S}"
    nuevos_material = {reglas["poles"]["new_pole_material_row_label"]: d["nuevos"]}
    datos_excel = {
        "budget_id": secrets.token_hex(16), "ticket_id": ticket, "client_name": "Medición del visor",
        "raw_comment": f"Medición de {len(pts)} puntos, {d['distancia']:,.1f} m (no es un presupuesto de un cliente)",
        "quantities": cantidades, "materials": {**equipos, **nuevos_material},
        "hardware": {**reglas["cable"].get("fiber_material_from_install", {}),
                     **reglas["cable"].get("hardware_by_cable_type", {}).get(materiales["cable_key"], {})},
        "route_fields": {"origin_node": "", "traffic_node": "Sin definir (medición)", "ticket_id": ticket,
                         "connection_point": f"{inicio[0]:.6f}, {inicio[1]:.6f} (inicio de la medición)",
                         "client_coordinates": f"{fin[0]:.6f}, {fin[1]:.6f} (fin de la medición)",
                         "sales_exec": "Estimación visor", "client_code": "Estimación visor", "contact_name": "Estimación visor",
                         "contact_phone": "Estimación visor"},
    }
    carpeta = presupuesto_visor.carpeta_visor()
    carpeta.mkdir(parents=True, exist_ok=True)
    presupuesto_visor.limpiar_archivos_viejos(carpeta)
    generado = main.generar_excel(datos_excel, reglas, main.settings.template_path, carpeta)
    avisos = list(d["avisos"]) + list(generado.warnings)
    calculado = False
    soffice = main.recalc.find_soffice(main.settings.libreoffice_path)
    if soffice is None:
        avisos.append("LibreOffice no disponible: los montos se ven al abrir el Excel")
    else:
        try:
            main.recalc.cache_formula_values(generado.path, ["Presupuesto", reglas["route_sheet"]["sheet"]], soffice)
            calculado = True
        except main.recalc.RecalcError as exc:
            avisos.append(f"Los totales del Excel no se pudieron calcular: {exc}")
    destino = carpeta / presupuesto_visor._nombre_archivo("Medicion", inicio[0], inicio[1], ahora)
    if destino.exists():
        destino.unlink()
    generado.path.replace(destino)
    respuesta = {
        "budget_id": datos_excel["budget_id"], "ticket_id": ticket, "distance_km": round(d["distancia"] / 1000, 3), "status": "ok",
        "connection_point": None, "route": {"distance_m": round(d["distancia"], 2), "duration_s": None, "turns": d["vista"]["postes"]["giros"]},
        "budget": {"cable_type": materiales["cable_type"], "final_distance_m": d["final"], "new_poles_8m": d["nuevos"]},
        "equipment": {"technology": tecnologia, "items": equipos}, "traffic_origin": {}, "quantities": cantidades,
        "pending_validation_items": [{"item": i, "quantity": cantidades.get(i, 0)} for i in reglas.get("manual_zero_row_labels", [])],
        "pending_validation_fields": [], "pending_validation_poles": [], "values_cached": calculado, "warnings": avisos,
        "excel_path": str(destino),
    }
    log.info("Visor: measurement of %d points, %.1f m -> final %.1f m, saved as %s", len(pts), d["distancia"], d["final"], destino.name)
    return {"medicion": d["vista"], "supuestos": supuestos, "resultado": presupuesto_visor.resultado_para_visor(respuesta)}
