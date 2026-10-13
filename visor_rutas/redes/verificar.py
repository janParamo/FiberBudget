"""Verificación de integridad del módulo de redes (sección 8 de la especificación).

Revisa en la base las reglas del modelo que no puede garantizar una restricción de PostgreSQL
(porque cruzan tablas o dependen del borrado lógico). Solo lee: no corrige nada.

    errores: datos que el visor no debería poder producir (conviene revisarlos)
    avisos:  situaciones válidas pero que alguien debería mirar (p. ej. un problema abierto
             cuyo elemento ya se eliminó)

Uso: menú Backup → "Verificar la base" (administradores), o
     .\\.venv\\Scripts\\python.exe -m visor_rutas.redes.verificar
"""
from datetime import datetime
from typing import Any

from visor_rutas.redes import usuarios
from visor_rutas.redes.db import SinPermiso

# (nivel, regla, consulta) — every query returns proyecto_id and texto
REGLAS: list[tuple[str, str, str]] = [
    ("error", "Hilos del cable",
     """SELECT c.proyecto_id, format('Cable %s: tiene %s hilos activos y debería tener %s (1..%s)', c.nombre, count(h.id), c.hilos, c.hilos) AS texto
        FROM redes.cables c LEFT JOIN redes.hilos h ON h.cable_id = c.id AND h.borrado_en IS NULL
        WHERE c.borrado_en IS NULL GROUP BY c.id
        HAVING count(h.id) <> c.hilos OR coalesce(min(h.numero), 1) <> 1 OR coalesce(max(h.numero), 0) <> c.hilos"""),
    ("error", "Buffer y color TIA",
     """SELECT c.proyecto_id, format('Cable %s hilo %s: buffer %s / color %s no coinciden con %s hilos por buffer', c.nombre, h.numero, h.buffer, h.color,
               c.hilos_por_buffer) AS texto
        FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id
        WHERE h.borrado_en IS NULL AND c.borrado_en IS NULL
          AND (h.buffer <> (h.numero - 1) / c.hilos_por_buffer + 1 OR h.color <> redes.color_tia((h.numero - 1) % c.hilos_por_buffer))"""),
    ("error", "Cable con extremo eliminado",
     """SELECT c.proyecto_id, format('Cable %s: su %s (%s) está eliminado', c.nombre, CASE WHEN o.borrado_en IS NOT NULL THEN 'origen' ELSE 'destino' END,
               CASE WHEN o.borrado_en IS NOT NULL THEN o.nombre ELSE d.nombre END) AS texto
        FROM redes.cables c JOIN redes.elementos o ON o.id = c.origen_id JOIN redes.elementos d ON d.id = c.destino_id
        WHERE c.borrado_en IS NULL AND (o.borrado_en IS NOT NULL OR d.borrado_en IS NOT NULL)"""),
    ("error", "Conexión con hilo eliminado",
     """SELECT x.proyecto_id, format('Mufa %s: una conexión usa el hilo %s de %s, que ya no existe', m.nombre, h.numero, c.nombre) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.hilos h ON h.id IN (x.a_hilo_id, x.b_hilo_id) JOIN redes.cables c ON c.id = h.cable_id
        WHERE x.borrado_en IS NULL AND (h.borrado_en IS NOT NULL OR c.borrado_en IS NOT NULL)"""),
    ("error", "Conexión con un cable que no llega a la mufa",
     """SELECT x.proyecto_id, format('Mufa %s: una conexión usa el hilo %s de %s, que no llega ni sale de esa mufa', m.nombre, h.numero, c.nombre) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.hilos h ON h.id IN (x.a_hilo_id, x.b_hilo_id) JOIN redes.cables c ON c.id = h.cable_id
        WHERE x.borrado_en IS NULL AND x.mufa_id NOT IN (c.origen_id, c.destino_id)"""),
    ("error", "Conexión con splitter o conector eliminado o de otra mufa",
     """SELECT x.proyecto_id, format('Mufa %s: una conexión usa un puerto de %s', m.nombre, coalesce(s.nombre, k.nombre)) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.puertos p ON p.id IN (x.a_puerto_id, x.b_puerto_id)
        LEFT JOIN redes.splitters s ON s.id = p.splitter_id LEFT JOIN redes.conectores k ON k.id = p.conector_id
        WHERE x.borrado_en IS NULL AND (coalesce(s.borrado_en, k.borrado_en) IS NOT NULL OR coalesce(s.mufa_id, k.mufa_id) <> x.mufa_id)"""),
    ("error", "Hilo conectado dos veces en la misma mufa",
     """SELECT x.proyecto_id, format('Mufa %s: el hilo %s de %s tiene %s conexiones', m.nombre, h.numero, c.nombre, count(*)) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.hilos h ON h.id IN (x.a_hilo_id, x.b_hilo_id) JOIN redes.cables c ON c.id = h.cable_id
        WHERE x.borrado_en IS NULL GROUP BY x.proyecto_id, m.nombre, h.id, h.numero, c.nombre HAVING count(*) > 1"""),
    ("error", "Salida de splitter fuera de rango",
     """SELECT x.proyecto_id, format('Mufa %s: %s (1x%s) tiene conectada la salida %s', m.nombre, s.nombre, s.salidas, p.numero) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.puertos p ON p.id IN (x.a_puerto_id, x.b_puerto_id) JOIN redes.splitters s ON s.id = p.splitter_id
        WHERE x.borrado_en IS NULL AND p.lado = 'salida' AND p.numero > s.salidas"""),
    ("error", "Empalme fuera de su bandeja",
     """SELECT x.proyecto_id, format('Mufa %s: un empalme está en la bandeja %s posición %s, que %s', m.nombre, x.bandeja, x.posicion_en_bandeja,
               CASE WHEN b.id IS NULL THEN 'no existe en el modelo' ELSE 'pasa de sus ' || b.capacidad || ' posiciones' END) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        LEFT JOIN redes.mufa_bandejas b ON b.mufa_id = x.mufa_id AND b.numero = x.bandeja AND b.borrado_en IS NULL
        WHERE x.borrado_en IS NULL AND x.bandeja IS NOT NULL AND (b.id IS NULL OR x.posicion_en_bandeja > b.capacidad)"""),
    ("error", "Bandeja de splitter con un empalme ajeno",
     """SELECT x.proyecto_id, format('Mufa %s: la bandeja %s es de %s y tiene un empalme que no es de ese splitter', m.nombre, b.numero, s.nombre) AS texto
        FROM redes.conexiones x JOIN redes.elementos m ON m.id = x.mufa_id
        JOIN redes.mufa_bandejas b ON b.mufa_id = x.mufa_id AND b.numero = x.bandeja AND b.borrado_en IS NULL
        JOIN redes.splitters s ON s.id = b.splitter_id
        WHERE x.borrado_en IS NULL AND NOT EXISTS (SELECT 1 FROM redes.puertos p WHERE p.id IN (x.a_puerto_id, x.b_puerto_id) AND p.splitter_id = s.id)"""),
    ("aviso", "Modelo de mufa con avisos",
     """SELECT m.proyecto_id, format('Mufa %s (%s hilos): %s', m.nombre, mm.capacidad, (SELECT string_agg(a, '; ') FROM jsonb_array_elements_text(mm.avisos) a)) AS texto
        FROM redes.mufa_modelos mm JOIN redes.elementos m ON m.id = mm.mufa_id
        WHERE mm.borrado_en IS NULL AND m.borrado_en IS NULL AND jsonb_array_length(mm.avisos) > 0"""),
    ("aviso", "Vértice pegado a un elemento eliminado",
     """SELECT c.proyecto_id, format('Cable %s: un punto sigue pegado a %s, que se eliminó', c.nombre, e.nombre) AS texto
        FROM redes.cables c CROSS JOIN LATERAL jsonb_array_elements(c.vertices) v
        JOIN redes.elementos e ON e.id = (v ->> 'elemento_id')::bigint
        WHERE c.borrado_en IS NULL AND e.borrado_en IS NOT NULL"""),
    ("aviso", "Diagrama sin inicio",
     """SELECT d.proyecto_id, format('Diagrama "%s": su elemento de inicio se eliminó', d.titulo) AS texto
        FROM redes.diagramas_logicos d LEFT JOIN redes.elementos e ON e.id = d.elemento_id LEFT JOIN redes.splitters s ON s.id = d.splitter_id
        WHERE d.borrado_en IS NULL AND coalesce(e.borrado_en, s.borrado_en) IS NOT NULL"""),
    ("aviso", "Problema abierto sobre algo eliminado",
     """SELECT pr.proyecto_id, format('Problema "%s" (%s): %s se eliminó', pr.titulo, pr.estado, coalesce(e.nombre, 'el cable ' || c.nombre)) AS texto
        FROM redes.problemas pr LEFT JOIN redes.elementos e ON e.id = pr.elemento_id LEFT JOIN redes.cables c ON c.id = pr.cable_id
        WHERE pr.borrado_en IS NULL AND pr.estado <> 'cerrado' AND coalesce(e.borrado_en, c.borrado_en) IS NOT NULL"""),
    ("aviso", "Pendiente con responsable desactivado",
     """SELECT t.proyecto_id, format('Pendiente "%s": su responsable %s está desactivado', t.titulo, u.nombre) AS texto
        FROM redes.pendientes t JOIN redes.usuarios u ON u.id = t.responsable_id
        WHERE t.borrado_en IS NULL AND t.estado <> 'hecho' AND u.borrado_en IS NOT NULL"""),
]


def revisar(con: Any) -> dict[str, Any]:
    """All the rules over the active projects."""
    nombres = {f["id"]: f"{f['nombre']} ({f['codigo']})" for f in con.execute(
        "SELECT id, nombre, codigo FROM redes.proyectos WHERE borrado_en IS NULL").fetchall()}
    hallazgos = []
    for nivel, regla, sql in REGLAS:
        for f in con.execute(sql).fetchall():
            if f["proyecto_id"] in nombres:                  # deleted projects are not checked
                hallazgos.append({"nivel": nivel, "regla": regla, "proyecto_id": f["proyecto_id"], "proyecto": nombres[f["proyecto_id"]],
                                  "texto": f["texto"]})
    hallazgos.sort(key=lambda h: (h["nivel"] != "error", h["proyecto"], h["regla"]))
    return {"revisado_en": datetime.now().isoformat(timespec="seconds"), "reglas": [r[1] for r in REGLAS], "proyectos": len(nombres),
            "errores": sum(h["nivel"] == "error" for h in hallazgos), "avisos": sum(h["nivel"] == "aviso" for h in hallazgos),
            "hallazgos": hallazgos}


def verificar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede verificar la base")
    return revisar(con)


def main() -> None:
    from visor_rutas.redes import db, migrar
    con = db.conectar()
    migrar.aplicar(con)
    r = revisar(con)
    print(f"{r['proyectos']} proyecto(s), {len(r['reglas'])} reglas: {r['errores']} error(es), {r['avisos']} aviso(s)")
    for h in r["hallazgos"]:
        print(f"  [{h['nivel']}] {h['proyecto']} · {h['regla']}: {h['texto']}")


if __name__ == "__main__":
    main()
