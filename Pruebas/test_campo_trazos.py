"""App de campo, fase 5 (servidor): cables trazados en campo (idempotentes, permisos, revisión: aprobar como cable de la red / de un proyecto o como ruta de
Mis lugares) y la red de referencia por zona para el teléfono."""
import uuid
from datetime import datetime, timezone

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import LAT, LON, MARIA, jpeg, punto  # noqa: F401
from test_campo_revision import crear_proyecto, mundo  # noqa: F401
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import campo, db
from visor_rutas.redes.api import METODOS


def trazo(**cambios):
    return {"uuid_cliente": str(uuid.uuid4()), "modo": "puntos", "tipo_cable": "ADSS", "hilos": 12, "notas": "por la calle principal",
            "puntos": [{"lat": LAT, "lon": LON}, {"lat": LAT + 0.0005, "lon": LON}, {"lat": LAT + 0.0010, "lon": LON + 0.0004}],
            "capturado_en": datetime.now(timezone.utc).isoformat(), **cambios}


def enviar_trazo(con, tecnico, **cambios):
    return campo.guardar_trazos(con, tecnico, trazos=[trazo(**cambios)])["resultados"][0]["trazo"]


def poste_en(con, proyecto, nombre, lat, lon, tipo="poste"):
    return con.execute("INSERT INTO redes.elementos (proyecto_id, tipo, nombre, ubicacion) VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) RETURNING id",
                       (proyecto, tipo, nombre, lon, lat)).fetchone()["id"]


# ------------------------------------------------------------------ saving

def test_a_trace_sent_twice_is_one_trace_and_it_measures_itself(mundo):
    con, g = mundo
    t = trazo()
    r1 = campo.guardar_trazos(con, g["juan"], trazos=[t])["resultados"][0]
    r2 = campo.guardar_trazos(con, g["juan"], trazos=[t, dict(t)])["resultados"]
    assert r1["ok"] and r1["repetido"] is False and r1["trazo"]["estado"] == "pendiente" and r1["trazo"]["n_puntos"] == 3
    assert 100 < r1["trazo"]["longitud_m"] < 200 and r1["trazo"]["puntos"][0] == [pytest.approx(LAT), pytest.approx(LON)]      # [lat, lon], as the app draws them
    assert [x["repetido"] for x in r2] == [True, True] and con.execute("SELECT count(*) AS n FROM redes.campo_trazos").fetchone()["n"] == 1
    otro = campo.guardar_trazos(con, g["pedro"], trazos=[t])["resultados"][0]
    assert otro["ok"] is False and "otro técnico" in otro["error"]
    assert con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad = 'campo_trazo' AND accion = 'crear'").fetchone()["n"] == 1


def test_a_trace_is_validated_per_trace(mundo):
    con, g = mundo
    aqui = {"lat": LAT, "lon": LON}
    malos = [trazo(puntos=[aqui]), trazo(puntos=[aqui, dict(aqui)]), trazo(puntos=[aqui, {"lat": 40, "lon": LON}]), trazo(puntos=[aqui, {"lat": "x", "lon": LON}]),
             trazo(puntos="no"), trazo(modo="volando"), trazo(tipo_cable="COBRE"), trazo(hilos=13), trazo(uuid_cliente="x"), trazo(puntos=[aqui] * 3000 + [{"lat": LAT + 1e-4, "lon": LON}])]
    r = campo.guardar_trazos(con, g["juan"], trazos=malos + [trazo(tipo_cable=None, hilos=None, modo="recorrido", postes=[{"nombre": "PT-1", "lat": LAT, "lon": LON}])])["resultados"]
    assert [x["ok"] for x in r] == [False] * 10 + [True]
    assert r[0]["errores"].keys() == {"puntos"} and r[5]["errores"].keys() == {"modo"} and r[6]["errores"].keys() == {"tipo_cable"} and r[7]["errores"].keys() == {"hilos"}
    assert r[10]["trazo"]["tipo_cable"] is None and r[10]["trazo"]["hilos"] is None and r[10]["trazo"]["postes"][0]["nombre"] == "PT-1"
    with pytest.raises(db.DatosInvalidos):
        campo.guardar_trazos(con, g["juan"], trazos=[])
    with pytest.raises(db.DatosInvalidos):
        campo.guardar_trazos(con, g["juan"], trazos=[trazo() for _ in range(21)])
    with pytest.raises(db.SinPermiso):
        campo.guardar_trazos(con, g["lola"], trazos=[trazo()])


def test_listing_and_owner_rules_of_the_traces(mundo):
    con, g = mundo
    j = campo.abrir_jornada(con, g["juan"], nombre="Calle norte")["jornada"]
    a, b = enviar_trazo(con, g["juan"]), enviar_trazo(con, g["pedro"], notas="otro")
    assert a["jornada_id"] == j["id"] and b["jornada_id"] is None
    assert [t["id"] for t in campo.trazos(con, g["juan"])["trazos"]] == [a["id"]]
    assert {t["id"] for t in campo.trazos(con, g["edu"])["trazos"]} == {a["id"], b["id"]}
    assert [t["id"] for t in campo.trazos(con, g["edu"], jornada=j["id"])["trazos"]] == [a["id"]]
    with pytest.raises(db.SinPermiso):
        campo.editar_trazo(con, g["pedro"], id=a["id"], version=a["version"], cambios={"notas": "x"})
    with pytest.raises(db.SinPermiso):
        campo.borrar_trazo(con, g["pedro"], id=a["id"])
    e = campo.editar_trazo(con, g["juan"], id=a["id"], version=a["version"], cambios={"hilos": 24, "tipo_cable": "FLAT", "puntos": [], "estado": "aprobado"})["trazo"]
    assert (e["hilos"], e["tipo_cable"], e["estado"], len(e["puntos"])) == (24, "FLAT", "pendiente", 3)         # only type, fibres and notes can change
    with pytest.raises(db.ConflictoVersion):
        campo.editar_trazo(con, g["juan"], id=a["id"], version=a["version"], cambios={"hilos": 48})
    with pytest.raises(db.DatosInvalidos):
        campo.editar_trazo(con, g["juan"], id=a["id"], version=e["version"], cambios={"puntos": []})
    c = campo.editar_trazo(con, g["edu"], id=a["id"], version=e["version"], cambios={"notas": "revisado"})["trazo"]
    assert c["estado"] == "editado"
    desde = "2000-01-01T00:00:00+00:00"
    campo.borrar_trazo(con, g["pedro"], id=b["id"])
    cambios = campo.trazos(con, g["pedro"], desde=desde)["trazos"]
    assert [(t["id"], t["borrado"]) for t in cambios] == [(b["id"], True)]                    # a sync tells the phone to drop it
    assert campo.trazos(con, g["pedro"])["trazos"] == []


# ------------------------------------------------------------------ review

def test_rejecting_a_trace_needs_a_reason_and_the_technician_reads_it(mundo):
    con, g = mundo
    a = enviar_trazo(con, g["juan"])
    with pytest.raises(db.SinPermiso):
        campo.rechazar_trazos(con, g["juan"], ids=[a["id"]], motivo="no")
    with pytest.raises(db.DatosInvalidos):
        campo.rechazar_trazos(con, g["edu"], ids=[a["id"]], motivo=" ")
    assert campo.rechazar_trazos(con, g["edu"], ids=[a["id"]], motivo="Mal trazado")["resultados"][0]["ok"]
    mio = campo.trazos(con, g["juan"])["trazos"][0]
    assert mio["estado"] == "rechazado" and mio["motivo_rechazo"] == "Mal trazado"
    assert campo.rechazar_trazos(con, g["edu"], ids=[a["id"]], motivo="otra vez")["resultados"][0]["ok"] is False
    with pytest.raises(db.SinPermiso):
        campo.editar_trazo(con, g["juan"], id=a["id"], version=mio["version"], cambios={"notas": "x"})


def test_approving_a_trace_as_a_cable_snaps_its_ends_to_the_poles_of_the_project(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    uno = poste_en(con, base, "PT-1", LAT + 0.00005, LON)                    # ≈ 5.5 m from the first point
    dos = poste_en(con, base, "MF-9", LAT + 0.0010, LON + 0.0004 + 0.00003, tipo="mufa")        # ≈ 3 m from the last one
    t = enviar_trazo(con, g["juan"], hilos=24, tipo_cable="FLAT")
    r = campo.aprobar_trazos(con, g["edu"], ids=[t["id"]], destino="red")
    assert r["proyecto_id"] == base and r["resultados"][0]["ok"] and r["resultados"][0]["cable_id"]
    cable = con.execute("SELECT * FROM redes.cables WHERE id = %s", (r["resultados"][0]["cable_id"],)).fetchone()
    assert (cable["proyecto_id"], cable["origen_id"], cable["destino_id"], cable["hilos"], cable["tipo"], cable["clase"]) == (base, uno, dos, 24, "FLAT", "distribucion")
    assert cable["nombre"] == "Cable PT-1 – MF-9" and "Trazado en campo por juan" in cable["descripcion"] and "por la calle principal" in cable["descripcion"]
    assert len(cable["vertices"]) == 3 and cable["vertices"][0]["elemento_id"] == uno and cable["vertices"][-1]["elemento_id"] == dos      # its ends are the poles
    assert float(cable["longitud_m"]) > 100
    assert con.execute("SELECT count(*) AS n FROM redes.hilos WHERE cable_id = %s", (cable["id"],)).fetchone()["n"] == 24                  # its fibres 1..N exist
    p = campo.trazos(con, g["juan"])["trazos"][0]
    assert p["estado"] == "aprobado" and p["cable_id"] == cable["id"]
    assert campo.aprobar_trazos(con, g["edu"], ids=[t["id"]], destino="red")["resultados"][0]["ok"] is False                                # already approved
    assert con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad = 'cable' AND accion = 'crear'").fetchone()["n"] == 1


def test_a_trace_whose_ends_are_not_at_a_pole_cannot_become_a_cable_but_can_go_to_mis_lugares(mundo):
    con, g = mundo
    base = crear_proyecto(con, "RB", base=True)
    poste_en(con, base, "PT-1", LAT, LON)                                       # only the start has a pole
    t = enviar_trazo(con, g["juan"])
    r = campo.aprobar_trazos(con, g["edu"], ids=[t["id"]], destino="red")["resultados"][0]
    assert r["ok"] is False and "extremo final" in r["error"] and "Mis lugares" in r["error"]
    assert campo.trazos(con, g["juan"])["trazos"][0]["estado"] == "pendiente"             # nothing was left half done
    assert con.execute("SELECT count(*) AS n FROM redes.cables").fetchone()["n"] == 0
    ok = campo.aprobar_trazos(con, g["edu"], ids=[t["id"]], destino="lugares")["resultados"][0]
    assert ok["ok"] and ok["lugar_id"] and ok["cable_id"] is None
    lugar = con.execute("SELECT l.tipo, l.nombre, l.descripcion_html, ST_NPoints(l.geom) AS n, c.nombre AS carpeta, c.usuario_id FROM redes.lugares_elementos l "
                        "JOIN redes.lugares_carpetas c ON c.id = l.carpeta_id").fetchone()
    assert (lugar["tipo"], lugar["n"], lugar["carpeta"], lugar["usuario_id"]) == ("ruta", 3, "Campo – juan", g["edu"]["id"])
    assert "Cable trazado en campo" in lugar["descripcion_html"] and "ADSS" in lugar["descripcion_html"] and "12 hilos" in lugar["descripcion_html"]


def test_a_cable_to_a_project_needs_that_project_and_two_different_ends(mundo):
    con, g = mundo
    propio = crear_proyecto(con, "RUTA", asignar=[g["edu"]])
    uno = poste_en(con, propio, "PT-1", LAT, LON)
    t = enviar_trazo(con, g["juan"], puntos=[{"lat": LAT, "lon": LON}, {"lat": LAT + 0.00005, "lon": LON}, {"lat": LAT, "lon": LON + 0.00001}])      # starts and ends at the same pole
    r = campo.aprobar_trazos(con, g["edu"], ids=[t["id"]], destino="proyecto", proyecto_id=propio)["resultados"][0]
    assert r["ok"] is False and "mismo elemento" in r["error"]
    poste_en(con, propio, "PT-2", LAT + 0.0010, LON + 0.0004)
    bueno = enviar_trazo(con, g["juan"], hilos=None)
    with pytest.raises(db.SinPermiso):
        campo.aprobar_trazos(con, g["ana"], ids=[bueno["id"]], destino="proyecto", proyecto_id=propio)                  # not assigned
    ok = campo.aprobar_trazos(con, g["edu"], ids=[bueno["id"]], destino="proyecto", proyecto_id=propio)["resultados"][0]
    assert ok["ok"] and con.execute("SELECT hilos, origen_id FROM redes.cables WHERE id = %s", (ok["cable_id"],)).fetchone() == {"hilos": 12, "origen_id": uno}     # no fibres given: a 12-fibre cable
    with pytest.raises(db.DatosInvalidos, match="Elija el proyecto"):
        campo.aprobar_trazos(con, g["edu"], ids=[bueno["id"]], destino="proyecto")


def test_the_trace_methods_are_in_the_remote_list(mundo):
    for nombre in ("campo_trazos", "campo_editar_trazo", "campo_aprobar_trazos", "campo_rechazar_trazos"):
        assert nombre in METODOS


# ------------------------------------------------------------------ reference network

def test_the_reference_network_of_a_zone_is_light_and_limited(mundo, monkeypatch):
    con, g = mundo
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "red_lineas": True})          # the crews see no lines by default (test_campo_cuadrillas.py)
    base = crear_proyecto(con, "RB", base=True)
    otra = crear_proyecto(con, "PROY")                                           # a project that is not a base network is not reference
    a, b = poste_en(con, base, "PT-1", LAT, LON), poste_en(con, base, "MF-1", LAT + 0.001, LON, tipo="mufa")
    poste_en(con, otra, "PT-X", LAT, LON + 0.0001)
    poste_en(con, base, "LEJOS", LAT + 0.2, LON)
    con.execute("INSERT INTO redes.cables (proyecto_id, nombre, origen_id, destino_id, vertices, geom) VALUES (%s, 'Cable A', %s, %s, '[]'::jsonb, %s)",
                (base, a, b, f"SRID=4326;LINESTRING({LON} {LAT}, {LON} {LAT + 0.001})"))
    r = campo.red_referencia(con, g["juan"], oeste=LON - 0.01, sur=LAT - 0.01, este=LON + 0.01, norte=LAT + 0.01)
    assert {p["n"] for p in r["puntos"]} == {"PT-1", "MF-1"} and {p["t"] for p in r["puntos"]} == {"poste", "mufa"} and r["truncado"] is False
    assert r["lineas"][0]["n"] == "Cable A" and r["lineas"][0]["c"][0] == [pytest.approx(LAT), pytest.approx(LON)]
    assert set(r["puntos"][0]) == {"id", "n", "t", "lat", "lon"}
    with pytest.raises(db.DatosInvalidos, match="muy grande"):
        campo.red_referencia(con, g["juan"], oeste=LON - 1, sur=LAT - 0.01, este=LON + 1, norte=LAT + 0.01)
    with pytest.raises(db.DatosInvalidos):
        campo.red_referencia(con, g["juan"], oeste=LON, sur=LAT, este=LON - 0.01, norte=LAT + 0.01)
    with pytest.raises(db.DatosInvalidos):
        campo.red_referencia(con, g["juan"], oeste=-120, sur=LAT, este=LON, norte=LAT + 0.01)
    with pytest.raises(db.SinPermiso):
        campo.red_referencia(con, g["lola"], oeste=LON - 0.01, sur=LAT - 0.01, este=LON + 0.01, norte=LAT + 0.01)


# ------------------------------------------------------------------ REST

@pytest.fixture
def api(base_redes, con_redes, entorno, monkeypatch):
    from visor_rutas.redes import usuarios
    from test_campo import _servicio
    main_, visor_api, cliente, _, _ = entorno
    for nombre, rol in (("jan", "tecnico"), ("maria", "tecnico")):
        u = usuarios.identificar(con_redes, persona_visor=nombre)
        con_redes.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
    servicio = _servicio(base_redes)
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    import visor_rutas.campo_api as campo_api
    campo_api.limitador.reiniciar()
    yield cliente, con_redes
    servicio.cerrar()


def test_the_rest_api_of_the_traces(api):
    c, con = api
    t = trazo()
    assert c.post("/visor/campo/trazos", json={"trazos": [t]}).status_code == 401
    r = c.post("/visor/campo/trazos", json={"trazos": [t]}, headers=JAN)
    assert r.status_code == 200 and r.json()["resultados"][0]["trazo"]["usuario"] == "jan"
    assert c.post("/visor/campo/trazos", json={"trazos": [t]}, headers=JAN).json()["resultados"][0]["repetido"] is True
    assert c.post("/visor/campo/trazos", json={"trazos": []}, headers=JAN).status_code == 422
    malo = c.post("/visor/campo/trazos", json={"trazos": [trazo(hilos=13)]}, headers=JAN).json()["resultados"][0]
    assert malo["ok"] is False and "hilos" in malo["errores"]
    id_, version = r.json()["resultados"][0]["trazo"]["id"], r.json()["resultados"][0]["trazo"]["version"]
    assert c.get("/visor/campo/trazos", headers=MARIA).json()["trazos"] == []
    assert c.get("/visor/campo/trazos", headers=JAN).json()["trazos"][0]["id"] == id_
    assert c.patch(f"/visor/campo/trazos/{id_}", json={"version": version, "cambios": {"notas": "x"}}, headers=MARIA).status_code == 403
    assert c.patch(f"/visor/campo/trazos/{id_}", json={"version": version, "cambios": {"hilos": 48}}, headers=JAN).json()["trazo"]["hilos"] == 48
    assert c.patch(f"/visor/campo/trazos/{id_}", json={"version": version, "cambios": {"hilos": 12}}, headers=JAN).status_code == 409
    assert c.delete(f"/visor/campo/trazos/{id_}", headers=JAN).json() == {"ok": True, "id": id_}
    assert c.delete(f"/visor/campo/trazos/{id_}", headers=JAN).status_code == 404


def test_the_rest_api_of_the_reference_network(api, monkeypatch):
    c, con = api
    base = crear_proyecto(con, "RB", base=True)
    poste_en(con, base, "PT-1", LAT, LON)
    import db as presupuesto
    llamadas = []

    def falso(o, s, e, n, mp, ml, prefijos=None):
        llamadas.append((o, s, e, n, mp, ml))
        return {"puntos": [{"id": "k1", "n": "MF KMZ", "t": "mufa", "lat": LAT, "lon": LON + 0.0001}], "lineas": [{"id": "k2", "n": "FO", "t": "fibra", "c": [[LAT, LON], [LAT + 0.001, LON]]}], "truncado": False}
    monkeypatch.setattr(presupuesto, "find_red_en_bbox", falso)
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "red_lineas": True})          # with the lines on (by default the crews do not get them)
    caja = f"{LON - 0.005},{LAT - 0.005},{LON + 0.005},{LAT + 0.005}"
    assert c.get(f"/visor/campo/red?bbox={caja}").status_code == 401
    r = c.get(f"/visor/campo/red?bbox={caja}", headers=JAN).json()
    assert r["ok"] and {p["n"] for p in r["puntos"]} == {"MF KMZ", "PT-1"} and [x["id"] for x in r["lineas"]] == ["k2"] and r["aviso"] is None
    assert llamadas[0][4:] == (1500, 600) and r["zona"][0] == pytest.approx(LON - 0.005)
    for malo in ("1,2,3", "a,b,c,d", f"{LON - 1},{LAT},{LON + 1},{LAT + 0.01}", f"{LON},{LAT},{LON - 0.01},{LAT + 0.01}"):
        assert c.get(f"/visor/campo/red?bbox={malo}", headers=JAN).status_code == 422, malo
    # the budget database down: the network module's part still goes, with a notice
    monkeypatch.setattr(presupuesto, "find_red_en_bbox", lambda *a: (_ for _ in ()).throw(presupuesto.DatabaseError("sin base")))
    r = c.get(f"/visor/campo/red?bbox={caja}", headers=JAN).json()
    assert [p["n"] for p in r["puntos"]] == ["PT-1"] and "KMZ no está disponible" in r["aviso"]
