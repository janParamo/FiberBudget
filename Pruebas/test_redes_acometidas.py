"""Acometidas (visor_rutas/redes/acometidas.py): un cable nuevo de 2…96 hilos que sale de una mufa; sus hilos se conectan y reciben clientes."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import _hilo, mundo  # noqa: F401  (fixture)
from visor_rutas.redes import acometidas, mufa
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado


def _acometida(vista, nombre):
    return next(c for c in vista["cables"] if c["nombre"] == nombre)


def test_an_acometida_is_a_new_cable_with_its_fibres_that_takes_clients_and_connections(mundo):
    con, admin, p, ids = mundo
    r = acometidas.crear(con, admin, mufa_id=ids["b"], nombre="Acometida Café", hilos=24)
    c = _acometida(r, "Acometida Café")
    assert (c["clase"], c["hilos"], c["lado"], len(c["fibras"])) == ("acometida", 24, "salida", 24) and r["acometida"]["cable_id"] == c["id"]
    assert acometidas.crear(con, admin, mufa_id=ids["b"], hilos="2")["cables"][-1]["nombre"] == "Acometida 2"          # the name by default counts the ones that are there
    # its fibres take a client and are connected with the fibres of the mufa, like any cable
    h1 = next(f for f in c["fibras"] if f["numero"] == 1)
    d5 = _hilo(con, admin, ids["b"], "Otro", 5)
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={
        "hilo_clientes": [{"hilo_id": h1["id"], "codigo_cliente": "C28995", "nombre": "Casa del Café"}],
        "conexiones": [{"id": "n1", "a": {"hilo": h1["id"]}, "b": {"hilo": d5["id"]}}]})
    c = _acometida(r, "Acometida Café")
    assert next(f for f in c["fibras"] if f["numero"] == 1)["cliente"]["codigo_cliente"] == "C28995" and len(r["conexiones"]) == 1


def test_the_hilos_allowed_and_a_mufa_without_coordinate_are_refused(mundo):
    con, admin, p, ids = mundo
    for malo in (3, 144, "x", 0):
        with pytest.raises(DatosInvalidos):
            acometidas.crear(con, admin, mufa_id=ids["b"], hilos=malo)
    for bueno in (2, 4, 6, 8, 12, 24, 48, 72, 96):
        assert acometidas.crear(con, admin, mufa_id=ids["b"], hilos=bueno)["acometida"]["hilos"] == bueno
    con.execute("UPDATE redes.elementos SET ubicacion = NULL, ubicacion_fuente = 'sin_ubicar' WHERE id = %s", (ids["c"],))
    with pytest.raises(DatosInvalidos):
        acometidas.crear(con, admin, mufa_id=ids["c"], hilos=2)


def test_it_is_renamed_connected_to_another_mufa_and_deleted(mundo):
    con, admin, p, ids = mundo
    r = acometidas.crear(con, admin, mufa_id=ids["b"], nombre="Acometida A", hilos=12)
    c = _acometida(r, "Acometida A")
    assert [x["id"] for x in acometidas.mufas_para_conectar(con, admin, mufa_id=ids["b"])["mufas"]][:2] in ([ids["a"], ids["c"]], [ids["c"], ids["a"]])
    r = acometidas.actualizar(con, admin, mufa_id=ids["b"], cable_id=c["id"], nombre="Acometida Nueva")
    assert _acometida(r, "Acometida Nueva")["id"] == c["id"]
    n_clientes = con.execute("SELECT count(*) AS n FROM redes.elementos WHERE tipo = 'cliente' AND borrado_en IS NULL").fetchone()["n"]
    # connected to MF Otra: the cable now goes there and the filler end is gone
    r = acometidas.actualizar(con, admin, mufa_id=ids["b"], cable_id=c["id"], destino_mufa_id=ids["c"])
    c = _acometida(r, "Acometida Nueva")
    assert c["otro"]["id"] == ids["c"] and c["otro"]["tipo"] == "mufa"
    assert con.execute("SELECT count(*) AS n FROM redes.elementos WHERE tipo = 'cliente' AND borrado_en IS NULL").fetchone()["n"] == n_clientes - 1
    with pytest.raises(DatosInvalidos):
        acometidas.actualizar(con, admin, mufa_id=ids["b"], cable_id=c["id"], destino_mufa_id=ids["b"])             # not to itself
    # deleted: the cable and the clients on its fibres go
    h = next(f for f in c["fibras"] if f["numero"] == 2)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"hilo_clientes": [{"hilo_id": h["id"], "codigo_cliente": "C11111", "nombre": "X"}]})
    r = acometidas.eliminar(con, admin, mufa_id=ids["b"], cable_id=c["id"])
    assert all(x["nombre"] != "Acometida Nueva" for x in r["cables"])
    assert con.execute("SELECT count(*) AS n FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", (h["id"],)).fetchone()["n"] == 0
    with pytest.raises(NoEncontrado):
        acometidas.eliminar(con, admin, mufa_id=ids["b"], cable_id=c["id"])


def test_a_client_is_taken_off_and_put_back(mundo):
    con, admin, p, ids = mundo
    k = {"codigo_cliente": "C28995", "nombre": "Casa del Café", "id_servicio": "ID1", "hilos": 1}
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"clientes_mufa": [{**k, "baja": True}]})
    assert next(c for c in r["clientes"] if c["codigo_cliente"] == "C28995")["baja"] is True
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"clientes_mufa": [{**k, "baja": False}]})
    assert next(c for c in r["clientes"] if c["codigo_cliente"] == "C28995")["baja"] is False
