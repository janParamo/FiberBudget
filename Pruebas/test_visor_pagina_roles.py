"""La pantalla según el rol (página real, Edge sin ventana, base desechable): un guest solo ve el mapa y los presupuestos; un administrador no toca a los administradores y el
super administrador sí. El servidor aplica lo mismo (test_roles.py): esto prueba que el menú y la vista de Usuarios lo reflejan."""
import asyncio

import pytest

from arnes_pagina import hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

SIN_ACCESO = ["proyectos", "campo", "tickets", "planificacion", "problemas", "pendientes", "migracion", "usuarios", "backup"]


def _crear(con, nombre, rol):
    con.execute("INSERT INTO redes.usuarios (nombre, rol, usuario_windows) VALUES (%s, %s, %s)", (nombre, rol, nombre))


async def _guest(con):
    async with pagina_edge(1366, 768, con=con, usuario="guest") as p:
        await p.esperar("window.Redes && window.Redes.iniciado && window.Redes.rol === 'guest'", 20)
        cerrados = await p.evaluar("[...document.querySelectorAll('#menu-lateral .menu-item[aria-disabled=\"true\"]')].map((b) => b.dataset.vista)")
        abiertos = await p.evaluar("[...document.querySelectorAll('#menu-lateral .menu-item:not([aria-disabled=\"true\"])')].map((b) => b.dataset.vista)")
        assert sorted(SIN_ACCESO) == sorted(v for v in cerrados if v in SIN_ACCESO) and "mapa" in abiertos and "presupuesto" in abiertos and "configuracion" in abiertos
        assert not set(abiertos) & set(SIN_ACCESO)
        assert await p.evaluar("document.body.classList.contains('es-guest')") is True
        assert await p.evaluar("getComputedStyle(document.querySelector('.barra-herramientas')).display") == "none"           # no drawing tools
        assert await p.evaluar("window.MisLugares.estado.listo") is False                                                      # no Mis lugares for a guest
        assert "Guest" in await p.evaluar("document.querySelector('#menu-usuario .menu-pie-texto').textContent")
        assert await p.errores() == []


async def _usuarios(con, usuario, esperado):
    async with pagina_edge(1366, 768, con=con, usuario=usuario) as p:
        await p.esperar("window.Redes && window.Redes.iniciado && window.Redes.rol", 20)
        await p.evaluar("document.querySelector('[data-vista=usuarios]').click(); true")
        await p.esperar("document.querySelectorAll('#us-filas tr').length >= 4", 10)
        filas = await p.evaluar("Object.fromEntries([...document.querySelectorAll('#us-filas tr')].map((f) => [f.querySelector('b').textContent, f.querySelectorAll('[data-us-editar]').length]))")
        assert filas == esperado, filas
        await p.evaluar("(() => { const b = document.querySelector('[data-us-editar]'); if (b) b.click(); else document.getElementById('us-nuevo').click(); return true; })()")
        opciones = await p.evaluar("Object.fromEntries([...document.getElementById('us-rol').options].map((o) => [o.value, o.disabled]))")
        assert set(opciones) == {"lector", "editor", "administrador", "super_administrador", "tecnico", "guest", "prueba"}
        assert (opciones["administrador"], opciones["super_administrador"]) == ((False, False) if usuario == "jan" else (True, True))
        assert await p.errores() == []


async def _recorrido(con):
    for n, r in (("jan", "super_administrador"), ("marlon", "administrador"), ("ana", "editor"), ("guest", "guest")):
        _crear(con, n, r)
    await _guest(con)
    # an administrator sees everyone but only has buttons on the ones that are not administrators; the super administrator has them on all
    await _usuarios(con, "marlon", {"ana": 1, "guest": 1, "jan": 0, "marlon": 0})
    await _usuarios(con, "jan", {"ana": 1, "guest": 1, "jan": 1, "marlon": 1})


def test_the_screen_follows_the_role(con_redes):
    asyncio.run(_recorrido(con_redes))
