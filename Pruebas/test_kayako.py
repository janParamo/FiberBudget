"""Lectura de los tickets de Kayako (visor_rutas/kayako.py): solo SELECT y en modo solo lectura, los filtros de business_rules.yaml, y de cada ticket el texto de sus
comentarios (HTML), los datos del cliente y las coordenadas que traiga escritas. La base se simula: no se conecta a ninguna."""
import re

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from visor_rutas import kayako

FILA = {"prioridad": "Prioridad Alta", "organizacion": "Equipos y Sistemas", "ultimo_respondedor": "fibra@ideay.com", "respuestas": 1, "vence": 1_792_001_800, "id": 501, "ticket": "XKJ-813-61728", "asunto": "Presupuesto FO Tiendas Matagalpa", "cliente": "DAVID ALBERTO TOVAR JUAREZ", "ejecutivo": "Yader Ramirez",
        "departamento": "Fibra Optica", "tipo": "Presupuesto FO", "estado": "Abierto", "owner": "Jan", "creado": 1_792_000_000,
        "primer_comentario": "<p>• Nombre de cliente: David Alberto Tovar Juarez<br>• Código de cliente: C35307<br>• Persona de contacto: Grace Gutiérrez<br>"
                             "• Teléfono: 85999439</p><div>Ubicación: 12.727598, -86.125644 y también 12.836523, -85.462874</div>&nbsp;Ancho de Banda: 20M",
        "primer_html": 1, "ultimo_comentario": "Favor revisar&nbsp;la zona.\r\n\r\n\r\n\r\nGracias", "ultimo_html": 0, "ultima_actividad": 1_792_100_000}


class Cursor:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.con.ejecutados.append((sql, params))

    def fetchall(self):
        if "swcustomfieldvalues AS V" in self.con.ejecutados[-1][0]:                  # the additional fields of the tickets
            return [{"ticketid": 501, "titulo": "Sucursal", "valor": "Rivas"}, {"ticketid": 501, "titulo": "Medio", "valor": "FO"}, {"ticketid": 501, "titulo": "Vacío", "valor": ""}]
        return [dict(FILA)]


class Conexion:
    def __init__(self):
        self.ejecutados, self.cerrada = [], False

    def cursor(self):
        return Cursor(self)

    def close(self):
        self.cerrada = True


def test_the_query_is_one_select_with_the_filters_as_parameters_and_the_connection_is_read_only(monkeypatch):
    con = Conexion()
    filas = kayako.tickets(1_700_000_000, 20, abrir=lambda: con)
    assert filas == [{**FILA, "personalizados": {"Sucursal": "Rivas", "Medio": "FO"}}] and con.cerrada                          # an empty value is not a value
    sql, params = con.ejecutados[0]
    assert sql.strip().upper().startswith("SELECT") and not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b", sql, re.I)
    assert "kayako_fusion.swtickets" in sql and "swcustomfieldvalues" in sql and sql.count("%s") == len(params)
    assert params == (64, "%Fibra%Optica%", "Abierto", 1_700_000_000, 20)                                      # the department and the open ones, like Kayako's own list; any type, "En Espera" no
    assert "tickettypetitle LIKE" not in sql and "tickettypetitle LIKE" in kayako.consulta("kayako_fusion", 1, True)    # the type is filtered only when business_rules.yaml asks (tipo_like other than «%»)
    with pytest.raises(ValueError):
        kayako.consulta("kayako; DROP TABLE x", 1)                                                                  # the name of the database is checked
    # the real connection function opens read-only: first thing it runs
    import pymysql
    llamadas = {}
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    real = Conexion()
    monkeypatch.setattr(pymysql, "connect", lambda **kw: llamadas.update(kw) or real)
    kayako.conectar()
    assert real.ejecutados[0][0] == "SET SESSION TRANSACTION READ ONLY" and llamadas["host"] == "10.0.0.5" and llamadas["database"] == "kayako_fusion" and llamadas["port"] == 3306


def test_without_the_connection_in_the_env_it_says_what_is_missing(monkeypatch):
    for k in ("KAYAKO_DB_HOST", "KAYAKO_DB_USER", "KAYAKO_DB_PASSWORD"):
        monkeypatch.setenv(k, "")
    assert kayako.configurada() is False
    with pytest.raises(RuntimeError, match="KAYAKO_DB_HOST"):
        kayako.conectar()


def test_the_columns_of_kayako_own_list_come_with_each_ticket():
    d = kayako.datos_del_ticket(FILA)
    assert (d["prioridad"], d["organizacion"], d["ultimo_respondedor"], d["respuestas"], d["owner"]) == ("Prioridad Alta", "Equipos y Sistemas", "fibra@ideay.com", 1, "Jan")
    assert d["vencido"] is True and d["vence"]                                                                  # its due time (SLA) passed long ago: Kayako paints the row pink
    futuro = kayako.datos_del_ticket({**FILA, "vence": int(__import__("time").time()) + 600})
    assert futuro["vencido"] is False
    assert kayako.datos_del_ticket({"id": 1, "ticket": "T-1"})["vencido"] is False and kayako.datos_del_ticket({"id": 1, "ticket": "T-1"})["respuestas"] == 0


def test_a_ticket_becomes_text_client_data_and_coordinates():
    d = kayako.datos_del_ticket(FILA)
    assert (d["ticket"], d["cliente"], d["ejecutivo"], d["estado"], d["kayako_id"]) == ("XKJ-813-61728", "DAVID ALBERTO TOVAR JUAREZ", "Yader Ramirez", "Abierto", 501)
    assert d["campos"] == {"client_name": "David Alberto Tovar Juarez", "client_code": "C35307", "contact_name": "Grace Gutiérrez", "contact_phone": "85999439"}
    assert d["coordenadas"] == [[12.727598, -86.125644], [12.836523, -85.462874]]
    assert "<" not in d["comentario"] and "Código de cliente: C35307" in d["comentario"] and "\xa0" not in d["comentario"]
    assert d["ultimo_comentario"] == "Favor revisar la zona.\n\nGracias"                                           # entities decoded, blank lines squeezed
    assert d["creado"] and d["ultima_actividad"]
    # a ticket with nothing written in it: nothing is invented
    vacio = kayako.datos_del_ticket({"id": 1, "ticket": "T-1", "cliente": "Ana", "primer_comentario": None, "ultimo_comentario": None})
    assert vacio["campos"] == {} and vacio["coordenadas"] == [] and vacio["comentario"] == "" and vacio["creado"] is None


def test_the_preview_asks_for_the_last_days_and_parses_every_ticket(monkeypatch):
    pedido = {}
    monkeypatch.setattr(kayako, "tickets", lambda desde, limite, abrir: pedido.update(desde=desde, limite=limite) or [dict(FILA)])
    lista = kayako.vista_previa(2, 5)
    assert [t["ticket"] for t in lista] == ["XKJ-813-61728"] and pedido["limite"] == 5 and 2 * 86400 - 60 < __import__("time").time() - pedido["desde"] < 2 * 86400 + 60


# the ticket of the screenshot of 2026-10-28 (Compañía Licorera de Nicaragua, Rivas)
LICORERA = {"id": 900, "ticket": "DTF-377-48662", "asunto": "C22344 Compañia Licorera de Nicaragua, S.A - presupuesto de FO - Rivas", "cliente": "Área de Ventas", "ejecutivo": "Claudia Miranda",
            "departamento": "Fibra Optica", "tipo": "Ventas - Presupuesto FO", "estado": "Abierto", "owner": "Marlon Putoy", "creado": 1_792_000_000, "ultima_actividad": 1_792_000_100,
            "primer_comentario": "¡Buenos dias!\n\nFavor de su apoyo con presupuesto de FO para cambio de medio\n\n• Nombre: Compañia Licorera de Nicaragua, S.A (residencia de colaborador)\n"
                                 "• Código: C22344\nID:ID000451\n• Contacto: Carlos Canales\n• teléfonos: 7877 3419\n• Correo: ccanales@serlicorera.com\n• dirección: Rivas\n"
                                 "• coordenadas: 11.446029, -85.824754\n• Servicio: Transmisión de datos Departamental 25 Mbps\n• Ancho de banda: 25mbps\nmedio: FO\n\nsaludos\n\n"
                                 "Área de Ventas\nPista Jean Paul Genie\nCostado Suroeste Centro Comercial El Tiangue\nLas Cumbres, Managua, Nicaragua\nventas@ideay.com\nTel.: (505) 2255 9755",
            "prioridad": "Nivel 6", "organizacion": "Equipos y Sistemas", "ultimo_respondedor": "Área de Ventas", "respuestas": 0, "vence": 1_793_200_274,
            "primer_html": 0, "ultimo_comentario": None, "ultimo_html": None, "personalizados": {"Código de Cliente": "C22344", "Sucursal": "Rivas", "Tipo de Cliente": "Esmeralda", "Medio": "FO"}}


def test_everything_the_budget_needs_is_read_from_a_real_ticket():
    t = kayako.datos_del_ticket(LICORERA)
    s = t["sugerencia"]
    assert s == {"ticket_id": "DTF-377-48662", "client_name": "Compañia Licorera de Nicaragua, S.A (residencia de colaborador)", "client_code": "C22344", "sales_exec": "Claudia Miranda",
                 "contact_name": "Carlos Canales", "contact_phone": "7877 3419", "coordenadas": ["11.446029, -85.824754"], "servicio": "Transmisión de datos Departamental 25 Mbps",
                 "bandwidth": "25 Mbps", "medium": "FO", "direccion": "Rivas", "correo": "ccanales@serlicorera.com", "sucursal": "Rivas", "tipo_cliente": "Esmeralda"}
    assert t["coordenadas"] == [[11.446029, -85.824754]] and t["personalizados"]["Sucursal"] == "Rivas"
    # the signature of the sales area (its phone, its address) is not taken for the client's
    assert "2255" not in str(s) and "Tiangue" not in str(s)
    # the code and the executive fall back to Kayako's additional fields when the comment does not write them
    sin = kayako.datos_del_ticket({**LICORERA, "primer_comentario": "• Nombre: Casa Azul\n• coordenadas: 12.1364, -86.2514", "ejecutivo": ""})["sugerencia"]
    assert (sin["client_name"], sin["client_code"], sin["coordenadas"], sin["bandwidth"]) == ("Casa Azul", "C22344", ["12.136400, -86.251400"], "")
    # no name in the comment and Kayako's «client» is an e-mail: the subject
    asunto = kayako.datos_del_ticket({**LICORERA, "primer_comentario": "hola", "cliente": "fibra@ideay.com"})["sugerencia"]
    assert asunto["client_name"].startswith("C22344 Compañia Licorera")
    # the coordinate of the additional field «Coordenadas» when the comment has none
    campo = kayako.datos_del_ticket({**LICORERA, "primer_comentario": "hola", "personalizados": {"Coordenadas": "12.5, -86.5"}})["sugerencia"]
    assert campo["coordenadas"] == ["12.500000, -86.500000"]


def test_the_budgets_already_made_for_a_ticket_are_found_by_the_name_of_their_excel(tmp_path):
    from visor_rutas import presupuesto_visor as pv
    (tmp_path / "masivo_20261026-091704_Tiendas" / "aprobados").mkdir(parents=True)
    for ruta in ("DTF-377-48662_Compania_Licorera.xlsx", "DTF-377-48662_Otra_sucursal.xlsx", "XQV-620-37848_Casa.xlsx", "Estimacion_12.1_-86.2_20261020-100000.xlsx", "Resumen.xlsx",
                 "masivo_20261026-091704_Tiendas/aprobados/XKJ-813-61728_DARIO_1.xlsx", "masivo_20261026-091704_Tiendas/Resumen.xlsx", "~$DTF-377-48662_x.xlsx"):
        (tmp_path / ruta).write_bytes(b"x")
    hechos = pv.presupuestos_por_ticket(tmp_path)
    assert hechos["dtf-377-48662"] == ["DTF-377-48662_Compania_Licorera.xlsx", "DTF-377-48662_Otra_sucursal.xlsx"] and hechos["xkj-813-61728"] == ["masivo_20261026-091704_Tiendas/aprobados/XKJ-813-61728_DARIO_1.xlsx"]
    assert "fmo-311-48543" not in hechos and "resumen.xlsx" not in hechos


def test_the_pending_tickets_of_the_viewer_api(tmp_path, monkeypatch):
    from visor_rutas import presupuesto_visor as pv
    from visor_rutas.ventana_web import Api
    (tmp_path / "DTF-377-48662_Compania_Licorera.xlsx").write_bytes(b"x")
    monkeypatch.setattr(pv, "carpeta_visor", lambda: tmp_path)
    api = Api()
    api._modo = "local"
    for k in ("KAYAKO_DB_HOST", "KAYAKO_DB_USER", "KAYAKO_DB_PASSWORD"):
        monkeypatch.setenv(k, "")
    assert api.tickets_pendientes()["ok"] is False and "KAYAKO_DB_HOST" in api.tickets_pendientes()["error"]
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    monkeypatch.setattr(kayako, "tickets", lambda desde, limite, abrir=None: [dict(LICORERA), {**LICORERA, "id": 901, "ticket": "FMO-311-48543", "asunto": "Presupuesto FO/Redundancia"}])
    r = api.tickets_pendientes()
    assert r["ok"] and [(t["ticket"], t["pendiente"], t["presupuestos"]) for t in r["tickets"]] == [("DTF-377-48662", False, ["DTF-377-48662_Compania_Licorera.xlsx"]), ("FMO-311-48543", True, [])]
    assert r["tickets"][0]["sugerencia"]["client_code"] == "C22344"
    monkeypatch.setattr(kayako, "tickets", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("password is secret123")))
    caido = api.tickets_pendientes()
    assert caido["ok"] is False and "VPN" in caido["error"] and "secret123" not in caido["error"]


# --------------------------------------------------------------------------- the other folders of «Tickets»: incidencias masivas, instalaciones

def test_the_folders_read_their_department_incidencias_all_but_the_closed_and_instalaciones_in_five_statuses():
    con = Conexion()
    filas = kayako.tickets_de_carpeta("instalaciones", abrir=lambda: con)
    assert [t["ticket"] for t in filas] == ["XKJ-813-61728"] and con.cerrada
    sql, params = con.ejecutados[0]
    assert sql.strip().upper().startswith("SELECT") and "ticketstatustitle IN" in sql and "NOT IN" not in sql and "tickettypetitle LIKE" not in sql and sql.count("%s") == len(params)
    assert params == (64, "Instalaciones", "Abierto", "Agendado", "Planificación", "En Progreso", "En Espera del Cliente", 0, 1000)      # only those statuses, from the beginning (no date), any type
    con = Conexion()
    kayako.tickets_de_carpeta("incidencias_masivas", abrir=lambda: con)
    sql, params = con.ejecutados[0]
    assert "ticketstatustitle NOT IN" in sql and params[1] == "Incidencias Masivas" and params[2] == "Cerrado"                          # every status but «Cerrado»
    with pytest.raises(KeyError):
        kayako.tickets_de_carpeta("presupuesto")                                    # the budget folder has its own read
    assert set(kayako.carpetas_de_tickets()) == {"incidencias_masivas", "instalaciones"}
    # the budget query is the same as before: only the open ones, with the date
    assert "ticketstatustitle IN" in kayako.consulta("kayako_fusion", 1) and "NOT IN" not in kayako.consulta("kayako_fusion", 1)


def test_the_folder_tickets_of_the_viewer_api(monkeypatch):
    from visor_rutas.ventana_web import Api
    api = Api()
    api._modo = "local"
    for k in ("KAYAKO_DB_HOST", "KAYAKO_DB_USER", "KAYAKO_DB_PASSWORD"):
        monkeypatch.setenv(k, "")
    assert api.tickets_carpeta("nada")["ok"] is False and "no existe" in api.tickets_carpeta("nada")["error"]
    assert api.tickets_carpeta("instalaciones")["ok"] is False and "KAYAKO_DB_HOST" in api.tickets_carpeta("instalaciones")["error"]
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    pedidas = []
    monkeypatch.setattr(kayako, "tickets_de_carpeta", lambda clave, *a, **k: pedidas.append(clave) or [kayako.datos_del_ticket(dict(LICORERA))])
    r = api.tickets_carpeta("incidencias_masivas")
    assert r["ok"] and r["carpeta"] == "incidencias_masivas" and r["titulo"] == "Incidencias masivas" and [t["ticket"] for t in r["tickets"]] == ["DTF-377-48662"] and pedidas == ["incidencias_masivas"]
    monkeypatch.setattr(kayako, "tickets_de_carpeta", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("password is secret123")))
    caido = api.tickets_carpeta("instalaciones")
    assert caido["ok"] is False and "VPN" in caido["error"] and "secret123" not in caido["error"]


# --------------------------------------------------------------------------- the history of a ticket: its comments and its notes

class CursorHistorial:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.con.ejecutados.append((sql, params))
        self.ultimo = sql

    def fetchone(self):
        return {"ticketid": 270846} if self.con.es_de_las_carpetas else None

    def fetchall(self):
        if "swticketposts" in self.ultimo:
            return [{"id": 1, "dateline": 1_794_319_337, "autor": "Andrew Reyes", "creator": 1, "staffid": 268, "isprivate": 0, "ishtml": 0, "hasattachments": 0, "contents": "Apertura: corte de fibra"},
                    {"id": 2, "dateline": 1_794_330_000, "autor": "Cliente Uno", "creator": 2, "staffid": 0, "isprivate": 0, "ishtml": 1, "hasattachments": 1, "contents": "<p>Gracias</p><p>Seguimos sin servicio</p>"}]
        return [{"id": 9, "dateline": 1_794_325_063, "autor": "César Muñoz", "isedited": 1, "notecolor": 1, "note": "| MGA-ENT-OLT-001 | 0/2/1 | 20 | C29715 ILSE |"}]


class ConexionHistorial(Conexion):
    def __init__(self, es_de_las_carpetas=True):
        super().__init__()
        self.es_de_las_carpetas = es_de_las_carpetas

    def cursor(self):
        return CursorHistorial(self)


def test_the_history_has_the_comments_and_the_notes_and_only_of_tickets_of_the_folders():
    con = ConexionHistorial()
    h = kayako.historial(270846, abrir=lambda: con)
    assert con.cerrada and [c["autor"] for c in h["comentarios"]] == ["Andrew Reyes", "Cliente Uno"]
    assert [c["origen"] for c in h["comentarios"]] == ["personal", "cliente"] and h["comentarios"][1]["adjuntos"] is True and h["comentarios"][1]["texto"] == "Gracias\nSeguimos sin servicio"      # html turned into lines
    assert h["notas"] == [{"id": 9, "fecha": kayako._fecha(1_794_325_063), "autor": "César Muñoz", "editada": True, "color": 1, "texto": "| MGA-ENT-OLT-001 | 0/2/1 | 20 | C29715 ILSE |"}]
    for sql, params in con.ejecutados:
        assert sql.strip().upper().startswith("SELECT") and sql.count("%s") == len(params)
    assert con.ejecutados[0][1] == (270846, "Incidencias Masivas", "Instalaciones")                       # the ticket must be of a department of the folders
    with pytest.raises(KeyError):
        kayako.historial(1, abrir=lambda: ConexionHistorial(False))                                       # any other ticket of Kayako is not read through here


def test_the_history_of_the_viewer_api(monkeypatch):
    from visor_rutas.ventana_web import Api
    api = Api()
    api._modo = "local"
    for k in ("KAYAKO_DB_HOST", "KAYAKO_DB_USER", "KAYAKO_DB_PASSWORD"):
        monkeypatch.setenv(k, "")
    assert api.ticket_historial("abc")["ok"] is False and api.ticket_historial(5)["ok"] is False and "KAYAKO_DB_HOST" in api.ticket_historial(5)["error"]
    monkeypatch.setenv("KAYAKO_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("KAYAKO_DB_USER", "lector")
    monkeypatch.setenv("KAYAKO_DB_PASSWORD", "x")
    monkeypatch.setattr(kayako, "historial", lambda n, *a, **k: {"comentarios": [{"id": 1, "texto": "hola"}], "notas": []})
    r = api.ticket_historial(270846)
    assert r["ok"] and r["kayako_id"] == 270846 and r["comentarios"][0]["texto"] == "hola"
    monkeypatch.setattr(kayako, "historial", lambda n, *a, **k: (_ for _ in ()).throw(KeyError(n)))
    assert api.ticket_historial(1)["ok"] is False and "carpetas" in api.ticket_historial(1)["error"]
    monkeypatch.setattr(kayako, "historial", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("password is secret123")))
    caido = api.ticket_historial(2)
    assert caido["ok"] is False and "VPN" in caido["error"] and "secret123" not in caido["error"]
