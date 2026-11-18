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
