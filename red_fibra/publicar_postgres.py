#!/usr/bin/env python3
"""
Publica en PostgreSQL la base generada por importador.py.

Uso:
    python publicar_postgres.py --sqlite red_fibra.db --pg "postgresql://usuario:clave@servidor:5432/ideay"
    (o defina la variable de entorno RED_FIBRA_PG con la cadena de conexión)

Qué hace:
  - Crea el esquema red_fibra si no existe (ejecuta schema_postgres.sql).
  - En UNA sola transacción reemplaza el contenido de las tablas con el de la última
    importación. Si algo falla, PostgreSQL queda exactamente como estaba.
  - Conserva el historial de importaciones (tabla importaciones).

Requisito: python -m pip install --user psycopg2-binary
"""
import argparse
import os
import sqlite3
import sys

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    sys.exit('Falta psycopg2:  python -m pip install --user psycopg2-binary')

AQUI = os.path.dirname(os.path.abspath(__file__))

# Orden de carga (respeta las llaves foráneas)
TABLAS = ['archivos', 'nodos', 'nodo_apariciones', 'enlaces', 'servicios', 'anillo_tramos', 'textos_crudos',
          'fusiones_piloto']
BOOLEANAS = {'nodos': ['requiere_revision']}
# Pueden faltar en una base SQLite o un esquema PostgreSQL anteriores al piloto de fusiones.
TABLAS_OPCIONALES = {'fusiones_piloto'}


def tablas_a_publicar(tablas_pg):
    """Tablas que se vacían y cargan: las opcionales solo si ya existen en PostgreSQL."""
    return [t for t in TABLAS if t not in TABLAS_OPCIONALES or t in tablas_pg]


def publicar(ruta_sqlite, dsn, crear_esquema=True):
    lite = sqlite3.connect(ruta_sqlite)
    lite.row_factory = sqlite3.Row
    pg = psycopg2.connect(dsn)
    try:
        with pg:
            with pg.cursor() as cur:
                if crear_esquema:
                    with open(os.path.join(AQUI, 'schema_postgres.sql'), encoding='utf-8') as f:
                        cur.execute(f.read())
                cur.execute('SET search_path TO red_fibra')
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'red_fibra'")
                tablas = tablas_a_publicar({r[0] for r in cur.fetchall()})
                en_sqlite = {r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

                # Importación: id nuevo en PostgreSQL para conservar el historial
                imp = dict(lite.execute('SELECT * FROM importaciones ORDER BY id DESC LIMIT 1').fetchone())
                cur.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM importaciones')
                nuevo_imp = cur.fetchone()[0]

                # Vaciar datos de la importación anterior (todo menos el historial)
                cur.execute('TRUNCATE ' + ', '.join(reversed(tablas)) + ' RESTART IDENTITY')

                imp['id'] = nuevo_imp
                cols = list(imp.keys())
                cur.execute('INSERT INTO importaciones (%s) VALUES (%s)' % (
                    ', '.join(cols), ', '.join(['%s'] * len(cols))), [imp[c] for c in cols])

                totales = {}
                for tabla in tablas:
                    if tabla not in en_sqlite:          # red_fibra.db anterior al piloto de fusiones
                        totales[tabla] = 0
                        continue
                    filas = lite.execute('SELECT * FROM %s' % tabla).fetchall()
                    totales[tabla] = len(filas)
                    if not filas:
                        continue
                    cols = filas[0].keys()
                    datos = []
                    for f in filas:
                        d = dict(f)
                        if tabla == 'archivos':
                            d['importacion_id'] = nuevo_imp
                        for b in BOOLEANAS.get(tabla, []):
                            d[b] = bool(d[b])
                        datos.append(tuple(d[c] for c in cols))
                    # archivos.duplicado_de apunta a la misma tabla: se carga en dos pasos
                    if tabla == 'archivos':
                        idx = list(cols).index('duplicado_de')
                        dup = [(r[idx], r[0]) for r in datos if r[idx] is not None]
                        datos = [tuple(None if i == idx else v for i, v in enumerate(r)) for r in datos]
                    execute_values(cur, 'INSERT INTO %s (%s) VALUES %%s' % (tabla, ', '.join(cols)),
                                   datos, page_size=2000)
                    if tabla == 'archivos' and dup:
                        execute_values(cur, 'UPDATE archivos SET duplicado_de = v.d FROM (VALUES %s) AS v(d, i) '
                                            'WHERE archivos.id = v.i', dup)
        print('Publicado en PostgreSQL (importación #%d):' % nuevo_imp)
        for t in TABLAS:
            print('   %-17s %7s filas' % (t, totales[t] if t in totales else '-'))
    finally:
        pg.close()
        lite.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sqlite', default='red_fibra.db')
    ap.add_argument('--pg', default=os.environ.get('RED_FIBRA_PG'),
                    help='Cadena de conexión, p. ej. postgresql://usuario:clave@servidor:5432/ideay')
    a = ap.parse_args()
    if not a.pg:
        sys.exit('Indique la conexión con --pg o la variable de entorno RED_FIBRA_PG')
    publicar(a.sqlite, a.pg)
