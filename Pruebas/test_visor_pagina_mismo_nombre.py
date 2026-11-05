"""Varias mufas se llaman igual: el diagrama Visio que se abre es el de LA mufa (su nodo, o la más cercana a su coordenada), no el del primer resultado con
ese nombre. Python: lo que el editor de mufa sabe de su Visio, y la ventana aparte. Página: la elección en visor.js."""
import asyncio
import json
import sys
import types
from urllib.parse import parse_qs, urlparse

import pytest
from psycopg.types.json import Jsonb

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import mufa, proyectos, red, usuarios


def test_the_mufa_editor_knows_its_exact_visio_node_and_place(con_redes):
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Jalapa", "codigo": "JAL"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [
        {"id": "a", "tipo": "mufa", "nombre": "MF CENTRO", "lat": 12.10, "lon": -86.30}, {"id": "b", "tipo": "mufa", "nombre": "MF CENTRO", "lat": 12.50, "lon": -86.10}]})
    con.execute("UPDATE redes.elementos SET ref_visio = %s WHERE id = %s", (Jsonb({"clave": "k1", "nodo_id": 1234, "nombre_visio": "MF CENTRO"}), r["ids"]["a"]))
    a, b = mufa.leer(con, admin, mufa_id=r["ids"]["a"])["mufa"], mufa.leer(con, admin, mufa_id=r["ids"]["b"])["mufa"]
    assert (a["nodo_visio"], a["nombre_visio"]) == (1234, "MF CENTRO") and round(a["lat"], 4) == 12.10 and round(a["lon"], 4) == -86.30
    assert b["nodo_visio"] is None and round(b["lat"], 4) == 12.50                                           # one made by hand: the place still tells it apart


class VentanaFalsa:
    def __init__(self, titulo, url, **kw):
        self.title, self.url = titulo, url


def test_windows_of_same_name_mufas_are_not_the_same_window(monkeypatch):
    modulo = types.ModuleType("webview")
    modulo.windows = []
    modulo.create_window = lambda titulo, url=None, **kw: modulo.windows.append(VentanaFalsa(titulo, url)) or modulo.windows[-1]
    monkeypatch.setitem(sys.modules, "webview", modulo)
    api = crear_api_prueba()
    assert api.abrir_ventana("mufa", {"nombre": "MF CENTRO", "id": 7}) == {"ok": True, "ya_abierta": False}
    assert api.abrir_ventana("mufa", {"nombre": "MF CENTRO", "id": 8}) == {"ok": True, "ya_abierta": False}        # another mufa with the same name
    assert api.abrir_ventana("mufa", {"nombre": "MF CENTRO", "id": 7}) == {"ok": True, "ya_abierta": True}
    assert api.abrir_ventana("diagrama", {"nombre": "MF CENTRO", "nodo_id": 21})["ya_abierta"] is False
    assert api.abrir_ventana("diagrama", {"nombre": "MF CENTRO", "nodo_id": 22})["ya_abierta"] is False
    q = {k: x[0] for k, x in parse_qs(urlparse(modulo.windows[-1].url).fragment).items()}
    assert q["nodo"] == "22" and q["ventana"] == "diagrama"
    # the zone schema in its own window: by project
    assert api.abrir_ventana("esquema", {"nombre": "Jalapa", "id": 3})["ok"] is True
    assert modulo.windows[-1].title == "Esquema de zona · Jalapa – Fiber Budget" and parse_qs(urlparse(modulo.windows[-1].url).fragment)["id"] == ["3"]
    assert api.abrir_ventana("esquema", {"nombre": "Jalapa"})["ok"] is False


pytestmark_pagina = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MUFAS = [{"id": 1, "nombre": "MF CENTRO", "tipo": "MUFA", "zona": "Norte", "diagramas": 1, "lat": 12.50, "lon": -86.10},
         {"id": 2, "nombre": "MF CENTRO", "tipo": "MUFA", "zona": "Sur", "diagramas": 1, "lat": 12.10, "lon": -86.30},
         {"id": 3, "nombre": "MUFA EL BALCON DE LA LAGUNA", "tipo": "MUFA", "zona": "Nindirí", "diagramas": 1, "lat": None, "lon": None}]      # drawn with its name only: no coordinate
DETALLE = {"id": 0, "nombre": "MF CENTRO", "tipo": "MUFA", "zona": "Sur", "propietario": "IDEAY", "lat": 12.1, "lon": -86.3, "textos": [], "hilos": [],
           "archivos": [{"diagrama": True, "md5": "a" * 32, "ruta_relativa": "SUR/MF.vsd", "nombre": "MF.vsd", "rol": "principal", "tipo_diagrama": "mufa", "ancla": None}]}
STUBS = """(() => { window.__mufas = [];
  window.__stubs.buscar_mufa = () => ({ok: true, resultados: %s});
  window.__stubs.mufa = (id) => { window.__mufas.push(id); return {ok: true, mufa: Object.assign(%s, {id}, id === 3 ? {nombre: 'MUFA EL BALCON DE LA LAGUNA', lat: null, lon: null} : {})}; };
  window.__stubs.diagrama = () => ({ok: false, error: 'sin imagen en la prueba'});
  window.__radios = []; window.__stubs.buscar_mufa_cerca = (lat, lon, radio) => { window.__radios.push(radio); return {ok: true, resultados: [%s]}; };
  return true; })()""" % (json.dumps(MUFAS), json.dumps(DETALLE), json.dumps(MUFAS[1]))


async def _recorrido():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa && window.visor.verVisioAlLado", 20)
        await p.evaluar(STUBS)
        # by the Visio node of the mufa: the second one, though the search lists the other first
        await p.evaluar("window.visor.verVisioAlLado({nombre: 'MF CENTRO', nodo_id: 2, lat: 12.1, lon: -86.3}); true")
        await p.esperar("window.__mufas.length === 1", 10)
        assert await p.evaluar("window.__mufas") == [2]
        # without a node, by the nearest coordinate
        await p.evaluar("window.visor.abrirDiagramaPorNombre('MF CENTRO', 12.4999, -86.1001); true")
        await p.esperar("window.__mufas.length === 2", 10)
        assert await p.evaluar("window.__mufas") == [2, 1]
        await p.evaluar("window.visor.abrirDiagramaPorNombre('MF CENTRO', 12.1002, -86.2999); true")
        await p.esperar("window.__mufas.length === 3", 10)
        assert await p.evaluar("window.__mufas") == [2, 1, 2]
        # a plain name keeps working (the first of that name)
        await p.evaluar("window.visor.abrirDiagramaPorNombre('MF CENTRO'); true")
        await p.esperar("window.__mufas.length === 4", 10)
        assert (await p.evaluar("window.__mufas"))[-1] == 1
        # a saved node number that is now another mufa (the diagrams were imported again and renumbered) is not trusted: the place decides
        await p.evaluar("window.visor.verVisioAlLado({nombre: 'MF CENTRO VIEJO', nodo_id: 1, lat: 12.1, lon: -86.3}); true")
        await p.esperar("window.__mufas.length === 5", 10)
        assert (await p.evaluar("window.__mufas"))[-1] == 2
        # by place only the mufa AT the point (a few metres), never the next one on the street (the Visio and the KMZ agree to a few metres)
        assert await p.evaluar("window.__radios.every((r) => r <= 30) && window.__radios.length > 0") is True
        # a mufa the diagram draws with only its name (no coordinate): «MF» is «MUFA», the lone node of that name is the one, and it is placed where the mufa asked for is
        await p.evaluar("window.visor.verVisioAlLado({nombre: 'MF EL BALCON DE LA LAGUNA', lat: 11.999516, lon: -86.118638}); true")
        await p.esperar("window.__mufas.length === 6", 10)
        assert (await p.evaluar("window.__mufas"))[-1] == 3
        mensaje = await p.evaluar("document.getElementById('mensaje-texto').textContent")
        assert "sin coordenadas" not in mensaje and "11.999516" in mensaje and "posición es la de la mufa asignada" in mensaje
        assert await p.errores() == []


@pytestmark_pagina
def test_the_visio_diagram_of_the_right_mufa_opens_when_names_repeat():
    asyncio.run(_recorrido())


async def _cerrar_visio_al_lado():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        # the Visio beside the editor with a long title and a long file name: the ✕ must stay inside the window
        await p.evaluar("""(() => { document.body.classList.add('ventana-aparte', 'visio-al-lado'); document.getElementById('modal-diagrama').hidden = false;
          document.getElementById('diagrama-titulo').textContent = 'MUFA FOSC LOS POLLOS / SANGRIA ' + 'X'.repeat(60);
          const s = document.getElementById('diagrama-archivo'); s.innerHTML = '<option>' + '1 MUFA RED GRANADA CITY.vsd (en diagrama de red, subred) '.repeat(3) + '</option>'; return true; })()""")
        assert await p.evaluar("getComputedStyle(document.getElementById('diagrama-cerrar')).display") != 'none'          # the esquema window is a ventana-aparte
        caja = await p.evaluar("(() => { const r = document.getElementById('diagrama-cerrar').getBoundingClientRect(); return [r.left, r.right, window.innerWidth]; })()")
        assert 0 <= caja[0] and caja[1] <= caja[2], caja
        await p.evaluar("document.getElementById('diagrama-cerrar').click(); true")
        assert await p.evaluar("document.getElementById('modal-diagrama').hidden") is True
        assert await p.evaluar("document.body.classList.contains('visio-al-lado')") is False


@pytestmark_pagina
def test_the_close_button_of_the_visio_beside_the_editor_is_always_reachable():
    asyncio.run(_cerrar_visio_al_lado())


async def _botones_del_popup():
    async with pagina_edge(1366, 768) as p:
        await p.esperar("window.visor && window.visor.mapa", 20)
        # the popup of a KMZ mufa: two rows of buttons that together are wider than the popup; none may stick out of its box
        await p.evaluar("""(() => { const d = document.createElement('div'); d.id = 'caja-prueba'; d.style.cssText = 'position:fixed;left:20px;top:20px;width:340px;z-index:9999;background:#fff';
          const b = (t) => '<button type="button" class="btn btn-chico">' + t + '</button>';
          d.innerHTML = '<div class="popup"><div class="acciones">' + ['Copiar', 'Entrar a la mufa', 'Ver diagrama Visio'].map(b).join('') + '</div>'
            + '<div class="acciones kc-acciones">' + ['Renombrar', 'Mover', 'Cambiar ícono…', 'Eliminar', 'Deshacer cambios'].map(b).join('') + '</div></div>';
          document.body.appendChild(d); return true; })()""")
        sobran = await p.evaluar("""(() => { const c = document.getElementById('caja-prueba').getBoundingClientRect();
          return [...document.querySelectorAll('#caja-prueba button')].filter((x) => x.getBoundingClientRect().right > c.right + 0.5).length; })()""")
        assert sobran == 0, sobran


@pytestmark_pagina
def test_popup_buttons_wrap_inside_the_box():
    asyncio.run(_botones_del_popup())
