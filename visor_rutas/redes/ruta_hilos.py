"""Ruta de fusión de un cliente según los diagramas (la red de mufas ya migrada): desde el H1 del cliente se sigue la fusión mufa por mufa hasta el splitter
al que está conectado; si el cliente está en punta con la mufa y no hay splitter en el camino, se sigue hasta el nodo.

Cada paso dice el número del hilo y la mufa hacia la que va, y con qué hilo se pega al otro lado (el de la siguiente mufa o el de la salida del splitter):
  «En MF A … ingresar la acometida del cliente. H1 del cliente fusionarlo con H6 hacia MF B»
  «En MF B … H6 hacia MF A fusionarlo con H2 hacia MF C»
  «En MF C … H2 hacia MF B fusionarlo con H3 del SPL 1/8 de MF C»
Los pasos son los del plan de la ruta de fusión (`ruta_fusion_plan`): se editan y se exportan igual. Solo lee la red; no cambia nada.
"""
from typing import Any

from visor_rutas.redes import proyectos, trazado
from visor_rutas.redes.db import NoEncontrado, SinPermiso


def _elegir(caminos: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int | None]:
    """(the path to follow, index of its first splitter step or None). The one that reaches a splitter (the shortest); else the one that reaches the node; else the longest."""
    def primer_splitter(c: dict[str, Any]) -> int | None:
        return next((i for i, p in enumerate(c["pasos"]) if p["tipo"] == "splitter" and "conexion_salida_id" not in p), None)   # output -> input: the client's side

    con_splitter = [(primer_splitter(c), c) for c in caminos if primer_splitter(c) is not None]
    if con_splitter:
        i, c = min(con_splitter, key=lambda x: (len([p for p in x[1]["pasos"][: x[0]] if p["tipo"] == "tramo"]), x[1]["distancia_m"]))
        return c, i
    nodos = [c for c in caminos if c["fin"]["motivo"] == "nodo"]
    if nodos:
        return min(nodos, key=lambda c: c["distancia_m"]), None
    return (max(caminos, key=lambda c: len(c["pasos"])) if caminos else None), None


def ruta_cliente(con: Any, actor: dict[str, Any], *, mufa_id: int, hilo_id: int | None = None, splitter_id: int | None = None, numero: int | None = None) -> dict[str, Any]:
    """The fusion route of the client that is, in mufa `mufa_id`, on fibre `hilo_id` (a fibre of one of its cables) or on output `numero` of splitter `splitter_id`.
    Returns {"plan": plan of ruta_fusion_plan (steps and texts), "avisos": [...], "fin": "splitter" | "nodo" | "sin_continuidad"}."""
    from visor_rutas import ruta_fusion_plan                # here, not at the top: the network module does not depend on the route calculator

    red = trazado._Red(con)
    mufa = con.execute("SELECT id, proyecto_id FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(mufa_id),)).fetchone()
    if mufa is None:
        raise NoEncontrado("La mufa no existe")
    if not proyectos.puede_ver(con, actor, mufa["proyecto_id"]):
        raise SinPermiso("No tiene acceso a este proyecto")
    if splitter_id is not None:                              # the client is on an output of a splitter of this mufa: it is served from there
        s = con.execute("SELECT id, salidas FROM redes.splitters WHERE id = %s AND mufa_id = %s AND borrado_en IS NULL", (int(splitter_id), mufa["id"])).fetchone()
        if s is None:
            raise NoEncontrado("El splitter no es de esta mufa")
        el = red.elemento(mufa["id"])
        paso = {"id": "p1", "tipo": "mufa", "nombre": el["nombre"], "lat": el["lat"], "lon": el["lon"], "tocar": True, "motivo": None, "hilo_cliente": "H1",
                "hilo_potencia": f"H{int(numero or 0)}", "splitter": f"1/{s['salidas']}", "texto_manual": None, "fuente_hilos": "diagrama", "por_nombre": False}
        return {"plan": ruta_fusion_plan.redactar({"pasos": [paso], "potencia": None, "avisos_rojos": []}), "avisos": [], "fin": "splitter"}
    h = red.hilo(int(hilo_id or 0))
    if h["borrado_en"] is not None:
        raise NoEncontrado("El hilo fue eliminado")
    cable = red.cable(h["cable_id"])
    if mufa["id"] not in (cable["origen_id"], cable["destino_id"]):
        raise NoEncontrado("El hilo no es de un cable de esta mufa")
    return _desde(con, red, trazado._Trazado(red), h, cable, mufa["id"], ruta_fusion_plan)


def _desde(con: Any, red: Any, t: Any, h: dict[str, Any], cable: dict[str, Any], inicio_id: int, ruta_fusion_plan: Any) -> dict[str, Any]:
    inicio = red.elemento(inicio_id)
    visto = frozenset({("h", h["id"])})
    caminos: list[dict[str, Any]] = []
    conexiones = red.conexiones_hilo(inicio_id, h["id"])
    if conexiones:                       # the fibre is fused right there (a tap: the client hangs from a fibre that goes on): the route leaves by those fusions
        for c in conexiones:
            otro_hilo, otro_puerto = trazado._otro_extremo(c, hilo_id=h["id"])
            caminos += list(t.extremo(inicio, c["id"], otro_hilo, otro_puerto, [], 0.0, visto, fusion=otro_hilo is not None))
    else:                                # the client is at the tip of the mufa: along its own fibre, to the other end
        siguiente = cable["destino_id"] if cable["origen_id"] == inicio_id else cable["origen_id"]
        caminos = list(t.por_hilo(h["id"], siguiente, [], 0.0, visto))
    camino, i_split = _elegir(caminos)
    if camino is None:
        raise NoEncontrado("El hilo no continúa: no hay con qué seguir la fusión")
    pasos_red = camino["pasos"] if i_split is None else camino["pasos"][: i_split + 1]

    # the stops: one per mufa where the fibre is fused (client side first)
    paradas: list[dict[str, Any]] = []
    en = inicio
    llega = {"hilo": "H1", "de": None}                       # the fibre that arrives at `en` from the client's side
    for p in pasos_red:
        if p["tipo"] == "tramo":
            salida = f"H{p['hilo']['numero']}"
            paradas.append({"el": en, "hilo_cliente": llega["hilo"], "hilo_potencia": salida, "splitter": None, "estado": p["hilo"]["estado"]})
            llega = {"hilo": salida, "de": en["nombre"]}
            en = red.elemento(p["hasta"]["id"])
        elif p["tipo"] == "splitter":
            sp = con.execute("SELECT salidas FROM redes.splitters WHERE id = %s", (p["splitter_id"],)).fetchone()
            paradas.append({"el": en, "hilo_cliente": llega["hilo"], "hilo_potencia": f"H{p['salida']}", "splitter": f"1/{sp['salidas']}" if sp else None, "estado": "activo"})
            break
    fin = "splitter" if i_split is not None else "nodo" if camino["fin"]["motivo"] == "nodo" else "sin_continuidad"
    avisos = list(camino["avisos"])
    if fin == "nodo":
        paradas.append({"el": en, "hilo_cliente": llega["hilo"], "hilo_potencia": None, "splitter": None, "estado": "activo", "fin": "nodo"})
        avisos.append(f"No hay splitter en el camino de este cliente: la fusión sigue hasta el nodo {en['nombre']}")
    elif fin == "sin_continuidad":
        avisos.append(camino["fin"]["texto"] + ": la ruta de fusión queda incompleta, revisar el diagrama")
    pasos = []
    for k, q in enumerate(paradas):
        e = q["el"]
        pasos.append({"id": f"p{k + 1}", "tipo": "mufa", "nombre": e["nombre"], "lat": e["lat"], "lon": e["lon"], "tocar": True, "motivo": None,
                      "hilo_cliente": q["hilo_cliente"], "hilo_potencia": q["hilo_potencia"] or "H__", "splitter": q["splitter"], "texto_manual": None,
                      "fuente_hilos": "diagrama", "por_nombre": False, "fin": q.get("fin")})
    for q in paradas:
        if q["estado"] != "activo":
            avisos.append(f"El hilo {q['hilo_potencia']} en {q['el']['nombre']} está marcado {trazado.NOMBRE_ESTADO.get(q['estado'], q['estado'])}")
    plan = ruta_fusion_plan.redactar({"pasos": pasos, "potencia": en["nombre"] if fin == "nodo" else None, "avisos_rojos": avisos})
    return {"plan": plan, "avisos": avisos, "fin": fin}
