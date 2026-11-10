"""Deja los usuarios del módulo de redes con los roles de la estructura nueva (idempotente: se puede repetir).

    jan      super_administrador   todo, y es el único que gestiona a los administradores
    marlon   administrador
    javier   administrador
    guest    guest                 mapa, rutas y presupuestos; nada más
    prueba   prueba                solo lectura en todo (para probar los endpoints)

Cada uno se identifica con su clave del visor (VISOR_API_KEYS=nombre:clave): el «nombre» de la clave es la persona del visor. Si ya existe un usuario con esa persona
se le cambia el rol; si no, se crea. Los demás usuarios (de prueba: jparamo, janPlanificacion, jgutierrez…) se desactivan con --desactivar-otros (borrado lógico: se
pueden reactivar desde la vista Usuarios).

Sin --aplicar solo muestra lo que haría y no cambia nada.

En la VM (dentro del contenedor, con la base de la VM):
    docker compose --profile db exec app python herramientas/configurar_usuarios.py                    simula
    docker compose --profile db exec app python herramientas/configurar_usuarios.py --aplicar --desactivar-otros
En la PC de desarrollo:  .venv\\Scripts\\python.exe herramientas\\configurar_usuarios.py
"""
import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

OBJETIVO = [("jan", "super_administrador"), ("marlon", "administrador"), ("javier", "administrador"), ("guest", "guest"), ("prueba", "prueba")]


def _usuario_por_persona(con, persona):
    return con.execute("SELECT * FROM redes.usuarios WHERE lower(persona_visor) = lower(%s)", (persona,)).fetchone()


def construir_plan(con, objetivo=OBJETIVO, desactivar_otros=False):
    """[(accion, persona/nombre, detalle)] of what has to change; nothing is written."""
    plan, personas = [], {p.lower() for p, _ in objetivo}
    for persona, rol in objetivo:
        fila = _usuario_por_persona(con, persona)
        if fila is None:
            plan.append(("crear", persona, {"rol": rol}))
        elif fila["rol"] != rol or fila["borrado_en"] is not None:
            plan.append(("cambiar", persona, {"id": fila["id"], "antes": fila["rol"], "rol": rol, "reactivar": fila["borrado_en"] is not None}))
        else:
            plan.append(("igual", persona, {"id": fila["id"], "rol": rol}))
    if desactivar_otros:
        for f in con.execute("SELECT * FROM redes.usuarios WHERE borrado_en IS NULL ORDER BY id").fetchall():
            if (f["persona_visor"] or "").lower() not in personas:
                plan.append(("desactivar", f["nombre"], {"id": f["id"], "rol": f["rol"]}))
    return plan


def aplicar(con, plan):
    """Writes the plan in one transaction, with the history of each change (the first super administrator is the one who signs the rest)."""
    from visor_rutas.redes import repositorio
    with con.transaction():
        actor = None
        for accion, persona, d in plan:                           # the super administrator first: he signs the rest
            if d.get("rol") == "super_administrador" and accion in ("crear", "cambiar", "igual"):
                actor = _poner(con, accion, persona, d, None)
        for accion, persona, d in plan:
            if d.get("rol") == "super_administrador" and accion in ("crear", "cambiar", "igual"):
                continue
            if accion in ("crear", "cambiar"):
                _poner(con, accion, persona, d, actor)
            elif accion == "desactivar":
                if actor is None:
                    raise SystemExit("Sin super administrador no se desactiva a nadie")
                fila = repositorio.obtener(con, "usuarios", d["id"], bloquear=True)
                repositorio.actualizar(con, "usuarios", d["id"], fila["version"], {"borrado_en": con.execute("SELECT now() AS n").fetchone()["n"]}, actor["id"])
                repositorio.registrar(con, actor["id"], "usuario", d["id"], "eliminar", {"motivo": [None, "reestructuracion de roles"]})
        if con.execute("SELECT count(*) AS n FROM redes.usuarios WHERE rol = 'super_administrador' AND borrado_en IS NULL").fetchone()["n"] < 1:
            raise SystemExit("Debe quedar un super administrador activo: no se aplicó nada")


def _poner(con, accion, persona, d, actor):
    from visor_rutas.redes import repositorio
    if accion == "crear":
        fila = repositorio.insertar(con, "usuarios", {"nombre": persona, "persona_visor": persona, "rol": d["rol"]}, actor["id"] if actor else None)
        repositorio.registrar(con, (actor or fila)["id"], "usuario", fila["id"], "crear", repositorio.diferencias(None, fila))
        return fila
    fila = repositorio.obtener(con, "usuarios", d["id"], bloquear=True)
    if accion == "igual":
        return fila
    valores = {"rol": d["rol"], **({"borrado_en": None} if d.get("reactivar") else {})}
    antes, nueva = repositorio.actualizar(con, "usuarios", d["id"], fila["version"], valores, (actor or fila)["id"])
    repositorio.registrar(con, (actor or nueva)["id"], "usuario", d["id"], "editar", repositorio.diferencias(antes, nueva))
    return nueva


def claves_que_faltan(objetivo=OBJETIVO):
    """People of the target that have no key in VISOR_API_KEYS of the .env (the key's name is the person)."""
    import config  # noqa: F401  (loads the .env)
    nombres = {e.split(":")[0].strip().lower() for e in os.getenv("VISOR_API_KEYS", "").split(",") if ":" in e}
    return [p for p, _ in objetivo if p.lower() not in nombres]


def main():
    ap = argparse.ArgumentParser(description="Roles de los usuarios de redes")
    ap.add_argument("--aplicar", action="store_true", help="escribe los cambios (sin esto solo muestra el plan)")
    ap.add_argument("--desactivar-otros", action="store_true", help="desactiva a los usuarios que no están en la lista (borrado lógico)")
    args = ap.parse_args()
    from visor_rutas.redes import db
    con = db.conectar()
    plan = construir_plan(con, desactivar_otros=args.desactivar_otros)
    for accion, persona, d in plan:
        if accion == "crear":
            print(f"CREAR      {persona}  -> {d['rol']}")
        elif accion == "igual":
            print(f"igual      {persona}  ya es {d['rol']}")
        elif accion == "cambiar":
            print(f"CAMBIAR    {persona}  {d['antes']} -> {d['rol']}{' (y se reactiva)' if d.get('reactivar') else ''}")
        else:
            print(f"DESACTIVAR {persona}  (era {d['rol']})")
    faltan = claves_que_faltan()
    if faltan:
        print(f"\nAviso: VISOR_API_KEYS de este .env no tiene clave para: {', '.join(faltan)} (sin clave no pueden entrar).")
    if not args.aplicar:
        print("\nSimulación: no se cambió nada. Para aplicar:  --aplicar" + ("" if args.desactivar_otros else " [--desactivar-otros]"))
        return
    aplicar(con, plan)
    print("\nListo: roles aplicados.")


if __name__ == "__main__":
    main()
