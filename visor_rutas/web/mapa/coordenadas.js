/* Coordenadas escritas a mano (visor v2, fase 2): decimal, grados-minutos-segundos y grados-minutos decimales.
 *
 *   13.094578, -86.002708 | 13.094578 -86.002708 | 13.094578;-86.002708
 *   13°5'38.09"N 86°0'7.42"O (también W, º, espacios; la letra puede ir delante) | 13 5.6348N 86 0.1237W
 *
 * Es el mismo intérprete de visor_rutas/coordenadas.py (ahí está explicada la gramática). Los dos se prueban con
 * los casos de Pruebas/vectores_coordenadas.json: si cambia uno, cambia el otro.
 *   Coordenadas.interpretar(texto) -> {estado: "ok" | "invertida" | "fuera" | "error" | "no_coordenada", lat, lon, mensaje, sugerencia}
 */
(function () {
  "use strict";

  const NI = { latMin: 10.7, latMax: 15.1, lonMin: -87.8, lonMax: -82.5 };       // = config.NI_* de Python
  const HEMISFERIO = { N: ["lat", 1], S: ["lat", -1], E: ["lon", 1], W: ["lon", -1], O: ["lon", -1] };
  const NO_ES = "no es una coordenada";

  class NoValida extends Error {}

  const enNicaragua = (lat, lon) => lat >= NI.latMin && lat <= NI.latMax && lon >= NI.lonMin && lon <= NI.lonMax;

  function unidades(texto) {
    return texto.replace(/[º˚]/g, "°").replace(/[′’´ʹ]/g, "'").replace(/[″”“ʺ]/g, '"');
  }

  const fichasDe = (limpio) => [...limpio.matchAll(/((?<![A-Za-z])[NSEWOnsewo](?![A-Za-z]))|([-+]?\d+(?:\.\d+)?)/g)]
    .map((m) => (m[1] ? ["hem", m[1]] : ["num", m[2]]));

  /** [] when the text holds anything besides numbers, hemisphere letters and separators / units. */
  function separar(texto) {
    const limpio = unidades(texto);
    const resto = limpio.replace(/((?<![A-Za-z])[NSEWOnsewo](?![A-Za-z]))|([-+]?\d+(?:\.\d+)?)/g, " ");
    if (/[^\s,;°'"()[\]]/.test(resto)) return [];
    return fichasDe(limpio);
  }

  function grupoAGrados(numeros, ejeMaximo) {
    const d = parseFloat(numeros[0]);
    const signo = numeros[0].trimStart().startsWith("-") ? -1 : 1;
    if (numeros.length > 1 && d !== Math.trunc(d)) throw new NoValida("Los grados con decimales no llevan minutos");
    const m = numeros.length > 1 ? parseFloat(numeros[1]) : 0;
    const s = numeros.length > 2 ? parseFloat(numeros[2]) : 0;
    if (numeros.length > 1 && (m < 0 || m >= 60 || /^[-+]/.test(numeros[1]))) throw new NoValida("Los minutos van de 0 a 59");
    if (numeros.length > 2 && (s < 0 || s >= 60 || /^[-+]/.test(numeros[2]))) throw new NoValida("Los segundos van de 0 a 59");
    if (numeros.length > 2 && m !== Math.trunc(m)) throw new NoValida("Los minutos con decimales no llevan segundos");
    const valor = Math.abs(d) + m / 60 + s / 3600;
    if (valor > ejeMaximo) throw new NoValida(`El valor ${valor.toFixed(6)} se sale del rango (±${ejeMaximo})`);
    return signo * valor;
  }

  function valores(texto) {
    const fichas = separar(texto);
    if (!fichas.length || !fichas.some(([t]) => t === "num")) throw new NoValida(NO_ES);
    const letras = fichas.filter(([t]) => t === "hem").map(([, v]) => v.toUpperCase());
    let grupos = [];
    if (letras.length) {
      if (letras.length !== 2) throw new NoValida("Indique las dos letras (por ejemplo N y O), o ninguna");
      const sufijo = fichas[0][0] === "num";             // 13 5 38 N 86 0 7 O   (or N 13 5 38 O 86 0 7)
      let actual = [], pendiente = null;
      for (const [tipo, valor] of fichas) {
        if (tipo === "num") actual.push(valor);
        else if (sufijo) { grupos.push([actual, valor.toUpperCase()]); actual = []; }
        else {
          if (actual.length) grupos.push([actual, pendiente]);
          actual = []; pendiente = valor.toUpperCase();
        }
      }
      if (!sufijo) grupos.push([actual, pendiente]);
      else if (actual.length) throw new NoValida("Sobran números después de la última letra");
      if (grupos.length !== 2 || grupos.some((g) => !g[0].length)) throw new NoValida("Cada coordenada necesita sus números");
    } else {
      const numeros = fichas.map(([, v]) => v);
      if (![2, 4, 6].includes(numeros.length)) throw new NoValida("Escriba latitud y longitud (decimal, o grados minutos segundos)");
      const mitad = numeros.length / 2;
      grupos = [[numeros.slice(0, mitad), null], [numeros.slice(mitad), null]];
    }
    const ejes = grupos.map(([, l]) => (l ? HEMISFERIO[l][0] : null));
    if (letras.length && ejes[0] === ejes[1]) throw new NoValida("Una letra es de latitud (N o S) y la otra de longitud (E, O o W)");
    const salida = [];
    grupos.forEach(([numeros, letra], i) => {
      let v = grupoAGrados(numeros, ejes[i] === "lat" || (ejes[i] === null && i === 0) ? 90 : 180);
      if (letra) v = numeros[0].trimStart()[0] !== "-" ? Math.abs(v) * HEMISFERIO[letra][1] : -Math.abs(v);
      salida.push(v);
    });
    if (letras.length && ejes[0] === "lon") salida.reverse();
    return salida;
  }

  function interpretar(textoOriginal) {
    const texto = String(textoOriginal || "").trim();
    const nada = { estado: "no_coordenada", lat: null, lon: null, mensaje: "", sugerencia: null };
    if (!texto || !/\d/.test(texto)) return nada;
    let lat, lon;
    try {
      [lat, lon] = valores(texto);
    } catch (e) {
      if (!(e instanceof NoValida)) throw e;
      const numeros = separar(texto).filter(([t]) => t === "num");
      return e.message !== NO_ES && numeros.length >= 2 ? { ...nada, estado: "error", mensaje: e.message } : nada;
    }
    if (enNicaragua(lat, lon)) return { ...nada, estado: "ok", lat, lon };
    if (enNicaragua(lon, lat)) {
      return { ...nada, estado: "invertida", lat, lon, mensaje: `Latitud y longitud parecen invertidas: (${lat}, ${lon})`, sugerencia: [lon, lat] };
    }
    return { ...nada, estado: "fuera", lat, lon,
      mensaje: `La coordenada (${lat.toFixed(6)}, ${lon.toFixed(6)}) está fuera de Nicaragua (latitud ${NI.latMin}..${NI.latMax}, longitud ${NI.lonMin}..${NI.lonMax})` };
  }

  /** One coordinate value ("13.094578", `13°5'38.09"N`, "86 0.1237 W", "-86.0027") as signed degrees, or null if it is not one.
   *  For the latitude / longitude fields of a mark (a pair is read by interpretar). */
  function valor(texto) {
    const limpio = unidades(String(texto || ""));
    if (/[^\s,;°'"()[\]]/.test(limpio.replace(/((?<![A-Za-z])[NSEWOnsewo](?![A-Za-z]))|([-+]?\d+(?:\.\d+)?)/g, " "))) return null;
    const fichas = fichasDe(limpio);
    const nums = fichas.filter(([t]) => t === "num").map(([, v]) => v), letras = fichas.filter(([t]) => t === "hem").map(([, v]) => v.toUpperCase());
    if (!nums.length || nums.length > 3 || letras.length > 1) return null;
    try {
      let v = grupoAGrados(nums, 180);
      if (letras.length) v = nums[0].trimStart()[0] === "-" ? -Math.abs(v) : Math.abs(v) * HEMISFERIO[letras[0]][1];
      return v;
    } catch (e) {
      if (e instanceof NoValida) return null;
      throw e;
    }
  }

  const formatoDecimal = (lat, lon) => `${lat.toFixed(6)}, ${lon.toFixed(6)}`;

  function gms(valor, positivo, negativo) {
    const letra = valor >= 0 ? positivo : negativo;
    const v = Math.abs(valor);
    let grados = Math.trunc(v);
    let minutos = Math.trunc((v - grados) * 60);
    let segundos = Math.round((v - grados - minutos / 60) * 3600 * 100) / 100;
    if (segundos >= 60) { segundos = 0; minutos += 1; }       // 59.999 s rounds up
    if (minutos >= 60) { minutos = 0; grados += 1; }
    return `${grados}°${minutos}'${segundos}"${letra}`;
  }
  /** 13°5'38.09"N 86°0'7.42"O  (O = oeste, as Google Earth in Spanish). */
  const formatoGMS = (lat, lon) => `${gms(lat, "N", "S")} ${gms(lon, "E", "O")}`;

  window.Coordenadas = { interpretar, valor, formatoDecimal, formatoGMS, enNicaragua, limites: NI };
})();
