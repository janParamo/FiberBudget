/* App de campo: cliente de la API (/visor/campo/*), clave del técnico y fotos comprimidas. */
(function () {
  "use strict";
  const CLAVE = "campo.clave";
  const FOTO_LADO = 1600, FOTO_CALIDAD = 0.7;

  class ErrorApi extends Error {
    constructor(mensaje, estado, errores) { super(mensaje); this.estado = estado; this.errores = errores || null; }
    get sinConexion() { return this.estado === 0; }
  }

  function leer(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardar(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  const clave = () => leer(CLAVE) || "";
  const ponerClave = (v) => guardar(CLAVE, v ? String(v).trim() : null);

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const b = new Uint8Array(16); (window.crypto || {}).getRandomValues ? crypto.getRandomValues(b) : b.forEach((_, i) => { b[i] = Math.random() * 256; });
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  /* JSON (o el cuerpo crudo de una foto) con la clave. Lanza ErrorApi: estado 0 = sin conexión. */
  async function pedir(metodo, ruta, cuerpo, opciones) {
    const o = opciones || {};
    const cabeceras = { "X-Visor-Key": clave(), "ngrok-skip-browser-warning": "1" };
    let body;
    if (o.crudo) { body = cuerpo; cabeceras["Content-Type"] = o.tipo || "application/octet-stream"; }
    else if (cuerpo !== undefined) { body = JSON.stringify(cuerpo); cabeceras["Content-Type"] = "application/json"; }
    let r;
    try { r = await fetch(ruta, { method: metodo, headers: cabeceras, body }); }
    catch (e) { throw new ErrorApi("Sin conexión con el servidor", 0); }
    if (o.blob && r.ok) return r.blob();
    let datos = null;
    try { datos = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) {
      const texto = (datos && (datos.error || (typeof datos.detail === "string" && datos.detail))) ||
        (r.status === 401 ? "La clave no es válida" : r.status === 404 ? "El servicio de campo no está disponible" : `Error ${r.status}`);
      throw new ErrorApi(texto, r.status, datos && datos.errores);
    }
    return datos;
  }

  const api = {
    config: () => pedir("GET", "/visor/campo/config"),
    abrirJornada: (nombre) => pedir("POST", "/visor/campo/jornadas", { accion: "abrir", nombre }),
    cerrarJornada: (id) => pedir("POST", "/visor/campo/jornadas", { accion: "cerrar", id }),
    enviarPuntos: (puntos) => pedir("POST", "/visor/campo/puntos", { puntos }),
    trazos: (jornada) => pedir("GET", `/visor/campo/trazos?jornada=${encodeURIComponent(jornada)}&limite=100`),
    borrarTrazo: (id) => pedir("DELETE", `/visor/campo/trazos/${id}`),
    red: (o, s, e, n) => pedir("GET", `/visor/campo/red?bbox=${o},${s},${e},${n}`),
    ubicacion: (u) => pedir("POST", "/visor/campo/ubicacion", { lat: u.lat, lon: u.lon, precision_m: u.precision_m, capturado_en: new Date(u.hora || Date.now()).toISOString() }),
    puntos: (jornada) => pedir("GET", `/visor/campo/puntos?jornada=${encodeURIComponent(jornada)}&limite=500`),
    editarPunto: (id, version, cambios) => pedir("PATCH", `/visor/campo/puntos/${id}`, { version, cambios }),
    borrarPunto: (id) => pedir("DELETE", `/visor/campo/puntos/${id}`),
    subirFoto: (puntoId, blob, uid) =>
      pedir("POST", `/visor/campo/fotos?punto_id=${puntoId}&uuid_cliente=${encodeURIComponent(uid)}`, blob, { crudo: true, tipo: blob.type || "image/jpeg" }),
  };

  /* Foto del teléfono -> JPEG de máximo ~1600 px y calidad 0.7 (una foto de cámara pesa varios MB). */
  async function comprimir(archivo) {
    let img;
    try { img = await createImageBitmap(archivo, { imageOrientation: "from-image" }); }
    catch (e) {
      img = await new Promise((ok, mal) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => mal(new Error("No se pudo leer la foto")); i.src = URL.createObjectURL(archivo); });
    }
    const ancho = img.width || img.naturalWidth, alto = img.height || img.naturalHeight;
    const escala = Math.min(1, FOTO_LADO / Math.max(ancho, alto));
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.max(1, Math.round(ancho * escala)); lienzo.height = Math.max(1, Math.round(alto * escala));
    lienzo.getContext("2d").drawImage(img, 0, 0, lienzo.width, lienzo.height);
    if (img.close) img.close();
    return new Promise((ok, mal) => lienzo.toBlob((b) => (b ? ok(b) : mal(new Error("No se pudo comprimir la foto"))), "image/jpeg", FOTO_CALIDAD));
  }

  window.CampoApi = { api, ErrorApi, clave, ponerClave, uuid, comprimir };
})();
