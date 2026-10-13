/* Vista "Backup" del módulo de redes (fase 7.4).
 *
 * Administradores: "Crear respaldo" (todos los proyectos en .json + el esquema en .sql con pg_dump),
 * lista de respaldos de la carpeta del servidor, "Restaurar" un proyecto como copia nueva y
 * "Descargar" el archivo. Cualquier usuario: exportar un proyecto que puede ver a KMZ o GeoJSON.
 * Los archivos se guardan con el diálogo de Windows (api.guardar_archivo), también en el .exe.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const st = { lista: [], restaurando: null, conectado: false, admin: false };
  const estado = (t, tipo) => Redes.estadoEn($("bk-estado"), t, tipo);
  const tamano = (n) => (n == null ? "—" : n < 1048576 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`);

  async function cargar() {
    st.admin = !!(Redes.estado && Redes.estado.puede && Redes.estado.puede.administrar);
    $("bk-crear").hidden = !st.admin;
    $("bk-seccion-respaldos").hidden = !st.admin;
    $("bk-seccion-verificar").hidden = !st.admin;
    await Redes.llenarProyectos($("bk-proyecto"), $("bk-proyecto").value || null);
    if (!st.admin) {
      $("bk-carpeta").textContent = "Crear y restaurar respaldos: solo administradores";
      estado("");
      return;
    }
    estado("Cargando respaldos…", "cargando");
    const r = await Redes.llamar("respaldos");
    if (!r.ok) { estado(r.error, "error"); return; }
    st.lista = r.respaldos;
    $("bk-carpeta").textContent = `Carpeta: ${r.carpeta}${r.pg_dump ? "" : " · pg_dump no encontrado: solo respaldo .json"}`;
    $("bk-carpeta").title = r.pg_dump ? `pg_dump: ${r.pg_dump}` : "";
    estado(`${st.lista.length} respaldo${st.lista.length === 1 ? "" : "s"}`);
    pintar();
  }

  function pintar() {
    $("bk-filas").innerHTML = st.lista.map((b) => `<tr>
      <td>${esc(Redes.fecha(b.fecha))}${b.creado_por ? `<div class="nota">${esc(b.creado_por)}</div>` : ""}</td>
      <td><code>${esc(b.archivo)}</code>${b.error ? `<div class="nota error">${esc(b.error)}</div>` : ""}</td>
      <td>${b.proyectos.length}<div class="nota">${esc(b.proyectos.slice(0, 4).map((p) => p.codigo).join(", "))}${b.proyectos.length > 4 ? "…" : ""}</div></td>
      <td>${tamano(b.tamano)}</td>
      <td>${b.sql ? `${tamano(b.sql_tamano)} <button type="button" class="btn btn-chico" data-bk-bajar="${esc(b.sql)}">Descargar .sql</button>` : "—"}</td>
      <td class="acciones">${b.proyectos.length ? `<button type="button" class="btn btn-chico" data-bk-restaurar="${esc(b.archivo)}">Restaurar…</button>` : ""}
        <button type="button" class="btn btn-chico" data-bk-bajar="${esc(b.archivo)}">Descargar</button></td>
    </tr>`).join("") || `<tr><td colspan="6" class="vacio">Todavía no hay respaldos. Use <b>Crear respaldo</b>.</td></tr>`;
  }

  async function crear() {
    if (!(await Redes.confirmar("¿Crear un respaldo de todos los proyectos ahora?", "Crear respaldo"))) return;
    $("bk-crear").disabled = true;
    estado("Creando el respaldo (puede tardar un poco)…", "cargando");
    const r = await Redes.llamar("crear_respaldo");
    $("bk-crear").disabled = false;
    if (!r.ok) { estado(r.error, "error"); return; }
    st.lista = r.respaldos;
    pintar();
    estado(`Respaldo creado: ${r.creado}${r.aviso ? ` · ${r.aviso}` : ""}`, r.aviso ? "error" : "ok");
  }

  function abrirRestaurar(archivo) {
    const b = st.lista.find((x) => x.archivo === archivo);
    if (!b) return;
    st.restaurando = b;
    $("bk-rest-titulo").textContent = `Restaurar desde ${b.archivo}`;
    $("bk-rest-lista").innerHTML = b.proyectos.map((p, i) => `<label class="bk-rest-opcion"><input type="radio" name="bk-rest" value="${p.indice}" ${i === 0 ? "checked" : ""}>
      <b>${esc(p.nombre)}</b> <span class="nota">(${esc(p.codigo)}) · ${p.elementos} elementos · ${p.cables} cables</span></label>`).join("");
    Redes.estadoEn($("bk-rest-estado"), "");
    $("modal-restaurar").hidden = false;
  }

  async function restaurar() {
    const b = st.restaurando, elegido = document.querySelector("input[name=bk-rest]:checked");
    if (!b || !elegido) return;
    const p = b.proyectos.find((x) => x.indice === Number(elegido.value));
    if (!(await Redes.confirmar(`¿Restaurar "${p.nombre}" del respaldo del ${Redes.fecha(b.fecha)} como un proyecto NUEVO? El proyecto actual no se toca.`,
                                "Restaurar como copia"))) return;
    Redes.estadoEn($("bk-rest-estado"), "Restaurando…", "cargando");
    const r = await Redes.llamar("restaurar_respaldo", { archivo: b.archivo, indice: p.indice });
    if (!r.ok) { Redes.estadoEn($("bk-rest-estado"), r.error, "error"); return; }
    $("modal-restaurar").hidden = true;
    await Redes.proyectosVisibles(true);
    await Redes.llenarProyectos($("bk-proyecto"), $("bk-proyecto").value);
    estado(`Proyecto restaurado como "${r.proyecto.nombre}" (${r.proyecto.codigo}): está en Proyectos`, "ok");
  }

  async function guardar(r) {
    if (!r.ok) { estado(r.error, "error"); return; }
    const g = await Redes.guardarArchivo(r.nombre, r.datos, r.tipo);
    if (g.ok) estado(`Guardado: ${g.ruta}`, "ok");
    else estado(g.cancelado ? "" : g.error, g.cancelado ? "" : "error");
  }

  async function exportar(formato) {
    const id = Number($("bk-proyecto").value);
    if (!id) { estado("Elija el proyecto", "error"); return; }
    estado(`Preparando el ${formato.toUpperCase()}…`, "cargando");
    const r = await Redes.llamar("exportar_proyecto", { proyecto_id: id, formato });
    if (r.ok) estado(`${r.resumen.elementos} elementos, ${r.resumen.cables} cables, ${r.resumen.problemas} problemas: elija dónde guardarlo…`, "cargando");
    await guardar(r);
  }

  /** Section 8: integrity rules of the model over every active project (read only). */
  async function verificarBase() {
    $("bk-verificar").disabled = true;
    $("bk-ver-resumen").textContent = "Revisando…";
    const r = await Redes.llamar("verificar_base");
    $("bk-verificar").disabled = false;
    if (!r.ok) { $("bk-ver-resumen").textContent = r.error; return; }
    $("bk-ver-resumen").textContent = `${r.proyectos} proyecto(s), ${r.reglas.length} reglas · `
      + (r.errores || r.avisos ? `${r.errores} error(es), ${r.avisos} aviso(s)` : "todo en orden") + ` · ${Redes.fecha(r.revisado_en)}`;
    $("bk-ver-tabla").hidden = !r.hallazgos.length;
    $("bk-ver-filas").innerHTML = r.hallazgos.map((h) => `<tr><td><span class="tk-sev ${h.nivel === "error" ? "sev-critica" : "sev-media"}">`
      + `${h.nivel === "error" ? "Error" : "Aviso"}</span></td><td>${esc(h.proyecto)}</td><td>${esc(h.regla)}</td><td>${esc(h.texto)}</td></tr>`).join("");
  }

  function conectar() {
    if (st.conectado) return;
    st.conectado = true;
    $("bk-verificar").addEventListener("click", verificarBase);
    $("bk-recargar").addEventListener("click", cargar);
    $("bk-crear").addEventListener("click", crear);
    $("bk-kmz").addEventListener("click", () => exportar("kmz"));
    $("bk-geojson").addEventListener("click", () => exportar("geojson"));
    $("bk-rest-si").addEventListener("click", restaurar);
    $("bk-filas").addEventListener("click", async (e) => {
      const rest = e.target.closest("[data-bk-restaurar]"), bajar = e.target.closest("[data-bk-bajar]");
      if (rest) abrirRestaurar(rest.dataset.bkRestaurar);
      else if (bajar) {
        estado("Preparando el archivo…", "cargando");
        await guardar(await Redes.llamar("descargar_respaldo", { archivo: bajar.dataset.bkBajar }));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.backup = { mostrar() { conectar(); cargar(); } };
})();
