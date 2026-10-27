/* App de planificación: cuadrillas, actividades, cola, estados, puntos de control y tiempos (API /visor/planificacion/*, clave del visor). */
(function () {
  "use strict";

  const CLAVE = "planificacion.clave";
  const REFRESCO_MS = 15000;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const COLOR = { inactivo: "#9aa0ab", asignado: "#5c7cfa", en_revision: "#ab47bc", en_curso: "#1f6feb", pausado: "#fb8c00", terminado: "#2ca02c", no_viable: "#8d6e63", cancelado: "#e53935" };
  const ETIQUETA = { inactivo: "Inactivo", asignado: "Asignado", en_revision: "En revisión", en_curso: "En curso", pausado: "Pausado", terminado: "Terminado", no_viable: "No viable", cancelado: "Cancelado" };
  const st = { catalogo: null, tablero: null, cuadrillas: [], actividades: [], todas: [], tecnicos: [], marcadas: new Set(), filtro: { estado: "", cuadrilla: "", buscar: "" }, detalleId: null,
               vista: "lista", mapa: null, capaMapa: null, cargadoEn: Date.now(), temporizador: null, ajustado: false };

  // The key also lives in memory: inside the viewer's window (pywebview, private mode) the browser may not keep localStorage.
  const memoria = {};
  const leer = (k) => { try { const v = localStorage.getItem(k); if (v != null) return v; } catch (e) { /* private window */ } return memoria[k] ?? null; };
  const guardar = (k, v) => {
    if (v == null) delete memoria[k]; else memoria[k] = v;
    try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ }
  };
  // Opened from the viewer: the key comes in the address (#clave=...); it is saved and taken out of the address bar.
  (function () {
    const m = /(?:^#|&)clave=([^&]+)/.exec(location.hash);
    if (!m) return;
    guardar(CLAVE, decodeURIComponent(m[1]));
    history.replaceState(null, "", location.pathname + location.search);
  })();

  class ErrorApi extends Error {
    constructor(mensaje, estado, errores) { super(mensaje); this.estado = estado; this.errores = errores || null; }
  }

  async function pedir(metodo, ruta, cuerpo) {
    const cab = { "X-Visor-Key": leer(CLAVE) || "", "ngrok-skip-browser-warning": "1" };
    if (cuerpo !== undefined) cab["Content-Type"] = "application/json";
    let r;
    try { r = await fetch("/visor/planificacion" + ruta, { method: metodo, headers: cab, body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) }); }
    catch (e) { throw new ErrorApi("Sin conexión con el servidor", 0); }
    let datos = null;
    try { datos = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) {
      const texto = r.status === 401 ? "La clave no es válida" : (datos && (datos.error || (typeof datos.detail === "string" && datos.detail))) ||
        (r.status === 404 ? "El servicio no está disponible" : `Error ${r.status}`);
      throw new ErrorApi(texto, r.status, datos && datos.errores);
    }
    return datos;
  }

  function duracion(s) {
    if (s == null) return "—";
    s = Math.max(0, Math.round(s));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return `${d} d ${h} h`;
    if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
    if (m) return `${m} min`;
    return `${s} s`;
  }
  const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString("es-NI", { dateStyle: "short", timeStyle: "short" }) : "—");
  const etiqueta = (e) => `<span class="etiqueta" style="--c:${COLOR[e] || "#999"}">${esc(ETIQUETA[e] || e)}</span>`;

  /** A clock that keeps running in the page between refreshes: espera runs while waiting, ejecución while in progress. */
  function reloj(a, tipo) {
    const base = tipo === "espera" ? a.espera_s : a.ejecucion_s;
    if (base == null) return "—";
    const corre = tipo === "espera" ? ["asignado", "en_revision"].includes(a.estado) : a.estado === "en_curso";
    const alerta = tipo === "espera" && a.sin_iniciar_alerta ? " alerta-tiempo" : "";
    return `<span class="${alerta.trim()}" ${corre ? `data-reloj="${base}" data-desde="${st.cargadoEn}"` : ""}>${duracion(base)}</span>`;
  }
  function tic() {
    const ahora = Date.now();
    document.querySelectorAll("[data-reloj]").forEach((el) => { el.textContent = duracion(Number(el.dataset.reloj) + (ahora - Number(el.dataset.desde)) / 1000); });
  }

  // ------------------------------------------------------------------ carga
  function estadoConexion(texto, error) { const e = $("estado-conexion"); e.textContent = texto; e.className = error ? "nota error" : "nota"; }

  async function cargar(conDetalle = true) {
    try {
      if (!st.catalogo) { st.catalogo = await pedir("GET", "/catalogo"); llenarFiltros(); }
      const q = new URLSearchParams();
      if (st.filtro.estado) q.set("estado", st.filtro.estado);
      if (st.filtro.cuadrilla) q.set("cuadrilla_id", st.filtro.cuadrilla);
      if (st.filtro.buscar) q.set("buscar", st.filtro.buscar);
      const sinFiltro = !q.toString();
      const [t, c, a, todas, tec] = await Promise.all([pedir("GET", "/tablero"), pedir("GET", "/cuadrillas"), pedir("GET", "/actividades?" + q.toString()),
        sinFiltro ? null : pedir("GET", "/actividades"), pedir("GET", "/tecnicos")]);          // the queues are drawn from all the activities, whatever the filter
      st.tablero = t; st.cuadrillas = c.cuadrillas; st.actividades = a.actividades; st.todas = todas ? todas.actividades : a.actividades; st.tecnicos = tec.tecnicos;
      st.cargadoEn = Date.now();
      estadoConexion(`Actualizado ${new Date().toLocaleTimeString("es-NI", { timeStyle: "short" })}`);
      pintar();
      if (conDetalle && st.detalleId) abrirDetalle(st.detalleId, true);
    } catch (e) {
      if (e.estado === 401 || e.estado === 403) { guardar(CLAVE, null); mostrarClave(e.estado === 403 ? "Esa clave no es de planificación (rol editor o administrador)" : e.message); return; }
      estadoConexion(e.message, true);
    }
  }

  function llenarFiltros() {
    $("filtro-estado").innerHTML = '<option value="">Todos los estados</option>' + st.catalogo.estados.map((e) => `<option value="${e.clave}">${esc(e.etiqueta)}</option>`).join("");
    $("filtro-estado").value = st.filtro.estado;
  }

  // ------------------------------------------------------------------ pintar
  function pintar() {
    pintarTablero(); pintarLateral(); pintarFiltrosCuadrilla(); pintarTabla(); pintarCuadrillas();
    if (st.vista === "mapa") pintarMapa();
  }

  function pintarTablero() {
    const t = st.tablero;
    $("tablero").innerHTML = Object.keys(ETIQUETA).map((e) => `<div class="carta ${st.filtro.estado === e ? "sel" : ""}" data-estado="${e}" style="--c:${COLOR[e]}"><b>${t.por_estado[e] || 0}</b><span>${esc(ETIQUETA[e])}</span></div>`).join("") +
      `<div class="carta fija"><b>${duracion(t.espera_media_s)}</b><span>Espera media</span></div><div class="carta fija"><b>${duracion(t.ejecucion_media_s)}</b><span>Ejecución media</span></div>`;
    const al = $("alertas");
    al.hidden = !t.sin_iniciar.length;
    al.innerHTML = t.sin_iniciar.length ? `Sin iniciar hace más de ${t.alerta_min} min: ` + t.sin_iniciar.map((x) => `<a data-id="${x.id}">${esc(x.cliente_nombre)}</a> (${esc(x.cuadrilla)}, ${duracion(x.espera_s)})`).join(" · ") : "";
  }

  function haceTexto(u) {
    if (!u) return '<span class="punto"></span>sin ubicación';
    const m = Math.round(u.hace_s / 60);
    return `<span class="punto ${m <= 5 ? "vivo" : "viejo"}"></span>${esc(u.quien)} · hace ${m < 1 ? "menos de 1 min" : duracion(u.hace_s)}`;
  }

  function pintarLateral() {
    let html = "", empresa = null;
    for (const c of st.cuadrillas) {
      if (c.empresa !== empresa) { empresa = c.empresa; html += `<div class="grupo-empresa">${esc(c.empresa)}${c.tercerizada ? "" : " (propia)"}</div>`; }
      html += `<div class="cuadrilla ${String(st.filtro.cuadrilla) === String(c.id) ? "sel" : ""} ${c.activa ? "" : "inactiva"}" data-cuadrilla="${c.id}"><b>${esc(c.nombre)}</b>
        <div class="carga">${c.en_curso ? "1 en curso" : "libre"} · ${c.en_cola} en cola · ${c.terminadas} terminadas</div><div class="carga">${haceTexto(c.ubicacion)}</div></div>`;
    }
    $("lateral").innerHTML = html;
  }

  function pintarFiltrosCuadrilla() {
    const opciones = st.cuadrillas.filter((c) => c.activa).map((c) => `<option value="${c.id}">${esc(c.nombre)}</option>`).join("");
    const f = $("filtro-cuadrilla"), a = $("asignar-a"), fv = f.value, av = a.value;
    f.innerHTML = '<option value="">Todas las cuadrillas</option>' + st.cuadrillas.map((c) => `<option value="${c.id}">${esc(c.nombre)}</option>`).join("");
    a.innerHTML = '<option value="">Asignar lo marcado a…</option>' + opciones;
    f.value = st.filtro.cuadrilla || fv; a.value = av;
    $("asignar").disabled = !st.marcadas.size || !a.value;
  }

  function pintarTabla() {
    const cuerpo = $("tabla").querySelector("tbody");
    st.marcadas = new Set([...st.marcadas].filter((id) => st.actividades.some((a) => a.id === id)));
    cuerpo.innerHTML = st.actividades.length ? st.actividades.map((a) => `<tr data-id="${a.id}" class="${st.detalleId === a.id ? "sel" : ""}">
      <td><input type="checkbox" data-marca="${a.id}" ${st.marcadas.has(a.id) ? "checked" : ""} ${["inactivo", "asignado", "en_revision"].includes(a.estado) ? "" : "disabled"} aria-label="Marcar"></td>
      <td>${esc(a.ticket || "—")}</td><td class="cliente"><b>${esc(a.cliente_nombre)}</b><br><span class="nota">${esc(a.codigo_cliente)}</span></td>
      <td>${etiqueta(a.estado)}${a.iniciada_por === "planificacion" && a.estado === "en_curso" ? ' <span class="nota" title="La inició planificación">(plan.)</span>' : ""}</td>
      <td>${esc(a.cuadrilla || "—")}</td><td>${reloj(a, "espera")}</td><td>${reloj(a, "ejecucion")}</td>
      <td><span class="barra-avance"><i style="width:${a.avance.porcentaje}%"></i></span>${a.avance.hechos}/${a.avance.total}</td></tr>`).join("")
      : '<tr><td colspan="8" class="nota" style="text-align:center;padding:24px">No hay actividades con ese filtro</td></tr>';
    $("asignar").disabled = !st.marcadas.size || !$("asignar-a").value;
  }

  /** The queue of a crew, in the order the crew will take it (drag a row or use the arrows). */
  function colaDe(c) {
    const cola = st.todas.filter((a) => a.cuadrilla_id === c.id && ["asignado", "en_revision", "pausado"].includes(a.estado)).sort((x, y) => x.cola_orden - y.cola_orden || x.id - y.id);
    if (!cola.length) return '<span class="nota">Cola vacía</span>';
    return `<ol class="cola" data-cola="${c.id}">${cola.map((a, i) => `<li draggable="true" data-id="${a.id}"><span class="agarre" title="Arrastre para ordenar">⠿</span>
      <a data-id-abrir="${a.id}"><b>${esc(a.cliente_nombre)}</b></a> <span class="nota">${esc(ETIQUETA[a.estado])}</span>
      <span class="flechas"><button type="button" class="chico" data-sube="${a.id}" ${i === 0 ? "disabled" : ""} aria-label="Subir">▲</button><button type="button" class="chico" data-baja="${a.id}" ${i === cola.length - 1 ? "disabled" : ""} aria-label="Bajar">▼</button></span></li>`).join("")}</ol>`;
  }

  function miembrosDe(c) {
    const libres = st.tecnicos.filter((t) => t.cuadrilla_id !== c.id);
    return `<div class="miembros">${c.miembros.length ? c.miembros.map((m) => `<span class="miembro">${esc(m.nombre)} <button type="button" class="chico" data-quitar-miembro="${m.usuario_id}" data-cuadrilla-id="${c.id}" aria-label="Quitar a ${esc(m.nombre)}">✕</button></span>`).join("")
      : '<span class="nota">Sin miembros: nadie ve esta cuadrilla en su teléfono todavía</span>'}</div>
      ${libres.length ? `<div class="acciones"><select data-agregar-select="${c.id}" aria-label="Técnico"><option value="">Agregar técnico…</option>${libres.map((t) => `<option value="${t.id}">${esc(t.nombre)}${t.cuadrilla ? ` (hoy en ${esc(t.cuadrilla)})` : ""}</option>`).join("")}</select>
        <button type="button" data-agregar="${c.id}">Agregar</button></div>` : '<span class="nota">No hay más técnicos (los crea un administrador con el rol «técnico»)</span>'}`;
  }

  function pintarCuadrillas() {
    // not while a row is being dragged or a technician is being chosen: the periodic refresh would take it away from under the hand
    if (st.arrastrando || (document.activeElement && document.activeElement.matches("#lista-cuadrillas select"))) return;
    $("lista-cuadrillas").innerHTML = st.cuadrillas.map((c) => `<div class="tarjeta"><b>${esc(c.nombre)}</b><span class="nota">${esc(c.empresa)}${c.telefono ? " · " + esc(c.telefono) : ""}</span>
      <span>${c.en_curso ? "1 en curso" : "libre"} · ${c.en_cola} en cola · ${c.terminadas} terminadas</span>
      <span class="nota">${haceTexto(c.ubicacion)}</span>
      <h4>Cola</h4>${colaDe(c)}
      <h4>Miembros</h4>${miembrosDe(c)}
      <div class="acciones"><button type="button" data-activar="${c.id}" data-activa="${c.activa ? 0 : 1}">${c.activa ? "Desactivar" : "Activar"}</button></div></div>`).join("");
  }

  async function guardarCola(cuadrillaId, ids) {
    try { await pedir("POST", `/cuadrillas/${cuadrillaId}/cola`, { ids }); await cargar(false); }
    catch (e) { estadoConexion(textoError(e), true); await cargar(false); }
  }
  const textoError = (e) => (e.errores ? Object.values(e.errores).join(" · ") : e.message);
  const idsDeCola = (ol) => [...ol.querySelectorAll("li[data-id]")].map((li) => Number(li.dataset.id));

  // ------------------------------------------------------------------ mapa
  function pintarMapa() {
    if (!st.mapa) {
      st.mapa = L.map("mapa").setView([12.6, -85.9], 7);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(st.mapa);
      st.capaMapa = L.layerGroup().addTo(st.mapa);
    }
    st.capaMapa.clearLayers();
    const puntos = [];
    st.actividades.filter((a) => !["terminado", "cancelado"].includes(a.estado)).forEach((a) => {
      puntos.push([a.lat, a.lon]);
      L.circleMarker([a.lat, a.lon], { radius: 8, color: "#fff", weight: 2, fillColor: COLOR[a.estado], fillOpacity: 1 })
        .bindPopup(`<b>${esc(a.cliente_nombre)}</b><br>${esc(ETIQUETA[a.estado])}${a.cuadrilla ? " · " + esc(a.cuadrilla) : ""}<br>${esc(a.contacto_nombre)} ${esc(a.contacto_telefono)}`)
        .on("click", () => abrirDetalle(a.id)).addTo(st.capaMapa);
    });
    st.cuadrillas.filter((c) => c.ubicacion).forEach((c) => {
      puntos.push([c.ubicacion.lat, c.ubicacion.lon]);
      L.marker([c.ubicacion.lat, c.ubicacion.lon], { icon: L.divIcon({ className: "", iconSize: [0, 0], html: `<div style="transform:translate(-50%,-100%);background:#1f2430;color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;white-space:nowrap">${esc(c.nombre)}</div>` }) })
        .bindPopup(haceTexto(c.ubicacion)).addTo(st.capaMapa);
    });
    if (puntos.length && !st.ajustado) { st.mapa.fitBounds(L.latLngBounds(puntos), { padding: [40, 40], maxZoom: 15 }); st.ajustado = true; }
    setTimeout(() => st.mapa.invalidateSize(), 50);
  }

  // ------------------------------------------------------------------ detalle
  function accionesDe(a) {
    const b = (clave, texto, extra = "") => `<button type="button" data-a="${clave}" ${extra}>${texto}</button>`;
    switch (a.estado) {
      case "inactivo": return b("cancelado", "Cancelar");
      case "asignado": return b("en_curso", "Dar por iniciada") + b("en_revision", "Pasar a revisión") + b("inactivo", "Quitar de la cola") + b("cancelado", "Cancelar");
      case "en_revision": return b("en_curso", "Dar por iniciada") + b("no_viable", "No viable") + b("asignado", "Volver a asignado") + b("cancelado", "Cancelar");
      case "en_curso": return b("pausado", "Pausar") + b("terminado", "Terminar") + b("en_revision", "Volver a revisión") + b("cancelado", "Cancelar");
      case "pausado": return b("en_curso", "Reanudar") + b("no_viable", "No viable") + b("cancelado", "Cancelar");
      case "no_viable": case "cancelado": return b("inactivo", "Reactivar");
      default: return '<span class="nota">Terminada</span>';
    }
  }

  async function abrirDetalle(id, silencioso) {
    st.detalleId = id;
    let d;
    try { d = (await pedir("GET", `/actividades/${id}`)).actividad; } catch (e) { if (!silencioso) estadoConexion(e.message, true); return; }
    const cajas = $("detalle");
    cajas.hidden = false;
    const r = d.resumen || {};
    const reasignable = ["inactivo", "asignado", "en_revision"].includes(d.estado);
    const maps = `https://www.google.com/maps?q=${d.lat},${d.lon}`;
    cajas.innerHTML = `<button type="button" class="cerrar secundario" data-cerrar>✕</button>
      <h2>${esc(d.cliente_nombre)}</h2><div>${etiqueta(d.estado)} ${d.motivo_estado ? `<span class="nota">${esc(d.motivo_estado)}</span>` : ""}</div>
      <dl><dt>Ticket</dt><dd>${esc(d.ticket || "—")}</dd><dt>Código</dt><dd>${esc(d.codigo_cliente || "—")}</dd>
        <dt>Contacto</dt><dd>${esc(d.contacto_nombre || "—")}</dd><dt>Teléfono</dt><dd>${d.contacto_telefono ? `<a href="tel:${esc(d.contacto_telefono)}">${esc(d.contacto_telefono)}</a>` : "—"}</dd>
        <dt>Coordenada</dt><dd><a href="${maps}" target="_blank" rel="noopener">${d.lat.toFixed(6)}, ${d.lon.toFixed(6)}</a></dd>${d.direccion ? `<dt>Dirección</dt><dd>${esc(d.direccion)}</dd>` : ""}
        <dt>Origen</dt><dd>${esc(d.origen)}</dd>${d.presupuesto_total != null ? `<dt>Presupuesto</dt><dd>C$ ${d.presupuesto_total.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd>` : ""}
        ${r.metraje_final_m ? `<dt>Metraje</dt><dd>${Math.round(r.metraje_final_m)} m</dd>` : ""}
        <dt>Cuadrilla</dt><dd>${esc(d.cuadrilla || "—")}${d.empresa ? ` (${esc(d.empresa)})` : ""}</dd>
        <dt>Asignada</dt><dd>${fechaHora(d.asignada_en)}</dd><dt>Inició</dt><dd>${fechaHora(d.iniciada_en)}${d.iniciada_por === "planificacion" ? " (la inició planificación)" : ""}</dd>
        <dt>Espera</dt><dd>${reloj(d, "espera")}</dd><dt>Ejecución</dt><dd>${reloj(d, "ejecucion")}</dd></dl>
      <p id="det-error" class="error" hidden></p>
      <h3>Acciones</h3><div class="acciones" data-id="${d.id}">${accionesDe(d)}</div>
      ${reasignable ? `<div class="acciones"><select id="det-cuadrilla">${st.cuadrillas.filter((c) => c.activa).map((c) => `<option value="${c.id}" ${c.id === d.cuadrilla_id ? "selected" : ""}>${esc(c.nombre)}</option>`).join("")}</select>
        <button type="button" data-asignar-detalle="${d.id}">${d.cuadrilla ? "Reasignar" : "Asignar"}</button></div>` : ""}
      <h3>Puntos de control · ${d.avance.hechos}/${d.avance.total}</h3>
      <ul class="controles">${d.controles.map((c) => `<li><span class="etiqueta" style="--c:${c.estado === "hecho" ? "#2ca02c" : c.estado === "en_proceso" ? "#fb8c00" : "#9aa0ab"}">${c.estado === "hecho" ? "Hecho" : c.estado === "en_proceso" ? "En proceso" : "Pendiente"}</span>
        <span>${esc(c.etiqueta)}${c.obligatorio ? "" : ' <span class="nota">(opcional)</span>'}</span>
        <span class="quien">${c.marcado_en ? `${fechaHora(c.marcado_en)}<br>${esc(c.origen === "planificacion" ? "planificación" : "cuadrilla")}` : ""}</span>
        ${["terminado", "cancelado", "no_viable", "inactivo", "asignado"].includes(d.estado) ? "" : `<button type="button" data-control="${c.clave}" data-nuevo="${c.estado === "hecho" ? "pendiente" : "hecho"}">${c.estado === "hecho" ? "Quitar" : "Marcar"}</button>`}</li>`).join("")}</ul>
      <h3>Historial</h3><ul class="linea-tiempo">${d.historial.map((h) => `<li><b>${esc(ETIQUETA[h.a] || h.a)}</b>${h.cuadrilla ? ` · ${esc(h.cuadrilla)}` : ""}<br><span class="nota">${fechaHora(h.en)} · ${esc(h.por || "")} (${esc(h.origen || "")})${h.motivo ? " · " + esc(h.motivo) : ""}</span></li>`).join("")}</ul>`;
    document.querySelectorAll("#tabla tbody tr").forEach((tr) => tr.classList.toggle("sel", Number(tr.dataset.id) === id));
    tic();
  }

  function errorDetalle(e) {
    const caja = $("det-error");
    if (!caja) { estadoConexion(e.message, true); return; }
    caja.hidden = false;
    caja.textContent = e.errores ? Object.values(e.errores).join(" · ") : e.message;
  }

  async function cambiarEstado(id, a) {
    let motivo = "";
    if (["pausado", "no_viable", "cancelado"].includes(a)) {
      motivo = window.prompt(a === "pausado" ? "Motivo de la pausa" : a === "no_viable" ? "Por qué no es viable" : "Motivo de la cancelación") || "";
      if (!motivo.trim()) return;
    }
    let forzar = false;
    try {
      try { await pedir("POST", `/actividades/${id}/estado`, { a, motivo, forzar }); }
      catch (e) {
        if (a === "terminado" && e.errores && e.errores.controles && window.confirm(`${e.errores.controles}\n\n¿Terminar de todos modos?`)) { forzar = true; await pedir("POST", `/actividades/${id}/estado`, { a, motivo, forzar }); }
        else throw e;
      }
      await cargar();
    } catch (e) { errorDetalle(e); }
  }

  // ------------------------------------------------------------------ eventos
  function conectar() {
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
      st.vista = b.dataset.vista;
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("activa", x === b));
      ["lista", "mapa", "cuadrillas"].forEach((v) => { $("vista-" + v).hidden = v !== st.vista; });
      if (st.vista === "mapa") pintarMapa();
    }));
    $("tablero").addEventListener("click", (e) => {
      const c = e.target.closest("[data-estado]");
      if (!c) return;
      st.filtro.estado = st.filtro.estado === c.dataset.estado ? "" : c.dataset.estado;
      $("filtro-estado").value = st.filtro.estado; cargar(false);
    });
    $("alertas").addEventListener("click", (e) => { const a = e.target.closest("[data-id]"); if (a) abrirDetalle(Number(a.dataset.id)); });
    $("lateral").addEventListener("click", (e) => {
      const c = e.target.closest("[data-cuadrilla]");
      if (!c) return;
      st.filtro.cuadrilla = String(st.filtro.cuadrilla) === c.dataset.cuadrilla ? "" : c.dataset.cuadrilla;
      $("filtro-cuadrilla").value = st.filtro.cuadrilla; cargar(false);
    });
    let espera = null;
    $("buscar").addEventListener("input", (e) => { clearTimeout(espera); espera = setTimeout(() => { st.filtro.buscar = e.target.value.trim(); cargar(false); }, 300); });
    $("filtro-estado").addEventListener("change", (e) => { st.filtro.estado = e.target.value; cargar(false); });
    $("filtro-cuadrilla").addEventListener("change", (e) => { st.filtro.cuadrilla = e.target.value; cargar(false); });
    $("asignar-a").addEventListener("change", () => { $("asignar").disabled = !st.marcadas.size || !$("asignar-a").value; });
    $("asignar").addEventListener("click", async () => {
      try { await pedir("POST", "/actividades/asignar", { ids: [...st.marcadas], cuadrilla_id: Number($("asignar-a").value) }); st.marcadas.clear(); await cargar(); }
      catch (e) { estadoConexion(e.errores ? Object.values(e.errores).join(" · ") : e.message, true); }
    });
    $("tabla").addEventListener("click", (e) => {
      const marca = e.target.closest("[data-marca]");
      if (marca) { const id = Number(marca.dataset.marca); if (marca.checked) st.marcadas.add(id); else st.marcadas.delete(id); $("asignar").disabled = !st.marcadas.size || !$("asignar-a").value; return; }
      const fila = e.target.closest("tr[data-id]");
      if (fila) abrirDetalle(Number(fila.dataset.id));
    });
    $("detalle").addEventListener("click", async (e) => {
      const t = e.target;
      if (t.closest("[data-cerrar]")) { st.detalleId = null; $("detalle").hidden = true; pintarTabla(); return; }
      const a = t.closest("[data-a]");
      if (a) { cambiarEstado(st.detalleId, a.dataset.a); return; }
      const c = t.closest("[data-control]");
      if (c) {
        try { await pedir("POST", `/actividades/${st.detalleId}/control`, { clave: c.dataset.control, estado: c.dataset.nuevo }); await cargar(); } catch (er) { errorDetalle(er); }
        return;
      }
      const as = t.closest("[data-asignar-detalle]");
      if (as) {
        try { await pedir("POST", "/actividades/asignar", { ids: [st.detalleId], cuadrilla_id: Number($("det-cuadrilla").value) }); await cargar(); } catch (er) { errorDetalle(er); }
      }
    });
    $("lista-cuadrillas").addEventListener("click", async (e) => {
      const mover = e.target.closest("[data-sube], [data-baja]");
      if (mover) {
        const li = mover.closest("li"), ol = li.parentElement, id = Number(li.dataset.id), ids = idsDeCola(ol), i = ids.indexOf(id), j = mover.dataset.sube ? i - 1 : i + 1;
        if (j >= 0 && j < ids.length) { [ids[i], ids[j]] = [ids[j], ids[i]]; await guardarCola(Number(ol.dataset.cola), ids); }
        return;
      }
      const abrir = e.target.closest("[data-id-abrir]");
      if (abrir) { abrirDetalle(Number(abrir.dataset.idAbrir)); return; }
      const quitar = e.target.closest("[data-quitar-miembro]");
      if (quitar) {
        try { await pedir("POST", `/cuadrillas/${quitar.dataset.cuadrillaId}/miembros`, { usuario_id: Number(quitar.dataset.quitarMiembro), quitar: true }); await cargar(false); }
        catch (er) { estadoConexion(textoError(er), true); }
        return;
      }
      const agregar = e.target.closest("[data-agregar]");
      if (agregar) {
        const sel = agregar.parentElement.querySelector("select");
        if (!sel.value) { estadoConexion("Elija el técnico que se agrega", true); return; }
        try { await pedir("POST", `/cuadrillas/${agregar.dataset.agregar}/miembros`, { usuario_id: Number(sel.value) }); await cargar(false); }
        catch (er) { estadoConexion(textoError(er), true); }
        return;
      }
      const b = e.target.closest("[data-activar]");
      if (!b) return;
      try { await pedir("POST", `/cuadrillas/${b.dataset.activar}`, { cambios: { activa: b.dataset.activa === "1" } }); await cargar(false); } catch (er) { estadoConexion(er.message, true); }
    });
    // drag a row of a queue to another place of the same queue
    let arrastrada = null;
    $("lista-cuadrillas").addEventListener("dragstart", (e) => { const li = e.target.closest("li[data-id]"); if (li) { arrastrada = li; st.arrastrando = true; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", li.dataset.id); } });
    $("lista-cuadrillas").addEventListener("dragend", () => { arrastrada = null; st.arrastrando = false; });
    $("lista-cuadrillas").addEventListener("dragover", (e) => {
      const li = e.target.closest("li[data-id]");
      if (arrastrada && li && li.parentElement === arrastrada.parentElement) e.preventDefault();
    });
    $("lista-cuadrillas").addEventListener("drop", (e) => {
      const li = e.target.closest("li[data-id]");
      if (!arrastrada || !li || li === arrastrada || li.parentElement !== arrastrada.parentElement) return;
      e.preventDefault();
      const ol = li.parentElement, despues = e.clientY > li.getBoundingClientRect().top + li.offsetHeight / 2;
      ol.insertBefore(arrastrada, despues ? li.nextSibling : li);
      const ids = idsDeCola(ol);
      arrastrada = null; st.arrastrando = false;
      guardarCola(Number(ol.dataset.cola), ids);
    });
    $("form-cuadrilla").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await pedir("POST", "/cuadrillas", { empresa: $("cq-empresa").value, nombre: $("cq-nombre").value, telefono: $("cq-telefono").value });
        e.target.reset(); await cargar(false);
      } catch (er) { estadoConexion(er.errores ? Object.values(er.errores).join(" · ") : er.message, true); }
    });
    $("nueva-actividad").addEventListener("click", () => { $("nueva-error").hidden = true; $("form-nueva").reset(); $("dialogo-nueva").showModal(); });
    $("nueva-cancelar").addEventListener("click", () => $("dialogo-nueva").close());
    $("form-nueva").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target), m = String(f.get("coordenada")).match(/(-?\d+(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d+(?:[.,]\d+)?)/);
      const error = $("nueva-error");
      if (!m) { error.hidden = false; error.textContent = "Escriba la coordenada como «12.1364, -86.2514»"; return; }
      const cuerpo = { cliente_nombre: f.get("cliente_nombre"), ticket: f.get("ticket"), codigo_cliente: f.get("codigo_cliente"), contacto_nombre: f.get("contacto_nombre"),
                       contacto_telefono: f.get("contacto_telefono"), direccion: f.get("direccion"), lat: parseFloat(m[1].replace(",", ".")), lon: parseFloat(m[2].replace(",", ".")), origen: "manual" };
      try { const r = await pedir("POST", "/actividades", cuerpo); $("dialogo-nueva").close(); await cargar(false); abrirDetalle(r.id); }
      catch (er) { error.hidden = false; error.textContent = er.errores ? Object.values(er.errores).join(" · ") : er.message; }
    });
    $("salir").addEventListener("click", () => { guardar(CLAVE, null); clearInterval(st.temporizador); location.reload(); });
  }

  // ------------------------------------------------------------------ clave y arranque
  function mostrarClave(mensaje) {
    $("app").hidden = true; $("pantalla-clave").hidden = false;
    const e = $("clave-error"); e.hidden = !mensaje; e.textContent = mensaje || "";
  }

  let conectado = false;
  function entrar() {
    $("pantalla-clave").hidden = true; $("app").hidden = false;
    if (!conectado) { conectar(); conectado = true; }
    cargar();
    clearInterval(st.temporizador);
    st.temporizador = setInterval(() => { if (!document.hidden) cargar(); }, REFRESCO_MS);
    setInterval(tic, 1000);
  }

  $("clave-entrar").addEventListener("click", () => {
    const v = $("clave").value.trim();
    if (!v) { mostrarClave("Escriba la clave"); return; }
    guardar(CLAVE, v); entrar();
  });
  $("clave").addEventListener("keydown", (e) => { if (e.key === "Enter") $("clave-entrar").click(); });
  if (leer(CLAVE)) entrar(); else mostrarClave("");

  window.Planificacion = { _st: st, duracion };
})();
