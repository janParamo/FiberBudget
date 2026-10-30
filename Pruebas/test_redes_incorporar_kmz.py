"""Incorporar a la red (visor_rutas/redes/incorporar_kmz.py, migración 024): lo aplicado de una importación de KMZ (lo nuevo, lo modificado, lo eliminado) se mete en el archivo de la red,
en sus carpetas, y deja de ser una capa «Importados» y cambios del KMZ."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_actualizar_red import KMZ_NUEVO
from test_redes_importar_kmz import _linea, _pm, b64, hacer_kmz
from visor_rutas import kmz_capas, subidas
from visor_rutas.redes import actualizar_red as ar, db, importar_kmz, incorporar_kmz, usuarios
from visor_rutas.redes.api import METODOS

# the network in force is KMZ_NUEVO plus six more posts (a network has to look like one: at least 10 elements); this file is its update:
MAS = [_pm(f"Q{i}", -86.4 - i / 100, 12.3 + i / 100) for i in range(6)]
BASE = {**KMZ_NUEVO, "POSTES MAS": MAS}
ACTUALIZACION = {
    "MUFAS": [_pm("MF UNO", -86.2503, 12.1303, "Mufa uno"),                                   # moved ~45 m
              _pm("MF DOS", -86.2603, 12.1403),                                               # (as in the network)
              _pm("MF TRES RENOMBRADA", -86.270, 12.150),                                     # same place, other name
              _pm("MF CUATRO", -86.280, 12.160),
              _pm("MF CINCO", -86.290, 12.170, "Mufa nueva")],                                # new
    "FIBRA OPTICA": [_linea("L1", (-86.250, 12.130), (-86.256, 12.137), (-86.260, 12.140)),
                     _linea("L2", (-86.280, 12.160), (-86.285, 12.165)),
                     _linea("L3", (-86.290, 12.170), (-86.295, 12.175))],                     # new line
    "POSTES DE CONCRETO": [_pm("P1", -86.251, 12.131), _pm("P2", -86.25200001, 12.13200001), _pm("P3", -86.253, 12.133)],        # P4 is gone
    "POSTES MAS": MAS,
    "NODOS NUEVOS": [_pm("NODO JALAPA", -86.3, 12.2)],                                          # a folder the network does not have
}


@pytest.fixture(autouse=True)
def _nunca_el_presupuesto_real(monkeypatch):
    def prohibido():
        raise AssertionError("conectar_presupuesto sin la base de prueba")
    monkeypatch.setattr(importar_kmz, "conectar_presupuesto", prohibido)
    ar._cache_elementos.clear()
    subidas.almacen.reiniciar()
    yield
    ar._cache_elementos.clear()
    subidas.almacen.reiniciar()


@pytest.fixture
def mundo(con_redes, tmp_path, monkeypatch):
    carpeta = tmp_path / "red_kmz"
    carpeta.mkdir()
    (carpeta / "RED.kmz").write_bytes(hacer_kmz(BASE, "RED"))
    monkeypatch.setenv("KMZ_PATH", str(carpeta))
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", tmp_path / "datos_kmz")
    kmz_capas.asegurar()
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    editor = usuarios.identificar(con, persona_visor="ed")
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE id = %s", (editor["id"],))
    editor = usuarios.identificar(con, persona_visor="ed")
    return con, admin, editor, carpeta


def _aplicar_actualizacion(con, admin):
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ACTUALIZACION, "RED")), nombre="red_nueva.kmz", modo="actualizacion")["importacion"]
    importar_kmz.aceptar(con, admin, id=imp["id"], aceptado=True, clase="eliminado")                 # the removed ones are not accepted by default
    return importar_kmz.aplicar(con, admin, id=imp["id"], incorporar=False)["importacion"]            # as a layer first: the incorporation is a step of its own here


def _nombres(crudo, carpeta=None):
    return sorted(e["nombre"] for e in importar_kmz.leer(crudo) if carpeta is None or e["ruta"] == carpeta)


def test_incorporate_puts_what_the_imports_added_and_changed_inside_the_file(mundo):
    con, admin, editor, carpeta = mundo
    aplicada = _aplicar_actualizacion(con, admin)
    previa = incorporar_kmz.previa(con, admin)
    assert previa["agregados"] >= 3 and previa["modificados"] >= 2 and previa["eliminados"] == 1 and [i["id"] for i in previa["importaciones"]] == [aplicada["id"]]
    antes = (carpeta / "RED.kmz").read_bytes()
    r = incorporar_kmz.incorporar(con, admin)
    assert r["agregados"] >= 3 and r["eliminados"] == 1 and r["modificados"] >= 2 and r["importaciones"] == 1 and r["archivo"] == "RED.kmz"
    despues = (carpeta / "RED.kmz").read_bytes()
    assert despues != antes
    # the file of the network now has them, each in its own folder
    assert _nombres(despues, "RED/MUFAS") == ["MF CINCO", "MF CUATRO", "MF DOS", "MF TRES RENOMBRADA", "MF UNO"]
    assert _nombres(despues, "RED/FIBRA OPTICA") == ["L1", "L2", "L3"] and "P4" not in _nombres(despues, "RED/POSTES DE CONCRETO")
    assert _nombres(despues, "RED/NODOS NUEVOS") == ["NODO JALAPA"]                                       # the folder that did not exist was created
    uno = next(e for e in importar_kmz.leer(despues) if e["nombre"] == "MF UNO")
    assert round(uno["geom"]["coordinates"][0], 4) == -86.2503 and round(uno["geom"]["coordinates"][1], 4) == 12.1303      # the moved one
    # the old file is kept, and the cache of the panel is the new network
    guardados = list((carpeta / "anteriores").glob("*RED.kmz"))
    assert len(guardados) == 1 and guardados[0].read_bytes() == antes
    arbol = kmz_capas.leer_arbol()
    assert any(c["nombre"] == "NODOS NUEVOS" for c in arbol["carpetas"].values())
    # nothing is an overlay any more: no layer of imported, no changes of the KMZ, and the import cannot be reverted
    assert importar_kmz.elementos_importados(con) == []
    assert con.execute("SELECT count(*) AS n FROM redes.kmz_cambios WHERE borrado_en IS NULL").fetchone()["n"] == 0
    lista = importar_kmz.listar(con, admin)["importaciones"]
    assert lista[0]["incorporada"] is True and lista[0]["es_ultima_aplicada"] is False
    with pytest.raises(db.DatosInvalidos):
        importar_kmz.revertir(con, admin, id=aplicada["id"])
    with pytest.raises(db.DatosInvalidos):                                                                # now there is nothing to incorporate
        incorporar_kmz.incorporar(con, admin)
    # the next comparison with the same file finds nothing to do: the network IS the file
    filas, conteos = importar_kmz.comparar(importar_kmz.leer(hacer_kmz(ACTUALIZACION, "RED")), importar_kmz.actuales(con))
    assert not [f for f in filas if f["clase"] in ("nuevo", "modificado")], [(f["nombre"], f["clase"]) for f in filas]


def test_only_an_administrator_and_a_changed_file_is_not_overwritten(mundo):
    con, admin, editor, carpeta = mundo
    _aplicar_actualizacion(con, admin)
    with pytest.raises(db.SinPermiso):
        incorporar_kmz.incorporar(con, editor)
    with pytest.raises(db.SinPermiso):
        incorporar_kmz.previa(con, editor)
    # the KMZ in force was replaced by another one after applying: the changes do not find their elements, nothing is touched
    (carpeta / "RED.kmz").write_bytes(hacer_kmz({"OTRA": [_pm(f"X{i}", -86.0 - i / 100, 12.0 + i / 100) for i in range(12)]}, "RED"))
    ar._cache_elementos.clear()
    antes = (carpeta / "RED.kmz").read_bytes()
    with pytest.raises(db.DatosInvalidos) as e:
        incorporar_kmz.incorporar(con, admin)
    assert "no se encontraron" in str(e.value) or "no se incorporó" in str(e.value)
    assert (carpeta / "RED.kmz").read_bytes() == antes and not (carpeta / "anteriores").exists()
    assert con.execute("SELECT count(*) AS n FROM redes.kmz_cambios WHERE borrado_en IS NULL").fetchone()["n"] > 0          # the changes are still there
    assert METODOS["incorporar_kmz_red"] is incorporar_kmz.incorporar and METODOS["incorporar_previa_kmz"] is incorporar_kmz.previa


def test_manual_edits_of_the_map_are_incorporated_too(mundo):
    """A rename or a removal made by hand in the popup of an element (kmz_cambios without an import) goes into the file as well."""
    from visor_rutas.redes import kmz_cambios
    con, admin, editor, carpeta = mundo
    antes = {"nombre": "MF UNO", "lat": 12.13, "lon": -86.25}
    kmz_cambios.editar(con, admin, clave=importar_kmz.clave_kmz("RED/MUFAS", "MF UNO", 12.13, -86.25), carpeta="RED/MUFAS", tipo="punto", antes=antes, nombre="MF UNO CORREGIDA")
    kmz_cambios.borrar(con, admin, clave=importar_kmz.clave_kmz("RED/POSTES DE CONCRETO", "P3", 12.133, -86.253), carpeta="RED/POSTES DE CONCRETO", tipo="punto",
                       antes={"nombre": "P3", "lat": 12.133, "lon": -86.253})
    assert incorporar_kmz.previa(con, admin)["manuales"] == 2
    incorporar_kmz.incorporar(con, admin)
    nombres = _nombres((carpeta / "RED.kmz").read_bytes())
    assert "MF UNO CORREGIDA" in nombres and "MF UNO" not in nombres and "P3" not in nombres


def test_applying_as_an_administrator_updates_the_network_file_straight_away(mundo):
    """«Aplicar» (as an administrator) no longer leaves a layer of imported: the file of the network gets the changes in its folders at once."""
    con, admin, editor, carpeta = mundo
    imp = importar_kmz.importar(con, admin, datos=b64(hacer_kmz(ACTUALIZACION, "RED")), nombre="red_nueva.kmz", modo="actualizacion")["importacion"]
    importar_kmz.aceptar(con, admin, id=imp["id"], aceptado=True, clase="eliminado")
    antes = (carpeta / "RED.kmz").read_bytes()
    r = importar_kmz.aplicar(con, admin, id=imp["id"])
    assert r["incorporada"] is True and r["incorporacion"]["agregados"] >= 3 and r["importacion"]["incorporada"] is True and "aviso_incorporacion" not in r
    despues = (carpeta / "RED.kmz").read_bytes()
    assert "MF CINCO" in _nombres(despues, "RED/MUFAS") and "P4" not in _nombres(despues) and _nombres(despues, "RED/NODOS NUEVOS") == ["NODO JALAPA"]
    assert list((carpeta / "anteriores").glob("*RED.kmz"))[0].read_bytes() == antes                   # the file it had is kept
    assert importar_kmz.elementos_importados(con) == [] and con.execute("SELECT count(*) AS n FROM redes.kmz_cambios WHERE borrado_en IS NULL").fetchone()["n"] == 0
    assert importar_kmz.listar(con, admin)["importaciones"][0]["es_ultima_aplicada"] is False         # nothing to revert from the program: the old file is in «anteriores»


def test_an_editor_still_applies_as_layers_and_a_failure_to_update_the_file_falls_back(mundo, monkeypatch):
    con, admin, editor, carpeta = mundo
    imp = importar_kmz.importar(con, editor, datos=b64(hacer_kmz(ACTUALIZACION, "RED")), nombre="red_nueva.kmz", modo="actualizacion")["importacion"]
    r = importar_kmz.aplicar(con, editor, id=imp["id"])
    assert r["incorporada"] is False and "aviso_incorporacion" not in r                                # not an administrator: the file is not touched
    assert importar_kmz.elementos_importados(con)                                                       # the new ones are the layer of imported, as before
    assert not (carpeta / "anteriores").exists()
    # an administrator, but the file cannot be updated: the import is applied as layers and the reason is told
    imp2 = importar_kmz.importar(con, admin, datos=b64(hacer_kmz({"NUEVA": [_pm("N1", -86.7, 12.7)]}, "RED")), nombre="ruta.kmz")["importacion"]

    def roto(*a, **k):
        raise db.DatosInvalidos({"red": "no hay cómo escribir el archivo"})
    monkeypatch.setattr(incorporar_kmz, "incorporar", roto)
    r2 = importar_kmz.aplicar(con, admin, id=imp2["id"])
    assert r2["incorporada"] is False and "no hay cómo escribir" in r2["aviso_incorporacion"] and r2["importacion"]["estado"] == "aplicada"
    assert any(e["nombre"] == "N1" for e in importar_kmz.elementos_importados(con))                    # it stays as a layer, nothing lost
