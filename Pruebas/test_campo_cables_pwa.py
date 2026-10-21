"""App de campo, fase 5 (teléfono): trazar un cable tocando postes, con «Mi ubicación» y grabando el recorrido; la red de referencia por zonas (también sin señal) y
el aviso de «ya hay algo aquí», en un Edge de verdad con GPS simulado contra la API real y la base de pruebas."""
import asyncio
import json

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import hay_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo_pwa import _captura, _entrar, _tocar, esperar_sql, mundo, servidor_real, telefono, websockets  # noqa: F401
from test_visor_api import entorno  # noqa: F401  (fixture of the /visor/* API)

pytestmark = pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")

LAT, LON = 12.1364, -86.2514
A = (LAT, LON)                                   # PT-A: where the technician stands
B = (LAT + 0.0006, LON + 0.0004)                 # PT-B, ≈ 90 m away


@pytest.fixture(autouse=True)
def _red_del_kmz(monkeypatch):
    """The KMZ network of the budget database is a fake here: two poles and a line between them (nothing reads the real database)."""
    import db

    def zona(o, s, e, n, max_puntos=1500, max_lineas=600):
        return {"puntos": [{"id": "k1", "n": "PT-A", "t": "poste", "lat": A[0], "lon": A[1]}, {"id": "k2", "n": "MF-B", "t": "mufa", "lat": B[0], "lon": B[1]}],
                "lineas": [{"id": "k3", "n": "FO", "t": "fibra", "c": [list(A), list(B)]}], "truncado": False}
    monkeypatch.setattr(db, "find_red_en_bbox", zona)


async def _pixel(p, lat, lon):
    return await p.evaluar("(() => { const q = CampoMapa.puntoEnPantalla(%s, %s), r = document.getElementById('mapa').getBoundingClientRect(); return [r.left + q.x, r.top + q.y]; })()" % (lat, lon))


async def _tocar_mapa(p, lat, lon):
    x, y = await _pixel(p, lat, lon)
    await p.clic(x, y)


async def _info(p):
    return await p.evaluar("document.getElementById('cable-info').textContent")


async def _recorrido(puerto, con, tmp_path):
    async with telefono(puerto, cdp=9351) as p:
        await _entrar(p, "clave-jan")
        await p.esperar("window.Campo.lista && document.getElementById('gps-estado').textContent.includes('±5')", 20)
        await p.evaluar("CampoMapa.leaflet().setView([%s, %s], 18, {animate: false}); true" % (LAT + 0.0003, LON + 0.0002))
        # ---- the reference network shows up (poles and the line), by zone
        await p.esperar("CampoRed.celdas() >= 1 && CampoRed.dibujados() >= 3", 20)
        await _captura(p, "11_red_referencia")

        # ---- registering a point where something already is: the form says so
        await _tocar(p, "#acciones [data-tipo=poste]")
        await p.esperar("!document.getElementById('hoja-formulario').hidden", 5)
        assert "Ya hay algo aquí: PT-A (poste)" in await p.evaluar("document.getElementById('form-cerca').textContent")
        await _tocar(p, "#form-cancelar")

        # ---- a cable by tapping the poles: PT-A, a point in between and MF-B; the ends stick to the poles
        await _tocar(p, "#btn-cable")
        await p.esperar("!document.getElementById('hoja-cable').hidden && !document.getElementById('mira').hidden", 5)
        await p.evaluar("CampoMapa.leaflet().setView([%s, %s], 18, {animate: false}); true" % (LAT - 0.0004, LON + 0.0002))        # the poles in the upper half: the sheet covers the lower one
        await p.esperar("CampoRed.dibujados() >= 3", 10)
        assert document_info_vacia(await _info(p))
        await _tocar_mapa(p, A[0] + 0.00001, A[1] + 0.00001)                              # a tap next to PT-A: it sticks to it
        await _tocar_mapa(p, LAT + 0.0003, LON + 0.0001)                                  # empty ground
        await _tocar_mapa(p, B[0], B[1])                                                  # the pole itself
        await p.esperar("document.getElementById('cable-info').textContent.startsWith('3 puntos')", 5)
        assert await p.evaluar("document.getElementById('cable-terminar').disabled") is False
        await p.evaluar("document.getElementById('cable-deshacer').click(); true")
        assert (await _info(p)).startswith("2 puntos")
        await _tocar_mapa(p, B[0], B[1])
        await p.esperar("document.getElementById('cable-info').textContent.startsWith('3 puntos')", 5)
        await _captura(p, "12_trazando")
        await _tocar(p, "#cable-terminar")
        await p.esperar("!document.getElementById('hoja-cable-form').hidden", 5)
        assert "3 puntos" in await p.evaluar("document.getElementById('cable-resumen').textContent") and "postes" in await p.evaluar("document.getElementById('cable-resumen').textContent")
        await p.evaluar("document.getElementById('cable-tipo').value = 'ADSS'; document.getElementById('cable-hilos').value = '24'; document.getElementById('cable-notas').value = 'por la calle'; true")
        await _tocar(p, "#cable-guardar")
        fila = (await esperar_sql(con, "SELECT * FROM redes.campo_trazos"))[0]
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        assert (fila["modo"], fila["tipo_cable"], fila["hilos"], fila["notas"], fila["estado"]) == ("postes", "ADSS", 24, "por la calle", "pendiente")
        assert [x["nombre"] for x in fila["postes"]] == ["PT-A", "MF-B"] and float(fila["longitud_m"]) > 80
        assert con.execute("SELECT ST_NPoints(geom) AS n FROM redes.campo_trazos").fetchone()["n"] == 3
        await p.esperar("document.getElementById('contador').textContent === '1'", 15)
        assert (await p.errores()) == []

        # ---- recording the walk: a vertex every 5 m with a good fix; a bad fix (±40 m) and a tiny move are skipped
        await _tocar(p, "#btn-cable")
        await p.esperar("!document.getElementById('hoja-cable').hidden", 5)
        await p.gps(LAT + 0.0010, LON, 5.0)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±5')", 10)
        await _tocar(p, "#cable-grabar")
        await p.esperar("document.getElementById('cable-info').textContent.startsWith('1 punto')", 10)
        for lat, acc in ((LAT + 0.0010 + 0.00001, 5.0),            # ≈ 1 m: too close
                         (LAT + 0.0011, 40.0),                      # far enough but a poor fix
                         (LAT + 0.0011, 4.0),                       # good: vertex 2
                         (LAT + 0.0012, 6.0)):                      # good: vertex 3
            await p.gps(lat, LON, acc)
            await asyncio.sleep(0.4)
        await p.esperar("document.getElementById('cable-info').textContent.startsWith('3 puntos')", 10)
        assert "grabando" in await _info(p)
        await _tocar(p, "#cable-grabar")                            # stop
        assert "grabando" not in await _info(p)
        await p.gps(LAT + 0.0030, LON, 4.0)
        await asyncio.sleep(0.6)
        assert (await _info(p)).startswith("3 puntos")             # stopped: no more vertices
        await _tocar(p, "#cable-terminar")
        await p.esperar("!document.getElementById('hoja-cable-form').hidden", 5)
        assert "recorrido" in await p.evaluar("document.getElementById('cable-resumen').textContent")
        await _tocar(p, "#cable-guardar")
        await esperar_sql(con, "SELECT 1 FROM redes.campo_trazos", 2)
        assert con.execute("SELECT modo, tipo_cable, hilos FROM redes.campo_trazos ORDER BY id DESC").fetchone() == {"modo": "recorrido", "tipo_cable": None, "hilos": None}

        # ---- "my location" and the centre of the map; cancel asks before throwing away
        await p.gps(*A, 5.0)
        await _tocar(p, "#btn-cable")
        await p.esperar("!document.getElementById('hoja-cable').hidden", 5)
        await _tocar(p, "#cable-ubicacion")
        await p.gps(A[0] + 0.0003, A[1], 5.0)
        await asyncio.sleep(0.4)
        await _tocar(p, "#cable-ubicacion")
        await p.evaluar("CampoMapa.leaflet().setView([%s, %s], 18, {animate: false}); true" % (A[0] + 0.0010, A[1]))      # the centre of the map is somewhere else now
        await _tocar(p, "#cable-mira")
        await p.esperar("document.getElementById('cable-info').textContent.startsWith('3 puntos')", 5)
        asked = await p.evaluar("(() => { window.__preguntas = 0; window.confirm = () => { window.__preguntas += 1; return false; }; document.getElementById('cable-cancelar').click(); return window.__preguntas; })()")
        assert asked == 1 and not await p.evaluar("document.getElementById('hoja-cable').hidden")          # «no»: the cable is kept
        await p.evaluar("window.confirm = () => true; document.getElementById('cable-cancelar').click(); true")
        assert await p.evaluar("document.getElementById('hoja-cable').hidden") is True
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos").fetchone()["n"] == 2

        # ---- no signal: the cable waits in the phone and goes out when the signal returns; the zone of the network is still there after a restart
        await p.sin_red(True)
        await p.esperar("navigator.onLine === false", 10)
        await _tocar(p, "#btn-cable")
        await p.gps(*A, 5.0)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±5')", 10)
        await _tocar(p, "#cable-ubicacion")
        await p.gps(*B, 5.0)
        await asyncio.sleep(0.4)
        await _tocar(p, "#cable-ubicacion")
        await _tocar(p, "#cable-terminar")
        await _tocar(p, "#cable-guardar")
        await p.esperar("!document.getElementById('cola-barra').hidden", 10)
        assert "1 pendiente de enviar" in await p.evaluar("document.getElementById('cola-texto').textContent")
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos").fetchone()["n"] == 2
        await _tocar(p, "#btn-lista")
        assert "Sin enviar" in await p.evaluar("document.getElementById('lista-puntos').textContent") and "Cable" in await p.evaluar("document.getElementById('lista-puntos').textContent")
        await p.enviar("Page.reload")
        await p.esperar("document.readyState === 'complete' && window.Campo && window.Campo.lista", 30)
        await p.evaluar("CampoMapa.leaflet().setView([%s, %s], 18, {animate: false}); true" % (LAT + 0.0003, LON + 0.0002))
        await p.esperar("CampoRed.dibujados() >= 3", 20)                                           # from the phone's store, with no signal
        await p.esperar("document.getElementById('cola-texto').textContent.includes('1 pendiente')", 10)
        await p.sin_red(False)
        await esperar_sql(con, "SELECT 1 FROM redes.campo_trazos", 3, 40)
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        assert con.execute("SELECT modo FROM redes.campo_trazos ORDER BY id DESC").fetchone()["modo"] == "puntos"

        # ---- the list: the cables of the jornada; delete a pending one
        await p.evaluar("window.confirm = () => true; Campo.cargarPuntos(); true")
        await _tocar(p, "#btn-lista")
        await p.esperar("document.querySelectorAll('#lista-puntos li').length === 3", 10)
        n0 = con.execute("SELECT count(*) AS n FROM redes.campo_trazos WHERE borrado_en IS NULL").fetchone()["n"]
        await p.evaluar("document.querySelector('#lista-puntos li button').click(); true")
        await p.esperar("document.querySelectorAll('#lista-puntos li').length === 2 || document.getElementById('contador').textContent === '2'", 10)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos WHERE borrado_en IS NULL").fetchone()["n"] == n0 - 1
        # the reference network can be hidden
        await _tocar(p, "#lista-cerrar")
        await _tocar(p, "#btn-red")
        await p.esperar("CampoRed.dibujados() === 0", 5)
        assert await p.evaluar("document.getElementById('btn-red').getAttribute('aria-pressed')") == "false"
        assert (await p.errores()) == []


def document_info_vacia(texto):
    return texto.startswith("Toque los postes")


def test_a_technician_traces_cables_and_sees_the_network_around(mundo, tmp_path):
    main_, _, con = mundo
    with servidor_real(main_.app) as puerto:
        asyncio.run(_recorrido(puerto, con, tmp_path))


def test_the_cable_logic_of_the_page(mundo):
    main_, _, _ = mundo

    async def correr(puerto):
        async with telefono(puerto, cdp=9352) as p:
            ev = lambda js: p.evaluar(js)
            d = await ev("CampoTrazo.distanciaM({lat: 12.0, lon: -86.0}, {lat: 12.001, lon: -86.0})")
            assert 110 < d < 112
            assert await ev("""(() => { const t = CampoTrazo.crear();
              const r = [t.agregar(12, -86), t.agregar(12, -86), t.agregar(12.0001, -86)].map((v) => !!v);
              return [r, t.n(), t.listo(), t.modo()]; })()""") == [[True, False, True], 2, True, "puntos"]                       # the same place twice in a row is not a vertex
            assert await ev("""(() => { const t = CampoTrazo.crear(); t.agregar(12, -86); t.agregar(12.0001, -86, {poste: {nombre: 'PT'}}); return [t.modo(), t.postes().length]; })()""") == ["postes", 1]
            assert await ev("""(() => { const t = CampoTrazo.crear(); t.agregar(12, -86);
              return [!!t.fijar({lat: 12.00001, lon: -86, precision_m: 5}), !!t.fijar({lat: 12.001, lon: -86, precision_m: 40}), !!t.fijar({lat: 12.001, lon: -86, precision_m: 5}), t.n(), t.modo()]; })()""") == [False, False, True, 2, "recorrido"]
            assert await ev("(() => { const t = CampoTrazo.crear(); t.agregar(12, -86); return t.listo(); })()") is False          # one point is not a cable
            assert await ev("[CampoTrazo.texto(45.4), CampoTrazo.texto(1530)]") == ["45 m", "1.53 km"]
    with servidor_real(main_.app) as puerto:
        asyncio.run(correr(puerto))
