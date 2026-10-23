# Documentación

Dónde está cada cosa. El manual general (instalar, configurar, endpoints, visor, app de campo) es el [README.md](../README.md) de la raíz.

## Para usar el sistema
| Documento | Para qué |
|---|---|
| [campo/GUIA_TECNICOS.md](campo/GUIA_TECNICOS.md) | La app de campo para técnicos: instalar en Android / iPhone, registrar puntos y cables, sin señal, **descargar la zona**, problemas comunes. Corta; se puede imprimir o mandar por WhatsApp. |
| [campo/CLOUDFLARE.md](campo/CLOUDFLARE.md) | El túnel de Cloudflare (dirección oficial de la app de campo; por ahora se usa ngrok). |
| [../docker/LEEME.md](../docker/LEEME.md) | Poner el servicio en un contenedor Docker en una VM Linux (sin Cloudflare ni dominio comprado): primer arranque, cargar datos, HTTPS, actualizar, respaldos. |
| [../datos/LEEME.md](../datos/LEEME.md) | Qué hay en la carpeta `datos/` y qué se puede borrar. |
| [../herramientas/LEEME.txt](../herramientas/LEEME.txt) | Los scripts de apoyo (empaquetado del visor, túnel, verificador, carga del KMZ, almacén de archivos). |
| [../red_fibra/LEEME.md](../red_fibra/LEEME.md) | La base de los diagramas Visio y cómo volver a importarla. |

## Diseño y decisiones
| Documento | Para qué |
|---|---|
| [modulo_redes/ESPECIFICACION.md](modulo_redes/ESPECIFICACION.md) | Especificación del visor v2 y del módulo de redes (con la actualización del 2026-10-22). |
| [modulo_redes/ARQUITECTURA.md](modulo_redes/ARQUITECTURA.md) | Datos y arquitectura del módulo de redes FTTH. |
| [modulo_redes/V2_FASE0_PLAN.md](modulo_redes/V2_FASE0_PLAN.md) | Plan del visor v2 (lectura del código y decisiones de Jan). |
| [modulo_redes/ESTUDIO_SPLITTERS.md](modulo_redes/ESTUDIO_SPLITTERS.md) | Estudios medidos sobre los diagramas: splitters, puertos libres y «hilos verdes». |
| [migracion_visio/PLAN.md](migracion_visio/PLAN.md) | Plan de migrar los diagramas Visio a mufas interactivas (§11: decisiones y estado actual). |
| [migracion_visio/FASE0_DIAGNOSTICO.md](migracion_visio/FASE0_DIAGNOSTICO.md) | Lo que se midió antes de migrar y las respuestas de Jan. |

## Bitácoras (una carpeta por día; empezar por la más reciente)
| Carpeta | Contenido |
|---|---|
| [bitacora/2026-10-22/](bitacora/2026-10-22/LEEME.md) | Cambio de máquina, bases desde cero, almacén de archivos en la base, claves de técnicos, descargar zona, regla del splitter, migración Visio, reorganización de carpetas. **Pendientes al final.** |
| [bitacora/2026-10-13/](bitacora/2026-10-13/LEEME.md) | Visor v2, migración Visio (fases 1 a 7), reglas de presupuesto, app de campo (fases 1 a 6). |
| [bitacora/2026-10-12/](bitacora/2026-10-12/LEEME.md) | Módulo de redes (fases 5 a 7 y sección 8). |
| [bitacora/2026-10-09/](bitacora/2026-10-09/LEEME.md) | Fases 2 a 5 del módulo de redes y reglas de metraje. |
| [bitacora/2026-10-08/](bitacora/2026-10-08/LEEME.md) | Fase 1 del módulo de redes (con `01_` a `04_`: hecho, pendiente de confirmar, siguiente, datos útiles). |

Las bitácoras son historia: describen las carpetas y los nombres de ese día (por ejemplo `red_kmz/` o `visioMapas/`, hoy dentro de `datos/`).
