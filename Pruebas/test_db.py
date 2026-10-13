from types import SimpleNamespace

import pytest

import db


class _FakeConnection:
    def __init__(self, mufa_row, rows=None):
        self.mufa_row = mufa_row
        self.rows = rows or []
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.queries.append((query, params))
        return SimpleNamespace(
            fetchone=lambda: self.mufa_row if len(self.queries) == 1 else None,
            fetchall=lambda: self.rows,
        )


class _SequenceConnection(_FakeConnection):
    """Returns one fetchone() row per query, in order."""

    def __init__(self, rows_by_query):
        super().__init__(None)
        self.rows_by_query = list(rows_by_query)

    def execute(self, query, params):
        self.queries.append((query, params))
        row = self.rows_by_query[len(self.queries) - 1]
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [])


def _patch_db(monkeypatch, fake):
    monkeypatch.setattr(db.psycopg, "connect", lambda **kwargs: fake)
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(
        db_host="host", db_port=5432, db_name="db", db_user="user", db_password="password"))


def test_mufa_within_radius_is_selected_first(monkeypatch):
    fake = _SequenceConnection([(17, "mufa", 12.1, -86.2, 40.0, " MUFA REBECA ")])
    _patch_db(monkeypatch, fake)

    selected = db.find_nearest_connection_point(12.2, -86.2, ["mal estado"], 500)

    assert selected.is_mufa is True and selected.is_reserve is False
    assert selected.nombre == "MUFA REBECA"
    assert (selected.lat, selected.lon) == (12.1, -86.2)
    assert len(fake.queries) == 1
    assert fake.queries[0][1]["tipos"] == ["mufa%"]
    assert fake.queries[0][1]["radius_m"] == 500


def test_reserve_within_radius_is_used_when_no_mufa(monkeypatch):
    fake = _SequenceConnection([None, (30, "reserva", 12.1, -86.2, 120.0, "RVA CLIENTE")])
    _patch_db(monkeypatch, fake)

    selected = db.find_nearest_connection_point(12.2, -86.2, [], 500)

    assert selected.is_reserve is True and selected.is_mufa is False
    assert fake.queries[1][1]["tipos"] == ["reserva%"]
    assert fake.queries[1][1]["radius_m"] == 500


def test_nearest_point_without_limit_and_never_a_line(monkeypatch):
    fake = _SequenceConnection([None, None, (40, "mufa", 12.3, -86.3, 2400.0, None)])
    _patch_db(monkeypatch, fake)

    selected = db.find_nearest_connection_point(12.2, -86.2, [], 500)

    assert selected.is_mufa is True and selected.nombre is None
    assert fake.queries[2][1]["tipos"] == ["mufa%", "reserva%"]
    assert fake.queries[2][1]["radius_m"] is None
    assert all("red_lineas" not in query for query, _ in fake.queries)


def test_no_mufa_or_reserve_raises(monkeypatch):
    _patch_db(monkeypatch, _SequenceConnection([None, None, None]))
    with pytest.raises(db.NoSegmentFound):
        db.find_nearest_connection_point(12.2, -86.2, [], 500)


class _GraphConnection(_FakeConnection):
    """Fake mufa graph: answers neighbor and distribution queries from dicts."""

    def __init__(self, neighbors, distribution):
        super().__init__(None)
        self.neighbors, self.distribution = neighbors, distribution

    def execute(self, query, params):
        self.queries.append((query, params))
        if "regexp_matches" in query:
            rows = [(mid, self.distribution[mid]) for mid in params["ids"] if mid in self.distribution]
        else:
            rows = self.neighbors.get(params["mufa_id"], [])
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None)


CHAIN_RULES = {"line_tolerance_m": 5, "max_hops": 6, "distribution_min_fibers": 24,
               "distribution_line_tipos": ["troncal%"]}


def test_upstream_chain_walks_to_first_distribution_mufa(monkeypatch):
    graph = {
        1: [(2, "MF KAREN BERMUDEZ", 74.0)],
        2: [(1, "MUFA REBECA", 74.0), (3, "MF CACIQUE", 233.0), (4, "MF LEJOS", 500.0)],
    }
    _patch_db(monkeypatch, _GraphConnection(graph, distribution={3: "cable_24h", 4: "linea_troncal"}))

    chain = db.find_upstream_mufa_chain(1, "MUFA REBECA", [], CHAIN_RULES)

    assert [(m.id, m.nombre) for m in chain] == [
        (1, "MUFA REBECA"), (2, "MF KAREN BERMUDEZ"), (3, "MF CACIQUE")]
    assert [m.distribution_reason for m in chain] == [None, None, "cable_24h"]


def test_upstream_chain_is_just_the_mufa_when_it_is_distribution_or_isolated(monkeypatch):
    _patch_db(monkeypatch, _GraphConnection({}, distribution={1: "mufa_troncal"}))
    chain = db.find_upstream_mufa_chain(1, "A", [], CHAIN_RULES)
    assert [(m.id, m.distribution_reason) for m in chain] == [(1, "mufa_troncal")]
    _patch_db(monkeypatch, _GraphConnection({}, distribution={}))
    chain = db.find_upstream_mufa_chain(1, "A", [], CHAIN_RULES)
    assert [(m.id, m.distribution_reason) for m in chain] == [(1, None)]


def test_distribution_rules_keep_24h_first_and_use_word_boundaries(monkeypatch):
    fake = _GraphConnection({}, distribution={})
    _patch_db(monkeypatch, fake)
    db.find_upstream_mufa_chain(1, "A", [], {**CHAIN_RULES, "distribution_keywords": ["TRONCAL", "BACKBONE"]})
    query, params = fake.queries[0]
    assert query.index("'cable_24h'") < query.index("'linea_troncal'") < query.index("'mufa_troncal'")
    assert params["trunk_words"] == r"\m(TRONCAL|BACKBONE)\M"


def test_reserve_poles_are_in_existing_pole_query(monkeypatch):
    fake = _FakeConnection(None)
    monkeypatch.setattr(db.psycopg, "connect", lambda **kwargs: fake)
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(
        db_host="host", db_port=5432, db_name="db", db_user="user", db_password="password"))

    assert db.find_existing_poles_near_route("LINESTRING(-86.2 12.1,-86.2 12.2)", 15) == []
    assert "reserva" in fake.queries[0][0].casefold()


def test_duplicate_pole_records_count_once_but_distinct_poles_at_route_end_count_twice():
    poles = [
        # Shoeless: two real poles ~13 m apart, both beyond the route end (same projection).
        db.ExistingPole(id=7799, lat=12.119886, lon=-86.262610, route_position_m=149.91),
        db.ExistingPole(id=13509, lat=12.119966, lon=-86.262524, route_position_m=149.91),
        # The same pole loaded twice (0.5 m apart).
        db.ExistingPole(id=1, lat=12.120226, lon=-86.263040, route_position_m=88.82),
        db.ExistingPole(id=2, lat=12.1202305, lon=-86.263040, route_position_m=88.82),
    ]

    unique = db.deduplicate_existing_poles(poles)

    assert [pole.id for pole in unique] == [7799, 13509, 1]


def test_route_mufas_returns_all_intermediate_mufas(monkeypatch):
    fake = _FakeConnection(None, [
        (15, "mufa", 12.1, -86.2, 5.0, True),
        (16, "mufa", 12.11, -86.21, 8.0, False),
        (17, "mufa", 12.12, -86.22, 10.0, True),
        (18, "mufa", 12.13, -86.23, 12.0, False),
    ])
    monkeypatch.setattr(db.psycopg, "connect", lambda **kwargs: fake)
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(
        db_host="host", db_port=5432, db_name="db", db_user="user", db_password="password"))
    mufas = db.find_mufas_near_route(
        "LINESTRING(-86.2 12.1,-86.23 12.13)", 15, ["sin info"])

    assert len(mufas) == 4
    assert sum(mufa.is_backbone for mufa in mufas) == 2