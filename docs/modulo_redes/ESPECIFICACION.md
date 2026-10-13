# Módulo de Proyectos y Diagramación de Redes FTTH (Visor de rutas)

> **Instrucciones para Claude Code:** lee este archivo completo y **abre cada imagen de `img/`
> con la herramienta Read cuando se mencione**. Las imágenes son capturas de referencia de una
> herramienta comercial (OZmap): úsalas solo como guía de comportamiento y distribución, **no
> copies su marca, logo ni textos**. Trabaja **por fases** (sección 9): al terminar cada fase,
> detente, muéstrame qué hiciste y cómo probarlo, y espera mi OK antes de seguir.

---

## 1. Contexto del proyecto (lo que ya existe)

- **API de presupuestos** (`main.py`, FastAPI): n8n la llama por el túnel de **ngrok** con los
  datos de Kayako → genera Excel/PDF → n8n lo envía al vendedor. **Es la función principal y no
  se toca**: mismos endpoints, mismo body, mismas respuestas, mismo `budget_index.json`.
- **Visor de rutas de escritorio** (`visor_rutas/`, HTML + Leaflet dentro de pywebview, con
  modo local y, si ya existe, modo remoto por `/visor/*`):
  - Vista principal con mapa, cálculo de ruta, presupuesto aproximado, ruta de fusión y
    diagramas Visio de cada mufa ("Ver diagrama").
  - Menú hamburguesa (☰) con "Mapa y ruta" y "Generar presupuesto".
  - Capas: KMZ de la red (panel "Lugares" estilo Google Earth, si ya se implementó) y red Visio.
- **Bases de datos PostgreSQL**:
  - KMZ en PostGIS (`DB_*`: `red_lineas`, `red_puntos`), usada por el presupuesto.
  - Red Visio en `Presupuesto_visio` (`VISIO_DB_*`, esquema `red_fibra`).
- Windows **sin permisos de administrador**, mismo `.venv`, LibreOffice Portable.
- Preferencia del dueño: **entregar archivos COMPLETOS listos para reemplazar**, no fragmentos.

**Objetivo del módulo:** que los usuarios diseñen y documenten sus propias redes de fibra
(postes, mufas, clientes, cables, hilos, splitters) dentro del visor, guardándolo en PostgreSQL,
para ir reemplazando poco a poco los diagramas Visio, **sin quitar** la consulta de las mufas
existentes con sus diagramas Visio, que se seguirán usando.

---

## 2. Menú hamburguesa ampliado

Referencia: `img/01_menu_hamburguesa.png`

Opciones, cada una con un ícono representativo (SVG local, sin CDN):

| Opción | Ícono sugerido | Contenido |
|---|---|---|
| Mapa | mapa | Vista principal actual (ruta, capas, presupuesto aproximado) |
| Presupuestos | calculadora / documento | La vista "Generar presupuesto" actual + historial de presupuestos del visor (`output/visor/`) |
| Proyectos | casa / carpeta | Sección 3 |
| Problemas | triángulo de alerta | Sección 7.1 |
| Pendientes | portapapeles / camión | Sección 7.2 |
| Usuarios | persona | Sección 7.3 |
| Backup | base de datos | Sección 7.4 |

- El menú se puede contraer a solo íconos (botón «‹» arriba, como en la imagen) y expandir con
  texto. Recordar el estado.
- Resaltar la opción activa. Las opciones de fases aún no hechas se muestran deshabilitadas con
  el tooltip "Próximamente".

---

## 3. Proyectos

### 3.1 Lista de proyectos
Referencia: `img/02_lista_proyectos.png`

- Buscador "Filtrar proyectos" arriba.
- Una tarjeta por proyecto: imagen/logo del proyecto, nombre, y acciones a la derecha:
  **Información** (i), **Historial** (reloj: quién cambió qué y cuándo), **Editar datos**
  (lápiz), **Duplicar** y **Eliminar** (con confirmación; borrado lógico).
- Clic en la tarjeta → abre el proyecto en el editor de mapa (sección 4).
- Botón fijo **abajo a la derecha: "+ Crear proyecto"**.

### 3.2 Datos del proyecto (crear / editar)
Referencia: `img/03_datos_proyecto.png`

Ventana modal con:
- **Imagen** del proyecto: "Seleccionar archivo" / "Eliminar la imagen" (guardar en la base o
  en una carpeta de adjuntos con ruta en la base).
- **Nombre** (obligatorio) e **Identificador** (código corto único, obligatorio).
- **Usuarios** con acceso (selección múltiple de la tabla de usuarios).
- **Proyectos principales**: proyecto padre opcional (jerarquía de proyectos).
- **Buscar por dirección** + mapa pequeño con capas Mapa/Satélite para fijar la **ubicación**
  (marcador arrastrable). La búsqueda de dirección puede usar Google Geocoding con la clave
  existente; si no hay internet, permitir pegar coordenadas.
- **Diseñar área**: dibujar en ese mapa el polígono del área del proyecto.
- Botones **Cancelar** / **Guardar**.

---

## 4. Editor de red en el mapa (dentro de un proyecto)

Al abrir un proyecto, el mapa principal entra en **modo edición del proyecto**: se ven las capas
actuales (KMZ, Visio, etc., configurables) y, encima, los elementos del proyecto.

### 4.1 Paleta de elementos de red (arrastrar y soltar)
- **Poste** (tipos: IDEAY, concreto, madera, metal, cliente).
- **Mufa** (capacidad en hilos / bandejas, tipo: empalme, distribución, terminal/FAT).
- **Casa de cliente** (código de cliente C#####, nombre, ID de servicio).
- **Cable de fibra**: troncal, distribución o acometida, con:
  - **tipo ADSS o FLAT**,
  - **cantidad de hilos** (12, 24, 48, 72, 96, 144) y **hilos por buffer** (8 o 12; ver 5.1),
  - **color personalizado** para dibujarlo en el mapa,
  - nombre y descripción.

Comportamiento:
- El usuario **arrastra un ícono** de la paleta y lo **suelta en el mapa**; al soltar se pide el
  **nombre** (obligatorio) y los datos básicos del tipo.
- El **cable se dibuja** haciendo clic desde un elemento a otro (con puntos intermedios),
  **pegándose (snap)** a postes y mufas. Se puede editar la geometría después, moviendo vértices.
- Mostrar la **longitud** del cable y el **detalle del metraje** al pasar el mouse
  (referencia `img/06_detalle_metraje_cable.png`): distancia lineal, contingencia, salida de nodo,
  reservas por mufa, por tendido y por cruce. Tomar los valores de reserva de
  `business_rules.yaml` (sección nueva `diseno_red` con comentarios); no inventar reglas.
- Seleccionar, mover, editar, duplicar y eliminar elementos (con confirmación si tiene conexiones).
- **Notas en el mapa**: cuadros de texto con formato básico (negrita, cursiva, tipo y tamaño de
  letra, listas, color), anclados a un elemento o a una posición.
- Deshacer/rehacer (Ctrl+Z / Ctrl+Y) y guardado explícito, con aviso de cambios sin guardar.

### 4.2 Tecla Enter sobre una mufa
- **Mufa del proyecto** → abre el **editor de mufa** (sección 5).
- **Mufa existente de la red** (KMZ o Visio) → abre su **diagrama Visio** correspondiente, con
  el mismo visor que ya existe en "Ver diagrama". Si tiene varios diagramas, mostrar el selector.
- Doble clic hace lo mismo que Enter.

---

## 5. Editor de mufa (diagramación de hilos)

Referencias: `img/04_concepto_cable_troncal_mufa.png`, `img/05_editor_mufa_hilos_y_splitter.png`,
`img/08_mufa_con_splitters_hacia_fat.png`, `img/07_conector_salida_hacia_fat.png`

La idea es reemplazar los diagramas Visio grandes y confusos por **una vista por mufa**: solo lo
que entra y sale de esa mufa, y desde ahí navegar a la siguiente.

### 5.1 Representación
- Ventana grande (maximizable) con lienzo de cuadrícula, zoom y desplazamiento.
- Cada **cable** que llega o sale de la mufa aparece como una **barra vertical por buffer/tubo**,
  con sus **hilos numerados** en círculos y coloreados con el **código TIA-598**:
  1 azul, 2 naranja, 3 verde, 4 café, 5 gris, 6 blanco, 7 rojo, 8 negro, 9 amarillo,
  10 violeta, 11 rosa, 12 aqua.
  - El color del **buffer** también sigue TIA-598 (buffer 1 azul, 2 naranja…).
  - Si el cable está configurado con **8 hilos por buffer**, los colores se repiten cada 8
    (ejemplo del dueño: mufa de 16 hilos = hilos 1–8 y 9–16 con los colores 1–8). Si tiene 12,
    se repiten cada 12. Debe ser un dato del cable, no fijo.
- Encabezado del cable: "Cable | origen | destino | hilos" (como "C-Mufa | 21-Mufa | 25").
- Tooltip al pasar sobre un cable o hilo: nombre, tipo, hilos, metraje con su detalle (ver
  `img/06_detalle_metraje_cable.png`), estado y a qué está conectado en cada extremo.

### 5.2 Operaciones
Barra de herramientas arriba y abajo, como en las referencias:
- **Conectar hilos**: arrastrar desde un hilo (por ejemplo, el 2 del cable troncal) hasta otro
  hilo de otro cable (**fusión**) o hasta la **entrada de un splitter**. La conexión se dibuja
  como línea ortogonal del color del hilo de origen.
- **Splitters**: agregar 1x2, 1x4, 1x8, 1x16, 1x32, balanceados o desbalanceados (por ejemplo,
  70/30), con nombre ("Splitter 1 (01x02 RC)"), entrada y salidas numeradas. Las salidas se
  conectan a hilos de cables de salida o a conectores.
- **Conectores / adaptadores** (conector de salida hacia FAT o cliente; ver
  `img/07_conector_salida_hacia_fat.png`).
- **Estado de cada hilo**: activo, **fibra oscura**, **cliente de baja**, reservado, dañado.
  Se ve en el dibujo (por ejemplo, gris o punteado) y en el tooltip.
- **Eliminar conexión**, eliminar splitter o conector, reordenar, alinear y distribuir elementos.
- **Notas**: cuadros de texto con formato (negrita, tipo de letra, listas) dentro del lienzo.
- Todo elemento soltado lleva **nombre** obligatorio.
- Botones **Aplicar** (guardar sin cerrar) y **Guardar / Cerrar**. Opción futura: código QR de
  la mufa (dejarlo preparado; no es obligatorio en la primera versión).

### 5.3 Navegación entre mufas
- En el editor, cada destino conectado (otra mufa, FAT, cliente) se muestra como una **caja con
  su nombre** al final del hilo o del splitter (ver `img/08_mufa_con_splitters_hacia_fat.png`).
- **Enter o doble clic** sobre esa caja → abre el editor de **esa** mufa. Migas de pan arriba
  para volver ("Proyecto > Mufa A > Mufa B").
- **Seguir hilo**: seleccionar un hilo y "Trazar" → resalta el recorrido completo, mufa por
  mufa, hasta el cliente o el extremo final, y lo lista en un panel (también se ve en el mapa).
- Así, desde el cable troncal se puede ver a qué cliente o a qué otra mufa llega cada hilo.

---

## 6. Diagrama lógico de red

Referencias: `img/09_diagrama_logico_red.png`, `img/10_leyenda_ftth.png`

- Ventana "Diagrama lógico de red" con una tabla de diagramas guardados (título, elemento de
  inicio, caja, dirección izquierda/derecha, "incluir inmuebles/clientes") y, debajo, el
  diagrama.
- Se genera **automáticamente** a partir de las conexiones guardadas: desde el elemento elegido
  (OLT, nodo, mufa o splitter) hacia adelante, de izquierda a derecha, mostrando cada caja
  (mufa, FDT, FAT) con sus splitters dentro y los cables entre cajas con su etiqueta.
- Leyenda FTTH: OLT (triángulo), SC (círculo rojo), FDT (cuadro amarillo), FAT (círculo
  magenta), derivación (punto), y colores de cable por capacidad (por ejemplo, 144 hilos rojo y
  48 hilos morado; configurable).
- Zoom, desplazamiento, clic en una caja → abre su editor de mufa. Exportar a PNG y PDF.

---

## 7. Otras opciones del menú

### 7.1 Problemas
Registro de problemas ligados a un elemento del mapa (mufa, cable, poste, cliente): título,
descripción, severidad, estado (abierto / en proceso / cerrado), fotos y usuario. Se ven como
íconos de alerta en el mapa, con filtro.

### 7.2 Pendientes
Tareas pendientes (por ejemplo, "validar existencia de mufa", "dar continuidad a hilos"),
ligadas a un proyecto o elemento, con responsable, fecha límite y estado. Lista con filtros.

### 7.3 Usuarios
Tabla de usuarios (nombre, correo, rol: administrador, editor, lector). Al abrir el visor, el
usuario se identifica (en modo remoto, con su clave `X-Visor-Key`). Todo cambio queda registrado
con su usuario (historial y auditoría). Los permisos se aplican por proyecto (sección 3.2).

### 7.4 Backup
- Botón "Crear respaldo": exporta el esquema del módulo (proyectos y todo su contenido) a un
  archivo (`.sql` con `pg_dump` si está disponible en la instalación de PostgreSQL; si no,
  exportación JSON completa por proyecto) en una carpeta configurable, con fecha y hora.
- Lista de respaldos y "Restaurar" (con confirmación; restaurar como copia nueva de proyecto,
  sin pisar el actual).
- Exportar un proyecto a **KMZ** (para abrirlo en Google Earth) y a GeoJSON.

---

## 8. Datos y arquitectura

### 8.1 Base de datos
- Esquema nuevo **`redes`** en la base `Presupuesto_visio` (`VISIO_DB_*`). Si no tiene PostGIS,
  guardar la geometría como lat/lon y GeoJSON (`jsonb`). Proponer el modelo en el PASO 0.
- Tablas mínimas sugeridas (ajústalas y justifícalas):
  `usuarios`, `proyectos` (padre, área, ubicación, imagen), `proyecto_usuarios`, `elementos`
  (poste, mufa, cliente, nodo/OLT, FAT/FDT; tipo, nombre, propiedades jsonb, geometría),
  `cables` (tipo ADSS/FLAT, hilos, hilos por buffer, color, extremos, geometría, metraje),
  `hilos` (cable, número, buffer, color TIA, estado), `splitters` (mufa, tipo, relación,
  posición en el lienzo), `puertos` (entradas y salidas de splitters y conectores),
  `conexiones` (de puerto/hilo a puerto/hilo, mufa donde ocurre), `notas` (texto con formato,
  ancla), `problemas`, `pendientes`, `diagramas_logicos`, `historial` (auditoría: usuario,
  fecha, entidad, cambio jsonb).
- Toda escritura con **versión** por registro (bloqueo optimista) para que dos usuarios no se
  pisen los cambios: si alguien guardó antes, avisar y ofrecer recargar.
- Script de **migraciones** versionado (`redes/migraciones/NNN_*.sql`) que se aplica solo al
  iniciar si falta.
- **No modificar** las tablas existentes (`red_lineas`, `red_puntos`, esquema `red_fibra`).

### 8.2 Código
- Backend en Python en un paquete nuevo (por ejemplo, `visor_rutas/redes/`): repositorio de
  datos, servicios (validaciones, trazado de hilos, generación del diagrama lógico, metraje) y
  métodos expuestos al JS por `js_api` (modo local) y por endpoints `/visor/redes/*` con
  `X-Visor-Key` (modo remoto, si existe).
- Frontend: librerías **locales en `web/lib/`** (sin CDN), con licencia libre. Sugerencias
  (elige y justifica): Leaflet-Geoman para dibujar y editar en el mapa; Konva.js o JointJS
  (core) para el editor de mufa y el diagrama lógico; Quill para el texto con formato.
- Separar el JS por módulos (mapa, proyectos, editor de mufa, diagrama lógico, menú) para no
  crecer un solo archivo gigante.

---

## 9. Fases (detenerse al final de cada una)

| Fase | Alcance | Listo cuando |
|---|---|---|
| **0** | Leer el código actual (visor, modo remoto si existe, `main.py`, configuración). Proponer el modelo de datos, las librerías y la estructura de archivos. | Apruebo el plan. |
| **1** | Menú ampliado con íconos y modo contraído. Usuarios básicos (tabla e identificación). Migraciones del esquema `redes`. | Menú funcional, base creada. |
| **2** | Proyectos: lista, crear/editar/duplicar/eliminar, historial, imagen, ubicación, área, jerarquía y usuarios. | CRUD completo guardado en PostgreSQL. |
| **3** | Editor de mapa: paleta (poste, mufa, cliente, cable ADSS/FLAT con color), arrastrar y soltar, snap, nombres, metraje con detalle, notas con formato, deshacer/rehacer. Enter en mufa existente → diagrama Visio. | Diseño un tramo con 2 mufas, postes y un cliente y queda guardado. |
| **4** | Editor de mufa: cables con buffers e hilos TIA, conexiones arrastrando, splitters, conectores, estados de hilo, notas, Aplicar/Guardar, navegación con Enter y migas de pan. | Conecto un hilo troncal a un splitter 1x8 y una salida a otra mufa, y navego. |
| **5** | Trazado de hilo de punta a punta (panel y mapa). | Desde un hilo del troncal veo a qué cliente llega. |
| **6** | Diagrama lógico de red automático, con leyenda y exportación. | Se genera desde una mufa y se exporta a PDF. |
| **7** | Problemas, Pendientes y Backup (respaldo, restauración y exportación a KMZ/GeoJSON). | Funcionan las tres opciones. |

En cada fase:
- **Pruebas** en `Pruebas/` (repositorio con base de prueba, validaciones, trazado, diagrama
  lógico y permisos), y que **todas las pruebas existentes sigan pasando**.
- `POST /presupuesto` y n8n **sin cambios** (verificarlo).
- Archivos **completos** listos para reemplazar.
- Actualizar el `README.md` (sección del visor: módulo de Proyectos y Diagramación).

## 10. Restricciones
- Windows sin permisos de administrador; mismo `.venv`; nada que requiera instalar servicios.
- Google Directions sigue en modo `driving`. No cambiar reglas de presupuesto existentes.
- No quitar ni romper: diagramas Visio, ruta de fusión, capas KMZ y Visio, presupuesto aproximado,
  modo remoto/.exe.
- Todo en español en la interfaz.
