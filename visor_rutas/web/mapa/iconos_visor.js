/* Íconos de lo que dibuja el propio visor (postes y mufas de la ruta, nodos Visio, mufa buscada, punto de conexión y cliente), cambiables por todos.
 *
 * En «Lugares → Capas del visor → Íconos del visor…» se abre esta ventana: cada ícono con su muestra, «Cambiar…» (el selector de íconos de Mis lugares:
 * pushpins, letras, números, figuras, texto o emoji, imagen propia, con color, escala y opacidad) y «Restablecer». El cambio lo ven todos los usuarios
 * (se guarda en la base con los estilos del KMZ: alcance «capa», clave «capa|<id>|») y solo lo hacen administradores y editores.
 * Al abrir el visor se leen y se aplican (window.visor.iconosVisor.aplicar), y el mapa, la mufa buscada y la leyenda se redibujan al instante.
 *
 *   IconosVisor.iniciar({aviso})   IconosVisor.abrir()   IconosVisor.cargar()
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const llamar = (m, a) => window.Redes.llamar(m, a);
  const clave = (id) => `capa|${id}|`;
  const puedeEditar = () => !!(window.Redes && window.Redes.estado && window.Redes.estado.puede && window.Redes.estado.puede.editar);
  const s = { aviso: () => {}, guardados: {} };

  /** Reads the icons changed for everyone and puts them on the map. */
  async function cargar() {
    const r = await llamar("estilos_kmz", {});
    if (!r.ok) return;
    s.guardados = {};
    r.estilos.filter((e) => e.alcance === "capa" && e.estilo && e.estilo.icono).forEach((e) => { s.guardados[e.clave.split("|")[1]] = e.estilo.icono; });
    window.visor.iconosVisor.aplicar(s.guardados);
    if ($("iv-modal") && !$("iv-modal").hidden) pintar();
  }

  function pintar() {
    const v = window.visor.iconosVisor, editor = puedeEditar();
    $("iv-filas").innerHTML = v.catalogo.map((c) => `<div class="iv-fila" data-id="${esc(c.id)}">
        <span class="iv-muestra">${v.html(c.id)}</span><span class="iv-nombre">${esc(c.texto)}${s.guardados[c.id] ? ' <span class="nota">· cambiado</span>' : ""}</span>
        <button type="button" class="btn btn-chico" data-iv="cambiar" ${editor ? "" : "disabled"}>Cambiar…</button>
        <button type="button" class="btn btn-chico" data-iv="restablecer" ${editor && s.guardados[c.id] ? "" : "disabled"}>Restablecer</button></div>`).join("");
    $("iv-nota").textContent = editor ? "El cambio lo ven todos los usuarios." : "Solo un administrador o un editor puede cambiar los íconos.";
  }

  async function cambiar(id) {
    const c = window.visor.iconosVisor.catalogo.find((x) => x.id === id);
    const icono = await window.Iconos.seleccionar(s.guardados[id] || c.defecto);
    if (!icono) return;
    const r = await llamar("guardar_estilo_kmz", { clave: clave(id), alcance: "capa", carpeta: "visor", nombre: c.texto, icono });
    if (!r.ok) { s.aviso(r.error, "error"); return; }
    s.guardados[id] = r.estilo.estilo.icono;
    window.visor.iconosVisor.aplicar(s.guardados);
    pintar();
    s.aviso(`Ícono de «${c.texto}» cambiado para todos`, "ok");
  }

  async function restablecer(id) {
    const c = window.visor.iconosVisor.catalogo.find((x) => x.id === id);
    const r = await llamar("quitar_estilo_kmz", { clave: clave(id) });
    if (!r.ok && !/ya no tiene/.test(r.error || "")) { s.aviso(r.error, "error"); return; }
    delete s.guardados[id];
    window.visor.iconosVisor.aplicar(s.guardados);
    pintar();
    s.aviso(`«${c.texto}» vuelve a su ícono original`, "ok");
  }

  function crear() {
    if ($("iv-modal")) return;
    document.body.insertAdjacentHTML("beforeend", `<div id="iv-modal" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="iv-titulo">
      <div class="modal-caja config-caja"><header class="modal-cabecera"><h2 id="iv-titulo">Íconos del visor</h2><button type="button" class="btn-icono" data-iv="cerrar" aria-label="Cerrar">✕</button></header>
      <div class="config-cuerpo"><p class="ml-d-nota" id="iv-nota"></p><div id="iv-filas" class="iv-filas"></div>
        <div class="config-acciones"><button type="button" class="btn" data-iv="cerrar">Cerrar</button></div></div></div></div>`);
    $("iv-modal").addEventListener("click", (e) => {
      const b = e.target.closest("[data-iv]");
      if (!b) { if (e.target === $("iv-modal")) $("iv-modal").hidden = true; return; }
      const id = (b.closest("[data-id]") || {}).dataset && b.closest("[data-id]").dataset.id;
      if (b.dataset.iv === "cerrar") $("iv-modal").hidden = true;
      else if (b.dataset.iv === "cambiar") cambiar(id);
      else if (b.dataset.iv === "restablecer") restablecer(id);
    });
    $("iv-modal").addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("ml-iconos") || e.key === "Escape" && $("ml-iconos").hidden) $("iv-modal").hidden = true; });
  }

  function abrir() {
    if (!window.Redes || !window.Redes.disponible) { s.aviso("El módulo de redes no está disponible", "error"); return; }
    crear();
    pintar();
    $("iv-modal").hidden = false;
  }

  function iniciar(ctx) {
    s.aviso = ctx.aviso || s.aviso;
    window.Redes.cuandoListo(async () => {
      if (!window.Redes.disponible) return;
      await cargar();
      if (window.Lugares) window.Lugares.refrescar();                // the «Íconos del visor…» row shows once the module answered
    });
  }

  window.IconosVisor = { iniciar, abrir, cargar, get guardados() { return { ...s.guardados }; } };
})();
