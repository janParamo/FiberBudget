"""Migraciones versionadas del esquema `redes`: migraciones/NNN_nombre.sql, en orden.

Se aplican solas la primera vez que el visor (o la API /visor/redes/*) usa la base, solo las que
faltan, cada una en su transacción. Un advisory lock de PostgreSQL evita que dos procesos las
apliquen a la vez. Una migración ya aplicada nunca se vuelve a correr; si su archivo cambió
después, solo se avisa en el log (los cambios van en una migración nueva).

Una migración que cambia datos o restricciones existentes lleva en sus primeras líneas el comentario
`-- respaldo: previo`: antes de aplicarla se crea un respaldo completo (redes/respaldo.py: .json de
todos los proyectos + .sql con pg_dump), si la base ya tiene proyectos. Si el respaldo falla, la
migración no se aplica.

    .\\.venv\\Scripts\\python.exe -m visor_rutas.redes.migrar      # aplicarlas a mano y ver el estado
"""
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CARPETA = Path(__file__).resolve().parent / "migraciones"
_NOMBRE = re.compile(r"^(\d{3})_([\w-]+)\.sql$")
LLAVE_BLOQUEO = 731_052_401          # pg_advisory_lock: one migrator at a time


@dataclass(frozen=True)
class Migracion:
    version: int
    nombre: str
    sql: str
    checksum: str


def disponibles(carpeta: Path | None = None) -> list[Migracion]:
    migraciones = []
    for archivo in sorted((carpeta or CARPETA).glob("*.sql")):
        m = _NOMBRE.match(archivo.name)
        if not m:
            log.warning("Redes: migration file ignored (name must be NNN_name.sql): %s", archivo.name)
            continue
        sql = archivo.read_text(encoding="utf-8")
        migraciones.append(Migracion(int(m.group(1)), m.group(2), sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()))
    versiones = [m.version for m in migraciones]
    if len(versiones) != len(set(versiones)):
        raise RuntimeError("Hay dos migraciones de redes con el mismo número")
    return migraciones


def aplicadas(con: Any) -> dict[int, dict[str, Any]]:
    existe = con.execute("SELECT to_regclass('redes.migraciones') IS NOT NULL AS hay").fetchone()["hay"]
    if not existe:
        return {}
    return {f["version"]: f for f in con.execute(
        "SELECT version, nombre, checksum, aplicada_en FROM redes.migraciones ORDER BY version").fetchall()}


def pide_respaldo(m: Migracion) -> bool:
    """`-- respaldo: previo` among the first comment lines of the file."""
    cabecera = "\n".join(m.sql.splitlines()[:15]).lower()
    return "-- respaldo: previo" in cabecera


def respaldo_previo(con: Any, m: Migracion) -> str | None:
    """Full backup before a marked migration (only when there are projects); raises if it fails."""
    hay = con.execute("SELECT to_regclass('redes.proyectos') IS NOT NULL AS t").fetchone()["t"] and \
        con.execute("SELECT count(*) AS n FROM redes.proyectos WHERE borrado_en IS NULL").fetchone()["n"] > 0
    if not hay:
        return None
    from visor_rutas.redes import respaldo
    archivo, aviso = respaldo.respaldar(con, "migración automática", None, motivo=f"antes de la migración {m.version:03d}_{m.nombre}")
    log.info("Redes: backup %s before migration %03d_%s%s", archivo, m.version, m.nombre, f" ({aviso})" if aviso else "")
    return archivo


def aplicar(con: Any, carpeta: Path | None = None) -> list[int]:
    """Applies the missing migrations; returns their versions."""
    nuevas: list[int] = []
    con.execute("SELECT pg_advisory_lock(%s)", (LLAVE_BLOQUEO,))
    try:
        with con.transaction():
            con.execute("CREATE SCHEMA IF NOT EXISTS redes")
            con.execute("""CREATE TABLE IF NOT EXISTS redes.migraciones (
                               version     integer PRIMARY KEY,
                               nombre      text NOT NULL,
                               checksum    text NOT NULL,
                               aplicada_en timestamptz NOT NULL DEFAULT now())""")
        hechas = aplicadas(con)
        for m in disponibles(carpeta):
            if m.version in hechas:
                if hechas[m.version]["checksum"] != m.checksum:
                    log.warning("Redes: migration %03d_%s changed after being applied (not re-run)", m.version, m.nombre)
                continue
            if pide_respaldo(m):
                respaldo_previo(con, m)
            with con.transaction():
                con.execute(m.sql)
                con.execute("INSERT INTO redes.migraciones (version, nombre, checksum) VALUES (%s, %s, %s)",
                            (m.version, m.nombre, m.checksum))
            log.info("Redes: migration %03d_%s applied", m.version, m.nombre)
            nuevas.append(m.version)
    finally:
        con.execute("SELECT pg_advisory_unlock(%s)", (LLAVE_BLOQUEO,))
    return nuevas


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from visor_rutas.redes import db
    con = db.conectar()
    try:
        nuevas = aplicar(con)
        print("Aplicadas ahora:", ", ".join(f"{v:03d}" for v in nuevas) or "ninguna (ya estaba al día)")
        for v, f in aplicadas(con).items():
            print(f"  {v:03d}_{f['nombre']}  {f['aplicada_en']:%Y-%m-%d %H:%M}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
