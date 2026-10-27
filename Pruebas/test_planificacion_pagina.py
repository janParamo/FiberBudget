"""App de planificación (visor_rutas/planificacion_web/*, GET /planificacion/): la sirve la misma API (con las mismas reglas que la de campo) y, en un Edge de
verdad contra el servicio real y la base de prueba, planificación entra con su clave, crea una actividad, la asigna, la ve avanzar y cambia su estado."""
import asyncio
import contextlib
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import Pagina, hay_edge, ruta_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo_pwa import _puerto_libre, mundo, servidor_real, websockets  # noqa: F401
from test_planificacion import sembrar_cuadrillas
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import planificacion as pl


def test_the_page_and_its_files_are_served_but_nothing_else(mundo):
    _, c, _ = mundo
    redirigida = c.get("/planificacion", follow_redirects=False)
    assert redirigida.status_code == 307 and redirigida.headers["location"] == "/planificacion/"
    r = c.get("/planificacion/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and '<base href="/planificacion/">' in r.text
    for archivo, tipo in (("planificacion.js", "javascript"), ("planificacion.css", "css"), ("lib/leaflet/leaflet.js", "javascript"), ("lib/leaflet/leaflet.css", "css"),
                          ("lib/leaflet/images/marker-icon.png", "png")):
        r = c.get(f"/planificacion/{archivo}")
        assert r.status_code == 200 and tipo in r.headers["content-type"], archivo
    for malo in ("../../.env", "..%2f..%2f.env", "lib/leaflet/../../../.env", "%2e%2e/main.py", "lib/leaflet/LICENSE", "no_existe.js", "C:/Windows/win.ini"):
        assert c.get(f"/planificacion/{malo}").status_code == 404, malo


def test_the_page_is_off_when_there_is_no_key_of_any_kind(mundo, monkeypatch):
    _, c, _ = mundo
    monkeypatch.setenv("VISOR_API_KEYS", "")
    monkeypatch.setenv("CAMPO_API_KEYS", "")
    assert c.get("/planificacion", follow_redirects=False).status_code == 404 and c.get("/planificacion/").status_code == 404


@contextlib.asynccontextmanager
async def escritorio(puerto, cdp=9351):
    perfil = tempfile.mkdtemp(prefix="edge_plan_")
    proceso = subprocess.Popen([str(ruta_edge()), "--headless=new", f"--remote-debugging-port={cdp}", "--window-size=1500,900", f"--user-data-dir={perfil}",
                                "--no-first-run", "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                destino = next(o for o in json.load(urllib.request.urlopen(f"http://127.0.0.1:{cdp}/json")) if o["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Edge no arrancó")
        async with websockets.connect(destino["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
            p = Pagina(ws)
            tarea = asyncio.create_task(p._leer())
            for dominio in ("Page", "Runtime"):
                await p.enviar(f"{dominio}.enable")
            await p.enviar("Emulation.setDeviceMetricsOverride", width=1500, height=900, deviceScaleFactor=1, mobile=False)
            await p.enviar("Page.navigate", url=f"http://127.0.0.1:{puerto}/planificacion/")
            await p.esperar("document.readyState === 'complete' && window.Planificacion", 30)
            yield p
            tarea.cancel()
    finally:
        proceso.terminate()
        try:
            proceso.wait(10)
        except Exception:
            proceso.kill()
        shutil.rmtree(perfil, ignore_errors=True)


async def _recorrido(main_, con):
    sembrar_cuadrillas(con)
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'jan'")
    async with escritorio(servidor_real_puerto) as p:
        # without a key: the key screen; with a wrong one: it says so
        assert await p.evaluar("!document.getElementById('pantalla-clave').hidden && document.getElementById('app').hidden") is True
        await p.evaluar("document.getElementById('clave').value = 'mala'; document.getElementById('clave-entrar').click(); true")
        await p.esperar("!document.getElementById('clave-error').hidden", 10)
        assert "clave" in await p.evaluar("document.getElementById('clave-error').textContent")
        await p.evaluar("localStorage.setItem('planificacion.clave', 'clave-jan'); location.reload(); true")
        try:
            await p.esperar("document.readyState === 'complete' && !document.getElementById('app').hidden && document.querySelectorAll('.cuadrilla').length === 6", 20)
        except TimeoutError:
            raise AssertionError(await p.evaluar("JSON.stringify({con: document.getElementById('estado-conexion').textContent, clave: document.getElementById('clave-error').textContent, "
                                                 "app: document.getElementById('app').hidden, n: document.querySelectorAll('.cuadrilla').length})") + " " + str(await p.errores()))
        assert await p.evaluar("[...document.querySelectorAll('.grupo-empresa')].map((e) => e.textContent)") == ["Tamos", "Telenic", "IDEAY (propia)"]
        assert await p.evaluar("document.querySelectorAll('#tablero .carta').length") == 10                      # 8 states + two averages
        # a new activity by hand
        await p.evaluar("document.getElementById('nueva-actividad').click(); true")
        await p.evaluar("(() => { const f = document.getElementById('form-nueva'); f.cliente_nombre.value = 'Casa Pérez'; f.ticket.value = 'XKJ-1'; f.contacto_nombre.value = 'Grace';"
                        " f.contacto_telefono.value = '8599 9439'; f.coordenada.value = '12.1364, -86.2514'; f.requestSubmit(); return true; })()")
        await p.esperar("document.querySelectorAll('#tabla tbody tr[data-id]').length === 1 && !document.getElementById('detalle').hidden", 15)
        assert "Casa Pérez" in await p.evaluar("document.getElementById('detalle').innerText") and "8599 9439" in await p.evaluar("document.getElementById('detalle').innerText")
        # assign it from the detail
        await p.evaluar("(() => { const s = document.getElementById('det-cuadrilla'); s.value = [...s.options].find((o) => o.text === 'Tamos 1').value; "
                        "document.querySelector('[data-asignar-detalle]').click(); return true; })()")
        await p.esperar("document.querySelector('#tabla tbody tr td:nth-child(5)').textContent === 'Tamos 1'", 15)
        assert "Asignado" in await p.evaluar("document.querySelector('#tabla tbody tr td:nth-child(4)').textContent")
        # planning starts the clock; the state and who started it show
        await p.evaluar("document.querySelector('#detalle [data-a=en_curso]').click(); true")
        await p.esperar("document.querySelector('#tabla tbody tr td:nth-child(4)').textContent.includes('En curso')", 15)
        assert "plan." in await p.evaluar("document.querySelector('#tabla tbody tr td:nth-child(4)').textContent")
        # a control point marked from planning moves the progress
        await p.esperar("document.querySelector('#detalle [data-control=llegada]') !== null", 15)               # the detail is drawn again a moment after the table
        await p.evaluar("document.querySelector('#detalle [data-control=llegada]').click(); true")
        await p.esperar("document.querySelector('#tabla tbody tr td:nth-child(8)').textContent.trim() === '1/6'", 15)
        # the clock keeps running in the page
        await p.esperar("document.querySelector('[data-reloj]') !== null", 5)
        # the map has the activity; the crews tab lists the six crews
        await p.evaluar("document.querySelector('[data-vista=mapa]').click(); true")
        await p.esperar("document.querySelectorAll('#mapa .leaflet-interactive').length >= 1", 10)
        await p.evaluar("document.querySelector('[data-vista=cuadrillas]').click(); true")
        assert await p.evaluar("document.querySelectorAll('#lista-cuadrillas .tarjeta').length") == 6
        assert await p.errores() == []


servidor_real_puerto = 0


@pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")
def test_planning_in_a_real_browser(mundo, monkeypatch):
    global servidor_real_puerto
    main_, c, con = mundo
    with servidor_real(main_.app) as puerto:
        servidor_real_puerto = puerto
        asyncio.run(_recorrido(main_, con))
    assert pl.actividades(con, con.execute("SELECT * FROM redes.usuarios WHERE persona_visor = 'jan'").fetchone())["actividades"][0]["estado"] == "en_curso"
