"""Migración Visio, fase 3: lo de adentro de cada mufa (reglas 6.3 y 6.4 de docs/migracion_visio/PLAN.md).

Lee `red_fibra` y el KMZ **solo para leer** y, sobre las mufas ya migradas (fase 2), crea:
  - **splitters** de los textos "SPL 1X8 … OLT SD P0/2/9 -20.42 dBm" (salidas, relación, OLT, puerto
    OLT, potencia y "DEPENDE DE" en `propiedades`). Un renglón numerado ("38- SPL 1X8 MF GOMPER") no
    es un splitter de esta mufa: describe un hilo o un puerto que va a otra;
  - **puertos con su cliente** de las listas "SPL 1X8 …" + "1- C24712 Nombre ID418400" (`puerto_servicios`).
    Solo listas cuya numeración cabe en el splitter: "DE MF A A LA MF B / 29- …" es una lista de hilos;
  - **clientes de la mufa sin puerto conocido** (`mufa_clientes`);
  - **clientes en el mapa** (elemento `cliente`) en la punta de su acometida del KMZ (línea "C32043 …"),
    la punta lejos de su mufa (Kayako no se usa por ahora);
  - **empalmes** del Excel de anillos (`anillo_tramos`): hilo de entrada ↔ hilo de salida, confianza alta,
    solo si los dos cables existen, tienen hilos conocidos y el hilo está libre en esa mufa.
No se inventa nada: los textos que nombran hilos sin decir entre qué cables, y las fusiones dibujadas
(geometría, apagada en `business_rules.yaml`), quedan "sin diagramar" y se listan en el reporte.
Es idempotente: cada splitter, puerto, cliente y empalme se reconoce y no se repite.
"""
import collections
import re
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import metraje, migrar_visio, mufa, red, repositorio
from visor_rutas.redes.migrar_visio import Plan, _comparable

SALIDAS = (2, 4, 8, 16, 32)
FRACCIONES = {"½": 2, "¼": 4, "⅛": 8}
_TAMANO = re.compile(r"(?<![\d/])1\s*[X/:]\s*(\d{1,2})(?![\d/])|([½¼⅛])", re.I)
_NUMERADO = re.compile(r"^\s*(\d{1,2})\s*[-–.)]\s*(.*)$")
_CODIGO = re.compile(r"\bC\d{4,6}\b", re.I)
_ID = re.compile(r"\bID\s*\d{5,7}\b", re.I)
_PUERTO_OLT = re.compile(r"(?<![\d/])(\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{1,2})(?![\d/])")
_OLT = re.compile(r"\bOLT\b\s*(?:PTO\s*\d+\s*)?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ]{1,30}?)(?=\s*(?:\bP(?:UERTO|TO)?\.?\s*\d|-?\d|$|[,(/:]))", re.I)
_POTENCIA = re.compile(r"(-?\d{1,2}(?:[.,]\d{1,2})?)\s*dBm?\b", re.I)
_DEPENDE = re.compile(r"\bDEPENDE\s+(?:DE\s+)?(.+)", re.I)
_RELACION = re.compile(r"(?<![\d/])(\d{2})\s*/\s*(\d{2})(?![\d/])")
_VACIO = re.compile(r"^(LIBRE|VALIDAR|DISPONIBLE|RESERVA(DO)?|N/?A|-+|\.+)?(\s+(LIBRE|VALIDAR|POTENCIA))*\s*$", re.I)
DISTANCIA_ACOMETIDA_M = 1500


# --------------------------------------------------------------------------- lectura de textos

def tamano(texto: str) -> int | None:
    m = _TAMANO.search(texto or "")
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else FRACCIONES[m.group(2)]


def leer_splitter(texto: str) -> dict[str, Any]:
    """'SPL 1X8 SECUNDARIO OLT SD PUERTO 0/2/9 -20.42 dBm' -> salidas, relación and properties."""
    t = " ".join(str(texto or "").split())
    salidas = tamano(t)
    props: dict[str, Any] = {"texto_visio": t[:300]}
    if m := _PUERTO_OLT.search(t):
        props["puerto_olt"] = re.sub(r"\s+", "", m.group(1))
    if (m := _OLT.search(t)) and not re.fullmatch(r"(P|PTO|PUERTO|DEL|EN|DE)(\s.*)?", m.group(1).strip(), re.I):
        props["olt"] = m.group(1).strip()          # "OLT PUERTO 0/2/0" names no OLT
    if m := _POTENCIA.search(t):
        props["potencia_dbm"] = float(m.group(1).replace(",", "."))
    if m := _DEPENDE.search(t):
        props["depende_de"] = re.sub(r"^[½¼⅛]|^1\s*[X/]\s*\d{1,2}\s*", "", m.group(1)).strip(" :-")[:120] or None
    relacion = None
    if salidas == 2 and (m := _RELACION.search(t)) and int(m.group(1)) + int(m.group(2)) == 100:
        relacion = f"{m.group(1)}/{m.group(2)}"
    return {"salidas": salidas, "relacion": relacion, "propiedades": {k: v for k, v in props.items() if v is not None}}


def nombre_splitter(texto: str) -> str:
    """'SPL SECUNDARIO 1X8 MUFA LA JOYA OLT ALAMO 0/ 0/2 -17 dBm' -> 'SPL SECUNDARIO 1X8 MUFA LA JOYA': the OLT, its
    port and the power go to their own properties (the full text stays in `texto_visio`)."""
    t = _POTENCIA.sub(" ", " ".join(str(texto or "").split()))
    t = re.sub(r"\b(?:DEL\s+|EN\s+)?OLT\b.*$|\bP(?:UERTO|TO)?\.?\s*\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{1,2}.*$", " ", t, flags=re.I)
    t = _PUERTO_OLT.sub(" ", t)
    return (" ".join(t.split()).strip(" :-/,(") or " ".join(str(texto).split()))[:60]


def alto_etiqueta(nombre: str, propiedades: dict[str, Any]) -> int:
    """Height of the label under a splitter in the mufa editor (same estimate as editor_mufa.js)."""
    lineas = -(-len(nombre) // 17) + 1 + bool(propiedades.get("olt") or propiedades.get("puerto_olt")) + bool(propiedades.get("depende_de"))
    return lineas * 14 + 6


def _clave_texto(texto: str) -> str:
    """Same splitter written in two Visio files: the text without the measured power."""
    return _comparable(_POTENCIA.sub(" ", texto or ""))


def leer_servicio(texto: str) -> dict[str, Any] | None:
    """'C35896 Roger David Vallecillo Lanzas/ID496760/-24.59dBm' -> code, name and service id; None if empty / free."""
    t = " ".join(str(texto or "").split())
    if not t or _VACIO.match(t):
        return None
    codigo = (m.group(0).upper() if (m := _CODIGO.search(t)) else None)
    id_servicio = (re.sub(r"\s+", "", m.group(0)).upper() if (m := _ID.search(t)) else None)
    nombre = _POTENCIA.sub(" ", _ID.sub(" ", _CODIGO.sub(" ", t)))
    nombre = " ".join(re.sub(r"\||(?<!\d)/|/(?!\d)", " ", nombre).split()).strip(" -–/,.") or None   # keeps "1/16", "0/2/0"
    if not (codigo or nombre or id_servicio):
        return None
    return {"codigo_cliente": codigo, "nombre": (nombre or "")[:200] or None, "id_servicio": id_servicio}


# --------------------------------------------------------------------------- plan

@dataclass
class Contenido:
    splitters: list[dict[str, Any]] = field(default_factory=list)
    clientes: list[dict[str, Any]] = field(default_factory=list)          # of a mufa, without a known port
    ubicaciones: dict[str, dict[str, Any]] = field(default_factory=dict)  # client code -> point from the KMZ
    empalmes: list[dict[str, Any]] = field(default_factory=list)
    omitidos: list[dict[str, Any]] = field(default_factory=list)


def planificar_contenido(fuente: Any, kmz: Any, plan: Plan) -> Contenido:
    """What phase 3 would create inside the mufas of `plan` (nothing is written)."""
    cont = Contenido()
    elementos = {e["clave"]: e for e in plan.elementos if e["tipo"] in ("mufa", "nodo", "odf")}
    nodo_clave = {i: k for i, k in plan.clave_de.items() if k in elementos}
    servicios = [dict(f) for f in fuente.execute(
        "SELECT id, nodo_id, archivo_id, tipo, codigo_cliente, id_servicio, descripcion FROM red_fibra.servicios "
        "WHERE nodo_id = ANY(%s) ORDER BY id", (list(nodo_clave),)).fetchall()]
    omitir = lambda entidad, clave, nombre, motivo: cont.omitidos.append({"entidad": entidad, "clave": clave, "nombre": nombre, "motivo": motivo})

    # 1) splitters named in the mufa (one per distinct text)
    por_clave: dict[str, dict[str, Any]] = {}

    def splitter(elemento: str, texto: str, origen: str) -> dict[str, Any] | None:
        datos = leer_splitter(texto)
        nombre = nombre_splitter(texto)
        if datos["salidas"] is None:
            omitir("splitter", elemento, f"{elementos[elemento]['nombre']}: {nombre}", "no dice el tamaño (1x8, 1/16…)")
            return None
        if datos["salidas"] not in SALIDAS:
            omitir("splitter", elemento, f"{elementos[elemento]['nombre']}: {nombre}", f"1x{datos['salidas']} no existe: revisar el Visio")
            return None
        clave = f"{elemento}|SPL|{_clave_texto(texto)}"
        if clave not in por_clave:
            por_clave[clave] = {"elemento": elemento, "clave": clave, "nombre": nombre, **datos, "puertos": {}, "origen": origen,
                                "fuente": "texto_diagrama", "confianza": "media"}
            cont.splitters.append(por_clave[clave])
        return por_clave[clave]

    for s in servicios:
        if s["tipo"] != "splitter" or not s["descripcion"] or _NUMERADO.match(s["descripcion"]):
            continue                      # "38- SPL 1X8 MF GOMPER": a fibre / port that goes to another mufa
        if re.search(r"\bSPL|SPLITTER", s["descripcion"], re.I):
            splitter(nodo_clave[s["nodo_id"]], s["descripcion"], "texto")

    # 2) numbered port lists "SPL 1X8 …" + "1- C24712 …", tied to the mufa by the lines servicios read
    por_archivo: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for s in servicios:
        por_archivo[s["archivo_id"]].append(s)
    bloques = fuente.execute("SELECT id, archivo_id, texto FROM red_fibra.textos_crudos WHERE archivo_id = ANY(%s) "
                             "AND texto ~* 'SPL|SPLITTER' ORDER BY id", (list(por_archivo),)).fetchall()
    for b in bloques:
        lineas = [x.strip() for x in b["texto"].splitlines() if x.strip()]
        numeradas = [(int(m.group(1)), m.group(2).strip()) for x in lineas if (m := _NUMERADO.match(x))]
        if len(numeradas) < 2:
            continue
        cabecera = next((x for x in lineas if not _NUMERADO.match(x) and re.search(r"\bSPL|SPLITTER", x, re.I) and tamano(x)), None)
        votos = collections.Counter(s["nodo_id"] for s in por_archivo[b["archivo_id"]] if s["descripcion"] and s["descripcion"].strip() in lineas)
        mejores = [n for n, v in votos.items() if v == max(votos.values())] if votos else []
        claves = {nodo_clave[n] for n in mejores}
        resumen = " / ".join(lineas[:2])[:120]
        if cabecera is None:
            omitir("puertos", f"texto {b['id']}", resumen, "lista numerada sin un splitter con tamaño en su encabezado (¿lista de hilos?)")
            continue
        if len(claves) != 1:
            omitir("puertos", f"texto {b['id']}", resumen, "no se sabe de qué mufa es la lista" if not claves
                   else "la lista coincide con varias mufas: " + ", ".join(sorted(elementos[c]["nombre"] for c in claves))[:200])
            continue
        spl = splitter(claves.pop(), cabecera, "lista")
        if spl is None:
            continue
        if max(n for n, _ in numeradas) > spl["salidas"] or min(n for n, _ in numeradas) < 1:
            omitir("puertos", f"texto {b['id']}", resumen, f"la numeración pasa de las {spl['salidas']} salidas del splitter")
            continue
        for n, texto in numeradas:
            servicio = leer_servicio(texto)
            if servicio and n not in spl["puertos"]:
                spl["puertos"][n] = servicio

    # 3) clients listed in the mufa without a known port
    en_puerto = {(s["elemento"], p["codigo_cliente"]) for s in cont.splitters for p in s["puertos"].values() if p["codigo_cliente"]}
    vistos = set()
    for s in servicios:
        if s["tipo"] != "cliente":
            continue
        elemento = nodo_clave[s["nodo_id"]]
        datos = leer_servicio(re.sub(r"^\s*\d{1,2}\s*[-–.)]\s*", "", s["descripcion"] or ""))
        if datos is None:
            continue
        datos["codigo_cliente"] = (s["codigo_cliente"] or datos["codigo_cliente"] or "").upper() or None
        datos["id_servicio"] = (s["id_servicio"] or datos["id_servicio"] or "").upper() or None
        clave = (elemento, datos["codigo_cliente"] or _comparable(datos["nombre"]))
        if clave in vistos or (elemento, datos["codigo_cliente"]) in en_puerto:
            continue
        vistos.add(clave)
        cont.clientes.append({"elemento": elemento, **datos})

    # 4) where each client is: the far end of its drop in the KMZ (the end near its mufa is the mufa)
    mufas_de: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for s in cont.splitters:
        for p in s["puertos"].values():
            if p["codigo_cliente"]:
                mufas_de[p["codigo_cliente"]].append(elementos[s["elemento"]])
    for c in cont.clientes:
        if c["codigo_cliente"]:
            mufas_de[c["codigo_cliente"]].append(elementos[c["elemento"]])
    acometidas: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in kmz.execute(
            "SELECT id, nombre, ST_Y(ST_StartPoint(g)) la1, ST_X(ST_StartPoint(g)) lo1, ST_Y(ST_EndPoint(g)) la2, ST_X(ST_EndPoint(g)) lo2 "
            "FROM (SELECT id, nombre, ST_LineMerge(geom) g FROM red_lineas WHERE coalesce(nombre, '') ~* '^\\s*C[0-9]{4,6}') x "
            "WHERE GeometryType(g) = 'LINESTRING'").fetchall():
        m = _CODIGO.search(f["nombre"])
        if m:                                   # "C12345A…" (no word break) is not a client code
            acometidas[m.group(0).upper()].append(f)
    for codigo, mufas in mufas_de.items():
        ubicadas = [m for m in mufas if m["lat"] is not None]
        if not ubicadas or not acometidas.get(codigo):
            continue
        m = ubicadas[0]
        aqui = (float(m["lat"]), float(m["lon"]))
        mejor = None
        for a in acometidas[codigo]:
            d1, d2 = (metraje.longitud_m([aqui, (a["la1"], a["lo1"])]), metraje.longitud_m([aqui, (a["la2"], a["lo2"])]))
            cerca, lejos = (d1, (a["la2"], a["lo2"])) if d1 <= d2 else (d2, (a["la1"], a["lo1"]))
            if mejor is None or cerca < mejor[0]:
                mejor = (cerca, lejos, a)
        if mejor[0] > DISTANCIA_ACOMETIDA_M:
            omitir("cliente", codigo, codigo, f"su acometida del KMZ empieza a {mejor[0]:.0f} m de {m['nombre']}: no se ubica")
            continue
        nombre = " ".join(_CODIGO.sub(" ", mejor[2]["nombre"]).split()) or None
        cont.ubicaciones[codigo] = {"lat": mejor[1][0], "lon": mejor[1][1], "elemento": m["clave"], "kmz_linea_id": mejor[2]["id"],
                                    "nombre_kmz": nombre, "distancia_mufa_m": round(mejor[0], 1)}

    # 5) splices of the rings Excel: in mufa X, the fibre coming from the previous mufa <-> the fibre to the next one
    filas = [dict(f) for f in fuente.execute(
        "SELECT id, hoja, enlace, orden, nodo_id, en_mufa, de_mufa, hilo_entrante, hacia_mufa, hilo_saliente FROM red_fibra.anillo_tramos "
        "ORDER BY hoja, enlace, orden").fetchall()]
    por_orden = {(f["hoja"], f["enlace"], f["orden"]): f for f in filas}
    for f in filas:
        elemento = nodo_clave.get(f["nodo_id"])
        if elemento is None:
            continue
        antes, despues = por_orden.get((f["hoja"], f["enlace"], f["orden"] - 1)), por_orden.get((f["hoja"], f["enlace"], f["orden"] + 1))
        entra, sale = [int(x) for x in re.findall(r"\d{1,3}", f["hilo_entrante"] or "")], [int(x) for x in re.findall(r"\d{1,3}", f["hilo_saliente"] or "")]
        nombre = f"{f['hoja']} #{f['orden']} {elementos[elemento]['nombre']}"
        if not entra or len(entra) != len(sale):
            omitir("empalme", f"anillo {f['id']}", nombre, f"hilos no legibles o distintos: «{f['hilo_entrante']}» → «{f['hilo_saliente']}»")
            continue
        for a, b in zip(entra, sale):
            cont.empalmes.append({"elemento": elemento, "anillo_id": f["id"], "nombre": nombre, "hilo_entra": a, "hilo_sale": b,
                                  "de": {"clave": plan.clave_de.get(antes["nodo_id"]) if antes else None, "nombre": f["de_mufa"]},
                                  "hacia": {"clave": plan.clave_de.get(despues["nodo_id"]) if despues else None, "nombre": f["hacia_mufa"]}})
    return cont


# --------------------------------------------------------------------------- aplicar

def _alto_splitter(salidas: int) -> float:
    return max(36, salidas * 16 + 4)                  # as editor_mufa.js, to stack them in the middle column


def aplicar_contenido(con: Any, cont: Contenido, usuario_id: int | None, corrida_id: int) -> dict[str, int]:
    """Writes phase 3 in ONE transaction. What already exists (or a user changed) is not repeated."""
    conteo: collections.Counter = collections.Counter()
    logs: list[tuple] = []
    with con.transaction():
        elems = {f["clave"]: f for f in con.execute(
            "SELECT e.ref_visio ->> 'clave' AS clave, e.id, e.proyecto_id FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id "
            "WHERE e.borrado_en IS NULL AND p.es_red_base AND e.ref_visio ? 'clave'").fetchall()}
        # clients on the map (one element per code)
        clientes_id: dict[str, int] = {k.split("|", 1)[1]: f["id"] for k, f in elems.items() if k.startswith("CLIENTE|")}
        for codigo, u in sorted(cont.ubicaciones.items()):
            if codigo in clientes_id or u["elemento"] not in elems:
                continue
            fila = repositorio.insertar(con, "elementos", {
                "proyecto_id": elems[u["elemento"]]["proyecto_id"], "tipo": "cliente", "nombre": (u["nombre_kmz"] or codigo)[:160],
                "codigo": codigo, "ubicacion": f"SRID=4326;POINT({u['lon']:.8f} {u['lat']:.8f})", "ubicacion_fuente": "real",
                "propiedades": Jsonb({}), "ref_externa": Jsonb({"kmz": {"kmz_linea_id": u["kmz_linea_id"], "distancia_mufa_m": u["distancia_mufa_m"]}}),
                "fuente": "kmz", "confianza": "media", "estado_migracion": "automatica",
                "ref_visio": Jsonb({"clave": f"CLIENTE|{codigo}"})}, usuario_id)
            clientes_id[codigo] = fila["id"]
            conteo["clientes_en_mapa"] += 1
            logs.append(("cliente", codigo, "crear", "punta de su acometida del KMZ", None))
        # splitters, stacked in the middle column below what the mufa already has
        existentes = {f["clave"]: f for f in con.execute(
            "SELECT propiedades ->> 'clave_visio' AS clave, id, mufa_id, nombre, version FROM redes.splitters "
            "WHERE borrado_en IS NULL AND propiedades ? 'clave_visio'").fetchall()}
        # a mufa whose splitters nobody touched (all version 1, all from the Visio) is laid out again from the top
        tocadas = {f["mufa_id"] for f in con.execute(
            "SELECT DISTINCT mufa_id FROM redes.splitters WHERE borrado_en IS NULL AND (version > 1 OR NOT propiedades ? 'clave_visio') "
            "UNION SELECT DISTINCT mufa_id FROM redes.conectores WHERE borrado_en IS NULL").fetchall()}
        abajo = {f["mufa_id"]: f["y"] for f in con.execute(
            "SELECT mufa_id, max(y + greatest(36, salidas * 16 + 4) + 120) AS y FROM redes.splitters WHERE borrado_en IS NULL GROUP BY 1").fetchall()
            if f["mufa_id"] in tocadas}
        for s in cont.splitters:
            e = elems.get(s["elemento"])
            if e is None:
                continue
            ya = existentes.get(s["clave"])
            y = abajo.get(e["id"], 40)
            siguiente = y + _alto_splitter(s["salidas"]) + alto_etiqueta(s["nombre"], s["propiedades"]) + 20
            if ya is None:
                fila = repositorio.insertar(con, "splitters", {
                    "proyecto_id": e["proyecto_id"], "mufa_id": e["id"], "nombre": s["nombre"], "salidas": s["salidas"], "relacion": s["relacion"],
                    "x": 470, "y": y, "propiedades": Jsonb({**s["propiedades"], "clave_visio": s["clave"]}),
                    "fuente": s["fuente"], "confianza": s["confianza"]}, usuario_id)
                sid = fila["id"]
                mufa._crear_puertos(con, splitter_id=sid, salidas=s["salidas"])
                abajo[e["id"]] = siguiente
                conteo["splitters_creados"] += 1
                logs.append(("splitter", s["clave"], "crear", s["nombre"], None))
            else:
                sid = ya["id"]
                conteo["splitters_ya_estaban"] += 1
                if e["id"] not in tocadas and ya["version"] == 1:           # untouched: today's name and layout
                    con.execute("UPDATE redes.splitters SET nombre = %s, x = 470, y = %s, propiedades = %s WHERE id = %s",
                                (s["nombre"], y, Jsonb({**s["propiedades"], "clave_visio": s["clave"]}), sid))
                    abajo[e["id"]] = siguiente
                    conteo["splitters_reordenados"] += ya["nombre"] != s["nombre"]
            if not s["puertos"]:
                continue
            puertos = {f["numero"]: f["id"] for f in con.execute(
                "SELECT p.id, p.numero FROM redes.puertos p WHERE p.splitter_id = %s AND p.lado = 'salida' AND NOT EXISTS "
                "(SELECT 1 FROM redes.puerto_servicios x WHERE x.puerto_id = p.id AND x.borrado_en IS NULL)", (sid,)).fetchall()}
            for n, p in sorted(s["puertos"].items()):
                if n not in puertos:
                    continue                                   # already has its client (or the user set another one)
                repositorio.insertar(con, "puerto_servicios", {
                    "puerto_id": puertos[n], **p, "elemento_id": clientes_id.get(p["codigo_cliente"] or ""),
                    "fuente": "texto_diagrama", "confianza": "media"}, usuario_id)
                conteo["puertos_con_cliente"] += 1
        # clients of the mufa without a port
        ya = {(f["mufa_id"], f["k"]) for f in con.execute(
            "SELECT mufa_id, coalesce(codigo_cliente, nombre, id_servicio) AS k FROM redes.mufa_clientes WHERE borrado_en IS NULL").fetchall()}
        for c in cont.clientes:
            e = elems.get(c["elemento"])
            k = c["codigo_cliente"] or c["nombre"] or c["id_servicio"]
            if e is None or (e["id"], k) in ya:
                continue
            ya.add((e["id"], k))
            repositorio.insertar(con, "mufa_clientes", {
                "mufa_id": e["id"], "codigo_cliente": c["codigo_cliente"], "nombre": c["nombre"], "id_servicio": c["id_servicio"],
                "elemento_id": clientes_id.get(c["codigo_cliente"] or ""), "fuente": "texto_diagrama", "confianza": "media"}, usuario_id)
            conteo["clientes_de_mufa"] += 1
        # the fibre numbers of the rings Excel say how big the cables are at least
        _hilos_minimos_del_anillo(con, cont, elems, usuario_id, logs, conteo)
        # splices of the rings
        for x in cont.empalmes:
            e = elems.get(x["elemento"])
            if e is None:
                continue
            resultado = _empalmar(con, e, x, usuario_id)
            conteo[f"empalmes_{resultado[0]}"] += 1
            logs.append(("fusion", f"anillo {x['anillo_id']} H{x['hilo_entra']}-H{x['hilo_sale']}",
                         "crear" if resultado[0] == "creados" else "omitir", f"{x['nombre']}: {resultado[1]}", None))
        for o in cont.omitidos:
            logs.append((o["entidad"], o["clave"], "omitir", f"{o['nombre']}: {o['motivo']}"[:500], None))
        with con.cursor() as cur:
            cur.executemany("INSERT INTO redes.migracion_visio_log (corrida_id, entidad, clave, accion, resultado, avisos) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", [(corrida_id, *x) for x in logs])
    return dict(conteo)


def _hilos_minimos_del_anillo(con: Any, cont: Contenido, elems: dict[str, Any], usuario_id: int | None, logs: list[tuple],
                              conteo: collections.Counter) -> None:
    """A ring row that splices fibre 26 of a cable proves the cable has at least 26 fibres, so at least 48. The
    cables of the ring without a fibre count (or whose count was only deduced and is smaller) get that minimum,
    marked `estimado` / confianza baja / `configuracion_estimada`, so the splice can be created. A count that
    the Visio label states, or that a person edited or validated, is never changed."""
    regla = migrar_visio.reglas()
    if not regla["inferir_hilos"].get("minimo_del_anillo"):
        return
    maximo: dict[int, int] = {}
    for x in cont.empalmes:
        e = elems.get(x["elemento"])
        if e is None:
            continue
        entra, sale = _cable_hacia(con, e["id"], x["de"]), _cable_hacia(con, e["id"], x["hacia"])
        if entra is None or sale is None or entra["id"] == sale["id"]:
            continue
        for c, n in ((entra, x["hilo_entra"]), (sale, x["hilo_sale"])):
            maximo[c["id"]] = max(maximo.get(c["id"], 0), n)
    for cable_id, n in sorted(maximo.items()):
        c = con.execute("SELECT id, nombre, hilos, version, estado_migracion, proyecto_id, ref_visio FROM redes.cables WHERE id = %s", (cable_id,)).fetchone()
        origen = (c["ref_visio"] or {}).get("hilos_origen")
        nuevo = next((h for h in red.HILOS if h >= n), None)
        if nuevo is None or c["estado_migracion"] in migrar_visio.PROTEGIDOS:
            continue
        if c["hilos"] is not None and (c["hilos"] >= n or origen in ("visio", None)):
            continue                                            # it already fits, or the Visio label says its size
        por_buffer, _ = migrar_visio.configuracion(nuevo, regla)
        antes, despues = repositorio.actualizar(con, "cables", c["id"], c["version"], {
            "hilos": nuevo, "hilos_por_buffer": por_buffer, "color": migrar_visio.COLORES.get(nuevo, migrar_visio.COLOR_DESCONOCIDO),
            "configuracion_estimada": True, "fuente": "estimado", "confianza": "baja",
            "ref_visio": Jsonb({**(c["ref_visio"] or {}), "hilos_origen": "minimo_del_anillo", "hilos_anterior": c["hilos"]})}, usuario_id)
        mufa.sincronizar_hilos(con, c["id"], nuevo, usuario_id)
        repositorio.registrar(con, usuario_id, "cable", c["id"], "editar", repositorio.diferencias(antes, despues), proyecto_id=c["proyecto_id"])
        conteo["cables_hilos_minimo_del_anillo"] += 1
        logs.append(("enlace", (c["ref_visio"] or {}).get("clave", str(c["id"])), "actualizar",
                     f"{c['nombre']}: hilos {c['hilos'] or 'desconocidos'} → {nuevo} (el anillo usa el hilo {n}); estimado, por confirmar", None))


def _cable_hacia(con: Any, mufa_id: int, otro: dict[str, Any]) -> dict[str, Any] | None:
    """The cable between the mufa and the neighbour of the ring row (by its key, else by its name)."""
    cables = con.execute(
        "SELECT c.id, c.hilos, e.ref_visio ->> 'clave' AS clave, e.nombre FROM redes.cables c "
        "JOIN redes.elementos e ON e.id = CASE WHEN c.origen_id = %(m)s THEN c.destino_id ELSE c.origen_id END "
        "WHERE c.borrado_en IS NULL AND (c.origen_id = %(m)s OR c.destino_id = %(m)s)", {"m": mufa_id}).fetchall()
    por_clave = [c for c in cables if otro["clave"] and c["clave"] == otro["clave"]]
    if len(por_clave) == 1:
        return por_clave[0]
    por_nombre = [c for c in cables if _comparable(c["nombre"]) == _comparable(otro["nombre"])]
    return por_nombre[0] if len(por_nombre) == 1 else None


def _empalmar(con: Any, e: dict[str, Any], x: dict[str, Any], usuario_id: int | None) -> tuple[str, str]:
    entra, sale = _cable_hacia(con, e["id"], x["de"]), _cable_hacia(con, e["id"], x["hacia"])
    if entra is None or sale is None:
        falta = (x["de"] if entra is None else x["hacia"])["nombre"]
        if _comparable(falta).startswith("ODF"):
            # the ring goes in or out through an ODF of the node (a patch panel): the Visio does not draw the cable between that ODF and this mufa.
            # Not a cable that failed to migrate: a gap of the diagrams to review with Planta Externa (it has its own count, empalmes_odf)
            return "odf", f"el anillo entra o sale por «{falta}» y el Visio no dibuja el cable entre esa ODF y la mufa: revisar con Planta Externa"
        return "sin_cable", f"no hay cable migrado hacia {falta}"
    if entra["id"] == sale["id"]:
        return "sin_cable", "la entrada y la salida son el mismo cable"
    for c, n in ((entra, x["hilo_entra"]), (sale, x["hilo_sale"])):
        if c["hilos"] is None:
            return "hilos_desconocidos", f"el cable hacia {c['nombre']} no tiene la cantidad de hilos"
        if n > c["hilos"]:
            return "fuera_de_rango", f"hilo {n} en un cable de {c['hilos']} hilos (hacia {c['nombre']})"
    hilos = {(f["cable_id"], f["numero"]): f["id"] for f in con.execute(
        "SELECT id, cable_id, numero FROM redes.hilos WHERE borrado_en IS NULL AND ((cable_id = %s AND numero = %s) OR (cable_id = %s AND numero = %s))",
        (entra["id"], x["hilo_entra"], sale["id"], x["hilo_sale"])).fetchall()}
    a, b = hilos.get((entra["id"], x["hilo_entra"])), hilos.get((sale["id"], x["hilo_sale"]))
    if a is None or b is None:
        return "fuera_de_rango", "el hilo no existe en el cable"
    if con.execute("SELECT 1 FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL AND (a_hilo_id = ANY(%s) OR b_hilo_id = ANY(%s))",
                   (e["id"], [a, b], [a, b])).fetchone():
        return "ya_conectados", "uno de los hilos ya está conectado en esta mufa"
    repositorio.insertar(con, "conexiones", {"proyecto_id": e["proyecto_id"], "mufa_id": e["id"], "a_hilo_id": a, "b_hilo_id": b,
                                             "fuente": "excel_anillos", "confianza": "alta"}, usuario_id)
    return "creados", f"H{x['hilo_entra']} ({entra['nombre']}) ↔ H{x['hilo_sale']} ({sale['nombre']})"
