"""Pendientes (fase 7.2): tareas ligadas a un proyecto y, si se quiere, a un elemento o cable
("validar existencia de mufa", "dar continuidad a hilos"): responsable, fecha límite y estado
(pendiente / en proceso / hecho). Lista con filtros (proyecto, estado, responsable, vencidos, texto).

Permisos: crea, edita y elimina quien edita el proyecto; el responsable de una tarea puede cambiar
su estado aunque solo sea lector.
"""
from datetime import date
from typing import Any

from visor_rutas.redes import problemas, proyectos, repositorio
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

ESTADOS = ("pendiente", "en_proceso", "hecho")

_SELECT = """
SELECT t.id, t.proyecto_id, p.nombre AS proyecto, p.codigo AS proyecto_codigo, t.elemento_id, t.cable_id,
       e.nombre AS elemento, e.tipo AS elemento_tipo, c.nombre AS cable,
       t.titulo, t.descripcion, t.responsable_id, r.nombre AS responsable, t.fecha_limite, t.estado, t.hecho_en, t.version,
       (t.estado <> 'hecho' AND t.fecha_limite < current_date) AS vencido,
       t.creado_en, cu.nombre AS creado_por, t.actualizado_en, au.nombre AS actualizado_por
FROM redes.pendientes t
JOIN redes.proyectos p ON p.id = t.proyecto_id
LEFT JOIN redes.elementos e ON e.id = t.elemento_id
LEFT JOIN redes.cables c ON c.id = t.cable_id
LEFT JOIN redes.usuarios r ON r.id = t.responsable_id
LEFT JOIN redes.usuarios cu ON cu.id = t.creado_por
LEFT JOIN redes.usuarios au ON au.id = t.actualizado_por
"""


def _publico(con: Any, actor: dict[str, Any], f: dict[str, Any], editables: dict[int, bool]) -> dict[str, Any]:
    if f["proyecto_id"] not in editables:
        editables[f["proyecto_id"]] = proyectos.puede_editar(con, actor, f["proyecto_id"])
    vinculo = f"{f['elemento']} ({f['elemento_tipo']})" if f["elemento_id"] else f"Cable {f['cable']}" if f["cable_id"] else ""
    return {**f, "vinculo": vinculo, "puede_editar": editables[f["proyecto_id"]],
            "puede_cambiar_estado": editables[f["proyecto_id"]] or f["responsable_id"] == actor["id"]}


def listar(con: Any, actor: dict[str, Any], *, proyecto_id: int | None = None, estado: str | None = None,
           responsable: str | int | None = None, vencidos: bool = False, texto: str | None = None) -> dict[str, Any]:
    condicion, parametros = problemas.visibles(actor)
    sql = _SELECT + f" WHERE t.borrado_en IS NULL AND {condicion}"
    params: list[Any] = list(parametros)
    if proyecto_id:
        sql += " AND t.proyecto_id = %s"
        params.append(int(proyecto_id))
    if estado == "abiertos":
        sql += " AND t.estado <> 'hecho'"
    elif estado in ESTADOS:
        sql += " AND t.estado = %s"
        params.append(estado)
    if responsable == "yo":
        sql += " AND t.responsable_id = %s"
        params.append(actor["id"])
    elif responsable == "nadie":
        sql += " AND t.responsable_id IS NULL"
    elif str(responsable or "").isdigit():
        sql += " AND t.responsable_id = %s"
        params.append(int(responsable))
    if vencidos:
        sql += " AND t.estado <> 'hecho' AND t.fecha_limite < current_date"
    if texto and str(texto).strip():
        sql += " AND (t.titulo ILIKE %s OR t.descripcion ILIKE %s OR e.nombre ILIKE %s OR c.nombre ILIKE %s)"
        params += [f"%{str(texto).strip()}%"] * 4
    sql += (" ORDER BY (t.estado = 'hecho'), t.fecha_limite NULLS LAST, "
            "array_position(ARRAY['en_proceso','pendiente','hecho'], t.estado), t.creado_en DESC LIMIT 2000")
    editables: dict[int, bool] = {}
    return {"pendientes": [_publico(con, actor, dict(f), editables) for f in con.execute(sql, params).fetchall()]}


def _fila(con: Any, id_: int) -> dict[str, Any]:
    f = con.execute(_SELECT + " WHERE t.id = %s AND t.borrado_en IS NULL", (int(id_),)).fetchone()
    if f is None:
        raise NoEncontrado("El pendiente no existe (o fue eliminado)")
    return dict(f)


def _fecha(valor: Any, errores: dict[str, str]) -> date | None:
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        errores["fecha_limite"] = "fecha no válida (AAAA-MM-DD)"
        return None


def guardar(con: Any, actor: dict[str, Any], *, datos: dict[str, Any]) -> dict[str, Any]:
    datos = datos if isinstance(datos, dict) else {}
    actual = _fila(con, int(datos["id"])) if datos.get("id") else None
    proyecto_id = actual["proyecto_id"] if actual else int(datos.get("proyecto_id") or 0)
    if not proyecto_id or not proyectos.puede_ver(con, actor, proyecto_id):
        raise SinPermiso("No tiene acceso a este proyecto")
    editor = proyectos.puede_editar(con, actor, proyecto_id)
    solo_estado = bool(actual) and not editor and actual["responsable_id"] == actor["id"]
    if not editor and not solo_estado:
        raise SinPermiso("Solo quien edita el proyecto puede crear o cambiar pendientes (el responsable puede cambiar el estado)")
    errores: dict[str, str] = {}
    estado = datos.get("estado") or "pendiente"
    if estado not in ESTADOS:
        errores["estado"] = "pendiente, en proceso o hecho"
    if solo_estado:
        valores: dict[str, Any] = {"estado": estado}
    else:
        titulo = problemas._texto(datos.get("titulo"), 160)
        if not titulo:
            errores["titulo"] = "el título es obligatorio"
        elemento_id, cable_id, _ = problemas.vinculo(con, proyecto_id, datos.get("elemento_id"), datos.get("cable_id"), False, errores)
        responsable_id = int(datos["responsable_id"]) if str(datos.get("responsable_id") or "").isdigit() else None
        if responsable_id and con.execute("SELECT 1 FROM redes.usuarios WHERE id = %s AND borrado_en IS NULL", (responsable_id,)).fetchone() is None:
            errores["responsable_id"] = "usuario no válido"
        valores = {"titulo": titulo, "descripcion": problemas._texto(datos.get("descripcion"), 4000, True), "elemento_id": elemento_id,
                   "cable_id": cable_id, "responsable_id": responsable_id, "fecha_limite": _fecha(datos.get("fecha_limite"), errores),
                   "estado": estado}
    if errores:
        raise DatosInvalidos(errores)
    with con.transaction():
        ahora = con.execute("SELECT now() AS n").fetchone()["n"]
        if actual:
            if estado == "hecho" and actual["estado"] != "hecho":
                valores["hecho_en"] = ahora
            elif estado != "hecho":
                valores["hecho_en"] = None
            try:
                antes, despues = repositorio.actualizar(con, "pendientes", actual["id"], int(datos.get("version") or 0), valores, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("Otro usuario cambió este pendiente mientras usted editaba. Recargue.") from None
            auditar = [k for k in valores if k != "hecho_en"]
            cambio = repositorio.diferencias({k: antes[k] for k in auditar}, {k: despues[k] for k in auditar})
            if cambio:
                repositorio.registrar(con, actor["id"], "pendiente", actual["id"], "editar", cambio, proyecto_id=proyecto_id)
            id_ = actual["id"]
        else:
            if estado == "hecho":
                valores["hecho_en"] = ahora
            fila = repositorio.insertar(con, "pendientes", {**valores, "proyecto_id": proyecto_id}, actor["id"])
            repositorio.registrar(con, actor["id"], "pendiente", fila["id"], "crear",
                                  repositorio.diferencias(None, {k: v for k, v in valores.items() if k != "hecho_en"}), proyecto_id=proyecto_id)
            id_ = fila["id"]
    return {"pendiente": _publico(con, actor, _fila(con, id_), {}), "id": id_}


def eliminar(con: Any, actor: dict[str, Any], *, id: int, version: int) -> dict[str, Any]:
    actual = _fila(con, id)
    if not proyectos.puede_editar(con, actor, actual["proyecto_id"]):
        raise SinPermiso("Solo quien edita el proyecto puede eliminar pendientes")
    with con.transaction():
        ahora = con.execute("SELECT now() AS n").fetchone()["n"]
        try:
            repositorio.actualizar(con, "pendientes", actual["id"], int(version or 0), {"borrado_en": ahora}, actor["id"])
        except ConflictoVersion:
            raise ConflictoVersion("Otro usuario cambió este pendiente. Recargue.") from None
        repositorio.registrar(con, actor["id"], "pendiente", actual["id"], "eliminar", {"titulo": [actual["titulo"], None]},
                              proyecto_id=actual["proyecto_id"])
    return {"ok": True}


def historial(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    actual = _fila(con, id)
    if not proyectos.puede_ver(con, actor, actual["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    filas = con.execute("SELECT h.fecha, h.accion, h.cambio, u.nombre AS usuario FROM redes.historial h LEFT JOIN redes.usuarios u "
                        "ON u.id = h.usuario_id WHERE h.entidad = 'pendiente' AND h.entidad_id = %s ORDER BY h.fecha DESC", (actual["id"],)).fetchall()
    return {"historial": [dict(f) for f in filas]}
