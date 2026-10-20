/* Buscar dentro del diagrama de Visio (visor): un campo sobre el diagrama que se está viendo, para encontrar un texto (el nombre de una mufa, un
 * cliente, un splitter, «PUERTO 3»…) o una coordenada, y un interruptor para mostrar u ocultar el círculo que marca lo encontrado.
 *
 * El servidor busca en los textos del diagrama (visor_rutas/fusion.py: buscar_en_diagrama): palabras (sin acentos ni mayúsculas; MF, MC y MUFA son lo
 * mismo) o una coordenada en cualquier formato del buscador, que halla los textos que escriben una coordenada a menos de 25 m. Cada resultado trae dónde
 * está dibujado: el diagrama se acerca ahí y lo rodea el círculo. Enter / Mayús+Enter o las flechas pasan al siguiente / anterior; la lista muestra todos.
 *
 *   BusquedaDiagrama.montar(contenedor, { visor: () => v, api: () => api, circulo: { leer, poner }, mensaje })  -> { buscar(texto), limpiar() }
 */
(function () {
  "use strict";

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ESPERA_MS = 380;

  function montar(contenedor, ctx) {
    contenedor.innerHTML = `<div class="dg-bus">
      <input type="search" class="dg-bus-texto" placeholder="Buscar en el diagrama: texto o coordenada" aria-label="Buscar en el diagrama" autocomplete="off" spellcheck="false">
      <button type="button" class="btn btn-chico dg-bus-ant" title="Anterior (Mayús+Enter)" aria-label="Resultado anterior" disabled>▲</button>
      <button type="button" class="btn btn-chico dg-bus-sig" title="Siguiente (Enter)" aria-label="Resultado siguiente" disabled>▼</button>
      <span class="nota dg-bus-info" role="status"></span>
      <label class="dg-bus-circulo" title="Mostrar u ocultar el círculo que marca la mufa o el texto encontrado"><input type="checkbox" class="dg-bus-check"> Círculo</label>
      <ul class="dg-bus-lista" hidden></ul></div>`;
    const q = (s) => contenedor.querySelector(s);
    const campo = q(".dg-bus-texto"), info = q(".dg-bus-info"), lista = q(".dg-bus-lista"), ant = q(".dg-bus-ant"), sig = q(".dg-bus-sig"), check = q(".dg-bus-check");
    const e = { resultados: [], indice: -1, modo: "texto", pedido: 0, espera: null };

    check.checked = ctx.circulo.leer();
    check.addEventListener("change", () => ctx.circulo.poner(check.checked));

    const refrescarBotones = () => { ant.disabled = sig.disabled = e.resultados.length < 2; };

    function pintarLista() {
      lista.innerHTML = e.resultados.map((r, i) => `<li class="dg-bus-fila${i === e.indice ? " activa" : ""}" data-i="${i}">${esc(r.texto)}` +
        `${r.distancia_m !== undefined ? ` <span class="nota">· a ${r.distancia_m.toLocaleString("en-US", { maximumFractionDigits: 1 })} m</span>` : ""}</li>`).join("");
      lista.hidden = !e.resultados.length || document.activeElement !== campo;
      const activa = lista.querySelector(".activa");
      if (activa && activa.scrollIntoView) activa.scrollIntoView({ block: "nearest" });
    }

    function ir(i) {
      if (!e.resultados.length) return;
      e.indice = (i + e.resultados.length) % e.resultados.length;
      ctx.visor().irA(e.resultados[e.indice]);
      info.textContent = `${e.indice + 1} de ${e.resultados.length}${e.total > e.resultados.length ? "+" : ""}`;
      pintarLista();
    }

    async function buscar(texto) {
      const v = ctx.visor();
      const pedido = ++e.pedido;
      texto = String(texto || "").trim();
      e.resultados = []; e.indice = -1;
      v.quitarResalte();
      if (texto.length < 2) { info.textContent = ""; refrescarBotones(); pintarLista(); return; }
      if (!v.archivo || !v.cargado) { info.textContent = "Abra un diagrama"; refrescarBotones(); pintarLista(); return; }
      info.textContent = "Buscando…";
      let r;
      try { r = await ctx.api().buscar_en_diagrama(v.archivo.md5, texto); } catch (err) { r = { ok: false, error: String(err) }; }
      if (pedido !== e.pedido) return;                            // the text changed or another diagram was opened meanwhile
      if (!r.ok) { info.textContent = r.error; refrescarBotones(); pintarLista(); return; }
      e.resultados = r.resultados; e.total = r.total; e.modo = r.modo;
      refrescarBotones();
      if (!e.resultados.length) {
        info.textContent = r.modo === "coordenada" ? "Esa coordenada no está escrita en este diagrama" : "No está en este diagrama";
        pintarLista();
        return;
      }
      ir(0);
    }

    campo.addEventListener("input", () => { clearTimeout(e.espera); e.espera = setTimeout(() => buscar(campo.value), ESPERA_MS); });
    campo.addEventListener("focus", pintarLista);
    campo.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (e.pedido && e.espera) { clearTimeout(e.espera); e.espera = null; }
        if (e.indice < 0) buscar(campo.value); else ir(e.indice + (ev.shiftKey ? -1 : 1));
      } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if (e.resultados.length) ir(e.indice + (ev.key === "ArrowDown" ? 1 : -1));
      } else if (ev.key === "Escape" && (campo.value || e.resultados.length)) {
        ev.preventDefault(); ev.stopPropagation();
        limpiar();
      }
    });
    ant.addEventListener("click", () => ir(e.indice - 1));
    sig.addEventListener("click", () => ir(e.indice + 1));
    lista.addEventListener("mousedown", (ev) => {                 // mousedown, not click: the input loses focus (and the list hides) first
      const fila = ev.target.closest("[data-i]");
      if (!fila) return;
      ev.preventDefault();
      ir(Number(fila.dataset.i));
    });
    campo.addEventListener("blur", () => { lista.hidden = true; });

    function limpiar() {
      clearTimeout(e.espera);
      e.pedido++; e.resultados = []; e.indice = -1;
      campo.value = ""; info.textContent = "";
      refrescarBotones(); pintarLista();
      ctx.visor().quitarResalte();
    }

    return {
      buscar, limpiar,
      /** A diagram was (re)loaded: what was found belongs to the old one; if something is typed, look for it in the new one. */
      alCargar() { e.pedido++; e.resultados = []; e.indice = -1; info.textContent = ""; refrescarBotones(); pintarLista(); if (campo.value.trim().length >= 2) buscar(campo.value); },
      sincronizarCirculo() { check.checked = ctx.circulo.leer(); },
      get campo() { return campo; },
    };
  }

  window.BusquedaDiagrama = { montar };
})();
