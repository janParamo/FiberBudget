"""Visor v2, fase 5 (importar un KMZ a la red), en la página real (Edge sin ventana, base desechable, la red KMZ de la prueba en una caché temporal):
elegir el archivo, ver los conteos y la lista, filtrar y rechazar, aplicar (lo modificado queda en «Cambios al KMZ» y lo nuevo en la capa de
importados), ver el resultado en el mapa y revertir. Nada se publica en el presupuesto."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_importar_kmz import ACTUALIZACION, RED_ACTUAL, hacer_kmz
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)
from visor_rutas import kmz_capas
from visor_rutas.redes import importar_kmz

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


@pytest.fixture(autouse=True)
def _nunca_el_presupuesto_real(monkeypatch):
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", lambda: (_ for _ in ()).throw(AssertionError("no se publica en las pruebas de página")))


def _api(con, cache):
    api = crear_api_prueba(con)
    arbol = json.loads((cache / "arbol.json").read_text(encoding="utf-8"))
    api.kmz_arbol = lambda: {"ok": True, "arbol": arbol, "iconos": {}}
    api.kmz_capa = lambda cid: {"ok": True, "capa": json.loads((cache / "capas" / f"{cid}.geojson").read_text(encoding="utf-8"))}
    api.kmz_indice = lambda: {"ok": True, "indice": {}}
    return api


async def _recorrido(mundo, tmp_path, monkeypatch):
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    kmz = tmp_path / "red.kmz"
    kmz.write_bytes(hacer_kmz(RED_ACTUAL))
    cache = tmp_path / "datos_kmz"
    kmz_capas.importar(kmz, cache, descargar_iconos=False)
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", cache)
    nuevo = tmp_path / "actualizacion.kmz"
    nuevo.write_bytes(hacer_kmz(ACTUALIZACION))
    async with pagina_edge(1366, 768, api=_api(con, cache)) as p:
        await p.esperar("window.ImportarKmz && window.ImportarKmz.estado.listo && Object.keys(window.Lugares._s.carpetas).length > 0", 20)
        ids = await p.evaluar("Object.values(window.Lugares._s.carpetas).filter(c => c.directos).map(c => c.id)")
        for cid in ids:
            await p.evaluar("window.Lugares._marcarCarpeta(%s, true); true" % json.dumps(cid))
        await p.esperar("window.Lugares.estado.cargadas.length === %d" % len(ids), 15)
        # ---- el botón de la barra abre la ventana (ya no está deshabilitado) y se elige el archivo
        assert await p.evaluar("document.querySelector('[data-bh=importar]').getAttribute('aria-disabled')") is None
        await p.clic_en('[data-bh="importar"]')
        await p.esperar("!document.getElementById('ik-ventana').hidden", 5)
        assert "Elegir archivo KMZ" in await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        await p.subir_archivo("#ik-archivo", nuevo)
        await p.esperar("document.querySelector('.ik-chips')", 20)
        # ---- la revisión: conteos, modo sugerido, lista
        textos = await p.evaluar("[...document.querySelectorAll('.ik-chip')].map(c => c.innerText.replace(/\\s+/g, ' ').trim())")
        assert textos == ["1 nuevos", "3 modificados", "1 eliminados", "2 sin cambios"]
        assert await p.evaluar("document.querySelector('[name=ik-modo]:checked').value") == "actualizacion"
        assert await p.evaluar("document.querySelectorAll('.ik-fila').length") == 5
        assert "Importados (pendientes):" in await p.evaluar("document.getElementById('lg-filas').innerText")
        assert await p.evaluar("window.ImportarKmz._ik.revision.getLayers().length") == 5                       # the map shows the five
        # ---- filtrar por clase y rechazar uno
        await p.evaluar("document.querySelector('[data-ik=clase][data-clase=modificado]').click(); true")
        await p.esperar("document.querySelectorAll('.ik-fila').length === 3", 10)
        await p.evaluar("(() => { const c = [...document.querySelectorAll('[data-ik=aceptar]')].find(x => x.closest('li').innerText.includes('MF TRES RENOMBRADA')); c.click(); return true; })()")
        await p.esperar("window.ImportarKmz._ik.aceptadosTotal === 3", 10)
        # ---- aceptar también lo eliminado (empieza rechazado) con el filtro de la clase
        await p.evaluar("document.querySelector('[data-ik=clase][data-clase=eliminado]').click(); true")
        await p.esperar("document.querySelectorAll('.ik-fila').length === 1", 10)
        await p.evaluar("document.querySelector('[data-ik=aceptar_todos]').click(); true")
        await p.esperar("window.ImportarKmz._ik.aceptadosTotal === 4", 10)
        # ---- aplicar
        await p.evaluar("document.querySelector('[data-ik=aplicar]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        assert "4 cambios aceptados" in await p.evaluar("document.getElementById('modal-confirmar').innerText")
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.querySelector('.ik-resumen, .ik-pie [data-ik=revertir]')", 15)
        assert "1 nuevos, 2 modificados, 1 eliminados" in await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        cambios = {c["clave"]: c for c in consulta("SELECT clave, accion, despues FROM redes.kmz_cambios WHERE borrado_en IS NULL")}
        assert len(cambios) == 3 and cambios["RED/POSTES DE CONCRETO|p2|12.13200,-86.25200"]["accion"] == "borrar"
        # the map shows the network in force: P2 gone, MF DOS moved, the renamed one NOT applied (rejected), MF CUATRO in the new layer
        await p.esperar("window.KmzCambios.cantidad === 3", 10)
        items = await p.evaluar("(() => { const o = {}; window.Lugares.porCadaItem(({it}) => { o[it.orig.n || ''] = [it.borrado, it.f.properties.n]; }); return o; })()")
        assert items["P2"][0] is True and items["MF TRES"] == [False, "MF TRES"] and items["MF UNO"][0] is False
        assert await p.evaluar("window.ImportarKmz._ik.capaAplicados.getLayers().length") == 1
        assert "Importados (aplicados)" in await p.evaluar("document.getElementById('lg-filas').innerText")
        assert "Cambios al KMZ" in await p.evaluar("document.getElementById('lg-filas').innerText")
        # ---- revertir la última
        await p.evaluar("document.querySelector('[data-ik=revertir]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("window.KmzCambios.cantidad === 0 && window.ImportarKmz._ik.aplicados.length === 0", 15)
        items = await p.evaluar("(() => { const o = {}; window.Lugares.porCadaItem(({it}) => { o[it.orig.n || ''] = it.borrado; }); return o; })()")
        assert items["P2"] is False
        assert [f["estado"] for f in consulta("SELECT estado FROM redes.kmz_importaciones")] == ["revertida"]
        assert await p.errores() == []


def test_importar_un_kmz_a_la_red(mundo, tmp_path, monkeypatch):
    asyncio.run(_recorrido(mundo, tmp_path, monkeypatch))
