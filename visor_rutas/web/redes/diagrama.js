/* Diagrama lógico de red (fase 6 del módulo de redes).
 *
 * DiagramaLogico.abrir(proyectoId, {inicio?}) abre la ventana "Diagrama lógico de red":
 *   - arriba, el formulario (título, elemento de inicio: nodo / OLT, mufa o splitter; dirección
 *     derecha / izquierda; incluir inmuebles / clientes) y la tabla de diagramas guardados;
 *   - abajo, el diagrama generado AUTOMÁTICAMENTE de las conexiones guardadas
 *     (Redes.llamar("generar_diagrama"), visor_rutas/redes/diagrama.py): cada caja (OLT, SC, FDT,
 *     FAT) con sus splitters y conectores y las líneas de sus conexiones, y los cables entre cajas
 *     con su nombre, hilos y color por capacidad (144 rojo, 48 morado…; business_rules.yaml).
 *   - Zoom (rueda), desplazamiento (arrastrar), clic en una caja: su editor de mufa.
 *   - Exportar PNG y PDF: el dibujo completo con título y leyenda (api.guardar_imagen).
 * La posición de las cajas se calcula aquí: árbol de izquierda a derecha (o al revés).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const COLOR = { olt: "#f5a623", sc: "#e53935", fdt: "#d4b000", fat: "#d500f9", cliente: "#2e9d4a", derivacion: "#8e24aa" };
  const ANCHO = 250, SEP_X = 210, SEP_Y = 46, FILA = 32, CABEZA = 24;
  const LINEA_INTERNA = "#3d8bd9";
  const st = { proyecto: null, puedeEditar: false, lista: [], inicios: [], editando: null, datos: null, tituloAuto: true,
               stage: null, capa: null, maximizado: false };
  const mensaje = (t, tipo) => Redes.estadoEn($("dg-estado"), t, tipo);

  // ------------------------------------------------------------------ ventana, lista y formulario
  async function abrir(proyectoId, opciones = {}) {
    $("modal-dg").hidden = false;
    crearStage();
    const r = await Redes.llamar("diagramas", { proyecto_id: proyectoId });
    if (!r.ok) { mensaje(r.error, "error"); return false; }
    cargarLista(r);
    limpiar();
    if (opciones.inicio) {
      $("dg-f-inicio").value = opciones.inicio;
      autoTitulo();
      await generar();
    } else if (st.lista.length === 1) {
      await abrirGuardado(st.lista[0]);
    }
    return true;
  }

  function cargarLista(r) {
    st.proyecto = r.proyecto;
    st.puedeEditar = !!r.proyecto.puede_editar;
    st.lista = r.diagramas;
    st.inicios = r.inicios;
    $("dg-titulo").textContent = `Diagrama lógico de red · ${r.proyecto.nombre}`;
    const actual = $("dg-f-inicio").value;
    $("dg-f-inicio").innerHTML = `<option value="">Elija nodo / OLT, mufa o splitter…</option>`
      + st.inicios.map((i) => `<option value="${esc(i.clave)}">${esc(i.texto)}</option>`).join("");
    if (actual) $("dg-f-inicio").value = actual;
    $("dg-guardar").hidden = !st.puedeEditar;
    pintarLista();
  }

  function pintarLista() {
    $("dg-lista").innerHTML = st.lista.map((d, i) => `<tr data-dg="${d.id}" class="${st.editando && st.editando.id === d.id ? "sel" : ""}">
        <td>${i + 1}</td><td>${esc(d.titulo)}</td>
        <td>${esc(d.elemento || "—")}${d.inicio_eliminado ? ` <span class="pr-etq">eliminado</span>` : ""}</td>
        <td>${esc(d.caja || "—")}</td><td>${d.direccion === "izquierda" ? "Izquierda" : "Derecha"}</td>
        <td><input type="checkbox" disabled ${d.incluir_clientes ? "checked" : ""} aria-label="Incluir clientes"></td>
        <td>${st.puedeEditar ? `<button type="button" class="btn-icono peligro" data-dg-eliminar="${d.id}" title="Eliminar" aria-label="Eliminar">
          <svg><use href="#i-papelera"/></svg></button>` : ""}</td></tr>`).join("")
      || `<tr><td colspan="7" class="vacio">Todavía no hay diagramas guardados en este proyecto.</td></tr>`;
  }

  function limpiar() {
    st.editando = null;
    st.tituloAuto = true;
    $("dg-f-titulo").value = "";
    $("dg-f-inicio").value = "";
    $("dg-f-direccion").value = "derecha";
    $("dg-f-clientes").checked = false;
    mensaje("");
    pintarLista();
  }

  function autoTitulo() {
    if (!st.tituloAuto) return;
    const i = st.inicios.find((x) => x.clave === $("dg-f-inicio").value);
    $("dg-f-titulo").value = i ? `${st.proyecto.nombre} | ${i.texto}` : "";
  }

  const formulario = () => ({ titulo: $("dg-f-titulo").value.trim(), inicio: $("dg-f-inicio").value, direccion: $("dg-f-direccion").value,
                              incluir_clientes: $("dg-f-clientes").checked });

  async function generar(ev) {
    if (ev) ev.preventDefault();
    const f = formulario();
    if (!f.inicio) { mensaje("Elija el elemento de inicio", "error"); return; }
    mensaje("Generando el diagrama…", "cargando");
    const r = await Redes.llamar("generar_diagrama", { proyecto_id: st.proyecto.id, ...f });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    mensaje("");
    dibujar(r);
  }

  async function abrirGuardado(d) {
    st.editando = d;
    st.tituloAuto = false;
    $("dg-f-titulo").value = d.titulo;
    $("dg-f-inicio").value = d.inicio_eliminado ? "" : d.inicio;
    $("dg-f-direccion").value = d.direccion;
    $("dg-f-clientes").checked = d.incluir_clientes;
    pintarLista();
    mensaje("Generando el diagrama…", "cargando");
    const r = await Redes.llamar("generar_diagrama", { diagrama_id: d.id });
    if (!r.ok) { mensaje(r.error, "error"); vaciar(); return; }
    mensaje("");
    dibujar(r);
  }

  async function guardar() {
    const f = formulario();
    if (!f.titulo) autoTitulo();
    const datos = { ...formulario(), ...(st.editando ? { id: st.editando.id, version: st.editando.version } : {}) };
    const r = await Redes.llamar("guardar_diagrama", { proyecto_id: st.proyecto.id, datos });
    if (!r.ok) {
      mensaje(r.errores ? Object.values(r.errores).join(" · ") : r.error, "error");
      return;
    }
    cargarLista(r);
    st.editando = st.lista.find((d) => d.id === r.id) || null;
    st.tituloAuto = false;
    pintarLista();
    mensaje(`Diagrama "${datos.titulo}" guardado`, "ok");
    await generar();
  }

  async function eliminar(id) {
    const d = st.lista.find((x) => x.id === id);
    if (!d || !(await Redes.confirmar(`¿Eliminar el diagrama "${d.titulo}" de la lista? (El dibujo se puede volver a generar)`, "Eliminar"))) return;
    const r = await Redes.llamar("eliminar_diagrama", { id: d.id, version: d.version });
    if (!r.ok) { mensaje(r.error, "error"); return; }
    if (st.editando && st.editando.id === id) st.editando = null;
    cargarLista(r);
    mensaje("Diagrama eliminado", "ok");
  }

  // ------------------------------------------------------------------ lienzo
  function crearStage() {
    if (st.stage) return;
    const caja = $("dg-lienzo");
    st.stage = new Konva.Stage({ container: $("dg-konva"), width: caja.clientWidth || 800, height: caja.clientHeight || 400, draggable: true,
                                 dragDistance: 4 });
    st.capa = new Konva.Layer();
    st.stage.add(st.capa);
    st.stage.on("wheel", (e) => {
      e.evt.preventDefault();
      const viejo = st.stage.scaleX(), p = st.stage.getPointerPosition();
      const punto = { x: (p.x - st.stage.x()) / viejo, y: (p.y - st.stage.y()) / viejo };
      const nuevo = Math.max(0.1, Math.min(4, viejo * (e.evt.deltaY > 0 ? 1 / 1.12 : 1.12)));
      st.stage.scale({ x: nuevo, y: nuevo });
      st.stage.position({ x: p.x - punto.x * nuevo, y: p.y - punto.y * nuevo });
    });
    new ResizeObserver(medir).observe(caja);
  }

  function medir() {
    const caja = $("dg-lienzo");
    if (st.stage && caja.clientWidth) st.stage.size({ width: caja.clientWidth, height: caja.clientHeight });
  }

  function vaciar() {
    st.datos = null;
    st.capa.destroyChildren();
    st.capa.draw();
    $("dg-vacio").hidden = false;
    $("dg-png").disabled = $("dg-pdf").disabled = true;
    $("dg-info").textContent = "";
  }

  function ajustar() {
    medir();
    const r = st.capa.getClientRect({ relativeTo: st.stage });
    if (!r.width || !r.height) return;
    const s = Math.max(0.1, Math.min(1.2, Math.min((st.stage.width() - 40) / r.width, (st.stage.height() - 40) / r.height)));
    st.stage.scale({ x: s, y: s });
    st.stage.position({ x: 20 - r.x * s + (st.stage.width() - 40 - r.width * s) / 2, y: 20 - r.y * s });
  }

  function tooltip(html) {
    const caja = $("dg-tooltip");
    if (!html) { caja.hidden = true; return; }
    caja.innerHTML = html;
    caja.hidden = false;
    const p = st.stage.getPointerPosition() || { x: 0, y: 0 };
    const lienzo = $("dg-lienzo");
    caja.style.left = `${Math.max(4, Math.min(p.x + 16, lienzo.clientWidth - caja.offsetWidth - 8))}px`;
    caja.style.top = `${p.y + 16 + caja.offsetHeight <= lienzo.clientHeight ? p.y + 16 : Math.max(4, p.y - 12 - caja.offsetHeight)}px`;
  }

  // ------------------------------------------------------------------ dibujo
  const filas = (c) => Math.max(1, c.splitters.length + c.conectores.length, c.salidas.length);
  const tamano = (c) => (c.tipo === "cliente" ? { w: 190, h: 50 }
    : { w: ANCHO, h: CABEZA + filas(c) * FILA + 8 + (c.clientes_omitidos ? 16 : 0) });

  /** Tree layout: children stacked, the parent centred on them; x by level. */
  function ubicar(d) {
    const hijos = new Map();
    const porId = new Map(d.cajas.map((c) => [c.id, c]));
    d.cajas.forEach((c) => {
      if (c.padre == null) return;
      if (!hijos.has(c.padre)) hijos.set(c.padre, []);
      hijos.get(c.padre).push(c);
    });
    hijos.forEach((lista, padre) => {                     // the same order as the parent's output ports
      const orden = porId.get(padre).salidas;
      lista.sort((a, b) => orden.indexOf(a.entrada) - orden.indexOf(b.entrada));
    });
    const alto = new Map();
    const medirSub = (c) => {
      const h = tamano(c).h, hs = (hijos.get(c.id) || []).map(medirSub);
      const total = Math.max(h, hs.reduce((a, b) => a + b, 0) + SEP_Y * Math.max(0, hs.length - 1));
      alto.set(c.id, total);
      return total;
    };
    const izq = d.direccion === "izquierda";
    const colocar = (c, arriba) => {
      const t = tamano(c), sub = alto.get(c.id);
      c._w = t.w; c._h = t.h;
      c._x = izq ? -c.nivel * (ANCHO + SEP_X) - t.w : c.nivel * (ANCHO + SEP_X);
      c._y = arriba + (sub - t.h) / 2;
      let y = arriba + (sub - (hijos.get(c.id) || []).reduce((a, h) => a + alto.get(h.id), 0)
        - SEP_Y * Math.max(0, (hijos.get(c.id) || []).length - 1)) / 2;
      (hijos.get(c.id) || []).forEach((h) => { colocar(h, y); y += alto.get(h.id) + SEP_Y; });
    };
    const raiz = d.cajas[0];
    medirSub(raiz);
    colocar(raiz, 0);
    return porId;
  }

  function dibujar(d) {
    st.datos = d;
    st.capa.destroyChildren();
    $("dg-vacio").hidden = true;
    const porId = ubicar(d);
    const izq = d.direccion === "izquierda";
    // X(c, rx): rx measured from the box's entry side
    const X = (c, rx) => (izq ? c._x + c._w - rx : c._x + rx);
    const puerto = (c, clave) => {                        // position of a port / piece end inside box c
      const fila = (i) => c._y + CABEZA + i * FILA + FILA / 2;
      if (clave === "entrada") return { x: X(c, 0), y: c._y + c._h / 2 };
      if (clave.startsWith("salida:")) {
        const i = c.salidas.indexOf(Number(clave.split(":")[1]));
        return { x: X(c, c._w), y: fila(Math.max(0, i)) };
      }
      const [tipo, id, lado] = clave.split(":");
      const piezas = [...c.splitters.map((s) => `splitter:${s.id}`), ...c.conectores.map((k) => `conector:${k.id}`)];
      const i = piezas.indexOf(`${tipo}:${id}`);
      const centro = c._w / 2;
      const medio = tipo === "splitter" ? 26 : 14;
      return { x: X(c, lado === "entrada" ? centro - medio : centro + medio), y: fila(Math.max(0, i)) };
    };
    const ortogonal = (p1, p2) => { const m = (p1.x + p2.x) / 2; return [p1.x, p1.y, m, p1.y, m, p2.y, p2.x, p2.y]; };

    // cables between boxes (under the boxes); a box that feeds 2+ cables gets a derivation dot on each exit
    const derivaciones = [];
    d.cables.forEach((k) => {
      const a = porId.get(k.desde), b = porId.get(k.hasta);
      if (!a || !b) return;
      const p1 = puerto(a, `salida:${k.id}`), p2 = puerto(b, "entrada");
      const linea = new Konva.Line({ points: ortogonal(p1, p2), stroke: k.color, strokeWidth: k.hilos >= 48 ? 3 : 2, hitStrokeWidth: 12,
                                     lineJoin: "round" });
      linea.on("mouseenter", () => tooltip(htmlCable(k)));
      linea.on("mouseleave", () => tooltip(null));
      st.capa.add(linea);
      const m = (p1.x + p2.x) / 2;
      const desde = izq ? p2.x + 6 : m + 8, ancho = Math.abs(p2.x - m) - 14;
      st.capa.add(new Konva.Text({ x: desde, y: p2.y - 30, width: ancho, text: k.nombre, fontSize: 11, fontStyle: "bold", fill: "#1d2128",
                                   wrap: "none", ellipsis: true, align: izq ? "right" : "left", listening: false }));
      st.capa.add(new Konva.Text({ x: desde, y: p2.y - 16, width: ancho, text: `${k.hilos ?? "?"} hilos · ${k.usados} usado${k.usados === 1 ? "" : "s"}`,
                                   fontSize: 10, fill: "#5b6270", wrap: "none", ellipsis: true, align: izq ? "right" : "left", listening: false }));
      if (a.salidas.length > 1) derivaciones.push(p1);
    });

    // boxes
    d.cajas.forEach((c) => {
      const g = new Konva.Group({ name: "caja" });
      g.setAttr("caja", c.id);
      const navegable = ["mufa", "nodo", "odf"].includes(c.tipo);
      g.add(new Konva.Rect({ x: c._x, y: c._y, width: c._w, height: c._h, fill: "#fff", stroke: COLOR[c.simbolo] || "#555", strokeWidth: 2,
                             cornerRadius: c.tipo === "cliente" ? 8 : 3, shadowColor: "#000", shadowOpacity: 0.12, shadowBlur: 5 }));
      if (c.tipo === "cliente") {
        g.add(simbolo("cliente", c._x + 16, c._y + 25, 9));
        g.add(new Konva.Text({ x: c._x + 30, y: c._y + 8, width: c._w - 36, fontSize: 11, fill: "#1d2128", lineHeight: 1.3,
                               text: `${c.nombre}\n${[c.codigo, c.id_servicio && `ID ${c.id_servicio}`].filter(Boolean).join(" · ")}` }));
      } else {
        // title above the box: symbol + "FAT 1 (1x8)"
        const titulo = new Konva.Text({ x: c._x - 30, y: c._y - 22, width: c._w + 60, align: "center", text: c.etiqueta, fontSize: 13,
                                        fontStyle: "bold", fill: "#1d2128", wrap: "none", ellipsis: true });
        g.add(titulo);
        const anchoTexto = Math.min(titulo.getTextWidth(), c._w + 60);
        g.add(simbolo(c.simbolo, c._x + c._w / 2 - anchoTexto / 2 - 14, c._y - 14, 8));
        if (c.entrada != null) g.add(new Konva.Rect({ x: X(c, 0) - 4, y: c._y + c._h / 2 - 4, width: 8, height: 8, fill: "#1d2128" }));
        c.salidas.forEach((cid) => { const p = puerto(c, `salida:${cid}`); g.add(new Konva.Rect({ x: p.x - 4, y: p.y - 4, width: 8, height: 8, fill: "#1d2128" })); });
        // internal connections
        c.lineas.forEach((l) => {
          const p1 = puerto(c, l.de), p2 = puerto(c, l.a);
          g.add(new Konva.Line({ points: ortogonal(p1, p2), stroke: LINEA_INTERNA, strokeWidth: 1.5, listening: false }));
          if (l.hilos > 1) g.add(new Konva.Text({ x: (p1.x + p2.x) / 2 + 3, y: p2.y - 12, text: `×${l.hilos}`, fontSize: 9, fill: "#1e429f", listening: false }));
        });
        // splitters and connectors in the middle
        c.splitters.forEach((s) => {
          const e = puerto(c, `splitter:${s.id}:entrada`), sa = puerto(c, `splitter:${s.id}:salida`);
          g.add(new Konva.Line({ points: [e.x, e.y, sa.x, e.y - 8, sa.x, e.y + 8], closed: true, fill: "#9aa3ad", stroke: "#1a1a1a", strokeWidth: 1 }));
          g.add(new Konva.Text({ x: Math.min(e.x, sa.x) - 40, y: e.y - 21, width: 52 + 80, align: "center", fontSize: 9.5, fill: "#374151",
                                 text: `${s.nombre} 1x${s.salidas}${s.relacion ? ` ${s.relacion}` : ""}`, wrap: "none", ellipsis: true }));
        });
        c.conectores.forEach((k) => {
          const e = puerto(c, `conector:${k.id}:entrada`), sa = puerto(c, `conector:${k.id}:salida`);
          g.add(new Konva.Rect({ x: Math.min(e.x, sa.x), y: e.y - 5, width: Math.abs(sa.x - e.x), height: 10, fill: "#5b6270", cornerRadius: 4 }));
          g.add(new Konva.Text({ x: Math.min(e.x, sa.x) - 40, y: e.y - 18, width: 108, align: "center", fontSize: 9.5, fill: "#374151",
                                 text: k.nombre, wrap: "none", ellipsis: true }));
        });
        if (c.clientes_omitidos) {
          g.add(new Konva.Text({ x: c._x + 8, y: c._y + c._h - 16, text: `+ ${c.clientes_omitidos} cliente${c.clientes_omitidos === 1 ? "" : "s"} (no incluidos)`,
                                 fontSize: 10, fill: "#2e7d32" }));
        }
      }
      g.on("mouseenter", () => { st.stage.container().style.cursor = navegable ? "pointer" : "default"; tooltip(htmlCaja(c)); });
      g.on("mouseleave", () => { st.stage.container().style.cursor = ""; tooltip(null); });
      g.on("click tap", () => { if (navegable && window.EditorMufa) { tooltip(null); window.EditorMufa.abrir(c.id, c.nombre); } });
      st.capa.add(g);
    });
    derivaciones.forEach((p) => st.capa.add(new Konva.Circle({ x: p.x, y: p.y, radius: 5, fill: COLOR.derivacion, listening: false })));
    encabezadoYLeyenda(d);
    st.capa.draw();
    ajustar();
    $("dg-png").disabled = $("dg-pdf").disabled = false;
    $("dg-info").textContent = `${d.cajas.length} caja${d.cajas.length === 1 ? "" : "s"} · ${d.cables.length} cable${d.cables.length === 1 ? "" : "s"}`
      + (d.recortado ? " · recortado (demasiadas cajas)" : "") + " · clic en una caja: su editor de mufa";
  }

  function simbolo(tipo, x, y, r) {
    const c = COLOR[tipo] || "#555";
    if (tipo === "olt") return new Konva.RegularPolygon({ x, y, sides: 3, radius: r + 2, fill: c, listening: false });
    if (tipo === "fdt") return new Konva.Rect({ x: x - r, y: y - r, width: 2 * r, height: 2 * r, stroke: c, strokeWidth: 2.5, fill: "#fffbe6", listening: false });
    if (tipo === "cliente") return new Konva.Line({ points: [x - r, y + r, x - r, y - 2, x, y - r - 2, x + r, y - 2, x + r, y + r], closed: true,
                                                    fill: c, listening: false });
    if (tipo === "derivacion") return new Konva.Circle({ x, y, radius: r * 0.6, fill: c, listening: false });
    return new Konva.Circle({ x, y, radius: r, stroke: c, strokeWidth: 2.5, fill: "#fff", listening: false });    // sc / fat
  }

  /** Title (top-left) and legend (right of the drawing): both are part of the exported image. */
  function encabezadoYLeyenda(d) {
    const r = st.capa.getClientRect({ relativeTo: st.capa });
    const ahora = new Date().toLocaleString("es-NI", { dateStyle: "short", timeStyle: "short" });
    st.capa.add(new Konva.Text({ x: r.x, y: r.y - 64, text: d.titulo, fontSize: 18, fontStyle: "bold", fill: "#1d2128", listening: false }));
    st.capa.add(new Konva.Text({ x: r.x, y: r.y - 40, fontSize: 11, fill: "#5b6270", listening: false,
      text: `Proyecto ${d.proyecto.nombre} (${d.proyecto.codigo}) · desde ${d.inicio.texto} · ${d.direccion === "izquierda" ? "hacia la izquierda" : "hacia la derecha"}`
        + ` · generado ${ahora} de las conexiones guardadas` }));
    const g = new Konva.Group({ x: r.x + r.width + 50, y: r.y, listening: false });
    const items = [...d.leyenda.simbolos.map((s) => ({ s })), ...d.leyenda.colores.map((k) => ({ k }))];
    const alto = 34 + items.length * 22;
    g.add(new Konva.Rect({ width: 200, height: alto, fill: "#fff", stroke: "#cfd6e0", cornerRadius: 6 }));
    g.add(new Konva.Text({ x: 12, y: 10, text: "Leyenda en diagramas FTTH", fontSize: 12, fontStyle: "bold", fill: "#1d2128" }));
    items.forEach((it, i) => {
      const y = 40 + i * 22;
      if (it.s) {
        g.add(simbolo(it.s.simbolo, 22, y, 7));
        g.add(new Konva.Text({ x: 40, y: y - 6, text: it.s.texto, fontSize: 11, fill: "#1d2128" }));
      } else {
        g.add(new Konva.Line({ points: [12, y, 34, y], stroke: it.k.color, strokeWidth: it.k.hilos >= 48 ? 3 : 2 }));
        g.add(new Konva.Text({ x: 40, y: y - 6, text: `Cable de ${it.k.hilos} hilos`, fontSize: 11, fill: "#1d2128" }));
      }
    });
    st.capa.add(g);
  }

  function htmlCaja(c) {
    const nombres = { olt: "OLT / nodo", sc: "SC · mufa de empalme", fdt: "FDT · distribución", fat: "FAT · terminal", cliente: "Cliente" };
    const sp = c.splitters.map((s) => `${esc(s.nombre)} 1x${s.salidas}${s.relacion ? ` ${esc(s.relacion)}` : ""}`).join(", ");
    return `<div class="mu-tt-titulo">${esc(c.nombre)}</div><div>${nombres[c.simbolo] || esc(c.tipo)}</div>
      ${sp ? `<div>Splitters: ${sp}</div>` : ""}${c.conectores.length ? `<div>Conectores: ${c.conectores.map((k) => esc(k.nombre)).join(", ")}</div>` : ""}
      ${c.tipo !== "cliente" ? `<div>${c.salidas.length} cable(s) de salida en el diagrama</div>` : ""}
      ${c.clientes_omitidos ? `<div>${c.clientes_omitidos} cliente(s) no incluidos</div>` : ""}
      ${["mufa", "nodo", "odf"].includes(c.tipo) ? `<div class="mu-tt-sec">Clic: abrir el editor de mufa</div>` : ""}`;
  }

  function htmlCable(k) {
    return `<div class="mu-tt-titulo">${esc(k.nombre)}</div><div>${esc(k.tipo)} · ${k.hilos == null ? "hilos desconocidos" : `${k.hilos} hilos`} ·${k.usados} usado${k.usados === 1 ? "" : "s"}</div>
      <div>Longitud ${Math.round(k.longitud_m)} m${k.metraje_m != null ? ` · metraje ${k.metraje_m} m` : ""}</div>`;
  }

  // ------------------------------------------------------------------ exportar
  /** The whole drawing (title and legend included) at up to 2x, on white. */
  function imagen() {
    const r = st.capa.getClientRect({ relativeTo: st.stage });
    const margen = 30, ancho = r.width + 2 * margen, alto = r.height + 2 * margen;
    const ratio = Math.max(0.5, Math.min(2, 14000 / Math.max(ancho, alto)));
    const antes = { s: st.stage.scaleX(), x: st.stage.x(), y: st.stage.y(), w: st.stage.width(), h: st.stage.height() };
    st.stage.scale({ x: 1, y: 1 });
    st.stage.position({ x: margen - r.x, y: margen - r.y });
    st.stage.size({ width: ancho, height: alto });
    const fondo = new Konva.Rect({ x: r.x - margen, y: r.y - margen, width: ancho, height: alto, fill: "#ffffff", listening: false });
    st.capa.add(fondo);
    fondo.moveToBottom();
    st.capa.draw();
    const url = st.stage.toDataURL({ pixelRatio: ratio, mimeType: "image/png" });
    fondo.destroy();
    st.stage.size({ width: antes.w, height: antes.h });
    st.stage.scale({ x: antes.s, y: antes.s });
    st.stage.position({ x: antes.x, y: antes.y });
    st.capa.draw();
    return url;
  }

  async function exportar(tipo) {
    if (!st.datos || !Redes.api || !Redes.api.guardar_imagen) return;
    mensaje(`Preparando el ${tipo.toUpperCase()}…`, "cargando");
    const r = await Redes.api.guardar_imagen(st.datos.titulo, imagen(), tipo);
    if (r && r.ok) mensaje(`Guardado: ${r.ruta}`, "ok");
    else mensaje(r && r.cancelado ? "" : (r && r.error) || "No se pudo guardar", r && r.cancelado ? "" : "error");
  }

  // ------------------------------------------------------------------ eventos
  function cerrar() {
    $("modal-dg").hidden = true;
    tooltip(null);
  }

  function conectar() {
    $("dg-cerrar").addEventListener("click", cerrar);
    $("dg-max").addEventListener("click", () => { st.maximizado = !st.maximizado; $("modal-dg").classList.toggle("maximizado", st.maximizado); });
    $("dg-form").addEventListener("submit", generar);
    $("dg-guardar").addEventListener("click", guardar);
    $("dg-nuevo").addEventListener("click", () => { limpiar(); vaciar(); });
    $("dg-f-inicio").addEventListener("change", autoTitulo);
    $("dg-f-titulo").addEventListener("input", () => { st.tituloAuto = !$("dg-f-titulo").value.trim(); });
    $("dg-lista").addEventListener("click", (e) => {
      const borrar = e.target.closest("[data-dg-eliminar]");
      if (borrar) { e.stopPropagation(); eliminar(Number(borrar.dataset.dgEliminar)); return; }
      const fila = e.target.closest("[data-dg]");
      if (fila) abrirGuardado(st.lista.find((d) => d.id === Number(fila.dataset.dg)));
    });
    $("dg-ajustar").addEventListener("click", ajustar);
    $("dg-acercar").addEventListener("click", () => st.stage.scale({ x: st.stage.scaleX() * 1.2, y: st.stage.scaleY() * 1.2 }));
    $("dg-alejar").addEventListener("click", () => st.stage.scale({ x: st.stage.scaleX() / 1.2, y: st.stage.scaleY() / 1.2 }));
    $("dg-png").addEventListener("click", () => exportar("png"));
    $("dg-pdf").addEventListener("click", () => exportar("pdf"));
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || $("modal-dg").hidden) return;
      const encima = ["modal-mufa", "modal-confirmar", "modal-mu-objeto", "modal-mu-nota"].some((id) => $(id) && !$(id).hidden);
      if (!encima) { e.stopPropagation(); cerrar(); }
    }, true);
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.DiagramaLogico = { abrir, cerrar, _st: st, _imagen: imagen };
})();
