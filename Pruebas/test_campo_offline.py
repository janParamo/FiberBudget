"""App de campo, fase 3 (cola en IndexedDB, reintentos, service worker, instalar en Android / iPhone), en un Edge de verdad contra la API real y la base de pruebas:
sin señal los puntos y sus fotos se guardan en el teléfono, sobreviven a cerrar la app y salen solos al volver la señal, sin duplicar."""
import asyncio
import json

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import hay_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import jpeg
from test_campo_pwa import (_captura, _entrar, _escribir, _tocar, _visible, esperar_sql, mundo, servidor_real, telefono, websockets)  # noqa: F401
from test_visor_api import entorno  # noqa: F401  (fixture of the /visor/* API)

pytestmark = pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
IPHONE_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/123.0 Mobile/15E148 Safari/604.1"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Mobile Safari/537.36"
IPAD_ESCRITORIO = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"


def pruebas_de(coro):
    asyncio.run(coro)


async def _ver_cola(p):
    return json.loads(await p.evaluar("CampoCola.listar().then((l) => JSON.stringify(l.map((e) => ({uuid: e.uuid, estado: e.estado, error: e.error, puntoId: e.puntoId, "
                                      "fotos: e.fotos.map((f) => ({enviada: f.enviada, descartada: !!f.descartada})), nombre: e.punto.nombre}))))"))


async def _recorrido_sin_senal(puerto, con, tmp_path):
    foto = tmp_path / "foto.jpg"
    foto.write_bytes(jpeg(2400, 1600))
    async with telefono(puerto) as p:
        await p.esperar("!document.getElementById('pantalla-clave').hidden", 10)
        await _entrar(p, "clave-jan")
        await p.esperar("!document.getElementById('app').hidden && document.getElementById('gps-estado').textContent.includes('±5')", 20)
        # the service worker is up and has the app's files (that is what lets the app open with no signal)
        await p.esperar("navigator.serviceWorker.ready.then(() => true)", 20)
        await p.esperar("caches.keys().then((k) => k.includes('campo-v6'))", 20)
        await p.esperar("caches.open('campo-v6').then((c) => c.keys()).then((k) => k.length >= 10)", 20)
        assert await p.evaluar("CampoCola.meta('clave')") == "clave-jan"          # the service worker sends with it

        # ---- no signal: a pole with a photo is kept in the phone, not lost
        await p.sin_red(True)
        await p.esperar("navigator.onLine === false", 10)
        assert "sin conexión" in await p.evaluar("document.getElementById('persona').textContent")
        await _tocar(p, "#acciones [data-tipo=poste]")
        await p.esperar("!document.getElementById('hoja-formulario').hidden", 5)
        await p.subir_archivo("#form-foto", foto)
        await p.esperar("document.querySelectorAll('#form-fotos img').length === 1", 20)
        await _tocar(p, "#form-guardar")
        await p.esperar("document.getElementById('hoja-formulario').hidden && !document.getElementById('cola-barra').hidden", 10)
        assert "1 pendiente de enviar" in await p.evaluar("document.getElementById('cola-texto').textContent")
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 0
        await _captura(p, "5_sin_senal")
        cola = await _ver_cola(p)
        assert len(cola) == 1 and cola[0]["estado"] == "cola" and cola[0]["puntoId"] is None and cola[0]["fotos"] == [{"enviada": False, "descartada": False}]

        # a second point, then change its name while it is still in the phone, and drop it
        await _tocar(p, "#acciones [data-tipo=reserva]")
        await p.esperar("!document.getElementById('hoja-formulario').hidden", 5)
        await _tocar(p, "#form-guardar")
        await p.esperar("document.getElementById('contador').textContent === '2'", 10)
        await _tocar(p, "#btn-lista")
        assert await p.evaluar("[...document.querySelectorAll('#lista-puntos .estado')].map((e) => e.textContent).join()") == "Sin enviar,Sin enviar"
        await p.evaluar("window.confirm = () => true; [...document.querySelectorAll('#lista-puntos li')].find((li) => li.textContent.includes('Reserva 1')).querySelector('button').click(); true")
        await p.esperar("!document.getElementById('hoja-editar').hidden", 5)
        await _tocar(p, "#editar-borrar")
        await p.esperar("document.getElementById('contador').textContent === '1'", 10)
        await _tocar(p, "#btn-lista")
        await p.evaluar("document.querySelector('#lista-puntos li button').click(); true")
        await p.esperar("!document.getElementById('hoja-editar').hidden", 5)
        await _escribir(p, "editar-nombre", "Poste sin señal")
        await _tocar(p, "#editar-guardar")
        await p.esperar("document.getElementById('hoja-editar').hidden", 5)
        assert [e["nombre"] for e in await _ver_cola(p)] == ["Poste sin señal"]

        # ---- the app is closed and opened again with no signal: it opens (service worker) and the queue is still there
        await p.enviar("Page.reload")
        await p.esperar("document.readyState === 'complete' && window.Campo && !document.getElementById('app').hidden", 30)
        await p.esperar("document.getElementById('cola-texto').textContent.includes('1 pendiente')", 15)
        assert "sin conexión" in await p.evaluar("document.getElementById('persona').textContent")
        assert await p.evaluar("document.getElementById('persona').textContent.startsWith('jan')") is True

        # ---- the signal comes back: it goes out by itself, once, with its photo
        await p.sin_red(False)
        await esperar_sql(con, "SELECT 1 FROM redes.campo_fotos", 1, 40)
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        puntos = con.execute("SELECT nombre, tipo, estado FROM redes.campo_puntos").fetchall()
        assert [(x["nombre"], x["tipo"], x["estado"]) for x in puntos] == [("Poste sin señal", "poste", "pendiente")]
        assert await _ver_cola(p) == []
        await p.esperar("document.getElementById('contador').textContent === '1'", 15)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_fotos").fetchone()["n"] == 1
        assert (await p.errores()) == []


def test_points_taken_without_signal_survive_a_restart_and_are_sent_once_when_it_returns(mundo, tmp_path):
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        pruebas_de(_recorrido_sin_senal(puerto, con, tmp_path))


async def _recorrido_reintentos(puerto, con):
    async with telefono(puerto, cdp=9342) as p:
        await _entrar(p, "clave-jan")
        await p.esperar("window.Campo.lista", 20)
        await _escribir_cola(p, "Poste A", fotos=2)

        # a cut in the middle of sending: the point is in the server, the first photo too, the second one not; the entry stays
        await p.evaluar("""(() => { window.__fotos = 0; window.__fetch = window.fetch;
          window.fetch = (u, o) => { if (String(u).includes('/fotos')) { window.__fotos += 1; if (window.__fotos === 2) return Promise.reject(new TypeError('red cortada')); } return window.__fetch(u, o); };
          return true; })()""")
        r = json.loads(await p.evaluar("CampoCola.enviar().then((r) => JSON.stringify(r))"))
        assert r["detenido"] == "red" and r["restantes"] == 1 and r["enviados"] == []
        cola = await _ver_cola(p)
        assert cola[0]["puntoId"] and [f["enviada"] for f in cola[0]["fotos"]] == [True, False]
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 1
        assert con.execute("SELECT count(*) AS n FROM redes.campo_fotos").fetchone()["n"] == 1

        # the retry finishes it: still one point and now two photos (nothing duplicated)
        r = json.loads(await p.evaluar("CampoCola.enviar().then((r) => JSON.stringify(r))"))
        assert [x["nombre"] for x in r["enviados"]] == ["Poste A"] and r["restantes"] == 0 and r["detenido"] is None
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 1
        assert con.execute("SELECT count(*) AS n FROM redes.campo_fotos").fetchone()["n"] == 2

        # the same entry sent again (the answer was lost the first time) is recognised by its uuid
        await p.evaluar("""(() => CampoCola.agregar({uuid: window.__ultimo.uuid, creado: Date.now(), puntoId: null, estado: 'cola', error: null, intentos: 0,
          punto: window.__ultimo.punto, fotos: window.__ultimo.fotos.map((f) => ({uuid: f.uuid, blob: f.blob, enviada: false}))}))()""")
        r = json.loads(await p.evaluar("CampoCola.enviar().then((r) => JSON.stringify(r))"))
        assert r["restantes"] == 0
        assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 1
        assert con.execute("SELECT count(*) AS n FROM redes.campo_fotos").fetchone()["n"] == 2

        # data the server refuses stays in the queue with its error, is shown in red, and is NOT retried over and over
        await _escribir_cola(p, "Poste B", extra="punto.subtipo = 'plástico';")
        await p.evaluar("window.__pedidos = 0; window.fetch = (u, o) => { if (String(u).includes('/puntos')) window.__pedidos += 1; return window.__fetch(u, o); }; true")
        r = json.loads(await p.evaluar("CampoCola.enviar().then((r) => JSON.stringify(r))"))
        assert r["con_error"] == 1 and r["restantes"] == 1 and r["enviados"] == []
        pedidos = await p.evaluar("window.__pedidos")
        await p.evaluar("CampoCola.enviar()")
        assert await p.evaluar("window.__pedidos") == pedidos                           # no automatic retry of a refused point
        cola = await _ver_cola(p)
        assert cola[0]["estado"] == "error" and "subtipo" in cola[0]["error"]
        await p.evaluar("Campo.leerCola()")
        assert "con error" in await p.evaluar("document.getElementById('cola-texto').textContent")
        assert "con-error" in await p.evaluar("document.getElementById('cola-barra').className")
        await _tocar(p, "#btn-lista")
        assert "Con error" in await p.evaluar("document.querySelector('#lista-puntos .estado.error').textContent")
        assert "subtipo" in await p.evaluar("document.querySelector('#lista-puntos small.error').textContent")
        await _captura(p, "6_con_error")

        # a key that stopped working stops the sending without losing anything
        await _escribir_cola(p, "Poste C")
        await p.evaluar("CampoCola.ponerMeta('clave', 'otra-clave')")
        r = json.loads(await p.evaluar("CampoCola.enviar().then((r) => JSON.stringify(r))"))
        assert r["detenido"] == "clave" and r["restantes"] == 2
        assert (await p.errores()) == []


async def _escribir_cola(p, nombre, fotos=0, extra=""):
    """Puts a point (with `fotos` little photos) in the queue as the page does and remembers it in window.__ultimo."""
    await p.evaluar("""(async () => {
      const punto = {uuid_cliente: crypto.randomUUID(), jornada_id: null, tipo: 'poste', subtipo: 'concreto', nombre: %s, notas: '', lat: 12.1364, lon: -86.2514,
                     precision_m: 4, altitud: null, origen_coord: 'gps', capturado_en: new Date().toISOString()};
      %s
      const lienzo = document.createElement('canvas'); lienzo.width = lienzo.height = 8;
      const fotos = [];
      for (let i = 0; i < %d; i++) fotos.push({uuid: crypto.randomUUID(), blob: await new Promise((ok) => lienzo.toBlob(ok, 'image/jpeg', 0.7)), enviada: false});
      window.__ultimo = {uuid: punto.uuid_cliente, creado: Date.now(), puntoId: null, estado: 'cola', error: null, intentos: 0, punto, fotos};
      await CampoCola.agregar(window.__ultimo);
      return true; })()""" % (json.dumps(nombre), extra, fotos))


def test_a_cut_while_sending_never_duplicates_and_refused_data_waits_for_a_person(mundo):
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        pruebas_de(_recorrido_reintentos(puerto, con))


async def _recorrido_instalar(puerto):
    # iPhone in Safari, not installed: the warning bar and the steps
    async with telefono(puerto, cdp=9343, ua=IPHONE) as p:
        assert await p.evaluar("CampoAyuda.plataforma()") == "iphone" and await p.evaluar("CampoAyuda.safari()") is True
        await _entrar(p, "clave-jan")
        await p.esperar("!document.getElementById('app').hidden", 20)
        await p.esperar("!document.getElementById('ios-barra').hidden", 5)
        await _tocar(p, "#ios-como")
        await p.esperar("!document.getElementById('hoja-ayuda').hidden", 5)
        texto = await p.evaluar("document.getElementById('ayuda-contenido').textContent")
        assert "Compartir" in texto and "Agregar a pantalla de inicio" in texto and "puede borrar los puntos" in texto and "segundo plano" in texto
        await _captura(p, "7_ayuda_iphone")
        await _tocar(p, "#ayuda-cerrar")
        await _tocar(p, "#ios-cerrar")
        assert await p.evaluar("document.getElementById('ios-barra').hidden") is True
    # Android: the install button appears when Chrome offers to install and starts it
    async with telefono(puerto, cdp=9344, ua=ANDROID) as p:
        assert await p.evaluar("CampoAyuda.plataforma()") == "android"
        await _entrar(p, "clave-jan")
        await p.esperar("!document.getElementById('app').hidden", 20)
        assert await p.evaluar("document.getElementById('ios-barra').hidden") is True            # the iPhone warning is only for iPhone
        await p.evaluar("""(() => { const e = new Event('beforeinstallprompt', {cancelable: true}); window.__instalo = 0;
          e.prompt = () => { window.__instalo += 1; }; e.userChoice = Promise.resolve({outcome: 'accepted'}); window.dispatchEvent(e); return true; })()""")
        await _tocar(p, "#btn-menu")
        await p.esperar("!document.getElementById('menu-instalar').hidden", 5)
        await _tocar(p, "#menu-instalar")
        await p.esperar("window.__instalo === 1", 5)
        await p.esperar("document.getElementById('menu-instalar').hidden", 5)                        # once installed (or answered) the button goes away
        await _tocar(p, "#btn-menu")
        await _tocar(p, "#menu-ayuda")
        assert "Instalar app" in await p.evaluar("document.getElementById('ayuda-contenido').textContent")


def test_install_help_by_platform(mundo):
    main_, _, _ = mundo
    with servidor_real(main_.app) as puerto:
        pruebas_de(_recorrido_instalar(puerto))


def test_platform_detection_from_the_user_agent(mundo):
    main_, _, _ = mundo

    async def correr(puerto):
        async with telefono(puerto, cdp=9345) as p:
            f = lambda ua, tactil=None: p.evaluar(f"CampoAyuda.plataforma({json.dumps(ua)}, {json.dumps(tactil)})")
            assert await f(IPHONE) == "iphone" and await f(ANDROID) == "android"
            assert await f(IPAD_ESCRITORIO, True) == "iphone" and await f(IPAD_ESCRITORIO, False) == "otro"      # iPad in desktop mode has touch, a Mac does not
            assert await p.evaluar(f"CampoAyuda.safari({json.dumps(IPHONE)})") is True and await p.evaluar(f"CampoAyuda.safari({json.dumps(IPHONE_CHROME)})") is False
    with servidor_real(main_.app) as puerto:
        pruebas_de(correr(puerto))
