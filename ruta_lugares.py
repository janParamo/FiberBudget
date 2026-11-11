"""The route of a budget in «Mis lugares» (called by main when a budget is generated; the work is in visor_rutas/redes/lugares_presupuesto.py)."""
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def dueno_de_la_api() -> dict[str, str] | None:
    """Whose «Mis lugares» get the route of a budget made by the API (n8n, a ticket): LUGARES_USUARIO_PRESUPUESTOS in the .env, a Windows user
    («jparamo») or «persona:Nombre» for the name of a remote viewer key; empty: the API does not save routes."""
    valor = os.getenv("LUGARES_USUARIO_PRESUPUESTOS", "").strip()
    if not valor:
        return None
    if valor.lower().startswith("persona:"):
        return {"persona_visor": valor.split(":", 1)[1].strip()}
    return {"usuario_windows": valor}


def _solicitud(req: Any) -> dict[str, Any]:
    """What the budget form had (the names of its fields), kept with the route: to make the budget again when the route is edited in Mis lugares."""
    def campo(nombre: str, defecto: Any = "") -> Any:
        valor = getattr(req, nombre, None)
        return defecto if valor is None else valor
    return {"ticket_id": campo("ticket_id"), "client_name": campo("client_name"), "client_code": campo("client_code"), "sales_exec": campo("sales_exec"),
            "contact_name": campo("contact_name"), "contact_phone": campo("contact_phone"), "raw_comment": campo("raw_comment"), "comment_edits": campo("comment_edits", None) or None,
            "technology": campo("technology"), "odf_rack_ports": str(campo("odf_rack_ports")), "service_type": campo("service_type"), "medium": campo("medium"),
            "bandwidth": campo("bandwidth"), "coordenada": f"{campo('latitude', 0.0)}, {campo('longitude', 0.0)}"}


def guardar(req: Any, seg: Any, route: Any, dueno: dict[str, str] | None, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Saves the route of the budget in the «Presupuestos» folder of the owner's Mis lugares (to see it on the map and edit it), in a folder of its own with the exact point of
    the client, the drop and the new poles (`extra["postes_nuevos"]`). Never blocks:
    returns {"ok": True, "nombre", "accion"} or {"ok": False, "error"} (None when there is no owner or no route)."""
    if not dueno or len(route.points) < 2:
        return None
    try:
        from visor_rutas.redes import lugares_presupuesto
        distancia = f"{route.distance_m:,.0f} m"
        descripcion = f"Ticket {req.ticket_id} · {distancia} desde {seg.nombre or seg.tipo}".replace("&", "&amp;").replace("<", "&lt;")
        extra = extra or {}
        r = lugares_presupuesto.guardar_de(
            dueno, nombre=lugares_presupuesto.nombre_ruta(req.client_code, req.client_name), puntos=route.points, descripcion=descripcion,
            propiedades={"solicitud": _solicitud(req), "ticket": req.ticket_id, "cliente": req.client_name, "codigo": req.client_code, "distancia_m": round(route.distance_m, 1), **(extra.get("propiedades") or {})},
            cliente={"lat": getattr(req, "latitude", None), "lon": getattr(req, "longitude", None), "nombre": req.client_name, "codigo": req.client_code},
            postes_nuevos=[tuple(p) for p in (extra.get("postes_nuevos") or [])])
        return {"ok": True, "nombre": r["nombre"], "accion": r["accion"]}
    except Exception as exc:                                  # noqa: BLE001 - the budget must come out even without the network database
        log.warning("Ticket %s: the route was not saved in Mis lugares (%s: %s)", req.ticket_id, type(exc).__name__, str(exc)[:160])
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
