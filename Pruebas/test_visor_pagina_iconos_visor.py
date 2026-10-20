"""Íconos de lo que dibuja el propio visor (postes y mufas de la ruta, nodos, mufa buscada, conexión y cliente), cambiables por todos
(web/mapa/iconos_visor.js, kmz_estilos con alcance «capa»), en la página real con la base desechable: la fila «Íconos del visor…», cambiar uno (se ve en
el mapa, en la leyenda y queda en la base), restablecer, y que al abrir otra vez el cambio sigue ahí."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_fase1 import DATOS
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

GENERAR = ("window.__stubs.calcular = () => ({ok: true, datos: %s, coordenada: '12.153000, -86.263000'});"
           "window.__stubs.estimar_presupuesto = () => ({ok: false, error: 'prueba'});"
           "document.getElementById('coord').value = '12.153, -86.263'; document.getElementById('generar').click(); true" % json.dumps(DATOS))
ICONOS_POSTE = "[...document.querySelectorAll('.leaflet-marker-icon')].filter(e => e.innerHTML.includes('<polygon') && e.innerHTML.includes('#e53935')).length"


async def _elegir(p, figura, color):
    await p.esperar("!document.getElementById('ml-iconos').hidden", 5)
    await p.evaluar("""(() => { const c = [...document.querySelectorAll('#ml-iconos [data-ic]')].find(b => JSON.parse(b.dataset.ic).id === '%s'); c.click();
      const i = document.getElementById('ml-ic-color'); i.value = '%s'; i.dispatchEvent(new Event('input', {bubbles: true}));
      document.querySelector('[data-ml-ic=aceptar]').click(); return true; })()""" % (figura, color))


async def _recorrido(mundo):
    con, lectura, *_ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.Redes && window.Redes.disponible && window.IconosVisor", 30)
        await p.evaluar(GENERAR)
        await p.esperar("window.visor.datos", 15)
        # ---- the row opens the window with every icon of the viewer
        await p.esperar("[...document.querySelectorAll('#lg-filas .lg-fila')].some(f => f.innerText.includes('Íconos del visor'))", 10)
        assert await p.evaluar("[...document.querySelectorAll('#lg-filas .lg-fila.seccion')].find(f => f.innerText.includes('Capas del visor')).querySelector('input').indeterminate !== undefined")
        await p.evaluar("[...document.querySelectorAll('#lg-filas .lg-fila')].find(f => f.innerText.includes('Íconos del visor')).click(); true")
        await p.esperar("!document.getElementById('iv-modal').hidden", 5)
        nombres = await p.evaluar("[...document.querySelectorAll('#iv-filas .iv-nombre')].map(e => e.innerText.trim())")
        assert nombres == ["Punto de conexión", "Cliente", "Mufa buscada", "Mufa intervenida", "Mufa en ruta", "Nodo Visio cercano", "Poste existente", "Poste nuevo",
                           "Poste nuevo marcado como existente"], nombres
        assert await p.evaluar("[...document.querySelectorAll('#iv-filas [data-iv=restablecer]')].every(b => b.disabled)") is True       # nothing changed yet
        antes = await p.evaluar(ICONOS_POSTE)
        # ---- change «Poste existente»: a red star for everybody
        await p.evaluar("document.querySelector('#iv-filas [data-id=poste] [data-iv=cambiar]').click(); true")
        await _elegir(p, "estrella", "#e53935")
        await p.esperar("window.IconosVisor.guardados.poste", 10)
        fila = consulta("SELECT clave, alcance, nombre, estilo FROM redes.kmz_estilos WHERE borrado_en IS NULL")
        assert len(fila) == 1 and fila[0]["clave"] == "capa|poste|" and fila[0]["alcance"] == "capa" and fila[0]["estilo"]["icono"]["id"] == "estrella"
        # the marker on the map is the new icon, and so are the legend and the window
        await p.esperar("%s === %d" % (ICONOS_POSTE, antes + 1), 5)
        assert "#e53935" in await p.evaluar("[...document.querySelectorAll('.leyenda .fila')].find(f => f.innerText.includes('Poste existente')).innerHTML")
        assert "cambiado" in await p.evaluar("document.querySelector('#iv-filas [data-id=poste] .iv-nombre').innerText")
        assert await p.evaluar("document.querySelector('#iv-filas [data-id=poste] [data-iv=restablecer]').disabled") is False
        assert await p.evaluar("document.querySelector('#iv-filas [data-id=posteNuevo] [data-iv=restablecer]').disabled") is True      # only that one changed
        # the pin of a searched mufa takes the new icon of «Mufa buscada» too
        await p.evaluar("window.visor.marcarBuscada(12.15, -86.26, 'MF X', 'MUFA'); true")
        await p.evaluar("document.querySelector('#iv-filas [data-id=buscada] [data-iv=cambiar]').click(); true")
        await _elegir(p, "cuadrado", "#00a651")
        await p.esperar("window.IconosVisor.guardados.buscada", 10)
        assert await p.evaluar("window.visor.mapa.hasLayer && [...document.querySelectorAll('.leaflet-marker-icon')].some(e => e.innerHTML.includes('#00a651'))") is True
        # ---- restablecer: the original again, and the database forgets it
        await p.evaluar("document.querySelector('#iv-filas [data-id=poste] [data-iv=restablecer]').click(); true")
        await p.esperar("!window.IconosVisor.guardados.poste", 10)
        await p.esperar("%s === %d" % (ICONOS_POSTE, antes), 5)
        assert [f["clave"] for f in consulta("SELECT clave FROM redes.kmz_estilos WHERE borrado_en IS NULL")] == ["capa|buscada|"]
        assert await p.errores() == []
    # ---- another session (another user, another PC): the icon changed for everyone is already there when the viewer opens
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.IconosVisor && window.IconosVisor.guardados.buscada", 30)
        assert (await p.evaluar("window.visor.iconosVisor.personalizados()"))["buscada"]["id"] == "cuadrado"
        await p.evaluar(GENERAR)
        await p.esperar("window.visor.datos", 15)
        assert "#00a651" in await p.evaluar("window.visor.iconosVisor.html('buscada')")
        assert await p.errores() == []


def test_icons_of_the_viewers_own_layers_are_changed_for_everyone(mundo):
    asyncio.run(_recorrido(mundo))
