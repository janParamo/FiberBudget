"""Network design module, phase 4: the mufa editor (fibres, splitters, connectors, connections,
fibre states, notes) and how the map editor keeps fibres and connections consistent."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, mufa, proyectos, red, usuarios


@pytest.fixture
def red_lista(con_redes):
    """MF Norte -(troncal 48)-> FAT 1 -(acometida 12)-> Casa Pérez, plus a 24-fibre cable MF Norte -> MF Sur."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Los Robles", "codigo": "RLR"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "m1", "tipo": "mufa", "nombre": "MF Norte", "lat": 12.1000, "lon": -86.3000},
                      {"id": "m2", "tipo": "mufa", "subtipo": "terminal", "nombre": "FAT 1", "lat": 12.1020, "lon": -86.3000},
                      {"id": "m3", "tipo": "mufa", "nombre": "MF Sur", "lat": 12.0980, "lon": -86.3000},
                      {"id": "c1", "tipo": "cliente", "nombre": "Casa Pérez", "lat": 12.1021, "lon": -86.2995}],
        "cables": [{"id": "k1", "nombre": "Troncal", "clase": "troncal", "hilos": 48, "hilos_por_buffer": 12, "origen_id": "m1",
                    "destino_id": "m2", "vertices": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0}]},
                   {"id": "k2", "nombre": "Acometida", "clase": "acometida", "tipo": "FLAT", "hilos": 12, "origen_id": "m2",
                    "destino_id": "c1", "vertices": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0}]},
                   {"id": "k3", "nombre": "Distribución Sur", "hilos": 24, "hilos_por_buffer": 8, "origen_id": "m1",
                    "destino_id": "m3", "vertices": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0}]}]})
    return con, admin, p, r["ids"]


def _fibra(vista, cable, numero):
    c = next(c for c in vista["cables"] if c["nombre"] == cable)
    return next(f for f in c["fibras"] if f["numero"] == numero)


def test_cables_come_with_their_fibres_and_their_side(red_lista):
    con, admin, _, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    assert {c["nombre"]: (c["lado"], c["otro"]["nombre"], len(c["fibras"])) for c in norte["cables"]} == {
        "Troncal": ("salida", "FAT 1", 48), "Distribución Sur": ("salida", "MF Sur", 24)}
    fat = mufa.leer(con, admin, mufa_id=ids["m2"])
    assert {c["nombre"]: c["lado"] for c in fat["cables"]} == {"Troncal": "entrada", "Acometida": "salida"}
    assert next(c for c in norte["cables"] if c["nombre"] == "Distribución Sur")["hilos_por_buffer"] == 8
    assert norte["mufa"]["puede_editar"] is True and norte["proyecto"]["codigo"] == "RLR"
    with pytest.raises(db.NoEncontrado):
        mufa.leer(con, admin, mufa_id=ids["c1"])                      # a client has no mufa canvas


def test_trunk_fibre_to_a_1x8_splitter_and_an_output_to_another_mufa(red_lista):
    """The phase's acceptance case: hilo 2 of the trunk -> splitter 1x8 at MF Norte; output 1 ->
    hilo 1 of the cable to MF Sur; from MF Sur that fibre shows where it comes from."""
    con, admin, _, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    troncal_2 = _fibra(norte, "Troncal", 2)["id"]
    sur_1 = _fibra(norte, "Distribución Sur", 1)["id"]
    r = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "posiciones": [{"cable_id": ids["k1"], "x": 40, "y": 60}],
        "splitters": [{"id": "s1", "nombre": "Splitter 1", "salidas": 8, "x": 420, "y": 120}],
        "conexiones": [{"id": "x1", "a": {"hilo": troncal_2}, "b": {"splitter": "s1", "lado": "entrada", "numero": 1}},
                       {"id": "x2", "a": {"splitter": "s1", "lado": "salida", "numero": 1}, "b": {"hilo": sur_1}}]})
    sp = r["splitters"][0]
    assert (sp["nombre"], sp["salidas"], sp["puertos"]["entrada"], len(sp["puertos"]["salida"])) == ("Splitter 1", 8, [1], 8)
    assert len(r["conexiones"]) == 2 and {"splitter": r["ids"]["s1"], "lado": "salida", "numero": 1} in [x["a"] for x in r["conexiones"]]
    assert next(c for c in r["cables"] if c["id"] == ids["k1"])[ "x"] == 40
    sur = mufa.leer(con, admin, mufa_id=ids["m3"])                    # navigate to the other end
    assert _fibra(sur, "Distribución Sur", 1)["lejos"] == "Splitter 1 · salida 1"
    fat = mufa.leer(con, admin, mufa_id=ids["m2"])
    assert _fibra(fat, "Troncal", 2)["lejos"] == "Splitter 1 · entrada"
    assert _fibra(fat, "Troncal", 3)["lejos"] is None
    acciones = {(h["entidad"], h["accion"]) for h in proyectos.historial(con, admin, id=r["proyecto"]["id"])["historial"]}
    assert {("splitter", "crear"), ("conexion", "crear")} <= acciones


def test_connection_rules(red_lista):
    con, admin, _, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    t1, t2 = _fibra(norte, "Troncal", 1)["id"], _fibra(norte, "Troncal", 2)["id"]
    s1 = _fibra(norte, "Distribución Sur", 1)["id"]
    acometida = mufa.leer(con, admin, mufa_id=ids["m2"])
    a1 = _fibra(acometida, "Acometida", 1)["id"]
    casos = [
        ([{"id": "x", "a": {"hilo": t1}, "b": {"hilo": t2}}], "cables distintos"),
        ([{"id": "x", "a": {"hilo": t1}, "b": {"hilo": a1}}], "no pertenece a un cable de esta mufa"),
        ([{"id": "x", "a": {"hilo": t1}, "b": {"hilo": s1}}, {"id": "y", "a": {"hilo": t1}, "b": {"hilo": _fibra(norte, "Distribución Sur", 2)["id"]}}],
         "ya está conectado"),
        ([{"id": "x", "a": {"splitter": "nada", "lado": "entrada"}, "b": {"hilo": t1}}], "no viene en el envío"),
    ]
    for conexiones, texto in casos:
        with pytest.raises(db.DatosInvalidos, match=texto):
            mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"conexiones": conexiones})
    with pytest.raises(db.DatosInvalidos, match="solo para 1x2"):
        mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"splitters": [{"id": "s", "nombre": "S", "salidas": 4, "relacion": "70/30"}]})
    r = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "splitters": [{"id": "s", "nombre": "S 70/30", "salidas": 2, "relacion": "70/30"}],
        "conexiones": [{"id": "x", "a": {"splitter": "s", "lado": "salida", "numero": 2}, "b": {"hilo": s1}}]})
    sp = r["splitters"][0]
    with pytest.raises(db.DatosInvalidos, match="ya está conectado"):
        mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"conexiones": [{"id": "y", "a": {"splitter": sp["id"], "lado": "salida", "numero": 2},
                                                                              "b": {"hilo": t1}}]})
    assert mufa.leer(con, admin, mufa_id=ids["m1"])["conexiones"] and len(r["conexiones"]) == 1


def test_splitter_resize_delete_states_versions_and_notes(red_lista):
    con, admin, _, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    sur_5 = _fibra(norte, "Distribución Sur", 5)["id"]
    r = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "splitters": [{"id": "s", "nombre": "Splitter 1", "salidas": 8}],
        "conexiones": [{"id": "x", "a": {"splitter": "s", "lado": "salida", "numero": 6}, "b": {"hilo": sur_5}}],
        "notas": [{"id": "n", "html": "<p><b>Revisar</b> bandeja 2</p>", "x": 300, "y": 40}]})
    sp = r["splitters"][0]
    with pytest.raises(db.DatosInvalidos, match="salidas 6"):
        mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"splitters": [{**sp, "salidas": 4}]})
    hilo = _fibra(r, "Troncal", 7)
    r2 = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"hilos": [{**hilo, "estado": "oscura", "observacion": "reserva"}]})
    assert (_fibra(r2, "Troncal", 7)["estado"], _fibra(r2, "Troncal", 7)["observacion"]) == ("oscura", "reserva")
    with pytest.raises(db.ConflictoVersion, match="Hilo 7"):
        mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"hilos": [{**hilo, "estado": "baja"}]})   # old version
    assert r2["notas"][0]["html"] == "<p><b>Revisar</b> bandeja 2</p>"
    r3 = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"splitters": [{**sp, "eliminar": True}]})
    assert r3["splitters"] == [] and r3["conexiones"] == []                       # its connections went with it
    assert con.execute("SELECT count(*) AS n FROM redes.conexiones WHERE borrado_en IS NOT NULL").fetchone()["n"] == 1


def test_map_editor_keeps_fibres_and_connections_consistent(red_lista):
    con, admin, p, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "conexiones": [{"id": "x", "a": {"hilo": _fibra(norte, "Troncal", 40)["id"]}, "b": {"hilo": _fibra(norte, "Distribución Sur", 3)["id"]}}]})
    mapa = red.red(con, admin, proyecto_id=p["id"])
    troncal = next(c for c in mapa["cables"] if c["nombre"] == "Troncal")
    with pytest.raises(db.DatosInvalidos, match="hilos 40"):                    # 48 -> 24 while fibre 40 is fused
        red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**troncal, "hilos": 24}]})
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**troncal, "hilos": 72}]})
    assert len(_cable(mufa.leer(con, admin, mufa_id=ids["m1"]), "Troncal")["fibras"]) == 72
    troncal = next(c for c in r["cables"] if c["nombre"] == "Troncal")
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**troncal, "eliminar": True}]})
    assert mufa.leer(con, admin, mufa_id=ids["m1"])["conexiones"] == []           # the fusion went with the cable


def _cable(vista, nombre):
    return next(c for c in vista["cables"] if c["nombre"] == nombre)


def test_duplicate_copies_the_mufa_canvas_and_readers_cannot_edit(red_lista):
    con, admin, p, ids = red_lista
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={
        "posiciones": [{"cable_id": ids["k1"], "x": 10, "y": 20}],
        "splitters": [{"id": "s", "nombre": "Splitter 1", "salidas": 4}],
        "conexiones": [{"id": "x", "a": {"hilo": _fibra(norte, "Troncal", 1)["id"]}, "b": {"splitter": "s", "lado": "entrada"}}],
        "hilos": [{**_fibra(norte, "Troncal", 9), "estado": "danado"}]})
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    mufa_copia = next(e for e in red.red(con, admin, proyecto_id=copia["id"])["elementos"] if e["nombre"] == "MF Norte")
    v = mufa.leer(con, admin, mufa_id=mufa_copia["id"])
    assert [s["nombre"] for s in v["splitters"]] == ["Splitter 1"] and len(v["conexiones"]) == 1
    assert _fibra(v, "Troncal", 9)["estado"] == "danado" and _cable(v, "Troncal")["x"] == 10
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    lector = con.execute("SELECT * FROM redes.usuarios WHERE id = %s", (lector["id"],)).fetchone()
    proyectos.guardar(con, admin, datos={**proyectos.obtener(con, admin, id=p["id"])["proyecto"], "usuarios": [admin["id"], lector["id"]]})
    assert mufa.leer(con, lector, mufa_id=ids["m1"])["mufa"]["puede_editar"] is False
    with pytest.raises(db.SinPermiso):
        mufa.guardar(con, lector, mufa_id=ids["m1"], cambios={})


def test_service_methods(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS
    assert {"mufa", "guardar_mufa"} <= set(METODOS)
