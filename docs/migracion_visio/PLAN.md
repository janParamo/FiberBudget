# Migración de los diagramas Visio a mufas interactivas

> **Para Claude Code:** lee este plan completo antes de tocar código. Trabaja **por fases**
> (sección 7): al terminar cada una, detente, muéstrame qué hiciste y cómo probarlo, y espera mi
> OK. Entrega **archivos completos** listos para reemplazar. Todo en español en la interfaz.

## 1. Objetivo

Que **todas las mufas existentes** de la red, no solo las que se creen nuevas, se puedan abrir en el
editor de mufa del visor y se vea **de forma gráfica, sin Visio**:

- qué cables entran y salen, cuántos hilos y buffers tiene cada uno y a qué mufa o nodo van,
- qué hilos están empalmados con cuáles, qué splitters hay y a qué cliente va cada puerto,
- **en qué bandeja y en qué posición** está cada empalme,
- y cómo están conectadas las mufas entre sí, navegando de una a otra con Enter.

Todo queda guardado en PostgreSQL (esquema `redes`) y es **configurable y editable**, igual que las
mufas nuevas.

## 2. Decisiones confirmadas por IDEAY

| Tema | Decisión |
|---|---|
| Empalmes por bandeja | **24** |
| Modelos de mufa | Capacidad **48** y **96** hilos, en dos formatos: **domo (vertical)** y **cierre horizontal**. Por lo tanto: mufa de 48 = 2 bandejas, mufa de 96 = 4 bandejas. |
| Splitters | Van **en la misma bandeja** de empalme. Una bandeja que lleva un splitter queda **limitada a los puertos de ese splitter** (por ejemplo, con un 1x8 esa bandeja admite solo los 8 empalmes de sus salidas, más la entrada). |
| Cable de 48 hilos | Dos configuraciones: **6x8** (6 buffers de 8 hilos) o **12x4** (12 buffers de 4 hilos) |
| Cable de 24 hilos | Dos configuraciones: **6x4** (6 buffers de 4 hilos) o **12x2** (12 buffers de 2 hilos) |
| Tipo de fibra | Monomodo de **dispersión cromática cero**, el estándar de la empresa (guardarlo como atributo del cable, editable) |
| Alcance | **Migrar todas las mufas de una vez.** No hay piloto: los errores se corrigen después en el editor, y todo queda marcado con su fuente y confianza para saber qué revisar. |

## 3. Lo que ya existe (no romper)

- **API de presupuestos + n8n + ngrok:** no se toca.
- **Base Visio (`red_fibra`, SQLite y PostgreSQL), construida por `red_fibra/importador.py`:**
  - 3 397 mufas (3 314 nodos con coordenada real; unas 3 300 menciones de nodos sin coordenada).
  - 1 110 enlaces entre nodos; 919 con número de hilos (12 h: 370, 24 h: 317, 6 h: 137,
    48 h: 61, 8 h: 17, 2 h: 11, 72 h: 6).
  - 14 248 servicios (clientes y splitters) en 1 049 mufas.
  - `anillo_tramos`: 135 tramos (110 mufas) con hilo de entrada y de salida.
  - `textos_crudos`: todo el texto con posición, incluidas unas 27 500 etiquetas de numeración y
    unas 2 000 de splitters.
  - `cache_odg/` (hoy `datos/cache/odg/`): 428 diagramas convertidos, con las fusiones dibujadas como líneas sueltas.
  - `red_fibra/fusiones.py` + `piloto_fusiones.py`: extracción geométrica de fusiones (tabla
    `fusiones_piloto`). Revisar si ya se corrió y con qué precisión.
- **Módulo de redes (`visor_rutas/redes/`, esquema `redes`, migraciones 001–008):** `elementos`,
  `cables` (clase, ADSS/FLAT, hilos, `hilos_por_buffer`, color, geometría, metraje), `hilos`
  (buffer y color TIA por trigger, estado), `mufa_cables`, `splitters`, `conectores`, `puertos`,
  `conexiones`, notas, historial, bloqueo optimista, trazado, diagrama lógico, editor de mapa y
  editor de mufa.
- **Visor:** "Ver diagrama" (Visio en imagen), ruta de fusión (`fusion.py`), capas KMZ y PostGIS
  (`red_lineas` / `red_puntos`).

## 4. Principios

1. **No inventar conexiones.** Cada dato migrado lleva su **fuente** y su **confianza**:
   - `excel_anillos`: alta
   - `texto_diagrama`: media
   - `geometria_visio`: según la precisión medida
   - `estimado`: baja
   - `usuario`: verificado

   Lo desconocido se muestra como **"sin diagramar"**.
2. **Los supuestos se marcan.** Si se eligió por regla la configuración de buffers de un cable, o el
   modelo y las bandejas de una mufa, queda marcado como `estimado` y se ve en el editor, para que
   el técnico lo confirme o lo cambie.
3. **El Visio original sigue disponible** junto al editor, para comparar.
4. **Lo que un usuario valida o edita manda:** una reimportación nunca lo sobrescribe; solo
   reporta las diferencias.
5. **Idempotente:** correr la migración dos veces no duplica. **Clave = nombre normalizado + coordenada
   redondeada a 4 decimales** (o + carpeta si no tiene coordenada), no el id del nodo: el importador
   renumera los ids en cada carga (decisión de Jan, 2026-10-12; ver §11).
6. **No modificar** `red_lineas`, `red_puntos` ni `red_fibra`; solo leerlas.

## 5. Modelo de datos (migración `009_red_existente.sql` y siguientes)

Proponer y justificar en la fase 0; como mínimo:

- **Proyectos base** (`es_red_base = true`), por zona ("Red existente – Managua", "– León"…), donde
  vive lo migrado. Visibles por defecto en el visor.
- **`elementos`:**
  - `fuente`, `confianza`, `ref_visio` (nodo_id, archivos, md5) y `ubicacion_estimada`;
  - `estado_migracion`: `automatica` | `en_revision` | `validada` | `editada`;
  - tipo `odf` si hace falta.
- **Mufa** (`propiedades` o tabla propia):
  - `formato`: `domo` | `horizontal` | `desconocido`;
  - `capacidad`: 48 | 96;
  - `empalmes_por_bandeja`: 24;
  - `bandejas`: 2 | 4;
  - `modelo_estimado` (boolean).
- **`mufa_bandejas`:** mufa, número, capacidad efectiva (24, o los puertos del splitter que
  lleva), `splitter_id` opcional, `fuente`.
- **`cables`:**
  - ampliar el CHECK de `hilos` a 2, 4, 6, 8, 12, 24, 48, 72, 96 y 144, y aceptar "desconocido";
  - ampliar `hilos_por_buffer` a **2, 4, 6, 8 y 12**;
  - nuevos campos:
    - `configuracion` (texto "6x8", "12x4", "6x4", "12x2", "1x12"…) y `configuracion_estimada`;
    - `tipo_fibra` (por defecto "SM dispersión cero");
    - `fuente`, `confianza`;
    - `geom_fuente`: `kmz` | `recta`.
  - El trigger de hilos ya calcula buffer y color TIA con `hilos_por_buffer`: verificar que
    funciona con 2 y 4 (buffers 1–12 en colores TIA y, dentro de cada buffer, hilos con los
    primeros 2, 4 u 8 colores TIA).
- **`conexiones`:** `bandeja`, `posicion_en_bandeja` (1–24), `fuente`, `confianza`.
- **`migracion_visio_log`:** corrida, nodo o archivo, acción, resultado, avisos y conteos.

## 6. Reglas de migración

### 6.1 Nodos → elementos
- `nodos` de tipo MUFA, NODO, MINI_NODO y ODF → `elementos`, con nombre, propietario y notas
  (SANGRIA, VALIDAR, SATURADA…).
- Coordenada real → ubicación normal. `estimada_vecinos` → `ubicacion_estimada`. Sin coordenada →
  la cola de corrección «Sin ubicar» (vista **Red existente**), desde la que el usuario las coloca con un clic
  en el mapa; el mapa se centra donde probablemente están (ver §11).
- Emparejar con `red_puntos` (KMZ) con las reglas de `origen.py`; guardar el id en `ref_externa`.

### 6.2 Enlaces → cables
- Cada `enlace` → `cable` con `hilos_cable` (o "desconocido"), longitud y clase (`troncal` si viene
  de `anillo_tramos` o dice TRONCAL/BACKBONE; si no, `distribucion`).
- **Configuración de buffers:**
  1. Si el texto del diagrama la dice ("6X8", "12X4", "6 TUBOS", "12 BUFFER"…), usar esa
     (confianza media).
  2. Si no, aplicar el valor por defecto de `business_rules.yaml` → `migracion_visio.configuracion_por_hilos`,
     marcado `configuracion_estimada = true`:
     ```yaml
     migracion_visio:
       configuracion_por_hilos:     # hilos: "buffers x hilos_por_buffer" (editable por cable)
         2:  "1x2"
         6:  "1x6"
         8:  "1x8"
         12: "1x12"
         24: "6x4"                  # alternativa: "12x2"
         48: "6x8"                  # alternativa: "12x4"
         72: "6x12"
         96: "8x12"
         144: "12x12"
       tipo_fibra: "SM dispersión cero"
       empalmes_por_bandeja: 24
       capacidades_mufa: [48, 96]
     ```
     (Los valores para 24 y 48 hilos son los que confirmó IDEAY; elegir cuál es el más común y
     dejar el otro como alternativa en el selector del editor. Confirmar los demás con Jan en
     la fase 0.)
- **Trazo:** la línea de `red_lineas` (KMZ) que une ambas mufas, con tolerancia; si no hay, recta
  (`geom_fuente = recta`).
- Generar los `hilos` (el trigger asigna buffer y color).

### 6.3 Splitters, clientes y puertos (desde el texto)
- "SPL 1X8 … 0/2/0 OLT LEON" → `splitter` (salidas, relación si dice 70/30, OLT y puerto en
  `propiedades`).
- Listas "1- C22835 AGRO ALFA ID000721" → salida n → cliente (código, nombre, ID de servicio).
- "SPL DEPENDE DE 1/8 PLAZA MAYOR 2" → la entrada viene de esa mufa (relación, aunque el hilo sea
  desconocido).
- Si el código C##### tiene coordenada en las solicitudes de Kayako, crear el cliente en el mapa
  (fuente `kayako`).

### 6.4 Hilos y empalmes (en orden de confianza)
1. `anillo_tramos` → conexión hilo ↔ hilo, confianza alta.
2. Texto que nombra hilos ("H12 E H13", "HILOS 45,46,47,48", "1H"…), confianza media.
3. `fusiones_piloto`, solo si su precisión supera el umbral configurable (por ejemplo, ≥ 85 %).
4. Sin dato: "fusiones sin diagramar".

### 6.5 Hilos de la mufa, modelo y bandejas
- **Hilos de la mufa:**
  - los que se cortan y empalman en la mufa (los cables en sangría cuentan solo los hilos
    sangrados);
  - si no se sabe, usar los hilos del cable mayor y marcar `estimado`;
  - mostrar empalmados, libres y en splitter.
- **Modelo:** el texto del diagrama manda (por ejemplo, "FOSC …", "48F", "96F", "HORIZONTAL",
  "DOMO"). Si no lo dice, aplicar la regla y marcarlo `modelo_estimado`:
  - hasta 48 empalmes → mufa de 48 (2 bandejas);
  - de 49 a 96 → mufa de 96 (4 bandejas);
  - más de 96 → aviso "excede capacidad, revisar".

  El formato (domo u horizontal) queda `desconocido` salvo que el texto lo diga.
- **Bandejas y splitters:**
  - cada bandeja tiene 24 posiciones;
  - una bandeja que lleva un splitter 1xN queda limitada a los N empalmes de sus salidas, más la
    entrada (confirmar en la fase 0 si la entrada ocupa una posición);
  - los splitters se ubican primero en las bandejas más altas, y los empalmes directos llenan las
    bandejas desde la 1;
  - si los empalmes más los splitters no caben en la capacidad del modelo, aviso.
- **Asignación por defecto:** los empalmes se reparten por buffer en orden, llenando cada bandeja
  hasta su capacidad efectiva. Las salidas del splitter van a la bandeja de ese splitter. Se guarda
  `bandeja` y `posicion_en_bandeja`, con fuente `estimado`, hasta que el usuario los mueva.

## 7. Fases

| Fase | Alcance | Listo cuando |
|---|---|---|
| **0. Diagnóstico** | Leer el código y los datos actuales. Medir la cobertura: cables con hilos, mufas con splitters/clientes, datos de anillo, textos con configuración de buffers o modelo, y precisión del piloto de fusiones. Proponer el modelo exacto y `migracion_visio` en `business_rules.yaml`. | Apruebo el plan. |
| **1. Modelo** | Migraciones SQL del punto 5, idempotentes y con respaldo automático previo. | Base actualizada sin perder lo existente; pruebas pasan. |
| **2. Migrar toda la red base** | Script `visor_rutas/redes/migrar_visio.py` (opciones `--zona`, `--simular`, `--solo-mufas lista.txt`) que migra **todas** las mufas: nodos → elementos, enlaces → cables con trazo KMZ y configuración de buffers, hilos. Corre primero en modo `--simular` y genera un reporte Excel de lo que se migraría y de lo que no se pudo; luego corre en real. | Toda la red aparece en el mapa con sus cables e hilos, y el reporte cuadra con la cobertura de la fase 0. |
| **3. Splitters, clientes y empalmes** | Reglas 6.3 y 6.4 para todas las mufas, con fuente y confianza. | Las mufas muestran sus splitters, puertos con clientes y los empalmes conocidos. |
| **4. Modelo y bandejas** | Regla 6.5 y vista de bandejas en el editor (sección 8). | Cada mufa muestra su modelo (48/96), sus bandejas, la bandeja limitada por el splitter y la posición de cada empalme. |
| **5. Interactividad en la red existente** | Enter sobre cualquier mufa existente abre el editor con sus datos migrados. "Ver Visio original" al lado para comparar. Botón "Marcar como validada". | Navego mufa → mufa por los cables migrados, corrijo una y la valido. |
| **6. Cola de corrección y tablero** | Tablero por zona: mufas migradas, con fusiones conocidas, con supuestos (`estimado`) y validadas. Lista ordenada de lo que hay que corregir (sin ubicar, sin diagramar, excede capacidad, configuración estimada…) con filtro y salto directo a la mufa. Exportable a Excel para Planta Externa. | Veo el avance y la lista de pendientes de corrección. |
| **7. Reimportación segura** | Si cambia un Visio: reimportar solo lo que no está validado ni editado; para lo demás, un reporte de diferencias sin sobrescribir. | Cambio un Visio de prueba y el reporte muestra la diferencia sin pisar lo validado. |

En cada fase:
- pruebas en `Pruebas/` con una base mínima de prueba (incluir cables de 24 6x4 y 12x2, de 48
  6x8 y 12x4, una mufa de 48 y una de 96, y un splitter 1x8 en bandeja),
- todas las pruebas existentes siguen pasando,
- `POST /presupuesto` sin cambios,
- README actualizado.

## 8. Visualización en el editor de mufa

- **Encabezado:**
  - nombre, formato (domo u horizontal), capacidad (48/96) y tipo de fibra;
  - hilos empalmados / libres / en splitter y bandejas usadas / totales;
  - estado de migración e insignias de confianza (y "estimado" donde aplique).
- **Vista de bandejas:**
  - una tarjeta por bandeja (2 o 4), con 24 posiciones;
  - cada posición muestra el par empalmado: cable A · buffer · hilo, con su color TIA ↔
    cable B · buffer · hilo, con su color TIA;
  - una bandeja con splitter se dibuja con el splitter y solo sus N posiciones habilitadas; el
    resto aparece bloqueado;
  - arrastrar un empalme a otra bandeja o posición lo reasigna (y respeta la capacidad);
  - las posiciones libres se ven vacías.
- **Vista de cables** (la actual):
  - buffers con el color TIA y sus hilos agrupados según la configuración (6x8, 12x4, 6x4, 12x2…);
  - al pasar sobre un empalme, se resalta su bandeja;
  - selector para cambiar la configuración del cable si está mal; los hilos se regeneran y las
    conexiones se conservan por número de hilo.
- **Colores por fuente** en las conexiones: verde = verificado/Excel, azul = texto,
  naranja = geometría Visio, gris punteado = estimado. Leyenda visible.
- **Hilos sin dato:** "sin diagramar" y un botón "Diagramar ahora" (pasa a fuente `usuario`).
- **Vista "Red de mufas":** grafo de la mufa y sus vecinas a 1 o 2 saltos, con los cables entre
  ellas. Enter para entrar a cualquiera.

## 9. Por confirmar en la fase 0

- ¿La entrada del splitter ocupa una de las 24 posiciones de la bandeja, o solo cuentan sus salidas?
- Para 24 y 48 hilos, ¿cuál configuración es la más común (6x4 o 12x2; 6x8 o 12x4)? Esa será la
  regla por defecto.
- Configuración de los cables de 6, 12, 72, 96 y 144 hilos.
- Precisión mínima aceptable para usar las fusiones extraídas de la geometría del Visio.

## 10. Restricciones

- Windows sin permisos de administrador, mismo `.venv`. LibreOffice Portable para las imágenes del
  Visio.
- No romper: diagramas Visio ("Ver diagrama"), ruta de fusión, capas KMZ y Visio, presupuesto
  aproximado, modo remoto/.exe, módulo de proyectos.
- Respaldo de la base antes de cada corrida de migración (usar `redes/respaldo.py`).

## 11. Decisiones tomadas y estado (actualizado el 2026-10-22)

Lo que se decidió después de escribir este plan (diagnóstico de la fase 0, `FASE0_DIAGNOSTICO.md`, y las fases siguientes) y que **manda sobre el texto de arriba**:

| Tema | Decisión |
|---|---|
| Clave de idempotencia | **Nombre normalizado + coordenada a 4 decimales** (~11 m); sin coordenada, nombre + carpeta del Visio. El `nodo_id` y los md5 solo se guardan como referencia (`ref_visio`). |
| Hilos de un cable | 2, 4, 6, 8, 12, 24, 48, 72, 96 y 144, o **desconocido** (71 % de los cables no lo traen). Orden: etiqueta del Visio → continuidad por los dos lados → continuidad por un lado («por confirmar») → texto de la línea del KMZ → **mínimo que exige el Excel de anillos** (el hilo 26 pide al menos 48; estimado, confianza baja, OK de Jan 2026-10-13). |
| Reservas | **Se migran** como `elementos` tipo `mufa`, subtipo `reserva` (13 en el diagnóstico). |
| Proyectos base | **Uno por región** (carpeta del Visio → proyecto, `business_rules.yaml: migracion_visio.proyectos_base`); lo demás va a «Red existente – Managua». Una mufa de una carpeta sin región (ruta troncal) a ≤ 5 km del centro de una región pasa a esa región. Masachapa, Montelimar, Villa El Carmen y San Benito son del departamento de Managua aunque estén a 30–46 km de su centro: están nombradas en la lista de Managua. |
| Configuración de buffers | 24 → 6x4, 48 → 6x8 por defecto (12x2 y 12x4 como alternativas); 6 → 1x6, 12 → 1x12, 72 → 6x12, 96 → 8x12, 144 → 12x12. Lo que sale de la regla queda `configuracion_estimada`. |
| Splitter y bandejas | La entrada del splitter ocupa una posición (1x8 → 9). Mufa de 48 (2 bandejas) o 96 (4); 24 empalmes por bandeja. |
| Fusiones por geometría | **Apagadas** (`fusiones_geometria.usar: false`): medido 2026-10-13, precisión 3,9 %. Las fusiones migradas son solo las del Excel de anillos (confianza alta). |
| Coordenadas de clientes | Del KMZ (acometidas «C#####»). **Kayako queda fuera por orden de Jan.** |
| Mufas sin ubicar | No se dibujan en el mapa; salen en la cola de corrección de **Red existente** con el botón «Colocar en el mapa». Cada una trae una pista de dónde está, solo para centrar el mapa (nunca se guarda): las mufas a las que se une en el Visio, si no las otras que salen en su mismo diagrama, si no el resto de su carpeta. |

Resultado de la migración real (corrida del 2026-10-22 sobre la base nueva, igual a la del 13 de octubre): 13 proyectos base, 3 472 elementos (3 191 con ubicación real, 102 estimada, **179 sin ubicar**), 3 006 cables, 35 754 hilos, 1 375 splitters, 1 208 puertos con cliente, 2 016 clientes en el mapa, 3 032 mufas de modelo 48 y 335 de 96 (66 con avisos), verificación: 0 errores y 66 avisos.

**Empalmes del Excel de anillos: 233 filas.** 212 se crearon. **21 no**: todas nombran como vecino un «ODF xx PUERTOS» del nodo y el Visio no dibuja el cable entre esa ODF y la mufa; se cuentan aparte (`empalmes_odf`) para revisarlas con Planta Externa. Otras 8 filas del Excel traen hilos ilegibles («¿?») y se omiten con su motivo.

**Lo que sigue pendiente:** Kayako (fuera por ahora); decidir si se crean los cables mufa–ODF que faltan (hoy no se inventan); y las 179 mufas sin ubicar, que alguien tiene que colocar una por una.
