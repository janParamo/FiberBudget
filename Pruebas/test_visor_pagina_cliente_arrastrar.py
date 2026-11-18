"""Editor de mufa: el cliente de un hilo es un objeto (icono de casa unido al hilo) que se arrastra desde la paleta de clientes hasta el hilo y de un hilo a otro.
En la página real (Edge sin ventana) con una base desechable."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

# the page point (client coordinates) of the circle of fibre `h:<id>`
PUNTO = """(hilo) => { const st = window.EditorMufa._st, q = st.puertos.get('h:' + hilo), r = document.getElementById('mu-konva').getBoundingClientRect();
  const x = q.grupo.x() + q.dx, y = q.grupo.y() + q.dy; return {x: r.left + st.stage.x() + x * st.stage.scaleX(), y: r.top + st.stage.y() + y * st.stage.scaleY()}; }"""

SOLTAR = """(hilo) => { const p = (%s)(hilo), dt = new DataTransfer(), item = document.querySelector('#mu-paleta-lista .mu-pal-item');
  const ev = (tipo, el) => el.dispatchEvent(new DragEvent(tipo, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: p.x, clientY: p.y}));
  ev('dragstart', item); const konva = document.getElementById('mu-konva'); ev('dragover', konva); ev('drop', konva); ev('dragend', item); return true; }""" % PUNTO


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    con.execute("INSERT INTO redes.mufa_clientes (mufa_id, codigo_cliente, nombre, id_servicio, fuente) VALUES (%s, 'C24656', 'BANCO DE FOMENTO', 'ID374588', 'texto_diagrama')", (ids["a"],))
    hilos = {f["numero"]: f["id"] for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"]}
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 1", 15)
        assert await p.evaluar("document.getElementById('mu-clientes').disabled") is False
        await p.evaluar("document.getElementById('mu-clientes').click(); true")                                  # the palette opens with the client of the mufa
        assert await p.evaluar("document.getElementById('mu-paleta').hidden") is False
        assert await p.evaluar("document.querySelectorAll('#mu-paleta-lista .mu-pal-item').length") == 1
        # dropped on fibre 3: the client is drawn as an object joined to that fibre by a line
        await p.evaluar("(%s)(%d)" % (SOLTAR, hilos[3]))
        await p.esperar("window.EditorMufa._st.capa.find('.cliente-hilo').length === 1", 5)
        assert await p.evaluar("window.EditorMufa._st.capaLineas.find('.hilo-cliente').length") == 1
        assert await p.evaluar("window.EditorMufa._st.hiloClientes.get(%d).codigo_cliente" % hilos[3]) == "C24656"
        # dropped on fibre 4: the same client moves (it is not left on two fibres)
        await p.evaluar("(%s)(%d)" % (SOLTAR, hilos[4]))
        await p.esperar("window.EditorMufa._st.hiloClientes.has(%d)" % hilos[4], 5)
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1
        assert await p.evaluar("window.EditorMufa._st.hiloClientes.has(%d)" % hilos[3]) is False
        # dropped far from every fibre: nothing changes
        await p.evaluar("""(() => { const dt = new DataTransfer(), item = document.querySelector('#mu-paleta-lista .mu-pal-item'), konva = document.getElementById('mu-konva');
          const ev = (t, el) => el.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: 5, clientY: 5}));
          ev('dragstart', item); ev('dragover', konva); ev('drop', konva); ev('dragend', item); return true; })()""")
        assert await p.evaluar("window.EditorMufa._st.hiloClientes.has(%d)" % hilos[4]) is True
        # the object moved onto another fibre with the code of its own: a fibre already taken refuses a second client
        await p.evaluar("window.EditorMufa._st.hiloClientes.set(%d, {hilo_id: %d, codigo_cliente: 'C99999', nombre: 'Otro', id_servicio: '', elemento_id: null}); window.EditorMufa._st.capa.getLayer().draw(); true" % (hilos[5], hilos[5]))
        await p.evaluar("(%s)(%d)" % (SOLTAR, hilos[5]))
        assert await p.evaluar("window.EditorMufa._st.hiloClientes.get(%d).codigo_cliente" % hilos[5]) == "C99999"
        # Aplicar saves the client where it was left
        await p.evaluar("window.EditorMufa._st.hiloClientes.delete(%d); true" % hilos[5])
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.hiloClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = [dict(f) for f in con.execute("SELECT hilo_id, codigo_cliente FROM redes.hilo_servicios WHERE borrado_en IS NULL").fetchall()]
        assert fila == [{"hilo_id": hilos[4], "codigo_cliente": "C24656"}]
        assert await p.errores() == []


def test_a_client_is_dragged_from_the_palette_to_a_fibre_and_moved(mundo):
    asyncio.run(_recorrido(mundo))


# the same drop, on the output of a splitter
SOLTAR_SALIDA = """(clave) => { const st = window.EditorMufa._st, q = st.puertos.get(clave), r = document.getElementById('mu-konva').getBoundingClientRect();
  const p = {x: r.left + st.stage.x() + (q.grupo.x() + q.dx) * st.stage.scaleX(), y: r.top + st.stage.y() + (q.grupo.y() + q.dy) * st.stage.scaleY()};
  const dt = new DataTransfer(), item = document.querySelector('#mu-paleta-lista .mu-pal-item');
  const ev = (tipo, el) => el.dispatchEvent(new DragEvent(tipo, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: p.x, clientY: p.y}));
  ev('dragstart', item); const konva = document.getElementById('mu-konva'); ev('dragover', konva); ev('drop', konva); ev('dragend', item); return true; }"""


async def _en_splitter(mundo_):
    con, admin, proy, ids = mundo_
    con.execute("INSERT INTO redes.mufa_clientes (mufa_id, codigo_cliente, nombre, id_servicio, fuente) VALUES (%s, 'C24656', 'BANCO DE FOMENTO', 'ID374588', 'texto_diagrama')", (ids["a"],))
    sid = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"splitters": [{"id": "s1", "nombre": "SPL 1X8", "salidas": 8, "x": 470, "y": 40}]})["ids"]["s1"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.splitters.size === 1", 15)
        await p.evaluar("document.getElementById('mu-clientes').click(); true")
        await p.evaluar("(%s)('s:%d:salida:3')" % (SOLTAR_SALIDA, sid))
        await p.esperar("window.EditorMufa._st.capa.find('.cliente-hilo').length === 1", 5)
        assert await p.evaluar("window.EditorMufa._st.puertoClientes.get('%d:3').codigo_cliente" % sid) == "C24656"
        # moved to output 6 (not left on two)
        await p.evaluar("(%s)('s:%d:salida:6')" % (SOLTAR_SALIDA, sid))
        await p.esperar("window.EditorMufa._st.puertoClientes.has('%d:6')" % sid, 5)
        assert await p.evaluar("window.EditorMufa._st.puertoClientes.has('%d:3')" % sid) is False
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.puertoClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = [dict(f) for f in con.execute("SELECT p.numero, x.codigo_cliente FROM redes.puerto_servicios x JOIN redes.puertos p ON p.id = x.puerto_id WHERE x.borrado_en IS NULL").fetchall()]
        assert fila == [{"numero": 6, "codigo_cliente": "C24656"}]
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1                  # drawn from the saved data
        assert await p.errores() == []


def test_a_client_is_dragged_from_the_palette_to_a_splitter_output(mundo):
    asyncio.run(_en_splitter(mundo))


async def _con_dos_hilos(mundo_):
    """A client with 2 fibres: ONE card with two circles, each joined to its own place (a fibre of the mufa and an output of the splitter); the card is moved
    freely and stays where it was left, also after saving."""
    con, admin, proy, ids = mundo_
    sid = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"splitters": [{"id": "s1", "nombre": "SPL 1X8", "salidas": 8, "x": 470, "y": 40}]})["ids"]["s1"]
    hilos = {f["numero"]: f["id"] for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"]}
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={
        "clientes_mufa": [{"codigo_cliente": "C28995", "nombre": "Casa del Café", "hilos": 2}],
        "hilo_clientes": [{"hilo_id": hilos[2], "codigo_cliente": "C28995", "nombre": "Casa del Café", "hilo_cliente": 1}],
        "puerto_clientes": [{"splitter": sid, "numero": 6, "codigo_cliente": "C28995", "nombre": "Casa del Café", "hilo_cliente": 2}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.splitters.size === 1", 15)
        assert await p.evaluar("window.EditorMufa._st.capa.find('.cliente-hilo').length") == 1                # one card for the client
        assert await p.evaluar("window.EditorMufa._st.capa.find('.puerto-cliente').length") == 2              # with a circle for each of its two fibres
        assert await p.evaluar("window.EditorMufa._st.capaLineas.find('.hilo-cliente').length") == 2          # and a line from each to its place
        # the card dragged anywhere stays there (it does not go back)
        await p.evaluar("""(() => { const t = window.EditorMufa._st.capa.find('.cliente-hilo')[0]; t.fire('dragstart'); t.position({x: 777, y: 333}); t.fire('dragend'); return true; })()""")
        await p.esperar("window.EditorMufa._st.clientesMufa.size === 1", 5)
        await p.evaluar("window.EditorMufa._st.capa.getLayer().batchDraw(); true")
        await asyncio.sleep(0.2)
        assert await p.evaluar("(() => { const t = window.EditorMufa._st.capa.find('.cliente-hilo')[0]; return [t.x(), t.y()]; })()") == [777, 333]
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.clientesMufa.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = dict(con.execute("SELECT hilos, x, y FROM redes.mufa_clientes WHERE codigo_cliente = 'C28995' AND borrado_en IS NULL").fetchone())
        assert fila == {"hilos": 2, "x": 777, "y": 333}
        assert await p.evaluar("(() => { const t = window.EditorMufa._st.capa.find('.cliente-hilo')[0]; return [t.x(), t.y()]; })()") == [777, 333]
        assert await p.errores() == []


def test_a_client_with_two_fibres_is_one_card_with_two_lines_and_moves_freely(mundo):
    asyncio.run(_con_dos_hilos(mundo))


async def _en_cascada(mundo_):
    """Clients with one fibre: always a straight horizontal line away from the cable box; neighbours go in cascade (each longer than the one before); the icon only slides
    along its line to stretch it, and the length is saved."""
    con, admin, proy, ids = mundo_
    hilos = {f["numero"]: f["id"] for c in mufa.leer(con, admin, mufa_id=ids["a"])["cables"] for f in c["fibras"]}
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [
        {"hilo_id": hilos[1], "codigo_cliente": "C10001", "nombre": "Uno"}, {"hilo_id": hilos[2], "codigo_cliente": "C10002", "nombre": "Dos"},
        {"hilo_id": hilos[3], "codigo_cliente": "C10003", "nombre": "Tres"}, {"hilo_id": hilos[9], "codigo_cliente": "C10009", "nombre": "Nueve"}]})
    medir = """(() => { const st = window.EditorMufa._st; return [...st.tarjetas.values()].map((t) => { const p = st.puertos.get('h:' + t.lugares[0].lugar.hilo), ic = t.grupo.getAttr('icono');
      const cx = t.grupo.x() + ic.x, cy = t.grupo.y() + ic.y, px = p.grupo.x() + p.dx, py = p.grupo.y() + p.dy; return [Math.round((cx - px) * p.salida), Math.round(cy - py)]; }); })()"""
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.tarjetas.size === 4", 15)
        # outward (positive), on the same row as its fibre (straight), 44 then 78 then 112 for three neighbours, and 44 again for the one that is far away
        assert await p.evaluar(medir) == [[44, 0], [78, 0], [112, 0], [44, 0]]
        # stretching the second one: it only moves along its line (the height it is dragged to is ignored; towards the box it stops at 26)
        await p.evaluar("""(() => { const T = [...window.EditorMufa._st.tarjetas.values()][1], t = T.grupo, sal = window.EditorMufa._st.puertos.get('h:' + T.lugares[0].lugar.hilo).salida; t.fire('dragstart'); t.position({x: t.x() + 100 * sal, y: t.y() + 70}); t.fire('dragmove'); t.fire('dragend'); return true; })()""")
        assert (await p.evaluar(medir))[1] == [178, 0]
        await p.evaluar("""(() => { const T = [...window.EditorMufa._st.tarjetas.values()][3], t = T.grupo, sal = window.EditorMufa._st.puertos.get('h:' + T.lugares[0].lugar.hilo).salida; t.fire('dragstart'); t.position({x: t.x() - 500 * sal, y: t.y()}); t.fire('dragmove'); t.fire('dragend'); return true; })()""")
        assert (await p.evaluar(medir))[3] == [26, 0]                                          # never behind the cable box
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.clientesMufa.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = {f["codigo_cliente"]: f["largo"] for f in con.execute("SELECT codigo_cliente, largo FROM redes.mufa_clientes WHERE borrado_en IS NULL").fetchall()}
        assert fila == {"C10002": 178.0, "C10009": 26.0}
        assert await p.errores() == []


def test_single_clients_are_straight_in_cascade_and_can_be_stretched(mundo):
    asyncio.run(_en_cascada(mundo))
