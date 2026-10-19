# Visor de rutas – Nuevas funcionalidades (versión 2)

> **Para Claude Code:** lee este archivo completo y **abre cada imagen de `img_v2/`** cuando se
> mencione (son capturas del visor actual y de Google Earth, como referencia de comportamiento; no
> copies marcas). Trabaja **por fases** (sección 10): al terminar cada una, detente, muéstrame qué
> hiciste y cómo probarlo, y espera mi OK. Entrega **archivos completos** listos para reemplazar.
> Interfaz en español.
>
> Este documento reemplaza la especificación anterior del módulo de proyectos, que **ya está
> implementada**. Aquí solo va lo nuevo.

## 1. Contexto y reglas

- **Función principal, no se toca:** la API de presupuestos (`main.py`) que n8n llama por ngrok.
- **Visor de escritorio actual** (`visor_rutas/`, HTML + Leaflet en pywebview):
  - mapa con el panel "Lugares" (árbol del KMZ estilo Google Earth, `kmz_capas.py` y `lugares.js`);
  - buscador superior de mufas por nombre;
  - barra inferior para generar ruta y presupuesto;
  - panel derecho con Resumen, Ruta de fusión, Diagrama y Presupuesto;
  - módulo `redes/` con proyectos, editor de mapa, editor de mufa, trazado, diagrama lógico,
    problemas, pendientes, usuarios y respaldos;
  - modo remoto/.exe.
- **Plan en curso:** `docs/migracion_visio/PLAN.md` (las mufas existentes migradas desde Visio
  al esquema `redes` como "red base"). Este documento se apoya en ese plan; donde haya cruce,
  usar el mismo modelo de "red base" y no duplicarlo.
- **Proyectos** quedan para **planes futuros** (red que todavía no existe). La red real se ve y se
  edita **desde el mapa principal**, sin entrar a un proyecto.
- Sin permisos de administrador; mismo `.venv`; todas las pruebas existentes deben seguir pasando;
  `POST /presupuesto` sin cambios; README actualizado en cada fase.

---

## 2. Arreglos de la interfaz actual

Referencias: `img_v2/09_panel_filtros_actual.png`, `img_v2/10_lugares_minimizado_tapado.png`,
`img_v2/11_panel_derecho_ocupa_espacio.png`, `img_v2/01_mapa_actual_popup_mufa.png`.

1. **Unir el panel de filtros con "Lugares".** El recuadro flotante de capas del visor (Satélite /
   Calles, Postes existentes, Postes nuevos, Mufas en ruta, Mufas intervenidas, Nodos Visio,
   Camino de la fibra, Mufa buscada, Mis medidas, Red Visio · nodos/enlaces) pasa a ser una sección
   del árbol de Lugares ("Capas del visor" y "Mapa base"), con las mismas casillas de tres estados.
   Así queda **un solo panel de capas**.
2. **Verificar que esos filtros funcionan.** Hoy no se nota ningún cambio al marcarlos, sobre todo
   con las capas del KMZ. Revisar cada casilla:
   - qué capa controla, y si esa capa existe aunque no haya una ruta calculada;
   - corregir las que no hagan nada;
   - deshabilitar con un tooltip ("se llena al generar una ruta") las que dependen de un cálculo.
3. **Botones de zoom (+ / −)** abajo a la derecha, donde no tapen nada.
4. **Lugares minimizado:** cuando se contrae, su pestaña "Lugares ›" no debe quedar debajo de
   ningún otro control. Revisar el orden (z-index) y las posiciones de todos los controles
   flotantes.
5. **Panel derecho** (Resumen, Ruta de fusión, Diagrama, Presupuesto):
   - oculto por defecto mientras no haya un resultado;
   - se abre solo al generar una ruta o al seleccionar una mufa;
   - más angosto y redimensionable;
   - se puede contraer a una pestaña lateral.

   Hoy ocupa casi un cuarto de la pantalla vacío.
6. Revisar el diseño a 1366×768 y a 1920×1080: el mapa debe quedar con el mayor espacio posible.

---

## 3. Buscador superior: mufas y coordenadas

Referencia: `img_v2/08_pin_coordenada_buscada.png`

- El buscador de arriba acepta, además de nombres de mufa:
  - decimal: `13.094578, -86.002708`, `13.094578 -86.002708` o `13.094578;-86.002708`;
  - grados, minutos y segundos (como en Google Earth): `13°5'38.09"N 86°0'7.42"O`, también con
    `W`, con espacios o con `º`;
  - grados y minutos decimales: `13 5.6348N 86 0.1237W`.
- Validar que caiga en Nicaragua y avisar si latitud y longitud parecen invertidas.
- Al buscar una coordenada:
  - volar a ella y poner un **pincho** (pin) con una **etiqueta con las coordenadas en decimal**
    (como en la imagen);
  - clic en el pin: copiar en decimal o en grados/minutos/segundos, "Guardar en Mis lugares",
    "Usar para generar ruta" (llena la barra inferior sin calcular) y "Quitar".
  - **No calcula presupuesto ni ruta.** La barra inferior queda exactamente como está.
- Las sugerencias mezclan resultados: mufas del KMZ y de la red base, nodos Visio, elementos de
  Mis lugares y "Ir a la coordenada …".

---

## 4. Mis lugares (funciones de Google Earth)

Referencias: `img_v2/02_barra_herramientas_google_earth.png`, `img_v2/03_nueva_marca_posicion.png`,
`img_v2/04_marca_pestana_ver.png`, `img_v2/05_marca_nombre_lat_lon.png`,
`img_v2/06_selector_iconos.png`, `img_v2/07_nueva_ruta.png`

### 4.1 Carpetas
- En el árbol de Lugares, una raíz **"Mis lugares"** (por usuario) junto a "RED DE IDEAY".
- Crear, renombrar, eliminar (con confirmación) y mover carpetas y subcarpetas; arrastrar y soltar
  elementos entre carpetas; casilla de visibilidad de tres estados; orden manual.
- Clic derecho en una carpeta: "Nueva carpeta", "Agregar marca de posición aquí", "Agregar ruta",
  "Agregar polígono", "Encuadrar", "Exportar a KMZ", "Guardar como proyecto", "Eliminar".

### 4.2 Barra de herramientas (como Google Earth)
Una barra arriba del mapa (íconos, sin ventana aparte) con:
- **Marca de posición**
- **Polígono**
- **Ruta**
- **Medir** (distancia y área; integrar con "Mis medidas")
- Elementos de red: **mufa, poste, cliente, cable** (ver sección 5)
- **Importar** (sección 6) y **Coordenadas masivas** (sección 7)

### 4.3 Marca de posición
Diálogo como en Google Earth:
- Nombre, y latitud/longitud que se pueden escribir en decimal o en grados/minutos/segundos. Al
  arrastrar el pin en el mapa se actualizan.
- Pestañas:
  - **Descripción:** texto con formato, agregar vínculo, agregar imagen local (se guarda en la
    base o en una carpeta de adjuntos).
  - **Estilo, color:** selector de ícono (pushpins de colores, letras, números, figuras; ver
    `06_selector_iconos.png`), color, escala, opacidad, color y escala de la etiqueta. Usar SVG
    locales equivalentes, sin depender de Google.
  - **Ver:** centrar en la vista y "Instantánea de vista actual" (guarda el centro y el zoom para
    volar ahí después).
- Botones Aceptar / Cancelar.

### 4.4 Ruta y polígono
Diálogo similar (ver `07_nueva_ruta.png`): nombre, descripción, estilo (color, grosor,
opacidad, relleno en polígonos), la pestaña **Medidas** (longitud de la ruta, perímetro y área
del polígono) y dibujo punto por punto en el mapa, con edición de vértices.

### 4.5 Guardado
- Todo se guarda en PostgreSQL (tablas nuevas, por ejemplo `redes.lugares_carpetas` y
  `redes.lugares_elementos` con geometría, estilo y vista), por usuario. Opción de compartir
  una carpeta con otros usuarios.
- **"Guardar como proyecto":** convierte una carpeta, con sus elementos de red, en un proyecto
  del módulo Proyectos (plan futuro).
- Exportar e importar una carpeta como KMZ.

---

## 5. Edición de la red real desde el mapa

### 5.1 Entrar a cualquier mufa
Referencia: `img_v2/01_mapa_actual_popup_mufa.png`

- El popup de una mufa del KMZ (o de la red base) agrega, junto a "Ver diagrama Visio", un botón
  **"Entrar a la mufa"**. También funciona con Enter o doble clic sobre la mufa seleccionada.
- Abre el **editor de mufa** (el mismo de proyectos) con los datos de la **red base**:
  - si la mufa ya se migró (plan de migración Visio), se ven sus cables, hilos, bandejas,
    splitters y conexiones;
  - si todavía no existe en la red base, se crea en ese momento, ligada al punto del KMZ
    (`ref_externa`), vacía y lista para diagramar.
- Desde el editor se navega a las mufas vecinas, igual que en proyectos.

### 5.2 Herramientas de edición de red (sin entrar a un proyecto)
- Un modo **"Editar red"** (botón en la barra de herramientas) que habilita:
  - agregar mufa, poste, cliente, nodo y cable (troncal o distribución, ADSS/FLAT, hilos,
    configuración de buffers, color) **sobre la red actual**, con snap a mufas y postes del KMZ y
    de la red base;
  - **editar y borrar elementos del KMZ y de la red base** (mover, renombrar, cambiar
    propiedades, eliminar);
  - unir lo nuevo con lo existente (por ejemplo, un cable nuevo desde una mufa del KMZ).
- **No es una ventana aparte:** se trabaja en el mismo mapa, con una barra de estado que muestra
  "N cambios sin guardar" y los botones **Guardar**, **Deshacer / Rehacer** y
  **Descartar cambios**.
- Los cambios se guardan en la **red base** (esquema `redes`) con historial y usuario. **El
  archivo KMZ original no se modifica**: la capa del KMZ muestra el estado efectivo (KMZ + cambios
  guardados). Lo editado o borrado del KMZ se registra como capa de cambios, para poder revertir y
  para exportar un KMZ actualizado.
- Permisos: solo usuarios con rol editor o administrador; los demás ven el botón deshabilitado.
- Al guardar cambios que afecten mufas, postes o líneas usadas por el presupuesto, avisar que el
  presupuesto usa PostGIS (`red_lineas` / `red_puntos`) y ofrecer "Publicar en la red del
  presupuesto", con respaldo previo (ver 6.3).

### 5.3 Capas
Todo lo agregado o editado se ve en el árbol de Lugares como capas activables, igual que el KMZ:
"Red base · mufas", "· postes", "· cables", "· clientes", "Cambios sin publicar", y Mis lugares.

---

## 6. Importar KMZ desde el programa

### 6.1 Dos modos
1. **Nueva ruta o elementos:** el archivo aparece primero como una capa nueva en
   **"Importados (pendientes)"**, con el **nombre del archivo**, para revisarlo. Luego, con
   **"Aplicar a la red"**, sus elementos pasan a la red base.
2. **Actualización de toda la red:** un KMZ completo (como `RED_DE_IDEAY.kmz`) que reemplaza o
   actualiza la red.

### 6.2 Detectar qué cambió
Al importar, comparar con la red actual (KMZ vigente + red base) y clasificar cada elemento:
- **Nuevo:** no existe ninguno con nombre parecido cerca.
- **Modificado:** mismo elemento (por nombre normalizado + cercanía, o por geometría casi igual)
  con cambios de posición, trazo, descripción o estilo.
- **Sin cambios.**
- **Eliminado:** está en la red y no en el archivo; solo en el modo de actualización completa.

Mostrar una **pantalla de revisión**:
- conteos por tipo;
- lista filtrable y vista en el mapa con colores (verde nuevo, naranja modificado, rojo eliminado);
- casillas para aceptar o rechazar cada cambio o grupos enteros.
- Detectar también si el archivo es una ruta nueva (todo nuevo, en una zona sin red) o un cambio a
  la red existente, y sugerir el modo.

### 6.3 Aplicar
- Respaldo automático antes de aplicar.
- Aplicar a la red base y regenerar la caché del árbol de Lugares (`kmz_capas.py`).
- Opción de **publicar también en PostGIS** (`red_lineas` / `red_puntos`) para que el presupuesto
  use la red nueva. Respaldo de esas tablas antes, y reporte de lo que cambió.
- Guardar el historial de importaciones (archivo, md5, fecha, usuario, cambios aplicados) con la
  opción de revertir la última.

---

## 7. Coordenadas masivas (varios presupuestos a la vez)

- Herramienta "Coordenadas masivas" en la barra: subir un archivo **Excel (.xlsx/.xls), CSV,
  Word (.docx), texto o notas (.txt)**.
- Extraer todas las coordenadas:
  - en Excel o CSV, detectar las columnas (latitud/longitud o una sola columna) y las columnas
    opcionales de nombre o código de cliente;
  - en Word o texto, buscar coordenadas con los mismos formatos del buscador (sección 3);
  - mostrar una vista previa para confirmar, marcar las inválidas o duplicadas y permitir
    corregirlas.
- Ver todos los puntos en el mapa (capa temporal con número y nombre).
- **Calcular el presupuesto de cada una** con la misma lógica del presupuesto aproximado del visor
  (supuestos de `visor_estimacion`), en segundo plano, con una barra de progreso y la opción de
  cancelar. Respetar un límite de llamadas a Google por minuto (configurable) y avisar el costo
  estimado antes de empezar.
- Tabla de resultados: punto de conexión, distancia por ruta, metraje, tipo de cable, postes,
  total, avisos. Ordenable, con clic para ver la ruta en el mapa.
- Opciones al terminar:
  - **"Generar presupuestos":** guarda un Excel por coordenada más un Excel resumen en
    `output/visor/masivo_<AAAAMMDD-HHMMSS>_<nombre del archivo>/`, con "Abrir carpeta";
  - **"Guardar como proyecto":** crea un proyecto con esos puntos y sus rutas;
  - **"Guardar en Mis lugares":** carpeta con los puntos.

---

## 8. Datos (proponer en la fase 0)

- Mis lugares: carpetas (padre, nombre, orden, visible, usuario, compartida) y elementos (tipo
  marca/ruta/polígono, geometría, nombre, descripción HTML, estilo jsonb, vista jsonb, adjuntos).
- Edición de red: usar el modelo de "red base" del plan de migración Visio (`es_red_base`,
  `fuente`, `estado_migracion`) más una tabla de cambios sobre el KMZ (elemento KMZ, acción
  editar/borrar, valores anteriores y nuevos, usuario, fecha, publicado sí/no).
- Importaciones KMZ: historial y detalle de cambios.
- Lotes masivos: lote, archivo, usuario, puntos, resultados y carpeta de salida.
- Migraciones SQL numeradas a continuación de las existentes, idempotentes, con respaldo previo.

---

## 9. Modo remoto (.exe)

Todo lo nuevo debe funcionar también en modo remoto por `/visor/*` con `X-Visor-Key`:
- Mis lugares y edición de red por la API, con los mismos permisos;
- importación de KMZ y coordenadas masivas subiendo el archivo;
- los presupuestos masivos se generan en el servidor y se descargan como .zip.

---

## 10. Fases (detenerse al final de cada una)

| Fase | Alcance | Listo cuando |
|---|---|---|
| **0** | Leer el código actual (`ventana_web.py`, `visor.js`, `lugares.js`, `menu.js`, `redes/`, `kmz_capas.py`, `calculo.py`, `presupuesto_visor.py`, `remoto.py`) y el plan de migración Visio. Proponer el modelo de datos, la estructura de archivos JS (sin crecer `visor.js`) y cómo se cruza con la red base. | Apruebo el plan. |
| **1** | Arreglos de interfaz (sección 2). | Un solo panel de capas, filtros que funcionan, zoom abajo a la derecha, nada tapado, panel derecho oculto hasta tener resultado. |
| **2** | Buscador de coordenadas con pin (sección 3). | Busco en decimal y en grados/minutos/segundos, aparece el pin con la etiqueta y no se calcula nada. |
| **3** | Mis lugares: carpetas, marca de posición, ruta, polígono, estilos, íconos, vista, exportar e importar KMZ de una carpeta (sección 4). | Creo carpetas y elementos, se guardan y siguen ahí al reabrir. |
| **4** | Entrar a cualquier mufa desde el mapa y modo "Editar red" con Guardar/Deshacer/Descartar (sección 5). | Entro a una mufa del KMZ, la diagramo, agrego un cable nuevo desde ella, edito una mufa del KMZ y guardo. |
| **5** | Importar KMZ: dos modos, comparación, revisión, aplicar, publicar en PostGIS y revertir (sección 6). | Importo una ruta nueva y una actualización, reviso los cambios y los aplico. |
| **6** | Coordenadas masivas (sección 7). | Subo un Excel con 20 coordenadas, veo los puntos, genero los presupuestos en su carpeta y lo guardo como proyecto. |
| **7** | Modo remoto para todo lo anterior (sección 9). | Funciona igual desde el .exe. |

En cada fase: pruebas en `Pruebas/`, todas las existentes pasan, `POST /presupuesto` sin cambios,
README actualizado.
