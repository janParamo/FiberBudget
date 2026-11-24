"""Mapa base (web/mapa/tiles.js): las capas de teselas piden también las de más allá de cada borde y guardan más alrededor, para que al arrastrar no queden cuadros vacíos.
En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


async def _recorrido(con):
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.L && window.Redes && window.Redes.disponible", 30)
        r = await p.evaluar("""(() => { const d = document.createElement('div'); d.style.cssText = 'width:800px;height:600px;position:absolute;left:-9999px'; document.body.appendChild(d);
          const m = L.map(d).setView([12.13, -86.25], 15), centro = m.getCenter();
          const url = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7#{z}{x}{y}';
          const como_leaflet = L.tileLayer(url, {precarga: 0}).addTo(m), nueva = L.tileLayer(url).addTo(m), mas = L.tileLayer(url, {precarga: 2}).addTo(m);
          const ancho = (c) => c._getTiledPixelBounds(centro).getSize().x, alto = (c) => c._getTiledPixelBounds(centro).getSize().y;
          return {leaflet: [ancho(como_leaflet), alto(como_leaflet)], por_omision: [ancho(nueva), alto(nueva)], dos: ancho(mas), keep: nueva.options.keepBuffer, idle: nueva.options.updateWhenIdle,
                  fondo: getComputedStyle(document.getElementById('mapa')).backgroundColor}; })()""")
        assert r["leaflet"] == [800, 600]                                   # precarga 0: what Leaflet asks for
        assert r["por_omision"] == [800 + 512, 600 + 512]                   # one tile (256 px) more beyond each edge
        assert r["dos"] == 800 + 1024
        assert (r["keep"], r["idle"]) == (5, False)
        assert r["fondo"] != "rgb(43, 43, 43)"                              # what shows where a tile has not arrived is no longer almost black
        assert await p.errores() == []


def test_the_tile_layers_ask_for_a_margin_around_the_screen(con_redes):
    asyncio.run(_recorrido(con_redes))
