"""Importar un KMZ a la red desde el programa (visor v2, fase 5): leer, comparar, revisar, aplicar, publicar y revertir.

Dos modos:
  - «nueva»: una ruta o elementos nuevos (todo lo que no está en la red es nuevo; lo que falta en el archivo no se toca);
  - «actualizacion»: un KMZ completo como RED_DE_IDEAY.kmz: además se detecta lo que ya no viene en el archivo (eliminado).

Al importar se compara cada elemento del archivo con la red actual (el KMZ vigente con sus cambios de kmz_cambios y lo que ya se importó)
y se clasifica: NUEVO (no hay ninguno con ese nombre cerca en esa carpeta), MODIFICADO (el mismo elemento con otra posición, trazo,
descripción o nombre), SIN CAMBIOS (solo se cuenta) y ELIMINADO (está en la red y no en el archivo; solo en «actualizacion»). Nada se
cambia todavía: queda una importación «pendiente» para revisar (aceptar o rechazar cada cambio o grupos enteros).

Aplicar deja lo modificado / eliminado de un elemento del KMZ en `kmz_cambios` (el archivo KMZ no se modifica) y lo nuevo como capa
«Importados»; todo guarda lo que había antes y se puede **revertir** (la última aplicada). Publicar (solo administradores) pasa lo aplicado a
`red_puntos` / `red_lineas` de la base del presupuesto con `tabla_origen = 'visor'`, guardando lo que había para poder revertirlo.
"""
import base64
import hashlib
import io
import json
import logging
import math
import re
import unicodedata
import zipfile
from typing import Any

from lxml import etree
from psycopg.types.json import Jsonb

from visor_rutas import kmz_capas, subidas
from visor_rutas.redes import lugares_kmz, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

log = logging.getLogger(__name__)

TOL_NOMBRE_M = 300.0          # same folder and name: the same element if it is within this distance
MOVIDO_M = 1.5                # a point / vertex that moved less than this has not changed
TOL_RENOMBRE_M = 2.0          # no name match: a point this close, in the same folder, is the same element (renamed)
TOL_LINEA_RENOMBRE_M = 3.0    # idem for lines: both ends this close
CELDA = 2e-5                  # grid of the point index (~2.2 m)
MAX_FILAS = 60_000
MAX_ELEMENTOS_MAPA = 3000
UMBRAL_ACTUALIZACION = 0.5    # this share of the file already in the network: it is an update, not a new route
UMBRAL_ELIMINADOS = 0.2       # more removed than this share of the network: a warning
CLASES = ("nuevo", "modificado", "eliminado")
TIPOS = {"punto": "punto", "linea": "linea", "poligono": "poligono"}


# --------------------------------------------------------------------------- texto y geometría

def normal(texto: Any) -> str:
    """Same as `normal` of web/lugares/kmz_cambios.js: no accents, lower case, spaces collapsed."""
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(t.lower().split())


def clave_kmz(ruta: str, nombre: str, lat: float | None, lon: float | None) -> str:
    """What identifies an element of the KMZ for kmz_cambios (the page builds the same text)."""
    ll = f"{lat:.5f},{lon:.5f}" if lat is not None and lon is not None else ""
    return f"{ruta}|{normal(nombre)}|{ll}"


def _distancia(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(min(1.0, a)))


def _simple(geo: dict[str, Any] | None) -> dict[str, Any] | None:
    """One Point / LineString / MultiLineString / Polygon from whatever the KML had (a collection keeps its first usable part)."""
    if not geo:
        return None
    t = geo.get("type")
    if t == "MultiPoint":
        return {"type": "Point", "coordinates": geo["coordinates"][0]} if geo.get("coordinates") else None
    if t == "GeometryCollection":
        for g in geo.get("geometries") or []:
            s = _simple(g)
            if s:
                return s
        return None
    return geo if t in ("Point", "LineString", "MultiLineString", "Polygon") else None


def _tipo(geo: dict[str, Any]) -> str:
    return "punto" if geo["type"] == "Point" else ("poligono" if geo["type"] == "Polygon" else "linea")


def _lineas(geo: dict[str, Any]) -> list[list[list[float]]]:
    t = geo["type"]
    if t == "LineString":
        return [geo["coordinates"]]
    if t == "MultiLineString":
        return geo["coordinates"]
    if t == "Polygon":
        return geo["coordinates"][:1]
    return []


def primero(geo: dict[str, Any]) -> tuple[float, float] | None:
    """(lat, lon) of the first point of a geometry (the page does the same to build the key)."""
    if geo["type"] == "Point":
        c = geo["coordinates"]
    else:
        ls = _lineas(geo)
        if not ls or not ls[0]:
            return None
        c = ls[0][0]
    return (c[1], c[0])


def _extremos(geo: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    ls = [l for l in _lineas(geo) if l]
    if not ls:
        return None
    a, b = ls[0][0], ls[-1][-1]
    return (a[1], a[0]), (b[1], b[0])


def _distancia_geom(f: dict[str, Any], a: dict[str, Any]) -> float:
    """Meters between two elements of the same kind: points, or the ends of lines (either direction)."""
    if f["tipo"] != a["tipo"]:
        return math.inf
    if f["tipo"] == "punto":
        p, q = primero(f["geom"]), primero(a["geom"])
        return _distancia(*p, *q) if p and q else math.inf
    e1, e2 = _extremos(f["geom"]), _extremos(a["geom"])
    if not e1 or not e2:
        return math.inf
    directo = max(_distancia(*e1[0], *e2[0]), _distancia(*e1[1], *e2[1]))
    inverso = max(_distancia(*e1[0], *e2[1]), _distancia(*e1[1], *e2[0]))
    return min(directo, inverso)


def _mismo_trazo(g1: dict[str, Any], g2: dict[str, Any]) -> bool:
    if g1["type"] == "Point" and g2["type"] == "Point":
        return _distancia(*primero(g1), *primero(g2)) <= MOVIDO_M
    l1, l2 = _lineas(g1), _lineas(g2)
    if len(l1) != len(l2):
        return False
    for a, b in zip(l1, l2):
        if len(a) != len(b):
            return False
        directo = max((_distancia(p[1], p[0], q[1], q[0]) for p, q in zip(a, b)), default=0)
        inverso = max((_distancia(p[1], p[0], q[1], q[0]) for p, q in zip(a, reversed(b))), default=0)
        if min(directo, inverso) > MOVIDO_M:
            return False
    return True


def _texto_desc(html: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split()).lower()


# --------------------------------------------------------------------------- leer el archivo

def leer(crudo: bytes) -> list[dict[str, Any]]:
    """The elements of a .kmz / .kml: [{ruta, nombre, tipo, geom, desc}] with `ruta` as the page and kmz_capas name the folders."""
    if crudo[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(crudo)) as z:
                nombres = z.namelist()
                kml = next((n for n in nombres if n.lower() == "doc.kml"), None) or next((n for n in nombres if n.lower().endswith(".kml")), None)
                if kml is None:
                    raise DatosInvalidos({"archivo": "El KMZ no trae ningún KML"})
                crudo = z.read(kml)
        except zipfile.BadZipFile:
            raise DatosInvalidos({"archivo": "El KMZ está dañado"}) from None
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
    raiz = etree.fromstring(crudo, parser)
    if raiz is None:
        raise DatosInvalidos({"archivo": "El KML no es válido"})
    local = kmz_capas._local
    documento = next((e for e in raiz.iter() if local(e) == "Document"), raiz)
    salida: list[dict[str, Any]] = []

    def recorrer(nodo: Any, ruta: list[str]) -> None:
        nombre = kmz_capas._texto(nodo, "name") or ("(sin nombre)" if local(nodo) == "Folder" else "Documento")
        ruta_nodo = ruta + [nombre]
        for hijo in nodo:
            etiqueta = local(hijo) if isinstance(hijo.tag, str) else ""
            if etiqueta in ("Folder", "Document"):
                recorrer(hijo, ruta_nodo)
            elif etiqueta == "Placemark":
                geo = _simple(kmz_capas._geometria(hijo))
                if geo is None:
                    continue
                desc, _ = kmz_capas.limpiar_descripcion(kmz_capas._texto(hijo, "description"))
                salida.append({"ruta": "/".join(ruta_nodo), "nombre": kmz_capas._texto(hijo, "name"), "tipo": _tipo(geo), "geom": geo, "desc": desc})

    recorrer(documento, [])
    return salida


# --------------------------------------------------------------------------- la red actual

def _cambios_vigentes(con: Any) -> dict[str, dict[str, Any]]:
    filas = con.execute("SELECT id, clave, accion, antes, despues, version FROM redes.kmz_cambios WHERE borrado_en IS NULL").fetchall()
    return {f["clave"]: dict(f) for f in filas}


def actuales_kmz(con: Any) -> list[dict[str, Any]]:
    """The KMZ in force: the cache of kmz_capas with the changes of kmz_cambios applied (renamed, moved, removed)."""
    arbol_json = kmz_capas.CARPETA_DATOS / "arbol.json"
    if not arbol_json.is_file():
        return []
    arbol = json.loads(arbol_json.read_text(encoding="utf-8"))
    cambios = _cambios_vigentes(con)
    salida: list[dict[str, Any]] = []
    for c in arbol["carpetas"].values():
        if not c.get("directos"):
            continue
        archivo = kmz_capas.CARPETA_DATOS / "capas" / f"{c['id']}.geojson"
        if not archivo.is_file():
            continue
        for f in json.loads(archivo.read_text(encoding="utf-8"))["features"]:
            geo = _simple(f.get("geometry"))
            if geo is None:
                continue
            p = f.get("properties") or {}
            ll = primero(geo)
            nombre = p.get("n") or ""
            clave = clave_kmz(c["ruta"], nombre or c["nombre"], ll[0] if ll else None, ll[1] if ll else None)
            elemento = {"origen": "kmz", "ruta": c["ruta"], "nombre": nombre, "tipo": _tipo(geo), "geom": geo, "desc": p.get("d", ""),
                        "clave": clave, "original": {"nombre": nombre or c["nombre"], "geom": geo}}
            ch = cambios.get(clave)
            if ch and ch["accion"] == "borrar":
                continue
            if ch and ch["accion"] == "editar" and ch["despues"]:
                d = ch["despues"]
                if d.get("nombre"):
                    elemento["nombre"] = d["nombre"]
                if d.get("lat") is not None and geo["type"] == "Point":
                    elemento["geom"] = {"type": "Point", "coordinates": [d["lon"], d["lat"]]}
                if d.get("coords") and geo["type"] in ("LineString", "MultiLineString"):
                    elemento["geom"] = {"type": "LineString", "coordinates": d["coords"]}
                if d.get("descripcion") is not None:
                    elemento["desc"] = d["descripcion"]
            salida.append(elemento)
    return salida


def elementos_importados(con: Any) -> list[dict[str, Any]]:
    """What the applied imports added to the network (new and modified elements), in the order they were applied."""
    filas = con.execute(
        "SELECT d.id, d.clase, d.carpeta, d.nombre, d.tipo, d.geom_nueva, d.props, d.descripcion, i.id AS importacion_id, i.archivo "
        "FROM redes.kmz_importacion_detalle d JOIN redes.kmz_importaciones i ON i.id = d.importacion_id "
        "WHERE i.estado = 'aplicada' AND i.borrado_en IS NULL AND d.aplicado AND (d.clase <> 'eliminado' OR i.modo = 'actualizacion') ORDER BY i.id, d.id").fetchall()
    vigentes: dict[int, dict[str, Any]] = {}
    for f in filas:
        ref = (f["props"] or {}).get("ref_detalle")
        if f["clase"] in ("modificado", "eliminado") and ref:
            vigentes.pop(int(ref), None)                      # it replaces / removes an element of an earlier import
        if f["clase"] in ("nuevo", "modificado") and (f["clase"] == "nuevo" or ref):
            vigentes[f["id"]] = {"id": f["id"], "carpeta": f["carpeta"], "nombre": f["nombre"], "tipo": f["tipo"], "geom": f["geom_nueva"],
                                 "desc": f["descripcion"] or "", "importacion_id": f["importacion_id"], "archivo": f["archivo"]}
    return list(vigentes.values())


def actuales(con: Any) -> list[dict[str, Any]]:
    lista = actuales_kmz(con)
    for e in elementos_importados(con):
        lista.append({"origen": "importado", "ruta": e["carpeta"], "nombre": e["nombre"], "tipo": e["tipo"], "geom": e["geom"], "desc": e["desc"],
                      "ref_detalle": e["id"], "original": {"nombre": e["nombre"], "geom": e["geom"]}})
    return lista


# --------------------------------------------------------------------------- comparar

def _celda(lat: float, lon: float) -> tuple[int, int]:
    return (round(lat / CELDA), round(lon / CELDA))


def comparar(items: list[dict[str, Any]], vigentes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(rows to review, counts). Rows: nuevo / modificado / eliminado; the ones that did not change are only counted."""
    por_nombre: dict[tuple[str, str], list[int]] = {}
    for i, a in enumerate(vigentes):
        n = normal(a["nombre"])
        if n:
            por_nombre.setdefault((normal(a["ruta"]), n), []).append(i)
    pareja: dict[int, int] = {}               # file index -> current index
    tomados: set[int] = set()
    # 1) same folder and name: the closest ones first (a name can repeat)
    pares: list[tuple[float, int, int]] = []
    for fi, f in enumerate(items):
        n = normal(f["nombre"])
        if not n:
            continue
        for ai in por_nombre.get((normal(f["ruta"]), n), []):
            d = _distancia_geom(f, vigentes[ai])
            if d <= TOL_NOMBRE_M:
                pares.append((d, fi, ai))
    for d, fi, ai in sorted(pares):
        if fi not in pareja and ai not in tomados:
            pareja[fi] = ai
            tomados.add(ai)
    # 2) no name match: the same place in the same folder is the same element (it was renamed)
    puntos: dict[tuple[str, int, int], list[int]] = {}
    extremos: dict[tuple[str, int, int], list[int]] = {}
    for ai, a in enumerate(vigentes):
        if ai in tomados:
            continue
        ruta = normal(a["ruta"])
        if a["tipo"] == "punto":
            p = primero(a["geom"])
            if p:
                puntos.setdefault((ruta, *_celda(*p)), []).append(ai)
        else:
            e = _extremos(a["geom"])
            if e:
                for extremo in e:
                    extremos.setdefault((ruta, *_celda(*extremo)), []).append(ai)
    for fi, f in enumerate(items):
        if fi in pareja:
            continue
        ruta = normal(f["ruta"])
        if f["tipo"] == "punto":
            p = primero(f["geom"])
            claves = [(ruta, p_[0] + dx, p_[1] + dy) for p_ in [_celda(*p)] for dx in (-1, 0, 1) for dy in (-1, 0, 1)] if p else []
            indice, tolerancia = puntos, TOL_RENOMBRE_M
        else:
            e = _extremos(f["geom"])
            claves = [(ruta, c[0] + dx, c[1] + dy) for c in ([_celda(*e[0])] if e else []) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
            indice, tolerancia = extremos, TOL_LINEA_RENOMBRE_M
        mejor: tuple[float, int] | None = None
        for k in claves:
            for ai in indice.get(k, []):
                if ai in tomados:
                    continue
                d = _distancia_geom(f, vigentes[ai])
                if d <= tolerancia and (mejor is None or d < mejor[0]):
                    mejor = (d, ai)
        if mejor:
            pareja[fi] = mejor[1]
            tomados.add(mejor[1])
    # classify
    filas: list[dict[str, Any]] = []
    carpetas: dict[str, dict[str, int]] = {}
    por_clase = {"nuevo": 0, "modificado": 0, "sin_cambios": 0, "eliminado": 0}
    por_tipo: dict[str, dict[str, int]] = {}

    def contar(clase: str, ruta: str, tipo: str) -> None:
        por_clase[clase] += 1
        carpetas.setdefault(ruta, {}).setdefault(clase, 0)
        carpetas[ruta][clase] += 1
        por_tipo.setdefault(tipo, {}).setdefault(clase, 0)
        por_tipo[tipo][clase] += 1

    for fi, f in enumerate(items):
        nombre = f["nombre"] or f["ruta"].rsplit("/", 1)[-1]
        if fi not in pareja:
            filas.append({"clase": "nuevo", "carpeta": f["ruta"], "nombre": nombre, "tipo": f["tipo"], "geom_nueva": f["geom"], "geom_actual": None,
                          "descripcion": f["desc"], "props": {}, "aceptado": True})
            contar("nuevo", f["ruta"], f["tipo"])
            continue
        a = vigentes[pareja[fi]]
        cambios = []
        if normal(f["nombre"]) != normal(a["nombre"]):
            cambios.append("nombre")
        if not _mismo_trazo(f["geom"], a["geom"]):
            cambios.append("posicion" if f["tipo"] == "punto" else "trazo")
        if _texto_desc(f["desc"]) != _texto_desc(a["desc"]):
            cambios.append("descripcion")
        if not cambios:
            contar("sin_cambios", f["ruta"], f["tipo"])
            continue
        props: dict[str, Any] = {"cambios": cambios, "origen": a["origen"], "nombre_actual": a["nombre"] or a["ruta"].rsplit("/", 1)[-1]}
        if f["tipo"] == "punto":
            props["dist_m"] = round(_distancia_geom(f, a), 1)
        if a["origen"] == "kmz":
            props.update(clave=a["clave"], original={"nombre": a["original"]["nombre"], "geom": a["original"]["geom"]})
        else:
            props["ref_detalle"] = a["ref_detalle"]
        filas.append({"clase": "modificado", "carpeta": f["ruta"], "nombre": nombre, "tipo": f["tipo"], "geom_nueva": f["geom"], "geom_actual": a["geom"],
                      "descripcion": f["desc"], "props": props, "aceptado": True})
        contar("modificado", f["ruta"], f["tipo"])
    for ai, a in enumerate(vigentes):
        if ai in tomados:
            continue
        props = {"origen": a["origen"]}
        if a["origen"] == "kmz":
            props.update(clave=a["clave"], original={"nombre": a["original"]["nombre"], "geom": a["original"]["geom"]})
        else:
            props["ref_detalle"] = a["ref_detalle"]
        filas.append({"clase": "eliminado", "carpeta": a["ruta"], "nombre": a["nombre"] or a["ruta"].rsplit("/", 1)[-1], "tipo": a["tipo"], "geom_nueva": None,
                      "geom_actual": a["geom"], "descripcion": a["desc"], "props": props, "aceptado": False})
        contar("eliminado", a["ruta"], a["tipo"])
    top = sorted(carpetas.items(), key=lambda kv: -sum(kv[1].values()))[:400]
    return filas, {"por_clase": por_clase, "por_tipo": por_tipo, "carpetas": dict(top), "elementos_archivo": len(items), "elementos_red": len(vigentes)}


def sugerir_modo(conteos: dict[str, Any]) -> str:
    """«actualizacion» when a good share of the file is already in the network; a route that is all new is «nueva»."""
    total = conteos["elementos_archivo"]
    ya_estan = conteos["por_clase"]["modificado"] + conteos["por_clase"]["sin_cambios"]
    return "actualizacion" if total and ya_estan / total >= UMBRAL_ACTUALIZACION else "nueva"


def _avisos(conteos: dict[str, Any], modo: str) -> list[str]:
    avisos = []
    red = conteos["elementos_red"]
    if not red:
        avisos.append("No hay una red KMZ cargada en el servidor con la que comparar: todo se ve como nuevo")
    eliminados = conteos["por_clase"]["eliminado"]
    if modo == "actualizacion" and red and eliminados / red > UMBRAL_ELIMINADOS:
        avisos.append(f"El archivo no trae {eliminados:,} elementos de la red ({eliminados / red:.0%}): revise que sea el KMZ completo antes de aceptar los eliminados")
    return avisos


# --------------------------------------------------------------------------- importar y revisar

def _exigir_editor(actor: dict[str, Any]) -> None:
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede importar un KMZ a la red")


def _publica(f: Any) -> dict[str, Any]:
    d = {k: f[k] for k in ("id", "archivo", "md5", "modo", "modo_sugerido", "estado", "conteos", "publicada", "version")}
    d["aplicada_en"] = f["aplicada_en"].isoformat() if f["aplicada_en"] else None
    d["creado_en"] = f["creado_en"].isoformat() if f["creado_en"] else None
    d["publicada_en"] = f["publicada_en"].isoformat() if f["publicada_en"] else None
    d["publicacion"] = {k: v for k, v in (f["publicacion"] or {}).items() if k in ("resumen",)} or None
    return d


def _importacion(con: Any, id_: int, *, bloquear: bool = False) -> Any:
    f = con.execute("SELECT * FROM redes.kmz_importaciones WHERE id = %s AND borrado_en IS NULL" + (" FOR UPDATE" if bloquear else ""), (int(id_),)).fetchone()
    if f is None:
        raise NoEncontrado("La importación ya no existe")
    return f


def importar(con: Any, actor: dict[str, Any], *, datos: str = "", nombre: str = "", modo: str | None = None, subida_id: str | None = None) -> dict[str, Any]:
    """Reads the KMZ / KML, compares it with the network and keeps the result as a pending import to review. The file comes as base64 (`datos`) or,
    for a big one, as the id of a finished upload by parts (`subida_id`, visor_rutas/subidas.py)."""
    _exigir_editor(actor)
    if subida_id:
        try:
            nombre_subido, crudo = subidas.almacen.tomar(subida_id)
        except subidas.ErrorSubida as exc:
            raise DatosInvalidos({"archivo": str(exc)}) from None
        nombre = nombre or nombre_subido
    else:
        try:
            crudo = base64.b64decode(str(datos or ""), validate=True)
        except (ValueError, TypeError):
            raise DatosInvalidos({"archivo": "El archivo no se pudo leer"}) from None
    if not crudo or len(crudo) > lugares_kmz.MAX_ARCHIVO:
        raise DatosInvalidos({"archivo": f"El archivo debe pesar hasta {lugares_kmz.MAX_ARCHIVO // (1024 * 1024)} MB"})
    if modo not in (None, "nueva", "actualizacion"):
        raise DatosInvalidos({"modo": "Modo no válido"})
    items = leer(crudo)
    if not items:
        raise DatosInvalidos({"archivo": "El archivo no trae puntos ni líneas que importar"})
    filas, conteos = comparar(items, actuales(con))
    if len(filas) > MAX_FILAS:
        raise DatosInvalidos({"archivo": f"El archivo cambia demasiados elementos para revisarlos aquí ({len(filas):,}; máximo {MAX_FILAS:,})"})
    sugerido = sugerir_modo(conteos)
    modo = modo or sugerido
    conteos["avisos"] = _avisos(conteos, modo)
    with con.transaction():
        fila = repositorio.insertar(con, "kmz_importaciones", {"archivo": " ".join(str(nombre or "").split())[:200] or "importado.kmz", "md5": hashlib.md5(crudo).hexdigest(),
                                                              "modo": modo, "modo_sugerido": sugerido, "conteos": Jsonb(conteos)}, actor["id"])
        with con.cursor() as cur:
            cur.executemany(
                "INSERT INTO redes.kmz_importacion_detalle (importacion_id, clase, carpeta, nombre, tipo, geom_nueva, geom_actual, descripcion, props, aceptado) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(fila["id"], f["clase"], f["carpeta"][:600], f["nombre"][:300], f["tipo"], Jsonb(f["geom_nueva"]) if f["geom_nueva"] else None,
                  Jsonb(f["geom_actual"]) if f["geom_actual"] else None, f["descripcion"] or None, Jsonb(f["props"]), f["aceptado"]) for f in filas])
        repositorio.registrar(con, actor["id"], "kmz_importacion", fila["id"], "crear", {"archivo": [None, fila["archivo"]], "modo": [None, modo]})
    log.info("KMZ import %s: %d elements, %s", fila["archivo"], len(items), conteos["por_clase"])
    return {"importacion": _publica(fila)}


def listar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """The history of imports (newest first)."""
    filas = con.execute("SELECT i.*, u.nombre AS usuario FROM redes.kmz_importaciones i LEFT JOIN redes.usuarios u ON u.id = i.creado_por "
                        "WHERE i.borrado_en IS NULL ORDER BY i.id DESC LIMIT 100").fetchall()
    ultima = con.execute("SELECT max(id) AS m FROM redes.kmz_importaciones WHERE estado = 'aplicada' AND borrado_en IS NULL").fetchone()["m"]
    return {"importaciones": [{**_publica(f), "usuario": f["usuario"], "es_ultima_aplicada": f["id"] == ultima} for f in filas]}


def _filtro(id_: int, clase: str | None, carpeta: str | None, texto: str | None, aceptado: bool | None, modo: str) -> tuple[str, list[Any]]:
    donde, args = ["importacion_id = %s"], [int(id_)]
    if modo != "actualizacion":
        donde.append("clase <> 'eliminado'")
    if clase in CLASES:
        donde.append("clase = %s")
        args.append(clase)
    if carpeta:
        donde.append("(carpeta = %s OR carpeta LIKE %s)")
        args += [carpeta, carpeta.rstrip("/") + "/%"]
    if texto:
        donde.append("lower(nombre) LIKE %s")
        args.append("%" + " ".join(str(texto).lower().split()) + "%")
    if aceptado is not None:
        donde.append("aceptado = %s")
        args.append(bool(aceptado))
    return " AND ".join(donde), args


def detalle(con: Any, actor: dict[str, Any], *, id: int, clase: str | None = None, carpeta: str | None = None, texto: str | None = None,
            aceptado: bool | None = None, limite: int = 200, desde: int = 0) -> dict[str, Any]:
    """A page of the rows to review (filtered), with the totals of the filter."""
    imp = _importacion(con, id)
    donde, args = _filtro(id, clase, carpeta, texto, aceptado, imp["modo"])
    limite = max(1, min(int(limite or 200), 500))
    filas = con.execute(f"SELECT id, clase, carpeta, nombre, tipo, geom_nueva, geom_actual, props, aceptado, aplicado FROM redes.kmz_importacion_detalle "
                        f"WHERE {donde} ORDER BY clase, carpeta, nombre, id LIMIT %s OFFSET %s", [*args, limite, max(0, int(desde or 0))]).fetchall()
    total = con.execute(f"SELECT count(*) AS n, count(*) FILTER (WHERE aceptado) AS aceptados FROM redes.kmz_importacion_detalle WHERE {donde}", args).fetchone()
    todo_donde, todo_args = _filtro(id, None, None, None, True, imp["modo"])
    aceptados_total = con.execute(f"SELECT count(*) AS n FROM redes.kmz_importacion_detalle WHERE {todo_donde}", todo_args).fetchone()["n"]
    return {"importacion": _publica(imp), "filas": [dict(f) for f in filas], "total": total["n"], "aceptados": total["aceptados"], "aceptados_total": aceptados_total}


def mapa(con: Any, actor: dict[str, Any], *, id: int, clase: str | None = None, carpeta: str | None = None, texto: str | None = None) -> dict[str, Any]:
    """The geometries of the filtered rows to draw them on the map (green new, orange modified, red removed), at most MAX_ELEMENTOS_MAPA."""
    imp = _importacion(con, id)
    donde, args = _filtro(id, clase, carpeta, texto, None, imp["modo"])
    filas = con.execute(f"SELECT id, clase, nombre, tipo, COALESCE(geom_nueva, geom_actual) AS geom, aceptado FROM redes.kmz_importacion_detalle "
                        f"WHERE {donde} ORDER BY id LIMIT %s", [*args, MAX_ELEMENTOS_MAPA + 1]).fetchall()
    return {"elementos": [dict(f) for f in filas[:MAX_ELEMENTOS_MAPA]], "truncado": len(filas) > MAX_ELEMENTOS_MAPA}


def aceptar(con: Any, actor: dict[str, Any], *, id: int, aceptado: bool, ids: list[int] | None = None, clase: str | None = None,
            carpeta: str | None = None, texto: str | None = None) -> dict[str, Any]:
    """Accept / reject rows: the given ids, or every row of a filter (a class, a folder, a text), or all of them."""
    _exigir_editor(actor)
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "pendiente":
        raise DatosInvalidos({"importacion": "Solo se puede cambiar lo que se acepta mientras la importación está pendiente"})
    with con.transaction():
        if ids is not None:
            if not isinstance(ids, list) or len(ids) > 5000:
                raise DatosInvalidos({"ids": "Lista de elementos no válida"})
            n = con.execute("UPDATE redes.kmz_importacion_detalle SET aceptado = %s WHERE importacion_id = %s AND id = ANY(%s)",
                            (bool(aceptado), int(id), [int(i) for i in ids])).rowcount
        else:
            donde, args = _filtro(id, clase, carpeta, texto, None, imp["modo"])
            n = con.execute(f"UPDATE redes.kmz_importacion_detalle SET aceptado = %s WHERE {donde}", [bool(aceptado), *args]).rowcount
    return {"cambiados": n, **detalle(con, actor, id=id, clase=clase, carpeta=carpeta, texto=texto, limite=1)}


def cambiar_modo(con: Any, actor: dict[str, Any], *, id: int, modo: str) -> dict[str, Any]:
    _exigir_editor(actor)
    if modo not in ("nueva", "actualizacion"):
        raise DatosInvalidos({"modo": "Modo no válido"})
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "pendiente":
        raise DatosInvalidos({"importacion": "El modo solo se cambia mientras la importación está pendiente"})
    conteos = dict(imp["conteos"])
    conteos["avisos"] = _avisos(conteos, modo)
    with con.transaction():
        repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"], {"modo": modo, "conteos": Jsonb(conteos)}, actor["id"])
    return {"importacion": _publica(_importacion(con, id))}


def descartar(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    _exigir_editor(actor)
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "pendiente":
        raise DatosInvalidos({"importacion": "Solo se descarta una importación pendiente (una aplicada se revierte)"})
    with con.transaction():
        repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"], {"estado": "descartada"}, actor["id"])
        con.execute("DELETE FROM redes.kmz_importacion_detalle WHERE importacion_id = %s", (imp["id"],))
        repositorio.registrar(con, actor["id"], "kmz_importacion", imp["id"], "eliminar", {"archivo": [imp["archivo"], None]})
    return {"id": imp["id"]}


# --------------------------------------------------------------------------- aplicar y revertir

def _tipo_cambio(tipo: str) -> str:
    return "punto" if tipo == "punto" else "linea"


def _despues(f: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"nombre": f["nombre"]}
    g = f["geom_nueva"]
    if f["tipo"] == "punto" and g:
        d.update(lat=g["coordinates"][1], lon=g["coordinates"][0])
    elif g:
        ls = _lineas(g)
        if ls:
            d["coords"] = ls[0]
    d["descripcion"] = f["descripcion"] or ""
    return d


def _antes_original(props: dict[str, Any], tipo: str) -> dict[str, Any]:
    o = props.get("original") or {}
    antes: dict[str, Any] = {"nombre": o.get("nombre") or ""}
    if tipo == "punto" and o.get("geom"):
        antes.update(lat=o["geom"]["coordinates"][1], lon=o["geom"]["coordinates"][0])
    return antes


def aplicar(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Applies what was accepted. New elements become the «Importados» layer; changes and removals of KMZ elements go to kmz_cambios, keeping
    what was there before so the import can be reverted."""
    _exigir_editor(actor)
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "pendiente":
        raise DatosInvalidos({"importacion": "Solo se aplica una importación pendiente"})
    filas = con.execute("SELECT * FROM redes.kmz_importacion_detalle WHERE importacion_id = %s AND aceptado AND (clase <> 'eliminado' OR %s) ORDER BY id",
                        (imp["id"], imp["modo"] == "actualizacion")).fetchall()
    if not filas:
        raise DatosInvalidos({"importacion": "No hay cambios aceptados que aplicar"})
    cuenta = {"nuevo": 0, "modificado": 0, "eliminado": 0}
    with con.transaction():
        for f in filas:
            props = dict(f["props"] or {})
            if f["clase"] in ("modificado", "eliminado") and props.get("origen") == "kmz":
                clave = props["clave"]
                previo = con.execute("SELECT id, accion, antes, despues, version, importacion_id FROM redes.kmz_cambios WHERE clave = %s AND borrado_en IS NULL FOR UPDATE",
                                     (clave,)).fetchone()
                accion = "borrar" if f["clase"] == "eliminado" else "editar"
                despues = None if accion == "borrar" else _despues(f)
                if previo:
                    props["cambio_previo"] = {"accion": previo["accion"], "despues": previo["despues"], "importacion_id": previo["importacion_id"]}
                    repositorio.actualizar(con, "kmz_cambios", previo["id"], previo["version"],
                                           {"accion": accion, "despues": Jsonb(despues) if despues else None, "publicado": False, "importacion_id": imp["id"]}, actor["id"])
                    props["cambio_id"] = previo["id"]
                else:
                    nuevo = repositorio.insertar(con, "kmz_cambios", {
                        "clave": clave, "carpeta": f["carpeta"], "nombre": (props.get("original") or {}).get("nombre") or f["nombre"], "tipo": _tipo_cambio(f["tipo"]),
                        "accion": accion, "antes": Jsonb(_antes_original(props, f["tipo"])), "despues": Jsonb(despues) if despues else None,
                        "publicado": False, "importacion_id": imp["id"]}, actor["id"])
                    props["cambio_id"] = nuevo["id"]
            cuenta[f["clase"]] += 1
            con.execute("UPDATE redes.kmz_importacion_detalle SET aplicado = true, props = %s WHERE id = %s", (Jsonb(props), f["id"]))
        repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"],
                               {"estado": "aplicada", "aplicada_en": con.execute("SELECT now() AS n").fetchone()["n"], "aplicada_por": actor["id"]}, actor["id"])
        repositorio.registrar(con, actor["id"], "kmz_importacion", imp["id"], "editar", {"estado": ["pendiente", "aplicada"], **{k: [None, v] for k, v in cuenta.items() if v}})
    log.info("KMZ import %s applied: %s", imp["archivo"], cuenta)
    return {"importacion": _publica(_importacion(con, id)), "aplicados": cuenta}


def revertir(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Undoes the LAST applied import: the changes of kmz_cambios go back to what they were and the new elements leave the layer."""
    _exigir_editor(actor)
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "aplicada":
        raise DatosInvalidos({"importacion": "Solo se revierte una importación aplicada"})
    ultima = con.execute("SELECT max(id) AS m FROM redes.kmz_importaciones WHERE estado = 'aplicada' AND borrado_en IS NULL").fetchone()["m"]
    if ultima != imp["id"]:
        raise DatosInvalidos({"importacion": "Solo se puede revertir la última importación aplicada: antes hay que revertir las posteriores"})
    if imp["publicada"]:
        raise DatosInvalidos({"importacion": "La importación está publicada en el presupuesto: primero hay que revertir la publicación"})
    with con.transaction():
        for f in con.execute("SELECT id, props FROM redes.kmz_importacion_detalle WHERE importacion_id = %s AND aplicado AND props ? 'cambio_id' ORDER BY id DESC", (imp["id"],)).fetchall():
            props = f["props"]
            cambio = con.execute("SELECT id, version FROM redes.kmz_cambios WHERE id = %s AND borrado_en IS NULL FOR UPDATE", (int(props["cambio_id"]),)).fetchone()
            if cambio is None:
                continue
            previo = props.get("cambio_previo")
            if previo:
                repositorio.actualizar(con, "kmz_cambios", cambio["id"], cambio["version"],
                                       {"accion": previo["accion"], "despues": Jsonb(previo["despues"]) if previo["despues"] else None,
                                        "importacion_id": previo.get("importacion_id")}, actor["id"])
            else:
                con.execute("UPDATE redes.kmz_cambios SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], cambio["id"]))
        con.execute("UPDATE redes.kmz_importacion_detalle SET aplicado = false WHERE importacion_id = %s", (imp["id"],))
        repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"], {"estado": "revertida", "revertida_en": con.execute("SELECT now() AS n").fetchone()["n"]}, actor["id"])
        repositorio.registrar(con, actor["id"], "kmz_importacion", imp["id"], "editar", {"estado": ["aplicada", "revertida"]})
    return {"importacion": _publica(_importacion(con, id))}


def capa(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """The elements the applied imports added (the «Importados» layer of the page)."""
    return {"elementos": elementos_importados(con)}


# --------------------------------------------------------------------------- publicar en PostGIS (red_puntos / red_lineas)

TABLAS = {"punto": "red_puntos", "linea": "red_lineas"}
TOL_PUBLICAR_M = 50.0         # the row of red_puntos that is the element: its name and this close
TOL_PUBLICAR_RENOMBRADO_M = 1.5
TOL_PUBLICAR_LINEA = 0.0005   # degrees (~50 m) of Hausdorff distance between the line of the network and the element


def conectar_presupuesto() -> Any:
    """Connection to the BUDGET database (DB_*: where red_puntos / red_lineas are), in a transaction. Tests replace this function."""
    import psycopg
    from psycopg.rows import dict_row
    from config import get_settings
    s = get_settings()
    return psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password, connect_timeout=5, row_factory=dict_row)


def _categorias(pg: Any, tabla: str) -> dict[str, tuple[str, str]]:
    assert tabla in TABLAS.values()
    filas = pg.execute(f"SELECT categoria, mode() WITHIN GROUP (ORDER BY tipo) AS tipo FROM {tabla} WHERE categoria IS NOT NULL GROUP BY categoria").fetchall()
    return {normal(f["categoria"]): (f["categoria"], f["tipo"]) for f in filas}


def categoria_para(ruta: str, tabla: str, info: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """(categoria, tipo) of red_puntos / red_lineas for a KMZ folder, from the categories that already exist (the folder's own name, also in
    singular / plural). For points it also knows mufas, reservas and posts by their words. None: no equivalent, it is not published."""
    hoja = normal(ruta.rsplit("/", 1)[-1])
    for candidata in (hoja, hoja.rstrip("s"), hoja + "s", hoja[:-2] if hoja.endswith("es") else ""):
        if candidata and candidata in info:
            return info[candidata]
    if tabla != "red_puntos":
        return None
    if "mufa" in hoja:
        return info.get("mufa", ("mufa", "mufa"))
    if "reserva" in hoja:
        return info.get("reserva", ("reserva", "reserva"))
    if "poste" in hoja:
        tipo = ("poste de ideay" if "ideay" in hoja else "poste de madera" if "madera" in hoja else "poste de metal" if "metal" in hoja
                else "poste cliente" if "cliente" in hoja else "poste de concreto")
        return (hoja, tipo)
    return None


def _json(geom: dict[str, Any]) -> str:
    return json.dumps(geom, separators=(",", ":"))


def _buscar_fila(pg: Any, tabla: str, categoria: str, tipo: str, nombre: str, geom: dict[str, Any], es_punto: bool) -> Any:
    g = "ST_SetSRID(ST_GeomFromGeoJSON(%(g)s), 4326)"
    base = f"SELECT id, tabla_origen, categoria, nombre, descripcion, tipo, ST_AsText(geom) AS wkt FROM {tabla} WHERE (categoria = %(c)s OR tipo = %(t)s) AND "
    args = {"g": _json(geom), "c": categoria, "t": tipo, "n": normal(nombre)}
    if es_punto:
        for condicion, tolerancia in (("lower(nombre) = %(n)s", TOL_PUBLICAR_M), ("true", TOL_PUBLICAR_RENOMBRADO_M)):
            f = pg.execute(base + f"{condicion} AND ST_DWithin(geom::geography, {g}::geography, %(m)s) ORDER BY ST_Distance(geom::geography, {g}::geography) LIMIT 1",
                           {**args, "m": tolerancia}).fetchone()
            if f:
                return f
        return None
    return pg.execute(base + f"lower(nombre) = %(n)s AND ST_HausdorffDistance(geom, {g}) < %(h)s ORDER BY ST_HausdorffDistance(geom, {g}) LIMIT 1",
                      {**args, "h": TOL_PUBLICAR_LINEA}).fetchone()


def _texto_plano(html: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def _exigir_admin(actor: dict[str, Any]) -> None:
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede publicar en las tablas del presupuesto")


def _aplicar_a_presupuesto(pg: Any, filas: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Changes red_puntos / red_lineas inside an open transaction. Returns (snapshot to undo it, summary)."""
    info = {t: _categorias(pg, t) for t in TABLAS.values()}
    snap: dict[str, list[Any]] = {"insertados": [], "modificados": [], "eliminados": []}
    resumen: dict[str, Any] = {"insertados": 0, "modificados": 0, "eliminados": 0, "sin_categoria": [], "no_encontrados": [], "omitidos": 0}
    for f in filas:
        if f["tipo"] not in TABLAS:
            resumen["omitidos"] += 1
            continue
        tabla, es_punto = TABLAS[f["tipo"]], f["tipo"] == "punto"
        props = f["props"] or {}
        if f["clase"] == "nuevo":
            destino = categoria_para(f["carpeta"], tabla, info[tabla])
            if destino is None:
                resumen["sin_categoria"].append(f["carpeta"].rsplit("/", 1)[-1])
                continue
            nuevo = pg.execute(f"INSERT INTO {tabla} (tabla_origen, categoria, nombre, descripcion, geom, tipo) VALUES ('visor', %s, %s, %s, "
                               f"ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s) RETURNING id", (destino[0], f["nombre"], _texto_plano(f["descripcion"]) or None,
                                                                                              _json(f["geom_nueva"]), destino[1])).fetchone()
            snap["insertados"].append({"tabla": tabla, "id": nuevo["id"]})
            resumen["insertados"] += 1
            continue
        if props.get("origen") != "kmz" or not f["geom_actual"]:
            resumen["omitidos"] += 1                 # it replaces an element a former import added: not in red_* by this route
            continue
        destino = categoria_para(f["carpeta"], tabla, info[tabla])
        fila = _buscar_fila(pg, tabla, destino[0], destino[1], props.get("nombre_actual") or f["nombre"], f["geom_actual"], es_punto) if destino else None
        if fila is None:
            resumen["no_encontrados"].append(f["nombre"])
            continue
        anterior = {k: fila[k] for k in ("id", "tabla_origen", "categoria", "nombre", "descripcion", "tipo", "wkt")}
        if f["clase"] == "modificado":
            snap["modificados"].append({"tabla": tabla, "fila": anterior})
            pg.execute(f"UPDATE {tabla} SET nombre = %s, descripcion = %s, geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) WHERE id = %s",
                       (f["nombre"], _texto_plano(f["descripcion"]) or fila["descripcion"], _json(f["geom_nueva"]), fila["id"]))
            resumen["modificados"] += 1
        else:
            snap["eliminados"].append({"tabla": tabla, "fila": anterior})
            pg.execute(f"DELETE FROM {tabla} WHERE id = %s", (fila["id"],))
            resumen["eliminados"] += 1
    resumen["sin_categoria"] = sorted(set(resumen["sin_categoria"]))
    resumen["no_encontrados"] = resumen["no_encontrados"][:50]
    return snap, resumen


def _deshacer_en_presupuesto(pg: Any, snap: dict[str, Any]) -> None:
    for x in snap["insertados"]:
        pg.execute(f"DELETE FROM {x['tabla']} WHERE id = %s AND tabla_origen = 'visor'", (x["id"],))
    for x in snap["modificados"]:
        f = x["fila"]
        pg.execute(f"UPDATE {x['tabla']} SET nombre = %s, descripcion = %s, geom = ST_SetSRID(ST_GeomFromText(%s), 4326) WHERE id = %s", (f["nombre"], f["descripcion"], f["wkt"], f["id"]))
    for x in snap["eliminados"]:
        f = x["fila"]
        pg.execute(f"INSERT INTO {x['tabla']} (id, tabla_origen, categoria, nombre, descripcion, geom, tipo) VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 4326), %s) "
                   f"ON CONFLICT (id) DO NOTHING", (f["id"], f["tabla_origen"], f["categoria"], f["nombre"], f["descripcion"], f["wkt"], f["tipo"]))


def publicar(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Publishes an applied import in red_puntos / red_lineas (new: inserted with tabla_origen = 'visor'; modified: updated; removed: deleted),
    so the budget uses the new network. What was there is kept in the import to revert it. Administrators only."""
    _exigir_admin(actor)
    imp = _importacion(con, id, bloquear=True)
    if imp["estado"] != "aplicada":
        raise DatosInvalidos({"importacion": "Primero hay que aplicar la importación a la red"})
    if imp["publicada"]:
        raise DatosInvalidos({"importacion": "La importación ya está publicada"})
    filas = con.execute("SELECT * FROM redes.kmz_importacion_detalle WHERE importacion_id = %s AND aplicado AND (clase <> 'eliminado' OR %s) ORDER BY id",
                        (imp["id"], imp["modo"] == "actualizacion")).fetchall()
    pg = conectar_presupuesto()
    try:
        with pg.transaction():
            snap, resumen = _aplicar_a_presupuesto(pg, filas)
    finally:
        pg.close()
    try:
        with con.transaction():
            repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"],
                                   {"publicada": True, "publicada_en": con.execute("SELECT now() AS n").fetchone()["n"],
                                    "publicacion": Jsonb({"resumen": resumen, **snap})}, actor["id"])
            repositorio.registrar(con, actor["id"], "kmz_importacion", imp["id"], "editar",
                                  {"publicada": [False, True], **{k: [None, v] for k, v in resumen.items() if isinstance(v, int) and v}})
    except Exception:
        log.exception("KMZ import %s: could not record the publication; undoing it in red_puntos / red_lineas", imp["id"])
        pg = conectar_presupuesto()
        try:
            with pg.transaction():
                _deshacer_en_presupuesto(pg, snap)
        finally:
            pg.close()
        raise
    log.info("KMZ import %s published: %s", imp["archivo"], {k: v for k, v in resumen.items() if isinstance(v, int)})
    return {"importacion": _publica(_importacion(con, id)), "resumen": resumen}


def revertir_publicacion(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Takes a publication back: what it inserted is deleted, what it changed or deleted goes back as it was."""
    _exigir_admin(actor)
    imp = _importacion(con, id, bloquear=True)
    if not imp["publicada"] or not imp["publicacion"]:
        raise DatosInvalidos({"importacion": "La importación no está publicada"})
    snap = imp["publicacion"]
    pg = conectar_presupuesto()
    try:
        with pg.transaction():
            _deshacer_en_presupuesto(pg, snap)
    finally:
        pg.close()
    with con.transaction():
        repositorio.actualizar(con, "kmz_importaciones", imp["id"], imp["version"], {"publicada": False, "publicada_en": None, "publicacion": None}, actor["id"])
        repositorio.registrar(con, actor["id"], "kmz_importacion", imp["id"], "editar", {"publicada": [True, False]})
    return {"importacion": _publica(_importacion(con, id))}
