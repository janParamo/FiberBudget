/* Ruta de fusión editable y su franja en el Excel (visor v2, fase 4B).
 *
 * En la pestaña «Ruta de fusión», debajo de las paradas de los diagramas, el bloque «Ruta para el Excel» muestra el plan que armó Python
 * (visor_rutas/ruta_fusion_plan.py): una caja por mufa, del cliente hacia la potencia, con el texto como se escribe en el libro de rutas
 * de fusión. Se edita: tocar / no tocar (aérea y de corte no se tocan por el nombre), hilos hacia el cliente y hacia la potencia, splitter,
 * texto a mano, quitar, subir / bajar, agregar una mufa o una mufa nueva, «compartir potencia del SP» y avisos en rojo. Cada cambio pide a
 * Python los textos de nuevo (`redactar_fusion`), rehace el camino del mapa y el presupuesto aproximado (cuenta las mufas que se tocan).
 * «Exportar al Excel» agrega la franja al libro (`exportar_fusion`): cliente vacío si fue a mano, fecha de hoy, mapa opcional.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ef = { ctx: null, origen: null, plan: null, editado: false, cliente: "", fecha: "", conMapa: true, estado: "", tipoEstado: "", espera: null, token: 0, exportando: false };
  const hoy = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const SPLITTERS = ["1/2", "1/4", "1/8", "1/16", "1/32"];

  /** Takes the plan of the route on screen (a new route resets the edits). */
  function sincronizar() {
    const d = ef.ctx.datos();
    const plan = d && d.plan_fusion;
    if (plan === ef.origen) return;
    ef.origen = plan || null;
    ef.plan = plan ? JSON.parse(JSON.stringify(plan)) : null;
    ef.editado = false;
    ef.estado = ef.tipoEstado = "";
    ef.fecha = ef.fecha || hoy();
  }

  const nombresTocados = () => (ef.plan && ef.editado ? new Set(ef.plan.pasos.filter((p) => p.tocar).map((p) => p.nombre)) : null);
  const mufasTocadas = () => (ef.plan && ef.editado ? ef.plan.tocadas : null);

  // ------------------------------------------------------------------ cambios
  function cambio() {
    ef.editado = true;
    clearTimeout(ef.espera);
    const token = ++ef.token;
    ef.espera = setTimeout(async () => {
      let r;
      try { r = await ef.ctx.api().redactar_fusion(ef.plan); } catch (e) { r = { ok: false, error: String(e) }; }
      if (token !== ef.token) return;
      if (!r.ok) { ef.estado = r.error; ef.tipoEstado = "error"; pintar(); return; }
      ef.plan = r.plan;
      ef.estado = ef.tipoEstado = "";
      pintar();
      ef.ctx.alCambiar();            // the map path and the approximate budget (it counts the mufas that are touched)
    }, 250);
    pintar();
  }

  function pintar() { ef.ctx.repintar(); }

  async function agregarMufa(tipo) {
    const nombre = await Dialogo.pedirTexto(tipo === "nueva" ? "Mufa nueva" : "Agregar mufa", "", "Nombre de la mufa (sin «MF»)");
    if (!nombre) return;
    ef.plan.pasos.push({ id: `u${Date.now()}`, tipo, nombre, lat: null, lon: null, tocar: true, motivo: null, hilo_cliente: "H__", hilo_potencia: "H__", splitter: null, texto_manual: null, fuente_hilos: "usuario" });
    cambio();
  }

  function alAccion(e) {
    const b = e.target.closest("[data-ef]");
    if (!b || !ef.plan || !$("fusion").contains(b)) return;
    const a = b.dataset.ef, i = Number(b.dataset.i);
    const paso = ef.plan.pasos[i];
    if (e.type === "click") {
      if (a === "quitar") { ef.plan.pasos.splice(i, 1); cambio(); }
      else if (a === "subir" && i > 0) { ef.plan.pasos.splice(i - 1, 0, ef.plan.pasos.splice(i, 1)[0]); cambio(); }
      else if (a === "bajar" && i < ef.plan.pasos.length - 1) { ef.plan.pasos.splice(i + 1, 0, ef.plan.pasos.splice(i, 1)[0]); cambio(); }
      else if (a === "mufa") agregarMufa("mufa");
      else if (a === "nueva") agregarMufa("nueva");
      else if (a === "restaurar_texto") { paso.texto_manual = null; cambio(); }
      else if (a === "rehacer") { ef.origen = null; ef.plan = null; sincronizar(); ef.ctx.alCambiar(); pintar(); }
      else if (a === "exportar") exportar();
      return;
    }
    // change events
    if (a === "tocar") { paso.tocar = b.checked; paso.motivo = b.checked ? null : (paso.motivo || "a mano"); cambio(); }
    else if (a === "hilo_cliente" || a === "hilo_potencia") { paso[a] = b.value.trim() || "H__"; cambio(); }
    else if (a === "splitter") { paso.splitter = b.value || null; cambio(); }
    else if (a === "texto_manual") { paso.texto_manual = b.value.trim() && b.value.trim() !== paso.texto ? b.value.trim() : null; cambio(); }
    else if (a === "compartir") { ef.plan.compartir_potencia = b.checked; cambio(); }
    else if (a === "avisos") { ef.plan.avisos_rojos = b.value.split("\n").map((x) => x.trim()).filter(Boolean); cambio(); }
    else if (a === "cliente") ef.cliente = b.value;
    else if (a === "fecha") ef.fecha = b.value;
    else if (a === "mapa") ef.conMapa = b.checked;
  }

  // ------------------------------------------------------------------ exportar
  async function exportar() {
    if (ef.exportando || !ef.plan) return;
    const d = ef.ctx.datos();
    ef.exportando = true;
    ef.estado = "Agregando la franja al libro de rutas de fusión…"; ef.tipoEstado = "cargando";
    pintar();
    const opciones = { cliente: ef.cliente.trim(), fecha: ef.fecha || hoy(), con_mapa: ef.conMapa,
                       mapa: { ruta: d.ruta.puntos, conexion: { nombre: d.conexion.nombre, lat: d.conexion.lat, lon: d.conexion.lon }, cliente: d.cliente, distancia_m: d.ruta.distancia_m } };
    let r;
    try { r = await ef.ctx.api().exportar_fusion(ef.plan, opciones); } catch (e) { r = { ok: false, error: "Error al comunicarse con Python: " + e }; }
    ef.exportando = false;
    if (!r.ok) { ef.estado = r.error; ef.tipoEstado = "error"; pintar(); return; }
    ef.plan = r.plan;
    ef.estado = `Ruta de fusión agregada a «${r.hoja}», filas ${r.fila_inicial}–${r.fila_final} (${r.pasos} mufa(s)). Respaldo del libro: ${r.respaldo || "—"}`
      + (r.avisos && r.avisos.length ? ` · ${r.avisos.join(" · ")}` : "");
    ef.tipoEstado = "ok";
    pintar();
    ef.ctx.mensaje("Ruta de fusión agregada al libro de rutas de fusión", "ok");
  }

  // ------------------------------------------------------------------ vista
  function htmlPaso(p, i, n) {
    const fila = `<li class="ef-paso${p.tocar ? "" : " ef-no-tocar"}" data-i="${i}">
      <div class="ef-cabeza"><label><input type="checkbox" data-ef="tocar" data-i="${i}" ${p.tocar ? "checked" : ""}> <b>${esc(p.nombre)}</b></label>
        ${p.tipo === "nueva" ? '<span class="insignia nota">mufa nueva</span>' : ""}${!p.tocar && p.motivo ? `<span class="insignia alerta">no se toca: ${esc(p.motivo)}</span>` : ""}
        ${p.por_nombre ? '<span class="insignia por-nombre">por nombre</span>' : ""}
        <span class="ef-botones"><button type="button" class="btn btn-chico" data-ef="subir" data-i="${i}" ${i === 0 ? "disabled" : ""} title="Hacia el cliente">↑</button>
          <button type="button" class="btn btn-chico" data-ef="bajar" data-i="${i}" ${i === n - 1 ? "disabled" : ""} title="Hacia la potencia">↓</button>
          <button type="button" class="btn btn-chico" data-ef="quitar" data-i="${i}" title="Quitar de la ruta">✕</button></span></div>`;
    if (!p.tocar) return fila + "</li>";
    return fila + `<div class="ef-hilos"><label>Hilo hacia el cliente <input class="ef-hilo" data-ef="hilo_cliente" data-i="${i}" value="${esc(p.hilo_cliente)}" ${i === 0 || ef.plan.pasos.findIndex((x) => x.tocar) === i ? "disabled title=\"Es la mufa del cliente: entra la acometida (H1)\"" : ""}></label>
        <label>Hilo hacia la potencia <input class="ef-hilo" data-ef="hilo_potencia" data-i="${i}" value="${esc(p.hilo_potencia)}"></label>
        <label>Splitter <select data-ef="splitter" data-i="${i}"><option value="">—</option>${SPLITTERS.map((s) => `<option value="${s}" ${p.splitter === s ? "selected" : ""}>1x${s.split("/")[1]}</option>`).join("")}</select></label></div>
      <textarea class="ef-texto" data-ef="texto_manual" data-i="${i}" rows="2" title="Se puede escribir a mano">${esc(p.texto || "")}</textarea>
      ${p.texto_manual ? `<button type="button" class="btn btn-chico" data-ef="restaurar_texto" data-i="${i}">Volver al texto automático</button>` : ""}
      </li>`;
  }

  function html() {
    sincronizar();
    const d = ef.ctx.datos();
    if (!d || !ef.plan) return "";
    const plan = ef.plan, n = plan.pasos.length;
    const nota = `<p class="nota">Del cliente hacia la potencia (${esc(plan.potencia || "potencia sin definir")}). Una mufa aérea o de corte no se toca (por el nombre); marque o desmarque a mano.
        Los hilos sin dato quedan «H__» para identificarlos.</p>`;
    return `<section class="tarjeta ef-bloque"><h2>Ruta para el Excel <span class="nota">${plan.tocadas} mufa(s) a intervenir${ef.editado ? " · editada" : ""}</span></h2>${nota}
      <ol class="ef-pasos">${n ? plan.pasos.map((p, i) => htmlPaso(p, i, n)).join("") : '<li class="vacio">No hay mufas en la ruta: agregue las que se intervienen.</li>'}</ol>
      <div class="acciones-pres"><button type="button" class="btn btn-chico" data-ef="mufa">＋ Mufa</button><button type="button" class="btn btn-chico" data-ef="nueva">＋ Mufa nueva</button>
        ${ef.editado ? '<button type="button" class="btn btn-chico" data-ef="rehacer">Rehacer desde los diagramas</button>' : ""}</div>
      <label class="ef-linea"><input type="checkbox" data-ef="compartir" ${plan.compartir_potencia ? "checked" : ""}> Escribir «COMPARTIR POTENCIA DEL SP»</label>
      <label class="ef-linea">Avisos en rojo (uno por línea)<textarea data-ef="avisos" rows="2">${esc((plan.avisos_rojos || []).join("\n"))}</textarea></label>
      <div class="ef-exportar"><label class="ef-linea">Cliente <input data-ef="cliente" value="${esc(ef.cliente)}" placeholder="vacío si el presupuesto fue a mano; con ticket: su nombre"></label>
        <label class="ef-linea">Fecha <input type="date" data-ef="fecha" value="${esc(ef.fecha)}"></label>
        <label class="ef-linea"><input type="checkbox" data-ef="mapa" ${ef.conMapa ? "checked" : ""}> Mapa de la ruta bajo «RUTA SUGERIDA»</label>
        <button type="button" class="btn btn-primario" data-ef="exportar" ${ef.exportando || !plan.tocadas ? "disabled" : ""}>Exportar al Excel</button></div>
      ${ef.estado ? `<div class="nota ef-estado ${esc(ef.tipoEstado)}">${esc(ef.estado)}</div>` : ""}</section>`;
  }

  function iniciar(ctx) {
    ef.ctx = ctx;
    ef.fecha = hoy();
    const caja = $("fusion");
    caja.addEventListener("click", alAccion);
    caja.addEventListener("change", alAccion);
  }

  window.EditarFusion = { iniciar, html, nombresTocados, mufasTocadas, get plan() { return ef.plan; }, get editado() { return ef.editado; } };
})();
