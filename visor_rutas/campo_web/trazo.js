/* App de campo: la lógica de un cable que se traza (sin pantalla): sus vértices, su largo y el modo de grabar el recorrido caminando.
 *
 * Un cable se arma de tres maneras que se pueden mezclar: poniendo la mira del centro en cada punto (los que caen sobre un poste o punto conocido se pegan a él:
 * «postes»), con «Mi ubicación», o grabando el recorrido mientras se camina («recorrido»: se agrega un vértice cada vez que el GPS, con precisión aceptable, se mueve
 * lo suficiente y ha pasado el tiempo mínimo). */
(function () {
  "use strict";
  const RADIO_TIERRA_M = 6371000;
  const MIN_ENTRE_VERTICES_M = 0.5;          // the same place twice in a row is not a new vertex
  const PRECISION_GRABANDO_M = 25;           // a fix worse than this is not recorded (default; the setting overrides it)
  const PASO_GRABANDO_M = 5;                 // recording: a vertex every this many metres (default)
  const TIEMPO_GRABANDO_S = 0;               // recording: at least this many seconds between vertices (default)

  function distanciaM(a, b) {
    const rad = Math.PI / 180, f1 = a.lat * rad, f2 = b.lat * rad;
    const h = Math.sin((f2 - f1) / 2) ** 2 + Math.cos(f1) * Math.cos(f2) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
    return 2 * RADIO_TIERRA_M * Math.asin(Math.sqrt(h));
  }

  function crear() {
    const vertices = [];                     // {lat, lon, poste: {nombre} | null, grabado: bool, t: ms}
    const ultimo = () => vertices[vertices.length - 1];
    const nuevo = (lat, lon, extra) => ({ lat, lon, poste: (extra && extra.poste) || null, grabado: !!(extra && extra.grabado), t: (extra && extra.t) || Date.now() });
    return {
      /* al final; no repite el mismo lugar dos veces seguidas */
      agregar(lat, lon, extra) {
        const v = nuevo(lat, lon, extra);
        if (ultimo() && distanciaM(ultimo(), v) < MIN_ENTRE_VERTICES_M) return null;
        vertices.push(v);
        return v;
      },
      /* después del vértice `indice` (sin comprobar repetidos: nace en el mismo lugar y luego se mueve); devuelve su índice */
      insertarTras(indice, lat, lon, extra) {
        const i = Math.min(Math.max(indice + 1, 0), vertices.length);
        vertices.splice(i, 0, nuevo(lat, lon, extra));
        return i;
      },
      mover(indice, lat, lon, extra) {
        const v = vertices[indice];
        if (!v) return null;
        v.lat = lat; v.lon = lon; v.poste = (extra && extra.poste) || null;
        return v;
      },
      quitarEn(indice) { return indice >= 0 && indice < vertices.length ? vertices.splice(indice, 1)[0] : null; },
      /* Un fix del GPS mientras se graba: se agrega si es lo bastante preciso, está lo bastante lejos del último vértice y pasó el tiempo mínimo. */
      fijar(fix, opciones) {
        const o = opciones || {};
        if (!fix || fix.precision_m > (o.precision != null ? o.precision : PRECISION_GRABANDO_M)) return null;
        const u = ultimo();
        if (u && distanciaM(u, fix) < (o.paso != null ? o.paso : PASO_GRABANDO_M)) return null;
        if (u && ((fix.hora || Date.now()) - u.t) / 1000 < (o.tiempoMin != null ? o.tiempoMin : TIEMPO_GRABANDO_S)) return null;
        return this.agregar(fix.lat, fix.lon, { grabado: true, t: fix.hora });
      },
      deshacer() { return vertices.pop() || null; },
      vaciar() { vertices.length = 0; },
      /* quita los vértices que quedaron repetidos uno junto al otro */
      limpiar() { for (let i = vertices.length - 1; i > 0; i--) if (distanciaM(vertices[i - 1], vertices[i]) < MIN_ENTRE_VERTICES_M) vertices.splice(i, 1); },
      n: () => vertices.length,
      vertices: () => vertices.slice(),
      longitud() { let m = 0; for (let i = 1; i < vertices.length; i++) m += distanciaM(vertices[i - 1], vertices[i]); return m; },
      modo: () => (vertices.some((v) => v.grabado) ? "recorrido" : vertices.some((v) => v.poste) ? "postes" : "puntos"),
      puntos: () => vertices.map((v) => ({ lat: +v.lat.toFixed(7), lon: +v.lon.toFixed(7) })),
      postes: () => vertices.filter((v) => v.poste).map((v) => ({ nombre: v.poste.nombre || "", lat: +v.lat.toFixed(7), lon: +v.lon.toFixed(7) })),
      listo: () => vertices.length >= 2 && vertices.some((v) => distanciaM(vertices[0], v) >= MIN_ENTRE_VERTICES_M),
    };
  }

  const texto = (m) => (window.Campo && window.Campo.fmt ? window.Campo.fmt.dist(m) : (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`));

  window.CampoTrazo = { crear, distanciaM, texto, PASO_GRABANDO_M, PRECISION_GRABANDO_M };
})();
