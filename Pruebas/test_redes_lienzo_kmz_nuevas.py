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


def test_a_mufa_renamed_in_the_kmz_after_it_was_linked_can_follow_the_new_name(zona):
    con, admin, p, ids = zona
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega(), acciones=[{"kmz_id": 2, "accion": "renombrar", "elemento_id": ids["m2"]}])
    assert lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())["nombres_cambiados"] == []              # same name as its KMZ point: nothing to do
    cambiado = KmzFalso([punto(1, "MF UNO", 12.1010, -86.3000), punto(2, "MF DOS CENTRO", 12.1020, -86.3000)])      # somebody renamed the point in the KMZ
    r = lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado)
    assert [(x["elemento_id"], x["nombre"], x["nombre_kmz"]) for x in r["nombres_cambiados"]] == [(ids["m2"], "MF DOS 1", "MF DOS CENTRO")] and r["nuevas"] == []
    r = lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado, acciones=[{"accion": "actualizar_nombre", "elemento_id": ids["m2"]}])
    assert r["nombres_actualizados"] == 1 and r["nombres_cambiados"] == []
    fila = con.execute("SELECT nombre, ref_externa FROM redes.elementos WHERE id = %s", (ids["m2"],)).fetchone()
    assert fila["nombre"] == "MF DOS CENTRO" and fila["ref_externa"]["kmz"]["nombre"] == "MF DOS CENTRO" and fila["ref_externa"]["kmz"]["kmz_punto_id"] == 2
    assert len(lienzo.lienzo(con, admin, proyecto_id=p["id"])["cables"]) == 2                                      # its cables stay
    with pytest.raises(db.DatosInvalidos):                                                                          # already done: a stale list is refused
        lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado, acciones=[{"accion": "actualizar_nombre", "elemento_id": ids["m2"]}])


def test_rename_a_mufa_by_hand_from_the_schema(zona):
    con, admin, p, ids = zona
    r = lienzo.renombrar_elemento(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nombre="  MF   UNO   NUEVA ")
    assert r["elemento"]["nombre"] == "MF UNO NUEVA" and r["elemento"]["version"] > 1
    assert next(e for e in lienzo.lienzo(con, admin, proyecto_id=p["id"])["elementos"] if e["id"] == ids["m1"])["nombre"] == "MF UNO NUEVA"
    with pytest.raises(db.DatosInvalidos):
        lienzo.renombrar_elemento(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nombre="   ")
    with pytest.raises(db.ConflictoVersion):
        lienzo.renombrar_elemento(con, admin, proyecto_id=p["id"], elemento_id=ids["m1"], nombre="OTRA", version=1)
    ana = usuarios.identificar(con, usuario_windows="ana")
    with pytest.raises(db.SinPermiso):
        lienzo.renombrar_elemento(con, ana, proyecto_id=p["id"], elemento_id=ids["m1"], nombre="X")
    assert METODOS["renombrar_elemento_zona"] is lienzo.renombrar_elemento


def test_a_name_the_person_chose_is_not_undone_by_the_kmz_list(zona):
    con, admin, p, ids = zona
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega(), acciones=[{"kmz_id": 2, "accion": "renombrar", "elemento_id": ids["m2"]}])
    lienzo.renombrar_elemento(con, admin, proyecto_id=p["id"], elemento_id=ids["m2"], nombre="MF DOS (mi nombre)")        # by hand, the KMZ still says «MF DOS 1»
    assert lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())["nombres_cambiados"] == []              # not offered: it is not a KMZ change
    cambiado = KmzFalso([punto(1, "MF UNO", 12.1010, -86.3000), punto(2, "MF DOS CENTRO", 12.1020, -86.3000)])            # but if the KMZ changes it again, it is offered
    r = lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado)
    assert [(x["nombre"], x["nombre_kmz"]) for x in r["nombres_cambiados"]] == [("MF DOS (mi nombre)", "MF DOS CENTRO")]
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado, acciones=[{"accion": "actualizar_nombre", "elemento_id": ids["m2"]}])
    assert lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=cambiado)["nombres_cambiados"] == []                      # followed; and no longer offered


def test_a_rename_made_to_the_kmz_in_the_viewer_reaches_the_zone(zona):
    from visor_rutas.redes import kmz_cambios
    con, admin, p, ids = zona
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega(), acciones=[{"kmz_id": 2, "accion": "renombrar", "elemento_id": ids["m2"]}])
    # the viewer renames the KMZ point «MF DOS 1» (the KMZ file / red_puntos keeps the old name: the change lives in kmz_cambios)
    kmz_cambios.editar(con, admin, clave="RED/JINOTEGA/MUFA|mf dos 1|12.10200,-86.30000", carpeta="RED/JINOTEGA/MUFA", tipo="punto",
                       antes={"nombre": "MF DOS 1", "lat": 12.1020, "lon": -86.3000}, nombre="MUFA FOSC DOS SANGRIA")
    r = lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())
    assert [(x["nombre"], x["nombre_kmz"]) for x in r["nombres_cambiados"]] == [("MF DOS 1", "MUFA FOSC DOS SANGRIA")] and r["en_kmz"] == 4
    assert "MF DOS 1" not in [n["nombre"] for n in r["nuevas"]]                                    # and it is not offered as a new mufa either
    lienzo.aplicar_mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega(), acciones=[{"accion": "actualizar_nombre", "elemento_id": ids["m2"]}])
    assert con.execute("SELECT nombre FROM redes.elementos WHERE id = %s", (ids["m2"],)).fetchone()["nombre"] == "MUFA FOSC DOS SANGRIA"
    assert lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())["nombres_cambiados"] == []
    # a point taken off the map in the viewer is not offered to the zone
    kmz_cambios.borrar(con, admin, clave="RED/JINOTEGA/RESERVA|mf lejana|12.11000,-86.30000", carpeta="RED/JINOTEGA/RESERVA", tipo="punto",
                       antes={"nombre": "MF LEJANA", "lat": 12.1100, "lon": -86.3000})
    assert "MF LEJANA" not in [n["nombre"] for n in lienzo.mufas_kmz(con, admin, proyecto_id=p["id"], kmz=_kmz_jinotega())["nuevas"]]
