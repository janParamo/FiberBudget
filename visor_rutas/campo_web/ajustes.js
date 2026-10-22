/* App de campo: los ajustes de la persona (se guardan en su teléfono) y cómo se muestran las distancias y las coordenadas. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const CLAVE = "campo.ajustes";

  /* id -> {grupo, titulo, tipo: opciones | casilla | numero, defecto, ...}; el orden es el de la pantalla de Ajustes. */
  const DEFINICION = [
    { id: "tema", grupo: "Pantalla", titulo: "Tema (oscuro / claro)", tipo: "opciones", defecto: "sistema",
      opciones: [["sistema", "Usar el del teléfono"], ["claro", "Claro"], ["oscuro", "Oscuro"]] },
    { id: "mira", grupo: "Pantalla", titulo: "Mira del centro", tipo: "opciones", defecto: "contextual",
      opciones: [["contextual", "Solo al ubicar un punto"], ["siempre", "Siempre"], ["nunca", "Nunca"]] },
    { id: "coordenadas", grupo: "Pantalla", titulo: "Ventana de coordenadas", tipo: "opciones", defecto: "contextual",
      opciones: [["contextual", "Solo al ubicar un punto"], ["siempre", "Siempre"], ["nunca", "Nunca"]] },
    { id: "texto", grupo: "Pantalla", titulo: "Tamaño del texto", tipo: "opciones", defecto: "normal",
      opciones: [["chico", "Pequeño"], ["normal", "Normal"], ["grande", "Grande"], ["muygrande", "Muy grande"]] },
    { id: "pin", grupo: "Pantalla", titulo: "Tamaño de los puntos en el mapa", tipo: "opciones", defecto: "normal",
      opciones: [["chico", "Pequeño"], ["normal", "Normal"], ["grande", "Grande"], ["muygrande", "Muy grande"]] },
    { id: "zoom", grupo: "Pantalla", titulo: "Mostrar botones de acercar y alejar", tipo: "casilla", defecto: false },
    { id: "red", grupo: "Pantalla", titulo: "Mostrar los postes y mufas existentes", tipo: "casilla", defecto: true },
    { id: "decimales", grupo: "Pantalla", titulo: "Decimales de las coordenadas", tipo: "numero", defecto: 5, minimo: 3, maximo: 7, unidad: "" },
    { id: "rapido", grupo: "Acciones", titulo: "Agregar punto al instante", detalle: "El botón + guarda el punto donde está usted, sin mover el mapa", tipo: "casilla", defecto: false },
    { id: "navegacion", grupo: "Acciones", titulo: "Cómo llegar a un punto", tipo: "opciones", defecto: "preguntar",
      opciones: [["preguntar", "Preguntar"], ["google", "Google Maps"], ["apple", "Mapas de Apple"], ["waze", "Waze"], ["copiar", "Solo copiar las coordenadas"]] },
    { id: "distancia", grupo: "Idioma y unidades", titulo: "Unidad de distancia", tipo: "opciones", defecto: "metrico",
      opciones: [["metrico", "Metros / Kilómetros"], ["imperial", "Pies / Millas"]] },
    { id: "formato", grupo: "Idioma y unidades", titulo: "Formato de las coordenadas", tipo: "opciones", defecto: "decimal",
      opciones: [["decimal", "Grados decimales"], ["dms", "Grados, minutos y segundos"], ["dm", "Grados y minutos decimales"]] },
    { id: "foto_calidad", grupo: "Fotos", titulo: "Compresión de las fotos (JPEG)", tipo: "numero", defecto: 70, minimo: 40, maximo: 95, unidad: "%" },
    { id: "foto_lado", grupo: "Fotos", titulo: "Tamaño máximo de la foto", tipo: "opciones", defecto: 1600,
      opciones: [[1024, "Cabe en 1024 × 1024"], [1600, "Cabe en 1600 × 1600"], [2048, "Cabe en 2048 × 2048"], [3000, "Cabe en 3000 × 3000"]] },
    { id: "grab_precision", grupo: "Grabación de recorridos", titulo: "Precisión mínima del GPS", tipo: "numero", defecto: 25, minimo: 3, maximo: 100, unidad: "m" },
    { id: "grab_paso", grupo: "Grabación de recorridos", titulo: "Distancia mínima entre puntos", tipo: "numero", defecto: 5, minimo: 1, maximo: 100, unidad: "m" },
    { id: "grab_tiempo", grupo: "Grabación de recorridos", titulo: "Tiempo mínimo entre puntos", tipo: "numero", defecto: 3, minimo: 0, maximo: 120, unidad: "s" },
  ];
  const DEFECTOS = Object.fromEntries(DEFINICION.map((d) => [d.id, d.defecto]));
  let valores = { ...DEFECTOS };
  try { valores = { ...DEFECTOS, ...(JSON.parse(localStorage.getItem(CLAVE)) || {}) }; } catch (e) { /* private mode */ }

  const obtener = (id) => (id === undefined ? { ...valores } : valores[id]);

  function poner(id, valor) {
    const d = DEFINICION.find((x) => x.id === id);
    if (!d) return;
    if (d.tipo === "numero") valor = Math.min(d.maximo, Math.max(d.minimo, Math.round(Number(valor))));
    if (d.tipo === "casilla") valor = !!valor;
    valores[id] = valor;
    try { localStorage.setItem(CLAVE, JSON.stringify(valores)); } catch (e) { /* private mode */ }
    aplicar();
  }

  const TEXTO = { chico: 14, normal: 16, grande: 18, muygrande: 21 };
  const PIN = { chico: 0.8, normal: 1, grande: 1.3, muygrande: 1.6 };

  /* Puts the settings that are styles on the page (the rest are read by whoever needs them, when they need them). */
  function aplicar() {
    const r = document.documentElement;
    r.dataset.tema = valores.tema;
    r.style.fontSize = `${TEXTO[valores.texto] || 16}px`;
    r.style.setProperty("--pin", String(PIN[valores.pin] || 1));
    r.dataset.mira = valores.mira;
    r.dataset.coordenadas = valores.coordenadas;
    document.dispatchEvent(new CustomEvent("campo-ajustes"));
  }

  /* ---------------------------------------------------------------- cómo se muestran las medidas */
  const grados = (v, pos, neg) => ({ n: Math.abs(v), h: v >= 0 ? pos : neg });

  function coord(lat, lon) {
    const f = valores.formato, d = Number(valores.decimales);
    if (f === "decimal") return `${lat.toFixed(d)}, ${lon.toFixed(d)}`;
    const una = (v, pos, neg) => {
      const g = grados(v, pos, neg), ent = Math.floor(g.n), resto = (g.n - ent) * 60;
      if (f === "dm") return `${ent}° ${resto.toFixed(Math.max(0, d - 2))}′ ${g.h}`;
      const min = Math.floor(resto), seg = (resto - min) * 60;
      return `${ent}° ${min}′ ${seg.toFixed(Math.max(0, d - 3))}″ ${g.h}`;
    };
    return `${una(lat, "N", "S")}  ${una(lon, "E", "O")}`;
  }

  function dist(m) {
    if (m == null || !isFinite(m)) return "—";
    if (valores.distancia === "imperial") {
      const pies = m * 3.28084;
      return pies >= 1000 ? `${(m / 1609.344).toFixed(2)} mi` : `${Math.round(pies)} ft`;
    }
    return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
  }

  C.ajustes = { DEFINICION, obtener, poner, aplicar };
  C.fmt = { coord, dist };
})();
