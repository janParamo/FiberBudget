/* Vista "Red de mufas" del editor de mufa (migración Visio, fase 5: sección 8 de docs/migracion_visio/PLAN.md).
 *
 * La mufa abierta al centro y sus vecinas a 1 o 2 saltos por los cables (de cualquier proyecto), en
 * anillos; cada línea es un cable con su color y sus hilos. Doble clic (o Enter sobre la mufa
 * enfocada con Tab) entra a esa mufa en el editor. Datos: Redes.llamar("red_de_mufas").
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const mensaje = (t, tipo) => (window.visor && window.visor.mensaje ? window.visor.mensaje(t, tipo) : null);
  const COLOR_TIPO = { mufa: "#ff8c00", nodo: "#f5b400", odf: "#4a5568", cliente: "#0a9d57", poste: "#9aa3ad" };
  let visible = false, saltos = 2, datos = null;

  function corto(t, n) { t = String(t || ""); return t.length > n ? `${t.slice(0, n - 1)}…` : t; }

  /** Rings: level 1 evenly around the centre; level 2 near the neighbour they hang from. */
  function ubicar(r, ancho, alto) {
    const cx = ancho / 2, cy = alto / 2, r1 = Math.min(ancho, alto) * 0.24, r2 = Math.min(ancho, alto) * 0.44;
    const pos = new Map([[r.centro, { x: cx, y: cy }]]);
    const n1 = r.nodos.filter((n) => n.nivel === 1);
    n1.forEach((n, i) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, n1.length); pos.set(n.id, { x: cx + r1 * Math.cos(a), y: cy + r1 * Math.sin(a), a }); });
    const hijos = new Map();
    r.nodos.filter((n) => n.nivel === 2).forEach((n) => {
      const c = r.cables.find((k) => (k.a === n.id && pos.has(k.b) && pos.get(k.b).a !== undefined) || (k.b === n.id && pos.has(k.a) && pos.get(k.a).a !== undefined));
      const padre = c ? (c.a === n.id ? c.b : c.a) : n1.length ? n1[0].id : r.centro;
      if (!hijos.has(padre)) hijos.set(padre, []);
      hijos.get(padre).push(n);
    });
    const paso = (2 * Math.PI) / Math.max(1, n1.length);
    hijos.forEach((lista, padre) => {
      const base = (pos.get(padre) || {}).a ?? 0;
      lista.forEach((n, i) => {
        const a = base + (lista.length > 1 ? (i / (lista.length - 1) - 0.5) * paso * 0.8 : 0);
        pos.set(n.id, { x: cx + r2 * Math.cos(a), y: cy + r2 * Math.sin(a), a });
      });
    });
    return pos;
  }

  function dibujar() {
    const caja = $("mu-red-vista"), r = datos;
    const ancho = Math.max(900, caja.clientWidth - 20), alto = Math.max(640, caja.clientHeight - 50);
    const pos = ubicar(r, ancho, alto);
    const lineas = r.cables.map((k) => {
      const a = pos.get(k.a), b = pos.get(k.b);
      if (!a || !b) return "";
      return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${esc(k.color || "#9e9e9e")}" stroke-width="${k.hilos >= 48 ? 4 : 2.5}"`
        + `${k.hilos == null ? ' stroke-dasharray="6 4"' : ""}><title>${esc(k.nombre)} · ${k.hilos == null ? "hilos desconocidos" : `${k.hilos} hilos`}</title></line>`
        + `<text x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2 - 4}" font-size="10" fill="#5b6270" text-anchor="middle">${k.hilos ?? "?"}</text>`;
    }).join("");
    const nodos = r.nodos.map((n) => {
      const p = pos.get(n.id);
      if (!p) return "";
      const centro = n.id === r.centro, radio = centro ? 22 : n.nivel === 1 ? 15 : 11;
      const borde = n.estado_migracion === "validada" ? "#0a9d57" : "#1a1a1a";
      return `<g class="rm-nodo" tabindex="0" data-id="${n.id}" data-nombre="${esc(n.nombre)}" data-tipo="${esc(n.tipo)}">`
        + `<title>${esc(n.nombre)} · ${esc(n.proyecto)}${n.estado_migracion ? ` · ${esc(n.estado_migracion)}` : ""}</title>`
        + `<circle cx="${p.x}" cy="${p.y}" r="${radio}" fill="${COLOR_TIPO[n.tipo] || "#9aa3ad"}" stroke="${borde}" stroke-width="${n.estado_migracion === "validada" ? 3 : 1.5}"/>`
        + `<text x="${p.x}" y="${p.y + radio + 13}" font-size="${centro ? 13 : 11}" font-weight="${centro ? "bold" : "normal"}" text-anchor="middle" fill="#1d2128">`
        + `${esc(corto(n.nombre, centro ? 40 : 26))}</text></g>`;
    }).join("");
    caja.innerHTML = `<div class="rm-barra"><b>Red de mufas</b>`
      + `<label>Saltos <select id="rm-saltos"><option value="1"${saltos === 1 ? " selected" : ""}>1</option><option value="2"${saltos === 2 ? " selected" : ""}>2</option></select></label>`
      + `<span class="nota">${r.nodos.length} elementos · ${r.cables.length} cables · doble clic (o Tab y Enter) entra a una mufa · borde verde: validada</span></div>`
      + `<svg width="${ancho}" height="${alto}" viewBox="0 0 ${ancho} ${alto}" role="img" aria-label="Red de mufas">${lineas}${nodos}</svg>`;
  }

  async function pintar() {
    const caja = $("mu-red-vista");
    caja.hidden = !visible;
    $("mu-red").textContent = visible ? "Ver cables" : "Red de mufas";
    $("mu-konva").hidden = visible || !!(window.BandejasMufa && window.BandejasMufa.visible);
    if (!visible) return;
    const r = await Redes.llamar("red_de_mufas", { mufa_id: window.EditorMufa._st.mufaId, saltos });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    datos = r;
    dibujar();
  }

  function alternar() {
    visible = !visible;
    if (visible && window.BandejasMufa) window.BandejasMufa.ocultar();
    pintar();
  }

  function ocultar() {
    if (!visible) return;
    visible = false;
    pintar();
  }

  async function entrar(g) {
    const otro = { id: Number(g.dataset.id), nombre: g.dataset.nombre, tipo: g.dataset.tipo };
    if (otro.id === window.EditorMufa._st.mufaId) { ocultar(); return; }
    visible = false;
    await window.EditorMufa._navegar(otro);
    pintar();
  }

  const caja = $("mu-red-vista");
  $("mu-red").addEventListener("click", alternar);
  caja.addEventListener("dblclick", (e) => { const g = e.target.closest(".rm-nodo"); if (g) entrar(g); });
  caja.addEventListener("keydown", (e) => {
    const g = e.target.closest && e.target.closest(".rm-nodo");
    if (g && e.key === "Enter") { e.preventDefault(); e.stopPropagation(); entrar(g); }
  });
  caja.addEventListener("change", (e) => { if (e.target.id === "rm-saltos") { saltos = Number(e.target.value); pintar(); } });

  window.RedMufas = { pintar, alternar, ocultar, get visible() { return visible; } };
})();
