"""App de campo, fase 1 (visor_rutas/redes/campo.py, visor_rutas/campo_api.py, migración 017): jornadas, puntos idempotentes, permisos del técnico, fotos,
duplicados, NOTIFY y la API REST con la X-Visor-Key."""
import io
import json
import select
import uuid
from datetime import datetime, timedelta, timezone

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_base import _servicio
from test_visor_api import JAN, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import campo, db, usuarios

LAT, LON = 12.1364, -86.2514
MARIA = {"X-Visor-Key": "clave-maria"}


def punto(**cambios):
    return {"uuid_cliente": str(uuid.uuid4()), "tipo": "poste", "subtipo": "concreto", "nombre": "Poste 1", "lat": LAT, "lon": LON, "precision_m": 4.2,
            "origen_coord": "gps", "capturado_en": datetime.now(timezone.utc).isoformat(), **cambios}


def jpeg(ancho=800, alto=600):
    from PIL import Image
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), (200, 120, 40)).save(salida, "JPEG")
    return salida.getvalue()


@pytest.fixture(autouse=True)
def _fotos_en_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPO_FOTOS_DIR", str(tmp_path / "fotos"))


@pytest.fixture
def mundo(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    gente = {}
    for nombre, rol in (("juan", "tecnico"), ("pedro", "tecnico"), ("edu", "editor"), ("lola", "lector")):
        u = usuarios.identificar(con, persona_visor=nombre)
        con.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
        gente[nombre] = usuarios.identificar(con, persona_visor=nombre)
    return con, admin, gente


def test_a_point_sent_twice_is_one_point(mundo):
    con, _, g = mundo
    p = punto()
    r1 = campo.guardar_puntos(con, g["juan"], puntos=[p])["resultados"][0]
    r2 = campo.guardar_puntos(con, g["juan"], puntos=[p, dict(p)])["resultados"]
    assert r1["ok"] and r1["repetido"] is False and r1["punto"]["estado"] == "pendiente" and r1["punto"]["lat"] == pytest.approx(LAT)
    assert [r["repetido"] for r in r2] == [True, True] and {r["punto"]["id"] for r in r2} == {r1["punto"]["id"]}
    assert con.execute("SELECT count(*) AS n FROM redes.campo_puntos").fetchone()["n"] == 1
    # somebody else cannot take over that identifier
    otro = campo.guardar_puntos(con, g["pedro"], puntos=[p])["resultados"][0]
    assert otro["ok"] is False and "otro técnico" in otro["error"]
    # the change is in the history
    assert con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad = 'campo_punto' AND accion = 'crear'").fetchone()["n"] == 1


def test_validation_per_point_and_nicaragua_only(mundo):
    con, _, g = mundo
    malos = [punto(lat=40.0), punto(lon=-100), punto(tipo="antena"), punto(tipo="poste", subtipo="plástico"), punto(tipo="mufa", subtipo="24"),
             punto(uuid_cliente="x"), punto(lat="abc"), punto(nombre="", tipo="reserva", subtipo=None)]
    bien = punto(tipo="mufa", subtipo="48 Domo", nombre="")
    r = campo.guardar_puntos(con, g["juan"], puntos=malos + [bien])["resultados"]
    assert [x["ok"] for x in r] == [False] * 7 + [True, True]
    assert r[0]["errores"].keys() == {"lat"} and r[2]["errores"].keys() == {"tipo"} and r[3]["errores"].keys() == {"subtipo"} and r[5]["errores"].keys() == {"uuid_cliente"}
    assert r[7]["punto"]["nombre"] == "Reserva"                      # no name: the kind
    assert r[8]["punto"]["subtipo"] == "48 domo" and r[8]["punto"]["nombre"] == "Mufa"
    with pytest.raises(db.DatosInvalidos):
        campo.guardar_puntos(con, g["juan"], puntos=[])
    with pytest.raises(db.DatosInvalidos):
        campo.guardar_puntos(con, g["juan"], puntos=[punto() for _ in range(51)])


def test_only_technicians_and_reviewers_use_the_field_app(mundo):
    con, admin, g = mundo
    with pytest.raises(db.SinPermiso, match="rol de técnico"):
        campo.guardar_puntos(con, g["lola"], puntos=[punto()])
    with pytest.raises(db.SinPermiso):
        campo.puntos(con, g["lola"])
    assert campo.abrir_jornada(con, admin)["nueva"] is True        # an administrator can also register


def test_a_technician_edits_only_his_own_pending_points(mundo):
    con, _, g = mundo
    p = campo.guardar_puntos(con, g["juan"], puntos=[punto()])["resultados"][0]["punto"]
    with pytest.raises(db.SinPermiso, match="otro técnico"):
        campo.editar_punto(con, g["pedro"], id=p["id"], version=p["version"], cambios={"nombre": "X"})
    with pytest.raises(db.SinPermiso):
        campo.borrar_punto(con, g["pedro"], id=p["id"])
    e = campo.editar_punto(con, g["juan"], id=p["id"], version=p["version"], cambios={"nombre": "Poste 7", "tipo": "reserva"})["punto"]
    assert e["nombre"] == "Poste 7" and e["tipo"] == "reserva" and e["subtipo"] is None and e["estado"] == "pendiente" and e["version"] == p["version"] + 1
    with pytest.raises(db.ConflictoVersion):
        campo.editar_punto(con, g["juan"], id=p["id"], version=p["version"], cambios={"nombre": "Otra vez"})
    with pytest.raises(db.DatosInvalidos):
        campo.editar_punto(con, g["juan"], id=p["id"], version=e["version"], cambios={"lat": 3})
    # a reviewer's correction leaves it «editado»
    c = campo.editar_punto(con, g["edu"], id=p["id"], version=e["version"], cambios={"notas": "revisado"})["punto"]
    assert c["estado"] == "editado" and c["notas"] == "revisado"
    # approved or rejected points are closed
    con.execute("UPDATE redes.campo_puntos SET estado = 'aprobado' WHERE id = %s", (p["id"],))
    with pytest.raises(db.SinPermiso, match="aprobado"):
        campo.editar_punto(con, g["juan"], id=p["id"], version=c["version"] + 1, cambios={"nombre": "Z"})
    with pytest.raises(db.SinPermiso):
        campo.borrar_punto(con, g["juan"], id=p["id"])
    q = campo.guardar_puntos(con, g["juan"], puntos=[punto()])["resultados"][0]["punto"]
    assert campo.borrar_punto(con, g["juan"], id=q["id"]) == {"id": q["id"]}
    with pytest.raises(db.NoEncontrado):
        campo.editar_punto(con, g["juan"], id=q["id"], version=1, cambios={"nombre": "x"})


def test_listing_by_role_state_jornada_and_changes_since(mundo):
    con, _, g = mundo
    j = campo.abrir_jornada(con, g["juan"], nombre="Barrio Sur")["jornada"]
    a = campo.guardar_puntos(con, g["juan"], puntos=[punto(nombre="A"), punto(nombre="B", tipo="mufa", subtipo="96")])["resultados"]
    campo.guardar_puntos(con, g["pedro"], puntos=[punto(nombre="C")])
    assert a[0]["punto"]["jornada_id"] == j["id"]                    # no jornada given: the open one
    assert {p["nombre"] for p in campo.puntos(con, g["juan"])["puntos"]} == {"A", "B"}      # a technician: only his
    todos = campo.puntos(con, g["edu"])
    assert {p["nombre"] for p in todos["puntos"]} == {"A", "B", "C"} and todos["puntos"][0]["usuario"] == "juan"
    assert {p["nombre"] for p in campo.puntos(con, g["edu"], jornada=j["id"])["puntos"]} == {"A", "B"}
    assert {p["nombre"] for p in campo.puntos(con, g["edu"], usuario_id=g["pedro"]["id"])["puntos"]} == {"C"}
    con.execute("UPDATE redes.campo_puntos SET estado = 'aprobado' WHERE nombre = 'A'")
    assert {p["nombre"] for p in campo.puntos(con, g["edu"], estado="aprobado")["puntos"]} == {"A"}
    with pytest.raises(db.DatosInvalidos):
        campo.puntos(con, g["edu"], estado="raro")
    # changes since: edit one and delete another; `desde` brings both, the deleted one flagged
    antes = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    b = a[1]["punto"]
    campo.editar_punto(con, g["juan"], id=b["id"], version=b["version"], cambios={"notas": "n"})
    cambios = campo.puntos(con, g["juan"], desde=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())
    assert {p["nombre"] for p in cambios["puntos"]} == {"A", "B"} and cambios["ahora"]
    assert campo.puntos(con, g["juan"], desde=antes)["puntos"] == []


def test_deleted_points_come_back_flagged_when_asking_for_changes(mundo):
    con, _, g = mundo
    p = campo.guardar_puntos(con, g["juan"], puntos=[punto()])["resultados"][0]["punto"]
    assert [x["id"] for x in campo.puntos(con, g["juan"])["puntos"]] == [p["id"]]
    campo.borrar_punto(con, g["juan"], id=p["id"])
    assert campo.puntos(con, g["juan"])["puntos"] == []             # a plain list hides it...
    ultimo = campo.puntos(con, g["juan"], desde=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())["puntos"]
    assert [(x["id"], x["borrado"]) for x in ultimo] == [(p["id"], True)]      # ...a sync tells the phone to drop it


def test_jornada_opens_once_and_closes(mundo):
    con, _, g = mundo
    j = campo.abrir_jornada(con, g["juan"], nombre="Día 1")
    assert j["nueva"] and j["jornada"]["nombre"] == "Día 1" and j["jornada"]["fin"] is None
    assert campo.abrir_jornada(con, g["juan"])["jornada"]["id"] == j["jornada"]["id"] and not campo.abrir_jornada(con, g["juan"])["nueva"]
    with pytest.raises(db.SinPermiso):
        campo.cerrar_jornada(con, g["pedro"], id=j["jornada"]["id"])
    assert campo.cerrar_jornada(con, g["juan"], id=j["jornada"]["id"])["jornada"]["fin"]
    assert campo.abrir_jornada(con, g["juan"])["nueva"] is True        # after closing, a new one
    assert len(campo.jornadas(con, g["juan"])["jornadas"]) == 2 and len(campo.jornadas(con, g["pedro"])["jornadas"]) == 0
    assert len(campo.jornadas(con, g["edu"])["jornadas"]) == 2         # reviewers see everybody's
    # a point cannot go in somebody else's jornada
    r = campo.guardar_puntos(con, g["pedro"], puntos=[punto(jornada_id=j["jornada"]["id"])])["resultados"][0]
    assert r["ok"] is False and "jornada_id" in r["errores"]


def test_a_point_near_something_that_exists_is_flagged_as_possible_duplicate(mundo):
    con, admin, g = mundo
    proy = con.execute("INSERT INTO redes.proyectos (codigo, nombre, es_red_base) VALUES ('RB', 'Red base', true) RETURNING id").fetchone()["id"]
    con.execute("INSERT INTO redes.elementos (proyecto_id, tipo, nombre, ubicacion) VALUES (%s, 'poste', 'PT-100', ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                (proy, LON, LAT))
    cerca = campo.guardar_puntos(con, g["juan"], puntos=[punto(lat=LAT + 0.00002)])["resultados"][0]        # ≈ 2 m
    lejos = campo.guardar_puntos(con, g["juan"], puntos=[punto(lat=LAT + 0.0005)])["resultados"][0]          # ≈ 55 m
    assert cerca["duplicado"]["origen"] == "red" and cerca["duplicado"]["nombre"] == "PT-100" and cerca["duplicado"]["distancia_m"] < 5
    assert lejos["duplicado"] is None
    # another field point of the same kind counts too (two technicians at the same pole)
    otro = campo.guardar_puntos(con, g["pedro"], puntos=[punto(lat=LAT + 0.0005, lon=LON + 0.00002)])["resultados"][0]
    assert otro["duplicado"]["origen"] == "campo"
    # both are saved: it is only a warning
    assert cerca["ok"] and otro["ok"]


def test_every_change_notifies_the_campo_channel(mundo, base_redes):
    con, _, g = mundo
    _, params = base_redes
    oyente = db.conectar(params=params)
    try:
        oyente.execute("LISTEN campo")
        p = campo.guardar_puntos(con, g["juan"], puntos=[punto()])["resultados"][0]["punto"]
        campo.editar_punto(con, g["juan"], id=p["id"], version=p["version"], cambios={"notas": "x"})
        avisos = [json.loads(n.payload) for n in oyente.notifies(timeout=2, stop_after=2)]
        assert [a["cambio"] for a in avisos] == ["insert", "update"]
        assert avisos[0] == {"tabla": "campo_puntos", "id": str(p["id"]), "cambio": "insert", "usuario_id": str(g["juan"]["id"])}
    finally:
        oyente.close()


def test_photos_are_stored_once_checked_and_only_shown_to_their_owner(mundo, monkeypatch):
    con, _, g = mundo
    p = campo.guardar_puntos(con, g["juan"], puntos=[punto()])["resultados"][0]["punto"]
    foto = jpeg()
    r = campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=foto, uuid_cliente="f0f0-0001-abcdef")
    assert r["repetida"] is False and r["foto"]["tipo"] == "image/jpeg"
    assert campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=foto, uuid_cliente="f0f0-0001-abcdef")["repetida"] is True
    assert campo.foto(con, g["juan"], id=r["foto"]["id"])["datos"] == foto
    mini = campo.foto(con, g["edu"], id=r["foto"]["id"], miniatura=True)["datos"]
    assert 0 < len(mini) < len(foto) and mini[:3] == b"\xff\xd8\xff"
    with pytest.raises(db.SinPermiso):
        campo.foto(con, g["pedro"], id=r["foto"]["id"])
    with pytest.raises(db.SinPermiso):
        campo.subir_foto(con, g["pedro"], punto_id=p["id"], datos=foto)
    assert campo.puntos(con, g["juan"])["puntos"][0]["fotos"] == [{"id": r["foto"]["id"], "tipo": "image/jpeg", "tamano": len(foto)}]
    for malo, texto in ((b"", "vacía"), (b"GIF89a....", "JPEG, PNG o WebP"), (b"%PDF-1.4 hola", "JPEG, PNG o WebP")):
        with pytest.raises(db.DatosInvalidos, match=texto):
            campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=malo)
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "foto_max_bytes": 1000})
    with pytest.raises(db.DatosInvalidos, match="máximo"):
        campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=foto)
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "fotos_por_punto": 1})
    with pytest.raises(db.DatosInvalidos, match="hasta 1"):
        campo.subir_foto(con, g["juan"], punto_id=p["id"], datos=jpeg(100, 100))


# ------------------------------------------------------------------ the REST API

@pytest.fixture
def api(base_redes, con_redes, entorno, monkeypatch):
    main, visor_api, cliente, _, _ = entorno
    con = con_redes
    for nombre, rol in (("jan", "tecnico"), ("maria", "tecnico")):
        u = usuarios.identificar(con, persona_visor=nombre)
        con.execute("UPDATE redes.usuarios SET rol = %s WHERE id = %s", (rol, u["id"]))
    servicio = _servicio(base_redes)
    monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
    import visor_rutas.campo_api as campo_api
    campo_api.limitador.reiniciar()
    yield cliente, con
    servicio.cerrar()


def test_the_rest_api_needs_the_key_and_answers_with_the_right_codes(api):
    c, con = api
    assert c.post("/visor/campo/puntos", json={"puntos": [punto()]}).status_code == 401
    assert c.get("/visor/campo/puntos", headers={"X-Visor-Key": "mala"}).status_code == 401
    p = punto()
    r = c.post("/visor/campo/puntos", json={"puntos": [p]}, headers=JAN)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["resultados"][0]["punto"]["usuario"] == "jan"
    assert c.post("/visor/campo/puntos", json={"puntos": [p]}, headers=JAN).json()["resultados"][0]["repetido"] is True
    assert c.post("/visor/campo/puntos", json={"puntos": []}, headers=JAN).status_code == 422
    id_ = r.json()["resultados"][0]["punto"]["id"]
    version = r.json()["resultados"][0]["punto"]["version"]
    # maria cannot touch jan's point (403), and sees none of them
    assert c.patch(f"/visor/campo/puntos/{id_}", json={"version": version, "cambios": {"nombre": "x"}}, headers=MARIA).status_code == 403
    assert c.get("/visor/campo/puntos", headers=MARIA).json()["puntos"] == []
    e = c.patch(f"/visor/campo/puntos/{id_}", json={"version": version, "cambios": {"nombre": "Poste B"}}, headers=JAN)
    assert e.status_code == 200 and e.json()["punto"]["nombre"] == "Poste B"
    assert c.patch(f"/visor/campo/puntos/{id_}", json={"version": version, "cambios": {"nombre": "Otra"}}, headers=JAN).status_code == 409
    bad = c.patch(f"/visor/campo/puntos/{id_}", json={"version": version + 1, "cambios": {"lat": 1}}, headers=JAN)
    assert bad.status_code == 422 and "lat" in bad.json()["errores"] and bad.json()["ok"] is False
    assert c.delete(f"/visor/campo/puntos/{id_}", headers=JAN).json() == {"ok": True, "id": id_}
    assert c.delete(f"/visor/campo/puntos/{id_}", headers=JAN).status_code == 404
    # a reader is refused
    con.execute("UPDATE redes.usuarios SET rol = 'lector' WHERE persona_visor = 'maria'")
    assert c.get("/visor/campo/puntos", headers=MARIA).status_code == 403


def test_the_rest_api_jornadas_and_photos(api, monkeypatch):
    c, _ = api
    j = c.post("/visor/campo/jornadas", json={"accion": "abrir", "nombre": "Hoy"}, headers=JAN).json()
    assert j["nueva"] and c.post("/visor/campo/jornadas", json={"accion": "abrir"}, headers=JAN).json()["nueva"] is False
    assert c.post("/visor/campo/jornadas", json={"accion": "cerrar"}, headers=JAN).status_code == 422
    assert c.post("/visor/campo/jornadas", json={"accion": "borrar"}, headers=JAN).status_code == 422
    p = c.post("/visor/campo/puntos", json={"puntos": [punto()]}, headers=JAN).json()["resultados"][0]["punto"]
    assert p["jornada_id"] == j["jornada"]["id"]
    foto = jpeg()
    r = c.post(f"/visor/campo/fotos?punto_id={p['id']}&uuid_cliente=aaaaaaaa-1111", content=foto, headers={**JAN, "Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["foto"]["tamano"] == len(foto)
    assert c.get(f"/visor/campo/foto/{r.json()['foto']['id']}", headers=JAN).content == foto
    assert c.get(f"/visor/campo/foto/{r.json()['foto']['id']}?miniatura=true", headers=JAN).headers["content-type"] == "image/jpeg"
    assert c.get(f"/visor/campo/foto/{r.json()['foto']['id']}", headers=MARIA).status_code == 403
    assert c.post(f"/visor/campo/fotos?punto_id={p['id']}", content=b"no es una foto", headers=JAN).status_code == 422
    assert c.post("/visor/campo/fotos?punto_id=99999", content=foto, headers=JAN).status_code == 404
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "foto_max_bytes": 2000})
    assert c.post(f"/visor/campo/fotos?punto_id={p['id']}", content=foto, headers=JAN).status_code == 413
    assert c.post(f"/visor/campo/jornadas", json={"accion": "cerrar", "id": j["jornada"]["id"]}, headers=JAN).json()["jornada"]["fin"]


def test_a_technician_has_a_request_limit(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(campo, "configuracion", lambda: {**campo.POR_DEFECTO, "peticiones_por_hora": 3})
    codigos = [c.get("/visor/campo/jornadas", headers=JAN).status_code for _ in range(5)]
    assert codigos == [200, 200, 200, 429, 429]
    assert c.get("/visor/campo/jornadas", headers=MARIA).status_code == 200      # per person
