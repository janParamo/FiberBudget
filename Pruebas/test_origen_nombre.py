"""Connection-point matching by name (origen.py cases c and d) and the diagnosis (case e)."""
import sqlite3
from dataclasses import asdict
from pathlib import Path

from origen import ChainPoint, find_traffic_origin, name_similarity, name_tokens

SCHEMA = Path(__file__).resolve().parent.parent / "red_fibra" / "schema.sql"
NAME_MATCH = {"enabled": True, "min_similarity": 0.8, "max_distance_m": 2000, "search_texts": True,
              "dependency_words": ["SPL DEPENDE DE", "DEPENDE DE", "VIENE DE", "VIENE DEL"]}
RULES = {"traffic_origin": {
    "match_radius_m": 40, "fallback_radius_m": 150, "max_hops": 8, "media_max_hops": 3,
    "saturated_text_distance_cm": 3, "ignore_label_words": ["RESPALDO", "REDUNDAN"],
    "nodes": {"NODO LAS SIERRITAS": ["LAS SIERRITAS", "SIERRITAS"], "OLT LAS COLINAS": ["LAS COLINAS"],
              "OLT GALERÍAS": ["GALERIAS"]},
    "name_match": NAME_MATCH,
}}
# The KMZ connection point "MF CASA GERENCIA OTTO MUNKEL" (red_puntos id 460)
KMZ = ChainPoint("MF CASA GERENCIA OTTO MUNKEL", 12.098894, -86.220120, "mufa")
FOLDER = "Mufas Establo a C Masaya a Nodo Las Sierritas"
PLAZA_MAYOR = f"{FOLDER}/3-2.1 Mufa Plaza Mayor 2  Ideay.vsd"


def _db(path: Path, nodes=(), links=(), services=(), files=((1, PLAZA_MAYOR),), appearances=(), texts=()) -> Path:
    """nodes: (id, nombre, lat, lon, zona); texts: (archivo_id, x, y, texto, clasificacion)."""
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("INSERT INTO importaciones (id, fecha, carpeta_origen) VALUES (1, '2026-10-07', 'x')")
    for file_id, ruta in files:
        con.execute("""INSERT INTO archivos (id, importacion_id, ruta_relativa, carpeta, nombre, formato,
                       tipo_diagrama, md5, estado) VALUES (?, 1, ?, ?, ?, 'vsd', 'subred', ?, 'ok')""",
                    (file_id, ruta, Path(ruta).parent.name, Path(ruta).name, f"{file_id:032d}"))
    for node_id, nombre, lat, lon, zona in nodes:
        con.execute("INSERT INTO nodos (id, nombre, nombre_normalizado, tipo, lat, lon, zona) "
                    "VALUES (?, ?, ?, 'MUFA', ?, ?, ?)", (node_id, nombre, nombre.upper(), lat, lon, zona))
    for a, b in links:
        con.execute("INSERT INTO enlaces (nodo_a_id, nodo_b_id, fuente, confianza) VALUES (?, ?, 'visio_linea', 'media')",
                    (a, b))
    for node_id, text in services:
        con.execute("INSERT INTO servicios (nodo_id, archivo_id, tipo, descripcion) VALUES (?, 1, 'splitter', ?)",
                    (node_id, text))
    for node_id, file_id, rol in appearances:
        con.execute("INSERT INTO nodo_apariciones (nodo_id, archivo_id, rol) VALUES (?, ?, ?)", (node_id, file_id, rol))
    for file_id, x, y, text, clase in texts:
        con.execute("INSERT INTO textos_crudos (archivo_id, pagina, x_cm, y_cm, texto, clasificacion) "
                    "VALUES (?, 0, ?, ?, ?, ?)", (file_id, x, y, text, clase))
    con.commit()
    con.close()
    return path


def _otto_munkel(tmp_path: Path, **extra) -> Path:
    """Minimal copy of the real diagram: the mufa is drawn without coordinates, depends on Plaza Mayor 2
    (which has no coordinates and no cables either), and the closest Visio mufa is ~900 m away."""
    return _db(tmp_path / "r.db",
               nodes=[(10, "MUFA PLAZA MAYOR 2 IDEAY", None, None, FOLDER),
                      (11, "MUFA OTTO MUNKEL EXTERNA", 12.094974, -86.227388, FOLDER),
                      (12, "MF NESTOR ABAUNZA", 12.09593, -86.21683, FOLDER)],
               appearances=[(10, 1, "principal"), (11, 1, "red"), (12, 1, "red")],
               texts=[(1, 145.53, 284.25, "MUFA - CASA GERENCIA OTTO MUNKEL\nVALIDAR EXISTENCIA DE MF EN ENLACE",
                       "nodo_sin_coord"),
                      (1, 147.56, 252.0, "MUFA OTTO MUNKEL EXTERNA\n12.094974,-86.227388\nHAY QUE DARLE "
                       "CONTINUIDAD A LOS HILOS", "nodo"),
                      (1, 126.2, 236.45, "HACIA MF EXTERNA OTTO MUNKEL à", "otro"),
                      (1, 140.35, 318.71, "C24764 MUNKEL LENTES DE NICARAGUA S,A (casa de gerencia Otto Munkel)",
                       "cliente"),
                      (1, 104.05, 248.38, "SPL DEPENDE DE 1/8 PM2\n1- FILY JOSSUE ROMERO\n6- CASA GERENCIA OTTO "
                       "MUNKEL\n7- MARIA ALEJANDRA HASBANI", "splitter"),
                      (1, 30.0, 20.0, "SPL DEPENDE DE OLT LAS COLINAS\n1- KINDER MONTESSORI", "cliente")],
               **extra)


# --------------------------------------------------------------------------- case d: OTTO MUNKEL

def test_otto_munkel_drawn_without_coordinate_starts_at_plaza_mayor_2(tmp_path):
    origin = find_traffic_origin(_otto_munkel(tmp_path), [KMZ], RULES)

    assert origin.match_method == "d"
    assert origin.path == ["MUFA - CASA GERENCIA OTTO MUNKEL", "MUFA PLAZA MAYOR 2 IDEAY"]
    assert (origin.node, origin.confidence) == ("NODO LAS SIERRITAS", "baja")   # from the diagram's folder
    assert origin.path_traced is False and origin.origin_mufa is None          # never counts intervened mufas
    assert origin.reason.startswith("emparejado por nombre en diagrama")
    assert origin.diagnostico["caso"] == "sin_coordenada_en_visio"
    assert origin.diagnostico["casos"] == ["sin_coordenada_en_visio", "marcada_validar"]
    assert "VALIDAR EXISTENCIA DE MF EN ENLACE" in origin.diagnostico["detalle"]
    match = origin.name_match
    assert (match["archivo"], match["archivo_id"], match["x_cm"]) == (Path(PLAZA_MAYOR).name, 1, 145.53)
    assert match["dependencia"] == "SPL DEPENDE DE 1/8 PM2" and match["inicio_por"] == "dependencia"
    assert origin.connection_match == {"name": "MUFA - CASA GERENCIA OTTO MUNKEL", "distance_m": None,
                                       "exact": False, "method": "d"}


def test_dependency_text_naming_the_olt_gives_the_node_directly(tmp_path):
    db = _otto_munkel(tmp_path)
    con = sqlite3.connect(db)
    con.execute("UPDATE textos_crudos SET texto = 'SPL DEPENDE DE OLT LAS COLINAS' || substr(texto, 23) "
                "WHERE texto LIKE 'SPL DEPENDE DE 1/8 PM2%'")
    con.commit()
    con.close()
    origin = find_traffic_origin(db, [KMZ], RULES)
    assert (origin.node, origin.confidence, origin.path) == (
        "OLT LAS COLINAS", "baja", ["MUFA - CASA GERENCIA OTTO MUNKEL"])
    assert origin.name_match["inicio_por"] == "nodo"


def test_walk_from_the_dependency_mufa_follows_its_cables(tmp_path):
    db = _otto_munkel(tmp_path, links=[(10, 12)], services=[(12, "SPL 1X8 PUERTO 3 OLT GALERIAS")])
    origin = find_traffic_origin(db, [KMZ], RULES)
    assert origin.path == ["MUFA - CASA GERENCIA OTTO MUNKEL", "MUFA PLAZA MAYOR 2 IDEAY", "MF NESTOR ABAUNZA"]
    assert (origin.node, origin.confidence, origin.labelled_mufa) == ("OLT GALERÍAS", "baja", "MF NESTOR ABAUNZA")
    assert origin.path_traced is False


def test_same_name_in_a_diagram_of_another_city_is_not_matched(tmp_path):
    far = 12.43   # ~37 km north: every georeferenced mufa of the diagram is beyond max_distance_m
    db = _db(tmp_path / "r.db", nodes=[(10, "MUFA LEON CENTRO", far, -86.87, "Red Leon")],
             appearances=[(10, 1, "principal")],
             texts=[(1, 5.0, 5.0, "MUFA - CASA GERENCIA OTTO MUNKEL", "nodo_sin_coord")])
    origin = find_traffic_origin(db, [KMZ], RULES)
    assert origin.node is None and origin.match_method == "e" and origin.path == []
    assert origin.diagnostico["caso"] == "sin_coordenada_en_visio"   # still reported for review


# --------------------------------------------------------------------------- normalization

def test_normalization_ignores_prefixes_accents_and_signs():
    assert name_tokens("MF CASA GERENCIA OTTO MUNKEL") == name_tokens("MUFA - CASA GERENCIA OTTO MUNKEL") == [
        "CASA", "GERENCIA", "OTTO", "MUNKEL"]
    assert name_similarity("MF CASA GERENCIA OTTO MUNKEL", "MUFA - CASA GERENCIA OTTO MUNKEL") == 1.0
    assert name_similarity("MF Óptica Visión", "MUFA OPTICA VISION") == 1.0
    assert name_similarity("MF Agusto Munkel", "MF AUGUSTO MUNKEL") == 1.0       # misspelling
    assert name_tokens("MN GALERIAS") == ["GALERIAS"] and name_tokens("6- CASA GERENCIA") == ["CASA", "GERENCIA"]


def test_different_names_are_not_matched():
    assert name_similarity("MF AUGUSTO MUNKEL", "MF CASA GERENCIA OTTO MUNKEL") < 0.8
    assert name_similarity("MF OTTO MUNKEL EXTERNA", "MF CASA GERENCIA OTTO MUNKEL") < 0.8
    assert name_similarity("MF PLAZA MAYOR 1", "MUFA PLAZA MAYOR 2") < 0.8       # numbers must be equal
    assert name_similarity("MF DE CORTE", "MUFA DE CORTE") == 0.0                # generic names never match


def test_augusto_munkel_nearby_does_not_match_casa_gerencia(tmp_path):
    db = _db(tmp_path / "r.db", nodes=[(10, "MF AUGUSTO MUNKEL", 12.0950, -86.2210, "Zona")],
             appearances=[(10, 1, "red")])
    origin = find_traffic_origin(db, [KMZ], RULES)
    assert origin.node is None and origin.path == [] and origin.match_method == "e"
    assert origin.diagnostico["casos"] == ["no_diagramada"]
    assert "150 m" in origin.reason and "no aparece en ningún diagrama" in origin.reason


# --------------------------------------------------------------------------- case c

def test_similar_node_farther_than_150_m_is_low_confidence(tmp_path):
    db = _db(tmp_path / "r.db",
             nodes=[(10, "MUFA CASA GERENCIA OTTO MUNKEL", 12.0950, KMZ.lon, "Zona"),   # ~433 m
                    (11, "MF LABEL", 12.0940, KMZ.lon, "Zona")],
             links=[(10, 11)], services=[(11, "OLT GALERIAS PTO 2")], appearances=[(10, 1, "red")])
    origin = find_traffic_origin(db, [KMZ], RULES)
    assert origin.match_method == "c"
    assert (origin.node, origin.confidence) == ("OLT GALERÍAS", "baja")
    assert origin.path == ["MUFA CASA GERENCIA OTTO MUNKEL", "MF LABEL"]
    assert origin.path_traced is False and origin.origin_mufa is None
    assert origin.diagnostico["caso"] == "a_mayor_distancia"
    assert "MUFA CASA GERENCIA OTTO MUNKEL a 433 m" in origin.diagnostico["detalle"]
    assert origin.name_match["similitud"] == 1.0 and round(origin.name_match["distancia_m"]) == 433
    assert origin.connection_match["method"] == "c" and origin.connection_match["exact"] is False


def test_similar_node_beyond_max_distance_is_only_diagnosed(tmp_path):
    db = _db(tmp_path / "r.db", nodes=[(10, "MUFA CASA GERENCIA OTTO MUNKEL", 12.1300, -86.2210, "Zona")])
    origin = find_traffic_origin(db, [KMZ], RULES)   # ~3.5 km away
    assert origin.node is None and origin.match_method == "e"
    assert origin.diagnostico["caso"] == "a_mayor_distancia"


def test_name_match_disabled_keeps_only_the_diagnosis(tmp_path):
    rules = {"traffic_origin": {**RULES["traffic_origin"], "name_match": {**NAME_MATCH, "enabled": False}}}
    origin = find_traffic_origin(_otto_munkel(tmp_path), [KMZ], rules)
    assert origin.node is None and origin.path == [] and origin.match_method == "e"
    assert origin.diagnostico["casos"] == ["sin_coordenada_en_visio", "marcada_validar"]


def test_reserva_is_diagnosed_and_never_matched_by_name(tmp_path):
    reserva = ChainPoint("RVA CASA GERENCIA OTTO MUNKEL", KMZ.lat, KMZ.lon, "reserva")
    origin = find_traffic_origin(_otto_munkel(tmp_path), [reserva], RULES)
    assert origin.node is None and origin.match_method == "e"
    assert origin.diagnostico["caso"] == "es_reserva" and "mufa nueva" in origin.diagnostico["detalle"]


# --------------------------------------------------------------------------- cases a and b unchanged

def test_cases_a_and_b_behave_as_before(tmp_path):
    # A text with the exact name in a diagram must not change a coordinate match.
    db = _db(tmp_path / "r.db",
             nodes=[(10, "MF CERCA", KMZ.lat + 0.0002, KMZ.lon, "Zona"),           # ~22 m
                    (11, "MF ETIQUETA", KMZ.lat + 0.0012, KMZ.lon, "Zona")],
             links=[(10, 11)], services=[(11, "OLT GALERIAS")], appearances=[(10, 1, "red")],
             texts=[(1, 5.0, 5.0, "MUFA - CASA GERENCIA OTTO MUNKEL", "nodo_sin_coord")])
    a = find_traffic_origin(db, [KMZ], RULES)
    assert (a.match_method, a.node, a.confidence, a.path) == ("a", "OLT GALERÍAS", "media", ["MF CERCA", "MF ETIQUETA"])
    assert a.path_traced is True and a.origin_mufa == "MF ETIQUETA" and a.diagnostico is None
    assert a.connection_match == {"name": "MF CERCA", "distance_m": 22.2, "exact": True}

    b_point = ChainPoint(KMZ.nombre, KMZ.lat - 0.0008, KMZ.lon, "mufa")           # MF CERCA ~111 m away
    b = find_traffic_origin(db, [b_point], RULES)
    assert (b.match_method, b.node, b.confidence) == ("b", "OLT GALERÍAS", "baja")
    assert b.path_traced is False and b.connection_match["exact"] is False and b.diagnostico is None


# --------------------------------------------------------------------------- viewer: fusion route

def test_fusion_route_marks_the_stop_matched_by_name_with_its_diagram(tmp_path):
    from visor_rutas import fusion
    db = _otto_munkel(tmp_path)
    origin = find_traffic_origin(db, [KMZ], RULES)
    origen_trafico = {"nodo": origin.node, "camino": origin.path, "motivo": origin.reason,
                      "metodo": origin.match_method, "emparejamiento": origin.name_match,
                      "diagnostico": origin.diagnostico}
    paradas = fusion.ruta_fusion(origen_trafico, {"lat": KMZ.lat, "lon": KMZ.lon}, archivo_sqlite=db)

    assert [p["nombre"] for p in paradas] == ["MUFA PLAZA MAYOR 2 IDEAY", "MUFA - CASA GERENCIA OTTO MUNKEL"]
    plaza, otto = paradas
    assert (plaza["identificacion"], plaza["emparejado_por_nombre"]) == ("exacta", False)
    assert otto["es_conexion"] and otto["identificacion"] == "por_nombre" and otto["emparejado_por_nombre"]
    assert otto["nodo_id"] is None and otto["lat"] is None
    assert [(a["rol"], a["md5"], a["diagrama"]) for a in otto["archivos"]] == [("por_nombre", f"{1:032d}", True)]
    assert any("VALIDAR EXISTENCIA" in n for n in otto["notas"])


def test_empty_fusion_route_warning_shows_the_diagnosis(tmp_path):
    from visor_rutas import fusion
    db = _db(tmp_path / "r.db")
    origin = find_traffic_origin(db, [KMZ], RULES)
    avisos = []
    assert fusion.ruta_fusion({"camino": [], "motivo": origin.reason, **{"diagnostico": origin.diagnostico}},
                              {"lat": KMZ.lat, "lon": KMZ.lon}, archivo_sqlite=db, avisos=avisos) == []
    assert "no aparece en ningún diagrama Visio" in avisos[0]
    assert set(asdict(origin)) >= {"match_method", "diagnostico", "name_match"}   # in the API's traffic_origin
