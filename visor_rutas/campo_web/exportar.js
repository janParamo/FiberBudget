/* App de campo: exportar lo levantado (KML, KMZ o CSV) y compartirlo con las apps del teléfono. Todo se arma en el teléfono, también sin señal. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]));
  const kmlColor = (hex) => { const h = hex.replace("#", ""); return `ff${h.slice(4, 6)}${h.slice(2, 4)}${h.slice(0, 2)}`; };     // #rrggbb -> aabbggrr

  /* items: lo que arma Campo.lista.items(): {clase: "punto" | "cable", tipo, subtipo, nombre, notas, lat, lon, puntos, estado, fecha, jornada, usuario, precision_m, hilos, tipo_cable} */
  function aKml(items, titulo) {
    const estilos = Object.entries(C.COLOR_TIPO).map(([t, c]) => `<Style id="t-${t}"><IconStyle><color>${kmlColor(c)}</color><scale>1.1</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle><LineStyle><color>${kmlColor(c)}</color><width>4</width></LineStyle></Style>`).join("");
    const datos = (i) => [["Estado", C.ESTADO[i.estado] || i.estado], ["Jornada", i.jornada], ["Técnico", i.usuario], ["Fecha", i.fecha ? C.fecha(i.fecha) : ""], ["Subtipo", C.subtipoTexto(i.tipo, i.subtipo)],
      ["Precisión (m)", i.precision_m != null ? Math.round(i.precision_m) : ""], ["Hilos", i.hilos || ""], ["Tipo de cable", i.tipo_cable || ""]]
      .filter(([, v]) => v !== "" && v != null).map(([k, v]) => `<Data name="${esc(k)}"><value>${esc(v)}</value></Data>`).join("");
    const marcas = items.map((i) => {
      const nombre = i.clase === "cable" ? `Cable ${i.nombre || ""}`.trim() : i.nombre;
      const geo = i.clase === "cable"
        ? `<LineString><tessellate>1</tessellate><coordinates>${i.puntos.map((p) => `${p.lon},${p.lat},0`).join(" ")}</coordinates></LineString>`
        : `<Point><coordinates>${i.lon},${i.lat},0</coordinates></Point>`;
      return `<Placemark><name>${esc(nombre)}</name><description>${esc(i.notas || "")}</description><styleUrl>#t-${i.tipo}</styleUrl><ExtendedData>${datos(i)}</ExtendedData>${geo}</Placemark>`;
    }).join("");
    return `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${esc(titulo)}</name>${estilos}${marcas}</Document></kml>`;
  }

  /* CSV: solo los puntos (un cable no cabe en una fila) */
  function aCsv(items) {
    const celda = (v) => { const t = String(v == null ? "" : v); return /[",\n;]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
    const filas = [["tipo", "subtipo", "nombre", "descripcion", "latitud", "longitud", "precision_m", "estado", "fecha", "jornada", "tecnico"]];
    items.filter((i) => i.clase === "punto").forEach((i) => filas.push([C.ETIQUETA[i.tipo], C.subtipoTexto(i.tipo, i.subtipo), i.nombre, i.notas, i.lat, i.lon,
      i.precision_m != null ? Math.round(i.precision_m) : "", C.ESTADO[i.estado] || i.estado, i.fecha ? C.fecha(i.fecha) : "", i.jornada, i.usuario]));
    return "﻿" + filas.map((f) => f.map(celda).join(",")).join("\r\n");
  }

  /* KMZ: un zip con doc.kml (sin comprimir: no hace falta una biblioteca) */
  const TABLA_CRC = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc32 = (b) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TABLA_CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

  function zip(nombre, contenido) {
    const n = new TextEncoder().encode(nombre), d = contenido, crc = crc32(d), ahora = new Date();
    const hora = (ahora.getHours() << 11) | (ahora.getMinutes() << 5) | (ahora.getSeconds() >> 1), dia = ((ahora.getFullYear() - 1980) << 9) | ((ahora.getMonth() + 1) << 5) | ahora.getDate();
    const local = new DataView(new ArrayBuffer(30));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, hora, 2], [12, dia, 2], [14, crc, 4], [18, d.length, 4], [22, d.length, 4], [26, n.length, 2], [28, 0, 2]]
      .forEach(([o, v, t]) => (t === 4 ? local.setUint32(o, v, true) : local.setUint16(o, v, true)));
    const central = new DataView(new ArrayBuffer(46));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, hora, 2], [14, dia, 2], [16, crc, 4], [20, d.length, 4], [24, d.length, 4], [28, n.length, 2], [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2], [38, 0, 4], [42, 0, 4]]
      .forEach(([o, v, t]) => (t === 4 ? central.setUint32(o, v, true) : central.setUint16(o, v, true)));
    const fin = new DataView(new ArrayBuffer(22));
    [[0, 0x06054b50, 4], [4, 0, 2], [6, 0, 2], [8, 1, 2], [10, 1, 2], [12, 46 + n.length, 4], [16, 30 + n.length + d.length, 4], [20, 0, 2]]
      .forEach(([o, v, t]) => (t === 4 ? fin.setUint32(o, v, true) : fin.setUint16(o, v, true)));
    return new Blob([local, n, d, central, n, fin], { type: "application/vnd.google-earth.kmz" });
  }

  function generar(items, formato, titulo) {
    const base = `campo_${new Date().toISOString().slice(0, 10)}`;
    if (formato === "csv") return { blob: new Blob([aCsv(items)], { type: "text/csv;charset=utf-8" }), nombre: `${base}.csv` };
    const kml = aKml(items, titulo || "Levantamiento de campo");
    if (formato === "kmz") return { blob: zip("doc.kml", new TextEncoder().encode(kml)), nombre: `${base}.kmz` };
    return { blob: new Blob([kml], { type: "application/vnd.google-earth.kml+xml" }), nombre: `${base}.kml` };
  }

  /* abre la hoja de compartir del teléfono; si no la hay, descarga el archivo */
  async function entregar(blob, nombre) {
    const archivo = new File([blob], nombre, { type: blob.type });
    try {
      if (navigator.canShare && navigator.canShare({ files: [archivo] })) { await navigator.share({ files: [archivo], title: nombre }); return "compartido"; }
    } catch (e) { if (e && e.name === "AbortError") return "cancelado"; }
    const url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = nombre; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return "descargado";
  }

  /* El diálogo «Compartir o exportar»: todo lo de la jornada, lo de varias jornadas, o solo lo que se ve ahora (el filtro) */
  async function abrir() {
    const todos = C.lista.items(false);
    if (!todos.length) { C.aviso("Todavía no hay nada que exportar"); return; }
    const modo = await C.dialogo.opciones("Compartir o exportar", [
      { valor: "todo", texto: "Todos los puntos y cables", detalle: `${todos.length} en total`, icono: "compartir" },
      { valor: "visible", texto: "Lo que se ve ahora en el mapa", detalle: "según el filtro", icono: "filtro" },
      { valor: "jornadas", texto: "Elegir jornadas", detalle: "una o varias", icono: "carpeta" },
    ]);
    if (!modo) return;
    let items = modo === "visible" ? C.lista.items(true) : todos;
    if (modo === "jornadas") {
      const nombres = [...new Set(todos.map((i) => i.jornada))];
      const elegidas = await C.dialogo.mostrar({
        titulo: "Jornadas a exportar", cuerpo: nombres.map((n, k) => `<label class="dlg-check"><input type="checkbox" data-n="${k}" checked> ${C.esc(n)} (${todos.filter((i) => i.jornada === n).length})</label>`).join(""),
        botones: [{ texto: "Cancelar", valor: null }, { texto: "Aceptar", valor: "leer", primario: true }],
        leer: (r) => [...r.querySelectorAll("input:checked")].map((c) => nombres[Number(c.dataset.n)]),
      });
      if (!elegidas) return;
      items = todos.filter((i) => elegidas.includes(i.jornada));
    }
    if (!items.length) { C.aviso("No hay nada con ese filtro", "malo"); return; }
    const formato = await C.dialogo.opciones("¿En qué formato?", [
      { valor: "kml", texto: "KML", detalle: "Formato de Google Earth. No lleva fotos." },
      { valor: "kmz", texto: "KMZ", detalle: "KML comprimido, para Google Earth." },
      { valor: "csv", texto: "CSV", detalle: "Hoja de cálculo. Solo los puntos (no lleva cables ni fotos)." },
    ]);
    if (!formato) return;
    const r = generar(items, formato);
    const estado = await entregar(r.blob, r.nombre);
    if (estado === "descargado") C.aviso(`Se descargó ${r.nombre}`, "ok");
    else if (estado === "compartido") C.aviso("Listo", "ok");
  }

  C.exportar = { abrir, generar, aKml, aCsv, zip, crc32, entregar };
})();
