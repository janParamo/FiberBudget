# Bitácora del 9 de octubre de 2026

Viene de [../2026-10-08/](../2026-10-08/LEEME.md). Esta carpeta se va actualizando durante el día.

## Decisiones de Jan (mañana)

| Punto | Decisión |
|---|---|
| D1. Fase 1 del módulo de redes | **Aprobada** |
| D2. Historial de presupuestos en "Presupuestos" | **Sí**: va al inicio de la fase 2 |
| D3. Reglas de metraje | **Decidido: los mismos valores del presupuesto.** Contingencia 0 %, tendido cada 300 m al 20 %, 35 m por mufa, y 0 m en salida de nodo, cruce y extremo en cliente. Iguales para todos los cables y redondeo al metro hacia arriba. Se aplica en la fase 3, en la sección `diseno_red` de `business_rules.yaml`. |
| D4. PostGIS en el esquema `redes` | **Se queda así** |
| D5 y D6. Lugares, menú y Usuarios en la ventana real | **Aprobados** |
| Subir a GitHub / archivos borrados el 7 oct | **No se hacen** |

## ¿n8n funciona al reiniciar `start_service.bat`? (verificado)

**Sí.** `start_service.bat` hace lo de siempre: `uvicorn main:app` en `127.0.0.1:8000` y conecta el mismo dominio de ngrok al arrancar.

Se cargó `main:app` con el `.env` real y el código actual, sin arrancar ngrok ni generar presupuestos:
- **Arranque:** `GET /health` responde 200.
- **`POST /presupuesto`:**
  - sin clave → 401;
  - con clave y body vacío → 422, es decir, valida el body igual que antes.
- **Endpoints de n8n:** siguen iguales (`/presupuesto`, `/presupuesto/{id}/excel`, `/presupuesto/{id}/pdf`, `/origen`, `/health`). Lo nuevo vive solo bajo `/visor/*`.
- **Módulos nuevos:** el de redes y el del KMZ **no se cargan al arrancar**, solo cuando alguien los usa desde el visor. Un problema en ellos no afecta a n8n.

**Lo único que n8n verá distinto** son dos cosas pedidas por Jan:
1. Cada Excel y PDF trae la nota "Sujeto a disponibilidad de postes de concreto sobre la ruta" en cada página.
2. Nada más cambia en cantidades o respuestas. Las marcas de postes existentes son solo del visor: n8n nunca las envía, así que su presupuesto calcula los postes igual que antes.

## Reglas de metraje que Jan debe especificar (D3, para la fase 3)

Ver el detalle en [01_reglas_metraje.md](01_reglas_metraje.md).

## Fase 2 (Proyectos): terminada, espera el OK de Jan

**Estado:**
- **Pruebas:** **271** pasan (+10 de esta fase).
- **Migración** `002_proyectos.sql` **aplicada en `Presupuesto_visio`** (columna `miniatura`, sin SVG, índice por nombre).
- **`VisorRutas.zip`:** regenerado y verificado (24.5 MB).
- **Interfaz:** revisada en Edge headless (lista en árbol, ventana de datos con minimapa, información, historial de presupuestos). Se corrigió el selector Mapa/Satélite, que se deformaba con los estilos de los campos del formulario.

**Para usarlo en remoto (Marlon):** reiniciar `start_service.bat` y pasarle el zip nuevo (A1 y A2 del 8 oct siguen pendientes).

**Decisiones de Claude en esta fase:**
- **Clic en una tarjeta** abre la Información; el editor de red llega en la fase 3.
- **Eliminar** un proyecto con subproyectos activos se rechaza. **Restaurar** exige que el identificador siga libre.
- **Duplicar** copia datos, imagen, área y usuarios. Desde la fase 3 copiará también la red.
- **El creador** siempre queda asignado al proyecto. Un editor no puede quitarse a sí mismo.
- **Historial de presupuestos:** el cliente, la fecha y la coordenada salen del nombre del archivo; el total se lee al abrir uno.

Avance:

- [x] Historial de presupuestos: backend
  - `presupuesto_visor.historial` / `abrir_guardado`;
  - `Api.historial_presupuestos` / `abrir_presupuesto_guardado`;
  - remoto: `GET /visor/presupuestos` y `/visor/presupuestos/{id}`.
- [x] Backend de proyectos (`visor_rutas/redes/proyectos.py` + migración `002_proyectos.sql`):
  - CRUD, duplicar, eliminar/restaurar (borrado lógico) e historial;
  - imagen PNG/JPG/WEBP/GIF de hasta 2 MB con miniatura (SVG rechazado);
  - ubicación y área en PostGIS, jerarquía sin ciclos, usuarios y permisos;
  - búsqueda de dirección con Google Geocoding. **Probada con la clave real: funciona.** En remoto cuenta para el límite por hora.
  - 9 pruebas en `Pruebas/test_redes_proyectos.py`.
- [x] Leaflet-Geoman free 2.17.0 (MIT) copiado en `web/lib/geoman/`, sin recursos externos.
- [x] Vista Proyectos (`web/redes/proyectos.js` + `redes.css`):
  - lista en árbol, filtro, tarjetas con Información, Historial, Editar, Duplicar y Eliminar/Restaurar, y "+ Crear proyecto";
  - ventana "Datos del proyecto" con imagen, usuarios (chips), proyecto principal, dirección o coordenada pegada, minimapa Mapa/Satélite con marcador arrastrable, y "Diseñar área" con Geoman.
- [x] Historial de presupuestos: pestaña "Historial" en Presupuestos, con filtro y "Incluir aproximados".
- [x] Pruebas, README, `VisorRutas.zip`

## Cambio en el presupuesto: Preformada Punto Verde = 2 × Clevis (ADSS)

- **Jan** cambió la plantilla real: `Presupuesto!G42` = `=G37*2`, es decir, 2 × Clevis tipo D Chico = 2 por poste.
- **`business_rules.yaml`:** se quitó la regla que, para ADSS, sobrescribía esa celda con `=G39` (hebillas, 1 por poste). Flat sigue escribiendo `0`.
  - **ADSS:** se usa la fórmula de la plantilla.
  - **Flat:** 0.
- **Verificado** con la plantilla real y LibreOffice:
  - Flat, 420 m, 8 postes: Clevis 8, Preformada 0;
  - ADSS, 900 m, 18 postes: Clevis 18, Preformada **36**.
- **Pruebas:** se actualizó la plantilla de prueba (`make_sample_template.py`, fila 40 = `=G35*2`) y la línea de `test_api.py` que verificaba la regla vieja. Pasan las 271.
- **Aplica de inmediato**, también para n8n: el servicio lee `business_rules.yaml` y la plantilla en cada presupuesto, sin reiniciar.
- **Pendiente menor:** `presupuesto.calcular_materiales` todavía cuenta 1 preformada por poste en un dato interno que **no se escribe en el Excel**. Igualarlo exige cambiar una prueba vieja; se hace solo si Jan quiere.

## Cambio pedido por Jan: varios clientes por proyecto (hecho)

Un proyecto encierra un área donde puede haber **varios clientes**. En "Datos del proyecto" hay una sección **Clientes del proyecto**:
- tabla con nombre (obligatorio), código C##### (opcional, único en el proyecto), ID de servicio y coordenada editable;
- **＋ Agregar en el mapa**: cada clic agrega un cliente; con ese modo activo, la búsqueda de dirección o una coordenada pegada también agregan un cliente;
- **Pegar coordenadas**: varias a la vez, una por línea (`lat, lon[, nombre][, código]`); avisa qué líneas no sirven;
- marcadores verdes (casa) arrastrables en el minimapa; quitar un cliente es borrado lógico.

Detalles:
- La ubicación del proyecto (marcador azul) sigue existiendo aparte.
- **Datos:** los clientes se guardan en la tabla nueva `redes.elementos` (migración `003_elementos.sql`, **aplicada**) como elementos tipo `cliente`. Son las mismas casas de cliente que dibujará el editor de mapa (fase 3), sin duplicar datos.
- **Duplicar** copia también los clientes. El historial registra la lista de clientes antes y después.
- **Pruebas:** 2 nuevas. Pasan las 273.

## Fase 3 (editor de red en el mapa): terminada, espera el OK de Jan

**Estado:**
- **Pruebas:** **280** pasan (+7 de esta fase en `Pruebas/test_redes_editor.py`).
- **Migración** `004_cables_notas.sql` **aplicada en `Presupuesto_visio`**.
- **`VisorRutas.zip`:** regenerado y verificado (24.6 MB).

**Qué se hizo:**
- **Backend:**
  - `visor_rutas/redes/red.py`: carga y guardado de la red en una transacción, con ids temporales, versión por registro, cables pegados a elementos que los siguen al moverse, no borrar elementos con cables, historial y copia de la red al duplicar;
  - `metraje.py` (reglas `diseno_red`) y `texto.py` (HTML seguro de las notas);
  - `business_rules.yaml`: sección `diseno_red` con los mismos valores del presupuesto (D3).
- **Página:**
  - `web/redes/editor_mapa.js`: franja del proyecto arriba del mapa, paleta para arrastrar y soltar (poste, mufa, cliente, nodo), cable con imán a postes y mufas, metraje con detalle al pasar el mouse, inspector, notas Quill, deshacer/rehacer, Ctrl+S, Supr, F2 y Enter;
  - `lugares.js` y `visor.js`: Enter o doble clic sobre una mufa existente (KMZ o Visio) abre su diagrama Visio, y el popup tiene "Ver diagrama Visio";
  - en la lista de proyectos, clic en la tarjeta abre el proyecto en el mapa.
- **Librería nueva:** Quill 2.0.3 (BSD-3) en `web/lib/quill/`.
- **Revisado en Edge headless:**
  - se soltaron 3 elementos y se dibujó un cable MF Norte → P-01 → FAT 1 pegado al poste;
  - metraje 623 m = 432 lineal + 70 (2 mufas) + 120 (tendido);
  - deshacer y rehacer, nota con negrita anclada al poste, borrar una mufa con cable (confirmación) y Ctrl+S;
  - sin errores de JavaScript.
- **Ajuste visual:** la franja del editor tapaba los controles del mapa en pantallas angostas. Ahora pasa a dos filas y los controles se bajan.

**Decisiones de Claude:**
- **Enter sobre una mufa del proyecto** muestra un aviso: el editor de mufa es la fase 4.
- **Borrar un elemento con cables:** se borran los cables que terminan en él; los que solo pasan quedan despegados en ese punto.
- **FLAT** se dibuja con guiones y ADSS continuo; el grosor depende de la clase.
- **Al mover un poste,** el servidor recalcula el recorrido y el metraje de los cables pegados y les sube la versión.

**Pendiente de verificar por Jan:** el editor en la ventana real con datos reales (crear un tramo con 2 mufas, postes y un cliente, y guardarlo).

**Jan aprobó la fase 3 ("Ok").**

## Fase 4 (editor de mufa): terminada, espera el OK de Jan

**Estado:**
- **Pruebas:** **287** pasan (+7 en `Pruebas/test_redes_mufa.py`).
- **Migración** `005_mufa.sql` **aplicada en `Presupuesto_visio`** (12:06).
- **`VisorRutas.zip`:** regenerado y verificado (24.7 MB, incluye `editor_mufa.js` y Konva).
- **README:** sección "Editor de mufa".

**Qué se hizo:**
- **Base:** `005_mufa.sql` con estas tablas:
  - `hilos`, que se llena también para los cables que ya existían;
  - `mufa_cables`, con la posición de cada cable en el lienzo;
  - `splitters`, `conectores` y `puertos`;
  - `conexiones`, con un extremo A y uno B; cada extremo es un hilo o un puerto, uno por hilo o puerto en la mufa.
- **Backend:**
  - `visor_rutas/redes/mufa.py`:
    - `leer` devuelve los cables que llegan y salen, con sus hilos, el otro extremo y qué tiene cada hilo en la mufa lejana;
    - `guardar` hace todo en una transacción, con ids temporales, versión e historial.
  - **Ganchos en `red.py`:**
    - cambiar la cantidad de hilos de un cable sincroniza sus hilos;
    - borrar un cable o una mufa quita las conexiones que dependen de ellos;
    - Duplicar copia también lo de las mufas.
- **Página:** `web/redes/editor_mufa.js` sobre Konva.
  - Cables de entrada a la izquierda y de salida a la derecha, con colores TIA-598.
  - Se conecta arrastrando de hilo a hilo o puerto. Hay splitters 1x2 a 1x32 y desbalanceados, conectores, y estado por hilo (clic derecho).
  - Notas Quill, alinear y distribuir, deshacer/rehacer, zoom, Aplicar y Guardar/Cerrar.
  - La caja «→ destino» y las migas de pan sirven para navegar entre mufas.
  - En el editor de mapa, Enter o doble clic sobre una mufa del proyecto abre su editor. La mufa debe estar guardada y el mapa sin cambios pendientes.
- **Revisado en Edge headless** (caso de aceptación: hilo troncal a splitter 1x8, una salida hacia otra mufa, y navegar):
  - se creó un splitter 1x8 y se conectó hilo 1 de la troncal → entrada del splitter, salida 1 → hilo 1 del drop a FAT 1, más una fusión troncal → troncal sur;
  - **arrastre real con el mouse**: hilo 3 → salida 2 del splitter. Arrastrar a un puerto ocupado se rechaza;
  - estados oscura y dañado, deshacer/rehacer y Supr;
  - Aplicar envió 1 splitter, 4 conexiones y 2 hilos;
  - navegó a FAT 1 con Enter y volvió por las migas;
  - nota, y sin errores de JavaScript;
  - el arnés de la fase 3 sigue pasando.

**Decisiones de Claude:**
- Al crear un splitter o conector, va a la columna central, debajo de los que ya hay.
- Las líneas que unen puertos del mismo lado rodean por fuera.
- Cada línea dobla en un carril distinto para que no se encimen.
- Desde el mapa, el editor de mufa solo se abre con la red guardada, para no mezclar dos guardados.
- Se puede navegar también a un **nodo**: el backend lo acepta igual que una mufa.

**Detalle técnico:**
- Konva vacía su contenedor, así que el lienzo va en su propio `#mu-konva`.
- `dibujar()` pinta de forma síncrona; si no, el primer clic tras un cambio podía no detectar el hilo.

**Pendiente de verificar por Jan** (en la ventana real):
- abrir una mufa del proyecto;
- conectar hilos arrastrando con el mouse;
- un splitter;
- navegar a la mufa vecina.

**Jan pidió avanzar con la fase 5 ("Avanza con la fase 5"), lo que aprueba la fase 4.**

**Corrección:** en el resumen de la fase 4, Claude dijo que había cambiado una clave "fase-4" en `ESPECIFICACION.md`. Eso no se hizo y no hacía falta; la especificación no se tocó. También se corrigió el README: reducir los hilos de un cable con hilos conectados **se rechaza**, no quita las conexiones.

## Fase 5 (trazado de hilo): terminada, espera el OK de Jan

**Estado:**
- **Pruebas:** **292** pasan (+5 en `Pruebas/test_redes_trazado.py`).
- **Sin migración nueva:** el trazado solo lee.
- **`VisorRutas.zip`:** regenerado y verificado (24.7 MB).
- **README:** sección "Trazado de hilo".

**Qué se hizo:**
- **Backend** `visor_rutas/redes/trazado.py`: método `trazar_hilo` en `api.py`.
  - Sigue un hilo, indicado por su id o por cable y número, en los dos sentidos: fusiones, splitters (abre una rama por salida conectada; desde una salida sube por la entrada), conectores, hasta cliente, nodo o "sin continuidad".
  - Devuelve los caminos paso a paso con su distancia, los avisos de hilos no activos, un resumen de clientes, y los ids de cables, hilos, conexiones y elementos para resaltarlos.
- **Página:**
  - `web/redes/trazado.js`: panel de trazado; clic en una mufa del recorrido la abre; botón "Ver en el mapa".
  - Editor de mufa: el botón *Trazar hilo*, la tecla T y el menú contextual. Brillo amarillo en el recorrido y el resto atenuado. Si hay cambios sin aplicar, ofrece "Aplicar y trazar".
  - Mapa: en el inspector de un cable, número de hilo y *Trazar hilo*. Resaltado amarillo de cables y elementos, con la etiqueta del cliente.
- **Revisado en Edge headless:**
  - desde el editor de mufa: pide aplicar, aplica y traza;
  - el panel muestra "Llega al cliente Casa Pérez", un camino sin continuidad con el aviso "dañado", y el camino al nodo;
  - 3 de 3 líneas resaltadas en la mufa;
  - "Ver en el mapa" cierra la mufa y resalta 7 capas;
  - el inspector del mapa pide el hilo 3 del cable 32 y rechaza el 99;
  - cerrar el panel quita el resaltado;
  - sin errores de JavaScript. Los arneses de las fases 3 y 4 siguen pasando.
- **Pruebas:** el caso de aceptación (desde el hilo 2 de la troncal se llega a Casa Pérez pasando por splitter 1x8, distribución, conector y acometida); del cliente al nodo; fusión; hilo libre; splitter sin salidas; hilo inexistente; usuario sin acceso.
- **Errores encontrados y corregidos durante la fase:**
  - un hilo al que se llega desde un puerto se marcaba como "fusión";
  - el nombre salía "Conector Conector A";
  - faltaba registrar la conexión puerto → hilo para el resaltado.

**Decisiones de Claude:**
- El trazado usa solo lo **guardado**. Desde la mufa ofrece aplicar antes; en el mapa solo avisa.
- La distancia de cada camino es la suma de las longitudes de los cables desde el extremo del cable trazado. No incluye las reservas del metraje.
- Hasta 400 caminos por trazado, y corte con aviso si el recorrido vuelve sobre sí mismo.
- El panel queda abierto al navegar entre mufas y al pasar al mapa. La ✕ lo cierra y quita el resaltado.

**Pendiente de verificar por Jan** (en la ventana real):
- trazar desde un hilo de la troncal y ver el cliente;
- "Ver en el mapa".

Las capturas headless de esta secuencia larga salieron a medio pintar, pero las comprobaciones del DOM pasan.

Con las reglas de metraje decididas (D3, los mismos valores del presupuesto). Ver `../2026-10-08/03_siguiente.md`.
