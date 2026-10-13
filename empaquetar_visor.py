"""Genera dist\\VisorRutas\\VisorRutas.exe (modo remoto) y VisorRutas.zip para compartir.

Lo llama build_visor.bat:  .venv\\Scripts\\python.exe empaquetar_visor.py

Empaqueta SOLO lo del modo remoto: pywebview (WebView2), requests, openpyxl/Pillow (dibujar las
hojas del Excel descargado) y el código del visor (ventana_web, remoto, config_visor, excel_html,
remoto_main) con visor_rutas\\web (HTML, CSS, JS y lib\\ de Leaflet). Excluye el servicio (main,
db, routing, config...), FastAPI, psycopg y todo lo que lee bases o .env, y al final comprueba que
no quedó dentro ningún .env, base de datos, plantilla, regla de negocio ni salida.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
NOMBRE = "VisorRutas"
DIST = RAIZ / "dist"
BUILD = RAIZ / "build" / "visor"
ICONO = BUILD / "visor.ico"
ZIP = RAIZ / f"{NOMBRE}.zip"
ENTRADA = RAIZ / "visor_rutas" / "remoto_main.py"
WEB = RAIZ / "visor_rutas" / "web"

# The service and everything that reads databases / .env / Google: never in the .exe.
EXCLUIR = [
    "main", "db", "routing", "presupuesto", "excel_generator", "recalc", "pdf_export", "mapa_ruta",
    "red_fibra_pg", "origen", "config", "visor_api", "empaquetar_visor",
    "visor_rutas.calculo", "visor_rutas.fusion", "visor_rutas.red", "visor_rutas.presupuesto_visor",
    "visor_rutas.ventana", "visor_rutas.__main__", "visor_rutas.kmz_capas", "visor_rutas.redes",
    "fastapi", "starlette", "uvicorn", "pydantic", "pydantic_core", "psycopg", "psycopg_binary", "psycopg_pool",
    "ngrok", "dotenv", "yaml", "tenacity", "polyline", "staticmap", "tkintermapview", "tkinter",
    "pytest", "httpx", "pypdf", "anyio", "watchfiles", "websockets", "uvloop",
]
# Names that must not appear among the files of dist\VisorRutas, nor as bundled modules.
PROHIBIDOS_ARCHIVO = (".env", ".db", ".sqlite", "business_rules.yaml", "budget_index.json")
PROHIBIDAS_CARPETAS = ("red_fibra", "templates", "output", "visiomapas", "logs", "pruebas",
                       "red_kmz", "datos_kmz", "datos_kmz_iconos_google", "kmz_cache", "respaldos_redes")
PROHIBIDOS_MODULO = ("main", "db", "config", "routing", "psycopg", "fastapi", "visor_rutas.calculo",
                     "visor_rutas.presupuesto_visor", "red_fibra_pg", "visor_api", "visor_rutas.kmz_capas",
                     "visor_rutas.redes", "visor_rutas.redes.api", "visor_rutas.redes.db")

LEEME = """VISOR DE RUTAS – modo remoto
=============================

1. Descomprima esta carpeta "VisorRutas" en su carpeta de usuario, por ejemplo
   C:\\Users\\<su usuario>\\VisorRutas  (no hace falta ser administrador).
2. Doble clic en VisorRutas.exe. Si quiere, clic derecho -> Enviar a -> Escritorio (crear acceso directo).
3. La primera vez se abre "Configuración": escriba la URL del servidor de presupuestos y su
   clave personal (se las da quien administra el servidor), presione "Probar conexión" y "Guardar".
   La clave queda cifrada para su usuario de Windows. Para cambiarla: menú ☰ -> Configuración.

Requisitos: Windows 10/11 con Microsoft Edge WebView2 (ya viene instalado; si falta, el visor
muestra el enlace de descarga) y conexión a internet. Todos los cálculos se hacen en el servidor:
si dice "No se pudo conectar con el servidor de presupuestos", el servicio está apagado en la PC
del servidor o la URL cambió.

Los Excel / PDF que abra se descargan a %TEMP%\\VisorRutas\\descargas; use "Guardar Excel como…"
para guardarlos donde quiera. Registro de errores: %LOCALAPPDATA%\\VisorRutas\\visor.log

Panel "Lugares" (izquierda): la red del KMZ como en Google Earth. La primera vez la descarga del
servidor y la guarda en %APPDATA%\\VisorRutas\\kmz_cache (se actualiza sola cuando el servidor
tiene un KMZ nuevo). Las casillas que deje marcadas se guardan en %APPDATA%\\VisorRutas\\capas.json.
"""


def crear_icono() -> None:
    """Blue rounded square with a white map pin, in the sizes Windows uses."""
    from PIL import Image, ImageDraw
    lado = 256
    imagen = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rounded_rectangle((8, 8, lado - 8, lado - 8), radius=48, fill=(31, 111, 235, 255))
    dibujo.line([(40, 196), (100, 120), (150, 160), (216, 70)], fill=(255, 212, 0, 255), width=18, joint="curve")
    dibujo.ellipse((150, 36, 230, 116), fill=(255, 255, 255, 255))
    dibujo.polygon([(158, 92), (222, 92), (190, 150)], fill=(255, 255, 255, 255))
    dibujo.ellipse((174, 58, 206, 90), fill=(230, 30, 30, 255))
    ICONO.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(ICONO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def ejecutar_pyinstaller() -> None:
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", NOMBRE, "--icon", str(ICONO), "--paths", str(RAIZ),
               "--add-data", f"{WEB};visor_rutas/web",
               "--hidden-import", "visor_rutas.ventana_web", "--hidden-import", "visor_rutas.remoto",
               "--hidden-import", "visor_rutas.config_visor", "--hidden-import", "visor_rutas.excel_html",
               "--distpath", str(DIST), "--workpath", str(BUILD / "trabajo"), "--specpath", str(BUILD)]
    for modulo in EXCLUIR:
        comando += ["--exclude-module", modulo]
    comando.append(str(ENTRADA))
    print("PyInstaller:", " ".join(comando[:6]), "...")
    subprocess.run(comando, cwd=RAIZ, check=True)


def verificar(carpeta: Path) -> None:
    """Fails if a secret, database, template or the service code ended up in the package."""
    problemas = []
    for archivo in carpeta.rglob("*"):
        relativo = archivo.relative_to(carpeta)
        partes = [p.lower() for p in relativo.parts]
        if archivo.is_file() and (archivo.name.lower() in PROHIBIDOS_ARCHIVO
                                  or archivo.suffix.lower() in (".db", ".sqlite", ".kmz", ".kml", ".geojson")):
            problemas.append(str(relativo))
        if any(p in PROHIBIDAS_CARPETAS for p in partes[:-1] if p != "_internal"):
            problemas.append(str(relativo))
    toc = next((BUILD / "trabajo" / NOMBRE).glob("PYZ-*.toc"), None)
    if toc is not None:
        texto = toc.read_text(encoding="utf-8", errors="ignore")
        for modulo in PROHIBIDOS_MODULO:
            if f"('{modulo}'," in texto:
                problemas.append(f"módulo {modulo}")
    for pagina in ("visor.html", "visor.js", "lugares.js", "menu.js", "redes/comun.js", "redes/usuarios.js", "redes/redes.css",
                   "redes/proyectos.js", "redes/editor_mapa.js", "redes/editor_mufa.js", "redes/trazado.js", "redes/diagrama.js",
                   "redes/problemas.js", "redes/pendientes.js", "redes/respaldos.js", "lib/geoman/leaflet-geoman.js",
                   "lib/geoman/leaflet-geoman.css", "lib/quill/quill.js", "lib/quill/quill.snow.css", "lib/konva/konva.min.js"):
        if not (carpeta / "_internal" / "visor_rutas" / "web" / pagina).is_file():
            problemas.append(f"falta visor_rutas/web/{pagina}")
    if problemas:
        raise SystemExit("El paquete contiene cosas que no debe (o le falta algo):\n  " + "\n  ".join(problemas))
    print("Verificación: sin .env, bases, plantillas, reglas ni código del servicio.")


def comprimir(carpeta: Path) -> None:
    (carpeta / "LEEME.txt").write_text(LEEME, encoding="utf-8")
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as destino:
        for archivo in sorted(carpeta.rglob("*")):
            if archivo.is_file():
                destino.write(archivo, Path(NOMBRE) / archivo.relative_to(carpeta))
    print(f"{ZIP.name}: {ZIP.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("Falta PyInstaller:  .venv\\Scripts\\python.exe -m pip install pyinstaller")
    if not (WEB / "visor.html").is_file():
        raise SystemExit(f"No se encontró {WEB / 'visor.html'}")
    crear_icono()
    if (DIST / NOMBRE).exists():
        shutil.rmtree(DIST / NOMBRE)
    ejecutar_pyinstaller()
    carpeta = DIST / NOMBRE
    verificar(carpeta)
    comprimir(carpeta)
    print(f"Listo: {carpeta / (NOMBRE + '.exe')}  y  {ZIP}")


if __name__ == "__main__":
    main()
