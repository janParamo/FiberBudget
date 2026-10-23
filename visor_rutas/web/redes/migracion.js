/* Vista "Red existente" (migración Visio, fase 6: cola de corrección y tablero, docs/migracion_visio/PLAN.md §7).
 *
 * Arriba, el avance por zona (proyecto base): mufas migradas, con fusiones conocidas, con supuestos,
 * validadas y editadas. Abajo, la lista ordenada de lo que hay que corregir, con filtros por zona,
 * motivo y texto; clic en una fila abre la mufa en su editor, y una mufa sin ubicar se coloca con
 * un clic en el mapa de su zona. "Exportar a Excel" guarda ambas cosas para Planta Externa.
 * Datos: Redes.llamar("tablero_migracion" | "correcciones_migracion" | "exportar_correcciones").
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const st = { conectado: false, filas: [] };
  const estado = (t, tipo) => Redes.estadoEn($("mg-estado"), t, tipo);
  const filtros = () => ({ proyecto_id: Number($("mg-f-proyecto").value) || null, motivo: $("mg-f-motivo").value || null,
                           texto: $("mg-f-texto").value.trim() || null });
  const n = (v) => Number(v || 0).toLocaleString("es-NI");

  async function cargarTablero() {
    const r = await Redes.llamar("tablero_migracion", {});
    if (!r.ok) { estado(r.error, "error"); return false; }
    const fila = (z, total) => `<tr class="${total ? "mg-total" : ""}"${total ? "" : ` data-mg-zona="${z.proyecto_id}"`}>
      <td>${total ? "<b>Total</b>" : esc(z.proyecto)}</td><td>${n(z.mufas)}</td><td>${n(z.con_fusiones)}</td><td>${n(z.con_supuestos)}</td>
      <td>${n(z.validadas)}</td><td>${n(z.editadas)}</td><td>${n(z.sin_ubicar)}</td><td>${n(z.sin_diagramar)}</td><td>${n(z.por_corregir)}</td>
      <td><span class="mg-barra"><i style="width:${Math.min(100, z.avance)}%"></i></span> ${z.avance} %</td></tr>`;
    $("mg-zonas").innerHTML = r.zonas.map((z) => fila(z, false)).join("") + fila(r.total, true);
    const elegido = $("mg-f-proyecto").value, motivo = $("mg-f-motivo").value;
    $("mg-f-proyecto").innerHTML = `<option value="">Todas las zonas</option>` + r.zonas.map((z) => `<option value="${z.proyecto_id}">${esc(z.proyecto)}</option>`).join("");
    $("mg-f-proyecto").value = elegido;
    $("mg-f-motivo").innerHTML = `<option value="">Todos los motivos</option>` + r.motivos.map((m) => `<option value="${m.clave}">${esc(m.titulo)} (${n(m.mufas)})</option>`).join("");
    $("mg-f-motivo").value = motivo;
    return true;
  }

  async function cargarCola() {
    estado("Cargando la cola de corrección…", "cargando");
    const r = await Redes.llamar("correcciones_migracion", { ...filtros(), limite: 500 });
    if (!r.ok) { estado(r.error, "error"); $("mg-filas").innerHTML = ""; return; }
    st.filas = r.correcciones;
    $("mg-cuenta").textContent = r.total > r.correcciones.length ? `${n(r.total)} (se muestran las primeras ${n(r.correcciones.length)}; use los filtros)` : n(r.total);
    $("mg-filas").innerHTML = st.filas.map((f, i) => `<tr data-mg="${i}" class="mg-p${f.prioridad}">
      <td>${f.prioridad}</td><td>${esc(f.titulo)}</td><td><b>${esc(f.mufa)}</b></td><td>${esc(f.proyecto)}</td><td class="nota">${esc(f.detalle)}</td>
      <td class="acciones"><button type="button" class="btn btn-chico" data-mg-abrir="${i}">${f.motivo === "sin_ubicar" ? "Colocar en el mapa" : "Abrir mufa"}</button></td>
    </tr>`).join("") || `<tr><td colspan="6" class="vacio">Nada que corregir con estos filtros.</td></tr>`;
    estado("");
  }

  async function cargar() {
    estado("Cargando…", "cargando");
    if (await cargarTablero()) await cargarCola();
  }

  async function abrirFila(f) {
    if (f.motivo === "sin_ubicar") {
      if (window.EditorRed) window.EditorRed.ubicar(f.proyecto_id, f.mufa_id, f.sugerencia);
      return;
    }
    if (window.EditorMufa) window.EditorMufa.abrir(f.mufa_id, f.mufa);
  }

  async function exportar() {
    estado("Preparando el Excel…", "cargando");
    const r = await Redes.llamar("exportar_correcciones", filtros());
    if (!r.ok) { estado(r.error, "error"); return; }
    const g = await Redes.guardarArchivo(r.nombre, r.datos, r.tipo);
    if (g.ok) estado(`Guardado: ${g.ruta} (${n(r.filas)} correcciones)`, "ok");
    else estado(g.cancelado ? "" : g.error, g.cancelado ? "" : "error");
  }

  function conectar() {
    if (st.conectado) return;
    st.conectado = true;
    $("mg-recargar").addEventListener("click", cargar);
    $("mg-exportar").addEventListener("click", exportar);
    ["mg-f-proyecto", "mg-f-motivo"].forEach((id) => $(id).addEventListener("change", cargarCola));
    let espera = null;
    $("mg-f-texto").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(cargarCola, 300); });
    $("mg-zonas").addEventListener("click", (e) => {
      const z = e.target.closest("[data-mg-zona]");
      if (z) { $("mg-f-proyecto").value = z.dataset.mgZona; cargarCola(); }
    });
    $("mg-filas").addEventListener("click", (e) => {
      const fila = e.target.closest("[data-mg]");
      if (fila) abrirFila(st.filas[Number(fila.dataset.mg)]);
    });
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.migracion = { mostrar() { conectar(); cargar(); } };
  window.MigracionVisio = { _st: st, cargar };
})();
