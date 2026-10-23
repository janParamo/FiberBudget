"""Archivos en PostgreSQL (tabla redes.almacen_archivos): la base es la fuente de verdad; las carpetas del proyecto son una copia local.

Un archivo se identifica por (espacio, clave). Los espacios son los de la migración 019: `visor`, `odg`, `diagramas`, `kmz`, `datos_kmz`.
Cada función abre su propia conexión corta (la misma base y usuario del módulo de redes) y **nunca lanza**: si la base no está configurada o no
responde, devuelve False / None / [] y lo anota en el log, así que el programa sigue con los archivos locales como antes.

Quien necesita un archivo con ruta (LibreOffice, openpyxl, el navegador) pide `restaurar()`: si la copia local falta, se escribe desde la base.
Quien produce un archivo lo manda con `guardar_archivo()` y después puede borrar la copia local sin perder nada.
"""
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

ESPACIOS = ("visor", "odg", "diagramas", "kmz", "datos_kmz")
ACTIVO = True            # las pruebas lo apagan (conftest) para no escribir en la base real
_TROZO = 50              # archivos por consulta al restaurar o subir carpetas enteras


def _abrir() -> Any:
    from visor_rutas.redes import db
    return db.conectar()


def habilitado() -> bool:
    """True when the store is switched on and the redes database is configured (no connection is made)."""
    if not ACTIVO:
        return False
    try:
        from visor_rutas.redes import db
        return bool(db.parametros().get("dbname"))
    except Exception:                                                # noqa: BLE001 - no settings: no store
        return False


def _conexion(con: Any = None) -> tuple[Any, bool]:
    """(connection, ours): a given connection is used and left open; otherwise a new one is opened (and must be closed)."""
    if con is not None:
        return con, False
    if not habilitado():
        return None, False
    try:
        return _abrir(), True
    except Exception as exc:                                         # noqa: BLE001 - unreachable / not configured
        log.info("Almacén de archivos no disponible (%s)", type(exc).__name__)
        return None, False


def _seguro(espacio: str) -> str:
    if espacio not in ESPACIOS:
        raise ValueError(f"Espacio de almacén desconocido: {espacio}")
    return espacio


def clave_segura(clave: str) -> str:
    """A key is a relative path with forward slashes: no drive, no '..', no empty parts."""
    partes = [p for p in str(clave).replace("\\", "/").split("/") if p not in ("", ".")]
    if not partes or any(p == ".." or ":" in p for p in partes):
        raise ValueError(f"Clave de almacén no válida: {clave!r}")
    return "/".join(partes)


def guardar(espacio: str, clave: str, datos: bytes, con: Any = None) -> bool:
    """Stores (or replaces) one file. False when the database is not available."""
    espacio, clave = _seguro(espacio), clave_segura(clave)
    conexion, propia = _conexion(con)
    if conexion is None:
        return False
    try:
        conexion.execute(
            "INSERT INTO redes.almacen_archivos (espacio, clave, contenido, tamano, md5) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (espacio, clave) DO UPDATE SET contenido = EXCLUDED.contenido, tamano = EXCLUDED.tamano, md5 = EXCLUDED.md5, "
            "modificado_en = now()",
            (espacio, clave, datos, len(datos), hashlib.md5(datos).hexdigest()))
        return True
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se guardó %s/%s (%s): %s", espacio, clave, type(exc).__name__, str(exc).strip()[:160])
        return False
    finally:
        if propia:
            conexion.close()


def guardar_archivo(espacio: str, clave: str, ruta: Path | str, con: Any = None) -> bool:
    try:
        datos = Path(ruta).read_bytes()
    except OSError as exc:
        log.warning("Almacén: no se pudo leer %s (%s)", ruta, type(exc).__name__)
        return False
    return guardar(espacio, clave, datos, con)


def leer(espacio: str, clave: str, con: Any = None) -> bytes | None:
    espacio, clave = _seguro(espacio), clave_segura(clave)
    conexion, propia = _conexion(con)
    if conexion is None:
        return None
    try:
        fila = conexion.execute("SELECT contenido FROM redes.almacen_archivos WHERE espacio = %s AND clave = %s", (espacio, clave)).fetchone()
        return bytes(fila["contenido"]) if fila else None
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se leyó %s/%s (%s)", espacio, clave, type(exc).__name__)
        return None
    finally:
        if propia:
            conexion.close()


def info(espacio: str, clave: str, con: Any = None) -> dict[str, Any] | None:
    """{clave, tamano, md5, creado_en, modificado_en} without the content, or None."""
    espacio, clave = _seguro(espacio), clave_segura(clave)
    conexion, propia = _conexion(con)
    if conexion is None:
        return None
    try:
        return conexion.execute("SELECT clave, tamano, md5, creado_en, modificado_en FROM redes.almacen_archivos "
                                "WHERE espacio = %s AND clave = %s", (espacio, clave)).fetchone()
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se consultó %s/%s (%s)", espacio, clave, type(exc).__name__)
        return None
    finally:
        if propia:
            conexion.close()


def existe(espacio: str, clave: str, con: Any = None) -> bool:
    return info(espacio, clave, con) is not None


def listar(espacio: str, prefijo: str = "", con: Any = None) -> list[dict[str, Any]]:
    """The files of a space (newest first) whose key starts with `prefijo`; {clave, tamano, md5, creado_en, modificado_en}."""
    espacio = _seguro(espacio)
    conexion, propia = _conexion(con)
    if conexion is None:
        return []
    try:
        patron = prefijo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return conexion.execute("SELECT clave, tamano, md5, creado_en, modificado_en FROM redes.almacen_archivos "
                                "WHERE espacio = %s AND clave LIKE %s ORDER BY creado_en DESC, clave", (espacio, patron)).fetchall()
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se listó %s (%s)", espacio, type(exc).__name__)
        return []
    finally:
        if propia:
            conexion.close()


def borrar(espacio: str, clave: str, con: Any = None) -> bool:
    espacio, clave = _seguro(espacio), clave_segura(clave)
    conexion, propia = _conexion(con)
    if conexion is None:
        return False
    try:
        conexion.execute("DELETE FROM redes.almacen_archivos WHERE espacio = %s AND clave = %s", (espacio, clave))
        return True
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se borró %s/%s (%s)", espacio, clave, type(exc).__name__)
        return False
    finally:
        if propia:
            conexion.close()


def borrar_viejos(espacio: str, dias: float, prefijo: str = "", con: Any = None) -> int:
    """Deletes the files of a space created more than `dias` ago; returns how many."""
    espacio = _seguro(espacio)
    conexion, propia = _conexion(con)
    if conexion is None:
        return 0
    try:
        patron = prefijo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return conexion.execute("DELETE FROM redes.almacen_archivos WHERE espacio = %s AND clave LIKE %s "
                                "AND creado_en < now() - make_interval(secs => %s)", (espacio, patron, float(dias) * 86400)).rowcount
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se limpió %s (%s)", espacio, type(exc).__name__)
        return 0
    finally:
        if propia:
            conexion.close()


def _escribir(destino: Path, datos: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=destino.parent, prefix=destino.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        os.replace(temporal, destino)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def restaurar(espacio: str, clave: str, destino: Path | str, con: Any = None) -> bool:
    """Writes the stored file to `destino` if it is not there yet. True when `destino` exists afterwards."""
    destino = Path(destino)
    if destino.is_file():
        return True
    datos = leer(espacio, clave, con)
    if datos is None:
        return False
    try:
        _escribir(destino, datos)
    except OSError as exc:
        log.warning("Almacén: no se pudo escribir %s (%s)", destino, type(exc).__name__)
        return False
    return True


def restaurar_espacio(espacio: str, carpeta: Path | str, prefijo: str = "", con: Any = None) -> int:
    """Writes to `carpeta` every file of the space (under `prefijo`) that is missing there, keeping the keys as relative paths. Returns how many."""
    espacio = _seguro(espacio)
    carpeta = Path(carpeta)
    conexion, propia = _conexion(con)
    if conexion is None:
        return 0
    escritos = 0
    try:
        faltan = [f["clave"] for f in listar(espacio, prefijo, conexion) if not (carpeta / f["clave"]).is_file()]
        for i in range(0, len(faltan), _TROZO):
            lote = faltan[i:i + _TROZO]
            for fila in conexion.execute("SELECT clave, contenido FROM redes.almacen_archivos WHERE espacio = %s AND clave = ANY(%s)", (espacio, lote)):
                try:
                    _escribir(carpeta / fila["clave"], bytes(fila["contenido"]))
                    escritos += 1
                except OSError as exc:
                    log.warning("Almacén: no se pudo escribir %s (%s)", fila["clave"], type(exc).__name__)
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se restauró %s (%s)", espacio, type(exc).__name__)
    finally:
        if propia:
            conexion.close()
    return escritos


def subir_carpeta(espacio: str, carpeta: Path | str, patron: str = "**/*", excluir: Iterable[str] = (), borrar_sobrantes: bool = False,
                  conservar: Iterable[str] = (), con: Any = None) -> dict[str, int]:
    """Sends to the store the files of `carpeta` that are not there yet (same key and size) or that changed (other size).

    Returns {"subidos", "iguales", "fallidos", "borrados"}. `excluir`: relative paths (a file or a folder) that are not sent.
    `borrar_sobrantes`: also deletes from the store the keys that are no longer in the folder, except those under `conservar`.
    """
    espacio = _seguro(espacio)
    carpeta = Path(carpeta)
    resultado = {"subidos": 0, "iguales": 0, "fallidos": 0, "borrados": 0}
    if not carpeta.is_dir():
        return resultado
    conexion, propia = _conexion(con)
    if conexion is None:
        return resultado
    try:
        guardados = {f["clave"]: f["tamano"] for f in listar(espacio, "", conexion)}
        excluidas = {str(e).replace("\\", "/").strip("/") for e in excluir}
        for archivo in sorted(p for p in carpeta.glob(patron) if p.is_file()):
            clave = archivo.relative_to(carpeta).as_posix()
            if any(clave == e or clave.startswith(e + "/") for e in excluidas) or archivo.name.startswith("~$") or archivo.suffix == ".tmp":
                continue
            try:
                tamano = archivo.stat().st_size
            except OSError:
                resultado["fallidos"] += 1
                continue
            if guardados.get(clave) == tamano:
                resultado["iguales"] += 1
            elif guardar_archivo(espacio, clave, archivo, conexion):
                resultado["subidos"] += 1
            else:
                resultado["fallidos"] += 1
        if borrar_sobrantes:
            propias = {p.relative_to(carpeta).as_posix() for p in carpeta.glob(patron) if p.is_file()}
            resguardo = [str(c).replace("\\", "/").strip("/") for c in conservar]
            for clave in guardados:
                if clave not in propias and not any(clave == c or clave.startswith(c + "/") for c in resguardo):
                    if borrar(espacio, clave, conexion):
                        resultado["borrados"] += 1
    finally:
        if propia:
            conexion.close()
    return resultado


def resumen(con: Any = None) -> dict[str, dict[str, int]]:
    """{espacio: {archivos, bytes}} of what the store holds."""
    conexion, propia = _conexion(con)
    if conexion is None:
        return {}
    try:
        return {f["espacio"]: {"archivos": int(f["n"]), "bytes": int(f["b"])} for f in conexion.execute(
            "SELECT espacio, count(*) AS n, coalesce(sum(tamano), 0) AS b FROM redes.almacen_archivos GROUP BY espacio ORDER BY espacio").fetchall()}
    except Exception as exc:                                         # noqa: BLE001
        log.warning("Almacén: no se resumió (%s)", type(exc).__name__)
        return {}
    finally:
        if propia:
            conexion.close()
