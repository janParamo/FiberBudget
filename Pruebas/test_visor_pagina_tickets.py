"""La vista «Tickets» del visor (web/tickets.js): la lista de los tickets de Kayako pendientes de presupuesto, lo que el programa leyó de cada uno y «Hacer presupuesto»,
que abre «Nuevo presupuesto» con el formulario llenado. El servidor se simula; la lectura del ticket de verdad está en test_kayako.py."""
import asyncio
import json

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import hay_edge, pagina_edge
from test_kayako import LICORERA
from visor_rutas import kayako

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _tickets():
    uno = kayako.datos_del_ticket(LICORERA)
    otro = kayako.datos_del_ticket({**LICORERA, "id": 901, "ticket": "FMO-311-48543", "asunto": "Presupuesto FO/Redundancia", "primer_comentario": "• Nombre: Ferretería Luna\n• Código: C21232\n"
                                    "• coordenadas: 12.1, -86.2 y 12.2, -86.3", "ejecutivo": "Elba Soto"})
    uno.update(presupuestos=[], pendiente=True, vencido=False, ultima_actividad="2999-01-01T00:00:00")
    otro.update(presupuestos=["FMO-311-48543_Ferreteria_Luna.xlsx"], pendiente=False, vencido=True, prioridad="Prioridad Alta")
    return [uno, otro]


STUBS = """(() => {
  window.__stubs.tickets_pendientes = () => ({ok: true, tickets: %s});
  window.__stubs.presupuesto_config = () => ({ok: true, servicios: ['Residencial', 'Empresarial', 'Corporativo'], medios: ['FO', 'Radio'], estimacion: {bandwidth: '10 Mbps'}, libreoffice: true});
  return true; })()""" % json.dumps(_tickets())


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.Tickets && document.querySelector('[data-vista=tickets]')", 20)
        await p.evaluar(STUBS)
        await p.evaluar("window.Tickets._st.cargando = false; true")                  # the first read of the page started before the stub existed (the test server has no such call)
        await p.evaluar("document.querySelector('[data-vista=tickets]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 1", 10)                  # only the pending one
        assert await p.evaluar("document.getElementById('tickets-contador').textContent") == "1" and await p.evaluar("document.getElementById('tickets-contador').hidden") is False
        await p.evaluar("document.getElementById('tk-con-hechos').click(); true")
        assert await p.evaluar("document.querySelectorAll('#tk-lista [data-ticket]').length") == 2 and "Con presupuesto" in await p.evaluar("document.getElementById('tk-lista').innerText")
        # the list looks like Kayako's: its columns, the green «Nivel», the red high priority, the yellow status and the pink row of what is overdue
        cabecera = await p.evaluar("[...document.querySelectorAll('#tk-lista thead th')].map((e) => e.textContent.trim())")
        assert cabecera == ["Ticket ID", "Prioridad", "Organización", "Estado", "Asunto", "Última actividad ▾", "Último en responder", "Respuestas", "Dueño"]
        assert await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"]').classList.contains('vencido')") is False
        assert await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"] td.prioridad').classList.contains('nivel')") is True
        assert await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"FMO-311-48543\"]').classList.contains('vencido')") is True
        assert await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"FMO-311-48543\"] td.prioridad').classList.contains('alta')") is True
        assert await p.evaluar("getComputedStyle(document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"] td.estado')).backgroundColor") == "rgb(255, 244, 204)"      # the soft yellow of the theme (tema.css: --aviso-fondo)
        assert await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"] td.org').textContent") == "Equipos y Sistemas"
        await p.evaluar("document.getElementById('tk-con-hechos').click(); true")
        # what was read from the ticket
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"]').click(); true")
        texto = await p.evaluar("document.getElementById('tk-detalle').innerText")
        for esperado in ("Compañia Licorera de Nicaragua", "C22344", "Claudia Miranda", "Carlos Canales", "7877 3419", "ccanales@serlicorera.com", "11.446029, -85.824754", "25 Mbps", "FO"):
            assert esperado in texto, esperado
        # «Hacer presupuesto» opens the form filled
        await p.evaluar("document.querySelector('#tk-detalle [data-tk=hacer]').click(); true")
        await p.esperar("!document.getElementById('vista-presupuesto').hidden && document.getElementById('f-client_code').value === 'C22344'", 10)
        valores = await p.evaluar("Object.fromEntries(['f-ticket_id', 'f-client_name', 'f-client_code', 'f-sales_exec', 'f-contact_name', 'f-contact_phone', 'f-coordenada', 'f-bandwidth', 'f-medium', 'f-raw_comment']"
                                  ".map((id) => [id, document.getElementById(id).value]))")
        assert valores == {"f-ticket_id": "DTF-377-48662", "f-client_name": "Compañia Licorera de Nicaragua, S.A (residencia de colaborador)", "f-client_code": "C22344", "f-sales_exec": "Claudia Miranda",
                           "f-contact_name": "Carlos Canales", "f-contact_phone": "7877 3419", "f-coordenada": "11.446029, -85.824754", "f-bandwidth": "25 Mbps", "f-medium": "FO", "f-raw_comment": ""}
        # a ticket with two coordinates: the one chosen in the list is the one that goes to the form
        await p.evaluar("document.querySelector('[data-vista=tickets]').click(); true")
        await p.evaluar("document.getElementById('tk-con-hechos').click(); true")
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"FMO-311-48543\"]').click(); true")
        assert await p.evaluar("document.querySelectorAll('#tk-coordenada option').length") == 2
        await p.evaluar("(() => { const s = document.getElementById('tk-coordenada'); s.value = '1'; s.dispatchEvent(new Event('change', {bubbles: true})); document.querySelector('#tk-detalle [data-tk=hacer]').click(); return true; })()")
        await p.esperar("document.getElementById('f-coordenada').value === '12.200000, -86.300000'", 10)
        assert await p.errores() == []


def test_the_tickets_window_lists_what_waits_for_a_budget_and_fills_the_form():
    asyncio.run(_recorrido())


async def _todas():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.Tickets && window.Masivas && document.querySelector('[data-vista=tickets]')", 20)
        await p.evaluar(STUBS)
        await p.evaluar("window.Redes = window.Redes || {}; try { window.Redes.disponible = true; } catch (e) {} window.__stubs.estado = () => ({ok: true, modo: 'local'}); true")      # the window of bulk coordinates needs the redes module
        await p.evaluar("window.Tickets._st.cargando = false; true")
        await p.evaluar("document.querySelector('[data-vista=tickets]').click(); document.getElementById('tk-con-hechos').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 2", 10)
        # a ticket with one coordinate does not offer it
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"]').click(); true")
        assert await p.evaluar("document.querySelector('#tk-detalle [data-tk=todas]')") is None
        # the one with two does: the window of «Coordenadas masivas» opens at the preview with both points, the ticket, the client and the code
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"FMO-311-48543\"]').click(); true")
        assert "2 coordenadas" in await p.evaluar("document.querySelector('#tk-detalle [data-tk=todas]').textContent")
        await p.evaluar("document.querySelector('#tk-detalle [data-tk=todas]').click(); true")
        await p.esperar("document.getElementById('ms-ventana') && !document.getElementById('ms-ventana').hidden && window.Masivas.estado.vista === 'previa'", 10)
        assert await p.evaluar("document.getElementById('vista-tickets').hidden") is True                         # back at the map, where the points are drawn
        puntos = await p.evaluar("window.Masivas._ms.puntos.map(x => [x.n, x.ticket, x.nombre, x.codigo, x.lat, x.lon, x.estado, x.incluir])")
        assert puntos == [[1, "FMO-311-48543", "Ferretería Luna 1", "C21232", 12.1, -86.2, "ok", True], [2, "FMO-311-48543", "Ferretería Luna 2", "C21232", 12.2, -86.3, "ok", True]]
        assert await p.evaluar("window.Masivas._ms.nombre") == "FMO-311-48543_Ferretería Luna.txt"
        assert "2 coordenadas" in await p.evaluar("document.getElementById('ms-ventana').innerText")
        assert await p.errores() == []


def test_a_ticket_with_several_coordinates_goes_to_the_bulk_window():
    asyncio.run(_todas())


def _de_carpeta(prefijo, estados):
    return [{**kayako.datos_del_ticket({**LICORERA, "id": 700 + i, "ticket": f"{prefijo}-{i}", "asunto": f"{prefijo} caso {i}", "tipo": "FO – Caída Total Nodo", "estado": e}),
             "ultima_actividad": "2999-01-01T00:00:00"} for i, e in enumerate(estados, 1)]


HISTORIAL = {"ok": True, "kayako_id": 0, "comentarios": [
    {"id": 1, "fecha": "2026-11-10T08:02:17", "autor": "Andrew Reyes", "origen": "personal", "privado": False, "adjuntos": False, "texto": "Apertura: corte de fibra en el nodo"},
    {"id": 2, "fecha": "2026-11-10T11:30:00", "autor": "Cliente Uno", "origen": "cliente", "privado": False, "adjuntos": True, "texto": "Seguimos sin servicio"}],
    "notas": [{"id": 9, "fecha": "2026-11-10T09:37:43", "autor": "César Muñoz", "editada": False, "color": 1, "texto": "| MGA-ENT-OLT-001 | 0/2/1 | 20 | C29715 ILSE |"}]}


async def _carpetas():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.Tickets && document.querySelector('[data-vista=tickets]')", 20)
        await p.evaluar(STUBS)
        incidencias, instalaciones = _de_carpeta("INC", ["Abierto", "En Progreso"]), _de_carpeta("INS", ["Planificación", "Agendado", "Abierto"])
        await p.evaluar("""(() => { const d = %s; window.__carpetas = []; window.__stubs.tickets_carpeta = (c) => { window.__carpetas.push(c); return {ok: true, carpeta: c, titulo: c, tickets: d[c]}; }; return true; })()"""
                        % json.dumps({"incidencias_masivas": incidencias, "instalaciones": instalaciones}))
        await p.evaluar("window.__historiales = []; window.__stubs.ticket_historial = (id) => { window.__historiales.push(id); return %s; }; true" % json.dumps(HISTORIAL))
        await p.evaluar("window.Tickets._st.cargando = false; true")
        await p.evaluar("document.querySelector('[data-vista=tickets]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 1", 10)                  # Presupuesto is the folder that opens, as before
        assert await p.evaluar("[...document.querySelectorAll('.tk-carpeta')].map((b) => b.dataset.carpeta)") == ["presupuesto", "incidencias_masivas", "instalaciones"]
        assert await p.evaluar("document.getElementById('tk-hechos-caja').hidden") is False and await p.evaluar("window.__carpetas.length") == 0       # the other folders are not read until opened
        # Incidencias masivas: every ticket the server sent (it already left the closed ones out), shown like the budget ones, without the budget buttons
        await p.evaluar("document.querySelector('[data-carpeta=incidencias_masivas]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 2", 10)
        assert await p.evaluar("document.getElementById('tk-titulo').textContent") == "Incidencias masivas" and await p.evaluar("document.getElementById('tk-hechos-caja').hidden") is True
        assert await p.evaluar("document.getElementById('tk-n-incidencias_masivas').textContent") == "2"
        assert await p.evaluar("[...document.querySelectorAll('#tk-lista thead th')].length") == 9 and "FO – Caída Total Nodo" in await p.evaluar("document.getElementById('tk-lista').innerText")
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"INC-1\"]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-detalle .tk-msg, #tk-detalle .tk-nota-k').length === 3", 10)
        texto = await p.evaluar("document.getElementById('tk-detalle').innerText")
        assert "INC-1" in texto and "Compañia Licorera de Nicaragua" in texto and "Historial de comentarios y notas" in texto
        assert await p.evaluar("document.querySelectorAll('#tk-detalle [data-tk=hacer], #tk-detalle [data-tk=todas]').length") == 0                  # no «Hacer presupuesto» here
        # the comments and the notes, in the order they were written: comment, note (yellow), comment
        assert await p.evaluar("[...document.querySelectorAll('#tk-detalle .tk-hist-cuerpo > article')].map((a) => a.className.split(' ')[0])") == ["tk-msg", "tk-nota-k", "tk-msg"]
        assert "1 nota" in await p.evaluar("document.querySelector('#tk-detalle .tk-hist-resumen').textContent") and "2 comentarios" in await p.evaluar("document.querySelector('#tk-detalle .tk-hist-resumen').textContent")
        assert "MGA-ENT-OLT-001" in await p.evaluar("document.querySelector('#tk-detalle .tk-nota-k').innerText") and "Cliente" in await p.evaluar("document.querySelector('#tk-detalle .tk-msg.cliente').innerText")
        n_historiales = await p.evaluar("window.__historiales.length")
        await p.evaluar("window.Tickets._st.firmaDetalle = ''; document.querySelector('#tk-lista [data-ticket=\"INC-1\"]').click(); true")
        assert await p.evaluar("window.__historiales.length") == n_historiales                                    # the history is kept for a minute: not read again
        # a ticket in its own tab: only that ticket, with all the room; the main tab keeps the list
        await p.evaluar("document.querySelector('[data-tk=pestana]').click(); true")
        await p.esperar("!document.getElementById('tk-pagina').hidden", 5)
        assert await p.evaluar("document.getElementById('tk-pagina').innerText.includes('INC-1')") and await p.evaluar("document.querySelector('.tk-cuerpo').hidden") is True and await p.evaluar("document.querySelector('.tk-carpetas').hidden") is True
        await p.esperar("document.querySelectorAll('#tk-pagina .tk-msg, #tk-pagina .tk-nota-k').length === 3", 10)
        assert await p.evaluar("[...document.querySelectorAll('#tk-pestanas [data-pestana]')].map((b) => b.dataset.pestana)") == ["lista", "incidencias_masivas:INC-1"]
        # a second ticket (double click on its row) has its own tab too; opening the first one again does not repeat it
        await p.evaluar("document.querySelector('#tk-pestanas [data-pestana=lista]').click(); true")
        await p.esperar("!document.querySelector('.tk-cuerpo').hidden", 5)
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"INC-2\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true")
        await p.esperar("document.querySelectorAll('#tk-pestanas [data-pestana]').length === 3 && document.getElementById('tk-pagina').innerText.includes('INC-2')", 5)
        await p.evaluar("document.querySelector('#tk-pestanas [data-pestana=lista]').click(); true")
        await p.evaluar("document.querySelector('#tk-lista [data-ticket=\"INC-1\"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true")
        await p.esperar("document.getElementById('tk-pagina').innerText.includes('INC-1') && !document.getElementById('tk-pagina').hidden", 5)
        assert await p.evaluar("document.querySelectorAll('#tk-pestanas [data-pestana]').length") == 3
        # closing a tab leaves the next one open; the last one takes back to the list
        await p.evaluar("document.querySelector('#tk-pestanas [data-cerrar=\"incidencias_masivas:INC-1\"]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-pestanas [data-pestana]').length === 2 && document.getElementById('tk-pagina').innerText.includes('INC-2')", 5)
        await p.evaluar("document.querySelector('#tk-pestanas [data-cerrar=\"incidencias_masivas:INC-2\"]').click(); true")
        await p.esperar("document.getElementById('tk-pagina').hidden && !document.querySelector('.tk-cuerpo').hidden", 5)
        # the height of the list is changed with the bar under it, and a double click puts it back
        antes = await p.evaluar("document.querySelector('.tk-tabla-caja').getBoundingClientRect().height")
        caja = await p.evaluar("(() => { const r = document.getElementById('tk-divisor').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()")
        await p.evaluar("""((c) => { const d = document.getElementById('tk-divisor'); const ev = (t, y) => d.dispatchEvent(new PointerEvent(t, {bubbles: true, pointerId: 1, clientX: c.x, clientY: y}));
          d.setPointerCapture = () => {}; ev('pointerdown', c.y); ev('pointermove', c.y + 120); ev('pointerup', c.y + 120); return true; })(%s)""" % json.dumps(caja))
        despues = await p.evaluar("document.querySelector('.tk-tabla-caja').getBoundingClientRect().height")
        assert despues > antes + 60, (antes, despues)
        await p.evaluar("document.getElementById('tk-divisor').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); true")
        assert await p.evaluar("document.querySelector('.tk-cuerpo').style.getPropertyValue('--tk-alto')") == ""
        # Instalaciones
        await p.evaluar("document.querySelector('[data-carpeta=instalaciones]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 3", 10)
        assert await p.evaluar("window.__carpetas") == ["incidencias_masivas", "instalaciones"]
        # back to Presupuesto: the same list as before, with its own checkbox, and the menu badge still counts the budget ones
        await p.evaluar("document.querySelector('[data-carpeta=presupuesto]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 1 && document.getElementById('tk-titulo').textContent.includes('presupuesto')", 10)
        assert await p.evaluar("document.getElementById('tickets-contador').textContent") == "1"
        # opening a folder again does not read it again (the list is kept) until «Actualizar»
        await p.evaluar("document.querySelector('[data-carpeta=instalaciones]').click(); true")
        await p.esperar("document.querySelectorAll('#tk-lista [data-ticket]').length === 3", 10)
        assert await p.evaluar("window.__carpetas.length") == 2
        await p.evaluar("document.getElementById('tk-recargar').click(); true")
        await p.esperar("window.__carpetas.length === 3", 10)
        assert await p.errores() == []


def test_the_three_folders_of_tickets():
    asyncio.run(_carpetas())
