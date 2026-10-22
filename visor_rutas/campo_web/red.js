/* App de campo: la red de referencia (mufas, postes y líneas del KMZ y de la red base) alrededor del técnico, por zonas de 0,02° (~2 km).
 *
 * Cada zona se pide una vez a /visor/campo/red y se guarda en el teléfono (IndexedDB, almacén «red»): se renueva si tiene más de 12 horas y, sin señal,
 * se usa la que haya aunque esté vieja. Solo se dibuja lo que cae en pantalla y desde cierto zoom (líneas desde 15, puntos desde 16). */
(function () {
  "use strict";
  const CELDA = 0.02, VIGENCIA_MS = 12 * 3600 * 1000, ZOOM_LINEAS = 15, ZOOM_PUNTOS = 16, MAX_CELDAS = 9, ESPERA_MS = 500;

  let mapa = null, api = null, cola = null, capa = null, canvas = null, visible = true, alTocar = null, aviso = null, temporizador = null;
  const celdas = new Map();                 // zone key -> {puntos, lineas, hora}
  const pidiendo = new Map();               // zone key -> promise (one request at a time per zone)

  const claveDe = (i, j) => `${i}_${j}`;
  const caja = (i, j) => ({ o: +(j * CELDA).toFixed(5), s: +(i * CELDA).toFixed(5), e: +((j + 1) * CELDA).toFixed(5), n: +((i + 1) * CELDA).toFixed(5) });

  function celdasDe(b) {
    const lista = [];
    for (let i = Math.floor(b.getSouth() / CELDA); i <= Math.floor(b.getNorth() / CELDA); i++) {
      for (let j = Math.floor(b.getWest() / CELDA); j <= Math.floor(b.getEast() / CELDA); j++) lista.push([i, j]);
    }
    return lista.length > MAX_CELDAS ? [] : lista;
  }

  /* The zone from memory, from the phone's store (if it is fresh, or the server does not answer), or from the server. */
  async function zona(i, j) {
    const k = claveDe(i, j);
    if (pidiendo.has(k)) return pidiendo.get(k);
    const p = (async () => {
      let guardada = celdas.get(k);
      if (!guardada && cola) { try { const r = await cola.redLeer(k); if (r) guardada = { ...r.datos, hora: r.hora }; } catch (e) { /* no store */ } }
      if (guardada && Date.now() - guardada.hora < VIGENCIA_MS) { celdas.set(k, guardada); return guardada; }
      if (navigator.onLine !== false) {
        try {
          const c = caja(i, j), r = await api.red(c.o, c.s, c.e, c.n);
          const datos = { puntos: r.puntos || [], lineas: r.lineas || [], hora: Date.now(), truncado: !!r.truncado };
          celdas.set(k, datos);
          aviso = r.aviso || null;
          if (cola) { try { await cola.redGuardar(k, datos); } catch (e) { /* no store */ } }
          return datos;
        } catch (e) { /* no signal / no role: the old one, if there is */ }
      }
      if (guardada) celdas.set(k, guardada);
      return guardada || null;
    })();
    pidiendo.set(k, p);
    try { return await p; } finally { pidiendo.delete(k); }
  }

  const COLOR = (t) => { const s = String(t || "").toLowerCase(); return s.includes("mufa") || s === "odf" || s === "nodo" ? "#1e88e5" : s.includes("poste") ? "#8d6e63" : s.includes("reserva") ? "#fb8c00" : "#78909c"; };

  async function actualizar() {
    if (!mapa || !capa) return;
    capa.clearLayers();
    if (!visible) return;
    const z = mapa.getZoom();
    if (z < ZOOM_LINEAS) return;
    const grande = mapa.getBounds().pad(0.25);
    const pedidas = await Promise.all(celdasDe(mapa.getBounds()).map(([i, j]) => zona(i, j)));
    if (!capa || mapa.getZoom() !== z) return;
    capa.clearLayers();
    const vistos = new Set();
    pedidas.filter(Boolean).forEach((d) => {
      d.lineas.forEach((l) => {
        if (vistos.has(l.id)) return; vistos.add(l.id);
        if (l.c.some(([la, lo]) => grande.contains([la, lo]))) L.polyline(l.c, { color: l.t === "cable" ? "#ffeb3b" : "#26c6da", weight: 2, opacity: 0.85, interactive: false, renderer: canvas }).addTo(capa);
      });
      if (z < ZOOM_PUNTOS) return;
      d.puntos.forEach((p) => {
        if (vistos.has(p.id) || !grande.contains([p.lat, p.lon])) return; vistos.add(p.id);
        const m = L.circleMarker([p.lat, p.lon], { radius: 6, weight: 2, color: "#fff", fillColor: COLOR(p.t), fillOpacity: 1, renderer: canvas }).addTo(capa);
        m.bindTooltip(`${p.n || "(sin nombre)"}${p.t ? " · " + p.t : ""}`, { direction: "top" });
        m.on("click", (e) => {
          const C = window.Campo;
          if (alTocar) { L.DomEvent.stop(e); alTocar(p); }
          else if (C && C.tarjeta && !(C.captura && C.captura.activa())) { L.DomEvent.stop(e); C.tarjeta.mostrarRed(p); }
          else m.openTooltip();
        });
      });
    });
  }

  function programar() { clearTimeout(temporizador); temporizador = setTimeout(() => { actualizar().catch(() => {}); }, ESPERA_MS); }

  function iniciar(mapaLeaflet, clienteApi, colaIdb) {
    mapa = mapaLeaflet; api = clienteApi; cola = colaIdb;
    canvas = L.canvas({ padding: 0.3 });
    capa = L.layerGroup().addTo(mapa);
    mapa.on("moveend", programar);
    programar();
  }

  /* The nearest point of the reference network within `metros` of a position (from the zones already loaded), or null. */
  function cercano(lat, lon, metros) {
    let mejor = null;
    celdas.forEach((d) => d.puntos.forEach((p) => {
      const dist = window.CampoTrazo.distanciaM({ lat, lon }, p);
      if (dist <= metros && (!mejor || dist < mejor.distancia_m)) mejor = { ...p, distancia_m: dist };
    }));
    return mejor;
  }

  /* Poles and mufas already loaded whose name contains the text (at most `max`), nearest to the map centre first. */
  function buscar(texto, max) {
    const q = String(texto || "").trim().toLowerCase();
    if (!q) return [];
    const c = mapa ? mapa.getCenter() : null, vistos = new Set(), r = [];
    celdas.forEach((d) => d.puntos.forEach((p) => {
      if (vistos.has(p.id) || !String(p.n || "").toLowerCase().includes(q)) return;
      vistos.add(p.id);
      r.push({ ...p, d: c ? window.CampoTrazo.distanciaM({ lat: c.lat, lon: c.lng }, p) : 0 });
    }));
    return r.sort((a, b) => a.d - b.d).slice(0, max || 30);
  }

  window.CampoRed = {
    iniciar, actualizar: programar, cercano, buscar,
    alternar() { visible = !visible; programar(); return visible; },
    get visible() { return visible; }, get aviso() { return aviso; },
    alTocar(f) { alTocar = f; }, celdas: () => celdas.size, dibujados: () => (capa ? capa.getLayers().length : 0),
  };
})();
