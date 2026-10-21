"""App de campo (migración 017): jornadas, puntos y fotos que registran los técnicos desde el teléfono.

Un técnico (rol «tecnico») solo crea y edita SUS puntos mientras están pendientes; un editor o administrador ve los de todos, los corrige y (en la
fase de revisión) los aprueba o rechaza. Enviar es idempotente: el teléfono genera `uuid_cliente` de cada punto y de cada foto, así que reenviar
tras un corte no duplica. Cada cambio del esquema dispara NOTIFY 'campo' (trigger de la migración) para el visor en tiempo real.
"""
import hashlib
import json
import io
import math
import os
import re
import uuid
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import lugares, proyectos, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

TIPOS = ("poste", "mufa", "reserva", "solitaria", "cliente", "otro")
ESTADOS = ("pendiente", "aprobado", "rechazado", "editado")
SUBTIPOS_POSTE = ("ideay", "concreto", "madera", "metal", "cliente")
_MUFA = re.compile(r"^(48|96)(?:\s+(domo|horizontal))?$", re.I)
_UUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_TIPOS_FOTO = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 10.7, 15.1, -87.7, -82.7        # Nicaragua (config.NI_*), with a little margin
LIMITE_PUNTOS = 500
MINIATURA_PX = 320
RAIZ = Path(__file__).resolve().parents[2]
POR_DEFECTO = {"precision_max_m": 10, "duplicado_m": 5, "foto_max_bytes": 3145728, "fotos_por_punto": 8, "puntos_por_lote": 50, "peticiones_por_hora": 1200,
               "trazo_max_puntos": 3000, "trazo_extremo_m": 20, "trazos_por_lote": 20, "red_zona_max_grados": 0.03, "red_max_puntos": 1500, "red_max_lineas": 600}


def configuracion() -> dict[str, Any]:
    """The `campo` section of business_rules.yaml over the defaults."""
    try:
        import yaml
        from config import get_settings
        ruta = Path(get_settings().rules_path)
        datos = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("campo") or {}
    except Exception:                                                # noqa: BLE001 - defaults are fine
        datos = {}
    return {**POR_DEFECTO, **{k: v for k, v in datos.items() if k in POR_DEFECTO}}


def carpeta_fotos() -> Path:
    return Path(os.environ.get("CAMPO_FOTOS_DIR") or RAIZ / "datos_campo" / "fotos")


def exigir_campo(actor: dict[str, Any]) -> None:
    if actor.get("borrado_en") is not None or actor.get("rol") not in ("tecnico", "editor", "administrador"):
        raise SinPermiso("Su usuario no tiene el rol de técnico de campo: pida a un administrador que se lo asigne")


def revisa(actor: dict[str, Any]) -> bool:
    return usuarios.puede_editar(actor)


def _texto(valor: Any, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _numero(valor: Any, campo: str, minimo: float, maximo: float, obligatorio: bool = False) -> float | None:
    if valor is None or valor == "":
        if obligatorio:
            raise DatosInvalidos({campo: "Campo obligatorio"})
        return None
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({campo: "Número no válido"}) from None
    if not math.isfinite(n) or not minimo <= n <= maximo:
        raise DatosInvalidos({campo: f"Debe estar entre {minimo:g} y {maximo:g}"})
    return n


def _fecha(valor: Any, campo: str) -> datetime:
    try:
        f = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        raise DatosInvalidos({campo: "Fecha no válida (ISO 8601)"}) from None
    return f if f.tzinfo else f.replace(tzinfo=timezone.utc)


def _subtipo(tipo: str, valor: Any) -> str | None:
    s = _texto(valor, 40).lower()
    if not s:
        return None
    if tipo == "poste" and s not in SUBTIPOS_POSTE:
        raise DatosInvalidos({"subtipo": "Poste: " + ", ".join(SUBTIPOS_POSTE)})
    if tipo == "mufa":
        m = _MUFA.match(s)
        if not m:
            raise DatosInvalidos({"subtipo": "Mufa: 48 o 96, y domo u horizontal (por ejemplo «48 domo»)"})
        return m.group(1) + (f" {m.group(2).lower()}" if m.group(2) else "")
    return s


def _ewkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon:.8f} {lat:.8f})"


def limpiar_punto(datos: Any, *, completo: bool = True) -> dict[str, Any]:
    """Validated columns of a point (`completo`: a new point, all required fields; otherwise only what the edit brings)."""
    if not isinstance(datos, dict):
        raise DatosInvalidos({"punto": "Punto no válido"})
    v: dict[str, Any] = {}
    if completo or "tipo" in datos:
        tipo = _texto(datos.get("tipo"), 20).lower()
        if tipo not in TIPOS:
            raise DatosInvalidos({"tipo": "Elija " + ", ".join(TIPOS)})
        v["tipo"] = tipo
    if completo or "subtipo" in datos:
        v["subtipo"] = _subtipo(v.get("tipo") or _texto(datos.get("tipo_actual"), 20), datos.get("subtipo"))
    if completo or "nombre" in datos:
        v["nombre"] = _texto(datos.get("nombre"), 160) or (v["tipo"].capitalize() if v.get("tipo") else "")
        if not v["nombre"]:
            raise DatosInvalidos({"nombre": "Campo obligatorio"})
    if completo or "notas" in datos:
        v["notas"] = _texto(datos.get("notas"), 1000)
    if completo or "lat" in datos or "lon" in datos:
        lat = _numero(datos.get("lat"), "lat", LAT_MIN, LAT_MAX, True)
        lon = _numero(datos.get("lon"), "lon", LON_MIN, LON_MAX, True)
        v["ubicacion"] = _ewkt(lat, lon)
    if completo or "precision_m" in datos:
        v["precision_m"] = _numero(datos.get("precision_m"), "precision_m", 0, 100000)
    if completo or "altitud" in datos:
        v["altitud"] = _numero(datos.get("altitud"), "altitud", -500, 9000)
    if completo or "origen_coord" in datos:
        origen = _texto(datos.get("origen_coord") or "gps", 10).lower()
        if origen not in ("gps", "mapa"):
            raise DatosInvalidos({"origen_coord": "gps o mapa"})
        v["origen_coord"] = origen
    if completo:
        v["capturado_en"] = _fecha(datos.get("capturado_en") or datetime.now(timezone.utc).isoformat(), "capturado_en")
    return v


def _publico(f: dict[str, Any]) -> dict[str, Any]:
    salida = {k: f.get(k) for k in ("id", "uuid_cliente", "jornada_id", "usuario_id", "tipo", "subtipo", "nombre", "notas", "lat", "lon", "precision_m",
                                    "altitud", "origen_coord", "estado", "motivo_rechazo", "elemento_red_id", "lugar_id", "version")}
    for k in ("precision_m", "altitud", "lat", "lon"):
        if salida[k] is not None:
            salida[k] = float(salida[k])
    for k in ("capturado_en", "recibido_en", "actualizado_en", "revisado_en"):
        salida[k] = f[k].isoformat() if f.get(k) else None
    salida["usuario"] = f.get("usuario")
    salida["fotos"] = f.get("fotos", [])
    salida["borrado"] = f.get("borrado_en") is not None
    return salida


_SELECT = ("SELECT p.*, ST_Y(p.ubicacion) AS lat, ST_X(p.ubicacion) AS lon, u.nombre AS usuario, "
           "COALESCE((SELECT jsonb_agg(jsonb_build_object('id', f.id, 'tipo', f.tipo, 'tamano', f.tamano) ORDER BY f.id) FROM redes.campo_fotos f "
           "WHERE f.punto_id = p.id AND f.borrado_en IS NULL), '[]'::jsonb) AS fotos "
           "FROM redes.campo_puntos p JOIN redes.usuarios u ON u.id = p.usuario_id")


def _punto(con: Any, id_: int) -> dict[str, Any]:
    f = con.execute(_SELECT + " WHERE p.id = %s", (int(id_),)).fetchone()
    if f is None:
        raise NoEncontrado("El punto no existe")
    return f


def _duplicado(con: Any, ubicacion: str, tipo: str, propio: int | None, metros: float) -> dict[str, Any] | None:
    """The nearest existing element (red base / projects) or other field point of the same kind within `metros`, or None."""
    fila = con.execute(
        "SELECT * FROM (SELECT 'red' AS origen, e.id, e.nombre, e.tipo, ST_Distance(e.ubicacion::geography, %(p)s::geography) AS d FROM redes.elementos e "
        "WHERE e.borrado_en IS NULL AND e.tipo <> 'cliente' AND ST_DWithin(e.ubicacion::geography, %(p)s::geography, %(m)s) "
        "UNION ALL SELECT 'campo', c.id, c.nombre, c.tipo, ST_Distance(c.ubicacion::geography, %(p)s::geography) FROM redes.campo_puntos c "
        "WHERE c.borrado_en IS NULL AND c.estado <> 'rechazado' AND c.id IS DISTINCT FROM %(propio)s AND c.tipo = %(tipo)s "
        "AND ST_DWithin(c.ubicacion::geography, %(p)s::geography, %(m)s)) t ORDER BY d LIMIT 1",
        {"p": ubicacion, "m": metros, "propio": propio, "tipo": tipo}).fetchone()
    return None if fila is None else {"origen": fila["origen"], "id": fila["id"], "nombre": fila["nombre"], "tipo": fila["tipo"], "distancia_m": round(float(fila["d"]), 1)}


# --------------------------------------------------------------------------- jornadas

def _jornada_publica(f: dict[str, Any]) -> dict[str, Any]:
    return {"id": f["id"], "usuario_id": f["usuario_id"], "nombre": f["nombre"], "notas": f["notas"], "inicio": f["inicio"].isoformat(),
            "fin": f["fin"].isoformat() if f["fin"] else None, "version": f["version"], "usuario": f.get("usuario")}


def abrir_jornada(con: Any, actor: dict[str, Any], *, nombre: str | None = None, notas: str | None = None) -> dict[str, Any]:
    """Opens today's jornada, or returns the one that is already open (a technician has one at a time)."""
    exigir_campo(actor)
    with con.transaction():
        abierta = con.execute("SELECT * FROM redes.campo_jornadas WHERE usuario_id = %s AND fin IS NULL AND borrado_en IS NULL", (actor["id"],)).fetchone()
        if abierta:
            return {"jornada": _jornada_publica(abierta), "nueva": False}
        nombre = _texto(nombre, 120) or f"Jornada {datetime.now():%Y-%m-%d}"
        fila = repositorio.insertar(con, "campo_jornadas", {"usuario_id": actor["id"], "nombre": nombre, "notas": _texto(notas, 1000)}, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_jornada", fila["id"], "crear", {"nombre": nombre})
    return {"jornada": _jornada_publica(fila), "nueva": True}


def cerrar_jornada(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    exigir_campo(actor)
    with con.transaction():
        fila = repositorio.obtener(con, "campo_jornadas", int(id), bloquear=True)
        if fila["borrado_en"] is not None:
            raise NoEncontrado("La jornada no existe")
        if fila["usuario_id"] != actor["id"] and not revisa(actor):
            raise SinPermiso("Esa jornada es de otro técnico")
        if fila["fin"] is None:
            _, fila = repositorio.actualizar(con, "campo_jornadas", fila["id"], fila["version"], {"fin": datetime.now(timezone.utc)}, actor["id"])
            repositorio.registrar(con, actor["id"], "campo_jornada", fila["id"], "editar", {"fin": "cerrada"})
    return {"jornada": _jornada_publica(fila)}


def jornadas(con: Any, actor: dict[str, Any], *, usuario_id: int | None = None, limite: int = 50) -> dict[str, Any]:
    """The technician's own jornadas; reviewers see everybody's (optionally one technician's)."""
    exigir_campo(actor)
    quien = usuario_id if revisa(actor) and usuario_id else (None if revisa(actor) else actor["id"])
    filas = con.execute(
        "SELECT j.*, u.nombre AS usuario FROM redes.campo_jornadas j JOIN redes.usuarios u ON u.id = j.usuario_id WHERE j.borrado_en IS NULL "
        "AND (%s::bigint IS NULL OR j.usuario_id = %s) ORDER BY j.inicio DESC LIMIT %s", (quien, quien, max(1, min(int(limite), 200)))).fetchall()
    return {"jornadas": [_jornada_publica(f) for f in filas]}


# --------------------------------------------------------------------------- puntos

def _jornada_de(con: Any, actor: dict[str, Any], jornada_id: Any) -> int | None:
    if jornada_id in (None, ""):
        f = con.execute("SELECT id FROM redes.campo_jornadas WHERE usuario_id = %s AND fin IS NULL AND borrado_en IS NULL", (actor["id"],)).fetchone()
        return f["id"] if f else None
    f = con.execute("SELECT id FROM redes.campo_jornadas WHERE id = %s AND usuario_id = %s AND borrado_en IS NULL", (int(jornada_id), actor["id"])).fetchone()
    if f is None:
        raise DatosInvalidos({"jornada_id": "La jornada no es suya o no existe"})
    return f["id"]


def _guardar_uno(con: Any, actor: dict[str, Any], datos: Any, metros: float) -> dict[str, Any]:
    uid = str((datos or {}).get("uuid_cliente") or "") if isinstance(datos, dict) else ""
    if not _UUID.match(uid):
        raise DatosInvalidos({"uuid_cliente": "Falta el identificador del punto (uuid_cliente)"})
    with con.transaction():
        existente = con.execute("SELECT id, usuario_id FROM redes.campo_puntos WHERE uuid_cliente = %s", (uid,)).fetchone()
        if existente:
            if existente["usuario_id"] != actor["id"]:
                raise SinPermiso("Ese identificador ya lo usa otro técnico")
            return {"punto": _publico(_punto(con, existente["id"])), "repetido": True, "duplicado": None}
        valores = limpiar_punto(datos)
        valores.update(uuid_cliente=uid, usuario_id=actor["id"], jornada_id=_jornada_de(con, actor, datos.get("jornada_id")))
        fila = repositorio.insertar(con, "campo_puntos", valores, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_punto", fila["id"], "crear", {k: valores[k] for k in ("tipo", "subtipo", "nombre") if k in valores})
        duplicado = _duplicado(con, valores["ubicacion"], valores["tipo"], fila["id"], metros)
    return {"punto": _publico(_punto(con, fila["id"])), "repetido": False, "duplicado": duplicado}


def guardar_puntos(con: Any, actor: dict[str, Any], *, puntos: list[dict[str, Any]]) -> dict[str, Any]:
    """A batch of points (idempotent by uuid_cliente). Each one is saved on its own: one wrong point does not stop the others. Answer: one result
    per point, in order: {uuid_cliente, ok, punto, repetido, duplicado} or {uuid_cliente, ok: false, error, errores}."""
    exigir_campo(actor)
    cfg = configuracion()
    if not isinstance(puntos, list) or not puntos:
        raise DatosInvalidos({"puntos": "Envíe al menos un punto"})
    if len(puntos) > int(cfg["puntos_por_lote"]):
        raise DatosInvalidos({"puntos": f"Máximo {cfg['puntos_por_lote']} puntos por envío"})
    resultados = []
    for p in puntos:
        uid = p.get("uuid_cliente") if isinstance(p, dict) else None
        try:
            resultados.append({"uuid_cliente": uid, "ok": True, **_guardar_uno(con, actor, p, float(cfg["duplicado_m"]))})
        except DatosInvalidos as exc:
            resultados.append({"uuid_cliente": uid, "ok": False, "error": str(exc), "errores": exc.errores})
        except SinPermiso as exc:
            resultados.append({"uuid_cliente": uid, "ok": False, "error": str(exc)})
    return {"resultados": resultados, "ahora": datetime.now(timezone.utc).isoformat()}


def puntos(con: Any, actor: dict[str, Any], *, desde: str | None = None, jornada: int | None = None, estado: str | None = None,
           usuario_id: int | None = None, limite: int = 200) -> dict[str, Any]:
    """Field points changed after `desde` (ISO time; also the deleted ones, flagged `borrado`, so a client can remove them). A technician only sees
    his own; a reviewer sees everybody's. `ahora` is the `desde` of the next call."""
    exigir_campo(actor)
    if estado and estado not in ESTADOS:
        raise DatosInvalidos({"estado": "Estado no válido"})
    quien = usuario_id if revisa(actor) else actor["id"]
    desde_f = _fecha(desde, "desde") if desde else None
    filas = con.execute(
        _SELECT + " WHERE (%(u)s::bigint IS NULL OR p.usuario_id = %(u)s) AND (%(j)s::bigint IS NULL OR p.jornada_id = %(j)s) "
        "AND (%(e)s::text IS NULL OR p.estado = %(e)s) AND (%(d)s::timestamptz IS NULL OR p.actualizado_en > %(d)s) "
        "AND (%(d)s::timestamptz IS NOT NULL OR p.borrado_en IS NULL) ORDER BY p.actualizado_en, p.id LIMIT %(l)s",
        {"u": quien, "j": jornada, "e": estado, "d": desde_f, "l": max(1, min(int(limite), LIMITE_PUNTOS))}).fetchall()
    # ten seconds back: a transaction still open when this one read has an earlier `actualizado_en`; asking again with this time never loses it
    ahora = con.execute("SELECT now() - interval '10 seconds' AS n").fetchone()["n"]
    salida = [_publico(f) for f in filas]
    if revisa(actor):                                           # a reviewer sees, for each point still to be decided, whether something already exists there
        metros = float(configuracion()["duplicado_m"])
        for f, p in zip(filas, salida):
            if f["estado"] in ("pendiente", "editado") and f["borrado_en"] is None:
                p["duplicado"] = _duplicado(con, f["ubicacion"], f["tipo"], f["id"], metros)
    return {"puntos": salida, "ahora": ahora.isoformat(), "mas": len(filas) >= max(1, min(int(limite), LIMITE_PUNTOS))}


def _editable(actor: dict[str, Any], fila: dict[str, Any]) -> None:
    if fila["borrado_en"] is not None:
        raise NoEncontrado("El punto no existe")
    if fila["usuario_id"] != actor["id"] and not revisa(actor):
        raise SinPermiso("Ese punto es de otro técnico")
    if fila["estado"] in ("aprobado", "rechazado"):
        raise SinPermiso(f"El punto ya fue {fila['estado']}: no se puede cambiar")


def editar_punto(con: Any, actor: dict[str, Any], *, id: int, version: int, cambios: dict[str, Any]) -> dict[str, Any]:
    """Edits a pending point (its owner, or a reviewer: then it becomes «editado»)."""
    exigir_campo(actor)
    with con.transaction():
        fila = repositorio.obtener(con, "campo_puntos", int(id), bloquear=True)
        _editable(actor, fila)
        cambios = dict(cambios or {}, tipo_actual=fila["tipo"])
        valores = limpiar_punto(cambios, completo=False)
        if "subtipo" not in cambios and "tipo" in cambios and valores.get("tipo") != fila["tipo"]:
            valores["subtipo"] = None
        if not valores:
            raise DatosInvalidos({"punto": "No hay nada que cambiar"})
        if fila["usuario_id"] != actor["id"]:
            valores["estado"] = "editado"
        antes, despues = repositorio.actualizar(con, "campo_puntos", fila["id"], int(version), valores, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_punto", fila["id"], "editar", repositorio.diferencias(antes, despues))
        duplicado = _duplicado(con, despues["ubicacion"], despues["tipo"], fila["id"], float(configuracion()["duplicado_m"])) if "ubicacion" in valores else None
    return {"punto": _publico(_punto(con, fila["id"])), "duplicado": duplicado}


def borrar_punto(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Deletes (logically) a pending point; its photos stay on disk with it."""
    exigir_campo(actor)
    with con.transaction():
        fila = repositorio.obtener(con, "campo_puntos", int(id), bloquear=True)
        _editable(actor, fila)
        antes, despues = repositorio.actualizar(con, "campo_puntos", fila["id"], fila["version"], {"borrado_en": datetime.now(timezone.utc)}, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_punto", fila["id"], "eliminar", {"nombre": fila["nombre"]})
    return {"id": fila["id"]}


# --------------------------------------------------------------------------- fotos

def _tipo_foto(datos: bytes) -> str | None:
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return next((t for firma, t in _TIPOS_FOTO.items() if datos.startswith(firma)), None)


def _miniatura(datos: bytes) -> bytes | None:
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(datos)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((MINIATURA_PX, MINIATURA_PX))
            salida = io.BytesIO()
            im.save(salida, "JPEG", quality=70)
            return salida.getvalue()
    except Exception:                                                # noqa: BLE001 - a photo without thumbnail is still a photo
        return None


def subir_foto(con: Any, actor: dict[str, Any], *, punto_id: int, datos: bytes, uuid_cliente: str | None = None) -> dict[str, Any]:
    """Stores a photo of a pending point (JPEG, PNG or WebP up to `foto_max_bytes`). Idempotent by `uuid_cliente`."""
    exigir_campo(actor)
    cfg = configuracion()
    if not isinstance(datos, (bytes, bytearray)) or not datos:
        raise DatosInvalidos({"foto": "La foto está vacía"})
    if len(datos) > int(cfg["foto_max_bytes"]):
        raise DatosInvalidos({"foto": f"La foto pesa {len(datos) // 1024} KB; el máximo es {int(cfg['foto_max_bytes']) // 1024} KB"})
    tipo = _tipo_foto(bytes(datos))
    if tipo is None:
        raise DatosInvalidos({"foto": "Solo se aceptan fotos JPEG, PNG o WebP"})
    uid = _texto(uuid_cliente, 64) or None
    if uid and not _UUID.match(uid):
        raise DatosInvalidos({"uuid_cliente": "Identificador no válido"})
    with con.transaction():
        punto = repositorio.obtener(con, "campo_puntos", int(punto_id), bloquear=True)
        _editable(actor, punto)
        if uid:
            previa = con.execute("SELECT id, punto_id FROM redes.campo_fotos WHERE uuid_cliente = %s", (uid,)).fetchone()
            if previa:
                return {"foto": {"id": previa["id"], "punto_id": previa["punto_id"]}, "repetida": True}
        n = con.execute("SELECT count(*) AS n FROM redes.campo_fotos WHERE punto_id = %s AND borrado_en IS NULL", (punto["id"],)).fetchone()["n"]
        if n >= int(cfg["fotos_por_punto"]):
            raise DatosInvalidos({"foto": f"Un punto admite hasta {cfg['fotos_por_punto']} fotos"})
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[tipo]
        relativa = f"{datetime.now():%Y%m}/{punto['id']}/{uuid.uuid4().hex}.{extension}"
        destino = carpeta_fotos() / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(bytes(datos))
        try:
            fila = repositorio.insertar(con, "campo_fotos", {"uuid_cliente": uid, "punto_id": punto["id"], "archivo": relativa, "tipo": tipo,
                                                             "tamano": len(datos), "miniatura": _miniatura(bytes(datos))}, actor["id"])
            repositorio.registrar(con, actor["id"], "campo_punto", punto["id"], "editar", {"foto": fila["id"], "tamano": len(datos),
                                                                                         "sha1": hashlib.sha1(bytes(datos)).hexdigest()[:12]})
        except Exception:
            destino.unlink(missing_ok=True)
            raise
    return {"foto": {"id": fila["id"], "punto_id": punto["id"], "tipo": tipo, "tamano": len(datos)}, "repetida": False}


def foto(con: Any, actor: dict[str, Any], *, id: int, miniatura: bool = False) -> dict[str, Any]:
    """{tipo, datos}: the photo (or its thumbnail) for its owner or a reviewer."""
    exigir_campo(actor)
    f = con.execute("SELECT f.*, p.usuario_id FROM redes.campo_fotos f JOIN redes.campo_puntos p ON p.id = f.punto_id WHERE f.id = %s AND f.borrado_en IS NULL",
                    (int(id),)).fetchone()
    if f is None:
        raise NoEncontrado("La foto no existe")
    if f["usuario_id"] != actor["id"] and not revisa(actor):
        raise SinPermiso("Esa foto es de otro técnico")
    if miniatura and f["miniatura"]:
        return {"tipo": "image/jpeg", "datos": bytes(f["miniatura"])}
    ruta = carpeta_fotos() / f["archivo"]
    if not ruta.is_file():
        raise NoEncontrado("El archivo de la foto no está en el servidor")
    return {"tipo": f["tipo"], "datos": ruta.read_bytes()}


def foto_datos(con: Any, actor: dict[str, Any], *, id: int, miniatura: bool = False) -> dict[str, Any]:
    """The photo as base64 (what the viewer's JSON calls can carry): {tipo, datos}."""
    f = foto(con, actor, id=id, miniatura=miniatura)
    return {"tipo": f["tipo"], "datos": base64.b64encode(f["datos"]).decode("ascii")}


# --------------------------------------------------------------------------- ubicación en vivo de los técnicos

def ubicacion(con: Any, actor: dict[str, Any], *, lat: float, lon: float, precision_m: float | None = None, capturado_en: str | None = None) -> dict[str, Any]:
    """The technician''s last position (one row per technician, no history). The app sends it every 20 seconds while it is open."""
    exigir_campo(actor)
    la = _numero(lat, "lat", LAT_MIN, LAT_MAX, True)
    lo = _numero(lon, "lon", LON_MIN, LON_MAX, True)
    pr = _numero(precision_m, "precision_m", 0, 100000)
    hora = _fecha(capturado_en or datetime.now(timezone.utc).isoformat(), "capturado_en")
    con.execute("INSERT INTO redes.campo_ubicaciones (usuario_id, ubicacion, precision_m, capturado_en) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (usuario_id) DO UPDATE SET ubicacion = EXCLUDED.ubicacion, precision_m = EXCLUDED.precision_m, "
                "capturado_en = EXCLUDED.capturado_en, recibido_en = now()", (actor["id"], _ewkt(la, lo), pr, hora))
    return {}


def ubicaciones(con: Any, actor: dict[str, Any], *, minutos: int = 480) -> dict[str, Any]:
    """Where each technician was last seen (the ones heard from in the last `minutos`). Reviewers only."""
    exigir_revisor(con, actor)
    filas = con.execute(
        "SELECT l.usuario_id, u.nombre, ST_Y(l.ubicacion) AS lat, ST_X(l.ubicacion) AS lon, l.precision_m, l.capturado_en, l.recibido_en, "
        "EXTRACT(EPOCH FROM now() - l.recibido_en)::int AS hace_s FROM redes.campo_ubicaciones l JOIN redes.usuarios u ON u.id = l.usuario_id "
        "WHERE l.recibido_en > now() - make_interval(mins => %s) AND u.borrado_en IS NULL ORDER BY u.nombre", (max(1, min(int(minutos), 10080)),)).fetchall()
    return {"ubicaciones": [{"usuario_id": f["usuario_id"], "nombre": f["nombre"], "lat": float(f["lat"]), "lon": float(f["lon"]),
                             "precision_m": None if f["precision_m"] is None else float(f["precision_m"]), "hace_s": f["hace_s"],
                             "capturado_en": f["capturado_en"].isoformat()} for f in filas]}


# --------------------------------------------------------------------------- revisión: rechazar y aprobar

def exigir_revisor(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """For the endpoints that only a reviewer (administrator or editor) may call."""
    if not revisa(actor):
        raise SinPermiso("Solo un administrador o un editor revisa los puntos de campo")
    return {}


def _ids(ids: Any) -> list[int]:
    try:
        lista = list(dict.fromkeys(int(i) for i in (ids or [])))
    except (TypeError, ValueError):
        raise DatosInvalidos({"ids": "Puntos no válidos"}) from None
    if not lista or len(lista) > 200:
        raise DatosInvalidos({"ids": "Elija de 1 a 200 puntos"})
    return lista


def _por_decidir(con: Any, id_: int) -> dict[str, Any]:
    fila = repositorio.obtener(con, "campo_puntos", id_, bloquear=True)
    if fila["borrado_en"] is not None:
        raise NoEncontrado("El punto fue borrado")
    if fila["estado"] not in ("pendiente", "editado"):
        raise DatosInvalidos({"estado": f"El punto ya fue {fila['estado']}"})
    return fila


def rechazar(con: Any, actor: dict[str, Any], *, ids: list[int], motivo: str) -> dict[str, Any]:
    """Rejects pending points with a reason the technician can read in his list."""
    exigir_revisor(con, actor)
    motivo = _texto(motivo, 300)
    if len(motivo) < 3:
        raise DatosInvalidos({"motivo": "Escriba el motivo del rechazo"})
    resultados = []
    for id_ in _ids(ids):
        try:
            with con.transaction():
                fila = _por_decidir(con, id_)
                antes, despues = repositorio.actualizar(con, "campo_puntos", id_, fila["version"], {"estado": "rechazado", "motivo_rechazo": motivo,
                                                        "revisado_por": actor["id"], "revisado_en": datetime.now(timezone.utc)}, actor["id"])
                repositorio.registrar(con, actor["id"], "campo_punto", id_, "editar", repositorio.diferencias(antes, despues))
            resultados.append({"id": id_, "ok": True})
        except (DatosInvalidos, NoEncontrado) as exc:
            resultados.append({"id": id_, "ok": False, "error": str(exc)})
    return {"resultados": resultados}


def _proyecto_destino(con: Any, actor: dict[str, Any], destino: str, proyecto_id: Any) -> int:
    """The project that receives poles / mufas: a base project («red») or a project of its own («proyecto»)."""
    if destino == "red":
        bases = [f["id"] for f in con.execute("SELECT id FROM redes.proyectos WHERE es_red_base AND borrado_en IS NULL ORDER BY id").fetchall()]
        if proyecto_id in (None, ""):
            if len(bases) == 1:
                proyecto_id = bases[0]
            else:
                raise DatosInvalidos({"proyecto_id": "Elija la red base (hay " + ("ninguna" if not bases else "varias") + ")"})
        if int(proyecto_id) not in bases:
            raise DatosInvalidos({"proyecto_id": "Ese proyecto no es una red base"})
    else:
        if proyecto_id in (None, ""):
            raise DatosInvalidos({"proyecto_id": "Elija el proyecto"})
        f = con.execute("SELECT es_red_base FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL", (int(proyecto_id),)).fetchone()
        if f is None:
            raise NoEncontrado("El proyecto no existe")
        if f["es_red_base"]:
            raise DatosInvalidos({"proyecto_id": "Ese es una red base: use el destino «Red base»"})
    if not proyectos.puede_editar(con, actor, int(proyecto_id)):
        raise SinPermiso("No tiene permiso para editar ese proyecto")
    return int(proyecto_id)


def _a_elemento(con: Any, actor: dict[str, Any], p: dict[str, Any], proyecto_id: int) -> int:
    """A pole / mufa (or the client''s house) of a project from a field point; the technician and the capture go in `propiedades`."""
    if p["tipo"] not in ("poste", "mufa", "cliente"):
        raise DatosInvalidos({"tipo": f"Un punto «{p['tipo']}» no va a un proyecto ni a la red: envíelo a Mis lugares"})
    props: dict[str, Any] = {"campo": {"punto_id": p["id"], "tecnico_id": p["usuario_id"], "precision_m": None if p["precision_m"] is None else float(p["precision_m"]),
                                       "capturado_en": p["capturado_en"].isoformat(), "notas": p["notas"]}}
    subtipo = p["subtipo"]
    if p["tipo"] == "mufa":                                      # «48 domo» -> capacidad and formato (the mufa subtipos of the editor are empalme / FDT / FAT)
        partes = (subtipo or "").split()
        if partes:
            props["capacidad"] = int(partes[0])
        if len(partes) > 1:
            props["formato"] = partes[1]
        subtipo = None
    if p["tipo"] == "cliente":
        subtipo = None
    gps_bueno = p["origen_coord"] == "gps" and p["precision_m"] is not None and float(p["precision_m"]) <= float(configuracion()["precision_max_m"])
    fila = repositorio.insertar(con, "elementos", {
        "proyecto_id": proyecto_id, "tipo": p["tipo"], "subtipo": subtipo, "nombre": p["nombre"], "ubicacion": con.execute(
            "SELECT ST_AsEWKT(ubicacion) AS e FROM redes.campo_puntos WHERE id = %s", (p["id"],)).fetchone()["e"],
        "propiedades": Jsonb(props), "fuente": "usuario", "confianza": "alta" if gps_bueno else "media",
        "ubicacion_fuente": "real" if p["origen_coord"] == "gps" else "usuario"}, actor["id"])
    repositorio.registrar(con, actor["id"], "elemento", fila["id"], "crear", {"nombre": [None, p["nombre"]], "tipo": [None, p["tipo"]], "origen": [None, "campo"]}, proyecto_id)
    return fila["id"]


_LETRA_LUGAR = {"poste": "P", "mufa": "M", "reserva": "R", "solitaria": "S", "cliente": "C", "otro": "O"}
_COLOR_LUGAR = {"poste": "#8d6e63", "mufa": "#1e88e5", "reserva": "#fb8c00", "solitaria": "#8e24aa", "cliente": "#43a047", "otro": "#546e7a"}


def _carpeta_campo(con: Any, actor: dict[str, Any], tecnico: str) -> int:
    """The reviewer''s own folder «Campo – <technician>» in Mis lugares (created the first time)."""
    nombre = f"Campo – {tecnico}"[:160]
    f = con.execute("SELECT id FROM redes.lugares_carpetas WHERE usuario_id = %s AND padre_id IS NULL AND nombre = %s AND borrado_en IS NULL",
                    (actor["id"], nombre)).fetchone()
    if f:
        return f["id"]
    return lugares.guardar_carpeta(con, actor, nombre=nombre)["id"]


def _a_lugar(con: Any, actor: dict[str, Any], p: dict[str, Any], carpeta_id: int | None) -> int:
    """A marca in Mis lugares with the point''s data and photos in its description."""
    tecnico = con.execute("SELECT nombre FROM redes.usuarios WHERE id = %s", (p["usuario_id"],)).fetchone()["nombre"]
    carpeta = int(carpeta_id) if carpeta_id else _carpeta_campo(con, actor, tecnico)
    geo = con.execute("SELECT ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.campo_puntos WHERE id = %s", (p["id"],)).fetchone()
    imagenes, html_fotos = [], ""
    for i, f in enumerate(con.execute("SELECT id FROM redes.campo_fotos WHERE punto_id = %s AND borrado_en IS NULL ORDER BY id", (p["id"],)).fetchall()):
        d = foto(con, actor, id=f["id"])["datos"]
        if len(d) > lugares.MAX_ADJUNTO:
            d = foto(con, actor, id=f["id"], miniatura=True)["datos"]
        imagenes.append({"ref": f"f{i}", "nombre": f"foto{i + 1}.jpg", "datos": base64.b64encode(d).decode("ascii")})
        html_fotos += f'<p><img data-nuevo="f{i}"></p>'
    esc = lambda t: str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    gps = "" if p["precision_m"] is None else f" · GPS ±{float(p['precision_m']):.0f} m"
    detalle = (f"<p><b>{esc(p['tipo'].capitalize())}</b>{' · ' + esc(p['subtipo']) if p['subtipo'] else ''}<br>Levantado por {esc(tecnico)} el "
               f"{p['capturado_en']:%Y-%m-%d %H:%M}{gps}</p>{'<p>' + esc(p['notas']) + '</p>' if p['notas'] else ''}{html_fotos}")
    lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="marca", nombre=p["nombre"], geom={"type": "Point", "coordinates": [float(geo["lon"]), float(geo["lat"])]},
                                  descripcion_html=detalle, imagenes=imagenes,
                                  estilo={"icono": {"tipo": "letra", "id": _LETRA_LUGAR[p["tipo"]], "color": _COLOR_LUGAR[p["tipo"]], "escala": 1.1, "opacidad": 1}},
                                  propiedades={"campo": {"punto_id": p["id"], "tecnico": tecnico}})
    return lugar["lugar"]["id"] if "lugar" in lugar else lugar["id"]


def aprobar(con: Any, actor: dict[str, Any], *, ids: list[int], destino: str, proyecto_id: int | None = None, carpeta_id: int | None = None) -> dict[str, Any]:
    """Approves pending points: `destino` «red» (poles / mufas into a base project), «proyecto» (poles / mufas / client houses into a project of its own)
    or «lugares» (a marca in the reviewer''s Mis lugares). Each point on its own: one that cannot go there says why and the others go on."""
    exigir_revisor(con, actor)
    if destino not in ("red", "proyecto", "lugares"):
        raise DatosInvalidos({"destino": "Elija red base, proyecto o Mis lugares"})
    lista = _ids(ids)
    proyecto = _proyecto_destino(con, actor, destino, proyecto_id) if destino != "lugares" else None
    if destino == "lugares" and carpeta_id:
        lugares._exigir(con, actor, int(carpeta_id), editar=True)
    resultados = []
    for id_ in lista:
        try:
            with con.transaction():
                p = _por_decidir(con, id_)
                if proyecto is not None:
                    elemento, lugar = _a_elemento(con, actor, p, proyecto), None
                else:
                    elemento, lugar = None, _a_lugar(con, actor, p, carpeta_id)
                antes, despues = repositorio.actualizar(con, "campo_puntos", id_, p["version"], {"estado": "aprobado", "elemento_red_id": elemento, "lugar_id": lugar,
                                                        "revisado_por": actor["id"], "revisado_en": datetime.now(timezone.utc), "motivo_rechazo": None}, actor["id"])
                repositorio.registrar(con, actor["id"], "campo_punto", id_, "editar", repositorio.diferencias(antes, despues))
            resultados.append({"id": id_, "ok": True, "elemento_id": elemento, "lugar_id": lugar})
        except (DatosInvalidos, NoEncontrado, SinPermiso) as exc:
            resultados.append({"id": id_, "ok": False, "error": str(exc)})
    return {"resultados": resultados, "proyecto_id": proyecto}



# --------------------------------------------------------------------------- cables trazados en campo

HILOS_CABLE = (2, 4, 6, 8, 12, 24, 48, 72, 96, 144)
MODOS_TRAZO = ("puntos", "postes", "recorrido")
TIPOS_CABLE = ("ADSS", "FLAT")


def limpiar_trazo(datos: Any, *, completo: bool = True) -> dict[str, Any]:
    """Validated columns of a trace: `puntos` [{lat, lon}] (Nicaragua, at least two different ones), modo, tipo_cable, hilos, notas."""
    if not isinstance(datos, dict):
        raise DatosInvalidos({"trazo": "Trazo no válido"})
    v: dict[str, Any] = {}
    if completo or "puntos" in datos:
        puntos = datos.get("puntos")
        maximo = int(configuracion()["trazo_max_puntos"])
        if not isinstance(puntos, list) or len(puntos) < 2:
            raise DatosInvalidos({"puntos": "Un cable necesita al menos dos puntos"})
        if len(puntos) > maximo:
            raise DatosInvalidos({"puntos": f"Un trazo admite hasta {maximo} puntos"})
        pares = []
        for p in puntos:
            if not isinstance(p, dict):
                raise DatosInvalidos({"puntos": "Punto no válido"})
            pares.append((_numero(p.get("lat"), "puntos", LAT_MIN, LAT_MAX, True), _numero(p.get("lon"), "puntos", LON_MIN, LON_MAX, True)))
        if len(set(pares)) < 2:
            raise DatosInvalidos({"puntos": "Los puntos del cable están todos en el mismo lugar"})
        v["geom"] = "SRID=4326;LINESTRING(" + ", ".join(f"{lo:.8f} {la:.8f}" for la, lo in pares) + ")"
        # which vertices were tapped on a pole / point (name and position) so the reviewer sees what the cable follows; at most 200
        postes = [{"nombre": _texto(x.get("nombre"), 80), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in (datos.get("postes") or [])[:200]
                  if isinstance(x, dict) and isinstance(x.get("lat"), (int, float)) and isinstance(x.get("lon"), (int, float))]
        v["postes"] = Jsonb(postes)
    if completo or "modo" in datos:
        modo = _texto(datos.get("modo") or "puntos", 12).lower()
        if modo not in MODOS_TRAZO:
            raise DatosInvalidos({"modo": "puntos, postes o recorrido"})
        v["modo"] = modo
    if completo or "tipo_cable" in datos:
        tipo = _texto(datos.get("tipo_cable"), 8).upper() or None
        if tipo is not None and tipo not in TIPOS_CABLE:
            raise DatosInvalidos({"tipo_cable": "ADSS o FLAT"})
        v["tipo_cable"] = tipo
    if completo or "hilos" in datos:
        hilos = datos.get("hilos")
        if hilos in (None, ""):
            v["hilos"] = None
        else:
            try:
                v["hilos"] = int(hilos)
            except (TypeError, ValueError):
                raise DatosInvalidos({"hilos": "Número no válido"}) from None
            if v["hilos"] not in HILOS_CABLE:
                raise DatosInvalidos({"hilos": "Hilos: " + ", ".join(map(str, HILOS_CABLE))})
    if completo or "notas" in datos:
        v["notas"] = _texto(datos.get("notas"), 1000)
    if completo:
        v["capturado_en"] = _fecha(datos.get("capturado_en") or datetime.now(timezone.utc).isoformat(), "capturado_en")
    return v


_SELECT_TRAZO = ("SELECT t.*, ST_AsGeoJSON(t.geom, 7) AS gj, u.nombre AS usuario FROM redes.campo_trazos t JOIN redes.usuarios u ON u.id = t.usuario_id")


def _publico_trazo(f: dict[str, Any], con_puntos: bool = True) -> dict[str, Any]:
    coords = [[c[1], c[0]] for c in json.loads(f["gj"])["coordinates"]] if con_puntos else []
    salida = {k: f.get(k) for k in ("id", "uuid_cliente", "jornada_id", "usuario_id", "usuario", "modo", "tipo_cable", "hilos", "notas", "estado", "motivo_rechazo",
                                     "cable_id", "lugar_id", "version")}
    salida["longitud_m"] = None if f["longitud_m"] is None else float(f["longitud_m"])
    salida["puntos"] = coords
    salida["n_puntos"] = len(coords) if con_puntos else None
    salida["postes"] = f.get("postes") or []
    for k in ("capturado_en", "recibido_en", "actualizado_en", "revisado_en"):
        salida[k] = f[k].isoformat() if f.get(k) else None
    salida["borrado"] = f.get("borrado_en") is not None
    return salida


def _trazo(con: Any, id_: int) -> dict[str, Any]:
    f = con.execute(_SELECT_TRAZO + " WHERE t.id = %s", (int(id_),)).fetchone()
    if f is None:
        raise NoEncontrado("El trazo no existe")
    return f


def _guardar_un_trazo(con: Any, actor: dict[str, Any], datos: Any) -> dict[str, Any]:
    uid = str((datos or {}).get("uuid_cliente") or "") if isinstance(datos, dict) else ""
    if not _UUID.match(uid):
        raise DatosInvalidos({"uuid_cliente": "Falta el identificador del trazo (uuid_cliente)"})
    with con.transaction():
        existente = con.execute("SELECT id, usuario_id FROM redes.campo_trazos WHERE uuid_cliente = %s", (uid,)).fetchone()
        if existente:
            if existente["usuario_id"] != actor["id"]:
                raise SinPermiso("Ese identificador ya lo usa otro técnico")
            return {"trazo": _publico_trazo(_trazo(con, existente["id"])), "repetido": True}
        valores = limpiar_trazo(datos)
        valores.update(uuid_cliente=uid, usuario_id=actor["id"], jornada_id=_jornada_de(con, actor, datos.get("jornada_id")))
        fila = repositorio.insertar(con, "campo_trazos", valores, actor["id"])
        con.execute("UPDATE redes.campo_trazos SET longitud_m = round(ST_Length(geom::geography)::numeric, 2) WHERE id = %s", (fila["id"],))
        repositorio.registrar(con, actor["id"], "campo_trazo", fila["id"], "crear", {"modo": [None, valores["modo"]], "tipo_cable": [None, valores["tipo_cable"]]})
    return {"trazo": _publico_trazo(_trazo(con, fila["id"])), "repetido": False}


def guardar_trazos(con: Any, actor: dict[str, Any], *, trazos: list[dict[str, Any]]) -> dict[str, Any]:
    """A batch of traces (idempotent by uuid_cliente), each saved on its own like the points."""
    exigir_campo(actor)
    if not isinstance(trazos, list) or not trazos:
        raise DatosInvalidos({"trazos": "Envíe al menos un trazo"})
    if len(trazos) > int(configuracion()["trazos_por_lote"]):
        raise DatosInvalidos({"trazos": f"Máximo {configuracion()['trazos_por_lote']} trazos por envío"})
    resultados = []
    for t in trazos:
        uid = t.get("uuid_cliente") if isinstance(t, dict) else None
        try:
            resultados.append({"uuid_cliente": uid, "ok": True, **_guardar_un_trazo(con, actor, t)})
        except DatosInvalidos as exc:
            resultados.append({"uuid_cliente": uid, "ok": False, "error": str(exc), "errores": exc.errores})
        except SinPermiso as exc:
            resultados.append({"uuid_cliente": uid, "ok": False, "error": str(exc)})
    return {"resultados": resultados, "ahora": datetime.now(timezone.utc).isoformat()}


def trazos(con: Any, actor: dict[str, Any], *, desde: str | None = None, jornada: int | None = None, estado: str | None = None,
           usuario_id: int | None = None, limite: int = 100) -> dict[str, Any]:
    """Traces changed after `desde` (the deleted ones flagged); a technician sees his own, a reviewer everybody's. Same contract as `puntos`."""
    exigir_campo(actor)
    if estado and estado not in ESTADOS:
        raise DatosInvalidos({"estado": "Estado no válido"})
    quien = usuario_id if revisa(actor) else actor["id"]
    tope = max(1, min(int(limite), 200))
    filas = con.execute(
        _SELECT_TRAZO + " WHERE (%(u)s::bigint IS NULL OR t.usuario_id = %(u)s) AND (%(j)s::bigint IS NULL OR t.jornada_id = %(j)s) "
        "AND (%(e)s::text IS NULL OR t.estado = %(e)s) AND (%(d)s::timestamptz IS NULL OR COALESCE(t.actualizado_en, t.recibido_en) > %(d)s) "
        "AND (%(d)s::timestamptz IS NOT NULL OR t.borrado_en IS NULL) ORDER BY COALESCE(t.actualizado_en, t.recibido_en), t.id LIMIT %(l)s",
        {"u": quien, "j": jornada, "e": estado, "d": _fecha(desde, "desde") if desde else None, "l": tope}).fetchall()
    ahora = con.execute("SELECT now() - interval '10 seconds' AS n").fetchone()["n"]
    return {"trazos": [_publico_trazo(f) for f in filas], "ahora": ahora.isoformat(), "mas": len(filas) >= tope}


def _trazo_editable(actor: dict[str, Any], fila: dict[str, Any]) -> None:
    if fila["borrado_en"] is not None:
        raise NoEncontrado("El trazo no existe")
    if fila["usuario_id"] != actor["id"] and not revisa(actor):
        raise SinPermiso("Ese trazo es de otro técnico")
    if fila["estado"] in ("aprobado", "rechazado"):
        raise SinPermiso(f"El trazo ya fue {fila['estado']}: no se puede cambiar")


def editar_trazo(con: Any, actor: dict[str, Any], *, id: int, version: int, cambios: dict[str, Any]) -> dict[str, Any]:
    """Type of cable, fibres and notes of a pending trace (its owner, or a reviewer: then it becomes «editado»). The route itself is not edited: it is traced again."""
    exigir_campo(actor)
    with con.transaction():
        fila = repositorio.obtener(con, "campo_trazos", int(id), bloquear=True)
        _trazo_editable(actor, fila)
        permitido = {k: v for k, v in (cambios or {}).items() if k in ("tipo_cable", "hilos", "notas")}
        valores = limpiar_trazo(permitido, completo=False)
        if not valores:
            raise DatosInvalidos({"trazo": "No hay nada que cambiar"})
        if fila["usuario_id"] != actor["id"]:
            valores["estado"] = "editado"
        antes, despues = repositorio.actualizar(con, "campo_trazos", fila["id"], int(version), valores, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_trazo", fila["id"], "editar", repositorio.diferencias(antes, despues))
    return {"trazo": _publico_trazo(_trazo(con, fila["id"]))}


def borrar_trazo(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    exigir_campo(actor)
    with con.transaction():
        fila = repositorio.obtener(con, "campo_trazos", int(id), bloquear=True)
        _trazo_editable(actor, fila)
        repositorio.actualizar(con, "campo_trazos", fila["id"], fila["version"], {"borrado_en": datetime.now(timezone.utc)}, actor["id"])
        repositorio.registrar(con, actor["id"], "campo_trazo", fila["id"], "eliminar", {"longitud_m": [float(fila["longitud_m"] or 0), None]})
    return {"id": fila["id"]}


def _trazo_por_decidir(con: Any, id_: int) -> dict[str, Any]:
    fila = repositorio.obtener(con, "campo_trazos", id_, bloquear=True)
    if fila["borrado_en"] is not None:
        raise NoEncontrado("El trazo fue borrado")
    if fila["estado"] not in ("pendiente", "editado"):
        raise DatosInvalidos({"estado": f"El trazo ya fue {fila['estado']}"})
    return fila


def rechazar_trazos(con: Any, actor: dict[str, Any], *, ids: list[int], motivo: str) -> dict[str, Any]:
    exigir_revisor(con, actor)
    motivo = _texto(motivo, 300)
    if len(motivo) < 3:
        raise DatosInvalidos({"motivo": "Escriba el motivo del rechazo"})
    resultados = []
    for id_ in _ids(ids):
        try:
            with con.transaction():
                fila = _trazo_por_decidir(con, id_)
                antes, despues = repositorio.actualizar(con, "campo_trazos", id_, fila["version"], {"estado": "rechazado", "motivo_rechazo": motivo,
                                                        "revisado_por": actor["id"], "revisado_en": datetime.now(timezone.utc)}, actor["id"])
                repositorio.registrar(con, actor["id"], "campo_trazo", id_, "editar", repositorio.diferencias(antes, despues))
            resultados.append({"id": id_, "ok": True})
        except (DatosInvalidos, NoEncontrado) as exc:
            resultados.append({"id": id_, "ok": False, "error": str(exc)})
    return {"resultados": resultados}


def _extremo_cercano(con: Any, proyecto_id: int, lat: float, lon: float, metros: float) -> dict[str, Any] | None:
    return con.execute(
        "SELECT id, nombre, tipo, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos WHERE proyecto_id = %(p)s AND borrado_en IS NULL "
        "AND ubicacion IS NOT NULL AND tipo IN ('poste', 'mufa', 'nodo', 'odf') AND ST_DWithin(ubicacion::geography, ST_SetSRID(ST_MakePoint(%(lo)s, %(la)s), 4326)::geography, %(m)s) "
        "ORDER BY ST_Distance(ubicacion::geography, ST_SetSRID(ST_MakePoint(%(lo)s, %(la)s), 4326)::geography) LIMIT 1",
        {"p": proyecto_id, "la": lat, "lo": lon, "m": metros}).fetchone()


def _a_cable(con: Any, actor: dict[str, Any], t: dict[str, Any], proyecto_id: int) -> int:
    """A cable of the project from a trace: it must start and end at a pole or mufa of that project (within `trazo_extremo_m`), as every cable of the network."""
    coords = [[c[1], c[0]] for c in json.loads(con.execute("SELECT ST_AsGeoJSON(geom, 8) AS g FROM redes.campo_trazos WHERE id = %s", (t["id"],)).fetchone()["g"])["coordinates"]]
    metros = float(configuracion()["trazo_extremo_m"])
    ini, fin = _extremo_cercano(con, proyecto_id, *coords[0], metros), _extremo_cercano(con, proyecto_id, *coords[-1], metros)
    if ini is None or fin is None:
        lado = "inicial" if ini is None else "final"
        raise DatosInvalidos({"extremos": f"El extremo {lado} no está a {metros:g} m o menos de un poste o mufa del proyecto: apruebe antes ese punto o use Mis lugares"})
    if ini["id"] == fin["id"]:
        raise DatosInvalidos({"extremos": "El cable empieza y termina en el mismo elemento"})
    cable = {"id": "n1", "nombre": f"Cable {ini['nombre']} – {fin['nombre']}"[:160], "clase": "distribucion", "tipo": t["tipo_cable"] or "ADSS",
             "origen_id": ini["id"], "destino_id": fin["id"], "descripcion": f"Trazado en campo por {t['usuario']}" + (f". {t['notas']}" if t["notas"] else ""),
             "vertices": [{"lat": la, "lon": lo, "elemento_id": None} for la, lo in coords]}
    if t["hilos"]:
        cable["hilos"] = t["hilos"]
    from visor_rutas.redes import red
    return red.guardar(con, actor, proyecto_id=proyecto_id, cambios={"cables": [cable]})["ids"]["n1"]


def _trazo_a_lugar(con: Any, actor: dict[str, Any], t: dict[str, Any], carpeta_id: int | None) -> int:
    """A ruta of Mis lugares with the cable's data in its description."""
    carpeta = int(carpeta_id) if carpeta_id else _carpeta_campo(con, actor, t["usuario"])
    coords = [[c[0], c[1]] for c in json.loads(con.execute("SELECT ST_AsGeoJSON(geom, 8) AS g FROM redes.campo_trazos WHERE id = %s", (t["id"],)).fetchone()["g"])["coordinates"]]
    esc = lambda x: str(x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    datos = " · ".join(x for x in (t["tipo_cable"], f"{t['hilos']} hilos" if t["hilos"] else None, f"{float(t['longitud_m'] or 0):.0f} m", t["modo"]) if x)
    html = f"<p><b>Cable trazado en campo</b><br>{esc(datos)}<br>Por {esc(t['usuario'])} el {t['capturado_en']:%Y-%m-%d %H:%M}</p>{'<p>' + esc(t['notas']) + '</p>' if t['notas'] else ''}"
    lugar = lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="ruta", nombre=f"Cable {t['usuario']} {t['capturado_en']:%d/%m %H:%M}"[:160],
                                  geom={"type": "LineString", "coordinates": coords}, descripcion_html=html,
                                  estilo={"linea": {"color": "#00bcd4", "grosor": 4, "opacidad": 1}}, propiedades={"campo": {"trazo_id": t["id"], "tecnico": t["usuario"]}})
    return lugar["lugar"]["id"]


def aprobar_trazos(con: Any, actor: dict[str, Any], *, ids: list[int], destino: str, proyecto_id: int | None = None, carpeta_id: int | None = None) -> dict[str, Any]:
    """Approves pending traces: «red» / «proyecto» (a cable of that project: its ends must be at poles or mufas of it) or «lugares» (a ruta of the reviewer's Mis lugares)."""
    exigir_revisor(con, actor)
    if destino not in ("red", "proyecto", "lugares"):
        raise DatosInvalidos({"destino": "Elija red base, proyecto o Mis lugares"})
    lista = _ids(ids)
    proyecto = _proyecto_destino(con, actor, destino, proyecto_id) if destino != "lugares" else None
    if destino == "lugares" and carpeta_id:
        lugares._exigir(con, actor, int(carpeta_id), editar=True)
    resultados = []
    for id_ in lista:
        try:
            with con.transaction():
                t = dict(_trazo_por_decidir(con, id_))
                t["usuario"] = con.execute("SELECT nombre FROM redes.usuarios WHERE id = %s", (t["usuario_id"],)).fetchone()["nombre"]
                cable, lugar = (_a_cable(con, actor, t, proyecto), None) if proyecto is not None else (None, _trazo_a_lugar(con, actor, t, carpeta_id))
                antes, despues = repositorio.actualizar(con, "campo_trazos", id_, t["version"], {"estado": "aprobado", "cable_id": cable, "lugar_id": lugar, "motivo_rechazo": None,
                                                        "revisado_por": actor["id"], "revisado_en": datetime.now(timezone.utc)}, actor["id"])
                repositorio.registrar(con, actor["id"], "campo_trazo", id_, "editar", repositorio.diferencias(antes, despues))
            resultados.append({"id": id_, "ok": True, "cable_id": cable, "lugar_id": lugar})
        except (DatosInvalidos, NoEncontrado, SinPermiso) as exc:
            resultados.append({"id": id_, "ok": False, "error": str(exc)})
    return {"resultados": resultados, "proyecto_id": proyecto}


# --------------------------------------------------------------------------- red de referencia para el teléfono

def zona(oeste: Any, sur: Any, este: Any, norte: Any) -> tuple[float, float, float, float]:
    """A valid zone (west, south, east, north) inside Nicaragua and not bigger than `red_zona_max_grados`."""
    o = _numero(oeste, "bbox", LON_MIN, LON_MAX, True)
    s = _numero(sur, "bbox", LAT_MIN, LAT_MAX, True)
    e = _numero(este, "bbox", LON_MIN, LON_MAX, True)
    n = _numero(norte, "bbox", LAT_MIN, LAT_MAX, True)
    if not (o < e and s < n):
        raise DatosInvalidos({"bbox": "La zona debe ir oeste,sur,este,norte"})
    maximo = float(configuracion()["red_zona_max_grados"])
    if e - o > maximo or n - s > maximo:
        raise DatosInvalidos({"bbox": f"La zona es muy grande (máximo {maximo:g} grados por lado)"})
    return o, s, e, n


def red_referencia(con: Any, actor: dict[str, Any], *, oeste: float, sur: float, este: float, norte: float) -> dict[str, Any]:
    """Poles, mufas and cables of the base networks inside the zone (what was created in the tool and approved from the field), light for the phone."""
    exigir_campo(actor)
    o, s, e, n = zona(oeste, sur, este, norte)
    cfg = configuracion()
    caja = {"o": o, "s": s, "e": e, "n": n}
    puntos = con.execute(
        "SELECT el.id, el.nombre, el.tipo, ST_Y(el.ubicacion) AS lat, ST_X(el.ubicacion) AS lon FROM redes.elementos el JOIN redes.proyectos p ON p.id = el.proyecto_id "
        "WHERE p.es_red_base AND p.borrado_en IS NULL AND el.borrado_en IS NULL AND el.ubicacion IS NOT NULL AND el.tipo IN ('poste', 'mufa', 'nodo', 'odf') "
        "AND el.ubicacion && ST_MakeEnvelope(%(o)s, %(s)s, %(e)s, %(n)s, 4326) LIMIT %(l)s", {**caja, "l": int(cfg["red_max_puntos"])}).fetchall()
    lineas = con.execute(
        "SELECT c.id, c.nombre, ST_AsGeoJSON(ST_SimplifyPreserveTopology(c.geom, 0.000005), 6) AS g FROM redes.cables c JOIN redes.proyectos p ON p.id = c.proyecto_id "
        "WHERE p.es_red_base AND p.borrado_en IS NULL AND c.borrado_en IS NULL AND c.geom && ST_MakeEnvelope(%(o)s, %(s)s, %(e)s, %(n)s, 4326) LIMIT %(l)s",
        {**caja, "l": int(cfg["red_max_lineas"])}).fetchall()
    return {"puntos": [{"id": f"r{f['id']}", "n": f["nombre"], "t": f["tipo"], "lat": round(float(f["lat"]), 6), "lon": round(float(f["lon"]), 6)} for f in puntos],
            "lineas": [{"id": f"c{f['id']}", "n": f["nombre"], "t": "cable", "c": [[c[1], c[0]] for c in json.loads(f["g"])["coordinates"]]} for f in lineas],
            "truncado": len(puntos) >= int(cfg["red_max_puntos"]) or len(lineas) >= int(cfg["red_max_lineas"])}
