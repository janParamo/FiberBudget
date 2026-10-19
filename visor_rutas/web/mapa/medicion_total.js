/* Metraje final y total de las medidas del mapa, con las reglas de negocio (Python: visor_rutas/medicion.py).
 *
 * Al terminar una medida se piden dos cosas, una detrás de otra:
 *   1. api.medir_ruta(puntos, false): al instante, el metraje final (reservas), el cable y los postes.
 *   2. api.medir_ruta(puntos, true): el total, llenando la misma plantilla del presupuesto y recalculándola (10-30 s).
 * Cada medida lleva su estado en medida.calc = { medicion, total: {estado, ...} }. Este archivo no conoce visor.js:
 * recibe lo que necesita en MedicionTotal.iniciar({...}).
 */
(function () {
  "use strict";
  let ctx = null;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** ctx: { api(): Api, medidas(): [], dinero(v), metros(v, dec), num(v, dec), cambio(medida), descargar(archivo),
   *         detalle(resultado), totalDe(resultado) } */
  function iniciar(contexto) {
    ctx = contexto;
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-mt]");
      if (!b) return;
      const medida = ctx.medidas().find((m) => m.id === Number(b.dataset.id));
      if (!medida || !medida.calc) return;
      const t = medida.calc.total;
      if (b.dataset.mt === "reintentar") pedir(medida);
      else if (b.dataset.mt === "descargar" && t.resultado) ctx.descargar(t.resultado.archivo);
      else if (b.dataset.mt === "detalle" && t.resultado) ctx.detalle(t.resultado);
    }, true);          // capture: Leaflet stops the click inside popups
  }

  const puntosDe = (medida) => medida.puntos.map((p) => [p.lat, p.lng]);

  async function llamar(medida, conTotal) {
    try {
      return await ctx.api().medir_ruta(puntosDe(medida), conTotal);
    } catch (e) {
      return { ok: false, error: "Error al comunicarse con Python: " + e };
    }
  }

  /** Pide el metraje y luego el total de la medida; cada respuesta avisa con ctx.cambio(medida). */
  async function pedir(medida) {
    if (!ctx || !ctx.api()) return;
    const calc = medida.calc = { medicion: null, error: null, total: { estado: "calculando" } };
    ctx.cambio(medida);
    const ligera = await llamar(medida, false);
    if (medida.calc !== calc) return;                     // the measure was recalculated or removed meanwhile
    if (!ligera.ok) {
      calc.error = ligera.error;
      calc.total = { estado: "error", error: ligera.error };
      ctx.cambio(medida);
      return;
    }
    calc.medicion = ligera.medicion;
    ctx.cambio(medida);
    const pesada = await llamar(medida, true);
    if (medida.calc !== calc) return;
    calc.total = pesada.ok ? { estado: "listo", resultado: pesada.resultado, supuestos: pesada.supuestos, medicion: pesada.medicion }
                           : { estado: "error", error: pesada.error };
    if (pesada.ok && pesada.medicion) calc.medicion = pesada.medicion;
    ctx.cambio(medida);
  }

  function totalDe(medida) {
    const t = medida.calc && medida.calc.total;
    return t && t.estado === "listo" && t.resultado.calculado ? ctx.totalDe(t.resultado) : null;
  }

  /** Short text for the end-of-line tooltip: " · final 523 m · C$ 12,345.00". */
  function textoCorto(medida) {
    const c = medida.calc;
    if (!c || !c.medicion) return "";
    const total = totalDe(medida);
    const final = ` · final ${ctx.metros(c.medicion.metraje_final_m, 0)}`;
    if (total !== null && total !== undefined) return `${final} · ${ctx.dinero(total)}`;
    return c.total.estado === "calculando" ? `${final} · calculando total…` : final;
  }

  function fila(titulo, valor) {
    return valor === null || valor === undefined || valor === "" ? "" : `<dt>${titulo}</dt><dd>${valor}</dd>`;
  }

  /** <dl> rows + buttons for the popup and the "Mis medidas" card. */
  function htmlDetalle(medida) {
    const c = medida.calc;
    if (!c) return "";
    if (!c.medicion) {
      return c.error ? `<div class="nota error">${esc(c.error)}</div><button type="button" class="btn btn-chico" data-mt="reintentar" data-id="${medida.id}">Reintentar</button>`
                     : `<div class="nota cargando"><span class="spinner"></span> Calculando metraje…</div>`;
    }
    const m = c.medicion, t = c.total, p = m.postes;
    let filas = fila("Metraje final", `<b>${ctx.metros(m.metraje_final_m, 1)}</b> <span class="nota">(+${ctx.metros(m.reserva_m, 1)} de reservas)</span>`)
      + fila("Cable", `${esc(m.tipo_cable)} <span class="nota">(umbral ${ctx.metros(m.umbral_m, 0)})</span>`)
      + fila("Postes", `${p.requeridos} <span class="nota">(${p.existentes} existentes, ${p.nuevos} nuevos)</span>`);
    let pie = "";
    if (t.estado === "calculando") {
      filas += fila("Total", `<span class="nota cargando"><span class="spinner"></span> calculando con las reglas de negocio…</span>`);
    } else if (t.estado === "error") {
      filas += fila("Total", `<span class="nota error">${esc(t.error)}</span>`);
      pie = `<button type="button" class="btn btn-chico" data-mt="reintentar" data-id="${medida.id}">Reintentar total</button>`;
    } else {
      const r = t.resultado;
      filas += fila("Total", r.calculado ? `<b class="medida-total">${ctx.dinero(ctx.totalDe(r))}</b>`
                                          : `<span class="nota">al abrir el Excel (falta LibreOffice)</span>`);
      pie = `<button type="button" class="btn btn-chico" data-mt="descargar" data-id="${medida.id}">Descargar Excel</button>
             <button type="button" class="btn btn-chico" data-mt="detalle" data-id="${medida.id}">Ver detalle</button>`;
    }
    const s = m.supuestos;
    const nota = `<div class="nota medida-supuestos">Supone ${s.conexiones_nuevas} conexión(es) de cliente y ${s.mufas_intervenidas} mufa(s) intervenida(s), `
      + `${esc(s.servicio)} ${esc(s.ancho_de_banda)}. Aproximado, no enviado.</div>`;
    const avisos = (m.avisos || []).map((a) => `<div class="nota error">${esc(a)}</div>`).join("");
    return `<dl class="medida-calc">${filas}</dl>${avisos}${nota}${pie ? `<div class="acciones">${pie}</div>` : ""}`;
  }

  window.MedicionTotal = { iniciar, pedir, textoCorto, htmlDetalle, totalDe };
})();
