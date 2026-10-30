"""Sangría en la página: botón «Sangría» del editor de mufa (la fusión elegida se dibuja en rojo y se guarda) y la casilla «Sangría» de la ventana de conexión de hilos del esquema."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _sangrias(con):
    return [f["sangria"] for f in con.execute("SELECT sangria FROM redes.conexiones WHERE borrado_en IS NULL ORDER BY id").fetchall()]


def _fusion_11(con, admin, ids):
    vista = mufa.leer(con, admin, mufa_id=ids["b"])
    h = lambda cable: next(f for c in vista["cables"] if c["nombre"] == cable for f in c["fibras"] if f["numero"] == 11)["id"]
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": h("Distribución")}, "b": {"hilo": h("Otro")}}]})


async def _editor(mundo_):
    con, admin, proy, ids = mundo_
    _fusion_11(con, admin, ids)
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.conexiones.size === 1", 15)
        assert await p.evaluar("document.getElementById('mu-sangria').disabled") is True               # nothing chosen
        await p.evaluar("window.EditorMufa._st.capaLineas.children[0].fire('click', {evt: new MouseEvent('click')}); true")
        assert await p.evaluar("document.getElementById('mu-sangria').disabled") is False
        assert await p.evaluar("window.EditorMufa._st.capaLineas.children[0].stroke()") != "#e11d1d"
        await p.evaluar("document.getElementById('mu-sangria').click(); true")
        assert await p.evaluar("window.EditorMufa._st.capaLineas.children[0].stroke()") == "#e11d1d"      # drawn in red
        assert await p.evaluar("document.getElementById('mu-sangria').textContent") == "Quitar sangría"
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert _sangrias(con) == [True]
        assert await p.evaluar("window.EditorMufa._st.capaLineas.children[0].stroke()") == "#e11d1d"      # still red after reloading from the server
        await p.evaluar("window.EditorMufa._st.capaLineas.children[0].fire('click', {evt: new MouseEvent('click')}); document.getElementById('mu-sangria').click(); document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert _sangrias(con) == [False]
        assert await p.errores() == []


def test_the_mufa_editor_marks_a_fusion_as_a_tap_in_red(mundo):
    asyncio.run(_editor(mundo))


async def _esquema(mundo_):
    con, admin, proy, ids = mundo_
    _fusion_11(con, admin, ids)
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.FusionHilos && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.FusionHilos.abrir(%d); true" % ids["b"])
        await p.esperar("!document.getElementById('modal-fh').hidden && document.querySelectorAll('#fh-filas tr').length > 0", 10)
        assert await p.evaluar("document.querySelectorAll('#fh-filas input[data-fh-sangria]').length") == 1      # only the row that has a fusion offers it
        await p.evaluar("(() => { const c = document.querySelector('#fh-filas input[data-fh-sangria]'); c.checked = true; c.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        assert await p.evaluar("document.querySelectorAll('#fh-filas tr.fh-sangre').length") == 1
        assert await p.evaluar("document.getElementById('fh-guardar').disabled") is False
        await p.evaluar("document.getElementById('fh-guardar').click(); true")
        await p.esperar("document.getElementById('fh-estado').textContent.includes('Guardado')", 10)
        assert _sangrias(con) == [True]
        assert await p.errores() == []


def test_the_hilo_window_of_the_schema_marks_the_tap(mundo):
    asyncio.run(_esquema(mundo))


async def _puntas(mundo_):
    con, admin, proy, ids = mundo_
    _fusion_11(con, admin, ids)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "S1", "salidas": 4}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.conexiones.size === 1", 15)
        cabeceras = await p.evaluar("window.EditorMufa._st.capa.find('.cabecera').map(t => t.text()).sort()")
        assert len(cabeceras) == 2 and all("|" in t for t in cabeceras)                                 # the cable names as before: cable | origin | destination | fibres
        # the strip: where we are and who we are connected to, each one a click away
        franja = await p.evaluar("document.getElementById('mu-vecinas').innerText.replace(/\s+/g, ' ')")
        assert "MF Dos" in franja and "← MF Uno" in franja and "→ MF Otra" in franja
        # a second end on the fibre that is already connected (drag to the splitter input): accepted, both marked as a tap, in red
        st = "window.EditorMufa._st"
        h11 = con.execute("SELECT h.id FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE c.nombre = 'Distribución' AND h.numero = 11").fetchone()["id"]
        s_id = mufa.leer(con, admin, mufa_id=ids["b"])["splitters"][0]["id"]
        assert await p.evaluar("window.EditorMufa._conectar('h:%d', 's:%d:entrada:1')" % (h11, s_id)) is True
        await p.esperar("window.EditorMufa._st.conexiones.size === 2", 5)
        assert await p.evaluar("[...window.EditorMufa._st.conexiones.values()].every(x => x.sangria === true)") is True
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        assert _sangrias(con) == [True, True]
        assert await p.errores() == []


def test_a_fibre_takes_a_second_end_in_the_mufa_editor(mundo):
    asyncio.run(_puntas(mundo))


async def _lados(mundo_):
    con, admin, proy, ids = mundo_
    _fusion_11(con, admin, ids)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "S1", "salidas": 4}]})
    h11 = con.execute("SELECT h.id FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE c.nombre = 'Distribución' AND h.numero = 11").fetchone()["id"]
    s_id = mufa.leer(con, admin, mufa_id=ids["b"])["splitters"][0]["id"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Dos'); true" % ids["b"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.conexiones.size === 1", 15)
        assert await p.evaluar("window.EditorMufa._conectar('h:%d', 's:%d:entrada:1')" % (h11, s_id)) is True
        # the two ends of the tapped fibre leave its box from opposite sides: the first points start at the port, the second at the other edge of the box
        inicios = await p.evaluar("window.EditorMufa._st.capaLineas.children.map(l => l.points()[0])")
        puerto = await p.evaluar("(() => { const st = window.EditorMufa._st, q = st.puertos.get('h:%d'); return q.grupo.x() + q.dx; })()" % h11)
        assert len(inicios) == 2 and abs(inicios[0] - puerto) < 1 and abs(inicios[1] - puerto) > 20
        # the fibre shows a second circle (same number) on the other side of its cable box
        assert await p.evaluar("window.EditorMufa._st.puertos.has('h:%d:2')" % h11) is True
        assert await p.evaluar("window.EditorMufa._st.capa.find('.puerto').filter(c => c.getAttr('puerto') === 'h:%d:2').length" % h11) == 1
        assert await p.errores() == []


def test_the_ends_of_a_tapped_fibre_leave_from_opposite_sides(mundo):
    asyncio.run(_lados(mundo))
