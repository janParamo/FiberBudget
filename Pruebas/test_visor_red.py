"""Network layers of the viewer (visor_rutas/red.py and Api.red), with the databases simulated."""
import importlib
import json
import os
import sqlite3
from pathlib import Path

import psycopg
import pytest

from make_sample_template import create_template

SCHEMA = Path(__file__).resolve().parent.parent / "red_fibra" / "schema.sql"
RECT = (-86.30, 12.10, -86.20, 12.20)          # oeste, sur, este, norte


@pytest.fixture
def red(tmp_path, monkeypatch):
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
    from visor_rutas import red as modulo
    return modulo


class _ConexionFalsa:
    """Stands in for the PostGIS connection: records the queries and returns fixed rows."""

    def __init__(self, filas):
        self.filas, self.consultas = filas, []

    def execute(self, sql, params):
        self.consultas.append((sql, params))
        filas = self.filas
        return type("Cursor", (), {"fetchall": lambda self_: filas})()


def test_debajo_del_zoom_minimo_no_consulta_nada(red):
    for capa, conf in red.CAPAS.items():
        res = red.consultar(capa, *RECT, conf["zoom_min"] - 1)          # no connection needed
        assert res["debajo_del_zoom"] is True and res["elementos"] == []


def test_capa_o_rectangulo_no_validos(red):
    with pytest.raises(red.CapaNoValida):
        red.consultar("todo", *RECT, 18)
    with pytest.raises(red.CapaNoValida):
        red.consultar("kmz_mufas", -86.2, 12.1, -86.3, 12.2, 18, kmz_con=_ConexionFalsa([]))   # oeste > este
    with pytest.raises(ConnectionError):
        red.consultar("kmz_mufas", *RECT, 18, kmz_con=None)


def test_mufas_del_kmz_en_la_vista_con_excluidas_y_maximo(red, monkeypatch):
    con = _ConexionFalsa([(1, "mufa", "MF UNO", "desc " * 100, 12.15, -86.25),
                          (2, "mufa mal estado", "MF DOS", None, 12.16, -86.26),
                          (3, "mufa", None, None, 12.17, -86.27)])
    monkeypatch.setitem(red.CAPAS, "kmz_mufas", {**red.CAPAS["kmz_mufas"], "max": 2})
    res = red.consultar("kmz_mufas", *RECT, 17, kmz_con=con)
    sql, params = con.consultas[0]
    assert "red_puntos" in sql and "ST_MakeEnvelope" in sql
    assert params["tipo"] == "mufa%" and (params["o"], params["n"]) == (-86.30, 12.20) and params["limite"] == 3
    assert [m["nombre"] for m in res["elementos"]] == ["MF UNO", "MF DOS"]       # capped at the maximum
    assert res["truncado"] is True
    assert [m["excluida"] for m in res["elementos"]] == [False, True]            # "mal estado" in business_rules
    assert res["elementos"][0]["descripcion"].endswith("…") and (res["elementos"][0]["lat"], res["elementos"][0]["lon"]) == (12.15, -86.25)


def test_lineas_del_kmz_simplificadas_segun_el_zoom(red):
    multi = json.dumps({"type": "MultiLineString", "coordinates": [[[-86.25, 12.15], [-86.24, 12.16]],
                                                                    [[-86.23, 12.17], [-86.22, 12.18], [-86.21, 12.19]]]})
    linea = json.dumps({"type": "LineString", "coordinates": [[-86.2, 12.1], [-86.1, 12.2]]})
    con = _ConexionFalsa([(10, "troncal", "CABLE 48H", None, multi), (11, "acometida", None, None, linea),
                          (12, "x", None, None, None)])
    res = red.consultar("kmz_lineas", *RECT, 15, kmz_con=con)
    assert con.consultas[0][1]["tol"] == pytest.approx(360 / (256 * 2 ** 15))
    assert [e["id"] for e in res["elementos"]] == [10, 11]                       # no geometry: dropped
    assert res["elementos"][0]["lineas"] == [[[12.15, -86.25], [12.16, -86.24]],
                                             [[12.17, -86.23], [12.18, -86.22], [12.19, -86.21]]]  # [lat, lon]
    assert res["truncado"] is False


def test_nodos_y_enlaces_visio_de_la_vista(red, tmp_path):
    ruta = tmp_path / "rf.db"
    con = sqlite3.connect(ruta)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executemany("INSERT INTO nodos(id, nombre, nombre_normalizado, tipo, lat, lon, fuente_coord) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(1, "MF DENTRO", "MUFA DENTRO", "MUFA", 12.15, -86.25, "visio"),
                     (2, "NODO DENTRO", "NODO DENTRO", "NODO", 12.16, -86.24, "estimada_vecinos"),
                     (3, "MF FUERA", "MUFA FUERA", "MUFA", 13.00, -86.00, "visio"),
                     (4, "C12345", "C12345", "CLIENTE", 12.15, -86.25, "visio"),
                     (5, "MF SIN COORD", "MUFA SIN COORD", "MUFA", None, None, None)])
    con.executemany("INSERT INTO enlaces(nodo_a_id, nodo_b_id, fuente, confianza, hilos_cable) VALUES (?, ?, ?, ?, ?)",
                    [(1, 3, "visio_linea", "media", 24), (3, 3, "excel", "alta", None), (1, 5, "visio_mufa", "media", None)])
    con.commit()
    con.close()
    nodos = red.consultar("visio_nodos", *RECT, 14, archivo_sqlite=ruta)["elementos"]
    assert [(n["nombre"], n["estimada"]) for n in nodos] == [("MF DENTRO", False), ("NODO DENTRO", True)]
    enlaces = red.consultar("visio_enlaces", *RECT, 14, archivo_sqlite=ruta)["elementos"]
    assert len(enlaces) == 1                                   # one end inside the view, both with coordinates
    assert enlaces[0]["nombre"] == "MF DENTRO ↔ MF FUERA" and enlaces[0]["hilos"] == 24
    assert enlaces[0]["lineas"] == [[[12.15, -86.25], [13.0, -86.0]]]
    with pytest.raises(FileNotFoundError):
        red.consultar("visio_nodos", *RECT, 14, archivo_sqlite=tmp_path / "no_existe.db")


def test_api_red_mensajes_claros(red, monkeypatch):
    from visor_rutas import ventana_web
    api = ventana_web.Api()
    assert api.red("todo", *RECT, 18) == {"ok": False, "error": "Capa desconocida"}

    def caida():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(red, "conectar_kmz", caida)
    assert api.red("kmz_mufas", *RECT, 18) == {
        "ok": False, "error": "No se pudo consultar la base del KMZ (PostGIS) para mufas del KMZ"}
    # below the minimum zoom the database is not even opened
    assert api.red("kmz_mufas", *RECT, 10)["debajo_del_zoom"] is True
    monkeypatch.setattr(red, "conectar_kmz", lambda: _ConexionFalsa([(1, "mufa", "MF UNO", None, 12.15, -86.25)]))
    res = api.red("kmz_mufas", *RECT, 18)
    assert res["ok"] is True and res["elementos"][0]["nombre"] == "MF UNO"
    assert api.red("visio_nodos", *RECT, 14) == {"ok": False, "error": "No se encontró la base de diagramas (red_fibra)"}
