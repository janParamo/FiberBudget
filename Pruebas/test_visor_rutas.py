"""Visor de rutas (visor_rutas/calculo.py) with DB and Google mocked, as in test_api.py."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

from make_sample_template import create_template

LAT, LON = 12.1364, -86.2514
BODY = {"ticket_id": "T-VISOR", "client_name": "Cliente", "client_code": "1", "sales_exec": "A",
        "contact_name": "B", "contact_phone": "1", "raw_comment": "", "latitude": LAT, "longitude": LON,
        "service_type": "internet", "medium": "fibra", "bandwidth": "100 Mbps"}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    template = tmp_path / "t.xlsx"
    create_template(template)
    env = {"DB_HOST": "x", "DB_PORT": "5432", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
           "GOOGLE_API_KEY": "x", "SERVICE_API_KEY": "secret",
           "TEMPLATE_PATH": str(template), "OUTPUT_DIR": str(tmp_path / "out"),
           "LOG_FILE": str(tmp_path / "log.txt"),
           "RED_FIBRA_DB": str(tmp_path / "missing_red_fibra.db"),
           "VISIO_DB_NAME": "",
           "RULES_PATH": os.path.join(os.path.dirname(__file__), "..", "business_rules.yaml"), "RUTA_FUSION_XLSX": str(tmp_path / "no_hay_libro_de_fusion.xlsx")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    config.get_settings.cache_clear()
    import main
    importlib.reload(main)
    from visor_rutas import calculo

    seg = main.db.Segment(id=7, tipo="mufa", lat=12.13, lon=-86.25, distance_m=120.0,
                          is_mufa=True, nombre="MF PRUEBA")
    route = main.routing.Route(distance_m=1850.0, duration_s=300.0,
                               points=[(12.13, -86.25), (12.14, -86.25), (12.14, -86.24)])
    monkeypatch.setattr(main.db, "find_nearest_connection_point", lambda *a, **k: seg)
    # 1850 m by route for 120 m in straight line: no other KMZ mufa to compare (no network call)
    monkeypatch.setattr(main.db, "find_connection_candidates", lambda *a, **k: [])
    monkeypatch.setattr(main.db, "find_mufas_near_route", lambda *a, **k: [
        main.db.RouteMufa(id=31, tipo="mufa", lat=12.14, lon=-86.249, distance_m=3.0, is_backbone=False)])
    monkeypatch.setattr(main.db, "find_point_coords", lambda ids: {})
    monkeypatch.setattr(main.db, "find_upstream_mufa_chain", lambda mufa_id, nombre, *a, **k: [
        main.db.ChainMufa(mufa_id, nombre), main.db.ChainMufa(8, "MF TRONCAL", "cable_24h")])
    monkeypatch.setattr(main.db, "find_existing_poles_near_route", lambda *a, **k: [
        main.db.ExistingPole(id=8, lat=12.135, lon=-86.25, route_position_m=50.0),
        main.db.ExistingPole(id=9, lat=12.14, lon=-86.2495, route_position_m=1200.0)])
    monkeypatch.setattr(main.routing, "get_route", lambda *a, **k: route)
    monkeypatch.setattr(main.recalc, "find_soffice", lambda *a, **k: None)
    monkeypatch.setattr(main.mapa_ruta, "generar_mapa_ruta", lambda *a, **k: None)
    return main, calculo, tmp_path


def _visio_node(**overrides):
    node = {"id": 2423, "nombre": "MF LOYOLA #2 MUFA FOSC", "tipo": "MUFA", "propietario": None,
            "lat": 12.153661, "lon": -86.264043, "fuente_coord": "visio", "zona": "Loyola",
            "notas": None, "distancia_m": 75.5, "enlaces": 0, "clientes": 2}
    return {**node, **overrides}


def test_calcular_ruta_devuelve_conexion_ruta_y_postes(entorno):
    main, calculo, tmp_path = entorno
    r = calculo.calcular_ruta(LAT, LON)

    c = r["conexion"]
    assert (c["nombre"], c["tipo"], c["fuente"], c["lat"], c["lon"]) == ("MF PRUEBA", "mufa", "kmz", 12.13, -86.25)
    assert c["distancia_lineal_m"] == 120.0
    assert r["ruta"]["puntos"] == [(12.13, -86.25), (12.14, -86.25), (12.14, -86.24)]
    assert r["ruta"]["distancia_m"] == 1850.0 and r["ruta"]["aproximada"] is False
    assert r["ruta"]["tipo_cable"] == "ADSS 24 hilos"          # > adss_threshold_m
    assert r["postes_existentes"] == [(8, 12.135, -86.25), (9, 12.14, -86.2495)]
    nuevos = r["postes_nuevos"]
    assert nuevos["cantidad"] > 0 and len(nuevos["posiciones"]) == nuevos["cantidad"]
    assert [m["nombre"] for m in r["mufas_intervenidas"]] == ["MF PRUEBA", "MF TRONCAL", "Mufa 31"]
    assert r["mufas_en_ruta"][0]["id"] == 31
    assert r["origen_trafico"]["nodo"] is None
    assert any("Base Visio desactivada" in a for a in r["avisos"])
    assert not (tmp_path / "out").exists()                     # the viewer writes nothing to output/


def test_visor_da_las_mismas_cantidades_que_el_presupuesto(entorno):
    main, calculo, _ = entorno
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers={"X-API-Key": "secret"}).json()
    r = calculo.calcular_ruta(LAT, LON)

    budget = data["budget"]
    assert r["ruta"]["distancia_m"] == budget["route_distance_m"]
    assert r["ruta"]["metraje_final_m"] == budget["final_distance_m"]
    assert r["ruta"]["tipo_cable"] == budget["cable_type"]
    assert len(r["postes_existentes"]) == budget["existing_poles"]
    assert r["postes_nuevos"]["cantidad"] == budget["new_poles_8m"]
    assert [m["id"] for m in r["mufas_intervenidas"]] == [m["id"] for m in budget["intervened_mufas"]]
    assert r["mufas_intervenidas_fuente"] == budget["mufa_count_source"]
    assert (r["conexion"]["lat"], r["conexion"]["lon"]) == (
        data["connection_point"]["latitude"], data["connection_point"]["longitude"])


def test_acometida_del_fin_de_ruta_al_cliente(entorno):
    main, calculo, _ = entorno
    r = calculo.calcular_ruta(LAT, LON)
    # The mocked route ends at (12.14, -86.24); the drop goes from there to the client.
    assert r["ruta"]["acometida_m"] == round(main.origen._distance_m(12.14, -86.24, LAT, LON), 1)
    assert r["ruta"]["acometida_m"] > 0


def test_sin_google_linea_recta_y_aviso(entorno, monkeypatch):
    main, calculo, _ = entorno

    def sin_internet(*a, **k):
        raise main.routing.RoutingError("Directions API unavailable after retries: ConnectionError")

    monkeypatch.setattr(main.routing, "get_route", sin_internet)
    r = calculo.calcular_ruta(LAT, LON)
    assert r["ruta"]["aproximada"] is True
    assert r["ruta"]["puntos"] == [(12.13, -86.25), (LAT, LON)]
    recta = main.origen._distance_m(12.13, -86.25, LAT, LON)
    assert r["ruta"]["distancia_m"] == round(recta, 2)
    assert any(a.startswith("Ruta aproximada (sin Google)") for a in r["avisos"])


def test_sin_ruta_de_google_tambien_es_linea_recta(entorno, monkeypatch):
    main, calculo, _ = entorno
    monkeypatch.setattr(main.routing, "get_route",
                        lambda *a, **k: (_ for _ in ()).throw(main.routing.RouteNotFound("ZERO_RESULTS")))
    r = calculo.calcular_ruta(LAT, LON)
    assert r["ruta"]["aproximada"] is True
    assert any("Google no encontró ruta" in a for a in r["avisos"])


@pytest.mark.parametrize("lat, lon", [(40.4, -3.7), (0.0, 0.0)])
def test_coordenada_fuera_de_nicaragua_es_error_claro(entorno, lat, lon):
    _, calculo, _ = entorno
    with pytest.raises(calculo.CoordenadaInvalida, match="fuera de Nicaragua"):
        calculo.calcular_ruta(lat, lon)


def test_coordenadas_invertidas_se_avisan(entorno):
    _, calculo, _ = entorno
    with pytest.raises(calculo.CoordenadaInvalida, match="invertidas"):
        calculo.parsear_coordenadas("-86.263438, 12.153328")


@pytest.mark.parametrize("texto", ["12.153328, -86.263438", "12.153328 -86.263438",
                                   "12.153328;-86.263438", " (12.153328 ,  -86.263438) "])
def test_parsear_coordenadas_acepta_separadores(entorno, texto):
    _, calculo, _ = entorno
    assert calculo.parsear_coordenadas(texto) == (12.153328, -86.263438)


@pytest.mark.parametrize("texto", ["", "12.15", "abc, def", "12.1 -86.2 5"])
def test_parsear_coordenadas_rechaza_texto(entorno, texto):
    _, calculo, _ = entorno
    with pytest.raises(calculo.CoordenadaInvalida):
        calculo.parsear_coordenadas(texto)


def test_base_visio_caida_sigue_con_kmz(entorno, monkeypatch):
    main, calculo, _ = entorno
    monkeypatch.setattr(main.red_fibra_pg, "enabled", lambda: True)
    monkeypatch.setattr(main.red_fibra_pg, "connect",
                        lambda: (_ for _ in ()).throw(main.psycopg.OperationalError("down")))
    r = calculo.calcular_ruta(LAT, LON)
    assert r["conexion"]["fuente"] == "kmz" and r["conexion"]["nombre"] == "MF PRUEBA"
    assert "Base Visio no disponible: se usó solo el KMZ" in r["avisos"]


def test_kmz_caido_usa_nodo_visio_y_avisa(entorno, monkeypatch):
    main, calculo, _ = entorno
    monkeypatch.setattr(main.db, "find_nearest_connection_point",
                        lambda *a, **k: (_ for _ in ()).throw(main.db.DatabaseError("down")))
    busqueda = main.red_fibra_pg.BusquedaVisio(fuente="red_fibra", radio_m=2000.0, nodo=_visio_node(),
                                               alternativas=[_visio_node(id=1, nombre="NODO X", tipo="NODO",
                                                                         lat=12.16, lon=-86.27, distancia_m=900.0)])
    monkeypatch.setattr(main.red_fibra_pg, "buscar_origen", lambda *a, **k: busqueda)
    r = calculo.calcular_ruta(LAT, LON)
    assert (r["conexion"]["tipo"], r["conexion"]["fuente"]) == ("nodo Visio", "red_fibra")
    assert r["conexion"]["nombre"] == "MF LOYOLA #2 MUFA FOSC"
    assert [n["nombre"] for n in r["nodos_visio_cercanos"]] == ["NODO X"]
    assert any("KMZ (PostGIS) no respondió" in a for a in r["avisos"])


def test_sin_punto_de_conexion_es_error_claro(entorno, monkeypatch):
    main, calculo, _ = entorno
    monkeypatch.setattr(main.db, "find_nearest_connection_point",
                        lambda *a, **k: (_ for _ in ()).throw(main.db.NoSegmentFound("none")))
    with pytest.raises(calculo.SinPuntoConexion):
        calculo.calcular_ruta(LAT, LON)


def test_falla_de_postes_no_bloquea_el_visor(entorno, monkeypatch):
    main, calculo, _ = entorno
    monkeypatch.setattr(main.db, "find_existing_poles_near_route",
                        lambda *a, **k: (_ for _ in ()).throw(main.db.ExistingPolesQueryError("down")))
    r = calculo.calcular_ruta(LAT, LON)
    assert r["postes_existentes"] == []
    assert any("postes existentes" in a for a in r["avisos"])


@pytest.mark.parametrize("distance, positions", [
    (1850.0, [50.0, 1200.0]), (0.0, []), (49.0, []), (500.0, []), (1000.0, [55.0, 110.0, 400.0, 999.0])])
def test_posiciones_postes_nuevos_coinciden_con_el_conteo(entorno, distance, positions):
    _, calculo, _ = entorno
    from presupuesto import count_new_poles_by_gaps
    nuevas = calculo.posiciones_postes_nuevos(distance, 50, positions, 60)
    assert len(nuevas) == count_new_poles_by_gaps(distance, 50, positions, 0, 60)
    assert all(0 < m <= distance for m in nuevas)
