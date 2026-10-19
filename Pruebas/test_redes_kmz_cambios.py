"""Visor v2, fase 4 (segunda parte): cambios al KMZ sin tocar el archivo (redes/kmz_cambios.py, migración 012) y "Entrar a la mufa"
de un punto del KMZ que la migración no tiene (mufas_existentes.crear_vacia)."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, kmz_cambios, mufa, mufas_existentes, usuarios
from visor_rutas.redes.api import METODOS

CLAVE = "KMZ / MUFAS|MF PRUEBA|12.13000,-86.25000"
ANTES = {"nombre": "MF PRUEBA", "lat": 12.13, "lon": -86.25}


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    lector = usuarios.identificar(con, persona_visor="ana")
    return con, admin, lector


def _editar(con, actor, **kw):
    args = {"clave": CLAVE, "carpeta": "KMZ / MUFAS", "tipo": "punto", "antes": ANTES, **kw}
    return kmz_cambios.editar(con, actor, **args)


def test_rename_and_move_keep_the_original_and_going_back_removes_the_change(mundo):
    con, admin, _ = mundo
    c = _editar(con, admin, nombre="  MF   NUEVA ", lat=12.131, lon=-86.251)["cambio"]
    assert (c["accion"], c["antes"], c["despues"]) == ("editar", ANTES, {"nombre": "MF NUEVA", "lat": 12.131, "lon": -86.251})
    # editing again updates the same change; the original stays
    c2 = _editar(con, admin, nombre="MF OTRA")["cambio"]
    assert c2["id"] == c["id"] and c2["antes"] == ANTES and c2["despues"]["nombre"] == "MF OTRA" and c2["despues"]["lat"] == 12.13
    assert [x["id"] for x in kmz_cambios.listar(con, admin)["cambios"]] == [c["id"]]
    # the same name and position as the KMZ: nothing to keep
    assert _editar(con, admin)["cambio"] is None and kmz_cambios.listar(con, admin)["cambios"] == []


def test_delete_undo_and_permissions(mundo):
    con, admin, lector = mundo
    b = kmz_cambios.borrar(con, admin, clave=CLAVE, carpeta="KMZ / MUFAS", tipo="punto", antes=ANTES)["cambio"]
    assert b["accion"] == "borrar" and b["despues"] is None
    assert METODOS["cambios_kmz"](con, lector)["cambios"][0]["id"] == b["id"]               # everybody sees the changes
    with pytest.raises(db.SinPermiso):
        kmz_cambios.deshacer(con, lector, id=b["id"])
    with pytest.raises(db.SinPermiso):
        _editar(con, lector, nombre="X")
    kmz_cambios.deshacer(con, admin, id=b["id"])
    assert kmz_cambios.listar(con, admin)["cambios"] == []
    with pytest.raises(db.NoEncontrado):
        kmz_cambios.deshacer(con, admin, id=b["id"])
    assert con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad = 'kmz_cambio'").fetchone()["n"] == 2
    # a deleted element can be created again later (the unique key is only for active changes)
    assert kmz_cambios.borrar(con, admin, clave=CLAVE, carpeta="KMZ / MUFAS", tipo="punto", antes=ANTES)["cambio"]["id"] != b["id"]


def test_invalid_data_is_refused(mundo):
    con, admin, _ = mundo
    for kw in ({"clave": ""}, {"tipo": "raro"}, {"antes": {"nombre": "", "lat": 1, "lon": 1}}, {"antes": {"nombre": "X"}}, {"lat": 95, "lon": 0}):
        with pytest.raises(db.DatosInvalidos):
            _editar(con, admin, **kw)
    with pytest.raises(db.DatosInvalidos):                                                   # a line cannot be moved
        kmz_cambios.editar(con, admin, clave="L|Cable|1,1", carpeta="L", tipo="linea", antes={"nombre": "Cable"}, lat=1, lon=1)
    c = kmz_cambios.editar(con, admin, clave="L|Cable|1,1", carpeta="L", tipo="linea", antes={"nombre": "Cable"}, nombre="Cable 2")["cambio"]
    assert c["despues"] == {"nombre": "Cable 2"}


def test_entering_a_kmz_mufa_creates_an_empty_one_once(mundo):
    con, admin, lector = mundo
    r = METODOS["crear_mufa_kmz"](con, admin, nombre="MF SIN MIGRAR", lat=12.2, lon=-86.3)
    assert r["creada"] is True and r["mufa"]["proyecto"].startswith("Red existente")
    leida = mufa.leer(con, admin, mufa_id=r["mufa"]["id"])                                  # the mufa editor opens it
    assert leida["mufa"]["nombre"] == "MF SIN MIGRAR"
    e = con.execute("SELECT tipo, subtipo, fuente, ref_externa, estado_migracion FROM redes.elementos WHERE id = %s", (r["mufa"]["id"],)).fetchone()
    assert (e["tipo"], e["fuente"], e["estado_migracion"]) == ("mufa", "kmz", "editada") and e["ref_externa"]["kmz"]["nombre"] == "MF SIN MIGRAR"
    # entering again finds it (no duplicate), also by name when the click is a little off
    r2 = mufas_existentes.crear_vacia(con, admin, nombre="mf sin migrar", lat=12.2001, lon=-86.3001)
    assert r2["creada"] is False and r2["mufa"]["id"] == r["mufa"]["id"]
    assert METODOS["mufa_existente"](con, lector, nombre="MF SIN MIGRAR", lat=12.2, lon=-86.3)["mufa"]["id"] == r["mufa"]["id"]
    # a second one goes to the same base project
    r3 = mufas_existentes.crear_vacia(con, admin, nombre="OTRA", lat=12.3, lon=-86.4)
    assert r3["mufa"]["proyecto_id"] == r["mufa"]["proyecto_id"]
    assert con.execute("SELECT count(*) AS n FROM redes.proyectos WHERE codigo = 'BASE-VISOR'").fetchone()["n"] == 1
    with pytest.raises(db.SinPermiso):
        mufas_existentes.crear_vacia(con, lector, nombre="X", lat=12.4, lon=-86.5)
    with pytest.raises(db.DatosInvalidos):
        mufas_existentes.crear_vacia(con, admin, nombre="", lat=12.4, lon=-86.5)
