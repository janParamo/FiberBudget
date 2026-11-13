/* Paleta de comandos (Ctrl+K), como la de las apps actuales: escribir unas letras y Enter para ir a una vista, tomar una herramienta del mapa o
 * hacer una acción, sin buscar el botón. No agrega nada nuevo: cada comando hace clic en el botón que ya existe (así respeta lo que el rol no puede:
 * lo deshabilitado u oculto no sale).
 *
 *   Paleta.iniciar()      Paleta.abrir()      Paleta.cerrar()
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const plano = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  let comandos = [], visibles = [], marcado = 0;

  const enMapa = () => !document.querySelector(".vista:not([hidden])");
  const irAlMapa = () => { if (!enMapa()) { const m = document.querySelector('#menu-lateral [data-vista="mapa"]'); if (m) m.click(); } };

  /** The commands of this moment: the views of the menu, the tools of the map and the actions of the bottom bar that are there and enabled. */
  function reunir() {
    const lista = [];
    document.querySelectorAll("#menu-lateral .menu-item").forEach((b) => {
      if (b.getAttribute("aria-disabled") === "true") return;
      const svg = b.querySelector("svg");
      lista.push({ grupo: "Ir a", texto: b.querySelector(".menu-texto").textContent, icono: svg ? svg.outerHTML : "", hacer: () => b.click() });
    });
    if (!document.body.classList.contains("es-guest")) {
      document.querySelectorAll("#barra-herramientas [data-bh]").forEach((b) => {
        if (b.getAttribute("aria-disabled") === "true") return;
        lista.push({ grupo: "Herramientas del mapa", texto: b.getAttribute("aria-label") || b.title, detalle: (b.title.split(": ")[1] || ""), icono: b.innerHTML,
                     hacer: () => { irAlMapa(); b.click(); } });
      });
    }
    [["ruta-mano", "Ruta a mano"], ["captura", "Captura del mapa"], ["limpiar", "Limpiar la ruta"], ["borrar-medidas", "Borrar medidas"]].forEach(([id, texto]) => {
      const b = $(id);
      if (!b || b.disabled) return;
      const svg = b.querySelector("svg");
      lista.push({ grupo: "Acciones", texto, detalle: b.title || "", icono: svg ? svg.outerHTML : "", hacer: () => { irAlMapa(); b.click(); } });
    });
    lista.push({ grupo: "Acciones", texto: "Buscar mufa, lugar o coordenada", detalle: "El buscador de arriba del mapa", icono: "",
                 hacer: () => { irAlMapa(); const c = $("buscar-mufa"); if (c) setTimeout(() => c.focus(), 50); } });
    return lista;
  }

  function pintar() {
    const q = plano($("paleta-campo").value).split(/\s+/).filter(Boolean);
    visibles = comandos.filter((c) => { const t = plano(`${c.grupo} ${c.texto} ${c.detalle || ""}`); return q.every((p) => t.includes(p)); });
    marcado = Math.min(marcado, Math.max(0, visibles.length - 1));
    let grupo = null;
    $("paleta-lista").innerHTML = visibles.length ? visibles.map((c, i) => {
      const titulo = c.grupo !== grupo ? `<li class="paleta-grupo" role="presentation">${esc(grupo = c.grupo)}</li>` : "";
      return `${titulo}<li class="paleta-fila${i === marcado ? " marcada" : ""}" role="option" data-i="${i}" aria-selected="${i === marcado}">
        <span class="paleta-icono">${c.icono || ""}</span><span class="paleta-texto">${esc(c.texto)}</span>
        <span class="paleta-detalle">${esc(c.detalle || "")}</span></li>`;
    }).join("") : `<li class="paleta-vacia">Nada con «${esc($("paleta-campo").value)}»</li>`;
    const fila = $("paleta-lista").querySelector(".marcada");
    if (fila) fila.scrollIntoView({ block: "nearest" });
  }

  function abrir() {
    if (!$("paleta").hidden) return;
    comandos = reunir();
    marcado = 0;
    $("paleta-campo").value = "";
    $("paleta").hidden = false;
    pintar();
    $("paleta-campo").focus();
  }

  function cerrar() { $("paleta").hidden = true; }

  function ejecutar(i) {
    const c = visibles[i];
    if (!c) return;
    cerrar();
    c.hacer();
  }

  function iniciar() {
    document.body.insertAdjacentHTML("beforeend", `<div id="paleta" class="paleta" hidden role="dialog" aria-modal="true" aria-label="Comandos">
      <div class="paleta-caja">
        <div class="paleta-cabecera"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="paleta-campo" type="text" autocomplete="off" spellcheck="false" placeholder="Escriba una vista, una herramienta o una acción…" aria-controls="paleta-lista">
          <kbd>Esc</kbd></div>
        <ul id="paleta-lista" class="paleta-lista" role="listbox"></ul>
        <div class="paleta-pie"><span><kbd>↑</kbd><kbd>↓</kbd> elegir</span><span><kbd>Enter</kbd> abrir</span><span><kbd>Ctrl</kbd><kbd>K</kbd> abrir o cerrar</span></div>
      </div></div>`);
    $("paleta").addEventListener("mousedown", (e) => { if (e.target === $("paleta")) cerrar(); });
    $("paleta-campo").addEventListener("input", () => { marcado = 0; pintar(); });
    $("paleta-lista").addEventListener("click", (e) => { const f = e.target.closest("[data-i]"); if (f) ejecutar(Number(f.dataset.i)); });
    $("paleta-lista").addEventListener("mousemove", (e) => {
      const f = e.target.closest("[data-i]");
      if (f && Number(f.dataset.i) !== marcado) { marcado = Number(f.dataset.i); pintar(); }
    });
    document.addEventListener("keydown", (e) => {
      const abierta = !$("paleta").hidden;
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault(); e.stopPropagation();
        if (abierta) cerrar(); else abrir();
        return;
      }
      if (!abierta) return;
      e.stopPropagation();                                    // nothing behind reacts while it is open (Enter would end a measurement, Esc would close a window…)
      if (e.key === "Escape") { e.preventDefault(); cerrar(); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (visibles.length) { marcado = (marcado + (e.key === "ArrowDown" ? 1 : -1) + visibles.length) % visibles.length; pintar(); }
      } else if (e.key === "Enter") { e.preventDefault(); ejecutar(marcado); }
    }, true);
    const boton = $("abrir-paleta");
    if (boton) boton.addEventListener("click", abrir);
  }

  window.Paleta = { iniciar, abrir, cerrar, get abierta() { return !$("paleta").hidden; } };
})();
