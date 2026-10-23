"""Carga inicial del KMZ de la red en la base del presupuesto (DB_*): crea `red_puntos` / `red_lineas` y las llena.

Para una base vacía (por ejemplo, después de cambiar de máquina). Reutiliza el lector del visor (importar_kmz.leer), así que ve los mismos
elementos que el panel Lugares. Los polígonos no se cargan (el presupuesto no los usa).

    .\\.venv\\Scripts\\python.exe herramientas\\cargar_kmz.py                       # usa KMZ_PATH
    .\\.venv\\Scripts\\python.exe herramientas\\cargar_kmz.py --kmz "ruta\\RED DE IDEAY.kmz" --reemplazar

`tipo` es el nombre de la carpeta del KMZ en minúsculas y sin acentos («mufa», «poste de concreto», «mufas de corte», «trunk gpon»…), porque
business_rules.yaml y db.py filtran por él con ILIKE. Si una carpeta de arriba lleva una palabra de `excluded_tipo_keywords` («MUFAS EN MAL ESTADO»,
«NODOS DESHABILITADOS»…), esa carpeta da el `tipo`, para que sus mufas sigan excluidas.
"""
import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from config import get_settings  # noqa: E402
from visor_rutas import kmz_capas  # noqa: E402
from visor_rutas.redes import importar_kmz  # noqa: E402

ORIGEN = "kmz inicial"
LOTE = 2000

CREAR = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS public.red_puntos (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text);
CREATE TABLE IF NOT EXISTS public.red_lineas (id serial PRIMARY KEY, tabla_origen text, categoria text, nombre text, descripcion text, geom geometry, tipo text);
"""
INDICES = """
CREATE INDEX IF NOT EXISTS red_puntos_geom_gix ON public.red_puntos USING gist (geom);
CREATE INDEX IF NOT EXISTS red_lineas_geom_gix ON public.red_lineas USING gist (geom);
CREATE INDEX IF NOT EXISTS red_puntos_tipo_idx ON public.red_puntos (tipo);
CREATE INDEX IF NOT EXISTS red_lineas_tipo_idx ON public.red_lineas (tipo);
ANALYZE public.red_puntos;
ANALYZE public.red_lineas;
"""


def tipo_de(ruta: str, excluidas: list[str]) -> tuple[str, str]:
    """(categoria, tipo) for the folder path of an element."""
    carpetas = [c for c in ruta.split("/") if c]
    hoja = importar_kmz.normal(carpetas[-1])
    for c in carpetas:
        n = importar_kmz.normal(c)
        if any(k in n for k in excluidas):
            return hoja, n
    return hoja, hoja


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kmz", default=None, help="archivo .kmz (por defecto KMZ_PATH del .env)")
    ap.add_argument("--reemplazar", action="store_true", help="vaciar red_puntos y red_lineas antes de cargar")
    args = ap.parse_args()

    import yaml
    reglas = yaml.safe_load(open(get_settings().rules_path, encoding="utf-8")) or {}
    excluidas = [importar_kmz.normal(k) for k in reglas.get("excluded_tipo_keywords", [])]

    kmz = kmz_capas.ruta_kmz(args.kmz)
    print(f"Leyendo {kmz} ...")
    elementos = importar_kmz.leer(kmz.read_bytes())
    print(f"  {len(elementos)} elementos")

    pg = importar_kmz.conectar_presupuesto()
    pg.execute(CREAR)
    previo = {t: pg.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in ("red_puntos", "red_lineas")}
    if any(previo.values()):
        if not args.reemplazar:
            sys.exit(f"red_puntos / red_lineas ya tienen filas {previo}; usa --reemplazar para vaciarlas.")
        pg.execute("TRUNCATE public.red_puntos, public.red_lineas RESTART IDENTITY")

    lotes: dict[str, list] = {"red_puntos": [], "red_lineas": []}
    cuentas = {"red_puntos": 0, "red_lineas": 0}
    omitidos = 0

    def vaciar(tabla: str) -> None:
        if lotes[tabla]:
            with pg.cursor() as cur:
                cur.executemany(f"INSERT INTO {tabla} (tabla_origen, categoria, nombre, descripcion, geom, tipo) VALUES "
                                f"(%s, %s, %s, %s, ST_SetSRID(ST_Force2D(ST_GeomFromGeoJSON(%s)), 4326), %s)", lotes[tabla])
            cuentas[tabla] += len(lotes[tabla])
            lotes[tabla] = []

    for e in elementos:
        tabla = importar_kmz.TABLAS.get(e["tipo"])
        if tabla is None:
            omitidos += 1
            continue
        categoria, tipo = tipo_de(e["ruta"], excluidas)
        lotes[tabla].append((ORIGEN, categoria, (e["nombre"] or "").strip() or None, e["desc"] or None, json.dumps(e["geom"]), tipo))
        if len(lotes[tabla]) >= LOTE:
            vaciar(tabla)
    for t in lotes:
        vaciar(t)
    pg.commit()
    for sentencia in INDICES.strip().split("\n"):
        pg.execute(sentencia)
    pg.commit()
    print(f"Cargado: red_puntos {cuentas['red_puntos']}, red_lineas {cuentas['red_lineas']} ({omitidos} polígonos omitidos)")
    for t in ("red_puntos", "red_lineas"):
        filas = pg.execute(f"SELECT tipo, count(*) AS n FROM {t} GROUP BY tipo ORDER BY n DESC LIMIT 12").fetchall()
        print(f"  {t}: " + ", ".join(f"{f['tipo']} {f['n']}" for f in filas))


if __name__ == "__main__":
    main()
