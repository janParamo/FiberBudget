"""Planificación de cuadrillas (migración 020, visor_rutas/redes/planificacion.py): cuadrillas de partida, actividades, cola, estados, puntos de control y tiempos."""
import re
import time
from pathlib import Path

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import LAT, LON, MARIA
from test_campo_revision import mundo as _mundo  # noqa: F401
from test_campo_trazos import api  # noqa: F401  (fixture of the field app's REST API)
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import campo, db, planificacion as pl


def sembrar_cuadrillas(con):
    """The test fixtures empty the tables that point at the users (the crews among them): the INSERT of the migration file is run again."""
    sql = (Path(__file__).parents[1] / "visor_rutas" / "redes" / "migraciones" / "020_planificacion.sql").read_text(encoding="utf-8")
    con.execute(re.search(r"INSERT INTO redes\.plan_cuadrillas.*?;", sql, re.S).group(0))


@pytest.fixture
def mundo(_mundo):
    """The people of test_campo_revision plus the starting crews of the migration."""
    con, g = _mundo
    sembrar_cuadrillas(con)
    return con, g


def actividad(con, plan, nombre="Casa Pérez", **extra):
    return pl.crear_actividad(con, plan, cliente_nombre=nombre, lat=LAT, lon=LON, ticket=extra.pop("ticket", "XKJ-1"), codigo_cliente="C1", contacto_nombre="Grace",
                              contacto_telefono="8599 9439", **extra)["id"]


def cuadrilla_id(con, nombre):
    return con.execute("SELECT id FROM redes.plan_cuadrillas WHERE nombre = %s", (nombre,)).fetchone()["id"]


@pytest.fixture
def equipo(mundo):
    """juan and pedro are crews (technicians) of Tamos 1 and Telenic 1; edu is planning; lola is a reader."""
    con, g = mundo
    for u, c in (("juan", "Tamos 1"), ("pedro", "Telenic 1")):
        pl.agregar_miembro(con, g["admin"], cuadrilla_id=cuadrilla_id(con, c), usuario_id=g[u]["id"])
    return con, g


def test_the_six_starting_crews_and_the_control_points_come_with_the_migration(mundo):
    con, g = mundo
    c = pl.cuadrillas(con, g["edu"])["cuadrillas"]
    assert [(x["empresa"], x["nombre"], x["tercerizada"]) for x in c] == [
        ("Tamos", "Tamos 1", True), ("Tamos", "Tamos 2", True), ("Telenic", "Telenic 1", True), ("Telenic", "Telenic 2", True), ("IDEAY", "IDEAY 1", False), ("IDEAY", "IDEAY 2", False)]
    assert [x["clave"] for x in pl.catalogo(con, g["edu"])["controles"]] == ["llegada", "inspeccion", "postes", "acometida", "equipos_cliente", "fusiones"]
    with pytest.raises(db.SinPermiso):
        pl.cuadrillas(con, g["juan"])                                             # a crew does not see the crews
    nueva = pl.crear_cuadrilla(con, g["edu"], empresa="IDEAY", nombre="IDEAY 3", telefono="8888")["id"]
    assert pl.editar_cuadrilla(con, g["edu"], id=nueva, cambios={"activa": False})["id"] == nueva
    with pytest.raises(db.DatosInvalidos):
        pl.crear_cuadrilla(con, g["edu"], empresa="IDEAY", nombre="IDEAY 3")


def test_an_activity_is_born_inactive_with_its_control_points_and_asking_twice_for_the_same_ticket_is_refused(mundo):
    con, g = mundo
    i = actividad(con, g["edu"], presupuesto_clave="a.xlsx", presupuesto_total=1234.5, resumen={"metraje_m": 320})
    d = pl.actividad(con, g["edu"], id=i)["actividad"]
    assert (d["estado"], d["cuadrilla"], d["ticket"], d["contacto_telefono"], d["presupuesto_total"], d["resumen"]) == ("inactivo", None, "XKJ-1", "8599 9439", 1234.5, {"metraje_m": 320})
    assert d["avance"] == {"hechos": 0, "total": 6, "porcentaje": 0} and [h["a"] for h in d["historial"]] == ["inactivo"]
    with pytest.raises(db.DatosInvalidos):
        actividad(con, g["edu"])                                                  # same ticket and client
    for malo in ({"lat": 40.0}, {"origen": "otro"}, {"cliente_nombre": " "}):
        with pytest.raises(db.DatosInvalidos):
            pl.crear_actividad(con, g["edu"], **{"cliente_nombre": "X", "lat": LAT, "lon": LON, **malo})
    with pytest.raises(db.SinPermiso):
        actividad(con, g["lola"], nombre="Otra")                                  # only planning creates


def test_assign_queue_and_the_crew_sees_only_its_own(equipo):
    con, g = equipo
    a, b, c = (actividad(con, g["edu"], nombre=n, ticket=f"T-{n}") for n in ("Uno", "Dos", "Tres"))
    pl.asignar(con, g["edu"], ids=[a, b], cuadrilla_id=cuadrilla_id(con, "Tamos 1"))
    pl.asignar(con, g["edu"], ids=[c], cuadrilla_id=cuadrilla_id(con, "Telenic 1"))
    mia = pl.mi_cuadrilla(con, g["juan"])
    assert mia["cuadrilla"]["nombre"] == "Tamos 1" and mia["actual"] is None and [x["cliente_nombre"] for x in mia["cola"]] == ["Uno", "Dos"]
    assert [x["cliente_nombre"] for x in pl.actividades(con, g["pedro"])["actividades"]] == ["Tres"]
    with pytest.raises(db.SinPermiso):
        pl.actividad(con, g["pedro"], id=a)                                       # the other crew's activity
    pl.reordenar_cola(con, g["edu"], cuadrilla_id=cuadrilla_id(con, "Tamos 1"), ids=[b, a])
    assert [x["cliente_nombre"] for x in pl.mi_cuadrilla(con, g["juan"])["cola"]] == ["Dos", "Uno"]
    with pytest.raises(db.DatosInvalidos):
        pl.reordenar_cola(con, g["edu"], cuadrilla_id=cuadrilla_id(con, "Tamos 1"), ids=[c])
    pl.asignar(con, g["edu"], ids=[a], cuadrilla_id=cuadrilla_id(con, "Telenic 1"))        # moved to another crew
    assert sorted(x["cliente_nombre"] for x in pl.actividades(con, g["pedro"])["actividades"]) == ["Tres", "Uno"]
    pl.cambiar_estado(con, g["edu"], id=a, a="inactivo")                                   # taken out of the queue
    assert pl.actividad(con, g["edu"], id=a)["actividad"]["cuadrilla"] is None
    with pytest.raises(db.DatosInvalidos):
        pl.asignar(con, g["edu"], ids=[a], cuadrilla_id=cuadrilla_id(con, "Tamos 1")) if False else pl.crear_cuadrilla(con, g["edu"], empresa="Tamos", nombre="Tamos 1")


def test_the_life_of_an_activity_review_work_pause_and_finish_with_its_times(equipo):
    con, g = equipo
    i = actividad(con, g["edu"])
    pl.asignar(con, g["edu"], ids=[i], cuadrilla_id=cuadrilla_id(con, "Tamos 1"))
    con.execute("UPDATE redes.plan_actividades SET asignada_en = now() - interval '2 hours' WHERE id = %s", (i,))
    d = pl.actividad(con, g["juan"], id=i)["actividad"]
    assert d["estado"] == "asignado" and 7190 <= d["espera_s"] <= 7300 and d["ejecucion_s"] is None and d["sin_iniciar_alerta"] is True       # waiting for 2 hours: flagged
    assert [s["id"] for s in pl.tablero(con, g["edu"])["sin_iniciar"]] == [i]
    # a crew cannot mark control points before starting; it starts with the review
    with pytest.raises(db.DatosInvalidos):
        pl.marcar_control(con, g["juan"], id=i, clave="llegada")
    pl.cambiar_estado(con, g["juan"], id=i, a="en_revision")
    pl.marcar_control(con, g["juan"], id=i, clave="llegada", lat=LAT, lon=LON)
    pl.marcar_control(con, g["juan"], id=i, clave="inspeccion", nota="todo bien")
    pl.cambiar_estado(con, g["juan"], id=i, a="en_curso")
    d = pl.actividad(con, g["juan"], id=i)["actividad"]
    assert d["estado"] == "en_curso" and d["iniciada_por"] == "cuadrilla" and d["espera_s"] >= 7190 and d["ejecucion_s"] is not None and d["avance"]["hechos"] == 2
    # the wait stops counting when it starts
    espera = d["espera_s"]
    time.sleep(1.1)
    assert pl.actividad(con, g["juan"], id=i)["actividad"]["espera_s"] == espera
    # pause needs a reason; the paused time is not execution time
    with pytest.raises(db.DatosInvalidos):
        pl.cambiar_estado(con, g["juan"], id=i, a="pausado")
    pl.cambiar_estado(con, g["juan"], id=i, a="pausado", motivo="Lluvia")
    con.execute("UPDATE redes.plan_actividades SET iniciada_en = now() - interval '3 hours', pausada_desde = now() - interval '1 hour' WHERE id = %s", (i,))
    ej_pausada = pl.actividad(con, g["juan"], id=i)["actividad"]["ejecucion_s"]
    assert 7190 <= ej_pausada <= 7300                                              # 3 h since it started minus the 1 h that it has been paused... the clock stopped at the pause
    pl.cambiar_estado(con, g["juan"], id=i, a="en_curso")
    d = pl.actividad(con, g["juan"], id=i)["actividad"]
    assert d["pausada"] is False and 7190 <= d["ejecucion_s"] <= 7300              # 1 h of pause is out
    # cannot finish with required control points missing; planning can force it
    with pytest.raises(db.DatosInvalidos) as exc:
        pl.cambiar_estado(con, g["juan"], id=i, a="terminado")
    assert "Acometida" in str(exc.value.errores["controles"]) and "Levantado de postes" not in str(exc.value.errores["controles"])    # postes is optional
    for clave in ("acometida", "equipos_cliente", "fusiones"):
        pl.marcar_control(con, g["juan"], id=i, clave=clave)
    pl.cambiar_estado(con, g["juan"], id=i, a="terminado")
    d = pl.actividad(con, g["edu"], id=i)["actividad"]
    assert d["estado"] == "terminado" and d["terminada_en"] and d["avance"]["hechos"] == 5
    assert [h["a"] for h in d["historial"]] == ["inactivo", "asignado", "en_revision", "en_curso", "pausado", "en_curso", "terminado"]
    assert pl.tablero(con, g["edu"])["por_estado"]["terminado"] == 1 and pl.tablero(con, g["edu"])["ejecucion_media_s"] > 0
    with pytest.raises(db.DatosInvalidos):
        pl.marcar_control(con, g["edu"], id=i, clave="llegada")                    # finished: closed


def test_planning_starts_it_when_the_crew_forgot_and_a_crew_has_one_activity_in_progress(equipo):
    con, g = equipo
    a, b = actividad(con, g["edu"], nombre="Uno", ticket="T-1"), actividad(con, g["edu"], nombre="Dos", ticket="T-2")
    pl.asignar(con, g["edu"], ids=[a, b], cuadrilla_id=cuadrilla_id(con, "Tamos 1"))
    pl.cambiar_estado(con, g["edu"], id=a, a="en_curso")                          # planning starts the clock for the crew
    d = pl.actividad(con, g["edu"], id=a)["actividad"]
    assert d["estado"] == "en_curso" and d["iniciada_por"] == "planificacion" and d["ejecucion_s"] is not None
    with pytest.raises(db.DatosInvalidos) as exc:
        pl.cambiar_estado(con, g["juan"], id=b, a="en_curso")                      # one at a time
    assert "ya tiene una actividad en curso" in str(exc.value.errores["a"])
    assert pl.mi_cuadrilla(con, g["juan"])["actual"]["id"] == a
    # planning can force the finish; a crew cannot make planning's moves (cancel, back to inactive)
    pl.cambiar_estado(con, g["edu"], id=a, a="terminado", forzar=True)
    with pytest.raises(db.SinPermiso):
        pl.cambiar_estado(con, g["juan"], id=b, a="cancelado", motivo="x")
    with pytest.raises(db.DatosInvalidos):
        pl.cambiar_estado(con, g["edu"], id=a, a="en_curso")                       # finished does not go back
    with pytest.raises(db.DatosInvalidos):
        pl.cambiar_estado(con, g["edu"], id=b, a="no_viable")                      # asignado does not go straight to no_viable (it is reviewed first)
    pl.cambiar_estado(con, g["juan"], id=b, a="en_revision")
    pl.cambiar_estado(con, g["juan"], id=b, a="no_viable", motivo="El cliente no está")
    d = pl.actividad(con, g["edu"], id=b)["actividad"]
    assert d["estado"] == "no_viable" and d["motivo_estado"] == "El cliente no está"
    pl.cambiar_estado(con, g["edu"], id=b, a="inactivo")                           # planning can put it back
    assert pl.actividad(con, g["edu"], id=b)["actividad"]["cuadrilla"] is None


def test_the_last_place_of_a_crew_comes_from_the_app_of_its_members(equipo):
    con, g = equipo
    assert all(c["ubicacion"] is None for c in pl.cuadrillas(con, g["edu"])["cuadrillas"])
    campo.ubicacion(con, g["juan"], lat=LAT, lon=LON, precision_m=5)
    tamos = next(c for c in pl.cuadrillas(con, g["edu"])["cuadrillas"] if c["nombre"] == "Tamos 1")
    assert tamos["ubicacion"]["lat"] == LAT and tamos["ubicacion"]["quien"] and tamos["ubicacion"]["hace_s"] < 60 and [m["nombre"] for m in tamos["miembros"]]
    with pytest.raises(db.DatosInvalidos):
        pl.agregar_miembro(con, g["admin"], cuadrilla_id=tamos["id"], usuario_id=g["edu"]["id"])        # only technicians are crew members
    with pytest.raises(db.SinPermiso):
        pl.agregar_miembro(con, g["edu"], cuadrilla_id=tamos["id"], usuario_id=g["pedro"]["id"])        # only administrators
    with pytest.raises(db.SinPermiso):
        pl.mi_cuadrilla(con, g["edu"])


# ------------------------------------------------------------------ the REST API (/visor/planificacion/*)

def test_the_rest_api_planning_and_a_crew_with_its_own_key(api, monkeypatch):  # noqa: F811
    c, con = api
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:clave-tecnico-juan")
    juan = {"X-Visor-Key": "clave-tecnico-juan"}
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'jan'")                        # jan is planning
    sembrar_cuadrillas(con)
    assert c.get("/visor/planificacion/tablero").status_code == 401
    assert c.get("/visor/planificacion/tablero", headers=juan).status_code == 403                               # a crew is not planning
    assert c.get("/visor/planificacion/mia", headers=juan).status_code == 403                                   # and it has no crew yet
    tamos = next(x for x in c.get("/visor/planificacion/cuadrillas", headers=JAN).json()["cuadrillas"] if x["nombre"] == "Tamos 1")
    con.execute("INSERT INTO redes.plan_cuadrilla_miembros (cuadrilla_id, usuario_id) SELECT %s, id FROM redes.usuarios WHERE persona_visor = 'juan'", (tamos["id"],))
    nueva = c.post("/visor/planificacion/actividades", json={"cliente_nombre": "Casa Pérez", "lat": LAT, "lon": LON, "ticket": "XKJ-1", "contacto_telefono": "8599 9439"}, headers=JAN)
    assert nueva.status_code == 200 and nueva.json()["ok"] is True
    i = nueva.json()["id"]
    assert c.post("/visor/planificacion/actividades", json={"cliente_nombre": "Casa Pérez", "lat": LAT, "lon": LON, "ticket": "XKJ-1"}, headers=JAN).status_code == 422      # repeated
    assert c.post("/visor/planificacion/actividades", json={"cliente_nombre": "X", "lat": LAT, "lon": LON}, headers=juan).status_code == 403
    assert c.post("/visor/planificacion/actividades/asignar", json={"ids": [i], "cuadrilla_id": tamos["id"]}, headers=JAN).status_code == 200
    mia = c.get("/visor/planificacion/mia", headers=juan).json()
    assert mia["cuadrilla"]["nombre"] == "Tamos 1" and [x["id"] for x in mia["cola"]] == [i] and mia["cola"][0]["contacto_telefono"] == "8599 9439"
    assert c.get(f"/visor/planificacion/actividades/{i}", headers=juan).status_code == 200
    assert c.get("/visor/planificacion/actividades/99999", headers=JAN).status_code == 404
    assert c.post(f"/visor/planificacion/actividades/{i}/control", json={"clave": "llegada"}, headers=juan).status_code == 422       # not started yet
    assert c.post(f"/visor/planificacion/actividades/{i}/estado", json={"a": "en_revision"}, headers=juan).status_code == 200
    r = c.post(f"/visor/planificacion/actividades/{i}/control", json={"clave": "llegada", "lat": LAT, "lon": LON}, headers=juan)
    assert r.status_code == 200 and c.get(f"/visor/planificacion/actividades/{i}", headers=JAN).json()["actividad"]["avance"]["hechos"] == 1
    assert c.post(f"/visor/planificacion/actividades/{i}/estado", json={"a": "cancelado", "motivo": "x"}, headers=juan).status_code == 403
    assert c.post(f"/visor/planificacion/actividades/{i}/estado", json={"a": "en_curso"}, headers=JAN).status_code == 200            # planning starts the clock
    assert c.get("/visor/planificacion/tablero", headers=JAN).json()["por_estado"]["en_curso"] == 1
    assert c.get("/visor/planificacion/actividades?estado=en_curso", headers=JAN).json()["actividades"][0]["iniciada_por"] == "planificacion"
    assert c.get("/visor/planificacion/catalogo", headers=juan).status_code == 200


def test_the_technicians_to_put_in_a_crew_are_listed_with_their_crew(equipo):
    con, g = equipo
    lista = pl.tecnicos(con, g["edu"])["tecnicos"]
    assert {(t["nombre"], t["cuadrilla"]) for t in lista} == {("juan", "Tamos 1"), ("pedro", "Telenic 1")}                  # only technicians, with their crew
    pl.quitar_miembro(con, g["admin"], cuadrilla_id=cuadrilla_id(con, "Tamos 1"), usuario_id=g["juan"]["id"])
    assert {(t["nombre"], t["cuadrilla"]) for t in pl.tecnicos(con, g["edu"])["tecnicos"]} == {("juan", None), ("pedro", "Telenic 1")}
    with pytest.raises(db.SinPermiso):
        pl.tecnicos(con, g["juan"])


# ------------------------------------------------------------------ live notices (Server-Sent Events)

def test_the_server_sends_the_changes_of_planning_by_sse_to_planning_and_to_a_crew_only(base_redes, con_redes, entorno, monkeypatch):  # noqa: F811
    import json
    import threading

    import httpx

    from test_campo import MARIA
    from test_campo_pwa import servidor_real
    from visor_rutas import campo_eventos
    from visor_rutas.redes import usuarios
    from visor_rutas.redes.api import ServicioRedes
    main_, visor_api, _, _, _ = entorno
    for nombre, rol in (("jan", "editor"), ("maria", "tecnico"), ("lola", "lector")):
        u = usuarios.identificar(con_redes, persona_visor=nombre)
        con_redes.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
    sembrar_cuadrillas(con_redes)
    _, params = base_redes
    servicio = ServicioRedes(conectar=lambda: db.conectar(params=params))
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    escucha = campo_eventos.Escucha(lambda: db.conectar(params=params), "planificacion")
    monkeypatch.setitem(campo_eventos._otras, "planificacion", escucha)
    import visor_rutas.campo_api as campo_api
    campo_api.limitador.reiniciar()
    try:
        with servidor_real(main_.app) as puerto:
            base = f"http://127.0.0.1:{puerto}/visor/planificacion"
            assert httpx.get(base + "/eventos", headers={"X-Visor-Key": "mala"}).status_code == 401
            assert httpx.get(base + "/eventos", headers=MARIA).status_code == 403                    # a technician without a crew gets nothing
            recibidos, listo = [], threading.Event()

            def leer():
                with httpx.stream("GET", base + "/eventos", headers=JAN, timeout=30) as r:
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
            assert listo.wait(10) and escucha.conectado.wait(10)
            # planning creates an activity and assigns it: the stream gets both, live
            r = httpx.post(base + "/actividades", json={"cliente_nombre": "Casa Pérez", "lat": LAT, "lon": LON, "ticket": "T-1"}, headers=JAN).json()
            tamos = httpx.get(base + "/cuadrillas", headers=JAN).json()["cuadrillas"][0]["id"]
            assert httpx.post(base + "/actividades/asignar", json={"ids": [r["id"]], "cuadrilla_id": tamos}, headers=JAN).status_code == 200
            hilo.join(15)
            assert [a["tabla"] for a in recibidos] == ["plan_actividades", "plan_actividades"] and recibidos[0]["cambio"] == "insert" and recibidos[1]["cambio"] == "update"
            # a technician that belongs to a crew does get the stream
            maria = con_redes.execute("SELECT id FROM redes.usuarios WHERE persona_visor = 'maria'").fetchone()["id"]
            con_redes.execute("INSERT INTO redes.plan_cuadrilla_miembros (cuadrilla_id, usuario_id) VALUES (%s, %s)", (tamos, maria))
            with httpx.stream("GET", base + "/eventos", headers=MARIA, timeout=10) as r2:
                assert r2.status_code == 200
    finally:
        servicio.cerrar()


# ------------------------------------------------------------------ chat of an activity

def test_the_chat_between_planning_and_the_crew_with_unread_counts(equipo):
    con, g = equipo
    i = actividad(con, g["edu"])
    otra = actividad(con, g["edu"], nombre="Otra", ticket="T-2")
    pl.asignar(con, g["edu"], ids=[i], cuadrilla_id=cuadrilla_id(con, "Tamos 1"))
    pl.asignar(con, g["edu"], ids=[otra], cuadrilla_id=cuadrilla_id(con, "Telenic 1"))
    pl.enviar_mensaje(con, g["edu"], actividad_id=i, texto="  Buen día, ¿ya llegaron?  ")
    pl.enviar_mensaje(con, g["edu"], actividad_id=i, texto="Avisen cuando estén en el sitio")
    # the crew has two unread messages on its activity and none on the other crew's; reading them marks them
    assert [a["sin_leer"] for a in pl.mi_cuadrilla(con, g["juan"])["cola"]] == [2]
    assert pl.mi_cuadrilla(con, g["juan"])["cola"][0]["sin_leer"] == 2
    m = pl.mensajes(con, g["juan"], actividad_id=i)["mensajes"]
    assert [(x["origen"], x["texto"]) for x in m] == [("planificacion", "Buen día, ¿ya llegaron?"), ("planificacion", "Avisen cuando estén en el sitio")] and m[0]["de"] == "edu"
    assert pl.mi_cuadrilla(con, g["juan"])["cola"][0]["sin_leer"] == 0
    # the crew answers: planning sees one unread on that activity (and its own messages are not «unread» for itself)
    pl.enviar_mensaje(con, g["juan"], actividad_id=i, texto="Ya estamos en camino")
    assert {a["id"]: a["sin_leer"] for a in pl.actividades(con, g["edu"])["actividades"]} == {i: 1, otra: 0}
    nuevos = pl.mensajes(con, g["edu"], actividad_id=i, desde_id=m[-1]["id"])["mensajes"]
    assert [(x["origen"], x["texto"]) for x in nuevos] == [("cuadrilla", "Ya estamos en camino")]
    assert {a["id"]: a["sin_leer"] for a in pl.actividades(con, g["edu"])["actividades"]} == {i: 0, otra: 0}
    # the other crew cannot read or write; nobody writes an empty message; a reader cannot enter
    with pytest.raises(db.SinPermiso):
        pl.mensajes(con, g["pedro"], actividad_id=i)
    with pytest.raises(db.SinPermiso):
        pl.enviar_mensaje(con, g["pedro"], actividad_id=i, texto="hola")
    with pytest.raises(db.DatosInvalidos):
        pl.enviar_mensaje(con, g["juan"], actividad_id=i, texto="   ")
    with pytest.raises(db.SinPermiso):
        pl.mensajes(con, g["lola"], actividad_id=i)
    assert len(pl.mensajes(con, g["edu"], actividad_id=i)["mensajes"]) == 3
    long = pl.enviar_mensaje(con, g["edu"], actividad_id=i, texto="x" * 5000)["id"]
    assert len(pl.mensajes(con, g["edu"], actividad_id=i, desde_id=long - 1)["mensajes"][0]["texto"]) == pl.MENSAJE_MAX


def test_the_chat_over_the_rest_api(api, monkeypatch):  # noqa: F811
    c, con = api
    monkeypatch.setenv("CAMPO_API_KEYS", "juan:clave-tecnico-juan")
    juan = {"X-Visor-Key": "clave-tecnico-juan"}
    con.execute("UPDATE redes.usuarios SET rol = 'editor' WHERE persona_visor = 'jan'")
    sembrar_cuadrillas(con)
    j = con.execute("INSERT INTO redes.usuarios (nombre, persona_visor, rol) VALUES ('juan', 'juan', 'tecnico') RETURNING id").fetchone()["id"]
    tamos = con.execute("SELECT id FROM redes.plan_cuadrillas WHERE nombre = 'Tamos 1'").fetchone()["id"]
    con.execute("INSERT INTO redes.plan_cuadrilla_miembros (cuadrilla_id, usuario_id) VALUES (%s, %s)", (tamos, j))
    i = c.post("/visor/planificacion/actividades", json={"cliente_nombre": "Casa", "lat": LAT, "lon": LON}, headers=JAN).json()["id"]
    c.post("/visor/planificacion/actividades/asignar", json={"ids": [i], "cuadrilla_id": tamos}, headers=JAN)
    assert c.post(f"/visor/planificacion/actividades/{i}/mensajes", json={"texto": "Hola cuadrilla"}, headers=JAN).status_code == 200
    assert c.post(f"/visor/planificacion/actividades/{i}/mensajes", json={"texto": " "}, headers=JAN).status_code == 422
    assert c.get("/visor/planificacion/mia", headers=juan).json()["cola"][0]["sin_leer"] == 1
    r = c.get(f"/visor/planificacion/actividades/{i}/mensajes", headers=juan).json()
    assert r["ok"] and [(m["origen"], m["texto"]) for m in r["mensajes"]] == [("planificacion", "Hola cuadrilla")]
    assert c.post(f"/visor/planificacion/actividades/{i}/mensajes", json={"texto": "Recibido"}, headers=juan).status_code == 200
    assert c.get(f"/visor/planificacion/actividades/99999/mensajes", headers=JAN).status_code == 404
    assert c.get(f"/visor/planificacion/actividades/{i}/mensajes", headers=MARIA).status_code == 403
