"""Pozos en la ruta → fibra en ducto (regla de Jan, 2026-10-20; business_rules.yaml: `ducto`, presupuesto.tramos_ducto):
donde la ruta pasa por pozos la fibra va en ducto (fila de ducto), sin postes; donde sale de los pozos hacia los postes queda un tramo aéreo y otro de
ducto (igual en un edificio: ducto adentro, aérea afuera). El material de fibra cuenta el aéreo y el ducto."""
from pathlib import Path

import psycopg
import pytest
import yaml

import db
import main
from presupuesto import calcular_presupuesto, new_pole_positions_in_spans, tramos_aereos, tramos_ducto
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)

REGLAS = yaml.safe_load((Path(__file__).resolve().parent.parent / "business_rules.yaml").read_text(encoding="utf-8"))
RUTA = [(12.1, -86.25), (12.105, -86.25)]
DUCTO = REGLAS["route"]["duct_install_row_label"]
AEREA_FLAT = REGLAS["route"]["aerial_install_row_label"]
AEREA_ADSS = REGLAS["route"]["adss_install_row_label"]
EXISTENTE = REGLAS["poles"]["existing_pole_row_label"]
NUEVO = REGLAS["poles"]["new_pole_row_label"]


# ---------------------------------------------------------------------------- tramos

def test_without_wells_nothing_goes_in_duct():
    assert tramos_ducto(500, [], REGLAS) == [] and tramos_aereos(500, []) == [(0.0, 500.0)] and tramos_aereos(0, []) == []


@pytest.mark.parametrize("pozos, esperado", [
    ([10, 30], [(0.0, 30.0)]),                          # wells at the start: duct from the connection mufa up to the last well
    ([440, 470], [(440.0, 500.0)]),                     # wells at the client's end (a building): duct up to the client
    ([10, 480], [(0.0, 10.0), (480.0, 500.0)]),         # far apart: two runs, aerial in the middle
    ([20, 100, 180], [(0.0, 180.0)]),                   # 80 m apart: one run
    ([250], []),                                        # one well in the middle of the street: nothing to run duct through
    ([250, 300], [(250.0, 300.0)]),                     # two wells in the middle: the stretch between them
    ([5, 495], [(0.0, 5.0), (495.0, 500.0)]),
    ([0, 60, 120, 180, 240, 300, 360, 420, 480], [(0.0, 500.0)])])   # wells all along: everything is duct (and the runs that touch are one)
def test_duct_runs_follow_the_wells(pozos, esperado):
    assert tramos_ducto(500, pozos, REGLAS) == esperado


def test_the_aerial_stretches_are_the_rest():
    assert tramos_aereos(500, [(0.0, 30.0)]) == [(30.0, 500.0)]
    assert tramos_aereos(500, [(0.0, 10.0), (480.0, 500.0)]) == [(10.0, 480.0)]
    assert tramos_aereos(500, [(0.0, 500.0)]) == [] and tramos_aereos(500, [(100.0, 200.0)]) == [(0.0, 100.0), (200.0, 500.0)]


def test_poles_are_placed_only_along_the_aerial_stretches():
    spans = [(200.0, 500.0)]
    nuevos = new_pole_positions_in_spans(spans, 50, [], 60, 100)
    assert nuevos == [250.0, 300.0, 350.0, 400.0, 450.0, 500.0]                         # every 50 m from the end of the duct
    assert new_pole_positions_in_spans(spans, 50, [330.0], 60, 100) == [250.0, 300.0, 380.0, 430.0, 480.0]


# ---------------------------------------------------------------------------- cantidades

def q(duct_spans=None, **k):
    return calcular_presupuesto(500, RUTA, REGLAS, existing_pole_positions_m=k.pop("posiciones", []), duct_spans=duct_spans, **k)


def test_without_duct_the_budget_is_the_same_as_before():
    sin = q()
    assert sin[DUCTO] == 0 and sin[AEREA_ADSS] == 655 and sin[AEREA_FLAT] == 0 and sin[NUEVO] == 10
    assert q(duct_spans=None) == q(duct_spans=[])                                          # nothing changes unless there are wells


def test_the_duct_metres_leave_the_aerial_row_and_the_poles():
    con = q(duct_spans=[(0.0, 200.0)])
    assert con[DUCTO] == 200 and con[AEREA_ADSS] == 655 - 200 and con[AEREA_FLAT] == 0           # aerial + duct = the whole cable
    assert con[NUEVO] == 6                                                                  # poles only on the 300 m that go on poles (10 without wells)
    # poles that already stand inside the duct stretch are not used; those in the aerial stretch are
    otra = q(duct_spans=[(0.0, 200.0)], posiciones=[100.0, 250.0])
    assert otra[EXISTENTE] == 1 and otra[NUEVO] == q(duct_spans=[(0.0, 200.0)], posiciones=[250.0])[NUEVO]
    # everything in duct: no aerial fibre, no poles
    todo = q(duct_spans=[(0.0, 500.0)], posiciones=[100.0])
    assert todo[DUCTO] == 655 and todo[AEREA_ADSS] == 0 and todo[AEREA_FLAT] == 0 and todo[NUEVO] == 0 and todo[EXISTENTE] == 0
    # two stretches (duct at both ends, aerial in the middle)
    dos = q(duct_spans=[(0.0, 10.0), (480.0, 500.0)])
    assert dos[DUCTO] == 30 and dos[AEREA_ADSS] == 655 - 30 and dos[NUEVO] == len(new_pole_positions_in_spans([(10.0, 480.0)], 50, [], 60, 100))


def test_a_short_route_with_wells_keeps_the_flat_cable_rows():
    corta = calcular_presupuesto(100, RUTA, REGLAS, existing_pole_positions_m=[], duct_spans=[(0.0, 40.0)])
    final = calcular_presupuesto(100, RUTA, REGLAS, existing_pole_positions_m=[])[AEREA_FLAT]
    assert corta[DUCTO] == 40 and corta[AEREA_FLAT] == final - 40 and corta[AEREA_ADSS] == 0


def test_the_fibre_material_counts_the_aerial_and_the_duct_rows_of_the_cable_used():
    sin = main.hardware_fibra(REGLAS, "flat", False)
    flat, adss = REGLAS["cable"]["flat_material_label"], REGLAS["cable"]["adss_material_label"]
    assert sin[flat] == {"same_as_install": AEREA_FLAT} and sin[adss] == {"same_as_install": AEREA_ADSS}
    con = main.hardware_fibra(REGLAS, "flat", True)
    assert con[flat] == {"same_as_install": [AEREA_FLAT, DUCTO]} and con[adss] == {"same_as_install": AEREA_ADSS}          # only the cable used
    assert main.hardware_fibra(REGLAS, "adss", True)[adss] == {"same_as_install": [AEREA_ADSS, DUCTO]}
    assert REGLAS["cable"]["fiber_material_from_install"][flat] == {"same_as_install": AEREA_FLAT}                         # the rules are not modified


def test_the_excel_sums_the_rows_of_a_material():
    import openpyxl
    import excel_generator
    ws = openpyxl.load_workbook(Path(__file__).resolve().parent.parent / "templates" / "PlantilaEjemploPresupuesto.xlsx")["Presupuesto"]
    asignaciones = excel_generator._hardware_assignments(ws, main.hardware_fibra(REGLAS, "flat", True))
    formulas = {k: v.value if hasattr(v, "value") else str(v) for k, v in asignaciones.items() if not isinstance(v, int)}
    assert "=G12+G28" in set(formulas.values()) or "G12+G28" in set(formulas.values()), formulas             # flat material = aerial flat + duct
    simple = excel_generator._hardware_assignments(ws, main.hardware_fibra(REGLAS, "flat", False))
    assert not any("G28" in str(getattr(v, "value", v)) for v in simple.values())


# ---------------------------------------------------------------------------- en PostgreSQL

@pytest.mark.pozos_reales
def test_the_wells_of_the_route_come_from_postgis(base_redes, con_redes, monkeypatch):
    from visor_rutas.redes import db as redes_db
    _, params = base_redes
    pg = redes_db.conectar(params=params)
    pg.execute("DROP TABLE IF EXISTS public.red_puntos")
    pg.execute("CREATE TABLE public.red_puntos (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text)")
    for tipo, lat, lon in (("pozo", 12.1010, -86.25), ("pozo", 12.1020, -86.25), ("pozo", 12.1500, -86.25), ("poste de concreto", 12.1030, -86.25), ("pozo", 12.1040, -86.2510)):
        pg.execute("INSERT INTO public.red_puntos (tabla_origen, categoria, nombre, geom, tipo) VALUES ('t', %s, 'x', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)", (tipo, lon, lat, tipo))
    real = psycopg.connect
    monkeypatch.setattr(db.psycopg, "connect", lambda **k: real(**{**params, "connect_timeout": 5, "options": "-c search_path=redes,public"}))
    try:
        ruta = "LINESTRING(-86.25 12.1000, -86.25 12.1050)"
        posiciones = db.find_pozos_near_route(ruta, 15)
        assert len(posiciones) == 2 and 100 < posiciones[0] < 120 and 215 < posiciones[1] < 230       # the two wells on the street, in metres from the start
        assert posiciones == sorted(posiciones)                                                        # the far one, the pole and the one 100 m aside are not
        assert len(db.find_pozos_near_route(ruta, 200)) == 3                                           # with a wider buffer the one 100 m aside counts too
        with pytest.raises(ValueError):
            db.find_pozos_near_route(ruta, -1)
    finally:
        pg.execute("DROP TABLE IF EXISTS public.red_puntos")
        pg.close()
