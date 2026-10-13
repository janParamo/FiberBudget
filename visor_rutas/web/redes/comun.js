/* Módulo de redes (página): utilidades comunes de sus vistas.
 *
 * Redes.llamar(metodo, args) -> api.redes(...) de pywebview, igual en modo local y remoto
 * (en remoto el servidor identifica al usuario por su X-Visor-Key). Las vistas del módulo se
 * registran en window.RedesVistas[nombre] = {mostrar()} y visor.js las abre desde el menú.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ROLES = { administrador: "Administrador", editor: "Editor", lector: "Lector" };
  const ACCIONES = { crear: "Creó", editar: "Editó", eliminar: "Eliminó / desactivó", restaurar: "Restauró / reactivó",
                     duplicar: "Duplicó", identificar: "Primer ingreso" };

  const Redes = {
    api: null, estado: null, esc, ROLES,
    disponible: false,

    async llamar(metodo, args) {
      if (!this.api) return { ok: false, error: "El visor todavía no está listo" };
      try {
        const r = await this.api.redes(metodo, args || {});
        return r || { ok: false, error: "Sin respuesta" };
      } catch (e) {
        return { ok: false, error: "Error al comunicarse con Python: " + e };
      }
    },

    /** Enter / double click on an existing mufa of the map (KMZ, Visio nodes): its migrated editor
     *  (migración Visio, fase 5); if it was not migrated (or the module is off), its Visio diagram. */
    async abrirMufaExistente(nombre, lat, lon) {
      if (this.disponible && window.EditorMufa) {
        const r = await this.llamar("mufa_existente", { nombre, lat: lat ?? null, lon: lon ?? null });
        if (r.ok && r.mufa) { window.EditorMufa.abrir(r.mufa.id, r.mufa.nombre); return true; }
      }
      if (window.visor) window.visor.abrirDiagramaPorNombre(nombre);
      return false;
    },

    /** Identifies the user (and applies the missing migrations) when the viewer opens. */
    async iniciar(api) {
      this.api = api;
      const r = await this.llamar("estado");
      this.disponible = !!r.ok;
      if (r.ok) {
        this.estado = r;
        const u = r.usuario;
        if (window.Menu) {
          Menu.moduloRedes(true);
          Menu.usuario(`<b>${esc(u.nombre)}</b> · ${esc(ROLES[u.rol] || u.rol)}`,
                       `Usuario del módulo de redes: ${u.nombre} (${ROLES[u.rol] || u.rol})`);
        }
      } else if (window.Menu) {
        Menu.moduloRedes(false, r.error || "Base de redes no disponible");
        Menu.usuario("Redes no disponible", r.error || "");
      }
      return r;
    },

    fecha(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      return isNaN(d) ? String(iso) : d.toLocaleString("es-NI", { dateStyle: "short", timeStyle: "short" });
    },

    /** Confirmation dialog; resolves true/false. */
    confirmar(texto, aceptar = "Aceptar") {
      return new Promise((resolver) => {
        const modal = $("modal-confirmar");
        $("conf-texto").textContent = texto;
        $("conf-si").textContent = aceptar;
        modal.hidden = false;
        $("conf-si").focus();
        const fin = (valor) => {
          modal.hidden = true;
          $("conf-si").onclick = $("conf-no").onclick = modal.onkeydown = null;
          resolver(valor);
        };
        $("conf-si").onclick = () => fin(true);
        $("conf-no").onclick = () => fin(false);
        modal.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); fin(false); } };
      });
    },

    /** History window: [{fecha, accion, usuario, cambio}]. */
    mostrarHistorial(titulo, filas) {
      $("hist-titulo").textContent = titulo;
      const valor = (v) => (v === null || v === undefined || v === "" ? "—" : esc(typeof v === "object" ? JSON.stringify(v) : v));
      $("hist-cuerpo").innerHTML = filas.length ? `<ol class="hist-lista">${filas.map((f) => {
        const cambios = f.cambio && typeof f.cambio === "object"
          ? Object.entries(f.cambio).map(([k, v]) => Array.isArray(v) && v.length === 2
            ? `<li><b>${esc(k)}</b>: ${valor(v[0])} → ${valor(v[1])}</li>` : `<li><b>${esc(k)}</b>: ${valor(v)}</li>`).join("")
          : "";
        return `<li><div class="hist-cabeza"><b>${esc(ACCIONES[f.accion] || f.accion)}</b> · ${esc(f.usuario || "sistema")}
          <span class="nota">${esc(this.fecha(f.fecha))}</span></div>${cambios ? `<ul>${cambios}</ul>` : ""}</li>`;
      }).join("")}</ol>` : `<p class="vacio">Sin cambios registrados.</p>`;
      $("modal-historial").hidden = false;
    },

    estadoEn(caja, texto, tipo = "") {
      caja.className = caja.className.replace(/\s*\b(error|ok|cargando)\b/g, "") + (tipo ? " " + tipo : "");
      caja.innerHTML = (tipo === "cargando" ? `<span class="spinner"></span> ` : "") + esc(texto || "");
    },

    // ---- shared by Problemas, Pendientes and Backup (phase 7)
    _proyectos: null,

    /** Projects the user can see (cached; recargar=true asks again). */
    async proyectosVisibles(recargar = false) {
      if (!this._proyectos || recargar) {
        const r = await this.llamar("proyectos", {});
        this._proyectos = r.ok ? r.proyectos.filter((p) => !p.eliminado) : [];
      }
      return this._proyectos;
    },

    /** Fills a <select> with the projects; keeps `valor` selected. */
    async llenarProyectos(select, valor, primera = null) {
      const lista = await this.proyectosVisibles();
      select.innerHTML = (primera ? `<option value="">${esc(primera)}</option>` : "")
        + lista.map((p) => `<option value="${p.id}">${esc(p.nombre)} (${esc(p.codigo)})</option>`).join("");
      if (valor != null) select.value = String(valor);
    },

    /** Options "e:ID" (elements, grouped by type) and "c:ID" (cables) of a project. */
    opcionesVinculo(ref, primera) {
      const grupos = { nodo: "Nodos / OLT", mufa: "Mufas", poste: "Postes", cliente: "Clientes" };
      let html = primera ? `<option value="">${esc(primera)}</option>` : "";
      Object.entries(grupos).forEach(([tipo, titulo]) => {
        const lista = ref.elementos.filter((e) => e.tipo === tipo);
        if (lista.length) html += `<optgroup label="${titulo}">${lista.map((e) => `<option value="e:${e.id}">${esc(e.nombre)}</option>`).join("")}</optgroup>`;
      });
      if (ref.cables.length) html += `<optgroup label="Cables">${ref.cables.map((c) => `<option value="c:${c.id}">${esc(c.nombre)} (${c.hilos == null ? "hilos desconocidos" : `${c.hilos} hilos`})</option>`).join("")}</optgroup>`;
      return html;
    },

    leerArchivo(archivo) {
      return new Promise((resolver, rechazar) => {
        const lector = new FileReader();
        lector.onload = () => resolver(lector.result);
        lector.onerror = () => rechazar(lector.error);
        lector.readAsDataURL(archivo);
      });
    },

    /** Saves base64 data with the Windows save dialog (api.guardar_archivo). */
    async guardarArchivo(nombre, datos, tipo) {
      if (!this.api || !this.api.guardar_archivo) return { ok: false, error: "No disponible" };
      try {
        return (await this.api.guardar_archivo(nombre, datos, tipo)) || { ok: false, error: "Sin respuesta" };
      } catch (e) {
        return { ok: false, error: "Error al guardar: " + e };
      }
    },

    marcarErrores(prefijo, campos, errores) {
      campos.forEach((k) => {
        const campo = $(prefijo + k);
        if (!campo) return;
        const caja = campo.closest(".vp-campo");
        caja.classList.toggle("invalido", !!(errores && errores[k]));
        caja.querySelector("small").textContent = (errores && errores[k]) || "";
      });
    },
  };

  document.addEventListener("click", (e) => { if (e.target.closest("#hist-cerrar")) $("modal-historial").hidden = true; });
  // phase 7 dialogs: [data-tk-cerrar="modal-id"] closes, and Escape closes the topmost one
  const MODALES_TK = ["modal-foto", "modal-restaurar", "modal-problema", "modal-pendiente"];
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tk-cerrar]");
    if (b) $(b.dataset.tkCerrar).hidden = true;
    else if (e.target.id === "modal-foto") $("modal-foto").hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !$("modal-confirmar").hidden || !$("modal-historial").hidden) return;
    const abierto = MODALES_TK.find((id) => $(id) && !$(id).hidden);
    if (abierto) { e.stopPropagation(); $(abierto).hidden = true; }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("modal-historial").hidden) { e.stopPropagation(); $("modal-historial").hidden = true; }
  }, true);

  window.Redes = Redes;
  window.RedesVistas = window.RedesVistas || {};
})();
