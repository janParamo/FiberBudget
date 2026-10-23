r"""Revisa que la app de campo responda bien desde una dirección (la pública del túnel de Cloudflare, o http://localhost:8000).

    .\.venv\Scripts\python.exe herramientas\verificar_campo.py https://api.fiberbudget.com  CLAVE_DE_UN_TECNICO

Sin dirección usa CAMPO_URL_PUBLICA del .env. La clave es opcional: con ella también se prueba el acceso de la persona (rol de técnico) y, si es de
un administrador o editor, el canal de avisos en tiempo real. Termina con código 0 si todo lo necesario está bien, 1 si algo falla.
"""
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # `config` (el .env del proyecto) vive en la raiz, no en herramientas/

ARCHIVOS = (("/campo/", "text/html"), ("/campo/app.js", "javascript"), ("/campo/sw.js", "javascript"), ("/campo/manifest.webmanifest", "json"),
            ("/campo/icono-192.png", "image/png"), ("/campo/icono-512.png", "image/png"), ("/campo/lib/leaflet/leaflet.js", "javascript"))


def verificar(base: str, clave: str | None = None, sesion: Any = None, con_eventos: bool = True, espera_s: float = 8.0) -> list[tuple[str, bool, str]]:
    """[(prueba, ok, detalle)]. `sesion` has .get(url, headers=, timeout=, stream=) (requests, or a test client)."""
    sesion = sesion or requests
    base = base.rstrip("/")
    cabeceras = {"X-Visor-Key": clave, "ngrok-skip-browser-warning": "1"} if clave else {"ngrok-skip-browser-warning": "1"}
    filas: list[tuple[str, bool, str]] = []

    def hecho(nombre: str, ok: bool, detalle: str = "") -> None:
        filas.append((nombre, bool(ok), detalle))

    hecho("Dirección segura (https)", base.startswith("https://") or "://localhost" in base or "://127.0.0.1" in base,
          "" if base.startswith("https://") else "sin https el teléfono no instala la app ni da el GPS (solo vale en la propia PC)")
    for ruta, tipo in ARCHIVOS:
        try:
            t0 = time.monotonic()
            r = sesion.get(base + ruta, headers=cabeceras, timeout=espera_s)
            tipo_real = r.headers.get("content-type", "")
            hecho(f"GET {ruta}", r.status_code == 200 and tipo in tipo_real, f"{r.status_code} {tipo_real.split(';')[0]} · {1000 * (time.monotonic() - t0):.0f} ms"
                  + ("" if r.status_code != 200 else " (¿página de aviso del túnel?)" if "text/html" in tipo_real and ruta != "/campo/" else ""))
            if ruta.endswith("manifest.webmanifest") and r.status_code == 200:
                m = json.loads(r.text)
                hecho("El manifest manda a /campo/", m.get("start_url") == "/campo/" and m.get("display") == "standalone", f"start_url={m.get('start_url')}")
        except Exception as exc:                                             # noqa: BLE001 - every failure is a line of the report
            hecho(f"GET {ruta}", False, f"{type(exc).__name__}: {str(exc)[:100]}")
    if clave:
        try:
            r = sesion.get(base + "/visor/campo/config", headers=cabeceras, timeout=espera_s)
            datos = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            hecho("La clave entra", r.status_code == 200, f"persona {datos.get('persona')}" if r.status_code == 200 else
                  {401: "clave no válida", 403: "sin el rol de técnico", 404: "VISOR_API_KEYS y CAMPO_API_KEYS vacíos en el servidor"}.get(r.status_code, str(r.status_code)))
            if r.status_code == 200:
                hecho("La dirección pública del servidor coincide", not datos.get("url_publica") or base == datos["url_publica"].rstrip("/"),
                      f"CAMPO_URL_PUBLICA={datos.get('url_publica') or '(vacía)'}")
        except Exception as exc:                                             # noqa: BLE001
            hecho("La clave entra", False, f"{type(exc).__name__}: {str(exc)[:100]}")
        if con_eventos:
            try:
                with sesion.get(base + "/visor/campo/eventos", headers={**cabeceras, "Accept": "text/event-stream"}, timeout=(espera_s, espera_s), stream=True) as r:
                    if r.status_code == 403:
                        hecho("Avisos en tiempo real", True, "omitido: la clave es de un técnico (solo administradores y editores los reciben)")
                    else:
                        primera = next(iter(r.iter_lines(decode_unicode=True)), None) if r.status_code == 200 else None
                        hecho("Avisos en tiempo real (SSE)", r.status_code == 200 and primera is not None, f"{r.status_code} {primera or ''}")
            except Exception as exc:                                         # noqa: BLE001
                hecho("Avisos en tiempo real (SSE)", False, f"{type(exc).__name__}: {str(exc)[:100]}")
    return filas


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else ""
    if not base:
        try:
            from config import get_settings
            base = get_settings().campo_url_publica
        except Exception:                                                    # noqa: BLE001
            base = ""
    if not base:
        print("Indique la dirección: herramientas\verificar_campo.py https://api.fiberbudget.com [clave]  (o ponga CAMPO_URL_PUBLICA en .env)")
        return 2
    filas = verificar(base, argv[2] if len(argv) > 2 else None)
    for nombre, ok, detalle in filas:
        print(f"[{'OK' if ok else 'FALLA'}] {nombre}{' – ' + detalle if detalle else ''}")
    malas = [f for f in filas if not f[1]]
    print(f"\n{len(filas) - len(malas)} de {len(filas)} pruebas bien" + ("" if not malas else f"; {len(malas)} fallan: revise docs/campo/CLOUDFLARE.md"))
    return 1 if malas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
