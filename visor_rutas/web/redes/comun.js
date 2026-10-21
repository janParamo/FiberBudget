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
  const ROLES = { administrador: "Administrador", editor: "Editor", lector: "Lector", tecnico: "Técnico de campo" };
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

    /** "Entrar a la mufa" (popup, double click or Enter on a mufa of the KMZ): its editor; when the migration does not have it,
     *  offers to create an empty mufa at that point (linked to it by name and position); declining shows its Visio diagram. */
    async entrarMufa(nombre, lat, lon) {
      if (this.disponible && window.EditorMufa) {
        const r = await this.llamar("mufa_existente", { nombre, lat: lat ?? null, lon: lon ?? null });
        if (r.ok && r.mufa) { window.EditorMufa.abrir(r.mufa.id, r.mufa.nombre); return true; }
        const puede = this.estado && this.estado.puede && this.estado.puede.editar && lat != null;
        if (puede && await this.confirmar(`«${nombre}» no está en la red del módulo de redes. ¿Crear una mufa vacía en este punto para armar sus bandejas y empalmes?`, "Crear mufa vacía")) {
          const c = await this.llamar("crear_mufa_kmz", { nombre, lat, lon });
          if (c.ok) { window.EditorMufa.abrir(c.mufa.id, c.mufa.nombre); return true; }
          if (window.visor) window.visor.mensaje(c.error, "error");
          return false;
        }
      }
      if (window.visor) window.visor.abrirDiagramaPorNombre(nombre);
      return false;
    },

    /** Identifies the user (and applies the missing migrations) when the viewer opens. */
    /** Runs `fn` once the module has answered (available or not): Mis lugares loads its data then. */
    cuandoListo(fn) {
      if (this.iniciado) fn(); else (this._espera = this._espera || []).push(fn);
    },

    async iniciar(api) {
      this.api = api;
      const r = await this.llamar("estado");
      this.disponible = !!r.ok;
      if (r.ok && window.Buscador) {          // search box: what was created in the tool (and the clients), not the migrated mufas
        window.Buscador.registrarFuente({
          id: "base", titulo: "Red base (módulo de redes)",
          buscar: async (texto) => {
            const x = await this.llamar("buscar_elementos", { texto });
            if (!x.ok) throw new Error(x.error);
            return x.elementos.map((e) => ({ titulo: e.nombre, sinCoord: e.lat === null, dato: e,
              detalle: `${e.tipo}${e.subtipo ? " " + e.subtipo : ""}${e.proyecto ? " · " + e.proyecto : ""}` }));
          },
          elegir: (item) => {
            const e = item.dato;
            if (e.lat === null || !window.visor) { if (window.visor) window.visor.mensaje(`${e.nombre}: sin coordenadas, no se puede ubicar en el mapa`, "error"); return; }
            window.visor.marcarBuscada(e.lat, e.lon, e.nombre, e.tipo);
          },
        });
      }
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
      this.iniciado = true;
      (this._espera || []).splice(0).forEach((f) => { try { f(); } catch (e) { console.error(e); } });
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
    /** Uploads a big file by parts (1.5 MB each; a whole KMZ weighs 20 MB) to the viewer's API, local or remote: {ok, id} to hand over to the method that
     *  uses it (`subida_id`). `progreso(porcentaje)` is called after each part. */
    async subirArchivo(archivo, progreso) {
      if (!this.api || !this.api.subir_iniciar) return { ok: false, error: "No disponible" };
      try {
        const inicio = await this.api.subir_iniciar(archivo.name, archivo.size);
        if (!inicio.ok) return inicio;
        const PARTE = 1.5 * 1024 * 1024;
        for (let i = 0, n = 0; i < archivo.size; i += PARTE, n++) {
          const bytes = new Uint8Array(await archivo.slice(i, i + PARTE).arrayBuffer());
          let texto = "";
          for (let j = 0; j < bytes.length; j += 0x8000) texto += String.fromCharCode.apply(null, bytes.subarray(j, j + 0x8000));
          const r = await this.api.subir_parte(inicio.id, n, btoa(texto));
          if (!r.ok) return r;
          if (progreso) progreso(Math.min(100, Math.round(((i + PARTE) * 100) / archivo.size)));
        }
        const fin = await this.api.subir_fin(inicio.id);
        return fin.ok ? { ok: true, id: inicio.id } : fin;
      } catch (e) {
        return { ok: false, error: "Error al subir el archivo: " + e };
      }
    },

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
