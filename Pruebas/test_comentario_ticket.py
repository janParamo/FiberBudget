"""Los datos de la primera página del Excel (cliente y vendedor) que se leen del comentario del ticket."""
from visor_rutas.comentario_ticket import extraer_campos


def test_one_field_per_line_with_bullets_accents_and_any_case():
    texto = ("*Código cliente: C35307\n* NOMBRE DE CONTACTO: Roxana López\n- Teléfono contacto: 8599 9439\n• Ejecutivo de ventas: Yader Ramírez\n"
             "*Plan a contratar:  Residencial\n*Ancho de banda: 200 mbps\n*Medio: GPON")
    assert extraer_campos(texto) == {"client_code": "C35307", "contact_name": "Roxana López", "contact_phone": "8599 9439", "sales_exec": "Yader Ramírez"}


def test_a_real_ticket_comment():
    texto = ("• Nombre de cliente: David Alberto Tovar Juarez\n• Código de cliente: C35307\n• Persona de contacto: Grace Gutiérrez\n• Teléfono: 85999439\n"
             "• Dirección de instalación: Sucursales de Matagalpa\n• Coordenadas: Direcciones y coordenadas se encuentran en documento adjunto\n"
             "• Medio de Servicio: FO\n• Tipo de servicio: Transmisión de Datos\nAncho de Banda: 20M")
    assert extraer_campos(texto) == {"client_name": "David Alberto Tovar Juarez", "client_code": "C35307", "contact_name": "Grace Gutiérrez", "contact_phone": "85999439"}


def test_several_fields_on_one_line_and_other_labels():
    texto = "Cliente: Ferretería Luna  Codigo de cliente = C100 Contacto: Juan Pérez, Cel: +505 8888-0000 Vendedor: Ana Ticket: TLC-1"
    assert extraer_campos(texto) == {"client_name": "Ferretería Luna", "client_code": "C100", "contact_name": "Juan Pérez", "contact_phone": "+505 8888-0000",
                                     "sales_exec": "Ana", "ticket_id": "TLC-1"}


def test_the_code_label_wins_over_the_client_label_and_missing_or_empty_fields_are_left_out():
    assert extraer_campos("Código cliente: C1\nTeléfono: sin número\nContacto:\nValidar acceso de FO al cliente") == {"client_code": "C1"}
    assert extraer_campos("") == {} and extraer_campos(None) == {} and extraer_campos("Llamar antes de visitar.") == {}


def test_the_first_value_of_a_field_is_kept():
    assert extraer_campos("Teléfono: 8111 1111\nTeléfono: 8222 2222") == {"contact_phone": "8111 1111"}


def test_seller_and_ticket_labels_and_the_bandwidth_in_mbps():
    from visor_rutas.comentario_ticket import ancho_de_banda_mbps
    assert extraer_campos("Vendedor: Yader Ramirez, Ticket: xkj-813-61728") == {"sales_exec": "Yader Ramirez", "ticket_id": "xkj-813-61728"}
    assert [ancho_de_banda_mbps(t) for t in ("Ancho de Banda: 20M", "ancho de banda: 200 mbps", "Ancho de banda: 1G", "Ancho de banda: 2,5 M", "sin dato", None)] == \
        [20, 200, 1000, 2.5, None, None]


def test_the_templates_own_comment_only_changes_the_values_it_has():
    from excel_generator import _con_valor
    base = "Validar acceso de FO al cliente, PP sujeto a cambio.\n\n\n*Plan a contratar:  Residencial\n*Ancho de banda: 200 mbps\n*Medio: GPON "
    nuevo = _con_valor(_con_valor(base, "Ancho de banda", "100 mbps"), "Plan a contratar", "Residencial")
    assert nuevo == base.replace("200 mbps", "100 mbps")
    assert _con_valor("sin esa línea", "Ancho de banda", "100 mbps") == "sin esa línea"


def test_the_real_template_changes_only_the_plan_and_speed_lines_and_the_ticket_comment_goes_after():
    """With templates/Plantilla.xlsx: «*Plan a contratar» and «*Ancho de banda» take the typed values and the rest of the template's comment stays."""
    import tempfile
    from pathlib import Path

    import main
    from excel_generator import _comment_cell, generar_excel
    from openpyxl import load_workbook
    from presupuesto import calcular_presupuesto
    raiz = Path(__file__).parents[1]
    reglas = main.load_rules(raiz / "business_rules.yaml")
    cant = calcular_presupuesto(500, [(12.13, -86.25), (12.14, -86.25)], reglas, service_type="Residencial", bandwidth="10 Mbps", existing_poles=2)

    def comentario(**extra):
        datos = {"budget_id": "a", "ticket_id": "T", "client_name": "X", "raw_comment": "", "quantities": cant, "materials": {}, "hardware": {}, "route_fields": {}, **extra}
        g = generar_excel(datos, reglas, raiz / "templates" / "Plantilla.xlsx", Path(tempfile.mkdtemp()))
        ws = load_workbook(g.path)["Presupuesto"]
        return ws[_comment_cell(ws)].value
    original = comentario()
    assert "*Plan a contratar:  Residencial" in original and "*Ancho de banda: 200 mbps" in original and "*Medio: GPON" in original
    editado = comentario(comment_edits={"plan": "Empresarial", "bandwidth": "25 Mbps"})
    assert editado == original.replace("Plan a contratar:  Residencial", "Plan a contratar:  Empresarial").replace("200 mbps", "25 Mbps")          # nothing else changes
    con_ticket = comentario(comment_edits={"plan": "Empresarial", "bandwidth": "25 Mbps"}, raw_comment="Texto del ticket")
    assert con_ticket.startswith(editado) and con_ticket.endswith("Texto del ticket")                                                           # the ticket's comment goes after, the edits stay
