/* Tickets pendientes de presupuesto (menú «Tickets»): los tickets abiertos de Kayako que piden un presupuesto, con lo que el programa lee de cada uno para hacerlo.
 *
 * Lista a la izquierda (los que todavía no tienen presupuesto; los que ya tienen se pueden mostrar) y, al abrir uno, a la derecha todo lo que se extrajo (cliente,
 * código, contacto, teléfono, coordenadas, servicio, velocidad, medio, ejecutivo…) junto con el texto del ticket. «Hacer presupuesto» abre «Nuevo presupuesto» con el
 * formulario ya llenado. Kayako solo se lee. Un presupuesto «ya hecho» es un Excel de output/visor cuyo nombre empieza con el número del ticket.
 *
 *   Tickets.iniciar({api, aviso, rellenar})   Tickets.mostrar()
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const st = { ctx: null, tickets: [], error: "", elegido: null, coordenada: 0, conHechos: false, cargado: 0, cargando: false };
  const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString("es-NI", { dateStyle: "short", timeStyle: "short" }) : "—");

  async function cargar() {
    if (st.cargando) return;
    st.cargando = true; pintar();
    let r;
    try { r = await st.ctx.api().tickets_pendientes(); } catch (e) { r = { ok: false, error: `Los tickets no están disponibles: cierre el visor y ábralo de nuevo (${e})` }; }
    st.cargando = false;
    if (r.ok) { st.tickets = r.tickets; st.error = ""; st.cargado = Date.now(); } else { st.error = r.error; st.tickets = []; }
    pintar();
  }

  /** «22m 24s», «19h 39m 19s», «2d 3h»: how long ago, as Kayako writes it. */
  function haceCuanto(iso) {
    if (!iso) return "—";
    let s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    s %= 60;
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m ${s}s` : m ? `${m}m ${s}s` : `${s}s`;
  }

  /** The list as Kayako's own: ticket, priority (high one in red, «Nivel» in green), organization, status (yellow), subject, last activity (orange and a pink row when its due time passed),
   *  who answered last, replies and owner; the most recent activity first. */
  function pintar() {
    const pendientes = st.tickets.filter((t) => t.pendiente).length;
    const insignia = $("tickets-contador");
    if (insignia) { insignia.hidden = !pendientes; insignia.textContent = pendientes; }
    const lista = $("tk-lista");
    if (!lista) return;
    $("tk-estado").textContent = st.cargando ? "Leyendo Kayako…" : st.cargado ? `Actualizado ${new Date(st.cargado).toLocaleTimeString("es-NI", { timeStyle: "short" })}` : "";
    const vistos = st.tickets.filter((t) => st.conHechos || t.pendiente);
    const cuerpo = lista.querySelector("tbody");
    cuerpo.innerHTML = st.error ? `<tr><td colspan="9" class="error" style="padding:20px">${esc(st.error)}</td></tr>`
      : vistos.length ? vistos.map((t) => {
        const p = String(t.prioridad || "").toLowerCase();
        return `<tr data-ticket="${esc(t.ticket)}" class="${t.vencido ? "vencido" : ""} ${st.elegido === t.ticket ? "sel" : ""}"><td class="id">${esc(t.ticket)}</td>
          <td class="prioridad ${p.includes("alta") ? "alta" : p.includes("nivel") ? "nivel" : ""}">${esc(t.prioridad)}</td><td class="org" title="${esc(t.organizacion)}">${esc(t.organizacion)}</td>
          <td class="estado">${esc(t.estado)}</td><td class="asunto">${esc(t.asunto)}${t.pendiente ? "" : ' <span class="vp-hist-etiqueta">Con presupuesto</span>'}</td>
          <td class="actividad">${esc(haceCuanto(t.ultima_actividad))}</td><td>${esc(t.ultimo_respondedor)}</td><td class="n">${t.respuestas}</td><td>${esc(t.owner || "")}</td></tr>`;
      }).join("")
        : `<tr><td colspan="9" class="nota" style="text-align:center;padding:24px">${st.cargando ? "Leyendo…" : "No hay tickets pendientes de presupuesto"}</td></tr>`;
    pintarDetalle();
  }

  function fila(etiqueta, valor) {
    return valor ? `<dt>${esc(etiqueta)}</dt><dd>${esc(valor)}</dd>` : `<dt>${esc(etiqueta)}</dt><dd class="nota">el ticket no lo dice</dd>`;
  }

  function pintarDetalle() {
    const caja = $("tk-detalle");
    const t = st.tickets.find((x) => x.ticket === st.elegido);
    if (!t) { caja.innerHTML = '<p class="vacio">Elija un ticket de la lista para ver lo que el programa lee de él y hacer su presupuesto.</p>'; return; }
    const s = t.sugerencia, lugares = s.coordenadas || [];
    caja.innerHTML = `<h2>${esc(s.client_name || t.ticket)}</h2><p class="nota">${esc(t.asunto)}</p>
      <dl class="tk-datos">${fila("Ticket", t.ticket)}${fila("Estado en Kayako", t.estado)}${fila("Última actividad", fechaHora(t.ultima_actividad))}${fila("Cliente", s.client_name)}${fila("Código de cliente", s.client_code)}
        ${fila("Ejecutivo de ventas", s.sales_exec)}${fila("Contacto", s.contact_name)}${fila("Teléfono", s.contact_phone)}${fila("Correo", s.correo)}${fila("Dirección", s.direccion)}
        ${fila("Servicio", s.servicio)}${fila("Velocidad", s.bandwidth)}${fila("Medio", s.medium)}
        <dt>Coordenada</dt><dd>${lugares.length > 1 ? `<select id="tk-coordenada" aria-label="Coordenada">${lugares.map((c, i) => `<option value="${i}" ${i === st.coordenada ? "selected" : ""}>${esc(c)}</option>`).join("")}</select> <span class="nota">el ticket trae ${lugares.length}</span>`
          : lugares.length ? esc(lugares[0]) : '<span class="nota">el ticket no la dice: se escribe al hacer el presupuesto</span>'}</dd></dl>
      ${t.presupuestos.length ? `<div class="vp-avisos"><b>Ya hay presupuestos de este ticket:</b><ul>${t.presupuestos.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>` : ""}
      <div class="tk-acciones"><button type="button" class="btn btn-primario" data-tk="hacer">Hacer presupuesto</button>${lugares.length > 1
        ? ` <button type="button" class="btn" data-tk="todas" title="Un presupuesto por cada coordenada del ticket, como en «Coordenadas masivas»">Presupuesto de las ${lugares.length} coordenadas</button>` : ""}</div>
      <details><summary>Texto del ticket</summary><pre class="tk-texto">${esc(t.comentario || "(sin comentario)")}${t.ultimo_comentario ? "\\n\\n--- último comentario ---\\n" + esc(t.ultimo_comentario) : ""}</pre></details>`;
  }

  /** The ticket brings several coordinates: one budget for each, in the window of «Coordenadas masivas» with the ticket, the client and the comment already in it. */
  function todasLasCoordenadas() {
    const t = st.tickets.find((x) => x.ticket === st.elegido);
    if (!t || !st.ctx.masivas) return;
    const s = t.sugerencia, lugares = s.coordenadas || [];
    const cliente = (s.client_name || "").trim();
    const puntos = lugares.map((c, i) => {
      const [lat, lon] = String(c).split(",").map((x) => Number(x.trim()));
      return { n: i + 1, ticket: t.ticket, nombre: cliente ? `${cliente} ${i + 1}` : `Punto ${i + 1}`, codigo: s.client_code || "", texto: String(c), lat, lon, estado: "ok", motivo: "", sugerencia: null, incluir: true };
    });
    st.ctx.masivas({ nombre: `${t.ticket}_${(cliente || "ticket").replace(/[^\p{L}\p{N} _-]/gu, "").trim()}.txt`, puntos, comentario: t.comentario || "" });
  }

  function conectar() {
    $("tk-lista").addEventListener("click", (e) => {
      const fila = e.target.closest("[data-ticket]");
      if (!fila) return;
      st.elegido = fila.dataset.ticket; st.coordenada = 0; pintar();
    });
    $("tk-detalle").addEventListener("change", (e) => { if (e.target.id === "tk-coordenada") st.coordenada = Number(e.target.value); });
    $("tk-detalle").addEventListener("click", (e) => {
      if (e.target.closest("[data-tk=todas]")) { todasLasCoordenadas(); return; }
      if (!e.target.closest("[data-tk=hacer]")) return;
      const t = st.tickets.find((x) => x.ticket === st.elegido);
      if (!t) return;
      const s = t.sugerencia;
      st.ctx.rellenar({ ...s, coordenada: (s.coordenadas || [])[st.coordenada] || "" });
    });
    $("tk-recargar").addEventListener("click", cargar);
    $("tk-con-hechos").addEventListener("change", (e) => { st.conHechos = e.target.checked; pintar(); });
  }

  let listo = false;
  function iniciar(ctx) {
    st.ctx = ctx;
    if (!listo) { listo = true; conectar(); }
    cargar();                                                                  // the badge of the menu counts the pending ones from the start
    setInterval(() => { if (!document.hidden) cargar(); }, 120000);
    setInterval(() => { if (!document.hidden && $("vista-tickets") && !$("vista-tickets").hidden) pintar(); }, 30000);          // «hace cuánto» keeps counting
  }

  window.Tickets = { iniciar, mostrar: () => { if (!st.cargado || Date.now() - st.cargado > 30000) cargar(); else pintar(); }, _st: st };
})();
