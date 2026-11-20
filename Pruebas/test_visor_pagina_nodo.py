"""El nodo como lugar físico (web/redes/nodo.js): sus ODF como mosaicos de puertos libres / ocupados, sus OLT y los hilos de una OLT. En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import nodo

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _filas(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _recorrido(zona_):
    con, admin, proy, ids = zona_
    nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=24)
    nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT Granada", puertos=8)
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        # a mufa has no button for the node; the node has it
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["m1"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.datos.mufa.id === %d" % ids["m1"], 15)
        assert await p.evaluar("document.getElementById('mu-grupo-nodo').hidden") is True
        await p.evaluar("window.EditorMufa.abrir(%d, 'Nodo Jalapa'); true" % ids["n"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.datos.mufa.id === %d" % ids["n"], 15)
        assert await p.evaluar("document.getElementById('mu-grupo-nodo').hidden") is False
        await p.evaluar("document.getElementById('mu-nodo').click(); true")
        await p.esperar("!document.getElementById('modal-nodo').hidden && document.querySelectorAll('#nd-odfs .nd-baldosa').length === 24", 10)
        assert await p.evaluar("(() => { const r = document.querySelector('#nd-odfs').getBoundingClientRect(); const e = document.elementFromPoint(r.left + 40, r.top + 30); return !!e && !!e.closest('#modal-nodo'); })()") is True      # on top of the mufa editor
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-baldosa.libre').length") == 24 and await p.evaluar("document.querySelectorAll('#nd-olts .nd-olt').length") == 1
        # a free tile: connect it to a port of the OLT and to fibre 3 of the cable that goes to MF Uno
        await p.evaluar("document.querySelector('#nd-odfs .nd-baldosa[data-nd-baldosa$=\":5\"]').click(); true")
        await p.esperar("!document.getElementById('modal-nd-enlace').hidden", 5)
        await p.evaluar("""(() => { const f = document.getElementById('nd-enl-form'); f.elements.oltpuerto.value = '2'; f.elements.cable.value = f.elements.cable.options[1].value; f.elements.cable.dispatchEvent(new Event('change'));
          f.elements.hilo.value = [...f.elements.hilo.options].find(o => o.textContent.startsWith('Hilo 3')).value; f.requestSubmit(); return true; })()""")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-baldosa.ocupada').length === 1", 10)
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-baldosa.ocupada').title") == "Puerto 5 · ocupado: OLT Granada (hilo 2) · Troncal hilo 3 → MF Uno"
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-odf header small').textContent") == "24 puertos · 1 ocupado · 23 libres"
        e = _filas(con, "SELECT olt_puerto, odf_puerto FROM redes.nodo_enlaces WHERE borrado_en IS NULL")
        assert e == [{"olt_puerto": 2, "odf_puerto": 5}]
        # inside the OLT: its fibres, the second one is used and says where it goes
        await p.evaluar("document.querySelector('[data-nd-abrir-olt]').click(); true")
        await p.esperar("document.querySelectorAll('#nd-olt-filas tr').length === 8", 5)
        fila = await p.evaluar("[...document.querySelectorAll('#nd-olt-filas tr')[1].children].map(td => td.textContent.trim())")
        assert fila[:4] == ["2", "ODF A · puerto 5", "Troncal · hilo 3", "MF Uno"]
        assert await p.evaluar("document.querySelectorAll('#nd-olt-filas tr.libre').length") == 7
        # back to the node; a new ODF and a new OLT from the buttons
        await p.evaluar("document.getElementById('nd-volver').click(); true")
        await p.evaluar("document.getElementById('nd-odf-nuevo').click(); true")
        await p.esperar("!document.getElementById('modal-nd-elem').hidden", 5)
        await p.evaluar("(() => { const f = document.getElementById('nd-elem-form'); f.elements.nombre.value = 'ODF B'; f.elements.puertos.value = '12'; f.requestSubmit(); return true; })()")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-odf').length === 2", 10)
        assert await p.errores() == []


def test_the_node_shows_its_odfs_as_tiles_its_olts_and_the_fibres_of_an_olt(zona):
    asyncio.run(_recorrido(zona))


async def _traer_del_visio(con_, admin, proy, ids):
    """«Traer del Visio» (administrators): the ODFs of the Visio near the node are brought in, after a question that says how many."""
    from visor_rutas.redes import red
    red.guardar(con_, admin, proyecto_id=proy["id"], cambios={"elementos": [{"id": "o", "tipo": "odf", "nombre": "ODF 24H RACK", "lat": 12.10001, "lon": -86.3000}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con_)) as p:
        await p.esperar("window.Nodo && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Nodo.abrir(%d); true" % ids["n"])
        await p.esperar("!document.getElementById('modal-nodo').hidden", 10)
        assert await p.evaluar("document.getElementById('nd-visio-nodo').hidden") is False and await p.evaluar("document.getElementById('nd-visio-todos').hidden") is False
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-odf').length") == 0
        await p.evaluar("document.getElementById('nd-visio-nodo').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 10)
        assert "Se traerían 1 ODF" in await p.evaluar("document.getElementById('conf-texto').textContent")
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-odf').length === 1", 10)
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-odf .nd-visio').textContent") == "Del Visio"            # 24 ports read from its name: not an estimate
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-baldosa').length") == 24
        # again: nothing new
        await p.evaluar("document.getElementById('nd-visio-nodo').click(); true")
        await p.esperar("document.getElementById('nd-estado').textContent.startsWith('Nada nuevo')", 10)
        assert await p.errores() == []


def test_the_odfs_of_the_visio_are_brought_into_the_node_by_an_administrator(zona):
    con, admin, proy, ids = zona
    asyncio.run(_traer_del_visio(con, admin, proy, ids))
