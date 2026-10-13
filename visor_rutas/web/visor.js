/* Visor de rutas – Fiber Budget.
 * Toda la lógica de negocio está en Python (visor_rutas/calculo.py), que se llama con
 * window.pywebview.api.calcular(texto). Este archivo solo dibuja y maneja la interfaz.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const MAX_HISTORIAL = 10;
  const IMAN_PX = 12;               // a measurement click this close to a route point or marker snaps to it
  const COLORES = {
    ruta: "#FFD400", rutaBorde: "#1a1a1a", aproximada: "#FF8C00", acometida: "#00E65A",
    conexion: "#00C846", cliente: "#E61E1E", mufa: "#FF8C00", mufaBorde: "#5A2600",
    nodo: "#2878FF", poste: "#FFFFFF", posteNuevo: "#9A9A9A", medida: "#00E5FF", fibra: "#7B2FBE",
    buscada: "#E01B84", posteMarcado: "#00A651",
  };

  let api = null;
  let cfg = null;
  let mapa = null;
  let datos = null;                 // last calcular_ruta result
  let calculando = false;
  let iniciado = false;
  const historial = [];
  const capas = {};
  let puntosIman = [];              // L.LatLng the measuring tool snaps to
  const postesMarcados = new Set(); // indexes of datos.postes_nuevos marked as existing (clicked on the map)

  // ------------------------------------------------------------------ utilidades
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, dec = 1) => Number(v).toLocaleString("en-US",
    { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const metros = (v, dec = 1) => `${num(v, dec)} m`;
  const coordTexto = (lat, lon) => `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`;
  const mismoPunto = (a, b) => Math.abs(a.lat - b.lat) < 1e-9 && Math.abs(a.lon - b.lon) < 1e-9;

  function mensaje(texto, tipo = "") {
    const caja = $("mensaje");
    caja.className = "mensaje" + (tipo && tipo !== "cargando" ? " " + tipo : "");
    $("spinner").hidden = tipo !== "cargando";
    $("mensaje-texto").textContent = texto;
    $("mensaje-texto").title = texto;
  }

  async function copiar(texto, avisoOk) {
    if (!api) return;
    try {
      const r = await api.copiar(texto);
      if (r && r.ok) mensaje(avisoOk, "ok");
      else mensaje((r && r.error) || "No se pudo copiar", "error");
    } catch (e) {
      mensaje("No se pudo copiar: " + e, "error");
    }
  }

  // ------------------------------------------------------------------ íconos SVG
  function pin(color, ancho, alto) {
    const html = `<svg width="${ancho}" height="${alto}" viewBox="0 0 30 42">
      <path d="M15 41C15 41 2 24.5 2 15a13 13 0 0 1 26 0c0 9.5-13 26-13 26z"
            fill="${color}" stroke="#1a1a1a" stroke-width="2"/>
      <circle cx="15" cy="15" r="5.5" fill="#fff" stroke="#1a1a1a" stroke-width="1.5"/></svg>`;
    return L.divIcon({ className: "icono", html, iconSize: [ancho, alto], iconAnchor: [ancho / 2, alto - 1],
                       popupAnchor: [0, -alto + 4], tooltipAnchor: [0, -alto + 2] });
  }
  function circulo(color, diametro, borde = "#1a1a1a", grosor = 2) {
    const r = diametro / 2;
    const html = `<svg width="${diametro}" height="${diametro}">
      <circle cx="${r}" cy="${r}" r="${r - grosor / 2}" fill="${color}" stroke="${borde}" stroke-width="${grosor}"/></svg>`;
    return L.divIcon({ className: "icono", html, iconSize: [diametro, diametro], iconAnchor: [r, r],
                       popupAnchor: [0, -r], tooltipAnchor: [0, -r] });
  }
  function rombo(color, lado) {
    const h = lado / 2;
    const html = `<svg width="${lado}" height="${lado}">
      <path d="M${h} 1 L${lado - 1} ${h} L${h} ${lado - 1} L1 ${h} Z" fill="${color}" stroke="#0b1f4d" stroke-width="2"/></svg>`;
    return L.divIcon({ className: "icono", html, iconSize: [lado, lado], iconAnchor: [h, h],
                       popupAnchor: [0, -h], tooltipAnchor: [0, -h] });
  }
  const iconoVacio = () => L.divIcon({ className: "icono", html: "", iconSize: [0, 0] });
  const ICONOS = {};
  function crearIconos() {
    ICONOS.conexion = pin(COLORES.conexion, 34, 48);
    ICONOS.cliente = pin(COLORES.cliente, 34, 48);
    ICONOS.buscada = pin(COLORES.buscada, 34, 48);
    ICONOS.mufaRuta = circulo(COLORES.mufa, 16);
    ICONOS.mufaIntervenida = circulo(COLORES.mufa, 20, COLORES.mufaBorde, 5);
    ICONOS.nodo = rombo(COLORES.nodo, 18);
    ICONOS.poste = circulo(COLORES.poste, 11);
    ICONOS.posteNuevo = circulo(COLORES.posteNuevo, 11);
    ICONOS.posteMarcado = circulo(COLORES.poste, 13, COLORES.posteMarcado, 3.5);
  }

  // ------------------------------------------------------------------ mapa
  function grupoPostes(clase) {
    return L.markerClusterGroup({
      maxClusterRadius: 35, disableClusteringAtZoom: 17, showCoverageOnHover: false,
      spiderfyOnMaxZoom: false,
      iconCreateFunction: (c) => L.divIcon({
        className: "icono", iconSize: [28, 28],
        html: `<div class="cluster-postes ${clase}" style="width:28px;height:28px">${c.getChildCount()}</div>`,
      }),
    });
  }

  function crearMapa() {
    crearIconos();
    mapa = L.map("mapa", { zoomControl: true, maxZoom: 20, worldCopyJump: false })
      .setView(cfg.inicio, cfg.zoom_inicial);
    mapa.attributionControl.setPrefix(false);

    const opciones = { maxZoom: 20, maxNativeZoom: 19 };
    const satelite = L.layerGroup([
      L.tileLayer(cfg.imagery_url, { ...opciones, attribution: "Imágenes © Esri, Maxar, Earthstar Geographics" }),
      L.tileLayer(cfg.labels_url, { ...opciones, attribution: "Calles © Esri" }),
    ]).addTo(mapa);
    const calles = L.tileLayer(cfg.streets_url, { ...opciones, attribution: cfg.streets_attribution });

    // Whole network (like the KMZ in Google Earth): one canvas in its own pane under the route and
    // markers; the layers start OFF and load only the visible area when turned on (see cargarRed).
    mapa.createPane("red").style.zIndex = 350;
    lienzoRed = L.canvas({ pane: "red", padding: 0.2 });
    Object.keys(CAPAS_RED).forEach((nombre) => { capas[nombre] = L.layerGroup(); });   // not added: off
    capas.caminoFibra = L.layerGroup().addTo(mapa);     // logical fibre path (fusion route), under the new route
    capas.ruta = L.layerGroup().addTo(mapa);
    capas.postesExistentes = grupoPostes("").addTo(mapa);
    capas.postesNuevos = grupoPostes("nuevos").addTo(mapa);
    capas.mufasRuta = L.layerGroup().addTo(mapa);
    capas.mufasIntervenidas = L.layerGroup().addTo(mapa);
    capas.nodosVisio = L.layerGroup().addTo(mapa);
    capas.extremos = L.layerGroup().addTo(mapa);         // connection point and client, always on top
    capas.medidas = L.layerGroup().addTo(mapa);
    capas.busqueda = L.layerGroup().addTo(mapa);       // mufa chosen in the search box

    L.control.layers({ "Satélite": satelite, "Calles": calles }, {
      "Postes existentes": capas.postesExistentes,
      "Postes nuevos": capas.postesNuevos,
      "Mufas en ruta": capas.mufasRuta,
      "Mufas intervenidas": capas.mufasIntervenidas,
      "Nodos Visio": capas.nodosVisio,
      "Camino de la fibra": capas.caminoFibra,
      "Mufa buscada": capas.busqueda,
      "Mis medidas": capas.medidas,
      ...Object.fromEntries(Object.entries(CAPAS_RED).map(([nombre, c]) => [
        `<span class="capa-red">${c.etiqueta}</span>`, capas[nombre]])),
    }, { position: "topleft", collapsed: false }).addTo(mapa);
    crearEstadoRed();
    mapa.on("overlayadd", (e) => { const n = nombreCapaRed(e.layer); if (n) cargarRed(n); });
    mapa.on("overlayremove", (e) => { const n = nombreCapaRed(e.layer); if (n) quitarRed(n); });
    mapa.on("moveend", () => {
      clearTimeout(temporizadorRed);
      temporizadorRed = setTimeout(() => capasRedActivas().forEach(cargarRed), 350);
    });

    crearLeyenda();
    mapa.on("contextmenu", alClicDerecho);
    mapa.on("click", alClicMapa);
    mapa.on("mousemove", alMoverMouse);
    mapa.on("dblclick", () => { if (med.activo) terminarMedicion(); });
    mapa.on("movestart zoomstart", ocultarMenu);
  }

  function crearLeyenda() {
    const fila = (muestra, texto) =>
      `<div class="fila"><span class="muestra">${muestra}</span><span>${texto}</span></div>`;
    const linea = (css) => `<span class="linea" style="${css}"></span>`;
    const icono = (ic) => ic.options.html;
    const control = L.control({ position: "bottomleft" });
    control.onAdd = () => {
      const div = L.DomUtil.create("div", "leyenda");
      div.innerHTML = `<h4>Leyenda</h4><div class="cuerpo">
        ${fila(linea(`border-top:7px solid ${COLORES.ruta};box-shadow:0 0 0 2px ${COLORES.rutaBorde}`), "Ruta (flechas hacia el cliente)")}
        ${fila(linea(`border-top:4px dashed ${COLORES.aproximada}`), "Ruta aproximada (sin Google)")}
        ${fila(linea(`border-top:4px dashed ${COLORES.acometida}`), "Acometida al cliente")}
        ${fila(linea(`border-top:4px dotted ${COLORES.fibra}`), "Camino de la fibra (fusión)")}
        ${fila(linea(`border-top:4px solid ${COLORES.medida}`), "Mis medidas")}
        ${fila(icono(pin(COLORES.conexion, 17, 24)), "Punto de conexión")}
        ${fila(icono(pin(COLORES.cliente, 17, 24)), "Cliente")}
        ${fila(icono(pin(COLORES.buscada, 17, 24)), "Mufa buscada")}
        ${fila(icono(ICONOS.mufaIntervenida), "Mufa intervenida")}
        ${fila(icono(ICONOS.mufaRuta), "Mufa en ruta")}
        ${fila(icono(ICONOS.nodo), "Nodo Visio cercano")}
        ${fila(icono(ICONOS.poste), "Poste existente")}
        ${fila(icono(ICONOS.posteNuevo), "Poste nuevo (aprox.; clic: ya existe)")}
        ${fila(icono(ICONOS.posteMarcado), "Poste nuevo marcado como existente")}
        ${fila(linea(`border-top:3px dashed ${COLORES.nodo}`), "Red Visio: enlace entre nodos")}
        <div class="nota">Red KMZ: panel <b>Lugares</b> (izquierda), con los estilos del KMZ</div>
      </div>`;
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.querySelector("h4").addEventListener("click", () => div.classList.toggle("leyenda-plegada"));
      if (window.innerHeight < 820) div.classList.add("leyenda-plegada");   // would cover the layer checkboxes
      return div;
    };
    control.addTo(mapa);
  }

  function limpiarCapas() {
    ["ruta", "postesExistentes", "postesNuevos", "mufasRuta", "mufasIntervenidas", "nodosVisio", "extremos", "caminoFibra"]
      .forEach((nombre) => capas[nombre].clearLayers());
    puntosIman = [];
  }

  // ------------------------------------------------------------------ marcadores y popups
  function popupHtml(info, latlng) {
    const filas = (info.filas || []).filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
    const coord = coordTexto(latlng.lat, latlng.lng);
    return `<div class="popup"><h3>${esc(info.nombre)}</h3>
      <div class="tipo">${esc(info.tipo)}</div>
      <dl>${filas}<dt>Coordenada</dt><dd>${coord}</dd></dl>
      <div class="acciones"><button type="button" class="btn btn-chico" data-copiar="${coord}">Copiar coordenada</button></div>
    </div>`;
  }

  function marcador(lat, lon, icono, info, capa, tooltip = {}) {
    const latlng = L.latLng(lat, lon);
    const mk = L.marker(latlng, { icon: icono, riseOnHover: true, zIndexOffset: tooltip.zIndex || 0 });
    if (tooltip.permanente) {
      mk.bindTooltip(esc(info.nombre), { permanent: true, direction: "top", className: `etiqueta ${tooltip.clase || ""}` });
    } else {
      mk.bindTooltip(esc(info.nombre), { direction: "top", className: "hover" });
    }
    mk.bindPopup(() => popupHtml(info, latlng), { maxWidth: 340 });
    mk.on("click", () => {                 // while measuring, a marker click adds a point instead
      if (med.activo) { mk.closePopup(); agregarPunto(latlng); }
    });
    capa.addLayer(mk);
    puntosIman.push(latlng);
    return mk;
  }

  // ------------------------------------------------------------------ postes nuevos que ya existen
  // A click on a new pole marks it as existing (and back). The budget then charges it as an
  // existing pole instead of a new 8 m pole: the marks travel as route metres (postes_nuevos.metros).
  const postesMarcables = (d) => !!d && Array.isArray(d.postes_nuevos.metros)
    && d.postes_nuevos.metros.length === d.postes_nuevos.posiciones.length;
  const metrosMarcados = () => (postesMarcables(datos)
    ? [...postesMarcados].map((i) => datos.postes_nuevos.metros[i]).sort((a, b) => a - b) : []);
  const textoPosteNuevo = (d, i) => (postesMarcados.has(i)
    ? `Poste ${i + 1}: marcado como existente (clic para volver a nuevo)`
    : `Poste nuevo ${i + 1} (aprox., cada ${d.postes_nuevos.spacing_m} m) · clic si ya existe`);

  function marcadorPosteNuevo(d, i) {
    const [lat, lon] = d.postes_nuevos.posiciones[i];
    const latlng = L.latLng(lat, lon);
    const mk = L.marker(latlng, { icon: postesMarcados.has(i) ? ICONOS.posteMarcado : ICONOS.posteNuevo,
                                  riseOnHover: true });
    mk.bindTooltip(esc(textoPosteNuevo(d, i)), { direction: "top", className: "hover" });
    mk.on("click", () => {
      if (med.activo) { agregarPunto(latlng); return; }   // while measuring, a click adds a point instead
      alternarPoste(i, mk);
    });
    (postesMarcados.has(i) ? capas.postesExistentes : capas.postesNuevos).addLayer(mk);
    puntosIman.push(latlng);
    return mk;
  }

  function alternarPoste(i, mk) {
    if (!datos) return;
    const marcado = !postesMarcados.has(i);
    if (marcado) postesMarcados.add(i); else postesMarcados.delete(i);
    // A marked pole moves to the existing poles layer (and its clusters), with its own icon.
    (marcado ? capas.postesNuevos : capas.postesExistentes).removeLayer(mk);
    mk.setIcon(marcado ? ICONOS.posteMarcado : ICONOS.posteNuevo);
    (marcado ? capas.postesExistentes : capas.postesNuevos).addLayer(mk);
    mk.setTooltipContent(esc(textoPosteNuevo(datos, i)));
    renderPanel();
    mensaje(`Poste ${i + 1} ${marcado ? "marcado como existente" : "vuelve a ser nuevo"}: ` +
            `${datos.postes_existentes.length + postesMarcados.size} existentes, ` +
            `${datos.postes_nuevos.cantidad - postesMarcados.size} nuevos. Recalculando el presupuesto aproximado…`, "ok");
    programarEstimacion();
  }

  function desmarcarPostes() {
    if (!datos || !postesMarcados.size) return;
    postesMarcados.clear();
    capas.postesNuevos.clearLayers();
    capas.postesExistentes.clearLayers();
    // Redraw only the poles; the rest of the map (and the view) stays as it is.
    datos.postes_existentes.forEach(([id, lat, lon]) =>
      marcador(lat, lon, ICONOS.poste, { nombre: `Poste ${id}`, tipo: "Poste existente" }, capas.postesExistentes));
    datos.postes_nuevos.posiciones.forEach((_, i) => marcadorPosteNuevo(datos, i));
    renderPanel();
    mensaje("Postes desmarcados: todos los postes nuevos se cobran como nuevos. Recalculando el presupuesto aproximado…", "ok");
    programarEstimacion();
  }

  // ------------------------------------------------------------------ red Visio completa
  // Off at start-up. Turning a layer on (layer control) loads only the visible area of the map,
  // again after every move; below each layer's minimum zoom nothing is loaded (see visor_rutas/red.py).
  // The KMZ network is in the "Lugares" panel (lugares.js), with the KMZ's own folders and styles.
  const CAPAS_RED = {
    visio_nodos:   { etiqueta: "Red Visio · nodos", tipo: "punto", relleno: "#2878FF", radio: 5 },
    visio_enlaces: { etiqueta: "Red Visio · enlaces", tipo: "linea" },
  };
  const PALETA_LINEAS = ["#00C2FF", "#FF4FD8", "#7CFC00", "#FFB000", "#B388FF", "#00E6A8", "#FF6B6B", "#4DD0E1",
                         "#F4FF81", "#FF9E80"];
  let lienzoRed = null, temporizadorRed = null, controlEstadoRed = null;
  const estadoRed = {};               // layer -> { pedido, texto, error, puntos }

  const colorTipo = (tipo) => {       // one stable colour per KMZ line type
    let h = 0;
    for (const c of String(tipo || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return PALETA_LINEAS[h % PALETA_LINEAS.length];
  };
  const esTroncal = (texto) => /troncal|backbone|principal|trunk/i.test(texto || "");
  const nombreCapaRed = (capa) => Object.keys(CAPAS_RED).find((n) => capas[n] === capa);
  const capasRedActivas = () => Object.keys(CAPAS_RED).filter((n) => mapa.hasLayer(capas[n]));

  function popupRed(e, html) {
    if (med.activo) return;                       // while measuring, the click adds a point instead
    L.popup({ maxWidth: 340 }).setLatLng(e.latlng).setContent(html).openOn(mapa);
  }

  async function cargarRed(nombre) {
    const est = estadoRed[nombre] || (estadoRed[nombre] = { pedido: 0, texto: "", error: false, puntos: [] });
    const pedido = ++est.pedido;                  // an older answer (previous map position) is dropped
    const b = mapa.getBounds().pad(0.15);
    est.texto = "cargando…";
    est.error = false;
    pintarEstadoRed();
    let res;
    try { res = await api.red(nombre, b.getWest(), b.getSouth(), b.getEast(), b.getNorth(), mapa.getZoom()); }
    catch (e) { res = { ok: false, error: String(e) }; }
    if (pedido !== est.pedido || !mapa.hasLayer(capas[nombre])) return;
    capas[nombre].clearLayers();
    est.puntos = [];
    if (!res.ok) {
      est.texto = res.error;
      est.error = true;
    } else if (res.debajo_del_zoom) {
      est.texto = `acerque el mapa para verla (zoom ${res.zoom_min} o más)`;
    } else {
      dibujarRed(nombre, res.elementos);
      est.texto = `${res.elementos.length.toLocaleString("en-US")}` +
        (res.truncado ? " (máximo por vista: acerque el mapa para ver todo)" : "");
    }
    pintarEstadoRed();
  }

  function quitarRed(nombre) {
    if (estadoRed[nombre]) estadoRed[nombre].pedido++;
    delete estadoRed[nombre];
    capas[nombre].clearLayers();
    pintarEstadoRed();
  }

  function dibujarRed(nombre, elementos) {
    const conf = CAPAS_RED[nombre], capa = capas[nombre], est = estadoRed[nombre];
    elementos.forEach((x) => {
      const titulo = x.nombre || x.tipo || conf.etiqueta;
      const filas = [["Tipo", x.tipo], ["Descripción", x.descripcion], ["Fuente", x.fuente], ["Confianza", x.confianza],
                     ["Hilos del cable", x.hilos],
                     ["Estado", x.excluida ? "excluida en business_rules (mal estado / deshabilitado / sin info)" : null],
                     ["Coordenada", x.estimada ? "estimada con sus vecinos" : null]];
      if (conf.tipo === "linea") {
        const troncal = esTroncal(`${x.tipo || ""} ${x.nombre || ""}`);
        const enlace = nombre === "visio_enlaces";
        const color = enlace ? COLORES.nodo : (x.excluida ? "#9A9A9A" : (troncal ? "#FF3B30" : colorTipo(x.tipo)));
        x.lineas.forEach((linea) => {
          const pl = L.polyline(linea, { renderer: lienzoRed, pane: "red", color, weight: troncal ? 4 : 2.5,
                                         opacity: enlace && x.confianza === "baja" ? 0.5 : 0.9,
                                         dashArray: enlace ? "6 6" : (x.excluida ? "4 6" : null) });
          pl.bindTooltip(esc(titulo), { sticky: true, className: "hover" });
          pl.on("click", (e) => popupRed(e, popupHtml({ nombre: titulo, tipo: conf.etiqueta, filas }, e.latlng)));
          capa.addLayer(pl);
        });
      } else {
        const ll = L.latLng(x.lat, x.lon);
        const relleno = x.excluida ? "#9A9A9A"
          : (nombre === "visio_nodos" && x.tipo !== "MUFA" ? COLORES.fibra : conf.relleno);
        const m = L.circleMarker(ll, { renderer: lienzoRed, pane: "red", radius: conf.radio, color: "#1a1a1a",
                                       weight: 1.5, fillColor: relleno, fillOpacity: 1,
                                       dashArray: x.estimada ? "2 2" : null });
        m.bindTooltip(esc(titulo), { direction: "top", className: "hover" });
        m.on("click", (e) => {
          if (nombre === "visio_nodos") window.__mufaExistente = { nombre: x.nombre, lat: x.lat, lon: x.lon };   // Enter: its editor / Visio
          popupRed(e, popupHtml({ nombre: titulo, tipo: conf.etiqueta, filas }, ll));
        });
        if (nombre === "visio_nodos") m.on("dblclick", (e) => {
          L.DomEvent.stop(e);
          if (window.Redes) window.Redes.abrirMufaExistente(x.nombre, x.lat, x.lon); else abrirDiagramaPorNombre(x.nombre);
        });
        capa.addLayer(m);
        if (nombre !== "kmz_postes") est.puntos.push(ll);       // the measuring tool snaps to them
      }
    });
  }

  function crearEstadoRed() {
    controlEstadoRed = L.control({ position: "bottomleft" });
    controlEstadoRed.onAdd = () => {
      const div = L.DomUtil.create("div", "estado-red");
      div.hidden = true;
      L.DomEvent.disableClickPropagation(div);
      return div;
    };
    controlEstadoRed.addTo(mapa);
    // a separator before the network layers in the layer control
    const primera = document.querySelector(".leaflet-control-layers .capa-red");
    if (primera) primera.closest("label").classList.add("primera-red");
  }

  function pintarEstadoRed() {
    if (!controlEstadoRed) return;
    const div = controlEstadoRed.getContainer();
    const activas = Object.keys(estadoRed).filter((n) => mapa.hasLayer(capas[n]));
    div.hidden = !activas.length;
    div.innerHTML = `<b>Red completa</b>` + activas.map((n) =>
      `<div class="${estadoRed[n].error ? "error" : ""}">${esc(CAPAS_RED[n].etiqueta)}: ${esc(estadoRed[n].texto)}</div>`).join("");
  }

  // ------------------------------------------------------------------ dibujo de la ruta
  function dibujar(d) {
    limpiarCapas();
    const r = d.ruta, c = d.conexion, cli = d.cliente;
    const pts = r.puntos.map((p) => L.latLng(p[0], p[1]));
    const limites = L.latLngBounds(pts);
    pts.forEach((p) => puntosIman.push(p));

    // Ruta: borde oscuro + línea amarilla; punteada naranja si es aproximada. Flechas hacia el cliente.
    let principal;
    if (r.aproximada) {
      L.polyline(pts, { color: COLORES.rutaBorde, weight: 9, opacity: 0.6, interactive: false }).addTo(capas.ruta);
      principal = L.polyline(pts, { color: COLORES.aproximada, weight: 5, dashArray: "12 10", lineCap: "butt" });
    } else {
      L.polyline(pts, { color: COLORES.rutaBorde, weight: 11, opacity: 0.85, lineJoin: "round", interactive: false })
        .addTo(capas.ruta);
      principal = L.polyline(pts, { color: COLORES.ruta, weight: 7, lineJoin: "round" });
    }
    principal.bindTooltip(`Ruta: ${metros(r.distancia_m)}${r.aproximada ? " (línea recta)" : ""}`, { sticky: true })
      .addTo(capas.ruta);
    L.polylineDecorator(principal, {
      patterns: [{
        offset: 45, repeat: 120,
        symbol: L.Symbol.arrowHead({
          pixelSize: 11, polygon: true,
          pathOptions: { stroke: true, color: "#1a1a1a", weight: 1, fillColor: "#1a1a1a", fillOpacity: 1, interactive: false },
        }),
      }],
    }).addTo(capas.ruta);

    // Acometida: del fin de la ruta (donde Google la deja en la calle) al cliente.
    if (r.acometida_m >= cfg.drop_min_m) {
      const tramo = [pts[pts.length - 1], L.latLng(cli.lat, cli.lon)];
      L.polyline(tramo, { color: COLORES.rutaBorde, weight: 8, opacity: 0.75, interactive: false }).addTo(capas.ruta);
      L.polyline(tramo, { color: COLORES.acometida, weight: 4, dashArray: "6 7", lineCap: "butt" })
        .bindTooltip(`Acometida al cliente: ${metros(r.acometida_m, 0)}`, { sticky: true }).addTo(capas.ruta);
    }

    // Postes
    d.postes_existentes.forEach(([id, lat, lon]) => {
      marcador(lat, lon, ICONOS.poste, { nombre: `Poste ${id}`, tipo: "Poste existente" }, capas.postesExistentes);
      limites.extend([lat, lon]);
    });
    d.postes_nuevos.posiciones.forEach(([lat, lon], i) => {
      if (postesMarcables(d)) marcadorPosteNuevo(d, i);
      else marcador(lat, lon, ICONOS.posteNuevo, {
        nombre: `Poste nuevo ${i + 1}`, tipo: `Posición aproximada (cada ${d.postes_nuevos.spacing_m} m)`,
      }, capas.postesNuevos);
      limites.extend([lat, lon]);
    });

    // Mufas: las intervenidas con borde grueso; las de la ruta que no lo son, normales.
    const enConexion = (p) => mismoPunto(p, c);
    const idsIntervenidas = new Set(d.mufas_intervenidas.map((m) => String(m.id)));
    d.mufas_intervenidas.filter((m) => m.lat !== null && m.lon !== null && !enConexion(m)).forEach((m) => {
      marcador(m.lat, m.lon, ICONOS.mufaIntervenida, {
        nombre: m.nombre, tipo: "Mufa intervenida",
        filas: [["Fuente", d.mufas_intervenidas_fuente]],
      }, capas.mufasIntervenidas);
      limites.extend([m.lat, m.lon]);
    });
    d.mufas_en_ruta.filter((m) => !idsIntervenidas.has(String(m.id)) && !enConexion(m)).forEach((m) => {
      marcador(m.lat, m.lon, ICONOS.mufaRuta, {
        nombre: m.nombre, tipo: "Mufa en ruta" + (m.troncal ? " · troncal" : ""),
        filas: [["Distancia a la ruta", metros(m.distancia_m)], ["Tipo", m.tipo]],
      }, capas.mufasRuta);
      limites.extend([m.lat, m.lon]);
    });

    // Nodos Visio cercanos
    d.nodos_visio_cercanos.forEach((n) => {
      marcador(n.lat, n.lon, ICONOS.nodo, {
        nombre: n.nombre, tipo: `Nodo Visio · ${n.tipo}`,
        filas: [["Distancia al cliente", metros(n.distancia_m, 0)], ["Notas", n.notas]],
      }, capas.nodosVisio);
      limites.extend([n.lat, n.lon]);
    });

    dibujarCaminoFibra(d);     // not included in the zoom: the path to the OLT can be kilometres long

    // Punto de conexión y cliente, con su nombre siempre visible (como en el mapa del Excel).
    marcador(c.lat, c.lon, ICONOS.conexion, {
      nombre: c.nombre, tipo: `Punto de conexión · ${c.tipo}`,
      filas: [["Fuente", c.fuente], ["Línea recta al cliente", metros(c.distancia_lineal_m)],
              ["Revisión", c.requiere_revision ? "Validar en campo" : null], ["Notas", c.notas]],
    }, capas.extremos, { permanente: true, clase: "conexion", zIndex: 1000 });
    marcador(cli.lat, cli.lon, ICONOS.cliente, {
      nombre: "Cliente", tipo: "Coordenada del cliente",
      filas: [["Distancia por ruta", metros(r.distancia_m)]],
    }, capas.extremos, { permanente: true, clase: "cliente", zIndex: 1100 });
    limites.extend([c.lat, c.lon]).extend([cli.lat, cli.lon]);

    // Leave room for the layer control (left) and the summary panel (right) when they are open.
    const control = document.querySelector(".leaflet-control-layers");
    const izquierda = (control ? control.offsetWidth : 0) + 30;
    const derecha = $("panel").hidden ? 40 : $("panel").offsetWidth + 30;
    mapa.fitBounds(limites, { paddingTopLeft: [izquierda, 50], paddingBottomRight: [derecha, 50], maxZoom: 19 });
  }

  // ------------------------------------------------------------------ panel de resumen
  function tarjeta(titulo, cuerpo, clase = "") {
    return `<section class="tarjeta ${clase}"><h2>${esc(titulo)}</h2>${cuerpo}</section>`;
  }
  function filas(pares) {
    return "<dl>" + pares.filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("") + "</dl>";
  }

  function renderPanel() {
    const html = [];
    if (datos) {
      const d = datos, c = d.conexion, r = d.ruta, o = d.origen_trafico;
      if (d.avisos.length) {
        html.push(tarjeta("Avisos", "<ul>" + d.avisos.map((a) => `<li>${esc(a)}</li>`).join("") + "</ul>", "avisos"));
      }
      html.push(tarjeta("Punto de conexión",
        `<div class="principal">${esc(c.nombre)}</div>` +
        filas([["Tipo", esc(c.tipo + (c.tipo_detalle && c.tipo_detalle !== c.tipo ? ` (${c.tipo_detalle})` : ""))],
               ["Fuente", esc(c.fuente)], ["Línea recta", metros(c.distancia_lineal_m)],
               ["Coordenada", coordTexto(c.lat, c.lon)]]) +
        (c.requiere_revision ? `<span class="etiqueta-revision">Validar en campo</span>` : "") +
        (c.notas ? `<div class="nota">${esc(c.notas)}</div>` : "")));
      html.push(tarjeta("Ruta", filas([
        ["Distancia por ruta", metros(r.distancia_m) + (r.aproximada ? " (línea recta)" : "")],
        ["Acometida al cliente", r.acometida_m >= cfg.drop_min_m ? metros(r.acometida_m, 0) : null],
        ["Reserva", metros(r.reserva_m)],
        ["Metraje final", `<b>${metros(r.metraje_final_m)}</b>`],
        ["Tipo de cable", esc(r.tipo_cable)],
      ])));
      const marcados = postesMarcados.size;
      html.push(tarjeta("Postes", filas([
        ["Existentes", String(d.postes_existentes.length + marcados) +
          (marcados ? ` <span class="nota">(${marcados} marcado${marcados === 1 ? "" : "s"} en el mapa)</span>` : "")],
        ["Nuevos", `${d.postes_nuevos.cantidad - marcados} (cada ${esc(d.postes_nuevos.spacing_m)} m)`],
      ]) + (postesMarcables(d) && d.postes_nuevos.posiciones.length
        ? `<div class="nota">Clic en un poste nuevo (gris) del mapa si ya existe: se cobra como existente y el presupuesto baja.` +
          (marcados ? ` <button type="button" class="btn btn-chico" data-desmarcar-postes>Desmarcar todos</button>` : "") + `</div>`
        : "")));
      html.push(tarjeta(`Mufas intervenidas (${d.mufas_intervenidas.length})`,
        (d.mufas_intervenidas_fuente ? `<div class="nota">Fuente: ${esc(d.mufas_intervenidas_fuente)}</div>` : "") +
        "<ul>" + d.mufas_intervenidas.map((m) => `<li>${esc(m.nombre)}</li>`).join("") + "</ul>"));
      html.push(tarjeta("Origen de tráfico", filas([
        ["Nodo OLT", esc(o.nodo || "Pendiente de validar")],
        ["MF", esc(o.mf || "—")],
        ["Confianza", o.confianza ? `<span class="confianza ${esc(o.confianza)}">${esc(o.confianza)}</span>` : "—"],
      ]) + (porNombre(o) ? `<div class="fila-insignias"><span class="insignia por-nombre">Por nombre – validar</span></div>` : "")
         + (o.camino.length ? `<div class="nota">Camino: ${o.camino.map(esc).join(" → ")}</div>` : "")
         + (o.motivo && !(o.diagnostico && o.motivo === o.diagnostico.detalle) ? `<div class="nota">${esc(o.motivo)}</div>` : "")
         + htmlDiagnostico(o)));
      if (d.nodos_visio_cercanos.length) {
        html.push(tarjeta("Nodos Visio cercanos", "<ul>" + d.nodos_visio_cercanos.map((n) =>
          `<li>${esc(n.nombre)} <span class="nota">(${esc(n.tipo)}, ${metros(n.distancia_m, 0)})</span></li>`).join("") + "</ul>"));
      }
    } else {
      html.push(`<p class="vacio">Pegue la coordenada del cliente abajo y presione <b>Generar ruta</b>.<br>
        Clic derecho en el mapa para usar o copiar una coordenada, o para medir desde ahí.</p>`);
    }
    if (medidas.length) {
      const total = medidas.reduce((s, m) => s + m.total, 0);
      html.push(tarjeta(`Mis medidas (${medidas.length})`, "<ul class=\"medidas\">" + medidas.map((m) =>
        `<li><span><span class="muestra-medida" style="background:${esc(m.color || COLORES.medida)}"></span>${esc(m.nombre)}: <b>${metros(m.total)}</b> <span class="nota">(${m.puntos.length - 1} tramo${m.puntos.length > 2 ? "s" : ""})</span></span>
         <button type="button" class="quitar" data-quitar-medida="${m.id}" title="Borrar esta medida">✕</button></li>`).join("") +
        "</ul>" + (medidas.length > 1 ? filas([["Suma", `<b>${metros(total)}</b>`]]) : "")));
    }
    $("tarjetas").innerHTML = html.join("");
    $("copiar-resumen").disabled = !datos && !medidas.length;
    renderFusion();
  }

  function resumenTexto() {
    const l = ["Visor de rutas – Fiber Budget"];
    if (datos) {
      const d = datos, c = d.conexion, r = d.ruta, o = d.origen_trafico;
      l.push(`Cliente: ${coordTexto(d.cliente.lat, d.cliente.lon)}`, "");
      l.push(`Punto de conexión: ${c.nombre}`,
             `  Tipo: ${c.tipo}${c.tipo_detalle && c.tipo_detalle !== c.tipo ? ` (${c.tipo_detalle})` : ""}`,
             `  Fuente: ${c.fuente}`, `  Coordenada: ${coordTexto(c.lat, c.lon)}`,
             `  Distancia en línea recta: ${metros(c.distancia_lineal_m)}`);
      if (c.requiere_revision) l.push("  VALIDAR EN CAMPO");
      if (c.notas) l.push(`  Notas: ${c.notas}`);
      l.push("", "Ruta", `  Distancia por ruta: ${metros(r.distancia_m)}${r.aproximada ? " (línea recta, sin Google)" : ""}`);
      if (r.acometida_m >= cfg.drop_min_m) l.push(`  Acometida al cliente: ${metros(r.acometida_m, 0)}`);
      l.push(`  Reserva: ${metros(r.reserva_m)}`, `  Metraje final: ${metros(r.metraje_final_m)}`,
             `  Tipo de cable: ${r.tipo_cable}`);
      l.push("", "Postes", `  Existentes: ${d.postes_existentes.length + postesMarcados.size}` +
             (postesMarcados.size ? ` (${postesMarcados.size} marcados en el mapa)` : ""),
             `  Nuevos: ${d.postes_nuevos.cantidad - postesMarcados.size} (cada ${d.postes_nuevos.spacing_m} m)`);
      l.push("", `Mufas intervenidas: ${d.mufas_intervenidas.length}` +
             (d.mufas_intervenidas_fuente ? ` (fuente: ${d.mufas_intervenidas_fuente})` : ""));
      d.mufas_intervenidas.forEach((m) => l.push(`  - ${m.nombre}`));
      l.push("", "Origen de tráfico", `  Nodo OLT: ${o.nodo || "Pendiente de validar"}`,
             `  MF: ${o.mf || "—"}`, `  Confianza: ${o.confianza || "—"}`);
      if (o.camino.length) l.push(`  Camino: ${o.camino.join(" → ")}`);
      if (porNombre(o)) l.push("  Mufa de conexión emparejada por nombre: VALIDAR");
      if (o.diagnostico) l.push(`  Diagnóstico: ${o.diagnostico.detalle}`);
      if (d.nodos_visio_cercanos.length) {
        l.push("", "Nodos Visio cercanos");
        d.nodos_visio_cercanos.forEach((n) => l.push(`  - ${n.nombre} (${n.tipo}, ${metros(n.distancia_m, 0)})`));
      }
      if (d.avisos.length) {
        l.push("", "Avisos");
        d.avisos.forEach((a) => l.push(`  - ${a}`));
      }
    }
    if (medidas.length) {
      l.push("", "Mis medidas");
      medidas.forEach((m) => l.push(`  - ${m.nombre}: ${metros(m.total)} (${m.puntos.length - 1} tramos)`));
    }
    return l.join("\r\n");
  }

  // ------------------------------------------------------------------ ruta de fusión
  const FUENTE_HILOS = {
    excel: ["excel", "Excel anillos"],
    texto_diagrama: ["texto", "Texto del diagrama"],
    sin_dato: ["sin-dato", "Sin dato de hilos"],
  };
  const IDENTIFICACION = {
    por_enlace: "nombre repetido: elegido por el cable a la mufa anterior",
    por_cercania: "elegido por cercanía (validar)",
    no_encontrada: "no se encontró en la base de diagramas",
    por_nombre: "emparejada por nombre con el punto de conexión del KMZ (sin mufa Visio por coordenada): validar",
  };
  // Why the connection mufa was not found by coordinate (origen.py "diagnostico").
  const CASOS_DIAGNOSTICO = {
    a_mayor_distancia: "Mufa parecida a mayor distancia",
    sin_coordenada_en_visio: "Sin coordenada en Visio",
    marcada_validar: "Marcada VALIDAR en el diagrama",
    no_diagramada: "No diagramada",
    es_reserva: "Es reserva (mufa nueva)",
  };
  const porNombre = (o) => !!o && (o.metodo === "c" || o.metodo === "d");

  function htmlDiagnostico(o) {
    const dg = o && o.diagnostico;
    if (!dg) return "";
    const casos = (dg.casos || [dg.caso]).map((c) =>
      `<span class="insignia diagnostico">${esc(CASOS_DIAGNOSTICO[c] || c)}</span>`).join("");
    return `<div class="diagnostico"><div class="fila-insignias">${casos}</div>` +
      `<div class="nota">${esc(dg.detalle)}</div></div>`;
  }
  let paradaActiva = null;
  let mostrarPiloto = false;        // "Mostrar fusiones detectadas (piloto)": off by default

  const tieneCoord = (p) => p && p.lat !== null && p.lat !== undefined && p.lon !== null && p.lon !== undefined;

  function dibujarCaminoFibra(d) {
    const paradas = (d.ruta_fusion || []).filter(tieneCoord);
    if (!paradas.length) return;
    const puntos = paradas.map((p) => L.latLng(p.lat, p.lon));
    puntos.push(L.latLng(d.conexion.lat, d.conexion.lon));       // last Visio mufa -> KMZ connection point
    L.polyline(puntos, { color: "#1a1a1a", weight: 7, opacity: 0.35, interactive: false }).addTo(capas.caminoFibra);
    L.polyline(puntos, { color: COLORES.fibra, weight: 4, dashArray: "2 9", lineCap: "round" })
      .bindTooltip("Camino lógico de la fibra (ruta de fusión)", { sticky: true }).addTo(capas.caminoFibra);
    paradas.forEach((p) => {
      L.circleMarker([p.lat, p.lon], { radius: 7, color: "#fff", weight: 2, fillColor: COLORES.fibra, fillOpacity: 1 })
        .bindTooltip(`${p.orden}. ${esc(p.nombre)}`, { direction: "top", className: "hover" })
        .on("click", () => { if (!med.activo) { mostrarPestana("fusion"); marcarParada(p.orden); } })
        .addTo(capas.caminoFibra);
    });
  }

  function insignias(p) {
    const [clase, texto] = FUENTE_HILOS[p.fuente_hilos] || FUENTE_HILOS.sin_dato;
    let html = `<span class="insignia ${clase}">${texto}</span>`;
    if (p.identificacion === "por_nombre") {
      html += `<span class="insignia por-nombre" title="${esc(IDENTIFICACION.por_nombre)}">Por nombre – validar</span>`;
    } else if (p.identificacion && p.identificacion !== "exacta") {
      html += `<span class="insignia alerta" title="${esc(IDENTIFICACION[p.identificacion] || p.identificacion)}">${
        p.identificacion === "no_encontrada" ? "No encontrada" : "Validar mufa"}</span>`;
    }
    (p.notas || []).slice(0, 4).forEach((n) => { html += `<span class="insignia nota">${esc(n)}</span>`; });
    return `<div class="fila-insignias">${html}</div>`;
  }

  function htmlParada(p) {
    const clases = ["parada", p.es_conexion ? "conexion" : ""].join(" ");
    const hilos = (p.hilos_anillo || []).map((h) =>
      `<li>${esc(h.de_mufa || "?")} <b>${esc(h.hilo_entrante || "?")}</b> → ${esc(h.hacia_mufa || "?")} <b>${esc(h.hilo_saliente || "?")}</b>` +
      `${h.enlace ? ` <span class="nota">(${esc(h.enlace)})</span>` : ""}</li>`).join("");
    const textos = p.splitters_y_puertos || [];
    const visibles = textos.slice(0, 4).map((t) => `<li>${esc(t.texto)}</li>`).join("");
    const resto = textos.slice(4).map((t) => `<li>${esc(t.texto)}</li>`).join("");
    const clientes = (p.clientes || []).map((c) => `<li>${esc(c.descripcion)}</li>`).join("");
    const diagramas = (p.archivos || []).filter((a) => a.diagrama);
    const sub = [p.tipo, p.propietario, p.zona].filter(Boolean).map(esc).join(" · ");
    // Pilot fusions: their own block and badge, never mixed with the Excel / diagram-text data.
    let piloto = "";
    if (mostrarPiloto && Array.isArray(p.fusiones_piloto)) {
      const item = (f) => `<li><span class="muestra-color" style="background:${esc(f.color)}"></span>` +
        `${esc(f.entrada)} → ${esc(f.salida)} <span class="nota">(${esc(f.color_tia)} · confianza ${Number(f.confianza).toFixed(2)})</span></li>`;
      const lista = p.fusiones_piloto;
      piloto = `<div class="bloque-piloto"><span class="insignia piloto">Piloto – validar</span>` + (lista.length
        ? `<ul class="lista-textos">${lista.slice(0, 5).map(item).join("")}</ul>` +
          (lista.length > 5 ? `<details><summary>${lista.length - 5} fusión(es) más</summary><ul class="lista-textos">${lista.slice(5).map(item).join("")}</ul></details>` : "")
        : `<div class="nota">Sin fusiones detectadas por el piloto en esta mufa</div>`) + `</div>`;
    }
    return `<li class="${clases}" data-orden="${p.orden}"><span class="punto"></span><div class="caja">
      <button type="button" class="titulo-parada" data-centrar="${p.orden}" ${tieneCoord(p) ? "" : "disabled"}
        title="${tieneCoord(p) ? "Centrar el mapa en esta mufa" : "Sin coordenadas"}">${p.orden}. ${esc(p.nombre)}</button>
      ${sub ? `<div class="sub">${sub}${p.es_conexion ? " · punto de conexión" : ""}</div>`
            : (p.es_conexion ? `<div class="sub">punto de conexión</div>` : "")}
      ${insignias(p)}
      ${hilos ? `<ul class="hilos">${hilos}</ul>` : ""}
      ${visibles ? `<ul class="lista-textos">${visibles}</ul>` : ""}
      ${resto ? `<details><summary>${textos.length - 4} texto(s) más del diagrama</summary><ul class="lista-textos">${resto}</ul></details>` : ""}
      ${clientes ? `<details><summary>${p.clientes.length} cliente(s) fusionado(s) en esta mufa</summary><ul class="lista-textos">${clientes}</ul></details>` : ""}
      ${piloto}
      <div class="acciones-parada">
        ${diagramas.length ? `<button type="button" class="btn btn-chico" data-diagrama="${p.orden}">Ver diagrama${diagramas.length > 1 ? ` (${diagramas.length})` : ""}</button>` : `<span class="nota">Sin diagrama</span>`}
      </div>
    </div></li>`;
  }

  function renderFusion() {
    const caja = $("fusion");
    const paradas = (datos && datos.ruta_fusion) || [];
    $("copiar-fusion").disabled = !paradas.length;
    if (!datos) {
      caja.innerHTML = `<p class="vacio">Genere una ruta para ver cómo llega el servicio desde el OLT hasta el punto de conexión.</p>`;
      return;
    }
    const o = datos.origen_trafico, c = datos.conexion;
    if (!paradas.length) {
      caja.innerHTML = o.diagnostico
        ? `<p class="vacio">Sin ruta de fusión: la mufa de conexión no se pudo seguir en los diagramas Visio.</p>${htmlDiagnostico(o)}`
        : `<p class="vacio">Sin ruta de fusión: no se encontró la mufa de conexión en los diagramas Visio.` +
          (o.motivo ? `<br><span class="nota">${esc(o.motivo)}</span>` : "") + `</p>`;
      return;
    }
    const olt = `<li class="parada olt"><span class="punto"></span><div class="caja">
        <div class="titulo-parada">${esc(o.nodo || "Nodo / OLT pendiente de validar")}</div>
        <div class="sub">Origen de tráfico${o.confianza ? ` · confianza <span class="confianza ${esc(o.confianza)}">${esc(o.confianza)}</span>` : ""}</div>
        ${o.etiqueta ? `<ul class="lista-textos"><li>${esc(o.etiqueta)}</li></ul>` : ""}
      </div></li>`;
    const ultima = paradas[paradas.length - 1];
    const conexionKmz = c.fuente === "kmz" && c.nombre !== ultima.nombre
      ? `<div class="sub">En el KMZ: ${esc(c.nombre)} (${metros(c.distancia_lineal_m)} del cliente en línea recta)</div>` : "";
    const cliente = `<li class="parada cliente"><span class="punto"></span><div class="caja">
        <div class="titulo-parada">Cliente</div>
        <div class="sub">${coordTexto(datos.cliente.lat, datos.cliente.lon)} · ${metros(datos.ruta.distancia_m)} de ruta nueva</div>
        ${conexionKmz}
      </div></li>`;
    // The pilot checkbox exists only when the fusiones_piloto table exists (fusiones_piloto is a list).
    const conPiloto = paradas.filter((p) => Array.isArray(p.fusiones_piloto));
    const totalPiloto = conPiloto.reduce((s, p) => s + p.fusiones_piloto.length, 0);
    const casilla = conPiloto.length ? `<label class="casilla-piloto">
        <input type="checkbox" id="ver-piloto" ${mostrarPiloto ? "checked" : ""}>
        Mostrar fusiones detectadas (piloto) <span class="nota">· ${totalPiloto} en estas mufas, sin validar</span></label>` : "";
    caja.innerHTML = `<p class="encabezado-fusion">Del OLT al punto de conexión, mufa por mufa, según los diagramas Visio y el Excel de anillos.
        Clic en una mufa para centrarla en el mapa.</p>${casilla}${porNombre(o) ? htmlDiagnostico(o) : ""}
      <ol class="metro">${olt}${paradas.map(htmlParada).join("")}${cliente}</ol>`;
    if (paradaActiva) marcarParada(paradaActiva, false);
  }

  function marcarParada(orden, desplazar = true) {
    paradaActiva = orden;
    document.querySelectorAll("#fusion .parada").forEach((li) =>
      li.classList.toggle("activa", Number(li.dataset.orden) === Number(orden)));
    const li = document.querySelector(`#fusion .parada[data-orden="${orden}"]`);
    if (li && desplazar) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function centrarParada(orden) {
    const p = ((datos && datos.ruta_fusion) || []).find((x) => x.orden === Number(orden));
    if (!tieneCoord(p)) return;
    marcarParada(orden, false);
    if (!mapa.hasLayer(capas.caminoFibra)) capas.caminoFibra.addTo(mapa);
    mapa.setView([p.lat, p.lon], Math.max(mapa.getZoom(), 18));
    mensaje(`${p.orden}. ${p.nombre}`, "ok");
  }

  function fusionTexto() {
    const paradas = (datos && datos.ruta_fusion) || [];
    const o = datos.origen_trafico;
    const l = [`Ruta de fusión – cliente ${coordTexto(datos.cliente.lat, datos.cliente.lon)}`,
               `OLT / nodo: ${o.nodo || "Pendiente de validar"}${o.confianza ? ` (confianza ${o.confianza})` : ""}` +
               (o.etiqueta ? ` – ${o.etiqueta}` : "")];
    if (o.diagnostico) l.push(`Diagnóstico: ${o.diagnostico.detalle}`);
    paradas.forEach((p) => {
      const partes = [`${p.orden}. ${p.nombre}${p.es_conexion ? " [punto de conexión]" : ""}`];
      const hilos = (p.hilos_anillo || []).map((h) => `${h.de_mufa || "?"} ${h.hilo_entrante || "?"} -> ${h.hacia_mufa || "?"} ${h.hilo_saliente || "?"}`);
      partes.push(hilos.length ? `hilos: ${hilos.join("; ")}` : "hilos: sin dato");
      const spl = (p.splitters_y_puertos || []).map((t) => t.texto);
      if (spl.length) partes.push(`splitter/puerto: ${spl.slice(0, 4).join(" | ")}`);
      partes.push(`fuente: ${(FUENTE_HILOS[p.fuente_hilos] || FUENTE_HILOS.sin_dato)[1]}`);
      if (p.identificacion !== "exacta") partes.push(`validar: ${IDENTIFICACION[p.identificacion] || p.identificacion}`);
      if ((p.notas || []).length) partes.push(`notas: ${p.notas.join(", ")}`);
      l.push(partes.join(" – "));
      if (mostrarPiloto && Array.isArray(p.fusiones_piloto) && p.fusiones_piloto.length) {
        l.push(`   PILOTO – VALIDAR: ` + p.fusiones_piloto.slice(0, 5).map((f) =>
          `${f.entrada} -> ${f.salida} (${f.color_tia}, ${Number(f.confianza).toFixed(2)})`).join(" | "));
      }
    });
    l.push(`Cliente: ${coordTexto(datos.cliente.lat, datos.cliente.lon)} (${metros(datos.ruta.distancia_m)} de ruta nueva desde ${datos.conexion.nombre})`);
    return l.join("\r\n");
  }

  function mostrarPestana(nombre) {
    document.querySelectorAll(".pestana").forEach((b) => {
      const activa = b.dataset.pestana === nombre;
      b.classList.toggle("activa", activa);
      b.setAttribute("aria-selected", String(activa));
    });
    $("tarjetas").hidden = nombre !== "resumen";
    $("fusion").hidden = nombre !== "fusion";
    $("panel-diagrama").hidden = nombre !== "diagrama";
    $("presupuesto-aprox").hidden = nombre !== "presupuesto";
    $("copiar-resumen").hidden = nombre !== "resumen";
    $("copiar-fusion").hidden = nombre !== "fusion";
    document.querySelector(".panel-acciones").hidden = nombre === "diagrama" || nombre === "presupuesto";
    $("panel").classList.toggle("ancho", nombre === "diagrama");      // diagrams are wide: the panel widens
    if ($("panel").hidden) { $("panel").hidden = false; $("abrir-panel").hidden = true; }
    actualizarOcupado();
    if (nombre === "diagrama" && visorPanel) visorPanel.alMostrar();
  }

  /** Width the panel covers, for the CSS that centres the search box in the visible map. */
  function actualizarOcupado() {
    const panel = $("panel");
    const ocupado = panel.hidden ? 0 : panel.offsetWidth + 20;
    document.documentElement.style.setProperty("--ocupado-derecha", `${ocupado}px`);
  }

  // ------------------------------------------------------------------ visor de diagramas (panel y pantalla completa)
  // Zoom resizes the image (width/height) instead of a CSS scale, so the SVG is drawn again at every
  // zoom and stays sharp. The mufa's label position (archivo.ancla, in cm of the page) is circled.
  const cacheDiagramas = new Map();   // md5 -> data URL, shared by both viewers
  const ZOOM_MAXIMO_PX = 60000;       // largest drawn width: enough to read the smallest hilo number
  const CM_ALREDEDOR = 30;            // "Ubicar mufa" shows about this much of the drawing around the mufa
  let visorPanel = null, visorModal = null;
  let diagramaActual = null;          // { titulo, archivos, indice } shown in the panel

  function crearVisor(ids) {
    const lienzo = $(ids.lienzo), img = $(ids.img), anillo = $(ids.anillo), estado = $(ids.estado);
    const v = { escala: 1, x: 0, y: 0, base: { w: 1, h: 1 }, arrastre: null, pedido: 0, archivo: null,
                cargado: false, pendiente: false };

    function aplicar() {
      Object.assign(img.style, { left: `${v.x}px`, top: `${v.y}px`,
                                 width: `${v.base.w * v.escala}px`, height: `${v.base.h * v.escala}px` });
      const a = v.archivo && v.archivo.ancla;
      anillo.hidden = !(a && v.cargado);
      if (!anillo.hidden) {
        anillo.style.left = `${v.x + (a.x_cm / a.ancho_cm) * v.base.w * v.escala}px`;
        anillo.style.top = `${v.y + (a.y_cm / a.alto_cm) * v.base.h * v.escala}px`;
      }
    }
    v.ajustar = () => {
      const w = lienzo.clientWidth, h = lienzo.clientHeight;
      v.escala = Math.min(w / v.base.w, h / v.base.h) * 0.97;
      v.x = (w - v.base.w * v.escala) / 2;
      v.y = (h - v.base.h * v.escala) / 2;
      aplicar();
    };
    /** Zoom to the mufa and circle it; false (and the whole diagram) when its position is unknown. */
    v.ubicar = () => {
      const a = v.archivo && v.archivo.ancla;
      if (!a || !v.cargado) { v.ajustar(); return false; }
      const w = lienzo.clientWidth, h = lienzo.clientHeight;
      const pxPorCm = v.base.w / a.ancho_cm;
      v.escala = Math.min(Math.min(w, h) / (CM_ALREDEDOR * pxPorCm), ZOOM_MAXIMO_PX / v.base.w);
      v.x = w / 2 - (a.x_cm / a.ancho_cm) * v.base.w * v.escala;
      v.y = h / 2 - (a.y_cm / a.alto_cm) * v.base.h * v.escala;
      aplicar();
      return true;
    };
    v.zoom = (factor, cx, cy) => {
      if (!v.cargado) return;
      if (cx === undefined) { cx = lienzo.clientWidth / 2; cy = lienzo.clientHeight / 2; }
      const minimo = Math.min(lienzo.clientWidth / v.base.w, lienzo.clientHeight / v.base.h) * 0.3;
      const nueva = Math.min(Math.max(v.escala * factor, minimo), ZOOM_MAXIMO_PX / v.base.w);
      v.x = cx - (cx - v.x) * (nueva / v.escala);
      v.y = cy - (cy - v.y) * (nueva / v.escala);
      v.escala = nueva;
      aplicar();
    };
    const colocar = () => {               // first view of a diagram: on the mufa when known
      if (!lienzo.clientWidth) { v.pendiente = true; return; }     // hidden: place it when shown
      v.pendiente = false;
      if (!v.ubicar() && v.archivo) mensaje("No se encontró la mufa dentro de este diagrama: se muestra completo");
    };
    v.alMostrar = () => { if (v.pendiente && v.cargado) colocar(); };
    v.limpiar = (texto = "") => {
      v.pedido++;
      v.archivo = null;
      v.cargado = false;
      img.hidden = true;
      anillo.hidden = true;
      estado.className = "diagrama-estado";
      estado.textContent = texto;
    };
    v.cargar = async (archivo) => {
      const pedido = ++v.pedido;          // ignore answers for a diagram that is no longer selected
      v.archivo = archivo;
      v.cargado = false;
      img.hidden = true;
      anillo.hidden = true;
      if (ids.ruta) $(ids.ruta).textContent = archivo.ruta_relativa;
      estado.className = "diagrama-estado";
      estado.innerHTML = `<span class="spinner"></span> Generando el diagrama… la primera vez tarda unos segundos`;
      let url = cacheDiagramas.get(archivo.md5);
      if (!url) {
        let res;
        try { res = await api.diagrama(archivo.md5, 0); } catch (e) { res = { ok: false, error: String(e) }; }
        if (pedido !== v.pedido) return;
        if (!res.ok) {
          estado.className = "diagrama-estado error";
          estado.textContent = res.error;
          return;
        }
        url = res.data_url;
        cacheDiagramas.set(archivo.md5, url);
      }
      img.onload = () => {
        if (pedido !== v.pedido) return;
        v.base = { w: img.naturalWidth || 1600, h: img.naturalHeight || 1000 };
        v.cargado = true;
        estado.innerHTML = "";
        img.hidden = false;
        colocar();
      };
      img.src = url;
    };

    lienzo.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = lienzo.getBoundingClientRect();
      v.zoom(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    lienzo.addEventListener("dblclick", (e) => {
      const r = lienzo.getBoundingClientRect();
      v.zoom(2, e.clientX - r.left, e.clientY - r.top);
    });
    lienzo.addEventListener("pointerdown", (e) => {
      v.arrastre = { x: e.clientX - v.x, y: e.clientY - v.y };
      lienzo.setPointerCapture(e.pointerId);
      lienzo.classList.add("arrastrando");
    });
    lienzo.addEventListener("pointermove", (e) => {
      if (!v.arrastre) return;
      v.x = e.clientX - v.arrastre.x;
      v.y = e.clientY - v.arrastre.y;
      aplicar();
    });
    const soltar = () => { v.arrastre = null; lienzo.classList.remove("arrastrando"); };
    lienzo.addEventListener("pointerup", soltar);
    lienzo.addEventListener("pointercancel", soltar);
    return v;
  }

  const ROLES = { principal: "diagrama de la mufa", vecino: "como vecina", red: "en diagrama de red",
                  por_nombre: "nombre encontrado aquí, sin coordenada" };
  const opcionesArchivos = (archivos) => archivos.map((a, i) =>
    `<option value="${i}">${esc(a.nombre)} (${esc(ROLES[a.rol] || a.rol)}${a.tipo_diagrama ? ", " + esc(a.tipo_diagrama) : ""}` +
    `${a.ancla ? "" : " · sin ubicar"})</option>`).join("");

  function htmlInfoMufa(m, titulo) {
    const coord = tieneCoord(m) ? coordTexto(m.lat, m.lon) : `<span class="sin-coord">sin coordenadas</span>`;
    const sub = [m.tipo, m.propietario, m.zona].filter(Boolean).map(esc).join(" · ");
    const hilos = (m.hilos_anillo || []).map((h) =>
      `<li>${esc(h.de_mufa || "?")} <b>${esc(h.hilo_entrante || "?")}</b> → ${esc(h.hacia_mufa || "?")} <b>${esc(h.hilo_saliente || "?")}</b></li>`).join("");
    const textos = (m.splitters_y_puertos || []).slice(0, 4).map((t) => `<li>${esc(t.texto)}</li>`).join("");
    const diagramas = (m.archivos || []).filter((a) => a.diagrama).length;
    return `<h3>${esc(titulo || m.nombre)}</h3>
      <div class="sub">${sub ? sub + " · " : ""}${coord} · ${diagramas} diagrama(s)</div>
      ${insignias(m)}
      ${hilos ? `<ul class="lista-textos">${hilos}</ul>` : ""}
      ${textos ? `<ul class="lista-textos">${textos}</ul>` : ""}`;
  }

  /** Show a mufa's diagrams in the panel's "Diagrama" tab (the panel widens). */
  function mostrarDiagrama(titulo, infoHtml, archivos, indice = 0) {
    diagramaActual = { titulo, archivos, indice };
    $("pd-info").innerHTML = infoHtml;
    $("pd-archivo").innerHTML = archivos.length ? opcionesArchivos(archivos) : `<option>Sin diagrama Visio</option>`;
    $("pd-archivo").disabled = archivos.length < 2;
    $("pd-archivo").value = String(indice);
    ["pd-menos", "pd-mas", "pd-ubicar", "pd-ajustar", "pd-pantalla"].forEach((id) => { $(id).disabled = !archivos.length; });
    mostrarPestana("diagrama");
    if (archivos.length) visorPanel.cargar(archivos[indice]);
    else visorPanel.limpiar("Esta mufa no aparece en ningún diagrama Visio");
  }

  function abrirDiagrama(orden) {             // "Ver diagrama" of a fusion-route stop
    const p = ((datos && datos.ruta_fusion) || []).find((x) => x.orden === Number(orden));
    if (!p) return;
    marcarParada(p.orden, false);
    mostrarDiagrama(`${p.orden}. ${p.nombre}`, htmlInfoMufa(p, `${p.orden}. ${p.nombre}`),
                    (p.archivos || []).filter((a) => a.diagrama));
  }

  function abrirPantallaCompleta() {
    if (!diagramaActual || !diagramaActual.archivos.length) return;
    const { titulo, archivos, indice } = diagramaActual;
    $("diagrama-titulo").textContent = titulo;
    $("diagrama-archivo").innerHTML = opcionesArchivos(archivos);
    $("diagrama-archivo").disabled = archivos.length < 2;
    $("diagrama-archivo").value = String(indice);
    $("modal-diagrama").hidden = false;
    visorModal.cargar(archivos[indice]);
  }

  function cerrarDiagrama() {
    $("modal-diagrama").hidden = true;
    document.body.classList.remove("visio-al-lado");
    visorModal.limpiar();
  }

  /** "Ver Visio original" of the mufa editor (migración Visio, fase 5): the mufa's Visio diagram in
   *  the full viewer, on the right half of the screen, next to the editor. */
  async function verVisioAlLado(nombre) {
    const limpio = String(nombre || "").trim();
    let res;
    try { res = await api.buscar_mufa(limpio); } catch (e) { res = { ok: false, error: String(e) }; }
    if (!res.ok) { mensaje(res.error, "error"); return false; }
    const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
    const m = res.resultados.find((x) => normal(x.nombre) === normal(limpio)) || res.resultados[0];
    if (!m || !m.diagramas) { mensaje(`${limpio}: no tiene diagrama Visio`, "error"); return false; }
    await seleccionarMufa(m);
    if (!diagramaActual || !diagramaActual.archivos.length) return false;
    document.body.classList.add("visio-al-lado");
    abrirPantallaCompleta();
    return true;
  }

  function conectarDiagrama() {
    visorPanel = crearVisor({ lienzo: "pd-lienzo", img: "pd-img", anillo: "pd-anillo", estado: "pd-estado" });
    visorModal = crearVisor({ lienzo: "diagrama-lienzo", img: "diagrama-img", anillo: "diagrama-anillo",
                              estado: "diagrama-estado", ruta: "diagrama-ruta" });
    $("pd-mas").addEventListener("click", () => visorPanel.zoom(1.4));
    $("pd-menos").addEventListener("click", () => visorPanel.zoom(1 / 1.4));
    $("pd-ajustar").addEventListener("click", () => visorPanel.ajustar());
    $("pd-ubicar").addEventListener("click", () => {
      if (!visorPanel.ubicar()) mensaje("No se encontró la mufa dentro de este diagrama");
    });
    $("pd-pantalla").addEventListener("click", abrirPantallaCompleta);
    $("pd-archivo").addEventListener("change", (e) => {
      diagramaActual.indice = Number(e.target.value);
      visorPanel.cargar(diagramaActual.archivos[diagramaActual.indice]);
    });
    $("diagrama-cerrar").addEventListener("click", cerrarDiagrama);
    $("diagrama-mas").addEventListener("click", () => visorModal.zoom(1.4));
    $("diagrama-menos").addEventListener("click", () => visorModal.zoom(1 / 1.4));
    $("diagrama-ajustar").addEventListener("click", () => visorModal.ajustar());
    $("diagrama-ubicar").addEventListener("click", () => {
      if (!visorModal.ubicar()) mensaje("No se encontró la mufa dentro de este diagrama");
    });
    $("diagrama-archivo").addEventListener("change", (e) => {
      visorModal.cargar(diagramaActual.archivos[Number(e.target.value)]);
    });
    $("modal-diagrama").addEventListener("click", (e) => { if (e.target === $("modal-diagrama")) cerrarDiagrama(); });
    conectarTirador();
  }

  /** Drag the panel's left edge to change its width (one width for the diagram, one for the rest). */
  function conectarTirador() {
    const tirador = $("panel-tirador");
    let activo = false;
    tirador.addEventListener("pointerdown", (e) => {
      activo = true;
      tirador.setPointerCapture(e.pointerId);
      tirador.classList.add("activo");
    });
    tirador.addEventListener("pointermove", (e) => {
      if (!activo) return;
      const ancho = Math.round(Math.min(Math.max(window.innerWidth - e.clientX - 10, 300), window.innerWidth * 0.85));
      const variable = $("panel").classList.contains("ancho") ? "--ancho-panel-diagrama" : "--ancho-panel";
      document.documentElement.style.setProperty(variable, `${ancho}px`);
      actualizarOcupado();
    });
    const soltar = () => { activo = false; tirador.classList.remove("activo"); };
    tirador.addEventListener("pointerup", soltar);
    tirador.addEventListener("pointercancel", soltar);
  }

  // ------------------------------------------------------------------ buscador de mufas
  const busqueda = { temporizador: null, pedido: 0, resultados: [], marcado: -1 };

  function ocultarResultados() { $("buscar-resultados").hidden = true; busqueda.marcado = -1; }
  function mostrarResultados(html) { $("buscar-resultados").innerHTML = html; $("buscar-resultados").hidden = false; }

  async function buscarMufa(texto) {
    const pedido = ++busqueda.pedido;
    if (texto.trim().length < 2) { $("buscar-spinner").hidden = true; ocultarResultados(); return; }
    $("buscar-spinner").hidden = false;
    let res;
    try { res = await api.buscar_mufa(texto); } catch (e) { res = { ok: false, error: String(e) }; }
    if (pedido !== busqueda.pedido) return;          // an older search answering late
    $("buscar-spinner").hidden = true;
    if (!res.ok) { mostrarResultados(`<li class="vacio">${esc(res.error)}</li>`); return; }
    busqueda.resultados = res.resultados;
    busqueda.marcado = -1;
    mostrarResultados(res.resultados.length ? res.resultados.map((m, i) =>
      `<li data-i="${i}" role="option"><b>${esc(m.nombre)}</b><span class="det">${esc(m.tipo)}` +
      `${m.zona ? " · " + esc(m.zona) : ""} · ${m.diagramas} diagrama(s)` +
      `${m.lat === null ? ' · <span class="sin-coord">sin coordenadas</span>' : ""}</span></li>`).join("")
      : `<li class="vacio">Ninguna mufa con ese nombre</li>`);
  }

  function marcarResultado(i) {
    const items = document.querySelectorAll("#buscar-resultados li[data-i]");
    if (!items.length) return;
    busqueda.marcado = (i + items.length) % items.length;
    items.forEach((li) => li.classList.toggle("marcado", Number(li.dataset.i) === busqueda.marcado));
    items[busqueda.marcado].scrollIntoView({ block: "nearest" });
  }

  async function seleccionarMufa(m) {
    ocultarResultados();
    $("buscar-mufa").value = m.nombre;
    $("buscar-mufa").blur();
    mensaje(`Cargando ${m.nombre}…`, "cargando");
    let res;
    try { res = await api.mufa(m.id); } catch (e) { res = { ok: false, error: String(e) }; }
    if (!res.ok) { mensaje(res.error, "error"); return; }
    const d = res.mufa;
    mostrarDiagrama(d.nombre, htmlInfoMufa(d), (d.archivos || []).filter((a) => a.diagrama));
    capas.busqueda.clearLayers();
    if (tieneCoord(d)) {
      L.marker([d.lat, d.lon], { icon: ICONOS.buscada, zIndexOffset: 1200 })
        .bindTooltip(esc(d.nombre), { permanent: true, direction: "top", className: "etiqueta buscada" })
        .bindPopup(() => popupHtml({ nombre: d.nombre, tipo: `Mufa buscada · ${d.tipo || ""}`,
                                     filas: [["Zona", d.zona], ["Propietario", d.propietario]] }, L.latLng(d.lat, d.lon)))
        .addTo(capas.busqueda);
      // centre it in the part of the map the (now wider) panel does not cover
      mapa.setView([d.lat, d.lon], Math.max(mapa.getZoom(), 18), { animate: false });
      mapa.panBy([($("panel").offsetWidth + 20) / 2, 0], { animate: false });
      mensaje(`${d.nombre} · ${coordTexto(d.lat, d.lon)}`, "ok");
    } else {
      mensaje(`${d.nombre}: sin coordenadas en la base, no se puede ubicar en el mapa`, "error");
    }
  }

  /** Enter / double click on an EXISTING mufa of the network (KMZ "Lugares" or Visio nodes):
   *  its Visio diagram in the panel, with the same viewer as the search box (selector if several). */
  async function abrirDiagramaPorNombre(nombre) {
    const limpio = String(nombre || "").trim();
    if (!limpio) return;
    mensaje(`Buscando el diagrama de ${limpio}…`, "cargando");
    let res;
    try { res = await api.buscar_mufa(limpio); } catch (e) { res = { ok: false, error: String(e) }; }
    if (!res.ok) { mensaje(res.error, "error"); return; }
    const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
    const m = res.resultados.find((x) => normal(x.nombre) === normal(limpio)) || res.resultados[0];
    if (!m) { mensaje(`${limpio}: no está en los diagramas Visio`, "error"); return; }
    if (!m.diagramas) { mensaje(`${m.nombre}: no tiene diagrama Visio`, "error"); return; }
    seleccionarMufa(m);
  }

  function conectarBuscador() {
    const campo = $("buscar-mufa");
    campo.addEventListener("input", () => {
      clearTimeout(busqueda.temporizador);
      busqueda.temporizador = setTimeout(() => buscarMufa(campo.value), 250);
    });
    campo.addEventListener("focus", () => { if (busqueda.resultados.length && campo.value.trim().length >= 2) $("buscar-resultados").hidden = false; });
    campo.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        marcarResultado(busqueda.marcado + (e.key === "ArrowDown" ? 1 : -1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const m = busqueda.resultados[busqueda.marcado >= 0 ? busqueda.marcado : 0];
        if (m && !$("buscar-resultados").hidden) seleccionarMufa(m);
      } else if (e.key === "Escape") {
        ocultarResultados();
        campo.blur();
      }
    });
    $("buscar-resultados").addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); seleccionarMufa(busqueda.resultados[Number(li.dataset.i)]); }
    });
    L.DomEvent.disableClickPropagation($("buscador"));
    L.DomEvent.disableScrollPropagation($("buscador"));
  }

  // ------------------------------------------------------------------ cálculo
  async function generar() {
    if (calculando || !api) return;
    ocultarHistorial();
    const texto = $("coord").value.trim();
    if (!texto) {
      mensaje("Pegue una coordenada: latitud, longitud (ejemplo: 12.153328, -86.263438)", "error");
      $("coord").focus();
      return;
    }
    calculando = true;
    $("generar").disabled = true;
    mensaje("Calculando…", "cargando");
    let res;
    try {
      res = await api.calcular(texto);
    } catch (e) {
      res = { ok: false, error: "Error al comunicarse con Python: " + e };
    } finally {
      calculando = false;
      $("generar").disabled = false;
    }
    if (res.coordenada) {
      agregarHistorial(res.coordenada);
      $("coord").value = res.coordenada;
    }
    if (!res.ok) {
      mensaje(res.error, "error");
      return;
    }
    datos = res.datos;
    postesMarcados.clear();       // marks belong to the previous route
    paradaActiva = null;
    try {
      dibujar(datos);
      renderPanel();
      mensaje(datos.ruta.aproximada ? "Ruta aproximada (sin Google)" : "Ruta generada",
              datos.ruta.aproximada ? "error" : "ok");
    } catch (e) {
      console.error(e);
      mensaje("No se pudo dibujar la ruta: " + e.message, "error");
    }
    iniciarEstimacion();          // after drawing: the map never waits for the Excel
  }

  function limpiar() {
    if (med.activo) cancelarMedicion();
    limpiarCapas();
    datos = null;
    postesMarcados.clear();
    reiniciarEstimacion();
    paradaActiva = null;
    $("coord").value = "";
    renderPanel();
    mensaje("Pegue una coordenada y presione Enter");
    $("coord").focus();
  }

  // ------------------------------------------------------------------ historial
  let marcadoHist = -1;
  function agregarHistorial(texto) {
    const i = historial.indexOf(texto);
    if (i >= 0) historial.splice(i, 1);
    historial.unshift(texto);
    historial.length = Math.min(historial.length, MAX_HISTORIAL);
  }
  function mostrarHistorial() {
    const lista = $("historial");
    lista.innerHTML = historial.length
      ? historial.map((h, i) => `<li data-i="${i}" class="${i === marcadoHist ? "marcado" : ""}">${esc(h)}</li>`).join("")
      : `<li class="vacio">Sin coordenadas todavía</li>`;
    lista.hidden = false;
  }
  function ocultarHistorial() { $("historial").hidden = true; marcadoHist = -1; }
  function elegirHistorial(i) {
    if (i < 0 || i >= historial.length) return;
    $("coord").value = historial[i];
    ocultarHistorial();
    $("coord").focus();
  }

  // ------------------------------------------------------------------ menú de clic derecho
  let latlngMenu = null;
  function alClicDerecho(e) {
    if (med.activo) { terminarMedicion(); return; }
    latlngMenu = e.latlng;
    const menu = $("menu");
    menu.querySelectorAll(".menu-titulo").forEach((n) => n.remove());
    menu.insertAdjacentHTML("afterbegin",
      `<li class="menu-titulo">${coordTexto(e.latlng.lat, e.latlng.lng)}</li>`);
    menu.hidden = false;
    const { clientX: x, clientY: y } = e.originalEvent;
    menu.style.left = Math.min(x, window.innerWidth - menu.offsetWidth - 4) + "px";
    menu.style.top = Math.min(y, window.innerHeight - menu.offsetHeight - 4) + "px";
  }
  function ocultarMenu() { $("menu").hidden = true; }
  function accionMenu(accion) {
    if (!latlngMenu) return;
    const texto = coordTexto(latlngMenu.lat, latlngMenu.lng);
    if (accion === "usar") {
      $("coord").value = texto;
      $("coord").focus();
      mensaje("Coordenada lista: presione Enter o Generar ruta");
    } else if (accion === "copiar") {
      copiar(texto, `Coordenada copiada: ${texto}`);
    } else if (accion === "medir") {
      iniciarMedicion(latlngMenu);
    }
    ocultarMenu();
  }

  // ------------------------------------------------------------------ medición
  const med = { activo: false, puntos: [], capa: null, linea: null, guia: null, iman: null, color: COLORES.medida };
  const medidas = [];
  let siguienteMedida = 1;
  // Each new measurement takes the next color (readable on the satellite imagery), so several
  // measurements can be told apart; "＋ Nueva medida" (or N) saves the current one and starts another.
  const COLORES_MEDIDA = [COLORES.medida, "#FF4FD8", "#B6FF00", "#FFB000", "#9D8CFF", "#00FF9C", "#FF6B4A", "#FFFFFF"];
  let siguienteColor = 0;

  function distanciaTotal(puntos) {
    let total = 0;
    for (let i = 1; i < puntos.length; i++) total += puntos[i - 1].distanceTo(puntos[i]);
    return total;
  }

  function imantar(latlng) {
    const p = mapa.latLngToContainerPoint(latlng);
    let mejor = null, mejorPx = IMAN_PX;
    const candidatos = puntosIman.concat(...medidas.map((m) => m.puntos),
                                         ...Object.values(estadoRed).map((e) => e.puntos));
    for (const q of candidatos) {
      const px = p.distanceTo(mapa.latLngToContainerPoint(q));
      if (px < mejorPx) { mejor = q; mejorPx = px; }
    }
    return mejor ? L.latLng(mejor.lat, mejor.lng) : latlng;
  }

  function iniciarMedicion(desde) {
    if (med.activo) return;
    ocultarMenu();
    med.activo = true;
    med.puntos = [];
    med.color = COLORES_MEDIDA[siguienteColor++ % COLORES_MEDIDA.length];
    $("medir").classList.add("activo");
    $("medir").textContent = "✔ Terminar medida";
    $("nueva-medida").hidden = false;
    $("medir-ayuda").style.borderLeftColor = med.color;
    mapa.getContainer().classList.add("midiendo");
    mapa.doubleClickZoom.disable();
    $("medir-ayuda").hidden = false;
    med.capa = L.layerGroup().addTo(mapa);
    med.linea = L.polyline([], { color: med.color, weight: 4, interactive: false }).addTo(med.capa);
    med.guia = L.polyline([], { color: med.color, weight: 2, dashArray: "5 6", interactive: false }).addTo(med.capa);
    med.iman = L.circleMarker([0, 0], { radius: 9, color: med.color, weight: 2, fillOpacity: 0.25, interactive: false });
    if (desde) agregarPunto(imantar(desde));
    actualizarAyuda(null);
  }

  function agregarPunto(latlng) {
    if (!med.activo) return;
    const ultimo = med.puntos[med.puntos.length - 1];
    // The two clicks of a double click land on the same spot: ignore the repeat.
    if (ultimo && mapa.latLngToContainerPoint(ultimo).distanceTo(mapa.latLngToContainerPoint(latlng)) < 4) return;
    med.puntos.push(latlng);
    med.linea.setLatLngs(med.puntos);
    L.circleMarker(latlng, { radius: 4, color: "#003a40", weight: 2, fillColor: med.color, fillOpacity: 1,
                             interactive: false }).addTo(med.capa);
    actualizarAyuda(null);
  }

  function quitarUltimoPunto() {
    if (!med.puntos.length) return;
    med.puntos.pop();
    const vertices = [];
    med.capa.eachLayer((l) => { if (l instanceof L.CircleMarker && l !== med.iman) vertices.push(l); });
    if (vertices.length) med.capa.removeLayer(vertices[vertices.length - 1]);
    med.linea.setLatLngs(med.puntos);
    med.guia.setLatLngs([]);
    actualizarAyuda(null);
  }

  function actualizarAyuda(cursor) {
    const total = distanciaTotal(med.puntos);
    let texto = med.puntos.length ? `Total: ${metros(total)}` : "Haga clic en el primer punto";
    if (cursor && med.puntos.length) {
      const tramo = med.puntos[med.puntos.length - 1].distanceTo(cursor);
      texto = `Tramo: ${metros(tramo)} · Total: ${metros(total + tramo)}`;
    }
    $("medir-total").textContent = texto;
  }

  function alMoverMouse(e) {
    if (!med.activo) return;
    const punto = imantar(e.latlng);
    if (punto !== e.latlng) { med.iman.setLatLng(punto); if (!med.capa.hasLayer(med.iman)) med.iman.addTo(med.capa); }
    else if (med.capa.hasLayer(med.iman)) med.capa.removeLayer(med.iman);
    if (med.puntos.length) med.guia.setLatLngs([med.puntos[med.puntos.length - 1], punto]);
    actualizarAyuda(punto);
  }

  function alClicMapa(e) {
    ocultarMenu();
    ocultarHistorial();
    if (med.activo) agregarPunto(imantar(e.latlng));
  }

  function salirModoMedicion() {
    med.activo = false;
    if (med.capa) mapa.removeLayer(med.capa);
    med.capa = med.linea = med.guia = med.iman = null;
    med.puntos = [];
    $("medir").classList.remove("activo");
    $("medir").innerHTML = "&#x1F4CF; Medir";
    $("nueva-medida").hidden = true;
    mapa.getContainer().classList.remove("midiendo");
    mapa.doubleClickZoom.enable();
    $("medir-ayuda").hidden = true;
  }

  function cancelarMedicion() {
    salirModoMedicion();
    mensaje("Medición cancelada");
  }

  function terminarMedicion() {
    if (!med.activo) return;
    const puntos = med.puntos.slice(), color = med.color;
    salirModoMedicion();
    if (puntos.length < 2) { mensaje("Medición cancelada: se necesitan al menos dos puntos"); return; }
    const medida = crearMedida(puntos, color);
    mensaje(`${medida.nombre}: ${metros(medida.total)}`, "ok");
  }

  /** "＋ Nueva medida" / N: keep the measurement in progress (if it has 2+ points) and start the next one
   *  right away, in the next color; the earlier measurements stay on the map. */
  function nuevaMedida() {
    if (!med.activo) { iniciarMedicion(null); return; }
    const puntos = med.puntos.slice(), color = med.color;
    salirModoMedicion();
    const medida = puntos.length >= 2 ? crearMedida(puntos, color) : null;
    iniciarMedicion(null);
    mensaje(medida ? `${medida.nombre}: ${metros(medida.total)} guardada · nueva medida en curso`
                   : "Nueva medida en curso", "ok");
  }

  function crearMedida(puntos, color = COLORES.medida) {
    const id = siguienteMedida++;
    const medida = { id, nombre: `Medida ${id}`, puntos, color, total: distanciaTotal(puntos), capa: L.featureGroup() };
    L.polyline(puntos, { color: "#003a40", weight: 7, opacity: 0.7, interactive: false }).addTo(medida.capa);
    const linea = L.polyline(puntos, { color, weight: 4 }).addTo(medida.capa);
    puntos.forEach((p) => L.circleMarker(p, { radius: 4, color: "#003a40", weight: 2, fillColor: color,
                                              fillOpacity: 1, interactive: false }).addTo(medida.capa));
    if (puntos.length > 2) {                                    // length of every segment
      for (let i = 1; i < puntos.length; i++) {
        const medio = L.latLng((puntos[i - 1].lat + puntos[i].lat) / 2, (puntos[i - 1].lng + puntos[i].lng) / 2);
        L.marker(medio, { icon: iconoVacio(), interactive: false, keyboard: false })
          .bindTooltip(metros(puntos[i - 1].distanceTo(puntos[i])),
                       { permanent: true, direction: "center", className: "tooltip-tramo" })
          .addTo(medida.capa);
      }
    }
    L.marker(puntos[puntos.length - 1], { icon: iconoVacio(), interactive: false, keyboard: false })
      .bindTooltip(`<span class="muestra-medida" style="background:${color}"></span>${esc(medida.nombre)}: ${metros(medida.total)}`,
                   { permanent: true, direction: "right", offset: [8, 0], className: "tooltip-medida" })
      .addTo(medida.capa);
    linea.on("click", (e) => {
      if (med.activo) return;
      L.DomEvent.stopPropagation(e);
      const tramos = puntos.slice(1).map((p, i) => `<dt>Tramo ${i + 1}</dt><dd>${metros(puntos[i].distanceTo(p))}</dd>`).join("");
      L.popup({ maxWidth: 300 }).setLatLng(e.latlng).setContent(
        `<div class="popup"><h3>${esc(medida.nombre)}</h3><div class="tipo">Medida propia</div>
         <dl><dt>Total</dt><dd><b>${metros(medida.total)}</b></dd>${tramos}</dl>
         <div class="acciones">
           <button type="button" class="btn btn-chico" data-copiar-medida="${id}">Copiar medida</button>
           <button type="button" class="btn btn-chico" data-quitar-medida="${id}">Borrar</button>
         </div></div>`).openOn(mapa);
    });
    medida.capa.addTo(capas.medidas);
    medidas.push(medida);
    $("borrar-medidas").disabled = false;
    renderPanel();
    return medida;
  }

  function quitarMedida(id) {
    const i = medidas.findIndex((m) => m.id === id);
    if (i < 0) return;
    capas.medidas.removeLayer(medidas[i].capa);
    medidas.splice(i, 1);
    mapa.closePopup();
    $("borrar-medidas").disabled = !medidas.length;
    renderPanel();
  }

  function borrarMedidas() {
    capas.medidas.clearLayers();
    medidas.length = 0;
    siguienteMedida = 1;
    siguienteColor = med.activo ? 1 : 0;        // the one in progress keeps the first color
    $("borrar-medidas").disabled = true;
    renderPanel();
    mensaje("Medidas borradas");
  }

  // ------------------------------------------------------------------ presupuestos
  // Same budget generation as POST /presupuesto (Python: visor_rutas/presupuesto_visor.py), saved
  // in output/visor and never sent. Amounts come from the workbook as LibreOffice computed it.
  const MONEDA = "C$";                // the template's currency (number format _-"C$"* #,##0.00_-)
  const dinero = (v) => (v === null || v === undefined ? "—" : `${MONEDA} ${num(v, 2)}`);
  const cantidad = (v) => (v === null || v === undefined ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }));
  const CAMPOS_FORM = ["ticket_id", "coordenada", "client_name", "client_code", "sales_exec", "contact_name",
                       "contact_phone", "service_type", "medium", "bandwidth", "technology", "odf_rack_ports", "raw_comment"];
  const pres = { config: null, cargaConfig: null, actual: null, hoja: "Presupuesto", html: new Map(), pdfUrl: null,
                 pdfDe: null, zoom: 1, generando: false };
  const estim = { token: 0, estado: "vacio", datos: null, error: null };
  const totalDe = (resultado) => ((resultado.resumen.totales || []).find((t) => t.clave === "total") || {}).valor;

  // --- vistas (menú lateral: menu.js)
  // "mapa" is the map itself; the other views (class "vista", data-vista) cover it. The network
  // module's views are in redes/*.js (window.RedesVistas).
  function mostrarVista(nombre) {
    if (nombre === "configuracion") { abrirConfiguracion(false); return; }
    document.querySelectorAll(".vista").forEach((v) => { v.hidden = v.dataset.vista !== nombre; });
    if (window.Menu) Menu.marcarActivo(nombre);
    if (nombre !== "mapa") {
      if (med.activo) terminarMedicion();
      ocultarMenu();
    }
    if (nombre === "presupuesto") {
      cargarConfigPresupuesto();
      if (!$("f-coordenada").value) usarCoordenadaMapa(false);
    } else if (nombre === "mapa" && mapa) {
      mapa.invalidateSize();
    }
    if (window.RedesVistas && window.RedesVistas[nombre]) window.RedesVistas[nombre].mostrar();
  }

  // --- formulario "Generar presupuesto"
  function cargarConfigPresupuesto() {
    // One request shared by every caller: the options must be in place before a form is filled.
    if (!pres.cargaConfig && api) {
      pres.cargaConfig = (async () => {
        try {
          const r = await api.presupuesto_config();
          if (r && r.ok) {
            pres.config = r;
            $("f-service_type").innerHTML = r.servicios.map((s) => `<option>${esc(s)}</option>`).join("");
            $("f-medium").innerHTML = r.medios.map((m) => `<option>${esc(m)}</option>`).join("");
            if (!$("f-bandwidth").value) $("f-bandwidth").value = r.estimacion.bandwidth;
            if (!r.libreoffice) vpEstado("LibreOffice no está disponible: el Excel se genera igual y los totales se ven al abrirlo en Excel.", "error");
          } else {
            pres.cargaConfig = null;
          }
        } catch (e) {
          pres.cargaConfig = null;
          vpEstado("No se pudo leer la configuración: " + e, "error");
        }
        return pres.config;
      })();
    }
    return pres.cargaConfig || Promise.resolve(pres.config);
  }
  function usarCoordenadaMapa(avisar = true) {
    const texto = datos ? coordTexto(datos.cliente.lat, datos.cliente.lon) : $("coord").value.trim();
    if (texto) $("f-coordenada").value = texto;
    else if (avisar) vpEstado("No hay coordenada en el mapa todavía", "error");
  }
  function leerFormulario() {
    const campos = {};
    CAMPOS_FORM.forEach((k) => { campos[k] = $("f-" + k).value; });
    return campos;
  }
  function llenarFormulario(campos) {
    CAMPOS_FORM.forEach((k) => {
      if (campos[k] === undefined || campos[k] === null) return;
      const campo = $("f-" + k);
      if (campo.tagName === "SELECT" && ![...campo.options].some((o) => o.value === String(campos[k]))) {
        campo.insertAdjacentHTML("beforeend", `<option>${esc(campos[k])}</option>`);
      }
      campo.value = campos[k];
    });
  }
  function marcarErrores(errores) {
    CAMPOS_FORM.forEach((k) => {
      const caja = $("f-" + k).closest(".vp-campo");
      const texto = errores && errores[k];
      caja.classList.toggle("invalido", !!texto);
      caja.querySelector("small").textContent = texto || "";
    });
    const primero = errores && CAMPOS_FORM.find((k) => errores[k]);
    if (primero) $("f-" + primero).focus();
  }
  function vpEstado(texto, tipo = "") {
    const caja = $("vp-estado");
    caja.className = "vp-estado" + (tipo ? " " + tipo : "");
    caja.innerHTML = (tipo === "cargando" ? `<span class="spinner"></span> ` : "") + esc(texto);
  }
  function aviso(texto, tipo) {
    if (!$("vista-presupuesto").hidden) vpEstado(texto, tipo); else mensaje(texto, tipo);
  }

  // The poles marked on the map apply only to a budget of the same client coordinate as the map's route.
  function marcasParaFormulario(coordenada) {
    if (!datos || !postesMarcados.size) return [];
    const partes = String(coordenada || "").trim().replace(/^[([]|[)\]]$/g, "").split(/[,;\s]+/).filter(Boolean);
    if (partes.length !== 2) return [];
    const [lat, lon] = partes.map(Number);
    const igual = (a, b) => Math.abs(a - b) < 5e-7;
    return igual(lat, datos.cliente.lat) && igual(lon, datos.cliente.lon) ? metrosMarcados() : [];
  }

  async function generarPresupuesto(ev) {
    if (ev) ev.preventDefault();
    if (pres.generando || !api) return;
    await cargarConfigPresupuesto();
    marcarErrores(null);
    pres.generando = true;
    $("vp-generar").disabled = true;
    const campos = leerFormulario();
    const marcas = marcasParaFormulario(campos.coordenada);
    if (marcas.length) campos.postes_existentes_m = marcas;
    vpEstado("Generando presupuesto… (ruta, mapa y LibreOffice: puede tardar 10–40 s)" +
             (marcas.length ? ` con ${marcas.length} poste(s) nuevo(s) marcados como existentes` : ""), "cargando");
    let r;
    try {
      r = await api.generar_presupuesto(campos);
    } catch (e) {
      r = { ok: false, error: "Error al comunicarse con Python: " + e };
    } finally {
      pres.generando = false;
      $("vp-generar").disabled = false;
    }
    if (!r.ok) { marcarErrores(r.errores); vpEstado(r.error, "error"); return; }
    vpEstado(`Presupuesto generado: ${r.resultado.nombre} (no enviado)`, "ok");
    hist.cargado = false;                    // the history reads the folder again next time
    mostrarResultado(r.resultado);
  }

  // --- historial: presupuestos guardados por el visor (output/visor; en remoto, los del servidor)
  const hist = { lista: [], cargado: false, seleccionado: null };

  function mostrarPestanaVp(nombre) {
    document.querySelectorAll(".vp-tab").forEach((b) => b.classList.toggle("activa", b.dataset.vpTab === nombre));
    $("vp-form").hidden = nombre !== "nuevo";
    $("vp-historial").hidden = nombre !== "historial";
    if (nombre === "historial" && !hist.cargado) cargarHistorial();
  }

  async function cargarHistorial() {
    $("vp-hist-lista").innerHTML = `<li class="vacio"><span class="spinner"></span> Leyendo los presupuestos…</li>`;
    let r;
    try { r = await api.historial_presupuestos(); } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r.ok) { $("vp-hist-lista").innerHTML = `<li class="vacio error">${esc(r.error)}</li>`; return; }
    hist.lista = r.presupuestos;
    hist.cargado = true;
    pintarHistorial();
  }

  function fechaCortaHora(iso) {
    const d = new Date(iso);
    return isNaN(d) ? String(iso || "") : d.toLocaleString("es-NI", { dateStyle: "short", timeStyle: "short" });
  }

  function pintarHistorial() {
    const filtro = $("vp-hist-filtro").value.trim().toLowerCase();
    const conAprox = $("vp-hist-estimaciones").checked;
    const visibles = hist.lista.filter((p) => (conAprox || !p.estimacion)
      && (!filtro || `${p.cliente} ${p.coordenada || ""} ${fechaCortaHora(p.fecha)} ${p.nombre}`.toLowerCase().includes(filtro)));
    $("vp-hist-lista").innerHTML = visibles.length ? visibles.map((p) => `<li data-hist="${esc(p.archivo)}"
        class="${hist.seleccionado === p.archivo ? "sel" : ""}" title="${esc(p.nombre)}">
        <b>${esc(p.cliente)}${p.estimacion ? `<span class="vp-hist-etiqueta">Aproximado</span>` : ""}</b>
        <span>${esc(fechaCortaHora(p.fecha))}${p.coordenada ? ` · ${esc(p.coordenada)}` : ""}</span></li>`).join("")
      : `<li class="vacio">${hist.lista.length ? "Ningún presupuesto coincide con el filtro" : "Todavía no hay presupuestos guardados por el visor"}</li>`;
  }

  async function abrirDelHistorial(archivo) {
    hist.seleccionado = archivo;
    pintarHistorial();
    vpEstado("Abriendo el presupuesto guardado…", "cargando");
    let r;
    try { r = await api.abrir_presupuesto_guardado(archivo); } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r.ok) { vpEstado(r.error, "error"); return; }
    mostrarResultado(r.resultado);
    vpEstado(`Presupuesto guardado: ${r.resultado.nombre}`, "ok");
  }

  // --- resultado: hojas del Excel, PDF y botones
  function mostrarResultado(resultado) {
    pres.actual = resultado;
    pres.html.clear();
    liberarPdf();
    $("vp-vacio").hidden = true;
    $("vp-contenido").hidden = false;
    const detalles = [resultado.calculado ? `TOTAL ${dinero(totalDe(resultado))}` : "Totales al abrir en Excel (falta LibreOffice)",
                      resultado.tecnologia ? String(resultado.tecnologia).toUpperCase() : null, resultado.tipo_cable,
                      resultado.metraje_final_m != null ? `${metros(resultado.metraje_final_m, 0)} de cable` : null,
                      resultado.postes_marcados ? `${resultado.postes_marcados} poste(s) marcado(s) como existente(s)` : null]
      .filter(Boolean).map(esc).join(" · ");
    $("vp-titulo").innerHTML = `<b>${esc(resultado.nombre)}</b><span class="nota">${detalles}</span>`;
    const conPdf = !pres.config || pres.config.libreoffice;
    $("vp-pestana-pdf").disabled = !conPdf;
    $("vp-guardar-pdf").disabled = !conPdf;
    $("vp-avisos").innerHTML = htmlAvisos(resultado);
    mostrarHoja("Presupuesto");
  }

  function htmlAvisos(r) {
    const avisos = r.avisos || [], p = r.pendientes || {};
    const pendientes = [...(p.campos || []).map((c) => `Campo a validar: ${c}`),
                        ...(p.items || []).map((i) => `Partida manual (queda en ${i.quantity}): ${i.item}`),
                        ...(p.postes ? [`${p.postes} poste(s) existente(s) a validar en campo`] : [])];
    if (!avisos.length && !pendientes.length) return "";
    return `<details ${avisos.length ? "open" : ""}><summary>Avisos (${avisos.length}) y pendientes de validación (${pendientes.length})</summary>` +
      (avisos.length ? `<ul class="vp-lista-avisos">${avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "") +
      (pendientes.length ? `<ul class="vp-lista-pendientes">${pendientes.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "") +
      `</details>`;
  }

  async function mostrarHoja(hoja) {
    const actual = pres.actual;
    if (!actual) return;
    pres.hoja = hoja;
    document.querySelectorAll(".vp-pestana").forEach((b) => b.classList.toggle("activa", b.dataset.hoja === hoja));
    const caja = $("vp-hoja"), marco = $("vp-pdf");
    if (hoja === "PDF") { caja.hidden = true; marco.hidden = false; await mostrarPdf(); return; }
    marco.hidden = true;
    caja.hidden = false;
    const clave = `${actual.archivo}|${hoja}`;
    if (!pres.html.has(clave)) {
      caja.innerHTML = `<p class="vacio"><span class="spinner"></span> Cargando la hoja…</p>`;
      let r;
      try {
        r = await api.hoja_excel(actual.archivo, hoja, actual.calculado);
      } catch (e) {
        r = { ok: false, error: String(e) };
      }
      if (pres.actual !== actual || pres.hoja !== hoja) return;
      if (!r.ok) { caja.innerHTML = `<p class="vacio error">${esc(r.error)}</p>`; return; }
      pres.html.set(clave, r.html);
    }
    caja.innerHTML = pres.html.get(clave);
    aplicarZoom();
  }
  function aplicarZoom() {
    const hoja = $("vp-hoja").querySelector(".hoja-excel");
    if (hoja) hoja.style.zoom = pres.zoom;
    $("vp-zoom-valor").textContent = `${Math.round(pres.zoom * 100)}%`;
  }

  function liberarPdf() {
    if (pres.pdfUrl) URL.revokeObjectURL(pres.pdfUrl);
    pres.pdfUrl = pres.pdfDe = null;
    $("vp-pdf").removeAttribute("src");
  }
  async function mostrarPdf() {
    const actual = pres.actual, marco = $("vp-pdf");
    if (pres.pdfDe === actual.archivo) return;
    const nota = (texto, color = "#5b6270") =>
      `<p style="font-family:Segoe UI,sans-serif;padding:16px;color:${color}">${esc(texto)}</p>`;
    marco.srcdoc = nota("Generando el PDF con LibreOffice…");
    let r;
    try {
      r = await api.pdf_presupuesto(actual.archivo);
    } catch (e) {
      r = { ok: false, error: String(e) };
    }
    if (pres.actual !== actual) return;
    if (!r.ok) { marco.srcdoc = nota(r.error, "#b00020"); return; }
    const bytes = Uint8Array.from(atob(r.base64), (c) => c.charCodeAt(0));
    liberarPdf();
    pres.pdfUrl = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    pres.pdfDe = actual.archivo;
    marco.removeAttribute("srcdoc");
    marco.src = pres.pdfUrl;
  }

  async function guardarComo(archivo, tipo) {
    if (!archivo) return;
    aviso(tipo === "pdf" ? "Preparando el PDF…" : "Elija dónde guardar el Excel…", "cargando");
    let r;
    try {
      r = await api.guardar_como(archivo, tipo);
    } catch (e) {
      r = { ok: false, error: String(e) };
    }
    if (r.ok) aviso(`Guardado en ${r.ruta}`, "ok");
    else if (r.cancelado) aviso("Guardado cancelado");
    else aviso(r.error || "No se pudo guardar", "error");
  }
  async function abrirEnExcel(archivo) {
    const r = await api.abrir_excel(archivo);
    if (!r.ok) aviso(r.error, "error");
  }
  async function abrirCarpeta(archivo) {
    const r = await api.abrir_carpeta(archivo || "");
    if (!r.ok) aviso(r.error, "error");
  }

  // --- presupuesto aproximado (pestaña "Presupuesto" del panel)
  let temporizadorEstim = null;
  function reiniciarEstimacion() {
    clearTimeout(temporizadorEstim);
    estim.token++;
    Object.assign(estim, { estado: "vacio", datos: null, error: null });
    renderEstimacion();
  }
  // After marking poles: wait for the clicks to stop, then one recalculation with all the marks.
  function programarEstimacion() {
    clearTimeout(temporizadorEstim);
    if (!datos || datos.ruta.aproximada) return;
    estim.token++;                                  // an estimate still on its way is dropped
    Object.assign(estim, { estado: "calculando", datos: null, error: null });
    renderEstimacion();
    temporizadorEstim = setTimeout(iniciarEstimacion, 900);
  }
  async function iniciarEstimacion() {
    clearTimeout(temporizadorEstim);
    const token = ++estim.token;
    if (!datos || !api) return;
    if (datos.ruta.aproximada) {
      Object.assign(estim, { estado: "error", datos: null,
                             error: "Sin ruta de Google no hay presupuesto aproximado: el presupuesto necesita la ruta por calle." });
      renderEstimacion();
      return;
    }
    Object.assign(estim, { estado: "calculando", datos: null, error: null });
    renderEstimacion();
    let r;
    try {
      const marcas = metrosMarcados();
      r = await api.estimar_presupuesto(datos.cliente.lat, datos.cliente.lon, datos.ruta.metraje_final_m,
                                        marcas.length ? marcas : null);
    } catch (e) {
      r = { ok: false, error: "Error al comunicarse con Python: " + e };
    }
    if (token !== estim.token) return;              // a newer route was generated (or cleared) meanwhile
    if (r.ok) {
      Object.assign(estim, { estado: "listo", datos: r });
      if (!calculando) mensaje(r.resultado.calculado
        ? `Presupuesto aproximado: ${dinero(totalDe(r.resultado))} (pestaña Presupuesto)`
        : "Presupuesto aproximado listo (montos al abrir en Excel)", "ok");
    } else {
      Object.assign(estim, { estado: "error", error: r.error });
    }
    renderEstimacion();
  }

  function htmlSeccion(seccion) {
    const lineas = seccion.lineas.map((l) => `<tr><td>${esc(l.descripcion)}</td>
        <td class="num">${cantidad(l.cantidad)}${l.unidad ? ` <span class="nota">${esc(l.unidad)}</span>` : ""}</td>
        <td class="num">${dinero(l.total)}</td></tr>`).join("");
    return `<details class="pres-seccion"><summary><span>${esc(seccion.nombre)}
        <span class="nota">(${seccion.lineas.length} línea${seccion.lineas.length === 1 ? "" : "s"})</span></span>
        <b>${dinero(seccion.total)}</b></summary>
      <table class="pres-lineas"><thead><tr><th>Descripción</th><th>Cant.</th><th>Total</th></tr></thead>
        <tbody>${lineas || `<tr><td colspan="3" class="nota">Sin líneas con cantidad</td></tr>`}</tbody></table>
      ${seccion.por_formula ? `<div class="nota">${seccion.por_formula} cantidad(es) las calcula la plantilla: se ven al abrir en Excel.</div>` : ""}
      </details>`;
  }

  function renderEstimacion() {
    $("pestana-pres-spinner").hidden = estim.estado !== "calculando";
    const caja = $("presupuesto-aprox");
    if (estim.estado === "vacio") {
      caja.innerHTML = `<p class="vacio">Genere una ruta: el presupuesto aproximado se calcula solo, con valores por defecto
        (solo la coordenada).<br>Para un presupuesto con los datos del cliente use ☰ → <b>Generar presupuesto</b>.</p>`;
      return;
    }
    if (estim.estado === "calculando") {
      caja.innerHTML = `<p class="vacio cargando"><span class="spinner"></span> Calculando presupuesto aproximado…
        <span class="nota">(mapa del Excel y LibreOffice: 10–30 s; el mapa ya se puede usar)</span></p>`;
      return;
    }
    if (estim.estado === "error") {
      caja.innerHTML = tarjeta("Presupuesto aproximado", `<span class="etiqueta-aprox">Aproximado – no enviado</span>
        <div class="nota error">${esc(estim.error)}</div>
        <div class="acciones-pres"><button type="button" class="btn btn-chico" data-pres="ajustar">Ajustar datos</button></div>`);
      return;
    }
    const { supuestos: s, resultado: r } = estim.datos;
    const totales = filas((r.resumen.totales || []).map((t) =>
      [t.etiqueta, t.clave === "total" ? `<b>${dinero(t.valor)}</b>` : dinero(t.valor)]));
    caja.innerHTML = tarjeta("Presupuesto aproximado",
      `<span class="etiqueta-aprox">Aproximado – no enviado</span>
       <div class="pres-total">${r.calculado ? dinero(totalDe(r)) : "Montos: al abrir en Excel"}</div>` +
      filas([["Servicio", esc(s.service_type)], ["Velocidad", esc(s.bandwidth)],
             ["Tecnología", esc(String(s.technology || "").toUpperCase())], ["Cable", esc(s.cable)],
             ["Metraje final", `${metros(s.metraje_final_m, 0)} <span class="nota">(${s.metraje_final_m <= s.umbral_m ? "≤" : ">"} ${metros(s.umbral_m, 0)})</span>`],
             ["Postes marcados", s.postes_marcados ? `${s.postes_marcados} <span class="nota">(cobrados como existentes)</span>` : null]]) +
      (r.calculado ? "" : `<div class="nota aviso-pres">LibreOffice no está disponible: se muestran las cantidades;
         los montos requieren LibreOffice (o abrir el Excel).</div>`) +
      `<div class="pres-secciones">${r.resumen.secciones.map(htmlSeccion).join("")}</div>` +
      (r.calculado ? `<div class="pres-totales">${totales}</div>` : "") +
      `<div class="acciones-pres">
         <button type="button" class="btn btn-chico" data-pres="descargar">Descargar Excel</button>
         <button type="button" class="btn btn-chico" data-pres="detalle">Ver detalle</button>
         <button type="button" class="btn btn-chico" data-pres="ajustar">Ajustar datos</button>
       </div>` +
      (r.avisos.length ? `<details class="pres-avisos"><summary>Avisos (${r.avisos.length})</summary><ul>${
        r.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""), "presupuesto");
  }

  async function accionEstimacion(e) {
    const boton = e.target.closest("[data-pres]");
    if (!boton) return;
    const accion = boton.dataset.pres, d = estim.datos;
    if (accion === "descargar" && d) {
      guardarComo(d.resultado.archivo, "xlsx");
    } else if (accion === "detalle" && d) {
      mostrarVista("presupuesto");
      mostrarPestanaVp("nuevo");
      await cargarConfigPresupuesto();
      llenarFormulario({ ...d.campos, ticket_id: "" });
      mostrarResultado(d.resultado);
      vpEstado("Presupuesto aproximado (no enviado). Ajuste los datos y genere uno completo si lo necesita.");
    } else if (accion === "ajustar") {
      mostrarVista("presupuesto");
      mostrarPestanaVp("nuevo");
      await cargarConfigPresupuesto();
      const base = d ? d.campos : { coordenada: datos ? coordTexto(datos.cliente.lat, datos.cliente.lon) : "" };
      llenarFormulario({ ...base, ticket_id: "" });
      vpEstado("Datos de la estimación cargados: cámbielos y presione Generar presupuesto.");
      $("f-client_name").focus();
      $("f-client_name").select();
    }
  }

  // --- configuración: modo local / remoto, servidor y clave (Python: config_visor.py)
  const fechaCorta = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? `${m[3]}/${m[2]}/${m[1]}` : String(iso || "");
  };
  const modoElegido = () => (document.querySelector('input[name="config-modo"]:checked') || {}).value || "remoto";

  function configEstado(texto, tipo = "") {
    const caja = $("config-estado");
    caja.className = "vp-estado" + (tipo ? " " + tipo : "");
    caja.innerHTML = (tipo === "cargando" ? `<span class="spinner"></span> ` : "") + esc(texto);
  }
  function actualizarCamposConfig() {
    const remoto = modoElegido() === "remoto";
    $("config-url").disabled = $("config-clave").disabled = $("config-probar").disabled = !remoto;
  }
  async function abrirConfiguracion(primeraVez) {
    let c;
    try {
      c = await api.configuracion_visor();
    } catch (e) {
      mensaje("No se pudo leer la configuración: " + e, "error");
      return;
    }
    $("config-modos").hidden = !c.local_disponible;
    document.querySelectorAll('input[name="config-modo"]').forEach((r) => { r.checked = r.value === c.modo; });
    $("config-url").value = c.url || "";
    $("config-clave").value = "";
    $("config-clave").placeholder = c.clave_guardada ? "•••••••• guardada (escriba otra para cambiarla)" : "";
    $("config-archivo").textContent = c.archivo;
    actualizarCamposConfig();
    configEstado(primeraVez ? "Escriba la URL del servidor de presupuestos y su clave, pruebe la conexión y guarde." : "");
    $("modal-config").hidden = false;
    (c.modo === "remoto" && !c.url ? $("config-url") : $("config-guardar")).focus();
  }
  function cerrarConfiguracion() { $("modal-config").hidden = true; }

  async function probarConexion() {
    configEstado("Probando la conexión…", "cargando");
    let r;
    try {
      r = await api.probar_conexion($("config-url").value, $("config-clave").value);
    } catch (e) {
      r = { ok: false, error: String(e) };
    }
    if (r.ok) {
      configEstado(`Conexión correcta: ${r.servidor} · usuario ${r.persona} · API ${r.version_api}` +
                   (r.fecha_red ? ` · red Visio ${fechaCorta(r.fecha_red)}` : ""), "ok");
    } else {
      configEstado(r.error, "error");
    }
  }
  async function guardarConfiguracion() {
    configEstado("Guardando…", "cargando");
    let r;
    try {
      r = await api.guardar_configuracion(modoElegido(), $("config-url").value, $("config-clave").value);
    } catch (e) {
      r = { ok: false, error: String(e) };
    }
    if (!r.ok) { configEstado(r.error, "error"); return; }
    cerrarConfiguracion();
    pres.config = null;                 // the budget form options may come from another server now
    pres.cargaConfig = null;
    try { cfg = { ...cfg, ...(await api.configuracion()) }; } catch (e) { /* keep the current map */ }
    await actualizarEstadoModo();
    mensaje(r.modo === "remoto" ? `Modo remoto: ${r.url}` : "Modo local", "ok");
  }

  /** Status bar: mode, server and date of the Visio network. */
  async function actualizarEstadoModo() {
    const caja = $("estado-modo");
    let e;
    try {
      e = await api.estado();
    } catch (err) {
      return;
    }
    const fecha = e.fecha_red ? ` · red Visio ${fechaCorta(e.fecha_red)}` : "";
    if (e.modo === "local") caja.textContent = `Local${fecha}`;
    else if (e.sin_configurar) caja.textContent = "Remoto · sin configurar";
    else if (!e.ok) caja.textContent = `Remoto · ${e.servidor || "?"} · sin conexión`;
    else caja.textContent = `Remoto · ${e.servidor}${fecha}`;
    caja.className = "estado-modo " + (e.ok ? e.modo : "error");
    caja.title = (e.error ? e.error + " · " : "") + "Clic: configuración";
  }

  function conectarConfiguracion() {
    $("config-cerrar").addEventListener("click", cerrarConfiguracion);
    $("config-probar").addEventListener("click", probarConexion);
    $("config-guardar").addEventListener("click", guardarConfiguracion);
    document.querySelectorAll('input[name="config-modo"]').forEach((r) => r.addEventListener("change", actualizarCamposConfig));
    $("config-clave").addEventListener("keydown", (e) => { if (e.key === "Enter") guardarConfiguracion(); });
    $("estado-modo").addEventListener("click", () => abrirConfiguracion(false));
  }

  function conectarPresupuesto() {
    conectarConfiguracion();
    $("vp-volver").addEventListener("click", () => mostrarVista("mapa"));
    document.querySelectorAll(".vp-tab").forEach((b) => b.addEventListener("click", () => mostrarPestanaVp(b.dataset.vpTab)));
    $("vp-hist-filtro").addEventListener("input", pintarHistorial);
    $("vp-hist-estimaciones").addEventListener("change", pintarHistorial);
    $("vp-hist-recargar").addEventListener("click", cargarHistorial);
    $("vp-hist-lista").addEventListener("click", (e) => {
      const item = e.target.closest("[data-hist]");
      if (item) abrirDelHistorial(item.dataset.hist);
    });
    $("vp-form").addEventListener("submit", generarPresupuesto);
    $("vp-desde-mapa").addEventListener("click", () => usarCoordenadaMapa(true));
    document.querySelectorAll(".vp-pestana").forEach((b) =>
      b.addEventListener("click", () => { if (!b.disabled) mostrarHoja(b.dataset.hoja); }));
    $("vp-zoom-menos").addEventListener("click", () => { pres.zoom = Math.max(0.4, +(pres.zoom - 0.1).toFixed(2)); aplicarZoom(); });
    $("vp-zoom-mas").addEventListener("click", () => { pres.zoom = Math.min(2, +(pres.zoom + 0.1).toFixed(2)); aplicarZoom(); });
    document.querySelectorAll("[data-guardar]").forEach((b) =>
      b.addEventListener("click", () => pres.actual && guardarComo(pres.actual.archivo, b.dataset.guardar)));
    $("vp-abrir-excel").addEventListener("click", () => pres.actual && abrirEnExcel(pres.actual.archivo));
    $("vp-abrir-carpeta").addEventListener("click", () => abrirCarpeta(pres.actual ? pres.actual.archivo : ""));
    $("presupuesto-aprox").addEventListener("click", accionEstimacion);
    renderEstimacion();
  }

  // ------------------------------------------------------------------ eventos de la interfaz
  function conectarEventos() {
    $("generar").addEventListener("click", generar);
    $("limpiar").addEventListener("click", limpiar);
    $("medir").addEventListener("click", () => (med.activo ? terminarMedicion() : iniciarMedicion(null)));
    $("nueva-medida").addEventListener("click", nuevaMedida);
    $("borrar-medidas").addEventListener("click", borrarMedidas);
    conectarPresupuesto();
    $("copiar-resumen").addEventListener("click", () => copiar(resumenTexto(), "Resumen copiado al portapapeles"));
    $("copiar-fusion").addEventListener("click", () => copiar(fusionTexto(), "Ruta de fusión copiada al portapapeles"));
    document.querySelectorAll(".pestana").forEach((b) => b.addEventListener("click", () => mostrarPestana(b.dataset.pestana)));
    $("fusion").addEventListener("change", (e) => {
      if (e.target.id === "ver-piloto") { mostrarPiloto = e.target.checked; renderFusion(); }
    });
    $("fusion").addEventListener("click", (e) => {
      const centrar = e.target.closest("[data-centrar]");
      if (centrar && !centrar.disabled) centrarParada(centrar.dataset.centrar);
      const ver = e.target.closest("[data-diagrama]");
      if (ver) abrirDiagrama(ver.dataset.diagrama);
    });
    conectarDiagrama();
    conectarBuscador();
    $("cerrar-panel").addEventListener("click", () => { $("panel").hidden = true; $("abrir-panel").hidden = false; actualizarOcupado(); });
    $("abrir-panel").addEventListener("click", () => { $("panel").hidden = false; $("abrir-panel").hidden = true; actualizarOcupado(); });
    window.addEventListener("resize", actualizarOcupado);
    actualizarOcupado();

    const coord = $("coord");
    coord.addEventListener("keydown", (e) => {
      const lista = $("historial");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (lista.hidden) { marcadoHist = -1; mostrarHistorial(); }
        if (!historial.length) return;
        marcadoHist = (marcadoHist + (e.key === "ArrowDown" ? 1 : -1) + historial.length) % historial.length;
        mostrarHistorial();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (!lista.hidden && marcadoHist >= 0) elegirHistorial(marcadoHist);
        else generar();
      } else if (e.key === "Escape") {
        ocultarHistorial();
      }
    });
    $("hist-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      if ($("historial").hidden) mostrarHistorial(); else ocultarHistorial();
    });
    $("historial").addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); elegirHistorial(Number(li.dataset.i)); }
    });

    $("menu").addEventListener("click", (e) => {
      const li = e.target.closest("li[data-accion]");
      if (li) accionMenu(li.dataset.accion);
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#menu")) ocultarMenu();
      if (!e.target.closest("#campo")) ocultarHistorial();
      if (!e.target.closest("#buscador")) ocultarResultados();
      const copiarBtn = e.target.closest("[data-copiar]");
      if (copiarBtn) copiar(copiarBtn.dataset.copiar, `Coordenada copiada: ${copiarBtn.dataset.copiar}`);
      const copiarMedida = e.target.closest("[data-copiar-medida]");
      if (copiarMedida) {
        const m = medidas.find((x) => x.id === Number(copiarMedida.dataset.copiarMedida));
        if (m) copiar(`${m.nombre}: ${metros(m.total)}`, `${m.nombre} copiada`);
      }
      const quitar = e.target.closest("[data-quitar-medida]");
      if (quitar) quitarMedida(Number(quitar.dataset.quitarMedida));
      if (e.target.closest("[data-desmarcar-postes]")) desmarcarPostes();
      if (e.target.closest("a[href]")) e.preventDefault();     // never navigate away from the viewer
    }, true);   // capture: Leaflet stops click propagation inside popups and controls
    // Our own right-click menu replaces the browser's (except in text fields, to paste).
    document.addEventListener("contextmenu", (e) => {
      if (!e.target.closest("input, textarea")) e.preventDefault();
    });
    document.addEventListener("keydown", (e) => {
      if (!$("modal-config").hidden) {
        if (e.key === "Escape") { e.preventDefault(); cerrarConfiguracion(); }
        return;                                            // typing the URL / key never reaches the map
      }
      if (!$("modal-diagrama").hidden) {
        if (e.key === "Escape") cerrarDiagrama();
        else if (e.key === "+" || e.key === "=") visorModal.zoom(1.4);
        else if (e.key === "-") visorModal.zoom(1 / 1.4);
        return;                                            // the map does not react behind the viewer
      }
      if (e.key === "Escape") ocultarMenu();
      if (!med.activo || document.querySelector(".vista:not([hidden])")) return;   // a view covers the map
      const enCampo = e.target.closest && e.target.closest("input, textarea");
      if (e.key === "Escape") { e.preventDefault(); cancelarMedicion(); }
      else if (e.key === "Enter" && !enCampo) { e.preventDefault(); terminarMedicion(); }
      else if ((e.key === "n" || e.key === "N") && !enCampo) { e.preventDefault(); nuevaMedida(); }
      else if ((e.key === "Backspace" || e.key === "Delete") && !enCampo) { e.preventDefault(); quitarUltimoPunto(); }
    });
  }

  // ------------------------------------------------------------------ arranque
  async function iniciar() {
    if (iniciado || !window.pywebview || !window.pywebview.api) return;
    iniciado = true;
    api = window.pywebview.api;
    try {
      cfg = await api.configuracion();
      crearMapa();
      conectarEventos();
      renderPanel();
      if (window.Menu) {               // side menu (menu.js) and the network module's user (redes/comun.js)
        window.Menu.iniciar({ api, mostrarVista, mensaje }).catch((e) => console.error("Menu", e));
        if (window.Redes) {
          window.Redes.cfg = cfg;      // base map (tiles) for the module's small maps
          window.Redes.iniciar(api).catch((e) => console.error("Redes", e));
        }
      }
      if (window.Lugares) {            // KMZ network panel (lugares.js); never blocks the map
        window.Lugares.iniciar({
          mapa, api, esc, copiar, coordTexto, mensaje,
          midiendo: () => med.activo, agregarPunto: (ll) => agregarPunto(imantar(ll)),
        }).catch((e) => console.error("Lugares", e));
      }
      mensaje("Pegue una coordenada y presione Enter");
      $("coord").focus();
      actualizarEstadoModo();
      if (cfg.sin_configurar) abrirConfiguracion(true);   // remote mode, first time: URL and key
    } catch (e) {
      console.error(e);
      mensaje("No se pudo iniciar el mapa: " + e, "error");
    }
  }

  // Read-only handle for automated checks (pywebview evaluate_js) and troubleshooting.
  window.visor = {
    get mapa() { return mapa; }, get datos() { return datos; }, get medidas() { return medidas.length; },
    get estimacion() { return estim.estado; }, mostrarVista: (nombre) => mostrarVista(nombre),
    get midiendo() { return med.activo; }, abrirDiagramaPorNombre: (nombre) => abrirDiagramaPorNombre(nombre),
    verVisioAlLado: (nombre) => verVisioAlLado(nombre),
    mensaje: (texto, tipo) => mensaje(texto, tipo),
    abrirDiagrama: (orden) => abrirDiagrama(orden), mostrarPestana: (nombre) => mostrarPestana(nombre),
  };

  window.addEventListener("pywebviewready", iniciar);
  iniciar();
  setTimeout(() => {
    if (!iniciado) mensaje("No se pudo conectar con Python (pywebview). Cierre y vuelva a abrir el visor.", "error");
  }, 10000);
})();
