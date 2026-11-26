"""Calibración de la ruta (routing.calibrar / routing.get_route): una ruta de Google en auto que da una vuelta enorme para un cliente cercano se
cambia por el camino a pie o, si el cliente está muy cerca, por la línea recta; las rutas normales no se tocan ni piden nada más."""
import pytest

import main  # noqa: F401  (loads the project modules as in the whole suite)
import routing
from routing import Route

ORIGEN = (12.071701, -86.318896)
CLIENTE = (12.071929, -86.318577)                       # ≈ 43 m en línea recta (el caso de la captura)
LEJOS = (12.0809, -86.3189)                             # ≈ 1 km


ANTIGUO = {**routing.POR_DEFECTO, "always_walking": False}              # the mode that only asks walking for a big detour


def auto(metros):
    return Route(metros, 60.0, [ORIGEN, (12.07, -86.32), CLIENTE])


def a_pie(metros):
    return lambda o, d: Route(metros, 300.0, [o, d], "walking")


def test_the_straight_distance_of_the_case_is_about_43_m():
    assert routing._recta_m(ORIGEN, CLIENTE) == pytest.approx(43, abs=3)


def test_without_always_walking_a_normal_route_is_not_touched_and_walking_is_not_asked():
    preguntas = []
    r = routing.calibrar(auto(1200), ORIGEN, LEJOS, lambda o, d: preguntas.append(1), cfg=ANTIGUO)             # 1.2 km for 1 km: normal
    assert r.modo == "driving" and r.aviso is None and preguntas == []
    corto = auto(150)                                                                           # 150 m for 43 m: under 2 x 43 + 150
    assert routing.calibrar(corto, ORIGEN, CLIENTE, lambda o, d: preguntas.append(1), cfg=ANTIGUO) is corto and preguntas == []


def test_a_big_detour_uses_the_walking_path_when_it_is_clearly_shorter():
    assert routing.calibrar(auto(460), ORIGEN, (12.0745, -86.3189), a_pie(120), cfg=ANTIGUO).modo == "driving"   # ≈ 310 m straight, 460 m: not a detour
    cerca = (12.0731, -86.3186)                                                                   # ≈ 160 m straight: over direct_max_m
    r = routing.calibrar(auto(700), ORIGEN, cerca, a_pie(210), cfg=ANTIGUO)
    assert r.modo == "walking" and r.distance_m == 210 and "camino a pie" in r.aviso and "700" in r.aviso
    # walking that is not clearly shorter (> 85 %) keeps the driving route
    assert routing.calibrar(auto(700), ORIGEN, cerca, a_pie(650), cfg=ANTIGUO).modo == "driving"


def test_a_close_client_with_a_long_way_round_uses_the_straight_line():
    r = routing.calibrar(auto(460), ORIGEN, CLIENTE, a_pie(460), cfg=ANTIGUO)
    assert r.modo == "directa" and r.points == [ORIGEN, CLIENTE] and r.distance_m == pytest.approx(43, abs=3) and "línea recta" in r.aviso
    # the walking path wins when it is short enough not to need the straight line
    assert routing.calibrar(auto(460), ORIGEN, CLIENTE, a_pie(150), cfg=ANTIGUO).modo == "walking"


def test_far_clients_are_never_replaced_by_a_straight_line():
    lejos = (12.0745, -86.3189)                                                                   # ≈ 310 m: over direct_max_m
    r = routing.calibrar(auto(2500), ORIGEN, lejos, a_pie(2400), cfg=ANTIGUO)
    assert r.modo == "driving" and r.aviso is None


def test_a_walking_failure_leaves_the_driving_route_or_the_straight_line():
    def falla(o, d):
        raise routing.RouteNotFound("sin ruta a pie")
    assert routing.calibrar(auto(460), ORIGEN, CLIENTE, falla, cfg=ANTIGUO).modo == "directa"
    assert routing.calibrar(auto(700), ORIGEN, (12.0731, -86.3186), falla, cfg=ANTIGUO).modo == "driving"


def test_it_can_be_switched_off_and_tuned():
    assert routing.calibrar(auto(460), ORIGEN, CLIENTE, a_pie(100), cfg={**routing.POR_DEFECTO, "enabled": False}).modo == "driving"
    assert routing.calibrar(auto(460), ORIGEN, CLIENTE, None, cfg={**routing.POR_DEFECTO, "direct_max_m": 20}).modo == "driving"
    cfg = routing.calibracion()
    assert cfg["always_walking"] is True and cfg["detour_factor"] == 2.0 and cfg["direct_max_m"] == 150     # business_rules.yaml


def test_get_route_always_asks_walking_and_keeps_the_shorter(monkeypatch):
    largos = {"driving": 460.0, "walking": 460.0}
    modos = []

    def pedir(origin, destination, modo):
        modos.append(modo)
        return Route(largos[modo], 60.0, [origin, (12.07, -86.32), destination], modo)
    monkeypatch.setattr(routing, "_pedir", pedir)
    lejos = (12.0745, -86.3189)                                                                   # ≈ 310 m straight: not a detour for 460 m
    assert routing.get_route(ORIGEN, lejos).modo == "driving" and modos == ["driving", "walking"]    # asked anyway; equal: the driving one stays
    modos.clear()
    largos["walking"] = 380.0
    r = routing.get_route(ORIGEN, lejos)
    assert r.modo == "walking" and r.distance_m == 380.0 and "80 m menos" in r.aviso and modos == ["driving", "walking"]


def test_the_warning_is_given_only_when_walking_saves_a_real_amount():
    lejos = (12.0745, -86.3189)
    poco = routing.calibrar(auto(1000), ORIGEN, lejos, a_pie(960))                               # 40 m (4 %) less: used, no warning
    assert poco.modo == "walking" and poco.distance_m == 960 and poco.aviso is None
    mucho = routing.calibrar(auto(1000), ORIGEN, lejos, a_pie(700))                              # 300 m less: used and warned
    assert mucho.modo == "walking" and "camino a pie" in mucho.aviso and "300 m menos" in mucho.aviso
    assert routing.calibrar(auto(1000), ORIGEN, lejos, a_pie(1000)).modo == "driving"            # not shorter: driving stays
    assert routing.calibrar(auto(1000), ORIGEN, lejos, a_pie(1200)).modo == "driving"


from test_visor_fusion import _simular_ruta, entorno  # noqa: E402,F401  (fixture and route stubs of the viewer tests)


def test_the_viewer_shows_the_calibration_notice(entorno, monkeypatch):
    """The notice travels with the route into the warnings of the viewer's result, and the route used is the calibrated one."""
    main_, _, _ = entorno
    from visor_rutas import calculo
    _simular_ruta(main_, monkeypatch)
    directa = main_.routing.Route(distance_m=43.0, duration_s=0.0, points=[(12.13, -86.25), (12.1364, -86.2514)], modo="directa",
                                  aviso="Google daba 460 m por calles para 43 m en línea recta; se usó la línea recta")
    monkeypatch.setattr(main_.routing, "get_route", lambda *a, **k: directa)
    r = calculo.calcular_ruta(12.1364, -86.2514)
    assert any("se usó la línea recta" in a for a in r["avisos"]) and r["ruta"]["distancia_m"] == 43.0
