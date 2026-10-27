"""Planificación de cuadrillas (migración 020): las actividades —instalaciones de presupuestos— que se asignan a las cuadrillas, su estado, su cola,
sus puntos de control y los tiempos.

Dos tipos de persona usan estas funciones:
- planificación (rol editor o administrador): crea las actividades (desde el visor de rutas, Kayako o a mano), las asigna a una cuadrilla, ordena su cola,
  cambia estados, marca puntos de control y puede dar por iniciada una actividad si la cuadrilla se olvidó;
- una cuadrilla (rol «tecnico» y miembro de la cuadrilla de la actividad): ve su cola, empieza, marca puntos de control, pausa y termina.

Estados:  inactivo -> asignado -> en_revision -> en_curso -> terminado   (más: pausado, no_viable, cancelado).
Tiempos:  espera = de asignada a iniciada; ejecución = de iniciada a terminada, sin lo pausado.
"""
import re
from datetime import datetime, timezone
from typing import Any

import psycopg.errors
from psycopg.types.json import Jsonb

from visor_rutas.redes import usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

ESTADOS = ("inactivo", "asignado", "en_revision", "en_curso", "pausado", "terminado", "no_viable", "cancelado")
ETIQUETAS_ESTADO = {"inactivo": "Inactivo", "asignado": "Asignado", "en_revision": "En revisión", "en_curso": "En curso", "pausado": "Pausado",
                    "terminado": "Terminado", "no_viable": "No viable", "cancelado": "Cancelado"}
TRANSICIONES = {
    "inactivo": {"asignado", "cancelado"},
    "asignado": {"en_revision", "en_curso", "inactivo", "cancelado"},
    "en_revision": {"en_curso", "no_viable", "asignado", "cancelado"},
    "en_curso": {"pausado", "terminado", "en_revision", "cancelado"},
    "pausado": {"en_curso", "no_viable", "cancelado"},
    "terminado": set(),
    "no_viable": {"inactivo", "cancelado"},
    "cancelado": {"inactivo"},
}
# What a crew may do by itself (the rest is for planning): start (review or straight to work), pause, resume, finish, say it is not viable.
DE_CUADRILLA = {("asignado", "en_revision"), ("asignado", "en_curso"), ("en_revision", "en_curso"), ("en_revision", "no_viable"),
                ("en_curso", "pausado"), ("en_curso", "terminado"), ("pausado", "en_curso")}
CON_MOTIVO = {"pausado", "no_viable", "cancelado"}
ORIGENES = ("visor", "kayako", "manual")
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 10.7, 15.1, -87.7, -82.7
ESPERA_ALERTA_MIN = 60                # an activity assigned for more than this and not started is flagged to planning


def es_planificacion(actor: dict[str, Any]) -> bool:
    return usuarios.puede_editar(actor)


def exigir_planificacion(actor: dict[str, Any]) -> None:
    if not es_planificacion(actor):
        raise SinPermiso("Solo planificación (editor o administrador) puede hacer esto")


def _texto(valor: Any, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _numero(valor: Any, campo: str, minimo: float, maximo: float) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({campo: "Debe ser un número"}) from None
    if not minimo <= n <= maximo:
        raise DatosInvalidos({campo: f"Fuera de Nicaragua ({minimo} a {maximo})"})
    return n


def _ids(ids: Any) -> list[int]:
    try:
        lista = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise DatosInvalidos({"ids": "Lista de números"}) from None
    if not lista or len(lista) > 200:
        raise DatosInvalidos({"ids": "Entre 1 y 200 actividades"})
    return lista


# --------------------------------------------------------------------------- lectura

_SELECT = ("SELECT a.*, ST_Y(a.ubicacion) AS lat, ST_X(a.ubicacion) AS lon, c.nombre AS cuadrilla, e.nombre AS empresa, "
           "CASE WHEN a.asignada_en IS NULL THEN NULL ELSE EXTRACT(EPOCH FROM COALESCE(a.iniciada_en, CASE WHEN a.estado IN ('no_viable', 'cancelado', 'inactivo') "
           "THEN a.actualizado_en ELSE now() END) - a.asignada_en)::bigint END AS espera_s, "
           "CASE WHEN a.iniciada_en IS NULL THEN NULL ELSE GREATEST(0, EXTRACT(EPOCH FROM COALESCE(a.terminada_en, a.pausada_desde, now()) - a.iniciada_en)::bigint "
           "- a.pausa_total_s) END AS ejecucion_s "
           "FROM redes.plan_actividades a LEFT JOIN redes.plan_cuadrillas c ON c.id = a.cuadrilla_id LEFT JOIN redes.plan_empresas e ON e.id = c.empresa_id")


def _iso(valor: Any) -> str | None:
    return valor.isoformat() if valor is not None else None


def _controles(con: Any, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    salida: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return salida
    for f in con.execute("SELECT k.actividad_id, k.clave, k.estado, k.marcado_en, k.origen, k.nota, g.etiqueta, g.obligatorio, u.nombre AS marcado_por "
                         "FROM redes.plan_actividad_control k JOIN redes.plan_control_catalogo g ON g.clave = k.clave "
                         "LEFT JOIN redes.usuarios u ON u.id = k.marcado_por WHERE k.actividad_id = ANY(%s) ORDER BY k.actividad_id, g.orden", (ids,)).fetchall():
        salida[f["actividad_id"]].append({"clave": f["clave"], "etiqueta": f["etiqueta"], "obligatorio": f["obligatorio"], "estado": f["estado"],
                                          "marcado_en": _iso(f["marcado_en"]), "origen": f["origen"], "nota": f["nota"], "marcado_por": f["marcado_por"]})
    return salida


def _publica(f: dict[str, Any], controles: list[dict[str, Any]]) -> dict[str, Any]:
    hechos = sum(1 for c in controles if c["estado"] == "hecho")
    salida = {k: f[k] for k in ("id", "ticket", "cliente_nombre", "codigo_cliente", "contacto_nombre", "contacto_telefono", "direccion", "origen", "presupuesto_clave",
                                "estado", "motivo_estado", "cuadrilla_id", "cola_orden", "prioridad", "iniciada_por", "notas", "version", "cuadrilla", "empresa",
                                "espera_s", "ejecucion_s")}
    salida.update(lat=float(f["lat"]), lon=float(f["lon"]), resumen=f["resumen"] or {},
                  presupuesto_total=None if f["presupuesto_total"] is None else float(f["presupuesto_total"]),
                  estado_etiqueta=ETIQUETAS_ESTADO[f["estado"]], pausada=f["estado"] == "pausado",
                  asignada_en=_iso(f["asignada_en"]), iniciada_en=_iso(f["iniciada_en"]), terminada_en=_iso(f["terminada_en"]), creado_en=_iso(f["creado_en"]),
                  controles=controles, avance={"hechos": hechos, "total": len(controles), "porcentaje": round(100 * hechos / len(controles)) if controles else 0},
                  sin_iniciar_alerta=bool(f["estado"] in ("asignado", "en_revision") and f["espera_s"] is not None and f["espera_s"] > ESPERA_ALERTA_MIN * 60))
    return salida


def _actividad(con: Any, id_: int, bloquear: bool = False) -> dict[str, Any]:
    f = con.execute(_SELECT + " WHERE a.id = %s AND a.borrado_en IS NULL" + (" FOR UPDATE OF a" if bloquear else ""), (id_,)).fetchone()
    if f is None:
        raise NoEncontrado("La actividad no existe")
    return f


def _cuadrilla_de(con: Any, actor: dict[str, Any]) -> dict[str, Any] | None:
    return con.execute("SELECT c.* FROM redes.plan_cuadrillas c JOIN redes.plan_cuadrilla_miembros m ON m.cuadrilla_id = c.id "
                       "WHERE m.usuario_id = %s AND c.activa ORDER BY c.id LIMIT 1", (actor["id"],)).fetchone()


def _exigir_acceso(con: Any, actor: dict[str, Any], f: dict[str, Any]) -> str:
    """"planificacion" or "cuadrilla" (the crew the activity is assigned to); otherwise SinPermiso."""
    if es_planificacion(actor):
        return "planificacion"
    propia = _cuadrilla_de(con, actor) if actor.get("rol") == "tecnico" and actor.get("borrado_en") is None else None
    if propia is None or f["cuadrilla_id"] != propia["id"]:
        raise SinPermiso("Esta actividad no está asignada a su cuadrilla")
    return "cuadrilla"


def exigir_eventos(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Who may receive the live notices: planning, or a technician that belongs to a crew."""
    if es_planificacion(actor):
        return {}
    if actor.get("rol") == "tecnico" and actor.get("borrado_en") is None and _cuadrilla_de(con, actor) is not None:
        return {}
    raise SinPermiso("Los avisos son de planificación y de las cuadrillas")


def catalogo(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    return {"estados": [{"clave": e, "etiqueta": ETIQUETAS_ESTADO[e]} for e in ESTADOS],
            "controles": [dict(f) for f in con.execute("SELECT clave, etiqueta, orden, obligatorio FROM redes.plan_control_catalogo ORDER BY orden").fetchall()],
            "transiciones": {k: sorted(v) for k, v in TRANSICIONES.items()}}


# --------------------------------------------------------------------------- cuadrillas

def cuadrillas(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Every crew with its company, members, load (queue, in progress) and the last place its members were seen. Planning only."""
    exigir_planificacion(actor)
    filas = con.execute(
        "SELECT c.id, c.nombre, c.telefono, c.notas, c.activa, c.version, e.nombre AS empresa, e.tercerizada, "
        "(SELECT count(*) FROM redes.plan_actividades a WHERE a.cuadrilla_id = c.id AND a.borrado_en IS NULL AND a.estado IN ('asignado', 'en_revision', 'pausado')) AS en_cola, "
        "(SELECT count(*) FROM redes.plan_actividades a WHERE a.cuadrilla_id = c.id AND a.borrado_en IS NULL AND a.estado = 'en_curso') AS en_curso, "
        "(SELECT count(*) FROM redes.plan_actividades a WHERE a.cuadrilla_id = c.id AND a.borrado_en IS NULL AND a.estado = 'terminado') AS terminadas, "
        "(SELECT a.id FROM redes.plan_actividades a WHERE a.cuadrilla_id = c.id AND a.borrado_en IS NULL AND a.estado = 'en_curso' LIMIT 1) AS actividad_actual, "
        "COALESCE((SELECT jsonb_agg(jsonb_build_object('usuario_id', u.id, 'nombre', u.nombre) ORDER BY u.nombre) FROM redes.plan_cuadrilla_miembros m "
        "JOIN redes.usuarios u ON u.id = m.usuario_id WHERE m.cuadrilla_id = c.id AND u.borrado_en IS NULL), '[]'::jsonb) AS miembros "
        "FROM redes.plan_cuadrillas c JOIN redes.plan_empresas e ON e.id = c.empresa_id ORDER BY e.tercerizada DESC, e.nombre, c.nombre").fetchall()
    salida = []
    for f in filas:
        vista = con.execute(
            "SELECT ST_Y(l.ubicacion) AS lat, ST_X(l.ubicacion) AS lon, l.precision_m, l.recibido_en, EXTRACT(EPOCH FROM now() - l.recibido_en)::bigint AS hace_s, u.nombre "
            "FROM redes.campo_ubicaciones l JOIN redes.plan_cuadrilla_miembros m ON m.usuario_id = l.usuario_id JOIN redes.usuarios u ON u.id = l.usuario_id "
            "WHERE m.cuadrilla_id = %s ORDER BY l.recibido_en DESC LIMIT 1", (f["id"],)).fetchone()
        salida.append({**{k: f[k] for k in ("id", "nombre", "telefono", "notas", "activa", "version", "empresa", "tercerizada", "en_cola", "en_curso", "terminadas",
                                            "actividad_actual", "miembros")},
                       "ubicacion": None if vista is None else {"lat": float(vista["lat"]), "lon": float(vista["lon"]), "hace_s": vista["hace_s"], "quien": vista["nombre"],
                                                                "precision_m": None if vista["precision_m"] is None else float(vista["precision_m"])}})
    return {"cuadrillas": salida}


def crear_cuadrilla(con: Any, actor: dict[str, Any], *, empresa: str, nombre: str, telefono: str = "", notas: str = "") -> dict[str, Any]:
    exigir_planificacion(actor)
    empresa_, nombre_ = _texto(empresa, 80), _texto(nombre, 80)
    if not empresa_ or not nombre_:
        raise DatosInvalidos({"nombre": "Escriba la empresa y el nombre de la cuadrilla"})
    fila = con.execute("SELECT id FROM redes.plan_empresas WHERE lower(nombre) = lower(%s)", (empresa_,)).fetchone()
    if fila is None:
        fila = con.execute("INSERT INTO redes.plan_empresas (nombre) VALUES (%s) RETURNING id", (empresa_,)).fetchone()
    try:
        nuevo = con.execute("INSERT INTO redes.plan_cuadrillas (empresa_id, nombre, telefono, notas, creado_por) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                            (fila["id"], nombre_, _texto(telefono, 40), _texto(notas, 500), actor["id"])).fetchone()
    except psycopg.errors.UniqueViolation:
        raise DatosInvalidos({"nombre": "Ya hay una cuadrilla con ese nombre"}) from None
    return {"id": nuevo["id"]}


def editar_cuadrilla(con: Any, actor: dict[str, Any], *, id: int, cambios: dict[str, Any]) -> dict[str, Any]:
    exigir_planificacion(actor)
    campos, valores = [], []
    for k, maximo in (("nombre", 80), ("telefono", 40), ("notas", 500)):
        if k in cambios:
            texto = _texto(cambios[k], maximo)
            if k == "nombre" and not texto:
                raise DatosInvalidos({"nombre": "Campo obligatorio"})
            campos.append(f"{k} = %s")
            valores.append(texto)
    if "activa" in cambios:
        campos.append("activa = %s")
        valores.append(bool(cambios["activa"]))
    if not campos:
        raise DatosInvalidos({"cambios": "No hay nada que cambiar"})
    try:
        f = con.execute(f"UPDATE redes.plan_cuadrillas SET {', '.join(campos)}, actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s RETURNING id",
                        (*valores, actor["id"], id)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise DatosInvalidos({"nombre": "Ya hay una cuadrilla con ese nombre"}) from None
    if f is None:
        raise NoEncontrado("La cuadrilla no existe")
    return {"id": id}


def tecnicos(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """The users with the role «tecnico» and the crew each one belongs to (to put them in a crew). Planning only."""
    exigir_planificacion(actor)
    filas = con.execute("SELECT u.id, u.nombre, c.id AS cuadrilla_id, c.nombre AS cuadrilla FROM redes.usuarios u "
                        "LEFT JOIN redes.plan_cuadrilla_miembros m ON m.usuario_id = u.id LEFT JOIN redes.plan_cuadrillas c ON c.id = m.cuadrilla_id "
                        "WHERE u.rol = 'tecnico' AND u.borrado_en IS NULL ORDER BY u.nombre").fetchall()
    return {"tecnicos": [dict(f) for f in filas]}


def agregar_miembro(con: Any, actor: dict[str, Any], *, cuadrilla_id: int, usuario_id: int) -> dict[str, Any]:
    """Puts a technician (role «tecnico») in a crew: the crew app shows him what is assigned to it. Administrators only."""
    usuarios.exigir_admin(actor)
    u = con.execute("SELECT id, rol FROM redes.usuarios WHERE id = %s AND borrado_en IS NULL", (usuario_id,)).fetchone()
    if u is None:
        raise NoEncontrado("El usuario no existe")
    if u["rol"] != "tecnico":
        raise DatosInvalidos({"usuario_id": "Solo un usuario con el rol de técnico puede ser de una cuadrilla"})
    if con.execute("SELECT 1 FROM redes.plan_cuadrillas WHERE id = %s", (cuadrilla_id,)).fetchone() is None:
        raise NoEncontrado("La cuadrilla no existe")
    con.execute("DELETE FROM redes.plan_cuadrilla_miembros WHERE usuario_id = %s", (usuario_id,))              # a technician belongs to one crew
    con.execute("INSERT INTO redes.plan_cuadrilla_miembros (cuadrilla_id, usuario_id) VALUES (%s, %s)", (cuadrilla_id, usuario_id))
    return {}


def quitar_miembro(con: Any, actor: dict[str, Any], *, cuadrilla_id: int, usuario_id: int) -> dict[str, Any]:
    usuarios.exigir_admin(actor)
    con.execute("DELETE FROM redes.plan_cuadrilla_miembros WHERE cuadrilla_id = %s AND usuario_id = %s", (cuadrilla_id, usuario_id))
    return {}


# --------------------------------------------------------------------------- actividades (planificación)

def _historial(con: Any, actividad_id: int, a: str, de: str | None, actor: dict[str, Any], origen: str, cuadrilla_id: int | None, motivo: str = "") -> None:
    con.execute("INSERT INTO redes.plan_actividad_historial (actividad_id, de, a, por, origen, cuadrilla_id, motivo) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (actividad_id, de, a, actor["id"], origen, cuadrilla_id, motivo))


def crear_actividad(con: Any, actor: dict[str, Any], *, cliente_nombre: str, lat: float, lon: float, ticket: str = "", codigo_cliente: str = "",
                    contacto_nombre: str = "", contacto_telefono: str = "", direccion: str = "", origen: str = "visor", presupuesto_clave: str | None = None,
                    presupuesto_total: float | None = None, resumen: dict[str, Any] | None = None, notas: str = "", prioridad: int = 0) -> dict[str, Any]:
    """A new activity, «inactivo»: an approved budget taken to planning (from the route viewer, Kayako or by hand)."""
    exigir_planificacion(actor)
    nombre = _texto(cliente_nombre, 200)
    if not nombre:
        raise DatosInvalidos({"cliente_nombre": "Campo obligatorio"})
    if origen not in ORIGENES:
        raise DatosInvalidos({"origen": "visor, kayako o manual"})
    la, lo = _numero(lat, "lat", LAT_MIN, LAT_MAX), _numero(lon, "lon", LON_MIN, LON_MAX)
    ticket_ = _texto(ticket, 64)
    if ticket_ and con.execute("SELECT 1 FROM redes.plan_actividades WHERE ticket = %s AND lower(cliente_nombre) = lower(%s) AND borrado_en IS NULL "
                               "AND estado NOT IN ('cancelado', 'no_viable', 'terminado')", (ticket_, nombre)).fetchone():
        raise DatosInvalidos({"ticket": "Ese ticket ya está en planificación para ese cliente"})
    total = None if presupuesto_total in (None, "") else float(presupuesto_total)
    f = con.execute(
        "INSERT INTO redes.plan_actividades (ticket, cliente_nombre, codigo_cliente, contacto_nombre, contacto_telefono, direccion, ubicacion, origen, presupuesto_clave, "
        "presupuesto_total, resumen, notas, prioridad, creado_por, actualizado_por) VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id", (ticket_, nombre, _texto(codigo_cliente, 64), _texto(contacto_nombre, 200), _texto(contacto_telefono, 64), _texto(direccion, 300), lo, la, origen,
                         _texto(presupuesto_clave, 300) or None, total, Jsonb(resumen or {}), _texto(notas, 1000), int(prioridad or 0), actor["id"], actor["id"])).fetchone()
    con.execute("INSERT INTO redes.plan_actividad_control (actividad_id, clave) SELECT %s, clave FROM redes.plan_control_catalogo", (f["id"],))
    _historial(con, f["id"], "inactivo", None, actor, "planificacion", None, "Creada")
    return {"id": f["id"]}


def llevar_a_planificacion(con: Any, actor: dict[str, Any], *, archivos: list[str] | None = None, carpetas: list[str] | None = None) -> dict[str, Any]:
    """Takes budgets that already exist (Excel of output/visor, or the groups of a bulk-coordinates batch) to planning: one «inactivo» activity per Excel, with
    the client, ticket, contact, coordinate and total read from the file. `archivos` / `carpetas`: keys relative to output/visor (as pdf_lote.planificar).
    Returns one result per Excel (created, already in planning, or the reason it could not)."""
    exigir_planificacion(actor)
    from visor_rutas import almacen_archivos, pdf_lote, presupuesto_visor
    try:
        plan = pdf_lote.planificar(presupuesto_visor.carpeta_visor().resolve(), [str(a) for a in archivos or []], [str(c) for c in carpetas or []])
    except ValueError as exc:
        raise DatosInvalidos({"archivos": str(exc)}) from None
    resultados = []
    for clave, ruta, _ in plan:
        try:
            if not ruta.is_file():
                almacen_archivos.restaurar("visor", clave, ruta)
            datos = presupuesto_visor.datos_para_planificacion(ruta)
            id_ = crear_actividad(con, actor, origen="visor", presupuesto_clave=clave, **datos)["id"]
            resultados.append({"archivo": ruta.name, "ok": True, "id": id_, "cliente": datos["cliente_nombre"]})
        except DatosInvalidos as exc:
            repetida = "ticket" in (exc.errores or {})
            resultados.append({"archivo": ruta.name, "ok": False, "repetida": repetida, "error": " · ".join((exc.errores or {}).values()) or str(exc)})
        except Exception as exc:                                      # a broken Excel never stops the rest
            resultados.append({"archivo": ruta.name, "ok": False, "repetida": False, "error": f"No se pudo leer el Excel ({type(exc).__name__})"})
    return {"resultados": resultados, "creadas": sum(r["ok"] for r in resultados), "repetidas": sum(r.get("repetida", False) for r in resultados),
            "fallidas": sum(1 for r in resultados if not r["ok"] and not r.get("repetida"))}


def actividades(con: Any, actor: dict[str, Any], *, estado: str | None = None, cuadrilla_id: int | None = None, buscar: str | None = None,
                limite: int = 500) -> dict[str, Any]:
    """Planning: every activity (filter by state, crew or text). A crew: only those of its own crew."""
    condiciones, valores = ["a.borrado_en IS NULL"], []
    if es_planificacion(actor):
        if cuadrilla_id:
            condiciones.append("a.cuadrilla_id = %s")
            valores.append(int(cuadrilla_id))
    else:
        propia = _cuadrilla_de(con, actor) if actor.get("rol") == "tecnico" else None
        if propia is None:
            raise SinPermiso("Su usuario no es de ninguna cuadrilla")
        condiciones.append("a.cuadrilla_id = %s")
        valores.append(propia["id"])
    if estado:
        if estado not in ESTADOS:
            raise DatosInvalidos({"estado": "Estado no válido"})
        condiciones.append("a.estado = %s")
        valores.append(estado)
    if buscar:
        condiciones.append("(a.cliente_nombre ILIKE %s OR a.ticket ILIKE %s OR a.codigo_cliente ILIKE %s)")
        valores += [f"%{buscar}%"] * 3
    filas = con.execute(_SELECT + " WHERE " + " AND ".join(condiciones) + " ORDER BY a.prioridad DESC, a.cola_orden, a.id DESC LIMIT %s", (*valores, max(1, min(int(limite), 2000)))).fetchall()
    controles = _controles(con, [f["id"] for f in filas])
    return {"actividades": [_publica(f, controles[f["id"]]) for f in filas]}


def actividad(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    f = _actividad(con, id)
    _exigir_acceso(con, actor, f)
    detalle = _publica(f, _controles(con, [id])[id])
    detalle["historial"] = [{"de": h["de"], "a": h["a"], "en": _iso(h["en"]), "origen": h["origen"], "motivo": h["motivo"], "por": h["por_nombre"], "cuadrilla": h["cuadrilla"]}
                            for h in con.execute("SELECT h.*, u.nombre AS por_nombre, c.nombre AS cuadrilla FROM redes.plan_actividad_historial h LEFT JOIN redes.usuarios u ON u.id = h.por "
                                                 "LEFT JOIN redes.plan_cuadrillas c ON c.id = h.cuadrilla_id WHERE h.actividad_id = %s ORDER BY h.en, h.id", (id,)).fetchall()]
    return {"actividad": detalle}


def asignar(con: Any, actor: dict[str, Any], *, ids: list[int], cuadrilla_id: int) -> dict[str, Any]:
    """Puts activities at the end of a crew's queue (inactive ones become «asignado»; one already waiting in another crew is moved)."""
    exigir_planificacion(actor)
    c = con.execute("SELECT id, activa FROM redes.plan_cuadrillas WHERE id = %s", (cuadrilla_id,)).fetchone()
    if c is None:
        raise NoEncontrado("La cuadrilla no existe")
    if not c["activa"]:
        raise DatosInvalidos({"cuadrilla_id": "Esa cuadrilla no está activa"})
    for id_ in _ids(ids):
        f = _actividad(con, id_, bloquear=True)
        if f["estado"] not in ("inactivo", "asignado", "en_revision"):
            raise DatosInvalidos({"ids": f"«{f['cliente_nombre']}» está {ETIQUETAS_ESTADO[f['estado']].lower()}: no se puede asignar"})
        orden = con.execute("SELECT COALESCE(max(cola_orden), 0) + 1 AS n FROM redes.plan_actividades WHERE cuadrilla_id = %s AND borrado_en IS NULL", (cuadrilla_id,)).fetchone()["n"]
        con.execute("UPDATE redes.plan_actividades SET cuadrilla_id = %s, estado = 'asignado', cola_orden = %s, asignada_en = now(), iniciada_en = NULL, iniciada_por = NULL, "
                    "motivo_estado = '', actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (cuadrilla_id, orden, actor["id"], id_))
        _historial(con, id_, "asignado", f["estado"], actor, "planificacion", cuadrilla_id)
    return {}


def reordenar_cola(con: Any, actor: dict[str, Any], *, cuadrilla_id: int, ids: list[int]) -> dict[str, Any]:
    """The queue of a crew in the order given (the ids not listed keep going after them)."""
    exigir_planificacion(actor)
    dados = [int(i) for i in ids]
    en_cola = [f["id"] for f in con.execute("SELECT id FROM redes.plan_actividades WHERE cuadrilla_id = %s AND borrado_en IS NULL AND estado IN ('asignado', 'en_revision', 'pausado') "
                                            "ORDER BY cola_orden, id", (cuadrilla_id,)).fetchall()]
    if any(i not in en_cola for i in dados):
        raise DatosInvalidos({"ids": "Hay actividades que no están en la cola de esa cuadrilla"})
    for orden, id_ in enumerate(dados + [i for i in en_cola if i not in dados], 1):
        con.execute("UPDATE redes.plan_actividades SET cola_orden = %s WHERE id = %s", (orden, id_))
    return {}


# --------------------------------------------------------------------------- estados

def _por_hacer(con: Any, id_: int) -> list[str]:
    return [f["etiqueta"] for f in con.execute("SELECT g.etiqueta FROM redes.plan_actividad_control k JOIN redes.plan_control_catalogo g ON g.clave = k.clave "
                                               "WHERE k.actividad_id = %s AND g.obligatorio AND k.estado <> 'hecho' ORDER BY g.orden", (id_,)).fetchall()]


def cambiar_estado(con: Any, actor: dict[str, Any], *, id: int, a: str, motivo: str = "", forzar: bool = False) -> dict[str, Any]:
    """Moves an activity to another state (see TRANSICIONES). A crew only makes the moves of DE_CUADRILLA; planning any of them, and can start an activity
    for a crew that forgot («en_curso» from asignado / en_revision: the time starts to run, marked as started by planning). `forzar`: finish with
    required control points missing (planning only)."""
    if a not in ESTADOS:
        raise DatosInvalidos({"a": "Estado no válido"})
    f = _actividad(con, id, bloquear=True)
    quien = _exigir_acceso(con, actor, f)
    de = f["estado"]
    if a not in TRANSICIONES[de]:
        raise DatosInvalidos({"a": f"Una actividad {ETIQUETAS_ESTADO[de].lower()} no pasa a {ETIQUETAS_ESTADO[a].lower()}"})
    if quien == "cuadrilla" and (de, a) not in DE_CUADRILLA:
        raise SinPermiso("Ese cambio lo hace planificación")
    motivo = _texto(motivo, 500)
    if a in CON_MOTIVO and not motivo:
        raise DatosInvalidos({"motivo": "Escriba el motivo"})
    sets = ["estado = %s", "motivo_estado = %s"]
    valores: list[Any] = [a, motivo if a in CON_MOTIVO else ""]
    if a == "en_curso":
        if de == "pausado":
            sets += ["pausa_total_s = pausa_total_s + EXTRACT(EPOCH FROM now() - pausada_desde)::int", "pausada_desde = NULL"]
        elif de in ("asignado", "en_revision"):
            sets += ["iniciada_en = now()", "iniciada_por = %s"]
            valores.append(quien)
    elif a == "pausado":
        sets.append("pausada_desde = now()")
    elif a == "terminado":
        faltan = _por_hacer(con, id)
        if faltan and not (forzar and quien == "planificacion"):
            raise DatosInvalidos({"controles": "Faltan puntos de control: " + ", ".join(faltan)})
        sets.append("terminada_en = now()")
    elif a == "inactivo":
        sets += ["cuadrilla_id = NULL", "cola_orden = 0", "asignada_en = NULL", "iniciada_en = NULL", "iniciada_por = NULL", "terminada_en = NULL", "pausada_desde = NULL", "pausa_total_s = 0"]
    elif a == "en_revision" and de == "en_curso":
        sets.append("pausada_desde = NULL")
    try:
        con.execute(f"UPDATE redes.plan_actividades SET {', '.join(sets)}, actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s",
                    (*valores, actor["id"], id))
    except psycopg.errors.UniqueViolation:
        raise DatosInvalidos({"a": "La cuadrilla ya tiene una actividad en curso: termínela o pause esa primero"}) from None
    _historial(con, id, a, de, actor, quien, f["cuadrilla_id"], motivo)
    return {}


def marcar_control(con: Any, actor: dict[str, Any], *, id: int, clave: str, estado: str = "hecho", nota: str = "", lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """A control point of an activity («Llegó al lugar», «Inspección hecha»...): pendiente / en_proceso / hecho. A crew marks them while it reviews or works on it;
    planning at any time (while the activity is not finished or cancelled). The place where it was marked is kept when the app sends it."""
    if estado not in ("pendiente", "en_proceso", "hecho"):
        raise DatosInvalidos({"estado": "pendiente, en_proceso o hecho"})
    f = _actividad(con, id, bloquear=True)
    quien = _exigir_acceso(con, actor, f)
    if f["estado"] in ("terminado", "cancelado", "no_viable"):
        raise DatosInvalidos({"estado": f"La actividad está {ETIQUETAS_ESTADO[f['estado']].lower()}"})
    if quien == "cuadrilla" and f["estado"] not in ("en_revision", "en_curso"):
        raise DatosInvalidos({"estado": "Empiece la actividad antes de marcar los puntos de control"})
    if con.execute("SELECT 1 FROM redes.plan_control_catalogo WHERE clave = %s", (clave,)).fetchone() is None:
        raise DatosInvalidos({"clave": "Punto de control desconocido"})
    punto = None
    if lat is not None and lon is not None:
        punto = f"SRID=4326;POINT({_numero(lon, 'lon', LON_MIN, LON_MAX)} {_numero(lat, 'lat', LAT_MIN, LAT_MAX)})"
    con.execute("UPDATE redes.plan_actividad_control SET estado = %s, marcado_en = CASE WHEN %s = 'pendiente' THEN NULL ELSE now() END, "
                "marcado_por = CASE WHEN %s = 'pendiente' THEN NULL ELSE %s END, origen = CASE WHEN %s = 'pendiente' THEN NULL ELSE %s END, ubicacion = %s, nota = %s "
                "WHERE actividad_id = %s AND clave = %s", (estado, estado, estado, actor["id"], estado, quien, punto, _texto(nota, 500), id, clave))
    con.execute("UPDATE redes.plan_actividades SET actualizado_en = now(), actualizado_por = %s WHERE id = %s", (actor["id"], id))          # wakes the NOTIFY
    return {}


# --------------------------------------------------------------------------- la cuadrilla y el tablero

def mi_cuadrilla(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """For the crew app: the crew of the user, what it is doing now and its queue in order."""
    c = _cuadrilla_de(con, actor) if actor.get("rol") == "tecnico" else None
    if c is None:
        raise SinPermiso("Su usuario no es de ninguna cuadrilla: pida a un administrador que lo ponga en una")
    filas = con.execute(_SELECT + " WHERE a.cuadrilla_id = %s AND a.borrado_en IS NULL AND a.estado IN ('asignado', 'en_revision', 'en_curso', 'pausado') "
                        "ORDER BY (a.estado = 'en_curso') DESC, a.prioridad DESC, a.cola_orden, a.id", (c["id"],)).fetchall()
    controles = _controles(con, [f["id"] for f in filas])
    publicas = [_publica(f, controles[f["id"]]) for f in filas]
    empresa = con.execute("SELECT nombre FROM redes.plan_empresas WHERE id = %s", (c["empresa_id"],)).fetchone()["nombre"]
    return {"cuadrilla": {"id": c["id"], "nombre": c["nombre"], "empresa": empresa, "telefono": c["telefono"]},
            "actual": next((p for p in publicas if p["estado"] == "en_curso"), None), "cola": [p for p in publicas if p["estado"] != "en_curso"]}


def tablero(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Planning's summary: how many activities in each state, the average waiting and execution times, and what needs attention."""
    exigir_planificacion(actor)
    por_estado = {e: 0 for e in ESTADOS}
    for f in con.execute("SELECT estado, count(*) AS n FROM redes.plan_actividades WHERE borrado_en IS NULL GROUP BY estado").fetchall():
        por_estado[f["estado"]] = f["n"]
    medias = con.execute(
        "SELECT AVG(EXTRACT(EPOCH FROM iniciada_en - asignada_en))::bigint AS espera_s, "
        "AVG(EXTRACT(EPOCH FROM terminada_en - iniciada_en) - pausa_total_s)::bigint AS ejecucion_s FROM redes.plan_actividades "
        "WHERE borrado_en IS NULL AND iniciada_en IS NOT NULL AND asignada_en IS NOT NULL").fetchone()
    alertas = con.execute(
        "SELECT a.id, a.cliente_nombre, c.nombre AS cuadrilla, EXTRACT(EPOCH FROM now() - a.asignada_en)::bigint AS espera_s FROM redes.plan_actividades a "
        "JOIN redes.plan_cuadrillas c ON c.id = a.cuadrilla_id WHERE a.borrado_en IS NULL AND a.estado IN ('asignado', 'en_revision') "
        "AND a.asignada_en < now() - make_interval(mins => %s) ORDER BY a.asignada_en", (ESPERA_ALERTA_MIN,)).fetchall()
    return {"por_estado": por_estado, "espera_media_s": medias["espera_s"], "ejecucion_media_s": medias["ejecucion_s"],
            "sin_iniciar": [{"id": a["id"], "cliente_nombre": a["cliente_nombre"], "cuadrilla": a["cuadrilla"], "espera_s": a["espera_s"]} for a in alertas],
            "alerta_min": ESPERA_ALERTA_MIN}
