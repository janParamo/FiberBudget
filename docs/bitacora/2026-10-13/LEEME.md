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
