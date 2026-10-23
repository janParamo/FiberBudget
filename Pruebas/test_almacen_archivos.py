"""Files in PostgreSQL (visor_rutas/almacen_archivos.py, migration 019): the database is the source and the local folders are a cache.
Each integration is checked by deleting the local copy and asking for it again."""
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_kmz_capas import crear_kmz, sin_internet  # noqa: F401  (sin_internet: fixture)
from visor_rutas import almacen_archivos as alm
from visor_rutas.redes import db


@pytest.fixture
def almacen_pruebas(con_redes, base_redes, monkeypatch):
    """The store pointed at the throw-away database (the conftest switches the real one off)."""
    _, params = base_redes
    con_redes.execute("TRUNCATE redes.almacen_archivos")
    monkeypatch.setattr(alm, "ACTIVO", True)
    monkeypatch.setattr(alm, "habilitado", lambda: True)       # other tests may leave get_settings() without a database
    monkeypatch.setattr(alm, "_abrir", lambda: db.conectar(params=params))
    return con_redes


def test_store_read_list_and_delete_files(almacen_pruebas):
    assert alm.guardar("odg", "a.odg", b"uno") and alm.guardar("odg", "carpeta/b.odg", b"dos")
    assert alm.leer("odg", "a.odg") == b"uno" and alm.leer("odg", "nada") is None and alm.leer("kmz", "a.odg") is None
    assert alm.guardar("odg", "a.odg", b"uno-nuevo") and alm.leer("odg", "a.odg") == b"uno-nuevo"      # replaced, not duplicated
    assert {f["clave"] for f in alm.listar("odg")} == {"a.odg", "carpeta/b.odg"}
    assert {f["clave"] for f in alm.listar("odg", "carpeta/")} == {"carpeta/b.odg"}
    assert alm.info("odg", "a.odg")["tamano"] == len(b"uno-nuevo") and alm.existe("odg", "carpeta/b.odg")
    assert alm.resumen()["odg"] == {"archivos": 2, "bytes": len(b"uno-nuevo") + 3}
    assert alm.borrar("odg", "a.odg") and not alm.existe("odg", "a.odg")


def test_keys_and_spaces_are_validated():
    for mala in ("", "..", "../x", "a/../b", "C:/x", "/"):
        with pytest.raises(ValueError):
            alm.clave_segura(mala)
    assert alm.clave_segura("\\a\\b.txt") == "a/b.txt"
    with pytest.raises(ValueError):
        alm.guardar("otro", "x", b"")


def test_restore_writes_the_file_only_when_it_is_missing(almacen_pruebas, tmp_path):
    alm.guardar("odg", "sub/x.odg", b"contenido")
    destino = tmp_path / "sub" / "x.odg"
    assert alm.restaurar("odg", "sub/x.odg", destino) and destino.read_bytes() == b"contenido"
    destino.write_bytes(b"local")
    assert alm.restaurar("odg", "sub/x.odg", destino) and destino.read_bytes() == b"local"            # an existing copy is never overwritten
    assert not alm.restaurar("odg", "no-existe", tmp_path / "y")
    assert alm.restaurar_espacio("odg", tmp_path / "otra") == 1 and (tmp_path / "otra" / "sub" / "x.odg").is_file()


def test_uploading_a_folder_sends_only_what_is_new_or_changed(almacen_pruebas, tmp_path):
    (tmp_path / "a.png").write_bytes(b"1")
    (tmp_path / "mapas").mkdir()
    (tmp_path / "mapas" / "m.png").write_bytes(b"mapa")
    (tmp_path / "~$abierto.xlsx").write_bytes(b"x")
    r = alm.subir_carpeta("diagramas", tmp_path, excluir=("mapas",))
    assert (r["subidos"], r["iguales"], r["fallidos"]) == (1, 0, 0) and {f["clave"] for f in alm.listar("diagramas")} == {"a.png"}
    assert alm.subir_carpeta("diagramas", tmp_path, excluir=("mapas",))["iguales"] == 1
    (tmp_path / "a.png").write_bytes(b"12")
    assert alm.subir_carpeta("diagramas", tmp_path, excluir=("mapas",))["subidos"] == 1 and alm.leer("diagramas", "a.png") == b"12"
    alm.guardar("diagramas", "viejo.png", b"v")
    alm.guardar("diagramas", "guardar/esto.json", b"g")
    r = alm.subir_carpeta("diagramas", tmp_path, excluir=("mapas",), borrar_sobrantes=True, conservar=("guardar",))
    assert r["borrados"] == 1 and {f["clave"] for f in alm.listar("diagramas")} == {"a.png", "guardar/esto.json"}


def test_old_files_of_a_space_are_removed(almacen_pruebas):
    alm.guardar("visor", "viejo.xlsx", b"1")
    alm.guardar("visor", "nuevo.xlsx", b"2")
    almacen_pruebas.execute("UPDATE redes.almacen_archivos SET creado_en = now() - interval '40 days' WHERE clave = 'viejo.xlsx'")
    assert alm.borrar_viejos("visor", 30) == 1 and {f["clave"] for f in alm.listar("visor")} == {"nuevo.xlsx"}


def test_without_a_database_nothing_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(alm, "ACTIVO", False)
    assert not alm.guardar("odg", "x", b"1") and alm.leer("odg", "x") is None and alm.listar("odg") == [] and alm.resumen() == {}
    assert not alm.restaurar("odg", "x", tmp_path / "x") and alm.subir_carpeta("odg", tmp_path)["subidos"] == 0
    monkeypatch.setattr(alm, "ACTIVO", True)

    def _caida():
        raise RuntimeError("sin conexión")
    monkeypatch.setattr(alm, "_abrir", _caida)
    assert not alm.guardar("odg", "x", b"1") and alm.leer("odg", "x") is None


# --------------------------------------------------------------------------- the integrations

def test_visor_budgets_come_back_from_the_database(almacen_pruebas, tmp_path, monkeypatch):
    from openpyxl import Workbook

    from visor_rutas import presupuesto_visor as pv
    carpeta = tmp_path / "visor"
    carpeta.mkdir()
    monkeypatch.setattr(pv, "carpeta_visor", lambda: carpeta)
    nombre = "Cliente_Uno_12.136400_-86.251400_20261007-153005.xlsx"
    libro = Workbook()
    libro.active.title = "Presupuesto"
    libro.active["H20"], libro.active["I20"] = "TOTAL", 30.5
    libro.save(carpeta / nombre)
    (carpeta / "mapas").mkdir()
    (carpeta / "mapas" / "m.png").write_bytes(b"png")
    assert pv.subir_a_la_base()["subidos"] == 1 and [f["clave"] for f in alm.listar("visor")] == [nombre]   # the map is not kept
    # a day later the local copy is removed (the database has it); the map goes too
    ayer = time.time() - (pv.LOCAL_HORAS + 1) * 3600
    for ruta in (carpeta / nombre, carpeta / "mapas" / "m.png"):
        os.utime(ruta, (ayer, ayer))
    assert pv.limpiar_archivos_viejos() == 2 and not (carpeta / nombre).exists()
    # the history still lists it and opening it writes it back
    lista = pv.historial()
    assert [x["nombre"] for x in lista] == [nombre] and lista[0]["coordenada"] == "12.136400, -86.251400"
    abierto = pv.abrir_guardado(carpeta / nombre)
    assert abierto["resumen"]["totales"][0]["valor"] == 30.5 and (carpeta / nombre).is_file()
    # a pdf is found by its name too; outside the folder nothing is restored
    alm.guardar("visor", nombre[:-5] + ".pdf", b"%PDF")
    assert [x["tiene_pdf"] for x in pv.historial()] == [True]
    assert pv.archivo_del_visor(carpeta / (nombre[:-5] + ".pdf")).read_bytes() == b"%PDF"
    with pytest.raises(FileNotFoundError):
        pv.archivo_del_visor(tmp_path / "otro.xlsx")
    # without a copy in the database an old file keeps the retention-days rule
    solo = carpeta / "solo_local.xlsx"
    solo.write_bytes(b"x")
    os.utime(solo, (ayer, ayer))
    monkeypatch.setattr(alm, "habilitado", lambda: False)
    assert pv.limpiar_archivos_viejos() == 0 and solo.exists()


def test_diagrams_are_restored_and_converted_ones_are_kept(almacen_pruebas, tmp_path, monkeypatch):
    from visor_rutas import fusion
    md5 = "a" * 32
    monkeypatch.setattr(fusion, "CACHE_ODG", tmp_path / "odg")
    monkeypatch.setattr(fusion, "CACHE_DIAGRAMAS", tmp_path / "png")
    assert not fusion.ruta_odg(md5).is_file()
    alm.guardar("odg", f"{md5}.odg", b"odg-falso")
    assert fusion.ruta_odg(md5).read_bytes() == b"odg-falso"
    assert not fusion.ruta_odg("../../etc").is_file()                       # an invalid id never reaches the store
    # a stored image is used without converting anything
    alm.guardar("diagramas", f"{md5}_0.png", b"png-guardado")
    (tmp_path / "odg" / f"{md5}.odg").unlink()
    assert fusion.diagrama_png(md5).read_bytes() == b"png-guardado"


def test_kmz_and_its_cache_come_back_from_the_database(almacen_pruebas, sin_internet, tmp_path, monkeypatch):
    from visor_rutas import kmz_capas
    datos = tmp_path / "datos_kmz"
    carpeta_kmz = tmp_path / "red_kmz"
    carpeta_kmz.mkdir()
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", datos)
    monkeypatch.setenv("KMZ_PATH", str(carpeta_kmz))
    kmz = crear_kmz(carpeta_kmz / "RED.kmz")
    arbol = kmz_capas.asegurar()
    assert arbol["elementos"] and alm.existe("kmz", "RED.kmz") and alm.existe("datos_kmz", "arbol.json")
    capas = {f["clave"] for f in alm.listar("datos_kmz", "capas/")}
    assert capas and all((datos / c).is_file() for c in capas)
    # the machine loses both copies: the cache and the KMZ file come back from the database
    import shutil
    shutil.rmtree(datos)
    kmz.unlink()
    assert kmz_capas.asegurar()["md5"] == arbol["md5"] and (datos / "arbol.json").is_file() and not kmz.exists()
    # one layer file deleted on its own is restored when the page asks for it
    una = sorted(capas)[0]
    (datos / una).unlink()
    assert kmz_capas.archivo_capa(Path(una).stem).is_file()
    # the KMZ file itself is restored when something asks for it
    assert kmz_capas.ruta_kmz().read_bytes() == alm.leer("kmz", "RED.kmz")
    assert kmz.is_file()


def test_synchronization_records_survive_a_lost_cache(almacen_pruebas, tmp_path, monkeypatch):
    from visor_rutas import kmz_capas
    from visor_rutas.redes import actualizar_red
    datos = tmp_path / "datos_kmz"
    monkeypatch.setattr(kmz_capas, "CARPETA_DATOS", datos)
    registro = {"id": "20261022-120000-000001", "archivo": "RED.kmz", "revertida": False, "insertados": {"puntos": [1], "lineas": []},
                "eliminados": {"puntos": [], "lineas": []}}
    actualizar_red._guardar_registro(actualizar_red._carpeta_sincronizaciones(), registro)
    import shutil
    shutil.rmtree(datos)
    assert [r["id"] for r in actualizar_red._registros()] == [registro["id"]]
