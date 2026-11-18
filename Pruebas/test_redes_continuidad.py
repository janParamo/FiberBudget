"""Mufa en continuidad (visor_rutas/redes/continuidad.py): los hilos escritos (1-12, 15, 20-24) pasan de un cable al otro con el mismo número; el resto no se conecta."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import _hilo, mundo  # noqa: F401  (fixture)
from visor_rutas.redes import continuidad, mufa
from visor_rutas.redes.db import DatosInvalidos


def _cables(con, admin, mid):
    return {c["nombre"]: c["id"] for c in mufa.leer(con, admin, mufa_id=mid)["cables"]}


def _numeros(vista):
    ids = {f["id"]: (c["nombre"], f["numero"]) for c in vista["cables"] for f in c["fibras"]}
    return sorted((ids[x["a"]["hilo"]][1], ids[x["b"]["hilo"]][1]) for x in vista["conexiones"] if x["a"].get("hilo") and x["b"].get("hilo"))


def test_the_ranges_are_read_and_written_back():
    assert continuidad.leer_hilos("1-12, 15, 20-22", 24) == list(range(1, 13)) + [15, 20, 21, 22]
    assert continuidad.leer_hilos("todos", 12) == list(range(1, 13)) and continuidad.leer_hilos("", 12) == []
    assert continuidad.leer_hilos("3 5;5 1-2", 24) == [1, 2, 3, 5]
    assert continuidad.texto_hilos([1, 2, 3, 4, 15, 20, 21]) == "1-4, 15, 20-21"
    for malo in ("a-b", "12-1", "0-3", "1-"):
        with pytest.raises(DatosInvalidos):
            continuidad.leer_hilos(malo, 24)


def test_only_the_written_fibres_go_in_continuity_with_the_same_number(mundo):
    """MF Dos (the cut mufa) has Distribución (24) arriving and Otro (12) leaving: 1-4 and 8 are in continuity, the rest are not connected."""
    con, admin, p, ids = mundo
    c = _cables(con, admin, ids["b"])
    r = continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Distribución"], cable_b=c["Otro"], hilos="1-4, 8")
    assert r["continuidad"] == {"hilos": [1, 2, 3, 4, 8], "saltados": [], "texto": "1-4, 8"}
    assert _numeros(r) == [(1, 1), (2, 2), (3, 3), (4, 4), (8, 8)]                           # the same number on both cables; nothing else
    assert r["mufa"]["propiedades"]["continuidad"]["hilos"] == "1-4, 8"                        # it stays in the mufa
    # applying another list replaces what the last one made
    r = continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Distribución"], cable_b=c["Otro"], hilos="5-6")
    assert _numeros(r) == [(5, 5), (6, 6)]
    # taken off
    r = continuidad.aplicar(con, admin, mufa_id=ids["b"], quitar=True)
    assert _numeros(r) == [] and "continuidad" not in r["mufa"]["propiedades"]


def test_fibres_already_connected_are_respected_and_a_fibre_the_cables_do_not_have_is_refused(mundo):
    con, admin, p, ids = mundo
    c = _cables(con, admin, ids["b"])
    d2, o9 = _hilo(con, admin, ids["b"], "Distribución", 2), _hilo(con, admin, ids["b"], "Otro", 9)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": d2["id"]}, "b": {"hilo": o9["id"]}}]})     # by hand: 2 with 9
    r = continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Distribución"], cable_b=c["Otro"], hilos="1-3, 9")
    assert r["continuidad"]["hilos"] == [1, 3] and r["continuidad"]["saltados"] == [2, 9]    # 2 and 9 keep what they had (no second end: it would be a tap)
    assert (2, 9) in _numeros(r) and not any(x["sangria"] for x in r["conexiones"])
    with pytest.raises(DatosInvalidos):
        continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Distribución"], cable_b=c["Otro"], hilos="1-24")   # Otro only has 12
    with pytest.raises(DatosInvalidos):
        continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Otro"], cable_b=c["Otro"], hilos="1")
    with pytest.raises(DatosInvalidos):
        continuidad.aplicar(con, admin, mufa_id=ids["b"], cable_a=c["Distribución"], cable_b=c["Otro"], hilos="")


def test_a_note_keeps_the_colour_of_its_box_and_of_its_text(mundo):
    con, admin, p, ids = mundo
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"notas": [{"id": "n1", "html": "<p>SPL SECUNDARIO</p>", "x": 10, "y": 20, "color_fondo": "#1F2937", "color_texto": "#FFE600"}]})
    n = r["notas"][0]
    assert (n["color_fondo"], n["color_texto"]) == ("#1f2937", "#ffe600")
    # back to the default colours (empty), and a wrong colour is refused
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"notas": [{"id": n["id"], "version": n["version"], "html": "<p>SPL SECUNDARIO</p>", "x": 10, "y": 20, "color_fondo": "", "color_texto": None}]})
    assert (r["notas"][0]["color_fondo"], r["notas"][0]["color_texto"]) == (None, None)
    with pytest.raises(DatosInvalidos):
        mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"notas": [{"id": "n2", "html": "<p>x</p>", "color_fondo": "rojo"}]})
