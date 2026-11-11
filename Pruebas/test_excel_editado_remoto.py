"""Modo remoto: el Excel que se abre desde el visor es una COPIA descargada y el PDF lo hace el servidor con SU Excel. Lo que se edita y se guarda en la copia sube al servidor
(antes de pedir el PDF y al volver a la ventana del visor) para que las hojas y el PDF salgan con los cambios."""
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
import recalc
import visor_api
from test_visor_api import CAMPOS, JAN, _api_remota, entorno  # noqa: F401  (fixture)
from visor_rutas import presupuesto_visor
from visor_rutas.remoto import ErrorRemoto

SOFFICE = recalc.find_soffice(None)


def _editar(ruta, celda="E1", valor="EDITADO POR LA PERSONA"):
    libro = load_workbook(ruta)
    libro["Presupuesto"][celda] = valor
    libro.save(ruta)
    libro.close()


def _generar(entorno, tmp_path):
    main_, _, _, salida, _ = entorno
    remota = _api_remota(main_, tmp_path)
    pres = remota.generar_presupuesto(CAMPOS)
    assert pres["ok"], pres
    archivo, id_ = pres["resultado"]["archivo"], pres["resultado"]["id"]
    assert remota.hoja_excel(archivo, "Presupuesto", True)["ok"]                      # downloads the copy (and notes what the server has)
    return remota, archivo, id_, salida / "visor" / f"{id_}.xlsx"


def test_an_edit_saved_in_the_downloaded_excel_goes_up_and_the_server_version_changes(entorno, tmp_path):
    remota, archivo, id_, servidor = _generar(entorno, tmp_path)
    proveedor = remota._remoto
    local = proveedor.carpeta / "descargas" / f"{id_}.xlsx"
    subidas = []
    pedir = proveedor._pedir
    proveedor._pedir = lambda metodo, ruta, **kw: (subidas.append((metodo, ruta)) if metodo == "PUT" else None) or pedir(metodo, ruta, **kw)
    antes = remota.abrir_presupuesto_guardado(archivo)["resultado"]["version"]
    assert subidas == [] and proveedor.sincronizar_excel(archivo) is False                  # nothing edited: nothing goes up
    _editar(local)                                                                         # the person edits the copy in Excel and saves
    despues = remota.abrir_presupuesto_guardado(archivo)                                   # what the viewer asks when its window comes back
    assert despues["ok"] and despues["resultado"]["version"] != antes                       # the server has a new version: the page refreshes what it shows
    assert subidas == [("PUT", f"/visor/presupuestos/{id_}/excel")] and servidor.read_bytes() == local.read_bytes()
    assert load_workbook(servidor)["Presupuesto"]["E1"].value == "EDITADO POR LA PERSONA"
    remota.abrir_presupuesto_guardado(archivo)
    assert len(subidas) == 1                                                                # the same file is not uploaded again
    # and the sheet drawn in the viewer is the edited one
    assert "EDITADO POR LA PERSONA" in remota.hoja_excel(archivo, "Presupuesto", True)["html"]


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice not installed")
def test_the_pdf_comes_out_of_the_edited_excel_and_a_pdf_made_before_is_not_reused(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr(recalc, "find_soffice", lambda *a, **k: SOFFICE)
    remota, archivo, id_, servidor = _generar(entorno, tmp_path)
    proveedor = remota._remoto
    local = proveedor.carpeta / "descargas" / f"{id_}.xlsx"
    primero = remota.pdf_presupuesto(archivo)
    assert primero["ok"], primero
    pdf_local = proveedor.carpeta / "descargas" / f"{id_}.pdf"
    assert pdf_local.is_file()
    _editar(local, "E1", "TEXTO NUEVO DE LA PERSONA")
    segundo = remota.pdf_presupuesto(archivo)                                               # asking for the PDF applies the changes first
    assert segundo["ok"], segundo
    assert servidor.read_bytes() == local.read_bytes()                                      # the server made it from the edited Excel
    assert segundo["base64"] != primero["base64"]                                           # not the one made before


def test_when_the_changes_cannot_go_up_the_pdf_says_so_instead_of_coming_without_them(entorno, tmp_path):
    remota, archivo, id_, servidor = _generar(entorno, tmp_path)
    proveedor = remota._remoto
    _editar(proveedor.carpeta / "descargas" / f"{id_}.xlsx")
    pedir = proveedor._pedir

    def falla(metodo, ruta, **kw):
        if metodo == "PUT":
            raise ErrorRemoto("No se pudo conectar con el servidor")
        return pedir(metodo, ruta, **kw)
    proveedor._pedir = falla
    r = remota.pdf_presupuesto(archivo)
    assert r["ok"] is False and "cambios del Excel" in r["error"]
    assert "EDITADO" not in str(load_workbook(servidor)["Presupuesto"]["E1"].value)           # the server still has the old one, and the person knows


def test_the_server_only_takes_a_real_budget_excel_of_an_existing_budget(entorno, tmp_path):
    main_, _, cliente, salida, _ = entorno
    remota, archivo, id_, servidor = _generar(entorno, tmp_path)
    original = servidor.read_bytes()
    url = f"/visor/presupuestos/{id_}/excel"
    assert cliente.put(url, content=b"esto no es un excel", headers=JAN).status_code == 400
    assert cliente.put(url, content=b"", headers=JAN).status_code == 400
    otro = io.BytesIO()
    libro = Workbook()
    libro.active.title = "Otra cosa"
    libro.save(otro)
    r = cliente.put(url, content=otro.getvalue(), headers=JAN)
    assert r.status_code == 400 and "Presupuesto" in r.json()["detail"]                            # a workbook without the two sheets of a budget
    assert cliente.put("/visor/presupuestos/no_existe/excel", content=original, headers=JAN).status_code == 404
    assert cliente.put(url, content=original).status_code == 401                                    # with the key of the viewer
    assert cliente.put("/visor/presupuestos/..%2Fsecreto/excel", content=original, headers=JAN).status_code in (404, 400)
    assert servidor.read_bytes() == original                                                        # nothing changed
    ok = cliente.put(url, content=original, headers=JAN)
    assert ok.status_code == 200 and ok.json()["ok"] is True and ok.json()["version"]
    assert [p.name for p in servidor.parent.iterdir() if p.suffix == ".tmp" or p.name.startswith("tmp")] == []   # no temporary file is left


def test_it_is_part_of_making_a_budget_for_guest_and_not_for_the_read_only_role():
    ruta = "/visor/presupuestos/Cliente_1/excel"
    assert visor_api.permitido("guest", "PUT", ruta) and visor_api.permitido("administrador", "PUT", ruta) and visor_api.permitido(None, "PUT", ruta)
    assert not visor_api.permitido("prueba", "PUT", ruta)                                           # prueba only reads
    assert not visor_api.permitido("guest", "PUT", "/visor/presupuestos/Cliente_1")                 # only the Excel
    assert not visor_api.permitido("guest", "DELETE", ruta)


def test_a_copy_that_was_never_downloaded_here_has_nothing_to_apply(entorno, tmp_path):
    main_, _, _, _, _ = entorno
    remota = _api_remota(main_, tmp_path)
    assert remota._remoto.sincronizar_excel("remoto:nunca_descargado") is False
    assert remota._remoto.sincronizar_excel("../raro") is False


def test_a_copy_downloaded_before_the_viewer_kept_its_note_also_applies_its_edits(entorno, tmp_path):
    remota, archivo, id_, servidor = _generar(entorno, tmp_path)
    proveedor = remota._remoto
    local = proveedor.carpeta / "descargas" / f"{id_}.xlsx"
    proveedor._marca(id_).unlink()                                                          # a copy of an older version of the viewer: no note
    assert proveedor.sincronizar_excel(archivo) is False and proveedor._marca(id_).is_file()   # not edited: the note is made from the server's file, nothing goes up
    proveedor._marca(id_).unlink()
    _editar(local)
    assert proveedor.sincronizar_excel(archivo) is True                                      # edited: it goes up
    assert load_workbook(servidor)["Presupuesto"]["E1"].value == "EDITADO POR LA PERSONA"
