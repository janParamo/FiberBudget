/* Mapas base sin cuadros vacíos al mover (Leaflet 1.9): por defecto Leaflet pide solo las teselas que se ven, así que al arrastrar el mapa el borde nuevo
 * aparece vacío (cuadros oscuros) hasta que llegan. Aquí todas las capas de teselas:
 *   - piden también `precarga` teselas más allá de cada borde de la pantalla (el borde ya está cargado cuando llega el arrastre),
 *   - guardan más teselas alrededor (`keepBuffer`: al volver al mismo lugar no hay que pedirlas otra vez),
 *   - se actualizan mientras se arrastra (`updateWhenIdle: false`) y con menos espera (`updateInterval`).
 * Se carga justo después de leaflet.js: cambia el prototipo de L.TileLayer, así que vale también para las capas que lo extienden. Cada capa puede poner su propia
 * `precarga` (0: como Leaflet). */
(function () {
  "use strict";
  if (!window.L || !L.TileLayer || !L.Bounds) return;
  const original = L.TileLayer.prototype._getTiledPixelBounds;
  if (typeof original !== "function") return;
  L.TileLayer.mergeOptions({ precarga: 1, keepBuffer: 5, updateWhenIdle: false, updateInterval: 100 });
  L.TileLayer.include({
    _getTiledPixelBounds(centro) {
      const b = original.call(this, centro), n = this.options.precarga;
      if (!n) return b;
      const margen = this.getTileSize().multiplyBy(n);
      return new L.Bounds(b.min.subtract(margen), b.max.add(margen));
    },
  });
})();
