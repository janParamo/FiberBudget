/* Dibujar encima de lo que ya está en el mapa.
 *
 * Mientras se dibuja o se coloca algo (ruta a mano, postes a mano, cable, medida, marca, línea o polígono de Mis lugares, área de un proyecto) un clic
 * sobre un poste, una mufa, un cliente o una línea del KMZ abría la ficha del elemento y el punto no se ponía. Aquí se corrige en un solo lugar: con un
 * modo de dibujo activo, los elementos del mapa dejan de recibir clics (siguen mostrando su nombre al pasar el mouse) y el clic llega al mapa, que es
 * lo que escuchan todas las herramientas. Los puntos de ayuda de Geoman (cerrar el polígono, terminar la línea) siguen funcionando.
 *
 *   ModoDibujo.activo(mapa)    ¿hay un modo de dibujo activo?
 */
(function () {
  "use strict";

  const BLOQUEADOS = new Set(["click", "preclick", "dblclick", "contextmenu"]);

  function activo(mapa) {
    return !!((window.visor && window.visor.midiendo)
      || (window.EditarRuta && window.EditarRuta.activo)
      || (window.MisLugares && window.MisLugares.trabajando)          // a place being drawn or placed, a cable included
      || (mapa && mapa.pm && mapa.pm.globalDrawModeEnabled && mapa.pm.globalDrawModeEnabled()));
  }

  /** Targets that keep their clicks while drawing: the map itself and the helper points of Geoman. */
  const conserva = (mapa) => (t) => t === mapa || !!t._pmTempLayer;

  if (window.L && L.Map && !L.Map.prototype._modoDibujo) {
    L.Map.prototype._modoDibujo = true;
    const buscar = L.Map.prototype._findEventTargets;
    L.Map.prototype._findEventTargets = function (e, tipo) {
      const objetivos = buscar.call(this, e, tipo);
      if (!BLOQUEADOS.has(tipo) || !activo(this)) return objetivos;
      const quedan = objetivos.filter(conserva(this));
      return quedan.length ? quedan : [this];
    };
    const disparar = L.Map.prototype._fireDOMEvent;
    L.Map.prototype._fireDOMEvent = function (e, tipo, canvas) {
      if (canvas && BLOQUEADOS.has(tipo) && activo(this)) canvas = canvas.filter(conserva(this));         // layers drawn on canvas (the KMZ)
      return disparar.call(this, e, tipo, canvas);
    };
  }

  window.ModoDibujo = { activo };
})();
