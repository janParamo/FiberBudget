"""Clave aparte para los técnicos (CAMPO_API_KEYS): abre solo la app de campo (/campo y /visor/campo/*); el resto de /visor/* la rechaza;
la persona de una clave de técnico se crea con el rol «tecnico»; las claves del visor (VISOR_API_KEYS) siguen sirviendo para revisar."""
import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import LAT, LON, punto
from test_campo_trazos import api  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)

JUAN = {"X-Visor-Key": "clave-tecnico-juan"}


@pytest.fixture
def con_claves_de_campo(api, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:clave-tecnico-juan, ana : clave-tecnico-ana ,malformada")
    return api


def test_the_technician_keys_are_read_like_the_viewer_keys(monkeypatch):
    import visor_api
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:k1, ana : k2 ,sin-clave:,:sin-nombre,malformada")
    assert visor_api.claves_campo() == {"k1": "juan", "k2": "ana"}
    monkeypatch.setenv("CAMPO_API_KEYS", "")
    assert visor_api.claves_campo() == {}


def test_a_technician_key_works_in_the_field_app_and_is_created_as_technician(con_claves_de_campo):
    c, con = con_claves_de_campo
    r = c.get("/visor/campo/config", headers=JUAN)
    assert r.status_code == 200 and r.json()["persona"] == "juan"
    j = c.post("/visor/campo/jornadas", json={"accion": "abrir", "nombre": "Ruta 1"}, headers=JUAN)
    assert j.status_code == 200, j.text                                          # a brand-new person, no administrator touched anything
    assert con.execute("SELECT rol FROM redes.usuarios WHERE persona_visor = 'juan'").fetchone()["rol"] == "tecnico"
    p = c.post("/visor/campo/puntos", json={"puntos": [punto()]}, headers=JUAN)
    assert p.status_code == 200 and p.json()["resultados"][0]["ok"] is True


def test_a_technician_key_opens_nothing_else_of_the_viewer(con_claves_de_campo):
    c, _ = con_claves_de_campo
    for ruta in ("/visor/ruta?lat=12.13&lon=-86.25", "/visor/presupuestos", "/visor/kmz/arbol", "/visor/redes/estado"):
        assert c.get(ruta, headers=JUAN).status_code in (401, 404, 405, 422), ruta
    assert c.get("/visor/presupuestos", headers=JUAN).status_code == 401
    assert c.get("/visor/presupuestos", headers=JAN).status_code == 200            # the viewer key still does
    assert c.get("/visor/campo/config", headers={"X-Visor-Key": "otra"}).status_code == 401
    assert c.get("/visor/campo/config").status_code == 401


def test_a_viewer_key_still_works_in_the_field_app_with_its_usual_role(con_claves_de_campo):
    c, con = con_claves_de_campo
    assert c.get("/visor/campo/config", headers=JAN).json()["persona"] == "jan"
    assert con.execute("SELECT rol FROM redes.usuarios WHERE persona_visor = 'jan'").fetchone()["rol"] == "tecnico"   # set by the fixture: not touched


def test_someone_who_has_both_keys_is_not_turned_into_a_technician(api, monkeypatch):
    c, con = api
    monkeypatch.setenv("CAMPO_API_KEYS", "lucia:clave-campo-lucia")
    monkeypatch.setenv("VISOR_API_KEYS", "lucia:clave-visor-lucia,jan:clave-jan")
    assert c.get("/visor/campo/jornadas", headers={"X-Visor-Key": "clave-campo-lucia"}).status_code == 403     # a lector: not a technician
    assert con.execute("SELECT rol FROM redes.usuarios WHERE persona_visor = 'lucia'").fetchone()["rol"] == "lector"


def test_the_field_page_needs_some_key_of_any_kind(api, monkeypatch):
    c, _ = api
    assert c.get("/campo/").status_code == 200
    monkeypatch.setenv("VISOR_API_KEYS", "")
    assert c.get("/campo/").status_code == 404                                     # no key at all: the app is off
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:k")
    assert c.get("/campo/").status_code == 200 and c.get("/visor/campo/config", headers={"X-Visor-Key": "k"}).status_code == 200
    assert c.get("/visor/campo/config", headers={"X-Visor-Key": "clave-jan"}).status_code == 401      # the old viewer keys are gone from the list
