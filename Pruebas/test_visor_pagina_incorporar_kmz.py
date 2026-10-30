"""Ventana Importar KMZ → «Incorporar a la red» (web/lugares/importar_kmz.js): lo que se aplicó al importar entra al archivo de la red. El servidor se simula con respuestas fijas: la
lógica de verdad está en test_redes_incorporar_kmz.py."""
import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _api(con, previa):
    api = crear_api_prueba(con)
    original = api.redes
    llamadas = []

    def redes(metodo, args=None):
        llamadas.append((metodo, args))
        if metodo == "estado_actualizar_red":
            return {"ok": True, "kmz": {"archivo": "RED DE IDEAY.kmz", "tamano": 1, "modificado": "2026-10-29T10:00:00"}, "sincronizaciones": []}
        if metodo == "incorporar_previa_kmz":
            return {"ok": True, **previa["valor"]}
        if metodo == "incorporar_kmz_red":
            previa["valor"] = {"agregados": 0, "modificados": 0, "eliminados": 0, "manuales": 0, "importaciones": []}
            return {"ok": True, "agregados": 3, "modificados": 2, "eliminados": 1, "no_encontrados": 0, "importaciones": 1, "archivo": "RED DE IDEAY.kmz", "elementos": 36006, "anterior_en": "x"}
        return original(metodo, args)

    api.redes = redes
    api.llamadas = llamadas
    return api


async def _recorrido(mundo):
    con, *_ = mundo
    previa = {"valor": {"agregados": 3, "modificados": 2, "eliminados": 1, "manuales": 1, "importaciones": [{"id": 7, "archivo": "red_nueva.kmz"}]}}
    api = _api(con, previa)
    async with pagina_edge(1366, 768, api=api) as p:
        await p.esperar("window.ImportarKmz && window.ImportarKmz.estado.listo", 20)
        await p.clic_en('[data-bh="importar"]')
        await p.esperar("!document.getElementById('ik-ventana').hidden && document.querySelector('[data-ik=red_incorporar]')", 10)
        texto = await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        assert "Incorporar a la red" in texto and "3 nuevo(s), 2 modificado(s) y 1 eliminado(s)" in texto and "1 cambio(s) hechos a mano" in texto and "red_nueva.kmz" in texto
        assert "RED DE IDEAY.kmz" in texto and await p.evaluar("document.querySelector('[data-ik=red_incorporar]').disabled") is False
        await p.evaluar("document.querySelector('[data-ik=red_incorporar]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        confirmacion = await p.evaluar("document.getElementById('modal-confirmar').innerText")
        assert "3 nuevo(s), 2 modificado(s) y 1 eliminado(s)" in confirmacion and "anteriores" in confirmacion
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden && document.getElementById('modal-confirmar').innerText.includes('36,006 elementos')", 10)
        assert ("incorporar_kmz_red", {}) in api.llamadas
        await p.evaluar("document.getElementById('conf-no').click(); true")                                  # not now: no reload
        await p.esperar("document.getElementById('ik-cuerpo').innerText.includes('No hay nada que incorporar')", 8)
        assert await p.evaluar("document.querySelector('[data-ik=red_incorporar]').disabled") is True      # nothing left to incorporate
        assert await p.errores() == []


def test_the_administrator_incorporates_the_applied_imports_into_the_network_file(mundo):
    import asyncio
    asyncio.run(_recorrido(mundo))
