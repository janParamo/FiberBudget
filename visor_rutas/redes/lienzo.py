"""Esquema de zona (lienzo): las mufas y los nodos de una zona acomodados en un mapa en blanco para interconectarlos.

- `zonas`: los proyectos donde hay lienzo (zonas de la red existente y los proyectos del usuario), con cuántas mufas / nodos tienen y cuántos hay ya en el lienzo.
- `lienzo`: lo de una zona: la lista de lo que se puede agregar (mufas, nodos y ODF del proyecto), lo ya colocado (x, y) y los cables entre ellos
  (con los extremos y los hilos). El primer lienzo, «General», se crea al abrir si el usuario puede editar el proyecto.
- `crear_lienzo`, `renombrar_lienzo`, `eliminar_lienzo`: los esquemas generales de la zona, cada uno con su nombre (uno por vista: «General», «Troncal norte»…).
- `guardar_lienzo`: las posiciones (y lo que se quitó del lienzo, que NO se borra de la red). Con la versión del lienzo, como lo demás.
Las cajas se colocan donde están las mufas en el mapa (coordenadas reales, sin mapa de fondo): el esquema guarda el punto de referencia (`origen_lat`,
`origen_lon`) y la escala (`escala`, píxeles del lienzo por metro) con los que la página calcula esas posiciones, para que todos vean lo mismo.
La posición de cada caja es la REAL del KMZ: a cada mufa se le busca en el KMZ (`red_puntos`) el punto del mismo nombre (el más cercano a la que
tiene guardada) y, si hay, ese punto manda para ubicarla en el esquema (`kmz`: lat, lon, a cuántos metros de la de Visio está); el KMZ es el mapa que ven los
técnicos y el diagrama Visio suele traer coordenadas aproximadas. Sin coincidencia (o sin acceso al KMZ) se usa la coordenada de la propia mufa.
Los cables se crean y editan con `guardar_red` (red.py), los mismos del editor de mapa; la conexión hilo a hilo, con el editor de mufa.
"""
import logging
import re
import time
import unicodedata
from typing import Any

import psycopg

from psycopg.types.json import Jsonb

from visor_rutas.redes import proyectos, repositorio, usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

log = logging.getLogger(__name__)

TIPOS = ("mufa", "nodo", "odf")
RADIO_KMZ_M = 3000.0                 # a KMZ point of the same name farther than this from the saved coordinate is another mufa
MARGEN_KMZ_GRADOS = 0.03             # ~3 km around the zone, to read the KMZ points near it
_kmz_sin_acceso_hasta = 0.0
MAX_COLOCADOS = 5000
_COLUMNAS = "id, nombre, version, origen_lat, origen_lon, escala"
LIMITE_COORD = 5_000_000.0


def _proyecto(con: Any, actor: dict[str, Any], proyecto_id: int) -> dict[str, Any]:
    p = con.execute("SELECT id, codigo, nombre, zona, es_red_base FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL", (int(proyecto_id),)).fetchone()
    if p is None:
        raise NoEncontrado("El proyecto no existe (o fue eliminado)")
    if not proyectos.puede_ver(con, actor, p["id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    return dict(p)


def zonas(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Projects with mufas / nodes the actor can see: the zones of the existing network first, then the rest."""
    filas = con.execute(
        "SELECT p.id, p.codigo, p.nombre, p.zona, p.es_red_base, "
        " count(e.id) FILTER (WHERE e.tipo = 'mufa') AS mufas, count(e.id) FILTER (WHERE e.tipo IN ('nodo', 'odf')) AS nodos, "
        " (SELECT count(*) FROM redes.lienzo_elementos le JOIN redes.lienzos l ON l.id = le.lienzo_id WHERE l.proyecto_id = p.id AND l.borrado_en IS NULL) AS colocados "
        "FROM redes.proyectos p LEFT JOIN redes.elementos e ON e.proyecto_id = p.id AND e.borrado_en IS NULL AND e.tipo IN ('mufa', 'nodo', 'odf') "
        "WHERE p.borrado_en IS NULL AND (p.es_red_base OR %(todos)s OR EXISTS (SELECT 1 FROM redes.proyecto_usuarios pu WHERE pu.proyecto_id = p.id AND pu.usuario_id = %(u)s)) "
        "GROUP BY p.id ORDER BY p.es_red_base DESC, lower(coalesce(p.zona, p.nombre)), lower(p.nombre)",
        {"todos": usuarios.es_admin(actor), "u": actor["id"]}).fetchall()
    return {"zonas": [{**dict(f), "mufas": int(f["mufas"]), "nodos": int(f["nodos"]), "colocados": int(f["colocados"])} for f in filas
                      if f["mufas"] or f["nodos"] or not f["es_red_base"]]}


def _lienzo_de(con: Any, actor: dict[str, Any], proyecto_id: int, puede_editar: bool, lienzo_id: int | None = None) -> dict[str, Any] | None:
    """The canvas `lienzo_id` of the project, or the first one (created as «General» when there is none and the actor can edit)."""
    if lienzo_id is not None:
        fila = con.execute(f"SELECT {_COLUMNAS} FROM redes.lienzos WHERE id = %s AND proyecto_id = %s AND borrado_en IS NULL", (int(lienzo_id), proyecto_id)).fetchone()
        if fila is None:
            raise NoEncontrado("El esquema no existe (o fue eliminado)")
        return dict(fila)
    consulta = f"SELECT {_COLUMNAS} FROM redes.lienzos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id LIMIT 1"
    fila = con.execute(consulta, (proyecto_id,)).fetchone()
    if fila is None and puede_editar:
        with con.transaction():
            fila = con.execute("INSERT INTO redes.lienzos (proyecto_id, nombre, creado_por) VALUES (%s, 'General', %s) "
                               f"ON CONFLICT DO NOTHING RETURNING {_COLUMNAS}", (proyecto_id, actor["id"])).fetchone()
        if fila is None:                                             # another one created it at the same time
            fila = con.execute(consulta, (proyecto_id,)).fetchone()
    return dict(fila) if fila else None


def conexion_kmz() -> Any:
    """Read-only connection to the KMZ network database (red_puntos), or None when it is not reachable (checked again after a minute)."""
    global _kmz_sin_acceso_hasta
    if time.time() < _kmz_sin_acceso_hasta:
        return None
    try:
        from psycopg.rows import dict_row

        from config import get_settings
        s = get_settings()
        return psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password, row_factory=dict_row,
                               connect_timeout=3, options="-c default_transaction_read_only=on -c statement_timeout=15000")
    except Exception as exc:                                    # noqa: BLE001 - the schema works without the KMZ: the mufas' own coordinates are used
        _kmz_sin_acceso_hasta = time.time() + 60
        log.info("Esquema de zona: el KMZ no está disponible (%s); se usan las coordenadas de las mufas", type(exc).__name__)
        return None


def _plano(texto: Any) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", sin.upper()).split())


def _metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from visor_rutas.redes import metraje
    return metraje.longitud_m([(lat1, lon1), (lat2, lon2)])


def _cambios_puntos(con: Any) -> list[dict[str, Any]]:
    """The changes made in the viewer to points of the KMZ (renamed, moved, removed). The KMZ file does not change: they live in `redes.kmz_cambios` and the map applies them,
    so the zone must too (what the map shows as the name of a mufa is the name here)."""
    return [dict(f) for f in con.execute("SELECT accion, antes, despues FROM redes.kmz_cambios WHERE borrado_en IS NULL AND tipo = 'punto'").fetchall()]


def _con_cambios(filas: list[dict[str, Any]], cambios: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """`filas` ({nombre, lat, lon, ...} of KMZ points) with the changes of the viewer applied. A change belongs to the point that had its ORIGINAL name at its ORIGINAL place
    (3 m): red_puntos has no folder, so the key the page uses cannot be rebuilt."""
    if not cambios:
        return filas
    salida = []
    for f in filas:
        ch = next((c for c in cambios if (c["antes"] or {}).get("lat") is not None and _plano((c["antes"] or {}).get("nombre")) == _plano(f.get("nombre"))
                   and _metros(c["antes"]["lat"], c["antes"]["lon"], float(f["lat"]), float(f["lon"])) <= 3.0), None)
        if ch is None:
            salida.append(f)
            continue
        if ch["accion"] == "borrar":
            continue
        d = ch["despues"] or {}
        g = dict(f)
        if d.get("nombre"):
            g["nombre"] = d["nombre"]
        if d.get("lat") is not None and d.get("lon") is not None:
            g["lat"], g["lon"] = d["lat"], d["lon"]
        salida.append(g)
    return salida


def coincidencias_kmz(elementos: list[dict[str, Any]], kmz: Any = None, cambios: list[dict[str, Any]] | None = None) -> dict[int, dict[str, Any]]:
    """{element id: {"id", "nombre", "categoria", "lat", "lon", "distancia_m"}} of the KMZ point (mufa, reserve, node...) with the same name as each element,
    the nearest one to the coordinate the element already has (within RADIO_KMZ_M). {} when the KMZ cannot be read."""
    con_coord = [e for e in elementos if e.get("lat") is not None and e.get("lon") is not None]
    if not con_coord:
        return {}
    cerrar = kmz is None
    kmz = kmz if kmz is not None else conexion_kmz()
    if kmz is None:
        return {}
    try:
        lats, lons = [e["lat"] for e in con_coord], [e["lon"] for e in con_coord]
        filas = kmz.execute("SELECT id, nombre, categoria, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM red_puntos WHERE geom IS NOT NULL AND GeometryType(geom) = 'POINT' "
                            "AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)",
                            (min(lons) - MARGEN_KMZ_GRADOS, min(lats) - MARGEN_KMZ_GRADOS, max(lons) + MARGEN_KMZ_GRADOS, max(lats) + MARGEN_KMZ_GRADOS)).fetchall()
    except Exception as exc:                                    # noqa: BLE001
        log.warning("Esquema de zona: no se pudo leer red_puntos (%s)", type(exc).__name__)
        return {}
    finally:
        if cerrar:
            kmz.close()
    por_nombre: dict[str, list[dict[str, Any]]] = {}
    for f in _con_cambios([dict(x) for x in filas], cambios):
        clase = f"{f.get('categoria') or ''}".lower()
        if "poste" in clase or "pozo" in clase or not f.get("nombre"):
            continue
        por_nombre.setdefault(_plano(f["nombre"]), []).append(dict(f))
    salida: dict[int, dict[str, Any]] = {}
    for e in con_coord:
        mejores = sorted(((_metros(e["lat"], e["lon"], k["lat"], k["lon"]), k) for k in por_nombre.get(_plano(e["nombre"]), [])), key=lambda c: c[0])
        if mejores and mejores[0][0] <= RADIO_KMZ_M:
            d, k = mejores[0]
            salida[e["id"]] = {"id": k["id"], "nombre": k["nombre"], "categoria": k.get("categoria"), "lat": float(k["lat"]), "lon": float(k["lon"]), "distancia_m": round(d, 1)}
    return salida


def lienzo(con: Any, actor: dict[str, Any], *, proyecto_id: int, lienzo_id: int | None = None) -> dict[str, Any]:
    p = _proyecto(con, actor, proyecto_id)
    editar = proyectos.puede_editar(con, actor, p["id"])
    lz = _lienzo_de(con, actor, p["id"], editar, lienzo_id)
    lienzos = [dict(f) for f in con.execute(f"SELECT {_COLUMNAS} FROM redes.lienzos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (p["id"],)).fetchall()]
    elementos = [dict(f) for f in con.execute(
        "SELECT id, tipo, subtipo, nombre, codigo, ST_Y(ubicacion::geometry) AS lat, ST_X(ubicacion::geometry) AS lon, ubicacion_fuente, estado_migracion "
        "FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL AND tipo = ANY(%s) ORDER BY lower(nombre), id", (p["id"], list(TIPOS))).fetchall()]
    en_kmz = coincidencias_kmz(elementos, cambios=_cambios_puntos(con))
    for e in elementos:
        e["kmz"] = en_kmz.get(e["id"])                       # where the KMZ has it (None: it uses its own coordinate)
    colocados = [dict(f) for f in con.execute("SELECT elemento_id, x, y FROM redes.lienzo_elementos WHERE lienzo_id = %s ORDER BY elemento_id",
                                              (lz["id"],)).fetchall()] if lz else []
    cables = [dict(f) for f in con.execute(
        "SELECT c.id, c.nombre, c.clase, c.tipo, c.hilos, c.color, c.origen_id, c.destino_id, c.longitud_m, c.version, "
        " (SELECT count(*) FROM redes.conexiones x WHERE x.borrado_en IS NULL AND (x.a_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = c.id) "
        "  OR x.b_hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = c.id))) AS conectados "
        "FROM redes.cables c WHERE c.proyecto_id = %s AND c.borrado_en IS NULL "
        "AND c.origen_id IN (SELECT id FROM redes.elementos WHERE proyecto_id = %s AND tipo = ANY(%s)) "
        "AND c.destino_id IN (SELECT id FROM redes.elementos WHERE proyecto_id = %s AND tipo = ANY(%s)) ORDER BY c.id",
        (p["id"], p["id"], list(TIPOS), p["id"], list(TIPOS))).fetchall()]
    return {"proyecto": {**p, "puede_editar": editar}, "lienzo": lz, "lienzos": lienzos, "elementos": elementos, "colocados": colocados, "cables": cables}


def _numero(valor: Any, quien: str) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({"lienzo": f"posición no válida ({quien})"}) from None
    if n != n or abs(n) > LIMITE_COORD:
        raise DatosInvalidos({"lienzo": f"posición fuera de rango ({quien})"})
    return round(n, 2)


def _referencia(origen: Any, escala: Any) -> dict[str, Any]:
    """The reference point {lat, lon} and the scale (canvas pixels per metre) to keep, validated; {} when none comes."""
    salida: dict[str, Any] = {}
    if origen is not None:
        try:
            lat, lon = float(origen["lat"]), float(origen["lon"])
        except (TypeError, ValueError, KeyError):
            raise DatosInvalidos({"lienzo": "punto de referencia no válido"}) from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise DatosInvalidos({"lienzo": "punto de referencia fuera de rango"})
        salida.update(origen_lat=round(lat, 7), origen_lon=round(lon, 7))
    if escala is not None:
        try:
            e = float(escala)
        except (TypeError, ValueError):
            raise DatosInvalidos({"lienzo": "escala no válida"}) from None
        if not 0.05 <= e <= 50:
            raise DatosInvalidos({"lienzo": "escala fuera de rango (0.05 a 50 píxeles por metro)"})
        salida["escala"] = round(e, 4)
    return salida


def guardar_lienzo(con: Any, actor: dict[str, Any], *, proyecto_id: int, lienzo_id: int | None = None, version: int | None = None,
                   colocados: list[dict[str, Any]] | None = None, quitados: list[int] | None = None, origen: dict[str, Any] | None = None,
                   escala: float | None = None) -> dict[str, Any]:
    """Places (or moves) the elements in `colocados` [{elemento_id, x, y}] and takes `quitados` off the canvas (they stay in the network).
    `origen` {lat, lon} and `escala` (pixels per metre) set the reference of the real-coordinates layout."""
    p = _proyecto(con, actor, proyecto_id)
    if not proyectos.puede_editar(con, actor, p["id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    colocados = [c for c in (colocados or []) if isinstance(c, dict)]
    quitados = [int(i) for i in (quitados or []) if str(i).lstrip("-").isdigit()]
    if len(colocados) > MAX_COLOCADOS:
        raise DatosInvalidos({"lienzo": f"Demasiados elementos en un guardado (máximo {MAX_COLOCADOS})"})
    referencia = _referencia(origen, escala)
    nuevos: dict[int, tuple[float, float]] = {}
    for c in colocados:
        if not str(c.get("elemento_id", "")).lstrip("-").isdigit():
            raise DatosInvalidos({"lienzo": "elemento no válido"})
        nuevos[int(c["elemento_id"])] = (_numero(c.get("x"), "x"), _numero(c.get("y"), "y"))
    with con.transaction():
        lz = _lienzo_de(con, actor, p["id"], True, lienzo_id)
        if lz is None:
            raise NoEncontrado("El lienzo no existe")
        validos = {f["id"] for f in con.execute("SELECT id FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL AND tipo = ANY(%s) AND id = ANY(%s)",
                                                 (p["id"], list(TIPOS), list(nuevos))).fetchall()} if nuevos else set()
        if set(nuevos) - validos:
            raise DatosInvalidos({"lienzo": "Hay elementos que no son mufas, nodos u ODF de esta zona"})
        ajustes = "".join(f", {campo} = %s" for campo in referencia)
        actualizado = con.execute(f"UPDATE redes.lienzos SET version = version + 1, actualizado_en = now(), actualizado_por = %s{ajustes} WHERE id = %s AND version = %s "
                                  "RETURNING version", (actor["id"], *referencia.values(), lz["id"], int(version if version is not None else lz["version"]))).fetchone()
        if actualizado is None:
            raise ConflictoVersion("Otro usuario cambió este esquema mientras usted lo editaba. Recargue y repita el cambio.")
        for eid, (x, y) in nuevos.items():
            con.execute("INSERT INTO redes.lienzo_elementos (lienzo_id, elemento_id, x, y) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (lienzo_id, elemento_id) DO UPDATE SET x = EXCLUDED.x, y = EXCLUDED.y", (lz["id"], eid, x, y))
        if quitados:
            con.execute("DELETE FROM redes.lienzo_elementos WHERE lienzo_id = %s AND elemento_id = ANY(%s)", (lz["id"], quitados))
    return lienzo(con, actor, proyecto_id=p["id"], lienzo_id=lz["id"])


# --------------------------------------------------------------------------- los esquemas de una zona (cada uno con su nombre)

def _nombre(valor: Any) -> str:
    nombre = " ".join(str(valor or "").split())[:120]
    if not nombre:
        raise DatosInvalidos({"nombre": "Escriba el nombre del esquema"})
    return nombre


def _editable(con: Any, actor: dict[str, Any], proyecto_id: int) -> dict[str, Any]:
    p = _proyecto(con, actor, proyecto_id)
    if not proyectos.puede_editar(con, actor, p["id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    return p


def crear_lienzo(con: Any, actor: dict[str, Any], *, proyecto_id: int, nombre: str) -> dict[str, Any]:
    """A new empty schema of the zone («Troncal norte», «Ramal 2»…); it opens ready to fill."""
    p = _editable(con, actor, proyecto_id)
    nombre = _nombre(nombre)
    try:
        with con.transaction():
            fila = con.execute("INSERT INTO redes.lienzos (proyecto_id, nombre, creado_por) VALUES (%s, %s, %s) RETURNING id", (p["id"], nombre, actor["id"])).fetchone()
    except psycopg.errors.UniqueViolation:
        raise DatosInvalidos({"nombre": "Ya hay un esquema con ese nombre en esta zona"}) from None
    return lienzo(con, actor, proyecto_id=p["id"], lienzo_id=fila["id"])


def renombrar_lienzo(con: Any, actor: dict[str, Any], *, proyecto_id: int, lienzo_id: int, nombre: str, version: int | None = None) -> dict[str, Any]:
    p = _editable(con, actor, proyecto_id)
    nombre = _nombre(nombre)
    lz = _lienzo_de(con, actor, p["id"], True, lienzo_id)
    try:
        with con.transaction():
            fila = con.execute("UPDATE redes.lienzos SET nombre = %s, version = version + 1, actualizado_en = now(), actualizado_por = %s WHERE id = %s AND version = %s "
                               "RETURNING id", (nombre, actor["id"], lz["id"], int(version if version is not None else lz["version"]))).fetchone()
    except psycopg.errors.UniqueViolation:
        raise DatosInvalidos({"nombre": "Ya hay un esquema con ese nombre en esta zona"}) from None
    if fila is None:
        raise ConflictoVersion("Otro usuario cambió este esquema. Recargue y repita el cambio.")
    return lienzo(con, actor, proyecto_id=p["id"], lienzo_id=lz["id"])


def eliminar_lienzo(con: Any, actor: dict[str, Any], *, proyecto_id: int, lienzo_id: int, version: int | None = None) -> dict[str, Any]:
    """Deletes a schema (where the boxes were placed); the mufas and cables of the network are not touched. «General» is created again if none is left."""
    p = _editable(con, actor, proyecto_id)
    lz = _lienzo_de(con, actor, p["id"], True, lienzo_id)
    with con.transaction():
        fila = con.execute("UPDATE redes.lienzos SET borrado_en = now(), version = version + 1, actualizado_en = now(), actualizado_por = %s WHERE id = %s AND version = %s "
                           "RETURNING id", (actor["id"], lz["id"], int(version if version is not None else lz["version"]))).fetchone()
        if fila is None:
            raise ConflictoVersion("Otro usuario cambió este esquema. Recargue y repita el cambio.")
        con.execute("DELETE FROM redes.lienzo_elementos WHERE lienzo_id = %s", (lz["id"],))
    return lienzo(con, actor, proyecto_id=p["id"])


# --------------------------------------------------------------------------- las mufas del KMZ que la zona no tiene (nuevas o renombradas)

RADIO_RENOMBRADA_M = 60.0            # an element this close to a KMZ point with another name is probably the same mufa, renamed
FAMILIA_KMZ = {"mufa": ("mufa", "empalme"), "reserva": ("mufa", "reserva"), "nodo": ("nodo", "nodo")}


def _puntos_kmz_cerca(elementos: list[dict[str, Any]], kmz: Any, cambios: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The KMZ points (mufa, reserve, node) around the zone: not posts or wells."""
    con_coord = [e for e in elementos if e.get("lat") is not None and e.get("lon") is not None]
    if not con_coord:
        return []
    lats, lons = [e["lat"] for e in con_coord], [e["lon"] for e in con_coord]
    filas = kmz.execute("SELECT id, nombre, categoria, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM red_puntos WHERE geom IS NOT NULL AND GeometryType(geom) = 'POINT' "
                        "AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)",
                        (min(lons) - MARGEN_KMZ_GRADOS, min(lats) - MARGEN_KMZ_GRADOS, max(lons) + MARGEN_KMZ_GRADOS, max(lats) + MARGEN_KMZ_GRADOS)).fetchall()
    return _con_cambios([dict(f) for f in filas if f.get("nombre") and (f.get("categoria") or "").lower() in FAMILIA_KMZ], cambios)


def mufas_kmz(con: Any, actor: dict[str, Any], *, proyecto_id: int, kmz: Any = None) -> dict[str, Any]:
    """The KMZ mufas around the zone that the zone does not have yet: new ones, or the same mufa renamed (e.g. two mufas that were both «PUERTO PAZ» and are now
    «PUERTO PAZ 1» and «PUERTO PAZ 2»). A KMZ point is «had» by the zone when an element is linked to it (`ref_externa.kmz.kmz_punto_id`) or, failing that, has its name
    and is the nearest one with it; each element has at most one. {"nuevas": [{kmz_id, nombre, categoria, lat, lon, cercana: {id, nombre, distancia_m} | None}],
    "en_zona": n, "en_kmz": n, "nombres_cambiados": [{elemento_id, version, nombre, kmz_id, nombre_kmz}]} (the last: mufas of the zone linked to a KMZ point that has another
    name now). Nothing is written."""
    p = _proyecto(con, actor, proyecto_id)
    elementos = [dict(f) for f in con.execute(
        "SELECT id, tipo, nombre, version, ST_Y(ubicacion::geometry) AS lat, ST_X(ubicacion::geometry) AS lon, ref_externa FROM redes.elementos "
        "WHERE proyecto_id = %s AND borrado_en IS NULL AND tipo = ANY(%s) ORDER BY id", (p["id"], list(TIPOS))).fetchall()]
    cerrar = kmz is None
    kmz = kmz if kmz is not None else conexion_kmz()
    if kmz is None:
        raise DatosInvalidos({"kmz": "No se pudo leer el KMZ (la base del presupuesto no responde)"})
    try:
        puntos = _puntos_kmz_cerca(elementos, kmz, _cambios_puntos(con))
    except Exception as exc:                                    # noqa: BLE001
        log.warning("Esquema de zona: no se pudo leer red_puntos (%s)", type(exc).__name__)
        raise DatosInvalidos({"kmz": "No se pudo leer el KMZ (la base del presupuesto no responde)"}) from None
    finally:
        if cerrar:
            kmz.close()
    por_id = {k["id"]: k for k in puntos}
    tenidos: set[int] = set()
    sin_vinculo: list[dict[str, Any]] = []
    renombradas: list[dict[str, Any]] = []                      # linked to a KMZ point that now has another name: the KMZ was edited after the mufa was created
    for e in elementos:
        enlace = ((e.get("ref_externa") or {}).get("kmz") or {}).get("kmz_punto_id")
        if enlace in por_id and enlace not in tenidos:
            tenidos.add(enlace)
            k = por_id[enlace]
            # the name the KMZ point had when the mufa was linked: if the KMZ still calls it that, a different name in the zone is the person's own rename (kept);
            # only a point whose name changed since is offered (a link without that name is compared with the mufa's own name)
            visto = ((e.get("ref_externa") or {}).get("kmz") or {}).get("nombre") or e["nombre"]
            if _plano(k["nombre"]) != _plano(visto) and _plano(k["nombre"]) != _plano(e["nombre"]):
                renombradas.append({"elemento_id": e["id"], "version": e["version"], "nombre": e["nombre"], "kmz_id": k["id"], "nombre_kmz": k["nombre"]})
        else:
            sin_vinculo.append(e)
    for e in sin_vinculo:                                       # by name: the nearest KMZ point with it that nobody has yet
        if e["lat"] is None:
            continue
        candidatos = sorted(((_metros(e["lat"], e["lon"], k["lat"], k["lon"]), k) for k in puntos if k["id"] not in tenidos and _plano(k["nombre"]) == _plano(e["nombre"])),
                            key=lambda c: c[0])
        if candidatos and candidatos[0][0] <= RADIO_KMZ_M:
            tenidos.add(candidatos[0][1]["id"])
            e["_tiene"] = True
    libres = [e for e in sin_vinculo if not e.get("_tiene") and e["lat"] is not None]
    nuevas = []
    for k in sorted((k for k in puntos if k["id"] not in tenidos), key=lambda k: (_plano(k["nombre"]), k["id"])):
        cercanas = sorted(((_metros(k["lat"], k["lon"], e["lat"], e["lon"]), e) for e in libres), key=lambda c: c[0])
        cercana = None
        if cercanas and cercanas[0][0] <= RADIO_RENOMBRADA_M:
            d, e = cercanas[0]
            cercana = {"id": e["id"], "nombre": e["nombre"], "distancia_m": round(d, 1)}
        nuevas.append({"kmz_id": k["id"], "nombre": k["nombre"], "categoria": (k.get("categoria") or "").lower(), "lat": float(k["lat"]), "lon": float(k["lon"]), "cercana": cercana})
    return {"nuevas": nuevas, "nombres_cambiados": sorted(renombradas, key=lambda r: (_plano(r["nombre"]), r["elemento_id"])), "en_zona": len(elementos), "en_kmz": len(puntos), "proyecto_id": p["id"]}


def _poner_nombre(con: Any, actor: dict[str, Any], proyecto_id: int, elemento_id: int, nombre: str, version: int, kmz_id: int | None = None) -> dict[str, Any]:
    """Renames a mufa / node of the zone (and the name of its KMZ link, when it follows the KMZ). Inside the caller's transaction."""
    e = con.execute("SELECT id, nombre, version, ref_externa, proyecto_id, estado_migracion FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(elemento_id),)).fetchone()
    if e is None or e["proyecto_id"] != proyecto_id:
        raise DatosInvalidos({"mufa": "La mufa no es de esta zona"})
    nuevo = " ".join(str(nombre or "").split())[:160]
    if not nuevo:
        raise DatosInvalidos({"nombre": "Escriba el nombre"})
    valores: dict[str, Any] = {"nombre": nuevo}
    if e["estado_migracion"] is not None:
        valores["estado_migracion"] = "editada"
    if kmz_id is not None and ((e["ref_externa"] or {}).get("kmz") or {}).get("kmz_punto_id") == kmz_id:
        valores["ref_externa"] = Jsonb({**e["ref_externa"], "kmz": {**e["ref_externa"]["kmz"], "nombre": nuevo}})
    try:
        antes, despues = repositorio.actualizar(con, "elementos", e["id"], version, valores, actor["id"])
    except ConflictoVersion:
        raise ConflictoVersion(f"«{e['nombre']}» cambió mientras usted decidía. Recargue la lista.") from None
    repositorio.registrar(con, actor["id"], "elemento", e["id"], "editar", {"nombre": [antes["nombre"], despues["nombre"]]}, proyecto_id=proyecto_id)
    return {"id": e["id"], "nombre": despues["nombre"], "version": despues["version"]}


def renombrar_elemento(con: Any, actor: dict[str, Any], *, proyecto_id: int, elemento_id: int, nombre: str, version: int | None = None) -> dict[str, Any]:
    """Changes the name of a mufa / node of the zone from its schema (the name was set when it was created from the KMZ, and the KMZ may have changed since).
    Its place, cables and connections are not touched. {"elemento": {id, nombre, version}}."""
    p = _editable(con, actor, proyecto_id)
    fila = con.execute("SELECT version, tipo FROM redes.elementos WHERE id = %s AND borrado_en IS NULL AND proyecto_id = %s", (int(elemento_id), p["id"])).fetchone()
    if fila is None or fila["tipo"] not in TIPOS:
        raise DatosInvalidos({"mufa": "La mufa no es de esta zona"})
    with con.transaction():
        return {"elemento": _poner_nombre(con, actor, p["id"], int(elemento_id), nombre, int(version if version is not None else fila["version"]))}


def aplicar_mufas_kmz(con: Any, actor: dict[str, Any], *, proyecto_id: int, acciones: list[dict[str, Any]], kmz: Any = None) -> dict[str, Any]:
    """Applies what the person chose from `mufas_kmz`: `agregar` creates the mufa in the zone at the KMZ point (name and place of the KMZ, linked to it); `renombrar`
    (with `elemento_id`) gives the existing mufa the name of the KMZ point and links it (its own coordinate is not touched: its cables are anchored to it).
    Returns the new list of what is missing. All or nothing."""
    p = _editable(con, actor, proyecto_id)
    acciones = [a for a in (acciones or []) if isinstance(a, dict)]
    if not acciones:
        raise DatosInvalidos({"acciones": "No hay nada que aplicar"})
    if len(acciones) > 500:
        raise DatosInvalidos({"acciones": "Demasiadas mufas en un solo paso (máximo 500)"})
    pendiente = mufas_kmz(con, actor, proyecto_id=p["id"], kmz=kmz)           # what is still missing / changed now, read again (not what the page remembers)
    actual = {n["kmz_id"]: n for n in pendiente["nuevas"]}
    cambios = {r["elemento_id"]: r for r in pendiente["nombres_cambiados"]}
    hechas = {"agregadas": 0, "renombradas": 0, "nombres_actualizados": 0}
    with con.transaction():
        for a in acciones:
            if a.get("accion") == "actualizar_nombre":                      # the KMZ renamed the mufa: the zone follows
                c = cambios.get(int(a.get("elemento_id") or 0))
                if c is None:
                    raise DatosInvalidos({"mufa": "Esa mufa ya tiene el nombre del KMZ (o dejó de estar vinculada). Revise la lista."})
                _poner_nombre(con, actor, p["id"], c["elemento_id"], c["nombre_kmz"], int(a.get("version") if a.get("version") is not None else c["version"]), kmz_id=c["kmz_id"])
                hechas["nombres_actualizados"] += 1
                continue
            n = actual.get(int(a.get("kmz_id") or 0))
            if n is None:
                raise DatosInvalidos({"mufa": f"La mufa {a.get('kmz_id')} ya no falta en la zona (otra persona la agregó o el KMZ cambió). Revise la lista."})
            vinculo = {"kmz": {"kmz_punto_id": n["kmz_id"], "nombre": n["nombre"], "categoria": n["categoria"], "distancia_m": 0.0}}
            if a.get("accion") == "renombrar":
                e = con.execute("SELECT id, nombre, version, ref_externa, proyecto_id FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(a.get("elemento_id") or 0),)).fetchone()
                if e is None or e["proyecto_id"] != p["id"]:
                    raise DatosInvalidos({"mufa": "La mufa que se quiere renombrar no es de esta zona"})
                try:
                    antes, despues = repositorio.actualizar(con, "elementos", e["id"], int(a.get("version") if a.get("version") is not None else e["version"]),
                                                            {"nombre": n["nombre"][:160], "ref_externa": Jsonb({**(e["ref_externa"] or {}), **vinculo}), "estado_migracion": "editada"},
                                                            actor["id"])
                except ConflictoVersion:
                    raise ConflictoVersion(f"«{e['nombre']}» cambió mientras usted decidía. Revise la lista.") from None
                repositorio.registrar(con, actor["id"], "elemento", e["id"], "editar", {"nombre": [antes["nombre"], despues["nombre"]]}, proyecto_id=p["id"])
                hechas["renombradas"] += 1
            else:
                tipo, subtipo = FAMILIA_KMZ.get(n["categoria"], ("mufa", "empalme"))
                fila = repositorio.insertar(con, "elementos", {
                    "proyecto_id": p["id"], "tipo": tipo, "subtipo": subtipo, "nombre": n["nombre"][:160], "ubicacion": f"SRID=4326;POINT({n['lon']:.8f} {n['lat']:.8f})",
                    "ref_externa": Jsonb(vinculo), "ubicacion_fuente": "real", "fuente": "kmz", "confianza": "alta"}, actor["id"])
                repositorio.registrar(con, actor["id"], "elemento", fila["id"], "crear", {"nombre": [None, n["nombre"]], "origen": [None, "KMZ"]}, proyecto_id=p["id"])
                hechas["agregadas"] += 1
    return {**hechas, **mufas_kmz(con, actor, proyecto_id=p["id"], kmz=kmz)}
