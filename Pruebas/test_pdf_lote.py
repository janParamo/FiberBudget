"""PDF de presupuestos que ya existen: Excel sueltos y carpetas de coordenadas masivas (visor_rutas/pdf_lote.py)."""
import base64
import io
import time
import zipfile
from pathlib import Path

import pytest

from visor_rutas import pdf_lote


@pytest.fixture
def carpeta(tmp_path):
    base = tmp_path / "visor"
    (base / "masivo_20261026-091704_Tiendas_Matagalpa").mkdir(parents=True)
    for g, nombres in (("aprobados", ("A1", "A2")), ("desaprobados", ("D1",))):
        (base / "masivo_20261026-091704_Tiendas_Matagalpa" / g).mkdir()
        for n in nombres:
            (base / "masivo_20261026-091704_Tiendas_Matagalpa" / g / f"T-1_{n}.xlsx").write_bytes(b"x")
    (base / "masivo_20261026-091704_Tiendas_Matagalpa" / "Resumen.xlsx").write_bytes(b"x")
    (base / "masivo_20261023-140145_Esteli").mkdir()                                  # a batch from before the two folders
    for n in ("E1", "E2"):
        (base / "masivo_20261023-140145_Esteli" / f"{n}.xlsx").write_bytes(b"x")
    (base / "masivo_20261023-140145_Esteli" / "Resumen.xlsx").write_bytes(b"x")
    (base / "masivo_20261023-140145_Esteli" / "E1.pdf").write_bytes(b"%PDF")        # one already made by hand
    for n in ("Suelto_1_12.1_-86.2_20261020-100000.xlsx", "Suelto_2_12.1_-86.2_20261021-100000.xlsx"):
        (base / n).write_bytes(b"x")
    return base


def test_the_batch_folders_are_listed_with_their_groups(carpeta):
    lotes = pdf_lote.carpetas(carpeta)
    assert [l["id"] for l in lotes] == ["masivo_20261026-091704_Tiendas_Matagalpa", "masivo_20261023-140145_Esteli"]       # newest first
    nuevo, viejo = lotes
    assert nuevo["nombre"] == "Tiendas Matagalpa" and nuevo["fecha"] == "2026-10-26 09:17" and nuevo["xlsx"] == 3          # the Resumen is not a budget
    assert [(g["nombre"], g["xlsx"], g["pdf"]) for g in nuevo["grupos"]] == [("aprobados", 2, 0), ("desaprobados", 1, 0)]
    assert [(g["id"], g["xlsx"], g["pdf"], g["destino"]) for g in viejo["grupos"]] == [("masivo_20261023-140145_Esteli", 2, 1, "pdf")]


def test_the_plan_puts_each_pdf_where_it_belongs(carpeta):
    lote = "masivo_20261026-091704_Tiendas_Matagalpa"
    plan = pdf_lote.planificar(carpeta, ["Suelto_1_12.1_-86.2_20261020-100000.xlsx"], [f"{lote}/aprobados", "masivo_20261023-140145_Esteli"])
    assert [(c, d.relative_to(carpeta.resolve()).as_posix()) for c, _, d in plan] == [
        ("Suelto_1_12.1_-86.2_20261020-100000.xlsx", "."),
        (f"{lote}/aprobados/T-1_A1.xlsx", f"{lote}/aprobados_pdf"), (f"{lote}/aprobados/T-1_A2.xlsx", f"{lote}/aprobados_pdf"),
        ("masivo_20261023-140145_Esteli/E1.xlsx", "masivo_20261023-140145_Esteli/pdf"), ("masivo_20261023-140145_Esteli/E2.xlsx", "masivo_20261023-140145_Esteli/pdf")]
    assert pdf_lote.planificar(carpeta, [], [lote])[-1][2].name == "desaprobados_pdf"
    for malo in ([["../fuera.xlsx"], []], [["C:/x.xlsx"], []], [["a.txt"], []], [[], ["otra"]], [[], ["masivo_x/otra"]], [[], []]):
        with pytest.raises(ValueError):
            pdf_lote.planificar(carpeta, *malo)


def test_a_job_converts_in_the_background_keeps_going_after_an_error_and_zips_the_pdfs(carpeta):
    lote = "masivo_20261026-091704_Tiendas_Matagalpa"
    plan = pdf_lote.planificar(carpeta, ["Suelto_1_12.1_-86.2_20261020-100000.xlsx"], [lote])

    def convertir(xlsx, destino):
        if xlsx.name.endswith("A2.xlsx"):
            raise RuntimeError("LibreOffice falló")
        destino.mkdir(parents=True, exist_ok=True)
        pdf = destino / (xlsx.stem + ".pdf")
        pdf.write_bytes(b"%PDF")
        return pdf
    g = pdf_lote.GestorPdf()
    trabajo = g.iniciar(carpeta, plan, convertir)
    with pytest.raises(ValueError):
        g.iniciar(carpeta, plan, convertir) if trabajo.estado == "convirtiendo" else (_ for _ in ()).throw(ValueError("ya terminó"))
    t0 = time.time()
    while g.obtener(trabajo.id).estado == "convirtiendo" and time.time() - t0 < 10:
        time.sleep(0.02)
    pub = g.obtener(trabajo.id).publico()
    assert (pub["estado"], pub["hechos"], pub["total"], pub["pdf"], pub["fallos"]) == ("listo", 4, 4, 3, ["T-1_A2.xlsx"])
    assert sorted(pub["carpetas_salida"]) == ["aprobados_pdf", "desaprobados_pdf", "visor"]
    nombre, datos = g.comprimir(trabajo.id)
    assert nombre.endswith(".zip") and sorted(zipfile.ZipFile(io.BytesIO(datos)).namelist()) == [
        "Suelto_1_12.1_-86.2_20261020-100000.pdf", f"{lote}/aprobados_pdf/T-1_A1.pdf", f"{lote}/desaprobados_pdf/T-1_D1.pdf"]
    with pytest.raises(KeyError):
        g.obtener("nada")


def test_the_api_of_the_viewer_lists_converts_and_downloads(carpeta, monkeypatch):
    import pdf_export
    import recalc
    from visor_rutas import presupuesto_visor
    from visor_rutas.ventana_web import Api
    monkeypatch.setattr(presupuesto_visor, "carpeta_visor", lambda: carpeta)
    monkeypatch.setattr(recalc, "find_soffice", lambda *a, **k: "soffice")
    monkeypatch.setattr(pdf_export, "xlsx_a_pdf", lambda x, s, carpeta_pdf=None: (carpeta_pdf or x.parent).mkdir(parents=True, exist_ok=True) or
                        (carpeta_pdf or x.parent).joinpath(x.stem + ".pdf").write_bytes(b"%PDF") and (carpeta_pdf or x.parent) / (x.stem + ".pdf"))
    api = Api()
    assert [c["nombre"] for c in api.pdf_carpetas()["carpetas"]] == ["Tiendas Matagalpa", "Esteli"]
    suelto = str(carpeta / "Suelto_2_12.1_-86.2_20261021-100000.xlsx")                    # the history gives absolute paths
    r = api.pdf_convertir([suelto], ["masivo_20261026-091704_Tiendas_Matagalpa/desaprobados"])
    assert r["ok"] and r["trabajo"]["total"] == 2
    t0 = time.time()
    while api.pdf_estado(r["trabajo"]["id"])["trabajo"]["estado"] == "convirtiendo" and time.time() - t0 < 10:
        time.sleep(0.02)
    assert api.pdf_estado(r["trabajo"]["id"])["trabajo"]["estado"] == "listo"
    z = api.pdf_descargar(r["trabajo"]["id"])
    assert z["ok"] and sorted(zipfile.ZipFile(io.BytesIO(base64.b64decode(z["datos"]))).namelist()) == [
        "Suelto_2_12.1_-86.2_20261021-100000.pdf", "masivo_20261026-091704_Tiendas_Matagalpa/desaprobados_pdf/T-1_D1.pdf"]
    assert api.pdf_convertir([str(carpeta.parent / "fuera.xlsx")], [])["ok"] is False and api.pdf_convertir([], ["x"])["ok"] is False
    assert api.pdf_estado("no")["ok"] is False and api.pdf_descargar("no")["ok"] is False


def test_files_and_folders_chosen_in_the_explorer_are_converted_where_they_are(tmp_path, monkeypatch):
    import pdf_export
    import recalc
    from visor_rutas import presupuesto_visor
    from visor_rutas.ventana_web import Api
    managua = tmp_path / "Presupuestos" / "Managua"
    for g, ns in (("aprobados", ("A1", "A2")), ("desaprobados", ("D1",)), ("otra", ("O1",))):
        (managua / g).mkdir(parents=True)
        for n in ns:
            (managua / g / f"{n}.xlsx").write_bytes(b"x")
    (managua / "Resumen.xlsx").write_bytes(b"x")
    (managua / "aprobados_pdf").mkdir()
    (managua / "aprobados_pdf" / "viejo.xlsx").write_bytes(b"x")                        # a *_pdf folder inside a chosen folder is never read again
    suelto = tmp_path / "Presupuestos" / "uno.xlsx"
    suelto.write_bytes(b"x")
    plan = pdf_lote.planificar_externo([str(suelto)], [str(managua)])
    assert [(r.relative_to(tmp_path).as_posix(), d.relative_to(tmp_path).as_posix(), c) for c, r, d in plan] == [
        ("Presupuestos/uno.xlsx", "Presupuestos", None),
        ("Presupuestos/Managua/aprobados/A1.xlsx", "Presupuestos/Managua/aprobados_pdf", None), ("Presupuestos/Managua/aprobados/A2.xlsx", "Presupuestos/Managua/aprobados_pdf", None),
        ("Presupuestos/Managua/desaprobados/D1.xlsx", "Presupuestos/Managua/desaprobados_pdf", None), ("Presupuestos/Managua/otra/O1.xlsx", "Presupuestos/Managua/otra/pdf", None)]
    for malo in ([[str(tmp_path / "no.xlsx")], []], [[str(tmp_path / "x.txt")], []], [[], [str(tmp_path / "nada")]]):
        with pytest.raises(ValueError):
            pdf_lote.planificar_externo(*malo)
    # through the API of the viewer
    monkeypatch.setattr(presupuesto_visor, "carpeta_visor", lambda: tmp_path / "visor")
    monkeypatch.setattr(recalc, "find_soffice", lambda *a, **k: "soffice")
    monkeypatch.setattr(pdf_export, "xlsx_a_pdf", lambda x, s, carpeta_pdf=None: (carpeta_pdf.mkdir(parents=True, exist_ok=True), (carpeta_pdf / (x.stem + ".pdf")).write_bytes(b"%PDF"))[0] or carpeta_pdf / (x.stem + ".pdf"))
    api = Api()
    r = api.pdf_convertir([], [], {"archivos": [str(suelto)], "carpetas": [str(managua)]})
    assert r["ok"] and r["trabajo"]["total"] == 5
    t0 = time.time()
    while api.pdf_estado(r["trabajo"]["id"])["trabajo"]["estado"] == "convirtiendo" and time.time() - t0 < 10:
        time.sleep(0.02)
    assert (managua / "aprobados_pdf" / "A1.pdf").is_file() and (managua / "desaprobados_pdf" / "D1.pdf").is_file() and (suelto.parent / "uno.pdf").is_file()
    z = api.pdf_descargar(r["trabajo"]["id"])
    assert z["ok"] and len(zipfile.ZipFile(io.BytesIO(base64.b64decode(z["datos"]))).namelist()) == 5
    assert api.pdf_convertir([], [], {})["ok"] is False                                          # nothing chosen
    assert api.pdf_elegir("archivos")["ok"] is False                                              # no window in the tests
