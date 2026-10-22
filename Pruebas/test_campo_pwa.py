"""App de campo, fase 2 (visor_rutas/campo_web/*, GET /campo): la página la sirve la misma API, y en un Edge de verdad (con GPS simulado) un técnico entra
con su clave, registra un punto con GPS y otro marcado en el mapa, con foto, y lo ve en la base y en su lista."""
import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import Pagina, hay_edge, ruta_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import _servicio, jpeg, usuarios  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)

try:
    import websockets
except ImportError:                                             # the browser tests are skipped without it
    websockets = None

LAT, LON = 12.1364, -86.2514
ANCHO, ALTO = int(os.environ.get("CAMPO_ANCHO", 390)), int(os.environ.get("CAMPO_ALTO", 800))          # a tablet: CAMPO_ANCHO=1024 CAMPO_ALTO=768


@pytest.fixture
def mundo(base_redes, con_redes, entorno, monkeypatch, tmp_path):
    main_, visor_api, cliente, _, _ = entorno
    monkeypatch.setenv("CAMPO_FOTOS_DIR", str(tmp_path / "fotos"))
    for nombre, rol in (("jan", "tecnico"), ("maria", "lector")):
        u = usuarios.identificar(con_redes, persona_visor=nombre)
        con_redes.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
    servicio = _servicio(base_redes)
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    import visor_rutas.campo_api as campo_api
    campo_api.limitador.reiniciar()
    yield main_, cliente, con_redes
    servicio.cerrar()


# ------------------------------------------------------------------ the page is served by the API

def test_the_page_and_its_files_are_served_without_a_key_but_nothing_else(mundo):
    _, c, _ = mundo
    redirigida = c.get("/campo", follow_redirects=False)
    assert redirigida.status_code == 307 and redirigida.headers["location"] == "/campo/"          # the service worker controls /campo/
    r = c.get("/campo/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and '<base href="/campo/">' in r.text and "Campo" in r.text
    for archivo, tipo in (("app.js", "javascript"), ("api.js", "javascript"), ("mapa.js", "javascript"), ("cola.js", "javascript"), ("ayuda.js", "javascript"), ("sw.js", "javascript"),
                          ("manifest.webmanifest", "manifest+json"), ("icono-192.png", "png"), ("icono-512.png", "png"), ("icono-apple.png", "png"), ("campo.css", "css"), ("lib/leaflet/leaflet.js", "javascript"),
                          ("lib/leaflet/leaflet.css", "css"), ("lib/leaflet/images/marker-icon.png", "png")):
        r = c.get(f"/campo/{archivo}")
        assert r.status_code == 200 and tipo in r.headers["content-type"], archivo
    # nothing outside the app: not the .env, not the code, not a folder
    for malo in ("../../.env", "..%2f..%2f.env", "lib/leaflet/../../../.env", "lib/leaflet/../../../main.py", "%2e%2e/main.py", "campo_api.py", "lib", "no_existe.js",
                 "C:/Windows/win.ini", "lib/leaflet/LICENSE"):
        assert c.get(f"/campo/{malo}").status_code == 404, malo


def test_the_page_is_off_when_the_remote_viewer_is(mundo, monkeypatch):
    main_, c, _ = mundo
    monkeypatch.setenv("VISOR_API_KEYS", "")
    assert c.get("/campo", follow_redirects=False).status_code == 404 and c.get("/campo/").status_code == 404 and c.get("/campo/app.js").status_code == 404


def test_the_config_tells_who_the_key_belongs_to(mundo):
    _, c, _ = mundo
    assert c.get("/visor/campo/config").status_code == 401
    r = c.get("/visor/campo/config", headers=JAN).json()
    assert r["ok"] and r["persona"] == "jan" and r["precision_max_m"] == 10 and r["duplicado_m"] == 5 and r["fotos_por_punto"] == 8


# ------------------------------------------------------------------ the page in a real browser, with a simulated GPS

def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def servidor_real(app):
    import uvicorn
    puerto = _puerto_libre()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning", lifespan="off"))
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    try:
        yield puerto
    finally:
        srv.should_exit = True
        hilo.join(10)


@contextlib.asynccontextmanager
async def telefono(puerto, precision=5.0, cdp=9341, ua=None):
    """Headless Edge sized like a phone, on /campo, with the GPS at (LAT, LON) with the accuracy given."""
    perfil = tempfile.mkdtemp(prefix="edge_campo_")
    proceso = subprocess.Popen([str(ruta_edge()), "--headless=new", f"--remote-debugging-port={cdp}", f"--window-size={ANCHO},{ALTO}", f"--user-data-dir={perfil}",
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
            await p.enviar("Emulation.setDeviceMetricsOverride", width=ANCHO, height=ALTO, deviceScaleFactor=2, mobile=True)
            await p.enviar("Network.enable")
            if ua:
                await p.enviar("Emulation.setUserAgentOverride", userAgent=ua)
            p.sin_red = lambda si: p.enviar("Network.emulateNetworkConditions", offline=si, latency=0, downloadThroughput=-1, uploadThroughput=-1)
            await p.enviar("Browser.grantPermissions", permissions=["geolocation"], origin=f"http://127.0.0.1:{puerto}")
            await p.enviar("Emulation.setGeolocationOverride", latitude=LAT, longitude=LON, accuracy=precision)
            await p.enviar("Page.navigate", url=f"http://127.0.0.1:{puerto}/campo/")
            await p.esperar("document.readyState === 'complete' && window.Campo", 30)
            p.gps = lambda lat, lon, acc: p.enviar("Emulation.setGeolocationOverride", latitude=lat, longitude=lon, accuracy=acc)
            yield p
            tarea.cancel()
    finally:
        proceso.terminate()
        try:
            proceso.wait(10)
        except Exception:
            proceso.kill()
        shutil.rmtree(perfil, ignore_errors=True)


async def esperar_sql(con, consulta, cuantos=1, segundos=30):
    """Waits until the query returns at least `cuantos` rows (the page saves to its queue first and sends in the background)."""
    t0 = time.time()
    while time.time() - t0 < segundos:
        filas = con.execute(consulta).fetchall()
        if len(filas) >= cuantos:
            return filas
        await asyncio.sleep(0.25)
    raise TimeoutError(consulta)


async def _entrar(p, clave):
    await p.evaluar(f"(() => {{ document.getElementById('clave').value = {json.dumps(clave)}; document.getElementById('clave-entrar').click(); return true; }})()")


async def _visible(p, id_):
    return await p.evaluar(f"!document.getElementById({json.dumps(id_)}).hidden")


async def _escribir(p, id_, valor):
    await p.evaluar(f"(() => {{ const e = document.getElementById({json.dumps(id_)}); e.value = {json.dumps(valor)}; e.dispatchEvent(new Event('input', {{bubbles: true}})); return true; }})()")


async def _tocar(p, selector):
    await p.evaluar(f"document.querySelector({json.dumps(selector)}).click(); true")


async def _captura(p, nombre):
    """Screenshots for looking at the app by eye: only when CAMPO_CAPTURAS names a folder."""
    carpeta = os.environ.get("CAMPO_CAPTURAS")
    if carpeta:
        await asyncio.sleep(0.5)
        await p.captura(Path(carpeta) / f"{nombre}.png")


async def _dialogo(p, texto):
    """Taps the button of the open dialog whose text contains `texto`."""
    await p.esperar("!document.getElementById('dialogo').hidden", 5)
    await p.evaluar(f"[...document.querySelectorAll('#dialogo button')].find((b) => b.textContent.includes({json.dumps(texto)})).click(); true")
    await asyncio.sleep(0.4)


async def _capturar_punto(p, tipo=None):
    """The + button, the type chip (if any) and OK: the point editor opens."""
    await _tocar(p, "#b-agregar")
    await p.esperar("document.body.classList.contains('capturando')", 5)
    if tipo:
        await _tocar(p, f"#cap-tipos [data-cap-tipo={tipo}]")
    await _tocar(p, "#cap-ok")
    await p.esperar("!document.getElementById('p-editor').hidden", 5)


async def _recorrido(puerto, con, tmp_path):
    foto = tmp_path / "foto.jpg"
    foto.write_bytes(jpeg(3000, 2000))                                       # a 3000 x 2000 photo, as a camera takes it
    async with telefono(puerto, precision=5.0) as p:
        # ---- the key: wrong, then a reader (no field role), then the technician's
        await p.esperar("!document.getElementById('pantalla-clave').hidden", 10)
        await _entrar(p, "mala")
        await p.esperar("document.getElementById('clave-error').textContent.includes('no es válida')", 10)
        await _entrar(p, "clave-maria")
        await p.esperar("document.getElementById('clave-error').textContent.includes('rol de técnico')", 10)
        assert not await _visible(p, "app")
        await _captura(p, "1_clave")
        await _entrar(p, "clave-jan")
        await p.esperar("!document.getElementById('app').hidden", 15)
        assert await p.evaluar("document.getElementById('persona').textContent") == "jan"
        assert "Jornada" in await p.evaluar("document.getElementById('jornada-nombre').textContent")
        # ---- the GPS shows its accuracy and is good enough (5 m <= 10 m)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±5')", 15)
        assert "buena" in await p.evaluar("document.getElementById('gps-estado').className")
        await _captura(p, "2_mapa")

        # ---- a pole with GPS and a photo: + , the crosshair on the GPS fix, OK
        await _tocar(p, "#b-agregar")
        await p.esperar("document.body.classList.contains('capturando') && !document.getElementById('mira').hidden", 5)
        assert "GPS ±5" in await p.evaluar("document.getElementById('cap-banner').textContent")
        await _captura(p, "3_capturando")
        await _tocar(p, "#cap-ok")
        await p.esperar("!document.getElementById('p-editor').hidden", 5)
        assert await p.evaluar("document.getElementById('ed-nombre').value") == "Poste 1"          # suggested name
        assert "GPS ±5 m" in await p.evaluar("document.getElementById('ed-coord').textContent")
        await p.evaluar("document.getElementById('ed-poste').value = 'concreto'; true")
        await _escribir(p, "ed-notas", "esquina de la pulpería")
        await p.subir_archivo("#ed-foto", foto)
        await p.esperar("document.querySelectorAll('#ed-fotos img').length === 1", 20)
        await _captura(p, "4_editor")
        await _tocar(p, "#ed-guardar")
        await p.esperar("document.getElementById('p-editor').hidden && document.getElementById('contador').textContent === '1'", 20)
        await esperar_sql(con, "SELECT 1 FROM redes.campo_fotos")                                   # saved in the phone first, sent in the background
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        fila = con.execute("SELECT * FROM redes.campo_puntos").fetchone()
        assert (fila["tipo"], fila["subtipo"], fila["nombre"], fila["notas"], fila["origen_coord"], fila["estado"]) == ("poste", "concreto", "Poste 1", "esquina de la pulpería", "gps", "pendiente")
        assert float(fila["precision_m"]) == pytest.approx(5.0, abs=0.5)
        fotos = con.execute("SELECT tamano FROM redes.campo_fotos WHERE punto_id = %s", (fila["id"],)).fetchall()
        assert len(fotos) == 1 and 0 < fotos[0]["tamano"] < foto.stat().st_size                      # compressed in the phone
        assert (await p.errores()) == []

        # ---- the position goes to the office (the app does it every 20 s; here on demand), and a rejection comes back with its reason
        assert await p.evaluar("Campo.enviarUbicacion()") is True
        u = con.execute("SELECT ST_Y(ubicacion) AS lat, precision_m FROM redes.campo_ubicaciones").fetchone()
        assert float(u["lat"]) == pytest.approx(LAT, abs=1e-5) and float(u["precision_m"]) == pytest.approx(5.0, abs=0.5)
        con.execute("UPDATE redes.campo_puntos SET estado = 'rechazado', motivo_rechazo = 'Está en un lote privado' WHERE tipo = 'poste'")
        con.execute("UPDATE redes.campo_puntos SET actualizado_en = now() WHERE tipo = 'poste'")
        await p.evaluar("Campo.cargarPuntos()")
        await _tocar(p, "#b-lista")
        await p.esperar("document.getElementById('l-cuerpo').textContent.includes('Rechazado: Está en un lote privado')", 10)
        await _tocar(p, "#l-atras")
        con.execute("UPDATE redes.campo_puntos SET estado = 'pendiente', motivo_rechazo = NULL, actualizado_en = now() WHERE tipo = 'poste'")
        await p.evaluar("Campo.cargarPuntos()")

        # ---- a bad signal: the banner warns; the crosshair is moved by hand, so the point is «marcado en el mapa»
        await p.gps(LAT + 0.0003, LON, 60.0)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±60')", 15)
        await _tocar(p, "#b-agregar")
        await p.esperar("document.body.classList.contains('capturando')", 5)
        await p.esperar("document.getElementById('cap-banner').textContent.includes('poco preciso') || document.getElementById('cap-banner').textContent.includes('±60')", 10)
        await _captura(p, "5_gps_debil")
        await _tocar(p, "#cap-tipos [data-cap-tipo=mufa]")
        await p.evaluar(f"CampoMapa.leaflet().setView([{LAT + 0.0009}, {LON}], 19, {{animate: false}}); true")
        await _tocar(p, "#cap-ok")
        await p.esperar("!document.getElementById('p-editor').hidden", 5)
        assert "marcado en el mapa" in await p.evaluar("document.getElementById('ed-coord').textContent")
        assert await p.evaluar("document.getElementById('ed-nombre').value") == "Mufa 1"
        await p.evaluar("document.getElementById('ed-mufa-capacidad').value = '48'; document.getElementById('ed-mufa-formato').value = 'domo'; true")
        await _tocar(p, "#ed-guardar")
        await p.esperar("document.getElementById('contador').textContent === '2'", 20)
        await esperar_sql(con, "SELECT 1 FROM redes.campo_puntos WHERE tipo = 'mufa'")
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        mufa = con.execute("SELECT * FROM redes.campo_puntos WHERE tipo = 'mufa'").fetchone()
        assert (mufa["subtipo"], mufa["origen_coord"], mufa["precision_m"], mufa["nombre"]) == ("48 domo", "mapa", None, "Mufa 1")

        # ---- cancelling the capture saves nothing
        await _tocar(p, "#b-agregar")
        await p.esperar("document.body.classList.contains('capturando')", 5)
        await _tocar(p, "#cap-cancelar")
        await p.esperar("!document.body.classList.contains('capturando')", 5)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 2

        # ---- the list: both points, edit the name of the pending pole, delete the mufa
        await _tocar(p, "#b-lista")
        await p.esperar("document.querySelectorAll('#l-cuerpo .fila-item').length === 2", 5)
        await _captura(p, "6_lista")
        assert await p.evaluar("[...document.querySelectorAll('#l-cuerpo .estado')].every((e) => e.textContent === 'Pendiente')") is True
        await p.evaluar("[...document.querySelectorAll('#l-cuerpo .fila-item')].find((li) => li.textContent.includes('Poste 1')).click(); true")
        await p.esperar("!document.getElementById('tarjeta').hidden && document.getElementById('t-titulo').textContent === 'Poste 1'", 5)
        await _captura(p, "7_tarjeta")
        await _tocar(p, "#t-editar")
        await p.esperar("!document.getElementById('p-editor').hidden", 5)
        await _escribir(p, "ed-nombre", "Poste esquina")
        await _tocar(p, "#ed-guardar")
        await p.esperar("document.getElementById('p-editor').hidden", 10)
        assert con.execute("SELECT nombre FROM redes.campo_puntos WHERE tipo = 'poste'").fetchone()["nombre"] == "Poste esquina"
        await _tocar(p, "#b-lista")
        await p.evaluar("[...document.querySelectorAll('#l-cuerpo .fila-item')].find((li) => li.textContent.includes('Mufa 1')).click(); true")
        await p.esperar("!document.getElementById('tarjeta').hidden", 5)
        await _tocar(p, "#t-mas")
        await _dialogo(p, "Eliminar")
        await _dialogo(p, "Eliminar")
        await p.esperar("document.getElementById('contador').textContent === '1'", 10)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos WHERE borrado_en IS NULL").fetchone()["n"] == 1

        # ---- closing the jornada
        await _tocar(p, "#b-menu")
        await p.esperar("!document.getElementById('p-menu').hidden", 5)
        await _captura(p, "8_menu")
        await _tocar(p, "#m-ajustes")
        await p.esperar("!document.getElementById('p-ajustes').hidden && document.querySelectorAll('#aj-cuerpo .aj-fila').length >= 15", 5)
        await _captura(p, "9_ajustes")
        await _tocar(p, "#aj-atras")
        await p.esperar("!document.getElementById('p-menu').hidden", 5)
        await _tocar(p, "#m-jornada")
        await _dialogo(p, "Cerrar la jornada")
        await _dialogo(p, "Cerrar jornada")
        await p.esperar("document.getElementById('jornada-nombre').textContent === 'Sin jornada abierta'", 10)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_jornadas WHERE fin IS NOT NULL").fetchone()["n"] == 1
        assert (await p.errores()) == []



@pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")
def test_a_technician_registers_points_from_the_phone(mundo, tmp_path):
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        asyncio.run(_recorrido(puerto, con, tmp_path))
