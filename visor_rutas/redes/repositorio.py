"""Escrituras del módulo de redes: actualización con versión (bloqueo optimista) e historial.

Toda escritura de un servicio pasa por aquí dentro de `with con.transaction():`, así el cambio y
su registro en redes.historial se guardan juntos o no se guarda ninguno.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from visor_rutas.redes.db import ConflictoVersion, NoEncontrado

# Columns of each table that services may write (anything else is never interpolated in SQL).
COLUMNAS = {
    "usuarios": {"nombre", "correo", "rol", "persona_visor", "usuario_windows", "borrado_en"},
    "proyectos": {"codigo", "nombre", "descripcion", "padre_id", "ubicacion", "area", "imagen", "imagen_tipo",
                  "miniatura", "es_red_base", "zona", "borrado_en"},
    "elementos": {"proyecto_id", "tipo", "subtipo", "nombre", "codigo", "ubicacion", "propiedades", "ref_externa",
                  "ubicacion_fuente", "fuente", "confianza", "estado_migracion", "ref_visio", "borrado_en"},
    "cables": {"proyecto_id", "nombre", "descripcion", "clase", "tipo", "hilos", "hilos_por_buffer", "color",
               "origen_id", "destino_id", "vertices", "geom", "cruces", "longitud_m", "metraje",
               "configuracion_estimada", "tipo_fibra", "fuente", "confianza", "geom_fuente", "estado_migracion", "ref_visio",
               "borrado_en"},
    "notas": {"proyecto_id", "contexto", "mufa_id", "elemento_id", "ubicacion", "x", "y", "html", "ancho", "borrado_en"},
    "hilos": {"cable_id", "numero", "estado", "observacion", "borrado_en"},
    "splitters": {"proyecto_id", "mufa_id", "nombre", "salidas", "relacion", "conector", "x", "y", "propiedades", "fuente",
                  "confianza", "borrado_en"},
    "conectores": {"proyecto_id", "mufa_id", "nombre", "tipo", "x", "y", "borrado_en"},
    "conexiones": {"proyecto_id", "mufa_id", "a_hilo_id", "a_puerto_id", "b_hilo_id", "b_puerto_id", "bandeja",
                   "posicion_en_bandeja", "fuente", "confianza", "posicion_estimada", "borrado_en"},
    # migración de la red existente (Visio): modelo de mufa, bandejas y clientes
    "mufa_modelos": {"mufa_id", "formato", "capacidad", "empalmes_por_bandeja", "bandejas", "modelo_estimado", "fuente", "motivo", "avisos",
                     "borrado_en"},
    "mufa_bandejas": {"mufa_id", "numero", "capacidad", "splitter_id", "fuente", "borrado_en"},
    "puerto_servicios": {"puerto_id", "codigo_cliente", "nombre", "id_servicio", "elemento_id", "fuente", "confianza", "borrado_en"},
    "mufa_clientes": {"mufa_id", "codigo_cliente", "nombre", "id_servicio", "elemento_id", "fuente", "confianza", "borrado_en"},
    "diagramas_logicos": {"proyecto_id", "titulo", "elemento_id", "splitter_id", "direccion", "incluir_clientes", "borrado_en"},
    "problemas": {"proyecto_id", "elemento_id", "cable_id", "titulo", "descripcion", "severidad", "estado", "ubicacion",
                  "cerrado_en", "borrado_en"},
    "pendientes": {"proyecto_id", "elemento_id", "cable_id", "titulo", "descripcion", "responsable_id", "fecha_limite", "estado",
                   "hecho_en", "borrado_en"},
    # visor v2, fase 3: Mis lugares (lo personal de cada usuario)
    "lugares_carpetas": {"usuario_id", "padre_id", "nombre", "orden", "visible", "expandida", "borrado_en"},
    "kmz_cambios": {"clave", "carpeta", "nombre", "tipo", "accion", "antes", "despues", "publicado", "importacion_id", "borrado_en"},
    "kmz_estilos": {"clave", "alcance", "carpeta", "nombre", "estilo", "borrado_en"},
    "kmz_importaciones": {"archivo", "md5", "modo", "modo_sugerido", "estado", "conteos", "aplicada_en", "aplicada_por", "revertida_en", "publicada",
                          "publicacion", "publicada_en", "borrado_en"},
    "lugares_elementos": {"carpeta_id", "tipo", "nombre", "descripcion_html", "geom", "estilo", "vista", "propiedades", "orden", "visible",
                          "borrado_en"},
}
NO_AUDITAR = {"version", "actualizado_en", "actualizado_por", "creado_en", "creado_por"}


def _json(valor: Any) -> Any:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (bytes, memoryview)):
        return f"<{len(valor)} bytes>"
    return valor


def diferencias(antes: dict[str, Any] | None, despues: dict[str, Any] | None) -> dict[str, Any]:
    """{campo: [antes, después]} of the audited fields that changed."""
    antes, despues = antes or {}, despues or {}
    return {k: [_json(antes.get(k)), _json(despues.get(k))] for k in sorted(set(antes) | set(despues))
            if k not in NO_AUDITAR and antes.get(k) != despues.get(k)}


def registrar(con: Any, usuario_id: int | None, entidad: str, entidad_id: int | None, accion: str,
              cambio: dict[str, Any] | None = None, proyecto_id: int | None = None) -> None:
    con.execute("INSERT INTO redes.historial (usuario_id, proyecto_id, entidad, entidad_id, accion, cambio) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (usuario_id, proyecto_id, entidad, entidad_id, accion, Jsonb(cambio) if cambio is not None else None))


def obtener(con: Any, tabla: str, id_: int, *, bloquear: bool = False) -> dict[str, Any]:
    if tabla not in COLUMNAS:
        raise ValueError(tabla)
    consulta = sql.SQL("SELECT * FROM redes.{} WHERE id = %s" + (" FOR UPDATE" if bloquear else "")).format(
        sql.Identifier(tabla))
    fila = con.execute(consulta, (id_,)).fetchone()
    if fila is None:
        raise NoEncontrado("El registro ya no existe")
    return fila


def insertar(con: Any, tabla: str, valores: dict[str, Any], usuario_id: int | None) -> dict[str, Any]:
    if tabla not in COLUMNAS or not set(valores) <= COLUMNAS[tabla]:
        raise ValueError(f"Columnas no permitidas en {tabla}: {set(valores) - COLUMNAS.get(tabla, set())}")
    columnas = list(valores) + ["creado_por"]
    consulta = sql.SQL("INSERT INTO redes.{} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(tabla), sql.SQL(", ").join(map(sql.Identifier, columnas)),
        sql.SQL(", ").join(sql.Placeholder() * len(columnas)))
    return con.execute(consulta, [*valores.values(), usuario_id]).fetchone()


def actualizar(con: Any, tabla: str, id_: int, version: int, valores: dict[str, Any],
               usuario_id: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(row before, row after). ConflictoVersion if someone saved since `version` was read."""
    if tabla not in COLUMNAS or not set(valores) <= COLUMNAS[tabla]:
        raise ValueError(f"Columnas no permitidas en {tabla}: {set(valores) - COLUMNAS.get(tabla, set())}")
    antes = obtener(con, tabla, id_, bloquear=True)
    if antes["version"] != int(version):
        raise ConflictoVersion()
    asignaciones = [sql.SQL("{} = %s").format(sql.Identifier(c)) for c in valores]
    asignaciones += [sql.SQL("version = version + 1"), sql.SQL("actualizado_en = now()"),
                     sql.SQL("actualizado_por = %s")]
    consulta = sql.SQL("UPDATE redes.{} SET {} WHERE id = %s AND version = %s RETURNING *").format(
        sql.Identifier(tabla), sql.SQL(", ").join(asignaciones))
    despues = con.execute(consulta, [*valores.values(), usuario_id, id_, int(version)]).fetchone()
    if despues is None:
        raise ConflictoVersion()
    return antes, despues
