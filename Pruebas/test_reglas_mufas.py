"""Reglas de Jan del 2026-10-20 sobre qué mufas se pueden usar (reglas_mufas.py, business_rules.yaml: `mufas_no_usables`):

  - una mufa de corte («MC»), aérea o de punta plana / plancha NO es punto de conexión (por el nombre y por la carpeta del KMZ), no cuenta como mufa
    intervenida y la ruta de fusión pasa de largo (en la ruta de fusión tampoco se usa un mini nodo);
  - los empalmes del respaldo = mufas intervenidas hasta el splitter + 2 del splitter (solo si se conecta a una mufa existente);
  - la visita técnica se presupuesta si el cliente está en una plaza, un edificio o un centro comercial.
"""
import os
from pathlib import Path

import psycopg
import pytest
import yaml

import db
import reglas_mufas
from presupuesto import calcular_presupuesto, requiere_visita_tecnica
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures: the migrations create PostGIS in the test database)

REGLAS = yaml.safe_load((Path(__file__).resolve().parent.parent / "business_rules.yaml").read_text(encoding="utf-8"))
CFG = reglas_mufas.configuracion(REGLAS)


# ---------------------------------------------------------------------------- por el nombre

@pytest.mark.parametrize("nombre, motivo", [
    ("MC", "de corte"), ("MC FOSC ", "de corte"), ("MF MC PLAZA", "de corte"), ("MF DE CORTE", "de corte"), ("mufa de corte #3", "de corte"),
    ("MF CORTE LA FINCA", "de corte"), ("MF AÉREA CENTRO", "aérea"), ("mf aerea", "aérea"), ("MUFA AEREA 2", "aérea"),
    ("MF PUNTA PLANA ALTOS", "punta plana"), ("MF PUNTA  PLANCHA", "punta plana"), ("MF PLANCHA 3", "punta plana"), ("mf punta plana", "punta plana")])
def test_unusable_mufas_are_recognised_by_name(nombre, motivo):
    assert reglas_mufas.motivo(nombre, CFG) == motivo and not reglas_mufas.usable(nombre, CFG)


@pytest.mark.parametrize("nombre", [
    "MF FERRETERIA LA PRINCIPAL", "MF FUERZA AEREA", "MF CORTEZA", "MF AEREAL", "MF MCDONALDS", "MF PLANA SUR", "MF PUNTA CANA", "MF MARCO", "",
    "MF MINI NODO CENTRO"])
def test_usable_mufas_stay_usable(nombre):
    assert reglas_mufas.usable(nombre, CFG), nombre                        # a place is not an aerial mufa; whole words only (MC, not MCDONALDS)


def test_a_mini_nodo_is_left_out_of_the_fusion_route_only():
    assert reglas_mufas.motivo("MF MINI NODO CENTRO", CFG) is None and reglas_mufas.motivo("MN SUR", CFG) is None            # as connection / count: not a rule
    assert reglas_mufas.motivo("MF MINI NODO CENTRO", CFG, en_ruta_de_fusion=True) == "mini nodo"
    assert reglas_mufas.motivo("MN SUR", CFG, en_ruta_de_fusion=True) == "mini nodo"
    from visor_rutas import ruta_fusion_plan as plan
    assert plan.motivo_no_tocar("MF MINI NODO CENTRO", plan.reglas()) == "mini nodo" and plan.motivo_no_tocar("MF PUNTA PLANA 1", plan.reglas()) == "punta plana"
    assert plan.motivo_no_tocar("MF FERRETERIA", plan.reglas()) is None


def test_filtering_a_chain_keeps_only_the_usable_mufas():
    class M:
        def __init__(self, nombre):
            self.nombre = nombre
    cadena = [M("MF A"), M("MC FOSC"), M("MF AEREA 5"), M("MF PUNTA PLANA"), M("MF B"), M(None)]
    assert [m.nombre for m in reglas_mufas.filtrar(cadena, CFG)] == ["MF A", "MF B", None]
    assert reglas_mufas.filtrar([], CFG) == []


def test_the_rules_come_from_the_yaml_and_have_defaults():
    assert set(CFG["motivos"]) == {"de corte", "aérea", "punta plana"} and CFG["excepciones"] == ["FUERZA AEREA"]
    vacia = reglas_mufas.configuracion({})                                  # without the section the same defaults apply
    assert reglas_mufas.motivo("MC", vacia) == "de corte" and reglas_mufas.motivo("MF PLANCHA", vacia) == "punta plana"
    solo_corte = reglas_mufas.configuracion({"mufas_no_usables": {"motivos": {"de corte": ["CORTE"]}, "excepciones": []}})
    assert reglas_mufas.motivo("MF AEREA", solo_corte) is None and reglas_mufas.motivo("MF FUERZA AEREA CORTE", solo_corte) == "de corte"
    assert any(k in REGLAS["excluded_tipo_keywords"] for k in ("de corte", "aerea", "punta plana", "plancha"))      # and the KMZ folders too


# ---------------------------------------------------------------------------- en PostgreSQL (la base de prueba)

@pytest.fixture
def puntos(base_redes, con_redes, monkeypatch):
    """red_puntos with mufas around (12.1, -86.25), the nearest ones of the kinds that cannot be used, and db.py pointed at that database."""
    _, params = base_redes
    from visor_rutas.redes import db as redes_db
    pg = redes_db.conectar(params=params)
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.execute("CREATE TABLE public.red_puntos (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    pg.execute("CREATE TABLE public.red_lineas (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    filas = [("MC", "mufa", 12.1000), ("MF DE CORTE LA FINCA", "mufa", 12.1001), ("MF AÉREA CENTRO", "mufa", 12.1002), ("MF PUNTA PLANA 4", "mufa", 12.1003),
             ("MF PLANCHA", "mufa", 12.1004), ("MF SIN NOMBRE DE CORTE", "mufa de corte", 12.1005),          # by the folder of the KMZ
             ("MF FUERZA AEREA", "mufa", 12.1010), ("MF BUENA", "mufa", 12.1020), ("MF MAS LEJOS", "mufa", 12.1100)]
    for nombre, tipo, lat in filas:
        pg.execute("INSERT INTO public.red_puntos (tabla_origen, categoria, nombre, geom, tipo) VALUES ('t', %s, %s, ST_SetSRID(ST_MakePoint(-86.25, %s), 4326), %s)", (tipo, nombre, lat, tipo))
    real = psycopg.connect                                                  # db.psycopg IS psycopg: keep the real one before replacing it
    monkeypatch.setattr(db.psycopg, "connect", lambda **k: real(**{**params, "connect_timeout": 5, "options": "-c search_path=redes,public"}))
    yield pg
    pg.execute("DROP TABLE IF EXISTS public.red_puntos, public.red_lineas")
    pg.close()


def test_the_connection_point_is_never_a_mufa_of_those_kinds(puntos):
    excluidas = REGLAS["excluded_tipo_keywords"]
    # without the name rule the nearest mufa is an unusable one (the old behaviour)
    assert db.find_nearest_connection_point(12.1000, -86.25, [], 500).nombre == "MC"
    # with the rules (names and folders): the first usable one, which is a place with «AEREA» in its name, not an aerial mufa
    elegido = db.find_nearest_connection_point(12.1000, -86.25, excluidas, 500, excluded_names=reglas_mufas.patrones_sql(CFG))
    assert elegido.nombre == "MF FUERZA AEREA"
    # candidates to compare by route are cleaned the same way
    nombres = [c.nombre for c in db.find_connection_candidates(12.1000, -86.25, excluidas, 5000, 10, excluded_names=reglas_mufas.patrones_sql(CFG))]
    assert nombres == ["MF FUERZA AEREA", "MF BUENA", "MF MAS LEJOS"]
    # and so are the mufas the new route goes through (they are not intervened)
    ruta = "LINESTRING(-86.25 12.0999, -86.25 12.1025)"
    cerca = [m.nombre for m in db.find_mufas_near_route(ruta, 400, excluidas, excluded_names=reglas_mufas.patrones_sql(CFG))]
    assert cerca == ["MF FUERZA AEREA", "MF BUENA"]


def test_the_regex_of_the_names_matches_what_python_matches(puntos):
    excluida, excepcion = reglas_mufas.patrones_sql(CFG)
    nombres = ["MC", "MF MC 3", "MF DE CORTE", "MF CORTES NORTE", "MF AÉREA CENTRO", "mf aerea", "MF PUNTA   PLANA", "MF PLANCHA", "MF CORTEZA", "MF AEREAL",
               "MF MCDONALDS", "MF FUERZA AEREA", "MF BUENA", "MF MINI NODO", "MN SUR"]
    for nombre in nombres:
        en_sql = puntos.execute("SELECT (%s ~* %s AND NOT (%s ~* %s)) AS en_sql", (nombre, excluida, nombre, excepcion)).fetchone()["en_sql"]
        assert en_sql == (reglas_mufas.motivo(nombre, CFG) is not None), nombre
    assert reglas_mufas.patrones_sql(reglas_mufas.configuracion({"mufas_no_usables": {"motivos": {"de corte": []}}}))[0] is None      # no words: nothing to leave out


# ---------------------------------------------------------------------------- empalmes y visita técnica

def test_splices_are_the_mufas_plus_two_of_the_splitter():
    q = lambda **k: calcular_presupuesto(500, [(12.1, -86.25), (12.105, -86.25)], REGLAS, **k)
    fila = REGLAS["splice"]["backbone_splice_row_label"]
    assert q(connection_is_mufa=True, mufa_count=3)[fila] == 3 + 2
    assert q(connection_is_mufa=True, mufa_count=1)[fila] == 1 + 2
    assert q(connection_is_mufa=True, mufa_count=3)[REGLAS["splice"]["mufa_intervention_row_label"]] == 3          # the intervention is only the mufas
    assert q(connection_is_reserve=True, mufa_count=0)[fila] == 0                                                 # a reserva installs a new mufa: no splitter splices
    assert q(connection_is_mufa=False, mufa_count=2)[fila] == 2


def test_technical_visit_only_in_a_plaza_a_building_or_a_mall():
    textos = lambda *t: requiere_visita_tecnica(list(t), REGLAS)
    for cliente in ("Plaza Inter", "CENTRO COMERCIAL GALERIAS", "Edificio Banpro", "Oficina en edificio central", "centro  comercial metrocentro", "CC Multicentro"):
        assert textos(cliente), cliente
    assert textos("Juan Perez", "instalar en la casa", "Residencial") is False
    assert textos("Plazoleta Maria", "") is False and textos("Edificacion Sur") is False and textos("Maria Plazaola") is False          # whole words only\n    assert textos("Edificios del Valle", "") is True                                                              # the plural too
    assert textos("Juan Perez", "es en la plaza de Granada", "Empresarial") is True                            # the ticket comment too
    assert textos(None, None, None) is False
    fila = REGLAS["technical_visit"]["visit_row_label"]
    base = lambda **k: calcular_presupuesto(100, [(12.1, -86.25), (12.101, -86.25)], REGLAS, **k)
    assert base()[fila] == 0 and base(technical_visit=False)[fila] == 0 and base(technical_visit=True)[fila] == 1


def test_reservas_are_points_of_the_folder_or_poles_whose_name_says_rsv(puntos):
    for nombre, tipo, lat in (("RESERVA ESQUINA", "reserva", 12.2000), ("PM_I7573 RSV", "poste de madera", 12.2002), ("PC_44 RVA", "poste de concreto", 12.2004),
                              ("PC_45", "poste de concreto", 12.2001), ("PC_46 RESERVADO ASI", "poste de concreto", 12.2003),          # a pole without the word / a longer word
                              ("RSV LEJANA", "reserva", 12.3000), ("RVA MAL ESTADO", "reserva mal estado", 12.2005)):
        puntos.execute("INSERT INTO public.red_puntos (tabla_origen, categoria, nombre, geom, tipo) VALUES ('t', %s, %s, ST_SetSRID(ST_MakePoint(-86.25, %s), 4326), %s)", (tipo, nombre, lat, tipo))
    palabras = reglas_mufas.regex_palabras(["RSV", "RVA", "RESERVA"])
    r = db.find_reservas_cercanas(12.2000, -86.25, 400, palabras, REGLAS["excluded_tipo_keywords"], limit=5)
    assert [x.nombre for x in r] == ["RESERVA ESQUINA", "PM_I7573 RSV", "PC_44 RVA"] and r[0].is_reserve and r[0].distance_m < 1 and 20 < r[1].distance_m < 30
    assert [x.nombre for x in db.find_reservas_cercanas(12.2000, -86.25, 400, palabras, [], limit=1)] == ["RESERVA ESQUINA"]
    assert [x.nombre for x in db.find_reservas_cercanas(12.3000, -86.25, 50, palabras, REGLAS["excluded_tipo_keywords"])] == ["RSV LEJANA"]        # only what is within the radius
    assert reglas_mufas.regex_palabras([]) is None
