# Bitácora 2026-10-12

Contexto anterior: `../2026-10-09/LEEME.md`, con las fases 1 a 5 del módulo de redes. Las fases 1 a 4 están aprobadas. La fase 5 (trazado de hilo) quedó terminada; Jan no la aprobó explícitamente, pero pidió seguir con la "5.1".

## Pedido de hoy: "fase 5.1"

La especificación (`docs/modulo_redes/ESPECIFICACION.md`) no tiene una fase 5.1. Claude preguntó y Jan aclaró: **"Realiza la sección 5.1 Representación y espera mi OK para avanzar a la siguiente"**. Se refiere a la sección 5.1 del editor de mufa.

## Sección 5.1 "Representación": terminada, espera el OK de Jan

**Cotejo con la especificación y las imágenes 04, 05 y 06:**

| Punto de 5.1 | Estado |
|---|---|
| Ventana grande maximizable, cuadrícula, zoom, desplazamiento | ya estaba (fase 4) |
| Barra vertical por buffer, hilos numerados en círculos con colores TIA-598 | ya estaba |
| Color del buffer según TIA-598 | ya estaba |
| 8 o 12 hilos por buffer como dato del cable (los colores se repiten) | ya estaba |
| Encabezado "Cable \| origen \| destino \| hilos" | se veía cortado ("…MF…"); **arreglado** |
| Tooltip de cable o hilo: nombre, tipo, hilos, metraje con detalle (imagen 06), estado y conexión en cada extremo | estaba incompleto; **completado** |

**Qué se cambió** (solo la página: `web/redes/editor_mufa.js` y `web/redes/redes.css`):
- **Encabezado del cable:** a 14 px y hasta 3 líneas, con la zona del nombre más ancha (200 px). Se lee completo.
- **Tooltip del cable:**
  - aparece también sobre las **barras de buffer** y el encabezado, como en la imagen 06; antes solo sobre el marco;
  - trae clase, tipo, hilos y buffers, origen → destino, si llega o sale de la mufa, el **estado de sus hilos** (por ejemplo, "46 activos · 1 en fibra oscura · 1 dañado") y cuántos hilos están conectados aquí y en el otro extremo;
  - termina con **METRAJE = N m** y su detalle en tabla: distancia lineal, contingencia, salida de nodo, y N° de reservas × mufa, × tendido y × cruce, con el formato "cantidad (und × m) = total".
- **Tooltip del hilo:** color y buffer, estado, conexión aquí y en el otro extremo (o "llega al cliente X"), los datos del cable y el mismo detalle de metraje.
- Los tooltips se mantienen dentro del lienzo: si no caben abajo, salen arriba del mouse.

**Verificación:**
- **Pruebas:** 292 pasan; no hubo cambios en el backend.
- **Edge headless:** al pasar el mouse por la barra del buffer 2 sale el tooltip del cable con el metraje 1,063 m = 812.4 + 70 (2 × 35) + 180 (3 × 60). El hilo 6 dañado muestra "Estado: Dañado". El hilo 1 del drop muestra "Aquí: Splitter 1 salida 1".
- El arnés de la fase 4 sigue pasando (arrastre real y navegación), sin errores de JavaScript.
- **`VisorRutas.zip`:** regenerado (24.7 MB).

**Pendiente de verificar por Jan:** pasar el mouse por un cable y un hilo en la ventana real.

## Secciones 5.2 "Operaciones" y 5.3 "Navegación entre mufas": terminadas, esperan el OK de Jan

Jan: "pasar al 5.2 y al punto 5.3 Navegación entre mufas si todavía no lo has hecho".

**Cotejo de 5.2 (Operaciones):** ya cumplía todo desde la fase 4, sin cambios:
- conectar arrastrando de hilo a hilo (fusión) o a la entrada de un splitter, con línea ortogonal del color del hilo;
- splitters 1x2 a 1x32, balanceados o desbalanceados, con nombre "Splitter 1 (01x02 RC)" y salidas que van a hilos o conectores;
- conectores, estado de cada hilo, eliminar conexión, splitter o conector;
- reordenar (*Ordenar*), alinear y distribuir;
- notas con formato (negrita, tipo de letra, listas), nombre obligatorio, barras arriba y abajo, Aplicar y Guardar/Cerrar, y el botón QR preparado.

**Cotejo de 5.3 (Navegación) con las imágenes 07 y 08:**
- Ya estaban: Enter o doble clic para abrir la otra mufa, migas de pan, y "Seguir hilo" (fase 5).
- **Faltaba:** "cada destino conectado se muestra como una caja con su nombre **al final del hilo**". Solo había una caja por cable.

**Qué se hizo** (solo `web/redes/editor_mufa.js`):
- **Caja de destino por hilo:** cada hilo en uso (conectado aquí o en el otro extremo) lleva al final una caja con su color.
  - El texto es el destino y lo que hay allá: «→ FAT 1 · Conector A (entrada)», «← Nodo Central · sin conectar allá», o el cliente.
  - Sale en cursiva si solo está conectado allá.
  - Con doble clic, o con el hilo seleccionado y Enter, se abre la otra mufa.
- **Tooltip de los puertos** de splitter y conector: a qué están conectados y hacia dónde sigue el hilo, o "Libre".
- **Altura del cable** +36 px, para que la caja «→ destino» del cable no tape las cajas de los últimos hilos.
- "1 buffer" en singular.

**Verificación:**
- **Edge headless:**
  - sin conexiones, solo el hilo usado en FAT 1 tiene caja;
  - con splitter y conexiones salen las dos cajas esperadas;
  - los tooltips de salida 1, salida 2 (libre) y entrada son correctos;
  - doble clic en la caja del drop abre FAT 1, donde se ve «← MF Norte · Splitter 1 · salida 1»;
  - Enter con el hilo seleccionado vuelve a MF Norte;
  - sin errores de JavaScript.
- Los arneses de las fases 4 y 5 siguen pasando.
- **Pruebas:** 292 pasan.
- **`VisorRutas.zip`:** regenerado.

**Pendiente de verificar por Jan:** en la ventana real, ver las cajas por hilo y navegar con doble clic.

## Fase 6 (diagrama lógico de red): terminada, espera el OK de Jan

Jan: "Ahora sigue con la fase 6", lo que aprueba las secciones 5.1 a 5.3.

**Estado:**
- **Pruebas:** **300** pasan (+8 en `Pruebas/test_redes_diagrama.py`).
- **Migración** `006_diagramas.sql` **aplicada en `Presupuesto_visio`** (09:01).
- **`VisorRutas.zip`:** regenerado y verificado (24.7 MB).
- **README:** sección "Diagrama lógico de red".

**Qué se hizo:**
- **Base:** tabla `redes.diagramas_logicos` con proyecto, título, elemento o splitter de inicio, dirección, incluir clientes, versión y borrado lógico.
- **Backend** `visor_rutas/redes/diagrama.py`, con los métodos `diagramas`, `guardar_diagrama`, `eliminar_diagrama` y `generar_diagrama`:
  - genera de las conexiones guardadas: desde el inicio sigue los cables que **salen** de cada caja (origen → destino), sin volver a una caja ya puesta;
  - por caja: símbolo (OLT, SC, FDT, FAT), splitters, conectores usados, líneas internas agregadas (×N hilos) y clientes no incluidos;
  - por cable: hilos, usados y color por capacidad;
  - desde un splitter solo sigue los cables que salen de él.
- **Colores por capacidad:** configurables en `business_rules.yaml`, sección nueva `diagrama_logico.colores_capacidad` (144 rojo, 96 naranja, 72 azul, 48 morado, 24 verde, 12 aqua). No toca el presupuesto.
- **Duplicar:** el proyecto copia también los diagramas guardados (`red.copiar`).
- **Página** `web/redes/diagrama.js` (Konva):
  - formulario con título automático, tabla de guardados, árbol a la derecha o a la izquierda;
  - leyenda FTTH y título dentro del dibujo, para que salgan en la exportación;
  - zoom, desplazamiento, *Ajustar*, clic en una caja abre su editor de mufa, *Exportar PNG / PDF*.
- **Accesos:** botón en la tarjeta del proyecto (ícono nuevo), en la franja del editor de mapa y en el editor de mufa (genera desde esa mufa).
- **`ventana_web.Api.guardar_imagen`:** guarda el PNG de la página como PNG, o como PDF con Pillow, mediante el diálogo de Windows. Limpia del nombre los caracteres que Windows no acepta ("|" pasa a "_"). Funciona igual en el `.exe`.

**Verificación:**
- Con salida **real** de `generar` (base temporal), el **caso de aceptación** funcionó: se generó desde MF Norte y se exportó a **PDF**. El PDF tiene título, cajas, splitter, conector, cables coloreados, derivaciones y leyenda.
- Desde el nodo, con clientes (5 cajas y 4 cables), y desde el splitter hacia la izquierda: bien.
- Clic en FAT 1 abre su editor.
- Los botones del editor de mufa y del mapa abren el diagrama.
- Los arneses de las fases 3, 4, 5 y 5.3 siguen pasando, sin errores de JavaScript.

**Decisiones de Claude:**
- **"Hacia adelante"** = la dirección en que se dibujaron los cables (origen → destino). Desde una mufa intermedia no se dibuja hacia el nodo.
- **"Caja"** en la tabla = la mufa del splitter de inicio, o el propio elemento.
- **Derivación** = punto morado en cada salida de una caja que reparte a 2 o más cables. La especificación lo pide en la leyenda sin decir dónde va.
- **El PDF** es de una página del tamaño del dibujo, a 150 ppp; no se ajusta a carta ni A4.
- **Sin opción de menú propia:** la especificación no la pone en el menú; se abre desde el proyecto.

**Pendiente de verificar por Jan** (en la ventana real):
- abrir el diagrama de un proyecto con datos reales;
- exportar a PDF y abrirlo;
- revisar si los colores por capacidad y los símbolos son los que usan.

## Fase 7 (Problemas, Pendientes y Backup): terminada, espera el OK de Jan

Jan: "Procede con la fase 7", lo que aprueba la fase 6.

**Estado:**
- **Pruebas:** **307** pasan (+7 en `Pruebas/test_redes_fase7.py`).
- **Migración** `007_problemas_pendientes.sql` **aplicada en `Presupuesto_visio`** (13:36).
- **`VisorRutas.zip`:** regenerado y verificado (24.7 MB).
- **README:** secciones Problemas, Pendientes y Backup.
- **Primer respaldo real** creado en `respaldos_redes\` con el `.json` y el `.sql` de `pg_dump` (PostgreSQL 18). El proyecto real RLR-02 se exportó bien a KMZ y GeoJSON.

**Qué se hizo:**
- **Base:** tablas `problemas` (ligado a un elemento o cable; severidad, estado, fecha de cierre), `problema_fotos` (imagen y miniatura) y `pendientes` (responsable, fecha límite, estado, fecha de hecho).
- **Backend** (14 métodos nuevos en `api.py`):
  - `problemas.py`: lista con filtros, guardar con fotos (hasta 6, validadas con la misma función de la imagen de proyecto), foto completa, eliminar, historial, y `referencias_proyecto` (elementos, cables y usuarios del proyecto para los formularios);
  - `pendientes.py`: lista con filtros (responsable "yo", vencidos), guardar, eliminar, historial;
  - `respaldo.py`: crear, listar, restaurar como copia, descargar y exportar a KMZ o GeoJSON.
- **Respaldo:** un `.json` con todos los proyectos y todo su contenido, tomado en una transacción REPEATABLE READ, más el `.sql` de `pg_dump` del esquema `redes`.
  - **Restaurar:** un proyecto del `.json` vuelve como proyecto nuevo `-R1`, `-R2`…, con todos sus ids remapeados.
  - Los usuarios se emparejan por persona del visor, usuario de Windows o nombre.
- **KMZ:** hecho a mano con estilos e íconos PNG dibujados con Pillow dentro del KMZ, así se abre sin internet. Se validó con un lector XML.
- **Página:**
  - vistas `problemas.js`, `pendientes.js` y `respaldos.js`; el menú ya habilita Problemas, Pendientes y Backup;
  - en el mapa: íconos de alerta con filtro en la franja, ventana con *Abrir*, y botones *⚠ Problema* y *Pendiente* en el inspector;
  - `comun.js`: utilidades compartidas.
- **`ventana_web.Api.guardar_archivo`:** KMZ, GeoJSON, `.json` y `.sql` con el diálogo de Windows; solo esos tipos.
- **`empaquetar_visor.py`:** exige las 3 páginas nuevas y prohíbe la carpeta `respaldos_redes` dentro del `.exe`.

**Verificación en Edge headless,** con salida real del backend en una base temporal:
- **Problemas:**
  - lista de 2 activos y 3 en total;
  - la ventana muestra 2 fotos; se quitó una, se agregó otra y se cambió el estado: el envío fue correcto;
  - la foto completa se abre.
- **Pendientes:** 1 vencido en rojo; *✓ Hecho* funciona, y la ventana muestra el responsable y la fecha.
- **Backup:** lista con el `.sql`, *Restaurar* → RLR-R1, y el KMZ pasa a `guardar_archivo`.
- **Mapa:**
  - 2 íconos con "abiertos", 3 con "todos", 0 con "ocultar";
  - el inspector de FAT 1 tiene *⚠ Problema*, que abre la ventana con la FAT ya elegida;
  - "Ver en el mapa" de un problema cerrado cambia el filtro a "todos" y abre su resumen.
- Sin errores de JavaScript, y los arneses de las fases 3 a 6 siguen pasando.

**Decisiones de Claude:**
- **Reportar problemas:** cualquier usuario con acceso al proyecto, incluido un lector, porque quien está en campo debe poder reportar. Editar, cerrar o eliminar: quien edita el proyecto o quien lo reportó.
- **Pendientes:** los crea y edita quien edita el proyecto; el responsable puede cambiar el estado.
- **Respaldo:** siempre `.json`, porque es lo único que permite "restaurar como copia nueva de proyecto", y además `.sql` si hay `pg_dump`. La especificación decía uno u otro; se hacen los dos.
- **Carpeta configurable** con `REDES_RESPALDOS_DIR` en el `.env` del servidor, no desde la pantalla, para que una clave remota no pueda escribir en rutas arbitrarias. Por defecto, `respaldos_redes\`. **Es sensible:** tiene datos y fotos, no se publica.
- **Duplicar proyecto** no copia problemas ni pendientes, porque son de la red real y no del diseño. Restaurar un respaldo sí los trae.
- **Exportar KMZ o GeoJSON:** cualquier usuario que puede ver el proyecto. Crear, restaurar y descargar respaldos: solo administradores.

**Pendiente de verificar por Jan** (en la ventana real):
- reportar un problema con foto desde el inspector y verlo en el mapa;
- crear un pendiente con fecha;
- crear un respaldo, restaurarlo como copia y abrir el KMZ en Google Earth.

**Con esto quedan hechas las 7 fases de la especificación del módulo de redes.**

## Sección 8 "Datos y arquitectura": terminada, espera el OK de Jan

Jan pidió la "fase 8", que no existe. Claude preguntó y Jan aclaró: "realiza la parte de datos y arquitectura", es decir, la sección 8 de la especificación. Esto aprueba la fase 7.

**Estado:**
- **Pruebas:** **312** pasan (+5 en `Pruebas/test_redes_seccion8.py`).
- **Migración** `008_datos_arquitectura.sql` **aplicada en `Presupuesto_visio`**.
- **Integridad de la base real:** 1 proyecto, 12 reglas, **0 errores, 0 avisos**.
- **`VisorRutas.zip`:** regenerado.

**Revisión de la sección 8, punto por punto:**

| Punto | Estado antes | Qué se hizo |
|---|---|---|
| Esquema `redes` en `Presupuesto_visio`, PostGIS | cumplía (PostGIS 3.6.2 en `redes`) | — |
| Tablas mínimas sugeridas | todas, salvo que `hilos` no guardaba "buffer, color TIA" | columnas `buffer`, `color`, `color_buffer` en `hilos`, calculadas por **triggers** (también si el cable cambia de 12 a 8 por buffer); el trazado usa el color guardado |
| Toda escritura con versión | faltaba la posición de los cables en el lienzo de la mufa | `mufa_cables.version` y bloqueo optimista en `guardar_mufa`; el editor envía la versión leída |
| Migraciones versionadas | cumplía | 008 |
| No modificar `red_lineas`, `red_puntos`, `red_fibra` | cumplía (verificado: nada las escribe) | prueba de arquitectura que falla si una migración las nombra |
| 8.2 paquete backend, servicios, `js_api` y `/visor/redes/*` | cumplía | — |
| Librerías locales con licencia libre | cumplía (las 6 con su LICENSE) | tabla en ARQUITECTURA.md |
| JS separado por módulos | cumplía | — |

**Además:**
- **Índices** que faltaban: `proyecto_id` de conexiones, splitters y conectores; `cable_id` de `mufa_cables`; `responsable_id` de pendientes; `elemento_id` y `cable_id` de problemas.
- **`visor_rutas/redes/verificar.py`:** integridad de los datos, 12 reglas que cruzan tablas (8 errores y 4 avisos); solo lee. Está en el menú Backup → *Verificar la base* (administradores) y como `python -m visor_rutas.redes.verificar`.
- **`docs/modulo_redes/ARQUITECTURA.md`:** diagrama entidad-relación, diccionario de las 19 tablas sacado de la base real, triggers, reglas transversales, migraciones, flujo local y remoto, módulos con sus métodos, librerías y licencias, matriz de permisos, respaldo y verificación, cómo agregar una tabla o un método, y las diferencias con la especificación.
- **Pruebas de arquitectura:** todo en `redes`; toda tabla editable con `version` y `borrado_en` (con excepciones justificadas); ninguna migración nombra las tablas existentes; la lista blanca de columnas apunta a tablas reales.

## Nuevo trabajo: migración Visio → mufas interactivas (`docs/migracion_visio/PLAN.md`)

**Fase 0 (diagnóstico): hecha, espera el OK de Jan.** No se escribió código. Las mediciones fueron de solo lectura, con scripts temporales.

Todo está en `docs/migracion_visio/FASE0_DIAGNOSTICO.md`:
- cobertura medida;
- modelo de datos propuesto (migración 009);
- `migracion_visio` para `business_rules.yaml`;
- 8 preguntas para Jan.

**Hallazgos principales:**
- El plan usaba la importación n.º 1 (1 110 enlaces). La actual (n.º 2) tiene **3 208**, y el **71 % de los pares de mufas no tiene hilos**.
- **`fusiones_piloto` nunca se corrió:** precisión desconocida.
- **No hay datos de Kayako** en el proyecto.
- **Los `id` de `red_fibra.nodos` no son estables** entre reimportaciones, y hay 129 nombres repetidos. Se propone otra clave de idempotencia.
- Configuración de buffers escrita: solo 4 textos. Modelo de mufa escrito: prácticamente ninguno. Todo eso será "estimado".
- KMZ: el 95 % de los nodos tiene un punto a ≤ 30 m y el 64 % de los cables una línea a ≤ 25 m.
- Empalmes conocidos: unas 212 fusiones del anillo (106 tramos legibles). Lo demás depende de la geometría, que hay que medir.

**Respuestas de Jan a la fase 0:** quedan en §4 del informe.
- 1: sí; 2: 6x4 y 6x8; 3: de acuerdo; 6: de acuerdo; 7: de acuerdo; 8: migrar las reservas.
- 4: pidió aclarar qué haría él; se propuso medir primero en automático con el anillo.
- 5: las coordenadas vienen en el comentario del ticket. Medido: el 70 % de los clientes del Visio ya se ubican con las acometidas del KMZ; falta saber cómo leer Kayako.
- Hilos sueltos: se midió su idea. La continuidad resuelve 122 cables directo. El texto del KMZ acierta solo el 36–50 %, así que queda como estimado.

**Antes de la fase 1 falta:** el OK de Jan y cómo leer Kayako (esto no bloquea la fase 1).

**Pendiente de verificar por Jan (sección 8):**
- leer ARQUITECTURA.md;
- en la ventana real, *Verificar la base*;
- mover un cable en una mufa desde dos visores a la vez: el segundo debe recibir el aviso de recargar.
