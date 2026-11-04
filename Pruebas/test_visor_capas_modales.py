"""The dialogs opened from the mufa editor must stack above it, or they open behind it and the button seems to do nothing."""
import re
from pathlib import Path

CSS = re.sub(r"/\*.*?\*/", "",(Path(__file__).resolve().parent.parent / "visor_rutas" / "web" / "redes" / "redes.css").read_text(encoding="utf-8"), flags=re.S)


def _capa(modal: str) -> int:
    for regla in re.finditer(r"([^{}]+)\{([^}]*)\}", CSS):
        if modal in [s.strip() for s in regla.group(1).split(",")]:
            z = re.search(r"z-index:\s*(\d+)", regla.group(2))
            if z:
                return int(z.group(1))
    return 0


def test_assign_visio_dialog_is_above_the_mufa_editor():
    assert _capa("#modal-mu-visio") > _capa("#modal-mufa") > 0
