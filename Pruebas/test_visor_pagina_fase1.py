"""Visor v2, phase 1 (docs/modulo_redes/ESPECIFICACION.md §2), in a real page (headless Edge, arnes_pagina.py):
one layers panel (the sections of "Lugares", no floating Leaflet control), layers that need a calculation are
disabled with their reason, zoom at the bottom right, nothing floating covers anything else, and the right
panel stays closed until there is a result. Same checks at 1366x768 and 1920x1080."""
import asyncio
import json

import pytest

from arnes_pagina import hay_edge, pagina_edge, se_cruzan

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

DATOS = {
    "cliente": {"lat": 12.1530, "lon": -86.2630},
    "conexion": {"nombre": "MF PRUEBA", "tipo": "mufa", "tipo_detalle": "mufa", "id": 1, "lat": 12.1500, "lon": -86.2600,
                 "distancia_lineal_m": 450.0, "fuente": "kmz", "requiere_revision": False, "notas": None},
    "ruta": {"puntos": [[12.1500, -86.2600], [12.1515, -86.2615], [12.1530, -86.2630]], "distancia_m": 480.0, "metraje_final_m": 520.0,
             "reserva_m": 40.0, "tipo_cable": "Flat", "aproximada": False, "acometida_m": 5.0},
    "postes_existentes": [[1, 12.1505, -86.2605]],
    "postes_nuevos": {"cantidad": 2, "posiciones": [[12.1515, -86.2615], [12.1522, -86.2622]], "metros": [200, 350], "spacing_m": 50},
    "mufas_en_ruta": [], "mufas_intervenidas": [{"id": 1, "nombre": "MF PRUEBA", "lat": 12.15, "lon": -86.26}],
    "mufas_intervenidas_fuente": "postgis", "distribution_reason": None, "nodos_visio_cercanos": [],
    "origen_trafico": {"nodo": None, "mf": None, "confianza": None, "camino": [], "motivo": "prueba", "etiqueta": None,
                       "mufa_etiquetada": None, "metodo": None, "emparejamiento": None, "diagnostico": None},
    "avisos": [], "ruta_fusion": [],
}
FLOTANTES = {"zoom": ".leaflet-control-zoom", "buscador": "#buscador", "panel": "#panel", "abrirPanel": "#abrir-panel",
             "abrirLugares": "#abrir-lugares", "lugares": "#lugares", "barra": "#barra", "leyenda": ".leyenda:not(.leyenda-troncales)",
             "troncales": ".leyenda-troncales"}


def correr(coro):
    return asyncio.run(coro)


async def _filas(p):
    return await p.evaluar("""[...document.querySelectorAll('#lg-filas .lg-fila')].map(f => ({
      texto: f.innerText.trim().replace(/\\s+/g, ' '), seccion: f.classList.contains('seccion'),
      deshabilitada: f.classList.contains('vacia'), aviso: f.title}))""")


async def _sin_solapes(p, nombre):
    cajas = await p.cajas(**FLOTANTES)
    for a in cajas:
        for b in cajas:
            if a < b and {a, b} != {"lugares", "abrirLugares"}:
                assert not se_cruzan(cajas[a], cajas[b]), f"{nombre}: {a} y {b} se pisan: {cajas[a]} {cajas[b]}"
    return cajas


async def _recorrido(ancho, alto):
    async with pagina_edge(ancho, alto) as p:
        # --- one layers panel: no floating Leaflet control; two sections in the tree of Lugares
        assert await p.evaluar("document.querySelectorAll('.leaflet-control-layers').length") == 0
        await p.esperar("document.querySelector('#lg-filas .lg-fila.seccion')")
        filas = await _filas(p)
        assert [f["texto"] for f in filas if f["seccion"]] == ["▾ Mapa base", "▾ Capas del visor"]
        textos = {f["texto"].split(" zoom")[0]: f for f in filas}
        for capa in ("Postes existentes", "Postes nuevos", "Mufas en ruta", "Mufas intervenidas", "Nodos Visio cercanos", "Camino de la fibra"):
            assert textos[capa]["deshabilitada"] and "se llena al generar una ruta" in textos[capa]["aviso"], capa
        assert "se llena al buscar una mufa" in textos["Mufa buscada"]["aviso"]
        assert "se llena al buscar una coordenada" in textos["Coordenada buscada"]["aviso"]
        assert "se llena al medir" in textos["Mis medidas"]["aviso"]
        assert not textos["Red Visio · nodos"]["deshabilitada"] and "zoom 12+" in textos["Red Visio · nodos"]["texto"]
        # --- the right panel starts closed (and its side tab too)
        assert await p.evaluar("document.getElementById('panel').hidden && document.getElementById('abrir-panel').hidden")
        inicio = await _sin_solapes(p, "inicio")
        assert inicio["panel"] is None
        # --- zoom at the bottom right, inside the map, above the bottom bar
        z = inicio["zoom"]
        assert z["x"] > ancho / 2 and z["y"] > alto / 2 and z["y"] + z["h"] <= inicio["barra"]["y"], z
        # --- collapsed Lugares: its tab is free (it was under the zoom control)
        await p.evaluar("document.getElementById('lg-plegar').click()")
        plegado = await _sin_solapes(p, "Lugares plegado")
        assert plegado["abrirLugares"] and plegado["lugares"] is None
        await p.evaluar("document.getElementById('abrir-lugares').click()")
        # --- base map and network layers from the tree
        await p.evaluar("document.querySelector('[data-capa-visor=\"base:calles\"]').click()")
        assert await p.evaluar("(() => { let c = 0, s = 0; window.visor.mapa.eachLayer(l => { c += !!(l._url && l._url.includes('World_Street')); "
                               "s += !!(l._url && l._url.includes('World_Imagery')); }); return [c, s]; })()") == [1, 0]
        await p.evaluar("document.querySelector('[data-capa-visor=\"base:satelite\"]').click()")
        await p.evaluar("window.__llamadas.length = 0")
        await p.evaluar("document.querySelector('[data-capa-visor=\"visor:visio_nodos\"]').click()")
        await p.esperar("window.__llamadas.includes('red')")
        await p.evaluar("document.querySelector('[data-capa-visor=\"visor:visio_nodos\"]').click()")
        # --- a route: the panel opens by itself, the layers of the route are enabled
        await p.evaluar("window.__stubs.calcular = () => ({ok: true, datos: %s, coordenada: '12.153000, -86.263000'});"
                        "window.__stubs.estimar_presupuesto = () => ({ok: false, error: 'prueba'});" % json.dumps(DATOS))
        await p.evaluar("document.getElementById('coord').value = '12.153, -86.263'; document.getElementById('generar').click();")
        await p.esperar("!document.getElementById('panel').hidden", 15)
        await asyncio.sleep(0.8)
        assert await p.evaluar("document.getElementById('panel').offsetWidth") <= 320            # narrower than the old 340
        filas = {f["texto"].split(" zoom")[0]: f for f in await _filas(p)}
        assert not filas["Postes nuevos"]["deshabilitada"] and not filas["Camino de la fibra"]["deshabilitada"]
        assert filas["Mufa buscada"]["deshabilitada"]
        con_ruta = await _sin_solapes(p, "con ruta")
        assert con_ruta["zoom"]["x"] + con_ruta["zoom"]["w"] <= con_ruta["panel"]["x"], "el zoom queda tapado por el panel"
        # the header box: partial (Red Visio is off), one click turns on every enabled layer
        assert await p.evaluar("document.querySelector('[data-sec-casilla=\"visor\"]').indeterminate")
        # --- the panel collapses to its side tab and opens again
        await p.evaluar("document.getElementById('cerrar-panel').click()")
        assert await p.evaluar("document.getElementById('panel').hidden && !document.getElementById('abrir-panel').hidden")
        contraido = await _sin_solapes(p, "panel contraído")
        assert contraido["abrirPanel"]
        await p.evaluar("document.getElementById('abrir-panel').click()")
        # --- clear: nothing to show, so the panel and its tab go away and the route layers are disabled again
        await p.evaluar("document.getElementById('limpiar').click()")
        assert await p.evaluar("document.getElementById('panel').hidden && document.getElementById('abrir-panel').hidden")
        assert await p.evaluar("document.querySelectorAll('#lg-filas .capa-visor.vacia').length") == 9
        assert await p.errores() == []


@pytest.mark.parametrize("ancho,alto", [(1366, 768), (1920, 1080)])
def test_interfaz_de_la_fase_1(ancho, alto):
    correr(_recorrido(ancho, alto))
