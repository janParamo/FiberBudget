"""Problemas (fase 7.1): registro de problemas ligados a un elemento (mufa, poste, cliente, nodo) o a
un cable de un proyecto: título, descripción, severidad, estado (abierto / en proceso / cerrado),
fotos y usuario. En el mapa se ven como íconos de alerta (web/redes/editor_mapa.js) con filtro.

Permisos: cualquier usuario con acceso al proyecto puede reportar un problema (incluido un lector:
quien está en campo); editarlo, cerrarlo o eliminarlo, quien edita el proyecto o quien lo reportó.
"""
from typing import Any

from visor_rutas.redes import proyectos, repositorio, usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

SEVERIDADES = ("baja", "media", "alta", "critica")
ESTADOS = ("abierto", "en_proceso", "cerrado")
MAX_FOTOS = 6

# location on the map: the element's current position, else the middle of the cable, else the saved one
_UBICACION = ("COALESCE(CASE WHEN e.borrado_en IS NULL THEN e.ubicacion END, "
              "CASE WHEN c.borrado_en IS NULL THEN ST_LineInterpolatePoint(c.geom, 0.5) END, pr.ubicacion)")

_SELECT = f"""
SELECT pr.id, pr.proyecto_id, p.nombre AS proyecto, p.codigo AS proyecto_codigo, pr.elemento_id, pr.cable_id,
       e.nombre AS elemento, e.tipo AS elemento_tipo, e.subtipo AS elemento_subtipo, e.borrado_en IS NOT NULL AS elemento_eliminado,
       c.nombre AS cable, c.borrado_en IS NOT NULL AS cable_eliminado,
       pr.titulo, pr.descripcion, pr.severidad, pr.estado, pr.cerrado_en, pr.version,
       ST_Y({_UBICACION}) AS lat, ST_X({_UBICACION}) AS lon,
       pr.creado_en, pr.creado_por AS creado_por_id, cu.nombre AS creado_por, pr.actualizado_en, au.nombre AS actualizado_por,
       (SELECT count(*) FROM redes.problema_fotos f WHERE f.problema_id = pr.id AND f.borrado_en IS NULL) AS n_fotos,
       (SELECT f.miniatura FROM redes.problema_fotos f WHERE f.problema_id = pr.id AND f.borrado_en IS NULL ORDER BY f.id LIMIT 1) AS miniatura
FROM redes.problemas pr
JOIN redes.proyectos p ON p.id = pr.proyecto_id
LEFT JOIN redes.elementos e ON e.id = pr.elemento_id
LEFT JOIN redes.cables c ON c.id = pr.cable_id
LEFT JOIN redes.usuarios cu ON cu.id = pr.creado_por
LEFT JOIN redes.usuarios au ON au.id = pr.actualizado_por
"""


def visibles(actor: dict[str, Any], alias: str = "p") -> tuple[str, tuple]:
    """SQL condition: projects the actor can see (all for an administrator)."""
    if usuarios.es_admin(actor):
        return f"{alias}.borrado_en IS NULL", ()
    return (f"{alias}.borrado_en IS NULL AND ({alias}.es_red_base OR {alias}.id IN "
            f"(SELECT proyecto_id FROM redes.proyecto_usuarios WHERE usuario_id = %s))",
            (actor["id"],))


def _publico(con: Any, actor: dict[str, Any], f: dict[str, Any], editables: dict[int, bool]) -> dict[str, Any]:
    if f["proyecto_id"] not in editables:
        editables[f["proyecto_id"]] = proyectos.puede_editar(con, actor, f["proyecto_id"])
    d = {k: v for k, v in f.items() if k != "miniatura"}
    d["miniatura"] = proyectos._data_url(f["miniatura"], "image/png")
    d["vinculo"] = (f"{f['elemento']} ({f['elemento_tipo']})" if f["elemento_id"] else f"Cable {f['cable']}") + \
        (" · eliminado" if f["elemento_eliminado"] or f["cable_eliminado"] else "")
    d["puede_editar"] = editables[f["proyecto_id"]] or f["creado_por_id"] == actor["id"]
    return d


def listar(con: Any, actor: dict[str, Any], *, proyecto_id: int | None = None, estado: str | None = None,
           severidad: str | None = None, texto: str | None = None) -> dict[str, Any]:
    condicion, parametros = visibles(actor)
    sql = _SELECT + f" WHERE pr.borrado_en IS NULL AND {condicion}"
    params: list[Any] = list(parametros)
    if proyecto_id:
        sql += " AND pr.proyecto_id = %s"
        params.append(int(proyecto_id))
    if estado == "activos":
        sql += " AND pr.estado <> 'cerrado'"
    elif estado in ESTADOS:
        sql += " AND pr.estado = %s"
        params.append(estado)
    if severidad in SEVERIDADES:
        sql += " AND pr.severidad = %s"
        params.append(severidad)
    elif severidad == "alta_o_mas":
        sql += " AND pr.severidad IN ('alta', 'critica')"
    if texto and str(texto).strip():
        sql += " AND (pr.titulo ILIKE %s OR pr.descripcion ILIKE %s OR e.nombre ILIKE %s OR c.nombre ILIKE %s)"
        patron = f"%{str(texto).strip()}%"
        params += [patron] * 4
    sql += (" ORDER BY CASE pr.estado WHEN 'abierto' THEN 0 WHEN 'en_proceso' THEN 1 ELSE 2 END, "
            "array_position(ARRAY['critica','alta','media','baja'], pr.severidad), pr.creado_en DESC LIMIT 2000")
    editables: dict[int, bool] = {}
    return {"problemas": [_publico(con, actor, dict(f), editables) for f in con.execute(sql, params).fetchall()]}


def _fila(con: Any, id_: int) -> dict[str, Any]:
    f = con.execute(_SELECT + " WHERE pr.id = %s AND pr.borrado_en IS NULL", (int(id_),)).fetchone()
    if f is None:
        raise NoEncontrado("El problema no existe (o fue eliminado)")
    return dict(f)


def obtener(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    f = _fila(con, id)
    if not proyectos.puede_ver(con, actor, f["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    fotos = [{"id": x["id"], "miniatura": proyectos._data_url(x["miniatura"], "image/png"), "creado_en": x["creado_en"]}
             for x in con.execute("SELECT id, miniatura, creado_en FROM redes.problema_fotos WHERE problema_id = %s AND borrado_en IS NULL "
                                  "ORDER BY id", (f["id"],)).fetchall()]
    return {"problema": {**_publico(con, actor, f, {}), "fotos": fotos}}


def foto(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    f = con.execute("SELECT f.imagen, f.imagen_tipo, p.proyecto_id FROM redes.problema_fotos f JOIN redes.problemas p ON p.id = f.problema_id "
                    "WHERE f.id = %s AND f.borrado_en IS NULL", (int(id),)).fetchone()
    if f is None:
        raise NoEncontrado("La foto no existe")
    if not proyectos.puede_ver(con, actor, f["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    return {"imagen": proyectos._data_url(f["imagen"], f["imagen_tipo"])}


def vinculo(con: Any, proyecto_id: int, elemento_id: Any, cable_id: Any, obligatorio: bool, errores: dict[str, str]) -> tuple[int | None, int | None, Any]:
    """(elemento_id, cable_id, location) checked against the project."""
    elemento_id = int(elemento_id) if str(elemento_id or "").isdigit() else None
    cable_id = int(cable_id) if str(cable_id or "").isdigit() else None
    if elemento_id and cable_id:
        errores["vinculo"] = "elija un elemento o un cable, no los dos"
        return None, None, None
    if elemento_id:
        f = con.execute("SELECT ubicacion FROM redes.elementos WHERE id = %s AND proyecto_id = %s AND borrado_en IS NULL",
                        (elemento_id, proyecto_id)).fetchone()
        if f is None:
            errores["vinculo"] = "el elemento no es de este proyecto"
            return None, None, None
        return elemento_id, None, f["ubicacion"]
    if cable_id:
        f = con.execute("SELECT ST_LineInterpolatePoint(geom, 0.5) AS u FROM redes.cables WHERE id = %s AND proyecto_id = %s "
                        "AND borrado_en IS NULL", (cable_id, proyecto_id)).fetchone()
        if f is None:
            errores["vinculo"] = "el cable no es de este proyecto"
            return None, None, None
        return None, cable_id, f["u"]
    if obligatorio:
        errores["vinculo"] = "elija el elemento o cable del mapa donde está el problema"
    return None, None, None


def _texto(valor: Any, maximo: int, multilinea: bool = False) -> str | None:
    t = str(valor or "").strip() if multilinea else " ".join(str(valor or "").split())
    return t[:maximo] or None


def guardar(con: Any, actor: dict[str, Any], *, datos: dict[str, Any]) -> dict[str, Any]:
    datos = datos if isinstance(datos, dict) else {}
    actual = _fila(con, int(datos["id"])) if datos.get("id") else None
    proyecto_id = actual["proyecto_id"] if actual else int(datos.get("proyecto_id") or 0)
    if not proyecto_id or not proyectos.puede_ver(con, actor, proyecto_id):
        raise SinPermiso("No tiene acceso a este proyecto")
    if actual and not (proyectos.puede_editar(con, actor, proyecto_id) or actual["creado_por_id"] == actor["id"]):
        raise SinPermiso("Solo quien edita el proyecto o quien reportó el problema lo puede cambiar")
    errores: dict[str, str] = {}
    titulo = _texto(datos.get("titulo"), 160)
    if not titulo:
        errores["titulo"] = "el título es obligatorio"
    severidad = datos.get("severidad") or "media"
    if severidad not in SEVERIDADES:
        errores["severidad"] = "baja, media, alta o crítica"
    estado = datos.get("estado") or "abierto"
    if estado not in ESTADOS:
        errores["estado"] = "abierto, en proceso o cerrado"
    elemento_id, cable_id, ubicacion = vinculo(con, proyecto_id, datos.get("elemento_id"), datos.get("cable_id"), True, errores)
    nuevas = [x for x in (datos.get("fotos_nuevas") or []) if x]
    quitar = {int(x) for x in (datos.get("fotos_quitar") or []) if str(x).isdigit()}
    imagenes = []
    for i, valor in enumerate(nuevas):
        try:
            imagenes.append(proyectos.procesar_imagen(valor))
        except DatosInvalidos as exc:
            errores["fotos"] = f"foto {i + 1}: {exc.errores.get('imagen', 'no válida')}"
            break
    existentes = 0 if not actual else con.execute(
        "SELECT count(*) AS n FROM redes.problema_fotos WHERE problema_id = %s AND borrado_en IS NULL AND NOT (id = ANY(%s))",
        (actual["id"], list(quitar))).fetchone()["n"]
    if existentes + len(imagenes) > MAX_FOTOS:
        errores["fotos"] = f"máximo {MAX_FOTOS} fotos por problema"
    if errores:
        raise DatosInvalidos(errores)
    valores = {"titulo": titulo, "descripcion": _texto(datos.get("descripcion"), 4000, True), "severidad": severidad,
               "estado": estado, "elemento_id": elemento_id, "cable_id": cable_id, "ubicacion": ubicacion}
    with con.transaction():
        if actual:
            if actual["estado"] != "cerrado" and estado == "cerrado":
                valores["cerrado_en"] = con.execute("SELECT now() AS n").fetchone()["n"]
            elif estado != "cerrado":
                valores["cerrado_en"] = None
            try:
                antes, despues = repositorio.actualizar(con, "problemas", actual["id"], int(datos.get("version") or 0), valores, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("Otro usuario cambió este problema mientras usted editaba. Recargue.") from None
            id_ = actual["id"]
            auditar = {k: v for k, v in valores.items() if k not in ("ubicacion", "cerrado_en")}
            cambio = repositorio.diferencias({k: antes[k] for k in auditar}, {k: despues[k] for k in auditar})
        else:
            if estado == "cerrado":
                valores["cerrado_en"] = con.execute("SELECT now() AS n").fetchone()["n"]
            fila = repositorio.insertar(con, "problemas", {**valores, "proyecto_id": proyecto_id}, actor["id"])
            id_ = fila["id"]
            cambio = repositorio.diferencias(None, {k: v for k, v in valores.items() if k not in ("ubicacion", "cerrado_en")})
        if quitar:
            con.execute("UPDATE redes.problema_fotos SET borrado_en = now() WHERE problema_id = %s AND id = ANY(%s) AND borrado_en IS NULL",
                        (id_, list(quitar)))
            cambio["fotos_quitadas"] = [None, len(quitar)]
        for datos_img, tipo, mini in imagenes:
            con.execute("INSERT INTO redes.problema_fotos (problema_id, imagen, imagen_tipo, miniatura, creado_por) VALUES (%s, %s, %s, %s, %s)",
                        (id_, datos_img, tipo, mini, actor["id"]))
        if imagenes:
            cambio["fotos_agregadas"] = [None, len(imagenes)]
        if cambio or not actual:
            repositorio.registrar(con, actor["id"], "problema", id_, "editar" if actual else "crear", cambio, proyecto_id=proyecto_id)
    return {**obtener(con, actor, id=id_), "id": id_}


def eliminar(con: Any, actor: dict[str, Any], *, id: int, version: int) -> dict[str, Any]:
    actual = _fila(con, id)
    if not (proyectos.puede_editar(con, actor, actual["proyecto_id"]) or actual["creado_por_id"] == actor["id"]):
        raise SinPermiso("Solo quien edita el proyecto o quien reportó el problema lo puede eliminar")
    with con.transaction():
        ahora = con.execute("SELECT now() AS n").fetchone()["n"]
        try:
            repositorio.actualizar(con, "problemas", actual["id"], int(version or 0), {"borrado_en": ahora}, actor["id"])
        except ConflictoVersion:
            raise ConflictoVersion("Otro usuario cambió este problema. Recargue.") from None
        repositorio.registrar(con, actor["id"], "problema", actual["id"], "eliminar", {"titulo": [actual["titulo"], None]},
                              proyecto_id=actual["proyecto_id"])
    return {"ok": True}


def historial(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    actual = _fila(con, id)
    if not proyectos.puede_ver(con, actor, actual["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    filas = con.execute("SELECT h.fecha, h.accion, h.cambio, u.nombre AS usuario FROM redes.historial h LEFT JOIN redes.usuarios u "
                        "ON u.id = h.usuario_id WHERE h.entidad = 'problema' AND h.entidad_id = %s ORDER BY h.fecha DESC", (actual["id"],)).fetchall()
    return {"historial": [dict(f) for f in filas]}


def referencias(con: Any, actor: dict[str, Any], *, proyecto_id: int) -> dict[str, Any]:
    """What the Problemas / Pendientes forms offer for a project: its elements and cables, and the
    users who can be responsible (assigned to the project, plus administrators)."""
    if not proyectos.puede_ver(con, actor, int(proyecto_id)):
        raise SinPermiso("No tiene acceso a este proyecto")
    elementos = [dict(f) for f in con.execute(
        "SELECT id, tipo, subtipo, nombre FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY tipo, nombre",
        (int(proyecto_id),)).fetchall()]
    cables = [dict(f) for f in con.execute(
        "SELECT id, nombre, hilos FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY nombre", (int(proyecto_id),)).fetchall()]
    gente = [dict(f) for f in con.execute(
        "SELECT id, nombre, rol FROM redes.usuarios WHERE borrado_en IS NULL AND (rol = 'administrador' OR id IN "
        "(SELECT usuario_id FROM redes.proyecto_usuarios WHERE proyecto_id = %s)) ORDER BY lower(nombre)", (int(proyecto_id),)).fetchall()]
    return {"elementos": elementos, "cables": cables, "usuarios": gente,
            "puede_editar": proyectos.puede_editar(con, actor, int(proyecto_id))}
