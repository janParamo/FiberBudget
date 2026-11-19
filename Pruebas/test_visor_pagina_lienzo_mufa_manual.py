"""Esquema de zona (web/redes/lienzo.js): «Nueva mufa» (nombre, coordenada y su mufa del Visio, con la búsqueda del Visio de mentira), «Vincular Visio…» y las mufas hechas a mano
que se colocan solas según su coordenada. En la página real (Edge sin ventana) con una base desechable."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import lienzo

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

# three mufas of the Visio with the same name: the one next to the coordinate (12.1030, -86.3000) is the second
VISIO = """window.__stubs.buscar_mufa = (t) => ({ok: true, resultados: [
  {id: 901, nombre: 'MF RADIO SHACK', zona: 'Granada', diagramas: 1, lat: 12.20, lon: -86.30},
  {id: 902, nombre: 'MF RADIO SHACK', zona: 'Granada', diagramas: 2, lat: 12.10301, lon: -86.30001},
  {id: 903, nombre: 'MF RADIO SHACK', zona: 'Granada', diagramas: 1, lat: 12.30, lon: -86.30}]});
window.__stubs.buscar_mufa_cerca = (la, lo, r) => ({ok: true, resultados: []}); true"""


def _consulta(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _recorrido(zona_):
    con, proy, ids = zona_
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar(VISIO)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await p.evaluar("document.getElementById('lz-mufa-nueva').click(); true")
        await p.esperar("!document.getElementById('modal-lz-mufa').hidden", 5)
        # it is on top of the schema (not behind it)
        assert await p.evaluar("(() => { const r = document.getElementById('lz-mufa-form').getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + 20); return !!e && !!e.closest('#modal-lz-mufa'); })()") is True
        # without a name or a coordinate it is refused in the window
        await p.evaluar("document.getElementById('lz-mufa-form').requestSubmit(); true")
        assert "nombre" in await p.evaluar("document.getElementById('lz-mufa-error').textContent")
        await p.evaluar("""(() => { const f = document.getElementById('lz-mufa-form'); f.elements.nombre.value = 'MF Radio Shack nueva'; f.elements.coordenada.value = '12.1030, -86.3000';
          f.elements.buscar.value = 'radio shack'; f.elements.buscar.dispatchEvent(new Event('input')); return true; })()""")
        await p.esperar("document.querySelectorAll('#lz-mufa-lista tr').length === 3", 10)
        # the nearest first (the one at 2 m), the far ones in orange: the person chooses by distance and diagrams
        filas = await p.evaluar("[...document.querySelectorAll('#lz-mufa-lista tr')].map(tr => [tr.children[3].textContent, tr.children[4].textContent, tr.children[4].className])")
        assert filas[0][0] == "2" and filas[0][1].endswith(" m") and filas[0][2] == "" and filas[1][2] == "lejos" and filas[2][2] == "lejos"
        await p.evaluar("document.querySelector('#lz-mufa-lista input[type=radio]').click(); true")
        assert "902" in await p.evaluar("document.getElementById('lz-mufa-elegida').textContent") or "MF RADIO SHACK" in await p.evaluar("document.getElementById('lz-mufa-elegida').textContent")
        await p.evaluar("(() => { const f = document.getElementById('lz-mufa-form'); f.elements.nombres.value = 'visio'; f.requestSubmit(); return true; })()")
        await p.esperar("document.getElementById('modal-lz-mufa').hidden && document.querySelectorAll('#lz-lista .lz-item').length >= 0", 10)
        await p.esperar("window.Esquema._st.cajas.size === 1", 15)                                  # it was put in the schema by itself, by its coordinate
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        fila = _consulta(con, "SELECT nombre, fuente, ref_visio ->> 'nodo_id' AS nodo, ST_Y(ubicacion::geometry) AS lat FROM redes.elementos WHERE nombre = 'MF RADIO SHACK' AND fuente = 'usuario'")
        assert len(fila) == 1 and fila[0]["nodo"] == "902" and round(fila[0]["lat"], 4) == 12.1030          # named like the Visio, linked to the nearest one
        assert len(_consulta(con, "SELECT 1 FROM redes.lienzo_elementos")) == 1
        # the new mufa is the chosen one: «Vincular Visio…» is ready for it (it was disabled with nothing chosen)
        assert await p.evaluar("document.getElementById('lz-visio').disabled") is False
        assert await p.errores() == []


def test_a_mufa_is_created_by_hand_with_its_visio_mufa_and_goes_to_the_schema(zona):
    asyncio.run(_recorrido(zona))


async def _desde_el_mapa(zona_):
    """A mufa made by hand on the map (any other way: it is in the zone, fuente usuario) after the schema was saved: it is placed by itself where its coordinate says."""
    con, proy, ids = zona_
    from test_redes_lienzo import usuarios
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids["m1"])
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
    nueva = lienzo.crear_mufa(con, admin, proyecto_id=proy["id"], nombre="MF Del Mapa", lat=12.1030, lon=-86.3000)["elemento"]["id"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("window.Esquema._st.pos && window.Esquema._st.pos.has(%d)" % nueva, 20)
        await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        assert {f["elemento_id"] for f in _consulta(con, "SELECT elemento_id FROM redes.lienzo_elementos")} == {ids["m1"], nueva}
        assert await p.errores() == []


def test_a_mufa_made_by_hand_is_placed_in_the_schema_by_itself(zona):
    asyncio.run(_desde_el_mapa(zona))
