"""Arranque del visor:  .venv\\Scripts\\pythonw.exe -m visor_rutas  (desde la carpeta del proyecto).

Por defecto abre la ventana HTML/Leaflet (ventana_web.py, pywebview + WebView2). Si pywebview
no está instalado o la ventana web falla (por ejemplo, sin WebView2), registra el motivo en
logs/visor.log y abre la ventana Tkinter (ventana.py). Con --tk se fuerza Tkinter.

Todo el log (también el de db/routing/main) va a logs/visor.log, no a logs/service.log.
"""
import logging
import os
import sys
import threading
from pathlib import Path

PROYECTO = Path(__file__).resolve().parent.parent
LOG_VISOR = PROYECTO / "logs" / "visor.log"

log = logging.getLogger("visor_rutas")


def _preparar_log() -> logging.Logger:
    # pythonw.exe no tiene consola: sys.stdout/stderr son None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if str(PROYECTO) not in sys.path:
        sys.path.insert(0, str(PROYECTO))
    try:
        # config.setup_logging is idempotent: main.py's own call (logs/service.log) becomes a no-op.
        from config import setup_logging
        setup_logging(LOG_VISOR, "INFO")
    except Exception:
        LOG_VISOR.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=LOG_VISOR, level=logging.INFO, encoding="utf-8",
                            format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    sys.excepthook = lambda t, e, tb: log.critical("Unhandled error", exc_info=(t, e, tb))
    threading.excepthook = lambda a: log.critical("Unhandled thread error",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return log


def elegir_interfaz(argv: list[str]) -> str:
    """"web" (pywebview) or "tk": --tk forces Tkinter; without pywebview Tkinter is used."""
    if "--tk" in argv:
        log.info("Tkinter viewer requested (--tk)")
        return "tk"
    try:
        import webview  # noqa: F401
    except Exception as exc:          # not installed, or pythonnet/.NET missing
        log.warning("pywebview not available (%s: %s); using the Tkinter viewer", type(exc).__name__, exc)
        return "tk"
    return "web"


def _abrir_web() -> bool:
    """True when the web window opened and was closed normally."""
    try:
        from visor_rutas.ventana_web import abrir
        log.info("Visor started (web)")
        abrir()
        return True
    except Exception as exc:
        log.exception("Web viewer failed (%s); falling back to Tkinter", type(exc).__name__)
        return False


def _abrir_tk() -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.report_callback_exception = lambda t, e, tb: log.error("Tk callback error", exc_info=(t, e, tb))
    try:
        # Imports main.py (settings from .env); a missing variable or package fails here.
        from visor_rutas.ventana import VisorRutas
        VisorRutas(root)
    except Exception as exc:
        log.exception("Visor could not start")
        root.withdraw()
        messagebox.showerror("Visor de rutas",
                             f"No se pudo iniciar el visor:\n\n{type(exc).__name__}: {exc}\n\n"
                             f"Detalle en {LOG_VISOR}")
        root.destroy()
        return
    log.info("Visor started (Tkinter)")
    root.mainloop()


def main(argv: list[str] | None = None) -> None:
    _preparar_log()
    os.chdir(PROYECTO)
    argv = sys.argv[1:] if argv is None else argv
    if elegir_interfaz(argv) == "web" and _abrir_web():
        return
    _abrir_tk()


if __name__ == "__main__":
    main()
