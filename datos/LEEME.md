# datos/

Todo lo que **no es código** y no se sube a Git (datos de la empresa y archivos derivados). La carpeta entera está en `.gitignore`, salvo este archivo.

| Carpeta | Qué es | ¿Se puede borrar? |
|---|---|---|
| `kmz/` | El KMZ de la red (`RED DE IDEAY.kmz`; `KMZ_PATH` del `.env` apunta aquí). La base guarda una copia (almacén, espacio `kmz`). | Sí, vuelve a escribirse desde la base. |
| `visio/` | Los diagramas Visio originales (`.vsd` / `.vsdx` y el Excel de anillos; `visio/DIAGRAMAS ACTUALIZADOS`, o `VISIO_ORIGEN`). Se reimportan con `red_fibra/importador.py` o desde el programa (**Red existente → Actualizar diagramas Visio**, que reemplaza el archivo del mismo nombre y guarda el anterior en `visio/anteriores/`). | No, son la fuente. |
| `rutas_de_fusion/` | El libro de rutas de fusión donde el visor agrega una franja (`RUTA_FUSION_XLSX`). | No, es de trabajo. |
| `campo/` | Fotos de la app de campo (`campo/fotos/`; `CAMPO_FOTOS_DIR` lo cambia). | No: la base guarda solo la miniatura. |
| `cache/odg/` | Diagramas Visio ya convertidos a `.odg`, por md5. | Sí (están en la base). |
| `cache/diagramas/` | Imágenes SVG / PNG de esos diagramas. | Sí (están en la base). |
| `cache/kmz/` | Capas, íconos y fotos que salen del KMZ (panel Lugares). | Sí (están en la base). |
| `cache/iconos_google/` | Íconos de Google ya descargados. | Sí, se descargan de nuevo. |

Las carpetas `cache/*` se llenan solas: la fuente de verdad es la base (`redes.almacen_archivos`, ver `herramientas/almacen_sincronizar.py`).
