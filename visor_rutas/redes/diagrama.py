"""Diagrama lógico de red (fase 6): se genera automáticamente de las conexiones guardadas.

Desde el elemento elegido (nodo / OLT, mufa, o un splitter dentro de una mufa) se sigue la red
"hacia adelante": los cables que SALEN de cada caja (origen = la caja, como se dibujaron en el
mapa), caja por caja, sin volver a una caja ya puesta. Cada caja (OLT, SC = mufa de empalme,
FDT = distribución, FAT = terminal) lleva sus splitters y conectores y las líneas internas de sus
conexiones (cuántos hilos van de la entrada a cada splitter y de cada splitter a cada salida).
Los clientes se incluyen solo si se pide ("incluir inmuebles / clientes"); si no, la caja dice
cuántos tiene. Si se arranca en un splitter, en esa primera caja solo se siguen los cables que
salen de ese splitter.

Los diagramas guardados (tabla diagramas_logicos) solo guardan cómo generarlo (inicio, dirección,
clientes): el dibujo siempre refleja las conexiones actuales. La posición de cada caja se calcula
en la página (web/redes/diagrama.js).
"""
from typing import Any

from visor_rutas.redes import proyectos, repositorio
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

# cable colour by fibre count (legend "Cable de 144 hilos" red, "de 48 hilos" purple); configurable
# in business_rules.yaml, section diagrama_logico.colores_capacidad
COLORES_POR_DEFECTO = {144: "#e53935", 96: "#fb8c00", 72: "#1e88e5", 48: "#8e24aa", 24: "#43a047", 12: "#00acc1"}
SIMBOLO = {"nodo": "olt", "odf": "olt", "cliente": "cliente"}
SIMBOLO_MUFA = {"empalme": "sc", "distribucion": "fdt", "terminal": "fat"}
NOMBRE_SIMBOLO = {"olt": "OLT / nodo", "sc": "SC (mufa de empalme)", "fdt": "FDT (distribución)", "fat": "FAT (terminal)",
                  "derivacion": "Derivación", "cliente": "Cliente"}
MAX_CAJAS = 500


def colores_capacidad() -> dict[int, str]:
    try:
        from config import get_settings, load_rules
        datos = (load_rules(get_settings().rules_path) or {}).get("diagrama_logico") or {}
        colores = {int(k): str(v) for k, v in (datos.get("colores_capacidad") or {}).items()}
        return colores or dict(COLORES_POR_DEFECTO)
    except Exception:                       # settings not available (tests): the defaults
        return dict(COLORES_POR_DEFECTO)


COLOR_DESCONOCIDO = "#9e9e9e"          # migrated cable whose fibre count is unknown


def color_de(hilos: int | None, colores: dict[int, str]) -> str:
    """Exact count, else the next larger configured capacity, else the largest (grey if unknown)."""
    if hilos is None:
        return COLOR_DESCONOCIDO
    for capacidad in sorted(colores):
        if hilos <= capacidad:
            return colores[capacidad]
    return colores[max(colores)]


def _simbolo(e: dict[str, Any]) -> str:
    if e["tipo"] == "mufa":
        return SIMBOLO_MUFA.get(e["subtipo"] or "", "sc")
    return SIMBOLO.get(e["tipo"], "sc")


# --------------------------------------------------------------------------- diagramas guardados

def _proyecto(con: Any, actor: dict[str, Any], proyecto_id: int) -> dict[str, Any]:
    p = con.execute("SELECT id, codigo, nombre FROM redes.proyectos WHERE id = %s AND borrado_en IS NULL", (int(proyecto_id),)).fetchone()
    if p is None:
        raise NoEncontrado("El proyecto no existe (o fue eliminado)")
    if not proyectos.puede_ver(con, actor, p["id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    return dict(p)


def _inicios(con: Any, proyecto_id: int) -> list[dict[str, Any]]:
    """Possible start points: nodes / OLTs, mufas and splitters of the project."""
    salida = [{"clave": f"e:{e['id']}", "texto": f"{e['nombre']} ({NOMBRE_SIMBOLO[_simbolo(e)].split(' (')[0]})", "caja": e["nombre"]}
              for e in con.execute("SELECT id, tipo, subtipo, nombre FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL "
                                   "AND tipo IN ('nodo', 'mufa') ORDER BY tipo DESC, nombre", (proyecto_id,)).fetchall()]
    salida += [{"clave": f"s:{s['id']}", "texto": f"{s['nombre']} (1x{s['salidas']}{' ' + s['relacion'] if s['relacion'] else ''}) · {s['mufa']}",
                "caja": s["mufa"]}
               for s in con.execute("SELECT s.id, s.nombre, s.salidas, s.relacion, e.nombre AS mufa FROM redes.splitters s "
                                    "JOIN redes.elementos e ON e.id = s.mufa_id WHERE s.proyecto_id = %s AND s.borrado_en IS NULL "
                                    "AND e.borrado_en IS NULL ORDER BY e.nombre, s.nombre", (proyecto_id,)).fetchall()]
    return salida


def listar(con: Any, actor: dict[str, Any], *, proyecto_id: int) -> dict[str, Any]:
    p = _proyecto(con, actor, proyecto_id)
    filas = con.execute(
        "SELECT d.*, e.nombre AS e_nombre, e.borrado_en AS e_borrado, s.nombre AS s_nombre, s.borrado_en AS s_borrado, "
        "m.nombre AS m_nombre FROM redes.diagramas_logicos d LEFT JOIN redes.elementos e ON e.id = d.elemento_id "
        "LEFT JOIN redes.splitters s ON s.id = d.splitter_id LEFT JOIN redes.elementos m ON m.id = s.mufa_id "
        "WHERE d.proyecto_id = %s AND d.borrado_en IS NULL ORDER BY d.id", (p["id"],)).fetchall()
    diagramas = []
    for d in filas:
        if d["splitter_id"]:
            elemento, caja, borrado = d["s_nombre"], d["m_nombre"], d["s_borrado"] is not None
        else:
            elemento, caja, borrado = d["e_nombre"], d["e_nombre"], d["e_borrado"] is not None
        diagramas.append({"id": d["id"], "version": d["version"], "titulo": d["titulo"],
                          "inicio": f"s:{d['splitter_id']}" if d["splitter_id"] else f"e:{d['elemento_id']}",
                          "elemento": elemento, "caja": caja, "inicio_eliminado": borrado,
                          "direccion": d["direccion"], "incluir_clientes": d["incluir_clientes"]})
    return {"proyecto": {**p, "puede_editar": proyectos.puede_editar(con, actor, p["id"])}, "diagramas": diagramas,
            "inicios": _inicios(con, p["id"])}


def _leer_inicio(con: Any, proyecto_id: int, inicio: Any) -> tuple[int | None, int | None]:
    """'e:12' / 's:5' -> (elemento_id, splitter_id), checked against the project."""
    tipo, _, valor = str(inicio or "").partition(":")
    if tipo not in ("e", "s") or not valor.isdigit():
        raise DatosInvalidos({"inicio": "elija el elemento de inicio"})
    if tipo == "e":
        e = con.execute("SELECT tipo FROM redes.elementos WHERE id = %s AND proyecto_id = %s AND borrado_en IS NULL",
                        (int(valor), proyecto_id)).fetchone()
        if e is None or e["tipo"] not in ("nodo", "odf", "mufa"):
            raise DatosInvalidos({"inicio": "el inicio debe ser un nodo / OLT, una mufa o un splitter del proyecto"})
        return int(valor), None
    if con.execute("SELECT 1 FROM redes.splitters WHERE id = %s AND proyecto_id = %s AND borrado_en IS NULL",
                   (int(valor), proyecto_id)).fetchone() is None:
        raise DatosInvalidos({"inicio": "el splitter no existe en este proyecto"})
    return None, int(valor)


def guardar(con: Any, actor: dict[str, Any], *, proyecto_id: int, datos: dict[str, Any]) -> dict[str, Any]:
    p = _proyecto(con, actor, proyecto_id)
    if not proyectos.puede_editar(con, actor, p["id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    datos = datos if isinstance(datos, dict) else {}
    titulo = " ".join(str(datos.get("titulo") or "").split())[:120]
    errores = {} if titulo else {"titulo": "el título es obligatorio"}
    direccion = datos.get("direccion") or "derecha"
    if direccion not in ("derecha", "izquierda"):
        errores["direccion"] = "derecha o izquierda"
    try:
        elemento_id, splitter_id = _leer_inicio(con, p["id"], datos.get("inicio"))
    except DatosInvalidos as exc:
        errores.update(exc.errores)
    if errores:
        raise DatosInvalidos(errores)
    valores = {"titulo": titulo, "elemento_id": elemento_id, "splitter_id": splitter_id, "direccion": direccion,
               "incluir_clientes": bool(datos.get("incluir_clientes"))}
    with con.transaction():
        if datos.get("id"):
            actual = repositorio.obtener(con, "diagramas_logicos", int(datos["id"]), bloquear=True)
            if actual["proyecto_id"] != p["id"] or actual["borrado_en"] is not None:
                raise NoEncontrado("El diagrama no existe (o fue eliminado)")
            try:
                antes, despues = repositorio.actualizar(con, "diagramas_logicos", actual["id"], int(datos.get("version") or 0), valores, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("Otro usuario cambió este diagrama mientras usted editaba. Recargue la lista.") from None
            cambio = repositorio.diferencias({k: antes[k] for k in valores}, {k: despues[k] for k in valores})
            if cambio:
                repositorio.registrar(con, actor["id"], "diagrama", actual["id"], "editar", cambio, proyecto_id=p["id"])
            id_ = actual["id"]
        else:
            fila = repositorio.insertar(con, "diagramas_logicos", {**valores, "proyecto_id": p["id"]}, actor["id"])
            repositorio.registrar(con, actor["id"], "diagrama", fila["id"], "crear", repositorio.diferencias(None, valores), proyecto_id=p["id"])
            id_ = fila["id"]
    return {**listar(con, actor, proyecto_id=p["id"]), "id": id_}


def eliminar(con: Any, actor: dict[str, Any], *, id: int, version: int) -> dict[str, Any]:
    actual = repositorio.obtener(con, "diagramas_logicos", int(id))
    if not proyectos.puede_editar(con, actor, actual["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    with con.transaction():
        ahora = con.execute("SELECT now() AS n").fetchone()["n"]
        try:
            repositorio.actualizar(con, "diagramas_logicos", actual["id"], int(version or 0), {"borrado_en": ahora}, actor["id"])
        except ConflictoVersion:
            raise ConflictoVersion("Otro usuario cambió este diagrama. Recargue la lista.") from None
        repositorio.registrar(con, actor["id"], "diagrama", actual["id"], "eliminar", {"titulo": [actual["titulo"], None]},
                              proyecto_id=actual["proyecto_id"])
    return listar(con, actor, proyecto_id=actual["proyecto_id"])


# --------------------------------------------------------------------------- generación

class _Red:
    """The whole active network of a project, read once."""

    def __init__(self, con: Any, proyecto_id: int):
        self.elementos = {e["id"]: dict(e) for e in con.execute(
            "SELECT id, tipo, subtipo, nombre, codigo, propiedades FROM redes.elementos WHERE proyecto_id = %s AND borrado_en IS NULL",
            (proyecto_id,)).fetchall()}
        self.cables = {c["id"]: dict(c) for c in con.execute(
            "SELECT id, nombre, clase, tipo, hilos, color, origen_id, destino_id, longitud_m, metraje FROM redes.cables "
            "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (proyecto_id,)).fetchall()}
        self.salientes: dict[int, list[int]] = {}
        for c in self.cables.values():
            self.salientes.setdefault(c["origen_id"], []).append(c["id"])
        hilos = {h["id"]: h["cable_id"] for h in con.execute(
            "SELECT h.id, h.cable_id FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id "
            "WHERE c.proyecto_id = %s AND h.borrado_en IS NULL", (proyecto_id,)).fetchall()}
        puertos = {p["id"]: dict(p) for p in con.execute(
            "SELECT p.id, p.splitter_id, p.conector_id, p.lado, p.numero FROM redes.puertos p "
            "LEFT JOIN redes.splitters s ON s.id = p.splitter_id LEFT JOIN redes.conectores k ON k.id = p.conector_id "
            "WHERE s.proyecto_id = %s OR k.proyecto_id = %s", (proyecto_id, proyecto_id)).fetchall()}
        self.splitters: dict[int, list[dict[str, Any]]] = {}
        for s in con.execute("SELECT id, mufa_id, nombre, salidas, relacion, conector FROM redes.splitters "
                             "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (proyecto_id,)).fetchall():
            self.splitters.setdefault(s["mufa_id"], []).append(dict(s))
        self.conectores: dict[int, list[dict[str, Any]]] = {}
        for k in con.execute("SELECT id, mufa_id, nombre, tipo FROM redes.conectores WHERE proyecto_id = %s AND borrado_en IS NULL "
                             "ORDER BY id", (proyecto_id,)).fetchall():
            self.conectores.setdefault(k["mufa_id"], []).append(dict(k))
        # connections per mufa, each end as ("cable", id) / ("splitter", id, lado, n) / ("conector", id, lado)
        self.conexiones: dict[int, list[tuple[tuple, tuple]]] = {}
        self.usados: dict[int, set[int]] = {}

        def extremo(hilo_id: int | None, puerto_id: int | None) -> tuple | None:
            if hilo_id is not None:
                cable = hilos.get(hilo_id)
                if cable is None:
                    return None
                self.usados.setdefault(cable, set()).add(hilo_id)
                return ("cable", cable)
            p = puertos.get(puerto_id)
            if p is None:
                return None
            if p["splitter_id"] is not None:
                return ("splitter", p["splitter_id"], p["lado"], p["numero"])
            return ("conector", p["conector_id"], p["lado"])

        for x in con.execute("SELECT * FROM redes.conexiones WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id",
                             (proyecto_id,)).fetchall():
            a, b = extremo(x["a_hilo_id"], x["a_puerto_id"]), extremo(x["b_hilo_id"], x["b_puerto_id"])
            if a and b:
                self.conexiones.setdefault(x["mufa_id"], []).append((a, b))

    def cables_del_splitter(self, mufa_id: int, splitter_id: int) -> set[int]:
        """Cables whose fibres leave splitter `splitter_id` (directly or through a connector)."""
        conexiones = self.conexiones.get(mufa_id, [])
        cables: set[int] = set()
        conectores: set[int] = set()
        for a, b in conexiones:
            for x, y in ((a, b), (b, a)):
                if x[0] == "splitter" and x[1] == splitter_id and x[2] == "salida":
                    if y[0] == "cable":
                        cables.add(y[1])
                    elif y[0] == "conector":
                        conectores.add(y[1])
        for a, b in conexiones:
            for x, y in ((a, b), (b, a)):
                if x[0] == "conector" and x[1] in conectores and y[0] == "cable":
                    cables.add(y[1])
        return cables


def _clave_pieza(extremo: tuple, entrada: int | None, salidas: set[int]) -> str | None:
    """Node of the box drawing an end belongs to (None: a cable outside the diagram)."""
    if extremo[0] == "cable":
        if extremo[1] == entrada:
            return "entrada"
        return f"salida:{extremo[1]}" if extremo[1] in salidas else None
    if extremo[0] == "splitter":
        return f"splitter:{extremo[1]}:{'entrada' if extremo[2] == 'entrada' else 'salida'}"
    return f"conector:{extremo[1]}:{extremo[2]}"


def generar(con: Any, actor: dict[str, Any], *, diagrama_id: int | None = None, proyecto_id: int | None = None,
            inicio: str | None = None, direccion: str = "derecha", incluir_clientes: bool = False,
            titulo: str | None = None) -> dict[str, Any]:
    """The logical diagram: boxes (tree from the start, forward) and the cables between them."""
    if diagrama_id is not None:
        d = repositorio.obtener(con, "diagramas_logicos", int(diagrama_id))
        if d["borrado_en"] is not None:
            raise NoEncontrado("El diagrama fue eliminado")
        proyecto_id, titulo, direccion, incluir_clientes = d["proyecto_id"], d["titulo"], d["direccion"], d["incluir_clientes"]
        inicio = f"s:{d['splitter_id']}" if d["splitter_id"] else f"e:{d['elemento_id']}"
    p = _proyecto(con, actor, int(proyecto_id or 0))
    try:
        elemento_id, splitter_id = _leer_inicio(con, p["id"], inicio)
    except DatosInvalidos:
        raise NoEncontrado("El elemento de inicio de este diagrama ya no existe: edítelo y elija otro") from None
    red = _Red(con, p["id"])
    if splitter_id is not None:
        raiz = con.execute("SELECT mufa_id FROM redes.splitters WHERE id = %s", (splitter_id,)).fetchone()["mufa_id"]
    else:
        raiz = elemento_id
    colores = colores_capacidad()
    cajas: list[dict[str, Any]] = []
    cables: list[dict[str, Any]] = []
    puestas = {raiz}
    cola: list[tuple[int, int | None, int, int | None]] = [(raiz, None, 0, None)]       # (box, incoming cable, level, parent)
    while cola and len(cajas) < MAX_CAJAS:
        caja_id, entrada, nivel, padre = cola.pop(0)
        e = red.elementos[caja_id]
        simbolo = _simbolo(e)
        salidas: list[int] = []
        clientes_omitidos = 0
        permitidos = red.cables_del_splitter(caja_id, splitter_id) if (caja_id == raiz and splitter_id is not None) else None
        if e["tipo"] != "cliente":
            for cid in red.salientes.get(caja_id, []):
                c = red.cables[cid]
                destino = red.elementos.get(c["destino_id"])
                if destino is None or c["destino_id"] in puestas or (permitidos is not None and cid not in permitidos):
                    continue
                if destino["tipo"] == "cliente" and not incluir_clientes:
                    clientes_omitidos += 1
                    continue
                if destino["tipo"] not in ("nodo", "odf", "mufa", "cliente"):
                    continue
                puestas.add(c["destino_id"])
                salidas.append(cid)
                cola.append((c["destino_id"], cid, nivel + 1, caja_id))
                cables.append({"id": cid, "nombre": c["nombre"], "clase": c["clase"], "tipo": c["tipo"], "hilos": c["hilos"],
                               "usados": len(red.usados.get(cid, ())), "color": color_de(c["hilos"], colores),
                               "desde": caja_id, "hasta": c["destino_id"], "longitud_m": float(c["longitud_m"] or 0),
                               "metraje_m": (c["metraje"] or {}).get("metraje_m")})
        splitters = [s for s in red.splitters.get(caja_id, []) if permitidos is None or s["id"] == splitter_id]
        ids_splitters = {s["id"] for s in splitters}
        conectores = red.conectores.get(caja_id, [])
        lineas: dict[tuple[str, str], int] = {}
        for a, b in red.conexiones.get(caja_id, []):
            if any(x[0] == "splitter" and x[1] not in ids_splitters for x in (a, b)):
                continue
            ka, kb = _clave_pieza(a, entrada, set(salidas)), _clave_pieza(b, entrada, set(salidas))
            if ka is None or kb is None:
                continue
            # entrada first / salidas last, so every line is drawn left to right
            orden = lambda k: 0 if k == "entrada" else 2 if k.startswith("salida:") else 1
            # (a splitter / connector output is the source of a line to another piece's input)
            de, a_ = sorted((ka, kb), key=lambda k: (orden(k), 0 if k.endswith(":salida") else 1))
            lineas[(de, a_)] = lineas.get((de, a_), 0) + 1
        usados_conectores = {k.split(":")[1] for par in lineas for k in par if k.startswith("conector:")}
        resumen = ", ".join(f"1x{s['salidas']}{' ' + s['relacion'] if s['relacion'] else ''}" for s in splitters)
        cajas.append({"id": caja_id, "nombre": e["nombre"], "codigo": e["codigo"], "tipo": e["tipo"], "subtipo": e["subtipo"],
                      "simbolo": simbolo, "nivel": nivel, "padre": padre, "entrada": entrada, "salidas": salidas,
                      "etiqueta": f"{e['nombre']} ({resumen})" if resumen else e["nombre"],
                      "splitters": [{k: s[k] for k in ("id", "nombre", "salidas", "relacion", "conector")} for s in splitters],
                      "conectores": [{k: x[k] for k in ("id", "nombre", "tipo")} for x in conectores if str(x["id"]) in usados_conectores],
                      "lineas": [{"de": k[0], "a": k[1], "hilos": n} for k, n in lineas.items()],
                      "clientes_omitidos": clientes_omitidos,
                      "id_servicio": (e["propiedades"] or {}).get("id_servicio") if e["tipo"] == "cliente" else None})
    inicio_txt = next((i["texto"] for i in _inicios(con, p["id"]) if i["clave"] == inicio), inicio)
    return {"proyecto": p, "diagrama_id": diagrama_id, "titulo": titulo or f"{p['nombre']} | {inicio_txt}",
            "inicio": {"clave": inicio, "texto": inicio_txt, "caja": raiz}, "direccion": direccion,
            "incluir_clientes": bool(incluir_clientes), "cajas": cajas, "cables": cables,
            "recortado": len(cajas) >= MAX_CAJAS,
            "leyenda": {"simbolos": [{"simbolo": k, "texto": v} for k, v in NOMBRE_SIMBOLO.items() if k != "cliente" or incluir_clientes],
                        "colores": [{"hilos": k, "color": colores[k]} for k in sorted(colores, reverse=True)]}}
