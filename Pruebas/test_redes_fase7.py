"""Network design module, phase 7: Problemas, Pendientes and Backup (JSON + pg_dump backup, restore as
a new project, KMZ / GeoJSON export)."""
import base64
import io
import json
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_diagrama import red_diagrama  # noqa: F401  (fixture: Nodo -> MF Norte (splitter) -> FAT 1 -> Casa Pérez, MF Sur)
from visor_rutas.redes import db, diagrama, mufa, pendientes, problemas, proyectos, red, respaldo, usuarios


def _foto(color=(200, 30, 30)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _usuario(con, admin, nombre, rol, proyecto_id=None):
    u = usuarios.guardar(con, admin, datos={"nombre": nombre, "rol": rol, "persona_visor": nombre.lower()})["usuario"]
    u = con.execute("SELECT * FROM redes.usuarios WHERE id = %s", (u["id"],)).fetchone()
    if proyecto_id:
        p = proyectos.obtener(con, admin, id=proyecto_id)["proyecto"]
        actuales = [x["id"] for x in p.get("usuarios", [])] or [admin["id"]]
        proyectos.guardar(con, admin, datos={**p, "usuarios": actuales + [u["id"]]})
    return u


# --------------------------------------------------------------------------- 7.1 Problemas

def test_problems_reported_by_a_reader_with_photos_filters_and_map_position(red_diagrama):
    con, admin, p, ids = red_diagrama
    tecnico = _usuario(con, admin, "Pedro", "lector", p["id"])
    r = problemas.guardar(con, tecnico, datos={"proyecto_id": p["id"], "elemento_id": ids["m2"], "titulo": "Tapa de la FAT rota",
                                               "descripcion": "Se moja\ncon la lluvia", "severidad": "alta",
                                               "fotos_nuevas": [_foto(), _foto((0, 90, 200))]})
    pr = r["problema"]
    assert (pr["titulo"], pr["severidad"], pr["estado"], pr["creado_por"], len(pr["fotos"])) == ("Tapa de la FAT rota", "alta", "abierto", "Pedro", 2)
    assert pr["descripcion"] == "Se moja\ncon la lluvia" and pr["vinculo"] == "FAT 1 (mufa)" and pr["puede_editar"] is True
    assert (round(pr["lat"], 4), round(pr["lon"], 4)) == (12.102, -86.3)
    assert problemas.foto(con, tecnico, id=pr["fotos"][0]["id"])["imagen"].startswith("data:image/png;base64,")
    en_cable = problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "cable_id": ids["k3"], "titulo": "Cable colgando",
                                                    "severidad": "critica"})["problema"]
    assert en_cable["vinculo"] == "Cable Distribución Sur" and en_cable["lat"] is not None       # middle of the cable
    # filters
    assert [x["titulo"] for x in problemas.listar(con, admin, severidad="alta_o_mas")["problemas"]] == ["Cable colgando", "Tapa de la FAT rota"]
    assert [x["titulo"] for x in problemas.listar(con, admin, texto="fat")["problemas"]] == ["Tapa de la FAT rota"]
    # another reader of the project cannot change Pedro's report; an editor can, and closing it dates it
    otro = _usuario(con, admin, "Luis", "lector", p["id"])
    with pytest.raises(db.SinPermiso):
        problemas.guardar(con, otro, datos={**pr, "estado": "cerrado"})
    editado = problemas.guardar(con, tecnico, datos={**pr, "estado": "en_proceso", "fotos_quitar": [pr["fotos"][0]["id"]]})["problema"]
    assert editado["estado"] == "en_proceso" and len(editado["fotos"]) == 1
    cerrado = problemas.guardar(con, admin, datos={**editado, "estado": "cerrado"})["problema"]
    assert cerrado["cerrado_en"] is not None
    assert [x["titulo"] for x in problemas.listar(con, admin, estado="activos")["problemas"]] == ["Cable colgando"]
    with pytest.raises(db.ConflictoVersion):
        problemas.guardar(con, admin, datos={**editado, "titulo": "viejo"})                         # old version
    # the icon follows the element when it is moved on the map
    mapa = red.red(con, admin, proyecto_id=p["id"])
    fat = next(e for e in mapa["elementos"] if e["nombre"] == "FAT 1")
    red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [{**fat, "lat": 12.1030}]})
    assert round(problemas.obtener(con, admin, id=pr["id"])["problema"]["lat"], 4) == 12.103
    acciones = [h["accion"] for h in problemas.historial(con, admin, id=pr["id"])["historial"]]
    assert acciones == ["editar", "editar", "crear"]
    problemas.eliminar(con, admin, id=cerrado["id"], version=cerrado["version"])
    assert [x["titulo"] for x in problemas.listar(con, admin)["problemas"]] == ["Cable colgando"]


def test_problem_validation_and_access(red_diagrama):
    con, admin, p, ids = red_diagrama
    with pytest.raises(db.DatosInvalidos) as e:
        problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "", "severidad": "rara"})
    assert set(e.value.errores) == {"titulo", "severidad", "vinculo"}
    otro = proyectos.guardar(con, admin, datos={"nombre": "Otro", "codigo": "OTR"})["proyecto"]
    with pytest.raises(db.DatosInvalidos, match="no es de este proyecto"):
        problemas.guardar(con, admin, datos={"proyecto_id": otro["id"], "elemento_id": ids["m1"], "titulo": "x"})
    with pytest.raises(db.DatosInvalidos, match="máximo 6"):
        problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "elemento_id": ids["m1"], "titulo": "x", "fotos_nuevas": [_foto()] * 7})
    with pytest.raises(db.DatosInvalidos, match="foto 1"):
        problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "elemento_id": ids["m1"], "titulo": "x",
                                             "fotos_nuevas": ["data:image/svg+xml;base64,PHN2Zz4="]})
    ajeno = _usuario(con, admin, "Ana", "lector")                                                  # not assigned
    with pytest.raises(db.SinPermiso):
        problemas.guardar(con, ajeno, datos={"proyecto_id": p["id"], "elemento_id": ids["m1"], "titulo": "x"})
    assert problemas.listar(con, ajeno)["problemas"] == []
    ref = problemas.referencias(con, admin, proyecto_id=p["id"])
    assert {e["nombre"] for e in ref["elementos"]} >= {"MF Norte", "FAT 1"} and {c["nombre"] for c in ref["cables"]} >= {"Troncal"}


# --------------------------------------------------------------------------- 7.2 Pendientes

def test_pending_tasks_responsible_due_dates_and_filters(red_diagrama):
    con, admin, p, ids = red_diagrama
    tecnico = _usuario(con, admin, "Pedro", "lector", p["id"])
    ayer = (date.today() - timedelta(days=1)).isoformat()
    t = pendientes.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "Validar existencia de mufa", "elemento_id": ids["m3"],
                                              "responsable_id": tecnico["id"], "fecha_limite": ayer})["pendiente"]
    assert (t["estado"], t["responsable"], t["vencido"], t["vinculo"], t["puede_editar"]) == ("pendiente", "Pedro", True, "MF Sur (mufa)", True)
    pendientes.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "Dar continuidad a hilos", "cable_id": ids["k1"]})
    vista = pendientes.listar(con, tecnico, responsable="yo")["pendientes"]
    assert [x["titulo"] for x in vista] == ["Validar existencia de mufa"] and vista[0]["puede_cambiar_estado"] and not vista[0]["puede_editar"]
    assert [x["titulo"] for x in pendientes.listar(con, admin, vencidos=True)["pendientes"]] == ["Validar existencia de mufa"]
    # the responsible reader only changes the state (the title is kept)
    hecho = pendientes.guardar(con, tecnico, datos={**t, "estado": "hecho", "titulo": "otro título"})["pendiente"]
    assert (hecho["estado"], hecho["titulo"], hecho["vencido"]) == ("hecho", "Validar existencia de mufa", False) and hecho["hecho_en"]
    with pytest.raises(db.SinPermiso):
        pendientes.guardar(con, tecnico, datos={"proyecto_id": p["id"], "titulo": "nuevo"})       # a reader does not create
    with pytest.raises(db.DatosInvalidos) as e:
        pendientes.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "", "fecha_limite": "31/12/2026", "estado": "x"})
    assert set(e.value.errores) == {"titulo", "fecha_limite", "estado"}
    assert [x["titulo"] for x in pendientes.listar(con, admin, estado="abiertos")["pendientes"]] == ["Dar continuidad a hilos"]
    assert [h["accion"] for h in pendientes.historial(con, admin, id=t["id"])["historial"]] == ["editar", "crear"]
    pendientes.eliminar(con, admin, id=hecho["id"], version=hecho["version"])
    assert len(pendientes.listar(con, admin)["pendientes"]) == 1


# --------------------------------------------------------------------------- 7.4 Backup y exportación

def _contar(con, proyecto_id):
    q = lambda sql: con.execute(sql, (proyecto_id,)).fetchone()["n"]
    return {"elementos": q("SELECT count(*) AS n FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "cables": q("SELECT count(*) AS n FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "hilos": q("SELECT count(*) AS n FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE c.proyecto_id = %s AND h.borrado_en IS NULL"),
            "splitters": q("SELECT count(*) AS n FROM redes.splitters WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "conexiones": q("SELECT count(*) AS n FROM redes.conexiones WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "diagramas": q("SELECT count(*) AS n FROM redes.diagramas_logicos WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "problemas": q("SELECT count(*) AS n FROM redes.problemas WHERE proyecto_id = %s AND borrado_en IS NULL"),
            "fotos": q("SELECT count(*) AS n FROM redes.problema_fotos f JOIN redes.problemas p ON p.id = f.problema_id WHERE p.proyecto_id = %s"),
            "pendientes": q("SELECT count(*) AS n FROM redes.pendientes WHERE proyecto_id = %s AND borrado_en IS NULL")}


def test_backup_and_restore_as_a_new_project(red_diagrama, tmp_path, monkeypatch):
    con, admin, p, ids = red_diagrama
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path))
    diagrama.guardar(con, admin, proyecto_id=p["id"], datos={"titulo": "Desde el splitter", "inicio": f"s:{ids['s']}"})
    problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "elemento_id": ids["m2"], "titulo": "Tapa rota", "fotos_nuevas": [_foto()]})
    pendientes.guardar(con, admin, datos={"proyecto_id": p["id"], "titulo": "Validar mufa", "elemento_id": ids["m3"], "responsable_id": admin["id"]})
    antes = _contar(con, p["id"])
    r = respaldo.crear(con, admin)
    assert r["creado"].startswith("respaldo_redes_") and (tmp_path / r["creado"]).is_file()
    info = r["respaldos"][0]
    assert info["archivo"] == r["creado"] and [x["codigo"] for x in info["proyectos"]] == ["RLR"] and info["creado_por"] == "jgutierrez"
    if respaldo.pg_dump():
        assert info["sql"] and "CREATE TABLE redes.problemas" in (tmp_path / info["sql"]).read_text(encoding="utf-8"), r["aviso"]
    # restore: a NEW project, the original untouched
    nuevo = respaldo.restaurar(con, admin, archivo=info["archivo"], indice=0)["proyecto"]
    assert nuevo["codigo"] == "RLR-R1" and nuevo["nombre"].startswith("Los Robles (restaurado ")
    assert _contar(con, nuevo["id"]) == antes and _contar(con, p["id"]) == antes
    copia = mufa.leer(con, admin, mufa_id=next(e["id"] for e in red.red(con, admin, proyecto_id=nuevo["id"])["elementos"] if e["nombre"] == "MF Norte"))
    assert [s["nombre"] for s in copia["splitters"]] == ["Splitter 1"] and len(copia["conexiones"]) == 4
    assert diagrama.generar(con, admin, diagrama_id=diagrama.listar(con, admin, proyecto_id=nuevo["id"])["diagramas"][0]["id"])["cajas"]
    assert respaldo.restaurar(con, admin, archivo=info["archivo"], indice=0)["proyecto"]["codigo"] == "RLR-R2"
    assert {h["accion"] for h in proyectos.historial(con, admin, id=nuevo["id"])["historial"]} >= {"restaurar"}
    # download, permissions and file names
    bajada = respaldo.descargar(con, admin, archivo=info["archivo"])
    assert json.loads(base64.b64decode(bajada["datos"]))["formato"] == "redes-respaldo"
    lector = _usuario(con, admin, "Ana", "lector", p["id"])
    for llamada in (lambda: respaldo.listar(con, lector), lambda: respaldo.crear(con, lector),
                    lambda: respaldo.restaurar(con, lector, archivo=info["archivo"], indice=0)):
        with pytest.raises(db.SinPermiso):
            llamada()
    with pytest.raises(db.DatosInvalidos):
        respaldo.restaurar(con, admin, archivo="..\\..\\.env", indice=0)


def test_export_kmz_and_geojson(red_diagrama):
    con, admin, p, ids = red_diagrama
    problemas.guardar(con, admin, datos={"proyecto_id": p["id"], "elemento_id": ids["m2"], "titulo": "Tapa rota", "severidad": "alta"})
    g = respaldo.exportar(con, admin, proyecto_id=p["id"], formato="geojson")
    geo = json.loads(base64.b64decode(g["datos"]))
    capas = [f["properties"]["capa"] for f in geo["features"]]
    assert geo["type"] == "FeatureCollection" and capas.count("elemento") == 5 and capas.count("cable") == 4 and capas.count("problema") == 1
    troncal = next(f for f in geo["features"] if f["properties"].get("nombre") == "Troncal")
    assert troncal["geometry"]["type"] == "LineString" and troncal["properties"]["origen"] == "Nodo Central"
    k = respaldo.exportar(con, admin, proyecto_id=p["id"], formato="kmz")
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(k["datos"]))) as z:
        nombres = z.namelist()
        raiz = ElementTree.fromstring(z.read("doc.kml"))
    assert "doc.kml" in nombres and "files/mufa_terminal.png" in nombres and "files/problema.png" in nombres
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    carpetas = [f.find("k:name", ns).text for f in raiz.iter("{http://www.opengis.net/kml/2.2}Folder")]
    assert carpetas == ["Nodos / OLT", "Mufas", "Clientes", "Cables", "Problemas"]
    assert len(raiz.findall(".//k:LineString", ns)) == 4 and k["nombre"] == "RLR Los Robles"
    ajeno = _usuario(con, admin, "Ana", "lector")
    with pytest.raises(db.SinPermiso):
        respaldo.exportar(con, ajeno, proyecto_id=p["id"], formato="kmz")
    with pytest.raises(db.DatosInvalidos):
        respaldo.exportar(con, admin, proyecto_id=p["id"], formato="shp")


def test_save_file_dialog(tmp_path, monkeypatch):
    """Api.guardar_archivo: KMZ / GeoJSON / backup files saved with the Windows dialog (also in the .exe)."""
    import sys
    import types
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1)))
    from visor_rutas.ventana_web import Api
    pedidos = []

    class Ventana:
        def create_file_dialog(self, *args, **kwargs):
            pedidos.append(kwargs)
            return str(tmp_path / "salida")

    api = Api.__new__(Api)
    api._ventana = Ventana()
    datos = base64.b64encode(b"PK\x03\x04 kmz").decode()
    r = api.guardar_archivo("RLR Los Robles", datos, "kmz")
    assert r["ok"] and (tmp_path / "salida.kmz").read_bytes() == b"PK\x03\x04 kmz"
    assert pedidos[0]["save_filename"] == "RLR Los Robles.kmz" and pedidos[0]["file_types"] == ("Google Earth (*.kmz)",)
    api.guardar_archivo("respaldo_redes_2026-10-12_090000.json", base64.b64encode(b"{}").decode(), "json")
    assert pedidos[1]["save_filename"] == "respaldo_redes_2026-10-12_090000.json"              # no double suffix
    assert api.guardar_archivo("x", datos, "exe")["ok"] is False                                  # only the module's file types


def test_service_methods(base_redes, con_redes):
    from visor_rutas.redes.api import METODOS
    assert {"problemas", "guardar_problema", "pendientes", "guardar_pendiente", "respaldos", "crear_respaldo", "restaurar_respaldo",
            "exportar_proyecto", "referencias_proyecto"} <= set(METODOS)


def test_old_backups_are_pruned_beyond_the_configured_amount(tmp_path, monkeypatch):
    monkeypatch.setenv("REDES_RESPALDOS_DIR", str(tmp_path))
    for dia in range(1, 6):
        for sufijo in (".json", ".sql"):
            (tmp_path / f"respaldo_redes_2026-10-0{dia}_120000{sufijo}").write_text("x")
    (tmp_path / "otro.json").write_text("x")
    assert respaldo.podar() == 0                              # no limit configured: nothing is removed
    monkeypatch.setenv("REDES_RESPALDOS_CONSERVAR", "2")
    assert respaldo.podar() == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "otro.json", "respaldo_redes_2026-10-04_120000.json", "respaldo_redes_2026-10-04_120000.sql",
        "respaldo_redes_2026-10-05_120000.json", "respaldo_redes_2026-10-05_120000.sql"]
