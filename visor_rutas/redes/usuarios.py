"""Usuarios del módulo de redes: identificación, roles y su administración.

Identificación al abrir el visor (nadie escribe su nombre):
  - modo local (la PC del servidor): el usuario de Windows. Si todavía no hay ningún
    administrador activo, queda como administrador; si ya hay, como lector.
  - modo remoto (VisorRutas.exe): la persona de su X-Visor-Key (VISOR_API_KEYS). Si no está en la
    tabla se crea como lector; un administrador le asigna el rol.
Roles: administrador (todo, incluidos usuarios), editor (edita los proyectos donde está
asignado), lector (solo ve los proyectos donde está asignado), tecnico (app de campo: solo crea y edita sus propios puntos pendientes).
Desactivar un usuario es borrado lógico (borrado_en): se puede reactivar.
"""
import re
from typing import Any

from visor_rutas.redes import repositorio
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

ROLES = ("administrador", "editor", "lector", "tecnico")
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_IDENTIFICADOR = re.compile(r"^[\w.@-]{1,64}$")
PUBLICOS = ("id", "nombre", "correo", "rol", "persona_visor", "usuario_windows", "version",
            "creado_en", "actualizado_en", "borrado_en")


def publico(fila: dict[str, Any]) -> dict[str, Any]:
    datos = {k: fila.get(k) for k in PUBLICOS}
    datos["activo"] = fila.get("borrado_en") is None
    return datos


def es_admin(actor: dict[str, Any]) -> bool:
    return actor.get("rol") == "administrador" and actor.get("borrado_en") is None


def puede_editar(actor: dict[str, Any]) -> bool:
    return actor.get("rol") in ("administrador", "editor") and actor.get("borrado_en") is None


def exigir_admin(actor: dict[str, Any]) -> None:
    if not es_admin(actor):
        raise SinPermiso("Solo un administrador puede hacer esto")


# --------------------------------------------------------------------------- identificación

def identificar(con: Any, *, persona_visor: str | None = None, usuario_windows: str | None = None, rol_inicial: str | None = None) -> dict[str, Any]:
    """The user making the call (created the first time). SinPermiso if deactivated.
    `rol_inicial`: the role of a NEW remote person (a technician's own key creates «tecnico»); never changes an existing user and never
    makes a remote person an administrator."""
    if persona_visor:
        campo, valor, origen = "persona_visor", str(persona_visor).strip(), "visor"
    elif usuario_windows:
        campo, valor, origen = "usuario_windows", str(usuario_windows).strip(), "windows"
    else:
        raise SinPermiso("No se pudo identificar al usuario")
    consulta = f"SELECT * FROM redes.usuarios WHERE lower({campo}) = lower(%s)"
    fila = con.execute(consulta, (valor,)).fetchone()
    if fila is None:
        with con.transaction():
            con.execute("LOCK TABLE redes.usuarios IN SHARE ROW EXCLUSIVE MODE")
            fila = con.execute(consulta, (valor,)).fetchone()        # another request may have created it
            if fila is None:
                # Only this PC (Windows user) can become the first administrator, never a remote key
                # (even if the remote person came first, the server PC still gets the admin).
                rol = "administrador" if (origen == "windows" and not _admins_activos(con)) else "lector"
                if origen == "visor" and rol_inicial == "tecnico":
                    rol = "tecnico"
                fila = repositorio.insertar(con, "usuarios", {"nombre": valor, campo: valor, "rol": rol}, None)
                repositorio.registrar(con, fila["id"], "usuario", fila["id"], "identificar",
                                      {"origen": origen, "rol": rol, campo: valor})
    if fila["borrado_en"] is not None:
        raise SinPermiso(f"El usuario {fila['nombre']} está desactivado. Pida a un administrador que lo reactive.")
    return fila


# --------------------------------------------------------------------------- administración

def listar(con: Any, actor: dict[str, Any], *, incluir_inactivos: bool = True) -> dict[str, Any]:
    filas = con.execute("SELECT * FROM redes.usuarios" + ("" if incluir_inactivos else " WHERE borrado_en IS NULL")
                        + " ORDER BY borrado_en IS NOT NULL, lower(nombre)").fetchall()
    return {"usuarios": [publico(f) for f in filas], "puede_administrar": es_admin(actor)}


def _limpio(valor: Any) -> str | None:
    texto = " ".join(str(valor or "").split())
    return texto or None


def _validar(datos: dict[str, Any]) -> dict[str, Any]:
    errores: dict[str, str] = {}
    valores = {"nombre": _limpio(datos.get("nombre")), "correo": _limpio(datos.get("correo")),
               "rol": _limpio(datos.get("rol")) or "lector",
               "persona_visor": _limpio(datos.get("persona_visor")),
               "usuario_windows": _limpio(datos.get("usuario_windows"))}
    if not valores["nombre"]:
        errores["nombre"] = "Campo obligatorio"
    elif len(valores["nombre"]) > 120:
        errores["nombre"] = "Máximo 120 caracteres"
    if valores["correo"] and not _CORREO.match(valores["correo"]):
        errores["correo"] = "Correo no válido"
    if valores["rol"] not in ROLES:
        errores["rol"] = "Elija administrador, editor o lector"
    for campo in ("persona_visor", "usuario_windows"):
        if valores[campo] and not _IDENTIFICADOR.match(valores[campo]):
            errores[campo] = "Solo letras, números, punto, guion y @ (sin espacios)"
    if errores:
        raise DatosInvalidos(errores)
    return valores


def _duplicados(con: Any, valores: dict[str, Any], id_: int | None) -> None:
    errores = {}
    for campo, texto in (("correo", "Ya hay un usuario con ese correo"),
                         ("persona_visor", "Esa persona del visor ya está asignada a otro usuario"),
                         ("usuario_windows", "Ese usuario de Windows ya está asignado a otro usuario")):
        if valores[campo] and con.execute(
                f"SELECT 1 FROM redes.usuarios WHERE lower({campo}) = lower(%s) AND id IS DISTINCT FROM %s",
                (valores[campo], id_)).fetchone():
            errores[campo] = texto
    if errores:
        raise DatosInvalidos(errores)


def _admins_activos(con: Any, excepto: int | None = None) -> int:
    return con.execute("SELECT count(*) AS n FROM redes.usuarios WHERE rol = 'administrador' AND borrado_en IS NULL "
                       "AND id IS DISTINCT FROM %s", (excepto,)).fetchone()["n"]


def guardar(con: Any, actor: dict[str, Any], *, datos: dict[str, Any]) -> dict[str, Any]:
    """Creates (no id) or edits (id + version) a user. Administrators only."""
    exigir_admin(actor)
    datos = dict(datos or {})
    valores = _validar(datos)
    id_ = datos.get("id")
    with con.transaction():
        _duplicados(con, valores, int(id_) if id_ else None)
        if not id_:
            fila = repositorio.insertar(con, "usuarios", valores, actor["id"])
            repositorio.registrar(con, actor["id"], "usuario", fila["id"], "crear", repositorio.diferencias(None, fila))
        else:
            actual = repositorio.obtener(con, "usuarios", int(id_), bloquear=True)
            if actual["rol"] == "administrador" and valores["rol"] != "administrador" and not _admins_activos(con, actual["id"]):
                raise DatosInvalidos({"rol": "Debe quedar al menos un administrador activo"})
            antes, fila = repositorio.actualizar(con, "usuarios", int(id_), int(datos.get("version") or 0), valores, actor["id"])
            repositorio.registrar(con, actor["id"], "usuario", fila["id"], "editar", repositorio.diferencias(antes, fila))
    return {"usuario": publico(fila)}


def cambiar_estado(con: Any, actor: dict[str, Any], *, id: int, version: int, activo: bool) -> dict[str, Any]:
    """Deactivates (logical delete) or reactivates a user. Administrators only."""
    exigir_admin(actor)
    with con.transaction():
        actual = repositorio.obtener(con, "usuarios", int(id), bloquear=True)
        if not activo:
            if actual["id"] == actor["id"]:
                raise DatosInvalidos({"usuario": "No puede desactivarse a sí mismo"})
            if actual["rol"] == "administrador" and not _admins_activos(con, actual["id"]):
                raise DatosInvalidos({"usuario": "Debe quedar al menos un administrador activo"})
        valor = None if activo else con.execute("SELECT now() AS n").fetchone()["n"]
        if (actual["borrado_en"] is None) == bool(activo):
            return {"usuario": publico(actual)}                     # already in that state
        antes, fila = repositorio.actualizar(con, "usuarios", int(id), int(version), {"borrado_en": valor}, actor["id"])
        repositorio.registrar(con, actor["id"], "usuario", fila["id"], "restaurar" if activo else "eliminar",
                              repositorio.diferencias(antes, fila))
    return {"usuario": publico(fila)}


def historial(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    exigir_admin(actor)
    if con.execute("SELECT 1 FROM redes.usuarios WHERE id = %s", (int(id),)).fetchone() is None:
        raise NoEncontrado("El usuario no existe")
    filas = con.execute(
        "SELECT h.fecha, h.accion, h.cambio, u.nombre AS usuario FROM redes.historial h "
        "LEFT JOIN redes.usuarios u ON u.id = h.usuario_id WHERE h.entidad = 'usuario' AND h.entidad_id = %s "
        "ORDER BY h.fecha DESC, h.id DESC LIMIT 200", (int(id),)).fetchall()
    return {"historial": [{**f, "fecha": f["fecha"].isoformat()} for f in filas]}
