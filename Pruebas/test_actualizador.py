"""Actualización automática del visor (visor_rutas/actualizador.py, /visor/actualizacion*, herramientas/publicar_visor.py y el arranque de remoto_main).

El visor .exe pregunta al servidor qué versión hay; si es más nueva avisa, descarga, verifica y un ayudante (.bat con robocopy) reemplaza el programa y lo abre.
"""
import hashlib
import io
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from test_visor_api import JAN, entorno  # noqa: F401  (fixture)
from visor_rutas import actualizador

RAIZ = Path(__file__).resolve().parents[1]


def _paquete(carpeta: Path, version: str = "2026.11.10.1500", extra: dict | None = None) -> Path:
    """A package like the real one: VisorRutas/VisorRutas.exe + version.json (+ files)."""
    zip_ = carpeta / "VisorRutas.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        z.writestr("VisorRutas/VisorRutas.exe", "exe " + version)
        z.writestr("VisorRutas/version.json", json.dumps({"version": version}))
        z.writestr("VisorRutas/_internal/datos.txt", "datos " + version)
        for nombre, contenido in (extra or {}).items():
            z.writestr(nombre, contenido)
    return zip_


def _publicar(carpeta: Path, version: str = "2026.11.10.1500") -> dict:
    carpeta.mkdir(parents=True, exist_ok=True)
    zip_ = _paquete(carpeta, version)
    datos = {"version": version, "sha256": hashlib.sha256(zip_.read_bytes()).hexdigest(), "tamano": zip_.stat().st_size, "creado": "2026-11-10T15:00:00"}
    (carpeta / "version.json").write_text(json.dumps(datos), encoding="utf-8")
    return datos


# --------------------------------------------------------------------------- versions

def test_versions_compare_as_numbers_and_only_a_newer_one_updates():
    assert actualizador.clave_version("2026.11.10.1530") == (2026, 11, 10, 1530) and actualizador.clave_version("abc") == () and actualizador.clave_version(None) == ()
    assert actualizador.es_nueva("2026.11.10.900", "2026.11.10.1530")                                  # 900 < 1530 as numbers, not as text
    assert not actualizador.es_nueva("2026.11.10.1530", "2026.11.10.1530") and not actualizador.es_nueva("2026.11.11.0001", "2026.11.10.2359")
    assert not actualizador.es_nueva(None, "2026.11.10.1530") and not actualizador.es_nueva("2026.11.10.1530", "x")      # no valid version: nothing is updated
    assert actualizador.clave_version(actualizador.nueva_version())


def test_the_installed_version_is_the_one_next_to_the_exe(tmp_path, monkeypatch):
    assert actualizador.version_instalada(tmp_path) is None                                            # an old build without version.json
    (tmp_path / "version.json").write_text(json.dumps({"version": "2026.11.10.1500"}), encoding="utf-8")
    assert actualizador.version_instalada(tmp_path) == "2026.11.10.1500"
    (tmp_path / "version.json").write_text("no es json", encoding="utf-8")
    assert actualizador.version_instalada(tmp_path) is None
    assert actualizador.carpeta_programa() is None                                                     # from the code (not the .exe) there is nothing to update


# --------------------------------------------------------------------------- the server

def test_the_published_version_is_offered_only_when_the_package_is_complete(tmp_path):
    assert actualizador.leer_publicada(tmp_path) is None
    datos = _publicar(tmp_path)
    assert actualizador.leer_publicada(tmp_path) == {"version": datos["version"], "sha256": datos["sha256"], "tamano": datos["tamano"], "creado": "2026-11-10T15:00:00"}
    (tmp_path / "VisorRutas.zip").write_bytes(b"a medias")                                             # half uploaded: its size does not match
    assert actualizador.leer_publicada(tmp_path) is None
    (tmp_path / "version.json").write_text(json.dumps({**datos, "sha256": "x"}), encoding="utf-8")
    assert actualizador.leer_publicada(tmp_path) is None


def test_the_service_offers_the_version_and_the_package_with_the_key_of_the_viewer(entorno, tmp_path, monkeypatch):
    _, _, cliente, _, _ = entorno
    carpeta = tmp_path / "actualizaciones"
    monkeypatch.setenv("VISOR_ACTUALIZACIONES_DIR", str(carpeta))
    assert cliente.get("/visor/actualizacion").status_code == 401 and cliente.get("/visor/actualizacion/paquete").status_code == 401
    assert cliente.get("/visor/actualizacion", headers=JAN).json() == {"ok": True, "disponible": False}                 # nothing published yet
    assert cliente.get("/visor/actualizacion/paquete", headers=JAN).status_code == 404
    datos = _publicar(carpeta)
    r = cliente.get("/visor/actualizacion", headers=JAN).json()
    assert r["ok"] and r["disponible"] and r["version"] == datos["version"] and r["sha256"] == datos["sha256"] and r["tamano"] == datos["tamano"]
    paquete = cliente.get("/visor/actualizacion/paquete", headers=JAN)
    assert paquete.status_code == 200 and hashlib.sha256(paquete.content).hexdigest() == datos["sha256"]


# --------------------------------------------------------------------------- the viewer: ask and download

class Respuesta:
    def __init__(self, datos=None, contenido=b"", falla_a_la_mitad=False):
        self._datos, self._contenido, self._falla = datos, contenido, falla_a_la_mitad
        self.cerrada = False

    def json(self):
        return self._datos

    def iter_content(self, chunk_size):
        mitad = len(self._contenido) // 2
        yield self._contenido[:mitad]
        if self._falla:
            raise ConnectionError("se cayó la conexión")
        yield self._contenido[mitad:]

    def close(self):
        self.cerrada = True


class Proveedor:
    """The remote provider of the viewer, with a server that publishes `datos` and the package `contenido`."""

    def __init__(self, datos=None, contenido=b"", falla=False, error=None):
        self.datos, self.contenido, self.falla, self.error, self.pedidas = datos, contenido, falla, error, []

    def _pedir(self, metodo, ruta, **kw):
        self.pedidas.append((metodo, ruta, kw.get("timeout")))
        if self.error:
            raise self.error
        if ruta == "/visor/actualizacion":
            return Respuesta(self.datos)
        self.ultima = Respuesta(contenido=self.contenido, falla_a_la_mitad=self.falla)
        return self.ultima


def _servidor(version="2026.11.10.1500", **kw):
    contenido = b"x" * 1000
    datos = {"ok": True, "disponible": True, "version": version, "sha256": hashlib.sha256(contenido).hexdigest(), "tamano": len(contenido)}
    return Proveedor(datos, contenido, **kw)


def test_the_viewer_asks_and_only_a_newer_version_comes_back():
    assert actualizador.consultar(_servidor("2026.11.10.1500"), "2026.11.10.1400")["version"] == "2026.11.10.1500"
    assert actualizador.consultar(_servidor("2026.11.10.1500"), "2026.11.10.1500") is None                 # up to date
    assert actualizador.consultar(_servidor("2026.11.10.1500"), "2026.11.11.0900") is None                 # the installed one is newer
    assert actualizador.consultar(Proveedor({"ok": True, "disponible": False}), "2026.11.10.1400") is None  # nothing published
    assert actualizador.consultar(Proveedor({"ok": True, "disponible": True, "version": "2026.11.10.1500", "sha256": "mal"}), "2026.11.10.1400") is None


def test_the_download_is_checked_and_a_damaged_one_is_deleted(tmp_path):
    servidor = _servidor()
    info = actualizador.consultar(servidor, "2026.11.10.1400")
    destino = actualizador.descargar(servidor, info, tmp_path / "x" / "p.zip")
    assert destino.read_bytes() == b"x" * 1000 and servidor.ultima.cerrada
    mala = _servidor()
    mala.contenido = b"y" * 1000                                                                          # arrives, but it is not what was published
    with pytest.raises(actualizador.ErrorActualizacion, match="dañada"):
        actualizador.descargar(mala, info, tmp_path / "mala.zip")
    assert not (tmp_path / "mala.zip").exists()
    cortada = _servidor(falla=True)
    with pytest.raises(actualizador.ErrorActualizacion, match="cortó"):
        actualizador.descargar(cortada, info, tmp_path / "cortada.zip")
    assert not (tmp_path / "cortada.zip").exists()


# --------------------------------------------------------------------------- the replacement

def test_the_package_is_unzipped_checked_and_refused_when_it_is_not_what_it_says(tmp_path):
    paquete = _paquete(tmp_path)
    script, nuevo = actualizador.preparar(paquete, tmp_path / "programa", tmp_path / "trabajo", "2026.11.10.1500")
    assert (nuevo / "VisorRutas.exe").is_file() and (nuevo / "_internal" / "datos.txt").is_file() and script.name == "actualizar.bat" and "robocopy" in script.read_text(encoding="utf-8")
    with pytest.raises(actualizador.ErrorActualizacion, match="versión"):
        actualizador.preparar(paquete, tmp_path / "programa", tmp_path / "trabajo2", "2030.01.01.0000")      # not the version the server announced
    sin_exe = tmp_path / "sin_exe.zip"
    with zipfile.ZipFile(sin_exe, "w") as z:
        z.writestr("VisorRutas/otra_cosa.txt", "x")
    with pytest.raises(actualizador.ErrorActualizacion, match="programa"):
        actualizador.preparar(sin_exe, tmp_path / "programa", tmp_path / "trabajo3", "2026.11.10.1500")
    malo = tmp_path / "malo.zip"
    with zipfile.ZipFile(malo, "w") as z:
        z.writestr("../fuera.txt", "x")                                                                    # a path out of the folder
    with pytest.raises(actualizador.ErrorActualizacion, match="no es válido"):
        actualizador.preparar(malo, tmp_path / "programa", tmp_path / "trabajo4", "2026.11.10.1500")
    assert not (tmp_path / "fuera.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="el ayudante es un .bat de Windows")
def test_the_helper_replaces_the_program_keeps_the_rest_and_opens_it_again(tmp_path):
    programa = tmp_path / "VisorRutas"
    (programa / "_internal").mkdir(parents=True)
    exe = shutil.which("whoami") or r"C:\Windows\System32\whoami.exe"
    shutil.copyfile(exe, programa / "VisorRutas.exe")                                                         # a harmless program that ends at once
    (programa / "version.json").write_text(json.dumps({"version": "2026.11.10.1400"}), encoding="utf-8")
    (programa / "_internal" / "datos.txt").write_text("viejo", encoding="utf-8")
    (programa / "_internal" / "solo_del_usuario.txt").write_text("se queda", encoding="utf-8")
    trabajo = tmp_path / "trabajo"
    paquete = _paquete(tmp_path, extra={"VisorRutas/_internal/nuevo.txt": "nuevo"})
    # the package carries the same «exe» (so that «start» opens something harmless)
    with zipfile.ZipFile(paquete, "a") as z:
        z.writestr("VisorRutas/VisorRutas.exe", Path(exe).read_bytes())
    script, nuevo = actualizador.preparar(paquete, programa, trabajo, "2026.11.10.1500")
    fallo = tmp_path / "fallo.json"
    resultado = subprocess.run(["cmd", "/c", str(script), str(nuevo), str(programa), "99999999", str(fallo), "2026.11.10.1500"], capture_output=True, timeout=60)   # no such process: it does not wait
    assert resultado.returncode == 0
    assert actualizador.version_instalada(programa) == "2026.11.10.1500"                                          # replaced
    assert (programa / "_internal" / "datos.txt").read_text(encoding="utf-8") == "datos 2026.11.10.1500" and (programa / "_internal" / "nuevo.txt").read_text() == "nuevo"
    assert (programa / "_internal" / "solo_del_usuario.txt").read_text() == "se queda"                            # what the package does not have stays
    assert not fallo.exists() and not nuevo.exists() and not list(trabajo.glob("*.zip"))                           # no failure, and the work files are cleaned


def test_the_helper_is_started_apart_from_the_viewer(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(actualizador.subprocess, "Popen", lambda cmd, **kw: llamadas.append((cmd, kw)))
    actualizador.lanzar(tmp_path / "a.bat", tmp_path / "n", tmp_path / "p", tmp_path / "f.json", "2026.11.10.1500", pid=4321)
    cmd, kw = llamadas[0]
    assert cmd[:3] == ["cmd", "/c", str(tmp_path / "a.bat")] and cmd[5] == "4321" and cmd[-1] == "2026.11.10.1500" and kw["close_fds"] is True


# --------------------------------------------------------------------------- when the viewer opens

def _al_abrir(tmp_path, servidor, instalada="2026.11.10.1400", monkeypatch=None, **kw):
    programa = tmp_path / "programa"
    programa.mkdir(exist_ok=True)
    avisos, lanzados = [], []
    if monkeypatch:
        monkeypatch.setattr(actualizador, "lanzar", lambda *a, **k: lanzados.append(a))
    hecho = actualizador.actualizar_al_abrir(servidor, avisos.append, tmp_path / "trabajo", tmp_path / "fallo.json", programa=programa, instalada=instalada, **kw)
    return hecho, avisos, lanzados


def test_on_opening_it_tells_downloads_and_starts_the_update(tmp_path, monkeypatch):
    contenido = _paquete(tmp_path).read_bytes()
    servidor = Proveedor({"ok": True, "disponible": True, "version": "2026.11.10.1500", "sha256": hashlib.sha256(contenido).hexdigest(), "tamano": len(contenido)}, contenido)
    hecho, avisos, lanzados = _al_abrir(tmp_path, servidor, monkeypatch=monkeypatch)
    assert hecho is True and len(avisos) == 1 and "2026.11.10.1500" in avisos[0] and "actualizar" in avisos[0].lower() and len(lanzados) == 1
    assert [p[:2] for p in servidor.pedidas] == [("GET", "/visor/actualizacion"), ("GET", "/visor/actualizacion/paquete")]


def test_on_opening_nothing_happens_when_it_is_up_to_date_or_cannot_ask(tmp_path, monkeypatch):
    assert _al_abrir(tmp_path, _servidor("2026.11.10.1400"), monkeypatch=monkeypatch)[:2] == (False, [])        # same version: it does not even tell
    assert _al_abrir(tmp_path, Proveedor(error=ConnectionError("sin red")), monkeypatch=monkeypatch)[:2] == (False, [])    # the server is off: it opens as it is
    assert _al_abrir(tmp_path, _servidor(), instalada=None, monkeypatch=monkeypatch)[:2] == (False, [])        # from the code / an old build: nothing to compare


def test_on_opening_a_failed_download_is_told_and_the_viewer_opens_as_it_is(tmp_path, monkeypatch):
    servidor = _servidor()
    servidor.contenido = b"y" * 1000                                                                          # damaged
    hecho, avisos, lanzados = _al_abrir(tmp_path, servidor, monkeypatch=monkeypatch)
    assert hecho is False and lanzados == [] and len(avisos) == 2 and "dañada" in avisos[1] and "versión actual" in avisos[1]


def test_a_version_that_failed_is_not_tried_again_the_same_day(tmp_path, monkeypatch):
    (tmp_path / "fallo.json").write_text(json.dumps({"version": "2026.11.10.1500"}), encoding="utf-8")
    assert _al_abrir(tmp_path, _servidor("2026.11.10.1500"), monkeypatch=monkeypatch)[:2] == (False, [])
    assert actualizador.fallo_reciente(tmp_path / "fallo.json", "2026.11.10.1500") and not actualizador.fallo_reciente(tmp_path / "fallo.json", "2026.11.12.0900")
    assert not actualizador.fallo_reciente(tmp_path / "fallo.json", "2026.11.10.1500", ahora=time.time() + 2 * 86400)    # a day later it is tried again


def test_a_folder_that_cannot_be_written_is_told_to_ask_for_the_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(actualizador, "carpeta_escribible", lambda c: False)
    hecho, avisos, lanzados = _al_abrir(tmp_path, _servidor(), monkeypatch=monkeypatch)
    assert hecho is False and lanzados == [] and len(avisos) == 1 and "instalador" in avisos[0]


# --------------------------------------------------------------------------- the packaging and the publishing

def test_publishing_writes_the_version_with_the_size_and_the_checksum_of_the_package(tmp_path):
    sys.path.insert(0, str(RAIZ / "herramientas"))
    import publicar_visor
    zip_ = _paquete(tmp_path)
    salida = tmp_path / "actualizaciones"
    datos = publicar_visor.preparar(zip_, salida)
    assert datos["version"] == "2026.11.10.1500" and datos["tamano"] == zip_.stat().st_size and datos["sha256"] == hashlib.sha256(zip_.read_bytes()).hexdigest()
    assert actualizador.leer_publicada(salida)["version"] == "2026.11.10.1500"                              # what the server will read from it
    sin_version = tmp_path / "viejo.zip"
    with zipfile.ZipFile(sin_version, "w") as z:
        z.writestr("VisorRutas/VisorRutas.exe", "x")
    with pytest.raises(SystemExit):
        publicar_visor.version_del_zip(sin_version)                                                          # a package without version.json is not published


def test_the_packaging_writes_version_json_next_to_the_exe(tmp_path):
    sys.path.insert(0, str(RAIZ / "herramientas"))
    import empaquetar_visor
    version = empaquetar_visor.escribir_version(tmp_path)
    assert actualizador.version_instalada(tmp_path) == version and actualizador.clave_version(version)
