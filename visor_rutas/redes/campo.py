"""App de campo (migración 017): jornadas, puntos y fotos que registran los técnicos desde el teléfono.

Un técnico (rol «tecnico») solo crea y edita SUS puntos mientras están pendientes; un editor o administrador ve los de todos, los corrige y (en la
fase de revisión) los aprueba o rechaza. Enviar es idempotente: el teléfono genera `uuid_cliente` de cada punto y de cada foto, así que reenviar
tras un corte no duplica. Cada cambio del esquema dispara NOTIFY 'campo' (trigger de la migración) para el visor en tiempo real.
"""
import hashlib
import io
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from visor_rutas.redes import repositorio, usuarios
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
POR_DEFECTO = {"precision_max_m": 10, "duplicado_m": 5, "foto_max_bytes": 3145728, "fotos_por_punto": 8, "puntos_por_lote": 50, "peticiones_por_hora": 1200}


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
    return {"puntos": [_publico(f) for f in filas], "ahora": ahora.isoformat(), "mas": len(filas) >= max(1, min(int(limite), LIMITE_PUNTOS))}


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
