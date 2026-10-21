"""Varios íconos en el mismo punto (web/mapa/superpuestos.js), de CUALQUIER tipo de capa: un pin, un marcador con icono y un círculo de canvas (como los nodos
Visio) en el mismo lugar. Un clic abre la lista y el abanico; uno suelto abre su popup de siempre; mientras se dibuja no estorba."""
import asyncio

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

PREPARAR = """(() => {
  const m = window.visor.mapa; m.setView([12.13, -86.25], 18, { animate: false });
  const lienzo = L.canvas({ padding: 0.5 }); const c = [12.13, -86.25];
  const pin = L.divIcon({ className: 'icono', html: '<svg width="30" height="42" viewBox="0 0 30 42"><path d="M15 41C2 24 2 15 15 2s13 22 0 39z" fill="#e01b84"/></svg>', iconSize: [30, 42], iconAnchor: [15, 41] });
  const rombo = L.divIcon({ className: 'icono', html: '<svg width="18" height="18"><path d="M9 1L17 9L9 17L1 9Z" fill="#1e88e5"/></svg>', iconSize: [18, 18], iconAnchor: [9, 9] });
  window.__abiertos = [];
  const abre = (n) => () => window.__abiertos.push(n);
  window.__capas = {
    buscada: L.marker(c, { icon: pin, pane: 'buscada' }).bindTooltip('MUFA 3M EL ALCON').on('click', abre('buscada')).addTo(m),
    nodo: L.marker(c, { icon: rombo }).bindTooltip('<b>NODO VISIO</b>').on('click', abre('nodo')).addTo(m),
    circulo: L.circleMarker(c, { renderer: lienzo, radius: 9, fillColor: '#ff8800', fillOpacity: 1 }).bindTooltip('POSTE 7').on('click', abre('circulo')).addTo(m),
    suelto: L.circleMarker([12.1315, -86.2515], { renderer: lienzo, radius: 9 }).bindTooltip('SOLO').on('click', abre('suelto')).addTo(m),
  };
  if (!m.getPane('buscada')) m.createPane('buscada').style.zIndex = 585;
  const px = (ll) => { const q = m.latLngToContainerPoint(ll), r = m.getContainer().getBoundingClientRect(); return { x: Math.round(r.left + q.x), y: Math.round(r.top + q.y) }; };
  return { pila: px(c), suelto: px([12.1315, -86.2515]) };
})()"""


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa && window.Superpuestos", 20)
        donde = await p.evaluar(PREPARAR)
        await asyncio.sleep(0.4)
        # ---- a lone point: its own click, no list
        await p.clic(donde["suelto"]["x"], donde["suelto"]["y"])
        await asyncio.sleep(0.4)
        assert await p.evaluar("window.__abiertos") == ["suelto"] and await p.evaluar("document.querySelectorAll('.sup-popup').length") == 0
        # ---- three icons on one point: the list and the fan, whichever of them is clicked (the pin is tall: click on its head)
        await p.clic(donde["pila"]["x"], donde["pila"]["y"] - 30)
        await p.esperar("document.querySelector('.sup-popup')", 5)
        assert await p.evaluar("window.__abiertos") == ["suelto"]                                      # nothing of the stack opened by itself
        assert "3 elementos aquí" in await p.evaluar("document.querySelector('.sup-popup h3').innerText")
        nombres = await p.evaluar("[...document.querySelectorAll('.sup-popup .lg-sup b')].map(b => b.innerText).sort()")
        assert nombres == ["MUFA 3M EL ALCON", "NODO VISIO", "POSTE 7"], nombres                       # the names come from their tooltips (HTML removed)
        assert await p.evaluar("document.querySelectorAll('.lg-abanico').length") == 3
        assert await p.evaluar("document.querySelectorAll('.leaflet-abanico-pane svg.leaflet-zoom-animated path').length") == 3
        # a click on a fan icon opens that one (the canvas circle too) and the fan folds
        caja = await p.evaluar("(() => { const r = document.querySelectorAll('.lg-abanico')[2].getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        elegido = await p.evaluar("window.__superpuestos[2].getTooltip().getContent()")
        await p.clic(caja[0], caja[1])
        await p.esperar("window.__abiertos.length === 2", 5)
        esperado = {"MUFA 3M EL ALCON": "buscada", "<b>NODO VISIO</b>": "nodo", "POSTE 7": "circulo"}[elegido]
        assert (await p.evaluar("window.__abiertos"))[1] == esperado
        await p.esperar("document.querySelectorAll('.lg-abanico').length === 0", 3)
        # a click on a row of the list opens that one too
        await p.clic(donde["pila"]["x"], donde["pila"]["y"] - 30)
        await p.esperar("document.querySelector('.sup-popup')", 5)
        await p.evaluar("[...document.querySelectorAll('.sup-popup .lg-sup')].find(b => b.innerText.includes('POSTE 7')).click(); true")
        await p.esperar("window.__abiertos.length === 3 && window.__abiertos[2] === 'circulo'", 5)
        # ---- while drawing, the click is for the drawing: no list
        await p.evaluar("window.visor.mapa.closePopup(); window.visor.mapa.pm.enableDraw('Line', { snappable: false }); true")
        await p.clic(donde["pila"]["x"], donde["pila"]["y"])
        await asyncio.sleep(0.5)
        assert await p.evaluar("document.querySelectorAll('.sup-popup').length") == 0 and len(await p.evaluar("window.__abiertos")) == 3
        await p.evaluar("window.visor.mapa.pm.disableDraw(); true")
        assert await p.errores() == []


def test_stacked_icons_of_any_layer_open_as_a_list_and_a_fan():
    asyncio.run(_recorrido())
