# Base de datos de la red de fibra (IDEAY)

`red_fibra.db` es una base SQLite generada a partir de la carpeta **DIAGRAMAS ACTUALIZADOS**:
433 diagramas Visio (388 `.vsd` y 45 `.vsdx`) y el Excel `ACTUALIZACION ENLACES.xlsx`.

## Contenido

| Archivo | Para qué sirve |
| --- | --- |
| `red_fibra.db` | La base ya cargada. Se abre con DB Browser for SQLite, DBeaver o desde Python. |
| `schema.sql` | Definición de tablas y vistas. |
| `importador.py` | Vuelve a construir la base leyendo la carpeta de diagramas. |
| `consultas.py` | Nodos más cercanos a una coordenada, resumen y exportación a GeoJSON. |

## Tablas

| Tabla | Qué guarda |
| --- | --- |
| `nodos` | Mufas, nodos, mini nodos, ODF y reservas, con su coordenada, tipo, propietario (IDEAY, UFINET…) y notas (SANGRIA, VALIDAR…). |
| `nodo_apariciones` | En qué archivo aparece cada nodo y con qué nombre y coordenada exactos. |
| `enlaces` | Cables entre nodos, con capacidad (12H, 24H…) y longitud cuando el diagrama la indica. |
| `servicios` | Clientes (código C#####, ID de servicio) y splitters, asociados a la mufa donde están fusionados. |
| `anillo_tramos` | Recorrido de los anillos del Excel: mufa por mufa, con hilo de entrada y de salida. |
| `textos_crudos` | Todo el texto extraído de cada diagrama, con su posición, para reprocesar sin volver a convertir. |
| `archivos` / `importaciones` | Inventario de archivos leídos, errores y estadísticas de cada carga. |

Vistas: `v_nodos_ubicados`, `v_enlaces_detalle`, `v_revision` (nodos que conviene revisar a mano).

## Cómo leer la columna `fuente_coord` de `nodos`

- `visio` o `excel`: la coordenada está escrita en el diagrama o en el Excel.
- `estimada_vecinos`: el diagrama no trae la coordenada de esa mufa; se estimó con el promedio de las mufas conectadas a ella. Sirve para ubicarla, pero conviene confirmarla.
- vacío: no hay forma de ubicarla con los datos actuales.

## Confiabilidad de los enlaces

- `excel` (confianza alta): tomados del recorrido de anillos del Excel.
- `visio_mufa` (media): en el diagrama de una mufa, sus vecinas aparecen dibujadas. Si la longitud escrita no coincide con la distancia real, se deja la longitud vacía.
- `visio_red` (media): en los diagramas de red, la conexión se deduce de dónde está la etiqueta del cable. Solo se guardan las conexiones cuya longitud coincide con la distancia real entre las mufas; las demás se descartan.
- `visio_linea` (media): en los diagramas de red y subred, cada línea de cable dibujada (trazo sólido gris/negro) une las mufas cuyo ícono de moño toca, aunque la línea no esté pegada a ellas en Visio. Las líneas punteadas de color (hilos) no cuentan. Cada mufa se identifica con la etiqueta de coordenadas más cercana a su ícono; un ícono sin etiqueta se atraviesa pero no se cuenta. En estos diagramas los textos de servicio (SPL ... OLT ...) se asignan a la mufa cuyo ícono está más cerca.

## Volver a cargar la base (en Windows, sin permisos de administrador)

1. Instala las librerías en tu usuario:
   `python -m pip install --user lxml openpyxl`
2. Descarga **LibreOffice Portable** (no necesita instalación) y descomprímelo, por ejemplo en `C:\Users\jgutierrez\LibreOfficePortable`.
3. Ejecuta:

```
python importador.py --origen "C:\Users\jgutierrez\Downloads\DIAGRAMAS ACTUALIZADOS" --db red_fibra.db --soffice "C:\Users\jgutierrez\LibreOfficePortable\App\libreoffice\program\soffice.exe"
```

La primera vez convierte todos los Visio (unos 10 minutos). Las conversiones quedan en la carpeta `cache_odg`, así que en las siguientes cargas solo se convierten los archivos nuevos o modificados. La base se reconstruye completa en cada ejecución, de modo que siempre refleja el estado actual de la carpeta.

## Consultas útiles

```
python consultas.py cercanos 12.052271 -86.175817 --n 5
python consultas.py resumen
python consultas.py exportar red.geojson      # se puede abrir en geojson.io, QGIS o Google Earth
```

Desde la API de presupuestos:

```python
from consultas import nodos_cercanos
origen = nodos_cercanos('red_fibra.db', lat, lon, n=3, radio_m=2000)
```

## PostgreSQL

La misma base se puede tener en PostgreSQL, para que la API y n8n la consulten desde el servidor sin depender del archivo `red_fibra.db` ni de la PC donde están los Visio.

1. Instala el driver: `python -m pip install --user psycopg2-binary`
2. Crea la base en pgAdmin (por ejemplo `ideay`). El esquema `red_fibra` y sus tablas se crean solos en la primera publicación (`schema_postgres.sql`).
3. Publica la carga actual:

```
python publicar_postgres.py --sqlite red_fibra.db --pg "postgresql://usuario:clave@servidor:5432/ideay"
```

O, en un solo paso, al importar los Visio:

```
python importador.py --origen "C:\...\DIAGRAMAS ACTUALIZADOS" --db red_fibra.db --pg "postgresql://usuario:clave@servidor:5432/ideay"
```

La publicación reemplaza los datos en una sola transacción (si falla, PostgreSQL queda como estaba) y conserva el historial en `red_fibra.importaciones`.

Consultas en pgAdmin:

```sql
SELECT * FROM red_fibra.nodos_cercanos(12.153328, -86.263438, 2000, 5);   -- lat, lon, radio_m, n
SELECT * FROM red_fibra.v_ultima_importacion;
SELECT * FROM red_fibra.v_revision;
```

Desde Python, `consultas.nodos_cercanos()` acepta una cadena `postgresql://...` en lugar de la ruta del archivo. También se puede definir la variable de entorno `RED_FIBRA_PG` y omitir `--db` / `--pg`.

## Piloto: extracción automática de fusiones

`fusiones.py` intenta leer de cada diagrama las fusiones dibujadas, y `piloto_fusiones.py` mide qué tan bien lo hace sobre las mufas que elijas. El importador **todavía no** lo usa.

**Cómo están dibujadas las fusiones.** En los `.odg` no hay conectores. Cada fusión es una línea suelta, casi siempre un "puente" en ángulo recto con flechas, que va del número de un hilo de un cable al número de un hilo de otro cable, o a un splitter o cliente. Los números de hilo están en **un** cuadro de texto por cable ("1 2 3 … 24" o "6 / 5 / 4"). El color del trazo es el color del hilo en el código TIA-598 (1 azul, 2 naranja, 3 verde, 4 café, 5 gris, 6 blanco, 7 rojo, 8 negro, 9 amarillo, 10 violeta, 11 rosa, 12 aqua) **dentro de su buffer**. Los buffers pueden ser de 12, 6, 2… hilos, y se toma lo que diga la etiqueta del cable ("4BUFFER DE 6H"); si no dice nada, se asume 12.

**Qué hace `fusiones.py`:**

- Lee las líneas (`draw:line`, `draw:polyline`, `draw:path`, aplicando `draw:transform`) con su color real, resuelto desde los estilos.
- Une las piezas del mismo color cuyas puntas se tocan.
- Estima la posición de cada número de hilo dentro de su cuadro.
- Empareja cada punta con el número más cercano, o con un texto de splitter o cliente.
- Calcula una **confianza de 0 a 1** con el motivo. Sube si las puntas están cerca de los números, si el color TIA coincide con el número de hilo según el tamaño del buffer, si la línea tiene flechas y si une cables distintos.
- Guarda el resultado en la tabla `fusiones_piloto`. Las tolerancias están en `TOLERANCIAS`.

**Uso:**

1. Escribe una lista con las mufas, una por línea: nombre exacto de la mufa, md5 del diagrama o parte de la ruta del archivo. Las líneas con `#` se ignoran.
2. Genera los reportes:

   ```
   ..\.venv\Scripts\python.exe piloto_fusiones.py --mufas lista.txt
   ```

   Se crean `piloto/index.html` y un reporte por mufa. Cada reporte muestra el diagrama con las fusiones detectadas encima (verde ≥ 0.7, naranja 0.4–0.7, rojo < 0.4) y una tabla con *Correcto / Incorrecto* para cada una. La imagen del diagrama es un SVG vectorial, que se lee bien con cualquier zoom. Necesita LibreOffice para la imagen; usa la misma caché que el visor (`cache_diagramas/`).
3. Abre cada reporte con doble clic (Edge o Chrome). Marca cada fusión, anota cuántas **fusiones reales** tiene el diagrama y pulsa *Descargar marcas (CSV)*. Mueve los `marcas_<archivo_id>.csv` a `piloto/marcas/`. Las marcas se recuerdan en ese navegador aunque vuelvas a generar el reporte.
4. Calcula las métricas:

   ```
   ..\.venv\Scripts\python.exe piloto_fusiones.py --metricas piloto\marcas
   ```

   - **Precisión** = correctas / marcadas.
   - **Cobertura** = correctas / reales (también se muestra detectadas / reales).

   Se calculan por mufa, en total y por umbral de confianza, para elegir desde qué confianza conviene mostrarlas.

`fusiones_piloto` está en `schema.sql`, `schema_postgres.sql` y `publicar_postgres.py`. Ojo: como el importador reconstruye `red_fibra.db` completa, la tabla queda **vacía** después de cada importación. Hay que volver a correr el piloto.
