"""Cargas grandes por el tunel: el servicio comprime sus respuestas JSON (compresion_json.py) y el visor reintenta lo que solo lee (visor_rutas/remoto.py).

Una carga grande (Mis lugares ~1 MB) se cortaba a mitad de camino por ngrok y el visor decia «No se pudo conectar con el servidor».
"""
import asyncio
import gzip
import json

import pytest
import requests

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from compresion_json import GzipJson
from test_visor_api import JAN, entorno  # noqa: F401  (fixture)
from visor_rutas import remoto
from visor_rutas.remoto import ErrorRemoto, ProveedorRemoto


# --------------------------------------------------------------------------- the compression

async def _llamar(app, cabeceras):
    """Runs the ASGI app with a request and returns (status, headers dict, body)."""
    enviados = []

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(m):
        enviados.append(m)

    await GzipJson(app)({"type": "http", "method": "GET", "path": "/", "headers": [(k.encode(), v.encode()) for k, v in cabeceras.items()]}, recibir, enviar)
    inicio = next(m for m in enviados if m["type"] == "http.response.start")
    return inicio["status"], {k.decode().lower(): v.decode() for k, v in inicio["headers"]}, b"".join(m.get("body", b"") for m in enviados if m["type"] == "http.response.body")


def _app(tipo, cuerpo, partes=1, extra=()):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", tipo.encode()), (b"content-length", str(len(cuerpo)).encode()), *extra]})
        trozo = max(1, len(cuerpo) // partes)
        for i in range(0, len(cuerpo), trozo):
            await send({"type": "http.response.body", "body": cuerpo[i:i + trozo], "more_body": i + trozo < len(cuerpo)})
    return app


GRANDE = json.dumps({"carpetas": [{"id": i, "nombre": f"Carpeta {i}", "geom": [12.1, -86.2] * 5} for i in range(300)]}).encode()


def test_a_big_json_goes_compressed_and_comes_back_the_same():
    estado, cabeceras, cuerpo = asyncio.run(_llamar(_app("application/json", GRANDE), {"accept-encoding": "gzip, deflate"}))
    assert estado == 200 and cabeceras["content-encoding"] == "gzip" and "accept-encoding" in cabeceras["vary"].lower()
    assert int(cabeceras["content-length"]) == len(cuerpo) < len(GRANDE) / 3                                    # a third or less
    assert gzip.decompress(cuerpo) == GRANDE
    _, cabeceras, cuerpo = asyncio.run(_llamar(_app("application/json", GRANDE, partes=5), {"accept-encoding": "gzip"}))        # a body that arrives in pieces too
    assert gzip.decompress(cuerpo) == GRANDE and int(cabeceras["content-length"]) == len(cuerpo)


def test_nothing_else_is_touched_small_json_streams_files_already_compressed_or_a_caller_that_does_not_accept_gzip():
    pequeno = b'{"ok": true}'
    for tipo, cuerpo, cabeceras, esperado in (
            ("application/json", pequeno, {"accept-encoding": "gzip"}, pequeno),                                  # too small to be worth it
            ("application/json", GRANDE, {}, GRANDE),                                                             # the caller does not ask for gzip
            ("application/json", GRANDE, {"accept-encoding": "identity"}, GRANDE),
            ("text/event-stream", b"data: {}\n\n" * 400, {"accept-encoding": "gzip"}, b"data: {}\n\n" * 400),     # the live notices (SSE) go as they are
            ("application/zip", GRANDE, {"accept-encoding": "gzip"}, GRANDE),                                     # the package of the viewer, the Excel files...
            ("image/png", GRANDE, {"accept-encoding": "gzip"}, GRANDE)):
        estado, enviadas, cuerpo_recibido = asyncio.run(_llamar(_app(tipo, cuerpo, partes=3 if "event" in tipo else 1), cabeceras))
        assert estado == 200 and "content-encoding" not in enviadas and cuerpo_recibido == esperado, tipo
    ya = asyncio.run(_llamar(_app("application/json", GRANDE, extra=[(b"content-encoding", b"br")]), {"accept-encoding": "gzip"}))     # already encoded by someone else
    assert ya[1]["content-encoding"] == "br" and ya[2] == GRANDE


def test_the_service_answers_compressed_json_and_the_client_reads_it_without_noticing(entorno):
    _, _, cliente, _, _ = entorno
    r = cliente.get("/openapi.json", headers={"Accept-Encoding": "gzip"})                                         # a big JSON of the service itself
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"                                   # TestClient (httpx) opens it as requests does
    sin = cliente.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert sin.status_code == 200 and "content-encoding" not in sin.headers and sin.json() == r.json()
    pequena = cliente.get("/visor/info", headers={**JAN, "Accept-Encoding": "gzip"})                              # under 1 KB it is not worth compressing
    assert pequena.status_code == 200 and "content-encoding" not in pequena.headers and isinstance(pequena.json(), dict)


# --------------------------------------------------------------------------- the attempts of the viewer

class Sesion:
    """Fails `fallos` times with a dropped connection and then answers."""

    def __init__(self, fallos, codigo=200):
        self.fallos, self.llamadas, self.codigo = fallos, 0, codigo

    def request(self, metodo, url, **kw):
        self.llamadas += 1
        if self.llamadas <= self.fallos:
            raise requests.ConnectionError("Connection reset by peer")

        class R:
            status_code = self.codigo
            headers: dict = {}

            def json(_):
                return {"ok": True, "n": self.llamadas}
        return R()


@pytest.fixture
def sin_esperas(monkeypatch):
    monkeypatch.setattr(remoto.time, "sleep", lambda s: None)


def _proveedor(sesion):
    return ProveedorRemoto("https://servidor.example", "clave", sesion=sesion)


def test_a_get_is_tried_three_times_and_a_write_only_twice(sin_esperas):
    s = Sesion(fallos=2)
    assert _proveedor(s)._json("GET", "/visor/info")["ok"] and s.llamadas == 3                                  # the third one went through
    s = Sesion(fallos=3)
    with pytest.raises(ErrorRemoto, match="No se pudo conectar"):
        _proveedor(s)._json("GET", "/visor/info")
    assert s.llamadas == 3
    s = Sesion(fallos=2)
    assert _proveedor(s).redes("guardar_lugar", {"x": 1})["ok"] is False and s.llamadas == 2                    # a write: not repeated more than twice


def test_the_network_calls_that_only_read_are_tried_three_times(sin_esperas):
    for metodo in ("lugares", "estado", "cambios_kmz", "estilos_kmz"):
        s = Sesion(fallos=2)
        r = _proveedor(s).redes(metodo)
        assert r["ok"] is True and s.llamadas == 3, metodo
    assert "guardar_lugar" not in remoto.LECTURAS_REDES and "guardar_usuario" not in remoto.LECTURAS_REDES and "eliminar_lugar" not in remoto.LECTURAS_REDES


def test_a_gateway_error_of_the_tunnel_is_also_retried(sin_esperas):
    class Pasarela:
        llamadas = 0

        def request(self, metodo, url, **kw):
            Pasarela.llamadas += 1

            class R:
                status_code = 502 if Pasarela.llamadas < 3 else 200
                headers: dict = {}

                def json(_):
                    return {"ok": True}
            return R()

    assert _proveedor(Pasarela())._json("GET", "/visor/info")["ok"] and Pasarela.llamadas == 3


# --------------------------------------------------------------------------- the connections: few at a time, kept and reused

def test_the_viewer_keeps_its_connections_and_sends_only_a_few_calls_at_a_time(sin_esperas):
    """When it opens it asks for dozens of things at once; every one used to open its own connection and the tunnel cut the bursts (SSLError in the log)."""
    import threading
    import time as tiempo

    proveedor = ProveedorRemoto("https://servidor.example", "clave")
    adaptador = proveedor._sesion.get_adapter("https://servidor.example/visor/info")
    assert adaptador._pool_maxsize == remoto.CONEXIONES_GUARDADAS and adaptador._pool_connections == 2           # kept open and reused, not thrown away at 10

    class Cuenta:
        """A session that counts how many calls are inside at the same time."""
        dentro = maximo = 0
        lock = threading.Lock()

        def request(self, metodo, url, **kw):
            with Cuenta.lock:
                Cuenta.dentro += 1
                Cuenta.maximo = max(Cuenta.maximo, Cuenta.dentro)
            tiempo.sleep(0.05)
            with Cuenta.lock:
                Cuenta.dentro -= 1

            class R:
                status_code = 200
                headers: dict = {}

                def json(_):
                    return {"ok": True}
            return R()

    p = _proveedor(Cuenta())
    hilos = [threading.Thread(target=lambda: p._json("GET", "/visor/info")) for _ in range(30)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert 1 <= Cuenta.maximo <= remoto.MAX_SIMULTANEAS, Cuenta.maximo                                              # 30 at once ask, never more than a few go
