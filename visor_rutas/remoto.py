"""Visor en modo remoto: los cálculos los hace la API de la PC del servidor por el túnel de ngrok.

ProveedorRemoto tiene los mismos métodos (y devuelve los mismos dict) que la Api local de
ventana_web.py, pero llamando a /visor/* de la API (visor_api.py) con requests. En la PC del
usuario no hay bases de datos, Google ni LibreOffice: solo esta clase, excel_html.py (para dibujar
las hojas de un Excel descargado) y la ventana.

Solo depende de requests, openpyxl (vía excel_html) y la biblioteca estándar: entra en el .exe.
"""
import base64
import hashlib
import logging
import json
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter

from visor_rutas import excel_html

log = logging.getLogger(__name__)

AGENTE = "VisorRutas/1.0"
TIMEOUT_CONSULTA_S = 20           # route, layers, search
TIMEOUT_PRESUPUESTO_S = 180       # budgets: Google, map tiles and LibreOffice on the server
SIN_CONEXION = ("No se pudo conectar con el servidor de presupuestos. Verifique que el servicio "
                "esté encendido en la PC del servidor y que la URL sea correcta.")
# The methods of the network module that only read (what the viewer asks when it opens): repeating them after a dropped connection changes nothing.
# When it opens the viewer asks for dozens of things at once (every folder of the KMZ, Mis lugares, the field data...). Each one used to open its own connection (the pool kept 10 and
# threw the rest away), and the tunnel of ngrok cuts the bursts of new connections (SSLError): only MAX_SIMULTANEAS go at a time and the connections are kept and reused.
MAX_SIMULTANEAS = 5
CONEXIONES_GUARDADAS = 8
LECTURAS_REDES = frozenset({"estado", "lugares", "lugar", "cambios_kmz", "estilos_kmz", "capa_importados_kmz", "buscar_elementos", "mufa_existente", "proyectos", "proyecto",
                            "usuarios", "mufa", "red_proyecto", "diagramas", "problemas", "pendientes", "campo_puntos", "campo_ubicaciones", "campo_jornadas", "lienzo_zonas", "lienzo"})
PREFIJO_ARCHIVO = "remoto:"       # resultado["archivo"] in remote mode: "remoto:<id>"
RE_ID = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,200}$")
# Base map used until /visor/info answers (same values as mapa_ruta.py on the server).
MAPA_POR_DEFECTO = {
    "imagery_url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "labels_url": "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}",
    "streets_url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    "streets_attribution": "Calles © Esri, HERE, Garmin, OpenStreetMap",
    "drop_min_m": 1.0, "inicio": [12.13, -86.25], "zoom_inicial": 13,
}


class ErrorRemoto(Exception):
    """Mensaje claro para la barra del visor (servidor apagado, clave, límite...)."""


class ProveedorRemoto:
    """Cliente de /visor/* de la API. sesion: requests.Session (o el TestClient de las pruebas)."""

    def __init__(self, url: str, clave: str, sesion: Any = None, carpeta: Path | None = None,
                 carpeta_kmz: Path | None = None):
        self.url = (url or "").strip().rstrip("/")
        self._clave = clave or ""
        if sesion is None:
            sesion = requests.Session()
            adaptador = HTTPAdapter(pool_connections=2, pool_maxsize=CONEXIONES_GUARDADAS)       # connections kept open and reused, not a new one for every call
            sesion.mount("https://", adaptador)
            sesion.mount("http://", adaptador)
        self._sesion = sesion
        self._cupos = threading.BoundedSemaphore(MAX_SIMULTANEAS)
        self.carpeta = carpeta or Path(tempfile.gettempdir()) / "VisorRutas"
        # Network KMZ ("Lugares" panel): %APPDATA%\VisorRutas\kmz_cache\<md5 of the server's KMZ>
        if carpeta_kmz is None:
            from visor_rutas.config_visor import carpeta_usuario
            carpeta_kmz = (carpeta / "kmz_cache") if carpeta is not None else carpeta_usuario() / "kmz_cache"
        self.carpeta_kmz = carpeta_kmz
        self._kmz_md5: str | None = None
        self._info: dict[str, Any] | None = None

    @property
    def servidor(self) -> str:
        return urlparse(self.url).netloc or self.url

    # ----------------------------------------------------------------------- HTTP

    def _pedir(self, metodo: str, ruta: str, *, timeout: float = TIMEOUT_CONSULTA_S, intentos: int | None = None, **kwargs: Any) -> Any:
        """Response 2xx, or ErrorRemoto with a message for the user. The connection through the tunnel sometimes drops: a GET is tried up to 3 times, a POST twice (a write
        is not repeated more than that), and a call that only reads can ask for 3 (`intentos`). A GET that timed out is repeated; a POST that timed out is not."""
        if not self.url:
            raise ErrorRemoto("Falta configurar el servidor (☰ → Configuración)")
        intentos = intentos or (3 if metodo == "GET" else 2)
        headers = {"X-Visor-Key": self._clave, "ngrok-skip-browser-warning": "1", "User-Agent": AGENTE}
        for intento in range(1, intentos + 1):
            ultimo = intento == intentos
            try:
                with self._cupos:                                        # a few at a time: the rest wait their turn
                    respuesta = self._sesion.request(metodo, f"{self.url}{ruta}", headers=headers,
                                                     timeout=timeout, **kwargs)
            except requests.Timeout:
                if metodo == "GET" and not ultimo:
                    continue
                raise ErrorRemoto("El servidor de presupuestos tardó demasiado en responder") from None
            except requests.RequestException as exc:
                if not ultimo:
                    time.sleep(intento)
                    continue
                log.warning("Remote viewer: %s %s failed (%s: %s)", metodo, ruta, type(exc).__name__, str(exc)[:160])
                raise ErrorRemoto(SIN_CONEXION) from None
            if respuesta.status_code in (502, 503, 504) and not ultimo:
                time.sleep(intento)
                continue
            return self._revisar(respuesta)
        raise ErrorRemoto(SIN_CONEXION)

    @staticmethod
    def _detalle(respuesta: Any) -> str:
        try:
            datos = respuesta.json()
            return str(datos.get("detail") or datos.get("error") or "")
        except ValueError:
            return ""

    def _revisar(self, respuesta: Any) -> Any:
        codigo = respuesta.status_code
        if codigo < 400:
            return respuesta
        detalle = self._detalle(respuesta)
        if respuesta.headers.get("ngrok-error-code") or (codigo in (404, 502, 503, 504) and not detalle):
            raise ErrorRemoto(SIN_CONEXION)          # tunnel up but the API is off, or the URL is wrong
        if codigo == 401:
            raise ErrorRemoto("La clave del visor no es válida. Revise ☰ → Configuración.")
        if codigo == 404 and detalle.lower() == "not found":
            raise ErrorRemoto("El servidor no tiene habilitado el visor remoto (VISOR_API_KEYS vacío)")
        if codigo == 429:
            raise ErrorRemoto(detalle or "Límite de consultas por hora alcanzado")
        raise ErrorRemoto(f"Error del servidor ({codigo}){': ' + detalle if detalle else ''}")

    def _json(self, metodo: str, ruta: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return self._pedir(metodo, ruta, **kwargs).json()
        except ValueError:
            raise ErrorRemoto("Respuesta no válida del servidor") from None

    def _seguro(self, accion: Any) -> dict[str, Any]:
        """Same result shape as the local Api: {"ok": false, "error": "..."} on failure."""
        try:
            return accion()
        except ErrorRemoto as exc:
            return {"ok": False, "error": str(exc)}

    # ----------------------------------------------------------------------- información

    def info(self, forzar: bool = False) -> dict[str, Any]:
        """GET /visor/info (raises ErrorRemoto): API version, Visio network date, base map, form."""
        if self._info is None or forzar:
            self._info = self._json("GET", "/visor/info")
        return self._info

    def configuracion(self) -> dict[str, Any]:
        """Base map and constants for the page; the defaults while the server does not answer."""
        datos = dict(MAPA_POR_DEFECTO)
        try:
            datos.update(self.info().get("configuracion") or {})
        except ErrorRemoto as exc:
            log.warning("Remote viewer: /visor/info failed at start (%s)", exc)
        return datos

    def estado(self) -> dict[str, Any]:
        try:
            info = self.info(forzar=True)
            return {"ok": True, "modo": "remoto", "servidor": self.servidor, "fecha_red": info.get("fecha_red"),
                    "version_api": info.get("version")}
        except ErrorRemoto as exc:
            return {"ok": False, "modo": "remoto", "servidor": self.servidor, "error": str(exc)}

    # ----------------------------------------------------------------------- mapa

    def calcular(self, texto: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/ruta", json={"texto": str(texto or "")},
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def calcular_con_ruta(self, lat: float | None, lon: float | None, puntos: list[list[float]], postes_extra: int = 0) -> dict[str, Any]:
        cuerpo = {"lat": lat, "lon": lon, "puntos": puntos, "postes_extra": int(postes_extra or 0)}
        return self._seguro(lambda: self._json("POST", "/visor/ruta_editada", json=cuerpo, timeout=TIMEOUT_PRESUPUESTO_S))

    def subir_iniciar(self, nombre: str, tamano: int) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/subidas", json={"nombre": str(nombre or ""), "tamano": int(tamano)}))

    def subir_parte(self, id: str, numero: int, datos: str) -> dict[str, Any]:
        crudo = base64.b64decode(str(datos or ""), validate=False)
        return self._seguro(lambda: self._json("POST", f"/visor/subidas/{quote(str(id), safe='')}/{int(numero)}", data=crudo,
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def subir_fin(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/subidas/{quote(str(id), safe='')}/fin"))

    def masivas_leer(self, nombre: str, datos: str = "", subida_id: str | None = None) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/masivas/leer", json={"nombre": str(nombre or ""), "datos": datos or "", "subida_id": subida_id},
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def masivas_iniciar(self, nombre: str, puntos: list[dict[str, Any]], comentario: str = "") -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/masivas/iniciar", json={"nombre": str(nombre or ""), "puntos": puntos, "comentario": str(comentario or "")}))

    def masivas_pdf(self, id: str, cuales: str = "ambos") -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/masivas/{quote(str(id), safe='')}/pdf", params={"cuales": str(cuales or "ambos")}))

    def masivas_estado(self, id: str, desde: int = 0) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", f"/visor/masivas/{quote(str(id), safe='')}", params={"desde": int(desde or 0)}))

    def masivas_cancelar(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/masivas/{quote(str(id), safe='')}/cancelar"))

    def masivas_descargar(self, id: str, tipo: str = "xlsx") -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/masivas/{quote(str(id), safe='')}/descargar", params={"tipo": "pdf" if tipo == "pdf" else "xlsx"},
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def redactar_fusion(self, plan: dict[str, Any]) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/fusion/redactar", json={"plan": plan}))

    def exportar_fusion(self, plan: dict[str, Any], opciones: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/fusion/exportar", json={"plan": plan, "opciones": opciones or {}},
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def red(self, capa: str, oeste: float, sur: float, este: float, norte: float, zoom: int) -> dict[str, Any]:
        params = {"oeste": oeste, "sur": sur, "este": este, "norte": norte, "zoom": zoom}
        return self._seguro(lambda: self._json("GET", f"/visor/red/{quote(str(capa), safe='')}", params=params))

    def buscar_mufa(self, texto: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/mufas", params={"texto": str(texto or "")}))

    def buscar_mufa_cerca(self, lat: float, lon: float, radio_m: float = 300) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/mufas_cerca", params={"lat": lat, "lon": lon, "radio_m": radio_m}))

    def mufa(self, nodo_id: Any) -> dict[str, Any]:
        try:
            nodo = int(nodo_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Mufa no válida"}
        return self._seguro(lambda: self._json("GET", f"/visor/mufa/{nodo}"))

    def buscar_texto_diagramas(self, texto: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/diagramas/buscar", params={"texto": str(texto or "")}))

    def buscar_en_diagrama(self, md5: str, texto: str) -> dict[str, Any]:
        md5 = str(md5 or "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", md5):
            return {"ok": False, "error": "Identificador de diagrama no válido"}
        return self._seguro(lambda: self._json("GET", f"/visor/diagrama/{md5}/buscar", params={"texto": str(texto or "")}))

    def diagrama(self, md5: str, pagina: int = 0) -> dict[str, Any]:
        md5 = str(md5 or "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", md5):
            return {"ok": False, "error": "Identificador de diagrama no válido"}

        def accion() -> dict[str, Any]:
            respuesta = self._pedir("GET", f"/visor/diagrama/{md5}/{int(pagina)}", timeout=TIMEOUT_PRESUPUESTO_S)
            tipo = (respuesta.headers.get("content-type") or "image/svg+xml").split(";")[0]
            datos = base64.b64encode(respuesta.content).decode("ascii")
            return {"ok": True, "data_url": f"data:{tipo};base64,{datos}", "formato": "svg" if "svg" in tipo else "png"}
        return self._seguro(accion)

    # ----------------------------------------------------------------------- panel "Lugares" (KMZ)

    def _cache_kmz(self) -> Path:
        if not self._kmz_md5:
            raise ErrorRemoto("Primero se debe cargar el árbol de la red KMZ")
        return self.carpeta_kmz / self._kmz_md5

    def _archivo_kmz(self, relativa: str) -> Path:
        """iconos/<name> or fotos/<name>: from the local cache, else downloaded once."""
        if not re.fullmatch(r"(iconos|fotos)/[\w .()-]{1,160}\.(png|svg|jpe?g|gif|webp|bmp)", relativa, re.I):
            raise ErrorRemoto("Archivo no válido")
        destino = self._cache_kmz() / relativa
        if not (destino.is_file() and destino.stat().st_size > 0):
            respuesta = self._pedir("GET", f"/visor/kmz/archivo/{quote(relativa)}", timeout=TIMEOUT_PRESUPUESTO_S)
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_suffix(destino.suffix + ".tmp")
            temporal.write_bytes(respuesta.content)
            temporal.replace(destino)
        return destino

    def kmz_arbol(self) -> dict[str, Any]:
        """Tree of the server's KMZ; capas, icons and photos are cached per md5 (a new KMZ on the
        server means a new md5: the old cache is removed)."""
        import json
        import shutil

        def accion() -> dict[str, Any]:
            arbol = self._json("GET", "/visor/kmz/arbol", timeout=TIMEOUT_PRESUPUESTO_S)
            md5 = str(arbol.get("md5") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", md5):
                raise ErrorRemoto("Respuesta no válida del servidor (árbol KMZ)")
            self._kmz_md5 = md5
            cache = self._cache_kmz()
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "arbol.json").write_text(json.dumps(arbol, ensure_ascii=False), encoding="utf-8")
            for vieja in self.carpeta_kmz.iterdir():
                if vieja.is_dir() and vieja.name != md5:
                    shutil.rmtree(vieja, ignore_errors=True)
            iconos = {}
            for nombre in arbol.get("iconos", []):
                try:
                    archivo = self._archivo_kmz(f"iconos/{nombre}")
                except ErrorRemoto as exc:
                    log.warning("Remote viewer: KMZ icon %s failed (%s)", nombre, exc)
                    continue
                tipo = "image/svg+xml" if archivo.suffix.lower() == ".svg" else "image/png"
                iconos[nombre] = f"data:{tipo};base64,{base64.b64encode(archivo.read_bytes()).decode('ascii')}"
            return {"ok": True, "arbol": arbol, "iconos": iconos}
        return self._seguro(accion)

    def kmz_capa(self, cid: str) -> dict[str, Any]:
        import json
        cid = str(cid or "")
        if not re.fullmatch(r"[0-9a-f]{12}", cid):
            return {"ok": False, "error": "Capa no válida"}

        def accion() -> dict[str, Any]:
            archivo = self._cache_kmz() / "capas" / f"{cid}.geojson"
            if archivo.is_file():
                try:
                    return {"ok": True, "capa": json.loads(archivo.read_text(encoding="utf-8"))}
                except ValueError:
                    pass                                      # damaged copy: download again
            respuesta = self._pedir("GET", f"/visor/kmz/capa/{cid}", timeout=TIMEOUT_PRESUPUESTO_S)
            archivo.parent.mkdir(parents=True, exist_ok=True)
            archivo.write_bytes(respuesta.content)
            return {"ok": True, "capa": json.loads(respuesta.content.decode("utf-8"))}
        return self._seguro(accion)

    def kmz_indice(self) -> dict[str, Any]:
        import json

        def accion() -> dict[str, Any]:
            archivo = self._cache_kmz() / "indice.json"
            if not archivo.is_file():
                respuesta = self._pedir("GET", "/visor/kmz/indice", timeout=TIMEOUT_PRESUPUESTO_S)
                archivo.parent.mkdir(parents=True, exist_ok=True)
                archivo.write_bytes(respuesta.content)
            return {"ok": True, "indice": json.loads(archivo.read_text(encoding="utf-8"))}
        return self._seguro(accion)

    def kmz_foto(self, nombre: str) -> dict[str, Any]:
        def accion() -> dict[str, Any]:
            archivo = self._archivo_kmz(f"fotos/{nombre}")
            tipo = {".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(archivo.suffix.lower(), "image/jpeg")
            return {"ok": True, "data_url": f"data:{tipo};base64,{base64.b64encode(archivo.read_bytes()).decode('ascii')}"}
        return self._seguro(accion)

    # ----------------------------------------------------------------------- módulo de redes

    def redes(self, metodo: str, args: Any = None) -> dict[str, Any]:
        """POST /visor/redes/{metodo}: the server identifies the user by the X-Visor-Key."""
        metodo = str(metodo or "")
        if not re.fullmatch(r"[a-z_]{1,40}", metodo):
            return {"ok": False, "error": f"Operación desconocida: {metodo}"}
        return self._seguro(lambda: self._json("POST", f"/visor/redes/{metodo}",
                                               json={"args": args if isinstance(args, dict) else {}},
                                               timeout=TIMEOUT_PRESUPUESTO_S, intentos=3 if metodo in LECTURAS_REDES else None))

    # ----------------------------------------------------------------------- app de campo en tiempo real

    def escuchar_campo(self, alerta: Any, detener: threading.Event, espera_min: float = 1.0, espera_max: float = 30.0) -> None:
        """Blocks until `detener` is set: GET /visor/campo/eventos (Server-Sent Events) and `alerta(dict)` for every event of the field data
        ({tabla, id, cambio, usuario_id}). After every (re)connection `alerta({"tabla": "_conectado"})` so the page asks for what it missed. A cut
        connection is retried with a growing wait; a key that is refused (401), a missing role (403) or no field app (404) ends it with
        `alerta({"tabla": "_error", "error": ...})`."""
        if not self.url:
            alerta({"tabla": "_error", "error": "Falta configurar el servidor"})
            return
        espera = espera_min
        headers = {"X-Visor-Key": self._clave, "ngrok-skip-browser-warning": "1", "User-Agent": AGENTE, "Accept": "text/event-stream"}
        while not detener.is_set():
            try:
                with self._sesion.get(f"{self.url}/visor/campo/eventos", headers=headers, stream=True, timeout=(10, 45)) as r:
                    if r.status_code in (401, 403, 404):
                        alerta({"tabla": "_error", "error": {401: "La clave del visor no es válida",
                                                             403: "Solo un administrador o un editor recibe los avisos de campo"}.get(r.status_code, "El servidor no tiene la app de campo")})
                        return
                    if r.status_code == 200:
                        espera = espera_min
                        alerta({"tabla": "_conectado"})
                        for linea in r.iter_lines(decode_unicode=True):
                            if detener.is_set():
                                return
                            if linea and linea.startswith("data: "):
                                try:
                                    alerta(json.loads(linea[6:]))
                                except ValueError:
                                    log.warning("Remote viewer: campo event that is not JSON ignored")
            except requests.RequestException as exc:
                log.info("Remote viewer: campo events cut (%s); retrying in %.0f s", type(exc).__name__, espera)
            if detener.wait(espera):
                return
            espera = min(espera_max, espera * 2)

    # ----------------------------------------------------------------------- presupuestos

    def presupuesto_config(self) -> dict[str, Any]:
        def accion() -> dict[str, Any]:
            return {"ok": True, **(self.info().get("presupuesto") or {}), "carpeta": str(self.carpeta)}
        return self._seguro(accion)

    def generar_presupuesto(self, campos: dict[str, Any]) -> dict[str, Any]:
        r = self._seguro(lambda: self._json("POST", "/visor/presupuesto", json={"campos": dict(campos or {})},
                                            timeout=TIMEOUT_PRESUPUESTO_S))
        rehecho = str((campos or {}).get("reemplazar_presupuesto") or "")
        if r.get("ok") and rehecho and RE_ID.match(rehecho) and rehecho not in (".", ".."):          # made again over the same file: the copies downloaded here are of the old one
            for sufijo in (".xlsx", ".pdf", ".xlsx.sync"):
                (self.carpeta / "descargas" / f"{rehecho}{sufijo}").unlink(missing_ok=True)
        return r

    def estimar_presupuesto(self, lat: float, lon: float, metraje_final_m: float | None = None,
                            postes_existentes_m: list[float] | None = None, ruta: list[list[float]] | None = None,
                            postes_extra: int = 0, mufas_tocadas: int | None = None) -> dict[str, Any]:
        cuerpo = {"lat": float(lat), "lon": float(lon), "metraje_final_m": metraje_final_m}
        if ruta:
            cuerpo["ruta"] = ruta
        if postes_extra:
            cuerpo["postes_extra"] = int(postes_extra)
        if mufas_tocadas is not None:
            cuerpo["mufas_tocadas"] = int(mufas_tocadas)
        if postes_existentes_m:
            cuerpo["postes_existentes_m"] = list(postes_existentes_m)
        return self._seguro(lambda: self._json("POST", "/visor/estimacion", json=cuerpo,
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    def medir_ruta(self, puntos: list[list[float]], con_total: bool = False) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/medicion", json={"puntos": puntos, "con_total": bool(con_total)},
                                               timeout=TIMEOUT_PRESUPUESTO_S if con_total else TIMEOUT_CONSULTA_S))

    def tickets_pendientes(self) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/tickets", timeout=TIMEOUT_PRESUPUESTO_S))

    def tickets_carpeta(self, carpeta: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", f"/visor/tickets/carpeta/{quote(str(carpeta), safe='')}", timeout=TIMEOUT_PRESUPUESTO_S))

    def ticket_historial(self, kayako_id: int) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", f"/visor/tickets/{int(kayako_id)}/historial", timeout=TIMEOUT_PRESUPUESTO_S))

    def pdf_carpetas(self) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/pdf/carpetas"))

    def pdf_convertir(self, archivos: list[str], carpetas: list[str]) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/pdf/convertir", json={"archivos": [str(a) for a in archivos or []], "carpetas": [str(c) for c in carpetas or []]}))

    def pdf_estado(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", f"/visor/pdf/{quote(str(id), safe='')}"))

    def pdf_descargar(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/pdf/{quote(str(id), safe='')}/descargar", timeout=TIMEOUT_PRESUPUESTO_S))

    def historial_presupuestos(self) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/presupuestos"))

    def abrir_presupuesto_guardado(self, archivo: str) -> dict[str, Any]:
        identificador = str(archivo or "")
        if identificador.startswith(PREFIJO_ARCHIVO):
            identificador = identificador[len(PREFIJO_ARCHIVO):]
        if not RE_ID.match(identificador) or identificador in (".", ".."):
            return {"ok": False, "error": "Archivo no válido"}
        try:
            self.sincronizar_excel(identificador)           # the Excel edited here goes up first: then the server's version changes and the page refreshes what it shows
        except ErrorRemoto as exc:
            log.warning("Remote viewer: the edited Excel %s could not go up (%s)", identificador, exc)
        return self._seguro(lambda: self._json("GET", f"/visor/presupuestos/{quote(identificador)}",
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    # ----------------------------------------------------------------------- Excel editado en este equipo

    @staticmethod
    def _huella(datos: bytes) -> str:
        return hashlib.sha256(datos).hexdigest()

    def _marca(self, identificador: str) -> Path:
        """Next to the downloaded Excel: the fingerprint of the version that the server has (written when it is downloaded or uploaded)."""
        return self.carpeta / "descargas" / f"{identificador}.xlsx.sync"

    def sincronizar_excel(self, archivo: str) -> bool:
        """The Excel that is opened from the viewer is a copy downloaded to this computer; the PDF is made on the server from its own. When the copy was edited and saved
        (its fingerprint is not the one of what the server has) it goes up and replaces the server's, and the PDFs made from the old one are dropped. True when something
        was uploaded; False when there was nothing to apply. ErrorRemoto when it cannot be read or uploaded (the person is told: not silently a PDF without their changes)."""
        identificador = str(archivo or "")
        if identificador.startswith(PREFIJO_ARCHIVO):
            identificador = identificador[len(PREFIJO_ARCHIVO):]
        if not RE_ID.match(identificador) or identificador in (".", ".."):
            return False
        local = self.carpeta / "descargas" / f"{identificador}.xlsx"
        marca = self._marca(identificador)
        if not local.is_file():                                         # never downloaded here: nothing of theirs to apply
            return False
        if not marca.is_file():                                         # a copy downloaded before the viewer kept this note: what the server has now is the reference
            try:
                marca.write_text(self._huella(self._pedir("GET", f"/visor/archivo/{quote(identificador)}.xlsx", timeout=TIMEOUT_PRESUPUESTO_S).content), encoding="utf-8")
            except ErrorRemoto:
                return False                                            # the server cannot be asked now: the next time
        try:
            datos = local.read_bytes()
        except OSError:
            raise ErrorRemoto("No se pudo leer el Excel para aplicar sus cambios: cierre el Excel (guardando) e intente de nuevo") from None
        huella = self._huella(datos)
        if marca.read_text(encoding="utf-8").strip() == huella:
            return False
        try:
            self._pedir("PUT", f"/visor/presupuestos/{quote(identificador)}/excel", timeout=TIMEOUT_PRESUPUESTO_S, intentos=3, data=datos)
        except ErrorRemoto as exc:
            raise ErrorRemoto(f"No se pudieron aplicar los cambios del Excel en el servidor: {exc}") from None
        marca.write_text(huella, encoding="utf-8")
        (self.carpeta / "descargas" / f"{identificador}.pdf").unlink(missing_ok=True)       # made from the old Excel
        log.info("Remote viewer: the edited Excel %s went up to the server", identificador)
        return True

    # ----------------------------------------------------------------------- archivos

    def descargar(self, archivo: str, extension: str = "xlsx") -> Path:
        """Local copy (%TEMP%\\VisorRutas\\descargas) of a server budget "remoto:<id>"."""
        identificador = str(archivo or "")
        if identificador.startswith(PREFIJO_ARCHIVO):
            identificador = identificador[len(PREFIJO_ARCHIVO):]
        if extension not in ("xlsx", "pdf") or not RE_ID.match(identificador) or identificador in (".", ".."):
            raise ErrorRemoto("Archivo no válido")
        destino = self.carpeta / "descargas" / f"{identificador}.{extension}"
        if extension == "pdf":
            self.sincronizar_excel(identificador)                       # the PDF is made on the server from ITS Excel: it must be the one the person edited
            xlsx_local = destino.with_suffix(".xlsx")
            if destino.is_file() and xlsx_local.is_file() and xlsx_local.stat().st_mtime > destino.stat().st_mtime:
                destino.unlink(missing_ok=True)                         # a PDF older than the edited Excel is not the one that is wanted
        if destino.is_file() and destino.stat().st_size > 0:
            return destino
        respuesta = self._pedir("GET", f"/visor/archivo/{quote(identificador)}.{extension}", timeout=TIMEOUT_PRESUPUESTO_S)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        temporal.write_bytes(respuesta.content)
        temporal.replace(destino)
        if extension == "xlsx":
            self._marca(identificador).write_text(self._huella(respuesta.content), encoding="utf-8")     # what the server has: an edit of this copy is told apart from it
        return destino

    def hoja_excel(self, archivo: str, hoja: str, calculado: bool = True) -> dict[str, Any]:
        def accion() -> dict[str, Any]:
            if hoja not in ("Presupuesto", "Ruta proyectada"):
                return {"ok": False, "error": "Hoja no válida"}
            return {"ok": True, "html": excel_html.hoja_a_html(self.descargar(archivo, "xlsx"), hoja, bool(calculado))}
        return self._seguro(accion)

    def pdf_presupuesto(self, archivo: str) -> dict[str, Any]:
        def accion() -> dict[str, Any]:
            pdf = self.descargar(archivo, "pdf")
            return {"ok": True, "base64": base64.b64encode(pdf.read_bytes()).decode("ascii"), "nombre": pdf.name}
        try:
            return accion()
        except ErrorRemoto as exc:
            return {"ok": False, "error": f"PDF no disponible: {exc}"}
