"""Visor v2, fase 8: subir un KMZ nuevo y poner la base del presupuesto al día (visor_rutas/redes/actualizar_red.py): comparar con red_puntos /
red_lineas (en una base de prueba), sincronizar, revertir exacto, y reemplazar el KMZ vigente guardando el anterior."""
import json

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_importar_kmz import _linea, _pm, hacer_kmz
from visor_rutas import kmz_capas, subidas
from visor_rutas.redes import actualizar_red as ar, db, importar_kmz, usuarios
from visor_rutas.redes.api import METODOS

KMZ_NUEVO = {
    "MUFAS": [_pm("MF UNO", -86.250, 12.130), _pm("MF DOS", -86.2603, 12.1403),      # DOS moved ~45 m: new + gone
              _pm("MF TRES", -86.270, 12.150), _pm("MF CUATRO", -86.280, 12.160)],    # CUATRO is new
    "FIBRA OPTICA": [_linea("L1", (-86.250, 12.130), (-86.256, 12.137), (-86.260, 12.140)),      # same ends, other trace: the same line
                     _linea("L2", (-86.280, 12.160), (-86.285, 12.165))],                           # new
    "POSTES DE CONCRETO": [_pm("P1", -86.251, 12.131),
                           _pm("P2", -86.25200001, 12.13200001),                    # moved a few millimetres: the same pole
                           _pm("P3", -86.253, 12.133), _pm("P4", -86.254, 12.134)],   # two new poles (the ones the route did not see)
}


@pytest.fixture(autouse=True)
def _nunca_el_presupuesto_real(monkeypatch):
    def prohibido():
        raise AssertionError("conectar_presupuesto sin la base de prueba")
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", prohibido)
    ar._cache_elementos.clear()
    subidas.almacen.reiniciar()
    yield
    ar._cache_elementos.clear()
    subidas.almacen.reiniciar()


@pytest.fixture
def mundo(con_redes, tmp_path, monkeypatch):
    carpeta = tmp_path / "red_kmz"
    carpeta.mkdir()
    (carpeta / "RED.kmz").write_bytes(hacer_kmz(KMZ_NUEVO, "RED"))
    monkeypatch.setenv("KMZ_PATH", str(carpeta))
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", tmp_path / "datos_kmz")
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    editor = usuarios.identificar(con, persona_visor="ed")
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE id = %s", (editor["id"],))
    editor = usuarios.identificar(con, persona_visor="ed")
    return con, admin, editor, carpeta


@pytest.fixture
def presupuesto(base_redes, monkeypatch):
    """The budget's tables as they were before the new KMZ: the old network, plus something the viewer published."""
    _, params = base_redes
    pg = db.conectar(params=params)
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.execute("CREATE TABLE public.red_puntos (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    pg.execute("CREATE TABLE public.red_lineas (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    pg.execute("INSERT INTO public.red_puntos (tabla_origen, categoria, nombre, geom, tipo) VALUES "
               "('mufa', 'mufa', 'MF UNO', ST_SetSRID(ST_MakePoint(-86.250, 12.130), 4326), 'mufa'),"
               "('mufa', 'mufa', 'MF DOS', ST_SetSRID(ST_MakePoint(-86.260, 12.140), 4326), 'mufa'),"
               "('mufa', 'mufa', 'MF TRES', ST_SetSRID(ST_MakePoint(-86.270, 12.150), 4326), 'mufa'),"
               "('postes de concreto', 'postes de concreto', 'P1', ST_SetSRID(ST_MakePoint(-86.251, 12.131), 4326), 'poste de concreto'),"
               "('postes de concreto', 'postes de concreto', 'P2', ST_SetSRID(ST_MakePoint(-86.252, 12.132), 4326), 'poste de concreto'),"
               "('postes de concreto', 'postes de concreto', 'P9', ST_SetSRID(ST_MakePoint(-86.290, 12.170), 4326), 'poste de concreto'),"      # gone from the KMZ
               "('visor', 'mufa', 'MF DEL VISOR', ST_SetSRID(ST_MakePoint(-86.5, 12.5), 4326), 'mufa')")                                     # published by the viewer: untouchable
    pg.execute("INSERT INTO public.red_lineas (tabla_origen, categoria, nombre, geom, tipo) VALUES "
               "('fibra optica', 'fibra optica', 'L1', ST_SetSRID(ST_GeomFromText('LINESTRING(-86.250 12.130, -86.255 12.135, -86.260 12.140)'), 4326), 'fibra óptica')")
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", lambda: db.conectar(params=params))
    yield pg
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.close()


def _estado(pg):
    return ({f["nombre"]: (f["tabla_origen"], f["tipo"], f["wkt"]) for f in pg.execute("SELECT nombre, tabla_origen, tipo, ST_AsText(geom) AS wkt FROM public.red_puntos").fetchall()},
            {f["nombre"]: (f["tabla_origen"], f["tipo"], f["wkt"]) for f in pg.execute("SELECT nombre, tabla_origen, tipo, ST_AsText(geom) AS wkt FROM public.red_lineas").fetchall()})


def test_compare_sees_new_and_gone_elements_and_ignores_tiny_shifts(mundo, presupuesto):
    con, admin, *_ = mundo
    r = ar.comparar(con, admin)["resumen"]
    assert r["archivo"] == "RED.kmz" and r["en_base"] == {"puntos": 7, "lineas": 1}
    assert r["nuevos"] == {"puntos": 4, "lineas": 1}                              # MF DOS (moved), MF CUATRO, P3, P4 / L2
    assert r["postes_nuevos"] == 2 and r["mufas_nuevas"] == 2
    assert r["sobran"] == {"puntos": 2, "lineas": 0}                              # the old MF DOS and P9; MF DEL VISOR is not listed
    assert {e["nombre"] for e in r["ejemplos_nuevos"]} == {"MF DOS", "MF CUATRO", "P3", "P4", "L2"}
    assert "MF DEL VISOR" not in {e["nombre"] for e in r["ejemplos_sobran"]}
    assert _estado(presupuesto)[0].keys() == {"MF UNO", "MF DOS", "MF TRES", "P1", "P2", "P9", "MF DEL VISOR"}      # comparing writes nothing


def test_synchronize_adds_what_is_missing_and_reverts_exactly(mundo, presupuesto):
    con, admin, *_ = mundo
    antes = _estado(presupuesto)
    r = ar.sincronizar(con, admin)
    assert r["insertados"] == {"puntos": 4, "lineas": 1} and r["eliminados"] == {"puntos": 0, "lineas": 0}
    puntos, lineas = _estado(presupuesto)
    assert {"MF CUATRO", "P3", "P4"} <= puntos.keys() and "P9" in puntos                                          # nothing removed without asking
    assert puntos["P3"][:2] == (ar.ORIGEN, "poste de concreto") and puntos["MF CUATRO"][:2] == (ar.ORIGEN, "mufa")   # the budget sees poles as poles, mufas as mufas
    assert "L2" in lineas and lineas["L2"][1] == "fibra óptica"
    again = ar.comparar(con, admin)["resumen"]
    assert again["nuevos"] == {"puntos": 0, "lineas": 0}                                                         # nothing left to add
    registro = ar.sincronizaciones(con, admin)["sincronizaciones"][0]
    assert registro["id"] == r["id"] and registro["revertida"] is False
    ar.revertir_sincronizacion(con, admin, id=r["id"])
    assert _estado(presupuesto) == antes
    with pytest.raises(db.DatosInvalidos):
        ar.revertir_sincronizacion(con, admin, id=r["id"])                                                       # already reverted


def test_synchronize_can_remove_what_the_kmz_no_longer_has_but_never_the_viewers(mundo, presupuesto):
    con, admin, *_ = mundo
    antes = _estado(presupuesto)
    r = ar.sincronizar(con, admin, quitar=True)
    assert r["eliminados"] == {"puntos": 2, "lineas": 0}
    puntos, _ = _estado(presupuesto)
    assert "P9" not in puntos and "MF DEL VISOR" in puntos and "MF CUATRO" in puntos
    segunda = ar.sincronizar(con, admin, quitar=True)                                                             # idempotent
    assert segunda["insertados"] == {"puntos": 0, "lineas": 0} and segunda["eliminados"] == {"puntos": 0, "lineas": 0}
    with pytest.raises(db.DatosInvalidos):
        ar.revertir_sincronizacion(con, admin, id=r["id"])                                                       # the last one first
    ar.revertir_sincronizacion(con, admin, id=segunda["id"])
    ar.revertir_sincronizacion(con, admin, id=r["id"])
    assert _estado(presupuesto) == antes                                                                         # ids and all


def test_it_refuses_to_remove_most_of_the_base_with_a_wrong_file(mundo, presupuesto):
    con, admin, _, carpeta = mundo
    (carpeta / "RED.kmz").write_bytes(hacer_kmz({"MUFAS": [_pm("A", -86.9, 12.9)] + [_pm(f"B{i}", -86.9 + i / 1000, 12.9) for i in range(1, 12)]}, "OTRA"))
    ar._cache_elementos.clear()
    antes = _estado(presupuesto)
    with pytest.raises(db.DatosInvalidos):
        ar.sincronizar(con, admin, quitar=True)
    assert _estado(presupuesto) == antes
    assert ar.sincronizar(con, admin)["eliminados"] == {"puntos": 0, "lineas": 0}                                 # adding is still fine


def test_only_administrators_touch_the_network(mundo, presupuesto):
    con, _, editor, _ = mundo
    for f, args in ((ar.estado, {}), (ar.comparar, {}), (ar.sincronizar, {}), (ar.subir_kmz, {"subida_id": "x"}), (ar.revertir_sincronizacion, {"id": "x"})):
        with pytest.raises(db.SinPermiso):
            f(con, editor, **args)
    for nombre in ("estado_actualizar_red", "subir_kmz_red", "comparar_red_presupuesto", "sincronizar_red_presupuesto", "revertir_sincronizacion_red"):
        assert nombre in METODOS


def _subida(crudo: bytes, nombre="nuevo.kmz") -> str:
    id_ = subidas.almacen.iniciar(nombre, len(crudo))
    subidas.almacen.parte(id_, 0, crudo)
    subidas.almacen.terminar(id_)
    return id_


def test_upload_replaces_the_kmz_in_force_and_keeps_the_old_one(mundo):
    con, admin, _, carpeta = mundo
    nuevo = hacer_kmz({"MUFAS": [_pm(f"M{i}", -86.2 - i / 1000, 12.1) for i in range(12)]}, "OTRA RED")
    r = ar.subir_kmz(con, admin, subida_id=_subida(nuevo, "Red Nueva (1).kmz"))
    assert r["archivo"] == "Red Nueva (1).kmz" and r["elementos"] == 12
    assert [p.name for p in carpeta.glob("*.kmz")] == ["Red Nueva (1).kmz"]                                        # one network at a time
    guardado = list((carpeta / "anteriores").glob("*_RED.kmz"))
    assert len(guardado) == 1 and guardado[0].stat().st_size > 0                                                  # the old one is kept
    assert kmz_capas.ruta_kmz().name == "Red Nueva (1).kmz"
    arbol = json.loads((kmz_capas.CARPETA_DATOS / "arbol.json").read_text(encoding="utf-8"))
    assert arbol["kmz"] == "Red Nueva (1).kmz"                                                                    # the map's cache is already the new one
    assert ar.estado(con, admin)["kmz"]["archivo"] == "Red Nueva (1).kmz"


def test_upload_rejects_what_is_not_a_network(mundo):
    con, admin, _, carpeta = mundo
    for crudo in (b"no es un zip", b"PK\x03\x04roto", hacer_kmz({"VACIA": [_pm("solo uno", -86.2, 12.1)]})):
        with pytest.raises(db.DatosInvalidos):
            ar.subir_kmz(con, admin, subida_id=_subida(crudo))
    assert [p.name for p in carpeta.glob("*.kmz")] == ["RED.kmz"] and not (carpeta / "anteriores").exists()      # nothing changed
    with pytest.raises(db.DatosInvalidos):
        ar.subir_kmz(con, admin, subida_id="no-existe-123")
