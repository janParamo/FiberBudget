"""Routes guided by the fibre lines of the KMZ (ruta_red.py) and the nodes of the KMZ for Fibra Metro; no database, no Google."""
import pytest

import ruta_red
import routing
from ruta_red import _Plano, ruta_por_lineas, mejorar

PLANO = _Plano(12.9237, -85.9203)            # around the NODO MATAGALPA of the KMZ


def ll(x, y):
    """(lat, lon) of a point x metres east, y metres north of the plane's origin."""
    return PLANO.latlon(x, y)


def lin(*puntos):
    return [ll(x, y) for x, y in puntos]


def google(distancia, origen, destino):
    return routing.Route(distance_m=distancia, duration_s=60.0, points=[origen, ll(0, -200), ll(300, -200), destino])


# The street of the case: a line along y = 0 from x = 0 to 300 (the connection point at its east end), another one going up at x = 0 that
# does not share a vertex with it (a T junction drawn without a point), and the client 30 m north of the street.
CALLE = lin((0, 0), (120, 0), (300, 0))
SUBE = lin((0, 40), (0, 0.5))                 # ends 0.5 m from CALLE's vertex at (0, 0): the same point for the network


def test_guided_route_goes_along_the_existing_line_not_round_the_block():
    origen, cliente = ll(300, 0), ll(150, 30)
    hallado = ruta_por_lineas(origen, cliente, [CALLE])
    assert hallado is not None
    metros, puntos = hallado
    assert 180 < metros < 200                       # 150 m along the line + the 30 m drop
    assert puntos[0] == origen and puntos[-1] == cliente


def test_the_guided_route_replaces_a_google_detour_and_says_so():
    origen, cliente = ll(300, 0), ll(150, 30)
    ruta = google(700.0, origen, cliente)
    nueva = mejorar(ruta, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: [CALLE])
    assert nueva.modo == "red" and nueva.distance_m < 200
    assert "líneas de fibra existentes" in nueva.aviso and "700" in nueva.aviso


def test_google_stays_when_the_lines_are_clearly_longer_and_the_lines_win_when_about_as_long():
    origen, cliente = ll(300, 0), ll(150, 30)
    corta = google(150.0, origen, cliente)          # the guided route (about 187 m) is more than 10 % longer: Google's stays
    assert mejorar(corta, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: [CALLE]) is corta
    parecida = google(175.0, origen, cliente)       # within 10 %: the existing line is taken (the poles are already there)
    assert mejorar(parecida, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: [CALLE]).modo == "red"


def test_lines_that_only_touch_at_a_t_junction_are_joined():
    origen, cliente = ll(300, 0), ll(0, 35)         # the client is on top of the line that goes up: it is reached through the junction
    hallado = ruta_por_lineas(origen, cliente, [CALLE, SUBE])
    assert hallado is not None and 330 < hallado[0] < 345        # 300 m west + 35 m north


def test_a_client_far_from_the_lines_or_without_lines_keeps_googles_route():
    origen, cliente = ll(300, 0), ll(150, 300)       # 300 m from the nearest line: more than attach_client_m
    ruta = google(700.0, origen, cliente)
    assert mejorar(ruta, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: [CALLE]) is ruta
    assert mejorar(ruta, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: []) is ruta


def test_unconnected_lines_keep_googles_route():
    origen, cliente = ll(300, 0), ll(150, 330)
    ruta = google(900.0, origen, cliente)
    otra = lin((100, 300), (200, 300))               # near the client, not connected to the connection point's line
    assert mejorar(ruta, origen, cliente, ruta_red.POR_DEFECTO, lambda *a: [CALLE, otra]) is ruta


def test_the_wrapper_never_replaces_a_hand_drawn_route_and_survives_a_failure(monkeypatch):
    import db
    origen, cliente = ll(300, 0), ll(150, 30)
    monkeypatch.setattr(db, "find_lineas_en_caja", lambda *a, **k: [CALLE])
    ruta = google(700.0, origen, cliente)

    def base(origin=None, destination=None):
        return ruta

    assert ruta_red.con_red_existente(base, {})(origin=origen, destination=cliente).modo == "red"
    base.fija = True
    assert ruta_red.con_red_existente(base, {}) is base                       # a route drawn by hand stays as it is
    del base.fija
    assert ruta_red.con_red_existente(base, {"route_guidance": {"enabled": False}}) is base

    def falla(*a, **k):
        raise db.DatabaseError("sin base")

    monkeypatch.setattr(db, "find_lineas_en_caja", falla)
    assert ruta_red.con_red_existente(base, {})(origin=origen, destination=cliente) is ruta


@pytest.mark.parametrize("kmz, visio, esperado", [
    ({"id": 23434, "nombre": "NODO MATAGALPA", "tipo": "nodo", "lat": 12.9237, "lon": -85.9203, "distancia_m": 250.0}, [], "NODO MATAGALPA"),
    ({"id": 1, "nombre": "NODO LEJOS", "tipo": "nodo", "lat": 12.9, "lon": -85.9, "distancia_m": 90000.0},
     [(7, "NODO CERCA VISIO", None, 12.92, -85.92, "visio", None, None)], "NODO CERCA VISIO"),
])
def test_metro_considers_the_nodes_of_the_kmz_and_takes_the_nearest(monkeypatch, kmz, visio, esperado):
    import db
    import metro
    monkeypatch.setattr(db, "find_nearest_nodo", lambda lat, lon: kmz)
    monkeypatch.setattr(metro, "_filas_nodos", lambda con: visio)
    seg, busqueda = metro.resolver_nodo(12.926, -85.918, {}, None)
    assert seg.nombre == esperado and busqueda.nodo["nombre"] == esperado


def test_metro_without_nodes_anywhere_raises(monkeypatch):
    import metro
    monkeypatch.setattr(metro, "_filas_nodos", lambda con: [])
    with pytest.raises(metro.SinNodo):
        metro.resolver_nodo(12.926, -85.918, {}, None)
