"""App de campo, fase 4 (servidor): ubicación en vivo de los técnicos, rechazar y aprobar (a la red base, a un proyecto o a Mis lugares, con historial), avisos
duplicados para quien revisa, y los avisos en tiempo real (NOTIFY → LISTEN → SSE)."""
import json
import threading
import time

import httpx
import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import LAT, LON, MARIA, jpeg, punto  # noqa: F401
from test_campo_pwa import servidor_real  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas import campo_eventos
from visor_rutas.redes import campo, db, proyectos, usuarios
from visor_rutas.redes.api import METODOS, ServicioRedes


@pytest.fixture(autouse=True)
def _fotos_en_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPO_FOTOS_DIR", str(tmp_path / "fotos"))


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    gente = {}
    for nombre, rol in (("juan", "tecnico"), ("pedro", "tecnico"), ("edu", "editor"), ("ana", "editor"), ("lola", "lector")):
        u = usuarios.identificar(con, persona_visor=nombre)
        con.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
        gente[nombre] = usuarios.identificar(con, persona_visor=nombre)
    gente["admin"] = admin
    return con, gente


def crear_proyecto(con, codigo, base=False, asignar=()):
    pid = con.execute("INSERT INTO redes.proyectos (codigo, nombre, es_red_base) VALUES (%s, %s, %s) RETURNING id", (codigo, f"Proyecto {codigo}", base)).fetchone()["id"]
    for u in asignar:
        con.execute("INSERT INTO redes.proyecto_usuarios (proyecto_id, usuario_id) VALUES (%s, %s)", (pid, u["id"]))
    return pid


def enviar(con, tecnico, **cambios):
    return campo.guardar_puntos(con, tecnico, puntos=[punto(**cambios)])["resultados"][0]["punto"]


# ------------------------------------------------------------------ live position

def test_each_technician_has_one_last_position_and_only_reviewers_see_them(mundo):
    con, g = mundo
    campo.ubicacion(con, g["juan"], lat=LAT, lon=LON, precision_m=6)
    campo.ubicacion(con, g["juan"], lat=LAT + 0.001, lon=LON, precision_m=4)                  # replaces the first
    campo.ubicacion(con, g["pedro"], lat=LAT - 0.001, lon=LON)
    assert con.execute("SELECT count(*) AS n FROM redes.campo_ubicaciones").fetchone()["n"] == 2
    u = {x["nombre"]: x for x in campo.ubicaciones(con, g["edu"])["ubicaciones"]}
    assert set(u) == {"juan", "pedro"} and u["juan"]["lat"] == pytest.approx(LAT + 0.001) and u["juan"]["precision_m"] == 4 and u["pedro"]["precision_m"] is None
    assert u["juan"]["hace_s"] <= 2
    with pytest.raises(db.SinPermiso):
        campo.ubicaciones(con, g["juan"])                                                      # a technician does not see the others
    with pytest.raises(db.SinPermiso):
        campo.ubicacion(con, g["lola"], lat=LAT, lon=LON)
    with pytest.raises(db.DatosInvalidos):
        campo.ubicacion(con, g["juan"], lat=40, lon=LON)
    con.execute("UPDATE redes.campo_ubicaciones SET recibido_en = now() - interval '2 days' WHERE usuario_id = %s", (g["pedro"]["id"],))
    assert [x["nombre"] for x in campo.ubicaciones(con, g["edu"])["ubicaciones"]] == ["juan"]      # the ones not heard from for hours are not shown


# ------------------------------------------------------------------ reject and approve

def test_rejecting_needs_a_reason_a_reviewer_and_the_technician_reads_it(mundo):
    con, g = mundo
    a, b = enviar(con, g["juan"], nombre="A"), enviar(con, g["juan"], nombre="B")
    with pytest.raises(db.SinPermiso):
        campo.rechazar(con, g["juan"], ids=[a["id"]], motivo="no")
    with pytest.raises(db.DatosInvalidos):
        campo.rechazar(con, g["edu"], ids=[a["id"]], motivo=" ")
    r = campo.rechazar(con, g["edu"], ids=[a["id"], 99999, a["id"]], motivo="Está duplicado")["resultados"]
    assert [x["ok"] for x in r] == [True, False] and "no existe" in r[1]["error"]
    mio = {p["nombre"]: p for p in campo.puntos(con, g["juan"])["puntos"]}
    assert mio["A"]["estado"] == "rechazado" and mio["A"]["motivo_rechazo"] == "Está duplicado" and mio["B"]["estado"] == "pendiente"
    assert campo.rechazar(con, g["edu"], ids=[a["id"]], motivo="otra vez")["resultados"][0]["ok"] is False        # already decided
    assert con.execute("SELECT revisado_por FROM redes.campo_puntos WHERE id = %s", (a["id"],)).fetchone()["revisado_por"] == g["edu"]["id"]


def test_approving_a_pole_and_a_mufa_creates_them_in_the_base_network_with_history(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB-MGA", base=True)
    poste = enviar(con, g["juan"], tipo="poste", subtipo="concreto", nombre="Poste 7", notas="esquina")
    mufa = enviar(con, g["juan"], tipo="mufa", subtipo="48 domo", nombre="Mufa 2", lat=LAT + 0.01)
    with pytest.raises(db.SinPermiso):
        campo.aprobar(con, g["juan"], ids=[poste["id"]], destino="red")
    r = campo.aprobar(con, g["edu"], ids=[poste["id"], mufa["id"]], destino="red")                  # one base project: it is the destination
    assert r["proyecto_id"] == base and [x["ok"] for x in r["resultados"]] == [True, True]
    e = con.execute("SELECT e.*, ST_Y(e.ubicacion) AS lat FROM redes.elementos e WHERE e.id = %s", (r["resultados"][0]["elemento_id"],)).fetchone()
    assert (e["proyecto_id"], e["tipo"], e["subtipo"], e["nombre"], e["fuente"], e["confianza"], e["ubicacion_fuente"]) == (base, "poste", "concreto", "Poste 7", "usuario", "alta", "real")
    assert e["propiedades"]["campo"]["punto_id"] == poste["id"] and e["propiedades"]["campo"]["notas"] == "esquina" and float(e["lat"]) == pytest.approx(LAT)
    m = con.execute("SELECT * FROM redes.elementos WHERE id = %s", (r["resultados"][1]["elemento_id"],)).fetchone()
    assert (m["tipo"], m["subtipo"], m["propiedades"]["capacidad"], m["propiedades"]["formato"]) == ("mufa", None, 48, "domo")
    p = {x["nombre"]: x for x in campo.puntos(con, g["juan"])["puntos"]}["Poste 7"]
    assert p["estado"] == "aprobado" and p["elemento_red_id"] == e["id"]
    historial = con.execute("SELECT entidad, accion, proyecto_id FROM redes.historial WHERE entidad IN ('elemento', 'campo_punto') ORDER BY id").fetchall()
    assert ("elemento", "crear", base) in [(h["entidad"], h["accion"], h["proyecto_id"]) for h in historial]
    # an approved point is closed: cannot be approved or rejected again
    assert campo.aprobar(con, g["edu"], ids=[poste["id"]], destino="red")["resultados"][0]["ok"] is False
    with pytest.raises(db.SinPermiso):
        campo.editar_punto(con, g["edu"], id=poste["id"], version=p["version"], cambios={"nombre": "x"})


def test_approving_to_the_network_needs_the_right_project_and_a_pole_or_a_mufa(mundo):
    con, g = mundo
    punto_p, reserva = enviar(con, g["juan"], nombre="P"), enviar(con, g["juan"], tipo="reserva", subtipo=None, nombre="R")
    with pytest.raises(db.DatosInvalidos, match="red base"):
        campo.aprobar(con, g["edu"], ids=[punto_p["id"]], destino="red")                         # no base network at all
    b1, b2 = crear_proyecto(con, "B1", base=True), crear_proyecto(con, "B2", base=True)
    with pytest.raises(db.DatosInvalidos, match="varias"):
        campo.aprobar(con, g["edu"], ids=[punto_p["id"]], destino="red")                         # several: it must say which
    normal = crear_proyecto(con, "P1", asignar=[g["edu"]])
    with pytest.raises(db.DatosInvalidos, match="no es una red base"):
        campo.aprobar(con, g["edu"], ids=[punto_p["id"]], destino="red", proyecto_id=normal)
    with pytest.raises(db.DatosInvalidos, match="red base"):
        campo.aprobar(con, g["edu"], ids=[punto_p["id"]], destino="proyecto", proyecto_id=b1)
    r = campo.aprobar(con, g["edu"], ids=[reserva["id"], punto_p["id"]], destino="red", proyecto_id=b2)["resultados"]
    assert r[0]["ok"] is False and "Mis lugares" in r[0]["error"] and r[1]["ok"] is True          # the reserva cannot go to the network; the pole can
    assert con.execute("SELECT proyecto_id FROM redes.elementos").fetchone()["proyecto_id"] == b2
    with pytest.raises(db.DatosInvalidos):
        campo.aprobar(con, g["edu"], ids=[reserva["id"]], destino="otro")


def test_approving_to_a_project_of_its_own_needs_the_editor_to_be_assigned(mundo):
    con, g = mundo
    propio = crear_proyecto(con, "RUTA-1", asignar=[g["edu"]])
    poste, cliente = enviar(con, g["juan"], nombre="P"), enviar(con, g["juan"], tipo="cliente", subtipo=None, nombre="Casa del cliente")
    with pytest.raises(db.SinPermiso, match="permiso"):
        campo.aprobar(con, g["ana"], ids=[poste["id"]], destino="proyecto", proyecto_id=propio)       # ana is an editor but not assigned
    with pytest.raises(db.DatosInvalidos, match="Elija el proyecto"):
        campo.aprobar(con, g["edu"], ids=[poste["id"]], destino="proyecto")
    r = campo.aprobar(con, g["edu"], ids=[poste["id"], cliente["id"]], destino="proyecto", proyecto_id=propio)["resultados"]
    assert [x["ok"] for x in r] == [True, True]
    assert {x["tipo"] for x in con.execute("SELECT tipo FROM redes.elementos WHERE proyecto_id = %s", (propio,)).fetchall()} == {"poste", "cliente"}
    assert campo.aprobar(con, g["admin"], ids=[enviar(con, g["pedro"], nombre="Q")["id"]], destino="proyecto", proyecto_id=propio)["resultados"][0]["ok"]       # an administrator can


def test_approving_to_mis_lugares_makes_a_marca_with_the_photos_in_the_reviewers_own_folder(mundo):
    con, g = mundo
    reserva = enviar(con, g["juan"], tipo="reserva", subtipo=None, nombre="Reserva 1", notas="30 m de cable")
    campo.subir_foto(con, g["juan"], punto_id=reserva["id"], datos=jpeg(300, 200), uuid_cliente="aaaa1111-0001")
    otra = enviar(con, g["juan"], tipo="solitaria", subtipo=None, nombre="Solitaria 1", lat=LAT + 0.01)
    r = campo.aprobar(con, g["edu"], ids=[reserva["id"], otra["id"]], destino="lugares")["resultados"]
    assert [x["ok"] for x in r] == [True, True] and r[0]["lugar_id"] and r[0]["elemento_id"] is None
    carpetas = con.execute("SELECT id, usuario_id, nombre FROM redes.lugares_carpetas WHERE borrado_en IS NULL").fetchall()
    assert [(c["usuario_id"], c["nombre"]) for c in carpetas] == [(g["edu"]["id"], "Campo – juan")]       # one folder per technician, the reviewer's own
    lugar = con.execute("SELECT * FROM redes.lugares_elementos WHERE id = %s", (r[0]["lugar_id"],)).fetchone()
    assert lugar["tipo"] == "marca" and lugar["nombre"] == "Reserva 1" and lugar["carpeta_id"] == carpetas[0]["id"]
    assert "Levantado por juan" in lugar["descripcion_html"] and "30 m de cable" in lugar["descripcion_html"] and "data-adj" in lugar["descripcion_html"]
    assert lugar["estilo"]["icono"]["id"] == "R"
    assert con.execute("SELECT count(*) AS n FROM redes.lugares_adjuntos WHERE elemento_id = %s", (lugar["id"],)).fetchone()["n"] == 1
    assert con.execute("SELECT count(*) AS n FROM redes.lugares_carpetas WHERE borrado_en IS NULL").fetchone()["n"] == 1      # the second one reused it
    p = {x["nombre"]: x for x in campo.puntos(con, g["juan"])["puntos"]}["Reserva 1"]
    assert p["estado"] == "aprobado" and p["lugar_id"] == lugar["id"]
    # a chosen folder of its own
    nueva = con.execute("INSERT INTO redes.lugares_carpetas (usuario_id, nombre) VALUES (%s, 'Mi levantamiento') RETURNING id", (g["ana"]["id"],)).fetchone()["id"]
    otro = enviar(con, g["pedro"], tipo="otro", subtipo=None, nombre="Otro 1")
    assert campo.aprobar(con, g["ana"], ids=[otro["id"]], destino="lugares", carpeta_id=nueva)["resultados"][0]["ok"]
    with pytest.raises(db.NoEncontrado):
        campo.aprobar(con, g["ana"], ids=[enviar(con, g["pedro"], nombre="Z")["id"]], destino="lugares", carpeta_id=carpetas[0]["id"])       # not her folder (nor shared)


def test_a_reviewer_sees_possible_duplicates_and_can_correct_before_approving(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    con.execute("INSERT INTO redes.elementos (proyecto_id, tipo, nombre, ubicacion) VALUES (%s, 'poste', 'PT-1', ST_SetSRID(ST_MakePoint(%s, %s), 4326))", (base, LON, LAT))
    cerca = enviar(con, g["juan"], nombre="Cerca", lat=LAT + 0.00002)
    lejos = enviar(con, g["juan"], nombre="Lejos", lat=LAT + 0.01)
    vistos = {p["nombre"]: p for p in campo.puntos(con, g["edu"])["puntos"]}
    assert vistos["Cerca"]["duplicado"]["nombre"] == "PT-1" and vistos["Lejos"]["duplicado"] is None
    assert "duplicado" not in campo.puntos(con, g["juan"])["puntos"][0]                       # the technician is warned when he sends, not here
    c = campo.editar_punto(con, g["edu"], id=cerca["id"], version=cerca["version"], cambios={"nombre": "Cerca (corregido)"})["punto"]
    assert c["estado"] == "editado"
    r = campo.aprobar(con, g["edu"], ids=[cerca["id"]], destino="red")["resultados"][0]            # an «editado» point can be approved
    assert r["ok"] and con.execute("SELECT nombre FROM redes.elementos WHERE id = %s", (r["elemento_id"],)).fetchone()["nombre"] == "Cerca (corregido)"


def test_the_review_methods_are_in_the_remote_list_and_the_photo_travels_as_base64(mundo):
    con, g = mundo
    for nombre in ("campo_puntos", "campo_jornadas", "campo_ubicaciones", "campo_editar", "campo_aprobar", "campo_rechazar", "campo_foto"):
        assert nombre in METODOS
    p = enviar(con, g["juan"])
    f = campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=jpeg())["foto"]
    r = campo.foto_datos(con, g["edu"], id=f["id"], miniatura=True)
    import base64
    assert r["tipo"] == "image/jpeg" and base64.b64decode(r["datos"])[:3] == b"\xff\xd8\xff"


# ------------------------------------------------------------------ real time

def esperar(condicion, segundos=10):
    t0 = time.time()
    while time.time() - t0 < segundos:
        if condicion():
            return True
        time.sleep(0.05)
    raise TimeoutError("la condición no se cumplió")


def test_a_notify_reaches_every_subscriber_and_the_thread_stops_with_the_last_one(mundo, base_redes):
    con, g = mundo
    _, params = base_redes
    escucha = campo_eventos.Escucha(lambda: db.conectar(params=params))
    uno, dos = [], []
    quitar1, quitar2 = escucha.suscribir(uno.append), escucha.suscribir(dos.append)
    assert escucha.conectado.wait(10)
    p = enviar(con, g["juan"])
    esperar(lambda: uno and dos)
    assert uno[0] == {"tabla": "campo_puntos", "id": str(p["id"]), "cambio": "insert", "usuario_id": str(g["juan"]["id"])} and uno == dos
    quitar1()
    campo.editar_punto(con, g["juan"], id=p["id"], version=p["version"], cambios={"notas": "x"})
    esperar(lambda: len(dos) == 2)
    assert len(uno) == 1 and dos[1]["cambio"] == "update"
    quitar2()
    esperar(lambda: not escucha._hilo.is_alive(), 15)                                         # nobody listening: the connection is closed


def test_the_listener_reconnects_when_its_connection_is_cut(mundo, base_redes, monkeypatch):
    con, g = mundo
    nombre, params = base_redes
    monkeypatch.setattr(campo_eventos, "ESPERA_MIN_S", 0.2)
    escucha = campo_eventos.Escucha(lambda: db.conectar(params=params))
    recibidos = []
    quitar = escucha.suscribir(recibidos.append)
    try:
        assert escucha.conectado.wait(10)
        enviar(con, g["juan"], nombre="antes")
        esperar(lambda: len(recibidos) == 1)
        con.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query = 'LISTEN campo' AND datname = %s AND pid <> pg_backend_pid()", (nombre,))
        esperar(lambda: not escucha.conectado.is_set() or True, 2)
        time.sleep(0.5)
        assert escucha.conectado.wait(10)
        enviar(con, g["juan"], nombre="despues", lat=LAT + 0.01)
        esperar(lambda: len(recibidos) >= 2, 15)
        assert recibidos[-1]["cambio"] == "insert"
    finally:
        quitar()


@pytest.fixture
def servicio_real(base_redes, con_redes, entorno, monkeypatch):
    main_, visor_api, cliente, _, _ = entorno
    for nombre, rol in (("jan", "editor"), ("maria", "tecnico")):
        u = usuarios.identificar(con_redes, persona_visor=nombre)
        con_redes.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
    _, params = base_redes
    servicio = ServicioRedes(conectar=lambda: db.conectar(params=params))
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    monkeypatch.setattr(campo_eventos, "_escucha", campo_eventos.Escucha(lambda: db.conectar(params=params)))
    import visor_rutas.campo_api as campo_api
    campo_api.limitador.reiniciar()
    yield main_, con_redes
    servicio.cerrar()


def test_the_server_sends_the_changes_by_sse_only_to_reviewers(servicio_real):
    main_, con = servicio_real
    with servidor_real(main_.app) as puerto:
        base = f"http://127.0.0.1:{puerto}/visor/campo/eventos"
        assert httpx.get(base, headers={"X-Visor-Key": "mala"}).status_code == 401
        assert httpx.get(base, headers=MARIA).status_code == 403                                  # a technician does not get the stream
        recibidos, listo = [], threading.Event()

        def leer():
            with httpx.stream("GET", base, headers=JAN, timeout=30) as r:
                assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
                for linea in r.iter_lines():
                    if linea.startswith(": conectado"):
                        listo.set()
                    if linea.startswith("data: "):
                        recibidos.append(json.loads(linea[6:]))
                        if len(recibidos) == 2:
                            return
        hilo = threading.Thread(target=leer, daemon=True)
        hilo.start()
        assert listo.wait(10)
        assert campo_eventos._escucha.conectado.wait(10)
        # the technician sends a point (through the real API) and then his position: the reviewer gets both, live
        r = httpx.post(f"http://127.0.0.1:{puerto}/visor/campo/puntos", json={"puntos": [punto()]}, headers=MARIA)
        assert r.status_code == 200 and r.json()["resultados"][0]["ok"]
        r = httpx.post(f"http://127.0.0.1:{puerto}/visor/campo/ubicacion", json={"lat": LAT, "lon": LON, "precision_m": 5}, headers=MARIA)
        assert r.status_code == 200
        hilo.join(15)
        assert [a["tabla"] for a in recibidos] == ["campo_puntos", "campo_ubicaciones"] and recibidos[0]["cambio"] == "insert"
        # and the reviewer asks for what changed, with the same key, through the remote methods
        r = httpx.post(f"http://127.0.0.1:{puerto}/visor/redes/campo_puntos", json={"args": {}}, headers=JAN).json()
        assert r["ok"] and [p["usuario"] for p in r["puntos"]] == ["maria"]
        r = httpx.post(f"http://127.0.0.1:{puerto}/visor/redes/campo_ubicaciones", json={"args": {}}, headers=JAN).json()
        assert r["ok"] and [u["nombre"] for u in r["ubicaciones"]] == ["maria"]
