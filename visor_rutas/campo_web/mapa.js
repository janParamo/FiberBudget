/* App de campo: el mapa (Leaflet local, pantalla completa), la ubicación en vivo con su círculo de precisión y los puntos / cables dibujados. */
(function () {
  "use strict";
  const NICARAGUA = [12.87, -85.2];
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const CAPAS = {
    satelite: { titulo: "Satélite", detalle: "Esri World Imagery", capas: [[`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, 19]] },
    hibrido: { titulo: "Satélite con calles", detalle: "Imagen + nombres de calles", capas: [[`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, 19], [`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, 19]] },
    calles: { titulo: "Calles", detalle: "OpenStreetMap", capas: [["https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19]] },
    calles_esri: { titulo: "Calles (Esri)", detalle: "Esri World Street Map", capas: [[`${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`, 19]] },
  };
  const COLOR_TIPO = { poste: "#8d6e63", mufa: "#1e88e5", reserva: "#fb8c00", solitaria: "#8e24aa", cliente: "#43a047", otro: "#546e7a", cable: "#00acc1" };
  const LETRA = { poste: "P", mufa: "M", reserva: "R", solitaria: "S", cliente: "C", otro: "O" };
  const COLOR_ESTADO = { pendiente: "#ffd400", editado: "#ff8c1a", aprobado: "#1b9e4b", rechazado: "#8a8f98", cola: "#ffffff", error: "#e53935" };

  let mapa, capasBase = [], nombreCapa = "satelite", yo, circulo, marcas, lineas, capaTrazo, temporal, control = null;
  let ultima = null, vigilante = null, seguir = true;
  const oyentes = new Set();
  const estadoGps = { error: null };

  function iniciar(idMapa, opciones) {
    const o = opciones || {};
    mapa = L.map(idMapa, { zoomControl: false, attributionControl: false, tap: true }).setView(NICARAGUA, 7);
    ponerCapa(o.capa || nombreCapa);
    lineas = L.layerGroup().addTo(mapa);
    marcas = L.layerGroup().addTo(mapa);
    capaTrazo = L.layerGroup().addTo(mapa);
    temporal = L.layerGroup().addTo(mapa);
    mapa.on("dragstart", () => { seguir = false; });
    zoom(!!o.zoom);
    return mapa;
  }

  function ponerCapa(nombre) {
    if (!CAPAS[nombre]) return nombreCapa;
    nombreCapa = nombre;
    capasBase.forEach((c) => mapa.removeLayer(c));
    capasBase = CAPAS[nombre].capas.map(([url, max]) => L.tileLayer(url, { maxZoom: max, maxNativeZoom: max, attribution: CAPAS[nombre].detalle, crossOrigin: true }).addTo(mapa));
    capasBase.forEach((c) => c.bringToBack());
    return nombre;
  }

  function zoom(mostrar) {
    if (mostrar && !control) control = L.control.zoom({ position: "bottomleft", zoomInTitle: "Acercar", zoomOutTitle: "Alejar" }).addTo(mapa);
    else if (!mostrar && control) { control.remove(); control = null; }
  }

  function alRecibir(pos) {
    const c = pos.coords;
    ultima = { lat: c.latitude, lon: c.longitude, precision_m: c.accuracy, altitud: c.altitude, hora: pos.timestamp || Date.now() };
    estadoGps.error = null;
    const ll = [ultima.lat, ultima.lon];
    if (mapa) {
      if (!yo) {
        yo = L.marker(ll, { icon: L.divIcon({ className: "", html: '<div class="yo"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(mapa);
        circulo = L.circle(ll, { radius: c.accuracy, color: "#1a73e8", weight: 1, fillOpacity: 0.12, interactive: false }).addTo(mapa);
        mapa.setView(ll, 18);
      } else { yo.setLatLng(ll); circulo.setLatLng(ll).setRadius(c.accuracy); if (seguir) mapa.panTo(ll, { animate: true }); }
    }
    oyentes.forEach((f) => f(ultima, null));
  }

  function alFallar(e) {
    estadoGps.error = e.code === 1 ? "Permita la ubicación para esta página en el teléfono" : e.code === 2 ? "No hay señal de GPS" : "El GPS tardó demasiado";
    oyentes.forEach((f) => f(ultima, estadoGps.error));
  }

  function vigilar() {
    if (vigilante != null || !navigator.geolocation) { if (!navigator.geolocation) alFallar({ code: 2 }); return; }
    vigilante = navigator.geolocation.watchPosition(alRecibir, alFallar, { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
  }

  /* ---------------------------------------------------------------- lo dibujado */
  const pinHtml = (tipo, estado, extra) => `<div class="pin t-${tipo} e-${estado}${extra ? " " + extra : ""}" style="--c:${COLOR_TIPO[tipo] || "#546e7a"};--e:${COLOR_ESTADO[estado] || "#ffd400"}"><span>${LETRA[tipo] || "·"}</span></div>`;

  /* `punto`: {lat, lon, tipo, estado, nombre}; `alTocar(punto)` al tocarlo */
  function marcar(punto, alTocar) {
    const m = L.marker([punto.lat, punto.lon], { icon: L.divIcon({ className: "", html: pinHtml(punto.tipo, punto.estado), iconSize: [30, 30], iconAnchor: [15, 15] }), title: punto.nombre, keyboard: false });
    if (alTocar) m.on("click", (e) => { L.DomEvent.stop(e); alTocar(punto); });
    m.addTo(marcas);
    return m;
  }

  /* un cable ya enviado o guardado en el teléfono: del color de su estado (punteado mientras no se envía) */
  function marcarLinea(puntos, estado, alTocar) {
    const l = L.polyline(puntos.map((p) => [p.lat, p.lon]), { color: COLOR_ESTADO[estado] || "#ffd400", weight: 5, opacity: 0.92, dashArray: estado === "cola" || estado === "error" ? "8 8" : null });
    const borde = L.polyline(puntos.map((p) => [p.lat, p.lon]), { color: "#111", weight: 8, opacity: 0.45, interactive: false });
    if (alTocar) l.on("click", (e) => { L.DomEvent.stop(e); alTocar(); });
    borde.addTo(lineas); l.addTo(lineas);
    return l;
  }

  const limpiarMarcas = () => { if (marcas) marcas.clearLayers(); if (lineas) lineas.clearLayers(); };

  /* el cable que se está trazando: su línea y un círculo en cada vértice (el elegido más grande; los pegados a un poste, en verde) */
  function pintarTrazo(vertices, elegido) {
    capaTrazo.clearLayers();
    if (vertices.length >= 2) L.polyline(vertices.map((v) => [v.lat, v.lon]), { color: "#e53935", weight: 4, opacity: 0.95, interactive: false }).addTo(capaTrazo);
    vertices.forEach((v, i) => L.circleMarker([v.lat, v.lon], { radius: i === elegido ? 9 : 5, color: i === elegido ? "#ffd400" : "#fff", weight: i === elegido ? 3 : 2,
      fillColor: v.poste ? "#1b9e4b" : "#e53935", fillOpacity: 1, interactive: false }).addTo(capaTrazo));
  }
  const limpiarTrazo = () => capaTrazo && capaTrazo.clearLayers();

  /* un lugar encontrado (búsqueda): un círculo con un anillo que se quita solo al tocar el mapa */
  function ponerTemporal(lat, lon) {
    temporal.clearLayers();
    L.circleMarker([lat, lon], { radius: 13, color: "#ffd400", weight: 4, fillColor: "#e53935", fillOpacity: 0.9, interactive: false }).addTo(temporal);
  }
  const quitarTemporal = () => temporal && temporal.clearLayers();

  const centrar = () => { seguir = true; if (ultima) mapa.setView([ultima.lat, ultima.lon], Math.max(mapa.getZoom(), 18)); };
  const irA = (lat, lon, z) => { seguir = false; mapa.setView([lat, lon], z || Math.max(mapa.getZoom(), 18), { animate: false }); };
  const ajustarA = (puntos) => { if (puntos.length) { seguir = false; mapa.fitBounds(L.latLngBounds(puntos.map((p) => [p.lat, p.lon])), { padding: [60, 60], maxZoom: 19 }); } };

  window.CampoMapa = {
    iniciar, ponerCapa, zoom, vigilar, marcar, marcarLinea, limpiarMarcas, pintarTrazo, limpiarTrazo, ponerTemporal, quitarTemporal, centrar, irA, ajustarA,
    CAPAS, capaActual: () => nombreCapa, pinHtml,
    leaflet: () => mapa, puntoEnPantalla: (lat, lon) => mapa.latLngToContainerPoint([lat, lon]),
    ultima: () => ultima, error: () => estadoGps.error, centro: () => { const c = mapa.getCenter(); return { lat: c.lat, lon: c.lng }; },
    cuandoCambie: (f) => { oyentes.add(f); return () => oyentes.delete(f); },
    ajustar: () => mapa && mapa.invalidateSize(), seguirGps: (v) => { seguir = !!v; },
  };
})();
