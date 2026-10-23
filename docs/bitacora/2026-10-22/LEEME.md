# Bitácora 2026-10-22

Viene de [../2026-10-13/LEEME.md](../2026-10-13/LEEME.md). Hoy se cambió de máquina (Windows de `jparamo`) y hubo que rehacer el entorno y las bases.

## Entorno y bases desde cero
- Python 3.13 instalado (`winget`, por usuario) y `.venv` recreado; `psycopg2-binary` instalado a mano (el importador lo pide para publicar; no está en `requirements.txt`).
- Dos bases en PostgreSQL 18 (con PostGIS 3.6): **`Presupuesto_fibra`** (`red_puntos` / `red_lineas`, el KMZ) y **`Presupuesto_visio`** (esquema `red_fibra` de los Visio **y** el esquema `redes` del módulo: usuarios, proyectos, campo…; `redes` no está en `Presupuesto_fibra`).
- `Presupuesto_visio.red_fibra`: importados los 433 archivos de `visioMapas\DIAGRAMAS ACTUALIZADOS` (3 571 nodos, 3 183 enlaces, 14 145 servicios; 2 `.vsdx` dañados no se pudieron convertir, ver «Pendiente»).
- `Presupuesto_fibra`: no existe script que cargue el KMZ; se escribió `herramientas/cargar_kmz.py` (30 202 puntos, 5 803 líneas; `tipo` = nombre de la carpeta del KMZ).
- `.env`: `KMZ_PATH` corregido; `REDES_RESPALDOS_DIR` = `C:\Users\jparamo\Desktop\Respaldos` y `REDES_RESPALDOS_CONSERVAR=20`.

## Los archivos viven en la base (almacén)
Tabla `redes.almacen_archivos` (migración 019) y `visor_rutas/almacen_archivos.py`: presupuestos del visor, `.odg` e imágenes de los diagramas, el KMZ y su caché pasan a PostgreSQL; las carpetas del proyecto son copia desechable que se restaura sola. Herramienta `herramientas/almacen_sincronizar.py` (`resumen`, `subir`, `verificar`). Los originales se movieron (no se borraron) a `Respaldos\movido_a_la_base_2026-10-22`. El importador de Visio ya publica directo en PostgreSQL y no deja `red_fibra.db`. Detalle en el README («Los archivos viven en la base»).

## Limpieza
Borrados `build/`, `dist/`, `__pycache__` y logs viejos; los reportes de migración antiguos están en `Respaldos\...\reportes_output`. `EjemploRutaFusiones` **no** se borró: es el libro por defecto de la exportación de la ruta de fusión (`RUTA_FUSION_XLSX`).

## App de campo
- **Clave aparte para técnicos:** `CAMPO_API_KEYS` (`nombre:clave`). Abre solo `/campo` y `/visor/campo/*`; el resto de `/visor/*` responde 401. La persona se crea sola con rol **técnico** (antes había que ir a Usuarios; al rehacer la base se perdieron los roles y por eso la app decía «no tiene el rol de técnico»). Las claves de `VISOR_API_KEYS` siguen abriendo la app para quien revisa. Pruebas: `test_campo_claves.py`.
- **Descargar esta zona** (menú ☰): mosaicos del mapa visible (Esri) + red existente de la zona, para trabajar sin señal. `campo_web/zona.js`, cache `campo-zonas` (el service worker la consulta primero y no la recorta; `campo-v8`). Hasta 2 500 mosaicos por zona y 8 000 en total; se borran una a una; OpenStreetMap excluido. Pruebas en un Edge real: `test_campo_zona.py`.
- Nota de «Sin GPS» (no es un fallo del servicio): permiso de ubicación negado, GPS apagado o página abierta desde un navegador integrado (WhatsApp) o sin HTTPS.

## Reglas de presupuesto, fase B
- **Regla 7 (splitter con puertos libres):** la ruta de fusión **se detiene** en el primer splitter secundario con puertos libres; las mufas que siguen hacia la potencia quedan en el plan como «no se toca: después del splitter» (se pueden volver a marcar), bajan las mufas intervenidas y el aviso rojo pide validar con Planta Externa los puertos y los **hilos libres entre mufas**. `ruta_fusion_plan.armar`; prueba en `test_splitters_diagrama.py`.
- **Hilos verdes (continuidad), medido** (`red_fibra/estudio_splitters/e4_hilos_verdes.py`, ESTUDIO_SPLITTERS §6): el verde del código TIA aparece en el 65 % de los diagramas pero el 99 % de esas líneas llevan flechas (son puentes de fusión del hilo 3); solo 7 diagramas tienen verdes sin flechas. **El color solo no permite leer la continuidad**: queda como aviso y habría que contar con una lista de hilos libres por cable.
- Íconos de lo que dibuja la ruta: ya resuelto el 2026-10-20 («Íconos del visor para todos»).
- **Nota de contabilidad — sigue esperando la aprobación de Jan cuando se haga el presupuesto:** `presupuesto.calcular_materiales` todavía cuenta 1 preformada por poste en un dato interno que **no se escribe en el Excel** (en la bitácora del 9 de octubre). No se tocó.

## Migración Visio (sin Kayako)
- Migración real corrida sobre la base nueva (`python -m visor_rutas.redes.migrar_visio`, respaldo previo): 13 proyectos base, 3 472 elementos (179 sin ubicar), 3 006 cables, 212 empalmes, verificación 0 errores / 66 avisos; igual a la del 13 de octubre.
- **Sin ubicar:** la cola de corrección ya existía; ahora cada mufa trae una **pista** para centrar el mapa (vecinas del Visio → mismas mufas de su diagrama → su carpeta; solo orientación, no se guarda): 54 por diagrama, 116 por carpeta, 9 sin pista; va también al Excel.
- **22 elementos lejos de Managua:** eran de Masachapa, Montelimar, Villa El Carmen y San Benito (departamento de Managua); se nombraron en la lista de Managua de `business_rules.yaml`. La simulación confirma que no cambió ningún proyecto.
- **21 empalmes sin cable:** todos nombran un «ODF xx PUERTOS» y el Visio no dibuja ese cable; ahora se cuentan aparte (`empalmes_odf`). Otros 8 renglones del Excel de anillos traen hilos ilegibles («¿?»). No se inventan cables.
- `PLAN.md` (§11) y `ESPECIFICACION.md` actualizados con las decisiones del diagnóstico. **Kayako sigue fuera por orden de Jan.**

## Reorganización de carpetas
El código del servicio (`main.py`, `config.py`, `db.py`… ) **se queda en la raíz**: todo el proyecto y las pruebas lo importan por nombre y Uvicorn arranca `main:app`. Lo demás se ordenó así (índice en `docs/INDICE.md`):

| Antes | Ahora |
|---|---|
| `red_kmz/` | `datos/kmz/` |
| `visioMapas/DIAGRAMAS ACTUALIZADOS/DIAGRAMAS ACTUALIZADOS/` | `datos/visio/DIAGRAMAS ACTUALIZADOS/` |
| `EjemploRutaFusiones/` | `datos/rutas_de_fusion/` |
| `datos_campo/` | `datos/campo/` |
| `red_fibra/cache_odg/`, `red_fibra/cache_diagramas/` | `datos/cache/odg/`, `datos/cache/diagramas/` |
| `visor_rutas/datos_kmz/`, `visor_rutas/datos_kmz_iconos_google/` | `datos/cache/kmz/`, `datos/cache/iconos_google/` |
| `build_visor.bat`, `empaquetar_visor.py`, `instalador_visor.iss` | `herramientas/` (mismos nombres) |
| `iniciar_tunel_cloudflare.bat`, `cloudflared/` | `herramientas/iniciar_tunel_cloudflare.bat`, `herramientas/cloudflared/` |
| `verificar_campo.py` | `herramientas/verificar_campo.py` |

`datos/` entera está en `.gitignore` (salvo `datos/LEEME.md`). Se cambiaron los valores por defecto de `KMZ_PATH`, `RUTA_FUSION_XLSX`, `CAMPO_FOTOS_DIR` y de las cachés; **el `.env` de esta PC ya apunta a `datos\kmz`**. En otra PC con `.env` propio hay que cambiar `KMZ_PATH` si estaba puesto. Reiniciar `start_service.bat` y reabrir el visor.
**Corrección:** en el resumen anterior se dijo que el enlace de `docs/bitacora/2026-10-08/` a sus archivos `01_` a `04_` estaba roto; no lo está (existen). Sí falta anotar lo que dicen esos archivos como pendiente: ver `02_pendiente_de_confirmar.md` y `03_siguiente.md` de ese día.

## Pendiente
- Reiniciar `start_service.bat`, regenerar `VisorRutas.zip` para Marlon (la página y la app de campo cambiaron) y asignar `CAMPO_API_KEYS` a los técnicos.
- Arreglar en Visio los 2 `.vsdx` dañados (`2 Mufa IDEAY la colonia de rubenia - Sabana Grande 1.vsdx` y `3 - 1 Mufa de Union Fenosa IDEAY la Colonia Gran Via.vsdx`) y reimportar.
- Colocar las 179 mufas sin ubicar (vista **Red existente**); decidir si se crean los cables mufa–ODF que faltan.
- Probar la app de campo y «Descargar esta zona» en un Android y un iPhone reales.
- Aprobación de la nota de contabilidad (preformadas) cuando se haga el presupuesto.
- Mucho trabajo sin commit (app de campo, almacén, claves, zona, regla 7, migración).
