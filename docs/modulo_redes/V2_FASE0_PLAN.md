# Visor v2 · Fase 0: lectura del código y plan

Respuesta a la fase 0 de `ESPECIFICACION.md` (versión 2), con las decisiones de Jan del 2026-10-13 y 2026-10-14 ya incorporadas.
**No se escribió código en la fase 0.** Todo sale de leer `ventana_web.py`, `remoto.py`, `visor_api.py`, `visor.js`,
`lugares.js`, `menu.js`, `visor.html`, `visor.css`, `redes/` (API, editor de mapa, editor de mufa, respaldo),
`kmz_capas.py`, `calculo.py`, `presupuesto_visor.py`, `fusion.py`, `red.py`, las 11 imágenes de `img_v2/` y las bases reales.

## 0. Decisiones de Jan

| Tema | Decisión |
|---|---|
| Elementos de red nuevos | Se dibujan **en el mapa actual, sin entrar a un proyecto**, y quedan **en una carpeta de "Mis lugares"** (como en Google Earth). De ahí se **exportan a KMZ** y, si se quiere, se **guardan como proyecto**. |
| Editar la ruta calculada | **Nuevo:** al generar una ruta se puede **editar** si tiene un error, y de igual manera la **ruta de fusión**. **Todo cambio recalcula** (vértices, postes a mano, postes marcados como existentes) y una ruta dibujada a mano va generando su presupuesto aproximado. Ver sección 7. |
| Ruta de fusión | Se arma **desde donde viene la potencia**; las mufas **aéreas** y **de corte** no se tocan (por el nombre); se revisa la disponibilidad de hilos y se hacen las fusiones. Cada ruta de fusión se **agrega al Excel de ejemplo** (una franja nueva con la fecha del día, mismo formato). Ver sección 7. |
| Aplicar una carpeta a la red | Por ahora **basta con guardarla en la carpeta** de Mis lugares. |
| Excel de rutas de fusión | El real está en la nube y lo comparten otras personas. **Por ahora se usa la copia del proyecto** (`EjemploRutaFusiones/`): se le van agregando las rutas armadas y Jan verifica después si quedaron bien. **Solo se escribe en la hoja "2025 - 2026"**, nunca en otra. |
| Qué se llena en la franja | La **fecha** va por defecto la de hoy y Jan la cambia. **Cuadrilla y Diagramas no se tocan** (quedan vacíos). **Cliente:** vacío si el presupuesto se hizo a mano (lo llena Jan después); si viene de un ticket, el **nombre del ticket**. Siempre se escribe la ruta (los pasos). |
| Mufas que no se tocan | Confirmado: "aérea" y "de corte" por el nombre, con excepción de nombres de lugar ("FUERZA AÉREA") y botón para marcarlas a mano. |
| Duplicados KMZ ↔ red base | **Se dejan como están**: el KMZ y el Visio se ven los dos. No se filtra nada. |
| Publicar en PostGIS | Jan no sabe quién carga esas tablas. Se investigó (sección 1): se resuelve con una función de **re-publicar** y no hace falta saberlo. |
| Todo lo demás | Aprobado: íconos propios en SVG, sin pestaña Altitud ni encabezado / inclinación, límite de Google configurable, copiar el KMZ importado a `red_kmz\` con el anterior de respaldo, endpoint aparte para archivos grandes en remoto. |

## 1. Lo que ya existe y condiciona el diseño

| Hallazgo | Consecuencia |
|---|---|
| **Una sola puerta para todo lo de redes:** `Api.redes(metodo, args)` → `ServicioRedes.llamar` (lista cerrada `METODOS`), igual en local y en remoto (`POST /visor/redes/{metodo}` con la clave del visor). | Mis lugares, edición, importación y lotes masivos se agregan como métodos nuevos y **funcionan en remoto sin trabajo extra** (sección 9 de la spec). Solo los archivos grandes y las tareas largas necesitan algo propio. |
| **El editor de red de proyectos ya trabaja sobre el mapa principal** (sin ventana aparte): paleta, imán a postes y mufas, vértices, deshacer/rehacer, Ctrl+S, metraje. | Su motor de dibujo se reutiliza para dibujar en carpetas; lo que cambia es **dónde se guarda** (carpeta, no proyecto). |
| **Entrar a una mufa del KMZ ya existe a medias** (migración Visio, fase 5): Enter o doble clic abre el editor de mufa si está migrada; si no, el diagrama Visio. | Falta el botón "Entrar a la mufa" en el popup y **crear la mufa vacía al vuelo** si no existe. |
| **El visor muestra el KMZ desde un archivo** (35 526 elementos), pero **el presupuesto usa PostGIS** (`red_puntos` 29 892 filas, `red_lineas` 5 742). Columnas: `id, tabla_origen, categoria, nombre, descripcion, geom, tipo`. | Son dos copias de la red. Lo editado en el visor se ve al instante; lo que usa el presupuesto cambia solo al **publicar**. |
| **Origen de esas tablas (investigado):** `tabla_origen` guarda el nombre de la capa de origen ("mufa (_20)", "postes de concreto (_4)", "fibra optica (_34)"…) y en `public` quedan **~400 tablas sueltas, una por capa del KMZ**. Es decir, se cargó a mano (QGIS u ogr2ogr, una tabla por capa) y se consolidó en las dos tablas. **No hay script en el proyecto que lo repita.** | No hay un proceso automático que pise lo publicado. El riesgo es que la próxima carga manual rehaga las tablas y **borre** lo publicado. Por eso se guarda todo cambio publicado en `kmz_cambios` y se agrega **"Re-publicar cambios"** (vuelve a aplicarlos sobre tablas recién cargadas). Lo publicado se marca `tabla_origen = 'visor'`. |
| **Los puntos del KMZ (archivo) no traen el id de PostGIS.** | Ligar una mufa del archivo con la red base se hace por nombre + cercanía, como ya hace `mufa_existente`. |
| La red base ya trae 3 412 mufas, 51 ODF, 44 nodos y 2 037 clientes (migración Visio); 4 561 elementos llevan `ref_externa.kmz`. | Se ven repetidas con las del KMZ si se muestran las dos capas. **Decidido: se deja así.** |
| `visor.js` tiene 2 064 líneas (110 KB), `lugares.js` 803. | Todo lo nuevo va en módulos aparte; `visor.js` solo cambia para conectarlos. |
| La ruta calculada es una polilínea de Google (`calculo.calcular_ruta`); sus postes, mufas en ruta y presupuesto salen de esa polilínea. El presupuesto pide la ruta a un caché (`CacheRutas`, `usando_rutas`). | Se puede **inyectar una ruta editada** en ese mismo punto y recalcular sin tocar `POST /presupuesto` (sección 9). |

## 2. Sección 2 de la spec (arreglos de interfaz): causas encontradas

1. **Dos paneles de capas:** `L.control.layers` (visor.js:135) crea el recuadro flotante, y `lugares.js` el árbol. Se unifican.
2. **Filtros "que no hacen nada":** hipótesis a confirmar en la fase 1 con el visor abierto:
   - Postes existentes / nuevos, Mufas en ruta / intervenidas, Nodos Visio y Camino de la fibra son grupos que **solo se llenan al calcular una ruta** (`dibujar()`). Antes de eso marcarlos no cambia nada → se deshabilitan con el tooltip "se llena al generar una ruta".
   - "Red Visio · nodos / enlaces" carga por pantalla y **solo desde zoom 12**.
   - Las capas del KMZ no dependen de ese recuadro sino del árbol de Lugares.
3. **"Lugares ›" tapado (img 10):** la pestaña tiene `z-index: 970`, los controles de Leaflet arriba a la izquierda (zoom y capas) `1000`, y caen en el mismo lugar. Se mueve el zoom abajo a la derecha, **desplazado por el ancho del panel derecho**, y se ordenan los z-index en una tabla única (hoy hay una decena de valores sueltos entre 900 y 3500).
4. **Panel derecho (img 11):** hoy siempre visible a 340 px. Ya tiene botón de contraer (`❮ Resumen`) y tirador para redimensionar; falta ocultarlo por defecto y abrirlo solo con un resultado (`generar()`, `seleccionarMufa()`).

## 3. Modelo de datos

Migraciones nuevas a continuación de la 010, idempotentes, con `-- respaldo: previo`; sus tablas entran en la lista blanca de `repositorio.COLUMNAS`, en el respaldo y en `ARQUITECTURA.md`. Convención: `version`, `borrado_en`, `creado_por`, `actualizado_por`.

**`011_lugares.sql` (Mis lugares, incluye elementos de red)**
- `lugares_carpetas`: `usuario_id`, `padre_id`, `nombre`, `orden`, `visible`.
- `lugares_elementos`: `carpeta_id`, **`tipo`** (`marca` | `ruta` | `poligono` | **`mufa` | `poste` | `cliente` | `nodo` | `odf` | `cable`**), `nombre`, `descripcion_html`, `geom`, `estilo` (jsonb), `vista` (jsonb), `propiedades` (jsonb: subtipo de la mufa o del poste; en un cable, clase, ADSS/FLAT, hilos, hilos por buffer, color y a qué elementos se une en cada extremo), `orden`, `visible`.
- `lugares_adjuntos`: imágenes de la descripción, **en la base** (viajan en los respaldos y funcionan en remoto).
- `lugares_compartidas`: `carpeta_id`, `usuario_id`, `puede_editar`.
- **Guardar como proyecto:** copia uno a uno los elementos de la carpeta a un proyecto nuevo (mismos tipos; los cables se unen a los elementos creados), sin preguntas. **Exportar a KMZ:** íconos y colores por tipo, cables con su color y grosor por clase, igual que ya exporta el módulo de proyectos.

**`012_kmz_cambios.sql` (editar lo existente e importar)**
- `kmz_cambios`: elemento del KMZ identificado por **carpeta + nombre normalizado + coordenada redondeada** (el criterio que ya funcionó con Visio); `accion` (`editar` | `borrar`), `antes` y `despues`, usuario, fecha, `publicado`, `elemento_id` si se ligó a la red base.
- `kmz_importaciones` (archivo, md5, modo, usuario, fecha, estado, conteos, respaldo, publicado) y `kmz_importacion_detalle` (clase `nuevo` | `modificado` | `sin_cambios` | `eliminado`, geometrías, `aceptado`).
- Se amplía el dominio `fuente_dato` con `kmz_importado`.

**`013_lotes_masivos.sql`:** `lotes_masivos` (usuario, archivo, estado, puntos, carpeta de salida, configuración, costo estimado, progreso) y `lotes_masivos_puntos` (orden, nombre, código, lat/lon, estado, `resultado`).

**`014_rutas_trabajo.sql`:** `rutas_trabajo` (usuario, cliente lat/lon, ruta de Google y ruta editada, si es manual, resumen del presupuesto, pasos de la ruta de fusión con sus hilos, datos del cliente y la cuadrilla, fecha de la actividad, hoja y filas donde se exportó, estado borrador / exportada), para recuperar una ruta corregida, guardarla en Mis lugares y no duplicarla en el Excel (sección 7).

## 4. Estructura de archivos

Sin hacer crecer `visor.js`: este solo conecta módulos y expone `window.visor`.

| Fase | Python (`visor_rutas/…`) | Página (`web/…`) |
|---|---|---|
| 1 | — | `mapa/capas_visor.js` (secciones "Capas del visor" y "Mapa base" dentro del árbol de Lugares), `mapa/controles.js` (zoom, z-index, panel derecho) |
| 2 | `coordenadas.py` (decimal, GMS, GM; validación Nicaragua) | `mapa/coordenadas.js` (mismo parser), `mapa/pin.js` |
| 3 | `redes/lugares.py`, `redes/kmz_io.py` (exportar e importar carpeta; reusa el KMZ de `respaldo.py`; guardar como proyecto) | `lugares/mis_lugares.js`, `lugares/dialogo_marca.js`, `lugares/dialogo_ruta.js`, `lugares/iconos.js`, `mapa/barra_herramientas.js` |
| 4 | `redes/kmz_cambios.py`, `mufas_existentes.py` (crear al vuelo) | `lugares/dibujar_red.js` (mufa, poste, cliente, nodo, cable en la carpeta activa, con el imán del editor actual), `redes/editar_existente.js` (mover / renombrar / borrar KMZ y red base), cambios en `lugares.js` |
| 4B | `ruta_editable.py` (`calcular_con_ruta`), ampliar `calculo.py` / `presupuesto_visor.py` (ruta editada), `ruta_fusion_plan.py` (potencia → mufas a intervenir → hilos → pasos), `ruta_fusion_xlsx.py` (agregar la franja al libro a nivel XML) | `mapa/editar_ruta.js`, `mapa/editar_fusion.js` (pasos editables y formulario de exportación) |
| 5 | `redes/importar_kmz.py` | `redes/importar_kmz.js` (pantalla de revisión) |
| 6 | `redes/masivas.py`, `lectura_coordenadas.py` | `redes/masivas.js` |
| 7 | `visor_api.py` (subida de archivos y tareas largas), `remoto.py` | — |

## 5. Cómo se cruza con la red base

- **Dibujar red nueva (fase 4):** no toca la red base ni los proyectos; vive en la carpeta activa de Mis lugares. Imán y metraje son los del editor actual. Se puede unir un cable nuevo a una mufa del KMZ o de la red base (referencia por clave, sin modificar a esa mufa).
- **Editar lo existente (fase 4):** mufas, nodos y ODF del KMZ pasan a ser elementos de la red base **al tocarlos** (copiar al editar, ligados por `ref_externa`); postes, líneas y el resto del KMZ se editan o borran con `kmz_cambios`; lo ya migrado de Visio se edita directo. Cada elemento se guarda en **su propio proyecto base**, agrupado automáticamente: no hay que elegir proyecto ni región.
- **Ver el estado efectivo:** `lugares.js` pide los cambios al arrancar y, al construir una capa, oculta lo borrado y dibuja lo editado. El archivo KMZ **no se modifica**.
- **Publicar en PostGIS:** escribe en `red_puntos` / `red_lineas` con `tabla_origen = 'visor'`, respaldo previo de las dos tablas y reporte. "Re-publicar" repite lo publicado después de una recarga manual de las tablas.
- **Aplicar una carpeta a la red base:** no se pidió; queda **fuera** hasta que lo pidas.

## 6. Riesgos y cosas que hay que resolver

1. **Dos copias de la red** (archivo KMZ y PostGIS): lo publicado se mantiene con "Re-publicar".
2. **Envío de archivos en remoto:** `redes` recibe JSON; un KMZ completo pesa 20 MB (≈27 MB en base64) por ngrok. Endpoint de subida aparte (fase 7).
3. **Tareas largas (masivas, importación):** en segundo plano con progreso y cancelación. Hoy el presupuesto genera **un Excel a la vez** (LibreOffice), así que 20 coordenadas serán secuenciales; el tiempo por presupuesto se mide en la fase 6 antes de prometer una duración.
4. **Google en las masivas:** límite por minuto configurable (propuesto: 30) y aviso con el número de consultas; en remoto, el límite por hora de la persona se cuenta también dentro de la tarea. Sin precio de Directions, el aviso dice "N consultas".
5. **Íconos propios** (pushpins de colores, letras A–Z, números 1–10, figuras y ~20 símbolos), con el orden y selector de `06_selector_iconos.png`.
6. **Mapa 2D:** en "Ver" se guardan centro y zoom; no hay alcance en metros, encabezado ni inclinación. Sin pestaña Altitud.
7. **Pruebas de la página:** en Edge sin ventana con datos reales, como en las fases anteriores; los parsers se prueban en Python y en la página con los mismos casos.

## 7. Fase 4B: editar la ruta, presupuesto en vivo y ruta de fusión con su Excel

Respuestas de Jan del 2026-10-14, y el libro de ejemplo `EjemploRutaFusiones/RUTA DE FUSION - Copia.xlsx` leído completo.

### 7.1 Ruta editable y presupuesto en vivo

**Regla de Jan: todo cambio recalcula.** Son cambios: mover, agregar o quitar un vértice de la ruta; agregar un poste a mano; marcar un poste como existente; y dibujar la ruta completa a mano. En una ruta a mano, el presupuesto aproximado **se va generando mientras se dibuja**.

- **Cómo:** un método nuevo `calcular_con_ruta` reutiliza el cálculo actual (`calculo._calcular`) **sin pedir la ruta a Google**: usa la polilínea del usuario. Esa misma ruta se inyecta en el caché de rutas (el punto donde hoy entra la de Google), así el presupuesto aproximado y "Generar presupuesto" usan la ruta editada. **`POST /presupuesto` no cambia.**
- **Qué se recalcula:** distancia, metraje final y reserva, postes existentes (consulta PostGIS cerca de la línea), postes nuevos y sus posiciones, mufas en ruta, mufas intervenidas y el presupuesto.
- **Cuándo:** unos 0,6 s después del último cambio, y una respuesta vieja se descarta si ya hay otra más nueva (como ya hace la estimación).
- **Ritmo:** el presupuesto completo pasa por LibreOffice (varios segundos). Se mide en la fase; si es lento, metraje, postes y mufas se actualizan al instante y el importe llega detrás.
- **Postes a mano:** agregar un poste en un punto cuenta como nuevo; marcar uno existente baja el cobro (igual que hoy, pero también sobre la ruta editada).
- **Marcas:** "ruta manual" mientras difiera de la de Google; botón "Volver a la de Google". La ruta editada se puede guardar en Mis lugares y exportar a KMZ.

### 7.2 Ruta de fusión (reglas de Jan)

1. **Se arma desde donde viene la potencia** (OLT, nodo o splitter). De ahí se deduce qué mufas hay que intervenir, se mira la disponibilidad de hilos y se asignan las fusiones. En el Excel se escribe en el orden de los ejemplos: **del cliente hacia la potencia**.
2. **No se tocan** (la fusión pasa de largo): una mufa **aérea** (queda suspendida en los cables) y una mufa **de corte**. Se reconocen **por el nombre**. En los datos hay 91 mufas con "aérea" y 299 con "corte" en el KMZ (246 y 899 en la red base). Cuidado: "MF FUERZA AEREA" es un lugar, no una mufa aérea. Por eso las palabras viven en `business_rules.yaml` (`ruta_fusion.no_tocar`, con sus excepciones) y el usuario puede **marcar o desmarcar a mano** "no tocar" en cada mufa de la ruta.
3. **Hilos:** se proponen con lo que se sabe (conexiones y estado de hilos de la red base, Excel de anillos, clientes de cada mufa). Donde no hay dato queda **"H__ por identificar"**, como en el propio ejemplo ("Identificar H4…", "Hacer la correcta identificación del hilo"). Cada línea es editable antes de exportar. Hoy la disponibilidad de hilos solo se conoce en una parte de la red (212 empalmes del anillo y las mufas ya diagramadas): el resto lo completa el técnico.
4. **Editar la ruta de fusión:** agregar, quitar, reordenar o reemplazar mufas; marcar "no tocar"; cambiar hilos; agregar un splitter (SPL 1/8, 1/16), una mufa nueva ("instalar MF FOSC") o "COMPARTIR POTENCIA DEL SP". Cada cambio rehace las líneas, el camino punteado del mapa y el conteo de mufas intervenidas del presupuesto.

### 7.3 Excel de rutas de fusión (el del ejemplo, no uno nuevo)

**Qué es el archivo.** Cuatro hojas: "2023 - 2024", "2025 - 2026" (15 645 filas con datos y 12 851 celdas combinadas), "Rutas Borradores" y "RUTAS NO EJECUTADAS". Una hoja cada dos años y las franjas de cada día una debajo de otra.

**Cómo es una franja:**

| Parte | Formato real |
|---|---|
| Fecha | barra **verde** (A:I, 2 filas) con la fecha del día |
| Bloques | dos lado a lado: **izquierdo A–D** y **derecho F–I** (hasta 2 actividades por fecha, una por cuadrilla) |
| Cliente | fila azul claro: `C##### Nombre / ID###### / Lugar / Tipo de actividad` (Instalacion FO, Cambio de medio LTE a FO, Traslado de servicio…) |
| Diagramas | fila azul; **no se toca** (Jan pone ahí las imágenes) |
| Cuadrilla | fila blanca: código de la cuadrilla (p. ej. `BUZ-507-51147`) y a veces la empresa (TELENIC); **no se toca** (queda vacía) |
| Pasos | una **caja blanca por mufa** (combinada A:D o F:I × 2 filas, centrada, con ajuste de texto) |
| Avisos | texto rojo para notas especiales; `COMPARTIR POTENCIA DEL SP` en azul negrita |
| Cierre | `RUTA SUGERIDA` en rojo; debajo, la imagen del mapa de la ruta |

**Texto de cada caja (patrones reales del libro):**
- Primera, la del cliente: `En MF {NOMBRE} {lat}°, {lon}° ingresar la acometida del cliente. H1 del cliente fusionarlo con H{n} hacia MF {SIGUIENTE}`
- Intermedia: `En MF {NOMBRE} {lat}°, {lon}° H{a} hacia MF {ANTERIOR} fusionarlo con H{b} hacia MF {SIGUIENTE}`
- Con splitter: `… fusionarlo con H{n} del SPL 1/8` · `alimentar SPL PRINCIPAL con H{n} hacia {X}` · `instalar el SPL SECUNDARIO NUEVO` · `H{n} del SPL 1/8 fusionado con H1 del cliente de baja {nombre}`
- Cuando falta el dato: `Identificar fusión H{n} hacia MF {X}…`

**Cómo se agrega la franja del día:**
1. Se copian las cajas de la franja más reciente (mismos anchos, colores, bordes y celdas combinadas) debajo de la última de la hoja **"2025 - 2026"**, con la fecha de hoy (Jan la cambia en el libro). Si ya hay una franja de esa fecha con el bloque derecho libre, se usa ese bloque.
2. Se llena: el **cliente** (vacío si el presupuesto fue a mano; el nombre del ticket si viene de un ticket), un **paso por mufa intervenida** y los avisos. **Cuadrilla y Diagramas quedan vacíos.**
3. **RUTA SUGERIDA:** además del rótulo, debajo va el mapa de la ruta (el mismo que ya genera el presupuesto). *Supuesto mío: si prefieres dejarlo vacío, se quita.*
4. Se agrega solo al final; lo que ya existe no se toca. El archivo es una variable de configuración (`RUTA_FUSION_XLSX`, por defecto la copia del proyecto), pensada para apuntar luego al de la nube; al ser compartido habrá que cuidar que nadie lo tenga abierto al escribir.
**Riesgo técnico (detectado):** el libro pesa 5 MB (una hoja de 30 MB de XML) y tiene **comentarios en hilo** y dibujos. Si se regrabara con `openpyxl` esos comentarios se perderían. Por eso la franja se escribe **a nivel XML**, clonando las filas de la plantilla y sin tocar el resto, con respaldo previo del archivo, escritura atómica y un aviso claro si el archivo está abierto en Excel (entonces no se puede escribir). Se verifica reabriéndolo.

## 8. Fases (detenerse al final de cada una)

| Fase | Alcance | Listo cuando |
|---|---|---|
| 1 | Arreglos de interfaz (sección 2 de la spec). | Un solo panel de capas, filtros que funcionan, zoom abajo a la derecha, nada tapado, panel derecho oculto hasta tener resultado. |
| 2 | Buscador de coordenadas con pin. | Busco en decimal y en grados/minutos/segundos, aparece el pin con la etiqueta y no se calcula nada. |
| 3 | Mis lugares: carpetas, marca, ruta, polígono, estilos, íconos, vista, exportar e importar KMZ de una carpeta. | Creo carpetas y elementos, siguen ahí al reabrir. |
| 4 | Dibujar mufas, postes, clientes, nodos y cables en una carpeta; guardar como proyecto; editar lo existente (KMZ y red base); entrar a cualquier mufa. | Dibujo una mufa y un cable en una carpeta, la exporto a KMZ y la guardo como proyecto; edito una mufa del KMZ y guardo. |
| **4B** | **Editar la ruta, presupuesto en vivo y ruta de fusión con su Excel (sección 7).** | Corrijo una ruta y el presupuesto se recalcula solo; dibujo una a mano y se va generando; armo la ruta de fusión, edito una parada y la agrego como franja nueva a una copia del Excel de ejemplo, que se abre en Excel con el mismo formato y sin perder sus comentarios. |
| 5 | Importar KMZ: dos modos, comparación, revisión, aplicar, publicar y revertir. | Importo una ruta nueva y una actualización, reviso y aplico. |
| 6 | Coordenadas masivas. | Subo un Excel con 20 coordenadas, genero los presupuestos y lo guardo como proyecto. |
| 7 | Modo remoto para todo lo anterior. | Funciona igual desde el .exe. |

En cada fase: pruebas en `Pruebas/`, las 344 actuales siguen pasando, `POST /presupuesto` sin cambios, README y `ARQUITECTURA.md` al día, bitácora.

## 9. Preguntas de la fase 4B: todas respondidas

Respondidas el 2026-10-14: el archivo es el de la copia del proyecto por ahora (después el de la nube); "aérea" y "corte" por nombre; la fecha la cambia Jan; cuadrilla y diagramas no se tocan; el cliente va vacío si el presupuesto es a mano y con el nombre del ticket si viene de uno; solo se escribe en la hoja "2025 - 2026". No quedan preguntas abiertas. Queda un solo supuesto mío (el mapa bajo "RUTA SUGERIDA", sección 7.3) que se quita si no lo quieres.