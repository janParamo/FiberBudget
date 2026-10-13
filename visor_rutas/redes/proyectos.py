"""Proyectos del módulo de redes (fase 2): lista, datos, duplicar, eliminar / restaurar, historial.

Permisos:
  - administrador: ve y edita todos los proyectos, y restaura los eliminados;
  - editor: crea proyectos (queda asignado) y edita los que tiene asignados;
  - lector: solo ve los proyectos que tiene asignados.
Eliminar es borrado lógico (borrado_en): el proyecto se puede restaurar. Toda escritura va con
la versión leída (bloqueo optimista) y queda en redes.historial con su usuario.
"""
import base64
import binascii
import io
import json
import math
import re
from typing import Any

from visor_rutas.redes import elementos, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

MAX_IMAGEN = 2 * 1024 * 1024
LADO_MINIATURA = 160
TIPOS_IMAGEN = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
_CODIGO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,29}$")
_DATA_URL = re.compile(r"^data:image/[\w.+-]+;base64,(?P<datos>[A-Za-z0-9+/=\s]+)$")
MAX_VERTICES_AREA = 5000

_SELECT = """
SELECT p.id, p.codigo, p.nombre, p.descripcion, p.padre_id, padre.nombre AS padre_nombre,
       ST_Y(p.ubicacion) AS lat, ST_X(p.ubicacion) AS lon,
       ST_AsGeoJSON(p.area, 7) AS area, ST_NPoints(p.area) AS area_vertices,
       p.imagen IS NOT NULL AS tiene_imagen, p.miniatura, p.imagen_tipo,
       p.version, p.creado_en, p.actualizado_en, p.borrado_en, p.es_red_base, p.zona,
       (SELECT count(*) FROM redes.elementos e WHERE e.proyecto_id = p.id AND e.tipo = 'cliente'
        AND e.borrado_en IS NULL) AS n_clientes,
       creador.nombre AS creado_por, editor.nombre AS actualizado_por
FROM redes.proyectos p
LEFT JOIN redes.proyectos padre ON padre.id = p.padre_id
LEFT JOIN redes.usuarios creador ON creador.id = p.creado_por
LEFT JOIN redes.usuarios editor ON editor.id = p.actualizado_por
"""


# --------------------------------------------------------------------------- permisos

def asignado(con: Any, actor: dict[str, Any], proyecto_id: int) -> bool:
    return con.execute("SELECT 1 FROM redes.proyecto_usuarios WHERE proyecto_id = %s AND usuario_id = %s",
                       (proyecto_id, actor["id"])).fetchone() is not None


def es_red_base(con: Any, proyecto_id: int) -> bool:
    """Base projects hold the existing network migrated from the Visio: every user sees them and every
    editor edits them, without being assigned one by one."""
    f = con.execute("SELECT es_red_base FROM redes.proyectos WHERE id = %s", (proyecto_id,)).fetchone()
    return bool(f and f["es_red_base"])


def puede_ver(con: Any, actor: dict[str, Any], proyecto_id: int) -> bool:
    return usuarios.es_admin(actor) or asignado(con, actor, proyecto_id) or es_red_base(con, proyecto_id)


def puede_editar(con: Any, actor: dict[str, Any], proyecto_id: int) -> bool:
    return usuarios.es_admin(actor) or (usuarios.puede_editar(actor)
                                        and (asignado(con, actor, proyecto_id) or es_red_base(con, proyecto_id)))


def _exigir_ver(con: Any, actor: dict[str, Any], proyecto_id: int) -> None:
    if not puede_ver(con, actor, proyecto_id):
        raise SinPermiso("No tiene acceso a este proyecto")


def _exigir_editar(con: Any, actor: dict[str, Any], proyecto_id: int) -> None:
    if not puede_editar(con, actor, proyecto_id):
        raise SinPermiso("No tiene permiso para editar este proyecto")


# --------------------------------------------------------------------------- lectura

def _data_url(datos: bytes | memoryview | None, tipo: str | None) -> str | None:
    if not datos:
        return None
    return f"data:{tipo or 'image/png'};base64,{base64.b64encode(bytes(datos)).decode('ascii')}"


def _usuarios_de(con: Any, proyecto_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not proyecto_ids:
        return {}
    filas = con.execute(
        "SELECT pu.proyecto_id, u.id, u.nombre, u.rol, u.borrado_en IS NULL AS activo FROM redes.proyecto_usuarios pu "
        "JOIN redes.usuarios u ON u.id = pu.usuario_id WHERE pu.proyecto_id = ANY(%s) ORDER BY lower(u.nombre)",
        (proyecto_ids,)).fetchall()
    salida: dict[int, list[dict[str, Any]]] = {}
    for f in filas:
        salida.setdefault(f["proyecto_id"], []).append({"id": f["id"], "nombre": f["nombre"], "rol": f["rol"],
                                                        "activo": f["activo"]})
    return salida


def _publico(fila: dict[str, Any], *, completo: bool = False) -> dict[str, Any]:
    datos = {k: fila[k] for k in ("id", "codigo", "nombre", "descripcion", "padre_id", "padre_nombre", "lat", "lon",
                                  "tiene_imagen", "version", "creado_en", "actualizado_en", "creado_por",
                                  "actualizado_por", "borrado_en", "n_clientes", "es_red_base", "zona")}
    datos["eliminado"] = fila["borrado_en"] is not None
    datos["miniatura"] = _data_url(fila["miniatura"], "image/png")
    datos["area"] = json.loads(fila["area"]) if fila["area"] else None
    datos["area_vertices"] = max(0, (fila["area_vertices"] or 1) - 1) if fila["area"] else 0
    return datos


def listar(con: Any, actor: dict[str, Any], *, texto: str = "", incluir_eliminados: bool = False) -> dict[str, Any]:
    """Visible projects (tree order is done by the page with padre_id)."""
    condiciones, parametros = [], []
    if not (incluir_eliminados and usuarios.es_admin(actor)):
        condiciones.append("p.borrado_en IS NULL")
    if not usuarios.es_admin(actor):
        condiciones.append("(p.es_red_base OR EXISTS (SELECT 1 FROM redes.proyecto_usuarios pu WHERE pu.proyecto_id = p.id "
                           "AND pu.usuario_id = %s))")
        parametros.append(actor["id"])
    texto = " ".join(str(texto or "").split())
    if texto:
        condiciones.append("(lower(p.nombre) LIKE %s OR lower(p.codigo) LIKE %s OR lower(coalesce(p.descripcion, '')) LIKE %s)")
        patron = f"%{texto.lower()}%"
        parametros += [patron, patron, patron]
    consulta = _SELECT + (" WHERE " + " AND ".join(condiciones) if condiciones else "") + " ORDER BY lower(p.nombre)"
    filas = con.execute(consulta, parametros).fetchall()
    proyectos = [_publico(f) for f in filas]
    asignados = _usuarios_de(con, [p["id"] for p in proyectos])
    for p in proyectos:
        p["usuarios"] = asignados.get(p["id"], [])
        p["puede_editar"] = usuarios.es_admin(actor) or (usuarios.puede_editar(actor)
                                                         and (p["es_red_base"] or any(u["id"] == actor["id"] for u in p["usuarios"])))
    return {"proyectos": proyectos, "puede_crear": usuarios.puede_editar(actor),
            "puede_restaurar": usuarios.es_admin(actor)}


def obtener(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    fila = con.execute(_SELECT + " WHERE p.id = %s", (int(id),)).fetchone()
    if fila is None or (fila["borrado_en"] is not None and not usuarios.es_admin(actor)):
        raise NoEncontrado("El proyecto no existe o fue eliminado")
    _exigir_ver(con, actor, fila["id"])
    proyecto = _publico(fila, completo=True)
    imagen = con.execute("SELECT imagen, imagen_tipo FROM redes.proyectos WHERE id = %s", (fila["id"],)).fetchone()
    proyecto["imagen"] = _data_url(imagen["imagen"], imagen["imagen_tipo"])
    proyecto["usuarios"] = _usuarios_de(con, [fila["id"]]).get(fila["id"], [])
    proyecto["clientes"] = elementos.clientes_de(con, fila["id"])
    proyecto["puede_editar"] = puede_editar(con, actor, fila["id"])
    proyecto["hijos"] = [dict(h) for h in con.execute(
        "SELECT id, codigo, nombre FROM redes.proyectos WHERE padre_id = %s AND borrado_en IS NULL ORDER BY lower(nombre)",
        (fila["id"],)).fetchall()]
    return {"proyecto": proyecto}


def usuarios_asignables(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Active users for the "Usuarios" selector of a project."""
    filas = con.execute("SELECT id, nombre, rol FROM redes.usuarios WHERE borrado_en IS NULL ORDER BY lower(nombre)").fetchall()
    return {"usuarios": [dict(f) for f in filas]}


# --------------------------------------------------------------------------- validación

def _texto(valor: Any, maximo: int) -> str | None:
    texto = " ".join(str(valor or "").split())
    return texto[:maximo] if texto else None


def _coordenada(lat: Any, lon: Any, errores: dict[str, str]) -> str | None:
    if lat in (None, "") and lon in (None, ""):
        return None
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        errores["ubicacion"] = "Coordenada no válida"
        return None
    if not (math.isfinite(la) and math.isfinite(lo) and -90 <= la <= 90 and -180 <= lo <= 180):
        errores["ubicacion"] = "Coordenada fuera de rango"
        return None
    return f"SRID=4326;POINT({lo:.8f} {la:.8f})"


def _area(valor: Any, errores: dict[str, str]) -> str | None:
    """GeoJSON Polygon (or a Feature with one) -> EWKT; only the outer ring is kept."""
    if not valor:
        return None
    try:
        geo = json.loads(valor) if isinstance(valor, str) else dict(valor)
        if geo.get("type") == "Feature":
            geo = geo["geometry"]
        if geo.get("type") != "Polygon":
            raise ValueError
        anillo = [(float(x), float(y)) for x, y, *_ in geo["coordinates"][0]]
    except (ValueError, TypeError, KeyError, IndexError):
        errores["area"] = "Área no válida: dibuje un polígono"
        return None
    if anillo and anillo[0] != anillo[-1]:
        anillo.append(anillo[0])
    if len(anillo) < 4:
        errores["area"] = "El área necesita al menos 3 puntos"
        return None
    if len(anillo) > MAX_VERTICES_AREA:
        errores["area"] = f"El área tiene demasiados puntos (máximo {MAX_VERTICES_AREA})"
        return None
    if not all(math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90 for x, y in anillo):
        errores["area"] = "Área con coordenadas fuera de rango"
        return None
    return "SRID=4326;POLYGON((" + ", ".join(f"{x:.8f} {y:.8f}" for x, y in anillo) + "))"


def procesar_imagen(valor: Any) -> tuple[bytes, str, bytes] | None:
    """data:image/...;base64 -> (bytes, mime, PNG thumbnail). DatosInvalidos if it is not a real
    PNG / JPEG / WEBP / GIF image of at most 2 MB (SVG is not accepted)."""
    m = _DATA_URL.match(str(valor or "").strip())
    if not m:
        raise DatosInvalidos({"imagen": "Formato no válido: use PNG, JPG, WEBP o GIF"})
    try:
        datos = base64.b64decode(re.sub(r"\s", "", m.group("datos")), validate=True)
    except (binascii.Error, ValueError):
        raise DatosInvalidos({"imagen": "La imagen está dañada"}) from None
    if len(datos) > MAX_IMAGEN:
        raise DatosInvalidos({"imagen": f"La imagen pesa {len(datos) / 1048576:.1f} MB: el máximo es 2 MB"})
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            formato = imagen.format
            imagen.verify()
        if formato not in TIPOS_IMAGEN:
            raise DatosInvalidos({"imagen": "Formato no válido: use PNG, JPG, WEBP o GIF"})
        with Image.open(io.BytesIO(datos)) as imagen:
            imagen.seek(0)
            mini = imagen.convert("RGBA")
            mini.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
            salida = io.BytesIO()
            mini.save(salida, "PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise DatosInvalidos({"imagen": "El archivo no es una imagen válida"}) from None
    return datos, TIPOS_IMAGEN[formato], salida.getvalue()


def _validar(con: Any, datos: dict[str, Any], id_: int | None) -> dict[str, Any]:
    errores: dict[str, str] = {}
    valores: dict[str, Any] = {"nombre": _texto(datos.get("nombre"), 160), "codigo": _texto(datos.get("codigo"), 30),
                               "descripcion": (str(datos.get("descripcion") or "").strip()[:4000] or None)}
    if not valores["nombre"]:
        errores["nombre"] = "Campo obligatorio"
    if not valores["codigo"]:
        errores["codigo"] = "Campo obligatorio"
    elif not _CODIGO.match(valores["codigo"]):
        errores["codigo"] = "Solo letras, números, punto, guion y guion bajo (máximo 30, sin espacios)"
    elif con.execute("SELECT 1 FROM redes.proyectos WHERE lower(codigo) = lower(%s) AND borrado_en IS NULL "
                     "AND id IS DISTINCT FROM %s", (valores["codigo"], id_)).fetchone():
        errores["codigo"] = "Ya hay un proyecto con ese identificador"
    padre = datos.get("padre_id")
    valores["padre_id"] = int(padre) if padre not in (None, "", 0, "0") else None
    if valores["padre_id"] is not None:
        if valores["padre_id"] == id_:
            errores["padre_id"] = "Un proyecto no puede ser su propio proyecto principal"
        elif con.execute("SELECT 1 FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL",
                         (valores["padre_id"],)).fetchone() is None:
            errores["padre_id"] = "El proyecto principal no existe"
        elif id_ is not None and _es_descendiente(con, valores["padre_id"], id_):
            errores["padre_id"] = "No puede elegir un subproyecto de este proyecto como principal"
    valores["ubicacion"] = _coordenada(datos.get("lat"), datos.get("lon"), errores)
    valores["area"] = _area(datos.get("area"), errores)
    if valores["area"] and "area" not in errores:
        valido = con.execute("SELECT ST_IsValid(%s::geometry) AS ok, ST_IsValidReason(%s::geometry) AS motivo",
                             (valores["area"], valores["area"])).fetchone()
        if not valido["ok"]:
            errores["area"] = "El área se cruza consigo misma: vuelva a dibujarla"
    usuarios_ids = datos.get("usuarios")
    if usuarios_ids is not None:
        try:
            # ids, or the user objects of a project read before ({"id": ..., "nombre": ...})
            valores["usuarios"] = sorted({int(u["id"] if isinstance(u, dict) else u) for u in usuarios_ids})
        except (TypeError, ValueError, KeyError):
            errores["usuarios"] = "Usuarios no válidos"
        else:
            activos = {f["id"] for f in con.execute(
                "SELECT id FROM redes.usuarios WHERE id = ANY(%s) AND borrado_en IS NULL", (valores["usuarios"],)).fetchall()}
            if set(valores["usuarios"]) - activos:
                errores["usuarios"] = "Algún usuario no existe o está desactivado"
    if datos.get("clientes") is not None:                   # absent: keep the current clients
        try:
            valores["clientes"] = elementos.validar_clientes(datos["clientes"])
        except DatosInvalidos as exc:
            errores.update(exc.errores)
    if "imagen" in datos:                                   # absent: keep the current image
        if datos["imagen"]:
            try:
                valores["imagen"], valores["imagen_tipo"], valores["miniatura"] = procesar_imagen(datos["imagen"])
            except DatosInvalidos as exc:
                errores.update(exc.errores)
        else:
            valores["imagen"] = valores["imagen_tipo"] = valores["miniatura"] = None
    if errores:
        raise DatosInvalidos(errores)
    return valores


def _es_descendiente(con: Any, candidato: int, proyecto: int) -> bool:
    """True if `candidato` is `proyecto` or one of its subprojects (it would create a cycle)."""
    fila = con.execute("""
        WITH RECURSIVE sub(id) AS (
            SELECT id FROM redes.proyectos WHERE id = %s
            UNION SELECT p.id FROM redes.proyectos p JOIN sub ON p.padre_id = sub.id)
        SELECT 1 FROM sub WHERE id = %s""", (proyecto, candidato)).fetchone()
    return fila is not None


# --------------------------------------------------------------------------- auditoría

def _legible(con: Any, id_: int) -> dict[str, Any]:
    """Audited view of a project: readable values (never raw geometry or image bytes)."""
    f = con.execute(
        "SELECT codigo, nombre, descripcion, padre_id, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, "
        "ST_NPoints(area) AS area, octet_length(imagen) AS imagen, borrado_en FROM redes.proyectos WHERE id = %s",
        (id_,)).fetchone()
    datos = dict(f)
    datos["lat"] = round(datos["lat"], 6) if datos["lat"] is not None else None
    datos["lon"] = round(datos["lon"], 6) if datos["lon"] is not None else None
    datos["area"] = f"polígono de {datos['area'] - 1} puntos" if datos["area"] else None
    datos["imagen"] = f"{datos['imagen'] / 1024:.0f} KB" if datos["imagen"] else None
    datos["usuarios"] = ", ".join(u["nombre"] for u in _usuarios_de(con, [id_]).get(id_, [])) or None
    datos["clientes"] = elementos.resumen_clientes(con, id_)
    return datos


def _asignar_usuarios(con: Any, proyecto_id: int, ids: list[int], actor_id: int) -> None:
    con.execute("DELETE FROM redes.proyecto_usuarios WHERE proyecto_id = %s AND NOT (usuario_id = ANY(%s))",
                (proyecto_id, ids))
    for uid in ids:
        con.execute("INSERT INTO redes.proyecto_usuarios (proyecto_id, usuario_id, asignado_por) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING", (proyecto_id, uid, actor_id))


# --------------------------------------------------------------------------- escritura

def guardar(con: Any, actor: dict[str, Any], *, datos: dict[str, Any]) -> dict[str, Any]:
    """Creates (no id) or edits (id + version) a project."""
    datos = dict(datos or {})
    id_ = int(datos["id"]) if datos.get("id") else None
    if id_ is None and not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede crear proyectos")
    with con.transaction():
        if id_ is not None:
            repositorio.obtener(con, "proyectos", id_, bloquear=True)
            _exigir_editar(con, actor, id_)
        valores = _validar(con, datos, id_)
        ids_usuarios = valores.pop("usuarios", None)
        clientes = valores.pop("clientes", None)
        if id_ is None:
            fila = repositorio.insertar(con, "proyectos", valores, actor["id"])
            id_ = fila["id"]
            # The creator always has access to what he created (and can give it to others later).
            _asignar_usuarios(con, id_, sorted(set(ids_usuarios or []) | {actor["id"]}), actor["id"])
            if clientes:
                elementos.sincronizar_clientes(con, id_, clientes, actor["id"])
            repositorio.registrar(con, actor["id"], "proyecto", id_, "crear",
                                  repositorio.diferencias(None, _legible(con, id_)), proyecto_id=id_)
        else:
            antes = _legible(con, id_)
            repositorio.actualizar(con, "proyectos", id_, int(datos.get("version") or 0), valores, actor["id"])
            if ids_usuarios is not None:
                if not usuarios.es_admin(actor) and actor["id"] not in ids_usuarios:
                    raise DatosInvalidos({"usuarios": "No puede quitarse a sí mismo del proyecto"})
                _asignar_usuarios(con, id_, ids_usuarios, actor["id"])
            if clientes is not None:
                elementos.sincronizar_clientes(con, id_, clientes, actor["id"])
            cambio = repositorio.diferencias(antes, _legible(con, id_))
            repositorio.registrar(con, actor["id"], "proyecto", id_, "editar", cambio, proyecto_id=id_)
    return obtener(con, actor, id=id_)


def _codigo_libre(con: Any, base: str) -> str:
    base = base[:23]
    for n in range(1, 1000):
        codigo = f"{base}-COPIA" + ("" if n == 1 else f"{n}")
        if not con.execute("SELECT 1 FROM redes.proyectos WHERE lower(codigo) = lower(%s) AND borrado_en IS NULL",
                           (codigo,)).fetchone():
            return codigo
    raise DatosInvalidos({"codigo": "No se encontró un identificador libre para la copia"})


def duplicar(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Copy of the project (name "(copia)", code "-COPIA"): its data, users and network
    (elements, cables and notes)."""
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede duplicar proyectos")
    with con.transaction():
        original = con.execute("SELECT * FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL", (int(id),)).fetchone()
        if original is None:
            raise NoEncontrado("El proyecto no existe o fue eliminado")
        _exigir_ver(con, actor, original["id"])
        valores = {k: original[k] for k in ("descripcion", "padre_id", "ubicacion", "area", "imagen", "imagen_tipo", "miniatura")}
        valores["codigo"] = _codigo_libre(con, original["codigo"])
        valores["nombre"] = f"{original['nombre']} (copia)"[:160]
        fila = repositorio.insertar(con, "proyectos", valores, actor["id"])
        ids = [u["id"] for u in _usuarios_de(con, [original["id"]]).get(original["id"], [])]
        _asignar_usuarios(con, fila["id"], sorted(set(ids) | {actor["id"]}), actor["id"])
        from visor_rutas.redes import red                  # red imports this module
        red.copiar(con, original["id"], fila["id"], actor["id"])
        repositorio.registrar(con, actor["id"], "proyecto", fila["id"], "duplicar",
                              {"origen": [None, f"{original['codigo']} (id {original['id']})"]}, proyecto_id=fila["id"])
    return obtener(con, actor, id=fila["id"])


def eliminar(con: Any, actor: dict[str, Any], *, id: int, version: int) -> dict[str, Any]:
    """Logical delete (it can be restored). Refused while it has active subprojects."""
    with con.transaction():
        actual = repositorio.obtener(con, "proyectos", int(id), bloquear=True)
        _exigir_editar(con, actor, actual["id"])
        if actual["borrado_en"] is not None:
            raise NoEncontrado("El proyecto ya estaba eliminado")
        hijos = con.execute("SELECT nombre FROM redes.proyectos WHERE padre_id = %s AND borrado_en IS NULL "
                            "ORDER BY lower(nombre)", (actual["id"],)).fetchall()
        if hijos:
            raise DatosInvalidos({"proyecto": "Tiene subproyectos: elimínelos o cámbielos de proyecto principal primero ("
                                  + ", ".join(h["nombre"] for h in hijos[:5]) + ("…" if len(hijos) > 5 else "") + ")"})
        ahora = con.execute("SELECT now() AS n").fetchone()["n"]
        repositorio.actualizar(con, "proyectos", actual["id"], int(version), {"borrado_en": ahora}, actor["id"])
        repositorio.registrar(con, actor["id"], "proyecto", actual["id"], "eliminar",
                              {"borrado_en": [None, ahora.isoformat()]}, proyecto_id=actual["id"])
    return {"eliminado": actual["id"]}


def restaurar(con: Any, actor: dict[str, Any], *, id: int, version: int) -> dict[str, Any]:
    """Undo a delete (administrators). Its code must still be free."""
    usuarios.exigir_admin(actor)
    with con.transaction():
        actual = repositorio.obtener(con, "proyectos", int(id), bloquear=True)
        if actual["borrado_en"] is None:
            return obtener(con, actor, id=actual["id"])
        if con.execute("SELECT 1 FROM redes.proyectos WHERE lower(codigo) = lower(%s) AND borrado_en IS NULL",
                       (actual["codigo"],)).fetchone():
            raise DatosInvalidos({"codigo": f"Ya hay otro proyecto activo con el identificador {actual['codigo']}: "
                                            "cámbielo en ese proyecto antes de restaurar este"})
        if actual["padre_id"] and con.execute("SELECT 1 FROM redes.proyectos WHERE id = %s AND borrado_en IS NOT NULL",
                                              (actual["padre_id"],)).fetchone():
            raise DatosInvalidos({"padre_id": "Su proyecto principal está eliminado: restáurelo primero"})
        repositorio.actualizar(con, "proyectos", actual["id"], int(version), {"borrado_en": None}, actor["id"])
        repositorio.registrar(con, actor["id"], "proyecto", actual["id"], "restaurar",
                              {"borrado_en": [actual["borrado_en"].isoformat(), None]}, proyecto_id=actual["id"])
    return obtener(con, actor, id=actual["id"])


def historial(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Who changed what and when, for this project (and, from phase 3, its contents)."""
    fila = con.execute("SELECT id, borrado_en FROM redes.proyectos WHERE id = %s", (int(id),)).fetchone()
    if fila is None or (fila["borrado_en"] is not None and not usuarios.es_admin(actor)):
        raise NoEncontrado("El proyecto no existe")
    _exigir_ver(con, actor, fila["id"])
    filas = con.execute(
        "SELECT h.fecha, h.accion, h.entidad, h.cambio, u.nombre AS usuario FROM redes.historial h "
        "LEFT JOIN redes.usuarios u ON u.id = h.usuario_id WHERE h.proyecto_id = %s "
        "ORDER BY h.fecha DESC, h.id DESC LIMIT 500", (fila["id"],)).fetchall()
    return {"historial": [{**f, "fecha": f["fecha"].isoformat()} for f in filas]}


# --------------------------------------------------------------------------- dirección

def geocodificar(con: Any, actor: dict[str, Any], *, texto: str) -> dict[str, Any]:
    """Address search for the project location (Google Geocoding, the .env key; Nicaragua first)."""
    texto = " ".join(str(texto or "").split())[:200]
    if len(texto) < 3:
        raise DatosInvalidos({"direccion": "Escriba al menos 3 letras"})
    import requests

    from config import get_settings
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                         params={"address": texto, "region": "ni", "language": "es", "key": get_settings().google_api_key},
                         timeout=10)
        datos = r.json()
    except (requests.RequestException, ValueError):
        raise DatosInvalidos({"direccion": "No se pudo consultar Google (¿sin internet?). Puede pegar la coordenada."}) from None
    estado = datos.get("status")
    if estado == "ZERO_RESULTS":
        return {"resultados": []}
    if estado != "OK":
        detalle = {"REQUEST_DENIED": "la clave de Google no tiene habilitada la Geocoding API",
                   "OVER_QUERY_LIMIT": "límite de consultas de Google alcanzado"}.get(estado, estado)
        raise DatosInvalidos({"direccion": f"Google no respondió la búsqueda ({detalle}). Puede pegar la coordenada."})
    return {"resultados": [{"direccion": x.get("formatted_address"), "lat": x["geometry"]["location"]["lat"],
                            "lon": x["geometry"]["location"]["lng"]} for x in datos.get("results", [])[:5]]}
