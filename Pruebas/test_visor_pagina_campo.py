"""App de campo, fase 4 (visor de escritorio): la capa «Levantamiento de campo», la ubicación de los técnicos, los avisos en tiempo real, la vista «Campo» con
aprobar / rechazar / editar, fotos y duplicados, en el visor real (Edge) contra la base de pruebas. Quien no revisa no ve nada de esto."""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import main  # noqa: F401  (before the fixtures: visor_api reads the environment on import)
import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_campo import jpeg
from visor_rutas.redes import campo, usuarios

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

LAT, LON = 12.1364, -86.2514


def punto(nombre, tipo="poste", lat=LAT, lon=LON, **extra):
    return {"uuid_cliente": str(uuid.uuid4()), "tipo": tipo, "subtipo": "concreto" if tipo == "poste" else None, "nombre": nombre, "lat": lat, "lon": lon,
            "precision_m": 4.0, "origen_coord": "gps", "capturado_en": datetime.now(timezone.utc).isoformat(), **extra}


@pytest.fixture
def mundo(con_redes, tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPO_FOTOS_DIR", str(tmp_path / "fotos"))
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")                 # the viewer's user: administrator
    u = usuarios.identificar(con, persona_visor="juan")
    con.execute("UPDATE redes.usuarios SET rol = 'tecnico' WHERE id = %s", (u["id"],))
    juan = usuarios.identificar(con, persona_visor="juan")
    base = con.execute("INSERT INTO redes.proyectos (codigo, nombre, es_red_base) VALUES ('RB-MGA', 'Red base Managua', true) RETURNING id").fetchone()["id"]
    campo.abrir_jornada(con, juan, nombre="Barrio Sur")
    campo.ubicacion(con, juan, lat=LAT + 0.0004, lon=LON, precision_m=6)
    return con, admin, juan, base


def enviar(con, juan, *puntos):
    return [r["punto"] for r in campo.guardar_puntos(con, juan, puntos=list(puntos))["resultados"]]


async def _captura(p, nombre):
    """Screenshots for looking at the viewer by eye: only when CAMPO_CAPTURAS names a folder."""
    import os
    from pathlib import Path
    if os.environ.get("CAMPO_CAPTURAS"):
        await asyncio.sleep(0.6)
        await p.captura(Path(os.environ["CAMPO_CAPTURAS"]) / f"{nombre}.png")


async def _tocar(p, selector):
    await p.evaluar(f"document.querySelector({json.dumps(selector)}).click(); true")


async def _fila(p, nombre, boton):
    await p.evaluar(f"""(() => {{ const tr = [...document.querySelectorAll('#cm-filas tr')].find((t) => t.textContent.includes({json.dumps(nombre)}));
      tr.querySelector('[data-cm-a={boton}]').click(); return true; }})()""")


async def _recorrido(con, admin, juan, base):
    poste, mufa, reserva = enviar(con, juan, punto("Poste 1"), punto("Mufa 1", "mufa", lat=LAT + 0.0002, subtipo="48 domo"), punto("Reserva 1", "reserva", lat=LAT - 0.0002))
    campo.subir_foto(con, juan, punto_id=poste["id"], datos=jpeg(300, 200), uuid_cliente="aaaa1111-0001")
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.CampoVisor && window.CampoVisor.estado().puntos.length === 3", 30)
        await p.evaluar("window.visor.mapa.setView([%s, %s], 18, {animate: false}); true" % (LAT, LON))
        # ---- the layer: a section of Lugares with one box per technician and jornada, yellow (pending) circles with the letter of the type
        await p.esperar("document.querySelectorAll('.campo-marca.pendiente').length === 3", 10)
        assert sorted(await p.evaluar("[...document.querySelectorAll('.campo-marca')].map((m) => m.textContent)")) == ["M", "P", "R"]
        assert await p.evaluar("document.getElementById('campo-contador').textContent") == "3"          # the menu badge: points to review
        assert "juan · Barrio Sur" in await p.evaluar("document.getElementById('panel-lugares') ? document.getElementById('panel-lugares').textContent : document.body.textContent")
        await _captura(p, "8_visor_mapa")
        # ---- the technician's live position: his name and how long ago
        assert "juan · hace" in await p.evaluar("document.querySelector('.campo-tecnico').textContent")

        # ---- real time: a new point arrives, the page is told, asks only for what changed and says it
        nuevo = enviar(con, juan, punto("Poste 2", lat=LAT + 0.0006))[0]
        await p.evaluar("window.CampoVisor.evento({tabla: 'campo_puntos', id: '%s', cambio: 'insert', usuario_id: '%s'}); true" % (nuevo["id"], juan["id"]))
        await p.esperar("window.CampoVisor.estado().puntos.length === 4", 10)
        await p.esperar("document.getElementById('mensaje') && document.getElementById('mensaje').textContent.includes('juan agregó un poste «Poste 2»')", 5)
        assert await p.evaluar("document.getElementById('campo-contador').textContent") == "4"
        campo.ubicacion(con, juan, lat=LAT + 0.0010, lon=LON, precision_m=3)
        await p.evaluar("window.CampoVisor.evento({tabla: 'campo_ubicaciones'}); true")
        await p.esperar("window.CampoVisor.estado().ubicaciones[0].lat > %s" % (LAT + 0.0009), 10)
        # an event of a notice that was lost: «_conectado» asks for everything again
        enviar(con, juan, punto("Poste 3", lat=LAT + 0.0008))
        await p.evaluar("window.CampoVisor.evento({tabla: '_conectado'}); true")
        await p.esperar("window.CampoVisor.estado().puntos.length === 5", 10)

        # ---- hiding a technician-jornada removes its circles
        await p.evaluar("window.Lugares.refrescar(); true")
        await p.evaluar("""(() => { const c = [...document.querySelectorAll('input[type=checkbox]')].find((i) => i.closest('li, label, div') && i.closest('li, label, div').textContent.includes('juan · Barrio Sur')); c.click(); return true; })()""")
        await p.esperar("document.querySelectorAll('.campo-marca').length === 0", 5)
        await p.evaluar("""(() => { const c = [...document.querySelectorAll('input[type=checkbox]')].find((i) => i.closest('li, label, div') && i.closest('li, label, div').textContent.includes('juan · Barrio Sur')); c.click(); return true; })()""")
        await p.esperar("document.querySelectorAll('.campo-marca').length === 5", 5)

        # ---- the «Campo» view: the pending ones, with photos
        await _tocar(p, '#menu-lateral [data-vista="campo"]')
        await p.esperar("!document.getElementById('vista-campo').hidden && document.querySelectorAll('#cm-filas tr[data-k]').length === 5", 10)
        await p.esperar("[...document.querySelectorAll('#cm-filas img[data-cm-foto]')].every((i) => i.src.startsWith('data:image'))", 10)
        assert "5 elementos" in await p.evaluar("document.getElementById('cm-estado').textContent")
        await _captura(p, "9_visor_panel")
        await p.evaluar("(() => { const t = document.getElementById('cm-f-texto'); t.value = 'mufa'; t.dispatchEvent(new Event('input')); return true; })()")
        assert await p.evaluar("document.querySelectorAll('#cm-filas tr[data-k]').length") == 1
        await p.evaluar("(() => { const t = document.getElementById('cm-f-texto'); t.value = ''; t.dispatchEvent(new Event('input')); return true; })()")

        # ---- correct one before deciding: it becomes «Corregido»
        await _fila(p, "Poste 3", "editar")
        await p.esperar("document.querySelector('.campo-modal #cm-e-nombre')", 5)
        await p.evaluar("document.getElementById('cm-e-nombre').value = 'Poste 3 (esquina)'; document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 10)
        assert con.execute("SELECT nombre, estado FROM redes.campo_puntos WHERE nombre LIKE 'Poste 3%'").fetchone() == {"nombre": "Poste 3 (esquina)", "estado": "editado"}
        await p.esperar("[...document.querySelectorAll('#cm-filas .cm-est')].some((e) => e.textContent === 'Corregido')", 10)

        # ---- reject: the reason is required, then the technician can read it
        await _fila(p, "Reserva 1", "rechazar")
        await p.esperar("document.querySelector('.campo-modal #cm-d-motivo')", 5)
        await p.evaluar("document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("document.querySelector('.cm-d-error').textContent.includes('motivo')", 5)
        await p.evaluar("document.getElementById('cm-d-motivo').value = 'Está en un lote privado'; document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 10)
        assert con.execute("SELECT estado, motivo_rechazo FROM redes.campo_puntos WHERE nombre = 'Reserva 1'").fetchone() == {"estado": "rechazado", "motivo_rechazo": "Está en un lote privado"}
        await p.esperar("document.querySelectorAll('#cm-filas tr[data-k]').length === 4", 10)       # it left the «por revisar» list

        # ---- approve in a batch: the poles and the mufa go to the base network
        await p.evaluar("document.querySelectorAll('#cm-filas [data-cm-sel]').forEach((c) => { c.click(); }); true")
        await p.esperar("!document.getElementById('cm-lote').hidden && document.getElementById('cm-lote-texto').textContent.startsWith('4 elementos')", 5)
        await _tocar(p, "#cm-lote-aprobar")
        await p.esperar("document.querySelector('.campo-modal #cm-d-proyecto') && document.querySelector('#cm-d-proyecto option')", 5)
        await _captura(p, "10_visor_aprobar")
        assert "Red base Managua" in await p.evaluar("document.getElementById('cm-d-proyecto').textContent")
        assert await p.evaluar("document.querySelector('[name=cm-dest]:checked').value") == "red"
        await p.evaluar("document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 15)
        await p.esperar("document.querySelectorAll('#cm-filas tr[data-k]').length === 0", 10)
        elementos = con.execute("SELECT tipo, nombre, proyecto_id FROM redes.elementos ORDER BY nombre").fetchall()
        assert [(e["tipo"], e["nombre"], e["proyecto_id"]) for e in elementos] == [("mufa", "Mufa 1", base), ("poste", "Poste 1", base), ("poste", "Poste 2", base), ("poste", "Poste 3 (esquina)", base)]
        assert await p.evaluar("document.getElementById('campo-contador').hidden") is True
        assert (await p.errores()) == []

        # ---- a new point where something already exists is flagged as a possible duplicate; and a reserva goes to Mis lugares with its photo
        dup, res = enviar(con, juan, punto("Poste otra vez", lat=LAT + 0.00001), punto("Reserva 2", "reserva", lat=LAT - 0.0004))
        campo.subir_foto(con, juan, punto_id=res["id"], datos=jpeg(300, 200), uuid_cliente="aaaa1111-0002")
        await p.evaluar("window.CampoVisor.evento({tabla: 'campo_puntos'}); true")
        await p.esperar("document.querySelectorAll('#cm-filas tr[data-k]').length === 2", 10)
        assert "Posible duplicado: Poste 1" in await p.evaluar("document.getElementById('cm-filas').textContent")
        await _fila(p, "Reserva 2", "aprobar")
        await p.esperar("document.querySelector('.campo-modal [name=cm-dest]')", 5)
        assert await p.evaluar("document.querySelector('[name=cm-dest]:checked').value") == "lugares"             # no pole or mufa in the selection
        await p.evaluar("document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 15)
        lugar = con.execute("SELECT l.nombre, c.nombre AS carpeta FROM redes.lugares_elementos l JOIN redes.lugares_carpetas c ON c.id = l.carpeta_id").fetchone()
        assert lugar == {"nombre": "Reserva 2", "carpeta": "Campo – juan"}
        assert (await p.errores()) == []


def test_the_field_survey_in_the_viewer_for_who_reviews(mundo):
    con, admin, juan, base = mundo
    asyncio.run(_recorrido(con, admin, juan, base))


def test_who_does_not_review_sees_nothing_of_the_field_survey(mundo):
    con, *_ = mundo

    async def correr():
        async with pagina_edge(1366, 768, api=crear_api_prueba(con, usuario="alguien-nuevo")) as p:       # a new user is a reader
            await p.esperar("window.Redes && window.Redes.iniciado", 20)
            await asyncio.sleep(0.5)
            assert await p.evaluar("document.querySelector('#menu-lateral [data-vista=campo]').hidden") is True
            assert await p.evaluar("window.CampoVisor.estado().puntos.length") == 0
            assert await p.evaluar("document.querySelectorAll('.campo-marca').length") == 0
    asyncio.run(correr())


def trazo(**cambios):
    return {"uuid_cliente": str(uuid.uuid4()), "modo": "puntos", "tipo_cable": "ADSS", "hilos": 24, "notas": "por la calle",
            "puntos": [{"lat": LAT, "lon": LON}, {"lat": LAT + 0.0005, "lon": LON + 0.0001}, {"lat": LAT + 0.0010, "lon": LON + 0.0004}],
            "capturado_en": datetime.now(timezone.utc).isoformat(), **cambios}


async def _cables(con, juan, base):
    for nombre, tipo, lat, lon in (("PT-1", "poste", LAT, LON), ("MF-2", "mufa", LAT + 0.0010, LON + 0.0004)):
        con.execute("INSERT INTO redes.elementos (proyecto_id, tipo, nombre, ubicacion) VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))", (base, tipo, nombre, lon, lat))
    bueno, sin_polos = [r["trazo"] for r in campo.guardar_trazos(con, juan, trazos=[trazo(), trazo(puntos=[{"lat": LAT + 0.01, "lon": LON}, {"lat": LAT + 0.011, "lon": LON}], hilos=12)])["resultados"]]
    punto_suelto = enviar(con, juan, punto("Reserva 9", "reserva", lat=LAT - 0.0004))[0]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.CampoVisor && window.CampoVisor.estado().trazos.length === 2 && window.CampoVisor.estado().puntos.length === 1", 30)
        await p.evaluar("window.visor.mapa.setView([%s, %s], 17, {animate: false}); true" % (LAT + 0.0005, LON))
        assert await p.evaluar("document.getElementById('campo-contador').textContent") == "3"                      # one point and two cables to review
        await p.esperar("document.querySelectorAll('path.leaflet-interactive').length >= 1", 10)                    # the cables are drawn
        assert "juan · Barrio Sur" in await p.evaluar("document.body.textContent")

        # ---- the view lists the cables, filtered by type
        await _tocar(p, '#menu-lateral [data-vista="campo"]')
        await p.esperar("document.querySelectorAll('#cm-filas tr[data-k]').length === 3", 10)
        await p.evaluar("(() => { const t = document.getElementById('cm-f-tipo'); t.value = 'cable'; t.dispatchEvent(new Event('change')); return true; })()")
        assert await p.evaluar("document.querySelectorAll('#cm-filas tr[data-k]').length") == 2
        assert "Cable ADSS · 24 hilos" in await p.evaluar("document.getElementById('cm-filas').textContent")
        await _captura(p, "13_visor_cables")

        # ---- the one with poles at its ends becomes a cable of the base network
        await _fila(p, "Cable ADSS · 24 hilos", "aprobar")
        await p.esperar("document.querySelector('.campo-modal [name=cm-dest]')", 5)
        assert await p.evaluar("document.querySelector('[name=cm-dest]:checked').value") == "red"
        await p.evaluar("document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 15)
        cable = (await _esperar_fila(con, "SELECT nombre, hilos, proyecto_id FROM redes.cables"))[0]
        assert (cable["nombre"], cable["hilos"], cable["proyecto_id"]) == ("Cable PT-1 – MF-2", 24, base)

        # ---- the other one has no pole at its ends: it says so and stays pending; then it is rejected with a reason
        await p.evaluar("(() => { const t = document.getElementById('cm-f-estado'); t.value = 'por_decidir'; t.dispatchEvent(new Event('change')); return true; })()")
        await _fila(p, "Cable ADSS · 12 hilos", "aprobar")
        await p.esperar("document.querySelector('.campo-modal [name=cm-dest]')", 5)
        await p.evaluar("document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 15)
        await p.esperar("document.getElementById('mensaje') && document.getElementById('mensaje').textContent.includes('no se pudo')", 10)
        assert con.execute("SELECT estado FROM redes.campo_trazos WHERE hilos = 12").fetchone()["estado"] == "pendiente"
        await _fila(p, "Cable ADSS · 12 hilos", "rechazar")
        await p.esperar("document.querySelector('.campo-modal #cm-d-motivo')", 5)
        await p.evaluar("document.getElementById('cm-d-motivo').value = 'No sigue la calle'; document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 10)
        assert con.execute("SELECT estado, motivo_rechazo FROM redes.campo_trazos WHERE hilos = 12").fetchone() == {"estado": "rechazado", "motivo_rechazo": "No sigue la calle"}

        # ---- a point and a cable decided together: both to Mis lugares
        extra = campo.guardar_trazos(con, juan, trazos=[trazo()])["resultados"][0]["trazo"]
        await p.evaluar("window.CampoVisor.evento({tabla: 'campo_trazos'}); true")
        await p.esperar("window.CampoVisor.estado().trazos.length === 3", 10)
        await p.evaluar("(() => { const t = document.getElementById('cm-f-tipo'); t.value = ''; t.dispatchEvent(new Event('change')); return true; })()")
        await p.evaluar("document.querySelectorAll('#cm-filas [data-cm-sel]').forEach((c) => { c.click(); }); true")
        await p.esperar("document.getElementById('cm-lote-texto').textContent.startsWith('2 elementos')", 5)
        await _tocar(p, "#cm-lote-aprobar")
        await p.esperar("document.querySelector('.campo-modal [name=cm-dest]')", 5)
        await p.evaluar("document.querySelector('.campo-modal [value=lugares]').click(); document.querySelector('.campo-modal [data-d=si]').click(); true")
        await p.esperar("!document.querySelector('.campo-modal')", 15)
        tipos = sorted(f["tipo"] for f in await _esperar_fila(con, "SELECT tipo FROM redes.lugares_elementos", 2))
        assert tipos == ["marca", "ruta"]
        assert (await p.errores()) == []


async def _esperar_fila(con, consulta, cuantos=1, segundos=15):
    import time
    t0 = time.time()
    while time.time() - t0 < segundos:
        filas = con.execute(consulta).fetchall()
        if len(filas) >= cuantos:
            return filas
        await asyncio.sleep(0.25)
    raise TimeoutError(consulta)


def test_the_cables_traced_in_the_field_are_reviewed_in_the_viewer(mundo):
    con, admin, juan, base = mundo
    asyncio.run(_cables(con, juan, base))
