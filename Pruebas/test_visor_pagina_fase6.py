"""Visor v2, fase 6 (coordenadas masivas), en la página real (Edge sin ventana, base desechable): el archivo se lee de verdad (Python), la vista previa deja
corregir, el lote se simula (`masivas_iniciar` / `masivas_estado`: sin Google ni LibreOffice) y lo que se guarda en Mis lugares y como proyecto va a la
base de prueba."""
import asyncio
import json

import pytest

from arnes_pagina import hay_edge, pagina_edge
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _resultado(n, nombre, lat, lon, **extra):
    return {"n": n, "nombre": nombre, "codigo": "", "lat": lat, "lon": lon, "ok": True, "conexion": "MF PRUEBA", "conexion_lat": 12.13, "conexion_lon": -86.25,
            "distancia_m": 100.0 * n, "metraje_final_m": 100.0 * n + 40, "tipo_cable": "Flat", "aproximada": False, "ruta": [[12.13, -86.25], [lat, lon]],
            "postes_existentes": 1, "postes_nuevos": n, "mufas": 1, "total": 1000.0 * (4 - n), "calculado": True, "archivo": f"C:/x/{n}.xlsx", "nombre_archivo": f"{n}.xlsx",
            "avisos": ["Aviso uno"] if n == 1 else [], **extra}


STUBS = """
window.__iniciado = null; window.__sondeos = 0; window.__carpeta = 0;
window.__stubs.masivas_iniciar = (nombre, puntos) => { window.__iniciado = {nombre, puntos}; return {ok: true, lote: {id: '20261015-100000', nombre: 'clientes', estado: 'corriendo', total: 3, hechos: 0,
  actual: 'Casa', mensaje: '', esperando_s: 0, carpeta: 'C:/x', segundos: 4, resultados: []}}; };
window.__stubs.masivas_estado = (id, desde) => { window.__sondeos++;
  const todos = %(resultados)s;
  const listo = window.__sondeos >= 2;
  const hechos = listo ? 3 : 1;
  return {ok: true, lote: {id, nombre: 'clientes', estado: listo ? 'terminado' : 'corriendo', total: 3, hechos, actual: listo ? null : 'Tienda', mensaje: '', esperando_s: 0, carpeta: 'C:/x',
          segundos: 30, resultados: todos.slice(desde, hechos)}}; };
window.__stubs.masivas_abrir_carpeta = (id) => { window.__carpeta++; return {ok: true}; };
"""


async def _recorrido(mundo, tmp_path):
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    csv = tmp_path / "clientes.csv"
    csv.write_text("Nombre,Código,Latitud,Longitud\nCasa Pérez,C12345,12.1364,-86.2514\nTienda Ana,,12.14,-86.26\nAl revés,,-86.27,12.15\nMala,,abc,def\nCasa repetida,,12.1364,-86.2514\n", encoding="utf-8")
    resultados = [_resultado(1, "Casa Pérez", 12.1364, -86.2514, codigo="C12345"), _resultado(2, "Tienda Ana", 12.14, -86.26),
                  {"n": 3, "nombre": "Al revés", "codigo": "", "lat": 12.15, "lon": -86.27, "ok": False, "error": "No se encontró mufa, reserva ni nodo de red para esta coordenada"}]
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.Masivas && window.MisLugares && window.MisLugares.estado.listo", 20)
        await p.evaluar(STUBS % {"resultados": json.dumps(resultados)})
        assert await p.evaluar("document.querySelector('[data-bh=masivas]').getAttribute('aria-disabled')") is None
        await p.clic_en('[data-bh="masivas"]')
        await p.esperar("!document.getElementById('ms-ventana').hidden", 5)
        await p.subir_archivo("#ms-archivo", csv)
        await p.esperar("document.querySelector('.ms-t')", 15)
        # ---- la vista previa: lo que se leyó, lo que tiene problema, y los puntos en el mapa
        assert await p.evaluar("window.Masivas._ms.puntos.map(x => x.estado)") == ["ok", "ok", "invertida", "invalida", "duplicada"]
        chips = await p.evaluar("[...document.querySelectorAll('.ik-chip')].map(c => c.innerText.replace(/\\s+/g, ' ').trim())")
        assert chips == ["2 válidas", "1 al revés", "1 con problema", "1 duplicadas"]
        assert await p.evaluar("document.querySelector('[data-ms=calcular]').innerText") == "Calcular 2 presupuesto(s)"
        assert await p.evaluar("document.querySelectorAll('.ms-num').length") >= 3                              # numbered markers of the points that have a position
        # ---- corregir: usar la sugerida de la que está al revés y escribir bien la que no se entendía
        await p.evaluar("document.querySelector('[data-ms=usar_sugerida]').click(); true")
        await p.esperar("window.Masivas._ms.puntos[2].estado === 'ok'", 5)
        await p.evaluar("(() => { const i = document.querySelectorAll('[data-ms=texto]')[3]; i.value = '12.16 -86.28'; i.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        await p.esperar("window.Masivas._ms.puntos[3].estado === 'ok'", 5)
        assert await p.evaluar("document.querySelector('[data-ms=calcular]').innerText") == "Calcular 4 presupuesto(s)"
        # ---- calcular: confirma, avanza y termina
        await p.evaluar("document.querySelector('[data-ms=calcular]').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        assert "4 presupuestos aproximados" in await p.evaluar("document.getElementById('modal-confirmar').innerText")
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.querySelector('.ms-barra')", 10)
        iniciado = await p.evaluar("window.__iniciado")
        assert iniciado["nombre"] == "clientes.csv" and [x["incluir"] for x in iniciado["puntos"]] == [True, True, True, True, False]
        await p.esperar("window.Masivas.estado.vista === 'resultados'", 15)
        assert await p.evaluar("document.querySelectorAll('.ms-t tbody tr').length") == 3
        assert "No se encontró mufa" in await p.evaluar("document.querySelector('.ms-error').innerText")
        # ---- la tabla se ordena y un clic muestra la ruta
        primera = lambda: p.evaluar("document.querySelector('.ms-t tbody tr td').innerText")
        assert await primera() == "1"
        await p.evaluar("document.querySelector('[data-campo=distancia_m]').click(); true")
        await p.evaluar("document.querySelector('[data-campo=distancia_m]').click(); true")                  # descending
        assert await primera() == "2"
        await p.evaluar("document.querySelector('[data-ms=ver_ruta][data-n=\"1\"]').click(); true")
        assert await p.evaluar("window.Masivas._ms.capaRuta.getLayers().length") == 3
        # ---- abrir la carpeta (modo local)
        await p.evaluar("document.querySelector('[data-ms=carpeta]').click(); true")
        await p.esperar("window.__carpeta === 1", 5)
        # ---- guardar en Mis lugares (con las rutas) y como proyecto: a la base de prueba
        await p.evaluar("document.querySelector('[data-ms=lugares]').click(); true")
        await p.esperar("/Carpeta creada en Mis lugares con 2 punto\\(s\\) y 2 ruta\\(s\\)/.test(document.getElementById('ms-cuerpo').innerText)", 15)
        assert sorted(f["nombre"] for f in consulta("SELECT nombre FROM redes.lugares_carpetas")) == ["Rutas", "clientes"]
        assert sorted(f["nombre"] for f in consulta("SELECT nombre FROM redes.lugares_elementos WHERE tipo = 'marca'")) == ["Casa Pérez", "Tienda Ana"]
        await p.evaluar("document.querySelector('[data-ms=proyecto]').click(); true")
        await p.esperar("/Proyecto «clientes» \\(MAS-CLIENTES\\) creado: 2 cliente\\(s\\), 1 punto\\(s\\) de conexión, 2 cable\\(s\\)/.test(document.getElementById('ms-cuerpo').innerText)", 15)
        assert consulta("SELECT count(*) AS n FROM redes.cables c JOIN redes.proyectos p ON p.id = c.proyecto_id WHERE p.codigo = 'MAS-CLIENTES'")[0]["n"] == 2
        assert await p.errores() == []


def test_coordenadas_masivas_en_la_pagina(mundo, tmp_path):
    asyncio.run(_recorrido(mundo, tmp_path))
