"""«Convertir a PDF…» del historial (web/lugares/pdf_existentes.js), en la página real: las dos listas con casillas, lo que se manda a convertir, el avance y
los botones del final. El servidor se simula; la conversión de verdad está en test_pdf_lote.py."""
import json

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import hay_edge, pagina_edge

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

SUELTOS = [{"archivo": "C:/o/visor/Casa_Perez_12.1_-86.2_20261020-100000.xlsx", "nombre": "Casa_Perez_12.1_-86.2_20261020-100000.xlsx", "cliente": "Casa Perez",
            "fecha": "2026-10-20T10:00:00", "coordenada": "12.1, -86.2", "tiene_pdf": False},
           {"archivo": "C:/o/visor/Tienda_Ana_12.2_-86.3_20261021-100000.xlsx", "nombre": "Tienda_Ana_12.2_-86.3_20261021-100000.xlsx", "cliente": "Tienda Ana",
            "fecha": "2026-10-21T10:00:00", "coordenada": "12.2, -86.3", "tiene_pdf": True}]
LOTES = [{"id": "masivo_20261026-091704_Matagalpa", "nombre": "Matagalpa", "fecha": "2026-10-26 09:17", "xlsx": 3, "grupos": [
    {"id": "masivo_20261026-091704_Matagalpa/aprobados", "nombre": "aprobados", "xlsx": 2, "pdf": 0, "destino": "aprobados_pdf"},
    {"id": "masivo_20261026-091704_Matagalpa/desaprobados", "nombre": "desaprobados", "xlsx": 1, "pdf": 1, "destino": "desaprobados_pdf"}]}]
STUBS = """(() => {
  window.__pedido = null; window.__sondeos = 0; window.__zip = 0;
  window.__stubs.historial_presupuestos = () => ({ok: true, presupuestos: %s});
  window.__stubs.pdf_carpetas = () => ({ok: true, carpetas: %s});
  window.__stubs.pdf_convertir = (archivos, carpetas, externos) => { window.__pedido = {archivos, carpetas, externos};
    return {ok: true, trabajo: {id: '20261026-100000', estado: 'convirtiendo', hechos: 0, total: 3, actual: 'a.xlsx', fallos: [], pdf: 0, carpetas_salida: []}}; };
  window.__stubs.pdf_estado = (id) => { window.__sondeos++; const listo = window.__sondeos >= 2;
    return {ok: true, trabajo: {id, estado: listo ? 'listo' : 'convirtiendo', hechos: listo ? 3 : 1, total: 3, actual: listo ? '' : 'b.xlsx', fallos: [], pdf: listo ? 3 : 1, carpetas_salida: ['aprobados_pdf']}}; };
  window.__stubs.pdf_descargar = (id) => { window.__zip++; return {ok: true, nombre: 'PDF_x.zip', datos: 'eA=='}; };
  window.__stubs.pdf_abrir_carpeta = () => ({ok: true});
  window.__plan = null;
  window.__stubs.redes = (metodo, args) => { window.__plan = {metodo, args}; return {ok: true, creadas: 2, repetidas: 1, fallidas: 0, resultados: []}; };
  window.__elegidos = 0;
  window.__stubs.pdf_elegir = (tipo) => { window.__elegidos++; return tipo === 'carpeta' ? {ok: true, rutas: ['D:/Presupuestos/Managua']} : {ok: true, rutas: ['D:/x/uno.xlsx', 'D:/x/dos.xlsx']}; };
  window.__stubs.guardar_archivo = (nombre, datos, tipo) => ({ok: true, ruta: 'C:/x/' + nombre});
  return true; })()""" % (json.dumps(SUELTOS), json.dumps(LOTES))

API = "{ historial_presupuestos: (...a) => window.pywebview.api.historial_presupuestos(...a), pdf_carpetas: (...a) => window.pywebview.api.pdf_carpetas(...a), " \
      "pdf_convertir: (...a) => window.pywebview.api.pdf_convertir(...a), pdf_estado: (...a) => window.pywebview.api.pdf_estado(...a), " \
      "pdf_descargar: (...a) => window.pywebview.api.pdf_descargar(...a), pdf_elegir: (...a) => window.pywebview.api.pdf_elegir(...a), redes: (...a) => window.pywebview.api.redes(...a), pdf_abrir_carpeta: (...a) => window.pywebview.api.pdf_abrir_carpeta(...a) }"


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.PdfExistentes", 20)
        await p.evaluar(STUBS)
        await p.evaluar("window.visor && document.querySelectorAll('.vista').forEach((v) => { v.hidden = v.dataset.vista !== 'presupuesto'; }); true")      # opened from the Presupuestos view
        await p.evaluar("window.PdfExistentes.abrir({ api: () => (%s), aviso: () => {} }); true" % API)
        await p.esperar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=marca]').length === 2", 10)
        assert await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=carpeta_marca]').length") == 2
        # it is on top of the Presupuestos view (not hidden behind it): the element at the centre of the window belongs to it
        assert await p.evaluar("(() => { const r = document.getElementById('pdfx-ventana').getBoundingClientRect();"
                               " const e = document.elementFromPoint(r.left + r.width / 2, r.top + 60); return !!e && document.getElementById('pdfx-ventana').contains(e); })()") is True
        texto = await p.evaluar("document.getElementById('pdfx-cuerpo').innerText")
        assert "Matagalpa" in texto and "aprobados" in texto and "1 PDF ya hechos" in texto and "ya tiene PDF" in texto
        assert await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=convertir]').disabled") is True               # nothing marked yet
        # the file explorer: files and a folder chosen by hand join the list (and count) and can be removed
        await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=elegir_archivos]').click(); true")
        await p.esperar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=quitar_externo]').length === 2", 5)
        await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=elegir_carpeta]').click(); true")
        await p.esperar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=quitar_externo]').length === 3", 5)
        assert "Managua" in await p.evaluar("document.getElementById('pdfx-cuerpo').innerText")
        await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=quitar_externo]')[1].click(); true")                    # remove dos.xlsx
        assert await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=quitar_externo]').length") == 2
        # taking budgets to planning needs something marked; then it sends the keys of the Excel files and the groups
        assert await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=plan]').disabled") is True
        # mark one loose budget and the aprobados group of the batch
        await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=marca]')[1].click(); true")
        await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=carpeta_marca]')[0].click(); true")
        assert "Convertir a PDF (4)" in await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=convertir]').innerText")
        await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=plan]').click(); true")
        await p.esperar("window.__plan !== null", 5)
        assert await p.evaluar("window.__plan") == {"metodo": "plan_llevar", "args": {"archivos": ["Tienda_Ana_12.2_-86.3_20261021-100000.xlsx"], "carpetas": ["masivo_20261026-091704_Matagalpa/aprobados"]}}
        await p.esperar("document.getElementById('pdfx-cuerpo').innerText.includes('2 actividad(es) creada(s) en Planificación, 1 ya estaban')", 5)
        await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=convertir]').click(); true")
        await p.esperar("window.__pedido !== null", 5)
        assert await p.evaluar("window.__pedido") == {"archivos": [SUELTOS[1]["archivo"]], "carpetas": ["masivo_20261026-091704_Matagalpa/aprobados"],
                                                      "externos": {"archivos": ["D:/x/uno.xlsx"], "carpetas": ["D:/Presupuestos/Managua"]}}
        await p.esperar("document.querySelector('#pdfx-cuerpo [data-pdfx=zip]') !== null", 15)                                    # finished: the buttons appear
        assert "3 de 3" in await p.evaluar("document.getElementById('pdfx-cuerpo').innerText")
        await p.evaluar("document.querySelector('#pdfx-cuerpo [data-pdfx=zip]').click(); true")
        await p.esperar("window.__zip === 1", 5)
        # the filter narrows the loose budgets and «Marcar los que se ven» marks only those
        await p.evaluar("(() => { const i = document.getElementById('pdfx-filtro'); i.value = 'ana'; i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
        assert await p.evaluar("document.querySelectorAll('#pdfx-cuerpo [data-pdfx=marca]').length") == 1
        assert await p.errores() == []


def test_convert_existing_budgets_to_pdf_in_the_page():
    import asyncio
    asyncio.run(_recorrido())
