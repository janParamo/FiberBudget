"""Elementos de red de un proyecto (tabla redes.elementos): postes, mufas, casas de cliente, nodos.

Fase 2: los **clientes del proyecto** (varios por proyecto) se editan desde la ventana "Datos del
proyecto": nombre, código C#####, ID de servicio y coordenada. Son las mismas casas de cliente
que el editor de mapa (fase 3) dibuja y conecta, así que no se duplican.
Quitar un cliente es borrado lógico (borrado_en).
"""
import math
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import repositorio
from visor_rutas.redes.db import DatosInvalidos

MAX_CLIENTES = 2000
_CODIGO_CLIENTE = re.compile(r"^C\d{3,8}$", re.I)

_SELECT = ("SELECT id, tipo, subtipo, nombre, codigo, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, propiedades, "
           "ref_externa, version FROM redes.elementos")


def punto(lat: Any, lon: Any) -> str | None:
    """EWKT of a valid (lat, lon), or None."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(la) and math.isfinite(lo) and -90 <= la <= 90 and -180 <= lo <= 180):
        return None
    return f"SRID=4326;POINT({lo:.8f} {la:.8f})"


def publico(fila: dict[str, Any]) -> dict[str, Any]:
    datos = {k: fila[k] for k in ("id", "tipo", "subtipo", "nombre", "codigo", "lat", "lon", "ref_externa", "version")}
    datos.update(fila.get("propiedades") or {})
    return datos


def clientes_de(con: Any, proyecto_id: int) -> list[dict[str, Any]]:
    filas = con.execute(_SELECT + " WHERE proyecto_id = %s AND tipo = 'cliente' AND borrado_en IS NULL ORDER BY id",
                        (proyecto_id,)).fetchall()
    return [publico(f) for f in filas]


def validar_clientes(lista: Any) -> list[dict[str, Any]]:
    """[{id?, nombre, codigo?, id_servicio?, lat, lon}] -> clean values. DatosInvalidos with the
    row numbers (as the user sees them: 1, 2, ...) of the wrong ones."""
    if not isinstance(lista, list):
        raise DatosInvalidos({"clientes": "Lista de clientes no válida"})
    if len(lista) > MAX_CLIENTES:
        raise DatosInvalidos({"clientes": f"Máximo {MAX_CLIENTES} clientes por proyecto"})
    errores: list[str] = []
    salida: list[dict[str, Any]] = []
    codigos: set[str] = set()
    for n, c in enumerate(lista, start=1):
        c = c if isinstance(c, dict) else {}
        nombre = " ".join(str(c.get("nombre") or "").split())[:160]
        codigo = " ".join(str(c.get("codigo") or "").split()).upper() or None
        id_servicio = " ".join(str(c.get("id_servicio") or "").split())[:40] or None
        ubicacion = punto(c.get("lat"), c.get("lon"))
        problemas = []
        if not nombre:
            problemas.append("falta el nombre")
        if codigo and not _CODIGO_CLIENTE.match(codigo):
            problemas.append("el código debe ser C seguido de números (C12345)")
        elif codigo and codigo in codigos:
            problemas.append(f"el código {codigo} está repetido")
        if ubicacion is None:
            problemas.append("coordenada no válida")
        if problemas:
            errores.append(f"cliente {n}: " + ", ".join(problemas))
            continue
        if codigo:
            codigos.add(codigo)
        salida.append({"id": int(c["id"]) if c.get("id") else None, "nombre": nombre, "codigo": codigo,
                       "ubicacion": ubicacion, "propiedades": {"id_servicio": id_servicio} if id_servicio else {}})
    if errores:
        raise DatosInvalidos({"clientes": "; ".join(errores[:8]) + (" …" if len(errores) > 8 else "")})
    return salida


def sincronizar_clientes(con: Any, proyecto_id: int, clientes: list[dict[str, Any]], usuario_id: int) -> None:
    """Leaves exactly `clientes` as the project's active clients: new ones are inserted, the ones
    with id are updated if they changed, and the missing ones get borrado_en (recoverable).
    Runs inside the caller's transaction (the project's version guards the whole form)."""
    actuales = {f["id"]: f for f in con.execute(
        "SELECT id, nombre, codigo, ubicacion, propiedades, version FROM redes.elementos "
        "WHERE proyecto_id = %s AND tipo = 'cliente' AND borrado_en IS NULL", (proyecto_id,)).fetchall()}
    conservar = set()
    # Free the codes of the clients that will be removed or recoded first (unique index).
    for c in clientes:
        if c["id"] is not None and c["id"] not in actuales:
            raise DatosInvalidos({"clientes": "Un cliente ya no existe: cierre y vuelva a abrir el proyecto"})
        if c["id"] is not None:
            conservar.add(c["id"])
    quitar = [i for i in actuales if i not in conservar]
    if quitar:
        con.execute("UPDATE redes.elementos SET borrado_en = now(), actualizado_en = now(), actualizado_por = %s, "
                    "version = version + 1 WHERE id = ANY(%s)", (usuario_id, quitar))
    for c in clientes:
        if c["id"] is None:
            continue
        fila = actuales[c["id"]]
        mismo_punto = con.execute("SELECT ST_Equals(%s::geometry, %s::geometry) AS igual",
                                  (fila["ubicacion"], c["ubicacion"])).fetchone()["igual"]
        if (fila["nombre"], fila["codigo"], fila["propiedades"] or {}) != (c["nombre"], c["codigo"], c["propiedades"]) \
                or not mismo_punto:
            repositorio.actualizar(con, "elementos", c["id"], fila["version"],
                                   {"nombre": c["nombre"], "codigo": c["codigo"], "ubicacion": c["ubicacion"],
                                    "propiedades": Jsonb(c["propiedades"])}, usuario_id)
    for c in clientes:
        if c["id"] is None:
            repositorio.insertar(con, "elementos", {"proyecto_id": proyecto_id, "tipo": "cliente", "nombre": c["nombre"],
                                                    "codigo": c["codigo"], "ubicacion": c["ubicacion"],
                                                    "propiedades": Jsonb(c["propiedades"])}, usuario_id)


def resumen_clientes(con: Any, proyecto_id: int) -> str | None:
    """Audit text: "3: Casa A (C12345), Casa B, …"."""
    nombres = [c["nombre"] + (f" ({c['codigo']})" if c["codigo"] else "") for c in clientes_de(con, proyecto_id)]
    if not nombres:
        return None
    return f"{len(nombres)}: " + ", ".join(nombres[:20]) + (" …" if len(nombres) > 20 else "")


