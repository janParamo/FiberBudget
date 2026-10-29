"""Esquema de zona con las coordenadas reales (web/redes/lienzo.js): las cajas se colocan donde están las mufas en el mapa pero sobre un fondo blanco; una mufa
paralela en el mismo punto se corre al lado; «Acomodar por coordenadas», la escala y «Agregar nodo / ODF» (la fuente de la red)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import proyectos, red, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

M_LAT = 110574


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def zona(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Jalapa", "codigo": "BASE-JAL"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "m1", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Uno", "lat": 12.1010, "lon": -86.3000},
                      {"id": "par", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Uno PARALELA", "lat": 12.1010, "lon": -86.3000},        # the same point
                      {"id": "m2", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Dos", "lat": 12.1020, "lon": -86.3000}]})
    return con, p, r["ids"]


def _consulta(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _distribucion(p, modo):
    await p.evaluar("(() => { const s = document.getElementById('lz-distribucion'); s.value = %r; s.dispatchEvent(new Event('change')); return true; })()" % modo)
    await p.esperar("window.Esquema._st.distribucion === %r" % modo, 5)


async def _doble_clic(p, id_):
    await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true" % id_)


async def _guardado(p):
    await p.esperar("document.getElementById('lz-estado').textContent.includes('Guardado')", 10)


async def _pos(p, id_):
    return await p.evaluar("(() => { const g = window.Esquema._st.cajas.get(%d); return [g.x(), g.y()]; })()" % id_)


async def _recorrido(zona):
    con, proy, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        assert await p.evaluar("document.getElementById('lz-por-coord').checked") is True
        assert await p.evaluar("document.getElementById('lz-distribucion').value") == "compacta"                    # the default: only the direction
        await _distribucion(p, "real")
        assert await p.evaluar("document.getElementById('lz-escala').disabled") is False and await p.evaluar("document.getElementById('lz-escala').value") == "2"
        for k in ("m1", "par", "m2"):
            await _doble_clic(p, ids[k])
            await p.esperar("window.Esquema._st.cajas.has(%d)" % ids[k], 5)
        await _guardado(p)
        (x1, y1), (xp, yp), (x2, y2) = [await _pos(p, ids[k]) for k in ("m1", "par", "m2")]
        # by real coordinates: 0.001° of latitude = 110.574 m = 221.1 px at 2 px per metre, north up, same longitude -> same x
        assert abs((y1 - y2) - 0.001 * M_LAT * 2) < 1 and abs(x1 - x2) < 0.5
        # the parallel mufa is at the same point: it moves to the side, not on top of the other
        assert abs(xp - x1) >= 132 + 8 or abs(yp - y1) >= 44 + 8, ((x1, y1), (xp, yp))
        assert abs(xp - x1) < 400 and abs(yp - y1) < 200                                                 # and not far
        lz = _consulta(con, "SELECT origen_lat, origen_lon, escala FROM redes.lienzos")[0]
        assert abs(lz["origen_lat"] - (12.1010 * 2 + 12.1020) / 3) < 1e-6 and abs(lz["origen_lon"] + 86.3) < 1e-6 and lz["escala"] == 2
        # without «Colocar por coordenadas» the box stays where it is dropped
        await p.evaluar("document.getElementById('lz-por-coord').click(); true")
        await p.evaluar("window.Esquema._st.cajas.get(%d).fire('click'); document.getElementById('lz-quitar').click(); true" % ids["m2"])
        await p.esperar("!window.Esquema._st.cajas.has(%d)" % ids["m2"], 5)
        await p.evaluar("window.Esquema._st.stage.position({x: 0, y: 0}); window.Esquema._st.stage.scale({x: 1, y: 1}); true")
        await p.evaluar("""(() => { const el = document.getElementById('lz-lienzo'), r = el.getBoundingClientRect(), dt = new DataTransfer(); dt.setData('text/plain', 'lz:%d');
          el.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, clientX: r.left + 500, clientY: r.top + 300, bubbles: true, cancelable: true})); return true; })()""" % ids["m2"])
        await p.esperar("window.Esquema._st.cajas.has(%d)" % ids["m2"], 5)
        xl, yl = await _pos(p, ids["m2"])
        assert abs(xl - (500 - 66)) < 2 and abs(yl - (300 - 22)) < 2 and abs(yl - y2) > 100               # where it was dropped, not where the mufa is
        await _guardado(p)
        # «Acomodar por coordenadas» puts everything back by the real coordinates (asks first)
        await p.evaluar("document.getElementById('lz-geo').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("(() => { const g = window.Esquema._st.cajas.get(%d); return g && Math.abs(g.x() - %r) < 1; })()" % (ids["m2"], x2), 10)
        await _guardado(p)
        (xa, ya), (xb, yb) = await _pos(p, ids["m1"]), await _pos(p, ids["m2"])
        assert abs((ya - yb) - 0.001 * M_LAT * 2) < 1
        # the scale: the double, the boxes are laid out again (asks first) and the schema keeps it
        await p.evaluar("(() => { const s = document.getElementById('lz-escala'); s.value = '4'; s.dispatchEvent(new Event('change')); return true; })()")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("(() => { const a = window.Esquema._st.cajas.get(%d), b = window.Esquema._st.cajas.get(%d); return Math.abs((a.y() - b.y()) - %r) < 1; })()" % (ids["m1"], ids["m2"], 0.001 * M_LAT * 4), 10)
        await _guardado(p)
        assert _consulta(con, "SELECT escala FROM redes.lienzos")[0]["escala"] == 4
        assert await p.errores() == []


def test_boxes_follow_the_real_coordinates_on_a_white_background(zona):
    asyncio.run(_recorrido(zona))


async def _fuente(zona):
    con, proy, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        await _doble_clic(p, ids["m1"])
        await p.esperar("window.Esquema._st.cajas.size === 1", 5)
        await p.evaluar("document.getElementById('lz-fuente').click(); true")
        await p.esperar("!document.getElementById('modal-lz-fuente').hidden", 5)
        assert await p.evaluar("document.getElementById('lz-fuente-form').elements.coordenada.value") != ""        # suggests the middle of the zone
        # a name and a valid coordinate are required
        await p.evaluar("(() => { const f = document.getElementById('lz-fuente-form'); f.elements.nombre.value = ''; f.requestSubmit(); return true; })()")
        assert "nombre" in await p.evaluar("document.getElementById('lz-fuente-error').textContent")
        await p.evaluar("(() => { const f = document.getElementById('lz-fuente-form'); f.elements.nombre.value = 'ODF JALAPA'; f.elements.coordenada.value = 'no es'; f.requestSubmit(); return true; })()")
        assert await p.evaluar("document.getElementById('lz-fuente-error').textContent") != ""
        await p.evaluar("(() => { const f = document.getElementById('lz-fuente-form'); f.elements.tipo.value = 'odf:'; f.elements.coordenada.value = '12.0990, -86.3000'; f.requestSubmit(); return true; })()")
        await p.esperar("document.getElementById('modal-lz-fuente').hidden && window.Esquema._st.cajas.size === 2", 10)
        fila = _consulta(con, "SELECT tipo, nombre, ST_Y(ubicacion::geometry) AS lat FROM redes.elementos WHERE nombre = 'ODF JALAPA'")
        assert len(fila) == 1 and fila[0]["tipo"] == "odf" and abs(fila[0]["lat"] - 12.0990) < 1e-6
        nuevo = next(i for i in ((await p.evaluar("[...window.Esquema._st.elementos.values()].map(e => [e.id, e.nombre])"))) if i[1] == "ODF JALAPA")[0]
        # placed by its coordinates: south of the mufa (greater y), next to it (compact layout), and marked as the source of the network
        (_, ym), (_, yn) = await _pos(p, ids["m1"]), await _pos(p, nuevo)
        assert 0 < yn - ym <= 2 * (44 + 28) + 1
        assert await p.evaluar("window.Esquema._st.cajas.get(%d).find('Text').some(t => t.text().includes('Fuente'))" % nuevo) is True
        assert await p.evaluar("window.Esquema._st.cajas.get(%d).find('Text').some(t => t.text().includes('Fuente'))" % ids["m1"]) is False       # a mufa is not the source
        assert await p.errores() == []


def test_the_node_or_odf_that_feeds_the_network_is_added_from_the_schema(zona):
    asyncio.run(_fuente(zona))


async def _con_kmz(zona):
    con, proy, ids = zona
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 3", 15)
        assert "posición del KMZ" in await p.evaluar("document.querySelector('#lz-lista [data-lz-item=\"%d\"]').textContent" % ids["m2"])
        await _doble_clic(p, ids["m1"])
        await _doble_clic(p, ids["m2"])
        await p.esperar("window.Esquema._st.cajas.size === 2", 5)
        (x1, y1), (x2, y2) = await _pos(p, ids["m1"]), await _pos(p, ids["m2"])
        # in Visio MF Dos is north of MF Uno (same longitude); in the KMZ it is about 220 m EAST of it (and level): that is where the box goes, next to it
        assert 150 <= x2 - x1 <= 140 * 2.5 and abs(y2 - y1) < 30, ((x1, y1), (x2, y2))
        assert await p.errores() == []


def test_boxes_use_the_position_of_the_kmz_point_of_the_same_name(zona, monkeypatch):
    from visor_rutas.redes import lienzo
    from test_redes_lienzo_kmz import KmzFalso, punto
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: KmzFalso([punto(1, "MF Uno", 12.1010, -86.3000), punto(2, "MF Dos", 12.1011, -86.2980)]))
    asyncio.run(_con_kmz(zona))


async def _lejos(zona):
    con, proy, ids = zona
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    lejana = red.guardar(con, admin, proyecto_id=proy["id"], cambios={"elementos": [
        {"id": "lej", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Lejana", "lat": 12.2000, "lon": -86.2000}]})["ids"]["lej"]       # ~14 km away
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 4", 15)
        await _distribucion(p, "real")
        for id_ in (ids["m1"], ids["m2"], lejana):
            await _doble_clic(p, id_)
            await p.esperar("window.Esquema._st.cajas.has(%d)" % id_, 5)
        # a big scale with a spread-out zone: «Acomodar» must leave every box in sight (it used to zoom out only to 10 % and lose them)
        await p.evaluar("(() => { const s = document.getElementById('lz-escala'); s.value = '8'; s.dispatchEvent(new Event('change')); return true; })()")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("window.Esquema._st.datos.lienzo.escala === 8", 10)
        await p.evaluar("document.getElementById('lz-geo').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await asyncio.sleep(0.8)
        dentro = await p.evaluar("""(() => { const st = window.Esquema._st, k = st.stage.scaleX(); return [...st.cajas.values()].every((g) => {
          const x = g.x() * k + st.stage.x(), y = g.y() * k + st.stage.y(); return x >= -1 && y >= -1 && x + 132 * k <= st.stage.width() + 1 && y + 44 * k <= st.stage.height() + 1; }); })()""")
        assert dentro is True, await p.evaluar("[window.Esquema._st.stage.scaleX(), window.Esquema._st.stage.x(), window.Esquema._st.stage.y()]")
        assert await p.evaluar("window.Esquema._st.stage.scaleX()") < 0.1                                  # it needed more zoom out than before allowed
        # and the zoom buttons / Ctrl + wheel can go out that far too
        assert await p.errores() == []


def test_acomodar_with_a_big_scale_keeps_every_box_in_sight(zona):
    asyncio.run(_lejos(zona))


async def _compacta(zona):
    con, proy, ids = zona
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    extra = red.guardar(con, admin, proyecto_id=proy["id"], cambios={"elementos": [
        {"id": "este", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Este", "lat": 12.1010, "lon": -86.2000},          # ~11 km EAST of MF Uno
        {"id": "norte", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Norte", "lat": 12.2000, "lon": -86.3000},        # ~10 km NORTH
        {"id": "sur", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Sur", "lat": 12.0000, "lon": -86.3010}]})["ids"]      # ~12 km SOUTH
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Esquema && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Esquema.abrir(%d); true" % proy["id"])
        await p.esperar("document.querySelectorAll('#lz-lista .lz-item').length === 6", 15)
        await _distribucion(p, "compacta")
        assert await p.evaluar("document.getElementById('lz-escala').disabled") is True               # the scale is only for the true-to-scale layout
        antes = await p.evaluar("(() => { const e = [...window.Esquema._st.elementos.values()].find(x => x.nombre === 'MF Este'); return window.Esquema._posicionReal(e); })()")
        for k in ("m1", "par", "m2", "este", "norte", "sur"):
            await _doble_clic(p, ids[k] if k in ids else extra[k])
            await p.esperar("window.Esquema._st.cajas.has(%d)" % (ids[k] if k in ids else extra[k]), 5)
        pos = {k: await _pos(p, ids[k] if k in ids else extra[k]) for k in ("m1", "par", "m2", "este", "norte", "sur")}
        # the same slot whatever the order they were dragged in (it is worked out with the whole zone)
        assert [round(v) for v in antes.values()] == [round(v) for v in pos["este"]]
        # the direction of the map: east is to the right, north up, south down (y grows downward)
        assert pos["este"][0] > pos["m1"][0] and pos["norte"][1] < pos["m2"][1] < pos["m1"][1] < pos["sur"][1]
        # ...but close together: 11 km away is a box or two, not a screen of its own
        assert pos["este"][0] - pos["m1"][0] <= 2 * (132 + 24) + 1 and pos["m1"][1] - pos["norte"][1] <= 4 * (44 + 28) + 1 and pos["sur"][1] - pos["m1"][1] <= 2 * (44 + 28) + 1
        # no box on top of another (the parallel mufa is at the very same point as MF Uno)
        cajas = list(pos.values())
        assert all(abs(a[0] - b[0]) >= 132 or abs(a[1] - b[1]) >= 44 for i, a in enumerate(cajas) for b in cajas[i + 1:]), pos
        # all of it in one screen after «Ajustar» without zooming far out
        assert await p.evaluar("window.Esquema._st.stage.scaleX()") > 0.5
        # switching to «real» lays it out true to scale again (asks first), and back
        await p.evaluar("(() => { const s = document.getElementById('lz-distribucion'); s.value = 'real'; s.dispatchEvent(new Event('change')); return true; })()")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("window.Esquema._st.distribucion === 'real'", 5)
        await asyncio.sleep(0.6)
        (xe, _), (xm, _) = await _pos(p, extra["este"]), await _pos(p, ids["m1"])
        assert xe - xm > 5000                                                                          # 11 km at 2 px per metre
        assert await p.errores() == []


def test_compact_layout_keeps_the_direction_of_the_map_but_close_together(zona):
    asyncio.run(_compacta(zona))
