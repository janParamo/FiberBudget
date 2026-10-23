"""Visio → interactive mufas migration, phase 1 (docs/migracion_visio/PLAN.md §5): the data model of
migration 009 — cable configurations (24 = 6x4 / 12x2, 48 = 6x8 / 12x4…) with buffer and TIA colour,
unknown fibre count, ODF and unplaced elements, mufa model 48 / 96 with its trays and a 1x8 splitter
in a tray, tray positions, origin / confidence of each datum, the automatic backup before a marked
migration, and backup / duplicate keeping all of it."""
import json
from pathlib import Path

import psycopg
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, migrar, mufa, proyectos, red, repositorio, respaldo, usuarios

MIGRACION_009 = Path(__file__).resolve().parents[1] / "visor_rutas" / "redes" / "migraciones" / "009_red_existente.sql"


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


@pytest.fixture
def base_minima(con_redes):
    """Mufa A (48) -(24 6x4)-> Mufa B (96) -(48 6x8)-> ODF, plus 24 12x2 and 48 12x4 between A and B."""
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Prueba", "codigo": "RE-PRUEBA"})["proyecto"]
    con.execute("UPDATE redes.proyectos SET es_red_base = true, zona = 'Managua' WHERE id = %s", (p["id"],))
    cable = lambda id_, nombre, hilos, pb, o, d: {"id": id_, "nombre": nombre, "hilos": hilos, "hilos_por_buffer": pb, "origen_id": o,
                                                  "destino_id": d, "vertices": [_v(12.10, -86.30), _v(12.11, -86.30)]}
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "a", "tipo": "mufa", "nombre": "Mufa A", "lat": 12.10, "lon": -86.30},
                      {"id": "b", "tipo": "mufa", "nombre": "Mufa B", "lat": 12.11, "lon": -86.30},
                      {"id": "o", "tipo": "odf", "nombre": "ODF Central", "lat": 12.12, "lon": -86.30}],
        "cables": [cable("k1", "C24 6x4", 24, 4, "a", "b"), cable("k2", "C24 12x2", 24, 2, "a", "b"),
                   cable("k3", "C48 6x8", 48, 8, "b", "o"), cable("k4", "C48 12x4", 48, 4, "a", "b")]})
    return con, admin, p, r["ids"]


def _hilos(con, cable_id):
    return {f["numero"]: (f["buffer"], f["color"], f["color_buffer"]) for f in con.execute(
        "SELECT numero, buffer, color, color_buffer FROM redes.hilos WHERE cable_id = %s", (cable_id,)).fetchall()}


def test_cable_configurations_buffers_and_tia_colours(base_minima):
    con, admin, p, ids = base_minima
    conf = {f["nombre"]: (f["hilos"], f["buffers"], f["configuracion"]) for f in con.execute(
        "SELECT nombre, hilos, buffers, configuracion FROM redes.cables WHERE proyecto_id = %s", (p["id"],)).fetchall()}
    assert conf == {"C24 6x4": (24, 6, "6x4"), "C24 12x2": (24, 12, "12x2"), "C48 6x8": (48, 6, "6x8"), "C48 12x4": (48, 12, "12x4")}
    h = _hilos(con, ids["k1"])                                          # 6 buffers of 4: blue, orange, green, brown in each
    assert h[1] == (1, "azul", "azul") and h[4] == (1, "café", "azul") and h[5] == (2, "azul", "naranja") and h[24] == (6, "café", "blanco")
    h = _hilos(con, ids["k2"])                                          # 12 buffers of 2: blue, orange
    assert h[1] == (1, "azul", "azul") and h[2] == (1, "naranja", "azul") and h[3] == (2, "azul", "naranja") and h[24] == (12, "naranja", "aqua")
    h = _hilos(con, ids["k3"])                                          # 6 buffers of 8
    assert h[8] == (1, "negro", "azul") and h[9] == (2, "azul", "naranja") and h[48] == (6, "negro", "blanco")
    h = _hilos(con, ids["k4"])                                          # 12 buffers of 4
    assert h[48] == (12, "café", "aqua")
    # the small cables of the existing network, and the editor still validates
    cable = next(c for c in red.red(con, admin, proyecto_id=p["id"])["cables"] if c["id"] == ids["k1"])
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**cable, "hilos": 12, "hilos_por_buffer": 2}]})
    assert con.execute("SELECT configuracion FROM redes.cables WHERE id = %s", (ids["k1"],)).fetchone()["configuracion"] == "6x2"
    for hilos, pb, error in ((10, 2, "cantidad de hilos"), (24, 3, "hilos por buffer")):
        with pytest.raises(db.DatosInvalidos, match=error):
            red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**cable, "hilos": hilos, "hilos_por_buffer": pb, "version": 2}]})
    pequeno = con.execute("INSERT INTO redes.cables (proyecto_id, nombre, hilos, hilos_por_buffer, origen_id, destino_id, vertices, geom, longitud_m) "
                          "SELECT proyecto_id, 'C2', 2, 2, origen_id, destino_id, vertices, geom, longitud_m FROM redes.cables WHERE id = %s "
                          "RETURNING configuracion", (ids["k1"],)).fetchone()
    assert pequeno["configuracion"] == "1x2"


def test_unknown_fibre_count_and_origin_fields(base_minima):
    con, admin, p, ids = base_minima
    fila = repositorio.insertar(con, "cables", {
        "proyecto_id": p["id"], "nombre": "Visio sin hilos", "hilos": None, "origen_id": ids["a"], "destino_id": ids["b"],
        "vertices": psycopg.types.json.Jsonb([_v(12.10, -86.30), _v(12.11, -86.30)]), "geom": "SRID=4326;LINESTRING(-86.30 12.10, -86.30 12.11)",
        "longitud_m": 1111, "fuente": "texto_diagrama", "confianza": "media", "geom_fuente": "recta", "configuracion_estimada": True,
        "estado_migracion": "automatica", "ref_visio": psycopg.types.json.Jsonb({"clave": "MUFA A|MUFA B", "enlaces": [10, 11]})}, admin["id"])
    assert (fila["hilos"], fila["buffers"], fila["configuracion"], fila["tipo_fibra"]) == (None, None, None, "SM dispersión cero")
    vista = mufa.leer(con, admin, mufa_id=ids["a"])
    sin = next(c for c in vista["cables"] if c["nombre"] == "Visio sin hilos")
    assert sin["hilos"] is None and sin["fibras"] == []
    with pytest.raises(psycopg.errors.CheckViolation):
        with con.transaction():
            con.execute("UPDATE redes.cables SET fuente = 'inventada' WHERE id = %s", (fila["id"],))
    with pytest.raises(psycopg.errors.UniqueViolation):                       # the Visio key does not repeat in a project
        with con.transaction():
            repositorio.insertar(con, "cables", {"proyecto_id": p["id"], "nombre": "otro", "hilos": None, "origen_id": ids["a"],
                                                 "destino_id": ids["b"], "vertices": psycopg.types.json.Jsonb([]),
                                                 "geom": "SRID=4326;LINESTRING(-86.30 12.10, -86.30 12.11)", "longitud_m": 1,
                                                 "ref_visio": psycopg.types.json.Jsonb({"clave": "MUFA A|MUFA B"})}, admin["id"])


def test_odf_unplaced_elements_and_user_edits_win(base_minima):
    con, admin, p, ids = base_minima
    sin = repositorio.insertar(con, "elementos", {
        "proyecto_id": p["id"], "tipo": "mufa", "subtipo": "reserva", "nombre": "Reserva sin ubicar", "ubicacion": None,
        "ubicacion_fuente": "sin_ubicar", "fuente": "texto_diagrama", "confianza": "media", "estado_migracion": "automatica",
        "ref_visio": psycopg.types.json.Jsonb({"clave": "RESERVA SIN UBICAR|", "nodo_id": 77})}, admin["id"])
    with pytest.raises(psycopg.errors.CheckViolation):                        # no position only when "sin_ubicar"
        with con.transaction():
            con.execute("UPDATE redes.elementos SET ubicacion = NULL WHERE id = %s", (ids["a"],))
    mapa = red.red(con, admin, proyecto_id=p["id"])
    assert {e["tipo"] for e in mapa["elementos"]} >= {"odf", "mufa"}
    fila = next(e for e in mapa["elementos"] if e["id"] == sin["id"])
    assert fila["lat"] is None
    # the user places it on the map: user position, and the migrated element becomes "editada"
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**fila, "lat": 12.105, "lon": -86.301}]})
    f = con.execute("SELECT ubicacion_fuente, estado_migracion, subtipo FROM redes.elementos WHERE id = %s", (sin["id"],)).fetchone()
    assert (f["ubicacion_fuente"], f["estado_migracion"], f["subtipo"]) == ("usuario", "editada", "reserva")
    # an estimated cable configuration the user changes is no longer an estimate
    con.execute("UPDATE redes.cables SET configuracion_estimada = true, estado_migracion = 'automatica', geom_fuente = 'recta' WHERE id = %s",
                (ids["k3"],))
    cable = next(c for c in red.red(con, admin, proyecto_id=p["id"])["cables"] if c["id"] == ids["k3"])
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**cable, "hilos_por_buffer": 4}]})
    f = con.execute("SELECT configuracion, configuracion_estimada, estado_migracion, geom_fuente FROM redes.cables WHERE id = %s",
                    (ids["k3"],)).fetchone()
    assert (f["configuracion"], f["configuracion_estimada"], f["estado_migracion"], f["geom_fuente"]) == ("12x4", False, "editada", "recta")


def test_mufa_models_trays_and_splitter_tray(base_minima):
    _mufas_bandejas_y_clientes(base_minima)


def _mufas_bandejas_y_clientes(base_minima):
    """A 48 mufa (2 trays) and a 96 mufa (4 trays) with a 1x8 splitter in tray 4, a splice in tray 1
    and clients; checks the constraints on the way."""
    con, admin, p, ids = base_minima
    for mufa_id, capacidad, bandejas in ((ids["a"], 48, 2), (ids["b"], 96, 4)):
        repositorio.insertar(con, "mufa_modelos", {"mufa_id": mufa_id, "capacidad": capacidad, "bandejas": bandejas, "fuente": "estimado"}, admin["id"])
        for n in range(1, bandejas + 1):
            repositorio.insertar(con, "mufa_bandejas", {"mufa_id": mufa_id, "numero": n, "fuente": "estimado"}, admin["id"])
    modelos = {f["mufa_id"]: (f["capacidad"], f["bandejas"], f["formato"], f["modelo_estimado"], f["empalmes_por_bandeja"])
               for f in con.execute("SELECT * FROM redes.mufa_modelos").fetchall()}
    assert modelos == {ids["a"]: (48, 2, "desconocido", True, 24), ids["b"]: (96, 4, "desconocido", True, 24)}
    # a 1x8 splitter in tray 4 of the 96 mufa: 8 outputs + the input = 9 positions (decided by IDEAY)
    vista = mufa.guardar(con, admin, mufa_id=ids["b"], cambios={"splitters": [{"id": "s", "nombre": "SPL 1X8", "salidas": 8}]})
    sp = vista["splitters"][0]
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s, capacidad = 9 WHERE mufa_id = %s AND numero = 4", (sp["id"], ids["b"]))
    con.execute("UPDATE redes.splitters SET propiedades = %s, fuente = 'texto_diagrama', confianza = 'media' WHERE id = %s",
                (json.dumps({"olt": "OLT LEON", "puerto_olt": "0/2/0"}), sp["id"]))
    bandeja4 = con.execute("SELECT capacidad, splitter_id FROM redes.mufa_bandejas WHERE mufa_id = %s AND numero = 4", (ids["b"],)).fetchone()
    assert (bandeja4["capacidad"], bandeja4["splitter_id"]) == (9, sp["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):                       # a splitter sits in one tray only
        with con.transaction():
            con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s WHERE mufa_id = %s AND numero = 3", (sp["id"], ids["b"]))
    # splices with tray and position; two splices never share a position; positions 1..24
    h = lambda cable, n: con.execute("SELECT id FROM redes.hilos WHERE cable_id = %s AND numero = %s", (ids[cable], n)).fetchone()["id"]
    x = repositorio.insertar(con, "conexiones", {"proyecto_id": p["id"], "mufa_id": ids["b"], "a_hilo_id": h("k1", 1), "b_hilo_id": h("k3", 1),
                                                 "bandeja": 1, "posicion_en_bandeja": 1, "fuente": "excel_anillos", "confianza": "alta"}, admin["id"])
    assert (x["bandeja"], x["posicion_en_bandeja"], x["fuente"]) == (1, 1, "excel_anillos")
    malas = [{"a_hilo_id": h("k1", 2), "b_hilo_id": h("k3", 2), "bandeja": 1, "posicion_en_bandeja": 1},      # taken
             {"a_hilo_id": h("k1", 3), "b_hilo_id": h("k3", 3), "bandeja": 1, "posicion_en_bandeja": 25},     # out of the tray
             {"a_hilo_id": h("k1", 4), "b_hilo_id": h("k3", 4), "bandeja": 2, "posicion_en_bandeja": None}]   # tray without position
    for m in malas:
        with pytest.raises((psycopg.errors.UniqueViolation, psycopg.errors.CheckViolation)):
            with con.transaction():
                repositorio.insertar(con, "conexiones", {"proyecto_id": p["id"], "mufa_id": ids["b"], **m}, admin["id"])
    # clients: by splitter port, and listed in a mufa without a port
    puerto = con.execute("SELECT id FROM redes.puertos WHERE splitter_id = %s AND lado = 'salida' AND numero = 1", (sp["id"],)).fetchone()["id"]
    repositorio.insertar(con, "puerto_servicios", {"puerto_id": puerto, "codigo_cliente": "C22835", "nombre": "AGRO ALFA",
                                                   "id_servicio": "ID000721", "fuente": "texto_diagrama", "confianza": "media"}, admin["id"])
    repositorio.insertar(con, "mufa_clientes", {"mufa_id": ids["a"], "codigo_cliente": "C24217", "nombre": "Centro de Producción",
                                                "fuente": "texto_diagrama", "confianza": "media"}, admin["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):                       # one client per port
        with con.transaction():
            repositorio.insertar(con, "puerto_servicios", {"puerto_id": puerto, "codigo_cliente": "C1"}, admin["id"])


def test_backup_and_duplicate_keep_the_migration_data(base_minima, tmp_path, monkeypatch):
    con, admin, p, ids = base_minima
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path))
    _mufas_bandejas_y_clientes(base_minima)
    con.execute("UPDATE redes.elementos SET fuente = 'texto_diagrama', confianza = 'media', estado_migracion = 'automatica', "
                "ref_visio = '{\"clave\": \"MUFA A|12.1000,-86.3000\", \"nodo_id\": 5}' WHERE id = %s", (ids["a"],))
    con.execute("UPDATE redes.cables SET configuracion_estimada = true, geom_fuente = 'kmz', fuente = 'estimado' WHERE id = %s", (ids["k3"],))

    def contar(pid):
        q = lambda sql: con.execute(sql, (pid,)).fetchone()["n"]
        return {
            "modelos": q("SELECT count(*) n FROM redes.mufa_modelos m JOIN redes.elementos e ON e.id = m.mufa_id WHERE e.proyecto_id = %s"),
            "bandejas": q("SELECT count(*) n FROM redes.mufa_bandejas b JOIN redes.elementos e ON e.id = b.mufa_id WHERE e.proyecto_id = %s"),
            "bandeja_splitter": q("SELECT count(*) n FROM redes.mufa_bandejas b JOIN redes.elementos e ON e.id = b.mufa_id "
                                  "WHERE e.proyecto_id = %s AND b.splitter_id IS NOT NULL AND b.capacidad = 9"),
            "puerto_clientes": q("SELECT count(*) n FROM redes.puerto_servicios ps JOIN redes.puertos pt ON pt.id = ps.puerto_id "
                                 "JOIN redes.splitters s ON s.id = pt.splitter_id WHERE s.proyecto_id = %s"),
            "mufa_clientes": q("SELECT count(*) n FROM redes.mufa_clientes c JOIN redes.elementos e ON e.id = c.mufa_id WHERE e.proyecto_id = %s"),
            "en_bandeja": q("SELECT count(*) n FROM redes.conexiones WHERE proyecto_id = %s AND bandeja = 1 AND fuente = 'excel_anillos'"),
            "olt": q("SELECT count(*) n FROM redes.splitters WHERE proyecto_id = %s AND propiedades ->> 'puerto_olt' = '0/2/0'"),
            "visio": q("SELECT count(*) n FROM redes.elementos WHERE proyecto_id = %s AND ref_visio ->> 'nodo_id' = '5' AND estado_migracion = 'automatica'"),
            "odf": q("SELECT count(*) n FROM redes.elementos WHERE proyecto_id = %s AND tipo = 'odf'"),
            "estimados": q("SELECT count(*) n FROM redes.cables WHERE proyecto_id = %s AND configuracion_estimada AND geom_fuente = 'kmz'"),
            "6x4": q("SELECT count(*) n FROM redes.cables WHERE proyecto_id = %s AND configuracion = '6x4'"),
        }

    antes = contar(p["id"])
    assert all(antes.values()), antes
    archivo, aviso = respaldo.respaldar(con, "prueba", admin["id"])
    restaurado = respaldo.restaurar(con, admin, archivo=archivo, indice=0)["proyecto"]
    assert contar(restaurado["id"]) == antes
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    assert contar(copia["id"]) == antes


def test_migration_009_is_idempotent(base_redes, con_redes):
    con = con_redes
    with con.transaction():
        con.execute(MIGRACION_009.read_text(encoding="utf-8"))              # once more: no error, nothing duplicated
    assert con.execute("SELECT count(*) n FROM pg_constraint WHERE conname = 'cables_hilos_check'").fetchone()["n"] == 1


def test_real_upgrade_from_008_backs_up_first(base_redes, tmp_path, monkeypatch):
    """What happens on the real database: schema up to 008 with a project, then 009 with its
    automatic backup — taken by today's code on yesterday's schema (it must not ask for 009 columns)."""
    import os
    import secrets
    import shutil

    from redes_base import PREFIJO, _admin
    _, params = base_redes
    nombre = f"{PREFIJO}_{os.getpid()}_{secrets.token_hex(3)}_008"
    admin_pg = _admin(params)
    admin_pg.execute(f'CREATE DATABASE "{nombre}"')
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path / "respaldos"))
    hasta_008 = tmp_path / "hasta_008"
    hasta_008.mkdir()
    for archivo in sorted(MIGRACION_009.parent.glob("00[1-8]_*.sql")):
        shutil.copy(archivo, hasta_008 / archivo.name)
    con = db.conectar(params={**params, "dbname": nombre})
    try:
        assert migrar.aplicar(con, hasta_008) == [1, 2, 3, 4, 5, 6, 7, 8]
        yo = usuarios.identificar(con, usuario_windows="jgutierrez")
        # yesterday's data written with plain SQL (today's code already reads the 009 columns)
        pid = con.execute("INSERT INTO redes.proyectos (codigo, nombre, creado_por) VALUES ('A009', 'Antes de la 009', %s) RETURNING id",
                          (yo["id"],)).fetchone()["id"]
        a, b = (con.execute("INSERT INTO redes.elementos (proyecto_id, tipo, nombre, ubicacion) VALUES "
                            "(%s, 'mufa', %s, ST_SetSRID(ST_MakePoint(-86.3, %s), 4326)) RETURNING id", (pid, n, lat)).fetchone()["id"]
                for n, lat in (("MF 1", 12.1), ("MF 2", 12.11)))
        cid = con.execute("INSERT INTO redes.cables (proyecto_id, nombre, hilos, hilos_por_buffer, origen_id, destino_id, vertices, geom, longitud_m) "
                          "VALUES (%s, 'C1', 24, 12, %s, %s, %s, 'SRID=4326;LINESTRING(-86.3 12.1, -86.3 12.11)', 1112) RETURNING id",
                          (pid, a, b, json.dumps([{**_v(12.1, -86.3), "elemento_id": a}, {**_v(12.11, -86.3), "elemento_id": b}]))).fetchone()["id"]
        mufa.sincronizar_hilos(con, cid, 24, yo["id"])
        assert migrar.aplicar(con) == [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]       # all the real folder: 009 to 019 were missing
        hechos = sorted((tmp_path / "respaldos").glob("respaldo_redes_*.json"))
        assert len(hechos) == 8                                            # one before each marked migration, never overwritten
        datos = json.loads(hechos[0].read_text(encoding="utf-8"))
        assert datos["motivo"] == "antes de la migración 009_red_existente"
        assert [x["proyecto"]["codigo"] for x in datos["proyectos"]] == ["A009"] and len(datos["proyectos"][0]["cables"]) == 1
        assert "es_red_base" not in datos["proyectos"][0]["proyecto"]       # yesterday's schema
        cable = con.execute("SELECT configuracion, tipo_fibra FROM redes.cables").fetchone()
        assert (cable["configuracion"], cable["tipo_fibra"]) == ("2x12", "SM dispersión cero")
        # and that backup restores into today's schema
        nuevo = respaldo.restaurar(con, yo, archivo=hechos[0].name, indice=0)["proyecto"]
        assert con.execute("SELECT count(*) n FROM redes.cables WHERE proyecto_id = %s", (nuevo["id"],)).fetchone()["n"] == 1
    finally:
        con.close()
        assert nombre.startswith(PREFIJO)
        admin_pg.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        admin_pg.close()


def test_automatic_backup_before_a_marked_migration(base_minima, tmp_path, monkeypatch):
    con, admin, p, ids = base_minima
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path / "respaldos"))
    carpeta = tmp_path / "migraciones"
    carpeta.mkdir()
    (carpeta / "990_sin_respaldo.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (carpeta / "991_con_respaldo.sql").write_text("-- respaldo: previo\n-- prueba\nSELECT 1;\n", encoding="utf-8")
    try:
        assert migrar.aplicar(con, carpeta) == [990, 991]
        hechos = list((tmp_path / "respaldos").glob("respaldo_redes_*.json"))
        assert len(hechos) == 1                                              # only before 991
        datos = json.loads(hechos[0].read_text(encoding="utf-8"))
        assert datos["motivo"] == "antes de la migración 991_con_respaldo" and [x["proyecto"]["codigo"] for x in datos["proyectos"]] == ["RE-PRUEBA"]
        assert migrar.pide_respaldo(next(m for m in migrar.disponibles() if m.version == 9))
    finally:
        con.execute("DELETE FROM redes.migraciones WHERE version >= 990")
    # an empty database (fresh install, tests) needs no backup
    con.execute("UPDATE redes.proyectos SET borrado_en = now()")
    assert migrar.respaldo_previo(con, migrar.Migracion(992, "x", "-- respaldo: previo", "0")) is None

