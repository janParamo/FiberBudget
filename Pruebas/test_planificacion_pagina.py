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
    from visor_rutas import campo_eventos
    sembrar_cuadrillas(con)
    con.execute("UPDATE redes.usuarios SET rol = 'administrador' WHERE persona_visor = 'jan'")                 # an administrator: he also puts technicians in the crews
    from visor_rutas.redes import usuarios
    jan = usuarios.identificar(con, persona_visor="jan")
    juan = usuarios.identificar(con, persona_visor="juan", rol_inicial="tecnico")
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
        # live notices: what planning creates somewhere else shows up in a moment (not after the 15 s refresh)
        await p.esperar("document.getElementById('vivo').textContent.includes('en vivo')", 15)
        assert campo_eventos.escucha("planificacion").conectado.wait(10)                                            # the server is listening to the database
        otra = pl.crear_actividad(con, jan, cliente_nombre="Creada por otro", lat=12.15, lon=-86.27, ticket="T-OTRO")["id"]
        await p.esperar("[...document.querySelectorAll('#tabla tbody tr td.cliente b')].some((e) => e.textContent === 'Creada por otro')", 8)
        con.execute("UPDATE redes.plan_actividades SET borrado_en = now() WHERE id = %s", (otra,))                # it is not part of the rest of the test
        await p.evaluar("document.getElementById('buscar').dispatchEvent(new Event('input')); true")
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
        await p.esperar("document.querySelector('#detalle [data-a=en_curso]') !== null", 15)                      # the detail is drawn again a moment after the table
        await p.evaluar("document.querySelector('#detalle [data-a=en_curso]').click(); true")
        await p.esperar("document.querySelector('#tabla tbody tr td:nth-child(4)').textContent.includes('En curso')", 15)
        assert "plan." in await p.evaluar("document.querySelector('#tabla tbody tr td:nth-child(4)').textContent")
        # a control point marked from planning moves the progress
        await p.esperar("document.querySelector('#detalle [data-control=llegada]') !== null", 15)               # the detail is drawn again a moment after the table
        await p.evaluar("document.querySelector('#detalle [data-control=llegada]').click(); true")
        await p.esperar("document.querySelector('#tabla tbody tr td:nth-child(8)').textContent.trim() === '1/6'", 15)
        # the chat of the activity: what the crew writes shows up live, and planning answers from the panel
        id_actividad = con.execute("SELECT id FROM redes.plan_actividades WHERE ticket = 'XKJ-1'").fetchone()["id"]
        con.execute("INSERT INTO redes.plan_mensajes (actividad_id, de_usuario, de_origen, texto) VALUES (%s, %s, 'cuadrilla', 'Ya llegamos al sitio')", (id_actividad, juan["id"]))
        await p.esperar("document.getElementById('chat-lista').innerText.includes('Ya llegamos al sitio')", 10)
        await p.evaluar("(() => { const c = document.getElementById('chat-texto'); c.value = 'Perfecto, marquen la llegada'; document.getElementById('chat-form').requestSubmit(); return true; })()")
        await p.esperar("document.getElementById('chat-lista').innerText.includes('Perfecto, marquen la llegada') && document.getElementById('chat-texto').value === ''", 10)
        assert con.execute("SELECT count(*) AS n FROM redes.plan_mensajes WHERE actividad_id = %s AND de_origen = 'planificacion'", (id_actividad,)).fetchone()["n"] == 1
        # the clock keeps running in the page
        await p.esperar("document.querySelector('[data-reloj]') !== null", 5)
        # the tray of Kayako tickets: the pending ones are listed (the badge counts them) and an activity is made from a ticket with no budget
        await p.esperar("document.getElementById('kayako-n').textContent === '2'", 15)
        await p.evaluar("document.querySelector('[data-vista=kayako]').click(); true")
        await p.esperar("document.querySelectorAll('#tabla-kayako tbody tr[data-ticket]').length === 2", 10)
        assert "Ferretería Luna" in await p.evaluar("document.querySelector('#tabla-kayako tbody').innerText") and "Elba Soto" in await p.evaluar("document.querySelector('#tabla-kayako tbody').innerText")
        await p.evaluar("document.querySelector('[data-crear-ticket=\"FMO-311-48543\"]').click(); true")
        await p.esperar("document.querySelector('#tabla-kayako tr[data-ticket=\"FMO-311-48543\"] .etiqueta') !== null", 15)
        assert con.execute("SELECT origen, cliente_nombre, estado FROM redes.plan_actividades WHERE ticket = 'FMO-311-48543'").fetchone() == {"origen": "kayako", "cliente_nombre": "Ferretería Luna", "estado": "inactivo"}
        assert await p.evaluar("document.getElementById('kayako-n').textContent") == "1"                                  # one ticket left to plan
        # the map has the activity; the crews tab lists the six crews
        await p.evaluar("document.querySelector('[data-vista=mapa]').click(); true")
        await p.esperar("document.querySelectorAll('#mapa .leaflet-interactive').length >= 1", 10)
        await p.evaluar("document.querySelector('[data-vista=cuadrillas]').click(); true")
        assert await p.evaluar("document.querySelectorAll('#lista-cuadrillas .tarjeta').length") == 6
        # two more activities wait in the queue of Tamos 1: the rows can be moved (arrows; the rows are also draggable)
        tamos = con.execute("SELECT id FROM redes.plan_cuadrillas WHERE nombre = 'Tamos 1'").fetchone()["id"]
        a = pl.crear_actividad(con, jan, cliente_nombre="Uno", lat=12.13, lon=-86.25, ticket="T-1")["id"]
        b = pl.crear_actividad(con, jan, cliente_nombre="Dos", lat=12.14, lon=-86.26, ticket="T-2")["id"]
        pl.asignar(con, jan, ids=[a, b], cuadrilla_id=tamos)
        await p.evaluar("document.getElementById('buscar').dispatchEvent(new Event('input')); true")
        await p.evaluar("window.Planificacion._st.arrastrando = false; true")
        await p.esperar("document.querySelectorAll('#lista-cuadrillas .cola li').length === 2", 30)                  # the next refresh draws them
        orden = "[...document.querySelectorAll('#lista-cuadrillas .cola li b')].map((e) => e.textContent)"
        assert await p.evaluar(orden) == ["Uno", "Dos"]
        await p.evaluar("document.querySelectorAll('#lista-cuadrillas [data-sube]')[1].click(); true")                # «Dos» goes up
        await p.esperar(orden + ".join() === 'Dos,Uno'", 15)
        assert [x["cliente_nombre"] for x in pl.actividades(con, jan, cuadrilla_id=tamos)["actividades"] if x["estado"] == "asignado"] == ["Dos", "Uno"]
        # a technician is put in a crew from the list and taken out again
        await p.evaluar("(() => { const s = document.querySelector('#lista-cuadrillas [data-agregar-select]'); s.value = [...s.options].find((o) => o.text.startsWith('juan')).value; "
                        "document.querySelector('#lista-cuadrillas [data-agregar]').click(); return true; })()")
        await p.esperar("document.querySelectorAll('#lista-cuadrillas [data-quitar-miembro]').length === 1", 15)
        assert con.execute("SELECT count(*) AS n FROM redes.plan_cuadrilla_miembros WHERE usuario_id = %s", (juan["id"],)).fetchone()["n"] == 1
        await p.evaluar("document.querySelector('#lista-cuadrillas [data-quitar-miembro]').click(); true")
        await p.esperar("document.querySelectorAll('#lista-cuadrillas [data-quitar-miembro]').length === 0", 15)
        assert await p.errores() == []


servidor_real_puerto = 0


@pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")
def test_planning_in_a_real_browser(mundo, base_redes, monkeypatch):
    global servidor_real_puerto
    main_, c, con = mundo
    from test_planificacion import ticket_kayako
    from visor_rutas import campo_eventos, kayako
    from visor_rutas.redes import db
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    monkeypatch.setattr(kayako, "vista_previa", lambda dias=None, limite=50, abrir=None: [ticket_kayako(), ticket_kayako("SZC-554-70181", coordenadas=[])])      # Kayako is not read in the tests
    _, params = base_redes
    monkeypatch.setitem(campo_eventos._otras, "planificacion", campo_eventos.Escucha(lambda: db.conectar(params=params), "planificacion"))      # the live notices of the test database
    with servidor_real(main_.app) as puerto:
        servidor_real_puerto = puerto
        asyncio.run(_recorrido(main_, con))
    jan = con.execute("SELECT * FROM redes.usuarios WHERE persona_visor = 'jan'").fetchone()
    assert sorted(x["estado"] for x in pl.actividades(con, jan)["actividades"]) == ["asignado", "asignado", "en_curso", "inactivo"]
