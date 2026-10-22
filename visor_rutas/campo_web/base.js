/* App de campo: lo que comparten todas las pantallas: el estado, avisos, paneles y ventanas de diálogo. */
(function () {
  "use strict";
  const C = (window.Campo = window.Campo || {});
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const leer = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
  const guardar = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } };

  C.$ = $; C.esc = esc; C.leer = leer; C.guardar = guardar;

  /* Todo lo que la pantalla sabe: se llena al entrar y al enviar / recibir cambios. */
  C.estado = {
    cfg: { precision_max_m: 10, duplicado_m: 5, foto_max_bytes: 3145728, fotos_por_punto: 8 },
    jornada: null, puntos: [], trazos: [], cola: [],
    filtro: { tipos: null, estados: null, jornadas: null },        // null = todo
  };

  C.ETIQUETA = { poste: "Poste", mufa: "Mufa", reserva: "Reserva", solitaria: "Solitaria", cliente: "Cliente", otro: "Otro", cable: "Cable" };
  C.LETRA = { poste: "P", mufa: "M", reserva: "R", solitaria: "S", cliente: "C", otro: "O", cable: "≈" };
  C.COLOR_TIPO = { poste: "#8d6e63", mufa: "#1e88e5", reserva: "#fb8c00", solitaria: "#8e24aa", cliente: "#43a047", otro: "#546e7a", cable: "#00acc1" };
  C.ESTADO = { cola: "Sin enviar", error: "Con error", pendiente: "Pendiente", editado: "Corregido", aprobado: "Aprobado", rechazado: "Rechazado" };
  C.POSTES = { ideay_tubular: "Ideay tubular", ideay_8_120: "Ideay 8/120", ideay_9_120: "Ideay 9/120", madera: "Madera", concreto: "Concreto" };
  /* «ideay_8_120» -> «Ideay 8/120»; los tipos anteriores se muestran tal cual */
  C.subtipoTexto = (tipo, sub) => (!sub ? "" : tipo === "poste" ? C.POSTES[sub] || sub : sub);

  C.fecha = (v) => {
    const d = v instanceof Date ? v : new Date(v);
    if (isNaN(d)) return "";
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} @ ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };

  async function copiar(texto) {
    try { await navigator.clipboard.writeText(texto); return true; } catch (e) { /* older browsers */ }
    const t = document.createElement("textarea");
    t.value = texto; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { /* ignore */ }
    t.remove();
    return ok;
  }
  C.copiar = copiar;

  /* ---------------------------------------------------------------- avisos */
  let temporizador = null;
  C.aviso = (texto, tipo) => {
    const a = $("aviso");
    a.textContent = texto; a.className = tipo || ""; a.hidden = false;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { a.hidden = true; }, tipo === "malo" ? 7000 : 3500);
  };

  /* ---------------------------------------------------------------- paneles (uno a la vez) */
  const PANELES = ["p-menu", "p-lista", "p-buscar", "p-editor", "p-cable", "p-ajustes", "p-acerca"];
  let abierto = null;
  const oyentes = [];
  C.panel = {
    abrir(id) {
      PANELES.forEach((p) => { const e = $(p); if (e) e.hidden = p !== id; });
      abierto = id;
      document.body.dataset.panel = id || "";
      C.tarjeta && C.tarjeta.ocultar();
      oyentes.forEach((f) => f(id));
    },
    cerrar() { this.abrir(null); },
    actual: () => abierto,
    cuandoCambie: (f) => oyentes.push(f),
  };

  /* ---------------------------------------------------------------- diálogos */
  let resolver = null;
  function cerrarDialogo(valor) {
    $("dialogo").hidden = true;
    const r = resolver; resolver = null;
    if (r) r(valor === undefined ? null : valor);
  }

  /* {titulo, cuerpo (HTML), botones: [{texto, valor, primario}], alMostrar(raiz), leer(raiz) -> valor del botón (puede ser un objeto)} -> el valor del botón tocado, o null */
  function mostrar(op) {
    if (resolver) cerrarDialogo(null);
    $("dlg-titulo").textContent = op.titulo || "";
    $("dlg-titulo").hidden = !op.titulo;
    $("dlg-cuerpo").innerHTML = op.cuerpo || "";
    const botones = op.botones || [];
    $("dlg-botones").innerHTML = botones.map((b, i) => `<button type="button" class="dlg-btn${b.primario ? " primario" : ""}" data-i="${i}">${esc(b.texto)}</button>`).join("");
    $("dialogo").hidden = false;
    C.iconos.poner($("dialogo"));
    return new Promise((ok) => {
      resolver = ok;
      $("dialogo").onclick = (e) => {
        const b = e.target.closest("[data-i]");
        if (b) {
          const def = botones[Number(b.dataset.i)];
          cerrarDialogo(op.leer && def.valor === "leer" ? op.leer($("dlg-cuerpo")) : def.valor);
        } else if (e.target.closest("[data-dlg]")) cerrarDialogo(e.target.closest("[data-dlg]").dataset.dlg === "" ? "" : JSON.parse(e.target.closest("[data-dlg]").dataset.dlg));
        else if (e.target === $("dialogo")) cerrarDialogo(null);
      };
      $("dialogo").onkeydown = (e) => { if (e.key === "Escape") cerrarDialogo(null); };
      if (op.alMostrar) op.alMostrar($("dlg-cuerpo"));
      const primero = $("dlg-cuerpo").querySelector("input,textarea,select");
      if (primero) primero.focus();
    });
  }

  C.dialogo = {
    mostrar,
    cerrar: () => cerrarDialogo(null),
    abierto: () => !$("dialogo").hidden,
    /* lista de opciones (cada una cierra el diálogo con su valor) + Cancelar */
    opciones(titulo, lista, actual) {
      const cuerpo = `<ul class="dlg-lista">${lista.map((o) => `<li><button type="button" class="dlg-opcion${o.valor === actual ? " actual" : ""}" data-dlg='${esc(JSON.stringify(o.valor))}'>
        ${o.icono ? C.iconos.svg(o.icono) : ""}<span><b>${esc(o.texto)}</b>${o.detalle ? `<small>${esc(o.detalle)}</small>` : ""}</span></button></li>`).join("")}</ul>`;
      return mostrar({ titulo, cuerpo, botones: [{ texto: "Cancelar", valor: null }] });
    },
    /* Sí / No / ... : devuelve el valor del botón tocado */
    confirmar(titulo, texto, botones) {
      return mostrar({ titulo, cuerpo: texto ? `<p>${esc(texto)}</p>` : "", botones: botones || [{ texto: "Sí", valor: true, primario: true }, { texto: "No", valor: false }] });
    },
    texto(titulo, inicial, placeholder, maximo) {
      return mostrar({ titulo, cuerpo: `<input id="dlg-texto" type="text" maxlength="${maximo || 160}" value="${esc(inicial || "")}" placeholder="${esc(placeholder || "")}" autocomplete="off">`,
        botones: [{ texto: "Cancelar", valor: null }, { texto: "Aceptar", valor: "leer", primario: true }], leer: (r) => r.querySelector("#dlg-texto").value.trim() });
    },
    numero(titulo, inicial, minimo, maximo, unidad) {
      return mostrar({ titulo, cuerpo: `<div class="dlg-numero"><input id="dlg-num" type="number" inputmode="decimal" min="${minimo}" max="${maximo}" value="${inicial}"><span>${esc(unidad || "")}</span></div>
        <p class="nota">Entre ${minimo} y ${maximo}${unidad ? " " + esc(unidad) : ""}.</p>`,
        botones: [{ texto: "Cancelar", valor: null }, { texto: "Aceptar", valor: "leer", primario: true }], leer: (r) => { const v = Number(r.querySelector("#dlg-num").value); return isNaN(v) ? null : v; } });
    },
  };
})();
