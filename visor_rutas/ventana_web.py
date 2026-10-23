"""Ventana del visor de rutas en HTML + Leaflet dentro de pywebview (WebView2).

Sin servidor HTTP ni puertos: carga visor_rutas/web/visor.html como file:// y expone a
JavaScript la clase Api (js_api). pywebview ejecuta cada llamada de js_api en su propio hilo,
así que el cálculo no congela la ventana.

Dos modos (config_visor.py, %APPDATA%\\VisorRutas\\config.json):
  - local:  los métodos de Api calculan aquí (calculo.py, fusion.py, red.py, presupuesto_visor.py)
            con las bases y Google de esta PC, como siempre;
  - remoto: cada método de Api llama al mismo método de remoto.ProveedorRemoto, que pide lo mismo
            a la API del servidor (/visor/*, visor_api.py) por el túnel de ngrok.
La página (visor.html / visor.js) es la misma en los dos modos.

El código local se importa dentro de un try: el .exe del modo remoto no lo incluye (ni main.py,
ni bases, ni .env) y entonces el visor solo puede funcionar en modo remoto.
`import webview` va dentro de abrir(): este módulo (y Api) se puede importar y probar sin pywebview.
"""
import base64
import ctypes
import logging
import math
import os
import shutil
import subprocess
import json
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from visor_rutas import almacen_archivos, config_visor, excel_html
from visor_rutas.remoto import ErrorRemoto, ProveedorRemoto

log = logging.getLogger(__name__)

try:   # local mode: the service code, its .env and databases (not in the remote-only .exe)
    import psycopg

    import pdf_export
    import recalc
    import red_fibra_pg
    from config import get_settings
    from mapa_ruta import DROP_MIN_M, IMAGERY_URL, LABELS_URL
    from visor_rutas import fusion, kmz_capas, masivas, medicion, presupuesto_visor, red, ruta_fusion_plan, subidas
    from visor_rutas.exportar_fusion import exportar_fusion
    from visor_rutas.calculo import RutaFija, VisorError, calcular_con_ruta, calcular_ruta, parsear_coordenadas, usando_rutas
    from visor_rutas.redes.api import ServicioRedes
    LOCAL_DISPONIBLE, MOTIVO_SIN_LOCAL = True, None
except Exception as _exc:          # ImportError in the .exe; RuntimeError when the .env is incomplete
    LOCAL_DISPONIBLE, MOTIVO_SIN_LOCAL = False, f"{type(_exc).__name__}: {_exc}"
    log.info("Local mode not available (%s): remote mode only", MOTIVO_SIN_LOCAL)

TITULO = "Visor de rutas – Fiber Budget"
HTML = Path(__file__).resolve().parent / "web" / "visor.html"
# "Calles": Esri World Street Map. OpenStreetMap was tried first (as in the Tkinter window), but
# WebView2 sends no Referer from file:// pages and OSM answers every tile with an
# "Access blocked" image (HTTP 200, so it looks like a normal tile). Esri has no such restriction.
STREETS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
STREETS_ATTRIBUTION = "Calles © Esri, HERE, Garmin, OpenStreetMap"
INICIO = (12.13, -86.25)          # Managua
ZOOM_INICIAL = 13
SIN_CONFIGURAR = "Falta configurar el servidor de presupuestos (☰ → Configuración)"
MAX_ESTADO_CAPAS = 2_000_000          # bytes of %APPDATA%\VisorRutas\capas.json
TIPOS_IMAGEN = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


def data_url(archivo: Path) -> str:
    """Image file as a data: URL (the page never reads local files itself)."""
    tipo = TIPOS_IMAGEN.get(archivo.suffix.lower(), "application/octet-stream")
    return f"data:{tipo};base64,{base64.b64encode(archivo.read_bytes()).decode('ascii')}"


def archivo_estado_capas() -> Path:
    """%APPDATA%\\VisorRutas\\capas.json: checkboxes, expanded folders and opacities of "Lugares"."""
    return config_visor.carpeta_usuario() / "capas.json"


def archivo_preferencias() -> Path:
    """%APPDATA%\\VisorRutas\\preferencias.json: page preferences (menu collapsed...). pywebview
    runs in private mode, so the page's localStorage does not survive a restart."""
    return config_visor.carpeta_usuario() / "preferencias.json"


def _leer_json(archivo: Path) -> Any:
    import json
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Visor web: %s unreadable (%s)", archivo.name, exc)
        return None


def _guardar_json(archivo: Path, datos: Any) -> dict[str, Any]:
    import json
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    if len(texto) > MAX_ESTADO_CAPAS:
        return {"ok": False, "error": "Datos demasiado grandes"}
    try:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        temporal = archivo.with_suffix(".tmp")
        temporal.write_text(texto, encoding="utf-8")
        temporal.replace(archivo)
    except OSError as exc:
        return {"ok": False, "error": f"No se pudo guardar {archivo.name}: {exc}"}
    return {"ok": True}


def a_json(valor: Any) -> Any:
    """Copy of `valor` that json.dumps (and pywebview) can always serialize."""
    if valor is None or isinstance(valor, (bool, str)):
        return valor
    if isinstance(valor, int):
        return valor if abs(valor) < 2 ** 53 else str(valor)     # JS numbers lose precision above
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, Decimal):
        return a_json(float(valor))
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {str(k): a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [a_json(v) for v in valor]
    return str(valor)


# --------------------------------------------------------------------------- portapapeles

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def copiar_al_portapapeles(texto: str) -> None:
    """Copy text to the Windows clipboard (Win32 API through ctypes, no Tk)."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    datos = (texto or "").encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):                        # another program may hold the clipboard briefly
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("El portapapeles está ocupado por otro programa")
    try:
        user32.EmptyClipboard()
        memoria = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(datos))
        if not memoria:
            raise OSError("No se pudo reservar memoria para el portapapeles")
        puntero = kernel32.GlobalLock(memoria)
        ctypes.memmove(puntero, datos, len(datos))
        kernel32.GlobalUnlock(memoria)
        if not user32.SetClipboardData(_CF_UNICODETEXT, memoria):
            kernel32.GlobalFree(memoria)
            raise OSError("No se pudo escribir en el portapapeles")
    finally:
        user32.CloseClipboard()


def _abrir_en_explorador(archivo: Path | None, carpeta: Path) -> None:
    if archivo is not None:
        subprocess.Popen(["explorer", "/select,", str(archivo)])
    else:
        carpeta.mkdir(parents=True, exist_ok=True)
        os.startfile(carpeta)                                          # type: ignore[attr-defined]


# --------------------------------------------------------------------------- API para JS

class Api:
    """Methods callable from JavaScript as window.pywebview.api.<name>(...).

    (Attributes starting with "_" are not exposed to JavaScript.)

    configuracion_visor: None = local mode (as before; what the tests and the server use);
    a ConfigVisor selects the mode saved in this PC. forzar_remoto: the .exe (no local code).
    """

    def __init__(self, configuracion_visor: config_visor.ConfigVisor | None = None, forzar_remoto: bool = False):
        self._lock = threading.Lock()
        self._visio = None              # Visio PostgreSQL connection reused by the mufa search
        self._visio_probada = False
        self._lock_kmz = threading.Lock()
        self._kmz = None                # KMZ PostGIS connection reused by the network layers
        self._rutas = presupuesto_visor.CacheRutas() if LOCAL_DISPONIBLE else None   # Google routes of this session
        self._lock_presupuesto = threading.Lock()      # one budget (LibreOffice) at a time
        self._lock_fusion = threading.Lock()           # one write to the workbook of fusion routes at a time
        self._lotes = masivas.GestorLotes() if LOCAL_DISPONIBLE else None      # bulk coordinates batches (this process)
        self._redes = None              # ServicioRedes (network design module), created on first use
        self._ventana = None            # pywebview window (save dialogs); set by abrir()
        self._lock_campo = threading.Lock()
        self._campo_parar: threading.Event | None = None      # the field-app notices are being forwarded to the page (campo_escuchar)
        self._campo_quitar: Any = None
        self._forzar_remoto = forzar_remoto or not LOCAL_DISPONIBLE
        self._config = configuracion_visor or config_visor.ConfigVisor(
            modo="remoto" if self._forzar_remoto else "local")
        self._modo = "local"
        self._remoto: ProveedorRemoto | None = None
        self._aplicar(self._config)

    # ----------------------------------------------------------------------- modo local / remoto

    def _aplicar(self, config: config_visor.ConfigVisor) -> None:
        self._config = config
        self._modo = "remoto" if self._forzar_remoto or config.modo == "remoto" else "local"
        self._remoto = (ProveedorRemoto(config.url, config.clave)
                        if self._modo == "remoto" and config.remoto_completo else None)

    def _usar_remoto(self, sesion: Any, carpeta: Path | None = None) -> None:
        """Tests: remote mode through `sesion` (a TestClient of the API)."""
        self._modo = "remoto"
        self._remoto = ProveedorRemoto(self._config.url or "http://testserver", self._config.clave,
                                       sesion=sesion, carpeta=carpeta)

    def _remota(self, metodo: str, *args: Any) -> dict[str, Any]:
        if self._remoto is None:
            return {"ok": False, "error": SIN_CONFIGURAR, "sin_configurar": True}
        return getattr(self._remoto, metodo)(*args)

    def configuracion_visor(self) -> dict[str, Any]:
        """The "Configuración" screen: mode, server URL and whether a key is saved (never the key)."""
        return {"modo": self._modo, "url": self._config.url, "clave_guardada": bool(self._config.clave),
                "local_disponible": not self._forzar_remoto, "archivo": str(config_visor.archivo_config())}

    def probar_conexion(self, url: str, clave: str = "") -> dict[str, Any]:
        """"Probar conexión": GET /visor/info with that URL and key (empty key = the saved one)."""
        proveedor = ProveedorRemoto(config_visor.normalizar_url(url), clave or self._config.clave)
        try:
            info = proveedor.info()
        except ErrorRemoto as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "servidor": proveedor.servidor, "version_api": info.get("version"),
                "fecha_red": info.get("fecha_red"), "persona": info.get("persona")}

    def guardar_configuracion(self, modo: str, url: str = "", clave: str = "") -> dict[str, Any]:
        """Saves %APPDATA%\\VisorRutas\\config.json (key encrypted with DPAPI) and switches mode now."""
        modo = "remoto" if self._forzar_remoto else (modo if modo in config_visor.MODOS else "local")
        nueva = config_visor.ConfigVisor(modo=modo, url=config_visor.normalizar_url(url) or self._config.url,
                                         clave=clave or self._config.clave)
        if modo == "remoto" and not nueva.remoto_completo:
            return {"ok": False, "error": "Escriba la URL del servidor y la clave"}
        try:
            config_visor.guardar(nueva)
        except OSError as exc:
            return {"ok": False, "error": f"No se pudo guardar la configuración: {exc}"}
        self._aplicar(nueva)
        return {"ok": True, **self.configuracion_visor()}

    def estado(self) -> dict[str, Any]:
        """Status bar: mode, server and date of the Visio network."""
        if self._modo == "remoto":
            if self._remoto is None:
                return {"ok": False, "modo": "remoto", "error": SIN_CONFIGURAR, "sin_configurar": True}
            return self._remoto.estado()
        return {"ok": True, "modo": "local", "servidor": None, "fecha_red": self._fecha_red()}

    def _fecha_red(self) -> str | None:
        """Date of the last Visio import: PostgreSQL copy, else red_fibra.db."""
        try:
            with self._lock:
                conexion = self._conexion_visio()
                if conexion is not None:
                    fila = conexion.execute(red_fibra_pg._FECHA_RED_SQL).fetchone()
                    if fila and fila[0]:
                        return fila[0].isoformat(sep=" ", timespec="seconds")
        except psycopg.Error as exc:
            log.warning("Visor web: Visio network date failed (%s)", type(exc).__name__)
        archivo = get_settings().red_fibra_db
        if archivo.is_file():
            import sqlite3
            try:
                con = sqlite3.connect(f"{archivo.resolve().as_uri()}?mode=ro", uri=True)
                try:
                    fila = con.execute("SELECT max(fecha) FROM importaciones").fetchone()
                finally:
                    con.close()
                return str(fila[0]) if fila and fila[0] else None
            except sqlite3.Error:
                return None
        return None

    # ----------------------------------------------------------------------- mapa y red

    def _conexion_kmz(self) -> Any:
        if self._kmz is not None and (getattr(self._kmz, "closed", False) or getattr(self._kmz, "broken", False)):
            self._kmz = None
        if self._kmz is None:
            self._kmz = red.conectar_kmz()          # psycopg.Error when PostGIS is down
        return self._kmz

    def red(self, capa: str, oeste: float, sur: float, este: float, norte: float, zoom: int) -> dict[str, Any]:
        """Network layer (KMZ mufas / reservas / postes / lines, Visio nodes / links) inside the
        visible map rectangle. Only called when the user turns a layer on, and on map moves."""
        if self._modo == "remoto":
            return self._remota("red", capa, oeste, sur, este, norte, zoom)
        config = red.CAPAS.get(str(capa))
        if config is None:
            return {"ok": False, "error": "Capa desconocida"}
        try:
            if config["origen"] == "kmz":
                with self._lock_kmz:
                    conexion = self._conexion_kmz() if int(zoom) >= config["zoom_min"] else None
                    datos = red.consultar(capa, oeste, sur, este, norte, zoom, kmz_con=conexion)
            else:
                with self._lock:
                    datos = red.consultar(capa, oeste, sur, este, norte, zoom, visio_con=self._conexion_visio(),
                                          archivo_sqlite=get_settings().red_fibra_db)
        except (red.CapaNoValida, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "Datos no válidos"}
        except FileNotFoundError:
            return {"ok": False, "error": "No se encontró la base de diagramas (red_fibra)"}
        except (psycopg.Error, ConnectionError) as exc:
            if config["origen"] == "kmz":
                self._kmz = None
            log.warning("Visor web: layer %s failed (%s: %s)", capa, type(exc).__name__, str(exc).strip()[:200])
            base = "del KMZ (PostGIS)" if config["origen"] == "kmz" else "Visio"
            return {"ok": False, "error": f"No se pudo consultar la base {base} para {config['nombre']}"}
        except Exception as exc:
            log.exception("Visor web: layer %s failed", capa)
            return {"ok": False, "error": f"No se pudo cargar {config['nombre']} ({type(exc).__name__})"}
        return {"ok": True, **a_json(datos)}

    # ----------------------------------------------------------------------- panel "Lugares" (KMZ)

    def kmz_arbol(self) -> dict[str, Any]:
        """Folder tree of the KMZ cache (imported first if missing or the KMZ changed) and its
        icons as data URLs. Remote mode: from the server, cached in %APPDATA%\\VisorRutas\\kmz_cache."""
        if self._modo == "remoto":
            return self._remota("kmz_arbol")
        try:
            arbol = kmz_capas.asegurar()
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"{exc}. Revise KMZ_PATH en el .env"}
        except Exception as exc:
            log.exception("Visor web: KMZ import failed")
            return {"ok": False, "error": f"No se pudo leer el KMZ ({type(exc).__name__}: {exc})"}
        iconos = {}
        for nombre in arbol.get("iconos", []):
            try:
                iconos[nombre] = data_url(kmz_capas.archivo_seguro(f"iconos/{nombre}"))
            except FileNotFoundError:
                pass
        return {"ok": True, "arbol": arbol, "iconos": iconos}

    def kmz_progreso(self) -> dict[str, Any]:
        """Progress of an import in course (the page polls it while kmz_arbol runs)."""
        if self._modo == "remoto" or not LOCAL_DISPONIBLE:
            return {"activo": False}
        return kmz_capas.progreso_actual()

    def kmz_capa(self, cid: str) -> dict[str, Any]:
        """GeoJSON of one folder's elements (loaded the first time the folder is turned on)."""
        if self._modo == "remoto":
            return self._remota("kmz_capa", cid)
        try:
            import json
            return {"ok": True, "capa": json.loads(kmz_capas.archivo_capa(str(cid or "")).read_text(encoding="utf-8"))}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("Visor web: KMZ layer %s failed", cid)
            return {"ok": False, "error": f"No se pudo leer la capa ({type(exc).__name__})"}

    def kmz_indice(self) -> dict[str, Any]:
        """{folder id: [[name, description text], ...]} for the search box (loaded on the first search)."""
        if self._modo == "remoto":
            return self._remota("kmz_indice")
        try:
            import json
            return {"ok": True, "indice": json.loads(kmz_capas.archivo_indice().read_text(encoding="utf-8"))}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}

    def kmz_foto(self, nombre: str) -> dict[str, Any]:
        """A photo of the KMZ (files/) as a data URL, for the popup."""
        if self._modo == "remoto":
            return self._remota("kmz_foto", nombre)
        try:
            return {"ok": True, "data_url": data_url(kmz_capas.archivo_seguro(f"fotos/{nombre}"))}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}

    def capas_estado(self) -> dict[str, Any]:
        """Saved state of the "Lugares" panel in this PC (both modes)."""
        return {"ok": True, "estado": _leer_json(archivo_estado_capas())}

    def guardar_capas_estado(self, estado: Any) -> dict[str, Any]:
        return _guardar_json(archivo_estado_capas(), estado if isinstance(estado, dict) else {})

    def preferencias(self) -> dict[str, Any]:
        """Page preferences saved in this PC (both modes): menu collapsed, ..."""
        datos = _leer_json(archivo_preferencias())
        return {"ok": True, "preferencias": datos if isinstance(datos, dict) else {}}

    def guardar_preferencias(self, cambios: Any) -> dict[str, Any]:
        """Merges `cambios` into the saved preferences."""
        if not isinstance(cambios, dict):
            return {"ok": False, "error": "Preferencias no válidas"}
        actuales = _leer_json(archivo_preferencias())
        return _guardar_json(archivo_preferencias(), {**(actuales if isinstance(actuales, dict) else {}), **cambios})

    # ----------------------------------------------------------------------- módulo de redes

    def _servicio_redes(self) -> Any:
        with self._lock:
            if self._redes is None:
                self._redes = ServicioRedes()
            return self._redes

    def redes(self, metodo: str, args: Any = None) -> dict[str, Any]:
        """Network design module (visor_rutas/redes): the same call in both modes. Local: the
        user is this PC's Windows user. Remote: POST /visor/redes/{metodo} with the X-Visor-Key."""
        if self._modo == "remoto":
            return self._remota("redes", metodo, args)
        import getpass
        try:
            return a_json(self._servicio_redes().llamar(str(metodo or ""), args if args is not None else {},
                                                        usuario_windows=getpass.getuser()))
        except Exception as exc:
            log.exception("Visor web: network module call %s failed", metodo)
            return {"ok": False, "error": f"Error inesperado en el módulo de redes ({type(exc).__name__}). Detalle en el log."}

    # ----------------------------------------------------------------------- app de campo: avisos en tiempo real hacia la página

    def campo_escuchar(self) -> dict[str, Any]:
        """Starts sending the changes of the field data to the page (`window.CampoVisor.evento(aviso)`), once. Local mode: PostgreSQL LISTEN here;
        remote mode: the server's Server-Sent Events. The page calls it only for an administrator or an editor."""
        with self._lock_campo:
            if self._campo_parar is not None:
                return {"ok": True, "ya": True}
            if self._modo == "remoto" and self._remoto is None:
                return {"ok": False, "error": "Falta configurar el servidor"}
            parar = threading.Event()
            self._campo_parar = parar
            if self._modo == "remoto":
                threading.Thread(target=self._remoto.escuchar_campo, args=(self._avisar_campo, parar), name="campo-sse", daemon=True).start()
                self._campo_quitar = parar.set
            else:
                from visor_rutas import campo_eventos
                self._campo_quitar = campo_eventos.escucha().suscribir(self._avisar_campo)
        return {"ok": True, "ya": False}

    def campo_detener(self) -> dict[str, Any]:
        with self._lock_campo:
            if self._campo_parar is not None:
                self._campo_parar.set()
                if self._campo_quitar is not None:
                    self._campo_quitar()
            self._campo_parar = self._campo_quitar = None
        return {"ok": True}

    def _avisar_campo(self, aviso: dict[str, Any]) -> None:
        """From the listening thread to the page (the main window; the windows of their own do not need it)."""
        if self._ventana is None:
            return
        try:
            self._ventana.evaluate_js(f"window.CampoVisor && window.CampoVisor.evento({json.dumps(aviso)})")
        except Exception:                                           # noqa: BLE001 - the window is closing
            log.info("Visor web: campo notice could not be delivered")

    def _conexion_visio(self) -> Any:
        """Reused connection (None -> the searches read red_fibra.db); reconnects if it broke."""
        if self._visio is not None and (getattr(self._visio, "closed", False) or getattr(self._visio, "broken", False)):
            self._visio, self._visio_probada = None, False
        if not self._visio_probada:
            self._visio = red_fibra_pg.connect_or_none()
            self._visio_probada = True
        return self._visio

    def buscar_mufa(self, texto: str) -> dict[str, Any]:
        """Mufas / nodes whose name contains the typed words (search box at the top of the map)."""
        if self._modo == "remoto":
            return self._remota("buscar_mufa", texto)
        try:
            with self._lock:
                resultados = fusion.buscar_mufas(str(texto or ""), visio_con=self._conexion_visio(),
                                                 archivo_sqlite=get_settings().red_fibra_db)
        except FileNotFoundError:
            return {"ok": False, "error": "No se encontró la base de diagramas (red_fibra)"}
        except Exception as exc:
            log.exception("Visor web: mufa search failed")
            return {"ok": False, "error": f"No se pudo buscar ({type(exc).__name__})"}
        return {"ok": True, "resultados": a_json(resultados)}

    def mufa(self, nodo_id: int) -> dict[str, Any]:
        """One searched mufa: coordinates, diagrams (with its position in each), hilos, splitters..."""
        if self._modo == "remoto":
            return self._remota("mufa", nodo_id)
        try:
            with self._lock:
                detalle = fusion.detalle_mufa(int(nodo_id), visio_con=self._conexion_visio(),
                                              archivo_sqlite=get_settings().red_fibra_db)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Mufa no válida"}
        except FileNotFoundError:
            return {"ok": False, "error": "No se encontró la base de diagramas (red_fibra)"}
        except Exception as exc:
            log.exception("Visor web: mufa %s failed", nodo_id)
            return {"ok": False, "error": f"No se pudo leer la mufa ({type(exc).__name__})"}
        if detalle is None:
            return {"ok": False, "error": "La mufa ya no está en la base de diagramas"}
        return {"ok": True, "mufa": a_json(detalle)}

    def buscar_en_diagrama(self, md5: str, texto: str) -> dict[str, Any]:
        """Search inside one Visio diagram: text (words) or a coordinate. {"modo", "resultados": [{texto, x_cm, y_cm, ancho_cm, alto_cm, …}], "total"}."""
        if self._modo == "remoto":
            return self._remota("buscar_en_diagrama", md5, texto)
        try:
            with self._lock:
                respuesta = fusion.buscar_en_diagrama(str(md5 or ""), str(texto or ""), visio_con=self._conexion_visio(),
                                                      archivo_sqlite=get_settings().red_fibra_db)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"No se puede buscar en este diagrama ({exc})"}
        except Exception as exc:
            log.exception("Visor web: diagram search failed")
            return {"ok": False, "error": f"No se pudo buscar ({type(exc).__name__})"}
        return {"ok": True, **a_json(respuesta)}

    def configuracion(self) -> dict[str, Any]:
        """Tile URLs and constants shared with the Tkinter window and the Excel map, plus the mode."""
        modo = {"modo": self._modo, "local_disponible": not self._forzar_remoto,
                "sin_configurar": self._modo == "remoto" and self._remoto is None}
        if self._modo == "remoto":
            base = self._remoto.configuracion() if self._remoto is not None else {}
            from visor_rutas.remoto import MAPA_POR_DEFECTO
            return {**MAPA_POR_DEFECTO, **base, **modo}
        return {"imagery_url": IMAGERY_URL, "labels_url": LABELS_URL, "streets_url": STREETS_URL,
                "streets_attribution": STREETS_ATTRIBUTION,
                "drop_min_m": DROP_MIN_M, "inicio": list(INICIO), "zoom_inicial": ZOOM_INICIAL, **modo}

    def calcular(self, texto: str) -> dict[str, Any]:
        """{"ok": true, "datos": {...}, "coordenada": "lat, lon"} or {"ok": false, "error": "..."}.

        "coordenada" (normalized text, for the history) is also returned when the text was a
        valid coordinate but the calculation failed, as the Tkinter window does.
        """
        if self._modo == "remoto":
            return self._remota("calcular", texto)
        try:
            lat, lon = parsear_coordenadas(str(texto or ""))
        except VisorError as exc:
            return {"ok": False, "error": str(exc)}
        coordenada = f"{lat:.6f}, {lon:.6f}"
        try:
            with usando_rutas(self._rutas):      # the approximate budget reuses these Google routes
                datos = a_json(calcular_ruta(lat, lon))
        except VisorError as exc:
            return {"ok": False, "error": str(exc), "coordenada": coordenada}
        except Exception as exc:
            log.exception("Visor web: route calculation failed")
            return {"ok": False, "coordenada": coordenada,
                    "error": f"Error inesperado ({type(exc).__name__}): {exc}. Detalle en logs/visor.log"}
        return {"ok": True, "datos": datos, "coordenada": coordenada}

    def calcular_con_ruta(self, lat: float | None, lon: float | None, puntos: list[list[float]], postes_extra: int = 0) -> dict[str, Any]:
        """The same as `calcular` for a route the user edited or drew on the map (no Google): distance, metraje final, poles, mufas
        and quantities are recalculated from the polyline. (lat, lon): the client (None: the last point). postes_extra: poles added
        by hand."""
        if self._modo == "remoto":
            return self._remota("calcular_con_ruta", lat, lon, puntos, postes_extra)
        try:
            datos = a_json(calcular_con_ruta(lat, lon, puntos, presupuesto_visor.postes_a_mano(postes_extra)))
        except VisorError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("Visor web: edited route calculation failed")
            return {"ok": False, "error": f"Error inesperado ({type(exc).__name__}): {exc}. Detalle en logs/visor.log"}
        return {"ok": True, "datos": datos, "coordenada": f"{datos['cliente']['lat']:.6f}, {datos['cliente']['lon']:.6f}"}

    def diagrama(self, md5: str, pagina: int = 0) -> dict[str, Any]:
        """Real Visio diagram as a data URL (the page must not read local files itself).

        SVG (vector, sharp at any zoom); PNG only if the SVG export fails. The first time a
        diagram is converted with LibreOffice (~5-15 s); then it comes from datos/cache/diagramas.
        """
        if self._modo == "remoto":
            return self._remota("diagrama", md5, pagina)
        try:
            archivo, formato = fusion.diagrama_mejor(md5)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except FileNotFoundError:
            return {"ok": False, "error": "Diagrama no disponible (no está convertido: ni en la base ni en datos/cache/odg)"}
        except Exception as exc:
            log.exception("Visor web: diagram %s failed", md5)
            return {"ok": False, "error": f"Diagrama no disponible ({exc})"}
        if archivo is None:
            return {"ok": False, "error": "Diagrama no disponible (falta LibreOffice)"}
        tipo = "image/svg+xml" if formato == "svg" else "image/png"
        datos = base64.b64encode(archivo.read_bytes()).decode("ascii")
        return {"ok": True, "data_url": f"data:{tipo};base64,{datos}", "formato": formato}

    # ----------------------------------------------------------------------- presupuestos

    def presupuesto_config(self) -> dict[str, Any]:
        """Options and defaults of the "Generar presupuesto" form."""
        if self._modo == "remoto":
            return self._remota("presupuesto_config")
        rules = presupuesto_visor.main.load_rules(get_settings().rules_path)
        return {"ok": True, "servicios": list(presupuesto_visor.SERVICIOS), "medios": list(presupuesto_visor.MEDIOS),
                "estimacion": {**presupuesto_visor.ESTIMACION_POR_DEFECTO, **(rules.get("visor_estimacion") or {})},
                "umbral_m": rules["cable"]["adss_threshold_m"],
                "libreoffice": recalc.find_soffice(get_settings().libreoffice_path) is not None,
                "carpeta": str(presupuesto_visor.carpeta_visor())}

    def _presupuesto(self, accion: Any) -> dict[str, Any]:
        """Runs a budget action with the shared errors (form, no connection point, Google...)."""
        try:
            with self._lock_presupuesto:
                return {"ok": True, **a_json(accion())}
        except presupuesto_visor.ErrorFormulario as exc:
            return {"ok": False, "error": "Revise los datos marcados", "errores": exc.errores}
        except presupuesto_visor.PresupuestoError as exc:
            return {"ok": False, "error": f"No se pudo generar el presupuesto: {exc}"}
        except Exception as exc:
            log.exception("Visor web: budget failed")
            return {"ok": False, "error": f"Error inesperado ({type(exc).__name__}): {exc}. Detalle en logs/visor.log"}

    def generar_presupuesto(self, campos: dict[str, Any]) -> dict[str, Any]:
        """Full budget from the form, with the same generation as POST /presupuesto, in output/visor."""
        if self._modo == "remoto":
            return self._remota("generar_presupuesto", campos)

        def accion() -> dict[str, Any]:
            campos_form = dict(campos or {})
            solicitud = presupuesto_visor.construir_solicitud(campos_form)
            marcados = presupuesto_visor.postes_marcados(campos_form.get(presupuesto_visor.CAMPO_POSTES_MARCADOS))
            ruta = self._ruta_editada(campos_form.get("ruta_editada"))
            respuesta = presupuesto_visor.generar(solicitud, ruta or self._rutas, postes_existentes_m=marcados,
                                                  postes_extra=presupuesto_visor.postes_a_mano(campos_form.get("postes_a_mano")),
                                                  mufas_tocadas=presupuesto_visor.mufas_tocadas(campos_form.get("mufas_tocadas")))
            return {"resultado": presupuesto_visor.resultado_para_visor(respuesta)}
        return self._presupuesto(accion)

    # ---- coordenadas masivas: leer el archivo, calcular un presupuesto por punto en segundo plano, seguirlo y bajar el resultado
    # ---- archivos grandes por partes (un KMZ completo, un Excel grande): primero se suben, después se usa el id
    def subir_iniciar(self, nombre: str, tamano: int) -> dict[str, Any]:
        if self._modo == "remoto":
            return self._remota("subir_iniciar", nombre, tamano)
        try:
            return {"ok": True, "id": subidas.almacen.iniciar(nombre, tamano)}
        except subidas.ErrorSubida as exc:
            return {"ok": False, "error": str(exc)}

    def subir_parte(self, id: str, numero: int, datos: str) -> dict[str, Any]:
        """Part `numero` of the upload `id` (base64)."""
        if self._modo == "remoto":
            return self._remota("subir_parte", id, numero, datos)
        try:
            return {"ok": True, "recibido": subidas.almacen.parte(id, numero, base64.b64decode(str(datos or ""), validate=False))}
        except subidas.ErrorSubida as exc:
            return {"ok": False, "error": str(exc)}

    def subir_fin(self, id: str) -> dict[str, Any]:
        if self._modo == "remoto":
            return self._remota("subir_fin", id)
        try:
            return {"ok": True, **subidas.almacen.terminar(id)}
        except subidas.ErrorSubida as exc:
            return {"ok": False, "error": str(exc)}

    def masivas_leer(self, nombre: str, datos: str = "", subida_id: str | None = None) -> dict[str, Any]:
        """The coordinates of an Excel / CSV / Word / text file (base64, or the id of a finished upload): {"puntos": [...], "formato", "avisos"}."""
        if self._modo == "remoto":
            return self._remota("masivas_leer", nombre, datos, subida_id)
        try:
            if subida_id:
                nombre_subido, crudo = subidas.almacen.tomar(subida_id)
                nombre = nombre or nombre_subido
            else:
                crudo = base64.b64decode(str(datos or ""), validate=False)
            return {"ok": True, **masivas.extraer(str(nombre or ""), crudo)}
        except (ValueError, subidas.ErrorSubida) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("Visor web: bulk file could not be read")
            return {"ok": False, "error": f"No se pudo leer el archivo ({type(exc).__name__})"}

    def masivas_iniciar(self, nombre: str, puntos: list[dict[str, Any]]) -> dict[str, Any]:
        """Starts the batch (one approximate budget per valid point, in the background). Returns its state; ask for it with masivas_estado."""
        if self._modo == "remoto":
            return self._remota("masivas_iniciar", nombre, puntos)
        try:
            reglas = presupuesto_visor.main.load_rules(get_settings().rules_path).get("visor_masivo") or {}
            lote = self._lotes.iniciar(str(nombre or "lote"), masivas.revisar(puntos), presupuesto_visor.carpeta_visor(), int(reglas.get("google_por_minuto", 30)),
                                       int(reglas.get("max_puntos", 200)), self._lock_presupuesto, presupuesto_visor.CacheRutas)
            return {"ok": True, "lote": lote.publico()}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def masivas_estado(self, id: str, desde: int = 0) -> dict[str, Any]:
        """Progress of a batch and the results from the `desde`-th on."""
        if self._modo == "remoto":
            return self._remota("masivas_estado", id, desde)
        try:
            return {"ok": True, "lote": self._lotes.obtener(id).publico(desde)}
        except KeyError as exc:
            return {"ok": False, "error": str(exc.args[0])}

    def masivas_cancelar(self, id: str) -> dict[str, Any]:
        if self._modo == "remoto":
            return self._remota("masivas_cancelar", id)
        try:
            self._lotes.obtener(id).cancelar.set()
            return {"ok": True}
        except KeyError as exc:
            return {"ok": False, "error": str(exc.args[0])}

    def masivas_descargar(self, id: str) -> dict[str, Any]:
        """The Excel of every budget and the summary, as a .zip (base64)."""
        if self._modo == "remoto":
            return self._remota("masivas_descargar", id)
        try:
            nombre, datos = self._lotes.comprimir(id)
            return {"ok": True, "nombre": nombre, "datos": base64.b64encode(datos).decode("ascii")}
        except (KeyError, ValueError) as exc:
            return {"ok": False, "error": str(exc.args[0])}

    def masivas_abrir_carpeta(self, id: str) -> dict[str, Any]:
        """Opens the folder of the batch in Explorer (local mode: the folder is on this PC)."""
        if self._modo == "remoto":
            return {"ok": False, "error": "La carpeta está en el servidor: use «Descargar .zip»"}
        try:
            _abrir_en_explorador(None, self._lotes.obtener(id).carpeta)
            return {"ok": True}
        except (KeyError, OSError) as exc:
            return {"ok": False, "error": f"No se pudo abrir la carpeta: {exc}"}

    # ---- ruta de fusión: texto de cada paso y franja en el libro de rutas de fusión
    def redactar_fusion(self, plan: dict[str, Any]) -> dict[str, Any]:
        """The plan of the fusion route with the text of every step written again (after the user edited it)."""
        if self._modo == "remoto":
            return self._remota("redactar_fusion", plan)
        try:
            return {"ok": True, "plan": ruta_fusion_plan.redactar(plan)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def exportar_fusion(self, plan: dict[str, Any], opciones: dict[str, Any] | None = None) -> dict[str, Any]:
        """Adds the fusion route as a new strip to the workbook of fusion routes (RUTA_FUSION_XLSX; remote mode: the server's)."""
        if self._modo == "remoto":
            return self._remota("exportar_fusion", plan, opciones)
        with self._lock_fusion:
            return exportar_fusion(plan, opciones or {})

    @staticmethod
    def _ruta_editada(puntos: Any) -> Any:
        """RutaFija of a route edited on the map (None when there is none): the budget uses it instead of asking Google."""
        return RutaFija(puntos) if puntos else None

    def estimar_presupuesto(self, lat: float, lon: float, metraje_final_m: float,
                            postes_existentes_m: list[float] | None = None, ruta: list[list[float]] | None = None,
                            postes_extra: int = 0, mufas_tocadas: int | None = None) -> dict[str, Any]:
        """Approximate budget of the main view (coordinate only, defaults from visor_estimacion).
        postes_existentes_m: new poles marked as existing on the map (route metres)."""
        if self._modo == "remoto":
            return self._remota("estimar_presupuesto", lat, lon, metraje_final_m, postes_existentes_m, ruta, postes_extra, mufas_tocadas)

        def accion() -> dict[str, Any]:
            estimacion = presupuesto_visor.estimar(float(lat), float(lon), float(metraje_final_m), self._ruta_editada(ruta) or self._rutas,
                                                   presupuesto_visor.postes_marcados(postes_existentes_m),
                                                   presupuesto_visor.postes_a_mano(postes_extra),
                                                   None if mufas_tocadas is None else max(0, min(int(mufas_tocadas), 100)))
            return {"supuestos": estimacion["supuestos"], "campos": estimacion["campos"],
                    "resultado": presupuesto_visor.resultado_para_visor(estimacion["respuesta"])}
        return self._presupuesto(accion)

    def medir_ruta(self, puntos: list[list[float]], con_total: bool = False) -> dict[str, Any]:
        """Metraje final (business rules) of a line measured on the map; con_total also fills the Excel template and
        recalculates it (LibreOffice) to give the total. No Google involved."""
        if self._modo == "remoto":
            return self._remota("medir_ruta", puntos, con_total)
        if not con_total:
            try:
                return {"ok": True, "medicion": medicion.calcular(puntos)}
            except medicion.MedicionError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                log.exception("Visor web: measurement failed")
                return {"ok": False, "error": f"Error inesperado ({type(exc).__name__}): {exc}. Detalle en logs/visor.log"}
        return self._presupuesto(lambda: medicion.estimar(puntos))

    def historial_presupuestos(self) -> dict[str, Any]:
        """Budgets saved by the viewer (output/visor; remote mode: the server's), newest first."""
        if self._modo == "remoto":
            return self._remota("historial_presupuestos")
        try:
            return {"ok": True, "presupuestos": presupuesto_visor.historial()}
        except OSError as exc:
            return {"ok": False, "error": f"No se pudo leer output/visor: {exc}"}

    def abrir_presupuesto_guardado(self, archivo: str) -> dict[str, Any]:
        """One budget of the history, shown in the result area (sheets, PDF, save as...)."""
        if self._modo == "remoto":
            return self._remota("abrir_presupuesto_guardado", archivo)
        try:
            return {"ok": True, "resultado": a_json(presupuesto_visor.abrir_guardado(archivo))}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("Visor web: saved budget %s failed", archivo)
            return {"ok": False, "error": f"No se pudo abrir el presupuesto ({type(exc).__name__})"}

    def hoja_excel(self, archivo: str, hoja: str, calculado: bool = True) -> dict[str, Any]:
        """One sheet of a visor budget as an HTML table (values, never formulas)."""
        if self._modo == "remoto":
            return self._remota("hoja_excel", archivo, hoja, calculado)
        try:
            if hoja not in presupuesto_visor.HOJAS:
                return {"ok": False, "error": "Hoja no válida"}
            xlsx = presupuesto_visor.archivo_del_visor(archivo, (".xlsx",))
            return {"ok": True, "html": excel_html.hoja_a_html(xlsx, hoja, bool(calculado))}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("Visor web: sheet %s of %s failed", hoja, archivo)
            return {"ok": False, "error": f"No se pudo mostrar la hoja ({type(exc).__name__})"}

    def _pdf(self, xlsx: Path) -> Path:
        soffice = recalc.find_soffice(get_settings().libreoffice_path)
        if soffice is None:
            raise pdf_export.PdfExportError("LibreOffice no disponible")
        pdf_previo = xlsx.with_suffix(".pdf")
        try:                                                   # a PDF already made is kept in the database: no need to convert again
            almacen_archivos.restaurar("visor", pdf_previo.relative_to(presupuesto_visor.carpeta_visor().resolve()).as_posix(), pdf_previo)
        except ValueError:
            pass
        pdf = pdf_export.xlsx_a_pdf(xlsx, soffice)
        presupuesto_visor.subir_a_la_base()
        return pdf

    def pdf_presupuesto(self, archivo: str) -> dict[str, Any]:
        """PDF of a visor budget (same pdf_export as the API) as base64, for the PDF tab."""
        if self._modo == "remoto":
            return self._remota("pdf_presupuesto", archivo)
        try:
            xlsx = presupuesto_visor.archivo_del_visor(archivo, (".xlsx",))
            with self._lock_presupuesto:
                pdf = self._pdf(xlsx)
            return {"ok": True, "base64": base64.b64encode(pdf.read_bytes()).decode("ascii"), "nombre": pdf.name}
        except (FileNotFoundError, pdf_export.PdfExportError) as exc:
            return {"ok": False, "error": f"PDF no disponible: {exc}"}
        except Exception as exc:
            log.exception("Visor web: PDF of %s failed", archivo)
            return {"ok": False, "error": f"PDF no disponible ({type(exc).__name__})"}

    def _archivo_listo(self, archivo: str, tipo: str) -> Path:
        """The file to save / open: the local visor file, or the copy downloaded from the server."""
        if self._modo == "remoto":
            if self._remoto is None:
                raise ErrorRemoto(SIN_CONFIGURAR)
            return self._remoto.descargar(archivo, "pdf" if tipo == "pdf" else "xlsx")
        xlsx = presupuesto_visor.archivo_del_visor(archivo, (".xlsx",))
        if tipo == "pdf":
            with self._lock_presupuesto:
                return self._pdf(xlsx)
        return xlsx

    def guardar_como(self, archivo: str, tipo: str = "xlsx") -> dict[str, Any]:
        """"Guardar Excel / PDF como…": Windows save dialog, then a copy of the visor file."""
        try:
            origen = self._archivo_listo(archivo, tipo)
            if self._ventana is None:
                return {"ok": False, "error": "Diálogo de guardar no disponible"}
            import webview
            filtro = ("PDF (*.pdf)",) if tipo == "pdf" else ("Excel (*.xlsx)",)
            elegido = self._ventana.create_file_dialog(webview.FileDialog.SAVE, directory=str(Path.home() / "Documents"),
                                                       save_filename=origen.name, file_types=filtro)
            if not elegido:
                return {"ok": False, "cancelado": True}
            destino = Path(elegido if isinstance(elegido, str) else elegido[0])
            if destino.suffix.lower() != origen.suffix.lower():
                destino = destino.with_suffix(origen.suffix)
            shutil.copy2(origen, destino)
            return {"ok": True, "ruta": str(destino)}
        except (FileNotFoundError, ErrorRemoto) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            if LOCAL_DISPONIBLE and isinstance(exc, pdf_export.PdfExportError):
                return {"ok": False, "error": str(exc)}
            log.exception("Visor web: save-as failed")
            return {"ok": False, "error": f"No se pudo guardar ({type(exc).__name__}: {exc})"}

    def guardar_imagen(self, nombre: str, datos: str, tipo: str = "png") -> dict[str, Any]:
        """Logical diagram export (phase 6): the page sends a PNG (data URL); this saves it as PNG or,
        with Pillow, as a one-page PDF, wherever the user picks in the Windows save dialog. Same in
        local and remote mode (the drawing is made in the page)."""
        try:
            crudo = base64.b64decode(str(datos or "").split(",", 1)[-1], validate=False)
            if not crudo.startswith(b"\x89PNG"):
                return {"ok": False, "error": "La imagen del diagrama no es válida"}
            if self._ventana is None:
                return {"ok": False, "error": "Diálogo de guardar no disponible"}
            import webview
            pdf = tipo == "pdf"
            limpio = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in str(nombre or "")).strip()[:100] or "Diagrama logico"
            sufijo = ".pdf" if pdf else ".png"
            elegido = self._ventana.create_file_dialog(webview.FileDialog.SAVE, directory=str(Path.home() / "Documents"),
                                                       save_filename=limpio + sufijo,
                                                       file_types=("PDF (*.pdf)",) if pdf else ("Imagen PNG (*.png)",))
            if not elegido:
                return {"ok": False, "cancelado": True}
            destino = Path(elegido if isinstance(elegido, str) else elegido[0])
            if destino.suffix.lower() != sufijo:
                destino = destino.with_suffix(sufijo)
            if pdf:
                import io

                from PIL import Image
                with Image.open(io.BytesIO(crudo)) as imagen:
                    hoja = Image.new("RGB", imagen.size, "white")
                    hoja.paste(imagen, mask=imagen.convert("RGBA").split()[-1])
                    hoja.save(destino, "PDF", resolution=150, title=limpio)
            else:
                destino.write_bytes(crudo)
            return {"ok": True, "ruta": str(destino)}
        except Exception as exc:
            log.exception("Visor web: diagram export failed")
            return {"ok": False, "error": f"No se pudo guardar ({type(exc).__name__}: {exc})"}

    TIPOS_ARCHIVO = {"kmz": "Google Earth (*.kmz)", "geojson": "GeoJSON (*.geojson)", "json": "Respaldo JSON (*.json)",
                     "sql": "Respaldo SQL (*.sql)", "xlsx": "Excel (*.xlsx)", "zip": "Carpeta comprimida (*.zip)"}

    def guardar_archivo(self, nombre: str, datos: str, tipo: str) -> dict[str, Any]:
        """Phase 7: a file the network module produced on the server (base64: KMZ / GeoJSON export,
        backup .json / .sql) saved wherever the user picks in the Windows save dialog."""
        try:
            if tipo not in self.TIPOS_ARCHIVO:
                return {"ok": False, "error": "Tipo de archivo no permitido"}
            crudo = base64.b64decode(str(datos or ""), validate=False)
            if not crudo:
                return {"ok": False, "error": "El archivo está vacío"}
            if self._ventana is None:
                return {"ok": False, "error": "Diálogo de guardar no disponible"}
            import webview
            sufijo = f".{tipo}"
            limpio = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in str(nombre or "")).strip()[:120] or "archivo"
            if limpio.lower().endswith(sufijo):
                limpio = limpio[: -len(sufijo)]
            elegido = self._ventana.create_file_dialog(webview.FileDialog.SAVE, directory=str(Path.home() / "Documents"),
                                                       save_filename=limpio + sufijo, file_types=(self.TIPOS_ARCHIVO[tipo],))
            if not elegido:
                return {"ok": False, "cancelado": True}
            destino = Path(elegido if isinstance(elegido, str) else elegido[0])
            if destino.suffix.lower() != sufijo:
                destino = destino.with_suffix(sufijo)
            destino.write_bytes(crudo)
            return {"ok": True, "ruta": str(destino)}
        except Exception as exc:
            log.exception("Visor web: save of a network module file failed")
            return {"ok": False, "error": f"No se pudo guardar ({type(exc).__name__}: {exc})"}

    def abrir_excel(self, archivo: str) -> dict[str, Any]:
        """Opens the budget in Excel (remote mode: the copy downloaded to %TEMP%\\VisorRutas)."""
        try:
            os.startfile(self._archivo_listo(archivo, "xlsx"))                 # type: ignore[attr-defined]
            return {"ok": True}
        except (FileNotFoundError, OSError, ErrorRemoto) as exc:
            return {"ok": False, "error": f"No se pudo abrir: {exc}"}

    def abrir_carpeta(self, archivo: str = "") -> dict[str, Any]:
        try:
            if self._modo == "remoto":
                carpeta = (self._remoto.carpeta if self._remoto else Path(os.getenv("TEMP", "."))) / "descargas"
                _abrir_en_explorador(self._archivo_listo(archivo, "xlsx") if archivo else None, carpeta)
            else:
                _abrir_en_explorador(presupuesto_visor.archivo_del_visor(archivo) if archivo else None,
                                     presupuesto_visor.carpeta_visor())
            return {"ok": True}
        except (FileNotFoundError, OSError, ErrorRemoto) as exc:
            return {"ok": False, "error": f"No se pudo abrir la carpeta: {exc}"}

    # ----------------------------------------------------------------------- ventanas aparte
    # The Visio diagram and the editor of a mufa can live in their own window of Windows (moved to another screen, side by side with the
    # other one) to fill the mufa by hand from the diagram. They are the same page with `?ventana=<tipo>`: it shows only that window.

    VENTANAS_APARTE = {"diagrama": "Diagrama Visio", "mufa": "Mufa"}

    def abrir_ventana(self, tipo: str, parametros: dict[str, Any] | None = None) -> dict[str, Any]:
        """Opens `tipo` ('diagrama' | 'mufa') in its own window. `parametros`: nombre, id (mufa), indice (diagram file). One per mufa and kind:
        if it is already open it is brought forward."""
        if tipo not in self.VENTANAS_APARTE:
            return {"ok": False, "error": "Ventana desconocida"}
        p = parametros or {}
        nombre = str(p.get("nombre") or "").strip()[:200]
        if not nombre:
            return {"ok": False, "error": "Falta el nombre de la mufa"}
        titulo = f"{self.VENTANAS_APARTE[tipo]} · {nombre} – Fiber Budget"
        consulta = {"ventana": tipo, "nombre": nombre, "t": titulo}
        if tipo == "mufa":
            try:
                consulta["id"] = str(int(p.get("id")))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Mufa no válida"}
        else:
            indice = str(p.get("indice") or "0")
            consulta["indice"] = indice if indice.isdigit() else "0"
        try:
            import webview
            abierta = next((w for w in webview.windows if getattr(w, "title", None) == titulo), None)
            if abierta is not None:
                try:
                    abierta.restore()
                    abierta.show()
                except Exception:                                  # noqa: BLE001 - bringing it forward is a courtesy
                    pass
                return {"ok": True, "ya_abierta": True}
            # The parameters go after «#»: with «?» WebView2 takes it as part of the file name of a file:// URL (ERR_FILE_NOT_FOUND).
            webview.create_window(titulo, url=HTML.as_uri() + "#" + urlencode(consulta), js_api=self, width=1100, height=820,
                                  min_size=(640, 420), text_select=True)
        except Exception as exc:                                    # noqa: BLE001
            log.warning("Visor web: window %s could not be opened (%s)", tipo, exc)
            return {"ok": False, "error": f"No se pudo abrir la ventana: {exc}"}
        return {"ok": True, "ya_abierta": False}

    def cerrar_ventana(self, titulo: str) -> dict[str, Any]:
        """Closes the window with that title (a window of `abrir_ventana`; never the main one)."""
        try:
            import webview
            ventana = next((w for w in webview.windows if getattr(w, "title", None) == str(titulo) and w is not self._ventana), None)
            if ventana is not None:
                ventana.destroy()
        except Exception as exc:                                    # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def copiar(self, texto: str) -> dict[str, Any]:
        try:
            copiar_al_portapapeles(str(texto))
        except Exception as exc:
            log.warning("Visor web: clipboard failed (%s)", exc)
            return {"ok": False, "error": f"No se pudo copiar: {exc}"}
        return {"ok": True}


def abrir(forzar_remoto: bool = False) -> None:
    """Open the maximized pywebview window; returns when it is closed.

    Raises if pywebview or WebView2 is not available (the caller falls back to Tkinter, or the
    .exe shows a message). gui="edgechromium" on purpose: without it pywebview silently falls
    back to the old Internet Explorer engine, where Leaflet does not work.
    """
    import webview

    if not HTML.is_file():
        raise FileNotFoundError(f"No se encontró {HTML}")
    api = Api(config_visor.leer(), forzar_remoto=forzar_remoto)
    log.info("Visor mode: %s%s", api._modo, f" ({api._remoto.servidor})" if api._remoto else "")
    ventana = webview.create_window(TITULO, url=HTML.as_uri(), js_api=api, maximized=True,
                                    min_size=(900, 600), text_select=True)
    assert ventana is not None
    api._ventana = ventana               # save dialogs ("Guardar Excel / PDF como…")
    if LOCAL_DISPONIBLE:
        # Visor budgets older than OUTPUT_RETENTION_DAYS (output/visor only; never the API's files).
        threading.Thread(target=presupuesto_visor.limpiar_archivos_viejos, daemon=True).start()
    ventana.events.shown += lambda: ventana.maximize()   # maximized=True is not always honoured

    def cerrar_aparte() -> None:         # the windows of abrir_ventana go with the main one (webview.start returns when all are closed)
        for otra in list(webview.windows):
            if otra is not ventana:
                try:
                    otra.destroy()
                except Exception:        # noqa: BLE001
                    pass
    ventana.events.closed += cerrar_aparte
    webview.start(gui="edgechromium", http_server=False, debug=False)
