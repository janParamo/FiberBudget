# Lo que se hizo hoy (8 de octubre de 2026)

Al cierre pasan las **261 pruebas**. `POST /presupuesto` y n8n no cambiaron en endpoints, body ni respuestas; varias pruebas lo verifican.

---

## 1. Uso del visor en otra PC (Marlon)

Solo una explicación, sin cambios de código:
- Marlon descomprime `VisorRutas.zip` y abre `VisorRutas.exe`. No usa `Visor de rutas.bat`, que es solo para la PC de Jan.
- La primera vez se abre "Configuración del visor": ahí escribe la URL de ngrok y su clave `X-Visor-Key`, presiona **Probar conexión** y luego **Guardar**.
- La configuración queda en `%APPDATA%\VisorRutas\config.json`, con la clave cifrada (DPAPI).
- Borrar la carpeta vieja del visor no hace perder la configuración. Para empezar de cero también hay que borrar `%APPDATA%\VisorRutas`.

## 2. Postes nuevos que ya existen (clic en el mapa)

- En el visor, un clic en un poste nuevo (gris) lo marca como existente: queda blanco con borde verde y pasa a la capa *Postes existentes*. Otro clic lo devuelve a nuevo, y *Desmarcar todos* los restablece.
- **Efecto en el presupuesto, por cada poste marcado:**
  - "Instalación de poste metálico 8 mt." −1;
  - material "POSTE 8 MTRS" −1;
  - "Instalación de herraje en poste existente" +1.

  El herraje no cambia, porque el total de postes es el mismo.
- El presupuesto aproximado se recalcula solo, unos 900 ms después del último clic.
- **Generar presupuesto** aplica las marcas solo si la coordenada del formulario es la misma de la ruta del mapa.
- Las marcas viajan como **metros de la ruta**. El servidor solo acepta las que coinciden con un poste nuevo de esa ruta (tolerancia de 0.5 m); las demás se cobran como nuevas y salen en un aviso.
- **Decisión:** cada marca resta exactamente 1. No se recalculan los huecos entre postes.
- **Archivos:**
  - `presupuesto.py`: `new_pole_positions_by_gaps` y `match_marked_poles`.
  - `main.py`: parámetro opcional `new_poles_marked_existing_m` en `_generar_presupuesto_con`. El valor por defecto deja la API igual.
  - `visor_rutas/calculo.py`: `postes_nuevos.metros`.
  - `presupuesto_visor.py`, `ventana_web.py`, `remoto.py` y `visor_api.py`: el campo `postes_existentes_m`.
  - `web/visor.js`.
- **Pruebas:** `Pruebas/test_postes_marcados.py` y una prueba remota al final de `test_visor_api.py`.

## 3. Nota en cada página del presupuesto

- **Texto:** "Sujeto a disponibilidad de postes de concreto sobre la ruta".
- **Dónde:** sale en todos los Excel y PDF, tanto de n8n como del visor. Va en la celda D70 de *Ruta proyectada* y E91 de *Presupuesto*, con la plantilla actual: dos filas debajo de las firmas, en la columna ancha alineada a la izquierda.
- **Configuración:** bloque `budget_note` en `business_rules.yaml` (texto, columna por hoja y filas debajo). Nunca escribe encima de una celda ocupada. La última fila cuenta también los rangos combinados.
- **Archivos:** `excel_generator.py` (`_note_cell`, `_note_assignments`) y `business_rules.yaml`.
- **Pruebas:** `Pruebas/test_nota_presupuesto.py`. Además se verificó en un PDF real hecho con LibreOffice.

## 4. Panel "Lugares": la red del KMZ como en Google Earth

- Reemplaza las 4 casillas "Red KMZ ·" del visor. Las capas de Visio no cambiaron.
- **Importador** `visor_rutas/kmz_capas.py`:
  - **Entrada:** `KMZ_PATH` del `.env`. Hoy apunta a la carpeta `red_kmz`, y de ahí se usa el `.kmz` más reciente.
  - **Caché:** se genera en `visor_rutas/datos_kmz/` (`arbol.json`, `capas/<id>.geojson`, `indice.json`, `iconos/`, `fotos/`) y se regenera solo si cambia el md5 del KMZ.
  - **Resultado con el KMZ real:** 35 526 elementos, 397 carpetas, 19 íconos descargados de Google y 18 fotos, en unos 13 s.
- **Panel** `web/lugares.js`:
  - árbol con casillas de 3 estados, lista virtual de elementos, buscador (también en descripciones), y clic derecho con *Mostrar solo esta*, *Encuadrar*, *Opacidad* y *Etiquetas*;
  - el estado se guarda en `%APPDATA%\VisorRutas\capas.json`;
  - postes y pozos aparecen desde zoom 15, en canvas y agrupados;
  - el popup lleva descripción limpia (sin `com.exlyo`), fotos y botón Copiar.
- **Troncales:**
  - al inicio se encienden TRUNK GPON, TRUNK METRO, PRINCIPALES y TRONCAL*; ENLACE REDUNDANTE arranca apagado (decisión de Jan);
  - "Colores distintivos" se aplica donde el color se repite dentro de la misma carpeta;
  - cada familia tiene su estilo: GPON gruesa, METRO con borde doble, UFINET punteada, redundante con guiones;
  - al pasar el mouse se resalta con halo; hay leyenda "Troncales" y la longitud en km.
- **Modo remoto:**
  - endpoints: `GET /visor/kmz/arbol`, `/visor/kmz/capa/{id}`, `/visor/kmz/indice` y `/visor/kmz/archivo/{iconos|fotos}/{nombre}`;
  - van con gzip y no cuentan para el límite por hora (decisión de Jan);
  - el `.exe` guarda la caché en `%APPDATA%\VisorRutas\kmz_cache\<md5>`.
- **Pruebas:** `Pruebas/test_kmz_capas.py` (11) y una revisión visual en Edge headless con la caché real.
- `lxml==6.1.3` quedó agregado a `requirements.txt`.

## 5. Módulo de Proyectos y Diagramación de Redes: fases 0 y 1

**Fase 0 (plan):** se leyó la especificación y sus 10 imágenes y se propuso el modelo de datos, las librerías (Leaflet-Geoman, Konva, Quill) y la estructura. Jan decidió:
1. Activar PostGIS.
2. Para el metraje, usar las reglas que ya existen en `business_rules.yaml`.
3. Usar una base de prueba temporal, siempre que lo borrado se pueda recuperar. En el módulo todo borrado es lógico.
4. Las imágenes son solo referencia; se pueden hacer mejores visuales.

Claude decidió guardar la imagen del proyecto en la base (`bytea`).

**Fase 1 (hecha):**
- **Menú lateral fijo** (`web/menu.js`): reemplaza el antiguo ☰.
  - Opciones: Mapa, Presupuestos, Proyectos, Problemas, Pendientes, Usuarios, Backup y Configuración, con íconos SVG dentro de la página.
  - Se contrae a solo íconos y el estado se guarda en `%APPDATA%\VisorRutas\preferencias.json`.
  - Las fases no hechas salen como "Pronto / Próximamente". Abajo se ve el usuario identificado.
- **Esquema `redes` en `Presupuesto_visio`:**
  - PostGIS 3.6.2 instalado **dentro del esquema `redes`** (no en `public`).
  - Tablas: `migraciones`, `usuarios`, `proyectos`, `proyecto_usuarios` e `historial`, con `version` por registro (bloqueo optimista) y `borrado_en` (borrado lógico).
  - La migración `001_base.sql` **ya está aplicada en la base real**. `red_fibra` quedó intacto (12 tablas, 3 602 nodos).
- **Backend** `visor_rutas/redes/`: `db.py`, `migrar.py`, `repositorio.py`, `usuarios.py` y `api.py` (`ServicioRedes.llamar`).
  - En modo local: `ventana_web.Api.redes(metodo, args)`.
  - En modo remoto: `POST /visor/redes/{metodo}` con `X-Visor-Key`, sin límite por hora.
- **Usuarios:**
  - **Identificación automática:** en modo local por el usuario de Windows, que queda como administrador si no hay ningún administrador activo; en remoto por la persona de la clave, que entra como lector y nunca se vuelve administradora por sí sola.
  - **Administración:** el administrador crea y edita usuarios, ve el historial y los desactiva o reactiva. Siempre queda al menos un administrador.
  - **Vista:** `web/redes/usuarios.js`, apoyada en `web/redes/comun.js` y `redes.css`.
- **Pruebas:** `Pruebas/redes_base.py` crea y borra una base temporal `redes_pruebas_*` (nunca toca `Presupuesto_visio`), y `Pruebas/test_redes_base.py` tiene 10 pruebas.
- **Otros cambios:** `empaquetar_visor.py` (el `.exe` lleva solo las páginas del módulo, no su backend) y el README, con las secciones del menú y del módulo.

## 6. Ejecutable para Marlon

`VisorRutas.zip` se volvió a generar después de cada cambio del visor. El último quedó al final del día, con el menú nuevo, Lugares y la vista Usuarios, y está verificado: no lleva `.env`, bases, KMZ, caché ni código del servicio.
