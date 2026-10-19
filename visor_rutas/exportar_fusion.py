"""«Exportar al Excel» de la ruta de fusión: valida el plan editado y agrega su franja al libro de rutas de fusión.

El libro es `RUTA_FUSION_XLSX` (por defecto la copia del proyecto; luego el de la nube). Se escribe solo en la hoja "2025 - 2026", al final,
con respaldo previo en output/ruta_fusion_respaldos y sin tocar lo que ya existe (ver ruta_fusion_xlsx.py). El cliente va vacío si el
presupuesto fue a mano y con el nombre del ticket si viene de uno; Cuadrilla y Diagramas quedan vacíos; la fecha es hoy (Jan la cambia en el
libro). Si se pide el mapa, se genera el mismo mapa satelital del presupuesto y va bajo «RUTA SUGERIDA» (si no hay internet, sin mapa y se avisa).
"""
import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import main
from visor_rutas import ruta_fusion_plan, ruta_fusion_xlsx

log = logging.getLogger(__name__)


def _mapa(opciones: dict[str, Any], avisos: list[str]) -> bytes | None:
    datos = opciones.get("mapa")
    if not opciones.get("con_mapa") or not isinstance(datos, dict):
        return None
    try:
        import mapa_ruta
        from visor_rutas.calculo import validar_ruta
        puntos = validar_ruta(datos.get("ruta"))
        conexion, cliente = datos.get("conexion") or {}, datos.get("cliente") or {}
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "mapa.png"
            ruta = mapa_ruta.generar_mapa_ruta(
                puntos, {"nombre": conexion.get("nombre") or "Conexión", "lat": float(conexion["lat"]), "lon": float(conexion["lon"])},
                {"nombre": opciones.get("cliente") or "Cliente", "lat": float(cliente["lat"]), "lon": float(cliente["lon"])}, [], False, destino,
                postes=[], distancia_ruta_m=float(datos.get("distancia_m") or 0) or None, timeout_s=8.0)
            if ruta is None or not Path(ruta).is_file():
                avisos.append("No se pudo generar el mapa de la ruta (sin internet o sin imágenes): la franja se agregó sin mapa")
                return None
            return Path(ruta).read_bytes()
    except Exception as exc:
        log.warning("Fusion route: map failed (%s: %s)", type(exc).__name__, exc)
        avisos.append("No se pudo generar el mapa de la ruta: la franja se agregó sin mapa")
        return None


def exportar_fusion(plan: dict[str, Any], opciones: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = ruta_fusion_plan.redactar(plan)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not plan["lineas"]:
        return {"ok": False, "error": "No hay mufas que intervenir: marque al menos una mufa para escribir la ruta de fusión"}
    try:
        fecha = date.fromisoformat(str(opciones.get("fecha") or "")) if opciones.get("fecha") else date.today()
    except ValueError:
        return {"ok": False, "error": "La fecha no es válida (AAAA-MM-DD)"}
    cliente = " ".join(str(opciones.get("cliente") or "").split())[:300] or None
    avisos: list[str] = []
    imagen = _mapa(opciones, avisos)
    regla = (main.load_rules(main.settings.rules_path).get("ruta_fusion") or {})
    try:
        r = ruta_fusion_xlsx.agregar_franja(
            main.settings.ruta_fusion_xlsx, fecha=fecha, cliente=cliente, lineas=plan["lineas"], avisos=plan["avisos_rojos"],
            compartir=plan["compartir_potencia"], imagen=imagen, respaldos=main.settings.output_dir / "ruta_fusion_respaldos",
            conservar=int(regla.get("respaldos_a_conservar", 10)))
    except ruta_fusion_xlsx.ExcelAbierto as exc:
        return {"ok": False, "error": str(exc), "abierto": True}
    except ruta_fusion_xlsx.LibroNoValido as exc:
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        log.exception("Fusion route: workbook could not be written")
        return {"ok": False, "error": f"No se pudo escribir el libro de rutas de fusión ({type(exc).__name__}): {exc}"}
    log.info("Fusion route exported by the viewer: %d steps, rows %d-%d", len(plan["lineas"]), r["fila_inicial"], r["fila_final"])
    return {"ok": True, **r, "avisos": avisos + r["avisos"], "pasos": len(plan["lineas"]), "plan": plan}
