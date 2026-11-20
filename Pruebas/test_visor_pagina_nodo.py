"""El nodo como lugar físico (web/redes/nodo.js): sus ODF como mosaicos de puertos libres / ocupados, sus OLT y los hilos de una OLT. En la página real (Edge sin ventana)."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import nodo, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _filas(con, sql, *a):
    return [dict(f) for f in con.execute(sql, a).fetchall()]


async def _recorrido(zona_):
    con, admin, proy, ids = zona_
    nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=24)
    nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT Granada", puertos=8)
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        # a mufa has no button for the node; the node has it
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["m1"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.datos.mufa.id === %d" % ids["m1"], 15)
        assert await p.evaluar("document.getElementById('mu-grupo-nodo').hidden") is True
        await p.evaluar("window.EditorMufa.abrir(%d, 'Nodo Jalapa'); true" % ids["n"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.datos.mufa.id === %d" % ids["n"], 15)
        assert await p.evaluar("document.getElementById('mu-grupo-nodo').hidden") is False
        await p.evaluar("document.getElementById('mu-nodo').click(); true")
        await p.esperar("!document.getElementById('modal-nodo').hidden && document.querySelectorAll('#nd-odfs .nd-baldosa').length === 24", 10)
        assert await p.evaluar("(() => { const r = document.querySelector('#nd-odfs').getBoundingClientRect(); const e = document.elementFromPoint(r.left + 40, r.top + 30); return !!e && !!e.closest('#modal-nodo'); })()") is True      # on top of the mufa editor
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-baldosa.libre').length") == 24 and await p.evaluar("document.querySelectorAll('#nd-olts .nd-olt').length") == 1
        # a free tile: connect it to a port of the OLT and to fibre 3 of the cable that goes to MF Uno
        await p.evaluar("document.querySelector('#nd-odfs .nd-baldosa[data-nd-baldosa$=\":5\"]').click(); true")
        await p.esperar("!document.getElementById('modal-nd-enlace').hidden", 5)
        await p.evaluar("""(() => { const f = document.getElementById('nd-enl-form'); f.elements.oltpuerto.value = '2'; f.elements.cable.value = f.elements.cable.options[1].value; f.elements.cable.dispatchEvent(new Event('change'));
          f.elements.hilo.value = [...f.elements.hilo.options].find(o => o.textContent.startsWith('Hilo 3')).value; f.requestSubmit(); return true; })()""")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-baldosa.ocupada').length === 1", 10)
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-baldosa.ocupada').title") == "Puerto 5 · ocupado: OLT Granada (hilo 2) · Troncal hilo 3 → MF Uno"
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-odf header small').textContent") == "24 puertos (12 × 2) · 1 ocupado · 23 libres"
        e = _filas(con, "SELECT olt_puerto, odf_puerto FROM redes.nodo_enlaces WHERE borrado_en IS NULL")
        assert e == [{"olt_puerto": 2, "odf_puerto": 5}]
        # inside the OLT: its fibres, the second one is used and says where it goes
        await p.evaluar("document.querySelector('[data-nd-abrir-olt]').click(); true")
        await p.esperar("document.querySelectorAll('#nd-olt-filas tr').length === 8", 5)
        fila = await p.evaluar("[...document.querySelectorAll('#nd-olt-filas tr')[1].children].map(td => td.textContent.trim())")
        assert fila[:4] == ["2", "ODF A · puerto 5", "Troncal · hilo 3", "MF Uno"]
        assert await p.evaluar("document.querySelectorAll('#nd-olt-filas tr.libre').length") == 7
        # back to the node; a new ODF and a new OLT from the buttons
        await p.evaluar("document.getElementById('nd-volver').click(); true")
        await p.evaluar("document.getElementById('nd-odf-nuevo').click(); true")
        await p.esperar("!document.getElementById('modal-nd-elem').hidden", 5)
        await p.evaluar("(() => { const f = document.getElementById('nd-elem-form'); f.elements.nombre.value = 'ODF B'; f.elements.puertos.value = '12'; f.requestSubmit(); return true; })()")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-odf').length === 2", 10)
        assert await p.errores() == []


def test_the_node_shows_its_odfs_as_tiles_its_olts_and_the_fibres_of_an_olt(zona):
    asyncio.run(_recorrido(zona))


async def _traer_del_visio(con_, admin, proy, ids):
    """«Traer del Visio» (administrators): the ODFs of the Visio near the node are brought in, after a question that says how many."""
    from visor_rutas.redes import red
    red.guardar(con_, admin, proyecto_id=proy["id"], cambios={"elementos": [{"id": "o", "tipo": "odf", "nombre": "ODF 24H RACK", "lat": 12.10001, "lon": -86.3000}]})
    async with pagina_edge(1366, 768, api=crear_api_prueba(con_)) as p:
        await p.esperar("window.Nodo && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Nodo.abrir(%d); true" % ids["n"])
        await p.esperar("!document.getElementById('modal-nodo').hidden", 10)
        assert await p.evaluar("document.getElementById('nd-visio-nodo').hidden") is False and await p.evaluar("document.getElementById('nd-visio-todos').hidden") is False
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-odf').length") == 0
        await p.evaluar("document.getElementById('nd-visio-nodo').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 10)
        assert "Se traerían 1 ODF" in await p.evaluar("document.getElementById('conf-texto').textContent")
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-odf').length === 1", 10)
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-odf .nd-visio').textContent") == "Del Visio"            # 24 ports read from its name: not an estimate
        assert await p.evaluar("document.querySelectorAll('#nd-odfs .nd-baldosa').length") == 24
        # again: nothing new
        await p.evaluar("document.getElementById('nd-visio-nodo').click(); true")
        await p.esperar("document.getElementById('nd-estado').textContent.startsWith('Nada nuevo')", 10)
        assert await p.errores() == []


def test_the_odfs_of_the_visio_are_brought_into_the_node_by_an_administrator(zona):
    con, admin, proy, ids = zona
    asyncio.run(_traer_del_visio(con, admin, proy, ids))


PNG_PEQUENO = ("iVBORw0KGgoAAAANSUhEUgAAAB4AAAAUCAIAAAAVyRqTAAAALUlEQVR4nGM8YWPDQBvARCNzGUaNxgCjYY0GRgMEDYwGCBoYDRA0MBogDKgAAHbfAWgX5lU2AAAAAElFTkSuQmCC")


async def _disposicion_y_foto(con_, admin, proy, ids):
    nodo.guardar_odf(con_, admin, nodo_id=ids["n"], nombre="ODF A", puertos=32)
    async with pagina_edge(1366, 768, api=crear_api_prueba(con_)) as p:
        await p.esperar("window.Nodo && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.Nodo.abrir(%d); true" % ids["n"])
        await p.esperar("document.querySelectorAll('#nd-odfs .nd-baldosa').length === 32", 10)
        assert "(12 × 3)" in await p.evaluar("document.querySelector('#nd-odfs .nd-odf header small').textContent")           # the automatic layout
        await p.evaluar("document.querySelector('#nd-odfs [data-nd-elem]').click(); true")
        await p.esperar("!document.getElementById('modal-nd-elem').hidden && !document.getElementById('nd-elem-odf').hidden", 5)
        # columns and rows follow each other (4 columns → 8 rows) and a layout that does not cover the ports is said in the window
        await p.evaluar("(() => { const f = document.getElementById('nd-elem-form'); f.elements.columnas.value = '4'; f.elements.columnas.dispatchEvent(new Event('input')); return true; })()")
        assert await p.evaluar("document.getElementById('nd-elem-form').elements.filas.value") == "8" and "✓ 4 × 8 = 32" in await p.evaluar("document.getElementById('nd-elem-disp').textContent")
        await p.evaluar("(() => { const f = document.getElementById('nd-elem-form'); f.elements.columnas.value = '3'; f.elements.columnas.dispatchEvent(new Event('input')); f.elements.filas.value = '3'; f.elements.filas.dispatchEvent(new Event('input')); return true; })()")
        # (typing the rows moves the columns to keep covering the ports: 32 / 3 → 11 columns)
        await p.evaluar("(() => { const f = document.getElementById('nd-elem-form'); f.elements.columnas.value = '4'; f.elements.columnas.dispatchEvent(new Event('input')); return true; })()")
        # a photo from the computer: it is made small and shown to the right of the ports
        await p.evaluar("""(() => { const bin = atob('%s'), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
          const dt = new DataTransfer(); dt.items.add(new File([a], 'odf.png', {type: 'image/png'})); const inp = document.getElementById('nd-elem-foto'); inp.files = dt.files; inp.dispatchEvent(new Event('change')); return true; })()""" % PNG_PEQUENO)
        await p.esperar("!document.getElementById('nd-elem-foto-vista').hidden", 10)
        await p.evaluar("document.getElementById('nd-elem-form').requestSubmit(); true")
        await p.esperar("document.getElementById('modal-nd-elem').hidden", 10)
        await p.esperar("document.querySelector('#nd-odfs img[data-nd-foto]') && document.querySelector('#nd-odfs img[data-nd-foto]').src.startsWith('data:image')", 10)
        assert await p.evaluar("document.querySelector('#nd-odfs .nd-mosaico').style.getPropertyValue('--nd-cols')") == "4"
        assert "(4 × 8)" in await p.evaluar("document.querySelector('#nd-odfs .nd-odf header small').textContent")
        fila = _filas(con_, "SELECT columnas, filas, imagen_tipo, imagen_version, imagen IS NOT NULL AS hay FROM redes.nodo_odfs WHERE borrado_en IS NULL")
        assert fila == [{"columnas": 4, "filas": 8, "imagen_tipo": "image/jpeg", "imagen_version": 1, "hay": True}]
        # the photo is seen big, and taken off
        await p.evaluar("document.querySelector('#nd-odfs img[data-nd-foto]').click(); true")
        assert await p.evaluar("document.getElementById('nd-lightbox').hidden") is False
        await p.evaluar("document.getElementById('nd-lightbox').click(); true")
        await p.evaluar("document.querySelector('#nd-odfs [data-nd-elem]').click(); true")
        await p.esperar("!document.getElementById('nd-elem-foto-vista').hidden", 10)
        await p.evaluar("document.getElementById('nd-elem-foto-quitar').click(); document.getElementById('nd-elem-form').requestSubmit(); true")
        await p.esperar("document.querySelectorAll('#nd-odfs img[data-nd-foto]').length === 0", 10)
        # the automatic layout again
        await p.evaluar("document.querySelector('#nd-odfs [data-nd-elem]').click(); true")
        await p.evaluar("document.getElementById('nd-elem-auto').click(); document.getElementById('nd-elem-form').requestSubmit(); true")
        await p.esperar("document.querySelector('#nd-odfs .nd-mosaico').style.getPropertyValue('--nd-cols') === '12'", 10)
        assert await p.errores() == []


def test_the_layout_of_an_odf_is_edited_and_the_photo_of_the_real_odf_is_put_and_taken_off(zona):
    con, admin, proy, ids = zona
    asyncio.run(_disposicion_y_foto(con, admin, proy, ids))


async def _lienzo_del_nodo(con_, admin, ids):
    """Entering the node: its ODF and OLT are drawn (the OLT with its free fibres) and the nearest mufa, dashed, with the button that connects it; once connected the links are lines."""
    odf = nodo.guardar_odf(con_, admin, nodo_id=ids["n"], nombre="ODF GRANADA", puertos=24)["odfs"][0]
    olt = nodo.guardar_olt(con_, admin, nodo_id=ids["n"], nombre="OLT GRANADA", puertos=8)["olts"][0]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con_)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'NODO GRANADA'); true" % ids["n"])
        await p.esperar("window.EditorMufa._st.nodo && window.EditorMufa._st.capa.find('.nodo-odf').length === 1", 15)
        st = "window.EditorMufa._st"
        assert await p.evaluar(st + ".capa.find('.nodo-olt').length") == 1 and await p.evaluar(st + ".capa.find('.nodo-mufa').length") == 1
        # the OLT with its 8 fibres all free (light-blue ring), the ODF with its 24 tiles, and no line yet
        assert await p.evaluar(st + ".capa.find('.nodo-olt')[0].find('Circle').filter((c) => c.stroke() === '#29b6f6').length") == 8
        assert await p.evaluar(st + ".capa.find('.nodo-odf')[0].find('Rect').length") == 25                          # the frame and 24 tiles
        assert await p.evaluar(st + ".capaLineas.find('.enlace-nodo').length") == 0
        # connect the node to the nearest mufa with a 24-fibre cable
        await p.evaluar("(() => { const b = " + st + ".capa.find('.nodo-mufa')[0].getChildren((n) => n.getClassName() === 'Group')[0]; b.fire('click', {evt: new MouseEvent('click')}); return true; })()")
        await p.esperar("!document.getElementById('modal-mu-nodo-cable').hidden", 5)
        await p.evaluar("document.getElementById('mu-nc-form').requestSubmit(); true")
        await p.esperar(st + ".cables.length === 1 && " + st + ".capa.find('.nodo-mufa').length === 0", 15)
        cable = await p.evaluar(st + ".cables[0].nombre")
        assert cable.startswith("NODO GRANADA") and await p.evaluar(st + ".cables[0].fibras.length") == 24
        # a link made (OLT fibre 3 → ODF port 5 → fibre 7 of the cable): it is a line from the OLT to the ODF and from the ODF to the fibre
        h = await p.evaluar(st + ".cables[0].fibras.find((f) => f.numero === 7).id")
        nodo.guardar_enlace(con_, admin, nodo_id=ids["n"], olt_id=olt["id"], olt_puerto=3, odf_id=odf["id"], odf_puerto=5, hilo_id=h)
        await p.evaluar("window.Nodo.abrir(%d); true" % ids["n"])                      # (the node window reads it again and tells the drawing)
        await p.esperar("window.Nodo && !document.getElementById('modal-nodo').hidden", 10)
        await p.esperar(st + ".capaLineas.find('.enlace-nodo').length === 2", 10)
        assert await p.evaluar(st + ".capa.find('.nodo-olt')[0].find('Circle').filter((c) => c.stroke() === '#29b6f6').length") == 7        # one fibre less is free
        assert await p.errores() == []


def test_the_node_draws_its_odf_and_olt_and_the_nearest_mufa_and_connects_to_it(con_redes):
    from visor_rutas.redes import proyectos, red
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Granada", "codigo": "BASE-GRA"})["proyecto"]
    ids = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [
        {"id": "n", "tipo": "nodo", "subtipo": "nodo", "nombre": "NODO GRANADA", "lat": 11.9300, "lon": -85.9560},
        {"id": "m1", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF CERCANA", "lat": 11.9310, "lon": -85.9560}]})["ids"]
    asyncio.run(_lienzo_del_nodo(con, admin, ids))
