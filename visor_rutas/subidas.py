"""Subida de archivos grandes por partes (visor v2, fase 7): un KMZ completo pesa 20 MB (unos 27 MB en base64) y no cabe cómodo en una sola petición por el túnel.

La página parte el archivo en pedazos de ~1,5 MB y los manda uno a uno (`iniciar` → `parte` ×N → `terminar`); al final queda un archivo listo en la memoria del
servicio con un id que no se puede adivinar. Quien lo usa (importar un KMZ a la red, leer las coordenadas masivas) pasa ese id en lugar del archivo y lo
`tomar`: se entrega una sola vez y se borra. Todo vive en la memoria del proceso (nada se escribe en disco) y caduca a los 30 minutos.

En modo local la página hace lo mismo contra este módulo; en modo remoto, contra `/visor/subidas/*` (visor_api.py) con la X-Visor-Key.
"""
import secrets
import threading
import time
from typing import Any

MAX_ARCHIVO = 40 * 1024 * 1024
MAX_PARTE = 4 * 1024 * 1024
MAX_ACTIVAS = 8
CADUCA_S = 30 * 60


class ErrorSubida(ValueError):
    """Mensaje claro para el usuario."""


class Subidas:
    def __init__(self) -> None:
        self._subidas: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _limpiar(self, ahora: float) -> None:
        for id_ in [k for k, s in self._subidas.items() if ahora - s["creada"] > CADUCA_S]:
            del self._subidas[id_]

    def _obtener(self, id_: str) -> dict[str, Any]:
        s = self._subidas.get(str(id_))
        if s is None:
            raise ErrorSubida("La subida ya no existe (caducó o se reinició el servicio): vuelva a elegir el archivo")
        return s

    def iniciar(self, nombre: str, tamano: int) -> str:
        try:
            tamano = int(tamano)
        except (TypeError, ValueError):
            raise ErrorSubida("Tamaño de archivo no válido") from None
        if tamano <= 0 or tamano > MAX_ARCHIVO:
            raise ErrorSubida(f"El archivo debe pesar hasta {MAX_ARCHIVO // (1024 * 1024)} MB")
        with self._lock:
            ahora = time.time()
            self._limpiar(ahora)
            if len(self._subidas) >= MAX_ACTIVAS:
                raise ErrorSubida("Hay demasiadas subidas en curso: espere unos minutos")
            id_ = secrets.token_urlsafe(12)
            self._subidas[id_] = {"nombre": str(nombre or "")[:200], "tamano": tamano, "partes": {}, "recibido": 0, "lista": False, "creada": ahora}
            return id_

    def parte(self, id_: str, numero: int, datos: bytes) -> int:
        """Stores part `numero` (0, 1, 2…); returns the bytes received so far. A part sent twice replaces the first."""
        if not datos or len(datos) > MAX_PARTE:
            raise ErrorSubida(f"Cada parte debe pesar hasta {MAX_PARTE // (1024 * 1024)} MB")
        with self._lock:
            s = self._obtener(id_)
            if s["lista"]:
                raise ErrorSubida("La subida ya terminó")
            numero = int(numero)
            if numero < 0 or numero > s["tamano"] // 1024 + 1:
                raise ErrorSubida("Número de parte no válido")
            s["recibido"] += len(datos) - len(s["partes"].get(numero, b""))
            if s["recibido"] > s["tamano"]:
                raise ErrorSubida("Llegó más de lo que se anunció")
            s["partes"][numero] = bytes(datos)
            return s["recibido"]

    def terminar(self, id_: str) -> dict[str, Any]:
        """Joins the parts (they must be 0..N-1 and add up to the announced size). The file is ready for `tomar`."""
        with self._lock:
            s = self._obtener(id_)
            numeros = sorted(s["partes"])
            if numeros != list(range(len(numeros))):
                raise ErrorSubida("Faltan partes del archivo: vuelva a subirlo")
            junto = b"".join(s["partes"][n] for n in numeros)
            if len(junto) != s["tamano"]:
                raise ErrorSubida(f"El archivo llegó incompleto ({len(junto)} de {s['tamano']} bytes): vuelva a subirlo")
            s.update(partes={}, datos=junto, lista=True)
            return {"id": str(id_), "nombre": s["nombre"], "tamano": s["tamano"]}

    def tomar(self, id_: str) -> tuple[str, bytes]:
        """(name, bytes) of a finished upload; it is handed over once and forgotten."""
        with self._lock:
            s = self._obtener(id_)
            if not s["lista"]:
                raise ErrorSubida("La subida todavía no terminó")
            del self._subidas[str(id_)]
            return s["nombre"], s["datos"]

    def reiniciar(self) -> None:
        with self._lock:
            self._subidas.clear()


almacen = Subidas()
