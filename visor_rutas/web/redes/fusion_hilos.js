/* Conexión de hilos entre dos cables de una mufa, desde el esquema de zona (fase 2: «cuál hilo está conectado con cuál»).
 *
 * FusionHilos.abrir(mufaId, { cableId? }) abre la ventana «Conexión de hilos en <mufa>»: se eligen dos de los cables que llegan a esa mufa (lado A y lado B) y, por cada hilo
 * del cable A, se elige con qué hilo del cable B se fusiona (o ninguno). Lo que ya está conectado sale elegido; un hilo conectado a un splitter, a un conector o a un tercer
 * cable sale bloqueado con su destino; un hilo del cable B solo se puede elegir una vez. «1 a 1» conecta cada hilo libre con el del mismo número y «Quitar todas» suelta
 * las del par. Se guarda con Redes.llamar("guardar_mufa") (las mismas conexiones del editor de mufa, con sus reglas: una fusión une hilos de cables distintos).
 * El cliente que está en un hilo (etiqueta verde del editor de mufa) se ve junto al hilo.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const TIA = ["#1f5fd1", "#f28c28", "#2e9d4a", "#8b5a2b", "#8c8c8c", "#ffffff", "#e53935", "#111111", "#f7d117", "#7e3fbf", "#f06ba8", "#2ec4d6"];
  const TIA_NOMBRE = ["azul", "naranja", "verde", "café", "gris", "blanco", "rojo", "negro", "amarillo", "violeta", "rosa", "aqua"];
  const st = { mufaId: null, datos: null, a: null, b: null, elegido: new Map(), original: new Map(), alCerrar: null, conectado: false };
  const mensaje = (t, tipo) => Redes.estadoEn($("fh-estado"), t, tipo);

  const cableDe = (id) => st.datos.cables.find((c) => c.id === id);
  const indiceColor = (c, f) => (f.numero - 1) % (c.hilos_por_buffer || 12);
  const hiloDe = (id) => { for (const c of st.datos.cables) { const f = c.fibras.find((x) => x.id === id); if (f) return [c, f]; } return [null, null]; };
  const etiquetaHilo = (c, f) => `H${f.numero} · ${TIA_NOMBRE[indiceColor(c, f)]}`;
  const textoCliente = (f) => (f.cliente ? [f.cliente.codigo_cliente, f.cliente.nombre].filter(Boolean).join(" · ") : "");
  const puedeEditar = () => !!(st.datos && st.datos.mufa.puede_editar);

  /** What a hilo-hilo / hilo-port connection of this mufa joins, as text for the one that is on the other side of `hiloId`. */
  function destinoDe(x, hiloId) {
    const otro = x.a.hilo === hiloId ? x.b : x.a;
    if (otro.hilo != null) { const [c, f] = hiloDe(otro.hilo); return c ? `${c.nombre} · ${etiquetaHilo(c, f)}` : "otro hilo"; }
    if (otro.splitter != null) { const s = st.datos.splitters.find((y) => y.id === otro.splitter); return `${s ? s.nombre : "splitter"} · ${otro.lado === "entrada" ? "entrada" : "salida " + otro.numero}`; }
    if (otro.conector != null) { const k = st.datos.conectores.find((y) => y.id === otro.conector); return `conector ${k ? k.nombre : ""}`.trim(); }
    return "otro extremo";
  }

  /** Reads the connections of the mufa for the pair A-B: hilo of A -> {conexion, hiloB} (editable) or {bloqueada: text}. */
  function leerPar() {
    st.original = new Map(); st.elegido = new Map();
    const A = cableDe(st.a), B = cableDe(st.b);
    if (!A || !B) return;
    const idsB = new Set(B.fibras.map((f) => f.id));
    A.fibras.forEach((f) => {
      const x = st.datos.conexiones.find((c) => c.a.hilo === f.id || c.b.hilo === f.id);
      if (!x) return;
      const otro = x.a.hilo === f.id ? x.b.hilo : x.a.hilo;
      if (otro != null && idsB.has(otro)) st.original.set(f.id, { conexion: x.id, version: x.version, b: otro });
      else st.original.set(f.id, { conexion: x.id, version: x.version, bloqueada: destinoDe(x, f.id) });
    });
    st.original.forEach((o, aId) => { if (o.b) st.elegido.set(aId, o.b); });
  }

  /** The hilos of B that are taken: by another row of this pair, or connected in this mufa to something that is not an A hilo. */
  function ocupadosB(exceptoA) {
    const ocupados = new Map();
    st.elegido.forEach((bId, aId) => { if (bId && aId !== exceptoA) { const [c, f] = hiloDe(aId); ocupados.set(bId, `ya está con H${f.numero} del otro cable`); } });
    const B = cableDe(st.b), idsA = new Set(cableDe(st.a).fibras.map((f) => f.id));
    B.fibras.forEach((f) => {
      const x = st.datos.conexiones.find((c) => c.a.hilo === f.id || c.b.hilo === f.id);
      if (!x) return;
      const otro = x.a.hilo === f.id ? x.b.hilo : x.a.hilo;
      if (!(otro != null && idsA.has(otro))) ocupados.set(f.id, `conectado a ${destinoDe(x, f.id)}`);
    });
    return ocupados;
  }

  function pintar() {
    const A = cableDe(st.a), B = cableDe(st.b), editar = puedeEditar();
    if (!A || !B) { $("fh-filas").innerHTML = ""; return; }
    const filas = A.fibras.map((f) => {
      const o = st.original.get(f.id), bloqueada = o && o.bloqueada;
      const ocupados = ocupadosB(f.id), actual = st.elegido.get(f.id) || "";
      const opciones = `<option value="">— sin conectar —</option>` + B.fibras.map((g) => `<option value="${g.id}" ${ocupados.has(g.id) ? "disabled" : ""} ${actual === g.id ? "selected" : ""}>${esc(etiquetaHilo(B, g))}${ocupados.has(g.id) ? ` (${esc(ocupados.get(g.id))})` : ""}${g.cliente ? ` · ${esc(textoCliente(g))}` : ""}</option>`).join("");
      const cambiado = (actual || null) !== ((o && o.b) || null);
      return `<tr class="${cambiado ? "fh-cambio" : ""}"><td><i class="fh-punto" style="background:${TIA[indiceColor(A, f)]}"></i> <b>${esc(etiquetaHilo(A, f))}</b>${f.cliente ? ` <span class="fh-cliente">${esc(textoCliente(f))}</span>` : ""}</td>
        <td class="fh-flecha">→</td><td>${bloqueada ? `<span class="nota">Conectado a ${esc(o.bloqueada)} (se cambia en el editor de mufa)</span>`
        : `<select data-fh-hilo="${f.id}" ${editar ? "" : "disabled"}>${opciones}</select>`}</td></tr>`;
    });
    $("fh-filas").innerHTML = filas.join("");
    const hechas = [...st.elegido.values()].filter(Boolean).length;
    $("fh-cuenta").textContent = `${hechas} de ${A.fibras.length} hilos de ${A.nombre} conectados con ${B.nombre}`;
    $("fh-guardar").disabled = !editar || !hayCambios();
    $("fh-uno-a-uno").disabled = $("fh-quitar-todas").disabled = !editar;
  }

  function hayCambios() {
    const ids = new Set([...st.original.keys(), ...st.elegido.keys()]);
    for (const id of ids) {
      const o = st.original.get(id);
      if (o && o.bloqueada) continue;
      if (((st.elegido.get(id)) || null) !== ((o && o.b) || null)) return true;
    }
    return false;
  }

  function llenarCables() {
    const opciones = st.datos.cables.map((c) => `<option value="${c.id}">${esc(c.nombre)} (${c.lado === "entrada" ? "llega" : "sale"} · ${c.hilos ?? "?"} hilos · ${esc(c.otro.nombre)})</option>`).join("");
    $("fh-cable-a").innerHTML = $("fh-cable-b").innerHTML = opciones;
    $("fh-cable-a").value = String(st.a); $("fh-cable-b").value = String(st.b);
  }

  async function cargar(mufaId) {
    mensaje("Leyendo la mufa…", "cargando");
    const r = await Redes.llamar("mufa", { mufa_id: mufaId });
    if (!r.ok) { mensaje(r.error, "error"); return false; }
    mensaje("");
    st.mufaId = mufaId; st.datos = r;
    return true;
  }

  async function abrir(mufaId, opciones = {}) {
    if (!(await cargar(mufaId))) { $("modal-fh").hidden = false; return false; }
    const cables = st.datos.cables;
    $("fh-titulo").textContent = `Conexión de hilos en ${st.datos.mufa.nombre}`;
    if (cables.length < 2) {
      $("fh-aviso").textContent = cables.length ? "Esta mufa solo tiene un cable: para fusionar hilos hacen falta dos. Cree el otro cable en el esquema (Conectar con cable)." : "Esta mufa todavía no tiene cables.";
      $("fh-cuerpo").hidden = true;
      $("fh-guardar").disabled = $("fh-uno-a-uno").disabled = $("fh-quitar-todas").disabled = true;
      $("modal-fh").hidden = false;
      return true;
    }
    $("fh-aviso").textContent = ""; $("fh-cuerpo").hidden = false;
    st.a = opciones.cableId && cableDe(opciones.cableId) ? opciones.cableId : cables[0].id;
    st.b = (cables.find((c) => c.id !== st.a) || cables[1]).id;
    llenarCables(); leerPar(); pintar();
    $("modal-fh").hidden = false;
    return true;
  }

  function cambiarCables() {
    st.a = Number($("fh-cable-a").value); st.b = Number($("fh-cable-b").value);
    if (st.a === st.b) { mensaje("Elija dos cables distintos: una fusión une hilos de cables distintos", "error"); $("fh-filas").innerHTML = ""; $("fh-guardar").disabled = true; return; }
    mensaje(""); leerPar(); pintar();
  }

  function unoAUno() {
    const A = cableDe(st.a), B = cableDe(st.b);
    A.fibras.forEach((f) => {
      const o = st.original.get(f.id);
      if ((o && o.bloqueada) || st.elegido.get(f.id)) return;
      const g = B.fibras.find((x) => x.numero === f.numero);
      if (g && !ocupadosB(f.id).has(g.id)) st.elegido.set(f.id, g.id);
    });
    pintar();
  }

  function quitarTodas() {
    st.elegido.forEach((_, id) => st.elegido.set(id, null));
    pintar();
  }

  async function guardar() {
    const conexiones = [];
    let n = 0;
    const ids = new Set([...st.original.keys(), ...st.elegido.keys()]);
    ids.forEach((aId) => {
      const o = st.original.get(aId);
      if (o && o.bloqueada) return;
      const nuevo = st.elegido.get(aId) || null, previo = (o && o.b) || null;
      if (nuevo === previo) return;
      if (o) conexiones.push({ id: o.conexion, version: o.version, eliminar: true });
      if (nuevo) conexiones.push({ id: `n${++n}`, a: { hilo: aId }, b: { hilo: nuevo } });
    });
    if (!conexiones.length) return;
    $("fh-guardar").disabled = true;
    mensaje("Guardando…", "cargando");
    const r = await Redes.llamar("guardar_mufa", { mufa_id: st.mufaId, cambios: { conexiones } });
    if (!r.ok) {
      mensaje((r.errores && Object.values(r.errores).join(" · ")) || r.error, "error");
      if (r.conflicto) { await cargar(st.mufaId); leerPar(); pintar(); } else $("fh-guardar").disabled = false;
      return;
    }
    st.datos = r;
    leerPar(); pintar();
    mensaje(`Guardado: ${conexiones.filter((c) => !c.eliminar).length} conexión(es) nueva(s), ${conexiones.filter((c) => c.eliminar).length} quitada(s)`, "ok");
  }

  function cerrar() {
    $("modal-fh").hidden = true;
    if (st.alCerrar) st.alCerrar();
  }

  function conectar() {
    if (st.conectado || !$("modal-fh")) return;
    st.conectado = true;
    $("fh-cerrar").addEventListener("click", cerrar);
    $("fh-cable-a").addEventListener("change", cambiarCables);
    $("fh-cable-b").addEventListener("change", cambiarCables);
    $("fh-uno-a-uno").addEventListener("click", unoAUno);
    $("fh-quitar-todas").addEventListener("click", quitarTodas);
    $("fh-guardar").addEventListener("click", guardar);
    $("fh-filas").addEventListener("change", (e) => {
      const s = e.target.closest("select[data-fh-hilo]");
      if (!s) return;
      st.elegido.set(Number(s.dataset.fhHilo), s.value ? Number(s.value) : null);
      pintar();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || $("modal-fh").hidden || !$("modal-confirmar").hidden) return;
      e.stopPropagation(); cerrar();
    }, true);
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.FusionHilos = { abrir, cerrar, set alCerrar(f) { st.alCerrar = f; }, _st: st };
})();
