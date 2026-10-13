# Datos útiles para retomar

## Estado al cierre del día

- **Pruebas:** `.\.venv\Scripts\python.exe -m pytest Pruebas -q -p no:cacheprovider` dio **261 passed** (unos 95 s).
- **Base `Presupuesto_visio`** (local, PostgreSQL 18.6, usuario `postgres`):
  - esquema `redes` con la migración `001` aplicada, PostGIS 3.6.2 dentro de `redes` y la tabla `usuarios` vacía;
  - `red_fibra` sin cambios.
- **Caché del KMZ:** `visor_rutas/datos_kmz/`, formato versión 2.
- **`VisorRutas.zip`:** en la raíz del proyecto, generado al final del día (24.4 MB).
- **Servicio en el puerto 8000:** encendido pero **con código viejo** (ver A1 en `02_pendiente_de_confirmar.md`).

## Comandos

```powershell
# pruebas
.\.venv\Scripts\python.exe -m pytest Pruebas -q -p no:cacheprovider
# migraciones del módulo de redes (aplica las que falten y muestra el estado)
.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar
# caché del KMZ (Lugares): solo si cambió; --forzar para regenerar
.\.venv\Scripts\python.exe -m visor_rutas.kmz_capas
# ejecutable para otras PC (VisorRutas.exe + VisorRutas.zip)
.\build_visor.bat
```

## Cómo se prueba la interfaz sin abrir la ventana

- La página real (`visor_rutas/web/visor.html`) se carga en **Microsoft Edge headless** (`msedge.exe --headless=new --dump-dom` o `--screenshot`), con una API de pywebview simulada en JavaScript (un `Proxy` que responde `configuracion`, `kmz_arbol`, `redes`, etc.).
- El script de prueba escribe sus resultados en un `<pre>` y Claude revisa las capturas de pantalla.
- Los scripts de prueba viven en la carpeta temporal (scratchpad) de cada sesión, así que hay que rehacerlos.
- No hay Node instalado. La sintaxis del JS también se revisa con Edge headless.

## Reglas que no se rompen (del dueño)

- **API de n8n (`main.py`):** sin cambios en endpoints, body, respuestas ni `budget_index.json`. Todas las pruebas existentes deben pasar.
- **Entorno:** Windows sin permisos de administrador, el mismo `.venv` y nada que instale servicios.
- **Google Directions:** sigue en `driving`; no tocar `routing.py`.
- **Ejecutable:** nunca incluye `.env`, claves, bases, plantillas, KMZ, la caché ni código del servicio.
- **Red:** no se abren puertos ni se toca el firewall; el acceso remoto es solo por el túnel de ngrok.
- **Claves:** `X-Visor-Key` es una por persona en `VISOR_API_KEYS` (Jan y Marlon), distinta de `SERVICE_API_KEY`. **Nunca escribir las claves en documentos.**
- **Salidas:** lo que genera el visor va a `output/visor/`, nunca a `budget_index.json`.
- **Bases:** no modificar `red_lineas`, `red_puntos` ni el esquema `red_fibra`.
- **Interfaz:** todo en español.
- **Entregas:** archivos completos, trabajo por fases y detenerse a esperar el OK. Al final de cada fase, actualizar el README y volver a generar el zip.

## Mapa rápido del código

| Ruta | Qué es |
|---|---|
| `main.py` | API de presupuestos (n8n) + `include_router(visor_api.router)` |
| `visor_api.py` | `/visor/*` para el `.exe`: ruta, estimación, presupuesto, archivos, diagramas, red, mufas, `kmz/*`, `redes/{metodo}` |
| `visor_rutas/ventana_web.py` | `Api` de pywebview (modo local o remoto) |
| `visor_rutas/remoto.py` | `ProveedorRemoto`: los mismos métodos por HTTP |
| `visor_rutas/kmz_capas.py` | importador del KMZ para Lugares |
| `visor_rutas/redes/` | módulo de redes (backend) |
| `visor_rutas/web/` | `visor.html`, `visor.css`, `visor.js`, `menu.js`, `lugares.js`, `redes/*.js` y `lib/` (Leaflet 1.9.4, markercluster 1.5.3, polylinedecorator) |
| `business_rules.yaml` | reglas (postes, reservas, `budget_note`, `visor_estimacion`…) |
| `docs/modulo_redes/` | especificación e imágenes de referencia del módulo de redes |
