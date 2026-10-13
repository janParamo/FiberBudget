/* Vista "Proyectos" del módulo de redes (fase 2).
 *
 * Lista con filtro (en árbol: los subproyectos debajo de su proyecto principal), tarjeta por
 * proyecto con Información, Historial, Editar, Duplicar y Eliminar (borrado lógico; un
 * administrador puede ver los eliminados y restaurarlos), y la ventana "Datos del proyecto":
 * imagen, nombre, identificador, usuarios, proyecto principal, descripción, búsqueda de
 * dirección (Google) o coordenada pegada, minimapa Mapa/Satélite con marcador arrastrable y
 * "Diseñar área" (polígono con Leaflet-Geoman). Clic en la tarjeta: abre el proyecto en el editor de
 * red sobre el mapa (redes/editor_mapa.js).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const CAMPOS = ["nombre", "codigo", "padre_id", "descripcion"];
  const MAX_IMAGEN = 2 * 1024 * 1024;

  const st = {
    lista: [], puedeCrear: false, puedeRestaurar: false, usuarios: [],
    editando: null,            // project being edited (null = new)
    imagen: undefined,         // undefined = unchanged; null = removed; "data:..." = new
    asignados: [],             // [{id, nombre, rol}]
    mapa: null, marcador: null, area: null, dibujando: false,
    clientes: [],              // [{id?, version?, nombre, codigo, id_servicio, lat, lon, marcador}]
    modoCliente: false,        // "＋ Agregar en el mapa": each map click adds a client
    capaClientes: null,
    info: null, conectado: false, temporizador: null,
  };
  const COLOR_CLIENTE = "#0a9d57";
  const iconoCliente = () => L.divIcon({
    className: "icono", iconSize: [24, 24], iconAnchor: [12, 22], tooltipAnchor: [0, -20],
    html: `<svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2 2 11h3v10h5v-6h4v6h5V11h3z"
      fill="${COLOR_CLIENTE}" stroke="#063" stroke-width="1.5"/></svg>`,
  });

  const estado = (texto, tipo) => Redes.estadoEn($("pr-estado"), texto, tipo);
  const estadoForm = (texto, tipo) => Redes.estadoEn($("pr-form-estado"), texto, tipo);

  // ------------------------------------------------------------------ lista
  async function cargar() {
    estado("Cargando proyectos…", "cargando");
    const r = await Redes.llamar("proyectos", { texto: $("pr-filtro").value, incluir_eliminados: $("pr-eliminados").checked });
    if (!r.ok) { estado(r.error, "error"); $("pr-lista").innerHTML = ""; return; }
    st.lista = r.proyectos;
    st.puedeCrear = r.puede_crear;
    st.puedeRestaurar = r.puede_restaurar;
    $("pr-crear").hidden = !st.puedeCrear;
    $("pr-eliminados-lbl").hidden = !st.puedeRestaurar;
    const n = st.lista.filter((p) => !p.eliminado).length;
    estado(`${n} proyecto${n === 1 ? "" : "s"}` + ($("pr-filtro").value.trim() ? " con ese filtro" : ""));
    pintar();
  }

  /** Projects in tree order: each subproject right below its parent (depth for the indent). */
  function enArbol(lista) {
    const porId = new Map(lista.map((p) => [p.id, p]));
    const hijos = new Map();
    lista.forEach((p) => {
      const padre = p.padre_id && porId.has(p.padre_id) ? p.padre_id : 0;
      if (!hijos.has(padre)) hijos.set(padre, []);
      hijos.get(padre).push(p);
    });
    const salida = [];
    const recorrer = (id, nivel, vistos) => (hijos.get(id) || []).forEach((p) => {
      if (vistos.has(p.id)) return;
      vistos.add(p.id);
      salida.push({ p, nivel });
      recorrer(p.id, nivel + 1, vistos);
    });
    recorrer(0, 0, new Set());
    return salida;
  }

  function boton(accion, id, icono, titulo, clase = "") {
    return `<button type="button" class="btn-icono ${clase}" data-pr="${accion}" data-id="${id}" title="${titulo}" aria-label="${titulo}">
      <svg><use href="#${icono}"/></svg></button>`;
  }

  function pintar() {
    const filas = enArbol(st.lista);
    $("pr-lista").innerHTML = filas.map(({ p, nivel }) => {
      const img = p.miniatura ? `<img src="${p.miniatura}" alt="">` : `<svg class="pr-sin-imagen"><use href="#i-proyectos"/></svg>`;
      const acciones = p.eliminado
        ? (st.puedeRestaurar ? boton("restaurar", p.id, "i-restaurar", "Restaurar") : "")
        : boton("info", p.id, "i-info", "Información") + boton("diagrama", p.id, "i-diagrama", "Diagrama lógico de red")
          + boton("historial", p.id, "i-reloj", "Historial")
          + (p.puede_editar ? boton("editar", p.id, "i-lapiz", "Editar datos") : "")
          + (st.puedeCrear ? boton("duplicar", p.id, "i-duplicar", "Duplicar") : "")
          + (p.puede_editar ? boton("eliminar", p.id, "i-papelera", "Eliminar", "peligro") : "");
      const usuarios = p.usuarios.map((u) => u.nombre).join(", ");
      return `<article class="pr-tarjeta${p.eliminado ? " eliminado" : ""}" style="margin-left:${nivel * 28}px" data-pr="abrir" data-id="${p.id}" tabindex="0">
        <div class="pr-logo">${img}</div>
        <div class="pr-texto">
          <div class="pr-nombre">${nivel ? `<span class="pr-rama">↳</span>` : ""}${esc(p.nombre)}
            <span class="pr-cod">${esc(p.codigo)}</span>${p.eliminado ? `<span class="pr-etq">Eliminado</span>` : ""}</div>
          <div class="pr-detalle">${p.descripcion ? esc(p.descripcion) + " · " : ""}${usuarios ? "Usuarios: " + esc(usuarios) : "Sin usuarios"}
            ${p.n_clientes ? ` · ${p.n_clientes} cliente${p.n_clientes === 1 ? "" : "s"}` : ""}${p.lat != null ? " · 📍" : ""}${p.area ? " · área" : ""}</div>
        </div>
        <div class="pr-acciones">${acciones}</div>
      </article>`;
    }).join("") || `<p class="vacio">${$("pr-filtro").value.trim() ? "Ningún proyecto coincide con el filtro."
      : st.puedeCrear ? "Todavía no hay proyectos. Use <b>+ Crear proyecto</b>." : "No tiene proyectos asignados. Pida acceso a un administrador."}</p>`;
  }

  const proyecto = (id) => st.lista.find((p) => p.id === Number(id));

  async function accion(nombre, id) {
    const p = proyecto(id);
    if (!p) return;
    if (nombre === "abrir") {                 // the project's network in the map editor (phase 3)
      if (p.eliminado) return mostrarInfo(p.id);
      return window.EditorRed ? window.EditorRed.abrir(p.id) : mostrarInfo(p.id);
    }
    if (nombre === "info") return mostrarInfo(p.id);
    if (nombre === "diagrama") return window.DiagramaLogico && window.DiagramaLogico.abrir(p.id);        // phase 6
    if (nombre === "historial") {
      const r = await Redes.llamar("historial_proyecto", { id: p.id });
      if (!r.ok) { estado(r.error, "error"); return; }
      Redes.mostrarHistorial(`Historial: ${p.nombre}`, r.historial);
    } else if (nombre === "editar") {
      const r = await Redes.llamar("proyecto", { id: p.id });
      if (!r.ok) { estado(r.error, "error"); return; }
      abrirFormulario(r.proyecto);
    } else if (nombre === "duplicar") {
      if (!(await Redes.confirmar(`¿Duplicar "${p.nombre}"? Se crea una copia con sus datos, imagen, área y usuarios.`, "Duplicar"))) return;
      const r = await Redes.llamar("duplicar_proyecto", { id: p.id });
      if (!r.ok) { estado(r.error, "error"); return; }
      await cargar();
      estado(`Copia creada: ${r.proyecto.nombre} (${r.proyecto.codigo})`, "ok");
    } else if (nombre === "eliminar") {
      if (!(await Redes.confirmar(`¿Eliminar "${p.nombre}"? Deja de verse en la lista; un administrador lo puede restaurar.`, "Eliminar"))) return;
      const r = await Redes.llamar("eliminar_proyecto", { id: p.id, version: p.version });
      if (!r.ok) { estado(r.error, "error"); return; }
      await cargar();
      estado(`Proyecto ${p.nombre} eliminado`, "ok");
    } else if (nombre === "restaurar") {
      const r = await Redes.llamar("restaurar_proyecto", { id: p.id, version: p.version });
      if (!r.ok) { estado(r.error, "error"); return; }
      await cargar();
      estado(`Proyecto ${p.nombre} restaurado`, "ok");
    }
  }

  // ------------------------------------------------------------------ minimapa
  function capasBase() {
    const cfg = Redes.cfg || {};
    const op = { maxZoom: 20, maxNativeZoom: 19 };
    const calles = L.tileLayer(cfg.streets_url || "", { ...op, attribution: cfg.streets_attribution || "" });
    const satelite = L.layerGroup([L.tileLayer(cfg.imagery_url || "", { ...op, attribution: "Imágenes © Esri" }),
                                   L.tileLayer(cfg.labels_url || "", op)]);
    return { calles, satelite };
  }

  function crearMapa() {
    if (st.mapa) return;
    const cfg = Redes.cfg || {};
    st.mapa = L.map("pr-mapa", { zoomControl: true, maxZoom: 20 }).setView(cfg.inicio || [12.13, -86.25], 13);
    st.mapa.attributionControl.setPrefix(false);
    const { calles, satelite } = capasBase();
    satelite.addTo(st.mapa);
    L.control.layers({ "Mapa": calles, "Satélite": satelite }, null, { position: "topleft", collapsed: false }).addTo(st.mapa);
    st.capaClientes = L.layerGroup().addTo(st.mapa);
    st.mapa.on("click", (e) => {
      if (st.dibujando) return;
      if (st.modoCliente) agregarCliente({ lat: e.latlng.lat, lon: e.latlng.lng });
      else ponerMarcador(e.latlng.lat, e.latlng.lng);
    });
    st.mapa.on("pm:create", (e) => {
      if (st.area) st.mapa.removeLayer(st.area);
      st.area = e.layer;
      st.dibujando = false;
      prepararArea();
      actualizarBotonesArea();
    });
  }

  function ponerMarcador(lat, lon, centrar = false) {
    if (!st.marcador) {
      st.marcador = L.marker([lat, lon], { draggable: true, pmIgnore: true }).addTo(st.mapa);
      st.marcador.bindTooltip("Arrastre para ajustar la ubicación", { direction: "top" });
    } else {
      st.marcador.setLatLng([lat, lon]);
    }
    if (centrar) st.mapa.setView([lat, lon], Math.max(st.mapa.getZoom(), 17));
  }

  function prepararArea() {
    st.area.setStyle({ color: "#1f6feb", weight: 2, fillOpacity: 0.15 });
    st.area.on("pm:edit", actualizarBotonesArea);
  }

  function actualizarBotonesArea() {
    const editando = st.area && st.area.pm && st.area.pm.enabled();
    $("pr-area").textContent = st.dibujando ? "Cancelar dibujo" : !st.area ? "Diseñar área" : editando ? "Terminar edición" : "Editar área";
    $("pr-area-borrar").hidden = !st.area;
  }

  function botonArea() {
    if (st.dibujando) { st.mapa.pm.disableDraw(); st.dibujando = false; actualizarBotonesArea(); return; }
    if (!st.area) {
      st.dibujando = true;
      st.mapa.pm.enableDraw("Polygon", { snappable: false, allowSelfIntersection: false, finishOn: "dblclick",
                                         templineStyle: { color: "#1f6feb" }, hintlineStyle: { color: "#1f6feb", dashArray: "5,5" },
                                         pathOptions: { color: "#1f6feb", weight: 2, fillOpacity: 0.15 } });
      estadoForm("Clic para cada punto del área; clic en el primer punto (o doble clic) para cerrarla");
    } else if (st.area.pm.enabled()) {
      st.area.pm.disable();
      estadoForm("");
    } else {
      st.area.pm.enable({ allowSelfIntersection: false });
      estadoForm("Arrastre los vértices para cambiar el área; clic en Terminar edición al acabar");
    }
    actualizarBotonesArea();
  }

  function borrarArea() {
    if (!st.area) return;
    st.mapa.removeLayer(st.area);
    st.area = null;
    actualizarBotonesArea();
  }

  function areaGeojson() {
    if (!st.area) return null;
    if (st.area.pm && st.area.pm.enabled()) st.area.pm.disable();
    const geo = st.area.toGeoJSON();
    return geo.geometry || geo;
  }

  // ------------------------------------------------------------------ clientes del proyecto
  const coordCliente = (c) => `${Number(c.lat).toFixed(6)}, ${Number(c.lon).toFixed(6)}`;

  function marcadorCliente(c) {
    const m = L.marker([c.lat, c.lon], { icon: iconoCliente(), draggable: true, pmIgnore: true, zIndexOffset: 500 });
    m.bindTooltip(() => esc(c.nombre || "Cliente"), { direction: "top" });
    m.on("dragend", () => {
      const ll = m.getLatLng();
      c.lat = ll.lat;
      c.lon = ll.lng;
      pintarClientes();
    });
    m.addTo(st.capaClientes);
    return m;
  }

  function agregarCliente(datos, centrar = false) {
    const c = { id: null, nombre: datos.nombre || `Cliente ${st.clientes.length + 1}`, codigo: datos.codigo || "",
                id_servicio: datos.id_servicio || "", lat: datos.lat, lon: datos.lon };
    c.marcador = marcadorCliente(c);
    st.clientes.push(c);
    pintarClientes();
    if (centrar) st.mapa.setView([c.lat, c.lon], Math.max(st.mapa.getZoom(), 17));
    return c;
  }

  function pintarClientes() {
    $("pr-clientes-n").textContent = st.clientes.length ? `(${st.clientes.length})` : "";
    $("pr-clientes-filas").innerHTML = st.clientes.map((c, i) => `<tr data-cliente="${i}">
        <td class="nota">${i + 1}</td>
        <td><input data-campo="nombre" value="${esc(c.nombre)}" maxlength="160" placeholder="Nombre"></td>
        <td><input data-campo="codigo" value="${esc(c.codigo || "")}" maxlength="10" placeholder="C#####"></td>
        <td><input data-campo="id_servicio" value="${esc(c.id_servicio || "")}" maxlength="40"></td>
        <td><input data-campo="coordenada" value="${coordCliente(c)}" spellcheck="false"></td>
        <td class="acciones"><button type="button" class="btn-icono" data-cliente-ver="${i}" title="Ver en el mapa">◎</button>
          <button type="button" class="btn-icono" data-cliente-quitar="${i}" title="Quitar">✕</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="vacio">Sin clientes. Use <b>＋ Agregar en el mapa</b> o <b>Pegar coordenadas</b>.</td></tr>`;
  }

  function quitarClientes() {
    if (st.capaClientes) st.capaClientes.clearLayers();
    st.clientes = [];
  }

  function cambiarModoCliente(activo) {
    st.modoCliente = activo;
    $("pr-cliente-mapa").classList.toggle("activo", activo);
    $("pr-cliente-mapa").textContent = activo ? "✓ Agregando: clic en el mapa" : "＋ Agregar en el mapa";
    $("pr-mapa").classList.toggle("agregando", activo);
  }

  /** "lat, lon[, nombre][, código]" per line -> clients. Returns [added, wrong lines]. */
  function pegarClientes(texto) {
    let agregados = 0;
    const malas = [];
    texto.split(/\r?\n/).forEach((linea, n) => {
      if (!linea.trim()) return;
      const partes = linea.split(/[,;\t]/).map((x) => x.trim());
      const coord = coordenadaPegada(`${partes[0] || ""}, ${partes[1] || ""}`);
      if (!coord) { malas.push(n + 1); return; }
      const resto = partes.slice(2).filter(Boolean);
      const codigo = resto.find((x) => /^C\d{3,8}$/i.test(x)) || "";
      const nombre = resto.find((x) => x !== codigo) || "";
      agregarCliente({ lat: coord[0], lon: coord[1], nombre, codigo });
      agregados++;
    });
    return [agregados, malas];
  }

  // ------------------------------------------------------------------ formulario
  function opcionesPadre(actual) {
    // the project itself and its subprojects cannot be its parent (no cycles)
    const excluir = new Set();
    if (actual) {
      excluir.add(actual.id);
      let cambio = true;
      while (cambio) {
        cambio = false;
        st.lista.forEach((p) => { if (p.padre_id && excluir.has(p.padre_id) && !excluir.has(p.id)) { excluir.add(p.id); cambio = true; } });
      }
    }
    $("pr-padre_id").innerHTML = `<option value="">(ninguno)</option>` + enArbol(st.lista.filter((p) => !p.eliminado))
      .filter(({ p }) => !excluir.has(p.id))
      .map(({ p, nivel }) => `<option value="${p.id}">${"  ".repeat(nivel)}${esc(p.nombre)} (${esc(p.codigo)})</option>`).join("");
  }

  function pintarUsuarios() {
    $("pr-usuarios").innerHTML = st.asignados.map((u) => `<span class="pr-chip">${esc(u.nombre)}
      <span class="nota">${esc(Redes.ROLES[u.rol] || u.rol)}</span>
      <button type="button" data-quitar-usuario="${u.id}" title="Quitar">✕</button></span>`).join("")
      || `<span class="nota">Solo usted (y los administradores)</span>`;
    const ids = new Set(st.asignados.map((u) => u.id));
    $("pr-usuario-agregar").innerHTML = `<option value="">Agregar usuario…</option>` + st.usuarios
      .filter((u) => !ids.has(u.id)).map((u) => `<option value="${u.id}">${esc(u.nombre)} (${esc(Redes.ROLES[u.rol] || u.rol)})</option>`).join("");
  }

  function pintarImagen(url) {
    $("pr-imagen-vista").innerHTML = url ? `<img src="${url}" alt="Imagen del proyecto">` : `<svg><use href="#i-proyectos"/></svg>`;
    $("pr-imagen-quitar").disabled = !url;
  }

  async function abrirFormulario(p) {
    st.editando = p || null;
    st.imagen = undefined;
    $("pr-modal-titulo").textContent = p ? `Datos del proyecto: ${p.nombre}` : "Nuevo proyecto";
    const u = await Redes.llamar("usuarios_asignables");
    st.usuarios = u.ok ? u.usuarios : [];
    const yo = Redes.estado && Redes.estado.usuario;
    st.asignados = p ? p.usuarios.map((x) => ({ id: x.id, nombre: x.nombre, rol: x.rol }))
      : (yo ? [{ id: yo.id, nombre: yo.nombre, rol: yo.rol }] : []);
    opcionesPadre(p);
    $("pr-nombre").value = p ? p.nombre : "";
    $("pr-codigo").value = p ? p.codigo : "";
    $("pr-padre_id").value = p && p.padre_id ? String(p.padre_id) : "";
    $("pr-descripcion").value = p ? (p.descripcion || "") : "";
    $("pr-direccion").value = "";
    $("pr-resultados").hidden = true;
    pintarUsuarios();
    pintarImagen(p ? p.imagen : null);
    Redes.marcarErrores("pr-", CAMPOS, null);
    ["pr-imagen-error", "pr-usuarios-error", "pr-ubicacion-error", "pr-area-error"].forEach((id) => { $(id).textContent = ""; });
    estadoForm("");
    $("modal-proyecto").hidden = false;
    crearMapa();
    st.mapa.invalidateSize();
    if (st.marcador) { st.mapa.removeLayer(st.marcador); st.marcador = null; }
    borrarArea();
    st.dibujando = false;
    cambiarModoCliente(false);
    $("pr-pegar").hidden = true;
    $("pr-clientes-error").textContent = "";
    quitarClientes();
    (p ? p.clientes || [] : []).forEach((c) => {
      const copia = { id: c.id, version: c.version, nombre: c.nombre, codigo: c.codigo || "", id_servicio: c.id_servicio || "",
                      lat: c.lat, lon: c.lon };
      copia.marcador = marcadorCliente(copia);
      st.clientes.push(copia);
    });
    pintarClientes();
    if (p && p.area) {
      st.area = L.geoJSON(p.area).getLayers()[0];
      st.area.addTo(st.mapa);
      prepararArea();
    }
    if (p && p.lat != null) ponerMarcador(p.lat, p.lon);
    const limites = L.latLngBounds([]);
    if (st.area) limites.extend(st.area.getBounds());
    if (st.marcador) limites.extend(st.marcador.getLatLng());
    st.clientes.forEach((c) => limites.extend([c.lat, c.lon]));
    if (limites.isValid()) st.mapa.fitBounds(limites, { padding: [30, 30], maxZoom: 17 });
    else st.mapa.setView((Redes.cfg && Redes.cfg.inicio) || [12.13, -86.25], 13);
    actualizarBotonesArea();
    $("pr-nombre").focus();
  }

  function cerrarFormulario() {
    if (st.dibujando) { st.mapa.pm.disableDraw(); st.dibujando = false; }
    $("modal-proyecto").hidden = true;
    st.editando = null;
  }

  function elegirImagen(archivo) {
    $("pr-imagen-error").textContent = "";
    if (!archivo) return;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(archivo.type)) { $("pr-imagen-error").textContent = "Use PNG, JPG, WEBP o GIF"; return; }
    if (archivo.size > MAX_IMAGEN) {
      $("pr-imagen-error").textContent = `La imagen pesa ${(archivo.size / 1048576).toFixed(1)} MB: el máximo es 2 MB`;
      return;
    }
    const lector = new FileReader();
    lector.onload = () => { st.imagen = lector.result; pintarImagen(st.imagen); };
    lector.readAsDataURL(archivo);
  }

  async function guardar(ev) {
    ev.preventDefault();
    const datos = {
      nombre: $("pr-nombre").value, codigo: $("pr-codigo").value, padre_id: $("pr-padre_id").value || null,
      descripcion: $("pr-descripcion").value, usuarios: st.asignados.map((u) => u.id), area: areaGeojson(),
      lat: st.marcador ? st.marcador.getLatLng().lat : null, lon: st.marcador ? st.marcador.getLatLng().lng : null,
      clientes: st.clientes.map((c) => ({ id: c.id, nombre: c.nombre, codigo: c.codigo, id_servicio: c.id_servicio,
                                          lat: c.lat, lon: c.lon })),
    };
    if (st.imagen !== undefined) datos.imagen = st.imagen;
    if (st.editando) Object.assign(datos, { id: st.editando.id, version: st.editando.version });
    Redes.marcarErrores("pr-", CAMPOS, null);
    ["pr-imagen-error", "pr-usuarios-error", "pr-ubicacion-error", "pr-area-error", "pr-clientes-error"].forEach((id) => { $(id).textContent = ""; });
    estadoForm("Guardando…", "cargando");
    $("pr-guardar").disabled = true;
    const r = await Redes.llamar("guardar_proyecto", { datos });
    $("pr-guardar").disabled = false;
    if (!r.ok) {
      const e = r.errores || {};
      Redes.marcarErrores("pr-", CAMPOS, e);
      $("pr-imagen-error").textContent = e.imagen || "";
      $("pr-usuarios-error").textContent = e.usuarios || "";
      $("pr-ubicacion-error").textContent = e.ubicacion || "";
      $("pr-area-error").textContent = e.area || "";
      $("pr-clientes-error").textContent = e.clientes || "";
      estadoForm(r.conflicto ? `${r.error} Cierre la ventana y presione Recargar.` : r.error, "error");
      return;
    }
    cerrarFormulario();
    await cargar();
    estado(`Proyecto ${r.proyecto.nombre} guardado`, "ok");
  }

  /** "lat, lon" pasted in the address box: used directly, without Google. */
  function coordenadaPegada(texto) {
    const m = /^\s*\(?\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*\)?\s*$/.exec(texto);
    if (!m) return null;
    const lat = Number(m[1]), lon = Number(m[2]);
    return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
  }

  async function buscarDireccion() {
    const texto = $("pr-direccion").value.trim();
    const lista = $("pr-resultados");
    lista.hidden = true;
    if (!texto) return;
    // With "＋ Agregar en el mapa" active, the found place becomes a new client.
    const ubicar = (lat, lon, nombre) => (st.modoCliente ? agregarCliente({ lat, lon, nombre }, true) : ponerMarcador(lat, lon, true));
    const coord = coordenadaPegada(texto);
    if (coord) {
      ubicar(coord[0], coord[1]);
      estadoForm(st.modoCliente ? "Cliente agregado en la coordenada" : "Ubicación puesta en la coordenada", "ok");
      return;
    }
    estadoForm("Buscando la dirección…", "cargando");
    const r = await Redes.llamar("geocodificar", { texto });
    if (!r.ok) { estadoForm((r.errores && r.errores.direccion) || r.error, "error"); return; }
    if (!r.resultados.length) { estadoForm("Google no encontró esa dirección", "error"); return; }
    estadoForm("");
    if (r.resultados.length === 1) { ubicar(r.resultados[0].lat, r.resultados[0].lon, r.resultados[0].direccion); return; }
    lista.innerHTML = r.resultados.map((x, i) => `<li data-resultado="${i}">${esc(x.direccion)}</li>`).join("");
    lista.hidden = false;
    lista.onclick = (e) => {
      const li = e.target.closest("[data-resultado]");
      if (!li) return;
      const x = r.resultados[Number(li.dataset.resultado)];
      ubicar(x.lat, x.lon, x.direccion);
      lista.hidden = true;
    };
  }

  // ------------------------------------------------------------------ información
  async function mostrarInfo(id) {
    const r = await Redes.llamar("proyecto", { id });
    if (!r.ok) { estado(r.error, "error"); return; }
    const p = r.proyecto;
    $("pr-info-titulo").textContent = `${p.nombre} (${p.codigo})`;
    const fila = (k, v) => (v ? `<dt>${esc(k)}</dt><dd>${v}</dd>` : "");
    $("pr-info-datos").innerHTML = `<div class="pr-info-img">${p.imagen ? `<img src="${p.imagen}" alt="">` : `<svg><use href="#i-proyectos"/></svg>`}</div>
      <dl>${fila("Identificador", esc(p.codigo))}${fila("Descripción", esc(p.descripcion || ""))}
        ${fila("Proyecto principal", esc(p.padre_nombre || ""))}
        ${fila("Subproyectos", p.hijos.map((h) => esc(h.nombre)).join(", "))}
        ${fila("Usuarios", p.usuarios.map((u) => `${esc(u.nombre)} <span class="nota">(${esc(Redes.ROLES[u.rol] || u.rol)})</span>`).join(", ") || "—")}
        ${fila("Ubicación", p.lat != null ? `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}` : "Sin ubicación")}
        ${fila("Área", p.area ? `Polígono de ${p.area_vertices} puntos` : "Sin área")}
        ${fila(`Clientes (${(p.clientes || []).length})`, (p.clientes || []).map((c) =>
          `${esc(c.nombre)}${c.codigo ? ` <span class="nota">${esc(c.codigo)}</span>` : ""}`).join(", ") || "—")}
        ${fila("Creado", `${esc(p.creado_por || "—")} · ${esc(Redes.fecha(p.creado_en))}`)}
        ${fila("Última edición", p.actualizado_en ? `${esc(p.actualizado_por || "—")} · ${esc(Redes.fecha(p.actualizado_en))}` : "")}
        ${fila("Versión", String(p.version))}</dl>
      <p><button type="button" class="btn btn-primario btn-chico" data-pr-abrir="${p.id}">Abrir en el mapa</button>
        <span class="nota">(también: clic en la tarjeta del proyecto)</span></p>`;
    $("modal-pr-info").hidden = false;
    if (!st.info) {
      st.info = L.map("pr-info-mapa", { zoomControl: true, maxZoom: 20 });
      st.info.attributionControl.setPrefix(false);
      capasBase().satelite.addTo(st.info);
      st.infoCapa = L.layerGroup().addTo(st.info);
    }
    st.info.invalidateSize();
    st.infoCapa.clearLayers();
    const limites = [];
    if (p.area) { const a = L.geoJSON(p.area, { style: { color: "#1f6feb", weight: 2, fillOpacity: 0.15 } }).addTo(st.infoCapa); limites.push(a.getBounds()); }
    if (p.lat != null) { L.marker([p.lat, p.lon]).addTo(st.infoCapa); limites.push(L.latLngBounds([[p.lat, p.lon], [p.lat, p.lon]])); }
    (p.clientes || []).forEach((c) => {
      L.marker([c.lat, c.lon], { icon: iconoCliente() }).bindTooltip(esc(c.nombre), { direction: "top" }).addTo(st.infoCapa);
      limites.push(L.latLngBounds([[c.lat, c.lon], [c.lat, c.lon]]));
    });
    if (limites.length) st.info.fitBounds(limites.reduce((a, b) => a.extend(b)), { padding: [30, 30], maxZoom: 17 });
    else st.info.setView((Redes.cfg && Redes.cfg.inicio) || [12.13, -86.25], 12);
  }

  // ------------------------------------------------------------------ eventos
  function conectar() {
    if (st.conectado) return;
    st.conectado = true;
    $("pr-recargar").addEventListener("click", cargar);
    $("pr-eliminados").addEventListener("change", cargar);
    $("pr-filtro").addEventListener("input", () => { clearTimeout(st.temporizador); st.temporizador = setTimeout(cargar, 250); });
    $("pr-crear").addEventListener("click", () => abrirFormulario(null));
    $("pr-lista").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pr]");
      if (b) { e.stopPropagation(); accion(b.dataset.pr, b.dataset.id); }
    });
    $("pr-lista").addEventListener("keydown", (e) => {
      const t = e.target.closest(".pr-tarjeta");
      if (t && e.key === "Enter") accion("abrir", t.dataset.id);
    });
    $("pr-form").addEventListener("submit", guardar);
    $("pr-cancelar").addEventListener("click", cerrarFormulario);
    $("pr-cerrar").addEventListener("click", cerrarFormulario);
    $("pr-imagen-elegir").addEventListener("click", () => $("pr-imagen-archivo").click());
    $("pr-imagen-archivo").addEventListener("change", (e) => { elegirImagen(e.target.files[0]); e.target.value = ""; });
    $("pr-imagen-quitar").addEventListener("click", () => { st.imagen = null; pintarImagen(null); });
    $("pr-usuario-agregar").addEventListener("change", (e) => {
      const u = st.usuarios.find((x) => x.id === Number(e.target.value));
      if (u) { st.asignados.push(u); pintarUsuarios(); }
    });
    $("pr-usuarios").addEventListener("click", (e) => {
      const b = e.target.closest("[data-quitar-usuario]");
      if (b) { st.asignados = st.asignados.filter((u) => u.id !== Number(b.dataset.quitarUsuario)); pintarUsuarios(); }
    });
    $("pr-buscar").addEventListener("click", buscarDireccion);
    $("pr-direccion").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); buscarDireccion(); } });
    $("pr-area").addEventListener("click", botonArea);
    $("pr-area-borrar").addEventListener("click", borrarArea);
    // clientes del proyecto
    $("pr-cliente-mapa").addEventListener("click", () => cambiarModoCliente(!st.modoCliente));
    $("pr-cliente-pegar").addEventListener("click", () => { $("pr-pegar").hidden = false; $("pr-pegar-texto").focus(); });
    $("pr-pegar-cancelar").addEventListener("click", () => { $("pr-pegar").hidden = true; });
    $("pr-pegar-agregar").addEventListener("click", () => {
      const [agregados, malas] = pegarClientes($("pr-pegar-texto").value);
      $("pr-pegar-estado").textContent = `${agregados} agregado${agregados === 1 ? "" : "s"}`
        + (malas.length ? ` · líneas sin coordenada válida: ${malas.join(", ")}` : "");
      if (agregados && !malas.length) {
        $("pr-pegar-texto").value = "";
        $("pr-pegar").hidden = true;
        const limites = L.latLngBounds(st.clientes.map((c) => [c.lat, c.lon]));
        st.mapa.fitBounds(limites, { padding: [30, 30], maxZoom: 17 });
      }
    });
    $("pr-clientes-filas").addEventListener("change", (e) => {
      const fila = e.target.closest("[data-cliente]");
      const c = fila && st.clientes[Number(fila.dataset.cliente)];
      if (!c) return;
      const campo = e.target.dataset.campo;
      if (campo === "coordenada") {
        const coord = coordenadaPegada(e.target.value);
        if (!coord) { e.target.classList.add("invalido"); return; }
        e.target.classList.remove("invalido");
        [c.lat, c.lon] = coord;
        c.marcador.setLatLng(coord);
        e.target.value = coordCliente(c);
      } else {
        c[campo] = e.target.value.trim();
      }
    });
    $("pr-clientes-filas").addEventListener("click", (e) => {
      const ver = e.target.closest("[data-cliente-ver]");
      const quitar = e.target.closest("[data-cliente-quitar]");
      if (ver) {
        const c = st.clientes[Number(ver.dataset.clienteVer)];
        st.mapa.setView([c.lat, c.lon], Math.max(st.mapa.getZoom(), 18));
        c.marcador.openTooltip();
      } else if (quitar) {
        const [c] = st.clientes.splice(Number(quitar.dataset.clienteQuitar), 1);
        st.capaClientes.removeLayer(c.marcador);
        pintarClientes();
      }
    });
    $("pr-info-cerrar").addEventListener("click", () => { $("modal-pr-info").hidden = true; });
    $("pr-info-datos").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pr-abrir]");
      if (b && window.EditorRed) { $("modal-pr-info").hidden = true; window.EditorRed.abrir(Number(b.dataset.prAbrir)); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!$("modal-pr-info").hidden) { e.stopPropagation(); $("modal-pr-info").hidden = true; }
      else if (!$("modal-proyecto").hidden && $("modal-confirmar").hidden) {
        e.stopPropagation();
        if (st.dibujando) { st.mapa.pm.disableDraw(); st.dibujando = false; actualizarBotonesArea(); estadoForm(""); }
        else cerrarFormulario();
      }
    }, true);
  }

  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.proyectos = { mostrar() { conectar(); cargar(); } };
  window.Proyectos = { _st: st, abrirFormulario, mostrarInfo };        // automated checks
})();
