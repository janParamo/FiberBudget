/* App de campo: instalar la app en el teléfono (Android y iPhone) y avisos sobre lo que cada sistema permite. */
(function () {
  "use strict";
  let pedidoInstalar = null;
  const oyentes = new Set();

  /* "iphone" | "android" | "otro" from the user agent (iPad with desktop mode says «Macintosh» but has touch). */
  function plataforma(ua, tactil) {
    ua = ua || navigator.userAgent || "";
    if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && (tactil == null ? navigator.maxTouchPoints > 1 : tactil))) return "iphone";
    if (/Android/i.test(ua)) return "android";
    return "otro";
  }

  /* Opened from the home screen icon (installed) and not as a tab of the browser. */
  function instalada() {
    return (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
  }

  /* On iPhone only Safari can install a web app (iOS 16.4+ also from other browsers' Share menu, but the steps are the same on Safari). */
  function safari(ua) {
    ua = ua || navigator.userAgent || "";
    return /Safari/i.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome/i.test(ua);
  }

  const PASOS = {
    iphone: ["Abra esta página en <b>Safari</b> (si está en otro navegador, copie el enlace y ábralo en Safari).",
             "Toque el botón <b>Compartir</b> (el cuadro con una flecha hacia arriba, abajo en la pantalla).",
             "Baje en la lista y toque <b>Agregar a pantalla de inicio</b>.",
             "Toque <b>Agregar</b>. Desde ahora abra la app con su ícono «Campo», no desde Safari."],
    android: ["Abra esta página en <b>Chrome</b>.",
              "Toque <b>Instalar app</b> (en el menú de la app o en el aviso de Chrome). Si no aparece, toque los tres puntos de Chrome y elija <b>Instalar aplicación</b> o <b>Agregar a pantalla principal</b>.",
              "Confirme. Desde ahora abra la app con su ícono «Campo»."],
    otro: ["En el navegador del teléfono abra el menú y busque <b>Instalar aplicación</b> o <b>Agregar a pantalla de inicio</b>."],
  };

  /* GPS, the camera flow and installing the app only work on HTTPS (or on this same computer): http:// on a phone is a dead end. */
  function contextoSeguro(protocolo, host) {
    protocolo = protocolo || location.protocol; host = host || location.hostname;
    return protocolo === "https:" || host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  }

  function estado() {
    const p = plataforma();
    return { plataforma: p, seguro: contextoSeguro(), instalada: instalada(), puedeInstalar: !!pedidoInstalar, safari: p === "iphone" && safari(),
             // iOS may erase the data of a site that is not used for weeks: only an installed app is safe for a queue of points
             avisarSinInstalar: p === "iphone" && !instalada() };
  }

  async function instalar() {
    if (!pedidoInstalar) return false;
    pedidoInstalar.prompt();
    const r = await pedidoInstalar.userChoice;
    pedidoInstalar = null;
    oyentes.forEach((f) => f());
    return r && r.outcome === "accepted";
  }

  function html(forzado) {
    const e = forzado || estado();                                           // `forzado`: tests and previews of another situation
    const pasos = PASOS[e.plataforma].map((t) => `<li>${t}</li>`).join("");
    const extra = e.instalada ? `<p class="ok"><b>La app ya está instalada.</b></p>` : "";
    const aviso = e.plataforma === "iphone" && !e.instalada
      ? `<p class="error">En iPhone, si usa la app desde Safari sin instalarla, el teléfono puede borrar los puntos que aún no se enviaron. Instálela.</p>` : "";
    const http = e.seguro ? "" : `<p class="error">Esta página está abierta por una dirección no segura (http). El GPS y la instalación no funcionan así: pida al administrador la dirección que empieza con https://.</p>`;
    const uso = `<h3>Uso diario</h3><ol><li>Abra la app con su ícono «Campo» y deje el GPS encendido.</li><li>Toque <b>Poste</b>, <b>Mufa</b>, <b>Reserva</b>… cuando esté junto al punto; espere el círculo verde (±10 m o menos) y toque <b>Guardar y enviar</b>.</li>
      <li>Para un cable toque <b>Trazar cable</b> y los postes en orden (o grabe el recorrido caminando).</li><li>Sin señal no pasa nada: queda guardado y sale solo al volver la señal (en iPhone, al abrir la app).</li><li>Al terminar el día, ☰ → <b>Cerrar la jornada</b>.</li></ol>`;
    return `${http}${extra}${aviso}<ol>${pasos}</ol>${uso}
      <p class="nota">La ubicación solo se toma con la app abierta y en pantalla (una app web no puede rastrear en segundo plano). Sin señal, los puntos se guardan en el teléfono
      y se envían solos al volver la señal; en iPhone eso ocurre al abrir la app.</p>`;
  }

  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); pedidoInstalar = e; oyentes.forEach((f) => f()); });
  window.addEventListener("appinstalled", () => { pedidoInstalar = null; oyentes.forEach((f) => f()); });

  window.CampoAyuda = { plataforma, instalada, safari, contextoSeguro, estado, instalar, html, cuandoCambie: (f) => { oyentes.add(f); return () => oyentes.delete(f); } };
})();
