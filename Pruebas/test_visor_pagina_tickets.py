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
        assert await p.evaluar("getComputedStyle(document.querySelector('#tk-lista [data-ticket=\"DTF-377-48662\"] td.estado')).backgroundColor") == "rgb(230, 224, 111)"
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
