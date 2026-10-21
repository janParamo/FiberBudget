/* Varios íconos en el mismo punto (el pin de una mufa buscada sobre la mufa del KMZ y sobre su nodo Visio, un poste con su mufa, una mufa con su splitter…).
 *
 * Un clic sobre uno de ellos ya no abre «el de encima»: se abre una lista de lo que hay ahí y, a la vez, los íconos se abren en abanico debajo del punto
 * (cada uno en un círculo, unido al punto por una línea fina); un clic en uno de la lista o del abanico abre ese. Vale para TODO lo que se dibuja como
 * punto en el mapa —KMZ, ruta, nodos Visio, mufa buscada, coordenada buscada, Mis lugares— porque se engancha al clic de los marcadores y de los
 * círculos de Leaflet, no a cada capa. No actúa mientras se mide o se dibuja (modo_dibujo.js).
 *
 * Una capa puede decir cómo se llama y qué es con `capa._infoSuperpuesto = () => ({nombre, detalle})`; si no, se usa el texto de su tooltip.
 */
(function () {
  "use strict";

  const RADIO_PX = 14;          // anchors this close are «the same point»
  const MAX = 12;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const texto = (html) => { const d = document.createElement("div"); d.innerHTML = String(html ?? ""); return (d.textContent || "").replace(/\s+/g, " ").trim(); };
  let abanico = null, popupActual = null;

  function esPunto(l) {
    return !!l && (l instanceof L.Marker || (l instanceof L.CircleMarker && !(L.Circle && l instanceof L.Circle)))
      && !(L.MarkerCluster && l instanceof L.MarkerCluster) && l.options.interactive !== false && !l._pmTempLayer && !l._esAbanico && !!l._map && !!l.getLatLng;
  }

  function info(l) {
    if (l._infoSuperpuesto) return l._infoSuperpuesto();
    const t = l.getTooltip && l.getTooltip();
    let nombre = "";
    if (t) { const c = t.getContent(); nombre = texto(typeof c === "function" ? c(l) : (c instanceof Element ? c.textContent : c)); }
    return { nombre: nombre || "Elemento", detalle: "" };
  }

  function muestra(l) {
    if (l instanceof L.Marker) {
      const o = (l.options.icon && l.options.icon.options) || {};
      if (o.html) return o.html;
      if (o.iconUrl) return `<img src="${esc(o.iconUrl)}" alt="" width="22" height="22">`;
      return "";
    }
    return `<span class="sup-punto" style="background:${esc(l.options.fillColor || l.options.color || "#999")}"></span>`;
  }

  /** The point layers whose anchor is within a few pixels of the anchor of `l` (itself first). */
  function vecinos(l) {
    const mapa = l._map, p0 = mapa.latLngToContainerPoint(l.getLatLng()), lista = [[0, l]];
    mapa.eachLayer((x) => {
      if (x === l || !esPunto(x) || x._map !== mapa) return;
      const d = mapa.latLngToContainerPoint(x.getLatLng()).distanceTo(p0);
      if (d <= RADIO_PX) lista.push([d, x]);
    });
    return lista.sort((a, b) => a[0] - b[0]).slice(0, MAX).map(([, x]) => x);
  }

  /** Opens `l` as if it had been clicked (its own popup, Enter the mufa…), without asking again. */
  function abrir(l, ev) {
    l._abanicoSaltar = true;
    try {
      const ll = l.getLatLng(), mapa = l._map;
      l.fire("click", { latlng: ll, layerPoint: mapa.latLngToLayerPoint(ll), containerPoint: mapa.latLngToContainerPoint(ll), originalEvent: ev });
    } finally { l._abanicoSaltar = false; }
  }

  function quitarAbanico() {
    if (abanico) { abanico._map && abanico._map.removeLayer(abanico); abanico = null; }
  }

  function panel(mapa) {
    if (!mapa.getPane("abanico")) mapa.createPane("abanico").style.zIndex = 650;        // over the markers (600), under the popups
  }

  function mostrar(mapa, lista, datos) {
    quitarAbanico();
    const centro = lista[0].getLatLng();
    window.__superpuestos = lista;
    const filas = lista.map((l, n) => {
      const i = info(l);
      return `<button type="button" class="lg-sup" data-superpuesto="${n}" title="${esc(i.detalle || i.nombre)}"><span class="lg-sup-icono">${muestra(l)}</span>
        <span class="lg-sup-texto"><b>${esc(i.nombre)}</b>${i.detalle ? `<br><span class="nota">${esc(i.detalle)}</span>` : ""}</span></button>`;
    }).join("");
    const popup = L.popup({ maxWidth: 340, autoPanPaddingTopLeft: [20, 60] }).setLatLng(centro)
      .setContent(`<div class="popup lg-popup sup-popup"><h3>${lista.length} elementos aquí</h3><div class="tipo">Elija cuál (en la lista o en el abanico)</div><div class="lg-sups">${filas}</div></div>`)
      .openOn(mapa);
    popupActual = popup;
    const elegir = (n) => { const l = lista[n]; if (l && l._map) abrir(l, datos.originalEvent); };
    const el = popup.getElement();
    if (el) el.addEventListener("click", (e) => { const b = e.target.closest("[data-superpuesto]"); if (b) elegir(Number(b.dataset.superpuesto)); });

    // the fan: below the point (the list stays above), each one joined to the point by a thin line
    panel(mapa);
    abanico = L.layerGroup().addTo(mapa);
    const c = mapa.latLngToContainerPoint(centro), n = lista.length, radio = Math.max(38, 13 * n + 18);
    lista.forEach((l, i) => {
      const grados = n === 1 ? 90 : 25 + (130 * i) / (n - 1);
      const rad = (grados * Math.PI) / 180;
      const ll = mapa.containerPointToLatLng(L.point(c.x + radio * Math.cos(rad), c.y + radio * Math.sin(rad)));
      const pata = L.polyline([centro, ll], { color: "#2b2b2b", weight: 1.6, opacity: 0.85, interactive: false, pane: "abanico" });
      pata._esAbanico = true;
      pata.addTo(abanico);
      const mk = L.marker(ll, { icon: L.divIcon({ className: "icono", html: `<div class="lg-abanico">${muestra(l)}</div>`, iconSize: [32, 32], iconAnchor: [16, 16] }),
                                pane: "abanico", zIndexOffset: 3000, keyboard: false });
      mk._esAbanico = true;
      mk.bindTooltip(esc(info(l).nombre), { direction: "right", offset: [10, 0], className: "hover" })
        .on("click", (e) => { L.DomEvent.stopPropagation(e); elegir(i); })
        .addTo(abanico);
    });
    // Whatever closes the list folds the fan, a little later: a click on a fan icon first closes the popup (Leaflet's «preclick») and only then
    // reaches the icon, which must still be there.
    popup.on("remove", () => setTimeout(() => { if (popupActual === popup) quitarAbanico(); }, 150));
    mapa.once("zoomstart", () => { quitarAbanico(); mapa.closePopup(popup); });
  }

  function parchear(proto) {
    const original = proto.fire;
    proto.fire = function (tipo, datos, propagar) {
      if (tipo === "click" && datos && datos.originalEvent && !this._abanicoSaltar && esPunto(this)
          && !(window.ModoDibujo && window.ModoDibujo.activo(this._map))) {
        const lista = vecinos(this);
        if (lista.length > 1) { mostrar(this._map, lista, datos); return this; }
      }
      return original.call(this, tipo, datos, propagar);
    };
  }

  if (window.L && L.Marker && !L.Marker.prototype._superpuestos) {
    L.Marker.prototype._superpuestos = true;
    parchear(L.Marker.prototype);
    parchear(L.CircleMarker.prototype);
  }

  window.Superpuestos = { vecinos, mostrar, quitarAbanico, RADIO_PX };
})();
