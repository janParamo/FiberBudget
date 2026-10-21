/* Splitters leídos de los diagramas, por parada de la ruta de fusión (visor_rutas/splitters_diagrama.py).
 * html(parada): el bloque «Splitters» de la parada. abrir(splitter, alGuardar): la ventana donde una persona confirma la clase y los puertos
 * libres / ocupados que ve en el diagrama; se guarda en la red (Redes.llamar «confirmar_splitter») y gana sobre lo que se leyó solo. */
(function () {
  "use strict";
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CLASES = { secundario: "Secundario", principal: "Principal", por_confirmar: "Por confirmar" };
  const FUENTES = { color: "por color", palabra: "por la palabra", confirmado: "confirmado", sin_dato: "sin dato" };

  function resumen(s) {
    const libres = s.libres ? `${s.libres} libre${s.libres === 1 ? "" : "s"}` : (s.desconocidos ? "puertos por confirmar" : "sin libres");
    return `${CLASES[s.clase] || s.clase}${s.ratio ? " " + s.ratio : ""} · ${libres}`;
  }

  function html(parada) {
    const lista = parada.splitters_diagrama || [];
    if (!lista.length) return "";
    const filas = lista.map((s, i) => `<li class="splitter-fila">
        <span class="insignia splitter-${esc(s.clase)}" title="Clase ${esc(FUENTES[s.clase_fuente] || "")}">${esc(CLASES[s.clase] || s.clase)}</span>
        <span class="splitter-texto" title="${esc(s.etiqueta)}">${esc(resumen(s))}${s.confirmado ? ` <span class="nota">(confirmado)</span>` : ""}</span>
        <button type="button" class="btn btn-chico" data-splitter="${parada.orden}:${i}">${s.confirmado ? "Ver" : "Confirmar"}</button></li>`).join("");
    return `<div class="bloque-splitters"><div class="nota">Splitters del diagrama (${lista.length})</div><ul class="lista-splitters">${filas}</ul></div>`;
  }

  function abrir(s, alGuardar) {
    const fondo = document.createElement("div");
    fondo.className = "modal splitter-modal";
    const puertos = Object.keys(s.puertos || {});
    const estado = {};
    puertos.forEach((n) => { estado[n] = s.puertos[n].estado; });
    let clase = s.clase_fuente === "confirmado" || s.clase !== "por_confirmar" ? s.clase : "";
    const opcion = (n, valor, texto) => `<label><input type="radio" name="p${n}" value="${valor}" ${estado[n] === valor ? "checked" : ""}> ${texto}</label>`;
    fondo.innerHTML = `<div class="modal-caja splitter-caja"><div class="modal-cabecera"><h2>${esc(s.etiqueta || "Splitter")}</h2>
        <div class="modal-acciones"><button type="button" class="btn btn-chico" data-sp="cerrar">Cerrar</button></div></div>
      <div class="splitter-cuerpo">
        <p class="nota">Abra el diagrama (${esc(s.archivo || "")}) y marque lo que ve. Lo confirmado se guarda y se usa en las próximas rutas.</p>
        <label class="ef-linea">Clase <select data-sp="clase"><option value="">Por confirmar</option>
          <option value="secundario" ${clase === "secundario" ? "selected" : ""}>Secundario (morado)</option>
          <option value="principal" ${clase === "principal" ? "selected" : ""}>Principal (dorado)</option></select></label>
        ${puertos.length ? `<table class="splitter-puertos"><tbody>${puertos.map((n) => `<tr><th>${esc(n)}</th>
          <td>${opcion(n, "libre", "Libre")}${opcion(n, "ocupado", "Ocupado")}${opcion(n, "desconocido", "No sé")}</td>
          <td class="nota">${esc((s.puertos[n].cliente) || "")}</td></tr>`).join("")}</tbody></table>`
          : `<p class="nota">No se encontró el cuadro de números de puerto de este splitter.</p>`}
        <p class="splitter-error" role="alert" hidden></p>
        <div class="splitter-botones"><button type="button" class="btn btn-primario" data-sp="guardar">Guardar</button>
          ${s.confirmado ? `<button type="button" class="btn" data-sp="quitar">Quitar lo confirmado</button>` : ""}</div>
      </div></div>`;
    document.body.appendChild(fondo);
    const cerrar = () => fondo.remove();
    const error = (t) => { const e = fondo.querySelector(".splitter-error"); e.textContent = t; e.hidden = !t; };
    fondo.addEventListener("change", (e) => {
      const r = e.target.closest("input[type=radio]");
      if (r) estado[r.name.slice(1)] = r.value;
    });
    fondo.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-sp]");
      if (!b) return;
      if (b.dataset.sp === "cerrar") { cerrar(); return; }
      if (!window.Redes || !s.id) { error("La red no está disponible: no se puede guardar"); return; }
      b.disabled = true;
      let r;
      if (b.dataset.sp === "quitar") {
        r = await window.Redes.llamar("quitar_confirmacion_splitter", { id: s.id, version: s.version });
      } else {
        const marcados = {};
        Object.keys(estado).forEach((n) => { if (estado[n] === "libre" || estado[n] === "ocupado") marcados[n] = estado[n]; });
        const args = { id: s.id, version: s.version, clase: fondo.querySelector("[data-sp=clase]").value || null };
        if (Object.keys(marcados).length) args.puertos = marcados;
        r = await window.Redes.llamar("confirmar_splitter", args);
      }
      b.disabled = false;
      if (!r || !r.ok) { error((r && r.error) || "No se pudo guardar"); return; }
      cerrar();
      alGuardar(r);
    });
    return fondo;
  }

  /* The splitter as the page shows it once `confirmado` (what the server returned) is on top of the automatic reading. */
  function aplicar(s, r) {
    const conf = r.confirmado;
    s.version = r.version;
    s.confirmado = !!conf;
    if (conf && (conf.clase === "secundario" || conf.clase === "principal")) { s.clase = conf.clase; s.clase_fuente = "confirmado"; }
    Object.keys(s.puertos || {}).forEach((n) => {
      const c = conf && conf.puertos && conf.puertos[n];
      if (c) s.puertos[n] = Object.assign({}, s.puertos[n], { estado: c, fuente: "confirmado" });
      // Confirmation removed: what was confirmed goes back to «por confirmar» until the route is generated again (the reading is re-done then).
      else if (!conf && s.puertos[n].fuente === "confirmado") s.puertos[n] = Object.assign({}, s.puertos[n], { estado: "desconocido", fuente: "sin_dato" });
    });
    s.libres = Object.values(s.puertos || {}).filter((p) => p.estado === "libre").length;
    s.desconocidos = Object.values(s.puertos || {}).filter((p) => p.estado === "desconocido").length;
    return s;
  }

  window.SplitterPuertos = { html, abrir, aplicar, resumen };
})();
