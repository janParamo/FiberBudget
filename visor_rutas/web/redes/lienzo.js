/* Esquema de zona (lienzo): un mapa en blanco por zona donde se acomodan las mufas y los nodos para interconectarlos.
 *
 * Esquema.abrir(proyectoId?) abre la ventana "Esquema de zona":
 *   - a la izquierda, la lista de las mufas, nodos y ODF de la zona elegida (la zona es un proyecto de la red existente), con buscador; se ARRASTRAN
 *     al lienzo (o doble clic para ponerlos al centro). Lo que ya está en el esquema sale atenuado: clic lo busca en el lienzo;
 *   - en el centro, el lienzo en blanco (Konva): las cajas se mueven (se guarda solo), un cable une dos cajas (el mismo cable del editor de mapa,
 *     con su color y sus hilos), rueda para acercar, arrastrar el fondo para desplazar; doble clic en una caja ENTRA a su editor de mufa
 *     (un nodo también: es la fuente de la red);
 *   - distribución «Compacta» (la de siempre): solo importa la DIRECCIÓN: si en el mapa una mufa está arriba, abajo, a la izquierda o a la derecha de otra, en el
 *     esquema también, pero pegadas (las distancias no son reales: un hueco grande del mapa es un hueco de una o dos cajas). Se calcula con TODA la zona, así
 *     que cada mufa cae en el mismo lugar sin importar el orden en que se arrastren. «Real (a escala)»: las distancias del mapa, con la escala elegida.
 *   - las cajas se colocan DONDE ESTÁN LAS MUFAS EN EL MAPA (sus coordenadas reales: la del KMZ si la mufa tiene ahí un punto con su nombre, si no la suya; desde un punto de referencia y una escala que el esquema guarda), pero
 *     sobre un fondo blanco, sin mapa; si dos caen una sobre otra (una mufa paralela en el mismo punto) la segunda se corre al lugar libre más cercano.
 *     «Colocar por coordenadas» (activado) lo hace al arrastrar; desactivado, la caja queda donde se suelta. «Acomodar por coordenadas» reordena todo.
 *   - «Mufas del KMZ»: las mufas que el KMZ tiene alrededor de la zona y la zona no (nuevas, o la misma renombrada: dos mufas que se llamaban igual y ya se separaron en el KMZ como
 *     «… 1» y «… 2»); se agregan a la zona o se renombra la que ya estaba, y entran a la lista para arrastrarlas al esquema.
 *   - «Agregar nodo / ODF»: el nodo o el ODF que ALIMENTA a toda la red de la zona (se marca como fuente) se crea ahí mismo con su coordenada.
 *   - cada zona puede tener varios esquemas generales, cada uno con su nombre (Nuevo / Renombrar / Eliminar);
 *   - navegación como en Visio: la rueda desplaza el lienzo (Mayús + rueda, de lado), Ctrl + rueda acerca o aleja, arrastrar el fondo (o con el botón
 *     del medio) lo mueve; «Ventana aparte» lo saca a su propia ventana de Windows para ponerlo junto al editor de mufa o al Visio.
 *   - "Conectar": clic en una caja y clic en otra crea un cable entre ellas (nombre, clase, hilos…); clic en un cable lo selecciona (Supr lo elimina).
 *     Los hilos de cada cable se conectan en el editor de mufa de cada extremo.
 * Datos: Redes.llamar("lienzo_zonas" | "lienzo" | "guardar_lienzo" | "guardar_red"); lo guardado es de visor_rutas/redes/lienzo.py y red.py.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const ANCHO = 132, ALTO = 44;
  const COLOR = { nodo: "#f5a623", odf: "#4a5568", empalme: "#e53935", distribucion: "#d4b000", terminal: "#d500f9", reserva: "#7b8794", mufa: "#e53935" };
  const COLOR_HILOS = { 144: "#e53935", 96: "#fb8c00", 72: "#1e88e5", 48: "#8e24aa", 24: "#43a047", 12: "#00acc1" };
  const HILOS = [12, 24, 48, 72, 96, 144, 2, 4, 6, 8];
  const PASO_X = ANCHO + 24, PASO_Y = ALTO + 28;               // the least a column / a row of the compact layout is apart, and the most (a big gap of the map)
  const PASO_X_MAX = PASO_X * 2, PASO_Y_MAX = PASO_Y * 2;
  const ZOOM_MIN = 0.005;                                     // a zone of many kilometres at a big scale needs a lot of zoom out to be seen whole
  const ESCALAS = [0.5, 1, 2, 4, 8];                          // canvas pixels per metre of the real layout
  const M_LAT = 110574, M_LON = 111320;                       // metres per degree (latitude; longitude at the equator)
  const GUARDA_PREF = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* not saved: it works for this session */ } };
  const LEE_PREF = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const st = { proyectoId: null, lienzoId: null, datos: null, elementos: new Map(), pos: new Map(), cables: [], zonas: [], modo: null, origen: null, seleccion: null,
               stage: null, capaLineas: null, capaCajas: null, cajas: new Map(), lineas: new Map(), pendientes: new Set(), quitar: new Set(), temporizador: null,
               guardando: Promise.resolve(), conectado: false, referenciaPendiente: false, distribucion: LEE_PREF("lz.distribucion") === "real" ? "real" : "compacta", cacheCompacta: null };
  const mensaje = (t, tipo) => Redes.estadoEn($("lz-estado"), t, tipo);
  const puedeEditar = () => !!(st.datos && st.datos.proyecto && st.datos.proyecto.puede_editar);
  const colorDe = (e) => COLOR[e.tipo === "mufa" ? (e.subtipo || "empalme") : e.tipo] || "#e53935";
  const etiquetaTipo = (e) => ({ nodo: "Nodo", odf: "ODF", mufa: { empalme: "Mufa (empalme)", distribucion: "Mufa (distribución)", terminal: "Mufa (terminal)", reserva: "Reserva" }[e.subtipo || "empalme"] || "Mufa" }[e.tipo]);
  const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // ------------------------------------------------------------------ abrir y cargar
  async function abrir(proyectoId, lienzoId) {
    $("modal-lz").hidden = false;
    crearStage();
    mensaje("Cargando las zonas…", "cargando");
    const z = await Redes.llamar("lienzo_zonas", {});
    if (!z.ok) { mensaje(z.error, "error"); return false; }
    st.zonas = z.zonas;
    const elegida = st.zonas.find((x) => x.id === Number(proyectoId)) || st.zonas.find((x) => x.id === st.proyectoId) || st.zonas.find((x) => x.mufas + x.nodos > 0) || st.zonas[0];
    pintarZonas(elegida && elegida.id);
    if (!elegida) { mensaje("No hay zonas con mufas todavía.", ""); return false; }
    return cargar(elegida.id, false, lienzoId || null);
  }

  function pintarZonas(elegida) {
    $("lz-zona").innerHTML = st.zonas.map((z) => `<option value="${z.id}">${esc(z.zona || z.nombre)} · ${z.mufas} mufas${z.nodos ? ` + ${z.nodos} nodos` : ""} · ${z.colocados} en el esquema</option>`).join("");
    if (elegida) $("lz-zona").value = String(elegida);
  }

  async function cargar(proyectoId, conservarVista = false, lienzoId = undefined, sinGuardar = false) {
    if (!sinGuardar && proyectoId === st.proyectoId) await guardarPosiciones();               // what was just placed or moved is not lost by reading again
    mensaje("Cargando el esquema…", "cargando");
    const pedido = lienzoId !== undefined ? lienzoId : (proyectoId === st.proyectoId ? st.lienzoId : null);       // the same schema again, unless another zone / one chosen
    const r = await Redes.llamar("lienzo", pedido ? { proyecto_id: proyectoId, lienzo_id: pedido } : { proyecto_id: proyectoId });
    if (!r.ok) { mensaje(r.error, "error"); if (pedido) { st.lienzoId = null; } return false; }
    aplicar(r, proyectoId, conservarVista);
    mensaje("");
    return true;
  }

  function aplicar(r, proyectoId, conservarVista) {
    st.proyectoId = proyectoId;
    st.lienzoId = r.lienzo ? r.lienzo.id : null;
    st.datos = r;
    st.elementos = new Map(r.elementos.map((e) => [e.id, e]));
    st.pos = new Map(r.colocados.map((c) => [c.elemento_id, { x: c.x, y: c.y }]));
    st.cables = r.cables;
    st.pendientes.clear(); st.quitar.clear();
    st.referenciaPendiente = false;
    st.cacheCompacta = null;
    if (!st.cables.some((c) => st.seleccion && st.seleccion.tipo === "cable" && st.seleccion.id === c.id) && st.seleccion && st.seleccion.tipo === "cable") st.seleccion = null;
    if (st.seleccion && st.seleccion.tipo === "caja" && !st.pos.has(st.seleccion.id)) st.seleccion = null;
    document.querySelectorAll("#modal-lz [data-lz-edita]").forEach((b) => { b.hidden = !puedeEditar(); });
    $("lz-titulo").textContent = `Esquema de zona · ${r.proyecto.zona || r.proyecto.nombre}`;
    $("lz-esquema").innerHTML = (r.lienzos || []).map((l) => `<option value="${l.id}">${esc(l.nombre)}</option>`).join("");
    if (r.lienzo) $("lz-esquema").value = String(r.lienzo.id);
    $("lz-escala").innerHTML = ESCALAS.map((e) => `<option value="${e}">${e} px por metro</option>`).join("");
    $("lz-escala").value = String(r.lienzo ? r.lienzo.escala : 2);
    pintarLista();
    dibujar();
    if (!conservarVista) ajustar();
    info();
  }

  // ------------------------------------------------------------------ posiciones por coordenadas reales
  const escala = () => (st.datos && st.datos.lienzo && st.datos.lienzo.escala) || 2;

  /** The reference point of the layout: the one the schema keeps, else the centre of the zone's located elements (kept at the next save). */
  function origen() {
    const lz = st.datos && st.datos.lienzo;
    if (!lz) return null;
    if (lz.origen_lat !== null && lz.origen_lat !== undefined) return { lat: lz.origen_lat, lon: lz.origen_lon };
    const con = [...st.elementos.values()].map(puntoReal).filter(Boolean);
    if (!con.length) return null;
    lz.origen_lat = con.reduce((a, p) => a + p.lat, 0) / con.length;
    lz.origen_lon = con.reduce((a, p) => a + p.lon, 0) / con.length;
    st.referenciaPendiente = true;
    return { lat: lz.origen_lat, lon: lz.origen_lon };
  }

  /** Where the mufa really is: its point of the KMZ (the map the crews see) when the KMZ has one with its name, else its own coordinate; null when it has neither. */
  function puntoReal(e) {
    if (e.kmz) return { lat: e.kmz.lat, lon: e.kmz.lon, deKmz: true };
    return e.lat === null || e.lon === null ? null : { lat: e.lat, lon: e.lon, deKmz: false };
  }

  /** Metres-true position (px) of the centre of the mufa, north up, from the reference point at the schema's scale. */
  function posicionAEscala(q, o) {
    const k = escala();
    return { x: (q.lon - o.lon) * M_LON * Math.cos((o.lat * Math.PI) / 180) * k, y: -(q.lat - o.lat) * M_LAT * k };
  }

  /** One axis of the compact layout: the values (px) in order; those within half a step are the same column / row; each next column is a step apart: the real gap
   *  but never less than `minimo` (no overlap) nor more than `maximo` (a big hole of the map is a hole of one or two boxes). Returns Map value -> position. */
  function ejeCompacto(valores, minimo, maximo) {
    const orden = [...new Set(valores)].sort((a, b) => a - b), pos = new Map();
    let inicio = null, previo = null, p = 0;
    orden.forEach((v) => {
      if (previo === null) { inicio = previo = v; }
      else if (v - inicio > minimo * 0.5) { p += Math.min(maximo, Math.max(minimo, v - previo)); inicio = previo = v; }
      pos.set(v, p);
    });
    return pos;
  }

  /** The compact layout of the WHOLE zone (every mufa with a place on the map): same direction as the map, close together; a mufa lands in the same slot whatever the
   *  order they are dragged in. Map id -> top-left corner of its box. Cached until the zone, the reference or the scale change. */
  function distribucionCompacta() {
    const o = origen();
    if (!o) return new Map();
    const clave = `${st.elementos.size}|${o.lat}|${o.lon}|${escala()}`;
    if (st.cacheCompacta && st.cacheCompacta.clave === clave) return st.cacheCompacta.mapa;
    const todos = [...st.elementos.values()].map((e) => ({ e, q: puntoReal(e) })).filter((x) => x.q)
      .map((x) => ({ id: x.e.id, c: posicionAEscala(x.q, o) }));
    const colX = ejeCompacto(todos.map((t) => t.c.x), PASO_X, PASO_X_MAX), colY = ejeCompacto(todos.map((t) => t.c.y), PASO_Y, PASO_Y_MAX);
    const puestas = [], mapa = new Map();
    todos.sort((a, b) => colY.get(a.c.y) - colY.get(b.c.y) || colX.get(a.c.x) - colX.get(b.c.x) || a.id - b.id).forEach((t) => {
      const p = redondear(libre({ x: colX.get(t.c.x) - ANCHO / 2, y: colY.get(t.c.y) - ALTO / 2 }, puestas));      // two at the very same point: the second to the side
      puestas.push(p); mapa.set(t.id, p);
    });
    st.cacheCompacta = { clave, mapa };
    return mapa;
  }

  /** Top-left corner of the box of `e`: compact (same direction as the map, close together) or true to scale, as chosen; null when it has no coordinate. */
  function posicionReal(e) {
    const q = puntoReal(e), o = q ? origen() : null;
    if (!o) return null;
    if (st.distribucion === "compacta") { const p = distribucionCompacta().get(e.id); return p ? { ...p } : null; }
    const c = posicionAEscala(q, o);
    return { x: c.x - ANCHO / 2, y: c.y - ALTO / 2 };
  }

  const choca = (a, b) => Math.abs(a.x - b.x) < ANCHO + 8 && Math.abs(a.y - b.y) < ALTO + 8;

  /** The free place nearest to `p` (a box laid over another one - a parallel mufa at the same point - moves to the side, never far). `ocupadas`: the boxes in the way. */
  function libre(p, ocupadas) {
    if (!ocupadas.some((o) => choca(o, p))) return p;
    const sx = ANCHO + 12, sy = ALTO + 12;
    for (let r = 1; r <= 40; r++) {
      const candidatos = [];
      for (let i = -r; i <= r; i++) for (let j = -r; j <= r; j++) if (Math.max(Math.abs(i), Math.abs(j)) === r) candidatos.push({ x: p.x + i * sx, y: p.y + j * sy });
      candidatos.sort((a, b) => Math.hypot(a.x - p.x, a.y - p.y) - Math.hypot(b.x - p.x, b.y - p.y));
      const hallado = candidatos.find((c) => !ocupadas.some((o) => choca(o, c)));
      if (hallado) return hallado;
    }
    return p;
  }

  const redondear = (p) => ({ x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100 });

  async function acomodarPorCoordenadas() {
    if (!puedeEditar() || !st.pos.size) return;
    if (!(await Redes.confirmar("Se vuelven a acomodar todas las cajas según las coordenadas reales de sus mufas (las que no tienen coordenada se quedan donde están). ¿Continuar?", "Acomodar"))) return;
    if (!origen()) { mensaje("Ninguna de las mufas tiene coordenada: no hay cómo acomodarlas", "error"); return; }
    st.referenciaPendiente = true;
    const n = acomodarSinPreguntar();
    mensaje(`${n} caja(s) acomodadas según sus coordenadas`, "ok");
  }

  async function cambiarEscala() {
    const nueva = Number($("lz-escala").value), lz = st.datos.lienzo;
    st.cacheCompacta = null;
    if (nueva === lz.escala) return;
    if (st.pos.size && !(await Redes.confirmar(`Con ${nueva} píxeles por metro las cajas se vuelven a acomodar según sus coordenadas. ¿Continuar?`, "Cambiar escala"))) { $("lz-escala").value = String(lz.escala); return; }
    lz.escala = nueva;
    st.referenciaPendiente = true;
    if (st.pos.size) { await acomodarSinPreguntar(); } else programarGuardado();
  }

  function acomodarSinPreguntar() {
    const fijas = [], movibles = [];
    st.pos.forEach((p, id) => { const e = st.elementos.get(id); const real = e && posicionReal(e); if (real) movibles.push({ id, real }); else fijas.push(p); });
    movibles.sort((a, b) => a.real.y - b.real.y || a.real.x - b.real.x);
    const puestas = [...fijas];
    movibles.forEach((m) => { const p = redondear(libre(m.real, puestas)); puestas.push(p); st.pos.set(m.id, p); st.pendientes.add(m.id); });
    dibujar(); ajustar(); programarGuardado();
    return movibles.length;
  }

  // ------------------------------------------------------------------ lista de la zona
  function pintarLista() {
    const q = normal($("lz-buscar").value).split(/\s+/).filter(Boolean);
    const verColocados = $("lz-ver-colocados").checked;
    const todos = [...st.elementos.values()];
    const puestos = todos.filter((e) => st.pos.has(e.id)).length;
    const visibles = todos.filter((e) => (verColocados || !st.pos.has(e.id)) && q.every((p) => normal(`${e.nombre} ${e.codigo || ""}`).includes(p)));
    const grupo = (titulo, lista) => lista.length ? `<li class="lz-grupo">${titulo} (${lista.length})</li>` + lista.map((e) => {
      const puesto = st.pos.has(e.id);
      return `<li class="lz-item${puesto ? " colocado" : ""}" data-lz-item="${e.id}" draggable="${puesto || !puedeEditar() ? "false" : "true"}" title="${puesto ? "Ya está en el esquema: clic para buscarlo" : "Arrástrelo al lienzo (o doble clic)"}${e.kmz ? ` · el KMZ la tiene a ${Math.round(e.kmz.distancia_m)} m de la coordenada guardada` : ""}">
        <i class="lz-muestra" style="background:${colorDe(e)}"></i><span class="lz-nombre">${esc(e.nombre)}</span>
        <span class="lz-tipo">${esc(etiquetaTipo(e))}${e.lat === null && !e.kmz ? ` · <b class="lz-sin">sin ubicar</b>` : ""}${e.kmz ? " · posición del KMZ" : ""}${puesto ? " · en el esquema" : ""}</span></li>`;
    }).join("") : "";
    $("lz-lista").innerHTML = grupo("Nodos y ODF", visibles.filter((e) => e.tipo !== "mufa")) + grupo("Mufas", visibles.filter((e) => e.tipo === "mufa"))
      || `<li class="lz-vacio">${todos.length ? (q.length ? "Nada con ese texto." : "Todo está en el esquema.") : "Esta zona no tiene mufas ni nodos."}</li>`;
    $("lz-cuenta").textContent = `${puestos} de ${todos.length} en el esquema`;
  }

  // ------------------------------------------------------------------ lienzo (Konva)
  function crearStage() {
    if (st.stage) return;
    const caja = $("lz-lienzo");
    st.stage = new Konva.Stage({ container: $("lz-konva"), width: caja.clientWidth || 800, height: caja.clientHeight || 500, draggable: true, dragDistance: 4, dragButtons: [0, 1] });
    st.capaLineas = new Konva.Layer();
    st.capaCajas = new Konva.Layer();
    st.stage.add(st.capaLineas, st.capaCajas);
    st.stage.on("wheel", (e) => {                                  // as in Visio: the wheel scrolls, Ctrl + wheel zooms
      e.evt.preventDefault();
      if (e.evt.ctrlKey) {
        const viejo = st.stage.scaleX(), p = st.stage.getPointerPosition();
        const punto = { x: (p.x - st.stage.x()) / viejo, y: (p.y - st.stage.y()) / viejo };
        const nuevo = Math.max(ZOOM_MIN, Math.min(3, viejo * (e.evt.deltaY > 0 ? 1 / 1.12 : 1.12)));
        st.stage.scale({ x: nuevo, y: nuevo });
        st.stage.position({ x: p.x - punto.x * nuevo, y: p.y - punto.y * nuevo });
        return;
      }
      const lado = e.evt.shiftKey ? (e.evt.deltaY || e.evt.deltaX) : e.evt.deltaX, arriba = e.evt.shiftKey ? 0 : e.evt.deltaY;
      st.stage.position({ x: st.stage.x() - lado, y: st.stage.y() - arriba });
    });
    st.stage.on("click tap", (e) => { if (e.target === st.stage) { seleccionar(null); if (st.modo === "cable") st.origen = null, resaltarOrigen(); } });
    new ResizeObserver(() => { if (caja.clientWidth) st.stage.size({ width: caja.clientWidth, height: caja.clientHeight }); }).observe(caja);
  }

  function dibujar() {
    if (!st.stage) return;
    st.capaLineas.destroyChildren(); st.capaCajas.destroyChildren();
    st.cajas.clear(); st.lineas.clear();
    st.pos.forEach((p, id) => {
      const e = st.elementos.get(id);
      if (e) crearCaja(e, p);
    });
    st.cables.forEach((c) => { if (st.pos.has(c.origen_id) && st.pos.has(c.destino_id)) crearLinea(c); });
    resaltar();
    st.capaLineas.draw(); st.capaCajas.draw();
    $("lz-vacio").hidden = st.pos.size > 0;
  }

  function crearCaja(e, p) {
    const g = new Konva.Group({ x: p.x, y: p.y, draggable: puedeEditar() && st.modo !== "cable", name: "caja" });
    g.add(new Konva.Rect({ width: ANCHO, height: ALTO, cornerRadius: e.tipo === "nodo" ? 22 : 8, fill: colorDe(e), stroke: "#1a1a1a", strokeWidth: 1.5, shadowColor: "#000", shadowBlur: 4, shadowOpacity: 0.25, shadowOffsetY: 2, name: "marco" }));
    if (e.tipo !== "mufa") g.add(new Konva.Text({ x: 0, y: -15, width: ANCHO, text: "⚡ Fuente de la red", fontSize: 10, fontStyle: "bold", fill: "#b45309", align: "center", listening: false }));
    g.add(new Konva.Text({ x: 6, y: 5, width: ANCHO - 12, height: ALTO - 10, text: e.nombre, fontSize: 12, fontStyle: "bold", fill: "#fff", align: "center", verticalAlign: "middle", ellipsis: true, wrap: "word", listening: false }));
    g.on("dragmove", () => { st.pos.set(e.id, { x: g.x(), y: g.y() }); moverLineas(e.id); });
    g.on("dragend", () => { st.pos.set(e.id, { x: Math.round(g.x() * 100) / 100, y: Math.round(g.y() * 100) / 100 }); st.pendientes.add(e.id); st.quitar.delete(e.id); programarGuardado(); });
    g.on("click tap", (ev) => { ev.cancelBubble = true; clicCaja(e); });
    g.on("dblclick dbltap", (ev) => { ev.cancelBubble = true; entrar(e); });
    g.on("mouseenter", () => { st.stage.container().style.cursor = st.modo === "cable" ? "crosshair" : "pointer"; });
    g.on("mouseleave", () => { st.stage.container().style.cursor = "default"; });
    st.capaCajas.add(g);
    st.cajas.set(e.id, g);
  }

  function centro(id) {
    const p = st.pos.get(id);
    return { x: p.x + ANCHO / 2, y: p.y + ALTO / 2 };
  }

  function crearLinea(c) {
    const a = centro(c.origen_id), b = centro(c.destino_id);
    const color = c.color && !/^#1f6feb$/i.test(c.color) ? c.color : (COLOR_HILOS[c.hilos] || "#1f6feb");
    const g = new Konva.Group({ name: "cable" });
    const linea = new Konva.Line({ points: [a.x, a.y, b.x, b.y], stroke: color, strokeWidth: Math.max(2, Math.min(7, Math.round((c.hilos || 12) / 24) + 2)), lineCap: "round", hitStrokeWidth: 14, name: "trazo" });
    const rotulo = new Konva.Label({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, listening: false });
    rotulo.add(new Konva.Tag({ fill: "#ffffff", stroke: color, cornerRadius: 4, pointerDirection: "none" }));
    rotulo.add(new Konva.Text({ text: `${c.hilos ? c.hilos + " h" : "? h"}${c.conectados ? ` · ${c.conectados}↔` : ""}`, fontSize: 11, padding: 3, fill: "#222" }));
    rotulo.offsetX(rotulo.width() / 2); rotulo.offsetY(rotulo.height() / 2);
    g.add(linea, rotulo);
    g.on("click tap", (ev) => { ev.cancelBubble = true; seleccionar({ tipo: "cable", id: c.id }); });
    g.on("mouseenter", () => { st.stage.container().style.cursor = "pointer"; });
    g.on("mouseleave", () => { st.stage.container().style.cursor = "default"; });
    st.capaLineas.add(g);
    st.lineas.set(c.id, { g, linea, rotulo, color, c });
  }

  function moverLineas(id) {
    st.lineas.forEach((l) => {
      if (l.c.origen_id !== id && l.c.destino_id !== id) return;
      const a = centro(l.c.origen_id), b = centro(l.c.destino_id);
      l.linea.points([a.x, a.y, b.x, b.y]);
      l.rotulo.position({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    });
    st.capaLineas.batchDraw();
  }

  function resaltar() {
    st.cajas.forEach((g, id) => {
      const marco = g.findOne(".marco");
      const sel = st.seleccion && st.seleccion.tipo === "caja" && st.seleccion.id === id;
      const origen = st.modo === "cable" && st.origen === id;
      marco.stroke(origen ? "#00c853" : sel ? "#1f6feb" : "#1a1a1a"); marco.strokeWidth(origen || sel ? 4 : 1.5);
    });
    st.lineas.forEach((l, id) => {
      const sel = st.seleccion && st.seleccion.tipo === "cable" && st.seleccion.id === id;
      l.linea.opacity(!st.seleccion || sel || st.seleccion.tipo !== "cable" ? 1 : 0.45);
      l.linea.shadowColor("#1f6feb"); l.linea.shadowBlur(sel ? 12 : 0); l.linea.shadowOpacity(sel ? 0.9 : 0);
    });
    st.capaCajas.batchDraw(); st.capaLineas.batchDraw();
  }
  const resaltarOrigen = resaltar;

  function seleccionar(sel) {
    st.seleccion = sel;
    resaltar();
    info();
  }

  function info() {
    const s = st.seleccion, caja = $("lz-info");
    $("lz-quitar").disabled = !(s && s.tipo === "caja" && puedeEditar());
    $("lz-eliminar-cable").disabled = !(s && s.tipo === "cable" && puedeEditar());
    $("lz-abrir-a").hidden = $("lz-abrir-b").hidden = !(s && s.tipo === "cable");
    if (!s) {
      caja.textContent = st.modo === "cable" ? (st.origen ? "Clic en la caja donde termina el cable" : "Clic en la caja donde empieza el cable") : "Seleccione una caja o un cable. Doble clic en una caja: entrar a su editor de mufa.";
      return;
    }
    if (s.tipo === "caja") {
      const e = st.elementos.get(s.id);
      const n = st.cables.filter((c) => c.origen_id === s.id || c.destino_id === s.id).length;
      caja.innerHTML = `<b>${esc(e.nombre)}</b> · ${esc(etiquetaTipo(e))} · ${n} cable(s) · doble clic para entrar`;
      return;
    }
    const c = st.cables.find((x) => x.id === s.id);
    if (!c) return;
    const o = st.elementos.get(c.origen_id), d = st.elementos.get(c.destino_id);
    $("lz-abrir-a").textContent = `Abrir ${o ? o.nombre : "origen"}`; $("lz-abrir-b").textContent = `Abrir ${d ? d.nombre : "destino"}`;
    caja.innerHTML = `<b>${esc(c.nombre)}</b> · ${esc(o ? o.nombre : "?")} → ${esc(d ? d.nombre : "?")} · ${c.hilos || "?"} hilos · ${Math.round(c.longitud_m || 0).toLocaleString("es-NI")} m · ${c.conectados} conexión(es) de hilo`;
  }

  function ajustar() {
    if (!st.stage) return;
    const cajas = [...st.cajas.values()];
    if (!cajas.length) { st.stage.scale({ x: 1, y: 1 }); st.stage.position({ x: 20, y: 20 }); return; }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    cajas.forEach((g) => { x0 = Math.min(x0, g.x()); y0 = Math.min(y0, g.y()); x1 = Math.max(x1, g.x() + ANCHO); y1 = Math.max(y1, g.y() + ALTO); });
    const w = st.stage.width(), h = st.stage.height(), m = 50;
    const k = Math.max(ZOOM_MIN, Math.min(1.2, Math.min((w - 2 * m) / (x1 - x0 || 1), (h - 2 * m) / (y1 - y0 || 1))));
    st.stage.scale({ x: k, y: k });
    st.stage.position({ x: m - x0 * k + (w - 2 * m - (x1 - x0) * k) / 2, y: m - y0 * k + (h - 2 * m - (y1 - y0) * k) / 2 });
  }

  // ------------------------------------------------------------------ poner, mover, quitar
  function aLienzo(clientX, clientY) {
    const r = $("lz-konva").getBoundingClientRect(), k = st.stage.scaleX();
    return { x: (clientX - r.left - st.stage.x()) / k - ANCHO / 2, y: (clientY - r.top - st.stage.y()) / k - ALTO / 2 };
  }

  function poner(id, punto) {
    const e = st.elementos.get(id);
    if (!e || !puedeEditar()) return;
    const real = $("lz-por-coord").checked ? posicionReal(e) : null;                // where the mufa is on the map, else where it was dropped
    const ocupadas = [...st.pos.entries()].filter(([otro]) => otro !== id).map(([, q]) => q);
    const p = redondear(real ? libre(real, ocupadas) : punto);
    st.pos.set(id, p);
    st.pendientes.add(id); st.quitar.delete(id);
    dibujar();
    seleccionar({ tipo: "caja", id });
    pintarLista();
    if (real) centrarEn(id);                                                         // by its coordinates it may land away from where it was dropped
    programarGuardado();
  }

  function centrarEn(id) {
    const g = st.cajas.get(id);
    if (!g || !st.stage) return;
    const k = st.stage.scaleX(), x = g.x() * k + st.stage.x(), y = g.y() * k + st.stage.y();
    if (x < 0 || y < 0 || x + ANCHO * k > st.stage.width() || y + ALTO * k > st.stage.height()) {
      st.stage.position({ x: st.stage.width() / 2 - (g.x() + ANCHO / 2) * k, y: st.stage.height() / 2 - (g.y() + ALTO / 2) * k });
    }
  }

  function quitarSeleccion() {
    const s = st.seleccion;
    if (!s || s.tipo !== "caja" || !puedeEditar()) return;
    st.pos.delete(s.id); st.pendientes.delete(s.id); st.quitar.add(s.id);
    seleccionar(null);
    dibujar(); pintarLista();
    programarGuardado();
  }

  function programarGuardado() {
    mensaje("Cambios sin guardar…");
    clearTimeout(st.temporizador);
    st.temporizador = setTimeout(guardarPosiciones, 450);
  }

  function guardarPosiciones() {
    clearTimeout(st.temporizador);
    st.guardando = st.guardando.then(async () => {
      if (!st.pendientes.size && !st.quitar.size && !st.referenciaPendiente) return;
      const colocados = [...st.pendientes].filter((id) => st.pos.has(id)).map((id) => ({ elemento_id: id, ...st.pos.get(id) }));
      const quitados = [...st.quitar];
      st.pendientes.clear(); st.quitar.clear();
      const ref = st.referenciaPendiente && st.datos.lienzo.origen_lat !== null && st.datos.lienzo.origen_lat !== undefined
        ? { origen: { lat: st.datos.lienzo.origen_lat, lon: st.datos.lienzo.origen_lon }, escala: st.datos.lienzo.escala } : {};
      st.referenciaPendiente = false;
      const r = await Redes.llamar("guardar_lienzo", { proyecto_id: st.proyectoId, lienzo_id: st.lienzoId, version: st.datos.lienzo.version, colocados, quitados, ...ref });
      if (r.ok) {
        st.datos.lienzo = r.lienzo;
        const z = st.zonas.find((x) => x.id === st.proyectoId);
        if (z) { z.colocados = st.pos.size; const v = $("lz-zona").value; pintarZonas(Number(v)); }
        mensaje("Guardado", "ok");
      } else {
        mensaje(r.error, "error");
        if (r.conflicto) await cargar(st.proyectoId, true, undefined, true);
      }
    });
    return st.guardando;
  }

  // ------------------------------------------------------------------ cables
  function clicCaja(e) {
    if (st.modo !== "cable") { seleccionar({ tipo: "caja", id: e.id }); return; }
    if (st.origen === null) { st.origen = e.id; resaltar(); info(); return; }
    if (st.origen === e.id) { st.origen = null; resaltar(); info(); return; }
    const origen = st.origen;
    st.origen = null;
    resaltar();
    pedirCable(origen, e.id);
  }

  function modoCable(on) {
    st.modo = on && puedeEditar() ? "cable" : null;
    st.origen = null;
    $("lz-conectar").classList.toggle("activo", st.modo === "cable");
    $("lz-conectar").setAttribute("aria-pressed", st.modo === "cable" ? "true" : "false");
    st.cajas.forEach((g) => g.draggable(puedeEditar() && st.modo !== "cable"));
    seleccionar(null);
  }

  function pedirCable(origenId, destinoId) {
    const o = st.elementos.get(origenId), d = st.elementos.get(destinoId);
    if (o.lat === null || d.lat === null) {
      mensaje(`${o.lat === null ? o.nombre : d.nombre} no tiene coordenada: colóquela en el mapa (vista Red existente) antes de unirla con un cable`, "error");
      return;
    }
    const f = $("lz-cable-form");
    st.cableNuevo = { origenId, destinoId };
    f.elements.nombre.value = `${o.nombre} – ${d.nombre}`;
    f.elements.clase.value = o.tipo === "nodo" ? "troncal" : "distribucion";
    f.elements.tipo.value = "ADSS";
    f.elements.hilos.innerHTML = HILOS.map((h) => `<option value="${h}">${h} hilos</option>`).join("");
    f.elements.hilos.value = "24";
    f.elements.buffer.value = "12";
    $("lz-cable-error").textContent = "";
    $("lz-cable-sentido").textContent = `${o.nombre} → ${d.nombre}`;
    $("modal-lz-cable").hidden = false;
    f.elements.nombre.focus();
    f.elements.nombre.select();
  }

  async function crearCable(ev) {
    ev.preventDefault();
    const f = $("lz-cable-form"), { origenId, destinoId } = st.cableNuevo;
    const o = st.elementos.get(origenId), d = st.elementos.get(destinoId);
    const hilos = Number(f.elements.hilos.value);
    $("lz-cable-error").textContent = "";
    const r = await Redes.llamar("guardar_red", { proyecto_id: st.proyectoId, cambios: { cables: [{
      id: "nuevo", nombre: f.elements.nombre.value.trim(), clase: f.elements.clase.value, tipo: f.elements.tipo.value, hilos, hilos_por_buffer: Number(f.elements.buffer.value),
      color: COLOR_HILOS[hilos] || "#1f6feb", origen_id: origenId, destino_id: destinoId,
      vertices: [{ lat: o.lat, lon: o.lon, elemento_id: origenId }, { lat: d.lat, lon: d.lon, elemento_id: destinoId }] }] } });
    if (!r.ok) { $("lz-cable-error").textContent = (r.errores ? Object.values(r.errores).join(" · ") : r.error) || "No se pudo crear el cable"; return; }
    $("modal-lz-cable").hidden = true;
    await cargar(st.proyectoId, true);
    const nuevo = r.ids && r.ids.nuevo;
    if (nuevo) seleccionar({ tipo: "cable", id: nuevo });
    mensaje("Cable creado", "ok");
  }

  async function eliminarCable() {
    const s = st.seleccion;
    if (!s || s.tipo !== "cable" || !puedeEditar()) return;
    const c = st.cables.find((x) => x.id === s.id);
    if (!c) return;
    const texto = c.conectados ? `El cable «${c.nombre}» tiene ${c.conectados} conexión(es) de hilo que también se quitarán. ¿Eliminarlo?` : `¿Eliminar el cable «${c.nombre}»?`;
    if (!(await Redes.confirmar(texto, "Eliminar cable"))) return;
    const r = await Redes.llamar("guardar_red", { proyecto_id: st.proyectoId, cambios: { cables: [{ id: c.id, version: c.version, nombre: c.nombre, eliminar: true }] } });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    seleccionar(null);
    await cargar(st.proyectoId, true);
    mensaje("Cable eliminado", "ok");
  }

  function entrar(e) {
    if (!window.EditorMufa) return;
    if (st.pendientes.size || st.quitar.size) guardarPosiciones();
    window.EditorMufa.abrir(e.id, e.nombre);
  }

  // ------------------------------------------------------------------ eventos
  // ------------------------------------------------------------------ los esquemas de la zona: nuevo, renombrar, eliminar
  function pedirNombre(titulo, valor) {
    return new Promise((resolver) => {
      const f = $("lz-nombre-form");
      $("lz-nombre-titulo").textContent = titulo;
      f.elements.nombre.value = valor || "";
      $("lz-nombre-error").textContent = "";
      $("modal-lz-nombre").hidden = false;
      f.elements.nombre.focus(); f.elements.nombre.select();
      const fin = (v) => { $("modal-lz-nombre").hidden = true; f.onsubmit = null; $("lz-nombre-cancelar").onclick = null; resolver(v); };
      f.onsubmit = (ev) => { ev.preventDefault(); const v = f.elements.nombre.value.trim(); if (!v) { $("lz-nombre-error").textContent = "Escriba el nombre"; return; } fin(v); };
      $("lz-nombre-cancelar").onclick = () => fin(null);
    });
  }

  async function nuevoEsquema() {
    const nombre = await pedirNombre("Nuevo esquema de la zona", "");
    if (!nombre) return;
    await guardarPosiciones();
    const r = await Redes.llamar("crear_lienzo", { proyecto_id: st.proyectoId, nombre });
    if (!r.ok) { mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); return; }
    aplicar(r, st.proyectoId, false);
    mensaje(`Esquema «${r.lienzo.nombre}» creado`, "ok");
  }

  async function renombrarEsquema() {
    const actual = st.datos && st.datos.lienzo;
    if (!actual) return;
    const nombre = await pedirNombre("Nombre del esquema", actual.nombre);
    if (!nombre || nombre === actual.nombre) return;
    await guardarPosiciones();
    const r = await Redes.llamar("renombrar_lienzo", { proyecto_id: st.proyectoId, lienzo_id: actual.id, nombre, version: st.datos.lienzo.version });
    if (!r.ok) { mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); if (r.conflicto) cargar(st.proyectoId, true); return; }
    aplicar(r, st.proyectoId, true);
    mensaje(`Esquema renombrado: «${r.lienzo.nombre}»`, "ok");
  }

  async function eliminarEsquema() {
    const actual = st.datos && st.datos.lienzo;
    if (!actual) return;
    if (!(await Redes.confirmar(`¿Eliminar el esquema «${actual.nombre}»? Solo se borra cómo estaban acomodadas las cajas: las mufas y los cables siguen en la red.`, "Eliminar esquema"))) return;
    const r = await Redes.llamar("eliminar_lienzo", { proyecto_id: st.proyectoId, lienzo_id: actual.id, version: st.datos.lienzo.version });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    st.pendientes.clear(); st.quitar.clear();
    aplicar(r, st.proyectoId, false);
    mensaje("Esquema eliminado", "ok");
  }

  async function aparte() {
    if (!window.visor || !window.visor.abrirVentana) return;
    await guardarPosiciones();
    const z = st.datos.proyecto;
    const r = await window.visor.abrirVentana("esquema", { nombre: z.zona || z.nombre, id: st.proyectoId });
    if (r && r.ok) $("modal-lz").hidden = true;
  }

  // ------------------------------------------------------------------ las mufas del KMZ que la zona no tiene (nuevas o renombradas)
  async function abrirMufasKmz() {
    if (!st.proyectoId) return;
    mensaje("Leyendo las mufas del KMZ…", "cargando");
    const r = await Redes.llamar("mufas_kmz_zona", { proyecto_id: st.proyectoId });
    if (!r.ok) { mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); return; }
    mensaje("");
    st.kmzNuevas = r.nuevas;
    $("lz-kmz-titulo").textContent = `Mufas del KMZ que faltan en ${st.datos.proyecto.zona || st.datos.proyecto.nombre}`;
    $("lz-kmz-resumen").textContent = r.nuevas.length
      ? `${r.nuevas.length} mufa(s) del KMZ no están en la zona (la zona tiene ${r.en_zona}; el KMZ, ${r.en_kmz} alrededor). Elija qué hacer con cada una.`
      : `La zona está al día con el KMZ: ${r.en_zona} elementos en la zona, ${r.en_kmz} puntos del KMZ alrededor.`;
    $("lz-kmz-lista").innerHTML = r.nuevas.map((n, i) => `<tr data-i="${i}"><td><b>${esc(n.nombre)}</b><div class="nota">${n.categoria === "reserva" ? "Reserva" : n.categoria === "nodo" ? "Nodo" : "Mufa"} · ${n.lat.toFixed(6)}, ${n.lon.toFixed(6)}</div></td>
      <td><select data-lz-kmz="${i}" ${puedeEditar() ? "" : "disabled"}>
        ${n.cercana ? `<option value="renombrar" selected>Es «${esc(n.cercana.nombre)}» renombrada (a ${Math.round(n.cercana.distancia_m)} m)</option><option value="agregar">Agregar como mufa nueva</option>` : `<option value="agregar" selected>Agregar como mufa nueva</option>`}
        <option value="nada">No hacer nada</option></select></td></tr>`).join("");
    $("lz-kmz-aplicar").hidden = !r.nuevas.length || !puedeEditar();
    $("modal-lz-kmz").hidden = false;
  }

  async function aplicarMufasKmz() {
    const acciones = [];
    document.querySelectorAll("#lz-kmz-lista select[data-lz-kmz]").forEach((s) => {
      const n = st.kmzNuevas[Number(s.dataset.lzKmz)];
      if (s.value === "renombrar") acciones.push({ kmz_id: n.kmz_id, accion: "renombrar", elemento_id: n.cercana.id });
      else if (s.value === "agregar") acciones.push({ kmz_id: n.kmz_id, accion: "agregar" });
    });
    if (!acciones.length) { $("modal-lz-kmz").hidden = true; return; }
    $("lz-kmz-aplicar").disabled = true;
    const r = await Redes.llamar("aplicar_mufas_kmz_zona", { proyecto_id: st.proyectoId, acciones });
    $("lz-kmz-aplicar").disabled = false;
    if (!r.ok) { $("lz-kmz-error").textContent = (r.errores && Object.values(r.errores).join(" · ")) || r.error; return; }
    $("lz-kmz-error").textContent = "";
    $("modal-lz-kmz").hidden = true;
    const z = st.zonas.find((x) => x.id === st.proyectoId);
    await cargar(st.proyectoId, true);
    if (z) { z.mufas = [...st.elementos.values()].filter((e) => e.tipo === "mufa").length; pintarZonas(st.proyectoId); }
    mensaje(`${r.agregadas} mufa(s) agregada(s), ${r.renombradas} renombrada(s): ya están en la lista para arrastrarlas al esquema`, "ok");
  }

  // ------------------------------------------------------------------ el nodo / ODF que alimenta la red
  function centroZona() {
    const con = [...st.elementos.values()].map(puntoReal).filter(Boolean);
    return con.length ? { lat: con.reduce((a, p) => a + p.lat, 0) / con.length, lon: con.reduce((a, p) => a + p.lon, 0) / con.length } : null;
  }

  function pedirFuente() {
    if (!puedeEditar()) return;
    const f = $("lz-fuente-form"), c = centroZona();
    f.elements.tipo.value = "nodo:olt";
    f.elements.nombre.value = "";
    f.elements.coordenada.value = c ? `${c.lat.toFixed(6)}, ${c.lon.toFixed(6)}` : "";
    $("lz-fuente-error").textContent = "";
    $("modal-lz-fuente").hidden = false;
    f.elements.nombre.focus();
  }

  async function crearFuente(ev) {
    ev.preventDefault();
    const f = $("lz-fuente-form"), error = (t) => { $("lz-fuente-error").textContent = t; };
    const nombre = f.elements.nombre.value.trim();
    if (!nombre) { error("Escriba el nombre del nodo o del ODF"); return; }
    const c = window.Coordenadas ? window.Coordenadas.interpretar(f.elements.coordenada.value) : { estado: "error", mensaje: "No hay lector de coordenadas" };
    if (c.estado === "invertida") { error("La latitud y la longitud parecen invertidas (escriba primero la latitud)"); return; }
    if (c.estado !== "ok") { error(c.mensaje || "Escriba la coordenada del nodo (latitud, longitud)"); return; }
    const [tipo, subtipo] = f.elements.tipo.value.split(":");
    const r = await Redes.llamar("guardar_red", { proyecto_id: st.proyectoId, cambios: { elementos: [{ id: "nuevo", tipo, subtipo: subtipo || null, nombre, lat: c.lat, lon: c.lon }] } });
    if (!r.ok) { error((r.errores ? Object.values(r.errores).join(" · ") : r.error) || "No se pudo crear"); return; }
    $("modal-lz-fuente").hidden = true;
    await cargar(st.proyectoId, true);
    const nuevo = r.ids && r.ids.nuevo;
    if (nuevo && st.elementos.has(nuevo)) { const b = $("lz-konva").getBoundingClientRect(); poner(nuevo, aLienzo(b.left + b.width / 2, b.top + b.height / 2)); }
    mensaje(`«${nombre}» creado: es la fuente de la red de la zona`, "ok");
  }

  function cerrar() {
    if (window.visor && window.visor.aparte === "esquema") { if (st.pendientes.size || st.quitar.size) guardarPosiciones(); window.visor.cerrarVentana(); return; }       // a window of its own: closing it closes the window
    $("modal-lz").hidden = true;
    $("modal-lz-cable").hidden = true;
    if (st.pendientes.size || st.quitar.size) guardarPosiciones();
  }

  function conectar() {
    if (st.conectado || !$("modal-lz")) return;
    st.conectado = true;
    $("lz-cerrar").addEventListener("click", cerrar);
    $("lz-max").addEventListener("click", () => $("modal-lz").classList.toggle("maximizado"));
    $("lz-zona").addEventListener("change", async () => { await guardarPosiciones(); st.seleccion = null; st.origen = null; cargar(Number($("lz-zona").value)); });
    $("lz-esquema").addEventListener("change", async () => { await guardarPosiciones(); st.seleccion = null; st.origen = null; cargar(st.proyectoId, false, Number($("lz-esquema").value)); });
    $("lz-nuevo").addEventListener("click", nuevoEsquema);
    $("lz-kmz").addEventListener("click", abrirMufasKmz);
    $("lz-kmz-aplicar").addEventListener("click", aplicarMufasKmz);
    $("lz-kmz-cerrar").addEventListener("click", () => { $("modal-lz-kmz").hidden = true; $("lz-kmz-error").textContent = ""; });
    $("lz-fuente").addEventListener("click", pedirFuente);
    $("lz-fuente-form").addEventListener("submit", crearFuente);
    $("lz-fuente-cancelar").addEventListener("click", () => { $("modal-lz-fuente").hidden = true; });
    $("lz-geo").addEventListener("click", acomodarPorCoordenadas);
    $("lz-distribucion").value = st.distribucion;
    $("lz-escala").disabled = st.distribucion === "compacta";
    $("lz-distribucion").addEventListener("change", async () => {
      const nueva = $("lz-distribucion").value;
      if (nueva === st.distribucion) return;
      if (st.pos.size && !(await Redes.confirmar(nueva === "compacta" ? "Las cajas se vuelven a acomodar en la distribución compacta: la misma dirección que el mapa pero pegadas. ¿Continuar?"
        : "Las cajas se vuelven a acomodar a escala real (con la distancia del mapa). ¿Continuar?", "Cambiar distribución"))) { $("lz-distribucion").value = st.distribucion; return; }
      st.distribucion = nueva; st.cacheCompacta = null;
      GUARDA_PREF("lz.distribucion", nueva);
      $("lz-escala").disabled = nueva === "compacta";
      if (st.pos.size) { st.referenciaPendiente = true; acomodarSinPreguntar(); }
    });
    $("lz-escala").addEventListener("change", cambiarEscala);
    $("lz-por-coord").checked = LEE_PREF("lz.por_coord") !== "0";
    $("lz-por-coord").addEventListener("change", () => GUARDA_PREF("lz.por_coord", $("lz-por-coord").checked ? "1" : "0"));
    $("lz-renombrar").addEventListener("click", renombrarEsquema);
    $("lz-borrar").addEventListener("click", eliminarEsquema);
    $("lz-aparte").addEventListener("click", aparte);
    $("lz-recargar").addEventListener("click", async () => { await guardarPosiciones(); cargar(st.proyectoId, true); });
    $("lz-buscar").addEventListener("input", pintarLista);
    $("lz-ver-colocados").addEventListener("change", pintarLista);
    $("lz-ajustar").addEventListener("click", ajustar);
    $("lz-acercar").addEventListener("click", () => st.stage.scale({ x: st.stage.scaleX() * 1.2, y: st.stage.scaleY() * 1.2 }));
    $("lz-alejar").addEventListener("click", () => st.stage.scale({ x: st.stage.scaleX() / 1.2, y: st.stage.scaleY() / 1.2 }));
    $("lz-conectar").addEventListener("click", () => modoCable(st.modo !== "cable"));
    $("lz-quitar").addEventListener("click", quitarSeleccion);
    $("lz-eliminar-cable").addEventListener("click", eliminarCable);
    const abrirExtremo = (campo) => { const c = st.seleccion && st.seleccion.tipo === "cable" && st.cables.find((x) => x.id === st.seleccion.id); const e = c && st.elementos.get(c[campo]); if (e) entrar(e); };
    $("lz-abrir-a").addEventListener("click", () => abrirExtremo("origen_id"));
    $("lz-abrir-b").addEventListener("click", () => abrirExtremo("destino_id"));
    // list: drag to the canvas, double click to put it in the centre, click on a placed one to find it
    $("lz-lista").addEventListener("dragstart", (ev) => {
      const li = ev.target.closest("[data-lz-item]");
      if (!li || li.classList.contains("colocado")) { ev.preventDefault(); return; }
      ev.dataTransfer.setData("text/plain", `lz:${li.dataset.lzItem}`);
      ev.dataTransfer.effectAllowed = "copy";
    });
    $("lz-lista").addEventListener("dblclick", (ev) => {
      const li = ev.target.closest("[data-lz-item]");
      if (!li || li.classList.contains("colocado")) return;
      const r = $("lz-konva").getBoundingClientRect();
      const p = aLienzo(r.left + r.width / 2 + (st.pos.size % 5) * 24, r.top + r.height / 2 + (st.pos.size % 5) * 24);
      poner(Number(li.dataset.lzItem), p);
    });
    $("lz-lista").addEventListener("click", (ev) => {
      const li = ev.target.closest("[data-lz-item]");
      if (!li || !li.classList.contains("colocado")) return;
      const id = Number(li.dataset.lzItem), g = st.cajas.get(id);
      if (!g) return;
      seleccionar({ tipo: "caja", id });
      const k = st.stage.scaleX();
      st.stage.position({ x: st.stage.width() / 2 - (g.x() + ANCHO / 2) * k, y: st.stage.height() / 2 - (g.y() + ALTO / 2) * k });
    });
    const lienzo = $("lz-lienzo");
    lienzo.addEventListener("dragover", (ev) => { if (puedeEditar()) { ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; } });
    lienzo.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const t = (ev.dataTransfer && ev.dataTransfer.getData("text/plain")) || "";
      if (!t.startsWith("lz:")) return;
      poner(Number(t.slice(3)), aLienzo(ev.clientX, ev.clientY));
    });
    $("lz-cable-form").addEventListener("submit", crearCable);
    $("lz-cable-cancelar").addEventListener("click", () => { $("modal-lz-cable").hidden = true; });
    // what the mufa editor changed (cables, hilos) shows when it is closed
    new MutationObserver(() => { if ($("modal-mufa").hidden && !$("modal-lz").hidden && st.proyectoId) cargar(st.proyectoId, true); })
      .observe($("modal-mufa"), { attributes: true, attributeFilter: ["hidden"] });
    document.addEventListener("keydown", (e) => {
      if ($("modal-lz").hidden) return;
      const encima = ["modal-mufa", "modal-confirmar", "modal-lz-cable", "modal-lz-nombre", "modal-lz-fuente", "modal-lz-kmz"].some((id) => $(id) && !$(id).hidden);
      if (e.key === "Escape" && !encima) { e.stopPropagation(); if (st.modo === "cable") modoCable(false); else cerrar(); return; }
      if (encima || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || ""))) return;
      if (e.key === "Delete" || e.key === "Supr") { if (st.seleccion && st.seleccion.tipo === "cable") eliminarCable(); else quitarSeleccion(); }
    }, true);
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.Esquema = { abrir, cerrar, nuevoEsquema, renombrarEsquema, _posicionReal: posicionReal, _libre: libre, _st: st, _poner: poner };
})();
