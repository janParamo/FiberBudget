/* Menú lateral del visor: vistas con íconos, modo contraído (solo íconos) y opción activa.
 *
 * El estado contraído/expandido se guarda en %APPDATA%\VisorRutas\preferencias.json
 * (api.guardar_preferencias): pywebview corre en modo privado y no conserva el localStorage.
 * Las opciones de fases todavía no hechas (data-fase) quedan deshabilitadas con "Próximamente";
 * las del módulo de redes (data-redes) se deshabilitan si su base no está disponible.
 *
 * visor.js llama a Menu.iniciar({api, mostrarVista}) y mostrarVista llama a Menu.marcarActivo.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const ANCHO = { expandido: 210, contraido: 56 };
  let ctx = null;
  let contraido = false;

  const items = () => [...document.querySelectorAll("#menu-lateral .menu-item")];

  function aplicarAncho() {
    $("menu-lateral").classList.toggle("contraido", contraido);
    document.documentElement.style.setProperty("--ancho-menu", `${contraido ? ANCHO.contraido : ANCHO.expandido}px`);
    const boton = $("menu-plegar");
    boton.title = boton.ariaLabel = contraido ? "Expandir el menú" : "Contraer el menú";
    // the map changed width: let Leaflet know (after the CSS applies)
    requestAnimationFrame(() => { if (window.visor && window.visor.mapa) window.visor.mapa.invalidateSize({ pan: false }); });
  }

  function deshabilitar(boton, motivo) {
    boton.setAttribute("aria-disabled", "true");
    boton.dataset.motivo = motivo;
    boton.title = `${boton.querySelector(".menu-texto").textContent}: ${motivo}`;
  }

  function habilitar(boton) {
    boton.removeAttribute("aria-disabled");
    delete boton.dataset.motivo;
  }

  function marcarActivo(vista) {
    items().forEach((b) => b.classList.toggle("activo", b.dataset.vista === vista));
  }

  /** Module options available or not (the network database answered, or the reason it did not). */
  function moduloRedes(disponible, motivo) {
    items().filter((b) => b.dataset.redes).forEach((b) => (disponible ? habilitar(b) : deshabilitar(b, motivo)));
  }

  function usuario(texto, titulo) {
    const caja = $("menu-usuario");
    caja.querySelector(".menu-pie-texto").innerHTML = texto;
    caja.title = titulo || caja.textContent.trim();
  }

  async function iniciar(contexto) {
    ctx = contexto;
    items().forEach((b) => {
      if (b.dataset.fase) {
        deshabilitar(b, "Próximamente");
        b.insertAdjacentHTML("beforeend", `<span class="menu-proximo">Pronto</span>`);
      }
      b.addEventListener("click", () => {
        if (b.getAttribute("aria-disabled") === "true") {
          if (ctx.mensaje) ctx.mensaje(`${b.querySelector(".menu-texto").textContent}: ${b.dataset.motivo || "no disponible"}`);
          return;
        }
        ctx.mostrarVista(b.dataset.vista);
      });
    });
    $("menu-plegar").addEventListener("click", () => {
      contraido = !contraido;
      aplicarAncho();
      if (ctx.api && ctx.api.guardar_preferencias) ctx.api.guardar_preferencias({ menu_contraido: contraido }).catch(() => {});
    });
    try {
      const r = await ctx.api.preferencias();
      contraido = !!(r && r.preferencias && r.preferencias.menu_contraido);
    } catch (e) { /* defaults */ }
    aplicarAncho();
  }

  window.Menu = { iniciar, marcarActivo, moduloRedes, usuario, get contraido() { return contraido; } };
})();
