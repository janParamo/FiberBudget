/* Barra de herramientas del mapa (visor v2, fase 3), como la de Google Earth: íconos arriba del mapa, sin ventana aparte.
 *
 *   Marca de posición · Polígono · Ruta · Medir | Mufa · Poste · Cliente · Cable (dibujar red, fase 4) | Importar (fase 5) · Coordenadas masivas (fase 6)
 *
 * Marca, polígono y ruta crean un lugar en una carpeta de "Mis lugares" (lugares/mis_lugares.js). Medir es el mismo botón de la
 * barra inferior. Lo que todavía no está queda deshabilitado, con un tooltip que dice en qué fase llega.
 *   BarraHerramientas.iniciar({accion(id)})    BarraHerramientas.marcarActivo(id | null)
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const svg = (d) => `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const BOTONES = [
    { id: "marca", titulo: "Marca de posición: clic en el mapa donde va", icono: svg('<path d="M12 21s-6-5.6-6-10a6 6 0 0 1 12 0c0 4.4-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>') },
    { id: "poligono", titulo: "Polígono: clic para cada punto, doble clic para terminar", icono: svg('<path d="M5 8 12 4l7 5-2 10H7z"/>') },
    { id: "ruta", titulo: "Ruta: clic para cada punto, doble clic para terminar", icono: svg('<path d="M4 18 9 9l5 6 6-10"/><circle cx="4" cy="18" r="1.4"/><circle cx="20" cy="5" r="1.4"/>') },
    { id: "medir", titulo: "Medir distancia y área (es el botón Medir de la barra de abajo)", icono: svg('<path d="m3 16 13-13 5 5L8 21z"/><path d="m7 12 2 2M10 9l2 2M13 6l2 2"/>') },
    null,
    { id: "mufa", titulo: "Mufa: clic en el mapa donde va (se guarda en una carpeta de Mis lugares)", icono: svg('<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/>') },
    { id: "poste", titulo: "Poste: clic en el mapa donde va (se guarda en una carpeta de Mis lugares)", icono: svg('<path d="M12 3v18M7 7h10M8 11h8"/>') },
    { id: "cliente", titulo: "Cliente: clic en el mapa donde va (se guarda en una carpeta de Mis lugares)", icono: svg('<path d="M4 11 12 4l8 7v9H4z"/><path d="M10 20v-5h4v5"/>') },
    { id: "nodo", titulo: "Nodo / OLT: clic en el mapa donde va (se guarda en una carpeta de Mis lugares)", icono: svg('<path d="M12 4 21 19H3z"/>') },
    { id: "odf", titulo: "ODF: clic en el mapa donde va (se guarda en una carpeta de Mis lugares)", icono: svg('<rect x="4" y="6" width="16" height="12" rx="1.5"/><path d="M8 10h8M8 14h8"/>') },
    { id: "cable", titulo: "Cable: clic en el elemento de inicio, en el recorrido y doble clic en el elemento final", icono: svg('<path d="M3 15c3-8 6 8 9 0s6 8 9 0"/>') },
    null,
    { id: "importar", titulo: "Importar KMZ a la red: nueva ruta o actualización (para una carpeta de Mis lugares: clic derecho en la carpeta)", icono: svg('<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>') },
    { id: "masivas", titulo: "Coordenadas masivas: un presupuesto por cada coordenada de un Excel, CSV, Word o texto", icono: svg('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M10 10v9"/>') },
  ];
  let ctx = null;

  function iniciar(contexto) {
    ctx = contexto;
    document.body.insertAdjacentHTML("beforeend", `<nav id="barra-herramientas" class="barra-herramientas" aria-label="Herramientas del mapa">${
      BOTONES.map((b) => (b === null ? '<span class="bh-sep" role="separator"></span>'
        : `<button type="button" class="bh-boton" data-bh="${b.id}" title="${(b.pronto || b.titulo).replace(/"/g, "&quot;")}" aria-label="${b.titulo.split(":")[0]}"${b.pronto ? ' aria-disabled="true"' : ""}>${b.icono}</button>`)).join("")}</nav>`);
    $("barra-herramientas").addEventListener("click", (e) => {
      const b = e.target.closest("[data-bh]");
      if (!b) return;
      if (b.getAttribute("aria-disabled") === "true") { if (ctx.mensaje) ctx.mensaje(b.title); return; }
      ctx.accion(b.dataset.bh);
    });
    L.DomEvent.disableClickPropagation($("barra-herramientas"));
    // Medir is the bottom bar's button: this one shows when it is on
    const medir = $("medir");
    if (medir) new MutationObserver(() => marcarActivo(medir.classList.contains("activo") ? "medir" : (activo === "medir" ? null : activo))).observe(medir, { attributes: true, attributeFilter: ["class"] });
  }

  let activo = null;
  function marcarActivo(id) {
    activo = id;
    document.querySelectorAll("#barra-herramientas [data-bh]").forEach((b) => b.classList.toggle("activo", b.dataset.bh === id));
  }

  window.BarraHerramientas = { iniciar, marcarActivo, get activo() { return activo; } };
})();
