"""FastAPI app: routes and error mapping."""
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import ngrok
import psycopg
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

import db
import mapa_ruta
import reglas_mufas
import origen
import pdf_export
import recalc
import red_fibra_pg
import routing
from config import (NI_LAT_MAX, NI_LAT_MIN, NI_LON_MAX, NI_LON_MIN,
                    get_settings, load_rules, setup_logging)
from excel_generator import generar_excel
from presupuesto import (calcular_equipos, calcular_materiales, calcular_metraje_final,
                         calcular_presupuesto, count_turns, match_marked_poles,
                         new_pole_positions_by_gaps, new_pole_positions_in_spans, requiere_visita_tecnica,
                         seleccionar_tecnologia, tramos_aereos, tramos_ducto)

settings = get_settings()          # fails fast if the .env is incomplete
setup_logging(settings.log_file, settings.log_level)
log = logging.getLogger(__name__)
_budget_lock = threading.Lock()
PENDING_TEXT = "Pendiente de validar"


def _budget_index_path():
    return settings.output_dir / "budget_index.json"


def _load_budget_index() -> dict[str, Any]:
    try:
        with _budget_index_path().open("r", encoding="utf-8") as index_file:
            index = json.load(index_file)
        return index if isinstance(index, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_budget_index(index: dict[str, Any]) -> None:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=settings.output_dir,
            prefix=".budget-index-",
            suffix=".tmp",
            delete=False,
        ) as index_file:
            temp_path = index_file.name
            json.dump(index, index_file, ensure_ascii=False)
            index_file.flush()
            os.fsync(index_file.fileno())
        os.replace(temp_path, _budget_index_path())
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _clean_old_output_files() -> None:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - settings.output_retention_days * 24 * 60 * 60
    maps_dir = settings.output_dir / "mapas"
    expired_maps = maps_dir.iterdir() if maps_dir.is_dir() else iter(())
    for output_file in [*settings.output_dir.iterdir(), *expired_maps]:
        if output_file == _budget_index_path():
            continue
        try:
            if output_file.is_file() and output_file.stat().st_mtime < cutoff:
                output_file.unlink()
        except OSError as exc:
            log.warning("Could not remove expired output file (%s)", type(exc).__name__)
    index = _load_budget_index()
    current_index = {
        ticket_id: record
        for ticket_id, record in index.items()
        if isinstance(record, dict) and Path(record.get("excel_path", "")).is_file()
    }
    if current_index != index:
        _save_budget_index(current_index)


async def connect_ngrok() -> None:
    """Expose the local API through ngrok. Skipped when NGROK_DOMAIN is empty;
    the auth token is read from NGROK_AUTHTOKEN. Inside a running event loop
    ngrok returns a Task, so it must be awaited."""
    if not settings.ngrok_domain:
        return
    forwarder = await ngrok.forward(  # type: ignore[misc]  # stubs omit the Task
        f"{settings.api_host}:{settings.api_port}",
        authtoken_from_env=True,
        domain=settings.ngrok_domain,
    )
    log.info("Available at: %s", forwarder.url())


async def disconnect_ngrok() -> None:
    if settings.ngrok_domain:
        await ngrok.disconnect()  # type: ignore[misc]


@asynccontextmanager
async def lifespan(app: FastAPI):
    _clean_old_output_files()
    await connect_ngrok()
    try:
        yield
    finally:
        await disconnect_ngrok()


app = FastAPI(title="Fiber budget service", lifespan=lifespan)

# Desktop route viewer on other computers (/visor/*, own X-Visor-Key; 404 when VISOR_API_KEYS is
# empty). It does not touch the endpoints below.
import visor_api  # noqa: E402

app.include_router(visor_api.router)

# Field app (technicians register poles / mufas from the phone): /visor/campo/*, same X-Visor-Key. Independent of /presupuesto.
import visor_rutas.campo_api as campo_api  # noqa: E402

app.include_router(campo_api.router)
app.include_router(campo_api.pagina)


def _route_linestring_wkt(points: list[tuple[float, float]]) -> str:
    """Convert route points from (latitude, longitude) to EPSG:4326 WKT."""
    if len(points) < 2:
        raise ValueError("At least two route points are required")
    coordinates = ", ".join(f"{lon} {lat}" for lat, lon in points)
    return f"LINESTRING({coordinates})"


class TicketRequest(BaseModel):
    """Incoming ticket. Coordinates arrive as (latitude, longitude)."""
    ticket_id: str = Field(min_length=1, max_length=64)
    client_name: str = Field(min_length=1, max_length=200)
    client_code: str = Field(min_length=1, max_length=64)
    sales_exec: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_phone: str = Field(min_length=1, max_length=64)
    raw_comment: str = Field(max_length=30000)   # written verbatim; Excel caps a cell at 32767 chars
    # Optional: omitted, null or "" all mean "not requested".
    technology: Literal["gpon", "metro"] | None = Field(
        default=None, description="Forces GPON or Metro; otherwise taken from the comment or bandwidth")
    odf_rack_ports: Literal[12, 24] | None = Field(
        default=None, description="Rack ODF with 12 or 24 couplers instead of the ODF 2 Hilos")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    service_type: str = Field(min_length=1)
    medium: str = Field(min_length=1)
    bandwidth: str = Field(min_length=1)

    @field_validator("ticket_id", "client_name", "client_code", "sales_exec", "contact_name",
                     "contact_phone", "service_type", "medium", "bandwidth", mode="before")
    @classmethod
    def _to_str(cls, v: Any) -> Any:
        """n8n often sends ids/bandwidth as numbers; accept them as text."""
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    @field_validator("technology", "odf_rack_ports", mode="before")
    @classmethod
    def _optional(cls, v: Any) -> Any:
        """n8n sends empty strings for unset fields; normalize case and numeric text."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            v = v.strip().casefold()
            return int(v) if v.isdigit() else v
        return v

    @model_validator(mode="after")
    def _inside_nicaragua(self) -> "TicketRequest":
        if not (NI_LAT_MIN <= self.latitude <= NI_LAT_MAX and NI_LON_MIN <= self.longitude <= NI_LON_MAX):
            raise ValueError(
                f"Coordinates ({self.latitude}, {self.longitude}) are outside Nicaragua's bounding box "
                f"(lat {NI_LAT_MIN}..{NI_LAT_MAX}, lon {NI_LON_MIN}..{NI_LON_MAX}). "
                "Order must be latitude, longitude.")
        return self


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject requests without the correct X-API-Key (constant-time compare)."""
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.service_api_key):
        log.warning("Rejected request: bad or missing API key")
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return validation failures in the service's standard error shape."""
    log.warning("Invalid request payload")
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": "Invalid request payload"})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    error = {401: "unauthorized", 404: "not_found", 422: "validation_error", 502: "upstream_error"}.get(
        exc.status_code, "request_error")
    return JSONResponse(status_code=exc.status_code, content={"error": error, "detail": str(exc.detail)})


@app.exception_handler(Exception)
async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the traceback, return a generic 500."""
    log.error("Unhandled error (%s)", type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness check for n8n, including PostgreSQL connectivity."""
    try:
        db.check_connection()
    except db.DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok"}


@app.post("/presupuesto", dependencies=[Depends(verify_api_key)])
def crear_presupuesto(req: TicketRequest) -> dict[str, Any]:
    with _budget_lock:
        index = _load_budget_index()
        existing = index.get(req.ticket_id)
        if isinstance(existing, dict) and Path(existing.get("excel_path", "")).is_file():
            return existing
        if req.ticket_id in index:
            del index[req.ticket_id]
            _save_budget_index(index)
        response = _generar_presupuesto(req)
        index[req.ticket_id] = response
        _save_budget_index(index)
        return response


def _traffic_origin(seg: db.Segment, chain: list[db.ChainMufa], rules: dict[str, Any],
                    visio_con: Any = None) -> tuple[origen.TrafficOrigin, list[str]]:
    """Origin node for the connection point and its upstream chain, plus warnings.

    Reads the PostgreSQL copy of the diagrams when connected, else the SQLite file.
    """
    try:
        coords = db.find_point_coords([mufa.id for mufa in chain[1:]])
        points = [origen.ChainPoint(seg.nombre, seg.lat, seg.lon, seg.tipo)] + [
            origen.ChainPoint(mufa.nombre, *coords[mufa.id]) for mufa in chain[1:] if mufa.id in coords]
        origin = None
        if visio_con is not None:
            try:
                origin = origen.find_traffic_origin(visio_con, points, rules)
            except psycopg.Error as exc:
                log.error("Traffic-origin lookup on PostgreSQL failed (%s); using the SQLite file",
                          type(exc).__name__)
        if origin is None:
            origin = origen.find_traffic_origin(settings.red_fibra_db, points, rules)
    except (db.DatabaseError, sqlite3.Error) as exc:
        log.error("Traffic-origin lookup failed (%s: %s)", type(exc).__name__, exc)
        return origen.TrafficOrigin(reason="error al consultar la base de diagramas"), [
            "Traffic-origin lookup failed: Origen de Tráfico (Nodo) left pending"]
    warnings = []
    if origin.node is None:
        warnings.append(f"Traffic-origin node not found ({origin.reason})")
    if origin.match_method in ("c", "d"):
        match = origin.name_match or {}
        where = f" in diagram {match['archivo']}" if match.get("archivo") else ""
        warnings.append(f"Connection mufa matched by name{where} ({match.get('nombre_diagrama')}): "
                        "Origen de Tráfico (Nodo) must be validated")
    if origin.diagnostico:
        warnings.append(f"Connection mufa not found by coordinate in the Visio diagrams "
                        f"[{', '.join(origin.diagnostico['casos'])}]: {origin.diagnostico['detalle']}")
    if origin.saturated_mufas:
        warnings.append("Mufas marked SATURADA on the path to the origin node: "
                        + ", ".join(origin.saturated_mufas))
    return origin, warnings


def _visio_segment(nodo: dict[str, Any]) -> db.Segment:
    """A Visio network node used as the connection point (no KMZ point close enough)."""
    return db.Segment(id=f"visio:{nodo['id']}", tipo=f"{nodo['tipo'].lower()} (visio)",
                      lat=float(nodo["lat"]), lon=float(nodo["lon"]), distance_m=float(nodo["distancia_m"]),
                      is_mufa=True, nombre=nodo["nombre"])


def _resolver_conexion(lat: float, lon: float, rules: dict[str, Any], visio_con: Any,
                       radio_m: float | None = None, tolerate_kmz_errors: bool = False,
                       ) -> tuple[db.Segment | None, red_fibra_pg.BusquedaVisio, bool]:
    """(connection point, Visio search, whether the point came from Visio).

    The KMZ (red_puntos) decides: mufa, then reserva, within mufa_search_radius_m. When it
    has nothing that close, the nearest Visio node is used if it is closer than the KMZ's
    farther fallback point.
    """
    kmz_radius = rules["connection"]["mufa_search_radius_m"]
    mufas = reglas_mufas.configuracion(rules)
    try:
        # never a mufa de corte / aérea / punta plana: by the folder of the KMZ (excluded_tipo_keywords) and by its name (mufas_no_usables)
        seg = db.find_nearest_connection_point(lat, lon, rules["excluded_tipo_keywords"], kmz_radius,
                                               excluded_names=reglas_mufas.patrones_sql(mufas))
    except db.NoSegmentFound:
        seg = None
    except db.DatabaseError:
        if not tolerate_kmz_errors:
            raise HTTPException(status_code=500, detail="Database query failed")
        seg = None
    busqueda = red_fibra_pg.buscar_origen(lat, lon, radio_m, visio_con)
    nodo = busqueda.nodo
    if nodo is not None and reglas_mufas.motivo(nodo.get("nombre"), mufas):      # a Visio node of that kind cannot be the connection point either
        log.info("Visio node %s ignored as connection point: %s", nodo.get("nombre"), reglas_mufas.motivo(nodo.get("nombre"), mufas))
        nodo = None
    if (seg is None or seg.distance_m > kmz_radius) and nodo is not None and (
            seg is None or nodo["distancia_m"] < seg.distance_m):
        log.info("Connection point from Visio: %s (%.1f m); KMZ had %s", nodo["nombre"], nodo["distancia_m"],
                 f"{seg.nombre or seg.id} at {seg.distance_m:.1f} m" if seg else "nothing")
        return _visio_segment(nodo), busqueda, True
    return seg, busqueda, False


def _no_disponible(seg: db.Segment, rules: dict[str, Any], visio_con: Any) -> str | None:
    """Why this KMZ point cannot give hilos, or None: a mark of connection.route_selection's
    unavailable_keywords in its KMZ name/description ("MF ELIMINADA", "MF SATURADA") or in its
    Visio mufa (notes, SATURADA next to its label)."""
    keywords = rules["connection"].get("route_selection", {}).get("unavailable_keywords", [])
    texto = origen._normalized(f"{seg.nombre or ''} {seg.descripcion or ''}")
    word = next((w for w in (origen._normalized(k) for k in keywords) if w and w in texto), None)
    if word:
        return f"{word} en el KMZ"
    point = origen.ChainPoint(seg.nombre, seg.lat, seg.lon, seg.tipo)
    if visio_con is not None:
        try:
            return origen.visio_unavailable(visio_con, point, rules, keywords)
        except psycopg.Error as exc:
            log.warning("Visio availability check on PostgreSQL failed (%s); using the SQLite file",
                        type(exc).__name__)
    try:
        return origen.visio_unavailable(settings.red_fibra_db, point, rules, keywords)
    except sqlite3.Error as exc:
        log.warning("Visio availability check failed (%s)", type(exc).__name__)
        return None


def _elegir_por_ruta(seg: db.Segment, desde_visio: bool, lat: float, lon: float, rules: dict[str, Any],
                     visio_con: Any, route: routing.Route, get_route: Any = None,
                     ) -> tuple[db.Segment, routing.Route, dict[str, Any] | None]:
    """(connection point, its route, what was compared) — connection.route_selection.

    The nearest KMZ point by straight line can be far by street (one-way streets, a river) or
    have no hilos ("MF ELIMINADA", "SATURADA"). Then the nearest KMZ mufas are compared by
    Google route length and the shortest one without such marks is used. A Visio node used as
    the connection point (desde_visio) is kept. get_route: routing.get_route unless the caller
    passes another one with the same signature (the desktop viewer's per-session route cache).
    """
    get_route = get_route or routing.get_route
    config = rules["connection"].get("route_selection") or {}
    if desde_visio or not config.get("enabled", True):
        return seg, route, None
    motivo = _no_disponible(seg, rules, visio_con)
    rodeo = (route.distance_m > float(config.get("detour_factor", 2.0)) * seg.distance_m
             and route.distance_m - seg.distance_m > float(config.get("min_detour_m", 300)))
    if motivo is None and not rodeo:
        return seg, route, None
    resumen = lambda s, ruta_m, m: {"id": s.id, "nombre": s.nombre, "tipo": s.tipo,
                                    "lineal_m": round(s.distance_m, 1),
                                    "ruta_m": None if ruta_m is None else round(ruta_m, 1),
                                    "disponible": m is None, "motivo": m}
    evaluados = [resumen(seg, route.distance_m, motivo)]
    seleccion = {"cambiada": False, "criterio": "sin_hilos" if motivo else "rodeo", "inicial": evaluados[0],
                 "evaluados": evaluados}
    try:
        candidatos = db.find_connection_candidates(
            lat, lon, rules["excluded_tipo_keywords"], float(config.get("candidate_radius_m", 2000)),
            int(config.get("max_candidates", 5)) + 1, include_reserves=seg.is_reserve,
            excluded_names=reglas_mufas.patrones_sql(reglas_mufas.configuracion(rules)))
    except db.DatabaseError:
        seleccion["error"] = "no se pudieron consultar otras mufas del KMZ"
        return seg, route, seleccion
    mejor = (seg, route) if motivo is None else None
    for candidato in [c for c in candidatos if c.id != seg.id][:int(config.get("max_candidates", 5))]:
        m = _no_disponible(candidato, rules, visio_con)
        ruta = None
        if m is None:
            try:
                ruta = get_route(origin=(candidato.lat, candidato.lon), destination=(lat, lon))
            except (routing.RoutingError, routing.RouteNotFound, requests.RequestException) as exc:
                m = f"sin ruta de Google ({type(exc).__name__})"
        evaluados.append(resumen(candidato, ruta.distance_m if ruta else None, m))
        if ruta is not None and (mejor is None or ruta.distance_m < mejor[1].distance_m):
            mejor = (candidato, ruta)
    if mejor is None:   # nothing usable nearby: keep the nearest point, flagged
        return seg, route, seleccion
    elegido, ruta = mejor
    seleccion.update(cambiada=elegido.id != seg.id,
                     elegida=next(e for e in evaluados if e["id"] == elegido.id))
    log.info("Connection by route: %s (%.0f m by route) instead of %s (%.0f m%s)", elegido.nombre,
             ruta.distance_m, seg.nombre, route.distance_m, f", {motivo}" if motivo else "")
    return elegido, ruta, seleccion


def _aviso_seleccion(seleccion: dict[str, Any] | None) -> str | None:
    """One line for warnings / the viewer about the connection point chosen by route."""
    if not seleccion:
        return None
    inicial = seleccion["inicial"]
    por = (f"sin hilos: {inicial['motivo']}" if inicial["motivo"]
           else f"{inicial['ruta_m']:.0f} m por calle contra {inicial['lineal_m']:.0f} m en línea recta")
    if seleccion.get("cambiada"):
        elegida = seleccion["elegida"]
        return (f"Punto de conexión elegido por ruta: {elegida['nombre']} ({elegida['ruta_m']:.0f} m por calle) "
                f"en lugar de {inicial['nombre']} ({por}); validar hilos disponibles")
    if inicial["motivo"]:
        return (f"Punto de conexión {inicial['nombre']} marcado {inicial['motivo']} y no hay otra mufa disponible "
                f"cerca: validar con Planta Externa")
    return None


def _origen_block(seg: db.Segment | None, busqueda: red_fibra_pg.BusquedaVisio, desde_visio: bool,
                  origin: origen.TrafficOrigin, rules: dict[str, Any],
                  distancia_ruta_m: float | None) -> dict[str, Any]:
    """The response's "origen" block, with the KMZ point checked against the diagrams."""
    verificacion = None
    if seg is not None and not desde_visio and origin.connection_match is not None:
        match = origin.connection_match
        verificacion = {"coincide": bool(match.get("exact")), "mufa_visio": match.get("name"),
                        "distancia_m": match.get("distance_m")}
    elif seg is not None and not desde_visio and busqueda.fuente != red_fibra_pg.SIN_CONEXION:
        verificacion = {"coincide": False, "mufa_visio": None, "distancia_m": None}
    punto = None if seg is None else {"nombre": seg.nombre, "tipo": seg.tipo, "lat": seg.lat,
                                      "lon": seg.lon, "distancia_m": seg.distance_m}
    return red_fibra_pg.bloque_origen(
        busqueda=busqueda, punto=punto, desde_visio=desde_visio, verificacion=verificacion,
        distancia_ruta_m=distancia_ruta_m, radio_kmz_m=rules["connection"]["mufa_search_radius_m"])


@app.get("/origen", dependencies=[Depends(verify_api_key)])
def consultar_origen(
    lat: float = Query(ge=NI_LAT_MIN, le=NI_LAT_MAX),
    lon: float = Query(ge=NI_LON_MIN, le=NI_LON_MAX),
    radio: float | None = Query(default=None, gt=0, le=50000),
) -> dict[str, Any]:
    """The "origen" block for a coordinate, without generating a budget (no route distance)."""
    rules = load_rules(settings.rules_path)
    visio_con = red_fibra_pg.connect_or_none()
    try:
        seg, busqueda, desde_visio = _resolver_conexion(lat, lon, rules, visio_con, radio,
                                                        tolerate_kmz_errors=True)
        chain: list[db.ChainMufa] = []
        if seg is not None and seg.is_mufa and not desde_visio:
            try:
                chain = db.find_upstream_mufa_chain(seg.id, seg.nombre, rules["excluded_tipo_keywords"],
                                                    rules["connection"].get("upstream_chain", {}))
            except db.DatabaseError:
                chain = []
        origin = (_traffic_origin(seg, chain, rules, visio_con)[0] if seg is not None
                  else origen.TrafficOrigin(reason="sin punto de conexión"))
        block = _origen_block(seg, busqueda, desde_visio, origin, rules, None)
    finally:
        if visio_con is not None:
            visio_con.close()
    return {"origen": block,
            "origen_trafico": {"mf": origin.origin_mufa, "nodo": origin.node,
                               "confianza": origin.confidence, "camino": origin.path,
                               "motivo": origin.reason, "metodo": origin.match_method,
                               "emparejamiento": origin.name_match, "diagnostico": origin.diagnostico}}


def _route_map(req: TicketRequest, seg: db.Segment, route: routing.Route, busqueda: red_fibra_pg.BusquedaVisio,
               desde_visio: bool, poles: list[db.ExistingPole], rules: dict[str, Any],
               output_dir: Path | None = None) -> Path | None:
    """Satellite map of the route for the Excel (in <output_dir>/mapas); None when disabled or the tiles fail."""
    config = rules.get("route_map", {})
    if not config.get("enabled", True):
        return None
    # Nearby Visio nodes, except the one that is the connection point itself.
    nodes = busqueda.alternativas if desde_visio else [n for n in [busqueda.nodo] if n] + busqueda.alternativas
    alternativas = [n for n in nodes
                    if origen._distance_m(seg.lat, seg.lon, n["lat"], n["lon"]) > config.get("same_point_m", 15)]
    safe_ticket = re.sub(r"[^A-Za-z0-9_-]", "_", req.ticket_id)[:64] or "ticket"
    return mapa_ruta.generar_mapa_ruta(
        route.points,
        {"nombre": seg.nombre or seg.tipo, "lat": seg.lat, "lon": seg.lon},
        {"nombre": req.client_name, "lat": req.latitude, "lon": req.longitude},
        alternativas[:4],
        False,
        (output_dir or settings.output_dir) / "mapas" / f"{safe_ticket}.png",
        postes=[(pole.lat, pole.lon) for pole in poles],
        distancia_ruta_m=route.distance_m,
        timeout_s=float(config.get("tile_timeout_s", 10)),
        max_zoom=int(config.get("max_zoom", mapa_ruta.MAX_ZOOM)),
    )


def _generar_presupuesto(req: TicketRequest) -> dict[str, Any]:
    """Nearest segment -> Google route -> materials -> Excel file."""
    visio_con = red_fibra_pg.connect_or_none()
    try:
        return _generar_presupuesto_con(req, visio_con)
    finally:
        if visio_con is not None:
            visio_con.close()


def hardware_fibra(rules: dict[str, Any], cable_key: str, hay_ducto: bool) -> dict[str, Any]:
    """The MATERIALES rules of the fibre and the hanging hardware for the cable type used. The fibre material is what is installed: the aerial
    row, and also the duct row when the route goes through wells (only for the material of the cable type used)."""
    cable = rules["cable"]
    fibra = {etiqueta: dict(valor) if isinstance(valor, dict) else valor for etiqueta, valor in cable.get("fiber_material_from_install", {}).items()}
    ducto = rules["route"].get("duct_install_row_label")
    if hay_ducto and ducto:
        etiqueta = cable["flat_material_label"] if cable_key == "flat" else cable["adss_material_label"]
        if isinstance(fibra.get(etiqueta), dict) and "same_as_install" in fibra[etiqueta]:
            fibra[etiqueta] = {"same_as_install": [fibra[etiqueta]["same_as_install"], ducto]}
    return {**fibra, **cable.get("hardware_by_cable_type", {}).get(cable_key, {})}


def _generar_presupuesto_con(req: TicketRequest, visio_con: Any, *, output_dir: Path | None = None,
                             get_route: Any = None,
                             new_poles_marked_existing_m: list[float] | None = None,
                             new_poles_extra: int = 0, mufa_count_override: int | None = None) -> dict[str, Any]:
    """The whole budget for one request: connection point, route, quantities, map, Excel, recalc.

    POST /presupuesto calls it with the defaults (settings.output_dir, routing.get_route). The
    desktop viewer passes output_dir=output/visor and its per-session route cache as get_route,
    so it produces the very same budget without touching the API's files. It may also pass
    new_poles_marked_existing_m: route positions of new poles the user marked on the map as
    already standing; each one that matches a new pole of this route is charged as existing.
    new_poles_extra: poles the user added by hand on the map (viewer only): charged as new poles on top of the computed ones.
    mufa_count_override: mufas to intervene after the user edited the fusion route in the viewer (None: the computed count).
    """
    output_dir = output_dir or settings.output_dir
    get_route = get_route or routing.get_route
    log.info("Ticket %s received (%.6f, %.6f)", req.ticket_id, req.latitude, req.longitude)
    rules = load_rules(settings.rules_path)

    # 1) Connection point: KMZ mufa, then reserva (never a line projection); the Visio
    # network fills in when the KMZ has nothing near the client.
    seg, busqueda, desde_visio = _resolver_conexion(req.latitude, req.longitude, rules, visio_con)
    if seg is None:
        raise HTTPException(status_code=404, detail="No eligible mufa or reserva found")

    # 2) Street route: origin = connection point, destination = client
    try:
        route = get_route(origin=(seg.lat, seg.lon), destination=(req.latitude, req.longitude))
    except routing.RouteNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except routing.RoutingError as exc:
        log.error("Directions failure (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Google Directions API failed")
    # The nearest point by straight line may be a long way round by street, or have no hilos.
    seg, route, seleccion = _elegir_por_ruta(seg, desde_visio, req.latitude, req.longitude, rules,
                                             visio_con, route, get_route)

    route_wkt = _route_linestring_wkt(route.points)
    try:
        route_mufas = db.find_mufas_near_route(
            route_wkt,
            rules.get("fixed_events", {}).get("route_mufa_search_buffer_m", 15),
            rules["excluded_tipo_keywords"],
            excluded_names=reglas_mufas.patrones_sql(reglas_mufas.configuracion(rules)),
        )
    except db.ExistingPolesQueryError:
        raise HTTPException(status_code=500, detail="Database mufa query failed")
    mufas_cfg = reglas_mufas.configuracion(rules)
    route_mufas = reglas_mufas.filtrar(route_mufas, mufas_cfg)

    # Intervened mufas: every mufa the new hilo passes from where the service is fed down
    # to the client, plus any other mufa on the new route. That path comes from the Visio
    # diagrams when they trace it cable by cable (connection mufa -> mufa labelled with the
    # node); otherwise from the PostGIS upstream chain to the distribution mufa. A reserva
    # gets a new mufa instead, whose price already includes the intervention.
    intervened: dict[Any, str | None] = {}
    if desde_visio:
        chain = [db.ChainMufa(seg.id, seg.nombre)]   # not in the KMZ: no PostGIS chain
        distribution_reason = None
    elif seg.is_mufa:
        try:
            chain = db.find_upstream_mufa_chain(
                seg.id, seg.nombre, rules["excluded_tipo_keywords"],
                rules["connection"].get("upstream_chain", {}))
        except db.DatabaseError:
            raise HTTPException(status_code=500, detail="Database mufa chain query failed")
        distribution_reason = chain[-1].distribution_reason   # None: no distribution mufa found
    else:
        chain = []
        distribution_reason = None
    origin, origin_warnings = _traffic_origin(seg, chain[:1] if desde_visio else chain, rules, visio_con)
    use_diagram_path = (seg.is_mufa and origin.path_traced
                        and rules.get("traffic_origin", {}).get("count_path_mufas", True))
    if use_diagram_path:
        # path[0] is the connection mufa itself: keep its PostGIS id so route mufas dedupe.
        intervened[seg.id] = seg.nombre
        # the mufas de corte / aérea / punta plana of the path are passed by, not intervened
        intervened.update((f"diagrama:{name}", name) for name in origin.path[1:] if reglas_mufas.usable(name, mufas_cfg))
        mufa_count_source = "diagramas"
    else:
        intervened.update((mufa.id, mufa.nombre) for mufa in reglas_mufas.filtrar(chain, mufas_cfg))
        mufa_count_source = "postgis" if seg.is_mufa else None
    for mufa in route_mufas:
        intervened.setdefault(mufa.id, mufa.nombre)
    mufa_count = len(intervened)
    if mufa_count_override is not None:
        mufa_count = max(0, int(mufa_count_override))
    log.info(
        "Mufa audit: intervened=%d source=%s ids=%s distribution_reason=%s route_ids=%s route_distances_m=%s buffer_m=%s",
        mufa_count,
        mufa_count_source,
        list(intervened),
        distribution_reason,
        [mufa.id for mufa in route_mufas],
        [round(mufa.distance_m, 2) for mufa in route_mufas],
        rules.get("fixed_events", {}).get("route_mufa_search_buffer_m", 50),
    )

    # 3) Existing poles and quantities. Prices/formulas stay in the template.
    try:
        existing_pole_records = db.find_existing_poles_near_route(
            route_wkt,
            rules["poles"]["existing_pole_search_buffer_m"],
        )
    except db.ExistingPolesQueryError:
        raise HTTPException(status_code=500, detail="Database pole query failed")

    existing_pole_records = db.deduplicate_existing_poles(existing_pole_records)
    existing_poles = len(existing_pole_records)
    existing_pole_positions_m = [pole.route_position_m for pole in existing_pole_records]
    # Wells along the route: that stretch is installed in duct, not aerial (business_rules.yaml: ducto; presupuesto.tramos_ducto).
    try:
        pozos_m = db.find_pozos_near_route(route_wkt, float((rules.get("ducto") or {}).get("pozo_search_buffer_m", 15)))
    except db.ExistingPolesQueryError:
        log.warning("Ticket %s: the wells of the route could not be queried; aerial fibre on the whole route", req.ticket_id)
        pozos_m = []
    duct_spans = tramos_ducto(route.distance_m, pozos_m, rules)
    quantities = calcular_presupuesto(
        route.distance_m,
        route.points,
        rules,
        service_type=req.service_type,
        bandwidth=req.bandwidth,
        existing_poles=existing_poles,
        existing_pole_positions_m=existing_pole_positions_m,
        connection_is_mufa=seg.is_mufa,
        connection_is_reserve=seg.is_reserve,
        mufa_count=mufa_count,
        new_connections=1,
        technical_visit=requiere_visita_tecnica([req.client_name, req.raw_comment, req.service_type], rules),
        duct_spans=duct_spans or None,
    )
    existing_poles = quantities[rules["poles"]["existing_pole_row_label"]]      # the poles inside a duct stretch are not used
    pole_spacing_m = rules["poles"]["spacing_m"]
    turns = count_turns(route.points, rules["poles"]["corner_angle_deg"])
    new_pole_label = rules["poles"]["new_pole_row_label"]
    marked_warnings: list[str] = []
    if new_poles_extra:
        quantities[new_pole_label] += int(new_poles_extra)
        marked_warnings.append(f"{int(new_poles_extra)} poste(s) nuevo(s) agregado(s) a mano en el visor")
    if new_poles_marked_existing_m is not None:
        # Viewer only: new poles the user saw standing on the map count as existing poles.
        marked_m, unmatched_m = match_marked_poles(
            new_poles_marked_existing_m,
            (new_pole_positions_in_spans(tramos_aereos(route.distance_m, duct_spans), pole_spacing_m, existing_pole_positions_m,
                                         rules["poles"].get("max_span_m"), rules["poles"].get("max_span_between_existing_m"))
             if duct_spans else
             new_pole_positions_by_gaps(route.distance_m, pole_spacing_m, existing_pole_positions_m,
                                        rules["poles"].get("max_span_m"),
                                        rules["poles"].get("max_span_between_existing_m"))))
        marked = min(len(marked_m), quantities[new_pole_label])
        quantities[new_pole_label] -= marked
        quantities[rules["poles"]["existing_pole_row_label"]] += marked
        existing_poles += marked
        if marked:
            marked_warnings.append(f"{marked} poste(s) nuevo(s) marcado(s) como existente(s) en el visor: validar en campo")
        if unmatched_m:
            marked_warnings.append(f"{len(unmatched_m)} poste(s) marcado(s) en el visor no coinciden con esta ruta: "
                                   "se cobran como nuevos")
    required_poles = existing_poles + quantities[new_pole_label]
    final_distance_m = calcular_metraje_final(route.distance_m, rules)
    reserve_m = round(final_distance_m - route.distance_m, 2)
    materials = calcular_materiales(final_distance_m, required_poles, rules)
    log.info("Route audit: raw_distance_m=%.2f reserve_m=%.2f final_distance_m=%.2f",
             route.distance_m, reserve_m, final_distance_m)
    log.info(
        "Pole audit: required=%d existing=%d new_8m=%d spacing_m=%s",
        required_poles, existing_poles, quantities[new_pole_label], pole_spacing_m,
    )
    budget = {
        "route_distance_m": round(route.distance_m, 2),
        "turns": turns,
        "pole_spacing_m": pole_spacing_m,
        "required_poles": required_poles,
        "existing_poles": existing_poles,
        "existing_pole_positions_m": [round(position, 2) for position in existing_pole_positions_m],
        "new_poles_8m": quantities[new_pole_label],
        "cable_type": materials["cable_type"],
        "final_distance_m": final_distance_m,
        "reserve_m": reserve_m,
        "mufa_count": mufa_count,
        "intervened_mufas": [{"id": mufa_id, "name": name} for mufa_id, name in intervened.items()],
        "distribution_reason": distribution_reason,
        "mufa_count_source": mufa_count_source,
        "mufa_ids": [mufa.id for mufa in route_mufas],
        "mufa_distances_m": [round(mufa.distance_m, 2) for mufa in route_mufas],
        "quantities": quantities,
    }
    if duct_spans:                                   # only with wells: the answer of a route without them keeps its keys
        budget["duct_m"] = round(sum(b - a for a, b in duct_spans), 1)
        budget["duct_spans_m"] = [[a, b] for a, b in duct_spans]
    if new_poles_marked_existing_m is not None:      # viewer only: the API response keeps its keys
        budget["new_poles_marked_existing_m"] = [round(position, 2) for position in marked_m[:marked]]
    distance_km = round(route.distance_m / 1000, 3)
    distance_threshold_km = float(rules.get("budget_alerts", {}).get("distance_threshold_km", 5.0))

    # Customer equipment (MATERIALES): GPON or Metro kit plus one ODF.
    technology, technology_source = seleccionar_tecnologia(
        req.bandwidth, req.technology, req.raw_comment, rules)
    equipment = calcular_equipos(technology, req.odf_rack_ports, rules)
    log.info("Equipment audit: technology=%s source=%s items=%s", technology, technology_source, equipment)

    # New poles are also charged as material, unless the template computes that row itself.
    pole_material = {rules["poles"]["new_pole_material_row_label"]: quantities[new_pole_label]}
    # Traffic-origin node from the Visio diagrams (looked up above); never blocks the budget.
    if origin.node is None:
        traffic_node = PENDING_TEXT
    else:
        traffic_node = origin.node + (" (validar)" if origin.confidence == "baja" else "")
    pending_fields = ["Origen de Tráfico (Nodo)"] if origin.node is None or origin.confidence == "baja" else []
    log.info("Origin audit: node=%s mf=%s confidence=%s label=%r path=%s alternatives=%s saturated=%s reason=%s",
             origin.node, origin.origin_mufa, origin.confidence, origin.label, origin.path,
             origin.alternatives, origin.saturated_mufas, origin.reason)
    # Connection point as the route starts from it, checked against the Visio network.
    origen_block = _origen_block(seg, busqueda, desde_visio, origin, rules, route.distance_m)
    if origen_block["requiere_revision"] or origen_block["sin_punto_cercano"]:
        pending_fields.append("Punto de conexión")
    log.info("Connection audit: fuente=%s nombre=%s revision=%s verificacion=%s visio=%s",
             origen_block["fuente"], origen_block["nombre"], origen_block["requiere_revision"],
             origen_block["verificacion_kmz"], origen_block["nodo_red_mas_cercano"])

    # Satellite map of the route for the "ESQUEMA DE RUTA PROYECTADA" box; never blocks.
    map_png = _route_map(req, seg, route, busqueda, desde_visio, existing_pole_records, rules, output_dir)
    google_maps_url = (f"https://www.google.com/maps/dir/?api=1&origin={seg.lat:.6f},{seg.lon:.6f}"
                       f"&destination={req.latitude:.6f},{req.longitude:.6f}&travelmode=walking")

    # 4) Excel quantities, materials and technical route header.
    excel_data = {
        "route_map_png": map_png,
        "budget_id": secrets.token_hex(16),
        "ticket_id": req.ticket_id,
        "client_name": req.client_name,
        "raw_comment": req.raw_comment,
        "quantities": quantities,
        "materials": {**equipment, **pole_material},
        "hardware": hardware_fibra(rules, materials["cable_key"], bool(duct_spans)),
        "route_fields": {
            "origin_node": "",          # only the node's traffic origin goes in the Excel, never the mufa's (rule of 2026-10-20)
            "traffic_node": traffic_node,
            "connection_point": f"{seg.lat:.6f}, {seg.lon:.6f}"
                                + red_fibra_pg.leyenda_punto_conexion(origen_block),
            "ticket_id": req.ticket_id,
            "client_coordinates": f"{req.latitude:.6f}, {req.longitude:.6f}",
            "sales_exec": req.sales_exec,
            "client_code": req.client_code,
            "contact_name": req.contact_name,
            "contact_phone": req.contact_phone,
        },
    }
    generated = generar_excel(excel_data, rules, settings.template_path, output_dir)
    missing_equipment = [item for item in generated.missing_materials if item in equipment]
    warnings = origin_warnings + marked_warnings + list(generated.warnings)
    if (aviso := _aviso_seleccion(seleccion)) is not None:
        warnings.insert(0, aviso)
    if getattr(route, "aviso", None):                                  # routing.calibrar replaced the street route (walking path / straight line)
        warnings.insert(0, route.aviso)

    # 5) Cache formula results so readers that do not recalculate see real totals.
    values_cached = False
    soffice = recalc.find_soffice(settings.libreoffice_path)
    if soffice is None:
        warnings.append("LibreOffice not found: Excel totals are not cached (Excel recalculates on open)")
    else:
        try:
            recalc.cache_formula_values(generated.path, ["Presupuesto", rules["route_sheet"]["sheet"]], soffice)
            values_cached = True
        except recalc.RecalcError as exc:
            warnings.append(f"Excel totals not cached: {exc}")
    for message in warnings:
        log.warning("Ticket %s: %s", req.ticket_id, message)

    # 5) Response
    return {
        "budget_id": excel_data["budget_id"],
        "ticket_id": req.ticket_id,
        "distance_km": distance_km,
        "exceeds_5km": distance_km > distance_threshold_km,
        "status": "ok",
        "connection_point": {
            "latitude": seg.lat, "longitude": seg.lon,
            "segment_id": seg.id, "segment_tipo": seg.tipo, "name": seg.nombre,
            "straight_distance_to_segment_m": round(seg.distance_m, 1),
            # None when the nearest point was kept; otherwise the points compared by route length
            "selection": seleccion,
        },
        "route": {"distance_m": budget["route_distance_m"], "duration_s": route.duration_s,
                  "turns": budget["turns"]},
        "budget": budget,
        "traffic_origin": asdict(origin),
        "origen": origen_block,
        "ruta": {
            "puntos": len(route.points),
            "aproximada": False,          # no route from Google means no budget (404)
            "mapa_generado": map_png is not None,
            "mapa_archivo": str(map_png) if map_png else None,
            "google_maps_url": google_maps_url,
        },
        "quantities": quantities,
        "equipment": {
            "technology": technology,
            "technology_source": technology_source,
            "items": equipment,
            "missing_in_template": missing_equipment,
        },
        # Manual rows plus equipment the template has no row for (must be added by hand).
        "pending_validation_items": [
            {"item": item, "quantity": quantities.get(item, 0)}
            for item in rules.get("manual_zero_row_labels", [])
        ] + [{"item": item, "quantity": equipment[item]} for item in missing_equipment],
        "pending_validation_poles": [
            {
                "id": pole.id,
                "latitude": pole.lat,
                "longitude": pole.lon,
                "distance_along_route_m": round(pole.route_position_m, 2),
            }
            for pole in existing_pole_records
        ],
        "pending_validation_fields": pending_fields,
        "values_cached": values_cached,
        "warnings": warnings,
        "excel_path": str(generated.path),
        "pdf_url": f"/presupuesto/{excel_data['budget_id']}/pdf",
    }


@app.get("/presupuesto/{budget_id}/excel", dependencies=[Depends(verify_api_key)])
def descargar_excel(
    budget_id: str = PathParam(pattern=r"^[A-Za-z0-9]+$", min_length=1, max_length=64),
) -> FileResponse:
    # Files are named "<client>_<budget_id>.xlsx"; budget_id is alphanumeric, so the glob is safe.
    output_dir = settings.output_dir.resolve()
    matches = sorted(p for p in output_dir.glob(f"*_{budget_id}.xlsx") if p.is_file())
    if not matches:
        raise HTTPException(status_code=404, detail="Budget Excel not found")
    excel_path = matches[0]
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=excel_path.name,
    )


@app.get("/presupuesto/{budget_id}/pdf", dependencies=[Depends(verify_api_key)])
def descargar_pdf(
    budget_id: str = PathParam(pattern=r"^[A-Za-z0-9]+$", min_length=1, max_length=64),
) -> FileResponse:
    """PDF of the budget (route sheet + budget sheet), converted on first request."""
    output_dir = settings.output_dir.resolve()
    matches = sorted(p for p in output_dir.glob(f"*_{budget_id}.xlsx") if p.is_file())
    if not matches:
        raise HTTPException(status_code=404, detail="Budget Excel not found")
    soffice = recalc.find_soffice(settings.libreoffice_path)
    if soffice is None:
        raise HTTPException(status_code=503, detail="LibreOffice no disponible")
    try:
        pdf_path = pdf_export.xlsx_a_pdf(matches[0], soffice)
    except pdf_export.PdfExportError as exc:
        log.error("PDF export failed for %s (%s)", budget_id, exc)
        raise HTTPException(status_code=500, detail=f"No se pudo generar el PDF: {exc}")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)
