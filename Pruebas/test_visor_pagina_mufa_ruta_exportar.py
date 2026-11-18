"""Editor de mufa: exportar la mufa completa (PNG / PDF) y la ruta de fusión de un cliente (clic derecho → «Ruta de fusión de este cliente…»).
En la página real (Edge sin ventana) con una base desechable."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import _hilo, mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MENU = """(hilo) => { const st = window.EditorMufa._st;
  const c = st.capa.find('.puerto').find((x) => x.getAttr('puerto') === 'h:' + hilo);
  c.fire('contextmenu', {evt: new MouseEvent('contextmenu', {clientX: 300, clientY: 300, bubbles: true, cancelable: true})}); return true; }"""


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    d3, o5 = _hilo(con, admin, ids["a"], "Distribución", 3), _hilo(con, admin, ids["b"], "Otro", 5)
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": d3["id"], "codigo_cliente": "C28995", "nombre": "Casa del Café"}]})
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": d3["id"]}, "b": {"hilo": o5["id"]}}]})
    sid = mufa.guardar(con, admin, mufa_id=ids["c"], cambios={"splitters": [{"id": "s", "nombre": "SPL 1/8", "salidas": 8}]})["ids"]["s"]
    mufa.guardar(con, admin, mufa_id=ids["c"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": o5["id"]}, "b": {"splitter": sid, "lado": "salida", "numero": 3}}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 1", 15)
        vista = await p.evaluar("(() => { const t = window.EditorMufa._st.stage; return [t.scaleX(), t.x(), t.y(), t.width()]; })()")
        # export: the whole mufa as a PNG (or PDF) handed to the program
        await p.evaluar("window.__exp = null; window.__stubs.guardar_imagen = (n, d, t) => { window.__exp = [n, d.slice(0, 22), t, d.length]; return {ok: true, ruta: 'C:/x.png'}; }; "
                        "document.getElementById('mu-png').click(); true")
        await p.esperar("window.__exp", 10)
        exp = await p.evaluar("window.__exp")
        assert exp[0] == "MF Uno" and exp[1] == "data:image/png;base64," and exp[2] == "png" and exp[3] > 2000
        await p.evaluar("window.__exp = null; document.getElementById('mu-pdf').click(); true")
        await p.esperar("window.__exp", 10)
        assert (await p.evaluar("window.__exp"))[2] == "pdf"
        # what is on the screen is not left changed by the export (same size and zoom)
        assert await p.evaluar("(() => { const t = window.EditorMufa._st.stage; return [t.scaleX(), t.x(), t.y(), t.width()]; })()") == vista
        # the route of the client
        await p.evaluar("(%s)(%d)" % (MENU, d3["id"]))
        await p.evaluar("document.querySelector('#mu-menu li[data-mu-cliente-ruta]').click(); true")
        await p.esperar("!document.getElementById('modal-mu-rf').hidden", 10)
        lineas = await p.evaluar("[...document.querySelectorAll('#mu-rf-lista li')].map(li => li.textContent)")
        assert len(lineas) == 3 and lineas[0].endswith("H1 del cliente fusionarlo con H3 hacia MF Dos") and lineas[2].endswith("con H3 del SPL 1/8 de MF Otra")
        assert "splitter" in await p.evaluar("document.getElementById('mu-rf-nota').textContent")
        assert await p.errores() == []


def test_the_mufa_is_exported_and_the_fusion_route_of_a_client_is_shown(mundo):
    asyncio.run(_recorrido(mundo))
