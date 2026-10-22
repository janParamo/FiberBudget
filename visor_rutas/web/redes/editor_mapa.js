/* Editor de red del proyecto en el mapa principal (fase 3 del módulo de redes).
 *
 * Al abrir un proyecto (menú Proyectos → clic en la tarjeta) el mapa entra en modo edición: se
 * siguen viendo las capas del visor (Lugares/KMZ, Visio, ruta) y encima los elementos del proyecto.
 *   - Paleta: Poste, Mufa, Cliente, Nodo/OLT (arrastrar y soltar en el mapa, o clic y clic), Cable
 *     (clic en el elemento de inicio, puntos intermedios que se pegan a postes y mufas, y el
 *     elemento final) y Nota (texto con formato, Quill; suelta o anclada a un elemento).
 *   - Cada elemento soltado pide su nombre (obligatorio) y sus datos.
 *   - Seleccionar (clic), mover (arrastrar; los cables pegados lo siguen), editar (F2 o doble
 *     clic en postes/clientes), duplicar, eliminar (Supr; pregunta si tiene cables).
 *   - Cable seleccionado: sus vértices se arrastran (cerca de un poste o mufa se pegan), doble
 *     clic en un vértice lo quita, clic en "+" a mitad de tramo agrega uno.
 *   - Metraje del cable con su detalle al pasar el mouse (reglas diseno_red de business_rules.yaml).
 *   - Deshacer / rehacer (Ctrl+Z / Ctrl+Y) y guardado explícito (Ctrl+S); aviso de cambios sin guardar.
 *   - Enter (o doble clic) sobre una mufa: del proyecto → editor de mufa (fase 4); existente de la
 *     red (KMZ o Visio) → su diagrama Visio, con el visor de "Ver diagrama".
 * Todo se guarda con Redes.llamar("guardar_red") en una sola transacción (visor_rutas/redes/red.py).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const IMAN_PX = 18;
  const TIPOS = {
    poste: { titulo: "Poste", subtipos: [["ideay_tubular", "Ideay tubular"], ["ideay_8_120", "Ideay 8/120"], ["ideay_9_120", "Ideay 9/120"], ["madera", "Madera"], ["concreto", "Concreto"]] },
    mufa: { titulo: "Mufa", subtipos: [["empalme", "Empalme"], ["distribucion", "Distribución (FDT)"], ["terminal", "Terminal (FAT)"], ["reserva", "Reserva"]] },
    cliente: { titulo: "Casa de cliente", subtipos: [] },
    nodo: { titulo: "Nodo / OLT", subtipos: [["olt", "OLT"], ["nodo", "Nodo"], ["mini_nodo", "Mini nodo"]] },
    odf: { titulo: "ODF", subtipos: [] },
  };
  const textoHilos = (c) => (c.hilos == null ? "hilos desconocidos" : `${c.hilos} hilos`);
  const COLOR_POSTE = { concreto: "#9aa3ad", ideay_tubular: "#1e4fa8", ideay_8_120: "#2f6fdb", ideay_9_120: "#6aa0ff", madera: "#8b5a2b", ideay: "#2f6fdb", metal: "#c0c7cf", cliente: "#f08c00" };
  // poles drawn before the list changed keep their type: shown (and kept when edited) but no longer offered for new ones
  const POSTE_LEGADO = [["ideay", "IDEAY"], ["metal", "Metal"], ["cliente", "Cliente"]];
  const CLASES = { troncal: "Troncal", distribucion: "Distribución", acometida: "Acometida" };

  const ed = {
    activo: false, proyecto: null, puedeEditar: false, reglas: null,
    elementos: new Map(), cables: new Map(), notas: new Map(),
    borrados: { elementos: new Map(), cables: new Map(), notas: new Map() },    // id -> version
    sucios: new Set(),                       // "elementos:5", "cables:n3"...
    temporal: 0, pilas: { deshacer: [], rehacer: [] },
    seleccion: null,                         // {tipo: "elementos"|"cables"|"notas", id}
    modo: null,                              // null | "colocar" | "cable" | "nota"
    colocar: null, cableNuevo: null, edicion: null,
    mapa: null, capas: null, marcadores: new Map(), lineas: new Map(), notasCapa: new Map(), quill: null,
    guardando: false,
  };

  const clave = (tipo, id) => `${tipo}:${id}`;
  const nuevoId = () => `n${++ed.temporal}`;
  const esNuevo = (id) => typeof id === "string";
  const mensaje = (t, tipo) => (window.visor && window.visor.mensaje ? window.visor.mensaje(t, tipo) : null);

  // ------------------------------------------------------------------ metraje (igual que redes/metraje.py)
  function longitud(puntos) {
    let total = 0;
    for (let i = 1; i < puntos.length; i++) {
      const [la1, lo1] = puntos[i - 1], [la2, lo2] = puntos[i];
      const p1 = la1 * Math.PI / 180, p2 = la2 * Math.PI / 180, dp = p2 - p1, dl = (lo2 - lo1) * Math.PI / 180;
      const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
      total += 2 * 6371008.8 * Math.asin(Math.sqrt(Math.min(1, a)));
    }
    return total;
  }
  function metraje(c) {
    const r = ed.reglas || {};
    const lineal = longitud(c.vertices.map((v) => [v.lat, v.lon]));
    const tipos = [ed.elementos.get(c.origen_id), ed.elementos.get(c.destino_id)].map((e) => (e ? e.tipo : ""));
    const cuenta = (t) => tipos.filter((x) => x === t).length;
    const intervalo = r.reserva_tendido_intervalo_m || 0;
    const nTend = intervalo > 0 && lineal > 0 ? Math.ceil(Math.round(lineal / intervalo * 1e6) / 1e6) : 0;
    const d = {
      lineal, contingencia: lineal * (r.contingencia_porcentaje || 0) + (r.contingencia_m || 0),
      nodo: cuenta("nodo") * (r.salida_nodo_m || 0),
      mufa: [cuenta("mufa"), r.reserva_por_mufa_m || 0], tendido: [nTend, intervalo, r.reserva_tendido_porcentaje || 0],
      cruce: [c.cruces || 0, r.reserva_por_cruce_m || 0], cliente: [cuenta("cliente"), r.reserva_extremo_cliente_m || 0],
    };
    const suma = lineal + d.contingencia + d.nodo + d.mufa[0] * d.mufa[1] + d.tendido[0] * d.tendido[1] * d.tendido[2]
      + d.cruce[0] * d.cruce[1] + d.cliente[0] * d.cliente[1];
    d.total = Math.ceil(Math.round(suma * 1e6) / 1e6);
    return d;
  }
  const m1 = (v) => `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })} m`;
  function htmlMetraje(c) {
    const d = metraje(c);
    return `<div class="er-metraje"><b>${esc(c.nombre)}</b> · ${esc(CLASES[c.clase] || c.clase)} ${esc(c.tipo)} ${textoHilos(c)}
      <div class="er-met-total">METRAJE = ${m1(d.total)}</div>
      <div>Detalle del metraje:</div>
      <div>› Distancia lineal = ${m1(d.lineal)}</div>
      <div>› Contingencia = ${m1(d.contingencia)}</div>
      <div>› Salida de nodo = ${m1(d.nodo)}</div>
      <div>› Reservas por mufa: ${d.mufa[0]} (und × ${m1(d.mufa[1])}) = ${m1(d.mufa[0] * d.mufa[1])}</div>
      <div>› Reservas por tendido: ${d.tendido[0]} (cada ${m1(d.tendido[1])} × ${Math.round(d.tendido[2] * 100)} %) = ${m1(d.tendido[0] * d.tendido[1] * d.tendido[2])}</div>
      <div>› Reservas por cruce: ${d.cruce[0]} (und × ${m1(d.cruce[1])}) = ${m1(d.cruce[0] * d.cruce[1])}</div>
      ${d.cliente[1] ? `<div>› Reservas en cliente: ${d.cliente[0]} (und × ${m1(d.cliente[1])}) = ${m1(d.cliente[0] * d.cliente[1])}</div>` : ""}
      <div class="nota">${esc(nombreDe(c.origen_id))} → ${esc(nombreDe(c.destino_id))}</div></div>`;
  }
  const nombreDe = (id) => (ed.elementos.get(id) || {}).nombre || "?";

  // ------------------------------------------------------------------ íconos
  function svgElemento(e, seleccionado) {
    const borde = seleccionado ? "#ffe600" : "#1a1a1a";
    const g = seleccionado ? 3 : 1.5;
    if (e.tipo === "poste") {
      return { html: `<svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="${COLOR_POSTE[e.subtipo] || "#9aa3ad"}" stroke="${borde}" stroke-width="${g}"/></svg>`, t: 16 };
    }
    if (e.tipo === "mufa") {
      const forma = e.subtipo === "terminal"
        ? `<circle cx="11" cy="11" r="8" fill="#fff" stroke="#d6249f" stroke-width="4"/>`                 // FAT: magenta circle
        : e.subtipo === "distribucion"
          ? `<rect x="3" y="3" width="16" height="16" fill="#fff" stroke="#e6c200" stroke-width="4"/>`   // FDT: yellow square
          : e.subtipo === "reserva"
            ? `<circle cx="11" cy="11" r="7.5" fill="none" stroke="#5a2600" stroke-width="2"/><circle cx="11" cy="11" r="4" fill="none" stroke="#ff8c00" stroke-width="2"/>`   // cable coil
            : `<ellipse cx="11" cy="11" rx="9" ry="6.5" fill="#ff8c00" stroke="#5a2600" stroke-width="2"/>`;
      const halo = seleccionado ? `<circle cx="11" cy="11" r="10.5" fill="none" stroke="#ffe600" stroke-width="2"/>` : "";
      return { html: `<svg width="22" height="22">${forma}${halo}</svg>`, t: 22 };
    }
    if (e.tipo === "odf") {
      return { html: `<svg width="22" height="22"><rect x="2" y="4" width="18" height="14" rx="2" fill="#4a5568" stroke="${borde}" stroke-width="${g}"/><path d="M6 8h10M6 11h10M6 14h10" stroke="#9ae6b4" stroke-width="1.5"/></svg>`, t: 22 };
    }
    if (e.tipo === "cliente") {
      return { html: `<svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2 2 11h3v10h5v-6h4v6h5V11h3z" fill="#0a9d57" stroke="${borde}" stroke-width="${g}"/></svg>`, t: 22 };
    }
    return { html: `<svg width="24" height="22"><path d="M12 2 22 20H2z" fill="#f5b400" stroke="${borde}" stroke-width="${g + 0.5}"/></svg>`, t: 22 };
  }
  function iconoDe(e, seleccionado) {
    const { html, t } = svgElemento(e, seleccionado);
    return L.divIcon({ className: "icono er-icono", html, iconSize: [t, t], iconAnchor: [t / 2, t / 2], tooltipAnchor: [0, -t / 2] });
  }

  // ------------------------------------------------------------------ estado y deshacer
  function instantanea() {
    return JSON.stringify({
      elementos: [...ed.elementos.values()], cables: [...ed.cables.values()], notas: [...ed.notas.values()],
      borrados: Object.fromEntries(Object.entries(ed.borrados).map(([k, v]) => [k, [...v]])), sucios: [...ed.sucios], temporal: ed.temporal,
    });
  }
  function restaurar(texto) {
    const s = JSON.parse(texto);
    ed.elementos = new Map(s.elementos.map((e) => [e.id, e]));
    ed.cables = new Map(s.cables.map((c) => [c.id, c]));
    ed.notas = new Map(s.notas.map((n) => [n.id, n]));
    ed.borrados = Object.fromEntries(Object.entries(s.borrados).map(([k, v]) => [k, new Map(v)]));
    ed.sucios = new Set(s.sucios);
    ed.temporal = s.temporal;
  }
  /** Call BEFORE a change: keeps the state to go back to. */
  function antesDeCambiar() {
    ed.pilas.deshacer.push(instantanea());
    if (ed.pilas.deshacer.length > 200) ed.pilas.deshacer.shift();
    ed.pilas.rehacer = [];
  }
  function deshacer() {
    if (!ed.pilas.deshacer.length) return;
    ed.pilas.rehacer.push(instantanea());
    restaurar(ed.pilas.deshacer.pop());
    ed.seleccion = null;
    pintarTodo();
  }
  function rehacer() {
    if (!ed.pilas.rehacer.length) return;
    ed.pilas.deshacer.push(instantanea());
    restaurar(ed.pilas.rehacer.pop());
    ed.seleccion = null;
    pintarTodo();
  }
  const marcarSucio = (tipo, id) => ed.sucios.add(clave(tipo, id));
  const nCambios = () => ed.sucios.size + ed.borrados.elementos.size + ed.borrados.cables.size + ed.borrados.notas.size;

  function actualizarBarra() {
    const n = nCambios();
    $("er-cambios").textContent = n ? `${n} cambio${n === 1 ? "" : "s"} sin guardar` : "Guardado";
    $("er-cambios").classList.toggle("pendiente", !!n);
    $("er-guardar").disabled = !n || ed.guardando || !ed.puedeEditar;
    $("er-deshacer").disabled = !ed.pilas.deshacer.length;
    $("er-rehacer").disabled = !ed.pilas.rehacer.length;
  }

  // ------------------------------------------------------------------ dibujo
  function pintarTodo() {
    if (!ed.capas) return;
    ed.capas.elementos.clearLayers();
    ed.capas.cables.clearLayers();
    ed.capas.notas.clearLayers();
    ed.capas.edicion.clearLayers();
    ed.marcadores.clear();
    ed.lineas.clear();
    ed.notasCapa.clear();
    ed.cables.forEach((c) => pintarCable(c));
    ed.elementos.forEach((e) => pintarElemento(e));
    ed.notas.forEach((n) => pintarNota(n));
    if (ed.seleccion && ed.seleccion.tipo === "cables") manijasCable(ed.cables.get(ed.seleccion.id));
    pintarInspector();
    actualizarBarra();
  }

  function pintarElemento(e) {
    if (e.lat == null) return;                 // migrated without a location: listed, not drawn
    const sel = ed.seleccion && ed.seleccion.tipo === "elementos" && ed.seleccion.id === e.id;
    const m = L.marker([e.lat, e.lon], { icon: iconoDe(e, sel), draggable: ed.puedeEditar && !ed.modo, pane: "erElementos",
                                         keyboard: false, riseOnHover: true, zIndexOffset: sel ? 1000 : 0 });
    m.bindTooltip(`${esc(e.nombre)}<span class="nota"> · ${esc(etiquetaTipo(e))}</span>`, { direction: "top", className: "hover" });
    m.on("click", (ev) => { L.DomEvent.stop(ev); clicElemento(e, ev); });
    m.on("dblclick", (ev) => { L.DomEvent.stop(ev); abrirElemento(e); });
    m.on("dragstart", () => { antesDeCambiar(); seleccionar("elementos", e.id, false); });
    m.on("drag", () => {
      const ll = m.getLatLng();
      e.lat = ll.lat; e.lon = ll.lng;
      seguirElemento(e, false);
    });
    m.on("dragend", () => { marcarSucio("elementos", e.id); seguirElemento(e, true); pintarTodo(); });
    m.addTo(ed.capas.elementos);
    ed.marcadores.set(e.id, m);
  }

  function etiquetaTipo(e) {
    const sub = ([...TIPOS[e.tipo].subtipos, ...(e.tipo === "poste" ? POSTE_LEGADO : [])].find(([v]) => v === e.subtipo) || [])[1];
    return TIPOS[e.tipo].titulo + (sub ? ` ${sub}` : "") + (e.codigo ? ` · ${e.codigo}` : "");
  }

  /** Cable ends and the vertices stuck to an element follow it (and the notes anchored to it). */
  function seguirElemento(e, marcar) {
    ed.cables.forEach((c) => {
      let cambio = false;
      c.vertices.forEach((v) => { if (v.elemento_id === e.id) { v.lat = e.lat; v.lon = e.lon; cambio = true; } });
      if (cambio) {
        const linea = ed.lineas.get(c.id);
        if (linea) linea.forEach((l) => l.setLatLngs(c.vertices.map((v) => [v.lat, v.lon])));
        if (marcar) marcarSucio("cables", c.id);
      }
    });
    ed.notas.forEach((n) => {
      if (n.elemento_id === e.id) {
        const mk = ed.notasCapa.get(n.id);
        if (mk) mk.setLatLng([e.lat, e.lon]);
      }
    });
  }

  function pintarCable(c) {
    const sel = ed.seleccion && ed.seleccion.tipo === "cables" && ed.seleccion.id === c.id;
    const pts = c.vertices.map((v) => [v.lat, v.lon]);
    const grosor = c.clase === "troncal" ? 5 : c.clase === "acometida" ? 2.5 : 3.5;
    const halo = L.polyline(pts, { color: sel ? "#ffe600" : "#111", weight: grosor + (sel ? 6 : 3), opacity: sel ? 0.9 : 0.55,
                                   pane: "erCables", interactive: false });
    const linea = L.polyline(pts, { color: c.color, weight: grosor, opacity: 1, pane: "erCables",
                                    dashArray: c.tipo === "FLAT" ? "10 5" : null });
    linea.bindTooltip(() => htmlMetraje(c), { sticky: true, className: "er-tooltip", direction: "top" });
    linea.on("click", (ev) => { L.DomEvent.stop(ev); if (!ed.modo) seleccionar("cables", c.id); });
    halo.addTo(ed.capas.cables);
    linea.addTo(ed.capas.cables);
    ed.lineas.set(c.id, [halo, linea]);
  }

  function manijasCable(c) {
    ed.capas.edicion.clearLayers();
    if (!c || !ed.puedeEditar) return;
    c.vertices.forEach((v, i) => {
      if (i === 0 || i === c.vertices.length - 1) return;                       // the ends belong to their elements
      const h = L.marker([v.lat, v.lon], { draggable: true, pane: "erManijas", keyboard: false,
        icon: L.divIcon({ className: `er-vertice${v.elemento_id != null ? " pegado" : ""}`, iconSize: [12, 12] }) });
      h.bindTooltip(v.elemento_id != null ? `Pegado a ${esc(nombreDe(v.elemento_id))} · arrastre para despegar` : "Arrastre (cerca de un poste o mufa se pega) · doble clic para quitar",
                    { direction: "top", className: "hover" });
      h.on("dragstart", () => antesDeCambiar());
      h.on("drag", () => {
        const ll = h.getLatLng();
        v.lat = ll.lat; v.lon = ll.lng; v.elemento_id = null;
        ed.lineas.get(c.id).forEach((l) => l.setLatLngs(c.vertices.map((x) => [x.lat, x.lon])));
      });
      h.on("dragend", () => {
        const e = imanElemento(h.getLatLng(), (x) => x.id !== c.origen_id && x.id !== c.destino_id);
        if (e) { v.lat = e.lat; v.lon = e.lon; v.elemento_id = e.id; }
        marcarSucio("cables", c.id);
        pintarTodo();
      });
      h.on("dblclick", (ev) => {
        L.DomEvent.stop(ev);
        antesDeCambiar();
        c.vertices.splice(i, 1);
        marcarSucio("cables", c.id);
        pintarTodo();
      });
      h.addTo(ed.capas.edicion);
    });
    for (let i = 1; i < c.vertices.length; i++) {                               // "+" between two vertices
      const a = c.vertices[i - 1], b = c.vertices[i];
      const mitad = L.marker([(a.lat + b.lat) / 2, (a.lon + b.lon) / 2], { pane: "erManijas", keyboard: false,
        icon: L.divIcon({ className: "er-mitad", html: "+", iconSize: [14, 14] }) });
      mitad.bindTooltip("Agregar un vértice aquí", { direction: "top", className: "hover" });
      mitad.on("click", (ev) => {
        L.DomEvent.stop(ev);
        antesDeCambiar();
        c.vertices.splice(i, 0, { lat: (a.lat + b.lat) / 2, lon: (a.lon + b.lon) / 2, elemento_id: null });
        marcarSucio("cables", c.id);
        pintarTodo();
      });
      mitad.addTo(ed.capas.edicion);
    }
  }

  function pintarNota(n) {
    const e = n.elemento_id != null ? ed.elementos.get(n.elemento_id) : null;
    const pos = e ? [e.lat, e.lon] : [n.lat, n.lon];
    if (pos[0] == null) return;
    const sel = ed.seleccion && ed.seleccion.tipo === "notas" && ed.seleccion.id === n.id;
    const m = L.marker(pos, { pane: "erNotas", draggable: ed.puedeEditar && !e && !ed.modo, keyboard: false,
      icon: L.divIcon({ className: `er-nota${sel ? " sel" : ""}${e ? " anclada" : ""}`, iconSize: null,
                        html: `<div class="er-nota-cuerpo ql-editor" style="width:${n.ancho || 220}px">${n.html}</div>` }) });
    m.on("click", (ev) => { L.DomEvent.stop(ev); if (!ed.modo) seleccionar("notas", n.id); });
    m.on("dblclick", (ev) => { L.DomEvent.stop(ev); if (ed.puedeEditar) abrirNota(n); });
    m.on("dragstart", () => antesDeCambiar());
    m.on("dragend", () => { const ll = m.getLatLng(); n.lat = ll.lat; n.lon = ll.lng; marcarSucio("notas", n.id); actualizarBarra(); });
    m.addTo(ed.capas.notas);
    ed.notasCapa.set(n.id, m);
  }

  // ------------------------------------------------------------------ selección e inspector
  function seleccionar(tipo, id, repintar = true) {
    ed.seleccion = tipo ? { tipo, id } : null;
    window.__mufaExistente = null;
    if (repintar) pintarTodo();
  }

  /** Phase 7: report a problem / add a task about the selected element or cable. */
  function botonesTareas() {
    return (window.Problemas ? `<button type="button" class="btn btn-chico" data-er="problema" title="Reportar un problema en este lugar">⚠ Problema</button>` : "")
      + (window.Pendientes && ed.puedeEditar ? `<button type="button" class="btn btn-chico" data-er="pendiente" title="Agregar una tarea pendiente">Pendiente</button>` : "");
  }

  function pintarInspector() {
    const caja = $("er-inspector");
    const s = ed.seleccion;
    const obj = s && ed[s.tipo].get(s.id);
    if (!obj) { caja.hidden = true; return; }
    let titulo, detalle, botones = "";
    if (s.tipo === "elementos") {
      titulo = obj.nombre;
      const cables = [...ed.cables.values()].filter((c) => c.vertices.some((v) => v.elemento_id === obj.id)).length;
      detalle = `${etiquetaTipo(obj)}${obj.propiedades && obj.propiedades.capacidad ? ` · ${obj.propiedades.capacidad} hilos` : ""}`
        + `${obj.propiedades && obj.propiedades.id_servicio ? ` · ID ${esc(obj.propiedades.id_servicio)}` : ""} · ${cables} cable${cables === 1 ? "" : "s"}`;
      if (obj.tipo === "mufa" || obj.tipo === "odf") botones += `<button type="button" class="btn btn-chico" data-er="abrir">Abrir ${obj.tipo === "odf" ? "ODF" : "mufa"} (Enter)</button>`;
      if (!esNuevo(obj.id)) botones += botonesTareas();
      if (ed.puedeEditar) botones += `<button type="button" class="btn btn-chico" data-er="editar">Editar (F2)</button>
        <button type="button" class="btn btn-chico" data-er="duplicar">Duplicar</button>
        <button type="button" class="btn btn-chico peligro" data-er="eliminar">Eliminar (Supr)</button>`;
    } else if (s.tipo === "cables") {
      const d = metraje(obj);
      titulo = obj.nombre;
      detalle = `${esc(CLASES[obj.clase])} ${esc(obj.tipo)} · ${obj.hilos == null ? "hilos desconocidos" : `${obj.hilos} hilos (${obj.configuracion || `${obj.hilos_por_buffer} por buffer`}${obj.configuracion_estimada ? ", estimada" : ""})`} · `
        + `<b>${m1(d.total)}</b> (lineal ${m1(d.lineal)}) · ${esc(nombreDe(obj.origen_id))} → ${esc(nombreDe(obj.destino_id))}`;
      if (!esNuevo(obj.id) && window.Trazado && obj.hilos) {
        botones += `<label class="er-trazar">Hilo <input id="er-hilo-num" type="number" min="1" max="${obj.hilos}" value="1"></label>
          <button type="button" class="btn btn-chico" data-er="trazar" title="Seguir ese hilo de punta a punta">Trazar hilo</button>`;
      }
      if (!esNuevo(obj.id)) botones += botonesTareas();
      if (ed.puedeEditar) botones += `<button type="button" class="btn btn-chico" data-er="editar">Editar (F2)</button>
        <button type="button" class="btn btn-chico peligro" data-er="eliminar">Eliminar (Supr)</button>`;
    } else {
      titulo = "Nota";
      detalle = obj.elemento_id != null ? `Anclada a ${esc(nombreDe(obj.elemento_id))}` : "En el mapa (arrástrela para moverla)";
      if (ed.puedeEditar) botones += `<button type="button" class="btn btn-chico" data-er="editar">Editar</button>
        <button type="button" class="btn btn-chico peligro" data-er="eliminar">Eliminar (Supr)</button>`;
    }
    caja.innerHTML = `<div class="er-insp-titulo">${esc(titulo)}</div><div class="er-insp-detalle">${detalle}</div>
      <div class="er-insp-botones">${botones}<button type="button" class="btn-icono" data-er="deseleccionar" title="Esc">✕</button></div>`;
    caja.hidden = false;
  }

  // ------------------------------------------------------------------ imán (snap)
  /** The project element nearest to `latlng` within IMAN_PX on screen (filter optional). */
  function imanElemento(latlng, filtro) {
    const p = ed.mapa.latLngToContainerPoint(latlng);
    let mejor = null, distancia = IMAN_PX;
    ed.elementos.forEach((e) => {
      if (e.lat == null || (filtro && !filtro(e))) return;
      const d = ed.mapa.latLngToContainerPoint([e.lat, e.lon]).distanceTo(p);
      if (d <= distancia) { mejor = e; distancia = d; }
    });
    return mejor;
  }

  // ------------------------------------------------------------------ elementos: crear / editar
  let formularioElemento = null;      // {tipo, objeto?, lat, lon}

  function abrirFormElemento(tipo, objeto, lat, lon) {
    formularioElemento = { tipo, objeto, lat, lon };
    const t = TIPOS[tipo];
    $("er-el-titulo").textContent = objeto ? `${t.titulo}: ${objeto.nombre}` : `Nuevo: ${t.titulo}`;
    const cuenta = [...ed.elementos.values()].filter((e) => e.tipo === tipo).length + 1;
    const sugerido = { poste: `P-${String(cuenta).padStart(2, "0")}`, mufa: `MF ${cuenta}`, cliente: `Cliente ${cuenta}`, nodo: `Nodo ${cuenta}` }[tipo];
    $("er-el-nombre").value = objeto ? objeto.nombre : sugerido;
    $("er-el-subtipo-campo").hidden = !t.subtipos.length;
    $("er-el-subtipo").innerHTML = t.subtipos.map(([v, txt]) => `<option value="${v}">${esc(txt)}</option>`).join("");
    const legado = tipo === "poste" && objeto && POSTE_LEGADO.find(([v]) => v === objeto.subtipo);
    if (legado) $("er-el-subtipo").insertAdjacentHTML("beforeend", `<option value="${legado[0]}">${esc(legado[1])} (anterior)</option>`);
    if (objeto && objeto.subtipo) $("er-el-subtipo").value = objeto.subtipo;
    const prop = (objeto && objeto.propiedades) || {};
    $("er-el-mufa").hidden = tipo !== "mufa";
    $("er-el-cliente").hidden = tipo !== "cliente";
    $("er-el-capacidad").value = prop.capacidad || "";
    $("er-el-bandejas").value = prop.bandejas ?? "";
    $("er-el-codigo").value = (objeto && objeto.codigo) || "";
    $("er-el-id_servicio").value = prop.id_servicio || "";
    $("er-el-descripcion").value = prop.descripcion || "";
    Redes.estadoEn($("er-el-estado"), "");
    $("er-el-nombre").closest(".vp-campo").classList.remove("invalido");
    $("er-el-nombre").closest(".vp-campo").querySelector("small").textContent = "";
    $("modal-er-elemento").hidden = false;
    $("er-el-nombre").focus();
    $("er-el-nombre").select();
  }

  function aceptarElemento(ev) {
    ev.preventDefault();
    const f = formularioElemento;
    if (!f) return;
    const nombre = $("er-el-nombre").value.trim();
    if (!nombre) {
      $("er-el-nombre").closest(".vp-campo").classList.add("invalido");
      $("er-el-nombre").closest(".vp-campo").querySelector("small").textContent = "El nombre es obligatorio";
      return;
    }
    const codigo = $("er-el-codigo").value.trim().toUpperCase();
    if (f.tipo === "cliente" && codigo && !/^C\d{3,8}$/.test(codigo)) {
      Redes.estadoEn($("er-el-estado"), "El código de cliente es C seguido de números (C12345)", "error");
      return;
    }
    const propiedades = {};
    if (f.tipo === "mufa") {
      if ($("er-el-capacidad").value) propiedades.capacidad = Number($("er-el-capacidad").value);
      if ($("er-el-bandejas").value !== "") propiedades.bandejas = Number($("er-el-bandejas").value);
    }
    if (f.tipo === "cliente" && $("er-el-id_servicio").value.trim()) propiedades.id_servicio = $("er-el-id_servicio").value.trim();
    if ($("er-el-descripcion").value.trim()) propiedades.descripcion = $("er-el-descripcion").value.trim();
    antesDeCambiar();
    const datos = { nombre, subtipo: TIPOS[f.tipo].subtipos.length ? $("er-el-subtipo").value : null,
                    codigo: f.tipo === "cliente" ? codigo || null : (f.objeto ? f.objeto.codigo : null), propiedades };
    let e;
    if (f.objeto) {
      e = Object.assign(f.objeto, datos);
    } else {
      e = { id: nuevoId(), tipo: f.tipo, lat: f.lat, lon: f.lon, version: null, ref_externa: null, ...datos };
      ed.elementos.set(e.id, e);
    }
    marcarSucio("elementos", e.id);
    $("modal-er-elemento").hidden = true;
    formularioElemento = null;
    ed.seleccion = { tipo: "elementos", id: e.id };
    pintarTodo();
  }

  function clicElemento(e) {
    if (ed.modo === "cable") return clicCable(L.latLng(e.lat, e.lon), e);
    if (ed.modo === "nota") return clicNota(L.latLng(e.lat, e.lon), e);
    if (ed.modo) return;
    seleccionar("elementos", e.id);
  }

  /** Enter / double click on a project element: mufa -> its editor (phase 4); others -> edit data. */
  function abrirElemento(e) {
    if (e.tipo === "mufa" || e.tipo === "odf") {
      if (typeof e.id === "string") { mensaje(`Guarde la red antes de abrir ${e.nombre} (es nueva)`, "error"); return; }
      if (nCambios()) { mensaje("Guarde (o deshaga) los cambios del mapa antes de abrir el editor de mufa", "error"); return; }
      if (window.EditorMufa) window.EditorMufa.abrir(e.id, e.nombre);
      return;
    }
    if (ed.puedeEditar) abrirFormElemento(e.tipo, e);
  }

  function duplicarElemento(e) {
    antesDeCambiar();
    const p = ed.mapa.latLngToContainerPoint([e.lat, e.lon]).add([28, 0]);
    const ll = ed.mapa.containerPointToLatLng(p);
    const copia = { ...JSON.parse(JSON.stringify(e)), id: nuevoId(), version: null, nombre: `${e.nombre} (copia)`,
                    lat: ll.lat, lon: ll.lng, codigo: e.tipo === "cliente" ? null : e.codigo };
    ed.elementos.set(copia.id, copia);
    marcarSucio("elementos", copia.id);
    ed.seleccion = { tipo: "elementos", id: copia.id };
    pintarTodo();
  }

  async function eliminarSeleccion() {
    const s = ed.seleccion;
    if (!s || !ed.puedeEditar) return;
    const obj = ed[s.tipo].get(s.id);
    if (!obj) return;
    const borrar = (tipo, o) => {
      ed[tipo].delete(o.id);
      ed.sucios.delete(clave(tipo, o.id));
      if (!esNuevo(o.id)) ed.borrados[tipo].set(o.id, o.version);
    };
    if (s.tipo === "elementos") {
      const cables = [...ed.cables.values()].filter((c) => c.vertices.some((v) => v.elemento_id === obj.id));
      const extremos = cables.filter((c) => c.origen_id === obj.id || c.destino_id === obj.id);
      const notas = [...ed.notas.values()].filter((n) => n.elemento_id === obj.id);
      if (cables.length) {
        const ok = await Redes.confirmar(`"${obj.nombre}" tiene ${cables.length} cable(s) conectado(s): `
          + `${cables.map((c) => c.nombre).join(", ")}. ¿Eliminarlo? Los cables que terminan en él se eliminan también; `
          + "los que solo pasan por él quedan despegados en ese punto.", "Eliminar");
        if (!ok) return;
      }
      antesDeCambiar();
      extremos.forEach((c) => borrar("cables", c));
      cables.filter((c) => !extremos.includes(c)).forEach((c) => {
        c.vertices.forEach((v) => { if (v.elemento_id === obj.id) v.elemento_id = null; });
        marcarSucio("cables", c.id);
      });
      notas.forEach((n) => { n.elemento_id = null; n.lat = obj.lat; n.lon = obj.lon; marcarSucio("notas", n.id); });
      borrar("elementos", obj);
    } else {
      antesDeCambiar();
      borrar(s.tipo, obj);
    }
    ed.seleccion = null;
    pintarTodo();
  }

  // ------------------------------------------------------------------ cables
  let formularioCable = null;        // the cable being edited (null = new)

  function abrirFormCable(cable) {
    formularioCable = cable || null;
    $("er-ca-titulo").textContent = cable ? `Cable: ${cable.nombre}` : "Nuevo cable de fibra";
    const n = ed.cables.size + 1;
    $("er-ca-nombre").value = cable ? cable.nombre : `Cable ${n}`;
    $("er-ca-clase").value = cable ? cable.clase : "distribucion";
    $("er-ca-tipo").value = cable ? cable.tipo : "ADSS";
    $("er-ca-color").value = cable ? cable.color : "#1f6feb";
    $("er-ca-hilos").value = cable ? (cable.hilos == null ? "" : String(cable.hilos)) : "12";
    $("er-ca-buffer").value = String(cable ? cable.hilos_por_buffer : 12);
    $("er-ca-cruces").value = cable ? cable.cruces || 0 : 0;
    $("er-ca-descripcion").value = (cable && cable.descripcion) || "";
    $("er-ca-aceptar").textContent = cable ? "Aceptar" : "Dibujar en el mapa";
    Redes.estadoEn($("er-ca-estado"), "");
    $("modal-er-cable").hidden = false;
    $("er-ca-nombre").focus();
    $("er-ca-nombre").select();
  }

  function datosFormCable() {
    return { nombre: $("er-ca-nombre").value.trim(), clase: $("er-ca-clase").value, tipo: $("er-ca-tipo").value,
             color: $("er-ca-color").value, hilos: $("er-ca-hilos").value === "" ? null : Number($("er-ca-hilos").value), hilos_por_buffer: Number($("er-ca-buffer").value),
             cruces: Math.max(0, Math.min(500, Number($("er-ca-cruces").value) || 0)), descripcion: $("er-ca-descripcion").value.trim() };
  }

  function aceptarCable(ev) {
    ev.preventDefault();
    const datos = datosFormCable();
    if (!datos.nombre) { Redes.estadoEn($("er-ca-estado"), "El nombre es obligatorio", "error"); return; }
    $("modal-er-cable").hidden = true;
    if (formularioCable) {
      antesDeCambiar();
      Object.assign(formularioCable, datos);
      marcarSucio("cables", formularioCable.id);
      formularioCable = null;
      pintarTodo();
      return;
    }
    if (ed.elementos.size < 2) { mensaje("Primero coloque al menos dos elementos (por ejemplo, dos mufas)", "error"); return; }
    ed.cableNuevo = { datos, vertices: [], linea: null, guia: null };
    cambiarModo("cable", "Cable: clic en el ELEMENTO DE INICIO (mufa, nodo, poste o cliente)");
  }

  function clicCable(latlng, elemento) {
    const cn = ed.cableNuevo;
    const e = elemento || imanElemento(latlng);
    if (!cn.vertices.length) {
      if (!e) { ayuda("El cable debe empezar en un elemento: haga clic sobre una mufa, nodo, poste o cliente", true); return; }
      cn.vertices.push({ lat: e.lat, lon: e.lon, elemento_id: e.id });
      ayuda(`Cable desde ${e.nombre}: clic para puntos intermedios (se pegan a los postes), y clic en el elemento final. `
        + "Doble clic o Enter termina en el último elemento · Retroceso quita un punto · Esc cancela");
    } else if (e) {
      if (e.id === cn.vertices[cn.vertices.length - 1].elemento_id) return;          // same element twice (double click)
      cn.vertices.push({ lat: e.lat, lon: e.lon, elemento_id: e.id });
      if (e.tipo !== "poste" && e.id !== cn.vertices[0].elemento_id) { terminarCable(); return; }
    } else {
      cn.vertices.push({ lat: latlng.lat, lon: latlng.lng, elemento_id: null });
    }
    dibujarCableNuevo();
  }

  function dibujarCableNuevo(raton) {
    const cn = ed.cableNuevo;
    if (!cn) return;
    const pts = cn.vertices.map((v) => [v.lat, v.lon]);
    if (!cn.linea) cn.linea = L.polyline(pts, { color: cn.datos.color, weight: 4, pane: "erManijas", interactive: false }).addTo(ed.capas.edicion);
    cn.linea.setLatLngs(pts);
    if (raton && pts.length) {
      const destino = imanElemento(raton);
      const fin = destino ? [destino.lat, destino.lon] : [raton.lat, raton.lng];
      if (!cn.guia) cn.guia = L.polyline([pts[pts.length - 1], fin], { color: cn.datos.color, weight: 2, dashArray: "6 6", pane: "erManijas", interactive: false }).addTo(ed.capas.edicion);
      cn.guia.setLatLngs([pts[pts.length - 1], fin]);
      const d = longitud([...pts, fin]);
      ayuda(`${cn.datos.nombre}: ${Math.round(d).toLocaleString("en-US")} m lineales${destino ? ` · se pega a ${destino.nombre}` : ""}`);
    }
  }

  function terminarCable() {
    const cn = ed.cableNuevo;
    if (!cn) return;
    while (cn.vertices.length && cn.vertices[cn.vertices.length - 1].elemento_id == null) cn.vertices.pop();   // end on an element
    const inicio = cn.vertices[0], fin = cn.vertices[cn.vertices.length - 1];
    if (cn.vertices.length < 2 || !fin || fin.elemento_id === inicio.elemento_id) {
      ayuda("El cable debe terminar en un elemento distinto del inicial: haga clic sobre él", true);
      return;
    }
    antesDeCambiar();
    const c = { id: nuevoId(), version: null, ...cn.datos, origen_id: inicio.elemento_id, destino_id: fin.elemento_id,
                vertices: cn.vertices.map((v) => ({ ...v })) };
    ed.cables.set(c.id, c);
    marcarSucio("cables", c.id);
    salirModo();
    ed.seleccion = { tipo: "cables", id: c.id };
    pintarTodo();
    mensaje(`Cable ${c.nombre}: ${m1(metraje(c).total)} de metraje (sin guardar)`, "ok");
  }

  // ------------------------------------------------------------------ notas
  let formularioNota = null;         // {nota?, lat, lon, elemento_id}

  function asegurarQuill() {
    if (ed.quill || !window.Quill) return;
    ed.quill = new Quill("#er-quill", {
      theme: "snow", placeholder: "Escriba la nota…",
      modules: { toolbar: [[{ font: [] }, { size: ["small", false, "large", "huge"] }], ["bold", "italic", "underline", "strike"],
                           [{ color: [] }, { background: [] }], [{ list: "ordered" }, { list: "bullet" }], [{ align: [] }], ["clean"]] },
    });
  }

  function clicNota(latlng, elemento) {
    salirModo();
    const e = elemento || imanElemento(latlng);
    abrirNota(null, e ? { elemento_id: e.id } : { lat: latlng.lat, lon: latlng.lng });
  }

  function abrirNota(nota, donde) {
    asegurarQuill();
    if (!ed.quill) { mensaje("No se pudo cargar el editor de texto (lib/quill)", "error"); return; }
    formularioNota = { nota, ...(donde || {}) };
    $("er-no-titulo").textContent = nota ? "Editar nota" : (donde && donde.elemento_id != null ? `Nota en ${nombreDe(donde.elemento_id)}` : "Nueva nota");
    ed.quill.setContents([]);
    if (nota) ed.quill.clipboard.dangerouslyPasteHTML(nota.html);     // our own saved (sanitized) HTML
    $("er-no-ancho").value = nota ? nota.ancho || 220 : 220;
    Redes.estadoEn($("er-no-estado"), "");
    $("modal-er-nota").hidden = false;
    ed.quill.focus();
  }

  function aceptarNota() {
    const html = ed.quill.root.innerHTML;
    if (!ed.quill.getText().trim()) { Redes.estadoEn($("er-no-estado"), "La nota está vacía", "error"); return; }
    const ancho = Math.max(80, Math.min(1200, Number($("er-no-ancho").value) || 220));
    antesDeCambiar();
    const f = formularioNota;
    let n = f.nota;
    if (n) Object.assign(n, { html, ancho });
    else {
      n = { id: nuevoId(), version: null, html, ancho, elemento_id: f.elemento_id ?? null, lat: f.lat ?? null, lon: f.lon ?? null };
      ed.notas.set(n.id, n);
    }
    marcarSucio("notas", n.id);
    $("modal-er-nota").hidden = true;
    formularioNota = null;
    pintarTodo();
  }

  // ------------------------------------------------------------------ modos
  function ayuda(texto, error = false) {
    const caja = $("er-ayuda");
    caja.textContent = texto || "";
    caja.hidden = !texto;
    caja.classList.toggle("error", !!error);
  }

  function cambiarModo(modo, texto) {
    ed.modo = modo;
    ed.mapa.getContainer().classList.toggle("er-modo", !!modo);
    if (modo === "cable") ed.mapa.doubleClickZoom.disable();             // double click ends the cable
    ayuda(texto);
    ed.seleccion = null;
    pintarTodo();
  }

  function salirModo() {
    if (ed.cableNuevo) { ed.capas.edicion.clearLayers(); ed.cableNuevo = null; }
    if (ed.modo === "cable") ed.mapa.doubleClickZoom.enable();
    ed.modo = null;
    ed.colocar = null;
    ed.mapa.getContainer().classList.remove("er-modo");
    document.querySelectorAll(".er-herr.activa").forEach((b) => b.classList.remove("activa"));
    ayuda("");
  }

  function alClicMapa(e) {
    if (!ed.activo) return;
    if (ed.modo === "colocar") { const tipo = ed.colocar; salirModo(); pintarTodo(); abrirFormElemento(tipo, null, e.latlng.lat, e.latlng.lng); return; }
    if (ed.modo === "ubicar") {                       // a migrated mufa without coordinate: here it is (fase 6, cola de corrección)
      const el = ed.elementos.get(ed.ubicando);
      salirModo();
      if (el) {
        antesDeCambiar();
        el.lat = e.latlng.lat; el.lon = e.latlng.lng;
        marcarSucio("elementos", el.id);
        ed.seleccion = { tipo: "elementos", id: el.id };
        mensaje(`${el.nombre} ubicada: presione Guardar para conservarla`, "ok");
      }
      pintarTodo();
      return;
    }
    if (ed.modo === "cable") { clicCable(e.latlng); return; }
    if (ed.modo === "nota") { clicNota(e.latlng); return; }
    if (ed.seleccion) seleccionar(null);
  }

  // ------------------------------------------------------------------ abrir / guardar / cerrar
  function cargarRed(r) {
    ed.proyecto = r.proyecto;
    ed.puedeEditar = !!r.proyecto.puede_editar;
    ed.reglas = r.reglas_metraje;
    ed.elementos = new Map(r.elementos.map((e) => [e.id, { ...e, propiedades: e.propiedades || {} }]));
    ed.cables = new Map(r.cables.map((c) => [c.id, c]));
    ed.notas = new Map(r.notas.map((n) => [n.id, n]));
    ed.borrados = { elementos: new Map(), cables: new Map(), notas: new Map() };
    ed.sucios = new Set();
    ed.pilas = { deshacer: [], rehacer: [] };
    ed.seleccion = null;
  }

  function prepararMapa() {
    if (ed.capas) return;
    ed.mapa = window.visor.mapa;
    const panes = { erArea: 410, erTrazado: 445, erCables: 450, erElementos: 620, erNotas: 630, erProblemas: 635, erManijas: 640 };
    Object.entries(panes).forEach(([n, z]) => { if (!ed.mapa.getPane(n)) ed.mapa.createPane(n).style.zIndex = z; });
    ed.capas = { area: L.layerGroup().addTo(ed.mapa), trazado: L.layerGroup().addTo(ed.mapa), cables: L.layerGroup().addTo(ed.mapa),
                 elementos: L.layerGroup().addTo(ed.mapa), notas: L.layerGroup().addTo(ed.mapa), problemas: L.layerGroup().addTo(ed.mapa),
                 edicion: L.layerGroup().addTo(ed.mapa) };
    ed.mapa.on("click", alClicMapa);
    ed.mapa.on("mousemove", (e) => { if (ed.modo === "cable" && ed.cableNuevo && ed.cableNuevo.vertices.length) dibujarCableNuevo(e.latlng); });
    ed.mapa.on("dblclick", (e) => { if (ed.modo === "cable") { L.DomEvent.stop(e); terminarCable(); } });
    // drag & drop from the palette
    const contenedor = ed.mapa.getContainer();
    contenedor.addEventListener("dragover", (e) => { if (ed.activo && e.dataTransfer.types.includes("text/er-tipo")) e.preventDefault(); });
    contenedor.addEventListener("drop", (e) => {
      const tipo = e.dataTransfer.getData("text/er-tipo");
      if (!ed.activo || !TIPOS[tipo]) return;
      e.preventDefault();
      const caja = contenedor.getBoundingClientRect();
      const ll = ed.mapa.containerPointToLatLng(L.point(e.clientX - caja.left, e.clientY - caja.top));
      abrirFormElemento(tipo, null, ll.lat, ll.lng);
    });
  }

  async function abrir(proyectoId) {
    if (ed.activo && ed.proyecto && ed.proyecto.id !== proyectoId && nCambios()) {
      if (!(await Redes.confirmar(`El proyecto ${ed.proyecto.nombre} tiene cambios sin guardar. ¿Descartarlos y abrir el otro?`, "Descartar"))) return false;
    }
    mensaje("Abriendo el proyecto…", "cargando");
    const r = await Redes.llamar("red_proyecto", { proyecto_id: proyectoId });
    if (!r.ok) { mensaje(r.error, "error"); return false; }
    if (window.visor) window.visor.mostrarVista("mapa");
    prepararMapa();
    cargarRed(r);
    ed.activo = true;
    document.body.classList.add("editando-red");
    $("editor-red").hidden = false;
    $("er-proyecto").textContent = `${r.proyecto.nombre} (${r.proyecto.codigo})`;
    $("er-paleta").hidden = !ed.puedeEditar;
    medirBarra();
    ed.capas.area.clearLayers();
    if (r.proyecto.area) L.geoJSON(r.proyecto.area, { pane: "erArea", interactive: false,
      style: { color: "#2f6fdb", weight: 2, dashArray: "8 6", fillOpacity: 0.04 } }).addTo(ed.capas.area);
    pintarTodo();
    const limites = L.latLngBounds([]);
    ed.elementos.forEach((e) => { if (e.lat != null) limites.extend([e.lat, e.lon]); });
    ed.capas.area.eachLayer((l) => l.getBounds && limites.extend(l.getBounds()));
    if (r.proyecto.lat != null) limites.extend([r.proyecto.lat, r.proyecto.lon]);
    if (limites.isValid()) ed.mapa.fitBounds(limites, { padding: [60, 60], maxZoom: 18 });
    const sinUbicar = [...ed.elementos.values()].filter((e) => e.lat == null).length;
    mensaje((ed.puedeEditar ? `Proyecto ${r.proyecto.nombre}: arrastre elementos de la paleta al mapa` : `Proyecto ${r.proyecto.nombre} (solo lectura)`)
      + (sinUbicar ? ` · ${sinUbicar} elemento${sinUbicar === 1 ? "" : "s"} sin ubicar (no se dibujan)` : ""), "ok");
    await cargarProblemas();
    return true;
  }

  // ------------------------------------------------------------------ trazado de hilo (fase 5)
  function trazarCable(c) {
    if (!c || esNuevo(c.id) || !window.Trazado) return;
    const n = Number($("er-hilo-num") ? $("er-hilo-num").value : 1);
    if (!Number.isInteger(n) || n < 1 || n > c.hilos) { mensaje(`El cable ${c.nombre} tiene hilos del 1 al ${c.hilos}`, "error"); return; }
    if (ed.sucios.has(`cables:${c.id}`)) mensaje("El trazado usa la red guardada: guarde para incluir sus cambios", "error");
    window.Trazado.abrir({ cable_id: c.id, numero: n });
  }

  /** Yellow glow under the cables of the trace and rings on its elements (clients labelled). */
  function pintarTrazado(t) {
    if (!ed.capas) return null;
    ed.capas.trazado.clearLayers();
    if (!t || !ed.activo || !ed.proyecto || ed.proyecto.id !== t.proyecto_id) return null;
    const limites = L.latLngBounds([]);
    t.cables.forEach((id) => {
      const c = ed.cables.get(id);
      if (!c) return;
      const pts = c.vertices.map((v) => [v.lat, v.lon]);
      L.polyline(pts, { color: "#ffd400", weight: 16, opacity: 0.75, pane: "erTrazado", interactive: false, lineCap: "round" })
        .addTo(ed.capas.trazado);
      pts.forEach((p) => limites.extend(p));
    });
    const clientes = new Set(t.resumen.clientes.map((c) => c.id));
    t.elementos.forEach((e) => {
      if (e.lat == null) return;
      const anillo = L.circleMarker([e.lat, e.lon], { radius: 15, color: "#e0a800", weight: 3, fillColor: "#ffd400", fillOpacity: 0.3,
                                                      pane: "erTrazado", interactive: false }).addTo(ed.capas.trazado);
      if (clientes.has(e.id)) anillo.bindTooltip(`✔ ${esc(e.nombre)}`, { permanent: true, direction: "right", className: "tz-etiqueta", offset: [14, 0] });
      limites.extend([e.lat, e.lon]);
    });
    return limites;
  }

  /** "Ver en el mapa" from the trace panel: opens the project if needed and frames the route. */
  async function mostrarTrazado(t) {
    if (!ed.activo || !ed.proyecto || ed.proyecto.id !== t.proyecto_id) {
      if (!(await abrir(t.proyecto_id))) return;
    } else if (window.visor) window.visor.mostrarVista("mapa");
    const limites = pintarTrazado(t);
    if (limites && limites.isValid()) ed.mapa.fitBounds(limites, { padding: [80, 80], maxZoom: 18 });
  }

  // ------------------------------------------------------------------ problemas en el mapa (fase 7.1)
  const SEVERIDAD = { baja: "Baja", media: "Media", alta: "Alta", critica: "Crítica" };
  const ESTADO_PROBLEMA = { abierto: "Abierto", en_proceso: "En proceso", cerrado: "Cerrado" };

  /** Alert icons of the open project's problems, with the strip's filter. */
  async function cargarProblemas() {
    if (!ed.capas) return;
    ed.capas.problemas.clearLayers();
    ed.problemas = new Map();
    const filtro = $("er-problemas").value;
    if (!ed.activo || !ed.proyecto || filtro === "ninguno" || !window.Problemas) return;
    const proyecto = ed.proyecto.id;
    const r = await Redes.llamar("problemas", { proyecto_id: proyecto, estado: filtro.startsWith("activos") ? "activos" : null,
                                                severidad: filtro === "activos_alta" ? "alta_o_mas" : null });
    if (!r.ok || !ed.proyecto || ed.proyecto.id !== proyecto) return;
    ed.capas.problemas.clearLayers();
    r.problemas.forEach((p) => {
      if (p.lat == null) return;
      const m = L.marker([p.lat, p.lon], { pane: "erProblemas", keyboard: false, riseOnHover: true,
        icon: L.divIcon({ className: `er-problema sev-${p.severidad} est-${p.estado}`, html: "!", iconSize: [22, 20], iconAnchor: [-2, 26] }) });
      m.bindTooltip(`⚠ ${esc(p.titulo)} · ${SEVERIDAD[p.severidad]} · ${ESTADO_PROBLEMA[p.estado]}`, { direction: "top", className: "hover" });
      m.bindPopup(() => `<div class="er-pop-problema"><b>⚠ ${esc(p.titulo)}</b>
          <div><span class="tk-sev sev-${p.severidad}">${SEVERIDAD[p.severidad]}</span> <span class="tk-est est-${p.estado}">${ESTADO_PROBLEMA[p.estado]}</span></div>
          <div class="nota">${esc(p.vinculo)} · ${esc(p.creado_por || "")} · ${esc(Redes.fecha(p.creado_en))}</div>
          ${p.descripcion ? `<div>${esc(p.descripcion.slice(0, 200))}</div>` : ""}
          ${p.miniatura ? `<img src="${p.miniatura}" alt="Foto">` : ""}
          <button type="button" class="btn btn-chico" data-er-problema="${p.id}">Abrir</button></div>`, { maxWidth: 280 });
      m.on("click", (ev) => L.DomEvent.stop(ev));
      m.addTo(ed.capas.problemas);
      ed.problemas.set(p.id, m);
    });
    $("er-problemas").title = `${r.problemas.length} problema(s) en el mapa con este filtro`;
  }

  /** "Ver en el mapa" from the Problemas view: opens the project and centres the alert icon. */
  async function mostrarProblema(p) {
    if (!ed.activo || !ed.proyecto || ed.proyecto.id !== p.proyecto_id) {
      if (!(await abrir(p.proyecto_id))) return;
    } else if (window.visor) window.visor.mostrarVista("mapa");
    if (p.estado === "cerrado" || ($("er-problemas").value === "activos_alta" && !["alta", "critica"].includes(p.severidad))
        || $("er-problemas").value === "ninguno") $("er-problemas").value = "todos";
    await cargarProblemas();
    if (p.lat == null) return;
    ed.mapa.setView([p.lat, p.lon], Math.max(ed.mapa.getZoom(), 18), { animate: false });
    const m = ed.problemas.get(p.id);
    if (m) m.openPopup();
  }

  /** The strip may take one or two rows (narrow map): the map's top controls go below it. */
  function medirBarra() {
    if (!ed.activo) return;
    document.documentElement.style.setProperty("--alto-editor", `${$("editor-red").offsetHeight}px`);
  }

  function cambiosParaGuardar() {
    const salida = { elementos: [], cables: [], notas: [] };
    ed.sucios.forEach((k) => {
      const [tipo, ...resto] = k.split(":");
      const id = resto.join(":");
      const obj = ed[tipo].get(/^n\d+$/.test(id) ? id : Number(id));
      if (obj) salida[tipo].push(obj);
    });
    Object.entries(ed.borrados).forEach(([tipo, mapa]) => mapa.forEach((version, id) => salida[tipo].push({ id, version, eliminar: true })));
    return salida;
  }

  async function guardar() {
    if (!ed.puedeEditar || ed.guardando || !nCambios()) return;
    ed.guardando = true;
    actualizarBarra();
    mensaje("Guardando el proyecto…", "cargando");
    const r = await Redes.llamar("guardar_red", { proyecto_id: ed.proyecto.id, cambios: cambiosParaGuardar() });
    ed.guardando = false;
    if (!r.ok) {
      actualizarBarra();
      if (r.conflicto) {
        if (await Redes.confirmar(`${r.error}\n\n¿Recargar el proyecto ahora? Sus cambios sin guardar se pierden.`, "Recargar")) {
          ed.sucios.clear();
          Object.values(ed.borrados).forEach((m) => m.clear());
          await abrir(ed.proyecto.id);
        }
        return;
      }
      mensaje(r.error, "error");
      return;
    }
    const seleccion = ed.seleccion;
    cargarRed(r);
    if (seleccion) {
      const id = esNuevo(seleccion.id) ? r.ids[seleccion.id] : seleccion.id;
      if (id && ed[seleccion.tipo].has(id)) ed.seleccion = { tipo: seleccion.tipo, id };
    }
    pintarTodo();
    mensaje(`Proyecto ${ed.proyecto.nombre} guardado`, "ok");
    cargarProblemas();                          // the icons follow moved elements
  }

  async function cerrar() {
    if (nCambios() && !(await Redes.confirmar(`Hay ${nCambios()} cambio(s) sin guardar en ${ed.proyecto.nombre}. ¿Cerrar sin guardar?`, "Cerrar sin guardar"))) return;
    salirModo();
    ed.activo = false;
    ed.proyecto = null;
    document.body.classList.remove("editando-red");
    $("editor-red").hidden = true;
    $("er-inspector").hidden = true;
    Object.values(ed.capas || {}).forEach((c) => c.clearLayers());
    ed.elementos.clear(); ed.cables.clear(); ed.notas.clear();
    mensaje("Proyecto cerrado");
  }

  // ------------------------------------------------------------------ eventos
  function enCampo(t) { return t && t.closest && t.closest("input, textarea, select, [contenteditable='true'], .ql-editor"); }
  const hayModal = () => [...document.querySelectorAll(".modal")].some((m) => !m.hidden);

  function teclado(e) {
    if (hayModal() || enCampo(e.target)) return;
    const sinMapa = document.querySelector(".vista:not([hidden])");
    if (sinMapa) return;
    // Enter on an existing mufa (KMZ / Visio) works with or without a project open.
    if (e.key === "Enter" && !(window.visor && window.visor.midiendo)) {
      const s = ed.activo && ed.seleccion;
      if (s && s.tipo === "elementos") { e.preventDefault(); abrirElemento(ed.elementos.get(s.id)); return; }
      if (ed.activo && ed.modo === "cable") { e.preventDefault(); terminarCable(); return; }
      const ex = window.__mufaExistente;
      if (ex) { e.preventDefault(); Redes.abrirMufaExistente(typeof ex === "string" ? ex : ex.nombre, ex.lat, ex.lon); return; }
    }
    if (!ed.activo || (window.visor && window.visor.midiendo)) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); deshacer(); }
    else if (ctrl && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); rehacer(); }
    else if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); guardar(); }
    else if (e.key === "Escape") { if (ed.modo) { salirModo(); pintarTodo(); } else if (ed.seleccion) seleccionar(null); }
    else if (e.key === "Backspace" && ed.modo === "cable" && ed.cableNuevo) {
      e.preventDefault();
      if (ed.cableNuevo.vertices.length > 1) { ed.cableNuevo.vertices.pop(); dibujarCableNuevo(); }
    }
    else if ((e.key === "Delete" || e.key === "Supr") && ed.seleccion) { e.preventDefault(); eliminarSeleccion(); }
    else if (e.key === "F2" && ed.seleccion) { e.preventDefault(); editarSeleccion(); }
  }

  function editarSeleccion() {
    const s = ed.seleccion;
    if (!s || !ed.puedeEditar) return;
    const obj = ed[s.tipo].get(s.id);
    if (s.tipo === "elementos") abrirFormElemento(obj.tipo, obj);
    else if (s.tipo === "cables") abrirFormCable(obj);
    else abrirNota(obj);
  }

  function conectar() {
    document.querySelectorAll("[data-er-nuevo]").forEach((b) => {
      b.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/er-tipo", b.dataset.erNuevo); e.dataTransfer.effectAllowed = "copy"; });
      b.addEventListener("click", () => {
        salirModo();
        ed.colocar = b.dataset.erNuevo;
        b.classList.add("activa");
        cambiarModo("colocar", `${TIPOS[ed.colocar].titulo}: clic en el mapa donde va (o arrástrelo desde la paleta) · Esc cancela`);
      });
    });
    $("er-cable").addEventListener("click", () => { salirModo(); abrirFormCable(null); });
    $("er-nota").addEventListener("click", () => {
      salirModo();
      $("er-nota").classList.add("activa");
      cambiarModo("nota", "Nota: clic en el mapa donde va, o sobre un elemento para anclarla a él · Esc cancela");
    });
    $("er-deshacer").addEventListener("click", deshacer);
    $("er-rehacer").addEventListener("click", rehacer);
    $("er-guardar").addEventListener("click", guardar);
    $("er-diagrama").addEventListener("click", () => {
      if (!ed.proyecto || !window.DiagramaLogico) return;
      if (nCambios()) mensaje("El diagrama usa la red guardada: guarde para incluir sus cambios", "error");
      window.DiagramaLogico.abrir(ed.proyecto.id);
    });
    $("er-cerrar").addEventListener("click", cerrar);
    $("er-el-form").addEventListener("submit", aceptarElemento);
    $("er-ca-form").addEventListener("submit", aceptarCable);
    $("er-no-aceptar").addEventListener("click", aceptarNota);
    document.querySelectorAll("[data-er-cerrar]").forEach((b) => b.addEventListener("click", () => { $(b.dataset.erCerrar).hidden = true; }));
    $("er-inspector").addEventListener("click", (e) => {
      const b = e.target.closest("[data-er]");
      if (!b) return;
      const s = ed.seleccion;
      const obj = s && ed[s.tipo].get(s.id);
      if (b.dataset.er === "deseleccionar") seleccionar(null);
      else if (b.dataset.er === "abrir" && obj) abrirElemento(obj);
      else if (b.dataset.er === "editar") editarSeleccion();
      else if (b.dataset.er === "duplicar" && obj) duplicarElemento(obj);
      else if (b.dataset.er === "eliminar") eliminarSeleccion();
      else if (b.dataset.er === "trazar" && obj) trazarCable(obj);
      else if ((b.dataset.er === "problema" || b.dataset.er === "pendiente") && obj) {
        if (nCambios()) mensaje("Guarde el proyecto antes, para que el elemento exista en la base", "error");
        const preset = { proyecto_id: ed.proyecto.id, [s.tipo === "cables" ? "cable_id" : "elemento_id"]: obj.id };
        (b.dataset.er === "problema" ? window.Problemas : window.Pendientes).nuevo(preset);
      }
    });
    $("er-inspector").addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.target.id !== "er-hilo-num") return;
      e.preventDefault();
      const s = ed.seleccion;
      if (s && s.tipo === "cables") trazarCable(ed.cables.get(s.id));
    });
    document.addEventListener("trazado", (e) => pintarTrazado(e.detail));
    $("er-problemas").addEventListener("change", cargarProblemas);
    document.addEventListener("problemas-cambiaron", (e) => { if (ed.activo && ed.proyecto && e.detail.proyecto_id === ed.proyecto.id) cargarProblemas(); });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-er-problema]");
      if (b && window.Problemas) { ed.mapa.closePopup(); window.Problemas.abrir(Number(b.dataset.erProblema)); }
    });
    ["modal-er-elemento", "modal-er-cable", "modal-er-nota"].forEach((id) => {
      $(id).addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); $(id).hidden = true; } });
    });
    document.addEventListener("keydown", teclado);
    new ResizeObserver(medirBarra).observe($("editor-red"));
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  /** Cola de corrección (migración Visio, fase 6): open the project and place an element that has no coordinate. */
  async function ubicar(proyectoId, elementoId) {
    if (!(await abrir(proyectoId))) return false;
    const el = ed.elementos.get(elementoId);
    if (!el) { mensaje("El elemento ya no está en el proyecto", "error"); return false; }
    if (!ed.puedeEditar) { mensaje("Solo un editor puede ubicarla", "error"); return false; }
    ed.ubicando = elementoId;
    cambiarModo("ubicar", `${el.nombre}: clic en el mapa donde está la mufa · Esc cancela`);
    return true;
  }

  window.EditorRed = {
    abrir, cerrar, guardar, deshacer, rehacer, mostrarTrazado, mostrarProblema, ubicar, _cargarProblemas: cargarProblemas,
    get activo() { return ed.activo; },
    _ed: ed, _clicCable: clicCable, _terminarCable: terminarCable, _metraje: metraje,
    _crear(tipo, lat, lon, nombre) {            // automated checks: like dropping from the palette
      abrirFormElemento(tipo, null, lat, lon);
      $("er-el-nombre").value = nombre;
      $("er-el-form").dispatchEvent(new Event("submit", { cancelable: true }));
    },
  };
})();
