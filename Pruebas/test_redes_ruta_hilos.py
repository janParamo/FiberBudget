"""Ruta de fusión de un cliente según los diagramas (visor_rutas/redes/ruta_hilos.py): del H1 del cliente, mufa por mufa, hasta el splitter."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import _hilo, mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa, ruta_hilos
from visor_rutas.redes.db import NoEncontrado


def test_the_route_follows_the_fusions_from_the_client_up_to_the_splitter(mundo):
    """MF Uno: client on Distribución H3 → MF Dos: H3 fused with Otro H5 → MF Otra: Otro H5 on output 3 of a 1x8 splitter."""
    con, admin, p, ids = mundo
    d3, o5 = _hilo(con, admin, ids["a"], "Distribución", 3), _hilo(con, admin, ids["b"], "Otro", 5)
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": d3["id"], "codigo_cliente": "C28995", "nombre": "Casa del Café"}]})
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": d3["id"]}, "b": {"hilo": o5["id"]}}]})
    sid = mufa.guardar(con, admin, mufa_id=ids["c"], cambios={"splitters": [{"id": "s", "nombre": "SPL 1/8", "salidas": 8}]})["ids"]["s"]
    mufa.guardar(con, admin, mufa_id=ids["c"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": o5["id"]}, "b": {"splitter": sid, "lado": "salida", "numero": 3}}]})

    r = ruta_hilos.ruta_cliente(con, admin, mufa_id=ids["a"], hilo_id=d3["id"])
    assert r["fin"] == "splitter" and r["avisos"] == []
    lineas = r["plan"]["lineas"]
    assert len(lineas) == 3
    assert lineas[0].startswith("En MF Uno ") and lineas[0].endswith("ingresar la acometida del cliente. H1 del cliente fusionarlo con H3 hacia MF Dos")
    assert lineas[1].startswith("En MF Dos ") and lineas[1].endswith("H3 hacia MF Uno fusionarlo con H5 hacia MF Otra")
    assert lineas[2].startswith("En MF Otra ") and lineas[2].endswith("H5 hacia MF Dos fusionarlo con H3 del SPL 1/8 de MF Otra")
    assert [x["tocar"] for x in r["plan"]["pasos"]] == [True, True, True]


def test_a_client_on_a_splitter_output_is_served_from_that_mufa(mundo):
    con, admin, p, ids = mundo
    sid = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"splitters": [{"id": "s", "nombre": "SPL 1/8", "salidas": 8}]})["ids"]["s"]
    r = ruta_hilos.ruta_cliente(con, admin, mufa_id=ids["a"], splitter_id=sid, numero=6)
    assert len(r["plan"]["lineas"]) == 1 and r["plan"]["lineas"][0].endswith("H1 del cliente fusionarlo con H6 del SPL 1/8 de MF Uno")


def test_a_fibre_that_does_not_continue_says_so_and_a_fibre_of_another_mufa_is_refused(mundo):
    con, admin, p, ids = mundo
    d7 = _hilo(con, admin, ids["a"], "Distribución", 7)
    r = ruta_hilos.ruta_cliente(con, admin, mufa_id=ids["a"], hilo_id=d7["id"])
    assert r["fin"] == "sin_continuidad" and any("Sin continuidad" in a for a in r["avisos"])
    assert r["plan"]["lineas"][0].endswith("H1 del cliente fusionarlo con H7 hacia MF Dos (hilos por identificar)") or "H7" in r["plan"]["lineas"][0]
    o1 = _hilo(con, admin, ids["c"], "Otro", 1)
    with pytest.raises(NoEncontrado):
        ruta_hilos.ruta_cliente(con, admin, mufa_id=ids["a"], hilo_id=o1["id"])             # that fibre is not of a cable of MF Uno
