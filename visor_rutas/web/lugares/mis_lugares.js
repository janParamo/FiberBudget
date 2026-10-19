/* "Mis lugares" (visor v2, fase 3): carpetas y elementos propios, como en Google Earth.
 *
 * Aparece en el árbol del panel Lugares, arriba de la red del KMZ (lugares.js → registrarFilas): la raíz "Mis lugares", sus carpetas
 * y elementos con casillas de tres estados, y "Compartidas conmigo". Clic derecho en una carpeta o elemento, doble clic para volar,
 * arrastrar y soltar para mover y ordenar a mano. Marcas de posición, rutas y polígonos se dibujan en el mapa con la barra de
 * herramientas (barra_herramientas.js) y se editan en una ventana flotante (dialogo.js): el pincho se arrastra y los vértices de
 * una ruta o polígono se mueven en el mapa. Todo se guarda en PostgreSQL por Redes.llamar (visor_rutas/redes/lugares.py), igual
 * en modo local y remoto. Carpetas exportables a KMZ e importables de KMZ; compartibles en solo lectura o con edición.
 *
 *   MisLugares.nuevo("marca" | "ruta" | "poligono", carpetaId?, {lat, lon, nombre}?)   MisLugares.editar(id)
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const TITULO = { marca: "Marca de posición", ruta: "Ruta", poligono: "Polígono", mufa: "Mufa", poste: "Poste", cliente: "Cliente", nodo: "Nodo", odf: "ODF", cable: "Cable" };
  const PUNTUALES = ["marca", "mufa", "poste", "cliente", "nodo", "odf"];

  const ml = {
    ctx: null, listo: false, carpetas: new Map(), elementos: new Map(), hijos: new Map(), cuentas: new Map(),
    abiertas: new Set(["r", "s"]), seleccion: null, ajenosVisibles: new Set(), ultimaCarpeta: null,
    capas: new Map(), grupo: null, detalle: new Map(), imagenes: new Map(), trabajo: null, modo: null, arrastre: null, menu: null,
  };
  const llamar = (m, a) => window.Redes.llamar(m, a);
  const aviso = (t, tipo) => ml.ctx.mensaje(t, tipo);

  // ------------------------------------------------------------------ datos
  function aplicarArbol(arbol) {
    ml.carpetas = new Map(arbol.carpetas.map((c) => [c.id, c]));
    ml.elementos = new Map(arbol.elementos.map((e) => [e.id, e]));
    const clave = (c) => (c.propia ? (c.padre_id === null ? "r" : c.padre_id) : (c.raiz_compartida ? "s" : c.padre_id));
    ml.hijos = new Map();
    const meter = (k, h) => { if (!ml.hijos.has(k)) ml.hijos.set(k, []); ml.hijos.get(k).push(h); };
    arbol.carpetas.forEach((c) => meter(clave(c), { t: "c", id: c.id, orden: c.orden }));
    arbol.elementos.forEach((e) => meter(e.carpeta_id, { t: "e", id: e.id, orden: e.orden }));
    ml.hijos.forEach((lista) => lista.sort((a, b) => (a.orden - b.orden) || (a.t === b.t ? a.id - b.id : (a.t === "c" ? -1 : 1))));
    ml.cuentas = new Map();
    const contar = (k) => {
      let n = 0;
      (ml.hijos.get(k) || []).forEach((h) => { n += h.t === "e" ? 1 : contar(h.id); });
      ml.cuentas.set(k, n);
      return n;
    };
    contar("r"); contar("s");
    if (ml.seleccion && !(ml.seleccion.t === "e" ? ml.elementos : ml.carpetas).has(ml.seleccion.id)) ml.seleccion = null;
    ml.listo = true;
    sincronizarMapa();
    window.Lugares.refrescar();
  }

  async function cargar() {
    const r = await llamar("lugares", {});
    if (!r.ok) { aviso(`Mis lugares: ${r.error}`, "error"); return false; }
    aplicarArbol(r);
    return true;
  }

  const propia = (c) => c && c.propia;
  const visible = (e) => (ml.carpetas.get(e.carpeta_id) || {}).propia ? e.visible : ml.ajenosVisibles.has(e.id);
  const editable = (c) => !!(c && c.puede_editar);
  const rutaCarpeta = (id) => { const n = []; for (let c = ml.carpetas.get(id); c; c = ml.carpetas.get(c.padre_id)) n.unshift(c.nombre); return n.join(" / "); };

  function elementosDe(clavePadre, salida = []) {
    (ml.hijos.get(clavePadre) || []).forEach((h) => { if (h.t === "e") salida.push(ml.elementos.get(h.id)); else elementosDe(h.id, salida); });
    return salida;
  }

  function estadoCasilla(clavePadre) {
    const els = elementosDe(clavePadre);
    if (!els.length) return "vacia";
    const n = els.filter(visible).length;
    return n === els.length ? "on" : (n ? "parcial" : "off");
  }

  // ------------------------------------------------------------------ mapa
  function latlngs(geo) {
    if (geo.type === "Point") return L.latLng(geo.coordinates[1], geo.coordinates[0]);
    const pts = geo.type === "Polygon" ? geo.coordinates[0] : geo.coordinates;
    const ll = pts.map(([x, y]) => L.latLng(y, x));
    return geo.type === "Polygon" ? ll.slice(0, -1) : ll;
  }

  function opcionesLinea(st, extra = {}) {
    const li = st.linea || {}, re = st.relleno || {};
    return { color: li.color || "#ffe600", weight: li.grosor ?? 3, opacity: li.opacidad ?? 1, fill: re.activo !== false, fillColor: re.color || "#ffe600",
             fillOpacity: re.activo === false ? 0 : (re.opacidad ?? 0.3), ...extra };
  }

  function etiquetaHtml(e) {
    const et = (e.estilo || {}).etiqueta || {};
    return `<span style="color:${esc(et.color || "#ffffff")};font-size:${Math.round(13 * (et.escala || 1))}px">${esc(e.nombre)}</span>`;
  }

  function crearCapa(e) {
    const st = e.estilo || {};
    let capa;
    if (e.geom.type === "Point") {
      capa = L.marker(latlngs(e.geom), { icon: Iconos.leaflet(st.icono || Iconos.DEFECTO), pane: "mlPuntos", keyboard: false, riseOnHover: true });
      if ((st.etiqueta || {}).visible !== false) capa.bindTooltip(etiquetaHtml(e), { permanent: true, direction: "right", className: "etiqueta ml-etiqueta", offset: [2, 0] });
    } else if (e.geom.type === "LineString") {
      capa = L.polyline(latlngs(e.geom), opcionesLinea(st, { pane: "mlLineas", fill: false })).bindTooltip(esc(e.nombre), { sticky: true, className: "hover" });
    } else {
      capa = L.polygon(latlngs(e.geom), opcionesLinea(st, { pane: "mlPoligonos" })).bindTooltip(esc(e.nombre), { sticky: true, className: "hover" });
    }
    capa.on("click", (ev) => {
      if (window.DibujarRed && window.DibujarRed.dibujando) {                 // drawing a cable: an element is a point of it (a line lets the click through)
        if (capa instanceof L.Marker) { L.DomEvent.stopPropagation(ev); window.DibujarRed.agregarPunto(ev.latlng); }
        return;
      }
      if (ml.ctx.midiendo()) { if (capa instanceof L.Marker) ml.ctx.agregarPunto(ev.latlng); return; }
      if (ev.originalEvent) L.DomEvent.stopPropagation(ev);
      abrirPopup(e.id, ev.latlng);
    });
    capa.on("dblclick", (ev) => {
      L.DomEvent.stop(ev);
      if (window.DibujarRed && window.DibujarRed.dibujando) { window.DibujarRed.terminar(); return; }       // the double click ends the cable on this element
      if (editable(ml.carpetas.get(e.carpeta_id))) editar(e.id);
    });
    return capa;
  }

  function sincronizarMapa() {
    const clave = (e) => `${e.version}|${JSON.stringify(e.estilo)}|${e.nombre}|${JSON.stringify(e.geom)}`;
    ml.capas.forEach((it, id) => { if (!ml.elementos.has(id) || it.clave !== clave(ml.elementos.get(id))) { ml.grupo.removeLayer(it.capa); ml.capas.delete(id); } });
    ml.elementos.forEach((e) => {
      if (!ml.capas.has(e.id)) ml.capas.set(e.id, { capa: crearCapa(e), clave: clave(e) });
      const it = ml.capas.get(e.id);
      const trabajando = ml.trabajo && ml.trabajo.id === e.id;
      const debe = visible(e) && !trabajando;
      if (debe && !ml.grupo.hasLayer(it.capa)) ml.grupo.addLayer(it.capa);
      else if (!debe && ml.grupo.hasLayer(it.capa)) ml.grupo.removeLayer(it.capa);
    });
    if (window.CapasVisor) window.CapasVisor.refrescar();
  }

  function limitesDe(els) {
    const b = L.latLngBounds([]);
    els.forEach((e) => { const ll = latlngs(e.geom); if (Array.isArray(ll)) ll.forEach((p) => b.extend(p)); else b.extend(ll); });
    return b;
  }

  function volarA(id, abrir = true) {
    const e = ml.elementos.get(id);
    if (!e) return;
    const mapa = ml.ctx.mapa;
    if (!visible(e)) {
      if ((ml.carpetas.get(e.carpeta_id) || {}).propia) cambiarVisibilidad({ elementos: [id] }, true); else { ml.ajenosVisibles.add(id); sincronizarMapa(); }
    }
    if (e.vista) mapa.flyTo([e.vista.lat, e.vista.lon], e.vista.zoom, { duration: 0.8 });
    else if (e.geom.type === "Point") mapa.flyTo(latlngs(e.geom), Math.max(mapa.getZoom(), 17), { duration: 0.8 });
    else mapa.flyToBounds(limitesDe([e]), { padding: [60, 60], maxZoom: 18, duration: 0.8 });
    if (abrir) mapa.once("moveend", () => abrirPopup(id));
  }

  function encuadrar(clavePadre) {
    const els = elementosDe(clavePadre);
    if (!els.length) { aviso("La carpeta no tiene elementos para encuadrar"); return; }
    ml.ctx.mapa.flyToBounds(limitesDe(els), { padding: [60, 60], maxZoom: 18, duration: 0.8 });
  }

  // ------------------------------------------------------------------ popup de un elemento
  function datosPopup(e) {
    const c = ml.carpetas.get(e.carpeta_id);
    const filas = [];
    if (e.geom.type === "Point") filas.push(["Coordenada", Coordenadas.formatoDecimal(e.geom.coordinates[1], e.geom.coordinates[0])]);
    else {
      const ll = latlngs(e.geom);
      if (e.geom.type === "LineString") filas.push(["Longitud", `${medidas(ll, "ruta").longitud_m.toLocaleString("en-US", { maximumFractionDigits: 1 })} m`]);
      else { const m = medidas(ll, "poligono"); filas.push(["Área", `${m.area_m2.toLocaleString("en-US", { maximumFractionDigits: 1 })} m²`], ["Perímetro", `${m.perimetro_m.toLocaleString("en-US", { maximumFractionDigits: 1 })} m`]); }
    }
    if (window.DibujarRed && window.DibujarRed.esRed(e.tipo)) filas.unshift(...window.DibujarRed.filasPopup(e, (id) => (ml.elementos.get(id) || {}).nombre));
    return { c, filas };
  }

  function abrirPopup(id, punto) {
    const e = ml.elementos.get(id);
    if (!e) return;
    const { c, filas } = datosPopup(e);
    const ed = editable(c);
    const ll = punto || (e.geom.type === "Point" ? latlngs(e.geom) : limitesDe([e]).getCenter());
    const html = `<div class="popup ml-popup"><h3>${esc(e.nombre)}</h3><div class="tipo">${esc(TITULO[e.tipo] || e.tipo)} · ${esc(rutaCarpeta(e.carpeta_id))}</div>
      <div class="ml-desc" data-ml-desc="${e.id}"></div>
      <dl>${filas.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      <div class="acciones ml-acciones"><button type="button" class="btn btn-chico" data-ml-p="copiar">Copiar coordenada</button>
        ${e.vista ? '<button type="button" class="btn btn-chico" data-ml-p="vista">Ir a la vista</button>' : ""}
        ${ed ? '<button type="button" class="btn btn-chico btn-primario" data-ml-p="editar">Editar</button><button type="button" class="btn btn-chico" data-ml-p="eliminar">Eliminar</button>' : ""}</div></div>`;
    const popup = L.popup({ maxWidth: 380, maxHeight: 460, autoPanPaddingTopLeft: [20, 60] }).setLatLng(ll).setContent(html).openOn(ml.ctx.mapa);
    const raiz = popup.getElement();
    raiz.querySelectorAll("[data-ml-p]").forEach((b) => b.addEventListener("click", () => accionPopup(b.dataset.mlP, e)));
    pintarDescripcion(raiz.querySelector(".ml-desc"), e);
  }

  async function pintarDescripcion(caja, e) {
    try {
      let d = ml.detalle.get(e.id);
      if (!d || d.version !== e.version) {
        const r = await llamar("lugar", { id: e.id });
        if (!r.ok) { caja.textContent = ""; return; }
        d = { version: e.version, html: r.lugar.descripcion_html, adjuntos: r.lugar.adjuntos };
        ml.detalle.set(e.id, d);
      }
      if (!d.html) return;
      caja.innerHTML = d.html.replace(/<img\b[^>]*?\bdata-adj="(\d+)"[^>]*>/gi, (_, id) => `<img class="ml-img" data-ml-img="${id}" alt="">`);
      caja.querySelectorAll("[data-ml-img]").forEach(async (img) => { try { img.src = await urlAdjunto(Number(img.dataset.mlImg)); } catch (x) { img.remove(); } });
    } catch (x) { /* the popup was closed */ }
  }

  async function urlAdjunto(id) {
    if (ml.imagenes.has(id)) return ml.imagenes.get(id);
    const r = await llamar("adjunto_lugar", { id });
    if (!r.ok) throw new Error(r.error);
    const url = `data:${r.adjunto.tipo};base64,${r.adjunto.datos}`;
    ml.imagenes.set(id, url);
    return url;
  }

  function accionPopup(a, e) {
    if (a === "editar") { ml.ctx.mapa.closePopup(); editar(e.id); }
    else if (a === "eliminar") eliminarElemento(e);
    else if (a === "vista") volarA(e.id, false);
    else if (a === "copiar") {
      const p = e.geom.type === "Point" ? e.geom.coordinates : latlngs(e.geom)[0] && [latlngs(e.geom)[0].lng, latlngs(e.geom)[0].lat];
      const texto = Coordenadas.formatoDecimal(p[1], p[0]);
      ml.ctx.copiar(texto, `Coordenada copiada: ${texto}`);
    }
  }

  // ------------------------------------------------------------------ medidas
  function medidas(pts, tipo) {
    const largo = (p, cerrar) => p.reduce((s, q, i) => s + (i ? p[i - 1].distanceTo(q) : 0), 0) + (cerrar && p.length > 2 ? p[p.length - 1].distanceTo(p[0]) : 0);
    if (tipo === "ruta") return { puntos: pts.length, longitud_m: largo(pts, false) };
    const R = 6371008.8, lat0 = pts.reduce((s, p) => s + p.lat, 0) / (pts.length || 1) * Math.PI / 180;
    const xy = pts.map((p) => [R * p.lng * Math.PI / 180 * Math.cos(lat0), R * p.lat * Math.PI / 180]);
    let a = 0;
    xy.forEach((p, i) => { const q = xy[(i + 1) % xy.length]; a += p[0] * q[1] - q[0] * p[1]; });
    return { puntos: pts.length, perimetro_m: largo(pts, true), area_m2: Math.abs(a) / 2 };
  }

  // ------------------------------------------------------------------ crear y editar (ventana flotante + trabajo en el mapa)
  function carpetasEditables() {
    const lista = [];
    const recorrer = (clave, nivel) => (ml.hijos.get(clave) || []).forEach((h) => {
      if (h.t !== "c") return;
      const c = ml.carpetas.get(h.id);
      if (editable(c)) lista.push({ id: c.id, etiqueta: `${"· ".repeat(nivel)}${c.nombre}`, ruta: rutaCarpeta(c.id) });
      recorrer(h.id, nivel + 1);
    });
    recorrer("r", 0);
    recorrer("s", 0);
    return lista;
  }

  async function asegurarCarpeta(carpetaId) {
    const lista = carpetasEditables();
    if (carpetaId && lista.some((c) => c.id === carpetaId)) return carpetaId;
    const previa = ml.seleccion && ml.seleccion.t === "c" && lista.some((c) => c.id === ml.seleccion.id) ? ml.seleccion.id : null;
    if (previa) return previa;
    if (ml.ultimaCarpeta && lista.some((c) => c.id === ml.ultimaCarpeta)) return ml.ultimaCarpeta;
    if (lista.length) return lista[0].id;
    const r = await llamar("guardar_carpeta_lugares", { nombre: "Mis lugares" });          // the first folder of a user
    if (!r.ok) { aviso(r.error, "error"); return null; }
    aplicarArbol(r);
    return r.id;
  }

  function limpiarTrabajo() {
    const t = ml.trabajo;
    if (!t) return;
    ml.ctx.mapa.pm.disableDraw();
    ml.ctx.mapa.doubleClickZoom.enable();                    // it was off while drawing / editing (see empezarDibujo)
    if (t.capa) { if (t.capa.pm) t.capa.pm.disable(); ml.ctx.mapa.removeLayer(t.capa); }
    ml.trabajo = null;
    ayuda("");
    if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo(null);
    sincronizarMapa();
  }

  function ayuda(texto) {
    const caja = $("ml-ayuda");
    if (!caja) return;
    caja.hidden = !texto;
    caja.textContent = texto || "";
  }

  function estiloInicial(tipo) {
    if (window.DibujarRed && window.DibujarRed.esRed(tipo)) return window.DibujarRed.estiloInicial(tipo);
    if (tipo === "marca") return { icono: { ...Iconos.DEFECTO }, etiqueta: { visible: true, color: "#ffffff", escala: 1 } };
    if (tipo === "ruta") return { linea: { color: "#ffe600", grosor: 4, opacidad: 1 } };
    return { linea: { color: "#ffe600", grosor: 3, opacidad: 1 }, relleno: { activo: true, color: "#ffe600", opacidad: 0.3 } };
  }

  /** Opens the floating window for a new element or an existing one (`e` with its full data) and the work layer on the map. */
  async function abrirDialogo({ tipo, e, carpetaId, lat, lon, nombre, latlngsIniciales, extremos }) {
    const mapa = ml.ctx.mapa;
    const puntual = PUNTUALES.includes(tipo), esRed = !!(window.DibujarRed && window.DibujarRed.esRed(tipo));
    limpiarTrabajo();
    // the folder first: with no folders yet the first one ("Mis lugares") is created now, and the list below must include it
    const carpetaElegida = e ? e.carpeta_id : await asegurarCarpeta(carpetaId);
    const carpetas = carpetasEditables();
    const estilo = e ? e.estilo : estiloInicial(tipo);
    ml.trabajo = { id: e ? e.id : null, tipo, capa: null, estilo: JSON.parse(JSON.stringify(estilo || {})), dialogo: null,
                   extremos: e ? { origen_id: (e.propiedades || {}).origen_id ?? null, destino_id: (e.propiedades || {}).destino_id ?? null } : (extremos || {}) };
    const t = ml.trabajo;
    const formRed = esRed ? window.DibujarRed.formulario(tipo, e ? e.propiedades : {}, (propiedades) => alCambiar({ propiedades })) : null;
    const unidad = (ll) => ({ type: "Point", coordinates: [ll.lng, ll.lat] });
    let punto = e && puntual ? latlngs(e.geom) : (lat !== undefined ? L.latLng(lat, lon) : null);

    const pintarPunto = () => {
      if (t.capa) { mapa.removeLayer(t.capa); t.capa = null; }
      if (!punto) return;
      t.capa = L.marker(punto, { draggable: true, icon: Iconos.leaflet(t.estilo.icono || Iconos.DEFECTO), pane: "mlPuntos", zIndexOffset: 1500 }).addTo(mapa);
      t.capa.on("drag dragend", () => { punto = t.capa.getLatLng(); t.dialogo && t.dialogo.ponerCoordenada(punto.lat, punto.lng); });
    };
    const medir = () => { if (t.capa && t.dialogo && !puntual) t.dialogo.ponerMedidas(medidas(lineaDe(t.capa), tipo === "poligono" ? "poligono" : "ruta")); };
    const lineaDe = (capa) => { const ll = capa.getLatLngs(); return tipo === "poligono" ? ll[0] : ll; };

    const alCambiar = (cambio) => {
      if (cambio.estilo) t.estilo = cambio.estilo;
      if (cambio.propiedades && esRed) {                    // the icon / line of a network element follows its type
        const nuevo = window.DibujarRed.estiloInicial(tipo, cambio.propiedades);
        t.estilo = nuevo.icono ? { ...t.estilo, icono: nuevo.icono } : { ...t.estilo, linea: { ...(t.estilo.linea || {}), ...nuevo.linea } };
      }
      if (puntual) {
        if (cambio.lat !== undefined) { punto = L.latLng(cambio.lat, cambio.lon); mapa.panTo(punto); }
        pintarPunto();
      } else if (t.capa) {
        t.capa.setStyle(opcionesLinea(t.estilo, { fill: tipo === "poligono" ? t.estilo.relleno.activo !== false : false }));
      }
    };

    t.dialogo = await Dialogo.abrir({
      tipo, titulo: e ? `Editar: ${TITULO[tipo]}` : `Nueva ${TITULO[tipo].toLowerCase()}`, nombre: e ? e.nombre : (nombre || (tipo === "marca" ? "Marca de posición sin título" : (esRed ? nombreRed(tipo) : `${TITULO[tipo]} sin título`))),
      red: formRed,
      carpetas, carpetaId: carpetaElegida, lat: punto && punto.lat, lon: punto && punto.lng,
      estilo: t.estilo, vista: e ? e.vista : null, descripcionHtml: e ? e.descripcion_html : "", adjuntos: e ? e.adjuntos : [], cargarAdjunto: urlAdjunto, mapa,
      alCambiar,
      alCancelar: () => { limpiarTrabajo(); },
      alAceptar: async (d) => {
        let geom;
        if (puntual) geom = unidad(punto);
        else {
          if (!t.capa) return { ok: false, error: tipo === "poligono" ? "Dibuje el polígono en el mapa" : "Dibuje la ruta en el mapa: clic para cada punto y doble clic para terminar" };
          const pts = lineaDe(t.capa).map((p) => [p.lng, p.lat]);
          geom = tipo === "poligono" ? { type: "Polygon", coordinates: [pts] } : { type: "LineString", coordinates: pts };
          if (pts.length < (tipo === "poligono" ? 3 : 2)) return { ok: false, error: "Faltan puntos" };
        }
        const base = { nombre: d.nombre, geom, descripcion_html: d.descripcion_html, imagenes: d.imagenes, estilo: d.estilo, vista: d.vista };
        if (formRed) base.propiedades = { ...formRed.leer(), ...(tipo === "cable" ? t.extremos : {}) };
        const r = e
          ? await llamar("guardar_lugar", { id: e.id, version: e.version, ...base })
          : await llamar("guardar_lugar", { carpeta_id: d.carpeta_id, tipo, ...base });
        if (!r.ok) { if (r.conflicto) { limpiarTrabajo(); await cargar(); } return { ok: false, error: r.error }; }
        ml.ultimaCarpeta = r.lugar.carpeta_id;
        ml.detalle.delete(r.lugar.id);
        const id = r.lugar.id;
        limpiarTrabajo();
        await cargar();
        ml.abiertas.add(r.lugar.carpeta_id);
        let c = ml.carpetas.get(r.lugar.carpeta_id);
        while (c) { ml.abiertas.add(c.id); c = ml.carpetas.get(c.padre_id); }
        ml.abiertas.add("r");
        ml.seleccion = { t: "e", id };
        guardarAbiertas();
        window.Lugares.refrescar();
        aviso(`${TITULO[tipo]} guardada en ${rutaCarpeta(r.lugar.carpeta_id)}`, "ok");
        return { ok: true };
      },
    });

    if (puntual) {
      pintarPunto();
      if (!e && punto) mapa.panTo(punto);
      sincronizarMapa();
    } else if (e) {                                         // editing a line / polygon: its vertices move in the map
      mapa.doubleClickZoom.disable();
      sincronizarMapa();
      const ll = latlngs(e.geom);
      t.capa = (tipo === "poligono" ? L.polygon : L.polyline)(ll, opcionesLinea(t.estilo, { pane: tipo === "poligono" ? "mlPoligonos" : "mlLineas", fill: tipo === "poligono" })).addTo(mapa);
      activarEdicion(t, medir);
      medir();
    } else if (latlngsIniciales) {                          // a cable just drawn with the magnet: its vertices can still be adjusted
      mapa.doubleClickZoom.disable();
      sincronizarMapa();
      t.capa = L.polyline(latlngsIniciales, opcionesLinea(t.estilo, { pane: "mlLineas", fill: false })).addTo(mapa);
      activarEdicion(t, medir);
      medir();
    } else {
      empezarDibujo(t, tipo, medir, latlngsIniciales);
    }
  }

  function activarEdicion(t, medir) {
    t.capa.pm.enable({ allowSelfIntersection: true, snappable: false });
    t.capa.on("pm:edit pm:vertexadded pm:vertexremoved pm:markerdrag pm:markerdragend", medir);
  }

  function empezarDibujo(t, tipo, medir) {
    const mapa = ml.ctx.mapa;
    mapa.doubleClickZoom.disable();                          // the double click that ends the line must not zoom the map
    ayuda(`${tipo === "ruta" ? "Ruta" : "Polígono"}: clic para cada punto · doble clic (o clic en el primero) para terminar · Esc cancela`);
    mapa.once("pm:create", (ev) => {
      if (ml.trabajo !== t) { mapa.removeLayer(ev.layer); return; }
      ev.layer.options.pane = tipo === "ruta" ? "mlLineas" : "mlPoligonos";
      t.capa = ev.layer;
      ayuda("");
      t.capa.setStyle(opcionesLinea(t.estilo, { fill: tipo === "poligono" }));
      activarEdicion(t, medir);
      medir();
    });
    mapa.pm.setGlobalOptions({ snappable: false, allowSelfIntersection: true });
    mapa.pm.enableDraw(tipo === "ruta" ? "Line" : "Polygon", {
      finishOn: "dblclick", snappable: false, allowSelfIntersection: true,
      pathOptions: opcionesLinea(t.estilo, { pane: tipo === "ruta" ? "mlLineas" : "mlPoligonos", fill: tipo === "poligono" }),
      templineStyle: { color: t.estilo.linea.color, weight: t.estilo.linea.grosor }, hintlineStyle: { color: t.estilo.linea.color, dashArray: [6, 6] },
    });
  }

  /** New element. Marks: with `lat`/`lon` (from the pin or a folder) the window opens at once; without them, one click on the map places it. */
  async function nuevo(tipo, carpetaId, opciones = {}) {
    const mapa = ml.ctx.mapa;
    if (!ml.listo) { aviso("Mis lugares no está disponible (módulo de redes sin conexión)", "error"); return; }
    if (ml.ctx.midiendo()) { aviso("Termine la medición antes de agregar un lugar"); return; }
    if (tipo === "cable") { limpiarTrabajo(); await window.DibujarRed.dibujarCable(carpetaId); return; }
    if (!PUNTUALES.includes(tipo)) { await abrirDialogo({ tipo, carpetaId, latlngsIniciales: opciones.latlngs, nombre: opciones.nombre }); if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo(tipo); return; }
    if (opciones.lat !== undefined) { await abrirDialogo({ tipo, carpetaId, lat: opciones.lat, lon: opciones.lon, nombre: opciones.nombre }); return; }
    if (opciones.centro) { const c = mapa.getCenter(); await abrirDialogo({ tipo, carpetaId, lat: c.lat, lon: c.lng }); return; }
    limpiarTrabajo();
    ml.modo = { tipo, carpetaId };
    mapa.getContainer().classList.add("ml-colocando");
    ayuda(`${TITULO[tipo]}: clic en el mapa donde va · Esc cancela`);
    if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo(tipo);
    const fin = () => { mapa.off("click", alClic); document.removeEventListener("keydown", alTecla, true); mapa.getContainer().classList.remove("ml-colocando"); ml.modo = null; ayuda(""); };
    const alClic = async (ev) => { fin(); await abrirDialogo({ tipo, carpetaId, lat: ev.latlng.lat, lon: ev.latlng.lng }); };
    const alTecla = (ev) => { if (ev.key === "Escape") { fin(); if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo(null); } };
    mapa.once("click", alClic);
    document.addEventListener("keydown", alTecla, true);
  }

  async function editar(id) {
    const r = await llamar("lugar", { id });
    if (!r.ok) { aviso(r.error, "error"); return; }
    if (!r.lugar.puede_editar) { aviso("Esta carpeta se compartió solo para lectura", "error"); return; }
    await abrirDialogo({ tipo: r.lugar.tipo, e: r.lugar });
  }

  async function eliminarElemento(e) {
    if (!(await Redes.confirmar(`¿Eliminar «${e.nombre}»?`, "Eliminar"))) return;
    ml.ctx.mapa.closePopup();
    let r = await llamar("eliminar_lugar", { id: e.id });
    if (!r.ok && r.errores && r.errores.cables) {            // a network element with cables: delete them together or leave it
      if (!(await Redes.confirmar(`«${e.nombre}» tiene cables conectados. ¿Eliminarlos también?`, "Eliminar todo"))) return;
      r = await llamar("eliminar_lugar", { id: e.id, con_cables: true });
    }
    if (!r.ok) { aviso(r.error, "error"); return; }
    await cargar();
    aviso(`«${e.nombre}» eliminado`, "ok");
  }

  // ------------------------------------------------------------------ carpetas
  async function nuevaCarpeta(padreId) {
    const nombre = await Dialogo.pedirTexto("Nueva carpeta", "", "Nombre de la carpeta");
    if (!nombre) return;
    const r = await llamar("guardar_carpeta_lugares", { nombre, padre_id: padreId ?? null });
    if (!r.ok) { aviso(r.error, "error"); return; }
    aplicarArbol(r);
    ml.abiertas.add(padreId ?? "r");
    ml.seleccion = { t: "c", id: r.id };
    guardarAbiertas();
    window.Lugares.refrescar();
  }

  async function renombrarCarpeta(c) {
    const nombre = await Dialogo.pedirTexto("Cambiar nombre", c.nombre, "Nombre de la carpeta");
    if (!nombre || nombre === c.nombre) return;
    const r = await llamar("guardar_carpeta_lugares", { id: c.id, nombre, version: c.version });
    if (!r.ok) { aviso(r.error, "error"); if (r.conflicto) await cargar(); return; }
    aplicarArbol(r);
  }

  async function eliminarCarpeta(c) {
    const n = elementosDe(c.id).length;
    if (!(await Redes.confirmar(`¿Eliminar la carpeta «${c.nombre}»${n ? ` con sus ${n} elemento(s)` : ""} y sus subcarpetas?`, "Eliminar"))) return;
    const r = await llamar("eliminar_carpeta_lugares", { id: c.id });
    if (!r.ok) { aviso(r.error, "error"); return; }
    aplicarArbol(r);
    aviso(`Carpeta «${c.nombre}» eliminada`, "ok");
  }

  async function cambiarVisibilidad(que, valor) {
    const els = que.carpetas ? que.carpetas.flatMap((c) => elementosDe(c)) : (que.elementos || []).map((id) => ml.elementos.get(id));
    const propios = els.filter((e) => e && (ml.carpetas.get(e.carpeta_id) || {}).propia);
    els.forEach((e) => { if (!e) return; if ((ml.carpetas.get(e.carpeta_id) || {}).propia) e.visible = valor; else if (valor) ml.ajenosVisibles.add(e.id); else ml.ajenosVisibles.delete(e.id); });
    sincronizarMapa();
    window.Lugares.refrescar();
    const carpetasPropias = (que.carpetas || []).filter((c) => typeof c === "number" && (ml.carpetas.get(c) || {}).propia);
    if (propios.length || carpetasPropias.length) {
      const r = await llamar("visibilidad_lugares", { carpetas: carpetasPropias, elementos: carpetasPropias.length ? [] : propios.map((e) => e.id), visible: valor });
      if (!r.ok) aviso(r.error, "error");
    }
  }

  // ------------------------------------------------------------------ KMZ y compartir
  async function exportarKmz(c) {
    aviso("Preparando el KMZ…", "cargando");
    const r = await llamar("exportar_lugares_kmz", { carpeta_id: c.id });
    if (!r.ok) { aviso(r.error, "error"); return; }
    const g = await Redes.guardarArchivo(r.nombre, r.datos, "kmz");
    if (g.ok) aviso(`KMZ guardado: ${g.ruta} (${r.resumen.lugares} lugares)`, "ok");
    else if (!g.cancelado) aviso(g.error, "error"); else aviso("");
  }

  function importarKmz(destinoId) {
    const entrada = $("ml-archivo");
    entrada.onchange = () => {
      const archivo = entrada.files && entrada.files[0];
      entrada.value = "";
      if (!archivo) return;
      const lector = new FileReader();
      lector.onload = async () => {
        aviso(`Importando ${archivo.name}…`, "cargando");
        const r = await llamar("importar_lugares_kmz", { datos: String(lector.result).split(",")[1], nombre: archivo.name, carpeta_id: destinoId ?? null });
        if (!r.ok) { aviso(r.error, "error"); return; }
        aplicarArbol(r);
        ml.abiertas.add("r");
        if (destinoId) ml.abiertas.add(destinoId);
        ml.abiertas.add(r.carpeta_id);
        guardarAbiertas();
        ml.seleccion = { t: "c", id: r.carpeta_id };
        window.Lugares.refrescar();
        encuadrar(r.carpeta_id);
        aviso(`Importado: ${r.importados.lugares} lugares en ${r.importados.carpetas} carpeta(s)` + (r.importados.omitidos ? ` · ${r.importados.omitidos} sin forma que se pueda mostrar` : ""), "ok");
      };
      lector.readAsDataURL(archivo);
    };
    entrada.click();
  }

  async function compartir(c) {
    const [usr, act] = await Promise.all([llamar("usuarios_asignables", {}), llamar("compartidos_lugares", { carpeta_id: c.id })]);
    if (!usr.ok || !act.ok) { aviso((usr.ok ? act : usr).error, "error"); return; }
    const yo = Redes.estado && Redes.estado.usuario ? Redes.estado.usuario.id : null;
    const dadas = new Map(act.compartidos.map((x) => [x.usuario_id, x.puede_editar]));
    let modal = $("ml-compartir");
    if (!modal) {
      document.body.insertAdjacentHTML("beforeend", `<div id="ml-compartir" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="ml-compartir-titulo">
        <div class="modal-caja config-caja"><header class="modal-cabecera"><h2 id="ml-compartir-titulo">Compartir</h2><button type="button" class="btn-icono" data-ml-comp="cancelar" aria-label="Cerrar">✕</button></header>
        <div class="config-cuerpo"><p class="ml-d-nota" id="ml-compartir-nota"></p><div id="ml-compartir-lista" class="ml-compartir-lista"></div>
        <div class="config-acciones"><span id="ml-compartir-estado" class="vp-estado"></span><button type="button" class="btn" data-ml-comp="cancelar">Cancelar</button><button type="button" class="btn btn-primario" data-ml-comp="aceptar">Guardar</button></div></div></div></div>`);
      modal = $("ml-compartir");
    }
    $("ml-compartir-nota").textContent = `Quien reciba «${c.nombre}» la ve en «Compartidas conmigo», con sus subcarpetas. Solo usted puede cambiar con quién se comparte.`;
    $("ml-compartir-lista").innerHTML = usr.usuarios.filter((u) => u.id !== yo).map((u) => `<div class="ml-comp-fila"><label><input type="checkbox" data-u="${u.id}" ${dadas.has(u.id) ? "checked" : ""}> ${esc(u.nombre)}</label>
      <select data-e="${u.id}"><option value="0">Solo lectura</option><option value="1" ${dadas.get(u.id) ? "selected" : ""}>Puede editar</option></select></div>`).join("") || `<p class="ml-d-nota">No hay otros usuarios todavía.</p>`;
    modal.hidden = false;
    modal.onclick = async (ev) => {
      const accion = (ev.target.closest("[data-ml-comp]") || {}).dataset;
      if (!accion && ev.target !== modal) return;
      if (!accion || accion.mlComp === "cancelar") { modal.hidden = true; return; }
      const lista = [...modal.querySelectorAll("input[data-u]:checked")].map((i) => ({ usuario_id: Number(i.dataset.u), puede_editar: modal.querySelector(`select[data-e="${i.dataset.u}"]`).value === "1" }));
      const r = await llamar("compartir_lugares", { carpeta_id: c.id, compartir_con: lista });
      if (!r.ok) { $("ml-compartir-estado").textContent = r.error; return; }
      modal.hidden = true;
      aviso(lista.length ? `«${c.nombre}» compartida con ${lista.length} persona(s)` : `«${c.nombre}» ya no se comparte`, "ok");
    };
  }

  // ------------------------------------------------------------------ filas del árbol
  function filas() {
    if (!ml.listo) return [];
    const salida = [{ k: "r", nivel: 0 }];
    const recorrer = (clave, nivel) => (ml.hijos.get(clave) || []).forEach((h) => {
      salida.push({ k: h.t === "c" ? `c:${h.id}` : `e:${h.id}`, nivel });
      if (h.t === "c" && ml.abiertas.has(h.id)) recorrer(h.id, nivel + 1);
    });
    if (ml.abiertas.has("r")) recorrer("r", 1);
    if ((ml.hijos.get("s") || []).length) {
      salida.push({ k: "s", nivel: 0 });
      if (ml.abiertas.has("s")) recorrer("s", 1);
    }
    return salida;
  }

  const ICONO_CARPETA = `<svg class="ml-ico" width="16" height="14" viewBox="0 0 16 14"><path d="M1 2.5A1.5 1.5 0 0 1 2.5 1H6l1.5 1.8h6A1.5 1.5 0 0 1 15 4.3v7.2a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 11.5z" fill="#f2c94c" stroke="#a37a00" stroke-width="1"/></svg>`;
  function muestraElemento(e) {
    const st = e.estilo || {};
    if (e.geom.type === "Point") return `<span class="ml-ico">${Iconos.svg(st.icono || Iconos.DEFECTO, 16)}</span>`;
    const li = st.linea || {}, re = st.relleno || {};
    if (e.geom.type === "LineString") return `<span class="ml-ico"><svg width="16" height="14" viewBox="0 0 16 14"><path d="M1 12 6 4 10 9 15 2" fill="none" stroke="${esc(li.color || "#ffe600")}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
    return `<span class="ml-ico"><svg width="16" height="14" viewBox="0 0 16 14"><path d="M2 11 4 3l8-1 2 8z" fill="${re.activo === false ? "none" : esc(re.color || "#ffe600")}" fill-opacity="${re.opacidad ?? 0.3}" stroke="${esc(li.color || "#ffe600")}" stroke-width="1.6"/></svg></span>`;
  }

  function htmlFila(f, k, top) {
    const sangria = 6 + f.nivel * 14, sel = ml.seleccion && `${ml.seleccion.t}:${ml.seleccion.id}` === f.k ? " sel" : "";
    const base = `style="${top}" data-ext="ml" data-ml="${f.k}" data-fila="${k}"`;
    const casilla = (estado, clave) => `<input type="checkbox" class="lg-casilla" data-ml-casilla="${clave}" ${estado === "on" ? "checked" : ""} ${estado === "vacia" ? "disabled" : ""} data-parcial="${estado === "parcial" ? 1 : 0}">`;
    if (f.k === "r" || f.k === "s") {
      const abierta = ml.abiertas.has(f.k), clave = f.k, n = ml.cuentas.get(clave) || 0;
      return `<div class="lg-fila ext ml raiz${sel}" ${base}><span class="lg-flecha" data-ml-flecha="${clave}">${abierta ? "▾" : "▸"}</span>${casilla(estadoCasilla(clave), clave)}
        ${ICONO_CARPETA}<span class="lg-nombre"><b>${f.k === "r" ? "Mis lugares" : "Compartidas conmigo"}</b></span><span class="lg-cuenta">${n || ""}</span></div>`;
    }
    const [t, idTexto] = f.k.split(":"), id = Number(idTexto);
    if (t === "c") {
      const c = ml.carpetas.get(id);
      if (!c) return "";
      const abierta = ml.abiertas.has(id), n = ml.cuentas.get(id) || 0;
      return `<div class="lg-fila ext ml ml-carpeta${n ? "" : " vacia"}${sel}" ${base} draggable="${propia(c) || editable(c) ? "true" : "false"}" title="${esc(rutaCarpeta(id))}">
        <span class="lg-flecha" data-ml-flecha="${id}">${(ml.hijos.get(id) || []).length ? (abierta ? "▾" : "▸") : ""}</span>${casilla(estadoCasilla(id), id)}${ICONO_CARPETA}
        <span class="lg-nombre">${esc(c.nombre)}</span>${c.propia ? "" : `<span class="lg-ruta">${esc(c.dueno)}${c.puede_editar ? "" : " · lectura"}</span>`}<span class="lg-cuenta">${n || ""}</span></div>`;
    }
    const e = ml.elementos.get(id);
    if (!e) return "";
    const c = ml.carpetas.get(e.carpeta_id);
    return `<div class="lg-fila ext ml elemento${sel}" ${base} draggable="${editable(c) ? "true" : "false"}" title="${esc(e.nombre)}"><span class="lg-flecha"></span>
      ${casilla(visible(e) ? "on" : "off", `e${id}`)}${muestraElemento(e)}<span class="lg-nombre">${esc(e.nombre)}</span></div>`;
  }

  // ------------------------------------------------------------------ eventos del árbol
  function claveDe(el) {
    const fila = el.closest("[data-ml]");
    if (!fila) return null;
    const k = fila.dataset.ml;
    if (k === "r" || k === "s") return { k, t: k, id: k, fila };
    const [t, id] = k.split(":");
    return { k, t, id: Number(id), fila };
  }

  function guardarAbiertas() {
    const api = ml.ctx.api;
    if (api && api.guardar_preferencias) api.guardar_preferencias({ mis_lugares_abiertas: [...ml.abiertas].map(String) }).catch(() => {});
  }

  function alClic(e) {
    const clave = claveDe(e.target);
    if (!clave) return;
    const flecha = e.target.closest("[data-ml-flecha]");
    if (flecha) {
      const v = flecha.dataset.mlFlecha, id = /^\d+$/.test(v) ? Number(v) : v;
      if (ml.abiertas.has(id)) ml.abiertas.delete(id); else ml.abiertas.add(id);
      guardarAbiertas();
      window.Lugares.refrescar();
      return;
    }
    const casilla = e.target.closest("[data-ml-casilla]");
    if (casilla) {
      const v = casilla.dataset.mlCasilla;
      const marcar = !casilla.checked ? false : true;
      if (v === "r" || v === "s") cambiarVisibilidad({ carpetas: (ml.hijos.get(v) || []).filter((h) => h.t === "c").map((h) => h.id), elementos: (ml.hijos.get(v) || []).filter((h) => h.t === "e").map((h) => h.id) }, marcar);
      else if (v.startsWith("e")) cambiarVisibilidad({ elementos: [Number(v.slice(1))] }, marcar);
      else cambiarVisibilidad({ carpetas: [Number(v)] }, marcar);
      return;
    }
    if (clave.t === "c" || clave.t === "e") { ml.seleccion = { t: clave.t, id: clave.id }; window.Lugares.refrescar(); }
  }

  function alDobleClic(e) {
    if (e.target.closest(".lg-casilla, [data-ml-flecha]")) return;
    const clave = claveDe(e.target);
    if (!clave) return;
    if (clave.t === "e") volarA(clave.id);
    else encuadrar(clave.t === "c" ? clave.id : clave.k);
  }

  function itemsMenu(clave) {
    const c = clave.t === "c" ? ml.carpetas.get(clave.id) : null;
    const m = [];
    if (clave.t === "r") {
      m.push(["Nueva carpeta", () => nuevaCarpeta(null)], ["Importar KMZ…", () => importarKmz(null)], ["Encuadrar todo", () => encuadrar("r")]);
    } else if (clave.t === "s") {
      m.push(["Encuadrar todo", () => encuadrar("s")]);
    } else if (clave.t === "c") {
      const ed = editable(c);
      if (ed) m.push(["Nueva carpeta", () => nuevaCarpeta(c.id)], ["Agregar marca de posición aquí", () => nuevo("marca", c.id, { centro: true })],
        ["Agregar ruta", () => nuevo("ruta", c.id)], ["Agregar polígono", () => nuevo("poligono", c.id)], null,
        ["Agregar mufa", () => nuevo("mufa", c.id)], ["Agregar poste", () => nuevo("poste", c.id)], ["Agregar cliente", () => nuevo("cliente", c.id)],
        ["Agregar nodo / OLT", () => nuevo("nodo", c.id)], ["Agregar ODF", () => nuevo("odf", c.id)], ["Agregar cable", () => nuevo("cable", c.id)], null);
      m.push(["Encuadrar", () => encuadrar(c.id)]);
      if (ed) m.push(["Cambiar nombre", () => renombrarCarpeta(c)]);
      if (c.propia) m.push(["Compartir…", () => compartir(c)]);
      m.push(null, ["Exportar a KMZ", () => exportarKmz(c)]);
      if (ed) m.push(["Importar KMZ aquí…", () => importarKmz(c.id)]);
      m.push(["Guardar como proyecto…", () => window.DibujarRed.guardarComoProyecto(c), "Copia las mufas, postes, clientes, nodos, ODF y cables de la carpeta a un proyecto nuevo"]);
      if (ed) m.push(null, ["Eliminar", () => eliminarCarpeta(c)]);
    } else {
      const e = ml.elementos.get(clave.id), ed = editable(ml.carpetas.get(e.carpeta_id));
      m.push(["Volar al lugar", () => volarA(e.id)]);
      if (ed) m.push(["Editar…", () => editar(e.id)]);
      m.push(["Copiar coordenada", () => accionPopup("copiar", e)]);
      if (ed) m.push(null, ["Eliminar", () => eliminarElemento(e)]);
    }
    return m;
  }

  function cerrarMenu() { if (ml.menu) { ml.menu.remove(); ml.menu = null; } }

  function alMenu(e) {
    const clave = claveDe(e.target);
    if (!clave) return;
    e.preventDefault();
    e.stopPropagation();
    cerrarMenu();
    if (clave.t === "c" || clave.t === "e") { ml.seleccion = { t: clave.t, id: clave.id }; window.Lugares.refrescar(); }
    const menu = document.createElement("ul");
    menu.className = "menu ml-menu";
    menu.innerHTML = itemsMenu(clave).map((it, i) => (it === null ? `<li class="ml-sep" role="separator"></li>` :
      `<li data-i="${i}" class="${it[1] ? "" : "ml-deshabilitado"}" ${it[2] ? `title="${esc(it[2])}"` : ""}>${esc(it[0])}</li>`)).join("");
    document.body.appendChild(menu);
    menu.style.left = `${Math.min(e.clientX, window.innerWidth - menu.offsetWidth - 4)}px`;
    menu.style.top = `${Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 4)}px`;
    const items = itemsMenu(clave);
    menu.addEventListener("click", (ev) => {
      const li = ev.target.closest("li[data-i]");
      if (!li) return;
      const it = items[Number(li.dataset.i)];
      if (!it || !it[1]) return;
      cerrarMenu();
      it[1]();
    });
    ml.menu = menu;
  }

  // ---- arrastrar y soltar: mover a otra carpeta y ordenar a mano
  function zonaDe(e, fila) {
    const r = fila.getBoundingClientRect(), y = (e.clientY - r.top) / r.height;
    return y < 0.28 ? "antes" : (y > 0.72 ? "despues" : "dentro");
  }

  function padreDe(clave) {
    if (clave.t === "c") { const c = ml.carpetas.get(clave.id); return c.padre_id === null ? "r" : c.padre_id; }
    return ml.elementos.get(clave.id).carpeta_id;
  }

  function limpiarMarcasDrop() { document.querySelectorAll(".ml-drop-antes, .ml-drop-despues, .ml-drop-dentro").forEach((x) => x.classList.remove("ml-drop-antes", "ml-drop-despues", "ml-drop-dentro")); }

  function alArrastrar(e) {
    const clave = claveDe(e.target);
    if (!clave || !(clave.t === "c" || clave.t === "e") || clave.fila.getAttribute("draggable") !== "true") { e.preventDefault(); return; }
    ml.arrastre = { tipo: clave.t === "c" ? "carpeta" : "lugar", id: clave.id };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", clave.k);
  }

  function alSobrevolar(e) {
    if (!ml.arrastre) return;
    const destino = claveDe(e.target);
    if (!destino) return;
    const zona = zonaDe(e, destino.fila);
    const esCarpetaDestino = destino.t === "c" || destino.t === "r";
    const valido = (zona === "dentro" ? esCarpetaDestino : (destino.t === "c" || destino.t === "e")) && !(ml.arrastre.tipo === "lugar" && destino.t === "r");
    if (!valido) { limpiarMarcasDrop(); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    limpiarMarcasDrop();
    destino.fila.classList.add(`ml-drop-${zona}`);
  }

  async function alSoltar(e) {
    const origen = ml.arrastre;
    ml.arrastre = null;
    const destino = claveDe(e.target);
    limpiarMarcasDrop();
    if (!origen || !destino) return;
    e.preventDefault();
    const zona = zonaDe(e, destino.fila);
    let destinoId, antesDe = null;
    if (zona === "dentro") {
      if (destino.t === "r" || destino.t === "s") { if (destino.t === "s") return; destinoId = null; } else destinoId = destino.id;
    } else {
      const padre = padreDe(destino);
      destinoId = padre === "r" ? null : padre;
      const hermanos = ml.hijos.get(padre) || [];
      const i = hermanos.findIndex((h) => h.t === destino.t && h.id === destino.id);
      const sig = zona === "antes" ? hermanos[i] : hermanos[i + 1];
      antesDe = sig ? { tipo: sig.t === "c" ? "carpeta" : "lugar", id: sig.id } : null;
    }
    if (origen.tipo === "lugar" && destinoId === null) { aviso("Un lugar va dentro de una carpeta", "error"); return; }
    const r = await llamar("mover_lugares", { items: [origen], destino_id: destinoId, antes_de: antesDe });
    if (!r.ok) { aviso(r.error, "error"); return; }
    aplicarArbol(r);
    if (destinoId !== null) { ml.abiertas.add(destinoId); guardarAbiertas(); window.Lugares.refrescar(); }
  }

  // ------------------------------------------------------------------ arranque
  function conectarEventos() {
    const filasEl = $("lg-filas");
    filasEl.addEventListener("click", alClic);
    filasEl.addEventListener("dblclick", alDobleClic);
    filasEl.addEventListener("contextmenu", alMenu);
    filasEl.addEventListener("dragstart", alArrastrar);
    filasEl.addEventListener("dragover", alSobrevolar);
    filasEl.addEventListener("dragleave", (e) => { if (!e.relatedTarget || !filasEl.contains(e.relatedTarget)) limpiarMarcasDrop(); });
    filasEl.addEventListener("drop", alSoltar);
    filasEl.addEventListener("dragend", () => { ml.arrastre = null; limpiarMarcasDrop(); });
    document.addEventListener("mousedown", (e) => { if (!e.target.closest(".ml-menu")) cerrarMenu(); });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      cerrarMenu();
      if (ml.trabajo && !Dialogo.abierto) limpiarTrabajo();
    });
    window.addEventListener("blur", cerrarMenu);
  }

  function buscarLugares(texto) {
    const palabras = normal(texto).split(/\s+/).filter(Boolean);
    return [...ml.elementos.values()].filter((e) => palabras.every((p) => normal(e.nombre).includes(p))).slice(0, 8)
      .map((e) => ({ titulo: e.nombre, detalle: `${TITULO[e.tipo] || e.tipo} · ${rutaCarpeta(e.carpeta_id)}`, id: e.id }));
  }

  async function iniciar(ctx) {
    ml.ctx = ctx;
    const mapa = ctx.mapa;
    mapa.createPane("mlPoligonos").style.zIndex = 365;
    mapa.createPane("mlLineas").style.zIndex = 375;
    mapa.createPane("mlPuntos").style.zIndex = 615;
    ml.grupo = L.layerGroup().addTo(mapa);
    if (mapa.pm && mapa.pm.setLang) mapa.pm.setLang("es");
    document.body.insertAdjacentHTML("beforeend", `<input type="file" id="ml-archivo" accept=".kmz,.kml" hidden><div id="ml-ayuda" class="ml-ayuda" hidden></div>`);
    if (window.DibujarRed) window.DibujarRed.iniciar({ mapa, aviso });
    if (window.KmzCambios) window.KmzCambios.iniciar({ mapa, aviso });
    if (window.ImportarKmz) window.ImportarKmz.iniciar({ mapa, aviso });
    if (window.Masivas) window.Masivas.iniciar({ mapa, aviso, api: () => ctx.api });
    window.Lugares.registrarFilas({ id: "ml", filas, html: htmlFila });
    conectarEventos();
    if (window.Buscador) window.Buscador.registrarFuente({ id: "lugares", titulo: "Mis lugares", buscar: async (t) => buscarLugares(t), elegir: (it) => volarA(it.id) });
    try {
      const p = await ctx.api.preferencias();
      const guardadas = (p && p.preferencias && p.preferencias.mis_lugares_abiertas) || null;
      if (guardadas) ml.abiertas = new Set(guardadas.map((v) => (/^\d+$/.test(v) ? Number(v) : v)));
    } catch (e) { /* defaults */ }
    window.Redes.cuandoListo(async () => {
      if (!window.Redes.disponible || !(await cargar())) return;
      // the pin of a searched coordinate can be saved here (its button stays disabled while the module is not available)
      if (window.Pin) window.Pin.guardarEnMisLugares = (lat, lon) => nuevo("marca", null, { lat, lon, nombre: "Coordenada buscada" });
    });
  }

  const nombreRed = (tipo) => `${TITULO[tipo]} ${[...ml.elementos.values()].filter((x) => x.tipo === tipo).length + 1}`;
  /** The network elements (own folders, visible) a cable can be glued to. */
  function elementosRed() {
    return [...ml.elementos.values()].filter((e) => window.DibujarRed.RED.includes(e.tipo) && visible(e) && (ml.carpetas.get(e.carpeta_id) || {}).propia)
      .map((e) => ({ id: e.id, tipo: e.tipo, nombre: e.nombre, latlng: latlngs(e.geom) }));
  }
  /** A cable drawn with the magnet (DibujarRed): its window opens with the line on the map. */
  async function abrirCable({ carpetaId, latlngs: puntos, origen_id, destino_id }) {
    await abrirDialogo({ tipo: "cable", carpetaId, latlngsIniciales: puntos, extremos: { origen_id, destino_id } });
    if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo("cable");
  }

  window.MisLugares = { iniciar, nuevo, editar, volarA, cargar, elementosRed, abrirCable, get estado() { return { carpetas: ml.carpetas.size, elementos: ml.elementos.size, listo: ml.listo }; },
                        get trabajando() { return !!ml.trabajo || !!ml.modo || !!(window.DibujarRed && window.DibujarRed.dibujando); }, _ml: ml };
})();
