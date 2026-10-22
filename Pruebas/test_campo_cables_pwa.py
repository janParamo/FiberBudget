"""App de campo, fase 5 (teléfono): trazar un cable tocando postes, con «Mi ubicación» y grabando el recorrido; la red de referencia por zonas (también sin señal) y
el aviso de «ya hay algo aquí», en un Edge de verdad con GPS simulado contra la API real y la base de pruebas."""
import asyncio
import json

import main  # noqa: F401  (loads visor_api before the fixtures change the environment, as in the whole suite)
import pytest

from arnes_pagina import hay_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo_pwa import _captura, _dialogo, _entrar, _escribir, _tocar, esperar_sql, mundo, servidor_real, telefono, websockets  # noqa: F401
from test_visor_api import entorno  # noqa: F401  (fixture of the /visor/* API)

pytestmark = pytest.mark.skipif(not hay_edge() or websockets is None, reason="necesita Edge y la librería websockets")

LAT, LON = 12.1364, -86.2514
A = (LAT, LON)                                   # PT-A: where the technician stands
B = (LAT + 0.0006, LON + 0.0004)                 # PT-B, ≈ 90 m away


@pytest.fixture(autouse=True)
def _red_del_kmz(monkeypatch):
    """The KMZ network of the budget database is a fake here: two poles and a line between them (nothing reads the real database)."""
    import db

    def zona(o, s, e, n, max_puntos=1500, max_lineas=600, prefijos=None):
        assert prefijos == ["poste", "mufa"] and max_lineas == 0                           # the crews ask for poles and mufas only, no lines
        return {"puntos": [{"id": "k1", "n": "PT-A", "t": "poste", "lat": A[0], "lon": A[1]}, {"id": "k2", "n": "MF-B", "t": "mufa", "lat": B[0], "lon": B[1]}],
                "lineas": [], "truncado": False}
    monkeypatch.setattr(db, "find_red_en_bbox", zona)


async def _ver(p, lat, lon, zoom=18):
    await p.evaluar("CampoMapa.leaflet().setView([%s, %s], %d, {animate: false}); true" % (lat, lon, zoom))


async def _banner(p):
    return await p.evaluar("document.getElementById('cap-banner').textContent")


async def _nuevo_cable(p):
    await _tocar(p, "#b-agregar")
    await p.esperar("document.body.classList.contains('capturando')", 5)
    await _tocar(p, "#cap-ruta")
    await p.esperar("!document.getElementById('cap-cable').hidden", 5)


async def _recorrido(puerto, con, tmp_path):
    async with telefono(puerto, cdp=9351) as p:
        await _entrar(p, "clave-jan")
        await p.esperar("window.Campo.listo && document.getElementById('gps-estado').textContent.includes('±5')", 20)
        await _ver(p, LAT + 0.0003, LON + 0.0002)
        # ---- the reference network shows up (only poles and mufas, no lines), by zone
        await p.esperar("CampoRed.celdas() >= 1 && CampoRed.dibujados() >= 2", 20)
        await _captura(p, "11_red_referencia")

        # ---- registering a point where something already is: the editor says so
        await _tocar(p, "#b-agregar")
        await p.esperar("document.body.classList.contains('capturando')", 5)
        await _tocar(p, "#cap-ok")
        await p.esperar("!document.getElementById('p-editor').hidden", 5)
        assert "Ya hay algo aquí: PT-A (poste)" in await p.evaluar("document.getElementById('ed-cerca').textContent")
        await _tocar(p, "#ed-atras")
        await _dialogo(p, "No")
        assert await p.evaluar("document.getElementById('p-editor').hidden") is True

        # ---- a cable point by point: the first one is on PT-A (it sticks), one on empty ground and the last on MF-B
        await _nuevo_cable(p)
        assert "punto 1 de 1" in await _banner(p)
        await _tocar(p, "#cap-mas")
        await _ver(p, LAT + 0.0003, LON + 0.0001)                                          # the selected point follows the centre of the map
        await _tocar(p, "#cap-mas")
        await _ver(p, B[0] + 0.00001, B[1] + 0.00001)                                      # next to MF-B: it sticks to it
        await p.esperar("document.getElementById('cap-banner').textContent.includes('punto 3 de 3')", 5)
        await _captura(p, "12_trazando")
        await _tocar(p, "#cap-quitar")                                                     # removes the selected one (MF-B) and goes back to the one on the ground
        assert "punto 2 de 2" in await _banner(p)
        await _tocar(p, "#cap-mas")
        await _ver(p, B[0], B[1])
        assert "punto 3 de 3" in await _banner(p)
        await _tocar(p, "#cap-prev")
        assert "punto 2 de 3" in await _banner(p) and await p.evaluar("document.getElementById('cap-sig').disabled") is False
        await _tocar(p, "#cap-sig")
        await _tocar(p, "#cap-guardar")
        await p.esperar("!document.getElementById('p-cable').hidden", 5)
        resumen = await p.evaluar("document.getElementById('cb-resumen').textContent")
        assert "3 puntos" in resumen and "postes" in resumen
        await _tocar(p, "#cb-tipos [data-cb-tipo=ADSS]")
        await p.evaluar("document.getElementById('cb-hilos').value = '24'; true")
        await _escribir(p, "cb-notas", "por la calle")
        await _captura(p, "13_cable")
        await _tocar(p, "#cb-guardar")
        fila = (await esperar_sql(con, "SELECT * FROM redes.campo_trazos"))[0]
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        assert (fila["modo"], fila["tipo_cable"], fila["hilos"], fila["notas"], fila["estado"]) == ("postes", "ADSS", 24, "por la calle", "pendiente")
        assert [x["nombre"] for x in fila["postes"]] == ["PT-A", "MF-B"] and float(fila["longitud_m"]) > 80
        assert con.execute("SELECT ST_NPoints(geom) AS n FROM redes.campo_trazos").fetchone()["n"] == 3
        await p.esperar("document.getElementById('contador').textContent === '1'", 15)
        assert (await p.errores()) == []

        # ---- recording the walk: a vertex every 5 m with a good fix; a bad fix (±40 m) and a tiny move are skipped
        await p.evaluar("Campo.ajustes.poner('grab_tiempo', 0); true")
        await p.gps(LAT + 0.0010, LON, 5.0)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±5')", 10)
        await _tocar(p, "#b-agregar")
        await p.esperar("document.body.classList.contains('capturando')", 5)
        await _tocar(p, "#cap-huellas")
        await p.esperar("!document.getElementById('cap-grab').hidden", 5)
        await p.esperar("document.getElementById('cap-grab-texto').textContent.startsWith('1 punto')", 10)
        for lat, acc in ((LAT + 0.0010 + 0.00001, 5.0),            # ≈ 1 m: too close
                         (LAT + 0.0011, 40.0),                      # far enough but a poor fix
                         (LAT + 0.0011, 4.0),                       # good: vertex 2
                         (LAT + 0.0012, 6.0)):                      # good: vertex 3
            await p.gps(lat, LON, acc)
            await asyncio.sleep(0.4)
        await p.esperar("document.getElementById('cap-grab-texto').textContent.startsWith('3 puntos')", 10)
        await _captura(p, "14_grabando")
        await _tocar(p, "#cap-grab-parar")
        await _dialogo(p, "Guardar")
        await p.esperar("!document.getElementById('p-cable').hidden", 5)
        assert await p.evaluar("document.getElementById('cap-grab').hidden") is True
        assert "recorrido" in await p.evaluar("document.getElementById('cb-resumen').textContent")
        await _tocar(p, "#cb-guardar")
        await esperar_sql(con, "SELECT 1 FROM redes.campo_trazos", 2)
        assert con.execute("SELECT modo, tipo_cable, hilos FROM redes.campo_trazos ORDER BY id DESC").fetchone() == {"modo": "recorrido", "tipo_cable": "ADSS", "hilos": None}

        # ---- cancelling a cable asks before throwing it away
        await p.gps(*A, 5.0)
        await p.esperar("document.getElementById('gps-estado').textContent.includes('±5')", 10)
        await _nuevo_cable(p)
        await _tocar(p, "#cap-mas")
        await _tocar(p, "#cap-mas")
        await _tocar(p, "#cap-cable-x")
        await _dialogo(p, "Seguir")
        assert await p.evaluar("document.body.classList.contains('capturando')") is True               # «keep»: the cable is kept
        await _tocar(p, "#cap-cable-x")
        await _dialogo(p, "Descartar")
        assert await p.evaluar("document.body.classList.contains('capturando')") is False
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos").fetchone()["n"] == 2

        # ---- no signal: the cable waits in the phone and goes out when the signal returns; the zone of the network is still there after a restart
        await p.sin_red(True)
        await p.esperar("navigator.onLine === false", 10)
        await _ver(p, *A)
        await _nuevo_cable(p)
        await _tocar(p, "#cap-mas")
        await _ver(p, *B)
        await _tocar(p, "#cap-guardar")
        await p.esperar("!document.getElementById('p-cable').hidden", 5)
        await _tocar(p, "#cb-guardar")
        await p.esperar("!document.getElementById('cola-barra').hidden", 10)
        assert "1 pendiente de enviar" in await p.evaluar("document.getElementById('cola-texto').textContent")
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos").fetchone()["n"] == 2
        await _tocar(p, "#b-lista")
        texto = await p.evaluar("document.getElementById('l-cuerpo').textContent")
        assert "Sin enviar" in texto and "Cable" in texto
        await p.enviar("Page.reload")
        await p.esperar("document.readyState === 'complete' && window.Campo && window.Campo.listo", 30)
        await _ver(p, LAT + 0.0003, LON + 0.0002)
        await p.esperar("CampoRed.dibujados() >= 2", 20)                                           # from the phone's store, with no signal
        await p.esperar("document.getElementById('cola-texto').textContent.includes('1 pendiente')", 10)
        await p.sin_red(False)
        await esperar_sql(con, "SELECT 1 FROM redes.campo_trazos", 3, 40)
        await p.esperar("document.getElementById('cola-barra').hidden", 20)
        assert con.execute("SELECT modo FROM redes.campo_trazos ORDER BY id DESC").fetchone()["modo"] == "postes"

        # ---- the list: the cables of the jornada; delete a pending one
        await p.evaluar("Campo.cargarPuntos(); true")
        await _tocar(p, "#b-lista")
        await p.esperar("document.querySelectorAll('#l-cuerpo .fila-item').length === 3", 10)
        n0 = con.execute("SELECT count(*) AS n FROM redes.campo_trazos WHERE borrado_en IS NULL").fetchone()["n"]
        await p.evaluar("document.querySelector('#l-cuerpo .fila-item').click(); true")
        await p.esperar("!document.getElementById('tarjeta').hidden", 5)
        await _tocar(p, "#t-mas")
        await _dialogo(p, "Eliminar")
        await _dialogo(p, "Eliminar")
        await p.esperar("document.getElementById('contador').textContent === '2'", 10)
        assert con.execute("SELECT count(*) AS n FROM redes.campo_trazos WHERE borrado_en IS NULL").fetchone()["n"] == n0 - 1
        # the reference network can be hidden
        await _tocar(p, "#btn-red")
        await p.esperar("CampoRed.dibujados() === 0", 5)
        assert await p.evaluar("document.getElementById('btn-red').getAttribute('aria-pressed')") == "false"
        assert (await p.errores()) == []


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
