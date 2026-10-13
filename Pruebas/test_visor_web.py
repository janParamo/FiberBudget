"""Visor de rutas web (visor_rutas/ventana_web.py) and the start-up choice in __main__.py.

pywebview is not needed: Api is plain Python and `import webview` only happens in abrir().
"""
import importlib
import json
import os
import sys
import types
from decimal import Decimal

import pytest

from make_sample_template import create_template


@pytest.fixture
def web(tmp_path, monkeypatch):
    template = tmp_path / "t.xlsx"
    create_template(template)
    env = {"DB_HOST": "x", "DB_PORT": "5432", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
           "GOOGLE_API_KEY": "x", "SERVICE_API_KEY": "secret",
           "TEMPLATE_PATH": str(template), "OUTPUT_DIR": str(tmp_path / "out"),
           "LOG_FILE": str(tmp_path / "log.txt"),
           "RED_FIBRA_DB": str(tmp_path / "missing_red_fibra.db"), "VISIO_DB_NAME": "",
           "RULES_PATH": os.path.join(os.path.dirname(__file__), "..", "business_rules.yaml")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    config.get_settings.cache_clear()
    import main
    importlib.reload(main)
    from visor_rutas import ventana_web
    return ventana_web


def _resultado_simulado():
    """Shape of calcular_ruta's result, with the Python types it really contains."""
    return {
        "cliente": {"lat": 12.1364, "lon": -86.2514},
        "conexion": {"nombre": "MF PRUEBA", "tipo": "mufa", "tipo_detalle": "mufa", "id": 7,
                     "lat": 12.13, "lon": -86.25, "distancia_lineal_m": 120.0, "fuente": "kmz",
                     "requiere_revision": False, "notas": None},
        "ruta": {"puntos": [(12.13, -86.25), (12.14, -86.25)], "distancia_m": 1850.0,
                 "metraje_final_m": Decimal("2140.5"), "reserva_m": 290.5, "tipo_cable": "ADSS 24 hilos",
                 "aproximada": False, "acometida_m": 12.3},
        "postes_existentes": [(8, 12.135, -86.25), ("poste-9", 12.14, -86.2495)],
        "postes_nuevos": {"cantidad": 1, "posiciones": [(12.137, -86.25)], "spacing_m": 50},
        "mufas_en_ruta": [{"id": 31, "nombre": "Mufa 31", "tipo": "mufa", "lat": 12.14, "lon": -86.249,
                           "distancia_m": 3.0, "troncal": False}],
        "mufas_intervenidas": [{"id": "diagrama:MF X", "nombre": "MF X", "lat": None, "lon": None},
                               {"id": 2 ** 60, "nombre": "MF GRANDE", "lat": 12.1, "lon": -86.2}],
        "mufas_intervenidas_fuente": "diagramas", "distribution_reason": None,
        "nodos_visio_cercanos": [{"nombre": "NODO X", "tipo": "NODO", "lat": Decimal("12.16"),
                                  "lon": Decimal("-86.27"), "distancia_m": 900.0, "notas": None}],
        "origen_trafico": {"nodo": "OLT MERCED", "mf": None, "confianza": "media", "camino": ("A", "B"),
                           "motivo": None},
        "avisos": [],
        "no_finito": float("nan"),
    }


def test_calcular_devuelve_json_serializable(web, monkeypatch):
    llamadas = []
    monkeypatch.setattr(web, "calcular_ruta", lambda lat, lon: (llamadas.append((lat, lon)), _resultado_simulado())[1])
    res = web.Api().calcular("12.1364; -86.2514")

    assert llamadas == [(12.1364, -86.2514)]
    assert res["ok"] is True and res["coordenada"] == "12.136400, -86.251400"
    texto = json.dumps(res, allow_nan=False)                 # strict JSON, as JavaScript reads it
    datos = json.loads(texto)["datos"]
    assert datos["ruta"]["puntos"] == [[12.13, -86.25], [12.14, -86.25]]
    assert datos["ruta"]["metraje_final_m"] == 2140.5
    assert datos["postes_existentes"][1] == ["poste-9", 12.14, -86.2495]
    assert datos["mufas_intervenidas"][1]["id"] == str(2 ** 60)    # too big for a JS number
    assert datos["nodos_visio_cercanos"][0]["lat"] == 12.16
    assert datos["origen_trafico"]["camino"] == ["A", "B"]
    assert datos["no_finito"] is None


@pytest.mark.parametrize("texto, fragmento", [
    ("40.4, -3.7", "fuera de Nicaragua"),
    ("-86.263438, 12.153328", "invertidas"),
    ("12.15", "separadas por coma"),
    ("", "separadas por coma"),
])
def test_calcular_con_texto_invalido_devuelve_el_mensaje_de_parsear(web, monkeypatch, texto, fragmento):
    from visor_rutas.calculo import CoordenadaInvalida, parsear_coordenadas

    monkeypatch.setattr(web, "calcular_ruta", lambda *a: pytest.fail("must not calculate an invalid coordinate"))
    res = web.Api().calcular(texto)
    with pytest.raises(CoordenadaInvalida) as esperado:
        parsear_coordenadas(texto)
    assert res == {"ok": False, "error": str(esperado.value)}
    assert fragmento in res["error"]


def test_error_del_calculo_conserva_la_coordenada_para_el_historial(web, monkeypatch):
    from visor_rutas.calculo import SinPuntoConexion

    def sin_punto(lat, lon):
        raise SinPuntoConexion("No se encontró mufa, reserva ni nodo de red para esta coordenada")

    monkeypatch.setattr(web, "calcular_ruta", sin_punto)
    res = web.Api().calcular("12.1364, -86.2514")
    assert res == {"ok": False, "error": "No se encontró mufa, reserva ni nodo de red para esta coordenada",
                   "coordenada": "12.136400, -86.251400"}


def test_error_inesperado_es_mensaje_claro(web, monkeypatch):
    monkeypatch.setattr(web, "calcular_ruta", lambda lat, lon: 1 / 0)
    res = web.Api().calcular("12.1364, -86.2514")
    assert res["ok"] is False and "Error inesperado (ZeroDivisionError)" in res["error"]
    assert "logs/visor.log" in res["error"]


def test_configuracion_usa_las_mismas_capas_que_el_resto(web):
    import mapa_ruta

    cfg = web.Api().configuracion()
    assert cfg["imagery_url"] == mapa_ruta.IMAGERY_URL and cfg["labels_url"] == mapa_ruta.LABELS_URL
    assert cfg["drop_min_m"] == mapa_ruta.DROP_MIN_M
    json.dumps(cfg)


def test_copiar_reporta_el_error_sin_romper(web, monkeypatch):
    def ocupado(texto):
        raise OSError("El portapapeles está ocupado por otro programa")

    monkeypatch.setattr(web, "copiar_al_portapapeles", ocupado)
    assert web.Api().copiar("x") == {"ok": False, "error": "No se pudo copiar: El portapapeles está ocupado por otro programa"}
    monkeypatch.setattr(web, "copiar_al_portapapeles", lambda texto: None)
    assert web.Api().copiar("x") == {"ok": True}


def test_html_carga_solo_librerias_locales(web):
    html = web.HTML.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html      # no CDN
    for ruta in ("lib/leaflet/leaflet.js", "lib/leaflet/leaflet.css", "lib/markercluster/leaflet.markercluster.js",
                 "lib/polylinedecorator/leaflet.polylineDecorator.js", "visor.js", "visor.css"):
        assert ruta in html
        assert (web.HTML.parent / ruta).is_file(), ruta


# --------------------------------------------------------------------------- __main__

def test_sin_pywebview_se_elige_tkinter(monkeypatch):
    from visor_rutas import __main__ as arranque

    monkeypatch.setitem(sys.modules, "webview", None)            # import webview -> ImportError
    assert arranque.elegir_interfaz([]) == "tk"


def test_con_pywebview_se_elige_web_salvo_con_tk(monkeypatch):
    from visor_rutas import __main__ as arranque

    monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))
    assert arranque.elegir_interfaz([]) == "web"
    assert arranque.elegir_interfaz(["--tk"]) == "tk"


def test_si_la_ventana_web_falla_se_abre_tkinter(web, monkeypatch):
    from visor_rutas import __main__ as arranque

    abiertas = []
    monkeypatch.setattr(arranque, "_preparar_log", lambda: arranque.log)
    monkeypatch.setattr(arranque.os, "chdir", lambda path: None)
    monkeypatch.setattr(arranque, "elegir_interfaz", lambda argv: "web")
    monkeypatch.setattr(web, "abrir", lambda: (_ for _ in ()).throw(RuntimeError("WebView2 no disponible")))
    monkeypatch.setattr(arranque, "_abrir_tk", lambda: abiertas.append("tk"))
    arranque.main([])
    assert abiertas == ["tk"]

    abiertas.clear()
    monkeypatch.setattr(web, "abrir", lambda: abiertas.append("web"))
    arranque.main([])
    assert abiertas == ["web"]                                   # closed normally: no Tkinter after it
