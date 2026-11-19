"""Editor de mufa: «Continuidad…» (mufa de corte): se escriben los hilos que van en continuidad y se conectan con el mismo número; el resto no. En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 2", 15)
        await p.evaluar("document.getElementById('mu-continuidad').click(); true")
        assert await p.evaluar("document.getElementById('modal-mu-cont').hidden") is False
        # and it is really on top of the mufa editor (not hidden behind it)
        assert await p.evaluar("(() => { const r = document.getElementById('mu-ct-form').getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + 20); return !!e && !!e.closest('#modal-mu-cont'); })()") is True
        assert await p.evaluar("document.getElementById('mu-ct-form').elements.a.options.length") == 2
        # a list that does not make sense is refused in the window
        await p.evaluar("(() => { const f = document.getElementById('mu-ct-form'); f.elements.hilos.value = 'a-b'; f.requestSubmit(); return true; })()")
        await p.esperar("document.getElementById('mu-ct-error').textContent.includes('no se entiende')", 10)
        # the first two cables, hilos 1-4 and 8 (the cable «Otro» has 12)
        await p.evaluar("""(() => { const f = document.getElementById('mu-ct-form'); const o = [...f.elements.a.options].map(x => x.textContent);
          const i = o.findIndex(x => x.startsWith('Distribución')), j = o.findIndex(x => x.startsWith('Otro'));
          f.elements.a.selectedIndex = i; f.elements.b.selectedIndex = j; f.elements.hilos.value = '1-4, 8'; f.requestSubmit(); return true; })()""")
        await p.esperar("document.getElementById('modal-mu-cont').hidden", 10)
        await p.esperar("window.EditorMufa._st.conexiones.size === 5", 10)
        assert await p.evaluar("document.getElementById('mu-estado') !== null") is True
        fila = [dict(f) for f in con.execute("SELECT count(*) AS n FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL", (ids["b"],)).fetchall()]
        assert fila == [{"n": 5}]
        # open again: it remembers what was written, and it can be taken off
        await p.evaluar("document.getElementById('mu-continuidad').click(); true")
        assert await p.evaluar("document.getElementById('mu-ct-form').elements.hilos.value") == "1-4, 8"
        assert await p.evaluar("document.getElementById('mu-ct-quitar').hidden") is False
        await p.evaluar("document.getElementById('mu-ct-quitar').click(); true")
        await p.esperar("window.EditorMufa._st.conexiones.size === 0", 10)
        assert await p.errores() == []


def test_the_written_fibres_are_put_in_continuity_from_the_editor(mundo):
    asyncio.run(_recorrido(mundo))


async def _colores_de_nota(mundo_):
    """A note of the mufa: the colour of its box and of its text are chosen in its window, drawn at once and saved."""
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos", 15)
        await p.evaluar("document.getElementById('mu-nota').click(); true")
        await p.esperar("!document.getElementById('modal-mu-nota').hidden", 5)
        await p.evaluar("""(() => { window.EditorMufa._st.quill.setText('SPL SECUNDARIO'); const f = document.getElementById('mu-no-fondo'), t = document.getElementById('mu-no-texto');
          f.value = '#1f2937'; f.dispatchEvent(new Event('input')); t.value = '#ffe600'; t.dispatchEvent(new Event('input'));
          document.getElementById('mu-no-aceptar').click(); return true; })()""")
        stil = await p.evaluar("(() => { const d = document.querySelector('#mu-notas .mu-nota'); return [d.style.background, d.style.color, d.classList.contains('con-color-texto')]; })()")
        assert "31, 41, 55" in stil[0] and "255, 230, 0" in stil[1] and stil[2] is True
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = [dict(f) for f in con.execute("SELECT color_fondo, color_texto FROM redes.notas WHERE borrado_en IS NULL").fetchall()]
        assert fila == [{"color_fondo": "#1f2937", "color_texto": "#ffe600"}]
        assert await p.errores() == []


def test_the_colours_of_a_note_are_chosen_and_saved(mundo):
    asyncio.run(_colores_de_nota(mundo))


async def _lineas_fuera_de_las_cajas(mundo_):
    """A connection line goes round the frame of a cable instead of passing behind it."""
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 2", 15)
        r = await p.evaluar("""(() => { const st = window.EditorMufa._st; st.marcos = [[400, 0, 700, 500]];
          const pts = window.EditorMufa._ruta({x: 100, y: 100, salida: 1}, {x: 1000, y: 300, salida: -1}, 0);       // the middle (x = 550) is inside the frame
          return {mx: pts[4], recto: pts[4] === pts[6]}; })()""")
        assert r["recto"] is True and not (394 < r["mx"] < 706)                   # the vertical segment is outside [400, 700]
        sin = await p.evaluar("""(() => { window.EditorMufa._st.marcos = []; const pts = window.EditorMufa._ruta({x: 100, y: 100, salida: 1}, {x: 1000, y: 300, salida: -1}, 0); return pts[4]; })()""")
        assert sin == 550                                   # with no frame in the way it turns halfway, as before
        assert await p.errores() == []


def test_the_connection_lines_go_round_the_frames_of_the_cables(mundo):
    asyncio.run(_lineas_fuera_de_las_cajas(mundo))


async def _lado_de_los_puntos(mundo_):
    """The button of a cable box passes its connection points to the other side of the box, and that is saved."""
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.cables.length === 2", 15)
        lado = "(() => { const st = window.EditorMufa._st; const c = st.cables[0]; const q = st.puertos.get('h:' + c.fibras[0].id); return [c.espejo === true, q.salida, Math.round(q.grupo.x() + q.dx - c.x)]; })()"
        antes = await p.evaluar(lado)
        assert await p.evaluar("window.EditorMufa._st.capa.find('.espejo').length") == 2          # one button on each cable box
        await p.evaluar("(() => { window.EditorMufa._st.capa.find('.espejo')[0].fire('click', {evt: new MouseEvent('click')}); return true; })()")
        despues = await p.evaluar(lado)
        assert despues[0] is True and despues[1] == -antes[1]                                      # the ports face the other way: the points are on the other side
        assert despues[2] != antes[2]
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert await p.evaluar(lado) == despues                                                     # still so after saving and reading again
        assert [f["espejo"] for f in con.execute("SELECT espejo FROM redes.mufa_cables WHERE mufa_id = %s", (ids["b"],)).fetchall()].count(True) == 1
        assert await p.errores() == []


def test_the_connection_points_of_a_cable_are_passed_to_the_other_side(mundo):
    asyncio.run(_lado_de_los_puntos(mundo))
