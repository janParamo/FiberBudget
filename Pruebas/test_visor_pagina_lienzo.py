"""Esquema de zona (web/redes/lienzo.js) en la página real (Edge sin ventana, base desechable): la lista de la zona, arrastrar y soltar al lienzo (se guarda solo),
los cables entre lo colocado, «Conectar con cable», eliminar un cable y quitar una caja del esquema."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import proyectos, red, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def zona(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Jalapa", "codigo": "BASE-JAL", "zona": "Jalapa"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "n", "tipo": "nodo", "subtipo": "nodo", "nombre": "Nodo Jalapa", "lat": 12.1000, "lon": -86.3000},
                      {"id": "m1", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Uno", "lat": 12.1010, "lon": -86.3000},
                      {"id": "m2", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Dos", "lat": 12.1020, "lon": -86.3000}],
        "cables": [{"id": "k0", "nombre": "Troncal", "clase": "troncal", "hilos": 48, "origen_id": "n", "destino_id": "m1", "vertices": [_v(12.1000, -86.3000), _v(12.1010, -86.3000)]},
                   {"id": "k1", "nombre": "Distribución", "hilos": 24, "origen_id": "m1", "destino_id": "m2", "vertices": [_v(12.1010, -86.3000), _v(12.1020, -86.3000)]}]})
    return con, p, r["ids"]


def _consulta(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


SOLTAR = """(id, dx, dy) => { const el = document.getElementById('lz-lienzo'), r = el.getBoundingClientRect(), dt = new DataTransfer();
  dt.setData('text/plain', 'lz:' + id);
  el.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, clientX: r.left + dx, clientY: r.top + dy, bubbles: true, cancelable: true}));
  el.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, clientX: r.left + dx, clientY: r.top + dy, bubbles: true, cancelable: true})); return true; }"""


async def _recorrido(zona):
    con, p, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p_:
        await p_.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p_.evaluar("window.Esquema.abrir(%d); true" % p["id"])
        await p_.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        assert "Jalapa" in await p_.evaluar("document.getElementById('lz-titulo').textContent")
        assert await p_.evaluar("document.getElementById('lz-cuenta').textContent") == "0 de 3 en el esquema"
        assert await p_.evaluar("document.getElementById('lz-vacio').hidden") is False
        # search in the list
        await p_.evaluar("(() => { const i = document.getElementById('lz-buscar'); i.value = 'uno'; i.dispatchEvent(new Event('input')); return true; })()")
        assert await p_.evaluar("[...document.querySelectorAll('#lz-lista .lz-nombre')].map(x => x.textContent)") == ["MF Uno"]
        await p_.evaluar("(() => { const i = document.getElementById('lz-buscar'); i.value = ''; i.dispatchEvent(new Event('input')); return true; })()")
        # drag the node and one mufa to the canvas; the other one with a double click
        await p_.evaluar("(%s)(%d, 120, 120)" % (SOLTAR, ids["n"]))
        await p_.evaluar("(%s)(%d, 420, 120)" % (SOLTAR, ids["m1"]))
        await p_.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % ids["m2"])
        await p_.esperar("window.Esquema._st.cajas.size === 3 && window.Esquema._st.lineas.size === 2", 25)       # both cables of the zone are drawn
        await p_.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        filas = _consulta(con, "SELECT elemento_id, x, y FROM redes.lienzo_elementos ORDER BY elemento_id")
        assert {f["elemento_id"] for f in filas} == set(ids.values()) and len(filas) == 3
        y = {f["elemento_id"]: f["y"] for f in filas}
        assert y[ids["n"]] > y[ids["m1"]] > y[ids["m2"]] and len({f["x"] for f in filas}) == 1                   # by real coordinates: north up, same longitude
        assert await p_.evaluar("document.getElementById('lz-cuenta').textContent") == "3 de 3 en el esquema"
        assert await p_.evaluar("document.querySelectorAll('#lz-lista .lz-item').length") == 0                     # what is placed leaves the list
        # the canvas is white squared paper in the dark theme too; its grid follows the pan and the zoom; legend, zoom figure and the label under the pointer
        assert await p_.evaluar("document.body.classList.contains('tema-oscuro') && getComputedStyle(document.getElementById('lz-lienzo')).backgroundColor") == "rgb(255, 255, 255)"
        assert await p_.evaluar("getComputedStyle(document.getElementById('mu-lienzo')).backgroundColor") == "rgb(255, 255, 255)"
        leyenda = await p_.evaluar("document.getElementById('lz-leyenda').innerText")
        assert "Nodo" in leyenda and "Mufa (empalme)" in leyenda and "48 hilos" in leyenda and "24 hilos" in leyenda
        await p_.evaluar("(() => { const s = window.Esquema._st.stage; s.scale({x: 1, y: 1}); s.position({x: 37, y: 53}); return true; })()")
        await p_.esperar("document.getElementById('lz-zoom').textContent === '100 %' && document.getElementById('lz-lienzo').style.getPropertyValue('--lz-x') === '37px'", 5)
        assert await p_.evaluar("(() => { const c = document.getElementById('lz-lienzo').style; return [c.getPropertyValue('--lz-c'), c.getPropertyValue('--lz-x'), c.getPropertyValue('--lz-y')]; })()") == ["24px", "37px", "53px"]
        await p_.evaluar("document.getElementById('lz-alejar').click(); document.getElementById('lz-alejar').click(); document.getElementById('lz-alejar').click(); true")
        await p_.esperar("document.getElementById('lz-zoom').textContent === '51 %'", 5)
        await p_.evaluar("window.Esquema._st.cajas.get(%d).fire('mouseenter'); true" % ids["m1"])                 # too small to read: the name shows under the pointer
        assert "MF Uno" in await p_.evaluar("document.getElementById('lz-tip').hidden ? '' : document.getElementById('lz-tip').innerText")
        await p_.evaluar("window.Esquema._st.cajas.get(%d).fire('mouseleave'); true" % ids["m1"])
        assert await p_.evaluar("document.getElementById('lz-tip').hidden") is True
        await p_.evaluar("document.getElementById('lz-ajustar').click(); true")
        # moving a box saves its new place
        await p_.evaluar("(() => { const g = window.Esquema._st.cajas.get(%d); g.x(900); g.y(300); g.fire('dragend'); return true; })()" % ids["m2"])
        await p_.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        assert _consulta(con, "SELECT x, y FROM redes.lienzo_elementos WHERE elemento_id = %s", ids["m2"]) == [{"x": 900.0, "y": 300.0}]
        # connect two boxes with a new cable
        await p_.evaluar("document.getElementById('lz-conectar').click(); true")
        await p_.evaluar("window.Esquema._st.cajas.get(%d).fire('click'); true" % ids["n"])
        await p_.evaluar("window.Esquema._st.cajas.get(%d).fire('click'); true" % ids["m2"])
        await p_.esperar("!document.getElementById('modal-lz-cable').hidden", 5)
        assert await p_.evaluar("document.getElementById('lz-cable-form').elements.nombre.value") == "Nodo Jalapa – MF Dos"
        await p_.evaluar("(() => { const f = document.getElementById('lz-cable-form'); f.elements.hilos.value = '12'; f.requestSubmit(); return true; })()")
        await p_.esperar("window.Esquema._st.lineas.size === 3", 25)
        nuevo = _consulta(con, "SELECT nombre, hilos, origen_id, destino_id FROM redes.cables WHERE nombre = 'Nodo Jalapa – MF Dos' AND borrado_en IS NULL")
        assert nuevo == [{"nombre": "Nodo Jalapa – MF Dos", "hilos": 12, "origen_id": ids["n"], "destino_id": ids["m2"]}]
        assert "Enlace" not in await p_.evaluar("document.getElementById('lz-info').textContent") and "12 hilos" in await p_.evaluar("document.getElementById('lz-info').textContent")
        # delete that cable (asks first)
        assert await p_.evaluar("document.getElementById('lz-eliminar-cable').disabled") is False
        await p_.evaluar("document.getElementById('lz-eliminar-cable').click(); true")
        await p_.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p_.evaluar("document.getElementById('conf-si').click(); true")
        await p_.esperar("window.Esquema._st.lineas.size === 2", 25)
        assert _consulta(con, "SELECT count(*) AS n FROM redes.cables WHERE nombre = 'Nodo Jalapa – MF Dos' AND borrado_en IS NULL")[0]["n"] == 0
        assert await p_.evaluar("document.getElementById('lz-conectar').getAttribute('aria-pressed')") == "true"      # the mode stays on for the next cable; Esc / the button end it
        await p_.evaluar("document.getElementById('lz-conectar').click(); true")
        # take a box off the schema: it stays in the network and goes back to the list
        await p_.evaluar("window.Esquema._st.cajas.get(%d).fire('click'); document.getElementById('lz-quitar').click(); true" % ids["m2"])
        await p_.esperar("window.Esquema._st.cajas.size === 2 && document.querySelectorAll('#lz-lista .lz-item').length === 1", 10)
        await p_.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)
        assert _consulta(con, "SELECT count(*) AS n FROM redes.lienzo_elementos")[0]["n"] == 2
        assert _consulta(con, "SELECT count(*) AS n FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", ids["m2"])[0]["n"] == 1
        # closed and opened again: the schema is where it was left
        await p_.evaluar("window.Esquema.cerrar(); window.Esquema.abrir(%d); true" % p["id"])
        await p_.esperar("window.Esquema._st.cajas.size === 2", 10)
        assert await p_.errores() == []


def test_zone_schema_drag_and_drop_cables_and_persistence(zona):
    asyncio.run(_recorrido(zona))
