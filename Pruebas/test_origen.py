"""Traffic-origin lookup over a small red_fibra.db built from the real schema."""
import sqlite3
from pathlib import Path

import pytest

from origen import ChainPoint, _AliasMatcher, find_traffic_origin

SCHEMA = Path(__file__).resolve().parent.parent / "red_fibra" / "schema.sql"
RULES = {"traffic_origin": {
    "match_radius_m": 40, "fallback_radius_m": 150, "max_hops": 8, "media_max_hops": 3,
    "saturated_text_distance_cm": 3, "ignore_label_words": ["RESPALDO", "REDUNDAN"],
    "nodes": {"Nodo Villa Fontana": ["VILLA FONTANA", "VF"], "Mini Nodo Galerías": ["GALERIAS", "GALERIA"],
              "Nodo La Merced": ["LA MERCED", "MERCED"], "Nodo Santo Domingo": ["SANTO DOMINGO", "SD"],
              "Nodo Consovipe": ["CONSOVIPE"], "Nodo La Gruta": ["LA GRUTA", "GRUTA"]},
}}
# Mufas ~110 m apart along a meridian: (id, name, lat, zona)
LAT0, LON = 12.1100, -86.2600


def _build(path: Path, mufas, links, services, texts=(), zona="Mufas sueltas") -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("INSERT INTO importaciones (id, fecha, carpeta_origen) VALUES (1, '2026-10-05', 'x')")
    con.execute("""INSERT INTO archivos (id, importacion_id, ruta_relativa, nombre, formato, md5, estado)
                   VALUES (1, 1, 'Zona/diagrama.vsd', 'diagrama.vsd', 'vsd', 'x', 'ok')""")
    for node_id, name, lat in mufas:
        con.execute("INSERT INTO nodos (id, nombre, nombre_normalizado, tipo, lat, lon, zona) "
                    "VALUES (?, ?, ?, 'MUFA', ?, ?, ?)", (node_id, name, name.upper(), lat, LON, zona))
    for a, b in links:
        con.execute("INSERT INTO enlaces (nodo_a_id, nodo_b_id, fuente, confianza) VALUES (?, ?, 'visio_mufa', 'media')",
                    (a, b))
    for node_id, text in services:
        con.execute("INSERT INTO servicios (nodo_id, archivo_id, tipo, descripcion) VALUES (?, 1, 'splitter', ?)",
                    (node_id, text))
    for node_id, text, x, y in texts:   # node_id None: free text in the diagram
        con.execute("INSERT INTO textos_crudos (archivo_id, x_cm, y_cm, texto) VALUES (1, ?, ?, ?)", (x, y, text))
        if node_id is not None:
            con.execute("INSERT INTO nodo_apariciones (nodo_id, archivo_id, rol, texto_original) "
                        "VALUES (?, 1, 'principal', ?)", (node_id, text))
    con.commit()
    con.close()
    return path


@pytest.mark.parametrize("label, node", [
    ("SPL 1X16 -23.21 dBm OLT GALERÍAS Puerto 6", "Mini Nodo Galerías"),
    ("SPL 1X16 -21.4 dBm PUERTO 0/2/3 OLT MERCED", "Nodo La Merced"),
    ("OLT PTO 11 GRUTA", "Nodo La Gruta"),
    ("Puerto del SW Gi1/0/46 Nodo SD", "Nodo Santo Domingo"),
    # the mufa name comes before OLT, and the OLT itself is not named
    ("SPL 1X8 SECUNDARIO EN MF COLEGIO SANTO DOMINGO PUERTO 0/0/0 OLT", None),
    ("C36168 Lesly Marcel Prado Lopez / redundancia Nodo VF", None),
    ("C23586 ACA JOE / Enlace Respaldo -18.63 dBm OLT CONSOVIPE", None),
    ("SPL 1X8 EN MF YAHAIRA MERCEDES PUERTO 0/0/0 OLT", None),
    ("SPL 1X8 PRINCIPAL MUFA TAQUIZA OLT PUERTO 7", None),
])
def test_alias_matcher_reads_node_named_after_olt_or_nodo(label, node):
    matcher = _AliasMatcher(RULES["traffic_origin"]["nodes"], RULES["traffic_origin"]["ignore_label_words"])
    assert matcher.node_in(label) == node


def test_walks_cables_to_nearest_labelled_mufa_and_flags_saturation(tmp_path):
    db = _build(tmp_path / "r.db",
                mufas=[(1, "MF CLIENTE", LAT0), (2, "MF MEDIO", LAT0 + 0.001), (3, "MF CAR", LAT0 + 0.002),
                       (4, "MF LEJOS", LAT0 + 0.003)],
                links=[(1, 2), (2, 3), (3, 4)],
                services=[(3, "OLT VILLA FONTANA PTO 3"), (4, "OLT GALERIAS")],
                texts=[(3, "MF CAR", 10.0, 10.0), (None, "SATURADA", 11.0, 11.5)])
    origin = find_traffic_origin(db, [ChainPoint("MF CLIENTE", LAT0 + 0.0001, LON)], RULES)
    assert origin.node == "Nodo Villa Fontana"
    assert origin.confidence == "media"
    assert origin.path == ["MF CLIENTE", "MF MEDIO", "MF CAR"]
    assert origin.path_traced is True
    assert origin.saturated_mufas == ["MF CAR"]
    assert origin.connection_match["exact"] is True


def test_label_on_connection_mufa_is_high_confidence(tmp_path):
    db = _build(tmp_path / "r.db", mufas=[(1, "MF LOYOLA", LAT0)], links=[],
                services=[(1, "SPL 1X16 PUERTO 0/2/3 OLT MERCED")])
    origin = find_traffic_origin(db, [ChainPoint("MF LOYOLA", LAT0, LON)], RULES)
    assert (origin.node, origin.confidence, origin.saturated_mufas) == ("Nodo La Merced", "alta", [])


def test_postgis_chain_links_mufas_missing_from_visio_cables(tmp_path):
    db = _build(tmp_path / "r.db", mufas=[(1, "MF A", LAT0), (2, "MF B", LAT0 + 0.002)], links=[],
                services=[(2, "OLT GALERIAS")])
    chain = [ChainPoint("MF A", LAT0, LON), ChainPoint("MF B", LAT0 + 0.002, LON)]
    origin = find_traffic_origin(db, chain, RULES)
    assert (origin.node, origin.confidence, origin.path) == ("Mini Nodo Galerías", "media", ["MF A", "MF B"])


def test_two_nodes_at_same_distance_is_low_confidence_with_alternatives(tmp_path):
    db = _build(tmp_path / "r.db",
                mufas=[(1, "MF A", LAT0), (2, "MF NORTE", LAT0 + 0.001), (3, "MF SUR", LAT0 - 0.001)],
                links=[(1, 2), (1, 3)],
                services=[(2, "OLT GALERIAS"), (2, "OLT GALERIAS P5"), (3, "OLT MERCED")])
    origin = find_traffic_origin(db, [ChainPoint("MF A", LAT0, LON)], RULES)
    assert (origin.node, origin.confidence, origin.alternatives) == ("Mini Nodo Galerías", "baja", ["Nodo La Merced"])


def test_folder_name_is_last_low_confidence_fallback(tmp_path):
    db = _build(tmp_path / "r.db", mufas=[(1, "MF REBECA", LAT0)], links=[], services=[],
                zona="Nodo La Gruta  carretera hacia Leon")
    origin = find_traffic_origin(db, [ChainPoint("MUFA REBECA", LAT0, LON)], RULES)
    assert (origin.node, origin.confidence, origin.reason) == (
        "Nodo La Gruta", "baja", "nombre de la carpeta del diagrama")
    assert origin.path_traced is False   # a guess, never used to count mufas


def test_no_database_or_no_nearby_mufa_returns_reason(tmp_path):
    assert find_traffic_origin(tmp_path / "missing.db", [ChainPoint("A", LAT0, LON)], RULES).node is None
    db = _build(tmp_path / "r.db", mufas=[(1, "MF A", LAT0)], links=[], services=[])
    far = find_traffic_origin(db, [ChainPoint("A", LAT0 + 0.01, LON)], RULES)   # ~1.1 km away
    assert far.node is None and "150 m" in far.reason
