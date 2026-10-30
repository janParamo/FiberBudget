"""Esquema de zona: las listas desplegables de los diálogos se abren como menú de la página (en la ventana aparte la lista nativa se dibujaba en blanco). Página real."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


async def _menu(mundo_):
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        for k in ("a", "c"):
            await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids[k])
            await p.esperar("window.Esquema._st.cajas.has(%d)" % ids[k], 5)
        await p.evaluar("window.Esquema._st.modo = 'cable'; window.Esquema._st.cajas.get(%d).fire('click'); window.Esquema._st.cajas.get(%d).fire('click'); true" % (ids["a"], ids["c"]))
        await p.esperar("!document.getElementById('modal-lz-cable').hidden", 5)
        # the list of «Hilos» opens as a menu of the page (the native one is drawn blank in the window) and choosing sets the value
        await p.evaluar("document.querySelector('#lz-cable-form [name=hilos]').dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, button: 0})); true")
        assert await p.evaluar("document.querySelectorAll('#lz-menu-select .lz-menu-op').length") == 10
        assert "24 hilos" in await p.evaluar("document.querySelector('#lz-menu-select .actual').textContent")
        await p.evaluar("document.querySelectorAll('#lz-menu-select .lz-menu-op')[7].dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true})); true")
        assert await p.evaluar("document.querySelector('#lz-cable-form [name=hilos]').value") == "4"
        assert await p.evaluar("document.getElementById('lz-menu-select')") is None
        assert await p.errores() == []


def test_the_lists_of_the_dialogs_open_as_a_menu_of_the_page(mundo):
    asyncio.run(_menu(mundo))
