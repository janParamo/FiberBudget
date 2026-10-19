"""Medir en el mapa: además de los metros, el metraje final y el total con las reglas de negocio (mapa/medicion_total.js),
en una página real (Edge sin ventana, arnes_pagina.py) con `medir_ruta` simulado."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MEDICION = {"distancia_m": 410.5, "metraje_final_m": 520.25, "reserva_m": 109.75, "tipo_cable": "Flat", "umbral_m": 600,
            "postes": {"existentes": 2, "nuevos": 6, "requeridos": 8, "separacion_m": 50, "giros": 1},
            "supuestos": {"servicio": "Residencial", "ancho_de_banda": "10 Mbps", "conexiones_nuevas": 1, "mufas_intervenidas": 0},
            "avisos": []}
RESULTADO = {"calculado": True, "archivo": "Medicion_x.xlsx", "nombre": "Medicion x", "tecnologia": "gpon", "tipo_cable": "Flat",
             "metraje_final_m": 520.25, "postes_marcados": 0,
             "resumen": {"totales": [{"clave": "total", "etiqueta": "TOTAL", "valor": 12345.5}], "secciones": []}}
STUBS = """
window.__pesadas = 0;
window.__stubs.medir_ruta = (puntos, conTotal) => {
  if (!conTotal) return {ok: true, medicion: %(m)s};
  window.__pesadas++;
  if (window.__fallar) return {ok: false, error: 'LibreOffice no respondio'};
  return new Promise(r => setTimeout(() => r({ok: true, medicion: %(m)s, supuestos: {cable: 'Flat'}, resultado: %(r)s}), 600));
};
window.__guardado = []; window.__stubs.guardar_como = (a, t) => { window.__guardado.push([a, t]); return {ok: true, ruta: 'C:/x.xlsx'}; };
"""


def test_la_medida_muestra_metraje_final_y_total():
    import json

    async def recorrido():
        async with pagina_edge(1366, 768) as p:
            await p.esperar("window.MedicionTotal && window.pywebview", 20)
            await p.evaluar(STUBS % {"m": json.dumps(MEDICION), "r": json.dumps(RESULTADO)})
            await p.clic_en("#medir")
            await p.clic(800, 380)
            await asyncio.sleep(0.5)                      # two quick clicks would be a double click
            await p.clic(1000, 380)
            await asyncio.sleep(0.5)
            await p.evaluar("document.getElementById('medir').click(); true")
            await p.esperar("document.querySelector('.medidas .medida-calc')", 10)
            # 1) the metraje final arrives at once, the total shows it is being calculated
            tarjeta = await p.evaluar("document.querySelector('.medidas').innerText")
            assert "520.3 m" in tarjeta or "520.2 m" in tarjeta, tarjeta
            assert "Flat" in tarjeta and "10 existentes" not in tarjeta and "8 (2 existentes, 6 nuevos)" in tarjeta
            assert "Supone 1 conexión(es) de cliente y 0 mufa(s) intervenida(s)" in tarjeta
            etiqueta = await p.evaluar("document.querySelector('.tooltip-medida').innerText")
            assert "final 520 m" in etiqueta
            # 2) then the total (in the end-of-line label and in the card), with the Excel buttons
            await p.esperar("document.querySelector('.medidas [data-mt=descargar]')", 10)
            assert "C$ 12,345.50" in await p.evaluar("document.querySelector('.medidas').innerText")
            assert "C$ 12,345.50" in await p.evaluar("document.querySelector('.tooltip-medida').innerText")
            await p.evaluar("document.querySelector('.medidas [data-mt=descargar]').click(); true")
            await p.esperar("window.__guardado.length === 1", 5)
            assert await p.evaluar("window.__guardado[0]") == ["Medicion_x.xlsx", "xlsx"]
            # 3) the summary copied for the report carries both numbers
            assert await p.evaluar("window.__pesadas") == 1                    # one heavy call per measure, not per redraw
            assert await p.errores() == []
    asyncio.run(recorrido())


def test_si_falla_el_total_se_puede_reintentar_y_borrar_cancela():
    import json

    async def recorrido():
        async with pagina_edge(1366, 768) as p:
            await p.esperar("window.MedicionTotal && window.pywebview", 20)
            await p.evaluar(STUBS % {"m": json.dumps(MEDICION), "r": json.dumps(RESULTADO)} + "window.__fallar = true;")
            await p.clic_en("#medir")
            await p.clic(800, 380)
            await asyncio.sleep(0.5)                      # two quick clicks would be a double click
            await p.clic(1000, 380)
            await asyncio.sleep(0.5)
            await p.evaluar("document.getElementById('medir').click(); true")
            await p.esperar("document.querySelector('.medidas [data-mt=reintentar]')", 10)
            texto = await p.evaluar("document.querySelector('.medidas').innerText")
            assert "LibreOffice no respondio" in texto and "520" in texto           # the metraje stays
            await p.evaluar("window.__fallar = false; document.querySelector('.medidas [data-mt=reintentar]').click(); true")
            await p.esperar("document.querySelector('.medidas [data-mt=descargar]')", 10)
            assert await p.evaluar("window.__pesadas") == 2
            # deleting a measure while its total is on its way leaves no error behind
            await p.evaluar("document.querySelector('.medidas [data-quitar-medida]').click(); true")
            await asyncio.sleep(0.8)
            assert await p.evaluar("document.querySelectorAll('.medidas li').length") == 0
            assert await p.errores() == []
    asyncio.run(recorrido())
