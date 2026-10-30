"""Sangría (mufa.py): una fusión hilo con hilo que además alimenta a un cliente de esa mufa; se marca a mano o sola, y se dibuja en rojo."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import db, mufa


def _hilo(con, admin, mufa_id, cable, numero):
    vista = mufa.leer(con, admin, mufa_id=mufa_id)
    return next(f for c in vista["cables"] if c["nombre"] == cable for f in c["fibras"] if f["numero"] == numero)


def _fusion(vista, hilo_id):
    return next(x for x in vista["conexiones"] if hilo_id in (x["a"].get("hilo"), x["b"].get("hilo")))


def _unir(con, admin, ids, numero, **extra):
    a, b = _hilo(con, admin, ids["b"], "Distribución", numero), _hilo(con, admin, ids["b"], "Otro", numero)
    return mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": a["id"]}, "b": {"hilo": b["id"]}, **extra}]}), a


def test_a_fusion_is_marked_and_unmarked_as_a_tap(mundo):
    con, admin, p, ids = mundo
    r, a = _unir(con, admin, ids, 11)
    x = _fusion(r, a["id"])
    assert x["sangria"] is False                                          # a plain continuity
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": x["id"], "version": x["version"], "sangria": True}]})
    x = _fusion(r, a["id"])
    assert x["sangria"] is True
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": x["id"], "version": x["version"], "sangria": False}]})
    assert _fusion(r, a["id"])["sangria"] is False
    with pytest.raises(db.ConflictoVersion):                              # a stale version is refused like any other edit
        mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": x["id"], "version": 1, "sangria": True}]})


def test_it_can_be_born_marked(mundo):
    con, admin, p, ids = mundo
    r, a = _unir(con, admin, ids, 11, sangria=True)
    assert _fusion(r, a["id"])["sangria"] is True
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "S1", "salidas": 8}]})
    s = mufa.leer(con, admin, mufa_id=ids["b"])["splitters"][0]
    h12 = _hilo(con, admin, ids["b"], "Distribución", 12)
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": h12["id"]}, "b": {"splitter": s["id"], "lado": "entrada"}, "sangria": True}]})
    assert _fusion(r, h12["id"])["sangria"] is True                       # a fibre that goes to a splitter port can be a tap too


def test_the_fusion_is_a_tap_by_itself_when_the_fibre_feeds_a_client_of_this_mufa(mundo):
    con, admin, p, ids = mundo
    con.execute("INSERT INTO redes.mufa_clientes (mufa_id, codigo_cliente, nombre) VALUES (%s, 'C12345', 'Casa Pérez')", (ids["b"],))
    h11 = _hilo(con, admin, ids["b"], "Distribución", 11)
    r, _ = _unir(con, admin, ids, 11)                                     # first the continuity…
    x = _fusion(r, h11["id"])
    assert x["sangria"] is False
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"hilo_clientes": [{"hilo_id": h11["id"], "codigo_cliente": "C12345", "nombre": "Casa Pérez"}]})
    assert _fusion(r, h11["id"])["sangria"] is True                       # …then the client: that fusion is now the tap
    # born after the client: marked at once
    h12 = _hilo(con, admin, ids["b"], "Distribución", 12)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"hilo_clientes": [{"hilo_id": h12["id"], "codigo_cliente": "C12345"}]})
    a, b = h12, _hilo(con, admin, ids["b"], "Otro", 12)
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n9", "a": {"hilo": a["id"]}, "b": {"hilo": b["id"]}}]})
    assert _fusion(r, a["id"])["sangria"] is True


def test_a_client_that_is_not_of_this_mufa_does_not_mark_a_tap(mundo):
    con, admin, p, ids = mundo
    h5 = _hilo(con, admin, ids["b"], "Distribución", 5)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"hilo_clientes": [{"hilo_id": h5["id"], "codigo_cliente": "C55555", "nombre": "De otra mufa"}]})
    r, _ = _unir(con, admin, ids, 5)
    assert _fusion(r, h5["id"])["sangria"] is False


def test_a_fibre_takes_more_ends_and_all_its_connections_become_a_tap(mundo):
    """mf2 H11: the fibre of the cable that arrives goes to the fibre that continues AND to a splitter: two ends of the same fibre."""
    con, admin, p, ids = mundo
    r, a = _unir(con, admin, ids, 11)
    x = _fusion(r, a["id"])
    assert x["sangria"] is False
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "S1", "salidas": 8}]})
    s = mufa.leer(con, admin, mufa_id=ids["b"])["splitters"][0]
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": a["id"]}, "b": {"splitter": s["id"], "lado": "entrada"}}]})
    de_a = [c for c in r["conexiones"] if a["id"] in (c["a"].get("hilo"), c["b"].get("hilo"))]
    assert len(de_a) == 2 and all(c["sangria"] for c in de_a)             # both ends are marked, the first one too
    # the other cable's fibre could not be taken a second time by the same pair
    b = _hilo(con, admin, ids["b"], "Otro", 11)
    with pytest.raises(db.DatosInvalidos):
        mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n3", "a": {"hilo": a["id"]}, "b": {"hilo": b["id"]}}]})
    # a third end: another cable's fibre
    otro = _hilo(con, admin, ids["b"], "Otro", 12)
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n4", "a": {"hilo": a["id"]}, "b": {"hilo": otro["id"]}}]})
    assert len([c for c in r["conexiones"] if a["id"] in (c["a"].get("hilo"), c["b"].get("hilo"))]) == 3
    # taking ends off: with one left, it is a plain continuity again
    for c in [c for c in r["conexiones"] if a["id"] in (c["a"].get("hilo"), c["b"].get("hilo")) and c["id"] != x["id"]]:
        r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": c["id"], "version": c["version"], "eliminar": True}]})
    resto = _fusion(r, a["id"])
    assert resto["id"] == x["id"] and resto["sangria"] is False


def test_the_trace_follows_every_end_of_a_tapped_fibre(mundo):
    from visor_rutas.redes import trazado
    con, admin, p, ids = mundo
    r, a = _unir(con, admin, ids, 11)
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "S1", "salidas": 4}]})
    s = mufa.leer(con, admin, mufa_id=ids["b"])["splitters"][0]
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": a["id"]}, "b": {"splitter": s["id"], "lado": "entrada"}}]})
    t = trazado.trazar(con, admin, hilo_id=a["id"])
    hacia_dos = next(x for x in t["sentidos"] if x["nombre"] == "Hacia el destino")["caminos"]
    assert len(hacia_dos) >= 2                                            # one path goes on along the other cable, another into the splitter
    assert any(any(pa["tipo"] == "fusion" for pa in c["pasos"]) for c in hacia_dos)
