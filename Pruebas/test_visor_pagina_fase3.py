"""Visor v2, fase 3 (docs/modulo_redes/ESPECIFICACION.md §4), en la página real (Edge sin ventana, arnes_pagina.py) con una base de
datos desechable: Mis lugares en el árbol de Lugares, la barra de herramientas, la ventana flotante de una marca / ruta / polígono,
edición de vértices en el mapa, casillas, arrastrar y soltar, exportar e importar KMZ, compartir, el buscador y que todo siga ahí
al abrir el visor de nuevo."""
import asyncio
import base64
import io
import json
import zipfile

import pytest

from arnes_pagina import hay_edge, pagina_edge, se_cruzan
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import db, lugares, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

KML = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Del campo</name>
<Folder><name>Postes</name><Placemark><name>Poste A</name><Point><coordinates>-86.31,12.13,0</coordinates></Point></Placemark>
<Placemark><name>Cable B</name><LineString><coordinates>-86.31,12.13,0 -86.32,12.14,0</coordinates></LineString></Placemark></Folder></Document></kml>"""


@pytest.fixture
def mundo(base_redes, con_redes):
    """(con de la página, con para consultar sin chocar con ella, admin, luis): luis recibirá carpetas compartidas."""
    admin = usuarios.identificar(con_redes, usuario_windows="jgutierrez")
    luis = usuarios.identificar(con_redes, usuario_windows="luis")
    lectura = db.conectar(params=base_redes[1])
    yield con_redes, lectura, admin, luis
    lectura.close()


async def _filas(p):
    return await p.evaluar("[...document.querySelectorAll('#lg-filas .lg-fila[data-ext]')].map(f => ({k: f.dataset.ml, texto: f.innerText.trim().replace(/\\s+/g, ' '), vacia: f.classList.contains('vacia')}))")


async def _menu(p, fila, texto):
    """Right click on a row of the tree and choose an item of its menu."""
    await p.evaluar("""((sel) => { const f = document.querySelector(sel); f.scrollIntoView({block: 'nearest'}); const r = f.getBoundingClientRect();
      f.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: r.left + 60, clientY: r.top + 8})); return true; })(%s)""" % json.dumps(f'[data-ml="{fila}"]'))
    await p.esperar("document.querySelector('.ml-menu')", 5)
    items = await p.evaluar("[...document.querySelectorAll('.ml-menu li[data-i]')].map(li => [li.innerText, li.classList.contains('ml-deshabilitado')])")
    if texto is None:
        await p.evaluar("document.querySelector('.ml-menu').remove(); true")
        return items
    await p.evaluar("([...document.querySelectorAll('.ml-menu li')].find(li => li.innerText === %s)).click()" % json.dumps(texto))
    return items


async def _texto_pedido(p, valor):
    await p.esperar("document.getElementById('ml-pedir') && !document.getElementById('ml-pedir').hidden", 5)
    await p.evaluar("document.getElementById('ml-pedir-valor').value = %s; document.getElementById('ml-pedir-form').requestSubmit()" % json.dumps(valor))
    await p.esperar("!document.getElementById('ml-pedir') || document.getElementById('ml-pedir').hidden", 5)


async def _esperar_carga(p, carpetas, elementos):
    await p.esperar(f"window.MisLugares.estado.carpetas === {carpetas} && window.MisLugares.estado.elementos === {elementos}", 10)


async def _plegar_secciones(p):
    await p.evaluar("document.querySelectorAll('[data-sec-expandir]').forEach((f) => f.click()); true")      # the layers sections out of the way


async def _arrastrar(p, origen, destino, zona="dentro"):
    await p.evaluar("""((o, d, z) => { const a = document.querySelector(o), b = document.querySelector(d), dt = new DataTransfer();
      a.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt}));
      const r = b.getBoundingClientRect(), y = r.top + r.height * (z === 'antes' ? 0.1 : z === 'despues' ? 0.9 : 0.5);
      for (const tipo of ['dragover', 'drop']) b.dispatchEvent(new DragEvent(tipo, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: r.left + 40, clientY: y}));
      a.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt})); return true; })(%s, %s, %s)""" % (json.dumps(origen), json.dumps(destino), json.dumps(zona)))


async def _ventana_marca(p, nombre, lat=None):
    await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
    await p.evaluar("document.getElementById('ml-d-nombre').value = %s" % json.dumps(nombre))
    if lat is not None:
        await p.evaluar("document.getElementById('ml-d-lat').value = %s; document.getElementById('ml-d-lat').dispatchEvent(new Event('change', {bubbles: true}))" % json.dumps(lat))


async def _aceptar(p):
    await p.evaluar("document.getElementById('ml-d-form').requestSubmit()")
    await p.esperar("!document.getElementById('ml-dialogo') || document.getElementById('ml-dialogo').hidden", 10)


async def _dibujar(p, puntos, doble=True):
    for x, y in puntos:
        await p.clic(x, y)
    if doble:
        await p.clic(*puntos[-1], n=2)
    await asyncio.sleep(0.6)


async def _recorrido_dueno(mundo, tmp_path):
    con, lectura, admin, luis = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo", 20)
        await _plegar_secciones(p)
        # ---- la barra de herramientas: arriba, sin pisar al buscador; lo que no es de esta fase, deshabilitado y con su razón
        botones = await p.evaluar("[...document.querySelectorAll('#barra-herramientas [data-bh]')].map(b => [b.dataset.bh, b.getAttribute('aria-disabled') === 'true', b.title])")
        assert [b[0] for b in botones] == ["marca", "poligono", "ruta", "medir", "mufa", "poste", "cliente", "nodo", "odf", "cable", "importar", "masivas"]
        assert [b[0] for b in botones if b[1]] == [] and "Coordenadas masivas" in botones[11][2]
        cajas = await p.cajas(barra="#barra-herramientas", buscador="#buscador", zoom=".leaflet-control-zoom", lugares="#lugares", abajo="#barra")
        assert cajas["barra"]["y"] >= cajas["buscador"]["y"] + cajas["buscador"]["h"] and not se_cruzan(cajas["barra"], cajas["buscador"])
        assert not se_cruzan(cajas["barra"], cajas["lugares"]) and not se_cruzan(cajas["barra"], cajas["zoom"])
        # ---- carpetas: la raíz, una carpeta y una subcarpeta (clic derecho)
        assert [f["texto"] for f in await _filas(p)] == ["▾ Mis lugares"]
        items = await _menu(p, "r", "Nueva carpeta")
        assert [i[0] for i in items] == ["Nueva carpeta", "Importar KMZ…", "Encuadrar todo"]
        await _texto_pedido(p, "Visita Nandaime")
        await _esperar_carga(p, 1, 0)
        visita = consulta("SELECT id FROM redes.lugares_carpetas")[0]["id"]
        items = await _menu(p, f"c:{visita}", "Nueva carpeta")
        assert [i[0] for i in items if i[0]][:5] == ["Nueva carpeta", "Agregar marca de posición aquí", "Agregar ruta", "Agregar polígono", "Agregar mufa"]
        assert ("Guardar como proyecto…", False) in [tuple(i) for i in items]
        await _texto_pedido(p, "Postes")
        await _esperar_carga(p, 2, 0)
        postes = consulta("SELECT id FROM redes.lugares_carpetas WHERE nombre = 'Postes'")[0]["id"]
        # ---- marca de posición: botón de la barra, un clic en el mapa; la ventana se abre con la posición y el pincho se arrastra
        await p.clic_en('[data-bh="marca"]')
        assert "clic en el mapa" in await p.evaluar("document.getElementById('ml-ayuda').textContent")
        await p.clic(800, 420)
        await _ventana_marca(p, "Cliente Pérez")
        lat0 = float(await p.evaluar("document.getElementById('ml-d-lat').value"))
        assert 10.7 < lat0 < 15.1 and await p.evaluar("document.getElementById('ml-d-carpeta').selectedOptions[0].text") == "· Postes"      # the selected folder is the default
        await p.evaluar("document.getElementById('ml-d-carpeta').value = %d; true" % visita)
        marcador = await p.evaluar("(() => { const m = window.MisLugares._ml.trabajo.capa.getLatLng(); return [m.lat, m.lng]; })()")
        assert marcador[0] == pytest.approx(lat0, abs=1e-5)
        await p.evaluar("document.querySelector('#ml-d-quill .ql-editor').innerHTML = '<p>Casa <b>azul</b><script>x()</script></p>'")
        # ícono: la ventana de selección (letra A, color rojo)
        await p.clic_en("#ml-d-icono")
        await p.esperar("document.getElementById('ml-iconos') && !document.getElementById('ml-iconos').hidden", 5)
        grupos = await p.evaluar("[...document.querySelectorAll('#ml-iconos-rejilla h3')].map(h => h.textContent)")
        assert grupos == ["Pushpins", "Letras", "Números", "Figuras"]
        await p.evaluar("document.getElementById('ml-ic-color').value = '#e53935'; document.getElementById('ml-ic-color').dispatchEvent(new Event('input', {bubbles: true})); true")
        await p.evaluar("document.querySelector('#ml-iconos-rejilla [title=\"Letra A\"]').click()")
        await p.evaluar("document.querySelector('[data-ml-ic=aceptar]').click()")
        assert await p.evaluar("window.MisLugares._ml.trabajo.estilo.icono.id") == "A"
        await _aceptar(p)
        await _esperar_carga(p, 2, 1)
        marca = consulta("SELECT id, nombre, descripcion_html, estilo, ST_Y(geom) AS lat FROM redes.lugares_elementos")[0]
        assert (marca["nombre"], marca["descripcion_html"]) == ("Cliente Pérez", "<p>Casa <strong>azul</strong></p>")      # Quill writes <strong>; the script is gone
        assert marca["estilo"]["icono"]["id"] == "A" and marca["estilo"]["icono"]["color"] == "#e53935" and marca["lat"] == pytest.approx(lat0, abs=1e-5)
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 1
        assert await p.evaluar("document.querySelector('.ml-etiqueta').innerText") == "Cliente Pérez"      # the name next to the pin
        # ---- editar la marca con coordenadas en grados, minutos y segundos
        await p.evaluar("window.MisLugares.editar(%d); true" % marca["id"])
        await _ventana_marca(p, "Cliente Pérez 2", lat="12°7'22.5\"N")
        assert await p.evaluar("document.getElementById('ml-d-nombre').value") == "Cliente Pérez 2"
        await p.esperar("document.querySelector('#ml-d-quill .ql-editor').innerText.includes('Casa azul')", 5)
        await _aceptar(p)
        await asyncio.sleep(0.8)
        marca = consulta("SELECT nombre, version, ST_Y(geom) AS lat FROM redes.lugares_elementos")[0]
        assert (marca["nombre"], marca["version"]) == ("Cliente Pérez 2", 2) and marca["lat"] == pytest.approx(12 + 7 / 60 + 22.5 / 3600, abs=1e-6)
        # ---- ruta: tres clics y doble clic; la pestaña Medidas; luego se mueve un vértice con el ratón
        await p.clic_en('[data-bh="ruta"]')
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
        zoom_antes = await p.evaluar("window.visor.mapa.getZoom()")
        await _dibujar(p, [(640, 300), (760, 380), (880, 330)])
        await p.evaluar("document.querySelector('[data-ml-pest=medidas]').click()")
        texto = await p.evaluar("document.getElementById('ml-d-medidas').innerText")
        assert "Puntos\n3" in texto and "Longitud" in texto
        assert await p.evaluar("window.MisLugares._ml.trabajo.capa.getLatLngs().length") == 3
        assert await p.evaluar("window.visor.mapa.getZoom()") == zoom_antes                           # finishing with a double click did not zoom
        vertice = await p.evaluar("(() => { const m = document.querySelectorAll('.marker-icon:not(.marker-icon-middle)'); const r = m[m.length - 1].getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        longitud_antes = await p.evaluar("window.MisLugares._ml.trabajo.capa.getLatLngs().reduce((s, q, i, a) => s + (i ? a[i - 1].distanceTo(q) : 0), 0)")
        await p.mover(*vertice)
        await p.enviar("Input.dispatchMouseEvent", type="mousePressed", x=vertice[0], y=vertice[1], button="left", clickCount=1)
        for k in range(1, 7):
            await p.enviar("Input.dispatchMouseEvent", type="mouseMoved", x=vertice[0] + 12 * k, y=vertice[1] - 6 * k, buttons=1, button="left")
        await p.enviar("Input.dispatchMouseEvent", type="mouseReleased", x=vertice[0] + 72, y=vertice[1] - 36, button="left", clickCount=1)
        await asyncio.sleep(0.5)
        longitud_despues = await p.evaluar("window.MisLugares._ml.trabajo.capa.getLatLngs().reduce((s, q, i, a) => s + (i ? a[i - 1].distanceTo(q) : 0), 0)")
        assert abs(longitud_despues - longitud_antes) > 100                                                # the vertex moved (tens of pixels = hundreds of metres)…
        assert f"{longitud_despues:,.1f} m".replace(",", ",") in (await p.evaluar("document.getElementById('ml-d-medidas').innerText"))   # …and the measure followed
        await p.evaluar("document.querySelector('[data-ml-pest=estilo]').click()")
        await p.evaluar("document.getElementById('ml-d-e-linea-color').value = '#00aa00'; document.getElementById('ml-d-e-linea-grosor').value = '6'; "
                        "document.getElementById('ml-d-estilo').dispatchEvent(new Event('change', {bubbles: true})); true")
        assert await p.evaluar("window.MisLugares._ml.trabajo.capa.options.color") == "#00aa00"        # live preview
        await p.evaluar("document.getElementById('ml-d-nombre').value = 'Tramo norte'")
        await _aceptar(p)
        await _esperar_carga(p, 2, 2)
        ruta = consulta("SELECT nombre, estilo, ST_NPoints(geom) AS n, ST_Length(geom::geography) AS m FROM redes.lugares_elementos WHERE tipo = 'ruta'")[0]
        assert (ruta["nombre"], ruta["n"], ruta["estilo"]["linea"]["color"], ruta["estilo"]["linea"]["grosor"]) == ("Tramo norte", 3, "#00aa00", 6.0)
        assert ruta["m"] == pytest.approx(longitud_despues, rel=0.01)
        # ---- polígono: cuatro clics; área en la pestaña Medidas
        await p.clic_en('[data-bh="poligono"]')
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
        await _dibujar(p, [(600, 450), (720, 450), (720, 540), (600, 540)])
        await p.evaluar("document.querySelector('[data-ml-pest=medidas]').click()")
        assert "Área" in await p.evaluar("document.getElementById('ml-d-medidas').innerText")
        await _aceptar(p)
        await _esperar_carga(p, 2, 3)
        poligono = consulta("SELECT ST_Area(geom::geography) AS a, ST_NPoints(geom) AS n FROM redes.lugares_elementos WHERE tipo = 'poligono'")[0]
        assert poligono["n"] == 5 and poligono["a"] > 1000                                              # 4 corners + the closing point
        # ---- casillas: apagar la carpeta oculta todo del mapa y se guarda; volver a encenderla lo muestra
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 3
        await p.evaluar("document.querySelector('[data-ml=\"c:%d\"] .lg-casilla').click()" % visita)
        await asyncio.sleep(0.8)
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 0
        assert {f["visible"] for f in consulta("SELECT visible FROM redes.lugares_elementos")} == {False}
        await p.evaluar("document.querySelector('[data-ml=\"c:%d\"] .lg-casilla').click()" % visita)
        await asyncio.sleep(0.8)
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 3
        # ---- arrastrar y soltar: la marca a la subcarpeta; el polígono antes de la ruta (orden manual)
        await p.evaluar("window.Lugares.refrescar(); true")
        await _arrastrar(p, f'[data-ml="e:{marca["id"] if False else consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = chr(109)||chr(97)||chr(114)||chr(99)||chr(97)")[0]["id"]}"]', f'[data-ml="c:{postes}"]')
        await asyncio.sleep(0.8)
        assert consulta("SELECT carpeta_id FROM redes.lugares_elementos WHERE tipo = 'marca'")[0]["carpeta_id"] == postes
        ruta_id = consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'ruta'")[0]["id"]
        poli_id = consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'poligono'")[0]["id"]
        await _arrastrar(p, f'[data-ml="e:{poli_id}"]', f'[data-ml="e:{ruta_id}"]', "antes")
        await asyncio.sleep(0.8)
        ordenes = {f["tipo"]: f["orden"] for f in consulta("SELECT tipo, orden FROM redes.lugares_elementos")}
        assert ordenes["poligono"] < ordenes["ruta"]
        # un lugar no se suelta en la raíz
        await _arrastrar(p, f'[data-ml="e:{ruta_id}"]', '[data-ml="r"]')
        await asyncio.sleep(0.5)
        assert consulta("SELECT carpeta_id FROM redes.lugares_elementos WHERE id = %s", ruta_id)[0]["carpeta_id"] == visita
        # ---- exportar a KMZ (el diálogo de guardar de Windows se simula)
        await p.evaluar("window.__guardado = null; window.__stubs.guardar_archivo = (n, d, t) => { window.__guardado = {n, d, t}; return {ok: true, ruta: 'C:/x.kmz'}; }")
        await _menu(p, f"c:{visita}", "Exportar a KMZ")
        await p.esperar("window.__guardado", 10)
        guardado = await p.evaluar("window.__guardado")
        kmz = zipfile.ZipFile(io.BytesIO(base64.b64decode(guardado["d"])))
        assert guardado["t"] == "kmz" and guardado["n"] == "Visita Nandaime"
        doc = kmz.read("doc.kml").decode("utf-8")
        assert doc.count("<Placemark>") == 3 and doc.count("<Folder>") == 2 and any(n.startswith("files/letra-A-e53935") for n in kmz.namelist())
        # ---- importar un KML a una carpeta (clic derecho en la carpeta)
        archivo = tmp_path / "campo.kml"
        archivo.write_text(KML, encoding="utf-8")
        await _menu(p, f"c:{postes}", "Importar KMZ aquí…")
        await p.subir_archivo("#ml-archivo", archivo)
        await _esperar_carga(p, 4, 5)
        del_campo = consulta("SELECT id, padre_id FROM redes.lugares_carpetas WHERE nombre = 'Del campo'")[0]
        assert del_campo["padre_id"] == postes                                                         # inside the folder where it was imported
        assert consulta("SELECT padre_id FROM redes.lugares_carpetas WHERE nombre = 'Postes' AND id <> %s", postes)[0]["padre_id"] == del_campo["id"]
        assert {e["nombre"] for e in consulta("SELECT nombre FROM redes.lugares_elementos")} >= {"Poste A", "Cable B"}
        # ---- compartir con luis, en solo lectura
        await _menu(p, f"c:{visita}", "Compartir…")
        await p.esperar("document.getElementById('ml-compartir') && !document.getElementById('ml-compartir').hidden", 10)
        nombres = await p.evaluar("[...document.querySelectorAll('#ml-compartir-lista label')].map(l => l.innerText.trim())")
        assert nombres == ["luis"]                                                                    # not the owner himself
        await p.evaluar("document.querySelector('#ml-compartir-lista input').click(); document.querySelector('[data-ml-comp=aceptar]').click()")
        await asyncio.sleep(0.8)
        assert consulta("SELECT usuario_id, puede_editar FROM redes.lugares_compartidas") == [{"usuario_id": luis["id"], "puede_editar": False}]
        # ---- el pincho de una coordenada se guarda en Mis lugares
        await p.evaluar("document.getElementById('buscar-mufa').value = '12.2, -86.2'; document.getElementById('buscar-mufa').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); true")
        await p.esperar("window.Pin.hay()", 5)
        await p.evaluar("(window.Pin.marcador.openPopup(), true)")
        await p.esperar("document.querySelector('[data-pin=guardar]')", 5)
        assert await p.evaluar("document.querySelector('[data-pin=guardar]').disabled") is False
        await p.evaluar("document.querySelector('[data-pin=guardar]').click()")
        await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 5)
        assert float(await p.evaluar("document.getElementById('ml-d-lat').value")) == pytest.approx(12.2, abs=1e-6)
        await p.evaluar("document.getElementById('ml-d-cancelar').click()")
        assert await p.evaluar("window.MisLugares.trabajando") is False                                 # cancelling leaves nothing half done
        # ---- el buscador de arriba también busca en Mis lugares
        await p.evaluar("document.getElementById('buscar-mufa').value = 'tramo norte'; document.getElementById('buscar-mufa').dispatchEvent(new Event('input', {bubbles: true})); true")
        await asyncio.sleep(0.8)
        lista = await p.evaluar("[...document.querySelectorAll('#buscar-resultados li')].map(li => li.innerText.trim().replace(/\\s+/g, ' '))")
        assert any(t == "MIS LUGARES" for t in lista) and any(t.startswith("Tramo norte") for t in lista), lista
        # ---- eliminar con confirmación: un elemento desde su popup y una carpeta con su contenido
        await p.evaluar("window.MisLugares.volarA(%d); true" % ruta_id)
        await p.esperar("document.querySelector('.ml-popup [data-ml-p=eliminar]')", 10)
        await p.evaluar("document.querySelector('.ml-popup [data-ml-p=eliminar]').click()")
        await p.esperar("document.getElementById('modal-confirmar') && !document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click()")
        await asyncio.sleep(0.8)
        assert consulta("SELECT count(*) AS n FROM redes.lugares_elementos WHERE borrado_en IS NULL")[0]["n"] == 4
        assert await p.errores() == []
    # ---- al abrir el visor de nuevo, todo sigue ahí (otra ventana de Edge sobre la misma base)
    async with pagina_edge(1366, 768, con=con, puerto=9334) as p2:
        await p2.esperar("window.MisLugares && window.MisLugares.estado.listo", 20)
        await _esperar_carga(p2, 4, 4)
        assert await p2.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 4
        assert await p2.errores() == []


async def _recorrido_compartido(mundo):
    con, lectura, admin, luis = mundo
    visita = lugares.guardar_carpeta(con, admin, nombre="Para Luis")["id"]
    sub = lugares.guardar_carpeta(con, admin, nombre="Detalle", padre_id=visita)["id"]
    lugares.guardar_lugar(con, admin, carpeta_id=sub, tipo="marca", nombre="Poste compartido", geom={"type": "Point", "coordinates": [-86.3, 12.1]})
    lugares.compartir(con, admin, carpeta_id=visita, compartir_con=[{"usuario_id": luis["id"], "puede_editar": False}])
    async with pagina_edge(1366, 768, con=con, usuario="luis") as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo", 20)
        await _plegar_secciones(p)
        filas = await _filas(p)
        assert [f["texto"] for f in filas][:2] == ["▾ Mis lugares", "▾ Compartidas conmigo 1"]           # open by default: it is how they are found
        assert any("Para Luis" in f["texto"] and "jgutierrez" in f["texto"] and "lectura" in f["texto"] for f in filas)
        # shared folders start hidden for the one who receives them; turning the box on shows them (only in this window)
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 0
        await p.evaluar("document.querySelector('[data-ml=\"c:%d\"] .lg-casilla').click()" % visita)
        await asyncio.sleep(0.6)
        assert await p.evaluar("window.MisLugares._ml.grupo.getLayers().length") == 1
        assert lectura.execute("SELECT visible FROM redes.lugares_elementos").fetchone()["visible"] is True            # the owner's box did not change
        # read only: the menu offers no editing, and the element's popup neither
        items = [i[0] for i in await _menu(p, f"c:{visita}", None) if i[0]]
        assert items == ["Encuadrar", "Exportar a KMZ", "Guardar como proyecto…"] and "Eliminar" not in items
        elemento = lectura.execute("SELECT id FROM redes.lugares_elementos").fetchone()["id"]
        await p.evaluar("window.MisLugares.volarA(%d); true" % elemento)
        await p.esperar("document.querySelector('.ml-popup')", 10)
        botones = await p.evaluar("[...document.querySelectorAll('.ml-popup [data-ml-p]')].map(b => b.dataset.mlP)")
        assert "editar" not in botones and "eliminar" not in botones and "copiar" in botones
        assert await p.errores() == []


def test_mis_lugares_recorrido_del_dueno(mundo, tmp_path):
    asyncio.run(_recorrido_dueno(mundo, tmp_path))


def test_la_primera_marca_ya_ofrece_la_lista_de_carpetas(mundo):
    """Without any folder the first mark creates "Mis lugares" and the window already lists it (it came up empty once)."""
    async def recorrido():
        con, lectura, *_ = mundo
        async with pagina_edge(1366, 768, con=con) as p:
            await p.esperar("window.MisLugares && window.MisLugares.estado.listo", 20)
            assert (await p.evaluar("window.MisLugares.estado")) == {"carpetas": 0, "elementos": 0, "listo": True}
            for herramienta in ("marca", "ruta"):
                await p.clic_en(f'[data-bh="{herramienta}"]')
                if herramienta == "marca":
                    await p.clic(800, 420)
                await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)
                opciones = await p.evaluar("[...document.getElementById('ml-d-carpeta').options].map(o => o.text)")
                assert opciones == ["Mis lugares"], (herramienta, opciones)
                assert await p.evaluar("document.getElementById('ml-d-carpeta').offsetHeight") > 20          # and the list is visible
                await p.evaluar("document.getElementById('ml-d-cancelar').click(); true")
            assert len([f for f in lectura.execute("SELECT id FROM redes.lugares_carpetas").fetchall()]) == 1   # one folder, not one per try
            assert await p.errores() == []
    asyncio.run(recorrido())


def test_mis_lugares_compartidos_en_solo_lectura(mundo):
    asyncio.run(_recorrido_compartido(mundo))
