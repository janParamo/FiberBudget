"""Puerta única del módulo de redes: ServicioRedes.llamar(metodo, args).

La usan los dos caminos con el mismo resultado:
  - modo local: ventana_web.Api.redes(metodo, args)  -> identifica con el usuario de Windows;
  - modo remoto: POST /visor/redes/{metodo} {"args": {...}} (visor_api.py, X-Visor-Key)
                 -> identifica con la persona de la clave.
Solo se pueden llamar los métodos de METODOS; cada uno revisa sus permisos. Respuesta:
{"ok": true, ...} o {"ok": false, "error": "...", "errores"?: {...}, "conflicto"?: true}.
"""
import logging
import threading
from typing import Any, Callable

import psycopg

from visor_rutas.redes import bandejas, db, diagrama, migracion_tablero, migrar, mufa, mufas_existentes, pendientes, problemas, proyectos, red, respaldo, trazado, usuarios, verificar

log = logging.getLogger(__name__)


def _estado(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    postgis = con.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'").fetchone()
    return {"usuario": usuarios.publico(actor),
            "puede": {"administrar": usuarios.es_admin(actor), "editar": usuarios.puede_editar(actor)},
            "migraciones": sorted(migrar.aplicadas(con)), "postgis": postgis["extversion"] if postgis else None}


METODOS: dict[str, Callable[..., dict[str, Any]]] = {
    "estado": _estado,
    "usuarios": usuarios.listar,
    "guardar_usuario": usuarios.guardar,
    "estado_usuario": usuarios.cambiar_estado,
    "historial_usuario": usuarios.historial,
    # fase 2: proyectos
    "proyectos": proyectos.listar,
    "proyecto": proyectos.obtener,
    "guardar_proyecto": proyectos.guardar,
    "duplicar_proyecto": proyectos.duplicar,
    "eliminar_proyecto": proyectos.eliminar,
    "restaurar_proyecto": proyectos.restaurar,
    "historial_proyecto": proyectos.historial,
    "usuarios_asignables": proyectos.usuarios_asignables,
    "geocodificar": proyectos.geocodificar,
    # fase 3: editor de red en el mapa
    "red_proyecto": red.red,
    "guardar_red": red.guardar,
    # fase 4: editor de mufa
    "mufa": mufa.leer,
    "guardar_mufa": mufa.guardar,
    # migración Visio, fase 4: modelo de la mufa y bandejas
    "guardar_modelo_mufa": bandejas.guardar_modelo,
    "mover_empalme": bandejas.mover_empalme,
    "bandeja_splitter": bandejas.bandeja_splitter,
    # migración Visio, fase 5: la red existente interactiva
    "mufa_existente": mufas_existentes.buscar,
    "validar_mufa": mufas_existentes.validar,
    "configurar_cable": mufas_existentes.configurar_cable,
    "red_de_mufas": mufas_existentes.red_de_mufas,
    # migración Visio, fase 6: tablero y cola de corrección
    "tablero_migracion": migracion_tablero.tablero,
    "correcciones_migracion": migracion_tablero.correcciones,
    "exportar_correcciones": migracion_tablero.exportar_correcciones,
    # fase 5: trazado de hilo
    "trazar_hilo": trazado.trazar,
    # fase 6: diagrama lógico de red
    "diagramas": diagrama.listar,
    "guardar_diagrama": diagrama.guardar,
    "eliminar_diagrama": diagrama.eliminar,
    "generar_diagrama": diagrama.generar,
    # fase 7: problemas, pendientes, backup y exportación
    "problemas": problemas.listar,
    "problema": problemas.obtener,
    "foto_problema": problemas.foto,
    "guardar_problema": problemas.guardar,
    "eliminar_problema": problemas.eliminar,
    "historial_problema": problemas.historial,
    "referencias_proyecto": problemas.referencias,
    "pendientes": pendientes.listar,
    "guardar_pendiente": pendientes.guardar,
    "eliminar_pendiente": pendientes.eliminar,
    "historial_pendiente": pendientes.historial,
    "respaldos": respaldo.listar,
    "crear_respaldo": respaldo.crear,
    "restaurar_respaldo": respaldo.restaurar,
    "descargar_respaldo": respaldo.descargar,
    "exportar_proyecto": respaldo.exportar,
    # sección 8: integridad de los datos
    "verificar_base": verificar.verificar,
}
# Methods that call Google: in remote mode they count for the person's hourly limit.
CON_LIMITE = {"geocodificar"}


class ServicioRedes:
    """One connection per process (re-opened if it breaks); calls are serialized with a lock.
    The missing migrations are applied the first time the database is used."""

    def __init__(self, conectar: Callable[[], Any] | None = None):
        self._conectar = conectar or db.conectar
        self._con: Any = None
        self._migrado = False
        self._lock = threading.Lock()

    def _conexion(self) -> Any:
        if self._con is not None and (self._con.closed or self._con.broken):
            self._con = None
        if self._con is None:
            self._con = self._conectar()
        if not self._migrado:
            migrar.aplicar(self._con)
            self._migrado = True
        return self._con

    def cerrar(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
            self._con = None

    def llamar(self, metodo: str, args: dict[str, Any] | None = None, *, persona_visor: str | None = None,
               usuario_windows: str | None = None) -> dict[str, Any]:
        funcion = METODOS.get(str(metodo or ""))
        if funcion is None:
            return {"ok": False, "error": f"Operación desconocida: {metodo}"}
        if args is not None and not isinstance(args, dict):
            return {"ok": False, "error": "Datos no válidos"}
        try:
            with self._lock:
                con = self._conexion()
                actor = usuarios.identificar(con, persona_visor=persona_visor, usuario_windows=usuario_windows)
                try:
                    resultado = funcion(con, actor, **(args or {}))
                except TypeError as exc:
                    if "argument" not in str(exc):
                        raise
                    log.warning("Redes: bad arguments for %s (%s)", metodo, exc)
                    return {"ok": False, "error": "Datos no válidos para esta operación"}
            return {"ok": True, **resultado}
        except db.ConflictoVersion as exc:
            return {"ok": False, "conflicto": True, "error": str(exc)}
        except db.DatosInvalidos as exc:
            return {"ok": False, "error": str(exc), "errores": exc.errores}
        except db.ErrorRedes as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, KeyError) as exc:
            log.warning("Redes: invalid data in %s (%s: %s)", metodo, type(exc).__name__, exc)
            return {"ok": False, "error": "Datos no válidos para esta operación"}
        except psycopg.Error as exc:
            log.exception("Redes: database error in %s", metodo)
            with self._lock:
                if self._con is not None and (self._con.closed or self._con.broken):
                    self._con = None
            return {"ok": False, "error": f"Error de la base de redes ({type(exc).__name__}). Detalle en el log."}
