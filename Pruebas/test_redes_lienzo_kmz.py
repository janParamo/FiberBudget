"""Esquema de zona: la posición de cada caja es la del KMZ (el punto del mismo nombre, el más cercano a la coordenada guardada), no la aproximada del Visio."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import lienzo


class KmzFalso:
    """Stands for the connection to the KMZ database: answers the one query of `coincidencias_kmz`."""

    def __init__(self, filas):
        self.filas, self.cerrada = filas, False

    def execute(self, sql, params=None):
        assert "red_puntos" in sql
        return self

    def fetchall(self):
        return self.filas

    def close(self):
        self.cerrada = True


def punto(id_, nombre, lat, lon, categoria="mufa"):
    return {"id": id_, "nombre": nombre, "categoria": categoria, "lat": lat, "lon": lon}


def test_each_mufa_takes_the_position_of_its_kmz_point(zona, monkeypatch):
    con, admin, p, ids = zona                                    # Nodo Jalapa 12.1000, MF Uno 12.1010, MF Dos 12.1020 (all at -86.3000)
    kmz = KmzFalso([punto(1, "MF  UNO", 12.1015, -86.2990),                            # same name (spaces / case ignored): 120 m from the saved one
                    punto(2, "MF DOS", 12.1500, -86.1000), punto(3, "mf dos", 12.1021, -86.3001),   # two with that name: the nearest to the saved one
                    punto(4, "Nodo Jalapa", 12.1000, -86.3000, categoria="poste de concreto"),     # a post is never a mufa
                    punto(5, "OTRA COSA", 12.1, -86.3)])
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: kmz)
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    por_nombre = {e["nombre"]: e for e in r["elementos"]}
    uno, dos, nodo = por_nombre["MF Uno"], por_nombre["MF Dos"], por_nombre["Nodo Jalapa"]
    assert (uno["kmz"]["id"], uno["kmz"]["lat"], uno["kmz"]["lon"]) == (1, 12.1015, -86.2990) and 100 < uno["kmz"]["distancia_m"] < 140
    assert dos["kmz"]["id"] == 3 and dos["kmz"]["distancia_m"] < 30                    # the near homonym, not the one 50 km away
    assert nodo["kmz"] is None and uno["lat"] == 12.1010                               # no match: it keeps its own coordinate (which is never overwritten)
    assert kmz.cerrada is True                                                         # the connection it opened is closed


def test_a_same_name_point_too_far_is_another_mufa(zona, monkeypatch):
    con, admin, p, ids = zona
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: KmzFalso([punto(9, "MF UNO", 12.2500, -86.3000)]))        # 15 km away
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    assert next(e for e in r["elementos"] if e["nombre"] == "MF Uno")["kmz"] is None


def test_without_the_kmz_everything_still_works(zona, monkeypatch):
    con, admin, p, ids = zona
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: None)
    r = lienzo.lienzo(con, admin, proyecto_id=p["id"])
    assert len(r["elementos"]) == 3 and all(e["kmz"] is None for e in r["elementos"])

    class Roto(KmzFalso):
        def execute(self, sql, params=None):
            raise RuntimeError("sin tabla")
    monkeypatch.setattr(lienzo, "conexion_kmz", lambda: Roto([]))
    assert all(e["kmz"] is None for e in lienzo.lienzo(con, admin, proyecto_id=p["id"])["elementos"])               # a failed query: no match, no error


def test_the_unreachable_kmz_is_not_asked_again_for_a_minute(monkeypatch):
    llamadas = []
    monkeypatch.setattr(lienzo, "_kmz_sin_acceso_hasta", 0.0)
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: llamadas.append(1) or (_ for _ in ()).throw(OSError("sin red")))
    assert lienzo.conexion_kmz() is None and lienzo.conexion_kmz() is None
    assert len(llamadas) <= 1                                                          # the second call does not try again
