"""Arranque del visor para OTRAS computadoras (VisorRutas.exe, generado con herramientas\build_visor.bat).

Siempre en modo remoto: no hay bases de datos, .env, Google ni LibreOffice en esa PC; todo se
pide a la API del servidor (/visor/*) por el túnel de ngrok. La URL y la clave se escriben la
primera vez en la pantalla de configuración (quedan en %APPDATA%\\VisorRutas\\config.json).

Log: %LOCALAPPDATA%\\VisorRutas\\visor.log. Requiere WebView2 (viene con Windows 10/11); si no
está, se avisa con el enlace de descarga.

Desde el código (para probarlo sin empaquetar):  .venv\\Scripts\\python.exe -m visor_rutas.remoto_main
"""
import ctypes
import logging
import os
import sys
import threading
import winreg
from logging.handlers import RotatingFileHandler

TITULO = "Visor de rutas"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_MB_ICONERROR, _MB_ICONWARNING, _MB_YESNO, _IDYES = 0x10, 0x30, 0x04, 6

log = logging.getLogger("visor_rutas")


def _mensaje(texto: str, estilo: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, texto, TITULO, estilo)


def webview2_instalado() -> bool:
    """WebView2 Runtime registered for the machine or this user (Microsoft's documented keys)."""
    claves = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
              (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
              (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}")]
    for raiz, ruta in claves:
        try:
            with winreg.OpenKey(raiz, ruta) as clave:
                version, _ = winreg.QueryValueEx(clave, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def _ofrecer_webview2(motivo: str) -> None:
    if _mensaje(f"{motivo}\n\nEl visor necesita Microsoft Edge WebView2 Runtime (ya viene en Windows 10/11 "
                "actualizados). Se instala sin permisos de administrador.\n\n¿Abrir la página de descarga?\n"
                f"{WEBVIEW2_URL}", _MB_ICONWARNING | _MB_YESNO) == _IDYES:
        os.startfile(WEBVIEW2_URL)                                     # type: ignore[attr-defined]


def desbloquear_archivos() -> int:
    """Quita la marca de la web (flujo alternativo `Zone.Identifier`, "Mark of the Web") a los archivos de la aplicación.

    Un .zip descargado marca todo lo que se extrae de él y .NET se niega a cargar `Python.Runtime.dll` de pythonnet
    ("Failed to resolve Python.Runtime.Loader.Initialize"). Se llama ANTES de importar webview / pythonnet / clr. Devuelve cuántos
    archivos estaban marcados. Solo en el .exe empaquetado; ignora los archivos que no se dejan (permisos, en uso).
    """
    if not getattr(sys, "frozen", False):
        return 0
    raices = []
    for r in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable)):
        if r and os.path.isdir(r):
            r = os.path.abspath(r)
            if not any(r == x or r.startswith(x + os.sep) for x in raices):     # _internal lives inside the .exe folder
                raices = [x for x in raices if not x.startswith(r + os.sep)] + [r]
    desbloqueados = 0
    for raiz in raices:
        for carpeta, _, archivos in os.walk(raiz):
            for nombre in archivos:
                try:
                    os.remove(os.path.join(carpeta, nombre) + ":Zone.Identifier")
                    desbloqueados += 1
                except OSError:                                                # no mark (FileNotFoundError), no permission, in use
                    pass
    return desbloqueados


_PISTAS_PYTHONNET = ("python.runtime", "pythonnet", "clr_loader", "loader.initialize", "no module named 'clr'", "dotnet")
PASOS_DESBLOQUEAR = (
    "Windows bloqueó los archivos del programa porque vienen de un .zip descargado.\n\n"
    "Para arreglarlo:\n"
    "1. Borre la carpeta VisorRutas que extrajo.\n"
    "2. Clic derecho en VisorRutas.zip > Propiedades > marque «Desbloquear» > Aceptar.\n"
    "3. Vuelva a extraer el .zip y abra VisorRutas.exe.\n\n"
    "O, sin volver a extraer, en PowerShell (en la carpeta de VisorRutas):\n"
    "   Get-ChildItem -Recurse | Unblock-File")


def _preparar_log() -> str:
    # Windowed .exe: no console, sys.stdout / sys.stderr are None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    from visor_rutas.config_visor import carpeta_local
    carpeta = carpeta_local()
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / "visor.log"
    manejador = RotatingFileHandler(archivo, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(manejador)
    sys.excepthook = lambda t, e, tb: log.critical("Unhandled error", exc_info=(t, e, tb))
    threading.excepthook = lambda a: log.critical("Unhandled thread error",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return str(archivo)


def main() -> None:
    archivo_log = _preparar_log()
    log.info("Remote viewer started")
    log.info("Unblocked %d files marked as downloaded from the web (Zone.Identifier)", desbloquear_archivos())
    if not webview2_instalado():
        log.warning("WebView2 Runtime not found")
        _ofrecer_webview2("No se encontró Microsoft Edge WebView2 en esta computadora.")
        return
    try:
        from visor_rutas.ventana_web import abrir
        abrir(forzar_remoto=True)
    except Exception as exc:
        log.exception("Remote viewer could not start")
        texto = f"No se pudo abrir el visor:\n\n{type(exc).__name__}: {exc}\n\nDetalle en {archivo_log}"
        if any(p in str(exc).lower() for p in _PISTAS_PYTHONNET):
            # no Tkinter viewer in the .exe (the remote package leaves Tkinter and the local code out): the steps are the way out
            _mensaje(f"No se pudo abrir el visor.\n\n{PASOS_DESBLOQUEAR}\n\nDetalle técnico en {archivo_log}", _MB_ICONERROR)
        elif "webview2" in str(exc).lower() or "edgechromium" in str(exc).lower():
            _ofrecer_webview2(texto)
        else:
            _mensaje(texto, _MB_ICONERROR)


if __name__ == "__main__":
    main()
