"""Ruta de fusión: mufa por mufa, cómo llega el servicio desde el OLT/nodo hasta el punto de conexión.

Solo datos que ya están en la base de diagramas (red_fibra), sin adivinar fusiones:
  - hilos_anillo:          Excel de anillos (anillo_tramos)            -> fuente "excel", confianza alta
  - splitters_y_puertos:   textos del diagrama de esa mufa (servicios y textos_crudos con SPL, 1X8,
                           PUERTO, OLT, NODO, HILO, BUFFER, FUSION...) -> fuente "texto_diagrama"
  - clientes:              servicios registrados en esa mufa
  - archivos:              diagramas donde la mufa es principal o aparece (para ver el diagrama real)
  - fusiones_piloto:       fusiones detectadas por el piloto (red_fibra/fusiones.py), solo si existe
                           la tabla, aparte y sin validar ("Piloto – validar"); None si no existe

Lee la copia PostgreSQL (esquema red_fibra) cuando hay conexión, si no el SQLite red_fibra.db, con
las mismas consultas (estilo sqlite "?", adaptadas por origen._PgAdapter).

diagrama_png(md5) convierte el .odg de datos/cache/odg a PNG con LibreOffice (headless, perfil
temporal) y lo guarda en datos/cache/diagramas/<md5>_<pagina>.png.
"""
import logging
import math
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import psycopg

import recalc
from config import BASE_DIR, get_settings
from origen import _PgAdapter, _distance_m
from visor_rutas import almacen_archivos

log = logging.getLogger(__name__)

CACHE_ODG = BASE_DIR / "datos" / "cache" / "odg"
CACHE_DIAGRAMAS = BASE_DIR / "datos" / "cache" / "diagramas"
ANCHO_PNG_PX = 6000             # 2048 px (LibreOffice's default) is unreadable for subred diagrams
ALTO_MAX_PX = 9000
TIMEOUT_CONVERSION_S = 180
RADIO_TEXTOS_CM = 10.0          # in red/subred diagrams: texts this close to the mufa's label belong to it
MAX_TEXTOS = 25
MAX_PILOTO = 30                 # pilot fusions listed per mufa
MAX_DIAGRAMAS = 10              # diagrams of one mufa located (label position) for the viewer
MAX_RESULTADOS = 20             # mufa search results
STOP_BUSQUEDA = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "A", "AL", "EN", "FTE", "FRENTE"}   # as importador
MAX_CLIENTES = 60

RE_MD5 = re.compile(r"^[0-9a-f]{32}$")
RE_SPLITTER_PUERTO = re.compile(
    r"\bSPL|\b1\s*[X/*]\s*(2|4|8|16|32|64)\b|\bPUERTO|\bPT\.?\s*\d|\bOLT\b|\bNODO\b|\bHILOS?\b|\bBUFFER|\bFUSION"
    r"|\bH\d{1,2}\b", re.I)
RE_SOLO_NUMEROS = re.compile(r"^[\d\s/\-–,.]+$")
RE_COORDENADA = re.compile(r"\d{1,2}[.,]\d{4,}")
NOTAS_CLAVE = ("SANGRIA", "SANGRÍA", "VALIDAR", "SATURAD", "NO PROYECTAR", "ANULADA", "NO USAR", "CORTADO",
               "RESPALDO", "REDUNDANT", "DESHABILITAD")


# --------------------------------------------------------------------------- acceso a la base

class _Fuente:
    """PostgreSQL (red_fibra schema) when the connection works, else the SQLite file."""

    def __init__(self, visio_con: Any, archivo_sqlite: Path | None):
        self._pg = _PgAdapter(visio_con) if visio_con is not None else None
        self._sqlite_path = archivo_sqlite
        self._sqlite: sqlite3.Connection | None = None
        self.nombre = "postgresql" if self._pg else "sqlite"

    def _abrir_sqlite(self) -> sqlite3.Connection | None:
        if self._sqlite is None and self._sqlite_path is not None and Path(self._sqlite_path).is_file():
            self._sqlite = sqlite3.connect(f"{Path(self._sqlite_path).resolve().as_uri()}?mode=ro", uri=True)
            self.nombre = "sqlite"
        return self._sqlite

    @property
    def disponible(self) -> bool:
        return self._pg is not None or (self._sqlite_path is not None and Path(self._sqlite_path).is_file())

    def filas(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._pg is not None:
            try:
                return list(self._pg.execute(sql, params).fetchall())
            except psycopg.Error as exc:
                log.warning("Fusion route: PostgreSQL query failed (%s); using the SQLite file", type(exc).__name__)
                self._pg = None
        con = self._abrir_sqlite()
        if con is None:
            raise FileNotFoundError("base de diagramas no disponible")
        return con.execute(sql, params).fetchall()

    def tiene_tabla(self, nombre: str) -> bool:
        """Whether a table exists in the database being read (the pilot table may not)."""
        if self._pg is not None:
            sql = ("SELECT count(*) FROM information_schema.tables "
                   "WHERE table_schema = 'red_fibra' AND table_name = ?")
        else:
            sql = "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?"
        try:
            return bool(self.filas(sql, (nombre,))[0][0])
        except (sqlite3.Error, FileNotFoundError):
            return False

    def cerrar(self) -> None:
        if self._sqlite is not None:
            self._sqlite.close()


def _marcas(n: int) -> str:
    return ",".join("?" * n)


# --------------------------------------------------------------------------- camino -> nodos

_COLUMNAS_NODO = ("id", "nombre", "tipo", "propietario", "lat", "lon", "notas", "zona", "requiere_revision")


def _candidatos(fuente: _Fuente, nombres: list[str]) -> dict[str, list[dict[str, Any]]]:
    unicos = sorted(set(nombres))
    filas = fuente.filas(f"SELECT {', '.join(_COLUMNAS_NODO)} FROM nodos WHERE nombre IN ({_marcas(len(unicos))})",
                         tuple(unicos))
    por_nombre: dict[str, list[dict[str, Any]]] = {}
    for fila in filas:
        nodo = dict(zip(_COLUMNAS_NODO, fila))
        por_nombre.setdefault(nodo["nombre"], []).append(nodo)
    return por_nombre


def _vecinos(fuente: _Fuente, ids: list[int]) -> dict[int, set[int]]:
    if not ids:
        return {}
    m = _marcas(len(ids))
    vecinos: dict[int, set[int]] = {}
    for a, b in fuente.filas(f"SELECT nodo_a_id, nodo_b_id FROM enlaces WHERE nodo_a_id IN ({m}) OR nodo_b_id IN ({m})",
                             tuple(ids) * 2):
        vecinos.setdefault(a, set()).add(b)
        vecinos.setdefault(b, set()).add(a)
    return vecinos


def _distancia(a: dict[str, Any], lat: float | None, lon: float | None) -> float:
    if a.get("lat") is None or a.get("lon") is None or lat is None or lon is None:
        return math.inf
    return _distance_m(float(a["lat"]), float(a["lon"]), float(lat), float(lon))


def _resolver_camino(fuente: _Fuente, camino: list[str], conexion: dict[str, Any]) -> list[dict[str, Any]]:
    """Visio node of each name in `camino` (connection mufa first). A repeated name is resolved by
    the cable (enlaces) to the previous stop, else by distance."""
    candidatos = _candidatos(fuente, camino)
    vecinos = _vecinos(fuente, [n["id"] for lista in candidatos.values() for n in lista])
    paradas: list[dict[str, Any]] = []
    anterior: dict[str, Any] | None = None
    for nombre in camino:
        opciones = candidatos.get(nombre, [])
        if not opciones:
            paradas.append({"id": None, "nombre": nombre, "tipo": None, "propietario": None, "lat": None,
                            "lon": None, "notas": None, "zona": None, "identificacion": "no_encontrada"})
            continue
        if len(opciones) == 1:
            elegido, como = opciones[0], "exacta"
        elif anterior is None:
            elegido = min(opciones, key=lambda n: _distancia(n, conexion.get("lat"), conexion.get("lon")))
            como = "por_cercania"
        else:
            unidos = [n for n in opciones if n["id"] in vecinos.get(anterior.get("id"), set())]
            if len(unidos) == 1:
                elegido, como = unidos[0], "por_enlace"
            else:
                elegido = min(unidos or opciones, key=lambda n: _distancia(n, anterior.get("lat"), anterior.get("lon")))
                como = "por_cercania"
        parada = dict(elegido, identificacion=como)
        paradas.append(parada)
        anterior = parada
    return paradas


# --------------------------------------------------------------------------- detalle de cada mufa

def _archivos(fuente: _Fuente, nodo_id: int) -> list[dict[str, Any]]:
    filas = fuente.filas(
        "SELECT a.rol, a.texto_original, f.id, f.ruta_relativa, f.md5, f.tipo_diagrama, f.formato "
        "FROM nodo_apariciones a JOIN archivos f ON f.id = a.archivo_id "
        "WHERE a.nodo_id = ? AND f.estado = 'ok'", (nodo_id,))
    orden_rol = {"principal": 0, "vecino": 1, "red": 2, "excel": 3}
    por_archivo: dict[int, dict[str, Any]] = {}
    for rol, texto_original, archivo_id, ruta, md5, tipo, formato in filas:
        actual = por_archivo.get(archivo_id)
        if actual is None or orden_rol.get(rol, 9) < orden_rol.get(actual["rol"], 9):
            por_archivo[archivo_id] = {"archivo_id": archivo_id, "rol": rol, "ruta_relativa": ruta, "md5": md5,
                                       "tipo_diagrama": tipo, "nombre": Path(ruta).name,
                                       "diagrama": formato != "xlsx", "texto_original": texto_original}
    return sorted(por_archivo.values(),
                  key=lambda a: (orden_rol.get(a["rol"], 9), a["tipo_diagrama"] != "mufa", a["nombre"]))


def _hilos_anillo(fuente: _Fuente, nodo_id: int) -> list[dict[str, Any]]:
    filas = fuente.filas(
        "SELECT hoja, enlace, orden, de_mufa, hilo_entrante, hacia_mufa, hilo_saliente, nota "
        "FROM anillo_tramos WHERE nodo_id = ? ORDER BY hoja, orden", (nodo_id,))
    return [{"hoja": h, "enlace": e, "orden": o, "de_mufa": d, "hilo_entrante": he, "hacia_mufa": ha,
             "hilo_saliente": hs, "nota": n, "fuente": "excel", "confianza": "alta"}
            for h, e, o, d, he, ha, hs, n in filas]


def _servicios(fuente: _Fuente, nodo_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(clientes, splitters) registered in this mufa, without repeats."""
    clientes: dict[str, dict[str, Any]] = {}
    splitters: dict[str, dict[str, Any]] = {}
    for tipo, codigo, id_servicio, descripcion, ruta in fuente.filas(
            "SELECT s.tipo, s.codigo_cliente, s.id_servicio, s.descripcion, f.ruta_relativa "
            "FROM servicios s JOIN archivos f ON f.id = s.archivo_id WHERE s.nodo_id = ?", (nodo_id,)):
        clave = " ".join((descripcion or "").split()).upper()
        if not clave:
            continue
        if tipo == "cliente":
            clientes.setdefault(clave, {"codigo": codigo, "id_servicio": id_servicio, "descripcion": descripcion,
                                        "archivo": Path(ruta).name})
        elif tipo == "splitter" or RE_SPLITTER_PUERTO.search(descripcion or ""):
            splitters.setdefault(clave, {"texto": descripcion, "fuente": "texto_diagrama",
                                         "origen": "servicios", "archivo": Path(ruta).name})
    return list(clientes.values())[:MAX_CLIENTES], list(splitters.values())


def _es_diagrama_propio(archivo: dict[str, Any]) -> bool:
    """The mufa's own diagram: everything drawn in it belongs to this mufa."""
    return archivo["rol"] == "principal" and archivo["tipo_diagrama"] == "mufa"


def _textos_con_ancla(fuente: _Fuente, archivo: dict[str, Any]) -> tuple[list[tuple], tuple | None]:
    """(texts of the diagram, (page, x, y) of this mufa's label or None)."""
    filas = fuente.filas("SELECT pagina, x_cm, y_cm, texto FROM textos_crudos WHERE archivo_id = ?",
                         (archivo["archivo_id"],))
    etiqueta = archivo.get("texto_original")
    ancla = next(((p, x, y) for p, x, y, t in filas if etiqueta and t == etiqueta and x is not None), None)
    return filas, ancla


def _textos_de_mufa(fuente: _Fuente, archivo: dict[str, Any]) -> list[str]:
    """Texts of this mufa in one diagram: the whole diagram when it is the mufa's own diagram,
    otherwise only the texts near the mufa's label."""
    filas, ancla = _textos_con_ancla(fuente, archivo)
    if _es_diagrama_propio(archivo):
        return [t for _, _, _, t in filas]
    if ancla is None:
        return []
    pagina, x0, y0 = ancla
    return [t for p, x, y, t in filas
            if p == pagina and x is not None and y is not None and math.hypot(x - x0, y - y0) <= RADIO_TEXTOS_CM]


_COLUMNAS_PILOTO = ("pagina", "entrada", "salida", "color", "color_tia", "confianza", "motivo",
                    "x1_cm", "y1_cm", "x2_cm", "y2_cm")


def _fusiones_piloto(fuente: _Fuente, archivos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusions found by the pilot extraction (red_fibra/fusiones.py) in this mufa's diagrams.

    Kept apart from the Excel / diagram-text data: they are unvalidated ("Piloto – validar").
    In a red/subred diagram only the fusions with an end near this mufa's label are taken.
    """
    salida: list[dict[str, Any]] = []
    for archivo in [a for a in archivos if a["diagrama"]][:4]:
        filas = [dict(zip(_COLUMNAS_PILOTO, f)) for f in fuente.filas(
            f"SELECT {', '.join(_COLUMNAS_PILOTO)} FROM fusiones_piloto WHERE archivo_id = ? ORDER BY confianza DESC",
            (archivo["archivo_id"],))]
        if not filas:
            continue
        if not _es_diagrama_propio(archivo):
            _, ancla = _textos_con_ancla(fuente, archivo)
            if ancla is None:
                continue
            pagina, x0, y0 = ancla
            filas = [f for f in filas if f["pagina"] == pagina and min(
                math.hypot(f["x1_cm"] - x0, f["y1_cm"] - y0), math.hypot(f["x2_cm"] - x0, f["y2_cm"] - y0)
            ) <= RADIO_TEXTOS_CM]
        salida += [{"entrada": f["entrada"], "salida": f["salida"], "color": f["color"],
                    "color_tia": f["color_tia"], "confianza": f["confianza"], "motivo": f["motivo"],
                    "archivo": archivo["nombre"], "fuente": "piloto"} for f in filas]
    salida.sort(key=lambda f: -(f["confianza"] or 0))
    return salida[:MAX_PILOTO]


RE_CLIENTE_TEXTO = re.compile(r"\bC\s?\d{4,6}\b|\bID\s*\d{5,7}\b", re.I)
RE_ETIQUETA_NODO = re.compile(r"^\s*(MUFAS?|MF|MC|NODO|MINI\s*NODO|MN|ODF|FOSC)\b", re.I)
PALABRAS_GENERICAS = {"MUFA", "FOSC", "IDEAY", "UFINET"}


def _coincide(palabra: str, otras: list[str]) -> bool:
    """Same word, or a plural / truncated form of it (COLINA ~ COLINAS) for words of 4+ letters."""
    if len(palabra) < 4:
        return palabra in otras
    return any(len(o) >= 4 and (o.startswith(palabra) or palabra.startswith(o)) for o in otras)


def _ancla_por_nombre(filas: list[tuple], nombre: str) -> tuple | None:
    """The diagram text that best names this mufa, when its exact label was not recorded (the
    importer keeps the file name for 82 of the 347 mufa diagrams). Labels starting with MUFA / MF /
    NODO are preferred; client texts are skipped."""
    objetivo = [p for p in normalizar_busqueda(nombre) if p not in PALABRAS_GENERICAS]
    if not objetivo:
        return None
    mejor = None
    for p, x, y, texto in filas:
        if x is None or y is None or RE_CLIENTE_TEXTO.search(texto or ""):
            continue
        palabras = normalizar_busqueda(texto)
        puntaje = sum(_coincide(o, palabras) for o in objetivo) / len(objetivo)
        if puntaje < 0.6:
            continue
        clave = (puntaje, bool(RE_ETIQUETA_NODO.match(texto)), -len(texto))
        if mejor is None or clave > mejor[0]:
            mejor = (clave, (p, x, y))
    return mejor[1] if mejor else None


def _ancla_en_diagrama(fuente: _Fuente, archivo: dict[str, Any], nombre: str) -> dict[str, float] | None:
    """Where this mufa is drawn in the diagram: its label's position and the page size (cm), so
    the viewer can zoom to it and circle it. None when the label or the .odg is not found."""
    odg = ruta_odg(archivo["md5"])
    if not odg.is_file():
        return None
    filas, ancla = _textos_con_ancla(fuente, archivo)
    if ancla is None:
        ancla = _ancla_por_nombre(filas, nombre)
    if ancla is None:
        return None
    ancho_cm, alto_cm = _tamano_pagina_cm(odg)
    return {"x_cm": float(ancla[1]), "y_cm": float(ancla[2]), "ancho_cm": ancho_cm, "alto_cm": alto_cm}


def _limpio(texto: str) -> str:
    return " ".join((texto or "").replace("\n", " / ").split())


def _leer_textos(textos: list[str], archivo: str, splitters: list[dict[str, Any]], vistos: set[str],
                 notas: list[str]) -> None:
    """Splitter / port texts and notes (SANGRIA, VALIDAR...) of one diagram, added in place."""
    for texto in textos:
        plano = _limpio(texto)
        clave = plano.upper()
        if not plano or RE_SOLO_NUMEROS.match(plano) or clave in vistos:
            continue
        if RE_SPLITTER_PUERTO.search(plano) and len(splitters) < MAX_TEXTOS:
            vistos.add(clave)
            splitters.append({"texto": plano, "fuente": "texto_diagrama", "origen": "textos_crudos",
                              "archivo": archivo})
        # Notes: SANGRIA, VALIDAR, SATURADA... but not from another mufa's label (it has coordinates).
        if RE_COORDENADA.search(plano):
            continue
        for palabra in NOTAS_CLAVE:
            nota = plano if len(plano) <= 80 else plano[:77] + "…"
            if palabra in clave and nota not in notas and len(notas) < 10:
                notas.append(nota)
                break


def _detalle_por_nombre(fuente: _Fuente, emparejado: dict[str, Any]) -> dict[str, Any]:
    """A mufa drawn without coordinates (matched by name, origen.py case d): the diagram where its
    name was found, located at that text, and the texts written around it."""
    detalle = {"archivos": [], "hilos_anillo": [], "splitters_y_puertos": [], "clientes": [], "notas": []}
    fila = fuente.filas("SELECT id, ruta_relativa, md5, tipo_diagrama, formato FROM archivos WHERE id = ?",
                        (emparejado.get("archivo_id"),))
    if not fila:
        return detalle
    archivo_id, ruta, md5, tipo, formato = fila[0]
    archivo = {"archivo_id": archivo_id, "rol": "por_nombre", "ruta_relativa": ruta, "md5": md5,
               "tipo_diagrama": tipo, "nombre": Path(ruta).name, "diagrama": formato != "xlsx", "ancla": None}
    pagina, x0, y0 = emparejado.get("pagina"), emparejado.get("x_cm"), emparejado.get("y_cm")
    odg = ruta_odg(md5)
    if x0 is not None and y0 is not None and odg.is_file():
        ancho_cm, alto_cm = _tamano_pagina_cm(odg)
        archivo["ancla"] = {"x_cm": float(x0), "y_cm": float(y0), "ancho_cm": ancho_cm, "alto_cm": alto_cm}
    cercanos = [] if x0 is None or y0 is None else [
        t for p, x, y, t in fuente.filas("SELECT pagina, x_cm, y_cm, texto FROM textos_crudos WHERE archivo_id = ?",
                                         (archivo_id,))
        if p == pagina and x is not None and y is not None and math.hypot(x - x0, y - y0) <= RADIO_TEXTOS_CM]
    splitters: list[dict[str, Any]] = []
    notas = ["Emparejada por nombre en el diagrama (sin coordenada en Visio)"]
    _leer_textos(cercanos, archivo["nombre"], splitters, set(), notas)
    detalle.update(archivos=[archivo], splitters_y_puertos=splitters, notas=notas)
    return detalle


def _parada_por_nombre(fuente: _Fuente, emparejado: dict[str, Any], parada: dict[str, Any]) -> dict[str, Any]:
    """The connection stop of a path matched by name (origen.py cases c and d)."""
    if emparejado.get("metodo") == "c" and emparejado.get("nodo_id") is not None:
        fila = fuente.filas(f"SELECT {', '.join(_COLUMNAS_NODO)} FROM nodos WHERE id = ?", (emparejado["nodo_id"],))
        if fila:
            return dict(dict(zip(_COLUMNAS_NODO, fila[0])), identificacion="por_nombre")
        return dict(parada, identificacion="por_nombre")
    return {"id": None, "nombre": emparejado.get("nombre_diagrama") or parada["nombre"], "tipo": "MUFA",
            "propietario": None, "lat": None, "lon": None, "notas": None, "zona": None,
            "identificacion": "por_nombre"}


def _detalle(fuente: _Fuente, parada: dict[str, Any]) -> dict[str, Any]:
    nodo_id = parada.get("id")
    detalle = {"archivos": [], "hilos_anillo": [], "splitters_y_puertos": [], "clientes": [], "notas": []}
    if nodo_id is None:
        return detalle
    archivos = _archivos(fuente, nodo_id)
    clientes, splitters = _servicios(fuente, nodo_id)
    vistos = {" ".join(s["texto"].split()).upper() for s in splitters}
    notas: list[str] = []
    for archivo in [a for a in archivos if a["diagrama"]][:4]:
        _leer_textos(_textos_de_mufa(fuente, archivo), archivo["nombre"], splitters, vistos, notas)
    for nota in (parada.get("notas") or "").split(","):
        nota = nota.strip()
        if nota and nota not in notas:
            notas.insert(0, nota)
    for archivo in [a for a in archivos if a["diagrama"]][:MAX_DIAGRAMAS]:
        archivo["ancla"] = _ancla_en_diagrama(fuente, archivo, parada.get("nombre") or "")
    detalle.update(archivos=[{k: v for k, v in a.items() if k != "texto_original"} for a in archivos],
                   hilos_anillo=_hilos_anillo(fuente, nodo_id), splitters_y_puertos=splitters[:MAX_TEXTOS],
                   clientes=clientes, notas=notas)
    return detalle


def _fuente_hilos(detalle: dict[str, Any]) -> str:
    if detalle["hilos_anillo"]:
        return "excel"
    if detalle["splitters_y_puertos"]:
        return "texto_diagrama"
    return "sin_dato"


# --------------------------------------------------------------------------- API

def ruta_fusion(origen_trafico: dict[str, Any], conexion: dict[str, Any], visio_con: Any = None,
                archivo_sqlite: Path | None = None, avisos: list[str] | None = None) -> list[dict[str, Any]]:
    """One entry per mufa of the traffic-origin path, OLT side first and the connection mufa last.

    origen_trafico["camino"] comes from origen.find_traffic_origin: Visio mufa names from the
    connection mufa to the mufa labelled with the node, so it is reversed here. No path (or no
    diagrams database) -> empty list and a warning appended to `avisos`.

    Each stop carries "fusiones_piloto": the pilot's detected fusions when the fusiones_piloto
    table exists (a list, maybe empty), or None when it does not exist.

    When the connection mufa was matched by name (origen_trafico["emparejamiento"], origen.py
    cases c / d) that stop has identificacion "por_nombre" ("Por nombre – validar" in the viewer)
    and, for a mufa drawn without coordinates, the diagram where its name was found.
    """
    avisos = avisos if avisos is not None else []
    if archivo_sqlite is None:
        archivo_sqlite = get_settings().red_fibra_db
    fuente = _Fuente(visio_con, archivo_sqlite)
    if not fuente.disponible:
        avisos.append("Ruta de fusión no disponible: no se encontró la base de diagramas (red_fibra)")
        return []
    try:
        camino = [n for n in (origen_trafico.get("camino") or []) if n]
        if not camino:
            diagnostico = origen_trafico.get("diagnostico") or {}
            motivo = diagnostico.get("detalle") or origen_trafico.get("motivo")
            avisos.append("Ruta de fusión vacía: el origen de tráfico no tiene camino en los diagramas"
                          + (f" ({motivo})" if motivo else ""))
            return []
        paradas = _resolver_camino(fuente, camino, conexion)
        emparejado = origen_trafico.get("emparejamiento") or {}
        if emparejado.get("metodo") in ("c", "d") and camino[0] == emparejado.get("nombre_diagrama"):
            paradas[0] = _parada_por_nombre(fuente, emparejado, paradas[0])
        paradas.reverse()                                       # OLT side first
        hay_piloto = fuente.tiene_tabla("fusiones_piloto")
        resultado = []
        total = len(paradas)
        for i, parada in enumerate(paradas):
            por_nombre_sin_nodo = parada["identificacion"] == "por_nombre" and parada.get("id") is None
            detalle = _detalle_por_nombre(fuente, emparejado) if por_nombre_sin_nodo else _detalle(fuente, parada)
            if not hay_piloto:
                piloto = None
            elif parada.get("id") is None:
                piloto = []
            else:
                piloto = _fusiones_piloto(fuente, _archivos(fuente, parada["id"]))
            resultado.append({
                "orden": i + 1,
                "nombre": parada["nombre"],
                "nodo_id": parada.get("id"),
                "tipo": parada.get("tipo"),
                "propietario": parada.get("propietario"),
                "lat": parada.get("lat"),
                "lon": parada.get("lon"),
                "zona": parada.get("zona"),
                "identificacion": parada["identificacion"],
                "emparejado_por_nombre": parada["identificacion"] == "por_nombre",
                "es_mufa_del_nodo": i == 0 and bool(camino) and origen_trafico.get("nodo") is not None,
                "es_conexion": i == total - 1,
                "fuente_hilos": _fuente_hilos(detalle),   # Excel / diagram text only, never the pilot
                **detalle,
                "fusiones_piloto": piloto,
            })
        log.info("Fusion route: %d stops from %s", len(resultado), fuente.nombre)
        return resultado
    finally:
        fuente.cerrar()


# --------------------------------------------------------------------------- buscador de mufas

def normalizar_busqueda(texto: str) -> list[str]:
    """Search words written like nodos.nombre_normalizado (red_fibra/importador.normalizar):
    no accents, upper case, MF/MC/MUFAS -> MUFA, MN -> MINI NODO, without filler words."""
    plano = unicodedata.normalize("NFD", texto or "")
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn").upper()
    plano = re.sub(r"\bMF\b|\bMC\b|\bMUFAS?\b", " MUFA ", plano)
    plano = re.sub(r"\bMN\b", " MINI NODO ", plano)
    plano = re.sub(r"[^A-Z0-9 ]", " ", plano)
    palabras = [p for p in plano.split() if p not in STOP_BUSQUEDA]
    # "MUFA" alone matches half the network: only kept when it is the only word
    return [p for p in palabras if p != "MUFA"] or palabras


def buscar_mufas(texto: str, visio_con: Any = None, archivo_sqlite: Path | None = None,
                 limite: int = MAX_RESULTADOS) -> list[dict[str, Any]]:
    """Network nodes (mufas, nodos, ODF...) whose name contains every word of `texto`.

    Exact name first, then the nodes drawn in more diagrams. Clients are left out.
    """
    palabras = normalizar_busqueda(texto)
    if not palabras or len(" ".join(palabras)) < 2:
        return []
    if archivo_sqlite is None:
        archivo_sqlite = get_settings().red_fibra_db
    fuente = _Fuente(visio_con, archivo_sqlite)
    if not fuente.disponible:
        raise FileNotFoundError("base de diagramas no disponible")
    exacto = " ".join((texto or "").split()).upper()
    condicion = " AND ".join(["n.nombre_normalizado LIKE ?"] * len(palabras))
    try:
        filas = fuente.filas(
            "SELECT n.id, n.nombre, n.tipo, n.zona, n.lat, n.lon, n.fuente_coord, n.notas, "
            "(SELECT count(DISTINCT a.archivo_id) FROM nodo_apariciones a JOIN archivos f ON f.id = a.archivo_id "
            " WHERE a.nodo_id = n.id AND f.estado = 'ok' AND f.formato <> 'xlsx') AS diagramas "
            f"FROM nodos n WHERE n.tipo <> 'CLIENTE' AND (({condicion}) OR upper(n.nombre) LIKE ?) "
            "ORDER BY CASE WHEN upper(n.nombre) = ? THEN 0 ELSE 1 END, diagramas DESC, n.nombre LIMIT ?",
            tuple(f"%{p}%" for p in palabras) + (f"%{exacto}%", exacto, int(limite)))
    finally:
        fuente.cerrar()
    columnas = ("id", "nombre", "tipo", "zona", "lat", "lon", "fuente_coord", "notas", "diagramas")
    return [dict(zip(columnas, f)) for f in filas]


MAX_RESULTADOS_DIAGRAMA = 60
TOLERANCIA_COORDENADA_M = 25.0         # a coordinate typed is the one written in the diagram if it is this close
_SINONIMOS_MUFA = {"MF", "MC", "MUFA", "MUFAS"}
_RE_GRADO_DECIMAL = re.compile(r"(\d+\.\d+)\s*[°º˚�]+")


def _plano(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9.,\- ]", " ", sin.upper()).split())


def buscar_en_diagrama(md5: str, texto: str, visio_con: Any = None, archivo_sqlite: Path | None = None,
                       limite: int = MAX_RESULTADOS_DIAGRAMA) -> dict[str, Any]:
    """Texts of one Visio diagram that match what was typed, with where they are drawn (cm on the page) so the viewer can go there.

    A coordinate (any format of the search box: 12.1115, -86.2340 / N12°06'41" …) finds the texts that WRITE a coordinate within
    25 m of it, nearest first, and says how far each one is. Anything else is a text search: every word must be in the text
    (accents and case ignored; MF / MC / MUFA are the same word). Texts without a position are left out.
    """
    from visor_rutas import coordenadas, masivas
    md5, _ = _validar(md5, 0)
    consulta = " ".join((texto or "").split())
    vacio: dict[str, Any] = {"modo": "texto", "resultados": [], "total": 0}
    if len(consulta) < 2:
        return vacio
    odg = ruta_odg(md5)
    if not odg.is_file():
        raise FileNotFoundError("diagrama no convertido")
    ancho_cm, alto_cm = _tamano_pagina_cm(odg)
    if archivo_sqlite is None:
        archivo_sqlite = get_settings().red_fibra_db
    fuente = _Fuente(visio_con, archivo_sqlite)
    if not fuente.disponible:
        raise FileNotFoundError("base de diagramas no disponible")
    try:
        filas = fuente.filas("SELECT pagina, x_cm, y_cm, texto FROM textos_crudos WHERE x_cm IS NOT NULL AND y_cm IS NOT NULL AND archivo_id IN "
                             "(SELECT id FROM archivos WHERE md5 = ?)", (md5,))
    finally:
        fuente.cerrar()

    def item(p: Any, x: Any, y: Any, t: str, **extra: Any) -> dict[str, Any]:
        return {"texto": _limpio(t)[:160], "pagina": p, "x_cm": float(x), "y_cm": float(y), "ancho_cm": ancho_cm, "alto_cm": alto_cm, **extra}

    resultado = coordenadas.interpretar(consulta)
    if resultado.estado in (coordenadas.OK, coordenadas.INVERTIDA):
        lat, lon = (resultado.lat, resultado.lon) if resultado.estado == coordenadas.OK else tuple(resultado.sugerencia)
        halladas: list[dict[str, Any]] = []
        for p, x, y, t in filas:
            if not re.search(r"\d", t or ""):
                continue
            # the diagrams write «12.111510°, -86.234059°» (the degree sign is often stored as a broken character): without it the pair is a plain one
            for punto in masivas._desde_texto([_RE_GRADO_DECIMAL.sub(r"\1", t or "")]):
                if punto["lat"] is None:
                    continue
                d = _distance_m(lat, lon, punto["lat"], punto["lon"])
                if d <= TOLERANCIA_COORDENADA_M:
                    halladas.append(item(p, x, y, t, coordenada={"lat": punto["lat"], "lon": punto["lon"]}, distancia_m=round(d, 1)))
                    break
        halladas.sort(key=lambda r: (r["distancia_m"], r["y_cm"], r["x_cm"]))
        return {"modo": "coordenada", "consulta": {"lat": lat, "lon": lon}, "resultados": halladas[:limite], "total": len(halladas)}

    palabras = _plano(consulta).split()
    grupos = [_SINONIMOS_MUFA if p in _SINONIMOS_MUFA else {p} for p in palabras]
    vistos: set[tuple[str, int, int]] = set()
    halladas = []
    for p, x, y, t in filas:
        plano = _plano(t or "")
        if not plano or not all(any(a in plano for a in alternativas) for alternativas in grupos):
            continue
        clave = (plano, round(float(x) * 10), round(float(y) * 10))
        if clave in vistos:
            continue
        vistos.add(clave)
        puntaje = 0 if plano == " ".join(palabras) else 1 if plano.startswith(palabras[0]) else 2
        halladas.append((puntaje, len(plano), float(y), float(x), item(p, x, y, t)))
    halladas.sort(key=lambda r: r[:4])
    return {"modo": "texto", "resultados": [r[4] for r in halladas[:limite]], "total": len(halladas)}


def detalle_mufa(nodo_id: int, visio_con: Any = None, archivo_sqlite: Path | None = None) -> dict[str, Any] | None:
    """Everything the viewer shows for one searched mufa: same data as a fusion-route stop
    (diagrams with the mufa's position in each, Excel hilos, splitters, clients, notes, pilot)."""
    if archivo_sqlite is None:
        archivo_sqlite = get_settings().red_fibra_db
    fuente = _Fuente(visio_con, archivo_sqlite)
    if not fuente.disponible:
        raise FileNotFoundError("base de diagramas no disponible")
    try:
        fila = fuente.filas(f"SELECT {', '.join(_COLUMNAS_NODO)} FROM nodos WHERE id = ?", (int(nodo_id),))
        if not fila:
            return None
        nodo = dict(zip(_COLUMNAS_NODO, fila[0]))
        detalle = _detalle(fuente, nodo)
        piloto = (_fusiones_piloto(fuente, _archivos(fuente, nodo["id"]))
                  if fuente.tiene_tabla("fusiones_piloto") else None)
        return {"nodo_id": nodo["id"], "nombre": nodo["nombre"], "tipo": nodo["tipo"],
                "propietario": nodo["propietario"], "lat": nodo["lat"], "lon": nodo["lon"], "zona": nodo["zona"],
                "requiere_revision": bool(nodo["requiere_revision"]), "fuente_hilos": _fuente_hilos(detalle),
                **detalle, "fusiones_piloto": piloto}
    finally:
        fuente.cerrar()


# --------------------------------------------------------------------------- diagrama en SVG / PNG

_conversion_lock = threading.Lock()


def _tamano_pagina_cm(odg: Path) -> tuple[float, float]:
    """(width, height) of the drawing page from styles.xml; A4 landscape if not found."""
    try:
        estilos = zipfile.ZipFile(odg).read("styles.xml").decode("utf-8", "ignore")
    except (OSError, KeyError, zipfile.BadZipFile):
        return 29.7, 21.0
    ancho = re.search(r'fo:page-width="([\d.]+)(cm|mm|in)"', estilos)
    alto = re.search(r'fo:page-height="([\d.]+)(cm|mm|in)"', estilos)
    if not (ancho and alto):
        return 29.7, 21.0
    a_cm = lambda m: float(m.group(1)) * {"cm": 1, "mm": 0.1, "in": 2.54}[m.group(2)]
    return a_cm(ancho), a_cm(alto)


def ruta_png(md5: str, pagina: int = 0) -> Path:
    return CACHE_DIAGRAMAS / f"{md5}_{int(pagina)}.png"


def ruta_svg(md5: str) -> Path:
    return CACHE_DIAGRAMAS / f"{md5}_0.svg"


def _validar(md5: str, pagina: int) -> tuple[str, int]:
    md5 = str(md5 or "").lower()
    if not RE_MD5.match(md5):
        raise ValueError("Identificador de diagrama no válido")
    pagina = int(pagina)
    if pagina < 0:
        raise ValueError("Página no válida")
    return md5, pagina


def ruta_odg(md5: str) -> Path:
    """Local path of the converted diagram `<md5>.odg`; if the local copy is missing it is written from the database store first.
    The path may still not exist (a diagram that was never converted)."""
    ruta = CACHE_ODG / f"{md5}.odg"
    if not ruta.is_file() and RE_MD5.match(str(md5)):
        almacen_archivos.restaurar("odg", ruta.name, ruta)
    return ruta


def diagrama_svg(md5: str) -> Path | None:
    """SVG (vector) of a cached diagram, converted once with LibreOffice.

    Preferred over the PNG: the diagrams are drawn in vectors and some are metres wide (one is
    4.45 m), so any bitmap is unreadable when zoomed; the SVG stays sharp at every zoom.
    Same return values and errors as diagrama_png (all diagrams have one page).
    """
    md5, _ = _validar(md5, 0)
    return _convertir(md5, 0, ruta_svg(md5), "svg", lambda odg: "svg:draw_svg_Export")


def diagrama_png(md5: str, pagina: int = 0) -> Path | None:
    """PNG of a cached diagram (datos/cache/odg/<md5>.odg), converted once with LibreOffice.

    Returns None when LibreOffice is not installed. Raises ValueError for a malformed md5 or page,
    FileNotFoundError when the .odg is not in the cache and RuntimeError when the conversion fails.
    """
    md5, pagina = _validar(md5, pagina)

    def filtro(odg: Path) -> str:
        ancho_cm, alto_cm = _tamano_pagina_cm(odg)
        ancho_px = ANCHO_PNG_PX
        alto_px = max(1, round(ANCHO_PNG_PX * alto_cm / ancho_cm))
        if alto_px > ALTO_MAX_PX:
            ancho_px, alto_px = max(1, round(ancho_px * ALTO_MAX_PX / alto_px)), ALTO_MAX_PX
        return ('png:draw_png_Export:{"PixelWidth":{"type":"long","value":"%d"},'
                '"PixelHeight":{"type":"long","value":"%d"},'
                '"PageRange":{"type":"string","value":"%d"}}' % (ancho_px, alto_px, pagina + 1))

    return _convertir(md5, pagina, ruta_png(md5, pagina), "png", filtro)


def _convertir(md5: str, pagina: int, destino: Path, extension: str, filtro_de: Any) -> Path | None:
    """Convert datos/cache/odg/<md5>.odg with LibreOffice (headless, temporary profile) once."""
    if destino.is_file() and destino.stat().st_size > 0:
        return destino
    if almacen_archivos.restaurar("diagramas", destino.name, destino) and destino.stat().st_size > 0:
        return destino
    odg = ruta_odg(md5)
    if not odg.is_file():
        raise FileNotFoundError(f"El diagrama {md5} no está en la base ni en datos/cache/odg")
    soffice = recalc.find_soffice(get_settings().libreoffice_path)
    if soffice is None:
        return None
    with _conversion_lock:                    # one LibreOffice at a time; a second request reuses the file
        if destino.is_file() and destino.stat().st_size > 0:
            return destino
        filtro = filtro_de(odg)
        trabajo = Path(tempfile.mkdtemp(prefix="visor-diagrama-"))
        perfil = Path(tempfile.mkdtemp(prefix="visor-lo-perfil-"))
        try:
            copia = trabajo / f"{md5}.odg"
            shutil.copyfile(odg, copia)
            comando = [soffice, f"-env:UserInstallation={perfil.as_uri()}", "--headless", "--norestore",
                       "--convert-to", filtro, "--outdir", str(trabajo), str(copia)]
            try:
                subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=TIMEOUT_CONVERSION_S, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("LibreOffice tardó demasiado en convertir el diagrama") from exc
            generado = trabajo / f"{md5}.{extension}"
            if not generado.is_file() or generado.stat().st_size == 0:
                raise RuntimeError("LibreOffice no pudo convertir el diagrama")
            CACHE_DIAGRAMAS.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_suffix(".tmp")
            shutil.copyfile(generado, temporal)
            os.replace(temporal, destino)
            almacen_archivos.guardar_archivo("diagramas", destino.name, destino)
        finally:
            shutil.rmtree(trabajo, ignore_errors=True)
            shutil.rmtree(perfil, ignore_errors=True)
    log.info("Diagram %s page %d converted to %s", md5, pagina, destino.name)
    return destino


def diagrama_mejor(md5: str) -> tuple[Path | None, str]:
    """(file, "svg" | "png"): the SVG, or the PNG when the SVG export fails."""
    try:
        return diagrama_svg(md5), "svg"
    except RuntimeError as exc:
        log.warning("SVG export of %s failed (%s); using PNG", md5, exc)
        return diagrama_png(md5), "png"
