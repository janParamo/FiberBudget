/* App de campo: todo lo levantado en una sola lista (puntos y cables, enviados y sin enviar): filtro, explorar / organizar, búsqueda y su dibujo en el mapa. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const $ = (id) => document.getElementById(id);
  const M = () => window.CampoMapa;
  const TIPOS = ["poste", "mufa", "reserva", "solitaria", "cliente", "otro", "cable"];
  const ESTADOS = ["cola", "error", "pendiente", "editado", "aprobado", "rechazado"];
  let modo = "explorar";                                   // explorar | organizar
  let elegidos = new Set();

  const jornadaNombre = () => (C.estado.jornada ? C.estado.jornada.nombre : "Sin jornada");

  /* ---------------------------------------------------------------- los datos */
  function items(soloVisibles) {
    const e = C.estado, jor = jornadaNombre(), usuario = (e.cfg && e.cfg.persona) || "";
    const lista = [];
    e.trazos.forEach((t) => lista.push({ clase: "cable", origen: "servidor", ref: t, tipo: "cable", nombre: t.tipo_cable || "", notas: t.notas, estado: t.estado, fecha: t.capturado_en, jornada: jor, usuario: t.usuario || usuario,
      puntos: t.puntos.map(([lat, lon]) => ({ lat, lon })), longitud_m: t.longitud_m, modo: t.modo, hilos: t.hilos, tipo_cable: t.tipo_cable, lat: t.puntos[0][0], lon: t.puntos[0][1], id: t.id }));
    e.puntos.forEach((p) => lista.push({ clase: "punto", origen: "servidor", ref: p, tipo: p.tipo, subtipo: p.subtipo, nombre: p.nombre, notas: p.notas, lat: p.lat, lon: p.lon, estado: p.estado,
      fecha: p.capturado_en, jornada: jor, usuario, precision_m: p.precision_m, origen_coord: p.origen_coord, fotos: (p.fotos || []).length, motivo: p.motivo_rechazo, id: p.id }));
    e.cola.forEach((q) => {
      const estado = q.estado === "error" ? "error" : "cola";
      if (q.punto) lista.push({ clase: "punto", origen: "cola", ref: q, tipo: q.punto.tipo, subtipo: q.punto.subtipo, nombre: q.punto.nombre, notas: q.punto.notas, lat: q.punto.lat, lon: q.punto.lon, estado,
        fecha: q.punto.capturado_en, jornada: jor, usuario, precision_m: q.punto.precision_m, origen_coord: q.punto.origen_coord, fotos: (q.fotos || []).length, error: q.error });
      else if (q.trazo) lista.push({ clase: "cable", origen: "cola", ref: q, tipo: "cable", nombre: q.trazo.tipo_cable || "", notas: q.trazo.notas, estado, fecha: q.trazo.capturado_en, jornada: jor, usuario,
        puntos: q.trazo.puntos, modo: q.trazo.modo, hilos: q.trazo.hilos, tipo_cable: q.trazo.tipo_cable, lat: q.trazo.puntos[0].lat, lon: q.trazo.puntos[0].lon, error: q.error });
    });
    lista.sort((a, b) => String(b.fecha).localeCompare(String(a.fecha)));
    return soloVisibles ? lista.filter(visible) : lista;
  }

  function visible(i) {
    const f = C.estado.filtro;
    return (!f.tipos || f.tipos.includes(i.tipo)) && (!f.estados || f.estados.includes(i.estado)) && (!f.jornadas || f.jornadas.includes(i.jornada));
  }

  const hayFiltro = () => { const f = C.estado.filtro; return !!(f.tipos || f.estados || f.jornadas); };

  /* ---------------------------------------------------------------- el mapa */
  function pintar() {
    if (!M() || !M().leaflet()) return;
    M().limpiarMarcas();
    const todos = items(false), vistos = todos.filter(visible);
    vistos.forEach((i) => {
      const abrir = () => C.tarjeta.mostrar(i);
      if (i.clase === "cable") M().marcarLinea(i.puntos, i.estado, abrir);
      else M().marcar({ lat: i.lat, lon: i.lon, tipo: i.tipo, estado: i.estado, nombre: i.nombre }, abrir);
    });
    $("contador").textContent = String(vistos.length);
    $("b-filtro").classList.toggle("activo", hayFiltro());
    if (C.panel.actual() === "p-lista") pintarLista();
  }

  /* ---------------------------------------------------------------- filtro */
  async function filtrar() {
    const f = C.estado.filtro;
    const fila = (k, valor, texto, marcado) => `<label class="dlg-check"><input type="checkbox" data-${k}="${valor}"${marcado ? " checked" : ""}> ${C.esc(texto)}</label>`;
    const r = await C.dialogo.mostrar({
      titulo: "Filtrar lo que se ve",
      cuerpo: `<h4>Tipo</h4>${TIPOS.map((t) => fila("t", t, C.ETIQUETA[t], !f.tipos || f.tipos.includes(t))).join("")}
        <h4>Estado</h4>${ESTADOS.map((s) => fila("s", s, C.ESTADO[s], !f.estados || f.estados.includes(s))).join("")}`,
      botones: [{ texto: "Quitar filtro", valor: "limpiar" }, { texto: "Cancelar", valor: null }, { texto: "Aceptar", valor: "leer", primario: true }],
      leer: (raiz) => ({ tipos: [...raiz.querySelectorAll("[data-t]:checked")].map((c) => c.dataset.t), estados: [...raiz.querySelectorAll("[data-s]:checked")].map((c) => c.dataset.s) }),
    });
    if (!r) return;
    if (r === "limpiar") C.estado.filtro = { tipos: null, estados: null, jornadas: null };
    else C.estado.filtro = { tipos: r.tipos.length === TIPOS.length ? null : r.tipos, estados: r.estados.length === ESTADOS.length ? null : r.estados, jornadas: null };
    pintar();
  }

  /* ---------------------------------------------------------------- explorar / organizar */
  const sub = (i) => [C.ETIQUETA[i.tipo], C.subtipoTexto(i.tipo, i.subtipo), i.clase === "cable" ? window.CampoTrazo.texto(i.longitud_m != null ? i.longitud_m : largo(i.puntos)) : "",
    i.hilos ? `${i.hilos} hilos` : "", i.fotos ? `${i.fotos} foto${i.fotos > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
  const largo = (pts) => { const t = window.CampoTrazo.crear(); pts.forEach((p) => t.agregar(p.lat, p.lon)); return t.longitud(); };

  function filaHtml(i, k) {
    const nombre = i.clase === "cable" ? `Cable ${i.nombre}`.trim() : i.nombre;
    return `<li class="fila-item" data-k="${k}">
      ${modo === "organizar" ? `<input type="checkbox" class="fi-marca" data-k="${k}" ${elegidos.has(k) ? "checked" : ""} aria-label="Elegir ${C.esc(nombre)}">` : ""}
      <span class="fi-pin">${i.clase === "cable" ? C.iconos.svg("ruta") : M().pinHtml(i.tipo, i.estado)}</span>
      <span class="fi-texto"><b>${C.esc(nombre)}</b><small>${C.esc(sub(i))}</small><small>${i.fecha ? C.esc(C.fecha(i.fecha)) : ""}</small>
        ${i.estado === "rechazado" && i.motivo ? `<small class="error">Rechazado: ${C.esc(i.motivo)}</small>` : ""}${i.error ? `<small class="error">${C.esc(i.error)}</small>` : ""}</span>
      <span class="estado ${C.esc(i.estado)}">${C.esc(C.ESTADO[i.estado] || i.estado)}</span></li>`;
  }

  let ultimaLista = [];
  function pintarLista() {
    ultimaLista = items(true);
    const cuerpo = $("l-cuerpo");
    if (!ultimaLista.length) { cuerpo.innerHTML = `<p class="vacio">${hayFiltro() ? "Nada coincide con el filtro." : "Todavía no hay nada. Toque + en el mapa para agregar un punto."}</p>`; actualizarSeleccion(); return; }
    const grupos = new Map();
    ultimaLista.forEach((i, k) => { if (!grupos.has(i.jornada)) grupos.set(i.jornada, []); grupos.get(i.jornada).push([i, k]); });
    cuerpo.innerHTML = [...grupos.entries()].map(([j, l]) => `<h3 class="grupo">${C.esc(j)} <small>${l.length}</small></h3><ul class="lista-items">${l.map(([i, k]) => filaHtml(i, k)).join("")}</ul>`).join("");
    cuerpo.onclick = (e) => {
      const fila = e.target.closest(".fila-item");
      if (!fila) return;
      const k = Number(fila.dataset.k);
      if (modo === "organizar") { if (elegidos.has(k)) elegidos.delete(k); else elegidos.add(k); pintarLista(); return; }
      irA(ultimaLista[k]);
    };
    actualizarSeleccion();
  }

  function actualizarSeleccion() {
    $("l-seleccion").hidden = modo !== "organizar";
    $("l-sel-texto").textContent = `${elegidos.size} elegido${elegidos.size === 1 ? "" : "s"}`;
    $("l-modo-texto").textContent = modo === "organizar" ? "Organizar" : "Explorar";
  }

  function irA(i) {
    C.panel.cerrar();
    if (i.clase === "cable") M().ajustarA(i.puntos); else M().irA(i.lat, i.lon);
    C.tarjeta.mostrar(i);
  }

  async function borrarElegidos() {
    const lista = [...elegidos].map((k) => ultimaLista[k]).filter(Boolean), borrables = lista.filter(C.editor.puedeBorrar);
    if (!lista.length) { C.aviso("Elija lo que quiere eliminar"); return; }
    if (!borrables.length) { C.aviso("Lo que ya se revisó no se puede eliminar", "malo"); return; }
    const aviso = borrables.length < lista.length ? ` (${lista.length - borrables.length} ya revisados no se eliminan)` : "";
    if (!(await C.dialogo.confirmar(`¿Eliminar ${borrables.length} elemento${borrables.length === 1 ? "" : "s"}?${aviso}`, "Esta acción no se puede deshacer.", [{ texto: "Eliminar", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) return;
    let fallos = 0;
    for (const i of borrables) {
      try {
        if (i.origen === "cola") await window.CampoCola.quitar(i.ref.uuid);
        else if (i.clase === "cable") await window.CampoApi.api.borrarTrazo(i.ref.id);
        else await window.CampoApi.api.borrarPunto(i.ref.id);
      } catch (e) { fallos++; }
    }
    elegidos = new Set();
    await C.app.leerCola(); await C.app.cargarPuntos();
    C.aviso(fallos ? `${fallos} no se pudieron eliminar (¿sin conexión?)` : "Eliminado", fallos ? "malo" : "ok");
  }

  async function cambiarModo() {
    const r = await C.dialogo.opciones("Modo de la lista", [{ valor: "explorar", texto: "Explorar", detalle: "Tocar para ver en el mapa", icono: "lista" }, { valor: "organizar", texto: "Organizar", detalle: "Elegir varios para eliminarlos", icono: "todo" }], modo);
    if (!r) return;
    modo = r; elegidos = new Set(); pintarLista();
  }

  function abrir() { modo = "explorar"; elegidos = new Set(); C.panel.abrir("p-lista"); pintarLista(); }

  /* ---------------------------------------------------------------- búsqueda */
  function coordenada(t) {
    const m = String(t).match(/^\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$/);
    if (!m) return null;
    const lat = Number(m[1].replace(",", ".")), lon = Number(m[2].replace(",", "."));
    return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat, lon } : null;
  }

  function buscar(texto) {
    const q = texto.trim().toLowerCase(), cuerpo = $("bu-cuerpo");
    if (!q) { cuerpo.innerHTML = '<p class="vacio">Escriba el nombre de un punto o poste, o unas coordenadas («12.13, -86.25»).</p>'; return; }
    const c = coordenada(q), propios = items(false).filter((i) => String(i.nombre).toLowerCase().includes(q) || (i.notas || "").toLowerCase().includes(q)).slice(0, 30);
    const red = window.CampoRed.buscar(q, 30);
    const html = [];
    if (c) html.push(`<h3 class="grupo">Coordenadas</h3><ul class="lista-items"><li class="fila-item" data-coord="1"><span class="fi-pin">${C.iconos.svg("ubicacion")}</span><span class="fi-texto"><b>Ir a ${C.esc(C.fmt.coord(c.lat, c.lon))}</b></span></li></ul>`);
    if (propios.length) html.push(`<h3 class="grupo">Mis puntos <small>${propios.length}</small></h3><ul class="lista-items">${propios.map((i, k) => `<li class="fila-item" data-p="${k}"><span class="fi-pin">${i.clase === "cable" ? C.iconos.svg("ruta") : M().pinHtml(i.tipo, i.estado)}</span><span class="fi-texto"><b>${C.esc(i.nombre || "Cable")}</b><small>${C.esc(sub(i))}</small></span></li>`).join("")}</ul>`);
    if (red.length) html.push(`<h3 class="grupo">Red existente <small>${red.length}</small></h3><ul class="lista-items">${red.map((p, k) => `<li class="fila-item" data-r="${k}"><span class="fi-pin">${C.iconos.svg("red")}</span><span class="fi-texto"><b>${C.esc(p.n || "(sin nombre)")}</b><small>${C.esc(p.t || "")}</small></span></li>`).join("")}</ul>`);
    if (!html.length) html.push('<p class="vacio">No se encontró nada. La red existente solo se busca en la zona que ya se cargó en el mapa.</p>');
    cuerpo.innerHTML = html.join("");
    cuerpo.onclick = (e) => {
      const f = e.target.closest(".fila-item");
      if (!f) return;
      C.panel.cerrar();
      if (f.dataset.coord) { M().irA(c.lat, c.lon, 19); M().ponerTemporal(c.lat, c.lon); }
      else if (f.dataset.p != null) irA(propios[Number(f.dataset.p)]);
      else { const p = red[Number(f.dataset.r)]; M().irA(p.lat, p.lon, 19); C.tarjeta.mostrarRed(p); }
    };
  }

  function abrirBusqueda() { C.panel.abrir("p-buscar"); $("bu-texto").value = ""; buscar(""); setTimeout(() => $("bu-texto").focus(), 50); }

  function conectar() {
    $("b-filtro").onclick = filtrar; $("l-filtro").onclick = filtrar;
    $("b-lista").onclick = abrir;
    $("l-atras").onclick = () => C.panel.cerrar();
    $("l-modo").onclick = cambiarModo;
    $("l-buscar").onclick = abrirBusqueda; $("b-buscar").onclick = abrirBusqueda;
    $("l-todo").onclick = () => { elegidos = elegidos.size === ultimaLista.length ? new Set() : new Set(ultimaLista.map((_, k) => k)); pintarLista(); };
    $("l-borrar").onclick = borrarElegidos;
    $("bu-atras").onclick = () => C.panel.cerrar();
    $("bu-texto").addEventListener("input", (e) => buscar(e.target.value));
    $("b-compartir").onclick = () => C.exportar.abrir();
  }

  C.lista = { items, visible, pintar, filtrar, abrir, abrirBusqueda, conectar, coordenada };
})();
