"""La ruta guardada de un presupuesto, editada en Mis lugares (página real, Edge sin ventana, base desechable): la ventana de edición enseña como al medir el metraje, la acometida
al cliente, la reserva y los postes, avisa qué postes nuevos se borrarán por ya no usarse y, al guardar, se borran solos y la acometida sigue al final de la ruta."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, lugares_presupuesto, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

RUTA = [(12.1000, -86.2500), (12.1010, -86.2500), (12.1010, -86.2490)]
CLIENTE = {"lat": 12.1011, "lon": -86.2485, "nombre": "Constructores Unidos", "codigo": "C23839"}
POSTES = [(12.1005, -86.2500), (12.1010, -86.2495), (12.1010, -86.2490)]


@pytest.fixture
def mundo(base_redes, con_redes):
    admin = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    lectura = db.conectar(params=base_redes[1])
    yield con_redes, lectura, admin
    lectura.close()


async def _recorrido(mundo):
    con, lectura, admin = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    r = lugares_presupuesto.guardar_ruta(con, admin, nombre="C23839_Constructores Unidos", puntos=RUTA, cliente=CLIENTE, postes_nuevos=POSTES)
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo && window.MisLugares.estado.elementos >= 5", 20)
        await p.evaluar("window.MisLugares.editar(%d); true" % r["id"])
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
        # the numbers come first: the Medidas tab is the one shown, with the budget of the route as it is saved
        await p.esperar("document.getElementById('ml-d-medidas').innerText.includes('Postes nuevos guardados que se usan')", 10)
        texto = await p.evaluar("document.getElementById('ml-d-medidas').innerText")
        assert "Longitud de la ruta" in texto and "Acometida al cliente" in texto and "3 de 3" in texto and "se borrarán" not in texto
        assert await p.evaluar("document.getElementById('ml-d-pest-medidas').getAttribute('aria-selected') === 'true' || !document.getElementById('ml-d-medidas').hidden") is True
        # the route is moved a block north, away from the three new poles: the window says they will be deleted
        await p.evaluar("""(() => { const c = window.MisLugares._ml.trabajo.capa; c.setLatLngs([[12.1100, -86.2500], [12.1105, -86.2495], [12.1110, -86.2490]]); c.fire('pm:edit'); return true; })()""")
        await p.esperar("document.getElementById('ml-d-medidas').innerText.includes('se borrarán 3 poste(s)')", 10)
        texto = await p.evaluar("document.getElementById('ml-d-medidas').innerText")
        assert "0 de 3" in texto and "Poste nuevo 1" in texto
        assert len(consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'poste' AND borrado_en IS NULL")) == 3          # nothing is deleted until it is saved
        await p.evaluar("document.getElementById('ml-d-form').requestSubmit()")
        await p.esperar("!document.getElementById('ml-dialogo') || document.getElementById('ml-dialogo').hidden", 10)
        await asyncio.sleep(0.6)
        assert consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'poste' AND borrado_en IS NULL") == []              # deleted by themselves
        cable = consulta("SELECT ST_AsGeoJSON(geom, 6) AS g FROM redes.lugares_elementos WHERE tipo = 'cable' AND borrado_en IS NULL")[0]["g"]
        assert "-86.249" in cable and "12.111" in cable and "-86.2485" in cable                                                   # the drop starts at the new end and still ends on the client
        assert len(consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'cliente' AND borrado_en IS NULL")) == 1
        assert await p.errores() == []


def test_editing_a_budget_route_shows_its_numbers_and_what_will_be_deleted(mundo):
    asyncio.run(_recorrido(mundo))


async def _icono_del_cliente(mundo):
    con, lectura, admin = mundo
    r = lugares_presupuesto.guardar_ruta(con, admin, nombre="C23839_Constructores Unidos", puntos=RUTA, cliente=CLIENTE, postes_nuevos=POSTES)
    cliente_id = lectura.execute("SELECT id FROM redes.lugares_elementos WHERE tipo = 'cliente' AND borrado_en IS NULL").fetchone()["id"]
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo && window.MisLugares.estado.elementos >= 5", 20)
        await p.evaluar("window.MisLugares.editar(%d); true" % cliente_id)
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
        assert await p.evaluar("document.getElementById('ml-d-icono').hidden") is False                        # the icon of a network point can be changed
        assert await p.evaluar("document.getElementById('ml-d-icono-reset').hidden") is True
        await p.evaluar("document.getElementById('ml-d-icono').click(); true")
        await p.esperar("document.getElementById('ml-iconos') && !document.getElementById('ml-iconos').hidden", 5)
        await p.evaluar("[...document.querySelectorAll('#ml-iconos-rejilla [data-ic]')].find((b) => JSON.parse(b.dataset.ic).id === 'cuadrado').click(); document.querySelector('[data-ml-ic=aceptar]').click(); true")
        await p.esperar("!document.getElementById('ml-d-icono-reset').hidden", 5)                             # now it is the user's: a way back to the type's icon
        await p.evaluar("document.getElementById('ml-d-form').requestSubmit()")
        await p.esperar("!document.getElementById('ml-dialogo') || document.getElementById('ml-dialogo').hidden", 10)
        await asyncio.sleep(0.5)
        estilo = lectura.execute("SELECT estilo FROM redes.lugares_elementos WHERE id = %s", (cliente_id,)).fetchone()["estilo"]
        assert estilo["icono"]["id"] == "cuadrado" and estilo["icono"]["personalizado"] is True
        # opened again, «Del tipo» brings back the diamond of the client
        await p.evaluar("window.MisLugares.editar(%d); true" % cliente_id)
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden && !document.getElementById('ml-d-icono-reset').hidden", 10)
        await p.evaluar("document.getElementById('ml-d-icono-reset').click(); document.getElementById('ml-d-form').requestSubmit(); true")
        await asyncio.sleep(0.8)
        estilo = lectura.execute("SELECT estilo FROM redes.lugares_elementos WHERE id = %s", (cliente_id,)).fetchone()["estilo"]
        assert estilo["icono"]["id"] == "rombo" and not estilo["icono"].get("personalizado")
        assert await p.errores() == []


def test_the_icon_of_the_saved_client_can_be_changed_and_restored(mundo):
    asyncio.run(_icono_del_cliente(mundo))
