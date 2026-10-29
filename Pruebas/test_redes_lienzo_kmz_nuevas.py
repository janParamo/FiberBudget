"""Esquema de zona: las mufas del KMZ que la zona no tiene (nuevas, o la misma renombrada). Caso de Jinotega: dos mufas con el mismo nombre y las mismas coordenadas en el Visio
que el KMZ ya separó como «… 1» y «… 2»: la lista de la zona las ofrece y se pueden agregar o renombrar la que ya estaba."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from test_redes_lienzo_kmz import KmzFalso, punto
from visor_rutas.redes import db, lienzo, proyectos, usuarios
from visor_rutas.redes.api import METODOS


def _kmz_jinotega():
    return KmzFalso([punto(1, "MF UNO", 12.1010, -86.3000),                              # the zone already has it (same name, same place)
                     punto(2, "MF DOS 1", 12.1020, -86.3000),                            # MF Dos renamed: right on it
                     punto(3, "MF DOS 2", 12.1032, -86.3000),                            # the other mufa that used to have the same name: 130 m away
                     punto(4, "MF LEJANA", 12.1100, -86.3000, categoria="reserva"),      # a new reserve
                     punto(5, "POSTE 7", 12.1020, -86.3001, categoria="poste de concreto")])  # never a mufa


def test_the_zone_lists_what_the_kmz_has_and_it_does_not(zona):
    con, admin, p, ids = zona
    r = lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())
    assert [n["nombre"] for n in r["nuevas"]] == ["MF DOS 1", "MF DOS 2", "MF LEJANA"] and r["en_kmz"] == 4 and r["en_zona"] == 3
    uno, dos, lejana = r["nuevas"]
    assert uno["cercana"]["id"] == ids["m2"] and uno["cercana"]["nombre"] == "MF Dos" and uno["cercana"]["distancia_m"] < 1       # probably MF Dos renamed
    assert dos["cercana"] is None and lejana["cercana"] is None and lejana["categoria"] == "reserva"                              # 130 m is another mufa
    assert METODOS["mufas_kmz_zona"] is lienzo.mufas_kmz and METODOS["aplicar_mufas_kmz_zona"] is lienzo.aplicar_mufas_kmz


def test_rename_the_mufa_that_was_there_and_add_the_other_ones(zona):
    con, admin, p, ids = zona
    kmz = _kmz_jinotega()
    r = lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=kmz, acciones=[
        {"kmz_id": 2, "accion": "renombrar", "elemento_id": ids["m2"]}, {"kmz_id": 3, "accion": "agregar"}, {"kmz_id": 4, "accion": "agregar"}])
    assert (r["renombradas"], r["agregadas"]) == (1, 2) and r["nuevas"] == []                       # nothing is missing any more
    zona_ = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    nombres = sorted(e["nombre"] for e in zona_["elementos"])
    assert nombres == ["MF DOS 1", "MF DOS 2", "MF LEJANA", "MF Uno", "Nodo Jalapa"]                # MF Dos is now «MF DOS 1» (its cables stay), two new ones
    assert len(zona_["cables"]) == 2                                                                # the cable of MF Dos still ends in it
    nueva = next(e for e in zona_["elementos"] if e["nombre"] == "MF DOS 2")
    assert (round(nueva["lat"], 4), round(nueva["lon"], 4), nueva["subtipo"], nueva["ubicacion_fuente"]) == (12.1032, -86.3, "empalme", "real")
    assert next(e for e in zona_["elementos"] if e["nombre"] == "MF LEJANA")["subtipo"] == "reserva"
    renombrada = con.execute("SELECT nombre, estado_migracion, ref_externa FROM redes.elementos WHERE id = %s", (ids["m2"],)).fetchone()
    assert renombrada["nombre"] == "MF DOS 1" and renombrada["estado_migracion"] == "editada" and renombrada["ref_externa"]["kmz"]["kmz_punto_id"] == 2
    acciones = [f["accion"] for f in con.execute("SELECT accion FROM redes.historial WHERE entidad = 'elemento' AND accion IN ('crear', 'editar') ORDER BY id DESC LIMIT 3").fetchall()]
    assert sorted(acciones) == ["crear", "crear", "editar"]


def test_a_stale_list_is_refused_and_nothing_is_half_done(zona):
    con, admin, p, ids = zona
    kmz = _kmz_jinotega()
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=kmz, acciones=[{"kmz_id": 4, "accion": "agregar"}])
    with pytest.raises(db.DatosInvalidos):                                                           # someone already added it: the page's list is old
        lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=kmz, acciones=[{"kmz_id": 3, "accion": "agregar"}, {"kmz_id": 4, "accion": "agregar"}])
    nombres = sorted(e["nombre"] for e in lienzo.lienzo(con, admin, proyecto_id=p["id"])["elementos"])
    assert "MF DOS 2" not in nombres and nombres.count("MF LEJANA") == 1                             # the valid one of that batch was not applied either
    with pytest.raises(db.DatosInvalidos):                                                           # renaming a mufa of another zone
        otra = proyectos.guardar(con, admin, datos={"nombre": "Otra", "codigo": "OTRA"})["proyecto"]
        lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=otra["id"], kmz=kmz, acciones=[{"kmz_id": 2, "accion": "renombrar", "elemento_id": ids["m2"]}])
    with pytest.raises(db.DatosInvalidos):
        lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=kmz, acciones=[])


def test_without_the_kmz_it_says_so_and_a_reader_cannot_apply(zona, monkeypatch):
    con, admin, p, ids = zona
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: None)
    with pytest.raises(db.DatosInvalidos):
        lienzo.mufas_kmz(con, admin, proyecto_id=p["id"])
    ana = usuarios.identificar(con, persona_visor="ana")
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], ana["id"]]})
    with pytest.raises(db.SinPermiso):
        lienzo.aplicar_mufas_kmz(con, ana, proyecto_id=p["id"], kmz=_kmz_jinotega(), acciones=[{"kmz_id": 4, "accion": "agregar"}])
    assert lienzo.mufas_kmz(con, ana, proyecto_id=p["id"], kmz=_kmz_jinotega())["nuevas"]            # but she can see what is missing
