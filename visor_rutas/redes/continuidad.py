"""Mufa en continuidad (mufas de corte): los hilos que se escriben («1-12», «1-12, 15, 20-24», «todos») pasan de un cable al otro con el mismo número.

En una mufa de corte los hilos van en continuidad: el hilo n del cable que llega es el hilo n del cable que sale. Conectarlos uno por uno en un cable de 24 hilos o más es
perder el tiempo, y en algunas mufas de corte no todos los hilos van así. Aquí se escribe cuáles van en continuidad: se crean esas fusiones hilo con hilo (mismo número)
entre los dos cables y el resto no se toca. Los hilos que ya tenían una conexión en esa mufa se respetan (no se agrega una segunda punta: sería una sangría) y se avisan.
Lo elegido queda en la mufa (`propiedades.continuidad`): al aplicar otra vez se reemplazan las fusiones que hizo la vez anterior (las demás no se tocan).
"""
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import mufa, proyectos, repositorio
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

MAX_HILOS = 288
_TODOS = {"todos", "todo", "*", "all"}


def leer_hilos(texto: Any, maximo: int) -> list[int]:
    """«1-12, 15, 20-24» -> [1..12, 15, 20..24] (sorted, no repeats); «todos» -> 1..maximo."""
    t = str(texto or "").strip().lower()
    if not t:
        return []
    if t in _TODOS:
        return list(range(1, maximo + 1))
    numeros: set[int] = set()
    for trozo in re.split(r"[,;\s]+", t):
        if not trozo:
            continue
        m = re.fullmatch(r"(\d{1,3})(?:\s*[-–a]\s*(\d{1,3}))?", trozo)
        if not m:
            raise DatosInvalidos({"Continuidad": f"«{trozo}» no se entiende: escriba los hilos como 1-12, 15, 20-24 (o «todos»)"})
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            raise DatosInvalidos({"Continuidad": f"el rango «{trozo}» no es válido: va de menor a mayor y desde 1"})
        numeros.update(range(a, b + 1))
    return sorted(numeros)


def texto_hilos(numeros: list[int]) -> str:
    """[1,2,3,4,15] -> «1-4, 15»."""
    partes, i = [], 0
    while i < len(numeros):
        j = i
        while j + 1 < len(numeros) and numeros[j + 1] == numeros[j] + 1:
            j += 1
        partes.append(str(numeros[i]) if i == j else f"{numeros[i]}-{numeros[j]}")
        i = j + 1
    return ", ".join(partes)


def aplicar(con: Any, actor: dict[str, Any], *, mufa_id: int, cable_a: int | None = None, cable_b: int | None = None, hilos: Any = None,
            quitar: bool = False) -> dict[str, Any]:
    """Puts in continuity the fibres `hilos` of the two cables of the mufa (same number on both). `quitar`: takes off what a previous application made.
    Returns mufa.leer() + {"continuidad": {"hilos": [...], "saltados": [...], "texto": ...}}."""
    m = con.execute("SELECT id, proyecto_id, propiedades FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(mufa_id),)).fetchone()
    if m is None:
        raise NoEncontrado("La mufa no existe")
    if not proyectos.puede_editar(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    cables = {f["id"]: dict(f) for f in con.execute(
        "SELECT id, nombre, hilos FROM redes.cables WHERE borrado_en IS NULL AND (origen_id = %(m)s OR destino_id = %(m)s) ORDER BY id", {"m": m["id"]}).fetchall()}
    previa = (m["propiedades"] or {}).get("continuidad") or {}
    antes = [i for i in (previa.get("conexiones") or []) if isinstance(i, int)]
    quitadas = []
    if antes:                                                    # what the last application made, with the versions that are saved now
        quitadas = [{"id": f["id"], "version": f["version"], "eliminar": True} for f in con.execute(
            "SELECT id, version FROM redes.conexiones WHERE id = ANY(%s) AND mufa_id = %s AND borrado_en IS NULL", (antes, m["id"])).fetchall()]
    if quitar:
        if quitadas:
            mufa.guardar(con, actor, mufa_id=m["id"], cambios={"conexiones": quitadas})
        _guardar_propiedad(con, actor, m, None)
        return {**mufa.leer(con, actor, mufa_id=m["id"]), "continuidad": {"hilos": [], "saltados": [], "texto": ""}}
    a, b = int(cable_a or 0), int(cable_b or 0)
    if a not in cables or b not in cables or a == b:
        raise DatosInvalidos({"Continuidad": "elija los dos cables de esta mufa (distintos) entre los que van los hilos"})
    maximo = min(int(cables[a]["hilos"] or 0), int(cables[b]["hilos"] or 0))
    if maximo < 1:
        raise DatosInvalidos({"Continuidad": "alguno de los dos cables no tiene hilos conocidos: configure su cantidad de hilos primero"})
    pedidos = leer_hilos(hilos, maximo)
    if not pedidos:
        raise DatosInvalidos({"Continuidad": "escriba los hilos que van en continuidad (por ejemplo 1-12) o «todos»"})
    fuera = [n for n in pedidos if n > maximo]
    if fuera:
        raise DatosInvalidos({"Continuidad": f"los cables tienen {maximo} hilos en común: no existe el hilo {fuera[0]}"})
    hilo_de = {(f["cable_id"], f["numero"]): f["id"] for f in con.execute(
        "SELECT id, cable_id, numero FROM redes.hilos WHERE cable_id = ANY(%s) AND borrado_en IS NULL", ([a, b],)).fetchall()}
    ocupados = {x for f in con.execute(
        "SELECT a_hilo_id, b_hilo_id FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL AND NOT (id = ANY(%s))", (m["id"], [q["id"] for q in quitadas])).fetchall()
        for x in (f["a_hilo_id"], f["b_hilo_id"]) if x}
    nuevas, hechos, saltados = [], [], []
    for n in pedidos:
        ha, hb = hilo_de.get((a, n)), hilo_de.get((b, n))
        if ha is None or hb is None or ha in ocupados or hb in ocupados:
            saltados.append(n)                                    # missing fibre, or already connected here: left as it is
            continue
        nuevas.append({"id": f"n{n}", "a": {"hilo": ha}, "b": {"hilo": hb}})
        hechos.append(n)
    r = mufa.guardar(con, actor, mufa_id=m["id"], cambios={"conexiones": quitadas + nuevas})
    ids = [r["ids"][f"n{n}"] for n in hechos]
    _guardar_propiedad(con, actor, m, {"cables": [a, b], "hilos": texto_hilos(hechos), "pedidos": texto_hilos(pedidos), "conexiones": ids})
    return {**mufa.leer(con, actor, mufa_id=m["id"]), "continuidad": {"hilos": hechos, "saltados": saltados, "texto": texto_hilos(hechos)}}


def _guardar_propiedad(con: Any, actor: dict[str, Any], m: dict[str, Any], valor: dict[str, Any] | None) -> None:
    props = dict(m["propiedades"] or {})
    if valor is None:
        props.pop("continuidad", None)
    else:
        props["continuidad"] = valor
    con.execute("UPDATE redes.elementos SET propiedades = %s, version = version + 1, actualizado_en = now(), actualizado_por = %s WHERE id = %s",
                (Jsonb(props), actor["id"], m["id"]))
    repositorio.registrar(con, actor["id"], "elemento", m["id"], "editar",
                          {"continuidad": [(m["propiedades"] or {}).get("continuidad", {}).get("hilos"), None if valor is None else valor["hilos"]]}, proyecto_id=m["proyecto_id"])
