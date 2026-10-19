"""Ruta editada a mano (visor v2, fase 4B): visor_rutas/calculo.py (RutaFija, calcular_con_ruta), postes agregados a mano y el presupuesto
con la ruta del usuario. Mismos falsos de base y de Google que test_visor_rutas.py; Google no se llama nunca."""
import pytest
from fastapi.testclient import TestClient

from test_visor_rutas import BODY, LAT, LON, entorno  # noqa: F401  (fixture)

# a route the user corrected: it goes around by (12.135, -86.255) and is longer than Google's
EDITADA = [[12.13, -86.25], [12.135, -86.255], [12.14, -86.25], [12.14, -86.24]]
GOOGLE = [(12.13, -86.25), (12.14, -86.25), (12.14, -86.24)]


def test_the_edited_route_is_the_one_calculated_not_googles(entorno):
    main, calculo, _ = entorno
    google = calculo.calcular_ruta(LAT, LON)
    llamadas = []
    main.routing.get_route = lambda *a, **k: llamadas.append(1) or pytest.fail("Google must not be called")
    r = calculo.calcular_con_ruta(LAT, LON, EDITADA)
    assert not llamadas
    assert r["ruta"]["puntos"] == [tuple(p) for p in EDITADA] and r["ruta"]["manual"] is True and r["ruta"]["aproximada"] is False
    esperado = sum(main.origen._distance_m(a[0], a[1], b[0], b[1]) for a, b in zip(EDITADA, EDITADA[1:]))
    assert r["ruta"]["distancia_m"] == pytest.approx(esperado, abs=0.01) and r["ruta"]["distancia_m"] != google["ruta"]["distancia_m"]
    assert r["ruta"]["metraje_final_m"] == pytest.approx(main.calcular_metraje_final(esperado, main.load_rules(main.settings.rules_path)), abs=0.01)
    assert r["conexion"]["nombre"] == "MF PRUEBA"                         # the connection point is the same
    assert [m["nombre"] for m in r["mufas_intervenidas"]][0] == "MF PRUEBA"
    assert r["postes_nuevos"]["cantidad"] == len(r["postes_nuevos"]["posiciones"])


def test_poles_added_by_hand_count_as_new_ones(entorno):
    _, calculo, _ = entorno
    base = calculo.calcular_con_ruta(LAT, LON, EDITADA)
    con = calculo.calcular_con_ruta(LAT, LON, EDITADA, postes_extra=3)
    assert con["postes_nuevos"]["cantidad"] == base["postes_nuevos"]["cantidad"] + 3
    assert len(con["postes_nuevos"]["posiciones"]) == base["postes_nuevos"]["cantidad"]      # the page draws the ones it added
    assert not any("No se pudo ubicar" in a for a in con["avisos"])


def test_a_route_drawn_from_scratch_uses_its_last_point_as_the_client(entorno):
    _, calculo, _ = entorno
    r = calculo.calcular_con_ruta(None, None, EDITADA)
    assert (r["cliente"]["lat"], r["cliente"]["lon"]) == (EDITADA[-1][0], EDITADA[-1][1])


def test_a_route_that_does_not_start_at_the_connection_point_says_so(entorno):
    _, calculo, _ = entorno
    r = calculo.calcular_con_ruta(LAT, LON, [[12.1305, -86.2505], [12.14, -86.25], [12.14, -86.24]])      # ~70 m from MF PRUEBA
    assert any("empieza a" in a and "MF PRUEBA" in a for a in r["avisos"])


@pytest.mark.parametrize("malo", [None, [], [[12.1, -86.2]], [[12.1, -86.2], ["x", 1]], [[12.1, -86.2], [95, 0]], [[12.1, -86.2], [12.1]], "ruta"])
def test_invalid_routes_are_refused(entorno, malo):
    _, calculo, _ = entorno
    with pytest.raises(calculo.VisorError):
        calculo.calcular_con_ruta(LAT, LON, malo)


def test_the_api_of_the_viewer_gives_the_same_with_errors_as_text(entorno):
    from visor_rutas.ventana_web import Api
    api = Api()
    r = api.calcular_con_ruta(LAT, LON, EDITADA, 2)
    assert r["ok"] and r["datos"]["ruta"]["manual"] and r["coordenada"] == f"{LAT:.6f}, {LON:.6f}"
    assert api.calcular_con_ruta(LAT, LON, [[1, 2]]) == {"ok": False, "error": "Una ruta necesita al menos dos puntos"}


def test_the_budget_uses_the_edited_route_and_the_poles_added_by_hand(entorno):
    main, calculo, _ = entorno
    from visor_rutas.ventana_web import Api
    api = Api()
    google = api.estimar_presupuesto(LAT, LON, 1900.0)
    assert google["ok"]
    main.routing.get_route = lambda *a, **k: pytest.fail("Google must not be called")
    editada = api.estimar_presupuesto(LAT, LON, 1900.0, None, EDITADA)
    assert editada["ok"]
    esperado = sum(main.origen._distance_m(a[0], a[1], b[0], b[1]) for a, b in zip(EDITADA, EDITADA[1:]))
    # the Excel of the edited route carries ITS metraje
    assert editada["resultado"]["metraje_final_m"] == pytest.approx(main.calcular_metraje_final(esperado, main.load_rules(main.settings.rules_path)), abs=0.2)
    assert editada["resultado"]["metraje_final_m"] != google["resultado"]["metraje_final_m"]
    mas = api.estimar_presupuesto(LAT, LON, 1900.0, None, EDITADA, 4)
    assert any("agregado(s) a mano" in a for a in mas["resultado"]["avisos"]) and not any("a mano" in a for a in editada["resultado"]["avisos"])
    # the form budget takes the same two keys
    completo = api.generar_presupuesto({"ticket_id": "T-1", "coordenada": f"{LAT}, {LON}", "client_name": "Cliente", "client_code": "C1", "sales_exec": "Ana",
                                         "contact_name": "Roxana", "contact_phone": "5880", "service_type": "Empresarial", "medium": "FO",
                                         "bandwidth": "50 Mbps", "technology": "auto", "odf_rack_ports": "ninguno", "raw_comment": "",
                                         "ruta_editada": EDITADA, "postes_a_mano": 2})
    assert completo["ok"] and completo["resultado"]["metraje_final_m"] == editada["resultado"]["metraje_final_m"]
    assert any("2 poste(s) nuevo(s) agregado(s) a mano" in a for a in completo["resultado"]["avisos"])


def test_the_fusion_route_edited_by_the_user_sets_the_mufas_the_budget_counts(entorno):
    main, _, _ = entorno
    from visor_rutas import presupuesto_visor
    por_defecto = presupuesto_visor.estimar(LAT, LON, 1900.0, None)
    assert por_defecto["respuesta"]["budget"]["mufa_count"] == 3                      # MF PRUEBA, MF TRONCAL and the one on the route
    uno = presupuesto_visor.estimar(LAT, LON, 1900.0, None, mufas_tocadas=1)
    assert uno["respuesta"]["budget"]["mufa_count"] == 1 and uno["respuesta"]["quantities"] != por_defecto["respuesta"]["quantities"]
    assert presupuesto_visor.mufas_tocadas(None) is None and presupuesto_visor.mufas_tocadas("x") is None and presupuesto_visor.mufas_tocadas("2") == 2
    assert presupuesto_visor.mufas_tocadas(-4) == 0 and presupuesto_visor.mufas_tocadas(500) == 100
