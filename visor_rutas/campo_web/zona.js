/* App de campo: «Descargar esta zona» para trabajar sin señal.
 *
 * Guarda en el teléfono los mosaicos del mapa que se ven (cache «campo-zonas», que el service worker consulta primero y nunca recorta) y la red existente
 * (mufas y postes) de esa área (los mismos almacenes de red.js). Las zonas descargadas se recuerdan en localStorage («campo.zonas»), se pueden borrar una a
 * una y no se vuelven a pedir los mosaicos que ya están. Solo se descargan mapas de Esri: OpenStreetMap no permite descargas masivas. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const CACHE = "campo-zonas", CLAVE = "campo.zonas";
  const ZOOM_MINIMO = 12, ZOOM_MAXIMO = 18, MAX_ZONA = 2500, MAX_TOTAL = 8000, SIMULTANEAS = 6, MAX_CELDAS_RED = 80;
  const M = () => window.CampoMapa;

  /* ---------------------------------------------------------------- mosaicos de una zona (cuadrícula «slippy» de Web Mercator) */
  const tileX = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
  const tileY = (lat, z) => { const r = (lat * Math.PI) / 180; return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z); };
  const limitar = (v, z) => Math.max(0, Math.min(2 ** z - 1, v));

  function rango(z, c) {
    return { x0: limitar(tileX(c.oeste, z), z), x1: limitar(tileX(c.este, z), z), y0: limitar(tileY(c.norte, z), z), y1: limitar(tileY(c.sur, z), z) };
  }

  function contar(c, zmin, zmax) {
    let n = 0;
    for (let z = zmin; z <= zmax; z++) { const r = rango(z, c); n += (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1); }
    return n;
  }

  /* las direcciones de los mosaicos de todas las capas de un mapa base, para una zona y sus niveles */
  function direcciones(capa, c, zmin, zmax) {
    const plantillas = M().CAPAS[capa].capas.map(([url]) => url), lista = [];
    for (let z = zmin; z <= zmax; z++) {
      const r = rango(z, c);
      for (let x = r.x0; x <= r.x1; x++) for (let y = r.y0; y <= r.y1; y++) plantillas.forEach((p) => lista.push(p.replace("{z}", z).replace("{x}", x).replace("{y}", y)));
    }
    return lista;
  }

  /* lo que pesa un mosaico, para avisar antes de descargar (imagen satelital ~26 KB, nombres de calles ~8 KB, calles ~18 KB) */
  const KB_MOSAICO = (url) => (url.includes("World_Imagery") ? 26 : url.includes("Reference") || url.includes("Transportation") ? 8 : 18);
  const kbPorMosaico = (capa) => M().CAPAS[capa].capas.reduce((s, [url]) => s + KB_MOSAICO(url), 0);
  const permitida = (capa) => M().CAPAS[capa].capas.every(([url]) => new URL(url).hostname.endsWith("arcgisonline.com"));
  const mb = (bytes) => (bytes < 1048576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(bytes < 10485760 ? 1 : 0)} MB`);

  /* ---------------------------------------------------------------- zonas guardadas */
  const zonas = () => (Array.isArray(C.leer(CLAVE)) ? C.leer(CLAVE) : []);
  const guardarZonas = (l) => C.guardar(CLAVE, l.length ? l : null);
  const totalMosaicos = () => zonas().reduce((s, z) => s + (z.mosaicos || 0), 0);
  const cajaDe = (z) => ({ oeste: z.oeste, sur: z.sur, este: z.este, norte: z.norte });

  function resumen() {
    const l = zonas();
    if (!l.length) return "Mapa y red para trabajar sin señal";
    return `${l.length} zona${l.length === 1 ? "" : "s"} · ${mb(l.reduce((s, z) => s + (z.bytes || 0), 0))}`;
  }

  async function borrar(id) {
    const l = zonas(), z = l.find((x) => x.id === id);
    if (!z) return 0;
    const restantes = l.filter((x) => x.id !== id);
    const conservar = new Set();
    restantes.forEach((o) => { if (o.capa && M().CAPAS[o.capa]) direcciones(o.capa, cajaDe(o), o.zmin, o.zmax).forEach((u) => conservar.add(u)); });
    let n = 0;
    if (z.capa && M().CAPAS[z.capa]) {
      const cache = await caches.open(CACHE);
      for (const u of direcciones(z.capa, cajaDe(z), z.zmin, z.zmax)) if (!conservar.has(u) && (await cache.delete(u))) n++;
    }
    guardarZonas(restantes);
    return n;
  }

  /* ---------------------------------------------------------------- descarga */
  async function espacio() {
    try {
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
      if (navigator.storage && navigator.storage.estimate) { const e = await navigator.storage.estimate(); return e.quota ? e.quota - (e.usage || 0) : Infinity; }
    } catch (err) { /* sin dato: se intenta */ }
    return Infinity;
  }

  function avisarAlServiceWorker(activa) {
    try { if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ tipo: "zona", activa }); } catch (e) { /* sin service worker */ }
  }

  /* Baja los mosaicos de la lista (6 a la vez) a la cache de zonas. `progreso(hechos, total)`; `cancelado()` los detiene. */
  async function bajar(urls, progreso, cancelado) {
    const cache = await caches.open(CACHE);
    const r = { hechos: 0, nuevos: 0, fallidos: 0, bytes: 0 };
    let i = 0;
    async function uno(u) {
      if (await cache.match(u, { ignoreVary: true })) return;
      for (let intento = 0; intento < 2; intento++) {
        try {
          const resp = await window.fetch(u, { mode: "cors", credentials: "omit" });
          if (!resp.ok) throw new Error(String(resp.status));
          const copia = resp.clone();
          await cache.put(u, resp);
          r.bytes += (await copia.blob()).size;
          r.nuevos++;
          return;
        } catch (e) { if (cancelado()) return; }
      }
      r.fallidos++;
    }
    async function trabajador() {
      while (!cancelado()) {
        const k = i++;
        if (k >= urls.length) return;
        await uno(urls[k]);
        r.hechos++;
        progreso(r.hechos, urls.length);
      }
    }
    await Promise.all(Array.from({ length: Math.min(SIMULTANEAS, urls.length) }, trabajador));
    return r;
  }

  /* ---------------------------------------------------------------- pantallas */
  function opcionesDeNivel(c, z, capa) {
    const kb = kbPorMosaico(capa), zmin = Math.max(ZOOM_MINIMO - 1, z - 2);
    const hasta = [Math.min(ZOOM_MAXIMO, z + 2), ZOOM_MAXIMO].filter((v, i, a) => v >= z && a.indexOf(v) === i);
    return hasta.map((zmax) => {
      const n = contar(c, zmin, zmax) * M().CAPAS[capa].capas.length;
      return { zmin, zmax, mosaicos: n, kb: contar(c, zmin, zmax) * kb, cabe: n <= MAX_ZONA * M().CAPAS[capa].capas.length };
    });
  }

  function cuerpoPrincipal(capa, opciones, hayRed) {
    const primero = Math.max(0, opciones.findIndex((o) => o.cabe));
    const radios = opciones.map((o, i) => `<label class="dlg-check"><input type="radio" name="zn-nivel" value="${i}" ${i === primero ? "checked" : ""} ${o.cabe ? "" : "disabled"}>
      <span><b>${opciones.length > 1 && i === opciones.length - 1 ? "Con todo el detalle" : "Calles y postes"}</b><small class="nota"> (acercar hasta el nivel ${o.zmax}): ${o.mosaicos.toLocaleString("es")} mosaicos, ~${mb(o.kb * 1024)}${o.cabe ? "" : " — demasiado grande, acerque el mapa"}</small></span></label>`).join("");
    const lista = zonas();
    const guardadas = lista.length ? `<h3 class="dlg-grupo">Zonas descargadas</h3><ul class="dlg-lista">${lista.map((z) => `<li><button type="button" class="dlg-opcion" data-dlg='${C.esc(JSON.stringify("borrar:" + z.id))}'>${C.iconos.svg("basura")}<span><b>${C.esc(z.nombre)}</b><small>${z.mosaicos.toLocaleString("es")} mosaicos · ${mb(z.bytes || 0)}${z.parcial ? " · incompleta" : ""} · toque para borrarla</small></span></button></li>`).join("")}</ul>` : "";
    return `<p>Guarda en el teléfono el mapa <b>${C.esc(M().CAPAS[capa].titulo)}</b> de lo que se ve ahora, para verlo sin señal.</p>${radios}
      <label class="dlg-check"><input type="checkbox" id="zn-red" ${hayRed ? "checked" : "disabled"}><span>Incluir mufas y postes existentes</span></label>
      <p class="nota">Conviene bajarlo con buena señal o Wi-Fi.</p>${guardadas}`;
  }

  async function descargar(capa, nivel, conRed, caja) {
    const urls = direcciones(capa, caja, nivel.zmin, nivel.zmax);
    const libre = await espacio();
    if (urls.length * (kbPorMosaico(capa) / M().CAPAS[capa].capas.length) * 1024 > libre * 0.9) { C.aviso("No hay espacio suficiente en el teléfono para esta zona", "malo"); return; }
    const estado = { cancelado: false };
    let proceso = null;
    avisarAlServiceWorker(true);
    const dialogo = C.dialogo.mostrar({
      titulo: "Descargando la zona",
      cuerpo: `<p id="zn-texto">Mosaicos del mapa…</p><progress id="zn-barra" max="${urls.length}" value="0" style="width:100%"></progress><p class="nota" id="zn-detalle"></p>`,
      botones: [{ texto: "Cancelar", valor: "cancelar" }],
      alMostrar: (raiz) => {
        const barra = raiz.querySelector("#zn-barra"), detalle = raiz.querySelector("#zn-detalle");
        proceso = (async () => {
          const r = await bajar(urls, (h, t) => { barra.value = h; detalle.textContent = `${h.toLocaleString("es")} de ${t.toLocaleString("es")}`; }, () => estado.cancelado);
          let red = null;
          if (conRed && !estado.cancelado && window.CampoRed && window.CampoRed.precargar) {
            raiz.querySelector("#zn-texto").textContent = "Mufas y postes de la zona…"; barra.value = 0; detalle.textContent = "";
            red = await window.CampoRed.precargar(L.latLngBounds([caja.sur, caja.oeste], [caja.norte, caja.este]), (h, t) => { barra.max = t; barra.value = h; detalle.textContent = `${h} de ${t} cuadros`; }, () => estado.cancelado);
          }
          return { r, red };
        })();
      },
    });
    dialogo.then((v) => { if (v === "cancelar") estado.cancelado = true; });
    let salida;
    try { salida = await proceso; } finally { avisarAlServiceWorker(false); }
    if (C.dialogo.abierto()) C.dialogo.cerrar();
    const { r, red } = salida;
    const completa = !estado.cancelado && r.fallidos === 0;
    if (r.nuevos || r.hechos) {
      const total = urls.length;
      const l = zonas();
      l.push({ id: String(Date.now()), capa, nombre: `${M().CAPAS[capa].titulo} · ${C.fecha(new Date()).slice(0, 16).replace(/\//g, "-")}`, oeste: caja.oeste, sur: caja.sur, este: caja.este, norte: caja.norte,
               zmin: nivel.zmin, zmax: nivel.zmax, mosaicos: total - r.fallidos, bytes: r.bytes, red: red ? red.celdas : 0, parcial: !completa, fecha: Date.now() });
      guardarZonas(l);
    }
    if (estado.cancelado) C.aviso("Descarga cancelada: se conservó lo ya descargado", "malo");
    else if (r.fallidos) C.aviso(`Zona descargada con ${r.fallidos} mosaicos que no llegaron (sin señal). Vuelva a intentarlo para completarla`, "malo");
    else C.aviso(`Zona lista: ${urls.length.toLocaleString("es")} mosaicos${red && red.celdas ? " y la red existente" : ""} para usar sin señal`, "ok");
    return { r, red };
  }

  async function abrir() {
    const mapa = M() && M().leaflet();
    if (!mapa) return;
    if (navigator.onLine === false) { C.aviso("Sin señal: la zona se descarga con conexión", "malo"); return; }
    const capa = M().capaActual();
    if (!permitida(capa)) { C.aviso("OpenStreetMap no permite descargar el mapa: cambie el tipo de mapa a Satélite o a Calles (Esri)", "malo"); return; }
    const z = Math.round(mapa.getZoom());
    if (z < ZOOM_MINIMO) { C.aviso("Acerque el mapa a la zona que necesita (se ve muy grande para descargarla)", "malo"); return; }
    const b = mapa.getBounds(), caja = { oeste: +b.getWest().toFixed(6), sur: +b.getSouth().toFixed(6), este: +b.getEast().toFixed(6), norte: +b.getNorth().toFixed(6) };
    const opciones = opcionesDeNivel(caja, z, capa);
    if (totalMosaicos() >= MAX_TOTAL) { C.aviso("Ya hay muchas zonas descargadas: borre alguna para bajar otra", "malo"); }
    const elegible = opciones.findIndex((o) => o.cabe);
    const r = await C.dialogo.mostrar({
      titulo: "Descargar esta zona",
      cuerpo: cuerpoPrincipal(capa, opciones, !!(window.CampoRed && window.CampoRed.precargar)),
      botones: elegible === -1 ? [{ texto: "Cerrar", valor: null }] : [{ texto: "Cancelar", valor: null }, { texto: "Descargar", valor: "leer", primario: true }],
      leer: (raiz) => { const sel = raiz.querySelector("input[name=zn-nivel]:checked"); return { nivel: sel ? Number(sel.value) : elegible, red: raiz.querySelector("#zn-red").checked }; },
    });
    if (r && typeof r === "string" && r.startsWith("borrar:")) {
      const z1 = zonas().find((x) => x.id === r.slice(7));
      if (z1 && (await C.dialogo.confirmar("¿Borrar esta zona?", `${z1.nombre}: se liberan ${mb(z1.bytes || 0)}. La red existente guardada se renueva sola.`, [{ texto: "Borrar", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) {
        const n = await borrar(z1.id);
        C.aviso(`Zona borrada (${n.toLocaleString("es")} mosaicos)`, "ok");
        if (C.menu) C.menu.pintarMenu();
      }
      return;
    }
    if (!r || typeof r !== "object") return;
    await descargar(capa, opciones[r.nivel], r.red, caja);
    if (C.menu) C.menu.pintarMenu();
  }

  C.zona = { abrir, resumen, borrar, zonas, contar, direcciones, bajar, permitida, MAX_ZONA, CACHE };
})();
