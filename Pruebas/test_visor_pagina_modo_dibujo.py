"""Dibujar encima de lo que ya está en el mapa (web/mapa/modo_dibujo.js): con un modo de dibujo activo, un clic sobre un poste, una mufa o una línea
(marcador, círculo de canvas, línea) pone el punto de la herramienta y NO abre la ficha del elemento; sin modo activo el elemento responde como siempre."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

PREPARAR = """(() => {
  const m = window.visor.mapa; m.setView([12.13, -86.25], 18);
  const c = m.getCenter(); window.__clics = { marcador: 0, circulo: 0, linea: 0, mapa: 0 };
  const lienzo = L.canvas({ padding: 0.5 });
  const marcador = L.marker([c.lat, c.lng + 0.0004]).addTo(m).on("click", () => window.__clics.marcador++);
  const circulo = L.circleMarker([c.lat, c.lng - 0.0004], { renderer: lienzo, radius: 9 }).addTo(m).on("click", () => window.__clics.circulo++);
  const linea = L.polyline([[c.lat - 0.0002, c.lng - 0.0001], [c.lat - 0.0002, c.lng + 0.0001]], { renderer: lienzo, weight: 10 }).addTo(m).on("click", () => window.__clics.linea++);
  m.on("click", () => window.__clics.mapa++);
  const px = (ll) => { const p = m.latLngToContainerPoint(ll), r = m.getContainer().getBoundingClientRect(); return { x: Math.round(r.left + p.x), y: Math.round(r.top + p.y) }; };
  window.__donde = { marcador: px(marcador.getLatLng()), circulo: px(circulo.getLatLng()), linea: px(L.latLng(c.lat - 0.0002, c.lng)) };
  return window.__donde;
})()"""


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        donde = await p.evaluar(PREPARAR)
        # the marker icon sits above its coordinate: click on the middle of the icon
        caja = await p.evaluar("(() => { const r = document.querySelector('.leaflet-marker-icon:not(.leaflet-div-icon)').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()")
        sitios = {"marcador": caja, "circulo": donde["circulo"], "linea": donde["linea"]}

        # ---- no drawing mode: the elements answer their own clicks
        for nombre, s in sitios.items():
            await p.clic(s["x"], s["y"])
            await asyncio.sleep(0.5)
        clics = await p.evaluar("window.__clics")
        assert (clics["marcador"], clics["circulo"], clics["linea"]) == (1, 1, 1), clics

        # ---- Geoman line drawing: the clicks go to the map and each one is a vertex of the line
        await p.evaluar("window.__clics = { marcador: 0, circulo: 0, linea: 0, mapa: 0 }; window.visor.mapa.pm.enableDraw('Line', { snappable: false }); true")
        for nombre in ("marcador", "circulo", "linea"):
            s = sitios[nombre]
            await p.clic(s["x"], s["y"])
            await asyncio.sleep(0.5)
        clics = await p.evaluar("window.__clics")
        assert (clics["marcador"], clics["circulo"], clics["linea"]) == (0, 0, 0), clics               # no element answered
        assert clics["mapa"] == 3, clics                                                               # the map received the three clicks, once each
        vertices = await p.evaluar("window.visor.mapa.pm.Draw.Line._layer.getLatLngs().length")
        assert vertices == 3, vertices                                                                 # and the line got its three points
        assert await p.evaluar("window.ModoDibujo.activo(window.visor.mapa)") is True
        await p.evaluar("window.visor.mapa.pm.disableDraw(); true")
        assert await p.evaluar("window.ModoDibujo.activo(window.visor.mapa)") is False

        # ---- out of the drawing mode again: back to normal
        s = sitios["circulo"]
        await p.clic(s["x"], s["y"])
        await asyncio.sleep(0.5)
        assert (await p.evaluar("window.__clics"))["circulo"] == 1
        assert await p.errores() == []


def test_drawing_on_top_of_existing_elements():
    asyncio.run(_recorrido())
