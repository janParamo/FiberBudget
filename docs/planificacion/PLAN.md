# Planificación de cuadrillas

Tres piezas que comparten el servicio y la base de redes (`Presupuesto_visio`):

| Pieza | Quién la usa | Qué hace |
|---|---|---|
| **Visor de rutas** (ya existe) | quien hace presupuestos | genera el presupuesto y lo **lleva a planificación** (botón por hacer: fase 4) |
| **Planificación** (app aparte, `/planificacion/`) | planificación (rol editor / administrador) | administra las cuadrillas, asigna las actividades, ordena la cola, monitorea el avance y los tiempos |
| **Cuadrilla** (app aparte, PWA `/cuadrilla/`) | los técnicos de cada cuadrilla (clave de `CAMPO_API_KEYS`) | ve su cola, empieza la actividad, marca los puntos de control, pausa y termina; manda su ubicación |

## Cuadrillas de partida
Tamos 1 y 2, Telenic 1 y 2 (servicios tercerizados) e IDEAY 1 y 2 (propias). Se pueden crear más y desactivar.
Un técnico (rol «tecnico») pertenece a **una** cuadrilla; la pone un administrador.

## Actividad
Una instalación: nace de un presupuesto del visor (o de Kayako —más adelante— o a mano) con ticket, cliente, código, contacto (nombre y teléfono),
coordenada, el Excel del presupuesto y su resumen. Cada actividad tiene estado, cuadrilla, lugar en la cola, prioridad, puntos de control e historial.

### Estados
`inactivo` (con presupuesto, sin cuadrilla) → `asignado` (en la cola de una cuadrilla) → `en_revision` (se revisa si se hará) → `en_curso` (la cuadrilla la
ejecuta) → `terminado`. Además `pausado` (con motivo), `no_viable` (la revisión dijo que no; con motivo) y `cancelado`.
Una cuadrilla tiene **una** actividad en curso a la vez; las demás esperan en la cola. La cuadrilla hace: revisar, empezar, pausar, reanudar, terminar o
decir «no viable». Planificación hace todo lo demás (asignar, quitar de la cola, cancelar, reactivar) y puede **dar por iniciada** una actividad si la
cuadrilla se olvidó (queda registrado: `iniciada_por = planificacion`).

### Puntos de control (en orden)
Llegó al lugar · Inspección hecha · Levantado de postes (opcional) · Acometida del cliente · Instalación de los equipos del cliente · Fusión de hilos en las
mufas. Estado de cada uno: pendiente / en proceso / hecho, con quién, cuándo y (si la app la manda) dónde. No se puede terminar con puntos obligatorios
sin marcar (planificación puede forzarlo). El avance es lo marcado sobre el total.

### Tiempos
- **Espera**: desde que se asignó hasta que empezó (corre mientras esté asignado o en revisión; se marca una alerta pasados 60 minutos).
- **Ejecución**: desde que empezó hasta que terminó, sin descontar de más: lo pausado no cuenta.
- El tablero muestra los promedios de ambos y las actividades asignadas que nadie ha empezado.

### Ubicación
Es la que ya manda la app de campo (una fila por técnico, la última); la pantalla de planificación muestra la de cada cuadrilla (la más reciente de sus miembros).

## Chat (al final)
La tabla `plan_mensajes` ya existe (un hilo por actividad, de la cuadrilla a planificación y al revés); la pantalla se hace de último.

## Fases
1. **Hecha** — base (`020_planificacion.sql`), lógica (`visor_rutas/redes/planificacion.py`) y API REST (`/visor/planificacion/*`), con pruebas (`test_planificacion.py`).
2. **Hecha** — **App de planificación** (`/planificacion/`, `visor_rutas/planificacion_web/`): se entra con la clave del visor (rol editor o administrador). Tablero con el conteo por estado, espera y ejecución medias y alertas de actividades sin iniciar; cuadrillas con su carga y su última ubicación; lista de actividades con filtros (estado, cuadrilla, texto), marcar varias y asignarlas; detalle con contacto, teléfono, coordenada, tiempos que corren en pantalla, acciones de estado (dar por iniciada, pausar, terminar, no viable, cancelar, reactivar, reasignar), puntos de control y línea de tiempo; mapa con las actividades y las cuadrillas; pestaña de cuadrillas (crear, activar / desactivar). Se actualiza sola cada 15 s. **Cola y miembros** (pestaña Cuadrillas): cada cuadrilla muestra su cola en el orden en que la tomará y se reordena arrastrando una fila o con las flechas ▲ ▼ (`/cuadrillas/{id}/cola`); y sus miembros, con «Agregar técnico» (lista de los usuarios con rol técnico, con la cuadrilla donde están hoy; un técnico es de una sola cuadrilla) y ✕ para quitarlo. Agregar y quitar miembros lo hace solo un administrador. La lista no se redibuja mientras se arrastra o se elige un técnico.
2b. **Hecha** — **Ventana «Planificación» en el visor de rutas**: opción **Planificación** del menú lateral que muestra la app de planificación dentro del visor (un marco con `/planificacion/` del servicio; la clave va en la dirección y la app la guarda). En modo servidor usa la dirección y la clave de Configuración; en modo local, el servicio de este equipo (`API_HOST` / `API_PORT`, lo abre `start_service.bat`) y la clave del `.env` (`VISOR_API_KEYS`) de este usuario de Windows. Si el servicio no está en marcha, la ventana lo dice. También se puede abrir directo en el navegador: `http://<servidor>/planificacion/`.
3. **Hecha** — **App de la cuadrilla** (`/cuadrilla/`, PWA, `visor_rutas/cuadrilla_web/`): se entra con la clave de técnico (`CAMPO_API_KEYS`). Muestra la actividad de ahora y la cola con ticket, contacto, teléfono (toca para llamar), coordenada («Cómo llegar» abre el mapa del teléfono) y los dos tiempos corriendo; el técnico empieza la revisión o el trabajo, marca los puntos de control (guarda dónde los marcó), pausa con motivo, reanuda, dice «no es viable» o termina (no deja terminar con puntos obligatorios sin marcar). Manda su ubicación cada 20 s (la usa planificación). Se actualiza sola cada 15 s y se puede instalar como app; sin señal abre y muestra lo último cargado, pero las acciones piden conexión. Como la app de campo, el GPS necesita https.
4. **Hecha** — **Del visor a planificación**: botón **«Llevar a planificación»** en el resultado de un presupuesto, y en la ventana «Convertir a PDF…» (Historial) para lo marcado: presupuestos sueltos o grupos de una masiva (aprobados / desaprobados). Crea una actividad **inactiva** por cada Excel con lo que lee de él: cliente (celda de la segunda hoja), ticket, código, contacto, teléfono y coordenada del cliente (primera página) y el total; guarda de qué Excel viene. Si el ticket y el cliente ya están en planificación, lo dice y no repite. Método `plan_llevar` (modo local con el usuario de Windows, que debe ser editor o administrador; modo servidor con la clave del visor).
5. **Tiempo real**: avisos al instante (el trigger `NOTIFY 'planificacion'` ya está) en las dos apps.
6. **Chat** cuadrilla ↔ planificación.
7. **Kayako** como origen de actividades (cuando se decida).

## Decisiones tomadas por defecto (cambiables)
- Las dos apps viven en el mismo servicio y la misma base; no hay un servidor nuevo.
- Se usan las claves que ya existen: del visor para planificación y de técnico (`CAMPO_API_KEYS`) para las cuadrillas.
- Estados extra a los tuyos: `en_revision` se queda entre asignado y en curso; se agregan `pausado`, `no_viable` y `cancelado`.
