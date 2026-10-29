"""Esquema de zona: varios esquemas con su nombre (nuevo, renombrar, eliminar), la navegación como en Visio (rueda mueve, Ctrl + rueda acerca) y la
ventana aparte (el botón la pide y, en su propia ventana, solo se ve el esquema)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_lienzo import zona  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _consulta(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _nombrar(p, texto):
    await p.esperar("!document.getElementById('modal-lz-nombre').hidden", 5)
    await p.evaluar("(() => { const f = document.getElementById('lz-nombre-form'); f.elements.nombre.value = %r; f.requestSubmit(); return true; })()" % texto)


async def _recorrido(zona):
    con, proy, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        assert await p.evaluar("[...document.querySelectorAll('#lz-esquema option')].map(o => o.textContent)") == ["General"]
        await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids["m1"])
        await p.esperar("window.Esquema._st.cajas.size === 1", 10)
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        # a second schema, empty, with its own name
        await p.evaluar("document.getElementById('lz-nuevo').click(); true")
        await _nombrar(p, "Troncal norte")
        await p.esperar("[...document.querySelectorAll('#lz-esquema option')].length === 2 && window.Esquema._st.cajas.size === 0", 10)
        assert await p.evaluar("document.getElementById('lz-esquema').selectedOptions[0].textContent") == "Troncal norte"
        assert await p.evaluar("document.querySelectorAll('#lz-lista .lz-item').length") == 3             # everything is available again in the new one
        await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids["n"])
        await p.esperar("window.Esquema._st.cajas.size === 1", 10)
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        # rename the current one
        await p.evaluar("document.getElementById('lz-renombrar').click(); true")
        await _nombrar(p, "Troncal norte (Jalapa)")
        await p.esperar("document.getElementById('lz-esquema').selectedOptions[0].textContent === 'Troncal norte (Jalapa)'", 10)
        assert [f["nombre"] for f in _consulta(con, "SELECT nombre FROM redes.lienzos WHERE borrado_en IS NULL ORDER BY id")] == ["General", "Troncal norte (Jalapa)"]
        # a repeated name is refused with the reason
        await p.evaluar("document.getElementById('lz-nuevo').click(); true")
        await _nombrar(p, "general")
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Ya hay un esquema')", 10)
        # switching shows the other schema's own boxes
        await p.evaluar("(() => { const s = document.getElementById('lz-esquema'); s.value = s.options[0].value; s.dispatchEvent(new Event('change')); return true; })()")
        await p.esperar("window.Esquema._st.datos.lienzo.nombre === 'General' && window.Esquema._st.cajas.size === 1 && window.Esquema._st.cajas.has(%d)" % ids["m1"], 10)
        # delete the current one (asks first); the network is untouched
        await p.evaluar("document.getElementById('lz-borrar').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("[...document.querySelectorAll('#lz-esquema option')].length === 1 && window.Esquema._st.datos.lienzo.nombre === 'Troncal norte (Jalapa)'", 10)
        assert _consulta(con, "SELECT count(*) AS n FROM redes.elementos WHERE borrado_en IS NULL AND tipo IN ('mufa', 'nodo')")[0]["n"] == 3
        # as in Visio: the wheel scrolls, Ctrl + wheel zooms
        await p.evaluar("window.Esquema._st.stage.position({x: 100, y: 100}); window.Esquema._st.stage.scale({x: 1, y: 1}); true")
        c = (await p.cajas(c="#lz-konva"))["c"]
        x, y = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
        await p.enviar("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=120, modifiers=0)
        await p.esperar("window.Esquema._st.stage.y() < 100", 5)
        assert await p.evaluar("window.Esquema._st.stage.scaleX()") == 1                                  # it moved, did not zoom
        await p.enviar("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=-120, modifiers=2)
        await p.esperar("window.Esquema._st.stage.scaleX() > 1", 5)
        assert await p.errores() == []


def test_named_schemas_and_visio_like_navigation(zona):
    asyncio.run(_recorrido(zona))


async def _boton_aparte(zona):
    con, proy, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.__ventanas = []; window.__stubs.abrir_ventana = (tipo, q) => { window.__ventanas.push([tipo, q]); return {ok: true, ya_abierta: false}; }; true")
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await p.evaluar("document.getElementById('lz-aparte').click(); true")
        await p.esperar("window.__ventanas.length === 1 && document.getElementById('modal-lz').hidden", 5)
        assert await p.evaluar("window.__ventanas[0]") == ["esquema", {"nombre": proy["nombre"], "id": proy["id"]}]
        assert await p.errores() == []


def test_the_schema_button_asks_for_its_own_window(zona):
    asyncio.run(_boton_aparte(zona))


async def _ventana_del_esquema(zona):
    con, proy, ids = zona
    consulta = "#ventana=esquema&nombre=Jalapa&id=%d&t=Esquema%%20de%%20zona%%20%%C2%%B7%%20Jalapa%%20%%E2%%80%%93%%20Fiber%%20Budget" % proy["id"]
    async with pagina_edge(1100, 760, api=crear_api_prueba(con), consulta=consulta) as p:
        await p.evaluar("window.__ventanas = []; window.__stubs.cerrar_ventana = (t) => { window.__ventanas.push(['cerrar', t]); return {ok: true}; }; true")
        await p.esperar("!document.getElementById('modal-lz').hidden && document.querySelectorAll('#lz-lista .lz-item').length === 3", 30)      # it opens by itself
        assert await p.evaluar("window.visor.aparte") == "esquema" and await p.evaluar("document.title") == "Esquema de zona · Jalapa – Fiber Budget"
        cajas = await p.cajas(mapa="#mapa", barra="#barra", menu="#menu-lateral", aparte="#lz-aparte", max="#lz-max")
        assert all(v is None for v in cajas.values()), cajas                                              # only the schema: nothing to pop out again
        m = (await p.cajas(m="#modal-lz"))["m"]
        assert m["w"] == 1100 and m["h"] == 760, m                                                        # it fills the window
        await p.evaluar("document.getElementById('lz-cerrar').click(); true")                             # closing it closes the window
        await p.esperar("window.__ventanas.some(v => v[0] === 'cerrar')", 5)
        assert await p.errores() == []


def test_the_schema_window_shows_only_the_schema(zona):
    asyncio.run(_ventana_del_esquema(zona))
