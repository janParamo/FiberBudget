"""Configuración del visor en esta PC: %APPDATA%\\VisorRutas\\config.json.

  {"modo": "local" | "remoto", "url": "https://....ngrok-free.dev", "clave_dpapi": "<base64>"}

La clave X-Visor-Key se guarda cifrada con DPAPI de Windows (CryptProtectData): solo el mismo
usuario de Windows en la misma PC puede descifrarla; copiar el archivo a otra PC no sirve.
Solo usa la biblioteca estándar (ctypes, json): entra en el .exe del modo remoto.
"""
import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MODOS = ("local", "remoto")


def carpeta_usuario() -> Path:
    """%APPDATA%\\VisorRutas (config.json)."""
    base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "VisorRutas"


def carpeta_local() -> Path:
    """%LOCALAPPDATA%\\VisorRutas (log del .exe)."""
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "VisorRutas"


def archivo_config() -> Path:
    return carpeta_usuario() / "config.json"


# --------------------------------------------------------------------------- DPAPI

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(datos: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(datos, len(datos))
    return _Blob(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(datos: bytes, cifrar: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    entrada, _buffer = _blob(datos)
    salida = _Blob()
    funcion = crypt32.CryptProtectData if cifrar else crypt32.CryptUnprotectData
    ok = funcion(ctypes.byref(entrada), None, None, None, None, 0x01, ctypes.byref(salida))  # UI_FORBIDDEN
    if not ok:
        raise OSError(f"DPAPI falló (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(salida.pbData)


def cifrar(texto: str) -> str:
    return base64.b64encode(_dpapi(texto.encode("utf-8"), True)).decode("ascii")


def descifrar(texto: str) -> str:
    return _dpapi(base64.b64decode(texto), False).decode("utf-8")


# --------------------------------------------------------------------------- archivo

@dataclass
class ConfigVisor:
    modo: str = "local"
    url: str = ""
    clave: str = ""

    @property
    def remoto_completo(self) -> bool:
        return bool(self.url and self.clave)


def normalizar_url(url: str) -> str:
    """"broken-snowy....ngrok-free.dev" -> "https://broken-snowy....ngrok-free.dev" (sin / final)."""
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    return url


def leer(archivo: Path | None = None) -> ConfigVisor:
    """La configuración guardada; si no hay (o está dañada), la de por defecto (modo local)."""
    archivo = archivo or archivo_config()
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ConfigVisor()
    clave = ""
    if datos.get("clave_dpapi"):
        try:
            clave = descifrar(datos["clave_dpapi"])
        except (OSError, ValueError) as exc:
            log.warning("Visor config: the saved key could not be decrypted (%s); it must be typed again", exc)
    modo = datos.get("modo") if datos.get("modo") in MODOS else "local"
    return ConfigVisor(modo=modo, url=normalizar_url(datos.get("url", "")), clave=clave)


def guardar(config: ConfigVisor, archivo: Path | None = None) -> Path:
    archivo = archivo or archivo_config()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    datos = {"modo": config.modo if config.modo in MODOS else "local", "url": normalizar_url(config.url),
             "clave_dpapi": cifrar(config.clave) if config.clave else ""}
    temporal = archivo.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, archivo)
    return archivo
