"""Arranque del visor para OTRAS computadoras (VisorRutas.exe, generado con build_visor.bat).

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
        if "webview2" in str(exc).lower() or "edgechromium" in str(exc).lower():
            _ofrecer_webview2(texto)
        else:
            _mensaje(texto, _MB_ICONERROR)


if __name__ == "__main__":
    main()
