/* Buscador superior del mapa (visor v2, fase 2): mufas, lugares y coordenadas.
 *
 * Si lo escrito es una coordenada (decimal, grados-minutos-segundos o grados-minutos decimales; ver coordenadas.js)
 * ofrece "Ir a la coordenada …": vuela y pone un pincho con su etiqueta (pin.js). NO calcula ruta ni presupuesto: la
 * barra inferior queda como está. Si parece una coordenada con latitud y longitud al revés, o fuera de Nicaragua,
 * lo dice (y ofrece la forma correcta). Si no es una coordenada, pregunta a las fuentes registradas, que pueden ser
 * varias y se muestran juntas, cada una con su título:
 *   Buscador.registrarFuente({id, titulo, buscar(texto) -> Promise<[{titulo, detalle, sinCoord, ...}]>, elegir(item)})
 * Las registran quien tiene los datos: visor.js (mufas y nodos Visio), lugares.js (el KMZ), redes/comun.js (la red base)
 * y más adelante Mis lugares.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const fuentes = [];
  const st = { temporizador: null, pedido: 0, entradas: [], marcado: -1 };
  let ctx = null;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function registrarFuente(fuente) {
    const i = fuentes.findIndex((f) => f.id === fuente.id);
    if (i >= 0) fuentes[i] = fuente; else fuentes.push(fuente);
  }

  const lista = () => $("buscar-resultados");
  function ocultar() { lista().hidden = true; st.marcado = -1; }
  function mostrar(html) { lista().innerHTML = html; lista().hidden = false; }

  // ------------------------------------------------------------------ coordenadas
  const COORDENADA = { id: "coordenada", elegir: (it) => ctx.irACoordenada(it.lat, it.lon) };

  function sugerenciasDeCoordenada(c) {
    st.entradas = [];
    const entrada = (lat, lon, titulo, detalle) => {
      st.entradas.push({ fuente: COORDENADA, item: { lat, lon } });
      return `<li data-i="${st.entradas.length - 1}" role="option" class="coordenada"><b>${esc(titulo)}</b><span class="det">${esc(detalle)}</span></li>`;
    };
    const aviso = (texto) => `<li class="vacio error">${esc(texto)}</li>`;
    if (c.estado === "ok") {
      return entrada(c.lat, c.lon, `Ir a la coordenada ${Coordenadas.formatoDecimal(c.lat, c.lon)}`, Coordenadas.formatoGMS(c.lat, c.lon));
    }
    if (c.estado === "invertida") {
      const [la, lo] = c.sugerencia;
      return aviso("La latitud y la longitud parecen invertidas (escriba primero la latitud).") +
        entrada(la, lo, `Ir a ${Coordenadas.formatoDecimal(la, lo)}`, "con latitud y longitud en el otro orden");
    }
    return aviso(c.mensaje);
  }

  // ------------------------------------------------------------------ fuentes
  async function buscar(texto) {
    const pedido = ++st.pedido;
    const t = texto.trim();
    if (t.length < 2) { $("buscar-spinner").hidden = true; ocultar(); return; }
    const c = Coordenadas.interpretar(t);
    if (c.estado !== "no_coordenada") {                    // a coordinate: no other source is asked
      $("buscar-spinner").hidden = true;
      st.marcado = -1;
      mostrar(sugerenciasDeCoordenada(c));
      return;
    }
    $("buscar-spinner").hidden = false;
    const respuestas = await Promise.all(fuentes.map((f) => Promise.resolve().then(() => f.buscar(t))
      .then((items) => ({ f, items: items || [] }), (e) => ({ f, items: [], error: (e && e.message) || String(e) }))));
    if (pedido !== st.pedido) return;                      // an older search answering late
    $("buscar-spinner").hidden = true;
    st.entradas = [];
    st.marcado = -1;
    const trozos = [];
    respuestas.forEach(({ f, items, error }) => {
      if (!items.length && !error) return;
      if (fuentes.length > 1) trozos.push(`<li class="grupo">${esc(f.titulo)}</li>`);
      if (error) { trozos.push(`<li class="vacio">${esc(error)}</li>`); return; }
      items.forEach((item) => {
        st.entradas.push({ fuente: f, item });
        trozos.push(`<li data-i="${st.entradas.length - 1}" role="option"><b>${esc(item.titulo)}</b><span class="det">${esc(item.detalle || "")}` +
          `${item.sinCoord ? ' · <span class="sin-coord">sin coordenadas</span>' : ""}</span></li>`);
      });
    });
    mostrar(trozos.length ? trozos.join("") : `<li class="vacio">Nada con ese texto (mufas, lugares o coordenada)</li>`);
  }

  function marcarResultado(i) {
    const li = [...lista().querySelectorAll("li[data-i]")];
    if (!li.length) return;
    st.marcado = (i + li.length) % li.length;
    li.forEach((x, k) => x.classList.toggle("marcado", k === st.marcado));
    li[st.marcado].scrollIntoView({ block: "nearest" });
  }

  function elegir(indice) {
    const e = st.entradas[indice];
    if (!e) return;
    ocultar();
    $("buscar-mufa").blur();
    e.fuente.elegir(e.item);
  }

  /** Enter: a valid coordinate goes straight there; anything else takes the marked (or first) suggestion. */
  function entrar() {
    const c = Coordenadas.interpretar($("buscar-mufa").value);
    if (c.estado === "ok") { ocultar(); $("buscar-mufa").blur(); ctx.irACoordenada(c.lat, c.lon); return; }
    if (c.estado !== "no_coordenada") { buscar($("buscar-mufa").value); return; }
    if (lista().hidden) return;
    const li = lista().querySelectorAll("li[data-i]");
    const k = st.marcado >= 0 ? st.marcado : 0;
    if (li[k]) elegir(Number(li[k].dataset.i));
  }

  function iniciar(contexto) {
    ctx = contexto;
    const campo = $("buscar-mufa");
    campo.addEventListener("input", () => {
      clearTimeout(st.temporizador);
      st.temporizador = setTimeout(() => buscar(campo.value), 200);
    });
    campo.addEventListener("focus", () => { if (lista().innerHTML && campo.value.trim().length >= 2) lista().hidden = false; });
    campo.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); marcarResultado(st.marcado + (e.key === "ArrowDown" ? 1 : -1)); }
      else if (e.key === "Enter") { e.preventDefault(); entrar(); }
      else if (e.key === "Escape") { ocultar(); campo.blur(); }
    });
    lista().addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); elegir(Number(li.dataset.i)); }
    });
    document.addEventListener("click", (e) => { if (!e.target.closest("#buscador")) ocultar(); }, true);
    L.DomEvent.disableClickPropagation($("buscador"));
    L.DomEvent.disableScrollPropagation($("buscador"));
  }

  window.Buscador = { iniciar, registrarFuente, ocultar, buscar, get fuentes() { return fuentes.map((f) => f.id); } };
})();
