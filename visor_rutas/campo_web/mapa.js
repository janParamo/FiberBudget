/* App de campo: mapa (Leaflet local), ubicación en vivo con su círculo de precisión y las marcas de los puntos. */
(function () {
  "use strict";
  const NICARAGUA = [12.87, -85.2];
  const CAPAS = {
    satelite: { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", max: 19, atribucion: "Esri World Imagery" },
    calles: { url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", max: 19, atribucion: "© OpenStreetMap" },
  };

  let mapa, capaBase, yo, circulo, marcas, nombreCapa = "satelite", ultima = null, vigilante = null, seguir = true;
  const oyentes = new Set();
  const estadoGps = { error: null };

  function iniciar(idMapa) {
    mapa = L.map(idMapa, { zoomControl: false, attributionControl: false }).setView(NICARAGUA, 7);
    ponerCapa(nombreCapa);
    marcas = L.layerGroup().addTo(mapa);
    mapa.on("dragstart", () => { seguir = false; });
    return mapa;
  }

  function ponerCapa(nombre) {
    nombreCapa = nombre;
    if (capaBase) mapa.removeLayer(capaBase);
    const c = CAPAS[nombre];
    capaBase = L.tileLayer(c.url, { maxZoom: c.max, maxNativeZoom: c.max, attribution: c.atribucion, crossOrigin: true }).addTo(mapa);
    capaBase.bringToBack();
  }
  const alternarCapa = () => { ponerCapa(nombreCapa === "satelite" ? "calles" : "satelite"); return nombreCapa; };

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

  function marcar(punto, alTocar) {
    const ll = [punto.lat, punto.lon];
    const m = L.marker(ll, { icon: L.divIcon({ className: "", html: `<div class="marca ${punto.estado}"></div>`, iconSize: [22, 22], iconAnchor: [11, 11] }), title: punto.nombre });
    if (alTocar) m.on("click", () => alTocar(punto));
    m.addTo(marcas);
  }
  const limpiarMarcas = () => marcas && marcas.clearLayers();
  const centrar = () => { seguir = true; if (ultima) mapa.setView([ultima.lat, ultima.lon], Math.max(mapa.getZoom(), 18)); };

  window.CampoMapa = {
    iniciar, alternarCapa, vigilar, marcar, limpiarMarcas, centrar,
    ultima: () => ultima, centro: () => { const c = mapa.getCenter(); return { lat: c.lat, lon: c.lng }; },
    cuandoCambie: (f) => { oyentes.add(f); return () => oyentes.delete(f); },
    ajustar: () => mapa && mapa.invalidateSize(), irA: (lat, lon) => { seguir = false; mapa.setView([lat, lon], Math.max(mapa.getZoom(), 18)); },
  };
})();
