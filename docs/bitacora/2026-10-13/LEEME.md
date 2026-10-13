# Bitácora 2026-10-13

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

**Pendiente:**
- el OK de Jan para las fases 5, 6 y 7;
- decisión de Jan sobre los empalmes del anillo (ver más abajo) y sobre las fusiones por geometría (falta medir la precisión);
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
