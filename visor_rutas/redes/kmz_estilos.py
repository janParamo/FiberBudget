"""Ícono, color y tamaño propios para lo que sale del KMZ en el mapa (visor v2, fase 9).

Un estilo se le pone a un elemento (esa mufa, ese poste) o a toda una carpeta (todas las mufas, todos los postes de concreto); el del elemento
gana sobre el de la carpeta. Para puntos es un `icono` (el mismo de Mis lugares: pushpin, letra, número, figura o ninguno, con color, escala y
opacidad) y para líneas un `linea` (color, grosor, opacidad). Es de todos —la red es compartida—, así que solo un administrador o un editor lo
cambia. El archivo KMZ y las tablas del presupuesto no se tocan. La `clave` del elemento es la de kmz_cambios (la arma la página); la de una
carpeta es «<ruta de la carpeta>|*|».
"""
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import lugares_iconos, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

MAX_CLAVE = 600
# the icons of what the viewer itself draws (alcance «capa», key «capa|<id>|»): route poles and mufas, Visio nodes, the searched mufa, connection point, client
CAPAS_VISOR = ("poste", "posteNuevo", "posteMarcado", "mufaRuta", "mufaIntervenida", "nodo", "buscada", "conexion", "cliente")
TIPOS_ICONO = lugares_iconos.TIPOS_ICONO                     # the catalogue of Mis lugares: pushpin, letra, numero, figura, ninguno, imagen, texto
FIGURAS = lugares_iconos.FIGURAS
LETRAS = lugares_iconos.LETRAS
NUMEROS = lugares_iconos.NUMEROS
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_CAMPOS = "id, clave, alcance, carpeta, nombre, estilo, version"


def _exigir_editor(actor: dict[str, Any]) -> None:
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede cambiar los íconos del KMZ")


def _numero(valor: Any, minimo: float, maximo: float, campo: str) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({campo: "Número no válido"}) from None
    if not (minimo <= n <= maximo) or n != n:
        raise DatosInvalidos({campo: f"Debe estar entre {minimo:g} y {maximo:g}"})
    return round(n, 2)


def _color(valor: Any, campo: str) -> str:
    if not isinstance(valor, str) or not _COLOR.match(valor):
        raise DatosInvalidos({campo: "Color no válido (#rrggbb)"})
    return valor.lower()


def limpiar_icono(icono: Any) -> dict[str, Any]:
    """Same rules as `Iconos.limpiar` of the page, but strict: what is wrong is refused, not silently fixed."""
    if not isinstance(icono, dict):
        raise DatosInvalidos({"icono": "Ícono no válido"})
    tipo = icono.get("tipo")
    if tipo not in TIPOS_ICONO:
        raise DatosInvalidos({"icono": "Tipo de ícono no válido"})
    ident = str(icono.get("id") or "")
    salida: dict[str, Any] = {"tipo": tipo, "color": _color(icono.get("color"), "color"),
                              "escala": _numero(icono.get("escala", 1.1), 0.3, 4, "escala"), "opacidad": _numero(icono.get("opacidad", 1), 0, 1, "opacidad")}
    if tipo == "imagen":                                       # the user's own picture (a small data URL: the page shrinks it before sending)
        datos = icono.get("datos")
        if not isinstance(datos, str) or len(datos) > lugares_iconos.MAX_IMAGEN or not lugares_iconos._IMAGEN.match(datos):
            raise DatosInvalidos({"icono": "La imagen no es válida (PNG, JPG, WebP o GIF, pequeña)"})
        return {**salida, "id": "imagen", "datos": datos}
    if tipo == "texto":                                        # up to three characters: an emoji, "OLT", "5G"
        ident = ident.strip()
        if not 1 <= len(ident) <= 3 or any(c in lugares_iconos._TEXTO_PROHIBIDO or ord(c) < 32 for c in ident):
            raise DatosInvalidos({"icono": "El texto del ícono debe tener de 1 a 3 caracteres"})
        return {**salida, "id": ident}
    permitido = {"pushpin": ("pushpin",), "letra": LETRAS, "numero": NUMEROS, "figura": FIGURAS, "ninguno": ("ninguno",)}[tipo]
    if ident not in permitido:
        raise DatosInvalidos({"icono": "Ícono no válido"})
    return {**salida, "id": ident}


def limpiar_linea(linea: Any) -> dict[str, Any]:
    if not isinstance(linea, dict):
        raise DatosInvalidos({"linea": "Estilo de línea no válido"})
    return {"color": _color(linea.get("color"), "color"), "grosor": _numero(linea.get("grosor", 3), 0.5, 12, "grosor"),
            "opacidad": _numero(linea.get("opacidad", 1), 0, 1, "opacidad")}


def _publico(f: Any) -> dict[str, Any]:
    return {k: f[k] for k in ("id", "clave", "alcance", "carpeta", "nombre", "estilo", "version")}


def listar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Every active style (the page applies them to the KMZ layers when it builds them). Anyone can read them."""
    filas = con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_estilos WHERE borrado_en IS NULL ORDER BY id").fetchall()
    return {"estilos": [_publico(f) for f in filas]}


def guardar(con: Any, actor: dict[str, Any], *, clave: str, alcance: str, carpeta: str, nombre: str = "",
            icono: dict[str, Any] | None = None, linea: dict[str, Any] | None = None) -> dict[str, Any]:
    """Creates or replaces the style of `clave` (an element of the KMZ or a whole folder)."""
    _exigir_editor(actor)
    clave = str(clave or "")
    if not clave.strip() or len(clave) > MAX_CLAVE:
        raise DatosInvalidos({"clave": "Elemento del KMZ no válido"})
    if alcance not in ("elemento", "carpeta", "capa"):
        raise DatosInvalidos({"alcance": "Alcance no válido"})
    if alcance == "carpeta" and not clave.endswith("|*|"):
        raise DatosInvalidos({"clave": "La clave de una carpeta termina en |*|"})
    if alcance == "capa":
        if clave not in {f"capa|{c}|" for c in CAPAS_VISOR}:
            raise DatosInvalidos({"clave": "Esa capa del visor no tiene ícono que cambiar"})
        if icono is None or linea is not None:
            raise DatosInvalidos({"estilo": "Las capas del visor solo llevan un ícono"})
    if icono is None and linea is None:
        raise DatosInvalidos({"estilo": "No hay nada que guardar"})
    estilo: dict[str, Any] = {}
    if icono is not None:
        estilo["icono"] = limpiar_icono(icono)
    if linea is not None:
        estilo["linea"] = limpiar_linea(linea)
    valores = {"alcance": alcance, "carpeta": " ".join(str(carpeta or "").split())[:300], "nombre": " ".join(str(nombre or "").split())[:160],
               "estilo": Jsonb(estilo)}
    with con.transaction():
        actual = con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_estilos WHERE clave = %s AND borrado_en IS NULL FOR UPDATE", (clave,)).fetchone()
        if actual is None:
            fila = repositorio.insertar(con, "kmz_estilos", {"clave": clave, **valores}, actor["id"])
            repositorio.registrar(con, actor["id"], "kmz_estilo", fila["id"], "crear", {"clave": [None, clave]})
        else:
            _, fila = repositorio.actualizar(con, "kmz_estilos", actual["id"], actual["version"], valores, actor["id"])
            repositorio.registrar(con, actor["id"], "kmz_estilo", fila["id"], "editar", {"estilo": [actual["estilo"], estilo]})
    return {"estilo": _publico(fila)}


def quitar(con: Any, actor: dict[str, Any], *, clave: str) -> dict[str, Any]:
    """Removes the style of `clave`: the element (or the folder) looks as the KMZ says again."""
    _exigir_editor(actor)
    with con.transaction():
        fila = con.execute(f"SELECT {_CAMPOS} FROM redes.kmz_estilos WHERE clave = %s AND borrado_en IS NULL FOR UPDATE", (str(clave or ""),)).fetchone()
        if fila is None:
            raise NoEncontrado("Ese elemento ya no tiene un estilo propio")
        con.execute("UPDATE redes.kmz_estilos SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], fila["id"]))
        repositorio.registrar(con, actor["id"], "kmz_estilo", fila["id"], "eliminar", {"clave": [fila["clave"], None]})
    return {"clave": fila["clave"]}
