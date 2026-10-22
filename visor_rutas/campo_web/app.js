/* App de campo: el arranque (clave, jornada, mapa), la cola de envío sin señal, la ubicación en vivo y el enlace de todas las pantallas. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const { api, ErrorApi, clave, ponerClave } = window.CampoApi;
  const M = window.CampoMapa, Cola = window.CampoCola, Ayuda = window.CampoAyuda;
  const $ = (id) => document.getElementById(id);
  const E = C.estado;
  const INTERVALO_REINTENTO_MS = 30000;
  const INTERVALO_UBICACION_MS = 20000;

  let enviando = false, arrancada = false;
  const aviso = (t, tipo) => C.aviso(t, tipo);

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
      E.cfg = { ...E.cfg, ...(await api.config()) };
      try { E.jornada = (await api.abrirJornada()).jornada; } catch (e) { if (!(e instanceof ErrorApi) || !e.sinConexion) throw e; sinRed = true; }
      C.guardar("campo.sesion", { clave: clave(), cfg: E.cfg, jornada: E.jornada });
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      const sesion = C.leer("campo.sesion");
      if (e.sinConexion && sesion && sesion.clave === clave()) { E.cfg = { ...E.cfg, ...sesion.cfg }; E.jornada = sesion.jornada; sinRed = true; }
      else {
        if (e.sinConexion) pantallaClave("Sin conexión con el servidor. La primera vez hace falta señal; revise e intente de nuevo.");
        else pantallaClave(e.estado === 401 ? "La clave no es válida." : e.message);
        return false;
      }
    }
    try { await Cola.ponerMeta("clave", clave()); } catch (e) { /* IndexedDB blocked: the points are then sent from the page only */ }
    $("pantalla-clave").hidden = true; $("app").hidden = false;
    if (!arrancada) {
      arrancada = true;
      M.iniciar("mapa", { zoom: C.ajustes.obtener("zoom"), capa: C.menu.capaGuardada() || undefined });
      M.vigilar();
      window.CampoRed.iniciar(M.leaflet(), api, Cola);
      if (!C.ajustes.obtener("red")) window.CampoRed.alternar();
      $("btn-red").setAttribute("aria-pressed", String(window.CampoRed.visible));
      C.captura.conectar(); C.editor.conectar(); C.lista.conectar(); C.menu.conectar();
      M.cuandoCambie(pintarGps);
      C.iconos.poner(document.body);
    }
    pintarJornada(); pintarPersona(); pintarGps(M.ultima(), M.error());
    if (sinRed) E.puntos = C.leer("campo.puntos") || []; else await cargarPuntos();
    await leerCola();
    C.captura.refrescarSiempre();
    pintarIos();
    C.listo = true;                                              // the start is over (tests wait for it)
    enviarCola(false);
    return true;
  }

  function pintarJornada() { $("jornada-nombre").textContent = E.jornada ? E.jornada.nombre : "Sin jornada abierta"; }
  function pintarPersona() { $("persona").textContent = (E.cfg.persona || "") + (navigator.onLine === false ? " · sin conexión" : ""); }

  async function asegurarJornada() {
    if (E.jornada) return E.jornada;
    try { E.jornada = (await api.abrirJornada()).jornada; pintarJornada(); E.puntos = []; E.trazos = []; C.lista.pintar(); }
    catch (e) { if (!(e instanceof ErrorApi) || !e.sinConexion) throw e; }          // offline: the point goes with no jornada and the server uses the open one
    return E.jornada;
  }

  async function nuevaJornada(nombre) {
    if (E.jornada) {
      if (!(await C.dialogo.confirmar("¿Cerrar la jornada actual?", "Lo enviado queda para revisión y se abre una jornada nueva.", [{ texto: "Cerrar y abrir", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) return;
      try { await api.cerrarJornada(E.jornada.id); }
      catch (e) { if (!(e instanceof ErrorApi)) throw e; aviso(e.sinConexion ? "Sin conexión: abra la jornada nueva cuando tenga señal" : e.message, "malo"); return; }
    }
    try { E.jornada = (await api.abrirJornada(nombre || undefined)).jornada; }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; E.jornada = null; aviso(e.sinConexion ? "Sin conexión: abra la jornada nueva cuando tenga señal" : e.message, "malo"); }
    E.puntos = []; E.trazos = []; C.guardar("campo.puntos", []); C.guardar("campo.sesion", { clave: clave(), cfg: E.cfg, jornada: E.jornada });
    pintarJornada(); C.lista.pintar();
    if (E.jornada) aviso(`Jornada «${E.jornada.nombre}» abierta`, "ok");
  }

  async function cerrarJornada() {
    if (!E.jornada) { aviso("No hay jornada abierta"); return; }
    const n = E.cola.length;
    if (!(await C.dialogo.confirmar("¿Cerrar la jornada?", n ? `Hay ${n} elemento(s) sin enviar; se enviarán igual cuando haya señal.` : "Lo enviado queda para revisión.", [{ texto: "Cerrar jornada", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) return;
    try { await api.cerrarJornada(E.jornada.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; aviso(e.sinConexion ? "Sin conexión: cierre la jornada cuando tenga señal" : e.message, "malo"); return; }
    E.jornada = null; E.puntos = []; E.trazos = []; C.guardar("campo.sesion", { clave: clave(), cfg: E.cfg, jornada: null }); C.guardar("campo.puntos", []);
    pintarJornada(); C.lista.pintar(); aviso("Jornada cerrada", "ok");
  }

  async function salir() {
    if (E.cola.length) { aviso("Primero envíe lo pendiente (o elimínelo): está a nombre de esta clave", "malo"); return; }
    if (!(await C.dialogo.confirmar("¿Cambiar de clave?", "Se cierra la sesión en este teléfono.", [{ texto: "Cambiar", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) return;
    ponerClave(null); C.guardar("campo.sesion", null); C.guardar("campo.puntos", null); Cola.ponerMeta("clave", null).finally(() => location.reload());
  }

  /* ---------------------------------------------------------------- GPS */
  function claseGps(p) { return p <= E.cfg.precision_max_m ? "buena" : p <= E.cfg.precision_max_m * 2.5 ? "regular" : "mala"; }

  function pintarGps(u, error) {
    const c = $("gps-estado");
    if (error && !u) { c.textContent = "Sin GPS"; c.className = "chip mala"; return; }
    if (!u) { c.textContent = "GPS…"; c.className = "chip"; return; }
    c.textContent = `±${Math.round(u.precision_m)} m`; c.className = "chip " + claseGps(u.precision_m);
  }

  /* The last GPS fix goes to the office (it keeps only the latest one per technician). Not when the app is closed, hidden, offline or the fix is old. */
  async function enviarUbicacion() {
    const u = M.ultima();
    if ($("app").hidden || document.hidden || !u || navigator.onLine === false || Date.now() - (u.hora || 0) > 120000) return false;
    try { await api.ubicacion(u); return true; } catch (e) { return false; }                // no signal or no role: nothing to do
  }

  /* ---------------------------------------------------------------- cola de envío */
  async function leerCola() {
    try { E.cola = await Cola.listar(); } catch (e) { E.cola = []; }
    pintarBarra(); C.lista.pintar();
  }

  function pintarBarra() {
    const n = E.cola.length, malos = E.cola.filter((e) => e.estado === "error").length;
    $("cola-barra").hidden = n === 0;
    $("cola-barra").classList.toggle("con-error", malos > 0);
    $("cola-texto").textContent = `${n} pendiente${n === 1 ? "" : "s"} de enviar${malos ? ` · ${malos} con error` : ""}`;
    $("cola-enviar").hidden = malos === n;
  }

  async function enviarCola(manual) {
    if (enviando) return;
    if (!E.cola.length) { try { E.cola = await Cola.listar(); } catch (e) { return; } if (!E.cola.length) return; }
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
                : r.enviados.length === 1 ? `«${r.enviados[0].nombre}» enviado` : `${r.enviados.length} elementos enviados`, dup ? "malo" : "ok");
    }
    if (manual || !r.enviados.length) {
      if (r.detenido === "clave") aviso("La clave ya no es válida o perdió el rol de técnico. Pida ayuda al administrador.", "malo");
      else if (r.detenido === "limite") aviso("Demasiados envíos seguidos; se reintentará más tarde", "malo");
      else if (manual && r.detenido === "red") aviso("Sin conexión: todo sigue guardado y se enviará al volver la señal");
      else if (manual && r.detenido === "servidor") aviso("El servidor no responde; se reintentará solo", "malo");
      else if (manual && r.con_error) aviso(`${r.con_error} con error: ábralos en la lista para corregirlos`, "malo");
      else if (manual && !r.restantes) aviso("Todo enviado", "ok");
    }
  }

  function registrarSync() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then((reg) => reg.sync && reg.sync.register("campo-enviar")).catch(() => {});      // Android: sends even with the app closed
  }

  async function cargarPuntos() {
    if (!E.jornada) { E.puntos = []; E.trazos = []; C.lista.pintar(); return; }
    try {
      E.puntos = (await api.puntos(E.jornada.id)).puntos.filter((p) => !p.borrado);
      C.guardar("campo.puntos", E.puntos);
      E.trazos = (await api.trazos(E.jornada.id)).trazos.filter((t) => !t.borrado);
    } catch (e) { if (e instanceof ErrorApi) { if (!e.sinConexion) aviso(e.message, "malo"); } else throw e; return; }
    C.lista.pintar();
  }

  /* ---------------------------------------------------------------- avisos de iPhone e instalación */
  function pintarIos() {
    let cerrado = false;
    try { cerrado = sessionStorage.getItem("campo.ios-cerrado") === "1"; } catch (e) { /* private mode */ }
    $("ios-barra").hidden = !(Ayuda.estado().avisarSinInstalar && !cerrado);
    $("m-instalar").hidden = !Ayuda.estado().puedeInstalar;
  }

  /* ---------------------------------------------------------------- enlaces */
  function conectar() {
    C.ajustes.aplicar();
    C.iconos.poner(document.body);
    $("clave-entrar").onclick = async () => {
      const v = $("clave").value.trim();
      if (!v) { pantallaClave("Escriba la clave."); return; }
      ponerClave(v);
      $("clave-entrar").disabled = true;
      await entrar();
      $("clave-entrar").disabled = false;
    };
    $("clave").addEventListener("keydown", (e) => { if (e.key === "Enter") $("clave-entrar").click(); });
    $("b-ubicacion").onclick = () => M.centrar();
    $("ios-cerrar").onclick = () => { try { sessionStorage.setItem("campo.ios-cerrado", "1"); } catch (e) { /* ignore */ } pintarIos(); };
    $("cola-enviar").onclick = () => enviarCola(true);
    Ayuda.cuandoCambie(pintarIos);

    // every chance to send what is waiting: coming back online, coming back to the app, and a timer while there is something in the queue
    window.addEventListener("online", () => { pintarPersona(); enviarCola(false); });
    window.addEventListener("offline", pintarPersona);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("app").hidden) { M.ajustar(); M.vigilar(); pintarPersona(); enviarCola(false); } });
    setInterval(() => { if (!$("app").hidden && E.cola.length && navigator.onLine !== false) enviarCola(false); }, INTERVALO_REINTENTO_MS);
    // the position goes to the office every 20 s while the app is open (only the last one is kept there): so the supervisor sees where each technician is
    setInterval(enviarUbicacion, INTERVALO_UBICACION_MS);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(() => {});
      navigator.serviceWorker.addEventListener("message", (e) => { if (e.data && e.data.tipo === "cola") { leerCola(); if (e.data.resumen && e.data.resumen.enviados.length) cargarPuntos(); } });
    }
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});        // asks the browser not to erase the queue
  }

  C.app = { entrar, asegurarJornada, nuevaJornada, cerrarJornada, salir, leerCola, enviarCola, cargarPuntos, registrarSync, enviarUbicacion };
  Object.assign(C, { listo: false, enviarUbicacion, cargarPuntos, enviarCola, leerCola });
  conectar();
  $("aviso-http").hidden = Ayuda.contextoSeguro();
  if (clave()) entrar().then((ok) => { if (!ok) $("clave").value = ""; }); else pantallaClave("");
})();
