"""Un cliente identificado en un hilo de manera individual (no solo en la salida de un splitter): visor_rutas/redes/mufa.py (hilo_servicios)."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, mufa, proyectos, red, usuarios


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def mundo(con_redes):
    """MF Uno -(Distribución 24)-> MF Dos, with a client of the map (C12345) in the project."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Jalapa", "codigo": "JAL"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "a", "tipo": "mufa", "nombre": "MF Uno", "lat": 12.1000, "lon": -86.3000},
                      {"id": "b", "tipo": "mufa", "nombre": "MF Dos", "lat": 12.1010, "lon": -86.3000},
                      {"id": "c", "tipo": "mufa", "nombre": "MF Otra", "lat": 12.1020, "lon": -86.3000},
                      {"id": "k", "tipo": "cliente", "nombre": "Casa Pérez", "codigo": "C12345", "lat": 12.1011, "lon": -86.2995}],
        "cables": [{"id": "d", "nombre": "Distribución", "hilos": 24, "origen_id": "a", "destino_id": "b", "vertices": [_v(12.1000, -86.3000), _v(12.1010, -86.3000)]},
                   {"id": "e", "nombre": "Otro", "hilos": 12, "origen_id": "b", "destino_id": "c", "vertices": [_v(12.1010, -86.3000), _v(12.1020, -86.3000)]}]})
    return con, admin, p, r["ids"]


def _hilo(con, admin, mufa_id, cable, numero):
    vista = mufa.leer(con, admin, mufa_id=mufa_id)
    return next(f for c in vista["cables"] if c["nombre"] == cable for f in c["fibras"] if f["numero"] == numero)


def test_a_client_is_set_on_fibre_1_and_changed_and_taken_off(mundo):
    con, admin, p, ids = mundo
    h1 = _hilo(con, admin, ids["a"], "Distribución", 1)
    assert h1["cliente"] is None and _hilo(con, admin, ids["a"], "Distribución", 2)["cliente"] is None
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [
        {"hilo_id": h1["id"], "codigo_cliente": " c12345 ", "nombre": "Casa Pérez", "id_servicio": "ID418400", "elemento_id": ids["k"]}]})
    h1 = next(f for c in r["cables"] if c["nombre"] == "Distribución" for f in c["fibras"] if f["numero"] == 1)
    assert (h1["cliente"]["codigo_cliente"], h1["cliente"]["nombre"], h1["cliente"]["id_servicio"], h1["cliente"]["elemento_id"], h1["cliente"]["fuente"]) == \
        ("C12345", "Casa Pérez", "ID418400", ids["k"], "usuario")                                     # the code in capitals; only that fibre has a client
    assert all(f["cliente"] is None for c in r["cables"] for f in c["fibras"] if f["numero"] != 1)
    # the other end of the cable (MF Dos) sees the same client on the same fibre
    assert _hilo(con, admin, ids["b"], "Distribución", 1)["cliente"]["codigo_cliente"] == "C12345"
    # change it (with its version) and take it off
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "codigo_cliente": "C99999", "nombre": "Otro", "version": h1["cliente"]["version"]}]})
    assert next(f for c in r["cables"] for f in c["fibras"] if f["id"] == h1["id"])["cliente"]["codigo_cliente"] == "C99999"
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "quitar": True}]})
    assert next(f for c in r["cables"] for f in c["fibras"] if f["id"] == h1["id"])["cliente"] is None
    n = con.execute("SELECT count(*) AS n FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", (h1["id"],)).fetchone()["n"]
    assert n == 0
    # it is in the history
    acciones = [f["accion"] for f in con.execute("SELECT accion FROM redes.historial WHERE entidad = 'hilo_servicio' ORDER BY id").fetchall()]
    assert acciones == ["crear", "editar", "eliminar"]


def test_one_client_per_fibre_and_a_wrong_one_is_refused(mundo):
    con, admin, p, ids = mundo
    h1, h2 = _hilo(con, admin, ids["a"], "Distribución", 1), _hilo(con, admin, ids["a"], "Distribución", 2)
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "codigo_cliente": "C1000"}, {"hilo_id": h2["id"], "nombre": "Sin código"}]})
    vista = mufa.leer(con, admin, mufa_id=ids["a"])
    fibras = {f["numero"]: f["cliente"] for c in vista["cables"] for f in c["fibras"]}
    assert fibras[1]["codigo_cliente"] == "C1000" and fibras[2]["nombre"] == "Sin código" and fibras[3] is None      # each fibre its own client
    # setting it again on the same fibre replaces it (never two active): still one row
    mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "codigo_cliente": "C2000", "version": fibras[1]["version"]}]})
    assert con.execute("SELECT count(*) AS n FROM redes.hilo_servicios WHERE hilo_id = %s AND borrado_en IS NULL", (h1["id"],)).fetchone()["n"] == 1
    for malo in ({"hilo_id": h1["id"], "codigo_cliente": "123"}, {"hilo_id": h1["id"], "codigo_cliente": "Cxyz"}, {"hilo_id": h1["id"]},
                 {"hilo_id": h1["id"], "codigo_cliente": "C1", "nombre": "x" * 5},
                 {"hilo_id": h1["id"], "nombre": "X", "elemento_id": ids["b"]},                    # a mufa is not a client
                 {"hilo_id": 999999, "nombre": "X"}):
        with pytest.raises(db.DatosInvalidos):
            mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [malo]})
    # a fibre of a cable that does not touch this mufa is refused: MF Uno cannot set a client on the cable between MF Dos and MF Otra
    ajeno = _hilo(con, admin, ids["c"], "Otro", 1)
    with pytest.raises(db.DatosInvalidos):
        mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": ajeno["id"], "nombre": "X"}]})
    # the version is checked: someone else changed it
    with pytest.raises(db.ConflictoVersion):
        mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "codigo_cliente": "C3000", "version": 1}]})


def test_the_client_of_the_map_may_be_in_another_project_of_the_zone(mundo):
    """The existing network is split by zone: the client of the map linked to a mufa's client is not always in the project of that mufa (the error was «el cliente del mapa
    no es de este proyecto»)."""
    con, admin, p, ids = mundo
    otro = proyectos.guardar(con, admin, datos={"nombre": "Otra zona", "codigo": "OTRA"})["proyecto"]
    cliente = red.guardar(con, admin, proyecto_id=otro["id"], cambios={"elementos": [
        {"id": "k", "tipo": "cliente", "nombre": "BANCO AVANZ", "codigo": "C25898", "lat": 12.2, "lon": -86.2}]})["ids"]["k"]
    h5 = _hilo(con, admin, ids["a"], "Distribución", 5)
    r = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h5["id"], "codigo_cliente": "C25898", "nombre": "BANCO AVANZ", "elemento_id": cliente}]})
    assert next(f for c in r["cables"] for f in c["fibras"] if f["id"] == h5["id"])["cliente"]["elemento_id"] == cliente
    for malo in (ids["a"], 999999):                                                                  # a mufa, or one that does not exist, is not a client
        with pytest.raises(db.DatosInvalidos):
            mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h5["id"], "nombre": "X", "elemento_id": malo, "version": 1}]})


def test_a_reader_cannot_set_a_client_on_a_fibre(mundo):
    con, admin, p, ids = mundo
    ana = usuarios.identificar(con, persona_visor="ana")
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], ana["id"]]})
    h1 = _hilo(con, admin, ids["a"], "Distribución", 1)
    with pytest.raises(db.SinPermiso):
        mufa.guardar(con, ana, mufa_id=ids["a"], cambios={"hilo_clientes": [{"hilo_id": h1["id"], "nombre": "X"}]})
    assert mufa.leer(con, ana, mufa_id=ids["a"])["cables"]                                           # but she sees the mufa
