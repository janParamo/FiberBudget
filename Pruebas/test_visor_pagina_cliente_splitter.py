"""Editor de mufa: clic derecho en una salida de un splitter → «Asignar un cliente a esta salida…»: se elige uno de la mufa, se busca en toda la red o se crea uno nuevo
en la misma ventana. En la página real (Edge sin ventana) con una base desechable."""
import asyncio

import pytest

from arnes_pagina import crear_api_prueba, hay_edge, pagina_edge
from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_hilo_clientes import mundo  # noqa: F401  (fixture)
from visor_rutas.redes import mufa

pytestmark = pytest.mark.skipif(not hay_edge(), reason="necesita Edge y la librería websockets")

MENU_SALIDA = """(clave) => { const st = window.EditorMufa._st;
  const r = st.capa.find('.puerto').find((x) => x.getAttr('puerto') === clave);
  r.fire('contextmenu', {evt: new MouseEvent('contextmenu', {clientX: 300, clientY: 300, bubbles: true, cancelable: true})}); return true; }"""


async def _recorrido(mundo_):
    con, admin, proy, ids = mundo_
    sid = mufa.guardar(con, admin, mufa_id=ids["a"], cambios={"splitters": [{"id": "s1", "nombre": "SPL 1X8", "salidas": 8, "x": 470, "y": 40}]})["ids"]["s1"]
    async with pagina_edge(1366, 768, api=crear_api_prueba(con)) as p:
        await p.esperar("window.EditorMufa && window.Redes && window.Redes.disponible", 30)
        await p.evaluar("window.EditorMufa.abrir(%d, 'MF Uno'); true" % ids["a"])
        await p.esperar("window.EditorMufa._st.datos && window.EditorMufa._st.splitters.size === 1", 15)
        await p.evaluar("(%s)('s:%d:salida:4')" % (MENU_SALIDA, sid))
        assert await p.evaluar("document.querySelector('#mu-menu li[data-mu-cl-editar]').textContent") == "Asignar un cliente a esta salida…"
        assert await p.evaluar("document.querySelector('#mu-menu li[data-mu-cl-quitar]')") is None            # nothing to take off yet
        await p.evaluar("document.querySelector('#mu-menu li[data-mu-cl-editar]').click(); true")
        await p.esperar("!document.getElementById('modal-mu-hcliente').hidden", 5)
        assert "salida 4" in await p.evaluar("document.getElementById('mu-hc-titulo').textContent")
        # the client does not appear anywhere: it is created in the same window
        await p.evaluar("""(() => { const f = document.getElementById('mu-hc-form'); f.elements.manual.checked = true; f.elements.manual.dispatchEvent(new Event('change'));
          f.elements.codigo.value = 'C77777'; f.elements.nombre.value = 'Cliente Nuevo'; f.elements.servicio.value = 'ID777'; f.requestSubmit(); return true; })()""")
        await p.esperar("window.EditorMufa._st.puertoClientes.has('%d:4')" % sid, 5)
        await p.evaluar("document.getElementById('mu-aplicar').click(); true")
        await p.esperar("window.EditorMufa._st.puertoClientes.size === 0 && document.getElementById('mu-cambios').textContent === 'Guardado'", 10)
        fila = [dict(f) for f in con.execute("SELECT p.numero, x.codigo_cliente, x.nombre FROM redes.puerto_servicios x JOIN redes.puertos p ON p.id = x.puerto_id "
                                             "WHERE x.borrado_en IS NULL").fetchall()]
        assert fila == [{"numero": 4, "codigo_cliente": "C77777", "nombre": "Cliente Nuevo"}]
        # right click again: it can be changed or taken off
        await p.evaluar("(%s)('s:%d:salida:4')" % (MENU_SALIDA, sid))
        assert "Cambiar el cliente de esta salida" in await p.evaluar("document.querySelector('#mu-menu li[data-mu-cl-editar]').textContent")
        await p.evaluar("document.querySelector('#mu-menu li[data-mu-cl-quitar]').click(); true")
        assert await p.evaluar("window.EditorMufa._st.puertoClientes.get('%d:4').quitar" % sid) is True
        assert await p.errores() == []


def test_a_client_is_assigned_to_a_splitter_output_with_the_right_click(mundo):
    asyncio.run(_recorrido(mundo))
