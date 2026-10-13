"""Network design module, phase 1: migrations of the `redes` schema, users (identification,
roles, administration, logical delete, history, optimistic locking), the local and remote
entry points, and that the budget API is unchanged."""
import json

import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_api import JAN, _api_remota, entorno  # noqa: F401  (fixture of the /visor/* API)
from visor_rutas.redes import db, migrar, usuarios
from visor_rutas.redes.api import METODOS, ServicioRedes


def _servicio(base_redes):
    _, params = base_redes
    return ServicioRedes(conectar=lambda: db.conectar(params=params))


# --------------------------------------------------------------------------- migraciones

def test_migrations_create_the_schema_with_postgis_once(con_redes):
    tablas = {f["table_name"] for f in con_redes.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'redes'").fetchall()}
    assert {"migraciones", "usuarios", "proyectos", "proyecto_usuarios", "historial"} <= tablas
    assert con_redes.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'").fetchone()
    assert 1 in migrar.aplicadas(con_redes)
    assert migrar.aplicar(con_redes) == []                                # already applied: nothing to do
    assert con_redes.execute("SELECT to_regclass('red_fibra.nodos') AS t").fetchone()["t"] is None   # other schemas untouched


def test_migration_files_are_numbered_and_unique():
    versiones = [m.version for m in migrar.disponibles()]
    assert versiones == sorted(set(versiones)) and versiones[0] == 1


# --------------------------------------------------------------------------- identificación

def test_first_windows_user_is_admin_then_readers_and_remote_never_admin(con_redes):
    remoto = usuarios.identificar(con_redes, persona_visor="marlon")
    assert remoto["rol"] == "lector"                                       # a key never becomes the first admin
    jan = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    assert jan["rol"] == "administrador"
    otro = usuarios.identificar(con_redes, usuario_windows="OTRA")
    assert otro["rol"] == "lector"
    assert usuarios.identificar(con_redes, usuario_windows="JGUTIERREZ")["id"] == jan["id"]   # case-insensitive
    acciones = [f["accion"] for f in con_redes.execute("SELECT accion FROM redes.historial").fetchall()]
    assert acciones.count("identificar") == 3
    with pytest.raises(db.SinPermiso):
        usuarios.identificar(con_redes)


# --------------------------------------------------------------------------- administración

def test_admin_creates_and_edits_users_with_validation_history_and_versions(con_redes):
    jan = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    lector = usuarios.identificar(con_redes, persona_visor="marlon")
    with pytest.raises(db.SinPermiso):
        usuarios.guardar(con_redes, lector, datos={"nombre": "X"})
    with pytest.raises(db.DatosInvalidos) as error:
        usuarios.guardar(con_redes, jan, datos={"nombre": " ", "correo": "malo", "rol": "jefe", "persona_visor": "con espacio"})
    assert set(error.value.errores) == {"nombre", "correo", "rol", "persona_visor"}

    nuevo = usuarios.guardar(con_redes, jan, datos={"nombre": "Ana  Pérez", "correo": "ana@ideay.net", "rol": "editor",
                                                    "persona_visor": "ana"})["usuario"]
    assert (nuevo["nombre"], nuevo["rol"], nuevo["version"], nuevo["activo"]) == ("Ana Pérez", "editor", 1, True)
    with pytest.raises(db.DatosInvalidos) as error:
        usuarios.guardar(con_redes, jan, datos={"nombre": "Otra", "correo": "ANA@ideay.net", "persona_visor": "MARLON"})
    assert set(error.value.errores) == {"correo", "persona_visor"}

    editado = usuarios.guardar(con_redes, jan, datos={**nuevo, "rol": "lector"})["usuario"]
    assert (editado["rol"], editado["version"]) == ("lector", 2)
    with pytest.raises(db.ConflictoVersion):                                # someone saved since version 1
        usuarios.guardar(con_redes, jan, datos={**nuevo, "rol": "administrador"})
    cambios = usuarios.historial(con_redes, jan, id=nuevo["id"])["historial"]
    assert [c["accion"] for c in cambios] == ["editar", "crear"]
    assert cambios[0]["cambio"] == {"rol": ["editor", "lector"]} and cambios[0]["usuario"] == "jgutierrez"


def test_deactivate_is_recoverable_and_there_is_always_an_admin(con_redes):
    jan = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    marlon = usuarios.identificar(con_redes, persona_visor="marlon")
    with pytest.raises(db.DatosInvalidos):
        usuarios.cambiar_estado(con_redes, jan, id=jan["id"], version=jan["version"], activo=False)
    with pytest.raises(db.DatosInvalidos):
        usuarios.guardar(con_redes, jan, datos={**usuarios.publico(jan), "rol": "editor"})      # last admin
    baja = usuarios.cambiar_estado(con_redes, jan, id=marlon["id"], version=marlon["version"], activo=False)["usuario"]
    assert baja["activo"] is False
    with pytest.raises(db.SinPermiso, match="desactivado"):
        usuarios.identificar(con_redes, persona_visor="marlon")
    assert len(usuarios.listar(con_redes, jan)["usuarios"]) == 2           # still there: logical delete
    alta = usuarios.cambiar_estado(con_redes, jan, id=marlon["id"], version=baja["version"], activo=True)["usuario"]
    assert alta["activo"] is True and usuarios.identificar(con_redes, persona_visor="marlon")["id"] == marlon["id"]


# --------------------------------------------------------------------------- puertas de entrada

def test_service_answers_ok_or_clear_errors(base_redes, con_redes):
    servicio = _servicio(base_redes)
    try:
        estado = servicio.llamar("estado", usuario_windows="jgutierrez")
        assert estado["ok"] and estado["usuario"]["rol"] == "administrador" and estado["puede"]["administrar"]
        assert estado["postgis"] and 1 in estado["migraciones"]
        json.dumps(ventana_json(estado))
        assert servicio.llamar("borrar_todo", usuario_windows="jgutierrez") == {"ok": False, "error": "Operación desconocida: borrar_todo"}
        assert "Datos no válidos" in servicio.llamar("usuarios", {"inventado": 1}, usuario_windows="jgutierrez")["error"]
        r = servicio.llamar("guardar_usuario", {"datos": {"nombre": ""}}, usuario_windows="jgutierrez")
        assert r["ok"] is False and r["errores"] == {"nombre": "Campo obligatorio"}
        lector = servicio.llamar("guardar_usuario", {"datos": {"nombre": "X"}}, persona_visor="marlon")
        assert lector == {"ok": False, "error": "Solo un administrador puede hacer esto"}
        u = servicio.llamar("guardar_usuario", {"datos": {"nombre": "Ana"}}, usuario_windows="jgutierrez")["usuario"]
        servicio.llamar("guardar_usuario", {"datos": {**u, "nombre": "Ana B"}}, usuario_windows="jgutierrez")
        conflicto = servicio.llamar("guardar_usuario", {"datos": {**u, "nombre": "Ana C"}}, usuario_windows="jgutierrez")
        assert conflicto["conflicto"] is True and "Recargue" in conflicto["error"]
    finally:
        servicio.cerrar()
    assert set(METODOS) >= {"estado", "usuarios", "guardar_usuario", "estado_usuario", "historial_usuario"}


def ventana_json(valor):
    from visor_rutas.ventana_web import a_json
    return a_json(valor)


def test_unreachable_database_is_a_clear_message():
    servicio = ServicioRedes(conectar=lambda: db.conectar(params={"host": "127.0.0.1", "port": 1, "dbname": "x",
                                                                  "user": "x", "password": "x"}))
    r = servicio.llamar("estado", usuario_windows="x")
    assert r["ok"] is False and "No se pudo conectar con la base de redes" in r["error"]


def test_local_api_and_remote_endpoint_identify_the_right_person(base_redes, con_redes, entorno, monkeypatch, tmp_path):
    main, visor_api, cliente, _, _ = entorno
    servicio = _servicio(base_redes)
    try:
        monkeypatch.setattr(visor_api, "_servicio_redes", servicio)
        assert cliente.post("/visor/redes/estado", json={"args": {}}).status_code == 401
        r = cliente.post("/visor/redes/estado", json={"args": {}}, headers=JAN).json()
        assert r["ok"] and r["usuario"]["persona_visor"] == "jan" and r["usuario"]["rol"] == "lector"
        assert cliente.post("/visor/redes/Borrar", json={}, headers=JAN).status_code == 422
        # the client cannot pretend to be someone else: identity only from the key
        r = cliente.post("/visor/redes/estado", json={"args": {"usuario_windows": "jgutierrez"}}, headers=JAN).json()
        assert r["ok"] is False
        remota = _api_remota(main, tmp_path)
        assert remota.redes("estado", {})["usuario"]["persona_visor"] == "jan"
        assert remota.redes("x-y", {})["ok"] is False

        from visor_rutas import ventana_web
        local = ventana_web.Api()
        monkeypatch.setattr(local, "_redes", servicio)
        monkeypatch.setattr("getpass.getuser", lambda: "jgutierrez")
        assert local.redes("estado")["usuario"]["usuario_windows"] == "jgutierrez"
    finally:
        servicio.cerrar()


def test_preferences_are_saved_per_pc(monkeypatch, tmp_path):
    from visor_rutas import ventana_web
    monkeypatch.setenv("APPDATA", str(tmp_path))
    api = ventana_web.Api()
    assert api.preferencias() == {"ok": True, "preferencias": {}}
    assert api.guardar_preferencias({"menu_contraido": True})["ok"]
    assert api.guardar_preferencias({"otra": 1})["ok"]
    assert api.preferencias()["preferencias"] == {"menu_contraido": True, "otra": 1}
    assert api.guardar_preferencias("no")["ok"] is False


def test_budget_api_is_unchanged_by_the_module(entorno):
    main = entorno[0]
    rutas = {(r.path, tuple(sorted(r.methods or []))) for r in main.app.routes if hasattr(r, "methods")}
    assert ("/presupuesto", ("POST",)) in rutas and ("/visor/redes/{metodo}", ("POST",)) in rutas
    assert not any(p.startswith("/redes") for p, _ in rutas)               # only under /visor/redes
    assert "visor_rutas.redes" not in open(main.__file__, encoding="utf-8").read()
