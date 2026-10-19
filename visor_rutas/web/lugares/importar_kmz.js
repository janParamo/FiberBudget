/* Importar un KMZ a la red (visor v2, fase 5): elegir el archivo, ver qué cambia, aceptar o rechazar, aplicar, publicar y revertir.
 *
 * El botón «Importar KMZ» de la barra abre esta ventana. Un archivo se compara con la red actual (Python: redes/importar_kmz.py) y queda como
 * importación «pendiente» en el árbol de Lugares («Importados (pendientes)») sin tocar nada. En la revisión se ven los conteos (nuevo verde,
 * modificado naranja, eliminado rojo, sin cambios), la lista filtrable y el mapa con los mismos colores; cada cambio o grupo se acepta o se
 * rechaza (lo eliminado empieza rechazado). «Aplicar a la red» deja lo modificado / eliminado como cambios del KMZ y lo nuevo como la capa
 * «Importados (aplicados)»; se puede revertir la última. «Publicar en el presupuesto» (administradores) lo pasa a red_puntos / red_lineas.
 *
 *   ImportarKmz.iniciar({mapa, aviso})   ImportarKmz.abrir()
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const COLOR = { nuevo: "#2ca02c", modificado: "#fb8c00", eliminado: "#e53935", sin_cambios: "#9aa0ab" };
  const ETIQUETA = { nuevo: "Nuevos", modificado: "Modificados", eliminado: "Eliminados", sin_cambios: "Sin cambios" };
  const CAMBIOS = { nombre: "nombre", posicion: "movido", trazo: "trazo", descripcion: "descripción" };
  const POR_PAGINA = 100;
  const ik = { ctx: null, listo: false, importaciones: [], aplicados: [], actual: null, filas: [], total: 0, aceptados: 0, pagina: 0,
               aceptadosTotal: 0, filtro: { clase: "", carpeta: "", texto: "" }, vista: "inicio", resultado: null, estado: "", tipoEstado: "", ocupado: false,
               revision: null, capaAplicados: null, verRevision: true, verAplicados: true, mapaTruncado: false,
               red: { estado: null, resumen: null, quitar: false } };
  const llamar = (m, a) => window.Redes.llamar(m, a);
  const aviso = (t, tipo) => ik.ctx.aviso(t, tipo);
  const puedeEditar = () => !!(window.Redes && window.Redes.estado && window.Redes.estado.puede && window.Redes.estado.puede.editar);
  const esAdmin = () => !!(window.Redes && window.Redes.estado && window.Redes.estado.puede && window.Redes.estado.puede.administrar);
  const corta = (ruta) => String(ruta || "").split("/").slice(-2).join(" / ");
  const num = (n) => Number(n).toLocaleString("en-US");

  // ------------------------------------------------------------------ mapa
  function dibujarElemento(e, color, grupo, pane, opacidad = 1) {
    const g = e.geom;
    if (!g) return null;
    let capa;
    if (g.type === "Point") {
      capa = L.circleMarker([g.coordinates[1], g.coordinates[0]], { radius: 6, color: "#1a1a1a", weight: 1, fillColor: color, fillOpacity: opacidad, opacity: opacidad, pane: "kmzPuntos" });
    } else {
      const partes = g.type === "MultiLineString" ? g.coordinates : (g.type === "Polygon" ? g.coordinates : [g.coordinates]);
      capa = L.polyline(partes.map((l) => l.map(([x, y]) => [y, x])), { color, weight: 4, opacity: opacidad, pane: "kmzLineas" });
    }
    return capa.addTo(grupo);
  }

  async function dibujarRevision() {
    if (ik.revision) { ik.ctx.mapa.removeLayer(ik.revision); ik.revision = null; }
    if (!ik.actual || !ik.verRevision) return;
    const r = await llamar("mapa_importacion_kmz", { id: ik.actual.id, clase: ik.filtro.clase || null, carpeta: ik.filtro.carpeta || null, texto: ik.filtro.texto || null });
    if (!r.ok || !ik.actual) return;
    ik.mapaTruncado = r.truncado;
    ik.revision = L.layerGroup().addTo(ik.ctx.mapa);
    r.elementos.forEach((e) => {
      const capa = dibujarElemento(e, COLOR[e.clase], ik.revision, null, e.aceptado ? 1 : 0.45);
      if (capa) capa.bindTooltip(`${esc(e.nombre)} · ${ETIQUETA[e.clase].toLowerCase()}`, { sticky: true, className: "hover" });
    });
    if (r.truncado) aviso(`En el mapa se dibujan ${num(r.elementos.length)} elementos: filtre por carpeta o clase para ver el resto`);
    pintar();
  }

  function dibujarAplicados() {
    if (ik.capaAplicados) { ik.ctx.mapa.removeLayer(ik.capaAplicados); ik.capaAplicados = null; }
    if (!ik.aplicados.length || !ik.verAplicados) return;
    ik.capaAplicados = L.layerGroup().addTo(ik.ctx.mapa);
    ik.aplicados.forEach((e) => {
      const capa = dibujarElemento(e, "#1f6feb", ik.capaAplicados, null);
      if (capa) capa.bindTooltip(esc(e.nombre), { sticky: true, className: "hover" })
        .bindPopup(`<div class="popup"><h3>${esc(e.nombre)}</h3><div class="tipo">Importado de ${esc(e.archivo)}</div><dl><dt>Carpeta</dt><dd>${esc(corta(e.carpeta))}</dd></dl></div>`);
    });
  }

  function volarA(f) {
    const g = f.geom_nueva || f.geom_actual;
    if (!g) return;
    const mapa = ik.ctx.mapa;
    if (g.type === "Point") mapa.flyTo([g.coordinates[1], g.coordinates[0]], Math.max(mapa.getZoom(), 18), { duration: 0.6 });
    else {
      const partes = g.type === "MultiLineString" || g.type === "Polygon" ? g.coordinates : [g.coordinates];
      mapa.flyToBounds(L.latLngBounds(partes.flat().map(([x, y]) => [y, x])), { padding: [80, 80], maxZoom: 18, duration: 0.6 });
    }
  }

  // ------------------------------------------------------------------ datos
  async function cargarLista() {
    const r = await llamar("importaciones_kmz", {});
    if (r.ok) ik.importaciones = r.importaciones;
    const c = await llamar("capa_importados_kmz", {});
    if (c.ok) { ik.aplicados = c.elementos; dibujarAplicados(); }
    window.Lugares.refrescar();
    pintar();
  }

  async function cargarPagina() {
    if (!ik.actual) return;
    const r = await llamar("importacion_kmz", { id: ik.actual.id, clase: ik.filtro.clase || null, carpeta: ik.filtro.carpeta || null, texto: ik.filtro.texto || null,
                                                 limite: POR_PAGINA, desde: ik.pagina * POR_PAGINA });
    if (!r.ok) { estado(r.error, "error"); return; }
    ik.actual = r.importacion;
    ik.filas = r.filas; ik.total = r.total; ik.aceptados = r.aceptados; ik.aceptadosTotal = r.aceptados_total;
    pintar();
  }

  function estado(texto, tipo = "") { ik.estado = texto; ik.tipoEstado = tipo; pintar(); }

  async function abrirImportacion(id) {
    const r = await llamar("importacion_kmz", { id, limite: POR_PAGINA });
    if (!r.ok) { aviso(r.error, "error"); return; }
    ik.actual = r.importacion;
    ik.filtro = { clase: "", carpeta: "", texto: "" };
    ik.pagina = 0; ik.filas = r.filas; ik.total = r.total; ik.aceptados = r.aceptados; ik.aceptadosTotal = r.aceptados_total; ik.verRevision = true;
    ik.vista = r.importacion.estado === "pendiente" ? "revision" : "resultado";
    ik.resultado = null;
    abrir();
    await dibujarRevision();
  }

  async function subir(archivo) {
    if (!archivo) return;
    ik.ocupado = true;
    estado(`Subiendo ${archivo.name}…`, "cargando");
    const subida = await Redes.subirArchivo(archivo, (p) => estado(`Subiendo ${archivo.name}… ${p} %`, "cargando"));      // by parts: a whole KMZ weighs 20 MB
    if (!subida.ok) { ik.ocupado = false; estado(subida.error, "error"); return; }
    estado(`Leyendo y comparando ${archivo.name}… (un KMZ grande puede tardar un minuto)`, "cargando");
    const r = await llamar("importar_kmz_red", { subida_id: subida.id, nombre: archivo.name });
    ik.ocupado = false;
    if (!r.ok) { estado(r.error, "error"); return; }
    estado("");
    await cargarLista();
    await abrirImportacion(r.importacion.id);
  }

  async function accion(a, b) {
    const imp = ik.actual;
    if (a === "aplicar") {
      if (!(await Redes.confirmar(`¿Aplicar a la red los ${num(ik.aceptadosTotal)} cambios aceptados de «${imp.archivo}»? Lo nuevo se agrega como capa «Importados» y lo modificado o eliminado queda como cambio del KMZ. Se puede revertir.`, "Aplicar"))) return;
      ik.ocupado = true; estado("Aplicando a la red…", "cargando");
      const r = await llamar("aplicar_importacion_kmz", { id: imp.id });
      ik.ocupado = false;
      if (!r.ok) { estado(r.error, "error"); return; }
      ik.actual = r.importacion; ik.vista = "resultado"; ik.resultado = { aplicados: r.aplicados };
      await refrescarRed();
      estado("");
    } else if (a === "descartar") {
      if (!(await Redes.confirmar(`¿Descartar la importación de «${imp.archivo}»? No se cambia nada en la red.`, "Descartar"))) return;
      const r = await llamar("descartar_importacion_kmz", { id: imp.id });
      if (!r.ok) { estado(r.error, "error"); return; }
      cerrarRevision(); await cargarLista();
    } else if (a === "revertir") {
      const id = Number(b || imp.id);
      if (!(await Redes.confirmar("¿Revertir esta importación? Lo modificado o eliminado vuelve a como estaba y lo nuevo sale de la red.", "Revertir"))) return;
      const r = await llamar("revertir_importacion_kmz", { id });
      if (!r.ok) { estado(r.error, "error"); return; }
      if (ik.actual && ik.actual.id === id) { ik.actual = r.importacion; ik.resultado = null; }
      await refrescarRed();
      aviso("Importación revertida", "ok");
    } else if (a === "publicar") {
      const id = Number(b || imp.id);
      if (!(await Redes.confirmar("¿Publicar esta importación en las tablas del PRESUPUESTO (red_puntos / red_lineas)? Desde ese momento los presupuestos usan la red nueva. " +
                                  "Se guarda lo que había para poder revertirlo.", "Publicar"))) return;
      ik.ocupado = true; estado("Publicando en el presupuesto…", "cargando");
      const r = await llamar("publicar_importacion_kmz", { id });
      ik.ocupado = false;
      if (!r.ok) { estado(r.error, "error"); return; }
      if (ik.actual && ik.actual.id === id) ik.actual = r.importacion;
      ik.resultado = { ...(ik.resultado || {}), publicacion: r.resumen };
      await cargarLista();
      estado("");
    } else if (a === "revertir_publicacion") {
      const id = Number(b || imp.id);
      if (!(await Redes.confirmar("¿Quitar esta importación de las tablas del presupuesto? Vuelven a como estaban.", "Revertir publicación"))) return;
      const r = await llamar("revertir_publicacion_kmz", { id });
      if (!r.ok) { estado(r.error, "error"); return; }
      if (ik.actual && ik.actual.id === id) { ik.actual = r.importacion; ik.resultado = null; }
      await cargarLista();
      aviso("Publicación revertida", "ok");
    }
  }

  async function refrescarRed() {
    if (window.KmzCambios) await window.KmzCambios.cargar();         // the changes of the KMZ in force show on the map
    await cargarLista();
  }

  function cerrarRevision() {
    ik.actual = null; ik.filas = []; ik.vista = "inicio"; ik.resultado = null;
    if (ik.revision) { ik.ctx.mapa.removeLayer(ik.revision); ik.revision = null; }
    pintar();
  }

  // ------------------------------------------------------------------ ventana
  function crear() {
    if ($("ik-ventana")) return;
    document.body.insertAdjacentHTML("beforeend", `<aside id="ik-ventana" class="ik-ventana" hidden aria-label="Importar KMZ">
      <header class="ik-cabecera"><h2>Importar KMZ a la red</h2><button type="button" class="btn-icono" data-ik="cerrar" aria-label="Cerrar">✕</button></header>
      <div id="ik-cuerpo" class="ik-cuerpo"></div><input type="file" id="ik-archivo" accept=".kmz,.kml" hidden><input type="file" id="ik-archivo-red" accept=".kmz" hidden></aside>`);
    const v = $("ik-ventana");
    L.DomEvent.disableClickPropagation(v);
    L.DomEvent.disableScrollPropagation(v);
    v.addEventListener("click", alClic);
    v.addEventListener("change", alCambiar);
    v.addEventListener("input", alEscribir);
    $("ik-archivo").addEventListener("change", (e) => { const a = e.target.files && e.target.files[0]; e.target.value = ""; subir(a); });
    $("ik-archivo-red").addEventListener("change", (e) => { const a = e.target.files && e.target.files[0]; e.target.value = ""; subirRed(a); });
  }

  function abrir() {
    if (!window.Redes || !window.Redes.disponible) { aviso("El módulo de redes no está disponible", "error"); return; }
    crear();
    $("ik-ventana").hidden = false;
    pintar();
    cargarEstadoRed();
  }

  function cerrar() { $("ik-ventana").hidden = true; }

  function chips(c) {
    return ["nuevo", "modificado", "eliminado", "sin_cambios"].map((k) => {
      const n = c.por_clase[k];
      const activo = ik.filtro.clase === k;
      return `<button type="button" class="ik-chip${activo ? " activo" : ""}" data-ik="clase" data-clase="${k}" ${k === "sin_cambios" || (k === "eliminado" && ik.actual.modo !== "actualizacion") ? "disabled" : ""}
        style="--c:${COLOR[k]}"><b>${num(n)}</b> ${ETIQUETA[k].toLowerCase()}</button>`;
    }).join("");
  }

  function htmlFila(f) {
    const cambios = (f.props.cambios || []).map((x) => CAMBIOS[x] || x).join(", ");
    const extra = f.clase === "modificado" ? `${cambios}${f.props.dist_m ? ` (${num(f.props.dist_m)} m)` : ""}` : "";
    return `<li class="ik-fila${f.aceptado ? "" : " ik-rechazado"}" data-ik="fila" data-id="${f.id}">
      <input type="checkbox" data-ik="aceptar" data-id="${f.id}" ${f.aceptado ? "checked" : ""} ${ik.actual.estado !== "pendiente" ? "disabled" : ""}>
      <span class="ik-punto" style="background:${COLOR[f.clase]}"></span><span class="ik-nombre"><b>${esc(f.nombre)}</b>
      <span class="nota">${esc(corta(f.carpeta))}${extra ? " · " + esc(extra) : ""}</span></span></li>`;
  }

  function vistaInicio() {
    const filas = ik.importaciones.map((i) => `<li class="ik-hist"><div><b>${esc(i.archivo)}</b>
        <span class="nota">${esc((i.creado_en || "").slice(0, 16).replace("T", " "))} · ${esc(i.usuario || "")} · ${esc({ pendiente: "pendiente", aplicada: "aplicada", revertida: "revertida", descartada: "descartada" }[i.estado])}${i.publicada ? " · publicada" : ""}</span></div>
        <div class="ik-botones">${i.estado === "pendiente" || i.estado === "aplicada" ? `<button type="button" class="btn btn-chico" data-ik="abrir" data-id="${i.id}">${i.estado === "pendiente" ? "Revisar" : "Ver"}</button>` : ""}
        ${i.es_ultima_aplicada && puedeEditar() && !i.publicada ? `<button type="button" class="btn btn-chico" data-ik="revertir" data-id="${i.id}">Revertir</button>` : ""}</div></li>`).join("");
    return `<p class="ik-ayuda">Elija un archivo <b>.kmz</b>: una ruta o elementos nuevos, o el KMZ completo de la red para actualizarla. Antes de cambiar nada se compara con la red actual y se revisa.</p>
      ${puedeEditar() ? `<button type="button" class="btn btn-primario" data-ik="elegir" ${ik.ocupado ? "disabled" : ""}>Elegir archivo KMZ…</button>` : '<p class="nota">Solo un administrador o un editor puede importar.</p>'}
      <h3 class="ik-titulo">Importaciones</h3><ul class="ik-lista">${filas || '<li class="nota">Todavía no se importó nada.</li>'}</ul>${htmlActualizarRed()}`;
  }

  // ------------------------------------------------------------------ actualizar la red (administradores): KMZ nuevo + base del presupuesto
  function htmlActualizarRed() {
    if (!esAdmin()) return "";
    const r = ik.red, k = r.estado && r.estado.kmz, c = r.resumen;
    const lista = (t) => (t || []).map((x) => `<li>${esc(x.nombre || "(sin nombre)")} <span class="nota">${esc(x.carpeta)}</span></li>`).join("");
    const comparacion = c ? `<ul class="ik-resumen">
        <li><b>${num(c.nuevos.puntos)}</b> puntos y <b>${num(c.nuevos.lineas)}</b> líneas del KMZ <b>no están</b> en el presupuesto
          (${num(c.postes_nuevos)} postes, ${num(c.mufas_nuevas)} mufas)</li>
        <li><b>${num(c.sobran.puntos)}</b> puntos y <b>${num(c.sobran.lineas)}</b> líneas del presupuesto ya no están en el KMZ</li>
        ${Object.keys(c.sin_categoria).length ? `<li class="nota">Carpetas del KMZ sin equivalente en el presupuesto (no se pasan): ${esc(Object.keys(c.sin_categoria).join(", "))}</li>` : ""}
        ${c.ejemplos_nuevos.length ? `<li class="nota">Ejemplos nuevos:<ul>${lista(c.ejemplos_nuevos)}</ul></li>` : ""}</ul>
      <label class="nota"><input type="checkbox" data-ik="red_quitar" ${r.quitar ? "checked" : ""}> También quitar del presupuesto lo que el KMZ ya no trae</label>
      <button type="button" class="btn btn-primario" data-ik="red_sincronizar" ${ik.ocupado || (!c.nuevos.puntos && !c.nuevos.lineas && !(r.quitar && (c.sobran.puntos || c.sobran.lineas))) ? "disabled" : ""}>Poner el presupuesto al día</button>` : "";
    const ultima = (r.estado && r.estado.sincronizaciones || []).find((s) => !s.revertida);
    return `<h3 class="ik-titulo">Actualizar la red <span class="nota">(administrador)</span></h3>
      <p class="ik-ayuda">El mapa muestra el KMZ, pero la <b>ruta y el presupuesto usan la base del presupuesto</b>. Si subes un KMZ nuevo, después hay que ponerla al día o los postes y mufas nuevos no se tomarán en cuenta.</p>
      <p class="nota">KMZ vigente: <b>${esc(k ? (k.archivo || "ninguno") : "…")}</b>${k && k.modificado ? " · " + esc(k.modificado.replace("T", " ")) : ""}</p>
      <div class="ik-botones"><button type="button" class="btn" data-ik="red_subir" ${ik.ocupado ? "disabled" : ""}>Subir KMZ nuevo (reemplaza la red)…</button>
        <button type="button" class="btn" data-ik="red_comparar" ${ik.ocupado ? "disabled" : ""}>Comparar con el presupuesto</button></div>
      ${comparacion}
      ${ultima ? `<p class="nota">Última sincronización: ${esc(ultima.archivo)} (+${num(ultima.insertados.puntos + ultima.insertados.lineas)} / −${num(ultima.eliminados.puntos + ultima.eliminados.lineas)})
        <button type="button" class="btn btn-chico" data-ik="red_revertir" data-id="${esc(ultima.id)}">Revertir</button></p>` : ""}`;
  }

  async function cargarEstadoRed() {
    if (!esAdmin()) return;
    const r = await llamar("estado_actualizar_red", {});
    if (r.ok) { ik.red.estado = r; pintar(); }
  }

  async function accionRed(a, b) {
    if (a === "red_subir") { $("ik-archivo-red").click(); return; }
    if (a === "red_comparar") {
      ik.ocupado = true; estado("Comparando el KMZ con el presupuesto…", "cargando");
      const r = await llamar("comparar_red_presupuesto", {});
      ik.ocupado = false;
      if (!r.ok) { estado(r.error, "error"); return; }
      ik.red.resumen = r.resumen; estado("");
    } else if (a === "red_sincronizar") {
      const c = ik.red.resumen, quitar = !!ik.red.quitar;
      if (!(await Redes.confirmar(`¿Poner el presupuesto al día con «${c.archivo}»? Se agregan ${num(c.nuevos.puntos)} puntos y ${num(c.nuevos.lineas)} líneas` +
        `${quitar ? ` y se quitan ${num(c.sobran.puntos)} puntos y ${num(c.sobran.lineas)} líneas` : ""}. Desde ese momento los presupuestos usan esta red. Se guarda lo que había para poder revertirlo.`, "Poner al día"))) return;
      ik.ocupado = true; estado("Actualizando el presupuesto…", "cargando");
      const r = await llamar("sincronizar_red_presupuesto", { quitar });
      ik.ocupado = false;
      if (!r.ok) { estado(r.error, "error"); return; }
      ik.red.resumen = null; estado("");
      aviso(`Presupuesto al día: +${num(r.insertados.puntos + r.insertados.lineas)} elementos${quitar ? `, −${num(r.eliminados.puntos + r.eliminados.lineas)}` : ""}`, "ok");
      await cargarEstadoRed();
    } else if (a === "red_revertir") {
      if (!(await Redes.confirmar("¿Revertir la última sincronización? Lo que agregó sale del presupuesto y lo que quitó vuelve.", "Revertir"))) return;
      const r = await llamar("revertir_sincronizacion_red", { id: b });
      if (!r.ok) { estado(r.error, "error"); return; }
      ik.red.resumen = null; aviso("Sincronización revertida", "ok");
      await cargarEstadoRed();
    }
  }

  async function subirRed(archivo) {
    if (!archivo) return;
    if (!(await Redes.confirmar(`¿Reemplazar la red por «${archivo.name}»? El KMZ actual se guarda aparte (carpeta «anteriores») y todos verán la red nueva al abrir el visor.`, "Reemplazar"))) return;
    ik.ocupado = true;
    estado(`Subiendo ${archivo.name}…`, "cargando");
    const subida = await Redes.subirArchivo(archivo, (p) => estado(`Subiendo ${archivo.name}… ${p} %`, "cargando"));
    if (!subida.ok) { ik.ocupado = false; estado(subida.error, "error"); return; }
    estado("Leyendo el KMZ y armando el mapa… (unos 20 segundos)", "cargando");
    const r = await llamar("subir_kmz_red", { subida_id: subida.id, nombre: archivo.name });
    ik.ocupado = false;
    if (!r.ok) { estado(r.error, "error"); return; }
    ik.red.resumen = null; estado("");
    await cargarEstadoRed();
    if (await Redes.confirmar(`Listo: «${r.archivo}» con ${num(r.elementos)} elementos es la red vigente. Falta «Comparar con el presupuesto» y ponerlo al día. ¿Recargar el visor ahora para ver la red nueva en el mapa?`, "Recargar")) location.reload();
  }

  function vistaRevision() {
    const imp = ik.actual, c = imp.conteos;
    const carpetas = Object.entries(c.carpetas).filter(([, v]) => v.nuevo || v.modificado || v.eliminado);
    const paginas = Math.max(1, Math.ceil(ik.total / POR_PAGINA));
    const avisos = (c.avisos || []).map((a) => `<div class="nota error">${esc(a)}</div>`).join("");
    return `<div class="ik-archivo"><b>${esc(imp.archivo)}</b> <span class="nota">${num(c.elementos_archivo)} elementos · red actual: ${num(c.elementos_red)}</span></div>
      <fieldset class="ik-modo"><legend>Qué es este archivo</legend>
        <label><input type="radio" name="ik-modo" value="nueva" data-ik="modo" ${imp.modo === "nueva" ? "checked" : ""}> Una ruta o elementos nuevos <span class="nota">(lo que falta en el archivo no se toca)</span></label>
        <label><input type="radio" name="ik-modo" value="actualizacion" data-ik="modo" ${imp.modo === "actualizacion" ? "checked" : ""}> Actualización de toda la red <span class="nota">(también detecta lo eliminado)</span></label>
        <div class="nota">Sugerido: ${imp.modo_sugerido === "nueva" ? "nueva ruta" : "actualización de la red"}</div></fieldset>${avisos}
      <div class="ik-chips">${chips(c)}</div>
      <div class="ik-filtros"><select data-ik="carpeta"><option value="">Todas las carpetas</option>${carpetas.map(([k, v]) =>
        `<option value="${esc(k)}" ${ik.filtro.carpeta === k ? "selected" : ""}>${esc(corta(k))} (${num((v.nuevo || 0) + (v.modificado || 0) + (imp.modo === "actualizacion" ? v.eliminado || 0 : 0))})</option>`).join("")}</select>
        <input type="search" data-ik="texto" placeholder="Buscar por nombre" value="${esc(ik.filtro.texto)}"></div>
      <div class="ik-masivo"><span class="nota">${num(ik.total)} mostrados · ${num(ik.aceptados)} aceptados</span>
        <button type="button" class="btn btn-chico" data-ik="aceptar_todos">Aceptar los mostrados</button><button type="button" class="btn btn-chico" data-ik="rechazar_todos">Rechazar los mostrados</button>
        <label class="nota"><input type="checkbox" data-ik="ver_mapa" ${ik.verRevision ? "checked" : ""}> en el mapa</label></div>
      <ul class="ik-lista ik-filas">${ik.filas.map(htmlFila).join("") || '<li class="nota">Nada con ese filtro.</li>'}</ul>
      <div class="ik-paginas"><button type="button" class="btn btn-chico" data-ik="anterior" ${ik.pagina <= 0 ? "disabled" : ""}>‹</button><span class="nota">${ik.pagina + 1} / ${paginas}</span>
        <button type="button" class="btn btn-chico" data-ik="siguiente" ${ik.pagina + 1 >= paginas ? "disabled" : ""}>›</button></div>
      <div class="ik-pie"><button type="button" class="btn btn-primario" data-ik="aplicar" ${ik.ocupado ? "disabled" : ""}>Aplicar a la red</button>
        <button type="button" class="btn" data-ik="descartar">Descartar</button><button type="button" class="btn" data-ik="volver">Volver</button></div>`;
  }

  function vistaResultado() {
    const imp = ik.actual, ap = ik.resultado && ik.resultado.aplicados, pub = ik.resultado && ik.resultado.publicacion;
    const lineasPub = pub ? `<ul class="ik-resumen"><li>${num(pub.insertados)} agregados al presupuesto, ${num(pub.modificados)} modificados, ${num(pub.eliminados)} eliminados</li>
      ${pub.sin_categoria.length ? `<li class="nota error">Sin categoría equivalente en el presupuesto (no se publicaron): ${esc(pub.sin_categoria.join(", "))}</li>` : ""}
      ${pub.no_encontrados.length ? `<li class="nota error">No se encontraron en el presupuesto (no se cambiaron): ${esc(pub.no_encontrados.slice(0, 10).join(", "))}${pub.no_encontrados.length > 10 ? "…" : ""}</li>` : ""}</ul>` : "";
    return `<div class="ik-archivo"><b>${esc(imp.archivo)}</b> <span class="nota">${esc(imp.estado)}${imp.publicada ? " · publicada en el presupuesto" : ""}</span></div>
      ${ap ? `<p>Aplicado a la red: ${num(ap.nuevo)} nuevos, ${num(ap.modificado)} modificados, ${num(ap.eliminado)} eliminados.</p>` : ""}${lineasPub}
      <p class="nota">El archivo KMZ original no se modifica. Lo nuevo está en «Importados (aplicados)» del árbol de Lugares; lo modificado o eliminado, en «Cambios al KMZ».
        ${imp.publicada ? "" : "El presupuesto sigue usando la red como estaba hasta que se publique."}</p>
      <div class="ik-pie">${imp.estado === "aplicada" && esAdmin() && !imp.publicada ? '<button type="button" class="btn btn-primario" data-ik="publicar">Publicar en el presupuesto</button>' : ""}
        ${imp.estado === "aplicada" && imp.publicada && esAdmin() ? '<button type="button" class="btn" data-ik="revertir_publicacion">Revertir la publicación</button>' : ""}
        ${imp.estado === "aplicada" && !imp.publicada && puedeEditar() && ik.importaciones.find((i) => i.id === imp.id && i.es_ultima_aplicada) ? '<button type="button" class="btn" data-ik="revertir">Revertir importación</button>' : ""}
        <button type="button" class="btn" data-ik="volver">Volver</button></div>`;
  }

  function pintar() {
    const cuerpo = $("ik-cuerpo");
    if (!cuerpo) return;
    const pie = ik.estado ? `<div class="nota ik-estado ${esc(ik.tipoEstado)}">${ik.tipoEstado === "cargando" ? '<span class="spinner"></span> ' : ""}${esc(ik.estado)}</div>` : "";
    cuerpo.innerHTML = (ik.vista === "revision" && ik.actual ? vistaRevision() : ik.vista === "resultado" && ik.actual ? vistaResultado() : vistaInicio()) + pie;
  }

  // ------------------------------------------------------------------ eventos
  async function alClic(e) {
    const b = e.target.closest("[data-ik]");
    if (!b) return;
    const a = b.dataset.ik;
    if (a === "cerrar") cerrar();
    else if (a === "elegir") $("ik-archivo").click();
    else if (a.startsWith("red_") && a !== "red_quitar") accionRed(a, b.dataset.id);
    else if (a === "abrir") abrirImportacion(Number(b.dataset.id));
    else if (a === "volver") { cerrarRevision(); cargarLista(); }
    else if (a === "clase") { ik.filtro.clase = ik.filtro.clase === b.dataset.clase ? "" : b.dataset.clase; ik.pagina = 0; await cargarPagina(); dibujarRevision(); }
    else if (a === "anterior") { ik.pagina--; cargarPagina(); }
    else if (a === "siguiente") { ik.pagina++; cargarPagina(); }
    else if (a === "aceptar_todos" || a === "rechazar_todos") {
      const r = await llamar("aceptar_importacion_kmz", { id: ik.actual.id, aceptado: a === "aceptar_todos", clase: ik.filtro.clase || null, carpeta: ik.filtro.carpeta || null, texto: ik.filtro.texto || null });
      if (!r.ok) { estado(r.error, "error"); return; }
      await cargarPagina(); dibujarRevision();
    } else if (a === "fila" && !e.target.closest("input")) {
      const f = ik.filas.find((x) => x.id === Number(b.dataset.id));
      if (f) volarA(f);
    } else if (["aplicar", "descartar", "revertir", "publicar", "revertir_publicacion"].includes(a)) accion(a, b.dataset.id);
  }

  async function alCambiar(e) {
    const b = e.target.closest("[data-ik]");
    if (!b) return;
    const a = b.dataset.ik;
    if (a === "aceptar") {
      const r = await llamar("aceptar_importacion_kmz", { id: ik.actual.id, aceptado: b.checked, ids: [Number(b.dataset.id)] });
      if (!r.ok) { estado(r.error, "error"); return; }
      const f = ik.filas.find((x) => x.id === Number(b.dataset.id));
      if (f) f.aceptado = b.checked;
      ik.aceptados += b.checked ? 1 : -1;
      ik.aceptadosTotal += b.checked ? 1 : -1;
      pintar(); dibujarRevision();
    } else if (a === "modo") {
      const r = await llamar("modo_importacion_kmz", { id: ik.actual.id, modo: b.value });
      if (!r.ok) { estado(r.error, "error"); return; }
      ik.actual = r.importacion; ik.filtro.clase = ""; ik.pagina = 0;
      await cargarPagina(); dibujarRevision();
    } else if (a === "red_quitar") { ik.red.quitar = b.checked; pintar(); }
    else if (a === "carpeta") { ik.filtro.carpeta = b.value; ik.pagina = 0; await cargarPagina(); dibujarRevision(); }
    else if (a === "ver_mapa") { ik.verRevision = b.checked; dibujarRevision(); }
  }

  let espera = null;
  function alEscribir(e) {
    const b = e.target.closest("[data-ik=texto]");
    if (!b) return;
    clearTimeout(espera);
    espera = setTimeout(async () => { ik.filtro.texto = b.value.trim(); ik.pagina = 0; await cargarPagina(); dibujarRevision(); $("ik-cuerpo").querySelector("[data-ik=texto]").focus(); }, 350);
  }

  // ------------------------------------------------------------------ filas del árbol de Lugares
  function filas() {
    const f = ik.importaciones.filter((i) => i.estado === "pendiente").map((i) => ({ k: `p${i.id}`, nivel: 0, id: i.id }));
    if (ik.aplicados.length) f.push({ k: "capa", nivel: 0 });
    return f;
  }

  function htmlFilaArbol(f, n, top) {
    if (f.k === "capa") {
      return `<div class="lg-fila ext ik-fila-arbol" style="${top}" data-ext="ik" data-ik-arbol="capa" data-fila="${n}" title="Elementos que agregaron las importaciones aplicadas">
        <span class="lg-flecha"></span><input type="checkbox" class="lg-casilla" data-ik-arbol="ver_capa" ${ik.verAplicados ? "checked" : ""}><span class="ik-punto" style="background:#1f6feb"></span>
        <span class="lg-nombre"><b>Importados (aplicados)</b></span><span class="lg-cuenta">${num(ik.aplicados.length)}</span></div>`;
    }
    const i = ik.importaciones.find((x) => x.id === f.id);
    if (!i) return "";
    const total = i.conteos.por_clase.nuevo + i.conteos.por_clase.modificado + (i.modo === "actualizacion" ? i.conteos.por_clase.eliminado : 0);
    return `<div class="lg-fila ext ik-fila-arbol" style="${top}" data-ext="ik" data-ik-arbol="abrir" data-id="${i.id}" data-fila="${n}" title="Revisar y aplicar esta importación">
      <span class="lg-flecha"></span><input type="checkbox" class="lg-casilla" data-ik-arbol="ver_revision" data-id="${i.id}" ${ik.actual && ik.actual.id === i.id && ik.verRevision ? "checked" : ""}>
      <span class="ik-punto" style="background:${COLOR.modificado}"></span><span class="lg-nombre"><b>Importados (pendientes):</b> ${esc(i.archivo)}</span><span class="lg-cuenta">${num(total)}</span></div>`;
  }

  function iniciar(ctx) {
    ik.ctx = ctx;
    window.Lugares.registrarFilas({ id: "ik", filas, html: htmlFilaArbol });
    $("lg-filas").addEventListener("click", (e) => {
      const b = e.target.closest("[data-ik-arbol]");
      if (!b) return;
      const a = b.dataset.ikArbol;
      if (a === "ver_capa") { ik.verAplicados = b.checked; dibujarAplicados(); return; }
      if (a === "ver_revision") {
        if (ik.actual && ik.actual.id === Number(b.dataset.id)) { ik.verRevision = b.checked; dibujarRevision(); window.Lugares.refrescar(); }
        else abrirImportacion(Number(b.dataset.id));
        return;
      }
      if (a === "abrir") abrirImportacion(Number(b.dataset.id));
      else if (a === "capa" && ik.aplicados.length) {
        const pts = ik.aplicados.filter((x) => x.geom).flatMap((x) => (x.geom.type === "Point" ? [[x.geom.coordinates[1], x.geom.coordinates[0]]] :
          (x.geom.type === "MultiLineString" || x.geom.type === "Polygon" ? x.geom.coordinates.flat() : x.geom.coordinates).map(([lon, lat]) => [lat, lon])));
        if (pts.length) ctx.mapa.flyToBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 18, duration: 0.8 });
      }
    });
    window.Redes.cuandoListo(() => { if (window.Redes.disponible) { ik.listo = true; cargarLista(); } });
  }

  window.ImportarKmz = { iniciar, abrir, get estado() { return { importaciones: ik.importaciones.length, aplicados: ik.aplicados.length, vista: ik.vista, listo: ik.listo }; },
                         _ik: ik };
})();
