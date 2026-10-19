"""Visor v2, fase 2 (docs/modulo_redes/ESPECIFICACION.md §3), in a real page (headless Edge, arnes_pagina.py):
the search box takes coordinates (decimal, degrees-minutes-seconds, degrees-decimal minutes), validates Nicaragua and
warns of swapped latitude / longitude, puts a pin with its decimal label and a popup (copy, use for the route, remove)
and calculates NOTHING; other text goes to every registered source. The JavaScript reader is checked against the
Python one with the same cases (vectores_coordenadas.json)."""
import asyncio
import json
from pathlib import Path

import pytest

from arnes_pagina import hay_edge, pagina_edge
from visor_rutas import coordenadas
from config import NI_LAT_MAX, NI_LAT_MIN, NI_LON_MAX, NI_LON_MIN

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

VECTORES = json.loads((Path(__file__).parent / "vectores_coordenadas.json").read_text(encoding="utf-8"))
NO_CALCULA = {"calcular", "estimar_presupuesto", "generar_presupuesto"}


async def _escribir(p, texto):
    """Types in the search box (like the user): value + input event, then waits for the debounce and the answer."""
    await p.evaluar("(() => { const c = document.getElementById('buscar-mufa'); c.focus(); c.value = %s; "
                    "c.dispatchEvent(new Event('input', {bubbles: true})); })()" % json.dumps(texto))
    await asyncio.sleep(0.6)


async def _enter(p):
    await p.evaluar("document.getElementById('buscar-mufa').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")


async def _lista(p):
    return await p.evaluar("""(() => { const l = document.getElementById('buscar-resultados');
      return {visible: !l.hidden, filas: [...l.querySelectorAll('li')].map(li => ({clase: li.className, texto: li.innerText.trim().replace(/\\s+/g, ' '), elegible: !!li.dataset.i}))}; })()""")


async def _pin(p):
    return await p.evaluar("""(() => { const m = window.Pin.marcador; if (!m) return null; const ll = m.getLatLng();
      return {lat: ll.lat, lon: ll.lng, etiqueta: m.getTooltip().getContent()}; })()""")


async def _recorrido(ancho, alto):
    async with pagina_edge(ancho, alto) as p:
        # ---- the JavaScript reader = the Python one (same 41 cases, same messages)
        js = await p.evaluar("%s.map((t) => Coordenadas.interpretar(t))" % json.dumps([c["entrada"] for c in VECTORES]))
        for caso, r in zip(VECTORES, js):
            py = coordenadas.interpretar(caso["entrada"])
            assert r["estado"] == py.estado == caso["estado"], caso
            assert r["mensaje"] == py.mensaje, caso
            if py.estado in ("ok", "invertida", "fuera"):
                assert (r["lat"], r["lon"]) == pytest.approx((py.lat, py.lon), abs=1e-9), caso
        assert await p.evaluar("Coordenadas.limites") == {"latMin": NI_LAT_MIN, "latMax": NI_LAT_MAX, "lonMin": NI_LON_MIN, "lonMax": NI_LON_MAX}
        for lat, lon in ((13.094578, -86.002708), (12.153328, -86.263438), (11.9994983, -86.1214684), (13 + 5 / 60, -86.0)):
            assert await p.evaluar(f"Coordenadas.formatoGMS({lat}, {lon})") == coordenadas.formato_gms(lat, lon)
            assert await p.evaluar(f"Coordenadas.formatoDecimal({lat}, {lon})") == coordenadas.formato_decimal(lat, lon)

        await p.evaluar("window.__llamadas.length = 0; window.__copiado = []; window.__stubs.copiar = (t) => { window.__copiado.push(t); return {ok: true}; }")
        # ---- a decimal coordinate: one suggestion, Enter puts the pin, nothing is calculated
        await _escribir(p, "13.094578, -86.002708")
        lista = await _lista(p)
        assert lista["visible"] and [f["clase"] for f in lista["filas"]] == ["coordenada"]
        assert "Ir a la coordenada 13.094578, -86.002708" in lista["filas"][0]["texto"] and '13°5\'40.48"N 86°0\'9.75"O' in lista["filas"][0]["texto"]
        assert await p.evaluar("window.__llamadas.includes('buscar_mufa')") is False         # a coordinate asks no other source
        await _enter(p)
        pin = await _pin(p)
        assert pin == {"lat": pytest.approx(13.094578), "lon": pytest.approx(-86.002708), "etiqueta": "13.094578, -86.002708"}
        assert await p.evaluar("document.getElementById('buscar-resultados').hidden")
        assert await p.evaluar("document.querySelector('.etiqueta.coordenada').innerText") == "13.094578, -86.002708"
        capa = await p.evaluar("[...document.querySelectorAll('#lg-filas .capa-visor')].find(f => f.innerText.includes('Coordenada buscada')).classList.contains('vacia')")
        assert capa is False                                                                  # the layer is enabled now
        # ---- the pin popup: copy (decimal and degrees), use for the route, save (not yet), remove
        await p.evaluar("(window.Pin.marcador.openPopup(), true)")
        await p.esperar("document.querySelector('.pin-popup')")
        botones = await p.evaluar("[...document.querySelectorAll('.pin-popup [data-pin]')].map(b => [b.dataset.pin, b.disabled])")
        assert botones == [["copiar-decimal", False], ["copiar-gms", False], ["guardar", True], ["ruta", False], ["quitar", False]]
        await p.evaluar("document.querySelector('[data-pin=copiar-decimal]').click()")
        await p.evaluar("document.querySelector('[data-pin=copiar-gms]').click()")
        await asyncio.sleep(0.3)
        assert await p.evaluar("window.__copiado") == ["13.094578, -86.002708", '13°5\'40.48"N 86°0\'9.75"O']
        await p.evaluar("document.querySelector('[data-pin=ruta]').click()")
        assert await p.evaluar("document.getElementById('coord').value") == "13.094578, -86.002708"      # the bottom bar is filled...
        assert not NO_CALCULA & set(await p.evaluar("window.__llamadas"))                              # ...and nothing was calculated
        assert await p.evaluar("document.getElementById('panel').hidden")                              # no result panel either
        # ---- swapped latitude / longitude: warning + the right order offered; DMS; outside Nicaragua; another coordinate moves the pin
        await _escribir(p, "-86.002708, 13.094578")
        lista = await _lista(p)
        assert [f["clase"] for f in lista["filas"]] == ["vacio error", "coordenada"] and "invertidas" in lista["filas"][0]["texto"]
        assert "13.094578, -86.002708" in lista["filas"][1]["texto"]
        await _escribir(p, "40.7128, -74.0060")
        lista = await _lista(p)
        assert [f["clase"] for f in lista["filas"]] == ["vacio error"] and "fuera de Nicaragua" in lista["filas"][0]["texto"]
        await _enter(p)                                                                       # Enter on an error goes nowhere
        assert (await _pin(p))["lat"] == pytest.approx(13.094578)
        await _escribir(p, '12°9\'11.98"N 86°15\'48.38"O')
        await _enter(p)
        nuevo = await _pin(p)
        assert (nuevo["lat"], nuevo["lon"]) == pytest.approx((12.1533278, -86.2634389), abs=1e-5)
        await asyncio.sleep(0.5)                                                              # Leaflet fades the old label out for 200 ms
        assert await p.evaluar("window.Pin.marcador && document.querySelectorAll('.etiqueta.coordenada').length") == 1     # a single pin
        # ---- remove
        await p.evaluar("(window.Pin.marcador.openPopup(), true)")
        await p.esperar("document.querySelector('.pin-popup')")
        await p.evaluar("document.querySelector('[data-pin=quitar]').click()")
        assert await _pin(p) is None and await p.evaluar("window.Pin.hay()") is False
        assert await p.evaluar("[...document.querySelectorAll('#lg-filas .capa-visor')].find(f => f.innerText.includes('Coordenada buscada')).classList.contains('vacia')")
        # ---- anything else goes to every source, each with its title; a failing source does not hide the others
        await p.evaluar("""window.__stubs.buscar_mufa = (t) => ({ok: true, resultados: [
            {id: 1, nombre: 'MF CENTRO', tipo: 'MUFA', zona: 'Managua', diagramas: 2, lat: 12.1, lon: -86.3},
            {id: 2, nombre: 'MF CENTRO NORTE', tipo: 'MUFA', zona: null, diagramas: 0, lat: null, lon: null}]});
          window.__stubs.mufa = () => ({ok: false, error: 'prueba'});
          window.__elegido = null;
          Buscador.registrarFuente({id: 'prueba', titulo: 'Fuente de prueba', buscar: async (t) => [{titulo: 'Lugar ' + t, detalle: 'carpeta X'}],
                                    elegir: (it) => { window.__elegido = it.titulo; }});
          Buscador.registrarFuente({id: 'rota', titulo: 'Fuente rota', buscar: async () => { throw new Error('no responde'); }, elegir: () => {}});""")
        await _escribir(p, "centro")
        lista = await _lista(p)
        clases = [f["clase"] for f in lista["filas"]]
        assert clases == ["grupo", "", "", "grupo", "", "grupo", "vacio"], lista
        assert [f["texto"] for f in lista["filas"] if f["clase"] == "grupo"] == ["MUFAS Y NODOS (DIAGRAMAS VISIO)", "FUENTE DE PRUEBA", "FUENTE ROTA"]
        assert "sin coordenadas" in lista["filas"][2]["texto"] and "no responde" in lista["filas"][6]["texto"]
        # a pure number or a name with digits is a normal search, not a coordinate
        for texto in ("MF 12 NORTE", "2503"):
            await _escribir(p, texto)
            assert (await _lista(p))["filas"][0]["clase"] == "grupo", texto
        # keyboard: down, down, Enter takes the third selectable suggestion (the one of the test source)
        await _escribir(p, "centro")
        await p.evaluar("['ArrowDown', 'ArrowDown', 'ArrowDown'].forEach(k => document.getElementById('buscar-mufa').dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true})))")
        await _enter(p)
        assert await p.evaluar("window.__elegido") == "Lugar centro"
        assert await p.errores() == []


@pytest.mark.parametrize("ancho,alto", [(1366, 768), (1920, 1080)])
def test_buscador_de_coordenadas_con_pin(ancho, alto):
    asyncio.run(_recorrido(ancho, alto))
