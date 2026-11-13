/* Tema del visor: oscuro (por defecto) o claro. Se elige en Configuración > Apariencia y se guarda en las preferencias del usuario
 * (api.guardar_preferencias: %APPDATA%\VisorRutas\preferencias.json), así que vale también para las ventanas aparte.
 *
 * El oscuro es la clase `tema-oscuro` en <body> (tema.css cambia las variables de color y tema_oscuro.css los colores escritos a mano); el claro es no tenerla.
 *
 *   Tema.iniciar(api)      Tema.elegir("oscuro" | "claro")      Tema.actual
 */
(function () {
  "use strict";

  let api = null, actual = "oscuro";

  function aplicar(tema) {
    actual = tema === "claro" ? "claro" : "oscuro";
    document.body.classList.toggle("tema-oscuro", actual === "oscuro");
    document.querySelectorAll(".config-tema-opcion").forEach((b) => b.setAttribute("aria-checked", b.dataset.tema === actual ? "true" : "false"));
  }

  async function elegir(tema) {
    aplicar(tema);
    if (api && api.guardar_preferencias) { try { await api.guardar_preferencias({ tema: actual }); } catch (e) { /* it stays for this session */ } }
  }

  async function iniciar(apiPython) {
    api = apiPython;
    document.querySelectorAll(".config-tema-opcion").forEach((b) => b.addEventListener("click", () => elegir(b.dataset.tema)));
    try {
      const r = await api.preferencias();
      aplicar(r && r.preferencias ? r.preferencias.tema : undefined);
    } catch (e) { aplicar("oscuro"); }
  }

  window.Tema = { iniciar, elegir, get actual() { return actual; } };
})();
