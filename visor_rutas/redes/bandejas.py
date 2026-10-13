"""Modelo de la mufa y sus bandejas (migración Visio, fase 4: regla 6.5 y sección 8 de docs/migracion_visio/PLAN.md).

- **Modelo:** capacidad 48 (2 bandejas) o 96 (4), formato domo / horizontal / desconocido. Si nadie lo
  dijo, lo elige la regla y queda `modelo_estimado`: el cable mayor que llega a la mufa (hasta 48 hilos
  → 48; hasta 96 → 96; más → aviso) y que cada splitter necesita su propia bandeja.
- **Bandejas:** 24 empalmes cada una (`business_rules.yaml` → `migracion_visio.empalmes_por_bandeja`).
  Una bandeja con un splitter 1xN admite solo sus N salidas más la entrada (si
  `entrada_splitter_ocupa_posicion`): 1x8 → 9 posiciones, la 1 es la entrada y la n+1 la salida n.
- **Ubicación por defecto:** los splitters, desde la última bandeja hacia la 1; los empalmes directos
  (hilo con hilo) llenan desde la bandeja 1 en orden de cable, buffer e hilo. Lo que pone la regla queda
  `posicion_estimada`; lo que el usuario mueve, no.
"""
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import proyectos, repositorio
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

FORMATOS = ("domo", "horizontal", "desconocido")
DEFECTO = {"empalmes_por_bandeja": 24, "capacidades_mufa": {48: 2, 96: 4}, "entrada_splitter_ocupa_posicion": True}


def reglas(rules: dict[str, Any] | None = None) -> dict[str, Any]:
    if rules is None:
        try:
            from config import get_settings, load_rules
            rules = load_rules(get_settings().rules_path)
        except Exception:
            rules = {}
    r = {**DEFECTO, **{k: v for k, v in ((rules or {}).get("migracion_visio") or {}).items() if k in DEFECTO}}
    r["capacidades_mufa"] = {int(k): int(v) for k, v in r["capacidades_mufa"].items()}
    return r


def posiciones_splitter(salidas: int, r: dict[str, Any]) -> int:
    return salidas + (1 if r["entrada_splitter_ocupa_posicion"] else 0)


def elegir_modelo(hilos_mufa: int | None, salidas_splitters: list[int], r: dict[str, Any], *, sangria: bool = False) -> dict[str, Any]:
    """Capacity, trays, why and warnings for a mufa nobody described (rule 6.5)."""
    capacidades = sorted(r["capacidades_mufa"])
    motivos, avisos = [], []
    if hilos_mufa:
        capacidad = next((c for c in capacidades if hilos_mufa <= c), capacidades[-1])
        motivos.append(f"cable mayor de {hilos_mufa} hilos")
        if hilos_mufa > capacidades[-1]:
            avisos.append(f"excede la capacidad: cable de {hilos_mufa} hilos en una mufa de {capacidades[-1]}, revisar")
    else:
        capacidad = capacidades[0]
        motivos.append(f"sin cables con hilos conocidos: {capacidades[0]} por defecto")
    caben = [s for s in salidas_splitters if posiciones_splitter(s, r) <= r["empalmes_por_bandeja"]]
    for s in salidas_splitters:
        if s not in caben:
            avisos.append(f"un splitter 1x{s} no cabe en una bandeja ({posiciones_splitter(s, r)} posiciones > {r['empalmes_por_bandeja']})")
    necesarias = len(caben) + 1                          # one tray each splitter + one for direct splices
    if caben and necesarias > r["capacidades_mufa"][capacidad]:
        mayor = next((c for c in capacidades if r["capacidades_mufa"][c] >= necesarias), capacidades[-1])
        if mayor != capacidad:
            capacidad = mayor
            motivos.append(f"{len(caben)} splitter{'s' if len(caben) > 1 else ''} (una bandeja cada uno) + empalmes directos")
        if necesarias > r["capacidades_mufa"][capacidad]:
            avisos.append(f"{len(caben)} splitters + empalmes directos no caben en {r['capacidades_mufa'][capacidad]} bandejas, revisar")
    if sangria:
        motivos.append("sangría: los hilos sangrados no están escritos")
    return {"capacidad": capacidad, "bandejas": r["capacidades_mufa"][capacidad], "motivo": "; ".join(motivos), "avisos": avisos}


def formato_de_texto(texto: str) -> str:
    t = (texto or "").upper()
    return "domo" if "DOMO" in t else "horizontal" if "HORIZONTAL" in t else "desconocido"


# --------------------------------------------------------------------------- lectura

def leer(con: Any, mufa_id: int) -> dict[str, Any]:
    """{"modelo": {...} | None, "bandejas": [...]} for the mufa editor."""
    m = con.execute("SELECT id, formato, capacidad, empalmes_por_bandeja, bandejas, modelo_estimado, fuente, motivo, avisos, version "
                    "FROM redes.mufa_modelos WHERE mufa_id = %s AND borrado_en IS NULL", (mufa_id,)).fetchone()
    if m is None:
        return {"modelo": None, "bandejas": []}
    bandejas = [dict(b) for b in con.execute(
        "SELECT numero, capacidad, splitter_id, version FROM redes.mufa_bandejas WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY numero",
        (mufa_id,)).fetchall()]
    return {"modelo": dict(m), "bandejas": bandejas}


def hilos_mufa(con: Any, mufa_id: int) -> int | None:
    return con.execute("SELECT max(hilos) AS h FROM redes.cables WHERE borrado_en IS NULL AND (origen_id = %(m)s OR destino_id = %(m)s)",
                       {"m": mufa_id}).fetchone()["h"]


# --------------------------------------------------------------------------- ubicar

def crear_modelo(con: Any, mufa_id: int, usuario_id: int | None, r: dict[str, Any], *, capacidad: int | None = None,
                 formato: str = "desconocido", sangria: bool = False) -> dict[str, Any]:
    """Model + trays for a mufa that has none, then its splitters and splices in them. Returns the
    model and the warnings of what did not fit."""
    salidas = [f["salidas"] for f in con.execute("SELECT salidas FROM redes.splitters WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY id",
                                                 (mufa_id,)).fetchall()]
    eleccion = elegir_modelo(hilos_mufa(con, mufa_id), salidas, r, sangria=sangria)
    estimado = capacidad is None
    if capacidad is not None:
        eleccion = {"capacidad": capacidad, "bandejas": r["capacidades_mufa"][capacidad], "motivo": "elegido por el usuario", "avisos": []}
    repositorio.insertar(con, "mufa_modelos", {
        "mufa_id": mufa_id, "formato": formato, "capacidad": eleccion["capacidad"], "empalmes_por_bandeja": r["empalmes_por_bandeja"],
        "bandejas": eleccion["bandejas"], "modelo_estimado": estimado, "fuente": "estimado" if estimado else "usuario",
        "motivo": eleccion["motivo"], "avisos": Jsonb(eleccion["avisos"])}, usuario_id)
    for n in range(1, eleccion["bandejas"] + 1):
        repositorio.insertar(con, "mufa_bandejas", {"mufa_id": mufa_id, "numero": n, "capacidad": r["empalmes_por_bandeja"],
                                                    "fuente": "estimado" if estimado else "usuario"}, usuario_id)
    avisos = eleccion["avisos"] + ubicar_splitters(con, mufa_id, r) + ubicar_empalmes(con, mufa_id, r)
    return {**eleccion, "avisos": avisos}


def _ocupadas_directas(con: Any, mufa_id: int) -> set[int]:
    return {f["bandeja"] for f in con.execute(
        "SELECT DISTINCT x.bandeja FROM redes.conexiones x WHERE x.mufa_id = %s AND x.borrado_en IS NULL AND x.bandeja IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM redes.puertos p WHERE p.id IN (x.a_puerto_id, x.b_puerto_id) AND p.splitter_id IS NOT NULL)",
        (mufa_id,)).fetchall()}


def ubicar_splitters(con: Any, mufa_id: int, r: dict[str, Any]) -> list[str]:
    """Splitters without a tray -> the highest free tray (no splitter, no direct splice), down to tray 2:
    tray 1 stays for the direct splices (a user may still put a splitter there). Returns warnings."""
    bandejas = con.execute("SELECT id, numero, splitter_id FROM redes.mufa_bandejas WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY numero DESC",
                           (mufa_id,)).fetchall()
    if not bandejas:
        return []
    ocupadas = _ocupadas_directas(con, mufa_id)
    libres = [b for b in bandejas if b["splitter_id"] is None and b["numero"] not in ocupadas and b["numero"] > 1]
    avisos = []
    for s in con.execute("SELECT s.id, s.nombre, s.salidas FROM redes.splitters s WHERE s.mufa_id = %s AND s.borrado_en IS NULL "
                         "AND NOT EXISTS (SELECT 1 FROM redes.mufa_bandejas b WHERE b.splitter_id = s.id AND b.borrado_en IS NULL) ORDER BY s.id",
                         (mufa_id,)).fetchall():
        posiciones = posiciones_splitter(s["salidas"], r)
        if posiciones > r["empalmes_por_bandeja"]:
            avisos.append(f"{s['nombre']} (1x{s['salidas']}) no cabe en una bandeja")
            continue
        if not libres:
            avisos.append(f"{s['nombre']}: no hay bandeja libre (la 1 queda para los empalmes directos; cambie el modelo o asígnelo a mano)")
            continue
        b = libres.pop(0)
        con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s, capacidad = %s WHERE id = %s", (s["id"], posiciones, b["id"]))
    return avisos


def _orden_hilo(con: Any, hilo_id: int | None) -> tuple:
    if hilo_id is None:
        return (1e12, 0, 0)
    h = con.execute("SELECT cable_id, buffer, numero FROM redes.hilos WHERE id = %s", (hilo_id,)).fetchone()
    return (h["cable_id"], h["buffer"] or 0, h["numero"])


def ubicar_empalmes(con: Any, mufa_id: int, r: dict[str, Any]) -> list[str]:
    """Splices without a position: the ones of a splitter port go to that splitter's tray (input = 1,
    output n = n + 1); fibre-to-fibre (or fibre-to-connector) fill the trays without splitter from 1, in
    order of cable, buffer and fibre. Port-to-port connections are not splices. Returns warnings."""
    bandejas = {b["numero"]: b for b in con.execute(
        "SELECT numero, capacidad, splitter_id FROM redes.mufa_bandejas WHERE mufa_id = %s AND borrado_en IS NULL ORDER BY numero",
        (mufa_id,)).fetchall()}
    if not bandejas:
        return []
    de_splitter = {b["splitter_id"]: n for n, b in bandejas.items() if b["splitter_id"]}
    usadas = {(f["bandeja"], f["posicion_en_bandeja"]) for f in con.execute(
        "SELECT bandeja, posicion_en_bandeja FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL AND bandeja IS NOT NULL",
        (mufa_id,)).fetchall()}
    pendientes = con.execute(
        "SELECT x.id, x.a_hilo_id, x.b_hilo_id, pa.splitter_id AS a_spl, pa.lado AS a_lado, pa.numero AS a_num, pa.conector_id AS a_con, "
        "pb.splitter_id AS b_spl, pb.lado AS b_lado, pb.numero AS b_num, pb.conector_id AS b_con FROM redes.conexiones x "
        "LEFT JOIN redes.puertos pa ON pa.id = x.a_puerto_id LEFT JOIN redes.puertos pb ON pb.id = x.b_puerto_id "
        "WHERE x.mufa_id = %s AND x.borrado_en IS NULL AND x.bandeja IS NULL ORDER BY x.id", (mufa_id,)).fetchall()
    avisos, directas = [], []
    for x in pendientes:
        hilos = [h for h in (x["a_hilo_id"], x["b_hilo_id"]) if h]
        spl = [(x[p + "_spl"], x[p + "_lado"], x[p + "_num"]) for p in ("a", "b") if x[p + "_spl"]]
        if spl and hilos:                                # a fibre on a splitter port: that splitter's tray
            sid, lado, numero = spl[0]
            if sid not in de_splitter:
                avisos.append("un empalme de un splitter sin bandeja queda sin posición")
                continue
            pos = 1 if lado == "entrada" else numero + (1 if r["entrada_splitter_ocupa_posicion"] else 0)
            if (de_splitter[sid], pos) not in usadas:
                _poner(con, x["id"], de_splitter[sid], pos)
                usadas.add((de_splitter[sid], pos))
        elif hilos:                                      # fibre-fibre or fibre-connector: a direct splice
            directas.append(x)
    directas.sort(key=lambda x: min(_orden_hilo(con, x["a_hilo_id"]), _orden_hilo(con, x["b_hilo_id"])))
    libres = [(n, p) for n, b in bandejas.items() if not b["splitter_id"] for p in range(1, b["capacidad"] + 1) if (n, p) not in usadas]
    for x in directas:
        if not libres:
            avisos.append(f"{len(directas) - directas.index(x)} empalmes directos no caben en las bandejas del modelo")
            break
        n, p = libres.pop(0)
        _poner(con, x["id"], n, p)
    return avisos


def _poner(con: Any, conexion_id: int, bandeja: int, posicion: int, estimada: bool = True) -> None:
    con.execute("UPDATE redes.conexiones SET bandeja = %s, posicion_en_bandeja = %s, posicion_estimada = %s WHERE id = %s",
                (bandeja, posicion, estimada, conexion_id))


def liberar_splitter(con: Any, splitter_id: int, r: dict[str, Any]) -> None:
    """A deleted splitter frees its tray (back to 24 positions)."""
    con.execute("UPDATE redes.mufa_bandejas SET splitter_id = NULL, capacidad = %s WHERE splitter_id = %s AND borrado_en IS NULL",
                (r["empalmes_por_bandeja"], splitter_id))


# --------------------------------------------------------------------------- operaciones del editor (API)

def _mufa_editable(con: Any, actor: dict[str, Any], mufa_id: int) -> dict[str, Any]:
    m = con.execute("SELECT id, proyecto_id, tipo, nombre FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(mufa_id),)).fetchone()
    if m is None or m["tipo"] not in ("mufa", "nodo", "odf"):
        raise NoEncontrado("La mufa no existe (o fue eliminada)")
    if not proyectos.puede_editar(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    return dict(m)


def guardar_modelo(con: Any, actor: dict[str, Any], *, mufa_id: int, capacidad: int, formato: str = "desconocido") -> dict[str, Any]:
    """The user states the model: 48 / 96 and the format. Going smaller only if the trays that disappear are empty."""
    from visor_rutas.redes import mufa as mufa_mod
    m = _mufa_editable(con, actor, mufa_id)
    r = reglas()
    try:
        capacidad = int(capacidad)
    except (TypeError, ValueError):
        capacidad = 0
    if capacidad not in r["capacidades_mufa"]:
        raise DatosInvalidos({"modelo": "capacidad: " + " o ".join(str(c) for c in sorted(r["capacidades_mufa"]))})
    if formato not in FORMATOS:
        raise DatosInvalidos({"modelo": "formato: domo, horizontal o desconocido"})
    with con.transaction():
        con.execute("SELECT 1 FROM redes.elementos WHERE id = %s FOR UPDATE", (m["id"],))
        actual = con.execute("SELECT * FROM redes.mufa_modelos WHERE mufa_id = %s AND borrado_en IS NULL", (m["id"],)).fetchone()
        if actual is None:
            crear_modelo(con, m["id"], actor["id"], r, capacidad=capacidad, formato=formato)
            cambio = {"modelo": [None, f"{capacidad} hilos, {formato}"]}
        else:
            nuevas = r["capacidades_mufa"][capacidad]
            if nuevas < actual["bandejas"]:
                ocupadas = con.execute(
                    "SELECT DISTINCT b.numero FROM redes.mufa_bandejas b WHERE b.mufa_id = %(m)s AND b.borrado_en IS NULL AND b.numero > %(n)s "
                    "AND (b.splitter_id IS NOT NULL OR EXISTS (SELECT 1 FROM redes.conexiones x WHERE x.mufa_id = %(m)s AND x.borrado_en IS NULL "
                    "AND x.bandeja = b.numero)) ORDER BY 1", {"m": m["id"], "n": nuevas}).fetchall()
                if ocupadas:
                    raise DatosInvalidos({"modelo": "las bandejas " + ", ".join(str(o["numero"]) for o in ocupadas)
                                                    + " tienen splitters o empalmes: muévalos antes de achicar el modelo"})
                con.execute("UPDATE redes.mufa_bandejas SET borrado_en = now() WHERE mufa_id = %s AND numero > %s AND borrado_en IS NULL",
                            (m["id"], nuevas))
            for n in range(actual["bandejas"] + 1, nuevas + 1):
                repositorio.insertar(con, "mufa_bandejas", {"mufa_id": m["id"], "numero": n, "capacidad": r["empalmes_por_bandeja"],
                                                            "fuente": "usuario"}, actor["id"])
            con.execute("UPDATE redes.mufa_modelos SET capacidad = %s, bandejas = %s, formato = %s, modelo_estimado = false, fuente = 'usuario', "
                        "motivo = 'elegido por el usuario', avisos = '[]', version = version + 1, actualizado_en = now(), actualizado_por = %s "
                        "WHERE id = %s", (capacidad, nuevas, formato, actor["id"], actual["id"]))
            ubicar_splitters(con, m["id"], r)
            ubicar_empalmes(con, m["id"], r)
            cambio = {"modelo": [f"{actual['capacidad']} hilos, {actual['formato']}", f"{capacidad} hilos, {formato}"]}
        repositorio.registrar(con, actor["id"], "elemento", m["id"], "editar", cambio, proyecto_id=m["proyecto_id"])
    return mufa_mod.leer(con, actor, mufa_id=m["id"])


def mover_empalme(con: Any, actor: dict[str, Any], *, conexion_id: int, bandeja: int, posicion: int) -> dict[str, Any]:
    """Drag a direct splice to another tray / position (if taken by another direct splice, they swap).
    A splitter's splices stay in its tray, on the position of their port."""
    from visor_rutas.redes import mufa as mufa_mod
    x = con.execute("SELECT * FROM redes.conexiones WHERE id = %s AND borrado_en IS NULL", (int(conexion_id),)).fetchone()
    if x is None:
        raise NoEncontrado("El empalme ya no existe: recargue la mufa")
    m = _mufa_editable(con, actor, x["mufa_id"])
    bandeja, posicion = int(bandeja or 0), int(posicion or 0)
    with con.transaction():
        b = con.execute("SELECT numero, capacidad, splitter_id FROM redes.mufa_bandejas WHERE mufa_id = %s AND numero = %s AND borrado_en IS NULL",
                        (m["id"], bandeja)).fetchone()
        if b is None or not 1 <= posicion <= b["capacidad"]:
            raise DatosInvalidos({"empalme": "esa bandeja o posición no existe en el modelo de la mufa"})
        de_splitter = con.execute("SELECT 1 FROM redes.puertos WHERE id IN (%s, %s) AND splitter_id IS NOT NULL",
                                  (x["a_puerto_id"], x["b_puerto_id"])).fetchone()
        if de_splitter or b["splitter_id"]:
            raise DatosInvalidos({"empalme": "los empalmes de un splitter van en la bandeja del splitter, en la posición de su puerto"})
        otro = con.execute("SELECT id FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL AND bandeja = %s AND posicion_en_bandeja = %s "
                           "AND id <> %s", (m["id"], bandeja, posicion, x["id"])).fetchone()
        if otro:                                         # swap: free this one's slot first (one splice per position)
            _poner(con, x["id"], None, None, False)
            _poner(con, otro["id"], x["bandeja"], x["posicion_en_bandeja"], False)
        _poner(con, x["id"], bandeja, posicion, False)
        con.execute("UPDATE redes.conexiones SET version = version + 1, actualizado_en = now(), actualizado_por = %s WHERE id = ANY(%s)",
                    (actor["id"], [x["id"]] + ([otro["id"]] if otro else [])))
        repositorio.registrar(con, actor["id"], "conexion", x["id"], "editar",
                              {"bandeja": [f"{x['bandeja']}·{x['posicion_en_bandeja']}", f"{bandeja}·{posicion}"]}, proyecto_id=m["proyecto_id"])
    return mufa_mod.leer(con, actor, mufa_id=m["id"])


def bandeja_splitter(con: Any, actor: dict[str, Any], *, mufa_id: int, numero: int, splitter_id: int | None = None) -> dict[str, Any]:
    """Puts a splitter in a tray (or leaves the tray for direct splices). The tray must not have direct splices."""
    from visor_rutas.redes import mufa as mufa_mod
    m = _mufa_editable(con, actor, mufa_id)
    r = reglas()
    with con.transaction():
        b = con.execute("SELECT id, splitter_id FROM redes.mufa_bandejas WHERE mufa_id = %s AND numero = %s AND borrado_en IS NULL",
                        (m["id"], int(numero))).fetchone()
        if b is None:
            raise DatosInvalidos({"bandeja": "la bandeja no existe en el modelo"})
        sid = int(splitter_id) if splitter_id not in (None, "") else None
        s = None
        if sid is not None:
            s = con.execute("SELECT id, nombre, salidas FROM redes.splitters WHERE id = %s AND mufa_id = %s AND borrado_en IS NULL",
                            (sid, m["id"])).fetchone()
            if s is None:
                raise DatosInvalidos({"bandeja": "el splitter no está en esta mufa"})
            if posiciones_splitter(s["salidas"], r) > r["empalmes_por_bandeja"]:
                raise DatosInvalidos({"bandeja": f"un 1x{s['salidas']} no cabe en una bandeja"})
            if int(numero) in _ocupadas_directas(con, m["id"]):
                raise DatosInvalidos({"bandeja": "la bandeja tiene empalmes directos: muévalos a otra antes"})
        # the splitters involved lose their positions; they get them again in their new tray
        for viejo in {sid, b["splitter_id"]} - {None}:
            con.execute("UPDATE redes.conexiones SET bandeja = NULL, posicion_en_bandeja = NULL WHERE mufa_id = %s AND borrado_en IS NULL AND "
                        "(a_puerto_id IN (SELECT id FROM redes.puertos WHERE splitter_id = %s) OR b_puerto_id IN (SELECT id FROM redes.puertos "
                        "WHERE splitter_id = %s))", (m["id"], viejo, viejo))
            liberar_splitter(con, viejo, r)
        if s is not None:
            con.execute("UPDATE redes.mufa_bandejas SET splitter_id = %s, capacidad = %s, fuente = 'usuario' WHERE id = %s",
                        (s["id"], posiciones_splitter(s["salidas"], r), b["id"]))
        ubicar_empalmes(con, m["id"], r)
        repositorio.registrar(con, actor["id"], "elemento", m["id"], "editar",
                              {f"bandeja {numero}": [b["splitter_id"], s["nombre"] if s else None]}, proyecto_id=m["proyecto_id"])
    return mufa_mod.leer(con, actor, mufa_id=m["id"])


# --------------------------------------------------------------------------- migración (todas las mufas migradas)

def _intacto(con: Any, mufa_id: int) -> bool:
    """The model, trays and positions are still the rule's: nobody set the model, a tray or moved a splice."""
    return con.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM redes.mufa_modelos WHERE mufa_id = %(m)s AND borrado_en IS NULL AND (NOT modelo_estimado OR version > 1)) "
        "AND NOT EXISTS (SELECT 1 FROM redes.mufa_bandejas WHERE mufa_id = %(m)s AND borrado_en IS NULL AND fuente IS DISTINCT FROM 'estimado') "
        "AND NOT EXISTS (SELECT 1 FROM redes.conexiones WHERE mufa_id = %(m)s AND borrado_en IS NULL AND bandeja IS NOT NULL "
        "AND NOT posicion_estimada) AS intacto", {"m": mufa_id}).fetchone()["intacto"]


def _quitar_modelo(con: Any, mufa_id: int) -> None:
    con.execute("UPDATE redes.conexiones SET bandeja = NULL, posicion_en_bandeja = NULL WHERE mufa_id = %s AND borrado_en IS NULL", (mufa_id,))
    con.execute("UPDATE redes.mufa_bandejas SET borrado_en = now() WHERE mufa_id = %s AND borrado_en IS NULL", (mufa_id,))
    con.execute("UPDATE redes.mufa_modelos SET borrado_en = now() WHERE mufa_id = %s AND borrado_en IS NULL", (mufa_id,))


def migrar_modelos(con: Any, usuario_id: int | None, r: dict[str, Any] | None = None) -> dict[str, int]:
    """Model + trays for every migrated mufa (base projects, not reserves) that has none yet. A model
    still exactly as the rule left it is rebuilt if today's rule decides otherwise (capacity, or a
    splitter in tray 1); anything a user touched stays."""
    r = r or reglas()
    conteo: dict[str, int] = {}
    with con.transaction():
        for e in con.execute(
                "SELECT e.id FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id "
                "JOIN redes.mufa_modelos m ON m.mufa_id = e.id AND m.borrado_en IS NULL AND m.modelo_estimado "
                "WHERE p.es_red_base AND e.borrado_en IS NULL AND e.tipo = 'mufa' AND coalesce(e.subtipo, '') <> 'reserva' ORDER BY e.id").fetchall():
            actual = leer(con, e["id"])
            salidas = [f["salidas"] for f in con.execute("SELECT salidas FROM redes.splitters WHERE mufa_id = %s AND borrado_en IS NULL",
                                                         (e["id"],)).fetchall()]
            regla = elegir_modelo(hilos_mufa(con, e["id"]), salidas, r)
            distinto = regla["capacidad"] != actual["modelo"]["capacidad"] or any(b["numero"] == 1 and b["splitter_id"] for b in actual["bandejas"])
            if distinto and _intacto(con, e["id"]):
                _quitar_modelo(con, e["id"])
                conteo["modelos_recalculados"] = conteo.get("modelos_recalculados", 0) + 1
        for e in con.execute(
                "SELECT e.id, e.propiedades, e.ref_visio FROM redes.elementos e JOIN redes.proyectos p ON p.id = e.proyecto_id "
                "WHERE p.es_red_base AND e.borrado_en IS NULL AND e.tipo = 'mufa' AND coalesce(e.subtipo, '') <> 'reserva' "
                "AND NOT EXISTS (SELECT 1 FROM redes.mufa_modelos m WHERE m.mufa_id = e.id AND m.borrado_en IS NULL) ORDER BY e.id").fetchall():
            notas = " ".join(str(x) for x in ((e["propiedades"] or {}).get("notas") or [])) + " " + str((e["ref_visio"] or {}).get("notas") or "")
            hecho = crear_modelo(con, e["id"], usuario_id, r, formato=formato_de_texto(notas), sangria="SANGRIA" in notas.upper())
            for k in (f"modelos_{hecho['capacidad']}", "modelos_con_avisos" if hecho["avisos"] else None):
                if k:
                    conteo[k] = conteo.get(k, 0) + 1
    return conteo
