"""App de campo, fase 6: la dirección oficial (Cloudflare): configuración, el aviso de dirección no segura, el verificador y los archivos del túnel."""
import importlib
import json
import re
from pathlib import Path

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

import verificar_campo
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import MARIA  # noqa: F401
from test_campo_pwa import mundo, telefono, servidor_real, websockets  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _sin_direccion_publica_del_env(monkeypatch):
    """The real .env may carry CAMPO_URL_PUBLICA (ngrok today): these tests decide their own."""
    import config
    monkeypatch.delenv("CAMPO_URL_PUBLICA", raising=False)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_the_public_address_comes_from_the_environment_without_the_trailing_slash(monkeypatch):
    import config
    monkeypatch.setenv("CAMPO_URL_PUBLICA", " https://api.fiberbudget.com/ ")
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().campo_url_publica == "https://api.fiberbudget.com"
        monkeypatch.delenv("CAMPO_URL_PUBLICA")
        config.get_settings.cache_clear()
        assert config.get_settings().campo_url_publica == ""
    finally:
        config.get_settings.cache_clear()


def test_the_campo_config_carries_the_public_address(mundo, monkeypatch):
    _, c, _ = mundo
    import config
    assert c.get("/visor/campo/config", headers=JAN).json()["url_publica"] == ""
    monkeypatch.setenv("CAMPO_URL_PUBLICA", "https://api.fiberbudget.com")
    config.get_settings.cache_clear()
    try:
        assert c.get("/visor/campo/config", headers=JAN).json()["url_publica"] == "https://api.fiberbudget.com"
    finally:
        monkeypatch.delenv("CAMPO_URL_PUBLICA")
        config.get_settings.cache_clear()


def test_the_checker_passes_against_the_real_app_and_names_what_fails(mundo):
    _, c, _ = mundo
    ok = verificar_campo.verificar("http://testserver", "clave-jan", sesion=c, con_eventos=False)
    assert [n for n, bien, _ in ok if not bien] == ["Dirección segura (https)"] and len(ok) >= 11          # everything but the address itself: http://testserver is not https
    assert any(n == "El manifest manda a /campo/" for n, _, _ in ok) and any(n == "La clave entra" and "jan" in d for n, _, d in ok)
    # a wrong key, a key without the role, and a server that does not know the field app: each says why
    mala = {n: (b, d) for n, b, d in verificar_campo.verificar("http://testserver", "otra", sesion=c, con_eventos=False)}
    assert mala["La clave entra"] == (False, "clave no válida")
    sin_rol = {n: (b, d) for n, b, d in verificar_campo.verificar("http://testserver", "clave-maria", sesion=c, con_eventos=False)}
    assert sin_rol["La clave entra"] in ((False, "sin el rol de técnico"), (True, "persona maria"))      # maria is a reader in this fixture
    # http is flagged for a public address, accepted for the own PC
    assert verificar_campo.verificar("http://api.fiberbudget.com", None, sesion=c, con_eventos=False)[0][1] is False
    assert verificar_campo.verificar("http://localhost:8000", None, sesion=c, con_eventos=False)[0][1] is True


def test_the_checker_reports_a_tunnel_that_answers_with_its_own_page():
    class Respuesta:
        status_code, headers, text = 200, {"content-type": "text/html"}, "<html>aviso del túnel</html>"

        def json(self):
            raise ValueError

    class Sesion:
        def get(self, url, **kw):
            return Respuesta()
    filas = {n: (b, d) for n, b, d in verificar_campo.verificar("https://x.example", None, sesion=Sesion(), con_eventos=False)}
    assert filas["GET /campo/"][0] is True and filas["GET /campo/app.js"][0] is False and "aviso del túnel" in filas["GET /campo/app.js"][1]
    assert filas["Dirección segura (https)"][0] is True


def test_the_tunnel_files_do_not_leak_the_token_and_the_service_opens_it_only_when_configured():
    bat = (RAIZ / "iniciar_tunel_cloudflare.bat").read_text(encoding="utf-8")
    assert "TUNNEL_TOKEN" in bat and "herramientas\\cloudflared.exe" in bat and "tunnel --no-autoupdate run" in bat
    assert not re.search(r"echo[^\r\n]*%(CLOUDFLARE_)?TUNNEL_TOKEN%", bat) and "--token" not in bat.replace("rem ", "")          # never on screen nor on the command line
    inicio = (RAIZ / "start_service.bat").read_text(encoding="utf-8")
    assert "CLOUDFLARE_ACTIVAR" in inicio and 'if "%CF_TUNEL%"=="1" start' in inicio and inicio.index("CF_TUNEL") < inicio.index("uvicorn")      # opt-in (ngrok is the way in until the domain exists); the tunnel first, then the service
    ignorado = (RAIZ / ".gitignore").read_text(encoding="utf-8", errors="replace")
    assert "herramientas/cloudflared.exe" in ignorado and "cloudflared/config.yml" in ignorado
    ejemplo = (RAIZ / "cloudflared" / "config.yml.ejemplo").read_text(encoding="utf-8")
    assert "api.fiberbudget.com" in ejemplo and "http://127.0.0.1:8000" in ejemplo and "http_status:404" in ejemplo
    assert "<ID_DEL_TUNEL>" in ejemplo                                                    # the example keeps placeholders; the real data lives in config.yml (ignored)
    assert "--config" in bat and "cloudflared\\config.yml" in bat and "cloudflared\\config.yml" not in inicio             # a config file is used by the tunnel script; the service does not open it by itself


def test_the_guides_cover_both_phones_and_the_steps_of_the_tunnel():
    guia = (RAIZ / "docs" / "campo" / "GUIA_TECNICOS.md").read_text(encoding="utf-8")
    for texto in ("Android", "iPhone", "Safari", "Agregar a pantalla de inicio", "Instalar app", "Trazar cable", "Sin señal", "Cerrar la jornada", "https://"):
        assert texto in guia, texto
    nube = (RAIZ / "docs" / "campo" / "CLOUDFLARE.md").read_text(encoding="utf-8")
    for texto in ("CLOUDFLARE_TUNNEL_TOKEN", "CAMPO_URL_PUBLICA", "herramientas\\cloudflared.exe", "verificar_campo.py", "api.fiberbudget.com", "127.0.0.1:8000"):
        assert texto in nube, texto
    assert "App de campo (técnicos con el teléfono)" in (RAIZ / "README.md").read_text(encoding="utf-8")


def test_the_phone_warns_about_an_address_without_https(mundo):
    main_, _, _ = mundo

    async def correr(puerto):
        async with telefono(puerto, cdp=9361) as p:
            f = lambda *a: p.evaluar("CampoAyuda.contextoSeguro(%s)" % ", ".join(json.dumps(x) for x in a))
            assert await f("https:", "api.fiberbudget.com") is True and await f("http:", "localhost") is True and await f("http:", "127.0.0.1") is True
            assert await f("http:", "192.168.1.20") is False and await f("http:", "api.fiberbudget.com") is False
            assert await p.evaluar("document.getElementById('aviso-http').hidden") is True            # this test runs on 127.0.0.1: secure
            texto = await p.evaluar("CampoAyuda.html({plataforma: 'android', seguro: false, instalada: false})")
            assert "no segura (http)" in texto and "Uso diario" in texto and "Instalar app" in texto
            assert "no segura" not in await p.evaluar("CampoAyuda.html({plataforma: 'iphone', seguro: true, instalada: true})")
    import asyncio
    with servidor_real(main_.app) as puerto:
        asyncio.run(correr(puerto))
