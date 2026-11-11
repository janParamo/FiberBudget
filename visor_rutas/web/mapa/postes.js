/* Postes del mapa: mostrarlos u ocultarlos todos con un botón (barra de herramientas del mapa).
 *
 * Cuando una ruta usa muchos postes se ven más los postes que la ruta. El botón oculta, de una vez, los postes de la ruta (existentes y nuevos), los de la red del KMZ y los de
 * «Mis lugares»; al volver a mostrarlos quedan como estaban (cada casilla del panel Lugares sigue mandando sobre lo suyo). El estado se recuerda en las preferencias.
 *
 *   Postes.iniciar(api)    lee la preferencia (antes de dibujar nada)      Postes.alternar()    Postes.poner(ocultos)
 *   Postes.ocultos         true cuando están ocultos                       Postes.alCambiar(fn(ocultos))    cada parte del mapa dice cómo ocultar lo suyo
 */
(function () {
  "use strict";

  const oyentes = [];
  let ocultos = false;
  let api = null;

  function avisar() {
    oyentes.forEach((f) => { try { f(ocultos); } catch (e) { console.error("Postes", e); } });
  }

  async function iniciar(a) {
    api = a;
    try {
      const r = await a.preferencias();
      ocultos = !!(r && r.preferencias && r.preferencias.postes_ocultos);
    } catch (e) { /* without preferences they start visible */ }
    avisar();
  }

  function poner(valor) {
    valor = !!valor;
    if (valor === ocultos) return;
    ocultos = valor;
    avisar();
    if (api && api.guardar_preferencias) api.guardar_preferencias({ postes_ocultos: ocultos }).catch(() => {});
  }

  window.Postes = { iniciar, poner, alternar: () => poner(!ocultos), alCambiar: (f) => { oyentes.push(f); }, get ocultos() { return ocultos; } };
})();
