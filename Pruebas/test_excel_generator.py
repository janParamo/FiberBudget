import pytest



def test_the_money_cells_of_the_totals_shrink_to_fit_instead_of_showing_hashes(tmp_path):
    """The PDF is made on a server without the template's font (Century Gothic): a wider font made «TOTAL ###». The total cells shrink their text to fit."""
    import zipfile
    from pathlib import Path

    from openpyxl import load_workbook

    import excel_generator as g
    plantilla = Path(__file__).resolve().parent.parent / "templates" / "Plantilla.xlsx"
    if not plantilla.is_file():
        pytest.skip("the company template is not in the repository")
    with zipfile.ZipFile(plantilla) as z:
        hoja = g._sheet_paths(z)["Presupuesto"]
    salida = tmp_path / "x.xlsx"
    g._write_cells_preserving_package(plantilla, salida, {hoja: {}}, {hoja: g.SHRINK_TO_FIT_CELLS})
    ws = load_workbook(salida)["Presupuesto"]
    assert ws["I57"].alignment.shrink_to_fit and ws["I53"].alignment.shrink_to_fit
    assert ws["I57"].font.sz == 12 and ws["I57"].number_format.startswith('_-"C$"')            # the rest of its format is the template's
    assert not ws["I34"].alignment.shrink_to_fit                                                 # the other cells are as they were


def test_a_cell_format_copy_with_shrink_keeps_the_rest_of_the_format():
    import excel_generator as g
    estilos = '<styleSheet><cellXfs count="2"><xf numFmtId="0" fontId="0"/><xf numFmtId="4" fontId="1" applyAlignment="1"><alignment horizontal="center"/></xf></cellXfs></styleSheet>'
    nuevo, mapa = g._with_shrink_to_fit(estilos, [0, 1, 7])
    assert mapa == {0: 2, 1: 3}                                                                  # an index that does not exist is skipped
    assert 'count="4"' in nuevo
    assert '<xf numFmtId="0" fontId="0" applyAlignment="1"><alignment shrinkToFit="1"/></xf>' in nuevo or 'shrinkToFit="1"' in nuevo
    assert '<alignment shrinkToFit="1" horizontal="center"/>' in nuevo
