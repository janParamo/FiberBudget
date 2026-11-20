"""Editor de mufa: acometidas (cables nuevos que salen de la mufa, dibujados como tarjeta), clientes de baja en celeste y los colores de los hilos
(splitter secundario en morado discontinuo, primario en dorado, hilo libre en punta en celeste). En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import _hilo, mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MENU_HILO = """(hilo) => { const st = window.EditorMufa._st;
  const c = st.capa.find('.puerto').find((x) => x.getAttr('puerto') === 'h:' + hilo);
  c.fire('contextmenu', {evt: new MouseEvent('contextmenu', {clientX: 300, clientY: 300, bubbles: true, cancelable: true})}); return true; }"""


async def _acometida(mundo_):
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 2", 15)
        await p.evaluar("document.getElementById('mu-acometida').click(); true")
        await p.esperar("!document.getElementById('modal-mu-aco-nueva').hidden", 10)
        assert await p.evaluar("(() => { const r = document.getElementById('mu-an-form').getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + 20); return !!e && !!e.closest('#modal-mu-aco-nueva'); })()") is True
        assert await p.evaluar("[...document.getElementById('mu-an-form').elements.hilos.options].map(o => o.value)") == ["2", "4", "6", "8", "12", "24", "48", "72", "96"]
        await p.evaluar("(() => { const f = document.getElementById('mu-an-form'); f.elements.nombre.value = 'Acometida Café'; f.elements.hilos.value = '12'; f.requestSubmit(); return true; })()")
        await p.esperar("window.EditorMufa._st.cables.length === 3", 15)
        c = await p.evaluar("(() => { const c = window.EditorMufa._st.cables.find((x) => x.clase === 'acometida'); return [c.nombre, c.hilos, c.fibras.length]; })()")
        assert c == ["Acometida Café", 12, 12]
        # drawn as a small card (narrow, green) with a button to open it, and without the boxes of destination of the fibres
        marco = await p.evaluar("(() => { const g = window.EditorMufa._st.capa.find('.cable').find((x) => x.getAttr('obj').id === window.EditorMufa._st.cables.find((c) => c.clase === 'acometida').id); const m = g.findOne('.marco'); return [m.width(), m.stroke()]; })()")
        assert marco == [150, "#2e9d4a"]
        assert await p.evaluar("window.EditorMufa._st.capa.find('.destino-hilo').length") == 0                    # the other cables have none either (nothing is connected)
        # a client on one of its fibres, as on any other fibre
        hilo = await p.evaluar("window.EditorMufa._st.cables.find((x) => x.clase === 'acometida').fibras[0].id")
        await p.evaluar("(%s)(%d)" % (MENU_HILO, hilo))
        await p.evaluar("document.querySelector('#mu-menu li[data-mu-cliente]').click(); true")
        await p.evaluar("""(() => { const f = document.getElementById('mu-hc-form'); f.elements.manual.checked = true; f.elements.manual.dispatchEvent(new Event('change'));
          f.elements.codigo.value = 'C28995'; f.elements.nombre.value = 'Casa del Café'; f.requestSubmit(); return true; })()""")
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        # open it: rename, connect to a mufa
        await p.evaluar("(() => { const st = window.EditorMufa._st; st.capa.find('.cable').find((x) => x.getAttr('obj').id === st.cables.find((c) => c.clase === 'acometida').id).fire('dblclick', {evt: new MouseEvent('dblclick'), target: st.capa}); return true; })()")
        await p.esperar("!document.getElementById('modal-mu-aco').hidden", 10)
        await p.esperar("document.getElementById('mu-ac-form').elements.destino.options.length >= 3", 10)
        await p.evaluar("(() => { const f = document.getElementById('mu-ac-form'); f.elements.nombre.value = 'Acometida Final'; f.elements.destino.value = '%d'; f.requestSubmit(); return true; })()" % ids["c"])
        await p.esperar("document.getElementById('modal-mu-aco').hidden", 10)
        await p.esperar("window.EditorMufa._st.cables.some((x) => x.nombre === 'Acometida Final' && x.otro.tipo === 'mufa')", 10)
        assert await p.errores() == []


def test_an_acometida_is_created_drawn_as_a_card_takes_clients_and_connects_to_a_mufa(mundo):
    asyncio.run(_acometida(mundo))


async def _colores(mundo_):
    con, admin, proy, ids = mundo_
    d1, d2, d3 = (_hilo(con, admin, ids["a"], "Distribución", n) for n in (1, 2, 3))
    sid = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"splitters": [{"id": "p", "nombre": "SPL 1/8 PRIMARIO", "salidas": 8}, {"id": "s", "nombre": "SPL 1/8 SECUNDARIO", "salidas": 8}]})["ids"]
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"conexiones": [
        {"id": "n1", "a": {"hilo": d1["id"]}, "b": {"splitter": sid["p"], "lado": "entrada"}},
        {"id": "n2", "a": {"hilo": d2["id"]}, "b": {"splitter": sid["s"], "lado": "entrada"}}],
        "clientes_mufa": [{"codigo_cliente": "C28995", "nombre": "Casa del Café", "id_servicio": "", "hilos": 1, "baja": True}],
        "hilo_clientes": [{"hilo_id": d3["id"], "codigo_cliente": "C28995", "nombre": "Casa del Café"}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.conexiones.size === 2", 15)
        lineas = await p.evaluar("window.EditorMufa._st.capaLineas.find('Line').filter((l) => l.name() !== 'hilo-cliente').map((l) => [l.stroke(), (l.dash() || []).length > 0])")
        assert ["#d4a017", False] in lineas and ["#8e24aa", True] in lineas             # primary: gold, continuous; secondary: purple, dashed
        # a free fibre at the tip has a light-blue ring; one with a client or a connection does not
        anillo = await p.evaluar("""(() => { const st = window.EditorMufa._st, c = st.cables[0]; const col = (n) => st.capa.find('.puerto').find((x) => x.getAttr('puerto') === 'h:' + c.fibras.find((f) => f.numero === n).id).stroke();
          return [col(1), col(2), col(3), col(20)]; })()""")
        assert anillo[:3] == ["#333", "#333", "#333"] and anillo[3] == "#29b6f6"
        # the client of the fibre 3 was taken off: light-blue house; the button brings it back
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo')[0].findOne('Circle').stroke()") == "#29b6f6"
        await p.evaluar("window.EditorMufa._seleccionar({tipo: 'hilo', id: %d}); true" % d3["id"])
        assert await p.evaluar("document.getElementById('mu-baja').disabled") is False
        assert await p.evaluar("document.getElementById('mu-baja').textContent") == "Reactivar"
        await p.evaluar("document.getElementById('mu-baja').click(); true")
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo')[0].findOne('Circle').stroke()") == "#2e9d4a"
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert [f["baja"] for f in con.execute("SELECT baja FROM redes.mufa_clientes WHERE codigo_cliente = 'C28995'").fetchall()] == [False]
        assert await p.errores() == []


def test_colours_of_the_fibres_and_a_client_taken_off(mundo):
    asyncio.run(_colores(mundo))
