"""Visio → interactive mufas migration, phase 5 (docs/migracion_visio/PLAN.md): the existing network is
interactive — Enter on any mufa of the map finds its migrated mufa (KMZ point, Visio name near the
click, or the nearest), "Marcar como validada", the cable configuration selector, the "Red de mufas"
view, and what a person edits in a migrated mufa marked as hers."""
import pytest
from psycopg.types.json import Jsonb

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, mufa, mufas_existentes, proyectos, red, usuarios


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def red_base(con_redes):
    """Base project: MF Peñón (KMZ point 77) -(C1 24, 6x4)-> MF Centro -(C2 12)-> MF Final; a splice C1 H1 - C2 H1 in Centro."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Prueba", "codigo": "RE-P"})["proyecto"]
    con.execute("UPDATE redes.proyectos SET es_red_base = true WHERE id = %s", (p["id"],))
    ids = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "a", "tipo": "mufa", "nombre": "MF Peñón", "lat": 12.100, "lon": -86.300},
                      {"id": "b", "tipo": "mufa", "nombre": "MF Centro", "lat": 12.110, "lon": -86.300},
                      {"id": "c", "tipo": "mufa", "nombre": "MF Final", "lat": 12.120, "lon": -86.300}],
        "cables": [{"id": "c1", "nombre": "C1", "hilos": 24, "hilos_por_buffer": 4, "origen_id": "a", "destino_id": "b",
                    "vertices": [_v(12.100, -86.300), _v(12.110, -86.300)]},
                   {"id": "c2", "nombre": "C2", "hilos": 12, "origen_id": "b", "destino_id": "c",
                    "vertices": [_v(12.110, -86.300), _v(12.120, -86.300)]}]})["ids"]
    for k, nombre_visio in (("a", "MF PEÑON"), ("b", "MF CENTRO"), ("c", "MF FINAL")):
        con.execute("UPDATE redes.elementos SET estado_migracion = 'automatica', fuente = 'texto_diagrama', confianza = 'media', "
                    "ref_visio = %s WHERE id = %s", (Jsonb({"clave": nombre_visio, "nombre_visio": nombre_visio}), ids[k]))
    con.execute("UPDATE redes.elementos SET ref_externa = %s WHERE id = %s", (Jsonb({"kmz": {"kmz_punto_id": 77}}), ids["a"]))
    hilo = lambda c, n: con.execute("SELECT id FROM redes.hilos WHERE cable_id = %s AND numero = %s", (ids[c], n)).fetchone()["id"]
    con.execute("INSERT INTO redes.conexiones (proyecto_id, mufa_id, a_hilo_id, b_hilo_id, fuente, confianza) VALUES (%s, %s, %s, %s, 'excel_anillos', 'alta')",
                (p["id"], ids["b"], hilo("c1", 1), hilo("c2", 1)))
    return con, admin, p, ids, hilo


def test_find_the_migrated_mufa_from_the_map(red_base):
    con, admin, p, ids, _ = red_base
    buscar = lambda **k: (mufas_existentes.buscar(con, admin, **k)["mufa"] or {}).get("id")
    assert buscar(kmz_punto_id=77) == ids["a"]
    assert buscar(nombre="Mf. Peñon", lat=12.1003, lon=-86.3002) == ids["a"]          # accents and dots do not matter
    assert buscar(nombre="MF CENTRO") == ids["b"]                                        # name alone, unique
    assert buscar(nombre="MF CENTRO", lat=12.20, lon=-86.30) is None                     # same name, but far from the click
    assert buscar(nombre="OTRA", lat=12.11005, lon=-86.30005) == ids["b"]                # no name: the nearest within 30 m
    assert buscar(nombre="OTRA", lat=12.115, lon=-86.300) is None
    # a project that is not a base one and not assigned is not searched for a reader
    con.execute("UPDATE redes.proyectos SET es_red_base = false WHERE id = %s", (p["id"],))
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    assert mufas_existentes.buscar(con, lector, kmz_punto_id=77)["mufa"] is None


def test_validate_and_unvalidate(red_base):
    con, admin, p, ids, _ = red_base
    vista = mufas_existentes.validar(con, admin, mufa_id=ids["b"])
    assert (vista["mufa"]["estado_migracion"], vista["mufa"]["confianza"]) == ("validada", "verificada")
    assert {c["confianza"] for c in vista["conexiones"]} == {"verificada"}
    vista = mufas_existentes.validar(con, admin, mufa_id=ids["b"], validada=False)
    assert vista["mufa"]["estado_migracion"] == "editada"
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(db.SinPermiso):
        mufas_existentes.validar(con, lector, mufa_id=ids["b"])


def test_cable_configuration_keeps_connections_by_number(red_base):
    con, admin, p, ids, hilo = red_base
    c1 = con.execute("SELECT * FROM redes.cables WHERE id = %s", (ids["c1"],)).fetchone()
    h1 = hilo("c1", 1)
    vista = mufas_existentes.configurar_cable(con, admin, cable_id=ids["c1"], mufa_id=ids["b"], hilos=24, hilos_por_buffer=2, version=c1["version"])
    c = next(x for x in vista["cables"] if x["id"] == ids["c1"])
    assert c["hilos_por_buffer"] == 2 and next(f for f in c["fibras"] if f["numero"] == 3)["buffer"] == 2      # 12x2: fibre 3 in buffer 2
    assert hilo("c1", 1) == h1 and any(x["a"].get("hilo") == h1 or x["b"].get("hilo") == h1 for x in vista["conexiones"])
    assert con.execute("SELECT configuracion, configuracion_estimada FROM redes.cables WHERE id = %s", (ids["c1"],)).fetchone() == {
        "configuracion": "12x2", "configuracion_estimada": False}
    with pytest.raises(db.ConflictoVersion):
        mufas_existentes.configurar_cable(con, admin, cable_id=ids["c1"], mufa_id=ids["b"], hilos=24, hilos_por_buffer=4, version=c1["version"])
    # an unknown count is set from the editor (fibres created), and cannot go back to unknown
    con.execute("UPDATE redes.hilos SET borrado_en = now() WHERE cable_id = %s AND id NOT IN "
                "(SELECT a_hilo_id FROM redes.conexiones UNION SELECT b_hilo_id FROM redes.conexiones)", (ids["c2"],))
    con.execute("DELETE FROM redes.conexiones")
    con.execute("UPDATE redes.hilos SET borrado_en = now() WHERE cable_id = %s", (ids["c2"],))
    con.execute("UPDATE redes.cables SET hilos = NULL WHERE id = %s", (ids["c2"],))
    v = con.execute("SELECT version FROM redes.cables WHERE id = %s", (ids["c2"],)).fetchone()["version"]
    mufas_existentes.configurar_cable(con, admin, cable_id=ids["c2"], mufa_id=ids["b"], hilos=12, hilos_por_buffer=12, version=v)
    assert con.execute("SELECT count(*) AS n FROM redes.hilos WHERE cable_id = %s AND borrado_en IS NULL", (ids["c2"],)).fetchone()["n"] == 12
    with pytest.raises(db.DatosInvalidos, match="desconocido"):
        mufas_existentes.configurar_cable(con, admin, cable_id=ids["c2"], mufa_id=ids["b"], hilos=None, hilos_por_buffer=12, version=v + 1)


def test_network_of_mufas(red_base):
    con, admin, p, ids, _ = red_base
    r = mufas_existentes.red_de_mufas(con, admin, mufa_id=ids["a"], saltos=1)
    assert {n["id"] for n in r["nodos"]} == {ids["a"], ids["b"]} and len(r["cables"]) == 1
    r = mufas_existentes.red_de_mufas(con, admin, mufa_id=ids["a"], saltos=2)
    assert {n["id"]: n["nivel"] for n in r["nodos"]} == {ids["a"]: 0, ids["b"]: 1, ids["c"]: 2} and len(r["cables"]) == 2


def test_editing_a_migrated_mufa_marks_it_and_its_splices(red_base):
    con, admin, p, ids, hilo = red_base
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n1", "a": {"hilo": hilo("c1", 2)}, "b": {"hilo": hilo("c2", 2)}}]})
    nueva = next(x for x in r["conexiones"] if x["id"] == r["ids"]["n1"])
    assert (nueva["fuente"], nueva["confianza"]) == ("usuario", "verificada")
    assert r["mufa"]["estado_migracion"] == "editada" and r["mufa"]["nombre_visio"] == "MF CENTRO"
    vista = mufas_existentes.validar(con, admin, mufa_id=ids["b"])
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n2", "a": {"hilo": hilo("c1", 3)}, "b": {"hilo": hilo("c2", 3)}}]})
    assert r["mufa"]["estado_migracion"] == "validada"                                   # editing after validating keeps it validated


def test_map_search_box_finds_new_elements_and_clients_but_not_migrated_mufas(red_base):
    """Visor v2: the search box also looks in the network base. A mufa migrated from the Visio is found by the Visio
    search, so here only what was created in the tool and the clients; by name or code, accents ignored, every word."""
    con, admin, p, ids, _ = red_base
    nueva = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [
        {"id": "n", "tipo": "mufa", "nombre": "MF Ñandú Nueva", "lat": 12.13, "lon": -86.3},
        {"id": "k", "tipo": "cliente", "nombre": "Casa Pérez", "codigo": "C99001", "lat": 12.131, "lon": -86.301}]})["ids"]
    buscar = lambda texto, **k: mufas_existentes.buscar_elementos(con, admin, texto=texto, **k)["elementos"]
    assert [e["id"] for e in buscar("nandu")] == [nueva["n"]]                         # accents and case do not matter
    assert [e["id"] for e in buscar("mf nueva nandu")] == [nueva["n"]]                # every word, any order
    assert [e["id"] for e in buscar("c99001")] == [nueva["k"]]                        # a client by its code
    assert [e["id"] for e in buscar("perez")] == [nueva["k"]]
    assert buscar("centro") == []                                                      # migrated from the Visio: not here
    assert buscar("n") == [] and buscar("") == []                                      # too short
    hallado = buscar("nandu")[0]
    assert (hallado["tipo"], hallado["proyecto"], round(hallado["lat"], 3), round(hallado["lon"], 3)) == ("mufa", "Red existente – Prueba", 12.13, -86.3)
    # a project that is not a base one and not assigned is not searched for a reader
    con.execute("UPDATE redes.proyectos SET es_red_base = false WHERE id = %s", (p["id"],))
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    assert mufas_existentes.buscar_elementos(con, lector, texto="nandu")["elementos"] == []
    assert len(mufas_existentes.buscar_elementos(con, admin, texto="nandu")["elementos"]) == 1