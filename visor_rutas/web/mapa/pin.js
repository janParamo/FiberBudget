/* Pincho de una coordenada buscada (visor v2, fase 2), como la marca de Google Earth: un pincho amarillo con una
 * etiqueta con la coordenada en decimal. Clic en el pincho: copiar en decimal o en grados/minutos/segundos,
 * "Guardar en Mis lugares", "Generar ruta" (calcula de una vez la ruta y el presupuesto de esa coordenada) y "Quitar".
 * Hay uno solo: buscar otra coordenada lo cambia de sitio y abre su ventana, con "Generar ruta" a un clic.
 *
 *   Pin.iniciar({mapa, capa, copiar, mensaje, usarParaRuta, alCambiar})
 *   Pin.poner(lat, lon)    Pin.quitar()    Pin.hay()
 *   Pin.guardarEnMisLugares = (lat, lon) => …   (lo asigna Mis lugares, fase 3; mientras tanto el botón está deshabilitado)
 */
(function () {
  "use strict";

  const COLOR = "#f7d117";
  let ctx = null, marcador = null;

  function icono() {
    const html = `<svg width="34" height="48" viewBox="0 0 30 42">
      <path d="M15 41C15 41 2 24.5 2 15a13 13 0 0 1 26 0c0 9.5-13 26-13 26z" fill="${COLOR}" stroke="#1a1a1a" stroke-width="2"/>
      <circle cx="15" cy="15" r="5.5" fill="#fff" stroke="#1a1a1a" stroke-width="1.5"/></svg>`;
    return L.divIcon({ className: "icono", html, iconSize: [34, 48], iconAnchor: [17, 47], popupAnchor: [0, -44], tooltipAnchor: [14, -26] });
  }

  function contenido(lat, lon) {
    const guardable = typeof Pin.guardarEnMisLugares === "function";
    return `<div class="popup pin-popup"><h3>Coordenada buscada</h3>
      <dl><dt>Decimal</dt><dd>${Coordenadas.formatoDecimal(lat, lon)}</dd>
          <dt>Grados</dt><dd>${Coordenadas.formatoGMS(lat, lon)}</dd></dl>
      <div class="acciones pin-acciones">
        <button type="button" class="btn btn-chico" data-pin="copiar-decimal">Copiar decimal</button>
        <button type="button" class="btn btn-chico" data-pin="copiar-gms">Copiar grados</button>
        <button type="button" class="btn btn-chico" data-pin="guardar" ${guardable ? "" : 'disabled title="Disponible con Mis lugares"'}>Guardar en Mis lugares</button>
        <button type="button" class="btn btn-chico btn-primario" data-pin="ruta" title="Calcula la ruta y el presupuesto de esta coordenada">Generar ruta</button>
        <button type="button" class="btn btn-chico" data-pin="quitar">Quitar</button>
      </div></div>`;
  }

  function accion(nombre, lat, lon) {
    if (nombre === "copiar-decimal") ctx.copiar(Coordenadas.formatoDecimal(lat, lon), `Coordenada copiada: ${Coordenadas.formatoDecimal(lat, lon)}`);
    else if (nombre === "copiar-gms") ctx.copiar(Coordenadas.formatoGMS(lat, lon), `Coordenada copiada: ${Coordenadas.formatoGMS(lat, lon)}`);
    else if (nombre === "guardar" && typeof Pin.guardarEnMisLugares === "function") Pin.guardarEnMisLugares(lat, lon);
    else if (nombre === "ruta") { ctx.mapa.closePopup(); ctx.usarParaRuta(lat, lon); }
    else if (nombre === "quitar") quitar();
  }

  function poner(lat, lon, { volar = true } = {}) {
    quitar(false);
    const ll = L.latLng(lat, lon);
    marcador = L.marker(ll, { icon: icono(), zIndexOffset: 1300, riseOnHover: true })
      .bindTooltip(Coordenadas.formatoDecimal(lat, lon), { permanent: true, direction: "right", className: "etiqueta coordenada", offset: [0, 0] })
      .bindPopup(() => contenido(lat, lon), { maxWidth: 360 })
      .addTo(ctx.capa);
    marcador.on("popupopen", (e) => {
      e.popup.getElement().querySelectorAll("[data-pin]").forEach((b) => b.addEventListener("click", () => accion(b.dataset.pin, lat, lon)));
    });
    if (volar) {
      const puesto = marcador;                 // once there, its window opens: «Generar ruta» is one click away
      ctx.mapa.once("moveend", () => { if (marcador === puesto) puesto.openPopup(); });
      ctx.mapa.flyTo(ll, Math.max(ctx.mapa.getZoom(), 17), { duration: 0.8 });
    }
    ctx.mensaje(`${Coordenadas.formatoDecimal(lat, lon)} · Generar ruta en la ventana del pincho`, "ok");
    ctx.alCambiar();
    return marcador;
  }

  function quitar(avisar = true) {
    if (!marcador) return;
    ctx.capa.clearLayers();
    marcador = null;
    ctx.mapa.closePopup();
    if (avisar) ctx.mensaje("Pincho quitado");
    ctx.alCambiar();
  }

  const Pin = { iniciar(contexto) { ctx = contexto; }, poner, quitar, hay: () => !!marcador, guardarEnMisLugares: null,
                get marcador() { return marcador; } };
  window.Pin = Pin;
})();
