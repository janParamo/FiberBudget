"""/visor/*: the desktop route viewer used from OTHER computers (remote mode), through ngrok.

The other PC has no databases, Google key or LibreOffice: its viewer (visor_rutas/remoto.py)
calls these endpoints and this PC computes everything with the very same code as the local
viewer. Every endpoint delegates to visor_rutas.ventana_web.Api (local mode), the class the
local viewer's page calls, so results are identical and no logic is duplicated.

Security (independent from n8n's SERVICE_API_KEY, which is never accepted here):
  - header X-Visor-Key; one key per person in .env:  VISOR_API_KEYS="jan:clave1,maria:clave2"
    (.env is re-read when it changes: adding or removing a person needs no restart);
  - VISOR_API_KEYS empty -> every /visor/* endpoint answers 404 (disabled);
  - VISOR_RATE_LIMIT_PER_HOUR (default 60) requests per person and hour on the endpoints that
    can call Google (ruta, estimacion, presupuesto) -> 429 when exceeded. The read-only network
    files (/visor/kmz/*, the "Lugares" panel) and the network design module (/visor/redes/*)
    need the key but do not count for the limit.
Everything they generate goes to output/visor (never budget_index.json). Each request is logged
with person, endpoint, coordinate and duration (never the key).
"""
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Path as PathParam, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

log = logging.getLogger("visor_api")

VERSION = "1.0"
LIMITE_POR_DEFECTO = 60
PREFIJO_ARCHIVO = "remoto:"
RE_ARCHIVO = re.compile(r"^(?P<id>[^\\/:*?\"<>|\x00-\x1f]{1,200})\.(?P<ext>xlsx|pdf)$")

router = APIRouter(prefix="/visor", tags=["visor de rutas (remoto)"])


# --------------------------------------------------------------------------- claves y límite

_ENV = Path(__file__).resolve().parent / ".env"
# Values the process started with (config.py loaded .env into os.environ at import time).
_AL_INICIO = {nombre: os.environ.get(nombre) for nombre in ("VISOR_API_KEYS", "VISOR_RATE_LIMIT_PER_HOUR")}
_cache_env: dict[str, Any] = {"mtime": None, "valores": {}}
_cache_lock = threading.Lock()


def _valor(nombre: str, defecto: str) -> str:
    """Current value of a visor setting. The .env file is re-read when it changes, so adding or
    removing a person needs no restart. A value the process itself changed after start (a
    test, or `set` in the console before starting) wins over the file."""
    actual = os.environ.get(nombre)
    if actual != _AL_INICIO.get(nombre):
        return actual if actual is not None else defecto
    try:
        mtime = _ENV.stat().st_mtime
    except OSError:
        return actual if actual is not None else defecto
    with _cache_lock:
        if _cache_env["mtime"] != mtime:
            from dotenv import dotenv_values
            _cache_env["valores"] = dict(dotenv_values(_ENV))
            _cache_env["mtime"] = mtime
        valores = _cache_env["valores"]
    return valores.get(nombre) or defecto


def claves_visor() -> dict[str, str]:
    """{key: person} from VISOR_API_KEYS="jan:clave1,maria:clave2" (entries without ':' are ignored)."""
    claves: dict[str, str] = {}
    for entrada in _valor("VISOR_API_KEYS", "").split(","):
        nombre, separador, clave = entrada.strip().partition(":")
        if separador and nombre.strip() and clave.strip():
            claves[clave.strip()] = nombre.strip()
    return claves


def limite_por_hora() -> int:
    try:
        return max(1, int(_valor("VISOR_RATE_LIMIT_PER_HOUR", str(LIMITE_POR_DEFECTO))))
    except ValueError:
        return LIMITE_POR_DEFECTO


class Limitador:
    """Sliding one-hour window per person (in memory: it restarts with the service)."""

    def __init__(self) -> None:
        self._consultas: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def registrar(self, persona: str, limite: int, ahora: float | None = None) -> None:
        ahora = time.time() if ahora is None else ahora
        with self._lock:
            consultas = self._consultas.setdefault(persona, deque())
            while consultas and ahora - consultas[0] >= 3600:
                consultas.popleft()
            if len(consultas) >= limite:
                espera = max(1, round((3600 - (ahora - consultas[0])) / 60))
                raise HTTPException(status_code=429, detail=(
                    f"Límite de {limite} consultas por hora alcanzado para {persona}; "
                    f"intente de nuevo en {espera} minuto{'s' if espera != 1 else ''}"))
            consultas.append(ahora)

    def reiniciar(self) -> None:
        with self._lock:
            self._consultas.clear()


limitador = Limitador()


def persona_visor(x_visor_key: str | None = Header(default=None)) -> str:
    """The person owning the X-Visor-Key (401 otherwise); 404 when the remote viewer is disabled."""
    claves = claves_visor()
    if not claves:
        raise HTTPException(status_code=404, detail="Not Found")
    if x_visor_key:
        for clave, nombre in claves.items():
            if secrets.compare_digest(x_visor_key.encode("utf-8"), clave.encode("utf-8")):
                return nombre
    log.warning("Visor API: rejected request (bad or missing X-Visor-Key)")
    raise HTTPException(status_code=401, detail="X-Visor-Key no válida o ausente")


def persona_limitada(persona: str = Depends(persona_visor)) -> str:
    """persona_visor plus the hourly limit (endpoints that can call Google Directions)."""
    limitador.registrar(persona, limite_por_hora())
    return persona


@contextmanager
def _registro(persona: str, endpoint: str, coordenada: str | None = None) -> Iterator[dict[str, Any]]:
    estado: dict[str, Any] = {"resultado": "ok"}
    inicio = time.monotonic()
    try:
        yield estado
    except Exception:
        estado["resultado"] = "error"
        raise
    finally:
        log.info("Visor API: persona=%s endpoint=%s coordenada=%s resultado=%s duracion=%.1fs",
                 persona, endpoint, coordenada or "-", estado["resultado"], time.monotonic() - inicio)


# --------------------------------------------------------------------------- Api local compartida

_api_local: Any = None
_api_lock = threading.Lock()


def api_local() -> Any:
    """The local viewer's Api (local mode), shared by every request: its Google route cache lets an
    estimate after /visor/ruta of the same coordinate reuse that route."""
    global _api_local
    with _api_lock:
        if _api_local is None:
            from visor_rutas.ventana_web import Api
            _api_local = Api()
        return _api_local


_servicio_redes: Any = None


def servicio_redes() -> Any:
    """Network design module (visor_rutas/redes), shared by every request (one DB connection)."""
    global _servicio_redes
    with _api_lock:
        if _servicio_redes is None:
            from visor_rutas.redes.api import ServicioRedes
            _servicio_redes = ServicioRedes()
        return _servicio_redes


def reiniciar() -> None:
    """Fresh Api and limits (tests; also harmless at runtime)."""
    global _api_local, _servicio_redes
    with _api_lock:
        _api_local = None
        if _servicio_redes is not None:
            _servicio_redes.cerrar()
        _servicio_redes = None
    limitador.reiniciar()


def _para_remoto(respuesta: dict[str, Any]) -> dict[str, Any]:
    """Budget results name server files: give the client an id ("remoto:<name>") instead."""
    resultado = respuesta.get("resultado")
    if isinstance(resultado, dict) and resultado.get("archivo"):
        resultado["id"] = Path(resultado["archivo"]).stem
        resultado["archivo"] = PREFIJO_ARCHIVO + resultado["id"]
        resultado["carpeta"] = None
    return respuesta


def _resultado_ok(respuesta: dict[str, Any], estado: dict[str, Any]) -> dict[str, Any]:
    if not respuesta.get("ok"):
        estado["resultado"] = f"sin resultado: {str(respuesta.get('error', ''))[:120]}"
    return respuesta


# --------------------------------------------------------------------------- endpoints

class RutaPedido(BaseModel):
    texto: str | None = Field(default=None, max_length=200)
    lat: float | None = None
    lon: float | None = None


class EstimacionPedido(BaseModel):
    lat: float
    lon: float
    metraje_final_m: float | None = Field(default=None, ge=0)
    # new poles marked as existing on the map (route metres)
    postes_existentes_m: list[float] | None = Field(default=None, max_length=1000)


class PresupuestoPedido(BaseModel):
    campos: dict[str, Any]


@router.get("/info")
def info(persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """API version, Visio network date, base map and the budget form options."""
    api = api_local()
    configuracion = {k: v for k, v in api.configuracion().items()
                     if k not in ("modo", "local_disponible", "sin_configurar")}
    presupuesto = {k: v for k, v in api.presupuesto_config().items() if k not in ("ok", "carpeta")}
    return {"version": VERSION, "persona": persona, "fecha_red": api._fecha_red(),
            "configuracion": configuracion, "presupuesto": presupuesto}


@router.post("/ruta")
def ruta(pedido: RutaPedido, persona: str = Depends(persona_limitada)) -> dict[str, Any]:
    """Same as the local viewer's "Generar ruta": {"ok", "datos" (= calculo.calcular_ruta), "coordenada"}."""
    texto = pedido.texto if pedido.texto else (
        f"{pedido.lat}, {pedido.lon}" if pedido.lat is not None and pedido.lon is not None else "")
    with _registro(persona, "ruta", texto) as estado:
        return _resultado_ok(api_local().calcular(texto), estado)


@router.post("/estimacion")
def estimacion(pedido: EstimacionPedido, persona: str = Depends(persona_limitada)) -> dict[str, Any]:
    """Approximate budget (business_rules visor_estimacion). Without metraje_final_m the route is
    computed first (cached: no second Google call for the same coordinate)."""
    coordenada = f"{pedido.lat:.6f}, {pedido.lon:.6f}"
    with _registro(persona, "estimacion", coordenada) as estado:
        api = api_local()
        metraje = pedido.metraje_final_m
        if metraje is None:
            calculo = api.calcular(coordenada)
            if not calculo.get("ok"):
                return _resultado_ok(calculo, estado)
            if calculo["datos"]["ruta"]["aproximada"]:
                return _resultado_ok({"ok": False, "error": "Sin ruta de Google no hay presupuesto aproximado"}, estado)
            metraje = calculo["datos"]["ruta"]["metraje_final_m"]
        return _resultado_ok(_para_remoto(api.estimar_presupuesto(pedido.lat, pedido.lon, metraje,
                                                                  pedido.postes_existentes_m)), estado)


@router.post("/presupuesto")
def presupuesto(pedido: PresupuestoPedido, persona: str = Depends(persona_limitada)) -> dict[str, Any]:
    """Full budget from the viewer form (TicketRequest validation); files in output/visor."""
    with _registro(persona, "presupuesto", str(pedido.campos.get("coordenada") or "")) as estado:
        return _resultado_ok(_para_remoto(api_local().generar_presupuesto(pedido.campos)), estado)


@router.get("/presupuestos")
def presupuestos(persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """History of the viewer budgets (output/visor) with ids instead of server paths."""
    respuesta = api_local().historial_presupuestos()
    for p in respuesta.get("presupuestos", []):
        p["id"] = Path(p["archivo"]).stem
        p["archivo"] = PREFIJO_ARCHIVO + p["id"]
    return respuesta


@router.get("/presupuestos/{id_}")
def presupuesto_guardado(id_: str = PathParam(max_length=200), persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """One saved budget (summary of the Excel) for the result area of the remote viewer."""
    from visor_rutas import presupuesto_visor
    if RE_ARCHIVO.match(f"{id_}.xlsx") is None or id_ in (".", ".."):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with _registro(persona, "presupuestos.abrir"):
        return _para_remoto(api_local().abrir_presupuesto_guardado(str(presupuesto_visor.carpeta_visor() / f"{id_}.xlsx")))


@router.get("/archivo/{nombre}")
def archivo(nombre: str = PathParam(max_length=210), persona: str = Depends(persona_visor)) -> FileResponse:
    """<id>.xlsx or <id>.pdf of a visor budget; only files inside output/visor."""
    from visor_rutas import presupuesto_visor
    encontrado = RE_ARCHIVO.match(nombre)
    if encontrado is None or encontrado["id"] in (".", ".."):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with _registro(persona, f"archivo.{encontrado['ext']}"):
        try:
            xlsx = presupuesto_visor.archivo_del_visor(
                presupuesto_visor.carpeta_visor() / f"{encontrado['id']}.xlsx", (".xlsx",))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        if encontrado["ext"] == "xlsx":
            return FileResponse(xlsx, filename=xlsx.name,
                                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta = api_local().pdf_presupuesto(str(xlsx))
        if not respuesta.get("ok"):
            raise HTTPException(status_code=503, detail=respuesta.get("error") or "PDF no disponible")
        pdf = xlsx.with_suffix(".pdf")
        return FileResponse(pdf, filename=pdf.name, media_type="application/pdf")


@router.get("/diagrama/{md5}/{pagina}")
def diagrama(md5: str = PathParam(pattern=r"^[0-9a-fA-F]{32}$"), pagina: int = PathParam(ge=0, le=50),
             persona: str = Depends(persona_visor)) -> Response:
    """Visio diagram image: SVG (PNG if the SVG export fails), as in the local viewer."""
    from visor_rutas import fusion
    with _registro(persona, "diagrama"):
        try:
            if pagina == 0:
                imagen, formato = fusion.diagrama_mejor(md5)
            else:
                imagen, formato = fusion.diagrama_png(md5, pagina), "png"
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Diagrama no disponible (no está convertido en el servidor)")
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"Diagrama no disponible ({exc})")
        if imagen is None:
            raise HTTPException(status_code=503, detail="Diagrama no disponible (falta LibreOffice en el servidor)")
        tipo = "image/svg+xml" if formato == "svg" else "image/png"
        return Response(content=Path(imagen).read_bytes(), media_type=tipo)


@router.get("/red/{capa}")
def red(capa: str, oeste: float = Query(), sur: float = Query(), este: float = Query(), norte: float = Query(),
        zoom: int = Query(ge=0, le=25), persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """Network layer inside the visible map rectangle (read-only; does not count for the limit)."""
    return api_local().red(capa, oeste, sur, este, norte, zoom)


# --------------------------------------------------------------------------- red KMZ ("Lugares")
# Read-only files of the KMZ cache (visor_rutas/kmz_capas.py). They need the key but do not count
# for the hourly limit: turning layers on loads several of them. JSON goes gzip-compressed.

_gzip_cache: dict[tuple[str, float], bytes] = {}
_gzip_lock = threading.Lock()


def _archivo_gzip(archivo: Path, aceptar: str | None, media_type: str) -> Response:
    datos = archivo.read_bytes()
    if "gzip" not in (aceptar or "").lower():
        return Response(content=datos, media_type=media_type)
    clave = (str(archivo), archivo.stat().st_mtime)
    with _gzip_lock:
        comprimido = _gzip_cache.get(clave)
        if comprimido is None:
            import gzip
            comprimido = gzip.compress(datos, compresslevel=6)
            if len(_gzip_cache) > 400:
                _gzip_cache.clear()
            _gzip_cache[clave] = comprimido
    return Response(content=comprimido, media_type=media_type,
                    headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})


@router.get("/kmz/arbol")
def kmz_arbol(accept_encoding: str | None = Header(default=None), persona: str = Depends(persona_visor)) -> Response:
    """arbol.json of the network KMZ (imported first if the KMZ changed)."""
    from visor_rutas import kmz_capas
    with _registro(persona, "kmz.arbol"):
        try:
            kmz_capas.asegurar()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Red KMZ no disponible en el servidor: {exc}")
        return _archivo_gzip(kmz_capas.CARPETA_DATOS / "arbol.json", accept_encoding, "application/json")


@router.get("/kmz/capa/{cid}")
def kmz_capa(cid: str = PathParam(pattern=r"^[0-9a-f]{12}$"), accept_encoding: str | None = Header(default=None),
             persona: str = Depends(persona_visor)) -> Response:
    """GeoJSON of one folder of the KMZ."""
    from visor_rutas import kmz_capas
    try:
        archivo = kmz_capas.archivo_capa(cid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Capa no encontrada")
    return _archivo_gzip(archivo, accept_encoding, "application/geo+json")


@router.get("/kmz/indice")
def kmz_indice(accept_encoding: str | None = Header(default=None), persona: str = Depends(persona_visor)) -> Response:
    """Names and description text of every element, per folder (search box)."""
    from visor_rutas import kmz_capas
    try:
        archivo = kmz_capas.archivo_indice()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Índice no encontrado")
    return _archivo_gzip(archivo, accept_encoding, "application/json")


@router.get("/kmz/archivo/{relativa:path}")
def kmz_archivo(relativa: str = PathParam(max_length=200), persona: str = Depends(persona_visor)) -> FileResponse:
    """iconos/<name> or fotos/<name> of the KMZ cache (nothing else)."""
    from visor_rutas import kmz_capas
    try:
        archivo = kmz_capas.archivo_seguro(relativa)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(archivo)


# --------------------------------------------------------------------------- módulo de redes

class RedesPedido(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/redes/{metodo}")
def redes(metodo: str = PathParam(pattern=r"^[a-z_]{1,40}$"), pedido: RedesPedido | None = None,
          persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """Network design module: the same ServicioRedes.llamar as the local viewer; the user is the
    person of the X-Visor-Key (never a name sent by the client). Does not count for the limit,
    except the methods that call Google (CON_LIMITE: the address search)."""
    from visor_rutas.redes.api import CON_LIMITE
    if metodo in CON_LIMITE:                     # address search calls Google
        limitador.registrar(persona, limite_por_hora())
    with _registro(persona, f"redes.{metodo}") as estado:
        respuesta = servicio_redes().llamar(metodo, (pedido.args if pedido else {}), persona_visor=persona)
        return _resultado_ok(respuesta, estado)


@router.get("/mufas")
def mufas(texto: str = Query(default="", max_length=100), persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """Mufa search box (read-only)."""
    return api_local().buscar_mufa(texto)


@router.get("/mufa/{nodo_id}")
def mufa(nodo_id: int, persona: str = Depends(persona_visor)) -> dict[str, Any]:
    """One searched mufa: diagrams, hilos, splitters... (read-only)."""
    return api_local().mufa(nodo_id)
