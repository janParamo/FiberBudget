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
 *   - «Conectar hilos…» (con una caja elegida) o «Hilos en el origen / destino» (con un cable elegido): conexión hilo con hilo entre dos cables de una mufa (fusion_hilos.js).
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
  const ANCHO = 132, ALTO = 44, FRANJA = 34;                  // the box: a white card with a strip of the colour of its kind and its symbol
  // The symbol of each kind (24 x 24, drawn in white over the strip): a splice closure, a splitter, a terminal box, a coil of spare cable, a node (equipment) and an ODF (panel).
  const SIMBOLO = {
    empalme: "M2 12h3M19 12h3M7 8h10a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2zM9.5 8v8M14.5 8v8",
    distribucion: "M2 12h7M9 12l8-6M9 12h8M9 12l8 6M17 6h4M17 12h4M17 18h4",
    terminal: "M2 12h5M7 6h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H7zM11.5 10v4M15.5 10v4",
    reserva: "M2 17h6M12 19a7 7 0 1 1 7-7M12 15.5a3.5 3.5 0 1 1 3.5-3.5M19 12v5h3",
    nodo: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01M12 7h4M12 17h4M12 10v4",
    odf: "M4 4h16v16H4zM4 9.3h16M4 14.7h16M8 6.7h.01M12 6.7h.01M16 6.7h.01M8 12h.01M12 12h.01M16 12h.01M8 17.3h.01M12 17.3h.01M16 17.3h.01",
  };
  const simboloDe = (e) => SIMBOLO[e.tipo === "mufa" ? (e.subtipo || "empalme") : e.tipo] || SIMBOLO.empalme;
  const ICONOS_BARRA = {                                      // the icons of the buttons of the window (put when it is connected)
    "lz-nuevo": "M12 5v14M5 12h14", "lz-renombrar": "M4 20h4L19 9l-4-4L4 16zM13 7l4 4", "lz-borrar": "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
    "lz-exportar": "M12 3v12M8 11l4 4 4-4M4 17v3h16v-3", "lz-recargar": "M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7",
    "lz-kmz": "M12 21s-6-5.3-6-10a6 6 0 1 1 12 0c0 4.7-6 10-6 10zM12 13a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "lz-validar-todo": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM8 12l3 3 5-6",
    "lz-fuente": "M13 3 5 13h6l-1 8 8-10h-6z", "lz-conectar": "M7 12h10M5 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM23 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0z",
    "lz-renombrar-mufa": "M4 20h4L19 9l-4-4L4 16zM13 7l4 4", "lz-quitar": "M4 4h16v16H4zM8 12h8", "lz-eliminar-cable": "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
    "lz-hilos": "M3 6h5l8 12h5M3 18h5l8-12h5", "lz-geo": "M12 2v4M12 18v4M2 12h4M18 12h4M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "lz-deshacer": "M8 7 4 11l4 4M4 11h11a5 5 0 0 1 0 10h-3", "lz-rehacer": "M16 7l4 4-4 4M20 11H9a5 5 0 0 0 0 10h3",
  };
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
               guardando: Promise.resolve(), conectado: false, referenciaPendiente: false, distribucion: LEE_PREF("lz.distribucion") === "real" ? "real" : "compacta", cacheCompacta: null,
               multi: new Set(), deshacer: [], rehacer: [], arrastre: null, cablesRectos: LEE_PREF("lz.cables") === "rectos", minimapa: LEE_PREF("lz.minimapa") !== "0", mini: null, miniFijo: false, banda: 0 };
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
    if (proyectoId !== st.proyectoId || (r.lienzo ? r.lienzo.id : null) !== st.lienzoId) { st.deshacer = []; st.rehacer = []; }      // another schema: its own history
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
    st.multi = new Set([...st.multi].filter((id) => st.pos.has(id)));
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
    recordar();
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
    st.stage.on("xChange yChange scaleXChange", programarVista);       // the grid and the zoom figure follow whatever moves or zooms the canvas
    st.stage.on("mousemove", moverTip);
    st.stage.on("mouseleave dragstart", () => tip(null));
    st.stage.on("click tap", (e) => { if (e.target === st.stage && Date.now() - st.banda > 300) { seleccionar(null); if (st.modo === "cable") st.origen = null, resaltarOrigen(); } });
    new ResizeObserver(() => { if (caja.clientWidth) st.stage.size({ width: caja.clientWidth, height: caja.clientHeight }); }).observe(caja);
  }

  // ------------------------------------------------------------------ the view: squared paper, zoom figure, legend and the label under the pointer
  let vistaPendiente = 0;
  function programarVista() { if (!vistaPendiente) vistaPendiente = requestAnimationFrame(() => { vistaPendiente = 0; vista(); }); }

  /** The squared paper moves and grows with the canvas (24 px cells; too small to tell apart, they become 5 times bigger) and the zoom figure is put. */
  function vista() {
    if (!st.stage) return;
    const k = st.stage.scaleX(), caja = $("lz-lienzo");
    let celda = 24 * k;
    while (celda < 9) celda *= 5;
    caja.style.setProperty("--lz-c", `${celda}px`);
    caja.style.setProperty("--lz-x", `${st.stage.x()}px`);
    caja.style.setProperty("--lz-y", `${st.stage.y()}px`);
    $("lz-zoom").textContent = `${k >= 0.1 ? Math.round(k * 100) : (k * 100).toFixed(1)} %`;
    minimapa();
  }

  /** The overview: the whole schema small (boxes, cables) and the part that is on screen as a frame. A click or a drag over it goes there. */
  function minimapa() {
    const c = $("lz-mini");
    c.hidden = !st.minimapa || st.pos.size < 2;
    if (c.hidden) return;
    const k = st.stage.scaleX(), W = c.width, H = c.height, m = 8;
    const v = { x: -st.stage.x() / k, y: -st.stage.y() / k, w: st.stage.width() / k, h: st.stage.height() / k };
    if (!st.miniFijo || !st.mini) {                                // (while it is dragged the scale stays: it would move under the pointer)
      let x0 = v.x, y0 = v.y, x1 = v.x + v.w, y1 = v.y + v.h;
      st.pos.forEach((p) => { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + ANCHO); y1 = Math.max(y1, p.y + ALTO); });
      const e = Math.min((W - 2 * m) / (x1 - x0 || 1), (H - 2 * m) / (y1 - y0 || 1));
      st.mini = { e, ox: m - x0 * e + (W - 2 * m - (x1 - x0) * e) / 2, oy: m - y0 * e + (H - 2 * m - (y1 - y0) * e) / 2 };
    }
    const { e, ox, oy } = st.mini, ctx = c.getContext("2d");
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
    ctx.lineWidth = 1;
    st.lineas.forEach((l) => {
      const a = centro(l.c.origen_id), b = centro(l.c.destino_id);
      ctx.strokeStyle = l.color; ctx.globalAlpha = 0.7; ctx.beginPath(); ctx.moveTo(ox + a.x * e, oy + a.y * e); ctx.lineTo(ox + b.x * e, oy + b.y * e); ctx.stroke();
    });
    ctx.globalAlpha = 1;
    st.pos.forEach((p, id) => {
      const el = st.elementos.get(id);
      ctx.fillStyle = el ? colorDe(el) : "#888";
      ctx.fillRect(ox + p.x * e, oy + p.y * e, Math.max(3, ANCHO * e), Math.max(2, ALTO * e));
    });
    ctx.fillStyle = "rgba(37, 99, 235, .10)"; ctx.strokeStyle = "#2563eb"; ctx.lineWidth = 1.5;
    ctx.fillRect(ox + v.x * e, oy + v.y * e, v.w * e, v.h * e); ctx.strokeRect(ox + v.x * e, oy + v.y * e, v.w * e, v.h * e);
  }

  function irDesdeMini(ev) {
    const r = $("lz-mini").getBoundingClientRect(), k = st.stage.scaleX();
    const x = (ev.clientX - r.left - st.mini.ox) / st.mini.e, y = (ev.clientY - r.top - st.mini.oy) / st.mini.e;
    st.stage.position({ x: st.stage.width() / 2 - x * k, y: st.stage.height() / 2 - y * k });
  }

  // ------------------------------------------------------------------ cables: at right angles or straight
  /** The points of the line of a cable between the centres of its two boxes: straight, or with right angles (it leaves along the longer side). */
  function puntosCable(a, b) {
    if (st.cablesRectos || Math.abs(a.x - b.x) < 1 || Math.abs(a.y - b.y) < 1) return [a.x, a.y, b.x, b.y];
    if (Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)) { const mx = (a.x + b.x) / 2; return [a.x, a.y, mx, a.y, mx, b.y, b.x, b.y]; }
    const my = (a.y + b.y) / 2;
    return [a.x, a.y, a.x, my, b.x, my, b.x, b.y];
  }

  // ------------------------------------------------------------------ several boxes at once, and undo / redo
  /** The boxes that are chosen (one or several). */
  const elegidas = () => (st.multi.size ? [...st.multi] : st.seleccion && st.seleccion.tipo === "caja" ? [st.seleccion.id] : []);

  function elegirCajas(ids) {
    if (ids.length <= 1) { seleccionar(ids.length ? { tipo: "caja", id: ids[0] } : null); return; }
    st.multi = new Set(ids); st.seleccion = null;
    resaltar(); info();
  }

  const fotoDe = () => new Map([...st.pos].map(([id, p]) => [id, { x: p.x, y: p.y }]));

  /** Keeps how the boxes are now, before something moves, puts or takes them: Ctrl+Z comes back here. (Cables are not part of it: they are of the network.) */
  function recordar() {
    st.deshacer.push(fotoDe());
    if (st.deshacer.length > 60) st.deshacer.shift();
    st.rehacer = [];
    botonesHistoria();
  }

  function botonesHistoria() {
    $("lz-deshacer").disabled = !st.deshacer.length || !puedeEditar();
    $("lz-rehacer").disabled = !st.rehacer.length || !puedeEditar();
  }

  function volverA(de, hacia) {
    if (!de.length || !puedeEditar()) return;
    hacia.push(fotoDe());
    const foto = de.pop();
    st.pos.forEach((p, id) => { if (!foto.has(id)) { st.quitar.add(id); st.pendientes.delete(id); } });
    const nueva = new Map();
    foto.forEach((p, id) => {
      if (!st.elementos.has(id)) return;
      const q = st.pos.get(id);
      if (!q || q.x !== p.x || q.y !== p.y) { st.pendientes.add(id); st.quitar.delete(id); }
      nueva.set(id, p);
    });
    st.pos = nueva;
    st.multi = new Set([...st.multi].filter((id) => nueva.has(id)));
    if (st.seleccion && st.seleccion.tipo === "caja" && !nueva.has(st.seleccion.id)) st.seleccion = null;
    dibujar(); pintarLista(); info(); botonesHistoria();
    programarGuardado();
  }
  const deshacer = () => volverA(st.deshacer, st.rehacer), rehacer = () => volverA(st.rehacer, st.deshacer);

  /** Lines the chosen boxes up (izq, cx, der, arr, cy, aba) or spreads them evenly (dh, dv: three or more). */
  function alinear(modo) {
    const ids = [...st.multi];
    if (ids.length < 2 || !puedeEditar()) return;
    const ps = ids.map((id) => ({ id, ...st.pos.get(id) }));
    const x0 = Math.min(...ps.map((p) => p.x)), x1 = Math.max(...ps.map((p) => p.x)), y0 = Math.min(...ps.map((p) => p.y)), y1 = Math.max(...ps.map((p) => p.y));
    if ((modo === "dh" || modo === "dv") && ids.length < 3) { mensaje("Para repartir hacen falta tres cajas o más", "error"); return; }
    recordar();
    if (modo === "dh") ps.sort((a, b) => a.x - b.x).forEach((p, i) => { p.x = x0 + ((x1 - x0) * i) / (ps.length - 1); });
    else if (modo === "dv") ps.sort((a, b) => a.y - b.y).forEach((p, i) => { p.y = y0 + ((y1 - y0) * i) / (ps.length - 1); });
    else ps.forEach((p) => {
      if (modo === "izq") p.x = x0; else if (modo === "der") p.x = x1; else if (modo === "cx") p.x = (x0 + x1) / 2;
      else if (modo === "arr") p.y = y0; else if (modo === "aba") p.y = y1; else if (modo === "cy") p.y = (y0 + y1) / 2;
    });
    ps.forEach((p) => { st.pos.set(p.id, redondear({ x: p.x, y: p.y })); st.pendientes.add(p.id); st.quitar.delete(p.id); });
    dibujar(); info();
    programarGuardado();
  }

  /** Mayús + drag over the empty canvas: a frame; the boxes it touches are chosen. */
  function empezarBanda(ev) {
    if (!ev.shiftKey || ev.button !== 0 || !st.stage || st.modo === "cable") return;
    st.stage.setPointersPositions(ev);
    const p0 = st.stage.getPointerPosition();
    if (!p0 || st.stage.getIntersection(p0)) return;             // over a box or a cable: its own click
    ev.preventDefault();
    st.stage.draggable(false);
    const banda = $("lz-banda"), caja = $("lz-konva").getBoundingClientRect();
    let r = null;
    const mover = (e) => {
      const x = e.clientX - caja.left, y = e.clientY - caja.top;
      r = { x: Math.min(p0.x, x), y: Math.min(p0.y, y), w: Math.abs(x - p0.x), h: Math.abs(y - p0.y) };
      banda.hidden = false;
      banda.style.cssText = `transform:translate(${r.x}px,${r.y}px);width:${r.w}px;height:${r.h}px`;
    };
    const soltar = () => {
      window.removeEventListener("mousemove", mover); window.removeEventListener("mouseup", soltar);
      banda.hidden = true;
      st.stage.draggable(true);
      st.banda = Date.now();
      if (!r || (r.w < 4 && r.h < 4)) return;
      const k = st.stage.scaleX(), a = { x: (r.x - st.stage.x()) / k, y: (r.y - st.stage.y()) / k, w: r.w / k, h: r.h / k };
      elegirCajas([...st.pos].filter(([, p]) => p.x < a.x + a.w && p.x + ANCHO > a.x && p.y < a.y + a.h && p.y + ALTO > a.y).map(([id]) => id));
    };
    window.addEventListener("mousemove", mover); window.addEventListener("mouseup", soltar);
  }

  // ------------------------------------------------------------------ export: the whole schema as an image or a PDF
  async function exportar(tipo) {
    if (!st.cajas.size) { mensaje("El esquema está vacío: no hay qué exportar", "error"); return; }
    if (!Redes.api || !Redes.api.guardar_imagen) { mensaje("Exportar no está disponible aquí", "error"); return; }
    mensaje("Preparando la imagen…", "cargando");
    const antes = { s: st.stage.scaleX(), x: st.stage.x(), y: st.stage.y(), sel: st.seleccion, multi: st.multi };
    st.seleccion = null; st.multi = new Set(); resaltar();
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    st.pos.forEach((p) => { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + ANCHO); y1 = Math.max(y1, p.y + ALTO); });
    const m = 48, ancho = x1 - x0 + 2 * m, alto = y1 - y0 + 2 * m, f = Math.max(0.05, Math.min(2, 7000 / Math.max(ancho, alto)));
    st.stage.scale({ x: 1, y: 1 }); st.stage.position({ x: m - x0, y: m - y0 });
    let dibujo;
    try { dibujo = st.stage.toCanvas({ x: 0, y: 0, width: ancho, height: alto, pixelRatio: f }); }
    finally {
      st.stage.scale({ x: antes.s, y: antes.s }); st.stage.position({ x: antes.x, y: antes.y });
      st.seleccion = antes.sel; st.multi = antes.multi; resaltar();
    }
    const z = st.datos.proyecto, nombre = `${st.datos.lienzo ? st.datos.lienzo.nombre : "Esquema"} - ${z.zona || z.nombre}`;
    const hoja = document.createElement("canvas"), u = Math.max(1, dibujo.width / 1400), cab = Math.round(54 * u);
    hoja.width = dibujo.width; hoja.height = dibujo.height + cab;
    const ctx = hoja.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, hoja.width, hoja.height);
    ctx.fillStyle = "#1a2130"; ctx.font = `600 ${Math.round(20 * u)}px "Segoe UI", sans-serif`; ctx.textBaseline = "middle";
    ctx.fillText(nombre, Math.round(24 * u), cab / 2);
    ctx.fillStyle = "#6b7487"; ctx.font = `${Math.round(12 * u)}px "Segoe UI", sans-serif`; ctx.textAlign = "right";
    ctx.fillText(`${st.pos.size} cajas · ${st.lineas.size} cables · ${new Date().toLocaleDateString("es-NI")}`, hoja.width - Math.round(24 * u), cab / 2);
    ctx.fillStyle = "#e1e6ee"; ctx.fillRect(0, cab - 1, hoja.width, Math.max(1, Math.round(u)));
    ctx.drawImage(dibujo, 0, cab);
    const r = await Redes.api.guardar_imagen(nombre, hoja.toDataURL("image/png"), tipo);
    if (r && r.ok) mensaje(`Esquema guardado en ${r.ruta}`, "ok"); else if (r && r.cancelado) mensaje(""); else mensaje((r && r.error) || "No se pudo exportar", "error");
  }

  /** Zooms by `factor` (or to `fijo`) keeping the centre of the canvas where it is. */
  function zoom(factor, fijo) {
    const viejo = st.stage.scaleX(), nuevo = Math.max(ZOOM_MIN, Math.min(3, fijo || viejo * factor));
    const cx = st.stage.width() / 2, cy = st.stage.height() / 2;
    const punto = { x: (cx - st.stage.x()) / viejo, y: (cy - st.stage.y()) / viejo };
    st.stage.scale({ x: nuevo, y: nuevo });
    st.stage.position({ x: cx - punto.x * nuevo, y: cy - punto.y * nuevo });
  }

  /** What the colours mean: the kinds of box and the cables (by hilos) that are in the schema, with how many. */
  function leyenda() {
    const tipos = new Map(), cables = new Map();
    st.pos.forEach((p, id) => { const e = st.elementos.get(id); if (!e) return; const t = etiquetaTipo(e); tipos.set(t, { color: colorDe(e), n: ((tipos.get(t) || {}).n || 0) + 1 }); });
    st.lineas.forEach((l) => { const t = l.c.hilos ? `${l.c.hilos} hilos` : "Sin hilos"; cables.set(t, { color: l.color, n: ((cables.get(t) || {}).n || 0) + 1, orden: l.c.hilos || 0 }); });
    const fila = (cls) => ([t, v]) => `<div class="lz-ley"><i class="${cls}" style="background:${esc(v.color)}"></i>${esc(t)}<span>${v.n}</span></div>`;
    $("lz-leyenda").innerHTML = (tipos.size ? `<h4>Cajas</h4>${[...tipos].map(fila("")).join("")}` : "")
      + (cables.size ? `<h4>Cables</h4>${[...cables].sort((a, b) => b[1].orden - a[1].orden).map(fila("cable")).join("")}` : "");
    $("lz-leyenda").hidden = !tipos.size;
  }

  /** The label under the pointer: the name of a box (when the zoom leaves it too small to read) or what a cable is. null hides it. */
  function tip(html) {
    const t = $("lz-tip");
    t.hidden = !html;
    if (html) { t.innerHTML = html; moverTip(); }
  }
  function moverTip() {
    const t = $("lz-tip"), p = st.stage.getPointerPosition();
    if (t.hidden || !p) return;
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.transform = `translate(${Math.max(4, Math.min(st.stage.width() - w - 4, p.x + 14))}px, ${p.y + 18 + h > st.stage.height() ? p.y - h - 10 : p.y + 18}px)`;
  }
  const tipCaja = (e) => {
    if (st.stage.scaleX() >= 0.7) return null;                              // big enough: the name is read on the box
    const n = st.cables.filter((c) => c.origen_id === e.id || c.destino_id === e.id).length;
    return `<b>${esc(e.nombre)}</b><small>${esc(etiquetaTipo(e))} · ${n} cable(s)</small>`;
  };
  const tipCable = (c) => {
    const o = st.elementos.get(c.origen_id), d = st.elementos.get(c.destino_id);
    return `<b>${esc(c.nombre)}</b><small>${esc(o ? o.nombre : "?")} → ${esc(d ? d.nombre : "?")} · ${c.hilos || "?"} hilos · ${Math.round(c.longitud_m || 0).toLocaleString("es-NI")} m</small>`;
  };

  function dibujar() {
    if (!st.stage) return;
    tip(null);
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
    leyenda();
    vista();
  }

  function crearCaja(e, p) {
    const g = new Konva.Group({ x: p.x, y: p.y, draggable: puedeEditar() && st.modo !== "cable", name: "caja" });
    // A white card with the strip of its kind and its symbol (closure, splitter, terminal box, coil, node, ODF); a node is a pill, an ODF has square corners.
    const color = colorDe(e), radio = e.tipo === "nodo" ? ALTO / 2 : e.tipo === "odf" ? 3 : 10, cables = st.cables.filter((c) => c.origen_id === e.id || c.destino_id === e.id).length;
    g.setAttr("colorBase", color);
    g.add(new Konva.Rect({ width: ANCHO, height: ALTO, cornerRadius: radio, fill: "#fff", stroke: color, strokeWidth: 1.5, shadowColor: "#101828", shadowBlur: 10, shadowOpacity: 0.2, shadowOffsetY: 3, name: "marco" }));
    g.add(new Konva.Rect({ x: 0.75, y: 0.75, width: FRANJA, height: ALTO - 1.5, cornerRadius: [radio, 0, 0, radio], fill: color, listening: false }));
    g.add(new Konva.Path({ x: (FRANJA - 20) / 2 + (e.tipo === "nodo" ? 3 : 1), y: (ALTO - 20) / 2, scaleX: 20 / 24, scaleY: 20 / 24, data: simboloDe(e), stroke: "#fff", strokeWidth: 1.9, lineCap: "round", lineJoin: "round", listening: false }));
    if (e.tipo !== "mufa") g.add(new Konva.Text({ x: 0, y: -15, width: ANCHO, text: "⚡ Fuente de la red", fontSize: 10, fontStyle: "bold", fill: "#b45309", align: "center", listening: false }));
    g.add(new Konva.Text({ x: FRANJA + 7, y: 3, width: ANCHO - FRANJA - 13, height: ALTO - 6, text: e.nombre, fontSize: 11, fontStyle: "bold", fill: "#1a2130", lineHeight: 1.15, verticalAlign: "middle", ellipsis: true, wrap: "word", listening: false }));
    if (cables) {                                              // how many cables reach it, on its corner
      const n = String(cables), w = n.length > 1 ? 20 : 16;
      g.add(new Konva.Rect({ x: ANCHO - w + 5, y: -7, width: w, height: 16, cornerRadius: 8, fill: "#1a2130", stroke: "#fff", strokeWidth: 1.5, listening: false }));
      g.add(new Konva.Text({ x: ANCHO - w + 5, y: -7, width: w, height: 16, text: n, fontSize: 10, fontStyle: "bold", fill: "#fff", align: "center", verticalAlign: "middle", listening: false }));
    }
    g.on("dragstart", () => {
      tip(null); recordar();
      st.arrastre = st.multi.size > 1 && st.multi.has(e.id) ? { x: g.x(), y: g.y(), otros: [...st.multi].filter((id) => id !== e.id).map((id) => ({ id, ...st.pos.get(id) })) } : null;
    });
    g.on("dragmove", () => {
      st.pos.set(e.id, { x: g.x(), y: g.y() }); moverLineas(e.id);
      if (st.arrastre) st.arrastre.otros.forEach((o) => {        // the other chosen boxes go with it
        const p = { x: o.x + g.x() - st.arrastre.x, y: o.y + g.y() - st.arrastre.y }, otra = st.cajas.get(o.id);
        st.pos.set(o.id, p); if (otra) otra.position(p); moverLineas(o.id);
      });
      programarVista();
    });
    g.on("dragend", () => {
      st.pos.set(e.id, { x: g.x(), y: g.y() });
      [e.id, ...(st.arrastre ? st.arrastre.otros.map((o) => o.id) : [])].forEach((id) => { st.pos.set(id, redondear(st.pos.get(id))); st.pendientes.add(id); st.quitar.delete(id); });
      st.arrastre = null;
      programarGuardado();
    });
    g.on("click tap", (ev) => { ev.cancelBubble = true; clicCaja(e, ev.evt); });
    g.on("dblclick dbltap", (ev) => { ev.cancelBubble = true; entrar(e); });
    g.on("mouseenter", () => { st.stage.container().style.cursor = st.modo === "cable" ? "crosshair" : "pointer"; tip(tipCaja(e)); });
    g.on("mouseleave", () => { st.stage.container().style.cursor = "default"; tip(null); });
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
    const linea = new Konva.Line({ points: puntosCable(a, b), lineJoin: "round", stroke: color, strokeWidth: Math.max(2, Math.min(7, Math.round((c.hilos || 12) / 24) + 2)), lineCap: "round", hitStrokeWidth: 14, name: "trazo" });
    const rotulo = new Konva.Label({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, listening: false });
    rotulo.add(new Konva.Tag({ fill: "#ffffff", stroke: color, cornerRadius: 4, pointerDirection: "none" }));
    rotulo.add(new Konva.Text({ text: `${c.hilos ? c.hilos + " h" : "? h"}${c.conectados ? ` · ${c.conectados}↔` : ""}`, fontSize: 11, padding: 3, fill: "#222" }));
    rotulo.offsetX(rotulo.width() / 2); rotulo.offsetY(rotulo.height() / 2);
    g.add(linea, rotulo);
    g.on("click tap", (ev) => { ev.cancelBubble = true; seleccionar({ tipo: "cable", id: c.id }); });
    g.on("mouseenter", () => { st.stage.container().style.cursor = "pointer"; tip(tipCable(c)); });
    g.on("mouseleave", () => { st.stage.container().style.cursor = "default"; tip(null); });
    st.capaLineas.add(g);
    st.lineas.set(c.id, { g, linea, rotulo, color, c });
  }

  function moverLineas(id) {
    st.lineas.forEach((l) => {
      if (l.c.origen_id !== id && l.c.destino_id !== id) return;
      const a = centro(l.c.origen_id), b = centro(l.c.destino_id);
      l.linea.points(puntosCable(a, b));
      l.rotulo.position({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    });
    st.capaLineas.batchDraw();
  }

  function resaltar() {
    st.cajas.forEach((g, id) => {
      const marco = g.findOne(".marco");
      const sel = (st.seleccion && st.seleccion.tipo === "caja" && st.seleccion.id === id) || st.multi.has(id);
      const origen = st.modo === "cable" && st.origen === id;
      marco.stroke(origen ? "#00c853" : sel ? "#1f6feb" : g.getAttr("colorBase")); marco.strokeWidth(origen || sel ? 3.5 : 1.5);
      marco.shadowColor(sel ? "#1f6feb" : "#101828"); marco.shadowOpacity(sel ? 0.45 : 0.2);
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
    st.multi.clear();
    resaltar();
    info();
  }

  function info() {
    const s = st.seleccion, caja = $("lz-info"), varias = st.multi.size > 1;
    $("lz-alinear").hidden = !varias || !puedeEditar();
    caja.hidden = !$("lz-alinear").hidden;                     // the bar of the chosen boxes takes its place
    $("lz-alinear-n").textContent = `${st.multi.size} cajas`;
    botonesHistoria();
    $("lz-quitar").disabled = !((varias || (s && s.tipo === "caja")) && puedeEditar());
    $("lz-renombrar-mufa").disabled = !(s && s.tipo === "caja" && puedeEditar());
    $("lz-eliminar-cable").disabled = !(s && s.tipo === "cable" && puedeEditar());
    $("lz-abrir-a").hidden = $("lz-abrir-b").hidden = !(s && s.tipo === "cable");
    $("lz-hilos").hidden = !(s && s.tipo === "caja");
    $("lz-hilos-a").hidden = $("lz-hilos-b").hidden = !(s && s.tipo === "cable");
    if (varias) { caja.innerHTML = `<b>${st.multi.size} cajas elegidas</b> · arrástrelas juntas, alinéelas o quítelas del esquema (Supr)`; return; }
    if (!s) {
      caja.textContent = st.modo === "cable" ? (st.origen ? "Clic en la caja donde termina el cable" : "Clic en la caja donde empieza el cable") : "Seleccione una caja o un cable · doble clic en una caja abre su editor de mufa";
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
    $("lz-hilos-a").textContent = `Hilos en ${o ? o.nombre : "el origen"}`; $("lz-hilos-b").textContent = `Hilos en ${d ? d.nombre : "el destino"}`;
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
    recordar();
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
    const ids = elegidas();
    if (!ids.length || !puedeEditar()) return;
    recordar();
    ids.forEach((id) => { st.pos.delete(id); st.pendientes.delete(id); st.quitar.add(id); });
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
  function clicCaja(e, evt) {
    if (st.modo !== "cable") {
      if (evt && (evt.ctrlKey || evt.shiftKey || evt.metaKey)) {             // Ctrl / Mayús + click: adds it to (or takes it from) what is chosen
        const ids = new Set(elegidas());
        if (ids.has(e.id)) ids.delete(e.id); else ids.add(e.id);
        elegirCajas([...ids]);
      } else seleccionar({ tipo: "caja", id: e.id });
      return;
    }
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

  async function validarTodo() {
    if (!puedeEditar()) return;
    const pendientes = st.datos.elementos.filter((e) => e.tipo === "mufa" && e.estado_migracion && e.estado_migracion !== "validada").length;
    if (!pendientes) { mensaje("Todas las mufas de la zona ya están validadas", "ok"); return; }
    if (!(await Redes.confirmar(`¿Marcar como validadas las ${pendientes} mufa(s) de la zona que faltan? Su contenido queda como verificado y una reimportación del Visio no lo cambiará.`, "Validar todo"))) return;
    mensaje("Validando…", "cargando");
    const r = await Redes.llamar("validar_zona", { proyecto_id: st.proyectoId });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    await cargar(st.proyectoId, true);
    mensaje(`${r.validadas} mufa(s) validada(s)`, "ok");
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

  /** Changes the name of the chosen box (the mufa was named when it was created from the KMZ; the KMZ may call it something else now). */
  async function renombrarCaja() {
    const s = st.seleccion;
    if (!puedeEditar() || !s || s.tipo !== "caja") return;
    const e = st.elementos.get(s.id);
    const nombre = await pedirNombre("Nombre de la mufa", e.nombre);
    if (!nombre || nombre === e.nombre) return;
    const r = await Redes.llamar("renombrar_elemento_zona", { proyecto_id: st.proyectoId, elemento_id: e.id, nombre });
    if (!r.ok) { mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); return; }
    await cargar(st.proyectoId, true);
    if (st.pos.has(e.id)) seleccionar({ tipo: "caja", id: e.id });
    mensaje(`Ahora se llama «${r.elemento.nombre}»`, "ok");
  }

  // ------------------------------------------------------------------ las mufas del KMZ que la zona no tiene (nuevas o renombradas)
  async function abrirMufasKmz() {
    if (!st.proyectoId) return;
    mensaje("Leyendo las mufas del KMZ…", "cargando");
    const r = await Redes.llamar("mufas_kmz_zona", { proyecto_id: st.proyectoId });
    if (!r.ok) { mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); return; }
    mensaje("");
    st.kmzNuevas = r.nuevas;
    st.kmzNombres = r.nombres_cambiados || [];
    $("lz-kmz-titulo").textContent = `Mufas del KMZ que faltan en ${st.datos.proyecto.zona || st.datos.proyecto.nombre}`;
    $("lz-kmz-resumen").textContent = r.nuevas.length
      ? `${r.nuevas.length} mufa(s) del KMZ no están en la zona (la zona tiene ${r.en_zona}; el KMZ, ${r.en_kmz} alrededor). Marque las que quiere agregar al esquema.`
      : st.kmzNombres.length ? "" : `La zona está al día con el KMZ: ${r.en_zona} elementos en la zona, ${r.en_kmz} puntos del KMZ alrededor.`;
    $("lz-kmz-nombres").hidden = !st.kmzNombres.length;
    $("lz-kmz-nombres-lista").innerHTML = st.kmzNombres.map((n, i) => `<tr data-nombre="${esc(`${n.nombre} ${n.nombre_kmz}`.toLowerCase())}"><td><input type="checkbox" data-lz-kmz-sel data-lz-kmz-nom="${i}" aria-label="Renombrar ${esc(n.nombre)}" ${puedeEditar() ? "checked" : "disabled"}></td>
      <td>${esc(n.nombre)}</td><td><b>${esc(n.nombre_kmz)}</b></td></tr>`).join("");
    $("lz-kmz-filtro").value = "";
    $("lz-kmz-lista").innerHTML = r.nuevas.map((n, i) => `<tr data-i="${i}" data-nombre="${esc(n.nombre.toLowerCase())}"><td><input type="checkbox" data-lz-kmz-sel="${i}" aria-label="Agregar ${esc(n.nombre)}" ${puedeEditar() ? "checked" : "disabled"}></td>
      <td><b>${esc(n.nombre)}</b><div class="nota">${n.categoria === "reserva" ? "Reserva" : n.categoria === "nodo" ? "Nodo" : "Mufa"} · ${n.lat.toFixed(6)}, ${n.lon.toFixed(6)}</div></td>
      <td><select data-lz-kmz="${i}" ${puedeEditar() ? "" : "disabled"}>
        ${n.cercana ? `<option value="renombrar" selected>Es «${esc(n.cercana.nombre)}» renombrada (a ${Math.round(n.cercana.distancia_m)} m)</option><option value="agregar">Agregar como mufa nueva</option>` : `<option value="agregar" selected>Agregar como mufa nueva</option>`}
        </select></td></tr>`).join("");
    $("lz-kmz-aplicar").hidden = !(r.nuevas.length || st.kmzNombres.length) || !puedeEditar();
    $("modal-lz-kmz").hidden = false;
    contarMarcadas();
  }

  /** The rows that pass the filter (all of them when it is empty). */
  const filasKmzVisibles = () => [...document.querySelectorAll("#lz-kmz-lista tr, #lz-kmz-nombres-lista tr")].filter((tr) => !tr.hidden);
  function contarMarcadas() {
    const marcadas = document.querySelectorAll("#modal-lz-kmz input[data-lz-kmz-sel]:checked").length, total = st.kmzNuevas.length + (st.kmzNombres || []).length;
    $("lz-kmz-marcadas").textContent = total ? `${marcadas} de ${total} marcada(s)` : "";
    $("lz-kmz-aplicar").textContent = marcadas ? `Aplicar (${marcadas})` : "Aplicar";
    $("lz-kmz-aplicar").disabled = !marcadas;
  }
  function marcarKmz(valor) {
    filasKmzVisibles().forEach((tr) => { const c = tr.querySelector("input[data-lz-kmz-sel]"); if (c && !c.disabled) c.checked = valor; });
    contarMarcadas();
  }

  async function aplicarMufasKmz() {
    const acciones = [];
    document.querySelectorAll("#lz-kmz-lista select[data-lz-kmz]").forEach((s) => {
      if (!s.closest("tr").querySelector("input[data-lz-kmz-sel]").checked) return;
      const n = st.kmzNuevas[Number(s.dataset.lzKmz)];
      if (s.value === "renombrar") acciones.push({ kmz_id: n.kmz_id, accion: "renombrar", elemento_id: n.cercana.id });
      else if (s.value === "agregar") acciones.push({ kmz_id: n.kmz_id, accion: "agregar" });
    });
    document.querySelectorAll("#lz-kmz-nombres-lista input[data-lz-kmz-nom]:checked").forEach((c) => {
      const n = st.kmzNombres[Number(c.dataset.lzKmzNom)];
      acciones.push({ accion: "actualizar_nombre", elemento_id: n.elemento_id, version: n.version });
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
    mensaje(`${r.agregadas} mufa(s) agregada(s), ${r.renombradas} renombrada(s)${r.nombres_actualizados ? `, ${r.nombres_actualizados} nombre(s) puesto(s) como en el KMZ` : ""}: ya están en la lista para arrastrarlas al esquema`, "ok");
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

  /** The list of a <select> inside the dialogs of the schema as a menu of the page: in the window of its own the native list is drawn blank. */
  function menuPropio(ev) {
    const sel = ev.target.closest && ev.target.closest("select");
    if (!sel || !sel.closest("#modal-lz-cable, #modal-lz-fuente, #modal-lz-kmz, #modal-fh") || sel.disabled || ev.button !== 0) return;
    ev.preventDefault();
    const previo = document.getElementById("lz-menu-select");
    if (previo) { previo.remove(); if (previo._sel === sel) return; }
    const r = sel.getBoundingClientRect(), menu = document.createElement("div");
    menu.id = "lz-menu-select"; menu._sel = sel; menu.setAttribute("role", "listbox");
    menu.style.cssText = `position:fixed;left:${r.left}px;top:${r.bottom}px;min-width:${r.width}px;max-height:${Math.max(120, Math.min(280, window.innerHeight - r.bottom - 8))}px`;
    [...sel.options].forEach((o, i) => {
      const it = document.createElement("div");
      it.textContent = o.textContent; it.setAttribute("role", "option");
      it.className = `lz-menu-op${i === sel.selectedIndex ? " actual" : ""}${o.disabled ? " apagado" : ""}`;
      if (!o.disabled) it.addEventListener("mousedown", (e) => {
        e.preventDefault(); e.stopPropagation();
        const cambio = sel.selectedIndex !== i;
        sel.selectedIndex = i; menu.remove();
        if (cambio) sel.dispatchEvent(new Event("change", { bubbles: true }));
        sel.focus();
      });
      menu.appendChild(it);
    });
    document.body.appendChild(menu);
    const actual = menu.querySelector(".actual"); if (actual) menu.scrollTop = actual.offsetTop - 40;
    sel.focus();
  }

  function conectar() {
    document.addEventListener("mousedown", menuPropio, true);
    document.addEventListener("mousedown", (e) => { const m = document.getElementById("lz-menu-select"); if (m && !m.contains(e.target) && !(e.target.closest && e.target.closest("select") === m._sel)) m.remove(); });
    document.addEventListener("keydown", (e) => { const m = document.getElementById("lz-menu-select"); if (m && e.key === "Escape") { e.stopPropagation(); m.remove(); } }, true);
    if (st.conectado || !$("modal-lz")) return;
    st.conectado = true;
    $("lz-cerrar").addEventListener("click", cerrar);
    $("lz-max").addEventListener("click", () => $("modal-lz").classList.toggle("maximizado"));
    $("lz-zona").addEventListener("change", async () => { await guardarPosiciones(); st.seleccion = null; st.origen = null; cargar(Number($("lz-zona").value)); });
    $("lz-esquema").addEventListener("change", async () => { await guardarPosiciones(); st.seleccion = null; st.origen = null; cargar(st.proyectoId, false, Number($("lz-esquema").value)); });
    $("lz-nuevo").addEventListener("click", nuevoEsquema);
    $("lz-kmz").addEventListener("click", abrirMufasKmz);
    $("lz-kmz-aplicar").addEventListener("click", aplicarMufasKmz);
    $("lz-kmz-todas").addEventListener("click", () => marcarKmz(true));
    $("lz-kmz-ninguna").addEventListener("click", () => marcarKmz(false));
    $("lz-kmz-lista").addEventListener("change", (e) => { if (e.target.matches("input[data-lz-kmz-sel]")) contarMarcadas(); });
    $("lz-kmz-filtro").addEventListener("input", (e) => {
      const t = e.target.value.trim().toLowerCase();
      document.querySelectorAll("#lz-kmz-lista tr, #lz-kmz-nombres-lista tr").forEach((tr) => { tr.hidden = !!t && !tr.dataset.nombre.includes(t); });
    });
    $("lz-kmz-cerrar").addEventListener("click", () => { $("modal-lz-kmz").hidden = true; $("lz-kmz-error").textContent = ""; });
    $("lz-validar-todo").addEventListener("click", validarTodo);
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
    $("lz-acercar").addEventListener("click", () => zoom(1.25));
    $("lz-alejar").addEventListener("click", () => zoom(1 / 1.25));
    $("lz-zoom").addEventListener("click", () => zoom(1, 1));
    $("lz-conectar").addEventListener("click", () => modoCable(st.modo !== "cable"));
    Object.entries(ICONOS_BARRA).forEach(([id, d]) => {
      const b = $(id);
      if (!b) return;
      b.classList.add("con-icono");
      if (["lz-renombrar", "lz-borrar", "lz-recargar"].includes(id)) { b.classList.add("solo-icono"); b.setAttribute("aria-label", b.textContent.trim()); }
      b.insertAdjacentHTML("afterbegin", `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`);
    });
    $("lz-deshacer").addEventListener("click", deshacer);
    $("lz-rehacer").addEventListener("click", rehacer);
    $("lz-alinear").addEventListener("click", (e) => { const b = e.target.closest("[data-lz-al]"); if (b) alinear(b.dataset.lzAl); });
    const pintarOpciones = () => {
      $("lz-cables").setAttribute("aria-pressed", st.cablesRectos ? "false" : "true");
      $("lz-mini-ver").setAttribute("aria-pressed", st.minimapa ? "true" : "false");
    };
    pintarOpciones();
    $("lz-cables").addEventListener("click", () => { st.cablesRectos = !st.cablesRectos; GUARDA_PREF("lz.cables", st.cablesRectos ? "rectos" : "angulo"); pintarOpciones(); dibujar(); });
    $("lz-mini-ver").addEventListener("click", () => { st.minimapa = !st.minimapa; GUARDA_PREF("lz.minimapa", st.minimapa ? "1" : "0"); pintarOpciones(); vista(); });
    $("lz-mini").addEventListener("mousedown", (e) => {
      e.preventDefault(); st.miniFijo = true; irDesdeMini(e);
      const fin = () => { st.miniFijo = false; window.removeEventListener("mousemove", irDesdeMini); window.removeEventListener("mouseup", fin); programarVista(); };
      window.addEventListener("mousemove", irDesdeMini); window.addEventListener("mouseup", fin);
    });
    $("lz-konva").addEventListener("mousedown", empezarBanda, true);
    const menuExp = (ver) => { $("lz-exp-menu").hidden = !ver; $("lz-exportar").setAttribute("aria-expanded", ver ? "true" : "false"); };
    $("lz-exportar").addEventListener("click", (e) => { e.stopPropagation(); menuExp($("lz-exp-menu").hidden); });
    $("lz-exp-menu").addEventListener("click", (e) => { const b = e.target.closest("[data-lz-exp]"); if (b) { menuExp(false); exportar(b.dataset.lzExp); } });
    document.addEventListener("click", () => { if (!$("lz-exp-menu").hidden) menuExp(false); });
    $("lz-quitar").addEventListener("click", quitarSeleccion);
    $("lz-renombrar-mufa").addEventListener("click", renombrarCaja);
    $("lz-eliminar-cable").addEventListener("click", eliminarCable);
    const abrirExtremo = (campo) => { const c = st.seleccion && st.seleccion.tipo === "cable" && st.cables.find((x) => x.id === st.seleccion.id); const e = c && st.elementos.get(c[campo]); if (e) entrar(e); };
    const hilosEn = (campo) => {                                          // hilo-to-hilo connections in the mufa at one end of the chosen cable
      const c = st.seleccion && st.seleccion.tipo === "cable" && st.cables.find((x) => x.id === st.seleccion.id);
      if (c && window.FusionHilos) { window.FusionHilos.alCerrar = () => cargar(st.proyectoId, true); window.FusionHilos.abrir(c[campo], { cableId: c.id }); }
    };
    $("lz-hilos-a").addEventListener("click", () => hilosEn("origen_id"));
    $("lz-hilos-b").addEventListener("click", () => hilosEn("destino_id"));
    $("lz-hilos").addEventListener("click", () => {
      const s = st.seleccion;
      if (s && s.tipo === "caja" && window.FusionHilos) { window.FusionHilos.alCerrar = () => cargar(st.proyectoId, true); window.FusionHilos.abrir(s.id); }
    });
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
      const encima = ["modal-mufa", "modal-confirmar", "modal-lz-cable", "modal-lz-nombre", "modal-lz-fuente", "modal-lz-kmz", "modal-fh"].some((id) => $(id) && !$(id).hidden);
      if (e.key === "Escape" && !encima) { e.stopPropagation(); if (st.modo === "cable") modoCable(false); else cerrar(); return; }
      if (encima || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || ""))) return;
      if (e.key === "F2") { e.preventDefault(); renombrarCaja(); return; }
      if ((e.ctrlKey || e.metaKey) && !e.altKey && /^[zy]$/i.test(e.key)) { e.preventDefault(); if (/y/i.test(e.key) || e.shiftKey) rehacer(); else deshacer(); return; }
      if ((e.ctrlKey || e.metaKey) && !e.altKey && /^a$/i.test(e.key)) { e.preventDefault(); elegirCajas([...st.pos.keys()]); return; }
      if (e.key === "Delete" || e.key === "Supr") { if (st.seleccion && st.seleccion.tipo === "cable") eliminarCable(); else quitarSeleccion(); }
    }, true);
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.Esquema = { abrir, cerrar, nuevoEsquema, renombrarEsquema, deshacer, rehacer, alinear, exportar, elegirCajas, _posicionReal: posicionReal, _libre: libre, _st: st, _poner: poner };
})();
