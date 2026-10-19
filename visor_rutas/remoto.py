"""Visor en modo remoto: los cálculos los hace la API de la PC del servidor por el túnel de ngrok.

ProveedorRemoto tiene los mismos métodos (y devuelve los mismos dict) que la Api local de
ventana_web.py, pero llamando a /visor/* de la API (visor_api.py) con requests. En la PC del
usuario no hay bases de datos, Google ni LibreOffice: solo esta clase, excel_html.py (para dibujar
las hojas de un Excel descargado) y la ventana.

Solo depende de requests, openpyxl (vía excel_html) y la biblioteca estándar: entra en el .exe.
"""
import base64
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from visor_rutas import excel_html

log = logging.getLogger(__name__)

AGENTE = "VisorRutas/1.0"
TIMEOUT_CONSULTA_S = 20           # route, layers, search
TIMEOUT_PRESUPUESTO_S = 180       # budgets: Google, map tiles and LibreOffice on the server
SIN_CONEXION = ("No se pudo conectar con el servidor de presupuestos. Verifique que el servicio "
                "esté encendido en la PC del servidor y que la URL sea correcta.")
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
        self._sesion = sesion or requests.Session()
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

    def _pedir(self, metodo: str, ruta: str, *, timeout: float = TIMEOUT_CONSULTA_S, **kwargs: Any) -> Any:
        """Response 2xx, or ErrorRemoto with a message for the user. One retry when the
        connection fails (and on a GET timeout); a POST that timed out is not repeated."""
        if not self.url:
            raise ErrorRemoto("Falta configurar el servidor (☰ → Configuración)")
        headers = {"X-Visor-Key": self._clave, "ngrok-skip-browser-warning": "1", "User-Agent": AGENTE}
        for intento in (1, 2):
            try:
                respuesta = self._sesion.request(metodo, f"{self.url}{ruta}", headers=headers,
                                                 timeout=timeout, **kwargs)
            except requests.Timeout:
                if metodo == "GET" and intento == 1:
                    continue
                raise ErrorRemoto("El servidor de presupuestos tardó demasiado en responder") from None
            except requests.RequestException as exc:
                if intento == 1:
                    time.sleep(1)
                    continue
                log.warning("Remote viewer: %s %s failed (%s)", metodo, ruta, type(exc).__name__)
                raise ErrorRemoto(SIN_CONEXION) from None
            if respuesta.status_code in (502, 503, 504) and intento == 1:
                time.sleep(1)
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

    def masivas_iniciar(self, nombre: str, puntos: list[dict[str, Any]]) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/masivas/iniciar", json={"nombre": str(nombre or ""), "puntos": puntos}))

    def masivas_estado(self, id: str, desde: int = 0) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", f"/visor/masivas/{quote(str(id), safe='')}", params={"desde": int(desde or 0)}))

    def masivas_cancelar(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/masivas/{quote(str(id), safe='')}/cancelar"))

    def masivas_descargar(self, id: str) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", f"/visor/masivas/{quote(str(id), safe='')}/descargar", timeout=TIMEOUT_PRESUPUESTO_S))

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

    def mufa(self, nodo_id: Any) -> dict[str, Any]:
        try:
            nodo = int(nodo_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Mufa no válida"}
        return self._seguro(lambda: self._json("GET", f"/visor/mufa/{nodo}"))

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
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    # ----------------------------------------------------------------------- presupuestos

    def presupuesto_config(self) -> dict[str, Any]:
        def accion() -> dict[str, Any]:
            return {"ok": True, **(self.info().get("presupuesto") or {}), "carpeta": str(self.carpeta)}
        return self._seguro(accion)

    def generar_presupuesto(self, campos: dict[str, Any]) -> dict[str, Any]:
        return self._seguro(lambda: self._json("POST", "/visor/presupuesto", json={"campos": dict(campos or {})},
                                               timeout=TIMEOUT_PRESUPUESTO_S))

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

    def historial_presupuestos(self) -> dict[str, Any]:
        return self._seguro(lambda: self._json("GET", "/visor/presupuestos"))

    def abrir_presupuesto_guardado(self, archivo: str) -> dict[str, Any]:
        identificador = str(archivo or "")
        if identificador.startswith(PREFIJO_ARCHIVO):
            identificador = identificador[len(PREFIJO_ARCHIVO):]
        if not RE_ID.match(identificador) or identificador in (".", ".."):
            return {"ok": False, "error": "Archivo no válido"}
        return self._seguro(lambda: self._json("GET", f"/visor/presupuestos/{quote(identificador)}",
                                               timeout=TIMEOUT_PRESUPUESTO_S))

    # ----------------------------------------------------------------------- archivos

    def descargar(self, archivo: str, extension: str = "xlsx") -> Path:
        """Local copy (%TEMP%\\VisorRutas\\descargas) of a server budget "remoto:<id>"."""
        identificador = str(archivo or "")
        if identificador.startswith(PREFIJO_ARCHIVO):
            identificador = identificador[len(PREFIJO_ARCHIVO):]
        if extension not in ("xlsx", "pdf") or not RE_ID.match(identificador) or identificador in (".", ".."):
            raise ErrorRemoto("Archivo no válido")
        destino = self.carpeta / "descargas" / f"{identificador}.{extension}"
        if destino.is_file() and destino.stat().st_size > 0:
            return destino
        respuesta = self._pedir("GET", f"/visor/archivo/{quote(identificador)}.{extension}", timeout=TIMEOUT_PRESUPUESTO_S)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        temporal.write_bytes(respuesta.content)
        temporal.replace(destino)
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
