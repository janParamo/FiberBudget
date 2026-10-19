/* Coordenadas masivas (visor v2, fase 6): leer muchas coordenadas de un archivo y calcular el presupuesto de cada una.
 *
 * El botón «Coordenadas masivas» de la barra abre una ventana: se elige un archivo Excel, CSV, Word o texto (o se pega el texto) y Python extrae las
 * coordenadas (visor_rutas/masivas.py). La vista previa marca las inválidas, las que están al revés, las que caen fuera de Nicaragua y las
 * duplicadas, deja corregir cada una y muestra los puntos en el mapa con su número. «Calcular» arranca el lote en segundo plano (un presupuesto
 * aproximado por punto, con un límite de rutas de Google por minuto), con barra de progreso y cancelar. La tabla de resultados se ordena y un clic en una
 * fila muestra su ruta en el mapa. Al terminar: abrir la carpeta con los Excel (o bajarlos en un .zip si se usa el servidor), guardar como proyecto o
 * guardar en Mis lugares.
 *
 *   Masivas.iniciar({mapa, api(), aviso})   Masivas.abrir()
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ESTADOS = { ok: ["válida", "#2ca02c"], invertida: ["al revés", "#fb8c00"], fuera: ["fuera de Nicaragua", "#e53935"], invalida: ["no válida", "#e53935"], duplicada: ["duplicada", "#9aa0ab"] };
  const num = (n, d = 0) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d }));
  const ms = { ctx: null, vista: "inicio", nombre: "", formato: "", puntos: [], avisos: [], lote: null, resultados: [], sondeo: null, orden: { campo: "n", dir: 1 },
               estado: "", tipoEstado: "", capa: null, capaRuta: null, modo: "local", conRutas: true, ocupado: false, seleccionado: null };
  const llamar = (m, a) => window.Redes.llamar(m, a);
  const aviso = (t, tipo) => ms.ctx.aviso(t, tipo);

  // ------------------------------------------------------------------ mapa
  function dibujarPuntos() {
    if (ms.capa) { ms.ctx.mapa.removeLayer(ms.capa); ms.capa = null; }
    if (!ms.puntos.length || ms.vista === "inicio") return;
    ms.capa = L.layerGroup().addTo(ms.ctx.mapa);
    ms.puntos.filter((p) => p.lat !== null && p.lon !== null).forEach((p) => {
      const color = p.incluir ? "#1f6feb" : "#9aa0ab";
      L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "icono", iconSize: [26, 26], iconAnchor: [13, 13], html: `<div class="ms-num" style="background:${color}">${p.n}</div>` }) })
        .bindTooltip(`${p.n}. ${esc(p.nombre || p.texto)}`, { direction: "top", className: "hover" }).addTo(ms.capa);
    });
  }

  function ajustarMapa() {
    const pts = ms.puntos.filter((p) => p.lat !== null && p.lon !== null).map((p) => [p.lat, p.lon]);
    if (pts.length) ms.ctx.mapa.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 17 });
  }

  function mostrarRuta(r) {
    if (ms.capaRuta) { ms.ctx.mapa.removeLayer(ms.capaRuta); ms.capaRuta = null; }
    if (!r || !r.ruta) return;
    ms.capaRuta = L.layerGroup().addTo(ms.ctx.mapa);
    const linea = L.polyline(r.ruta, { color: "#ffe600", weight: 6 }).bindTooltip(`Ruta de ${esc(r.nombre || r.n)}: ${num(r.distancia_m, 1)} m`, { sticky: true }).addTo(ms.capaRuta);
    L.circleMarker([r.conexion_lat, r.conexion_lon], { radius: 8, color: "#1a1a1a", weight: 2, fillColor: "#ff8c00", fillOpacity: 1 }).bindTooltip(esc(r.conexion), { permanent: true, direction: "top" }).addTo(ms.capaRuta);
    L.circleMarker([r.lat, r.lon], { radius: 8, color: "#1a1a1a", weight: 2, fillColor: "#2ca02c", fillOpacity: 1 }).addTo(ms.capaRuta);
    ms.ctx.mapa.fitBounds(linea.getBounds().extend([r.lat, r.lon]), { padding: [80, 80], maxZoom: 18 });
  }

  // ------------------------------------------------------------------ pasos
  const estado = (texto, tipo = "") => { ms.estado = texto; ms.tipoEstado = tipo; pintar(); };

  async function leer(nombre, base64, subidaId) {
    ms.ocupado = true;
    estado(`Leyendo ${nombre}…`, "cargando");
    const r = await ms.ctx.api().masivas_leer(nombre, base64 || "", subidaId || null).catch((e) => ({ ok: false, error: String(e) }));
    ms.ocupado = false;
    if (!r.ok) { estado(r.error, "error"); return; }
    ms.nombre = nombre; ms.formato = r.formato; ms.puntos = r.puntos; ms.avisos = r.avisos || [];
    ms.vista = "previa";
    estado("");
    dibujarPuntos(); ajustarMapa();
  }

  async function leerArchivo(archivo) {
    if (!archivo) return;
    ms.ocupado = true;
    estado(`Subiendo ${archivo.name}…`, "cargando");
    const subida = await Redes.subirArchivo(archivo, (p) => estado(`Subiendo ${archivo.name}… ${p} %`, "cargando"));
    if (!subida.ok) { ms.ocupado = false; estado(subida.error, "error"); return; }
    await leer(archivo.name, "", subida.id);
  }

  function leerPegado() {
    const texto = $("ms-pegado").value;
    if (!texto.trim()) { estado("Pegue el texto con las coordenadas", "error"); return; }
    leer("pegado.txt", btoa(unescape(encodeURIComponent(texto))));
  }

  function marcarDuplicadas() {
    const vistos = new Map();
    ms.puntos.forEach((p) => {
      if (p.estado === "duplicada") { p.estado = "ok"; p.motivo = ""; }
      if (p.estado !== "ok" || p.lat === null) return;
      const k = `${p.lat.toFixed(5)},${p.lon.toFixed(5)}`;
      if (vistos.has(k)) { p.estado = "duplicada"; p.incluir = false; p.motivo = `Igual a la fila ${vistos.get(k)}`; } else vistos.set(k, p.n);
    });
  }

  function editarCoordenada(p, texto) {
    const r = window.Coordenadas.interpretar(texto);
    p.texto = texto;
    p.lat = r.lat ?? null; p.lon = r.lon ?? null; p.sugerencia = r.sugerencia || null; p.motivo = r.mensaje || "";
    p.estado = { ok: "ok", invertida: "invertida", fuera: "fuera" }[r.estado] || "invalida";
    if (p.estado === "invalida" && !p.motivo) p.motivo = "No se reconoce la coordenada";
    p.incluir = p.estado === "ok";
    marcarDuplicadas();
    dibujarPuntos(); pintar();
  }

  async function calcular() {
    const validos = ms.puntos.filter((p) => p.incluir && p.estado === "ok");
    if (!validos.length) { estado("No hay coordenadas válidas marcadas", "error"); return; }
    if (!(await Redes.confirmar(`Se calcularán ${validos.length} presupuestos aproximados, uno por coordenada. Cada uno pide al menos una ruta a Google Directions (${validos.length} consultas o más si hay que comparar mufas) ` +
                                `con un límite por minuto (configurable en business_rules.yaml) y genera un Excel con LibreOffice, así que puede tardar. Se puede cancelar.`, "Calcular"))) return;
    ms.ocupado = true;
    estado("Iniciando el lote…", "cargando");
    const r = await ms.ctx.api().masivas_iniciar(ms.nombre, ms.puntos).catch((e) => ({ ok: false, error: String(e) }));
    ms.ocupado = false;
    if (!r.ok) { estado(r.error, "error"); return; }
    ms.lote = r.lote; ms.resultados = []; ms.vista = "progreso"; estado("");
    ms.sondeo = setInterval(sondear, 1500);
    sondear();
  }

  async function sondear() {
    if (!ms.lote) return;
    const r = await ms.ctx.api().masivas_estado(ms.lote.id, ms.resultados.length).catch((e) => ({ ok: false, error: String(e) }));
    if (!r.ok) { clearInterval(ms.sondeo); ms.sondeo = null; estado(r.error, "error"); return; }
    ms.resultados = ms.resultados.concat(r.lote.resultados);
    ms.lote = { ...r.lote, resultados: [] };
    if (r.lote.estado !== "corriendo") {
      clearInterval(ms.sondeo); ms.sondeo = null;
      ms.vista = "resultados";
      aviso(`Lote ${r.lote.estado}: ${ms.resultados.filter((x) => x.ok).length} de ${r.lote.total} presupuestos`, r.lote.estado === "error" ? "error" : "ok");
    }
    pintar();
  }

  async function accion(a) {
    if (a === "cancelar") { await ms.ctx.api().masivas_cancelar(ms.lote.id); estado("Cancelando… termina el punto en curso", "cargando"); return; }
    const ok = ms.resultados.filter((r) => r.ok);
    if (a === "carpeta") {
      if (ms.modo === "remoto") return accion("zip");
      const r = await ms.ctx.api().masivas_abrir_carpeta(ms.lote.id);
      if (!r.ok) estado(r.error, "error");
    } else if (a === "zip") {
      const r = await ms.ctx.api().masivas_descargar(ms.lote.id);
      if (!r.ok) { estado(r.error, "error"); return; }
      const g = await Redes.guardarArchivo(r.nombre, r.datos, "zip");
      if (g.ok) estado(`Guardado en ${g.ruta}`, "ok"); else if (!g.cancelado) estado(g.error, "error");
    } else if (a === "lugares") {
      const r = await llamar("lugares_desde_masivas", { nombre: ms.nombre.replace(/\.[^.]+$/, ""), puntos: ok, con_rutas: ms.conRutas });
      if (!r.ok) { estado(r.error, "error"); return; }
      if (window.MisLugares) await window.MisLugares.cargar();
      estado(`Carpeta creada en Mis lugares con ${r.puntos} punto(s)${r.rutas ? ` y ${r.rutas} ruta(s)` : ""}`, "ok");
    } else if (a === "proyecto") {
      const r = await llamar("proyecto_desde_masivas", { nombre: ms.nombre.replace(/\.[^.]+$/, ""), puntos: ok });
      if (!r.ok) { estado(r.error, "error"); return; }
      const s = r.resumen;
      estado(`Proyecto «${r.proyecto.nombre}» (${r.proyecto.codigo}) creado: ${s.clientes} cliente(s), ${s.mufas} punto(s) de conexión, ${s.cables} cable(s)` +
             (s.sin_conexion.length ? ` · sin conexión: ${s.sin_conexion.join(", ")}` : "") + ". Está en el menú Proyectos.", "ok");
    }
  }

  // ------------------------------------------------------------------ vistas
  function crear() {
    if ($("ms-ventana")) return;
    document.body.insertAdjacentHTML("beforeend", `<aside id="ms-ventana" class="ik-ventana ms-ventana" hidden aria-label="Coordenadas masivas">
      <header class="ik-cabecera"><h2>Coordenadas masivas</h2><button type="button" class="btn-icono" data-ms="cerrar" aria-label="Cerrar">✕</button></header>
      <div id="ms-cuerpo" class="ik-cuerpo"></div><input type="file" id="ms-archivo" accept=".xlsx,.xlsm,.csv,.docx,.txt" hidden></aside>`);
    const v = $("ms-ventana");
    L.DomEvent.disableClickPropagation(v);
    L.DomEvent.disableScrollPropagation(v);
    v.addEventListener("click", alClic);
    v.addEventListener("change", alCambiar);
    $("ms-archivo").addEventListener("change", (e) => { const a = e.target.files && e.target.files[0]; e.target.value = ""; leerArchivo(a); });
  }

  async function abrir() {
    if (!window.Redes || !window.Redes.disponible) { aviso("El módulo de redes no está disponible", "error"); return; }
    crear();
    $("ms-ventana").hidden = false;
    try { ms.modo = ((await ms.ctx.api().estado()) || {}).modo || "local"; } catch (e) { ms.modo = "local"; }
    pintar();
  }

  function vistaInicio() {
    return `<p class="ik-ayuda">Suba un archivo con coordenadas (<b>Excel</b>, <b>CSV</b>, <b>Word</b> o <b>texto</b>) o pegue el texto. Se buscan las columnas de latitud / longitud (o una de coordenadas),
        el nombre y el código; en Word y texto se leen los formatos del buscador (decimal y grados).</p>
      <button type="button" class="btn btn-primario" data-ms="elegir" ${ms.ocupado ? "disabled" : ""}>Elegir archivo…</button>
      <h3 class="ik-titulo">O pegue las coordenadas</h3>
      <textarea id="ms-pegado" class="ms-pegado" rows="6" placeholder="Casa Pérez 12.1364, -86.2514&#10;12°8'11&quot;N 86°15'5&quot;O Tienda Ana"></textarea>
      <button type="button" class="btn" data-ms="leer_pegado" ${ms.ocupado ? "disabled" : ""}>Leer lo pegado</button>`;
  }

  function filaPrevia(p) {
    const [texto, color] = ESTADOS[p.estado] || ESTADOS.invalida;
    return `<tr class="${p.incluir ? "" : "ik-rechazado"}"><td>${p.n}</td><td><input type="checkbox" data-ms="incluir" data-n="${p.n}" ${p.incluir ? "checked" : ""} ${p.estado !== "ok" ? "disabled" : ""}></td>
      <td><input class="ms-in" data-ms="nombre" data-n="${p.n}" value="${esc(p.nombre)}" placeholder="nombre"></td>
      <td><input class="ms-in ms-corto" data-ms="codigo" data-n="${p.n}" value="${esc(p.codigo)}" placeholder="C#####"></td>
      <td><input class="ms-in" data-ms="texto" data-n="${p.n}" value="${esc(p.texto)}" title="${esc(p.motivo)}"></td>
      <td><span class="ms-estado" style="--c:${color}" title="${esc(p.motivo)}">${texto}</span>${p.estado === "invertida" && p.sugerencia ? ` <button type="button" class="btn btn-chico" data-ms="usar_sugerida" data-n="${p.n}">Usar ${p.sugerencia[0].toFixed(4)}, ${p.sugerencia[1].toFixed(4)}</button>` : ""}</td></tr>`;
  }

  function vistaPrevia() {
    const cuenta = (e) => ms.puntos.filter((p) => p.estado === e).length;
    const incl = ms.puntos.filter((p) => p.incluir && p.estado === "ok").length;
    return `<div class="ik-archivo"><b>${esc(ms.nombre)}</b> <span class="nota">${esc(ms.formato)} · ${ms.puntos.length} coordenadas</span></div>${ms.avisos.map((a) => `<div class="nota error">${esc(a)}</div>`).join("")}
      <div class="ik-chips"><span class="ik-chip" style="--c:#2ca02c"><b>${cuenta("ok")}</b> válidas</span><span class="ik-chip" style="--c:#fb8c00"><b>${cuenta("invertida")}</b> al revés</span>
        <span class="ik-chip" style="--c:#e53935"><b>${cuenta("fuera") + cuenta("invalida")}</b> con problema</span><span class="ik-chip" style="--c:#9aa0ab"><b>${cuenta("duplicada")}</b> duplicadas</span></div>
      <div class="ms-tabla"><table class="ms-t"><thead><tr><th>#</th><th></th><th>Nombre</th><th>Código</th><th>Coordenada</th><th>Estado</th></tr></thead><tbody>${ms.puntos.map(filaPrevia).join("")}</tbody></table></div>
      <div class="ik-pie"><button type="button" class="btn btn-primario" data-ms="calcular" ${incl && !ms.ocupado ? "" : "disabled"}>Calcular ${incl} presupuesto(s)</button>
        <button type="button" class="btn" data-ms="volver">Volver</button></div>`;
  }

  function vistaProgreso() {
    const l = ms.lote, hechos = ms.resultados.length, pct = l.total ? Math.round(hechos * 100 / l.total) : 0;
    const resto = hechos ? Math.round((l.segundos / hechos) * (l.total - hechos)) : null;
    return `<div class="ik-archivo"><b>${esc(l.nombre)}</b> <span class="nota">${hechos} de ${l.total}</span></div>
      <div class="ms-barra"><div style="width:${pct}%"></div></div>
      <div class="nota">${l.actual ? `Calculando: ${esc(l.actual)}` : ""}${l.esperando_s ? ` · esperando el límite de Google por minuto (${l.esperando_s} s)` : ""}${resto !== null ? ` · faltan unos ${Math.floor(resto / 60)} min ${resto % 60} s` : ""}</div>
      <div class="ms-tabla">${tablaResultados(false)}</div>
      <div class="ik-pie"><button type="button" class="btn" data-ms="cancelar">Cancelar</button></div>`;
  }

  function tablaResultados(ordenable) {
    const { campo, dir } = ms.orden;
    const filas = [...ms.resultados].sort((a, b) => ((a[campo] ?? -Infinity) > (b[campo] ?? -Infinity) ? 1 : (a[campo] ?? -Infinity) < (b[campo] ?? -Infinity) ? -1 : 0) * dir);
    const th = (t, c) => `<th ${ordenable ? `data-ms="ordenar" data-campo="${c}" class="ms-ord${campo === c ? " activo" : ""}"` : ""}>${t}${campo === c && ordenable ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`;
    return `<table class="ms-t"><thead><tr>${th("#", "n")}${th("Nombre", "nombre")}${th("Conexión", "conexion")}${th("Ruta (m)", "distancia_m")}${th("Metraje (m)", "metraje_final_m")}${th("Cable", "tipo_cable")}
      ${th("Postes", "postes_nuevos")}${th("Mufas", "mufas")}${th("Total", "total")}<th>Avisos</th></tr></thead><tbody>${filas.map((r) => r.ok ?
      `<tr data-ms="ver_ruta" data-n="${r.n}" class="${ms.seleccionado === r.n ? "sel" : ""}"><td>${r.n}</td><td>${esc(r.nombre)}</td><td>${esc(r.conexion)}</td><td class="n">${num(r.distancia_m, 1)}</td><td class="n">${num(r.metraje_final_m, 1)}</td>
        <td>${esc(r.tipo_cable)}</td><td class="n">${r.postes_existentes}+${r.postes_nuevos}</td><td class="n">${r.mufas}</td><td class="n">${r.total === null ? "al abrir el Excel" : "C$ " + num(r.total, 2)}</td>
        <td title="${esc((r.avisos || []).join("\n"))}">${(r.avisos || []).length || ""}</td></tr>` :
      `<tr class="ms-error"><td>${r.n}</td><td>${esc(r.nombre)}</td><td colspan="8">${esc(r.error)}</td></tr>`).join("")}</tbody></table>`;
  }

  function vistaResultados() {
    const l = ms.lote, ok = ms.resultados.filter((r) => r.ok).length;
    return `<div class="ik-archivo"><b>${esc(l.nombre)}</b> <span class="nota">${esc(l.estado)} · ${ok} de ${l.total} presupuestos · ${Math.floor(l.segundos / 60)} min ${l.segundos % 60} s</span></div>
      ${l.mensaje ? `<div class="nota error">${esc(l.mensaje)}</div>` : ""}<div class="ms-tabla">${tablaResultados(true)}</div>
      <p class="nota">Clic en una fila para ver su ruta en el mapa. Los Excel (uno por coordenada y un Resumen.xlsx) están en ${ms.modo === "remoto" ? "el servidor" : esc(l.carpeta)}.</p>
      <div class="ik-pie"><button type="button" class="btn btn-primario" data-ms="carpeta" ${ok ? "" : "disabled"}>${ms.modo === "remoto" ? "Descargar .zip" : "Abrir carpeta"}</button>
        ${ms.modo === "remoto" ? "" : '<button type="button" class="btn" data-ms="zip">Guardar .zip…</button>'}
        <button type="button" class="btn" data-ms="proyecto" ${ok ? "" : "disabled"}>Guardar como proyecto</button><button type="button" class="btn" data-ms="lugares" ${ok ? "" : "disabled"}>Guardar en Mis lugares</button>
        <label class="nota"><input type="checkbox" data-ms="con_rutas" ${ms.conRutas ? "checked" : ""}> con las rutas</label><button type="button" class="btn" data-ms="volver">Otro archivo</button></div>`;
  }

  function pintar() {
    const c = $("ms-cuerpo");
    if (!c) return;
    const pie = ms.estado ? `<div class="nota ik-estado ${esc(ms.tipoEstado)}">${ms.tipoEstado === "cargando" ? '<span class="spinner"></span> ' : ""}${esc(ms.estado)}</div>` : "";
    const sel = c.querySelector(".ms-tabla"), alto = sel ? sel.scrollTop : 0;
    c.innerHTML = (ms.vista === "previa" ? vistaPrevia() : ms.vista === "progreso" && ms.lote ? vistaProgreso() : ms.vista === "resultados" && ms.lote ? vistaResultados() : vistaInicio()) + pie;
    const nueva = c.querySelector(".ms-tabla");
    if (nueva) nueva.scrollTop = alto;
  }

  function alClic(e) {
    const b = e.target.closest("[data-ms]");
    if (!b) return;
    const a = b.dataset.ms;
    if (a === "cerrar") $("ms-ventana").hidden = true;
    else if (a === "elegir") $("ms-archivo").click();
    else if (a === "leer_pegado") leerPegado();
    else if (a === "calcular") calcular();
    else if (a === "volver") {
      if (ms.sondeo) { clearInterval(ms.sondeo); ms.sondeo = null; }
      ms.vista = "inicio"; ms.puntos = []; ms.lote = null; ms.resultados = []; ms.seleccionado = null; estado("");
      dibujarPuntos(); mostrarRuta(null);
    } else if (a === "usar_sugerida") {
      const p = ms.puntos.find((x) => x.n === Number(b.dataset.n));
      if (p && p.sugerencia) editarCoordenada(p, `${p.sugerencia[0]}, ${p.sugerencia[1]}`);
    } else if (a === "ordenar") {
      const c = b.dataset.campo;
      ms.orden = { campo: c, dir: ms.orden.campo === c ? -ms.orden.dir : 1 };
      pintar();
    } else if (a === "ver_ruta") {
      const r = ms.resultados.find((x) => x.n === Number(b.dataset.n));
      ms.seleccionado = r ? r.n : null; mostrarRuta(r); pintar();
    } else if (["cancelar", "carpeta", "zip", "lugares", "proyecto"].includes(a)) accion(a);
  }

  function alCambiar(e) {
    const b = e.target.closest("[data-ms]");
    if (!b) return;
    const a = b.dataset.ms;
    const p = ms.puntos.find((x) => x.n === Number(b.dataset.n));
    if (a === "incluir" && p) { p.incluir = b.checked; dibujarPuntos(); pintar(); }
    else if (a === "nombre" && p) { p.nombre = b.value.trim(); dibujarPuntos(); }
    else if (a === "codigo" && p) p.codigo = b.value.trim();
    else if (a === "texto" && p) editarCoordenada(p, b.value);
    else if (a === "con_rutas") ms.conRutas = b.checked;
  }

  function iniciar(ctx) {
    ms.ctx = ctx;
  }

  window.Masivas = { iniciar, abrir, get estado() { return { vista: ms.vista, puntos: ms.puntos.length, resultados: ms.resultados.length }; }, _ms: ms };
})();
