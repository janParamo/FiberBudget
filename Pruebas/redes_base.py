"""Throw-away PostgreSQL database for the network module tests.

Each test session creates `redes_pruebas_<pid>_<random>` on the local PostgreSQL of VISIO_DB_*
(PostGIS available) and drops it at the end. It NEVER touches Presupuesto_visio: the helper
refuses any database whose name does not start with "redes_pruebas". Without PostgreSQL the
tests that need it are skipped; all the others run as usual.
"""
import os
import secrets

import psycopg
import pytest

from visor_rutas.redes import db

PREFIJO = "redes_pruebas"


def _admin(params):
    return psycopg.connect(**{**params, "dbname": "postgres"}, connect_timeout=5, autocommit=True)


@pytest.fixture(scope="session")
def base_redes():
    """(name, connection params) of a fresh, empty test database."""
    params = db.parametros_env()
    nombre = f"{PREFIJO}_{os.getpid()}_{secrets.token_hex(3)}"
    assert nombre.startswith(PREFIJO)
    try:
        admin = _admin(params)
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL no disponible para las pruebas de redes: {exc}")
    try:
        admin.execute(f'CREATE DATABASE "{nombre}"')
    except psycopg.Error as exc:
        admin.close()
        pytest.skip(f"No se pudo crear la base de prueba: {exc}")
    try:
        yield nombre, {**params, "dbname": nombre}
    finally:
        assert nombre.startswith(PREFIJO)                  # never drop anything else
        admin.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        admin.close()


@pytest.fixture
def con_redes(base_redes):
    """Connection to the test database with the schema migrated and the tables emptied."""
    from visor_rutas.redes import migrar
    _, params = base_redes
    con = db.conectar(params=params)
    migrar.aplicar(con)
    con.execute("TRUNCATE redes.historial, redes.proyecto_usuarios, redes.proyectos, redes.usuarios RESTART IDENTITY CASCADE")
    yield con
    con.close()
