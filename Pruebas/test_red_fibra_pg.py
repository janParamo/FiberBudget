"""Nearest Visio node: selection rules, plus checks against the real Presupuesto_visio database
(skipped when it is not reachable or VISIO_DB_NAME is not configured)."""
import pytest

import config
import red_fibra_pg
from red_fibra_pg import BusquedaVisio, bloque_origen, elegir_candidato, requiere_revision


def _c(nombre, tipo="MUFA", distancia_m=10.0, fuente_coord="visio", notas=None):
    return {"id": hash(nombre) % 10000, "nombre": nombre, "tipo": tipo, "lat": 12.1, "lon": -86.2,
            "fuente_coord": fuente_coord, "notas": notas, "distancia_m": distancia_m}


def test_estimated_coordinates_drop_out_when_a_real_one_exists():
    elegido, alternativas = elegir_candidato([
        _c("ESTIMADA", distancia_m=5, fuente_coord="estimada_vecinos"), _c("REAL", distancia_m=80)])
    assert elegido["nombre"] == "REAL"
    assert [c["nombre"] for c in alternativas] == ["ESTIMADA"]
    solo_estimadas, _ = elegir_candidato([_c("E1", fuente_coord="estimada_vecinos")])
    assert solo_estimadas["nombre"] == "E1" and requiere_revision(solo_estimadas)


def test_mufa_or_nodo_beats_a_closer_mini_nodo_or_odf_within_50_m():
    assert elegir_candidato([_c("ODF", "ODF", 10), _c("MUFA", "MUFA", 55)])[0]["nombre"] == "MUFA"
    assert elegir_candidato([_c("MINI", "MINI_NODO", 10), _c("MUFA", "MUFA", 61)])[0]["nombre"] == "MINI"


def test_validar_note_requires_review_and_alternatives_cap_at_four():
    assert requiere_revision(_c("X", notas="SANGRIA, VALIDAR"))
    assert not requiere_revision(_c("X", notas="SANGRIA"))
    _, alternativas = elegir_candidato([_c(f"M{i}", distancia_m=i) for i in range(7)])
    assert len(alternativas) == 4


def test_block_for_kmz_point_when_visio_is_down():
    block = bloque_origen(busqueda=BusquedaVisio(fuente="sin_conexion_bd", radio_m=2000), punto={
        "nombre": "MF A", "tipo": "mufa", "lat": 12.1, "lon": -86.2, "distancia_m": 40.0},
        desde_visio=False, verificacion=None, distancia_ruta_m=210.0, radio_kmz_m=500)
    assert (block["fuente"], block["encontrado"], block["requiere_revision"]) == ("sin_conexion_bd", False, False)
    assert (block["nombre"], block["fuente_coord"], block["distancia_ruta_m"]) == ("MF A", "kmz", 210.0)
    assert red_fibra_pg.leyenda_punto_conexion(block) == ""


# --- real database -----------------------------------------------------------------------------

@pytest.fixture
def real_conn():
    config.get_settings.cache_clear()
    if not red_fibra_pg.enabled():
        pytest.skip("VISIO_DB_NAME not configured")
    conn = red_fibra_pg.connect_or_none()
    if conn is None:
        pytest.skip("Presupuesto_visio not reachable")
    yield conn
    conn.close()


def test_real_loyola_first_candidate(real_conn):
    busqueda = red_fibra_pg.buscar_origen(12.153328, -86.263438, 2000, real_conn)
    assert busqueda.fuente == "red_fibra" and busqueda.fecha_red
    assert busqueda.nodo["nombre"] in ("MF LOYOLA #2 MUFA FOSC", "MUFA FOSC CONTINUIDAD")
    assert busqueda.nodo["distancia_m"] == pytest.approx(76, abs=2)


def test_real_coordinate_in_the_sea_finds_nothing(real_conn):
    busqueda = red_fibra_pg.buscar_origen(11.0, -87.5, 2000, real_conn)
    assert busqueda.fuente == "red_fibra" and busqueda.encontrado is False


def test_wrong_password_is_sin_conexion(monkeypatch):
    config.get_settings.cache_clear()
    if not red_fibra_pg.enabled():
        pytest.skip("VISIO_DB_NAME not configured")
    monkeypatch.setenv("VISIO_DB_PASSWORD", "contraseña-incorrecta")
    config.get_settings.cache_clear()
    try:
        conn = red_fibra_pg.connect_or_none()
        assert conn is None
        assert red_fibra_pg.buscar_origen(12.153328, -86.263438, 2000, conn).fuente == "sin_conexion_bd"
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()
