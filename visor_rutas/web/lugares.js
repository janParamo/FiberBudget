/* Panel "Lugares" del visor de rutas: la red del KMZ como en Google Earth.
 *
 * Árbol de carpetas del KMZ (visor_rutas/kmz_capas.py -> datos_kmz/arbol.json) con casillas de
 * tres estados, conteos, estilo de cada carpeta, buscador y menú de clic derecho. Cada carpeta se
 * carga la primera vez que se enciende (api.kmz_capa) y se dibuja en canvas; postes y pozos solo
 * desde zoom 15, agrupados hasta zoom 16. Troncales: color y grosor originales, "colores
 * distintivos" donde se repiten, estilo por familia, resaltado al pasar el mouse y leyenda.
 * El estado (casillas, expandidas, opacidades...) se guarda en %APPDATA%\VisorRutas\capas.json.
 *
 * visor.js llama a Lugares.iniciar(ctx) cuando el mapa existe; ctx trae el mapa, la api de
 * pywebview y las utilidades de la página (mensaje, copiar, medición).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const FILA_PX = 22;
  const ZOOM_POSTES = 15;           // posts and wells: only from this zoom (like Google Earth Regions)
  const ZOOM_SIN_GRUPOS = 17;       // posts are clustered below this zoom
  const ZOOM_ETIQUETAS = 14;
  const MAX_ETIQUETAS = 300;        // labels per folder in the visible area
  const MAX_RESULTADOS = 500;
  const ANCHO_MIN = 220, ANCHO_MAX = 640;
  const VERSION_ESTADO = 1;

  let ctx = null;                   // {mapa, api, mensaje, esc, copiar, coordTexto, midiendo, agregarPunto}
  let mapa = null, api = null, esc = null;
  let lienzo = null;                // canvas renderer for lines and posts
  const s = {
    arbol: null, carpetas: {}, iconos: {}, raiz: null,
    marcadas: new Set(),            // folders whose own elements are on
    ocultos: new Map(),             // folder id -> Set(element index) turned off one by one
    expandidas: new Set(), opacidad: {}, etiquetas: {},
    distintivos: true, ancho: 300, plegado: false,
    capas: new Map(),               // folder id -> {geo, grupo, items, etiquetas}
    cargas: new Map(),              // folder id -> Promise of the layer
    indice: null, cargaIndice: null,
    busqueda: "", enDescripcion: false, seleccion: null,
    filas: [],
    resaltada: null,
  };

  // ------------------------------------------------------------------ utilidades
  const carpeta = (id) => s.carpetas[id];
  const hijos = (id) => (carpeta(id) ? carpeta(id).hijos : []);
  const rutaCorta = (ruta) => String(ruta || "").split("/").slice(2).join(" / ") || String(ruta || "");
  const normal = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const opacidadDe = (id) => (s.opacidad[id] === undefined ? 1 : s.opacidad[id]);
  const etiquetasDe = (id) => (s.etiquetas[id] === undefined ? !!carpeta(id).etiquetas : !!s.etiquetas[id]);

  function descendientes(id, salida = []) {
    salida.push(id);
    hijos(id).forEach((h) => descendientes(h, salida));
    return salida;
  }

  function estado(id) {
    /** "on" | "off" | "partial" | "empty" (three-state checkbox of a folder). */
    const c = carpeta(id);
    if (!c || !c.total) return "empty";
    const partes = [];
    if (c.directos) {
      const ocultos = s.ocultos.get(id);
      partes.push(!s.marcadas.has(id) ? "off" : (ocultos && ocultos.size ? "partial" : "on"));
    }
    c.hijos.forEach((h) => { const e = estado(h); if (e !== "empty") partes.push(e); });
    if (partes.every((e) => e === "on")) return "on";
    if (partes.every((e) => e === "off")) return "off";
    return "partial";
  }

  let temporizadorGuardar = null;
  function guardarEstado() {
    clearTimeout(temporizadorGuardar);
    temporizadorGuardar = setTimeout(() => {
      if (!api || !s.arbol) return;
      const ocultos = {};
      s.ocultos.forEach((v, k) => { if (v.size) ocultos[k] = [...v]; });
      api.guardar_capas_estado({
        version: VERSION_ESTADO, md5: s.arbol.md5, marcadas: [...s.marcadas], expandidas: [...s.expandidas],
        opacidad: s.opacidad, etiquetas: s.etiquetas, ocultos, distintivos: s.distintivos,
        ancho: s.ancho, plegado: s.plegado,
      }).catch(() => {});
    }, 700);
  }

  function estadoInicial() {
    s.marcadas = new Set(Object.values(s.carpetas).filter((c) => c.visible && c.directos).map((c) => c.id));
    s.ocultos = new Map();
    s.expandidas = new Set([s.raiz, ...hijos(s.raiz)]);
    s.opacidad = {};
    s.etiquetas = {};
    s.distintivos = true;
  }

  function restaurar(guardado) {
    estadoInicial();
    if (!guardado || guardado.version !== VERSION_ESTADO) return;
    const existe = (id) => !!s.carpetas[id];
    s.marcadas = new Set((guardado.marcadas || []).filter(existe));
    s.expandidas = new Set((guardado.expandidas || []).filter(existe));
    Object.entries(guardado.opacidad || {}).forEach(([k, v]) => { if (existe(k)) s.opacidad[k] = Number(v); });
    Object.entries(guardado.etiquetas || {}).forEach(([k, v]) => { if (existe(k)) s.etiquetas[k] = !!v; });
    Object.entries(guardado.ocultos || {}).forEach(([k, v]) => { if (existe(k)) s.ocultos.set(k, new Set(v)); });
    s.distintivos = guardado.distintivos !== false;
    if (guardado.ancho) s.ancho = Math.max(ANCHO_MIN, Math.min(ANCHO_MAX, Number(guardado.ancho)));
    s.plegado = !!guardado.plegado;
  }

  // ------------------------------------------------------------------ estilos
  function estiloLinea(c, f, est) {
    const p = f.properties, fam = c.troncal ? (p.f || "troncal") : null;
    const color = s.distintivos && p.cd ? p.cd : est.color;
    let grosor = est.grosor || 2;
    let dash = null, cap = "round";
    if (fam === "gpon") grosor = Math.max(grosor, 4);
    else if (fam === "ufinet") { dash = "1 7"; grosor = Math.max(grosor, 3); }
    else if (fam === "redundante") { dash = "6 6"; cap = "butt"; }
    else if (fam === "metro") grosor = Math.max(grosor, 3);
    return { color, weight: grosor, opacity: (est.opacidad || 1) * opacidadDe(c.id), dashArray: dash, lineCap: cap,
             renderer: lienzo, pane: "kmzLineas" };
  }

  function iconoLeaflet(est) {
    const url = s.iconos[est.icono];
    const t = est.tam || 24;
    const ancla = est.ancla === "pin" ? [Math.round(t * 0.31), t] : est.ancla === "bandera" ? [Math.round(t * 0.25), t] : [t / 2, t / 2];
    return L.icon({ iconUrl: url, iconSize: [t, t], iconAnchor: ancla, popupAnchor: [0, -ancla[1] + 4],
                    tooltipAnchor: [0, -ancla[1] + 2] });
  }

  function muestra(est, tam = 14) {
    /** Small sample of a style for the tree and the legends. */
    if (!est) return `<span class="lg-muestra vacia"></span>`;
    if (est.tipo === "linea") {
      return `<span class="lg-muestra linea" style="border-top:${Math.min(4, Math.max(2, est.grosor || 2))}px solid ${esc(est.color)}"></span>`;
    }
    if (est.tipo === "icono" && s.iconos[est.icono]) {
      return `<img class="lg-muestra" src="${s.iconos[est.icono]}" width="${tam}" height="${tam}" alt="">`;
    }
    return `<span class="lg-muestra punto" style="background:${esc(est.color || "#fff")}"></span>`;
  }

  // ------------------------------------------------------------------ capas
  function cargar(id) {
    if (s.capas.has(id)) return Promise.resolve(s.capas.get(id));
    if (s.cargas.has(id)) return s.cargas.get(id);
    const promesa = (async () => {
      let r;
      try { r = await api.kmz_capa(id); } catch (e) { r = { ok: false, error: String(e) }; }
      s.cargas.delete(id);
      if (!r.ok) { avisar(`No se pudo cargar ${carpeta(id).nombre}: ${r.error}`, true); return null; }
      const capa = construir(id, r.capa);
      s.capas.set(id, capa);
      return capa;
    })();
    s.cargas.set(id, promesa);
    return promesa;
  }

  function construir(id, geo) {
    const c = carpeta(id);
    const grupo = c.postes
      ? L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: ZOOM_SIN_GRUPOS, showCoverageOnHover: false,
                               spiderfyOnMaxZoom: false, chunkedLoading: true, clusterPane: "kmzPuntos",
                               iconCreateFunction: (k) => L.divIcon({ className: "icono", iconSize: [26, 26],
                                 html: `<div class="cluster-kmz" style="border-color:${esc((c.estilo || {}).color || "#888")}">${k.getChildCount()}</div>` }) })
      : L.featureGroup();
    const items = geo.features.map((f, i) => crearElemento(c, geo, f, i));
    const ocultos = s.ocultos.get(id);
    items.forEach((it, i) => { if (it && !(ocultos && ocultos.has(i))) grupo.addLayer(it.capa); });
    return { geo, grupo, items, etiquetas: L.layerGroup(), enMapa: false };
  }

  function latlngs(coords) { return coords.map(([lon, lat]) => [lat, lon]); }

  function crearElemento(c, geo, f, i) {
    const est = geo.estilos[f.properties.e] || {};
    const g = f.geometry;
    if (!g) return null;
    let capa = null, linea = null, borde = null;
    const tipo = g.type;
    if (tipo === "LineString" || tipo === "MultiLineString" || (est.tipo === "linea" && tipo === "GeometryCollection")) {
      const partes = tipo === "LineString" ? [latlngs(g.coordinates)]
        : tipo === "MultiLineString" ? g.coordinates.map(latlngs)
          : g.geometries.filter((x) => x.type === "LineString").map((x) => latlngs(x.coordinates));
      linea = L.polyline(partes, estiloLinea(c, f, est));
      if (c.troncal && f.properties.f === "metro") {          // TRUNK METRO: dark double border
        borde = L.polyline(partes, { color: "#111", weight: linea.options.weight + 4, opacity: 0.85 * opacidadDe(c.id),
                                     renderer: lienzo, pane: "kmzLineas", interactive: false });
        capa = L.featureGroup([borde, linea]);
      } else {
        capa = linea;
      }
    } else if (tipo === "Polygon") {
      capa = L.polygon(g.coordinates.map(latlngs), { color: est.color, weight: est.grosor || 1, opacity: opacidadDe(c.id),
                                                     fillColor: est.relleno || est.color, fillOpacity: (est.relleno_opacidad || 0.2) * opacidadDe(c.id),
                                                     renderer: lienzo, pane: "kmzLineas" });
    } else {
      const punto = tipo === "Point" ? g.coordinates : tipo === "MultiPoint" ? g.coordinates[0]
        : (g.geometries.find((x) => x.type === "Point") || {}).coordinates;
      if (!punto) return null;
      const ll = L.latLng(punto[1], punto[0]);
      if (est.tipo === "icono" && s.iconos[est.icono]) {
        capa = L.marker(ll, { icon: iconoLeaflet(est), opacity: opacidadDe(c.id), pane: "kmzPuntos", riseOnHover: true });
      } else {
        capa = L.circleMarker(ll, { renderer: lienzo, pane: "kmzPuntos", radius: est.radio || 4.5, color: "#1a1a1a", weight: 1,
                                    fillColor: est.color || "#ffffff", fillOpacity: (est.opacidad || 1) * opacidadDe(c.id),
                                    opacity: opacidadDe(c.id) });
      }
    }
    const it = { capa, linea, borde, c, f, est, i };
    const nombre = f.properties.n || c.nombre;
    capa.bindTooltip(esc(nombre), { sticky: !!linea, direction: "top", className: "hover" });
    capa.on("click", (e) => alClic(it, e));
    if (esMufa(it)) {                     // existing mufa: Enter or double click -> its migrated editor (else its Visio diagram)
      capa.on("dblclick", (e) => {
        L.DomEvent.stop(e);
        const p = capa.getLatLng ? capa.getLatLng() : e.latlng;
        if (window.Redes) window.Redes.abrirMufaExistente(nombre, p.lat, p.lng);
        else if (window.visor) window.visor.abrirDiagramaPorNombre(nombre);
      });
    }
    if (linea && c.troncal) {
      capa.on("mouseover", () => resaltar(it, true));
      capa.on("mouseout", () => resaltar(it, false));
    }
    return it;
  }

  function reestilar(id) {
    const capa = s.capas.get(id), c = carpeta(id);
    if (!capa) return;
    const op = opacidadDe(id);
    capa.items.forEach((it) => {
      if (!it) return;
      if (it.linea) {
        it.linea.setStyle(estiloLinea(c, it.f, it.est));
        if (it.borde) it.borde.setStyle({ opacity: 0.85 * op });
      } else if (it.capa.setOpacity) {
        it.capa.setOpacity(op);
      } else if (it.capa.setStyle) {
        it.capa.setStyle({ opacity: op, fillOpacity: (it.est.opacidad || 1) * op });
      }
    });
  }

  function debeVerse(id) {
    const c = carpeta(id);
    return s.marcadas.has(id) && !(c.postes && mapa.getZoom() < ZOOM_POSTES);
  }

  async function aplicar(id) {
    /** Puts the folder's own layer on or off the map, loading it the first time. */
    const c = carpeta(id);
    if (!c || !c.directos) return;
    if (!s.marcadas.has(id)) {
      const capa = s.capas.get(id);
      if (capa && capa.enMapa) { mapa.removeLayer(capa.grupo); mapa.removeLayer(capa.etiquetas); capa.enMapa = false; }
      return;
    }
    const capa = await cargar(id);
    if (!capa) return;
    const ver = debeVerse(id);
    if (ver && !capa.enMapa) { capa.grupo.addTo(mapa); capa.etiquetas.addTo(mapa); capa.enMapa = true; }
    else if (!ver && capa.enMapa) { mapa.removeLayer(capa.grupo); mapa.removeLayer(capa.etiquetas); capa.enMapa = false; }
    if (capa.enMapa) dibujarEtiquetas(id);
  }

  function aplicarTodas() {
    const ids = Object.keys(s.carpetas).filter((id) => carpeta(id).directos && (s.marcadas.has(id) || s.capas.has(id)));
    return Promise.all(ids.map(aplicar)).then(() => { actualizarAvisoPostes(); actualizarLeyendaTroncales(); });
  }

  // ------------------------------------------------------------------ etiquetas
  function puntoEtiqueta(it) {
    if (it.capa.getLatLng) return it.capa.getLatLng();
    const pts = it.linea ? it.linea.getLatLngs().flat(2) : [];
    return pts.length ? pts[Math.floor(pts.length / 2)] : null;
  }

  function dibujarEtiquetas(id) {
    const capa = s.capas.get(id);
    if (!capa) return;
    capa.etiquetas.clearLayers();
    if (!capa.enMapa || !etiquetasDe(id) || mapa.getZoom() < ZOOM_ETIQUETAS) return;
    const vista = mapa.getBounds().pad(0.1);
    const ocultos = s.ocultos.get(id);
    let n = 0;
    for (const it of capa.items) {
      if (!it || (ocultos && ocultos.has(it.i)) || !it.f.properties.n) continue;
      const ll = puntoEtiqueta(it);
      if (!ll || !vista.contains(ll)) continue;
      L.marker(ll, { pane: "kmzEtiquetas", interactive: false, keyboard: false,
                     icon: L.divIcon({ className: "etiqueta-kmz", html: `<span>${esc(it.f.properties.n)}</span>`, iconSize: null }) })
        .addTo(capa.etiquetas);
      if (++n >= MAX_ETIQUETAS) break;
    }
  }

  // ------------------------------------------------------------------ troncales: resaltar y leyenda
  function lineasTroncalesVisibles() {
    const lista = [];
    s.capas.forEach((capa, id) => {
      if (!capa.enMapa || !carpeta(id).troncal) return;
      const ocultos = s.ocultos.get(id);
      capa.items.forEach((it) => { if (it && it.linea && !(ocultos && ocultos.has(it.i))) lista.push(it); });
    });
    return lista;
  }

  let halo = null;
  function resaltar(it, activo) {
    if (halo) { mapa.removeLayer(halo); halo = null; }
    const lineas = lineasTroncalesVisibles();
    if (!activo) {
      s.resaltada = null;
      lineas.forEach((x) => x.linea.setStyle(estiloLinea(x.c, x.f, x.est)));
      return;
    }
    s.resaltada = it;
    lineas.forEach((x) => { if (x !== it) x.linea.setStyle({ opacity: 0.22 }); });
    const base = estiloLinea(it.c, it.f, it.est);
    halo = L.polyline(it.linea.getLatLngs(), { color: "#ffffff", weight: base.weight + 9, opacity: 0.75, renderer: lienzo,
                                               pane: "kmzLineas", interactive: false }).addTo(mapa);
    halo.bringToBack();
    it.linea.setStyle({ ...base, weight: base.weight + 3, opacity: 1 });
    it.linea.bringToFront();
  }

  function muestraTroncal(it) {
    const e = estiloLinea(it.c, it.f, it.est);
    const borde = e.dashArray ? "dashed" : "solid";
    const doble = it.f.properties.f === "metro" ? "box-shadow:0 0 0 2px #111;" : "";
    const punteada = it.f.properties.f === "ufinet" ? "dotted" : borde;
    return `<span class="lg-muestra linea" style="border-top:${Math.min(5, e.weight)}px ${punteada} ${esc(e.color)};${doble}"></span>`;
  }

  let controlTroncales = null;
  function crearLeyendaTroncales() {
    controlTroncales = L.control({ position: "bottomleft" });
    controlTroncales.onAdd = () => {
      const div = L.DomUtil.create("div", "leyenda leyenda-troncales");
      div.hidden = true;
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.addEventListener("click", (e) => {
        if (e.target.closest("h4")) { div.classList.toggle("leyenda-plegada"); return; }
        const fila = e.target.closest("[data-troncal]");
        if (!fila) return;
        const [id, i] = fila.dataset.troncal.split(":");
        const capa = s.capas.get(id), it = capa && capa.items[Number(i)];
        if (!it) return;
        mapa.fitBounds(it.linea.getBounds(), { padding: [60, 60], maxZoom: 17 });
        resaltar(it, true);
        setTimeout(() => { if (s.resaltada === it) resaltar(it, false); }, 3500);
      });
      return div;
    };
    controlTroncales.addTo(mapa);
  }

  function actualizarLeyendaTroncales() {
    if (!controlTroncales) return;
    const div = controlTroncales.getContainer();
    const lineas = lineasTroncalesVisibles().sort((a, b) => String(a.f.properties.n).localeCompare(String(b.f.properties.n)));
    div.hidden = !lineas.length;
    const plegada = div.classList.contains("leyenda-plegada");
    div.innerHTML = `<h4>Troncales (${lineas.length})</h4><div class="cuerpo">` + lineas.map((it) =>
      `<div class="fila" data-troncal="${it.c.id}:${it.i}" title="Clic: encuadrar y resaltar">${muestraTroncal(it)}<span>${esc(it.f.properties.n || it.c.nombre)}</span></div>`).join("") + `</div>`;
    div.classList.toggle("leyenda-plegada", plegada);
  }

  // ------------------------------------------------------------------ popups y fotos
  /** A point of a MUFA folder (MUFA, MUFAS DE CORTE, MUFA UFINET...): an existing mufa of the network. */
  const esMufa = (it) => !it.linea && !it.c.postes && /MUFA/i.test(it.c.ruta || "") && !!it.f.properties.n;

  function htmlPopup(it, ll) {
    const p = it.f.properties, c = it.c;
    const filas = [];
    const fila = (k, v) => { if (v !== undefined && v !== null && v !== "") filas.push(`<dt>${esc(k)}</dt><dd>${v}</dd>`); };
    if (it.linea) {
      fila("Longitud", p.km !== undefined ? `${Number(p.km).toLocaleString("en-US", { maximumFractionDigits: 2 })} km` : null);
      if (c.troncal) {
        fila("Familia", esc({ gpon: "Trunk GPON", metro: "Trunk Metro", ufinet: "UFINET (red de terceros)", redundante: "Enlace redundante" }[p.f] || "Troncal"));
        fila("Color original", `<span class="lg-color" style="background:${esc(it.est.color)}"></span>${esc(it.est.color)}`);
        if (p.cd && s.distintivos) fila("Color distintivo", `<span class="lg-color" style="background:${esc(p.cd)}"></span>${esc(p.cd)}`);
      }
    }
    fila("Notes", p.notes ? esc(p.notes) : null);
    fila("Descripción", p.desc ? esc(p.desc) : null);
    Object.entries(p.datos || {}).forEach(([k, v]) => fila(k, esc(v)));
    const coord = ctx.coordTexto(ll.lat, ll.lng);
    const fotos = (p.fotos || []).map((n) => `<img class="lg-foto" data-foto="${esc(n)}" alt="${esc(n)}" title="Clic: ver en grande">`).join("");
    return `<div class="popup lg-popup"><h3>${esc(p.n || "(sin nombre)")}</h3>
      <div class="tipo">${esc(rutaCorta(c.ruta))}</div>
      ${p.d ? `<div class="lg-descripcion">${p.d}</div>` : ""}
      <dl>${filas.join("")}<dt>Coordenada</dt><dd>${coord}</dd></dl>
      ${fotos ? `<div class="lg-fotos">${fotos}</div>` : ""}
      <div class="acciones"><button type="button" class="btn btn-chico" data-copiar="${coord}">Copiar</button>
        ${esMufa(it) ? `<button type="button" class="btn btn-chico" data-diagrama-mufa="${esc(p.n)}" title="También: doble clic o Enter">Ver diagrama Visio</button>` : ""}</div></div>`;
  }

  function abrirPopup(it, ll) {
    const punto = ll || (it.capa.getLatLng ? it.capa.getLatLng() : puntoEtiqueta(it));
    if (!punto) return;
    const popup = L.popup({ maxWidth: 380, maxHeight: 420, autoPanPaddingTopLeft: [20, 60] })
      .setLatLng(punto).setContent(htmlPopup(it, punto)).openOn(mapa);
    cargarFotos(popup.getElement());
  }

  async function cargarFotos(raiz) {
    if (!raiz) return;
    for (const img of raiz.querySelectorAll("img[data-foto]")) {
      try {
        const r = await api.kmz_foto(img.dataset.foto);
        if (r.ok) img.src = r.data_url; else img.replaceWith(Object.assign(document.createElement("span"), { textContent: r.error, className: "nota" }));
      } catch (e) { /* the popup was closed */ }
    }
  }

  function alClic(it, e) {
    if (ctx.midiendo()) {                // measuring: a marker click adds a point (lines bubble to the map)
      if (it.capa instanceof L.Marker) ctx.agregarPunto(e.latlng);
      return;
    }
    if (e.originalEvent) L.DomEvent.stopPropagation(e);
    // Enter opens its migrated editor (else its Visio diagram)
    window.__mufaExistente = esMufa(it) ? { nombre: it.f.properties.n, lat: e.latlng && e.latlng.lat, lon: e.latlng && e.latlng.lng } : null;
    abrirPopup(it, it.capa.getLatLng ? it.capa.getLatLng() : e.latlng);
  }

  function verFotoGrande(src) {
    const velo = $("lg-foto-grande");
    velo.querySelector("img").src = src;
    velo.hidden = false;
  }

  // ------------------------------------------------------------------ árbol (lista virtual)
  function construirFilas() {
    const filas = [];
    if (!s.arbol) { s.filas = filas; return; }
    if (s.busqueda) {
      buscar(filas);
    } else {
      const recorrer = (id, nivel) => {
        const c = carpeta(id);
        filas.push({ t: "carpeta", id, nivel });
        if (!s.expandidas.has(id)) return;
        c.hijos.forEach((h) => recorrer(h, nivel + 1));
        if (c.directos) {
          const capa = s.capas.get(id);
          if (!capa) filas.push({ t: "cargando", id, nivel: nivel + 1 });
          else capa.geo.features.forEach((f, i) => filas.push({ t: "elemento", id, i, nivel: nivel + 1 }));
        }
      };
      recorrer(s.raiz, 0);
    }
    s.filas = filas;
    $("lg-espaciador").style.height = `${filas.length * FILA_PX}px`;
  }

  function buscar(filas) {
    const q = normal(s.busqueda);
    let n = 0;
    Object.values(s.carpetas).forEach((c) => {
      if (n < MAX_RESULTADOS && normal(c.nombre).includes(q)) { filas.push({ t: "carpeta", id: c.id, nivel: 0, ruta: true }); n++; }
    });
    if (!s.indice) {
      filas.push({ t: "aviso", texto: s.cargaIndice ? "Buscando en los elementos…" : "" });
      return;
    }
    for (const [id, lista] of Object.entries(s.indice)) {
      for (let i = 0; i < lista.length && n < MAX_RESULTADOS; i++) {
        const [nombre, texto] = lista[i];
        if (normal(nombre).includes(q) || (s.enDescripcion && normal(texto).includes(q))) {
          filas.push({ t: "elemento", id, i, nivel: 0, nombre, ruta: true });
          n++;
        }
      }
    }
    if (n >= MAX_RESULTADOS) filas.push({ t: "aviso", texto: `Se muestran los primeros ${MAX_RESULTADOS} resultados: escriba más para afinar` });
    if (!n) filas.push({ t: "aviso", texto: "Sin resultados" });
  }

  function resaltarTexto(texto) {
    const t = esc(texto);
    if (!s.busqueda) return t;
    const q = normal(s.busqueda), base = normal(texto);
    const k = base.indexOf(q);
    if (k < 0) return t;
    return `${esc(texto.slice(0, k))}<mark>${esc(texto.slice(k, k + q.length))}</mark>${esc(texto.slice(k + q.length))}`;
  }

  function htmlFila(f, k) {
    const sangria = 6 + f.nivel * 14;
    const sel = s.seleccion && s.seleccion.id === f.id && s.seleccion.i === f.i ? " sel" : "";
    const top = `top:${k * FILA_PX}px;padding-left:${sangria}px`;
    if (f.t === "carpeta") {
      const c = carpeta(f.id), e = estado(f.id);
      const flecha = c.hijos.length || c.directos
        ? `<span class="lg-flecha" data-expandir="${f.id}">${s.expandidas.has(f.id) && !s.busqueda ? "▾" : "▸"}</span>`
        : `<span class="lg-flecha"></span>`;
      return `<div class="lg-fila carpeta${e === "empty" ? " vacia" : ""}${sel}" style="${top}" data-fila="${k}" title="${esc(rutaCorta(c.ruta))}">
        ${s.busqueda ? "" : flecha}<input type="checkbox" class="lg-casilla" data-casilla="${f.id}" ${e === "on" ? "checked" : ""} ${e === "empty" ? "disabled" : ""} data-parcial="${e === "partial" ? 1 : 0}">
        ${muestra(c.estilo)}<span class="lg-nombre">${resaltarTexto(c.nombre)}</span><span class="lg-cuenta">${c.total ? c.total.toLocaleString("en-US") : ""}</span>
        ${f.ruta ? `<span class="lg-ruta">${esc(rutaCorta(c.ruta))}</span>` : ""}</div>`;
    }
    if (f.t === "elemento") {
      const c = carpeta(f.id), capa = s.capas.get(f.id);
      const feat = capa ? capa.geo.features[f.i] : null;
      const nombre = feat ? (feat.properties.n || "(sin nombre)") : (f.nombre || "(sin nombre)");
      const est = feat && capa ? capa.geo.estilos[feat.properties.e] : c.estilo;
      const visible = s.marcadas.has(f.id) && !(s.ocultos.get(f.id) || new Set()).has(f.i);
      return `<div class="lg-fila elemento${sel}" style="${top}" data-fila="${k}" title="${esc(nombre)}">
        <span class="lg-flecha"></span><input type="checkbox" class="lg-casilla" data-elemento="${f.id}:${f.i}" ${visible ? "checked" : ""}>
        ${muestra(est)}<span class="lg-nombre">${resaltarTexto(nombre)}</span>
        ${f.ruta ? `<span class="lg-ruta">${esc(rutaCorta(c.ruta))}</span>` : ""}</div>`;
    }
    const texto = f.t === "cargando" ? "Cargando…" : f.texto;
    return `<div class="lg-fila aviso" style="${top}">${esc(texto)}</div>`;
  }

  function pintar() {
    const caja = $("lg-arbol");
    if (!caja) return;
    const desde = Math.max(0, Math.floor(caja.scrollTop / FILA_PX) - 10);
    const hasta = Math.min(s.filas.length, desde + Math.ceil(caja.clientHeight / FILA_PX) + 20);
    const html = [];
    for (let k = desde; k < hasta; k++) html.push(htmlFila(s.filas[k], k));
    $("lg-filas").innerHTML = html.join("");
    $("lg-filas").querySelectorAll("[data-parcial='1']").forEach((x) => { x.indeterminate = true; });
  }

  function refrescar() { construirFilas(); pintar(); }

  // ------------------------------------------------------------------ acciones del árbol
  function marcarCarpeta(id, encender) {
    descendientes(id).forEach((d) => {
      const c = carpeta(d);
      if (!c.directos) return;
      if (encender) { s.marcadas.add(d); s.ocultos.delete(d); } else s.marcadas.delete(d);
      const capa = s.capas.get(d);
      if (capa && encender) capa.items.forEach((it) => { if (it && !capa.grupo.hasLayer(it.capa)) capa.grupo.addLayer(it.capa); });
    });
    cambio();
  }

  function marcarElemento(id, i, visible) {
    const capa = s.capas.get(id);
    if (!capa || !capa.items[i]) return;
    const ocultos = s.ocultos.get(id) || new Set();
    if (visible) {
      ocultos.delete(i);
      if (!s.marcadas.has(id)) {                     // turning one element on turns its folder on, alone
        s.marcadas.add(id);
        capa.items.forEach((it, k) => { if (k !== i) ocultos.add(k); });
        capa.items.forEach((it, k) => { if (it && ocultos.has(k)) capa.grupo.removeLayer(it.capa); });
      }
      capa.grupo.addLayer(capa.items[i].capa);
    } else {
      ocultos.add(i);
      capa.grupo.removeLayer(capa.items[i].capa);
    }
    s.ocultos.set(id, ocultos);
    if (ocultos.size === capa.items.length) { s.marcadas.delete(id); s.ocultos.delete(id); capa.items.forEach((it) => it && capa.grupo.addLayer(it.capa)); }
    cambio();
  }

  function cambio() {
    aplicarTodas().then(refrescar);
    refrescar();
    guardarEstado();
  }

  async function expandir(id) {
    if (s.expandidas.has(id)) s.expandidas.delete(id);
    else {
      s.expandidas.add(id);
      if (carpeta(id).directos && !s.capas.has(id)) { refrescar(); await cargar(id); }
    }
    refrescar();
    guardarEstado();
  }

  function encuadrar(id) {
    const b = carpeta(id).bbox;
    if (!b) return;
    mapa.fitBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [40, 40], maxZoom: 18 });
  }

  async function volarA(id, i) {
    const capa = await cargar(id);
    if (!capa || !capa.items[i]) return;
    const it = capa.items[i];
    if (!s.marcadas.has(id) || (s.ocultos.get(id) || new Set()).has(i)) marcarElemento(id, i, true);
    const ll = it.capa.getLatLng ? it.capa.getLatLng() : null;
    if (ll) mapa.flyTo(ll, Math.max(mapa.getZoom(), carpeta(id).postes ? 18 : 17), { duration: 0.8 });
    else mapa.flyToBounds(it.linea.getBounds(), { padding: [60, 60], maxZoom: 17, duration: 0.8 });
    mapa.once("moveend", () => { aplicar(id).then(() => abrirPopup(it, ll || puntoEtiqueta(it))); });
  }

  // ------------------------------------------------------------------ menú de clic derecho
  function abrirMenu(id, x, y) {
    const menu = $("lg-menu");
    menu.dataset.id = id;
    $("lg-menu-etiquetas").textContent = `${etiquetasDe(id) ? "✓ " : ""}Etiquetas de nombre`;
    menu.hidden = false;
    const r = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(x, window.innerWidth - r.width - 8)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - r.height - 8)}px`;
  }
  function cerrarMenu() { $("lg-menu").hidden = true; $("lg-opacidad").hidden = true; }

  function accionMenu(accion) {
    const id = $("lg-menu").dataset.id;
    if (!id) return;
    if (accion === "solo") {
      s.marcadas = new Set(descendientes(id).filter((d) => carpeta(d).directos));
      s.ocultos = new Map();
      s.capas.forEach((capa) => capa.items.forEach((it) => { if (it && !capa.grupo.hasLayer(it.capa)) capa.grupo.addLayer(it.capa); }));
      cambio();
      encuadrar(id);
    } else if (accion === "encuadrar") {
      encuadrar(id);
    } else if (accion === "etiquetas") {
      const nuevo = !etiquetasDe(id);
      descendientes(id).forEach((d) => { s.etiquetas[d] = nuevo; dibujarEtiquetas(d); });
      guardarEstado();
    } else if (accion === "opacidad") {
      const caja = $("lg-opacidad"), menu = $("lg-menu");
      caja.dataset.id = id;
      $("lg-opacidad-valor").value = Math.round(opacidadDe(id) * 100);
      $("lg-opacidad-texto").textContent = `${Math.round(opacidadDe(id) * 100)}%`;
      caja.style.left = menu.style.left;
      caja.style.top = menu.style.top;
      caja.hidden = false;
      menu.hidden = true;
      return;
    }
    cerrarMenu();
  }

  function cambiarOpacidad(id, valor) {
    const v = Math.max(0.05, Math.min(1, valor / 100));
    descendientes(id).forEach((d) => { s.opacidad[d] = v; reestilar(d); });
    $("lg-opacidad-texto").textContent = `${Math.round(v * 100)}%`;
    guardarEstado();
  }

  // ------------------------------------------------------------------ panel: ancho, plegar, avisos
  function aplicarAncho() {
    const panel = $("lugares");
    const ancho = s.plegado ? 0 : s.ancho;
    panel.hidden = s.plegado;
    $("abrir-lugares").hidden = !s.plegado;
    panel.style.width = `${s.ancho}px`;
    document.documentElement.style.setProperty("--ancho-lugares", `${ancho}px`);   // + the menu: --ocupado-izquierda
    if (mapa) mapa.invalidateSize({ pan: false });
    pintar();
  }

  function avisar(texto, error = false) {
    const caja = $("lg-estado");
    caja.textContent = texto || "";
    caja.hidden = !texto;
    caja.classList.toggle("error", !!error);
  }

  let controlPostes = null;
  function actualizarAvisoPostes() {
    if (!controlPostes) return;
    const hay = [...s.marcadas].some((id) => carpeta(id) && carpeta(id).postes);
    controlPostes.getContainer().hidden = !(hay && mapa.getZoom() < ZOOM_POSTES);
  }

  function conectar() {
    const caja = $("lg-arbol");
    caja.addEventListener("scroll", pintar);
    new ResizeObserver(pintar).observe(caja);
    $("lg-filas").addEventListener("click", (e) => {
      const flecha = e.target.closest("[data-expandir]");
      if (flecha) { expandir(flecha.dataset.expandir); return; }
      const casilla = e.target.closest("[data-casilla]");
      if (casilla) { marcarCarpeta(casilla.dataset.casilla, estado(casilla.dataset.casilla) !== "on"); return; }
      const elem = e.target.closest("[data-elemento]");
      if (elem) { const [id, i] = elem.dataset.elemento.split(":"); marcarElemento(id, Number(i), elem.checked); return; }
      const fila = e.target.closest("[data-fila]");
      if (fila) { const f = s.filas[Number(fila.dataset.fila)]; s.seleccion = f ? { id: f.id, i: f.i } : null; pintar(); }
    });
    $("lg-filas").addEventListener("dblclick", (e) => {
      if (e.target.closest(".lg-casilla, [data-expandir]")) return;
      const fila = e.target.closest("[data-fila]");
      const f = fila && s.filas[Number(fila.dataset.fila)];
      if (!f) return;
      if (f.t === "carpeta") encuadrar(f.id); else if (f.t === "elemento") volarA(f.id, f.i);
    });
    $("lg-filas").addEventListener("contextmenu", (e) => {
      const fila = e.target.closest(".lg-fila.carpeta");
      if (!fila) return;
      e.preventDefault();
      e.stopPropagation();
      abrirMenu(s.filas[Number(fila.dataset.fila)].id, e.clientX, e.clientY);
    });
    $("lg-menu").addEventListener("click", (e) => { const li = e.target.closest("[data-lg-accion]"); if (li) accionMenu(li.dataset.lgAccion); });
    $("lg-opacidad-valor").addEventListener("input", (e) => cambiarOpacidad($("lg-opacidad").dataset.id, Number(e.target.value)));
    $("lg-opacidad-cerrar").addEventListener("click", cerrarMenu);
    document.addEventListener("mousedown", (e) => {
      if (!e.target.closest("#lg-menu, #lg-opacidad")) cerrarMenu();
    });
    let temporizador = null;
    $("lg-buscar").addEventListener("input", (e) => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => {
        s.busqueda = e.target.value.trim();
        if (s.busqueda && !s.indice && !s.cargaIndice) cargarIndice();
        $("lg-arbol").scrollTop = 0;
        refrescar();
      }, 200);
    });
    $("lg-buscar").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const f = s.filas.find((x) => x.t === "elemento" || x.t === "carpeta"); if (f) (f.t === "elemento" ? volarA(f.id, f.i) : encuadrar(f.id)); }
      if (e.key === "Escape") { e.target.value = ""; s.busqueda = ""; refrescar(); }
    });
    $("lg-en-descripcion").addEventListener("change", (e) => {
      s.enDescripcion = e.target.checked;
      if (s.enDescripcion && !s.indice && !s.cargaIndice) cargarIndice();
      refrescar();
    });
    $("lg-distintivos").addEventListener("change", (e) => {
      s.distintivos = e.target.checked;
      s.capas.forEach((_, id) => { if (carpeta(id).troncal) reestilar(id); });
      actualizarLeyendaTroncales();
      guardarEstado();
    });
    $("lg-restablecer").addEventListener("click", () => {
      estadoInicial();
      s.capas.forEach((capa) => capa.items.forEach((it) => { if (it && !capa.grupo.hasLayer(it.capa)) capa.grupo.addLayer(it.capa); }));
      s.capas.forEach((_, id) => reestilar(id));
      $("lg-distintivos").checked = true;
      cambio();
      avisar("Capas restablecidas: solo las troncales encendidas");
      setTimeout(() => avisar(""), 3000);
    });
    $("lg-plegar").addEventListener("click", () => { s.plegado = true; aplicarAncho(); guardarEstado(); });
    $("abrir-lugares").addEventListener("click", () => { s.plegado = false; aplicarAncho(); guardarEstado(); });
    // width: drag the right edge
    const tirador = $("lg-tirador");
    tirador.addEventListener("pointerdown", (e) => {
      tirador.setPointerCapture(e.pointerId);
      tirador.classList.add("activo");
      const mover = (ev) => {
        const izquierda = $("lugares").getBoundingClientRect().left;
        s.ancho = Math.max(ANCHO_MIN, Math.min(ANCHO_MAX, ev.clientX - izquierda));
        aplicarAncho();
      };
      const soltar = () => {
        tirador.classList.remove("activo");
        tirador.removeEventListener("pointermove", mover);
        tirador.removeEventListener("pointerup", soltar);
        guardarEstado();
      };
      tirador.addEventListener("pointermove", mover);
      tirador.addEventListener("pointerup", soltar);
    });
    // photos: thumbnail -> large
    document.addEventListener("click", (e) => {
      const diagrama = e.target.closest("[data-diagrama-mufa]");
      if (diagrama && window.visor) window.visor.abrirDiagramaPorNombre(diagrama.dataset.diagramaMufa);
      const img = e.target.closest("img.lg-foto");
      if (img && img.src) verFotoGrande(img.src);
      if (e.target.closest("#lg-foto-grande")) $("lg-foto-grande").hidden = true;
    });
    mapa.on("zoomend", () => {
      Object.keys(s.carpetas).forEach((id) => { if (carpeta(id).postes && s.marcadas.has(id)) aplicar(id); });
      actualizarAvisoPostes();
    });
    mapa.on("moveend", () => { s.capas.forEach((capa, id) => { if (capa.enMapa) dibujarEtiquetas(id); }); });
  }

  async function cargarIndice() {
    s.cargaIndice = (async () => {
      let r;
      try { r = await api.kmz_indice(); } catch (e) { r = { ok: false, error: String(e) }; }
      if (r.ok) s.indice = r.indice; else avisar(`Búsqueda solo por carpetas: ${r.error}`, true);
      s.cargaIndice = null;
      refrescar();
    })();
    refrescar();
  }

  // ------------------------------------------------------------------ arranque
  async function iniciar(contexto) {
    ctx = contexto;
    mapa = ctx.mapa; api = ctx.api; esc = ctx.esc;
    mapa.createPane("kmzLineas").style.zIndex = 360;      // over the Visio network (350), under the route (400)
    mapa.createPane("kmzPuntos").style.zIndex = 590;      // under the route markers (600)
    mapa.createPane("kmzEtiquetas").style.zIndex = 595;
    mapa.getPane("kmzEtiquetas").style.pointerEvents = "none";
    lienzo = L.canvas({ pane: "kmzLineas", padding: 0.3, tolerance: 4 });
    crearLeyendaTroncales();
    controlPostes = L.control({ position: "bottomleft" });
    controlPostes.onAdd = () => {
      const div = L.DomUtil.create("div", "estado-red aviso-postes");
      div.textContent = `Acerque para ver postes (zoom ${ZOOM_POSTES} o más)`;
      div.hidden = true;
      return div;
    };
    controlPostes.addTo(mapa);
    conectar();
    aplicarAncho();

    // Import progress while kmz_arbol works (local mode: ~15 s the first time or with a new KMZ).
    let terminado = false;
    avisar("Cargando la red KMZ…");
    const sondeo = setInterval(async () => {
      if (terminado) return;
      try {
        const p = await api.kmz_progreso();
        if (p && p.activo && !terminado) avisar(`Importando el KMZ: ${p.texto} (${Math.round((p.fraccion || 0) * 100)}%)`);
      } catch (e) { /* ignore */ }
    }, 700);
    let r, guardado = null;
    try {
      [r, guardado] = await Promise.all([api.kmz_arbol(), api.capas_estado().then((x) => x && x.estado).catch(() => null)]);
    } catch (e) {
      r = { ok: false, error: String(e) };
    } finally {
      terminado = true;
      clearInterval(sondeo);
    }
    if (!r || !r.ok) {
      avisar(`Red KMZ no disponible: ${(r && r.error) || "sin respuesta"}`, true);
      if (guardado) restaurar(guardado);
      aplicarAncho();
      return;
    }
    s.arbol = r.arbol;
    s.carpetas = r.arbol.carpetas;
    s.raiz = r.arbol.raiz;
    s.iconos = r.iconos || {};
    restaurar(guardado);
    $("lg-distintivos").checked = s.distintivos;
    aplicarAncho();
    $("lg-info").textContent = `${r.arbol.kmz} · ${Number(r.arbol.elementos).toLocaleString("en-US")} elementos · importado ${r.arbol.importado}`;
    avisar(r.arbol.aviso || "");
    refrescar();
    await aplicarTodas();
    refrescar();
  }

  window.Lugares = {
    iniciar,
    // read-only handle for automated checks
    get estado() { return { carpetas: Object.keys(s.carpetas).length, marcadas: [...s.marcadas], cargadas: [...s.capas.keys()], filas: s.filas.length }; },
    _s: s, _marcarCarpeta: marcarCarpeta, _expandir: expandir, _volarA: volarA, _resaltar: resaltar,
  };
})();
