"""Network design module, phase 2: projects (CRUD, hierarchy, users and permissions, image,
location and area, duplicate, logical delete / restore, history, address search) and the
history of viewer budgets in "Presupuestos"."""
import base64
import io
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, proyectos, usuarios

AREA = {"type": "Polygon", "coordinates": [[[-86.30, 12.10], [-86.29, 12.10], [-86.29, 12.11], [-86.30, 12.11], [-86.30, 12.10]]]}


def _png(lado=400, formato="PNG") -> str:
    salida = io.BytesIO()
    Image.new("RGB", (lado, lado), (30, 120, 220)).save(salida, formato)
    return f"data:image/{formato.lower()};base64," + base64.b64encode(salida.getvalue()).decode()


@pytest.fixture
def gente(con_redes):
    admin = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    editor = usuarios.guardar(con_redes, admin, datos={"nombre": "Marlon", "rol": "editor", "persona_visor": "marlon"})["usuario"]
    lector = usuarios.guardar(con_redes, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    otro = usuarios.guardar(con_redes, admin, datos={"nombre": "Otro", "rol": "editor", "persona_visor": "otro"})["usuario"]
    fila = lambda u: con_redes.execute("SELECT * FROM redes.usuarios WHERE id = %s", (u["id"],)).fetchone()
    return con_redes, admin, fila(editor), fila(lector), fila(otro)


def _crear(con, actor, **datos):
    return proyectos.guardar(con, actor, datos={"nombre": "Proyecto", "codigo": "P1", **datos})["proyecto"]


# --------------------------------------------------------------------------- crear / editar

def test_create_with_location_area_image_and_users(gente):
    con, admin, editor, lector, _ = gente
    p = _crear(con, editor, nombre="Residencial Los Robles", codigo="RLR-01", lat=12.105, lon=-86.295,
               area=AREA, imagen=_png(), usuarios=[lector["id"]], descripcion="Fase 1")
    assert (p["codigo"], p["lat"], p["lon"], p["version"]) == ("RLR-01", pytest.approx(12.105), pytest.approx(-86.295), 1)
    assert p["area"]["type"] == "Polygon" and p["area_vertices"] == 4
    assert p["imagen"].startswith("data:image/png;base64,") and p["miniatura"].startswith("data:image/png;base64,")
    mini = Image.open(io.BytesIO(base64.b64decode(p["miniatura"].split(",", 1)[1])))
    assert max(mini.size) <= proyectos.LADO_MINIATURA
    assert {u["nombre"] for u in p["usuarios"]} == {"Marlon", "Ana"}                # creator always assigned
    assert p["puede_editar"] is True


def test_validation_messages(gente):
    con, admin, *_ = gente
    _crear(con, admin, codigo="ABC")
    with pytest.raises(db.DatosInvalidos) as e:
        proyectos.guardar(con, admin, datos={"nombre": "", "codigo": "abc", "lat": 99, "lon": 0, "padre_id": 999})
    assert set(e.value.errores) == {"nombre", "codigo", "ubicacion", "padre_id"}
    assert e.value.errores["codigo"] == "Ya hay un proyecto con ese identificador"     # case-insensitive
    with pytest.raises(db.DatosInvalidos) as e:
        proyectos.guardar(con, admin, datos={"nombre": "X", "codigo": "con espacio"})
    assert "codigo" in e.value.errores
    corbata = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}   # self-intersecting
    with pytest.raises(db.DatosInvalidos, match="cruza"):
        proyectos.guardar(con, admin, datos={"nombre": "X", "codigo": "X1", "area": corbata})


def test_images_are_checked(gente):
    con, admin, *_ = gente
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg onload='alert(1)'/>").decode()
    for mala, texto in ((svg, "no es una imagen"), ("data:image/png;base64,AAAA", "no es una imagen"),
                        ("hola", "Formato no válido")):
        with pytest.raises(db.DatosInvalidos, match=texto):
            proyectos.guardar(con, admin, datos={"nombre": "X", "codigo": "X1", "imagen": mala})
    grande = "data:image/png;base64," + base64.b64encode(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10)).decode()
    with pytest.raises(db.DatosInvalidos, match="máximo es 2 MB"):
        proyectos.guardar(con, admin, datos={"nombre": "X", "codigo": "X1", "imagen": grande})
    p = _crear(con, admin, imagen=_png(formato="JPEG"))
    assert p["imagen"].startswith("data:image/jpeg")
    sin = proyectos.guardar(con, admin, datos={**p, "imagen": None})["proyecto"]       # "Eliminar la imagen"
    assert sin["imagen"] is None and sin["miniatura"] is None
    igual = proyectos.guardar(con, admin, datos={k: v for k, v in sin.items() if k != "imagen"} | {"nombre": "Y"})["proyecto"]
    assert igual["nombre"] == "Y"                                                     # no "imagen" key: unchanged


def test_edit_versions_history_and_hierarchy_without_cycles(gente):
    con, admin, *_ = gente
    raiz = _crear(con, admin, codigo="RAIZ", nombre="Managua")
    hijo = _crear(con, admin, codigo="HIJO", nombre="Los Robles", padre_id=raiz["id"])
    nieto = _crear(con, admin, codigo="NIETO", nombre="Etapa 1", padre_id=hijo["id"])
    assert nieto["padre_nombre"] == "Los Robles"
    with pytest.raises(db.DatosInvalidos, match="subproyecto"):
        proyectos.guardar(con, admin, datos={**raiz, "padre_id": nieto["id"]})
    with pytest.raises(db.DatosInvalidos, match="propio"):
        proyectos.guardar(con, admin, datos={**raiz, "padre_id": raiz["id"]})
    nuevo = proyectos.guardar(con, admin, datos={**hijo, "nombre": "Los Robles II", "lat": 12.1, "lon": -86.2})["proyecto"]
    assert nuevo["version"] == 2
    with pytest.raises(db.ConflictoVersion):
        proyectos.guardar(con, admin, datos={**hijo, "nombre": "otra cosa"})          # still version 1
    cambios = proyectos.historial(con, admin, id=hijo["id"])["historial"]
    assert [c["accion"] for c in cambios] == ["editar", "crear"]
    assert cambios[0]["cambio"]["nombre"] == ["Los Robles", "Los Robles II"] and cambios[0]["usuario"] == "jgutierrez"
    assert cambios[0]["cambio"]["lat"] == [None, 12.1]


# --------------------------------------------------------------------------- permisos

def test_permissions_by_role_and_assignment(gente):
    con, admin, editor, lector, otro = gente
    with pytest.raises(db.SinPermiso):
        _crear(con, lector)
    p = _crear(con, editor, usuarios=[lector["id"]])
    assert [x["id"] for x in proyectos.listar(con, otro)["proyectos"]] == []          # not assigned: not visible
    with pytest.raises(db.SinPermiso):
        proyectos.obtener(con, otro, id=p["id"])
    with pytest.raises(db.SinPermiso):
        proyectos.guardar(con, otro, datos={**p, "nombre": "Z"})
    vista = proyectos.listar(con, lector)["proyectos"][0]
    assert vista["id"] == p["id"] and vista["puede_editar"] is False                 # reader: sees, cannot edit
    with pytest.raises(db.SinPermiso):
        proyectos.guardar(con, lector, datos={**p, "nombre": "Z"})
    with pytest.raises(db.SinPermiso):
        proyectos.eliminar(con, lector, id=p["id"], version=p["version"])
    assert len(proyectos.listar(con, admin)["proyectos"]) == 1                        # admin sees everything
    with pytest.raises(db.DatosInvalidos, match="sí mismo"):
        proyectos.guardar(con, editor, datos={**p, "usuarios": [lector["id"]]})
    p2 = proyectos.guardar(con, editor, datos={**p, "usuarios": [editor["id"], otro["id"]]})["proyecto"]
    assert {u["nombre"] for u in p2["usuarios"]} == {"Marlon", "Otro"}
    assert proyectos.listar(con, lector)["proyectos"] == []                            # Ana removed


# --------------------------------------------------------------------------- duplicar / eliminar / restaurar

def test_duplicate_delete_and_restore(gente):
    con, admin, editor, lector, _ = gente
    p = _crear(con, editor, codigo="RED-1", nombre="Red Norte", area=AREA, imagen=_png(), usuarios=[lector["id"]])
    copia = proyectos.duplicar(con, editor, id=p["id"])["proyecto"]
    assert (copia["codigo"], copia["nombre"]) == ("RED-1-COPIA", "Red Norte (copia)")
    assert copia["area"] == p["area"] and copia["imagen"] == p["imagen"]
    assert {u["nombre"] for u in copia["usuarios"]} == {"Marlon", "Ana"}
    assert proyectos.duplicar(con, editor, id=p["id"])["proyecto"]["codigo"] == "RED-1-COPIA2"

    hijo = _crear(con, editor, codigo="SUB", padre_id=p["id"])
    with pytest.raises(db.DatosInvalidos, match="subproyectos"):
        proyectos.eliminar(con, editor, id=p["id"], version=p["version"])
    proyectos.eliminar(con, editor, id=hijo["id"], version=hijo["version"])
    proyectos.eliminar(con, editor, id=p["id"], version=p["version"])
    assert all(x["id"] != p["id"] for x in proyectos.listar(con, admin)["proyectos"])
    eliminados = proyectos.listar(con, admin, incluir_eliminados=True)["proyectos"]
    assert any(x["id"] == p["id"] and x["eliminado"] for x in eliminados)             # logical delete: still there
    with pytest.raises(db.NoEncontrado):
        proyectos.obtener(con, editor, id=p["id"])

    otro = _crear(con, admin, codigo="red-1", nombre="Ocupa el código")               # the code is free again
    actual = con.execute("SELECT version FROM redes.proyectos WHERE id = %s", (p["id"],)).fetchone()["version"]
    with pytest.raises(db.SinPermiso):
        proyectos.restaurar(con, editor, id=p["id"], version=actual)
    with pytest.raises(db.DatosInvalidos, match="identificador RED-1"):
        proyectos.restaurar(con, admin, id=p["id"], version=actual)
    proyectos.guardar(con, admin, datos={**otro, "codigo": "OTRO"})
    restaurado = proyectos.restaurar(con, admin, id=p["id"], version=actual)["proyecto"]
    assert restaurado["eliminado"] is False and restaurado["imagen"] == p["imagen"]
    acciones = [h["accion"] for h in proyectos.historial(con, admin, id=p["id"])["historial"]]
    assert acciones == ["restaurar", "eliminar", "crear"]


# --------------------------------------------------------------------------- dirección

def test_address_search_uses_google_with_clear_errors(gente, monkeypatch):
    con, admin, *_ = gente
    import requests

    class R:
        def __init__(self, datos):
            self._datos = datos

        def json(self):
            return self._datos

    pedidos = []
    respuestas = iter([
        {"status": "OK", "results": [{"formatted_address": "Metrocentro, Managua", "geometry": {"location": {"lat": 12.128, "lng": -86.265}}}]},
        {"status": "ZERO_RESULTS", "results": []},
        {"status": "REQUEST_DENIED"},
    ])
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: pedidos.append(params) or R(next(respuestas)))
    r = proyectos.geocodificar(con, admin, texto="Metrocentro")
    assert r["resultados"] == [{"direccion": "Metrocentro, Managua", "lat": 12.128, "lon": -86.265}]
    assert pedidos[0]["region"] == "ni" and pedidos[0]["address"] == "Metrocentro"
    assert proyectos.geocodificar(con, admin, texto="zzzz") == {"resultados": []}
    with pytest.raises(db.DatosInvalidos, match="Geocoding API"):
        proyectos.geocodificar(con, admin, texto="otra")
    with pytest.raises(db.DatosInvalidos):
        proyectos.geocodificar(con, admin, texto="a")


def test_service_exposes_the_project_methods(base_redes, con_redes):
    from visor_rutas.redes.api import CON_LIMITE, METODOS, ServicioRedes
    assert {"proyectos", "proyecto", "guardar_proyecto", "duplicar_proyecto", "eliminar_proyecto",
            "restaurar_proyecto", "historial_proyecto", "usuarios_asignables", "geocodificar"} <= set(METODOS)
    assert CON_LIMITE == {"geocodificar"}
    servicio = ServicioRedes(conectar=lambda: db.conectar(params=base_redes[1]))
    try:
        r = servicio.llamar("guardar_proyecto", {"datos": {"nombre": "Uno", "codigo": "U1"}}, usuario_windows="jgutierrez")
        assert r["ok"] and r["proyecto"]["codigo"] == "U1"
        assert servicio.llamar("proyectos", {"texto": "un"}, usuario_windows="jgutierrez")["proyectos"][0]["id"] == r["proyecto"]["id"]
        assert 2 in servicio.llamar("estado", usuario_windows="jgutierrez")["migraciones"]
    finally:
        servicio.cerrar()


# --------------------------------------------------------------------------- historial de presupuestos

def test_budget_history_lists_and_opens_the_viewer_files(tmp_path, monkeypatch):
    from openpyxl import Workbook

    from visor_rutas import presupuesto_visor as pv
    carpeta = tmp_path / "visor"
    carpeta.mkdir()
    monkeypatch.setattr(pv, "carpeta_visor", lambda: carpeta)
    for nombre in ("Cliente_Uno_12.136400_-86.251400_20261007-153005.xlsx", "Estimacion_12.100000_-86.200000_20261008-090000.xlsx",
                   "otro.xlsx"):
        libro = Workbook()
        libro.active.title = "Presupuesto"
        libro.active["C10"] = "MANO DE OBRA"
        libro.active["E11"], libro.active["G11"], libro.active["I11"] = "Instalación", 3, 30.5
        libro.active["H20"], libro.active["I20"] = "TOTAL", 30.5
        libro.save(carpeta / nombre)
    (carpeta / "Cliente_Uno_12.136400_-86.251400_20261007-153005.pdf").write_bytes(b"%PDF")
    lista = pv.historial()
    assert len(lista) == 3
    uno = next(x for x in lista if x["nombre"].startswith("Cliente_Uno"))
    assert (uno["cliente"], uno["coordenada"], uno["fecha"], uno["tiene_pdf"]) == (
        "Cliente Uno", "12.136400, -86.251400", "2026-10-07T15:30:05", True)
    assert next(x for x in lista if x["nombre"].startswith("Estimacion"))["estimacion"] is True
    assert next(x for x in lista if x["nombre"] == "otro.xlsx")["coordenada"] is None
    abierto = pv.abrir_guardado(carpeta / uno["nombre"])
    assert abierto["calculado"] and abierto["coordenada"] == "12.136400, -86.251400"
    assert abierto["resumen"]["totales"][0]["valor"] == 30.5
    with pytest.raises(FileNotFoundError):
        pv.abrir_guardado(tmp_path / "fuera.xlsx")
    assert datetime.fromisoformat(uno["fecha"])
    assert isinstance(Path(uno["archivo"]), Path)


# --------------------------------------------------------------------------- modo remoto

from test_visor_api import JAN, _api_remota, entorno  # noqa: E402,F401  (fixture of the /visor/* API)


def test_remote_history_uses_ids_and_address_search_counts_for_the_limit(base_redes, con_redes, entorno, monkeypatch, tmp_path):
    from openpyxl import Workbook

    from visor_rutas.redes.api import ServicioRedes
    main, visor_api, cliente, salida, _ = entorno
    carpeta = salida / "visor"
    carpeta.mkdir(parents=True, exist_ok=True)
    libro = Workbook()
    libro.active.title = "Presupuesto"
    libro.active["H20"], libro.active["I20"] = "TOTAL", 99.5
    libro.save(carpeta / "Cliente_Remoto_12.136400_-86.251400_20261009-080000.xlsx")

    lista = cliente.get("/visor/presupuestos", headers=JAN).json()["presupuestos"]
    assert lista[0]["archivo"] == "remoto:Cliente_Remoto_12.136400_-86.251400_20261009-080000"
    assert str(salida) not in str(lista)                                  # no server paths
    remota = _api_remota(main, tmp_path)
    abierto = remota.abrir_presupuesto_guardado(lista[0]["archivo"])
    assert abierto["ok"] and abierto["resultado"]["archivo"].startswith("remoto:")
    assert abierto["resultado"]["resumen"]["totales"][0]["valor"] == 99.5
    assert remota.abrir_presupuesto_guardado("remoto:../x")["ok"] is False
    assert cliente.get("/visor/presupuestos/no_existe", headers=JAN).json()["ok"] is False

    servicio = ServicioRedes(conectar=lambda: db.conectar(params=base_redes[1]))
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    monkeypatch.setattr(proyectos, "geocodificar", lambda con, actor, texto: {"resultados": []})
    from visor_rutas.redes import api as api_redes
    monkeypatch.setitem(api_redes.METODOS, "geocodificar", proyectos.geocodificar)
    monkeypatch.setenv("VISOR_RATE_LIMIT_PER_HOUR", "1")
    try:
        assert cliente.post("/visor/redes/geocodificar", json={"args": {"texto": "Metrocentro"}}, headers=JAN).status_code == 200
        assert cliente.post("/visor/redes/geocodificar", json={"args": {"texto": "otra"}}, headers=JAN).status_code == 429
        assert cliente.post("/visor/redes/proyectos", json={"args": {}}, headers=JAN).status_code == 200   # no limit
    finally:
        servicio.cerrar()


# --------------------------------------------------------------------------- clientes del proyecto

def test_project_has_several_clients_kept_in_sync(gente):
    con, admin, *_ = gente
    clientes = [{"nombre": "Casa Pérez", "codigo": "c12345", "id_servicio": "ID418400", "lat": 12.1051, "lon": -86.2951},
                {"nombre": "Ferretería", "lat": 12.1062, "lon": -86.2940},
                {"nombre": "Escuela", "codigo": "C2001", "lat": 12.1070, "lon": -86.2960}]
    p = _crear(con, admin, area=AREA, clientes=clientes)
    assert [c["nombre"] for c in p["clientes"]] == ["Casa Pérez", "Ferretería", "Escuela"]
    assert p["clientes"][0]["codigo"] == "C12345" and p["clientes"][0]["id_servicio"] == "ID418400"
    assert p["clientes"][0]["lat"] == pytest.approx(12.1051)
    assert proyectos.listar(con, admin)["proyectos"][0]["n_clientes"] == 3

    # edit one, remove one, add one; the removed one is a logical delete
    nuevos = [{**p["clientes"][0], "nombre": "Casa Pérez 2", "lat": 12.1052}, p["clientes"][2],
              {"nombre": "Clínica", "lat": 12.108, "lon": -86.291}]
    p2 = proyectos.guardar(con, admin, datos={**p, "clientes": nuevos})["proyecto"]
    assert [c["nombre"] for c in p2["clientes"]] == ["Casa Pérez 2", "Escuela", "Clínica"]
    assert p2["clientes"][0]["id"] == p["clientes"][0]["id"] and p2["clientes"][0]["version"] == 2
    borrado = con.execute("SELECT borrado_en FROM redes.elementos WHERE id = %s", (p["clientes"][1]["id"],)).fetchone()
    assert borrado["borrado_en"] is not None                                  # recoverable
    cambio = proyectos.historial(con, admin, id=p["id"])["historial"][0]["cambio"]["clientes"]
    assert cambio[0].startswith("3: Casa Pérez (C12345)") and cambio[1].startswith("3: Casa Pérez 2")

    sin_clientes = dict(p2)
    del sin_clientes["clientes"]                                              # no "clientes" key: unchanged
    assert len(proyectos.guardar(con, admin, datos={**sin_clientes, "nombre": "X"})["proyecto"]["clientes"]) == 3
    copia = proyectos.duplicar(con, admin, id=p["id"])["proyecto"]
    assert [c["nombre"] for c in copia["clientes"]] == ["Casa Pérez 2", "Escuela", "Clínica"]
    assert {c["id"] for c in copia["clientes"]}.isdisjoint({c["id"] for c in p2["clientes"]})


def test_client_validation_names_the_rows(gente):
    con, admin, *_ = gente
    with pytest.raises(db.DatosInvalidos) as e:
        _crear(con, admin, clientes=[{"nombre": "Bien", "lat": 12.1, "lon": -86.2},
                                     {"nombre": "", "lat": 12.1, "lon": -86.2},
                                     {"nombre": "Malo", "codigo": "X1", "lat": 99, "lon": 0},
                                     {"nombre": "Repetido", "codigo": "C1000", "lat": 12, "lon": -86},
                                     {"nombre": "Repetido 2", "codigo": "c1000", "lat": 12, "lon": -86}])
    texto = e.value.errores["clientes"]
    assert "cliente 2: falta el nombre" in texto and "cliente 3:" in texto and "código debe ser C" in texto
    assert "coordenada no válida" in texto and "cliente 5: el código C1000 está repetido" in texto
    assert "cliente 1" not in texto
