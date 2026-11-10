"""Pasa las carpetas de «Mis lugares» (con todo lo que tienen: marcas, rutas de los presupuestos, polígonos, cables…) de un usuario a otro.

Mis lugares es personal: cada carpeta es de un usuario. Si alguien cambia de usuario (por ejemplo del usuario de Windows del servicio local a su clave del visor en la VM),
lo que hizo con el usuario anterior no aparece con el nuevo; no se pierde, sigue en la base. Este script lo cambia de dueño.

    python herramientas/transferir_lugares.py --de jparamo --a jan             simula: muestra cuántas carpetas y elementos pasarían
    python herramientas/transferir_lugares.py --de jparamo --a jan --aplicar   lo hace

`--de` y `--a` son el nombre, la persona del visor o el usuario de Windows del usuario. Pasan las carpetas (con sus subcarpetas) que no estén eliminadas; lo que el destino ya
tenía se queda como está (los dos conjuntos quedan juntos). Se puede deshacer pasándolas de vuelta (--de jan --a jparamo, que movería TODO lo del destino: mejor usar la vista Mis lugares
para mover una carpeta suelta).

En la VM (dentro del contenedor):
    docker compose --profile db exec app python herramientas/transferir_lugares.py --de jparamo --a jan
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def resolver(con, texto):
    """The user whose name, visor person or Windows user is `texto` (exactly one), or SystemExit."""
    filas = con.execute("SELECT * FROM redes.usuarios WHERE lower(nombre) = lower(%s) OR lower(persona_visor) = lower(%s) OR lower(usuario_windows) = lower(%s)",
                        (texto, texto, texto)).fetchall()
    if not filas:
        raise SystemExit(f"No hay ningún usuario «{texto}» (nombre, persona del visor o usuario de Windows)")
    if len(filas) > 1:
        raise SystemExit(f"«{texto}» coincide con varios usuarios: " + ", ".join(f"{f['nombre']} (id {f['id']})" for f in filas))
    return filas[0]


def contar(con, usuario_id):
    """(folders, elements) of a user that are not deleted."""
    c = con.execute("SELECT count(*) AS n FROM redes.lugares_carpetas WHERE usuario_id = %s AND borrado_en IS NULL", (usuario_id,)).fetchone()["n"]
    e = con.execute("SELECT count(*) AS n FROM redes.lugares_elementos e JOIN redes.lugares_carpetas c ON c.id = e.carpeta_id "
                    "WHERE c.usuario_id = %s AND c.borrado_en IS NULL AND e.borrado_en IS NULL", (usuario_id,)).fetchone()["n"]
    return c, e


def transferir(con, origen, destino):
    """Moves the folders of `origen` to `destino` (one transaction, with its history). Returns (folders, elements) moved."""
    from visor_rutas.redes import repositorio
    if origen["id"] == destino["id"]:
        raise SystemExit("El origen y el destino son el mismo usuario")
    antes = contar(con, origen["id"])
    with con.transaction():
        ids = [f["id"] for f in con.execute(
            "UPDATE redes.lugares_carpetas SET usuario_id = %s, actualizado_en = now(), actualizado_por = %s, version = version + 1 "
            "WHERE usuario_id = %s AND borrado_en IS NULL RETURNING id", (destino["id"], destino["id"], origen["id"])).fetchall()]
        for i in ids:
            repositorio.registrar(con, destino["id"], "lugar_carpeta", i, "editar", {"dueno": [origen["nombre"], destino["nombre"]]})
    return antes


def main():
    ap = argparse.ArgumentParser(description="Pasa las carpetas de Mis lugares de un usuario a otro")
    ap.add_argument("--de", required=True, help="usuario actual de las carpetas")
    ap.add_argument("--a", required=True, help="usuario que las recibe")
    ap.add_argument("--aplicar", action="store_true", help="lo hace (sin esto solo muestra qué pasaría)")
    args = ap.parse_args()
    from visor_rutas.redes import db
    con = db.conectar()
    origen, destino = resolver(con, args.de), resolver(con, args.a)
    c, e = contar(con, origen["id"])
    dc, de = contar(con, destino["id"])
    print(f"De:   {origen['nombre']} (id {origen['id']}): {c} carpetas, {e} elementos")
    print(f"A:    {destino['nombre']} (id {destino['id']}): {dc} carpetas, {de} elementos (se quedan como están)")
    if not args.aplicar:
        print("\nSimulación: no se cambió nada. Para hacerlo:  --aplicar")
        return
    movidas = transferir(con, origen, destino)
    print(f"\nListo: {movidas[0]} carpetas con {movidas[1]} elementos ahora son de {destino['nombre']}. Cierre y vuelva a abrir el visor para verlas.")


if __name__ == "__main__":
    main()
