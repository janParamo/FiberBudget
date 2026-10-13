"""The viewer page must not repeat an id: document.getElementById returns only the first one, so a
repeated id silently sends one module's code to another module's element (it happened with
"modal-diagrama": the Visio full-screen viewer opened the logical diagram)."""
import collections
import re
from pathlib import Path

PAGINA = Path(__file__).resolve().parents[1] / "visor_rutas" / "web" / "visor.html"


def test_no_repeated_ids():
    ids = re.findall(r'\bid="([^"]+)"', PAGINA.read_text(encoding="utf-8"))
    repetidos = {i: n for i, n in collections.Counter(ids).items() if n > 1}
    assert repetidos == {}
