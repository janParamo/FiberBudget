/* Red dibujada en "Mis lugares" (visor v2, fase 4): mufas, postes, clientes, nodos, ODF y cables dentro de una carpeta, sin proyecto.
 *
 * Los puntos se colocan con un clic (igual que una marca) y se llenan en la pestaña "Datos de red" de la ventana flotante (dialogo.js).
 * Un cable se dibuja con clics: empieza y termina en un elemento de la red de Mis lugares (el cursor se pega a los elementos cercanos,
 * 18 px, como en el editor de proyectos), los puntos intermedios también se pegan; doble clic o Enter termina, Retroceso quita el
 * último punto, Esc cancela. Al terminar se abre la ventana del cable (clase, tipo, hilos…). El servidor (redes/lugares_red.py)
 * valida, pone el ícono según el subtipo, calcula el metraje con las reglas y mueve el extremo de los cables cuando un elemento se mueve.
 *
 *   DibujarRed.formulario(tipo, propiedades, alCambiar) -> {html, activar(raiz), leer(), validar()}   DibujarRed.icono(tipo, subtipo)
 *   DibujarRed.dibujarCable(carpetaId)    DibujarRed.filasPopup(elemento, nombreDe)    DibujarRed.guardarComoProyecto(carpeta)
 */
(function () {
  "use strict";

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const IMAN_PX = 18;
  const RED = ["mufa", "poste", "cliente", "nodo", "odf"];
  const SUBTIPOS = {
    poste: [["ideay", "IDEAY"], ["concreto", "Concreto"], ["madera", "Madera"], ["metal", "Metal"], ["cliente", "Cliente"]],
    mufa: [["empalme", "Empalme"], ["distribucion", "Distribución (FDT)"], ["terminal", "Terminal (FAT)"], ["reserva", "Reserva"]],
    nodo: [["olt", "OLT"], ["nodo", "Nodo"], ["mini_nodo", "Mini nodo"]],
  };
  const CLASES = [["troncal", "Troncal"], ["distribucion", "Distribución"], ["acometida", "Acometida"]];
  const HILOS = [2, 4, 6, 8, 12, 24, 48, 72, 96, 144];
  const POR_BUFFER = [2, 4, 6, 8, 12];
  const GROSOR = { troncal: 5, distribucion: 3, acometida: 2 };
  // the same table as redes/lugares_red.py (the server has the last word)
  const ICONOS = {
    mufa: { empalme: ["circulo", "#ff8c00", 1], distribucion: ["cuadrado", "#e6c200", 1], terminal: ["anillo", "#d6249f", 1], reserva: ["anillo", "#ff8c00", 1] },
    poste: { concreto: ["circulo", "#9aa3ad", 0.55], ideay: ["circulo", "#2f6fdb", 0.55], madera: ["circulo", "#8b5a2b", 0.55], metal: ["circulo", "#c0c7cf", 0.55], cliente: ["circulo", "#f08c00", 0.55] },
    cliente: { _: ["rombo", "#0a9d57", 0.9] }, nodo: { _: ["triangulo", "#f5b400", 1] }, odf: { _: ["cuadrado", "#4a5568", 0.9] },
  };
  const dr = { cable: null, ctx: null };

  const esRed = (tipo) => RED.includes(tipo) || tipo === "cable";

  function icono(tipo, subtipo) {
    const t = ICONOS[tipo] || {};
    const [id, color, escala] = t[subtipo] || t._ || Object.values(t)[0] || ["circulo", "#ff8c00", 1];
    return { tipo: "figura", id, color, escala, opacidad: 1 };
  }

  const estiloInicial = (tipo, propiedades = {}) => (tipo === "cable"
    ? { linea: { color: propiedades.color || "#1f6feb", grosor: GROSOR[propiedades.clase] || 3, opacidad: 1 } }
    : { icono: icono(tipo, propiedades.subtipo || (SUBTIPOS[tipo] || [[null]])[0][0]), etiqueta: { visible: tipo !== "poste", color: "#ffffff", escala: 1 } });

  // ------------------------------------------------------------------ formulario de cada tipo (pestaña "Datos de red")
  function formulario(tipo, propiedades, alCambiar) {
    const p = propiedades || {};
    const opciones = (lista, actual) => lista.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(actual) ? " selected" : ""}>${esc(t)}</option>`).join("");
    const campo = (id, etiqueta, cuerpo) => `<div class="vp-campo"><label for="dr-${id}">${etiqueta}</label>${cuerpo}</div>`;
    let html = "";
    if (SUBTIPOS[tipo]) html += campo("subtipo", "Tipo", `<select id="dr-subtipo">${opciones(SUBTIPOS[tipo], p.subtipo || SUBTIPOS[tipo][0][0])}</select>`);
    if (tipo === "mufa") {
      html += `<div class="vp-fila">${campo("capacidad", "Capacidad (hilos)", `<input id="dr-capacidad" type="number" min="1" max="1000" value="${esc(p.capacidad ?? "")}">`)}
        ${campo("bandejas", "Bandejas", `<input id="dr-bandejas" type="number" min="0" max="100" value="${esc(p.bandejas ?? "")}">`)}</div>
        <p class="ml-d-nota">Las bandejas y los empalmes se arman al pasar la carpeta a un proyecto («Guardar como proyecto»).</p>`;
    } else if (tipo === "cliente") {
      html += `<div class="vp-fila">${campo("codigo", "Código", `<input id="dr-codigo" maxlength="40" placeholder="C12345" value="${esc(p.codigo ?? "")}">`)}
        ${campo("id_servicio", "ID de servicio", `<input id="dr-id_servicio" maxlength="40" value="${esc(p.id_servicio ?? "")}">`)}</div>`;
    } else if (tipo === "odf") {
      html += `<p class="ml-d-nota">Un ODF no lleva datos propios: se une a los cables como cualquier otro elemento.</p>`;
    } else if (tipo === "cable") {
      html += `<div class="vp-fila">${campo("clase", "Clase", `<select id="dr-clase">${opciones(CLASES, p.clase || "distribucion")}</select>`)}
        ${campo("tipo", "Cable", `<select id="dr-tipo">${opciones([["ADSS", "ADSS"], ["FLAT", "FLAT"]], p.tipo || "ADSS")}</select>`)}</div>
        <div class="vp-fila">${campo("hilos", "Hilos", `<select id="dr-hilos">${opciones(HILOS.map((h) => [h, h]), p.hilos === undefined ? 12 : p.hilos)}</select>`)}
        ${campo("hilos_por_buffer", "Hilos por buffer", `<select id="dr-hilos_por_buffer">${opciones(POR_BUFFER.map((h) => [h, h]), p.hilos_por_buffer || 12)}</select>`)}
        ${campo("cruces", "Cruces", `<input id="dr-cruces" type="number" min="0" max="500" value="${esc(p.cruces ?? 0)}">`)}</div>
        ${campo("color", "Color en el mapa", `<input id="dr-color" type="color" value="${esc(p.color || "#1f6feb")}">`)}
        <p class="ml-d-nota" id="dr-extremos"></p>`;
    }
    const leer = () => {
      const v = (id) => { const e = document.getElementById(`dr-${id}`); return e ? e.value : undefined; };
      if (tipo === "cable") {
        return { clase: v("clase"), tipo: v("tipo"), hilos: Number(v("hilos")), hilos_por_buffer: Number(v("hilos_por_buffer")), cruces: Number(v("cruces") || 0), color: v("color") };
      }
      const salida = {};
      if (SUBTIPOS[tipo]) salida.subtipo = v("subtipo");
      if (tipo === "mufa") { salida.capacidad = v("capacidad"); salida.bandejas = v("bandejas"); }
      if (tipo === "cliente") { salida.codigo = (v("codigo") || "").trim(); salida.id_servicio = (v("id_servicio") || "").trim(); }
      return salida;
    };
    const validar = () => {
      const d = leer();
      if (tipo === "cliente" && d.codigo && !/^C\d{3,8}$/i.test(d.codigo)) return "El código de cliente debe ser C seguido de números (C12345)";
      if (tipo === "mufa" && d.capacidad && !(Number(d.capacidad) >= 1 && Number(d.capacidad) <= 1000)) return "La capacidad va de 1 a 1000 hilos";
      return null;
    };
    const activar = (raiz) => {
      raiz.oninput = raiz.onchange = () => alCambiar && alCambiar(leer());
    };
    return { html, activar, leer, validar };
  }

  // ------------------------------------------------------------------ popup
  function filasPopup(e, nombreDe) {
    const p = e.propiedades || {}, filas = [];
    const titulo = (lista, v) => (lista.find(([k]) => k === v) || [0, v])[1];
    if (SUBTIPOS[e.tipo] && p.subtipo) filas.push(["Tipo", titulo(SUBTIPOS[e.tipo], p.subtipo)]);
    if (e.tipo === "mufa") { if (p.capacidad) filas.push(["Capacidad", `${p.capacidad} hilos`]); if (p.bandejas) filas.push(["Bandejas", p.bandejas]); }
    if (e.tipo === "cliente") { if (p.codigo) filas.push(["Código", p.codigo]); if (p.id_servicio) filas.push(["ID de servicio", p.id_servicio]); }
    if (e.tipo === "cable") {
      filas.push(["Cable", `${titulo(CLASES, p.clase)} · ${p.tipo} · ${p.hilos == null ? "hilos desconocidos" : `${p.hilos} hilos`}`],
        ["Extremos", `${nombreDe(p.origen_id) || "sin elemento"} → ${nombreDe(p.destino_id) || "sin elemento"}`]);
      if (p.metraje) filas.push(["Metraje", `${Number(p.metraje.metraje_m).toLocaleString("en-US")} m (lineal ${Number(p.metraje.distancia_lineal_m).toLocaleString("en-US")} m + reservas)`]);
    }
    return filas;
  }

  // ------------------------------------------------------------------ cable: dibujo con imán
  function elementoCerca(latlng) {
    const mapa = dr.ctx.mapa, ref = mapa.latLngToContainerPoint(latlng);
    let mejor = null, dmin = IMAN_PX;
    window.MisLugares.elementosRed().forEach((el) => {
      const d = ref.distanceTo(mapa.latLngToContainerPoint(el.latlng));
      if (d <= dmin) { dmin = d; mejor = el; }
    });
    return mejor;
  }

  function ayuda(texto) {
    const caja = document.getElementById("ml-ayuda");
    if (caja) { caja.hidden = !texto; caja.textContent = texto || ""; }
  }

  function pintarCable() {
    const c = dr.cable;
    if (!c) return;
    const ll = c.puntos.map((q) => q.latlng);
    c.linea.setLatLngs(ll);
    c.anillos.clearLayers();
    c.puntos.forEach((q) => { if (q.elemento) L.circleMarker(q.latlng, { radius: 9, color: "#ffe600", weight: 3, fill: false, interactive: false }).addTo(c.anillos); });
  }

  function terminarCable() {
    const c = dr.cable;
    if (!c) return;
    const puntos = c.puntos, a = puntos[0], z = puntos[puntos.length - 1];
    if (puntos.length < 2) { dr.ctx.aviso("Faltan puntos: haga clic en el elemento de inicio, en el recorrido y en el elemento final", "error"); return; }
    if (!z.elemento) { dr.ctx.aviso("El cable termina en un elemento (mufa, poste, cliente, nodo u ODF): haga el último clic sobre uno", "error"); return; }
    if (z.elemento.id === a.elemento.id) { dr.ctx.aviso("El cable empieza y termina en el mismo elemento", "error"); return; }
    const datos = { carpetaId: c.carpetaId, latlngs: puntos.map((q) => q.latlng), origen_id: a.elemento.id, destino_id: z.elemento.id };
    limpiarCable();
    window.MisLugares.abrirCable(datos);
  }

  function limpiarCable(cancelado) {
    const c = dr.cable;
    if (!c) return;
    const mapa = dr.ctx.mapa;
    mapa.off("click", c.alClic).off("mousemove", c.alMover).off("dblclick", c.alDoble);
    document.removeEventListener("keydown", c.alTecla, true);
    mapa.removeLayer(c.linea).removeLayer(c.guia).removeLayer(c.anillos);
    mapa.getContainer().classList.remove("ml-colocando");
    mapa.doubleClickZoom.enable();
    dr.cable = null;
    ayuda("");
    if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo(null);
    if (cancelado) dr.ctx.aviso("Cable cancelado");
  }

  /** A click on the map (or on an element, passed by MisLugares) adds a point, glued to the element near it. */
  function agregarPunto(latlng) {
    const c = dr.cable;
    if (!c) return;
    const el = elementoCerca(latlng);
    if (!c.puntos.length && !el) { dr.ctx.aviso("El cable empieza en un elemento: haga clic sobre una mufa, poste, cliente, nodo u ODF", "error"); return; }
    const ll = el ? el.latlng : latlng;
    const ultimo = c.puntos[c.puntos.length - 1];
    if (ultimo && ultimo.latlng.equals(ll)) return;                       // the second click of a double click
    c.puntos.push({ latlng: ll, elemento: el });
    pintarCable();
  }

  async function dibujarCable(carpetaId) {
    if (dr.cable) limpiarCable();
    const mapa = dr.ctx.mapa;
    if (window.MisLugares.elementosRed().length < 2) { dr.ctx.aviso("Un cable une dos elementos de la red: agregue primero las mufas, postes, clientes, nodos u ODF", "error"); return; }
    mapa.doubleClickZoom.disable();
    mapa.getContainer().classList.add("ml-colocando");
    const c = dr.cable = { carpetaId, puntos: [], linea: L.polyline([], { color: "#1f6feb", weight: 4, interactive: false }).addTo(mapa),
                           guia: L.polyline([], { color: "#1f6feb", weight: 2, dashArray: "6 6", interactive: false }).addTo(mapa), anillos: L.layerGroup().addTo(mapa) };
    c.alClic = (ev) => agregarPunto(ev.latlng);
    c.alMover = (ev) => {
      if (!c.puntos.length) return;
      const el = elementoCerca(ev.latlng);
      c.guia.setLatLngs([c.puntos[c.puntos.length - 1].latlng, el ? el.latlng : ev.latlng]);
    };
    c.alDoble = (ev) => { L.DomEvent.stop(ev); terminarCable(); };
    c.alTecla = (ev) => {
      if (ev.target.closest && ev.target.closest("input, textarea, select")) return;
      if (ev.key === "Escape") { ev.stopPropagation(); limpiarCable(true); }
      else if (ev.key === "Enter") { ev.preventDefault(); terminarCable(); }
      else if (ev.key === "Backspace") { ev.preventDefault(); c.puntos.pop(); pintarCable(); c.guia.setLatLngs([]); }
    };
    mapa.on("click", c.alClic).on("mousemove", c.alMover).on("dblclick", c.alDoble);
    document.addEventListener("keydown", c.alTecla, true);
    ayuda("Cable: clic en el elemento de inicio, en el recorrido (se pega a postes y mufas) y doble clic en el elemento final · Retroceso quita el último · Esc cancela");
    if (window.BarraHerramientas) window.BarraHerramientas.marcarActivo("cable");
  }

  // ------------------------------------------------------------------ guardar la carpeta como proyecto
  async function guardarComoProyecto(carpeta) {
    const nombre = await Dialogo.pedirTexto("Guardar como proyecto", carpeta.nombre, "Nombre del proyecto");
    if (!nombre) return;
    dr.ctx.aviso("Creando el proyecto…", "cargando");
    const r = await window.Redes.llamar("lugares_a_proyecto", { carpeta_id: carpeta.id, nombre });
    if (!r.ok) { dr.ctx.aviso(r.error, "error"); return; }
    const s = r.resumen;
    dr.ctx.aviso(`Proyecto «${r.proyecto.nombre}» (${r.proyecto.codigo}) creado con ${s.elementos} elemento(s) y ${s.cables} cable(s)`
      + (s.cables_omitidos.length ? ` · sin extremos en la red, no se copiaron: ${s.cables_omitidos.join(", ")}` : "")
      + (s.fuera_de_la_red ? ` · ${s.fuera_de_la_red} marca(s)/ruta(s)/polígono(s) quedan solo en la carpeta` : "") + ". Está en el menú Proyectos.", "ok");
  }

  function iniciar(ctx) { dr.ctx = ctx; }

  window.DibujarRed = { iniciar, esRed, icono, estiloInicial, formulario, filasPopup, dibujarCable, agregarPunto, guardarComoProyecto, terminar: terminarCable,
                        get dibujando() { return !!dr.cable; }, RED };
})();
