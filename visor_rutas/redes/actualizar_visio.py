"""Actualizar los diagramas Visio desde el programa: subir los archivos nuevos o corregidos y poner al día la base de diagramas.

Antes esto solo se hacía por la línea de comandos (`red_fibra/importador.py`). Dos pasos, solo para administradores:

  1. `subir_visio`: el archivo que llega (`.vsd`, `.vsdx`, el Excel de anillos `.xlsx`, o un `.zip` con varios) reemplaza al que tiene el mismo nombre en la carpeta de
     diagramas (`VISIO_ORIGEN`, por defecto `datos/visio/DIAGRAMAS ACTUALIZADOS`), en el mismo lugar; lo anterior no se borra: se guarda en `anteriores/` con la fecha. Un
     archivo con un nombre que no existe se agrega en la carpeta que se indique («Nuevos» por defecto).
  2. `actualizar_diagramas`: corre el importador (convierte con LibreOffice solo lo nuevo o cambiado, lee los textos y los nodos y publica la base de diagramas en
     PostgreSQL) en segundo plano; `progreso` dice en qué paso va. Mientras corre no se puede lanzar otra y los diagramas ya cargados se siguen viendo. La red migrada
     del módulo de redes (mufas, cables) NO se toca: se actualiza con la migración y con «Mufas del KMZ» del esquema de zona.
"""
import collections
import datetime as dt
import io
import logging
import os
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

from visor_rutas import subidas
from visor_rutas.redes import usuarios
from visor_rutas.redes.db import DatosInvalidos, SinPermiso

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[2]
EXTENSIONES = (".vsd", ".vsdx", ".xlsx")
MAX_ARCHIVO = 150 * 1024 * 1024
MAX_ARCHIVOS_ZIP = 300
MAX_TOTAL_ZIP = 600 * 1024 * 1024
FIRMAS = {".vsd": (b"\xd0\xcf\x11\xe0",), ".vsdx": (b"PK",), ".xlsx": (b"PK",)}
CARPETA_NUEVOS = "Nuevos"
MAX_LINEAS = 400

_candado = threading.Lock()
_trabajo: dict[str, Any] = {"id": None, "proceso": None, "inicio": None, "fin": None, "codigo": None, "lineas": collections.deque(maxlen=MAX_LINEAS), "por": None}


def _exigir_admin(actor: dict[str, Any]) -> None:
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede actualizar los diagramas Visio")


def carpeta_origen() -> Path:
    """The folder with the Visio diagrams (VISIO_ORIGEN of the .env, else datos/visio/DIAGRAMAS ACTUALIZADOS)."""
    valor = os.getenv("VISIO_ORIGEN", "").strip()
    ruta = Path(valor) if valor else RAIZ / "datos" / "visio" / "DIAGRAMAS ACTUALIZADOS"
    return ruta if ruta.is_absolute() else RAIZ / ruta


def _nombre_seguro(nombre: str) -> str:
    return re.sub(r"[^\w .()\-]", "_", Path(str(nombre or "").replace("\\", "/")).name).strip(" .")


def _carpeta_segura(nombre: str) -> str:
    partes = [re.sub(r"[^\w .()\-]", "_", p).strip(" .") for p in re.split(r"[\\/]+", str(nombre or "")) if p.strip(" .") not in ("", "..")]
    return "/".join(p for p in partes if p) or CARPETA_NUEVOS


def _valido(nombre: str, datos: bytes) -> str | None:
    """None if the file can be a Visio / Excel diagram; else the reason."""
    ext = Path(nombre).suffix.lower()
    if nombre.startswith("~$"):
        return "es un archivo temporal de Office (~$)"
    if ext not in EXTENSIONES:
        return f"solo se aceptan {', '.join(EXTENSIONES)} (o un .zip con ellos)"
    if not datos:
        return "está vacío"
    if len(datos) > MAX_ARCHIVO:
        return f"pesa más de {MAX_ARCHIVO // (1024 * 1024)} MB"
    if not any(datos.startswith(f) for f in FIRMAS[ext]):
        return "no es un archivo " + ext[1:].upper() + " válido (está dañado o es de otro tipo)"
    return None


def _archivos_de(nombre: str, crudo: bytes) -> list[tuple[str, str, bytes]]:
    """[(name, folder-inside-the-zip or "", bytes)] of what comes: the file itself, or the Visio / Excel files inside a .zip."""
    if not nombre.lower().endswith(".zip"):
        return [(_nombre_seguro(nombre), "", crudo)]
    try:
        z = zipfile.ZipFile(io.BytesIO(crudo))
    except zipfile.BadZipFile:
        raise DatosInvalidos({"archivo": "El .zip está dañado"}) from None
    miembros = [i for i in z.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in EXTENSIONES]
    if len(miembros) > MAX_ARCHIVOS_ZIP or sum(i.file_size for i in miembros) > MAX_TOTAL_ZIP:
        raise DatosInvalidos({"archivo": "El .zip trae demasiados archivos o pesa demasiado"})
    return [(_nombre_seguro(i.filename), _carpeta_segura(str(Path(i.filename.replace("\\", "/")).parent)) if "/" in i.filename.replace("\\", "/") else "", z.read(i)) for i in miembros]


def _buscar(origen: Path, nombre: str) -> Path | None:
    if not origen.is_dir():
        return None
    objetivo = nombre.lower()
    return next((p for p in sorted(origen.rglob("*")) if p.is_file() and p.name.lower() == objetivo), None)


def estado(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """The folder of diagrams (how many files) and what the last update did."""
    _exigir_admin(actor)
    origen = carpeta_origen()
    archivos = [p for p in origen.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES] if origen.is_dir() else []
    return {"carpeta": str(origen), "archivos": len(archivos), "visio": sum(p.suffix.lower() != ".xlsx" for p in archivos), **_resumen_trabajo()}


def subir_visio(con: Any, actor: dict[str, Any], *, subida_id: str, nombre: str = "", carpeta: str = "") -> dict[str, Any]:
    """Puts the uploaded file (or the files of an uploaded .zip) in the folder of diagrams: the one with the same name is replaced in place (the old one goes to
    `anteriores/`), a new name is added in `carpeta`. {"reemplazados": [...], "nuevos": [...], "rechazados": [{nombre, motivo}]}."""
    _exigir_admin(actor)
    if _corriendo():
        raise DatosInvalidos({"archivo": "Se está actualizando la base de diagramas: espere a que termine para subir más archivos"})
    try:
        nombre_subido, crudo = subidas.almacen.tomar(subida_id)
    except subidas.ErrorSubida as exc:
        raise DatosInvalidos({"archivo": str(exc)}) from None
    nombre = nombre or nombre_subido
    origen = carpeta_origen()
    origen.mkdir(parents=True, exist_ok=True)
    sello = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    anteriores = origen.parent / "anteriores" / sello
    carpeta_nuevos = _carpeta_segura(carpeta)
    resultado: dict[str, Any] = {"reemplazados": [], "nuevos": [], "rechazados": []}
    for nom, subcarpeta, datos in _archivos_de(nombre, crudo):
        motivo = _valido(nom, datos)
        if motivo:
            resultado["rechazados"].append({"nombre": nom, "motivo": motivo})
            continue
        existente = _buscar(origen, nom)
        if existente is not None:
            if existente.read_bytes() == datos:
                resultado["rechazados"].append({"nombre": nom, "motivo": "es idéntico al que ya está"})
                continue
            relativa = existente.relative_to(origen)
            (anteriores / relativa).parent.mkdir(parents=True, exist_ok=True)
            existente.replace(anteriores / relativa)
            destino = existente
            resultado["reemplazados"].append(str(relativa).replace("\\", "/"))
        else:
            destino = origen / (subcarpeta or carpeta_nuevos) / nom
            destino.parent.mkdir(parents=True, exist_ok=True)
            resultado["nuevos"].append(str(destino.relative_to(origen)).replace("\\", "/"))
        temporal = destino.with_name(destino.name + ".tmp")
        temporal.write_bytes(datos)
        temporal.replace(destino)
    log.info("Diagramas Visio: %d reemplazados, %d nuevos, %d rechazados (%s)", len(resultado["reemplazados"]), len(resultado["nuevos"]), len(resultado["rechazados"]),
             actor.get("nombre") or actor.get("id"))
    return {**resultado, "carpeta": str(origen), "anteriores": str(anteriores) if anteriores.is_dir() else None}


# --------------------------------------------------------------------------- poner al día la base de diagramas (el importador, en segundo plano)

def _corriendo() -> bool:
    with _candado:
        p = _trabajo["proceso"]
        return p is not None and p.poll() is None


def _comando(origen: Path) -> list[str]:
    """The importer: it converts only what is new or changed (cache by md5) and publishes to PostgreSQL when VISIO_DB_* is set. Overridden in the tests."""
    from config import get_settings
    orden = [sys.executable, str(RAIZ / "red_fibra" / "importador.py"), "--origen", str(origen)]
    soffice = get_settings().libreoffice_path
    return orden + (["--soffice", soffice] if soffice else [])


def _leer_salida(proceso: subprocess.Popen) -> None:
    for linea in iter(proceso.stdout.readline, ""):
        with _candado:
            _trabajo["lineas"].append(linea.rstrip())
    proceso.wait()
    with _candado:
        _trabajo["fin"] = dt.datetime.now().isoformat(timespec="seconds")
        _trabajo["codigo"] = proceso.returncode
    log.info("Diagramas Visio: el importador terminó con código %s", proceso.returncode)


def actualizar_diagramas(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Starts the importer over the folder of diagrams, in the background. One at a time."""
    _exigir_admin(actor)
    origen = carpeta_origen()
    if not origen.is_dir() or not any(origen.rglob("*.vsd*")):
        raise DatosInvalidos({"archivo": f"No hay diagramas Visio en {origen}: suba primero los archivos"})
    with _candado:
        if _trabajo["proceso"] is not None and _trabajo["proceso"].poll() is None:
            raise DatosInvalidos({"archivo": "Ya se está actualizando la base de diagramas"})
        entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        proceso = subprocess.Popen(_comando(origen), cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=entorno)
        _trabajo.update(id=dt.datetime.now().strftime("%Y%m%d-%H%M%S"), proceso=proceso, inicio=dt.datetime.now().isoformat(timespec="seconds"), fin=None, codigo=None,
                        por=actor.get("nombre") or actor.get("id"))
        _trabajo["lineas"].clear()
    threading.Thread(target=_leer_salida, args=(proceso,), name="visio-importador", daemon=True).start()
    log.info("Diagramas Visio: importador lanzado por %s", _trabajo["por"])
    return {"id": _trabajo["id"], **_resumen_trabajo()}


def _resumen_trabajo() -> dict[str, Any]:
    with _candado:
        proceso = _trabajo["proceso"]
        lineas = list(_trabajo["lineas"])
        paso = next((m.groups() for m in (re.match(r"^\s*(\d)/(\d)\s+(.*)$", l) for l in reversed(lineas)) if m), None)
        activo = proceso is not None and proceso.poll() is None
        return {"actualizacion": {"id": _trabajo["id"], "activa": activo, "inicio": _trabajo["inicio"], "fin": _trabajo["fin"], "codigo": _trabajo["codigo"], "por": _trabajo["por"],
                                  "paso": {"n": int(paso[0]), "de": int(paso[1]), "texto": paso[2]} if paso else None, "ultimas": lineas[-12:]} if _trabajo["id"] else None}


def progreso(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    _exigir_admin(actor)
    return _resumen_trabajo()
