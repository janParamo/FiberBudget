"""Modo captura y buscador (página real, Edge sin ventana): el botón «Captura» deja solo el mapa a pantalla completa (sin menús, paneles, barras ni
controles) y Esc lo devuelve; las herramientas del mapa están dentro de la barra inferior, que ya no tiene campo de coordenada."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

ESCONDER = ["#barra", ".barra-herramientas", ".buscador", "#lugares", "#abrir-lugares", "#panel", "#abrir-panel", ".menu-lateral", ".leaflet-control-container"]


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa && document.querySelector('.barra-herramientas')", 20)
        # the toolbar is inside the bottom bar (not over the map, where the results list of the search box had to open over it), and the bar has no coordinate field
        assert await p.evaluar("!!document.querySelector('#barra > .barra-herramientas') && getComputedStyle(document.querySelector('.barra-herramientas')).position === 'static'")
        assert await p.evaluar("document.getElementById('coord').type") == "hidden"
        visibles = await p.evaluar("%s.map(s => { const e = document.querySelector(s); return !!e && e.getBoundingClientRect().width > 0; })" % ESCONDER.__repr__())
        assert sum(visibles) >= 6                                                                  # before: the interface is there
        await p.evaluar("document.getElementById('captura').click(); true")
        await p.esperar("document.body.classList.contains('modo-captura')", 5)
        assert await p.evaluar("%s.map(s => { const e = document.querySelector(s); return !e || getComputedStyle(e).display === 'none'; }).every(Boolean)" % ESCONDER.__repr__())
        caja = await p.evaluar("(() => { const r = document.getElementById('mapa').getBoundingClientRect(); return [r.left, r.top, r.width, r.height, innerWidth, innerHeight]; })()")
        assert caja[:2] == [0, 0] and caja[2] == caja[4] and caja[3] == caja[5]                      # the map fills the whole window
        assert await p.evaluar("document.querySelector('#mapa .leaflet-tile-pane') !== null")
        assert await p.evaluar("window.visor.mapa.getSize().x") == caja[4]                          # and Leaflet knows it
        await p.evaluar("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true")
        await p.esperar("!document.body.classList.contains('modo-captura')", 5)
        assert await p.evaluar("document.getElementById('barra').getBoundingClientRect().height") > 0
        assert await p.errores() == []


def test_modo_captura():
    asyncio.run(_recorrido())
