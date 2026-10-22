/* App de campo: ubicar un punto con la mira, trazar un cable punto por punto o grabar un recorrido caminando.
 *
 * Como en una app de marcadores: se mueve el mapa hasta que la mira queda sobre el lugar y se toca OK. En un cable, el punto elegido siempre está bajo la mira:
 * «+» agrega otro, «−» quita el elegido, «‹ ›» pasan de uno a otro y el disquete termina. Lo que cae sobre un poste o punto conocido se pega a él. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const $ = (id) => document.getElementById(id);
  const M = () => window.CampoMapa;
  const PX_PEGADO = 18;                               // a vertex that ends this close (in pixels) to a pole or a known point sticks to it
  const cap = { modo: null, tipo: "poste", tr: null, sel: 0, grabando: false, quitarGrab: null, quitarGps: null, enMapa: null, programatico: false, alAjustar: null };

  const activa = () => cap.modo;
  const ajustes = () => C.ajustes.obtener();

  function mostrarCoord() {
    const c = M().centro(), t = C.fmt.coord(c.lat, c.lon).replace("  ", "\n");
    $("cap-coord").textContent = /^[-0-9]/.test(t) ? `Lat: ${t.replace(", ", "\nLng: ")}` : t;
  }

  function pegadoEn(lat, lon) {
    const metros = PX_PEGADO * (156543.03 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, M().leaflet().getZoom());
    const r = window.CampoRed.cercano(lat, lon, metros);
    if (r) return { lat: r.lat, lon: r.lon, poste: { nombre: r.n || r.t } };
    const propio = [...C.estado.puntos, ...C.estado.cola.filter((e) => e.punto).map((e) => e.punto)]
      .map((p) => ({ lat: p.lat, lon: p.lon, nombre: p.nombre, d: window.CampoTrazo.distanciaM({ lat, lon }, p) })).filter((p) => p.d <= metros).sort((a, b) => a.d - b.d)[0];
    return propio ? { lat: propio.lat, lon: propio.lon, poste: { nombre: propio.nombre } } : null;
  }

  function centrarEn(lat, lon) {
    cap.programatico = true;
    try { M().leaflet().setView([lat, lon], M().leaflet().getZoom(), { animate: false }); } finally { cap.programatico = false; }
  }

  /* ---------------------------------------------------------------- pantalla de captura */
  function entrar(modo) {
    cap.modo = modo;
    document.body.classList.add("capturando");
    C.panel.cerrar(); C.tarjeta.ocultar();
    M().quitarTemporal();
    $("mira").hidden = ajustes().mira === "nunca";
    $("cap-coord").hidden = ajustes().coordenadas === "nunca";
    $("cap-banner").hidden = false;
    $("cap-tipos").hidden = modo !== "punto";
    $("cap-herramientas").hidden = modo !== "punto";
    $("cap-punto").hidden = modo !== "punto" && modo !== "ajuste";
    $("cap-cable").hidden = modo !== "cable";
    M().leaflet().on("move", alMover);
    M().leaflet().on("moveend", alTerminarDeMover);
    cap.quitarGps = M().cuandoCambie(() => pintarBanner());
    mostrarCoord();
  }

  function salir(conservarTrazo) {
    if (!cap.modo) return;
    const mapa = M().leaflet();
    mapa.off("move", alMover); mapa.off("moveend", alTerminarDeMover);
    if (cap.quitarGps) { cap.quitarGps(); cap.quitarGps = null; }
    cap.modo = null;
    document.body.classList.remove("capturando");
    ["cap-banner", "cap-tipos", "cap-herramientas", "cap-punto", "cap-cable"].forEach((id) => { $(id).hidden = true; });
    if (!conservarTrazo) M().limpiarTrazo();
    window.CampoRed.alTocar(null);
    C.captura.refrescarSiempre();
  }

  function pintarBanner() {
    if (!cap.modo) return;
    const u = M().ultima(), umbral = C.estado.cfg.precision_max_m;
    const gps = u ? (u.precision_m <= umbral ? `GPS ±${Math.round(u.precision_m)} m` : `<span class="mal">GPS ±${Math.round(u.precision_m)} m: poco preciso (se recomienda ±${umbral} m o menos)</span>`)
      : (M().error() ? `<span class="mal">${C.esc(M().error())}</span>` : "Buscando el GPS…");
    if (cap.modo === "punto") $("cap-banner").innerHTML = `Mueva el mapa hasta poner la mira donde va el punto y toque OK.<small>${gps} · o toque ◎ para ir a donde está usted</small>`;
    else if (cap.modo === "ajuste") $("cap-banner").innerHTML = `Mueva el mapa hasta la nueva posición y toque OK.<small>${gps}</small>`;
    else if (cap.modo === "cable") {
      const n = cap.tr.n();
      $("cap-banner").innerHTML = `Mueva el mapa para colocar el punto; toque + para agregar otro, ‹ › para cambiar de punto y el disquete para terminar.<small>Cable · punto ${cap.sel + 1} de ${n} · ${window.CampoTrazo.texto(cap.tr.longitud())}</small>`;
      $("cap-quitar").disabled = n < 2; $("cap-prev").disabled = cap.sel <= 0; $("cap-sig").disabled = cap.sel >= n - 1;
    }
  }

  function alMover() {
    mostrarCoord();
    if (cap.modo !== "cable" || cap.programatico) return;
    const c = M().centro();
    cap.tr.mover(cap.sel, c.lat, c.lon);
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  function alTerminarDeMover() {
    if (cap.modo !== "cable" || cap.programatico) return;
    const c = M().centro(), p = pegadoEn(c.lat, c.lon);
    if (p) { cap.tr.mover(cap.sel, p.lat, p.lon, { poste: p.poste }); centrarEn(p.lat, p.lon); }
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  /* ---------------------------------------------------------------- un punto */
  function coordDelCentro() {
    const c = M().centro(), u = M().ultima();
    if (u && window.CampoTrazo.distanciaM(c, u) <= 3) return { lat: u.lat, lon: u.lon, precision_m: u.precision_m, altitud: u.altitud, origen_coord: "gps", hora: u.hora };
    return { lat: c.lat, lon: c.lon, precision_m: null, altitud: null, origen_coord: "mapa", hora: Date.now() };
  }

  function elegirTipo(tipo) {
    cap.tipo = tipo;
    C.guardar("campo.ultimoTipo", tipo);
    document.querySelectorAll("#cap-tipos [data-cap-tipo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.capTipo === tipo)));
  }

  function iniciarPunto() {
    if (cap.modo || cap.grabando) { if (cap.grabando) C.aviso("Termine primero la grabación del recorrido"); return; }
    const u = M().ultima(), tipo = C.leer("campo.ultimoTipo") || "poste";
    if (ajustes().rapido && u && u.precision_m <= C.estado.cfg.precision_max_m) {          // «agregar al instante»: sin mover el mapa
      C.editor.nuevoPunto(tipo, { lat: u.lat, lon: u.lon, precision_m: u.precision_m, altitud: u.altitud, origen_coord: "gps", hora: u.hora });
      return;
    }
    entrar("punto");
    elegirTipo(tipo);
    if (u) M().irA(u.lat, u.lon, Math.max(M().leaflet().getZoom(), 19));
    pintarBanner(); mostrarCoord();
  }

  function ok() {
    if (cap.modo === "punto") {
      const coord = coordDelCentro();
      salir();
      C.editor.nuevoPunto(cap.tipo, coord);
    } else if (cap.modo === "ajuste") {
      const coord = coordDelCentro(), f = cap.alAjustar;
      salir(); cap.alAjustar = null;
      if (f) f(coord);
    }
  }

  function cancelar() {
    const f = cap.alAjustar;
    salir(); cap.alAjustar = null;
    if (f) f(null);
  }

  /* cambiar la posición de un punto que ya existe: devuelve la nueva coordenada (o null) a `alTerminar` */
  function ajustar(coord, alTerminar) {
    cap.alAjustar = alTerminar;
    entrar("ajuste");
    M().irA(coord.lat, coord.lon, Math.max(M().leaflet().getZoom(), 19));
    pintarBanner(); mostrarCoord();
  }

  /* ---------------------------------------------------------------- un cable, punto por punto */
  function iniciarCable(existente) {
    if (cap.modo || cap.grabando) return;
    entrar("cable");
    cap.tr = existente || window.CampoTrazo.crear();
    if (!existente) { const c = M().centro(), p = pegadoEn(c.lat, c.lon); cap.tr.agregar(p ? p.lat : c.lat, p ? p.lon : c.lon, p ? { poste: p.poste } : null); cap.sel = 0; if (p) centrarEn(p.lat, p.lon); }
    else { cap.sel = cap.tr.n() - 1; const v = cap.tr.vertices()[cap.sel]; centrarEn(v.lat, v.lon); }
    window.CampoRed.alTocar((p) => agregarEn(p.lat, p.lon, { poste: { nombre: p.n || p.t } }));
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  /* un poste o punto tocado en el mapa: pasa a ser el punto siguiente del cable */
  function agregarEn(lat, lon, extra) {
    if (cap.modo !== "cable") return false;
    cap.sel = cap.tr.insertarTras(cap.sel, lat, lon, extra);
    centrarEn(lat, lon);
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
    return true;
  }

  function masUno() {
    const c = M().centro();
    cap.sel = cap.tr.insertarTras(cap.sel, c.lat, c.lon);
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  function quitarUno() {
    if (cap.tr.n() < 2) { C.aviso("No se puede quitar el único punto: toque ✕ para cancelar el cable"); return; }
    cap.tr.quitarEn(cap.sel);
    cap.sel = Math.min(cap.sel, cap.tr.n() - 1);
    const v = cap.tr.vertices()[cap.sel]; centrarEn(v.lat, v.lon);
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  function irAlPunto(delta) {
    const n = cap.sel + delta;
    if (n < 0 || n >= cap.tr.n()) return;
    cap.sel = n;
    const v = cap.tr.vertices()[n]; centrarEn(v.lat, v.lon);
    M().pintarTrazo(cap.tr.vertices(), cap.sel); pintarBanner();
  }

  async function cancelarCable() {
    if (cap.tr.n() >= 3 && !(await C.dialogo.confirmar("¿Descartar el cable?", "Se pierden los puntos que puso.", [{ texto: "Descartar", valor: true, primario: true }, { texto: "Seguir", valor: false }]))) return;
    salir();
  }

  function terminarCable() {
    cap.tr.limpiar();
    if (!cap.tr.listo()) { C.aviso("Un cable necesita al menos dos puntos en lugares distintos", "malo"); pintarBanner(); return; }
    const tr = cap.tr;
    salir(true);
    C.editor.nuevoCable(tr);
  }

  /* ---------------------------------------------------------------- grabar un recorrido caminando */
  function opcionesGrabacion() { const a = ajustes(); return { precision: a.grab_precision, paso: a.grab_paso, tiempoMin: a.grab_tiempo }; }

  function textoGrabacion() {
    const u = M().ultima(), n = cap.tr.n();
    $("cap-grab-texto").textContent = n ? `${n} punto${n === 1 ? "" : "s"} · ${window.CampoTrazo.texto(cap.tr.longitud())}`
      : (u ? `Esperando un GPS de ±${ajustes().grab_precision} m o mejor (ahora ±${Math.round(u.precision_m)} m)…` : "Esperando el GPS…");
  }

  function iniciarGrabacion() {
    if (cap.modo || cap.grabando) { if (cap.grabando) C.aviso("Ya está grabando un recorrido"); return; }
    C.panel.cerrar(); C.tarjeta.ocultar();
    cap.tr = window.CampoTrazo.crear(); cap.grabando = true;
    cap.tr.fijar(M().ultima(), opcionesGrabacion());
    cap.quitarGrab = M().cuandoCambie((fix) => { if (fix && cap.tr.fijar(fix, opcionesGrabacion())) M().pintarTrazo(cap.tr.vertices(), -1); textoGrabacion(); });
    $("cap-grab").hidden = false; M().seguirGps(true);
    M().pintarTrazo(cap.tr.vertices(), -1); textoGrabacion();
  }

  function quitarGrabacion() {
    if (cap.quitarGrab) { cap.quitarGrab(); cap.quitarGrab = null; }
    cap.grabando = false; $("cap-grab").hidden = true;
  }

  async function pararGrabacion() {
    const r = await C.dialogo.confirmar("¿Terminar y guardar este cable?", cap.tr.n() ? `${cap.tr.n()} puntos · ${window.CampoTrazo.texto(cap.tr.longitud())}` : "Todavía no hay puntos grabados.",
      [{ texto: "Guardar", valor: "guardar", primario: true }, { texto: "Seguir grabando", valor: "seguir" }, { texto: "Descartar", valor: "descartar" }]);
    if (!r || r === "seguir") return;
    const tr = cap.tr;
    quitarGrabacion();
    if (r === "descartar") { M().limpiarTrazo(); return; }
    tr.limpiar();
    if (!tr.listo()) { M().limpiarTrazo(); C.aviso("Faltaron puntos: un cable necesita al menos dos en lugares distintos", "malo"); return; }
    C.editor.nuevoCable(tr);
  }

  /* ---------------------------------------------------------------- mira y coordenadas «siempre» (ajuste) */
  function refrescarSiempre() {
    if (cap.modo) return;
    const a = ajustes();
    $("mira").hidden = !(a.mira === "siempre");
    $("cap-coord").hidden = !(a.coordenadas === "siempre");
    if (a.coordenadas === "siempre" && M().leaflet()) mostrarCoord();
  }

  function conectar() {
    $("b-agregar").onclick = iniciarPunto;
    $("cap-ok").onclick = ok;
    $("cap-cancelar").onclick = cancelar;
    $("cap-huellas").onclick = () => { salir(); iniciarGrabacion(); };
    $("cap-ruta").onclick = () => { salir(); iniciarCable(); };
    document.querySelectorAll("#cap-tipos [data-cap-tipo]").forEach((b) => { b.onclick = () => elegirTipo(b.dataset.capTipo); });
    $("cap-mas").onclick = masUno; $("cap-quitar").onclick = quitarUno;
    $("cap-prev").onclick = () => irAlPunto(-1); $("cap-sig").onclick = () => irAlPunto(1);
    $("cap-guardar").onclick = terminarCable; $("cap-cable-x").onclick = cancelarCable;
    $("cap-grab-parar").onclick = pararGrabacion;
    document.addEventListener("campo-ajustes", refrescarSiempre);
    M().leaflet().on("move", () => { if (!cap.modo && ajustes().coordenadas === "siempre") mostrarCoord(); });
  }

  C.captura = { conectar, activa, iniciarPunto, iniciarCable, iniciarGrabacion, ajustar, agregarEn, refrescarSiempre, cancelar, salir, pegadoEn, trazoActual: () => cap.tr, grabando: () => cap.grabando };
})();
