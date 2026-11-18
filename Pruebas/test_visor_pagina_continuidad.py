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
