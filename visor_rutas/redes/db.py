"""Conexión a la base del módulo de redes (esquema `redes` en VISIO_DB_*) y errores para el usuario.

Conexión de lectura y escritura propia del módulo (la de red_fibra_pg es de solo lectura y no se
toca). autocommit=True: cada escritura va dentro de `with con.transaction():`.
"""
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


class ErrorRedes(Exception):
    """Mensaje claro para el usuario (se muestra tal cual en el visor)."""


class RedesNoDisponible(ErrorRedes):
    """Base de redes no configurada o sin conexión."""


class SinPermiso(ErrorRedes):
    """El usuario no tiene permiso para esa operación."""


class NoEncontrado(ErrorRedes):
    """El registro no existe (o fue borrado)."""


class ConflictoVersion(ErrorRedes):
    """Otro usuario guardó cambios antes (bloqueo optimista)."""

    def __init__(self, mensaje: str = "Otro usuario guardó cambios en este registro mientras usted lo editaba. "
                                      "Recargue para ver la versión actual."):
        super().__init__(mensaje)


class DatosInvalidos(ErrorRedes):
    """Campos no válidos: {campo: mensaje}."""

    def __init__(self, errores: dict[str, str]):
        super().__init__("Revise los datos marcados: " + "; ".join(f"{k}: {v}" for k, v in errores.items()))
        self.errores = errores


def parametros() -> dict[str, Any]:
    """VISIO_DB_* de la configuración (el mismo servidor y base que la red Visio)."""
    from config import get_settings
    s = get_settings()
    return {"host": s.visio_db_host, "port": s.visio_db_port, "dbname": s.visio_db_name,
            "user": s.visio_db_user, "password": s.visio_db_password}


def parametros_env(archivo: Path | None = None) -> dict[str, Any]:
    """VISIO_DB_* leídos directo del .env (pruebas: no dependen de get_settings())."""
    from dotenv import dotenv_values
    valores = {**dotenv_values(archivo or Path(__file__).resolve().parents[2] / ".env"), **{
        k: v for k, v in os.environ.items() if k.startswith("VISIO_DB_") and v}}
    return {"host": valores.get("VISIO_DB_HOST") or "localhost", "port": int(valores.get("VISIO_DB_PORT") or 5432),
            "dbname": valores.get("VISIO_DB_NAME") or "", "user": valores.get("VISIO_DB_USER") or "",
            "password": valores.get("VISIO_DB_PASSWORD") or ""}


def conectar(dbname: str | None = None, params: dict[str, Any] | None = None) -> psycopg.Connection:
    """Conexión con filas como dict, search_path=redes,public (PostGIS está en public)."""
    p = dict(params or parametros())
    if dbname:
        p["dbname"] = dbname
    if not p.get("dbname"):
        raise RedesNoDisponible("El módulo de redes necesita la base Presupuesto_visio (VISIO_DB_NAME vacío en el .env)")
    try:
        con = psycopg.connect(**p, connect_timeout=5, row_factory=dict_row,
                              options="-c statement_timeout=30000 -c search_path=redes,public")
    except psycopg.Error as exc:
        raise RedesNoDisponible(f"No se pudo conectar con la base de redes ({p['dbname']}): "
                                f"{str(exc).strip().splitlines()[0][:160]}") from None
    con.autocommit = True
    return con
