"""Buscar dentro del diagrama de Visio (web/mapa/busqueda_diagrama.js): el campo sobre el diagrama (texto o coordenada), pasar entre resultados, la lista,
y el interruptor «Círculo» (el de la mufa y el de lo encontrado), en la página real. El servidor se simula; la búsqueda de verdad está en
test_visor_fusion.py y test_visor_api.py."""
import asyncio
import base64
import json

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MD5 = "a" * 32
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"><rect width="1200" height="600" fill="#fff"/></svg>'
DATA_URL = "data:image/svg+xml;base64," + base64.b64encode(SVG.encode()).decode()
MUFA = {"id": 1, "nombre": "MF ARMANDO VAZQUES", "tipo": "MUFA", "zona": "Managua", "diagramas": 1, "lat": 12.108021, "lon": -86.294782}
DETALLE = {"id": 1, "nombre": "MF ARMANDO VAZQUES", "tipo": "MUFA", "zona": "Managua", "propietario": "IDEAY", "lat": 12.108021, "lon": -86.294782, "textos": [], "hilos": [],
           "archivos": [{"diagrama": True, "md5": MD5, "ruta_relativa": "MANAGUA/MF.vsd", "nombre": "MF.vsd", "rol": "principal", "tipo_diagrama": "mufa",
                         "ancla": {"x_cm": 30.0, "y_cm": 15.0, "ancho_cm": 60.0, "alto_cm": 30.0}}]}
PAGINA = {"ancho_cm": 60.0, "alto_cm": 30.0, "pagina": 0}

STUBS = """(() => {
  window.__busquedas = [];
  window.__stubs.buscar_mufa = () => ({ok: true, resultados: [%s]});
  window.__stubs.mufa = () => ({ok: true, mufa: %s});
  window.__stubs.diagrama = () => ({ok: true, data_url: %s, formato: 'svg'});
  window.__stubs.buscar_en_diagrama = (md5, texto) => {
    window.__busquedas.push([md5, texto]);
    const t = texto.toLowerCase();
    if (t.includes('ferre')) return {ok: true, modo: 'texto', total: 2, resultados: [
      Object.assign({texto: 'MUFA FERRETERIA LA PRINCIPAL', x_cm: 12, y_cm: 8}, %s), Object.assign({texto: 'HACIA FERRETERIA', x_cm: 48, y_cm: 22}, %s)]};
    if (/^12\\./.test(t)) return {ok: true, modo: 'coordenada', total: 1, resultados: [
      Object.assign({texto: 'MF OTRA / 12.12346, -86.23457', x_cm: 20, y_cm: 10, distancia_m: 3.2, coordenada: {lat: 12.12346, lon: -86.23457}}, %s)]};
    if (t.includes('mufa uno')) return {ok: true, modo: 'texto', total: 2, mufas_en_diagrama: 5, resultados: [
      Object.assign({texto: 'MF UNO', x_cm: 20, y_cm: 10, mufa: {nombre: 'MF UNO', tipo: 'MUFA', lat: 12.1, lon: -86.2, estimada: false}}, %s),
      Object.assign({texto: 'MF DOS', x_cm: 40, y_cm: 12, distancia_m: 120.5, mufa: {nombre: 'MF DOS', tipo: 'MUFA', lat: 12.2, lon: -86.3, estimada: true}}, %s)]};
    return {ok: true, modo: 'texto', total: 0, resultados: []};
  };
  return true; })()""" % (json.dumps(MUFA), json.dumps(DETALLE), json.dumps(DATA_URL), json.dumps(PAGINA), json.dumps(PAGINA), json.dumps(PAGINA), json.dumps(PAGINA), json.dumps(PAGINA))


async def _escribir(p, selector, texto):
    await p.evaluar("(() => { const i = document.querySelector(%s); i.focus(); i.value = %s; i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
                    % (json.dumps(selector), json.dumps(texto)))


async def _tecla(p, selector, tecla, mayus=False):
    await p.evaluar("document.querySelector(%s).dispatchEvent(new KeyboardEvent('keydown', {key: %s, shiftKey: %s, bubbles: true, cancelable: true})); true"
                    % (json.dumps(selector), json.dumps(tecla), "true" if mayus else "false"))


async def _centro(p, selector):
    c = (await p.cajas(x=selector))["x"]
    return (c["x"] + c["w"] / 2, c["y"] + c["h"] / 2) if c else None


async def _recorrido():
    BUS = "#pd-busqueda .dg-bus-texto"
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa && window.BusquedaDiagrama", 20)
        await p.evaluar(STUBS)
        await p.evaluar("window.visor.abrirDiagramaPorNombre('MF ARMANDO VAZQUES'); true")
        await p.esperar("!document.getElementById('pd-img').hidden && document.getElementById('pd-img').naturalWidth > 0", 15)
        # the search box is there, the circle is on by default and the mufa's own ring shows
        assert (await p.cajas(b=BUS))["b"] is not None and await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-check').checked") is True
        await p.esperar("!document.getElementById('pd-anillo').hidden", 5)
        lienzo = await _centro(p, "#pd-lienzo")

        # ---- a text: finds both, goes to the first and circles it (orange ring in the middle of the viewer)
        await _escribir(p, BUS, "ferre")
        await p.esperar("document.querySelector('#pd-busqueda .dg-bus-info').textContent === '1 de 2'", 5)
        assert await p.evaluar("window.__busquedas.at(-1)") == [MD5, "ferre"]
        assert await p.evaluar("document.querySelectorAll('#pd-busqueda .dg-bus-fila').length") == 2
        anillo = await _centro(p, "#pd-lienzo .anillo-busqueda")
        assert anillo and abs(anillo[0] - lienzo[0]) < 4 and abs(anillo[1] - lienzo[1]) < 4, (anillo, lienzo)
        # ---- Enter: the next one; Shift+Enter: back
        await _tecla(p, BUS, "Enter")
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-info').textContent") == "2 de 2"
        assert (await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-fila.activa').innerText")).startswith("HACIA FERRETERIA")
        await _tecla(p, BUS, "Enter", mayus=True)
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-info').textContent") == "1 de 2"
        # the list: a click on a row goes to it
        await p.evaluar("(() => { const f = document.querySelectorAll('#pd-busqueda .dg-bus-fila')[1]; f.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true})); return true; })()")
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-info').textContent") == "2 de 2"

        # ---- the circle off: neither the found one nor the mufa's ring; on again: both
        await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-check').click(); true")
        assert await p.evaluar("document.getElementById('pd-anillo').hidden && document.querySelector('#pd-lienzo .anillo-busqueda').hidden") is True
        assert await p.evaluar("localStorage.getItem('visor.circulo_diagrama')") == "0"
        await p.evaluar("document.getElementById('pd-ubicar').click(); true")                         # «Ubicar mufa» still goes there, without the ring
        assert await p.evaluar("document.getElementById('pd-anillo').hidden") is True
        await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-check').click(); true")
        assert await p.evaluar("!document.getElementById('pd-anillo').hidden && !document.querySelector('#pd-lienzo .anillo-busqueda').hidden") is True
        assert await p.evaluar("localStorage.getItem('visor.circulo_diagrama')") == "1"

        # ---- a coordinate: the text that writes it, with how far it is
        await _escribir(p, BUS, "12.12346, -86.23457")
        await p.esperar("document.querySelector('#pd-busqueda .dg-bus-info').textContent === '1 de 1'", 5)
        assert "a 3.2 m" in await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-fila').innerText")
        # ---- the mufas drawn in the diagram come as «Mufa» with their coordinate (and how far they are from a coordinate)
        await _escribir(p, BUS, "mufa uno")
        await p.esperar("document.querySelector('#pd-busqueda .dg-bus-info').textContent === '1 de 2 · mufa'", 5)
        filas = await p.evaluar("[...document.querySelectorAll('#pd-busqueda .dg-bus-fila')].map((f) => f.innerText.replace(/\s+/g, ' ').trim())")
        assert filas[0].startswith("MUFA MF UNO") and "12.10000, -86.20000" in filas[0] and "(estimada)" not in filas[0]
        assert "MF DOS" in filas[1] and "12.20000, -86.30000 (estimada)" in filas[1] and "a 120.5 m" in filas[1]
        assert await p.evaluar("document.querySelectorAll('#pd-busqueda .dg-bus-mufa').length") == 2
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-texto').placeholder") == "Buscar en el diagrama: texto, mufa o coordenada"
        # ---- nothing found: it says so and no ring is left from the previous search
        await _escribir(p, BUS, "zzzz")
        await p.esperar("document.querySelector('#pd-busqueda .dg-bus-info').textContent.includes('No está en este diagrama')", 5)
        assert await p.evaluar("document.querySelector('#pd-lienzo .anillo-busqueda').hidden") is True
        # ---- Esc clears the box (and does not close anything else)
        await _tecla(p, BUS, "Escape")
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-texto').value") == "" and await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-info').textContent") == ""

        # ---- the full-screen viewer has its own box and the same circle switch
        await p.evaluar("document.getElementById('pd-pantalla').click(); true")
        await p.esperar("!document.getElementById('modal-diagrama').hidden && document.getElementById('diagrama-img').naturalWidth > 0", 10)
        assert await p.evaluar("document.querySelector('#diagrama-busqueda .dg-bus-check').checked") is True
        await p.evaluar("document.querySelector('#diagrama-busqueda .dg-bus-check').click(); true")
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-check').checked") is False                  # both switches move together
        assert await p.evaluar("document.getElementById('diagrama-anillo').hidden") is True
        await _escribir(p, "#diagrama-busqueda .dg-bus-texto", "ferre")
        await p.esperar("document.querySelector('#diagrama-busqueda .dg-bus-info').textContent === '1 de 2'", 5)
        assert await p.evaluar("document.querySelector('#diagrama-lienzo .anillo-busqueda').hidden") is True              # found, circle off: no ring
        assert await p.errores() == []


def test_search_inside_the_visio_diagram_and_the_circle_switch():
    asyncio.run(_recorrido())


STUBS_TEXTO = STUBS + """;(() => {
  window.__stubs.buscar_texto_diagramas = (texto) => ({ok: true, total: 1, resultados: texto.toLowerCase().includes('ferre')
    ? [{md5: %s, nombre: 'MF.vsd', ruta_relativa: 'MANAGUA/MF.vsd', tipo_diagrama: 'mufa', coincidencias: 2, texto: 'MUFA FERRETERIA LA PRINCIPAL'}] : []});
  return true; })()""" % json.dumps(MD5)


async def _texto_en_todos():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa && window.BusquedaDiagrama", 20)
        await p.evaluar(STUBS_TEXTO)
        await _escribir(p, "#buscar-mufa", "ferreteria")
        await p.esperar("document.querySelectorAll('#buscar-resultados li[data-i]').length > 0", 5)
        assert "MF.vsd" in await p.evaluar("document.getElementById('buscar-resultados').textContent")
        assert "Texto dentro de los diagramas Visio" in await p.evaluar("document.getElementById('buscar-resultados').textContent")
        assert "2 coincidencia(s)" in await p.evaluar("document.getElementById('buscar-resultados').textContent")
        await p.evaluar("(() => { const li = [...document.querySelectorAll('#buscar-resultados li[data-i]')].find(x => x.textContent.includes('MF.vsd')); "
                        "li.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true})); return true; })()")
        # the diagram opens in the panel with the same text in its own search box, and goes to the first match
        await p.esperar("!document.getElementById('pd-img').hidden && document.getElementById('pd-img').naturalWidth > 0", 15)
        assert await p.evaluar("document.querySelector('#pd-busqueda .dg-bus-texto').value") == "ferreteria"
        await p.esperar("document.querySelector('#pd-busqueda .dg-bus-info').textContent === '1 de 2'", 5)
        assert [MD5, "ferreteria"] in await p.evaluar("window.__busquedas")
        assert await p.errores() == []


def test_search_a_text_in_all_the_visio_diagrams_opens_the_diagram_with_that_text():
    asyncio.run(_texto_en_todos())
