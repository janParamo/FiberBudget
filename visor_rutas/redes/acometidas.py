"""Acometidas creadas desde una mufa: un cable nuevo (de 2, 4, 6, 8, 12, 24, 48, 72 o 96 hilos) que sale de la mufa.

Es un cable de la red (clase «acometida»): sus hilos se conectan con los de la mufa como cualquier otro y a esos hilos se les asignan clientes. En el editor de la mufa se dibuja como
una tarjeta pequeña con el signo de acometida y sus hilos, como un cliente con varios hilos. El otro extremo es, al crearla, un cliente de relleno (el punto donde llegará la
acometida, a unos 5 m de la mufa); al «conectarla a una mufa» ese extremo pasa a la mufa elegida y el de relleno se quita. Todo sobre `red.guardar`, con sus mismas reglas.
"""
from typing import Any

from visor_rutas.redes import mufa, proyectos, red, repositorio
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

HILOS_ACOMETIDA = (2, 4, 6, 8, 12, 24, 48, 72, 96)
POR_BUFFER = {2: 2, 4: 4, 6: 6, 8: 8, 12: 12, 24: 12, 48: 12, 72: 12, 96: 12}
DESPLAZAMIENTO_GRADOS = 0.00005                          # ~5 m: where the filler end is put


def _mufa(con: Any, actor: dict[str, Any], mufa_id: int) -> dict[str, Any]:
    m = con.execute("SELECT id, proyecto_id, tipo, nombre, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos WHERE id = %s AND borrado_en IS NULL",
                    (int(mufa_id),)).fetchone()
    if m is None or m["tipo"] not in ("mufa", "nodo", "odf"):
        raise NoEncontrado("La mufa no existe (o fue eliminada)")
    if not proyectos.puede_editar(con, actor, m["proyecto_id"]):
        raise SinPermiso("No tiene permiso para editar este proyecto")
    return dict(m)


def _acometida(con: Any, cable_id: int, m: dict[str, Any]) -> dict[str, Any]:
    c = con.execute("SELECT * FROM redes.cables WHERE id = %s AND borrado_en IS NULL", (int(cable_id),)).fetchone()
    if c is None or c["clase"] != "acometida" or m["id"] not in (c["origen_id"], c["destino_id"]):
        raise NoEncontrado("La acometida no existe en esta mufa")
    return dict(c)


def crear(con: Any, actor: dict[str, Any], *, mufa_id: int, nombre: Any = None, hilos: Any = 2) -> dict[str, Any]:
    """A new acometida from the mufa: a cable of `hilos` fibres. Returns the mufa as `mufa.leer` + {"acometida": {"cable_id"}}."""
    m = _mufa(con, actor, mufa_id)
    try:
        n_hilos = int(hilos)
    except (TypeError, ValueError):
        raise DatosInvalidos({"hilos": "los hilos son un número"}) from None
    if n_hilos not in HILOS_ACOMETIDA:
        raise DatosInvalidos({"hilos": "la acometida puede ser de " + ", ".join(map(str, HILOS_ACOMETIDA)) + " hilos"})
    if m["lat"] is None or m["lon"] is None:
        raise DatosInvalidos({"mufa": "La mufa no tiene coordenada: póngala en el mapa antes de crear una acometida"})
    previas = con.execute("SELECT count(*) AS n FROM redes.cables WHERE borrado_en IS NULL AND clase = 'acometida' AND (origen_id = %(m)s OR destino_id = %(m)s)", {"m": m["id"]}).fetchone()["n"]
    limpio = " ".join(str(nombre or "").split())[:160] or f"Acometida {previas + 1}"
    lat, lon = float(m["lat"]), float(m["lon"])
    fin_lat = lat + DESPLAZAMIENTO_GRADOS * (previas + 1)
    r = red.guardar(con, actor, proyecto_id=m["proyecto_id"], cambios={
        "elementos": [{"id": "fin", "tipo": "cliente", "nombre": limpio, "lat": fin_lat, "lon": lon}],
        "cables": [{"id": "cab", "nombre": limpio, "clase": "acometida", "tipo": "FLAT" if n_hilos <= 12 else "ADSS", "hilos": n_hilos, "hilos_por_buffer": POR_BUFFER[n_hilos],
                    "origen_id": m["id"], "destino_id": "fin",
                    "vertices": [{"lat": lat, "lon": lon, "elemento_id": m["id"]}, {"lat": fin_lat, "lon": lon, "elemento_id": "fin"}]}]})
    return {**mufa.leer(con, actor, mufa_id=m["id"]), "acometida": {"cable_id": r["ids"]["cab"], "nombre": limpio, "hilos": n_hilos}}


def mufas_para_conectar(con: Any, actor: dict[str, Any], *, mufa_id: int) -> dict[str, Any]:
    """The mufas of the same project (nearest first) an acometida of this mufa can be connected to."""
    m = _mufa(con, actor, mufa_id)
    filas = con.execute(
        "SELECT e.id, e.nombre, CASE WHEN e.ubicacion IS NULL OR %(lat)s IS NULL THEN NULL ELSE ST_Distance(e.ubicacion::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) END AS distancia_m "
        "FROM redes.elementos e WHERE e.proyecto_id = %(p)s AND e.borrado_en IS NULL AND e.tipo = 'mufa' AND e.id <> %(m)s "
        "ORDER BY distancia_m NULLS LAST, lower(e.nombre) LIMIT 80", {"lat": m["lat"], "lon": m["lon"], "p": m["proyecto_id"], "m": m["id"]}).fetchall()
    return {"mufas": [{"id": f["id"], "nombre": f["nombre"], "distancia_m": None if f["distancia_m"] is None else round(float(f["distancia_m"]), 1)} for f in filas]}


def actualizar(con: Any, actor: dict[str, Any], *, mufa_id: int, cable_id: int, nombre: Any = None, destino_mufa_id: Any = None) -> dict[str, Any]:
    """Renames the acometida and/or connects its other end to a mufa of the project (the filler end is removed). Returns the mufa as `mufa.leer`."""
    m = _mufa(con, actor, mufa_id)
    c = _acometida(con, cable_id, m)
    otro_id = c["destino_id"] if c["origen_id"] == m["id"] else c["origen_id"]
    cambios_cable: dict[str, Any] = {}
    limpio = " ".join(str(nombre or "").split())[:160]
    if destino_mufa_id not in (None, "", 0):
        destino = con.execute("SELECT id, tipo, proyecto_id, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (int(destino_mufa_id),)).fetchone()
        if destino is None or destino["tipo"] != "mufa" or destino["proyecto_id"] != m["proyecto_id"] or destino["id"] == m["id"]:
            raise DatosInvalidos({"mufa": "Elija otra mufa de este mismo proyecto"})
        if destino["lat"] is None:
            raise DatosInvalidos({"mufa": "Esa mufa no tiene coordenada"})
        cambios_cable = {"destino": destino}
    with con.transaction():
        elementos_cambios: list[dict[str, Any]] = []
        cable = {"id": c["id"], "version": c["version"], "nombre": limpio or c["nombre"], "clase": "acometida", "tipo": c["tipo"], "hilos": c["hilos"], "hilos_por_buffer": c["hilos_por_buffer"],
                 "color": c["color"], "cruces": c["cruces"], "descripcion": c["descripcion"]}
        if cambios_cable:
            d = cambios_cable["destino"]
            cable.update(origen_id=m["id"], destino_id=d["id"], vertices=[{"lat": float(m["lat"]), "lon": float(m["lon"]), "elemento_id": m["id"]},
                                                                         {"lat": float(d["lat"]), "lon": float(d["lon"]), "elemento_id": d["id"]}])
            otro = con.execute("SELECT id, tipo, version FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (otro_id,)).fetchone()
            if otro is not None and otro["tipo"] == "cliente" and con.execute(
                    "SELECT 1 FROM redes.cables WHERE borrado_en IS NULL AND id <> %s AND (origen_id = %s OR destino_id = %s)", (c["id"], otro_id, otro_id)).fetchone() is None:
                elementos_cambios.append({"id": otro["id"], "eliminar": True, "version": otro["version"]})      # the filler end is no longer needed
        else:
            fila = con.execute("SELECT ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos WHERE id = %s", (otro_id,)).fetchone()
            cable.update(origen_id=m["id"], destino_id=otro_id, vertices=[{"lat": float(m["lat"]), "lon": float(m["lon"]), "elemento_id": m["id"]},
                                                                          {"lat": float(fila["lat"]), "lon": float(fila["lon"]), "elemento_id": otro_id}])
        red.guardar(con, actor, proyecto_id=m["proyecto_id"], cambios={"elementos": elementos_cambios, "cables": [cable]})
        if limpio and not cambios_cable:                    # the filler end takes the name of the acometida too
            otro = con.execute("SELECT id, tipo, version FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (otro_id,)).fetchone()
            if otro is not None and otro["tipo"] == "cliente":
                repositorio.actualizar(con, "elementos", otro["id"], otro["version"], {"nombre": limpio}, actor["id"])
    return mufa.leer(con, actor, mufa_id=m["id"])


def eliminar(con: Any, actor: dict[str, Any], *, mufa_id: int, cable_id: int) -> dict[str, Any]:
    """Deletes the acometida: its cable, its connections, the clients put on its fibres and the filler end (when nothing else uses it)."""
    m = _mufa(con, actor, mufa_id)
    c = _acometida(con, cable_id, m)
    otro_id = c["destino_id"] if c["origen_id"] == m["id"] else c["origen_id"]
    with con.transaction():
        con.execute("UPDATE redes.hilo_servicios SET borrado_en = now(), version = version + 1 WHERE borrado_en IS NULL AND hilo_id IN (SELECT id FROM redes.hilos WHERE cable_id = %s)", (c["id"],))
        elementos_cambios = []
        otro = con.execute("SELECT id, tipo, version FROM redes.elementos WHERE id = %s AND borrado_en IS NULL", (otro_id,)).fetchone()
        if otro is not None and otro["tipo"] == "cliente" and con.execute(
                "SELECT 1 FROM redes.cables WHERE borrado_en IS NULL AND id <> %s AND (origen_id = %s OR destino_id = %s)", (c["id"], otro_id, otro_id)).fetchone() is None:
            elementos_cambios.append({"id": otro["id"], "eliminar": True, "version": otro["version"]})
        red.guardar(con, actor, proyecto_id=m["proyecto_id"], cambios={"cables": [{"id": c["id"], "eliminar": True, "version": c["version"]}], "elementos": elementos_cambios})
    return mufa.leer(con, actor, mufa_id=m["id"])
