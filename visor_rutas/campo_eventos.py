"""Avisos en tiempo real de la app de campo: PostgreSQL `LISTEN campo` (el trigger de la migración 017 hace NOTIFY en cada cambio).

Un solo hilo con su propia conexión escucha y reparte cada aviso ({tabla, id, cambio, usuario_id}) a quien se suscribió:
  - el servicio (visor_api / campo_api): a cada visor remoto conectado por Server-Sent Events (GET /visor/campo/eventos);
  - el visor de escritorio en la PC del servidor (modo local): directamente, para avisar a su página.
Si la conexión se cae, reconecta sola con espera creciente. El hilo arranca con el primer suscriptor y termina cuando se va el último.
"""
import json
import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

ESPERA_MIN_S, ESPERA_MAX_S = 1.0, 30.0
SONDEO_S = 5.0                     # how often the listening loop looks at the stop flag


class Escucha:
    """`conectar()` returns an autocommit psycopg connection (db.conectar)."""

    def __init__(self, conectar: Callable[[], Any]):
        self._conectar = conectar
        self._suscriptores: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self.conectado = threading.Event()          # set while LISTEN is active (tests wait for it)

    def suscribir(self, funcion: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Calls `funcion(aviso)` from the listening thread for every notification. Returns the function that unsubscribes."""
        with self._lock:
            self._suscriptores.append(funcion)
            if self._hilo is None or not self._hilo.is_alive():
                self._parar.clear()
                self._hilo = threading.Thread(target=self._bucle, name="campo-escucha", daemon=True)
                self._hilo.start()

        def quitar() -> None:
            with self._lock:
                if funcion in self._suscriptores:
                    self._suscriptores.remove(funcion)
                if not self._suscriptores:
                    self._parar.set()
        return quitar

    def _repartir(self, aviso: dict[str, Any]) -> None:
        with self._lock:
            destinos = list(self._suscriptores)
        for f in destinos:
            try:
                f(aviso)
            except Exception:                                       # noqa: BLE001 - one bad subscriber must not stop the others
                log.exception("Campo: a subscriber failed")

    def _bucle(self) -> None:
        espera = ESPERA_MIN_S
        while not self._parar.is_set():
            con = None
            try:
                con = self._conectar()
                con.execute("LISTEN campo")
                self.conectado.set()
                espera = ESPERA_MIN_S
                while not self._parar.is_set():
                    for n in con.notifies(timeout=SONDEO_S):
                        try:
                            self._repartir(json.loads(n.payload))
                        except ValueError:
                            log.warning("Campo: notification that is not JSON ignored")
                        if self._parar.is_set():
                            break
            except Exception as exc:                                # noqa: BLE001 - the database went away: try again
                log.warning("Campo: listening stopped (%s: %s); retrying in %.0f s", type(exc).__name__, str(exc).strip()[:120], espera)
                self.conectado.clear()
                if self._parar.wait(espera):
                    break
                espera = min(ESPERA_MAX_S, espera * 2)
            finally:
                self.conectado.clear()
                if con is not None:
                    try:
                        con.close()
                    except Exception:                               # noqa: BLE001
                        pass
        log.info("Campo: listening ended")


_escucha: Escucha | None = None
_lock = threading.Lock()


def escucha() -> Escucha:
    """The listener of this process (the real database: redes.db.conectar)."""
    global _escucha
    with _lock:
        if _escucha is None:
            from visor_rutas.redes import db
            _escucha = Escucha(db.conectar)
        return _escucha


def reiniciar() -> None:
    """Tests: forget the listener (it stops when its last subscriber leaves)."""
    global _escucha
    with _lock:
        _escucha = None
