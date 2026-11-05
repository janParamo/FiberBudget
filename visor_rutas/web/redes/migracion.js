/* Vista "Red existente" (migración Visio, fase 6: cola de corrección y tablero, docs/migracion_visio/PLAN.md §7).
 *
 * Arriba, el avance por zona (proyecto base): mufas migradas, con fusiones conocidas, con supuestos,
 * validadas y editadas. Abajo, la lista ordenada de lo que hay que corregir, con filtros por zona,
 * motivo y texto; clic en una fila abre la mufa en su editor, y una mufa sin ubicar se coloca con
 * un clic en el mapa de su zona. "Exportar a Excel" guarda ambas cosas para Planta Externa.
 * «Actualizar diagramas Visio» (administradores): sube los archivos .vsd / .vsdx / .xlsx (o un .zip) nuevos o corregidos, reemplaza los del mismo nombre y pone al día la base
 * de diagramas con el importador en segundo plano (Redes.llamar("visio_estado" | "visio_subir" | "visio_actualizar" | "visio_progreso")).
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
      <td><span class="mg-barra"><i style="width:${Math.min(100, z.avance)}%"></i></span> ${z.avance} %</td>
      <td>${total ? "" : `<button type="button" class="btn btn-chico" data-mg-esquema="${z.proyecto_id}" title="Mufas y nodos de esta zona en un mapa en blanco">Esquema</button>`}</td></tr>`;
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

  // ------------------------------------------------------------------ actualizar los diagramas Visio subiendo los archivos
  const esAdmin = () => !!(window.Redes && Redes.estado && Redes.estado.puede && Redes.estado.puede.administrar);
  const vis = { subidos: { reemplazados: [], nuevos: [], rechazados: [] }, sondeo: null, ocupado: false, visio: 0 };          // visio: how many Visio files the folder has
  const avisoVisio = (t, tipo) => Redes.estadoEn($("mg-visio-estado"), t, tipo);

  function pintarResumenVisio() {
    const s = vis.subidos;
    const lista = (titulo, items, fila) => (items.length ? `<div class="mg-visio-grupo"><b>${titulo} (${items.length})</b><ul>${items.slice(0, 40).map((x) => `<li>${fila(x)}</li>`).join("")}${items.length > 40 ? `<li class="nota">… y ${items.length - 40} más</li>` : ""}</ul></div>` : "");
    $("mg-visio-resumen").innerHTML = lista("Reemplazados", s.reemplazados, (x) => esc(x)) + lista("Nuevos", s.nuevos, (x) => esc(x))
      + lista("No se subieron", s.rechazados, (x) => `${esc(x.nombre)} <span class="nota">· ${esc(x.motivo)}</span>`) || `<p class="nota">Todavía no se subió ningún archivo en esta sesión. «Actualizar la base de diagramas» también sirve con los archivos que ya están en la carpeta (por ejemplo, tras una corrección del lector de diagramas).</p>`;
    $("mg-visio-actualizar").disabled = vis.ocupado || !(vis.visio > 0 || s.reemplazados.length || s.nuevos.length);          // the folder is what is read, not only what was uploaded now
  }

  function pintarProgresoVisio(a) {
    if (!a) { $("mg-visio-paso").textContent = ""; $("mg-visio-log").textContent = ""; return; }
    $("mg-visio-paso").textContent = a.activa ? (a.paso ? `Paso ${a.paso.n} de ${a.paso.de}: ${a.paso.texto}` : "Arrancando el importador…")
      : a.codigo === 0 ? "Listo: la base de diagramas está al día." : `El importador terminó con error (código ${a.codigo}). Revise el detalle.`;
    $("mg-visio-paso").className = a.activa ? "vp-estado" : a.codigo === 0 ? "vp-estado ok" : "vp-estado error";
    $("mg-visio-log").textContent = (a.ultimas || []).join("\n");
  }

  async function sondearVisio() {
    clearTimeout(vis.sondeo);
    const r = await Redes.llamar("visio_progreso", {});
    if (!r.ok) { avisoVisio(r.error, "error"); vis.ocupado = false; return; }
    pintarProgresoVisio(r.actualizacion);
    if (r.actualizacion && r.actualizacion.activa) { vis.ocupado = true; vis.sondeo = setTimeout(sondearVisio, 2500); }
    else { vis.ocupado = false; pintarResumenVisio(); if (r.actualizacion && r.actualizacion.codigo === 0) avisoVisio("Diagramas actualizados: ábralos de nuevo para ver los cambios.", "ok"); }
  }

  async function abrirVisio() {
    $("modal-mg-visio").hidden = false;
    avisoVisio("");
    const r = await Redes.llamar("visio_estado", {});
    if (!r.ok) { avisoVisio(r.error, "error"); return; }
    $("mg-visio-carpeta").textContent = `${r.archivos} archivo(s) (${r.visio} Visio) en ${r.carpeta}`;
    vis.visio = r.visio;
    pintarResumenVisio();
    pintarProgresoVisio(r.actualizacion);
    if (r.actualizacion && r.actualizacion.activa) { vis.ocupado = true; sondearVisio(); }
  }

  async function subirVisio(archivos) {
    if (!archivos.length || vis.ocupado) return;
    vis.ocupado = true; pintarResumenVisio();
    for (const archivo of archivos) {
      avisoVisio(`Subiendo ${archivo.name}…`, "cargando");
      const subida = await Redes.subirArchivo(archivo, (p) => avisoVisio(`Subiendo ${archivo.name}… ${p} %`, "cargando"));
      if (!subida.ok) { vis.subidos.rechazados.push({ nombre: archivo.name, motivo: subida.error }); continue; }
      const r = await Redes.llamar("visio_subir", { subida_id: subida.id, nombre: archivo.name });
      if (!r.ok) { vis.subidos.rechazados.push({ nombre: archivo.name, motivo: (r.errores && Object.values(r.errores).join(" · ")) || r.error }); continue; }
      vis.subidos.reemplazados.push(...r.reemplazados); vis.subidos.nuevos.push(...r.nuevos); vis.subidos.rechazados.push(...r.rechazados);
    }
    vis.ocupado = false;
    avisoVisio("");
    pintarResumenVisio();
    const r = await Redes.llamar("visio_estado", {});
    if (r.ok) { $("mg-visio-carpeta").textContent = `${r.archivos} archivo(s) (${r.visio} Visio) en ${r.carpeta}`; vis.visio = r.visio; pintarResumenVisio(); }
  }

  async function actualizarVisio() {
    if (!(await Redes.confirmar("¿Poner al día la base de diagramas con los archivos subidos? Se convierten con LibreOffice solo los nuevos o cambiados y se vuelve a publicar la base: tarda varios minutos y mientras tanto los diagramas ya cargados se siguen viendo.", "Actualizar"))) return;
    avisoVisio("Arrancando…", "cargando");
    const r = await Redes.llamar("visio_actualizar", {});
    if (!r.ok) { avisoVisio((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error"); return; }
    avisoVisio("");
    vis.ocupado = true; pintarResumenVisio();
    sondearVisio();
  }

  function conectarVisio() {
    $("mg-visio").addEventListener("click", abrirVisio);
    $("mg-visio-cerrar").addEventListener("click", () => { $("modal-mg-visio").hidden = true; clearTimeout(vis.sondeo); });
    $("mg-visio-subir").addEventListener("click", () => { if (!vis.ocupado) $("mg-visio-archivo").click(); });
    $("mg-visio-archivo").addEventListener("change", (e) => { const a = [...e.target.files]; e.target.value = ""; subirVisio(a); });
    $("mg-visio-actualizar").addEventListener("click", actualizarVisio);
  }

  function conectar() {
    if (st.conectado) return;
    conectarVisio();
    st.conectado = true;
    $("mg-recargar").addEventListener("click", cargar);
    $("mg-esquema").addEventListener("click", () => { if (window.Esquema) window.Esquema.abrir(Number($("mg-f-proyecto").value) || null); });
    $("mg-exportar").addEventListener("click", exportar);
    ["mg-f-proyecto", "mg-f-motivo"].forEach((id) => $(id).addEventListener("change", cargarCola));
    let espera = null;
    $("mg-f-texto").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(cargarCola, 300); });
    $("mg-zonas").addEventListener("click", (e) => {
      const esquema = e.target.closest("[data-mg-esquema]");
      if (esquema) { if (window.Esquema) window.Esquema.abrir(Number(esquema.dataset.mgEsquema)); return; }
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
  window.RedesVistas.migracion = { mostrar() { conectar(); $("mg-visio").hidden = !esAdmin(); cargar(); } };
  window.MigracionVisio = { _st: st, cargar, _subirVisio: subirVisio, abrir() { conectar(); return abrirVisio(); } };
})();
