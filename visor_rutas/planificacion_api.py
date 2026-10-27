"""API REST de planificación de cuadrillas (/visor/planificacion/*): la usan la app de planificación (clave del visor, rol editor o administrador) y la app
de la cuadrilla (clave de técnico: CAMPO_API_KEYS, rol «tecnico» y miembro de una cuadrilla). La lógica y los permisos están en
visor_rutas/redes/planificacion.py; aquí solo se validan los cuerpos y los errores se vuelven códigos HTTP como en la app de campo
(403 sin permiso, 404 no existe, 422 datos no válidos, 503 sin base). Misma autenticación que /visor/campo/*.
"""
import json
import queue
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

import visor_api
from visor_rutas import campo_api, campo_eventos
from visor_rutas.redes import planificacion

router = APIRouter(prefix="/visor/planificacion", tags=["planificación de cuadrillas"])
persona = campo_api.persona_campo
_ejecutar = campo_api._ejecutar


class CuadrillaPedido(BaseModel):
    empresa: str = Field(max_length=80)
    nombre: str = Field(max_length=80)
    telefono: str = Field(default="", max_length=40)
    notas: str = Field(default="", max_length=500)


class CuadrillaCambios(BaseModel):
    cambios: dict[str, Any]


class MiembroPedido(BaseModel):
    usuario_id: int
    quitar: bool = False


class ActividadPedido(BaseModel):
    cliente_nombre: str = Field(max_length=200)
    lat: float
    lon: float
    ticket: str = Field(default="", max_length=64)
    codigo_cliente: str = Field(default="", max_length=64)
    contacto_nombre: str = Field(default="", max_length=200)
    contacto_telefono: str = Field(default="", max_length=64)
    direccion: str = Field(default="", max_length=300)
    origen: str = Field(default="visor", max_length=10)
    presupuesto_clave: str | None = Field(default=None, max_length=300)
    presupuesto_total: float | None = None
    resumen: dict[str, Any] | None = None
    notas: str = Field(default="", max_length=1000)
    prioridad: int = Field(default=0, ge=-10, le=10)


class AsignarPedido(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    cuadrilla_id: int


class ColaPedido(BaseModel):
    ids: list[int] = Field(max_length=200)


class EstadoPedido(BaseModel):
    a: str = Field(max_length=20)
    motivo: str = Field(default="", max_length=500)
    forzar: bool = False


class MensajePedido(BaseModel):
    texto: str = Field(max_length=1000)


class ControlPedido(BaseModel):
    clave: str = Field(max_length=40)
    estado: str = Field(default="hecho", max_length=12)
    nota: str = Field(default="", max_length=500)
    lat: float | None = None
    lon: float | None = None


@router.get("/catalogo")
def catalogo(p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.catalogo, "planificacion/catalogo")


@router.get("/tablero")
def tablero(p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.tablero, "planificacion/tablero")


@router.get("/cuadrillas")
def cuadrillas(p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.cuadrillas, "planificacion/cuadrillas")


@router.post("/cuadrillas")
def crear_cuadrilla(pedido: CuadrillaPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.crear_cuadrilla, "planificacion/cuadrillas/crear", **pedido.model_dump())


@router.post("/cuadrillas/{id}")
def editar_cuadrilla(id: int, pedido: CuadrillaCambios, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.editar_cuadrilla, "planificacion/cuadrillas/editar", id=id, cambios=pedido.cambios)


@router.post("/cuadrillas/{id}/miembros")
def miembro(id: int, pedido: MiembroPedido, p: str = Depends(persona)) -> dict[str, Any]:
    funcion = planificacion.quitar_miembro if pedido.quitar else planificacion.agregar_miembro
    return _ejecutar(p, funcion, "planificacion/cuadrillas/miembros", cuadrilla_id=id, usuario_id=pedido.usuario_id)


@router.post("/cuadrillas/{id}/cola")
def cola(id: int, pedido: ColaPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.reordenar_cola, "planificacion/cuadrillas/cola", cuadrilla_id=id, ids=pedido.ids)


@router.get("/eventos")
def eventos(p: str = Depends(persona)) -> Any:
    """Server-Sent Events with what changes in planning (an activity, a state, a control point, a message): the NOTIFY of the database, {tabla, id, cambio}.
    The page then asks for what changed. For planning and for the technicians of a crew. A comment line goes out every 15 s so a dead connection is noticed."""
    permiso = _ejecutar(p, planificacion.exigir_eventos, "planificacion/eventos")
    if isinstance(permiso, JSONResponse):
        return permiso
    cola: queue.Queue = queue.Queue(maxsize=500)
    quitar = campo_eventos.escucha("planificacion").suscribir(lambda aviso: cola.put_nowait(aviso) if not cola.full() else None)

    def flujo() -> Any:
        try:
            yield "retry: 3000\n: conectado\n\n"
            while True:
                try:
                    yield f"data: {json.dumps(cola.get(timeout=15))}\n\n"
                except queue.Empty:
                    yield ": latido\n\n"
        finally:
            quitar()
    return StreamingResponse(flujo(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/tecnicos")
def tecnicos(p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.tecnicos, "planificacion/tecnicos")


@router.get("/mia")
def mia(p: str = Depends(persona)) -> dict[str, Any]:
    """The crew app: the crew of the key, what it is doing now and its queue."""
    return _ejecutar(p, planificacion.mi_cuadrilla, "planificacion/mia")


@router.get("/actividades")
def actividades(estado: str | None = Query(default=None, max_length=20), cuadrilla_id: int | None = None, buscar: str | None = Query(default=None, max_length=80),
                p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.actividades, "planificacion/actividades", estado=estado, cuadrilla_id=cuadrilla_id, buscar=buscar)


@router.post("/actividades")
def crear_actividad(pedido: ActividadPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.crear_actividad, "planificacion/actividades/crear", **pedido.model_dump())


@router.post("/actividades/asignar")
def asignar(pedido: AsignarPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.asignar, "planificacion/actividades/asignar", ids=pedido.ids, cuadrilla_id=pedido.cuadrilla_id)


@router.get("/actividades/{id}")
def actividad(id: int, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.actividad, "planificacion/actividades/ver", id=id)


@router.post("/actividades/{id}/estado")
def estado(id: int, pedido: EstadoPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.cambiar_estado, "planificacion/actividades/estado", id=id, a=pedido.a, motivo=pedido.motivo, forzar=pedido.forzar)


@router.get("/actividades/{id}/mensajes")
def mensajes(id: int, desde_id: int = 0, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.mensajes, "planificacion/actividades/mensajes", actividad_id=id, desde_id=desde_id)


@router.post("/actividades/{id}/mensajes")
def enviar_mensaje(id: int, pedido: MensajePedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.enviar_mensaje, "planificacion/actividades/enviar", actividad_id=id, texto=pedido.texto)


@router.post("/actividades/{id}/control")
def control(id: int, pedido: ControlPedido, p: str = Depends(persona)) -> dict[str, Any]:
    return _ejecutar(p, planificacion.marcar_control, "planificacion/actividades/control", id=id, **pedido.model_dump())


# --------------------------------------------------------------------------- las páginas (/planificacion/ y /cuadrilla/)

pagina = APIRouter(tags=["planificación (páginas)"])
RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "planificacion_web"                      # the planning app
WEB_CUADRILLA = RAIZ / "cuadrilla_web"                # the crew app (PWA)
LIBS = {"lib/leaflet": RAIZ / "web" / "lib" / "leaflet"}          # Leaflet is the viewer's own copy (no CDN)
TIPOS_ARCHIVO = {".html", ".js", ".css", ".png", ".svg", ".json", ".ico", ".webmanifest"}
TIPOS_MIME = {".js": "text/javascript", ".webmanifest": "application/manifest+json"}


def _archivo_web(relativa: str, web: Path) -> Path | None:
    relativa = relativa.replace("\\", "/").lstrip("/")
    for prefijo, carpeta in LIBS.items():
        if relativa.startswith(prefijo + "/"):
            base, resto = carpeta, relativa[len(prefijo) + 1:]
            break
    else:
        base, resto = web, relativa
    ruta = (base / resto).resolve()
    if base.resolve() not in ruta.parents or ruta.suffix.lower() not in TIPOS_ARCHIVO or not ruta.is_file():
        return None
    return ruta


def _servir(relativa: str, web: Path = WEB) -> FileResponse:
    if not (visor_api.claves_visor() or visor_api.claves_campo()):      # off when there is no key of any kind
        raise HTTPException(status_code=404, detail="Not Found")
    ruta = _archivo_web(relativa, web)
    if ruta is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(ruta, media_type=TIPOS_MIME.get(ruta.suffix.lower()), headers={"Cache-Control": "no-cache"})


def _sin_barra(destino: str) -> RedirectResponse:
    if not (visor_api.claves_visor() or visor_api.claves_campo()):
        raise HTTPException(status_code=404, detail="Not Found")
    return RedirectResponse(destino, status_code=307)


@pagina.get("/planificacion", include_in_schema=False)
def pagina_sin_barra() -> RedirectResponse:
    return _sin_barra("/planificacion/")


@pagina.get("/planificacion/", include_in_schema=False)
def pagina_planificacion() -> FileResponse:
    return _servir("index.html")


@pagina.get("/planificacion/{relativa:path}", include_in_schema=False)
def archivo_planificacion(relativa: str) -> FileResponse:
    return _servir(relativa or "index.html")


@pagina.get("/cuadrilla", include_in_schema=False)
def cuadrilla_sin_barra() -> RedirectResponse:
    """The service worker controls /cuadrilla/ (with the slash): the app lives there."""
    return _sin_barra("/cuadrilla/")


@pagina.get("/cuadrilla/", include_in_schema=False)
def pagina_cuadrilla() -> FileResponse:
    return _servir("index.html", WEB_CUADRILLA)


@pagina.get("/cuadrilla/{relativa:path}", include_in_schema=False)
def archivo_cuadrilla(relativa: str) -> FileResponse:
    return _servir(relativa or "index.html", WEB_CUADRILLA)
