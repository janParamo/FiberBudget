"""Connection point chosen by street-route length and available hilos (connection.route_selection)."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

from make_sample_template import create_template

# Real case: client 12.104408, -86.220292. The nearest KMZ mufa by straight line (Casa Gerencia,
# 610 m) is 3324 m away by street; Bertha Gámez is marked "MF ELIMINADA" in the KMZ.
BODY = {"ticket_id": "T-SEL", "client_name": "Cliente", "client_code": "C1", "sales_exec": "Ana",
        "contact_name": "Ana", "contact_phone": "1", "raw_comment": "x",
        "latitude": 12.10440830636558, "longitude": -86.22029218908612,
        "service_type": "internet", "medium": "fibra", "bandwidth": "50 Mbps"}
HEADERS = {"X-API-Key": "secret"}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    template = tmp_path / "t.xlsx"
    create_template(template)
    env = {"DB_HOST": "x", "DB_PORT": "5432", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
           "GOOGLE_API_KEY": "x", "SERVICE_API_KEY": "secret",
           "TEMPLATE_PATH": str(template), "OUTPUT_DIR": str(tmp_path / "out"),
           "LOG_FILE": str(tmp_path / "log.txt"), "RED_FIBRA_DB": str(tmp_path / "missing.db"),
           "VISIO_DB_NAME": "", "RULES_PATH": os.path.join(os.path.dirname(__file__), "..", "business_rules.yaml")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    config.get_settings.cache_clear()
    import main
    importlib.reload(main)
    db = main.db
    mufa = lambda i, nombre, lat, lon, d, desc=None: db.Segment(id=i, tipo="mufa", lat=lat, lon=lon, distance_m=d,
                                                                is_mufa=True, nombre=nombre, descripcion=desc)
    puntos = {
        "casa": mufa(460, "MF CASA GERENCIA OTTO MUNKEL", 12.098894, -86.220120, 610.3,
                     "MF APARECE EN DIAGRAMA MF PLAZA MAYOR #2 IDEAY"),
        "hasbani": mufa(461, "MF MARIA HASBANI", 12.097472, -86.219930, 768.3),
        "bertha": mufa(478, "MF BERTHA GAMEZ", 12.098879, -86.225121, 806.5,
                       "MF BERTHA GAMEZ  12.098879°, -86.225121°\nMF ELIMINADA\nPROBABLEMENTE NO EXISTA"),
        "corte": mufa(1712, "MF DE CORTE", 12.098874, -86.225983, 870.9, "MF 3M PLANA"),
        "oscar": mufa(479, "MF OSCAR SANCHEZ", 12.099050, -86.226542, 902.4, "MF oscar sanchez\nSPL 1/4"),
    }
    metros = {460: 3324.0, 461: 3224.0, 478: 1350.0, 1712: 1396.0, 479: 1426.0}
    por_coord = {(p.lat, p.lon): p.id for p in puntos.values()}
    llamadas = {"rutas": [], "candidatos": 0}

    def get_route(origin, destination):
        mufa_id = por_coord[origin]
        llamadas["rutas"].append(mufa_id)
        return main.routing.Route(distance_m=metros[mufa_id], duration_s=60.0, points=[origin, destination])

    def candidatos(*a, **k):
        llamadas["candidatos"] += 1
        return sorted(puntos.values(), key=lambda p: p.distance_m)

    monkeypatch.setattr(main.db, "check_connection", lambda: None)
    monkeypatch.setattr(main.db, "find_nearest_connection_point", lambda *a, **k: puntos["casa"])
    monkeypatch.setattr(main.db, "find_connection_candidates", candidatos)
    monkeypatch.setattr(main.db, "find_mufas_near_route", lambda *a, **k: [])
    monkeypatch.setattr(main.db, "find_point_coords", lambda ids: {})
    monkeypatch.setattr(main.db, "find_upstream_mufa_chain",
                        lambda mufa_id, nombre, *a, **k: [main.db.ChainMufa(mufa_id, nombre)])
    monkeypatch.setattr(main.db, "find_existing_poles_near_route", lambda *a, **k: [])
    monkeypatch.setattr(main.routing, "get_route", get_route)
    monkeypatch.setattr(main.recalc, "find_soffice", lambda *a, **k: None)
    monkeypatch.setattr(main.mapa_ruta, "generar_mapa_ruta", lambda *a, **k: None)
    return main, puntos, metros, llamadas


def test_long_way_round_compares_nearby_mufas_by_route_and_skips_eliminated(entorno):
    main, _, _, llamadas = entorno
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()

    cp = data["connection_point"]
    assert (cp["segment_id"], cp["name"]) == (1712, "MF DE CORTE")        # 1396 m, the shortest available
    assert data["route"]["distance_m"] == 1396.0
    seleccion = cp["selection"]
    assert seleccion["cambiada"] and seleccion["criterio"] == "rodeo"
    assert seleccion["inicial"]["ruta_m"] == 3324.0 and seleccion["elegida"]["id"] == 1712
    bertha = next(e for e in seleccion["evaluados"] if e["id"] == 478)
    assert bertha["disponible"] is False and "ELIMINADA" in bertha["motivo"] and bertha["ruta_m"] is None
    assert 478 not in llamadas["rutas"]                                    # no Google call for it
    assert any(w.startswith("Punto de conexión elegido por ruta: MF DE CORTE (1396 m por calle)")
               and "validar hilos disponibles" in w for w in data["warnings"])


def test_nearest_without_detour_and_available_is_kept_without_extra_calls(entorno):
    main, puntos, metros, llamadas = entorno
    metros[460] = 900.0                                                    # < 2 x 610 m
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()
    assert data["connection_point"]["segment_id"] == 460 and data["connection_point"]["selection"] is None
    assert llamadas == {"rutas": [460], "candidatos": 0}


def test_nearest_marked_saturada_is_replaced_even_without_detour(entorno, monkeypatch):
    main, puntos, metros, _ = entorno
    metros[460] = 700.0
    puntos["casa"].descripcion = "MF 3M PLANA SATURADA\nNO REALIZAR PRESUPUESTOS"
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()
    seleccion = data["connection_point"]["selection"]
    assert seleccion["criterio"] == "sin_hilos" and "SATURAD" in seleccion["inicial"]["motivo"]
    assert data["connection_point"]["segment_id"] == 1712


def test_no_other_mufa_available_keeps_the_nearest_and_asks_to_validate(entorno, monkeypatch):
    main, puntos, _, _ = entorno
    puntos["casa"].descripcion = "MF ELIMINADA"
    monkeypatch.setattr(main.db, "find_connection_candidates", lambda *a, **k: [puntos["casa"], puntos["bertha"]])
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()
    assert data["connection_point"]["segment_id"] == 460
    assert any("no hay otra mufa disponible" in w for w in data["warnings"])


def test_disabled_keeps_the_straight_line_rule(entorno, monkeypatch):
    main, _, _, llamadas = entorno
    reglas = main.load_rules(main.settings.rules_path)
    reglas["connection"]["route_selection"]["enabled"] = False
    monkeypatch.setattr(main, "load_rules", lambda *a, **k: reglas)
    data = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()
    assert data["connection_point"]["segment_id"] == 460 and llamadas["candidatos"] == 0


def test_viewer_uses_the_same_choice(entorno):
    main, _, _, _ = entorno
    from visor_rutas import calculo
    r = calculo.calcular_ruta(BODY["latitude"], BODY["longitude"])
    assert (r["conexion"]["id"], r["ruta"]["distancia_m"]) == (1712, 1396.0)
    assert r["conexion"]["notas"].startswith("Elegida por ruta más corta (1396 m)")
    assert "MF BERTHA GAMEZ: ELIMINADA en el KMZ" in r["conexion"]["notas"]
