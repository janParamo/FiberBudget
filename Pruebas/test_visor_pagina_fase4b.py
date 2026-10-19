"""Visor v2, fase 4 (segunda parte), en la página real (Edge sin ventana, base desechable, un KMZ de mentira con dos mufas):
renombrar y quitar un elemento del KMZ (se guarda en la base y se ve al abrir otra vez), deshacer desde «Cambios al KMZ», y
«Entrar a la mufa» de una mufa que la migración no tiene (se ofrece crear una vacía)."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

CARPETAS = {
    "raiz": {"id": "raiz", "nombre": "Red", "ruta": "Red", "padre": None, "hijos": ["m1"], "directos": 0, "total": 2, "geometria": "punto", "bbox": None, "estilo": None,
             "troncal": False, "postes": False, "visible": True, "etiquetas": False, "visibilidad_kml": None},
    "m1": {"id": "m1", "nombre": "MUFA", "ruta": "Red/MUFA", "padre": "raiz", "hijos": [], "directos": 2, "total": 2, "geometria": "punto", "bbox": [-86.26, 12.13, -86.25, 12.14],
           "estilo": {"tipo": "punto", "color": "#ff8800", "radio": 7}, "troncal": False, "postes": False, "visible": True, "etiquetas": False, "visibilidad_kml": None},
}
CAPA = {"type": "FeatureCollection", "carpeta": "m1", "estilos": [{"tipo": "punto", "color": "#ff8800", "radio": 7}],
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-86.2500, 12.1300]}, "properties": {"n": "MF UNO", "e": 0}},
                     {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-86.2560, 12.1360]}, "properties": {"n": "MF DOS", "e": 0}}]}


def _api(con):
    api = crear_api_prueba(con)
    api.kmz_arbol = lambda: {"ok": True, "arbol": {"version": 1, "kmz": "prueba.kmz", "importado": "hoy", "raiz": "raiz", "carpetas": CARPETAS, "elementos": 2, "aviso": ""}, "iconos": {}}
    api.kmz_capa = lambda cid: {"ok": True, "capa": CAPA}
    api.kmz_indice = lambda: {"ok": True, "indice": {"m1": [["MF UNO", ""], ["MF DOS", ""]]}}
    return api


async def _pixel(p, lat, lon):
    return await p.evaluar("(() => { const m = window.visor.mapa, q = m.latLngToContainerPoint([%s, %s]), r = m.getContainer().getBoundingClientRect(); return [r.left + q.x, r.top + q.y]; })()" % (lat, lon))


async def _abrir(p):
    await p.esperar("window.MisLugares && window.MisLugares.estado.listo && window.Lugares.estado.cargadas.includes('m1')", 45)
    await p.evaluar("window.visor.mapa.setView([12.133, -86.253], 16, {animate: false}); true")
    await asyncio.sleep(0.5)


async def _clic_punto(p, lat, lon):
    await p.evaluar("window.visor.mapa.closePopup(); true")
    await p.esperar("!document.querySelector('.lg-popup')", 5)
    x, y = await _pixel(p, lat, lon)
    await p.clic(x, y)
    await p.esperar("document.querySelector('.lg-popup')", 10)


async def _recorrido(mundo):
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    async with pagina_edge(1366, 768, api=_api(con)) as p:
        await _abrir(p)
        # ---- renombrar: el popup trae los botones de edición y «Entrar a la mufa»
        await _clic_punto(p, 12.13, -86.25)
        botones = await p.evaluar("[...document.querySelectorAll('.lg-popup button')].map(b => b.innerText)")
        assert {"Entrar a la mufa", "Renombrar", "Mover", "Eliminar"} <= set(botones), botones
        await p.evaluar("document.querySelector('.lg-popup [data-kc=renombrar]').click(); true")
        await p.esperar("document.getElementById('ml-pedir') && !document.getElementById('ml-pedir').hidden", 5)
        await p.evaluar("document.getElementById('ml-pedir-valor').value = 'MF UNO RENOMBRADA'; document.getElementById('ml-pedir-form').requestSubmit()")
        await p.esperar("window.KmzCambios.cantidad === 1", 10)
        fila = consulta("SELECT accion, nombre, despues, clave FROM redes.kmz_cambios")[0]
        assert fila["accion"] == "editar" and fila["nombre"] == "MF UNO" and fila["despues"]["nombre"] == "MF UNO RENOMBRADA" and "mf uno" in fila["clave"]
        await _clic_punto(p, 12.13, -86.25)
        assert "MF UNO RENOMBRADA" in await p.evaluar("document.querySelector('.lg-popup h3').innerText")
        assert "Deshacer cambios" in await p.evaluar("document.querySelector('.lg-popup').innerText")
        # ---- quitar la otra del mapa (pide confirmación)
        await p.evaluar("window.visor.mapa.closePopup(); true")
        await _clic_punto(p, 12.136, -86.256)
        await p.evaluar("document.querySelector('.lg-popup [data-kc=borrar]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("window.KmzCambios.cantidad === 2", 10)
        assert await p.evaluar("window.Lugares._s.capas.get('m1').items.filter(i => i.borrado).length") == 1
        assert await p.evaluar("window.Lugares._s.capas.get('m1').grupo.getLayers().length") == 1
        # ---- la lista «Cambios al KMZ» del árbol deshace
        await p.esperar("document.querySelector('[data-kc-lista]')", 5)
        await p.evaluar("document.querySelector('[data-kc-lista]').click(); true")
        await p.esperar("!document.getElementById('kc-lista').hidden", 5)
        texto = await p.evaluar("document.getElementById('kc-filas').innerText")
        assert "MF UNO RENOMBRADA" in texto and "quitado del mapa" in texto
        await p.evaluar("[...document.querySelectorAll('[data-kc-deshacer]')].pop().click(); true")           # the removal
        await p.esperar("window.KmzCambios.cantidad === 1", 10)
        assert await p.evaluar("window.Lugares._s.capas.get('m1').grupo.getLayers().length") == 2
        assert await p.errores() == []
    # ---- abrir el visor otra vez: el cambio sigue ahí (es de la base, no de la página)
    async with pagina_edge(1366, 768, api=_api(con), puerto=9334) as p:
        await _abrir(p)
        await p.esperar("window.KmzCambios.cantidad === 1", 10)
        assert await p.evaluar("window.Lugares._s.capas.get('m1').items[0].f.properties.n") == "MF UNO RENOMBRADA"
        # ---- «Entrar a la mufa» de una mufa que la migración no tiene: se ofrece crear una vacía y se abre su editor
        await _clic_punto(p, 12.136, -86.256)
        await p.evaluar("document.querySelector('.lg-popup [data-entrar-mufa]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 10)
        assert "no está en la red del módulo de redes" in await p.evaluar("document.getElementById('modal-confirmar').innerText")
        await p.evaluar("document.getElementById('conf-si').click(); true")
        for _ in range(50):
            if consulta("SELECT id FROM redes.elementos WHERE nombre = 'MF DOS'"):
                break
            await asyncio.sleep(0.2)
        creada = consulta("SELECT e.id, e.fuente, p.codigo FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id WHERE e.nombre = 'MF DOS'")
        assert len(creada) == 1 and creada[0]["fuente"] == "kmz" and creada[0]["codigo"] == "BASE-VISOR"
        await p.evaluar("window.visor.mapa.closePopup(); true")
        assert await p.errores() == []


def test_cambios_al_kmz_y_entrar_a_la_mufa(mundo):
    asyncio.run(_recorrido(mundo))
