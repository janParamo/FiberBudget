"""El diagrama Visio y el editor de una mufa en su propia ventana de Windows (se mueven fuera del programa para llenar la mufa a mano mirando el
Visio), y el aviso flotante que ya no queda tapado por la barra inferior.

  - Python: Api.abrir_ventana / cerrar_ventana con un `webview` falso (no hay ventanas nativas en las pruebas).
  - Página (Edge sin ventana): el aviso se ve entero con la ventana angosta; el botón «Ventana aparte» del diagrama y de la mufa pide la ventana con
    los parámetros correctos; `?ventana=diagrama` y `?ventana=mufa` muestran solo esa ventana.
"""
import asyncio
import sys
import types
from urllib.parse import parse_qs, urlparse

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge


# ---------------------------------------------------------------------------- Python

class VentanaFalsa:
    def __init__(self, titulo, url, **kw):
        self.title, self.url, self.kw, self.destruida, self.restaurada = titulo, url, kw, False, 0

    def restore(self):
        self.restaurada += 1

    def show(self):
        pass

    def destroy(self):
        self.destruida = True


@pytest.fixture
def webview_falso(monkeypatch):
    modulo = types.ModuleType("webview")
    modulo.windows = []

    def create_window(titulo, url=None, **kw):
        v = VentanaFalsa(titulo, url, **kw)
        modulo.windows.append(v)
        return v
    modulo.create_window = create_window
    monkeypatch.setitem(sys.modules, "webview", modulo)
    return modulo


def test_open_window_builds_the_url_and_does_not_duplicate(webview_falso):
    api = crear_api_prueba()
    r = api.abrir_ventana("diagrama", {"nombre": "MF ARMANDO VAZQUES", "indice": 1})
    assert r == {"ok": True, "ya_abierta": False}
    v = webview_falso.windows[0]
    q = {k: x[0] for k, x in parse_qs(urlparse(v.url).fragment).items()}
    assert q["ventana"] == "diagrama" and q["nombre"] == "MF ARMANDO VAZQUES" and q["indice"] == "1" and q["t"] == v.title
    assert v.title == "Diagrama Visio · MF ARMANDO VAZQUES – Fiber Budget" and v.kw["js_api"] is api            # the same Api: same session and mode
    again = api.abrir_ventana("diagrama", {"nombre": "MF ARMANDO VAZQUES"})
    assert again == {"ok": True, "ya_abierta": True} and len(webview_falso.windows) == 1 and v.restaurada == 1
    # the same mufa in its editor is another window; a different mufa too
    assert api.abrir_ventana("mufa", {"nombre": "MF ARMANDO VAZQUES", "id": 7})["ok"] is True
    assert api.abrir_ventana("diagrama", {"nombre": "MF OTRA"})["ok"] is True
    assert len(webview_falso.windows) == 3
    assert parse_qs(urlparse(webview_falso.windows[1].url).fragment)["id"] == ["7"]


def test_open_window_rejects_bad_requests(webview_falso):
    api = crear_api_prueba()
    assert api.abrir_ventana("mapa", {"nombre": "x"})["ok"] is False
    assert api.abrir_ventana("diagrama", {})["ok"] is False
    assert api.abrir_ventana("mufa", {"nombre": "MF", "id": "no"})["ok"] is False
    assert api.abrir_ventana("diagrama", {"nombre": "MF", "indice": "../x"})["ok"] is True                 # a wrong index becomes 0
    assert parse_qs(urlparse(webview_falso.windows[0].url).fragment)["indice"] == ["0"]
    assert "?" not in webview_falso.windows[0].url and webview_falso.windows[0].url.count("#") == 1      # a «?» breaks file:// URLs in WebView2


def test_close_window_only_closes_the_one_asked_and_never_the_main(webview_falso):
    api = crear_api_prueba()
    principal = VentanaFalsa("Visor de rutas – Fiber Budget", "x")
    webview_falso.windows.append(principal)
    api._ventana = principal
    api.abrir_ventana("diagrama", {"nombre": "MF A"})
    api.abrir_ventana("diagrama", {"nombre": "MF B"})
    a, b = webview_falso.windows[1:]
    assert api.cerrar_ventana(a.title) == {"ok": True}
    assert a.destruida and not b.destruida and not principal.destruida
    api.cerrar_ventana(principal.title)
    assert not principal.destruida                                                                          # the main window is never closed from a page


# ---------------------------------------------------------------------------- página

pytestmark_pagina = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MUFA = {"id": 1, "nombre": "MF ARMANDO VAZQUES", "tipo": "MUFA", "zona": "Managua", "diagramas": 1, "lat": 12.108021, "lon": -86.294782}
DETALLE = {"id": 1, "nombre": "MF ARMANDO VAZQUES", "tipo": "MUFA", "zona": "Managua", "propietario": "IDEAY", "lat": 12.108021, "lon": -86.294782,
           "archivos": [{"diagrama": True, "md5": "a" * 32, "ruta": "MANAGUA/MF.vsd", "nombre": "MF.vsd", "pagina": 0}], "textos": [], "hilos": []}


def _preparar_stubs(p):
    return p.evaluar("""(() => {
      window.__ventanas = [];
      window.__stubs.buscar_mufa = () => ({ok: true, resultados: [%s]});
      window.__stubs.mufa = () => ({ok: true, mufa: %s});
      window.__stubs.diagrama = () => ({ok: false, error: 'prueba'});
      window.__stubs.abrir_ventana = (tipo, p) => { window.__ventanas.push([tipo, p]); return {ok: true, ya_abierta: false}; };
      window.__stubs.cerrar_ventana = (t) => { window.__ventanas.push(['cerrar', t]); return {ok: true}; };
      return true; })()""" % (__import__("json").dumps(MUFA), __import__("json").dumps(DETALLE)))


async def _aviso_con_ventana_angosta():
    async with pagina_edge(760, 600) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        await p.evaluar("window.visor.mensaje('MF ARMANDO VAZQUES: no tiene diagrama Visio', 'error'); true")
        cajas = await p.cajas(aviso="#mensaje", barra="#barra")
        assert cajas["aviso"] and cajas["barra"], cajas
        assert cajas["aviso"]["w"] > 250, cajas                                                           # the whole text, not a squeezed corner
        assert cajas["aviso"]["y"] + cajas["aviso"]["h"] <= cajas["barra"]["y"], cajas                    # above the bar, not under it
        assert cajas["aviso"]["x"] >= 0 and cajas["aviso"]["x"] + cajas["aviso"]["w"] <= 760, cajas       # inside the window
        assert "no tiene diagrama Visio" in await p.evaluar("document.getElementById('mensaje').innerText")
        # nothing on top of it: the element at its centre is the notice itself (or its text)
        c = cajas["aviso"]
        assert await p.evaluar("(() => { const e = document.elementFromPoint(%d, %d); return !!e; })()" % (c["x"] + 10, c["y"] + 10))
        assert await p.errores() == []


async def _boton_ventana_aparte():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        await _preparar_stubs(p)
        await p.evaluar("window.visor.abrirDiagramaPorNombre('MF ARMANDO VAZQUES'); true")
        await p.esperar("!document.getElementById('pd-aparte').disabled", 10)
        # the button of the panel asks for the window with the mufa name and the diagram being seen
        await p.evaluar("document.getElementById('pd-aparte').click(); true")
        await p.esperar("window.__ventanas.length === 1", 5)
        assert await p.evaluar("window.__ventanas[0]") == ["diagrama", {"nombre": "MF ARMANDO VAZQUES", "indice": 0}]
        # the one of the full-screen viewer too, and it hands the diagram over: the viewer closes
        await p.evaluar("document.getElementById('pd-pantalla').click(); true")
        await p.esperar("!document.getElementById('modal-diagrama').hidden", 5)
        assert await p.evaluar("getComputedStyle(document.getElementById('diagrama-aparte')).display") != "none"
        await p.evaluar("document.getElementById('diagrama-aparte').click(); true")
        await p.esperar("window.__ventanas.length === 2 && document.getElementById('modal-diagrama').hidden", 5)
        assert await p.errores() == []


async def _ventana_de_diagrama():
    api = crear_api_prueba()
    api.buscar_mufa = lambda texto: {"ok": True, "resultados": [MUFA]}
    api.mufa = lambda id_: {"ok": True, "mufa": DETALLE}
    api.diagrama = lambda md5, pagina=0: {"ok": False, "error": "prueba"}
    consulta = "#ventana=diagrama&nombre=MF%20ARMANDO%20VAZQUES&indice=0&t=Diagrama%20Visio%20%C2%B7%20MF%20ARMANDO%20VAZQUES"
    async with pagina_edge(1000, 700, api=api, consulta=consulta) as p:
        await p.evaluar("window.__ventanas = []; window.__stubs.cerrar_ventana = (t) => { window.__ventanas.push(['cerrar', t]); return {ok: true}; }; true")
        await p.esperar("!document.getElementById('modal-diagrama').hidden", 15)                        # it opens by itself, as the window does
        assert await p.evaluar("document.title") == "Diagrama Visio · MF ARMANDO VAZQUES"
        assert await p.evaluar("window.visor.aparte") == "diagrama"
        assert await p.evaluar("document.getElementById('diagrama-titulo').textContent") == "MF ARMANDO VAZQUES"
        # only the diagram window is on screen: no map, no bar, no panels, no side menu, nothing to pop out again
        cajas = await p.cajas(mapa="#mapa", barra="#barra", lugares="#lugares", menu="#menu-lateral", panel="#panel", cerrar="#diagrama-cerrar")
        assert all(v is None for v in cajas.values()), cajas
        modal = (await p.cajas(m="#modal-diagrama"))["m"]
        assert modal["w"] == 1000 and modal["h"] == 700, modal                                           # it fills the window
        assert (await p.cajas(a="#diagrama-aparte"))["a"] is None
        # Esc in a window of its own closes the window (not only the viewer)
        await p.evaluar("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true")
        await p.esperar("window.__ventanas.some(v => v[0] === 'cerrar')", 5)
        assert await p.evaluar("window.__ventanas.find(v => v[0] === 'cerrar')[1]") == "Diagrama Visio · MF ARMANDO VAZQUES"


async def _ventana_de_mufa():
    stubs = """window.__ventanas = []; window.__redes = [];
      window.__stubs.abrir_ventana = (tipo, p) => { window.__ventanas.push([tipo, p]); return {ok: true}; };
      window.__stubs.cerrar_ventana = (t) => { window.__ventanas.push(['cerrar', t]); return {ok: true}; };"""
    async with pagina_edge(1000, 700, consulta="#ventana=mufa&nombre=MF%20UNO&id=7&t=Mufa%20%C2%B7%20MF%20UNO%20%E2%80%93%20Fiber%20Budget") as p:
        assert await p.evaluar("window.visor.aparte") == "mufa"
        # the window asks the editor for mufa 7 once the module answers (this test API has no network module: it says so on screen)
        await p.esperar("document.getElementById('mensaje-texto').textContent.includes('módulo de redes no está disponible')", 15)
        await p.evaluar(stubs + "; true")
        cajas = await p.cajas(mapa="#mapa", barra="#barra", lugares="#lugares", aparte="#mu-aparte", max="#mu-max")
        assert all(v is None for v in cajas.values()), cajas                                             # nothing but the editor's window
        assert await p.evaluar("document.title") == "Mufa · MF UNO – Fiber Budget"
        # «Ver Visio original» from the editor's own window asks for the diagram in a window of its own (when the mufa has one)
        await p.evaluar("""window.__stubs.buscar_mufa = () => ({ok: true, resultados: [%s]}); true""" % __import__("json").dumps(MUFA))
        assert await p.evaluar("window.visor.verVisioAlLado('MF ARMANDO VAZQUES')") is True
        assert await p.evaluar("window.__ventanas") == [["diagrama", {"nombre": "MF ARMANDO VAZQUES"}]]
        await p.evaluar("window.__stubs.buscar_mufa = () => ({ok: true, resultados: []}); true")
        assert await p.evaluar("window.visor.verVisioAlLado('MF SIN VISIO')") is False
        assert len(await p.evaluar("window.__ventanas")) == 1                                            # no empty window is opened


async def _marcador_de_busqueda_no_tapa_la_mufa():
    async with pagina_edge(1200, 800) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        await p.evaluar("""(() => {
          const m = window.visor.mapa; m.setView([12.1115, -86.2340], 18, { animate: false });
          if (!m.getPane('kmzPuntos')) m.createPane('kmzPuntos').style.zIndex = 590;      // what lugares.js creates with the KMZ
          window.__clics = { kmz: 0, buscada: 0 };
          L.marker([12.1115, -86.2340], { pane: 'kmzPuntos' }).addTo(m).on('click', () => window.__clics.kmz++);
          window.visor.marcarBuscada(12.1115, -86.2340, 'MF FERRETERIA LA PRINCIPAL', 'MUFA');      // the searched pin lands on the mufa's own marker
          return true; })()""")
        await asyncio.sleep(1.5)                                                                       # flyTo ends
        await p.evaluar("window.visor.mapa.eachLayer(l => { if (l.options && l.options.pane === 'buscada' && l.on) l.on('click', () => window.__clics.buscada++); }); true")
        orden = await p.evaluar("(() => { const z = (n) => Number(window.visor.mapa.getPane(n).style.zIndex); return z('kmzPuntos') > z('buscada'); })()")
        assert orden is True                                                                           # the searched pin is under the KMZ points
        pos = await p.evaluar("""(() => { const m = window.visor.mapa, q = m.latLngToContainerPoint([12.1115, -86.2340]), r = m.getContainer().getBoundingClientRect();
                                          return {x: Math.round(r.left + q.x), y: Math.round(r.top + q.y - 10)}; })()""")
        await p.clic(pos["x"], pos["y"])
        await p.esperar("document.querySelector('.sup-popup')", 5)
        # the two icons on one point are offered (list and fan): nothing opens by itself, and choosing the mufa's own marker reaches it
        assert await p.evaluar("window.__clics") == {"kmz": 0, "buscada": 0}
        assert await p.evaluar("document.querySelectorAll('.sup-popup .lg-sup').length") == 2
        await p.evaluar("[...document.querySelectorAll('.sup-popup .lg-sup')].find(b => !b.innerText.includes('FERRETERIA')).click(); true")
        await p.esperar("window.__clics.kmz === 1", 5)
        assert await p.evaluar("window.__clics") == {"kmz": 1, "buscada": 0}                           # the mufa's marker (its popup: Entrar a la mufa, diagrama…)
        assert await p.errores() == []


def test_searched_pin_does_not_cover_the_mufa_marker():
    if not hay_edge():
        pytest.skip("necesita Edge y la librería websockets")
    asyncio.run(_marcador_de_busqueda_no_tapa_la_mufa())


def test_notice_is_not_hidden_by_the_bottom_bar():
    if not hay_edge():
        pytest.skip("necesita Edge y la librería websockets")
    asyncio.run(_aviso_con_ventana_angosta())


def test_diagram_window_button_asks_for_the_window():
    if not hay_edge():
        pytest.skip("necesita Edge y la librería websockets")
    asyncio.run(_boton_ventana_aparte())


def test_diagram_window_shows_only_the_diagram():
    if not hay_edge():
        pytest.skip("necesita Edge y la librería websockets")
    asyncio.run(_ventana_de_diagrama())


def test_mufa_window_shows_only_the_editor():
    if not hay_edge():
        pytest.skip("necesita Edge y la librería websockets")
    asyncio.run(_ventana_de_mufa())
