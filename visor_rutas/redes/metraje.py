"""Metraje de los cables del diseño de red (business_rules.yaml, sección diseno_red).

    metraje = distancia lineal + contingencia + salida de nodo + reservas por mufa, por tendido,
              por cruce y por extremo en cliente; redondeado hacia arriba al metro.

Por decisión de Jan (9 oct 2026) los valores son los mismos de las reglas de ruta del presupuesto.
La página calcula lo mismo en JavaScript (web/redes/editor_mapa.js) para mostrarlo al pasar el
mouse; el servidor lo vuelve a calcular al guardar y es el que se guarda.
"""
import math
from typing import Any

R_TIERRA_M = 6_371_008.8
POR_DEFECTO = {"contingencia_porcentaje": 0.0, "contingencia_m": 0, "salida_nodo_m": 0, "reserva_por_mufa_m": 35,
               "reserva_tendido_intervalo_m": 300, "reserva_tendido_porcentaje": 0.20, "reserva_por_cruce_m": 0,
               "reserva_extremo_cliente_m": 0}


def reglas(rules: dict[str, Any] | None) -> dict[str, float]:
    """diseno_red of business_rules.yaml, with the defaults for missing keys."""
    datos = {**POR_DEFECTO, **((rules or {}).get("diseno_red") or {})}
    return {k: float(datos[k]) for k in POR_DEFECTO}


def longitud_m(puntos: list[tuple[float, float]]) -> float:
    """Geodesic length of [(lat, lon), ...] (haversine, as the rest of the service)."""
    total = 0.0
    for (la1, lo1), (la2, lo2) in zip(puntos, puntos[1:]):
        p1, p2 = math.radians(la1), math.radians(la2)
        dp, dl = p2 - p1, math.radians(lo2 - lo1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * R_TIERRA_M * math.asin(math.sqrt(min(1.0, a)))
    return total


def calcular(lineal_m: float, extremos: list[str], cruces: int, regla: dict[str, float]) -> dict[str, Any]:
    """Detail of one cable. extremos: the element types at its two ends (mufa / nodo / cliente / poste)."""
    lineal = max(0.0, float(lineal_m))
    n_mufa = sum(1 for t in extremos if t == "mufa")
    n_nodo = sum(1 for t in extremos if t == "nodo")
    n_cliente = sum(1 for t in extremos if t == "cliente")
    intervalo = regla["reserva_tendido_intervalo_m"]
    n_tendido = math.ceil(round(lineal / intervalo, 6)) if intervalo > 0 and lineal > 0 else 0
    detalle = {
        "distancia_lineal_m": round(lineal, 1),
        "contingencia_m": round(lineal * regla["contingencia_porcentaje"] + regla["contingencia_m"], 1),
        "salida_nodo_m": round(n_nodo * regla["salida_nodo_m"], 1),
        "reservas_mufa": {"cantidad": n_mufa, "unidad_m": regla["reserva_por_mufa_m"],
                          "total_m": round(n_mufa * regla["reserva_por_mufa_m"], 1)},
        "reservas_tendido": {"cantidad": n_tendido, "intervalo_m": intervalo, "porcentaje": regla["reserva_tendido_porcentaje"],
                             "total_m": round(n_tendido * intervalo * regla["reserva_tendido_porcentaje"], 1)},
        "reservas_cruce": {"cantidad": int(cruces or 0), "unidad_m": regla["reserva_por_cruce_m"],
                           "total_m": round(int(cruces or 0) * regla["reserva_por_cruce_m"], 1)},
        "reservas_cliente": {"cantidad": n_cliente, "unidad_m": regla["reserva_extremo_cliente_m"],
                             "total_m": round(n_cliente * regla["reserva_extremo_cliente_m"], 1)},
    }
    suma = (lineal + detalle["contingencia_m"] + detalle["salida_nodo_m"] + detalle["reservas_mufa"]["total_m"]
            + detalle["reservas_tendido"]["total_m"] + detalle["reservas_cruce"]["total_m"]
            + detalle["reservas_cliente"]["total_m"])
    detalle["metraje_m"] = math.ceil(round(suma, 6))
    return detalle
