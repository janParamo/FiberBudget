"""Fixtures shared by every test of the folder."""
import pytest


@pytest.fixture(autouse=True)
def _sin_pozos_reales(monkeypatch, request):
    """The route's wells come from PostGIS (red_puntos): no test asks the real database for them. Tests of the wells replace this."""
    if "pozos_reales" in request.keywords:
        return
    try:
        import db
    except Exception:                                               # noqa: BLE001 - a test that cannot import db does not need the patch
        return
    monkeypatch.setattr(db, "find_pozos_near_route", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _sin_guardar_splitters(monkeypatch, request):
    """Generating a route stores the splitters it read in the redes database: no test writes to the real one (tests of that module replace this)."""
    if "guardar_splitters" in request.keywords:
        return
    try:
        from visor_rutas import splitters_diagrama
    except Exception:                                               # noqa: BLE001
        return
    monkeypatch.setattr(splitters_diagrama, "guardar_en_redes", lambda splitters: {})
