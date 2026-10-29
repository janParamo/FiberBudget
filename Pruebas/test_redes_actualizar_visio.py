"""Actualizar los diagramas Visio desde el programa (visor_rutas/redes/actualizar_visio.py): subir el archivo (o un .zip), reemplazar el del mismo nombre guardando el anterior, y
correr el importador en segundo plano con su avance."""
import io
import sys
import time
import zipfile

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas import subidas
from visor_rutas.redes import actualizar_visio, db, usuarios
from visor_rutas.redes.api import METODOS

VSDX = b"PK\x03\x04" + b"visio-1" * 20
VSDX_2 = b"PK\x03\x04" + b"visio-2" * 20
VSD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"viejo" * 20


@pytest.fixture
def origen(tmp_path, monkeypatch):
    carpeta = tmp_path / "visio" / "DIAGRAMAS ACTUALIZADOS"
    (carpeta / "Jinotega").mkdir(parents=True)
    (carpeta / "Jinotega" / "MUFA BANCO.vsdx").write_bytes(VSDX)
    monkeypatch.setenv("VISIO_ORIGEN", str(carpeta))
    return carpeta


@pytest.fixture
def admin(con_redes):
    return con_redes, usuarios.identificar(con_redes, usuario_windows="jgutierrez")


def _subir(nombre, datos):
    """An upload as the page makes it (by parts), ready for `subir_visio`."""
    id_ = subidas.almacen.iniciar(nombre, len(datos))
    subidas.almacen.parte(id_, 0, datos)
    subidas.almacen.terminar(id_)
    return id_


def test_a_file_with_the_same_name_is_replaced_in_place_and_the_old_one_is_kept(origen, admin):
    con, actor = admin
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("MUFA BANCO.vsdx", VSDX_2))
    assert r["reemplazados"] == ["Jinotega/MUFA BANCO.vsdx"] and r["nuevos"] == [] and r["rechazados"] == []
    assert (origen / "Jinotega" / "MUFA BANCO.vsdx").read_bytes() == VSDX_2                             # the same place, the new content
    guardado = list((origen.parent / "anteriores").rglob("MUFA BANCO.vsdx"))
    assert len(guardado) == 1 and guardado[0].read_bytes() == VSDX                                        # the old one, aside
    assert not list(origen.rglob("*.tmp"))
    # the same content again: nothing to do (not a second copy of the old one)
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("MUFA BANCO.vsdx", VSDX_2))
    assert r["reemplazados"] == [] and "idéntico" in r["rechazados"][0]["motivo"]


def test_a_new_name_is_added_in_the_chosen_folder_and_bad_files_are_refused_with_the_reason(origen, admin):
    con, actor = admin
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("MUFA PUERTO PAZ 2.vsd", VSD), carpeta="Jinotega/Nuevos 2026")
    assert r["nuevos"] == ["Jinotega/Nuevos 2026/MUFA PUERTO PAZ 2.vsd"] and (origen / "Jinotega" / "Nuevos 2026" / "MUFA PUERTO PAZ 2.vsd").read_bytes() == VSD
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("SIN CARPETA.vsdx", VSDX))
    assert r["nuevos"] == ["Nuevos/SIN CARPETA.vsdx"]                                                    # the default folder
    for nombre, datos, texto in (("nota.docx", b"PK\x03\x04xx", "solo se aceptan"), ("roto.vsdx", b"no es un zip", "dañado"), ("~$temporal.vsdx", VSDX, "temporal"),
                                 ("vacio.vsdx", b"", "vacío")):
        # an empty file cannot even be uploaded: it is tested straight on the check
        motivo = actualizar_visio._valido(nombre, datos)
        assert motivo and texto in motivo, (nombre, motivo)
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("roto.vsdx", b"esto no es un vsdx"))
    assert r["nuevos"] == [] and "dañado" in r["rechazados"][0]["motivo"]
    assert not (origen / "Nuevos" / "roto.vsdx").exists()
    # the carpeta name cannot climb out of the diagrams folder
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("ESCAPE.vsdx", VSDX), carpeta="../../fuera")
    assert (origen / "fuera" / "ESCAPE.vsdx").is_file() and not list(origen.parent.parent.rglob("ESCAPE.vsdx"))[1:]


def test_a_zip_with_many_files_replaces_the_ones_that_exist_and_adds_the_others(origen, admin):
    con, actor = admin
    contenido = io.BytesIO()
    with zipfile.ZipFile(contenido, "w") as z:
        z.writestr("DIAGRAMAS ACTUALIZADOS/Jinotega/MUFA BANCO.vsdx", VSDX_2)       # exists (in another folder of the zip): replaced where it is
        z.writestr("Jinotega/MUFA NUEVA.vsd", VSD)                                    # new: in the folder it comes in
        z.writestr("LEEME.txt", b"nada")                                              # not a diagram: ignored
        z.writestr("../../peligro.vsdx", VSDX)                                        # tries to climb out: only its name counts
    r = actualizar_visio.subir_visio(con, actor, subida_id=_subir("lote.zip", contenido.getvalue()))
    assert r["reemplazados"] == ["Jinotega/MUFA BANCO.vsdx"] and "Jinotega/MUFA NUEVA.vsd" in r["nuevos"] and "Nuevos/peligro.vsdx" in r["nuevos"]
    assert (origen / "Jinotega" / "MUFA BANCO.vsdx").read_bytes() == VSDX_2 and not (origen.parent.parent / "peligro.vsdx").exists()
    with pytest.raises(db.DatosInvalidos):
        actualizar_visio.subir_visio(con, actor, subida_id=_subir("roto.zip", b"PK\x03\x04no-es-un-zip"))


def test_only_an_administrator_and_not_while_updating(origen, admin, con_redes):
    con, actor = admin
    ana = usuarios.identificar(con, persona_visor="ana")
    for accion in (lambda: actualizar_visio.estado(con, ana), lambda: actualizar_visio.subir_visio(con, ana, subida_id="x"), lambda: actualizar_visio.actualizar_diagramas(con, ana),
                   lambda: actualizar_visio.progreso(con, ana)):
        with pytest.raises(db.SinPermiso):
            accion()
    e = actualizar_visio.estado(con, actor)
    assert e["archivos"] == 1 and e["visio"] == 1 and e["carpeta"] == str(origen) and e["actualizacion"] is None
    for m in ("visio_estado", "visio_subir", "visio_actualizar", "visio_progreso"):
        assert m in METODOS


def _esperar_fin(con, actor, segundos=15):
    limite = time.time() + segundos
    while time.time() < limite:
        a = actualizar_visio.progreso(con, actor)["actualizacion"]
        if a and not a["activa"] and a["codigo"] is not None:
            return a
        time.sleep(0.1)
    raise AssertionError("el importador no terminó")


def test_the_importer_runs_in_the_background_and_reports_its_steps(origen, admin, monkeypatch):
    con, actor = admin
    guion = "import time; print('1/5 Inventario de archivos...'); print('   1 archivos'); print('2/5 Conversión Visio -> ODG: 1 pendientes'); time.sleep(1.2); print('5/5 Publicando'); print('LISTO')"
    monkeypatch.setattr(actualizar_visio, "_comando", lambda origen_: [sys.executable, "-c", guion])
    r = actualizar_visio.actualizar_diagramas(con, actor)
    assert r["actualizacion"]["activa"] is True
    with pytest.raises(db.DatosInvalidos):                                                              # one at a time
        actualizar_visio.actualizar_diagramas(con, actor)
    with pytest.raises(db.DatosInvalidos):                                                              # and no uploads meanwhile
        actualizar_visio.subir_visio(con, actor, subida_id=_subir("OTRA.vsdx", VSDX))
    fin = _esperar_fin(con, actor)
    assert fin["codigo"] == 0 and fin["paso"] == {"n": 5, "de": 5, "texto": "Publicando"} and fin["ultimas"][-1] == "LISTO" and fin["por"]
    # it can be started again, and a failure is reported with its exit code
    monkeypatch.setattr(actualizar_visio, "_comando", lambda origen_: [sys.executable, "-c", "print('1/5 Inventario'); import sys; print('Traceback...'); sys.exit(3)"])
    actualizar_visio.actualizar_diagramas(con, actor)
    assert _esperar_fin(con, actor)["codigo"] == 3


def test_it_needs_diagrams_in_the_folder(tmp_path, admin, monkeypatch):
    con, actor = admin
    monkeypatch.setenv("VISIO_ORIGEN", str(tmp_path / "vacia"))
    with pytest.raises(db.DatosInvalidos):
        actualizar_visio.actualizar_diagramas(con, actor)
