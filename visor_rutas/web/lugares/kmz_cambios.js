/* Editar lo que ya existe en el KMZ (visor v2, fase 4, segunda parte): renombrar, mover o quitar del mapa un elemento de la red del KMZ.
 *
 * El archivo KMZ no cambia: cada cambio se guarda en la base (redes/kmz_cambios.py) y es de todos. Al construir una capa del KMZ,
 * lugares.js llama a `aplicarAItem` para ponerle el nombre y la posición nuevos o esconderlo. El popup de un elemento trae
 * Renombrar / Mover / Eliminar (solo administradores y editores) y, si ya tiene un cambio, Deshacer. En el árbol de Lugares aparece
 * «Cambios al KMZ (n)» con la lista y su Deshacer. Los cambios todavía no llegan al presupuesto (red_puntos / red_lineas).
 *
 *   KmzCambios.iniciar({mapa, aviso})   KmzCambios.aplicarAItem(it)   KmzCambios.botones(it) -> html   KmzCambios.actual (el del popup)
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const k = { ctx: null, cambios: new Map(), estilos: new Map(), listo: false, mover: null, actual: null };
  const llamar = (m, a) => window.Redes.llamar(m, a);
  const aviso = (t, tipo) => k.ctx.aviso(t, tipo);
  const puedeEditar = () => !!(window.Redes && window.Redes.estado && window.Redes.estado.puede && window.Redes.estado.puede.editar);

  /** What identifies an element of the KMZ: its folder, its ORIGINAL name and its first point rounded (about 1 m). */
  function claveDe(it) {
    const ll = it.orig.ll ? `${it.orig.ll[0].toFixed(5)},${it.orig.ll[1].toFixed(5)}` : "";
    return `${it.c.ruta}|${normal(it.orig.n || it.c.nombre)}|${ll}`;
  }

  /** Puts on the element what its change says (idempotent: it starts from the original). */
  function aplicarAItem(it) {
    it.clave = it.clave || claveDe(it);
    const ch = k.cambios.get(it.clave);
    if (it.orig.n === undefined) delete it.f.properties.n; else it.f.properties.n = it.orig.n;
    if (it.orig.ll && it.capa.setLatLng) it.capa.setLatLng(it.orig.ll);
    if (it.linea && !it.origLineas) it.origLineas = it.linea.getLatLngs();                // the original trace and description, to go back to them
    if (!("origDesc" in it)) it.origDesc = it.f.properties.d;
    if (it.linea && it.origLineas) { it.linea.setLatLngs(it.origLineas); if (it.borde) it.borde.setLatLngs(it.origLineas); }
    if (it.origDesc === undefined) delete it.f.properties.d; else it.f.properties.d = it.origDesc;
    it.borrado = false;
    it.cambio = ch || null;
    if (ch && ch.accion === "borrar") it.borrado = true;
    else if (ch && ch.despues) {
      if (ch.despues.nombre && ch.despues.nombre !== it.orig.n) it.f.properties.n = ch.despues.nombre;
      if (ch.despues.lat != null && it.capa.setLatLng) it.capa.setLatLng([ch.despues.lat, ch.despues.lon]);
      if (ch.despues.coords && it.linea) {                                                // a line replaced by an import
        const ll = ch.despues.coords.map(([x, y]) => [y, x]);
        it.linea.setLatLngs(ll);
        if (it.borde) it.borde.setLatLngs(ll);
      }
      if (typeof ch.despues.descripcion === "string" && ch.despues.descripcion !== (it.origDesc || "")) it.f.properties.d = ch.despues.descripcion;
    }
    aplicarEstilo(it);                                              // icon / colour of its own (or of its folder) — may swap the layer
    if (it.capa.setTooltipContent) it.capa.setTooltipContent(esc(it.f.properties.n || it.c.nombre));
  }

  // ------------------------------------------------------------------ ícono / color propio (de un elemento o de toda una carpeta)
  const claveCarpeta = (c) => `${c.ruta}|*|`;

  /** The style that applies to `it`: its own, else the one of its folder, else the one of the nearest folder above (null: the KMZ's). */
  function estiloDe(it) {
    const propio = k.estilos.get(it.clave || claveDe(it));
    if (propio) return { ...propio.estilo, origen: "elemento" };
    for (let c = it.c; c; c = c.padre ? window.Lugares.carpeta(c.padre) : null) {
      const f = k.estilos.get(claveCarpeta(c));
      if (f) return { ...f.estilo, origen: "carpeta" };
    }
    return null;
  }

  /** Paints `it` as its style says: a point gets an icon of its own (a layer swap), a line its colour and width. Idempotent. */
  function aplicarEstilo(it) {
    const st = estiloDe(it);
    it.estilo = st;
    if (it.linea) {
      const ln = st && st.linea;
      if (!ln && !it.lineaConEstilo) return;                          // nothing of its own now and nothing to undo: leave the KMZ's style alone
      const base = window.Lugares.estiloBaseLinea(it);
      it.linea.setStyle(ln ? { ...base, color: ln.color, weight: ln.grosor, opacity: ln.opacidad * window.Lugares.opacidad(it.c.id) } : base);
      it.lineaConEstilo = !!ln;
      return;
    }
    const ic = st && st.icono;
    if (ic && window.Iconos) {
      const clave = JSON.stringify(ic);
      if (!it.capaEstilo || it.capaEstiloClave !== clave) {
        it.capaEstilo = L.marker(it.capa.getLatLng(), { icon: window.Iconos.leaflet(ic), pane: "kmzPuntos", riseOnHover: true, opacity: window.Lugares.opacidad(it.c.id) });
        it.capaEstiloClave = clave;
      }
      it.capaEstilo.setLatLng(it.capa.getLatLng());
      window.Lugares.reemplazarCapa(it, it.capaEstilo);
    } else if (it.capa !== it.capaBase) {
      it.capaBase.setLatLng(it.capa.getLatLng());
      window.Lugares.reemplazarCapa(it, it.capaBase);
    }
  }

  /** The dialog of a line's style: colour, width, opacity. Resolves {color, grosor, opacidad} or null. */
  function pedirEstiloLinea(actual) {
    return new Promise((resolver) => {
      let modal = $("kc-linea");
      if (!modal) {
        document.body.insertAdjacentHTML("beforeend", `<div id="kc-linea" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="kc-linea-titulo">
          <div class="modal-caja config-caja"><header class="modal-cabecera"><h2 id="kc-linea-titulo">Estilo de la línea</h2><button type="button" class="btn-icono" data-kl="cancelar" aria-label="Cerrar">✕</button></header>
          <div class="config-cuerpo"><label>Color <input type="color" id="kl-color"></label>
            <label>Grosor <input type="number" id="kl-grosor" min="0.5" max="12" step="0.5"></label>
            <label>Opacidad <input type="number" id="kl-opacidad" min="0" max="100" step="5"> %</label>
            <span class="kl-vista" id="kl-vista"></span>
            <div class="config-acciones"><button type="button" class="btn" data-kl="cancelar">Cancelar</button><button type="button" class="btn btn-primario" data-kl="aceptar">Aceptar</button></div></div></div></div>`);
        modal = $("kc-linea");
      }
      const leer = () => ({ color: $("kl-color").value, grosor: Math.min(12, Math.max(0.5, Number($("kl-grosor").value) || 3)),
                            opacidad: Math.min(1, Math.max(0, (Number($("kl-opacidad").value) || 0) / 100)) });
      const vista = () => { const l = leer(); $("kl-vista").innerHTML = `<svg width="160" height="20"><line x1="6" y1="10" x2="154" y2="10" stroke="${esc(l.color)}" stroke-width="${l.grosor}" stroke-opacity="${l.opacidad}" stroke-linecap="round"/></svg>`; };
      const cerrar = (valor) => { modal.hidden = true; modal.onclick = modal.oninput = modal.onkeydown = null; resolver(valor); };
      $("kl-color").value = (actual && actual.color) || "#0000ff";
      $("kl-grosor").value = (actual && actual.grosor) || 3;
      $("kl-opacidad").value = Math.round(((actual && actual.opacidad) ?? 1) * 100);
      vista();
      modal.oninput = vista;
      modal.onclick = (e) => {
        const a = (e.target.closest("[data-kl]") || {}).dataset;
        if (a) cerrar(a.kl === "aceptar" ? leer() : null); else if (e.target === modal) cerrar(null);
      };
      modal.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); cerrar(null); } };
      modal.hidden = false;
      modal.querySelector("[data-kl=aceptar]").focus();
    });
  }

  async function guardarEstilo(clave, alcance, carpeta, nombre, icono, linea) {
    const r = await llamar("guardar_estilo_kmz", { clave, alcance, carpeta, nombre, ...(icono ? { icono } : {}), ...(linea ? { linea } : {}) });
    if (!r.ok) { aviso(r.error, "error"); return false; }
    k.estilos.set(clave, r.estilo);
    return true;
  }

  async function cambiarEstilo(it) {
    window.visor.mapa.closePopup();
    const actual = estiloDe(it);
    if (it.linea) {
      const linea = await pedirEstiloLinea(actual && actual.linea);
      if (!linea) return;
      if (!(await guardarEstilo(it.clave || claveDe(it), "elemento", it.c.ruta, it.f.properties.n || it.c.nombre, null, linea))) return;
    } else {
      const icono = await window.Iconos.seleccionar((actual && actual.icono) || window.Iconos.DEFECTO);
      if (!icono) return;
      if (!(await guardarEstilo(it.clave || claveDe(it), "elemento", it.c.ruta, it.f.properties.n || it.c.nombre, icono, null))) return;
    }
    aplicarEstilo(it);
    window.Lugares.redibujarEtiquetas();
    aviso("Estilo cambiado. Para volver al original: «Quitar estilo»", "ok");
  }

  async function quitarEstilo(it) {
    window.visor.mapa.closePopup();
    const clave = it.clave || claveDe(it);
    if (!k.estilos.has(clave)) return;
    const r = await llamar("quitar_estilo_kmz", { clave });
    if (!r.ok) { aviso(r.error, "error"); return; }
    k.estilos.delete(clave);
    aplicarEstilo(it);
    aviso("Estilo quitado", "ok");
  }

  /** Every loaded element under folder `id` (itself included) looks again as its style says. */
  function reaplicarCarpeta(id) {
    const ids = new Set(window.Lugares.descendientes(id));
    window.Lugares.porCadaItem(({ it }) => { if (ids.has(it.c.id)) aplicarEstilo(it); });
    window.Lugares.redibujarEtiquetas();
  }

  /** «Ícono / estilo…» of a folder of the tree (right click): points get an icon, lines a colour and width; everything below follows. */
  async function estiloCarpeta(id) {
    const c = window.Lugares.carpeta(id);
    if (!c || !puedeEditar()) return;
    const previo = (k.estilos.get(claveCarpeta(c)) || {}).estilo || {};
    const geo = c.geometria || "mixta";
    let icono = null, linea = null;
    if (geo !== "linea") icono = await window.Iconos.seleccionar(previo.icono || window.Iconos.DEFECTO);
    if (geo !== "punto") linea = await pedirEstiloLinea(previo.linea);
    if (!icono && !linea) return;
    if (!(await guardarEstilo(claveCarpeta(c), "carpeta", c.ruta, c.nombre, icono || previo.icono || null, linea || previo.linea || null))) return;
    reaplicarCarpeta(id);
    aviso(`Estilo de «${c.nombre}» cambiado. Para volver al original: clic derecho → Quitar estilo`, "ok");
  }

  async function quitarEstiloCarpeta(id) {
    const c = window.Lugares.carpeta(id);
    if (!c || !puedeEditar()) return;
    if (!k.estilos.has(claveCarpeta(c))) { aviso(`«${c.nombre}» no tiene un estilo propio`); return; }
    const r = await llamar("quitar_estilo_kmz", { clave: claveCarpeta(c) });
    if (!r.ok) { aviso(r.error, "error"); return; }
    k.estilos.delete(claveCarpeta(c));
    reaplicarCarpeta(id);
    aviso(`«${c.nombre}» vuelve a su estilo original`, "ok");
  }

  function reaplicar() {
    window.Lugares.porCadaItem(({ capa, it }) => {
      const estabaOculto = it.borrado;
      aplicarAItem(it);
      const enGrupo = capa.grupo.hasLayer(it.capa);
      if (it.borrado && enGrupo) capa.grupo.removeLayer(it.capa);
      else if (!it.borrado && estabaOculto && !enGrupo) capa.grupo.addLayer(it.capa);
    });
    window.Lugares.redibujarEtiquetas();
    window.Lugares.refrescar();
  }

  async function cargar() {
    const r = await llamar("cambios_kmz", {});
    if (!r.ok) { aviso(`Cambios al KMZ: ${r.error}`, "error"); return; }
    k.cambios = new Map(r.cambios.map((c) => [c.clave, c]));
    const e = await llamar("estilos_kmz", {});                      // icons / colours of their own: a failure here does not stop the rest
    if (e.ok) k.estilos = new Map(e.estilos.map((x) => [x.clave, x]));
    k.listo = true;
    reaplicar();
  }

  function botones(it) {
    if (!puedeEditar()) return "";
    const punto = !it.linea;
    return `<div class="acciones kc-acciones"><button type="button" class="btn btn-chico" data-kc="renombrar">Renombrar</button>
      ${punto ? '<button type="button" class="btn btn-chico" data-kc="mover">Mover</button>' : ""}
      <button type="button" class="btn btn-chico" data-kc="estilo">${punto ? "Cambiar ícono…" : "Cambiar estilo…"}</button>
      ${k.estilos.has(it.clave || claveDe(it)) ? '<button type="button" class="btn btn-chico" data-kc="estilo_quitar">Quitar estilo</button>' : ""}
      <button type="button" class="btn btn-chico" data-kc="borrar">Eliminar</button>
      ${it.cambio ? '<button type="button" class="btn btn-chico" data-kc="deshacer">Deshacer cambios</button>' : ""}</div>
      <div class="nota kc-nota">${it.cambio ? `Cambiado en el visor (${it.cambio.accion === "borrar" ? "eliminado" : "editado"}); el archivo KMZ no se modifica.` : "Los cambios son del visor: el archivo KMZ no se modifica."}</div>`;
  }

  // ------------------------------------------------------------------ guardar un cambio
  const antesDe = (it) => ({ nombre: it.orig.n || it.c.nombre, ...(it.orig.ll ? { lat: it.orig.ll[0], lon: it.orig.ll[1] } : {}) });
  const base = (it) => ({ clave: it.clave || claveDe(it), carpeta: it.c.ruta, tipo: it.linea ? "linea" : "punto", antes: antesDe(it) });

  async function enviar(it, metodo, extra) {
    it.clave = it.clave || claveDe(it);
    const r = await llamar(metodo, { ...base(it), ...extra });
    if (!r.ok) { aviso(r.error, "error"); if (r.conflicto) await cargar(); return false; }
    if (r.cambio) k.cambios.set(it.clave, r.cambio); else k.cambios.delete(it.clave);
    reaplicar();
    return true;
  }

  async function renombrar(it) {
    window.visor.mapa.closePopup();
    const nombre = await Dialogo.pedirTexto("Cambiar nombre", it.f.properties.n || "", "Nombre");
    if (!nombre || nombre === it.f.properties.n) return;
    const ch = it.cambio && it.cambio.despues;
    if (await enviar(it, "editar_kmz", { nombre, ...(ch && ch.lat != null ? { lat: ch.lat, lon: ch.lon } : {}) })) aviso(`Renombrado a «${nombre}»`, "ok");
  }

  async function borrar(it) {
    window.visor.mapa.closePopup();
    if (!(await Redes.confirmar(`¿Quitar «${it.f.properties.n || it.c.nombre}» del mapa? El archivo KMZ no se modifica y se puede deshacer en «Cambios al KMZ».`, "Quitar"))) return;
    if (await enviar(it, "borrar_kmz", {})) aviso("Elemento quitado del mapa. Deshacer: Lugares → Cambios al KMZ", "ok");
  }

  async function deshacer(it) {
    if (!it.cambio) return;
    window.visor.mapa.closePopup();
    const r = await llamar("deshacer_cambio_kmz", { id: it.cambio.id });
    if (!r.ok) { aviso(r.error, "error"); return; }
    k.cambios.delete(it.clave);
    reaplicar();
    aviso("Cambio deshecho", "ok");
  }

  /** Move: a pin to drag (the point itself may be a plain circle); drop saves it, Esc cancels. */
  function mover(it) {
    const mapa = window.visor.mapa;
    mapa.closePopup();
    if (k.mover) k.mover.fin();
    const ll = it.capa.getLatLng();
    const pin = L.marker(ll, { draggable: true, zIndexOffset: 2000, icon: L.divIcon({ className: "icono", html: '<div class="kc-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }) }).addTo(mapa);
    const ayuda = $("ml-ayuda");
    if (ayuda) { ayuda.hidden = false; ayuda.textContent = `Mover «${it.f.properties.n || it.c.nombre}»: arrastre el punto y suéltelo donde va · Esc cancela`; }
    const fin = () => { mapa.removeLayer(pin); document.removeEventListener("keydown", tecla, true); if (ayuda) { ayuda.hidden = true; ayuda.textContent = ""; } k.mover = null; };
    const tecla = (e) => { if (e.key === "Escape") { e.stopPropagation(); fin(); } };
    pin.on("dragend", async () => {
      const p = pin.getLatLng();
      fin();
      const ch = it.cambio && it.cambio.despues;
      if (await enviar(it, "editar_kmz", { nombre: (ch && ch.nombre) || it.f.properties.n || it.orig.n, lat: +p.lat.toFixed(7), lon: +p.lng.toFixed(7) })) aviso("Punto movido", "ok");
    });
    document.addEventListener("keydown", tecla, true);
    k.mover = { fin };
  }

  // ------------------------------------------------------------------ «Cambios al KMZ» en el árbol de Lugares
  const filas = () => (k.cambios.size ? [{ k: "kc", nivel: 0 }] : []);
  const htmlFila = (f, n, top) => `<div class="lg-fila ext kc-fila" style="${top}" data-ext="kc" data-kc-lista data-fila="${n}" title="Ver y deshacer los cambios hechos al KMZ">
      <span class="lg-flecha"></span><span class="lg-nombre"><b>Cambios al KMZ</b></span><span class="lg-cuenta">${k.cambios.size}</span></div>`;

  function abrirLista() {
    let modal = $("kc-lista");
    if (!modal) {
      document.body.insertAdjacentHTML("beforeend", `<div id="kc-lista" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="kc-titulo">
        <div class="modal-caja config-caja"><header class="modal-cabecera"><h2 id="kc-titulo">Cambios al KMZ</h2><button type="button" class="btn-icono" data-kc-cerrar aria-label="Cerrar">✕</button></header>
        <div class="config-cuerpo"><p class="ml-d-nota">El archivo KMZ no se modifica. Estos cambios los ve todo el equipo.</p><div id="kc-filas" class="kc-filas"></div>
        <div class="config-acciones"><button type="button" class="btn" data-kc-cerrar>Cerrar</button></div></div></div></div>`);
      modal = $("kc-lista");
      modal.addEventListener("click", async (e) => {
        if (e.target === modal || e.target.closest("[data-kc-cerrar]")) { modal.hidden = true; return; }
        const b = e.target.closest("[data-kc-deshacer]");
        if (!b) return;
        const r = await llamar("deshacer_cambio_kmz", { id: Number(b.dataset.kcDeshacer) });
        if (!r.ok) { aviso(r.error, "error"); return; }
        k.cambios.delete(r.clave);
        reaplicar();
        pintarLista();
      });
    }
    pintarLista();
    modal.hidden = false;
  }

  function pintarLista() {
    const lista = [...k.cambios.values()];
    $("kc-filas").innerHTML = lista.length ? lista.map((c) => `<div class="kc-fila-cambio"><span><b>${esc(c.despues && c.despues.nombre ? c.despues.nombre : c.nombre)}</b>
      <span class="nota">${c.accion === "borrar" ? "quitado del mapa" : (c.despues && c.despues.nombre !== c.nombre ? `antes «${esc(c.nombre)}»` : "movido")} · ${esc(String(c.carpeta).split(" / ").slice(-2).join(" / "))}</span></span>
      ${puedeEditar() ? `<button type="button" class="btn btn-chico" data-kc-deshacer="${c.id}">Deshacer</button>` : ""}</div>`).join("") : '<p class="ml-d-nota">No hay cambios.</p>';
    window.Lugares.refrescar();
  }

  function iniciar(ctx) {
    k.ctx = ctx;
    window.Lugares.registrarFilas({ id: "kc", filas, html: htmlFila });
    $("lg-filas").addEventListener("click", (e) => { if (e.target.closest("[data-kc-lista]")) abrirLista(); });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-kc]");
      const it = window.__kmzItem;
      if (!b || !it) return;
      ({ renombrar, mover, borrar, deshacer, estilo: cambiarEstilo, estilo_quitar: quitarEstilo }[b.dataset.kc] || (() => {}))(it);
    }, true);
    window.Redes.cuandoListo(() => { if (window.Redes.disponible) cargar(); });
  }

  window.KmzCambios = { iniciar, aplicarAItem, aplicarEstilo, estiloCarpeta, quitarEstiloCarpeta, puedeEditar, botones, cargar, get estilos() { return k.estilos; }, get actual() { return k.actual; }, set actual(v) { k.actual = v; },
                        get cantidad() { return k.cambios.size; } };
})();
