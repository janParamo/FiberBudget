/* Editar la ruta, postes a mano y ruta dibujada a mano, con el presupuesto recalculándose solo (visor v2, fase 4B).
 *
 * Regla de Jan: todo cambio recalcula. Son cambios: mover, agregar o quitar un punto de la ruta; agregar un poste a mano; marcar un poste
 * como existente (eso ya existía); y dibujar la ruta completa a mano. Unos 0,6 s después del último cambio se pide a Python
 * `calcular_con_ruta` (distancia, metraje final, postes, mufas intervenidas y cantidades, sin Google: visor_rutas/calculo.py) y luego el
 * presupuesto aproximado con esa misma ruta (`estimar_presupuesto` con `ruta` y `postes_extra`). Una respuesta vieja se descarta.
 *
 *   «✎ Editar ruta» (tarjeta Ruta): los puntos se arrastran, clic en el punto medio de un tramo agrega uno, clic derecho en un punto lo quita.
 *   «＋ Poste a mano»: clic en el mapa agrega un poste nuevo (clic en uno de los suyos lo quita).
 *   «✎ Ruta a mano» (barra de abajo): clic para cada punto (se pega a postes y mufas), doble clic o Enter terminan; el presupuesto se va
 *   generando mientras se dibuja. «Volver a la de Google» rehace la ruta de la coordenada. «Guardar en Mis lugares» guarda la ruta.
 */
(function () {
  "use strict";

  const ESPERA_MS = 600;
  const er = { ctx: null, modo: null, capa: null, linea: null, guia: null, puntos: [], postes: [], capaPostes: null, token: 0, espera: null,
               deNada: false, editada: false, calculando: false, error: null };
  const $ = (id) => document.getElementById(id);

  const activo = () => er.modo === "dibujar" || er.modo === "poste";

  // ------------------------------------------------------------------ recalcular
  function programar() {
    clearTimeout(er.espera);
    er.token++;
    er.calculando = true;
    er.ctx.mensaje("Recalculando la ruta…", "cargando");
    er.espera = setTimeout(recalcular, ESPERA_MS);
  }

  function puntosActuales() {
    if (er.pendientes) return er.pendientes;                // the points of an edit that ended before its recalculation did
    if (er.modo === "dibujar") return er.puntos.map((p) => [p.lat, p.lng]);
    return er.capa ? er.capa.getLatLngs().map((p) => [p.lat, p.lng]) : (er.ctx.datos() ? er.ctx.datos().ruta.puntos : []);
  }

  async function recalcular() {
    const token = er.token;
    const pts = puntosActuales();
    if (pts.length < 2) { er.calculando = false; return; }
    const cli = er.ctx.datos() && !er.deNada ? er.ctx.datos().cliente : null;
    let r;
    try {
      r = await er.ctx.api().calcular_con_ruta(cli ? cli.lat : null, cli ? cli.lon : null, pts, er.postes.length);
    } catch (e) {
      r = { ok: false, error: "Error al comunicarse con Python: " + e };
    }
    if (token !== er.token) return;                       // there is a newer change on its way
    er.calculando = false;
    if (!r.ok) { er.error = r.error; er.ctx.mensaje(r.error, "error"); er.ctx.repintar(); return; }
    er.error = null;
    er.editada = true;
    er.ctx.aplicar(r.datos, r.coordenada);
    pintarPostes();
    er.ctx.mensaje(`Ruta ${er.deNada ? "dibujada" : "editada"}: ${Number(r.datos.ruta.distancia_m).toLocaleString("en-US", { maximumFractionDigits: 1 })} m, metraje final ${Number(r.datos.ruta.metraje_final_m).toLocaleString("en-US", { maximumFractionDigits: 1 })} m. Recalculando el presupuesto aproximado…`, "ok");
  }

  // ------------------------------------------------------------------ editar los puntos de la ruta
  function empezarEdicion() {
    const d = er.ctx.datos();
    if (!d || activo()) return;
    if (er.ctx.ocupado()) { er.ctx.mensaje("Termine la medición antes de editar la ruta"); return; }
    detener();
    er.modo = "editar";
    er.capa = L.polyline(d.ruta.puntos, { color: "#ffffff", weight: 3, opacity: 0.95, interactive: true }).addTo(er.ctx.mapa);
    er.capa.pm.enable({ allowSelfIntersection: true, snappable: false });
    er.capa.on("pm:edit pm:vertexadded pm:vertexremoved pm:markerdragend", programar);
    er.ctx.mapa.doubleClickZoom.disable();
    er.ctx.mensaje("Editar ruta: arrastre un punto, clic en el punto medio de un tramo para agregar uno, clic derecho en un punto para quitarlo", "ok");
    er.ctx.repintar();
  }

  function detener() {
    clearTimeout(er.espera);
    if (er.capa) { if (er.capa.pm) er.capa.pm.disable(); er.ctx.mapa.removeLayer(er.capa); er.capa = null; }
    if (er.linea) { er.ctx.mapa.removeLayer(er.linea); er.linea = null; }
    if (er.guia) { er.ctx.mapa.removeLayer(er.guia); er.guia = null; }
    er.ctx.mapa.off("click", alClicMapa).off("mousemove", alMover).off("dblclick", alDoble);
    document.removeEventListener("keydown", alTecla, true);
    er.ctx.mapa.doubleClickZoom.enable();
    er.ctx.mapa.getContainer().classList.remove("midiendo");
    const ayuda = $("medir-ayuda");
    if (ayuda && er.ayudaPropia) { ayuda.hidden = true; er.ayudaPropia = false; }
    er.modo = null;
    er.puntos = [];
  }

  function terminar() {
    if (er.modo === "dibujar") {
      const pts = er.puntos.map((p) => [p.lat, p.lng]);
      detener();
      if (pts.length >= 2) {
        er.deNada = true;
        er.pendientes = pts;
        recalcular().then(() => { er.pendientes = null; empezarEdicion(); });
      } else { er.ctx.mensaje("Ruta cancelada: se necesitan al menos dos puntos"); er.ctx.repintar(); }
      return;
    }
    if (er.calculando) { er.pendientes = puntosActuales(); detener(); recalcular().then(() => { er.pendientes = null; er.ctx.repintar(); }); return; }
    detener();
    er.ctx.repintar();
  }

  // ------------------------------------------------------------------ ruta dibujada a mano
  function empezarDibujo() {
    if (activo() || er.ctx.ocupado()) { if (er.ctx.ocupado()) er.ctx.mensaje("Termine la medición antes de dibujar una ruta"); return; }
    detener();
    reiniciar(true);
    er.modo = "dibujar";
    er.deNada = true;
    const mapa = er.ctx.mapa;
    er.linea = L.polyline([], { color: "#ffe600", weight: 5, interactive: false }).addTo(mapa);
    er.guia = L.polyline([], { color: "#ffe600", weight: 2, dashArray: "6 6", interactive: false }).addTo(mapa);
    mapa.doubleClickZoom.disable();
    mapa.getContainer().classList.add("midiendo");
    const ayuda = $("medir-ayuda");
    if (ayuda) { ayuda.hidden = false; ayuda.textContent = "Ruta a mano: clic para cada punto (se pega a postes y mufas) · doble clic o Enter termina · Retroceso quita el último · Esc cancela. El presupuesto se va calculando."; er.ayudaPropia = true; }
    mapa.on("click", alClicMapa).on("mousemove", alMover).on("dblclick", alDoble);
    document.addEventListener("keydown", alTecla, true);
    er.ctx.repintar();
  }

  function agregarPunto(latlng) {
    const ll = er.ctx.imantar(latlng);
    const ultimo = er.puntos[er.puntos.length - 1];
    if (ultimo && ultimo.equals(ll)) return;                 // the second click of a double click
    er.puntos.push(ll);
    er.linea.setLatLngs(er.puntos);
    if (er.puntos.length >= 2) programar();
  }

  const alClicMapa = (ev) => {
    if (er.modo === "dibujar") agregarPunto(ev.latlng);
    else if (er.modo === "poste") agregarPoste(ev.latlng);
  };
  const alMover = (ev) => { if (er.modo === "dibujar" && er.puntos.length) er.guia.setLatLngs([er.puntos[er.puntos.length - 1], er.ctx.imantar(ev.latlng)]); };
  const alDoble = (ev) => { L.DomEvent.stop(ev); if (er.modo === "dibujar") terminar(); };
  const alTecla = (ev) => {
    if (ev.target.closest && ev.target.closest("input, textarea, select")) return;
    if (ev.key === "Escape") { ev.stopPropagation(); if (er.modo === "dibujar") terminar(); else terminar(); }
    else if (ev.key === "Enter") { ev.preventDefault(); terminar(); }
    else if (ev.key === "Backspace" && er.modo === "dibujar") { ev.preventDefault(); er.puntos.pop(); er.linea.setLatLngs(er.puntos); er.guia.setLatLngs([]); if (er.puntos.length >= 2) programar(); }
  };

  // ------------------------------------------------------------------ postes a mano
  function pintarPostes() {
    if (!er.capaPostes) er.capaPostes = L.layerGroup().addTo(er.ctx.mapa);
    er.capaPostes.clearLayers();
    er.postes.forEach((ll, i) => {
      const mk = L.marker(ll, { icon: er.ctx.ICONOS.posteNuevo, zIndexOffset: 800 }).bindTooltip(`Poste a mano ${i + 1} (nuevo) · clic para quitarlo`, { direction: "top", className: "hover" });
      mk.on("click", (ev) => { L.DomEvent.stopPropagation(ev); quitarPoste(i); });
      mk.addTo(er.capaPostes);
    });
  }

  function agregarPoste(latlng) {
    er.postes.push(latlng);
    pintarPostes();
    programar();
  }

  function quitarPoste(i) {
    er.postes.splice(i, 1);
    pintarPostes();
    programar();
  }

  function modoPoste() {
    const d = er.ctx.datos();
    if (!d || er.ctx.ocupado()) return;
    if (er.modo === "poste") { detener(); er.ctx.repintar(); return; }
    if (er.modo === "editar") {
      if (er.calculando) { er.pendientes = puntosActuales(); recalcular().then(() => { er.pendientes = null; }); }
      detener();
    }
    er.modo = "poste";
    er.ctx.mapa.on("click", alClicMapa);
    document.addEventListener("keydown", alTecla, true);
    er.ctx.mapa.getContainer().classList.add("midiendo");
    er.ctx.mensaje("Poste a mano: clic en el mapa donde va un poste nuevo · Esc o «Terminar» para salir", "ok");
    pintarPostes();
    er.ctx.repintar();
  }

  // ------------------------------------------------------------------ estado y tarjeta del panel
  function reiniciar(conservarModo) {
    clearTimeout(er.espera);
    er.token++;
    if (!conservarModo && er.modo) detener();
    if (er.capaPostes) { er.ctx.mapa.removeLayer(er.capaPostes); er.capaPostes = null; }
    er.postes = [];
    er.editada = false;
    er.deNada = false;
    er.calculando = false;
    er.error = null;
    er.pendientes = null;
  }

  /** Parameters of estimar_presupuesto: [ruta | null, postes_extra]. */
  function paramsEstimacion() {
    const d = er.ctx && er.ctx.datos();
    if (!d || !(er.editada || (d.ruta && d.ruta.manual))) return [null, 0];
    return [d.ruta.puntos.map((p) => [p[0], p[1]]), er.postes.length];
  }

  /** Extra fields for the budget form when it is for the same client coordinate as the edited route. */
  function paramsFormulario(coordenada) {
    const d = er.ctx && er.ctx.datos();
    if (!d || !(er.editada || (d.ruta && d.ruta.manual))) return {};
    const partes = String(coordenada || "").trim().replace(/^[([]|[)\]]$/g, "").split(/[,;\s]+/).filter(Boolean).map(Number);
    const igual = (a, b) => Math.abs(a - b) < 5e-7;
    if (partes.length !== 2 || !igual(partes[0], d.cliente.lat) || !igual(partes[1], d.cliente.lon)) return {};
    return { ruta_editada: d.ruta.puntos.map((p) => [p[0], p[1]]), ...(er.postes.length ? { postes_a_mano: er.postes.length } : {}) };
  }

  function htmlRuta() {
    const d = er.ctx.datos();
    if (!d) return "";
    const manual = d.ruta.manual || er.editada;
    const edit = er.modo === "editar", poste = er.modo === "poste", dibujo = er.modo === "dibujar";
    const boton = (a, t, extra = "") => `<button type="button" class="btn btn-chico${extra}" data-er="${a}">${t}</button>`;
    let botones;
    if (dibujo) botones = boton("terminar", "✔ Terminar ruta", " btn-primario");
    else if (edit || poste) botones = boton("terminar", "✔ Terminar edición", " btn-primario") + boton("poste", poste ? "Salir de postes" : "＋ Poste a mano");
    else botones = boton("editar", "✎ Editar ruta") + boton("poste", "＋ Poste a mano");
    if (!activo() && !edit) {
      if (manual && !er.deNada && !(d.ruta.manual && !er.editada)) botones += boton("google", "Volver a la de Google");
      botones += boton("guardar", "Guardar en Mis lugares");
    }
    const estado = er.error ? `<div class="nota error">${er.error}</div>` : (er.calculando ? '<div class="nota cargando"><span class="spinner"></span> Recalculando…</div>' : "");
    return `<div class="er-acciones">${manual ? `<span class="etiqueta-aprox">${er.deNada ? "Ruta dibujada a mano" : "Ruta editada a mano"}</span>` : ""}
      ${er.postes.length ? `<div class="nota">${er.postes.length} poste(s) a mano (cobrados como nuevos)</div>` : ""}${estado}
      <div class="acciones-pres">${botones}</div></div>`;
  }

  function iniciar(ctx) {
    er.ctx = ctx;
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-er]");
      if (!b) return;
      const a = b.dataset.er;
      if (a === "editar") empezarEdicion();
      else if (a === "terminar") terminar();
      else if (a === "poste") modoPoste();
      else if (a === "google") { reiniciar(); ctx.generarDeNuevo(); }
      else if (a === "guardar") ctx.guardarEnMisLugares(ctx.datos().ruta.puntos);
    }, true);
    const boton = $("ruta-mano");
    if (boton) boton.addEventListener("click", () => (er.modo === "dibujar" ? terminar() : empezarDibujo()));
  }

  window.EditarRuta = { iniciar, reiniciar: () => reiniciar(), htmlRuta, paramsEstimacion, paramsFormulario, terminar, empezarDibujo, empezarEdicion,
                        get activo() { return activo(); }, get _capa() { return er.capa; }, get modo() { return er.modo; }, get editada() { return er.editada; },
                        clic: (ll) => { if (er.modo === "dibujar") agregarPunto(ll); }, get postes() { return er.postes.length; } };
})();
