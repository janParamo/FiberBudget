"""Migración de la red existente de los Visio al módulo de redes (fase 2 de docs/migracion_visio/PLAN.md).

Lee `red_fibra` (los Visio ya importados por red_fibra/importador.py) y el KMZ (`red_puntos`,
`red_lineas`), **solo para leer**, y crea en el esquema `redes`, en los proyectos base por región:
  - cada nodo (MUFA, NODO, MINI_NODO, ODF, RESERVA) → `elementos`, con su ubicación (real,
    estimada o "sin ubicar"), el punto del KMZ más cercano (`ref_externa`) y su referencia al Visio;
  - cada par de nodos con enlace → un `cable`, con sus hilos (etiqueta del Visio; si no, deducidos por
    continuidad o por el texto de la línea del KMZ, marcados "estimado"), la configuración de buffers
    de `business_rules.yaml` → `migracion_visio`, el trazo de la línea del KMZ que recorre el tramo
    (o una recta) y su metraje;
  - los hilos de cada cable (la base les pone buffer y color TIA).
Todo lleva `fuente`, `confianza` y `estado_migracion = automatica` (o `en_revision` si el Visio pedía
revisarlo). Es idempotente: la clave de cada nodo es su nombre normalizado + su coordenada redondeada;
lo que ya existe no se vuelve a crear.

    .\\.venv\\Scripts\\python.exe -m visor_rutas.redes.migrar_visio --simular            # reporte, no escribe
    .\\.venv\\Scripts\\python.exe -m visor_rutas.redes.migrar_visio                      # migra (respaldo previo)
    opciones: --zona "León" (proyecto base o carpeta Visio), --solo-mufas lista.txt (un nombre por línea),
              --salida carpeta del reporte (por defecto output/migracion_visio)
"""
import argparse
import collections
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import bandejas, metraje, mufa, repositorio
from visor_rutas.redes.db import DatosInvalidos

log = logging.getLogger(__name__)
PROTEGIDOS = ("editada", "validada")        # a person touched it: a re-import never overwrites it, it only reports
UMBRAL_UBICACION_M = 5
RAIZ = Path(__file__).resolve().parents[2]
TIPOS = {"MUFA": ("mufa", "empalme"), "RESERVA": ("mufa", "reserva"), "NODO": ("nodo", "nodo"),
         "MINI_NODO": ("nodo", "mini_nodo"), "ODF": ("odf", None)}
COLORES = {144: "#e53935", 96: "#fb8c00", 72: "#1e88e5", 48: "#8e24aa", 24: "#43a047", 12: "#00acc1"}
COLOR_DESCONOCIDO = "#9e9e9e"
_HILOS_TEXTO = re.compile(r"\b(2|4|6|8|12|24|48|72|96|144)\s*(?:H|HILOS|F)\b|\bFO\s*(2|4|6|8|12|24|48|72|96|144)\b", re.I)
_CONFIG_TEXTO = re.compile(r"(\d{1,2})\s*BUFFERS?\s*DE\s*(\d{1,2})\s*(?:H|HILOS)|(?<![\d/])\b(\d{1,2})\s*X\s*(2|4|6|8|12)\b", re.I)

DEFECTO = {"configuracion_por_hilos": {2: "1x2", 4: "1x4", 6: "1x6", 8: "1x8", 12: "1x12", 24: "6x4", 48: "6x8", 72: "6x12",
                                       96: "8x12", 144: "12x12"},
           "tipo_fibra": "SM dispersión cero", "palabras_troncal": ["TRONCAL", "BACKBONE"], "tolerancia_linea_kmz_m": 25,
           "tolerancia_punto_kmz_m": 30, "inferir_hilos": {"continuidad_ambos_lados": True, "continuidad_un_lado": True, "texto_kmz": True},
           "migrar_reservas": True, "troncales_a_region_km": 5, "proyectos_base": {"defecto": "Red existente – Managua", "zonas": {}}}


# --------------------------------------------------------------------------- reglas y claves

def reglas(rules: dict[str, Any] | None = None) -> dict[str, Any]:
    if rules is None:
        try:
            from config import get_settings, load_rules
            rules = load_rules(get_settings().rules_path)
        except Exception:
            rules = {}
    r = {**DEFECTO, **((rules or {}).get("migracion_visio") or {})}
    r["configuracion_por_hilos"] = {int(k): str(v) for k, v in r["configuracion_por_hilos"].items()}
    r["inferir_hilos"] = {**DEFECTO["inferir_hilos"], **(r.get("inferir_hilos") or {})}
    return r


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def _comparable(texto: Any) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", _sin_acentos(str(texto or "")).upper()).split())


def region_de_carpeta(zona: str | None, r: dict[str, Any]) -> str | None:
    """Base project whose folder list names this Visio folder (zone), or None."""
    z = _comparable(zona)
    for proyecto, carpetas in (r["proyectos_base"].get("zonas") or {}).items():
        if any(_comparable(c) == z for c in carpetas):
            return proyecto
    return None


def proyecto_de_zona(zona: str | None, r: dict[str, Any]) -> str:
    """Base project of a Visio folder (zone): the first region whose list names it, else the default."""
    return region_de_carpeta(zona, r) or r["proyectos_base"]["defecto"]


def _distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return metraje.longitud_m([a, b]) / 1000


def ubicar_troncales(elementos: list[dict[str, Any]], r: dict[str, Any], nodos: list[dict[str, Any]]) -> None:
    """A trunk mufa (folder without a region) next to a region's centre goes to that region; a mufa
    of a regional folder sitting at another region's centre is only flagged (its coordinate may be
    borrowed). Centres: median lat / lon of ALL the Visio nodes of each region's folders (not only
    this run's, so a --zona run decides the same as a full one)."""
    limite = float(r.get("troncales_a_region_km") or 0)
    if limite <= 0:
        return
    puntos: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for n in nodos:
        region = region_de_carpeta(n["zona"], r)
        if region and n["lat"] is not None:
            puntos[region].append((float(n["lat"]), float(n["lon"])))
    mediana = lambda xs: sorted(xs)[len(xs) // 2]
    centros = {p: (mediana([x[0] for x in v]), mediana([x[1] for x in v])) for p, v in puntos.items()}
    if not centros:
        return
    for e in elementos:
        if e["lat"] is None:
            continue
        aqui = (float(e["lat"]), float(e["lon"]))
        cerca, km = min(((p, _distancia_km(aqui, c)) for p, c in centros.items()), key=lambda x: x[1])
        if km > limite or cerca == e["proyecto"]:
            continue
        if region_de_carpeta(e["ref_visio"]["zona"], r) is None:
            e["avisos"].append(f"mufa de troncal: va a {cerca} (a {km:.1f} km de su centro)")
            e["proyecto"] = cerca
        else:
            e["avisos"].append(f"revisar la coordenada: su carpeta es de {e['proyecto']} pero está a {km:.1f} km del centro de {cerca}")


def clave_nodo(n: dict[str, Any]) -> str:
    """Stable key (the Visio ids change on every re-import): normalized name + coordinate to 4
    decimals (~11 m), or + zone when it has no coordinate."""
    nombre = _comparable(n["nombre_normalizado"] or n["nombre"])
    if n["lat"] is not None and n["lon"] is not None:
        return f"{nombre}|{float(n['lat']):.4f},{float(n['lon']):.4f}"
    return f"{nombre}|zona:{_comparable(n['zona'])}"


def configuracion(hilos: int | None, r: dict[str, Any]) -> tuple[int, str | None]:
    """(hilos_por_buffer, "6x4") for a fibre count with the rule; 12 per buffer when unknown."""
    if not hilos:
        return 12, None
    texto = r["configuracion_por_hilos"].get(int(hilos))
    if texto and "x" in texto:
        por_buffer = int(texto.split("x")[1])
        if por_buffer in (2, 4, 6, 8, 12):
            return por_buffer, texto
    return (hilos if hilos in (2, 4, 6, 8, 12) else 12), None


def _slug(texto: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]+", "-", _sin_acentos(texto).upper())).strip("-")


# --------------------------------------------------------------------------- lectura (solo lectura)

def cargar_visio(fuente: Any, r: dict[str, Any]) -> dict[str, Any]:
    """Nodes, files and links of `red_fibra` (PostgreSQL copy published by importador.py)."""
    tipos = [t for t in TIPOS if t != "RESERVA" or r.get("migrar_reservas", True)]
    nodos = {f["id"]: dict(f) for f in fuente.execute(
        "SELECT id, nombre, nombre_normalizado, tipo, propietario, lat, lon, fuente_coord, zona, notas, requiere_revision, "
        "motivo_revision FROM red_fibra.nodos WHERE tipo = ANY(%s)", (tipos,)).fetchall()}
    archivos: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in fuente.execute("SELECT a.nodo_id, a.rol, f.ruta_relativa, f.md5 FROM red_fibra.nodo_apariciones a "
                            "JOIN red_fibra.archivos f ON f.id = a.archivo_id WHERE a.nodo_id = ANY(%s) ORDER BY a.nodo_id, a.rol",
                            (list(nodos),)).fetchall():
        archivos[f["nodo_id"]].append({"ruta": f["ruta_relativa"], "md5": f["md5"], "rol": f["rol"]})
    todos_tipos = {f["id"]: f["tipo"] for f in fuente.execute("SELECT id, tipo FROM red_fibra.nodos").fetchall()}
    enlaces = [dict(f) for f in fuente.execute(
        "SELECT id, nodo_a_id, nodo_b_id, hilos_cable, longitud_m, hilos_usados, enlace_logico, fuente, confianza, texto_original "
        "FROM red_fibra.enlaces ORDER BY id").fetchall()]
    return {"nodos": nodos, "archivos": archivos, "enlaces": enlaces, "tipos": todos_tipos}


def puntos_kmz(kmz: Any, nodos: list[dict[str, Any]], tolerancia: float) -> dict[int, dict[str, Any]]:
    """Nearest KMZ mufa / reserve point to each located node, within `tolerancia` metres."""
    ub = [n for n in nodos if n["lat"] is not None]
    if not ub:
        return {}
    filas = kmz.execute("""
        SELECT n.id, k.id AS kmz_id, k.nombre, k.categoria, k.d FROM unnest(%(i)s::int[], %(la)s::float8[], %(lo)s::float8[]) AS n(id, lat, lon)
        JOIN LATERAL (SELECT p.id, p.nombre, p.categoria,
                             ST_Distance(p.geom::geography, ST_SetSRID(ST_MakePoint(n.lon, n.lat), 4326)::geography) AS d
                      FROM red_puntos p WHERE p.categoria IN ('mufa', 'reserva')
                      ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(n.lon, n.lat), 4326) LIMIT 1) k ON k.d <= %(t)s""",
                        {"i": [n["id"] for n in ub], "la": [float(n["lat"]) for n in ub], "lo": [float(n["lon"]) for n in ub], "t": tolerancia}).fetchall()
    return {f["id"]: {"kmz_punto_id": f["kmz_id"], "nombre": f["nombre"], "categoria": f["categoria"], "distancia_m": round(f["d"], 1)}
            for f in filas}


def lineas_kmz(kmz: Any, pares: list[tuple[int, int, float, float, float, float]], tolerancia: float) -> dict[tuple[int, int], dict[str, Any]]:
    """For each pair (a, b, lat_a, lon_a, lat_b, lon_b): the KMZ line (not a client drop) that runs
    between both points (its stretch measures 0.8–2.5 x the straight distance), cut to that stretch and
    oriented from a to b; with the fibre count its text says, if any."""
    if not pares:
        return {}
    filas = kmz.execute("""
        WITH pr AS (SELECT a, b, ST_SetSRID(ST_MakePoint(lo1, la1), 4326) p1, ST_SetSRID(ST_MakePoint(lo2, la2), 4326) p2
                    FROM unnest(%(a)s::int[], %(b)s::int[], %(la1)s::float8[], %(lo1)s::float8[], %(la2)s::float8[], %(lo2)s::float8[])
                    AS t(a, b, la1, lo1, la2, lo2)),
        cand AS (
          SELECT pr.a, pr.b, l.id, l.nombre, l.descripcion, l.tipo, ST_LineMerge(l.geom) g,
                 ST_LineLocatePoint(ST_LineMerge(l.geom), pr.p1) f1, ST_LineLocatePoint(ST_LineMerge(l.geom), pr.p2) f2,
                 ST_Distance(pr.p1::geography, pr.p2::geography) d
          FROM pr JOIN red_lineas l ON ST_DWithin(l.geom::geography, pr.p1::geography, %(t)s)
                                   AND ST_DWithin(l.geom::geography, pr.p2::geography, %(t)s)
          WHERE GeometryType(ST_LineMerge(l.geom)) = 'LINESTRING'
            AND coalesce(l.nombre, '') !~* '^\\s*C\\d{4,6}' AND coalesce(l.descripcion, '') !~* 'CLIENTE'),
        tramo AS (SELECT *, ST_LineSubstring(g, least(f1, f2), greatest(f1, f2)) s FROM cand WHERE f1 <> f2),
        medido AS (SELECT *, ST_Length(s::geography) largo FROM tramo)
        SELECT DISTINCT ON (a, b) a, b, id, nombre, descripcion, tipo, largo, d,
               ST_AsGeoJSON(ST_Simplify(CASE WHEN f1 <= f2 THEN s ELSE ST_Reverse(s) END, 0.00002), 7) AS geojson
        FROM medido WHERE largo BETWEEN 0.8 * d AND 2.5 * d + 30
        ORDER BY a, b, abs(largo - d)""",
                        {"a": [p[0] for p in pares], "b": [p[1] for p in pares], "la1": [p[2] for p in pares], "lo1": [p[3] for p in pares],
                         "la2": [p[4] for p in pares], "lo2": [p[5] for p in pares], "t": tolerancia}).fetchall()
    salida = {}
    for f in filas:
        texto = " ".join(str(f[k] or "") for k in ("nombre", "descripcion", "tipo"))
        m = _HILOS_TEXTO.search(texto)
        salida[(f["a"], f["b"])] = {"kmz_linea_id": f["id"], "nombre": f["nombre"], "texto": texto[:200].strip(),
                                    "hilos": int(next(g for g in m.groups() if g)) if m else None,
                                    "coordenadas": json.loads(f["geojson"])["coordinates"], "largo_m": round(f["largo"], 1)}
    return salida


# --------------------------------------------------------------------------- plan

@dataclass
class Plan:
    reglas: dict[str, Any]
    elementos: list[dict[str, Any]] = field(default_factory=list)
    cables: list[dict[str, Any]] = field(default_factory=list)
    omitidos: list[dict[str, Any]] = field(default_factory=list)
    filtro: str = ""
    clave_de: dict[int, str] = field(default_factory=dict)      # every Visio node id -> its element key (phase 3)
    diferencias: list[dict[str, Any]] = field(default_factory=list)   # phase 7: what differs from what is migrated (see `comparar`)


def planificar(fuente: Any, kmz: Any, r: dict[str, Any] | None = None, *, zona: str | None = None,
               solo: set[str] | None = None) -> Plan:
    """What would be migrated (nothing is written): elements, cables and what is left out, with why."""
    r = r or reglas()
    datos = cargar_visio(fuente, r)
    plan = Plan(r, filtro=" · ".join(x for x in (f"zona {zona}" if zona else "", f"{len(solo)} mufas de la lista" if solo else "") if x))
    elegidos: dict[int, dict[str, Any]] = {}
    vistos: dict[str, int] = {}
    plan.clave_de = {i: clave_nodo(n) for i, n in datos["nodos"].items()}
    for n in sorted(datos["nodos"].values(), key=lambda x: x["id"]):
        proyecto = proyecto_de_zona(n["zona"], r)
        if zona and not (_comparable(zona) in _comparable(proyecto) or _comparable(zona) == _comparable(n["zona"])):
            continue                                          # --zona: a base project ("León") or a Visio folder ("Red Leon")
        if solo and _comparable(n["nombre"]) not in solo and _comparable(n["nombre_normalizado"]) not in solo:
            continue
        clave = clave_nodo(n)
        if clave in vistos:
            plan.omitidos.append({"entidad": "nodo", "clave": clave, "nombre": n["nombre"], "motivo":
                                  f"repetido en el Visio (mismo nombre y coordenada que el nodo {vistos[clave]})"})
            continue
        vistos[clave] = n["id"]
        tipo, subtipo = TIPOS[n["tipo"]]
        fuente_coord = n["fuente_coord"] or ""
        ubicacion = "real" if fuente_coord in ("visio", "excel", "excel+visio") else "estimada" if fuente_coord == "estimada_vecinos" else "sin_ubicar"
        if n["lat"] is None:
            ubicacion = "sin_ubicar"
        notas = [x.strip() for x in re.split(r"[;,|]", n["notas"] or "") if x.strip()]
        avisos = []
        if ubicacion == "sin_ubicar":
            avisos.append("sin ubicar: colóquela en el mapa")
        elif ubicacion == "estimada":
            avisos.append("ubicación estimada por sus vecinas")
        if n["requiere_revision"]:
            avisos.append(f"el Visio pide revisarla: {n['motivo_revision'] or ''}".strip())
        elegidos[n["id"]] = {
            "nodo_id": n["id"], "clave": clave, "proyecto": proyecto, "tipo": tipo, "subtipo": subtipo, "nombre": (n["nombre"] or "")[:160],
            "tipo_visio": n["tipo"], "lat": n["lat"], "lon": n["lon"], "ubicacion_fuente": ubicacion,
            "fuente": "excel_anillos" if fuente_coord.startswith("excel") else "texto_diagrama",
            "confianza": "alta" if fuente_coord.startswith("excel") else "media",
            "estado_migracion": "en_revision" if n["requiere_revision"] else "automatica",
            "propiedades": {k: v for k, v in {"propietario": n["propietario"], "notas": notas or None,
                                              "subtipo_estimado": True if tipo == "mufa" and subtipo == "empalme" else None}.items() if v},
            "ref_visio": {"clave": clave, "nodo_id": n["id"], "nombre_visio": n["nombre"], "zona": n["zona"], "fuente_coord": n["fuente_coord"],
                          "archivos": datos["archivos"].get(n["id"], []), "notas": n["notas"], "motivo_revision": n["motivo_revision"]},
            "kmz": None, "avisos": avisos}
    for p, k in puntos_kmz(kmz, list(datos["nodos"][i] for i in elegidos), r["tolerancia_punto_kmz_m"]).items():
        elegidos[p]["kmz"] = k
    plan.elementos = list(elegidos.values())
    ubicar_troncales(plan.elementos, r, list(datos["nodos"].values()))

    # links -> one cable per pair of nodes (several Visio links of the same pair are merged)
    pares: dict[tuple[int, int], list[dict[str, Any]]] = collections.defaultdict(list)
    for e in datos["enlaces"]:
        a, b = e["nodo_a_id"], e["nodo_b_id"]
        if a == b:
            continue
        pares[(min(a, b), max(a, b))].append(e)
    nodos = datos["nodos"]
    conocidos: dict[tuple[int, int], int] = {}
    for par, es in pares.items():
        h = max((e["hilos_cable"] for e in es if e["hilos_cable"]), default=None)
        if h:
            conocidos[par] = h
    vecinos: dict[int, set[int]] = collections.defaultdict(set)
    for a, b in pares:
        vecinos[a].add(b)
        vecinos[b].add(a)
    candidatos = []
    for (a, b), es in pares.items():
        fuera = [x for x in (a, b) if x not in elegidos]
        if (zona or solo) and len(fuera) == 2:
            continue                                          # a pair entirely outside this run
        if fuera:
            # a pair that touches a node outside this run is only reported when that node is of a migrable type
            # but filtered out by --zona / --solo-mufas: it is not an error, just "not in this run"
            tipos = [datos["tipos"].get(x) for x in fuera]
            if all(t in TIPOS for t in tipos) and (zona or solo):
                continue
            plan.omitidos.append({"entidad": "cable", "clave": f"{a}-{b}", "nombre": " – ".join(
                str((nodos.get(x) or {}).get("nombre") or f"nodo {x} ({datos['tipos'].get(x, '?')})") for x in (a, b)),
                "motivo": f"un extremo no es mufa, nodo, ODF ni reserva ({', '.join(str(t) for t in tipos)})"})
            continue
        ea, eb = elegidos[a], elegidos[b]
        if ea["lat"] is None or eb["lat"] is None:
            plan.omitidos.append({"entidad": "cable", "clave": f"{ea['clave']}||{eb['clave']}", "nombre": f"{ea['nombre']} – {eb['nombre']}",
                                  "motivo": "un extremo está sin ubicar (se crea cuando se coloque)"})
            continue
        candidatos.append((a, b, es))
    trazos = lineas_kmz(kmz, [(a, b, float(elegidos[a]["lat"]), float(elegidos[a]["lon"]), float(elegidos[b]["lat"]), float(elegidos[b]["lon"]))
                              for a, b, _ in candidatos], r["tolerancia_linea_kmz_m"])
    palabras = [p.upper() for p in r["palabras_troncal"]]
    for a, b, es in candidatos:
        ea, eb = elegidos[a], elegidos[b]
        primero = sorted(es, key=lambda e: (e["fuente"] != "excel", e["id"]))[0]
        if primero["nodo_a_id"] != a:                          # keep the direction the Visio / Excel wrote
            ea, eb = eb, ea
        avisos = []
        hilos, origen_hilos = conocidos.get((a, b)), "visio"
        trazo = trazos.get((a, b))
        if not hilos:
            lado_a = {conocidos[(min(a, x), max(a, x))] for x in vecinos[a] - {b} if (min(a, x), max(a, x)) in conocidos}
            lado_b = {conocidos[(min(b, x), max(b, x))] for x in vecinos[b] - {a} if (min(b, x), max(b, x)) in conocidos}
            comunes = lado_a & lado_b
            if r["inferir_hilos"]["continuidad_ambos_lados"] and len(comunes) == 1:
                hilos, origen_hilos = comunes.pop(), "continuidad_ambos_lados"
            elif r["inferir_hilos"]["continuidad_un_lado"] and len(lado_a | lado_b) == 1:
                hilos, origen_hilos = next(iter(lado_a | lado_b)), "continuidad_un_lado"
                avisos.append("hilos por continuidad de un solo lado: por confirmar")
            elif r["inferir_hilos"]["texto_kmz"] and trazo and trazo["hilos"]:
                hilos, origen_hilos = trazo["hilos"], "texto_kmz"
                avisos.append(f"hilos según la línea del KMZ «{trazo['nombre']}»: por confirmar")
            else:
                hilos, origen_hilos = None, None
                avisos.append("hilos desconocidos")
        textos = " | ".join(sorted({str(e["texto_original"] or "") for e in es if e["texto_original"]}))
        m = _CONFIG_TEXTO.search(textos)
        por_buffer, conf = configuracion(hilos, r)
        conf_estimada = True
        if hilos and m:                                       # the diagram says it ("6 BUFFER DE 2HILOS", "4X6")
            pb = int(m.group(2) or m.group(4))
            if pb in (2, 4, 6, 8, 12) and hilos % pb == 0:
                por_buffer, conf, conf_estimada = pb, f"{hilos // pb}x{pb}", False
        troncal = any(e["fuente"] == "excel" for e in es) or any(p in textos.upper() for p in palabras)
        puntos = ([(ea["lat"], ea["lon"])] + ([(la, lo) for lo, la in trazo["coordenadas"][1:-1]] if trazo else []) + [(eb["lat"], eb["lon"])])
        lineal = metraje.longitud_m([(float(la), float(lo)) for la, lo in puntos])
        confianza = "media" if origen_hilos == "visio" else "baja"
        plan.cables.append({
            "clave": "||".join(sorted((ea["clave"], eb["clave"]))), "proyecto": ea["proyecto"], "origen": ea, "destino": eb,
            "nombre": f"{ea['nombre']} – {eb['nombre']}"[:160], "hilos": hilos, "origen_hilos": origen_hilos, "hilos_por_buffer": por_buffer,
            "configuracion": conf, "configuracion_estimada": conf_estimada if hilos else True,
            "clase": "troncal" if troncal else "distribucion", "color": COLORES.get(hilos or 0, COLOR_DESCONOCIDO) if hilos else COLOR_DESCONOCIDO,
            "geom_fuente": "kmz" if trazo else "recta", "puntos": puntos, "longitud_m": round(lineal, 1),
            "fuente": "excel_anillos" if any(e["fuente"] == "excel" for e in es) else ("texto_diagrama" if origen_hilos == "visio" else "estimado"),
            "confianza": confianza, "entre_regiones": ea["proyecto"] != eb["proyecto"],
            "ref_visio": {"clave": "||".join(sorted((ea["clave"], eb["clave"]))), "enlaces": [e["id"] for e in es],
                          "fuentes": sorted({e["fuente"] for e in es}), "textos": textos[:500] or None, "hilos_origen": origen_hilos,
                          "longitud_visio_m": max((float(e["longitud_m"]) for e in es if e["longitud_m"]), default=None),
                          "kmz": {k: trazo[k] for k in ("kmz_linea_id", "nombre", "texto", "hilos", "largo_m")} if trazo else None},
            "avisos": avisos + (["cable entre dos regiones (queda en la región de su origen)"] if ea["proyecto"] != eb["proyecto"] else [])})
    return plan


# --------------------------------------------------------------------------- aplicar

def _proyecto_base(con: Any, nombre: str, elementos: list[dict[str, Any]], usuario_id: int | None) -> int:
    f = con.execute("SELECT id FROM redes.proyectos WHERE es_red_base AND nombre = %s AND borrado_en IS NULL", (nombre,)).fetchone()
    if f:
        return f["id"]
    ub = [e for e in elementos if e["lat"] is not None]
    centro = f"SRID=4326;POINT({sum(float(e['lon']) for e in ub) / len(ub):.6f} {sum(float(e['lat']) for e in ub) / len(ub):.6f})" if ub else None
    codigo = "RED-" + _slug(nombre.replace("Red existente", ""))
    fila = repositorio.insertar(con, "proyectos", {
        "codigo": codigo, "nombre": nombre, "es_red_base": True, "zona": nombre.split("–")[-1].strip(), "ubicacion": centro,
        "descripcion": "Red existente migrada de los diagramas Visio (red_fibra). Cada dato lleva su fuente y confianza."}, usuario_id)
    repositorio.registrar(con, usuario_id, "proyecto", fila["id"], "crear", {"red_base": [None, nombre]}, proyecto_id=fila["id"])
    return fila["id"]


def _mover(con: Any, tabla: str, id_: int, desde: int, hacia: int, usuario_id: int | None) -> None:
    """Moves a migrated element or cable to another base project (with its problems and pending tasks)."""
    con.execute(f"UPDATE redes.{tabla} SET proyecto_id = %s, version = version + 1, actualizado_en = now(), actualizado_por = %s "
                "WHERE id = %s", (hacia, usuario_id, id_))
    columna = {"elementos": "elemento_id", "cables": "cable_id"}[tabla]
    for otra in ("problemas", "pendientes"):
        con.execute(f"UPDATE redes.{otra} SET proyecto_id = %s WHERE {columna} = %s AND proyecto_id = %s", (hacia, id_, desde))
    for pid in (desde, hacia):
        repositorio.registrar(con, usuario_id, columna[:-3], id_, "editar", {"proyecto": [desde, hacia]}, proyecto_id=pid)


def _mover_elemento(con: Any, id_: int, desde: int, hacia: int, usuario_id: int | None) -> None:
    """Moves a migrated element to another base project with what hangs from it: the inside of the
    mufa, its notes and diagrams. Its cables follow the rule "a cable lives in its origin's project"
    (the cable loop moves them)."""
    _mover(con, "elementos", id_, desde, hacia, usuario_id)
    for tabla in ("splitters", "conectores", "conexiones"):
        con.execute(f"UPDATE redes.{tabla} SET proyecto_id = %s WHERE mufa_id = %s AND proyecto_id = %s", (hacia, id_, desde))
    con.execute("UPDATE redes.notas SET proyecto_id = %s WHERE (mufa_id = %s OR elemento_id = %s) AND proyecto_id = %s", (hacia, id_, id_, desde))
    con.execute("UPDATE redes.diagramas_logicos SET proyecto_id = %s WHERE elemento_id = %s AND proyecto_id = %s", (hacia, id_, desde))


def comparar(con: Any, plan: Plan) -> list[dict[str, Any]]:
    """Phase 7 (safe re-import): what the Visio says today against what is already migrated. One entry per
    element / cable that differs, or that the Visio no longer gives. `protegido` = a person edited or
    validated it (or, for a cable, one of its mufas): it is only reported. Otherwise `cambios` is what
    `aplicar` writes. Nothing is written here (the simulation uses it too)."""
    salida: list[dict[str, Any]] = []
    ya_e = {f["clave"]: f for f in con.execute(
        "SELECT e.id, e.version, e.nombre, e.estado_migracion, e.ubicacion_fuente, e.ref_visio ->> 'clave' AS clave, "
        "ST_Y(e.ubicacion::geometry) AS lat, ST_X(e.ubicacion::geometry) AS lon FROM redes.elementos e "
        "JOIN redes.proyectos p ON p.id = e.proyecto_id WHERE e.borrado_en IS NULL AND p.es_red_base AND e.ref_visio ? 'clave' "
        "AND e.tipo IN ('mufa', 'nodo', 'odf')").fetchall()}                # not the clients of phase 3, which carry a key too
    claves = set()
    for e in plan.elementos:
        claves.add(e["clave"])
        ya = ya_e.get(e["clave"])
        if ya is None:
            continue
        cambios: dict[str, Any] = {}
        textos: list[str] = []
        if ya["nombre"] != e["nombre"]:
            cambios["nombre"] = e["nombre"]
            textos.append(f"nombre: «{ya['nombre']}» → «{e['nombre']}»")
        if e["lat"] is not None and ya["ubicacion_fuente"] != "usuario":
            punto = f"SRID=4326;POINT({float(e['lon']):.8f} {float(e['lat']):.8f})"
            if ya["lat"] is None:
                cambios.update(ubicacion=punto, ubicacion_fuente=e["ubicacion_fuente"])
                textos.append("ahora el Visio le da coordenada")
            else:
                metros = _distancia_km((float(ya["lat"]), float(ya["lon"])), (float(e["lat"]), float(e["lon"]))) * 1000
                if metros > UMBRAL_UBICACION_M:
                    textos.append(f"ubicación: el Visio la pone {metros:.0f} m más allá")
                    if e["ubicacion_fuente"] == "real" or ya["ubicacion_fuente"] != "real":
                        cambios.update(ubicacion=punto, ubicacion_fuente=e["ubicacion_fuente"])
                elif ya["ubicacion_fuente"] != e["ubicacion_fuente"] and e["ubicacion_fuente"] == "real":
                    cambios["ubicacion_fuente"] = e["ubicacion_fuente"]
        if ya["estado_migracion"] in ("automatica", "en_revision") and e["estado_migracion"] != ya["estado_migracion"]:
            cambios["estado_migracion"] = e["estado_migracion"]
            textos.append("el Visio pide revisarla" if e["estado_migracion"] == "en_revision" else "el Visio ya no pide revisarla")
        if textos:
            salida.append({"entidad": "nodo", "tabla": "elementos", "clave": e["clave"], "nombre": e["nombre"], "id": ya["id"],
                           "version": ya["version"], "estado": ya["estado_migracion"], "protegido": ya["estado_migracion"] in PROTEGIDOS,
                           "textos": textos, "cambios": cambios})
    ya_c = {f["clave"]: f for f in con.execute(
        "SELECT c.id, c.version, c.nombre, c.hilos, c.hilos_por_buffer, c.configuracion_estimada, c.clase, c.estado_migracion, "
        "c.ref_visio ->> 'clave' AS clave, o.estado_migracion AS estado_origen, d.estado_migracion AS estado_destino FROM redes.cables c "
        "LEFT JOIN redes.elementos o ON o.id = c.origen_id LEFT JOIN redes.elementos d ON d.id = c.destino_id "
        "WHERE c.borrado_en IS NULL AND c.ref_visio ? 'clave'").fetchall()}
    for c in plan.cables:
        claves.add(c["clave"])
        ya = ya_c.get(c["clave"])
        if ya is None:
            continue
        cambios, textos = {}, []
        if c["hilos"] and c["hilos"] != ya["hilos"]:
            cambios.update(hilos=c["hilos"], hilos_por_buffer=c["hilos_por_buffer"], color=c["color"], configuracion_estimada=c["configuracion_estimada"])
            textos.append(f"hilos: {ya['hilos'] or 'desconocidos'} → {c['hilos']} ({c['origen_hilos']})")
        elif c["hilos"] is None and ya["hilos"]:
            textos.append(f"el Visio ya no da la cantidad de hilos (el cable tiene {ya['hilos']}): se conserva")
        elif c["hilos"] and ya["configuracion_estimada"] and not c["configuracion_estimada"] and ya["hilos_por_buffer"] != c["hilos_por_buffer"]:
            cambios.update(hilos_por_buffer=c["hilos_por_buffer"], configuracion_estimada=False)
            textos.append(f"configuración: ahora el diagrama la dice ({c['configuracion']})")
        if c["clase"] != ya["clase"]:
            cambios["clase"] = c["clase"]
            textos.append(f"clase: {ya['clase']} → {c['clase']}")
        if textos:
            protegido = any(x in PROTEGIDOS for x in (ya["estado_migracion"], ya["estado_origen"], ya["estado_destino"]))
            salida.append({"entidad": "enlace", "tabla": "cables", "clave": c["clave"], "nombre": c["nombre"], "id": ya["id"],
                           "version": ya["version"], "estado": ya["estado_migracion"], "protegido": protegido, "textos": textos, "cambios": cambios})
    if not plan.filtro:                                         # a partial run cannot tell what is gone
        for entidad, tabla, ya_ in (("nodo", "elementos", ya_e), ("enlace", "cables", ya_c)):
            for clave, ya in ya_.items():
                if clave not in claves:
                    salida.append({"entidad": entidad, "tabla": tabla, "clave": clave, "nombre": ya["nombre"], "id": ya["id"], "version": ya["version"],
                                   "estado": ya["estado_migracion"], "protegido": True, "cambios": {}, "desaparecido": True,
                                   "textos": ["ya no sale del Visio (o sus extremos cambiaron): se conserva, no se borra"]})
    return salida


def _aplicar_diferencia(con: Any, d: dict[str, Any], usuario_id: int | None, conteo: collections.Counter, logs: list[tuple]) -> None:
    """Writes the changes of an unprotected element / cable, or only reports a protected one."""
    resumen = "; ".join(d["textos"])
    if d.get("desaparecido"):
        conteo["elementos_ya_no_en_visio" if d["tabla"] == "elementos" else "cables_ya_no_en_visio"] += 1
        logs.append((d["entidad"], d["clave"], "conflicto", resumen, None))
        return
    if d["protegido"] or not d["cambios"]:
        conteo["diferencias_sin_aplicar"] += 1
        logs.append((d["entidad"], d["clave"], "conflicto", f"{d['estado']}: no se toca. {resumen}", None))
        return
    try:
        with con.transaction():
            antes, despues = repositorio.actualizar(con, d["tabla"], d["id"], d["version"], d["cambios"], usuario_id)
            if "hilos" in d["cambios"]:
                mufa.sincronizar_hilos(con, d["id"], d["cambios"]["hilos"], usuario_id)
            repositorio.registrar(con, usuario_id, "elemento" if d["tabla"] == "elementos" else "cable", d["id"], "editar",
                                  repositorio.diferencias(antes, despues), proyecto_id=antes["proyecto_id"])
    except DatosInvalidos as exc:
        conteo["diferencias_sin_aplicar"] += 1
        logs.append((d["entidad"], d["clave"], "conflicto", f"no se pudo actualizar ({'; '.join(exc.errores.values())}). {resumen}", None))
        return
    conteo["elementos_actualizados" if d["tabla"] == "elementos" else "cables_actualizados"] += 1
    logs.append((d["entidad"], d["clave"], "actualizar", resumen, None))


def aplicar(con: Any, plan: Plan, usuario_id: int | None, corrida_id: int) -> dict[str, int]:
    """Writes the plan in ONE transaction (all or nothing). Existing keys are not created again
    (idempotent); phase 7: what nobody edited is brought up to date with the Visio, what a person
    edited or validated is never overwritten, only reported (log + `diferencias_sin_aplicar`)."""
    conteo: collections.Counter = collections.Counter()
    logs: list[tuple] = []
    with con.transaction():
        for d in comparar(con, plan):                       # before any move: the moves raise the version
            _aplicar_diferencia(con, d, usuario_id, conteo, logs)
            plan.diferencias.append(d)
        proyectos_ids = {nombre: _proyecto_base(con, nombre, [e for e in plan.elementos if e["proyecto"] == nombre], usuario_id)
                         for nombre in sorted({e["proyecto"] for e in plan.elementos})}
        # what is already migrated, in any base project (the key is unique across them)
        existentes = {f["clave"]: f for f in con.execute(
            "SELECT e.ref_visio ->> 'clave' AS clave, e.id, e.proyecto_id, e.estado_migracion FROM redes.elementos e "
            "JOIN redes.proyectos p ON p.id = e.proyecto_id WHERE e.borrado_en IS NULL AND p.es_red_base AND e.ref_visio ? 'clave'").fetchall()}
        por_clave: dict[str, int] = {k: f["id"] for k, f in existentes.items()}
        for e in plan.elementos:
            pid = proyectos_ids[e["proyecto"]]
            ya = existentes.get(e["clave"])
            if ya and ya["proyecto_id"] != pid:                 # the rules now put it in another region
                if ya["estado_migracion"] == "editada":
                    conteo["elementos_no_movidos_editados"] += 1
                    logs.append(("nodo", e["clave"], "conflicto", f"editado por un usuario: no se mueve a {e['proyecto']}", None))
                else:
                    _mover_elemento(con, ya["id"], ya["proyecto_id"], pid, usuario_id)
                    conteo["elementos_movidos"] += 1
                    logs.append(("nodo", e["clave"], "actualizar", f"movido a {e['proyecto']}", Jsonb(e["avisos"]) if e["avisos"] else None))
                continue
            if ya:
                conteo["elementos_ya_estaban"] += 1
                logs.append(("nodo", e["clave"], "omitir", "ya migrado", None))
                continue
            fila = repositorio.insertar(con, "elementos", {
                "proyecto_id": pid, "tipo": e["tipo"], "subtipo": e["subtipo"], "nombre": e["nombre"],
                "ubicacion": None if e["lat"] is None else f"SRID=4326;POINT({float(e['lon']):.8f} {float(e['lat']):.8f})",
                "ubicacion_fuente": e["ubicacion_fuente"], "propiedades": Jsonb(e["propiedades"]),
                "ref_externa": Jsonb({"kmz": e["kmz"]}) if e["kmz"] else None, "fuente": e["fuente"], "confianza": e["confianza"],
                "estado_migracion": e["estado_migracion"], "ref_visio": Jsonb(e["ref_visio"])}, usuario_id)
            por_clave[e["clave"]] = fila["id"]
            conteo["elementos_creados"] += 1
            conteo[f"elementos_{e['ubicacion_fuente']}"] += 1
            logs.append(("nodo", e["clave"], "crear", e["proyecto"], Jsonb(e["avisos"]) if e["avisos"] else None))
        cables_existentes = {f["clave"]: f for f in con.execute(
            "SELECT ref_visio ->> 'clave' AS clave, id, proyecto_id, estado_migracion FROM redes.cables "
            "WHERE borrado_en IS NULL AND ref_visio ? 'clave'").fetchall()}
        regla = metraje.reglas(None)
        try:
            from config import get_settings, load_rules
            regla = metraje.reglas(load_rules(get_settings().rules_path))
        except Exception:
            pass
        for c in plan.cables:
            ya = cables_existentes.get(c["clave"])
            if ya and ya["proyecto_id"] != proyectos_ids[c["proyecto"]] and ya["estado_migracion"] != "editada":
                _mover(con, "cables", ya["id"], ya["proyecto_id"], proyectos_ids[c["proyecto"]], usuario_id)
                conteo["cables_movidos"] += 1
                logs.append(("enlace", c["clave"], "actualizar", f"movido a {c['proyecto']}", None))
                continue
            if ya:
                conteo["cables_ya_estaban"] += 1
                logs.append(("enlace", c["clave"], "omitir", "ya migrado", None))
                continue
            a, b = por_clave[c["origen"]["clave"]], por_clave[c["destino"]["clave"]]
            vertices = [{"lat": float(la), "lon": float(lo), "elemento_id": None} for la, lo in c["puntos"]]
            vertices[0]["elemento_id"], vertices[-1]["elemento_id"] = a, b
            extremos = [c["origen"]["tipo"], c["destino"]["tipo"]]
            fila = repositorio.insertar(con, "cables", {
                "proyecto_id": proyectos_ids[c["proyecto"]], "nombre": c["nombre"], "clase": c["clase"], "tipo": "ADSS",
                "hilos": c["hilos"], "hilos_por_buffer": c["hilos_por_buffer"], "color": c["color"], "origen_id": a, "destino_id": b,
                "vertices": Jsonb(vertices), "geom": "SRID=4326;LINESTRING(" + ", ".join(f"{float(lo):.8f} {float(la):.8f}" for la, lo in c["puntos"]) + ")",
                "cruces": 0, "longitud_m": c["longitud_m"], "metraje": Jsonb(metraje.calcular(c["longitud_m"], extremos, 0, regla)),
                "configuracion_estimada": c["configuracion_estimada"], "tipo_fibra": plan.reglas["tipo_fibra"], "fuente": c["fuente"],
                "confianza": c["confianza"], "geom_fuente": c["geom_fuente"], "estado_migracion": "automatica",
                "ref_visio": Jsonb(c["ref_visio"])}, usuario_id)
            if c["hilos"]:
                mufa.sincronizar_hilos(con, fila["id"], c["hilos"], usuario_id)
                conteo["hilos_creados"] += c["hilos"]
            conteo["cables_creados"] += 1
            conteo[f"cables_hilos_{c['origen_hilos'] or 'desconocidos'}"] += 1
            conteo[f"cables_trazo_{c['geom_fuente']}"] += 1
            logs.append(("enlace", c["clave"], "crear", c["proyecto"], Jsonb(c["avisos"]) if c["avisos"] else None))
        for o in plan.omitidos:
            logs.append((o["entidad"], o["clave"], "omitir", o["motivo"], None))
        with con.cursor() as cur:
            cur.executemany("INSERT INTO redes.migracion_visio_log (corrida_id, entidad, clave, accion, resultado, avisos) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", [(corrida_id, *x) for x in logs])
        for nombre, pid in proyectos_ids.items():
            repositorio.registrar(con, usuario_id, "proyecto", pid, "editar", {"migracion_visio": [None, f"corrida {corrida_id}"]}, proyecto_id=pid)
    conteo["proyectos_base"] = len(proyectos_ids)
    return dict(conteo)


# --------------------------------------------------------------------------- reporte Excel

FASE0 = {"nodos (sin reservas)": 3490, "reservas": 13, "pares de nodos con enlace": 3138, "pares con hilos en el Visio": 921}


def reporte(plan: Plan, ruta: Path, conteo: dict[str, int] | None = None, modo: str = "simular", contenido: Any = None) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    negrita, cabeza = Font(bold=True), PatternFill("solid", fgColor="DCE6F1")

    def hoja(ws, columnas: list[str], filas: list[list[Any]], anchos: list[int]):
        ws.append(columnas)
        for c in ws[1]:
            c.font, c.fill = negrita, cabeza
        for f in filas:
            ws.append(f)
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        if filas:
            ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "Resumen"
    ws.append([f"Migración Visio → mufas interactivas · {'SIMULACIÓN (no se escribió nada)' if modo == 'simular' else 'MIGRACIÓN REAL'}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Generado {datetime.now():%Y-%m-%d %H:%M}" + (f" · filtro: {plan.filtro}" if plan.filtro else " · toda la red")])
    ws.append([])
    por_proyecto = collections.defaultdict(collections.Counter)
    for e in plan.elementos:
        k = por_proyecto[e["proyecto"]]
        k["elementos"] += 1
        k[e["ubicacion_fuente"]] += 1
        k[e["tipo_visio"]] += 1
        k["con punto KMZ"] += bool(e["kmz"])
    for c in plan.cables:
        k = por_proyecto[c["proyecto"]]
        k["cables"] += 1
        k["cables con hilos"] += bool(c["hilos"])
        k["hilos del Visio"] += c["origen_hilos"] == "visio"
        k["hilos deducidos"] += c["origen_hilos"] not in ("visio", None)
        k["trazo KMZ"] += c["geom_fuente"] == "kmz"
        k["hilos a crear"] += c["hilos"] or 0
    cols = ["Proyecto base", "elementos", "MUFA", "NODO", "MINI_NODO", "ODF", "RESERVA", "real", "estimada", "sin_ubicar", "con punto KMZ",
            "cables", "cables con hilos", "hilos del Visio", "hilos deducidos", "trazo KMZ", "hilos a crear"]
    filas = [[p] + [k[c] for c in cols[1:]] for p, k in sorted(por_proyecto.items(), key=lambda x: -x[1]["elementos"])]
    total = ["TOTAL"] + [sum(f[i] for f in filas) for i in range(1, len(cols))]
    inicio = ws.max_row + 1
    ws.append(cols)
    for c in ws[inicio]:
        c.font, c.fill = negrita, cabeza
    for f in filas + [total]:
        ws.append(f)
    for c in ws[ws.max_row]:
        c.font = negrita
    ws.append([])
    ws.append(["Comparación con la cobertura medida en la fase 0 (FASE0_DIAGNOSTICO.md)"])
    ws[ws.max_row][0].font = negrita
    tot = collections.Counter()
    for e in plan.elementos:
        tot["reservas" if e["tipo_visio"] == "RESERVA" else "nodos (sin reservas)"] += 1
    omit_cables = collections.Counter(o["motivo"].split(" (")[0] for o in plan.omitidos if o["entidad"] == "cable")
    nodos_rep = sum(o["entidad"] == "nodo" for o in plan.omitidos)
    ws.append(["Dato", "Fase 0", "Este plan", "Explicación"])
    for c in ws[ws.max_row]:
        c.font, c.fill = negrita, cabeza
    ws.append(["Nodos MUFA/NODO/MINI_NODO/ODF", FASE0["nodos (sin reservas)"], tot["nodos (sin reservas)"] + nodos_rep,
               f"{tot['nodos (sin reservas)']} a migrar + {nodos_rep} repetidos (mismo nombre y coordenada) que se migran una sola vez"])
    ws.append(["Reservas", FASE0["reservas"], tot["reservas"], "migradas por decisión de Jan"])
    ws.append(["Pares de nodos con enlace", FASE0["pares de nodos con enlace"], len(plan.cables) + sum(omit_cables.values()),
               "; ".join(f"{n} omitidos: {m}" for m, n in omit_cables.items()) or "—"])
    ws.append(["Cables con hilos del Visio", FASE0["pares con hilos en el Visio"], sum(c["origen_hilos"] == "visio" for c in plan.cables),
               "los pares que tocan un nodo que no se migra (OTRO, CLIENTE) no cuentan"])
    if contenido is not None:
        motivos = collections.Counter((o["entidad"], o["motivo"].split(":")[0]) for o in contenido.omitidos)
        codigos = {p["codigo_cliente"] for s in contenido.splitters for p in s["puertos"].values() if p["codigo_cliente"]}
        codigos |= {c["codigo_cliente"] for c in contenido.clientes if c["codigo_cliente"]}
        ws.append(["Splitters (fase 3)", "1 519 con 1xN", len(contenido.splitters),
                   "uno por texto distinto en cada mufa; " + "; ".join(f"{n} {m}" for (e, m), n in motivos.items() if e == "splitter")])
        ws.append(["Listas de puertos", 285, sum(1 for s in contenido.splitters if s["puertos"]),
                   "; ".join(f"{n} {m}" for (e, m), n in motivos.items() if e == "puertos") or "—"])
        ws.append(["Puertos con cliente", "1 075 con C#####", sum(len(s["puertos"]) for s in contenido.splitters),
                   "incluye puertos que alimentan otro splitter o un nombre sin código"])
        ws.append(["Clientes (códigos distintos)", 3315, len(codigos), f"{len(contenido.clientes)} en una mufa sin puerto conocido"])
        ws.append(["Clientes ubicados en el mapa", "70 % (KMZ)", len(contenido.ubicaciones),
                   f"{100 * len(contenido.ubicaciones) / max(1, len(codigos)):.0f} %: punta de su acometida del KMZ"])
        ws.append(["Empalmes del Excel de anillos", "~212", len(contenido.empalmes),
                   "se crean solo si los dos cables tienen hilos conocidos (ver «Resultado» y el log)"])
        ws.append(["Textos que nombran hilos / fusiones dibujadas", "21 / sin medir", 0,
                   "no dicen entre qué cables / precisión sin medir: quedan «sin diagramar»"])
    if conteo:
        ws.append([])
        ws.append(["Resultado de la corrida real"])
        ws[ws.max_row][0].font = negrita
        for k, v in sorted(conteo.items()):
            ws.append([k, v])
    ws.column_dimensions["A"].width = 34
    for col in "BCDEFGHIJKLMNOPQ":
        ws.column_dimensions[col].width = 12
    ws.column_dimensions["D"].width = 14

    hoja(wb.create_sheet("Mufas"), ["Clave", "Nombre", "Tipo Visio", "Tipo", "Subtipo", "Proyecto base", "Ubicación", "Lat", "Lon",
                                    "Punto KMZ", "Distancia KMZ (m)", "Fuente", "Confianza", "Estado", "Archivos Visio", "Notas", "Avisos"],
         [[e["clave"], e["nombre"], e["tipo_visio"], e["tipo"], e["subtipo"], e["proyecto"], e["ubicacion_fuente"], e["lat"], e["lon"],
           (e["kmz"] or {}).get("nombre"), (e["kmz"] or {}).get("distancia_m"), e["fuente"], e["confianza"], e["estado_migracion"],
           "; ".join(a["ruta"] for a in e["ref_visio"]["archivos"][:3]), "; ".join(e["propiedades"].get("notas") or []), "; ".join(e["avisos"])]
          for e in plan.elementos], [44, 34, 11, 7, 10, 26, 10, 11, 11, 26, 10, 14, 9, 12, 50, 20, 40])
    hoja(wb.create_sheet("Cables"), ["Origen", "Destino", "Proyecto base", "Hilos", "Hilos según", "Configuración", "Config. estimada",
                                     "Clase", "Trazo", "Longitud (m)", "Longitud Visio (m)", "Fuentes Visio", "Línea KMZ", "Avisos"],
         [[c["origen"]["nombre"], c["destino"]["nombre"], c["proyecto"], c["hilos"], c["origen_hilos"] or "desconocido", c["configuracion"],
           "sí" if c["configuracion_estimada"] else "no", c["clase"], c["geom_fuente"], c["longitud_m"], c["ref_visio"]["longitud_visio_m"],
           ", ".join(c["ref_visio"]["fuentes"]), (c["ref_visio"]["kmz"] or {}).get("nombre"), "; ".join(c["avisos"])]
          for c in plan.cables], [34, 34, 26, 7, 22, 12, 9, 12, 8, 11, 11, 22, 30, 50])
    omitidos = plan.omitidos + (contenido.omitidos if contenido else [])
    if contenido is not None:
        nombre = {e["clave"]: e["nombre"] for e in plan.elementos}
        hoja(wb.create_sheet("Splitters"), ["Mufa", "Splitter", "Salidas", "Relación", "OLT", "Puerto OLT", "Potencia (dBm)", "Depende de",
                                            "Puertos con cliente", "De", "Texto Visio"],
             [[nombre[s["elemento"]], s["nombre"], s["salidas"], s["relacion"], s["propiedades"].get("olt"), s["propiedades"].get("puerto_olt"),
               s["propiedades"].get("potencia_dbm"), s["propiedades"].get("depende_de"), len(s["puertos"]),
               "lista de puertos" if s["origen"] == "lista" else "texto", s["propiedades"].get("texto_visio")] for s in contenido.splitters],
             [34, 34, 8, 8, 18, 11, 10, 26, 10, 14, 60])
        filas_cli = [[nombre[s["elemento"]], f"{s['nombre']} · salida {n}", p["codigo_cliente"], p["nombre"], p["id_servicio"],
                      "sí" if p["codigo_cliente"] in contenido.ubicaciones else "no"]
                     for s in contenido.splitters for n, p in sorted(s["puertos"].items())]
        filas_cli += [[nombre[c["elemento"]], "en la mufa (sin puerto)", c["codigo_cliente"], c["nombre"], c["id_servicio"],
                       "sí" if c["codigo_cliente"] in contenido.ubicaciones else "no"] for c in contenido.clientes]
        hoja(wb.create_sheet("Clientes"), ["Mufa", "Dónde", "Código", "Nombre", "ID servicio", "En el mapa (KMZ)"], filas_cli,
             [34, 40, 10, 44, 12, 10])
        # phase 4: the model each mufa would get (same rule as bandejas.elegir_modelo)
        rb = bandejas.reglas()
        mayor: dict[str, int] = {}
        for c in plan.cables:
            for k in (c["origen"]["clave"], c["destino"]["clave"]):
                if c["hilos"]:
                    mayor[k] = max(mayor.get(k, 0), c["hilos"])
        salidas: dict[str, list[int]] = collections.defaultdict(list)
        for s in contenido.splitters:
            salidas[s["elemento"]].append(s["salidas"])
        modelos = []
        for e in plan.elementos:
            if e["tipo"] != "mufa" or e["subtipo"] == "reserva":
                continue
            notas = " ".join(e["propiedades"].get("notas") or [])
            m = bandejas.elegir_modelo(mayor.get(e["clave"]), salidas[e["clave"]], rb, sangria="SANGRIA" in notas.upper())
            modelos.append([e["nombre"], e["proyecto"], m["capacidad"], m["bandejas"], bandejas.formato_de_texto(notas),
                            mayor.get(e["clave"]), len(salidas[e["clave"]]), m["motivo"], "; ".join(m["avisos"])])
        hoja(wb.create_sheet("Modelos"), ["Mufa", "Proyecto base", "Capacidad", "Bandejas", "Formato", "Cable mayor (hilos)", "Splitters",
                                          "Por qué (estimado)", "Avisos"], modelos, [34, 26, 9, 8, 11, 10, 9, 50, 50])
        cuenta = collections.Counter(f[2] for f in modelos)
        ws.append(["Modelos de mufa (fase 4)", "1 207 de 48 · 10 de 96", len(modelos),
                   f"{cuenta[48]} de 48 · {cuenta[96]} de 96 · {sum(1 for f in modelos if f[8])} con avisos; todos estimados"])
        hoja(wb.create_sheet("Empalmes"), ["Anillo", "Mufa", "Hilo de entrada", "Viene de", "Hilo de salida", "Va hacia"],
             [[x["nombre"].split(" #")[0], nombre[x["elemento"]], x["hilo_entra"], x["de"]["nombre"], x["hilo_sale"], x["hacia"]["nombre"]]
              for x in contenido.empalmes], [20, 34, 8, 34, 8, 34])
    if plan.diferencias:                                        # phase 7: re-import against what is already migrated
        def que_pasa(d):
            if d.get("desaparecido"):
                return "ya no sale del Visio"
            return "protegida: no se toca" if d["protegido"] else ("actualizada" if modo == "real" else "se actualizaría")
        hoja(wb.create_sheet("Diferencias"), ["Entidad", "Nombre", "Estado en la base", "Qué pasa", "Diferencias"],
             [[{"nodo": "mufa / nodo", "enlace": "cable"}[d["entidad"]], d["nombre"], d["estado"], que_pasa(d), "; ".join(d["textos"])]
              for d in sorted(plan.diferencias, key=lambda d: (d["protegido"], d["entidad"], d["nombre"]))], [12, 44, 14, 22, 90])
    hoja(wb.create_sheet("No migrado"), ["Entidad", "Nombre", "Clave", "Motivo"],
         [[o["entidad"], o["nombre"], o["clave"], o["motivo"]] for o in omitidos], [10, 50, 50, 70])
    for w in wb.worksheets[1:]:
        for fila in w.iter_rows(min_row=2):
            for c in fila:
                c.alignment = Alignment(vertical="top")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta


# --------------------------------------------------------------------------- línea de comandos

def _conexion_kmz() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    from config import get_settings
    s = get_settings()
    return psycopg.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password,
                           row_factory=dict_row, options="-c default_transaction_read_only=on -c statement_timeout=600000")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Migra la red existente de los Visio (red_fibra) al módulo de redes.")
    ap.add_argument("--simular", action="store_true", help="solo calcula y genera el reporte Excel; no escribe en la base")
    ap.add_argument("--zona", help="solo un proyecto base o una carpeta Visio (por ejemplo «León» o «Red Rivas»)")
    ap.add_argument("--solo-mufas", type=Path, help="archivo con un nombre de mufa por línea")
    ap.add_argument("--salida", type=Path, default=RAIZ / "output" / "migracion_visio", help="carpeta del reporte")
    a = ap.parse_args(argv)
    from visor_rutas.redes import db, migrar, respaldo
    con = db.conectar()
    migrar.aplicar(con)
    con.execute("SET statement_timeout = 600000")
    kmz = _conexion_kmz()
    solo = None
    if a.solo_mufas:
        solo = {_comparable(x) for x in a.solo_mufas.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")}
    from visor_rutas.redes import migrar_visio_contenido as contenido_mufas
    r = reglas()
    plan = planificar(con, kmz, r, zona=a.zona, solo=solo)
    contenido = contenido_mufas.planificar_contenido(con, kmz, plan)
    sello = f"{datetime.now():%Y-%m-%d_%H%M%S}"
    if a.simular:
        plan.diferencias = comparar(con, plan)
        ruta = reporte(plan, a.salida / f"simulacion_{sello}.xlsx", contenido=contenido)
        dif = plan.diferencias
        print(f"SIMULACIÓN: {len(plan.elementos)} elementos, {len(plan.cables)} cables, {len(contenido.splitters)} splitters, "
              f"{len(contenido.ubicaciones)} clientes en el mapa, {len(contenido.empalmes)} empalmes, "
              f"{len(plan.omitidos) + len(contenido.omitidos)} sin migrar. Contra lo ya migrado: "
              f"{sum(1 for d in dif if not d['protegido'])} se actualizarían, {sum(1 for d in dif if d['protegido'] and not d.get('desaparecido'))} "
              f"protegidas con diferencias, {sum(1 for d in dif if d.get('desaparecido'))} ya no salen del Visio. Reporte: {ruta}")
        return 0
    archivo, aviso = respaldo.respaldar(con, "migración Visio", None, motivo="antes de migrar la red existente de los Visio")
    print(f"Respaldo previo: {archivo}" + (f" ({aviso})" if aviso else ""))
    corrida = con.execute("INSERT INTO redes.migracion_visio_corridas (modo, zona, respaldo) VALUES ('real', %s, %s) RETURNING id",
                          (a.zona or (f"lista {a.solo_mufas.name}" if a.solo_mufas else None), archivo)).fetchone()["id"]
    try:
        conteo = aplicar(con, plan, None, corrida)
        conteo.update(contenido_mufas.aplicar_contenido(con, contenido, None, corrida))
        conteo.update(bandejas.migrar_modelos(con, None))                  # phase 4: model and trays of each mufa
    except Exception as exc:
        con.execute("UPDATE redes.migracion_visio_corridas SET fin = now(), resultado = 'error', conteos = %s WHERE id = %s",
                    (Jsonb({"error": f"{type(exc).__name__}: {exc}"}), corrida))
        raise
    con.execute("UPDATE redes.migracion_visio_corridas SET fin = now(), resultado = %s, conteos = %s WHERE id = %s",
                ("con_avisos" if plan.omitidos or contenido.omitidos else "ok", Jsonb(conteo), corrida))
    ruta = reporte(plan, a.salida / f"migracion_{sello}.xlsx", conteo, modo="real", contenido=contenido)
    print(f"MIGRADO (corrida {corrida}): {conteo}. Reporte: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
