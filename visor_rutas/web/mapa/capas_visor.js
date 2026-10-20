/* Capas del visor dentro del panel "Lugares" (visor v2, fase 1).
 *
 * Antes eran un recuadro flotante de Leaflet (L.control.layers) aparte del árbol de Lugares. Ahora son dos
 * secciones del mismo árbol (lugares.js → registrarSeccion):
 *   - "Mapa base": Satélite / Calles (casillas de opción).
 *   - "Capas del visor": postes, mufas y camino de la fibra de la ruta, mufa buscada, mis medidas y la
 *     red Visio completa, con casilla de tres estados en el encabezado.
 * Las capas que se llenan con un cálculo (ruta, búsqueda, medidas) quedan deshabilitadas, con un tooltip
 * que lo explica, hasta que haya algo que mostrar; la red Visio carga por pantalla y solo desde su zoom mínimo.
 *
 * visor.js llama a CapasVisor.iniciar({...}) cuando el mapa existe y a CapasVisor.refrescar() cuando cambia
 * algo que habilita o deshabilita una capa (ruta, búsqueda, medidas).
 */
(function () {
  "use strict";

  let ctx = null;

  /** Layers of the viewer, in the order shown. `necesita`: what fills it ("ruta" | "busqueda" | "medidas" | null). */
  const CAPAS = [
    { id: "postesExistentes", texto: "Postes existentes", necesita: "ruta" },
    { id: "postesNuevos", texto: "Postes nuevos", necesita: "ruta" },
    { id: "mufasRuta", texto: "Mufas en ruta", necesita: "ruta" },
    { id: "mufasIntervenidas", texto: "Mufas intervenidas", necesita: "ruta" },
    { id: "nodosVisio", texto: "Nodos Visio cercanos", necesita: "ruta" },
    { id: "caminoFibra", texto: "Camino de la fibra", necesita: "ruta" },
    { id: "busqueda", texto: "Mufa buscada", necesita: "busqueda" },
    { id: "coordenada", texto: "Coordenada buscada", necesita: "coordenada" },
    { id: "medidas", texto: "Mis medidas", necesita: "medidas" },
  ];
  const MOTIVO = {
    ruta: "se llena al generar una ruta",
    busqueda: "se llena al buscar una mufa",
    coordenada: "se llena al buscar una coordenada",
    medidas: "se llena al medir en el mapa",
  };

  const redes = () => Object.keys(ctx.redes);
  const enMapa = (nombre) => ctx.mapa.hasLayer(ctx.capas[nombre]);

  function hayDatos(necesita) {
    if (necesita === "ruta") return ctx.hayRuta();
    if (necesita === "busqueda") return ctx.capas.busqueda.getLayers().length > 0;
    if (necesita === "coordenada") return ctx.capas.coordenada.getLayers().length > 0;
    if (necesita === "medidas") return ctx.capas.medidas.getLayers().length > 0;
    return true;
  }

  function poner(nombre, encendida) {
    if (encendida === enMapa(nombre)) return;
    if (encendida) ctx.mapa.addLayer(ctx.capas[nombre]); else ctx.mapa.removeLayer(ctx.capas[nombre]);
    if (ctx.redes[nombre]) { if (encendida) ctx.cargarRed(nombre); else ctx.quitarRed(nombre); }
  }

  function itemsVisor() {
    const propias = CAPAS.map((c) => ({
      id: c.id, texto: c.texto, tipo: "check", marcado: enMapa(c.id),
      deshabilitado: !hayDatos(c.necesita), motivo: `${c.texto}: ${MOTIVO[c.necesita]}`,
    }));
    const red = redes().map((n) => ({
      id: n, texto: ctx.redes[n].etiqueta, tipo: "check", marcado: enMapa(n),
      pista: `zoom ${ctx.redes[n].zoomMin}+`,
    }));
    // «Íconos del visor…»: a row that opens the window to change the icons of the poles, mufas, nodes… (for everyone; mapa/iconos_visor.js)
    const acciones = window.IconosVisor && window.Redes && window.Redes.disponible ? [{ id: "_iconos", texto: "Íconos del visor…", tipo: "accion", pista: "cambiar el ícono de postes, mufas, nodos…" }] : [];
    return propias.concat(red, acciones);
  }

  const base = {
    id: "base", titulo: "Mapa base", tri: false,
    items: () => [
      { id: "satelite", texto: "Satélite", tipo: "radio", marcado: ctx.mapa.hasLayer(ctx.base.satelite) },
      { id: "calles", texto: "Calles", tipo: "radio", marcado: ctx.mapa.hasLayer(ctx.base.calles) },
    ],
    alternar(id) {
      const otra = id === "satelite" ? "calles" : "satelite";
      if (!ctx.mapa.hasLayer(ctx.base[id])) ctx.mapa.addLayer(ctx.base[id]);
      if (ctx.mapa.hasLayer(ctx.base[otra])) ctx.mapa.removeLayer(ctx.base[otra]);
    },
    alternarTodas() { /* radio group: no header box */ },
  };

  const visor = {
    id: "visor", titulo: "Capas del visor", tri: true,
    items: itemsVisor,
    alternar(id, valor) { if (id === "_iconos") { if (window.IconosVisor) window.IconosVisor.abrir(); return; } poner(id, valor); },
    alternarTodas(valor) { itemsVisor().filter((it) => !it.deshabilitado && it.tipo === "check").forEach((it) => poner(it.id, valor)); },
  };

  function iniciar(contexto) {
    ctx = contexto;
    window.Lugares.registrarSeccion(base);
    window.Lugares.registrarSeccion(visor);
  }

  function refrescar() {
    if (ctx && window.Lugares) window.Lugares.refrescar();
  }

  window.CapasVisor = { iniciar, refrescar, CAPAS, MOTIVO };
})();
