/* App de campo: la tarjeta que sale al tocar algo del mapa y las pantallas para ver / editar un punto o un cable (nuevos, sin enviar o ya enviados).
 *
 * Un `item` es lo que arma Campo.lista.items(): {clase: "punto" | "cable", origen: "cola" | "servidor", ref, tipo, subtipo, nombre, notas, lat, lon, puntos, estado, fecha, jornada, ...}. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const { api, ErrorApi, uuid, comprimir } = window.CampoApi;
  const $ = (id) => document.getElementById(id);
  const M = () => window.CampoMapa, Cola = () => window.CampoCola;
  const cfg = () => C.estado.cfg;

  let ed = null;                                           // the point being edited
  let cb = null;                                           // the cable being edited
  let tarjetaItem = null;                                  // what the bottom card shows

  const coordTexto = (lat, lon) => C.fmt.coord(lat, lon);
  const aviso = (t, tipo) => C.aviso(t, tipo);

  /* ---------------------------------------------------------------- tarjeta inferior */
  function infoDe(item) {
    const partes = [C.ETIQUETA[item.tipo] || "Cable"];
    const sub = C.subtipoTexto(item.tipo, item.subtipo);
    if (sub) partes.push(sub);
    if (item.clase === "cable") partes.push(window.CampoTrazo.texto(item.longitud_m != null ? item.longitud_m : largoDe(item.puntos)));
    if (item.estado) partes.push(C.ESTADO[item.estado] || item.estado);
    return partes.join(" · ");
  }

  const largoDe = (pts) => { const t = window.CampoTrazo.crear(); pts.forEach((p) => t.agregar(p.lat, p.lon)); return t.longitud(); };

  function mostrar(item) {
    tarjetaItem = { item };
    $("t-titulo").textContent = item.clase === "cable" ? `Cable ${item.nombre || ""}`.trim() : item.nombre || C.ETIQUETA[item.tipo];
    $("t-fecha").textContent = item.fecha ? C.fecha(item.fecha) : "";
    $("t-detalle").textContent = infoDe(item) + (item.clase === "punto" ? ` · ${coordTexto(item.lat, item.lon)}` : "");
    $("t-editar").hidden = false; $("t-mas").hidden = false;
    $("tarjeta").hidden = false;
    document.body.classList.add("con-tarjeta");
  }

  /* un poste o mufa de la red de referencia: solo se ve y se puede ir hacia él */
  function mostrarRed(p) {
    tarjetaItem = { red: p };
    $("t-titulo").textContent = p.n || "(sin nombre)";
    $("t-fecha").textContent = "Red existente (solo lectura)";
    $("t-detalle").textContent = `${p.t || "Elemento"} · ${coordTexto(p.lat, p.lon)}`;
    $("t-editar").hidden = true; $("t-mas").hidden = true;
    $("tarjeta").hidden = false;
    document.body.classList.add("con-tarjeta");
  }

  function ocultar() {
    tarjetaItem = null;
    const t = $("tarjeta");
    if (t) t.hidden = true;
    document.body.classList.remove("con-tarjeta");
  }

  const datosTarjeta = () => (tarjetaItem && (tarjetaItem.red ? { lat: tarjetaItem.red.lat, lon: tarjetaItem.red.lon, nombre: tarjetaItem.red.n } : tarjetaItem.item.clase === "cable"
    ? { lat: tarjetaItem.item.puntos[0].lat, lon: tarjetaItem.item.puntos[0].lon, nombre: "Cable" } : tarjetaItem.item));

  function textoDetalle(item) {
    const l = [item.nombre || C.ETIQUETA[item.tipo], infoDe(item)];
    if (item.clase === "punto") l.push(`${coordTexto(item.lat, item.lon)}`, `https://maps.google.com/?q=${item.lat},${item.lon}`);
    if (item.notas) l.push(item.notas);
    return l.join("\n");
  }

  async function navegar(d) {
    let como = C.ajustes.obtener("navegacion");
    if (como === "preguntar") {
      como = await C.dialogo.opciones("Cómo llegar", [{ valor: "google", texto: "Google Maps", icono: "navegar" }, { valor: "apple", texto: "Mapas de Apple", icono: "navegar" },
        { valor: "waze", texto: "Waze", icono: "navegar" }, { valor: "copiar", texto: "Copiar las coordenadas", icono: "copiar" }]);
      if (!como) return;
    }
    const ll = `${d.lat},${d.lon}`;
    if (como === "copiar") { aviso((await C.copiar(ll)) ? "Coordenadas copiadas" : "No se pudo copiar", "ok"); return; }
    const url = como === "apple" ? `https://maps.apple.com/?daddr=${ll}` : como === "waze" ? `https://waze.com/ul?ll=${ll}&navigate=yes` : `https://www.google.com/maps/dir/?api=1&destination=${ll}`;
    window.open(url, "_blank", "noopener");
  }

  async function borrar(item) {
    if (!(await C.dialogo.confirmar(`¿Eliminar «${item.nombre || "el cable"}»?`, "Esta acción no se puede deshacer.", [{ texto: "Eliminar", valor: true, primario: true }, { texto: "Cancelar", valor: false }]))) return false;
    try {
      if (item.origen === "cola") await Cola().quitar(item.ref.uuid);
      else if (item.clase === "cable") await api.borrarTrazo(item.ref.id);
      else await api.borrarPunto(item.ref.id);
    } catch (e) {
      if (!(e instanceof ErrorApi)) throw e;
      aviso(e.sinConexion ? "Sin conexión: no se puede borrar algo ya enviado" : e.message, "malo");
      return false;
    }
    await C.app.leerCola();
    if (item.origen !== "cola") await C.app.cargarPuntos();
    ocultar(); aviso("Eliminado", "ok");
    return true;
  }

  const puedeBorrar = (item) => item.origen === "cola" || item.estado === "pendiente";

  async function masOpciones(item) {
    const lista = [{ valor: "copiar", texto: "Copiar los detalles", icono: "copiar" }];
    if (puedeBorrar(item)) lista.push({ valor: "borrar", texto: "Eliminar", icono: "basura" });
    const r = await C.dialogo.opciones(item.nombre || "Cable", lista);
    if (r === "copiar") aviso((await C.copiar(textoDetalle(item))) ? "Copiado" : "No se pudo copiar", "ok");
    else if (r === "borrar") await borrar(item);
  }

  /* ---------------------------------------------------------------- un punto */
  const esSoloLectura = () => !!ed && ed.modo === "servidor" && ed.ref.estado !== "pendiente";

  function sugerirNombre(tipo) {
    const n = C.estado.puntos.filter((p) => p.tipo === tipo).length + C.estado.cola.filter((e) => e.punto && e.punto.tipo === tipo).length + 1;
    return `${C.ETIQUETA[tipo]} ${n}`;
  }

  function marcarSucio() { if (ed) ed.sucio = true; }

  function pintarTipo() {
    document.querySelectorAll("#ed-tipos [data-ed-tipo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.edTipo === ed.tipo)));
    $("ed-subtipo-poste").hidden = ed.tipo !== "poste";
    $("ed-subtipo-mufa").hidden = ed.tipo !== "mufa";
    $("ed-icono").innerHTML = window.CampoMapa.pinHtml(ed.tipo, ed.estado || "cola");
    $("ed-titulo").textContent = C.ETIQUETA[ed.tipo];
  }

  function subtipoElegido() {
    if (ed.tipo === "poste") return $("ed-poste").value || null;
    if (ed.tipo === "mufa") { const c = $("ed-mufa-capacidad").value, f = $("ed-mufa-formato").value; return c ? (f ? `${c} ${f}` : c) : null; }
    return null;
  }

  function ponerSubtipo(tipo, sub) {
    $("ed-poste").value = ""; $("ed-mufa-capacidad").value = ""; $("ed-mufa-formato").value = "";
    if (!sub) return;
    if (tipo === "poste") $("ed-poste").value = sub;
    else if (tipo === "mufa") { const [c, f] = String(sub).split(" "); $("ed-mufa-capacidad").value = c || ""; $("ed-mufa-formato").value = f || ""; }
  }

  function pintarCoord() {
    $("ed-coord").textContent = `${coordTexto(ed.coord.lat, ed.coord.lon)}${ed.coord.origen_coord === "gps" && ed.coord.precision_m != null ? ` · GPS ±${Math.round(ed.coord.precision_m)} m` : ed.coord.origen_coord === "mapa" ? " · marcado en el mapa" : ""}`;
    const cerca = ed.modo === "nuevo" ? window.CampoRed.cercano(ed.coord.lat, ed.coord.lon, cfg().duplicado_m || 5) : null;
    $("ed-cerca").textContent = cerca ? `Ya hay algo aquí: ${cerca.n || cerca.t} (${cerca.t || "red"}) a ${cerca.distancia_m.toFixed(1)} m. ¿Es el mismo?` : "";
    $("ed-cerca").hidden = !cerca;
  }

  function pintarExtra() {
    const e = ed.ref, l = [];
    if (ed.modo !== "nuevo") {
      if (ed.jornada) l.push(`Jornada: ${ed.jornada}`);
      l.push(`Estado: ${C.ESTADO[ed.estado] || ed.estado}`);
      if (e && e.motivo_rechazo) l.push(`Motivo del rechazo: ${e.motivo_rechazo}`);
      if (ed.modo === "cola" && e && e.error) l.push(`Error: ${e.error}`);
    } else l.push("Se guarda en el teléfono y se envía cuando haya señal.");
    $("ed-extra").textContent = l.join("\n");
  }

  async function pintarFotos() {
    const caja = $("ed-fotos");
    caja.innerHTML = "";
    ed.fotos.forEach((f, i) => {
      const fig = document.createElement("figure");
      fig.innerHTML = `<img alt="Foto ${i + 1}" src="${f.url || ""}">${esSoloLectura() ? "" : `<button type="button" aria-label="Quitar la foto ${i + 1}">✕</button>`}`;
      const b = fig.querySelector("button");
      if (b) b.onclick = () => quitarFoto(i);
      caja.appendChild(fig);
    });
  }

  async function quitarFoto(i) {
    const f = ed.fotos[i];
    if (f.existente) { aviso("Las fotos ya enviadas no se pueden quitar desde aquí"); return; }
    if (f.url) URL.revokeObjectURL(f.url);
    ed.fotos.splice(i, 1); marcarSucio(); pintarFotos();
  }

  async function agregarFotos(archivos) {
    for (const archivo of archivos) {
      if (!ed) return;
      if (ed.fotos.length >= cfg().fotos_por_punto) { aviso(`Un punto admite hasta ${cfg().fotos_por_punto} fotos`, "malo"); break; }
      try {
        const blob = await comprimir(archivo);
        if (blob.size > cfg().foto_max_bytes) { aviso("La foto sigue siendo muy pesada", "malo"); continue; }
        ed.fotos.push({ blob, url: URL.createObjectURL(blob), uuid: uuid(), nueva: true });
        marcarSucio();
      } catch (e) { aviso(e.message || "No se pudo leer la foto", "malo"); }
    }
    if (ed) pintarFotos();
  }

  const errorEd = (t) => { const e = $("ed-error"); e.textContent = t || ""; e.hidden = !t; };

  function abrirFormulario() {
    pintarTipo(); pintarCoord(); pintarExtra(); pintarFotos();
    $("ed-fecha").textContent = C.fecha(ed.fecha || Date.now());
    const lectura = esSoloLectura();
    document.querySelectorAll("#p-editor input[type=text], #p-editor textarea, #p-editor select").forEach((c) => { c.disabled = lectura; });
    document.querySelectorAll("#ed-tipos button, #p-editor .fila label.btn").forEach((c) => { c.classList.toggle("deshabilitado", lectura); if (c.tagName === "BUTTON") c.disabled = lectura; });
    $("ed-coord-editar").hidden = lectura; $("ed-guardar").hidden = lectura; $("ed-mas").hidden = ed.modo === "nuevo";
    errorEd("");
    ed.sucio = false;
    C.panel.abrir("p-editor");
    $("p-editor").querySelector(".p-cuerpo").scrollTop = 0;
  }

  function nuevoPunto(tipo, coord) {
    ed = { modo: "nuevo", tipo, coord, uuid: uuid(), fotos: [], estado: "cola", fecha: Date.now(), guardando: false, sucio: true };
    $("ed-nombre").value = sugerirNombre(tipo); $("ed-notas").value = ""; ponerSubtipo(tipo, null);
    abrirFormulario();
    ed.sucio = true;
  }

  async function abrirPunto(item) {
    ocultar();
    M().irA(item.lat, item.lon);
    ed = { modo: item.origen === "cola" ? "cola" : "servidor", ref: item.ref, tipo: item.tipo, estado: item.estado, jornada: item.jornada, fecha: item.fecha, guardando: false, fotos: [],
      coord: { lat: item.lat, lon: item.lon, precision_m: item.precision_m, altitud: item.ref.altitud != null ? item.ref.altitud : (item.ref.punto && item.ref.punto.altitud), origen_coord: item.origen_coord || (item.precision_m != null ? "gps" : "mapa") } };
    $("ed-nombre").value = item.nombre || ""; $("ed-notas").value = item.notas || ""; ponerSubtipo(item.tipo, item.subtipo);
    if (ed.modo === "cola") ed.fotos = (item.ref.fotos || []).map((f) => ({ blob: f.blob, url: URL.createObjectURL(f.blob), uuid: f.uuid, enviada: f.enviada, existente: false }));
    abrirFormulario();
    if (ed.modo === "servidor") {                                  // already-sent photos: thumbnails from the office (when there is signal)
      const actual = ed;
      for (const f of item.ref.fotos || []) {
        try { const b = await api.foto(f.id, true); if (ed !== actual) return; actual.fotos.push({ id: f.id, existente: true, url: URL.createObjectURL(b) }); pintarFotos(); }
        catch (e) { actual.fotos.push({ id: f.id, existente: true, url: "" }); pintarFotos(); }
      }
    }
  }

  function cerrarPunto() {
    if (ed) ed.fotos.forEach((f) => { if (f.url && !f.existente) URL.revokeObjectURL(f.url); });
    ed = null;
    C.panel.cerrar();
  }

  async function pedirSalida() {
    if (!ed) return;
    if (!ed.sucio || esSoloLectura() || ed.modo === "nuevo" && !ed.sucio) { cerrarPunto(); return; }
    const r = await C.dialogo.confirmar("¿Guardar los cambios?", "", [{ texto: "Sí", valor: "si", primario: true }, { texto: "No", valor: "no" }, { texto: "Cancelar", valor: "cancelar" }]);
    if (r === "si") await guardarPunto();
    else if (r === "no") cerrarPunto();
  }

  async function guardarPunto() {
    if (!ed || ed.guardando) return;
    const nombre = $("ed-nombre").value.trim();
    if (!nombre) { errorEd("Escriba el nombre del punto."); return; }
    ed.guardando = true; errorEd("");
    const campos = { tipo: ed.tipo, subtipo: subtipoElegido(), nombre, notas: $("ed-notas").value, lat: ed.coord.lat, lon: ed.coord.lon, origen_coord: ed.coord.origen_coord };
    try {
      if (ed.modo === "nuevo") {
        const jornada = await C.app.asegurarJornada();
        const entrada = { uuid: ed.uuid, creado: Date.now(), puntoId: null, estado: "cola", error: null, intentos: 0,
          punto: { uuid_cliente: ed.uuid, jornada_id: jornada ? jornada.id : null, ...campos, precision_m: ed.coord.precision_m, altitud: ed.coord.altitud,
            capturado_en: new Date(ed.coord.hora || Date.now()).toISOString() },
          fotos: ed.fotos.map((x) => ({ uuid: x.uuid, blob: x.blob, enviada: false })) };
        await Cola().agregar(entrada);
      } else if (ed.modo === "cola") {
        const e = (await Cola().obtener(ed.ref.uuid)) || ed.ref;
        Object.assign(e.punto, campos, { precision_m: ed.coord.precision_m, altitud: ed.coord.altitud });
        e.fotos = ed.fotos.filter((x) => x.uuid).map((x) => ({ uuid: x.uuid, blob: x.blob, enviada: !!x.enviada }));
        e.estado = "cola"; e.error = null;
        await Cola().actualizar(e);
      } else {
        const p = ed.ref;
        await api.editarPunto(p.id, p.version, campos.tipo === p.tipo ? { ...campos, tipo: undefined } : campos);
        for (const f of ed.fotos.filter((x) => x.nueva)) await api.subirFoto(p.id, f.blob, f.uuid);
      }
    } catch (e) {
      ed.guardando = false;
      if (!(e instanceof ErrorApi)) { errorEd("No se pudo guardar en el teléfono (¿poco espacio o modo privado?). No cierre esta pantalla."); return; }
      errorEd(e.sinConexion ? "Sin conexión: no se puede cambiar un punto ya enviado." : e.estado === 409 ? "Alguien cambió este punto; ciérrelo y ábralo otra vez." : (e.errores && Object.values(e.errores)[0]) || e.message);
      return;
    }
    const modo = ed.modo;
    cerrarPunto();
    await C.app.leerCola();
    if (modo === "servidor") { await C.app.cargarPuntos(); aviso("Punto actualizado", "ok"); }
    else { aviso(`«${nombre}» guardado en el teléfono`, "ok"); C.app.registrarSync(); C.app.enviarCola(false); }
  }

  function cambiarPosicion() {
    if (!ed || esSoloLectura()) return;
    const guardado = { nombre: $("ed-nombre").value, notas: $("ed-notas").value, poste: $("ed-poste").value, cap: $("ed-mufa-capacidad").value, fmt: $("ed-mufa-formato").value };
    const actual = ed;
    C.panel.cerrar();
    C.captura.ajustar(actual.coord, (nueva) => {
      ed = actual;
      if (nueva) { actual.coord = { ...actual.coord, ...nueva }; actual.sucio = true; }
      C.panel.abrir("p-editor");
      $("ed-nombre").value = guardado.nombre; $("ed-notas").value = guardado.notas; $("ed-poste").value = guardado.poste; $("ed-mufa-capacidad").value = guardado.cap; $("ed-mufa-formato").value = guardado.fmt;
      pintarCoord();
    });
  }

  async function menuPunto() {
    if (!ed || ed.modo === "nuevo") return;
    const item = { clase: "punto", origen: ed.modo === "cola" ? "cola" : "servidor", ref: ed.ref, tipo: ed.tipo, nombre: $("ed-nombre").value, notas: $("ed-notas").value, estado: ed.estado, lat: ed.coord.lat, lon: ed.coord.lon };
    const r = await C.dialogo.opciones(item.nombre, [{ valor: "copiar", texto: "Copiar los detalles", icono: "copiar" }].concat(puedeBorrar(item) ? [{ valor: "borrar", texto: "Eliminar", icono: "basura" }] : []));
    if (r === "copiar") aviso((await C.copiar(textoDetalle(item))) ? "Copiado" : "No se pudo copiar", "ok");
    else if (r === "borrar" && (await borrar(item))) { ed = null; C.panel.cerrar(); }
  }

  /* ---------------------------------------------------------------- un cable */
  const errorCb = (t) => { const e = $("cb-error"); e.textContent = t || ""; e.hidden = !t; };
  const cbSoloLectura = () => !!cb && cb.modo === "servidor" && cb.ref.estado !== "pendiente";

  function pintarCableTipo() { document.querySelectorAll("#cb-tipos [data-cb-tipo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cbTipo === (cb.tipo_cable || "")))); }

  function abrirFormularioCable() {
    const lectura = cbSoloLectura();
    $("cb-resumen").textContent = cb.resumen;
    pintarCableTipo();
    $("cb-fecha").textContent = C.fecha(cb.fecha || Date.now());
    const l = [];
    if (cb.modo !== "nuevo") { if (cb.jornada) l.push(`Jornada: ${cb.jornada}`); l.push(`Estado: ${C.ESTADO[cb.estado] || cb.estado}`); if (cb.ref.motivo_rechazo) l.push(`Motivo del rechazo: ${cb.ref.motivo_rechazo}`); if (cb.modo === "cola" && cb.ref.error) l.push(`Error: ${cb.ref.error}`); }
    else l.push("Se guarda en el teléfono y se envía cuando haya señal.");
    $("cb-extra").textContent = l.join("\n");
    $("cb-hilos").disabled = $("cb-notas").disabled = lectura;
    document.querySelectorAll("#cb-tipos button").forEach((b) => { b.disabled = lectura; });
    $("cb-guardar").hidden = lectura; $("cb-mas").hidden = cb.modo === "nuevo";
    errorCb(""); cb.sucio = cb.modo === "nuevo";
    C.panel.abrir("p-cable");
  }

  function nuevoCable(tr) {
    cb = { modo: "nuevo", tr, tipo_cable: C.leer("campo.ultimoCable") || "", fecha: Date.now(), estado: "cola", guardando: false,
      resumen: `${tr.n()} puntos · ${window.CampoTrazo.texto(tr.longitud())} · ${tr.modo()}` };
    $("cb-hilos").value = ""; $("cb-notas").value = "";
    M().pintarTrazo(tr.vertices(), -1);
    abrirFormularioCable();
  }

  function abrirCable(item) {
    ocultar();
    M().ajustarA(item.puntos);
    cb = { modo: item.origen === "cola" ? "cola" : "servidor", ref: item.ref, item, tipo_cable: item.tipo_cable || "", estado: item.estado, jornada: item.jornada, fecha: item.fecha, guardando: false,
      resumen: `${item.puntos.length} puntos · ${window.CampoTrazo.texto(item.longitud_m != null ? item.longitud_m : largoDe(item.puntos))}${item.modo ? " · " + item.modo : ""}` };
    $("cb-hilos").value = item.hilos ? String(item.hilos) : ""; $("cb-notas").value = item.notas || "";
    abrirFormularioCable();
  }

  function cerrarCable(descartarTrazo) {
    cb = null;
    if (descartarTrazo) M().limpiarTrazo();
    C.panel.cerrar();
  }

  async function salirCable() {
    if (!cb) return;
    if (cb.modo === "nuevo") {
      const r = await C.dialogo.confirmar("¿Guardar el cable?", "", [{ texto: "Sí", valor: "si", primario: true }, { texto: "No", valor: "no" }, { texto: "Cancelar", valor: "cancelar" }]);
      if (r === "si") await guardarCable(); else if (r === "no") cerrarCable(true);
      return;
    }
    cerrarCable(false);
  }

  async function guardarCable() {
    if (!cb || cb.guardando) return;
    cb.guardando = true; errorCb("");
    const hilos = $("cb-hilos").value, datos = { tipo_cable: cb.tipo_cable || null, hilos: hilos ? Number(hilos) : null, notas: $("cb-notas").value };
    try {
      if (cb.modo === "nuevo") {
        const jornada = await C.app.asegurarJornada(), tr = cb.tr, id = uuid();
        await Cola().agregar({ uuid: id, creado: Date.now(), estado: "cola", error: null, intentos: 0, fotos: [],
          trazo: { uuid_cliente: id, jornada_id: jornada ? jornada.id : null, modo: tr.modo(), ...datos, puntos: tr.puntos(), postes: tr.postes(), capturado_en: new Date().toISOString() } });
        C.guardar("campo.ultimoCable", cb.tipo_cable || null);
      } else if (cb.modo === "cola") {
        const e = (await Cola().obtener(cb.ref.uuid)) || cb.ref;
        Object.assign(e.trazo, datos); e.estado = "cola"; e.error = null;
        await Cola().actualizar(e);
      } else await api.editarTrazo(cb.ref.id, cb.ref.version, datos);
    } catch (e) {
      cb.guardando = false;
      if (!(e instanceof ErrorApi)) { errorCb("No se pudo guardar en el teléfono. No cierre esta pantalla."); return; }
      errorCb(e.sinConexion ? "Sin conexión: no se puede cambiar un cable ya enviado." : e.estado === 409 ? "Alguien cambió este cable; ciérrelo y ábralo otra vez." : (e.errores && Object.values(e.errores)[0]) || e.message);
      return;
    }
    const modo = cb.modo, largo = cb.resumen.split(" · ")[1];
    cerrarCable(true);
    await C.app.leerCola();
    if (modo === "servidor") { await C.app.cargarPuntos(); aviso("Cable actualizado", "ok"); }
    else { aviso(`Cable de ${largo} guardado en el teléfono`, "ok"); C.app.registrarSync(); C.app.enviarCola(false); }
  }

  async function menuCable() {
    if (!cb || cb.modo === "nuevo") return;
    const item = { ...cb.item, notas: $("cb-notas").value };
    const r = await C.dialogo.opciones("Cable", [{ valor: "copiar", texto: "Copiar los detalles", icono: "copiar" }].concat(puedeBorrar(item) ? [{ valor: "borrar", texto: "Eliminar", icono: "basura" }] : []));
    if (r === "copiar") aviso((await C.copiar(textoDetalle(item))) ? "Copiado" : "No se pudo copiar", "ok");
    else if (r === "borrar" && (await borrar(item))) { cb = null; C.panel.cerrar(); }
  }

  /* ---------------------------------------------------------------- enlaces */
  function conectar() {
    $("t-editar").onclick = () => { if (!tarjetaItem || !tarjetaItem.item) return; const i = tarjetaItem.item; if (i.clase === "cable") abrirCable(i); else abrirPunto(i); };
    $("t-copiar").onclick = async () => { if (!tarjetaItem) return; const d = tarjetaItem.item || { nombre: tarjetaItem.red.n, tipo: "otro", clase: "punto", lat: tarjetaItem.red.lat, lon: tarjetaItem.red.lon };
      aviso((await C.copiar(textoDetalle(d))) ? "Copiado" : "No se pudo copiar", "ok"); };
    $("t-navegar").onclick = () => { const d = datosTarjeta(); if (d) navegar(d); };
    $("t-mas").onclick = () => { if (tarjetaItem && tarjetaItem.item) masOpciones(tarjetaItem.item); };
    $("tarjeta").onclick = (e) => { if (!e.target.closest("button") && tarjetaItem && tarjetaItem.item) $("t-editar").click(); };
    M().leaflet().on("click", ocultar);

    document.querySelectorAll("#ed-tipos [data-ed-tipo]").forEach((b) => { b.onclick = () => {
      if (!ed || esSoloLectura()) return;
      const antes = sugerirNombre(ed.tipo), actual = $("ed-nombre").value.trim();
      ed.tipo = b.dataset.edTipo; ponerSubtipo(ed.tipo, null); marcarSucio(); pintarTipo();
      if (ed.modo === "nuevo" && (!actual || actual === antes)) $("ed-nombre").value = sugerirNombre(ed.tipo);
    }; });
    ["ed-nombre", "ed-notas", "ed-poste", "ed-mufa-capacidad", "ed-mufa-formato"].forEach((id) => { $(id).addEventListener("input", marcarSucio); $(id).addEventListener("change", marcarSucio); });
    $("ed-foto").onchange = async (e) => { const a = [...e.target.files]; e.target.value = ""; if (ed) await agregarFotos(a); };
    $("ed-galeria").onchange = async (e) => { const a = [...e.target.files]; e.target.value = ""; if (ed) await agregarFotos(a); };
    $("ed-atras").onclick = pedirSalida;
    $("ed-guardar").onclick = guardarPunto;
    $("ed-mas").onclick = menuPunto;
    $("ed-coord-editar").onclick = cambiarPosicion;
    $("ed-coord").onclick = async () => { if (ed) aviso((await C.copiar(`${ed.coord.lat}, ${ed.coord.lon}`)) ? "Coordenadas copiadas" : "No se pudo copiar", "ok"); };

    document.querySelectorAll("#cb-tipos [data-cb-tipo]").forEach((b) => { b.onclick = () => { if (!cb || cbSoloLectura()) return; cb.tipo_cable = b.dataset.cbTipo; cb.sucio = true; pintarCableTipo(); }; });
    $("cb-atras").onclick = salirCable;
    $("cb-guardar").onclick = guardarCable;
    $("cb-mas").onclick = menuCable;
  }

  C.tarjeta = { mostrar, mostrarRed, ocultar };
  C.editor = { conectar, nuevoPunto, abrirPunto, nuevoCable, abrirCable, navegar, borrar, masOpciones, puedeBorrar };
})();
