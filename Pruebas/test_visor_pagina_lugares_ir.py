"""Panel «Lugares»: cada elemento del KMZ (y cada carpeta) tiene el botón ⌖ que lo selecciona y vuela a su coordenada, también en los resultados de la búsqueda
del panel. En la página real (Edge sin ventana); el KMZ es de mentira."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from test_visor_pagina_fase4b import CAPA, CARPETAS

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _api():
    api = crear_api_prueba()
    api.kmz_arbol = lambda: {"ok": True, "arbol": {"version": 1, "kmz": "prueba.kmz", "importado": "hoy", "raiz": "raiz", "carpetas": CARPETAS, "elementos": 2, "aviso": ""}, "iconos": {}}
    api.kmz_capa = lambda cid: {"ok": True, "capa": CAPA}
    api.kmz_indice = lambda: {"ok": True, "indice": {"m1": [["MF UNO", ""], ["MF DOS", ""]]}}
    return api


async def _centro(p):
    return await p.evaluar("(() => { const c = window.visor.mapa.getCenter(); return [c.lat, c.lng]; })()")


async def _recorrido():
    async with pagina_edge(1366, 768, api=_api()) as p:
        await p.esperar("window.Lugares && window.Lugares._s.arbol && window.visor && window.visor.mapa", 45)
        await p.evaluar("window.visor.mapa.setView([12.20, -86.40], 12, {animate: false}); true")
        # search in the panel: the element comes with its button, which selects it and flies to its coordinate
        await p.evaluar("(() => { const i = document.getElementById('lg-buscar'); i.value = 'mf dos'; i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
        await p.esperar("document.querySelector('#lg-filas [data-ir=\"m1:1\"]')", 15)
        await p.evaluar("document.querySelector('#lg-filas [data-ir=\"m1:1\"]').click(); true")
        await p.esperar("Math.abs(window.visor.mapa.getCenter().lat - 12.136) < 0.002 && Math.abs(window.visor.mapa.getCenter().lng + 86.256) < 0.002", 15)
        assert await p.evaluar("document.querySelector('#lg-filas .lg-fila.sel [data-ir=\"m1:1\"]') !== null")
        # a folder: the button frames its elements
        await p.evaluar("(() => { const i = document.getElementById('lg-buscar'); i.value = 'mufa'; i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
        await p.evaluar("window.visor.mapa.setView([12.20, -86.40], 12, {animate: false}); true")
        await p.esperar("document.querySelector('#lg-filas .lg-fila.carpeta .lg-ir')", 15)
        await p.evaluar("document.querySelector('#lg-filas .lg-fila.carpeta .lg-ir').click(); true")
        await p.esperar("Math.abs(window.visor.mapa.getCenter().lat - 12.135) < 0.01 && window.visor.mapa.getZoom() > 12", 10)
        assert await p.errores() == []


def test_lugares_button_flies_to_the_selected_element_and_folder():
    asyncio.run(_recorrido())
