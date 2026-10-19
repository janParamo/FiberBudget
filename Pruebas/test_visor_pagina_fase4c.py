"""Visor v2, fase 4B (ruta editable y presupuesto en vivo), en la página real (Edge sin ventana) con `calcular`, `calcular_con_ruta` y
`estimar_presupuesto` simulados: editar los puntos de la ruta recalcula solo, un poste a mano también, dibujar una ruta a mano la va
calculando mientras se dibuja, y «Volver a la de Google» vuelve a la ruta de la coordenada."""
import asyncio
import json

import pytest

from arnes_pagina import hay_edge, pagina_edge
from test_visor_pagina_fase1 import DATOS

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

STUBS = """
window.__datos = %(datos)s; window.__ediciones = []; window.__estimaciones = [];
window.__stubs.calcular = () => ({ok: true, datos: window.__datos, coordenada: '12.153000, -86.263000'});
window.__stubs.calcular_con_ruta = (lat, lon, pts, extra) => {
  window.__ediciones.push({lat, lon, pts, extra});
  const d = JSON.parse(JSON.stringify(window.__datos));
  const cli = lat === null ? {lat: pts[pts.length - 1][0], lon: pts[pts.length - 1][1]} : {lat, lon};
  d.cliente = cli; d.ruta.puntos = pts; d.ruta.manual = true; d.ruta.distancia_m = 100 * pts.length; d.ruta.metraje_final_m = 100 * pts.length + 40;
  d.postes_nuevos.cantidad += extra;
  return {ok: true, datos: d, coordenada: cli.lat.toFixed(6) + ', ' + cli.lon.toFixed(6)};
};
window.__stubs.estimar_presupuesto = (lat, lon, metraje, marcas, ruta, extra) => {
  window.__estimaciones.push({lat, lon, metraje, marcas, ruta, extra});
  return {ok: true, supuestos: {service_type: 'Residencial', bandwidth: '10 Mbps', technology: 'gpon', cable: 'Flat', metraje_final_m: metraje, umbral_m: 600, postes_marcados: 0},
          campos: {}, resultado: {calculado: true, archivo: 'x.xlsx', avisos: [], resumen: {totales: [{clave: 'total', etiqueta: 'TOTAL', valor: metraje * 10}], secciones: []}}};
};
"""


async def _pixel(p, lat, lon):
    return await p.evaluar("(() => { const m = window.visor.mapa, q = m.latLngToContainerPoint([%s, %s]), r = m.getContainer().getBoundingClientRect(); return [r.left + q.x, r.top + q.y]; })()" % (lat, lon))


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.EditarRuta && window.visor && window.visor.mapa", 20)
        await p.evaluar(STUBS % {"datos": json.dumps(DATOS)})
        await p.evaluar("document.getElementById('coord').value = '12.153, -86.263'; document.getElementById('generar').click(); true")
        await p.esperar("window.visor.datos && window.__estimaciones.length === 1", 15)
        assert (await p.evaluar("window.__estimaciones[0]"))["ruta"] is None                   # Google's route: nothing to inject
        assert "Editar ruta" in await p.evaluar("document.getElementById('tarjetas').innerText")
        # ---- editar la ruta: se arrastra un punto (aquí, el cambio que Geoman avisa) y todo se recalcula solo
        await p.evaluar("document.querySelector('[data-er=editar]').click(); true")
        await p.esperar("window.EditarRuta.modo === 'editar'", 5)
        await p.evaluar("(() => { const c = window.EditarRuta._capa; const pts = c.getLatLngs(); pts[1] = L.latLng(12.1520, -86.2640); c.setLatLngs(pts); c.fire('pm:edit'); return true; })()")
        await p.esperar("window.__ediciones.length === 1 && window.__estimaciones.length === 2", 10)
        e = await p.evaluar("window.__ediciones[0]")
        assert e["lat"] == pytest.approx(12.153) and e["extra"] == 0 and e["pts"][1] == pytest.approx([12.152, -86.264])
        est = await p.evaluar("window.__estimaciones[1]")
        assert est["ruta"][1] == pytest.approx([12.152, -86.264]) and est["extra"] == 0 and est["metraje"] == 340            # the budget of the edited route
        texto = await p.evaluar("document.getElementById('tarjetas').innerText")
        assert "Ruta editada a mano" in texto and "340" in texto
        await p.esperar("/60,?0?0|C\\$ 3,400/.test(document.body.innerText) || document.body.innerText.includes('3,400')", 10)
        # ---- un poste a mano: clic en el mapa; cuenta como nuevo y recalcula
        await p.evaluar("document.querySelector('[data-er=poste]').click(); true")
        await p.esperar("window.EditarRuta.modo === 'poste'", 5)
        x, y = await _pixel(p, 12.1518, -86.2625)
        await p.clic(x, y)
        await p.esperar("window.__ediciones.length === 2 && window.__estimaciones.length === 3", 10)
        assert (await p.evaluar("window.__ediciones[1].extra")) == 1 and (await p.evaluar("window.__estimaciones[2].extra")) == 1
        assert await p.evaluar("window.EditarRuta.postes") == 1
        assert "1 poste(s) a mano" in await p.evaluar("document.getElementById('tarjetas').innerText")
        await p.evaluar("document.querySelector('[data-er=terminar]').click(); true")
        assert await p.evaluar("window.EditarRuta.modo") is None
        # ---- volver a la de Google: la ruta de la coordenada otra vez, sin ediciones
        await p.evaluar("document.querySelector('[data-er=google]').click(); true")
        await p.esperar("window.EditarRuta.editada === false && window.__estimaciones.length === 4", 15)
        assert (await p.evaluar("window.__estimaciones[3]"))["ruta"] is None and await p.evaluar("window.EditarRuta.postes") == 0
        assert "Editar ruta" in await p.evaluar("document.getElementById('tarjetas').innerText") and "editada a mano" not in await p.evaluar("document.getElementById('tarjetas').innerText")
        # ---- dibujar una ruta a mano: se calcula mientras se dibuja y al terminar queda en edición
        await p.evaluar("window.visor.mapa.setView([12.20, -86.30], 16, {animate: false}); true")
        await asyncio.sleep(0.4)
        n0 = await p.evaluar("window.__ediciones.length")
        await p.clic_en("#ruta-mano")
        await p.esperar("window.EditarRuta.modo === 'dibujar'", 5)
        for dx, dy in ((-300, 0), (-200, -20), (-100, 40)):
            x, y = await _pixel(p, 12.20, -86.30)
            await p.clic(x + dx, y + dy)
            await asyncio.sleep(0.8)
        await p.esperar("window.__ediciones.length >= %d" % (n0 + 2), 10)          # after the 2nd and the 3rd point
        ultima = await p.evaluar("window.__ediciones[window.__ediciones.length - 1]")
        assert ultima["lat"] is None and len(ultima["pts"]) == 3 and ultima["extra"] == 0
        x, y = await _pixel(p, 12.20, -86.30)
        await p.clic(x - 20, y + 40, n=2)
        await p.esperar("window.EditarRuta.modo === 'editar'", 10)
        assert await p.evaluar("window.EditarRuta._capa.getLatLngs().length") == 4
        assert "Ruta dibujada a mano" in await p.evaluar("document.getElementById('tarjetas').innerText")
        assert await p.errores() == []


def test_editar_ruta_postes_a_mano_y_ruta_dibujada():
    asyncio.run(_recorrido())
