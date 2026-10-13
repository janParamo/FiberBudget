/* Vista "Problemas" del módulo de redes (fase 7.1) y su ventana de alta / edición.
 *
 * Lista con filtros (proyecto, estado, severidad, texto); cada problema está ligado a un elemento o
 * cable de un proyecto, con severidad, estado, descripción y fotos. Problemas.nuevo({proyecto_id,
 * elemento_id | cable_id}) y Problemas.abrir(id) los usa también el editor de mapa (inspector y
 * popups de los íconos de alerta). Al guardar avisa con el evento "problemas-cambiaron".
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const SEVERIDAD = { baja: "Baja", media: "Media", alta: "Alta", critica: "Crítica" };
  const ESTADO = { abierto: "Abierto", en_proceso: "En proceso", cerrado: "Cerrado" };
  const CAMPOS = ["titulo", "proyecto", "vinculo", "severidad", "descripcion"];      // (pb-estado is the view's status line)
  const st = { lista: [], editando: null, ref: null, fotos: [], nuevas: [], quitar: new Set(), conectado: false };
  const estado = (t, tipo) => Redes.estadoEn($("pb-estado"), t, tipo);
  const formEstado = (t, tipo) => Redes.estadoEn($("pb-form-estado"), t, tipo);

  // ------------------------------------------------------------------ lista
  async function cargar() {
    estado("Cargando problemas…", "cargando");
    const f = { proyecto_id: $("pb-f-proyecto").value || null, estado: $("pb-f-estado").value || null,
                severidad: $("pb-f-severidad").value || null, texto: $("pb-f-texto").value.trim() || null };
    const r = await Redes.llamar("problemas", f);
    if (!r.ok) { estado(r.error, "error"); $("pb-filas").innerHTML = ""; return; }
    st.lista = r.problemas;
    estado(`${st.lista.length} problema${st.lista.length === 1 ? "" : "s"}`);
    pintar();
  }

  function pintar() {
    $("pb-filas").innerHTML = st.lista.map((p) => `<tr class="${p.estado === "cerrado" ? "inactivo" : ""}" data-pb="${p.id}">
      <td class="tk-mini">${p.miniatura ? `<img src="${p.miniatura}" alt="">` : `<span class="tk-alerta sev-${p.severidad}">⚠</span>`}</td>
      <td><b>${esc(p.titulo)}</b>${p.n_fotos ? ` <span class="nota">· ${p.n_fotos} foto${p.n_fotos === 1 ? "" : "s"}</span>` : ""}
        ${p.descripcion ? `<div class="nota tk-desc">${esc(p.descripcion.slice(0, 140))}</div>` : ""}</td>
      <td>${esc(p.proyecto)}</td><td>${esc(p.vinculo)}</td>
      <td><span class="tk-sev sev-${p.severidad}">${SEVERIDAD[p.severidad]}</span></td>
      <td><span class="tk-est est-${p.estado}">${ESTADO[p.estado]}</span></td>
      <td>${esc(p.creado_por || "")}<div class="nota">${esc(Redes.fecha(p.creado_en))}</div></td>
      <td class="acciones"><button type="button" class="btn btn-chico" data-pb-mapa="${p.id}" title="Ver en el mapa del proyecto">Mapa</button></td>
    </tr>`).join("") || `<tr><td colspan="8" class="vacio">Ningún problema con estos filtros.</td></tr>`;
  }

  // ------------------------------------------------------------------ ventana
  async function cargarReferencias(proyectoId, vinculo) {
    st.ref = null;
    $("pb-vinculo").innerHTML = "";
    if (!proyectoId) return;
    const r = await Redes.llamar("referencias_proyecto", { proyecto_id: Number(proyectoId) });
    if (!r.ok) { formEstado(r.error, "error"); return; }
    st.ref = r;
    $("pb-vinculo").innerHTML = Redes.opcionesVinculo(r, "Elija el elemento o cable…");
    if (vinculo) $("pb-vinculo").value = vinculo;
  }

  function pintarFotos() {
    const existentes = st.fotos.filter((f) => !st.quitar.has(f.id)).map((f) => `<figure class="tk-foto">
        <img src="${f.miniatura}" alt="Foto" data-pb-ver="${f.id}" title="Ver la foto completa">
        ${puedeEditar() ? `<button type="button" class="btn-icono" data-pb-quitar="${f.id}" title="Quitar la foto" aria-label="Quitar">✕</button>` : ""}</figure>`);
    const nuevas = st.nuevas.map((url, i) => `<figure class="tk-foto nueva"><img src="${url}" alt="Foto nueva">
        <button type="button" class="btn-icono" data-pb-quitar-nueva="${i}" title="Quitar" aria-label="Quitar">✕</button></figure>`);
    $("pb-fotos").innerHTML = existentes.concat(nuevas).join("") || `<span class="nota">Sin fotos</span>`;
  }

  const puedeEditar = () => !st.editando || st.editando.puede_editar;

  async function abrirFormulario(problema, preset = {}) {
    st.editando = problema || null;
    st.fotos = problema ? problema.fotos || [] : [];
    st.nuevas = [];
    st.quitar = new Set();
    $("pb-modal-titulo").textContent = problema ? `Problema: ${problema.titulo}` : "Reportar problema";
    Redes.marcarErrores("pb-", CAMPOS, null);
    formEstado("");
    $("pb-fotos-error").textContent = "";
    $("pb-titulo").value = problema ? problema.titulo : "";
    $("pb-severidad").value = problema ? problema.severidad : "media";
    $("pb-estado-sel").value = problema ? problema.estado : "abierto";
    $("pb-descripcion").value = problema ? problema.descripcion || "" : "";
    const proyecto = problema ? problema.proyecto_id : preset.proyecto_id || $("pb-f-proyecto").value || "";
    await Redes.llenarProyectos($("pb-proyecto"), proyecto, "Elija el proyecto…");
    $("pb-proyecto").disabled = !!problema;
    const vinculo = problema ? (problema.elemento_id ? `e:${problema.elemento_id}` : `c:${problema.cable_id}`)
      : preset.elemento_id ? `e:${preset.elemento_id}` : preset.cable_id ? `c:${preset.cable_id}` : "";
    await cargarReferencias($("pb-proyecto").value, vinculo);
    const editable = puedeEditar();
    ["pb-titulo", "pb-vinculo", "pb-severidad", "pb-estado-sel", "pb-descripcion", "pb-fotos-archivo"].forEach((id) => { $(id).disabled = !editable; });
    $("pb-guardar").hidden = !editable;
    $("pb-eliminar").hidden = !problema || !editable;
    $("pb-historial").hidden = $("pb-mapa").hidden = !problema;
    $("pb-info").textContent = problema ? `Reportado por ${problema.creado_por || "—"} el ${Redes.fecha(problema.creado_en)}`
      + (problema.actualizado_por ? ` · último cambio: ${problema.actualizado_por}, ${Redes.fecha(problema.actualizado_en)}` : "")
      + (problema.cerrado_en ? ` · cerrado el ${Redes.fecha(problema.cerrado_en)}` : "") + (editable ? "" : " · solo lectura") : "";
    pintarFotos();
    $("modal-problema").hidden = false;
    $("pb-titulo").focus();
  }

  async function abrir(id) {
    const r = await Redes.llamar("problema", { id });
    if (!r.ok) { (window.visor ? window.visor.mensaje : alert)(r.error, "error"); return; }
    await abrirFormulario(r.problema);
  }

  async function agregarFotos(ev) {
    const archivos = [...ev.target.files];
    ev.target.value = "";
    $("pb-fotos-error").textContent = "";
    for (const a of archivos) {
      if (a.size > 2 * 1024 * 1024) { $("pb-fotos-error").textContent = `${a.name}: pesa más de 2 MB`; continue; }
      st.nuevas.push(await Redes.leerArchivo(a));
    }
    const total = st.fotos.filter((f) => !st.quitar.has(f.id)).length + st.nuevas.length;
    if (total > 6) { st.nuevas = st.nuevas.slice(0, Math.max(0, 6 - (total - st.nuevas.length))); $("pb-fotos-error").textContent = "Máximo 6 fotos por problema"; }
    pintarFotos();
  }

  async function guardar(ev) {
    ev.preventDefault();
    const [tipo, id] = ($("pb-vinculo").value || ":").split(":");
    const datos = { proyecto_id: Number($("pb-proyecto").value) || null, titulo: $("pb-titulo").value, severidad: $("pb-severidad").value,
                    estado: $("pb-estado-sel").value, descripcion: $("pb-descripcion").value,
                    elemento_id: tipo === "e" ? Number(id) : null, cable_id: tipo === "c" ? Number(id) : null,
                    fotos_nuevas: st.nuevas, fotos_quitar: [...st.quitar] };
    if (st.editando) Object.assign(datos, { id: st.editando.id, version: st.editando.version });
    if (!datos.proyecto_id) { Redes.marcarErrores("pb-", CAMPOS, { proyecto: "elija el proyecto" }); return; }
    Redes.marcarErrores("pb-", CAMPOS, null);
    formEstado("Guardando…", "cargando");
    $("pb-guardar").disabled = true;
    const r = await Redes.llamar("guardar_problema", { datos });
    $("pb-guardar").disabled = false;
    if (!r.ok) {
      const e = r.errores || {};
      Redes.marcarErrores("pb-", CAMPOS, e);
      if (e.fotos) $("pb-fotos-error").textContent = e.fotos;
      formEstado(r.error, "error");
      return;
    }
    $("modal-problema").hidden = true;
    avisar(r.problema.proyecto_id);
    if (window.visor) window.visor.mensaje(`Problema "${r.problema.titulo}" guardado`, "ok");
  }

  function avisar(proyectoId) {
    document.dispatchEvent(new CustomEvent("problemas-cambiaron", { detail: { proyecto_id: proyectoId } }));
    if (!$("vista-problemas").hidden) cargar();
  }

  async function eliminar() {
    const p = st.editando;
    if (!p || !(await Redes.confirmar(`¿Eliminar el problema "${p.titulo}"? (Queda en el historial)`, "Eliminar"))) return;
    const r = await Redes.llamar("eliminar_problema", { id: p.id, version: p.version });
    if (!r.ok) { formEstado(r.error, "error"); return; }
    $("modal-problema").hidden = true;
    avisar(p.proyecto_id);
  }

  async function verFoto(id) {
    const r = await Redes.llamar("foto_problema", { id });
    if (!r.ok) { formEstado(r.error, "error"); return; }
    $("tk-foto-img").src = r.imagen;
    $("modal-foto").hidden = false;
  }

  async function verEnMapa(p) {
    if (!p || !window.EditorRed || !window.EditorRed.mostrarProblema) return;
    $("modal-problema").hidden = true;
    await window.EditorRed.mostrarProblema(p);
  }

  // ------------------------------------------------------------------ eventos
  function conectar() {
    if (st.conectado) return;
    st.conectado = true;
    $("pb-recargar").addEventListener("click", cargar);
    $("pb-nuevo").addEventListener("click", () => abrirFormulario(null));
    ["pb-f-proyecto", "pb-f-estado", "pb-f-severidad"].forEach((id) => $(id).addEventListener("change", cargar));
    let espera = null;
    $("pb-f-texto").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(cargar, 300); });
    $("pb-filas").addEventListener("click", (e) => {
      const mapa = e.target.closest("[data-pb-mapa]");
      if (mapa) { verEnMapa(st.lista.find((p) => p.id === Number(mapa.dataset.pbMapa))); return; }
      const fila = e.target.closest("[data-pb]");
      if (fila) abrir(Number(fila.dataset.pb));
    });
    $("pb-form").addEventListener("submit", guardar);
    $("pb-proyecto").addEventListener("change", () => cargarReferencias($("pb-proyecto").value));
    $("pb-fotos-archivo").addEventListener("change", agregarFotos);
    $("pb-fotos").addEventListener("click", (e) => {
      const ver = e.target.closest("[data-pb-ver]"), q = e.target.closest("[data-pb-quitar]"), qn = e.target.closest("[data-pb-quitar-nueva]");
      if (ver) verFoto(Number(ver.dataset.pbVer));
      else if (q) { st.quitar.add(Number(q.dataset.pbQuitar)); pintarFotos(); }
      else if (qn) { st.nuevas.splice(Number(qn.dataset.pbQuitarNueva), 1); pintarFotos(); }
    });
    $("pb-eliminar").addEventListener("click", eliminar);
    $("pb-mapa").addEventListener("click", () => verEnMapa(st.editando));
    $("pb-historial").addEventListener("click", async () => {
      const r = await Redes.llamar("historial_problema", { id: st.editando.id });
      if (r.ok) Redes.mostrarHistorial(`Historial: ${st.editando.titulo}`, r.historial);
    });
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.Problemas = { nuevo: (preset) => { conectar(); return abrirFormulario(null, preset || {}); }, abrir: (id) => { conectar(); return abrir(id); },
                       _st: st };
  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.problemas = {
    async mostrar() {
      conectar();
      await Redes.llenarProyectos($("pb-f-proyecto"), $("pb-f-proyecto").value, "Todos los proyectos");
      cargar();
    },
  };
})();
