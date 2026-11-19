"""Fixtures shared by every test of the folder."""
import pytest


@pytest.fixture(autouse=True)
def _sin_ngrok(monkeypatch):
    """The real .env carries NGROK_AUTHTOKEN / NGROK_DOMAIN: a test that starts the app (its lifespan) would open the tunnel of the VM from this PC, spend its bandwidth
    and take the address down there (ERR_NGROK_334 / 725). No test opens a tunnel: ngrok is replaced by one that does nothing."""
    try:
        import ngrok
    except Exception:                                               # noqa: BLE001
        return

    class _Tunel:
        def url(self) -> str:
            return "https://sin-tunel.invalid"

    async def _forward(*args, **kwargs):
        return _Tunel()

    async def _disconnect(*args, **kwargs):
        return None

    monkeypatch.setattr(ngrok, "forward", _forward)
    monkeypatch.setattr(ngrok, "disconnect", _disconnect)


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
def _sin_lineas_reales(monkeypatch, request):
    """The fibre lines that guide the routes (ruta_red) and the KMZ nodes (Metro) come from PostGIS: no test asks the real database for them.
    Tests of those replace these."""
    if "lineas_reales" in request.keywords:
        return
    try:
        import db
    except Exception:                                               # noqa: BLE001
        return
    monkeypatch.setattr(db, "find_lineas_en_caja", lambda *a, **k: [])
    monkeypatch.setattr(db, "find_nearest_nodo", lambda *a, **k: None)


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


@pytest.fixture(autouse=True)
def _respaldos_en_carpeta_temporal(monkeypatch, tmp_path_factory):
    """The .env points the backups to a real folder (the user's Respaldos): no test writes there (a test can still set its own folder)."""
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path_factory.mktemp("respaldos_pruebas")))
    monkeypatch.delenv("REDES_RESPALDOS_CONSERVAR", raising=False)


@pytest.fixture(autouse=True)
def _sin_almacen_real(monkeypatch, request):
    """The files store (redes.almacen_archivos) lives in the real Presupuesto_visio: no test writes there. Tests of the store use the `almacen_pruebas` fixture."""
    if "almacen_pruebas" in request.fixturenames:
        return
    try:
        from visor_rutas import almacen_archivos
    except Exception:                                               # noqa: BLE001
        return
    monkeypatch.setattr(almacen_archivos, "ACTIVO", False)
