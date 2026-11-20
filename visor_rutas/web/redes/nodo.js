/* El nodo como lugar físico (redes/nodo.js): tres niveles.
 *   1. El nodo (el elemento del esquema general) se abre aquí, con lo que aloja:
 *   2. sus ODF, cada uno como un mosaico de puertos (libres / ocupados, y a qué OLT va cada uno), y sus OLT con la cantidad de hilos que tienen;
 *   3. dentro de una OLT: cada uno de sus hilos, a qué puerto de qué ODF va y a qué hilo de qué cable (que lleva a una mufa).
 * Un ODF puede estar conectado a varias OLT y una OLT a varios ODF. Datos: Redes.llamar("nodo" | "guardar_odf_nodo" | "guardar_olt_nodo" | "guardar_enlace_nodo"), visor_rutas/redes/nodo.py.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nd = { datos: null, nodoId: null, olt: null, elem: null, enlace: null };
  const puedeEditar = () => !!(nd.datos && nd.datos.nodo.puede_editar);
  const mensaje = (t, tipo) => { const e = $("nd-estado"); if (e) { e.textContent = t || ""; e.className = `vp-estado${tipo === "error" ? " error" : ""}`; } };
  const errores = (r) => (r.errores ? Object.values(r.errores).join(" · ") : r.error);
  const esAdmin = () => !!(window.Redes && Redes.estado && Redes.estado.puede && Redes.estado.puede.administrar);
  const corto = (t) => String(t || "").replace(/^OLT\s+/i, "").slice(0, 7);

  // ------------------------------------------------------------------ abrir y leer
  async function abrir(nodoId) {
    nd.nodoId = nodoId;
    nd.olt = null;
    mensaje("");
    if (!(await cargar())) return;
    $("modal-nodo").hidden = false;
  }

  async function cargar() {
    const r = await Redes.llamar("nodo", { nodo_id: nd.nodoId });
    if (!r.ok) { if (window.visor && window.visor.mensaje) window.visor.mensaje(r.error, "error"); else mensaje(r.error, "error"); return false; }
    nd.datos = r;
    pintar();
    return true;
  }

  function aplicar(r) {
    nd.datos = r;
    if (nd.olt && !r.olts.some((o) => o.id === nd.olt)) nd.olt = null;
    pintar();
  }

  // ------------------------------------------------------------------ dibujar
  function pintar() {
    const d = nd.datos, olt = nd.olt ? d.olts.find((o) => o.id === nd.olt) : null;
    $("nd-migas").innerHTML = `<a href="#" data-nd-miga="nodo">${esc(d.nodo.nombre)}</a>${olt ? ` › <b>${esc(olt.nombre)}</b>` : ""}`;
    $("nd-nivel-nodo").hidden = !!olt;
    $("nd-nivel-olt").hidden = !olt;
    document.querySelectorAll("#modal-nodo [data-nd-edita]").forEach((b) => { b.hidden = !puedeEditar(); });
    $("nd-visio-nodo").hidden = $("nd-visio-todos").hidden = !esAdmin() || !!olt;
    if (olt) pintarOlt(olt); else pintarNodo();
  }

  function infoEnlace(e) {
    return `${e.olt_nombre} (hilo ${e.olt_puerto})${e.hilo_numero ? ` · ${e.cable_nombre} hilo ${e.hilo_numero}${e.destino_nombre ? ` → ${e.destino_nombre}` : ""}` : ""}`;
  }

  function pintarNodo() {
    const d = nd.datos;
    $("nd-odfs-vacio").hidden = d.odfs.length > 0;
    $("nd-olts-vacio").hidden = d.olts.length > 0;
    $("nd-odfs").innerHTML = d.odfs.map((o) => {
      const columnas = Math.min(o.puertos, 12);
      const baldosas = Array.from({ length: o.puertos }, (_, i) => {
        const n = i + 1, e = d.enlaces.find((x) => x.odf_id === o.id && x.odf_puerto === n);
        return `<button type="button" class="nd-baldosa ${e ? "ocupada" : "libre"}" data-nd-baldosa="${o.id}:${n}" title="${esc(e ? `Puerto ${n} · ocupado: ${infoEnlace(e)}` : `Puerto ${n} · libre`)}">${n}${e ? `<small>${esc(corto(e.olt_nombre))}</small>` : ""}</button>`;
      }).join("");
      const visio = o.fuente === "visio" ? `<small class="nd-visio">Del Visio${o.estimado ? " · puertos estimados: revíselos" : ""}</small>` : "";
      const cables = (o.cables_visio || []).length ? `<small class="nd-cables">Cables del Visio: ${o.cables_visio.map((c) => `${esc(c.nombre)}${c.hilos ? ` (${c.hilos}H)` : ""} → ${esc(c.otro)}`).join(" · ")}</small>` : "";
      return `<article class="nd-odf" data-odf="${o.id}"><header><div><b>${esc(o.nombre)}</b><small>${o.puertos} puertos · ${o.ocupados} ocupado${o.ocupados === 1 ? "" : "s"} · ${o.libres} libre${o.libres === 1 ? "" : "s"}</small>${visio}</div>
        <button type="button" class="btn btn-chico" data-nd-edita data-nd-elem="odf:${o.id}" title="Cambiar el nombre o la cantidad de puertos, o eliminarlo">Editar</button></header>
        <div class="nd-mosaico" style="--nd-cols:${columnas}">${baldosas}</div>${cables}</article>`;
    }).join("");
    $("nd-olts").innerHTML = d.olts.map((o) => {
      const conectados = [...new Set(d.enlaces.filter((e) => e.olt_id === o.id && e.odf_nombre).map((e) => e.odf_nombre))];
      const deVisio = o.fuente === "visio" ? `<small class="nd-visio">Del Visio${o.estimado ? " · hilos estimados: revíselos" : ""}</small>` : "";
      return `<article class="nd-olt" data-olt="${o.id}"><header><div><b>${esc(o.nombre)}</b><small>${o.puertos} hilos · ${o.ocupados} en uso · ${o.libres} libres</small>${deVisio}</div>
        <button type="button" class="btn btn-chico btn-primario" data-nd-abrir-olt="${o.id}" title="Ver los hilos de la OLT y asignar a qué ODF y a qué mufa va cada uno">Abrir</button>
        <button type="button" class="btn btn-chico" data-nd-edita data-nd-elem="olt:${o.id}" title="Cambiar el nombre o la cantidad de hilos, o eliminarla">Editar</button></header>
        <div class="nd-barra" aria-hidden="true"><i style="width:${Math.round((o.ocupados / o.puertos) * 100)}%"></i></div>
        <p class="nota">${conectados.length ? `ODF conectados: ${esc(conectados.join(", "))}` : "Sin ODF conectado"}</p></article>`;
    }).join("");
    $("nd-resumen").textContent = `${d.odfs.length} ODF · ${d.olts.length} OLT · ${d.enlaces.length} enlace${d.enlaces.length === 1 ? "" : "s"}`;
  }

  function pintarOlt(o) {
    const d = nd.datos;
    $("nd-olt-titulo").textContent = `${o.nombre} · ${o.puertos} hilos (${o.ocupados} en uso)`;
    $("nd-olt-filas").innerHTML = Array.from({ length: o.puertos }, (_, i) => {
      const n = i + 1, e = d.enlaces.find((x) => x.olt_id === o.id && x.olt_puerto === n);
      return `<tr class="${e ? "ocupada" : "libre"}"><td><b>${n}</b></td>
        <td>${e && e.odf_nombre ? `${esc(e.odf_nombre)} · puerto ${e.odf_puerto}` : '<span class="nota">—</span>'}</td>
        <td>${e && e.hilo_numero ? `${esc(e.cable_nombre)} · hilo ${e.hilo_numero}` : '<span class="nota">—</span>'}</td>
        <td>${e && e.destino_nombre ? esc(e.destino_nombre) : '<span class="nota">—</span>'}</td>
        <td><button type="button" class="btn btn-chico" data-nd-edita data-nd-enlace="${o.id}:${n}">${e ? "Cambiar" : "Asignar"}</button></td></tr>`;
    }).join("");
    document.querySelectorAll("#modal-nodo [data-nd-edita]").forEach((b) => { b.hidden = !puedeEditar(); });
  }

  // ------------------------------------------------------------------ ODF / OLT: crear, cambiar, eliminar
  function pedirElemento(tipo, id) {
    if (!puedeEditar()) return;
    const d = nd.datos, actual = id ? (tipo === "odf" ? d.odfs : d.olts).find((x) => x.id === id) : null;
    nd.elem = { tipo, id: actual ? actual.id : null };
    const f = $("nd-elem-form");
    $("nd-elem-titulo").textContent = actual ? `${tipo === "odf" ? "ODF" : "OLT"} ${actual.nombre}` : tipo === "odf" ? "Nuevo ODF" : "Nueva OLT";
    f.elements.nombre.value = actual ? actual.nombre : "";
    f.elements.nombre.placeholder = tipo === "odf" ? `ODF ${d.odfs.length + 1}` : `OLT ${d.olts.length + 1}`;
    f.elements.puertos.value = actual ? actual.puertos : tipo === "odf" ? 24 : 16;
    $("nd-elem-etiqueta").textContent = tipo === "odf" ? "Puertos del ODF" : "Hilos de la OLT";
    $("nd-elem-eliminar").hidden = !actual;
    $("nd-elem-error").textContent = "";
    $("modal-nd-elem").hidden = false;
    f.elements.nombre.focus();
  }

  async function guardarElemento(ev) {
    ev.preventDefault();
    const f = $("nd-elem-form"), e = nd.elem;
    const pedido = { nodo_id: nd.nodoId, nombre: f.elements.nombre.value, puertos: Number(f.elements.puertos.value) };
    const r = await Redes.llamar(e.tipo === "odf" ? "guardar_odf_nodo" : "guardar_olt_nodo", { ...pedido, ...(e.id ? { [e.tipo === "odf" ? "odf_id" : "olt_id"]: e.id } : {}) });
    if (!r.ok) { $("nd-elem-error").textContent = errores(r); return; }
    $("modal-nd-elem").hidden = true;
    aplicar(r);
    mensaje(e.id ? "Cambios guardados" : `${e.tipo === "odf" ? "ODF" : "OLT"} creado`);
  }

  async function eliminarElemento() {
    const e = nd.elem;
    if (!e || !e.id) return;
    const nombre = (e.tipo === "odf" ? nd.datos.odfs : nd.datos.olts).find((x) => x.id === e.id).nombre;
    if (!(await Redes.confirmar(e.tipo === "olt" ? `¿Eliminar la OLT «${nombre}»? Se borran los enlaces de sus hilos.` : `¿Eliminar el ODF «${nombre}»? Sus puertos quedan libres (los hilos asignados se conservan).`, "Eliminar"))) return;
    const r = await Redes.llamar(e.tipo === "odf" ? "guardar_odf_nodo" : "guardar_olt_nodo", { nodo_id: nd.nodoId, [e.tipo === "odf" ? "odf_id" : "olt_id"]: e.id, eliminar: true });
    if (!r.ok) { $("nd-elem-error").textContent = errores(r); return; }
    $("modal-nd-elem").hidden = true;
    aplicar(r);
    mensaje(`${e.tipo === "odf" ? "ODF" : "OLT"} eliminado`);
  }

  // ------------------------------------------------------------------ enlaces: un hilo de la OLT ↔ un puerto de un ODF y/o un hilo de un cable
  function pedirEnlace({ olt_id = null, olt_puerto = null, odf_id = null, odf_puerto = null }) {
    if (!puedeEditar()) return;
    const d = nd.datos;
    if (!d.olts.length) { mensaje("Primero cree una OLT: el ODF se conecta a una OLT", "error"); return; }
    const previo = olt_id && olt_puerto ? d.enlaces.find((e) => e.olt_id === olt_id && e.olt_puerto === olt_puerto) : null;
    nd.enlace = { fijaOlt: !!olt_id && !!olt_puerto, previo: previo || null };
    const f = $("nd-enl-form");
    f.elements.olt.innerHTML = d.olts.map((o) => `<option value="${o.id}">${esc(o.nombre)} (${o.puertos} hilos)</option>`).join("");
    f.elements.olt.value = String(olt_id || (previo ? previo.olt_id : d.olts[0].id));
    f.elements.odf.innerHTML = `<option value="">— Sin ODF —</option>` + d.odfs.map((o) => `<option value="${o.id}">${esc(o.nombre)} (${o.puertos} puertos)</option>`).join("");
    f.elements.odf.value = String(odf_id || (previo && previo.odf_id) || "");
    f.elements.cable.innerHTML = `<option value="">— Sin cable —</option>` + d.cables.map((c) => `<option value="${c.id}">${esc(c.nombre)} → ${esc(c.otro.nombre)}</option>`).join("");
    const cableDelHilo = previo && previo.cable_id ? previo.cable_id : "";
    f.elements.cable.value = String(cableDelHilo);
    ponerPuertosOlt(olt_puerto || (previo && previo.olt_puerto));
    ponerPuertosOdf(odf_puerto || (previo && previo.odf_puerto));
    ponerHilos(previo && previo.hilo_id);
    f.elements.olt.disabled = f.elements.oltpuerto.disabled = nd.enlace.fijaOlt;
    $("nd-enl-titulo").textContent = previo ? "Cambiar a qué va este hilo de la OLT" : "Conectar un hilo de la OLT";
    $("nd-enl-quitar").hidden = !previo;
    $("nd-enl-error").textContent = "";
    $("modal-nd-enlace").hidden = false;
  }

  function ponerPuertosOlt(elegido) {
    const f = $("nd-enl-form"), d = nd.datos, o = d.olts.find((x) => x.id === Number(f.elements.olt.value));
    if (!o) { f.elements.oltpuerto.innerHTML = ""; return; }
    f.elements.oltpuerto.innerHTML = Array.from({ length: o.puertos }, (_, i) => {
      const n = i + 1, e = d.enlaces.find((x) => x.olt_id === o.id && x.olt_puerto === n);
      return `<option value="${n}">${n}${e ? ` — en uso${e.odf_nombre ? `: ${esc(e.odf_nombre)} ${e.odf_puerto}` : ""}` : " — libre"}</option>`;
    }).join("");
    const libre = Array.from({ length: o.puertos }, (_, i) => i + 1).find((n) => !d.enlaces.some((x) => x.olt_id === o.id && x.olt_puerto === n));
    f.elements.oltpuerto.value = String(elegido || libre || 1);
  }

  function ponerPuertosOdf(elegido) {
    const f = $("nd-enl-form"), d = nd.datos, o = d.odfs.find((x) => x.id === Number(f.elements.odf.value));
    f.elements.odfpuerto.disabled = !o;
    if (!o) { f.elements.odfpuerto.innerHTML = '<option value="">—</option>'; return; }
    const propio = nd.enlace && nd.enlace.previo;
    f.elements.odfpuerto.innerHTML = Array.from({ length: o.puertos }, (_, i) => {
      const n = i + 1, e = d.enlaces.find((x) => x.odf_id === o.id && x.odf_puerto === n), mio = propio && e && e.id === propio.id;
      return `<option value="${n}" ${e && !mio ? "disabled" : ""}>${n}${e && !mio ? ` — ocupado por ${esc(e.olt_nombre)} (hilo ${e.olt_puerto})` : " — libre"}</option>`;
    }).join("");
    const libre = Array.from({ length: o.puertos }, (_, i) => i + 1).find((n) => !d.enlaces.some((x) => x.odf_id === o.id && x.odf_puerto === n));
    f.elements.odfpuerto.value = String(elegido || libre || 1);
  }

  function ponerHilos(elegido) {
    const f = $("nd-enl-form"), d = nd.datos, c = d.cables.find((x) => x.id === Number(f.elements.cable.value));
    f.elements.hilo.disabled = !c;
    if (!c) { f.elements.hilo.innerHTML = '<option value="">—</option>'; return; }
    f.elements.hilo.innerHTML = c.fibras.map((h) => {
      const e = d.enlaces.find((x) => x.hilo_id === h.id), mio = nd.enlace && nd.enlace.previo && e && e.id === nd.enlace.previo.id;
      return `<option value="${h.id}" ${e && !mio ? "disabled" : ""}>Hilo ${h.numero}${e && !mio ? ` — ya va a ${esc(e.olt_nombre)} (hilo ${e.olt_puerto})` : ""}</option>`;
    }).join("");
    const libre = c.fibras.find((h) => !d.enlaces.some((x) => x.hilo_id === h.id));
    f.elements.hilo.value = String(elegido || (libre && libre.id) || c.fibras[0].id);
  }

  async function guardarEnlace(ev, quitar = false) {
    if (ev) ev.preventDefault();
    const f = $("nd-enl-form");
    const r = await Redes.llamar("guardar_enlace_nodo", { nodo_id: nd.nodoId, olt_id: Number(f.elements.olt.value), olt_puerto: Number(f.elements.oltpuerto.value),
      odf_id: f.elements.odf.value ? Number(f.elements.odf.value) : null, odf_puerto: f.elements.odf.value ? Number(f.elements.odfpuerto.value) : null,
      hilo_id: f.elements.cable.value ? Number(f.elements.hilo.value) : null, quitar });
    if (!r.ok) { $("nd-enl-error").textContent = errores(r); return; }
    $("modal-nd-enlace").hidden = true;
    aplicar(r);
    mensaje(quitar ? "Enlace quitado" : "Enlace guardado");
  }

  // ------------------------------------------------------------------ traer del Visio (administradores)
  async function traerDelVisio(todos) {
    const pedido = todos ? {} : { nodo_id: nd.nodoId };
    const sim = await Redes.llamar("convertir_visio_nodo", { ...pedido, simular: true });
    if (!sim.ok) { mensaje(errores(sim), "error"); return; }
    if (!sim.odfs_nuevos && !sim.olts_nuevas) {
      mensaje(`Nada nuevo que traer: ${sim.odfs_ya_estaban} ODF y ${sim.olts_ya_estaban} OLT del Visio ya están en ${todos ? "sus nodos" : "este nodo"}${todos && sim.sin_nodo.length ? ` (${sim.sin_nodo.length} ODF del Visio no pertenecen a ningún nodo)` : ""}`);
      return;
    }
    const texto = `Se traerían ${sim.odfs_nuevos} ODF y ${sim.olts_nuevas} OLT${todos ? ` a ${sim.nodos} nodo${sim.nodos === 1 ? "" : "s"}` : " a este nodo"}`
      + `${sim.estimados ? `; ${sim.estimados} ODF con los puertos estimados (quedan marcados para revisarlos)` : ""}.`
      + `${todos && sim.sin_nodo.length ? ` ${sim.sin_nodo.length} ODF del Visio no están en ningún nodo (son de mufas o de clientes) y se dejan como están.` : ""} No se borra ni se cambia nada de la red. ¿Traerlos?`;
    if (!(await Redes.confirmar(texto, "Traer"))) return;
    const r = await Redes.llamar("convertir_visio_nodo", { ...pedido, simular: false });
    if (!r.ok) { mensaje(errores(r), "error"); return; }
    await cargar();
    mensaje(`Traídos del Visio: ${r.odfs_nuevos} ODF y ${r.olts_nuevas} OLT`);
  }

  // ------------------------------------------------------------------ eventos
  function conectar() {
    $("nd-visio-nodo").addEventListener("click", () => traerDelVisio(false));
    $("nd-visio-todos").addEventListener("click", () => traerDelVisio(true));
    $("nd-cerrar").addEventListener("click", () => { $("modal-nodo").hidden = true; });
    $("nd-max").addEventListener("click", () => $("modal-nodo").classList.toggle("maximizado"));
    $("nd-volver").addEventListener("click", () => { nd.olt = null; pintar(); });
    $("nd-migas").addEventListener("click", (e) => { if (e.target.closest("[data-nd-miga]")) { e.preventDefault(); nd.olt = null; pintar(); } });
    $("nd-odf-nuevo").addEventListener("click", () => pedirElemento("odf"));
    $("nd-olt-nueva").addEventListener("click", () => pedirElemento("olt"));
    $("modal-nodo").addEventListener("click", (e) => {
      const b = e.target.closest("[data-nd-baldosa]"), el = e.target.closest("[data-nd-elem]"), ab = e.target.closest("[data-nd-abrir-olt]"), en = e.target.closest("[data-nd-enlace]");
      if (b) {
        const [odf, n] = b.dataset.ndBaldosa.split(":").map(Number), previo = nd.datos.enlaces.find((x) => x.odf_id === odf && x.odf_puerto === n);
        if (previo) pedirEnlace({ olt_id: previo.olt_id, olt_puerto: previo.olt_puerto });
        else pedirEnlace({ odf_id: odf, odf_puerto: n });
      } else if (el) { const [tipo, id] = el.dataset.ndElem.split(":"); pedirElemento(tipo, Number(id)); }
      else if (ab) { nd.olt = Number(ab.dataset.ndAbrirOlt); pintar(); }
      else if (en) { const [olt, n] = en.dataset.ndEnlace.split(":").map(Number); pedirEnlace({ olt_id: olt, olt_puerto: n }); }
    });
    $("nd-elem-form").addEventListener("submit", guardarElemento);
    $("nd-elem-eliminar").addEventListener("click", eliminarElemento);
    $("nd-elem-cancelar").addEventListener("click", () => { $("modal-nd-elem").hidden = true; });
    $("nd-enl-form").addEventListener("submit", guardarEnlace);
    $("nd-enl-quitar").addEventListener("click", () => guardarEnlace(null, true));
    $("nd-enl-cancelar").addEventListener("click", () => { $("modal-nd-enlace").hidden = true; });
    $("nd-enl-form").elements.olt.addEventListener("change", () => ponerPuertosOlt());
    $("nd-enl-form").elements.odf.addEventListener("change", () => ponerPuertosOdf());
    $("nd-enl-form").elements.cable.addEventListener("change", () => ponerHilos());
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || $("modal-nodo").hidden) return;
      e.stopPropagation();
      if (!$("modal-nd-enlace").hidden) $("modal-nd-enlace").hidden = true;
      else if (!$("modal-nd-elem").hidden) $("modal-nd-elem").hidden = true;
      else if (nd.olt) { nd.olt = null; pintar(); } else $("modal-nodo").hidden = true;
    }, true);
  }

  window.Nodo = { abrir, _st: nd };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", conectar); else conectar();
})();
