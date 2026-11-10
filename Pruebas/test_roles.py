"""Roles de usuarios: super_administrador, administrador, guest y prueba.

- El super administrador es el único que gestiona a los administradores; un administrador gestiona al resto.
- guest: el mapa, las rutas y los presupuestos; nada más (ni redes, ni tickets, ni campo, ni usuarios).
- prueba: solo lectura en todo (más calcular rutas y presupuestos).
Base desechable (redes_base) para el módulo; las rutas del servicio se prueban con el rol simulado.
"""
import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
import visor_api
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_api import JAN, entorno  # noqa: F401  (fixture)
from visor_rutas.redes import db, usuarios
from visor_rutas.redes.api import METODOS, PERMITIDOS_GUEST, SOLO_LECTURA, ServicioRedes
from visor_rutas.redes.db import DatosInvalidos, SinPermiso


def _crear(con, nombre, rol, persona=None):
    fila = con.execute("INSERT INTO redes.usuarios (nombre, rol, persona_visor) VALUES (%s, %s, %s) RETURNING *", (nombre, rol, persona or nombre)).fetchone()
    return dict(fila)


@pytest.fixture
def equipo(con_redes):
    con = con_redes
    return con, {n: _crear(con, n, r) for n, r in (("jan", "super_administrador"), ("marlon", "administrador"), ("javier", "administrador"), ("ana", "editor"), ("guest", "guest"), ("prueba", "prueba"))}


def _datos(nombre, rol, **extra):
    return {"nombre": nombre, "rol": rol, "persona_visor": nombre, **extra}


# --------------------------------------------------------------------------- who manages whom

def test_the_super_administrator_is_an_administrator_and_the_only_one_who_manages_administrators(equipo):
    con, u = equipo
    assert usuarios.es_admin(u["jan"]) and usuarios.es_super(u["jan"]) and usuarios.es_admin(u["marlon"]) and not usuarios.es_super(u["marlon"])
    assert usuarios.puede_editar(u["jan"]) and usuarios.puede_editar(u["marlon"]) and not usuarios.puede_editar(u["guest"]) and not usuarios.puede_editar(u["prueba"])
    # the super administrator creates an administrator and changes his role
    nuevo = usuarios.guardar(con, u["jan"], datos=_datos("pedro", "administrador"))["usuario"]
    assert nuevo["rol"] == "administrador"
    # an administrator does not touch administrators: not create, not change, not deactivate, not even the super one
    with pytest.raises(SinPermiso, match="super administrador"):
        usuarios.guardar(con, u["marlon"], datos=_datos("otro", "administrador"))
    with pytest.raises(SinPermiso, match="super administrador"):
        usuarios.guardar(con, u["marlon"], datos={**_datos("javier", "lector"), "id": u["javier"]["id"], "version": u["javier"]["version"]})
    with pytest.raises(SinPermiso, match="super administrador"):
        usuarios.cambiar_estado(con, u["marlon"], id=u["javier"]["id"], version=u["javier"]["version"], activo=False)
    with pytest.raises(SinPermiso, match="super administrador"):
        usuarios.cambiar_estado(con, u["marlon"], id=u["jan"]["id"], version=u["jan"]["version"], activo=False)
    with pytest.raises(SinPermiso, match="super administrador"):
        usuarios.guardar(con, u["marlon"], datos={**_datos("ana", "super_administrador"), "id": u["ana"]["id"], "version": u["ana"]["version"]})      # nor makes anyone one
    # ...but the administrator does manage the rest: guest, prueba, editors, readers
    creado = usuarios.guardar(con, u["marlon"], datos=_datos("luis", "guest"))["usuario"]
    assert creado["rol"] == "guest"
    cambiado = usuarios.guardar(con, u["marlon"], datos={**_datos("ana", "lector"), "id": u["ana"]["id"], "version": u["ana"]["version"]})["usuario"]
    assert cambiado["rol"] == "lector"
    assert usuarios.cambiar_estado(con, u["marlon"], id=creado["id"], version=creado["version"], activo=False)["usuario"]["activo"] is False
    # guest and prueba cannot manage anyone
    for rol in ("guest", "prueba"):
        with pytest.raises(SinPermiso):
            usuarios.guardar(con, u[rol], datos=_datos("x", "lector"))


def test_there_is_always_one_super_administrator_and_one_administrator_left(equipo):
    con, u = equipo
    with pytest.raises(DatosInvalidos, match="super administrador"):
        usuarios.guardar(con, u["jan"], datos={**_datos("jan", "administrador"), "id": u["jan"]["id"], "version": u["jan"]["version"]})              # the only super one cannot be lowered
    with pytest.raises(DatosInvalidos):
        usuarios.cambiar_estado(con, u["jan"], id=u["jan"]["id"], version=u["jan"]["version"], activo=False)                                         # nor deactivate himself
    # a second super administrator can be made, and then the first one can step down
    otro = usuarios.guardar(con, u["jan"], datos=_datos("sara", "super_administrador"))["usuario"]
    bajado = usuarios.guardar(con, otro, datos={**_datos("jan", "administrador"), "id": u["jan"]["id"], "version": u["jan"]["version"]})["usuario"]
    assert bajado["rol"] == "administrador"
    assert usuarios.listar(con, otro)["es_super"] is True and usuarios.listar(con, u["marlon"])["es_super"] is False


def test_without_a_super_administrator_the_administrators_keep_their_old_power(con_redes):
    con = con_redes
    admin = _crear(con, "marlon", "administrador")
    nuevo = usuarios.guardar(con, admin, datos=_datos("javier", "administrador"))["usuario"]                  # a fresh installation: nobody is locked out
    assert nuevo["rol"] == "administrador"


# --------------------------------------------------------------------------- the network module: guest and prueba

def _servicio(base_redes):
    _, params = base_redes
    return ServicioRedes(conectar=lambda: db.conectar(params=params))


def test_guest_only_has_who_it_is_and_what_the_map_reads_and_prueba_only_reads(con_redes, base_redes):
    con = con_redes
    for n, r in (("guest", "guest"), ("prueba", "prueba"), ("ana", "editor"), ("jan", "super_administrador")):
        _crear(con, n, r)
    s = _servicio(base_redes)
    assert s.llamar("estado", persona_visor="guest")["ok"] and s.llamar("estado", persona_visor="guest")["usuario"]["rol"] == "guest"
    for metodo in ("proyectos", "usuarios", "lugares", "guardar_lugar", "guardar_usuario", "problemas", "campo_puntos", "crear_respaldo", "tablero_migracion"):
        r = s.llamar(metodo, persona_visor="guest")
        assert r["ok"] is False and "guest" in r["error"], metodo                                         # the network module is closed to a guest
    assert s.llamar("buscar_elementos", {"texto": "x"}, persona_visor="guest")["ok"]                      # the search box of the map is not
    # prueba reads everything and writes nothing
    assert s.llamar("proyectos", persona_visor="prueba")["ok"] and s.llamar("usuarios", persona_visor="prueba")["ok"] and s.llamar("lugares", persona_visor="prueba")["ok"]
    for metodo in ("guardar_usuario", "guardar_proyecto", "guardar_lugar", "eliminar_lugar", "crear_respaldo", "guardar_mufa", "editar_kmz", "visio_actualizar", "restaurar_respaldo"):
        r = s.llamar(metodo, {}, persona_visor="prueba")
        assert r["ok"] is False and "solo lectura" in r["error"], metodo
    # the others are not limited by these lists
    assert s.llamar("proyectos", persona_visor="ana")["ok"] and s.llamar("usuarios", persona_visor="jan")["ok"]
    r = s.llamar("guardar_usuario", {"datos": {"nombre": "luis", "rol": "guest", "persona_visor": "luis"}}, persona_visor="jan")
    assert r["ok"] and r["usuario"]["rol"] == "guest"


def test_the_lists_only_name_methods_that_exist_and_prueba_reads_what_it_names():
    assert PERMITIDOS_GUEST <= set(METODOS) and SOLO_LECTURA <= set(METODOS)
    escrituras = {m for m in METODOS if m.startswith(("guardar_", "eliminar_", "crear_", "restaurar_", "duplicar_", "mover_", "aceptar_", "aplicar_", "revertir_", "descartar_", "publicar_",
                                                      "incorporar_", "importar_", "subir_", "quitar_", "confirmar_", "deshacer_", "renombrar_", "sincronizar_", "estado_usuario", "asignar_",
                                                      "configurar_", "validar_", "visio_actualizar", "visio_subir", "editar_kmz", "borrar_kmz", "campo_editar", "campo_aprobar", "campo_rechazar", "plan_llevar"))}
    assert not (escrituras & SOLO_LECTURA), sorted(escrituras & SOLO_LECTURA)                             # nothing that writes is in the read only list
    assert not (escrituras & PERMITIDOS_GUEST), sorted(escrituras & PERMITIDOS_GUEST)


# --------------------------------------------------------------------------- the endpoints of the service

@pytest.mark.parametrize("metodo,ruta,guest,prueba", [
    ("GET", "/visor/info", True, True), ("GET", "/visor/red/postes", True, True), ("GET", "/visor/kmz/arbol", True, True), ("GET", "/visor/mufa/12", True, True),
    ("GET", "/visor/diagramas/buscar", True, True), ("GET", "/visor/presupuestos", True, True), ("GET", "/visor/archivo/x.xlsx", True, True), ("GET", "/visor/actualizacion", True, True),
    ("POST", "/visor/ruta", True, True), ("POST", "/visor/ruta_editada", True, True), ("POST", "/visor/estimacion", True, True), ("POST", "/visor/medicion", True, True),
    ("POST", "/visor/presupuesto", True, True), ("POST", "/visor/masivas/leer", True, True), ("POST", "/visor/masivas/iniciar", True, True), ("POST", "/visor/redes/estado", True, True),
    ("GET", "/visor/tickets", False, True), ("GET", "/visor/tickets/carpeta/instalaciones", False, True), ("GET", "/visor/tickets/55/historial", False, True),
    ("POST", "/visor/fusion/exportar", False, False), ("POST", "/visor/fusion/redactar", False, True), ("POST", "/visor/otra_cosa", False, False), ("DELETE", "/visor/presupuestos/x", False, False),
])
def test_what_guest_and_prueba_may_call_in_the_service(metodo, ruta, guest, prueba):
    assert visor_api.permitido("guest", metodo, ruta) is guest, ("guest", metodo, ruta)
    assert visor_api.permitido("prueba", metodo, ruta) is prueba, ("prueba", metodo, ruta)
    for rol in ("super_administrador", "administrador", "editor", "lector", None):
        assert visor_api.permitido(rol, metodo, ruta) is True                                              # the others are decided by the network module and each function


def test_the_service_refuses_what_the_role_does_not_allow_and_a_deactivated_user(entorno, monkeypatch):
    _, _, cliente, _, _ = entorno
    roles = {"jan": "guest"}
    monkeypatch.setattr(visor_api, "rol_de_persona", lambda persona: roles.get(persona))
    assert cliente.get("/visor/info", headers=JAN).status_code == 200                                      # guest: the map
    r = cliente.get("/visor/tickets", headers=JAN)
    assert r.status_code == 403 and "guest" in r.json()["detail"]                                          # guest: no tickets
    assert cliente.post("/visor/fusion/exportar", json={}, headers=JAN).status_code == 403
    roles["jan"] = "prueba"
    assert cliente.get("/visor/info", headers=JAN).status_code == 200
    assert cliente.post("/visor/fusion/exportar", json={}, headers=JAN).status_code == 403 and "prueba" in cliente.post("/visor/fusion/exportar", json={}, headers=JAN).json()["detail"]
    roles["jan"] = "administrador"
    assert cliente.get("/visor/info", headers=JAN).status_code == 200


def test_the_role_is_asked_to_the_database_cached_and_forgotten_when_a_role_changes(monkeypatch):
    llamadas = []

    class Falso:
        def rol_de(self, persona_visor):
            llamadas.append(persona_visor)
            return "guest"

    monkeypatch.setattr(visor_api, "servicio_redes", lambda: Falso())
    visor_api.olvidar_roles()
    assert visor_api.rol_de_persona("guest") == "guest" and visor_api.rol_de_persona("guest") == "guest" and llamadas == ["guest"]       # the second one is from memory
    visor_api.olvidar_roles()
    assert visor_api.rol_de_persona("guest") == "guest" and len(llamadas) == 2
    # a deactivated user is refused; the database that does not answer is a 503 (or the last answer if there is one); without the module nothing is limited
    from fastapi import HTTPException

    class Roto:
        def rol_de(self, persona_visor):
            raise db.SinPermiso("El usuario guest está desactivado")

    monkeypatch.setattr(visor_api, "servicio_redes", lambda: Roto())
    visor_api.olvidar_roles()
    with pytest.raises(HTTPException) as e:
        visor_api.rol_de_persona("guest")
    assert e.value.status_code == 403

    class Caida:
        def rol_de(self, persona_visor):
            raise ConnectionError("sin base")

    monkeypatch.setattr(visor_api, "servicio_redes", lambda: Caida())
    visor_api.olvidar_roles()
    with pytest.raises(HTTPException) as e:
        visor_api.rol_de_persona("otro")
    assert e.value.status_code == 503

    class SinModulo:
        def rol_de(self, persona_visor):
            raise db.RedesNoDisponible("VISIO_DB_NAME vacío")

    monkeypatch.setattr(visor_api, "servicio_redes", lambda: SinModulo())
    visor_api.olvidar_roles()
    assert visor_api.rol_de_persona("jan") is None
    visor_api.olvidar_roles()


# --------------------------------------------------------------------------- the script that sets the users

def test_the_script_sets_the_roles_creates_guest_and_prueba_and_deactivates_the_others(con_redes):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "herramientas"))
    import configurar_usuarios
    con = con_redes
    for n, r, p in (("jparamo", "administrador", None), ("jan", "tecnico", "jan"), ("marlon", "administrador", "marlon"), ("janPlanificacion", "administrador", "janPlanificacion"), ("javier", "editor", "javier")):
        con.execute("INSERT INTO redes.usuarios (nombre, rol, persona_visor) VALUES (%s, %s, %s)", (n, r, p))
    plan = configurar_usuarios.construir_plan(con, desactivar_otros=True)
    assert [(a, p) for a, p, _ in plan] == [("cambiar", "jan"), ("igual", "marlon"), ("cambiar", "javier"), ("crear", "guest"), ("crear", "prueba"), ("desactivar", "jparamo"), ("desactivar", "janPlanificacion")]
    assert con.execute("SELECT rol FROM redes.usuarios WHERE nombre = 'jan'").fetchone()["rol"] == "tecnico"        # a simulation changes nothing
    configurar_usuarios.aplicar(con, plan)
    estado = {f["nombre"]: (f["rol"], f["borrado_en"] is None) for f in con.execute("SELECT nombre, rol, borrado_en FROM redes.usuarios").fetchall()}
    assert estado == {"jan": ("super_administrador", True), "marlon": ("administrador", True), "javier": ("administrador", True), "guest": ("guest", True), "prueba": ("prueba", True),
                      "jparamo": ("administrador", False), "janPlanificacion": ("administrador", False)}
    assert [a for a, _, _ in configurar_usuarios.construir_plan(con, desactivar_otros=True)] == ["igual"] * 5                # again: nothing to do
    assert con.execute("SELECT count(*) AS n FROM redes.historial WHERE entidad = 'usuario'").fetchone()["n"] >= 6              # every change has its history
