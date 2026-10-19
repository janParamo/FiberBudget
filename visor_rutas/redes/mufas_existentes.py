"""Migración Visio, fase 5: interactividad con la red existente (docs/migracion_visio/PLAN.md §7 y §8).

- `buscar`: la mufa migrada que corresponde a lo que el usuario abrió en el mapa (punto del KMZ,
  nodo Visio o "Lugares"): por el punto del KMZ, por el nombre del Visio cerca de la coordenada, o la
  más cercana. Enter / doble clic en cualquier mufa existente abre así su editor.
- `validar`: "Marcar como validada" (o quitar la validación). Validar pone la mufa y lo que tiene
  adentro en confianza "verificada"; una reimportación (fase 7) nunca pisa lo validado ni lo editado.
- `configurar_cable`: el selector de configuración del cable en el editor (6x4 ↔ 12x2…; o fijar los
  hilos de un cable desconocido). Los hilos se recolorean y las conexiones se conservan por número.
- `red_de_mufas`: la mufa y sus vecinas a 1 o 2 saltos, con los cables entre ellas.
"""
import re
import unicodedata
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import mufa, proyectos, red, repositorio, usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

TIPOS_MUFA = ("mufa", "nodo", "odf")
DISTANCIA_NOMBRE_M = 300          # same Visio name within this distance of the clicked point
DISTANCIA_SOLA_M = 30             # no name match: the nearest mufa within this distance


def _comparable(texto: Any) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", t.upper()).split())


def buscar(con: Any, actor: dict[str, Any], *, nombre: str | None = None, lat: float | None = None, lon: float | None = None,
           kmz_punto_id: int | None = None) -> dict[str, Any]:
    """{"mufa": {id, nombre, proyecto_id, proyecto} | None} among the mufas the user can see."""
    visibles = "(p.es_red_base OR %(admin)s OR EXISTS (SELECT 1 FROM redes.proyecto_usuarios pu WHERE pu.proyecto_id = p.id AND pu.usuario_id = %(u)s))"
    base = ("SELECT e.id, e.nombre, e.proyecto_id, p.nombre AS proyecto, e.ref_visio ->> 'nombre_visio' AS nombre_visio, "
            "{dist} AS d FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id "
            f"WHERE e.borrado_en IS NULL AND p.borrado_en IS NULL AND e.tipo = ANY(%(tipos)s) AND {visibles} ")
    args = {"admin": bool(actor.get("rol") == "administrador"), "u": actor.get("id"), "tipos": list(TIPOS_MUFA),
            "lat": lat, "lon": lon}
    hay_punto = lat is not None and lon is not None
    dist = ("ST_Distance(e.ubicacion::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography)" if hay_punto else "NULL::float8")
    publico = lambda f: {k: f[k] for k in ("id", "nombre", "proyecto_id", "proyecto")} if f else None
    if kmz_punto_id is not None:
        f = con.execute(base.format(dist=dist) + "AND (e.ref_externa -> 'kmz' ->> 'kmz_punto_id')::bigint = %(k)s ORDER BY e.id LIMIT 1",
                        {**args, "k": int(kmz_punto_id)}).fetchone()
        if f:
            return {"mufa": publico(f)}
    if nombre:
        clave = _comparable(nombre)
        plano = "regexp_replace(upper(translate({}, 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun')), '[^A-Z0-9]+', '', 'g')"
        por_visio, por_nombre = plano.format("e.ref_visio ->> 'nombre_visio'"), plano.format("e.nombre")
        filas = [f for f in con.execute(
            base.format(dist=dist) + f"AND ({por_visio} = %(n)s OR {por_nombre} = %(n)s) "
            "ORDER BY d NULLS LAST, e.id LIMIT 50", {**args, "n": clave.replace(" ", "")}).fetchall()
                 if _comparable(f["nombre_visio"]) == clave or _comparable(f["nombre"]) == clave]
        if hay_punto:
            filas = [f for f in filas if f["d"] is not None and f["d"] <= DISTANCIA_NOMBRE_M]
        if filas and (hay_punto or len(filas) == 1):
            return {"mufa": publico(filas[0])}
    if hay_punto:
        f = con.execute(base.format(dist=dist) + "AND e.ubicacion IS NOT NULL ORDER BY e.ubicacion <-> ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) "
                        "LIMIT 1", args).fetchone()
        if f and f["d"] <= DISTANCIA_SOLA_M:
            return {"mufa": publico(f)}
    return {"mufa": None}


CODIGO_BASE_VISOR = "BASE-VISOR"


def _proyecto_base_visor(con: Any, actor: dict[str, Any]) -> int:
    """The base project (visible to everyone) that holds the mufas created from the map; made the first time."""
    f = con.execute("SELECT id FROM redes.proyectos WHERE codigo = %s AND borrado_en IS NULL", (CODIGO_BASE_VISOR,)).fetchone()
    if f:
        return f["id"]
    fila = repositorio.insertar(con, "proyectos", {"codigo": CODIGO_BASE_VISOR, "nombre": "Red existente – creada desde el mapa", "es_red_base": True,
                                                   "descripcion": "Mufas del KMZ que no estaban en la red migrada y se crearon vacías desde el mapa (visor v2)."}, actor["id"])
    repositorio.registrar(con, actor["id"], "proyecto", fila["id"], "crear", {"codigo": [None, CODIGO_BASE_VISOR]}, proyecto_id=fila["id"])
    return fila["id"]


def crear_vacia(con: Any, actor: dict[str, Any], *, nombre: str, lat: float, lon: float) -> dict[str, Any]:
    """"Entrar a la mufa" of a point of the KMZ that the migration does not have: an empty mufa at that point (linked to it by
    its KMZ name and position). If one is found by `buscar`, that one is returned and nothing is created."""
    from visor_rutas.redes.elementos import punto
    limpio = " ".join(str(nombre or "").split())[:160]
    ubicacion = punto(lat, lon)
    if not limpio or ubicacion is None:
        raise DatosInvalidos({"mufa": "Falta el nombre o la posición de la mufa"})
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede crear mufas")
    previa = buscar(con, actor, nombre=limpio, lat=float(lat), lon=float(lon))["mufa"]
    if previa:
        return {"mufa": previa, "creada": False}
    with con.transaction():
        proyecto_id = _proyecto_base_visor(con, actor)
        fila = repositorio.insertar(con, "elementos", {
            "proyecto_id": proyecto_id, "tipo": "mufa", "subtipo": "empalme", "nombre": limpio, "ubicacion": ubicacion, "fuente": "kmz",
            "confianza": "media", "estado_migracion": "editada", "ref_externa": Jsonb({"kmz": {"nombre": limpio, "lat": float(lat), "lon": float(lon)}})},
            actor["id"])
        repositorio.registrar(con, actor["id"], "elemento", fila["id"], "crear", {"nombre": [None, limpio], "origen": [None, "mufa del KMZ sin migrar"]},
                              proyecto_id=proyecto_id)
        proyecto = con.execute("SELECT nombre FROM redes.proyectos WHERE id = %s", (proyecto_id,)).fetchone()["nombre"]
    return {"mufa": {"id": fila["id"], "nombre": limpio, "proyecto_id": proyecto_id, "proyecto": proyecto}, "creada": True}


def buscar_elementos(con: Any, actor: dict[str, Any], *, texto: str, limite: int = 10) -> dict[str, Any]:
    """Search box of the map (visor v2): elements of the network by name (or client code), accents and case ignored,
    every typed word must appear. Only what the Visio search does not already find: elements created in the tool
    and the clients (a mufa migrated from the Visio has its Visio node in that search). Among the projects the user sees."""
    palabras = _comparable(texto).split()
    if not palabras or sum(len(p) for p in palabras) < 2:
        return {"elementos": []}
    plano = "upper(translate(coalesce({}, ''), 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun'))"
    nombre, codigo = plano.format("e.nombre"), plano.format("e.codigo")
    visibles = "(p.es_red_base OR %(admin)s OR EXISTS (SELECT 1 FROM redes.proyecto_usuarios pu WHERE pu.proyecto_id = p.id AND pu.usuario_id = %(u)s))"
    args: dict[str, Any] = {"admin": bool(actor.get("rol") == "administrador"), "u": actor.get("id"),
                            "limite": max(1, min(int(limite or 10), 30)), "primero": palabras[0] + "%"}
    condiciones = []
    for i, palabra in enumerate(palabras):
        args[f"p{i}"] = f"%{palabra}%"
        condiciones.append(f"({nombre} LIKE %(p{i})s OR {codigo} LIKE %(p{i})s)")
    filas = con.execute(
        "SELECT e.id, e.nombre, e.tipo, e.subtipo, e.codigo, e.proyecto_id, p.nombre AS proyecto, "
        "ST_Y(e.ubicacion::geometry) AS lat, ST_X(e.ubicacion::geometry) AS lon FROM redes.elementos e "
        "JOIN redes.proyectos p ON p.id = e.proyecto_id "
        f"WHERE e.borrado_en IS NULL AND p.borrado_en IS NULL AND {visibles} "
        "AND (e.ref_visio IS NULL OR NOT e.ref_visio ? 'clave' OR e.tipo = 'cliente') AND " + " AND ".join(condiciones) + " "
        f"ORDER BY ({nombre} LIKE %(primero)s) DESC, e.nombre LIMIT %(limite)s", args).fetchall()
    return {"elementos": [{"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"], "subtipo": f["subtipo"], "codigo": f["codigo"],
                           "proyecto_id": f["proyecto_id"], "proyecto": f["proyecto"],
                           "lat": None if f["lat"] is None else float(f["lat"]), "lon": None if f["lon"] is None else float(f["lon"])}
                          for f in filas]}

def _elemento_editable(con: Any, actor: dict[str, Any], mufa_id: int) -> dict[str, Any]:
    m = con.execute("SELECT id, proyecto_id, tipo, nombre, estado_migracion FROM redes.elementos WHERE id = %s AND borrado_en IS NULL",
                    (int(mufa_id),)).fetchone()
    if m is None or m["tipo"] not in TIPOS_MUFA:
        raise NoEncontrado("La mufa no existe (o fue eliminada)")
    if not proyectos.puede_editar(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    return dict(m)


def validar(con: Any, actor: dict[str, Any], *, mufa_id: int, validada: bool = True) -> dict[str, Any]:
    """Marks the mufa as checked by a person (or removes the mark: it becomes "editada")."""
    m = _elemento_editable(con, actor, mufa_id)
    nuevo = "validada" if validada else "editada"
    with con.transaction():
        con.execute("UPDATE redes.elementos SET estado_migracion = %s, confianza = CASE WHEN %s THEN 'verificada' ELSE confianza END, "
                    "version = version + 1, actualizado_en = now(), actualizado_por = %s WHERE id = %s", (nuevo, validada, actor["id"], m["id"]))
        if validada:
            for tabla in ("splitters", "conexiones", "mufa_clientes"):
                con.execute(f"UPDATE redes.{tabla} SET confianza = 'verificada' WHERE mufa_id = %s AND borrado_en IS NULL", (m["id"],))
            con.execute("UPDATE redes.puerto_servicios x SET confianza = 'verificada' FROM redes.puertos p JOIN redes.splitters s ON s.id = p.splitter_id "
                        "WHERE x.puerto_id = p.id AND s.mufa_id = %s AND x.borrado_en IS NULL", (m["id"],))
        repositorio.registrar(con, actor["id"], "elemento", m["id"], "editar", {"estado_migracion": [m["estado_migracion"], nuevo]},
                              proyecto_id=m["proyecto_id"])
    return mufa.leer(con, actor, mufa_id=m["id"])


def configurar_cable(con: Any, actor: dict[str, Any], *, cable_id: int, mufa_id: int, hilos: int | None, hilos_por_buffer: int,
                     version: int) -> dict[str, Any]:
    """Fibre count / fibres per buffer of a cable, from the mufa editor. The fibres keep their numbers,
    so their connections stay; the buffer and TIA colour follow (trigger cables_recolorear_hilos)."""
    c = con.execute("SELECT * FROM redes.cables WHERE id = %s AND borrado_en IS NULL", (int(cable_id),)).fetchone()
    if c is None:
        raise NoEncontrado("El cable ya no existe: recargue la mufa")
    if not proyectos.puede_editar(con, actor, c["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    try:
        hilos = None if hilos in (None, "") else int(hilos)
        hilos_por_buffer = int(hilos_por_buffer)
    except (TypeError, ValueError):
        raise DatosInvalidos({"cable": "hilos y hilos por buffer deben ser números"}) from None
    if hilos is None and c["hilos"] is not None:
        raise DatosInvalidos({"cable": "un cable con hilos no puede volver a 'desconocido'"})
    if hilos is not None and hilos not in red.HILOS:
        raise DatosInvalidos({"cable": "cantidad de hilos no válida (" + ", ".join(map(str, red.HILOS)) + ")"})
    if hilos_por_buffer not in red.HILOS_POR_BUFFER:
        raise DatosInvalidos({"cable": "hilos por buffer: " + ", ".join(map(str, red.HILOS_POR_BUFFER))})
    with con.transaction():
        try:
            antes, despues = repositorio.actualizar(con, "cables", c["id"], int(version or 0),
                                                    {"hilos": hilos, "hilos_por_buffer": hilos_por_buffer, "configuracion_estimada": False}, actor["id"])
        except ConflictoVersion:
            raise ConflictoVersion(f"Cable {c['nombre']}: otro usuario lo cambió mientras usted editaba. Recargue la mufa.") from None
        try:
            mufa.sincronizar_hilos(con, c["id"], hilos, actor["id"])
        except DatosInvalidos as exc:
            raise DatosInvalidos({"cable": exc.errores["cable"]}) from None
        if c.get("estado_migracion") in ("automatica", "en_revision"):
            con.execute("UPDATE redes.cables SET estado_migracion = 'editada' WHERE id = %s", (c["id"],))
        repositorio.registrar(con, actor["id"], "cable", c["id"], "editar",
                              repositorio.diferencias({"hilos": antes["hilos"], "hilos_por_buffer": antes["hilos_por_buffer"]},
                                                      {"hilos": despues["hilos"], "hilos_por_buffer": despues["hilos_por_buffer"]}),
                              proyecto_id=c["proyecto_id"])
    return mufa.leer(con, actor, mufa_id=int(mufa_id))


def red_de_mufas(con: Any, actor: dict[str, Any], *, mufa_id: int, saltos: int = 2) -> dict[str, Any]:
    """The mufa and its neighbours up to `saltos` (1 or 2) hops through cables, for the "Red de mufas" view."""
    inicio = con.execute("SELECT id, proyecto_id FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(mufa_id),)).fetchone()
    if inicio is None:
        raise NoEncontrado("La mufa no existe (o fue eliminada)")
    if not proyectos.puede_ver(con, actor, inicio["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    saltos = 2 if int(saltos or 2) >= 2 else 1
    nivel = {inicio["id"]: 0}
    aristas: dict[int, dict[str, Any]] = {}
    frontera = [inicio["id"]]
    for n in range(1, saltos + 1):
        if not frontera or len(nivel) > 120:
            break
        siguiente = []
        for c in con.execute("SELECT id, nombre, hilos, color, origen_id, destino_id FROM redes.cables WHERE borrado_en IS NULL "
                             "AND (origen_id = ANY(%(f)s) OR destino_id = ANY(%(f)s))", {"f": frontera}).fetchall():
            aristas[c["id"]] = {"id": c["id"], "nombre": c["nombre"], "hilos": c["hilos"], "color": c["color"], "a": c["origen_id"], "b": c["destino_id"]}
            for x in (c["origen_id"], c["destino_id"]):
                if x not in nivel:
                    nivel[x] = n
                    siguiente.append(x)
        frontera = siguiente
    nodos = [{**dict(f), "nivel": nivel[f["id"]]} for f in con.execute(
        "SELECT e.id, e.nombre, e.tipo, e.subtipo, e.estado_migracion, p.nombre AS proyecto FROM redes.elementos e "
        "JOIN redes.proyectos p ON p.id = e.proyecto_id WHERE e.id = ANY(%s) AND e.borrado_en IS NULL", (list(nivel),)).fetchall()]
    ids = {x["id"] for x in nodos}
    return {"centro": inicio["id"], "saltos": saltos, "nodos": sorted(nodos, key=lambda x: (x["nivel"], x["nombre"])),
            "cables": [a for a in aristas.values() if a["a"] in ids and a["b"] in ids]}
