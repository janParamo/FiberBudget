/* Trazado de hilo (fase 5 del módulo de redes): sigue un hilo de punta a punta.
 *
 * Trazado.abrir({hilo_id} | {cable_id, numero}) llama a Redes.llamar("trazar_hilo")
 * (visor_rutas/redes/trazado.py) y muestra el panel #panel-trazado: a qué cliente(s) llega,
 * los dos sentidos (hacia el origen y hacia el destino del cable) y cada camino paso a paso
 * (tramos de cable con su hilo, fusiones, splitters, conectores) hasta su final (cliente, nodo,
 * o "sin continuidad"). Clic en una mufa del recorrido: abre su editor de mufa. "Ver en el mapa"
 * resalta los cables y elementos del recorrido en el mapa del proyecto.
 *
 * Mientras el panel está abierto, Trazado.actual tiene el resultado y el editor de mufa y el de
 * mapa lo resaltan (escuchan el evento "trazado" del document; detail null = se cerró).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => Redes.esc(v);
  const TIA_CSS = { azul: "#1f5fd1", naranja: "#f28c28", verde: "#2e9d4a", "café": "#8b5a2b", gris: "#8c8c8c", blanco: "#ffffff",
                    rojo: "#e53935", negro: "#111111", amarillo: "#f7d117", violeta: "#7e3fbf", rosa: "#f06ba8", aqua: "#2ec4d6" };
  const ESTADO = { activo: "activo", oscura: "fibra oscura", baja: "cliente de baja", reservado: "reservado", danado: "dañado" };
  const FIN = { cliente: "ok", nodo: "nodo", sin_conexion: "corte", splitter_libre: "corte", ciclo: "corte", limite: "corte", otro: "nodo" };
  const m = (v) => `${Math.round(v || 0).toLocaleString("es-NI")} m`;

  const Trazado = {
    actual: null,
    pedido: null,

    async abrir(pedido) {
      this.pedido = pedido;
      const panel = $("panel-trazado");
      panel.hidden = false;
      $("tz-cuerpo").innerHTML = `<p class="vacio"><span class="spinner"></span> Trazando el hilo…</p>`;
      $("tz-titulo").textContent = "Trazado de hilo";
      const r = await Redes.llamar("trazar_hilo", pedido);
      if (!r.ok) {
        $("tz-cuerpo").innerHTML = `<p class="vacio error">${esc(r.error)}</p>`;
        this.fijar(null);
        return null;
      }
      this.fijar(r);
      this.pintar(r);
      return r;
    },

    /** Re-runs the last trace (after saving a mufa the route may have changed). */
    async refrescar() {
      if (this.actual && this.pedido && !$("panel-trazado").hidden) await this.abrir({ hilo_id: this.actual.inicio.hilo.id });
    },

    cerrar() {
      $("panel-trazado").hidden = true;
      this.fijar(null);
    },

    fijar(r) {
      this.actual = r;
      document.dispatchEvent(new CustomEvent("trazado", { detail: r }));
    },

    pintar(t) {
      const i = t.inicio;
      $("tz-titulo").innerHTML = `Trazado · ${esc(i.cable.nombre)} hilo ${i.hilo.numero} ${punto(i.hilo.color)}`;
      const clientes = t.resumen.clientes;
      const resumen = `<div class="tz-resumen">
        <div><b>${esc(i.cable.nombre)}</b> · ${esc(i.cable.tipo)} ${i.cable.hilos} hilos · ${esc(i.origen.nombre)} → ${esc(i.destino.nombre)}</div>
        <div>Hilo ${i.hilo.numero} (${esc(i.hilo.color)}) · estado <b>${esc(ESTADO[i.hilo.estado] || i.hilo.estado)}</b></div>
        <div class="tz-llega">${clientes.length
          ? `${clientes.length === 1 ? "Llega al cliente" : `Llega a ${clientes.length} clientes`}:${clientes.map((c) => `<b>${esc(c.nombre)}</b>${c.codigo ? ` (${esc(c.codigo)})` : ""}`).join(", ")}`
          : "No llega a ningún cliente"}</div>
        ${t.resumen.sin_continuidad ? `<div class="tz-alerta">${t.resumen.sin_continuidad} camino(s) sin continuidad</div>` : ""}
        ${t.resumen.recortado ? `<div class="tz-alerta">Demasiados caminos: se muestran los primeros</div>` : ""}
      </div>`;
      const sentidos = t.sentidos.map((s) => `<section class="tz-sentido"><h3>${esc(s.nombre)} <span class="nota">(${esc(s.elemento.nombre)})</span></h3>
        ${s.caminos.map((c, n) => camino(c, n, s.caminos.length, i)).join("")}</section>`).join("");
      $("tz-cuerpo").innerHTML = resumen + sentidos;
      $("tz-mapa").disabled = !(window.EditorRed);
    },
  };

  const punto = (color) => `<span class="tz-punto" style="background:${TIA_CSS[color] || "#999"}"></span>`;

  function elemento(e) {
    const navegable = ["mufa", "nodo", "odf"].includes(e.tipo);
    return navegable ? `<a href="#" data-tz-mufa="${e.id}" data-tz-nombre="${esc(e.nombre)}" title="Abrir el editor de ${esc(e.nombre)}">${esc(e.nombre)}</a>`
      : `<b>${esc(e.nombre)}</b>`;
  }

  function camino(c, n, total, inicio) {
    const pasos = c.pasos.map((p) => {
      if (p.tipo === "tramo") {
        const estado = p.hilo.estado !== "activo" ? ` <span class="tz-estado">${esc(ESTADO[p.hilo.estado] || p.hilo.estado)}</span>` : "";
        return `<li class="tz-tramo">${punto(p.hilo.color)} <b>${esc(p.cable.nombre)}</b> hilo ${p.hilo.numero}${estado}
          <span class="nota">${elemento(p.desde)} → ${elemento(p.hasta)} · ${m(p.longitud_m)}</span></li>`;
      }
      const icono = { fusion: "⨯", splitter: "◁", conector: "▭" }[p.tipo] || "•";
      return `<li class="tz-${p.tipo}"><span class="tz-icono">${icono}</span> ${esc(p.texto).replace(esc(p.en.nombre), elemento(p.en))}</li>`;
    }).join("");
    const fin = c.fin;
    const clase = FIN[fin.motivo] || "nodo";
    return `<div class="tz-camino">
      ${total > 1 ? `<div class="tz-camino-titulo">Camino ${n + 1} de ${total} · ${m(c.distancia_m)} desde el final del cable</div>`
                  : `<div class="tz-camino-titulo">${m(c.distancia_m)} desde el final del cable ${esc(inicio.cable.nombre)}</div>`}
      <ol class="tz-pasos">${pasos}<li class="tz-fin ${clase}">${clase === "ok" ? "✔" : clase === "corte" ? "⚠" : "■"} ${esc(fin.texto)}</li></ol>
      ${c.avisos.length ? `<div class="tz-alerta">${c.avisos.map(esc).join("<br>")}</div>` : ""}
    </div>`;
  }

  async function verEnMapa() {
    const t = Trazado.actual;
    if (!t || !window.EditorRed) return;
    if (window.EditorMufa && !$("modal-mufa").hidden) {
      await window.EditorMufa.cerrar(false);
      if (!$("modal-mufa").hidden) return;                 // the user stayed (unsaved changes)
    }
    await window.EditorRed.mostrarTrazado(t);
  }

  function conectar() {
    $("tz-cerrar").addEventListener("click", () => Trazado.cerrar());
    $("tz-mapa").addEventListener("click", verEnMapa);
    $("tz-cuerpo").addEventListener("click", (e) => {
      const a = e.target.closest("[data-tz-mufa]");
      if (!a || !window.EditorMufa) return;
      e.preventDefault();
      const destino = { id: Number(a.dataset.tzMufa), nombre: a.dataset.tzNombre, tipo: "mufa" };
      if (!$("modal-mufa").hidden) window.EditorMufa._navegar(destino);
      else window.EditorMufa.abrir(destino.id, destino.nombre);
    });
  }

  document.addEventListener("DOMContentLoaded", conectar);
  if (document.readyState !== "loading") conectar();

  window.Trazado = Trazado;
})();
