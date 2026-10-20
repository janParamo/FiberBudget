"""Visor v2, fase 9, en la página real (Edge sin ventana, base desechable, un KMZ de mentira): una mufa y un splitter en el MISMO punto (el clic ofrece
cuál), ícono y color propio de un elemento y de toda una carpeta (el del elemento gana), estilo de una línea, quitar el estilo, y que sigue ahí al
abrir otra vez. Además el botón «Lugares» a la misma altura que «Resumen»."""
import asyncio
import json

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_visor_pagina_fase3 import mundo  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


def _carpeta(id_, nombre, geometria, directos, padre="raiz", estilo=None):
    return {"id": id_, "nombre": nombre, "ruta": f"Red/{nombre}", "padre": padre, "hijos": [], "directos": directos, "total": directos, "geometria": geometria,
            "bbox": [-86.27, 12.12, -86.24, 12.15], "estilo": estilo, "troncal": False, "postes": False, "visible": True, "etiquetas": False, "visibilidad_kml": None}


CARPETAS = {
    "raiz": {"id": "raiz", "nombre": "Red", "ruta": "Red", "padre": None, "hijos": ["m1", "m2", "l1"], "directos": 0, "total": 5, "geometria": "mixta", "bbox": None,
             "estilo": None, "troncal": False, "postes": False, "visible": True, "etiquetas": False, "visibilidad_kml": None},
    "m1": _carpeta("m1", "MUFA", "punto", 2, estilo={"tipo": "punto", "color": "#ff8800", "radio": 7}),
    "m2": _carpeta("m2", "SPLITTER", "punto", 1, estilo={"tipo": "punto", "color": "#00aa00", "radio": 7}),
    "l1": _carpeta("l1", "FIBRA", "linea", 1, estilo={"tipo": "linea", "color": "#0000ff", "grosor": 2}),
}
PUNTO = lambda lon, lat, n: {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"n": n, "e": 0}}   # noqa: E731
CAPAS = {
    "m1": {"type": "FeatureCollection", "carpeta": "m1", "estilos": [{"tipo": "punto", "color": "#ff8800", "radio": 7}],
           "features": [PUNTO(-86.2500, 12.1300, "MF UNO"), PUNTO(-86.2560, 12.1360, "MF DOS")]},
    "m2": {"type": "FeatureCollection", "carpeta": "m2", "estilos": [{"tipo": "punto", "color": "#00aa00", "radio": 7}],
           "features": [PUNTO(-86.2500, 12.1300, "SPLITTER UNO")]},                                   # on top of MF UNO
    "l1": {"type": "FeatureCollection", "carpeta": "l1", "estilos": [{"tipo": "linea", "color": "#0000ff", "grosor": 2}],
           "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-86.2540, 12.1310], [-86.2545, 12.1320]]}, "properties": {"n": "C1 CLIENTE", "e": 0}}]},   # away from the points: no click is ambiguous
}


def _api(con):
    api = crear_api_prueba(con)
    api.kmz_arbol = lambda: {"ok": True, "arbol": {"version": 1, "kmz": "prueba.kmz", "importado": "hoy", "raiz": "raiz", "carpetas": CARPETAS, "elementos": 4, "aviso": ""}, "iconos": {}}
    api.kmz_capa = lambda cid: {"ok": True, "capa": CAPAS[cid]}
    api.kmz_indice = lambda: {"ok": True, "indice": {}}
    return api


async def _pixel(p, lat, lon, dy=0):
    return await p.evaluar("(() => { const m = window.visor.mapa, q = m.latLngToContainerPoint([%s, %s]), r = m.getContainer().getBoundingClientRect(); return [r.left + q.x, r.top + q.y + %s]; })()" % (lat, lon, dy))


async def _abrir(p):
    await p.esperar("window.MisLugares && window.MisLugares.estado.listo && window.Lugares.estado.cargadas.includes('m1')", 45)
    await p.evaluar("window.visor.mapa.setView([12.133, -86.253], 16, {animate: false}); true")
    await asyncio.sleep(0.5)


async def _clic(p, lat, lon, dy=0):
    """A real click on a point (circles and figures are centred on their coordinate)."""
    await p.evaluar("window.visor.mapa.closePopup(); true")
    await p.esperar("!document.querySelector('.lg-popup')", 5)
    x, y = await _pixel(p, lat, lon, dy)
    await p.clic(x, y)
    await p.esperar("document.querySelector('.lg-popup')", 10)


async def _elegir_icono(p, figura, color):
    await p.esperar("!document.getElementById('ml-iconos').hidden", 5)
    await p.evaluar("""(() => { const c = [...document.querySelectorAll('#ml-iconos [data-ic]')].find(b => JSON.parse(b.dataset.ic).id === '%s'); c.click();
      const i = document.getElementById('ml-ic-color'); i.value = '%s'; i.dispatchEvent(new Event('input', {bubbles: true}));
      document.querySelector('[data-ml-ic=aceptar]').click(); return true; })()""" % (figura, color))


ITEMS = "(() => { const o = {}; window.Lugares.porCadaItem(({it}) => { o[it.f.properties.n] = it; }); return o; })()"


def _estado(nombre):
    """What the page has for an element: is it a plain KMZ marker or one with an icon of its own, and which colour."""
    return f"""(() => {{ let it; window.Lugares.porCadaItem(({{it: x}}) => {{ if (x.f.properties.n === {json.dumps(nombre)}) it = x; }});
      const o = it.capa.options || {{}}; const ic = o.icon && o.icon.options && o.icon.options.html || '';
      return {{propio: it.capa !== it.capaBase, color: (ic.match(/fill="(#[0-9a-f]{{6}})"/i) || [])[1] || null, forma: ic.includes('<polygon') ? 'poligono' : (ic.includes('<rect') ? 'rect' : 'otro'),
              enMapa: window.Lugares._s.capas.get(it.c.id).grupo.hasLayer(it.capa), linea: it.linea ? {{color: it.linea.options.color, weight: it.linea.options.weight}} : null}}; }})()"""


async def _recorrido(mundo):
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    api = _api(con)
    async with pagina_edge(1366, 768, api=api) as p:
        await _abrir(p)
        # ---- «Lugares» a la misma altura que «Resumen»
        await p.evaluar("document.getElementById('lg-plegar').click(); document.getElementById('panel').hidden = true; document.getElementById('abrir-panel').hidden = false; true")
        cajas = await p.cajas(lugares="#abrir-lugares", resumen="#abrir-panel")
        assert cajas["lugares"] and cajas["resumen"], cajas
        assert cajas["lugares"]["y"] == cajas["resumen"]["y"] and cajas["lugares"]["h"] == cajas["resumen"]["h"], cajas          # same height
        await p.evaluar("document.getElementById('abrir-lugares').click(); true")
        # ---- una mufa y un splitter en el mismo punto: el clic ofrece cuál (cada fila abre su propio popup)
        await _clic(p, 12.13, -86.25)
        assert "2 elementos aquí" in await p.evaluar("document.querySelector('.lg-popup h3').innerText")
        filas = await p.evaluar("[...document.querySelectorAll('.lg-sup')].map(b => b.innerText.replace(/\\s+/g, ' ').trim())")
        assert len(filas) == 2 and any("SPLITTER UNO" in f for f in filas) and any("MF UNO" in f for f in filas), filas
        # ... and the same two open like a fan around the point (below it, each joined by a thin line); a click on one opens that one
        assert await p.evaluar("document.querySelectorAll('.lg-abanico').length") == 2
        assert await p.evaluar("document.querySelectorAll('.leaflet-kmzEtiquetas-pane path').length") == 2           # the two legs
        caja = await p.evaluar("(() => { const r = document.querySelector('.lg-abanico').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        centro = await _pixel(p, 12.13, -86.25)
        assert caja[1] > centro[1] + 10 and abs(caja[0] - centro[0]) > 20, (caja, centro)                                                          # below the point: the list stays above
        await p.clic(caja[0], caja[1])
        await p.esperar("document.querySelector('.lg-popup h3') && !document.querySelector('.lg-popup h3').innerText.includes('elementos aquí')", 5)
        assert await p.evaluar("document.querySelector('.lg-popup h3').innerText") in ("MF UNO", "SPLITTER UNO")
        await p.esperar("document.querySelectorAll('.lg-abanico').length === 0", 3)                              # the fan folds when one is chosen
        await _clic(p, 12.13, -86.25)                                                                              # again: the list, for the rest of the test
        await p.evaluar("[...document.querySelectorAll('.lg-sup')].find(b => b.innerText.includes('SPLITTER UNO')).click(); true")
        await p.esperar("document.querySelector('.lg-popup h3') && document.querySelector('.lg-popup h3').innerText.includes('SPLITTER UNO')", 5)
        await p.esperar("document.querySelectorAll('.lg-abanico').length === 0", 3)
        botones = await p.evaluar("[...document.querySelectorAll('.lg-popup button')].map(b => b.innerText)")
        assert {"Renombrar", "Mover", "Cambiar ícono…", "Eliminar"} <= set(botones), botones            # «Mover» is how they are separated
        # ---- ícono propio del splitter: una estrella roja
        await p.evaluar("document.querySelector('.lg-popup [data-kc=estilo]').click(); true")
        await _elegir_icono(p, "estrella", "#e53935")
        await p.esperar("window.KmzCambios.estilos.size === 1", 10)
        fila = consulta("SELECT clave, alcance, estilo FROM redes.kmz_estilos")[0]
        assert fila["alcance"] == "elemento" and "splitter uno" in fila["clave"] and fila["estilo"]["icono"]["id"] == "estrella" and fila["estilo"]["icono"]["color"] == "#e53935"
        e = await p.evaluar(_estado("SPLITTER UNO"))
        assert e["propio"] is True and e["color"] == "#e53935" and e["enMapa"] is True, e
        assert (await p.evaluar(_estado("MF UNO")))["propio"] is False                                    # the mufa under it is untouched
        # ---- estilo de toda la carpeta MUFA: cuadrados verdes; MF UNO lo toma, el del elemento (splitter) no cambia
        await p.evaluar("window.KmzCambios.estiloCarpeta('m1'); true")
        await _elegir_icono(p, "cuadrado", "#00a651")
        await p.esperar("window.KmzCambios.estilos.size === 2", 10)
        for nombre in ("MF UNO", "MF DOS"):
            e = await p.evaluar(_estado(nombre))
            assert e["propio"] is True and e["color"] == "#00a651" and e["enMapa"] is True, (nombre, e)
        assert (await p.evaluar(_estado("SPLITTER UNO")))["color"] == "#e53935"
        # a mufa with an icon of its own opens its popup as ever (Entrar a la mufa…) and the stack still lists both
        await _clic(p, 12.136, -86.256, dy=0)
        assert "MF DOS" in await p.evaluar("document.querySelector('.lg-popup h3').innerText")
        assert "Entrar a la mufa" in await p.evaluar("document.querySelector('.lg-popup').innerText")
        await _clic(p, 12.13, -86.25)
        assert "2 elementos aquí" in await p.evaluar("document.querySelector('.lg-popup h3').innerText")
        # ---- estilo de una línea (la carpeta FIBRA): azul → naranja y más gruesa
        await p.evaluar("window.visor.mapa.closePopup(); window.KmzCambios.estiloCarpeta('l1'); true")
        await p.esperar("!document.getElementById('kc-linea').hidden", 5)
        await p.evaluar("document.getElementById('kl-color').value = '#ff8800'; document.getElementById('kl-grosor').value = '6'; document.querySelector('[data-kl=aceptar]').click(); true")
        await p.esperar("window.KmzCambios.estilos.size === 3", 10)
        assert (await p.evaluar(_estado("C1 CLIENTE")))["linea"] == {"color": "#ff8800", "weight": 6}
        # ---- quitar: el elemento vuelve al marcador del KMZ y la carpeta también
        await _clic(p, 12.13, -86.25)
        await p.evaluar("[...document.querySelectorAll('.lg-sup')].find(b => b.innerText.includes('SPLITTER UNO')).click(); true")
        await p.esperar("document.querySelector('.lg-popup [data-kc=estilo_quitar]')", 5)
        await p.evaluar("document.querySelector('.lg-popup [data-kc=estilo_quitar]').click(); true")
        await p.esperar("window.KmzCambios.estilos.size === 2", 10)
        assert (await p.evaluar(_estado("SPLITTER UNO")))["propio"] is False
        await p.evaluar("window.KmzCambios.quitarEstiloCarpeta('l1'); true")
        await p.esperar("window.KmzCambios.estilos.size === 1", 10)
        assert (await p.evaluar(_estado("C1 CLIENTE")))["linea"] == {"color": "#0000ff", "weight": 2}      # the KMZ's own again
        assert consulta("SELECT count(*) AS n FROM redes.kmz_estilos WHERE borrado_en IS NULL")[0]["n"] == 1
        assert await p.errores() == []
    # ---- al abrir otra vez el estilo de la carpeta sigue ahí (es de todos, está en la base)
    async with pagina_edge(1366, 768, api=_api(con)) as p:
        await _abrir(p)
        await p.esperar("window.KmzCambios.estilos.size === 1", 15)
        for nombre in ("MF UNO", "MF DOS"):
            e = await p.evaluar(_estado(nombre))
            assert e["propio"] is True and e["color"] == "#00a651", (nombre, e)
        assert (await p.evaluar(_estado("SPLITTER UNO")))["propio"] is False
        assert await p.errores() == []


def test_icons_of_their_own_overlapping_points_and_lugares_button(mundo):
    asyncio.run(_recorrido(mundo))


async def _imagen_y_texto(mundo, tmp_path):
    from PIL import Image
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    Image.new("RGBA", (300, 200), (220, 30, 30, 255)).save(tmp_path / "logo.png")
    (tmp_path / "no_es_imagen.txt").write_text("hola")
    async with pagina_edge(1366, 768, api=_api(con)) as p:
        await _abrir(p)
        # ---- imagen propia en MF DOS: se reduce, se ve en el mapa y se guarda
        await _clic(p, 12.136, -86.256)
        await p.evaluar("document.querySelector('.lg-popup [data-kc=estilo]').click(); true")
        await p.esperar("!document.getElementById('ml-iconos').hidden", 5)
        await p.subir_archivo("#ml-ic-archivo", tmp_path / "logo.png")
        await p.esperar("document.getElementById('ml-iconos-vista').innerHTML.includes('<image')", 5)
        assert await p.evaluar("document.getElementById('ml-ic-error').textContent") == ""
        await p.evaluar("document.querySelector('[data-ml-ic=aceptar]').click(); true")
        await p.esperar("window.KmzCambios.estilos.size === 1", 10)
        icono = consulta("SELECT estilo FROM redes.kmz_estilos")[0]["estilo"]["icono"]
        assert icono["tipo"] == "imagen" and icono["datos"].startswith("data:image/png;base64,") and len(icono["datos"]) < 80000 and icono["escala"] == 1.6
        html = await p.evaluar("(() => { let h; window.Lugares.porCadaItem(({it}) => { if (it.f.properties.n === 'MF DOS') h = it.capa.options.icon.options.html; }); return h; })()")
        assert '<image href="data:image/png;base64,' in html
        # ---- texto / emoji en SPLITTER UNO; algo no permitido se rechaza con un aviso
        await p.evaluar("window.visor.mapa.closePopup(); true")
        await _clic(p, 12.13, -86.25)
        await p.evaluar("[...document.querySelectorAll('.lg-sup')].find(b => b.innerText.includes('SPLITTER UNO')).click(); true")
        await p.esperar("document.querySelector('.lg-popup [data-kc=estilo]')", 5)
        await p.evaluar("document.querySelector('.lg-popup [data-kc=estilo]').click(); true")
        await p.esperar("!document.getElementById('ml-iconos').hidden", 5)
        await p.evaluar("document.getElementById('ml-ic-texto').value = '<b>'; document.querySelector('[data-ml-ic=usar_texto]').click(); true")
        assert "1 a 3 caracteres" in await p.evaluar("document.getElementById('ml-ic-error').textContent")
        await p.evaluar("document.getElementById('ml-ic-texto').value = '5G'; document.querySelector('[data-ml-ic=usar_texto]').click(); true")
        assert "5G" in await p.evaluar("document.getElementById('ml-iconos-vista').innerHTML")
        await p.evaluar("document.querySelector('[data-ml-ic=aceptar]').click(); true")
        await p.esperar("window.KmzCambios.estilos.size === 2", 10)
        assert any(f["estilo"]["icono"]["tipo"] == "texto" and f["estilo"]["icono"]["id"] == "5G" for f in consulta("SELECT estilo FROM redes.kmz_estilos"))
        assert ">5G<" in await p.evaluar("(() => { let h; window.Lugares.porCadaItem(({it}) => { if (it.f.properties.n === 'SPLITTER UNO') h = it.capa.options.icon.options.html; }); return h; })()")
        # ---- un archivo que no es imagen no cambia nada
        await p.evaluar("window.visor.mapa.closePopup(); true")
        await _clic(p, 12.136, -86.256)
        await p.evaluar("document.querySelector('.lg-popup [data-kc=estilo]').click(); true")
        await p.esperar("!document.getElementById('ml-iconos').hidden", 5)
        await p.subir_archivo("#ml-ic-archivo", tmp_path / "no_es_imagen.txt")
        await p.esperar("document.getElementById('ml-ic-error').textContent !== ''", 5)
        await p.evaluar("document.querySelector('[data-ml-ic=cancelar]').click(); true")
        assert await p.errores() == []
    # ---- al abrir otra vez siguen las dos (la imagen viaja con el estilo)
    async with pagina_edge(1366, 768, api=_api(con)) as p:
        await _abrir(p)
        await p.esperar("window.KmzCambios.estilos.size === 2", 15)
        assert '<image href="data:image/png' in await p.evaluar("(() => { let h; window.Lugares.porCadaItem(({it}) => { if (it.f.properties.n === 'MF DOS') h = it.capa.options.icon.options.html; }); return h; })()")
        assert await p.errores() == []


def test_own_image_or_text_as_the_icon(mundo, tmp_path):
    asyncio.run(_imagen_y_texto(mundo, tmp_path))
