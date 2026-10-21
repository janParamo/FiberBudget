"""Splitters de la parada (web/mapa/splitters.js) en la página real: el bloque de la parada y la ventana donde se confirma la clase y los puertos.
El guardado en la red se simula; el de verdad está en test_splitters_diagrama.py."""
import asyncio
import json

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

SPLITTER = {"id": 7, "version": 2, "md5": "a" * 32, "clave": "10.0,10.0", "etiqueta": "SPL 1/8 SECUNDARIO", "archivo": "d.vsd", "clase": "por_confirmar",
            "clase_fuente": "sin_dato", "ratio": "1/8", "confirmado": False, "libres": 0, "desconocidos": 3,
            "puertos": {"1": {"estado": "ocupado", "cliente": "C10001", "fuente": "lista"}, "2": {"estado": "desconocido", "cliente": None, "fuente": "sin_dato"},
                        "3": {"estado": "desconocido", "cliente": None, "fuente": "sin_dato"}}}


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.SplitterPuertos", 20)
        html = await p.evaluar("window.SplitterPuertos.html(%s)" % json.dumps({"orden": 3, "splitters_diagrama": [SPLITTER]}))
        assert "data-splitter=\"3:0\"" in html and "Por confirmar" in html and "puertos por confirmar" in html and ">Confirmar<" in html
        assert await p.evaluar("window.SplitterPuertos.html({orden: 1, splitters_diagrama: []})") == ""

        # the window: the three ports, the class chooser; mark port 2 free and 3 occupied, choose secondary, save
        await p.evaluar("""(() => {
          window.__llamadas = [];
          window.Redes = Object.assign(window.Redes || {}, {llamar: async (m, a) => { window.__llamadas.push([m, a]);
            return {ok: true, id: a.id, version: 3, confirmado: {clase: a.clase, puertos: a.puertos}}; }});
          window.__s = %s; window.__r = null;
          window.SplitterPuertos.abrir(window.__s, (r) => { window.__r = r; });
          return true; })()""" % json.dumps(SPLITTER))
        assert await p.evaluar("document.querySelectorAll('.splitter-puertos tr').length") == 3
        await p.evaluar("""(() => {
          const marcar = (n, v) => { const r = document.querySelector(`input[name=p${n}][value=${v}]`); r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); };
          marcar(2, 'libre'); marcar(3, 'ocupado');
          const c = document.querySelector('[data-sp=clase]'); c.value = 'secundario';
          document.querySelector('[data-sp=guardar]').click(); return true; })()""")
        await p.esperar("window.__r !== null", 5)
        llamada = json.loads(await p.evaluar("JSON.stringify(window.__llamadas[0])"))
        assert llamada[0] == "confirmar_splitter" and llamada[1]["puertos"] == {"1": "ocupado", "2": "libre", "3": "ocupado"} and llamada[1]["clase"] == "secundario"
        assert await p.evaluar("document.querySelector('.splitter-modal')") is None             # closed after saving
        # what the page shows afterwards: confirmed class, one free port
        s = json.loads(await p.evaluar("JSON.stringify(window.SplitterPuertos.aplicar(window.__s, window.__r))"))
        assert s["clase"] == "secundario" and s["clase_fuente"] == "confirmado" and s["libres"] == 1 and s["desconocidos"] == 0 and s["confirmado"] and s["version"] == 3
        # a refused save keeps the window open with the message
        await p.evaluar("""(() => { window.Redes.llamar = async () => ({ok: false, error: 'Solo un administrador o un editor'});
          window.SplitterPuertos.abrir(%s, () => {}); document.querySelector('[data-sp=guardar]').click(); return true; })()""" % json.dumps(SPLITTER))
        await p.esperar("document.querySelector('.splitter-error') && !document.querySelector('.splitter-error').hidden", 5)
        assert "editor" in await p.evaluar("document.querySelector('.splitter-error').textContent")
        assert await p.evaluar("document.querySelector('.splitter-modal') !== null") is True


def test_the_splitters_of_a_stop_are_confirmed_on_the_page():
    asyncio.run(_recorrido())

