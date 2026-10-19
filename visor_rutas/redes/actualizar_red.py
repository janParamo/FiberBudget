"""Actualizar la red desde el programa: subir un KMZ nuevo y poner la base del presupuesto al día (visor v2, fase 8).

Dos pasos, los dos solo para administradores:

  1. `subir_kmz`: el KMZ que llega (subida por partes, subidas.py) reemplaza al vigente en la carpeta `KMZ_PATH`. Lo anterior no se borra: se mueve a
     `anteriores/` con la fecha. El panel «Lugares» lo muestra de inmediato (la caché se regenera sola); los usuarios remotos lo bajan al abrir el visor.
  2. `comparar` / `sincronizar`: la ruta y el presupuesto NO leen el KMZ sino `red_puntos` / `red_lineas` (PostGIS). Si esas tablas son de un KMZ
     anterior, el cálculo no ve los postes, mufas y fibra nuevos y cobra postes de más. `comparar` dice qué falta (y qué sobra) sin tocar nada;
     `sincronizar` agrega lo nuevo (y, si se pide, quita lo que el KMZ ya no trae) en una sola transacción y guarda lo que hizo para
     `revertir_sincronizacion`. Lo que publicó el visor (`tabla_origen = 'visor'`) nunca se quita.

Un elemento del KMZ «es el mismo» que uno de la base si es de la misma familia (poste, mufa, reserva, pozo, nodo…) y está a pocos metros; una línea, si sus
dos extremos coinciden. Así un poste corrido unos centímetros por la edición no se cuenta como nuevo y viejo a la vez.
"""
import datetime as dt
import io
import json
import logging
import math
import re
import zipfile
from pathlib import Path
from typing import Any

from visor_rutas import kmz_capas, subidas
from visor_rutas.redes import importar_kmz
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

log = logging.getLogger(__name__)

ORIGEN = "kmz sincronizado"       # tabla_origen of what this module inserts
TOL_PUNTO_M = 3.0                 # a point this close, of the same family, is the same element
TOL_LINEA_M = 6.0                 # a line whose two ends are this close (either direction) is the same
CELDA = 4e-5                      # grid of the index (~4.4 m)
MAX_EJEMPLOS = 8
MAX_SOBRAN_RELATIVO = 0.35        # removing more than this share of the base is almost surely a wrong file
FAMILIAS = ("poste", "mufa", "reserva", "pozo", "nodo")
TABLAS = importar_kmz.TABLAS
_cache_elementos: dict[str, Any] = {}


def _exigir_admin(actor: dict[str, Any]) -> None:
    importar_kmz._exigir_admin(actor)


def _familia(tipo: Any) -> str:
    t = importar_kmz.normal(tipo)
    return next((f for f in FAMILIAS if t.startswith(f)), t)


def _carpeta_sincronizaciones() -> Path:
    return kmz_capas.CARPETA_DATOS / "sincronizaciones"


# --------------------------------------------------------------------------- subir el KMZ

def _validar_kmz(crudo: bytes) -> int:
    """How many placemarks the file brings; DatosInvalidos if it is not a KMZ / KML with a network inside."""
    try:
        elementos = importar_kmz.leer(crudo)
    except DatosInvalidos:
        raise
    except Exception as exc:                          # noqa: BLE001 - whatever lxml / zipfile say, the user needs one clear sentence
        raise DatosInvalidos({"archivo": "El archivo no se pudo leer como KMZ"}) from exc
    if len(elementos) < 10:
        raise DatosInvalidos({"archivo": "El archivo casi no trae elementos: no parece la red"})
    return len(elementos)


def _carpeta_kmz() -> tuple[Path, Path | None]:
    """(folder where the KMZ lives, the KMZ file itself when KMZ_PATH points to a file)."""
    import os
    texto = str(os.getenv("KMZ_PATH") or "red_kmz").strip().strip('"')
    ruta = Path(texto)
    if not ruta.is_absolute():
        ruta = kmz_capas.RAIZ / ruta
    return (ruta.parent, ruta) if ruta.suffix.lower() == ".kmz" else (ruta, None)


def _nombre_seguro(nombre: str) -> str:
    base = re.sub(r"[^\w .()\-]", "_", Path(str(nombre or "")).name).strip(" .") or "RED.kmz"
    return base if base.lower().endswith(".kmz") else base + ".kmz"


def subir_kmz(con: Any, actor: dict[str, Any], *, subida_id: str, nombre: str = "") -> dict[str, Any]:
    """The uploaded KMZ becomes the network in force (the old one is kept in `anteriores/`). Administrators only."""
    _exigir_admin(actor)
    try:
        nombre_subido, crudo = subidas.almacen.tomar(subida_id)
    except subidas.ErrorSubida as exc:
        raise DatosInvalidos({"archivo": str(exc)}) from None
    nombre = _nombre_seguro(nombre or nombre_subido)
    if crudo[:2] != b"PK":
        raise DatosInvalidos({"archivo": "Tiene que ser un archivo .kmz (el .kml suelto no se acepta aquí)"})
    elementos = _validar_kmz(crudo)
    carpeta, archivo_fijo = _carpeta_kmz()
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = archivo_fijo or carpeta / nombre
    anteriores = carpeta / "anteriores"
    sello = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for viejo in carpeta.glob("*.kmz"):                   # one network at a time: the old ones are kept aside
        anteriores.mkdir(exist_ok=True)
        viejo.replace(anteriores / f"{sello}_{viejo.name}")
    temporal = destino.with_suffix(".kmz.tmp")
    temporal.write_bytes(crudo)
    temporal.replace(destino)
    log.info("Network KMZ replaced by %s (%d elements) for %s", destino.name, elementos, actor.get("nombre") or actor.get("id"))
    _cache_elementos.clear()
    arbol = kmz_capas.asegurar()                          # the cache is rebuilt now (~15 s) so the next page load is instant
    return {"archivo": destino.name, "tamano": len(crudo), "elementos": elementos, "importado": arbol.get("importado"),
            "anterior_en": str(anteriores) if anteriores.is_dir() else None}


def estado(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """The KMZ in force and the saved synchronizations (no comparison: that takes a while)."""
    _exigir_admin(actor)
    try:
        ruta = kmz_capas.ruta_kmz()
        info = {"archivo": ruta.name, "tamano": ruta.stat().st_size, "modificado": dt.datetime.fromtimestamp(ruta.stat().st_mtime).isoformat(timespec="seconds")}
    except kmz_capas.KmzNoEncontrado as exc:
        info = {"archivo": None, "error": str(exc)}
    return {"kmz": info, "sincronizaciones": sincronizaciones(con, actor)["sincronizaciones"]}


# --------------------------------------------------------------------------- comparar con red_puntos / red_lineas

def _elementos_kmz() -> tuple[str, str, list[dict[str, Any]]]:
    """(file name, md5, elements) of the KMZ in force; parsed once per file."""
    ruta = kmz_capas.ruta_kmz()
    clave = f"{ruta}|{ruta.stat().st_mtime_ns}|{ruta.stat().st_size}"
    if clave not in _cache_elementos:
        _cache_elementos.clear()
        _cache_elementos[clave] = (ruta.name, kmz_capas.md5_archivo(ruta), importar_kmz.leer(ruta.read_bytes()))
    return _cache_elementos[clave]


def _celda(lat: float, lon: float) -> tuple[int, int]:
    return (int(math.floor(lat / CELDA)), int(math.floor(lon / CELDA)))


class _Indice:
    """Grid of points (or ends of lines) to find the nearest unused one of a family."""

    def __init__(self) -> None:
        self.celdas: dict[tuple[int, int], list[tuple[str, float, float, int]]] = {}
        self.usados: set[int] = set()

    def agregar(self, familia: str, lat: float, lon: float, dato: int) -> None:
        self.celdas.setdefault(_celda(lat, lon), []).append((familia, lat, lon, dato))

    def candidatos(self, familia: str, lat: float, lon: float, maximo_m: float) -> list[int]:
        """Ids of the unused elements of the family within `maximo_m`, nearest first."""
        c0 = _celda(lat, lon)
        hallados: list[tuple[float, int]] = []
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for fam, la, lo, dato in self.celdas.get((c0[0] + i, c0[1] + j), ()):
                    if fam == familia and dato not in self.usados:
                        d = importar_kmz._distancia(lat, lon, la, lo)
                        if d <= maximo_m:
                            hallados.append((d, dato))
        return [dato for _, dato in sorted(hallados)]


def _extremos_json(geom: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    return importar_kmz._extremos({"type": geom["type"], "coordinates": geom["coordinates"]})


def diferencias(pg: Any, elementos: list[dict[str, Any]]) -> dict[str, Any]:
    """What the KMZ has and the base does not (`nuevos`), what the base has and the KMZ no longer does (`sobran`, never what the viewer published)."""
    info = {t: importar_kmz._categorias(pg, t) for t in TABLAS.values()}
    destinos: dict[tuple[str, str], Any] = {}
    nuevos: dict[str, list[dict[str, Any]]] = {"punto": [], "linea": []}
    sin_categoria: dict[str, int] = {}
    indices = {"punto": _Indice(), "linea": _Indice()}
    filas_db: dict[str, dict[int, dict[str, Any]]] = {"punto": {}, "linea": {}}

    for f in pg.execute("SELECT id, tabla_origen, tipo, nombre, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM red_puntos WHERE geom IS NOT NULL AND GeometryType(geom) = 'POINT'"):
        filas_db["punto"][f["id"]] = f
        indices["punto"].agregar(_familia(f["tipo"]), f["lat"], f["lon"], f["id"])
    for f in pg.execute("SELECT id, tabla_origen, tipo, nombre, ST_AsGeoJSON(geom) AS g FROM red_lineas WHERE geom IS NOT NULL"):
        ext = _extremos_json(json.loads(f["g"]))
        if ext is None:
            continue
        filas_db["linea"][f["id"]] = f
        for punta in ext:
            indices["linea"].agregar(_familia(f["tipo"]), punta[0], punta[1], f["id"])

    por_carpeta: dict[str, dict[str, int]] = {}
    for e in elementos:
        if e["tipo"] not in ("punto", "linea"):
            continue
        tabla = TABLAS[e["tipo"]]
        clave = (e["ruta"], tabla)
        if clave not in destinos:
            destinos[clave] = importar_kmz.categoria_para(e["ruta"], tabla, info[tabla])
        destino = destinos[clave]
        hoja = e["ruta"].rsplit("/", 1)[-1]
        if destino is None:
            sin_categoria[hoja] = sin_categoria.get(hoja, 0) + 1
            continue
        familia = _familia(destino[1])
        if e["tipo"] == "punto":
            lat, lon = importar_kmz.primero(e["geom"])
            hallados = indices["punto"].candidatos(familia, lat, lon, TOL_PUNTO_M)
            if hallados:
                indices["punto"].usados.add(hallados[0])
                continue
        else:
            ext = importar_kmz._extremos(e["geom"])
            if ext is None:
                continue
            hallado = None
            a, b = ext
            for candidato in indices["linea"].candidatos(familia, a[0], a[1], TOL_LINEA_M):
                ext_db = _extremos_json(json.loads(filas_db["linea"][candidato]["g"]))
                if not ext_db:
                    continue
                directo = max(importar_kmz._distancia(*a, *ext_db[0]), importar_kmz._distancia(*b, *ext_db[1]))
                inverso = max(importar_kmz._distancia(*a, *ext_db[1]), importar_kmz._distancia(*b, *ext_db[0]))      # drawn the other way round
                if min(directo, inverso) <= TOL_LINEA_M:
                    hallado = candidato
                    break
            if hallado is not None:
                indices["linea"].usados.add(hallado)
                continue
        nuevos[e["tipo"]].append({**e, "categoria": destino[0], "tipo_db": destino[1]})
        por_carpeta.setdefault(hoja, {"nuevos": 0, "sobran": 0})["nuevos"] += 1

    sobran: dict[str, list[Any]] = {"punto": [], "linea": []}
    for tipo in ("punto", "linea"):
        for id_, f in filas_db[tipo].items():
            if id_ in indices[tipo].usados or f["tabla_origen"] == "visor":
                continue
            sobran[tipo].append(f)
            por_carpeta.setdefault(f["tipo"] or "?", {"nuevos": 0, "sobran": 0})["sobran"] += 1
    return {"nuevos": nuevos, "sobran": sobran, "sin_categoria": sin_categoria, "por_carpeta": por_carpeta,
            "en_base": {"puntos": len(filas_db["punto"]), "lineas": len(filas_db["linea"])}}


def _resumen(d: dict[str, Any], archivo: str) -> dict[str, Any]:
    ejemplos = lambda lista: [{"nombre": (x.get("nombre") or "").strip()[:60], "carpeta": x.get("ruta", "").rsplit("/", 1)[-1] or x.get("tipo")} for x in lista[:MAX_EJEMPLOS]]  # noqa: E731
    return {"archivo": archivo, "en_base": d["en_base"],
            "nuevos": {"puntos": len(d["nuevos"]["punto"]), "lineas": len(d["nuevos"]["linea"])},
            "sobran": {"puntos": len(d["sobran"]["punto"]), "lineas": len(d["sobran"]["linea"])},
            "postes_nuevos": sum(1 for x in d["nuevos"]["punto"] if _familia(x["tipo_db"]) == "poste"),
            "mufas_nuevas": sum(1 for x in d["nuevos"]["punto"] if _familia(x["tipo_db"]) == "mufa"),
            "por_carpeta": dict(sorted(d["por_carpeta"].items(), key=lambda kv: -(kv[1]["nuevos"] + kv[1]["sobran"]))[:15]),
            "sin_categoria": dict(sorted(d["sin_categoria"].items(), key=lambda kv: -kv[1])[:10]),
            "ejemplos_nuevos": ejemplos(d["nuevos"]["punto"] + d["nuevos"]["linea"]),
            "ejemplos_sobran": ejemplos(d["sobran"]["punto"] + d["sobran"]["linea"])}


def comparar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """What the budget base lacks (and has too much of) against the KMZ in force. Writes nothing."""
    _exigir_admin(actor)
    archivo, _, elementos = _elementos_kmz()
    pg = importar_kmz.conectar_presupuesto()
    try:
        return {"resumen": _resumen(diferencias(pg, elementos), archivo)}
    finally:
        pg.close()


# --------------------------------------------------------------------------- sincronizar y revertir

def _plano(html: str | None) -> str | None:
    return importar_kmz._texto_plano(html) or None


def sincronizar(con: Any, actor: dict[str, Any], *, quitar: bool = False) -> dict[str, Any]:
    """Adds to red_puntos / red_lineas what the KMZ has and the base lacks (and removes what the KMZ no longer has if `quitar`), in one
    transaction. What it did is saved to revert it."""
    _exigir_admin(actor)
    archivo, md5, elementos = _elementos_kmz()
    pg = importar_kmz.conectar_presupuesto()
    try:
        d = diferencias(pg, elementos)
        sobran_n = len(d["sobran"]["punto"]) + len(d["sobran"]["linea"])
        total_db = d["en_base"]["puntos"] + d["en_base"]["lineas"]
        if quitar and total_db and sobran_n / total_db > MAX_SOBRAN_RELATIVO:
            raise DatosInvalidos({"quitar": f"Se quitaría el {sobran_n * 100 // total_db} % de la base: el KMZ no parece el correcto. Revise el archivo."})
        guardado: dict[str, Any] = {"insertados": {"puntos": [], "lineas": []}, "eliminados": {"puntos": [], "lineas": []}}
        with pg.transaction():
            for tipo, tabla, clave in (("punto", "red_puntos", "puntos"), ("linea", "red_lineas", "lineas")):
                for e in d["nuevos"][tipo]:
                    fila = pg.execute(f"INSERT INTO {tabla} (tabla_origen, categoria, nombre, descripcion, geom, tipo) VALUES (%s, %s, %s, %s, "
                                      f"ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s) RETURNING id",
                                      (ORIGEN, e["categoria"], e["nombre"] or None, _plano(e["desc"]), importar_kmz._json(e["geom"]), e["tipo_db"])).fetchone()
                    guardado["insertados"][clave].append(fila["id"])
            if quitar:
                for tipo, tabla, clave in (("punto", "red_puntos", "puntos"), ("linea", "red_lineas", "lineas")):
                    for f in d["sobran"][tipo]:
                        previa = pg.execute(f"SELECT id, tabla_origen, categoria, nombre, descripcion, tipo, ST_AsText(geom) AS wkt FROM {tabla} WHERE id = %s", (f["id"],)).fetchone()
                        if previa:
                            guardado["eliminados"][clave].append(dict(previa))
                            pg.execute(f"DELETE FROM {tabla} WHERE id = %s", (f["id"],))
    finally:
        pg.close()
    id_ = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    carpeta = _carpeta_sincronizaciones()
    carpeta.mkdir(parents=True, exist_ok=True)
    registro = {"id": id_, "archivo": archivo, "md5": md5, "por": actor.get("nombre") or actor.get("id"), "quitar": bool(quitar), "revertida": False,
                "resumen": _resumen(d, archivo), **guardado}
    (carpeta / f"{id_}.json").write_text(json.dumps(registro, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("Budget network synchronized with %s: +%d points, +%d lines, -%d points, -%d lines", archivo, len(guardado["insertados"]["puntos"]),
             len(guardado["insertados"]["lineas"]), len(guardado["eliminados"]["puntos"]), len(guardado["eliminados"]["lineas"]))
    return {"id": id_, "resumen": registro["resumen"], "insertados": {k: len(v) for k, v in guardado["insertados"].items()},
            "eliminados": {k: len(v) for k, v in guardado["eliminados"].items()}}


def _registros() -> list[dict[str, Any]]:
    carpeta = _carpeta_sincronizaciones()
    if not carpeta.is_dir():
        return []
    salida = []
    for archivo in sorted(carpeta.glob("*.json"), reverse=True):
        try:
            salida.append(json.loads(archivo.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("Synchronization record %s is unreadable", archivo.name)
    return salida


def sincronizaciones(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    _exigir_admin(actor)
    return {"sincronizaciones": [{"id": r["id"], "archivo": r["archivo"], "por": r.get("por"), "quitar": r.get("quitar"), "revertida": r.get("revertida"),
                                  "insertados": {k: len(v) for k, v in r["insertados"].items()}, "eliminados": {k: len(v) for k, v in r["eliminados"].items()}}
                                 for r in _registros()[:10]]}


def revertir_sincronizacion(con: Any, actor: dict[str, Any], *, id: str) -> dict[str, Any]:
    """Takes back the LAST synchronization: what it inserted is deleted, what it removed goes back as it was."""
    _exigir_admin(actor)
    registros = _registros()
    activos = [r for r in registros if not r.get("revertida")]
    r = next((x for x in registros if x["id"] == str(id)), None)
    if r is None:
        raise NoEncontrado("La sincronización no existe")
    if r.get("revertida"):
        raise DatosInvalidos({"id": "Esa sincronización ya se revirtió"})
    if activos and activos[0]["id"] != r["id"]:
        raise DatosInvalidos({"id": "Solo se puede revertir la última sincronización (primero la más reciente)"})
    pg = importar_kmz.conectar_presupuesto()
    try:
        with pg.transaction():
            for clave, tabla in (("puntos", "red_puntos"), ("lineas", "red_lineas")):
                for id_ in r["insertados"][clave]:
                    pg.execute(f"DELETE FROM {tabla} WHERE id = %s AND tabla_origen = %s", (id_, ORIGEN))
                for f in r["eliminados"][clave]:
                    pg.execute(f"INSERT INTO {tabla} (id, tabla_origen, categoria, nombre, descripcion, geom, tipo) VALUES (%s, %s, %s, %s, %s, "
                               f"ST_SetSRID(ST_GeomFromText(%s), 4326), %s) ON CONFLICT (id) DO NOTHING",
                               (f["id"], f["tabla_origen"], f["categoria"], f["nombre"], f["descripcion"], f["wkt"], f["tipo"]))
    finally:
        pg.close()
    r["revertida"] = True
    (_carpeta_sincronizaciones() / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, default=str), encoding="utf-8")
    return {"id": r["id"], "revertida": True}
