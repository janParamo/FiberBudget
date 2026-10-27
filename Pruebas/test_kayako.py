"""Lectura de los tickets de Kayako (visor_rutas/kayako.py): solo SELECT y en modo solo lectura, los filtros de business_rules.yaml, y de cada ticket el texto de sus
comentarios (HTML), los datos del cliente y las coordenadas que traiga escritas. La base se simula: no se conecta a ninguna."""
import re

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from visor_rutas import kayako

FILA = {"id": 501, "ticket": "XKJ-813-61728", "asunto": "Presupuesto FO Tiendas Matagalpa", "cliente": "DAVID ALBERTO TOVAR JUAREZ", "ejecutivo": "Yader Ramirez",
        "departamento": "Fibra Optica", "tipo": "Presupuesto FO", "estado": "Abierto", "owner": "Jan", "creado": 1_792_000_000,
        "primer_comentario": "<p>• Nombre de cliente: David Alberto Tovar Juarez<br>• Código de cliente: C35307<br>• Persona de contacto: Grace Gutiérrez<br>"
                             "• Teléfono: 85999439</p><div>Ubicación: 12.727598, -86.125644 y también 12.836523, -85.462874</div>&nbsp;Ancho de Banda: 20M",
        "primer_html": 1, "ultimo_comentario": "Favor revisar&nbsp;la zona.\r\n\r\n\r\n\r\nGracias", "ultimo_html": 0, "ultima_actividad": 1_792_100_000}


class Cursor:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.con.ejecutados.append((sql, params))

    def fetchall(self):
        return [dict(FILA)]


class Conexion:
    def __init__(self):
        self.ejecutados, self.cerrada = [], False

    def cursor(self):
        return Cursor(self)

    def close(self):
        self.cerrada = True


def test_the_query_is_one_select_with_the_filters_as_parameters_and_the_connection_is_read_only(monkeypatch):
    con = Conexion()
    filas = kayako.tickets(1_700_000_000, 20, abrir=lambda: con)
    assert filas == [FILA] and con.cerrada
    sql, params = con.ejecutados[0]
    assert sql.strip().upper().startswith("SELECT") and not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b", sql, re.I)
    assert "kayako_fusion.swtickets" in sql and "swcustomfieldvalues" in sql and sql.count("%s") == len(params)
    assert params == (64, "%Fibra%Optica%", "%Presupuesto%FO%", "Abierto", "En Espera", 1_700_000_000, 20)           # filters of business_rules.yaml, never glued into the text
    with pytest.raises(ValueError):
        kayako.consulta("kayako; DROP TABLE x", 1)                                                                  # the name of the database is checked
    # the real connection function opens read-only: first thing it runs
    import pymysql
    llamadas = {}
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    real = Conexion()
    monkeypatch.setattr(pymysql, "connect", lambda **kw: llamadas.update(kw) or real)
    kayako.conectar()
    assert real.ejecutados[0][0] == "SET SESSION TRANSACTION READ ONLY" and llamadas["host"] == "10.0.0.5" and llamadas["database"] == "kayako_fusion" and llamadas["port"] == 3306


def test_without_the_connection_in_the_env_it_says_what_is_missing(monkeypatch):
    for k in ("KAYAKO_DB_HOST", "KAYAKO_DB_USER", "KAYAKO_DB_PASSWORD"):
        monkeypatch.setenv(k, "")
    assert kayako.configurada() is False
    with pytest.raises(RuntimeError, match="KAYAKO_DB_HOST"):
        kayako.conectar()


def test_a_ticket_becomes_text_client_data_and_coordinates():
    d = kayako.datos_del_ticket(FILA)
    assert (d["ticket"], d["cliente"], d["ejecutivo"], d["estado"], d["kayako_id"]) == ("XKJ-813-61728", "DAVID ALBERTO TOVAR JUAREZ", "Yader Ramirez", "Abierto", 501)
    assert d["campos"] == {"client_name": "David Alberto Tovar Juarez", "client_code": "C35307", "contact_name": "Grace Gutiérrez", "contact_phone": "85999439"}
    assert d["coordenadas"] == [[12.727598, -86.125644], [12.836523, -85.462874]]
    assert "<" not in d["comentario"] and "Código de cliente: C35307" in d["comentario"] and "\xa0" not in d["comentario"]
    assert d["ultimo_comentario"] == "Favor revisar la zona.\n\nGracias"                                           # entities decoded, blank lines squeezed
    assert d["creado"] and d["ultima_actividad"]
    # a ticket with nothing written in it: nothing is invented
    vacio = kayako.datos_del_ticket({"id": 1, "ticket": "T-1", "cliente": "Ana", "primer_comentario": None, "ultimo_comentario": None})
    assert vacio["campos"] == {} and vacio["coordenadas"] == [] and vacio["comentario"] == "" and vacio["creado"] is None


def test_the_preview_asks_for_the_last_days_and_parses_every_ticket(monkeypatch):
    pedido = {}
    monkeypatch.setattr(kayako, "tickets", lambda desde, limite, abrir: pedido.update(desde=desde, limite=limite) or [dict(FILA)])
    lista = kayako.vista_previa(2, 5)
    assert [t["ticket"] for t in lista] == ["XKJ-813-61728"] and pedido["limite"] == 5 and 2 * 86400 - 60 < __import__("time").time() - pedido["desde"] < 2 * 86400 + 60
