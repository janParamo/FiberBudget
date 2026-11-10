"""Actualización automática del visor (VisorRutas.exe): al abrirse pregunta al servidor cuál es la versión vigente; si es más nueva que la suya, avisa, la descarga y se
reemplaza solo.

Cómo se reparte (ver docker/LEEME.md):
  1. En la PC de desarrollo, ``herramientas\\publicar_visor.bat`` arma el paquete (VisorRutas.zip, que lleva ``version.json`` junto al .exe) y lo sube al servidor
     (carpeta ``actualizaciones/`` de la VM: VisorRutas.zip + version.json con la versión, el tamaño y la suma SHA-256).
  2. El servicio lo ofrece en ``GET /visor/actualizacion`` (qué versión hay) y ``GET /visor/actualizacion/paquete`` (el zip), con la clave del visor de cada persona.
  3. El visor, al abrirse (remoto_main.main): compara, avisa, descarga a %TEMP%, verifica el tamaño y la suma, descomprime y lanza un ayudante (un .bat con robocopy) que
     espera a que el visor se cierre, copia los archivos nuevos sobre la carpeta del programa y lo vuelve a abrir. La URL y la clave están en %APPDATA%, no se tocan.

Solo usa la biblioteca estándar (más el proveedor remoto que recibe): entra en el .exe. Las funciones del servidor (leer_publicada) no abren nada de Windows.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

NOMBRE = "VisorRutas"
ARCHIVO_VERSION = "version.json"
ARCHIVO_PAQUETE = f"{NOMBRE}.zip"
_RE_VERSION = re.compile(r"^\d{1,4}(\.\d{1,6}){1,5}$")
_RE_SHA = re.compile(r"^[0-9a-f]{64}$")
ESPERA_TRAS_FALLO_S = 24 * 3600                       # after a failed update of a version it is not tried again for a day (the viewer opens as it was)
TIMEOUT_CONSULTA_S = 5
TIMEOUT_DESCARGA_S = 180
MAX_PAQUETE_BYTES = 400 * 1024 * 1024


class ErrorActualizacion(Exception):
    """Something that stops the update, in words for the user."""


# --------------------------------------------------------------------------- versions

def clave_version(version: str | None) -> tuple[int, ...]:
    """«2026.11.10.1530» -> (2026, 11, 10, 1530); () when it is not a version."""
    if not version or not _RE_VERSION.match(str(version)):
        return ()
    return tuple(int(p) for p in str(version).split("."))


def es_nueva(instalada: str | None, publicada: str | None) -> bool:
    """True when the published version is newer than the installed one (both must be valid versions)."""
    a, b = clave_version(instalada), clave_version(publicada)
    return bool(a and b and b > a)


def nueva_version() -> str:
    """The version of a package that is being made now: year.month.day.hourminute (it only grows)."""
    return time.strftime("%Y.%m.%d.%H%M")


def carpeta_programa() -> Path | None:
    """The folder of the installed program (where VisorRutas.exe is); None when it is not running as the .exe (from the code there is nothing to update)."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def version_instalada(carpeta: Path | None = None) -> str | None:
    """The version written next to the .exe by the packaging (None when there is no file: an old build or a run from the code)."""
    carpeta = carpeta or carpeta_programa()
    if carpeta is None:
        return None
    try:
        version = str(json.loads((carpeta / ARCHIVO_VERSION).read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return None
    return version if clave_version(version) else None


# --------------------------------------------------------------------------- the server: what is published

def leer_publicada(carpeta: Path) -> dict[str, Any] | None:
    """What the server offers: {version, sha256, tamano, creado} from ``version.json`` of its folder, only when the package is there with that size (so a
    half-uploaded package is never offered). None when nothing is published."""
    try:
        datos = json.loads((carpeta / ARCHIVO_VERSION).read_text(encoding="utf-8"))
        paquete = carpeta / ARCHIVO_PAQUETE
        version, sha, tamano = str(datos.get("version") or ""), str(datos.get("sha256") or "").lower(), int(datos.get("tamano") or 0)
        if not (clave_version(version) and _RE_SHA.match(sha) and 0 < tamano <= MAX_PAQUETE_BYTES and paquete.is_file() and paquete.stat().st_size == tamano):
            return None
    except (OSError, ValueError, TypeError):
        return None
    return {"version": version, "sha256": sha, "tamano": tamano, "creado": str(datos.get("creado") or "")}


# --------------------------------------------------------------------------- the viewer: ask, download, replace

def consultar(proveedor: Any, instalada: str | None) -> dict[str, Any] | None:
    """The published version when it is newer than `instalada`; None when the viewer is up to date or the server offers nothing (or an old server without this)."""
    respuesta = proveedor._pedir("GET", "/visor/actualizacion", timeout=TIMEOUT_CONSULTA_S)
    datos = respuesta.json()
    if not (isinstance(datos, dict) and datos.get("ok") and datos.get("disponible")):
        return None
    version, sha = str(datos.get("version") or ""), str(datos.get("sha256") or "").lower()
    if not (es_nueva(instalada, version) and _RE_SHA.match(sha)):
        return None
    return {"version": version, "sha256": sha, "tamano": int(datos.get("tamano") or 0)}


def descargar(proveedor: Any, info: dict[str, Any], destino: Path) -> Path:
    """Downloads the package to `destino` (a .zip) and checks its size and SHA-256; a damaged download is deleted and ErrorActualizacion says so."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    resumen, total = hashlib.sha256(), 0
    respuesta = proveedor._pedir("GET", "/visor/actualizacion/paquete", timeout=TIMEOUT_DESCARGA_S, stream=True)
    try:
        with destino.open("wb") as archivo:
            for trozo in respuesta.iter_content(chunk_size=256 * 1024):
                if not trozo:
                    continue
                total += len(trozo)
                if total > MAX_PAQUETE_BYTES:
                    raise ErrorActualizacion("El paquete de actualización es demasiado grande")
                resumen.update(trozo)
                archivo.write(trozo)
    except ErrorActualizacion:
        destino.unlink(missing_ok=True)
        raise
    except Exception as exc:                                                    # noqa: BLE001 - the connection dropped half way
        destino.unlink(missing_ok=True)
        raise ErrorActualizacion("Se cortó la descarga de la actualización") from exc
    finally:
        close = getattr(respuesta, "close", None)
        if close:
            close()
    if (info.get("tamano") and total != int(info["tamano"])) or resumen.hexdigest() != info["sha256"]:
        destino.unlink(missing_ok=True)
        raise ErrorActualizacion("La actualización llegó dañada (no coincide con la que publicó el servidor)")
    return destino


def _extraer(paquete: Path, destino: Path) -> Path:
    """Unzips into `destino` (it is emptied first) refusing paths that go out of it; returns the folder of the program inside (VisorRutas/)."""
    if destino.exists():
        shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    raiz = destino.resolve()
    with zipfile.ZipFile(paquete) as z:
        for nombre in z.namelist():
            objetivo = (destino / nombre).resolve()
            if objetivo != raiz and raiz not in objetivo.parents:
                raise ErrorActualizacion("El paquete de actualización no es válido")
        z.extractall(destino)
    nuevo = destino / NOMBRE
    if not (nuevo / f"{NOMBRE}.exe").is_file():
        raise ErrorActualizacion("El paquete de actualización no trae el programa")
    return nuevo


SCRIPT = r"""@echo off
rem Ayudante de la actualizacion del visor: espera a que se cierre, copia los archivos nuevos y lo abre. Lo escribe visor_rutas\actualizador.py
rem %1 = carpeta con la version nueva   %2 = carpeta del programa instalado   %3 = numero del proceso del visor   %4 = archivo de aviso de fallo   %5 = version
setlocal
set "NUEVO=%~1"
set "DESTINO=%~2"
set "PID=%~3"
set "FALLO=%~4"
set "VERSION=%~5"
set /a ESPERAS=0
:esperar
tasklist /FI "PID eq %PID%" /NH 2>nul | find /I "VisorRutas.exe" >nul
if errorlevel 1 goto copiar
set /a ESPERAS+=1
if %ESPERAS% GTR 60 goto copiar
timeout /t 1 /nobreak >nul
goto esperar
:copiar
robocopy "%NUEVO%" "%DESTINO%" /E /R:30 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 echo {"version": "%VERSION%"}> "%FALLO%"
start "" "%DESTINO%\VisorRutas.exe"
rmdir /s /q "%NUEVO%" >nul 2>&1
del /q "%~dp0*.zip" >nul 2>&1
exit /b 0
"""


def carpeta_escribible(carpeta: Path) -> bool:
    """The program can be replaced only when its folder can be written (the installer and the .zip put it in the user's own folder)."""
    prueba = carpeta / ".actualizacion_prueba"
    try:
        prueba.write_text("x", encoding="utf-8")
        prueba.unlink()
        return True
    except OSError:
        return False


def preparar(paquete: Path, programa: Path, trabajo: Path, version: str) -> tuple[Path, Path]:
    """Unzips the package and writes the helper; returns (script, folder with the new version). Nothing of the installed program is touched yet."""
    nuevo = _extraer(paquete, trabajo / "nuevo")
    if version_instalada(nuevo) != version:
        raise ErrorActualizacion("El paquete de actualización no es de la versión que anunció el servidor")
    script = trabajo / "actualizar.bat"
    script.write_text(SCRIPT, encoding="utf-8", newline="\r\n")
    return script, nuevo


def lanzar(script: Path, nuevo: Path, programa: Path, fallo: Path, version: str, pid: int | None = None) -> None:
    """Starts the helper apart from the viewer (it keeps running when the viewer closes). The caller closes the viewer right after."""
    banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", str(script), str(nuevo), str(programa), str(pid or os.getpid()), str(fallo), version],
                     creationflags=banderas, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fallo_reciente(archivo: Path, version: str, ahora: float | None = None) -> bool:
    """True when this version already failed to install on this PC in the last day: the viewer opens as it is instead of trying on every start."""
    try:
        if json.loads(archivo.read_text(encoding="utf-8")).get("version") != version:
            return False
        return (ahora if ahora is not None else time.time()) - archivo.stat().st_mtime < ESPERA_TRAS_FALLO_S
    except (OSError, ValueError):
        return False


def actualizar_al_abrir(proveedor: Any, avisar: Callable[[str], None], carpeta_trabajo: Path, archivo_fallo: Path, *, programa: Path | None = None,
                        instalada: str | None = None) -> bool:
    """Called when the viewer opens. True when an update was started: the caller must close the viewer at once (the helper replaces it and opens it again).
    Never raises: any problem is written to the log and the viewer opens as it is."""
    programa = programa or carpeta_programa()
    instalada = instalada or version_instalada(programa)
    if programa is None or not instalada:
        return False
    try:
        info = consultar(proveedor, instalada)
        if not info:
            return False
        if fallo_reciente(archivo_fallo, info["version"]):
            log.info("Update %s failed before on this PC: not tried again for a day", info["version"])
            return False
        if not carpeta_escribible(programa):
            log.warning("Update %s: the folder of the program cannot be written (%s)", info["version"], programa)
            avisar("Hay una versión nueva del visor, pero esta carpeta no permite actualizarla sola.\n\nPida el instalador o el .zip nuevo a quien administra el servidor.")
            return False
        avisar(f"Hay una versión nueva del visor ({info['version']}).\n\nSe va a actualizar ahora: pulse Aceptar y espere unos segundos, el visor se cerrará y se abrirá solo.")
        paquete = descargar(proveedor, info, carpeta_trabajo / f"{NOMBRE}-{info['version']}.zip")
        archivo_fallo.parent.mkdir(parents=True, exist_ok=True)
        script, nuevo = preparar(paquete, programa, carpeta_trabajo, info["version"])
        lanzar(script, nuevo, programa, archivo_fallo, info["version"])
        log.info("Update %s -> %s started", instalada, info["version"])
        return True
    except Exception as exc:                                                     # noqa: BLE001 - the viewer must open anyway
        log.warning("The viewer could not be updated (%s: %s)", type(exc).__name__, str(exc)[:200])
        if isinstance(exc, ErrorActualizacion):
            avisar(f"No se pudo actualizar el visor: {exc}.\n\nSe abrirá la versión actual.")
        return False
