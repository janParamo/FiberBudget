/* PDF de presupuestos que ya existen (menú Presupuestos > Historial > «Convertir a PDF…»).
 *
 * Dos listas con casillas: los Excel sueltos del historial (uno o varios) y las carpetas de coordenadas masivas con sus grupos (aprobados / desaprobados,
 * o la carpeta sin separar de los lotes anteriores). «Convertir» hace el PDF de todo lo marcado en segundo plano (visor_rutas/pdf_lote.py): el PDF de un Excel
 * suelto queda junto a él; el de un grupo, en aprobados_pdf / desaprobados_pdf (o pdf) dentro del lote. Al terminar: abrir la carpeta o bajar un .zip.
 *
 *   PdfExistentes.abrir({api, aviso})
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const st = { ctx: null, sueltos: [], lotes: [], externos: [], marcados: new Set(), marcadosCarpetas: new Set(), filtro: "", trabajo: null, sondeo: null, estado: "", tipoEstado: "", cargando: false };

  const api = () => st.ctx.api();
  const estado = (texto, tipo = "") => { st.estado = texto; st.tipoEstado = tipo; pintar(); };
  const cantidad = () => st.marcados.size + st.marcadosCarpetas.size + st.externos.length;
  const nombreDe = (ruta) => String(ruta).replace(/[\\/]+$/, "").split(/[\\/]/).pop();

  async function cargar() {
    st.cargando = true; pintar();
    const pedir = async (metodo) => {                       // a Python side that is older than the page has no such method: say so instead of showing nothing
      try { return await api()[metodo](); } catch (e) { return { ok: false, error: `${metodo} no está disponible: cierre el visor y ábralo de nuevo (${e})` }; }
    };
    const [h, c] = await Promise.all([pedir("historial_presupuestos"), pedir("pdf_carpetas")]);
    st.cargando = false;
    st.sueltos = h.ok ? h.presupuestos : [];
    st.lotes = c.ok ? c.carpetas : [];
    st.estado = ""; st.tipoEstado = "";
    if (!h.ok || !c.ok) estado(h.ok ? c.error : h.error, "error"); else pintar();
  }

  async function convertir() {
    if (!cantidad()) { estado("Marque al menos un presupuesto o una carpeta", "error"); return; }
    estado("Iniciando…", "cargando");
    const externos = { archivos: st.externos.filter((x) => x.tipo === "archivo").map((x) => x.ruta), carpetas: st.externos.filter((x) => x.tipo === "carpeta").map((x) => x.ruta) };
    const r = await api().pdf_convertir([...st.marcados], [...st.marcadosCarpetas], externos).catch((e) => ({ ok: false, error: String(e) }));
    if (!r.ok) { estado(r.error, "error"); return; }
    st.trabajo = r.trabajo; estado("");
    if (!st.sondeo) st.sondeo = setInterval(sondear, 1200);
  }

  async function sondear() {
    if (!st.trabajo) return;
    const r = await api().pdf_estado(st.trabajo.id).catch((e) => ({ ok: false, error: String(e) }));
    if (!r.ok) { clearInterval(st.sondeo); st.sondeo = null; estado(r.error, "error"); return; }
    st.trabajo = r.trabajo;
    if (r.trabajo.estado !== "convirtiendo") {
      clearInterval(st.sondeo); st.sondeo = null;
      const t = r.trabajo;
      st.ctx.aviso(t.estado === "listo" ? `${t.pdf} PDF listos${t.fallos.length ? `, ${t.fallos.length} fallaron` : ""}` : "No se pudo hacer ningún PDF", t.estado === "listo" && !t.fallos.length ? "ok" : "error");
      cargar();                                   // the counts of PDF made change
    }
    pintar();
  }

  const claveDe = (a) => (String(a).startsWith("remoto:") ? String(a).slice(7) + ".xlsx" : String(a).split(/[\\/]/).pop());

  /** «Llevar a planificación»: one activity per Excel of what is marked (the loose budgets and the groups of the batches, not what was chosen in the explorer). */
  async function aPlanificacion() {
    if (!st.marcados.size && !st.marcadosCarpetas.size) { estado("Marque presupuestos sueltos o carpetas de masivas (no sirven los del explorador)", "error"); return; }
    estado("Llevando a planificación…", "cargando");
    const r = await api().redes("plan_llevar", { archivos: [...st.marcados].map(claveDe), carpetas: [...st.marcadosCarpetas] }).catch((e) => ({ ok: false, error: String(e) }));
    if (!r.ok) { estado(r.error, "error"); return; }
    const motivos = r.resultados.filter((x) => !x.ok && !x.repetida).slice(0, 3).map((x) => `${x.archivo}: ${x.error}`);
    estado(`${r.creadas} actividad(es) creada(s) en Planificación` + (r.repetidas ? `, ${r.repetidas} ya estaban` : "") + (r.fallidas ? `, ${r.fallidas} con problema (${motivos.join(" | ")})` : ""),
           r.fallidas ? "error" : "ok");
  }

  async function elegir(tipo) {
    let r;
    try { r = await api().pdf_elegir(tipo); } catch (e) { r = { ok: false, error: `El explorador no está disponible: cierre el visor y ábralo de nuevo (${e})` }; }
    if (!r.ok) { estado(r.error, "error"); return; }
    if (r.cancelado) return;
    r.rutas.forEach((ruta) => { if (!st.externos.some((x) => x.ruta === ruta)) st.externos.push({ ruta, tipo: tipo === "carpeta" ? "carpeta" : "archivo" }); });
    estado("");
  }

  async function accion(a) {
    if (a === "carpeta") {
      const r = await api().pdf_abrir_carpeta(st.trabajo.id);
      if (!r.ok) estado(r.error, "error");
    } else if (a === "zip") {
      const r = await api().pdf_descargar(st.trabajo.id);
      if (!r.ok) { estado(r.error, "error"); return; }
      const g = window.Redes ? await window.Redes.guardarArchivo(r.nombre, r.datos, "zip") : { ok: false, error: "No disponible" };
      if (g.ok) estado(`Guardado en ${g.ruta}`, "ok"); else if (!g.cancelado) estado(g.error, "error");
    }
  }

  function visibles() {
    const f = st.filtro.trim().toLowerCase();
    return st.sueltos.filter((p) => !f || `${p.cliente} ${p.coordenada || ""} ${p.nombre}`.toLowerCase().includes(f));
  }

  function pintar() {
    const c = $("pdfx-cuerpo");
    if (!c) return;
    const trabajando = st.trabajo && st.trabajo.estado === "convirtiendo";
    const sueltos = visibles();
    const pie = st.estado ? `<div class="nota ik-estado ${esc(st.tipoEstado)}">${st.tipoEstado === "cargando" ? '<span class="spinner"></span> ' : ""}${esc(st.estado)}</div>` : "";
    let progreso = "";
    if (st.trabajo) {
      const t = st.trabajo, pct = t.total ? Math.round(t.hechos * 100 / t.total) : 0;
      progreso = `<div class="ik-archivo"><b>${t.estado === "convirtiendo" ? "Convirtiendo…" : t.estado === "listo" ? "Listo" : "Sin PDF"}</b>
          <span class="nota">${t.hechos} de ${t.total}${t.actual ? ` · ${esc(t.actual)}` : ""}${t.fallos.length ? ` · fallaron: ${esc(t.fallos.join(", "))}` : ""}</span></div>
        <div class="ms-barra"><div style="width:${pct}%"></div></div>
        ${t.estado !== "convirtiendo" && t.pdf ? `<div class="ik-pie"><button type="button" class="btn" data-pdfx="carpeta">Abrir carpeta</button>
          <button type="button" class="btn btn-primario" data-pdfx="zip">Guardar .zip…</button></div>` : ""}`;
    }
    const sel = c.querySelector(".pdfx-scroll"), alto = sel ? sel.scrollTop : 0;
    c.innerHTML = `${progreso}
      <p class="ik-ayuda">Marque los presupuestos de Excel que quiere pasar a PDF: sueltos, o carpetas de coordenadas masivas (un grupo a la vez, aprobados o desaprobados).
        El PDF de un Excel suelto queda junto a él; el de una carpeta, en <i>aprobados_pdf</i> / <i>desaprobados_pdf</i> dentro del lote.</p>
      <div class="pdfx-scroll">
      <h3 class="ik-titulo">Elegidos en el explorador</h3>
      <div class="pdfx-filtro"><button type="button" class="btn btn-chico" data-pdfx="elegir_archivos" ${trabajando ? "disabled" : ""}>Elegir archivos…</button>
        <button type="button" class="btn btn-chico" data-pdfx="elegir_carpeta" ${trabajando ? "disabled" : ""}>Elegir carpeta…</button></div>
      ${st.externos.length ? `<ul class="pdfx-lista">${st.externos.map((x, i) => `<li><label><b>${x.tipo === "carpeta" ? "Carpeta" : "Excel"}</b> ${esc(nombreDe(x.ruta))}
        <span class="nota" title="${esc(x.ruta)}">${esc(x.ruta)}</span></label> <button type="button" class="btn btn-chico" data-pdfx="quitar_externo" data-i="${i}" ${trabajando ? "disabled" : ""}>Quitar</button></li>`).join("")}</ul>`
        : `<p class="nota">Con «Elegir carpeta» se convierte todo lo que tenga dentro (en un lote con aprobados / desaprobados, cada grupo a su carpeta de PDF).</p>`}
      <h3 class="ik-titulo">Carpetas de coordenadas masivas</h3>
      ${st.lotes.length ? st.lotes.map((l) => `<div class="pdfx-lote"><b>${esc(l.nombre)}</b> <span class="nota">${esc(l.fecha)} · ${l.xlsx} presupuestos</span>
        ${l.grupos.map((g) => `<label class="pdfx-grupo"><input type="checkbox" data-pdfx="carpeta_marca" data-id="${esc(g.id)}" ${st.marcadosCarpetas.has(g.id) ? "checked" : ""} ${trabajando ? "disabled" : ""}>
          ${esc(g.nombre)} <span class="nota">${g.xlsx} Excel${g.pdf ? ` · ${g.pdf} PDF ya hechos` : ""}</span></label>`).join("")}</div>`).join("")
        : `<p class="nota">${st.cargando ? "Leyendo…" : "No hay carpetas de coordenadas masivas"}</p>`}
      <h3 class="ik-titulo">Presupuestos sueltos</h3>
      <div class="pdfx-filtro"><input type="search" id="pdfx-filtro" data-pdfx="filtro" placeholder="Filtrar por cliente o coordenada" value="${esc(st.filtro)}">
        <button type="button" class="btn btn-chico" data-pdfx="todos">Marcar los que se ven</button><button type="button" class="btn btn-chico" data-pdfx="ninguno">Quitar marcas</button></div>
      ${sueltos.length ? `<ul class="pdfx-lista">${sueltos.map((p) => `<li><label><input type="checkbox" data-pdfx="marca" data-id="${esc(p.archivo)}" ${st.marcados.has(p.archivo) ? "checked" : ""} ${trabajando ? "disabled" : ""}>
        <b>${esc(p.cliente)}</b> <span class="nota">${esc(String(p.fecha).replace("T", " ").slice(0, 16))}${p.coordenada ? ` · ${esc(p.coordenada)}` : ""}${p.tiene_pdf ? " · ya tiene PDF" : ""}</span></label></li>`).join("")}</ul>`
        : `<p class="nota">${st.cargando ? "Leyendo…" : "No hay presupuestos sueltos"}</p>`}
      </div>
      <div class="ik-pie"><button type="button" class="btn btn-primario" data-pdfx="convertir" ${cantidad() && !trabajando ? "" : "disabled"}>Convertir a PDF (${cantidad()})</button>
        <button type="button" class="btn" data-pdfx="plan" ${(st.marcados.size || st.marcadosCarpetas.size) && !trabajando ? "" : "disabled"} title="Crear en Planificación una actividad por cada presupuesto marcado">Llevar a planificación</button>
        <button type="button" class="btn" data-pdfx="recargar" ${trabajando ? "disabled" : ""}>Recargar</button></div>${pie}`;
    const nueva = c.querySelector(".pdfx-scroll");
    if (nueva) nueva.scrollTop = alto;
    const f = $("pdfx-filtro");
    if (f && document.activeElement === document.body && st.filtro) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
  }

  function crear() {
    if ($("pdfx-ventana")) return;
    document.body.insertAdjacentHTML("beforeend", `<aside id="pdfx-ventana" class="ik-ventana ms-ventana" hidden aria-label="Convertir presupuestos a PDF">
      <header class="ik-cabecera"><h2>Convertir presupuestos a PDF</h2><button type="button" class="btn-icono" data-pdfx="cerrar" aria-label="Cerrar">✕</button></header>
      <div id="pdfx-cuerpo" class="ik-cuerpo"></div></aside>`);
    const v = $("pdfx-ventana");
    v.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pdfx]");
      if (!b) return;
      const a = b.dataset.pdfx;
      if (a === "cerrar") v.hidden = true;
      else if (a === "convertir") convertir();
      else if (a === "plan") aPlanificacion();
      else if (a === "recargar") cargar();
      else if (a === "todos") { visibles().forEach((p) => st.marcados.add(p.archivo)); pintar(); }
      else if (a === "ninguno") { st.marcados.clear(); st.marcadosCarpetas.clear(); st.externos = []; pintar(); }
      else if (a === "elegir_archivos") elegir("archivos");
      else if (a === "elegir_carpeta") elegir("carpeta");
      else if (a === "quitar_externo") { st.externos.splice(Number(b.dataset.i), 1); pintar(); }
      else if (a === "carpeta" || a === "zip") accion(a);
    });
    v.addEventListener("change", (e) => {
      const b = e.target.closest("[data-pdfx]");
      if (!b) return;
      const conjunto = b.dataset.pdfx === "marca" ? st.marcados : b.dataset.pdfx === "carpeta_marca" ? st.marcadosCarpetas : null;
      if (conjunto) { if (b.checked) conjunto.add(b.dataset.id); else conjunto.delete(b.dataset.id); pintar(); }
    });
    v.addEventListener("input", (e) => {
      if (e.target.dataset.pdfx === "filtro") { st.filtro = e.target.value; pintar(); }
    });
  }

  function abrir(ctx) {
    st.ctx = ctx;
    crear();
    $("pdfx-ventana").hidden = false;
    cargar();
  }

  window.PdfExistentes = { abrir, get estado() { return { sueltos: st.sueltos.length, lotes: st.lotes.length, marcados: cantidad() }; }, _st: st };
})();
