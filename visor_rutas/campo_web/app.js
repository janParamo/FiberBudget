/* App de campo: pantallas y flujo (clave, registrar un punto con GPS o en el mapa, fotos, enviar, lista de la jornada). */
(function () {
  "use strict";
  const { api, ErrorApi, clave, ponerClave, uuid, comprimir } = window.CampoApi;
  const M = window.CampoMapa;
  const $ = (id) => document.getElementById(id);
  const ETIQUETA = { poste: "Poste", mufa: "Mufa", reserva: "Reserva", solitaria: "Solitaria", cliente: "Cliente", otro: "Otro" };
  const ESTADO = { pendiente: "Pendiente", aprobado: "Aprobado", rechazado: "Rechazado", editado: "Corregido" };
  const HOJAS = ["hoja-gps", "hoja-mira", "hoja-formulario", "hoja-lista", "hoja-editar", "hoja-menu"];

  let cfg = { precision_max_m: 10, foto_max_bytes: 3145728, fotos_por_punto: 8 };
  let jornada = null, puntos = [], formulario = null, editando = null, quitarOyente = null, temporizador = null;

  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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

  async function entrar() {
    try {
      const c = await api.config();
      cfg = { ...cfg, ...c };
      jornada = (await api.abrirJornada()).jornada;
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      if (e.sinConexion) { pantallaClave("Sin conexión con el servidor. Revise la señal e intente de nuevo."); return false; }
      pantallaClave(e.estado === 403 ? e.message : e.estado === 401 ? "La clave no es válida." : e.message);
      return false;
    }
    $("pantalla-clave").hidden = true; $("app").hidden = false;
    $("persona").textContent = cfg.persona || "";
    M.iniciar("mapa"); M.vigilar();
    pintarJornada();
    await cargarPuntos();
    return true;
  }

  function pintarJornada() { $("jornada-nombre").textContent = jornada ? jornada.nombre : "Sin jornada abierta"; }

  async function asegurarJornada() {
    if (!jornada) { jornada = (await api.abrirJornada()).jornada; pintarJornada(); puntos = []; pintarPuntos(); }
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
    const n = puntos.filter((p) => p.tipo === tipo).length + 1;
    return `${ETIQUETA[tipo]} ${n}`;
  }

  function abrirFormulario(tipo, coord) {
    formulario = { tipo, coord, uuid: uuid(), fotos: [], puntoId: null, enviando: false };
    $("form-titulo").textContent = ETIQUETA[tipo];
    $("form-coord").textContent = `${coord.lat.toFixed(6)}, ${coord.lon.toFixed(6)} · ${coord.origen_coord === "gps" ? `GPS ±${Math.round(coord.precision_m)} m` : "marcado en el mapa"}`;
    $("form-subtipo-poste").hidden = tipo !== "poste";
    $("form-subtipo-mufa").hidden = tipo !== "mufa";
    $("subtipo-poste").value = ""; $("mufa-capacidad").value = ""; $("mufa-formato").value = "";
    $("form-nombre").value = sugerirNombre(tipo); $("form-notas").value = "";
    $("form-error").hidden = true; $("form-fotos").innerHTML = "";
    $("form-guardar").disabled = false; $("form-guardar").textContent = "Guardar y enviar";
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
      if (formulario.fotos.length >= cfg.fotos_por_punto) { aviso(`Un punto admite hasta ${cfg.fotos_por_punto} fotos`, "malo"); break; }
      try {
        const blob = await comprimir(archivo);
        if (blob.size > cfg.foto_max_bytes) { aviso("La foto sigue siendo muy pesada", "malo"); continue; }
        formulario.fotos.push({ blob, url: URL.createObjectURL(blob), uuid: uuid(), enviada: false });
      } catch (e) { aviso(e.message || "No se pudo leer la foto", "malo"); }
    }
    pintarFotos();
  }

  function errorFormulario(texto) { const e = $("form-error"); e.textContent = texto; e.hidden = !texto; }

  async function guardarFormulario() {
    const f = formulario;
    if (!f || f.enviando) return;
    f.enviando = true; errorFormulario("");
    const boton = $("form-guardar"); boton.disabled = true; boton.textContent = "Enviando…";
    let duplicado = null;
    try {
      if (!f.puntoId) {
        await asegurarJornada();
        const r = (await api.enviarPuntos([{
          uuid_cliente: f.uuid, jornada_id: jornada.id, tipo: f.tipo, subtipo: subtipoElegido(), nombre: $("form-nombre").value, notas: $("form-notas").value,
          lat: f.coord.lat, lon: f.coord.lon, precision_m: f.coord.precision_m, altitud: f.coord.altitud, origen_coord: f.coord.origen_coord,
          capturado_en: new Date(f.coord.hora || Date.now()).toISOString(),
        }])).resultados[0];
        if (!r.ok) { errorFormulario(r.error || "No se pudo guardar el punto"); return; }
        f.puntoId = r.punto.id; duplicado = r.duplicado;
      }
      for (const foto of f.fotos.filter((x) => !x.enviada)) { await api.subirFoto(f.puntoId, foto.blob, foto.uuid); foto.enviada = true; }
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      errorFormulario(f.puntoId
        ? `El punto ya se guardó; faltan fotos por enviar (${e.message}). Toque «Guardar y enviar» para reintentar.`
        : (e.sinConexion ? "Sin conexión. Toque «Guardar y enviar» cuando tenga señal." : e.message));
      return;
    } finally {
      f.enviando = false; boton.disabled = false; boton.textContent = "Guardar y enviar";
    }
    const nombre = $("form-nombre").value;
    cerrarHojas();
    aviso(duplicado ? `Enviado. Posible duplicado: ${duplicado.nombre} a ${duplicado.distancia_m} m` : `«${nombre}» enviado`, duplicado ? "malo" : "ok");
    await cargarPuntos();
  }

  /* ---------------------------------------------------------------- lista y edición */

  async function cargarPuntos() {
    if (!jornada) { puntos = []; pintarPuntos(); return; }
    try { puntos = (await api.puntos(jornada.id)).puntos.filter((p) => !p.borrado); }
    catch (e) { if (e instanceof ErrorApi) aviso(e.message, "malo"); else throw e; return; }
    pintarPuntos();
  }

  function pintarPuntos() {
    M.limpiarMarcas();
    puntos.forEach((p) => M.marcar(p, abrirEdicion));
    $("contador").textContent = String(puntos.length);
    const ul = $("lista-puntos");
    ul.innerHTML = "";
    $("lista-vacio").hidden = puntos.length > 0;
    [...puntos].reverse().forEach((p) => {
      const li = document.createElement("li");
      const fotos = (p.fotos || []).length;
      li.innerHTML = `<span class="estado ${esc(p.estado)}">${esc(ESTADO[p.estado] || p.estado)}</span>
        <span class="texto"><strong>${esc(p.nombre)}</strong><small>${esc(ETIQUETA[p.tipo])}${p.subtipo ? " · " + esc(p.subtipo) : ""}${p.precision_m != null ? ` · ±${Math.round(p.precision_m)} m` : " · mapa"}${fotos ? ` · ${fotos} foto${fotos > 1 ? "s" : ""}` : ""}</small></span>
        <button type="button">${p.estado === "pendiente" ? "Editar" : "Ver"}</button>`;
      li.querySelector("button").onclick = () => abrirEdicion(p);
      ul.appendChild(li);
    });
  }

  function abrirEdicion(p) {
    cerrarHojas();
    M.irA(p.lat, p.lon);
    editando = p;
    const editable = p.estado === "pendiente";
    $("editar-titulo").textContent = `${ETIQUETA[p.tipo]} · ${ESTADO[p.estado] || p.estado}`;
    $("editar-nombre").value = p.nombre; $("editar-notas").value = p.notas || "";
    $("editar-nombre").disabled = $("editar-notas").disabled = !editable;
    $("editar-guardar").hidden = $("editar-borrar").hidden = !editable;
    $("editar-error").hidden = true;
    hoja("hoja-editar");
  }

  function errorEdicion(texto) { const e = $("editar-error"); e.textContent = texto; e.hidden = !texto; }

  async function guardarEdicion() {
    if (!editando) return;
    try {
      await api.editarPunto(editando.id, editando.version, { nombre: $("editar-nombre").value, notas: $("editar-notas").value });
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      errorEdicion(e.estado === 409 ? "Alguien cambió este punto; ciérrelo y ábralo otra vez." : (e.errores && Object.values(e.errores)[0]) || e.message);
      return;
    }
    cerrarHojas(); aviso("Punto actualizado", "ok"); await cargarPuntos();
  }

  async function borrarEdicion() {
    if (!editando || !window.confirm(`¿Borrar «${editando.nombre}»?`)) return;
    try { await api.borrarPunto(editando.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; errorEdicion(e.message); return; }
    cerrarHojas(); aviso("Punto borrado", "ok"); await cargarPuntos();
  }

  /* ---------------------------------------------------------------- menú */

  async function cerrarJornada() {
    if (!jornada) { aviso("No hay jornada abierta"); return; }
    if (!window.confirm("¿Cerrar la jornada? Los puntos enviados quedan para revisión.")) return;
    try { await api.cerrarJornada(jornada.id); }
    catch (e) { if (!(e instanceof ErrorApi)) throw e; aviso(e.message, "malo"); return; }
    jornada = null; puntos = []; cerrarHojas(); pintarJornada(); pintarPuntos(); aviso("Jornada cerrada", "ok");
  }

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
    $("btn-lista").onclick = () => { cerrarHojas(); hoja("hoja-lista"); };
    $("lista-cerrar").onclick = cerrarHojas;
    $("btn-menu").onclick = () => { cerrarHojas(); hoja("hoja-menu"); };
    $("menu-volver").onclick = cerrarHojas;
    $("menu-cerrar-jornada").onclick = cerrarJornada;
    $("menu-salir").onclick = () => { ponerClave(null); location.reload(); };
    $("form-foto").onchange = async (e) => { const a = [...e.target.files]; e.target.value = ""; if (formulario) await agregarFotos(a); };
    $("form-guardar").onclick = guardarFormulario;
    $("form-cancelar").onclick = () => { if (!formulario || !formulario.puntoId || window.confirm("El punto ya se guardó; ¿cerrar sin enviar las fotos que faltan?")) cerrarHojas(); };
    $("editar-guardar").onclick = guardarEdicion;
    $("editar-borrar").onclick = borrarEdicion;
    $("editar-cerrar").onclick = cerrarHojas;
    M.cuandoCambie(pintarGps);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("app").hidden) { M.ajustar(); M.vigilar(); } });
  }

  conectar();
  if (clave()) entrar().then((ok) => { if (!ok) $("clave").value = ""; }); else pantallaClave("");
  window.Campo = { registrar, cargarPuntos, estado: () => ({ jornada, puntos, cfg }) };
})();
