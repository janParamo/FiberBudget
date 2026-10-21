"""Splitters leídos de los diagramas y lo que las personas confirman de ellos (migración 016, visor_rutas/splitters_diagrama.py).

`registrar` guarda lo que se leyó cada vez que se genera una ruta (sin tocar lo confirmado). `de_diagrama` los lista y `confirmar` guarda la
clase y el estado de los puertos que una persona vio en el diagrama; lo confirmado gana sobre lo automático y queda como verdad de referencia.
"""
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import usuarios
from visor_rutas.redes.db import ConflictoVersion, DatosInvalidos, NoEncontrado, SinPermiso

MAX_PUERTOS = 64
_CAMPOS = "id, md5, clave, etiqueta, x_cm, y_cm, auto, confirmado, confirmado_en, version"


def registrar(con: Any, splitters: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Upserts what was read ({md5, clave, etiqueta, x_cm, y_cm, …}) and returns {(md5, clave): {id, version, confirmado}}."""
    salida: dict[tuple[str, str], dict[str, Any]] = {}
    with con.transaction():
        for s in splitters:
            auto = {k: s[k] for k in ("clase", "clase_fuente", "ratio", "puertos", "fuente_puertos") if k in s}
            fila = con.execute(
                "INSERT INTO redes.splitters_diagrama (md5, clave, etiqueta, x_cm, y_cm, auto) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (md5, clave) DO UPDATE SET etiqueta = EXCLUDED.etiqueta, x_cm = EXCLUDED.x_cm, y_cm = EXCLUDED.y_cm, auto = EXCLUDED.auto, "
                "veces_visto = redes.splitters_diagrama.veces_visto + 1, visto_en = now() RETURNING id, version, confirmado",
                (s["md5"], s["clave"], s.get("etiqueta") or "", s.get("x_cm"), s.get("y_cm"), Jsonb(auto))).fetchone()
            salida[(s["md5"], s["clave"])] = {"id": fila["id"], "version": fila["version"], "confirmado": fila["confirmado"]}
    return salida


def de_diagrama(con: Any, actor: dict[str, Any], md5: str) -> dict[str, Any]:
    """Splitters stored for a diagram (anyone can read them)."""
    filas = con.execute(f"SELECT {_CAMPOS} FROM redes.splitters_diagrama WHERE md5 = %s AND borrado_en IS NULL ORDER BY id", (str(md5),)).fetchall()
    return {"splitters": [{"id": f["id"], "md5": f["md5"], "clave": f["clave"], "etiqueta": f["etiqueta"], "auto": f["auto"],
                           "confirmado": f["confirmado"], "version": f["version"]} for f in filas]}


def _limpiar(clase: Any, puertos: Any) -> dict[str, Any]:
    confirmado: dict[str, Any] = {}
    if clase not in (None, ""):
        if clase not in ("secundario", "principal"):
            raise DatosInvalidos({"clase": "Debe ser secundario o principal"})
        confirmado["clase"] = clase
    if puertos is not None:
        if not isinstance(puertos, dict) or len(puertos) > MAX_PUERTOS:
            raise DatosInvalidos({"puertos": "Puertos no válidos"})
        limpios = {}
        for n, estado in puertos.items():
            if not str(n).isdigit() or not 1 <= int(n) <= MAX_PUERTOS or estado not in ("libre", "ocupado"):
                raise DatosInvalidos({"puertos": f"Puerto {n}: debe ser libre u ocupado"})
            limpios[str(int(n))] = estado
        confirmado["puertos"] = limpios
    if not confirmado:
        raise DatosInvalidos({"puertos": "No hay nada que confirmar"})
    return confirmado


def confirmar(con: Any, actor: dict[str, Any], id: int, version: int, clase: str | None = None,
              puertos: dict[str, str] | None = None) -> dict[str, Any]:
    """Saves what the person saw in the diagram (class and/or the state of the ports). Only administrators and editors."""
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede confirmar los splitters")
    confirmado = _limpiar(clase, puertos)
    with con.transaction():
        fila = con.execute("SELECT confirmado, version FROM redes.splitters_diagrama WHERE id = %s FOR UPDATE", (int(id),)).fetchone()
        if fila is None:
            raise NoEncontrado("El splitter ya no existe")
        if fila["version"] != int(version):
            raise ConflictoVersion()
        previo = fila["confirmado"] or {}
        unido = {**previo, **confirmado, "puertos": {**(previo.get("puertos") or {}), **(confirmado.get("puertos") or {})}}
        if not unido["puertos"]:
            unido.pop("puertos")
        actual = con.execute("UPDATE redes.splitters_diagrama SET confirmado = %s, confirmado_por = %s, confirmado_en = now(), version = version + 1 "
                             "WHERE id = %s RETURNING version", (Jsonb(unido), actor.get("id"), int(id))).fetchone()
    return {"id": int(id), "version": actual["version"], "confirmado": unido}


def quitar_confirmacion(con: Any, actor: dict[str, Any], id: int, version: int) -> dict[str, Any]:
    """Back to the automatic reading."""
    if not usuarios.puede_editar(actor):
        raise SinPermiso("Solo un administrador o un editor puede confirmar los splitters")
    with con.transaction():
        fila = con.execute("SELECT version FROM redes.splitters_diagrama WHERE id = %s FOR UPDATE", (int(id),)).fetchone()
        if fila is None:
            raise NoEncontrado("El splitter ya no existe")
        if fila["version"] != int(version):
            raise ConflictoVersion()
        actual = con.execute("UPDATE redes.splitters_diagrama SET confirmado = NULL, confirmado_por = NULL, confirmado_en = NULL, version = version + 1 "
                             "WHERE id = %s RETURNING version", (int(id),)).fetchone()
    return {"id": int(id), "version": actual["version"], "confirmado": None}

