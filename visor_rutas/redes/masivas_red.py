"""Lo que se hace con el resultado de las coordenadas masivas (visor v2, fase 6): guardarlo en una carpeta de «Mis lugares» o como un proyecto.

- `a_lugares`: una carpeta con una marca por punto (con el número del punto como ícono hasta el 10) y, si se piden, una subcarpeta «Rutas» con
  la ruta calculada de cada uno.
- `a_proyecto`: un proyecto nuevo con un cliente por punto, la mufa o el punto de conexión de cada ruta y un cable de acometida (FLAT, 2 hilos) de la
  conexión al cliente con el trazo de la ruta. Se guarda con la misma función del editor de proyectos (red.guardar), con sus mismas validaciones.
Los puntos son los de la tabla de resultados: {n, nombre, codigo, lat, lon, conexion, conexion_lat, conexion_lon, ruta, tipo_cable}.
"""
import math
import re
from typing import Any

from visor_rutas.redes import lugares, proyectos, red
from visor_rutas.redes.db import DatosInvalidos

MAX_PUNTOS = 500
_CODIGO_CLIENTE = re.compile(r"^C\d{3,8}$", re.I)


def _puntos(valor: Any) -> list[dict[str, Any]]:
    if not isinstance(valor, list) or not valor:
        raise DatosInvalidos({"puntos": "No hay puntos que guardar"})
    if len(valor) > MAX_PUNTOS:
        raise DatosInvalidos({"puntos": f"Máximo {MAX_PUNTOS} puntos"})
    salida = []
    for i, p in enumerate(valor, 1):
        p = p if isinstance(p, dict) else {}
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except (KeyError, TypeError, ValueError):
            raise DatosInvalidos({"puntos": f"El punto {i} no tiene una coordenada válida"}) from None
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise DatosInvalidos({"puntos": f"El punto {i} está fuera del mundo"})
        salida.append({**p, "n": int(p.get("n") or i), "lat": lat, "lon": lon, "nombre": " ".join(str(p.get("nombre") or "").split())[:160]})
    return salida


def _ruta(p: dict[str, Any]) -> list[list[float]] | None:
    r = p.get("ruta")
    if not isinstance(r, list) or len(r) < 2:
        return None
    try:
        return [[float(x[1]), float(x[0])] for x in r[:5000]]            # [lat, lon] -> GeoJSON [lon, lat]
    except (TypeError, ValueError, IndexError):
        return None


def a_lugares(con: Any, actor: dict[str, Any], *, nombre: str, puntos: list[dict[str, Any]], con_rutas: bool = False) -> dict[str, Any]:
    """A folder of Mis lugares with the points (and optionally their routes)."""
    pts = _puntos(puntos)
    limpio = " ".join(str(nombre or "").split())[:160] or "Coordenadas masivas"
    with con.transaction():
        carpeta = lugares.guardar_carpeta(con, actor, nombre=limpio)["id"]
        for i, p in enumerate(pts, 1):
            icono = {"tipo": "numero", "id": str(i), "color": "#2f6bff"} if i <= 10 else None
            descripcion = f"<p>{p['codigo']}</p>" if p.get("codigo") else None
            lugares.guardar_lugar(con, actor, carpeta_id=carpeta, tipo="marca", nombre=p["nombre"] or f"Punto {p['n']}",
                                  geom={"type": "Point", "coordinates": [p["lon"], p["lat"]]}, estilo={"icono": icono} if icono else None, descripcion_html=descripcion)
        rutas = [(p, _ruta(p)) for p in pts if con_rutas]
        rutas = [(p, r) for p, r in rutas if r]
        if rutas:
            sub = lugares.guardar_carpeta(con, actor, nombre="Rutas", padre_id=carpeta)["id"]
            for p, r in rutas:
                lugares.guardar_lugar(con, actor, carpeta_id=sub, tipo="ruta", nombre=f"Ruta {p['nombre'] or p['n']}", geom={"type": "LineString", "coordinates": r},
                                      estilo={"linea": {"color": "#ffe600", "grosor": 4, "opacidad": 1}})
    return {**lugares.arbol(con, actor), "carpeta_id": carpeta, "puntos": len(pts), "rutas": len(rutas)}


def _codigo_libre(con: Any, nombre: str) -> str:
    base = "MAS-" + (re.sub(r"[^A-Za-z0-9]+", "-", nombre).strip("-").upper()[:20] or "LOTE")
    for n in range(0, 1000):
        codigo = base if n == 0 else f"{base}-{n + 1}"
        if not con.execute("SELECT 1 FROM redes.proyectos WHERE lower(codigo) = lower(%s) AND borrado_en IS NULL", (codigo,)).fetchone():
            return codigo
    raise DatosInvalidos({"codigo": "No se encontró un identificador libre para el proyecto"})


def a_proyecto(con: Any, actor: dict[str, Any], *, nombre: str, puntos: list[dict[str, Any]]) -> dict[str, Any]:
    """A project with a client per point, the connection point of each and the route as the cable between them."""
    pts = _puntos(puntos)
    limpio = " ".join(str(nombre or "").split())[:160] or "Coordenadas masivas"
    with con.transaction():
        lat0 = sum(p["lat"] for p in pts) / len(pts)
        lon0 = sum(p["lon"] for p in pts) / len(pts)
        proyecto = proyectos.guardar(con, actor, datos={"nombre": limpio, "codigo": _codigo_libre(con, limpio), "lat": lat0, "lon": lon0,
                                                        "descripcion": "Creado con «Guardar como proyecto» desde las coordenadas masivas"})["proyecto"]
        elementos: list[dict[str, Any]] = []
        cables: list[dict[str, Any]] = []
        mufas: dict[tuple[str, float, float], str] = {}
        sin_ruta: list[str] = []
        for p in pts:
            codigo = (p.get("codigo") or "").upper() if _CODIGO_CLIENTE.match(str(p.get("codigo") or "").strip()) else None
            cliente = f"c{p['n']}"
            elementos.append({"id": cliente, "tipo": "cliente", "nombre": p["nombre"] or f"Cliente {p['n']}", "codigo": codigo, "lat": p["lat"], "lon": p["lon"]})
            ruta = _ruta(p)
            try:
                clat, clon = float(p["conexion_lat"]), float(p["conexion_lon"])
            except (KeyError, TypeError, ValueError):
                sin_ruta.append(p["nombre"] or str(p["n"]))
                continue
            clave = (str(p.get("conexion") or ""), round(clat, 6), round(clon, 6))
            if clave not in mufas:
                mufas[clave] = f"m{len(mufas) + 1}"
                elementos.append({"id": mufas[clave], "tipo": "mufa", "subtipo": "empalme", "nombre": clave[0] or f"Punto de conexión {len(mufas)}", "lat": clat, "lon": clon})
            vertices = [{"lat": la, "lon": lo, "elemento_id": None} for lo, la in (ruta or [[clon, clat], [p["lon"], p["lat"]]])]
            vertices[0]["elemento_id"], vertices[-1]["elemento_id"] = mufas[clave], cliente
            if len({(v["lat"], v["lon"]) for v in vertices}) < 2:                 # the client is on the connection point: no cable to draw
                continue
            cables.append({"id": f"k{p['n']}", "nombre": f"Acometida {p['nombre'] or p['n']}", "clase": "acometida", "tipo": "FLAT" if "flat" in str(p.get("tipo_cable") or "").lower() else "ADSS",
                           "hilos": 2, "hilos_por_buffer": 2, "color": "#1f6feb", "origen_id": mufas[clave], "destino_id": cliente, "vertices": vertices})
        guardado = red.guardar(con, actor, proyecto_id=proyecto["id"], cambios={"elementos": elementos, "cables": cables})
    return {"proyecto": {k: proyecto[k] for k in ("id", "codigo", "nombre")},
            "resumen": {"clientes": len(pts), "mufas": len(mufas), "cables": len(cables), "sin_conexion": sin_ruta, "ids": len(guardado.get("ids", {}))}}
