"""/visor/* (visor_api.py) and the remote viewer (visor_rutas/remoto.py, Api in remote mode).

The remote viewer must get exactly what the local viewer computes, through the API, with its own
keys (never SERVICE_API_KEY), an hourly limit, and files only from output/visor.
"""
import importlib
import json
import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from make_sample_template import create_template

CLAVES = "jan:clave-jan,maria:clave-maria"
JAN = {"X-Visor-Key": "clave-jan"}
LAT, LON = 12.1364, -86.2514
CAMPOS = {"ticket_id": "", "coordenada": f"{LAT}, {LON}", "client_name": "Cliente Remoto", "client_code": "C9",
          "sales_exec": "Ana", "contact_name": "", "contact_phone": "5880", "service_type": "Empresarial",
          "medium": "FO", "bandwidth": "50 Mbps", "technology": "auto", "odf_rack_ports": "ninguno", "raw_comment": ""}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    template = tmp_path / "t.xlsx"
    create_template(template)
    env = {"DB_HOST": "x", "DB_PORT": "5432", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
           "GOOGLE_API_KEY": "x", "SERVICE_API_KEY": "secret",
           "TEMPLATE_PATH": str(template), "OUTPUT_DIR": str(tmp_path / "out"),
           "LOG_FILE": str(tmp_path / "log.txt"), "RED_FIBRA_DB": str(tmp_path / "missing.db"),
           "VISIO_DB_NAME": "", "RULES_PATH": os.path.join(os.path.dirname(__file__), "..", "business_rules.yaml"), "RUTA_FUSION_XLSX": str(tmp_path / "no_hay_libro_de_fusion.xlsx"),
           "VISOR_API_KEYS": CLAVES, "VISOR_RATE_LIMIT_PER_HOUR": "60"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    config.get_settings.cache_clear()
    import main
    importlib.reload(main)
    import visor_api
    visor_api.reiniciar()
    seg = main.db.Segment(id=7, tipo="mufa", lat=12.13, lon=-86.25, distance_m=120.0, is_mufa=True, nombre="MF PRUEBA")
    llamadas = {"google": 0}

    def get_route(origin, destination):
        llamadas["google"] += 1
        return main.routing.Route(distance_m=1850.0, duration_s=300.0,
                                  points=[(12.13, -86.25), (12.14, -86.25), (LAT, LON)])

    monkeypatch.setattr(main.db, "check_connection", lambda: None)
    monkeypatch.setattr(main.db, "find_nearest_connection_point", lambda *a, **k: seg)
    monkeypatch.setattr(main.db, "find_connection_candidates", lambda *a, **k: [])
    monkeypatch.setattr(main.db, "find_mufas_near_route", lambda *a, **k: [])
    monkeypatch.setattr(main.db, "find_point_coords", lambda ids: {})
    monkeypatch.setattr(main.db, "find_upstream_mufa_chain",
                        lambda mufa_id, nombre, *a, **k: [main.db.ChainMufa(mufa_id, nombre)])
    monkeypatch.setattr(main.db, "find_existing_poles_near_route", lambda *a, **k: [
        main.db.ExistingPole(id=8, lat=12.135, lon=-86.25, route_position_m=50.0)])
    monkeypatch.setattr(main.routing, "get_route", get_route)
    monkeypatch.setattr(main.recalc, "find_soffice", lambda *a, **k: None)
    monkeypatch.setattr(main.mapa_ruta, "generar_mapa_ruta", lambda *a, **k: None)
    yield main, visor_api, TestClient(main.app), tmp_path / "out", llamadas
    visor_api.reiniciar()


def _api_remota(main, tmp_path, clave="clave-jan"):
    from visor_rutas import config_visor, ventana_web
    api = ventana_web.Api(config_visor.ConfigVisor("remoto", "http://testserver", clave))
    api._usar_remoto(TestClient(main.app), carpeta=tmp_path / "descargas_remotas")
    return api


# --------------------------------------------------------------------------- autenticación

def test_keys_are_required_and_separate_from_the_service_key(entorno):
    _, _, cliente, _, _ = entorno
    assert cliente.post("/visor/ruta", json={"texto": f"{LAT}, {LON}"}).status_code == 401
    assert cliente.post("/visor/ruta", json={"texto": f"{LAT}, {LON}"}, headers={"X-Visor-Key": "otra"}).status_code == 401
    assert cliente.get("/visor/info", headers={"X-Visor-Key": "secret"}).status_code == 401   # SERVICE_API_KEY
    assert cliente.get("/visor/info", headers={"X-API-Key": "secret"}).status_code == 401
    assert cliente.post("/presupuesto", json={}, headers=JAN).status_code == 401                 # and vice versa
    assert cliente.get("/visor/info", headers=JAN).status_code == 200


def test_empty_visor_api_keys_disables_every_endpoint(entorno, monkeypatch):
    _, _, cliente, _, _ = entorno
    monkeypatch.setenv("VISOR_API_KEYS", "")
    for metodo, ruta in (("get", "/visor/info"), ("post", "/visor/ruta"), ("get", "/visor/archivo/x.xlsx"),
                         ("get", "/visor/mufas"), ("get", "/visor/red/kmz_mufas")):
        assert getattr(cliente, metodo)(ruta, headers=JAN).status_code == 404, ruta


def test_info_gives_version_map_and_form(entorno):
    _, visor_api, cliente, _, _ = entorno
    info = cliente.get("/visor/info", headers={"X-Visor-Key": "clave-maria"}).json()
    assert (info["version"], info["persona"]) == (visor_api.VERSION, "maria")
    assert info["configuracion"]["imagery_url"].startswith("https://")
    assert "Residencial" in info["presupuesto"]["servicios"] and "carpeta" not in info["presupuesto"]


# --------------------------------------------------------------------------- mismos resultados

def test_ruta_returns_calcular_ruta(entorno):
    main, _, cliente, _, _ = entorno
    from visor_rutas import calculo
    from visor_rutas.ventana_web import a_json
    respuesta = cliente.post("/visor/ruta", json={"texto": f"{LAT}; {LON}"}, headers=JAN).json()
    assert respuesta["ok"] and respuesta["coordenada"] == "12.136400, -86.251400"
    assert respuesta["datos"] == json.loads(json.dumps(a_json(calculo.calcular_ruta(LAT, LON))))
    con_latlon = cliente.post("/visor/ruta", json={"lat": LAT, "lon": LON}, headers=JAN).json()
    assert con_latlon["datos"] == respuesta["datos"]
    invertida = cliente.post("/visor/ruta", json={"texto": f"{LON}, {LAT}"}, headers=JAN).json()
    assert invertida["ok"] is False and "invertidas" in invertida["error"]


def test_remote_provider_gives_the_same_as_local(entorno, tmp_path):
    main, _, _, salida, llamadas = entorno
    from visor_rutas import ventana_web
    local, remota = ventana_web.Api(), _api_remota(main, tmp_path)

    ruta_local, ruta_remota = local.calcular(f"{LAT}, {LON}"), remota.calcular(f"{LAT}, {LON}")
    assert ruta_remota == json.loads(json.dumps(ruta_local))

    metraje = ruta_local["datos"]["ruta"]["metraje_final_m"]
    est_local = local.estimar_presupuesto(LAT, LON, metraje)
    est_remota = remota.estimar_presupuesto(LAT, LON, metraje)
    assert est_remota["ok"] and est_remota["supuestos"] == est_local["supuestos"]
    comparar = ("calculado", "tecnologia", "tipo_cable", "metraje_final_m", "resumen", "pendientes", "distancia_km")
    assert {k: est_remota["resultado"][k] for k in comparar} == json.loads(json.dumps(
        {k: est_local["resultado"][k] for k in comparar}))
    assert est_remota["resultado"]["archivo"].startswith("remoto:")                 # no server path

    pres = remota.generar_presupuesto(CAMPOS)
    assert pres["ok"] and pres["resultado"]["carpeta"] is None
    hoja = remota.hoja_excel(pres["resultado"]["archivo"], "Presupuesto", pres["resultado"]["calculado"])
    assert hoja["ok"] and "<table" in hoja["html"]                                  # drawn here from the download
    descargado = remota._remoto.descargar(pres["resultado"]["archivo"], "xlsx")
    assert descargado.parent == tmp_path / "descargas_remotas" / "descargas"
    servidor = salida / "visor" / f"{pres['resultado']['id']}.xlsx"
    assert servidor.is_file() and descargado.read_bytes() == servidor.read_bytes()
    assert not (salida / "budget_index.json").exists()                            # never the n8n index


def test_estimate_without_metres_reuses_the_cached_route(entorno):
    _, _, cliente, _, llamadas = entorno
    cliente.post("/visor/ruta", json={"texto": f"{LAT}, {LON}"}, headers=JAN)
    antes = llamadas["google"]
    estimacion = cliente.post("/visor/estimacion", json={"lat": LAT, "lon": LON}, headers=JAN).json()
    assert estimacion["ok"] and estimacion["supuestos"]["bandwidth"] == "10 Mbps"
    assert estimacion["supuestos"]["service_type"] == "Empresarial"                 # 1850 m > 600 m
    assert llamadas["google"] == antes                                               # same coordinate: cached


def test_measurement_endpoint_gives_metraje_and_total_without_google(entorno):
    _, _, cliente, _, llamadas = entorno
    puntos = [[12.1300, -86.2500], [12.1320, -86.2500], [12.1320, -86.2490]]
    ligera = cliente.post("/visor/medicion", json={"puntos": puntos}, headers=JAN).json()
    assert ligera.get("ok"), ligera
    assert ligera["medicion"]["metraje_final_m"] > ligera["medicion"]["distancia_m"]
    total = cliente.post("/visor/medicion", json={"puntos": puntos, "con_total": True}, headers=JAN).json()
    assert total["ok"] and total["resultado"]["archivo"].startswith("remoto:Medicion_") and total["medicion"] == ligera["medicion"]
    assert llamadas["google"] == 0                                                  # a measure never calls Google
    assert cliente.post("/visor/medicion", json={"puntos": [[1, 2]]}, headers=JAN).status_code == 422
    assert cliente.post("/visor/medicion", json={"puntos": puntos}).status_code in (401, 403)   # needs the key


def test_edited_route_endpoints_use_the_users_route_and_never_google(entorno):
    main, _, cliente, _, llamadas = entorno
    puntos = [[12.13, -86.25], [12.135, -86.255], [12.14, -86.25], [LAT, LON]]
    editada = cliente.post("/visor/ruta_editada", json={"lat": LAT, "lon": LON, "puntos": puntos, "postes_extra": 2}, headers=JAN).json()
    assert editada["ok"] and editada["datos"]["ruta"]["manual"] is True and editada["datos"]["ruta"]["puntos"][1] == [12.135, -86.255]
    assert editada["datos"]["postes_nuevos"]["cantidad"] >= 2
    estimacion = cliente.post("/visor/estimacion", json={"lat": LAT, "lon": LON, "metraje_final_m": 900.0, "ruta": puntos, "postes_extra": 1}, headers=JAN).json()
    assert estimacion["ok"] and any("agregado(s) a mano" in a for a in estimacion["resultado"]["avisos"])
    assert llamadas["google"] == 0                                                  # the user's route replaces Google's
    assert cliente.post("/visor/ruta_editada", json={"puntos": [[1, 2]]}, headers=JAN).status_code == 422
    assert cliente.post("/visor/ruta_editada", json={"puntos": puntos}).status_code == 401


def test_fusion_route_endpoints_write_the_text_and_report_errors(entorno):
    _, _, cliente, _, _ = entorno
    plan = {"pasos": [{"nombre": "MF UNO", "lat": 12.0, "lon": -86.0, "tocar": True, "hilo_cliente": "H2", "hilo_potencia": "H5"},
                      {"nombre": "MF DOS", "lat": 12.1, "lon": -86.1, "tocar": False}], "potencia": "NODO X"}
    r = cliente.post("/visor/fusion/redactar", json={"plan": plan}, headers=JAN).json()
    assert r["ok"] and r["plan"]["tocadas"] == 1 and r["plan"]["lineas"][0].endswith("fusionarlo con H5 hacia NODO X")
    assert cliente.post("/visor/fusion/redactar", json={"plan": {"pasos": "no"}}, headers=JAN).json()["ok"] is False
    assert cliente.post("/visor/fusion/redactar", json={"plan": plan}).status_code == 401
    # the workbook of the server: a missing file is an error as text, never a crash
    malo = cliente.post("/visor/fusion/exportar", json={"plan": plan, "opciones": {"fecha": "2026-10-14"}}, headers=JAN).json()
    assert malo["ok"] is False and "libro de rutas de fusión" in malo["error"]
    est = cliente.post("/visor/estimacion", json={"lat": LAT, "lon": LON, "metraje_final_m": 900.0, "mufas_tocadas": 1}, headers=JAN).json()
    assert est["ok"]


def test_bulk_coordinates_endpoints_read_calculate_and_download(entorno):
    import base64
    import io as _io
    import time
    import zipfile
    _, _, cliente, _, llamadas = entorno
    texto = base64.b64encode(b"Uno 12.1364, -86.2514\nDos 12.1400, -86.2600\n").decode()
    leidas = cliente.post("/visor/masivas/leer", json={"nombre": "a.txt", "datos": texto}, headers=JAN).json()
    assert leidas["ok"] and [p["estado"] for p in leidas["puntos"]] == ["ok", "ok"]
    assert cliente.post("/visor/masivas/leer", json={"nombre": "a.pdf", "datos": texto}, headers=JAN).json()["ok"] is False
    inicio = cliente.post("/visor/masivas/iniciar", json={"nombre": "a.txt", "puntos": leidas["puntos"]}, headers=JAN).json()
    assert inicio["ok"]
    lote_id = inicio["lote"]["id"]
    for _ in range(300):
        estado = cliente.get(f"/visor/masivas/{lote_id}", params={"desde": 0}, headers=JAN).json()["lote"]
        if estado["estado"] != "corriendo":
            break
        time.sleep(0.05)
    assert estado["estado"] == "terminado" and [r["ok"] for r in estado["resultados"]] == [True, True]
    z = cliente.post(f"/visor/masivas/{lote_id}/descargar", headers=JAN).json()
    assert z["ok"] and "Resumen.xlsx" in zipfile.ZipFile(_io.BytesIO(base64.b64decode(z["datos"]))).namelist()
    assert cliente.post(f"/visor/masivas/{lote_id}/cancelar", headers=JAN).json()["ok"] is True
    assert cliente.get("/visor/masivas/20260101-000000", headers=JAN).json()["ok"] is False
    assert cliente.get(f"/visor/masivas/{lote_id}").status_code == 401 and cliente.get("/visor/masivas/mal;id", headers=JAN).status_code == 422
    # every valid point counts for the hourly limit of the person (it can ask Google): more than the limit is refused before starting
    muchos = [{"n": i, "nombre": f"P{i}", "codigo": "", "texto": "12.1, -86.2", "lat": 12.1, "lon": -86.2, "estado": "ok", "incluir": True} for i in range(1, 80)]
    assert cliente.post("/visor/masivas/iniciar", json={"nombre": "m", "puntos": muchos}, headers=JAN).status_code == 429


# --------------------------------------------------------------------------- límite y archivos

def test_hourly_limit_per_person(entorno, monkeypatch):
    _, _, cliente, _, _ = entorno
    monkeypatch.setenv("VISOR_RATE_LIMIT_PER_HOUR", "2")
    cuerpo = {"texto": f"{LAT}, {LON}"}
    assert [cliente.post("/visor/ruta", json=cuerpo, headers=JAN).status_code for _ in range(2)] == [200, 200]
    tercera = cliente.post("/visor/ruta", json=cuerpo, headers=JAN)
    assert tercera.status_code == 429 and "Límite de 2 consultas por hora" in tercera.json()["detail"]
    assert cliente.post("/visor/ruta", json=cuerpo, headers={"X-Visor-Key": "clave-maria"}).status_code == 200
    assert cliente.get("/visor/info", headers=JAN).status_code == 200              # read-only: not limited


def test_archivo_never_leaves_output_visor(entorno):
    _, _, cliente, salida, _ = entorno
    (salida / "visor").mkdir(parents=True)
    (salida / "visor" / "Presupuesto_ok.xlsx").write_bytes(b"PK excel")
    (salida / "secreto.xlsx").write_bytes(b"no")
    (salida / "budget_index.json").write_text("{}")
    assert cliente.get("/visor/archivo/Presupuesto_ok.xlsx", headers=JAN).content == b"PK excel"
    for ruta in ("/visor/archivo/..%2Fsecreto.xlsx", "/visor/archivo/..%5Csecreto.xlsx",
                 "/visor/archivo/%2E%2E%5Csecreto.xlsx", f"/visor/archivo/{str(salida / 'secreto')}.xlsx",
                 "/visor/archivo/budget_index.json", "/visor/archivo/..%5Cbudget_index.json",
                 "/visor/archivo/nada.xlsx", "/visor/archivo/..xlsx"):
        assert cliente.get(ruta, headers=JAN).status_code == 404, ruta


def test_requests_are_logged_without_keys(entorno, caplog):
    _, _, cliente, _, _ = entorno
    with caplog.at_level(logging.INFO, logger="visor_api"):
        cliente.post("/visor/ruta", json={"texto": f"{LAT}, {LON}"}, headers=JAN)
    linea = next(r.getMessage() for r in caplog.records if "endpoint=ruta" in r.getMessage())
    assert "persona=jan" in linea and "12.1364" in linea and "duracion=" in linea
    assert "clave-jan" not in caplog.text


def test_presupuesto_endpoint_for_n8n_is_unchanged(entorno):
    main, _, cliente, salida, _ = entorno
    body = {"ticket_id": "T-1", "client_name": "Cliente", "client_code": "C1", "sales_exec": "Ana",
            "contact_name": "R", "contact_phone": "1", "raw_comment": "x", "latitude": LAT, "longitude": LON,
            "service_type": "Empresarial", "medium": "FO", "bandwidth": "50 Mbps"}
    respuesta = cliente.post("/presupuesto", json=body, headers={"X-API-Key": "secret"})
    assert respuesta.status_code == 200 and respuesta.json()["status"] == "ok"
    assert list(json.loads((salida / "budget_index.json").read_text(encoding="utf-8"))) == ["T-1"]


def test_keys_are_reread_when_the_env_file_changes(entorno, tmp_path, monkeypatch):
    _, visor_api, cliente, _, _ = entorno
    archivo = tmp_path / ".env"
    archivo.write_text("VISOR_API_KEYS=ana:clave-ana\n", encoding="utf-8")
    monkeypatch.setattr(visor_api, "_ENV", archivo)
    monkeypatch.setattr(visor_api, "_AL_INICIO", {n: os.environ.get(n) for n in visor_api._AL_INICIO})
    monkeypatch.setattr(visor_api, "_cache_env", {"mtime": None, "valores": {}})
    assert visor_api.claves_visor() == {"clave-ana": "ana"}
    assert cliente.get("/visor/info", headers={"X-Visor-Key": "clave-ana"}).status_code == 200
    archivo.write_text("VISOR_API_KEYS=marlon:clave-marlon\n", encoding="utf-8")
    os.utime(archivo, (1, 2_000_000_000))                                          # surely a new mtime
    assert cliente.get("/visor/info", headers={"X-Visor-Key": "clave-ana"}).status_code == 401   # removed: no restart
    assert cliente.get("/visor/info", headers={"X-Visor-Key": "clave-marlon"}).json()["persona"] == "marlon"


# --------------------------------------------------------------------------- cliente remoto

def test_server_down_gives_a_clear_message(entorno, tmp_path):
    from visor_rutas.remoto import SIN_CONEXION, ProveedorRemoto
    proveedor = ProveedorRemoto("http://127.0.0.1:9", "x", carpeta=tmp_path)
    assert proveedor.calcular(f"{LAT}, {LON}") == {"ok": False, "error": SIN_CONEXION}
    assert "No se pudo conectar con el servidor de presupuestos" in SIN_CONEXION


def test_remote_errors_are_explained(entorno, tmp_path, monkeypatch):
    main, _, _, _, _ = entorno
    assert "clave del visor no es válida" in _api_remota(main, tmp_path, "mala").calcular("12.1, -86.2")["error"]
    monkeypatch.setenv("VISOR_API_KEYS", "")
    assert "no tiene habilitado el visor remoto" in _api_remota(main, tmp_path).calcular("12.1, -86.2")["error"]


def test_remote_mode_without_configuration_asks_for_it(entorno):
    from visor_rutas import config_visor, ventana_web
    api = ventana_web.Api(config_visor.ConfigVisor("remoto", "", ""))
    assert api.configuracion()["sin_configurar"] is True
    assert api.calcular("12.1, -86.2")["sin_configurar"] is True
    assert ventana_web.Api().configuracion()["modo"] == "local"                     # default: as before


def test_saved_key_is_encrypted_with_dpapi(tmp_path):
    from visor_rutas import config_visor
    archivo = tmp_path / "config.json"
    config_visor.guardar(config_visor.ConfigVisor("remoto", "broken-snowy.ngrok-free.dev/", "clave-secreta"), archivo)
    assert "clave-secreta" not in archivo.read_text(encoding="utf-8")
    leida = config_visor.leer(archivo)
    assert (leida.modo, leida.url, leida.clave) == ("remoto", "https://broken-snowy.ngrok-free.dev", "clave-secreta")
    assert config_visor.leer(tmp_path / "no_existe.json").modo == "local"


def test_remote_viewer_sends_the_poles_marked_as_existing(entorno, tmp_path):
    main, _, _, _, _ = entorno
    remota = _api_remota(main, tmp_path)
    ruta = remota.calcular(f"{LAT}, {LON}")["datos"]
    metros = ruta["postes_nuevos"]["metros"][:2]
    est = remota.estimar_presupuesto(LAT, LON, ruta["ruta"]["metraje_final_m"], metros)
    assert est["ok"] and est["supuestos"]["postes_marcados"] == 2
    pres = remota.generar_presupuesto({**CAMPOS, "postes_existentes_m": metros[:1]})
    assert pres["ok"] and pres["resultado"]["postes_marcados"] == 1
