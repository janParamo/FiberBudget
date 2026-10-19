"""Mis lugares (visor v2, fase 3): carpetas y elementos propios de cada usuario, como en Google Earth.

- `arbol`: las carpetas del usuario y las que le compartieron, con sus elementos (geometría y estilo; sin la descripción).
- `guardar_carpeta`, `mover`, `visibilidad`, `eliminar_carpeta`: el árbol (crear, renombrar, mover y ordenar a mano, casillas, borrar).
- `guardar_lugar`, `obtener`, `eliminar_lugar`, `adjunto`: marca de posición, ruta, polígono (y, en la fase 4, mufa, poste, cliente,
  nodo, odf y cable): geometría, nombre, descripción con formato e imágenes, estilo, vista guardada y propiedades.
- `compartidos`, `compartir`: compartir una carpeta (con sus subcarpetas) en solo lectura o con edición.
Lo exportable a KMZ / lo importable de KMZ está en lugares_kmz.py. Todo es personal: no toca proyectos ni la red.

Permisos: el dueño puede todo; quien tiene una carpeta compartida (o una de sus carpetas madre) la lee y, si se le dio edición, la
edita; las casillas de visibilidad se guardan solo en carpetas propias. Cualquier usuario activo del módulo puede tener lugares
propios (incluso un lector: no es la red). Lo creado dentro de una carpeta compartida es del dueño de la carpeta.
"""
import base64
import json
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import lugares_iconos, lugares_red, repositorio, texto
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

PUNTUALES = ("marca", "mufa", "poste", "cliente", "nodo", "odf")
LINEALES = ("ruta", "cable")
AREALES = ("poligono",)
TIPOS = PUNTUALES + LINEALES + AREALES
MAX_VERTICES = 20_000
MAX_NOMBRE = 160
MAX_ADJUNTO = 2 * 1024 * 1024
MAX_ADJUNTOS = 30
MAX_PROPIEDADES = 20_000                  # characters of the properties JSON
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_IMG_NUEVA = re.compile(r"<img\b[^>]*?\bdata-nuevo=\"([A-Za-z0-9_-]{1,40})\"[^>]*>", re.I)
_IMG_ADJ = re.compile(r"<img\b[^>]*?\bdata-adj=\"(\d{1,12})\"[^>]*>", re.I)
_MARCA_IMG = re.compile(r"\[\[IMG:(nuevo|adj):([A-Za-z0-9_-]{1,40})\]\]")
_IMAGENES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF87a": "image/gif", b"GIF89a": "image/gif"}


def _texto(valor: Any, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _tipo_imagen(datos: bytes) -> str | None:
    for cabecera, tipo in _IMAGENES.items():
        if datos.startswith(cabecera):
            return tipo
    return "image/webp" if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP" else None


# --------------------------------------------------------------------------- permisos

def _acceso(con: Any, actor: dict[str, Any], carpeta_id: int) -> dict[str, Any] | None:
    """{"dueno": bool, "edita": bool} of the actor over a folder, or None if it does not exist / is not visible to them."""
    c = con.execute("SELECT id, usuario_id FROM redes.lugares_carpetas WHERE id = %s AND borrado_en IS NULL", (int(carpeta_id),)).fetchone()
    if c is None:
        return None
    if c["usuario_id"] == actor["id"]:
        return {"dueno": True, "edita": True, "dueno_id": c["usuario_id"]}
    f = con.execute(
        "WITH RECURSIVE arriba AS (SELECT id, padre_id FROM redes.lugares_carpetas WHERE id = %(c)s AND borrado_en IS NULL "
        "UNION ALL SELECT p.id, p.padre_id FROM redes.lugares_carpetas p JOIN arriba a ON p.id = a.padre_id WHERE p.borrado_en IS NULL) "
        "SELECT bool_or(s.puede_editar) AS edita, count(*) AS n FROM arriba a JOIN redes.lugares_compartidas s "
        "ON s.carpeta_id = a.id AND s.usuario_id = %(u)s", {"c": int(carpeta_id), "u": actor["id"]}).fetchone()
    if not f["n"]:
        return None
    return {"dueno": False, "edita": bool(f["edita"]), "dueno_id": c["usuario_id"]}


def _exigir(con: Any, actor: dict[str, Any], carpeta_id: int, *, editar: bool = False, dueno: bool = False) -> dict[str, Any]:
    a = _acceso(con, actor, carpeta_id)
    if a is None:
        raise NoEncontrado("La carpeta no existe, fue eliminada o no se compartió con usted")
    if dueno and not a["dueno"]:
        raise SinPermiso("Solo el dueño de la carpeta puede hacer esto")
    if editar and not a["edita"]:
        raise SinPermiso("La carpeta se compartió solo para lectura")
    return a


def _del_elemento(con: Any, actor: dict[str, Any], elemento_id: int, *, editar: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    e = con.execute("SELECT * FROM redes.lugares_elementos WHERE id = %s AND borrado_en IS NULL", (int(elemento_id),)).fetchone()
    if e is None:
        raise NoEncontrado("El lugar ya no existe")
    return dict(e), _exigir(con, actor, e["carpeta_id"], editar=editar)


# --------------------------------------------------------------------------- geometría y estilo

def _par(p: Any) -> str:
    try:
        x, y = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        raise DatosInvalidos({"geometria": "Coordenada no válida"}) from None
    if not (-180 <= x <= 180 and -90 <= y <= 90):
        raise DatosInvalidos({"geometria": f"Coordenada fuera del mundo: {y}, {x}"})
    return f"{x:.8f} {y:.8f}"


def a_ewkt(tipo: str, geo: Any) -> str:
    """GeoJSON (Point / LineString / Polygon of the type) -> EWKT for PostGIS."""
    if not isinstance(geo, dict):
        raise DatosInvalidos({"geometria": "Falta la geometría"})
    tg, c = geo.get("type"), geo.get("coordinates")
    if tipo in PUNTUALES:
        if tg != "Point":
            raise DatosInvalidos({"geometria": "Una marca es un punto"})
        return f"SRID=4326;POINT({_par(c)})"
    if tipo in LINEALES:
        if tg != "LineString" or not isinstance(c, list) or len(c) < 2:
            raise DatosInvalidos({"geometria": "Una ruta necesita al menos dos puntos"})
        if len(c) > MAX_VERTICES:
            raise DatosInvalidos({"geometria": f"Demasiados puntos (máximo {MAX_VERTICES})"})
        return "SRID=4326;LINESTRING(" + ", ".join(_par(p) for p in c) + ")"
    if tg != "Polygon" or not isinstance(c, list) or not c or not isinstance(c[0], list):
        raise DatosInvalidos({"geometria": "Un polígono necesita su contorno"})
    anillo = [_par(p) for p in c[0]]
    if len(anillo) > 1 and anillo[0] == anillo[-1]:
        anillo = anillo[:-1]
    if len(anillo) < 3:
        raise DatosInvalidos({"geometria": "Un polígono necesita al menos tres puntos"})
    if len(anillo) > MAX_VERTICES:
        raise DatosInvalidos({"geometria": f"Demasiados puntos (máximo {MAX_VERTICES})"})
    return "SRID=4326;POLYGON((" + ", ".join(anillo + [anillo[0]]) + "))"


def _color(valor: Any, defecto: str | None = None) -> str | None:
    return str(valor) if isinstance(valor, str) and _COLOR.match(valor) else defecto


def _numero(valor: Any, minimo: float, maximo: float, defecto: float) -> float:
    try:
        return round(min(maximo, max(minimo, float(valor))), 2)
    except (TypeError, ValueError):
        return defecto


def limpiar_estilo(valor: Any) -> dict[str, Any]:
    """Only the style keys that exist, each in its range."""
    if not isinstance(valor, dict):
        return {}
    salida: dict[str, Any] = {}
    icono = lugares_iconos.limpiar_icono(valor.get("icono"))
    if icono:
        salida["icono"] = icono
    et = valor.get("etiqueta")
    if isinstance(et, dict):
        salida["etiqueta"] = {"visible": bool(et.get("visible", True)), "color": _color(et.get("color"), "#ffffff"),
                              "escala": _numero(et.get("escala"), 0.3, 4, 1.0)}
    li = valor.get("linea")
    if isinstance(li, dict):
        salida["linea"] = {"color": _color(li.get("color"), "#ffe600"), "grosor": _numero(li.get("grosor"), 1, 20, 3),
                           "opacidad": _numero(li.get("opacidad"), 0, 1, 1)}
    re_ = valor.get("relleno")
    if isinstance(re_, dict):
        salida["relleno"] = {"activo": bool(re_.get("activo", True)), "color": _color(re_.get("color"), "#ffe600"),
                             "opacidad": _numero(re_.get("opacidad"), 0, 1, 0.3)}
    return salida


def limpiar_vista(valor: Any) -> dict[str, Any] | None:
    if not isinstance(valor, dict):
        return None
    try:
        lat, lon, zoom = float(valor["lat"]), float(valor["lon"]), float(valor.get("zoom", 17))
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": round(lat, 7), "lon": round(lon, 7), "zoom": round(min(21, max(1, zoom)), 1)}


def _red(con: Any, tipo: str, geom: Any, props: dict[str, Any], est: dict[str, Any], dueno_id: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """(EWKT, propiedades, estilo) of a network element: its own data in order, a cable's ends snapped and its metraje, the icon of its type."""
    if tipo == "cable":
        if not isinstance(geom, dict) or geom.get("type") != "LineString" or len(geom.get("coordinates") or []) < 2:
            raise DatosInvalidos({"geometria": "Un cable necesita al menos dos puntos"})
        a_ewkt(tipo, geom)                                           # validates the coordinates
        props, coords = lugares_red.limpiar_cable(con, props, dueno_id, geom["coordinates"])
        geom = {"type": "LineString", "coordinates": coords}
    else:
        props = lugares_red.limpiar_puntual(tipo, props)
    return a_ewkt(tipo, geom), props, lugares_red.estilo(tipo, props, est)


def _propiedades(valor: Any) -> dict[str, Any]:
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise DatosInvalidos({"propiedades": "Propiedades no válidas"})
    import json
    if len(json.dumps(valor, ensure_ascii=False, default=str)) > MAX_PROPIEDADES:
        raise DatosInvalidos({"propiedades": "Demasiadas propiedades"})
    return valor


# --------------------------------------------------------------------------- lectura

_CAMPOS_ELEMENTO = ("e.id, e.carpeta_id, e.tipo, e.nombre, e.orden, e.visible, e.estilo, e.vista, e.propiedades, e.version, "
                    "ST_AsGeoJSON(e.geom, 7) AS geom")


def _elemento_publico(f: Any, *, completo: bool = False) -> dict[str, Any]:
    import json
    d = {"id": f["id"], "carpeta_id": f["carpeta_id"], "tipo": f["tipo"], "nombre": f["nombre"], "orden": f["orden"], "visible": f["visible"],
         "estilo": f["estilo"] or {}, "vista": f["vista"], "propiedades": f["propiedades"] or {}, "version": f["version"],
         "geom": json.loads(f["geom"])}
    if completo:
        d["descripcion_html"] = f["descripcion_html"] or ""
    return d


def arbol(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Own folders + the ones shared with the actor (with their subfolders), and their elements."""
    carpetas: dict[int, dict[str, Any]] = {}
    for f in con.execute(
            "SELECT c.id, c.padre_id, c.nombre, c.orden, c.visible, c.expandida, c.version, c.usuario_id, u.nombre AS dueno FROM redes.lugares_carpetas c "
            "JOIN redes.usuarios u ON u.id = c.usuario_id WHERE c.usuario_id = %s AND c.borrado_en IS NULL", (actor["id"],)).fetchall():
        carpetas[f["id"]] = {**dict(f), "propia": True, "puede_editar": True}
    for f in con.execute(
            "WITH RECURSIVE comp AS (SELECT c.id, s.puede_editar FROM redes.lugares_carpetas c JOIN redes.lugares_compartidas s "
            "ON s.carpeta_id = c.id AND s.usuario_id = %(u)s WHERE c.borrado_en IS NULL AND c.usuario_id <> %(u)s "
            "UNION SELECT h.id, p.puede_editar FROM redes.lugares_carpetas h JOIN comp p ON h.padre_id = p.id WHERE h.borrado_en IS NULL) "
            "SELECT c.id, c.padre_id, c.nombre, c.orden, c.visible, c.expandida, c.version, c.usuario_id, u.nombre AS dueno, bool_or(comp.puede_editar) AS puede_editar "
            "FROM comp JOIN redes.lugares_carpetas c ON c.id = comp.id JOIN redes.usuarios u ON u.id = c.usuario_id "
            "GROUP BY c.id, u.nombre", {"u": actor["id"]}).fetchall():
        carpetas[f["id"]] = {**dict(f), "propia": False, "puede_editar": bool(f["puede_editar"])}
    for c in carpetas.values():                         # a shared folder is a root for the one who receives it
        c["raiz_compartida"] = (not c["propia"]) and c["padre_id"] not in carpetas
        if c["raiz_compartida"]:
            c["padre_id"] = None
    elementos = [_elemento_publico(f) for f in con.execute(
        f"SELECT {_CAMPOS_ELEMENTO} FROM redes.lugares_elementos e WHERE e.carpeta_id = ANY(%s) AND e.borrado_en IS NULL "
        "ORDER BY e.carpeta_id, e.orden, e.id", (list(carpetas),)).fetchall()] if carpetas else []
    return {"carpetas": sorted(carpetas.values(), key=lambda c: (c["orden"], c["id"])), "elementos": elementos}


def obtener(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    e = con.execute(f"SELECT {_CAMPOS_ELEMENTO}, e.descripcion_html FROM redes.lugares_elementos e WHERE e.id = %s AND e.borrado_en IS NULL",
                    (int(id),)).fetchone()
    if e is None:
        raise NoEncontrado("El lugar ya no existe")
    a = _exigir(con, actor, e["carpeta_id"])
    adjuntos = [dict(f) for f in con.execute("SELECT id, nombre, tipo FROM redes.lugares_adjuntos WHERE elemento_id = %s AND borrado_en IS NULL ORDER BY id",
                                             (e["id"],)).fetchall()]
    return {"lugar": {**_elemento_publico(e, completo=True), "adjuntos": adjuntos, "puede_editar": a["edita"]}}


def adjunto(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    f = con.execute("SELECT a.id, a.nombre, a.tipo, a.datos, a.elemento_id FROM redes.lugares_adjuntos a WHERE a.id = %s AND a.borrado_en IS NULL",
                    (int(id),)).fetchone()
    if f is None:
        raise NoEncontrado("La imagen ya no existe")
    _del_elemento(con, actor, f["elemento_id"])
    return {"adjunto": {"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"], "datos": base64.b64encode(bytes(f["datos"])).decode("ascii")}}


# --------------------------------------------------------------------------- carpetas

def _siguiente_orden(con: Any, carpeta_id: int | None, usuario_id: int) -> int:
    f = con.execute(
        "SELECT greatest(coalesce((SELECT max(orden) FROM redes.lugares_carpetas WHERE padre_id IS NOT DISTINCT FROM %(c)s::bigint AND borrado_en IS NULL "
        "AND (%(c)s::bigint IS NOT NULL OR usuario_id = %(u)s)), 0), coalesce((SELECT max(orden) FROM redes.lugares_elementos WHERE carpeta_id = %(c)s::bigint "
        "AND borrado_en IS NULL), 0)) AS m", {"c": carpeta_id, "u": usuario_id}).fetchone()
    return int(f["m"]) + 10


def guardar_carpeta(con: Any, actor: dict[str, Any], *, id: int | None = None, nombre: str | None = None, padre_id: int | None = None,
                    expandida: bool | None = None, version: int | None = None) -> dict[str, Any]:
    """Create (nombre + padre_id, or a root folder) or rename / open-close an existing one (id + version)."""
    with con.transaction():
        if id is None:
            limpio = _texto(nombre, MAX_NOMBRE)
            if not limpio:
                raise DatosInvalidos({"nombre": "Escriba el nombre de la carpeta"})
            dueno = actor["id"]
            if padre_id is not None:
                dueno = _exigir(con, actor, padre_id, editar=True)["dueno_id"]
            fila = repositorio.insertar(con, "lugares_carpetas", {"usuario_id": dueno, "padre_id": padre_id, "nombre": limpio,
                                                                   "orden": _siguiente_orden(con, padre_id, dueno)}, actor["id"])
            repositorio.registrar(con, actor["id"], "lugar_carpeta", fila["id"], "crear", {"nombre": [None, limpio]})
        else:
            a = _exigir(con, actor, id, editar=True)
            cambios: dict[str, Any] = {}
            if nombre is not None:
                limpio = _texto(nombre, MAX_NOMBRE)
                if not limpio:
                    raise DatosInvalidos({"nombre": "Escriba el nombre de la carpeta"})
                cambios["nombre"] = limpio
            if expandida is not None and a["dueno"]:
                cambios["expandida"] = bool(expandida)
            if not cambios:
                return arbol(con, actor) | {"id": int(id)}
            try:
                antes, despues = repositorio.actualizar(con, "lugares_carpetas", int(id), int(version or 0), cambios, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("La carpeta cambió mientras la editaba. Recargue Mis lugares.") from None
            dif = repositorio.diferencias(antes, despues)
            if dif and set(dif) - {"expandida"}:
                repositorio.registrar(con, actor["id"], "lugar_carpeta", int(id), "editar", dif)
            fila = despues
    return arbol(con, actor) | {"id": fila["id"]}


def _descendientes(con: Any, carpeta_ids: list[int]) -> tuple[list[int], list[int]]:
    """(folders, elements) inside the folders, including the folders themselves."""
    carpetas = [f["id"] for f in con.execute(
        "WITH RECURSIVE d AS (SELECT id FROM redes.lugares_carpetas WHERE id = ANY(%s) AND borrado_en IS NULL "
        "UNION SELECT c.id FROM redes.lugares_carpetas c JOIN d ON c.padre_id = d.id WHERE c.borrado_en IS NULL) SELECT id FROM d", (carpeta_ids,)).fetchall()]
    elementos = [f["id"] for f in con.execute("SELECT id FROM redes.lugares_elementos WHERE carpeta_id = ANY(%s) AND borrado_en IS NULL", (carpetas,)).fetchall()]
    return carpetas, elementos


def eliminar_carpeta(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Logical delete of the folder with its subfolders and elements (the caller already asked for a confirmation)."""
    with con.transaction():
        a = _exigir(con, actor, id, editar=True)
        c = con.execute("SELECT padre_id FROM redes.lugares_carpetas WHERE id = %s", (int(id),)).fetchone()
        if not a["dueno"] and c["padre_id"] is None:
            raise SinPermiso("Solo el dueño puede eliminar una carpeta compartida")
        carpetas, elementos = _descendientes(con, [int(id)])
        con.execute("UPDATE redes.lugares_elementos SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = ANY(%s)", (actor["id"], elementos))
        con.execute("UPDATE redes.lugares_adjuntos SET borrado_en = now() WHERE elemento_id = ANY(%s) AND borrado_en IS NULL", (elementos,))
        con.execute("UPDATE redes.lugares_carpetas SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = ANY(%s)", (actor["id"], carpetas))
        repositorio.registrar(con, actor["id"], "lugar_carpeta", int(id), "eliminar", {"carpetas": len(carpetas), "elementos": len(elementos)})
    return arbol(con, actor)


# --------------------------------------------------------------------------- mover y ordenar

def _hermanos(con: Any, carpeta_id: int | None, usuario_id: int) -> list[tuple[str, int]]:
    """Children of a folder (or the root of a user) in their manual order: [("carpeta", id), ("lugar", id)]."""
    hijos = [(f["orden"], 0, f["id"], "carpeta") for f in con.execute(
        "SELECT id, orden FROM redes.lugares_carpetas WHERE padre_id IS NOT DISTINCT FROM %s::bigint AND borrado_en IS NULL AND (%s::bigint IS NOT NULL OR usuario_id = %s)",
        (carpeta_id, carpeta_id, usuario_id)).fetchall()]
    if carpeta_id is not None:
        hijos += [(f["orden"], 1, f["id"], "lugar") for f in con.execute(
            "SELECT id, orden FROM redes.lugares_elementos WHERE carpeta_id = %s AND borrado_en IS NULL", (carpeta_id,)).fetchall()]
    return [(t, i) for _, _, i, t in sorted(hijos)]


def mover(con: Any, actor: dict[str, Any], *, items: list[dict[str, Any]], destino_id: int | None,
          antes_de: dict[str, Any] | None = None) -> dict[str, Any]:
    """Moves folders / elements ([{"tipo": "carpeta" | "lugar", "id": n}]) into a folder (None = root of the actor's own folders),
    before `antes_de` ({"tipo", "id"}) or at the end. Also used to reorder inside the same folder."""
    if not isinstance(items, list) or not items:
        raise DatosInvalidos({"items": "Nada que mover"})
    with con.transaction():
        if destino_id is None:
            dueno = actor["id"]
            if any(i.get("tipo") == "lugar" for i in items):
                raise DatosInvalidos({"destino": "Un lugar va dentro de una carpeta"})
        else:
            dueno = _exigir(con, actor, destino_id, editar=True)["dueno_id"]
        movidos: list[tuple[str, int]] = []
        for it in items:
            tipo, ident = it.get("tipo"), int(it.get("id") or 0)
            if tipo == "carpeta":
                a = _exigir(con, actor, ident, editar=True)
                f = con.execute("SELECT usuario_id, padre_id FROM redes.lugares_carpetas WHERE id = %s", (ident,)).fetchone()
                if a["dueno_id"] != dueno:
                    raise DatosInvalidos({"destino": "No se puede mover una carpeta a los lugares de otra persona"})
                if destino_id is not None and destino_id in _descendientes(con, [ident])[0]:
                    raise DatosInvalidos({"destino": "Una carpeta no puede ir dentro de sí misma"})
                if f["padre_id"] is None and not a["dueno"]:
                    raise SinPermiso("Solo el dueño mueve una carpeta compartida")
                movidos.append(("carpeta", ident))
            elif tipo == "lugar":
                e, a = _del_elemento(con, actor, ident, editar=True)
                if a["dueno_id"] != dueno:
                    raise DatosInvalidos({"destino": "No se puede mover un lugar a la carpeta de otra persona"})
                movidos.append(("lugar", ident))
            else:
                raise DatosInvalidos({"items": "Tipo no válido"})
        for tipo, ident in movidos:                          # the new parent first, the order next
            tabla, columna = ("lugares_carpetas", "padre_id") if tipo == "carpeta" else ("lugares_elementos", "carpeta_id")
            con.execute(f"UPDATE redes.{tabla} SET {columna} = %s, actualizado_en = now(), actualizado_por = %s WHERE id = %s", (destino_id, actor["id"], ident))
            repositorio.registrar(con, actor["id"], "lugar_carpeta" if tipo == "carpeta" else "lugar", ident, "editar", {"movido_a": destino_id})
        resto = [h for h in _hermanos(con, destino_id, dueno) if h not in movidos]
        posicion = len(resto)
        if antes_de and (antes_de.get("tipo"), int(antes_de.get("id") or 0)) in resto:
            posicion = resto.index((antes_de["tipo"], int(antes_de["id"])))
        resto[posicion:posicion] = movidos
        for n, (tipo, ident) in enumerate(resto, 1):
            tabla = "lugares_carpetas" if tipo == "carpeta" else "lugares_elementos"
            con.execute(f"UPDATE redes.{tabla} SET orden = %s WHERE id = %s", (n * 10, ident))
    return arbol(con, actor)


def visibilidad(con: Any, actor: dict[str, Any], *, carpetas: list[int] | None = None, elementos: list[int] | None = None,
                visible: bool = True) -> dict[str, Any]:
    """The check boxes of the actor's own folders: a folder's box sets everything inside it."""
    with con.transaction():
        propias = [f["id"] for f in con.execute("SELECT id FROM redes.lugares_carpetas WHERE usuario_id = %s AND borrado_en IS NULL", (actor["id"],)).fetchall()]
        c_ids = [int(c) for c in (carpetas or []) if int(c) in propias]
        todas_c, todos_e = _descendientes(con, c_ids) if c_ids else ([], [])
        e_ids = [int(e) for e in (elementos or [])]
        validos = [f["id"] for f in con.execute("SELECT id FROM redes.lugares_elementos WHERE id = ANY(%s) AND carpeta_id = ANY(%s) AND borrado_en IS NULL", (e_ids, propias)).fetchall()]
        con.execute("UPDATE redes.lugares_carpetas SET visible = %s WHERE id = ANY(%s)", (bool(visible), todas_c))
        con.execute("UPDATE redes.lugares_elementos SET visible = %s WHERE id = ANY(%s)", (bool(visible), todos_e + validos))
    return {"carpetas": todas_c, "elementos": todos_e + validos, "visible": bool(visible)}


# --------------------------------------------------------------------------- lugares (elementos)

def _procesar_descripcion(con: Any, actor: dict[str, Any], elemento_id: int, html: Any, imagenes: Any) -> str:
    """Safe HTML of the description; its images are kept in lugares_adjuntos and referenced as <img data-adj="id">.
    The page sends new images as <img data-nuevo="ref"> plus `imagenes` [{ref, nombre, datos (base64)}]."""
    html = str(html or "")
    nuevas = {}
    for im in imagenes or []:
        if not isinstance(im, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(im.get("ref") or "")):
            raise DatosInvalidos({"imagenes": "Imagen no válida"})
        try:
            datos = base64.b64decode(str(im.get("datos") or ""), validate=True)
        except (ValueError, TypeError):
            raise DatosInvalidos({"imagenes": "Imagen no válida"}) from None
        tipo = _tipo_imagen(datos)
        if tipo is None:
            raise DatosInvalidos({"imagenes": "Solo se aceptan imágenes PNG, JPEG, WEBP o GIF"})
        if len(datos) > MAX_ADJUNTO:
            raise DatosInvalidos({"imagenes": "Cada imagen puede pesar hasta 2 MB"})
        nuevas[str(im["ref"])] = (_texto(im.get("nombre"), 120) or "imagen", tipo, datos)
    propios = {f["id"] for f in con.execute("SELECT id FROM redes.lugares_adjuntos WHERE elemento_id = %s AND borrado_en IS NULL", (elemento_id,)).fetchall()}
    html = _IMG_NUEVA.sub(lambda m: f"[[IMG:nuevo:{m.group(1)}]]", html)
    html = _IMG_ADJ.sub(lambda m: f"[[IMG:adj:{m.group(1)}]]", html)
    limpio = texto.limpiar_html(html)
    usados: set[int] = set()
    creados: dict[str, int] = {}

    def volver(m: re.Match) -> str:
        origen, ref = m.group(1), m.group(2)
        if origen == "adj":
            if int(ref) not in propios:
                return ""
            usados.add(int(ref))
            return f'<img data-adj="{int(ref)}">'
        if ref not in nuevas:
            return ""
        if ref not in creados:
            if len(propios) + len(creados) >= MAX_ADJUNTOS:
                raise DatosInvalidos({"imagenes": f"Máximo {MAX_ADJUNTOS} imágenes por lugar"})
            nombre, tipo, datos = nuevas[ref]
            fila = con.execute("INSERT INTO redes.lugares_adjuntos (elemento_id, nombre, tipo, datos, creado_por) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                               (elemento_id, nombre, tipo, datos, actor["id"])).fetchone()
            creados[ref] = fila["id"]
        usados.add(creados[ref])
        return f'<img data-adj="{creados[ref]}">'

    final = _MARCA_IMG.sub(volver, limpio)
    sobran = [i for i in propios if i not in usados]
    if sobran:
        con.execute("UPDATE redes.lugares_adjuntos SET borrado_en = now() WHERE id = ANY(%s)", (sobran,))
    return final


def guardar_lugar(con: Any, actor: dict[str, Any], *, id: int | None = None, carpeta_id: int | None = None, tipo: str | None = None,
                  nombre: str | None = None, geom: dict[str, Any] | None = None, descripcion_html: str | None = None,
                  estilo: dict[str, Any] | None = None, vista: dict[str, Any] | None = None, propiedades: dict[str, Any] | None = None,
                  imagenes: list[dict[str, Any]] | None = None, version: int | None = None) -> dict[str, Any]:
    """Create (carpeta_id, tipo, nombre, geom…) or update (id + version) a marca, ruta, polígono… of a folder."""
    with con.transaction():
        if id is None:
            if tipo not in TIPOS:
                raise DatosInvalidos({"tipo": "Tipo de lugar no válido"})
            if carpeta_id is None:
                raise DatosInvalidos({"carpeta": "Elija la carpeta"})
            _exigir(con, actor, carpeta_id, editar=True)
            limpio = _texto(nombre, MAX_NOMBRE)
            if not limpio:
                raise DatosInvalidos({"nombre": "Escriba el nombre"})
            dueno = _acceso(con, actor, carpeta_id)["dueno_id"]
            ewkt, props, est = a_ewkt(tipo, geom), _propiedades(propiedades), limpiar_estilo(estilo)
            if tipo in lugares_red.TIPOS_RED:
                ewkt, props, est = _red(con, tipo, geom, props, est, dueno)
            fila = repositorio.insertar(con, "lugares_elementos", {
                "carpeta_id": int(carpeta_id), "tipo": tipo, "nombre": limpio, "geom": ewkt,
                "estilo": Jsonb(est), "vista": Jsonb(v) if (v := limpiar_vista(vista)) else None,
                "propiedades": Jsonb(props), "orden": _siguiente_orden(con, int(carpeta_id), dueno)}, actor["id"])
            html = _procesar_descripcion(con, actor, fila["id"], descripcion_html, imagenes)
            if html:
                con.execute("UPDATE redes.lugares_elementos SET descripcion_html = %s WHERE id = %s", (html, fila["id"]))
            repositorio.registrar(con, actor["id"], "lugar", fila["id"], "crear", {"nombre": [None, limpio], "tipo": [None, tipo]})
            ident = fila["id"]
        else:
            e, _a = _del_elemento(con, actor, id, editar=True)
            cambios: dict[str, Any] = {}
            if nombre is not None:
                limpio = _texto(nombre, MAX_NOMBRE)
                if not limpio:
                    raise DatosInvalidos({"nombre": "Escriba el nombre"})
                cambios["nombre"] = limpio
            if geom is not None:
                cambios["geom"] = a_ewkt(e["tipo"], geom)
            if estilo is not None:
                cambios["estilo"] = Jsonb(limpiar_estilo(estilo))
            if vista is not None:
                cambios["vista"] = Jsonb(v) if (v := limpiar_vista(vista)) else None
            if propiedades is not None:
                cambios["propiedades"] = Jsonb(_propiedades(propiedades))
            if e["tipo"] in lugares_red.TIPOS_RED and (geom is not None or propiedades is not None or estilo is not None):
                dueno = _acceso(con, actor, e["carpeta_id"])["dueno_id"]
                geo = geom if geom is not None else json.loads(con.execute("SELECT ST_AsGeoJSON(geom, 8) AS g FROM redes.lugares_elementos WHERE id = %s", (e["id"],)).fetchone()["g"])
                previas = _propiedades(propiedades) if propiedades is not None else (e["propiedades"] or {})
                previo_estilo = limpiar_estilo(estilo) if estilo is not None else (e["estilo"] or {})
                cambios["geom"], props, est = _red(con, e["tipo"], geo, previas, previo_estilo, dueno)
                cambios["propiedades"], cambios["estilo"] = Jsonb(props), Jsonb(est)
            if descripcion_html is not None:
                cambios["descripcion_html"] = _procesar_descripcion(con, actor, int(id), descripcion_html, imagenes) or None
            try:
                antes, despues = repositorio.actualizar(con, "lugares_elementos", int(id), int(version or 0), cambios, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("El lugar cambió mientras lo editaba. Recargue Mis lugares.") from None
            repositorio.registrar(con, actor["id"], "lugar", int(id), "editar", repositorio.diferencias(antes, despues))
            if e["tipo"] in lugares_red.PUNTUALES_RED and "geom" in cambios:
                p = json.loads(con.execute("SELECT ST_AsGeoJSON(geom, 8) AS g FROM redes.lugares_elementos WHERE id = %s", (int(id),)).fetchone()["g"])["coordinates"]
                lugares_red.seguir_elemento(con, actor["id"], int(id), p[0], p[1])
            ident = int(id)
    return obtener(con, actor, id=ident)


def eliminar_lugar(con: Any, actor: dict[str, Any], *, id: int, con_cables: bool = False) -> dict[str, Any]:
    """Logical delete. A network element with cables is refused unless `con_cables`: then its cables are deleted with it."""
    with con.transaction():
        e, _a = _del_elemento(con, actor, id, editar=True)
        if e["tipo"] in lugares_red.PUNTUALES_RED:
            cables = lugares_red.cables_de(con, e["id"])
            if cables and not con_cables:
                raise DatosInvalidos({"cables": "Tiene cables conectados (" + ", ".join(c["nombre"] for c in cables[:5]) + "): elimínelos también o despéguelos"})
            for c in cables:
                con.execute("UPDATE redes.lugares_elementos SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], c["id"]))
                repositorio.registrar(con, actor["id"], "lugar", c["id"], "eliminar", {"nombre": [c["nombre"], None]})
        con.execute("UPDATE redes.lugares_elementos SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], e["id"]))
        con.execute("UPDATE redes.lugares_adjuntos SET borrado_en = now() WHERE elemento_id = %s AND borrado_en IS NULL", (e["id"],))
        repositorio.registrar(con, actor["id"], "lugar", e["id"], "eliminar", {"nombre": [e["nombre"], None]})
    return {"id": e["id"]}


# --------------------------------------------------------------------------- compartir

def compartidos(con: Any, actor: dict[str, Any], *, carpeta_id: int) -> dict[str, Any]:
    _exigir(con, actor, carpeta_id, dueno=True)
    filas = con.execute("SELECT s.usuario_id, u.nombre, s.puede_editar FROM redes.lugares_compartidas s JOIN redes.usuarios u ON u.id = s.usuario_id "
                        "WHERE s.carpeta_id = %s ORDER BY lower(u.nombre)", (int(carpeta_id),)).fetchall()
    return {"compartidos": [dict(f) for f in filas]}


def compartir(con: Any, actor: dict[str, Any], *, carpeta_id: int, compartir_con: list[dict[str, Any]]) -> dict[str, Any]:
    """Sets with whom a folder (and its subfolders) is shared: [{usuario_id, puede_editar}]; an empty list stops sharing."""
    lista = compartir_con
    if not isinstance(lista, list):
        raise DatosInvalidos({"compartir": "Indique con quién compartir"})
    with con.transaction():
        _exigir(con, actor, carpeta_id, dueno=True)
        destinos: dict[int, bool] = {}
        for x in lista:
            try:
                uid = int(x["usuario_id"])
            except (KeyError, TypeError, ValueError):
                raise DatosInvalidos({"compartir": "Usuario no válido"}) from None
            if uid != actor["id"]:
                destinos[uid] = bool(x.get("puede_editar"))
        validos = {f["id"] for f in con.execute("SELECT id FROM redes.usuarios WHERE id = ANY(%s) AND borrado_en IS NULL", (list(destinos),)).fetchall()}
        con.execute("DELETE FROM redes.lugares_compartidas WHERE carpeta_id = %s", (int(carpeta_id),))
        for uid, edita in destinos.items():
            if uid in validos:
                con.execute("INSERT INTO redes.lugares_compartidas (carpeta_id, usuario_id, puede_editar, creado_por) VALUES (%s, %s, %s, %s)",
                            (int(carpeta_id), uid, edita, actor["id"]))
        repositorio.registrar(con, actor["id"], "lugar_carpeta", int(carpeta_id), "editar", {"compartida_con": sorted(validos & set(destinos))})
    return compartidos(con, actor, carpeta_id=carpeta_id)
