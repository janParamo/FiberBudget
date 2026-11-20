"""El nodo como lugar físico: sus ODF y sus OLT, y cómo se conectan.

Tres niveles: el nodo (el elemento que se ve en el esquema general), los ODF que aloja (cada uno con su cantidad de puertos) y las OLT que aloja (cada una con su cantidad de hilos), y
por último los enlaces: el puerto de una OLT va al puerto de un ODF y/o a un hilo de un cable del nodo (el que lleva a las mufas). Un ODF puede estar conectado a varias OLT y una OLT
a varios ODF. Cada puerto de un ODF y de una OLT admite un solo enlace; un hilo, también.
`leer` lo trae todo armado para dibujarlo (los ODF como mosaicos de puertos libres / ocupados); las demás funciones cambian algo y devuelven lo mismo.
"""
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from visor_rutas.redes import proyectos, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

MAX_PUERTOS = 576


def _nodo(con: Any, actor: dict[str, Any], nodo_id: int, *, editar: bool = False) -> dict[str, Any]:
    n = con.execute("SELECT id, proyecto_id, tipo, subtipo, nombre, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos WHERE id = %s AND borrado_en IS NULL",
                    (int(nodo_id),)).fetchone()
    if n is None or n["tipo"] != "nodo":
        raise NoEncontrado("El nodo no existe (o no es un nodo)")
    if not (proyectos.puede_editar if editar else proyectos.puede_ver)(con, actor, n["proyecto_id"]):
        raise SinPermiso("No tiene permiso para " + ("editar" if editar else "ver") + " este proyecto")
    return dict(n)


def _puertos(valor: Any, quien: str) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({quien: "los puertos son un número"}) from None
    if not 1 <= n <= MAX_PUERTOS:
        raise DatosInvalidos({quien: f"los puertos van de 1 a {MAX_PUERTOS}"})
    return n


def _nombre(valor: Any, quien: str, por_defecto: str) -> str:
    return " ".join(str(valor or "").split())[:160] or por_defecto


def leer(con: Any, actor: dict[str, Any], *, nodo_id: int) -> dict[str, Any]:
    """The node with its ODFs (ports free / used), its OLTs, the links between them and the cables whose fibres can be assigned."""
    n = _nodo(con, actor, nodo_id)
    editar = proyectos.puede_editar(con, actor, n["proyecto_id"])
    odfs = [dict(f) for f in con.execute("SELECT id, nombre, puertos, version, fuente, estimado, ref_elemento_id FROM redes.nodo_odfs WHERE nodo_id = %s AND borrado_en IS NULL ORDER BY lower(nombre), id", (n["id"],)).fetchall()]
    olts = [dict(f) for f in con.execute("SELECT id, nombre, puertos, version, fuente, estimado FROM redes.nodo_olts WHERE nodo_id = %s AND borrado_en IS NULL ORDER BY lower(nombre), id", (n["id"],)).fetchall()]
    for o in odfs:                                    # the cables the ODF has in the Visio (towards mufas): kept as they were, shown beside the ODF
        o["cables_visio"] = [{"nombre": c["nombre"], "hilos": c["hilos"], "otro": c["otro_nombre"], "otro_tipo": c["otro_tipo"]} for c in con.execute(
            "SELECT c.nombre, c.hilos, x.nombre AS otro_nombre, x.tipo AS otro_tipo FROM redes.cables c JOIN redes.elementos x ON x.id = CASE WHEN c.origen_id = %(e)s THEN c.destino_id ELSE c.origen_id END "
            "WHERE c.borrado_en IS NULL AND (c.origen_id = %(e)s OR c.destino_id = %(e)s) ORDER BY lower(c.nombre) LIMIT 20", {"e": o["ref_elemento_id"]}).fetchall()] if o["ref_elemento_id"] else []
    cables = []
    for c in con.execute(
            "SELECT c.id, c.nombre, c.clase, c.hilos, o.id AS otro_id, o.nombre AS otro_nombre, o.tipo AS otro_tipo FROM redes.cables c "
            "JOIN redes.elementos o ON o.id = CASE WHEN c.origen_id = %(n)s THEN c.destino_id ELSE c.origen_id END "
            "WHERE c.borrado_en IS NULL AND (c.origen_id = %(n)s OR c.destino_id = %(n)s) ORDER BY lower(c.nombre), c.id", {"n": n["id"]}).fetchall():
        fibras = [dict(h) for h in con.execute("SELECT id, numero FROM redes.hilos WHERE cable_id = %s AND borrado_en IS NULL ORDER BY numero", (c["id"],)).fetchall()]
        cables.append({"id": c["id"], "nombre": c["nombre"], "clase": c["clase"], "hilos": c["hilos"],
                       "otro": {"id": c["otro_id"], "nombre": c["otro_nombre"], "tipo": c["otro_tipo"]}, "fibras": fibras})
    enlaces = [dict(f) for f in con.execute(
        "SELECT e.id, e.version, e.olt_id, e.olt_puerto, e.odf_id, e.odf_puerto, e.hilo_id, h.numero AS hilo_numero, h.cable_id, c.nombre AS cable_nombre, "
        " o.id AS destino_id, o.nombre AS destino_nombre, o.tipo AS destino_tipo "
        "FROM redes.nodo_enlaces e LEFT JOIN redes.hilos h ON h.id = e.hilo_id LEFT JOIN redes.cables c ON c.id = h.cable_id "
        "LEFT JOIN redes.elementos o ON o.id = CASE WHEN c.origen_id = e.nodo_id THEN c.destino_id ELSE c.origen_id END "
        "WHERE e.nodo_id = %s AND e.borrado_en IS NULL ORDER BY e.olt_id, e.olt_puerto", (n["id"],)).fetchall()]
    nombre_olt, nombre_odf = {o["id"]: o["nombre"] for o in olts}, {o["id"]: o["nombre"] for o in odfs}
    for e in enlaces:
        e["olt_nombre"], e["odf_nombre"] = nombre_olt.get(e["olt_id"]), nombre_odf.get(e["odf_id"])
    for o in odfs:
        usados = [e for e in enlaces if e["odf_id"] == o["id"]]
        o["ocupados"], o["libres"] = len(usados), o["puertos"] - len(usados)
    for o in olts:
        usados = [e for e in enlaces if e["olt_id"] == o["id"]]
        o["ocupados"], o["libres"] = len(usados), o["puertos"] - len(usados)
    return {"nodo": {"id": n["id"], "nombre": n["nombre"], "subtipo": n["subtipo"], "lat": n["lat"], "lon": n["lon"], "proyecto_id": n["proyecto_id"], "puede_editar": editar},
            "odfs": odfs, "olts": olts, "enlaces": enlaces, "cables": cables}


# --------------------------------------------------------------------------- ODF y OLT

def _guardar(con: Any, actor: dict[str, Any], tabla: str, etiqueta: str, columna_enlace: str, nodo_id: int, elem_id: Any, nombre: Any, puertos: Any, eliminar: bool) -> dict[str, Any]:
    n = _nodo(con, actor, nodo_id, editar=True)
    with con.transaction():
        if elem_id in (None, "", 0):
            if eliminar:
                raise DatosInvalidos({etiqueta: "no hay nada que eliminar"})
            hay = con.execute(f"SELECT count(*) AS n FROM redes.{tabla} WHERE nodo_id = %s AND borrado_en IS NULL", (n["id"],)).fetchone()["n"]
            limpio = _nombre(nombre, etiqueta, f"{etiqueta} {hay + 1}")
            if con.execute(f"SELECT 1 FROM redes.{tabla} WHERE nodo_id = %s AND borrado_en IS NULL AND lower(nombre) = lower(%s)", (n["id"], limpio)).fetchone():
                raise DatosInvalidos({etiqueta: f"ya hay un {etiqueta} llamado «{limpio}» en este nodo"})
            fila = repositorio.insertar(con, tabla, {"nodo_id": n["id"], "nombre": limpio, "puertos": _puertos(puertos if puertos not in (None, "") else 24, etiqueta)}, actor["id"])
            repositorio.registrar(con, actor["id"], tabla[:-1], fila["id"], "crear", {"nombre": [None, limpio], "puertos": [None, fila["puertos"]]}, proyecto_id=n["proyecto_id"])
            return leer(con, actor, nodo_id=n["id"])
        actual = con.execute(f"SELECT * FROM redes.{tabla} WHERE id = %s AND nodo_id = %s AND borrado_en IS NULL FOR UPDATE", (int(elem_id), n["id"])).fetchone()
        if actual is None:
            raise NoEncontrado(f"El {etiqueta} ya no existe en este nodo")
        if eliminar:
            if columna_enlace == "olt_id":                                       # an OLT that goes: its links go
                con.execute("UPDATE redes.nodo_enlaces SET borrado_en = now(), actualizado_en = now(), version = version + 1 WHERE olt_id = %s AND borrado_en IS NULL", (actual["id"],))
            else:                                                                # an ODF that goes: the links keep their fibre (if they have one) and lose the port
                con.execute("UPDATE redes.nodo_enlaces SET borrado_en = now(), actualizado_en = now(), version = version + 1 WHERE odf_id = %s AND hilo_id IS NULL AND borrado_en IS NULL", (actual["id"],))
                con.execute("UPDATE redes.nodo_enlaces SET odf_id = NULL, odf_puerto = NULL, actualizado_en = now(), version = version + 1 WHERE odf_id = %s AND borrado_en IS NULL", (actual["id"],))
            con.execute(f"UPDATE redes.{tabla} SET borrado_en = now(), actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], actual["id"]))
            repositorio.registrar(con, actor["id"], tabla[:-1], actual["id"], "eliminar", {"nombre": [actual["nombre"], None]}, proyecto_id=n["proyecto_id"])
            return leer(con, actor, nodo_id=n["id"])
        valores: dict[str, Any] = {}
        if nombre not in (None, ""):
            limpio = _nombre(nombre, etiqueta, actual["nombre"])
            if limpio.lower() != actual["nombre"].lower() and con.execute(
                    f"SELECT 1 FROM redes.{tabla} WHERE nodo_id = %s AND borrado_en IS NULL AND lower(nombre) = lower(%s) AND id <> %s", (n["id"], limpio, actual["id"])).fetchone():
                raise DatosInvalidos({etiqueta: f"ya hay un {etiqueta} llamado «{limpio}» en este nodo"})
            valores["nombre"] = limpio
        if puertos not in (None, ""):
            nuevo = _puertos(puertos, etiqueta)
            usado = con.execute(f"SELECT max({'olt_puerto' if columna_enlace == 'olt_id' else 'odf_puerto'}) AS m FROM redes.nodo_enlaces WHERE {columna_enlace} = %s AND borrado_en IS NULL",
                                (actual["id"],)).fetchone()["m"] or 0
            if nuevo < usado:
                raise DatosInvalidos({etiqueta: f"el puerto {usado} está en uso: no puede tener menos de {usado} puertos"})
            valores["puertos"] = nuevo
            valores["estimado"] = False
        if valores:
            antes, despues = repositorio.actualizar(con, tabla, actual["id"], actual["version"], valores, actor["id"])
            repositorio.registrar(con, actor["id"], tabla[:-1], actual["id"], "editar", repositorio.diferencias({k: antes[k] for k in valores}, {k: despues[k] for k in valores}), proyecto_id=n["proyecto_id"])
    return leer(con, actor, nodo_id=n["id"])


def guardar_odf(con: Any, actor: dict[str, Any], *, nodo_id: int, odf_id: Any = None, nombre: Any = None, puertos: Any = None, eliminar: bool = False) -> dict[str, Any]:
    """Creates an ODF of the node (name and number of ports), renames / resizes it (never below its highest port in use) or deletes it."""
    return _guardar(con, actor, "nodo_odfs", "ODF", "odf_id", nodo_id, odf_id, nombre, puertos, bool(eliminar))


def guardar_olt(con: Any, actor: dict[str, Any], *, nodo_id: int, olt_id: Any = None, nombre: Any = None, puertos: Any = None, eliminar: bool = False) -> dict[str, Any]:
    """Creates an OLT of the node (name and number of fibres), renames / resizes it or deletes it (its links go with it)."""
    return _guardar(con, actor, "nodo_olts", "OLT", "olt_id", nodo_id, olt_id, nombre, puertos, bool(eliminar))


# --------------------------------------------------------------------------- enlaces

def guardar_enlace(con: Any, actor: dict[str, Any], *, nodo_id: int, olt_id: int, olt_puerto: int, odf_id: Any = None, odf_puerto: Any = None,
                   hilo_id: Any = None, quitar: bool = False) -> dict[str, Any]:
    """Sets what port `olt_puerto` of the OLT is connected to: a port of an ODF and/or a fibre of a cable of the node (which goes to the mufas). `quitar`: no longer connected."""
    n = _nodo(con, actor, nodo_id, editar=True)
    with con.transaction():
        olt = con.execute("SELECT id, nombre, puertos FROM redes.nodo_olts WHERE id = %s AND nodo_id = %s AND borrado_en IS NULL", (int(olt_id or 0), n["id"])).fetchone()
        if olt is None:
            raise NoEncontrado("La OLT ya no existe en este nodo")
        try:
            puerto = int(olt_puerto)
        except (TypeError, ValueError):
            raise DatosInvalidos({"OLT": "el puerto es un número"}) from None
        if not 1 <= puerto <= olt["puertos"]:
            raise DatosInvalidos({"OLT": f"{olt['nombre']} tiene {olt['puertos']} hilos: no existe el {puerto}"})
        previo = con.execute("SELECT * FROM redes.nodo_enlaces WHERE olt_id = %s AND olt_puerto = %s AND borrado_en IS NULL FOR UPDATE", (olt["id"], puerto)).fetchone()
        if quitar:
            if previo is not None:
                con.execute("UPDATE redes.nodo_enlaces SET borrado_en = now(), actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], previo["id"]))
                repositorio.registrar(con, actor["id"], "nodo_enlace", previo["id"], "eliminar", {"olt": [f"{olt['nombre']} {puerto}", None]}, proyecto_id=n["proyecto_id"])
            return leer(con, actor, nodo_id=n["id"])
        odf = None
        if odf_id not in (None, "", 0):
            odf = con.execute("SELECT id, nombre, puertos FROM redes.nodo_odfs WHERE id = %s AND nodo_id = %s AND borrado_en IS NULL", (int(odf_id), n["id"])).fetchone()
            if odf is None:
                raise NoEncontrado("El ODF ya no existe en este nodo")
            try:
                po = int(odf_puerto)
            except (TypeError, ValueError):
                raise DatosInvalidos({"ODF": "elija el puerto del ODF"}) from None
            if not 1 <= po <= odf["puertos"]:
                raise DatosInvalidos({"ODF": f"{odf['nombre']} tiene {odf['puertos']} puertos: no existe el {po}"})
            otro = con.execute("SELECT e.id, o.nombre AS olt, e.olt_puerto FROM redes.nodo_enlaces e JOIN redes.nodo_olts o ON o.id = e.olt_id "
                               "WHERE e.odf_id = %s AND e.odf_puerto = %s AND e.borrado_en IS NULL AND e.id IS DISTINCT FROM %s", (odf["id"], po, previo["id"] if previo else None)).fetchone()
            if otro is not None:
                raise DatosInvalidos({"ODF": f"El puerto {po} de {odf['nombre']} ya está conectado a {otro['olt']} (hilo {otro['olt_puerto']})"})
        hilo = None
        if hilo_id not in (None, "", 0):
            hilo = con.execute("SELECT h.id, h.numero, c.nombre FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE h.id = %s AND h.borrado_en IS NULL AND c.borrado_en IS NULL "
                               "AND (c.origen_id = %s OR c.destino_id = %s)", (int(hilo_id), n["id"], n["id"])).fetchone()
            if hilo is None:
                raise DatosInvalidos({"hilo": "El hilo no es de un cable de este nodo"})
            otro = con.execute("SELECT o.nombre AS olt, e.olt_puerto FROM redes.nodo_enlaces e JOIN redes.nodo_olts o ON o.id = e.olt_id "
                               "WHERE e.hilo_id = %s AND e.borrado_en IS NULL AND e.id IS DISTINCT FROM %s", (hilo["id"], previo["id"] if previo else None)).fetchone()
            if otro is not None:
                raise DatosInvalidos({"hilo": f"El hilo {hilo['numero']} de {hilo['nombre']} ya está asignado a {otro['olt']} (hilo {otro['olt_puerto']})"})
        if odf is None and hilo is None:
            raise DatosInvalidos({"OLT": "elija a qué va el hilo: un puerto de un ODF o un hilo de un cable"})
        valores = (odf["id"] if odf else None, po if odf else None, hilo["id"] if hilo else None)
        if previo is None:
            fila = repositorio.insertar(con, "nodo_enlaces", {"nodo_id": n["id"], "olt_id": olt["id"], "olt_puerto": puerto, "odf_id": valores[0], "odf_puerto": valores[1], "hilo_id": valores[2]}, actor["id"])
            repositorio.registrar(con, actor["id"], "nodo_enlace", fila["id"], "crear", {"olt": [None, f"{olt['nombre']} {puerto}"]}, proyecto_id=n["proyecto_id"])
        else:
            con.execute("UPDATE redes.nodo_enlaces SET odf_id = %s, odf_puerto = %s, hilo_id = %s, actualizado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s",
                        (*valores, actor["id"], previo["id"]))
            repositorio.registrar(con, actor["id"], "nodo_enlace", previo["id"], "editar", {"olt": [f"{olt['nombre']} {puerto}", f"{olt['nombre']} {puerto}"]}, proyecto_id=n["proyecto_id"])
    return leer(con, actor, nodo_id=n["id"])


# --------------------------------------------------------------------------- lo que ya viene del Visio: ODF y OLT dentro de su nodo
RADIO_NODO_M = 150.0                       # an ODF with no cable towards a node is put in the node that is within this distance
RADIO_NODO_NOMBRE_M = 400.0                # …or this one when its name says it is of a node / rack («ODF NODO 12.5», «ODF #3 EN RACK DEL OLT»)
ESTANDAR = (12, 24, 48, 72, 96, 144)
PUERTOS_OLT_POR_OMISION = 16
_PUERTOS_EN_NOMBRE = (re.compile(r"\b(\d{1,3})\s*(?:P\b|PTOS?\b|PUERTOS?\b|POSICIONES\b|POS\b)", re.I), re.compile(r"\b1\s*-\s*(\d{1,3})\s*H?\b", re.I),
                      re.compile(r"\b(\d{1,3})\s*H\b", re.I), re.compile(r"\bODF\s*(?:DE\s*)?(\d{1,3})\b", re.I))


def _plano(texto: Any) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", t.upper()).split())


def _metros(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _radio_del_nombre(nombre: Any) -> float:
    """How far from a node an ODF with no cable to it can be and still be of it: more when its own name says it is of a node or a rack."""
    palabras = set(_plano(nombre).split())
    return RADIO_NODO_NOMBRE_M if palabras & {"NODO", "OLT", "RACK", "CONTENEDOR"} else RADIO_NODO_M


def puertos_del_nombre(nombre: str, hilos_cables: list[int]) -> tuple[int, bool]:
    """(ports, estimated) of an ODF from what its name says («ODF 48P», «24H», "1-24 H», «4 PUERTOS», «24 posiciones»), else from the biggest cable it has (rounded up to
    12, 24, 48, 72, 96, 144), else 12; `estimated` when it was not read from the name."""
    for patron in _PUERTOS_EN_NOMBRE:
        m = patron.search(nombre or "")
        if m and 1 <= int(m.group(1)) <= MAX_PUERTOS:
            return int(m.group(1)), False
    mayor = max([h for h in hilos_cables if h] or [0])
    if mayor:
        return next((e for e in ESTANDAR if e >= mayor), mayor), True
    return 12, True


def _olts_conocidas() -> dict[str, list[str]]:
    """The OLTs of business_rules.yaml (`traffic_origin.nodes`: «OLT GRANADA» → the spellings found in the diagrams)."""
    try:
        from config import get_settings
        reglas = yaml.safe_load(Path(get_settings().rules_path).read_text(encoding="utf-8")) or {}
    except Exception:                                                  # noqa: BLE001 - without the rules there are no OLTs to bring: the ODFs are still converted
        return {}
    nodos = (reglas.get("traffic_origin") or {}).get("nodes") or {}
    return {nombre: [str(a) for a in alias] for nombre, alias in nodos.items() if str(nombre).upper().startswith("OLT ")}


def plan_visio(con: Any, *, proyecto_id: int | None = None, nodo_id: int | None = None) -> dict[str, Any]:
    """What the conversion would do, without writing: the ODFs of the Visio put in their node (by the cable that joins them to it, through other ODFs, else by the nearest node
    within RADIO_NODO_M), their ports (from the name, else from their cables, else 12: estimated) and the OLTs of the node (by the name of the node against the OLTs of the rules).
    {"odfs": [{elemento_id, nombre, nodo_id, nodo, como, puertos, estimado}], "sin_nodo": [...], "olts": [{nodo_id, nodo, nombre, puertos}]}."""
    filtro = "AND e.proyecto_id = %(p)s" if proyecto_id else ""
    nodos = [dict(f) for f in con.execute(
        f"SELECT e.id, e.proyecto_id, e.nombre, ST_Y(e.ubicacion) AS lat, ST_X(e.ubicacion) AS lon FROM redes.elementos e WHERE e.borrado_en IS NULL AND e.tipo = 'nodo' {filtro} ORDER BY e.id", {"p": proyecto_id}).fetchall()]
    odfs = [dict(f) for f in con.execute(
        f"SELECT e.id, e.proyecto_id, e.nombre, ST_Y(e.ubicacion) AS lat, ST_X(e.ubicacion) AS lon FROM redes.elementos e WHERE e.borrado_en IS NULL AND e.tipo = 'odf' {filtro} ORDER BY e.id", {"p": proyecto_id}).fetchall()]
    ids = [e["id"] for e in nodos + odfs]
    vecinos: dict[int, list[tuple[int, int | None]]] = {i: [] for i in ids}
    hilos_de: dict[int, list[int]] = {i: [] for i in ids}
    for c in con.execute("SELECT c.origen_id, c.destino_id, c.hilos FROM redes.cables c WHERE c.borrado_en IS NULL AND (c.origen_id = ANY(%(i)s) OR c.destino_id = ANY(%(i)s))", {"i": ids}).fetchall():
        for a, b in ((c["origen_id"], c["destino_id"]), (c["destino_id"], c["origen_id"])):
            if a in vecinos:
                vecinos[a].append((b, c["hilos"]))
                hilos_de[a].append(c["hilos"] or 0)
    es_nodo = {n["id"]: n for n in nodos}
    es_odf = {o["id"]: o for o in odfs}
    resultado, sin_nodo = [], []
    for o in odfs:
        if nodo_id and o["id"] not in es_odf:
            continue
        hallado: tuple[dict[str, Any], str] | None = None
        visto, frente = {o["id"]}, [o["id"]]
        for profundidad in range(4):                                    # the cable that joins it to a node, directly or through other ODFs
            siguiente = []
            for actual in frente:
                for otro, _ in vecinos.get(actual, []):
                    if otro in es_nodo:
                        hallado = (es_nodo[otro], "por su cable" if profundidad == 0 else "por el cable de otro ODF"); break
                    if otro in es_odf and otro not in visto:
                        visto.add(otro); siguiente.append(otro)
                if hallado:
                    break
            if hallado or not siguiente:
                break
            frente = siguiente
        if hallado is None and o["lat"] is not None:                     # else the nearest node of its project
            cerca = sorted(((_metros((o["lat"], o["lon"]), (n["lat"], n["lon"])), n) for n in nodos if n["proyecto_id"] == o["proyecto_id"] and n["lat"] is not None), key=lambda x: x[0])
            radio = _radio_del_nombre(o["nombre"])
            if cerca and cerca[0][0] <= radio:
                hallado = (cerca[0][1], f"por cercanía ({cerca[0][0]:.0f} m)")
        if hallado is None or (nodo_id and hallado[0]["id"] != nodo_id):
            if hallado is None:
                sin_nodo.append({"elemento_id": o["id"], "nombre": o["nombre"]})
            continue
        puertos, estimado = puertos_del_nombre(o["nombre"], hilos_de.get(o["id"], []))
        resultado.append({"elemento_id": o["id"], "nombre": " ".join(str(o["nombre"]).split())[:160], "nodo_id": hallado[0]["id"], "nodo": hallado[0]["nombre"], "como": hallado[1], "puertos": puertos, "estimado": estimado})
    olts = []
    conocidas = _olts_conocidas()
    for n in nodos:
        if nodo_id and n["id"] != nodo_id:
            continue
        nombre = _plano(n["nombre"])
        for olt, alias in conocidas.items():
            if any(re.search(rf"\b{re.escape(_plano(a))}\b", nombre) for a in alias if len(_plano(a)) >= 4):
                olts.append({"nodo_id": n["id"], "nodo": n["nombre"], "nombre": olt, "puertos": PUERTOS_OLT_POR_OMISION})
    return {"odfs": resultado, "sin_nodo": sin_nodo, "olts": olts}


def convertir_visio(con: Any, actor: dict[str, Any], *, proyecto_id: Any = None, nodo_id: Any = None, simular: bool = True) -> dict[str, Any]:
    """Brings the ODFs and the OLTs the Visio already has into the structure of the node (administrators). Nothing of the network is deleted or changed: the ODF elements and their cables stay
    (the ODF of the node points to its element and shows its cables); what is created can be edited, and what was estimated says so. It can be repeated: what is already there is not made twice.
    With `simular` it only says what it would do. {"odfs_nuevos", "odfs_ya_estaban", "olts_nuevas", "olts_ya_estaban", "sin_nodo", "detalle": plan}."""
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede traer los ODF y las OLT del Visio")
    p = int(proyecto_id) if proyecto_id not in (None, "") else None
    n = int(nodo_id) if nodo_id not in (None, "") else None
    if n is not None:
        _nodo(con, actor, n, editar=True)
    plan = plan_visio(con, proyecto_id=p, nodo_id=n)
    existentes = {f["ref_elemento_id"] for f in con.execute("SELECT ref_elemento_id FROM redes.nodo_odfs WHERE borrado_en IS NULL AND ref_elemento_id IS NOT NULL").fetchall()}
    odfs_nuevos = [o for o in plan["odfs"] if o["elemento_id"] not in existentes]
    olts_nuevas = [o for o in plan["olts"] if not con.execute("SELECT 1 FROM redes.nodo_olts WHERE nodo_id = %s AND borrado_en IS NULL AND lower(nombre) = lower(%s)", (o["nodo_id"], o["nombre"])).fetchone()]
    informe = {"odfs_nuevos": len(odfs_nuevos), "odfs_ya_estaban": len(plan["odfs"]) - len(odfs_nuevos), "olts_nuevas": len(olts_nuevas), "olts_ya_estaban": len(plan["olts"]) - len(olts_nuevas),
               "sin_nodo": plan["sin_nodo"], "estimados": sum(1 for o in odfs_nuevos if o["estimado"]), "simulado": bool(simular), "nodos": len({o["nodo_id"] for o in odfs_nuevos + olts_nuevas})}
    if simular:
        return informe
    with con.transaction():
        for o in odfs_nuevos:
            nombre, k = o["nombre"], 1
            while con.execute("SELECT 1 FROM redes.nodo_odfs WHERE nodo_id = %s AND borrado_en IS NULL AND lower(nombre) = lower(%s)", (o["nodo_id"], nombre)).fetchone():
                k += 1
                nombre = f"{o['nombre']} ({k})"                        # «ODF A» twice in a node (the Visio repeats it per diagram): the second is «ODF A (2)»
            fila = repositorio.insertar(con, "nodo_odfs", {"nodo_id": o["nodo_id"], "nombre": nombre, "puertos": o["puertos"], "fuente": "visio", "estimado": o["estimado"], "ref_elemento_id": o["elemento_id"]}, actor["id"])
            repositorio.registrar(con, actor["id"], "nodo_odf", fila["id"], "crear", {"nombre": [None, nombre], "origen": [None, "Visio"]})
        for o in olts_nuevas:
            fila = repositorio.insertar(con, "nodo_olts", {"nodo_id": o["nodo_id"], "nombre": o["nombre"], "puertos": o["puertos"], "fuente": "visio", "estimado": True}, actor["id"])
            repositorio.registrar(con, actor["id"], "nodo_olt", fila["id"], "crear", {"nombre": [None, o["nombre"]], "origen": [None, "Visio (por el nombre del nodo)"]})
    return informe
