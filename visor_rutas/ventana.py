"""Ventana del visor de rutas: mapa (tkintermapview), barra inferior y panel de resumen."""
import io
import logging
import os
import queue
import ssl
import threading
import tkinter as tk
import urllib.request
from tkinter import ttk
from typing import Any

import certifi
import requests
import tkintermapview
from PIL import Image, ImageDraw, ImageFont, ImageTk, UnidentifiedImageError
from requests.adapters import HTTPAdapter

from mapa_ruta import DROP_COLOR, DROP_MIN_M, IMAGERY_URL, LABELS_URL, USER_AGENT
from visor_rutas.calculo import VisorError, calcular_ruta, parsear_coordenadas

log = logging.getLogger(__name__)

TILE_TIMEOUT_S = 15
OSM_URL = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
CAPAS = ("Satélite", "Calles")
INICIO = (12.13, -86.25)          # Managua
ZOOM_INICIAL = 12
MAX_HISTORIAL = 10

COLOR_RUTA = "#FFD400"
COLOR_RUTA_APROX = "#FF8C00"
COLOR_ACOMETIDA = "#{:02X}{:02X}{:02X}".format(*DROP_COLOR)
COLOR_CONEXION = "#00C846"
COLOR_CLIENTE = "#E61E1E"
COLOR_POSTE = "#FFFFFF"
COLOR_POSTE_NUEVO = "#9A9A9A"
COLOR_MUFA = "#FF8C00"
COLOR_NODO = "#2878FF"
COLOR_ERROR = "#B00020"
PIN_ALTO = 46          # height of tkintermapview's pin above its coordinate


class _AdaptadorTeselas(HTTPAdapter):
    """Uses one SSL context, loaded once, for every tile connection."""

    def __init__(self, contexto: ssl.SSLContext, **kwargs: Any):
        self._contexto = contexto
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ssl_context"] = self._contexto
        super().init_poolmanager(*args, **kwargs)


def _sesion_teselas() -> requests.Session:
    """Session for map tiles.

    tkintermapview calls requests.get once per tile. With CURL_CA_BUNDLE/REQUESTS_CA_BUNDLE set
    (the PostgreSQL installer sets CURL_CA_BUNDLE) requests reloads that CA file on every new
    connection (~0.7 s each), and 25 parallel tiles freeze the map. Same CA file, loaded once.
    """
    bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
    cafile = bundle if bundle and os.path.isfile(bundle) else certifi.where()
    sesion = requests.Session()
    sesion.trust_env = False                          # keep verify=True: no per-connection reload
    sesion.proxies.update(urllib.request.getproxies())  # trust_env=False would drop the proxy
    sesion.headers["User-Agent"] = USER_AGENT
    adaptador = _AdaptadorTeselas(ssl.create_default_context(cafile=cafile),
                                  pool_connections=4, pool_maxsize=32)
    sesion.mount("https://", adaptador)
    sesion.mount("http://", adaptador)
    return sesion


class _Mapa(tkintermapview.TkinterMapView):
    """TkinterMapView with tile downloads through _sesion_teselas (timeout, one SSL context).

    Also fixes the street-name overlay: tkintermapview 1.30 resizes it with Image.ANTIALIAS,
    removed in Pillow 10, so every satellite tile with labels came out empty.
    """

    _sesion = None

    def request_image(self, zoom: int, x: int, y: int, db_cursor: Any = None) -> ImageTk.PhotoImage:
        if _Mapa._sesion is None:
            _Mapa._sesion = _sesion_teselas()
        cache = self.tile_image_cache                 # a layer change replaces it: stale tiles stay out
        base, overlay = self.tile_server, self.overlay_tile_server
        try:
            image = self._descargar(base, zoom, x, y)
            if overlay is not None:
                etiquetas = self._descargar(overlay, zoom, x, y).convert("RGBA")
                if etiquetas.size != (self.tile_size, self.tile_size):
                    etiquetas = etiquetas.resize((self.tile_size, self.tile_size), Image.LANCZOS)
                image = image.convert("RGBA")
                image.paste(etiquetas, (0, 0), etiquetas)
            if not self.running:
                return self.empty_tile_image
            image_tk = ImageTk.PhotoImage(image)
        except (UnidentifiedImageError, requests.HTTPError):   # no tile at this zoom/place
            cache[f"{zoom}{x}{y}"] = self.empty_tile_image
            return self.empty_tile_image
        except Exception as exc:                                # offline, timeout...: retried on next move
            log.debug("Tile %s/%s/%s failed (%s)", zoom, x, y, type(exc).__name__)
            return self.empty_tile_image
        cache[f"{zoom}{x}{y}"] = image_tk
        return image_tk

    def _descargar(self, plantilla: str, zoom: int, x: int, y: int) -> Image.Image:
        url = plantilla.replace("{x}", str(x)).replace("{y}", str(y)).replace("{z}", str(zoom))
        respuesta = _Mapa._sesion.get(url, timeout=TILE_TIMEOUT_S)
        respuesta.raise_for_status()
        image = Image.open(io.BytesIO(respuesta.content))
        image.load()
        return image


def _fuente() -> ImageFont.ImageFont:
    for nombre in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(nombre, 13)
        except OSError:
            continue
    return ImageFont.load_default()


FUENTE_ETIQUETA = None


def _circulo(color: str, diametro: int) -> Image.Image:
    escala = 4
    tam = diametro * escala
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((escala, escala, tam - escala, tam - escala), fill=color,
                                outline="black", width=escala * 2)
    return img.resize((diametro, diametro), Image.LANCZOS)


def _icono(color: str, diametro: int, texto: str | None = None, color_texto: str = "white",
           espacio_abajo: int = 0) -> ImageTk.PhotoImage:
    """Marker image, drawn centred on its coordinate (icon_anchor="center").

    diametro > 0: circle (poles, mufas, nodes), with the label above it.
    diametro == 0: label only, raised espacio_abajo px (above the connection/client pins).
    The label has a black outline so it reads on satellite imagery.
    """
    global FUENTE_ETIQUETA
    if FUENTE_ETIQUETA is None:
        FUENTE_ETIQUETA = _fuente()
    alto_texto = ancho_texto = 0
    if texto:
        x0, y0, x1, y1 = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox(
            (0, 0), texto, font=FUENTE_ETIQUETA, stroke_width=3)
        ancho_texto, alto_texto = x1 - x0, y1 - y0
    franja = alto_texto + 4 + espacio_abajo        # label band above the centre; mirrored below
    ancho = max(diametro, ancho_texto) + 6
    alto = 2 * franja + max(diametro, 1)
    img = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    if diametro:
        img.paste(_circulo(color, diametro), ((ancho - diametro) // 2, franja), _circulo(color, diametro))
    if texto:
        ImageDraw.Draw(img).text(((ancho - ancho_texto) // 2, 0), texto, font=FUENTE_ETIQUETA,
                                 fill=color_texto, stroke_width=3, stroke_fill="black")
    return ImageTk.PhotoImage(img)


class VisorRutas:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.resultados: queue.Queue = queue.Queue()
        self.calculando = False
        self.historial: list[str] = []
        root.title("Visor de rutas")
        root.minsize(900, 600)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        self.iconos = {
            "poste": _icono(COLOR_POSTE, 11),
            "poste_nuevo": _icono(COLOR_POSTE_NUEVO, 11),
        }
        self.imagenes_ruta: list[ImageTk.PhotoImage] = []

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # Mapa
        _Mapa._sesion = _sesion_teselas()     # before the map starts its loader threads
        self.mapa = _Mapa(root, corner_radius=0)
        self.mapa.grid(row=0, column=0, sticky="nsew")
        self.mapa.add_right_click_menu_command("Usar esta coordenada", self._usar_coordenada, pass_coords=True)
        self.mapa.add_right_click_menu_command("Copiar coordenada", self._copiar_coordenada, pass_coords=True)

        # Panel lateral (resumen)
        self.panel = ttk.Frame(root, width=330, padding=(8, 6))
        self.panel.grid(row=0, column=1, sticky="ns")
        self.panel.grid_propagate(False)
        self.panel.rowconfigure(1, weight=1)
        self.panel.columnconfigure(0, weight=1)
        ttk.Label(self.panel, text="Resumen", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.texto = tk.Text(self.panel, wrap="word", relief="flat", font=("Segoe UI", 10),
                             background=root.cget("background"), cursor="arrow", padx=2)
        barra_texto = ttk.Scrollbar(self.panel, orient="vertical", command=self.texto.yview)
        self.texto.configure(yscrollcommand=barra_texto.set)
        self.texto.grid(row=1, column=0, sticky="nsew")
        barra_texto.grid(row=1, column=1, sticky="ns")
        self.texto.tag_configure("titulo", font=("Segoe UI", 10, "bold"), spacing1=6)
        self.texto.tag_configure("aviso", background="#FFF3B0", foreground="#5A3E00",
                                 lmargin1=4, lmargin2=4, spacing1=2, spacing3=2)
        self.texto.tag_configure("leyenda", font=("Segoe UI", 9), foreground="#444444")
        self._mostrar_leyenda()
        self.panel_visible = True

        # Barra inferior
        barra = ttk.Frame(root, padding=(8, 6))
        barra.grid(row=1, column=0, columnspan=2, sticky="ew")
        barra.columnconfigure(6, weight=1)
        ttk.Label(barra, text="Coordenada cliente (lat, lon):").grid(row=0, column=0, padx=(0, 6))
        self.entrada = ttk.Combobox(barra, width=34, values=self.historial)
        self.entrada.grid(row=0, column=1)
        self.entrada.bind("<Return>", lambda _e: self.generar())
        self.entrada.bind("<KP_Enter>", lambda _e: self.generar())
        self.boton = ttk.Button(barra, text="Generar ruta", command=self.generar)
        self.boton.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(barra, text="Limpiar", command=self.limpiar).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(barra, text="Capa:").grid(row=0, column=4, padx=(14, 4))
        self.capa = ttk.Combobox(barra, values=CAPAS, state="readonly", width=10)
        self.capa.set(CAPAS[0])
        self.capa.bind("<<ComboboxSelected>>", lambda _e: self._aplicar_capa())
        self.capa.grid(row=0, column=5)
        self.estado = ttk.Label(barra, text="Pegue una coordenada y presione Enter", anchor="w",
                                wraplength=650)
        self.estado.grid(row=0, column=6, sticky="ew", padx=(14, 6))
        self.boton_panel = ttk.Button(barra, text="Ocultar resumen", command=self._alternar_panel)
        self.boton_panel.grid(row=0, column=7)

        self._aplicar_capa()
        self.mapa.set_position(*INICIO)
        self.mapa.set_zoom(ZOOM_INICIAL)
        self.entrada.focus_set()
        self.root.after(100, self._revisar_resultados)

    # ------------------------------------------------------------------ barra
    def _mensaje(self, texto: str, error: bool = False) -> None:
        self.estado.configure(text=texto, foreground=COLOR_ERROR if error else "")

    def _aplicar_capa(self) -> None:
        if self.capa.get() == "Calles":
            self.mapa.set_overlay_tile_server(None)
            self.mapa.set_tile_server(OSM_URL, max_zoom=19)
        else:
            self.mapa.set_overlay_tile_server(LABELS_URL)
            self.mapa.set_tile_server(IMAGERY_URL, max_zoom=19)   # also resets the tile cache

    def _alternar_panel(self) -> None:
        if self.panel_visible:
            self.panel.grid_remove()
            self.boton_panel.configure(text="Mostrar resumen")
        else:
            self.panel.grid()
            self.boton_panel.configure(text="Ocultar resumen")
        self.panel_visible = not self.panel_visible

    def _agregar_historial(self, texto: str) -> None:
        if texto in self.historial:
            self.historial.remove(texto)
        self.historial.insert(0, texto)
        del self.historial[MAX_HISTORIAL:]
        self.entrada.configure(values=self.historial)

    def _usar_coordenada(self, coords: tuple[float, float]) -> None:
        self.entrada.set(f"{coords[0]:.6f}, {coords[1]:.6f}")
        self.entrada.focus_set()

    def _copiar_coordenada(self, coords: tuple[float, float]) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(f"{coords[0]:.6f}, {coords[1]:.6f}")
        self._mensaje(f"Coordenada copiada: {coords[0]:.6f}, {coords[1]:.6f}")

    # ------------------------------------------------------------------ cálculo
    def generar(self) -> None:
        if self.calculando:
            return
        texto = self.entrada.get().strip()
        try:
            lat, lon = parsear_coordenadas(texto)
        except VisorError as exc:
            self._mensaje(str(exc), error=True)
            return
        self._agregar_historial(f"{lat:.6f}, {lon:.6f}")
        self.entrada.set(f"{lat:.6f}, {lon:.6f}")
        self.calculando = True
        self.boton.state(["disabled"])
        self.root.configure(cursor="watch")
        self._mensaje("Calculando…")
        threading.Thread(target=self._trabajo, args=(lat, lon), daemon=True).start()

    def _trabajo(self, lat: float, lon: float) -> None:
        """Hilo aparte: nunca toca Tk, solo deja el resultado en la cola."""
        try:
            self.resultados.put(("ok", calcular_ruta(lat, lon)))
        except VisorError as exc:
            self.resultados.put(("error", str(exc)))
        except Exception as exc:   # anything else: logged, shown briefly
            log.exception("Visor: route calculation failed")
            self.resultados.put(("error", f"Error inesperado ({type(exc).__name__}): {exc}. "
                                          "Detalle en logs/visor.log"))

    def _revisar_resultados(self) -> None:
        try:
            while True:
                tipo, dato = self.resultados.get_nowait()
                self.calculando = False
                self.boton.state(["!disabled"])
                self.root.configure(cursor="")
                if tipo == "ok":
                    try:
                        self._dibujar(dato)
                        self._resumen(dato)
                        self._mensaje("Ruta aproximada (sin Google)" if dato["ruta"]["aproximada"]
                                      else "Ruta generada", error=dato["ruta"]["aproximada"])
                    except Exception:
                        log.exception("Visor: drawing failed")
                        self._mensaje("No se pudo dibujar la ruta. Detalle en logs/visor.log", error=True)
                else:
                    self._mensaje(dato, error=True)
        except queue.Empty:
            pass
        self.root.after(100, self._revisar_resultados)

    # ------------------------------------------------------------------ mapa
    def limpiar(self) -> None:
        self.mapa.delete_all_marker()
        self.mapa.delete_all_path()
        self.imagenes_ruta = []
        self.entrada.set("")
        self._mostrar_leyenda()
        self._mensaje("Pegue una coordenada y presione Enter")
        self.entrada.focus_set()

    def _marcador(self, lat: float, lon: float, imagen: ImageTk.PhotoImage) -> None:
        self.mapa.set_marker(lat, lon, icon=imagen, icon_anchor="center")

    def _etiquetado(self, lat: float, lon: float, texto: str, color: str, diametro: int = 15,
                    espacio_abajo: int = 0) -> None:
        """Marker whose image carries its outlined label (kept referenced until the next route)."""
        imagen = _icono(color, diametro, texto, color, espacio_abajo)
        self.imagenes_ruta.append(imagen)
        self._marcador(lat, lon, imagen)

    def _dibujar(self, r: dict[str, Any]) -> None:
        self.mapa.delete_all_marker()
        self.mapa.delete_all_path()
        self.imagenes_ruta = []
        puntos = r["ruta"]["puntos"]
        color = COLOR_RUTA_APROX if r["ruta"]["aproximada"] else COLOR_RUTA
        self.mapa.set_path(puntos, color=color, width=6)
        cliente = r["cliente"]
        if r["ruta"]["acometida_m"] >= DROP_MIN_M:      # same drop line as the Excel map
            acometida = [puntos[-1], (cliente["lat"], cliente["lon"])]
            self.mapa.set_path(acometida, color="black", width=9)
            self.mapa.set_path(acometida, color=COLOR_ACOMETIDA, width=5)

        for _id, lat, lon in r["postes_existentes"]:
            self._marcador(lat, lon, self.iconos["poste"])
        for lat, lon in r["postes_nuevos"]["posiciones"]:
            self._marcador(lat, lon, self.iconos["poste_nuevo"])
        conexion = r["conexion"]
        for mufa in r["mufas_en_ruta"]:
            if (mufa["lat"], mufa["lon"]) != (conexion["lat"], conexion["lon"]):
                self._etiquetado(mufa["lat"], mufa["lon"], mufa["nombre"], COLOR_MUFA)
        for nodo in r["nodos_visio_cercanos"]:
            self._etiquetado(nodo["lat"], nodo["lon"], nodo["nombre"], COLOR_NODO)

        for punto, texto, color_pin in ((conexion, conexion["nombre"], COLOR_CONEXION),
                                        (cliente, "Cliente", COLOR_CLIENTE)):
            self.mapa.set_marker(punto["lat"], punto["lon"], marker_color_circle="white",
                                 marker_color_outside=color_pin)
            self._etiquetado(punto["lat"], punto["lon"], texto, color_pin, diametro=0, espacio_abajo=PIN_ALTO)

        lats = [p[0] for p in puntos] + [conexion["lat"], cliente["lat"]]
        lons = [p[1] for p in puntos] + [conexion["lon"], cliente["lon"]]
        margen = max(max(lats) - min(lats), max(lons) - min(lons)) * 0.12 + 0.0008
        self.mapa.fit_bounding_box((max(lats) + margen, min(lons) - margen),
                                   (min(lats) - margen, max(lons) + margen))

    # ------------------------------------------------------------------ panel
    def _escribir(self, bloques: list[tuple[str, str]]) -> None:
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        for texto, tag in bloques:
            self.texto.insert("end", texto, tag)
        self.texto.configure(state="disabled")

    def _mostrar_leyenda(self) -> None:
        self._escribir([
            ("Leyenda\n", "titulo"),
            ("Amarillo: ruta (naranja si es aproximada)\nLínea verde: acometida al cliente\n"
             "Verde: punto de conexión\nRojo: cliente\n"
             "Blanco: postes existentes\nGris: postes nuevos\nNaranja: mufas en la ruta\n"
             "Azul: nodos Visio cercanos\n\n", "leyenda"),
            ("Clic derecho en el mapa para usar o copiar una coordenada.\n", "leyenda"),
        ])

    def _resumen(self, r: dict[str, Any]) -> None:
        c, ruta, origen = r["conexion"], r["ruta"], r["origen_trafico"]
        intervenidas = r["mufas_intervenidas"]
        b: list[tuple[str, str]] = []
        if r["avisos"]:
            b.append(("Avisos\n", "titulo"))
            b += [(f"⚠ {aviso}\n", "aviso") for aviso in r["avisos"]]
        b.append(("Punto de conexión\n", "titulo"))
        b.append((f"{c['nombre']}\nTipo: {c['tipo']}"
                  + (f" ({c['tipo_detalle']})" if c["tipo_detalle"] and c["tipo_detalle"] != c["tipo"] else "")
                  + f"\nFuente: {c['fuente']}\n{c['lat']:.6f}, {c['lon']:.6f}\n"
                  f"Línea recta al cliente: {c['distancia_lineal_m']:,.1f} m\n"
                  + ("Requiere revisión\n" if c["requiere_revision"] else "")
                  + (f"Notas: {c['notas']}\n" if c["notas"] else ""), ""))
        b.append(("Ruta\n", "titulo"))
        b.append((f"Distancia por ruta: {ruta['distancia_m']:,.1f} m"
                  + (" (línea recta)" if ruta["aproximada"] else "")
                  + (f"\nAcometida al cliente: {ruta['acometida_m']:,.0f} m"
                     if ruta["acometida_m"] >= DROP_MIN_M else "")
                  + f"\nMetraje final: {ruta['metraje_final_m']:,.1f} m (reserva {ruta['reserva_m']:,.1f} m)\n"
                  f"Cable: {ruta['tipo_cable']}\n", ""))
        b.append(("Postes\n", "titulo"))
        b.append((f"Existentes: {len(r['postes_existentes'])}\n"
                  f"Nuevos: {r['postes_nuevos']['cantidad']} (cada {r['postes_nuevos']['spacing_m']} m)\n", ""))
        b.append((f"Mufas intervenidas: {len(intervenidas)}\n", "titulo"))
        if r["mufas_intervenidas_fuente"]:
            b.append((f"Fuente: {r['mufas_intervenidas_fuente']}\n", "leyenda"))
        b += [(f"• {m['nombre']}\n", "") for m in intervenidas]
        b.append(("Origen de tráfico\n", "titulo"))
        b.append((f"OLT / Nodo: {origen['nodo'] or 'Pendiente de validar'}\n"
                  f"MF: {origen['mf'] or '—'}\nConfianza: {origen['confianza'] or '—'}\n", ""))
        if origen["camino"]:
            b.append(("Camino: " + " → ".join(origen["camino"]) + "\n", "leyenda"))
        if origen.get("metodo") in ("c", "d"):
            b.append(("Mufa de conexión emparejada por nombre: validar\n", "aviso"))
        if origen.get("diagnostico"):
            b.append((f"Diagnóstico: {origen['diagnostico']['detalle']}\n", "leyenda"))
        if r["nodos_visio_cercanos"]:
            b.append(("Nodos Visio cercanos\n", "titulo"))
            b += [(f"• {n['nombre']} ({n['tipo']}, {n['distancia_m']:,.0f} m)\n", "") for n in r["nodos_visio_cercanos"]]
        self._escribir(b)
