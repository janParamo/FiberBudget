"""Page tests of the viewer: headless Edge driven through the DevTools protocol, with a local HTTP server that
serves visor_rutas/web and bridges `window.pywebview.api.<method>(...)` to a Python object. The tests use an
`ApiPrueba` (the real Api with everything that touches PostgreSQL, Google or the user's profile replaced), so
they need neither the databases nor internet. Skipped when Edge or `websockets` is missing.

    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa")
        assert await p.evaluar("document.title")
"""
import asyncio
import base64
import contextlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "visor_rutas" / "web"
EDGES = (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
         Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"))

try:
    import websockets
except ImportError:                                      # pragma: no cover
    websockets = None


def ruta_edge() -> Path | None:
    return next((e for e in EDGES if e.is_file()), None)


def hay_edge() -> bool:
    return websockets is not None and ruta_edge() is not None


# Python side the page talks to: `window.__stubs[name]` answers in the page itself (no round trip);
# everything else goes to /_api/<name>. `window.__llamadas` lists the calls, in order.
SHIM = """
window.__stubs = {}; window.__llamadas = []; window.__errores = [];
window.pywebview = { api: new Proxy({}, { get: (t, n) => (...a) => {
  window.__llamadas.push(n);
  if (window.__stubs[n]) return Promise.resolve(window.__stubs[n](...a));
  return fetch('/_api/' + n, {method: 'POST', body: JSON.stringify(a)}).then(r => r.json()); } }) };
window.addEventListener('error', e => window.__errores.push(String(e.message) + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno));
window.addEventListener('unhandledrejection', e => window.__errores.push('promesa: ' + String(e.reason)));
"""


def crear_api_prueba(con=None, usuario="jgutierrez") -> object:
    """The real Api in local mode, with what needs the network, the databases or the user's profile stubbed.
    `con`: connection to a throw-away redes database (redes_base.con_redes): the network module then works for `usuario`."""
    from visor_rutas.redes.api import ServicioRedes
    from visor_rutas.ventana_web import Api, a_json
    servicio = ServicioRedes(conectar=lambda: con) if con is not None else None

    class ApiPrueba(Api):
        def kmz_arbol(self):
            return {"ok": False, "error": "prueba: sin KMZ"}

        def kmz_progreso(self):
            return {"activo": False}

        def capas_estado(self):
            return {"ok": True, "estado": {}}

        def guardar_capas_estado(self, estado):
            return {"ok": True}

        def preferencias(self):
            return {"ok": True, "preferencias": {}}

        def guardar_preferencias(self, cambios):
            return {"ok": True}

        def estado(self):
            return {"ok": True, "modo": "local", "fecha_red": None}

        def redes(self, metodo, args=None):
            if servicio is None:
                return {"ok": False, "error": "prueba: sin módulo de redes"}
            return a_json(servicio.llamar(str(metodo or ""), args if args is not None else {}, usuario_windows=usuario))

        def campo_escuchar(self):                     # the real one listens to the database: the tests send the notices to the page themselves
            return {"ok": True, "ya": False}

        def red(self, capa, oeste, sur, este, norte, zoom):
            return {"ok": True, "capa": capa, "elementos": [], "truncado": False, "zoom_min": 12, "debajo_del_zoom": False}

        def buscar_mufa(self, texto):
            return {"ok": True, "resultados": []}

    return ApiPrueba()


def _servidor(api):
    from visor_rutas.ventana_web import a_json

    class Manejador(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            nombre = self.path.rsplit("/", 1)[-1]
            n = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(n) or b"[]")
            try:
                r = getattr(api, nombre)(*args)
            except Exception as exc:                     # the page shows it like any failed call
                r = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            cuerpo = json.dumps(a_json(r), default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), partial(Manejador, directory=str(WEB)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


class Pagina:
    def __init__(self, ws):
        self.ws, self._id, self._esperando, self.consola = ws, 0, {}, []

    async def _leer(self):
        async for mensaje in self.ws:
            d = json.loads(mensaje)
            if "id" in d and d["id"] in self._esperando:
                self._esperando.pop(d["id"]).set_result(d)
            elif d.get("method") == "Runtime.exceptionThrown":
                det = d["params"]["exceptionDetails"]
                self.consola.append("EXC " + det.get("text", "") + " " + str(det.get("exception", {}).get("description", ""))[:300])

    async def enviar(self, metodo, **params):
        self._id += 1
        futuro = asyncio.get_event_loop().create_future()
        self._esperando[self._id] = futuro
        await self.ws.send(json.dumps({"id": self._id, "method": metodo, "params": params}))
        r = await asyncio.wait_for(futuro, 60)
        if "error" in r:
            raise RuntimeError(r["error"])
        return r["result"]

    async def evaluar(self, js):
        r = await self.enviar("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]["text"]))
        return r["result"].get("value")

    async def esperar(self, condicion, segundos=30):
        t0 = time.time()
        while time.time() - t0 < segundos:
            if await self.evaluar(f"!!({condicion})"):
                return True
            await asyncio.sleep(0.2)
        raise TimeoutError(condicion)

    async def captura(self, ruta):
        r = await self.enviar("Page.captureScreenshot", format="png")
        Path(ruta).write_bytes(base64.b64decode(r["data"]))

    async def mover(self, x, y):
        await self.enviar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    async def clic(self, x, y, boton="left", n=1):
        """Real mouse click (press + release `n` times in a row: n=2 is a double click)."""
        await self.mover(x, y)
        for i in range(1, n + 1):
            for tipo in ("mousePressed", "mouseReleased"):
                await self.enviar("Input.dispatchMouseEvent", type=tipo, x=x, y=y, button=boton, clickCount=i)

    async def clic_en(self, selector, boton="left", n=1, dx=0, dy=0):
        """Real mouse click at the centre of an element (CDP input events, not element.click())."""
        c = await self.cajas(x=selector)
        assert c["x"], f"{selector} no está visible"
        await self.clic(c["x"]["x"] + c["x"]["w"] / 2 + dx, c["x"]["y"] + c["x"]["h"] / 2 + dy, boton, n)

    async def subir_archivo(self, selector, ruta):
        """Puts a file in an <input type=file> (as if the user picked it)."""
        doc = await self.enviar("DOM.getDocument", depth=0)
        nodo = await self.enviar("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)
        await self.enviar("DOM.setFileInputFiles", files=[str(ruta)], nodeId=nodo["nodeId"])

    async def errores(self):
        return (await self.evaluar("window.__errores || []")) + self.consola

    async def cajas(self, **selectores):
        """{name: {x, y, w, h} | None} of the visible elements for each CSS selector."""
        return await self.evaluar("""((sel) => Object.fromEntries(Object.entries(sel).map(([k, s]) => {
          const e = document.querySelector(s); if (!e) return [k, null]; const b = e.getBoundingClientRect();
          return [k, b.width && b.height ? {x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height)} : null]; })))(%s)"""
                                  % json.dumps(selectores))


def se_cruzan(a, b) -> bool:
    return bool(a and b and a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


@contextlib.asynccontextmanager
async def pagina_edge(ancho=1366, alto=768, api=None, puerto=9333, con=None, usuario="jgutierrez", consulta=""):
    """The viewer open in headless Edge of `ancho` x `alto` pixels, started (api = ApiPrueba by default; `con` = test database;
    `consulta` = query string after visor.html, e.g. "?ventana=diagrama&nombre=MF X": a window of its own)."""
    api = api or crear_api_prueba(con, usuario)
    servidor = _servidor(api)
    perfil = tempfile.mkdtemp(prefix="edge_")
    proceso = subprocess.Popen([str(ruta_edge()), "--headless=new", f"--remote-debugging-port={puerto}", f"--window-size={ancho},{alto}",
                                f"--user-data-dir={perfil}", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                objetivos = json.load(urllib.request.urlopen(f"http://127.0.0.1:{puerto}/json"))
                destino = next(o for o in objetivos if o["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Edge no arrancó")
        async with websockets.connect(destino["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
            p = Pagina(ws)
            tarea = asyncio.create_task(p._leer())
            for dominio in ("Page", "Runtime"):
                await p.enviar(f"{dominio}.enable")
            await p.enviar("Emulation.setDeviceMetricsOverride", width=ancho, height=alto, deviceScaleFactor=1, mobile=False)
            await p.enviar("Page.addScriptToEvaluateOnNewDocument", source=SHIM)
            await p.enviar("Page.navigate", url=f"http://127.0.0.1:{servidor.server_address[1]}/visor.html{consulta}")
            await p.esperar("window.visor && window.visor.mapa", 40)
            yield p
            tarea.cancel()
    finally:
        proceso.terminate()
        try:
            proceso.wait(10)
        except Exception:
            proceso.kill()
        servidor.shutdown()
        shutil.rmtree(perfil, ignore_errors=True)
