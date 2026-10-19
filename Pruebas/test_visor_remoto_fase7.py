"""Visor v2, fase 7 (modo remoto para todo lo nuevo): lo que se hace desde VisorRutas.exe (la API remota del visor contra el servicio, por la X-Visor-Key) da lo
mismo que en local — medir, ruta editada, ruta de fusión, coordenadas masivas — y los archivos grandes (un KMZ completo) suben por partes y se usan por su id
para importarlos a la red. Mis lugares y la importación van por /visor/redes/* con los permisos de la persona de la clave."""
import base64
import json
import time

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_importar_kmz import ACTUALIZACION, RED_ACTUAL, hacer_kmz
from test_visor_api import JAN, LAT, LON, _api_remota, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas import kmz_capas, subidas
from visor_rutas.redes import db
from visor_rutas.redes.api import ServicioRedes

EDITADA = [[12.13, -86.25], [12.135, -86.255], [12.14, -86.25], [LAT, LON]]
CORTO = [[12.1300, -86.2500], [12.1320, -86.2500], [12.1320, -86.2490]]


def _b64(crudo: bytes) -> str:
    return base64.b64encode(crudo).decode("ascii")


@pytest.fixture(autouse=True)
def _subidas_limpias():
    subidas.almacen.reiniciar()
    yield
    subidas.almacen.reiniciar()


def _subir(api, nombre, crudo, parte=10_000):
    inicio = api.subir_iniciar(nombre, len(crudo))
    assert inicio["ok"], inicio
    for n, i in enumerate(range(0, len(crudo), parte)):
        assert api.subir_parte(inicio["id"], n, _b64(crudo[i:i + parte]))["ok"]
    fin = api.subir_fin(inicio["id"])
    return inicio["id"], fin


# --------------------------------------------------------------------------- archivos grandes por partes

def test_a_big_file_goes_up_in_parts_and_is_used_once_by_its_id(entorno, tmp_path):
    main, visor_api, cliente, _, _ = entorno
    remota = _api_remota(main, tmp_path)
    crudo = bytes(range(256)) * 200                                                     # 51,200 bytes in 6 parts
    id_, fin = _subir(remota, "grande.bin", crudo, parte=9000)
    assert fin["ok"] and fin["tamano"] == len(crudo) and fin["nombre"] == "grande.bin"
    assert subidas.almacen.tomar(id_) == ("grande.bin", crudo)                          # it arrives byte for byte...
    assert remota.subir_fin(id_)["ok"] is False                                         # ...and is handed over only once
    # incomplete or damaged uploads say so
    a = remota.subir_iniciar("a.bin", 100)["id"]
    remota.subir_parte(a, 0, _b64(b"x" * 40))
    assert "incompleto" in remota.subir_fin(a)["error"]
    b = remota.subir_iniciar("b.bin", 100)["id"]
    remota.subir_parte(b, 1, _b64(b"x" * 100))
    assert "Faltan partes" in remota.subir_fin(b)["error"]
    c = remota.subir_iniciar("c.bin", 10)["id"]
    assert "más de lo que se anunció" in remota.subir_parte(c, 0, _b64(b"x" * 11))["error"]
    assert "pesar hasta" in remota.subir_iniciar("d.bin", subidas.MAX_ARCHIVO + 1)["error"]
    assert "pesar hasta" in remota.subir_parte(remota.subir_iniciar("e.bin", 10)["id"], 0, _b64(b"x" * (subidas.MAX_PARTE + 1)))["error"]
    assert "ya no existe" in remota.subir_parte("noexiste123456", 0, _b64(b"x"))["error"]
    # the key is needed, and an id cannot be guessed by shape
    assert cliente.post("/visor/subidas", json={"nombre": "x", "tamano": 5}).status_code == 401
    assert cliente.post("/visor/subidas/malo!/0", content=b"x", headers=JAN).status_code == 422
    assert cliente.post("/visor/subidas", json={"nombre": "x", "tamano": 0}, headers=JAN).status_code == 422
    for _ in range(subidas.MAX_ACTIVAS):
        cliente.post("/visor/subidas", json={"nombre": "x", "tamano": 5}, headers=JAN)
    assert "demasiadas subidas" in cliente.post("/visor/subidas", json={"nombre": "x", "tamano": 5}, headers=JAN).json()["error"]


def test_the_uploaded_file_is_read_as_coordinates_from_the_exe(entorno, tmp_path):
    main, *_ = entorno
    remota = _api_remota(main, tmp_path)
    id_, fin = _subir(remota, "puntos.csv", b"Nombre,Latitud,Longitud\nUno,12.1364,-86.2514\nDos,12.14,-86.26\n")
    leido = remota.masivas_leer("puntos.csv", "", id_)
    assert leido["ok"] and leido["formato"] == "CSV" and [p["nombre"] for p in leido["puntos"]] == ["Uno", "Dos"]
    assert remota.masivas_leer("puntos.csv", "", id_)["ok"] is False                      # the id was used up


# --------------------------------------------------------------------------- lo mismo que en local

def test_measure_edited_route_and_fusion_plan_give_the_same_remotely(entorno, tmp_path):
    main, visor_api, cliente, salida, llamadas = entorno
    from visor_rutas import ventana_web
    local, remota = ventana_web.Api(), _api_remota(main, tmp_path)
    assert remota.medir_ruta(CORTO, False) == json.loads(json.dumps(local.medir_ruta(CORTO, False)))
    total = remota.medir_ruta(CORTO, True)
    assert total["ok"] and total["resultado"]["archivo"].startswith("remoto:") and total["medicion"] == local.medir_ruta(CORTO, False)["medicion"]
    antes = llamadas["google"]
    editada = remota.calcular_con_ruta(LAT, LON, EDITADA, 2)
    assert editada["ok"] and editada["datos"] == json.loads(json.dumps(local.calcular_con_ruta(LAT, LON, EDITADA, 2)["datos"]))
    assert llamadas["google"] == antes                                                  # an edited route never asks Google
    est = remota.estimar_presupuesto(LAT, LON, 900.0, None, EDITADA, 1, 1)
    assert est["ok"] and est["supuestos"] == local.estimar_presupuesto(LAT, LON, 900.0, None, EDITADA, 1, 1)["supuestos"]
    plan = {"pasos": [{"nombre": "MF UNO", "lat": 12.0, "lon": -86.0, "tocar": True, "hilo_cliente": "H1", "hilo_potencia": "H4"}], "potencia": "NODO X"}
    assert remota.redactar_fusion(plan) == json.loads(json.dumps(local.redactar_fusion(plan)))
    assert "libro de rutas de fusión" in remota.exportar_fusion(plan, {})["error"]       # the workbook is the server's: a missing one is a clear error
    assert remota.generar_presupuesto({"ticket_id": "T-1", "coordenada": f"{LAT}, {LON}", "client_name": "Cliente", "client_code": "C1", "sales_exec": "Ana",
                                       "contact_name": "Roxana", "contact_phone": "5880", "service_type": "Empresarial", "medium": "FO", "bandwidth": "50 Mbps",
                                       "technology": "auto", "odf_rack_ports": "ninguno", "raw_comment": "", "ruta_editada": EDITADA, "postes_a_mano": 2})["ok"]


def test_a_batch_of_coordinates_runs_on_the_server_and_comes_down_as_a_zip(entorno, tmp_path):
    import io
    import zipfile
    main, *_ = entorno
    remota = _api_remota(main, tmp_path)
    puntos = remota.masivas_leer("a.txt", _b64(b"Uno 12.1364, -86.2514\nDos 12.1400, -86.2600\n"))["puntos"]
    inicio = remota.masivas_iniciar("a.txt", puntos)
    assert inicio["ok"] and inicio["lote"]["total"] == 2
    for _ in range(300):
        lote = remota.masivas_estado(inicio["lote"]["id"], 0)["lote"]
        if lote["estado"] != "corriendo":
            break
        time.sleep(0.05)
    assert lote["estado"] == "terminado" and [r["ok"] for r in lote["resultados"]] == [True, True]
    zip_ = remota.masivas_descargar(inicio["lote"]["id"])
    assert zip_["ok"] and "Resumen.xlsx" in zipfile.ZipFile(io.BytesIO(base64.b64decode(zip_["datos"]))).namelist()
    assert remota.masivas_abrir_carpeta(inicio["lote"]["id"])["ok"] is False             # the folder is on the server: «Descargar .zip»
    assert remota.masivas_cancelar("20200101-000000")["ok"] is False


# --------------------------------------------------------------------------- la red por /visor/redes con los permisos de la persona

def test_import_kmz_and_mis_lugares_from_the_exe_follow_the_roles_of_the_key(base_redes, con_redes, entorno, tmp_path, monkeypatch):
    main, visor_api, cliente, _, _ = entorno
    _, params = base_redes
    servicio = ServicioRedes(conectar=lambda: db.conectar(params=params))
    kmz = tmp_path / "red.kmz"
    kmz.write_bytes(hacer_kmz(RED_ACTUAL))
    cache = tmp_path / "datos_kmz"
    kmz_capas.importar(kmz, cache, descargar_iconos=False)
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", cache)
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    try:
        remota = _api_remota(main, tmp_path)
        assert remota.redes("estado", {})["usuario"]["rol"] == "lector"
        archivo = hacer_kmz(ACTUALIZACION)
        id_, fin = _subir(remota, "actualizacion.kmz", archivo, parte=700)
        lector = remota.redes("importar_kmz_red", {"subida_id": id_, "nombre": "actualizacion.kmz"})
        assert lector["ok"] is False and "administrador o un editor" in lector["error"]       # a reader cannot import (the id is not even used)
        con_redes.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'jan'")
        id_, fin = _subir(remota, "actualizacion.kmz", archivo, parte=700)
        r = remota.redes("importar_kmz_red", {"subida_id": id_, "nombre": "actualizacion.kmz"})
        assert r["ok"] and r["importacion"]["modo"] == "actualizacion" and r["importacion"]["conteos"]["por_clase"] == {"nuevo": 1, "modificado": 3, "sin_cambios": 2, "eliminado": 1}
        imp = r["importacion"]["id"]
        assert remota.redes("importacion_kmz", {"id": imp, "clase": "nuevo"})["filas"][0]["nombre"] == "MF CUATRO"
        assert remota.redes("aplicar_importacion_kmz", {"id": imp})["aplicados"] == {"nuevo": 1, "modificado": 3, "eliminado": 0}
        assert [e["nombre"] for e in remota.redes("capa_importados_kmz", {})["elementos"]] == ["MF CUATRO"]
        assert remota.redes("publicar_importacion_kmz", {"id": imp})["ok"] is False             # only an administrator publishes (and never by accident in the test)
        assert remota.redes("revertir_importacion_kmz", {"id": imp})["importacion"]["estado"] == "revertida"
        # Mis lugares from the exe: own folders for any role, the KMZ cambios only for editors
        carpeta = remota.redes("guardar_carpeta_lugares", {"nombre": "Mi visita"})
        assert carpeta["ok"] and remota.redes("lugares_desde_masivas", {"nombre": "Lote", "puntos": [{"n": 1, "nombre": "A", "lat": 12.1, "lon": -86.2}]})["puntos"] == 1
        assert remota.redes("cambios_kmz", {})["ok"] and remota.redes("editar_kmz", {"clave": "k", "carpeta": "c", "tipo": "punto", "antes": {"nombre": "A", "lat": 1, "lon": 1}, "nombre": "B"})["ok"]
        con_redes.execute("UPDATE redes.usuarios SET rol = 'lector' WHERE persona_visor = 'jan'")
        assert "administrador o un editor" in remota.redes("editar_kmz", {"clave": "k2", "carpeta": "c", "tipo": "punto", "antes": {"nombre": "A", "lat": 1, "lon": 1}, "nombre": "B"})["error"]
        assert remota.redes("guardar_carpeta_lugares", {"nombre": "Otra mía"})["ok"] is True
    finally:
        servicio.cerrar()
