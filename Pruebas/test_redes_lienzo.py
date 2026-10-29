"""Esquema de zona (lienzo): visor_rutas/redes/lienzo.py — la lista de lo que se puede agregar, las posiciones, los cables entre lo colocado y los permisos."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, lienzo, proyectos, red, usuarios
from visor_rutas.redes.api import METODOS


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def zona(con_redes):
    """Zone «Jalapa»: Nodo Jalapa -(Troncal 48)-> MF Uno -(Distribución 24)-> MF Dos; one client, one pole (they never go on the canvas)."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Jalapa", "codigo": "BASE-JAL"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "n", "tipo": "nodo", "subtipo": "nodo", "nombre": "Nodo Jalapa", "lat": 12.1000, "lon": -86.3000},
                      {"id": "m1", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Uno", "lat": 12.1010, "lon": -86.3000},
                      {"id": "m2", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Dos", "lat": 12.1020, "lon": -86.3000},
                      {"id": "c", "tipo": "cliente", "nombre": "Casa", "codigo": "C12345", "lat": 12.1021, "lon": -86.2995},
                      {"id": "p", "tipo": "poste", "subtipo": "concreto", "nombre": "P1", "lat": 12.1005, "lon": -86.3000}],
        "cables": [{"id": "k0", "nombre": "Troncal", "clase": "troncal", "hilos": 48, "origen_id": "n", "destino_id": "m1",
                    "vertices": [_v(12.1000, -86.3000), _v(12.1010, -86.3000)]},
                   {"id": "k1", "nombre": "Distribución", "hilos": 24, "origen_id": "m1", "destino_id": "m2",
                    "vertices": [_v(12.1010, -86.3000), _v(12.1020, -86.3000)]},
                   {"id": "k2", "nombre": "Acometida", "clase": "acometida", "tipo": "FLAT", "hilos": 12, "origen_id": "m2", "destino_id": "c",
                    "vertices": [_v(12.1020, -86.3000), _v(12.1021, -86.2995)]}]})
    return con, admin, p, r["ids"]


def test_the_zone_lists_what_can_be_added_and_the_cables_between_them(zona):
    con, admin, p, ids = zona
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    assert r["lienzo"]["nombre"] == "General" and r["colocados"] == [] and r["proyecto"]["puede_editar"] is True
    assert [(e["tipo"], e["nombre"]) for e in r["elementos"]] == [("mufa", "MF Dos"), ("mufa", "MF Uno"), ("nodo", "Nodo Jalapa")]      # no client, no pole
    assert {c["nombre"] for c in r["cables"]} == {"Troncal", "Distribución"}                                 # the drop goes to a client: not between mufas
    assert next(c for c in r["cables"] if c["nombre"] == "Troncal")["hilos"] == 48
    assert lienzo.lienzo(con, admin, proyecto_id=p["id"])["lienzo"]["id"] == r["lienzo"]["id"]               # the same canvas, not another one each time


def test_positions_are_saved_moved_and_taken_off_without_deleting_from_the_network(zona):
    con, admin, p, ids = zona
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    r = lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], version=r["lienzo"]["version"],
                              colocados=[{"elemento_id": ids["n"], "x": 100, "y": 50}, {"elemento_id": ids["m1"], "x": 300.456, "y": 50}])
    assert {c["elemento_id"]: (c["x"], c["y"]) for c in r["colocados"]} == {ids["n"]: (100.0, 50.0), ids["m1"]: (300.46, 50.0)}
    v = r["lienzo"]["version"]
    r = lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], version=v, colocados=[{"elemento_id": ids["n"], "x": 120, "y": 60}], quitados=[ids["m1"]])
    assert [(c["elemento_id"], c["x"], c["y"]) for c in r["colocados"]] == [(ids["n"], 120.0, 60.0)] and r["lienzo"]["version"] == v + 1
    assert len(r["elementos"]) == 3 and len(r["cables"]) == 2                    # nothing was deleted from the network
    with pytest.raises(db.ConflictoVersion):                                     # someone else saved in between
        lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], version=v, colocados=[])


def test_only_mufas_nodes_and_odf_of_the_zone_can_be_placed(zona):
    con, admin, p, ids = zona
    for malo in (ids["c"], ids["p"], 999999):
        with pytest.raises(db.DatosInvalidos):
            lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": malo, "x": 1, "y": 1}])
    for xy in ({"x": "abc", "y": 1}, {"x": 1, "y": None}, {"x": 1e12, "y": 1}, {"x": float("nan"), "y": 1}):
        with pytest.raises(db.DatosInvalidos):
            lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], **xy}])
    otro = proyectos.guardar(con, admin, datos={"nombre": "Otra zona", "codigo": "OTRA"})["proyecto"]
    with pytest.raises(db.DatosInvalidos):                                       # a mufa of another project
        lienzo.guardar_lienzo(con, admin, proyecto_id=otro["id"], colocados=[{"elemento_id": ids["m1"], "x": 1, "y": 1}])
    assert lienzo.lienzo(con, admin, proyecto_id=p["id"])["colocados"] == []


def test_a_reader_sees_the_canvas_but_cannot_change_it(zona):
    con, admin, p, ids = zona
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], "x": 10, "y": 20}])
    ana = usuarios.identificar(con, persona_visor="ana")                          # a reader with access to the project
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], ana["id"]]})
    r = lienzo.lienzo(con, ana, proyecto_id=p["id"])
    assert r["proyecto"]["puede_editar"] is False and len(r["colocados"]) == 1 and len(r["elementos"]) == 3
    with pytest.raises(db.SinPermiso):
        lienzo.guardar_lienzo(con, ana, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], "x": 1, "y": 1}])


def test_zones_list_counts_and_service_methods(zona):
    con, admin, p, ids = zona
    lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m1"], "x": 10, "y": 20}])
    z = next(z for z in lienzo.zonas(con, admin)["zonas"] if z["id"] == p["id"])
    assert (z["mufas"], z["nodos"], z["colocados"]) == (2, 1, 1)
    assert METODOS["lienzo_zonas"] is lienzo.zonas and METODOS["lienzo"] is lienzo.lienzo and METODOS["guardar_lienzo"] is lienzo.guardar_lienzo


def test_a_cable_between_two_placed_mufas_is_made_with_the_map_editor_service(zona):
    """The canvas draws the cable; creating it is `guardar_red` (same rules, metraje and hilos as the map editor)."""
    con, admin, p, ids = zona
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [
        {"id": "nuevo", "nombre": "Enlace Nodo-Dos", "clase": "distribucion", "hilos": 12, "origen_id": ids["n"], "destino_id": ids["m2"],
         "vertices": [_v(12.1000, -86.3000), _v(12.1020, -86.3000)]}]})
    assert lienzo.lienzo(con, admin, proyecto_id=p["id"])["cables"][-1]["nombre"] == "Enlace Nodo-Dos" and r["ids"]["nuevo"]


def test_a_cable_between_two_mufas_at_the_same_point_is_allowed(zona):
    """A parallel mufa sits on the same point as the other one: the cable between them has length zero (it used to be refused as «sus extremos están en el mismo punto»)."""
    con, admin, p, ids = zona
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [
        {"id": "par", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF Uno PARALELA", "lat": 12.1010, "lon": -86.3000}],
        "cables": []})
    paralela = r["ids"]["par"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [
        {"id": "nuevo", "nombre": "MF Uno – MF Uno PARALELA", "clase": "distribucion", "hilos": 24, "origen_id": ids["m1"], "destino_id": paralela,
         "vertices": [_v(12.1010, -86.3000), _v(12.1010, -86.3000)]}]})
    cable = next(c for c in lienzo.lienzo(con, admin, proyecto_id=p["id"])["cables"] if c["id"] == r["ids"]["nuevo"])
    assert cable["hilos"] == 24 and float(cable["longitud_m"]) == 0.0 and {cable["origen_id"], cable["destino_id"]} == {ids["m1"], paralela}
    with pytest.raises(db.DatosInvalidos):                                                    # the same element at both ends is still refused
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [
            {"id": "x", "nombre": "X", "origen_id": ids["m1"], "destino_id": ids["m1"], "vertices": [_v(12.1010, -86.3000), _v(12.1011, -86.3000)]}]})


def test_the_schema_keeps_its_reference_point_and_scale(zona):
    """The boxes are laid out by real coordinates from a reference point and a scale that the schema keeps, so everybody sees the same layout."""
    con, admin, p, ids = zona
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    assert r["lienzo"]["origen_lat"] is None and r["lienzo"]["origen_lon"] is None and r["lienzo"]["escala"] == 2
    r = lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], origen={"lat": 12.1015, "lon": -86.3}, escala=4.5, colocados=[{"elemento_id": ids["m1"], "x": -3_000_000, "y": 12}])
    assert (r["lienzo"]["origen_lat"], r["lienzo"]["origen_lon"], r["lienzo"]["escala"]) == (12.1015, -86.3, 4.5) and r["colocados"][0]["x"] == -3_000_000
    r = lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], colocados=[{"elemento_id": ids["m2"], "x": 1, "y": 2}])          # not sent: kept
    assert (r["lienzo"]["origen_lat"], r["lienzo"]["escala"]) == (12.1015, 4.5)
    for malo in ({"origen": {"lat": 99, "lon": 0}}, {"origen": {"lat": "x", "lon": 0}}, {"origen": {"lat": 1}}, {"escala": 0}, {"escala": 500}, {"escala": "alta"}):
        with pytest.raises(db.DatosInvalidos):
            lienzo.guardar_lienzo(con, admin, proyecto_id=p["id"], **malo)
