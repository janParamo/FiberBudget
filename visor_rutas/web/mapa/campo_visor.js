/* Campo en el visor (app de campo, fase 4): lo que levantan los técnicos desde el teléfono, en tiempo real, para quien revisa (administrador / editor).
 *
 *  - Capa «Levantamiento de campo» en Lugares: una casilla por técnico y jornada; un círculo por punto con la letra del tipo y el color del estado
 *    (pendiente amarillo, corregido naranja, aprobado verde, rechazado gris); al tocarlo, sus datos, fotos y acciones.
 *  - «Ubicación de los técnicos»: el último punto donde se oyó de cada uno, con su nombre y hace cuánto.
 *  - Vista «Campo» del menú: lista filtrable con casillas para decidir en lote: editar, rechazar (con motivo) y aprobar a la red base, a un proyecto
 *    o a Mis lugares; avisa de posibles duplicados.
 *  - Tiempo real: Python avisa a CampoVisor.evento() (LISTEN de PostgreSQL en la PC del servidor; Server-Sent Events en el modo remoto) y aquí solo se
 *    pide lo que cambió desde la última vez. Si un aviso se pierde, al reconectar se vuelve a pedir todo.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TIPOS = { poste: "Poste", mufa: "Mufa", reserva: "Reserva", solitaria: "Solitaria", cliente: "Cliente", otro: "Otro" };
  const LETRA = { poste: "P", mufa: "M", reserva: "R", solitaria: "S", cliente: "C", otro: "O" };
  const ARTICULO = { poste: "un poste", mufa: "una mufa", reserva: "una reserva", solitaria: "una solitaria", cliente: "un cliente", otro: "un punto" };
  const ESTADO = { pendiente: "Pendiente", editado: "Corregido", aprobado: "Aprobado", rechazado: "Rechazado" };
  const DIAS_INICIALES = 14, ESPERA_AVISOS_MS = 400, REFRESCO_VIVO_MS = 30000, REFRESCO_SEGURO_MS = 120000;

  const st = {
    ctx: null, activo: false, puntos: new Map(), trazos: new Map(), ahoraT: null, jornadas: new Map(), ahora: null, ubic: [], ubicHora: 0, visibles: new Set(), conocidos: new Set(), vivo: true,
    capa: null, capaVivo: null, seleccion: new Set(), temporizador: null, tictac: null, fotos: new Map(), mostrada: false,
  };

  const llamar = (m, a) => window.Redes.llamar(m, a);
  const clave = (p) => `${p.usuario_id}|${p.jornada_id || 0}`;
  const porDecidir = (p) => p.estado === "pendiente" || p.estado === "editado";
  const hace = (s) => (s < 60 ? "hace un momento" : s < 3600 ? `hace ${Math.round(s / 60)} min` : s < 86400 ? `hace ${Math.round(s / 3600)} h` : `hace ${Math.round(s / 86400)} d`);
  const fechaHora = (iso) => (window.Redes && window.Redes.fecha ? window.Redes.fecha(iso) : iso);
  const vivos = () => [...st.puntos.values()].filter((p) => !p.borrado);
  const esTrazo = (x) => Array.isArray(x.puntos);
  const llave = (x) => (esTrazo(x) ? "t" : "p") + x.id;                        // points and traces have their own ids: «p12» / «t3»
  const todos = () => [...vivos(), ...[...st.trazos.values()].filter((t) => !t.borrado)];
  const colorEstado = { pendiente: "#ffd400", editado: "#ff8c1a", aprobado: "#1b9e4b", rechazado: "#8a8f98" };
  const descTrazo = (t) => `Cable${t.tipo_cable ? " " + t.tipo_cable : ""}${t.hilos ? " · " + t.hilos + " hilos" : ""} · ${Math.round(t.longitud_m || 0)} m`;

  // ---------------------------------------------------------------- datos

  async function pedirTodo() {
    const desde = new Date(Date.now() - DIAS_INICIALES * 86400000).toISOString();
    const nuevos = new Map(), trazos = new Map();
    let cursor = desde, ahora = null, ahoraT = null;
    for (let i = 0; i < 20; i++) {                                         // pages of up to 500 changes
      const r = await llamar("campo_puntos", { desde: cursor, limite: 500 });
      if (!r.ok) throw new Error(r.error);
      r.puntos.forEach((p) => { if (!p.borrado) nuevos.set(p.id, p); });
      ahora = r.ahora;
      if (!r.mas) break;
      cursor = r.puntos[r.puntos.length - 1].actualizado_en;
    }
    cursor = desde;
    for (let i = 0; i < 20; i++) {
      const r = await llamar("campo_trazos", { desde: cursor, limite: 200 });
      if (!r.ok) throw new Error(r.error);
      r.trazos.forEach((t) => { if (!t.borrado) trazos.set(t.id, t); });
      ahoraT = r.ahora;
      if (!r.mas) break;
      cursor = r.trazos[r.trazos.length - 1].actualizado_en || r.trazos[r.trazos.length - 1].recibido_en;
    }
    return { nuevos, trazos, ahora, ahoraT };
  }

  async function cargarJornadas() {
    const r = await llamar("campo_jornadas", { limite: 100 });
    if (r.ok) r.jornadas.forEach((j) => st.jornadas.set(j.id, j));
  }

  async function cargarUbicaciones() {
    const r = await llamar("campo_ubicaciones", {});
    if (!r.ok) return;
    st.ubic = r.ubicaciones; st.ubicHora = Date.now();
    pintarVivo();
  }

  /** Everything again (start, or after a reconnection that may have lost notices). */
  async function cargarTodo() {
    const { nuevos, trazos, ahora, ahoraT } = await pedirTodo();
    await cargarJornadas();
    st.puntos = nuevos; st.ahora = ahora; st.trazos = trazos; st.ahoraT = ahoraT;
    [...nuevos.values(), ...trazos.values()].forEach((p) => { if (!st.conocidos.has(clave(p))) { st.conocidos.add(clave(p)); if (hoyReciente(p)) st.visibles.add(clave(p)); } });
    await cargarUbicaciones();
    repintar();
  }

  const hoyReciente = (p) => Date.now() - new Date(p.actualizado_en || p.recibido_en).getTime() < 86400000;

  /** Only what changed since the last request; announces the new points. */
  async function cargarCambios() {
    const r = await llamar("campo_puntos", { desde: st.ahora, limite: 500 });
    if (!r.ok) return;
    st.ahora = r.ahora;
    const nuevos = [];
    r.puntos.forEach((p) => {
      if (p.borrado) { st.puntos.delete(p.id); st.seleccion.delete("p" + p.id); return; }
      const antes = st.puntos.has(p.id);
      st.puntos.set(p.id, p);
      if (!antes) nuevos.push(p);
      if (!st.conocidos.has(clave(p))) { st.conocidos.add(clave(p)); st.visibles.add(clave(p)); }
    });
    if (r.mas) { await cargarTodo(); return; }
    const rt = await llamar("campo_trazos", { desde: st.ahoraT, limite: 200 });
    const nuevosT = [];
    if (rt.ok) {
      st.ahoraT = rt.ahora;
      rt.trazos.forEach((t) => {
        if (t.borrado) { st.trazos.delete(t.id); st.seleccion.delete("t" + t.id); return; }
        if (!st.trazos.has(t.id)) nuevosT.push(t);
        st.trazos.set(t.id, t);
        if (!st.conocidos.has(clave(t))) { st.conocidos.add(clave(t)); st.visibles.add(clave(t)); }
      });
      if (rt.mas) { await cargarTodo(); return; }
    }
    if ([...r.puntos, ...(rt.ok ? rt.trazos : [])].some((p) => !st.jornadas.has(p.jornada_id) && p.jornada_id)) await cargarJornadas();
    repintar();
    nuevos.filter(porDecidir).forEach((p) => st.ctx.mensaje(`${p.usuario} agregó ${ARTICULO[p.tipo] || "un punto"} «${p.nombre}»`, "ok"));
    nuevosT.filter(porDecidir).forEach((t) => st.ctx.mensaje(`${t.usuario} trazó un cable de ${Math.round(t.longitud_m || 0)} m`, "ok"));
  }

  // ---------------------------------------------------------------- tiempo real

  function evento(e) {
    if (!st.activo || !e) return;
    if (e.tabla === "_error") { st.ctx.mensaje(`Avisos de campo: ${e.error}`, "error"); return; }
    clearTimeout(st.temporizador);
    st.temporizador = setTimeout(async () => {
      try {
        if (e.tabla === "_conectado") await cargarTodo();
        else if (e.tabla === "campo_ubicaciones") await cargarUbicaciones();
        else await cargarCambios();
      } catch (err) { console.error("CampoVisor", err); }
    }, ESPERA_AVISOS_MS);
  }

  // ---------------------------------------------------------------- mapa

  function iconoPunto(p) { return L.divIcon({ className: "", html: `<div class="campo-marca ${esc(p.estado)}">${LETRA[p.tipo] || "·"}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }); }

  function htmlPopup(p) {
    const dup = p.duplicado ? `<div class="cm-dup">Posible duplicado: ${esc(p.duplicado.nombre)} a ${p.duplicado.distancia_m} m</div>` : "";
    const fotos = (p.fotos || []).map((f) => `<img data-cm-foto="${f.id}" alt="Foto">`).join("");
    const acciones = porDecidir(p) ? `<div class="acciones"><button type="button" class="btn btn-primario btn-chico" data-cm-p="aprobar" data-k="p${p.id}">Aprobar…</button>
      <button type="button" class="btn btn-chico" data-cm-p="editar" data-k="p${p.id}">Editar</button>
      <button type="button" class="btn btn-chico peligro" data-cm-p="rechazar" data-k="p${p.id}">Rechazar…</button></div>` : "";
    return `<div class="campo-popup"><b>${esc(p.nombre)}</b><br>${esc(TIPOS[p.tipo])}${p.subtipo ? " · " + esc(p.subtipo) : ""} · <span class="cm-est ${esc(p.estado)}">${esc(ESTADO[p.estado])}</span>
      <br>${esc(p.usuario)} · ${esc(fechaHora(p.capturado_en))}<br>${p.precision_m != null ? `GPS ±${Math.round(p.precision_m)} m` : "Marcado en el mapa"}
      ${p.notas ? `<br>${esc(p.notas)}` : ""}${p.motivo_rechazo ? `<br><i>Motivo: ${esc(p.motivo_rechazo)}</i>` : ""}${dup}${fotos ? `<div class="cm-miniaturas">${fotos}</div>` : ""}${acciones}</div>`;
  }

  function htmlPopupTrazo(t) {
    const acciones = porDecidir(t) ? `<div class="acciones"><button type="button" class="btn btn-primario btn-chico" data-cm-p="aprobar" data-k="t${t.id}">Aprobar…</button>
      <button type="button" class="btn btn-chico peligro" data-cm-p="rechazar" data-k="t${t.id}">Rechazar…</button></div>` : "";
    return `<div class="campo-popup"><b>${esc(descTrazo(t))}</b><br><span class="cm-est ${esc(t.estado)}">${esc(ESTADO[t.estado])}</span> · ${esc(t.modo)}
      <br>${esc(t.usuario)} · ${esc(fechaHora(t.capturado_en))}${t.notas ? `<br>${esc(t.notas)}` : ""}${t.motivo_rechazo ? `<br><i>Motivo: ${esc(t.motivo_rechazo)}</i>` : ""}${acciones}</div>`;
  }

  function repintar() {
    if (!st.capa) return;
    st.capa.clearLayers();
    vivos().filter((p) => st.visibles.has(clave(p))).forEach((p) => {
      L.marker([p.lat, p.lon], { icon: iconoPunto(p), title: p.nombre }).bindPopup(() => htmlPopup(p), { minWidth: 220 }).addTo(st.capa);
    });
    todos().filter((x) => esTrazo(x) && st.visibles.has(clave(x))).forEach((t) => {
      L.polyline(t.puntos, { color: colorEstado[t.estado] || "#ffd400", weight: 5, opacity: 0.9 }).bindPopup(() => htmlPopupTrazo(t), { minWidth: 220 }).addTo(st.capa);
    });
    if (window.Lugares) window.Lugares.refrescar();
    pintarInsignia();
    if (st.mostrada) pintarVista();
  }

  function pintarInsignia() {
    const n = todos().filter(porDecidir).length, b = $("campo-contador");
    if (b) { b.textContent = String(n); b.hidden = n === 0; }
  }

  function pintarVivo() {
    if (!st.capaVivo) return;
    st.capaVivo.clearLayers();
    if (!st.vivo) return;
    const pasado = (Date.now() - st.ubicHora) / 1000;
    st.ubic.forEach((u) => {
      const texto = `${esc(u.nombre)} · ${hace(u.hace_s + pasado)}`;
      L.marker([u.lat, u.lon], { icon: L.divIcon({ className: "", html: `<div class="campo-tecnico">${texto}</div>`, iconSize: null, iconAnchor: [0, 0] }), zIndexOffset: 800,
        title: `${u.nombre} (±${u.precision_m == null ? "?" : Math.round(u.precision_m)} m)` }).addTo(st.capaVivo);
    });
  }

  // ---------------------------------------------------------------- sección de Lugares

  function grupos() {
    const m = new Map();
    todos().forEach((p) => {
      const k = clave(p), g = m.get(k) || { k, usuario: p.usuario, jornada_id: p.jornada_id, n: 0, ultimo: "" };
      const cuando = p.actualizado_en || p.recibido_en || "";
      g.n += 1; g.ultimo = g.ultimo > cuando ? g.ultimo : cuando;
      m.set(k, g);
    });
    return [...m.values()].sort((a, b) => (a.ultimo < b.ultimo ? 1 : -1)).slice(0, 40);
  }

  const seccion = {
    id: "campo", titulo: "Levantamiento de campo", tri: true,
    items: () => [
      ...grupos().map((g) => {
        const j = st.jornadas.get(g.jornada_id);
        return { id: g.k, texto: `${g.usuario} · ${j ? j.nombre : "sin jornada"}`, tipo: "check", marcado: st.visibles.has(g.k), pista: String(g.n) };
      }),
      { id: "_vivo", texto: "Ubicación de los técnicos", tipo: "check", marcado: st.vivo, pista: `${st.ubic.length}` },
      { id: "_panel", texto: "Abrir el panel de campo…", tipo: "accion", pista: "revisar, aprobar, rechazar" },
    ],
    alternar(id, valor) {
      if (id === "_panel") { st.ctx.mostrarVista("campo"); return; }
      if (id === "_vivo") { st.vivo = valor; pintarVivo(); return; }
      if (valor) st.visibles.add(id); else st.visibles.delete(id);
      repintar();
    },
    alternarTodas(valor) { grupos().forEach((g) => (valor ? st.visibles.add(g.k) : st.visibles.delete(g.k))); st.vivo = valor; repintar(); pintarVivo(); },
  };

  // ---------------------------------------------------------------- ventanas pequeñas

  function dialogo({ titulo, html, aceptar = "Aceptar", peligro = false, leer, alMostrar }) {
    return new Promise((resolver) => {
      const fondo = document.createElement("div");
      fondo.className = "modal campo-modal";
      fondo.innerHTML = `<div class="modal-caja"><header class="modal-cabecera"><h2>${esc(titulo)}</h2>
        <button type="button" class="btn-icono" data-d="no" aria-label="Cerrar">✕</button></header>
        <div class="config-cuerpo">${html}<p class="vp-estado cm-d-error" role="alert"></p>
        <div class="config-acciones"><button type="button" class="btn" data-d="no">Cancelar</button>
        <button type="button" class="btn ${peligro ? "peligro" : "btn-primario"}" data-d="si">${esc(aceptar)}</button></div></div></div>`;
      document.body.appendChild(fondo);
      const cerrar = (v) => { fondo.remove(); resolver(v); };
      fondo.addEventListener("click", async (e) => {
        const b = e.target.closest("[data-d]");
        if (!b) return;
        if (b.dataset.d === "no") { cerrar(null); return; }
        const r = await leer(fondo);
        if (r && r.error) { fondo.querySelector(".cm-d-error").textContent = r.error; return; }
        cerrar(r);
      });
      fondo.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); cerrar(null); } });
      if (alMostrar) alMostrar(fondo);
      const primero = fondo.querySelector("input,select,textarea,button[data-d=si]");
      if (primero) primero.focus();
    });
  }

  /* What the dialogs work on: keys «p12» (a point) and «t3» (a cable), only the ones still to decide. */
  const objeto = (k) => (k[0] === "t" ? st.trazos.get(Number(k.slice(1))) : st.puntos.get(Number(k.slice(1))));
  const pendientes = (keys) => keys.filter((k) => { const o = objeto(k); return o && porDecidir(o); });
  const idsDe = (keys, letra) => keys.filter((k) => k[0] === letra).map((k) => Number(k.slice(1)));

  function resumenKeys(keys) {
    const cuenta = {};
    keys.forEach((k) => { const o = objeto(k); if (o) { const c = esTrazo(o) ? "cable" : o.tipo; cuenta[c] = (cuenta[c] || 0) + 1; } });
    return cuenta;
  }

  function avisoResultados(resultados, verbo) {
    const bien = resultados.filter((x) => x.ok).length, mal = resultados.filter((x) => !x.ok);
    if (bien) st.ctx.mensaje(`${bien} elemento${bien === 1 ? "" : "s"} ${verbo}${bien === 1 ? "" : "s"}`, "ok");
    if (mal.length) st.ctx.mensaje(`${mal.length} no se pudo${mal.length === 1 ? "" : "ron"}: ${mal.slice(0, 2).map((x) => x.error).join(" · ")}`, "error");
  }

  const nombreDe = (k) => { const o = objeto(k); return esTrazo(o) ? descTrazo(o) : o.nombre; };

  async function aprobar(keys) {
    keys = pendientes(keys);
    if (!keys.length) { st.ctx.mensaje("No hay nada por revisar en la selección", "error"); return; }
    const cuenta = resumenKeys(keys), paraRed = (cuenta.poste || 0) + (cuenta.mufa || 0) + (cuenta.cable || 0), resto = keys.length - paraRed;
    const proyectos = await window.Redes.proyectosVisibles();
    const lista = Object.entries(cuenta).map(([t, n]) => `${n} ${(TIPOS[t] || "Cable").toLowerCase()}${n === 1 ? "" : "s"}`).join(", ");
    const hayCables = !!cuenta.cable;
    const r = await dialogo({
      titulo: keys.length === 1 ? `Aprobar «${nombreDe(keys[0])}»` : `Aprobar ${keys.length} elementos`, aceptar: "Aprobar",
      html: `<p>${esc(lista)}.</p>
        <label class="opcion"><input type="radio" name="cm-dest" value="red" ${paraRed ? "checked" : ""}> Red base (postes, mufas y cables)</label>
        <label class="opcion"><input type="radio" name="cm-dest" value="proyecto"> Un proyecto (postes, mufas, casas de cliente y cables)</label>
        <label class="opcion"><input type="radio" name="cm-dest" value="lugares" ${paraRed ? "" : "checked"}> Mis lugares (cualquier tipo; el cable como ruta)</label>
        <label id="cm-d-proyecto-caja">Proyecto <select id="cm-d-proyecto"></select></label>
        <p class="nota" id="cm-d-nota"></p>`,
      alMostrar: (f) => {
        const pintar = () => {
          const d = f.querySelector("[name=cm-dest]:checked").value, sel = f.querySelector("#cm-d-proyecto");
          const opciones = proyectos.filter((p) => (d === "red" ? p.es_red_base : !p.es_red_base));
          sel.innerHTML = opciones.map((p) => `<option value="${p.id}">${esc(p.nombre)} (${esc(p.codigo)})</option>`).join("");
          f.querySelector("#cm-d-proyecto-caja").hidden = d === "lugares";
          f.querySelector("#cm-d-nota").textContent = d === "lugares" ? "Quedan en tu carpeta «Campo – técnico» de Mis lugares, con sus fotos."
            : hayCables && d !== "lugares" ? "Un cable se aprueba aquí solo si empieza y termina a pocos metros de un poste o mufa del proyecto."
            : resto && d === "red" ? `${resto} que no es poste, mufa ni cable no se aprobará${resto === 1 ? "" : "n"} aquí: apruébelos en Mis lugares.` : "";
        };
        f.addEventListener("change", pintar); pintar();
      },
      leer: async (f) => {
        const destino = f.querySelector("[name=cm-dest]:checked").value, proyecto = destino === "lugares" ? null : Number(f.querySelector("#cm-d-proyecto").value || 0) || null;
        if (destino !== "lugares" && !proyecto) return { error: destino === "red" ? "No hay una red base disponible" : "Elija el proyecto" };
        const resultados = [];
        for (const [letra, metodo] of [["p", "campo_aprobar"], ["t", "campo_aprobar_trazos"]]) {
          const ids = idsDe(keys, letra);
          if (!ids.length) continue;
          const x = await llamar(metodo, { ids, destino, proyecto_id: proyecto });
          if (!x.ok) return { error: x.error };
          resultados.push(...x.resultados);
        }
        return { resultados };
      },
    });
    if (!r) return;
    avisoResultados(r.resultados, "aprobado");
    await cargarCambios();
    if (r.resultados.some((x) => x.ok && (x.elemento_id || x.cable_id)) && window.Redes.proyectosVisibles) window.Redes._proyectos = null;
  }

  async function rechazar(keys) {
    keys = pendientes(keys);
    if (!keys.length) { st.ctx.mensaje("No hay nada por revisar en la selección", "error"); return; }
    const r = await dialogo({
      titulo: keys.length === 1 ? `Rechazar «${nombreDe(keys[0])}»` : `Rechazar ${keys.length} elementos`, aceptar: "Rechazar", peligro: true,
      html: `<label for="cm-d-motivo">Motivo (lo lee el técnico)</label><textarea id="cm-d-motivo" rows="3" maxlength="300"></textarea>`,
      leer: async (f) => {
        const motivo = f.querySelector("#cm-d-motivo").value.trim();
        if (motivo.length < 3) return { error: "Escriba el motivo del rechazo" };
        const resultados = [];
        for (const [letra, metodo] of [["p", "campo_rechazar"], ["t", "campo_rechazar_trazos"]]) {
          const ids = idsDe(keys, letra);
          if (!ids.length) continue;
          const x = await llamar(metodo, { ids, motivo });
          if (!x.ok) return { error: x.error };
          resultados.push(...x.resultados);
        }
        return { resultados };
      },
    });
    if (!r) return;
    avisoResultados(r.resultados, "rechazado");
    await cargarCambios();
  }
  async function editar(id) {
    const p = st.puntos.get(id);
    if (!p) return;
    const opciones = Object.entries(TIPOS).map(([k, v]) => `<option value="${k}" ${k === p.tipo ? "selected" : ""}>${v}</option>`).join("");
    const r = await dialogo({
      titulo: `Editar «${p.nombre}»`, aceptar: "Guardar",
      html: `<label for="cm-e-nombre">Nombre</label><input id="cm-e-nombre" maxlength="160" value="${esc(p.nombre)}">
        <label for="cm-e-tipo">Tipo</label><select id="cm-e-tipo">${opciones}</select>
        <label for="cm-e-subtipo">Subtipo (poste: ideay, concreto, madera, metal, cliente; mufa: 48 o 96 y domo u horizontal)</label>
        <input id="cm-e-subtipo" maxlength="40" value="${esc(p.subtipo || "")}">
        <label for="cm-e-notas">Notas</label><textarea id="cm-e-notas" rows="3" maxlength="1000">${esc(p.notas || "")}</textarea>`,
      leer: async (f) => {
        const x = await llamar("campo_editar", { id, version: p.version, cambios: {
          nombre: f.querySelector("#cm-e-nombre").value, tipo: f.querySelector("#cm-e-tipo").value, subtipo: f.querySelector("#cm-e-subtipo").value,
          notas: f.querySelector("#cm-e-notas").value } });
        return x.ok ? x : { error: x.error };
      },
    });
    if (!r) return;
    st.ctx.mensaje("Punto corregido", "ok");
    await cargarCambios();
  }

  async function fotoUrl(id, grande) {
    const k = `${id}${grande ? "g" : ""}`;
    if (!st.fotos.has(k)) {
      const r = await llamar("campo_foto", { id, miniatura: !grande });
      if (!r.ok) return null;
      st.fotos.set(k, `data:${r.tipo};base64,${r.datos}`);
    }
    return st.fotos.get(k);
  }

  async function verFoto(id) {
    const url = await fotoUrl(id, true);
    if (!url) { st.ctx.mensaje("No se pudo cargar la foto", "error"); return; }
    const f = document.createElement("div");
    f.className = "modal campo-modal"; f.style.alignItems = "center"; f.style.justifyContent = "center";
    f.innerHTML = `<img src="${url}" alt="Foto" style="max-width:92vw;max-height:92vh;border-radius:8px;cursor:zoom-out">`;
    f.addEventListener("click", () => f.remove());
    document.body.appendChild(f);
  }

  async function cargarMiniaturas(raiz) {
    for (const img of raiz.querySelectorAll("img[data-cm-foto]")) {
      const url = await fotoUrl(Number(img.dataset.cmFoto), false);
      if (url) img.src = url;
    }
  }

  // ---------------------------------------------------------------- la vista «Campo»

  function filtrados() {
    const f = { estado: $("cm-f-estado").value, tecnico: $("cm-f-tecnico").value, jornada: $("cm-f-jornada").value, tipo: $("cm-f-tipo").value, texto: $("cm-f-texto").value.trim().toLowerCase() };
    return todos().filter((p) => (f.estado === "por_decidir" ? porDecidir(p) : !f.estado || p.estado === f.estado) && (!f.tecnico || String(p.usuario_id) === f.tecnico)
      && (!f.jornada || String(p.jornada_id) === f.jornada) && (!f.tipo || (f.tipo === "cable" ? esTrazo(p) : !esTrazo(p) && p.tipo === f.tipo))
      && (!f.texto || `${esTrazo(p) ? descTrazo(p) : p.nombre} ${p.notas} ${p.usuario} ${p.subtipo || ""}`.toLowerCase().includes(f.texto)))
      .sort((a, b) => (a.capturado_en < b.capturado_en ? 1 : -1));
  }

  function llenarFiltros() {
    const tec = $("cm-f-tecnico"), jor = $("cm-f-jornada"), vt = tec.value, vj = jor.value;
    const tecnicos = new Map(todos().map((p) => [p.usuario_id, p.usuario]));
    tec.innerHTML = `<option value="">Todos los técnicos</option>` + [...tecnicos].map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("");
    const js = [...st.jornadas.values()].filter((j) => todos().some((p) => p.jornada_id === j.id));
    jor.innerHTML = `<option value="">Todas las jornadas</option>` + js.map((j) => `<option value="${j.id}">${esc(j.usuario || "")} · ${esc(j.nombre)}</option>`).join("");
    tec.value = vt; jor.value = vj;
    if (!$("cm-f-tipo").querySelector('[value="cable"]')) $("cm-f-tipo").insertAdjacentHTML("beforeend", `<option value="cable">Cables</option>`);
  }

  function filaPunto(p) {
    const k = llave(p), n = (p.fotos || []).length;
    return `<tr data-k="${k}"><td>${porDecidir(p) ? `<input type="checkbox" data-cm-sel="${k}" ${st.seleccion.has(k) ? "checked" : ""} aria-label="Elegir">` : ""}</td>
        <td><span class="cm-est ${esc(p.estado)}">${esc(ESTADO[p.estado])}</span>${p.motivo_rechazo ? `<div class="nota">${esc(p.motivo_rechazo)}</div>` : ""}</td>
        <td><b>${esc(p.nombre)}</b><div class="nota">${esc(TIPOS[p.tipo])}${p.subtipo ? " · " + esc(p.subtipo) : ""}</div>${p.duplicado ? `<div class="cm-dup">Posible duplicado: ${esc(p.duplicado.nombre)} a ${p.duplicado.distancia_m} m</div>` : ""}</td>
        <td>${esc(p.usuario)}<div class="nota">${esc((st.jornadas.get(p.jornada_id) || {}).nombre || "sin jornada")} · ${esc(fechaHora(p.capturado_en))}</div></td>
        <td>${p.precision_m != null ? `±${Math.round(p.precision_m)} m` : "mapa"}</td><td class="cm-notas">${esc(p.notas || "")}</td>
        <td>${n ? `<div class="cm-miniaturas">${p.fotos.map((f) => `<img data-cm-foto="${f.id}" alt="Foto" data-cm-grande="${f.id}">`).join("")}</div>` : "—"}</td>
        <td class="acciones"><button type="button" class="btn btn-chico" data-cm-a="ver" data-k="${k}">Ver en mapa</button>
          ${porDecidir(p) ? `<button type="button" class="btn btn-chico" data-cm-a="editar" data-k="${k}">Editar</button>
          <button type="button" class="btn btn-chico btn-primario" data-cm-a="aprobar" data-k="${k}">Aprobar…</button>
          <button type="button" class="btn btn-chico peligro" data-cm-a="rechazar" data-k="${k}">Rechazar…</button>` : ""}</td></tr>`;
  }

  function filaTrazo(t) {
    const k = llave(t);
    return `<tr data-k="${k}"><td>${porDecidir(t) ? `<input type="checkbox" data-cm-sel="${k}" ${st.seleccion.has(k) ? "checked" : ""} aria-label="Elegir">` : ""}</td>
        <td><span class="cm-est ${esc(t.estado)}">${esc(ESTADO[t.estado])}</span>${t.motivo_rechazo ? `<div class="nota">${esc(t.motivo_rechazo)}</div>` : ""}</td>
        <td><b>${esc(descTrazo(t))}</b><div class="nota">Cable trazado · ${esc(t.modo)} · ${t.n_puntos} puntos${(t.postes || []).length ? ` · ${t.postes.length} sobre postes` : ""}</div></td>
        <td>${esc(t.usuario)}<div class="nota">${esc((st.jornadas.get(t.jornada_id) || {}).nombre || "sin jornada")} · ${esc(fechaHora(t.capturado_en))}</div></td>
        <td>—</td><td class="cm-notas">${esc(t.notas || "")}</td><td>—</td>
        <td class="acciones"><button type="button" class="btn btn-chico" data-cm-a="ver" data-k="${k}">Ver en mapa</button>
          ${porDecidir(t) ? `<button type="button" class="btn btn-chico btn-primario" data-cm-a="aprobar" data-k="${k}">Aprobar…</button>
          <button type="button" class="btn btn-chico peligro" data-cm-a="rechazar" data-k="${k}">Rechazar…</button>` : ""}</td></tr>`;
  }

  function pintarVista() {
    llenarFiltros();
    const lista = filtrados(), porRevisar = todos().filter(porDecidir).length;
    $("cm-estado").textContent = `${lista.length} elemento${lista.length === 1 ? "" : "s"}${porRevisar ? ` · ${porRevisar} por revisar en total` : ""}`;
    $("cm-filas").innerHTML = lista.map((x) => (esTrazo(x) ? filaTrazo(x) : filaPunto(x))).join("") || `<tr><td colspan="8" class="vacio">Nada con estos filtros.</td></tr>`;
    cargarMiniaturas($("cm-filas"));
    pintarLote();
  }

  function pintarLote() {
    st.seleccion.forEach((k) => { const o = objeto(k); if (!o || !porDecidir(o)) st.seleccion.delete(k); });
    const n = st.seleccion.size;
    $("cm-lote").hidden = n === 0;
    $("cm-lote-texto").textContent = `${n} elemento${n === 1 ? "" : "s"} elegido${n === 1 ? "" : "s"}`;
    $("cm-todos").checked = n > 0 && filtrados().filter(porDecidir).every((p) => st.seleccion.has(llave(p)));
  }

  function irAlMapa(k) {
    const o = objeto(k);
    if (!o) return;
    st.visibles.add(clave(o));
    st.ctx.mostrarVista("mapa");
    repintar();
    if (esTrazo(o)) { st.ctx.mapa.fitBounds(L.latLngBounds(o.puntos), { padding: [60, 60], maxZoom: 19 }); return; }
    st.ctx.mapa.setView([o.lat, o.lon], Math.max(st.ctx.mapa.getZoom(), 19));
    st.capa.eachLayer((m) => { if (m.getLatLng && m.getLatLng().lat === o.lat && m.getLatLng().lng === o.lon) m.openPopup(); });
  }

  const accion = (a, k) => (a === "ver" ? irAlMapa(k) : a === "editar" ? editar(Number(k.slice(1))) : a === "aprobar" ? aprobar([k]) : a === "rechazar" ? rechazar([k]) : null);

  function conectarVista() {
    ["cm-f-estado", "cm-f-tecnico", "cm-f-jornada", "cm-f-tipo"].forEach((i) => $(i).addEventListener("change", pintarVista));
    $("cm-f-texto").addEventListener("input", pintarVista);
    $("cm-recargar").addEventListener("click", async () => { try { await cargarTodo(); } catch (e) { st.ctx.mensaje(e.message, "error"); } });
    $("cm-filas").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cm-a]"), foto = e.target.closest("[data-cm-grande]");
      if (b) accion(b.dataset.cmA, b.dataset.k);
      else if (foto) verFoto(Number(foto.dataset.cmGrande));
    });
    $("cm-filas").addEventListener("change", (e) => {
      const c = e.target.closest("[data-cm-sel]");
      if (c) { if (c.checked) st.seleccion.add(c.dataset.cmSel); else st.seleccion.delete(c.dataset.cmSel); pintarLote(); }
    });
    $("cm-todos").addEventListener("change", (e) => {
      filtrados().filter(porDecidir).forEach((p) => (e.target.checked ? st.seleccion.add(llave(p)) : st.seleccion.delete(llave(p))));
      pintarVista();
    });
    $("cm-lote-aprobar").addEventListener("click", () => aprobar([...st.seleccion]));
    $("cm-lote-rechazar").addEventListener("click", () => rechazar([...st.seleccion]));
  }

  // ---------------------------------------------------------------- arranque

  function iniciar(ctx) {
    st.ctx = ctx;
    if (!window.Redes) return;
    window.Redes.cuandoListo(async () => {
      const e = window.Redes.estado;
      const revisa = window.Redes.disponible && e && e.puede && e.puede.editar;
      const boton = document.querySelector('#menu-lateral [data-vista="campo"]');
      if (!revisa) { if (boton) boton.hidden = true; return; }       // a technician or a reader has nothing to review
      st.activo = true;
      st.capa = L.layerGroup().addTo(ctx.mapa);
      st.capaVivo = L.layerGroup().addTo(ctx.mapa);
      if (window.Lugares) window.Lugares.registrarSeccion(seccion);
      conectarVista();
      ctx.mapa.on("popupopen", (ev) => {
        const raiz = ev.popup.getElement();
        if (!raiz || !raiz.querySelector(".campo-popup")) return;
        cargarMiniaturas(raiz);
        raiz.addEventListener("click", (c) => {
          const b = c.target.closest("[data-cm-p]"), f = c.target.closest("img[data-cm-foto]");
          if (b) { ev.popup.close(); accion(b.dataset.cmP, b.dataset.k); }
          else if (f) verFoto(Number(f.dataset.cmFoto));
        });
      });
      try { await cargarTodo(); } catch (err) { ctx.mensaje(`Campo: ${err.message}`, "error"); }
      st.tictac = setInterval(pintarVivo, REFRESCO_VIVO_MS);                        // the «hace N min» of the technicians
      setInterval(() => { cargarTodo().catch(() => {}); }, REFRESCO_SEGURO_MS);     // a net under the live notices: if one is lost, this brings everything
      if (ctx.api && ctx.api.campo_escuchar) ctx.api.campo_escuchar().catch(() => {});
    });
  }

  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.campo = { mostrar() { st.mostrada = true; if (st.activo) pintarVista(); } };
  window.CampoVisor = { iniciar, evento, aprobar, rechazar, editar, recargar: cargarTodo, estado: () => ({ puntos: vivos(), trazos: [...st.trazos.values()], ubicaciones: st.ubic, visibles: [...st.visibles] }) };
})();
