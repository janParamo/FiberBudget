"""Esquema de zona (web/redes/lienzo.js): «Mufas del KMZ» — lo que el KMZ tiene y la zona no (caso Jinotega: dos mufas con el mismo nombre que el KMZ ya separó), agregarlas o renombrar la
que ya estaba, y que entren a la lista para arrastrarlas. En la página real (Edge sin ventana) con una base desechable; el KMZ es de mentira."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo_kmz import KmzFalso, punto
from test_visor_pagina_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import lienzo

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _consulta(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _recorrido(zona_):
    con, proy, ids = zona_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await p.evaluar("document.getElementById('lz-kmz').click(); true")
        await p.esperar("!document.getElementById('modal-lz-kmz').hidden && document.querySelectorAll('#lz-kmz-lista tr').length === 3", 10)
        filas = await p.evaluar("[...document.querySelectorAll('#lz-kmz-lista tr')].map(tr => [tr.querySelector('b').textContent, tr.querySelector('select').value, tr.querySelector('select').textContent])")
        assert [f[0] for f in filas] == ["MF DOS 1", "MF DOS 2", "MF LEJANA"]
        assert filas[0][1] == "renombrar" and "MF Dos" in filas[0][2]                    # the one on top of MF Dos: probably it, renamed
        assert filas[1][1] == "agregar" and filas[2][1] == "agregar"
        # skip «MF LEJANA» and apply the other two
        await p.evaluar("(() => { const s = document.querySelectorAll('#lz-kmz-lista select')[2]; s.value = 'nada'; return true; })()")
        await p.evaluar("document.getElementById('lz-kmz-aplicar').click(); true")
        await p.esperar("document.getElementById('modal-lz-kmz').hidden && document.querySelectorAll('#lz-lista .lz-item').length === 4", 15)
        nombres = await p.evaluar("[...document.querySelectorAll('#lz-lista .lz-nombre')].map(x => x.textContent)")
        assert sorted(nombres) == ["MF DOS 1", "MF DOS 2", "MF Uno", "Nodo Jalapa"]        # MF Dos is now «MF DOS 1»; the new one is in the list to be dragged
        assert [f["nombre"] for f in _consulta(con, "SELECT nombre FROM redes.elementos WHERE id = %s", ids["m2"])] == ["MF DOS 1"]
        # opened again: only the one that was skipped is missing
        await p.evaluar("document.getElementById('lz-kmz').click(); true")
        await p.esperar("!document.getElementById('modal-lz-kmz').hidden && document.querySelectorAll('#lz-kmz-lista tr').length === 1", 10)
        assert await p.evaluar("document.querySelector('#lz-kmz-lista b').textContent") == "MF LEJANA"
        await p.evaluar("document.getElementById('lz-kmz-cerrar').click(); true")
        assert await p.errores() == []


def test_the_kmz_mufas_missing_in_the_zone_are_added_or_renamed(zona, monkeypatch):
    kmz = KmzFalso([punto(1, "MF UNO", 12.1010, -86.3000), punto(2, "MF DOS 1", 12.1020, -86.3000), punto(3, "MF DOS 2", 12.1032, -86.3000),
                    punto(4, "MF LEJANA", 12.1100, -86.3000, categoria="reserva")])
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: kmz)
    asyncio.run(_recorrido(zona))
