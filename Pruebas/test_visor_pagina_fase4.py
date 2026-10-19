"""Visor v2, fase 4 (red dibujada en una carpeta de Mis lugares), en la página real (Edge sin ventana, base desechable): mufa, poste y cliente
con su pestaña «Datos de red», un cable con el imán entre dos elementos, el popup con el metraje, y «Guardar como proyecto»."""
import asyncio
import json

import pytest

from arnes_pagina import hay_edge, pagina_edge
from test_visor_pagina_fase3 import _aceptar, _esperar_carga, _menu, _plegar_secciones, _texto_pedido, mundo  # noqa: F401  (fixture)
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import lugares

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")


async def _ventana(p):
    await p.esperar("document.getElementById('ml-dialogo') && !document.getElementById('ml-dialogo').hidden", 10)


async def _poner(p, campo, valor):
    await p.evaluar("(() => { const e = document.getElementById(%s); e.value = %s; e.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
                    % (json.dumps(campo), json.dumps(valor)))


async def _pixel(p, lat, lon):
    return await p.evaluar("(() => { const m = window.visor.mapa, q = m.latLngToContainerPoint([%s, %s]), r = m.getContainer().getBoundingClientRect(); return [r.left + q.x, r.top + q.y]; })()" % (lat, lon))


async def _colocar(p, herramienta, x, y, nombre, **campos):
    await p.clic_en(f'[data-bh="{herramienta}"]')
    await p.clic(x, y)
    await _ventana(p)
    assert await p.evaluar("document.querySelector('.ml-d-pest.activa').dataset.mlPest") == "red"          # the network data come first
    await p.evaluar("document.getElementById('ml-d-nombre').value = %s" % json.dumps(nombre))
    for campo, valor in campos.items():
        await _poner(p, f"dr-{campo}", valor)
    await _aceptar(p)


async def _recorrido(mundo):
    con, lectura, admin, _ = mundo
    consulta = lambda sql, *a: [dict(f) for f in lectura.execute(sql, a).fetchall()]
    carpeta = lugares.guardar_carpeta(con, admin, nombre="Red de la visita")["id"]
    async with pagina_edge(1366, 768, con=con) as p:
        await p.esperar("window.MisLugares && window.MisLugares.estado.listo", 20)
        await _plegar_secciones(p)
        await _esperar_carga(p, 1, 0)
        # ---- puntos: se colocan con un clic y se llenan en «Datos de red»; el ícono sale del tipo
        await _colocar(p, "mufa", 700, 400, "MF-100", subtipo="terminal", capacidad="48")
        await _colocar(p, "poste", 850, 380, "P-1", subtipo="madera")
        await _colocar(p, "cliente", 1000, 420, "Casa Pérez", codigo="c4455", id_servicio="S-9")
        await _esperar_carga(p, 1, 3)
        filas = {f["nombre"]: f for f in consulta("SELECT nombre, tipo, propiedades, estilo FROM redes.lugares_elementos")}
        assert filas["MF-100"]["propiedades"] == {"subtipo": "terminal", "capacidad": 48} and filas["MF-100"]["estilo"]["icono"]["id"] == "anillo"
        assert filas["P-1"]["propiedades"] == {"subtipo": "madera"} and filas["P-1"]["estilo"]["etiqueta"]["visible"] is False
        assert filas["Casa Pérez"]["propiedades"] == {"codigo": "C4455", "id_servicio": "S-9"}
        # un código mal escrito no se guarda y la ventana lo dice
        await p.clic_en('[data-bh="cliente"]')
        await p.clic(900, 300)
        await _ventana(p)
        await _poner(p, "dr-codigo", "XX")
        await p.evaluar("document.getElementById('ml-d-form').requestSubmit()")
        await asyncio.sleep(0.4)
        assert "C seguido de números" in await p.evaluar("document.getElementById('ml-d-estado').textContent")
        await p.evaluar("document.getElementById('ml-d-cancelar').click(); true")
        # ---- cable: clic en la mufa, en el poste y doble clic en el cliente (el cursor se pega a cada elemento)
        ids = {f["nombre"]: f["id"] for f in consulta("SELECT id, nombre FROM redes.lugares_elementos")}
        pos = {f["nombre"]: f["geom"]["coordinates"] for f in lugares.arbol(con, admin)["elementos"]}
        px = {n: await _pixel(p, c[1], c[0]) for n, c in pos.items()}
        await p.clic_en('[data-bh="cable"]')
        assert "elemento de inicio" in await p.evaluar("document.getElementById('ml-ayuda').textContent")
        await p.clic(px["Casa Pérez"][0] + 300, px["Casa Pérez"][1] + 120)                     # a click on nothing does not start a cable
        assert await p.evaluar("window.DibujarRed.dibujando") is True
        assert await p.evaluar("window._dr_puntos === undefined")
        await p.clic(px["MF-100"][0] + 6, px["MF-100"][1] - 5)                                   # near the mufa: glued to it
        await p.clic(px["P-1"][0] - 4, px["P-1"][1] + 4)
        await p.clic(px["Casa Pérez"][0], px["Casa Pérez"][1], n=2)
        await _ventana(p)
        assert await p.evaluar("window.DibujarRed.dibujando") is False
        assert await p.evaluar("document.querySelector('.ml-d-pest.activa').dataset.mlPest") == "red"
        await p.evaluar("document.getElementById('ml-d-nombre').value = 'Troncal 1'")
        await _poner(p, "dr-clase", "troncal")
        await _poner(p, "dr-hilos", "24")
        await _aceptar(p)
        await _esperar_carga(p, 1, 4)
        cable = consulta("SELECT nombre, propiedades, estilo, ST_AsGeoJSON(geom) AS g FROM redes.lugares_elementos WHERE tipo = 'cable'")[0]
        pr = cable["propiedades"]
        assert (pr["origen_id"], pr["destino_id"], pr["clase"], pr["hilos"]) == (ids["MF-100"], ids["Casa Pérez"], "troncal", 24)
        coords = json.loads(cable["g"])["coordinates"]
        assert len(coords) == 3 and coords[0] == pytest.approx(pos["MF-100"], abs=1e-6) and coords[1] == pytest.approx(pos["P-1"], abs=1e-6)
        assert pr["metraje"]["metraje_m"] >= pr["longitud_m"] > 100 and cable["estilo"]["linea"]["grosor"] == 5
        # ---- el popup del cable dice sus datos y su metraje
        await p.evaluar("window.MisLugares.volarA(%d, true); true" % consulta("SELECT id FROM redes.lugares_elementos WHERE tipo = 'cable'")[0]["id"])
        await p.esperar("document.querySelector('.ml-popup dl')", 10)
        popup = await p.evaluar("document.querySelector('.ml-popup').innerText")
        assert "MF-100 → Casa Pérez" in popup and "24 hilos" in popup and "Metraje" in popup, popup
        # ---- guardar la carpeta como proyecto
        await p.evaluar("window.visor.mapa.closePopup(); true")
        await _menu(p, f"c:{carpeta}", "Guardar como proyecto…")
        await _texto_pedido(p, "Proyecto de la visita")
        await p.esperar("/creado con 3 elemento/.test(document.body.innerText) || /creado con 4 elemento/.test(document.body.innerText)", 15)
        proyecto = consulta("SELECT id, nombre FROM redes.proyectos WHERE nombre = 'Proyecto de la visita'")[0]
        assert consulta("SELECT count(*) AS n FROM redes.elementos WHERE proyecto_id = %s", proyecto["id"])[0]["n"] == 3
        assert consulta("SELECT hilos FROM redes.cables WHERE proyecto_id = %s", proyecto["id"])[0]["hilos"] == 24
        assert await p.errores() == []


def test_red_dibujada_en_una_carpeta(mundo):
    asyncio.run(_recorrido(mundo))
