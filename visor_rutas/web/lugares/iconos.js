/* Íconos propios de "Mis lugares" (visor v2, fase 3), sin depender de Google: pushpins de colores, letras A–Z, números 1–10 y
 * figuras. Mismo catálogo y mismas formas que visor_rutas/redes/lugares_iconos.py (que los dibuja en PNG para el KMZ).
 *
 * Un ícono es {tipo: "pushpin" | "letra" | "numero" | "figura" | "ninguno" | "imagen" | "texto", id, color, escala, opacidad}; «imagen» lleva además
 * `datos` (la imagen del usuario, reducida a 96 px, como data URL) y «texto» hasta tres caracteres (un emoji, "OLT") en `id`. Las gotas (pushpin, letra,
 * número) señalan con la punta; las figuras, con el centro.
 *   Iconos.svg(icono, alto)            SVG para listas y botones
 *   Iconos.leaflet(icono)              L.divIcon para el mapa
 *   Iconos.seleccionar(icono, [alAceptar])   ventana de selección (como el selector de Google Earth); devuelve una promesa
 */
(function () {
  "use strict";

  const FIGURAS = [["circulo", "Círculo"], ["cuadrado", "Cuadrado"], ["rombo", "Rombo"], ["estrella", "Estrella"], ["triangulo", "Triángulo"],
                   ["cruz", "Cruz"], ["hexagono", "Hexágono"], ["anillo", "Anillo"]];
  const LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
  const NUMEROS = Array.from({ length: 10 }, (_, i) => String(i + 1));
  const COLORES = [["#f7d117", "Amarillo"], ["#2f6bff", "Azul"], ["#2ca02c", "Verde"], ["#1ec8e8", "Celeste"], ["#ff6fb5", "Rosa"],
                   ["#8e44ad", "Morado"], ["#e53935", "Rojo"], ["#ffffff", "Blanco"], ["#fb8c00", "Naranja"], ["#222222", "Negro"]];
  const DEFECTO = { tipo: "pushpin", id: "pushpin", color: "#f7d117", escala: 1.1, opacidad: 1 };
  const MAX_IMAGEN = 80000, LADO_IMAGEN = 96;                    // characters of the data URL / px of the longest side (the server checks the same)
  const RE_IMAGEN = /^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$/;
  const TEXTO_PROHIBIDO = /[<>&"'\\\u0000-\u001f]/;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const esGota = (ic) => ["pushpin", "letra", "numero"].includes(ic.tipo);

  function limpiar(ic) {
    if (!ic || typeof ic !== "object") return { ...DEFECTO };
    let tipo = ["pushpin", "letra", "numero", "figura", "ninguno", "imagen", "texto"].includes(ic.tipo) ? ic.tipo : "pushpin";
    let id = String(ic.id || ""), datos;
    if (tipo === "imagen") {
      if (typeof ic.datos === "string" && ic.datos.length <= MAX_IMAGEN && RE_IMAGEN.test(ic.datos)) { datos = ic.datos; id = "imagen"; } else tipo = "pushpin";
    } else if (tipo === "texto") {
      id = Array.from(id.trim()).slice(0, 3).join("");
      if (!id || TEXTO_PROHIBIDO.test(id)) tipo = "pushpin";
    }
    if (tipo === "pushpin") id = "pushpin";
    if (tipo === "letra" && !LETRAS.includes(id)) id = "A";
    if (tipo === "numero" && !NUMEROS.includes(id)) id = "1";
    if (tipo === "figura" && !FIGURAS.some(([f]) => f === id)) id = "circulo";
    const color = /^#[0-9a-fA-F]{6}$/.test(ic.color || "") ? ic.color : DEFECTO.color;
    const num = (v, mn, mx, d) => { const n = Number(v); return Number.isFinite(n) ? Math.min(mx, Math.max(mn, n)) : d; };
    const salida = { tipo, id, color, escala: Math.round(num(ic.escala, 0.3, 4, 1.1) * 100) / 100, opacidad: Math.round(num(ic.opacidad, 0, 1, 1) * 100) / 100 };
    if (datos) salida.datos = datos;
    return salida;
  }

  function oscuro(hexa) {
    const n = parseInt(hexa.slice(1), 16);
    const c = (v) => Math.round(v * 0.45).toString(16).padStart(2, "0");
    return `#${c((n >> 16) & 255)}${c((n >> 8) & 255)}${c(n & 255)}`;
  }
  const claro = (hexa) => { const n = parseInt(hexa.slice(1), 16); return ((n >> 16) & 255) + ((n >> 8) & 255) + (n & 255) >= 560; };

  const ESTRELLA = Array.from({ length: 10 }, (_, i) => {
    const r = i % 2 ? 7.5 : 17.5, a = -Math.PI / 2 + i * Math.PI / 5;
    return `${(20 + r * Math.cos(a)).toFixed(2)},${(20 + r * Math.sin(a)).toFixed(2)}`;
  }).join(" ");
  const HEXAGONO = Array.from({ length: 6 }, (_, i) => `${(20 + 16 * Math.cos(Math.PI / 3 * i)).toFixed(2)},${(20 + 16 * Math.sin(Math.PI / 3 * i)).toFixed(2)}`).join(" ");

  /** SVG of the icon, `alto` px high (a drop is 30:42, a figure square). */
  function svg(icono, alto = 36) {
    const ic = limpiar(icono);
    if (ic.tipo === "ninguno") return `<svg width="${alto}" height="${alto}" viewBox="0 0 40 40" aria-label="Sin ícono"><circle cx="20" cy="20" r="14" fill="none" stroke="#9aa0ab" stroke-width="2"/><path d="M10 30 30 10" stroke="#9aa0ab" stroke-width="2"/></svg>`;
    const borde = oscuro(ic.color), op = ic.opacidad < 1 ? ` opacity="${ic.opacidad}"` : "";
    if (ic.tipo === "imagen") {
      return `<svg width="${alto}" height="${alto}" viewBox="0 0 40 40"${op}><image href="${esc(ic.datos)}" x="0" y="0" width="40" height="40" preserveAspectRatio="xMidYMid meet"/></svg>`;
    }
    if (ic.tipo === "texto") {
      const n = Array.from(ic.id).length;
      return `<svg width="${alto}" height="${alto}" viewBox="0 0 40 40"${op}><circle cx="20" cy="20" r="17" fill="${ic.color}" stroke="${borde}" stroke-width="2.4"/>` +
        `<text x="20" y="${n > 1 ? 25 : 27}" text-anchor="middle" font-family="'Segoe UI Emoji','Apple Color Emoji',Arial,sans-serif" font-weight="700" font-size="${n === 1 ? 20 : n === 2 ? 15 : 11}" ` +
        `fill="${claro(ic.color) ? "#1e1e1e" : "#fff"}">${esc(ic.id)}</text></svg>`;
    }
    if (esGota(ic)) {
      const interior = ic.tipo === "pushpin"
        ? `<circle cx="15" cy="15" r="5.5" fill="#fff" stroke="${borde}" stroke-width="1.5"/>`
        : `<text x="15" y="${ic.id.length > 1 ? 19.5 : 20}" text-anchor="middle" font-family="Arial, sans-serif" font-weight="700" font-size="${ic.id.length > 1 ? 11 : 15}" fill="${claro(ic.color) ? "#1e1e1e" : "#fff"}">${esc(ic.id)}</text>`;
      return `<svg width="${Math.round(alto * 30 / 42)}" height="${alto}" viewBox="0 0 30 42"${op}><path d="M15 41C15 41 2 24.5 2 15a13 13 0 0 1 26 0c0 9.5-13 26-13 26z" fill="${ic.color}" stroke="${borde}" stroke-width="2"/>${interior}</svg>`;
    }
    const f = ic.id, p = `fill="${ic.color}" stroke="${borde}" stroke-width="2.4" stroke-linejoin="round"`;
    const forma = {
      circulo: `<circle cx="20" cy="20" r="16" ${p}/>`, anillo: `<circle cx="20" cy="20" r="13.5" fill="none" stroke="${ic.color}" stroke-width="6"/>`,
      cuadrado: `<rect x="6" y="6" width="28" height="28" ${p}/>`, rombo: `<polygon points="20,3 37,20 20,37 3,20" ${p}/>`,
      triangulo: `<polygon points="20,4 37,34 3,34" ${p}/>`, hexagono: `<polygon points="${HEXAGONO}" ${p}/>`, estrella: `<polygon points="${ESTRELLA}" ${p}/>`,
      cruz: `<polygon points="14,3 26,3 26,14 37,14 37,26 26,26 26,37 14,37 14,26 3,26 3,14 14,14" ${p}/>`,
    }[f];
    return `<svg width="${alto}" height="${alto}" viewBox="0 0 40 40"${op}>${forma}</svg>`;
  }

  /** Marker icon of the map: 1.0 of scale = a drop 36 px high or a figure 24 px wide. */
  function leaflet(icono) {
    const ic = limpiar(icono);
    if (ic.tipo === "ninguno") return L.divIcon({ className: "icono", html: "", iconSize: [14, 14], iconAnchor: [7, 7] });
    if (esGota(ic)) {
      const alto = Math.round(36 * ic.escala), ancho = Math.round(alto * 30 / 42);
      return L.divIcon({ className: "icono", html: svg(ic, alto), iconSize: [ancho, alto], iconAnchor: [ancho / 2, alto - 1],
                         popupAnchor: [0, -alto + 4], tooltipAnchor: [ancho / 2 + 2, -alto / 2] });
    }
    const lado = Math.round(24 * ic.escala);
    return L.divIcon({ className: "icono", html: svg(ic, lado), iconSize: [lado, lado], iconAnchor: [lado / 2, lado / 2], popupAnchor: [0, -lado / 2],
                       tooltipAnchor: [lado / 2 + 2, 0] });
  }

  // ------------------------------------------------------------------ ventana de selección
  let modal = null;

  function crearModal() {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="ml-iconos" class="modal ml-modal" hidden role="dialog" aria-modal="true" aria-labelledby="ml-iconos-titulo">
        <div class="modal-caja ml-iconos-caja">
          <header class="modal-cabecera"><h2 id="ml-iconos-titulo">Ícono</h2><button type="button" class="btn-icono" data-ml-ic="cerrar" aria-label="Cerrar">✕</button></header>
          <div class="ml-iconos-cuerpo">
            <div class="ml-iconos-ajustes">
              <span class="ml-iconos-vista" id="ml-iconos-vista"></span>
              <label>Color <input type="color" id="ml-ic-color"></label>
              <label>Escala <input type="number" id="ml-ic-escala" min="0.3" max="4" step="0.1"></label>
              <label>Opacidad <input type="number" id="ml-ic-opacidad" min="0" max="100" step="5"> %</label>
            </div>
            <div class="ml-iconos-extra">
              <label class="btn btn-chico ml-ic-imagen" title="Una imagen tuya (PNG, JPG, WebP o GIF): se reduce a 96 px">Imagen propia…
                <input type="file" id="ml-ic-archivo" accept="image/png,image/jpeg,image/webp,image/gif" hidden></label>
              <label class="ml-ic-texto">Texto o emoji <input type="text" id="ml-ic-texto" maxlength="3" size="4" placeholder="OLT, 5G, 🔌"></label>
              <button type="button" class="btn btn-chico" data-ml-ic="usar_texto">Usar texto</button>
              <span class="nota ml-ic-error" id="ml-ic-error"></span>
            </div>
            <div class="ml-iconos-rejilla" id="ml-iconos-rejilla"></div>
          </div>
          <footer class="ml-iconos-pie">
            <button type="button" class="btn" data-ml-ic="ninguno">No hay ícono</button><span class="ml-espacio"></span>
            <button type="button" class="btn" data-ml-ic="cancelar">Cancelar</button><button type="button" class="btn btn-primario" data-ml-ic="aceptar">Aceptar</button>
          </footer>
        </div>
      </div>`);
    modal = document.getElementById("ml-iconos");
  }

  /** Reads an image file and shrinks it to LADO_IMAGEN px (the longest side) as a PNG data URL; rejects what is not an image or stays too big. */
  function imagenReducida(archivo) {
    return new Promise((resolver, rechazar) => {
      if (!archivo || !/^image\/(png|jpeg|webp|gif)$/.test(archivo.type)) { rechazar(new Error("Elija una imagen PNG, JPG, WebP o GIF")); return; }
      const url = URL.createObjectURL(archivo), img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        for (const lado of [LADO_IMAGEN, 64, 40]) {
          const k = Math.min(1, lado / Math.max(img.naturalWidth, img.naturalHeight, 1));
          const lienzo = document.createElement("canvas");
          lienzo.width = Math.max(1, Math.round(img.naturalWidth * k)); lienzo.height = Math.max(1, Math.round(img.naturalHeight * k));
          lienzo.getContext("2d").drawImage(img, 0, 0, lienzo.width, lienzo.height);
          const datos = lienzo.toDataURL("image/png");
          if (datos.length <= MAX_IMAGEN) { resolver(datos); return; }
        }
        rechazar(new Error("La imagen es demasiado compleja: use una más simple"));
      };
      img.onerror = () => { URL.revokeObjectURL(url); rechazar(new Error("No se pudo leer la imagen")); };
      img.src = url;
    });
  }

  function seleccionar(actual) {
    if (!modal) crearModal();
    let ic = limpiar(actual);
    return new Promise((resolver) => {
      const rejilla = document.getElementById("ml-iconos-rejilla");
      const celda = (icono, titulo, activo) => `<button type="button" class="ml-ic-celda${activo ? " activa" : ""}" data-ic='${esc(JSON.stringify(icono))}' title="${esc(titulo)}">${svg({ ...icono, escala: 1, opacidad: 1 }, 30)}</button>`;
      const pintar = () => {
        const mismo = (a) => ic.tipo === a.tipo && ic.id === a.id && (a.tipo !== "pushpin" || ic.color === a.color);
        const base = { color: ic.color };
        rejilla.innerHTML =
          `<h3>Pushpins</h3><div class="ml-ic-fila">${COLORES.map(([c, n]) => celda({ tipo: "pushpin", id: "pushpin", color: c }, `Pushpin ${n.toLowerCase()}`, mismo({ tipo: "pushpin", id: "pushpin", color: c }))).join("")}</div>` +
          `<h3>Letras</h3><div class="ml-ic-fila">${LETRAS.map((l) => celda({ ...base, tipo: "letra", id: l }, `Letra ${l}`, mismo({ tipo: "letra", id: l }))).join("")}</div>` +
          `<h3>Números</h3><div class="ml-ic-fila">${NUMEROS.map((n) => celda({ ...base, tipo: "numero", id: n }, `Número ${n}`, mismo({ tipo: "numero", id: n }))).join("")}</div>` +
          `<h3>Figuras</h3><div class="ml-ic-fila">${FIGURAS.map(([f, n]) => celda({ ...base, tipo: "figura", id: f }, n, mismo({ tipo: "figura", id: f }))).join("")}</div>`;
        document.getElementById("ml-iconos-vista").innerHTML = svg(ic, 48);
        document.getElementById("ml-ic-color").value = ic.color;
        document.getElementById("ml-ic-escala").value = ic.escala;
        document.getElementById("ml-ic-opacidad").value = Math.round(ic.opacidad * 100);
        document.getElementById("ml-ic-texto").value = ic.tipo === "texto" ? ic.id : "";
        document.getElementById("ml-ic-error").textContent = "";
      };
      const cerrar = (valor) => { modal.hidden = true; modal.onclick = modal.oninput = modal.onkeydown = modal.onchange = null; resolver(valor); };
      modal.onclick = (e) => {
        const celdaEl = e.target.closest("[data-ic]");
        if (celdaEl) {
          const elegido = JSON.parse(celdaEl.dataset.ic);
          ic = limpiar({ ...ic, ...elegido, color: elegido.tipo === "pushpin" ? elegido.color : ic.color });
          pintar();
          return;
        }
        const accion = (e.target.closest("[data-ml-ic]") || {}).dataset;
        if (!accion) { if (e.target === modal) cerrar(null); return; }
        if (accion.mlIc === "usar_texto") {
          const texto = document.getElementById("ml-ic-texto").value;
          const nuevo = limpiar({ ...ic, tipo: "texto", id: texto, escala: ic.tipo === "texto" ? ic.escala : 1.3 });
          if (nuevo.tipo !== "texto") { document.getElementById("ml-ic-error").textContent = "Escriba de 1 a 3 caracteres (sin < > & \" ')"; return; }
          ic = nuevo; pintar();
        } else if (accion.mlIc === "aceptar") cerrar(ic);
        else if (accion.mlIc === "ninguno") cerrar({ tipo: "ninguno", id: "ninguno", color: ic.color, escala: ic.escala, opacidad: ic.opacidad });
        else cerrar(null);
      };
      modal.oninput = (e) => {
        if (e.target.id === "ml-ic-color") ic = limpiar({ ...ic, color: e.target.value });
        else if (e.target.id === "ml-ic-escala") ic = limpiar({ ...ic, escala: e.target.value });
        else if (e.target.id === "ml-ic-opacidad") ic = limpiar({ ...ic, opacidad: Number(e.target.value) / 100 });
        else return;
        if (e.target.id === "ml-ic-color") { pintar(); } else { document.getElementById("ml-iconos-vista").innerHTML = svg(ic, 48); }
      };
      modal.onkeydown = (e) => {
        if (e.key === "Escape") { e.stopPropagation(); cerrar(null); }
        else if (e.key === "Enter" && e.target.id === "ml-ic-texto") { e.preventDefault(); modal.querySelector("[data-ml-ic=usar_texto]").click(); }
      };
      modal.onchange = async (e) => {
        if (e.target.id !== "ml-ic-archivo") return;
        const archivo = e.target.files && e.target.files[0];
        e.target.value = "";
        try {
          const datos = await imagenReducida(archivo);
          ic = limpiar({ ...ic, tipo: "imagen", id: "imagen", datos, escala: ic.tipo === "imagen" ? ic.escala : 1.6 });
          pintar();
        } catch (err) { document.getElementById("ml-ic-error").textContent = err.message; }
      };
      pintar();
      modal.hidden = false;
      modal.querySelector("[data-ml-ic=aceptar]").focus();
    });
  }

  window.Iconos = { svg, leaflet, seleccionar, limpiar, esGota, DEFECTO, COLORES, FIGURAS, LETRAS, NUMEROS };
})();
