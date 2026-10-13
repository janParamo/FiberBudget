/* Vista "Usuarios" del módulo de redes: lista, alta/edición (administradores), desactivar /
 * reactivar (borrado lógico) e historial de cada usuario. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const CAMPOS = ["nombre", "correo", "rol", "persona_visor", "usuario_windows"];
  let lista = [];
  let puedeAdministrar = false;
  let editando = null;              // user being edited (null = new)
  let conectado = false;

  const esc = (v) => Redes.esc(v);
  const estado = (texto, tipo) => Redes.estadoEn($("us-estado"), texto, tipo);

  async function cargar() {
    estado("Cargando usuarios…", "cargando");
    const r = await Redes.llamar("usuarios");
    if (!r.ok) { estado(r.error, "error"); $("us-filas").innerHTML = ""; return; }
    lista = r.usuarios;
    puedeAdministrar = !!r.puede_administrar;
    $("us-nuevo").hidden = !puedeAdministrar;
    const yo = Redes.estado && Redes.estado.usuario;
    $("us-yo").textContent = yo ? `Usted: ${yo.nombre} (${Redes.ROLES[yo.rol] || yo.rol})` +
      (puedeAdministrar ? "" : " · solo un administrador puede cambiar usuarios") : "";
    estado(`${lista.length} usuario${lista.length === 1 ? "" : "s"}`);
    pintar();
  }

  function pintar() {
    $("us-filas").innerHTML = lista.map((u) => `<tr class="${u.activo ? "" : "inactivo"}">
      <td><b>${esc(u.nombre)}</b></td>
      <td><span class="rol rol-${esc(u.rol)}">${esc(Redes.ROLES[u.rol] || u.rol)}</span></td>
      <td>${esc(u.correo || "")}</td><td>${esc(u.persona_visor || "")}</td><td>${esc(u.usuario_windows || "")}</td>
      <td>${u.activo ? "Activo" : `Desactivado <span class="nota">${esc(Redes.fecha(u.borrado_en))}</span>`}</td>
      <td class="acciones">${puedeAdministrar ? `
        <button type="button" class="btn-icono" data-us-editar="${u.id}" title="Editar datos"><svg><use href="#i-lapiz"/></svg></button>
        <button type="button" class="btn-icono" data-us-historial="${u.id}" title="Historial de cambios"><svg><use href="#i-reloj"/></svg></button>
        <button type="button" class="btn btn-chico" data-us-estado="${u.id}">${u.activo ? "Desactivar" : "Reactivar"}</button>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="7" class="vacio">Sin usuarios</td></tr>`;
  }

  function abrirFormulario(usuario) {
    editando = usuario || null;
    $("us-modal-titulo").textContent = usuario ? `Editar usuario: ${usuario.nombre}` : "Nuevo usuario";
    CAMPOS.forEach((k) => { $("us-" + k).value = (usuario && usuario[k]) || (k === "rol" ? "lector" : ""); });
    Redes.marcarErrores("us-", CAMPOS, null);
    Redes.estadoEn($("us-form-estado"), "");
    $("modal-usuario").hidden = false;
    $("us-nombre").focus();
  }
  function cerrarFormulario() { $("modal-usuario").hidden = true; editando = null; }

  async function guardar(ev) {
    ev.preventDefault();
    const datos = {};
    CAMPOS.forEach((k) => { datos[k] = $("us-" + k).value; });
    if (editando) Object.assign(datos, { id: editando.id, version: editando.version });
    Redes.marcarErrores("us-", CAMPOS, null);
    Redes.estadoEn($("us-form-estado"), "Guardando…", "cargando");
    $("us-guardar").disabled = true;
    const r = await Redes.llamar("guardar_usuario", { datos });
    $("us-guardar").disabled = false;
    if (!r.ok) {
      Redes.marcarErrores("us-", CAMPOS, r.errores);
      Redes.estadoEn($("us-form-estado"), r.conflicto ? `${r.error} Cierre y presione Recargar.` : r.error, "error");
      return;
    }
    cerrarFormulario();
    await cargar();
    estado(`Usuario ${r.usuario.nombre} guardado`, "ok");
    if (Redes.estado && r.usuario.id === Redes.estado.usuario.id) Redes.iniciar(Redes.api);   // my own role changed
  }

  async function cambiarEstado(usuario) {
    const activar = !usuario.activo;
    const ok = await Redes.confirmar(activar ? `¿Reactivar a ${usuario.nombre}?`
      : `¿Desactivar a ${usuario.nombre}? No podrá usar el módulo de redes hasta que lo reactive (no se borra nada).`,
    activar ? "Reactivar" : "Desactivar");
    if (!ok) return;
    const r = await Redes.llamar("estado_usuario", { id: usuario.id, version: usuario.version, activo: activar });
    if (!r.ok) { estado(r.error, "error"); return; }
    await cargar();
    estado(`${usuario.nombre} ${activar ? "reactivado" : "desactivado"}`, "ok");
  }

  async function historial(usuario) {
    const r = await Redes.llamar("historial_usuario", { id: usuario.id });
    if (!r.ok) { estado(r.error, "error"); return; }
    Redes.mostrarHistorial(`Historial: ${usuario.nombre}`, r.historial);
  }

  function conectar() {
    if (conectado) return;
    conectado = true;
    $("us-recargar").addEventListener("click", cargar);
    $("us-nuevo").addEventListener("click", () => abrirFormulario(null));
    $("us-form").addEventListener("submit", guardar);
    $("us-cancelar").addEventListener("click", cerrarFormulario);
    $("us-cerrar").addEventListener("click", cerrarFormulario);
    $("modal-usuario").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); cerrarFormulario(); } });
    $("us-filas").addEventListener("click", (e) => {
      const boton = e.target.closest("[data-us-editar], [data-us-historial], [data-us-estado]");
      if (!boton) return;
      const id = Number(boton.dataset.usEditar || boton.dataset.usHistorial || boton.dataset.usEstado);
      const usuario = lista.find((u) => u.id === id);
      if (!usuario) return;
      if (boton.dataset.usEditar) abrirFormulario(usuario);
      else if (boton.dataset.usHistorial) historial(usuario);
      else cambiarEstado(usuario);
    });
  }

  window.RedesVistas = window.RedesVistas || {};
  window.RedesVistas.usuarios = { mostrar() { conectar(); cargar(); } };
})();
