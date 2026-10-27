/* App de la cuadrilla: la cola de instalaciones asignadas, la actividad en curso con el contacto y la coordenada, los puntos de control, pausar / terminar,
 * y la ubicación que se manda a planificación. Usa /visor/planificacion/* y /visor/campo/ubicacion con la clave del técnico. */
(function () {
  "use strict";

  const CLAVE = "cuadrilla.clave";
  const REFRESCO_MS = 15000, UBICACION_MS = 20000;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const COLOR = { asignado: "#5c7cfa", en_revision: "#ab47bc", en_curso: "#1f6feb", pausado: "#fb8c00" };
  const ETIQUETA = { asignado: "Asignado", en_revision: "En revisión", en_curso: "En curso", pausado: "Pausado" };
  const st = { datos: null, cargadoEn: Date.now(), temporizador: null, ubicacion: null, chatId: null, mensajes: [] };

  const leer = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const guardar = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ } };

  class ErrorApi extends Error {
    constructor(mensaje, estado, errores) { super(mensaje); this.estado = estado; this.errores = errores || null; }
  }

  async function pedir(metodo, ruta, cuerpo) {
    const cab = { "X-Visor-Key": leer(CLAVE) || "", "ngrok-skip-browser-warning": "1" };
    if (cuerpo !== undefined) cab["Content-Type"] = "application/json";
    let r;
    try { r = await fetch(ruta, { method: metodo, headers: cab, body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) }); }
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
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
    if (m) return `${m} min`;
    return `${s} s`;
  }
  function reloj(a, tipo) {
    const base = tipo === "espera" ? a.espera_s : a.ejecucion_s;
    if (base == null) return "—";
    const corre = tipo === "espera" ? ["asignado", "en_revision"].includes(a.estado) : a.estado === "en_curso";
    return `<span ${corre ? `data-reloj="${base}" data-desde="${st.cargadoEn}"` : ""}>${duracion(base)}</span>`;
  }
  function tic() {
    const ahora = Date.now();
    document.querySelectorAll("[data-reloj]").forEach((el) => { el.textContent = duracion(Number(el.dataset.reloj) + (ahora - Number(el.dataset.desde)) / 1000); });
  }

  function aviso(texto) {
    const a = $("aviso");
    a.hidden = !texto;
    a.textContent = texto || "";
    if (texto) window.scrollTo({ top: 0, behavior: "smooth" });
  }
  const textoError = (e) => (e.errores ? Object.values(e.errores).join(" · ") : e.message);

  // ------------------------------------------------------------------ ubicación
  function posicion(esperaMs) {
    return new Promise((resolver) => {
      if (!navigator.geolocation) { resolver(null); return; }
      navigator.geolocation.getCurrentPosition((p) => resolver({ lat: p.coords.latitude, lon: p.coords.longitude, precision_m: p.coords.accuracy }), () => resolver(null),
        { enableHighAccuracy: true, timeout: esperaMs, maximumAge: 15000 });
    });
  }
  async function mandarUbicacion() {
    const p = await posicion(8000);
    $("gps").textContent = p ? "GPS ✓" : "sin GPS";
    if (!p) return;
    try { await pedir("POST", "/visor/campo/ubicacion", { lat: p.lat, lon: p.lon, precision_m: p.precision_m, capturado_en: new Date().toISOString() }); } catch (e) { /* the next one tries again */ }
  }

  // ------------------------------------------------------------------ carga y pintado
  async function cargar() {
    try {
      st.datos = await pedir("GET", "/visor/planificacion/mia");
      st.cargadoEn = Date.now();
      if (st.chatId != null && ![...(st.datos.actual ? [st.datos.actual] : []), ...st.datos.cola].some((x) => x.id === st.chatId)) st.chatId = null;       // it left the crew
      $("estado").textContent = new Date().toLocaleTimeString("es-NI", { timeStyle: "short" });
      pintar();
      cargarChat();
    } catch (e) {
      if (e.estado === 401) { guardar(CLAVE, null); mostrarClave(e.message); return; }
      if (e.estado === 403) { $("contenido").innerHTML = `<p class="vacio error">${esc(e.message)}</p>`; return; }
      $("estado").textContent = e.message;
    }
  }

  function datosDe(a) {
    const maps = `https://www.google.com/maps/dir/?api=1&destination=${a.lat},${a.lon}`;
    return `<dl class="datos"><dt>Ticket</dt><dd>${esc(a.ticket || "—")}</dd>
      <dt>Contacto</dt><dd>${esc(a.contacto_nombre || "—")}</dd>
      <dt>Teléfono</dt><dd>${a.contacto_telefono ? `<a href="tel:${esc(a.contacto_telefono)}">${esc(a.contacto_telefono)}</a>` : "—"}</dd>
      <dt>Coordenada</dt><dd><a href="${maps}" target="_blank" rel="noopener">${a.lat.toFixed(6)}, ${a.lon.toFixed(6)} · Cómo llegar</a></dd>
      ${a.direccion ? `<dt>Dirección</dt><dd>${esc(a.direccion)}</dd>` : ""}${a.motivo_estado ? `<dt>Nota</dt><dd>${esc(a.motivo_estado)}</dd>` : ""}</dl>`;
  }

  function controlesDe(a) {
    return `<div class="barra-avance"><i style="width:${a.avance.porcentaje}%"></i></div>
      <ul class="controles">${a.controles.map((c) => `<li><button type="button" class="${c.estado === "hecho" ? "hecho" : ""}" data-id="${a.id}" data-control="${c.clave}" data-nuevo="${c.estado === "hecho" ? "pendiente" : "hecho"}">
        <span class="casilla">${c.estado === "hecho" ? "✓" : ""}</span><span class="texto">${esc(c.etiqueta)}${c.obligatorio ? "" : " (opcional)"}</span>
        ${c.marcado_en ? `<small>${new Date(c.marcado_en).toLocaleTimeString("es-NI", { timeStyle: "short" })}</small>` : ""}</button></li>`).join("")}</ul>`;
  }

  function botonesDe(a) {
    const b = (a_, texto, clase = "") => `<button type="button" class="${clase}" data-id="${a.id}" data-a="${a_}">${texto}</button>`;
    switch (a.estado) {
      case "asignado": return `<div class="fila">${b("en_revision", "Empezar revisión", "primario")}${b("en_curso", "Empezar trabajo")}</div>`;
      case "en_revision": return `<div class="fila">${b("en_curso", "Empezar trabajo", "primario")}${b("no_viable", "No es viable", "peligro")}</div>`;
      case "en_curso": return `<div class="fila">${b("pausado", "Pausar")}${b("terminado", "Terminar", "ok")}</div>`;
      case "pausado": return `<div class="fila">${b("en_curso", "Reanudar", "primario")}</div>`;
      default: return "";
    }
  }

  function burbujas(mensajes) {
    if (!mensajes.length) return '<span class="nota">Todavía no hay mensajes.</span>';
    return mensajes.map((m) => `<div class="burbuja ${m.origen === "cuadrilla" ? "mia" : "otra"}"><span class="quien">${esc(m.de)} · ${new Date(m.enviado_en).toLocaleTimeString("es-NI", { timeStyle: "short" })}</span>${esc(m.texto).replace(/\n/g, "<br>")}</div>`).join("");
  }
  function chatDe(a) {
    if (st.chatId !== a.id) return `<button type="button" data-chat="${a.id}" class="chico">💬 Chat con planificación${a.sin_leer ? ` <span class="insignia">${a.sin_leer}</span>` : ""}</button>`;
    return `<div class="chat" id="chat-lista">${burbujas(st.mensajes)}</div>
      <form id="chat-form" class="chat-form" data-id="${a.id}"><input id="chat-texto" maxlength="1000" autocomplete="off" placeholder="Escribir a planificación…" aria-label="Mensaje"><button type="submit" class="primario">Enviar</button></form>
      <button type="button" data-chat-cerrar class="chico">Cerrar el chat</button>`;
  }

  async function cargarChat() {
    if (st.chatId == null) return;
    const id = st.chatId;
    let r;
    try { r = await pedir("GET", `/visor/planificacion/actividades/${id}/mensajes`); } catch (e) { return; }
    if (st.chatId !== id) return;
    st.mensajes = r.mensajes;
    const lista = $("chat-lista");
    if (lista) { const alFinal = lista.scrollHeight - lista.scrollTop - lista.clientHeight < 40 || !lista.dataset.listo; lista.innerHTML = burbujas(r.mensajes); lista.dataset.listo = "1"; if (alFinal) lista.scrollTop = lista.scrollHeight; }
    const todas = [...(st.datos.actual ? [st.datos.actual] : []), ...st.datos.cola];             // reading them marks them read: the badge goes away
    const a = todas.find((x) => x.id === id);
    if (a && a.sin_leer) { a.sin_leer = 0; pintar(); }
  }
  async function enviarChat(ev) {
    ev.preventDefault();
    const campo = $("chat-texto"), texto = campo.value.trim();
    if (!texto) return;
    aviso("");
    try { await pedir("POST", `/visor/planificacion/actividades/${ev.target.dataset.id}/mensajes`, { texto }); campo.value = ""; await cargarChat(); }
    catch (e) { aviso(textoError(e)); }
  }

  function tarjeta(a, actual) {
    const conControles = ["en_revision", "en_curso"].includes(a.estado);
    return `<article class="tarjeta ${actual ? "actual" : ""}"><div class="fila"><h3>${esc(a.cliente_nombre)}</h3><span class="etiqueta" style="--c:${COLOR[a.estado]};flex:none">${esc(ETIQUETA[a.estado])}</span></div>
      <div class="tiempos"><div><b>${reloj(a, "espera")}</b>desde que se asignó</div><div><b>${reloj(a, "ejecucion")}</b>haciéndola</div></div>
      ${datosDe(a)}${conControles ? controlesDe(a) : ""}${botonesDe(a)}${chatDe(a)}</article>`;
  }

  function pintar() {
    const d = st.datos;
    $("nombre-cuadrilla").textContent = d.cuadrilla.nombre;
    $("nombre-empresa").textContent = d.cuadrilla.empresa;
    const partes = [];
    if (d.actual) partes.push('<h2 class="seccion">Ahora</h2>' + tarjeta(d.actual, true));
    if (d.cola.length) partes.push(`<h2 class="seccion">En cola (${d.cola.length})</h2>` + d.cola.map((a) => tarjeta(a, false)).join(""));
    const previo = $("chat-texto");                                         // what was being typed survives the redraw (a live notice redraws everything)
    const borrador = previo ? { v: previo.value, f: document.activeElement === previo, s: previo.selectionStart } : null;
    $("contenido").innerHTML = partes.join("") || '<p class="vacio">No tiene actividades asignadas.<br>Planificación le avisará cuando le asigne una.</p>';
    tic();
    const campo = $("chat-texto");
    if (campo && borrador) { campo.value = borrador.v; if (borrador.f) { campo.focus(); campo.setSelectionRange(borrador.s, borrador.s); } }
    const lista = $("chat-lista");
    if (lista) lista.scrollTop = lista.scrollHeight;
  }

  // ------------------------------------------------------------------ acciones
  async function cambiarEstado(id, a) {
    let motivo = "";
    if (["pausado", "no_viable"].includes(a)) {
      motivo = window.prompt(a === "pausado" ? "¿Por qué la pausa?" : "¿Por qué no es viable?") || "";
      if (!motivo.trim()) return;
    }
    aviso("");
    try { await pedir("POST", `/visor/planificacion/actividades/${id}/estado`, { a, motivo }); await cargar(); }
    catch (e) { aviso(textoError(e)); }
  }

  async function marcar(id, clave, nuevo) {
    aviso("");
    const p = nuevo === "hecho" ? await posicion(4000) : null;
    try { await pedir("POST", `/visor/planificacion/actividades/${id}/control`, { clave, estado: nuevo, ...(p ? { lat: p.lat, lon: p.lon } : {}) }); await cargar(); }
    catch (e) { aviso(textoError(e)); }
  }


  // ------------------------------------------------------------------ avisos en vivo (Server-Sent Events con la clave en la cabecera)
  const envivo = { activo: false, espera: 1000, parar: false };
  function escucharAvisos(alCambiar, etiquetaVivo) {
    async function conectar() {
      if (envivo.parar) return;
      try {
        const r = await fetch("/visor/planificacion/eventos", { headers: { "X-Visor-Key": leer(CLAVE) || "", "ngrok-skip-browser-warning": "1" } });
        if (!r.ok || !r.body) throw new Error(String(r.status));
        envivo.activo = true; envivo.espera = 1000; etiquetaVivo(true);
        alCambiar();                                    // what changed while it was not connected (or before the server was listening)
        const lector = r.body.getReader(), texto = new TextDecoder();
        let resto = "";
        for (;;) {
          const { done, value } = await lector.read();
          if (done) break;
          resto += texto.decode(value, { stream: true });
          let i;
          while ((i = resto.indexOf("\n\n")) >= 0) {
            const bloque = resto.slice(0, i);
            resto = resto.slice(i + 2);
            if (bloque.split("\n").some((l) => l.startsWith("data:"))) alCambiar();
          }
        }
      } catch (e) { /* the connection dropped or was refused: try again */ }
      envivo.activo = false; etiquetaVivo(false);
      if (!envivo.parar) setTimeout(conectar, envivo.espera = Math.min(30000, envivo.espera * 2));
    }
    conectar();
  }

  // ------------------------------------------------------------------ arranque
  function mostrarClave(mensaje) {
    $("app").hidden = true; $("pantalla-clave").hidden = false;
    const e = $("clave-error"); e.hidden = !mensaje; e.textContent = mensaje || "";
  }

  let conectado = false;
  function entrar() {
    $("pantalla-clave").hidden = true; $("app").hidden = false;
    if (!conectado) {
      conectado = true;
      $("contenido").addEventListener("submit", (ev) => { if (ev.target.id === "chat-form") enviarChat(ev); });
      $("contenido").addEventListener("click", (ev) => {
        const abrir = ev.target.closest("[data-chat]");
        if (abrir) { st.chatId = Number(abrir.dataset.chat); st.mensajes = []; pintar(); cargarChat().then(() => { const c = $("chat-texto"); if (c) c.focus(); }); return; }
        if (ev.target.closest("[data-chat-cerrar]")) { st.chatId = null; pintar(); return; }
        const c = ev.target.closest("[data-control]");
        if (c) { marcar(Number(c.dataset.id), c.dataset.control, c.dataset.nuevo); return; }
        const b = ev.target.closest("[data-a]");
        if (b) cambiarEstado(Number(b.dataset.id), b.dataset.a);
      });
      $("salir").addEventListener("click", () => { guardar(CLAVE, null); clearInterval(st.temporizador); location.reload(); });
      setInterval(tic, 1000);
      setInterval(() => { if (!document.hidden) mandarUbicacion(); }, UBICACION_MS);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) { cargar(); mandarUbicacion(); } });
      if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js", { scope: "/cuadrilla/" }).catch(() => { /* works without it */ });
    }
    cargar(); mandarUbicacion();
    clearInterval(st.temporizador);
    st.temporizador = setInterval(() => { if (!document.hidden && (!envivo.activo || Date.now() - st.cargadoEn > 60000)) cargar(); }, REFRESCO_MS);        // with the live notices the periodic refresh is only for when they are down (and once a minute: a crew's position sends no notice)
    let espera = null;
    escucharAvisos(() => { clearTimeout(espera); espera = setTimeout(() => cargar(), 250); }, (vivo) => { $("vivo").textContent = vivo ? "● en vivo" : ""; });
  }

  $("clave-entrar").addEventListener("click", () => {
    const v = $("clave").value.trim();
    if (!v) { mostrarClave("Escriba la clave"); return; }
    guardar(CLAVE, v); entrar();
  });
  $("clave").addEventListener("keydown", (e) => { if (e.key === "Enter") $("clave-entrar").click(); });
  if (leer(CLAVE)) entrar(); else mostrarClave("");

  window.Cuadrilla = { _st: st };
})();
