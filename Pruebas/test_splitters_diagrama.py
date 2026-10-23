"""Splitters de los diagramas (visor_rutas/splitters_diagrama.py, redes/splitters.py, migración 016): clase por color o palabra, puertos de la lista
de clientes, lo confirmado por una persona encima de lo leído, el guardado en cada ruta y el plan de fusión."""
import zipfile
from pathlib import Path

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas import ruta_fusion_plan, splitters_diagrama as sd
from visor_rutas.redes import db, splitters, usuarios
from visor_rutas.redes.api import METODOS

MD5 = "a" * 32
_ORIGINAL = sd.leer
CONTENIDO = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
<office:automatic-styles>
 <style:style style:name="T1"><style:text-properties fo:color="#7030a0"/></style:style>
 <style:style style:name="T2"><style:text-properties fo:color="#ea700d"/></style:style>
 <style:style style:name="T3"><style:text-properties fo:color="#000000"/></style:style>
</office:automatic-styles>
<office:body><office:drawing><draw:page>
{marcos}
</draw:page></office:drawing></office:body></office:document-content>"""


def marco(x, y, texto, estilo, w=4.0, h=1.0):
    parrafos = "".join(f'<text:p><text:span text:style-name="{estilo}">{linea}</text:span></text:p>' for linea in texto.split("\n"))
    return (f'<draw:frame svg:x="{x - w / 2}cm" svg:y="{y - h / 2}cm" svg:width="{w}cm" svg:height="{h}cm"><draw:text-box>{parrafos}</draw:text-box></draw:frame>')


@pytest.fixture(autouse=True)
def _sin_cache():
    sd._leer_cache.cache_clear()
    yield
    sd._leer_cache.cache_clear()


@pytest.fixture
def carpeta(tmp_path):
    marcos = "\n".join([
        marco(10, 10, "SPL 1x8 SECUNDARIO", "T1"),                 # purple with a client list: 3 ports used, 6 free
        marco(10, 12, "8\n7\n6\n5\n4\n3\n2\n1", "T1", w=0.5, h=4),
        marco(12, 10, "SPL 1x8 clientes\n1- C10001\n2- C10002\n3- C10003\n4-\n5-\n6-\n7-\n8-", "T1", w=3, h=5),
        marco(30, 10, "SPL 1/16", "T2"),                           # gold, no list
        marco(30, 12, "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16", "T2", w=8),
        marco(60, 10, "SPL PRINCIPAL", "T3"),                      # black: by the word
        marco(70, 10, "SPL 1/8", "T3"),                            # black, no word
        marco(200, 200, "SPL 1/8 LEJOS", "T1"),
    ])
    (tmp_path / f"{MD5}.odg").write_bytes(b"")
    with zipfile.ZipFile(tmp_path / f"{MD5}.odg", "w") as z:
        z.writestr("content.xml", CONTENIDO.format(marcos=marcos))
    return tmp_path


def test_class_by_colour_then_by_word_then_to_confirm(carpeta):
    por_etiqueta = {s["etiqueta"]: s for s in sd.leer(MD5, carpeta)}
    assert por_etiqueta["SPL 1x8 SECUNDARIO"]["clase"] == "secundario" and por_etiqueta["SPL 1x8 SECUNDARIO"]["clase_fuente"] == "color"
    assert por_etiqueta["SPL 1/16"]["clase"] == "principal" and por_etiqueta["SPL 1/16"]["ratio"] == "1/16"
    assert por_etiqueta["SPL PRINCIPAL"]["clase"] == "principal" and por_etiqueta["SPL PRINCIPAL"]["clase_fuente"] == "palabra"
    assert por_etiqueta["SPL 1/8"]["clase"] == "por_confirmar" and por_etiqueta["SPL 1/8"]["ratio"] == "1/8"
    assert len(por_etiqueta) == 5                                   # the client list is not a splitter of its own


def test_ports_come_from_the_client_list_and_blank_lines_are_free(carpeta):
    s = next(s for s in sd.leer(MD5, carpeta) if s["etiqueta"] == "SPL 1x8 SECUNDARIO")
    assert s["fuente_puertos"] == "lista" and len(s["puertos"]) == 8
    assert s["puertos"]["1"] == {"estado": "ocupado", "cliente": "C10001"}
    assert s["puertos"]["8"]["estado"] == "libre"
    comb = sd.combinar(s, None)
    assert (comb["libres"], comb["desconocidos"], comb["confirmado"]) == (5, 0, False)


def test_without_a_list_the_ports_are_unknown_and_a_confirmation_wins(carpeta):
    s = next(s for s in sd.leer(MD5, carpeta) if s["etiqueta"] == "SPL 1/16")
    assert len(s["puertos"]) == 16 and {p["estado"] for p in s["puertos"].values()} == {"desconocido"}
    comb = sd.combinar(s, {"clase": "secundario", "puertos": {"3": "libre", "4": "ocupado"}})
    assert comb["clase"] == "secundario" and comb["clase_fuente"] == "confirmado" and comb["confirmado"]
    assert comb["libres"] == 1 and comb["desconocidos"] == 14 and comb["puertos"]["3"]["fuente"] == "confirmado"
    assert list(comb["puertos"])[:3] == ["1", "2", "3"]             # numeric order


def test_preferred_splitter_is_a_secondary_with_free_ports(carpeta):
    todos = [sd.combinar(s, None) for s in sd.leer(MD5, carpeta)]
    assert sd.preferido(todos)["etiqueta"] == "SPL 1x8 SECUNDARIO"
    sin_libres = [sd.combinar(s, None) for s in sd.leer(MD5, carpeta) if s["etiqueta"] not in ("SPL 1x8 SECUNDARIO", "SPL 1/8 LEJOS")]
    assert sd.preferido(sin_libres)["clase"] == "principal"        # nothing secondary: a primary
    assert sd.preferido([]) is None
    assert "5 puerto(s) libre(s)" in sd.descripcion(todos[0])


def test_a_stop_gets_only_the_splitters_near_its_mufa(carpeta, monkeypatch):
    monkeypatch.setattr(sd, "leer", lambda md5, c=None: _ORIGINAL(md5, carpeta))
    parada = {"nombre": "MF UNO", "archivos": [{"diagrama": True, "md5": MD5, "nombre": "d.vsdx", "ancla": {"x_cm": 11, "y_cm": 10}}]}
    cerca = sd.de_parada(parada)
    assert {s["etiqueta"] for s in cerca} == {"SPL 1x8 SECUNDARIO", "SPL 1/16"}
    assert cerca[0]["etiqueta"] == "SPL 1x8 SECUNDARIO" and cerca[0]["md5"] == MD5
    sin_ancla = sd.de_parada({"archivos": [{"diagrama": True, "md5": MD5, "ancla": None}]})
    assert len(sin_ancla) == 5                                      # position unknown: all of the diagram (up to 8)
    assert sd.de_parada({"archivos": [{"diagrama": False, "md5": MD5}]}) == []


def test_enriquecer_stores_and_merges_what_people_confirmed(carpeta, monkeypatch):
    monkeypatch.setattr(sd, "leer", lambda md5, c=None: _ORIGINAL(md5, carpeta))
    parada = {"nombre": "MF UNO", "archivos": [{"diagrama": True, "md5": MD5, "ancla": {"x_cm": 11, "y_cm": 10}}]}
    guardados = []

    def guardar(lista):
        guardados.append(len(lista))
        return {(s["md5"], s["clave"]): {"id": i + 1, "version": 3, "confirmado": {"puertos": {"1": "libre"}} if s["etiqueta"] == "SPL 1/16" else None}
                for i, s in enumerate(lista)}
    paradas = [parada, {"nombre": "MF DOS", "archivos": []}]
    sd.enriquecer(paradas, guardar)
    assert guardados == [2] and paradas[1]["splitters_diagrama"] == []
    s16 = next(s for s in paradas[0]["splitters_diagrama"] if s["ratio"] == "1/16")
    assert s16["id"] and s16["version"] == 3 and s16["confirmado"] and s16["puertos"]["1"]["estado"] == "libre"
    # a failure while storing leaves the stop without splitters and never raises
    def falla(lista):
        raise RuntimeError("sin base")
    sd.enriquecer([parada], falla)
    assert parada["splitters_diagrama"] == []


def test_the_plan_uses_the_secondary_with_free_ports_and_mentions_the_ones_to_confirm(carpeta):
    leidos = {s["etiqueta"]: sd.combinar(s, None) for s in sd.leer(MD5, carpeta)}
    paradas = [
        {"orden": 1, "nombre": "MF UNO", "lat": 1, "lon": 2, "es_conexion": False, "fuente_hilos": "sin_dato", "hilos_anillo": [],
         "splitters_diagrama": [leidos["SPL 1x8 SECUNDARIO"]]},
        {"orden": 2, "nombre": "MF DOS", "lat": 1, "lon": 2, "es_conexion": True, "fuente_hilos": "sin_dato", "hilos_anillo": [],
         "splitters_diagrama": [sd.combinar(next(s for s in sd.leer(MD5, carpeta) if s["etiqueta"] == "SPL 1/16"), {"clase": "secundario"})]},
    ]
    plan = ruta_fusion_plan.armar({"ruta_fusion": paradas, "origen_trafico": {"nodo": "NODO X"}})
    por_nombre = {p["nombre"]: p for p in plan["pasos"]}
    assert por_nombre["MF UNO"]["splitter"] == "1/8" and "5 puerto(s) libre(s)" in por_nombre["MF UNO"]["info_splitter"]
    assert por_nombre["MF DOS"]["splitter"] is None and "por confirmar" in por_nombre["MF DOS"]["info_splitter"]
    assert any("puertos por confirmar" in a for a in plan["avisos_rojos"]) and any("5 puerto(s) libre(s)" in a for a in plan["avisos_rojos"])


def test_the_route_stops_at_the_first_secondary_with_free_ports(carpeta):
    libre = sd.combinar(next(s for s in sd.leer(MD5, carpeta) if s["etiqueta"] == "SPL 1x8 SECUNDARIO"), None)
    assert libre["libres"] > 0 and libre["clase"] == "secundario"

    def parada(nombre, orden, *, splitters=(), conexion=False):
        return {"orden": orden, "nombre": nombre, "lat": 1, "lon": 2, "es_conexion": conexion, "fuente_hilos": "sin_dato", "hilos_anillo": [],
                "splitters_diagrama": list(splitters)}
    # OLT side first: MF E (the node's mufa), MF D, MF C (a second secondary, never reached), MF B (the first one with free ports), MF A (connection)
    paradas = [parada("MF E", 1), parada("MF D", 2), parada("MF C", 3, splitters=[libre]), parada("MF B", 4, splitters=[libre]), parada("MF A", 5, conexion=True)]
    plan = ruta_fusion_plan.armar({"ruta_fusion": paradas, "origen_trafico": {"nodo": "NODO X"}})
    por_nombre = {p["nombre"]: p for p in plan["pasos"]}
    assert [p["nombre"] for p in plan["pasos"]] == ["MF A", "MF B", "MF C", "MF D", "MF E"]          # client side first, all still in the plan
    assert por_nombre["MF B"]["splitter"] == "1/8" and por_nombre["MF C"]["splitter"] is None         # only the first one is used
    assert [p["tocar"] for p in plan["pasos"]] == [True, True, False, False, False] and plan["tocadas"] == 2
    assert por_nombre["MF C"]["motivo"] == por_nombre["MF D"]["motivo"] == "después del splitter"
    assert any("se detiene en MF B" in a and "3 mufa(s)" in a for a in plan["avisos_rojos"]) and any("hilos libres" in a for a in plan["avisos_rojos"])
    assert plan["lineas"][1].endswith("fusionarlo con H__ del SPL 1/8 (hilos por identificar)")                  # the last box goes into the splitter
    # the user can mark them again (the splitter may not be usable): the plan is theirs
    editado = [dict(p) for p in plan["pasos"]]
    for p in editado:
        p["tocar"], p["motivo"] = True, None
    assert ruta_fusion_plan.redactar({**plan, "pasos": editado})["tocadas"] == 5
    # without a splitter with free ports nothing is cut; and a secondary with only unknown ports does not cut either
    sin = ruta_fusion_plan.armar({"ruta_fusion": [parada("MF E", 1), parada("MF A", 2, conexion=True)], "origen_trafico": {}})
    assert [p["tocar"] for p in sin["pasos"]] == [True, True]


# ------------------------------------------------------------------ storage (needs the test database)

@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    lector = usuarios.identificar(con, persona_visor="lec")
    return con, admin, lector


def _leido(carpeta, etiqueta):
    s = next(s for s in sd.leer(MD5, carpeta) if s["etiqueta"] == etiqueta)
    return dict(s, md5=MD5)


def test_registering_twice_keeps_what_was_confirmed(mundo, carpeta):
    con, admin, lector = mundo
    s = _leido(carpeta, "SPL 1/16")
    fila = splitters.registrar(con, [s])[(MD5, s["clave"])]
    r = splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], clase="secundario", puertos={"3": "libre", "4": "ocupado"})
    assert r["confirmado"] == {"clase": "secundario", "puertos": {"3": "libre", "4": "ocupado"}} and r["version"] == fila["version"] + 1
    otra = splitters.registrar(con, [s])[(MD5, s["clave"])]
    assert otra["id"] == fila["id"] and otra["confirmado"]["puertos"]["3"] == "libre"
    assert con.execute("SELECT veces_visto FROM redes.splitters_diagrama WHERE id = %s", (fila["id"],)).fetchone()["veces_visto"] == 2
    # confirming more ports adds to the earlier ones
    r2 = splitters.confirmar(con, admin, id=fila["id"], version=r["version"], puertos={"5": "libre"})
    assert r2["confirmado"]["puertos"] == {"3": "libre", "4": "ocupado", "5": "libre"} and r2["confirmado"]["clase"] == "secundario"
    assert splitters.de_diagrama(con, lector, MD5)["splitters"][0]["confirmado"]["puertos"]["5"] == "libre"


def test_confirming_needs_an_editor_a_current_version_and_valid_data(mundo, carpeta):
    con, admin, lector = mundo
    s = _leido(carpeta, "SPL 1/16")
    fila = splitters.registrar(con, [s])[(MD5, s["clave"])]
    with pytest.raises(db.SinPermiso):
        splitters.confirmar(con, lector, id=fila["id"], version=fila["version"], puertos={"1": "libre"})
    with pytest.raises(db.DatosInvalidos):
        splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], puertos={"1": "quizá"})
    with pytest.raises(db.DatosInvalidos):
        splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], clase="otro")
    with pytest.raises(db.DatosInvalidos):
        splitters.confirmar(con, admin, id=fila["id"], version=fila["version"])
    splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], puertos={"1": "libre"})
    with pytest.raises(db.ConflictoVersion):
        splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], puertos={"2": "libre"})
    with pytest.raises(db.NoEncontrado):
        splitters.confirmar(con, admin, id=999999, version=1, puertos={"1": "libre"})
    for nombre in ("splitters_de_diagrama", "confirmar_splitter", "quitar_confirmacion_splitter"):
        assert nombre in METODOS


def test_removing_the_confirmation_goes_back_to_the_reading(mundo, carpeta):
    con, admin, lector = mundo
    s = _leido(carpeta, "SPL 1/16")
    fila = splitters.registrar(con, [s])[(MD5, s["clave"])]
    r = splitters.confirmar(con, admin, id=fila["id"], version=fila["version"], puertos={"1": "libre"})
    with pytest.raises(db.SinPermiso):
        splitters.quitar_confirmacion(con, lector, id=fila["id"], version=r["version"])
    q = splitters.quitar_confirmacion(con, admin, id=fila["id"], version=r["version"])
    assert q["confirmado"] is None
    assert splitters.registrar(con, [s])[(MD5, s["clave"])]["confirmado"] is None


@pytest.mark.guardar_splitters
def test_storing_a_route_skips_a_missing_database_without_failing(monkeypatch):
    def sin_base():
        raise db.RedesNoDisponible("no hay base")
    monkeypatch.setattr(db, "conectar", sin_base)
    assert sd.guardar_en_redes([{"md5": MD5, "clave": "1,1"}]) == {}



