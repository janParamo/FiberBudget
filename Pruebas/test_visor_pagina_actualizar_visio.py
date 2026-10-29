"""Vista «Red existente» → «Actualizar diagramas Visio» (web/redes/migracion.js): subir los archivos, ver qué se reemplazó y qué es nuevo, y poner al día la base de diagramas con el
importador en segundo plano y su avance. En la página real (Edge sin ventana) con una base desechable; el importador es un guion corto."""
import asyncio
import sys

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from visor_rutas.redes import actualizar_visio

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

VSDX = b"PK\x03\x04" + b"visio-1" * 20


async def _recorrido(con, origen):
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.RedesVistas && window.RedesVistas.migracion && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.RedesVistas.migracion.mostrar(); true")
        assert await p.evaluar("document.getElementById('mg-visio').hidden") is False                        # an administrator sees it
        await p.evaluar("document.getElementById('mg-visio').click(); true")
        await p.esperar("!document.getElementById('modal-mg-visio').hidden && document.getElementById('mg-visio-carpeta').textContent.includes('1 archivo')", 10)
        assert await p.evaluar("document.getElementById('mg-visio-actualizar').disabled") is True            # nothing uploaded yet
        # two files: one replaces the existing, one is new; a wrong one is refused with the reason
        await p.evaluar("""window.__fin = false; (async () => {
          const f = (n, b) => new File([new Uint8Array(b)], n);
          const pk = (x) => [0x50, 0x4b, 3, 4, ...Array.from({length: 40}, (_, i) => (i + x) %% 256)];
          await window.MigracionVisio._subirVisio([f('MUFA BANCO.vsdx', pk(7)), f('MUFA PUERTO PAZ 2.vsdx', pk(9)), f('roto.vsdx', [1, 2, 3, 4, 5])]); window.__fin = true; })(); true""".replace("%%", "%"))
        await p.esperar("window.__fin === true", 20)
        resumen = await p.evaluar("document.getElementById('mg-visio-resumen').textContent")
        assert "Jinotega/MUFA BANCO.vsdx" in resumen and "Nuevos/MUFA PUERTO PAZ 2.vsdx" in resumen and "roto.vsdx" in resumen and "dañado" in resumen
        assert (origen / "Jinotega" / "MUFA BANCO.vsdx").read_bytes() != VSDX and (origen / "Nuevos" / "MUFA PUERTO PAZ 2.vsdx").is_file()
        assert list((origen.parent / "anteriores").rglob("MUFA BANCO.vsdx"))                               # the old one is kept
        assert await p.evaluar("document.getElementById('mg-visio-actualizar').disabled") is False
        # update the base: asks first, then shows the step and ends «Listo»
        await p.evaluar("document.getElementById('mg-visio-actualizar').click(); true")
        await p.esperar("!document.getElementById('modal-confirmar').hidden", 5)
        await p.evaluar("document.getElementById('conf-si').click(); true")
        await p.esperar("document.getElementById('mg-visio-paso').textContent.includes('Paso 2 de 5')", 15)
        assert await p.evaluar("document.getElementById('mg-visio-actualizar').disabled") is True           # while it runs
        await p.esperar("document.getElementById('mg-visio-paso').textContent.includes('Listo')", 25)
        assert "LISTO" in await p.evaluar("document.getElementById('mg-visio-log').textContent")
        assert await p.errores() == []


def test_upload_visio_files_and_update_the_diagram_base(con_redes, tmp_path, monkeypatch):
    origen = tmp_path / "visio" / "DIAGRAMAS ACTUALIZADOS"
    (origen / "Jinotega").mkdir(parents=True)
    (origen / "Jinotega" / "MUFA BANCO.vsdx").write_bytes(VSDX)
    monkeypatch.setenv("VISIO_ORIGEN", str(origen))
    guion = "import time; print('1/5 Inventario'); time.sleep(0.5); print('2/5 Conversión'); time.sleep(3.5); print('5/5 Publicando'); print('LISTO')"
    monkeypatch.setattr(actualizar_visio, "_comando", lambda o: [sys.executable, "-c", guion])
    from visor_rutas.redes import usuarios
    usuarios.identificar(con_redes, usuario_windows="jgutierrez")                                           # the administrator of the test database
    asyncio.run(_recorrido(con_redes, origen))
