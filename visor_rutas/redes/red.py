"""Red de un proyecto (fase 3, editor de mapa): elementos, cables y notas, y su guardado.

El editor trabaja en la página (deshacer / rehacer) y guarda de forma explícita: manda todos los
cambios juntos y se aplican en UNA transacción, o ninguno.

    cambios = {"elementos": [...], "cables": [...], "notas": [...]}

Cada registro trae su "id" (número = existente, con su "version"; texto como "n3" = nuevo, que
otros registros del mismo envío pueden referenciar) y "eliminar": true para borrarlo (borrado
lógico, recuperable). Si alguien guardó antes cualquiera de los registros editados, nada se
guarda y se avisa (bloqueo optimista). Todo cambio queda en redes.historial.

Reglas que se cumplen siempre aquí (no solo en la página):
  - un cable empieza y termina en elementos del proyecto; sus extremos y los vértices pegados a
    un poste o mufa se mueven con él;
  - no se puede borrar un elemento con cables activos (la página ofrece borrarlos juntos);
  - el metraje del cable se recalcula con business_rules.yaml (diseno_red).
"""
import json
import math
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import metraje, mufa, proyectos, repositorio, texto, usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

SUBTIPOS = {"poste": ("ideay", "concreto", "madera", "metal", "cliente"),
            "mufa": ("empalme", "distribucion", "terminal", "reserva"),
            "cliente": (None,), "nodo": ("olt", "nodo", "mini_nodo"), "odf": (None,)}
HILOS = (2, 4, 6, 8, 12, 24, 48, 72, 96, 144)        # 2-8: cables of the existing network (Visio)
HILOS_POR_BUFFER = (2, 4, 6, 8, 12)                  # 6x4, 12x2, 6x8, 12x4, 1x12…
CLASES = ("troncal", "distribucion", "acometida")
MAX_REGISTROS = 5000
_CODIGO_CLIENTE = re.compile(r"^C\d{3,8}$", re.I)
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- lectura

def _elementos(con: Any, proyecto_id: int) -> list[dict[str, Any]]:
    filas = con.execute(
        "SELECT id, tipo, subtipo, nombre, codigo, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, propiedades, "
        "ref_externa, ubicacion_fuente, version FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id",
        (proyecto_id,)).fetchall()
    return [{**{k: f[k] for k in ("id", "tipo", "subtipo", "nombre", "codigo", "lat", "lon", "ref_externa", "ubicacion_fuente", "version")},
             "propiedades": f["propiedades"] or {}} for f in filas]


def _extremos_otra_region(con: Any, cable_id: int, origen: Any, destino: Any) -> dict[int, dict[str, Any]]:
    """A migrated cable between two regions keeps the end that lives in the other base project, as
    long as that end is not changed (only base projects share elements this way)."""
    actual = con.execute("SELECT origen_id, destino_id FROM redes.cables WHERE id = %s AND borrado_en IS NULL", (cable_id,)).fetchone()
    if actual is None:
        return {}
    ids = [x for x, y in ((origen, actual["origen_id"]), (destino, actual["destino_id"])) if x == y]
    filas = con.execute(
        "SELECT e.id, e.tipo, e.subtipo, e.nombre, e.codigo, ST_Y(e.ubicacion) AS lat, ST_X(e.ubicacion) AS lon, e.propiedades, "
        "e.ref_externa, e.ubicacion_fuente, e.version FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id "
        "WHERE e.id = ANY(%s) AND e.borrado_en IS NULL AND p.es_red_base", (ids,)).fetchall() if ids else []
    return {f["id"]: {**f, "propiedades": f["propiedades"] or {}} for f in filas}


def _cables(con: Any, proyecto_id: int) -> list[dict[str, Any]]:
    filas = con.execute(
        "SELECT id, nombre, descripcion, clase, tipo, hilos, hilos_por_buffer, color, origen_id, destino_id, vertices, "
        "cruces, longitud_m, metraje, configuracion, configuracion_estimada, geom_fuente, fuente, confianza, version "
        "FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id",
        (proyecto_id,)).fetchall()
    return [{**f, "longitud_m": float(f["longitud_m"])} for f in filas]


def _notas(con: Any, proyecto_id: int, contexto: str = "mapa") -> list[dict[str, Any]]:
    filas = con.execute(
        "SELECT id, contexto, mufa_id, elemento_id, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, x, y, html, ancho, "
        "version FROM redes.notas WHERE proyecto_id = %s AND contexto = %s AND borrado_en IS NULL ORDER BY id",
        (proyecto_id, contexto)).fetchall()
    return [dict(f) for f in filas]


def red(con: Any, actor: dict[str, Any], *, proyecto_id: int) -> dict[str, Any]:
    """The project and its network for the map editor."""
    p = proyectos.obtener(con, actor, id=int(proyecto_id))["proyecto"]
    from config import get_settings, load_rules
    try:
        regla = metraje.reglas(load_rules(get_settings().rules_path))
    except Exception:                       # settings not available (tests): the decided defaults
        regla = metraje.reglas(None)
    return {"proyecto": {k: p[k] for k in ("id", "codigo", "nombre", "version", "area", "lat", "lon", "puede_editar")},
            "elementos": _elementos(con, p["id"]), "cables": _cables(con, p["id"]), "notas": _notas(con, p["id"]),
            "reglas_metraje": regla}


# --------------------------------------------------------------------------- validación

def _texto(valor: Any, maximo: int) -> str | None:
    t = " ".join(str(valor or "").split())
    return t[:maximo] or None


def _punto(lat: Any, lon: Any) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(la) and math.isfinite(lo) and -90 <= la <= 90 and -180 <= lo <= 180):
        return None
    return la, lo


def _ewkt_punto(p: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({p[1]:.8f} {p[0]:.8f})"


def _marcar_editado(con: Any, tabla: str, actual: dict[str, Any], cambio: dict[str, Any]) -> None:
    """Migrated data (Visio) that a user changes becomes `editada`: a re-import never overwrites it."""
    if cambio and actual.get("estado_migracion") in ("automatica", "en_revision"):
        con.execute(f"UPDATE redes.{tabla} SET estado_migracion = 'editada' WHERE id = %s", (actual["id"],))


def _validar_elemento(d: dict[str, Any], quien: str) -> dict[str, Any]:
    tipo = str(d.get("tipo") or "")
    if tipo not in SUBTIPOS:
        raise DatosInvalidos({quien: "tipo de elemento no válido"})
    subtipo = d.get("subtipo") or None
    if subtipo not in SUBTIPOS[tipo]:
        subtipo = SUBTIPOS[tipo][0] if None not in SUBTIPOS[tipo] else None
    nombre = _texto(d.get("nombre"), 160)
    if not nombre:
        raise DatosInvalidos({quien: "falta el nombre"})
    codigo = _texto(d.get("codigo"), 40)
    if tipo == "cliente" and codigo:
        codigo = codigo.upper()
        if not _CODIGO_CLIENTE.match(codigo):
            raise DatosInvalidos({quien: "el código de cliente debe ser C seguido de números (C12345)"})
    p = _punto(d.get("lat"), d.get("lon"))
    if p is None:
        raise DatosInvalidos({quien: "coordenada no válida"})
    origen = d.get("propiedades") if isinstance(d.get("propiedades"), dict) else {}
    propiedades: dict[str, Any] = {}
    if tipo == "mufa":
        for clave, minimo, maximo in (("capacidad", 1, 1000), ("bandejas", 0, 100)):
            if origen.get(clave) not in (None, ""):
                try:
                    valor = int(origen[clave])
                except (TypeError, ValueError):
                    raise DatosInvalidos({quien: f"{clave} debe ser un número"}) from None
                if not minimo <= valor <= maximo:
                    raise DatosInvalidos({quien: f"{clave} fuera de rango ({minimo}–{maximo})"})
                propiedades[clave] = valor
    if tipo == "cliente" and _texto(origen.get("id_servicio"), 40):
        propiedades["id_servicio"] = _texto(origen.get("id_servicio"), 40)
    if _texto(origen.get("descripcion"), 2000):
        propiedades["descripcion"] = _texto(origen.get("descripcion"), 2000)
    ref = d.get("ref_externa") if isinstance(d.get("ref_externa"), dict) else None
    if ref:
        ref = {k: _texto(ref.get(k), 160) for k in ("fuente", "nombre") if _texto(ref.get(k), 160)} or None
    return {"tipo": tipo, "subtipo": subtipo, "nombre": nombre, "codigo": codigo, "punto": p,
            "propiedades": propiedades, "ref_externa": ref}


def _validar_cable(d: dict[str, Any], quien: str) -> dict[str, Any]:
    nombre = _texto(d.get("nombre"), 160)
    if not nombre:
        raise DatosInvalidos({quien: "falta el nombre"})
    clase = d.get("clase") or "distribucion"
    tipo = str(d.get("tipo") or "ADSS").upper()
    try:
        # an explicit null keeps "unknown" (migrated cables); a missing value means a new 12-fiber cable
        hilos = None if "hilos" in d and d["hilos"] in (None, "") else int(d.get("hilos") or 12)
        por_buffer, cruces = int(d.get("hilos_por_buffer") or 12), int(d.get("cruces") or 0)
    except (TypeError, ValueError):
        raise DatosInvalidos({quien: "hilos, hilos por buffer y cruces deben ser números"}) from None
    color = str(d.get("color") or "#1f6feb")
    errores = []
    if clase not in CLASES:
        errores.append("clase no válida (troncal, distribución o acometida)")
    if tipo not in ("ADSS", "FLAT"):
        errores.append("tipo de cable no válido (ADSS o FLAT)")
    if hilos is not None and hilos not in HILOS:
        errores.append("cantidad de hilos no válida (2, 4, 6, 8, 12, 24, 48, 72, 96 o 144)")
    if por_buffer not in HILOS_POR_BUFFER:
        errores.append("hilos por buffer: 2, 4, 6, 8 o 12")
    if not _COLOR.match(color):
        errores.append("color no válido")
    if not 0 <= cruces <= 500:
        errores.append("cruces fuera de rango")
    vertices = d.get("vertices")
    if not isinstance(vertices, list) or len(vertices) < 2:
        errores.append("el cable necesita al menos dos puntos")
        vertices = []
    limpios = []
    for v in vertices[:5000]:
        v = v if isinstance(v, dict) else {}
        p = _punto(v.get("lat"), v.get("lon"))
        if p is None:
            errores.append("vértice con coordenada no válida")
            break
        limpios.append({"lat": p[0], "lon": p[1], "elemento_id": v.get("elemento_id")})
    if errores:
        raise DatosInvalidos({quien: "; ".join(errores)})
    return {"nombre": nombre, "descripcion": (str(d.get("descripcion") or "").strip()[:2000] or None), "clase": clase,
            "tipo": tipo, "hilos": hilos, "hilos_por_buffer": por_buffer, "color": color.lower(), "cruces": cruces,
            "origen": d.get("origen_id"), "destino": d.get("destino_id"), "vertices": limpios}


# --------------------------------------------------------------------------- guardado

def _nombre_registro(tipo: str, d: dict[str, Any]) -> str:
    etiqueta = {"elementos": "Elemento", "cables": "Cable", "notas": "Nota"}[tipo]
    return f"{etiqueta} {_texto(d.get('nombre'), 60) or d.get('id') or ''}".strip()


def _legible_elemento(f: dict[str, Any]) -> dict[str, Any]:
    return {"tipo": f["tipo"], "subtipo": f.get("subtipo"), "nombre": f["nombre"], "codigo": f.get("codigo"),
            "lat": None if f["lat"] is None else round(f["lat"], 6), "lon": None if f["lon"] is None else round(f["lon"], 6),
            **(f.get("propiedades") or {})}


def _legible_cable(f: dict[str, Any]) -> dict[str, Any]:
    return {k: f.get(k) for k in ("nombre", "clase", "tipo", "hilos", "hilos_por_buffer", "color", "cruces")} | {
        "origen_id": f.get("origen_id"), "destino_id": f.get("destino_id"), "vertices": len(f.get("vertices") or []),
        "metraje_m": (f.get("metraje") or {}).get("metraje_m")}


def guardar(con: Any, actor: dict[str, Any], *, proyecto_id: int, cambios: dict[str, Any]) -> dict[str, Any]:
    """Applies the editor's changes in one transaction and returns the saved network plus
    {"ids": {"n3": 57, ...}} (the real id of each new record)."""
    proyecto_id = int(proyecto_id)
    if not proyectos.puede_editar(con, actor, proyecto_id):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    cambios = cambios if isinstance(cambios, dict) else {}
    listas = {k: [c for c in (cambios.get(k) or []) if isinstance(c, dict)] for k in ("elementos", "cables", "notas")}
    if sum(len(v) for v in listas.values()) > MAX_REGISTROS:
        raise DatosInvalidos({"red": f"Demasiados cambios en un solo guardado (máximo {MAX_REGISTROS})"})
    ids: dict[str, int] = {}

    def real(ref: Any) -> int | None:
        if ref is None or ref == "":
            return None
        if isinstance(ref, str) and not ref.lstrip("-").isdigit():
            if ref not in ids:
                raise DatosInvalidos({"red": f"Referencia a un elemento nuevo que no viene en el envío ({ref})"})
            return ids[ref]
        return int(ref)

    with con.transaction():
        if con.execute("SELECT 1 FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL FOR UPDATE",
                       (proyecto_id,)).fetchone() is None:
            raise NoEncontrado("El proyecto no existe o fue eliminado")
        movidos: set[int] = set()
        # 1) elements: create and edit (deletes go last, after the cables)
        for d in listas["elementos"]:
            if d.get("eliminar"):
                continue
            quien = _nombre_registro("elementos", d)
            v = _validar_elemento(d, quien)
            valores = {"subtipo": v["subtipo"], "nombre": v["nombre"], "codigo": v["codigo"],
                       "ubicacion": _ewkt_punto(v["punto"]), "propiedades": Jsonb(v["propiedades"]),
                       "ref_externa": Jsonb(v["ref_externa"]) if v["ref_externa"] else None}
            if _es_nuevo(d.get("id")):
                fila = repositorio.insertar(con, "elementos", {**valores, "proyecto_id": proyecto_id, "tipo": v["tipo"]}, actor["id"])
                ids[str(d["id"])] = fila["id"]
                repositorio.registrar(con, actor["id"], "elemento", fila["id"], "crear",
                                      repositorio.diferencias(None, _legible_elemento({**v, "lat": v["punto"][0], "lon": v["punto"][1]})),
                                      proyecto_id=proyecto_id)
            else:
                actual = _propio(con, "elementos", int(d["id"]), proyecto_id, quien)
                if actual["tipo"] != v["tipo"]:
                    raise DatosInvalidos({quien: "no se puede cambiar el tipo de un elemento"})
                antes = _legible_elemento(_un_elemento(con, actual["id"]))
                # a mufa without position (or with an estimated one) that someone places: the user's position
                if actual.get("ubicacion_fuente") in ("sin_ubicar", "estimada") and (antes["lat"] is None or (
                        round(antes["lat"], 7), round(antes["lon"], 7)) != (round(v["punto"][0], 7), round(v["punto"][1], 7))):
                    valores = {**valores, "ubicacion_fuente": "usuario"}
                _, despues = _actualizar(con, "elementos", actual["id"], d, valores, actor, quien)
                ahora = _legible_elemento(_un_elemento(con, actual["id"]))
                if (antes["lat"], antes["lon"]) != (ahora["lat"], ahora["lon"]):
                    movidos.add(actual["id"])
                cambio = repositorio.diferencias(antes, ahora)
                _marcar_editado(con, "elementos", actual, cambio)
                repositorio.registrar(con, actor["id"], "elemento", actual["id"], "editar", cambio, proyecto_id=proyecto_id)
        # 2) cables
        posiciones = {e["id"]: e for e in _elementos(con, proyecto_id)}
        for d in listas["cables"]:
            quien = _nombre_registro("cables", d)
            if d.get("eliminar"):
                if not _es_nuevo(d.get("id")):
                    cid = int(d["id"])
                    mufa.quitar_conexiones(con, "a_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = %s) OR "
                                                "b_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = %s)",
                                           (cid, cid), actor["id"], proyecto_id, f"cable {quien} eliminado")
                    _borrar(con, "cables", cid, d, proyecto_id, actor, quien, "cable")
                    con.execute("UPDATE redes.hilos SET borrado_en = now(), version = version + 1 WHERE cable_id = %s "
                                "AND borrado_en IS NULL", (cid,))
                continue
            v = _validar_cable(d, quien)
            origen, destino = real(v["origen"]), real(v["destino"])
            pos = posiciones
            if not _es_nuevo(d.get("id")) and (origen not in posiciones or destino not in posiciones):
                pos = posiciones | _extremos_otra_region(con, int(d["id"]), origen, destino)
            if origen not in pos or destino not in pos:
                raise DatosInvalidos({quien: "debe empezar y terminar en elementos del proyecto"})
            if origen == destino:
                raise DatosInvalidos({quien: "empieza y termina en el mismo elemento"})
            vertices = []
            for i, vx in enumerate(v["vertices"]):
                anclado = real(vx["elemento_id"]) if vx["elemento_id"] not in (None, "") else None
                if i == 0:
                    anclado = origen
                elif i == len(v["vertices"]) - 1:
                    anclado = destino
                if anclado is not None and anclado not in pos:
                    raise DatosInvalidos({quien: "un vértice está pegado a un elemento que no existe"})
                vertices.append({"lat": vx["lat"], "lon": vx["lon"], "elemento_id": anclado})
            valores = {"nombre": v["nombre"], "descripcion": v["descripcion"], "clase": v["clase"], "tipo": v["tipo"],
                       "hilos": v["hilos"], "hilos_por_buffer": v["hilos_por_buffer"], "color": v["color"],
                       "cruces": v["cruces"], "origen_id": origen, "destino_id": destino,
                       **_geometria(vertices, pos, v["cruces"])}
            if _es_nuevo(d.get("id")):
                fila = repositorio.insertar(con, "cables", {**valores, "proyecto_id": proyecto_id}, actor["id"])
                ids[str(d["id"])] = fila["id"]
                mufa.sincronizar_hilos(con, fila["id"], v["hilos"], actor["id"])          # its fibres 1..N
                repositorio.registrar(con, actor["id"], "cable", fila["id"], "crear",
                                      repositorio.diferencias(None, _legible_cable(_un_cable(con, fila["id"]))), proyecto_id=proyecto_id)
            else:
                actual = _propio(con, "cables", int(d["id"]), proyecto_id, quien)
                antes = _legible_cable(_un_cable(con, actual["id"]))
                # migrated cable: what the user changes is no longer an estimate
                if (actual["hilos"], actual["hilos_por_buffer"]) != (v["hilos"], v["hilos_por_buffer"]):
                    valores["configuracion_estimada"] = False
                trazo = lambda vs: [(round(float(x["lat"]), 7), round(float(x["lon"]), 7)) for x in vs or []]
                if actual.get("geom_fuente") in ("kmz", "recta") and trazo(actual["vertices"]) != trazo(vertices):
                    valores["geom_fuente"] = "usuario"
                _actualizar(con, "cables", actual["id"], d, valores, actor, quien)
                try:
                    mufa.sincronizar_hilos(con, actual["id"], v["hilos"], actor["id"])
                except DatosInvalidos as exc:
                    raise DatosInvalidos({quien: exc.errores["cable"]}) from None
                # A cable re-drawn to other ends loses its connections in the mufas it no longer reaches.
                mufa.quitar_conexiones(con, "mufa_id <> ALL(%s) AND (a_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = %s) "
                                            "OR b_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = %s))",
                                       ([origen, destino], actual["id"], actual["id"]), actor["id"], proyecto_id,
                                       f"el cable {quien} ya no llega a esa mufa")
                cambio = repositorio.diferencias(antes, _legible_cable(_un_cable(con, actual["id"])))
                _marcar_editado(con, "cables", actual, cambio)
                repositorio.registrar(con, actor["id"], "cable", actual["id"], "editar", cambio, proyecto_id=proyecto_id)
        # 3) element deletions (never with active cables)
        for d in listas["elementos"]:
            if not d.get("eliminar") or _es_nuevo(d.get("id")):
                continue
            quien = _nombre_registro("elementos", d)
            enlazados = con.execute(
                "SELECT nombre FROM redes.cables WHERE borrado_en IS NULL AND (origen_id = %(e)s OR destino_id = %(e)s "
                "OR vertices @> %(v)s::jsonb)", {"e": int(d["id"]), "v": json.dumps([{"elemento_id": int(d["id"])}])}).fetchall()
            if enlazados:
                raise DatosInvalidos({quien: "tiene cables conectados (" + ", ".join(c["nombre"] for c in enlazados[:5])
                                             + "): elimínelos también o despéguelos"})
            _borrar(con, "elementos", int(d["id"]), d, proyecto_id, actor, quien, "elemento")
            # its mufa canvas goes with it (recoverable: logical delete)
            mufa.quitar_conexiones(con, "mufa_id = %s", (int(d["id"]),), actor["id"], proyecto_id, f"{quien} eliminado")
            for tabla in ("splitters", "conectores"):
                con.execute(f"UPDATE redes.{tabla} SET borrado_en = now(), version = version + 1 WHERE mufa_id = %s "
                            "AND borrado_en IS NULL", (int(d["id"]),))
        # 4) notes
        for d in listas["notas"]:
            quien = f"Nota {d.get('id') or ''}".strip()
            if d.get("eliminar"):
                if not _es_nuevo(d.get("id")):
                    _borrar(con, "notas", int(d["id"]), d, proyecto_id, actor, quien, "nota")
                continue
            html = texto.limpiar_html(d.get("html"))
            if not html:
                raise DatosInvalidos({quien: "la nota está vacía"})
            elemento = real(d.get("elemento_id"))
            p = _punto(d.get("lat"), d.get("lon"))
            if elemento is not None:
                if elemento not in posiciones and not _activo(con, "elementos", elemento, proyecto_id):
                    raise DatosInvalidos({quien: "está anclada a un elemento que no existe"})
            elif p is None:
                raise DatosInvalidos({quien: "le falta la posición"})
            try:
                ancho = max(80, min(1200, int(d.get("ancho") or 220)))
            except (TypeError, ValueError):
                ancho = 220
            valores = {"contexto": "mapa", "elemento_id": elemento, "html": html, "ancho": ancho,
                       "ubicacion": _ewkt_punto(p) if p else None}
            if _es_nuevo(d.get("id")):
                fila = repositorio.insertar(con, "notas", {**valores, "proyecto_id": proyecto_id}, actor["id"])
                ids[str(d["id"])] = fila["id"]
                repositorio.registrar(con, actor["id"], "nota", fila["id"], "crear", {"html": [None, html[:300]]},
                                      proyecto_id=proyecto_id)
            else:
                actual = _propio(con, "notas", int(d["id"]), proyecto_id, quien)
                antes = actual["html"]
                _actualizar(con, "notas", actual["id"], d, valores, actor, quien)
                repositorio.registrar(con, actor["id"], "nota", actual["id"], "editar",
                                      {"html": [antes[:300], html[:300]]} if antes != html else {"posicion": [None, "movida"]},
                                      proyecto_id=proyecto_id)
        # 5) cables that follow moved elements (their ends and anchored vertices)
        if movidos:
            _seguir_elementos(con, proyecto_id, movidos, actor["id"])
    return {**red(con, actor, proyecto_id=proyecto_id), "ids": ids}


def _es_nuevo(ref: Any) -> bool:
    return isinstance(ref, str) and not ref.lstrip("-").isdigit()


def _activo(con: Any, tabla: str, id_: int, proyecto_id: int) -> bool:
    return con.execute(f"SELECT 1 FROM redes.{tabla} WHERE id = %s AND proyecto_id = %s AND borrado_en IS NULL",
                       (id_, proyecto_id)).fetchone() is not None


def _propio(con: Any, tabla: str, id_: int, proyecto_id: int, quien: str) -> dict[str, Any]:
    fila = repositorio.obtener(con, tabla, id_, bloquear=True)
    if fila["proyecto_id"] != proyecto_id or fila["borrado_en"] is not None:
        raise ConflictoVersion(f"{quien}: ya no existe (otro usuario lo eliminó). Recargue el proyecto.")
    return fila


def _actualizar(con: Any, tabla: str, id_: int, d: dict[str, Any], valores: dict[str, Any], actor: dict[str, Any],
                quien: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return repositorio.actualizar(con, tabla, id_, int(d.get("version") or 0), valores, actor["id"])
    except ConflictoVersion:
        raise ConflictoVersion(f"{quien}: otro usuario lo cambió mientras usted editaba. Recargue el proyecto "
                               "(sus cambios sin guardar se pierden).") from None


def _borrar(con: Any, tabla: str, id_: int, d: dict[str, Any], proyecto_id: int, actor: dict[str, Any], quien: str,
            entidad: str) -> None:
    _propio(con, tabla, id_, proyecto_id, quien)
    ahora = con.execute("SELECT now() AS n").fetchone()["n"]
    _actualizar(con, tabla, id_, d, {"borrado_en": ahora}, actor, quien)
    repositorio.registrar(con, actor["id"], entidad, id_, "eliminar", {"borrado_en": [None, ahora.isoformat()]},
                          proyecto_id=proyecto_id)


def _un_elemento(con: Any, id_: int) -> dict[str, Any]:
    f = con.execute("SELECT tipo, subtipo, nombre, codigo, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, propiedades "
                    "FROM redes.elementos WHERE id = %s", (id_,)).fetchone()
    return dict(f)


def _un_cable(con: Any, id_: int) -> dict[str, Any]:
    return dict(con.execute("SELECT * FROM redes.cables WHERE id = %s", (id_,)).fetchone())


def _geometria(vertices: list[dict[str, Any]], posiciones: dict[int, dict[str, Any]], cruces: int) -> dict[str, Any]:
    """Anchored vertices take their element's position; then geom, length and metraje."""
    for v in vertices:
        e = posiciones.get(v["elemento_id"]) if v["elemento_id"] is not None else None
        if e is not None:
            v["lat"], v["lon"] = e["lat"], e["lon"]
    puntos = [(v["lat"], v["lon"]) for v in vertices]
    lineal = metraje.longitud_m(puntos)
    extremos = [posiciones[vertices[0]["elemento_id"]]["tipo"], posiciones[vertices[-1]["elemento_id"]]["tipo"]]
    from config import get_settings, load_rules
    try:
        regla = metraje.reglas(load_rules(get_settings().rules_path))
    except Exception:
        regla = metraje.reglas(None)
    if len(set(puntos)) < 2:
        raise DatosInvalidos({"cable": "sus extremos están en el mismo punto"})
    return {"vertices": Jsonb(vertices), "geom": "SRID=4326;LINESTRING(" + ", ".join(f"{lo:.8f} {la:.8f}" for la, lo in puntos) + ")",
            "longitud_m": round(lineal, 2), "metraje": Jsonb(metraje.calcular(lineal, extremos, cruces, regla))}


def _seguir_elementos(con: Any, proyecto_id: int, movidos: set[int], usuario_id: int) -> None:
    posiciones = {e["id"]: e for e in _elementos(con, proyecto_id)}
    for c in _cables(con, proyecto_id):
        anclas = {v.get("elemento_id") for v in c["vertices"]}
        if not anclas & movidos:
            continue
        valores = _geometria([dict(v) for v in c["vertices"]], posiciones, c["cruces"])
        con.execute("UPDATE redes.cables SET vertices = %s, geom = %s, longitud_m = %s, metraje = %s, version = version + 1, "
                    "actualizado_en = now(), actualizado_por = %s WHERE id = %s",
                    (valores["vertices"], valores["geom"], valores["longitud_m"], valores["metraje"], usuario_id, c["id"]))


# --------------------------------------------------------------------------- duplicar proyecto

def copiar(con: Any, origen: int, destino: int, usuario_id: int) -> dict[str, int]:
    """Copies the active network of one project into another (Duplicar): elements, cables (with
    their anchors re-pointed) and notes. Returns how many of each."""
    from visor_rutas.redes.respaldo import _extras        # the columns of the Visio migration (009)
    mapa: dict[int, int] = {}
    for e in con.execute("SELECT * FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (origen,)).fetchall():
        nuevo = con.execute(
            "INSERT INTO redes.elementos (proyecto_id, tipo, subtipo, nombre, codigo, ubicacion, propiedades, ref_externa, ubicacion_fuente, "
            "creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (destino, e["tipo"], e["subtipo"], e["nombre"], e["codigo"], e["ubicacion"], Jsonb(e["propiedades"] or {}),
             Jsonb(e["ref_externa"]) if e["ref_externa"] else None, e["ubicacion_fuente"], usuario_id)).fetchone()
        mapa[e["id"]] = nuevo["id"]
        _extras(con, "elementos", nuevo["id"], e)
    cables: dict[int, int] = {}
    for c in con.execute("SELECT * FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id",
                         (origen,)).fetchall():
        if c["origen_id"] not in mapa or c["destino_id"] not in mapa:
            continue
        vertices = [{**v, "elemento_id": mapa.get(v.get("elemento_id"))} for v in c["vertices"]]
        nuevo = con.execute(
            "INSERT INTO redes.cables (proyecto_id, nombre, descripcion, clase, tipo, hilos, hilos_por_buffer, color, origen_id, "
            "destino_id, vertices, geom, cruces, longitud_m, metraje, creado_por) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (destino, c["nombre"], c["descripcion"], c["clase"], c["tipo"], c["hilos"], c["hilos_por_buffer"], c["color"],
             mapa[c["origen_id"]], mapa[c["destino_id"]], Jsonb(vertices), c["geom"], c["cruces"], c["longitud_m"],
             Jsonb(c["metraje"]) if c["metraje"] else None, usuario_id)).fetchone()
        cables[c["id"]] = nuevo["id"]
        _extras(con, "cables", nuevo["id"], c)
    n_cables = len(cables)
    # mufa canvases (phase 4): fibres with their states, positions, splitters, connectors, connections
    hilos: dict[int, int] = {}
    for viejo, nuevo in cables.items():
        for h in con.execute("SELECT id, numero, estado, observacion FROM redes.hilos WHERE cable_id = %s AND borrado_en IS NULL",
                             (viejo,)).fetchall():
            hilos[h["id"]] = con.execute("INSERT INTO redes.hilos (cable_id, numero, estado, observacion, creado_por) "
                                         "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                                         (nuevo, h["numero"], h["estado"], h["observacion"], usuario_id)).fetchone()["id"]
        con.execute("INSERT INTO redes.mufa_cables (mufa_id, cable_id, x, y) SELECT m.nuevo, %s, mc.x, mc.y "
                    "FROM redes.mufa_cables mc JOIN unnest(%s::bigint[], %s::bigint[]) AS m(viejo, nuevo) ON m.viejo = mc.mufa_id "
                    "WHERE mc.cable_id = %s", (nuevo, list(mapa), list(mapa.values()), viejo))
    puertos: dict[int, int] = {}
    splitters: dict[int, int] = {}
    for tabla, columna in (("splitters", "splitter_id"), ("conectores", "conector_id")):
        for s in con.execute(f"SELECT * FROM redes.{tabla} WHERE proyecto_id = %s AND borrado_en IS NULL", (origen,)).fetchall():
            if s["mufa_id"] not in mapa:
                continue
            datos = {k: s[k] for k in ("nombre", "x", "y") } | ({"salidas": s["salidas"], "relacion": s["relacion"], "conector": s["conector"]}
                                                               if tabla == "splitters" else {"tipo": s["tipo"]})
            nuevo = repositorio.insertar(con, tabla, {**datos, "proyecto_id": destino, "mufa_id": mapa[s["mufa_id"]]}, usuario_id)
            if tabla == "splitters":
                splitters[s["id"]] = nuevo["id"]
                _extras(con, "splitters", nuevo["id"], s)
            for p in con.execute(f"SELECT id, lado, numero FROM redes.puertos WHERE {columna} = %s", (s["id"],)).fetchall():
                puertos[p["id"]] = con.execute(f"INSERT INTO redes.puertos ({columna}, lado, numero) VALUES (%s, %s, %s) RETURNING id",
                                               (nuevo["id"], p["lado"], p["numero"])).fetchone()["id"]
    for x in con.execute("SELECT * FROM redes.conexiones WHERE proyecto_id = %s AND borrado_en IS NULL", (origen,)).fetchall():
        a = (hilos.get(x["a_hilo_id"]), puertos.get(x["a_puerto_id"]))
        b = (hilos.get(x["b_hilo_id"]), puertos.get(x["b_puerto_id"]))
        if x["mufa_id"] in mapa and any(a) and any(b):
            nueva = con.execute("INSERT INTO redes.conexiones (proyecto_id, mufa_id, a_hilo_id, a_puerto_id, b_hilo_id, b_puerto_id, creado_por) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (destino, mapa[x["mufa_id"]], *a, *b, usuario_id)).fetchone()
            _extras(con, "conexiones", nueva["id"], x)
    # Visio migration (009): mufa model and trays, clients per splitter port and per mufa
    for m in con.execute("SELECT * FROM redes.mufa_modelos WHERE borrado_en IS NULL AND mufa_id = ANY(%s)", (list(mapa),)).fetchall():
        repositorio.insertar(con, "mufa_modelos", {**{k: m[k] for k in ("formato", "capacidad", "empalmes_por_bandeja", "bandejas",
                                                                        "modelo_estimado", "fuente", "motivo")}, "avisos": Jsonb(m["avisos"]),
                                                   "mufa_id": mapa[m["mufa_id"]]}, usuario_id)
    for b in con.execute("SELECT * FROM redes.mufa_bandejas WHERE borrado_en IS NULL AND mufa_id = ANY(%s)", (list(mapa),)).fetchall():
        repositorio.insertar(con, "mufa_bandejas", {"mufa_id": mapa[b["mufa_id"]], "numero": b["numero"], "capacidad": b["capacidad"],
                                                    "splitter_id": splitters.get(b["splitter_id"]), "fuente": b["fuente"]}, usuario_id)
    for s in con.execute("SELECT * FROM redes.puerto_servicios WHERE borrado_en IS NULL AND puerto_id = ANY(%s)", (list(puertos),)).fetchall():
        repositorio.insertar(con, "puerto_servicios", {**{k: s[k] for k in ("codigo_cliente", "nombre", "id_servicio", "fuente", "confianza")},
                                                       "puerto_id": puertos[s["puerto_id"]], "elemento_id": mapa.get(s["elemento_id"])}, usuario_id)
    for c in con.execute("SELECT * FROM redes.mufa_clientes WHERE borrado_en IS NULL AND mufa_id = ANY(%s)", (list(mapa),)).fetchall():
        repositorio.insertar(con, "mufa_clientes", {**{k: c[k] for k in ("codigo_cliente", "nombre", "id_servicio", "fuente", "confianza")},
                                                    "mufa_id": mapa[c["mufa_id"]], "elemento_id": mapa.get(c["elemento_id"])}, usuario_id)
    n_notas = 0
    for n in con.execute("SELECT * FROM redes.notas WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (origen,)).fetchall():
        con.execute("INSERT INTO redes.notas (proyecto_id, contexto, mufa_id, elemento_id, ubicacion, x, y, html, ancho, creado_por) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (destino, n["contexto"], mapa.get(n["mufa_id"]), mapa.get(n["elemento_id"]), n["ubicacion"], n["x"], n["y"],
                     n["html"], n["ancho"], usuario_id))
        n_notas += 1
    # saved logical diagrams (phase 6): same start element / splitter in the copy
    for d in con.execute("SELECT * FROM redes.diagramas_logicos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id",
                         (origen,)).fetchall():
        elemento, splitter = mapa.get(d["elemento_id"]), splitters.get(d["splitter_id"])
        if elemento or splitter:
            repositorio.insertar(con, "diagramas_logicos", {"proyecto_id": destino, "titulo": d["titulo"], "elemento_id": elemento,
                                                            "splitter_id": splitter, "direccion": d["direccion"],
                                                            "incluir_clientes": d["incluir_clientes"]}, usuario_id)
    return {"elementos": len(mapa), "cables": n_cables, "notas": n_notas}
