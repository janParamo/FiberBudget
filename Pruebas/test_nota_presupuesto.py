"""comment_note: "Sujeto a disponibilidad de postes de concreto sobre la ruta" goes in the comment of the second sheet, on the line under «*Medio: …», and not any more at the foot
of the two sheets (the old budget_note)."""
import tempfile
from pathlib import Path

from openpyxl import load_workbook

import main
from excel_generator import _comment_cell, _con_nota_bajo_medio, generar_excel
from presupuesto import calcular_presupuesto

NOTA = "Sujeto a disponibilidad de postes de concreto sobre la ruta"
RAIZ = Path(__file__).resolve().parent.parent


def test_the_note_is_a_line_of_the_comment_under_medio_and_the_rest_stays():
    base = "Validar acceso de FO al cliente.\n\n\n*Plan a contratar:  Residencial\n*Ancho de banda: 200 mbps\n*Medio: GPON "
    assert _con_nota_bajo_medio(base, NOTA) == base.rstrip() + "\n" + NOTA
    assert _con_nota_bajo_medio("*Medio: FO\nOtra cosa", NOTA) == f"*Medio: FO\n{NOTA}\nOtra cosa"                 # right under it, wherever it is
    assert _con_nota_bajo_medio("Solo texto", NOTA) == f"Solo texto\n{NOTA}"                                     # no «Medio» line: at the end


def test_the_real_template_gets_the_note_in_the_comment_and_nowhere_else():
    reglas = main.load_rules(RAIZ / "business_rules.yaml")
    assert reglas["comment_note"] == NOTA and "budget_note" not in reglas
    cant = calcular_presupuesto(500, [(12.13, -86.25), (12.14, -86.25)], reglas, service_type="Residencial", bandwidth="10 Mbps", existing_poles=2)

    def generar(**extra):
        datos = {"budget_id": "a", "ticket_id": "T", "client_name": "X", "raw_comment": "", "quantities": cant, "materials": {}, "hardware": {}, "route_fields": {}, **extra}
        return generar_excel(datos, reglas, RAIZ / "templates" / "Plantilla.xlsx", Path(tempfile.mkdtemp())).path
    xlsx = generar(comment_edits={"plan": "Empresarial", "bandwidth": "50 mbps"})
    libro = load_workbook(xlsx)
    comentario = libro["Presupuesto"][_comment_cell(libro["Presupuesto"])].value
    lineas = comentario.split("\n")
    assert lineas[-2].strip().startswith("*Medio:") and lineas[-1] == NOTA and "*Plan a contratar:  Empresarial" in comentario and "*Ancho de banda: 50 mbps" in comentario
    # the two sheets have no such line at the foot any more
    for hoja in (reglas["route_sheet"]["sheet"], "Presupuesto"):
        textos = [c.value for fila in libro[hoja].iter_rows() for c in fila if c.value == NOTA]
        assert textos == [] or hoja == "Presupuesto" and textos == [comentario] and False                      # only inside the comment (a cell with the whole comment), never alone
    # the comment of the ticket, when there is one, goes after the note
    con_ticket = load_workbook(generar(raw_comment="Texto del ticket"))
    texto = con_ticket["Presupuesto"][_comment_cell(con_ticket["Presupuesto"])].value
    assert texto.index(NOTA) < texto.index("Texto del ticket")
