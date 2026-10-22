/* App de campo: service worker. Deja abrir la app sin señal (guarda sus archivos), recuerda los mosaicos del mapa que ya se vieron y, en Android,
 * envía la cola cuando vuelve la señal aunque la app esté cerrada (Background Sync; iPhone no lo tiene: ahí se envía al abrir la app). */
importScripts("cola.js");

const VERSION = "campo-v7";
const TILES = "campo-mosaicos";
const MAX_MOSAICOS = 900;
const ARCHIVOS = ["./", "index.html", "campo.css", "api.js", "cola.js", "trazo.js", "iconos.js", "ajustes.js", "base.js", "mapa.js", "red.js", "ayuda.js",
                  "exportar.js", "captura.js", "editor.js", "lista.js", "menu.js", "app.js", "manifest.webmanifest", "icono-192.png", "icono-512.png",
                  "icono-apple.png", "lib/leaflet/leaflet.js", "lib/leaflet/leaflet.css", "lib/leaflet/images/marker-icon.png", "lib/leaflet/images/marker-icon-2x.png",
                  "lib/leaflet/images/marker-shadow.png", "lib/leaflet/images/layers.png", "lib/leaflet/images/layers-2x.png"];
const HOSTS_MOSAICOS = ["server.arcgisonline.com", "tile.openstreetmap.org"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(ARCHIVOS.map((u) => new Request(u, { cache: "reload" })))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((n) => n !== VERSION && n !== TILES).map((n) => caches.delete(n)))).then(() => self.clients.claim()));
});

async function recortar(cache) {
  const claves = await cache.keys();
  for (let i = 0; i < claves.length - MAX_MOSAICOS; i++) await cache.delete(claves[i]);
}

async function mosaico(req) {
  const cache = await caches.open(TILES);
  const guardado = await cache.match(req);
  if (guardado) return guardado;
  try {
    const r = await fetch(req);
    if (r && (r.ok || r.type === "opaque")) { cache.put(req, r.clone()).then(() => recortar(cache)).catch(() => {}); }
    return r;
  } catch (e) {
    return new Response("", { status: 504 });
  }
}

async function archivo(req) {
  const cache = await caches.open(VERSION);
  try {
    const r = await fetch(req);
    if (r.ok) cache.put(req, r.clone());
    return r;
  } catch (e) {
    return (await cache.match(req, { ignoreSearch: true })) || (req.mode === "navigate" ? await cache.match("./") : null) || new Response("Sin conexión", { status: 503 });
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (HOSTS_MOSAICOS.includes(url.hostname)) { e.respondWith(mosaico(req)); return; }
  if (url.origin === self.location.origin && url.pathname.startsWith("/campo/")) e.respondWith(archivo(req));
  // the API (/visor/...) always goes to the network: it is never answered from a cache
});

self.addEventListener("sync", (e) => {
  if (e.tag !== "campo-enviar") return;
  e.waitUntil(CampoCola.enviar().then(async (r) => {
    const clientes = await self.clients.matchAll({ includeUncontrolled: true });
    clientes.forEach((c) => c.postMessage({ tipo: "cola", resumen: r }));
    if (r && r.detenido === "red") throw new Error("sin conexión: reintentar");           // makes the browser try the sync again later
  }));
});
