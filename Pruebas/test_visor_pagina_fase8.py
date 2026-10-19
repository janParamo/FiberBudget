"""Visor v2, fase 8, en la página real: la sección «Actualizar la red» de la ventana Importar KMZ (solo administradores): KMZ vigente, comparar con el
presupuesto, poner al día (con confirmación y la casilla de quitar), revertir la última y subir un KMZ nuevo por partes. El servidor se simula con
respuestas fijas: la lógica de verdad está en test_redes_actualizar_red.py."""
import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


@pytest.fixture(autouse=True)
def _subidas_limpias():
    from visor_rutas import subidas
    subidas.almacen.reiniciar()                     # the store is global: uploads left by other tests would fill its limit
    yield
    subidas.almacen.reiniciar()

RESUMEN = {"archivo": "RED.kmz", "en_base": {"puntos": 100, "lineas": 10}, "nuevos": {"puntos": 7, "lineas": 2}, "sobran": {"puntos": 3, "lineas": 0},
           "postes_nuevos": 5, "mufas_nuevas": 1, "por_carpeta": {}, "sin_categoria": {"MAL ESTADO": 11},
           "ejemplos_nuevos": [{"nombre": "P3", "carpeta": "POSTES DE CONCRETO"}], "ejemplos_sobran": []}


def _api(con):
    api = crear_api_prueba(con)
    original = api.redes
    llamadas = []
    sync = {"hecha": False}

    def redes(metodo, args=None):
        llamadas.append((metodo, args))
        if metodo == "estado_actualizar_red":
            ultima = [{"id": "20261015-1", "archivo": "RED.kmz", "por": "x", "quitar": False, "revertida": False,
                       "insertados": {"puntos": 9, "lineas": 2}, "eliminados": {"puntos": 0, "lineas": 0}}] if sync["hecha"] else []
            return {"ok": True, "kmz": {"archivo": "RED.kmz", "tamano": 1, "modificado": "2026-10-15T14:00:00"}, "sincronizaciones": ultima}
        if metodo == "comparar_red_presupuesto":
            return {"ok": True, "resumen": RESUMEN}
        if metodo == "sincronizar_red_presupuesto":
            sync["hecha"] = True
            return {"ok": True, "id": "20261015-1", "resumen": RESUMEN, "insertados": {"puntos": 7, "lineas": 2}, "eliminados": {"puntos": 3 if args.get("quitar") else 0, "lineas": 0}}
        if metodo == "revertir_sincronizacion_red":
            sync["hecha"] = False
            return {"ok": True, "id": args["id"], "revertida": True}
        if metodo == "subir_kmz_red":
            return {"ok": True, "archivo": "nuevo.kmz", "tamano": 10, "elementos": 36000, "importado": "x", "anterior_en": None}
        return original(metodo, args)

    api.redes = redes
    api.llamadas = llamadas
    return api


async def _recorrido(mundo, tmp_path):
    con, *_ = mundo
    api = _api(con)
    kmz = tmp_path / "nuevo.kmz"
    kmz.write_bytes(b"PK\x03\x04" + b"x" * 5000)
    async with pagina_edge(1366, 768, api=api) as p:
        await p.esperar("window.ImportarKmz && window.ImportarKmz.estado.listo", 20)
        await p.clic_en('[data-bh="importar"]')
        await p.esperar("!document.getElementById('ik-ventana').hidden && document.getElementById('ik-cuerpo').innerText.includes('KMZ vigente: RED.kmz')", 10)
        texto = await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        assert "KMZ vigente: RED.kmz" in texto and "usan la base del presupuesto" in texto
        assert await p.evaluar("document.querySelector('[data-ik=red_sincronizar]')") is None                # nothing to update before comparing
        # ---- comparar
        await p.evaluar("document.querySelector('[data-ik=red_comparar]').click(); true")
        await p.esperar("document.querySelector('[data-ik=red_sincronizar]')", 8)
        texto = await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        assert "7 puntos y 2 líneas del KMZ no están en el presupuesto" in texto and "5 postes, 1 mufas" in texto
        assert "3 puntos y 0 líneas del presupuesto ya no están" in texto and "MAL ESTADO" in texto
        # ---- poner al día: pide confirmación; la casilla de quitar viaja al servidor
        await p.evaluar("document.querySelector('[data-ik=red_quitar]').click(); true")
        await p.evaluar("document.querySelector('[data-ik=red_sincronizar]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        confirmacion = await p.evaluar("document.getElementById('modal-confirmar').innerText")
        assert "7 puntos y 2 líneas" in confirmacion and "se quitan 3 puntos" in confirmacion and "revertirlo" in confirmacion
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.querySelector('[data-ik=red_revertir]')", 8)
        assert ("sincronizar_red_presupuesto", {"quitar": True}) in api.llamadas
        assert "Última sincronización: RED.kmz (+11 / −0)" in await p.evaluar("document.getElementById('ik-cuerpo').innerText")
        # ---- revertir
        await p.evaluar("document.querySelector('[data-ik=red_revertir]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("!document.querySelector('[data-ik=red_revertir]')", 8)
        assert any(m == "revertir_sincronizacion_red" and a == {"id": "20261015-1"} for m, a in api.llamadas)
        # ---- subir un KMZ nuevo: por partes, con confirmación, y el servidor recibe el id de la subida
        await p.subir_archivo("#ik-archivo-red", kmz)
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        assert "Reemplazar la red por «nuevo.kmz»" in await p.evaluar("document.getElementById('modal-confirmar').innerText")
        await p.evaluar("window.__recargada = false; document.getElementById('conf-si').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden && document.getElementById('modal-confirmar').innerText.includes('36,000 elementos')", 10)
        envio = next(a for m, a in api.llamadas if m == "subir_kmz_red")
        assert envio["nombre"] == "nuevo.kmz" and envio["subida_id"]
        await p.evaluar("document.getElementById('conf-no').click(); true")                                  # not now: no reload
        assert await p.errores() == []


def test_update_network_section_for_the_administrator(mundo, tmp_path):
    import asyncio
    asyncio.run(_recorrido(mundo, tmp_path))
