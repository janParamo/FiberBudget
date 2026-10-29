"""Los postes ya no se agrupan en círculos con números (tapaban el mapa al alejarlo): ni los de la ruta (visor.js) ni los del KMZ (lugares.js)."""
import asyncio
import re
from pathlib import Path

import pytest

from arnes_pagina import hay_edge, pagina_edge

WEB = Path(__file__).resolve().parent.parent / "visor_rutas" / "web"


def test_no_pole_group_clusters_at_any_zoom_in_the_sources():
    for archivo in ("visor.js", "lugares.js"):
        texto = (WEB / archivo).read_text(encoding="utf-8")
        opciones = re.findall(r"disableClusteringAtZoom:\s*([^,\s]+)", texto)
        assert opciones and set(opciones) == {"1"}, (archivo, opciones)                 # 1 = grouping off from the lowest zoom
    assert "ZOOM_POSTES = 17" in (WEB / "lugares.js").read_text(encoding="utf-8")        # the KMZ posts show only close up, one by one


@pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")
def test_a_group_with_that_option_draws_every_marker_and_no_numbered_circle():
    async def recorrido():
        async with pagina_edge(1200, 800) as p:
            await p.esperar("window.visor && window.visor.mapa && window.L && L.markerClusterGroup", 20)
            n = await p.evaluar("""(() => { const m = window.visor.mapa; m.setView([12.13, -86.25], 12, {animate: false});
              const g = L.markerClusterGroup({ maxClusterRadius: 35, disableClusteringAtZoom: 1, showCoverageOnHover: false, spiderfyOnMaxZoom: false,
                iconCreateFunction: (c) => L.divIcon({ className: 'icono', html: '<div class="cluster-postes">' + c.getChildCount() + '</div>' }) });
              for (let i = 0; i < 60; i++) g.addLayer(L.marker([12.13 + i * 0.00002, -86.25]));
              g.addTo(m); return true; })()""")
            await asyncio.sleep(0.6)
            assert await p.evaluar("document.querySelectorAll('.cluster-postes').length") == 0
            assert await p.evaluar("document.querySelectorAll('#mapa .leaflet-marker-icon').length") >= 40               # each one is drawn
    asyncio.run(recorrido())
