#!/usr/bin/env python3
"""
Consultas sobre la base de la red de fibra.

Funciona con la base SQLite (--db red_fibra.db) o con PostgreSQL
(--db "postgresql://usuario:clave@servidor:5432/ideay" o variable de entorno RED_FIBRA_PG).

Uso desde la terminal:
    python consultas.py cercanos 12.052271 -86.175817            # 5 nodos más cercanos
    python consultas.py cercanos 12.052271 -86.175817 --radio 2000 --solo-reales
    python consultas.py resumen
    python consultas.py exportar nodos.geojson                   # para abrir en Google Earth / QGIS / geojson.io

Uso desde Python (por ejemplo, en la API de presupuestos):
    from consultas import nodos_cercanos
    nodos_cercanos('red_fibra.db', 12.05, -86.17, n=3)
"""
import argparse
import json
import math
import sqlite3


def _dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _es_pg(db):
    return str(db).startswith(('postgresql://', 'postgres://'))


def _nodos_cercanos_pg(dsn, lat, lon, n, radio_m, solo_reales):
    import psycopg2
    import psycopg2.extras
    with psycopg2.connect(dsn) as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM red_fibra.nodos_cercanos(%s, %s, %s, %s, %s)',
                        (lat, lon, radio_m, n, solo_reales))
            return [dict(r) for r in cur.fetchall()]


def nodos_cercanos(db, lat, lon, n=5, radio_m=5000, tipos=('MUFA', 'NODO', 'MINI_NODO', 'ODF'),
                   solo_reales=False):
    """Nodos más cercanos a (lat, lon), ordenados por distancia en línea recta.

    db: ruta al archivo SQLite o cadena de conexión de PostgreSQL.
    solo_reales=True ignora los nodos cuya coordenada fue estimada a partir de sus vecinos.
    """
    if _es_pg(db):
        return _nodos_cercanos_pg(db, lat, lon, n, radio_m, solo_reales)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    dlat = radio_m / 111320.0
    dlon = radio_m / (111320.0 * max(math.cos(math.radians(lat)), 0.1))
    sql = '''SELECT id, nombre, tipo, propietario, lat, lon, fuente_coord, zona, notas, num_apariciones
             FROM nodos WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?'''
    params = [lat - dlat, lat + dlat, lon - dlon, lon + dlon]
    if tipos:
        sql += ' AND tipo IN (%s)' % ','.join('?' * len(tipos))
        params += list(tipos)
    if solo_reales:
        sql += " AND fuente_coord != 'estimada_vecinos'"
    filas = []
    for r in con.execute(sql, params):
        d = _dist_m(lat, lon, r['lat'], r['lon'])
        if d <= radio_m:
            fila = dict(r)
            fila['distancia_m'] = round(d, 1)
            fila['enlaces'] = con.execute(
                'SELECT COUNT(*) FROM enlaces WHERE nodo_a_id=? OR nodo_b_id=?', (r['id'], r['id'])).fetchone()[0]
            fila['clientes'] = con.execute(
                "SELECT COUNT(DISTINCT codigo_cliente) FROM servicios WHERE nodo_id=? AND tipo='cliente'",
                (r['id'],)).fetchone()[0]
            filas.append(fila)
    con.close()
    filas.sort(key=lambda f: f['distancia_m'])
    return filas[:n]


def resumen(db):
    con = sqlite3.connect(db)
    q = lambda s: con.execute(s).fetchall()
    imp = q('SELECT fecha, archivos_total, archivos_ok, archivos_error, archivos_duplicados, nodos, enlaces, servicios, notas '
            'FROM importaciones ORDER BY id DESC LIMIT 1')[0]
    print('Importación %s: %d archivos (%d ok, %d error, %d duplicados)' % imp[:5])
    print('Nodos %d | Enlaces %d | Servicios %d' % imp[5:8])
    print('Nota:', imp[8])
    print('\nNodos por tipo:', q('SELECT tipo, COUNT(*) FROM nodos GROUP BY 1 ORDER BY 2 DESC'))
    print('Origen de coordenadas:', q('SELECT COALESCE(fuente_coord, "sin coordenadas"), COUNT(*) FROM nodos GROUP BY 1 ORDER BY 2 DESC'))
    print('Nodos a revisar:', q('SELECT COUNT(*) FROM nodos WHERE requiere_revision=1')[0][0])
    print('Archivos con error:')
    for r in q("SELECT ruta_relativa, error FROM archivos WHERE estado='error'"):
        print('  -', r[0], '->', r[1])
    con.close()


def exportar_geojson(db, salida):
    con = sqlite3.connect(db)
    feats = []
    for r in con.execute('SELECT id, nombre, tipo, propietario, lat, lon, fuente_coord, zona, notas FROM nodos '
                         'WHERE lat IS NOT NULL'):
        feats.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [r[5], r[4]]},
                      'properties': {'id': r[0], 'nombre': r[1], 'tipo': r[2], 'propietario': r[3],
                                     'fuente_coord': r[6], 'zona': r[7], 'notas': r[8]}})
    for r in con.execute('''SELECT e.id, a.lat, a.lon, b.lat, b.lon, a.nombre, b.nombre, e.hilos_cable, e.fuente
                            FROM enlaces e JOIN nodos a ON a.id=e.nodo_a_id JOIN nodos b ON b.id=e.nodo_b_id
                            WHERE a.lat IS NOT NULL AND b.lat IS NOT NULL'''):
        feats.append({'type': 'Feature',
                      'geometry': {'type': 'LineString', 'coordinates': [[r[2], r[1]], [r[4], r[3]]]},
                      'properties': {'id': r[0], 'de': r[5], 'a': r[6], 'hilos': r[7], 'fuente': r[8]}})
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    print('Exportados %d elementos a %s' % (len(feats), salida))
    con.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    import os
    ap.add_argument('--db', default=os.environ.get('RED_FIBRA_PG') or 'red_fibra.db',
                    help='Archivo SQLite o cadena postgresql://... (por defecto RED_FIBRA_PG si existe)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('cercanos')
    c.add_argument('lat', type=float)
    c.add_argument('lon', type=float)
    c.add_argument('--n', type=int, default=5)
    c.add_argument('--radio', type=float, default=5000)
    c.add_argument('--solo-reales', action='store_true')
    sub.add_parser('resumen')
    e = sub.add_parser('exportar')
    e.add_argument('salida')
    a = ap.parse_args()
    if a.cmd == 'cercanos':
        filas = nodos_cercanos(a.db, a.lat, a.lon, a.n, a.radio, solo_reales=a.solo_reales)
        if not filas:
            print('No hay nodos de la red dentro de %.0f m' % a.radio)
        for f in filas:
            print('%7.0f m  %-45s %-9s %-16s clientes=%-3d enlaces=%-3d %s' % (
                f['distancia_m'], f['nombre'][:45], f['tipo'], f['fuente_coord'], f['clientes'], f['enlaces'],
                f['notas'] or ''))
    elif a.cmd == 'resumen':
        if _es_pg(a.db):
            raise SystemExit('El resumen usa el archivo SQLite; en PostgreSQL consulte la vista red_fibra.v_ultima_importacion')
        resumen(a.db)
    else:
        exportar_geojson(a.db, a.salida)
