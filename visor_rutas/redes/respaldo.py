"""Backup del módulo de redes (fase 7.4) y exportación de un proyecto a KMZ / GeoJSON.

"Crear respaldo" (solo administradores) escribe en la carpeta de respaldos (REDES_RESPALDOS_DIR del
.env; si no está, respaldos_redes/ junto al proyecto), con fecha y hora en el nombre:
  - respaldo_redes_AAAA-MM-DD_HHMMSS.json: TODOS los proyectos activos con todo su contenido
    (datos e imagen, usuarios, elementos, cables, notas, hilos, lienzos de mufa, splitters,
    conectores, conexiones, diagramas, problemas con fotos y pendientes). Es lo que se restaura.
  - respaldo_redes_AAAA-MM-DD_HHMMSS.sql: además, el esquema `redes` completo con pg_dump, si
    pg_dump está en la instalación de PostgreSQL (para recuperar la base entera con psql).
"Restaurar" carga UN proyecto de un respaldo .json como copia nueva (identificador -R1, -R2…): nunca
pisa el proyecto actual.
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from visor_rutas.redes import proyectos, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso

RAIZ = Path(__file__).resolve().parents[2]
FORMATO, VERSION = "redes-respaldo", 1
_NOMBRE = re.compile(r"^respaldo_redes_\d{4}-\d{2}-\d{2}_\d{6}\.(json|sql)$")


# --------------------------------------------------------------------------- carpeta y pg_dump

def carpeta() -> Path:
    valor = os.environ.get("REDES_RESPALDOS_DIR")
    if not valor:
        try:
            from dotenv import dotenv_values
            valor = dotenv_values(RAIZ / ".env").get("REDES_RESPALDOS_DIR")
        except Exception:
            valor = None
    destino = Path(valor).expanduser() if valor else RAIZ / "respaldos_redes"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def pg_dump() -> str | None:
    """pg_dump.exe of the PostgreSQL installation (newest version first), or on the PATH."""
    explicito = os.environ.get("REDES_PG_DUMP")
    if explicito and Path(explicito).is_file():
        return explicito
    candidatos = sorted(Path(os.environ.get("ProgramFiles", r"C:\Program Files")).glob("PostgreSQL/*/bin/pg_dump.exe"),
                        key=lambda p: int(p.parts[-3]) if p.parts[-3].isdigit() else 0, reverse=True)
    return str(candidatos[0]) if candidatos else shutil.which("pg_dump")


def _exigir_admin(actor: dict[str, Any]) -> None:
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede crear o restaurar respaldos")


def _plano(valor: Any) -> Any:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (bytes, memoryview)):
        return base64.b64encode(bytes(valor)).decode("ascii")
    return valor


def _filas(con: Any, sql: str, params: tuple) -> list[dict[str, Any]]:
    return [{k: _plano(v) for k, v in f.items()} for f in con.execute(sql, params).fetchall()]


# --------------------------------------------------------------------------- exportar un proyecto (JSON)

# Columns added by the Visio migration (009): exported, and restored with an UPDATE after the insert
# (older backups simply do not have them).
EXTRA = {
    "elementos": ("fuente", "confianza", "estado_migracion", "ref_visio"),
    "cables": ("configuracion_estimada", "tipo_fibra", "fuente", "confianza", "geom_fuente", "estado_migracion", "ref_visio"),
    "splitters": ("propiedades", "fuente", "confianza"),
    "conexiones": ("bandeja", "posicion_en_bandeja", "fuente", "confianza", "posicion_estimada"),
    "mufa_modelos": ("motivo", "avisos"),                       # 010
}


def _existentes(con: Any, tabla: str, columnas: tuple[str, ...]) -> list[str]:
    """The columns of `columnas` that `redes.tabla` has now. The backup before migration 009 runs on the
    schema without its columns (and with this same code), so it exports only what exists."""
    hay = {f["column_name"] for f in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'redes' AND table_name = %s", (tabla,)).fetchall()}
    return [c for c in columnas if c in hay]


def _lista(con: Any, tabla: str, columnas: tuple[str, ...], prefijo: str = "") -> str:
    """', col1, col2' with the existing ones ('' if none), to append to a SELECT list."""
    return "".join(f", {prefijo}{c}" for c in _existentes(con, tabla, columnas))


def _hay_tabla(con: Any, tabla: str) -> bool:
    return con.execute("SELECT to_regclass(%s) IS NOT NULL AS t", (f"redes.{tabla}",)).fetchone()["t"]


def _extras(con: Any, tabla: str, id_: int, fila: dict[str, Any]) -> None:
    valores = {k: (Jsonb(fila[k]) if isinstance(fila[k], (dict, list)) else fila[k]) for k in EXTRA[tabla] if k in fila and fila[k] is not None}
    if valores:
        con.execute(f"UPDATE redes.{tabla} SET {', '.join(f'{k} = %s' for k in valores)} WHERE id = %s", (*valores.values(), id_))


def exportar_proyecto(con: Any, proyecto_id: int) -> dict[str, Any]:
    """Everything of one project, ids kept as they are (the import maps them)."""
    p = con.execute(
        "SELECT p.id, p.codigo, p.nombre, p.descripcion, padre.codigo AS padre_codigo, ST_Y(p.ubicacion) AS lat, ST_X(p.ubicacion) AS lon, "
        "ST_AsGeoJSON(p.area) AS area, p.imagen, p.imagen_tipo, p.miniatura" + _lista(con, "proyectos", ("es_red_base", "zona"), "p.")
        + " FROM redes.proyectos p "
        "LEFT JOIN redes.proyectos padre ON padre.id = p.padre_id WHERE p.id = %s AND p.borrado_en IS NULL", (proyecto_id,)).fetchone()
    if p is None:
        raise NoEncontrado("El proyecto no existe (o fue eliminado)")
    pid = p["id"]
    cables_sql = "SELECT id FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL"
    return {
        "proyecto": {k: _plano(v) for k, v in dict(p).items()},
        "usuarios": _filas(con, "SELECT u.nombre, u.persona_visor, u.usuario_windows FROM redes.proyecto_usuarios pu "
                                "JOIN redes.usuarios u ON u.id = pu.usuario_id WHERE pu.proyecto_id = %s", (pid,)),
        "elementos": _filas(con, "SELECT id, tipo, subtipo, nombre, codigo, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, propiedades, "
                                 "ref_externa" + _lista(con, "elementos", ("ubicacion_fuente", *EXTRA["elementos"])) + " FROM redes.elementos "
                                 "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        "cables": _filas(con, "SELECT id, nombre, descripcion, clase, tipo, hilos, hilos_por_buffer, color, origen_id, destino_id, vertices, "
                              "ST_AsGeoJSON(geom) AS geom, cruces, longitud_m, metraje" + _lista(con, "cables", EXTRA["cables"]) + " FROM redes.cables "
                              "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        "notas": _filas(con, "SELECT contexto, mufa_id, elemento_id, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon, x, y, html, ancho "
                             "FROM redes.notas WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        "hilos": _filas(con, f"SELECT id, cable_id, numero, estado, observacion FROM redes.hilos WHERE borrado_en IS NULL "
                             f"AND cable_id IN ({cables_sql}) ORDER BY id", (pid,)),
        "mufa_cables": _filas(con, f"SELECT mufa_id, cable_id, x, y FROM redes.mufa_cables WHERE cable_id IN ({cables_sql})", (pid,)),
        "splitters": _filas(con, "SELECT id, mufa_id, nombre, salidas, relacion, conector, x, y" + _lista(con, "splitters", EXTRA["splitters"])
                                 + " FROM redes.splitters WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        "conectores": _filas(con, "SELECT id, mufa_id, nombre, tipo, x, y FROM redes.conectores WHERE proyecto_id = %s "
                                  "AND borrado_en IS NULL ORDER BY id", (pid,)),
        "puertos": _filas(con, "SELECT p.id, p.splitter_id, p.conector_id, p.lado, p.numero FROM redes.puertos p "
                               "LEFT JOIN redes.splitters s ON s.id = p.splitter_id LEFT JOIN redes.conectores k ON k.id = p.conector_id "
                               "WHERE (s.proyecto_id = %s AND s.borrado_en IS NULL) OR (k.proyecto_id = %s AND k.borrado_en IS NULL) "
                               "ORDER BY p.id", (pid, pid)),
        "conexiones": _filas(con, "SELECT mufa_id, a_hilo_id, a_puerto_id, b_hilo_id, b_puerto_id" + _lista(con, "conexiones", EXTRA["conexiones"])
                                  + " FROM redes.conexiones WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        # migración Visio (009): modelo y bandejas de cada mufa, clientes por puerto y por mufa
        "mufa_modelos": [] if not _hay_tabla(con, "mufa_modelos") else _filas(con, "SELECT m.id, m.mufa_id, m.formato, m.capacidad, m.empalmes_por_bandeja, m.bandejas, m.modelo_estimado, m.fuente"
                                    + _lista(con, "mufa_modelos", EXTRA["mufa_modelos"], "m.") + " FROM redes.mufa_modelos m JOIN redes.elementos e ON e.id = m.mufa_id "
                                    "WHERE e.proyecto_id = %s AND m.borrado_en IS NULL", (pid,)),
        "mufa_bandejas": [] if not _hay_tabla(con, "mufa_bandejas") else _filas(con, "SELECT b.mufa_id, b.numero, b.capacidad, b.splitter_id, b.fuente FROM redes.mufa_bandejas b "
                                     "JOIN redes.elementos e ON e.id = b.mufa_id WHERE e.proyecto_id = %s AND b.borrado_en IS NULL "
                                     "ORDER BY b.mufa_id, b.numero", (pid,)),
        "puerto_servicios": [] if not _hay_tabla(con, "puerto_servicios") else _filas(con, "SELECT ps.puerto_id, ps.codigo_cliente, ps.nombre, ps.id_servicio, ps.elemento_id, ps.fuente, ps.confianza "
                                        "FROM redes.puerto_servicios ps JOIN redes.puertos p ON p.id = ps.puerto_id "
                                        "JOIN redes.splitters s ON s.id = p.splitter_id WHERE s.proyecto_id = %s AND ps.borrado_en IS NULL", (pid,)),
        "mufa_clientes": [] if not _hay_tabla(con, "mufa_clientes") else _filas(con, "SELECT c.mufa_id, c.codigo_cliente, c.nombre, c.id_servicio, c.elemento_id, c.fuente, c.confianza "
                                     "FROM redes.mufa_clientes c JOIN redes.elementos e ON e.id = c.mufa_id "
                                     "WHERE e.proyecto_id = %s AND c.borrado_en IS NULL", (pid,)),
        "diagramas": _filas(con, "SELECT titulo, elemento_id, splitter_id, direccion, incluir_clientes FROM redes.diagramas_logicos "
                                 "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,)),
        "problemas": [{**pr, "fotos": _filas(con, "SELECT imagen, imagen_tipo, miniatura FROM redes.problema_fotos WHERE problema_id = %s "
                                                  "AND borrado_en IS NULL ORDER BY id", (pr["id"],))}
                      for pr in _filas(con, "SELECT id, elemento_id, cable_id, titulo, descripcion, severidad, estado, ST_Y(ubicacion) AS lat, "
                                            "ST_X(ubicacion) AS lon, cerrado_en, creado_en FROM redes.problemas "
                                            "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY id", (pid,))],
        "pendientes": _filas(con, "SELECT t.titulo, t.descripcion, t.elemento_id, t.cable_id, u.nombre AS responsable, t.fecha_limite, "
                                  "t.estado, t.hecho_en FROM redes.pendientes t LEFT JOIN redes.usuarios u ON u.id = t.responsable_id "
                                  "WHERE t.proyecto_id = %s AND t.borrado_en IS NULL ORDER BY t.id", (pid,)),
    }


def _punto(lat: Any, lon: Any) -> str | None:
    return None if lat is None or lon is None else f"SRID=4326;POINT({float(lon):.8f} {float(lat):.8f})"


def _bytes(valor: Any) -> bytes | None:
    return base64.b64decode(valor) if valor else None


def importar_proyecto(con: Any, actor: dict[str, Any], datos: dict[str, Any], *, codigo: str, nombre: str) -> int:
    """Creates a NEW project from an exported one (inside the caller's transaction); returns its id."""
    p = datos["proyecto"]
    padre = con.execute("SELECT id FROM redes.proyectos WHERE codigo = %s AND borrado_en IS NULL", (p.get("padre_codigo"),)).fetchone() \
        if p.get("padre_codigo") else None
    nuevo = con.execute(
        "INSERT INTO redes.proyectos (codigo, nombre, descripcion, padre_id, ubicacion, area, imagen, imagen_tipo, miniatura, creado_por) "
        "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s::text IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326) END, "
        "%s, %s, %s, %s) RETURNING id",
        (codigo, nombre, p.get("descripcion"), padre["id"] if padre else None, _punto(p.get("lat"), p.get("lon")), p.get("area"), p.get("area"),
         _bytes(p.get("imagen")), p.get("imagen_tipo"), _bytes(p.get("miniatura")), actor["id"])).fetchone()["id"]
    # users: the same people when they still exist (by visor person, Windows user or name), plus whoever restores
    ids_usuarios = {actor["id"]}
    for u in datos.get("usuarios", []):
        f = con.execute("SELECT id FROM redes.usuarios WHERE borrado_en IS NULL AND ((persona_visor IS NOT NULL AND persona_visor = %s) "
                        "OR (usuario_windows IS NOT NULL AND usuario_windows = %s) OR nombre = %s) ORDER BY id LIMIT 1",
                        (u.get("persona_visor"), u.get("usuario_windows"), u.get("nombre"))).fetchone()
        if f:
            ids_usuarios.add(f["id"])
    for uid in ids_usuarios:
        con.execute("INSERT INTO redes.proyecto_usuarios (proyecto_id, usuario_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (nuevo, uid))
    el: dict[int, int] = {}
    for e in datos.get("elementos", []):
        el[e["id"]] = con.execute(
            "INSERT INTO redes.elementos (proyecto_id, tipo, subtipo, nombre, codigo, ubicacion, propiedades, ref_externa, ubicacion_fuente, "
            "creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (nuevo, e["tipo"], e["subtipo"], e["nombre"], e["codigo"], _punto(e["lat"], e["lon"]), Jsonb(e.get("propiedades") or {}),
             Jsonb(e["ref_externa"]) if e.get("ref_externa") else None,
             e.get("ubicacion_fuente") or ("sin_ubicar" if e["lat"] is None else "real"), actor["id"])).fetchone()["id"]
        _extras(con, "elementos", el[e["id"]], e)
    ca: dict[int, int] = {}
    for c in datos.get("cables", []):
        if c["origen_id"] not in el or c["destino_id"] not in el:
            continue
        vertices = [{**v, "elemento_id": el.get(v.get("elemento_id"))} for v in (c.get("vertices") or [])]
        ca[c["id"]] = con.execute(
            "INSERT INTO redes.cables (proyecto_id, nombre, descripcion, clase, tipo, hilos, hilos_por_buffer, color, origen_id, destino_id, "
            "vertices, geom, cruces, longitud_m, metraje, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s) RETURNING id",
            (nuevo, c["nombre"], c["descripcion"], c["clase"], c["tipo"], c["hilos"], c["hilos_por_buffer"], c["color"], el[c["origen_id"]],
             el[c["destino_id"]], Jsonb(vertices), c["geom"], c["cruces"], c["longitud_m"], Jsonb(c["metraje"]) if c.get("metraje") else None,
             actor["id"])).fetchone()["id"]
        _extras(con, "cables", ca[c["id"]], c)
    for n in datos.get("notas", []):
        con.execute("INSERT INTO redes.notas (proyecto_id, contexto, mufa_id, elemento_id, ubicacion, x, y, html, ancho, creado_por) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (nuevo, n["contexto"], el.get(n["mufa_id"]), el.get(n["elemento_id"]), _punto(n["lat"], n["lon"]), n["x"], n["y"],
                     n["html"], n["ancho"], actor["id"]))
    hi: dict[int, int] = {}
    for h in datos.get("hilos", []):
        if h["cable_id"] in ca:
            hi[h["id"]] = con.execute("INSERT INTO redes.hilos (cable_id, numero, estado, observacion, creado_por) VALUES (%s, %s, %s, %s, %s) "
                                      "RETURNING id", (ca[h["cable_id"]], h["numero"], h["estado"], h["observacion"], actor["id"])).fetchone()["id"]
    for m in datos.get("mufa_cables", []):
        if m["mufa_id"] in el and m["cable_id"] in ca:
            con.execute("INSERT INTO redes.mufa_cables (mufa_id, cable_id, x, y) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (el[m["mufa_id"]], ca[m["cable_id"]], m["x"], m["y"]))
    sp: dict[int, int] = {}
    for s in datos.get("splitters", []):
        if s["mufa_id"] in el:
            sp[s["id"]] = repositorio.insertar(con, "splitters", {"proyecto_id": nuevo, "mufa_id": el[s["mufa_id"]], "nombre": s["nombre"],
                                                                  "salidas": s["salidas"], "relacion": s["relacion"], "conector": s["conector"],
                                                                  "x": s["x"], "y": s["y"]}, actor["id"])["id"]
            _extras(con, "splitters", sp[s["id"]], s)
    co: dict[int, int] = {}
    for k in datos.get("conectores", []):
        if k["mufa_id"] in el:
            co[k["id"]] = repositorio.insertar(con, "conectores", {"proyecto_id": nuevo, "mufa_id": el[k["mufa_id"]], "nombre": k["nombre"],
                                                                   "tipo": k["tipo"], "x": k["x"], "y": k["y"]}, actor["id"])["id"]
    pu: dict[int, int] = {}
    for p_ in datos.get("puertos", []):
        s, k = sp.get(p_["splitter_id"]), co.get(p_["conector_id"])
        if s or k:
            pu[p_["id"]] = con.execute("INSERT INTO redes.puertos (splitter_id, conector_id, lado, numero) VALUES (%s, %s, %s, %s) RETURNING id",
                                       (s, k, p_["lado"], p_["numero"])).fetchone()["id"]
    for x in datos.get("conexiones", []):
        a, b = (hi.get(x["a_hilo_id"]), pu.get(x["a_puerto_id"])), (hi.get(x["b_hilo_id"]), pu.get(x["b_puerto_id"]))
        if x["mufa_id"] in el and any(a) and any(b):
            nueva = con.execute("INSERT INTO redes.conexiones (proyecto_id, mufa_id, a_hilo_id, a_puerto_id, b_hilo_id, b_puerto_id, creado_por) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (nuevo, el[x["mufa_id"]], *a, *b, actor["id"])).fetchone()["id"]
            _extras(con, "conexiones", nueva, x)
    for m in datos.get("mufa_modelos", []):
        if m["mufa_id"] in el:
            nuevo_modelo = repositorio.insertar(con, "mufa_modelos", {**{k: m[k] for k in ("formato", "capacidad", "empalmes_por_bandeja", "bandejas",
                                                                            "modelo_estimado", "fuente")}, "mufa_id": el[m["mufa_id"]]}, actor["id"])
            _extras(con, "mufa_modelos", nuevo_modelo["id"], m)
    for b in datos.get("mufa_bandejas", []):
        if b["mufa_id"] in el:
            repositorio.insertar(con, "mufa_bandejas", {"mufa_id": el[b["mufa_id"]], "numero": b["numero"], "capacidad": b["capacidad"],
                                                        "splitter_id": sp.get(b["splitter_id"]), "fuente": b["fuente"]}, actor["id"])
    for s in datos.get("puerto_servicios", []):
        if s["puerto_id"] in pu:
            repositorio.insertar(con, "puerto_servicios", {**{k: s[k] for k in ("codigo_cliente", "nombre", "id_servicio", "fuente", "confianza")},
                                                           "puerto_id": pu[s["puerto_id"]], "elemento_id": el.get(s["elemento_id"])}, actor["id"])
    for c in datos.get("mufa_clientes", []):
        if c["mufa_id"] in el:
            repositorio.insertar(con, "mufa_clientes", {**{k: c[k] for k in ("codigo_cliente", "nombre", "id_servicio", "fuente", "confianza")},
                                                        "mufa_id": el[c["mufa_id"]], "elemento_id": el.get(c["elemento_id"])}, actor["id"])
    for d in datos.get("diagramas", []):
        e, s = el.get(d["elemento_id"]), sp.get(d["splitter_id"])
        if e or s:
            repositorio.insertar(con, "diagramas_logicos", {"proyecto_id": nuevo, "titulo": d["titulo"], "elemento_id": e, "splitter_id": s,
                                                            "direccion": d["direccion"], "incluir_clientes": d["incluir_clientes"]}, actor["id"])
    for pr in datos.get("problemas", []):
        e, c = el.get(pr["elemento_id"]), ca.get(pr["cable_id"])
        if not (e or c):
            continue
        nuevo_pr = con.execute(
            "INSERT INTO redes.problemas (proyecto_id, elemento_id, cable_id, titulo, descripcion, severidad, estado, ubicacion, cerrado_en, "
            "creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (nuevo, e, c, pr["titulo"], pr["descripcion"], pr["severidad"], pr["estado"], _punto(pr["lat"], pr["lon"]), pr["cerrado_en"],
             actor["id"])).fetchone()["id"]
        for f in pr.get("fotos", []):
            con.execute("INSERT INTO redes.problema_fotos (problema_id, imagen, imagen_tipo, miniatura, creado_por) VALUES (%s, %s, %s, %s, %s)",
                        (nuevo_pr, _bytes(f["imagen"]), f["imagen_tipo"], _bytes(f["miniatura"]), actor["id"]))
    for t in datos.get("pendientes", []):
        r = con.execute("SELECT id FROM redes.usuarios WHERE nombre = %s AND borrado_en IS NULL ORDER BY id LIMIT 1",
                        (t.get("responsable"),)).fetchone() if t.get("responsable") else None
        con.execute("INSERT INTO redes.pendientes (proyecto_id, elemento_id, cable_id, titulo, descripcion, responsable_id, fecha_limite, estado, "
                    "hecho_en, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (nuevo, el.get(t["elemento_id"]), ca.get(t["cable_id"]), t["titulo"], t["descripcion"], r["id"] if r else None,
                     t["fecha_limite"], t["estado"], t["hecho_en"], actor["id"]))
    return nuevo


# --------------------------------------------------------------------------- respaldos

def _info_archivo(ruta: Path) -> dict[str, Any]:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        lista = [{"indice": i, "codigo": p["proyecto"]["codigo"], "nombre": p["proyecto"]["nombre"], "elementos": len(p.get("elementos", [])),
                  "cables": len(p.get("cables", []))} for i, p in enumerate(datos.get("proyectos", []))]
        creado, por, error = datos.get("creado_en"), datos.get("creado_por"), None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        lista, creado, por, error = [], None, None, f"No se puede leer ({type(exc).__name__})"
    sql = ruta.with_suffix(".sql")
    return {"archivo": ruta.name, "fecha": creado or datetime.fromtimestamp(ruta.stat().st_mtime).isoformat(timespec="seconds"),
            "creado_por": por, "tamano": ruta.stat().st_size, "proyectos": lista, "error": error,
            "sql": sql.name if sql.is_file() else None, "sql_tamano": sql.stat().st_size if sql.is_file() else None}


def listar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    _exigir_admin(actor)
    destino = carpeta()
    archivos = sorted((p for p in destino.glob("respaldo_redes_*.json") if _NOMBRE.match(p.name)), reverse=True)
    return {"carpeta": str(destino), "pg_dump": pg_dump(), "respaldos": [_info_archivo(p) for p in archivos]}


def crear(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    _exigir_admin(actor)
    archivo, aviso = respaldar(con, actor["nombre"], actor["id"])
    return {**listar(con, actor), "creado": archivo, "aviso": aviso}


def respaldar(con: Any, creado_por: str, usuario_id: int | None = None, motivo: str | None = None) -> tuple[str, str | None]:
    """The backup itself (.json of every active project + .sql with pg_dump); returns (file name,
    warning). Also used by migrar.py before a migration marked "-- respaldo: previo"."""
    ahora = datetime.now()
    base = carpeta() / f"respaldo_redes_{ahora:%Y-%m-%d_%H%M%S}"
    while base.with_suffix(".json").exists():        # two backups in the same second (009 then 010): never overwrite
        ahora += timedelta(seconds=1)
        base = carpeta() / f"respaldo_redes_{ahora:%Y-%m-%d_%H%M%S}"
    ids = [f["id"] for f in con.execute("SELECT id FROM redes.proyectos WHERE borrado_en IS NULL ORDER BY id").fetchall()]
    with con.transaction():                  # one consistent snapshot of every project
        con.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        contenido = {"formato": FORMATO, "version": VERSION, "creado_en": ahora.isoformat(timespec="seconds"), "creado_por": creado_por,
                     "motivo": motivo, "base": con.info.dbname, "proyectos": [exportar_proyecto(con, i) for i in ids]}
    temporal = base.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    temporal.replace(base.with_suffix(".json"))
    aviso = None
    ejecutable = pg_dump()
    if ejecutable:
        info = con.info
        try:
            r = subprocess.run([ejecutable, "-h", info.host, "-p", str(info.port), "-U", info.user, "-d", info.dbname, "-n", "redes",
                                "--no-owner", "--no-privileges", "--encoding=UTF8", "-f", str(base.with_suffix(".sql"))],
                               env={**os.environ, "PGPASSWORD": info.password or ""}, capture_output=True, text=True, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                aviso = "pg_dump falló: " + (r.stderr.strip().splitlines() or ["sin detalle"])[-1][:200]
                base.with_suffix(".sql").unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError) as exc:
            aviso = f"pg_dump no se pudo ejecutar ({type(exc).__name__})"
    else:
        aviso = "pg_dump no está instalado: solo se creó el respaldo JSON"
    cambio = {"archivo": [None, base.with_suffix(".json").name], "proyectos": [None, len(ids)]}
    if motivo:
        cambio["motivo"] = [None, motivo]
    repositorio.registrar(con, usuario_id, "respaldo", None, "crear", cambio)
    return base.with_suffix(".json").name, aviso


def _archivo(nombre: Any, sufijo: str = ".json") -> Path:
    nombre = str(nombre or "")
    if not _NOMBRE.match(nombre) or not nombre.endswith(sufijo):
        raise DatosInvalidos({"archivo": "nombre de respaldo no válido"})
    ruta = carpeta() / nombre
    if not ruta.is_file():
        raise NoEncontrado("El respaldo ya no está en la carpeta de respaldos")
    return ruta


def restaurar(con: Any, actor: dict[str, Any], *, archivo: str, indice: int) -> dict[str, Any]:
    """One project of a backup as a NEW project (code -R1, -R2…): the current one is never touched."""
    _exigir_admin(actor)
    datos = json.loads(_archivo(archivo).read_text(encoding="utf-8"))
    if datos.get("formato") != FORMATO:
        raise DatosInvalidos({"archivo": "no es un respaldo del módulo de redes"})
    try:
        p = datos["proyectos"][int(indice)]
    except (IndexError, ValueError, TypeError):
        raise NoEncontrado("Ese proyecto no está en el respaldo") from None
    base_codigo = p["proyecto"]["codigo"]
    n = 1
    while con.execute("SELECT 1 FROM redes.proyectos WHERE codigo = %s AND borrado_en IS NULL", (f"{base_codigo}-R{n}",)).fetchone():
        n += 1
    codigo = f"{base_codigo}-R{n}"
    fecha = (datos.get("creado_en") or "")[:10]
    nombre = f"{p['proyecto']['nombre']} (restaurado {fecha})"[:120]
    with con.transaction():
        nuevo = importar_proyecto(con, actor, p, codigo=codigo, nombre=nombre)
        repositorio.registrar(con, actor["id"], "proyecto", nuevo, "restaurar",
                              {"respaldo": [None, archivo], "copia_de": [None, base_codigo]}, proyecto_id=nuevo)
    return {"proyecto": proyectos.obtener(con, actor, id=nuevo)["proyecto"]}


def descargar(con: Any, actor: dict[str, Any], *, archivo: str) -> dict[str, Any]:
    _exigir_admin(actor)
    ruta = _archivo(archivo, ".sql" if str(archivo).endswith(".sql") else ".json")
    return {"nombre": ruta.name, "tipo": ruta.suffix.lstrip("."), "datos": base64.b64encode(ruta.read_bytes()).decode("ascii")}


# --------------------------------------------------------------------------- exportar a GeoJSON / KMZ

def _capas(con: Any, proyecto_id: int) -> dict[str, Any]:
    p = con.execute("SELECT id, codigo, nombre, descripcion, ST_AsGeoJSON(area, 7) AS area FROM redes.proyectos WHERE id = %s", (proyecto_id,)).fetchone()
    elementos = [dict(f) for f in con.execute(
        "SELECT id, tipo, subtipo, nombre, codigo, propiedades, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon FROM redes.elementos "
        "WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY tipo, nombre", (proyecto_id,)).fetchall()]
    nombres = {e["id"]: e["nombre"] for e in elementos}
    cables = [dict(f) for f in con.execute(
        "SELECT id, nombre, descripcion, clase, tipo, hilos, hilos_por_buffer, color, origen_id, destino_id, longitud_m, metraje, "
        "ST_AsGeoJSON(geom, 7) AS geom FROM redes.cables WHERE proyecto_id = %s AND borrado_en IS NULL ORDER BY nombre", (proyecto_id,)).fetchall()]
    problemas = [dict(f) for f in con.execute(
        "SELECT pr.titulo, pr.descripcion, pr.severidad, pr.estado, COALESCE(e.nombre, c.nombre) AS vinculo, "
        "ST_Y(COALESCE(e.ubicacion, ST_LineInterpolatePoint(c.geom, 0.5), pr.ubicacion)) AS lat, "
        "ST_X(COALESCE(e.ubicacion, ST_LineInterpolatePoint(c.geom, 0.5), pr.ubicacion)) AS lon "
        "FROM redes.problemas pr LEFT JOIN redes.elementos e ON e.id = pr.elemento_id AND e.borrado_en IS NULL "
        "LEFT JOIN redes.cables c ON c.id = pr.cable_id AND c.borrado_en IS NULL WHERE pr.proyecto_id = %s AND pr.borrado_en IS NULL",
        (proyecto_id,)).fetchall()]
    return {"proyecto": dict(p), "elementos": elementos, "cables": cables, "problemas": problemas, "nombres": nombres}


ETIQUETA_TIPO = {"nodo": "Nodos / OLT", "mufa": "Mufas", "poste": "Postes", "cliente": "Clientes"}
SEVERIDAD = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
ESTADO = {"abierto": "Abierto", "en_proceso": "En proceso", "cerrado": "Cerrado"}


def _geojson(c: dict[str, Any]) -> bytes:
    p, nombres = c["proyecto"], c["nombres"]
    rasgos = []
    if p["area"]:
        rasgos.append({"type": "Feature", "geometry": json.loads(p["area"]), "properties": {"capa": "area", "nombre": f"Área de {p['nombre']}"}})
    for e in c["elementos"]:
        rasgos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
                       "properties": {"capa": "elemento", "id": e["id"], "tipo": e["tipo"], "subtipo": e["subtipo"], "nombre": e["nombre"],
                                      "codigo": e["codigo"], **{f"prop_{k}": v for k, v in (e["propiedades"] or {}).items()}}})
    for k in c["cables"]:
        rasgos.append({"type": "Feature", "geometry": json.loads(k["geom"]),
                       "properties": {"capa": "cable", "id": k["id"], "nombre": k["nombre"], "clase": k["clase"], "tipo": k["tipo"],
                                      "hilos": k["hilos"], "hilos_por_buffer": k["hilos_por_buffer"], "color": k["color"],
                                      "origen": nombres.get(k["origen_id"]), "destino": nombres.get(k["destino_id"]),
                                      "longitud_m": float(k["longitud_m"] or 0), "metraje_m": (k["metraje"] or {}).get("metraje_m")}})
    for pr in c["problemas"]:
        if pr["lat"] is not None:
            rasgos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [pr["lon"], pr["lat"]]},
                           "properties": {"capa": "problema", "titulo": pr["titulo"], "severidad": pr["severidad"], "estado": pr["estado"],
                                          "en": pr["vinculo"], "descripcion": pr["descripcion"]}})
    return json.dumps({"type": "FeatureCollection", "name": f"{p['codigo']} {p['nombre']}", "features": rasgos},
                      ensure_ascii=False, indent=1, default=_plano).encode("utf-8")


def _icono(tipo: str) -> bytes:
    """32x32 PNG icons drawn here, so the KMZ works offline in Google Earth."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tipo == "nodo":
        d.polygon([(32, 6), (60, 56), (4, 56)], fill=(245, 166, 35, 255), outline=(60, 40, 0, 255))
    elif tipo == "mufa_distribucion":
        d.rectangle((8, 8, 56, 56), fill=(255, 251, 230, 255), outline=(212, 176, 0, 255), width=7)
    elif tipo.startswith("mufa"):
        color = {"mufa_terminal": (213, 0, 249, 255)}.get(tipo, (229, 57, 53, 255))
        d.ellipse((6, 6, 58, 58), fill=(255, 255, 255, 255), outline=color, width=8)
    elif tipo == "cliente":
        d.polygon([(32, 6), (60, 30), (52, 30), (52, 58), (12, 58), (12, 30), (4, 30)], fill=(46, 157, 74, 255), outline=(20, 70, 30, 255))
    elif tipo == "problema":
        d.polygon([(32, 4), (62, 58), (2, 58)], fill=(229, 57, 53, 255), outline=(90, 0, 0, 255))
        d.rectangle((29, 20, 35, 42), fill=(255, 255, 255, 255))
        d.rectangle((29, 47, 35, 53), fill=(255, 255, 255, 255))
    else:                                   # poste
        d.ellipse((16, 16, 48, 48), fill=(120, 120, 120, 255), outline=(30, 30, 30, 255), width=4)
    salida = io.BytesIO()
    img.resize((32, 32), Image.LANCZOS).save(salida, "PNG")
    return salida.getvalue()


def _kml_color(hexa: str | None, alfa: str = "ff") -> str:
    h = (hexa or "#1f6feb").lstrip("#")
    h = h if len(h) == 6 else "1f6feb"
    return f"{alfa}{h[4:6]}{h[2:4]}{h[0:2]}"


def _descripcion(filas: list[tuple[str, Any]]) -> str:
    return escape("<table>" + "".join(f"<tr><td><b>{escape(str(k))}</b></td><td>{escape(str(v))}</td></tr>"
                                      for k, v in filas if v not in (None, "")) + "</table>")


def _kmz(c: dict[str, Any]) -> bytes:
    p, nombres = c["proyecto"], c["nombres"]
    iconos = ["nodo", "mufa", "mufa_empalme", "mufa_distribucion", "mufa_terminal", "poste", "cliente", "problema"]
    estilos = [f'<Style id="i-{i}"><IconStyle><scale>1.0</scale><Icon><href>files/{i}.png</href></Icon></IconStyle>'
               f'<LabelStyle><scale>0.8</scale></LabelStyle></Style>' for i in iconos]
    estilos.append('<Style id="area"><LineStyle><color>ffdb6f2f</color><width>2</width></LineStyle>'
                   '<PolyStyle><color>222f6fdb</color></PolyStyle></Style>')
    for k in c["cables"]:
        ancho = {"troncal": 5, "acometida": 2}.get(k["clase"], 3)
        estilos.append(f'<Style id="c-{k["id"]}"><LineStyle><color>{_kml_color(k["color"])}</color><width>{ancho}</width></LineStyle></Style>')
    partes = []
    if p["area"]:
        geo = json.loads(p["area"])
        anillos = geo["coordinates"] if geo["type"] == "Polygon" else geo["coordinates"][0]
        coords = " ".join(f"{x},{y},0" for x, y in anillos[0])
        partes.append(f'<Folder><name>Área</name><Placemark><name>{escape(p["nombre"])}</name><styleUrl>#area</styleUrl><Polygon>'
                      f'<outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Folder>')
    for tipo, etiqueta in ETIQUETA_TIPO.items():
        lista = [e for e in c["elementos"] if e["tipo"] == tipo]
        if not lista:
            continue
        marcas = []
        for e in lista:
            icono = f"mufa_{e['subtipo']}" if tipo == "mufa" and e["subtipo"] in ("empalme", "distribucion", "terminal") else tipo
            desc = _descripcion([("Tipo", tipo), ("Subtipo", e["subtipo"]), ("Código", e["codigo"]),
                                 *[(k, v) for k, v in (e["propiedades"] or {}).items()]])
            marcas.append(f'<Placemark><name>{escape(e["nombre"])}</name><description>{desc}</description><styleUrl>#i-{icono}</styleUrl>'
                          f'<Point><coordinates>{e["lon"]},{e["lat"]},0</coordinates></Point></Placemark>')
        partes.append(f"<Folder><name>{etiqueta}</name>{''.join(marcas)}</Folder>")
    if c["cables"]:
        marcas = []
        for k in c["cables"]:
            geo = json.loads(k["geom"])
            coords = " ".join(f"{x},{y},0" for x, y in geo["coordinates"])
            desc = _descripcion([("Clase", k["clase"]), ("Tipo", k["tipo"]), ("Hilos", k["hilos"]), ("Hilos por buffer", k["hilos_por_buffer"]),
                                 ("Origen", nombres.get(k["origen_id"])), ("Destino", nombres.get(k["destino_id"])),
                                 ("Longitud (m)", round(float(k["longitud_m"] or 0), 1)), ("Metraje (m)", (k["metraje"] or {}).get("metraje_m")),
                                 ("Descripción", k["descripcion"])])
            marcas.append(f'<Placemark><name>{escape(k["nombre"])}</name><description>{desc}</description><styleUrl>#c-{k["id"]}</styleUrl>'
                          f'<LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString></Placemark>')
        partes.append(f"<Folder><name>Cables</name>{''.join(marcas)}</Folder>")
    activos = [pr for pr in c["problemas"] if pr["lat"] is not None]
    if activos:
        marcas = [f'<Placemark><name>{escape(pr["titulo"])}</name><description>'
                  f'{_descripcion([("Severidad", SEVERIDAD.get(pr["severidad"])), ("Estado", ESTADO.get(pr["estado"])), ("En", pr["vinculo"]), ("Descripción", pr["descripcion"])])}'
                  f'</description><styleUrl>#i-problema</styleUrl><Point><coordinates>{pr["lon"]},{pr["lat"]},0</coordinates></Point></Placemark>'
                  for pr in activos]
        partes.append(f"<Folder><name>Problemas</name>{''.join(marcas)}</Folder>")
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>{escape(p["codigo"])} · {escape(p["nombre"])}</name><description>{escape(p["descripcion"] or "")}</description>'
           + "".join(estilos) + "".join(partes) + "</Document></kml>")
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml.encode("utf-8"))
        for i in iconos:
            z.writestr(f"files/{i}.png", _icono(i))
    return salida.getvalue()


def exportar(con: Any, actor: dict[str, Any], *, proyecto_id: int, formato: str) -> dict[str, Any]:
    """KMZ (Google Earth) or GeoJSON of one project: anyone who can see the project."""
    if formato not in ("kmz", "geojson"):
        raise DatosInvalidos({"formato": "kmz o geojson"})
    if not proyectos.puede_ver(con, actor, int(proyecto_id)):
        raise SinPermiso("No tiene acceso a este proyecto")
    c = _capas(con, int(proyecto_id))
    if c["proyecto"] is None:
        raise NoEncontrado("El proyecto no existe")
    datos = _kmz(c) if formato == "kmz" else _geojson(c)
    nombre = f"{c['proyecto']['codigo']} {c['proyecto']['nombre']}"
    return {"nombre": nombre, "tipo": formato, "datos": base64.b64encode(datos).decode("ascii"),
            "resumen": {"elementos": len(c["elementos"]), "cables": len(c["cables"]), "problemas": len(c["problemas"])}}
