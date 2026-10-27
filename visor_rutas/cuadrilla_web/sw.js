/* App de la cuadrilla: service worker. Guarda los archivos de la app para poder abrirla sin señal (los datos siempre se piden al servidor: sin señal
 * se ve lo último que se cargó y las acciones avisan que no hay conexión). */
const VERSION = "cuadrilla-v1";
const ARCHIVOS = ["./", "index.html", "cuadrilla.css", "cuadrilla.js", "manifest.webmanifest", "icono-192.png", "icono-512.png", "icono-apple.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(ARCHIVOS.map((u) => new Request(u, { cache: "reload" })))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((n) => n !== VERSION).map((n) => caches.delete(n)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/cuadrilla/")) return;   // the API is never cached
  e.respondWith(fetch(e.request).then((r) => { if (r.ok) { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copia)); } return r; })
    .catch(() => caches.match(e.request).then((c) => c || caches.match("index.html"))));
});
