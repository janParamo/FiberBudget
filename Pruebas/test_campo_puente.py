"""App de campo, fase 4: el camino de los avisos hasta la página del visor de escritorio: en modo local (LISTEN en la PC del servidor) y en modo remoto (Server-Sent
Events con la clave, con reconexión), sin repetir ni dejar hilos colgados."""
import json
import threading
import time

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest
import requests

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import MARIA, punto  # noqa: F401
from test_campo_pwa import servidor_real  # noqa: F401
from test_campo_revision import esperar, servicio_real  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas import campo_eventos, config_visor, remoto, ventana_web


class FalsaVentana:
    """pywebview's window: it only records what the page is told."""

    def __init__(self):
        self.js = []

    def evaluate_js(self, codigo):
        self.js.append(codigo)


class FalsaEscucha:
    def __init__(self):
        self.suscriptores = []
        self.quitados = 0

    def suscribir(self, f):
        self.suscriptores.append(f)

        def quitar():
            self.quitados += 1
            self.suscriptores.remove(f)
        return quitar


def test_local_mode_forwards_the_notices_to_the_page_once_and_stops(monkeypatch):
    falsa = FalsaEscucha()
    monkeypatch.setattr(campo_eventos, "escucha", lambda: falsa)
    api = ventana_web.Api(config_visor.ConfigVisor("local", "", ""))
    api._ventana = FalsaVentana()
    assert api.campo_escuchar() == {"ok": True, "ya": False}
    assert api.campo_escuchar() == {"ok": True, "ya": True}                                   # asking twice does not subscribe twice
    assert len(falsa.suscriptores) == 1
    falsa.suscriptores[0]({"tabla": "campo_puntos", "id": "7", "cambio": "insert", "usuario_id": "2"})
    assert api._ventana.js == ['window.CampoVisor && window.CampoVisor.evento({"tabla": "campo_puntos", "id": "7", "cambio": "insert", "usuario_id": "2"})']
    assert api.campo_detener() == {"ok": True} and falsa.quitados == 1 and falsa.suscriptores == []
    assert api.campo_escuchar()["ya"] is False                                                # it can start again


def test_a_window_that_is_closing_never_breaks_the_listener(monkeypatch):
    falsa = FalsaEscucha()
    monkeypatch.setattr(campo_eventos, "escucha", lambda: falsa)
    api = ventana_web.Api(config_visor.ConfigVisor("local", "", ""))

    class Rota(FalsaVentana):
        def evaluate_js(self, codigo):
            raise RuntimeError("ventana cerrada")
    api.campo_escuchar()
    api._avisar_campo({"tabla": "x"})                                                         # no window yet: nothing happens
    api._ventana = Rota()
    api._avisar_campo({"tabla": "x"})                                                         # a window that fails: nothing happens either


def test_remote_mode_listens_with_the_sse_client_of_the_proxy():
    recibidos = []

    class Remoto:
        def escuchar_campo(self, alerta, detener):
            alerta({"tabla": "_conectado"})
            detener.wait(5)
    api = ventana_web.Api(config_visor.ConfigVisor("remoto", "http://x", "k"))
    api._modo, api._remoto, api._ventana = "remoto", Remoto(), FalsaVentana()
    assert api.campo_escuchar()["ok"]
    esperar(lambda: api._ventana.js)
    assert "_conectado" in api._ventana.js[0]
    api.campo_detener()
    sin_servidor = ventana_web.Api(config_visor.ConfigVisor("remoto", "", ""))
    sin_servidor._modo = "remoto"
    assert sin_servidor.campo_escuchar()["ok"] is False


class RespuestaSse:
    def __init__(self, codigo, lineas=()):
        self.status_code, self._lineas = codigo, list(lineas)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        yield from self._lineas


def test_the_sse_client_reconnects_and_asks_the_page_to_refresh_every_time():
    llamadas = []

    class Sesion:
        def get(self, url, **kw):
            llamadas.append(url)
            if len(llamadas) == 1:
                raise requests.ConnectionError("se cortó")
            if len(llamadas) == 2:
                return RespuestaSse(200, [": conectado", 'data: {"tabla": "campo_puntos", "id": "1", "cambio": "insert"}', ": latido", "data: no es json"])
            return RespuestaSse(200, [])
    proveedor = remoto.ProveedorRemoto("http://servidor", "clave", sesion=Sesion())
    recibidos, detener = [], threading.Event()

    def alerta(e):
        recibidos.append(e)
        if len(recibidos) >= 4:
            detener.set()
    proveedor.escuchar_campo(alerta, detener, espera_min=0.01, espera_max=0.05)
    assert [e["tabla"] for e in recibidos] == ["_conectado", "campo_puntos", "_conectado", "_conectado"]       # the bad line was skipped; every (re)connection says so
    assert llamadas[0] == "http://servidor/visor/campo/eventos"


@pytest.mark.parametrize("codigo,texto", [(401, "clave"), (403, "administrador o un editor"), (404, "no tiene la app de campo")])
def test_the_sse_client_stops_when_the_key_or_the_role_is_refused(codigo, texto):
    class Sesion:
        def get(self, url, **kw):
            return RespuestaSse(codigo)
    recibidos = []
    remoto.ProveedorRemoto("http://servidor", "clave", sesion=Sesion()).escuchar_campo(recibidos.append, threading.Event(), espera_min=0.01)
    assert len(recibidos) == 1 and recibidos[0]["tabla"] == "_error" and texto in recibidos[0]["error"]
    sin_url = []
    remoto.ProveedorRemoto("", "k").escuchar_campo(sin_url.append, threading.Event())
    assert sin_url[0]["tabla"] == "_error"


def test_the_remote_client_gets_the_real_server_events(servicio_real):
    """The proxy of the exe against the real API: connect, receive a technician's point and position, stop."""
    main_, con = servicio_real
    with servidor_real(main_.app) as puerto:
        proveedor = remoto.ProveedorRemoto(f"http://127.0.0.1:{puerto}", "clave-jan")
        recibidos, detener = [], threading.Event()
        hilo = threading.Thread(target=proveedor.escuchar_campo, args=(recibidos.append, detener), daemon=True)
        hilo.start()
        esperar(lambda: recibidos and campo_eventos._escucha.conectado.is_set())
        assert recibidos[0] == {"tabla": "_conectado"}
        r = requests.post(f"http://127.0.0.1:{puerto}/visor/campo/puntos", json={"puntos": [punto()]}, headers=MARIA)
        assert r.status_code == 200
        esperar(lambda: any(e.get("tabla") == "campo_puntos" for e in recibidos))
        detener.set()
        # the server notices the stream is gone (heartbeat) and the viewer thread ends with its next line or timeout
        # a technician's key is refused with a clear message
        malos = []
        remoto.ProveedorRemoto(f"http://127.0.0.1:{puerto}", "clave-maria").escuchar_campo(malos.append, threading.Event())
        assert malos == [{"tabla": "_error", "error": "Solo un administrador o un editor recibe los avisos de campo"}]
