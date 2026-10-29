"""La ruta de cada presupuesto en «Mis lugares» (visor_rutas/redes/lugares_presupuesto.py) y su enganche en main._ruta_a_lugares."""
import pytest

import main
from test_visor_presupuesto import entorno  # noqa: F401  (fixture)
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import lugares, lugares_presupuesto, usuarios

RUTA = [(12.1000, -86.2500), (12.1010, -86.2500), (12.1010, -86.2490)]


@pytest.fixture
def jan(con_redes):
    return con_redes, usuarios.identificar(con_redes, usuario_windows="jan")


def _rutas(con, actor):
    arbol = lugares.arbol(con, actor)
    carpetas = {c["id"]: c["nombre"] for c in arbol["carpetas"]}
    return [(carpetas[e["carpeta_id"]], e["nombre"], e["tipo"], e["geom"]["coordinates"], e["estilo"]) for e in arbol["elementos"]]


def test_the_name_is_the_client_code_plus_the_client_name():
    assert lugares_presupuesto.nombre_ruta("C23839", "Constructores  Unidos") == "C23839_Constructores Unidos"
    assert lugares_presupuesto.nombre_ruta("Ferreteria", "ferreteria") == "Ferreteria"          # the viewer's form uses the name as the code
    assert lugares_presupuesto.nombre_ruta("", "Solo nombre") == "Solo nombre"


def test_the_route_is_saved_in_a_presupuestos_folder_and_refreshed_when_untouched(jan):
    con, actor = jan
    r = lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=RUTA, descripcion="Ticket T1", propiedades={"ticket": "T1"})
    assert r["accion"] == "creada"
    carpeta, nombre, tipo, coords, estilo = _rutas(con, actor)[0]
    assert (carpeta, nombre, tipo) == ("Presupuestos", "C1_Cliente", "ruta") and coords[0] == [-86.25, 12.1] and len(coords) == 3 and estilo["linea"]["color"] == "#ffd400"
    # the same budget again with another route and nobody touched it: replaced, not repeated
    otra = RUTA + [(12.1010, -86.2480)]
    assert lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=otra)["accion"] == "actualizada"
    rutas = _rutas(con, actor)
    assert len(rutas) == 1 and len(rutas[0][3]) == 4


def test_a_route_edited_by_hand_is_kept_and_the_new_one_goes_beside_it(jan):
    con, actor = jan
    r = lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=RUTA)
    lugar = lugares.obtener(con, actor, id=r["id"])["lugar"]
    editada = [[-86.25, 12.1], [-86.2495, 12.1005], [-86.249, 12.101]]                       # the user moved a vertex
    lugares.guardar_lugar(con, actor, id=r["id"], version=lugar["version"], geom={"type": "LineString", "coordinates": editada})
    nueva = lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=RUTA + [(12.1010, -86.2480)])
    assert nueva["accion"] == "aparte" and nueva["nombre"] == "C1_Cliente (2)"
    nombres = sorted(n for _, n, *_ in _rutas(con, actor))
    assert nombres == ["C1_Cliente", "C1_Cliente (2)"]
    assert [x[3] for x in _rutas(con, actor) if x[1] == "C1_Cliente"][0] == editada          # the edited one is intact
    assert lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=RUTA)["nombre"] == "C1_Cliente (3)"


def test_a_route_of_one_point_is_not_saved(jan):
    con, actor = jan
    with pytest.raises(lugares.DatosInvalidos):
        lugares_presupuesto.guardar_ruta(con, actor, nombre="X", puntos=[(12.1, -86.25), (12.1, -86.25)])
    assert _rutas(con, actor) == []


def test_the_budget_hook_saves_for_its_owner_and_never_blocks(monkeypatch):
    import routing
    from types import SimpleNamespace
    req = SimpleNamespace(client_code="C9", client_name="Cliente <9>", ticket_id="T9")
    seg = SimpleNamespace(nombre="MF A", tipo="MUFA")
    ruta = routing.Route(distance_m=1234.5, duration_s=0, points=RUTA)
    llamadas = []
    monkeypatch.setattr(lugares_presupuesto, "guardar_de", lambda quien, **datos: llamadas.append((quien, datos)))
    main._ruta_a_lugares(req, seg, ruta, None)                                                   # nobody to give it to: nothing happens
    assert llamadas == []
    main._ruta_a_lugares(req, seg, ruta, {"usuario_windows": "jan"})
    quien, datos = llamadas[0]
    assert quien == {"usuario_windows": "jan"} and datos["nombre"] == "C9_Cliente <9>" and datos["puntos"] == RUTA
    assert "Ticket T9" in datos["descripcion"] and "1,234 m" in datos["descripcion"] or "1,235 m" in datos["descripcion"]
    assert datos["propiedades"]["ticket"] == "T9"

    def falla(quien, **datos):
        raise RuntimeError("sin base")
    monkeypatch.setattr(lugares_presupuesto, "guardar_de", falla)
    r = main._ruta_a_lugares(req, seg, ruta, {"usuario_windows": "jan"})                      # an error is logged and told, the budget goes on
    assert r["ok"] is False and "sin base" in r["error"]


def test_the_api_owner_comes_from_the_env(monkeypatch):
    monkeypatch.delenv("LUGARES_USUARIO_PRESUPUESTOS", raising=False)
    assert main.dueno_de_la_api() is None
    monkeypatch.setenv("LUGARES_USUARIO_PRESUPUESTOS", " jparamo ")
    assert main.dueno_de_la_api() == {"usuario_windows": "jparamo"}
    monkeypatch.setenv("LUGARES_USUARIO_PRESUPUESTOS", "persona: Ana ")
    assert main.dueno_de_la_api() == {"persona_visor": "Ana"}


def test_the_viewer_form_gives_the_route_to_whoever_generates_it(entorno, monkeypatch):
    """Manual budget or one chosen from a ticket (both use the form): this PC's Windows user; on the server, the person of the key."""
    import getpass
    from test_visor_presupuesto import _campos
    from visor_rutas import ventana_web
    main_, _, _, _ = entorno
    dueños = []
    monkeypatch.setattr(main_, "_ruta_a_lugares", lambda req, seg, route, dueno: dueños.append((req.ticket_id, dueno)))
    api = ventana_web.Api()
    assert api.generar_presupuesto(_campos())["ok"]
    assert api.generar_presupuesto(_campos(), _dueno={"persona_visor": "ana"})["ok"]
    assert dueños[0][1] == {"usuario_windows": getpass.getuser()} and dueños[1][1] == {"persona_visor": "ana"}
