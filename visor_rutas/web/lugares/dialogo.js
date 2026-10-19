/* Ventana de una marca de posición, ruta o polígono (visor v2, fase 3), como la de Google Earth: nombre, carpeta, y las pestañas
 * Descripción (texto con formato, vínculos e imágenes locales), Estilo, color, Ver (centro y zoom guardados) y, en rutas y
 * polígonos, Medidas. Es una ventana flotante SIN fondo que bloquee el mapa: mientras está abierta se arrastra el pincho o se
 * editan los vértices en el mapa y sus campos se actualizan. Se mueve por su cabecera.
 *
 *   Dialogo.abrir({tipo, titulo, nombre, carpetas: [{id, etiqueta}], carpetaId, lat, lon, estilo, vista, descripcionHtml, adjuntos,
 *                  cargarAdjunto(id) -> Promise<dataURL>, mapa, alCambiar({lat, lon, estilo}), alAceptar(datos) -> Promise<{ok, error}>,
 *                  alCancelar()}) -> {ponerCoordenada(lat, lon), ponerMedidas(m), cerrar()}
 *   Dialogo.pedirTexto(titulo, valor, etiqueta) -> Promise<string | null>
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MAX_IMAGEN = 2 * 1024 * 1024;
  const esPunto = (t) => ["marca", "mufa", "poste", "cliente", "nodo", "odf"].includes(t);        // one point on the map (a mark or a network element)
  let actual = null;                        // the open dialog: {op, quill, nuevas, estilo, vista, ...}

  function crear() {
    if ($("ml-dialogo")) return;
    document.body.insertAdjacentHTML("beforeend", `
      <div id="ml-dialogo" class="ml-dialogo" hidden role="dialog" aria-labelledby="ml-d-titulo">
        <header class="ml-d-cabecera" id="ml-d-cabecera"><h2 id="ml-d-titulo">Marca de posición</h2>
          <button type="button" class="btn-icono" id="ml-d-cerrar" aria-label="Cancelar">✕</button></header>
        <form id="ml-d-form" class="ml-d-cuerpo" autocomplete="off" novalidate>
          <div class="vp-campo"><label for="ml-d-nombre">Nombre *</label>
            <div class="ml-d-nombre"><input id="ml-d-nombre" maxlength="160"><button type="button" id="ml-d-icono" class="ml-d-icono-btn" title="Cambiar el ícono"></button></div>
            <small id="ml-d-e-nombre"></small></div>
          <div class="vp-campo"><label for="ml-d-carpeta">Carpeta</label><select id="ml-d-carpeta"></select><small id="ml-d-e-carpeta"></small></div>
          <div id="ml-d-coords"><div class="vp-fila">
            <div class="vp-campo"><label for="ml-d-lat">Latitud</label><input id="ml-d-lat" inputmode="decimal" placeholder="13.094578 o 13°5'38.09&quot;N"></div>
            <div class="vp-campo"><label for="ml-d-lon">Longitud</label><input id="ml-d-lon" inputmode="decimal" placeholder="-86.002708 o 86°0'7.42&quot;O"></div></div>
            <small id="ml-d-e-coord"></small></div>
          <nav class="ml-d-pestanas" role="tablist">
            <button type="button" role="tab" class="ml-d-pest" data-ml-pest="red" id="ml-d-pest-red" hidden>Datos de red</button>
            <button type="button" role="tab" class="ml-d-pest activa" data-ml-pest="desc">Descripción</button>
            <button type="button" role="tab" class="ml-d-pest" data-ml-pest="estilo">Estilo, color</button>
            <button type="button" role="tab" class="ml-d-pest" data-ml-pest="ver">Ver</button>
            <button type="button" role="tab" class="ml-d-pest" data-ml-pest="medidas" id="ml-d-pest-medidas">Medidas</button></nav>
          <section data-ml-panel="red" hidden id="ml-d-red"></section>
          <section data-ml-panel="desc">
            <div class="ml-d-herr"><button type="button" class="btn btn-chico" id="ml-d-vinculo">Agregar vínculo</button>
              <button type="button" class="btn btn-chico" id="ml-d-imagen">Agregar imagen local…</button>
              <input type="file" id="ml-d-archivo" accept="image/png,image/jpeg,image/webp,image/gif" hidden></div>
            <div id="ml-d-quill"></div></section>
          <section data-ml-panel="estilo" hidden id="ml-d-estilo"></section>
          <section data-ml-panel="ver" hidden>
            <p class="ml-d-nota" id="ml-d-vista-nota"></p>
            <div class="vp-fila"><div class="vp-campo"><label for="ml-d-v-lat">Latitud</label><input id="ml-d-v-lat"></div>
              <div class="vp-campo"><label for="ml-d-v-lon">Longitud</label><input id="ml-d-v-lon"></div>
              <div class="vp-campo ml-d-corto"><label for="ml-d-v-zoom">Zoom</label><input id="ml-d-v-zoom" type="number" min="1" max="21" step="0.5"></div></div>
            <div class="ml-d-herr"><button type="button" class="btn btn-chico" id="ml-d-v-instantanea">Instantánea de vista actual</button>
              <button type="button" class="btn btn-chico" id="ml-d-v-probar">Ir a esta vista</button>
              <button type="button" class="btn btn-chico" id="ml-d-v-restablecer">Restablecer</button></div></section>
          <section data-ml-panel="medidas" hidden id="ml-d-medidas"></section>
          <div class="config-acciones"><span id="ml-d-estado" class="vp-estado"></span>
            <button type="button" class="btn" id="ml-d-cancelar">Cancelar</button>
            <button type="submit" class="btn btn-primario" id="ml-d-aceptar">Aceptar</button></div>
        </form>
      </div>
      <div id="ml-pedir" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="ml-pedir-titulo">
        <div class="modal-caja config-caja ml-pedir-caja"><header class="modal-cabecera"><h2 id="ml-pedir-titulo">Texto</h2>
          <button type="button" class="btn-icono" data-ml-pedir="cancelar" aria-label="Cerrar">✕</button></header>
          <form id="ml-pedir-form" class="config-cuerpo" autocomplete="off"><div class="vp-campo"><label for="ml-pedir-valor" id="ml-pedir-etiqueta">Nombre</label>
            <input id="ml-pedir-valor" maxlength="160"></div>
            <div class="config-acciones"><button type="button" class="btn" data-ml-pedir="cancelar">Cancelar</button><button type="submit" class="btn btn-primario">Aceptar</button></div></form>
        </div>
      </div>`);
    const form = $("ml-d-form");
    form.addEventListener("submit", (e) => { e.preventDefault(); aceptar(); });
    $("ml-d-cancelar").addEventListener("click", () => cerrar(true));
    $("ml-d-cerrar").addEventListener("click", () => cerrar(true));
    $("ml-dialogo").addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.target.closest(".ql-editor")) { e.stopPropagation(); cerrar(true); } });
    document.querySelectorAll(".ml-d-pest").forEach((b) => b.addEventListener("click", () => pestana(b.dataset.mlPest)));
    $("ml-d-icono").addEventListener("click", cambiarIcono);
    $("ml-d-vinculo").addEventListener("click", agregarVinculo);
    $("ml-d-imagen").addEventListener("click", () => $("ml-d-archivo").click());
    $("ml-d-archivo").addEventListener("change", agregarImagen);
    $("ml-d-v-instantanea").addEventListener("click", instantanea);
    $("ml-d-v-restablecer").addEventListener("click", () => { poner("ml-d-v-lat", ""); poner("ml-d-v-lon", ""); poner("ml-d-v-zoom", ""); notaVista(); });
    $("ml-d-v-probar").addEventListener("click", () => { const v = leerVista(); if (v && actual) actual.op.mapa.flyTo([v.lat, v.lon], v.zoom, { duration: 0.6 }); });
    ["ml-d-v-lat", "ml-d-v-lon", "ml-d-v-zoom"].forEach((id) => $(id).addEventListener("input", notaVista));
    $("ml-d-lat").addEventListener("change", () => coordenadaEscrita());
    $("ml-d-lon").addEventListener("change", () => coordenadaEscrita());
    arrastrable();
  }

  function arrastrable() {
    const cab = $("ml-d-cabecera"), caja = $("ml-dialogo");
    let origen = null;
    cab.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const r = caja.getBoundingClientRect();
      caja.style.left = `${r.left}px`; caja.style.top = `${r.top}px`; caja.style.right = "auto";
      origen = { x: e.clientX - r.left, y: e.clientY - r.top };
      cab.setPointerCapture(e.pointerId);
    });
    cab.addEventListener("pointermove", (e) => {
      if (!origen) return;
      caja.style.left = `${Math.max(0, Math.min(window.innerWidth - 120, e.clientX - origen.x))}px`;
      caja.style.top = `${Math.max(0, Math.min(window.innerHeight - 60, e.clientY - origen.y))}px`;
    });
    const soltar = () => { origen = null; };
    cab.addEventListener("pointerup", soltar);
    cab.addEventListener("pointercancel", soltar);
  }

  const poner = (id, valor) => { $(id).value = valor ?? ""; };
  const avisoEstado = (texto, error = false) => { $("ml-d-estado").textContent = texto || ""; $("ml-d-estado").style.color = error ? "var(--error)" : ""; };

  function pestana(nombre) {
    document.querySelectorAll(".ml-d-pest").forEach((b) => b.classList.toggle("activa", b.dataset.mlPest === nombre));
    document.querySelectorAll("#ml-dialogo [data-ml-panel]").forEach((p) => { p.hidden = p.dataset.mlPanel !== nombre; });
  }

  // ------------------------------------------------------------------ estilo
  function pintarIconoBoton() {
    if (actual.op.tipo !== "marca") return;
    $("ml-d-icono").innerHTML = Iconos.svg(actual.estilo.icono || Iconos.DEFECTO, 26);
  }

  async function cambiarIcono() {
    const elegido = await Iconos.seleccionar(actual.estilo.icono || Iconos.DEFECTO);
    if (!elegido || !actual) return;
    actual.estilo.icono = elegido;
    pintarIconoBoton();
    estiloCambio();
  }

  function estiloCambio() {
    if (actual && actual.op.alCambiar) actual.op.alCambiar({ estilo: actual.estilo });
  }

  function panelEstilo() {
    const e = actual.estilo, tipo = actual.op.tipo;
    const campo = (id, etiqueta, valor, extra = "") => `<div class="vp-campo"><label for="${id}">${etiqueta}</label><input id="${id}" ${extra} value="${esc(valor)}"></div>`;
    let html = "";
    if (tipo === "marca") {
      const et = e.etiqueta || {};
      html = `<div class="ml-d-herr"><button type="button" class="btn" id="ml-d-e-icono">Cambiar el ícono…</button><span class="ml-d-nota">el ícono, su color, escala y opacidad</span></div>
        <label class="ml-d-casilla"><input type="checkbox" id="ml-d-e-etiqueta-ver" ${et.visible === false ? "" : "checked"}> Mostrar el nombre junto al pincho</label>
        <div class="vp-fila">${campo("ml-d-e-etiqueta-color", "Color del nombre", et.color || "#ffffff", 'type="color"')}
          ${campo("ml-d-e-etiqueta-escala", "Escala del nombre", et.escala ?? 1, 'type="number" min="0.3" max="4" step="0.1"')}</div>`;
    } else {
      const li = e.linea || {}, re = e.relleno || {};
      html = `<div class="vp-fila">${campo("ml-d-e-linea-color", "Color de la línea", li.color || "#ffe600", 'type="color"')}
          ${campo("ml-d-e-linea-grosor", "Grosor (px)", li.grosor ?? 3, 'type="number" min="1" max="20" step="0.5"')}
          ${campo("ml-d-e-linea-op", "Opacidad (%)", Math.round((li.opacidad ?? 1) * 100), 'type="number" min="0" max="100" step="5"')}</div>`;
      if (tipo === "poligono") {
        html += `<label class="ml-d-casilla"><input type="checkbox" id="ml-d-e-relleno-activo" ${re.activo === false ? "" : "checked"}> Rellenar el polígono</label>
          <div class="vp-fila">${campo("ml-d-e-relleno-color", "Color del relleno", re.color || "#ffe600", 'type="color"')}
          ${campo("ml-d-e-relleno-op", "Opacidad del relleno (%)", Math.round((re.opacidad ?? 0.3) * 100), 'type="number" min="0" max="100" step="5"')}</div>`;
      }
    }
    $("ml-d-estilo").innerHTML = html;
    const leer = () => {
      const v = (id) => $(id) && $(id).value;
      if (tipo === "marca") {
        actual.estilo.etiqueta = { visible: $("ml-d-e-etiqueta-ver").checked, color: v("ml-d-e-etiqueta-color"), escala: Number(v("ml-d-e-etiqueta-escala")) || 1 };
      } else {
        actual.estilo.linea = { color: v("ml-d-e-linea-color"), grosor: Number(v("ml-d-e-linea-grosor")) || 3, opacidad: Math.min(100, Math.max(0, Number(v("ml-d-e-linea-op")))) / 100 };
        if (tipo === "poligono") {
          actual.estilo.relleno = { activo: $("ml-d-e-relleno-activo").checked, color: v("ml-d-e-relleno-color"),
                                    opacidad: Math.min(100, Math.max(0, Number(v("ml-d-e-relleno-op")))) / 100 };
        }
      }
      estiloCambio();
    };
    $("ml-d-estilo").oninput = leer;
    $("ml-d-estilo").onchange = leer;
    const botonIcono = $("ml-d-e-icono");
    if (botonIcono) botonIcono.addEventListener("click", cambiarIcono);
  }

  // ------------------------------------------------------------------ vista guardada
  function leerVista() {
    const lat = Coordenadas.valor($("ml-d-v-lat").value), lon = Coordenadas.valor($("ml-d-v-lon").value), zoom = Number($("ml-d-v-zoom").value);
    if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { lat: Math.round(lat * 1e7) / 1e7, lon: Math.round(lon * 1e7) / 1e7, zoom: Number.isFinite(zoom) && zoom >= 1 ? Math.min(21, zoom) : 17 };
  }
  function notaVista() {
    $("ml-d-vista-nota").textContent = leerVista() ? "Al volar a este lugar, el mapa se centrará en esta vista." : "Sin vista guardada: se usará el lugar mismo.";
  }
  function instantanea() {
    const m = actual.op.mapa, c = m.getCenter();
    poner("ml-d-v-lat", c.lat.toFixed(7)); poner("ml-d-v-lon", c.lng.toFixed(7)); poner("ml-d-v-zoom", m.getZoom());
    notaVista();
  }

  // ------------------------------------------------------------------ coordenadas de la marca
  function coordenadaEscrita() {
    if (!actual || !esPunto(actual.op.tipo)) return;
    const lat = Coordenadas.valor($("ml-d-lat").value), lon = Coordenadas.valor($("ml-d-lon").value);
    $("ml-d-e-coord").textContent = "";
    if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      $("ml-d-e-coord").textContent = "Escriba la latitud y la longitud en decimal o en grados, minutos y segundos";
      return;
    }
    actual.lat = lat; actual.lon = lon;
    if (actual.op.alCambiar) actual.op.alCambiar({ lat, lon, desdeCampos: true });
  }

  function ponerCoordenada(lat, lon) {
    if (!actual) return;
    actual.lat = lat; actual.lon = lon;
    poner("ml-d-lat", lat.toFixed(6)); poner("ml-d-lon", lon.toFixed(6));
    $("ml-d-e-coord").textContent = "";
  }

  function ponerMedidas(m) {
    if (!actual || esPunto(actual.op.tipo)) return;
    const metros = (v) => `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 })} m`;
    const filas = [["Puntos", m.puntos]];
    if (actual.op.tipo !== "poligono") filas.push(["Longitud", `${metros(m.longitud_m)} (${(m.longitud_m / 1000).toFixed(3)} km)`]);
    else filas.push(["Perímetro", `${metros(m.perimetro_m)} (${(m.perimetro_m / 1000).toFixed(3)} km)`],
      ["Área", `${Number(m.area_m2).toLocaleString("en-US", { maximumFractionDigits: 1 })} m² · ${(m.area_m2 / 10000).toFixed(3)} ha · ${(m.area_m2 / 1e6).toFixed(4)} km²`]);
    $("ml-d-medidas").innerHTML = `<dl class="ml-d-dl">${filas.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`
      + `<p class="ml-d-nota">${actual.op.tipo !== "poligono" ? "Se actualiza al agregar, mover o quitar puntos de la línea en el mapa." : "Se actualiza al mover los puntos del polígono en el mapa."}</p>`;
  }

  // ------------------------------------------------------------------ descripción (Quill)
  function crearQuill() {
    const caja = $("ml-d-quill");
    caja.innerHTML = "";
    caja.className = "";
    if (!window.Quill) { caja.innerHTML = `<textarea id="ml-d-texto-plano" rows="6"></textarea>`; return null; }
    const q = new Quill(caja, { theme: "snow", placeholder: "Descripción…",
      modules: { toolbar: [["bold", "italic", "underline"], [{ list: "ordered" }, { list: "bullet" }], [{ color: [] }], ["clean"]] } });
    return q;
  }

  async function cargarDescripcion(html, adjuntos, cargar) {
    if (!html) return "";
    avisoEstado("Cargando imágenes…");
    const urls = {};
    await Promise.all((adjuntos || []).map(async (a) => { try { urls[a.id] = await cargar(a.id); } catch (e) { /* the image is lost: it is dropped */ } }));
    avisoEstado("");
    return html.replace(/<img\b[^>]*?\bdata-adj="(\d+)"[^>]*>/gi, (_, id) => (urls[id] ? `<img src="${urls[id]}" alt="adj:${id}">` : ""));
  }

  function agregarVinculo() {
    if (!actual || !actual.quill) return;
    const q = actual.quill, rango = q.getSelection(true);
    Dialogo.pedirTexto("Agregar vínculo", "https://", "Dirección (http:// o https://)").then((url) => {
      if (!url) return;
      if (!/^(https?:\/\/|mailto:)/i.test(url)) { avisoEstado("El vínculo debe empezar con http://, https:// o mailto:", true); return; }
      if (rango && rango.length) q.formatText(rango.index, rango.length, "link", url);
      else { q.insertText(rango ? rango.index : q.getLength(), url, "link", url); }
    });
  }

  function agregarImagen(e) {
    const archivo = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!archivo || !actual || !actual.quill) return;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(archivo.type)) { avisoEstado("Solo imágenes PNG, JPEG, WEBP o GIF", true); return; }
    if (archivo.size > MAX_IMAGEN) { avisoEstado("Cada imagen puede pesar hasta 2 MB", true); return; }
    const lector = new FileReader();
    lector.onload = () => {
      const q = actual.quill, ref = `t${++actual.contador}`;
      actual.nuevas[ref] = { nombre: archivo.name, datos: String(lector.result).split(",")[1] };
      const i = (q.getSelection(true) || { index: q.getLength() }).index;
      q.insertEmbed(i, "image", lector.result);
      q.formatText(i, 1, { alt: `nuevo:${ref}` });
      q.setSelection(i + 1, 0);
      avisoEstado("");
    };
    lector.readAsDataURL(archivo);
  }

  /** The editor's HTML with its images as <img data-adj="id"> (already stored) or <img data-nuevo="ref"> (to upload). */
  function descripcionParaGuardar() {
    if (!actual.quill) return { html: ($("ml-d-texto-plano") || {}).value || "", imagenes: [] };
    const caja = document.createElement("div");
    caja.innerHTML = actual.quill.root.innerHTML;
    const imagenes = [];
    caja.querySelectorAll("img").forEach((img) => {
      const m = /^(adj|nuevo):(\w+)$/.exec(img.getAttribute("alt") || "");
      if (!m) { img.remove(); return; }                    // an image of the web: not kept
      const marca = document.createElement("img");
      marca.setAttribute(m[1] === "adj" ? "data-adj" : "data-nuevo", m[2]);
      if (m[1] === "nuevo" && actual.nuevas[m[2]]) imagenes.push({ ref: m[2], ...actual.nuevas[m[2]] });
      img.replaceWith(marca);
    });
    return { html: caja.innerHTML, imagenes };
  }

  // ------------------------------------------------------------------ abrir, aceptar, cerrar
  async function abrir(op) {
    crear();
    if (actual) cerrar(true);
    actual = { op, estilo: JSON.parse(JSON.stringify(op.estilo || {})), nuevas: {}, contador: 0, lat: op.lat, lon: op.lon, quill: null };
    const caja = $("ml-dialogo");
    caja.hidden = false;
    caja.style.left = ""; caja.style.top = ""; caja.style.right = "";
    $("ml-d-titulo").textContent = op.titulo;
    poner("ml-d-nombre", op.nombre || "");
    $("ml-d-e-nombre").textContent = ""; $("ml-d-e-carpeta").textContent = ""; $("ml-d-e-coord").textContent = ""; avisoEstado("");
    $("ml-d-carpeta").innerHTML = (op.carpetas || []).map((c) => `<option value="${c.id}"${c.id === op.carpetaId ? " selected" : ""}>${esc(c.etiqueta)}</option>`).join("");
    $("ml-d-coords").hidden = !esPunto(op.tipo);
    $("ml-d-icono").hidden = op.tipo !== "marca";
    $("ml-d-pest-medidas").hidden = esPunto(op.tipo);
    $("ml-d-pest-red").hidden = !op.red;                                   // network elements: their own data first; their style comes from the type
    document.querySelector('.ml-d-pest[data-ml-pest="estilo"]').hidden = !!op.red;
    $("ml-d-red").innerHTML = op.red ? op.red.html : "";
    if (op.red) op.red.activar($("ml-d-red"));
    if (esPunto(op.tipo) && op.lat !== undefined) ponerCoordenada(op.lat, op.lon);
    if (op.vista) { poner("ml-d-v-lat", op.vista.lat); poner("ml-d-v-lon", op.vista.lon); poner("ml-d-v-zoom", op.vista.zoom); }
    else { poner("ml-d-v-lat", ""); poner("ml-d-v-lon", ""); poner("ml-d-v-zoom", ""); }
    notaVista();
    $("ml-d-medidas").innerHTML = "";
    panelEstilo();
    pintarIconoBoton();
    pestana(op.red ? "red" : "desc");
    actual.quill = crearQuill();
    const instancia = actual;
    const html = await cargarDescripcion(op.descripcionHtml, op.adjuntos, op.cargarAdjunto);
    if (actual === instancia && actual.quill && html) actual.quill.clipboard.dangerouslyPasteHTML(0, html);
    else if (actual === instancia && !actual.quill && html) $("ml-d-texto-plano").value = html.replace(/<[^>]+>/g, "");
    if (actual === instancia) { actual.quill && actual.quill.setSelection(0, 0); $("ml-d-nombre").focus(); $("ml-d-nombre").select(); }
    return { ponerCoordenada, ponerMedidas, cerrar: () => cerrar(false), get abierto() { return actual === instancia; } };
  }

  async function aceptar() {
    if (!actual) return;
    const op = actual.op;
    const nombre = $("ml-d-nombre").value.trim();
    $("ml-d-e-nombre").textContent = nombre ? "" : "Escriba el nombre";
    if (!nombre) { $("ml-d-nombre").focus(); return; }
    if (esPunto(op.tipo)) {
      const lat = Coordenadas.valor($("ml-d-lat").value), lon = Coordenadas.valor($("ml-d-lon").value);
      if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) { coordenadaEscrita(); return; }
      actual.lat = lat; actual.lon = lon;
    }
    const falla = op.red ? op.red.validar() : null;
    if (falla) { pestana("red"); avisoEstado(falla, true); return; }
    const { html, imagenes } = descripcionParaGuardar();
    const vista = leerVista();
    $("ml-d-aceptar").disabled = true;
    avisoEstado("Guardando…");
    let r;
    try {
      r = await op.alAceptar({ carpeta_id: Number($("ml-d-carpeta").value) || null, nombre, descripcion_html: html, imagenes, estilo: actual.estilo,
                               vista: vista || null, lat: actual.lat, lon: actual.lon });
    } catch (e) { r = { ok: false, error: String(e) }; }
    $("ml-d-aceptar").disabled = false;
    if (!r || !r.ok) { avisoEstado((r && r.error) || "No se pudo guardar", true); return; }
    cerrar(false);
  }

  function cerrar(cancelado) {
    if (!actual) return;
    const op = actual.op;
    actual = null;
    $("ml-dialogo").hidden = true;
    if (cancelado && op.alCancelar) op.alCancelar();
  }

  // ------------------------------------------------------------------ pedir un texto
  function pedirTexto(titulo, valor = "", etiqueta = "Nombre") {
    crear();
    return new Promise((resolver) => {
      const modal = $("ml-pedir");
      $("ml-pedir-titulo").textContent = titulo;
      $("ml-pedir-etiqueta").textContent = etiqueta;
      $("ml-pedir-valor").value = valor;
      modal.hidden = false;
      $("ml-pedir-valor").focus();
      $("ml-pedir-valor").select();
      const fin = (v) => { modal.hidden = true; $("ml-pedir-form").onsubmit = modal.onclick = modal.onkeydown = null; resolver(v); };
      $("ml-pedir-form").onsubmit = (e) => { e.preventDefault(); fin($("ml-pedir-valor").value.trim() || null); };
      modal.onclick = (e) => { if (e.target === modal || e.target.closest("[data-ml-pedir=cancelar]")) fin(null); };
      modal.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); fin(null); } };
    });
  }

  const Dialogo = { abrir, pedirTexto, cerrar: () => cerrar(true), get abierto() { return !!actual; } };
  window.Dialogo = Dialogo;
})();
