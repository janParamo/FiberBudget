/* App de campo: pantallas y flujo (clave, registrar un punto con GPS o en el mapa, fotos, cola de envío sin señal, lista de la jornada, instalar). */
(function () {
  "use strict";
  const { api, ErrorApi, clave, ponerClave, uuid, comprimir } = window.CampoApi;
  const M = window.CampoMapa, Cola = window.CampoCola, Ayuda = window.CampoAyuda;
  const $ = (id) => document.getElementById(id);
  const ETIQUETA = { poste: "Poste", mufa: "Mufa", reserva: "Reserva", solitaria: "Solitaria", cliente: "Cliente", otro: "Otro" };
  const ESTADO = { pendiente: "Pendiente", aprobado: "Aprobado", rechazado: "Rechazado", editado: "Corregido", cola: "Sin enviar", error: "Con error" };
  const HOJAS = ["hoja-gps", "hoja-mira", "hoja-formulario", "hoja-lista", "hoja-editar", "hoja-menu", "hoja-ayuda", "hoja-cable", "hoja-cable-form"];
  const INTERVALO_REINTENTO_MS = 30000;
  const INTERVALO_UBICACION_MS = 20000;

  let cfg = { precision_max_m: 10, foto_max_bytes: 3145728, fotos_por_punto: 8 };
  let trazos = [], tr = null, trazando = false, grabando = false, quitarGrabacion = null;
  let jornada = null, puntos = [], cola = [], formulario = null, editando = null, quitarOyente = null, temporizador = null, enviando = false, arrancada = false;

  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const leer = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
  const guardar = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } };

  function aviso(texto, tipo) {
    const a = $("aviso");
    a.textContent = texto; a.className = tipo || ""; a.hidden = false;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { a.hidden = true; }, tipo === "malo" ? 7000 : 4000);
  }

  function hoja(id) {
    HOJAS.forEach((h) => { $(h).hidden = h !== id; });
    $("mira").hidden = id !== "hoja-mira";
    document.body.classList.toggle("ocupado", !!id);
  }
  function cerrarHojas() {
    hoja(null);
    if (quitarOyente) { quitarOyente(); quitarOyente = null; }
    formulario = null; editando = null;
  }

  /* ---------------------------------------------------------------- clave y arranque */

  function pantallaClave(mensaje) {
    $("app").hidden = true; $("pantalla-clave").hidden = false;
    const e = $("clave-error"); e.textContent = mensaje || ""; e.hidden = !mensaje;
    $("clave").focus();
  }

  /* Enters the app. With no connection it enters with what the last session saved (the points go to the queue and are sent later). */
  async function entrar() {
    let sinRed = false;
    try {
      cfg = { ...cfg, ...(await api.config()) };
      try { jornada = (await api.abrirJornada()).jornada; } catch (e) { if (!(e instanceof ErrorApi) || !e.sinConexion) throw e; sinRed = true; }
      guardar("campo.sesion", { clave: clave(), cfg, jornada });
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      const sesion = leer("campo.sesion");
      if (e.sinConexion && sesion && sesion.clave === clave()) { cfg = { ...cfg, ...sesion.cfg }; jornada = sesion.jornada; sinRed = true; }
      else {
        if (e.sinConexion) pantallaClave("Sin conexión con el servidor. La primera vez hace falta señal; revise e intente de nuevo.");
        else pantallaClave(e.estado === 401 ? "La clave no es válida." : e.message);
        return false;
      }
    }
    try { await Cola.ponerMeta("clave", clave()); } catch (e) { /* IndexedDB blocked: the points are then sent from the page only */ }
    $("pantalla-clave").hidden = true; $("app").hidden = false;
    if (!arrancada) { arrancada = true; M.iniciar("mapa"); M.vigilar(); window.CampoRed.iniciar(M.leaflet(), api, Cola); }
    pintarJornada(); pintarRed();
    if (sinRed) puntos = leer("campo.puntos") || []; else await cargarPuntos();
    await leerCola();
    pintarPuntos();
    pintarIos();
    window.Campo.lista = true;                                  // the start is over (tests wait for it)
    enviarCola(false);
    return true;
  }

  function pintarJornada() { $("jornada-nombre").textContent = jornada ? jornada.nombre : "Sin jornada abierta"; }
  function pintarRed() { $("persona").textContent = (cfg.persona || "") + (navigator.onLine === false ? " · sin conexión" : ""); }

  async function asegurarJornada() {
    if (jornada) return jornada;
    try { jornada = (await api.abrirJornada()).jornada; pintarJornada(); puntos = []; pintarPuntos(); }
    catch (e) { if (!(e instanceof ErrorApi) || !e.sinConexion) throw e; }          // offline: the point goes with no jornada and the server uses the open one
    return jornada;
  }

  /* ---------------------------------------------------------------- GPS */

  function claseGps(p) { return p <= cfg.precision_max_m ? "buena" : p <= cfg.precision_max_m * 2.5 ? "regular" : "mala"; }

  function pintarGps(u, error) {
    const c = $("gps-estado");
    if (error && !u) { c.textContent = "Sin GPS"; c.className = "chip mala"; return; }
    if (!u) { c.textContent = "GPS…"; c.className = "chip"; return; }
    c.textContent = `±${Math.round(u.precision_m)} m`; c.className = "chip " + claseGps(u.precision_m);
  }

  function registrar(tipo) {
    cerrarHojas();
    const u = M.ultima();
    if (u && u.precision_m <= cfg.precision_max_m) { abrirFormulario(tipo, { ...u, origen_coord: "gps" }); return; }
    hoja("hoja-gps");
    const pintar = (ub, error) => {
      if (ub && ub.precision_m <= cfg.precision_max_m) { cerrarHojas(); abrirFormulario(tipo, { ...ub, origen_coord: "gps" }); return; }
      $("gps-detalle").textContent = error || (ub ? `Precisión actual: ±${Math.round(ub.precision_m)} m (se necesita ±${cfg.precision_max_m} m o menos).` : "Buscando el GPS…");
    };
    pintar(u, null);
    quitarOyente = M.cuandoCambie(pintar);
    $("gps-usar").onclick = () => {
      const ub = M.ultima();
      if (!ub) { aviso("Todavía no hay ubicación del GPS", "malo"); return; }
      cerrarHojas(); abrirFormulario(tipo, { ...ub, origen_coord: "gps" });
    };
    $("gps-mapa").onclick = () => marcarEnMapa(tipo);
    $("gps-cancelar").onclick = cerrarHojas;
  }

  function marcarEnMapa(tipo) {
    cerrarHojas();
    hoja("hoja-mira");
    $("mira-ok").onclick = () => { const c = M.centro(); cerrarHojas(); abrirFormulario(tipo, { lat: c.lat, lon: c.lon, precision_m: null, altitud: null, origen_coord: "mapa" }); };
    $("mira-cancelar").onclick = cerrarHojas;
  }

  /* ---------------------------------------------------------------- formulario */

  function sugerirNombre(tipo) {
    const n = puntos.filter((p) => p.tipo === tipo).length + cola.filter((e) => e.punto && e.punto.tipo === tipo).length + 1;
    return `${ETIQUETA[tipo]} ${n}`;
  }

  function abrirFormulario(tipo, coord) {
    formulario = { tipo, coord, uuid: uuid(), fotos: [], guardando: false };
    $("form-titulo").textContent = ETIQUETA[tipo];
    $("form-coord").textContent = `${coord.lat.toFixed(6)}, ${coord.lon.toFixed(6)} · ${coord.origen_coord === "gps" ? `GPS ±${Math.round(coord.precision_m)} m` : "marcado en el mapa"}`;
    $("form-subtipo-poste").hidden = tipo !== "poste";
    $("form-subtipo-mufa").hidden = tipo !== "mufa";
    $("subtipo-poste").value = ""; $("mufa-capacidad").value = ""; $("mufa-formato").value = "";
    $("form-nombre").value = sugerirNombre(tipo); $("form-notas").value = "";
    const cerca = window.CampoRed.cercano(coord.lat, coord.lon, cfg.duplicado_m || 5);              // something of the network already there: say it before sending
    $("form-cerca").textContent = cerca ? `Ya hay algo aquí: ${cerca.n || cerca.t} (${cerca.t || "red"}) a ${cerca.distancia_m.toFixed(1)} m. ¿Es el mismo?` : "";
    $("form-cerca").hidden = !cerca;
    $("form-error").hidden = true; $("form-fotos").innerHTML = "";
    $("form-guardar").disabled = false;
    hoja("hoja-formulario");
  }

  function subtipoElegido() {
    const t = formulario.tipo;
    if (t === "poste") return $("subtipo-poste").value || null;
    if (t === "mufa") { const c = $("mufa-capacidad").value, f = $("mufa-formato").value; return c ? (f ? `${c} ${f}` : c) : null; }
    return null;
  }

  function pintarFotos() {
    const caja = $("form-fotos");
    caja.innerHTML = "";
    formulario.fotos.forEach((f, i) => {
      const fig = document.createElement("figure");
      fig.innerHTML = `<img alt="Foto ${i + 1}" src="${f.url}"><button type="button" aria-label="Quitar la foto ${i + 1}">✕</button>`;
      fig.querySelector("button").onclick = () => { URL.revokeObjectURL(f.url); formulario.fotos.splice(i, 1); pintarFotos(); };
      caja.appendChild(fig);
    });
  }

  async function agregarFotos(archivos) {
    for (const archivo of archivos) {
      if (!formulario) return;
      if (formulario.fotos.length >= cfg.fotos_por_punto) { aviso(`Un punto admite hasta ${cfg.fotos_por_punto} fotos`, "malo"); break; }
      try {
        const blob = await comprimir(archivo);
        if (blob.size > cfg.foto_max_bytes) { aviso("La foto sigue siendo muy pesada", "malo"); continue; }
        formulario.fotos.push({ blob, url: URL.createObjectURL(blob), uuid: uuid() });
      } catch (e) { aviso(e.message || "No se pudo leer la foto", "malo"); }
    }
    if (formulario) pintarFotos();
  }

  function errorFormulario(texto) { const e = $("form-error"); e.textContent = texto; e.hidden = !texto; }

  /* Saving never waits for the network: the point (with its photos) goes to the phone's queue and from there to the server. */
  async function guardarFormulario() {
    const f = formulario;
    if (!f || f.guardando) return;
    const nombre = $("form-nombre").value.trim();
    if (!nombre) { errorFormulario("Escriba el nombre del punto."); return; }
    f.guardando = true; errorFormulario("");
    await asegurarJornada();
    const entrada = {
      uuid: f.uuid, creado: Date.now(), puntoId: null, estado: "cola", error: null, intentos: 0,
      punto: { uuid_cliente: f.uuid, jornada_id: jornada ? jornada.id : null, tipo: f.tipo, subtipo: subtipoElegido(), nombre, notas: $("form-notas").value,
               lat: f.coord.lat, lon: f.coord.lon, precision_m: f.coord.precision_m, altitud: f.coord.altitud, origen_coord: f.coord.origen_coord,
               capturado_en: new Date(f.coord.hora || Date.now()).toISOString() },
      fotos: f.fotos.map((x) => ({ uuid: x.uuid, blob: x.blob, enviada: false })),
    };
    try { await Cola.agregar(entrada); }
    catch (e) { f.guardando = false; errorFormulario("No se pudo guardar en el teléfono (¿poco espacio o modo privado?). No cierre esta pantalla."); return; }
    f.fotos.forEach((x) => URL.revokeObjectURL(x.url));
    cerrarHojas();
    await leerCola();
    aviso(`«${nombre}» guardado en el teléfono`, "ok");
    registrarSync();
    enviarCola(false);
  }

  /* ---------------------------------------------------------------- cola de envío */

  async function leerCola() {
    try { cola = await Cola.listar(); } catch (e) { cola = []; }
    pintarBarra(); pintarPuntos();
  }

  function pintarBarra() {
    const n = cola.length, malos = cola.filter((e) => e.estado === "error").length;
    $("cola-barra").hidden = n === 0;
    $("cola-barra").classList.toggle("con-error", malos > 0);
    $("cola-texto").textContent = `${n} pendiente${n === 1 ? "" : "s"} de enviar${malos ? ` · ${malos} con error` : ""}`;
    $("cola-enviar").hidden = malos === n;
  }

  async function enviarCola(manual) {
    if (enviando) return;
    if (!cola.length) { try { cola = await Cola.listar(); } catch (e) { return; } if (!cola.length) return; }
    enviando = true;
    let r = null;
    try { r = await Cola.enviar(); }
    catch (e) { if (manual) aviso("No se pudo enviar: " + (e.message || e), "malo"); }
    finally { enviando = false; }
    await leerCola();
    if (!r) return;
    if (r.enviados.length) {
      await cargarPuntos();
      const dup = r.enviados.find((x) => x.duplicado);
      aviso(dup ? `Enviado. Posible duplicado: ${dup.duplicado.nombre} a ${dup.duplicado.distancia_m} m`
                : r.enviados.length === 1 ? `«${r.enviados[0].nombre}» enviado` : `${r.enviados.length} puntos enviados`, dup ? "malo" : "ok");
    }
    if (manual || !r.enviados.length) {
      if (r.detenido === "clave") aviso("La clave ya no es válida o perdió el rol de técnico. Pida ayuda al administrador.", "malo");
      else if (r.detenido === "limite") aviso("Demasiados envíos seguidos; se reintentará más tarde", "malo");
      else if (manual && r.detenido === "red") aviso("Sin conexión: los puntos siguen guardados y se enviarán al volver la señal");
      else if (manual && r.detenido === "servidor") aviso("El servidor no responde; se reintentará solo", "malo");
      else if (manual && r.con_error) aviso(`${r.con_error} punto(s) con error: ábralos en la lista para corregirlos`, "malo");
      else if (manual && !r.restantes) aviso("Todo enviado", "ok");
    }
  }

  /* The last GPS fix goes to the office (it keeps only the latest one per technician). Not when the app is closed, hidden, offline or the fix is old. */
  async function enviarUbicacion() {
    const u = M.ultima();
    if ($("app").hidden || document.hidden || !u || navigator.onLine === false || Date.now() - (u.hora || 0) > 120000) return false;
    try { await api.ubicacion(u); return true; } catch (e) { return false; }                // no signal or no role: nothing to do
  }

  function registrarSync() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then((reg) => reg.sync && reg.sync.register("campo-enviar")).catch(() => {});      // Android: sends even with the app closed
  }

  /* ---------------------------------------------------------------- lista y edición */

  async function cargarPuntos() {
    if (!jornada) { puntos = []; pintarPuntos(); return; }
    try {
      puntos = (await api.puntos(jornada.id)).puntos.filter((p) => !p.borrado);
      guardar("campo.puntos", puntos);
      trazos = (await api.trazos(jornada.id)).trazos.filter((t) => !t.borrado);
    } catch (e) { if (e instanceof ErrorApi) { if (!e.sinConexion) aviso(e.message, "malo"); } else throw e; return; }
    pintarPuntos();
  }

  function marcaCola(e) { return { lat: e.punto.lat, lon: e.punto.lon, nombre: e.punto.nombre, estado: e.estado === "error" ? "error" : "cola" }; }

  function pintarPuntos() {
    M.limpiarMarcas();
    puntos.forEach((p) => M.marcar(p, abrirEdicion));
    cola.filter((e) => e.punto).forEach((e) => M.marcar(marcaCola(e), () => abrirEdicionLocal(e)));
    trazos.forEach((t) => M.marcarLinea(t.puntos.map(([lat, lon]) => ({ lat, lon })), t.estado, () => abrirTrazo(t)));
    cola.filter((e) => e.trazo).forEach((e) => M.marcarLinea(e.trazo.puntos, e.estado === "error" ? "error" : "cola", () => abrirTrazoLocal(e)));
    $("contador").textContent = String(puntos.length + cola.length + trazos.length);
    const ul = $("lista-puntos");
    ul.innerHTML = "";
    $("lista-vacio").hidden = puntos.length + cola.length + trazos.length > 0;
    [...cola].filter((e) => e.trazo).reverse().forEach((e) => {
      const li = document.createElement("li"), t = e.trazo, clase = e.estado === "error" ? "error" : "cola";
      li.innerHTML = `<span class="estado ${clase}">${ESTADO[clase]}</span><span class="texto"><strong>Cable ${esc(CampoTrazo.texto(largoDe(t.puntos)))}</strong>
        <small>${esc(t.tipo_cable || "tipo ?")} · ${t.hilos ? t.hilos + " hilos" : "hilos ?"} · ${esc(t.modo)}</small>${e.error ? `<small class="error">${esc(e.error)}</small>` : ""}</span>
        <button type="button">Ver</button>`;
      li.querySelector("button").onclick = () => abrirTrazoLocal(e);
      ul.appendChild(li);
    });
    [...trazos].reverse().forEach((t) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="estado ${esc(t.estado)}">${esc(ESTADO[t.estado] || t.estado)}</span><span class="texto"><strong>Cable ${esc(CampoTrazo.texto(t.longitud_m || 0))}</strong>
        <small>${esc(t.tipo_cable || "tipo ?")} · ${t.hilos ? t.hilos + " hilos" : "hilos ?"} · ${esc(t.modo)}</small>${t.estado === "rechazado" && t.motivo_rechazo ? `<small class="error">Rechazado: ${esc(t.motivo_rechazo)}</small>` : ""}</span>
        <button type="button">Ver</button>`;
      li.querySelector("button").onclick = () => abrirTrazo(t);
      ul.appendChild(li);
    });
    [...cola].filter((e) => e.punto).reverse().forEach((e) => {
      const li = document.createElement("li"), p = e.punto, fotos = e.fotos.length, clase = e.estado === "error" ? "error" : "cola";
      li.innerHTML = `<span class="estado ${clase}">${ESTADO[clase]}</span>
        <span class="texto"><strong>${esc(p.nombre)}</strong><small>${esc(ETIQUETA[p.tipo])}${p.subtipo ? " · " + esc(p.subtipo) : ""}${fotos ? ` · ${fotos} foto${fotos > 1 ? "s" : ""}` : ""}</small>${e.error ? `<small class="error">${esc(e.error)}</small>` : ""}</span>
        <button type="button">Editar</button>`;
      li.querySelector("button").onclick = () => abrirEdicionLocal(e);
      ul.appendChild(li);
    });
    [...puntos].reverse().forEach((p) => {
      const li = document.createElement("li");
      const fotos = (p.fotos || []).length;
      li.innerHTML = `<span class="estado ${esc(p.estado)}">${esc(ESTADO[p.estado] || p.estado)}</span>
        <span class="texto"><strong>${esc(p.nombre)}</strong><small>${esc(ETIQUETA[p.tipo])}${p.subtipo ? " · " + esc(p.subtipo) : ""}${p.precision_m != null ? ` · ±${Math.round(p.precision_m)} m` : " · mapa"}${fotos ? ` · ${fotos} foto${fotos > 1 ? "s" : ""}` : ""}</small>${p.estado === "rechazado" && p.motivo_rechazo ? `<small class="error">Rechazado: ${esc(p.motivo_rechazo)}</small>` : ""}</span>
        <button type="button">${p.estado === "pendiente" ? "Editar" : "Ver"}</button>`;
      li.querySelector("button").onclick = () => abrirEdicion(p);
      ul.appendChild(li);
    });
  }

  function abrirEdicion(p) {
    cerrarHojas();
    M.irA(p.lat, p.lon);
    editando = { local: false, p };
    const editable = p.estado === "pendiente";
    $("editar-titulo").textContent = `${ETIQUETA[p.tipo]} · ${ESTADO[p.estado] || p.estado}`;
    $("editar-nombre").value = p.nombre; $("editar-notas").value = p.notas || "";
    $("editar-nombre").disabled = $("editar-notas").disabled = !editable;
    $("editar-guardar").hidden = $("editar-borrar").hidden = !editable;
    $("editar-error").hidden = true;
    hoja("hoja-editar");
  }

  function abrirEdicionLocal(e) {
    cerrarHojas();
    M.irA(e.punto.lat, e.punto.lon);
    editando = { local: true, e };
    $("editar-titulo").textContent = `${ETIQUETA[e.punto.tipo]} · ${e.estado === "error" ? "con error" : "sin enviar"}`;
    $("editar-nombre").value = e.punto.nombre; $("editar-notas").value = e.punto.notas || "";
    $("editar-nombre").disabled = $("editar-notas").disabled = false;
    $("editar-guardar").hidden = $("editar-borrar").hidden = false;
    errorEdicion(e.error || "");
    hoja("hoja-editar");
  }

  function errorEdicion(texto) { const e = $("editar-error"); e.textContent = texto; e.hidden = !texto; }

  async function guardarEdicion() {
    if (!editando) return;
    const nombre = $("editar-nombre").value, notas = $("editar-notas").value;
    if (editando.local) {                                       // still in the phone: change it there and send it again
      const e = (await Cola.obtener(editando.e.uuid)) || editando.e;
      e.punto.nombre = nombre; e.punto.notas = notas; e.estado = "cola"; e.error = null;
      await Cola.actualizar(e);
      cerrarHojas(); await leerCola(); enviarCola(false);
      return;
    }
    const p = editando.p;
    try { await api.editarPunto(p.id, p.version, { nombre, notas }); }
    catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      errorEdicion(e.sinConexion ? "Sin conexión: no se puede cambiar un punto ya enviado." : e.estado === 409 ? "Alguien cambió este punto; ciérrelo y ábralo otra vez." : (e.errores && Object.values(e.errores)[0]) || e.message);
      return;
    }
    cerrarHojas(); aviso("Punto actualizado", "ok"); await cargarPuntos();
  }

  async function borrarEdicion() {
    if (!editando || !window.confirm(`¿Borrar «${editando.local ? editando.e.punto.nombre : editando.p.nombre}»?`)) return;
    if (editando.local) { await Cola.quitar(editando.e.uuid); cerrarHojas(); await leerCola(); aviso("Punto borrado", "ok"); return; }
    try { await api.borrarPunto(editando.p.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; errorEdicion(e.sinConexion ? "Sin conexión: no se puede borrar un punto ya enviado." : e.message); return; }
    cerrarHojas(); aviso("Punto borrado", "ok"); await cargarPuntos();
  }

  /* ---------------------------------------------------------------- trazar un cable */

  const largoDe = (pts) => { const t = window.CampoTrazo.crear(); pts.forEach((p) => t.agregar(p.lat, p.lon)); return t.longitud(); };

  function pintarTrazoUI() {
    M.pintarTrazo(tr.vertices());
    const n = tr.n();
    $("cable-info").textContent = n ? `${n} punto${n === 1 ? "" : "s"} · ${CampoTrazo.texto(tr.longitud())}${grabando ? " · grabando el recorrido…" : ""}`
      : "Toque los postes o puntos del mapa en orden, use «Mi ubicación» o grabe el recorrido caminando.";
    $("cable-terminar").disabled = !tr.listo();
    $("cable-grabar").textContent = grabando ? "■ Detener grabación" : "● Grabar recorrido";
  }

  /* A tap near a pole of the reference network or a field point sticks to it (the cable follows it): within ~22 px. */
  function pegado(lat, lon) {
    const metros = 22 * (156543.03 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, M.leaflet().getZoom());
    const r = window.CampoRed.cercano(lat, lon, metros);
    if (r) return { lat: r.lat, lon: r.lon, poste: { nombre: r.n || r.t } };
    const propio = [...puntos, ...cola.filter((e) => e.punto).map((e) => e.punto)].map((p) => ({ lat: p.lat, lon: p.lon, nombre: p.nombre, d: CampoTrazo.distanciaM({ lat, lon }, p) }))
      .filter((p) => p.d <= metros).sort((a, b) => a.d - b.d)[0];
    return propio ? { lat: propio.lat, lon: propio.lon, poste: { nombre: propio.nombre } } : null;
  }

  function pararGrabacion() { grabando = false; if (quitarGrabacion) { quitarGrabacion(); quitarGrabacion = null; } }

  function salirDeTrazo() {
    pararGrabacion();
    trazando = false; tr = null;
    M.cuandoToque(null); window.CampoRed.alTocar(null); M.limpiarTrazo();
    cerrarHojas();
  }

  function iniciarTrazo() {
    cerrarHojas();
    tr = window.CampoTrazo.crear(); trazando = true; grabando = false;
    hoja("hoja-cable"); $("mira").hidden = false;
    M.cuandoToque((e) => { const s = pegado(e.latlng.lat, e.latlng.lng); tr.agregar(s ? s.lat : e.latlng.lat, s ? s.lon : e.latlng.lng, s ? { poste: s.poste } : null); pintarTrazoUI(); });
    window.CampoRed.alTocar((p) => { tr.agregar(p.lat, p.lon, { poste: { nombre: p.n || p.t } }); pintarTrazoUI(); });
    pintarTrazoUI();
  }

  /* Opening another sheet in the middle of a cable would lose it: ask first. */
  function liberarTrazo() {
    if (!trazando) return true;
    if (tr.n() >= 2 && !window.confirm("Hay un cable sin terminar. ¿Descartarlo?")) return false;
    salirDeTrazo();
    return true;
  }

  function conectarTrazo() {
    $("btn-cable").onclick = iniciarTrazo;
    $("cable-ubicacion").onclick = () => {
      const u = M.ultima();
      if (!u) { aviso("Todavía no hay ubicación del GPS", "malo"); return; }
      tr.agregar(u.lat, u.lon); pintarTrazoUI();
      if (u.precision_m > cfg.precision_max_m) aviso(`GPS de ±${Math.round(u.precision_m)} m: ese punto es poco preciso`);
    };
    $("cable-mira").onclick = () => { const c = M.centro(); tr.agregar(c.lat, c.lon); pintarTrazoUI(); };
    $("cable-deshacer").onclick = () => { tr.deshacer(); pintarTrazoUI(); };
    $("cable-grabar").onclick = () => {
      if (grabando) { pararGrabacion(); pintarTrazoUI(); return; }
      grabando = true;
      tr.fijar(M.ultima());
      quitarGrabacion = M.cuandoCambie((u) => { if (u && tr.fijar(u)) pintarTrazoUI(); });
      pintarTrazoUI();
    };
    $("cable-cancelar").onclick = () => { if (tr.n() >= 3 && !window.confirm("¿Descartar el cable?")) return; salirDeTrazo(); };
    $("cable-terminar").onclick = () => {
      pararGrabacion(); pintarTrazoUI();
      $("cable-resumen").textContent = `${tr.n()} puntos · ${CampoTrazo.texto(tr.longitud())} · ${tr.modo()}`;
      $("cable-error").hidden = true;
      hoja("hoja-cable-form"); $("mira").hidden = true;
    };
    $("cable-volver").onclick = () => { hoja("hoja-cable"); $("mira").hidden = false; };
    $("cable-guardar").onclick = async () => {
      const hilos = $("cable-hilos").value;
      const entrada = {
        uuid: uuid(), creado: Date.now(), estado: "cola", error: null, intentos: 0, fotos: [],
        trazo: { uuid_cliente: uuid(), jornada_id: jornada ? jornada.id : null, modo: tr.modo(), tipo_cable: $("cable-tipo").value || null, hilos: hilos ? Number(hilos) : null,
                 notas: $("cable-notas").value, puntos: tr.puntos(), postes: tr.postes(), capturado_en: new Date().toISOString() },
      };
      entrada.trazo.uuid_cliente = entrada.uuid;
      try { await Cola.agregar(entrada); }
      catch (e) { const er = $("cable-error"); er.textContent = "No se pudo guardar en el teléfono. No cierre esta pantalla."; er.hidden = false; return; }
      const largo = CampoTrazo.texto(tr.longitud());
      salirDeTrazo();
      $("cable-tipo").value = ""; $("cable-hilos").value = ""; $("cable-notas").value = "";
      await leerCola();
      aviso(`Cable de ${largo} guardado en el teléfono`, "ok");
      registrarSync();
      enviarCola(false);
    };
    $("btn-red").onclick = () => { const v = window.CampoRed.alternar(); $("btn-red").setAttribute("aria-pressed", String(v)); aviso(v ? "Red de referencia visible" : "Red de referencia oculta"); };
  }

  function verTrazo(pts) { cerrarHojas(); M.ajustarA(pts); }

  async function abrirTrazo(t) {
    verTrazo(t.puntos.map(([lat, lon]) => ({ lat, lon })));
    if (t.estado !== "pendiente") { aviso(`Cable ${ESTADO[t.estado] || t.estado}${t.motivo_rechazo ? ": " + t.motivo_rechazo : ""}`); return; }
    if (!window.confirm(`Cable de ${CampoTrazo.texto(t.longitud_m || 0)} pendiente de revisión. ¿Borrarlo?`)) return;
    try { await api.borrarTrazo(t.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; aviso(e.sinConexion ? "Sin conexión: no se puede borrar un cable ya enviado" : e.message, "malo"); return; }
    aviso("Cable borrado", "ok"); await cargarPuntos();
  }

  async function abrirTrazoLocal(e) {
    verTrazo(e.trazo.puntos);
    if (!window.confirm(`Cable de ${CampoTrazo.texto(largoDe(e.trazo.puntos))} sin enviar${e.error ? " (" + e.error + ")" : ""}. ¿Borrarlo?`)) return;
    await Cola.quitar(e.uuid); await leerCola(); aviso("Cable borrado", "ok");
  }

  /* ---------------------------------------------------------------- menú, instalar y avisos */

  async function cerrarJornada() {
    if (!jornada) { aviso("No hay jornada abierta"); return; }
    if (cola.length && !window.confirm(`Hay ${cola.length} punto(s) sin enviar. ¿Cerrar la jornada de todos modos? Se enviarán igual cuando haya señal.`)) return;
    if (!cola.length && !window.confirm("¿Cerrar la jornada? Los puntos enviados quedan para revisión.")) return;
    try { await api.cerrarJornada(jornada.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; aviso(e.sinConexion ? "Sin conexión: cierre la jornada cuando tenga señal" : e.message, "malo"); return; }
    jornada = null; puntos = []; guardar("campo.sesion", { clave: clave(), cfg, jornada: null }); guardar("campo.puntos", []);
    cerrarHojas(); pintarJornada(); pintarPuntos(); aviso("Jornada cerrada", "ok");
  }

  function pintarIos() {
    let cerrado = false;
    try { cerrado = sessionStorage.getItem("campo.ios-cerrado") === "1"; } catch (e) { /* private mode */ }
    $("ios-barra").hidden = !(Ayuda.estado().avisarSinInstalar && !cerrado);
  }

  function pintarInstalar() { $("menu-instalar").hidden = !Ayuda.estado().puedeInstalar; pintarIos(); }

  function abrirAyuda() { cerrarHojas(); $("ayuda-contenido").innerHTML = Ayuda.html(); hoja("hoja-ayuda"); }

  /* ---------------------------------------------------------------- enlaces */

  function conectar() {
    $("clave-entrar").onclick = async () => {
      const v = $("clave").value.trim();
      if (!v) { pantallaClave("Escriba la clave."); return; }
      ponerClave(v);
      $("clave-entrar").disabled = true;
      await entrar();
      $("clave-entrar").disabled = false;
    };
    $("clave").addEventListener("keydown", (e) => { if (e.key === "Enter") $("clave-entrar").click(); });
    document.querySelectorAll("#acciones [data-tipo]").forEach((b) => { b.onclick = () => registrar(b.dataset.tipo); });
    $("btn-centrar").onclick = () => M.centrar();
    $("btn-capa").onclick = () => aviso(M.alternarCapa() === "satelite" ? "Mapa satelital" : "Mapa de calles");
    conectarTrazo();
    $("btn-lista").onclick = () => { if (!liberarTrazo()) return; cerrarHojas(); hoja("hoja-lista"); };
    $("lista-cerrar").onclick = cerrarHojas;
    $("btn-menu").onclick = () => { if (!liberarTrazo()) return; cerrarHojas(); pintarInstalar(); hoja("hoja-menu"); };
    $("menu-volver").onclick = cerrarHojas;
    $("menu-cerrar-jornada").onclick = cerrarJornada;
    $("menu-instalar").onclick = async () => { if (await Ayuda.instalar()) aviso("App instalada", "ok"); cerrarHojas(); };
    $("menu-ayuda").onclick = abrirAyuda;
    $("ayuda-cerrar").onclick = cerrarHojas;
    $("ios-como").onclick = abrirAyuda;
    $("ios-cerrar").onclick = () => { try { sessionStorage.setItem("campo.ios-cerrado", "1"); } catch (e) { /* ignore */ } pintarIos(); };
    $("cola-enviar").onclick = () => enviarCola(true);
    $("menu-salir").onclick = () => {
      if (cola.length) { aviso("Primero envíe los puntos pendientes (o bórrelos): están a nombre de esta clave", "malo"); return; }
      ponerClave(null); guardar("campo.sesion", null); guardar("campo.puntos", null); Cola.ponerMeta("clave", null).finally(() => location.reload());
    };
    $("form-foto").onchange = async (e) => { const a = [...e.target.files]; e.target.value = ""; if (formulario) await agregarFotos(a); };
    $("form-guardar").onclick = guardarFormulario;
    $("form-cancelar").onclick = cerrarHojas;
    $("editar-guardar").onclick = guardarEdicion;
    $("editar-borrar").onclick = borrarEdicion;
    $("editar-cerrar").onclick = cerrarHojas;
    M.cuandoCambie(pintarGps);
    Ayuda.cuandoCambie(pintarInstalar);

    // every chance to send what is waiting: coming back online, coming back to the app, and a timer while there is something in the queue
    window.addEventListener("online", () => { pintarRed(); enviarCola(false); });
    window.addEventListener("offline", pintarRed);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("app").hidden) { M.ajustar(); M.vigilar(); pintarRed(); enviarCola(false); } });
    setInterval(() => { if (!$("app").hidden && cola.length && navigator.onLine !== false) enviarCola(false); }, INTERVALO_REINTENTO_MS);
    // the position goes to the office every 20 s while the app is open (only the last one is kept there): so the supervisor sees where each technician is
    setInterval(enviarUbicacion, INTERVALO_UBICACION_MS);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(() => {});
      navigator.serviceWorker.addEventListener("message", (e) => { if (e.data && e.data.tipo === "cola") { leerCola(); if (e.data.resumen && e.data.resumen.enviados.length) cargarPuntos(); } });
    }
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});        // asks the browser not to erase the queue
  }

  conectar();
  $("aviso-http").hidden = Ayuda.contextoSeguro();
  if (clave()) entrar().then((ok) => { if (!ok) $("clave").value = ""; }); else pantallaClave("");
  window.Campo = { lista: false, enviarUbicacion, iniciarTrazo, registrar, cargarPuntos, enviarCola, leerCola, estado: () => ({ jornada, puntos, cola, cfg }) };
})();
