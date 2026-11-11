"""Compresion gzip de las respuestas JSON del servicio.

Una carga grande (Mis lugares ~1 MB, una carpeta del KMZ) por el tunel de ngrok se cortaba a mitad de camino y el visor decia «No se pudo conectar con el servidor». Comprimida
queda en una decima parte: menos tiempo en el aire, menos probabilidad de que se corte y menos datos del tunel.

Solo comprime lo que es application/json y llega entero (no los avisos en tiempo real —text/event-stream—, ni las fotos, los Excel, los PDF o el paquete del visor, que ya van
comprimidos o salen por partes) y solo si quien llama lo acepta (Accept-Encoding: gzip). Lo pequeno (menos de MINIMO bytes) no se comprime.
"""
import gzip

from starlette.datastructures import Headers, MutableHeaders

MINIMO = 1024


class GzipJson:
    def __init__(self, app, minimo: int = MINIMO, nivel: int = 5):
        self.app, self.minimo, self.nivel = app, minimo, nivel

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", "").lower():
            await self.app(scope, receive, send)
            return
        inicio: dict = {}
        partes: list[bytes] = []
        comprimir = False

        async def enviar(mensaje):
            nonlocal inicio, comprimir
            if mensaje["type"] == "http.response.start":
                cabeceras = Headers(raw=mensaje["headers"])
                comprimir = cabeceras.get("content-type", "").lower().startswith("application/json") and "content-encoding" not in cabeceras
                if comprimir:
                    inicio = mensaje                                   # held until the whole body is here
                    return
                await send(mensaje)
                return
            if mensaje["type"] != "http.response.body" or not comprimir:
                await send(mensaje)
                return
            partes.append(mensaje.get("body", b""))
            if mensaje.get("more_body"):
                return
            cuerpo = b"".join(partes)
            cabeceras = MutableHeaders(raw=list(inicio["headers"]))
            if len(cuerpo) >= self.minimo:
                cuerpo = gzip.compress(cuerpo, compresslevel=self.nivel)
                cabeceras["content-encoding"] = "gzip"
                cabeceras.add_vary_header("Accept-Encoding")
            cabeceras["content-length"] = str(len(cuerpo))
            await send({**inicio, "headers": cabeceras.raw})
            await send({"type": "http.response.body", "body": cuerpo})

        await self.app(scope, receive, enviar)
