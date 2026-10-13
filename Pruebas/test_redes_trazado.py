"""Network design module, phase 5: tracing a fibre end to end (fusions, splitters, connectors,
clients, missing continuity, fibre states, permissions)."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, mufa, proyectos, red, trazado, usuarios


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def red_trazada(con_redes):
    """Nodo Central -(Troncal 48)-> MF Norte -(Distribución 24)-> FAT 1 -(Acometida 12)-> Casa Pérez.

    MF Norte: Troncal 2 -> Splitter 1 (1x8) entrada; salida 1 -> Distribución 1, salida 2 -> Distribución 2;
              Troncal 5 fused with Distribución 5.
    FAT 1:    Distribución 1 -> Conector A (entrada); Conector A (salida) -> Acometida 1.
              Distribución 2 and 5 are not connected there (no continuity).
    """
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Los Robles", "codigo": "RLR"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "n", "tipo": "nodo", "nombre": "Nodo Central", "lat": 12.0950, "lon": -86.3000},
                      {"id": "m1", "tipo": "mufa", "nombre": "MF Norte", "lat": 12.1000, "lon": -86.3000},
                      {"id": "m2", "tipo": "mufa", "subtipo": "terminal", "nombre": "FAT 1", "lat": 12.1020, "lon": -86.3000},
                      {"id": "c1", "tipo": "cliente", "nombre": "Casa Pérez", "codigo": "C12345", "lat": 12.1021, "lon": -86.2995,
                       "propiedades": {"id_servicio": "ID418400"}}],
        "cables": [{"id": "k0", "nombre": "Troncal", "clase": "troncal", "hilos": 48, "hilos_por_buffer": 12, "origen_id": "n",
                    "destino_id": "m1", "vertices": [_v(12.0950, -86.3000), _v(12.1000, -86.3000)]},
                   {"id": "k1", "nombre": "Distribución", "hilos": 24, "hilos_por_buffer": 8, "origen_id": "m1", "destino_id": "m2",
                    "vertices": [_v(12.1000, -86.3000), _v(12.1020, -86.3000)]},
                   {"id": "k2", "nombre": "Acometida", "clase": "acometida", "tipo": "FLAT", "hilos": 12, "origen_id": "m2",
                    "destino_id": "c1", "vertices": [_v(12.1020, -86.3000), _v(12.1021, -86.2995)]}]})
    ids = r["ids"]
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    h = lambda vista, cable, n: next(f for c in vista["cables"] if c["nombre"] == cable for f in c["fibras"] if f["numero"] == n)
    mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "splitters": [{"id": "s", "nombre": "Splitter 1", "salidas": 8}],
        "conexiones": [{"id": "a", "a": {"hilo": h(norte, "Troncal", 2)["id"]}, "b": {"splitter": "s", "lado": "entrada"}},
                       {"id": "b", "a": {"splitter": "s", "lado": "salida", "numero": 1}, "b": {"hilo": h(norte, "Distribución", 1)["id"]}},
                       {"id": "c", "a": {"splitter": "s", "lado": "salida", "numero": 2}, "b": {"hilo": h(norte, "Distribución", 2)["id"]}},
                       {"id": "d", "a": {"hilo": h(norte, "Troncal", 5)["id"]}, "b": {"hilo": h(norte, "Distribución", 5)["id"]}}],
        "hilos": [{**h(norte, "Distribución", 2), "estado": "danado"}]})
    fat = mufa.leer(con, admin, mufa_id=ids["m2"])
    mufa.guardar(con, admin, mufa_id=ids["m2"], cambios={
        "conectores": [{"id": "k", "nombre": "Conector A", "tipo": "SC/APC"}],
        "conexiones": [{"id": "a", "a": {"hilo": h(fat, "Distribución", 1)["id"]}, "b": {"conector": "k", "lado": "entrada"}},
                       {"id": "b", "a": {"conector": "k", "lado": "salida"}, "b": {"hilo": h(fat, "Acometida", 1)["id"]}}]})
    return con, admin, p, ids


def _sentido(t, nombre):
    return next(s for s in t["sentidos"] if s["nombre"] == nombre)


def test_trunk_fibre_reaches_the_client(red_trazada):
    """Acceptance case of the phase: from a trunk fibre I see which client it reaches."""
    con, admin, _, ids = red_trazada
    t = trazado.trazar(con, admin, cable_id=ids["k0"], numero=2)
    assert t["inicio"]["hilo"]["numero"] == 2 and t["inicio"]["hilo"]["color"] == "naranja"
    origen = _sentido(t, "Hacia el origen")["caminos"]
    assert len(origen) == 1 and origen[0]["fin"]["motivo"] == "nodo" and origen[0]["pasos"] == []
    destino = _sentido(t, "Hacia el destino")["caminos"]
    fines = sorted((c["fin"]["motivo"], c["fin"]["texto"]) for c in destino)
    assert fines == [("cliente", "Cliente Casa Pérez (C12345) · ID ID418400"),
                     ("sin_conexion", "Sin continuidad: el hilo 2 no está conectado en FAT 1")]
    al_cliente = next(c for c in destino if c["fin"]["motivo"] == "cliente")
    assert [p["tipo"] for p in al_cliente["pasos"]] == ["splitter", "tramo", "conector", "tramo"]
    assert al_cliente["pasos"][0]["texto"] == "Splitter 1 (1x8) en MF Norte: entrada → salida 1"
    assert [p["cable"]["nombre"] for p in al_cliente["pasos"] if p["tipo"] == "tramo"] == ["Distribución", "Acometida"]
    assert al_cliente["distancia_m"] == round(sum(p["longitud_m"] for p in al_cliente["pasos"] if p["tipo"] == "tramo"), 1)
    assert al_cliente["distancia_m"] > 0
    # the damaged fibre on the other branch is reported
    rota = next(c for c in destino if c["fin"]["motivo"] == "sin_conexion")
    assert rota["avisos"] == ["Distribución hilo 2: dañado"]
    assert [c["nombre"] for c in t["resumen"]["clientes"]] == ["Casa Pérez"]
    assert t["resumen"]["sin_continuidad"] == 1 and t["resumen"]["caminos"] == 3
    assert set(t["cables"]) == {ids["k0"], ids["k1"], ids["k2"]} and len(t["conexiones"]) == 5
    assert {e["nombre"] for e in t["elementos"]} == {"Nodo Central", "MF Norte", "FAT 1", "Casa Pérez"}
    assert all(e["lat"] is not None for e in t["elementos"])


def test_from_the_client_back_to_the_node(red_trazada):
    con, admin, _, ids = red_trazada
    t = trazado.trazar(con, admin, cable_id=ids["k2"], numero=1)
    arriba = _sentido(t, "Hacia el origen")["caminos"]
    assert len(arriba) == 1 and arriba[0]["fin"]["texto"] == "Llega al nodo Nodo Central"
    textos = [p.get("texto") or f"{p['cable']['nombre']} {p['hilo']['numero']}" for p in arriba[0]["pasos"]]
    assert textos == ["Conector A SC/APC en FAT 1", "Distribución 1", "Splitter 1 (1x8) en MF Norte: salida 1 → entrada", "Troncal 2"]
    abajo = _sentido(t, "Hacia el destino")["caminos"]
    assert [c["fin"]["motivo"] for c in abajo] == ["cliente"] and abajo[0]["pasos"] == []


def test_fusion_and_missing_continuity(red_trazada):
    con, admin, _, ids = red_trazada
    t = trazado.trazar(con, admin, cable_id=ids["k0"], numero=5)
    destino = _sentido(t, "Hacia el destino")["caminos"]
    assert len(destino) == 1
    assert destino[0]["pasos"][0]["texto"] == "Fusión en MF Norte con Distribución hilo 5"
    assert destino[0]["fin"]["motivo"] == "sin_conexion" and destino[0]["fin"]["elemento"]["nombre"] == "FAT 1"
    libre = trazado.trazar(con, admin, cable_id=ids["k0"], numero=7)
    assert [c["fin"]["texto"] for c in _sentido(libre, "Hacia el destino")["caminos"]] == [
        "Sin continuidad: el hilo 7 no está conectado en MF Norte"]


def test_splitter_without_outputs_and_errors(red_trazada):
    con, admin, p, ids = red_trazada
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    t9 = next(f for c in norte["cables"] if c["nombre"] == "Troncal" for f in c["fibras"] if f["numero"] == 9)
    mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "splitters": [{"id": "s", "nombre": "Splitter 2", "salidas": 4}],
        "conexiones": [{"id": "x", "a": {"hilo": t9["id"]}, "b": {"splitter": "s", "lado": "entrada"}}]})
    t = trazado.trazar(con, admin, hilo_id=t9["id"])
    assert [c["fin"]["texto"] for c in _sentido(t, "Hacia el destino")["caminos"]] == [
        "Splitter 2 (1x4) en MF Norte: ninguna salida conectada"]
    with pytest.raises(db.NoEncontrado):
        trazado.trazar(con, admin, cable_id=ids["k2"], numero=13)                 # the drop has 12 fibres
    otro = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    otro = con.execute("SELECT * FROM redes.usuarios WHERE id = %s", (otro["id"],)).fetchone()
    with pytest.raises(db.SinPermiso):
        trazado.trazar(con, otro, hilo_id=t9["id"])                             # not assigned to the project


def test_service_method(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS
    assert METODOS["trazar_hilo"] is trazado.trazar
