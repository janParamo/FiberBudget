"""API REST de la app de campo (/visor/campo/*): jornadas, puntos y fotos de los técnicos.

Misma autenticación que el resto de /visor/* (X-Visor-Key de VISOR_API_KEYS; 404 si está vacío). La persona de la clave debe tener en el módulo de
redes el rol «tecnico» (o editor / administrador). La lógica está en visor_rutas/redes/campo.py; aquí solo se valida el tamaño, se limita el ritmo
por persona y los errores se vuelven códigos HTTP: 403 sin permiso, 404 no existe, 409 otro cambió el registro, 422 datos no válidos, 503 sin base.
Las fotos suben como el cuerpo de la petición (Content-Type image/jpeg, image/png o image/webp) con el punto en la dirección: no necesita
python-multipart.
"""
import logging
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

import visor_api
from visor_rutas.redes import campo, db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/visor/campo", tags=["app de campo"])
pagina = APIRouter(tags=["app de campo (página)"])
WEB = Path(__file__).resolve().parent / "campo_web"
LIBS = {"lib/leaflet": Path(__file__).resolve().parent / "web" / "lib" / "leaflet"}      # Leaflet is the viewer's own copy (no CDN)
TIPOS_ARCHIVO = {".html", ".js", ".css", ".png", ".svg", ".json", ".webmanifest", ".ico"}
limitador = visor_api.Limitador()


def persona_campo(persona: str = Depends(visor_api.persona_visor)) -> str:
    """The person of the key, with the per-technician request limit of the field app."""
    limitador.registrar(persona, int(campo.configuracion()["peticiones_por_hora"]))
    return persona


def _error(codigo: int, mensaje: str, errores: dict[str, str] | None = None) -> JSONResponse:
    """The error body of the field app: {ok: false, error, errores?} (the app-wide handler would flatten a structured `detail` into text)."""
    return JSONResponse(status_code=codigo, content={"ok": False, "error": mensaje, **({"errores": errores} if errores else {})})


def _ejecutar(persona: str, funcion: Any, endpoint: str, **args: Any) -> Any:
    with visor_api._registro(persona, f"campo/{endpoint}") as estado:
        try:
            return {"ok": True, **visor_api.servicio_redes().ejecutar(funcion, args, persona_visor=persona)}
        except db.SinPermiso as exc:
            codigo, detalle, errores = 403, str(exc), None
        except db.NoEncontrado as exc:
            codigo, detalle, errores = 404, str(exc), None
        except db.ConflictoVersion as exc:
            codigo, detalle, errores = 409, str(exc), None
        except db.DatosInvalidos as exc:
            codigo, detalle, errores = 422, str(exc), exc.errores
        except db.RedesNoDisponible as exc:
            codigo, detalle, errores = 503, str(exc) or "La base de redes no está disponible", None
        except db.ErrorRedes as exc:
            codigo, detalle, errores = 400, str(exc), None
        except psycopg.Error as exc:
            log.exception("Campo: database error in %s", endpoint)
            codigo, detalle, errores = 503, f"Error de la base de redes ({type(exc).__name__})", None
        estado["resultado"] = f"error {codigo}"
        return _error(codigo, detalle, errores)


class JornadaPedido(BaseModel):
    accion: str = Field(pattern="^(abrir|cerrar)$")
    id: int | None = None
    nombre: str | None = Field(default=None, max_length=120)
    notas: str | None = Field(default=None, max_length=1000)


class PuntosPedido(BaseModel):
    puntos: list[dict[str, Any]] = Field(min_length=1, max_length=500)


class EdicionPedido(BaseModel):
    version: int
    cambios: dict[str, Any]


@router.post("/jornadas")
def jornada(pedido: JornadaPedido, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    if pedido.accion == "abrir":
        return _ejecutar(persona, campo.abrir_jornada, "jornadas/abrir", nombre=pedido.nombre, notas=pedido.notas)
    if pedido.id is None:
        return _error(422, "Falta el id de la jornada", {"id": "Campo obligatorio"})
    return _ejecutar(persona, campo.cerrar_jornada, "jornadas/cerrar", id=pedido.id)


@router.get("/jornadas")
def lista_jornadas(usuario_id: int | None = None, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    return _ejecutar(persona, campo.jornadas, "jornadas", usuario_id=usuario_id)


@router.post("/puntos")
def guardar_puntos(pedido: PuntosPedido, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    return _ejecutar(persona, campo.guardar_puntos, "puntos", puntos=pedido.puntos)


@router.get("/puntos")
def lista_puntos(desde: str | None = None, jornada: int | None = None, estado: str | None = None, usuario_id: int | None = None,
                 limite: int = 200, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    return _ejecutar(persona, campo.puntos, "puntos/lista", desde=desde, jornada=jornada, estado=estado, usuario_id=usuario_id, limite=limite)


@router.patch("/puntos/{id_}")
def editar_punto(id_: int, pedido: EdicionPedido, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    return _ejecutar(persona, campo.editar_punto, "puntos/editar", id=id_, version=pedido.version, cambios=pedido.cambios)


@router.delete("/puntos/{id_}")
def borrar_punto(id_: int, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    return _ejecutar(persona, campo.borrar_punto, "puntos/borrar", id=id_)


@router.post("/fotos")
async def subir_foto(request: Request, punto_id: int, uuid_cliente: str | None = None, persona: str = Depends(persona_campo)) -> dict[str, Any]:
    """The photo is the body of the request. Refused before reading it when it is bigger than the limit."""
    maximo = int(campo.configuracion()["foto_max_bytes"])
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > maximo + 1024:
        return _error(413, f"La foto pesa más de {maximo // 1024} KB", {"foto": "Demasiado grande"})
    cuerpo = bytearray()
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > maximo + 1024:
            return _error(413, f"La foto pesa más de {maximo // 1024} KB", {"foto": "Demasiado grande"})
    return _ejecutar(persona, campo.subir_foto, "fotos", punto_id=punto_id, datos=bytes(cuerpo), uuid_cliente=uuid_cliente)


@router.get("/foto/{id_}")
def ver_foto(id_: int, miniatura: bool = False, persona: str = Depends(persona_campo)) -> Response:
    r = _ejecutar(persona, campo.foto, "foto", id=id_, miniatura=miniatura)
    if isinstance(r, JSONResponse):
        return r
    return Response(content=r["datos"], media_type=r["tipo"], headers={"Cache-Control": "private, max-age=3600"})


@router.get("/config")
def configuracion(persona: str = Depends(persona_campo)) -> dict[str, Any]:
    """What the app needs to know: who the key belongs to and the limits (GPS threshold, photos)."""
    cfg = campo.configuracion()
    return {"ok": True, "persona": persona, **{k: cfg[k] for k in ("precision_max_m", "duplicado_m", "foto_max_bytes", "fotos_por_punto")}}


# --------------------------------------------------------------------------- la página de la app (sin clave: es solo HTML / JS / CSS)

def _archivo_web(relativa: str) -> Path | None:
    """The file of the app (or of Leaflet) for a path under /campo/, or None. Nothing outside the two folders is ever served."""
    relativa = relativa.replace("\\", "/").lstrip("/")
    for prefijo, carpeta in LIBS.items():
        if relativa.startswith(prefijo + "/"):
            base, resto = carpeta, relativa[len(prefijo) + 1:]
            break
    else:
        base, resto = WEB, relativa
    ruta = (base / resto).resolve()
    if base.resolve() not in ruta.parents or ruta.suffix.lower() not in TIPOS_ARCHIVO or not ruta.is_file():
        return None
    return ruta


def _servir(relativa: str) -> FileResponse:
    if not visor_api.claves_visor():                                   # the field app is part of the remote viewer: off when it is
        raise HTTPException(status_code=404, detail="Not Found")
    ruta = _archivo_web(relativa)
    if ruta is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(ruta, headers={"Cache-Control": "no-cache"})


@pagina.get("/campo", include_in_schema=False)
def pagina_campo() -> FileResponse:
    return _servir("index.html")


@pagina.get("/campo/{relativa:path}", include_in_schema=False)
def archivo_campo(relativa: str) -> FileResponse:
    return _servir(relativa or "index.html")
