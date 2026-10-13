"""Visio → interactive mufas migration, phase 4 (docs/migracion_visio/PLAN.md rule 6.5 and section 8):
the model of a mufa (48 / 96, estimated by the largest cable and its splitters), its trays (24 splices,
a splitter tray limited to its outputs + the input), the default positions (splitters from the last
tray, direct splices from tray 1 by buffer), moving a splice, changing the model, a splitter to another
tray, the editor placing what it creates, and backup / duplicate keeping it."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import bandejas, db, mufa, proyectos, red, usuarios

R = bandejas.reglas({})                       # defaults: 24 per tray, 48 -> 2 trays, 96 -> 4, splitter input takes a position


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


def test_model_rule():
    elegir = lambda h, s=(), **k: bandejas.elegir_modelo(h, list(s), R, **k)
    assert (elegir(24)["capacidad"], elegir(24)["bandejas"], elegir(24)["motivo"]) == (48, 2, "cable mayor de 24 hilos")
    assert elegir(72)["capacidad"] == 96 and elegir(96)["bandejas"] == 4
    assert elegir(None)["capacidad"] == 48 and "sin cables con hilos conocidos" in elegir(None)["motivo"]
    assert "excede la capacidad" in elegir(144)["avisos"][0]
    tres = elegir(24, [8, 8, 8])                                      # 3 splitters + direct splices = 4 trays
    assert (tres["capacidad"], tres["avisos"]) == (96, []) and "3 splitters" in tres["motivo"]
    assert "no caben en 4 bandejas" in elegir(24, [8, 8, 8, 8])["avisos"][0]
    assert "no cabe en una bandeja" in elegir(12, [32])["avisos"][0]  # 1x32 + input = 33 > 24
    assert "sangría" in elegir(24, sangria=True)["motivo"]
    assert bandejas.formato_de_texto("FOSC DOMO 48F") == "domo" and bandejas.formato_de_texto("SANGRIA") == "desconocido"


@pytest.fixture
def mufa_b(con_redes):
    """Mufa A -(C1 24)-> Mufa B -(C2 24)-> Mufa C, in a base project; in B a 1x8 splitter, three
    fibre-fibre splices (C1 H5↔C2 H5, C1 H1↔C2 H1, C1 H2↔C2 H2) and C1 H3 -> splitter -> output 2 -> C2 H8."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Prueba", "codigo": "RE-B"})["proyecto"]
    con.execute("UPDATE redes.proyectos SET es_red_base = true WHERE id = %s", (p["id"],))
    cable = lambda i, o, d, la: {"id": i, "nombre": i.upper(), "hilos": 24, "hilos_por_buffer": 4, "origen_id": o, "destino_id": d,
                                 "vertices": [_v(la, -86.30), _v(la + 0.01, -86.30)]}
    ids = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": k, "tipo": "mufa", "nombre": f"Mufa {k.upper()}", "lat": 12.10 + i * 0.01, "lon": -86.30}
                      for i, k in enumerate("abc")],
        "cables": [cable("c1", "a", "b", 12.10), cable("c2", "b", "c", 12.11)]})["ids"]
    hilo = lambda c, n: con.execute("SELECT id FROM redes.hilos WHERE cable_id = %s AND numero = %s", (ids[c], n)).fetchone()["id"]
    fusion = lambda i, a, b: {"id": i, "a": {"hilo": a}, "b": {"hilo": b}}
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={
        "splitters": [{"id": "s1", "nombre": "SPL 1X8", "salidas": 8, "x": 470, "y": 40}],
        "conexiones": [fusion("x1", hilo("c1", 5), hilo("c2", 5)), fusion("x2", hilo("c1", 1), hilo("c2", 1)),
                       fusion("x3", hilo("c1", 2), hilo("c2", 2)),
                       {"id": "x4", "a": {"hilo": hilo("c1", 3)}, "b": {"splitter": "s1", "lado": "entrada", "numero": 1}},
                       {"id": "x5", "a": {"splitter": "s1", "lado": "salida", "numero": 2}, "b": {"hilo": hilo("c2", 8)}}]})
    return con, admin, p, ids, r["ids"], hilo


def _lugares(con, mufa_id):
    return {(f["bandeja"], f["posicion_en_bandeja"]): f for f in con.execute(
        "SELECT x.id, x.bandeja, x.posicion_en_bandeja, x.posicion_estimada, x.version FROM redes.conexiones x "
        "WHERE x.mufa_id = %s AND x.borrado_en IS NULL", (mufa_id,)).fetchall()}


def test_default_model_trays_and_positions(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    hecho = bandejas.crear_modelo(con, ids["b"], admin["id"], R)
    assert (hecho["capacidad"], hecho["bandejas"], hecho["avisos"]) == (48, 2, [])
    vista = mufa.leer(con, admin, mufa_id=ids["b"])
    assert (vista["modelo"]["capacidad"], vista["modelo"]["modelo_estimado"], vista["modelo"]["fuente"]) == (48, True, "estimado")
    assert [(b["numero"], b["capacidad"], b["splitter_id"]) for b in vista["bandejas"]] == [(1, 24, None), (2, 9, nuevos["s1"])]
    lugar = _lugares(con, ids["b"])
    # direct splices from tray 1 in fibre order (H1, H2, H5); the splitter's in tray 2: input = 1, output 2 = 3
    assert {k: v["id"] for k, v in lugar.items()} == {(1, 1): nuevos["x2"], (1, 2): nuevos["x3"], (1, 3): nuevos["x1"],
                                                      (2, 1): nuevos["x4"], (2, 3): nuevos["x5"]}
    assert all(v["posicion_estimada"] for v in lugar.values())
    x = next(c for c in vista["conexiones"] if c["id"] == nuevos["x1"])
    assert (x["bandeja"], x["posicion"], x["posicion_estimada"]) == (1, 3, True)


def test_move_swap_and_limits(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    bandejas.crear_modelo(con, ids["b"], admin["id"], R)
    bandejas.mover_empalme(con, admin, conexion_id=nuevos["x2"], bandeja=1, posicion=10)
    lugar = _lugares(con, ids["b"])
    assert lugar[(1, 10)]["id"] == nuevos["x2"] and not lugar[(1, 10)]["posicion_estimada"]
    bandejas.mover_empalme(con, admin, conexion_id=nuevos["x2"], bandeja=1, posicion=3)        # taken by x1: they swap
    lugar = _lugares(con, ids["b"])
    assert (lugar[(1, 3)]["id"], lugar[(1, 10)]["id"]) == (nuevos["x2"], nuevos["x1"])
    for args, error in (({"conexion_id": nuevos["x4"], "bandeja": 1, "posicion": 20}, "bandeja del splitter"),   # a splitter's splice
                        ({"conexion_id": nuevos["x1"], "bandeja": 2, "posicion": 5}, "bandeja del splitter"),    # into the splitter tray
                        ({"conexion_id": nuevos["x1"], "bandeja": 3, "posicion": 1}, "no existe"),
                        ({"conexion_id": nuevos["x1"], "bandeja": 1, "posicion": 25}, "no existe")):
        with pytest.raises(db.DatosInvalidos, match=error):
            bandejas.mover_empalme(con, admin, **args)
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(db.SinPermiso):
        bandejas.mover_empalme(con, lector, conexion_id=nuevos["x1"], bandeja=1, posicion=4)


def test_change_model_and_splitter_tray(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    bandejas.crear_modelo(con, ids["b"], admin["id"], R)
    vista = bandejas.guardar_modelo(con, admin, mufa_id=ids["b"], capacidad=96, formato="domo")
    assert (vista["modelo"]["capacidad"], vista["modelo"]["bandejas"], vista["modelo"]["formato"], vista["modelo"]["modelo_estimado"]) == (96, 4, "domo", False)
    assert len(vista["bandejas"]) == 4
    with pytest.raises(db.DatosInvalidos, match="tiene empalmes directos"):
        bandejas.bandeja_splitter(con, admin, mufa_id=ids["b"], numero=1, splitter_id=nuevos["s1"])
    vista = bandejas.bandeja_splitter(con, admin, mufa_id=ids["b"], numero=4, splitter_id=nuevos["s1"])   # its splices follow it
    assert [(b["numero"], b["capacidad"], b["splitter_id"]) for b in vista["bandejas"]][1:] == [(2, 24, None), (3, 24, None), (4, 9, nuevos["s1"])]
    assert {(k[0], k[1]) for k, v in _lugares(con, ids["b"]).items() if v["id"] in (nuevos["x4"], nuevos["x5"])} == {(4, 1), (4, 3)}
    with pytest.raises(db.DatosInvalidos, match="las bandejas 4"):
        bandejas.guardar_modelo(con, admin, mufa_id=ids["b"], capacidad=48)
    bandejas.bandeja_splitter(con, admin, mufa_id=ids["b"], numero=2, splitter_id=nuevos["s1"])
    vista = bandejas.guardar_modelo(con, admin, mufa_id=ids["b"], capacidad=48)
    assert len(vista["bandejas"]) == 2 and vista["bandejas"][1]["splitter_id"] == nuevos["s1"]
    with pytest.raises(db.DatosInvalidos, match="capacidad"):
        bandejas.guardar_modelo(con, admin, mufa_id=ids["b"], capacidad=72)


def test_editor_places_what_it_creates_and_frees_trays(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    bandejas.crear_modelo(con, ids["b"], admin["id"], R)
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"conexiones": [{"id": "n9", "a": {"hilo": hilo("c1", 9)}, "b": {"hilo": hilo("c2", 9)}}]})
    nueva = next(c for c in r["conexiones"] if c["id"] == r["ids"]["n9"])
    assert (nueva["bandeja"], nueva["posicion"], nueva["posicion_estimada"]) == (1, 4, True)
    s1 = next(s for s in r["splitters"] if s["id"] == nuevos["s1"])
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{**s1, "eliminar": True}]})
    assert [(b["capacidad"], b["splitter_id"]) for b in r["bandejas"]] == [(24, None), (24, None)]
    r = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s2", "nombre": "SPL 1X16", "salidas": 16, "x": 470, "y": 40}]})
    assert r["bandejas"][1]["splitter_id"] == r["ids"]["s2"] and r["bandejas"][1]["capacidad"] == 17


def test_tray_1_stays_for_direct_splices_and_untouched_models_follow_the_rule(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [
        {"id": f"s{i}", "nombre": f"SPL {i}", "salidas": 8, "x": 470, "y": 40 * i} for i in (2, 3, 4)]})
    hecho = bandejas.crear_modelo(con, ids["b"], admin["id"], R)                # 4 splitters: 96, but tray 1 keeps the splices
    assert hecho["capacidad"] == 96 and any("no hay bandeja libre" in a for a in hecho["avisos"])
    vista = mufa.leer(con, admin, mufa_id=ids["b"])
    assert vista["bandejas"][0]["splitter_id"] is None and all(b["splitter_id"] for b in vista["bandejas"][1:])
    assert {(c["bandeja"], c["posicion"]) for c in vista["conexiones"] if c["id"] in (nuevos["x1"], nuevos["x2"], nuevos["x3"])} == {(1, 1), (1, 2), (1, 3)}
    # a model the older rule built (a splitter in tray 1) and nobody touched is rebuilt; a touched one is not
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = NULL, capacidad = 24 WHERE mufa_id = %s AND numero = 4", (ids["b"],))
    sid = vista["bandejas"][3]["splitter_id"]
    con.execute("UPDATE redes.conexiones SET bandeja = NULL, posicion_en_bandeja = NULL WHERE mufa_id = %s AND bandeja = 1", (ids["b"],))
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s, capacidad = 9 WHERE mufa_id = %s AND numero = 1", (sid, ids["b"]))
    assert bandejas.migrar_modelos(con, None).get("modelos_recalculados") == 1
    assert mufa.leer(con, admin, mufa_id=ids["b"])["bandejas"][0]["splitter_id"] is None
    bandejas.mover_empalme(con, admin, conexion_id=nuevos["x1"], bandeja=1, posicion=20)
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = NULL WHERE mufa_id = %s AND numero = 4", (ids["b"],))
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s WHERE mufa_id = %s AND numero = 1", (sid, ids["b"]))
    assert "modelos_recalculados" not in bandejas.migrar_modelos(con, None)


def test_migrate_models_and_duplicate_keep_them(mufa_b):
    con, admin, p, ids, nuevos, hilo = mufa_b
    conteo = bandejas.migrar_modelos(con, None)
    assert conteo == {"modelos_48": 3}
    assert bandejas.migrar_modelos(con, None) == {}                    # once
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    b2 = con.execute("SELECT id FROM redes.elementos WHERE proyecto_id = %s AND nombre = 'Mufa B'", (copia["id"],)).fetchone()["id"]
    vista = mufa.leer(con, admin, mufa_id=b2)
    assert (vista["modelo"]["capacidad"], vista["modelo"]["motivo"]) == (48, "cable mayor de 24 hilos")
    assert sorted((c["bandeja"], c["posicion"]) for c in vista["conexiones"]) == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 3)]
    assert all(c["posicion_estimada"] for c in vista["conexiones"])
