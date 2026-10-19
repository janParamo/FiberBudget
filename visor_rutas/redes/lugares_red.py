"""Red dibujada en "Mis lugares" (visor v2, fase 4): mufas, postes, clientes, nodos, ODF y cables dentro de una carpeta, sin proyecto.

Son lugares (redes.lugares_elementos) con tipo `mufa | poste | cliente | nodo | odf | cable` y sus datos en `propiedades`; no tocan la
red base ni los proyectos. Aquí se ordenan esos datos (las mismas reglas del editor de proyectos, red.py), el ícono y el color que
salen del subtipo, el metraje de los cables (metraje.py), los cables que siguen a un elemento que se mueve y "Guardar como proyecto":
copiar la carpeta a un proyecto nuevo con la misma función que usa el editor (red.guardar), sin preguntas.

Un cable une dos elementos de la red (`origen_id` y `destino_id` son ids de lugares del mismo dueño); sus extremos toman la posición
de esos elementos. Un cable sin extremos (por ejemplo, venido de un KMZ) se acepta, pero no se puede pasar a proyecto.
"""
import re
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import metraje, proyectos, red, repositorio
from visor_rutas.redes.db import DatosInvalidos

PUNTUALES_RED = ("mufa", "poste", "cliente", "nodo", "odf")
TIPOS_RED = PUNTUALES_RED + ("cable",)
_CODIGO_CLIENTE = re.compile(r"^C\d{3,8}$", re.I)
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
GROSOR_POR_CLASE = {"troncal": 5, "distribucion": 3, "acometida": 2}
COLOR_CABLE = "#1f6feb"
_ICONOS = {
    ("mufa", "empalme"): ("circulo", "#ff8c00", 1.0), ("mufa", "distribucion"): ("cuadrado", "#e6c200", 1.0),
    ("mufa", "terminal"): ("anillo", "#d6249f", 1.0), ("mufa", "reserva"): ("anillo", "#ff8c00", 1.0),
    ("poste", "concreto"): ("circulo", "#9aa3ad", 0.55), ("poste", "ideay"): ("circulo", "#2f6fdb", 0.55),
    ("poste", "madera"): ("circulo", "#8b5a2b", 0.55), ("poste", "metal"): ("circulo", "#c0c7cf", 0.55),
    ("poste", "cliente"): ("circulo", "#f08c00", 0.55),
    ("cliente", None): ("rombo", "#0a9d57", 0.9), ("nodo", None): ("triangulo", "#f5b400", 1.0), ("odf", None): ("cuadrado", "#4a5568", 0.9),
}


def _texto(valor: Any, maximo: int) -> str | None:
    t = " ".join(str(valor or "").split())
    return t[:maximo] or None


def _entero(valor: Any, minimo: int, maximo: int, campo: str) -> int | None:
    if valor in (None, ""):
        return None
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise DatosInvalidos({"propiedades": f"{campo} debe ser un número"}) from None
    if not minimo <= n <= maximo:
        raise DatosInvalidos({"propiedades": f"{campo} fuera de rango ({minimo}–{maximo})"})
    return n


# --------------------------------------------------------------------------- datos y estilo

def limpiar_puntual(tipo: str, valor: Any) -> dict[str, Any]:
    """propiedades of a mufa / poste / cliente / nodo / odf: subtipo and the fields of that type (the editor's rules)."""
    origen = valor if isinstance(valor, dict) else {}
    subtipo = origen.get("subtipo") or None
    if subtipo not in red.SUBTIPOS[tipo]:
        subtipo = red.SUBTIPOS[tipo][0]
    salida: dict[str, Any] = {"subtipo": subtipo} if subtipo else {}
    if tipo == "mufa":
        for clave, minimo, maximo in (("capacidad", 1, 1000), ("bandejas", 0, 100)):
            n = _entero(origen.get(clave), minimo, maximo, clave)
            if n is not None:
                salida[clave] = n
    if tipo == "cliente":
        codigo = _texto(origen.get("codigo"), 40)
        if codigo:
            codigo = codigo.upper()
            if not _CODIGO_CLIENTE.match(codigo):
                raise DatosInvalidos({"propiedades": "el código de cliente debe ser C seguido de números (C12345)"})
            salida["codigo"] = codigo
        if _texto(origen.get("id_servicio"), 40):
            salida["id_servicio"] = _texto(origen.get("id_servicio"), 40)
    return salida


def limpiar_cable(con: Any, valor: Any, dueno_id: int, coords: list[list[float]]) -> tuple[dict[str, Any], list[list[float]]]:
    """(propiedades, coordenadas) of a cable: class, type, fibres, color, crossings, its two end elements and the metraje. The end
    vertices take the position of their elements; the metraje is calculated here with the rules (what the editor shows)."""
    origen = valor if isinstance(valor, dict) else {}
    clase = origen.get("clase") or "distribucion"
    tipo = str(origen.get("tipo") or "ADSS").upper()
    color = str(origen.get("color") or COLOR_CABLE)
    errores = []
    if clase not in red.CLASES:
        errores.append("clase no válida (troncal, distribución o acometida)")
    if tipo not in ("ADSS", "FLAT"):
        errores.append("tipo de cable no válido (ADSS o FLAT)")
    if not _COLOR.match(color):
        errores.append("color no válido")
    try:
        hilos = None if "hilos" in origen and origen["hilos"] in (None, "") else int(origen.get("hilos") or 12)
        por_buffer, cruces = int(origen.get("hilos_por_buffer") or 12), int(origen.get("cruces") or 0)
    except (TypeError, ValueError):
        raise DatosInvalidos({"propiedades": "hilos, hilos por buffer y cruces deben ser números"}) from None
    if hilos is not None and hilos not in red.HILOS:
        errores.append("cantidad de hilos no válida (2, 4, 6, 8, 12, 24, 48, 72, 96 o 144)")
    if por_buffer not in red.HILOS_POR_BUFFER:
        errores.append("hilos por buffer: 2, 4, 6, 8 o 12")
    if not 0 <= cruces <= 500:
        errores.append("cruces fuera de rango")
    if errores:
        raise DatosInvalidos({"propiedades": "; ".join(errores)})
    extremos: list[dict[str, Any]] = []
    for clave in ("origen_id", "destino_id"):
        ident = origen.get(clave)
        if ident in (None, ""):
            extremos.append({})
            continue
        f = con.execute("SELECT e.id, e.tipo, e.nombre, ST_X(e.geom) AS lon, ST_Y(e.geom) AS lat FROM redes.lugares_elementos e "
                        "JOIN redes.lugares_carpetas c ON c.id = e.carpeta_id WHERE e.id = %s AND e.borrado_en IS NULL AND e.tipo = ANY(%s) "
                        "AND c.usuario_id = %s", (int(ident), list(PUNTUALES_RED), dueno_id)).fetchone()
        if f is None:
            raise DatosInvalidos({"propiedades": "un extremo del cable ya no existe (mufa, poste, cliente, nodo u ODF)"})
        extremos.append(dict(f))
    if extremos[0] and extremos[1] and extremos[0]["id"] == extremos[1]["id"]:
        raise DatosInvalidos({"propiedades": "el cable empieza y termina en el mismo elemento"})
    coords = [list(p) for p in coords]
    if extremos[0]:
        coords[0] = [extremos[0]["lon"], extremos[0]["lat"]]
    if extremos[1]:
        coords[-1] = [extremos[1]["lon"], extremos[1]["lat"]]
    lineal = metraje.longitud_m([(p[1], p[0]) for p in coords])
    try:
        from config import get_settings, load_rules
        regla = metraje.reglas(load_rules(get_settings().rules_path))
    except Exception:
        regla = metraje.reglas(None)
    salida: dict[str, Any] = {"clase": clase, "tipo": tipo, "hilos": hilos, "hilos_por_buffer": por_buffer, "color": color.lower(),
                              "cruces": cruces, "origen_id": extremos[0].get("id"), "destino_id": extremos[1].get("id"),
                              "longitud_m": round(lineal, 2),
                              "metraje": metraje.calcular(lineal, [x.get("tipo", "") for x in extremos], cruces, regla)}
    return salida, coords


def estilo(tipo: str, propiedades: dict[str, Any], previo: dict[str, Any]) -> dict[str, Any]:
    """The style a network element always has: its icon comes from the type and subtype, a cable's line from its class and color."""
    salida = dict(previo or {})
    if tipo == "cable":
        li = dict(salida.get("linea") or {})
        salida["linea"] = {"color": propiedades.get("color", COLOR_CABLE), "grosor": GROSOR_POR_CLASE.get(propiedades.get("clase"), 3),
                           "opacidad": li.get("opacidad", 1)}
        return salida
    figura, color, escala = _ICONOS.get((tipo, propiedades.get("subtipo")), _ICONOS[(tipo, None)] if (tipo, None) in _ICONOS else ("circulo", "#ff8c00", 1.0))
    salida["icono"] = {"tipo": "figura", "id": figura, "color": color, "escala": escala, "opacidad": 1.0}
    if "etiqueta" not in salida:
        salida["etiqueta"] = {"visible": tipo != "poste", "color": "#ffffff", "escala": 1.0}
    return salida


# --------------------------------------------------------------------------- cables que siguen a su elemento

def cables_de(con: Any, elemento_id: int) -> list[dict[str, Any]]:
    filas = con.execute("SELECT id, nombre, version, propiedades, ST_AsGeoJSON(geom, 8) AS geom FROM redes.lugares_elementos "
                        "WHERE tipo = 'cable' AND borrado_en IS NULL AND (propiedades->>'origen_id' = %s OR propiedades->>'destino_id' = %s)",
                        (str(int(elemento_id)), str(int(elemento_id)))).fetchall()
    return [dict(f) for f in filas]


def seguir_elemento(con: Any, usuario_id: int, elemento_id: int, lon: float, lat: float) -> None:
    """The cables attached to an element that moved: their end goes with it (the rest of the line stays) and the metraje is recalculated."""
    import json
    for c in cables_de(con, elemento_id):
        coords = json.loads(c["geom"])["coordinates"]
        p = c["propiedades"]
        if str(p.get("origen_id")) == str(elemento_id):
            coords[0] = [lon, lat]
        if str(p.get("destino_id")) == str(elemento_id):
            coords[-1] = [lon, lat]
        dueno = con.execute("SELECT c.usuario_id FROM redes.lugares_elementos e JOIN redes.lugares_carpetas c ON c.id = e.carpeta_id WHERE e.id = %s",
                            (c["id"],)).fetchone()["usuario_id"]
        nuevas, coords = limpiar_cable(con, p, dueno, coords)
        geom = "SRID=4326;LINESTRING(" + ", ".join(f"{x:.8f} {y:.8f}" for x, y in coords) + ")"
        repositorio.actualizar(con, "lugares_elementos", c["id"], c["version"], {"geom": geom, "propiedades": Jsonb(nuevas)}, usuario_id)


# --------------------------------------------------------------------------- guardar como proyecto

def _codigo_libre(con: Any, nombre: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", nombre).strip("-").upper()[:20] or "LUGARES"
    base = f"LUG-{base}"
    for n in range(0, 1000):
        codigo = base if n == 0 else f"{base}-{n + 1}"
        if not con.execute("SELECT 1 FROM redes.proyectos WHERE lower(codigo) = lower(%s) AND borrado_en IS NULL", (codigo,)).fetchone():
            return codigo
    raise DatosInvalidos({"codigo": "No se encontró un identificador libre para el proyecto"})


def guardar_como_proyecto(con: Any, actor: dict[str, Any], *, carpeta_id: int, nombre: str | None = None) -> dict[str, Any]:
    """Copies the network of a folder (with its subfolders) to a new project: elements and cables, the cables joined to the elements
    created. Marks, routes and polygons are not network and stay in the folder. Same checks as the project editor (red.guardar)."""
    import json
    from visor_rutas.redes import lugares
    lugares._exigir(con, actor, carpeta_id)
    carpetas, _ = lugares._descendientes(con, [int(carpeta_id)])
    filas = con.execute("SELECT id, carpeta_id, tipo, nombre, propiedades, ST_AsGeoJSON(geom, 8) AS geom FROM redes.lugares_elementos "
                        "WHERE carpeta_id = ANY(%s) AND borrado_en IS NULL ORDER BY orden, id", (carpetas,)).fetchall()
    puntos = [f for f in filas if f["tipo"] in PUNTUALES_RED]
    cables = [f for f in filas if f["tipo"] == "cable"]
    if not puntos:
        raise DatosInvalidos({"carpeta": "La carpeta no tiene elementos de red (mufas, postes, clientes, nodos u ODF) para guardar como proyecto"})
    nombre_proyecto = _texto(nombre, 160) or lugares._texto(con.execute("SELECT nombre FROM redes.lugares_carpetas WHERE id = %s", (int(carpeta_id),)).fetchone()["nombre"], 160)
    with con.transaction():
        elementos, posicion = [], {}
        for f in puntos:
            lon, lat = json.loads(f["geom"])["coordinates"]
            p = f["propiedades"] or {}
            posicion[f["id"]] = (lat, lon)
            propiedades = {k: p[k] for k in ("capacidad", "bandejas", "id_servicio") if p.get(k) not in (None, "")}
            elementos.append({"id": f"n{f['id']}", "tipo": f["tipo"], "subtipo": p.get("subtipo"), "nombre": f["nombre"], "codigo": p.get("codigo"),
                              "lat": lat, "lon": lon, "propiedades": propiedades})
        lat0 = sum(v[0] for v in posicion.values()) / len(posicion)
        lon0 = sum(v[1] for v in posicion.values()) / len(posicion)
        proyecto = proyectos.guardar(con, actor, datos={"nombre": nombre_proyecto, "codigo": _codigo_libre(con, nombre_proyecto), "lat": lat0, "lon": lon0,
                                                        "descripcion": "Creado con «Guardar como proyecto» desde Mis lugares"})["proyecto"]
        por_posicion = {(round(la, 7), round(lo, 7)): i for i, (la, lo) in posicion.items()}
        cambios_cables, omitidos = [], []
        for f in cables:
            p = f["propiedades"] or {}
            o, d = p.get("origen_id"), p.get("destino_id")
            if o not in posicion or d not in posicion:
                omitidos.append(f["nombre"])
                continue
            coords = json.loads(f["geom"])["coordinates"]
            vertices = []
            for i, (lon, lat) in enumerate(coords):
                ancla = o if i == 0 else d if i == len(coords) - 1 else por_posicion.get((round(lat, 7), round(lon, 7)))
                vertices.append({"lat": lat, "lon": lon, "elemento_id": f"n{ancla}" if ancla is not None else None})
            cambios_cables.append({"id": f"c{f['id']}", "nombre": f["nombre"], "clase": p.get("clase"), "tipo": p.get("tipo"), "hilos": p.get("hilos"),
                                   "hilos_por_buffer": p.get("hilos_por_buffer"), "color": p.get("color"), "cruces": p.get("cruces"),
                                   "origen_id": f"n{o}", "destino_id": f"n{d}", "vertices": vertices})
        guardado = red.guardar(con, actor, proyecto_id=proyecto["id"], cambios={"elementos": elementos, "cables": cambios_cables})
        repositorio.registrar(con, actor["id"], "proyecto", proyecto["id"], "editar",
                              {"origen": [None, f"Mis lugares, carpeta {int(carpeta_id)}"]}, proyecto_id=proyecto["id"])
    return {"proyecto": {k: proyecto[k] for k in ("id", "codigo", "nombre")},
            "resumen": {"elementos": len(elementos), "cables": len(cambios_cables), "cables_omitidos": omitidos,
                        "fuera_de_la_red": sum(1 for f in filas if f["tipo"] not in TIPOS_RED), "ids": len(guardado.get("ids", {}))}}
