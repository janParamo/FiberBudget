"""La ventana «Planificación» del visor: el menú, el marco con la app /planificacion/ y dónde la encuentra (servicio de este equipo o servidor)."""
import json

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import hay_edge, pagina_edge


def test_where_the_planning_app_is_in_each_mode(monkeypatch):
    import visor_api
    from visor_rutas import config_visor
    from visor_rutas.ventana_web import Api
    api = Api()
    # server mode: the server and the key of the configuration (or what is missing)
    api._modo = "remoto"
    api._config = config_visor.ConfigVisor(modo="remoto", url="https://servidor.example", clave="k-remota")
    assert api.planificacion_acceso() == {"ok": True, "url": "https://servidor.example", "clave": "k-remota", "modo": "remoto"}
    api._config = config_visor.ConfigVisor(modo="remoto", url="https://servidor.example", clave="")
    assert api.planificacion_acceso()["ok"] is False and "Configuración" in api.planificacion_acceso()["error"]
    # local mode: this computer's service; without it, the way to start it
    api._modo = "local"
    monkeypatch.setattr(visor_api, "claves_visor", lambda: {"k-otra": "otra", "k-yo": __import__("getpass").getuser()})
    from visor_rutas import ventana_web
    ajustes = ventana_web.get_settings()
    monkeypatch.setattr(ventana_web, "get_settings", lambda: type("A", (), {"api_host": "0.0.0.0", "api_port": 9})())          # nothing listens on port 9
    r = api.planificacion_acceso()
    assert r["ok"] is False and "start_service.bat" in r["error"]
    # with the service answering: the key of this Windows user
    import urllib.request

    class Respuesta:
        def close(self):
            pass
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Respuesta())
    r = api.planificacion_acceso()
    assert r == {"ok": True, "url": "http://127.0.0.1:9", "clave": "k-yo", "modo": "local"}
    monkeypatch.setattr(visor_api, "claves_visor", lambda: {"k-yo": __import__("getpass").getuser(), "k-plan": "Planificacion"})
    assert api.planificacion_acceso()["clave"] == "k-plan"                                    # the person «planificacion» comes first
    monkeypatch.setattr(visor_api, "claves_visor", lambda: {"k-yo": __import__("getpass").getuser(), "k-jan": "janPlanificacion", "k-otra": "otra"})
    assert api.planificacion_acceso()["clave"] == "k-jan"                                     # a name that has «planificacion» comes before this Windows user
    monkeypatch.setattr(visor_api, "claves_visor", lambda: {"k-otra": "otra"})
    assert api.planificacion_acceso()["clave"] == "k-otra"                                    # none is this user's: the first one
    assert ajustes is not None


pytestmark_edge = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


@pytestmark_edge
def test_the_window_is_in_the_menu_and_shows_the_app_or_why_it_cannot():
    import asyncio

    async def recorrido():
        async with pagina_edge(1366, 768) as p:
            await p.esperar("window.visor && document.querySelector('[data-vista=planificacion]')", 20)
            await p.evaluar("window.__stubs.planificacion_acceso = () => ({ok: false, error: 'El servicio no responde en http://127.0.0.1:8000: abra start_service.bat y vuelva a intentar'}); true")
            await p.evaluar("document.querySelector('[data-vista=planificacion]').click(); true")
            await p.esperar("!document.getElementById('vista-planificacion').hidden && !document.getElementById('plan-error').hidden", 10)
            assert "start_service.bat" in await p.evaluar("document.getElementById('plan-error').textContent")
            assert await p.evaluar("document.getElementById('plan-marco').hidden") is True
            # the service answers: the frame points at /planificacion/ with the key in the address
            await p.evaluar("window.__stubs.planificacion_acceso = () => ({ok: true, url: 'http://127.0.0.1:8123', clave: 'k 1&2', modo: 'local'}); true")
            await p.evaluar("document.getElementById('plan-recargar').click(); true")
            await p.esperar("!document.getElementById('plan-marco').hidden", 10)
            assert await p.evaluar("document.getElementById('plan-marco').getAttribute('src')") == "http://127.0.0.1:8123/planificacion/#clave=k%201%262"
            assert await p.evaluar("document.getElementById('plan-nota').textContent") == "http://127.0.0.1:8123"
            # the budget window has the button that takes a budget to planning
            assert await p.evaluar("document.getElementById('vp-llevar-plan').textContent") == "Llevar a planificación"
            # going to another window and coming back does not load it again
            await p.evaluar("document.querySelector('[data-vista=mapa]').click(); true")
            await p.evaluar("window.__stubs.planificacion_acceso = () => { window.__otra = 1; return {ok: true, url: 'http://x', clave: ''}; }; true")
            await p.evaluar("document.querySelector('[data-vista=planificacion]').click(); true")
            assert await p.evaluar("window.__otra === undefined") is True
            assert await p.errores() == []

    asyncio.run(recorrido())


def test_the_exe_opens_the_planning_without_the_service_modules(monkeypatch):
    """VisorRutas.exe (remote mode only) does not carry visor_api: Planificación must not import it to answer where the planning app is (it did, and the window said ModuleNotFoundError)."""
    import sys

    from visor_rutas import config_visor
    from visor_rutas.ventana_web import Api
    monkeypatch.setitem(sys.modules, "visor_api", None)                 # an import of it now raises ImportError, as inside the .exe
    api = Api()
    api._modo = "remoto"
    api._config = config_visor.ConfigVisor(modo="remoto", url="https://servidor.example", clave="k-remota")
    assert api.planificacion_acceso() == {"ok": True, "url": "https://servidor.example", "clave": "k-remota", "modo": "remoto"}
