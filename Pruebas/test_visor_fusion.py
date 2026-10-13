"""Ruta de fusión (visor_rutas/fusion.py), its key in calcular_ruta and the diagram images."""
import base64
import importlib
import os
import sqlite3
from pathlib import Path

import pytest

from make_sample_template import create_template

SCHEMA = Path(__file__).resolve().parent.parent / "red_fibra" / "schema.sql"
CONEXION = {"nombre": "MF CONEXION KMZ", "lat": 12.1000, "lon": -86.2500}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    template = tmp_path / "t.xlsx"
    create_template(template)
    env = {"DB_HOST": "x", "DB_PORT": "5432", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
           "GOOGLE_API_KEY": "x", "SERVICE_API_KEY": "secret",
           "TEMPLATE_PATH": str(template), "OUTPUT_DIR": str(tmp_path / "out"),
           "LOG_FILE": str(tmp_path / "log.txt"),
           "RED_FIBRA_DB": str(tmp_path / "missing_red_fibra.db"), "VISIO_DB_NAME": "",
           "RULES_PATH": os.path.join(os.path.dirname(__file__), "..", "business_rules.yaml")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    config.get_settings.cache_clear()
    import main
    importlib.reload(main)
    from visor_rutas import fusion
    return main, fusion, tmp_path


@pytest.fixture
def base(tmp_path):
    """Small red_fibra.db: OLT-side mufa (Excel ring), a repeated name, and the connection mufa."""
    ruta = tmp_path / "red_fibra.db"
    con = sqlite3.connect(ruta)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("INSERT INTO importaciones(id, fecha, carpeta_origen) VALUES (1, '2026-10-07', 'x')")
    archivos = [(1, "Zona/1 MUFA PEQUENA.vsd", "mufa", "vsd", "a" * 32),
                (2, "Zona/RED CONEXION.vsd", "red", "vsd", "b" * 32),
                (3, "ANILLOS.xlsx", "excel_anillos", "xlsx", "c" * 32)]
    con.executemany("INSERT INTO archivos(id, importacion_id, ruta_relativa, nombre, formato, tipo_diagrama, md5, estado) "
                    "VALUES (?, 1, ?, ?, ?, ?, ?, 'ok')",
                    [(i, r, Path(r).name, f, t, m) for i, r, t, f, m in archivos])
    nodos = [(1, "MF A", "MUFA", "IDEAY", 12.1030, -86.2500, "SANGRIA"),
             (2, "MUFA PEQUEÑA", "MUFA", None, 12.1020, -86.2500, None),
             (3, "MUFA PEQUEÑA", "MUFA", None, 12.1001, -86.2501, None),    # same name, not on the cable
             (4, "MF CONEXION", "MUFA", "UFINET", 12.1001, -86.2500, None)]
    con.executemany("INSERT INTO nodos(id, nombre, nombre_normalizado, tipo, propietario, lat, lon, notas) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(i, n, n, t, p, la, lo, no) for i, n, t, p, la, lo, no in nodos])
    con.executemany("INSERT INTO enlaces(nodo_a_id, nodo_b_id, fuente, confianza) VALUES (?, ?, 'visio_linea', 'media')",
                    [(1, 2), (2, 4)])
    con.executemany("INSERT INTO nodo_apariciones(nodo_id, archivo_id, rol, texto_original) VALUES (?, ?, ?, ?)",
                    [(1, 3, "excel", None), (2, 1, "principal", "MUFA PEQUEÑA"),
                     (4, 2, "red", "MF CONEXION 12.1001, -86.2500"), (4, 1, "vecino", "MF CONEXION")])
    con.execute("INSERT INTO anillo_tramos(archivo_id, hoja, enlace, orden, nodo_id, en_mufa, de_mufa, hilo_entrante, "
                "hacia_mufa, hilo_saliente) VALUES (3, 'Hoja1', 'NODO X / NODO Y', 2, 1, 'MF A', 'ODF', 'PUERTOS 17 Y 18', "
                "'MUFA PEQUEÑA', 'HILOS 8 / 9')")
    con.executemany("INSERT INTO servicios(nodo_id, archivo_id, tipo, codigo_cliente, id_servicio, descripcion) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(4, 2, "splitter", None, None, "SPL 1X8 PT 0/2/0 OLT X"),
                     (4, 2, "cliente", "C12345", "ID123456", "C12345 Cliente Uno ID123456"),
                     (4, 2, "cliente", "C12345", "ID123456", "C12345  Cliente Uno ID123456")])   # repeated
    con.executemany("INSERT INTO textos_crudos(archivo_id, pagina, x_cm, y_cm, texto) VALUES (?, ?, ?, ?, ?)",
                    [(1, 0, 5, 5, "MUFA PEQUEÑA"), (1, 0, 6, 5, "SPL 1/16 PUERTO 3 OLT X"),
                     (1, 0, 7, 5, "12 11 10 9"), (1, 0, 8, 5, "BUFFER EN SANGRIA"),
                     (1, 0, 9, 5, "MF OTRA / 12.1234567, -86.2345678 / SATURADA"),    # another mufa's label
                     (2, 0, 10, 10, "MF CONEXION 12.1001, -86.2500"), (2, 0, 12, 10, "PUERTO 0/2/3 OLT MERCED"),
                     (2, 0, 40, 40, "SPL LEJANO DE OTRA MUFA")])
    con.commit()
    con.close()
    return ruta


ORIGEN = {"nodo": "OLT X", "mf": "MF A", "confianza": "media",
          "camino": ["MF CONEXION", "MUFA PEQUEÑA", "MF A"], "motivo": None}


def test_ruta_fusion_va_del_olt_a_la_conexion_con_hilos_y_splitters(entorno, base):
    _, fusion, _ = entorno
    paradas = fusion.ruta_fusion(ORIGEN, CONEXION, archivo_sqlite=base)

    assert [p["nombre"] for p in paradas] == ["MF A", "MUFA PEQUEÑA", "MF CONEXION"]
    assert [p["orden"] for p in paradas] == [1, 2, 3]
    a, pequena, conexion = paradas
    assert a["es_mufa_del_nodo"] and not a["es_conexion"] and conexion["es_conexion"]
    # Excel ring data, source "excel" with high confidence
    assert a["fuente_hilos"] == "excel"
    assert a["hilos_anillo"] == [{"hoja": "Hoja1", "enlace": "NODO X / NODO Y", "orden": 2, "de_mufa": "ODF",
                                  "hilo_entrante": "PUERTOS 17 Y 18", "hacia_mufa": "MUFA PEQUEÑA",
                                  "hilo_saliente": "HILOS 8 / 9", "nota": None, "fuente": "excel", "confianza": "alta"}]
    assert "SANGRIA" in a["notas"] and a["propietario"] == "IDEAY"
    # repeated name: the one joined by a cable to the previous stop, not the one closest to the client
    assert (pequena["nodo_id"], pequena["identificacion"]) == (2, "por_enlace")
    assert pequena["fuente_hilos"] == "texto_diagrama"
    textos = [s["texto"] for s in pequena["splitters_y_puertos"]]
    assert "SPL 1/16 PUERTO 3 OLT X" in textos and "BUFFER EN SANGRIA" in textos
    assert "12 11 10 9" not in textos                                     # bare numbering is not a splitter
    assert "BUFFER EN SANGRIA" in pequena["notas"]
    assert not any("MF OTRA" in n for n in pequena["notas"])              # other mufa's label, skipped
    assert pequena["archivos"][0]["rol"] == "principal" and pequena["archivos"][0]["md5"] == "a" * 32
    # red diagram: only texts near the mufa's label; services without repeats
    textos = [s["texto"] for s in conexion["splitters_y_puertos"]]
    assert "SPL 1X8 PT 0/2/0 OLT X" in textos and "PUERTO 0/2/3 OLT MERCED" in textos
    assert "SPL LEJANO DE OTRA MUFA" not in textos
    assert [c["codigo"] for c in conexion["clientes"]] == ["C12345"]
    assert conexion["propietario"] == "UFINET"


def test_sin_camino_lista_vacia_y_aviso(entorno, base):
    _, fusion, _ = entorno
    avisos = []
    origen = {"nodo": None, "camino": [], "motivo": "ninguna mufa de los diagramas a menos de 150 m"}
    assert fusion.ruta_fusion(origen, CONEXION, archivo_sqlite=base, avisos=avisos) == []
    assert avisos == ["Ruta de fusión vacía: el origen de tráfico no tiene camino en los diagramas "
                      "(ninguna mufa de los diagramas a menos de 150 m)"]


def test_fusiones_piloto_aparte_y_solo_si_existe_la_tabla(entorno, base):
    _, fusion, _ = entorno
    con = sqlite3.connect(base)
    columnas = "archivo_id, pagina, entrada, salida, color, color_tia, confianza, motivo, x1_cm, y1_cm, x2_cm, y2_cm"
    con.executemany(f"INSERT INTO fusiones_piloto({columnas}) VALUES (?, 0, ?, ?, '#00b050', '3 verde', ?, 'm', ?, 5, ?, 5)",
                    [(1, "hilo 3", "hilo 3", 0.4, 1, 2), (1, "hilo 1", "hilo 9", 0.9, 1, 2),     # mufa's own diagram
                     (2, "hilo 2", "SPL", 0.8, 11, 13),                                          # near MF CONEXION's label
                     (2, "hilo 5", "hilo 6", 0.95, 40, 41)])                                     # another mufa in the red diagram
    con.commit()
    paradas = {p["nombre"]: p for p in fusion.ruta_fusion(ORIGEN, CONEXION, archivo_sqlite=base)}
    pequena, conexion, a = paradas["MUFA PEQUEÑA"], paradas["MF CONEXION"], paradas["MF A"]
    assert [(f["entrada"], f["confianza"]) for f in pequena["fusiones_piloto"]] == [("hilo 1", 0.9), ("hilo 3", 0.4)]
    assert [f["entrada"] for f in conexion["fusiones_piloto"]] == ["hilo 2"]
    assert all(f["fuente"] == "piloto" for f in pequena["fusiones_piloto"] + conexion["fusiones_piloto"])
    assert a["fusiones_piloto"] == [] and a["fuente_hilos"] == "excel"           # Excel data untouched
    assert pequena["fuente_hilos"] == "texto_diagrama"                          # the pilot never sets the badge

    con.execute("DROP TABLE fusiones_piloto")
    con.commit()
    con.close()
    assert all(p["fusiones_piloto"] is None for p in fusion.ruta_fusion(ORIGEN, CONEXION, archivo_sqlite=base))


def test_nombre_que_no_esta_en_la_base_queda_marcado(entorno, base):
    _, fusion, _ = entorno
    paradas = fusion.ruta_fusion({"nodo": "OLT X", "camino": ["MF CONEXION", "MF FANTASMA"]}, CONEXION,
                                 archivo_sqlite=base)
    assert [(p["nombre"], p["identificacion"], p["fuente_hilos"]) for p in paradas] == [
        ("MF FANTASMA", "no_encontrada", "sin_dato"), ("MF CONEXION", "exacta", "texto_diagrama")]


def test_sin_base_de_diagramas_devuelve_lista_vacia_y_aviso(entorno, tmp_path):
    _, fusion, _ = entorno
    avisos = []
    assert fusion.ruta_fusion(ORIGEN, CONEXION, archivo_sqlite=tmp_path / "no_existe.db", avisos=avisos) == []
    assert avisos == ["Ruta de fusión no disponible: no se encontró la base de diagramas (red_fibra)"]


# --------------------------------------------------------------------------- buscador de mufas

def _odg_falso(carpeta, md5, ancho_cm=40, alto_cm=20):
    import zipfile
    carpeta.mkdir(exist_ok=True)
    with zipfile.ZipFile(carpeta / f"{md5}.odg", "w") as z:
        z.writestr("styles.xml", f'<s fo:page-width="{ancho_cm}cm" fo:page-height="{alto_cm}cm"/>')


def test_buscar_mufas_por_palabras_sin_importar_mayusculas(entorno, base):
    _, fusion, _ = entorno
    nombres = lambda texto: [m["nombre"] for m in fusion.buscar_mufas(texto, archivo_sqlite=base)]
    assert nombres("mf conexion") == ["MF CONEXION"]
    assert nombres("conexion") == ["MF CONEXION"]
    # the one drawn in a diagram first, then the other one with the same name
    assert nombres("pequeña") == ["MUFA PEQUEÑA", "MUFA PEQUEÑA"]
    assert fusion.buscar_mufas("pequeña", archivo_sqlite=base)[0]["diagramas"] == 1
    assert nombres("x") == [] and nombres("") == []
    assert nombres("no existe") == []
    m = fusion.buscar_mufas("mf a", archivo_sqlite=base)[0]
    assert (m["nombre"], m["tipo"], m["lat"]) == ("MF A", "MUFA", 12.1030)


def test_normalizar_busqueda_como_el_importador():
    from visor_rutas import fusion
    assert fusion.normalizar_busqueda("MF Puma de las Colinas") == ["PUMA", "COLINAS"]
    assert fusion.normalizar_busqueda("Peñón #2") == ["PENON", "2"]
    assert fusion.normalizar_busqueda("mufa") == ["MUFA"]          # alone, it is kept


def test_detalle_mufa_con_su_posicion_en_cada_diagrama(entorno, base, monkeypatch):
    _, fusion, tmp_path = entorno
    monkeypatch.setattr(fusion, "CACHE_ODG", tmp_path / "odg")
    _odg_falso(tmp_path / "odg", "a" * 32)
    _odg_falso(tmp_path / "odg", "b" * 32, 60, 30)
    a = fusion.detalle_mufa(1, archivo_sqlite=base)
    assert (a["nombre"], a["fuente_hilos"], a["hilos_anillo"][0]["hilo_saliente"]) == ("MF A", "excel", "HILOS 8 / 9")
    conexion = fusion.detalle_mufa(4, archivo_sqlite=base)
    anclas = {x["md5"][0]: x.get("ancla") for x in conexion["archivos"] if x["diagrama"]}
    assert anclas["b"] == {"x_cm": 10.0, "y_cm": 10.0, "ancho_cm": 60.0, "alto_cm": 30.0}   # its label in the red diagram
    assert anclas["a"] is None                       # "MF CONEXION" is not written in that diagram
    assert fusion.detalle_mufa(999, archivo_sqlite=base) is None
    with pytest.raises(FileNotFoundError):
        fusion.detalle_mufa(1, archivo_sqlite=tmp_path / "no_existe.db")


def test_ubicacion_por_nombre_cuando_falta_la_etiqueta_exacta():
    from visor_rutas import fusion
    filas = [(0, 1.0, 1.0, "C33597 Puma Energy / Puma Las Colinas / -18.97 dBm"),   # a client: skipped
             (0, 2.0, 2.0, "ATM PUMA LA COLINA"),
             (0, 3.0, 3.0, "MUFA PUMA ENTRADA LA COLINA IDEAY"),                     # a label: preferred
             (0, 4.0, 4.0, "HACIA MUFA ALTOS DE SANTO DOMINGO")]
    assert fusion._ancla_por_nombre(filas, "MF PUMA LAS COLINAS") == (0, 3.0, 3.0)
    assert fusion._ancla_por_nombre(filas, "MF NADA PARECIDO") is None


def test_api_buscar_mufa_y_mufa(entorno, monkeypatch):
    _, fusion, _ = entorno
    from visor_rutas import ventana_web
    api = ventana_web.Api()
    monkeypatch.setattr(fusion, "buscar_mufas", lambda texto, **k: [{"id": 4, "nombre": "MF CONEXION", "lat": None}])
    assert api.buscar_mufa("conex") == {"ok": True, "resultados": [{"id": 4, "nombre": "MF CONEXION", "lat": None}]}
    monkeypatch.setattr(fusion, "detalle_mufa", lambda nodo_id, **k: None if nodo_id == 9 else {"nombre": "MF CONEXION"})
    assert api.mufa(4) == {"ok": True, "mufa": {"nombre": "MF CONEXION"}}
    assert api.mufa(9) == {"ok": False, "error": "La mufa ya no está en la base de diagramas"}
    assert api.mufa("abc") == {"ok": False, "error": "Mufa no válida"}

    def sin_base(*a, **k):
        raise FileNotFoundError("x")

    monkeypatch.setattr(fusion, "buscar_mufas", sin_base)
    assert api.buscar_mufa("conex") == {"ok": False, "error": "No se encontró la base de diagramas (red_fibra)"}


# --------------------------------------------------------------------------- calcular_ruta

def _simular_ruta(main, monkeypatch):
    seg = main.db.Segment(id=7, tipo="mufa", lat=12.13, lon=-86.25, distance_m=120.0, is_mufa=True, nombre="MF PRUEBA")
    monkeypatch.setattr(main.db, "find_nearest_connection_point", lambda *a, **k: seg)
    monkeypatch.setattr(main.db, "find_mufas_near_route", lambda *a, **k: [])
    monkeypatch.setattr(main.db, "find_point_coords", lambda ids: {})
    monkeypatch.setattr(main.db, "find_upstream_mufa_chain", lambda mufa_id, nombre, *a, **k: [main.db.ChainMufa(mufa_id, nombre)])
    monkeypatch.setattr(main.db, "find_existing_poles_near_route", lambda *a, **k: [])
    monkeypatch.setattr(main.routing, "get_route", lambda *a, **k: main.routing.Route(
        distance_m=200.0, duration_s=60.0, points=[(12.13, -86.25), (12.1364, -86.2514)]))


def test_calcular_ruta_agrega_ruta_fusion_sin_cambiar_lo_demas(entorno, monkeypatch):
    main, fusion, _ = entorno
    from visor_rutas import calculo
    _simular_ruta(main, monkeypatch)
    recibido = {}

    def falsa(origen, conexion, visio_con=None, archivo_sqlite=None, avisos=None):
        recibido.update(origen=origen, conexion=conexion, archivo=archivo_sqlite)
        return [{"orden": 1, "nombre": "MF PRUEBA"}]

    monkeypatch.setattr(fusion, "ruta_fusion", falsa)
    r = calculo.calcular_ruta(12.1364, -86.2514)
    assert r["ruta_fusion"] == [{"orden": 1, "nombre": "MF PRUEBA"}]
    # every key it returned before, plus ruta_fusion
    assert set(r) == {"cliente", "conexion", "ruta", "postes_existentes", "postes_nuevos", "mufas_en_ruta",
                      "mufas_intervenidas", "mufas_intervenidas_fuente", "distribution_reason",
                      "nodos_visio_cercanos", "origen_trafico", "avisos", "ruta_fusion"}
    assert {"nombre", "tipo", "tipo_detalle", "id", "lat", "lon", "distancia_lineal_m", "fuente",
            "requiere_revision", "notas"} == set(r["conexion"])
    assert {"puntos", "distancia_m", "metraje_final_m", "reserva_m", "tipo_cable", "aproximada",
            "acometida_m"} == set(r["ruta"])
    assert {"nodo", "mf", "confianza", "camino", "motivo"} <= set(r["origen_trafico"])   # keys kept
    assert recibido["conexion"]["nombre"] == "MF PRUEBA"
    assert recibido["archivo"] == main.settings.red_fibra_db


def test_falla_de_la_ruta_de_fusion_no_rompe_la_ruta(entorno, monkeypatch):
    main, fusion, _ = entorno
    from visor_rutas import calculo
    _simular_ruta(main, monkeypatch)
    monkeypatch.setattr(fusion, "ruta_fusion", lambda *a, **k: 1 / 0)
    r = calculo.calcular_ruta(12.1364, -86.2514)
    assert r["ruta_fusion"] == [] and r["ruta"]["distancia_m"] == 200.0
    assert "No se pudo armar la ruta de fusión (ZeroDivisionError)" in r["avisos"]


# --------------------------------------------------------------------------- diagramas

def test_diagrama_png_valida_reutiliza_y_sin_libreoffice_devuelve_none(entorno, monkeypatch):
    _, fusion, tmp_path = entorno
    monkeypatch.setattr(fusion, "CACHE_ODG", tmp_path / "cache_odg")
    monkeypatch.setattr(fusion, "CACHE_DIAGRAMAS", tmp_path / "cache_diagramas")
    with pytest.raises(ValueError):
        fusion.diagrama_png("../../etc/passwd")
    with pytest.raises(FileNotFoundError):
        fusion.diagrama_png("d" * 32)

    (tmp_path / "cache_odg").mkdir()
    (tmp_path / "cache_odg" / ("d" * 32 + ".odg")).write_bytes(b"PK")
    monkeypatch.setattr(fusion.recalc, "find_soffice", lambda *a: None)
    assert fusion.diagrama_png("d" * 32) is None                         # no LibreOffice

    (tmp_path / "cache_diagramas").mkdir()
    png = tmp_path / "cache_diagramas" / ("d" * 32 + "_0.png")
    png.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(fusion.recalc, "find_soffice", lambda *a: pytest.fail("cached: must not convert"))
    assert fusion.diagrama_png("D" * 32) == png                          # reused, md5 case-insensitive


def test_diagrama_svg_se_reutiliza_y_si_falla_se_usa_el_png(entorno, monkeypatch):
    _, fusion, tmp_path = entorno
    monkeypatch.setattr(fusion, "CACHE_DIAGRAMAS", tmp_path / "cache_diagramas")
    (tmp_path / "cache_diagramas").mkdir()
    svg = tmp_path / "cache_diagramas" / ("d" * 32 + "_0.svg")
    svg.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(fusion.recalc, "find_soffice", lambda *a: pytest.fail("cached: must not convert"))
    assert fusion.diagrama_svg("d" * 32) == svg
    assert fusion.diagrama_mejor("d" * 32) == (svg, "svg")

    png = tmp_path / "x.png"

    def svg_falla(md5):
        raise RuntimeError("LibreOffice no pudo convertir el diagrama")

    monkeypatch.setattr(fusion, "diagrama_svg", svg_falla)
    monkeypatch.setattr(fusion, "diagrama_png", lambda md5, pagina=0: png)
    assert fusion.diagrama_mejor("e" * 32) == (png, "png")


def test_api_diagrama_devuelve_data_url_o_mensaje_claro(entorno, monkeypatch):
    _, fusion, tmp_path = entorno
    from visor_rutas import ventana_web
    svg = tmp_path / "x.svg"
    svg.write_bytes(b"<svg>datos</svg>")
    monkeypatch.setattr(fusion, "diagrama_mejor", lambda md5: (svg, "svg"))
    res = ventana_web.Api().diagrama("e" * 32, 0)
    assert res == {"ok": True, "formato": "svg",
                   "data_url": "data:image/svg+xml;base64," + base64.b64encode(b"<svg>datos</svg>").decode()}

    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG datos")
    monkeypatch.setattr(fusion, "diagrama_mejor", lambda md5: (png, "png"))
    assert ventana_web.Api().diagrama("e" * 32)["data_url"].startswith("data:image/png;base64,")

    monkeypatch.setattr(fusion, "diagrama_mejor", lambda md5: (None, "svg"))
    assert ventana_web.Api().diagrama("e" * 32) == {"ok": False, "error": "Diagrama no disponible (falta LibreOffice)"}

    def no_esta(md5):
        raise FileNotFoundError(md5)

    monkeypatch.setattr(fusion, "diagrama_mejor", no_esta)
    assert "no está convertido" in ventana_web.Api().diagrama("e" * 32)["error"]
    assert ventana_web.Api().diagrama("../x")["ok"] is False                 # malformed md5
