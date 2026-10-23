"""App de campo: «Descargar esta zona» (visor_rutas/campo_web/zona.js) en un Edge de verdad: calcula y avisa cuántos mosaicos son, los guarda en la cache
«campo-zonas», sin señal el service worker los sirve desde ahí, se pueden borrar, y OpenStreetMap / mapas muy grandes se rechazan.
Los mosaicos de Esri se simulan (la prueba no usa internet): se reemplaza `window.fetch` solo para esas direcciones."""
import asyncio
import json

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import hay_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo_pwa import _dialogo, _entrar, _tocar, mundo, servidor_real, telefono, websockets  # noqa: F401
from test_visor_api import entorno  # noqa: F401  (fixture of the /visor/* API)

pytestmark = pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
FALSO_ESRI = """
(() => {
window.__pedidos = [];
const __fetch = window.fetch.bind(window);
window.__fetchReal = __fetch;
window.fetch = (u, o) => {
  const url = String(u && u.url || u);
  if (url.includes('arcgisonline.com')) {
    window.__pedidos.push(url);
    if (window.__fallar && window.__fallar(url)) return Promise.resolve(new Response('', { status: 503 }));
    const b = Uint8Array.from(atob('%s'), (c) => c.charCodeAt(0));
    return Promise.resolve(new Response(new Blob([b], { type: 'image/png' }), { status: 200, headers: { 'content-type': 'image/png' } }));
  }
  return __fetch(u, o);
};
})(); true
""" % PNG


async def _abrir_zona(p):
    await _tocar(p, "#b-menu")
    await p.esperar("!document.getElementById('p-menu').hidden", 5)
    await _tocar(p, "#m-zona")


async def _recorrido(puerto):
    async with telefono(puerto, precision=5.0) as p:
        await p.esperar("!document.getElementById('pantalla-clave').hidden", 10)
        await _entrar(p, "clave-jan")
        await p.esperar("!document.getElementById('app').hidden", 15)
        await p.esperar("navigator.serviceWorker.ready.then(() => true)", 20)
        await p.esperar("caches.keys().then((k) => k.includes('campo-v8'))", 20)
        await p.evaluar(FALSO_ESRI)

        # ---- too far out: the app asks to zoom in
        await p.evaluar("CampoMapa.leaflet().setView([12.13, -86.25], 9); true")
        await _abrir_zona(p)
        await p.esperar("!document.getElementById('aviso').hidden && document.getElementById('aviso').textContent.includes('Acerque')", 5)

        # ---- OpenStreetMap does not allow bulk downloads
        await p.evaluar("CampoMapa.leaflet().setView([12.13, -86.25], 15); CampoMapa.ponerCapa('calles'); true")
        await _abrir_zona(p)
        await p.esperar("document.getElementById('aviso').textContent.includes('OpenStreetMap')", 5)
        await p.evaluar("CampoMapa.ponerCapa('satelite'); true")

        # ---- the menu says there is nothing downloaded yet
        await _tocar(p, "#b-menu")
        assert "Mapa y red" in await p.evaluar("document.getElementById('m-zona-texto').textContent")
        await _tocar(p, "#m-zona")
        await p.esperar("!document.getElementById('dialogo').hidden", 5)
        titulo = await p.evaluar("document.getElementById('dlg-titulo').textContent")
        assert titulo == "Descargar esta zona"
        textos = await p.evaluar("[...document.querySelectorAll('#dlg-cuerpo label')].map((l) => l.textContent.replace(/\\s+/g, ' ').trim())")
        assert len(textos) == 3 and "Calles y postes" in textos[0] and "mosaicos" in textos[0] and "Con todo el detalle" in textos[1] and "Incluir mufas y postes" in textos[2]
        contados = await p.evaluar("(() => { const b = CampoMapa.leaflet().getBounds(); const c = {oeste: b.getWest(), sur: b.getSouth(), este: b.getEast(), norte: b.getNorth()}; "
                                   "return [Campo.zona.contar(c, 15, 19), Campo.zona.contar(c, 15, 18)]; })()")
        assert contados[0] > contados[1] > 0
        # download «Calles y postes» (at level 15 the choices are up to 17 and up to 18; the top level is 18)
        await _dialogo(p, "Descargar")
        await p.esperar("document.getElementById('dialogo').hidden", 60)
        await p.esperar("!document.getElementById('aviso').hidden && document.getElementById('aviso').textContent.includes('Zona lista')", 10)
        zonas = json.loads(await p.evaluar("localStorage.getItem('campo.zonas')"))
        assert len(zonas) == 1 and zonas[0]["capa"] == "satelite" and zonas[0]["parcial"] is False and zonas[0]["mosaicos"] > 0 and zonas[0]["zmax"] <= 18
        guardados = await p.evaluar("caches.open('campo-zonas').then((c) => c.keys()).then((k) => k.length)")
        assert guardados == zonas[0]["mosaicos"] and guardados == len(set(await p.evaluar("window.__pedidos")))
        assert all("World_Imagery" in u for u in await p.evaluar("window.__pedidos"))                # «satélite»: one layer
        # the fast cache that the service worker trims did not get a second copy of them
        assert await p.evaluar("caches.open('campo-mosaicos').then((c) => c.keys()).then((k) => k.length)") == 0

        # ---- the menu now shows what is stored
        await _tocar(p, "#b-menu")
        assert "1 zona" in await p.evaluar("document.getElementById('m-zona-texto').textContent")
        await _tocar(p, "#b-menu")

        # ---- no signal: the service worker answers a tile of the zone from the stored copy; one that was never downloaded gets nothing
        url = (await p.evaluar("window.__pedidos"))[0]
        fuera = url.replace("/tile/", "/tile/1/")                                                       # not in the zone
        await p.sin_red(True)
        await p.esperar("navigator.onLine === false", 10)
        await p.evaluar("window.fetch = window.__fetchReal; true")                                     # the real fetch, through the service worker
        # (the harness takes only the page offline; the service worker could still reach Esri, so «it came from the zone» is checked by the body:
        # the stored tile is the 1x1 test image, a real tile would be bigger)
        r = await p.evaluar(f"(async () => {{ const a = await fetch({json.dumps(url)}); const t = (await a.blob()).size; const b = await fetch({json.dumps(fuera)}).catch(() => ({{status: 0}})); return [a.status, a.headers.get('content-type'), t, b.status]; }})()")
        assert r[0] == 200 and "image" in r[1] and r[2] == 70 and r[3] != 200
        await p.sin_red(False)

        # ---- a second download of the same place asks for nothing again (they are already there)
        await p.evaluar(FALSO_ESRI)
        await _abrir_zona(p)
        await p.esperar("!document.getElementById('dialogo').hidden", 5)
        assert "toque para borrarla" in await p.evaluar("document.getElementById('dlg-cuerpo').textContent")
        await _dialogo(p, "Descargar")
        await p.esperar("document.getElementById('dialogo').hidden", 60)
        assert len(json.loads(await p.evaluar("localStorage.getItem('campo.zonas')"))) == 2
        assert await p.evaluar("window.__pedidos.length") == 0                                         # nothing was requested: all of it was already stored

        # ---- failing tiles: the zone is kept but marked incomplete, with a warning
        await p.evaluar(r"CampoMapa.leaflet().setView([12.20, -86.30], 16); window.__fallar = (u) => /\/17\/\d+\/\d*[02468]$/.test(u); true")
        await _abrir_zona(p)
        await _dialogo(p, "Descargar")
        await p.esperar("document.getElementById('dialogo').hidden", 60)
        zonas = json.loads(await p.evaluar("localStorage.getItem('campo.zonas')"))
        assert len(zonas) == 3 and zonas[2]["parcial"] is True and zonas[0]["parcial"] is False
        assert "no llegaron" in await p.evaluar("document.getElementById('aviso').textContent")
        assert "incompleta" in await p.evaluar("(() => { Campo.zona.abrir(); return new Promise((ok) => setTimeout(() => ok(document.getElementById('dlg-cuerpo').textContent), 300)); })()")
        await _dialogo(p, "Cancelar")

        # ---- deleting a zone frees its own tiles and keeps the ones another zone also needs
        async def en_cache():
            return await p.evaluar("caches.open('campo-zonas').then((c) => c.keys()).then((k) => k.length)")
        antes = await en_cache()
        n = await p.evaluar(f"Campo.zona.borrar({json.dumps(zonas[2]['id'])})")
        assert n > 0 and n == antes - await en_cache()
        antes = await en_cache()
        assert await p.evaluar(f"Campo.zona.borrar({json.dumps(zonas[0]['id'])})") == 0 and await en_cache() == antes        # the identical zone 2 still needs them
        assert len(json.loads(await p.evaluar("localStorage.getItem('campo.zonas')"))) == 1
        assert await p.evaluar("Campo.zona.borrar('no-existe')") == 0
        assert (await p.errores()) == []


def test_a_technician_downloads_a_zone_and_uses_it_without_signal(mundo):
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        asyncio.run(_recorrido(puerto))


def test_the_tile_arithmetic_matches_the_map(mundo):
    """The slippy-map formulas (checked with known tiles) and the size warning: no browser needed beyond evaluating the module."""
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        async def corrida():
            async with telefono(puerto, precision=5.0, cdp=9342) as p:
                await p.esperar("!document.getElementById('pantalla-clave').hidden", 10)
                await _entrar(p, "clave-jan")
                await p.esperar("!document.getElementById('app').hidden", 15)
                # Managua at level 12 is tile x=1066, y=1908 (Esri order in the address: z/y/x); one point is one tile and a bigger box more
                una = await p.evaluar("Campo.zona.contar({oeste: -86.2510, sur: 12.1360, este: -86.2509, norte: 12.1361}, 12, 12)")
                assert una == 1
                urls = await p.evaluar("Campo.zona.direcciones('hibrido', {oeste: -86.2510, sur: 12.1360, este: -86.2509, norte: 12.1361}, 12, 12)")
                assert len(urls) == 2 and "/tile/12/1908/1066" in urls[0] and "World_Transportation" in urls[1]
                assert await p.evaluar("Campo.zona.contar({oeste: -86.40, sur: 12.00, este: -86.10, norte: 12.30}, 12, 12)") > 4
                assert await p.evaluar("Campo.zona.permitida('satelite')") is True and await p.evaluar("Campo.zona.permitida('calles')") is False
        asyncio.run(corrida())
