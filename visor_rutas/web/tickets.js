/* Tickets pendientes de presupuesto (menú «Tickets»): los tickets abiertos de Kayako que piden un presupuesto, con lo que el programa lee de cada uno para hacerlo.
 *
 * Lista a la izquierda (los que todavía no tienen presupuesto; los que ya tienen se pueden mostrar) y, al abrir uno, a la derecha todo lo que se extrajo (cliente,
 * código, contacto, teléfono, coordenadas, servicio, velocidad, medio, ejecutivo…) junto con el texto del ticket. «Hacer presupuesto» abre «Nuevo presupuesto» con el
 * formulario ya llenado. Kayako solo se lee. Un presupuesto «ya hecho» es un Excel de output/visor cuyo nombre empieza con el número del ticket.
 *
 *   Tickets.iniciar({api, aviso, rellenar})   Tickets.mostrar()
 *
 * Tres carpetas: «Presupuesto» (lo de arriba, tal cual), «Incidencias masivas» (todos los tickets de ese departamento de Kayako menos los cerrados) e «Instalaciones» (los de cinco estados),
 * de cualquier fecha y tipo; se ven igual que los de presupuesto, sin los botones del presupuesto y con el historial de comentarios y notas de cada ticket (api.ticket_historial, se pide al
 * abrirlo). Se leen al abrir la carpeta (api.tickets_carpeta).
 * Pestañas como de navegador: la principal es la lista (con las carpetas); doble clic en un ticket, o «Abrir en pestaña», lo abre en la suya, solo ese ticket y con todo el espacio.
 * La barra bajo la lista se arrastra para cambiar el alto de la lista y del detalle.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const st = { ctx: null, tickets: [], error: "", elegido: null, coordenada: 0, conHechos: false, cargado: 0, cargando: false,
               carpeta: "presupuesto", listas: {},                          // listas: the other folders {tickets, error, cargado, cargando}
               pestanas: [], pestana: "lista", historiales: {}, firma: "" };  // pestanas: the tickets opened in their own tab {clave, carpeta, ticket, copia}; historiales: {kayakoId: {datos, error, cargado, cargando}}
  const PESTANAS_MAX = 12, HISTORIAL_FRESCO_MS = 60000;
  const CARPETAS = {
    presupuesto: { titulo: "Tickets pendientes de presupuesto", corto: "Presup.", nota: "Tickets abiertos de Kayako que piden un presupuesto de FO.", vacio: "No hay tickets pendientes de presupuesto" },
    incidencias_masivas: { titulo: "Incidencias masivas", corto: "Incid.", nota: "Todos los tickets de Incidencias Masivas, menos los cerrados. Con sus comentarios y notas.", vacio: "No hay incidencias masivas sin cerrar" },
    instalaciones: { titulo: "Instalaciones", corto: "Instal.", nota: "Tickets de Instalaciones abiertos, agendados, en planificación, en progreso o en espera del cliente. Con sus comentarios y notas.", vacio: "No hay instalaciones en esos estados" },
  };
  const esPresupuesto = () => st.carpeta === "presupuesto";
  const actual = () => (esPresupuesto() ? st : st.listas[st.carpeta] || { tickets: [], error: "", cargado: 0, cargando: false });
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

  /** The tickets of another folder (incidencias masivas, instalaciones): every ticket of that department except the closed ones. */
  async function cargarCarpeta(clave) {
    const lista = st.listas[clave] || (st.listas[clave] = { tickets: [], error: "", cargado: 0, cargando: false });
    if (lista.cargando) return;
    lista.cargando = true; pintar();
    let r;
    try { r = await st.ctx.api().tickets_carpeta(clave); } catch (e) { r = { ok: false, error: `Los tickets no están disponibles: cierre el visor y ábralo de nuevo (${e})` }; }
    lista.cargando = false;
    if (r.ok) { lista.tickets = r.tickets; lista.error = ""; lista.cargado = Date.now(); } else { lista.error = r.error; lista.tickets = []; }
    pintar();
  }

  /** Reads the folder that is open (the budget one has its own read, which also feeds the badge of the menu). */
  function recargar() { if (esPresupuesto()) cargar(); else cargarCarpeta(st.carpeta); }

  function elegirCarpeta(clave) {
    if (!CARPETAS[clave] || clave === st.carpeta) return;
    st.carpeta = clave; st.elegido = null; st.coordenada = 0; st.pestana = "lista";
    const lista = esPresupuesto() ? null : st.listas[clave];
    if (!esPresupuesto() && (!lista || !lista.cargado)) cargarCarpeta(clave); else pintar();
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
    const pendientes = st.tickets.filter((t) => t.pendiente).length;                // only the budget folder: the menu badge
    const insignia = $("tickets-contador");
    if (insignia) { insignia.hidden = !pendientes; insignia.textContent = pendientes; }
    const lista = $("tk-lista");
    if (!lista) return;
    const c = actual(), info = CARPETAS[st.carpeta];
    $("tk-titulo").textContent = info.titulo; $("tk-nota").textContent = info.nota;
    $("tk-hechos-caja").hidden = !esPresupuesto();
    document.querySelectorAll(".tk-carpeta").forEach((b) => { const activa = b.dataset.carpeta === st.carpeta; b.classList.toggle("activa", activa); b.setAttribute("aria-selected", activa ? "true" : "false"); });
    Object.entries(st.listas).forEach(([clave, l]) => { const n = $(`tk-n-${clave}`); if (n && l.cargado) { n.hidden = false; n.textContent = l.tickets.length; } });
    const nP = $("tk-n-presupuesto"); if (nP && st.cargado) { nP.hidden = !pendientes; nP.textContent = pendientes; }
    $("tk-estado").textContent = c.cargando ? "Leyendo Kayako…" : c.cargado ? `Actualizado ${new Date(c.cargado).toLocaleTimeString("es-NI", { timeStyle: "short" })}` : "";
    const vistos = esPresupuesto() ? c.tickets.filter((t) => st.conHechos || t.pendiente) : c.tickets;
    const cuerpo = lista.querySelector("tbody");
    cuerpo.innerHTML = c.error ? `<tr><td colspan="9" class="error" style="padding:20px">${esc(c.error)}</td></tr>`
      : vistos.length ? vistos.map((t) => {
        const p = String(t.prioridad || "").toLowerCase();
        return `<tr data-ticket="${esc(t.ticket)}" class="${t.vencido ? "vencido" : ""} ${st.elegido === t.ticket ? "sel" : ""}"><td class="id">${esc(t.ticket)}</td>
          <td class="prioridad ${p.includes("alta") ? "alta" : p.includes("nivel") ? "nivel" : ""}">${esc(t.prioridad)}</td><td class="org" title="${esc(t.organizacion)}">${esc(t.organizacion)}</td>
          <td class="estado">${esc(t.estado)}</td><td class="asunto">${esc(t.asunto)}${esPresupuesto() ? (t.pendiente ? "" : ' <span class="vp-hist-etiqueta">Con presupuesto</span>') : (t.tipo ? ` <span class="tk-tipo">${esc(t.tipo)}</span>` : "")}</td>
          <td class="actividad">${esc(haceCuanto(t.ultima_actividad))}</td><td>${esc(t.ultimo_respondedor)}</td><td class="n">${t.respuestas}</td><td>${esc(t.owner || "")}</td></tr>`;
      }).join("")
        : `<tr><td colspan="9" class="nota" style="text-align:center;padding:24px">${c.cargando ? "Leyendo…" : esc(info.vacio)}</td></tr>`;
    pintarPestanas();
    if (st.pestana === "lista") pintarDetalle(); else pintarPagina();
  }

  // ------------------------------------------------------------------ pestañas: la principal es la lista; cada ticket abierto tiene la suya
  /** The ticket of a tab: from the list of its folder (live), else the copy kept when it was opened (it was closed or changed status since). */
  function ticketDePestana(p) {
    const lista = p.carpeta === "presupuesto" ? st.tickets : (st.listas[p.carpeta] || { tickets: [] }).tickets;
    return lista.find((x) => x.ticket === p.ticket) || p.copia;
  }

  function pintarPestanas() {
    const enLista = st.pestana === "lista";
    $("tk-pestanas").innerHTML = `<button type="button" role="tab" class="tk-pest ${enLista ? "activa" : ""}" data-pestana="lista" aria-selected="${enLista}">Tickets</button>`
      + st.pestanas.map((p) => {
        const t = ticketDePestana(p), activa = st.pestana === p.clave;
        return `<span class="tk-pest-caja ${activa ? "activa" : ""}"><button type="button" role="tab" class="tk-pest" data-pestana="${esc(p.clave)}" aria-selected="${activa}" title="${esc(t.asunto)}">${esc(p.ticket)}<small>${esc(CARPETAS[p.carpeta].corto)}</small></button>`
          + `<button type="button" class="tk-pest-x" data-cerrar="${esc(p.clave)}" aria-label="Cerrar la pestaña de ${esc(p.ticket)}" title="Cerrar">✕</button></span>`;
      }).join("");
    document.querySelector(".tk-carpetas").hidden = !enLista;
    document.querySelector(".tk-cuerpo").hidden = !enLista;
    $("tk-pagina").hidden = enLista;
  }

  function abrirPestana(ticket) {
    const t = actual().tickets.find((x) => x.ticket === ticket);
    if (!t) return;
    const clave = `${st.carpeta}:${ticket}`;
    if (!st.pestanas.some((p) => p.clave === clave)) {
      if (st.pestanas.length >= PESTANAS_MAX) st.pestanas.shift();                  // the oldest one makes room
      st.pestanas.push({ clave, carpeta: st.carpeta, ticket, copia: t });
    }
    activarPestana(clave);
  }

  function activarPestana(clave) {
    st.firma = "";
    if (clave === "lista") { st.pestana = "lista"; pintar(); return; }
    const p = st.pestanas.find((x) => x.clave === clave);
    if (!p) return;
    st.pestana = clave; st.carpeta = p.carpeta; st.elegido = p.ticket; st.coordenada = 0;
    pintar();
  }

  function cerrarPestana(clave) {
    const i = st.pestanas.findIndex((p) => p.clave === clave);
    if (i < 0) return;
    st.pestanas.splice(i, 1);
    if (st.pestana === clave) activarPestana(st.pestanas[i] ? st.pestanas[i].clave : st.pestanas[i - 1] ? st.pestanas[i - 1].clave : "lista"); else pintar();
  }

  /** The page of a ticket (its tab): only that ticket, with all the room. It is drawn again only when the ticket changes, so what is being read does not jump. */
  function pintarPagina() {
    const p = st.pestanas.find((x) => x.clave === st.pestana);
    if (!p) return;
    const t = ticketDePestana(p), enLista = actual().tickets.some((x) => x.ticket === p.ticket);
    const firma = `${p.clave}|${t.estado}|${t.ultima_actividad}|${t.respuestas}|${t.pendiente}|${(t.presupuestos || []).length}|${enLista}|${st.coordenada}`;
    if (firma === st.firma) return;
    st.firma = firma;
    const caja = $("tk-pagina");
    caja.innerHTML = `<div class="tk-pagina-barra"><button type="button" class="btn btn-chico" data-tk="volver">← Volver a la lista</button>`
      + `${enLista ? "" : '<span class="nota">Este ticket ya no está en la lista (se cerró o cambió de estado): se muestra como estaba.</span>'}</div><div class="tk-pagina-cuerpo">${htmlDetalle(t, true)}</div>`;
    pedirHistoriales(caja);
  }

  function fila(etiqueta, valor) {
    return valor ? `<dt>${esc(etiqueta)}</dt><dd>${esc(valor)}</dd>` : `<dt>${esc(etiqueta)}</dt><dd class="nota">el ticket no lo dice</dd>`;
  }

  const botonPestana = (enPagina) => (enPagina ? "" : '<button type="button" class="btn btn-chico" data-tk="pestana" title="Abrir este ticket en su propia pestaña">↗ Abrir en pestaña</button>');

  /** The detail of a ticket of the other folders: what Kayako has of it and what could be read from its text (no budget buttons), then its whole history. */
  function htmlGeneral(t, enPagina) {
    const s = t.sugerencia || {}, lugares = s.coordenadas || [];
    const dato = (etiqueta, valor) => (valor ? `<dt>${esc(etiqueta)}</dt><dd>${esc(valor)}</dd>` : "");
    return `<div class="tk-titulo-fila"><div style="min-width:0"><h2>${esc(t.asunto || t.ticket)}</h2><p class="nota">${esc(t.ticket)}${t.tipo ? ` · ${esc(t.tipo)}` : ""}</p></div>${botonPestana(enPagina)}</div>
      <dl class="tk-datos">${dato("Ticket", t.ticket)}${dato("Departamento", t.departamento)}${dato("Tipo", t.tipo)}${dato("Estado en Kayako", t.estado)}${dato("Prioridad", t.prioridad)}
        ${dato("Organización", t.organizacion)}${dato("Cliente", s.client_name || t.cliente)}${dato("Código de cliente", s.client_code)}${dato("Contacto", s.contact_name)}${dato("Teléfono", s.contact_phone)}
        ${dato("Correo", s.correo)}${dato("Dirección", s.direccion)}${dato("Sucursal", s.sucursal)}${dato("Servicio", s.servicio)}${dato("Velocidad", s.bandwidth)}${dato("Medio", s.medium)}
        ${dato("Ejecutivo", t.ejecutivo)}${dato("Dueño", t.owner)}${dato("Creado", fechaHora(t.creado))}${dato("Última actividad", fechaHora(t.ultima_actividad))}
        ${dato("Último en responder", t.ultimo_respondedor)}${dato("Respuestas", String(t.respuestas ?? ""))}${t.vence ? dato("Vence", fechaHora(t.vence)) : ""}
        ${lugares.length ? `<dt>Coordenadas</dt><dd>${lugares.map((c) => esc(c)).join("<br>")}</dd>` : ""}</dl>
      <section class="tk-historial" data-hist="${esc(t.kayako_id)}"><h3>Historial de comentarios y notas</h3><div class="tk-hist-cuerpo"></div></section>`;
  }

  // ------------------------------------------------------------------ historial: los comentarios y las notas de un ticket (se piden al abrirlo)
  /** Reads the history of the tickets shown in `caja` (once; kept for a minute) and draws it where it goes. */
  function pedirHistoriales(caja) {
    caja.querySelectorAll("[data-hist]").forEach((s) => pedirHistorial(Number(s.dataset.hist)));
  }

  async function pedirHistorial(id) {
    const h = st.historiales[id] || (st.historiales[id] = { datos: null, error: "", cargado: 0, cargando: false });
    if (h.cargando || (h.cargado && Date.now() - h.cargado < HISTORIAL_FRESCO_MS)) { pintarHistorial(id); return; }
    h.cargando = true; pintarHistorial(id);
    let r;
    try { r = await st.ctx.api().ticket_historial(id); } catch (e) { r = { ok: false, error: `El historial no está disponible: cierre el visor y ábralo de nuevo (${e})` }; }
    h.cargando = false;
    if (r.ok) { h.datos = r; h.error = ""; h.cargado = Date.now(); } else { h.error = r.error; }
    pintarHistorial(id);
  }

  function ticketPorKayako(id) {
    for (const lista of Object.values(st.listas)) { const t = lista.tickets.find((x) => String(x.kayako_id) === String(id)); if (t) return t; }
    return null;
  }

  /** Comments and notes in the order they were written; a note is the yellow one staff leave in Kayako. */
  function htmlHistorial(id) {
    const h = st.historiales[id];
    if (!h || (h.cargando && !h.datos)) return '<p class="nota">Leyendo el historial…</p>';
    if (!h.datos) {
      const t = ticketPorKayako(id);
      return `<p class="error">${esc(h.error)}</p>${t ? `<pre class="tk-texto">${esc(t.comentario || "(sin comentario)")}${t.ultimo_comentario ? "\n\n--- último comentario ---\n" + esc(t.ultimo_comentario) : ""}</pre>` : ""}`;
    }
    const { comentarios, notas } = h.datos;
    const orden = [...comentarios.map((c) => ({ tipo: "c", ...c })), ...notas.map((n) => ({ tipo: "n", ...n }))].sort((a, b) => String(a.fecha).localeCompare(String(b.fecha)) || (a.tipo === "c" ? -1 : 1));
    const resumen = `<p class="tk-hist-resumen">${comentarios.length} comentario${comentarios.length === 1 ? "" : "s"} · ${notas.length} nota${notas.length === 1 ? "" : "s"}${h.cargando ? " · actualizando…" : ""}</p>`;
    return resumen + (orden.length ? orden.map((x) => (x.tipo === "n"
      ? `<article class="tk-nota-k"><header><span>📝 Nota de</span> <b>${esc(x.autor)}</b>${x.editada ? '<span class="tk-etiqueta">editada</span>' : ""}<time>${esc(fechaHora(x.fecha))}</time></header><pre class="tk-msg-texto">${esc(x.texto)}</pre></article>`
      : `<article class="tk-msg ${esc(x.origen)} ${x.privado ? "privado" : ""}"><header><b>${esc(x.autor || "—")}</b><span class="tk-etiqueta ${x.origen === "personal" ? "personal" : ""}">${x.origen === "cliente" ? "Cliente" : x.origen === "personal" ? "Personal" : "Otro"}</span>`
        + `${x.privado ? '<span class="tk-etiqueta">Privado</span>' : ""}${x.adjuntos ? '<span class="tk-etiqueta">Adjuntos</span>' : ""}<time>${esc(fechaHora(x.fecha))}</time></header><pre class="tk-msg-texto">${esc(x.texto || "(sin texto)")}</pre></article>`)).join("")
      : '<p class="nota">Este ticket no tiene comentarios.</p>');
  }

  function pintarHistorial(id) {
    document.querySelectorAll(`[data-hist="${id}"] .tk-hist-cuerpo`).forEach((c) => { c.innerHTML = htmlHistorial(id); });
  }

  /** The detail of a ticket of the budget folder (as it always was), with the button to open it in its tab. */
  function htmlPresupuesto(t, enPagina) {
    const s = t.sugerencia, lugares = s.coordenadas || [];
    return `<div class="tk-titulo-fila"><div style="min-width:0"><h2>${esc(s.client_name || t.ticket)}</h2><p class="nota">${esc(t.asunto)}</p></div>${botonPestana(enPagina)}</div>
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

  const htmlDetalle = (t, enPagina) => (esPresupuesto() ? htmlPresupuesto(t, enPagina) : htmlGeneral(t, enPagina));

  /** The detail under the list (the ticket chosen); it is drawn again only when the ticket or what is shown of it changes. */
  function pintarDetalle() {
    const caja = $("tk-detalle");
    const t = actual().tickets.find((x) => x.ticket === st.elegido);
    const firma = t ? `${st.carpeta}|${t.ticket}|${t.estado}|${t.ultima_actividad}|${t.respuestas}|${t.pendiente}|${(t.presupuestos || []).length}|${st.coordenada}` : `${st.carpeta}|nada`;
    if (firma === st.firmaDetalle && caja.innerHTML) return;
    st.firmaDetalle = firma;
    if (!t) { caja.innerHTML = esPresupuesto() ? '<p class="vacio">Elija un ticket de la lista para ver lo que el programa lee de él y hacer su presupuesto.</p>' : '<p class="vacio">Elija un ticket de la lista para ver lo que dice, con sus comentarios y notas. Doble clic: abrirlo en su pestaña.</p>'; return; }
    caja.innerHTML = htmlDetalle(t, false);
    pedirHistoriales(caja);
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
    $("tk-lista").addEventListener("dblclick", (e) => { const fila = e.target.closest("[data-ticket]"); if (fila) abrirPestana(fila.dataset.ticket); });     // the ticket in its own tab
    const alCambiar = (e) => { if (e.target.id === "tk-coordenada") st.coordenada = Number(e.target.value); };
    const alPulsar = (e) => {
      if (e.target.closest("[data-tk=pestana]")) { abrirPestana(st.elegido); return; }
      if (e.target.closest("[data-tk=volver]")) { activarPestana("lista"); return; }
      if (e.target.closest("[data-tk=todas]")) { todasLasCoordenadas(); return; }
      if (!e.target.closest("[data-tk=hacer]")) return;
      const t = st.tickets.find((x) => x.ticket === st.elegido);
      if (!t) return;
      const s = t.sugerencia;
      st.ctx.rellenar({ ...s, coordenada: (s.coordenadas || [])[st.coordenada] || "" });
    };
    ["tk-detalle", "tk-pagina"].forEach((id) => { $(id).addEventListener("change", alCambiar); $(id).addEventListener("click", alPulsar); });
    $("tk-pestanas").addEventListener("click", (e) => {
      const x = e.target.closest("[data-cerrar]"), p = e.target.closest("[data-pestana]");
      if (x) cerrarPestana(x.dataset.cerrar); else if (p) activarPestana(p.dataset.pestana);
    });
    $("tk-pestanas").addEventListener("auxclick", (e) => { const p = e.target.closest("[data-pestana]"); if (e.button === 1 && p && p.dataset.pestana !== "lista") { e.preventDefault(); cerrarPestana(p.dataset.pestana); } });   // middle click closes
    conectarDivisor();
    $("tk-recargar").addEventListener("click", recargar);
    document.querySelector(".tk-carpetas").addEventListener("click", (e) => { const b = e.target.closest("[data-carpeta]"); if (b) elegirCarpeta(b.dataset.carpeta); });
    $("tk-con-hechos").addEventListener("change", (e) => { st.conHechos = e.target.checked; pintar(); });
  }

  /** The height of the list is changed by dragging the bar under it (or with the arrows); a double click puts it back. It is remembered. */
  function conectarDivisor() {
    const div = $("tk-divisor"), cuerpo = document.querySelector(".tk-cuerpo"), caja = document.querySelector(".tk-tabla-caja");
    const poner = (px) => {
      const v = Math.round(Math.max(90, Math.min(Math.max(90, cuerpo.clientHeight - 140), px)));
      cuerpo.style.setProperty("--tk-alto", `${v}px`);
      try { localStorage.setItem("tk_alto", String(v)); } catch (e) { /* without storage it is not remembered */ }
    };
    try { const guardado = Number(localStorage.getItem("tk_alto")); if (guardado >= 90) cuerpo.style.setProperty("--tk-alto", `${guardado}px`); } catch (e) { /* nothing saved */ }
    div.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      div.setPointerCapture(e.pointerId);
      const y0 = e.clientY, h0 = caja.getBoundingClientRect().height;
      div.classList.add("activo");
      const mover = (ev) => poner(h0 + ev.clientY - y0);
      const soltar = () => { div.classList.remove("activo"); div.removeEventListener("pointermove", mover); div.removeEventListener("pointerup", soltar); div.removeEventListener("pointercancel", soltar); };
      div.addEventListener("pointermove", mover); div.addEventListener("pointerup", soltar); div.addEventListener("pointercancel", soltar);
    });
    div.addEventListener("dblclick", () => { cuerpo.style.removeProperty("--tk-alto"); try { localStorage.removeItem("tk_alto"); } catch (e) { /* nothing saved */ } });
    div.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      poner(caja.getBoundingClientRect().height + (e.key === "ArrowDown" ? 24 : -24));
    });
  }

  let listo = false;
  function iniciar(ctx) {
    st.ctx = ctx;
    if (!listo) { listo = true; conectar(); }
    cargar();                                                                  // the badge of the menu counts the pending ones from the start
    setInterval(() => { if (!document.hidden) { cargar(); if (!esPresupuesto() && $("vista-tickets") && !$("vista-tickets").hidden) cargarCarpeta(st.carpeta); } }, 120000);
    setInterval(() => { if (!document.hidden && $("vista-tickets") && !$("vista-tickets").hidden) pintar(); }, 30000);          // «hace cuánto» keeps counting
  }

  window.Tickets = { iniciar, mostrar: () => {
    const c = actual();
    if (!c.cargado || Date.now() - c.cargado > 30000) recargar(); else pintar();
  }, elegirCarpeta, _st: st };
})();
