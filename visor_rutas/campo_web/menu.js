/* App de campo: el menú lateral, la pantalla de Ajustes y la de Acerca de / ayuda. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const $ = (id) => document.getElementById(id);
  const M = () => window.CampoMapa, Ayuda = () => window.CampoAyuda;
  const CAPA_GUARDADA = "campo.capa";

  /* ---------------------------------------------------------------- menú */
  function pintarMenu() {
    const e = C.estado, n = e.cola.length, malos = e.cola.filter((x) => x.estado === "error").length;
    const r = $("m-respaldo");
    r.classList.toggle("bien", n === 0);
    r.querySelector(".m-ic").innerHTML = C.iconos.svg(n === 0 ? "ok" : "advertencia");
    $("m-respaldo-texto").textContent = n ? `${n} sin enviar${malos ? ` (${malos} con error)` : ""}: toque para enviar` : "Todo enviado al servidor";
    $("m-jornada-nombre").textContent = e.jornada ? e.jornada.nombre : "Sin jornada abierta";
    $("m-jornada-fecha").textContent = e.jornada && e.jornada.abierta_en ? C.fecha(e.jornada.abierta_en) : "Toque para cerrarla";
    $("m-tipo-mapa-texto").textContent = M().CAPAS[M().capaActual()].titulo;
    $("m-todas-texto").textContent = `${C.lista.items(false).length} en total`;
    $("m-instalar").hidden = !Ayuda().estado().puedeInstalar;
    $("m-version").textContent = "Fiber Budget · app de campo";
  }

  function abrirMenu() { pintarMenu(); C.panel.abrir("p-menu"); }

  async function tipoMapa() {
    const lista = Object.entries(M().CAPAS).map(([k, c]) => ({ valor: k, texto: c.titulo, detalle: c.detalle, icono: "mapa" }));
    const r = await C.dialogo.opciones("Tipo de mapa", lista, M().capaActual());
    if (!r) return;
    M().ponerCapa(r); C.guardar(CAPA_GUARDADA, r); pintarMenu();
  }

  async function menuJornada() {
    if (!C.estado.jornada) { C.aviso("No hay jornada abierta"); return; }
    const r = await C.dialogo.opciones(C.estado.jornada.nombre, [{ valor: "cerrar", texto: "Cerrar la jornada", detalle: "Lo enviado queda para revisión", icono: "carpeta" }]);
    if (r === "cerrar") { C.panel.cerrar(); await C.app.cerrarJornada(); }
  }

  async function jornadaNueva() {
    const nombre = await C.dialogo.texto("Jornada nueva", "", "Nombre (opcional)", 80);
    if (nombre === null) return;
    C.panel.cerrar();
    await C.app.nuevaJornada(nombre);
  }

  /* ---------------------------------------------------------------- ajustes */
  function valorTexto(d) {
    const v = C.ajustes.obtener(d.id);
    if (d.tipo === "casilla") return "";
    if (d.tipo === "numero") return `${v}${d.unidad ? " " + d.unidad : ""}`;
    const o = d.opciones.find(([k]) => String(k) === String(v));
    return o ? o[1] : String(v);
  }

  function pintarAjustes() {
    let grupo = null, html = "";
    C.ajustes.DEFINICION.forEach((d) => {
      if (d.grupo !== grupo) { grupo = d.grupo; html += `<h3 class="aj-grupo">${C.esc(grupo)}</h3>`; }
      const v = C.ajustes.obtener(d.id);
      html += `<button type="button" class="aj-fila" data-aj="${d.id}"><span><b>${C.esc(d.titulo)}</b><small>${C.esc(d.detalle || valorTexto(d))}</small></span>${d.tipo === "casilla" ? `<input type="checkbox" tabindex="-1" ${v ? "checked" : ""} aria-label="${C.esc(d.titulo)}">` : ""}</button>`;
    });
    $("aj-cuerpo").innerHTML = html;
  }

  async function cambiarAjuste(id) {
    const d = C.ajustes.DEFINICION.find((x) => x.id === id), actual = C.ajustes.obtener(id);
    if (!d) return;
    if (d.tipo === "casilla") C.ajustes.poner(id, !actual);
    else if (d.tipo === "numero") { const r = await C.dialogo.numero(d.titulo, actual, d.minimo, d.maximo, d.unidad); if (r === null) return; C.ajustes.poner(id, r); }
    else {
      const r = await C.dialogo.opciones(d.titulo, d.opciones.map(([valor, texto]) => ({ valor, texto })), actual);
      if (r === null) return;
      C.ajustes.poner(id, r);
    }
    if (id === "red" && window.CampoRed.visible !== C.ajustes.obtener("red")) alternarRed();
    if (id === "zoom") M().zoom(C.ajustes.obtener("zoom"));
    pintarAjustes();
    C.lista.pintar();
  }

  function alternarRed() {
    const v = window.CampoRed.alternar();
    $("btn-red").setAttribute("aria-pressed", String(v));
    return v;
  }

  /* ---------------------------------------------------------------- acerca de */
  function abrirAcerca() { $("ac-cuerpo").innerHTML = Ayuda().html(); C.panel.abrir("p-acerca"); }

  function conectar() {
    $("b-menu").onclick = abrirMenu;
    $("fondo-panel").onclick = () => { if (C.panel.actual() === "p-menu") C.panel.cerrar(); };
    C.panel.cuandoCambie((id) => { $("fondo-panel").hidden = id !== "p-menu"; });
    $("m-respaldo").onclick = () => { C.panel.cerrar(); C.app.enviarCola(true); };
    $("m-jornada").onclick = menuJornada;
    $("m-tipo-mapa").onclick = tipoMapa;
    $("m-todas").onclick = () => { C.estado.filtro = { tipos: null, estados: null, jornadas: null }; C.lista.pintar(); C.lista.abrir(); };
    $("m-nueva").onclick = jornadaNueva;
    $("m-ajustes").onclick = () => { pintarAjustes(); C.panel.abrir("p-ajustes"); };
    $("aj-cuerpo").onclick = (e) => { const f = e.target.closest("[data-aj]"); if (f) cambiarAjuste(f.dataset.aj); };
    $("aj-atras").onclick = abrirMenu;
    $("m-acerca").onclick = abrirAcerca;
    $("ac-atras").onclick = abrirMenu;
    $("m-instalar").onclick = async () => { if (await Ayuda().instalar()) C.aviso("App instalada", "ok"); C.panel.cerrar(); };
    $("m-salir").onclick = () => C.app.salir();
    $("btn-red").onclick = () => { const v = alternarRed(); C.ajustes.poner("red", v); C.aviso(v ? "Red existente visible" : "Red existente oculta"); };
    $("ios-como").onclick = abrirAcerca;
  }

  C.menu = { conectar, abrirMenu, abrirAcerca, pintarMenu, capaGuardada: () => C.leer(CAPA_GUARDADA) };
})();
