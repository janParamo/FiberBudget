"""Vista previa de los tickets de Kayako que llegarían a planificación. SOLO LEE: no crea ni cambia nada, ni en Kayako ni aquí.

Pone en el .env los datos de la conexión (la base de Kayako, MySQL):
    KAYAKO_DB_HOST=...   KAYAKO_DB_PORT=3306   KAYAKO_DB_NAME=kayako_fusion   KAYAKO_DB_USER=...   KAYAKO_DB_PASSWORD=...
y corre:
    .\\.venv\\Scripts\\python.exe herramientas\\kayako_vista_previa.py                 # los de los últimos 30 días (business_rules.yaml, kayako.dias_atras)
    .\\.venv\\Scripts\\python.exe herramientas\\kayako_vista_previa.py --dias 7 --limite 20
    .\\.venv\\Scripts\\python.exe herramientas\\kayako_vista_previa.py --ticket UHM-782-84959   # un ticket, con su comentario completo
    .\\.venv\\Scripts\\python.exe herramientas\\kayako_vista_previa.py --probar          # solo prueba la conexión y cuenta las tablas
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from visor_rutas import kayako  # noqa: E402


def probar() -> int:
    if not kayako.configurada():
        print("Falta la conexión de Kayako en el .env (KAYAKO_DB_HOST, KAYAKO_DB_USER, KAYAKO_DB_PASSWORD).")
        return 2
    con = kayako.conectar()
    try:
        with con.cursor() as cur:
            cur.execute("SELECT VERSION() AS version")
            version = cur.fetchone()["version"]
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()")
            tablas = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM swtickets")
            tickets = cur.fetchone()["n"]
    finally:
        con.close()
    print(f"Conectado (solo lectura). MySQL {version}; {tablas} tablas; {tickets} tickets en total.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=float, default=None, help="días de actividad hacia atrás (por defecto kayako.dias_atras)")
    ap.add_argument("--limite", type=int, default=50)
    ap.add_argument("--ticket", help="mostrar completo un ticket (su número, como UHM-782-84959)")
    ap.add_argument("--probar", action="store_true", help="solo probar la conexión")
    a = ap.parse_args()
    if a.probar:
        return probar()
    if not kayako.configurada():
        print("Falta la conexión de Kayako en el .env (KAYAKO_DB_HOST, KAYAKO_DB_USER, KAYAKO_DB_PASSWORD).")
        return 2
    lista = kayako.vista_previa(3650 if a.ticket else a.dias, 5000 if a.ticket else a.limite)
    if a.ticket:
        lista = [t for t in lista if t["ticket"].casefold() == a.ticket.casefold()]
        if not lista:
            print(f"No está entre los tickets de los filtros (departamento / tipo / estados): {a.ticket}")
            return 1
        t = lista[0]
        for k in ("ticket", "cliente", "ejecutivo", "departamento", "tipo", "estado", "owner", "creado", "ultima_actividad", "campos", "coordenadas"):
            print(f"{k:>17}: {t[k]}")
        print("\n--- primer comentario ---\n" + t["comentario"])
        if t["ultimo_comentario"]:
            print("\n--- último comentario ---\n" + t["ultimo_comentario"])
        return 0
    print(f"{len(lista)} ticket(s)\n")
    print(f"{'Ticket':<16}{'Cliente':<28}{'Ejecutivo':<22}{'Estado':<11}{'Últ. actividad':<20}{'Código':<9}{'Contacto':<20}{'Teléfono':<12}Coord.")
    for t in lista:
        c = t["campos"]
        print(f"{t['ticket'][:15]:<16}{t['cliente'][:27]:<28}{t['ejecutivo'][:21]:<22}{str(t['estado'])[:10]:<11}{str(t['ultima_actividad'] or '')[:19]:<20}"
              f"{c.get('client_code', '')[:8]:<9}{c.get('contact_name', '')[:19]:<20}{c.get('contact_phone', '')[:11]:<12}{len(t['coordenadas'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
