"""Esquema de zona: mufas creadas a mano (nombre, coordenada y su mufa del Visio), vínculo con el Visio validado y nombres de la mufa / del Visio."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import lienzo, usuarios
from visor_rutas.redes.db import DatosInvalidos, SinPermiso


def _elementos(con, admin, p):
    return {e["nombre"]: e for e in lienzo.lienzo(con, admin, proyecto_id=p["id"])["elementos"]}


def test_a_mufa_made_by_hand_is_in_the_zone_and_is_new_until_the_schema_is_saved(zona):
    con, admin, p, ids = zona
    base = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], version=base["lienzo"]["version"], colocados=[{"elemento_id": ids["m1"], "x": 10, "y": 10}])
    r = lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="  MF  Nueva ", lat=12.1030, lon=-86.3000)
    assert r["elemento"]["nombre"] == "MF Nueva" and r["avisos"] == []
    e = _elementos(con, admin, p)["MF Nueva"]
    assert (e["tipo"], e["fuente"], e["nueva"], e["nodo_visio"]) == ("mufa", "usuario", True, None) and round(e["lat"], 4) == 12.1030
    # the schema places it by its coordinate and saves: it is not new any more (so a mufa taken off the schema does not come back by itself)
    v = lienzo.lienzo(con, admin, proyecto_id=p["id"])["lienzo"]["version"]
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], version=v, colocados=[{"elemento_id": r["elemento"]["id"], "x": 50, "y": 60}])
    assert _elementos(con, admin, p)["MF Nueva"]["nueva"] is False
    assert _elementos(con, admin, p)["MF Uno"]["nueva"] is False                              # the ones that were already there are not «new»


def test_the_visio_mufa_is_checked_because_several_share_a_name_and_a_pole(zona):
    con, admin, p, ids = zona
    a = lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="MF Poste", lat=12.1040, lon=-86.3000, nodo_visio=321, nombre_visio="MF POSTE")
    assert _elementos(con, admin, p)["MF Poste"]["nodo_visio"] == "321"
    # the same Visio mufa for another mufa: refused with a question (the other mufa is named), and allowed when the person confirms
    with pytest.raises(DatosInvalidos) as e:
        lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="MF Poste", lat=12.1040, lon=-86.3000, nodo_visio=321, nombre_visio="MF POSTE")
    assert "visio_ocupado" in e.value.errores and "MF Poste" in e.value.errores["visio_ocupado"]
    b = lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="MF Poste", lat=12.1040, lon=-86.3000, nodo_visio=322, nombre_visio="MF POSTE")      # the other one of the pole
    assert b["avisos"] and "mismo poste" in b["avisos"][0]                                      # same name and place: created, with a warning
    # linking an existing mufa: the same rule, and taking the link off
    with pytest.raises(DatosInvalidos) as e:
        lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nodo_visio=321, nombre_visio="MF POSTE")
    assert "visio_ocupado" in e.value.errores
    lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nodo_visio=321, nombre_visio="MF POSTE", forzar=True)
    lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nodo_visio=None)
    assert _elementos(con, admin, p)["MF Uno"]["nodo_visio"] is None
    # a mufa is not «occupied» by itself: assigning its own node again is fine
    lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=a["elemento"]["id"], nodo_visio=321, nombre_visio="MF POSTE")


def test_one_name_for_both_the_mufa_and_the_visio(zona):
    con, admin, p, ids = zona
    # the Visio name goes to the mufa
    r = lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nodo_visio=500, nombre_visio="MUFA UNO DEL VISIO", nombres="visio")
    assert r["elemento"]["nombre"] == "MUFA UNO DEL VISIO"
    e = _elementos(con, admin, p)["MUFA UNO DEL VISIO"]
    assert (e["nodo_visio"], e["nombre_visio"]) == ("500", "MUFA UNO DEL VISIO")
    # the name of the mufa goes to the Visio link
    r = lienzo.vincular_visio(con, admin, proyecto_id=p["id"], elemento_id=ids["m2"], nodo_visio=501, nombre_visio="OTRO NOMBRE VISIO", nombres="mufa")
    assert r["elemento"]["nombre"] == "MF Dos" and r["elemento"]["nombre_visio"] == "MF Dos"
    assert _elementos(con, admin, p)["MF Dos"]["nombre_visio"] == "MF Dos"
    # when creating
    c = lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="MF Mia", lat=12.2, lon=-86.3, nodo_visio=600, nombre_visio="MF DEL VISIO", nombres="visio")
    assert c["elemento"]["nombre"] == "MF DEL VISIO"


def test_validations_and_permissions(zona):
    con, admin, p, ids = zona
    with pytest.raises(DatosInvalidos):
        lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="", lat=12.1, lon=-86.3)
    with pytest.raises(DatosInvalidos):
        lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="X", lat="a", lon=-86.3)
    with pytest.raises(DatosInvalidos):
        lienzo.crear_mufa(con, admin, proyecto_id=p["id"], nombre="X", lat=12.1, lon=-86.3, nodo_visio=5)            # a node without its name
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(SinPermiso):
        lienzo.crear_mufa(con, lector, proyecto_id=p["id"], nombre="X", lat=12.1, lon=-86.3)
    with pytest.raises(SinPermiso):
        lienzo.vincular_visio(con, lector, proyecto_id=p["id"], elemento_id=ids["m1"], nodo_visio=None)
