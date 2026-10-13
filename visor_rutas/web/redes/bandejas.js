/* Vista de bandejas del editor de mufa (migración Visio, fase 4: sección 8 de docs/migracion_visio/PLAN.md).
 *
 *   - Una tarjeta por bandeja (2 en una mufa de 48, 4 en una de 96) con sus 24 posiciones. Cada
 *     posición muestra el par empalmado: cable · buffer · hilo con su color TIA ↔ cable · buffer · hilo.
 *   - Una bandeja con splitter se dibuja con el splitter y solo sus posiciones (entrada + salidas)
 *     habilitadas; el resto aparece bloqueado.
 *   - Arrastrar un empalme directo a otra posición lo mueve (si está ocupada, se intercambian) y deja
 *     de ser "estimado". "Cambiar modelo" fija 48 / 96 y el formato; el selector de la bandeja le
 *     pone o quita un splitter.
 * Cada operación se guarda en el servidor al momento (bandejas.py); por eso pide no tener cambios
 * pendientes en la vista de cables.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const TIA = ["#1f5fd1", "#f28c28", "#2e9d4a", "#8b5a2b", "#8c8c8c", "#ffffff", "#e53935", "#111111", "#f7d117",
               "#7e3fbf", "#f06ba8", "#2ec4d6"];
  const mensaje = (t, tipo) => (window.visor && window.visor.mensaje ? window.visor.mensaje(t, tipo) : null);
  const E = () => window.EditorMufa;
  let visible = false;

  /** "C-Norte · B2 · H7" with the fibre and buffer colours, or the splitter / connector port. */
  function extremo(ref) {
    if (ref.hilo == null) return `<span class="bj-puerto">${esc(E().describir(ref))}</span>`;
    const [c, f] = E().fibraPorId(ref.hilo);
    if (!c) return "hilo";
    const pb = c.hilos_por_buffer, b = Math.floor((f.numero - 1) / pb), i = (f.numero - 1) % pb;
    return `<span class="bj-hilo" title="${esc(c.nombre)} · buffer ${b + 1} · hilo ${f.numero}">`
      + `<i class="bj-color" style="background:${TIA[b % 12]}"></i><i class="bj-color" style="background:${TIA[i]}"></i>`
      + `${esc(c.otro.nombre)} · B${b + 1} · H${f.numero}</span>`;
  }

  function pintar() {
    if (!E() || !E()._st.datos) return;
    const st = E()._st, r = st.datos, caja = $("mu-bandejas");
    $("mu-vista").textContent = visible ? "Ver cables" : "Ver bandejas";
    $("mu-vista").hidden = !(r.modelo || (r.mufa.tipo === "mufa" && r.mufa.subtipo !== "reserva"));
    caja.hidden = !visible;
    $("mu-konva").hidden = visible || !!(window.RedMufas && window.RedMufas.visible);
    if (!visible) return;
    if (!r.modelo) {
      caja.innerHTML = `<div class="bj-vacio"><p>Esta mufa todavía no tiene modelo (48 o 96 hilos) ni bandejas.</p>`
        + (st.puedeEditar ? `<button type="button" class="btn btn-primario" data-bj="modelo">Definir modelo</button>` : "") + "</div>";
      return;
    }
    const m = r.modelo, splitters = st.splitters;
    const porPosicion = new Map(), sinLugar = [];
    st.conexiones.forEach((x) => {
      if (![x.a, x.b].some((e) => e.hilo != null)) return;                    // port-to-port: not a splice
      if (x.bandeja) porPosicion.set(`${x.bandeja}:${x.posicion}`, x);
      else sinLugar.push(x);
    });
    const tarjetas = r.bandejas.map((b) => {
      const s = b.splitter_id ? splitters.get(b.splitter_id) : null;
      const opciones = st.puedeEditar ? `<select class="bj-splitter" data-bandeja="${b.numero}" title="Splitter de esta bandeja">
          <option value="">Empalmes directos</option>${[...splitters.values()].filter((x) => typeof x.id === "number").map((x) =>
            `<option value="${x.id}"${x.id === b.splitter_id ? " selected" : ""}>${esc(x.nombre)} (1x${x.salidas})</option>`).join("")}</select>` : "";
      const filas = [];
      for (let p = 1; p <= m.empalmes_por_bandeja; p++) {
        const habilitada = p <= b.capacidad;
        const x = porPosicion.get(`${b.numero}:${p}`);
        const etiqueta = s ? (p === 1 ? "entrada" : `salida ${p - 1}`) : "";
        const contenido = !habilitada ? '<span class="bj-bloqueada">bloqueada</span>'
          : x ? `${extremo(x.a)} <b>↔</b> ${extremo(x.b)}${x.posicion_estimada ? ' <span class="bj-est" title="Posición puesta por la regla">≈</span>' : ""}`
            : '<span class="bj-libre">libre</span>';
        const mover = x && !s && st.puedeEditar && typeof x.id === "number";
        filas.push(`<li class="bj-pos${habilitada ? "" : " bloqueada"}${x ? " ocupada" : ""}" data-bandeja="${b.numero}" data-posicion="${p}"`
          + `${habilitada && !s ? ' data-destino="1"' : ""}${mover ? ` draggable="true" data-conexion="${x.id}"` : ""}>`
          + `<span class="bj-num">${p}</span>${etiqueta ? `<span class="bj-etq">${etiqueta}</span>` : ""}<span class="bj-par">${contenido}</span></li>`);
      }
      const usadas = [...porPosicion.keys()].filter((k) => k.startsWith(`${b.numero}:`)).length;
      return `<section class="bj-bandeja${s ? " con-splitter" : ""}"><header><b>Bandeja ${b.numero}</b>`
        + `<span class="nota">${s ? `${esc(s.nombre)} · 1x${s.salidas} · ${b.capacidad} posiciones` : `${usadas} de ${b.capacidad} empalmes`}</span>${opciones}</header>`
        + `<ol>${filas.join("")}</ol></section>`;
    });
    const pendientes = sinLugar.length ? `<section class="bj-sin-lugar"><header><b>Empalmes sin bandeja (${sinLugar.length})</b>`
      + `<span class="nota">arrástrelos a una posición libre${E().cambios() ? " (después de Aplicar)" : ""}</span></header><ul>`
      + sinLugar.map((x) => `<li class="bj-pos ocupada"${typeof x.id === "number" && st.puedeEditar ? ` draggable="true" data-conexion="${x.id}"` : ""}>`
        + `<span class="bj-par">${extremo(x.a)} <b>↔</b> ${extremo(x.b)}</span></li>`).join("") + "</ul></section>" : "";
    caja.innerHTML = `<div class="bj-barra"><span>Mufa de <b>${m.capacidad}</b> · ${m.bandejas} bandejas · ${m.empalmes_por_bandeja} empalmes por bandeja`
      + `${m.modelo_estimado ? ` <span class="mu-insignia estimado">estimado</span> <span class="nota">${esc(m.motivo || "")}</span>` : ""}</span>`
      + (st.puedeEditar ? '<button type="button" class="btn btn-chico" data-bj="modelo">Cambiar modelo</button>' : "")
      + `<span class="nota">≈ posición estimada · arrastre un empalme para moverlo</span></div>`
      + `<div class="bj-tarjetas">${tarjetas.join("")}</div>${pendientes}`;
  }

  function alternar() {
    visible = !visible;
    if (visible && window.RedMufas) window.RedMufas.ocultar();
    pintar();
  }

  function ocultar() {
    if (!visible) return;
    visible = false;
    pintar();
  }

  /** Server operations need the cable view saved first (they reload the mufa). */
  async function operar(metodo, args) {
    if (E().cambios()) { mensaje("Aplique (guarde) los cambios de la vista de cables antes de cambiar las bandejas", "error"); return; }
    const r = await Redes.llamar(metodo, args);
    if (!r.ok) { mensaje(r.error, "error"); return; }
    E().recargar(r);
  }

  function abrirModelo() {
    const r = E()._st.datos, m = r.modelo;
    $("mu-mo-capacidad").value = String(m ? m.capacidad : 48);
    $("mu-mo-formato").value = m ? m.formato : "desconocido";
    $("mu-mo-motivo").textContent = m && m.modelo_estimado ? `Hoy es estimado: ${m.motivo || ""}` : "";
    Redes.estadoEn($("mu-mo-estado"), "");
    $("modal-mu-modelo").hidden = false;
  }

  async function guardarModelo(ev) {
    ev.preventDefault();
    $("modal-mu-modelo").hidden = true;
    await operar("guardar_modelo_mufa", { mufa_id: E()._st.mufaId, capacidad: Number($("mu-mo-capacidad").value), formato: $("mu-mo-formato").value });
  }

  // ------------------------------------------------------------------ eventos
  $("mu-vista").addEventListener("click", alternar);
  $("mu-mo-form").addEventListener("submit", guardarModelo);
  const caja = $("mu-bandejas");
  caja.addEventListener("click", (e) => { if (e.target.closest('[data-bj="modelo"]')) abrirModelo(); });
  caja.addEventListener("change", (e) => {
    const sel = e.target.closest(".bj-splitter");
    if (sel) operar("bandeja_splitter", { mufa_id: E()._st.mufaId, numero: Number(sel.dataset.bandeja), splitter_id: sel.value ? Number(sel.value) : null });
  });
  caja.addEventListener("dragstart", (e) => {
    const li = e.target.closest("[data-conexion]");
    if (!li) return;
    e.dataTransfer.setData("text/plain", li.dataset.conexion);
    e.dataTransfer.effectAllowed = "move";
  });
  caja.addEventListener("dragover", (e) => { if (e.target.closest("[data-destino]")) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } });
  caja.addEventListener("drop", (e) => {
    const destino = e.target.closest("[data-destino]");
    const id = Number(e.dataTransfer.getData("text/plain"));
    if (!destino || !id) return;
    e.preventDefault();
    operar("mover_empalme", { conexion_id: id, bandeja: Number(destino.dataset.bandeja), posicion: Number(destino.dataset.posicion) });
  });

  window.BandejasMufa = { pintar, alternar, ocultar, operar, get visible() { return visible; } };
})();
