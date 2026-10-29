"""Los esquemas generales de una zona, cada uno con su nombre: crear, renombrar, eliminar, y que cada uno guarde sus propias posiciones."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import db, lienzo, usuarios
from visor_rutas.redes.api import METODOS


def test_each_schema_has_its_own_name_and_positions(zona):
    con, admin, p, ids = zona
    general = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    assert [x["nombre"] for x in general["lienzos"]] == ["General"]
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], "x": 10, "y": 20}])
    norte = lienzo.crear_lienzo(con, admin, proyecto_id=p["id"], nombre="  Troncal   norte ")
    assert norte["lienzo"]["nombre"] == "Troncal norte" and norte["colocados"] == [] and [x["nombre"] for x in norte["lienzos"]] == ["General", "Troncal norte"]
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=norte["lienzo"]["id"], colocados=[{"elemento_id": ids["n"], "x": 5, "y": 6}])
    # the positions of one do not leak into the other, and "no lienzo_id" is still the first one
    assert [(c["elemento_id"]) for c in lienzo.lienzo(con, admin, proyecto_id=p["id"])["colocados"]] == [ids["m1"]]
    assert [(c["elemento_id"]) for c in lienzo.lienzo(con, admin, proyecto_id=p["id"], lienzo_id=norte["lienzo"]["id"])["colocados"]] == [ids["n"]]
    for m in ("crear_lienzo", "renombrar_lienzo", "eliminar_lienzo"):
        assert m in METODOS


def test_rename_checks_the_name_and_the_version(zona):
    con, admin, p, ids = zona
    general = lienzo.lienzo(con, admin, proyecto_id=p["id"])["lienzo"]
    otro = lienzo.crear_lienzo(con, admin, proyecto_id=p["id"], nombre="Ramal 2")["lienzo"]
    r = lienzo.renombrar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=general["id"], nombre="Jalapa completa", version=general["version"])
    assert r["lienzo"]["nombre"] == "Jalapa completa" and r["lienzo"]["version"] == general["version"] + 1
    with pytest.raises(db.DatosInvalidos):                                       # a name already used in the zone (any case)
        lienzo.renombrar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=otro["id"], nombre="JALAPA COMPLETA")
    with pytest.raises(db.DatosInvalidos):
        lienzo.crear_lienzo(con, admin, proyecto_id=p["id"], nombre="jalapa completa")
    with pytest.raises(db.DatosInvalidos):                                       # empty
        lienzo.renombrar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=otro["id"], nombre="   ")
    with pytest.raises(db.ConflictoVersion):                                     # someone else renamed it in between
        lienzo.renombrar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=general["id"], nombre="Otro nombre", version=general["version"])


def test_delete_a_schema_keeps_the_network_and_general_comes_back(zona):
    con, admin, p, ids = zona
    general = lienzo.lienzo(con, admin, proyecto_id=p["id"])["lienzo"]
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], "x": 1, "y": 2}])
    nuevo = lienzo.crear_lienzo(con, admin, proyecto_id=p["id"], nombre="Prueba")["lienzo"]
    r = lienzo.eliminar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=nuevo["id"])
    assert [x["nombre"] for x in r["lienzos"]] == ["General"] and len(r["elementos"]) == 3 and len(r["cables"]) == 2
    with pytest.raises(db.NoEncontrado):
        lienzo.lienzo(con, admin, proyecto_id=p["id"], lienzo_id=nuevo["id"])
    r = lienzo.eliminar_lienzo(con, admin, proyecto_id=p["id"], lienzo_id=general["id"])                    # the last one: an empty «General» is created again
    assert [x["nombre"] for x in r["lienzos"]] == ["General"] and r["colocados"] == [] and r["lienzo"]["id"] != general["id"]
    assert len(r["elementos"]) == 3                                                                          # the mufas were not touched


def test_a_reader_cannot_create_rename_or_delete(zona):
    con, admin, p, ids = zona
    from visor_rutas.redes import proyectos
    ana = usuarios.identificar(con, persona_visor="ana")
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], ana["id"]]})
    general = lienzo.lienzo(con, admin, proyecto_id=p["id"])["lienzo"]
    for accion in (lambda: lienzo.crear_lienzo(con, ana, proyecto_id=p["id"], nombre="X"),
                   lambda: lienzo.renombrar_lienzo(con, ana, proyecto_id=p["id"], lienzo_id=general["id"], nombre="X"),
                   lambda: lienzo.eliminar_lienzo(con, ana, proyecto_id=p["id"], lienzo_id=general["id"])):
        with pytest.raises(db.SinPermiso):
            accion()
