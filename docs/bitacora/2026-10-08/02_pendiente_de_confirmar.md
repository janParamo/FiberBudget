# Pendiente de confirmar (o de hacer) por Jan

> **Actualización 9 oct:** Jan respondió:
> - **D1:** fase 1 aprobada.
> - **D2:** sí al historial de presupuestos.
> - **D4:** PostGIS se queda en el esquema `redes`.
> - **D5 y D6:** aprobados.
> - **GitHub y archivos borrados:** no se hacen.
> - **D3:** sigue abierto. Jan definirá las reglas de metraje; la lista de reglas está en `../2026-10-09/`.

## Acciones de Jan (no de Claude)

| # | Qué | Por qué |
|---|---|---|
| A1 | **Reiniciar `start_service.bat`** | El servicio en el puerto 8000 corre con el código de antes. Sin reiniciar no funcionan, para n8n ni para Marlon: la nota de postes de concreto, las marcas de postes del modo remoto, `/visor/kmz/*` (Lugares en el `.exe`) ni `/visor/redes/*` (Usuarios en el `.exe`). Claude no lo reinicia porque es el servicio que usa n8n. |
| A2 | **Pasarle a Marlon el `VisorRutas.zip` nuevo** | Reemplaza su carpeta del visor. No pierde la URL ni la clave, que están en `%APPDATA%`. |
| A3 | **Abrir el visor en esta PC al menos una vez** | Así Jan queda registrado como administrador (`jgutierrez`). Hoy la tabla `redes.usuarios` está vacía. Después, en Usuarios, darle a Marlon el rol que corresponda: entrará como lector. |

## Decisiones que esperan respuesta

| # | Pregunta | Propuesta de Claude |
|---|---|---|
| D1 | **¿Se aprueba la fase 1?** Menú lateral, usuarios y migraciones. | Claude espera el OK antes de empezar la fase 2. |
| D2 | **Historial de presupuestos en "Presupuestos".** La especificación pide que la opción muestre también el historial de `output/visor/`. Hoy abre solo "Generar presupuesto". | Agregarlo al inicio de la fase 2: lista con fecha, cliente, coordenada y total, y botones Abrir / Guardar como / PDF. |
| D3 | **Mapeo de las reglas de metraje** (Jan: "utiliza las reglas que nosotros tenemos"). El detalle de la imagen 06 (contingencia, salida de nodo, reservas por mufa, tendido y cruce) no existe tal cual en `business_rules.yaml`. Hay `route.safety_margin: 0.0`, `slack_per_endpoint_m: 0`, `reserve_interval_m: 300`, `reserve_percent: 0.20` y `connection_reserve_m: 35`. | Para la fase 3, usar `calcular_metraje_final` de `presupuesto.py` y mostrar su desglose: distancia lineal, contingencia (`safety_margin`), reserva periódica (cada 300 m × 20 %), reserva de conexión (35 m) y holgura por extremo. Las reservas "por mufa", "por tendido" y "por cruce" no existen, así que no se inventan. Hay que confirmarlo antes de la fase 3. |
| D4 | **PostGIS quedó en el esquema `redes`**, no en `public`, porque la migración corre con `search_path=redes,public`. | Dejarlo así: todo el módulo queda en un solo esquema y `public` no se toca. Solo confirmar que está bien. |
| D5 | **Panel Lugares en la ventana real.** Se probó en Edge headless con la caché real, pero no en la ventana de pywebview. | Que Jan lo abra y avise si algo se ve o funciona distinto: troncales, búsqueda, postes con zoom 15+, fotos. |
| D6 | **Íconos del menú y vista Usuarios** en la ventana real (misma situación que D5). | Revisión rápida de Jan. |

## Lo que no está pendiente (para no retomarlo por error)

- **Subir el proyecto a GitHub:** Jan interrumpió esa pregunta en una sesión anterior. **No retomar a menos que Jan lo pida.** Si se retoma, nunca subir `.env`, `output/`, `logs/`, `red_fibra/`, `visioMapas/`, `templates/`, `red_kmz/` ni `visor_rutas/datos_kmz/`.
- **Archivos borrados por error (7 oct):** al limpiar `output\visor` se borraron por error archivos de prueba de Jan (`Prueba_…xlsx`, `Estimacion_…xlsx`, `Prueba.png`). Se pueden regenerar. Lección: revisar fechas antes de borrar.
