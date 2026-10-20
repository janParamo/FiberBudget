/* Editor de mufa (fase 4 del módulo de redes): una vista por mufa, solo lo que entra y sale de ella.
 *
 *   - Cada cable es una barra por buffer con sus hilos numerados en colores TIA-598 (1 azul,
 *     2 naranja, 3 verde, 4 café, 5 gris, 6 blanco, 7 rojo, 8 negro, 9 amarillo, 10 violeta,
 *     11 rosa, 12 aqua); con 8 hilos por buffer los colores se repiten cada 8. Los cables que
 *     llegan van a la izquierda y los que salen a la derecha, con el encabezado
 *     "Cable | origen | destino | hilos" y una caja «→ destino» (doble clic: abre esa mufa).
 *   - Conectar: arrastrar desde un hilo (círculo) o un puerto hasta otro hilo o puerto; la línea
 *     es ortogonal y del color del hilo. Splitters 1x2…1x32 (balanceados o 70/30…), conectores,
 *     estado de cada hilo (activo, fibra oscura, cliente de baja, reservado, dañado), notas.
 *   - Eliminar (Supr), alinear y distribuir (Ctrl+clic para elegir varios), deshacer/rehacer,
 *     zoom (rueda) y desplazamiento (arrastrar el fondo). Aplicar = guardar sin cerrar.
 *   - Migas de pan: Proyecto › Mufa A › Mufa B.
 * Guarda con Redes.llamar("guardar_mufa") (visor_rutas/redes/mufa.py), en una transacción.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const TIA = ["#1f5fd1", "#f28c28", "#2e9d4a", "#8b5a2b", "#8c8c8c", "#ffffff", "#e53935", "#111111", "#f7d117",
               "#7e3fbf", "#f06ba8", "#2ec4d6"];
  const TIA_NOMBRE = ["azul", "naranja", "verde", "café", "gris", "blanco", "rojo", "negro", "amarillo", "violeta", "rosa", "aqua"];
  const OSCUROS = new Set([0, 3, 6, 7, 9]);                   // white number on these colours
  const ESTADO = { activo: "Activo", oscura: "Fibra oscura", baja: "Cliente de baja", reservado: "Reservado", danado: "Dañado" };
  const FILA = 20, CABECERA = 78, SEPARA_BUFFER = 8, ANCHO_ETIQUETA = 200;
  const COL_IZQ = 40, COL_CENTRO = 470, COL_DER = 880;

  const st = {
    datos: null, mufaId: null, migas: [], puedeEditar: false,
    cables: [], splitters: new Map(), conectores: new Map(), conexiones: new Map(), notas: new Map(), hilos: new Map(),
    borrados: { splitters: new Map(), conectores: new Map(), conexiones: new Map(), notas: new Map() },
    sucios: new Set(), temporal: 0, pilas: { deshacer: [], rehacer: [] },
    seleccion: [], stage: null, capa: null, capaLineas: null, puertos: new Map(), arrastre: null, quill: null,
    formulario: null, notaEditando: null, maximizado: false, colorPor: "hilo",
  };
  const nuevoId = () => `n${++st.temporal}`;
  const esNuevo = (id) => typeof id === "string";
  const mensaje = (t, tipo) => (window.visor && window.visor.mensaje ? window.visor.mensaje(t, tipo) : null);
  const colorHilo = (c, n) => (n - 1) % c.hilos_por_buffer;          // TIA index of fibre n
  const bufferHilo = (c, n) => Math.floor((n - 1) / c.hilos_por_buffer);

  // ------------------------------------------------------------------ estado, deshacer
  function instantanea() {
    return JSON.stringify({
      cables: st.cables.map((c) => ({ id: c.id, x: c.x, y: c.y, movido: c.movido })),
      splitters: [...st.splitters.values()], conectores: [...st.conectores.values()], conexiones: [...st.conexiones.values()],
      notas: [...st.notas.values()], hilos: [...st.hilos.entries()],
      borrados: Object.fromEntries(Object.entries(st.borrados).map(([k, v]) => [k, [...v]])), sucios: [...st.sucios], temporal: st.temporal,
    });
  }
  function restaurar(t) {
    const s = JSON.parse(t);
    s.cables.forEach((p) => { const c = st.cables.find((x) => x.id === p.id); if (c) Object.assign(c, p); });
    st.splitters = new Map(s.splitters.map((x) => [x.id, x]));
    st.conectores = new Map(s.conectores.map((x) => [x.id, x]));
    st.conexiones = new Map(s.conexiones.map((x) => [x.id, x]));
    st.notas = new Map(s.notas.map((x) => [x.id, x]));
    st.hilos = new Map(s.hilos);
    st.borrados = Object.fromEntries(Object.entries(s.borrados).map(([k, v]) => [k, new Map(v)]));
    st.sucios = new Set(s.sucios);
    st.temporal = s.temporal;
  }
  function antesDeCambiar() {
    st.pilas.deshacer.push(instantanea());
    if (st.pilas.deshacer.length > 200) st.pilas.deshacer.shift();
    st.pilas.rehacer = [];
  }
  function deshacer() { if (!st.pilas.deshacer.length) return; st.pilas.rehacer.push(instantanea()); restaurar(st.pilas.deshacer.pop()); st.seleccion = []; dibujar(); }
  function rehacer() { if (!st.pilas.rehacer.length) return; st.pilas.deshacer.push(instantanea()); restaurar(st.pilas.rehacer.pop()); st.seleccion = []; dibujar(); }
  const nCambios = () => st.sucios.size + st.hilos.size + Object.values(st.borrados).reduce((n, m) => n + m.size, 0)
    + st.cables.filter((c) => c.movido).length;

  function actualizarBarra() {
    const n = nCambios();
    $("mu-cambios").textContent = n ? `${n} cambio${n === 1 ? "" : "s"} sin guardar` : "Guardado";
    $("mu-cambios").classList.toggle("pendiente", !!n);
    $("mu-aplicar").disabled = !n || !st.puedeEditar;
    $("mu-deshacer").disabled = !st.pilas.deshacer.length;
    $("mu-rehacer").disabled = !st.pilas.rehacer.length;
    const fibra = st.seleccion.length === 1 && st.seleccion[0].tipo === "hilo" ? st.seleccion[0] : null;
    $("mu-estado").disabled = !fibra || !st.puedeEditar;
    $("mu-trazar").disabled = !fibra || !window.Trazado;
    if (fibra) $("mu-estado").value = estadoHilo(fibra.id);
    $("mu-eliminar").disabled = !st.seleccion.some((s) => ["conexion", "splitter", "conector", "nota"].includes(s.tipo));
  }

  // ------------------------------------------------------------------ datos
  function fibraPorId(id) {
    for (const c of st.cables) { const f = c.fibras.find((x) => x.id === id); if (f) return [c, f]; }
    return [null, null];
  }
  const estadoHilo = (id) => (st.hilos.get(id) || fibraPorId(id)[1] || {}).estado || "activo";

  function cargar(r) {
    st.datos = r;
    st.puedeEditar = !!r.mufa.puede_editar;
    st.cables = r.cables.map((c) => ({ ...c, movido: false }));
    st.splitters = new Map(r.splitters.map((s) => [s.id, { ...s }]));
    st.conectores = new Map(r.conectores.map((k) => [k.id, { ...k }]));
    st.conexiones = new Map(r.conexiones.map((x) => [x.id, x]));
    st.notas = new Map(r.notas.map((n) => [n.id, n]));
    st.hilos = new Map();
    st.borrados = { splitters: new Map(), conectores: new Map(), conexiones: new Map(), notas: new Map() };
    st.sucios = new Set();
    st.pilas = { deshacer: [], rehacer: [] };
    st.seleccion = [];
    distribuirFaltantes();
  }

  // + 36: the cable's destination box goes below its last fibre (each fibre row may carry its own box, 5.3)
  // a migrated cable may have an unknown count (hilos null): it is drawn without fibres
  const altoCable = (c) => CABECERA + (c.hilos || 0) * FILA + Math.max(0, Math.ceil((c.hilos || 0) / c.hilos_por_buffer) - 1) * SEPARA_BUFFER + 10 + 36;
  const textoHilos = (c) => (c.hilos == null ? "hilos desconocidos" : `${c.hilos} hilos`);
  const altoSplitter = (s) => Math.max(36, s.salidas * 16 + 4);
  // label under the splitter: name (~17 characters per line), 01xNN, OLT and "depende de" (same estimate as migrar_visio_contenido.py)
  const altoEtiqueta = (s) => { const p = s.propiedades || {};
    return (Math.ceil((s.nombre || "").length / 17) + 1 + (p.olt || p.puerto_olt ? 1 : 0) + (p.depende_de ? 1 : 0)) * 14 + 6; };
  // where a migrated datum comes from (red existente, Visio)
  const FUENTE = { excel_anillos: "Excel de anillos", texto_diagrama: "texto del Visio", geometria_visio: "dibujo del Visio",
                   kmz: "KMZ", estimado: "estimado", usuario: "usuario" };
  const textoServicio = (p) => [p.codigo_cliente, p.nombre].filter(Boolean).join(" ");
  // plan §8: green = verified / Excel, blue = Visio text, orange = Visio drawing, grey dashed = estimated
  const COLOR_FUENTE = { usuario: "#0a9d57", excel_anillos: "#0a9d57", texto_diagrama: "#1f6feb", geometria_visio: "#f08c00",
                         kmz: "#1f6feb", estimado: "#9aa3ad" };

  /** Cables without a saved position: entering ones on the left, leaving ones on the right. */
  function distribuirFaltantes(todo = false) {
    const y = { entrada: 30, salida: 30 };
    st.cables.forEach((c) => {
      if (todo || c.x == null) {
        c.x = c.lado === "entrada" ? COL_IZQ : COL_DER;
        c.y = y[c.lado];
        if (todo) c.movido = true;
      }
      y[c.lado] = Math.max(y[c.lado], c.y + altoCable(c) + 30);
    });
    let ys = 40;
    [...st.splitters.values(), ...st.conectores.values()].forEach((o) => {
      if (todo) { o.x = COL_CENTRO; o.y = ys; st.sucios.add(`${o.salidas ? "splitters" : "conectores"}:${o.id}`); }
      ys = Math.max(ys, o.y + (o.salidas ? altoSplitter(o) + altoEtiqueta(o) + 20 : 60));
    });
  }

  // ------------------------------------------------------------------ dibujo
  function crearStage() {
    if (st.stage) return;
    const caja = $("mu-lienzo");
    st.stage = new Konva.Stage({ container: $("mu-konva"), width: caja.clientWidth, height: caja.clientHeight, draggable: true });
    st.fondo = new Konva.Layer({ listening: false });
    st.capaLineas = new Konva.Layer();
    st.capa = new Konva.Layer();
    st.stage.add(st.fondo, st.capaLineas, st.capa);
    st.stage.on("wheel", (e) => {
      e.evt.preventDefault();
      const viejo = st.stage.scaleX(), p = st.stage.getPointerPosition();
      const punto = { x: (p.x - st.stage.x()) / viejo, y: (p.y - st.stage.y()) / viejo };
      const nuevo = Math.max(0.15, Math.min(4, viejo * (e.evt.deltaY > 0 ? 1 / 1.12 : 1.12)));
      st.stage.scale({ x: nuevo, y: nuevo });
      st.stage.position({ x: p.x - punto.x * nuevo, y: p.y - punto.y * nuevo });
      pintarFondo(); moverNotas();
    });
    st.stage.on("dragmove", () => { pintarFondo(); moverNotas(); });
    st.stage.on("click", (e) => { if (e.target === st.stage) { st.seleccion = []; ocultarMenu(); resaltar(); } });
    st.stage.on("pointermove mousemove touchmove", alMover);
    st.stage.on("pointerup mouseup touchend", alSoltar);
    new ResizeObserver(() => { medir(); pintarFondo(); }).observe(caja);
  }

  /** 20 px grid over the visible part of the canvas (in canvas coordinates). */
  function pintarFondo() {
    const s = st.stage.scaleX(), paso = 20;
    st.fondo.destroyChildren();
    if (paso * s >= 6) {
      const caja = $("mu-lienzo");
      const ancho = Math.max(st.stage.width(), caja.clientWidth), alto = Math.max(st.stage.height(), caja.clientHeight);
      const x0 = -st.stage.x() / s, y0 = -st.stage.y() / s, x1 = x0 + (ancho + 400) / s, y1 = y0 + (alto + 400) / s;
      st.fondo.add(new Konva.Shape({
        sceneFunc: (ctx) => {
          ctx.beginPath();
          for (let x = Math.floor(x0 / paso) * paso; x < x1; x += paso) { ctx.moveTo(x, y0); ctx.lineTo(x, y1); }
          for (let y = Math.floor(y0 / paso) * paso; y < y1; y += paso) { ctx.moveTo(x0, y); ctx.lineTo(x1, y); }
          ctx.strokeStyle = "#e6e9ee"; ctx.lineWidth = 1 / s; ctx.stroke();
        },
      }));
    }
    st.fondo.batchDraw();
  }

  function dibujar() {
    st.capa.destroyChildren();
    st.puertos.clear();
    st.cables.forEach(dibujarCable);
    st.splitters.forEach(dibujarSplitter);
    st.conectores.forEach(dibujarConector);
    dibujarConexiones();
    dibujarNotas();
    resaltar();
    st.capa.draw();             // synchronous: the hit graph must match the new shapes before the next click
    pintarResumen();
  }

  const seleccionado = (tipo, id) => st.seleccion.some((s) => s.tipo === tipo && s.id === id);
  /** Fibres / connections of the open trace (phase 5), highlighted in yellow. */
  const trazado = () => (window.Trazado && window.Trazado.actual) || null;
  const enTrazado = (tipo, id) => { const t = trazado(); return !!t && t[tipo].includes(id); };

  function registrarPuerto(clave, grupo, dx, dy, ref, salida, color) {
    st.puertos.set(clave, { grupo, dx, dy, ref, salida, color });
  }
  const posicion = (clave) => {
    const p = st.puertos.get(clave);
    return p ? { x: p.grupo.x() + p.dx, y: p.grupo.y() + p.dy, salida: p.salida } : null;
  };

  function dibujarCable(c) {
    const izq = c.lado === "entrada";
    const g = new Konva.Group({ x: c.x, y: c.y, draggable: st.puedeEditar, name: "cable" });
    g.setAttr("obj", { tipo: "cable", id: c.id });
    const alto = altoCable(c);
    const barraX = izq ? ANCHO_ETIQUETA : 46;
    const circuloX = izq ? ANCHO_ETIQUETA + 10 + 30 : 8;
    const etiquetaX = izq ? 0 : 60;
    g.add(new Konva.Rect({ x: izq ? -6 : -14, y: -6, width: ANCHO_ETIQUETA + 74, height: alto + 6, fill: "#fff", stroke: "#cfd6e0",
                           cornerRadius: 6, shadowColor: "#000", shadowOpacity: 0.08, shadowBlur: 6, name: "marco" }));
    const encabezado = `${c.nombre} | ${c.origen.nombre} | ${c.destino.nombre} | ${c.hilos ?? "?"}`;
    g.add(new Konva.Text({ x: etiquetaX, y: 0, width: ANCHO_ETIQUETA - 10, text: encabezado, fontSize: 14, fontStyle: "bold",
                           fill: "#1d2128", wrap: "word", ellipsis: true, height: 54, lineHeight: 1.2, name: "cabecera" }));
    const tipo = (c.hilos == null ? `${c.tipo} · hilos desconocidos` : `${c.tipo} · ${c.hilos} hilos (${c.hilos_por_buffer}/buffer)`)
      + (st.puedeEditar ? "  ✎" : "");
    const lineaTipo = new Konva.Text({ x: etiquetaX, y: 56, width: ANCHO_ETIQUETA - 10, text: tipo, fontSize: 11,
                                       fill: st.puedeEditar ? "#1e429f" : "#5b6270", name: st.puedeEditar ? "config-cable" : "cabecera" });
    if (st.puedeEditar) {                              // plan §8: change the configuration (6x4 <-> 12x2…) or set an unknown count
      lineaTipo.on("click", (e) => { e.cancelBubble = true; abrirConfigCable(c); });
      lineaTipo.on("mouseenter", () => { st.stage.container().style.cursor = "pointer"; tooltip("Cambiar la configuración del cable"); });
      lineaTipo.on("mouseleave", () => { st.stage.container().style.cursor = ""; tooltip(null); });
    }
    g.add(lineaTipo);
    // destination box: double click (or Enter) -> that mufa's editor
    const caja = new Konva.Group({ x: etiquetaX, y: alto - 34, name: "destino" });
    const flecha = izq ? `← desde ${c.otro.nombre}` : `→ hacia ${c.otro.nombre}`;
    const navegable = ["mufa", "nodo", "odf"].includes(c.otro.tipo);
    caja.add(new Konva.Rect({ width: ANCHO_ETIQUETA - 14, height: 26, fill: navegable ? "#e7f0ff" : "#f1f3f6", stroke: navegable ? "#1f6feb" : "#cfd6e0",
                              cornerRadius: 4 }));
    caja.add(new Konva.Text({ x: 6, y: 7, width: ANCHO_ETIQUETA - 24, text: flecha, fontSize: 12, fill: navegable ? "#1e429f" : "#5b6270",
                              ellipsis: true, wrap: "none" }));
    caja.on("dblclick dbltap", () => navegar(c.otro));
    caja.on("click", (e) => { e.cancelBubble = true; seleccionar({ tipo: "cable", id: c.id }); });
    caja.on("mouseenter", () => { st.stage.container().style.cursor = navegable ? "pointer" : "default";
                                  tooltip(navegable ? `Doble clic o Enter: abrir ${esc(c.otro.nombre)}` : `${esc(c.otro.nombre)} (${esc(c.otro.tipo)})`); });
    caja.on("mouseleave", () => { st.stage.container().style.cursor = ""; tooltip(null); });
    g.add(caja);
    // buffers and fibres
    let y = CABECERA;
    for (let b = 0; b * c.hilos_por_buffer < (c.hilos || 0); b++) {
      const n = Math.min(c.hilos_por_buffer, c.hilos - b * c.hilos_por_buffer);
      g.add(new Konva.Rect({ x: barraX, y: y - 6, width: 10, height: n * FILA, fill: TIA[b % 12], stroke: "#333", strokeWidth: 1,
                             name: "barra", hitStrokeWidth: 8 }));
      for (let i = 0; i < n; i++) {
        const numero = b * c.hilos_por_buffer + i + 1;
        const f = c.fibras.find((x) => x.numero === numero);
        if (f) dibujarFibra(g, c, f, barraX, circuloX, y + i * FILA + 4, izq);
      }
      y += n * FILA + SEPARA_BUFFER;
    }
    g.on("dragstart", () => antesDeCambiar());
    g.on("dragmove", () => { c.x = g.x(); c.y = g.y(); dibujarConexiones(); });
    g.on("dragend", () => { c.movido = true; actualizarBarra(); });
    g.on("click", (e) => { if (e.target.name() !== "puerto") seleccionar({ tipo: "cable", id: c.id }, e.evt.ctrlKey); });
    // the cable tooltip (5.1): over its frame, its header and its buffer bars
    const delCable = (e) => ["marco", "cabecera", "barra"].includes(e.target.name());
    g.on("mouseover", (e) => { if (delCable(e) && !st.arrastre) tooltip(htmlCable(c)); });
    g.on("mouseout", (e) => { if (delCable(e)) tooltip(null); });
    st.capa.add(g);
  }

  function dibujarFibra(g, c, f, barraX, cx, cy, izq) {
    const idx = colorHilo(c, f.numero);
    const estado = estadoHilo(f.id);
    const desde = izq ? barraX + 10 : barraX, hasta = izq ? cx - 8 : cx + 8;
    g.add(new Konva.Line({ points: [desde, cy, hasta, cy], stroke: TIA[idx], strokeWidth: 3, dash: estado === "oscura" ? [4, 3] : null,
                           opacity: estado === "oscura" ? 0.5 : 1 }));
    const circulo = new Konva.Circle({
      x: cx, y: cy, radius: 8, fill: estado === "oscura" ? "#d4d7dc" : TIA[idx],
      stroke: estado === "baja" ? "#e53935" : estado === "reservado" ? "#1f6feb" : estado === "danado" ? "#b00020" : "#333",
      strokeWidth: ["baja", "reservado", "danado"].includes(estado) ? 3 : 1, dash: estado === "baja" ? [3, 2] : null, name: "puerto",
    });
    const clave = `h:${f.id}`;
    circulo.setAttr("puerto", clave);
    g.add(circulo);
    g.add(new Konva.Text({ x: cx - 8, y: cy - 5, width: 16, align: "center", text: String(f.numero), fontSize: 9, listening: false,
                           fill: OSCUROS.has(idx) && estado !== "oscura" ? "#fff" : "#111" }));
    if (estado === "danado") g.add(new Konva.Line({ points: [cx - 5, cy - 5, cx + 5, cy + 5, cx, cy, cx + 5, cy - 5, cx - 5, cy + 5],
                                                     stroke: "#fff", strokeWidth: 2, listening: false }));
    registrarPuerto(clave, g, cx + (izq ? 8 : -8), cy, { hilo: f.id }, izq ? 1 : -1, TIA[idx]);
    eventosPuerto(circulo, clave);
    circulo.on("click", (e) => { e.cancelBubble = true; seleccionar({ tipo: "hilo", id: f.id }); });
    circulo.on("contextmenu", (e) => { e.evt.preventDefault(); e.cancelBubble = true; seleccionar({ tipo: "hilo", id: f.id }); menuHilo(e.evt, f); });
    circulo.on("mouseenter", () => tooltip(htmlFibra(c, f)));
    circulo.on("mouseleave", () => tooltip(null));
    cajaDestinoHilo(g, c, f, cy, izq, idx);
  }

  /** 5.3: a box with the destination at the end of every fibre in use (connected here or at the
   *  other end), as in reference image 08. Double click (or the fibre selected + Enter) opens
   *  the mufa at the other end. */
  function cajaDestinoHilo(g, c, f, cy, izq, idx) {
    const aqui = !!ocupado(`h:${f.id}`);
    if (!aqui && !f.lejos) return;
    const navegable = ["mufa", "nodo", "odf"].includes(c.otro.tipo);
    const alla = navegable ? (f.lejos || "sin conectar allá") : c.otro.tipo === "cliente" ? "cliente" : c.otro.tipo;
    const texto = `${izq ? "←" : "→"} ${c.otro.nombre} · ${alla}`;
    const ancho = ANCHO_ETIQUETA - 14;
    const caja = new Konva.Group({ x: izq ? 0 : 60, y: cy - 8, name: "destino-hilo" });
    caja.add(new Konva.Rect({ width: ancho, height: 16, fill: aqui ? "#f3f7ff" : "#f6f7f9", stroke: navegable ? "#9db8ea" : "#cfd6e0",
                              cornerRadius: 3 }));
    caja.add(new Konva.Rect({ x: izq ? ancho - 5 : 0, width: 5, height: 16, fill: TIA[idx], stroke: "#333", strokeWidth: 0.5 }));
    caja.add(new Konva.Text({ x: izq ? 4 : 8, y: 3, width: ancho - 14, text: texto, fontSize: 10.5, wrap: "none", ellipsis: true,
                              align: izq ? "right" : "left", fill: navegable ? "#1e429f" : "#374151", fontStyle: aqui ? "normal" : "italic" }));
    caja.on("click", (e) => { e.cancelBubble = true; seleccionar({ tipo: "hilo", id: f.id }); });
    caja.on("dblclick dbltap", (e) => { e.cancelBubble = true; navegar(c.otro); });
    caja.on("mouseenter", () => { st.stage.container().style.cursor = navegable ? "pointer" : "default";
                                  tooltip(htmlFibra(c, f) + (navegable ? `<div class="mu-tt-sec">Doble clic: abrir ${esc(c.otro.nombre)}</div>` : "")); });
    caja.on("mouseleave", () => { st.stage.container().style.cursor = ""; tooltip(null); });
    g.add(caja);
  }

  function dibujarSplitter(s) {
    const g = new Konva.Group({ x: s.x, y: s.y, draggable: st.puedeEditar, name: "splitter" });
    const alto = altoSplitter(s);
    g.add(new Konva.Line({ points: [12, alto / 2, 62, 2, 62, alto - 2], closed: true, fill: "#9aa3ad", stroke: "#1a1a1a", strokeWidth: 1.5, name: "cuerpo" }));
    const entrada = new Konva.Circle({ x: 6, y: alto / 2, radius: 6, fill: "#111", stroke: "#fff", strokeWidth: 1, name: "puerto" });
    const ce = `s:${s.id}:entrada:1`;
    entrada.setAttr("puerto", ce);
    g.add(entrada);
    registrarPuerto(ce, g, 0, alto / 2, { splitter: s.id, lado: "entrada", numero: 1 }, -1, null);
    eventosPuerto(entrada, ce);
    for (let n = 1; n <= s.salidas; n++) {
      const y = 2 + (n - 1) * ((alto - 4) / s.salidas) + (alto - 4) / s.salidas / 2;
      const r = new Konva.Rect({ x: 62, y: y - 6, width: 12, height: 12, fill: "#111", stroke: "#fff", strokeWidth: 1, name: "puerto" });
      const cs = `s:${s.id}:salida:${n}`;
      r.setAttr("puerto", cs);
      g.add(r);
      g.add(new Konva.Text({ x: 62, y: y - 4.5, width: 12, align: "center", text: String(n), fontSize: 8, fill: "#fff", listening: false }));
      registrarPuerto(cs, g, 74, y, { splitter: s.id, lado: "salida", numero: n }, 1, null);
      eventosPuerto(r, cs);
      const servicio = (s.servicios || {})[n];
      if (servicio) {                                   // the client (or splitter) this output feeds, from the Visio list
        g.add(new Konva.Text({ x: 100, y: y - 5, width: 170, text: textoServicio(servicio) || servicio.id_servicio, fontSize: 9.5,
                               fill: "#0a6b3d", wrap: "none", ellipsis: true, listening: false }));
      }
    }
    const p = s.propiedades || {};
    const olt = [p.olt ? `OLT ${p.olt}` : "", p.puerto_olt || ""].filter(Boolean).join(" ");
    const etiqueta = `${s.nombre}\n(01x${String(s.salidas).padStart(2, "0")}${s.relacion ? ` ${s.relacion}` : ""}${s.conector ? ` ${s.conector}` : ""})`
      + (olt ? `\n${olt}` : "") + (p.depende_de ? `\nDepende de ${p.depende_de}` : "");
    g.add(new Konva.Text({ x: -20, y: alto + 6, width: 120, align: "center", text: etiqueta, fontSize: 12, fill: "#1d2128", name: "cuerpo" }));
    objetoMovible(g, s, "splitters");
    st.capa.add(g);
  }

  function dibujarConector(k) {
    const g = new Konva.Group({ x: k.x, y: k.y, draggable: st.puedeEditar, name: "conector" });
    g.add(new Konva.Rect({ x: 8, y: 0, width: 36, height: 16, fill: "#5b6270", stroke: "#1a1a1a", cornerRadius: 6, name: "cuerpo" }));
    g.add(new Konva.Rect({ x: 22, y: -2, width: 8, height: 20, fill: "#2b2f36", name: "cuerpo" }));
    [["entrada", 2, -1], ["salida", 50, 1]].forEach(([lado, x, dir]) => {
      const p = new Konva.Circle({ x, y: 8, radius: 5, fill: "#111", stroke: "#fff", strokeWidth: 1, name: "puerto" });
      const clave = `k:${k.id}:${lado}`;
      p.setAttr("puerto", clave);
      g.add(p);
      registrarPuerto(clave, g, x + dir * 5, 8, { conector: k.id, lado }, dir, null);
      eventosPuerto(p, clave);
    });
    g.add(new Konva.Text({ x: -30, y: 22, width: 112, align: "center", text: `${k.nombre}${k.tipo ? `\n${k.tipo}` : ""}`, fontSize: 11,
                           fill: "#1d2128", name: "cuerpo" }));
    objetoMovible(g, k, "conectores");
    st.capa.add(g);
  }

  function objetoMovible(g, o, tabla) {
    const tipo = tabla === "splitters" ? "splitter" : "conector";
    g.setAttr("obj", { tipo, id: o.id });
    g.on("dragstart", () => antesDeCambiar());
    g.on("dragmove", () => { o.x = g.x(); o.y = g.y(); dibujarConexiones(); });
    g.on("dragend", () => { st.sucios.add(`${tabla}:${o.id}`); actualizarBarra(); });
    g.on("click", (e) => { if (e.target.name() === "cuerpo") seleccionar({ tipo, id: o.id }, e.evt.ctrlKey); });
    g.on("dblclick", (e) => { if (e.target.name() === "cuerpo" && st.puedeEditar) abrirObjeto(tipo, o); });
  }

  // ------------------------------------------------------------------ conexiones
  const claveDe = (ref) => (ref.hilo != null ? `h:${ref.hilo}` : ref.splitter != null ? `s:${ref.splitter}:${ref.lado}:${ref.numero || 1}`
    : `k:${ref.conector}:${ref.lado}`);

  /** Colour of a connection: the fibre at one of its ends, or the fibre feeding the splitter. */
  function colorConexion(x, profundidad = 0) {
    for (const ref of [x.a, x.b]) if (ref.hilo != null) { const [c, f] = fibraPorId(ref.hilo); if (f) return TIA[colorHilo(c, f.numero)]; }
    if (profundidad > 3) return "#6b7280";
    for (const ref of [x.a, x.b]) {
      if (ref.splitter != null && ref.lado === "salida") {
        const entrada = [...st.conexiones.values()].find((y) => [y.a, y.b].some((r) => r.splitter === ref.splitter && r.lado === "entrada"));
        if (entrada) return colorConexion(entrada, profundidad + 1);
      }
    }
    return "#6b7280";
  }

  /** Orthogonal path; `carril` shifts the vertical segment so parallel connections do not overlap. */
  function ruta(p1, p2, carril = 0) {
    const a = { x: p1.x + p1.salida * 22, y: p1.y }, b = { x: p2.x + p2.salida * 22, y: p2.y };
    // ports facing the same side: go around on the outside; otherwise turn halfway
    const mx = (p1.salida === p2.salida ? (p1.salida > 0 ? Math.max(a.x, b.x) : Math.min(a.x, b.x)) : (a.x + b.x) / 2) + carril * 7;
    return [p1.x, p1.y, a.x, a.y, mx, a.y, mx, b.y, b.x, b.y, p2.x, p2.y];
  }

  function dibujarConexiones() {
    st.capaLineas.destroyChildren();
    let i = 0;
    st.conexiones.forEach((x) => {
      const p1 = posicion(claveDe(x.a)), p2 = posicion(claveDe(x.b));
      if (!p1 || !p2) return;
      const carril = ((i++ % 9) - 4);
      const sel = seleccionado("conexion", x.id);
      const traza = enTrazado("conexiones", x.id);
      const oscura = [x.a, x.b].some((r) => r.hilo != null && estadoHilo(r.hilo) !== "activo");
      const brillo = sel ? "#1f6feb" : traza ? "#ffd400" : null;
      const porFuente = st.colorPor === "fuente", fuente = x.fuente || "usuario";      // no source: drawn in the editor before the migration
      const linea = new Konva.Line({ points: ruta(p1, p2, carril), stroke: porFuente ? COLOR_FUENTE[fuente] || COLOR_FUENTE.estimado : colorConexion(x),
                                     strokeWidth: sel || traza ? 5 : 3, lineJoin: "round", hitStrokeWidth: 12,
                                     dash: oscura ? [8, 5] : porFuente && fuente === "estimado" ? [5, 4] : null, shadowColor: brillo, shadowBlur: brillo ? 10 : 0,
                                     shadowOpacity: brillo ? 1 : 0, opacity: trazado() && !traza && !sel ? 0.3 : 1 });
      linea.on("click", (e) => { e.cancelBubble = true; seleccionar({ tipo: "conexion", id: x.id }, e.evt.ctrlKey); });
      const origen = (FUENTE[x.fuente] ? `<div class="nota">Dato: ${FUENTE[x.fuente]}${x.confianza ? ` · confianza ${esc(x.confianza)}` : ""}</div>` : "")
        + (x.bandeja ? `<div class="nota">Bandeja ${x.bandeja} · posición ${x.posicion}${x.posicion_estimada ? " (estimada)" : ""}</div>` : "");
      linea.on("mouseenter", () => { st.stage.container().style.cursor = "pointer"; tooltip(`${esc(describir(x.a))} ↔ ${esc(describir(x.b))}${origen}`); });
      linea.on("mouseleave", () => { st.stage.container().style.cursor = ""; tooltip(null); });
      st.capaLineas.add(linea);
    });
    st.capaLineas.batchDraw();
  }

  function describir(ref) {
    if (ref.hilo != null) { const [c, f] = fibraPorId(ref.hilo); return c ? `${c.nombre} hilo ${f.numero}` : "hilo"; }
    if (ref.splitter != null) { const s = st.splitters.get(ref.splitter); return `${s ? s.nombre : "splitter"} ${ref.lado === "entrada" ? "entrada" : `salida ${ref.numero}`}`; }
    const k = st.conectores.get(ref.conector);
    return `${k ? k.nombre : "conector"} (${ref.lado})`;
  }

  const ocupado = (clave) => [...st.conexiones.values()].find((x) => claveDe(x.a) === clave || claveDe(x.b) === clave);

  function eventosPuerto(forma, clave) {
    const borde = forma.strokeWidth();
    const dePuerto = !clave.startsWith("h:");                // fibres have their own tooltip
    forma.on("mouseenter", () => { st.stage.container().style.cursor = st.puedeEditar ? "crosshair" : "default"; forma.strokeWidth(borde + 1.5);
                                   st.capa.batchDraw(); if (dePuerto && !st.arrastre) tooltip(htmlPuerto(clave)); });
    forma.on("mouseleave", () => { st.stage.container().style.cursor = ""; forma.strokeWidth(borde); st.capa.batchDraw(); if (dePuerto) tooltip(null); });
    forma.on("pointerdown mousedown touchstart", (e) => {
      e.cancelBubble = true;                                   // the block / stage must not start dragging
      if (!st.puedeEditar || e.evt.button === 2 || st.arrastre) return;
      const p = posicion(clave);
      st.arrastre = { desde: clave, linea: new Konva.Line({ points: [p.x, p.y, p.x, p.y], stroke: st.puertos.get(clave).color || "#1f6feb",
                                                           strokeWidth: 3, dash: [6, 4], listening: false }) };
      st.capaLineas.add(st.arrastre.linea);
      st.stage.draggable(false);
    });
  }

  function puntoLienzo() {
    const p = st.stage.getPointerPosition();
    return { x: (p.x - st.stage.x()) / st.stage.scaleX(), y: (p.y - st.stage.y()) / st.stage.scaleY() };
  }

  function alMover() {
    if (!st.arrastre) return;
    const p1 = posicion(st.arrastre.desde), p = puntoLienzo();
    st.arrastre.linea.points(ruta(p1, { ...p, salida: p.x < p1.x ? 1 : -1 }));
    st.capaLineas.batchDraw();
  }

  function alSoltar() {
    if (!st.arrastre) return;
    const { desde, linea } = st.arrastre;
    st.arrastre = null;
    linea.destroy();
    st.stage.draggable(true);
    const forma = st.stage.getIntersection(st.stage.getPointerPosition());
    const hasta = forma && forma.getAttr("puerto");
    if (!hasta || hasta === desde) { dibujarConexiones(); return; }
    const a = st.puertos.get(desde).ref, b = st.puertos.get(hasta).ref;
    const mismoObjeto = (a.splitter != null && a.splitter === b.splitter) || (a.conector != null && a.conector === b.conector);
    if (mismoObjeto) { mensaje("No se puede conectar un splitter o conector consigo mismo", "error"); dibujarConexiones(); return; }
    if (a.hilo != null && b.hilo != null && fibraPorId(a.hilo)[0] === fibraPorId(b.hilo)[0]) {
      mensaje("Una fusión une hilos de cables distintos", "error"); dibujarConexiones(); return;
    }
    for (const clave of [desde, hasta]) {
      if (ocupado(clave)) { mensaje(`${describir(st.puertos.get(clave).ref)} ya está conectado: quite primero esa conexión`, "error"); dibujarConexiones(); return; }
    }
    antesDeCambiar();
    const x = { id: nuevoId(), version: null, a, b };
    st.conexiones.set(x.id, x);
    st.sucios.add(`conexiones:${x.id}`);
    st.seleccion = [{ tipo: "conexion", id: x.id }];
    dibujar();
    mensaje(`Conectado: ${describir(a)} ↔ ${describir(b)}`, "ok");
  }

  // ------------------------------------------------------------------ selección, tooltip, menú
  function seleccionar(s, sumar = false) {
    st.seleccion = sumar ? (seleccionado(s.tipo, s.id) ? st.seleccion.filter((x) => !(x.tipo === s.tipo && x.id === s.id)) : [...st.seleccion, s]) : [s];
    ocultarMenu();
    resaltar();
  }

  function resaltar() {
    st.capa.find("Group").forEach((g) => {
      const o = g.getAttr("obj");
      if (!o) return;
      const sel = seleccionado(o.tipo, o.id);
      g.find(".marco, .cuerpo").forEach((n) => { if (n.getClassName() !== "Text") { n.shadowColor(sel ? "#1f6feb" : "#000"); n.shadowBlur(sel ? 14 : 6); n.shadowOpacity(sel ? 0.9 : 0.08); } });
    });
    st.capa.find(".puerto").forEach((p) => {
      const k = p.getAttr("puerto");
      const hilo = k.startsWith("h:") ? Number(k.slice(2)) : null;
      const brillo = hilo == null ? null : seleccionado("hilo", hilo) ? "#1f6feb" : enTrazado("hilos", hilo) ? "#ffd400" : null;
      p.shadowColor(brillo); p.shadowBlur(brillo ? 14 : 0); p.shadowOpacity(brillo ? 1 : 0);
    });
    st.capa.batchDraw();
    dibujarConexiones();
    moverNotas();
    actualizarBarra();
  }

  function tooltip(html) {
    const caja = $("mu-tooltip");
    if (!html) { caja.hidden = true; return; }
    caja.innerHTML = html;
    caja.hidden = false;
    // next to the pointer, kept inside the canvas (above the pointer when it does not fit below)
    const p = st.stage.getPointerPosition() || { x: 0, y: 0 };
    const lienzo = $("mu-lienzo");
    caja.style.left = `${Math.max(4, Math.min(p.x + 16, lienzo.clientWidth - caja.offsetWidth - 8))}px`;
    const abajo = p.y + 16 + caja.offsetHeight <= lienzo.clientHeight - 4;
    caja.style.top = `${abajo ? p.y + 16 : Math.max(4, p.y - 12 - caja.offsetHeight)}px`;
  }

  // ------------------------------------------------------------------ tooltips (5.1): cable and fibre
  const CLASE = { troncal: "Troncal", distribucion: "Distribución", acometida: "Acometida" };
  const num = (v) => (v == null || isNaN(v) ? "?" : Number(v).toLocaleString("es-NI", { maximumFractionDigits: 1 }));

  /** "METRAJE = 317 m" and its detail, as in the reference image 06. */
  function htmlMetraje(m) {
    if (!m || m.metraje_m == null) return `<div class="mu-met-total">METRAJE: sin calcular</div>`;
    const reserva = (o, unidad) => (o ? `${num(o.cantidad)} (und × ${num(unidad)} m) = ${num(o.total_m)} m` : "—");
    const t = m.reservas_tendido;
    const filas = [
      ["Distancia lineal", `${num(m.distancia_lineal_m)} m`],
      ["Contingencia", `${num(m.contingencia_m)} m`],
      ["Salida de nodo", `${num(m.salida_nodo_m)} m`],
      ["N° de reservas × mufa", reserva(m.reservas_mufa, m.reservas_mufa && m.reservas_mufa.unidad_m)],
      ["N° de reservas × tendido", reserva(t, t ? t.intervalo_m * t.porcentaje : 0)],
      ["N° de reservas × cruce", reserva(m.reservas_cruce, m.reservas_cruce && m.reservas_cruce.unidad_m)],
    ];
    if (m.reservas_cliente && m.reservas_cliente.total_m) {
      filas.push(["N° de reservas × cliente", reserva(m.reservas_cliente, m.reservas_cliente.unidad_m)]);
    }
    return `<div class="mu-met-total">METRAJE = ${num(m.metraje_m)} m</div><div class="mu-met-sub">Detalles del metraje:</div>
      <table class="mu-met">${filas.map(([k, v]) => `<tr><td>› ${k}</td><td>${v}</td></tr>`).join("")}</table>`;
  }

  const datosCable = (c) => `${esc(CLASE[c.clase] || c.clase)} · ${esc(c.tipo)} · ${textoHilos(c)} `
    + (c.hilos == null ? "(edite el cable en el mapa para indicarlos)"
      : `(${c.hilos_por_buffer} por buffer, ${Math.ceil(c.hilos / c.hilos_por_buffer)} buffer${c.hilos > c.hilos_por_buffer ? "s" : ""})`);

  function htmlFibra(c, f) {
    const idx = colorHilo(c, f.numero), buffer = bufferHilo(c, f.numero);
    const aqui = ocupado(`h:${f.id}`);
    const otro = aqui ? (claveDe(aqui.a) === `h:${f.id}` ? aqui.b : aqui.a) : null;
    const lejos = ["mufa", "nodo", "odf"].includes(c.otro.tipo) ? esc(f.lejos || "sin conectar")
      : c.otro.tipo === "cliente" ? `llega al cliente ${esc(c.otro.nombre)}` : esc(c.otro.tipo);
    return `<div class="mu-tt-titulo"><span class="mu-tt-punto" style="background:${TIA[idx]}"></span>${esc(c.nombre)} · hilo ${f.numero}</div>
      <div>Color <b>${TIA_NOMBRE[idx]}</b> · buffer ${buffer + 1} (${TIA_NOMBRE[buffer % 12]})</div>
      <div>Estado: <b>${esc(ESTADO[estadoHilo(f.id)])}</b>${f.observacion ? ` · ${esc(f.observacion)}` : ""}</div>
      <div class="mu-tt-sec">Conectado en cada extremo:</div>
      <div>› Aquí (${esc(st.datos.mufa.nombre)}): ${otro ? esc(describir(otro)) : "sin conectar"}</div>
      <div>› En ${esc(c.otro.nombre)}: ${lejos}</div>
      <div class="mu-tt-sec">${esc(c.nombre)}: ${datosCable(c)}</div>
      ${htmlMetraje(c.metraje)}`;
  }

  /** Splitter / connector port: what it is connected to and, through a fibre, where it goes (5.3). */
  function htmlPuerto(clave) {
    const p = st.puertos.get(clave);
    if (!p) return null;
    const ref = p.ref;
    let titulo = describir(ref);
    let servicio = "";
    if (ref.splitter != null) {
      const s = st.splitters.get(ref.splitter);
      if (s) titulo += ` · 1x${s.salidas}${s.relacion ? ` ${s.relacion}` : ""}`;
      const sv = s && ref.lado === "salida" && (s.servicios || {})[ref.numero];
      if (sv) {
        servicio = `<div>Cliente: <b>${esc(textoServicio(sv) || "—")}</b>${sv.id_servicio ? ` · ${esc(sv.id_servicio)}` : ""}</div>`
          + `<div class="nota">Dato: ${FUENTE[sv.fuente] || "usuario"}${sv.elemento_id ? " · está en el mapa" : ""}</div>`;
      }
    }
    const x = ocupado(clave);
    if (!x) return `<div class="mu-tt-titulo">${esc(titulo)}</div>${servicio}<div>Libre${st.puedeEditar ? ": arrastre desde aquí para conectar" : ""}</div>`;
    const otro = claveDe(x.a) === clave ? x.b : x.a;
    let sigue = "";
    if (otro.hilo != null) {
      const [c, f] = fibraPorId(otro.hilo);
      if (c) {
        const alla = ["mufa", "nodo", "odf"].includes(c.otro.tipo) ? (f.lejos || "sin conectar allá") : c.otro.tipo;
        sigue = `<div>› Sigue ${c.lado === "salida" ? "hacia" : "desde"} <b>${esc(c.otro.nombre)}</b> · ${esc(alla)}</div>`;
      }
    }
    return `<div class="mu-tt-titulo">${esc(titulo)}</div>${servicio}<div>Conectado a: <b>${esc(describir(otro))}</b></div>${sigue}`;
  }

  function htmlCable(c) {
    const estados = {};
    c.fibras.forEach((f) => { const e = estadoHilo(f.id); estados[e] = (estados[e] || 0) + 1; });
    const PLURAL = { activo: ["activo", "activos"], oscura: ["en fibra oscura", "en fibra oscura"], baja: ["de cliente de baja", "de clientes de baja"],
                     reservado: ["reservado", "reservados"], danado: ["dañado", "dañados"] };
    const resumenEstados = Object.keys(ESTADO).filter((k) => estados[k]).map((k) => `${estados[k]} ${PLURAL[k][estados[k] === 1 ? 0 : 1]}`).join(" · ");
    const aqui = c.fibras.filter((f) => ocupado(`h:${f.id}`)).length;
    const lejos = ["mufa", "nodo", "odf"].includes(c.otro.tipo) ? `${c.fibras.filter((f) => f.lejos).length} de ${c.hilos ?? "?"} hilos conectados`
      : c.otro.tipo === "cliente" ? `es el cliente ${esc(c.otro.nombre)}` : esc(c.otro.tipo);
    return `<div class="mu-tt-titulo">${esc(c.nombre)}</div>
      <div>${datosCable(c)}</div>
      <div>${esc(c.origen.nombre)} → ${esc(c.destino.nombre)} · ${c.lado === "entrada" ? "llega a" : "sale de"} esta mufa</div>
      <div>Estado de los hilos: ${resumenEstados || "—"}</div>
      <div class="mu-tt-sec">Conectado en cada extremo:</div>
      <div>› Aquí (${esc(st.datos.mufa.nombre)}): ${aqui} de ${c.hilos ?? "?"} hilos conectados</div>
      <div>› En ${esc(c.otro.nombre)}: ${lejos}</div>
      ${htmlMetraje(c.metraje)}`;
  }

  function menuHilo(evt, f) {
    const menu = $("mu-menu");
    const conectado = ocupado(`h:${f.id}`);
    menu.innerHTML = (window.Trazado ? `<li data-mu-trazar="${f.id}">Trazar este hilo (T)</li>` : "")
      + (st.puedeEditar ? Object.entries(ESTADO).map(([k, v]) => `<li data-mu-estado="${k}" class="${k === "activo" && window.Trazado ? "menu-sep" : ""}">`
          + `${estadoHilo(f.id) === k ? "✓ " : ""}${v}</li>`).join("")
        + (conectado ? `<li data-mu-quitar="${conectado.id}" class="menu-titulo-sep">Quitar su conexión</li>` : "") : "");
    if (!menu.innerHTML) return;
    menu.dataset.hilo = f.id;
    menu.style.left = `${evt.clientX}px`;
    menu.style.top = `${evt.clientY}px`;
    menu.hidden = false;
  }
  function ocultarMenu() { $("mu-menu").hidden = true; }

  function cambiarEstado(hiloId, estado) {
    const [, f] = fibraPorId(hiloId);
    if (!f || estadoHilo(hiloId) === estado) return;
    antesDeCambiar();
    if (estado === f.estado) st.hilos.delete(hiloId);
    else st.hilos.set(hiloId, { id: hiloId, version: f.version, estado, observacion: f.observacion });
    dibujar();
  }

  // ------------------------------------------------------------------ objetos: crear, editar, eliminar
  function centroVista() {
    const s = st.stage.scaleX();
    return { x: (st.stage.width() / 2 - st.stage.x()) / s, y: (st.stage.height() / 2 - st.stage.y()) / s };
  }

  function abrirObjeto(tipo, objeto) {
    st.formulario = { tipo, objeto };
    const esSplitter = tipo === "splitter";
    $("mu-ob-titulo").textContent = objeto ? `${esSplitter ? "Splitter" : "Conector"}: ${objeto.nombre}` : `Nuevo ${esSplitter ? "splitter" : "conector"}`;
    $("mu-ob-splitter").hidden = !esSplitter;
    $("mu-ob-tipo-campo").hidden = esSplitter;
    const n = (esSplitter ? st.splitters : st.conectores).size + 1;
    $("mu-ob-nombre").value = objeto ? objeto.nombre : `${esSplitter ? "Splitter" : "Conector"} ${n}`;
    const [salidas, relacion] = String($("mu-tipo-splitter").value).split(":");
    $("mu-ob-salidas").value = String(objeto && objeto.salidas ? objeto.salidas : salidas);
    $("mu-ob-relacion").value = objeto ? objeto.relacion || "" : relacion || "";
    $("mu-ob-conector").value = objeto ? objeto.conector || "" : "RC";
    $("mu-ob-tipo").value = objeto ? objeto.tipo || "" : "SC/APC";
    Redes.estadoEn($("mu-ob-estado"), "");
    $("modal-mu-objeto").hidden = false;
    $("mu-ob-nombre").focus();
    $("mu-ob-nombre").select();
  }

  function aceptarObjeto(ev) {
    ev.preventDefault();
    const f = st.formulario;
    const nombre = $("mu-ob-nombre").value.trim();
    if (!nombre) { Redes.estadoEn($("mu-ob-estado"), "El nombre es obligatorio", "error"); return; }
    const salidas = Number($("mu-ob-salidas").value);
    const relacion = $("mu-ob-relacion").value || null;
    if (f.tipo === "splitter" && relacion && salidas !== 2) { Redes.estadoEn($("mu-ob-estado"), "La relación desbalanceada es solo para 1x2", "error"); return; }
    if (f.tipo === "splitter" && f.objeto && salidas < f.objeto.salidas) {
      const usadas = [...st.conexiones.values()].flatMap((x) => [x.a, x.b]).filter((r) => r.splitter === f.objeto.id && r.lado === "salida" && r.numero > salidas);
      if (usadas.length) { Redes.estadoEn($("mu-ob-estado"), `Tiene conectadas salidas mayores a ${salidas}: quítelas primero`, "error"); return; }
    }
    antesDeCambiar();
    const tabla = f.tipo === "splitter" ? "splitters" : "conectores";
    const datos = f.tipo === "splitter" ? { nombre, salidas, relacion, conector: $("mu-ob-conector").value.trim() || null }
      : { nombre, tipo: $("mu-ob-tipo").value.trim() || null };
    let o = f.objeto;
    if (o) Object.assign(o, datos);
    else {
      // middle column (between the cables that arrive and the ones that leave), below what is already there
      const centro = [...st.splitters.values(), ...st.conectores.values()].filter((x) => Math.abs(x.x - COL_CENTRO) < 150);
      const y = centro.reduce((m, x) => Math.max(m, x.y + (x.salidas ? altoSplitter(x) + 50 : 60)), 40);
      o = { id: nuevoId(), version: null, x: COL_CENTRO, y, ...datos };
      st[tabla].set(o.id, o);
    }
    st.sucios.add(`${tabla}:${o.id}`);
    $("modal-mu-objeto").hidden = true;
    st.seleccion = [{ tipo: f.tipo, id: o.id }];
    dibujar();
  }

  function eliminarSeleccion() {
    const quitar = st.seleccion.filter((s) => ["conexion", "splitter", "conector", "nota"].includes(s.tipo));
    if (!quitar.length || !st.puedeEditar) return;
    antesDeCambiar();
    const borrar = (tabla, id) => {
      const o = st[tabla].get(id);
      if (!o) return;
      st[tabla].delete(id);
      st.sucios.delete(`${tabla}:${id}`);
      if (!esNuevo(id)) st.borrados[tabla].set(id, o.version);
    };
    quitar.forEach((s) => {
      if (s.tipo === "conexion") borrar("conexiones", s.id);
      else if (s.tipo === "nota") borrar("notas", s.id);
      else {
        const tabla = s.tipo === "splitter" ? "splitters" : "conectores";
        [...st.conexiones.values()].filter((x) => [x.a, x.b].some((r) => (s.tipo === "splitter" ? r.splitter : r.conector) === s.id))
          .forEach((x) => borrar("conexiones", x.id));
        borrar(tabla, s.id);
      }
    });
    st.seleccion = [];
    dibujar();
  }

  function alinear(modo) {
    const objs = st.seleccion.map((s) => (s.tipo === "cable" ? st.cables.find((c) => c.id === s.id)
      : s.tipo === "splitter" ? st.splitters.get(s.id) : s.tipo === "conector" ? st.conectores.get(s.id) : null)).filter(Boolean);
    if (objs.length < 2) { mensaje("Elija dos o más elementos con Ctrl+clic para alinear o distribuir", "error"); return; }
    antesDeCambiar();
    const xs = objs.map((o) => o.x), ys = objs.map((o) => o.y);
    if (modo === "izquierda") objs.forEach((o) => { o.x = Math.min(...xs); });
    if (modo === "derecha") objs.forEach((o) => { o.x = Math.max(...xs); });
    if (modo === "arriba") objs.forEach((o) => { o.y = Math.min(...ys); });
    if (modo === "abajo") objs.forEach((o) => { o.y = Math.max(...ys); });
    if (modo === "vertical" || modo === "horizontal") {
      const eje = modo === "vertical" ? "y" : "x";
      const orden = [...objs].sort((a, b) => a[eje] - b[eje]);
      const ini = orden[0][eje], fin = orden[orden.length - 1][eje];
      orden.forEach((o, i) => { o[eje] = ini + ((fin - ini) * i) / (orden.length - 1); });
    }
    objs.forEach((o) => {
      if (st.cables.includes(o)) o.movido = true;
      else st.sucios.add(`${o.salidas ? "splitters" : "conectores"}:${o.id}`);
    });
    dibujar();
  }

  // ------------------------------------------------------------------ notas (HTML sobre el lienzo)
  function dibujarNotas() {
    const caja = $("mu-notas");
    caja.innerHTML = "";
    st.notas.forEach((n) => {
      const div = document.createElement("div");
      div.className = `mu-nota er-nota-cuerpo ql-editor${seleccionado("nota", n.id) ? " sel" : ""}`;
      div.style.width = `${n.ancho || 220}px`;
      div.innerHTML = n.html;
      div.dataset.nota = n.id;
      caja.appendChild(div);
    });
    moverNotas();
  }
  function moverNotas() {
    if (!st.stage) return;
    const s = st.stage.scaleX();
    document.querySelectorAll("#mu-notas .mu-nota").forEach((div) => {
      const n = st.notas.get(/^n\d+$/.test(div.dataset.nota) ? div.dataset.nota : Number(div.dataset.nota));
      if (!n) return;
      div.style.transform = `translate(${st.stage.x() + n.x * s}px, ${st.stage.y() + n.y * s}px) scale(${s})`;
      div.classList.toggle("sel", seleccionado("nota", n.id));
    });
  }
  function conectarNotas() {
    const caja = $("mu-notas");
    let arrastre = null;
    caja.addEventListener("pointerdown", (e) => {
      const div = e.target.closest(".mu-nota");
      if (!div) return;
      const id = /^n\d+$/.test(div.dataset.nota) ? div.dataset.nota : Number(div.dataset.nota);
      seleccionar({ tipo: "nota", id }, e.ctrlKey);
      if (!st.puedeEditar) return;
      const n = st.notas.get(id);
      arrastre = { n, x: e.clientX, y: e.clientY, ox: n.x, oy: n.y, movida: false };
      div.setPointerCapture(e.pointerId);
    });
    caja.addEventListener("pointermove", (e) => {
      if (!arrastre) return;
      const s = st.stage.scaleX();
      if (!arrastre.movida) { antesDeCambiar(); arrastre.movida = true; }
      arrastre.n.x = arrastre.ox + (e.clientX - arrastre.x) / s;
      arrastre.n.y = arrastre.oy + (e.clientY - arrastre.y) / s;
      moverNotas();
    });
    caja.addEventListener("pointerup", () => {
      if (arrastre && arrastre.movida) { st.sucios.add(`notas:${arrastre.n.id}`); actualizarBarra(); }
      arrastre = null;
    });
    caja.addEventListener("dblclick", (e) => {
      const div = e.target.closest(".mu-nota");
      if (div && st.puedeEditar) abrirNota(st.notas.get(/^n\d+$/.test(div.dataset.nota) ? div.dataset.nota : Number(div.dataset.nota)));
    });
  }
  function abrirNota(nota) {
    if (!st.quill && window.Quill) {
      st.quill = new Quill("#mu-quill", { theme: "snow", placeholder: "Escriba la nota…",
        modules: { toolbar: [[{ font: [] }, { size: ["small", false, "large", "huge"] }], ["bold", "italic", "underline", "strike"],
                             [{ color: [] }, { background: [] }], [{ list: "ordered" }, { list: "bullet" }], ["clean"]] } });
    }
    if (!st.quill) { mensaje("No se pudo cargar el editor de texto (lib/quill)", "error"); return; }
    st.notaEditando = nota || null;
    st.quill.setContents([]);
    if (nota) st.quill.clipboard.dangerouslyPasteHTML(nota.html);
    Redes.estadoEn($("mu-no-estado"), "");
    $("modal-mu-nota").hidden = false;
    st.quill.focus();
  }
  function aceptarNota() {
    if (!st.quill.getText().trim()) { Redes.estadoEn($("mu-no-estado"), "La nota está vacía", "error"); return; }
    antesDeCambiar();
    let n = st.notaEditando;
    if (n) n.html = st.quill.root.innerHTML;
    else {
      const c = centroVista();
      n = { id: nuevoId(), version: null, html: st.quill.root.innerHTML, x: c.x, y: c.y, ancho: 220 };
      st.notas.set(n.id, n);
    }
    st.sucios.add(`notas:${n.id}`);
    $("modal-mu-nota").hidden = true;
    dibujar();
  }

  // ------------------------------------------------------------------ abrir, navegar, guardar
  function medir() {
    const caja = $("mu-lienzo");
    if (caja.clientWidth && (caja.clientWidth !== st.stage.width() || caja.clientHeight !== st.stage.height())) {
      st.stage.size({ width: caja.clientWidth, height: caja.clientHeight });
    }
  }

  function ajustar() {
    medir();
    const caja = st.capa.getClientRect({ relativeTo: st.stage });
    if (!caja.width || !caja.height) return;
    const s = Math.max(0.15, Math.min(1.5, Math.min((st.stage.width() - 60) / caja.width, (st.stage.height() - 60) / caja.height)));
    st.stage.scale({ x: s, y: s });
    st.stage.position({ x: 30 - caja.x * s, y: 30 - caja.y * s });
    pintarFondo();
    moverNotas();
  }

  function pintarMigas() {
    const p = st.datos.proyecto;
    $("mu-migas").innerHTML = `<a href="#" data-miga="-1">${esc(p.nombre)}</a>` + st.migas.map((m, i) =>
      ` › ${i === st.migas.length - 1 ? `<b>${esc(m.nombre)}</b>` : `<a href="#" data-miga="${i}">${esc(m.nombre)}</a>`}`).join("");
    $("mu-nombre").value = st.datos.mufa.nombre;
    const n = (st.datos.clientes || []).length;
    $("mu-clientes").textContent = n ? `Clientes (${n})` : "Clientes";
    $("mu-clientes").disabled = !n;
    const mu = st.datos.mufa;
    $("mu-visio").disabled = !window.visor || !window.visor.verVisioAlLado;
    $("mu-validar").hidden = !mu.estado_migracion || !st.puedeEditar;
    $("mu-validar").textContent = mu.estado_migracion === "validada" ? "Quitar validación" : "Marcar como validada";
  }

  /** "Ver Visio original": the Visio diagram of this mufa at the right of the editor. */
  async function verVisio() {
    const mu = st.datos.mufa;
    if (!(await window.visor.verVisioAlLado(mu.nombre_visio || mu.nombre))) mensaje(`${mu.nombre}: no se encontró su diagrama Visio`, "error");
  }

  async function validar() {
    if (nCambios()) { mensaje("Aplique (guarde) los cambios antes de validar la mufa", "error"); return; }
    const validada = st.datos.mufa.estado_migracion !== "validada";
    if (validada && !(await Redes.confirmar(`¿Marcar ${st.datos.mufa.nombre} como validada? Su contenido queda como verificado `
      + "y una reimportación del Visio no lo cambiará.", "Marcar como validada"))) return;
    const r = await Redes.llamar("validar_mufa", { mufa_id: st.mufaId, validada });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    recargar(r);
    mensaje(validada ? `${r.mufa.nombre}: validada` : `${r.mufa.nombre}: se quitó la validación`, "ok");
  }

  // ------------------------------------------------------------------ configuración de un cable (plan §8)
  let cableEnConfig = null;
  function abrirConfigCable(c) {
    if (!st.puedeEditar) return;
    if (nCambios()) { mensaje("Aplique (guarde) los cambios antes de cambiar la configuración de un cable", "error"); return; }
    cableEnConfig = c;
    $("mu-cb-titulo").textContent = `Configuración de ${c.nombre}`;
    $("mu-cb-hilos").value = c.hilos == null ? "" : String(c.hilos);
    $("mu-cb-hilos").querySelector('option[value=""]').disabled = c.hilos != null;
    $("mu-cb-buffer").value = String(c.hilos_por_buffer);
    mostrarConfig();
    Redes.estadoEn($("mu-cb-estado"), "");
    $("modal-mu-cable").hidden = false;
  }
  function mostrarConfig() {
    const h = Number($("mu-cb-hilos").value), pb = Number($("mu-cb-buffer").value);
    $("mu-cb-config").textContent = h ? `Quedaría ${Math.ceil(h / pb)}x${Math.min(h, pb)} (${Math.ceil(h / pb)} buffer${h > pb ? "s" : ""} de ${Math.min(h, pb)} hilos)` : "Hilos desconocidos";
  }
  async function guardarConfigCable(ev) {
    ev.preventDefault();
    const c = cableEnConfig;
    const r = await Redes.llamar("configurar_cable", { cable_id: c.id, mufa_id: st.mufaId, hilos: $("mu-cb-hilos").value || null,
                                                       hilos_por_buffer: Number($("mu-cb-buffer").value), version: c.version });
    if (!r.ok) { Redes.estadoEn($("mu-cb-estado"), r.error, "error"); return; }
    $("modal-mu-cable").hidden = true;
    recargar(r);
  }

  function abrirClientes() {
    $("mu-cl-titulo").textContent = `Clientes de ${st.datos.mufa.nombre}`;
    $("mu-cl-lista").innerHTML = (st.datos.clientes || []).map((c) => `<tr><td>${esc(c.codigo_cliente || "—")}</td><td>${esc(c.nombre || "")}</td>`
      + `<td>${esc(c.id_servicio || "")}</td><td>${c.elemento_id ? "sí" : "no"}</td></tr>`).join("");
    $("modal-mu-clientes").hidden = false;
  }

  async function cargarMufa(id) {
    const r = await Redes.llamar("mufa", { mufa_id: id });
    if (!r.ok) { mensaje(r.error, "error"); return false; }
    cargar(r);
    st.mufaId = id;
    document.querySelectorAll("#modal-mufa .mu-edicion").forEach((g) => { g.hidden = !st.puedeEditar; });
    pintarMigas();
    dibujar();
    ajustar();
    if (window.BandejasMufa) window.BandejasMufa.pintar();
    return true;
  }

  /** The server already saved (tray view: model, move a splice…): show what it returned. */
  function recargar(r) {
    cargar(r);
    pintarMigas();
    dibujar();
    if (window.BandejasMufa) window.BandejasMufa.pintar();
  }

  // ------------------------------------------------------------------ resumen (sección 8 del plan de migración)
  const NOMBRE_FORMATO = { domo: "domo", horizontal: "cierre horizontal", desconocido: "formato desconocido" };
  const NOMBRE_MIGRACION = { automatica: "migrada (automática)", en_revision: "migrada · en revisión", validada: "validada", editada: "migrada · editada" };

  /** Model, fibres spliced / free / on a splitter, trays used and the migration state of the mufa. */
  function pintarResumen() {
    const r = st.datos;
    if (!r) return;
    const m = r.modelo;
    const enSplitter = new Set(), empalmados = new Set();
    st.conexiones.forEach((x) => {
      const hilos = [x.a, x.b].filter((e) => e.hilo != null).map((e) => e.hilo);
      const aSplitter = [x.a, x.b].some((e) => e.splitter != null);
      hilos.forEach((h) => (aSplitter ? enSplitter : empalmados).add(h));
    });
    const total = st.cables.reduce((n, c) => n + c.fibras.length, 0);
    const libres = total - enSplitter.size - empalmados.size;
    const usadas = m ? new Set([...st.conexiones.values()].filter((x) => x.bandeja).map((x) => x.bandeja)
      .concat((r.bandejas || []).filter((b) => b.splitter_id).map((b) => b.numero))).size : 0;
    const est = (v) => (v ? ` <span class="mu-insignia estimado" title="${esc(m.motivo || "")}">estimado</span>` : "");
    const partes = [
      m ? `<b>Mufa de ${m.capacidad}</b> · ${NOMBRE_FORMATO[m.formato] || m.formato} · ${m.bandejas} bandejas de ${m.empalmes_por_bandeja}${est(m.modelo_estimado)}`
        : (["mufa"].includes(r.mufa.tipo) && r.mufa.subtipo !== "reserva" ? "Sin modelo de mufa" : ""),
      `Hilos: <b>${empalmados.size}</b> empalmados · <b>${enSplitter.size}</b> en splitter · <b>${libres}</b> libres`
        + (r.mufa.estado_migracion && !st.conexiones.size && total ? ' · <span class="mu-insignia sin-diagramar">sin diagramar</span>' : ""),
      m ? `Bandejas usadas: <b>${usadas}</b> de ${m.bandejas}` : "",
      r.mufa.estado_migracion ? `<span class="mu-insignia ${r.mufa.estado_migracion}">${NOMBRE_MIGRACION[r.mufa.estado_migracion] || r.mufa.estado_migracion}</span>` : "",
      m && (m.avisos || []).length ? `<span class="mu-insignia aviso" title="${esc(m.avisos.join("\n"))}">⚠ ${m.avisos.length} aviso${m.avisos.length > 1 ? "s" : ""}</span>` : "",
      r.mufa.estado_migracion && !st.conexiones.size && total && st.puedeEditar
        ? '<button type="button" class="btn btn-chico" data-mu-diagramar="1" title="Dibujar las fusiones de esta mufa a mano">Diagramar ahora</button>' : "",
      st.colorPor === "fuente" ? '<span class="mu-leyenda"><i style="border-color:#0a9d57"></i>verificado / Excel<i style="border-color:#1f6feb"></i>texto Visio'
        + '<i style="border-color:#f08c00"></i>dibujo Visio<i class="punteada" style="border-color:#9aa3ad"></i>estimado</span>' : "",
    ].filter(Boolean);
    $("mu-resumen").innerHTML = partes.join('<span class="mu-sep">|</span>');
  }

  /** Opens the editor of a project mufa (from the map editor: Enter / double click). */
  async function abrir(mufaId, nombre) {
    $("modal-mufa").hidden = false;
    crearStage();
    st.migas = [{ id: mufaId, nombre: nombre || "Mufa" }];
    if (!(await cargarMufa(mufaId))) { $("modal-mufa").hidden = true; return; }
    st.migas[0].nombre = st.datos.mufa.nombre;
    pintarMigas();
  }

  async function confirmarSalida(destino) {
    if (!nCambios()) return true;
    if (!st.puedeEditar) return true;
    const guardarAntes = await Redes.confirmar(`Hay ${nCambios()} cambio(s) sin guardar en ${st.datos.mufa.nombre}. `
      + `¿Guardarlos antes de ${destino}? (Cancelar: se queda aquí)`, "Guardar y seguir");
    return guardarAntes ? aplicar() : false;
  }

  async function navegar(otro) {
    if (!["mufa", "nodo", "odf"].includes(otro.tipo)) { mensaje(`${otro.nombre} es un ${otro.tipo}: no tiene editor de mufa`, "error"); return; }
    if (!(await confirmarSalida(`abrir ${otro.nombre}`))) return;
    const i = st.migas.findIndex((m) => m.id === otro.id);
    st.migas = i >= 0 ? st.migas.slice(0, i + 1) : [...st.migas, { id: otro.id, nombre: otro.nombre }];
    await cargarMufa(otro.id);
  }

  function cambiosParaGuardar() {
    const salida = { posiciones: st.cables.filter((c) => c.movido).map((c) => ({ cable_id: c.id, x: Math.round(c.x), y: Math.round(c.y),
                                                                                  version: c.pos_version ?? null })),
                     splitters: [], conectores: [], conexiones: [], hilos: [...st.hilos.values()], notas: [] };
    st.sucios.forEach((k) => {
      const [tabla, ...resto] = k.split(":");
      const id = resto.join(":");
      const o = st[tabla].get(/^n\d+$/.test(id) ? id : Number(id));
      if (o) salida[tabla].push({ ...o, x: Math.round(o.x ?? 0), y: Math.round(o.y ?? 0) });
    });
    Object.entries(st.borrados).forEach(([tabla, m]) => m.forEach((version, id) => salida[tabla].push({ id, version, eliminar: true })));
    return salida;
  }

  async function aplicar() {
    if (!st.puedeEditar) return false;
    if (!nCambios()) return true;
    $("mu-aplicar").disabled = $("mu-guardar").disabled = true;
    const r = await Redes.llamar("guardar_mufa", { mufa_id: st.mufaId, cambios: cambiosParaGuardar() });
    $("mu-guardar").disabled = false;
    if (!r.ok) {
      actualizarBarra();
      if (r.conflicto && await Redes.confirmar(`${r.error}\n\n¿Recargar la mufa? Sus cambios sin guardar se pierden.`, "Recargar")) {
        await cargarMufa(st.mufaId);
      } else if (!r.conflicto) mensaje(r.error, "error");
      return false;
    }
    const vista = { x: st.stage.x(), y: st.stage.y(), s: st.stage.scaleX() };
    cargar(r);
    dibujar();
    st.stage.scale({ x: vista.s, y: vista.s });
    st.stage.position({ x: vista.x, y: vista.y });
    pintarFondo(); moverNotas();
    mensaje(`Mufa ${st.datos.mufa.nombre} guardada`, "ok");
    if (window.Trazado) window.Trazado.refrescar();          // the open trace may have changed
    return true;
  }

  /** Phase 5: traces the selected fibre (the trace reads what is saved: apply first if needed). */
  async function trazarHilo(hiloId) {
    if (!window.Trazado || hiloId == null) return;
    if (nCambios() && st.puedeEditar) {
      if (!(await Redes.confirmar(`El trazado usa lo guardado y hay ${nCambios()} cambio(s) sin guardar. ¿Aplicarlos y trazar?`, "Aplicar y trazar"))) return;
      if (!(await aplicar())) return;
    }
    await window.Trazado.abrir({ hilo_id: hiloId });
  }

  async function cerrar(guardarAntes) {
    if (guardarAntes) { if (!(await aplicar())) return; }
    else if (nCambios() && st.puedeEditar
             && !(await Redes.confirmar(`Hay ${nCambios()} cambio(s) sin guardar en ${st.datos.mufa.nombre}. ¿Cerrar sin guardar?`, "Cerrar sin guardar"))) return;
    $("modal-mufa").hidden = true;
    ocultarMenu();
    tooltip(null);
    if (window.visor && window.visor.aparte === "mufa") window.visor.cerrarVentana();      // in its own window, closing the editor closes the window
  }

  /** «Ventana aparte»: the mufa being edited moves to a window of its own (it can go out of the program, beside the Visio diagram).
   *  Unsaved changes are asked about first; the in-program editor closes. */
  async function abrirAparte() {
    if (!window.visor || !window.visor.abrirVentana) return;
    if (!(await confirmarSalida("abrirla en una ventana aparte"))) return;
    const r = await window.visor.abrirVentana("mufa", { id: st.mufaId, nombre: st.datos.mufa.nombre });
    if (!r.ok) return;
    $("modal-mufa").hidden = true;
    ocultarMenu();
    tooltip(null);
  }

  // ------------------------------------------------------------------ eventos
  function teclado(e) {
    if ($("modal-mufa").hidden || !$("modal-mu-objeto").hidden || !$("modal-mu-nota").hidden || !$("modal-confirmar").hidden) return;
    const encima = ["modal-mu-clientes", "modal-mu-modelo", "modal-mu-cable"].filter((id) => !$(id).hidden);
    if (encima.length) {
      if (e.key === "Escape") encima.forEach((id) => { $(id).hidden = true; });
      return;
    }
    if (document.body.classList.contains("visio-al-lado") && e.key === "Escape") return;    // Escape closes the Visio beside it first
    if (e.target.closest && e.target.closest("input, textarea, select")) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (e.key === "Escape") { e.stopPropagation(); if (!$("mu-menu").hidden) ocultarMenu(); else cerrar(false); }
    else if (ctrl && e.key.toLowerCase() === "z") { e.preventDefault(); deshacer(); }
    else if (ctrl && e.key.toLowerCase() === "y") { e.preventDefault(); rehacer(); }
    else if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); aplicar(); }
    else if (e.key === "Delete" || e.key === "Supr") { e.preventDefault(); eliminarSeleccion(); }
    else if (!ctrl && e.key.toLowerCase() === "t" && st.seleccion.length === 1 && st.seleccion[0].tipo === "hilo") {
      e.preventDefault(); trazarHilo(st.seleccion[0].id);
    }
    else if (e.key === "Enter") {
      const s = st.seleccion[0];
      if (s && s.tipo === "cable") { e.preventDefault(); navegar(st.cables.find((c) => c.id === s.id).otro); }
      else if (s && s.tipo === "hilo") { e.preventDefault(); navegar(fibraPorId(s.id)[0].otro); }
      else if (s && (s.tipo === "splitter" || s.tipo === "conector") && st.puedeEditar) {
        e.preventDefault(); abrirObjeto(s.tipo, (s.tipo === "splitter" ? st.splitters : st.conectores).get(s.id));
      }
    }
    e.stopImmediatePropagation();
  }

  function conectar() {
    $("mu-cerrar").addEventListener("click", () => cerrar(false));
    $("mu-guardar").addEventListener("click", () => cerrar(true));
    $("mu-aplicar").addEventListener("click", aplicar);
    $("mu-aparte").addEventListener("click", abrirAparte);
    $("mu-max").addEventListener("click", () => { st.maximizado = !st.maximizado; $("modal-mufa").classList.toggle("maximizado", st.maximizado); });
    $("mu-splitter").addEventListener("click", () => abrirObjeto("splitter", null));
    $("mu-conector").addEventListener("click", () => abrirObjeto("conector", null));
    $("mu-nota").addEventListener("click", () => abrirNota(null));
    $("mu-ob-form").addEventListener("submit", aceptarObjeto);
    $("mu-no-aceptar").addEventListener("click", aceptarNota);
    $("mu-eliminar").addEventListener("click", eliminarSeleccion);
    $("mu-deshacer").addEventListener("click", deshacer);
    $("mu-rehacer").addEventListener("click", rehacer);
    $("mu-ordenar").addEventListener("click", () => { antesDeCambiar(); distribuirFaltantes(true); dibujar(); ajustar(); });
    $("mu-acercar").addEventListener("click", () => { st.stage.scale({ x: st.stage.scaleX() * 1.2, y: st.stage.scaleY() * 1.2 }); pintarFondo(); moverNotas(); });
    $("mu-alejar").addEventListener("click", () => { st.stage.scale({ x: st.stage.scaleX() / 1.2, y: st.stage.scaleY() / 1.2 }); pintarFondo(); moverNotas(); });
    $("mu-ajustar").addEventListener("click", ajustar);
    $("mu-estado").addEventListener("change", (e) => { const s = st.seleccion[0]; if (s && s.tipo === "hilo") cambiarEstado(s.id, e.target.value); });
    $("mu-diagrama").addEventListener("click", async () => {         // phase 6: the logical diagram from this mufa
      if (!window.DiagramaLogico || !st.datos) return;
      const proyecto = st.datos.proyecto.id, inicio = `e:${st.mufaId}`;
      await cerrar(false);
      if ($("modal-mufa").hidden) window.DiagramaLogico.abrir(proyecto, { inicio });
    });
    $("mu-trazar").addEventListener("click", () => { const s = st.seleccion[0]; if (s && s.tipo === "hilo") trazarHilo(s.id); });
    $("mu-clientes").addEventListener("click", abrirClientes);
    $("mu-visio").addEventListener("click", verVisio);
    $("mu-validar").addEventListener("click", validar);
    $("mu-colores").addEventListener("change", (e) => { st.colorPor = e.target.value; dibujarConexiones(); pintarResumen(); });
    $("mu-cb-form").addEventListener("submit", guardarConfigCable);
    $("mu-cb-hilos").addEventListener("change", mostrarConfig);
    $("mu-cb-buffer").addEventListener("change", mostrarConfig);
    $("mu-resumen").addEventListener("click", (e) => {
      if (!e.target.closest("[data-mu-diagramar]")) return;
      if (window.BandejasMufa && window.BandejasMufa.visible) window.BandejasMufa.alternar();
      if (window.RedMufas) window.RedMufas.ocultar();
      mensaje("Arrastre desde un hilo hasta otro hilo o un puerto de splitter para dibujar cada fusión; lo que dibuje queda como verificado (usuario)", "ok");
    });
    document.addEventListener("trazado", () => { if (st.stage && st.datos && !$("modal-mufa").hidden) dibujar(); });
    document.querySelectorAll("[data-mu-alinear]").forEach((b) => b.addEventListener("click", () => alinear(b.dataset.muAlinear)));
    $("mu-menu").addEventListener("click", (e) => {
      const li = e.target.closest("li");
      if (!li) return;
      const hilo = Number($("mu-menu").dataset.hilo);
      if (li.dataset.muTrazar) trazarHilo(hilo);
      if (li.dataset.muEstado) cambiarEstado(hilo, li.dataset.muEstado);
      if (li.dataset.muQuitar) { st.seleccion = [{ tipo: "conexion", id: /^n\d+$/.test(li.dataset.muQuitar) ? li.dataset.muQuitar : Number(li.dataset.muQuitar) }]; eliminarSeleccion(); }
      ocultarMenu();
    });
    $("mu-migas").addEventListener("click", async (e) => {
      const a = e.target.closest("[data-miga]");
      if (!a) return;
      e.preventDefault();
      const i = Number(a.dataset.miga);
      if (i < 0) { cerrar(false); return; }
      const m = st.migas[i];
      if (!(await confirmarSalida(`volver a ${m.nombre}`))) return;
      st.migas = st.migas.slice(0, i + 1);
      cargarMufa(m.id);
    });
    document.addEventListener("keydown", teclado, true);
    conectarNotas();
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.EditorMufa = { abrir, cerrar, aplicar, abrirAparte, trazarHilo, _st: st, _seleccionar: seleccionar,
    /** automated checks: connect two port keys as if dragged with the mouse */
    _conectar(desde, hasta) {
      const a = st.puertos.get(desde), b = st.puertos.get(hasta);
      if (!a || !b) return false;
      antesDeCambiar();
      const x = { id: nuevoId(), version: null, a: a.ref, b: b.ref };
      st.conexiones.set(x.id, x);
      st.sucios.add(`conexiones:${x.id}`);
      dibujar();
      return true;
    },
    _navegar: navegar, _abrirObjeto: abrirObjeto, _ajustar: ajustar,
    /** for the tray view (bandejas.js): pending changes, and redraw with what the server returned */
    cambios: nCambios, recargar, fibraPorId, describir };
})();
