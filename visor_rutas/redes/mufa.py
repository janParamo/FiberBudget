"""Editor de mufa (fase 4): hilos, splitters, conectores y conexiones dentro de una mufa.

Una vista por mufa: los cables que llegan o salen de ella (cada uno con sus hilos), sus
splitters y conectores, y las conexiones entre hilos y puertos. Desde aquí se navega a la mufa
del otro extremo de cada cable.

    cambios = {"posiciones": [{cable_id, x, y}],
               "splitters":  [{id, version?, nombre, salidas, relacion?, conector?, x, y, eliminar?}],
               "conectores": [{id, version?, nombre, tipo?, x, y, eliminar?}],
               "conexiones": [{id, version?, a: extremo, b: extremo, eliminar?}],
               "hilos":      [{id, version, estado, observacion?}],
               "notas":      [{id, version?, html, x, y, ancho?, eliminar?}]}
    extremo = {"hilo": id} | {"splitter": id|"n3", "lado": "entrada"|"salida", "numero": n}
              | {"conector": id|"n4", "lado": "entrada"|"salida"}

Como en el editor de mapa: ids de texto ("n3") = nuevos, una sola transacción, bloqueo
optimista por registro e historial (entidad splitter / conector / conexion / hilo / nota).
"""
from typing import Any

from visor_rutas.redes import bandejas, proyectos, repositorio, texto
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

SALIDAS = (2, 4, 8, 16, 32)
ESTADOS = ("activo", "oscura", "baja", "reservado", "danado")
NOMBRE_ESTADO = {"activo": "activo", "oscura": "fibra oscura", "baja": "cliente de baja", "reservado": "reservado",
                 "danado": "dañado"}


# --------------------------------------------------------------------------- lectura

def _mufa(con: Any, mufa_id: int) -> dict[str, Any]:
    fila = con.execute("SELECT id, proyecto_id, tipo, subtipo, nombre, codigo, propiedades, fuente, confianza, estado_migracion, "
                       "ref_visio ->> 'nombre_visio' AS nombre_visio, version FROM redes.elementos "
                       "WHERE id = %s AND borrado_en IS NULL", (int(mufa_id),)).fetchone()
    if fila is None or fila["tipo"] not in ("mufa", "nodo", "odf"):
        raise NoEncontrado("La mufa no existe (o fue eliminada)")
    return dict(fila)


def _describir_extremo(con: Any, hilo_id: int, mufa_id: int) -> str | None:
    """What fibre `hilo_id` is connected to inside mufa `mufa_id` (None: nothing)."""
    c = con.execute("SELECT * FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL "
                    "AND (a_hilo_id = %s OR b_hilo_id = %s) LIMIT 1", (mufa_id, hilo_id, hilo_id)).fetchone()
    if c is None:
        return None
    otro_hilo, otro_puerto = (c["b_hilo_id"], c["b_puerto_id"]) if c["a_hilo_id"] == hilo_id else (c["a_hilo_id"], c["a_puerto_id"])
    return _texto_extremo(con, otro_hilo, otro_puerto)


def _texto_extremo(con: Any, hilo_id: int | None, puerto_id: int | None) -> str:
    if hilo_id is not None:
        f = con.execute("SELECT h.numero, c.nombre FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE h.id = %s",
                        (hilo_id,)).fetchone()
        return f"fusión con {f['nombre']} hilo {f['numero']}"
    p = con.execute("SELECT p.lado, p.numero, s.nombre AS splitter, k.nombre AS conector FROM redes.puertos p "
                    "LEFT JOIN redes.splitters s ON s.id = p.splitter_id LEFT JOIN redes.conectores k ON k.id = p.conector_id "
                    "WHERE p.id = %s", (puerto_id,)).fetchone()
    if p["splitter"]:
        puerto = "entrada" if p["lado"] == "entrada" else f"salida {p['numero']}"
        return f"{p['splitter']} · {puerto}"
    return f"conector {p['conector']}"


def _ref_puerto(con: Any, puerto_id: int) -> dict[str, Any]:
    p = con.execute("SELECT splitter_id, conector_id, lado, numero FROM redes.puertos WHERE id = %s", (puerto_id,)).fetchone()
    if p["splitter_id"] is not None:
        return {"splitter": p["splitter_id"], "lado": p["lado"], "numero": p["numero"]}
    return {"conector": p["conector_id"], "lado": p["lado"]}


def leer(con: Any, actor: dict[str, Any], *, mufa_id: int) -> dict[str, Any]:
    """Everything the mufa editor draws."""
    m = _mufa(con, mufa_id)
    if not proyectos.puede_ver(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    proyecto = con.execute("SELECT id, codigo, nombre FROM redes.proyectos WHERE id = %s", (m["proyecto_id"],)).fetchone()
    posiciones = {f["cable_id"]: (f["x"], f["y"], f["version"]) for f in con.execute(
        "SELECT cable_id, x, y, version FROM redes.mufa_cables WHERE mufa_id = %s", (m["id"],)).fetchall()}
    cables = []
    for c in con.execute(
            "SELECT c.*, o.nombre AS o_nombre, o.tipo AS o_tipo, o.subtipo AS o_subtipo, d.nombre AS d_nombre, d.tipo AS d_tipo, "
            "d.subtipo AS d_subtipo FROM redes.cables c JOIN redes.elementos o ON o.id = c.origen_id "
            "JOIN redes.elementos d ON d.id = c.destino_id WHERE c.borrado_en IS NULL AND (c.origen_id = %(m)s OR c.destino_id = %(m)s) "
            "ORDER BY c.id", {"m": m["id"]}).fetchall():
        llega = c["destino_id"] == m["id"]
        otro_id = c["origen_id"] if llega else c["destino_id"]
        pre = "o_" if llega else "d_"
        fibras = []
        for h in con.execute("SELECT id, numero, buffer, color, color_buffer, estado, observacion, version FROM redes.hilos "
                             "WHERE cable_id = %s AND borrado_en IS NULL ORDER BY numero", (c["id"],)).fetchall():
            fibras.append({**h, "lejos": _describir_extremo(con, h["id"], otro_id) if c[pre + "tipo"] in ("mufa", "nodo", "odf") else None})
        x, y, pos_version = posiciones.get(c["id"], (None, None, None))
        cables.append({"id": c["id"], "nombre": c["nombre"], "clase": c["clase"], "tipo": c["tipo"], "hilos": c["hilos"],
                       "hilos_por_buffer": c["hilos_por_buffer"], "color": c["color"], "longitud_m": float(c["longitud_m"]),
                       "metraje": c["metraje"], "lado": "entrada" if llega else "salida", "version": c["version"],
                       "origen": {"id": c["origen_id"], "nombre": c["o_nombre"], "tipo": c["o_tipo"], "subtipo": c["o_subtipo"]},
                       "destino": {"id": c["destino_id"], "nombre": c["d_nombre"], "tipo": c["d_tipo"], "subtipo": c["d_subtipo"]},
                       "otro": {"id": otro_id, "nombre": c[pre + "nombre"], "tipo": c[pre + "tipo"], "subtipo": c[pre + "subtipo"]},
                       "x": x, "y": y, "pos_version": pos_version, "fibras": fibras})
    servicios: dict[int, dict[int, dict[str, Any]]] = {}
    for f in con.execute(
            "SELECT p.splitter_id, p.numero, x.codigo_cliente, x.nombre, x.id_servicio, x.elemento_id, x.fuente FROM redes.puerto_servicios x "
            "JOIN redes.puertos p ON p.id = x.puerto_id JOIN redes.splitters s ON s.id = p.splitter_id "
            "WHERE s.mufa_id = %s AND s.borrado_en IS NULL AND x.borrado_en IS NULL", (m["id"],)).fetchall():
        servicios.setdefault(f["splitter_id"], {})[f["numero"]] = {k: f[k] for k in ("codigo_cliente", "nombre", "id_servicio", "elemento_id", "fuente")}
    splitters = [dict(s) | {"puertos": _puertos(con, splitter_id=s["id"]), "servicios": servicios.get(s["id"], {}),
                            "propiedades": s["propiedades"] or {}} for s in con.execute(
        "SELECT id, nombre, salidas, relacion, conector, x, y, propiedades, fuente, confianza, version FROM redes.splitters "
        "WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY id", (m["id"],)).fetchall()]
    clientes = [dict(f) for f in con.execute(
        "SELECT codigo_cliente, nombre, id_servicio, elemento_id, fuente FROM redes.mufa_clientes WHERE mufa_id = %s AND borrado_en IS NULL "
        "ORDER BY codigo_cliente NULLS LAST, nombre", (m["id"],)).fetchall()]
    conectores = [dict(k) for k in con.execute(
        "SELECT id, nombre, tipo, x, y, version FROM redes.conectores WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY id",
        (m["id"],)).fetchall()]
    conexiones = []
    for x in con.execute("SELECT * FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY id", (m["id"],)).fetchall():
        conexiones.append({"id": x["id"], "version": x["version"], "fuente": x["fuente"], "confianza": x["confianza"],
                           "bandeja": x["bandeja"], "posicion": x["posicion_en_bandeja"], "posicion_estimada": x["posicion_estimada"],
                           "a": {"hilo": x["a_hilo_id"]} if x["a_hilo_id"] else _ref_puerto(con, x["a_puerto_id"]),
                           "b": {"hilo": x["b_hilo_id"]} if x["b_hilo_id"] else _ref_puerto(con, x["b_puerto_id"])})
    notas = [dict(n) for n in con.execute(
        "SELECT id, html, x, y, ancho, version FROM redes.notas WHERE mufa_id = %s AND contexto = 'mufa' AND borrado_en IS NULL "
        "ORDER BY id", (m["id"],)).fetchall()]
    return {"proyecto": dict(proyecto), "mufa": {**{k: m[k] for k in ("id", "tipo", "subtipo", "nombre", "codigo", "fuente", "confianza",
                                                                      "estado_migracion", "nombre_visio", "version")},
                                                 "propiedades": m["propiedades"] or {},
                                                 "puede_editar": proyectos.puede_editar(con, actor, m["proyecto_id"])},
            "cables": cables, "splitters": splitters, "conectores": conectores, "conexiones": conexiones, "notas": notas,
            "clientes": clientes, **bandejas.leer(con, m["id"])}


def _puertos(con: Any, *, splitter_id: int | None = None, conector_id: int | None = None) -> dict[str, list[int]]:
    filas = con.execute("SELECT lado, numero FROM redes.puertos WHERE splitter_id IS NOT DISTINCT FROM %s "
                        "AND conector_id IS NOT DISTINCT FROM %s ORDER BY lado, numero", (splitter_id, conector_id)).fetchall()
    return {"entrada": [f["numero"] for f in filas if f["lado"] == "entrada"],
            "salida": [f["numero"] for f in filas if f["lado"] == "salida"]}


# --------------------------------------------------------------------------- escritura

def _crear_puertos(con: Any, *, splitter_id: int | None = None, conector_id: int | None = None, salidas: int = 1) -> None:
    con.execute("INSERT INTO redes.puertos (splitter_id, conector_id, lado, numero) VALUES (%s, %s, 'entrada', 1) "
                "ON CONFLICT DO NOTHING", (splitter_id, conector_id))
    for n in range(1, salidas + 1):
        con.execute("INSERT INTO redes.puertos (splitter_id, conector_id, lado, numero) VALUES (%s, %s, 'salida', %s) "
                    "ON CONFLICT DO NOTHING", (splitter_id, conector_id, n))


def _texto_corto(valor: Any, maximo: int) -> str | None:
    t = " ".join(str(valor or "").split())
    return t[:maximo] or None


def _numero(valor: Any, quien: str, campo: str) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({quien: f"{campo} no válido"}) from None
    if not -1e6 < n < 1e6:
        raise DatosInvalidos({quien: f"{campo} fuera de rango"})
    return n


def _es_nuevo(ref: Any) -> bool:
    return isinstance(ref, str) and not ref.lstrip("-").isdigit()


def _actualizar(con: Any, tabla: str, id_: int, d: dict[str, Any], valores: dict[str, Any], actor: dict[str, Any],
                quien: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return repositorio.actualizar(con, tabla, id_, int(d.get("version") or 0), valores, actor["id"])
    except ConflictoVersion:
        raise ConflictoVersion(f"{quien}: otro usuario lo cambió mientras usted editaba. Recargue la mufa.") from None


def _propio(con: Any, tabla: str, id_: int, mufa_id: int, quien: str) -> dict[str, Any]:
    fila = repositorio.obtener(con, tabla, int(id_), bloquear=True)
    if fila.get("mufa_id") != mufa_id or fila["borrado_en"] is not None:
        raise ConflictoVersion(f"{quien}: ya no existe en esta mufa. Recargue la mufa.")
    return fila


def quitar_conexiones(con: Any, condicion: str, parametros: tuple, usuario_id: int, proyecto_id: int, motivo: str) -> int:
    """Soft-deletes the active connections matching `condicion` (history: one entry each)."""
    filas = con.execute(f"UPDATE redes.conexiones SET borrado_en = now(), actualizado_en = now(), actualizado_por = %s, "
                        f"version = version + 1 WHERE borrado_en IS NULL AND ({condicion}) RETURNING id",
                        (usuario_id, *parametros)).fetchall()
    for f in filas:
        repositorio.registrar(con, usuario_id, "conexion", f["id"], "eliminar", {"motivo": [None, motivo]}, proyecto_id=proyecto_id)
    return len(filas)


def guardar(con: Any, actor: dict[str, Any], *, mufa_id: int, cambios: dict[str, Any]) -> dict[str, Any]:
    """Applies the mufa editor's changes in one transaction; returns leer() + {"ids": {...}}."""
    m = _mufa(con, mufa_id)
    if not proyectos.puede_editar(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    proyecto_id, mid = m["proyecto_id"], m["id"]
    cambios = cambios if isinstance(cambios, dict) else {}
    lista = lambda k: [c for c in (cambios.get(k) or []) if isinstance(c, dict)]
    ids: dict[str, int] = {}
    reglas_bandejas = bandejas.reglas()
    with con.transaction():
        con.execute("SELECT 1 FROM redes.elementos WHERE id = %s FOR UPDATE", (mid,))
        cables_aqui = {f["id"] for f in con.execute(
            "SELECT id FROM redes.cables WHERE borrado_en IS NULL AND (origen_id = %(m)s OR destino_id = %(m)s)", {"m": mid}).fetchall()}
        # 1) positions of the cables in this mufa's canvas (optimistic lock: the version read with leer())
        for p in lista("posiciones"):
            cid = int(p.get("cable_id") or 0)
            if cid not in cables_aqui:
                continue
            x, y = _numero(p.get("x"), "Cable", "x"), _numero(p.get("y"), "Cable", "y")
            fila = con.execute("SELECT version FROM redes.mufa_cables WHERE mufa_id = %s AND cable_id = %s FOR UPDATE", (mid, cid)).fetchone()
            if fila is None:
                con.execute("INSERT INTO redes.mufa_cables (mufa_id, cable_id, x, y) VALUES (%s, %s, %s, %s)", (mid, cid, x, y))
                continue
            if p.get("version") is None or int(p["version"]) != fila["version"]:
                nombre = con.execute("SELECT nombre FROM redes.cables WHERE id = %s", (cid,)).fetchone()["nombre"]
                raise ConflictoVersion(f"Otro usuario movió el cable {nombre} en esta mufa mientras usted editaba. Recargue la mufa.")
            con.execute("UPDATE redes.mufa_cables SET x = %s, y = %s, version = version + 1 WHERE mufa_id = %s AND cable_id = %s",
                        (x, y, mid, cid))
        # 2) splitters and connectors (create / edit / delete with their connections)
        for tabla, entidad in (("splitters", "splitter"), ("conectores", "conector")):
            for d in lista(tabla):
                quien = f"{'Splitter' if tabla == 'splitters' else 'Conector'} {_texto_corto(d.get('nombre'), 60) or d.get('id')}"
                if d.get("eliminar"):
                    if _es_nuevo(d.get("id")):
                        continue
                    actual = _propio(con, tabla, int(d["id"]), mid, quien)
                    columna = "splitter_id" if tabla == "splitters" else "conector_id"
                    quitar_conexiones(con, f"a_puerto_id IN (SELECT id FROM redes.puertos WHERE {columna} = %s) OR "
                                           f"b_puerto_id IN (SELECT id FROM redes.puertos WHERE {columna} = %s)",
                                      (actual["id"], actual["id"]), actor["id"], proyecto_id, f"{entidad} eliminado")
                    if tabla == "splitters":
                        bandejas.liberar_splitter(con, actual["id"], reglas_bandejas)
                    ahora = con.execute("SELECT now() AS n").fetchone()["n"]
                    _actualizar(con, tabla, actual["id"], d, {"borrado_en": ahora}, actor, quien)
                    repositorio.registrar(con, actor["id"], entidad, actual["id"], "eliminar", {"nombre": [actual["nombre"], None]},
                                          proyecto_id=proyecto_id)
                    continue
                nombre = _texto_corto(d.get("nombre"), 120)
                if not nombre:
                    raise DatosInvalidos({quien: "falta el nombre"})
                valores: dict[str, Any] = {"nombre": nombre, "x": _numero(d.get("x", 0), quien, "x"), "y": _numero(d.get("y", 0), quien, "y")}
                if tabla == "splitters":
                    try:
                        salidas = int(d.get("salidas") or 0)
                    except (TypeError, ValueError):
                        salidas = 0
                    if salidas not in SALIDAS:
                        raise DatosInvalidos({quien: "salidas: 2, 4, 8, 16 o 32"})
                    relacion = _texto_corto(d.get("relacion"), 5)
                    if relacion:
                        partes = relacion.split("/")
                        if salidas != 2 or len(partes) != 2 or not all(x.isdigit() for x in partes) or sum(map(int, partes)) != 100:
                            raise DatosInvalidos({quien: "la relación desbalanceada es solo para 1x2 y debe sumar 100 (70/30)"})
                    valores.update(salidas=salidas, relacion=relacion, conector=_texto_corto(d.get("conector"), 20))
                else:
                    valores["tipo"] = _texto_corto(d.get("tipo"), 40)
                if _es_nuevo(d.get("id")):
                    origen = {"fuente": "usuario", "confianza": "verificada"} if tabla == "splitters" else {}   # a person drew it
                    fila = repositorio.insertar(con, tabla, {**valores, **origen, "proyecto_id": proyecto_id, "mufa_id": mid}, actor["id"])
                    ids[str(d["id"])] = fila["id"]
                    if tabla == "splitters":
                        _crear_puertos(con, splitter_id=fila["id"], salidas=valores["salidas"])
                    else:
                        _crear_puertos(con, conector_id=fila["id"], salidas=1)
                    repositorio.registrar(con, actor["id"], entidad, fila["id"], "crear",
                                          repositorio.diferencias(None, {k: v for k, v in valores.items() if k not in ("x", "y")}),
                                          proyecto_id=proyecto_id)
                else:
                    actual = _propio(con, tabla, int(d["id"]), mid, quien)
                    if tabla == "splitters" and valores["salidas"] < actual["salidas"]:
                        usadas = con.execute(
                            "SELECT p.numero FROM redes.puertos p JOIN redes.conexiones c ON c.borrado_en IS NULL "
                            "AND (c.a_puerto_id = p.id OR c.b_puerto_id = p.id) WHERE p.splitter_id = %s AND p.lado = 'salida' "
                            "AND p.numero > %s", (actual["id"], valores["salidas"])).fetchall()
                        if usadas:
                            raise DatosInvalidos({quien: "tiene conectadas las salidas " + ", ".join(str(u["numero"]) for u in usadas)
                                                         + ": quite esas conexiones antes de reducirlo"})
                    antes, despues = _actualizar(con, tabla, actual["id"], d, valores, actor, quien)
                    if tabla == "splitters":
                        _crear_puertos(con, splitter_id=actual["id"], salidas=valores["salidas"])
                    cambio = repositorio.diferencias({k: antes[k] for k in valores if k not in ("x", "y")},
                                                     {k: despues[k] for k in valores if k not in ("x", "y")})
                    if cambio:
                        repositorio.registrar(con, actor["id"], entidad, actual["id"], "editar", cambio, proyecto_id=proyecto_id)

        def real(ref: Any) -> int:
            if _es_nuevo(ref):
                if ref not in ids:
                    raise DatosInvalidos({"conexion": f"se refiere a un splitter o conector que no viene en el envío ({ref})"})
                return ids[ref]
            return int(ref)

        def extremo(e: Any, quien: str) -> tuple[int | None, int | None, str]:
            """(hilo_id, puerto_id, key) of an end, checked against this mufa."""
            e = e if isinstance(e, dict) else {}
            if e.get("hilo") is not None:
                h = con.execute("SELECT h.id, h.cable_id, h.numero, c.nombre FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id "
                                "WHERE h.id = %s AND h.borrado_en IS NULL", (int(e["hilo"]),)).fetchone()
                if h is None or h["cable_id"] not in cables_aqui:
                    raise DatosInvalidos({quien: "un hilo no pertenece a un cable de esta mufa"})
                return h["id"], None, f"hilo:{h['id']}"
            columna, objeto = ("splitter_id", e.get("splitter")) if e.get("splitter") is not None else ("conector_id", e.get("conector"))
            if objeto is None:
                raise DatosInvalidos({quien: "extremo de conexión no válido"})
            oid = real(objeto)
            tabla = "splitters" if columna == "splitter_id" else "conectores"
            if con.execute(f"SELECT 1 FROM redes.{tabla} WHERE id = %s AND mufa_id = %s AND borrado_en IS NULL", (oid, mid)).fetchone() is None:
                raise DatosInvalidos({quien: "un splitter o conector no está en esta mufa"})
            lado = e.get("lado") if e.get("lado") in ("entrada", "salida") else None
            numero = int(e.get("numero") or 1)
            p = con.execute(f"SELECT id FROM redes.puertos WHERE {columna} = %s AND lado = %s AND numero = %s", (oid, lado, numero)).fetchone()
            if p is None:
                raise DatosInvalidos({quien: f"el puerto {lado or '?'} {numero} no existe"})
            return None, p["id"], f"{columna}:{oid}"

        # 3) connections: deletes first (they free their ends), then the new ones
        for d in lista("conexiones"):
            if d.get("eliminar") and not _es_nuevo(d.get("id")):
                actual = _propio(con, "conexiones", int(d["id"]), mid, "Conexión")
                ahora = con.execute("SELECT now() AS n").fetchone()["n"]
                _actualizar(con, "conexiones", actual["id"], d, {"borrado_en": ahora}, actor, "Conexión")
                repositorio.registrar(con, actor["id"], "conexion", actual["id"], "eliminar", None, proyecto_id=proyecto_id)
        for d in lista("conexiones"):
            if d.get("eliminar") or not _es_nuevo(d.get("id")):
                continue
            quien = "Conexión"
            a_hilo, a_puerto, a_objeto = extremo(d.get("a"), quien)
            b_hilo, b_puerto, b_objeto = extremo(d.get("b"), quien)
            if a_objeto == b_objeto:
                raise DatosInvalidos({quien: "no se puede conectar un elemento consigo mismo"})
            if a_hilo and b_hilo:
                cables = con.execute("SELECT count(DISTINCT cable_id) AS n FROM redes.hilos WHERE id IN (%s, %s)", (a_hilo, b_hilo)).fetchone()["n"]
                if cables < 2:
                    raise DatosInvalidos({quien: "una fusión une hilos de cables distintos"})
            for hilo in (a_hilo, b_hilo):
                if hilo and con.execute("SELECT 1 FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL "
                                        "AND (a_hilo_id = %s OR b_hilo_id = %s)", (mid, hilo, hilo)).fetchone():
                    raise DatosInvalidos({quien: "ese hilo ya está conectado en esta mufa: quite primero su conexión"})
            for puerto in (a_puerto, b_puerto):
                if puerto and con.execute("SELECT 1 FROM redes.conexiones WHERE borrado_en IS NULL AND (a_puerto_id = %s OR b_puerto_id = %s)",
                                          (puerto, puerto)).fetchone():
                    raise DatosInvalidos({quien: "ese puerto ya está conectado: quite primero su conexión"})
            fila = repositorio.insertar(con, "conexiones", {"proyecto_id": proyecto_id, "mufa_id": mid, "a_hilo_id": a_hilo,
                                                            "a_puerto_id": a_puerto, "b_hilo_id": b_hilo, "b_puerto_id": b_puerto,
                                                            "fuente": "usuario", "confianza": "verificada"}, actor["id"])
            ids[str(d["id"])] = fila["id"]
            repositorio.registrar(con, actor["id"], "conexion", fila["id"], "crear",
                                  {"a": [None, _texto_extremo(con, a_hilo, a_puerto)], "b": [None, _texto_extremo(con, b_hilo, b_puerto)]},
                                  proyecto_id=proyecto_id)
        # 4) fibre states
        for d in lista("hilos"):
            estado = d.get("estado")
            if estado not in ESTADOS:
                raise DatosInvalidos({"hilo": "estado no válido"})
            actual = repositorio.obtener(con, "hilos", int(d.get("id") or 0), bloquear=True)
            if actual["cable_id"] not in cables_aqui or actual["borrado_en"] is not None:
                raise DatosInvalidos({"hilo": "el hilo no es de un cable de esta mufa"})
            valores = {"estado": estado, "observacion": _texto_corto(d.get("observacion"), 300)}
            antes, despues = _actualizar(con, "hilos", actual["id"], d, valores, actor, f"Hilo {actual['numero']}")
            repositorio.registrar(con, actor["id"], "hilo", actual["id"], "editar",
                                  repositorio.diferencias({k: antes[k] for k in valores}, {k: despues[k] for k in valores}),
                                  proyecto_id=proyecto_id)
        # 5) notes inside the canvas
        for d in lista("notas"):
            if d.get("eliminar"):
                if not _es_nuevo(d.get("id")):
                    actual = _propio(con, "notas", int(d["id"]), mid, "Nota")
                    ahora = con.execute("SELECT now() AS n").fetchone()["n"]
                    _actualizar(con, "notas", actual["id"], d, {"borrado_en": ahora}, actor, "Nota")
                    repositorio.registrar(con, actor["id"], "nota", actual["id"], "eliminar", None, proyecto_id=proyecto_id)
                continue
            html = texto.limpiar_html(d.get("html"))
            if not html:
                raise DatosInvalidos({"Nota": "la nota está vacía"})
            try:
                ancho = max(80, min(1200, int(d.get("ancho") or 220)))
            except (TypeError, ValueError):
                ancho = 220
            valores = {"html": html, "x": _numero(d.get("x", 0), "Nota", "x"), "y": _numero(d.get("y", 0), "Nota", "y"), "ancho": ancho}
            if _es_nuevo(d.get("id")):
                fila = repositorio.insertar(con, "notas", {**valores, "proyecto_id": proyecto_id, "contexto": "mufa", "mufa_id": mid}, actor["id"])
                ids[str(d["id"])] = fila["id"]
                repositorio.registrar(con, actor["id"], "nota", fila["id"], "crear", {"html": [None, html[:300]]}, proyecto_id=proyecto_id)
            else:
                actual = _propio(con, "notas", int(d["id"]), mid, "Nota")
                _actualizar(con, "notas", actual["id"], d, valores, actor, "Nota")
        # 6) a migrated mufa that a person changes is "editada": a re-import never overwrites it
        if any(lista(k) for k in ("splitters", "conectores", "conexiones", "hilos", "notas")):
            con.execute("UPDATE redes.elementos SET estado_migracion = 'editada' WHERE id = %s AND estado_migracion IN ('automatica', 'en_revision')",
                        (mid,))
        # 7) a mufa with a model: new splitters get a tray and new splices a position (estimated)
        if con.execute("SELECT 1 FROM redes.mufa_modelos WHERE mufa_id = %s AND borrado_en IS NULL", (mid,)).fetchone():
            bandejas.ubicar_splitters(con, mid, reglas_bandejas)
            bandejas.ubicar_empalmes(con, mid, reglas_bandejas)
    return {**leer(con, actor, mufa_id=mid), "ids": ids}


# --------------------------------------------------------------------------- hilos de los cables (desde red.py)

def sincronizar_hilos(con: Any, cable_id: int, hilos: int | None, usuario_id: int) -> None:
    """The cable has fibres 1..hilos: missing ones are created, extra ones are removed (logical
    delete) unless they are connected somewhere. Unknown count (None, migrated cables): untouched."""
    if hilos is None:
        return
    actuales = {f["numero"]: f["id"] for f in con.execute(
        "SELECT id, numero FROM redes.hilos WHERE cable_id = %s AND borrado_en IS NULL", (cable_id,)).fetchall()}
    sobran = [i for n, i in actuales.items() if n > hilos]
    if sobran:
        usados = con.execute("SELECT DISTINCT h.numero FROM redes.hilos h JOIN redes.conexiones c ON c.borrado_en IS NULL "
                             "AND (c.a_hilo_id = h.id OR c.b_hilo_id = h.id) WHERE h.id = ANY(%s) ORDER BY h.numero", (sobran,)).fetchall()
        if usados:
            raise DatosInvalidos({"cable": "no se puede reducir la cantidad de hilos: están conectados los hilos "
                                           + ", ".join(str(u["numero"]) for u in usados[:10])})
        con.execute("UPDATE redes.hilos SET borrado_en = now(), version = version + 1, actualizado_por = %s WHERE id = ANY(%s)",
                    (usuario_id, sobran))
    faltan = [n for n in range(1, hilos + 1) if n not in actuales]
    if faltan:
        con.execute("INSERT INTO redes.hilos (cable_id, numero, creado_por) SELECT %s, g, %s FROM unnest(%s::int[]) AS g",
                    (cable_id, usuario_id, faltan))
