# Migración Visio → mufas interactivas · Fase 0: diagnóstico

Fecha: 2026-10-12. Mediciones de **solo lectura** sobre `red_fibra/red_fibra.db` y la copia publicada en
PostgreSQL (`Presupuesto_visio.red_fibra`, importación n.º 2 del 5-oct, publicada el 6-oct): son
idénticas. El emparejamiento con el KMZ se midió en `Presupuesto_fibra` (`red_puntos`, `red_lineas`).
No se escribió código ni se modificó ninguna base.

---

## 1. Cobertura medida

### 1.1 Lo que el plan supone y lo que hay

| Dato | Plan (§3) | Medido hoy | Comentario |
|---|---|---|---|
| Mufas (tipo MUFA) | 3 397 | **3 397** | coincide |
| Enlaces | 1 110 (919 con hilos) | **3 208** (921 pares con hilos) | El plan tomó la importación n.º 1. La n.º 2 agregó **2 096 enlaces deducidos de las líneas dibujadas** (`visio_linea`), **sin hilos ni longitud**. |
| Servicios | 14 248 en 1 049 mufas | 14 248 en **2 198** mufas | el conteo de mufas del plan era el de splitters |
| `anillo_tramos` | 135 (110 mufas) | 135 (110 mufas, 6 anillos) | coincide |
| `fusiones_piloto` | "revisar si ya se corrió" | **no existe en ninguna de las dos bases** y no hay marcas en `piloto/marcas` | el piloto **nunca se corrió**: precisión **desconocida** |
| Kayako | coordenadas de clientes | **no hay datos de Kayako en el proyecto** | hay que saber de dónde leerlos |

### 1.2 Nodos → elementos

| | Total | Coordenada real (Visio / Excel) | Estimada (vecinos) | Sin ubicar |
|---|---|---|---|---|
| MUFA | 3 397 | 3 124 | 96 | 177 |
| ODF | 51 | 49 | 2 | 0 |
| NODO | 28 | 25 | 2 | 1 |
| MINI_NODO | 14 | 10 | 2 | 2 |
| **Total a migrar** | **3 490** | **3 208 (92 %)** | **102 (3 %)** | **180 (5 %)** |

- Otros nodos que **no** se migran (el plan no los nombra): RESERVA 13, OTRO 81, CLIENTE 18.
- Notas: SANGRIA en 290 mufas, VALIDAR en 153, NO PROYECTAR en 9. 293 nodos marcados `requiere_revision`.
- **Con un punto del KMZ cerca:** 3 138 de 3 310 nodos ubicados (**95 %**) a ≤ 30 m, y 2 378 (72 %) a ≤ 10 m. Sirve para `ref_externa` y para corregir la ubicación.
- **Con diagrama propio:** 337 nodos (267 diagramas de mufa). El resto aparece solo como vecino o en diagramas de red o subred.
- Mufas con al menos un enlace: 2 768. **Sin ningún enlace: 691.**
- **71 zonas** (carpetas de los Visio). Las de Managua son corredores ("Nodo La Gruta carretera hacia León"…, unas 2 530 mufas) y las de fuera son "Red León", "Red Rivas", etc. Ver §3.2.

### 1.3 Enlaces → cables

| | Pares de mufas | Con hilos | Con longitud |
|---|---|---|---|
| `visio_red` | 628 | 628 | 628 |
| `visio_mufa` | 370 | 293 | 162 |
| `excel` (anillos) | 114 | 0 | 0 |
| `visio_linea` (líneas dibujadas) | 2 096 | 0 | 0 |
| **Pares distintos** | **3 138** | **921 (29 %)** | |

- **Hilos conocidos:** 12 h: 369 · 24 h: 318 · 6 h: 139 · 48 h: 61 · 8 h: 17 · 2 h: 11 · 72 h: 6. **Desconocidos: 2 217 pares (71 %).** No hay conflictos (ningún par con dos capacidades distintas).
- **Trazo KMZ:** de 3 024 pares entre nodos migrables y ubicados, **1 946 (64 %)** tienen una línea de `red_lineas` que pasa a ≤ 25 m de ambos extremos. El resto irá en recta (`geom_fuente = recta`). Distancia media entre extremos: 642 m.
- **Troncal:** solo 1 texto de enlace dice TRONCAL o BACKBONE. La clase troncal saldrá casi solo de `anillo_tramos` (114 enlaces).
- **Configuración de buffers escrita en el diagrama:** **4 textos en total**: "6 BUFFER DE 2HILOS" (12 h), "4BUFFER DE 6H" (24 h), "4X6" (24 h), "8 tubos" (48 h). **En la práctica, el 100 % de las configuraciones será por regla (`estimada`).**

### 1.4 Mufas: modelo y hilos

Estimación del modelo con la regla 6.5, a partir del cable mayor de cada mufa:

| Caso | Mufas |
|---|---|
| Cable mayor ≤ 48 h → mufa de 48 (2 bandejas) | 1 207 |
| Cable mayor de 49 a 96 h → mufa de 96 (4 bandejas) | 10 |
| > 96 h (revisar) | 0 |
| Solo cables de hilos desconocidos | 1 489 |
| Sin cables | 691 |

- **Modelo o formato escrito:** "DOMO" en 1 texto y "HORIZONTAL" en ninguno. "FOSC" aparece en 652 textos, pero es la marca, no dice la capacidad. "48F" o "48H" se refieren al cable, no a la mufa. **Todos los modelos serán `estimado`, con formato `desconocido`.**
- **Sangría:** 290 mufas con nota SANGRIA. Sus cables cuentan solo los hilos sangrados, que casi nunca están escritos, así que esas mufas quedan `estimado`.

### 1.5 Splitters, clientes y puertos (texto)

| Dato | Medido |
|---|---|
| Menciones de splitter | 2 408 en **955 mufas** |
| … con 1xN legible | 1 519 (63 %): 1x8 1 066 · 1x16 323 · 1x4 125 · 1x32 2 · **1x6 3 (no existe: revisar)** |
| … con relación desbalanceada (70/30…) | **0** |
| … con OLT | 549; con puerto OLT x/y/z: 425 |
| "SPL DEPENDE DE …" | 47 textos |
| **Listas numeradas de puertos** ("1 - C24712 …") | **285 listas en 82 diagramas, 2 904 puertos**; 1 075 con código C#####, 744 con ID de servicio |
| Clientes mencionados | 8 341 en 2 060 mufas (3 315 códigos distintos) |

La mayoría de los clientes **no** tienen puerto de splitter: están listados en la mufa, fusionados directos o en sangría. **Se sabe a qué splitter y puerto va un cliente en unos 1 075 casos.** Los demás se pueden mostrar como "clientes de la mufa" sin puerto.

### 1.6 Hilos y empalmes

| Fuente (orden 6.4) | Cobertura |
|---|---|
| 1. `anillo_tramos` | 135 tramos en 110 mufas. **106 con hilo de entrada y de salida legibles** ("HILOS 17 / 18", "PUERTOS 17 Y 18") → unas **212 fusiones** de confianza alta |
| 2. Texto que nombra hilos ("H27 Y H28", "HILOS 4 Y 5") | **21 textos** en 21 diagramas: casi nada |
| 3. Geometría del Visio (`fusiones_piloto`) | **0: el piloto nunca se corrió.** Los 428 diagramas convertidos (`cache_odg/`, hoy `datos/cache/odg/`) sí tienen las fusiones dibujadas. |
| 4. Sin dato | Todo lo demás: "fusiones sin diagramar" |

**Conclusión:** sin la extracción geométrica, solo unas ~110 mufas del anillo tendrán empalmes conocidos. La geometría es la única fuente masiva, y hay que **medir su precisión antes** de usarla (§4, pregunta 4).

### 1.7 Hallazgos que cambian el plan

1. **Los `id` de `red_fibra.nodos` no son una clave estable.** `importador.py` reconstruye la base completa y los numera en orden de lectura; entre las dos cargas actuales coinciden, pero un Visio nuevo los corre. Además hay **129 nombres normalizados repetidos**.
   - **Propuesta:** clave de idempotencia = **nombre normalizado + coordenada redondeada a 4 decimales** (~11 m). Se guardan además el `nodo_id` y los md5 como referencia.
   - Si un nodo no tiene coordenada: nombre + zona.
   - Con esto, la regla del plan ("id Visio + md5") se usa solo para detectar si cambió el archivo.
2. **El 71 % de los cables no tiene hilos.**
   - Se crean con `hilos` **desconocido** (sin hilos generados). El editor muestra "hilos desconocidos · definir" y, al elegir la capacidad, genera los hilos.
   - Sin esto, 1 489 mufas no tendrían ningún hilo.
3. **El tamaño de la red de Managua:** unas 2 530 mufas en un solo proyecto base. Hoy el editor de mapa carga el proyecto completo de una vez.
   - **Propuesta:** proyectos base por región (§3.2).
   - En la fase 5, carga por zona visible del mapa para los proyectos base.
4. **No hay piloto de fusiones ni datos de Kayako.** Los dos dependen de ti (§4).

---

## 2. Modelo de datos propuesto (migración `009_red_existente.sql`)

Todo en el esquema `redes`, con versión y borrado lógico como el resto. **No se toca `red_fibra` ni el KMZ.**

### 2.1 Cambios a tablas existentes

| Tabla | Cambio | Por qué |
|---|---|---|
| `proyectos` | + `es_red_base boolean NOT NULL DEFAULT false`, + `zona text` | Los proyectos base guardan lo migrado y se ven por defecto en el visor |
| `elementos` | `tipo` acepta **`odf`**; el `subtipo` de un nodo acepta `mini_nodo` | 51 ODF; los mini nodos quedan como nodos |
| `elementos` | `ubicacion` pasa a **opcional** si `ubicacion_fuente = 'sin_ubicar'` (CHECK) | 180 nodos sin coordenada van a la lista "Mufas sin ubicar" |
| `elementos` | + `ubicacion_fuente`: `real` \| `estimada` \| `sin_ubicar` \| `usuario` | Reemplaza el `ubicacion_estimada` del plan: dice también cuándo la corrigió alguien |
| `elementos` | + `fuente`, + `confianza`, + `estado_migracion` (`automatica` \| `en_revision` \| `validada` \| `editada`; NULL = creado en el visor), + `ref_visio jsonb` (`clave`, `nodo_id`, `nombre_visio`, `zona`, `archivos: [{ruta, md5}]`, `notas`) | Principios 1, 4 y 5 |
| `elementos` | índice único parcial sobre `(proyecto_id, ref_visio->>'clave')` | Idempotencia (§1.7-1) |
| `cables` | `hilos` **opcional** (NULL = desconocido); CHECK `hilos IN (2, 4, 6, 8, 12, 24, 48, 72, 96, 144)` | §1.7-2; 6 h y 2 h existen en la red |
| `cables` | `hilos_por_buffer IN (2, 4, 6, 8, 12)` | 6x4, 12x2, 12x4, 1x6 |
| `cables` | + `configuracion_estimada boolean`, + `tipo_fibra text DEFAULT 'SM dispersión cero'`, + `fuente`, + `confianza`, + `geom_fuente` (`kmz` \| `recta` \| `usuario`), + `estado_migracion`, + `ref_visio jsonb` (enlaces, fuentes, textos) | Plan §5 |
| `cables` | **No** se guarda el texto `configuracion` ("6x4"): se calcula como `ceil(hilos / hilos_por_buffer) x hilos_por_buffer` | Guardarlo aparte permitiría "6x8" en un cable de 24 h. El selector del editor cambia `hilos_por_buffer`. |
| `splitters` | + `propiedades jsonb` (`olt`, `puerto_olt` "0/2/0", `depende_de`: {mufa_id, texto}), + `fuente`, + `confianza` | Regla 6.3 |
| `conexiones` | + `bandeja`, + `posicion_en_bandeja` (1–24), + `fuente`, + `confianza`; índice único parcial `(mufa_id, bandeja, posicion_en_bandeja)` | Plan §5; dos empalmes no ocupan la misma posición |
| `hilos` | sin cambios | El trigger ya funciona con 2 y 4 por buffer (se verifica con pruebas en la fase 1) |

### 2.2 Tablas nuevas

| Tabla | Columnas | Por qué una tabla y no `propiedades` |
|---|---|---|
| `mufa_modelos` (1 por mufa) | `mufa_id` PK, `formato` (`domo` \| `horizontal` \| `desconocido`), `capacidad` (48 \| 96), `empalmes_por_bandeja` (24), `bandejas` (2 \| 4), `modelo_estimado`, `fuente`, `version` | Campos con CHECK, versión propia y consultas del tablero (fase 6) sin leer jsonb |
| `mufa_bandejas` | `id`, `mufa_id`, `numero` (1..bandejas), `capacidad` (24, o N + entrada si lleva splitter), `splitter_id` opcional, `fuente`, `version`, `borrado_en`; único `(mufa_id, numero)` | Plan §5 |
| `puerto_servicios` | `id`, `puerto_id` (salida de splitter), `codigo_cliente`, `nombre`, `id_servicio`, `elemento_id` (cliente en el mapa, si lo hay), `fuente`, `confianza`, `version`, `borrado_en` | "A qué cliente va cada puerto" sin necesitar el cliente en el mapa: hoy un puerto solo se conecta a un hilo |
| `mufa_clientes` | `mufa_id`, `codigo_cliente`, `nombre`, `id_servicio`, `fuente`, `borrado_en` | Los ~7 000 clientes listados en una mufa sin puerto conocido (§1.5) |
| `migracion_visio_corridas` | `id`, `inicio`, `fin`, `modo` (`simular` \| `real`), `zona`, `respaldo` (archivo), `conteos jsonb`, `usuario_id` | Cada corrida, con su respaldo previo |
| `migracion_visio_log` | `id`, `corrida_id`, `clave` o `archivo`, `accion` (`crear` \| `actualizar` \| `omitir` \| `conflicto`), `resultado`, `avisos jsonb` | Plan §5; base del reporte Excel y de la fase 7 |

**Fuentes y confianza** (un CHECK compartido en todas las tablas):

| Fuente | Confianza |
|---|---|
| `excel_anillos` | alta |
| `texto_diagrama` | media |
| `geometria_visio` | según lo medido |
| `kmz` | media |
| `kayako` | media |
| `estimado` | baja |
| `usuario` | verificada |

---

## 3. Reglas configurables (`business_rules.yaml` → `migracion_visio`)

### 3.1 Propuesta

```yaml
migracion_visio:
  # Configuración de buffers por cantidad de hilos: "buffers x hilos_por_buffer". Editable por cable
  # en el editor; lo migrado por regla queda configuracion_estimada = true.
  configuracion_por_hilos:
    2:   "1x2"
    4:   "1x4"
    6:   "1x6"
    8:   "1x8"
    12:  "1x12"
    24:  "6x4"        # confirmado por Jan (12x2 como alternativa)
    48:  "6x8"        # confirmado por Jan (12x4 como alternativa)
    72:  "6x12"
    96:  "8x12"
    144: "12x12"
  alternativas:       # opciones extra en el selector del editor
    24: ["12x2"]
    48: ["12x4"]
    12: ["6x2"]       # la red tiene "6 BUFFER DE 2HILOS" (UFINET)
  tipo_fibra: "SM dispersión cero"

  # Mufas y bandejas
  empalmes_por_bandeja: 24
  capacidades_mufa: {48: 2, 96: 4}               # capacidad: bandejas
  entrada_splitter_ocupa_posicion: true           # confirmado por Jan
  orden_bandejas: {splitters: "desde_la_ultima", empalmes: "desde_la_1"}

  # Clase y trazo de los cables
  palabras_troncal: ["TRONCAL", "BACKBONE"]       # además de anillo_tramos
  tolerancia_linea_kmz_m: 25                      # 64 % de los pares tiene línea KMZ así
  tolerancia_punto_kmz_m: 30                      # 95 % de los nodos tiene punto KMZ así

  # Hilos de los cables sin etiqueta (§4.1), en este orden después de la etiqueta del Visio
  inferir_hilos:
    continuidad_ambos_lados: true
    continuidad_un_lado: true      # por confirmar en el editor
    texto_kmz: true                # acierto medido 36–50 %: por confirmar en el editor
  # Clientes: ubicación desde las acometidas / puntos del KMZ con su código C#####, luego Kayako
  ubicacion_clientes: ["kmz", "kayako"]
  migrar_reservas: true

  # Fusiones
  fusiones_geometria:
    usar: false                                   # hasta medir la precisión con el piloto
    confianza_minima: 0.85                        # de fusiones.py (0 a 1)
    precision_minima: 0.85                        # medida con piloto_fusiones.py

  # Proyectos base: la carpeta (zona) de los Visio decide el proyecto
  proyectos_base:
    defecto: "Red existente – Managua"
    zonas:
      "Red existente – León":       ["Red Leon", "RED SAUCE"]
      "Red existente – Chinandega": ["Red Chinandega", "RED CHICHIGALPA", "RED SOMOTILLO"]
      "Red existente – Masaya":     ["Red Masaya", "Red Nindirí"]
      "Red existente – Granada":    ["Red Granada"]
      "Red existente – Carazo":     ["RED Jinotepe", "Red Nodo Diriamba", "RED SAN MARCOS"]
      "Red existente – Rivas":      ["Red Rivas", "Red San Juan Del Sur", "RED NODO MACIZO PEÑAS BLANCAS"]
      "Red existente – Estelí":     ["Red Esteli"]
      "Red existente – Segovias":   ["Red Ocotal", "Red Somoto", "Red Jalapa"]
      "Red existente – Matagalpa":  ["Red Matagalpa", "Red Sebaco", "RED RIO BLANCO"]
      "Red existente – Jinotega":   ["RED JINOTEGA"]
      "Red existente – Boaco y Chontales": ["Red Boaco", "Red Juigalpa"]
      "Red existente – Caribe Sur": ["Red Bluefields", "Red El Rama", "RED NUEVA GUINEA"]
      # el resto (corredores de Managua, ANILLOS, ventanas, Tipitapa, Masachapa, Montelimar,
      # Villa El Carmen, San Benito…) va a "defecto"
```

### 3.2 Proyectos base que salen con esa regla

| Proyecto | Nodos aprox. |
|---|---|
| Managua | ~2 530 |
| Rivas | 248 |
| Chinandega | 198 |
| León | 108 |
| Masaya | 93 |
| Matagalpa | 77 |
| Carazo | 61 |
| Caribe Sur | 28 |
| Granada | 28 |
| Estelí | 43 |
| Boaco y Chontales | 37 |
| Segovias | 26 |
| Jinotega | 16 |

---

## 4. Respuestas de Jan (2026-10-12) y lo que se midió con ellas

| # | Pregunta | Decisión |
|---|---|---|
| 1 | ¿La entrada del splitter ocupa una posición? | **Sí** (1x8 → 9 posiciones de la bandeja) |
| 2 | 24 y 48 hilos | **6x4** y **6x8** por defecto (12x2 y 12x4 como alternativas) |
| 3 | 6, 12, 72, 96, 144 | 1x6, 1x12, 6x12, 8x12, 12x12, como se propuso |
| 4 | Fusiones por geometría | Se explicó qué haría Jan. Ver §4.3: se propone medir primero en automático. |
| 5 | Coordenadas de clientes | Vienen en el **comentario del ticket** de Kayako. Ver §4.2: el 70 % sale del KMZ. |
| 6 | Proyectos base por región | De acuerdo |
| 7 | Clave = nombre normalizado + coordenada | De acuerdo |
| 8 | Reservas | **Se migran** (13). Entran como `elementos` tipo `mufa` con subtipo `reserva`; el modelo aceptará el subtipo nuevo. |

### 4.1 Hilos de los cables "sueltos" (sin hilos en el Visio)

La idea de Jan: deducirlos por continuidad con las mufas vecinas y por el cable del KMZ que pasa por encima. Se midieron las dos fuentes sobre los 2 217 pares sin hilos:

| Fuente | Cables que resolvería | Qué tan confiable (medido donde el Visio sí dice los hilos) |
|---|---|---|
| **Continuidad:** el mismo valor en los cables a ambos lados del tramo (A–X de 24 y Y–B de 24 → X–Y de 24) | **122** | Regla lógica; queda `estimado` |
| Continuidad por un solo lado (la mufa solo tiene otro cable con hilos) | 717 | Débil en mufas de derivación: el cable de salida puede ser menor; `estimado` y "por confirmar" |
| **Texto de la línea del KMZ** ("FO 24H"…) | 908 tomando la línea más corta que toca ambas mufas; 434 descartando acometidas y exigiendo que recorra el tramo | **Solo coincide con el Visio en el 36–50 % de los casos.** Las troncales del KMZ son largas y su etiqueta describe el cable completo; 12 contra 24 y 12 contra 48 son los desacuerdos más comunes. |

**Propuesta** (en orden; todo marcado con su fuente):
1. **Etiqueta del Visio:** confianza media.
2. **Continuidad a ambos lados:** `estimado`.
3. **Continuidad por un lado:** `estimado`, "por confirmar".
4. **Texto del KMZ:** `estimado`, confianza baja, "por confirmar". Se muestra el texto del KMZ en el editor para que el técnico decida.
5. **Si nada aplica:** `hilos` desconocido, y el editor pide definirlo.

Las reglas 3 y 4 quedan **activables** en `business_rules.yaml`, porque son las de menor acierto.

### 4.2 Coordenadas de los clientes

- **El KMZ ya tiene las acometidas de los clientes**, con su código en el nombre ("C32043 …").
- De los **3 315 códigos de cliente del Visio, 2 329 (70 %) están en el KMZ**: 2 290 en una acometida y 562 en un punto.
- De los 630 clientes con puerto de splitter conocido, 442 tienen ubicación en el KMZ.
- **Propuesta:**
  - el punto de la acometida (su extremo lejos de la mufa) o el punto del KMZ es la ubicación del cliente, con fuente `kmz`;
  - los tickets de Kayako completan el 30 % restante, con fuente `kayako`.
- Para esto falta saber **cómo leer los tickets**: la API de Kayako (URL y clave), el flujo de n8n o una exportación.
  - Los tickets que llegan a la API de presupuestos no guardan el código del cliente: `budget_index.json` solo tiene 5 presupuestos y ningún código.

### 4.3 Fusiones por geometría: qué tendría que hacer Jan

`piloto_fusiones.py` genera, por cada mufa elegida, una página que se abre con doble clic. Muestra el diagrama Visio con las fusiones que el programa "leyó" de las líneas dibujadas (verde, naranja o rojo según su confianza) y una tabla. **Lo que haría Jan:**
1. En cada fusión detectada, marcar *Correcto* o *Incorrecto* mirando el dibujo.
2. Anotar cuántas fusiones tiene de verdad ese diagrama.
3. Pulsar *Descargar marcas* (un CSV).

Unos 3–5 minutos por mufa. Con unas 10 mufas variadas sale la precisión real.

**Propuesta para que no tenga que hacerlo:**
- En la fase 3, medirlo primero **en automático** con el anillo como verdad: 87 mufas del anillo tienen hilos legibles, y **16 de ellas tienen diagrama propio**. Se compara lo que lee la geometría con esos empalmes conocidos.
- Se corre sobre una **copia** de `red_fibra.db`, sin tocar la original.
- **Si la precisión automática es clara** (≥ 85 % o muy baja), se decide con eso.
- **Solo si queda en duda**, se le pide a Jan marcar unas pocas mufas.

---

## 5. Preguntas originales

1. **Entrada del splitter:** ¿ocupa una de las 24 posiciones de la bandeja (1x8 → 9 posiciones) o solo cuentan sus salidas (8)? Propuesta: **sí ocupa**.
2. **24 y 48 hilos:** ¿la configuración más común es 6x4 o 12x2, y 6x8 o 12x4? Será la regla por defecto, porque solo 4 textos de toda la red dicen la configuración.
3. **6, 12, 72, 96 y 144 hilos:** ¿1x6, 1x12, 6x12, 8x12 y 12x12? En la red existe también 12 h como "6 BUFFER DE 2HILOS" (UFINET); la propongo como alternativa.
4. **Fusiones por geometría:** el piloto nunca se corrió. Propuesta:
   - en la fase 3, correr `piloto_fusiones.py` sobre unas 10 mufas variadas que elijas, para que las marques en el reporte HTML (unos 30-45 minutos);
   - con esa precisión se decide el umbral (≥ 85 %);
   - mientras tanto, `usar: false`.
5. **Kayako:** ¿de dónde se leen las coordenadas de las solicitudes (base, API, exportación)? Hoy no hay nada en el proyecto. Sin eso, los clientes quedan en su puerto o en su mufa, sin punto en el mapa.
6. **Proyectos base:**
   - ¿te sirve la agrupación por región de §3.1?
   - ¿y dónde van "RED SAN BENITO" y "Referencia"?
   - Managua queda en un solo proyecto de unas 2 530 mufas; ¿prefieres partirlo por nodo (Gruta, Merced, Periodista, Oriental…)?
7. **Clave de idempotencia:** ¿de acuerdo con nombre normalizado + coordenada, en lugar de id Visio + md5 (§1.7-1)?
8. **Qué nodos se migran:** RESERVA (13) y OTRO (81) quedan fuera, como dice el plan. ¿Las reservas deberían entrar como elementos?
