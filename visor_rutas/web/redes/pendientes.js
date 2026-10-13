/* Vista "Pendientes" del módulo de redes (fase 7.2) y su ventana de alta / edición.
 *
 * Tareas de un proyecto (opcionalmente ligadas a un elemento o cable) con responsable, fecha límite y
 * estado; filtros por proyecto, estado, responsable, vencidos y texto. Las vencidas se ven en rojo.
 * Pendientes.nuevo({proyecto_id, elemento_id | cable_id}) lo usa también el editor de mapa.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const ESTADO = { pendiente: "Por hacer", en_proceso: "En proceso", hecho: "Hecho" };
  const CAMPOS = ["titulo", "proyecto", "vinculo", "responsable", "fecha", "descripcion"];      // (pe-estado is the view's status line)
  const st = { lista: [], editando: null, conectado: false };
  const estado = (t, tipo) => Redes.estadoEn($("pe-estado"), t, tipo);
  const formEstado = (t, tipo) => Redes.estadoEn($("pe-form-estado"), t, tipo);
  const fecha = (iso) => (iso ? new Date(`${String(iso).slice(0, 10)}T12:00:00`).toLocaleDateString("es-NI") : "—");

  async function cargar() {
    estado("Cargando pendientes…", "cargando");
    const f = { proyecto_id: $("pe-f-proyecto").value || null, estado: $("pe-f-estado").value || null,
                responsable: $("pe-f-responsable").value || null, vencidos: $("pe-f-vencidos").checked,
                texto: $("pe-f-texto").value.trim() || null };
    const r = await Redes.llamar("pendientes", f);
    if (!r.ok) { estado(r.error, "error"); $("pe-filas").innerHTML = ""; return; }
    st.lista = r.pendientes;
    const vencidos = st.lista.filter((t) => t.vencido).length;
    estado(`${st.lista.length} pendiente${st.lista.length === 1 ? "" : "s"}${vencidos ? ` · ${vencidos} vencido${vencidos === 1 ? "" : "s"}` : ""}`);
    pintar();
  }

  function pintar() {
    $("pe-filas").innerHTML = st.lista.map((t) => `<tr class="${t.estado === "hecho" ? "inactivo" : ""}${t.vencido ? " tk-vencido" : ""}" data-pe="${t.id}">
      <td><b>${esc(t.titulo)}</b>${t.descripcion ? `<div class="nota tk-desc">${esc(t.descripcion.slice(0, 140))}</div>` : ""}</td>
      <td>${esc(t.proyecto)}</td><td>${esc(t.vinculo || "—")}</td><td>${esc(t.responsable || "Sin responsable")}</td>
      <td>${fecha(t.fecha_limite)}${t.vencido ? ` <span class="tk-sev sev-critica">Vencido</span>` : ""}</td>
      <td><span class="tk-est est-${t.estado}">${ESTADO[t.estado]}</span></td>
      <td class="acciones">${t.puede_cambiar_estado && t.estado !== "hecho"
        ? `<button type="button" class="btn btn-chico" data-pe-hecho="${t.id}" title="Marcar como hecho">✓ Hecho</button>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="7" class="vacio">Ningún pendiente con estos filtros.</td></tr>`;
  }

  async function cargarReferencias(proyectoId, vinculo, responsable) {
    $("pe-vinculo").innerHTML = `<option value="">Todo el proyecto</option>`;
    $("pe-responsable").innerHTML = `<option value="">Sin responsable</option>`;
    if (!proyectoId) return;
    const r = await Redes.llamar("referencias_proyecto", { proyecto_id: Number(proyectoId) });
    if (!r.ok) { formEstado(r.error, "error"); return; }
    $("pe-vinculo").innerHTML = Redes.opcionesVinculo(r, "Todo el proyecto");
    $("pe-responsable").innerHTML = `<option value="">Sin responsable</option>`
      + r.usuarios.map((u) => `<option value="${u.id}">${esc(u.nombre)} (${esc(Redes.ROLES[u.rol] || u.rol)})</option>`).join("");
    if (vinculo) $("pe-vinculo").value = vinculo;
    if (responsable) $("pe-responsable").value = String(responsable);
  }

  async function abrirFormulario(t, preset = {}) {
    st.editando = t || null;
    $("pe-modal-titulo").textContent = t ? `Pendiente: ${t.titulo}` : "Nuevo pendiente";
    Redes.marcarErrores("pe-", CAMPOS, null);
    formEstado("");
    $("pe-titulo").value = t ? t.titulo : "";
    $("pe-descripcion").value = t ? t.descripcion || "" : "";
    $("pe-fecha").value = t && t.fecha_limite ? String(t.fecha_limite).slice(0, 10) : "";
    $("pe-estado-sel").value = t ? t.estado : "pendiente";
    const proyecto = t ? t.proyecto_id : preset.proyecto_id || $("pe-f-proyecto").value || "";
    await Redes.llenarProyectos($("pe-proyecto"), proyecto, "Elija el proyecto…");
    $("pe-proyecto").disabled = !!t;
    const vinculo = t ? (t.elemento_id ? `e:${t.elemento_id}` : t.cable_id ? `c:${t.cable_id}` : "")
      : preset.elemento_id ? `e:${preset.elemento_id}` : preset.cable_id ? `c:${preset.cable_id}` : "";
    await cargarReferencias($("pe-proyecto").value, vinculo, t ? t.responsable_id : null);
    const editor = !t || t.puede_editar;
    ["pe-titulo", "pe-vinculo", "pe-responsable", "pe-fecha", "pe-descripcion"].forEach((id) => { $(id).disabled = !editor; });
    $("pe-estado-sel").disabled = !(editor || (t && t.puede_cambiar_estado));
    $("pe-guardar").hidden = !(editor || (t && t.puede_cambiar_estado));
    $("pe-eliminar").hidden = !t || !t.puede_editar;
    $("pe-historial").hidden = !t;
    $("pe-info").textContent = t ? `Creado por ${t.creado_por || "—"} el ${Redes.fecha(t.creado_en)}`
      + (t.actualizado_por ? ` · último cambio: ${t.actualizado_por}, ${Redes.fecha(t.actualizado_en)}` : "")
      + (t.hecho_en ? ` · hecho el ${Redes.fecha(t.hecho_en)}` : "")
      + (!editor && t.puede_cambiar_estado ? " · usted es el responsable: puede cambiar el estado" : !editor ? " · solo lectura" : "") : "";
    $("modal-pendiente").hidden = false;
    (editor ? $("pe-titulo") : $("pe-estado-sel")).focus();
  }

  async function guardar(ev, cambios) {
    if (ev) ev.preventDefault();
    let datos;
    if (cambios) datos = cambios;
    else {
      const [tipo, id] = ($("pe-vinculo").value || ":").split(":");
      datos = { proyecto_id: Number($("pe-proyecto").value) || null, titulo: $("pe-titulo").value, descripcion: $("pe-descripcion").value,
                elemento_id: tipo === "e" ? Number(id) : null, cable_id: tipo === "c" ? Number(id) : null,
                responsable_id: Number($("pe-responsable").value) || null, fecha_limite: $("pe-fecha").value || null, estado: $("pe-estado-sel").value };
      if (st.editando) Object.assign(datos, { id: st.editando.id, version: st.editando.version });
      if (!datos.proyecto_id) { Redes.marcarErrores("pe-", CAMPOS, { proyecto: "elija el proyecto" }); return; }
      Redes.marcarErrores("pe-", CAMPOS, null);
      formEstado("Guardando…", "cargando");
    }
    const r = await Redes.llamar("guardar_pendiente", { datos });
    if (!r.ok) {
      if (cambios) { estado(r.error, "error"); return; }
      const e = r.errores || {};
      Redes.marcarErrores("pe-", CAMPOS, { ...e, fecha: e.fecha_limite, responsable: e.responsable_id });
      formEstado(r.error, "error");
      return;
    }
    $("modal-pendiente").hidden = true;
    if (!$("vista-pendientes").hidden) cargar();
    if (window.visor) window.visor.mensaje(`Pendiente "${r.pendiente.titulo}" guardado`, "ok");
  }

  async function eliminar() {
    const t = st.editando;
    if (!t || !(await Redes.confirmar(`¿Eliminar el pendiente "${t.titulo}"? (Queda en el historial)`, "Eliminar"))) return;
    const r = await Redes.llamar("eliminar_pendiente", { id: t.id, version: t.version });
    if (!r.ok) { formEstado(r.error, "error"); return; }
    $("modal-pendiente").hidden = true;
    if (!$("vista-pendientes").hidden) cargar();
  }

  function conectar() {
    if (st.conectado) return;
    st.conectado = true;
    $("pe-recargar").addEventListener("click", cargar);
    $("pe-nuevo").addEventListener("click", () => abrirFormulario(null));
    ["pe-f-proyecto", "pe-f-estado", "pe-f-responsable", "pe-f-vencidos"].forEach((id) => $(id).addEventListener("change", cargar));
    let espera = null;
    $("pe-f-texto").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(cargar, 300); });
    $("pe-filas").addEventListener("click", (e) => {
      const hecho = e.target.closest("[data-pe-hecho]");
      if (hecho) {
        const t = st.lista.find((x) => x.id === Number(hecho.dataset.peHecho));
        guardar(null, { ...t, estado: "hecho" });
        return;
      }
      const fila = e.target.closest("[data-pe]");
      if (fila) abrirFormulario(st.lista.find((t) => t.id === Number(fila.dataset.pe)));
    });
    $("pe-form").addEventListener("submit", guardar);
    $("pe-proyecto").addEventListener("change", () => cargarReferencias($("pe-proyecto").value));
    $("pe-eliminar").addEventListener("click", eliminar);
    $("pe-historial").addEventListener("click", async () => {
      const r = await Redes.llamar("historial_pendiente", { id: st.editando.id });
      if (r.ok) Redes.mostrarHistorial(`Historial: ${st.editando.titulo}`, r.historial);
    });
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.Pendientes = { nuevo: (preset) => { conectar(); return abrirFormulario(null, preset || {}); }, _st: st };
  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.pendientes = {
    async mostrar() {
      conectar();
      await Redes.llenarProyectos($("pe-f-proyecto"), $("pe-f-proyecto").value, "Todos los proyectos");
      cargar();
    },
  };
})();
