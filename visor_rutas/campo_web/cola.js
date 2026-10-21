/* App de campo: la cola de envío (IndexedDB). Sirve en la página y en el service worker (Background Sync de Android).
 *
 * Todo punto se guarda primero aquí, con su uuid y sus fotos ya comprimidas, y de aquí sale hacia el servidor cuando hay conexión. Enviar es
 * idempotente (el servidor reconoce el uuid del punto y de cada foto), así que reintentar tras un corte nunca duplica. Un punto que el servidor
 * rechaza por sus datos (422) queda en la cola con su error para que la persona lo corrija o lo quite; los cortes de red, un 5xx o un 429 solo
 * detienen el envío hasta el próximo intento (abrir la app, volver a primer plano, recuperar señal, el botón, o Background Sync si existe). */
(function (raiz) {
  "use strict";
  const BASE = "campo-cola", VERSION = 2;

  function abrir() {
    return new Promise((ok, mal) => {
      const r = raiz.indexedDB.open(BASE, VERSION);
      r.onupgradeneeded = () => {
        const db = r.result;
        if (!db.objectStoreNames.contains("pendientes")) db.createObjectStore("pendientes", { keyPath: "uuid" });
        if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "k" });
        if (!db.objectStoreNames.contains("red")) db.createObjectStore("red", { keyPath: "k" });        // reference network by zone (so it is there with no signal)
      };
      r.onsuccess = () => ok(r.result);
      r.onerror = () => mal(r.error);
    });
  }

  async function usar(almacen, modo, accion) {
    const db = await abrir();
    try {
      return await new Promise((ok, mal) => {
        const t = db.transaction(almacen, modo);
        const a = t.objectStore(almacen);
        let resultado;
        Promise.resolve(accion(a)).then((r) => { resultado = r; }, mal);
        t.oncomplete = () => ok(resultado);
        t.onerror = () => mal(t.error);
        t.onabort = () => mal(t.error);
      });
    } finally { db.close(); }
  }
  const pedirIdb = (req) => new Promise((ok, mal) => { req.onsuccess = () => ok(req.result); req.onerror = () => mal(req.error); });

  const agregar = (entrada) => usar("pendientes", "readwrite", (a) => pedirIdb(a.put(entrada)));
  const actualizar = agregar;
  const quitar = (uuid) => usar("pendientes", "readwrite", (a) => pedirIdb(a.delete(uuid)));
  const obtener = (uuid) => usar("pendientes", "readonly", (a) => pedirIdb(a.get(uuid)));
  const listar = () => usar("pendientes", "readonly", (a) => pedirIdb(a.getAll())).then((l) => l.sort((x, y) => x.creado - y.creado));
  const ponerMeta = (k, v) => usar("meta", "readwrite", (a) => pedirIdb(a.put({ k, v })));
  const meta = (k) => usar("meta", "readonly", (a) => pedirIdb(a.get(k))).then((r) => (r ? r.v : null));
  const redGuardar = (k, datos) => usar("red", "readwrite", (a) => pedirIdb(a.put({ k, datos, hora: Date.now() })));
  const redLeer = (k) => usar("red", "readonly", (a) => pedirIdb(a.get(k)));

  /* Una petición al servidor: { estado, datos } (estado 0 = sin conexión). */
  async function pedir(clave, metodo, ruta, cuerpo, tipo) {
    const cabeceras = { "X-Visor-Key": clave, "ngrok-skip-browser-warning": "1" };
    let body;
    if (tipo) { body = cuerpo; cabeceras["Content-Type"] = tipo; }
    else { body = JSON.stringify(cuerpo); cabeceras["Content-Type"] = "application/json"; }
    let r;
    try { r = await raiz.fetch(ruta, { method: metodo, headers: cabeceras, body }); }
    catch (e) { return { estado: 0, datos: null }; }
    let datos = null;
    try { datos = await r.json(); } catch (e) { /* not JSON */ }
    return { estado: r.status, datos };
  }

  const DETIENE = (estado) => estado === 0 || estado === 401 || estado === 403 || estado === 429 || estado >= 500;

  /* Sends one entry. Returns "listo" (all of it is in the server: the entry is removed), "error" (the server refused its data), or
   * { detener: "red" | "clave" | "limite" | "servidor" } (try again later). */
  /* A cable traced in the field: one request (no photos). Same rules as a point: a refused one waits for a person, a cut keeps it. */
  async function enviarTrazo(e, clave) {
    let r = await pedir(clave, "POST", "/visor/campo/trazos", { trazos: [e.trazo] });
    if (DETIENE(r.estado)) return { detener: razon(r.estado) };
    let res = r.datos && r.datos.resultados && r.datos.resultados[0];
    if (res && !res.ok && res.errores && res.errores.jornada_id && e.trazo.jornada_id) {
      delete e.trazo.jornada_id;
      r = await pedir(clave, "POST", "/visor/campo/trazos", { trazos: [e.trazo] });
      if (DETIENE(r.estado)) return { detener: razon(r.estado) };
      res = r.datos && r.datos.resultados && r.datos.resultados[0];
    }
    if (!res || !res.ok) {
      e.estado = "error"; e.error = (res && res.error) || (r.datos && r.datos.error) || `Error ${r.estado}`; e.intentos = (e.intentos || 0) + 1;
      await actualizar(e);
      return "error";
    }
    await quitar(e.uuid);
    return "listo";
  }

  async function enviarUna(e, clave, resumen) {
    if (e.trazo) return enviarTrazo(e, clave);
    if (!e.puntoId) {
      let r = await pedir(clave, "POST", "/visor/campo/puntos", { puntos: [e.punto] });
      if (DETIENE(r.estado)) return { detener: razon(r.estado) };
      let res = r.datos && r.datos.resultados && r.datos.resultados[0];
      if (res && !res.ok && res.errores && res.errores.jornada_id && e.punto.jornada_id) {         // the jornada no longer exists: the server picks the open one
        delete e.punto.jornada_id;
        r = await pedir(clave, "POST", "/visor/campo/puntos", { puntos: [e.punto] });
        if (DETIENE(r.estado)) return { detener: razon(r.estado) };
        res = r.datos && r.datos.resultados && r.datos.resultados[0];
      }
      if (!res || !res.ok) {
        e.estado = "error"; e.error = (res && res.error) || (r.datos && r.datos.error) || `Error ${r.estado}`; e.intentos = (e.intentos || 0) + 1;
        await actualizar(e);
        return "error";
      }
      e.puntoId = res.punto.id; e.duplicado = res.duplicado || null; e.estado = "cola"; e.error = null;
      await actualizar(e);
    }
    for (const f of e.fotos || []) {
      if (f.enviada) continue;
      const r = await pedir(clave, "POST", `/visor/campo/fotos?punto_id=${e.puntoId}&uuid_cliente=${encodeURIComponent(f.uuid)}`, f.blob, f.blob.type || "image/jpeg");
      if (DETIENE(r.estado)) return { detener: razon(r.estado) };
      if (r.estado === 404) { resumen.perdidas += 1; f.enviada = true; f.descartada = true; }                 // the point was deleted meanwhile
      else if (r.estado >= 400) { resumen.fotos_rechazadas += 1; f.enviada = true; f.descartada = true; f.error = (r.datos && r.datos.error) || `Error ${r.estado}`; }
      else f.enviada = true;
      await actualizar(e);
    }
    await quitar(e.uuid);
    return "listo";
  }

  const razon = (estado) => (estado === 0 ? "red" : estado === 401 || estado === 403 ? "clave" : estado === 429 ? "limite" : "servidor");

  async function enviarTodo() {
    const resumen = { enviados: [], con_error: 0, restantes: 0, detenido: null, perdidas: 0, fotos_rechazadas: 0 };
    const clave = await meta("clave");
    const pendientes = await listar();
    if (!clave || !pendientes.length) { resumen.restantes = pendientes.length; resumen.con_error = pendientes.filter((e) => e.estado === "error").length; return resumen; }
    for (const e of pendientes) {
      if (e.estado === "error") { resumen.con_error += 1; continue; }            // wrong data: waits for the person
      const r = await enviarUna(e, clave, resumen);
      if (r === "listo") resumen.enviados.push({ nombre: e.punto ? e.punto.nombre : "Cable", duplicado: e.duplicado || null, trazo: !!e.trazo });
      else if (r === "error") resumen.con_error += 1;
      else { resumen.detenido = r.detener; break; }
    }
    resumen.restantes = (await listar()).length;
    return resumen;
  }

  /* Only one sending at a time per browser (the page and the service worker could both be at it); the server would absorb a repeat anyway. */
  function enviar() {
    if (raiz.navigator && raiz.navigator.locks) return raiz.navigator.locks.request("campo-enviar", { ifAvailable: true }, (candado) => (candado ? enviarTodo() : null));
    return enviarTodo();
  }

  raiz.CampoCola = { agregar, actualizar, quitar, obtener, listar, ponerMeta, meta, redGuardar, redLeer, enviar };
})(typeof self !== "undefined" ? self : this);
