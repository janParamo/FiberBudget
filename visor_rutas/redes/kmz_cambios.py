"""Editar lo que ya existe en el KMZ (visor v2, fase 4, segunda parte): renombrar, mover o quitar del mapa un elemento del KMZ.

El archivo KMZ no se modifica: cada cambio se guarda en `redes.kmz_cambios` y el visor, al construir una capa, aplica los cambios
(oculta lo quitado, pone el nombre y la posición nuevos). Un elemento se identifica por una `clave` que arma la página (carpeta +
nombre original + coordenada redondeada). Hay un solo cambio activo por clave y es de todos: la red es compartida, así que solo
un administrador o un editor puede cambiarla. Volver a lo original (mismo nombre y posición) borra el cambio; "deshacer" también.
Los cambios todavía no llegan a las tablas del presupuesto (red_puntos / red_lineas): `publicado` queda en false.
"""
import math
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import repositorio, usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

MAX_CLAVE = 600
_CAMPOS = "id, clave, carpeta, nombre, tipo, accion, antes, despues, publicado, version"


def _exigir_editor(actor: dict[str, Any]) -> None:
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede cambiar la red del KMZ")


def _texto(valor: Any, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _coordenada(valor: Any) -> tuple[float, float] | None:
    try:
        lat, lon = float(valor["lat"]), float(valor["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 7), round(lon, 7)


def _publico(f: Any) -> dict[str, Any]:
    return {k: f[k] for k in ("id", "clave", "carpeta", "nombre", "tipo", "accion", "antes", "despues", "publicado", "version")}


def listar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Every active change (the page applies them to the KMZ layers when it builds them)."""
    filas = con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_cambios WHERE borrado_en IS NULL ORDER BY id").fetchall()
    return {"cambios": [_publico(f) for f in filas]}


def _activo(con: Any, clave: str) -> Any:
    return con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_cambios WHERE clave = %s AND borrado_en IS NULL FOR UPDATE", (clave,)).fetchone()


def _antes(valor: Any, tipo: str) -> dict[str, Any]:
    nombre = _texto((valor or {}).get("nombre") if isinstance(valor, dict) else None, 160)
    if not nombre:
        raise DatosInvalidos({"antes": "Falta el nombre original del elemento"})
    salida: dict[str, Any] = {"nombre": nombre}
    if tipo == "punto":
        c = _coordenada(valor)
        if c is None:
            raise DatosInvalidos({"antes": "Falta la posición original del punto"})
        salida.update(lat=c[0], lon=c[1])
    return salida


def _identificar(clave: Any, carpeta: Any, tipo: Any) -> tuple[str, str, str]:
    clave = str(clave or "")
    if not clave.strip() or len(clave) > MAX_CLAVE:
        raise DatosInvalidos({"clave": "Elemento del KMZ no válido"})
    if tipo not in ("punto", "linea"):
        raise DatosInvalidos({"tipo": "Tipo de elemento no válido"})
    return clave, _texto(carpeta, 300), tipo


def _guardar(con: Any, actor: dict[str, Any], clave: str, carpeta: str, tipo: str, antes: dict[str, Any], accion: str,
             despues: dict[str, Any] | None) -> dict[str, Any]:
    """Creates / updates the change of `clave`; one that leaves the element as it was deletes it."""
    with con.transaction():
        actual = _activo(con, clave)
        if actual is not None:
            antes = actual["antes"]                              # the original never changes
        if accion == "editar" and (despues or {}).get("nombre", antes["nombre"]) == antes["nombre"] \
                and (tipo == "linea" or (despues.get("lat"), despues.get("lon")) == (antes.get("lat"), antes.get("lon"))):
            if actual is not None:
                _quitar(con, actor, actual)
            return {"cambio": None}
        valores = {"carpeta": carpeta, "nombre": antes["nombre"], "tipo": tipo, "accion": accion, "antes": Jsonb(antes),
                   "despues": Jsonb(despues) if despues else None, "publicado": False}
        if actual is None:
            fila = repositorio.insertar(con, "kmz_cambios", {"clave": clave, **valores}, actor["id"])
            repositorio.registrar(con, actor["id"], "kmz_cambio", fila["id"], "crear", {"accion": [None, accion], "nombre": [None, antes["nombre"]]})
        else:
            try:
                _, fila = repositorio.actualizar(con, "kmz_cambios", actual["id"], actual["version"], valores, actor["id"])
            except ConflictoVersion:
                raise ConflictoVersion("El elemento cambió mientras lo editaba. Recargue la página.") from None
            repositorio.registrar(con, actor["id"], "kmz_cambio", fila["id"], "editar", {"accion": [actual["accion"], accion]})
    return {"cambio": _publico(fila)}


def _quitar(con: Any, actor: dict[str, Any], fila: Any) -> None:
    with con.transaction():
        con.execute("UPDATE redes.kmz_cambios SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], fila["id"]))
        repositorio.registrar(con, actor["id"], "kmz_cambio", fila["id"], "eliminar", {"nombre": [fila["nombre"], None]})


def editar(con: Any, actor: dict[str, Any], *, clave: str, carpeta: str, tipo: str, antes: dict[str, Any],
           nombre: str | None = None, lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """Renames and / or moves (points) an element of the KMZ."""
    _exigir_editor(actor)
    clave, carpeta, tipo = _identificar(clave, carpeta, tipo)
    origen = _antes(antes, tipo)
    despues: dict[str, Any] = {"nombre": _texto(nombre, 160) or origen["nombre"]}
    if tipo == "punto":
        if lat is not None or lon is not None:
            c = _coordenada({"lat": lat, "lon": lon})
            if c is None:
                raise DatosInvalidos({"posicion": "Posición no válida"})
            despues.update(lat=c[0], lon=c[1])
        else:
            despues.update(lat=origen["lat"], lon=origen["lon"])
    elif lat is not None or lon is not None:
        raise DatosInvalidos({"posicion": "Una línea del KMZ solo se puede renombrar o quitar"})
    return _guardar(con, actor, clave, carpeta, tipo, origen, "editar", despues)


def borrar(con: Any, actor: dict[str, Any], *, clave: str, carpeta: str, tipo: str, antes: dict[str, Any]) -> dict[str, Any]:
    """Takes an element of the KMZ off the map."""
    _exigir_editor(actor)
    clave, carpeta, tipo = _identificar(clave, carpeta, tipo)
    return _guardar(con, actor, clave, carpeta, tipo, _antes(antes, tipo), "borrar", None)


def deshacer(con: Any, actor: dict[str, Any], *, id: int) -> dict[str, Any]:
    """Removes a change: the element is as the KMZ has it again."""
    _exigir_editor(actor)
    fila = con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_cambios WHERE id = %s AND borrado_en IS NULL FOR UPDATE", (int(id),)).fetchone()
    if fila is None:
        raise NoEncontrado("El cambio ya no existe")
    _quitar(con, actor, fila)
    return {"id": fila["id"], "clave": fila["clave"]}
