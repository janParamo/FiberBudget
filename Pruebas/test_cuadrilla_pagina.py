"""App de la cuadrilla (visor_rutas/cuadrilla_web/*, GET /cuadrilla/): la sirve la misma API y, en un Edge de verdad con el tamaño de un teléfono y GPS simulado,
un técnico entra con su clave, ve su cola, empieza la revisión y el trabajo, marca los puntos de control, no puede terminar con obligatorios sin marcar y termina."""
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
from test_campo_pwa import LAT, LON, mundo, servidor_real, websockets  # noqa: F401
from test_planificacion import sembrar_cuadrillas
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import planificacion as pl, usuarios


def test_the_page_and_its_files_are_served_but_nothing_else(mundo):
    _, c, _ = mundo
    redirigida = c.get("/cuadrilla", follow_redirects=False)
    assert redirigida.status_code == 307 and redirigida.headers["location"] == "/cuadrilla/"
    r = c.get("/cuadrilla/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and '<base href="/cuadrilla/">' in r.text
    for archivo, tipo in (("cuadrilla.js", "javascript"), ("cuadrilla.css", "css"), ("sw.js", "javascript"), ("manifest.webmanifest", "manifest+json"), ("icono-192.png", "png"),
                          ("icono-512.png", "png"), ("icono-apple.png", "png")):
        r = c.get(f"/cuadrilla/{archivo}")
        assert r.status_code == 200 and tipo in r.headers["content-type"], archivo
    for malo in ("../../.env", "..%2f..%2f.env", "%2e%2e/main.py", "lib/leaflet/leaflet.js.map", "no_existe.js", "C:/Windows/win.ini", "../planificacion_web/planificacion.js"):
        assert c.get(f"/cuadrilla/{malo}").status_code == 404, malo
    assert c.get("/planificacion/planificacion.js").status_code == 200                              # the other app still works


def test_the_page_is_off_when_there_is_no_key_of_any_kind(mundo, monkeypatch):
    _, c, _ = mundo
    monkeypatch.setenv("VISOR_API_KEYS", "")
    monkeypatch.setenv("CAMPO_API_KEYS", "")
    assert c.get("/cuadrilla", follow_redirects=False).status_code == 404 and c.get("/cuadrilla/").status_code == 404


@contextlib.asynccontextmanager
async def movil(puerto, cdp=9361):
    perfil = tempfile.mkdtemp(prefix="edge_cuadrilla_")
    proceso = subprocess.Popen([str(ruta_edge()), "--headless=new", f"--remote-debugging-port={cdp}", "--window-size=390,800", f"--user-data-dir={perfil}",
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
            await p.enviar("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=2, mobile=True)
            await p.enviar("Browser.grantPermissions", permissions=["geolocation"], origin=f"http://127.0.0.1:{puerto}")
            await p.enviar("Emulation.setGeolocationOverride", latitude=LAT, longitude=LON, accuracy=5)
            await p.enviar("Page.navigate", url=f"http://127.0.0.1:{puerto}/cuadrilla/")
            await p.esperar("document.readyState === 'complete' && window.Cuadrilla", 30)
            yield p
            tarea.cancel()
    finally:
        proceso.terminate()
        try:
            proceso.wait(10)
        except Exception:
            proceso.kill()
        shutil.rmtree(perfil, ignore_errors=True)


async def _recorrido(puerto, con, id_):
    async with movil(puerto) as p:
        assert await p.evaluar("!document.getElementById('pantalla-clave').hidden") is True
        await p.evaluar("document.getElementById('clave').value = 'mala'; document.getElementById('clave-entrar').click(); true")
        await p.esperar("!document.getElementById('clave-error').hidden", 10)
        await p.evaluar("localStorage.setItem('cuadrilla.clave', 'clave-tecnico-juan'); location.reload(); true")
        await p.esperar("document.readyState === 'complete' && document.querySelectorAll('.tarjeta').length === 1", 20)
        assert await p.evaluar("document.getElementById('nombre-cuadrilla').textContent") == "Tamos 1"
        texto = await p.evaluar("document.getElementById('contenido').innerText")
        assert "Casa Pérez" in texto and "8599 9439" in texto and "Cómo llegar" in texto and "Asignado" in texto
        assert await p.evaluar("document.querySelector('#contenido a[href^=tel]').getAttribute('href')") == "tel:8599 9439"
        # the location of the crew reaches planning
        await p.esperar("document.getElementById('gps').textContent === 'GPS ✓'", 15)
        for _ in range(40):
            if con.execute("SELECT 1 FROM redes.campo_ubicaciones").fetchone():
                break
            await asyncio.sleep(0.25)
        assert con.execute("SELECT ST_Y(ubicacion) AS lat FROM redes.campo_ubicaciones").fetchone()["lat"] == pytest.approx(LAT, abs=0.001)
        # review first: the control points appear; «Llegó al lugar» is marked with the place
        await p.evaluar("document.querySelector('[data-a=en_revision]').click(); true")
        await p.esperar("document.querySelectorAll('[data-control]').length === 6", 15)
        await p.evaluar("document.querySelector('[data-control=llegada]').click(); true")
        await p.esperar("document.querySelector('[data-control=llegada]').classList.contains('hecho')", 15)
        assert con.execute("SELECT ST_Y(ubicacion) AS lat FROM redes.plan_actividad_control WHERE actividad_id = %s AND clave = 'llegada'", (id_,)).fetchone()["lat"] == pytest.approx(LAT, abs=0.001)
        # start the work; cannot finish with required control points missing
        await p.evaluar("document.querySelector('[data-a=en_curso]').click(); true")
        await p.esperar("document.querySelector('.tarjeta.actual') !== null", 15)
        assert "En curso" in await p.evaluar("document.querySelector('.tarjeta.actual').innerText")
        await p.evaluar("document.querySelector('[data-a=terminado]').click(); true")
        await p.esperar("!document.getElementById('aviso').hidden", 15)
        assert "Faltan puntos de control" in await p.evaluar("document.getElementById('aviso').textContent")
        for clave in ("inspeccion", "acometida", "equipos_cliente", "fusiones"):
            await p.evaluar(f"document.querySelector('[data-control={clave}]').click(); true")
            await p.esperar(f"document.querySelector('[data-control={clave}]').classList.contains('hecho')", 15)
        await p.evaluar("document.querySelector('[data-a=terminado]').click(); true")
        await p.esperar("document.querySelector('.vacio') !== null", 15)
        assert "No tiene actividades" in await p.evaluar("document.getElementById('contenido').innerText")
        assert await p.errores() == []


@pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")
def test_a_crew_works_an_activity_from_its_phone(mundo, monkeypatch):
    main_, c, con = mundo
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:clave-tecnico-juan")
    sembrar_cuadrillas(con)
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'maria'")
    plan = usuarios.identificar(con, persona_visor="maria")
    juan = usuarios.identificar(con, persona_visor="juan", rol_inicial="tecnico")
    tamos = con.execute("SELECT id FROM redes.plan_cuadrillas WHERE nombre = 'Tamos 1'").fetchone()["id"]
    pl.agregar_miembro(con, admin, cuadrilla_id=tamos, usuario_id=juan["id"])
    i = pl.crear_actividad(con, plan, cliente_nombre="Casa Pérez", lat=LAT, lon=LON, ticket="XKJ-1", contacto_nombre="Grace", contacto_telefono="8599 9439")["id"]
    pl.asignar(con, plan, ids=[i], cuadrilla_id=tamos)
    with servidor_real(main_.app) as puerto:
        asyncio.run(_recorrido(puerto, con, i))
    d = pl.actividad(con, plan, id=i)["actividad"]
    assert d["estado"] == "terminado" and d["iniciada_por"] == "cuadrilla" and d["avance"]["hechos"] == 5 and d["ejecucion_s"] is not None
    assert [h["a"] for h in d["historial"]] == ["inactivo", "asignado", "en_revision", "en_curso", "terminado"]
