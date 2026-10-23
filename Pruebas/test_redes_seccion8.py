"""Network design module, section 8 of the spec (data and architecture): fibre buffer / TIA colour
stored in `hilos`, optimistic lock on the mufa canvas positions, the integrity check, and
architecture rules of the schema (everything in `redes`, versions and logical delete, the existing
tables untouched)."""
import re
from pathlib import Path

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_diagrama import red_diagrama  # noqa: F401
from test_redes_fase7 import _usuario
from visor_rutas.redes import db, diagrama, mufa, pendientes, problemas, proyectos, red, usuarios, verificar

MIGRACIONES = Path(__file__).resolve().parents[1] / "visor_rutas" / "redes" / "migraciones"


def _hilos(con, cable_id):
    return {f["numero"]: (f["buffer"], f["color"], f["color_buffer"]) for f in con.execute(
        "SELECT numero, buffer, color, color_buffer FROM redes.hilos WHERE cable_id = %s AND borrado_en IS NULL", (cable_id,)).fetchall()}


def test_fibres_store_their_buffer_and_tia_colour(red_diagrama):
    con, admin, p, ids = red_diagrama
    dist = _hilos(con, ids["k1"])                                   # 24 hilos, 8 por buffer
    assert dist[1] == (1, "azul", "azul") and dist[8] == (1, "negro", "azul")
    assert dist[9] == (2, "azul", "naranja") and dist[24] == (3, "negro", "verde")
    troncal = _hilos(con, ids["k0"])                                # 48 hilos, 12 por buffer
    assert troncal[12] == (1, "aqua", "azul") and troncal[13] == (2, "azul", "naranja") and troncal[48] == (4, "aqua", "café")
    # 8 -> 12 per buffer: the database recolours the cable's fibres; more fibres get theirs too
    cable = next(c for c in red.red(con, admin, proyecto_id=p["id"])["cables"] if c["id"] == ids["k1"])
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"cables": [{**cable, "hilos_por_buffer": 12, "hilos": 48}]})
    dist = _hilos(con, ids["k1"])
    assert len(dist) == 48 and dist[9] == (1, "amarillo", "azul") and dist[13] == (2, "azul", "naranja") and dist[48] == (4, "aqua", "café")
    # what the mufa editor reads, and a duplicated project, carry the same values
    vista = mufa.leer(con, admin, mufa_id=ids["m1"])
    f9 = next(f for c in vista["cables"] if c["id"] == ids["k1"] for f in c["fibras"] if f["numero"] == 9)
    assert (f9["buffer"], f9["color"]) == (1, "amarillo")
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    otra = con.execute("SELECT id FROM redes.cables WHERE proyecto_id = %s AND nombre = 'Distribución'", (copia["id"],)).fetchone()["id"]
    assert _hilos(con, otra) == dist


def test_mufa_canvas_positions_have_optimistic_lock(red_diagrama):
    con, admin, _, ids = red_diagrama
    cable = lambda v: next(c for c in v["cables"] if c["id"] == ids["k1"])
    v0 = mufa.leer(con, admin, mufa_id=ids["m1"])
    assert cable(v0)["pos_version"] is None
    v1 = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"posiciones": [{"cable_id": ids["k1"], "x": 10, "y": 20}]})
    assert (cable(v1)["x"], cable(v1)["pos_version"]) == (10, 1)
    v2 = mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"posiciones": [{"cable_id": ids["k1"], "x": 30, "y": 20, "version": 1}]})
    assert (cable(v2)["x"], cable(v2)["pos_version"]) == (30, 2)
    for version in (1, None):                                       # a stale editor, or one that did not read the version
        with pytest.raises(db.ConflictoVersion, match="Distribución"):
            mufa.guardar(con, admin, mufa_id=ids["m1"], cambios={"posiciones": [{"cable_id": ids["k1"], "x": 99, "y": 99, "version": version}]})
    assert cable(mufa.leer(con, admin, mufa_id=ids["m1"]))["x"] == 30


def test_integrity_check(red_diagrama):
    con, admin, p, ids = red_diagrama
    limpio = verificar.verificar(con, admin)
    assert (limpio["errores"], limpio["avisos"], limpio["proyectos"]) == (0, 0, 1) and len(limpio["reglas"]) == 15
    # things the viewer cannot produce, written straight into the database
    norte = mufa.leer(con, admin, mufa_id=ids["m1"])
    sp = norte["splitters"][0]
    con.execute("UPDATE redes.puertos SET numero = 9 WHERE splitter_id = %s AND lado = 'salida' AND numero = 2", (sp["id"],))   # a 1x8
    troncal_2 = next(f for c in norte["cables"] if c["nombre"] == "Troncal" for f in c["fibras"] if f["numero"] == 2)
    con.execute("UPDATE redes.hilos SET borrado_en = now() WHERE id = %s", (troncal_2["id"],))
    con.execute("UPDATE redes.elementos SET borrado_en = now() WHERE id = %s", (ids["c1"],))               # Casa Pérez, end of the drop
    # valid but worth a look
    tecnico = _usuario(con, admin, "Pedro", "lector", p["id"])
    pendientes.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "Validar mufa", "responsable_id": tecnico["id"]})
    usuarios.cambiar_estado(con, admin, id=tecnico["id"], version=tecnico["version"], activo=False)
    problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "elemento_id": ids["m3"], "titulo": "Tapa rota"})
    diagrama.guardar(con, admin, proyecto_id=p["id"], datos={"titulo": "Sur", "inicio": f"e:{ids['m3']}"})
    con.execute("UPDATE redes.elementos SET borrado_en = now() WHERE id = %s", (ids["m3"],))
    r = verificar.verificar(con, admin)
    reglas = {(h["nivel"], h["regla"]) for h in r["hallazgos"]}
    assert {("error", "Hilos del cable"), ("error", "Conexión con hilo eliminado"), ("error", "Salida de splitter fuera de rango"),
            ("error", "Cable con extremo eliminado")} <= reglas
    assert {("aviso", "Diagrama sin inicio"), ("aviso", "Problema abierto sobre algo eliminado"),
            ("aviso", "Pendiente con responsable desactivado")} <= reglas
    textos = " | ".join(h["texto"] for h in r["hallazgos"])
    assert "Cable Troncal: tiene 47 hilos activos y debería tener 48" in textos and "Splitter 1 (1x8) tiene conectada la salida 9" in textos
    assert r["hallazgos"][0]["nivel"] == "error" and all(h["proyecto"] == "Los Robles (RLR)" for h in r["hallazgos"])
    lector = _usuario(con, admin, "Ana", "lector")
    with pytest.raises(db.SinPermiso):
        verificar.verificar(con, lector)


def test_schema_architecture_rules(base_redes, con_redes):
    """8.1: everything in schema `redes`; every editable table has `version` and logical delete; the
    existing tables (red_lineas, red_puntos, red_fibra) are never touched by a migration."""
    con = con_redes
    for archivo in sorted(MIGRACIONES.glob("*.sql")):
        texto = archivo.read_text(encoding="utf-8")
        for tabla in re.findall(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?([\w.]+)", texto, re.I):
            assert tabla.startswith("redes."), f"{archivo.name}: {tabla} fuera del esquema redes"
        sin_comentarios = re.sub(r"--[^\n]*", "", texto)
        assert not re.search(r"\b(red_lineas|red_puntos|red_fibra)\b", sin_comentarios, re.I), archivo.name
    columnas = {}
    for f in con.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'redes'").fetchall():
        columnas.setdefault(f["table_name"], set()).add(f["column_name"])
    # tables that are not edited record by record: the log, the migration list, links and derived ports
    sin_version = {"migraciones", "historial", "proyecto_usuarios", "puertos", "problema_fotos", "spatial_ref_sys",
                   "campo_ubicaciones",                          # only the last position of each technician: replaced, never deleted
                       "migracion_visio_corridas", "migracion_visio_log",         # logs: only inserted
                   "lugares_adjuntos", "lugares_compartidas",
                   "kmz_importacion_detalle",
                   "almacen_archivos"}                       # files by (space, key): replaced whole, deleted by age                # images / shares: replaced or logically deleted by their owner; the rows of an import go away with it
    for tabla, cols in columnas.items():
        if tabla in sin_version or tabla.startswith(("geography_", "geometry_")):
            continue
        assert "version" in cols, f"redes.{tabla} sin version"
        if tabla != "mufa_cables":                                  # a position is replaced, never deleted
            assert "borrado_en" in cols, f"redes.{tabla} sin borrado lógico"
    assert {"buffer", "color", "color_buffer"} <= columnas["hilos"]
    from visor_rutas.redes import repositorio
    assert set(repositorio.COLUMNAS) <= set(columnas)                # the writable whitelist names real tables


def test_service_method(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS
    assert METODOS["verificar_base"] is verificar.verificar
