"""Esquema de zona, fase 2 (web/redes/fusion_hilos.js): conectar hilo con hilo los cables de una mufa desde el esquema general — «Hilos en el destino» de un cable elegido,
«1 a 1», cambiar una fusión, lo que está conectado a un splitter sale bloqueado, y se guarda como las conexiones del editor de mufa. En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _filas(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    # MF Dos has the cables «Distribución» (24, arrives) and «Otro» (12, leaves); hilo 13 of «Distribución» is already on a splitter, and hilo 1 has a client
    vista = mufa.leer(con, admin, mufa_id=ids["b"])
    dist = next(c for c in vista["cables"] if c["nombre"] == "Distribución")
    h = lambda c, n: next(f for f in c["fibras"] if f["numero"] == n)["id"]
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "Splitter 1", "salidas": 8}],
                                                       "conexiones": [{"id": "x", "a": {"hilo": h(dist, 13)}, "b": {"splitter": "s", "lado": "entrada"}}],
                                                       "hilo_clientes": [{"hilo_id": h(dist, 1), "codigo_cliente": "C12345", "nombre": "Casa Pérez"}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        for k in ("a", "b", "c"):
            await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids[k])
            await p.esperar("window.Esquema._st.cajas.has(%d)" % ids[k], 5)
        await p.esperar("window.Esquema._st.lineas.size === 2", 10)
        # choose the cable «Distribución» and ask for the hilos at its end (MF Dos)
        await p.evaluar("window.Esquema._st.lineas.get(%d).g.fire('click'); true" % dist["id"])
        assert "MF Dos" in await p.evaluar("document.getElementById('lz-hilos-b').textContent")
        await p.evaluar("document.getElementById('lz-hilos-b').click(); true")
        await p.esperar("!document.getElementById('modal-fh').hidden && document.querySelectorAll('#fh-filas tr').length === 24", 10)
        assert await p.evaluar("document.getElementById('fh-titulo').textContent") == "Conexión de hilos en MF Dos"
        assert (await p.evaluar("document.getElementById('fh-cable-a').selectedOptions[0].textContent")).startswith("Distribución")      # the chosen cable is on side A
        assert (await p.evaluar("document.getElementById('fh-cable-b').selectedOptions[0].textContent")).startswith("Otro")
        filas = await p.evaluar("[...document.querySelectorAll('#fh-filas tr')].map(tr => tr.textContent.replace(/\\s+/g, ' ').trim())")
        assert "C12345 · Casa Pérez" in filas[0]                                                       # the client of hilo 1 is seen next to it
        assert "Splitter 1 · entrada" in filas[12] and await p.evaluar("document.querySelectorAll('#fh-filas tr')[12].querySelector('select')") is None     # on a splitter: locked
        # «1 a 1»: every free hilo with the one of the same number (12 of them: B has 12 hilos)
        await p.evaluar("document.getElementById('fh-uno-a-uno').click(); true")
        assert "12 de 24" in await p.evaluar("document.getElementById('fh-cuenta').textContent")
        assert await p.evaluar("document.getElementById('fh-guardar').disabled") is False
        # a hilo of B can be chosen once: hilo 3 of B is taken by row 3, so it is not offered in row 1
        assert await p.evaluar("[...document.querySelectorAll('#fh-filas tr')[0].querySelectorAll('option')].find(o => o.textContent.startsWith('H3 ')).disabled") is True
        # change row 1 to «sin conectar» and save: 11 connections
        await p.evaluar("(() => { const s = document.querySelectorAll('#fh-filas select')[0]; s.value = ''; s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        assert "11 de 24" in await p.evaluar("document.getElementById('fh-cuenta').textContent")
        await p.evaluar("document.getElementById('fh-guardar').click(); true")
        await p.esperar("document.getElementById('fh-estado').textContent.includes('Guardado')", 10)
        fusiones = _filas(con, "SELECT count(*) AS n FROM redes.conexiones c WHERE c.mufa_id = %s AND c.borrado_en IS NULL AND c.a_hilo_id IS NOT NULL AND c.b_hilo_id IS NOT NULL", ids["b"])
        assert fusiones[0]["n"] == 11
        # the splitter connection is untouched
        assert _filas(con, "SELECT count(*) AS n FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL AND (a_puerto_id IS NOT NULL OR b_puerto_id IS NOT NULL)", ids["b"])[0]["n"] == 1
        # the same cable on both sides is refused: a fusion joins hilos of different cables
        await p.evaluar("(() => { const b = document.getElementById('fh-cable-b'); b.value = document.getElementById('fh-cable-a').value; b.dispatchEvent(new Event('change')); return true; })()")
        assert "cables distintos" in await p.evaluar("document.getElementById('fh-estado').textContent")
        await p.evaluar("(() => { const b = document.getElementById('fh-cable-b'); b.selectedIndex = 1; b.dispatchEvent(new Event('change')); return true; })()")
        # «Quitar todas» and save: only the splitter connection is left
        await p.evaluar("document.getElementById('fh-quitar-todas').click(); document.getElementById('fh-guardar').click(); true")
        await p.esperar("document.getElementById('fh-estado').textContent.includes('11 quitada')", 10)
        assert _filas(con, "SELECT count(*) AS n FROM redes.conexiones c WHERE c.mufa_id = %s AND c.borrado_en IS NULL AND c.a_hilo_id IS NOT NULL AND c.b_hilo_id IS NOT NULL", ids["b"])[0]["n"] == 0
        # closing brings the schema up to date: the label of the cable shows how many hilos are joined
        await p.evaluar("document.getElementById('fh-cerrar').click(); true")
        await p.esperar("document.getElementById('modal-fh').hidden", 5)
        assert await p.errores() == []


def test_connect_hilo_with_hilo_from_the_general_schema(mundo):
    asyncio.run(_recorrido(mundo))


async def _desde_la_caja(mundo_):
    con, admin, proy, ids = mundo_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids["b"])
        await p.esperar("window.Esquema._st.cajas.has(%d)" % ids["b"], 5)
        await p.evaluar("window.Esquema._st.cajas.get(%d).fire('click'); true" % ids["b"])
        assert await p.evaluar("document.getElementById('lz-hilos').hidden") is False                  # a box chosen: «Conectar hilos…»
        await p.evaluar("document.getElementById('lz-hilos').click(); true")
        await p.esperar("!document.getElementById('modal-fh').hidden && document.querySelectorAll('#fh-filas tr').length > 0", 10)
        assert await p.evaluar("document.getElementById('fh-titulo').textContent") == "Conexión de hilos en MF Dos"
        await p.evaluar("document.getElementById('fh-cerrar').click(); true")
        # a mufa with one cable only cannot fuse: it says what to do
        await p.evaluar("window.FusionHilos.abrir(%d)" % ids["a"] + "; true")
        await p.esperar("document.getElementById('fh-aviso').textContent.includes('solo tiene un cable')", 10)
        assert await p.evaluar("document.getElementById('fh-cuerpo').hidden") is True
        assert await p.errores() == []


def test_the_mufa_box_offers_the_hilo_connections(mundo):
    asyncio.run(_desde_la_caja(mundo))
