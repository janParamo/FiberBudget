"""El icono de Fiber Budget: el .ico trae todos los tamaños de Windows y la ventana lo pone sin romperse si algo falla."""
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import icono_fiber_budget  # noqa: E402

from visor_rutas import ventana_web  # noqa: E402


def test_the_icon_file_has_every_size_windows_uses(tmp_path):
    destino = icono_fiber_budget.guardar(tmp_path / "x.ico")
    with Image.open(destino) as ico:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    assert ventana_web.ICONO.is_file()                                                              # the one the window and the shortcut use is in the repo
    with Image.open(ventana_web.ICONO) as ico:
        assert (256, 256) in ico.info["sizes"]


def test_the_window_icon_helpers_never_break_the_viewer():
    ventana_web.identidad_windows()                                                                 # does not raise on any system
    assert ventana_web._icono_en_ventana("Una ventana que no existe - Fiber Budget", espera_s=0.3) is False      # no such window: gives up, never waits for it
    ventana_web.poner_icono("Una ventana que no existe - Fiber Budget")                             # in its own thread: returns at once
    import inspect
    assert "Icon(" not in inspect.getsource(ventana_web.poner_icono) and "native" not in inspect.getsource(ventana_web._icono_en_ventana)   # never touches the window from here
