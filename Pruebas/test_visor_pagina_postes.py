"""El boton de postes de la barra del mapa (mapa/postes.js): oculta de una vez los postes de la ruta, los de la red del KMZ y los de Mis lugares, deja visible todo lo demas
(la ruta, el cliente, la acometida), se pone rojo mientras estan ocultos y recuerda su estado. Pagina real (Edge sin ventana), base desechable."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import lugares_presupuesto, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

RUTA = [(12.1000, -86.2500), (12.1010, -86.2500), (12.1010, -86.2490)]
CLIENTE = {"lat": 12.1011, "lon": -86.2485, "nombre": "Constructores Unidos", "codigo": "C23839"}
POSTES = [(12.1005, -86.2500), (12.1010, -86.2495), (12.1010, -86.2490)]

EN_MAPA = """(() => { const ml = window.MisLugares._ml, cuenta = {};
  ml.elementos.forEach((e) => { if (ml.capas.has(e.id) && ml.grupo.hasLayer(ml.capas.get(e.id).capa)) cuenta[e.tipo] = (cuenta[e.tipo] || 0) + 1; });
  return cuenta; })()"""


async def _recorrido(con):
    actor = usuarios.identificar(con, usuario_windows="jgutierrez")
    lugares_presupuesto.guardar_ruta(con, actor, nombre="C23839_Constructores Unidos", puntos=RUTA, cliente=CLIENTE, postes_nuevos=POSTES)
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo && window.MisLugares.estado.elementos >= 5 && window.Postes && window.visor", 20)
        await p.evaluar("window.__prefs = []; window.__stubs.guardar_preferencias = (c) => { window.__prefs.push(c); return {ok: true}; }; true")
        antes = await p.evaluar(EN_MAPA)
        assert antes.get("poste") == 3 and antes.get("ruta") == 1 and antes.get("cliente") == 1                        # everything is on the map
        # a pole of the generated route (the layers of the route) is also on the map
        await p.evaluar("(() => { const c = window.visor._capas; c.postesExistentes.addLayer(L.marker([12.1, -86.25])); c.postesNuevos.addLayer(L.marker([12.101, -86.25])); return true; })()")
        assert await p.evaluar("window.visor.mapa.hasLayer(window.visor._capas.postesExistentes) && window.visor.mapa.hasLayer(window.visor._capas.postesNuevos)") is True
        assert await p.evaluar("document.querySelector('[data-bh=postes]').classList.contains('apagado')") is False
        # the button hides the poles, only them
        await p.evaluar("document.querySelector('[data-bh=postes]').click(); true")
        assert await p.evaluar("window.Postes.ocultos") is True
        despues = await p.evaluar(EN_MAPA)
        assert despues.get("poste", 0) == 0 and despues.get("ruta") == 1 and despues.get("cliente") == 1 and despues.get("cable") == antes.get("cable")     # the route, the client and the drop stay
        assert await p.evaluar("window.visor.mapa.hasLayer(window.visor._capas.postesExistentes) || window.visor.mapa.hasLayer(window.visor._capas.postesNuevos)") is False
        assert await p.evaluar("document.querySelector('[data-bh=postes]').classList.contains('apagado') && document.querySelector('[data-bh=postes]').getAttribute('aria-pressed')") == "true"
        assert "ocultos" in await p.evaluar("document.querySelector('[data-bh=postes]').title")
        assert await p.evaluar("window.__prefs") == [{"postes_ocultos": True}]                                                        # remembered
        # a pole that is drawn while they are hidden does not show either; the tree keeps its boxes (they are not unchecked)
        assert await p.evaluar("window.MisLugares._ml.elementos.size") >= 5
        # shown again: as they were
        await p.evaluar("document.querySelector('[data-bh=postes]').click(); true")
        assert await p.evaluar("window.Postes.ocultos") is False and await p.evaluar(EN_MAPA) == antes
        assert await p.evaluar("window.visor.mapa.hasLayer(window.visor._capas.postesExistentes) && window.visor.mapa.hasLayer(window.visor._capas.postesNuevos)") is True
        assert await p.evaluar("document.querySelector('[data-bh=postes]').classList.contains('apagado')") is False
        assert await p.evaluar("window.__prefs") == [{"postes_ocultos": True}, {"postes_ocultos": False}]
        # a layer that was off before hiding stays off when they come back
        await p.evaluar("window.visor.mapa.removeLayer(window.visor._capas.postesNuevos); window.Postes.poner(true); window.Postes.poner(false); true")
        assert await p.evaluar("window.visor.mapa.hasLayer(window.visor._capas.postesExistentes)") is True and await p.evaluar("window.visor.mapa.hasLayer(window.visor._capas.postesNuevos)") is False
        # the next time the viewer opens it remembers: with the preference saved the poles start hidden
        await p.evaluar("window.__stubs.preferencias = () => ({ok: true, preferencias: {postes_ocultos: true}}); window.Postes.poner(false); true")
        await p.evaluar("window.Postes.iniciar(window.pywebview.api).then(() => { window.__listo = true; }); true")
        await p.esperar("window.__listo === true", 5)
        assert await p.evaluar("window.Postes.ocultos") is True and (await p.evaluar(EN_MAPA)).get("poste", 0) == 0
        assert await p.errores() == []


def test_the_poles_button_hides_and_shows_the_poles_of_the_map(con_redes):
    asyncio.run(_recorrido(con_redes))
