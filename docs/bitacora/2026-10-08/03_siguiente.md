# Lo que se va a hacer (en orden)

Se trabaja **por fases**. Al terminar cada una, Claude se detiene, muestra qué hizo y cómo probarlo, y espera el OK de Jan. La especificación completa está en `docs/modulo_redes/ESPECIFICACION.md`.

## Fase 2: Proyectos (lo próximo, cuando Jan apruebe la fase 1)

**Arranque:** historial de presupuestos del visor en "Presupuestos" (punto D2, si Jan lo aprueba).

**Lista de proyectos** (imagen `docs/modulo_redes/img/02_lista_proyectos.png`):
- Buscador "Filtrar proyectos".
- Una tarjeta por proyecto, con imagen, nombre y las acciones Información, Historial, Editar, Duplicar y Eliminar. Eliminar pide confirmación y es borrado lógico.
- Botón fijo "+ Crear proyecto".
- Por ahora, un clic en la tarjeta solo deja el proyecto seleccionado; el editor de mapa llega en la fase 3.

**Modal "Datos del proyecto"** (imagen `03_datos_proyecto.png`):
- Imagen (`bytea`, hasta 2 MB) con *Seleccionar archivo* y *Eliminar la imagen*.
- Nombre e identificador, ambos obligatorios; el identificador es único entre los no borrados.
- Usuarios con acceso (`proyecto_usuarios`) y proyecto padre, con la jerarquía (validar que no se formen ciclos).
- Buscar por dirección con Google Geocoding usando la clave existente; sin internet, pegar coordenadas. Antes hay que **comprobar que la clave tenga habilitada la Geocoding API**.
- Minimapa con capas Mapa/Satélite y marcador arrastrable para la ubicación.
- *Diseñar área* para dibujar el polígono del área.

**Permisos:** el administrador ve todos los proyectos; editor y lector ven solo los asignados, y solo el editor puede escribir.

**Datos:** cada cambio queda en `redes.historial` con versión (bloqueo optimista). Los proyectos borrados se pueden restaurar.

**Librería nueva:** Leaflet-Geoman free (MIT), copiada en `web/lib/geoman/` sin CDN. La copia necesita internet una sola vez, al desarrollar.

**Pruebas:** CRUD, duplicar, borrar y restaurar, código único, ciclos en la jerarquía, permisos por proyecto, conflicto de versión, imagen demasiado grande y el endpoint remoto.

**Al terminar:** actualizar el README y volver a generar `VisorRutas.zip`.

**Migración:** probablemente `002_proyectos.sql`, si hacen falta columnas o índices nuevos. La tabla `proyectos` ya existe desde la `001`.

## Fases siguientes (resumen de la especificación)

| Fase | Alcance | Listo cuando |
|---|---|---|
| 3 | Editor de mapa dentro de un proyecto: paleta (poste, mufa, cliente, cable ADSS/FLAT con color, hilos 12–144, hilos por buffer 8/12), arrastrar y soltar, snap a postes y mufas, nombres obligatorios, metraje con detalle (ver D3), notas con formato (Quill), deshacer/rehacer, guardado explícito. Enter o doble clic en una mufa existente (KMZ/Visio) abre su diagrama Visio con el visor actual. | Se diseña un tramo con 2 mufas, postes y un cliente, y queda guardado. |
| 4 | Editor de mufa (Konva): cables como barras por buffer con hilos en colores TIA-598, conexiones arrastrando (fusión o splitter), splitters 1x2…1x32 (balanceados o 70/30), conectores, estado de cada hilo (activo, oscura, baja, reservado, dañado), notas, Aplicar / Guardar, navegación con Enter y migas de pan. | Se conecta un hilo troncal a un splitter 1x8 y una salida a otra mufa, y se navega. |
| 5 | Trazar un hilo de punta a punta, en un panel y en el mapa. | Desde un hilo del troncal se ve a qué cliente llega. |
| 6 | Diagrama lógico automático (izquierda → derecha), con leyenda FTTH y exportación a PNG y PDF (Pillow). | Se genera desde una mufa y se exporta a PDF. |
| 7 | Problemas, Pendientes y Backup: `pg_dump` en `C:\Program Files\PostgreSQL\18\bin\pg_dump.exe` (o JSON), restaurar como copia nueva, y exportar a KMZ y GeoJSON. | Funcionan las tres opciones. |

**Modelo de datos previsto para las fases 3 y 4** (aprobado en la fase 0): `elementos`, `cables`, `cable_vertices`, `hilos`, `mufa_cables`, `splitters`, `conectores`, `puertos`, `conexiones`, `notas`, `diagramas_logicos`, `problemas`, `pendientes` y `fotos`. Las geometrías van como columnas PostGIS (4326).
