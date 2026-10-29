"""Editor de mufa (web/redes/editor_mufa.js): un cliente identificado en un hilo de manera individual — clic derecho en el hilo → «Asignar un cliente a este hilo…»,
la etiqueta verde con su código, aplicar (se guarda), cambiarlo y quitarlo. En la página real (Edge sin ventana) con una base desechable."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _filas(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


MENU = """(hilo) => { const st = window.EditorMufa._st;
  const c = st.capa.find('.puerto').find((x) => x.getAttr('puerto') === 'h:' + hilo);
  c.fire('contextmenu', {evt: new MouseEvent('contextmenu', {clientX: 300, clientY: 300, bubbles: true, cancelable: true})}); return true; }"""


async def _elegir(p, atributo, hilo):
    await p.evaluar("(%s)(%d)" % (MENU, hilo))
    await p.evaluar("document.querySelector('#mu-menu li[%s]').click(); true" % atributo)


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    hilo1 = next(f for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"] if f["numero"] == 1)["id"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 1", 15)
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 0
        # right click on fibre 1 -> «Asignar un cliente a este hilo…»
        await _elegir(p, "data-mu-cliente", hilo1)
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        assert "hilo 1" in await p.evaluar("document.getElementById('mu-hc-titulo').textContent")
        # a wrong code is refused with the reason; a right one is accepted
        await p.evaluar("(() => { const f = document.getElementById('mu-hc-form'); f.elements.manual.checked = true; f.elements.manual.dispatchEvent(new Event('change')); f.elements.codigo.value = 'xyz'; f.requestSubmit(); return true; })()")
        assert "C seguida de números" in await p.evaluar("document.getElementById('mu-hc-error').textContent")
        await p.evaluar("(() => { const f = document.getElementById('mu-hc-form'); f.elements.manual.checked = true; f.elements.manual.dispatchEvent(new Event('change')); f.elements.codigo.value = 'c12345'; f.elements.nombre.value = 'Casa Pérez'; f.elements.servicio.value = 'ID418400'; f.requestSubmit(); return true; })()")
        await p.esperar("document.getElementById('modal-mu-hcliente').hidden && window.EditorMufa._st.hiloClientes.size === 1", 5)
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1                    # the green tag is drawn next to the fibre
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo')[0].find('Text')[0].text()") == "C12345"
        assert "1 cambio" in await p.evaluar("document.getElementById('mu-cambios').textContent")
        # Aplicar saves it
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.hiloClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = _filas(con, "SELECT codigo_cliente, nombre, id_servicio FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", hilo1)
        assert fila == [{"codigo_cliente": "C12345", "nombre": "Casa Pérez", "id_servicio": "ID418400"}]
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1                    # now it comes from the saved data
        # the known clients of the mufa are offered when changing it: the one just saved
        await _elegir(p, "data-mu-cliente", hilo1)
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        assert await p.evaluar("document.getElementById('mu-hc-form').elements.codigo.value") == "C12345"
        assert await p.evaluar("document.getElementById('mu-hc-form').elements.manual.checked") is True                 # it is not in the list of this mufa: it stays editable
        assert "no tiene clientes en su lista" in await p.evaluar("document.getElementById('mu-hc-form').elements.conocido.textContent")
        await p.evaluar("(() => { const f = document.getElementById('mu-hc-form'); f.elements.nombre.value = 'Casa Pérez (nueva)'; f.requestSubmit(); return true; })()")
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.hiloClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert _filas(con, "SELECT nombre FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", hilo1) == [{"nombre": "Casa Pérez (nueva)"}]
        # take it off: asks nothing, applies like the rest
        await _elegir(p, "data-mu-cliente-quitar", hilo1)
        await p.esperar("window.EditorMufa._st.capa.find('.cliente-hilo').length === 0", 5)
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.hiloClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert _filas(con, "SELECT count(*) AS n FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", hilo1)[0]["n"] == 0
        # undo brings back what was waiting (the tag is part of the undo history)
        await _elegir(p, "data-mu-cliente", hilo1)
        await p.evaluar("(() => { const f = document.getElementById('mu-hc-form'); f.elements.manual.checked = true; f.elements.manual.dispatchEvent(new Event('change')); f.elements.codigo.value = 'C777'; f.requestSubmit(); return true; })()")
        await p.esperar("window.EditorMufa._st.capa.find('.cliente-hilo').length === 1", 5)
        await p.evaluar("document.getElementById('mu-deshacer').click(); true")
        await p.esperar("window.EditorMufa._st.capa.find('.cliente-hilo').length === 0 && window.EditorMufa._st.hiloClientes.size === 0", 5)
        assert await p.errores() == []


def test_a_client_on_one_fibre_of_a_cable(mundo):
    asyncio.run(_recorrido(mundo))


async def _lista_de_la_mufa(mundo_):
    con, admin, proy, ids = mundo_
    # the diagram of Visio lists 2 clients in MF Uno and 1 in MF Dos (each mufa has its own)
    for mufa_id, codigo, nombre, servicio in ((ids["a"], "C24656", "BANCO DE FOMENTO", "ID374588"), (ids["a"], "C25898", "BANCO AVANZ", "ID405966"), (ids["b"], "C24764", "MUNKEL LENTES", "ID004749")):
        con.execute("INSERT INTO redes.mufa_clientes (mufa_id, codigo_cliente, nombre, id_servicio, fuente) VALUES (%s, %s, %s, %s, 'texto_diagrama')", (mufa_id, codigo, nombre, servicio))
    hilo5 = next(f for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"] if f["numero"] == 5)["id"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 1", 15)
        await _elegir(p, "data-mu-cliente", hilo5)
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        opciones = await p.evaluar("[...document.getElementById('mu-hc-form').elements.conocido.options].map(o => o.textContent)")
        assert len(opciones) == 3 and "C24656" in opciones[1] and "C25898" in opciones[2] and not any("C24764" in o for o in opciones)      # only this mufa's clients (not MF Dos's)
        # the boxes cannot be typed in unless «Escribir otro cliente» is ticked, and nothing is saved without choosing one
        assert await p.evaluar("document.getElementById('mu-hc-form').elements.codigo.readOnly") is True
        await p.evaluar("document.getElementById('mu-hc-form').requestSubmit(); true")
        assert "Elija un cliente de la lista" in await p.evaluar("document.getElementById('mu-hc-error').textContent")
        # choosing BANCO AVANZ fills the boxes and assigns it to fibre 5
        await p.evaluar("(() => { const f = document.getElementById('mu-hc-form'); f.elements.conocido.value = '1'; f.elements.conocido.dispatchEvent(new Event('change')); return true; })()")
        assert await p.evaluar("document.getElementById('mu-hc-form').elements.codigo.value") == "C25898"
        await p.evaluar("document.getElementById('mu-hc-form').requestSubmit(); true")
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.hiloClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = [dict(f) for f in con.execute("SELECT codigo_cliente, nombre, id_servicio FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", (hilo5,)).fetchall()]
        assert fila == [{"codigo_cliente": "C25898", "nombre": "BANCO AVANZ", "id_servicio": "ID405966"}]
        # the same client is marked as already placed when asking for another fibre
        hilo2 = next(f for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"] if f["numero"] == 2)["id"]
        await _elegir(p, "data-mu-cliente", hilo2)
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        assert "ya está en" in await p.evaluar("[...document.getElementById('mu-hc-form').elements.conocido.options].find(o => o.textContent.includes('C25898')).textContent")
        await p.evaluar("document.getElementById('mu-hc-cancelar').click(); true")
        # the other mufa only offers its own client
        await p.evaluar("window.EditorMufa.cerrar(false); window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.datos.mufa.id === %d" % ids["b"], 10)
        hilo_b = next(f for c in mufa.leer(con, admin, mufa_id=ids["b"])["cables"] if c["nombre"] == "Otro" for f in c["fibras"] if f["numero"] == 1)["id"]
        await _elegir(p, "data-mu-cliente", hilo_b)
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        opciones = await p.evaluar("[...document.getElementById('mu-hc-form').elements.conocido.options].map(o => o.textContent)")
        assert len(opciones) == 2 and "C24764" in opciones[1], opciones
        assert await p.errores() == []


def test_only_the_clients_of_the_mufa_are_offered_for_its_fibres(mundo):
    asyncio.run(_lista_de_la_mufa(mundo))
