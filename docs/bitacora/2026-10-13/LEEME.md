# Bitácora 2026-10-13

## Visor v2 (docs/modulo_redes/ESPECIFICACION.md, versión 2): fase 0 y fase 1

- **Fase 0:** plan en `docs/modulo_redes/V2_FASE0_PLAN.md`, con las decisiones de Jan: los elementos de red nuevos se dibujan en el mapa **y quedan en una carpeta de Mis lugares** (exportar a KMZ o guardar como proyecto); **editar la ruta calculada y la ruta de fusión** es requisito nuevo (fase 4B); los duplicados KMZ ↔ Visio se dejan; íconos propios, sin Altitud, KMZ completo a `red_kmz\`. `red_puntos` / `red_lineas` se cargaron a mano (una tabla por capa del KMZ, ~400 quedan sueltas en `public`): se publicará con `tabla_origen = 'visor'` y habrá "Re-publicar".
- **Fase 1 (interfaz), hecha, espera el OK de Jan:**
  - **Un solo panel de capas:** las secciones «Mapa base» y «Capas del visor» (casilla de tres estados) están en el árbol de Lugares (`web/mapa/capas_visor.js` + `registrarSeccion` en `lugares.js`); se quitó el recuadro flotante de Leaflet. Funcionan aunque el KMZ no cargue.
  - **Filtros:** los que dependen de un cálculo (postes, mufas en ruta / intervenidas, nodos Visio cercanos, camino de la fibra, mufa buscada, mis medidas) quedan deshabilitados con el tooltip «se llena al generar una ruta / al buscar una mufa / al medir»; Red Visio indica «zoom 12+» y se probó que pide los datos al servidor.
  - **Zoom** ＋/− abajo a la derecha, corrido por el ancho del panel derecho. **«Lugares ›» ya no queda tapado** (era el zoom, z-index 1000 contra 970; ahora hay una tabla única de z-index `--z-*`).
  - **Panel derecho:** cerrado al inicio; se abre al generar una ruta, buscar una mufa o terminar una medida; 300 px (antes 340), redimensionable (mínimo 260), se contrae a su pestaña; «Limpiar» lo cierra. La leyenda de troncales empieza plegada a menos de 820 px de alto.
  - **Probado en Edge sin ventana** a 1366×768 y 1920×1080 con la red real: 0 errores JS, ningún control flotante pisa a otro. Quedó como prueba permanente: `Pruebas/arnes_pagina.py` + `test_visor_pagina_fase1.py` (Api de prueba, sin bases de datos). **Pruebas: 346 pasan.**
- **2026-10-14, fase 2 aprobada por Jan. Fase 3 (Mis lugares) hecha, espera su OK:**
  - **Datos:** migración `011_lugares.sql` (`lugares_carpetas`, `lugares_elementos`, `lugares_adjuntos`, `lugares_compartidas`), ya en la base real con su respaldo automático previo (el servicio la aplicó solo a las 10:53; son tablas nuevas y vacías; la verificación sigue en 0 errores). Los tipos de elemento ya incluyen mufa, poste, cliente, nodo, odf y cable para dibujar red en una carpeta en la fase 4.
  - **Servidor:** `lugares.py` (13 métodos de `METODOS`, todos funcionan igual en remoto), `lugares_kmz.py` (exportar e importar KMZ / KML de ida y vuelta, todo o nada) y `lugares_iconos.py` (íconos propios: pushpins de 10 colores, letras, números y 8 figuras, en SVG para la página y en PNG para el KMZ).
  - **Página:** Mis lugares en el árbol de Lugares (casillas de tres estados que se guardan, arrastrar y soltar para mover y ordenar a mano, menú de clic derecho con todo lo de la especificación §4.1, Compartidas conmigo), barra de herramientas arriba del mapa, y la ventana flotante de una marca / ruta / polígono (Descripción con Quill, vínculos e imágenes locales; Estilo, color; Ver; Medidas en vivo) que no bloquea el mapa: el pincho se arrastra y los vértices se mueven con el ratón.
  - **Errores reales encontrados al probar en la página y corregidos:** (1) el doble clic que termina una ruta también hacía zoom en el mapa y todo se corría; ahora el zoom por doble clic se apaga mientras se dibuja o edita; (2) el clic derecho en una carpeta de Mis lugares abría además el menú de las carpetas del KMZ; (3) «Compartidas conmigo» empezaba plegada y no se encontraba.
  - **Decisiones mías (cambiables):** «Guardar como proyecto» aparece deshabilitado hasta que las carpetas lleven elementos de red (fase 4); lo abierto o cerrado del árbol se recuerda en el equipo (no en la base) para no chocar con versiones; las casillas de una carpeta compartida valen solo en la ventana de quien la recibe; el KMZ de entrada admite hasta 30 MB y 5 000 lugares.
  - **Pruebas: 405 pasan** (+11 del servidor, +2 de la página con el recorrido completo en una base desechable; la de actualización 008 → 011 ahora espera tres respaldos).
- **2026-10-14, fase 1 aprobada por Jan. Fase 2 (buscador de coordenadas con pincho) hecha, espera su OK:**
  - **Formatos:** decimal (`13.094578, -86.002708`, espacio o `;`), grados-minutos-segundos (`13°5'38.09"N 86°0'7.42"O`; `W`, `º`, solo espacios, letra delante) y grados con minutos decimales (`13 5.6348N 86 0.1237W`). Debe caer en Nicaragua: si solo cabe con latitud y longitud al revés, avisa y ofrece la forma correcta; si no, dice que está fuera. Nunca confunde con coordenada un nombre como «MF 12 NORTE» (cualquier otra letra la descarta; con un solo número tampoco).
  - **Pincho:** Enter vuela y pone un pincho amarillo con la coordenada decimal (casilla «Coordenada buscada», uno solo). Clic: copiar decimal o grados, «Guardar en Mis lugares» (deshabilitado hasta la fase 3), «Usar para generar ruta» (llena la barra inferior) y «Quitar». **No calcula ruta ni presupuesto** (la prueba verifica que no se llame a `calcular` ni a `estimar_presupuesto`).
  - **Buscador con varias fuentes** (`web/mapa/buscador.js`): mufas y nodos Visio, el KMZ (sin postes ni pozos) y la red base (método nuevo `buscar_elementos`: lo creado en la herramienta y los clientes por nombre o código; una mufa migrada de Visio ya sale en la primera fuente). Cada fuente con su título; una que falla no oculta las demás. Mis lugares se suma en la fase 3 con `Buscador.registrarFuente`.
  - **Dos lectores, un solo criterio:** `visor_rutas/coordenadas.py` y `web/mapa/coordenadas.js`, probados con los mismos 41 casos (`Pruebas/vectores_coordenadas.json`) y con los mismos mensajes.
  - **Pruebas: 393 pasan** (+44 del intérprete, +1 de `buscar_elementos`, +2 de la página a 1366×768 y 1920×1080, y la de la fase 1 ajustada por la capa nueva).
  - Para Jan, a decidir cuando quiera: una longitud escrita sin signo menos y sin letra (`86.002708`) se toma como **este** y se rechaza por estar fuera de Nicaragua; lo habitual es escribir `-86.002708` o la letra `O`/`W`.
- **2026-10-14, respuestas de Jan sobre la fase 4B** (ya en `V2_FASE0_PLAN.md` §7 y §9): todo cambio de la ruta recalcula (vértices, postes a mano, postes marcados existentes) y una ruta a mano va generando su presupuesto; la carpeta de Mis lugares basta por ahora para lo dibujado; la ruta de fusión se arma desde la potencia, **no se tocan las mufas aéreas ni las de corte** (por nombre; ojo «MF FUERZA AEREA» es un lugar) y cada ruta se **agrega como franja nueva** (fecha del día, mismo formato) al Excel `EjemploRutaFusiones/RUTA DE FUSION - Copia.xlsx`. Ese libro (5 MB, hoja de 30 MB de XML, comentarios en hilo) se escribirá a nivel XML, no con `openpyxl`, para no perder los comentarios. Tiene clientes reales: la carpeta quedó en `.gitignore`.
- Confirmado en la prueba: los filtros «que no hacían nada» eran los que dependen de un cálculo; las capas del KMZ nunca dependieron de ese recuadro.
- Pendiente: el OK de Jan para la fase 1; responder las 3 preguntas de la fase 4B (ruta editada y presupuesto, qué corrige de la ruta de fusión, aplicar una carpeta a la red base); regenerar el zip para Marlon (la página cambió).

Contexto anterior:
- `../2026-10-12/LEEME.md`: módulo de redes, fases 1–7 y sección 8. La sección 8 espera el OK de Jan.
- Fase 0 de la migración Visio: `../../docs/migracion_visio/FASE0_DIAGNOSTICO.md`.

## Migración Visio: fases 5, 6 y 7 (cierre del plan)

Jan: "Sigue con las demás fases". Con esto quedan hechas las 8 fases (0–7) de `docs/migracion_visio/PLAN.md`; todas esperan el OK de Jan. **Pruebas: 343 pasan.**

**Fase 5, interactividad con la red existente** (`mufas_existentes.py`, `web/redes/red_mufas.js`, editor de mufa):
- Enter o doble clic en cualquier mufa existente (punto del KMZ, nodo Visio o «Lugares») abre su editor: se busca por el punto del KMZ, por el nombre Visio cerca de la coordenada o por la más cercana.
- «Ver Visio original»: el diagrama Visio de la mufa en la mitad derecha, para comparar.
- «Marcar como validada» / «Quitar validación»: la mufa y lo que tiene adentro pasan a confianza «verificada».
- Selector de configuración del cable (6x4 ↔ 12x2…; fijar los hilos de un cable desconocido): los hilos se recolorean y las conexiones se conservan por número.
- Vista «Red de mufas»: la mufa y sus vecinas a 1 o 2 saltos; Enter o doble clic entra a otra.

**Fase 6, cola de corrección y tablero** (`migracion_tablero.py`, `web/redes/migracion.js`):
- Tablero por zona: mufas migradas, con fusiones, con supuestos, validadas, editadas y avance.
- Cola ordenada, sin las validadas, con filtros por zona, motivo y texto, y salto a la mufa: sin ubicar, el Visio pedía revisarla, excede capacidad, cables sin hilos, sin diagramar, ubicación / configuración / modelo estimados.
- «Exportar a Excel» (hojas Tablero y Correcciones) para Planta Externa.

**Fase 7, reimportación segura** (`migrar_visio.py`: `comparar` + `aplicar`):
- Al volver a correr, lo que nadie tocó (`automatica` / `en_revision`) **sigue al Visio**: nombre, ubicación (si cambia más de 5 m), si pide revisión; en cables, hilos (con sus hilos y colores), configuración si el diagrama ahora la dice, y clase.
- **Lo `editada` o `validada` nunca se pisa**: se anota como «conflicto» en `migracion_visio_log` y en la hoja **Diferencias** del Excel. Un cable también queda protegido si cualquiera de sus mufas está validada o editada.
- Lo que el Visio ya no da (otro tipo de nodo, extremos que cambian) se **conserva** y se reporta («ya no sale del Visio»); en una corrida con `--zona` o `--solo-mufas` no se evalúa.
- Si cambiar los hilos choca con empalmes existentes, no se cambia y se reporta.
- `--simular` también compara contra la base. **Contra la red real hoy: 0 por actualizar, 0 protegidas, 0 que ya no salen** (la reimportación no cambia nada). Al probarlo salió un falso positivo, los 2 033 clientes de la fase 3, que ya no entran en la comparación.
- Conteos nuevos de la corrida: `elementos_actualizados`, `cables_actualizados`, `diferencias_sin_aplicar`, `elementos_ya_no_en_visio`, `cables_ya_no_en_visio`.
- Límite conocido: la clave es nombre + coordenada a 4 decimales, así que mover una mufa más de ~5–11 m o renombrarla en el Visio crea una mufa nueva (la vieja queda como «ya no sale del Visio»). No se funden solas.

**Jan aprobó las fases 5, 6 y 7** y pidió probar la fusión por geometría. Resultado abajo.

## Fusión por geometría: medida y descartada (sigue apagada)

Medida sobre una copia de `red_fibra.db` (nada se escribió en la real), con el Excel de anillos como verdad. Herramienta nueva y repetible: `red_fibra/medir_fusiones_anillo.py` (abre la base de solo lectura).
- **16 mufas del anillo tienen diagrama propio** (77 pares de hilos conocidos). Las otras 87 no tienen diagrama propio y no se pueden medir.
- **Precisión 3,9 %** con toda la confianza; **0 de 9** por encima de 0,80 y ninguna llega a 0,85 (el mínimo de la regla). Con confianza ≥ 0,7 solo se recupera el 3,9 % de los pares del Excel. **La confianza del extractor no separa aciertos de errores.**
- **Volumen en toda la red:** 267 diagramas de mufa → 9 129 «fusiones» (34 por diagrama; la mufa DATATEX, que el Excel da con 1 tramo, sale con 58). Solo 689 (7,5 %) tienen confianza alta.
- **Por qué falla:** casi todos los trazos están en negro u otro color que no sigue el código TIA y no sirve para validar; en 1 620 (18 %) el cable «cercano» es el mismo en ambos extremos; y el extractor solo da números de hilo, **no dice a qué cable pertenece cada uno**. Aunque se aceptaran, no habría de dónde sacar el cable para crear el empalme.
- **Decisión:** `fusiones_geometria.usar` queda en `false` (comentario con la medición en `business_rules.yaml`). Meter ~9 000 empalmes con 4 % de acierto convertiría «sin diagramar» en datos falsos con aspecto de dato.
- Para verlo: reportes visuales de 6 mufas en `output/piloto_fusiones/index.html` (diagrama con las fusiones dibujadas encima; carpeta ignorada por Git). Si Jan los marca a mano se puede medir la precisión real, pero no se espera que cambie la conclusión.

## Empalmes del anillo: tamaño mínimo del cable (OK de Jan, corrida 7 en real)

Jan aprobó la propuesta: el número de hilo del Excel de anillos dice el tamaño mínimo del cable (hilo 26 → al menos 48).
- Regla nueva `migracion_visio.inferir_hilos.minimo_del_anillo: true` (`business_rules.yaml`). En `migrar_visio_contenido._hilos_minimos_del_anillo`: un cable del anillo sin cantidad de hilos, o con una cantidad solo deducida y menor, pasa al menor tamaño que cabe. Queda `estimado`, confianza baja, `configuracion_estimada`, con `ref_visio.hilos_origen = minimo_del_anillo` y la cantidad anterior. **No toca** lo que el Visio rotula ni lo `editada` / `validada`.
- La reimportación (fase 7) no lo deshace: un conteo deducido menor no baja un mínimo del anillo.
- **Corrida 7** (14:37, respaldo `respaldo_redes_2026-10-13_143722.json`): **86 cables** con hilos fijados, **192 empalmes nuevos** (con los 20 de antes, **212 de 233**); 21 siguen sin cable migrado. 4 modelos de mufa recalculados (4 pasan a 96).
- **Verificación:** 0 errores, 67 avisos (los de antes). Al verificar apareció un falso positivo: la regla «hilo conectado dos veces en la misma mufa» agrupaba por **nombre** de mufa, y hay cables entre dos mufas distintas con el mismo nombre (MUFA DE CORTE – MUFA DE CORTE), con un empalme en cada extremo. Ahora agrupa por mufa.
- **Pruebas: 344 pasan.**

**Pendiente:**
- Kayako sigue fuera por orden de Jan;
- regenerar el zip y dárselo a Marlon; reiniciar `start_service.bat`;
- actualizar `PLAN.md` y `ESPECIFICACION.md` con las decisiones del diagnóstico (hilos 2–144, clave nombre + coordenada, reservas incluidas).

## Migración Visio: fase 4 (modelo y bandejas) corrida en real

Jan: "Sigue con las demás fases" (sigo fase por fase sin parar entre ellas; la propuesta de empalmes del anillo y la lectura de fusiones dibujadas siguen sin aprobar, no se tocaron).

- **Migración `010_bandejas.sql`** (con respaldo previo): `conexiones.posicion_estimada`, `mufa_modelos.motivo` y `avisos`. Respaldo, Duplicar y restaurar los conservan.
- **`bandejas.py`** (nuevo), regla 6.5:
  - modelo: cable mayor ≤ 48 → 48 (2 bandejas), ≤ 96 → 96 (4), más → aviso; cada splitter necesita su bandeja (sube a 96 si hace falta); sangría en el motivo. Formato "domo"/"horizontal" solo si el texto lo dice. Todo `modelo_estimado` con su **motivo**.
  - bandejas de 24; la de un splitter 1xN admite N + 1 (entrada = posición 1, salida n = n + 1).
  - splitters desde la última bandeja hasta la 2: **la bandeja 1 queda para los empalmes directos** (un usuario puede poner un splitter ahí a mano). Empalmes directos desde la bandeja 1 por cable, buffer e hilo. Lo que pone la regla queda `posicion_estimada`.
  - operaciones del editor (API): `guardar_modelo_mufa` (48/96 y formato; achicar solo si las bandejas que desaparecen están vacías), `mover_empalme` (si la posición está ocupada se intercambian; los de un splitter se quedan en su bandeja), `bandeja_splitter`.
  - `mufa.guardar` ubica lo que el editor crea (splitter nuevo → bandeja libre; empalme nuevo → posición) y libera la bandeja de un splitter eliminado.
  - en la migración, un modelo que nadie tocó se recalcula si la regla de hoy dice otra cosa.
- **Corridas 5 y 6** (10:43 y 10:49, con respaldo): 3 061 mufas de 48 y 336 de 96, todas estimadas; 65 recalculadas al reservar la bandeja 1; **67 con avisos** (más splitters que bandejas, 1x32, cable de más de 96 hilos).
- **Verificación:** 3 reglas nuevas (empalme fuera de su bandeja, empalme ajeno en la bandeja de un splitter, modelo con avisos): 0 errores, 67 avisos (los modelos con avisos).
- **Editor de mufa:**
  - franja de resumen: modelo (48/96, formato, bandejas, "estimado" con su motivo), hilos empalmados / en splitter / libres, "sin diagramar", bandejas usadas, estado de la migración y avisos;
  - **"Ver bandejas"** (`redes/bandejas.js`, nuevo): una tarjeta por bandeja con sus 24 posiciones y el par empalmado (cable · buffer · hilo con sus colores TIA); la del splitter muestra entrada/salidas y bloquea el resto; arrastrar un empalme lo mueve; "Cambiar modelo"; selector de splitter por bandeja; lista de empalmes sin bandeja;
  - el tooltip de un empalme dice su bandeja y posición.
- **Corregido:** dos respaldos en el mismo segundo (009 y 010 seguidas) usaban el mismo nombre y el segundo pisaba al primero. Ahora el nombre avanza un segundo.
- **Pruebas:** 335 pasan (+7 en `test_redes_bandejas.py`).

## Migración Visio: regiones corregidas y fase 3 (splitters, clientes y empalmes) corrida en real

Jan: "Ponlos en la región que correspondan y sigue con el siguiente paso" (aprueba la fase 2).

**Regiones (corrida 2, 09:26, respaldo `respaldo_redes_2026-10-13_092639.json`):**
- "RED NODO MACIZO PEÑAS BLANCAS" es el Macizo de Peñas Blancas (El Cuá, **Jinotega**), no el puesto fronterizo de Rivas: corregido en `proyectos_base`.
- Regla nueva `troncales_a_region_km: 5`: una mufa de una carpeta sin región (ruta troncal) a ≤ 5 km del centro de una región va a esa región. Movió MUFA LA RAMAC → Segovias, Mufa del Matadero → León, MUFA DOS PINOS → Boaco y Chontales, Mufa de Zermat → Masaya.
- La corrida **mueve** lo ya migrado (elemento con su contenido; sus cables siguen la regla "el cable va con su origen"): 6 elementos y 14 cables. Lo editado por un usuario no se mueve; se reporta.
- Quedan en Managua, a propósito: Masachapa y Montelimar (San Rafael del Sur es del departamento de Managua). El Sauce sigue en León.
- **Revisar:** "MUFA NODO MATAGALPA" (carpeta Red Matagalpa) tiene la coordenada de Juigalpa. Se marca en el reporte, no se mueve.

**Fase 3 (corridas 3 y 4, 09:43 y 09:47, con respaldo):**
- `migrar_visio_contenido.py` (nuevo), corre con el mismo comando y aparece en el mismo reporte (hojas Splitters, Clientes, Empalmes).
- **1 395 splitters** (de 1 519 menciones con 1xN): 932 1x8, 284 1x16, 177 1x4, 2 1x32. OLT en 339, puerto OLT en 367, "depende de" en 56. 569 menciones sin tamaño y 3 "1x6" quedan en "No migrado".
- **191 listas de puertos → 1 214 puertos con cliente** (o con el splitter que alimentan). 67 listas numeradas no tienen un SPL con tamaño en su encabezado: son listas de hilos ("DE MF A A LA MF B / 29- …"), no se usan.
- **6 488 clientes de mufa sin puerto** (`mufa_clientes`), botón "Clientes (N)" en el editor.
- **2 033 clientes en el mapa** (62 % de los 3 279 códigos), en la punta de su acometida del KMZ. Kayako no se usa.
- **Empalmes del Excel de anillos: solo 20 de 233** se pudieron crear: 154 caen en cables sin cantidad de hilos, 38 nombran un hilo mayor que la cantidad deducida del cable y 21 no tienen cable migrado. Ver propuesta en el pendiente.
- Los 21 textos que nombran hilos y las fusiones dibujadas (geometría) no se usan: quedan "sin diagramar".
- **Editor de mufa:** cliente junto a cada salida del splitter; tooltip del puerto con código, nombre, ID y si está en el mapa; OLT / puerto OLT / "depende de" bajo el splitter; tooltip de un empalme con su fuente y confianza; botón "Clientes (N)". Nombre corto del splitter (el texto completo queda en `propiedades.texto_visio`) y separación según el alto de la etiqueta (también en "Ordenar").
- Corrida 4: los 1 395 splitters sin tocar se renombraron y reacomodaron (652 cambiaron de nombre). Lo que un usuario movió o editó no se toca.
- **Verificación:** 0 errores. **Pruebas:** 328 pasan (+3: fase 3, lectura de textos y mudanza de región). Página probada en Edge sin ventana con MUFA LA JOYA y MUFA EXTERNA FERIA GANADERA: 0 errores JS.

**Pendiente:**
- el OK de Jan para la fase 4 (modelo y bandejas);
- **decisión de Jan sobre los empalmes del anillo:** el número de hilo del Excel dice el tamaño mínimo del cable (hilo 26 → al menos 48). Propuesta: usarlo para fijar los hilos de esos 154 + 38 cables como "estimado" (confianza baja) y crear sus empalmes;
- regenerar el zip y dárselo a Marlon; reiniciar `start_service.bat`.

## Migración Visio: fase 2 (migrar toda la red base) terminada y aprobada

Jan: "Prosigue con lo siguiente" (aprueba la fase 1).

**Estado:**
- **Corrida real 1** (08:55), respaldo previo `respaldos_redes/respaldo_redes_2026-10-13_085530.json` + `.sql`. Reporte: `output/migracion_visio/migracion_2026-10-13_085530.xlsx`. Igual a la simulación de las 08:41.
- **13 proyectos base**, **3 503 elementos** (3 221 ubicación real, 102 estimada, 180 sin ubicar), **3 031 cables**, **35 820 hilos**.
- **Hilos de los cables:** Visio 870 · continuidad de ambos lados 122 · de un lado 612 · texto del KMZ 300 · **desconocidos 1 127**.
- **Trazo:** 946 siguen la línea del KMZ; 2 085 son rectas.
- **Cuadre con la fase 0:** 3 031 cables + 107 omitidos (un extremo OTRO o CLIENTE) = **3 138 pares**; los nodos repetidos (mismo nombre y coordenada) se migran una vez.
- **Verificación de la base:** 14 proyectos, 0 errores, 0 avisos.
- **Pruebas:** **325** pasan (+5 en `Pruebas/test_redes_migrar_visio.py`).
- **Página probada** en Edge sin ventana con los datos reales de "Red existente – Managua": 2 530 elementos (2 351 dibujados, 179 sin ubicar), 2 052 cables, ~0,3 s, 0 errores JS. El editor de mufa abre mufas y ODF reales con cables de hilos desconocidos.
- **La página cambió:** hay que regenerar el zip.

**Qué se hizo:**
- **`migrar_visio.py`** (nuevo): `--simular`, `--zona`, `--solo-mufas`, `--salida`.
  - Reporte Excel con hojas Resumen (con la comparación con la fase 0), Mufas, Cables y No migrado.
  - La corrida real hace respaldo, anota la corrida en `migracion_visio_corridas` y cada paso en `migracion_visio_log`, y escribe todo en una transacción.
  - Es idempotente por la clave Visio.
  - Las pruebas encontraron dos errores antes de la corrida real: una columna `id` ambigua y que un filtro reportaba pares fuera del filtro. Ambos se corrigieron.
- **Proyectos base** (`proyectos.py`, `problemas.py`): todos los ven; los editores los editan sin estar asignados.
- **ODF** se trata como nodo: icono propio en el mapa, "Abrir ODF" abre su editor, sirve de inicio del diagrama lógico y el trazado pasa por él.
- **Reserva** (mufa) y **mini nodo**: en la paleta y con icono (rollo de cable).
- **Hilos desconocidos** en todo el visor: "hilos desconocidos" y gris; el formulario del cable tiene "Desconocido" y los tamaños 2, 4, 6, 8 y buffers 2–8.
  - Guardar un cable con hilos desconocidos **ya no lo convierte en 12** (antes `hilos or 12`).
  - `sincronizar_hilos(None)` no toca los hilos.
- **Sin ubicar:** no se dibujan; el mensaje al abrir el proyecto dice cuántos hay.
- El inspector del cable muestra la configuración ("6x4, estimada").
- **Cables entre regiones** (8): se pueden editar aunque su otro extremo esté en el proyecto base vecino.
- La prueba de subida 008 → 009 crea sus datos con SQL, porque el código de hoy ya lee las columnas de la 009.

**Pendiente:**
- el OK de Jan para la fase 3 (splitters, clientes y empalmes);
- regenerar el zip y dárselo a Marlon; reiniciar `start_service.bat`;
- 22 elementos de "Red existente – Managua" están lejos de Managua (rutas troncales a Ramal o Dos Pinos, Masachapa): son carpetas Visio sin región en `proyectos_base`. Se pueden mover agregándolas a una región;
- una lista para colocar los 180 "sin ubicar" (hoy solo se cuentan).

## Migración Visio → mufas interactivas: fase 1 (modelo) terminada y aprobada

Jan: "Prosigue; con lo de los tickets de Kayako no hagas cambios de nada". Eso aprueba la fase 0 con sus respuestas y deja **Kayako fuera por ahora**: los clientes se ubicarán solo con el KMZ.

**Estado:**
- **Pruebas:** **320** pasan (+8 en `Pruebas/test_redes_visio_modelo.py`).
- **Migración** `009_red_existente.sql` **aplicada en `Presupuesto_visio`** (08:22), con **respaldo automático previo** `respaldos_redes/respaldo_redes_2026-10-13_082256.json` + `.sql`.
- **Verificación de la base:** 0 errores, 0 avisos.
- **No hubo cambios en la página** (el `.exe` no cambia): no se regeneró el zip.

**Qué se hizo:**
- **`009_red_existente.sql`:** se puede volver a correr sin error (`IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`) y lleva `-- respaldo: previo`.
  - **Dominios** `fuente_dato`, `confianza_dato` y `estado_migracion`.
  - **`proyectos`:** `es_red_base`, `zona`.
  - **`elementos`:** tipo `odf`; ubicación opcional solo si está `sin_ubicar`; `ubicacion_fuente`, `fuente`, `confianza`, `estado_migracion`, `ref_visio`, con índice único de la clave Visio por proyecto.
  - **`cables`:** hilos desconocidos (NULL) y de 2 a 144; buffers de 2 a 12.
    - Columnas calculadas `buffers` y `configuracion` ("6x4").
    - `configuracion_estimada`, `tipo_fibra`, `fuente`, `confianza`, `geom_fuente`, `estado_migracion`, `ref_visio`.
  - **`splitters`:** `propiedades` (OLT…).
  - **`conexiones`:** `bandeja` y `posicion_en_bandeja` (1–24, única por mufa).
  - **Tablas nuevas:** `mufa_modelos`, `mufa_bandejas`, `puerto_servicios`, `mufa_clientes`, `migracion_visio_corridas`, `migracion_visio_log`.
- **`migrar.py`:** respaldo automático (`respaldo.respaldar`) antes de una migración con `-- respaldo: previo`, si hay proyectos. Si el respaldo falla, la migración no se aplica.
- **`respaldo.py`:**
  - exporta e importa las columnas y tablas nuevas;
  - **exporta solo lo que existe**, porque el respaldo previo corre con el esquema anterior.
  - El primer intento real falló justo por esto. **La 009 no se aplicó**, se corrigió, y una prueba reproduce ese caso: base hasta la 008 → la 009 con su respaldo → restaurar.
- **`red.py`:**
  - acepta `odf`, `mini_nodo`, `reserva`, hilos 2…144 y buffers de 2 a 12;
  - **lo que el usuario edita manda:** un elemento o cable migrado que alguien cambia queda `editada`; una mufa sin ubicar o estimada que alguien coloca pasa a ubicación `usuario`; cambiar hilos o buffers quita `configuracion_estimada`; redibujar el trazo lo pasa a `usuario`.
  - Duplicar copia también lo nuevo.
- **`business_rules.yaml` → `migracion_visio`:**
  - 24 → 6x4 y 48 → 6x8, con sus alternativas;
  - 24 empalmes por bandeja; la entrada del splitter ocupa posición;
  - inferencia de hilos;
  - clientes solo desde el KMZ;
  - reservas incluidas;
  - geometría apagada;
  - proyectos base por región.
- **Pruebas** (base mínima del plan):
  - cables 24 6x4 y 12x2, 48 6x8 y 12x4, con buffer y color TIA;
  - hilos desconocidos;
  - `odf` y "sin ubicar";
  - mufas de 48 y 96 con sus bandejas, y splitter 1x8 en la bandeja 4 (capacidad 9);
  - posiciones únicas;
  - clientes por puerto y por mufa;
  - respaldo y Duplicar conservan todo;
  - la 009 se puede volver a correr;
  - respaldo automático solo si hay proyectos.
- **Documentación:** ARQUITECTURA.md (009, tablas y columnas nuevas, respaldo previo) y README (tabla de fases de la migración).

**Pendiente:**
- el OK de Jan para la fase 2 (migrar toda la red base, con `--simular` y reporte Excel primero);
- en la fase 2, el editor de mapa tendrá que dibujar `odf` y la lista de "Mufas sin ubicar" (hoy no hay ninguno);
- sigue pendiente el OK de la sección 8 del módulo de redes.

## 2026-10-14 · Medir: metraje final y total (antes de la fase 4)
- Pedido de Jan: al medir dos puntos, que diga el metraje y cuánto sería en total con las reglas de negocio.
- `visor_rutas/medicion.py` (`calcular` al instante; `estimar` llena la plantilla y recalcula con LibreOffice), sección `visor_medicion` en `business_rules.yaml` (1 conexión de cliente, 0 mufas), `Api.medir_ruta`, `ProveedorRemoto.medir_ruta` y `POST /visor/medicion` (sin Google, no cuenta para el límite), `web/mapa/medicion_total.js` integrado en `visor.js` (etiqueta, popup, tarjeta *Mis medidas*, copiar resumen).
- Pruebas: `test_visor_medicion.py`, `test_visor_pagina_medicion.py`, una en `test_visor_api.py`. Suite completa: 422 (421 + la corregida).
- Nota: `test_visor_api.py` corrido solo falla (importa `visor_api` después de fijar el entorno y gana el `.env`); en la suite completa pasa. Ya era así.
- Siguiente: el OK de Jan y la fase 4 de Visor v2.

## 2026-10-14 · Visor v2, fase 4 (primera parte): red dibujada en una carpeta
- Hecho: mufa, poste, cliente, nodo, ODF y cable en carpetas de Mis lugares (`redes/lugares_red.py`, `web/lugares/dibujar_red.js`), pestaña «Datos de red» en la ventana flotante, cable con imán (doble clic en el elemento final), metraje en el servidor, cables que siguen al elemento, borrar con cables (pregunta), «Guardar como proyecto» (`lugares_a_proyecto`), KMZ de ida y vuelta. Sin migración nueva.
- Pruebas: `test_redes_lugares_red.py` (6), `test_visor_pagina_fase4.py` (Edge) y ajustes a `test_visor_pagina_fase3.py` (12 botones, menú).
- Falta de la fase 4 (segunda parte): «Entrar a la mufa» desde cualquier mufa del KMZ (crear la mufa vacía al vuelo) y editar / borrar lo existente del KMZ y de la red base (migración 012 `kmz_cambios`). Después 4B, 5, 6, 7.

## 2026-10-14 · Visor v2, fase 4 (segunda parte): entrar a la mufa y editar el KMZ
- Hecho: migración 012 `kmz_cambios` (se aplica sola al abrir el visor, con respaldo previo), `redes/kmz_cambios.py` (editar / borrar / deshacer / listar), `mufas_existentes.crear_vacia` («Entrar a la mufa» crea una mufa vacía en el proyecto base `BASE-VISOR` si la migración no la tiene), `web/lugares/kmz_cambios.js`, ajustes en `lugares.js` y `redes/comun.js`.
- Pruebas: `test_redes_kmz_cambios.py` (4), `test_visor_pagina_fase4b.py` (Edge, KMZ de mentira) y `test_redes_visio_modelo.py` (ahora 4 migraciones nuevas). Suite completa: 434.
- No hecho a propósito: publicar los cambios a `red_puntos` / `red_lineas` (el presupuesto no cambia); mover vértices de líneas del KMZ.
- Fase 4 completa. Siguiente, con OK de Jan: 4B (ruta editable, presupuesto en vivo, ruta de fusión + Excel), 5, 6, 7.

## 2026-10-14 · Visor v2, fase 4B (primera parte): ruta editable y presupuesto en vivo
- Hecho: `calculo.RutaFija` / `calcular_con_ruta` (sin Google), `Api.calcular_con_ruta`, `estimar_presupuesto(…, ruta, postes_extra)`, `generar_presupuesto` con `ruta_editada` / `postes_a_mano`, remoto (`POST /visor/ruta_editada`, campos nuevos de `/visor/estimacion`), `main._generar_presupuesto_con(new_poles_extra=0)` (opcional; `POST /presupuesto` igual), `web/mapa/editar_ruta.js` (editar puntos, poste a mano, ruta a mano, volver a Google, guardar en Mis lugares).
- Pruebas: `test_visor_ruta_editada.py`, `test_visor_pagina_fase4c.py` (Edge, Python simulado) y una en `test_visor_api.py`.
- Límite conocido: la prueba de la página simula el aviso de Geoman (`pm:edit`); el arrastre real con el mouse hay que probarlo en el visor.
- Falta de la 4B: ruta de fusión (plan §7.2) y su franja en el Excel (§7.3). Después 5, 6, 7.

## 2026-10-14 · Visor v2, fase 4B (segunda parte): ruta de fusión y su Excel
- Hecho: `ruta_fusion_plan.py` (plan cliente → potencia, aérea / corte no se tocan por nombre, hilos del Excel de anillos o H__), `ruta_fusion_xlsx.py` (franja a nivel XML, respaldo, verificación, detección de Excel abierto, mapa opcional), `exportar_fusion.py`, `Api.redactar_fusion / exportar_fusion` (+ remoto `/visor/fusion/*`), `mufa_count_override` opcional en `main` (el presupuesto cuenta las mufas que se tocan), `web/mapa/editar_fusion.js`, `RUTA_FUSION_XLSX` en `.env.example` y `config.py`.
- Pruebas: `test_ruta_fusion.py` (libro armado a mano con la estructura del real), `test_visor_pagina_fase4d.py` (Edge), más casos en `test_visor_ruta_editada.py` y `test_visor_api.py`.
- Incidente: una primera versión de una prueba de la API exportó una franja de prueba (fila 15661, un paso «MF UNO») al libro REAL de `EjemploRutaFusiones` (el entorno de la prueba no cambiaba `RUTA_FUSION_XLSX`). Los entornos de las pruebas ahora lo apuntan a un archivo inexistente. El respaldo previo al cambio quedó en la carpeta temporal de pytest; ver el aviso a Jan.
- Falta: probar el libro modificado abriéndolo en Excel (no se puede aquí). Después 5, 6, 7.

## 2026-10-15 · Visor v2, fase 5: importar un KMZ a la red
- Hecho: migración 013 (`kmz_importaciones`, `kmz_importacion_detalle`, `kmz_cambios.importacion_id`), `redes/importar_kmz.py` (leer, comparar, importar, listar, detalle, mapa, aceptar, modo, descartar, aplicar, revertir, capa, publicar, revertir publicación), 12 métodos nuevos en `redes/api.py`, `web/lugares/importar_kmz.js` (ventana de revisión, mapa con colores, filas del árbol), el overlay de líneas / descripción en `kmz_cambios.js`, botón «Importar KMZ» habilitado.
- Pruebas: `test_redes_importar_kmz.py` (9; la publicación en una base de prueba con `red_puntos` / `red_lineas` propias y una guarda para que ninguna prueba toque el presupuesto real), `test_visor_pagina_fase5.py` (Edge), ajustes a fase3 (botón), seccion8 (tabla sin version) y visio_modelo (5 migraciones).
- Medido con la red real (solo lectura): `RED DE IDEAY.kmz` contra su propia caché = 35 526 sin cambios; leer 2,7 s, red actual 1,2 s, comparar 3,4 s.
- Nada se publicó en `red_puntos` / `red_lineas` reales. Falta que Jan pruebe con un KMZ real; la publicación conviene probarla primero con una importación pequeña.
- Siguiente: fase 6 (coordenadas masivas), fase 7 (modo remoto: subida de archivos grandes).

## 2026-10-15 · Visor v2, fase 6: coordenadas masivas
- Hecho: `masivas.py` (leer Excel / CSV / Word / texto, validar, lote en segundo plano con límite de Google por minuto, cancelar, Resumen.xlsx, .zip), `redes/masivas_red.py` (`lugares_desde_masivas`, `proyecto_desde_masivas`), 6 métodos en `Api` (+ remoto: `/visor/masivas/*`), sección `visor_masivo` en `business_rules.yaml`, `web/lugares/masivas.js`, botón de la barra habilitado.
- Pruebas: `test_masivas.py` (lectura y lote), `test_visor_masivas.py` (cálculo real con Google / LibreOffice simulados, guardar en lugares y proyecto), `test_visor_pagina_fase6.py` (Edge) y una de endpoints en `test_visor_api.py`.
- Bug propio encontrado por las pruebas: el lote se marcaba «terminado» antes de escribir Resumen.xlsx; ahora el estado cambia al final.
- Sin medir todavía el tiempo real por presupuesto con Google y LibreOffice reales (los números de la barra de progreso se estiman con lo que lleva el lote). Probar primero con 3-5 coordenadas.
- Siguiente: fase 7 (modo remoto: subida de archivos grandes y tareas largas).

## 2026-10-15 · Ajustes de la interfaz
- El buscador abre sus resultados sobre la barra de herramientas (z-index de la barra por debajo del buscador).
- Botón «Captura» (`modoCaptura` en visor.js, `body.modo-captura` en visor.css): solo el mapa a pantalla completa; Esc vuelve. Prueba: `test_visor_pagina_captura.py`.

## 2026-10-15 · Visor v2, fase 7: modo remoto de todo lo nuevo
- Hecho: `visor_rutas/subidas.py` (subida por partes en memoria), `Api.subir_iniciar / subir_parte / subir_fin` (+ cliente remoto y `POST /visor/subidas*`), `subida_id` en `importar_kmz_red` y `masivas_leer`, `Redes.subirArchivo` en la página (importar KMZ y coordenadas masivas suben por partes con porcentaje). `empaquetar_visor.py` comprueba que las páginas nuevas estén en el paquete. `VisorRutas.exe` y `.zip` regenerados; el .exe abre (con la marca de descarga puesta a todos sus archivos).
- Pruebas: `test_visor_remoto_fase7.py` (subidas y sus errores, lo mismo en remoto que en local para medir / ruta editada / fusión / masivas, importar KMZ y Mis lugares por la clave con los roles).
- Pendiente de comprobar por Jan: abrir el .exe en otra PC con una clave de editor y subir un KMZ real por el túnel (la prueba usa un cliente HTTP en memoria, no ngrok).
- Con esto se terminan las 7 fases del plan de la versión 2 de la especificación.


## Fase 8 (2026-10-15): postes existentes y actualizar la red desde el programa

**Qué pasaba con la ruta de Steven Gaitán (cliente 11.965211, -86.078320):** el cálculo contaba 31 postes nuevos y solo 1 existente aunque en el mapa se veían postes a lo largo de la ruta. Causa: la ruta y el presupuesto **no leen el KMZ, leen `red_puntos` / `red_lineas` (PostGIS)**, y esas tablas eran copia del KMZ anterior (29 891 puntos = el KMZ viejo exacto). El KMZ nuevo trae 376 puntos (324 postes, 23 mufas) y 71 líneas que la base no tenía; trae 76 puntos y 14 líneas que ya no estaban en el KMZ.

**Cambios de regla (`business_rules.yaml`, `presupuesto.py`, `main.py`, `calculo.py`):**
- `poles.max_span_between_existing_m: 100`: entre dos postes que **ya existen** el vano que dejó el campo se acepta hasta 100 m (antes 60) y no se agregan postes nuevos en medio. Antes del primero y después del último sigue valiendo 60 m / cada 50 m.
- `poles.existing_pole_search_buffer_m: 15 → 25`: los postes de la acera quedan a 15-25 m del eje de la calle por donde va la ruta.

**Actualizar la red desde el programa (administradores)** — `visor_rutas/redes/actualizar_red.py`, ventana «Importar KMZ», sección «Actualizar la red»:
1. **Subir KMZ nuevo:** reemplaza el KMZ vigente en `KMZ_PATH`; el anterior se mueve a `anteriores/` con la fecha; la caché del mapa se regenera sola; los usuarios remotos lo bajan al abrir el visor.
2. **Comparar con el presupuesto:** dice cuántos puntos / líneas del KMZ faltan en `red_puntos` / `red_lineas` y cuántos sobran. No escribe nada. Un elemento es «el mismo» si es de la misma familia (poste, mufa, reserva, pozo…) y está a ≤ 3 m (línea: sus dos extremos a ≤ 6 m).
3. **Poner el presupuesto al día:** inserta lo que falta (`tabla_origen = 'kmz sincronizado'`) y, si se marca, quita lo que el KMZ ya no trae (nunca lo publicado por el visor, `tabla_origen = 'visor'`; se niega si fuera quitar más del 35 % de la base). Una sola transacción; lo hecho queda en `datos_kmz/sincronizaciones/<id>.json` y **se puede revertir** (solo la última, ids incluidos).
- Métodos (`redes/api.py`): `estado_actualizar_red`, `subir_kmz_red`, `comparar_red_presupuesto`, `sincronizar_red_presupuesto`, `revertir_sincronizacion_red`.
- Pruebas: `test_redes_actualizar_red.py` (7), `test_visor_pagina_fase8.py` (1), regla de postes en `test_presupuesto.py`. Suite: 506 pasan.

**Pendiente de Jan:** abrir Importar KMZ → «Comparar con el presupuesto» → revisar → «Poner el presupuesto al día» (NO se ejecutó en la base real); volver a generar la ruta de Steven Gaitán.
**Pendiente (sin empezar):** subir archivos Visio desde el programa (el importador reconstruye `red_fibra.db` completa con LibreOffice, ver preguntas en el chat); exportar «KMZ de la red + Mis lugares» combinados.

### Dibujar encima de postes, mufas y líneas (2026-10-15)
Con una herramienta de dibujo activa (ruta a mano, postes a mano, cable, medida, marca, línea o polígono de Mis lugares, área de un proyecto) un clic sobre un poste, mufa, cliente o línea del KMZ abría la ficha y no ponía el punto. `web/mapa/modo_dibujo.js` (cargado después de Geoman) filtra en Leaflet los clics a los elementos mientras hay un modo activo: el clic llega al mapa y cada herramienta pone su punto; el nombre al pasar el mouse sigue saliendo y los puntos de ayuda de Geoman (cerrar polígono, terminar línea) siguen funcionando. Prueba: `test_visor_pagina_modo_dibujo.py` (clics reales sobre marcador, círculo de canvas y línea; falla sin el arreglo). Suite: 507 pasan. `VisorRutas.exe` / `.zip` regenerados.

### Diagrama Visio y editor de mufa en ventana aparte; aviso que no queda tapado (2026-10-20)
- **Aviso tapado:** el mensaje vivía dentro de la barra inferior y con la ventana angosta (Medir, Captura, Ruta a mano… ocupan el ancho) se quedaba sin espacio. Ahora `#mensaje` es un aviso flotante centrado sobre la barra (z-index 4000); los avisos se van solos (7 s, errores 12 s; «cargando» se queda hasta el siguiente).
- **Ventana aparte** (botón «⧉ Ventana aparte» en la pestaña Diagrama, en el visor de diagrama a pantalla completa y en el editor de la mufa): abre una ventana de Windows propia (`Api.abrir_ventana('diagrama'|'mufa', …)`, pywebview `create_window` con la misma `Api`, así que sirve en modo local y remoto). Se puede mover a otro monitor o dejar al lado de la otra para llenar la mufa a mano mirando el Visio. Una sola por mufa y tipo (si ya está abierta se trae al frente). Es la misma página con `visor.html?ventana=diagrama|mufa&nombre=…`: solo muestra esa ventana, sin mapa ni paneles ni capas del KMZ.
- En la ventana del editor de mufa, «Ver Visio original» abre el diagrama en OTRA ventana aparte (solo si la mufa tiene diagrama). Cerrar el editor (✕ / Guardar y cerrar / Esc) cierra la ventana; en la del diagrama, Esc la cierra. Al cerrar la ventana principal se cierran todas.
- Al pasar el editor a ventana aparte se pregunta primero por los cambios sin guardar. Cerrar la ventana con la X de Windows con cambios sin guardar los pierde (no se avisa).
- Pruebas: `test_visor_ventana_aparte.py` (7: Api con `webview` falso, aviso con ventana de 760 px, botones, ventana de diagrama y de mufa). **No probado:** abrir de verdad la ventana nativa de WebView2 ni el editor de mufa completo dentro de ella (necesita pantalla); Jan debe probarlo. Suite: 514 pasan.

**Corrección (2026-10-20, misma tarde):** la ventana aparte salía con ERR_FILE_NOT_FOUND porque WebView2 convierte el «?» de una URL file:// en parte del nombre del archivo; los parámetros ahora van después de «#» (isor.html#ventana=diagrama&nombre=…). Probado en un WebView2 real: abre una sola ventana por mufa, carga la página con la clase ventana-aparte y el título, y se cierra con cerrar_ventana. Además, el pin magenta de la mufa buscada ahora va en un panel (uscada, z 585) DEBAJO de los puntos del KMZ (590): ya no tapa el marcador original de la mufa (popup con Entrar a la mufa / Ver diagrama). Prueba nueva con clic real que falla sin el arreglo. Suite: 515 pasan.



## Fase 9 (2026-10-20): íconos propios del KMZ, elementos en el mismo punto, botón Lugares
- **«Lugares» a la altura de «Resumen»** (`.abrir-lugares`: top 10 px, 32 px de alto).
- **Ícono / color / tamaño propio de lo que sale del KMZ** (mufas, postes, clientes, líneas…): migración `014_kmz_estilos.sql`, `redes/kmz_estilos.py` (`estilos_kmz`, `guardar_estilo_kmz`, `quitar_estilo_kmz`), `web/lugares/kmz_cambios.js`.
  - Por **elemento**: en su ficha, «Cambiar ícono…» (puntos) o «Cambiar estilo…» (líneas: color, grosor, opacidad) y «Quitar estilo». Usa el mismo selector de Mis lugares (pushpins, letras, números, figuras, «sin ícono»; color libre, escala, opacidad).
  - Por **carpeta**: clic derecho en la carpeta del árbol → «Ícono / estilo…» / «Quitar estilo». Vale para todo lo que hay debajo; el estilo de un elemento gana al de su carpeta y el de una carpeta gana al de la de arriba.
  - Es **de todos** (red compartida; solo administradores y editores lo cambian; lo ven todos, también el .exe). El archivo KMZ y el presupuesto no se tocan.
- **Varios elementos en el mismo punto** (mufa + splitter, poste + mufa): un clic sobre el punto lista los que hay (a ≤ 14 px) y cada uno abre su ficha, con «Mover» para separarlos, «Cambiar ícono…», «Entrar a la mufa»… (`lugares.js`: `superpuestos` / `elegirSuperpuesto`). Los postes agrupados en un círculo con número no cuentan.
- Pruebas: `test_redes_kmz_estilos.py` (12), `test_visor_pagina_fase9.py` (1: apilados, ícono de elemento y de carpeta, línea, quitar, persistencia, altura del botón). Suite: 528 pasan. La migración 014 se aplica sola al reiniciar `start_service.bat` (con respaldo previo).
- **Pendiente:** íconos de lo que dibuja la ruta (postes nuevos/existentes, mufas en ruta, nodos Visio) y de la «mufa buscada»: son capas del visor, no del KMZ; falta decidir si el cambio es de todos o personal.

### Abanico e íconos con imagen propia o texto (2026-10-20)
- **Abanico:** al hacer clic en puntos apilados, además de la lista, se abren en abanico debajo del punto (cada uno con su ícono en un círculo y una línea fina al punto); clic en uno abre su ficha y el abanico se recoge (también al cerrar la lista, al hacer clic fuera o al cambiar el zoom). Detalle de Leaflet: el clic cierra primero la lista («preclick»), por eso el abanico se recoge 150 ms después.
- **Ícono con imagen propia u otra opción:** el selector de íconos (el de Mis lugares y el nuevo de los elementos y carpetas del KMZ) trae ahora **«Imagen propia…»** (PNG, JPG, WebP o GIF; se reduce a 96 px en la página y viaja como data URL ≤ 80 000 caracteres) y **«Texto o emoji»** (1 a 3 caracteres: «OLT», «5G», 🔌, dentro de un círculo del color elegido). Siguen el color, la escala y la opacidad (la imagen solo escala y opacidad). Tipos nuevos `imagen` y `texto` en `lugares_iconos.py` (validación, PNG para el KMZ exportado de Mis lugares, nombre seguro de archivo) y en `kmz_estilos.py`. Se rechaza SVG, URLs externas, imágenes muy grandes y textos con `< > & " '`.
- Pruebas: abanico y selector con clic real y archivo real en `test_visor_pagina_fase9.py`; validación y exportación en `test_redes_kmz_estilos.py`. Suite: 538 pasan. `VisorRutas.exe` / `.zip` regenerados.
- **No probado:** que Google Earth muestre bien el emoji de un ícono de texto exportado (depende de la fuente `seguiemj.ttf` de Windows; sin ella sale en blanco y negro).

### Buscar dentro del diagrama de Visio y círculo activable (2026-10-20)
- **Campo «Buscar en el diagrama»** sobre el diagrama, en la pestaña Diagrama y en el visor a pantalla completa (`web/mapa/busqueda_diagrama.js`). Busca en los textos del diagrama (`fusion.buscar_en_diagrama`, tabla `textos_crudos`):
  - **Texto:** todas las palabras, sin acentos ni mayúsculas; MF, MC y MUFA son lo mismo. Ejemplo: «ferreteria», «spl», «sangria», «puerto 3».
  - **Coordenada** (cualquier formato del buscador, también grados o lat/lon al revés): halla los textos del diagrama que ESCRIBEN una coordenada a ≤ 25 m y dice a cuántos metros está cada uno. Los diagramas la escriben como «12.111510°, -86.234059°» (el grado a veces roto): se tolera.
  - El diagrama se acerca al resultado y lo marca con un círculo naranja. Enter / Mayús+Enter, ▲ ▼ y la lista pasan entre resultados; Esc borra. Si se cambia de diagrama con algo escrito, busca ahí.
- **Círculo** (casilla junto al campo): muestra u oculta el círculo de la mufa y el de lo encontrado; se recuerda en esta PC y las dos casillas (panel y pantalla completa) van juntas. «Ubicar mufa» sigue acercando aunque el círculo esté apagado.
- Servidor: `Api.buscar_en_diagrama`, `ProveedorRemoto.buscar_en_diagrama` y `GET /visor/diagrama/{md5}/buscar` (declarado antes de `/{pagina}`); funciona en modo remoto.
- Probado con datos reales: «ferreteria» y la coordenada de la MUFA FERRETERIA LA PRINCIPAL dan su texto (a 0.1 m) en 0.01 s. Pruebas: `test_visor_fusion.py` (3 nuevas), `test_visor_api.py` (1), `test_visor_pagina_busqueda_diagrama.py` (1). Suite: 543 pasan.

### Íconos del visor para todos (2026-10-20)
- **«Íconos del visor…»** (Lugares → Capas del visor): cambia el ícono de lo que dibuja el propio visor —punto de conexión, cliente, mufa buscada, mufa intervenida, mufa en ruta, nodo Visio, poste existente, poste nuevo y poste marcado como existente— con el mismo selector de íconos (pushpins, letras, números, figuras, texto/emoji, imagen propia; color, escala, opacidad) y «Restablecer». **El cambio es de todos** (se guarda en `redes.kmz_estilos` con alcance `capa` y clave `capa|<id>|`, migración `015_kmz_estilos_capas.sql`) y lo hacen administradores y editores; al abrir el visor se leen y se aplican. Se redibujan al instante el mapa, la mufa buscada y la leyenda (`web/mapa/iconos_visor.js`, `visor.js: aplicarIconosVisor`).
- Pruebas: `test_redes_kmz_estilos.py` (capas conocidas, permisos), `test_visor_pagina_iconos_visor.py` (cambiar, ver en mapa y leyenda, restablecer, otra sesión). Suite: 545 pasan.
- **Mapa al norte:** el mapa del visor (Leaflet) no gira: siempre tiene el norte arriba; no hay ningún gesto ni control que lo rote. Los diagramas de Visio sí están dibujados en cualquier orientación (no son geográficos).

## Reglas nuevas de conexión y ruta de fusión — fase A (2026-10-20)
Reglas de Jan: [1] punto de conexión nunca de mufa de corte (MC), aérea ni punta plana / plancha; [2] ruta de fusión sin esas ni mini nodos; [3] origen de tráfico: solo el del nodo; [4] intervención de mufa = mufas hasta el splitter sin las anteriores; [5] empalme = mufas + 2 del splitter; [6] visita técnica solo en plaza, edificio o centro comercial; [7] splitter secundario con puertos libres y hilos libres entre mufas; [8] si no hay splitter y harían falta más de 10 intervenciones: reservas para un splitter secundario; [9] pozos: fibra en ducto en vez de aérea.

**Hecho en esta fase (1-6):**
- `reglas_mufas.py` + sección `mufas_no_usables` de `business_rules.yaml` (palabras completas, sin acentos; «FUERZA AEREA» es excepción) y `excluded_tipo_keywords` con las carpetas «de corte», «aerea», «punta plana», «plancha». Lo usan `db.py` (3 consultas: punto de conexión, candidatos por ruta y mufas de la ruta, con regex en PostgreSQL), `main.py` / `visor_rutas/calculo.py` (mufas de la cadena, del camino de diagramas y de la ruta no se cuentan; un nodo Visio de esos tipos tampoco es punto de conexión) y `ruta_fusion_plan.py` (no se tocan; mini nodo solo en la ruta de fusión).
- «Origen de trafico (MF)» del Excel ya no se escribe (`origin_node: ""`): solo «Origen de Tráfico (Nodo)».
- Empalmes del respaldo = mufas intervenidas + 2 (`fixed_events.backbone_splice_extra_splitter`), solo si se conecta a una mufa existente (no a una reserva).
- Visita técnica = 1 cuando el nombre del cliente, el comentario del ticket o el servicio traen plaza, edificio, centro comercial o CC (`technical_visit.keywords`); si no, 0.
- Datos reales: 962 de 3 141 mufas del KMZ quedan excluidas (43 por carpeta, 933 por nombre; casi todas se llaman literalmente «MC»).
- Pruebas: `test_reglas_mufas.py` (30) y dos expectativas de `test_api.py` (+2 empalmes). Suite: 575 pasan.

**Falta (fase B, necesita datos y decisiones de Jan):** [7] splitter con puertos libres (¿de dónde sale «libre»?), [8] reservas para un splitter secundario cuando pasan de 10 intervenciones, [9] pozos → fibra en ducto.

## Reglas nuevas — fase B (2026-10-20, tarde)
**Hecho:**
- **Íconos apilados en abanico, de cualquier capa** (`web/mapa/superpuestos.js`): se engancha al clic de los marcadores y círculos de Leaflet (KMZ, ruta, nodos Visio, mufa buscada, coordenada, Mis lugares), no a cada capa. Un clic sobre un punto con otros a ≤ 14 px (el ancla, no el dibujo: un pin es alto) abre la lista y el abanico; al elegir uno se reenvía el clic a esa capa (su popup de siempre). No actúa mientras se mide o se dibuja. Sustituye al selector que solo conocía los elementos del KMZ. Pruebas: `test_visor_pagina_superpuestos.py`.
- **Pozos → fibra en ducto** (`business_rules.yaml: ducto`, `presupuesto.tramos_ducto`, `db.find_pozos_near_route`, `main.hardware_fibra`): los pozos de la ruta (a ≤ 15 m) forman tramos de ducto (pozos a ≤ 100 m uno de otro son una corrida; una corrida que termina a ≤ 60 m de la mufa de conexión o del cliente llega hasta ahí). Fila «Instalacion de Fibra en Ducto …» = metros de ducto; fila aérea = el resto; sin postes en el ducto (los existentes ahí no se usan) y los nuevos solo en los tramos aéreos; ruta toda en ducto = todo el cable incluidas reservas en ducto. El material de fibra del cable usado suma aéreo + ducto (`same_as_install` acepta lista). Sin pozos, el presupuesto no cambia. `calculo.py` (visor) hace lo mismo y añade `ducto` al resultado solo si hay pozos. Pruebas: `test_ducto.py` (17).
- **Splitter secundario sugerido** (`splitter_secundario` en el yaml, `db.find_reservas_cercanas`, `ruta_fusion_plan.armar`): con MÁS de 10 mufas por intervenir (sin corte / aérea / punta plana / mini nodo) el plan agrega al inicio un paso «MF NUEVA» con splitter 1/8 en la reserva más cercana al cliente (punto de la carpeta «reserva» o poste / punto cuyo nombre diga RSV, RVA o RESERVA, hasta 400 m) y un aviso rojo; solo sugerencia, el presupuesto no cambia. Sin reserva cerca, solo el aviso.
- Empalmes del respaldo = intervenciones + 2 (ya estaba; hoy se suman siempre que se conecta a una mufa existente).
- Suite: 597 pasan.

**Medido (no implementado) — splitters en los diagramas:** 2 072 textos de splitter en toda la base de Visio: 1×8 = 1 048, 1×16 = 310, 1×4 = 139, sin tipo = 570. La palabra SECUNDARIO aparece en 466 y PRINCIPAL en 310. Solo 280 (13 %) traen la lista «1- cliente … 7- 8-» por puerto (77 con algún puerto libre). El resto exige leer el DIBUJO (color del splitter y flechas hacia los números), que no está unido a nada: hay que analizar la geometría de la capa .odg (líneas, polilíneas, textos). Primer vistazo hecho con un diagrama real (MUFA FERRETERIA LA PRINCIPAL): las líneas de color y las flechas punteadas rosadas llegan junto a los números 1…8 del splitter. Falta decidir si se invierte en ese análisis.
**Sin hacer:** continuidad (hilos verdes, no se toca) y «hay splitter con puertos libres / es morado o dorado» dependen de ese análisis del dibujo.

### Estudio medido de los splitters en los diagramas (2026-10-20)
Ver docs/modulo_redes/ESTUDIO_SPLITTERS.md y los scripts en ed_fibra/estudio_splitters/. Resumen: [1] la conversión de LibreOffice **no desplaza** textos ni líneas (43 .vsdx: 17 556 extremos de línea, 100 % a ≤ 0,05 cm; textos 0,00 cm); [2] **secundario / principal por el color** del texto sí es confiable (morado #7030a0 → secundario, precisión 99,6 %; naranja/dorado → principal ~94 %; el negro no dice); [3] **puertos libres por las líneas** que llegan al número NO es confiable aún: con 1 186 puertos de referencia (52 libres) la mejor regla halla 62 % de los libres pero marca 141 ocupados como libres (precisión 18 %). Propuesta: confirmación humana en pantalla y seguir la línea hasta lo que conecta.


## Splitters de los diagramas, rellenados en cada ruta (2026-10-21)
**Hecho:** al generar una ruta de fusión se leen los splitters de los diagramas de sus mufas, se guardan y se muestran en cada parada.
- `visor_rutas/splitters_diagrama.py`: lee los marcos de texto del `.odg` convertido. Clase por color (morado = secundario, dorado = principal), si es negro por la palabra SECUNDARIO / PRINCIPAL y si no «por confirmar»; relación 1/8, 1/16…; cuadro de números de puerto a ≤ 8 cm del mismo color; lista «1- cliente … 8-» a ≤ 10 cm (renglón en blanco = libre). Sin lista los puertos quedan «desconocido» (las líneas no alcanzan, ver el estudio). Solo se muestran los splitters a ≤ 45 cm de donde está dibujada la mufa (todos si no se sabe).
- Migración `016_splitters_diagrama.sql` (tabla nueva `redes.splitters_diagrama`: md5 + posición, lo leído en `auto`, lo `confirmado` por una persona, `veces_visto`); `redes/splitters.py` (`registrar`, `de_diagrama`, `confirmar`, `quitar_confirmacion`; solo administrador/editor, versión optimista) y 3 métodos en `redes/api.py`. `calculo.py` los guarda en cada ruta con su propia conexión corta: si la base de redes no está, la ruta sale igual sin splitters guardados.
- Plan de fusión (`ruta_fusion_plan.armar`): cada parada a tocar dice su splitter preferido (secundario con libres > secundario por confirmar > principal) en `info_splitter`; la primera parada desde el cliente con un secundario con puertos libres recibe `splitter` (1/8, 1/16…) y un aviso; si solo hay puertos por confirmar, un aviso.
- Pantalla: en cada parada, bloque «Splitters del diagrama» con botón Confirmar / Ver (`web/mapa/splitters.js`): se marca la clase y cada puerto libre / ocupado / no sé; se guarda y gana sobre lo leído en las rutas siguientes.
- Hallazgo: la expresión que leía «1- cliente» del estudio usaba `\s*` y un renglón en blanco se tragaba el siguiente; corregida (`[ \t]*`). Los 52 puertos libres del estudio pueden ser más; los números del estudio quedan como cota inferior.
- Pruebas: `test_splitters_diagrama.py`.
**Falta:** que la ruta de fusión se detenga en el splitter con libres (hoy solo se marca; las mufas posteriores siguen en el plan), medir hilos verdes, y usar lo confirmado para afinar la lectura automática.

## App de campo — fase 1 (2026-10-21): datos y API
Decisiones de Jan: se usa la misma `VISOR_API_KEYS` por ahora (después una clave propia de técnicos); poste y mufa se aprobarán a la red base y reserva / solitaria / cliente / otro a Mis lugares (que ya vive en PostgreSQL: `redes.lugares_carpetas` / `lugares_elementos`, por usuario y compartible); red de referencia desde `red_puntos`/`red_lineas`; umbrales 10 m (precisión) y 5 m (duplicado) en `business_rules.yaml: campo`.
**Hecho:** migración `017_campo.sql` (rol `tecnico`; tablas `campo_jornadas`, `campo_puntos`, `campo_fotos`, `campo_trazos`, `campo_ubicaciones`; trigger `NOTIFY 'campo'`), `redes/campo.py` (jornadas, puntos idempotentes por `uuid_cliente`, permisos del técnico, fotos con miniatura, duplicados, sincronización con `desde`), `visor_rutas/campo_api.py` (`/visor/campo/jornadas|puntos|fotos|foto`, límite por persona, errores `{ok:false,error,errores}`), `ServicioRedes.ejecutar`, router incluido en `main.py` (no toca `/presupuesto`). Las fotos suben como cuerpo crudo (Content-Type image/*) porque no está `python-multipart`. Pruebas: `test_campo.py` (13). Falta: aprobar/rechazar (fase 4), trazos y ubicación (fases 4-5), la PWA (fase 2).

## Calibración de la ruta por calles (2026-10-21)
**Problema:** el cliente de «MF INTERNA LOS SOLICEOS» está a 43 m en línea recta pero Google (en auto) da 460 m: ambos extremos se pegan a una calle y la ruta rodea la manzana (en la captura, ~700 m con los postes). Medido con Google: auto 460 m, a pie 460 m (no hay camino mapeado), recta 43 m.
**Hecho:** `routing.calibrar` dentro de `routing.get_route` (lo usan el presupuesto, el visor, las masivas y la comparación de mufas candidatas): si la ruta en auto supera `detour_factor` (2) × la recta + `min_extra_m` (150), se pide la ruta A PIE y se usa si es < 85 % de la de auto; si el cliente está a ≤ `direct_max_m` (150 m) y aún da > 3 × la recta + 150, se usa la LÍNEA RECTA. `Route` trae `modo` (driving / walking / directa) y `aviso`, que sale en los avisos del visor y del presupuesto («validar el trazado»). Todo en `business_rules.yaml: route_calibration` (`enabled: false` lo apaga). Una ruta normal no pide nada más a Google. Pruebas: `test_routing_calibracion.py` (9).
**Ojo:** la línea recta es de ~43 m de cable sobre propiedad privada; por eso el aviso. Si prefieren otro umbral, se cambia en el yaml.

## App de campo — fase 2 (2026-10-21): la PWA básica
**Hecho:** `GET /campo` (sin clave; 404 si `VISOR_API_KEYS` está vacío) sirve `visor_rutas/campo_web/` (`index.html` con `<base href="/campo/">`, `campo.css`, `api.js`, `mapa.js`, `app.js`) y el Leaflet del propio visor (`/campo/lib/leaflet/…`, sin CDN); solo se sirven archivos de esas dos carpetas con extensiones permitidas (probado contra `../`, `%2e%2e`, carpetas y código). Nuevo `GET /visor/campo/config` (persona de la clave y límites). La app: pantalla de clave (se guarda en el teléfono; mensajes para clave mala y para falta de rol), mapa satelital / calles (Esri / OSM, hace falta señal para los mosaicos), ubicación en vivo con círculo de precisión, botones grandes Poste / Mufa / Reserva / Solitaria / Cliente / Otro; al tocar uno toma el GPS (si la precisión es peor que `precision_max_m` muestra «Esperando mejor señal…» con «Usar igual» o «Marcar en el mapa» con mira), formulario corto (tipo de poste, capacidad y formato de mufa, nombre sugerido «Poste 3», notas, fotos de la cámara comprimidas a 1600 px / calidad 0.7), envío del punto y luego de las fotos (reintentable sin duplicar), aviso de posible duplicado, lista de la jornada con editar / borrar los pendientes y cerrar jornada. Pruebas: `test_campo_pwa.py` (3 de servidor y 1 de punta a punta en Edge móvil con GPS simulado contra la API real y la base de pruebas).
**Falta (fase 3):** sin señal (IndexedDB y reintentos), instalación en Android / iPhone, ayuda por plataforma. Hoy, sin conexión, el formulario se queda abierto y se reintenta a mano.

## App de campo — fase 3 (2026-10-21): sin señal, reintentos e instalación
**Hecho:** todo punto se guarda primero en el teléfono (`campo_web/cola.js`, IndexedDB `campo-cola`: el punto con su uuid y sus fotos ya comprimidas) y de ahí sale al servidor. Se reintenta al abrir la app, al volver a primer plano, al evento `online`, con el botón «Enviar ahora» (franja amarilla «N pendientes de enviar»), cada 30 s mientras haya cola y, en Android, con Background Sync desde el service worker aunque la app esté cerrada (iPhone no lo tiene: se envía al abrir). Enviar es idempotente (uuid del punto y de cada foto): un corte a media foto deja el punto y la primera foto en el servidor, y el reintento termina sin duplicar. Un punto que el servidor rechaza por sus datos queda en la cola «Con error» (rojo, con el motivo) y no se reintenta solo; una clave que dejó de servir, un 429 o un 5xx solo detienen el envío. Los puntos aún en el teléfono se pueden editar (nombre / notas) o borrar. `sw.js` guarda los archivos de la app (abre sin señal con la última sesión: persona, jornada y puntos en caché) y los mosaicos del mapa que ya se vieron (hasta 900); `/campo` redirige a `/campo/` para que el service worker lo controle; `manifest.webmanifest` + íconos 192 / 512 / maskable / apple-touch. `ayuda.js`: detecta iPhone / Android / otro (iPad en modo escritorio incluido); en iPhone sin instalar muestra la franja «instale la app para no perder puntos» y los pasos de Safari (Compartir → Agregar a pantalla de inicio); en Android el botón «Instalar app» aparece con `beforeinstallprompt`; pide almacenamiento persistente. Pruebas: `test_campo_offline.py` (4, en Edge móvil contra la API real: sin red con foto, reinicio sin red y envío al volver; corte a media foto, error de datos y clave mala; ayuda por plataforma; detección de plataforma) y `test_campo_pwa.py` ajustado.
**Límites:** una web app no puede rastrear en segundo plano (la ubicación solo con la app abierta); los mosaicos nuevos del mapa necesitan señal; en iPhone Safari sin instalar el sistema puede borrar los datos del sitio. Falta: túnel HTTPS (fase 6) — sin HTTPS no se instala ni funciona el GPS en el teléfono.

## App de campo — fase 4 (2026-10-21): el visor ve el campo en tiempo real y decide
**Servidor** (`redes/campo.py`, `campo_api.py`, `campo_eventos.py`): `ubicacion` / `ubicaciones` (la última ubicación de cada técnico; la app la manda cada 20 s con la app abierta; el revisor ve a los de las últimas 8 h con «hace N min»), `rechazar` (con motivo, que el técnico lee en su lista), `aprobar` en lote a **red base** (poste y mufa → `redes.elementos` del proyecto base elegido —si hay uno solo se usa solo— con `fuente usuario`, confianza alta si el GPS fue ≤ 10 m, la mufa «48 domo» como `capacidad` / `formato`, el técnico y la captura en `propiedades.campo`, e historial), a **un proyecto** propio (poste, mufa y casa de cliente; el editor debe estar asignado) o a **Mis lugares** (marca con letra y color por tipo, el detalle y las fotos en la descripción, en la carpeta «Campo – técnico» del propio revisor, creada la primera vez); cada punto va aparte: el que no puede decir por qué y los demás siguen. Un punto «corregido» (editado por un revisor) también se puede aprobar. Al listar, el revisor recibe `duplicado` de cada punto por decidir (elemento o punto de campo del mismo tipo a ≤ 5 m). `GET /visor/campo/eventos` (SSE, solo revisores): un hilo con `LISTEN campo` (reconecta solo) reparte los NOTIFY del trigger; latido cada 15 s. Los métodos de revisión van por la lista `METODOS` (`campo_puntos|jornadas|ubicaciones|editar|aprobar|rechazar|foto`) y así funcionan igual en modo remoto.
**Visor** (`web/mapa/campo_visor.js`): sección «Levantamiento de campo» en Lugares (casilla por técnico y jornada, círculo con la letra del tipo y color por estado; «Ubicación de los técnicos»), vista **Campo** en el menú (con insignia de pendientes; oculta para quien no revisa) con filtros, selección en lote, Editar / Aprobar… / Rechazar… (diálogos), miniaturas y foto grande, «Ver en mapa». Tiempo real: `Api.campo_escuchar()` (local: LISTEN en la PC del servidor; remoto: `ProveedorRemoto.escuchar_campo`, SSE con reconexión y espera creciente) empuja cada aviso a `CampoVisor.evento()` con `evaluate_js`; la página pide solo lo que cambió, avisa «juan agregó un poste «Poste 7»» y, tras reconectar, vuelve a pedir todo; además un refresco de seguridad cada 2 min.
**Pruebas:** `test_campo_revision.py` (11: ubicación, rechazar, aprobar a red / proyecto / Mis lugares, duplicados, NOTIFY → suscriptores, reconexión tras cortar la conexión, SSE contra el servidor real solo para revisores), `test_campo_puente.py` (8: modo local y remoto hasta la página, cliente SSE con reconexión y errores 401 / 403 / 404), `test_visor_pagina_campo.py` (2: el visor real con capa, tiempo real, filtros, editar, rechazar con motivo, aprobar en lote, duplicado y foto → Mis lugares; y que un lector no ve nada).
**No probado aún:** `evaluate_js` en la ventana pywebview real y el modo remoto con el .exe contra el túnel (hay que reconstruir `VisorRutas.zip` y probar con un técnico real); la PWA en un teléfono.

## App de campo — fase 5 (2026-10-21): cables en campo y red de referencia en el teléfono
**Servidor** (migración `018_campo_trazos_revision.sql`, `redes/campo.py`, `campo_api.py`, `db.find_red_en_bbox`): `POST/GET /visor/campo/trazos` y `PATCH/DELETE /trazos/{id}` (idempotentes por `uuid_cliente`; modo puntos / postes / recorrido, tipo ADSS o FLAT, hilos, notas, hasta 3000 puntos dentro de Nicaragua; largo calculado con PostGIS; el técnico solo ve y edita los suyos pendientes). Revisión (`campo_trazos`, `campo_editar_trazo`, `campo_aprobar_trazos`, `campo_rechazar_trazos` en la lista remota): **rechazar** con motivo; **aprobar** a la red base / un proyecto como un **cable real** (por `red.guardar`: sus extremos se pegan al poste o mufa del proyecto a ≤ 20 m —`trazo_extremo_m`—, nombre «Cable PT-1 – MF-2», clase distribución, tipo y hilos del técnico —12 si no los puso—, con sus hilos 1..N e historial; si un extremo no tiene poste cerca o ambos son el mismo, se dice y el trazo queda pendiente) o a **Mis lugares** como ruta. `GET /visor/campo/red?bbox=oeste,sur,este,norte` (zona de hasta 0,03°): puntos y líneas del KMZ de la base del presupuesto (`red_puntos` / `red_lineas`, líneas simplificadas) y de la red base del módulo de redes, en JSON liviano; si la base del presupuesto no responde sale solo lo del módulo con un `aviso`. Medido con la base real: una zona de 2 km = 524 puntos y 130 líneas, 103 KB, 0,23 s.
**Teléfono** (`campo_web/trazo.js`, `red.js`, `app.js`): botón «Trazar cable» (junto a las acciones): se toca el mapa (lo que cae a ~22 px de un poste o punto conocido se pega a él), «Mi ubicación», «Centro del mapa» (mira) o «Grabar recorrido» (un vértice cada 5 m con GPS de ±25 m o mejor); Deshacer, Terminar, Cancelar (pregunta si hay más de 2 puntos); formulario de tipo, hilos y notas; se guarda en la cola del teléfono igual que un punto (sin señal espera; no se pierde al cerrar la app; error de datos → «Con error»). Los cables de la jornada se ven en el mapa (color por estado, punteado si no se han enviado) y en la lista (ver / borrar los pendientes). **Red de referencia**: zonas de 0,02° que se piden una vez y se guardan en IndexedDB (12 h; sin señal se usa la guardada), dibujadas desde zoom 15 (líneas) y 16 (puntos), botón ⌁ para ocultarla; el formulario de un punto avisa «Ya hay algo aquí: PT-A a 2 m. ¿Es el mismo?». El service worker pasa a `campo-v5` y guarda `red.js` y `trazo.js`.
**Visor:** los cables salen en la capa de campo (línea por estado, con Aprobar / Rechazar en su ventana), en la vista «Campo» (filtro «Cables», selección en lote mezclada con puntos: el diálogo de aprobar sirve para ambos) y en la insignia de pendientes; aviso «juan trazó un cable de 121 m».
**Pruebas:** `test_campo_trazos.py` (11, servidor y REST), `test_campo_cables_pwa.py` (2: en Edge móvil: red de referencia, aviso de duplicado, trazar tocando postes con pegado, grabar recorrido con filtros de precisión y paso, ubicación / mira / cancelar, sin señal con reinicio, lista y borrar, ocultar la red; y la lógica del trazo), `test_visor_pagina_campo.py` (+1: cables en el visor, aprobar como cable real, error de extremos, rechazar, lote punto + cable a Mis lugares).
**Falta (fase 6):** túnel de Cloudflare como dirección oficial y README con la guía para técnicos. Sin HTTPS el teléfono no instala la app ni da el GPS.

## App de campo — fase 6 (2026-10-21): dirección oficial por Cloudflare y guías
**Hecho:** configuración y documentación del túnel de Cloudflare (`api.fiberbudget.com`), sin activarlo (eso lo hace quien administra la cuenta del dominio): `iniciar_tunel_cloudflare.bat` (lee `CLOUDFLARE_TUNNEL_TOKEN` del `.env`, lo pasa por la variable `TUNNEL_TOKEN` —ni en pantalla ni en la línea de comandos— y usa `herramientas\cloudflared.exe` o el del PATH, sin permisos de administrador), `start_service.bat` lo abre solo (ventana minimizada, antes de arrancar el servicio) cuando ese token está en `.env`, `cloudflared/config.yml.ejemplo` (la otra forma, con archivo), `.gitignore` (binario y credenciales), `CAMPO_URL_PUBLICA` (`Settings.campo_url_publica`; sale en el log al arrancar y en `/visor/campo/config` como `url_publica`) y `verificar_campo.py <URL> [clave]` (archivos de la app, manifest, service worker, íconos, clave y rol, aviso si la dirección pública del servidor no coincide, canal SSE; avisa si el túnel contesta con su propia página). `docs/campo/CLOUDFLARE.md` (6 pasos con el token del panel, la otra forma, quién entra por esa dirección, tabla de fallas) y `docs/campo/GUIA_TECNICOS.md` (instalar en Android e iPhone, registrar, cables, sin señal, lista, problemas), más la sección «App de campo» del README (alta de un técnico, revisar, ajustes). La app avisa si se abre por `http://` (pantalla de clave y ayuda) y dice el uso diario en la ayuda; las peticiones llevan `ngrok-skip-browser-warning` mientras siga ngrok; el service worker pasa a `campo-v6`.
**Pruebas:** `test_campo_tunel.py` (7: configuración, `url_publica`, el verificador contra la app real y contra un túnel que responde con su página, archivos del túnel sin filtrar el token y orden en `start_service.bat`, guías, aviso de http). Todas las pruebas de la fase y el resto de la suite pasan.
**Pendiente de Jan:** crear el túnel en Cloudflare, copiar el token y `cloudflared.exe`, poner `CLOUDFLARE_TUNNEL_TOKEN` y `CAMPO_URL_PUBLICA` en `.env`, reiniciar `start_service.bat`, correr `verificar_campo.py`, y probar la app en un Android y un iPhone reales (el GPS, la cámara y «Agregar a pantalla de inicio» solo se pueden verificar ahí).

### App de campo: se usa ngrok por ahora (2026-10-21)
`fiberbudget.com` NO está registrado (consulta RDAP del registro `.com`: 404; en Cloudflare solo se agregó el nombre y espera nameservers que nunca llegarán), así que el túnel `fiber-budget` (creado el 28/09/2026, 0 conexiones) no se puede usar: `api.fiberbudget.com` no existe. Decisión de Jan: **usar ngrok por ahora**. `.env`: `CAMPO_URL_PUBLICA=https://broken-snowy-credibly.ngrok-free.dev`. `verificar_campo.py` contra esa dirección: 9 de 9 bien (app, manifest, service worker, íconos, Leaflet). `start_service.bat` ya no abre el túnel de Cloudflare solo: exige `CLOUDFLARE_ACTIVAR=1`. `cloudflared/config.yml` (real, fuera de GitHub) queda listo para cuando se compre el dominio. Guía de técnicos y README avisan del «Visit Site» de ngrok. Pendiente de Jan: probar en un Android y un iPhone reales con esa dirección (también la clave de un técnico con `verificar_campo.py <URL> <clave>`).
