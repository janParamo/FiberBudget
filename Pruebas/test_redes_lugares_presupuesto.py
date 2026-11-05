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
    return [(carpetas[e["carpeta_id"]], e["nombre"], e["tipo"], e["geom"]["coordinates"], e["estilo"]) for e in arbol["elementos"] if e["tipo"] == "ruta"]


def _todo(con, actor, carpeta):
    """{tipo: [(nombre, geometry, propiedades)]} of what a folder of the tree holds."""
    arbol = lugares.arbol(con, actor)
    ids = {c["id"] for c in arbol["carpetas"] if c["nombre"] == carpeta}
    salida: dict[str, list] = {}
    for e in arbol["elementos"]:
        if e["carpeta_id"] in ids:
            salida.setdefault(e["tipo"], []).append((e["nombre"], e["geom"], lugares.obtener(con, actor, id=e["id"])["lugar"]["propiedades"], e["id"]))
    return salida


def test_the_name_is_the_client_code_plus_the_client_name():
    assert lugares_presupuesto.nombre_ruta("C23839", "Constructores  Unidos") == "C23839_Constructores Unidos"
    assert lugares_presupuesto.nombre_ruta("Ferreteria", "ferreteria") == "Ferreteria"          # the viewer's form uses the name as the code
    assert lugares_presupuesto.nombre_ruta("", "Solo nombre") == "Solo nombre"


def test_the_route_is_saved_in_a_presupuestos_folder_and_refreshed_when_untouched(jan):
    con, actor = jan
    r = lugares_presupuesto.guardar_ruta(con, actor, nombre="C1_Cliente", puntos=RUTA, descripcion="Ticket T1", propiedades={"ticket": "T1"})
    assert r["accion"] == "creada"
    carpeta, nombre, tipo, coords, estilo = _rutas(con, actor)[0]
    assert (carpeta, nombre, tipo) == ("C1_Cliente", "C1_Cliente", "ruta") and coords[0] == [-86.25, 12.1] and len(coords) == 3 and estilo["linea"]["color"] == "#ffd400"
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
    monkeypatch.setattr(main_, "_ruta_a_lugares", lambda req, seg, route, dueno, extra=None: dueños.append((req.ticket_id, dueno)))
    api = ventana_web.Api()
    assert api.generar_presupuesto(_campos())["ok"]
    assert api.generar_presupuesto(_campos(), _dueno={"persona_visor": "ana"})["ok"]
    assert dueños[0][1] == {"usuario_windows": getpass.getuser()} and dueños[1][1] == {"persona_visor": "ana"}


# --------------------------------------------------------------------------- the client point, the drop and the new poles

CLIENTE = {"lat": 12.1011, "lon": -86.2485, "nombre": "Constructores Unidos", "codigo": "C23839"}
POSTES = [(12.1005, -86.2500), (12.1010, -86.2495), (12.1010, -86.2490)]                  # new poles along the route


def _con_todo(con, actor, **extra):
    return lugares_presupuesto.guardar_ruta(con, actor, nombre="C23839_Constructores Unidos", puntos=RUTA, cliente=CLIENTE, postes_nuevos=POSTES, **extra)


def test_the_budget_folder_keeps_the_route_the_exact_client_point_the_drop_and_the_new_poles(jan):
    con, actor = jan
    r = _con_todo(con, actor)
    assert r["accion"] == "creada" and r["postes_nuevos"] == 3
    todo = _todo(con, actor, "C23839_Constructores Unidos")
    assert sorted(todo) == ["cable", "cliente", "poste", "ruta"]
    (_, geom, _, cliente_id), = todo["cliente"]
    assert geom["coordinates"] == [-86.2485, 12.1011]                                         # the exact point of the client
    assert [p[1]["coordinates"] for p in todo["poste"]] == [[-86.25, 12.1005], [-86.2495, 12.101], [-86.249, 12.101]]
    assert sorted(p[0] for p in todo["poste"]) == ["Poste nuevo 1", "Poste nuevo 2", "Poste nuevo 3"]
    (nombre, geom, props, _), = todo["cable"]
    assert nombre == "Acometida" and props["clase"] == "acometida" and props["destino_id"] == cliente_id
    assert geom["coordinates"] == [RUTA[-1][::-1] and [-86.249, 12.101], [-86.2485, 12.1011]]       # from the end of the route to the client
    ruta = todo["ruta"][0][2]
    assert ruta["cliente_id"] == cliente_id and len(ruta["postes_nuevos"]) == 3 and ruta["acometida_m"] > 40 and ruta["cliente_punto"] == {"lat": 12.1011, "lon": -86.2485}
    assert [x[3] for x in todo["poste"]] == ruta["postes_nuevos"]


def test_no_drop_when_the_route_ends_on_the_client_and_no_client_means_only_the_route(jan):
    con, actor = jan
    lugares_presupuesto.guardar_ruta(con, actor, nombre="A", puntos=RUTA, cliente={"lat": RUTA[-1][0], "lon": RUTA[-1][1], "nombre": "Pegado"})
    assert sorted(_todo(con, actor, "A")) == ["cliente", "ruta"]                              # the client is there, but there is no drop to draw
    lugares_presupuesto.guardar_ruta(con, actor, nombre="B", puntos=RUTA)
    assert sorted(_todo(con, actor, "B")) == ["ruta"]                                         # as before: just the route
    lugares_presupuesto.guardar_ruta(con, actor, nombre="C", puntos=RUTA, cliente={**CLIENTE, "codigo": "no es un codigo"})
    assert _todo(con, actor, "C")["cliente"][0][2].get("codigo") is None                      # a code that is not C#### does not stop the save


def test_generating_again_replaces_the_poles_of_an_untouched_route(jan):
    con, actor = jan
    _con_todo(con, actor)
    antes = {p[3] for p in _todo(con, actor, "C23839_Constructores Unidos")["poste"]}
    r = lugares_presupuesto.guardar_ruta(con, actor, nombre="C23839_Constructores Unidos", puntos=RUTA, cliente=CLIENTE, postes_nuevos=POSTES[:2])
    assert r["accion"] == "actualizada"
    todo = _todo(con, actor, "C23839_Constructores Unidos")
    assert len(todo["poste"]) == 2 and not antes & {p[3] for p in todo["poste"]}               # the old ones are gone, not left behind
    assert len(todo["cliente"]) == 1 and len(todo["cable"]) == 1 and len(todo["ruta"]) == 1   # one of each, nothing duplicated
    assert len(todo["ruta"][0][2]["postes_nuevos"]) == 2


def test_editing_the_route_deletes_the_new_poles_it_no_longer_uses_and_moves_the_drop(jan):
    con, actor = jan
    r = _con_todo(con, actor)
    lugar = lugares.obtener(con, actor, id=r["id"])["lugar"]
    # the route now goes another way: a block north, far from the three poles it had, and ends elsewhere
    nueva = [[-86.2500, 12.1100], [-86.2495, 12.1105], [-86.2490, 12.1110]]
    lugares.guardar_lugar(con, actor, id=r["id"], version=lugar["version"], geom={"type": "LineString", "coordinates": nueva})
    todo = _todo(con, actor, "C23839_Constructores Unidos")
    assert "poste" not in todo                                                                # none of the new poles is used any more: deleted by themselves
    ruta = todo["ruta"][0][2]
    assert ruta["postes_nuevos"] == [] and ruta["huella"] and ruta["cliente_punto"] == {"lat": 12.1011, "lon": -86.2485}
    (_, geom, props, _), = todo["cable"]
    assert geom["coordinates"][0] == [-86.249, 12.111] and geom["coordinates"][1] == [-86.2485, 12.1011]   # the drop follows the new end of the route
    assert ruta["acometida_m"] > 900 and len(todo["cliente"]) == 1                            # and the client point stays where it was


def test_editing_the_route_keeps_the_poles_it_still_uses(jan):
    con, actor = jan
    r = _con_todo(con, actor)
    lugar = lugares.obtener(con, actor, id=r["id"])["lugar"]
    # a vertex added and moved about 10 m: the poles are still on the way (within the pole buffer of the rules)
    editada = [[-86.25, 12.1], [-86.2499, 12.1005], [-86.25, 12.1010], [-86.2490, 12.1010]]
    lugares.guardar_lugar(con, actor, id=r["id"], version=lugar["version"], geom={"type": "LineString", "coordinates": editada})
    todo = _todo(con, actor, "C23839_Constructores Unidos")
    assert len(todo["poste"]) == 3 and len(todo["ruta"][0][2]["postes_nuevos"]) == 3
    # a route that is not of a budget is never touched by this
    otra = lugares.guardar_lugar(con, actor, carpeta_id=lugares.arbol(con, actor)["carpetas"][0]["id"], tipo="ruta", nombre="Mia", geom={"type": "LineString", "coordinates": [[-86.2, 12.0], [-86.19, 12.0]]})
    lugares.guardar_lugar(con, actor, id=otra["lugar"]["id"], version=otra["lugar"]["version"], geom={"type": "LineString", "coordinates": [[-86.2, 12.0], [-86.18, 12.0]]})


def test_the_summary_of_an_edit_in_progress_says_what_would_be_deleted(jan):
    con, actor = jan
    r = _con_todo(con, actor)
    saved = lugares_presupuesto.resumen_ruta(con, actor, id=r["id"])["resumen"]
    assert saved["postes_guardados"] == 3 and saved["postes_guardados_usados"] == 3 and saved["postes_a_borrar"] == []
    assert saved["acometida_m"] > 40 and saved["distancia_m"] > 200
    lejos = lugares_presupuesto.resumen_ruta(con, actor, id=r["id"], puntos=[[12.1100, -86.2500], [12.1110, -86.2490]])["resumen"]      # nothing saved: the same ids, not yet deleted
    assert lejos["postes_guardados_usados"] == 0 and len(lejos["postes_a_borrar"]) == 3 and lejos["acometida_m"] > 900
    assert len(_todo(con, actor, "C23839_Constructores Unidos")["poste"]) == 3                 # a summary writes nothing
    with pytest.raises(lugares.DatosInvalidos):
        lugares_presupuesto.resumen_ruta(con, actor, id=r["id"], puntos=[[12.1, -86.25]])
    otra = lugares.guardar_lugar(con, actor, carpeta_id=lugares.arbol(con, actor)["carpetas"][0]["id"], tipo="ruta", nombre="Mia", geom={"type": "LineString", "coordinates": [[-86.2, 12.0], [-86.19, 12.0]]})
    with pytest.raises(lugares.DatosInvalidos):
        lugares_presupuesto.resumen_ruta(con, actor, id=otra["lugar"]["id"])


def test_the_budget_hook_sends_the_client_point_and_the_new_poles(monkeypatch):
    import routing
    from types import SimpleNamespace
    req = SimpleNamespace(client_code="C9", client_name="Cliente", ticket_id="T9", latitude=12.1011, longitude=-86.2485)
    ruta = routing.Route(distance_m=250.0, duration_s=0, points=RUTA)
    llamadas = []
    monkeypatch.setattr(lugares_presupuesto, "guardar_de", lambda quien, **datos: llamadas.append(datos))
    main._ruta_a_lugares(req, SimpleNamespace(nombre="MF A", tipo="MUFA"), ruta, {"usuario_windows": "jan"},
                         {"postes_nuevos": [(12.1005, -86.25)], "propiedades": {"metraje_final_m": 300.0, "reserva_m": 50.0}})
    datos = llamadas[0]
    assert datos["cliente"] == {"lat": 12.1011, "lon": -86.2485, "nombre": "Cliente", "codigo": "C9"} and datos["postes_nuevos"] == [(12.1005, -86.25)]
    assert datos["propiedades"]["metraje_final_m"] == 300.0 and datos["propiedades"]["reserva_m"] == 50.0 and datos["propiedades"]["ticket"] == "T9"
