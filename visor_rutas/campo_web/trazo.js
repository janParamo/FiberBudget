/* App de campo: la lógica de un cable que se traza (sin pantalla): sus vértices, su largo y el modo de grabar el recorrido caminando.
 *
 * Un cable se arma de tres maneras que se pueden mezclar: tocando puntos en el mapa (los que caen sobre un poste o punto conocido se pegan a él: «postes»),
 * con «Mi ubicación» o con la mira, o grabando el recorrido mientras se camina («recorrido»: se agrega un vértice cada vez que el GPS, con precisión
 * aceptable, se mueve lo suficiente). */
(function () {
  "use strict";
  const RADIO_TIERRA_M = 6371000;
  const MIN_ENTRE_VERTICES_M = 0.5;          // the same place twice in a row is not a new vertex
  const PRECISION_GRABANDO_M = 25;           // a fix worse than this is not recorded
  const PASO_GRABANDO_M = 5;                 // recording: a vertex every this many metres

  function distanciaM(a, b) {
    const rad = Math.PI / 180, f1 = a.lat * rad, f2 = b.lat * rad;
    const h = Math.sin((f2 - f1) / 2) ** 2 + Math.cos(f1) * Math.cos(f2) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
    return 2 * RADIO_TIERRA_M * Math.asin(Math.sqrt(h));
  }

  function crear() {
    const vertices = [];                     // {lat, lon, poste: {nombre} | null, grabado: bool}
    const ultimo = () => vertices[vertices.length - 1];
    return {
      agregar(lat, lon, extra) {
        const v = { lat, lon, poste: (extra && extra.poste) || null, grabado: !!(extra && extra.grabado) };
        if (ultimo() && distanciaM(ultimo(), v) < MIN_ENTRE_VERTICES_M) return null;
        vertices.push(v);
        return v;
      },
      /* A GPS fix while recording: added when it is precise enough and far enough from the last vertex. */
      fijar(fix) {
        if (!fix || fix.precision_m > PRECISION_GRABANDO_M) return null;
        if (ultimo() && distanciaM(ultimo(), fix) < PASO_GRABANDO_M) return null;
        return this.agregar(fix.lat, fix.lon, { grabado: true });
      },
      deshacer() { return vertices.pop() || null; },
      vaciar() { vertices.length = 0; },
      n: () => vertices.length,
      vertices: () => vertices.slice(),
      longitud() { let m = 0; for (let i = 1; i < vertices.length; i++) m += distanciaM(vertices[i - 1], vertices[i]); return m; },
      modo: () => (vertices.some((v) => v.grabado) ? "recorrido" : vertices.some((v) => v.poste) ? "postes" : "puntos"),
      puntos: () => vertices.map((v) => ({ lat: +v.lat.toFixed(7), lon: +v.lon.toFixed(7) })),
      postes: () => vertices.filter((v) => v.poste).map((v) => ({ nombre: v.poste.nombre || "", lat: +v.lat.toFixed(7), lon: +v.lon.toFixed(7) })),
      listo: () => vertices.length >= 2 && vertices.some((v) => distanciaM(vertices[0], v) >= MIN_ENTRE_VERTICES_M),
    };
  }

  const texto = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);

  window.CampoTrazo = { crear, distanciaM, texto, PASO_GRABANDO_M, PRECISION_GRABANDO_M };
})();
