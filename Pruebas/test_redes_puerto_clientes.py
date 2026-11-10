"""Mufa: un cliente puesto en la salida de un splitter (como el de un hilo): se crea junto con el splitter, se cambia, se mueve de salida y se quita."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa
from visor_rutas.redes.mufa import DatosInvalidos


def _servicios(con, admin, mufa_id):
    return {(s["nombre"], n): v for s in mufa.leer(con, admin, mufa_id=mufa_id)["splitters"] for n, v in s["servicios"].items()}


def test_a_client_is_put_on_a_splitter_output_changed_moved_and_taken_off(mundo):
    con, admin, proyecto, ids = mundo
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={
        "splitters": [{"id": "s1", "nombre": "SPL 1X8", "salidas": 8, "x": 470, "y": 40}],
        "puerto_clientes": [{"splitter": "s1", "numero": 2, "codigo_cliente": " c24656 ", "nombre": "BANCO DE FOMENTO", "id_servicio": "ID374588"}]})
    sid = r["ids"]["s1"]
    assert _servicios(con, admin, ids["a"]) == {("SPL 1X8", 2): {"version": 1, "codigo_cliente": "C24656", "nombre": "BANCO DE FOMENTO", "id_servicio": "ID374588", "elemento_id": None, "fuente": "usuario"}}
    # changed: same output, another name
    v = _servicios(con, admin, ids["a"])[("SPL 1X8", 2)]["version"]
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"puerto_clientes": [{"splitter": sid, "numero": 2, "codigo_cliente": "C24656", "nombre": "BANCO NUEVO", "version": v}]})
    assert _servicios(con, admin, ids["a"])[("SPL 1X8", 2)]["nombre"] == "BANCO NUEVO"
    # moved to output 5: taken off 2, put on 5, in one save
    v = _servicios(con, admin, ids["a"])[("SPL 1X8", 2)]["version"]
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"puerto_clientes": [
        {"splitter": sid, "numero": 2, "quitar": True, "version": v}, {"splitter": sid, "numero": 5, "codigo_cliente": "C24656", "nombre": "BANCO NUEVO"}]})
    assert list(_servicios(con, admin, ids["a"])) == [("SPL 1X8", 5)]
    # taken off
    v = _servicios(con, admin, ids["a"])[("SPL 1X8", 5)]["version"]
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"puerto_clientes": [{"splitter": sid, "numero": 5, "quitar": True, "version": v}]})
    assert _servicios(con, admin, ids["a"]) == {}
    # what is not valid is refused: a wrong code, an output that does not exist
    with pytest.raises(DatosInvalidos):
        mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"puerto_clientes": [{"splitter": sid, "numero": 1, "codigo_cliente": "xyz"}]})
    with pytest.raises(DatosInvalidos):
        mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"puerto_clientes": [{"splitter": sid, "numero": 9, "codigo_cliente": "C1234"}]})
