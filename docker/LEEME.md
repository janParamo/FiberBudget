# Despliegue con Docker

El servicio de presupuestos (API de n8n, visor remoto y app de campo) en un contenedor, en una VM Linux, **sin túnel de Cloudflare ni dominio comprado**. Todo se maneja por consola (SSH).

> **Estado:** estos archivos se escribieron sin poder construir la imagen en la PC de desarrollo (no tiene Docker). El primer `docker build` es la prueba real: trae una **prueba de humo** (importa el servicio y arranca LibreOffice); si falla, la imagen no se crea y el error dice por qué.

## Qué hay

| Archivo | Para qué |
|---|---|
| `Dockerfile` | La imagen: Python 3.13 + LibreOffice (con fuentes) + `pg_dump` 18 + el código. Corre sin privilegios (usuario 1000). |
| `docker-compose.yml` | Cómo se enciende: servicio `app`, y de forma opcional `db` (PostgreSQL + PostGIS) y `caddy` (HTTPS con subdominio). |
| `docker/env.ejemplo` | Plantilla del `.env` (claves, base de datos, cómo se entra desde afuera). |
| `docker/initdb/01-crear-bases.sql` | Crea las dos bases con PostGIS la primera vez que arranca `db`. |
| `docker/Caddyfile` | El proxy HTTPS (solo con el perfil `https`). |
| `requirements-servicio.txt` | Las librerías del contenedor (sin pruebas ni visor de escritorio). |
| `.dockerignore` | Lista blanca: a la imagen solo entra el código (nunca `.env`, `datos/`, `output/`, bases ni claves). |

## Qué necesita la VM
Linux con **Docker Engine y el plugin Compose** (`docker compose version`), 2 CPU, 4 GB de RAM y 30 GB de disco, zona horaria `America/Managua`, salida a internet hacia `maps.googleapis.com`, `server.arcgisonline.com` y (si usa ngrok) ngrok, y un usuario con SSH que pueda ejecutar `docker` sin contraseña de administrador (grupo `docker`).

## Primer arranque

```bash
# 1. el proyecto en la VM (git clone, o copiar la carpeta) y entrar a ella
cd fiber_budget

# 2. la configuración: copiar la plantilla y completarla (contraseñas, GOOGLE_API_KEY, SERVICE_API_KEY, claves, cómo se entra)
cp docker/env.ejemplo .env
nano .env

# 3. las carpetas que no se pueden perder (fuera del contenedor), con el dueño que usa el contenedor (1000)
mkdir -p volumenes/datos volumenes/output volumenes/logs volumenes/respaldos
sudo chown -R 1000:1000 volumenes

# 4. construir y encender, con PostgreSQL propio en la misma VM
docker compose --profile db up -d --build

# 5. comprobar
docker compose ps                         # app debe decir "healthy" (tarda ~1 minuto)
curl -s http://127.0.0.1:8000/health      # {"status":"ok"}
docker compose logs -f app                # Ctrl+C para salir
```

Con una base de datos que ya existe en otro servidor se omite `--profile db` y en el `.env` se pone su dirección en `DB_HOST` y `VISIO_DB_HOST`. Esa base necesita **PostgreSQL 16 o más y PostGIS 3.4 o más**, las bases `Presupuesto_fibra` y `Presupuesto_visio`, y un usuario que pueda hacer `CREATE EXTENSION postgis`.

## Cargar los datos
La base nueva está vacía. Hay dos caminos:

**A. Llevar las bases de la PC de desarrollo (recomendado: no se repite nada).** Contienen el KMZ, los diagramas Visio, la red migrada, los usuarios y el almacén de archivos.

```powershell
# En la PC de desarrollo (Windows), con el cliente de PostgreSQL 18:
pg_dump -h localhost -U postgres -Fc -f presupuesto_fibra.dump Presupuesto_fibra
pg_dump -h localhost -U postgres -Fc -f presupuesto_visio.dump Presupuesto_visio
# copiar los dos .dump a la VM (scp)
```
```bash
# En la VM, desde la carpeta del proyecto (la base `db` debe estar encendida y ser de versión 18 o más, igual que el pg_dump):
docker compose exec -T db pg_restore -U postgres -d Presupuesto_fibra --no-owner --clean --if-exists < presupuesto_fibra.dump
docker compose exec -T db pg_restore -U postgres -d Presupuesto_visio --no-owner --clean --if-exists < presupuesto_visio.dump
docker compose restart app
```
(Pueden salir avisos sobre la extensión `postgis`: son normales.)

**B. Empezar de cero** (cuando no se quiere llevar la base de desarrollo):
```bash
# el esquema `redes` se crea solo la primera vez que el servicio lo usa; para forzarlo:
docker compose exec app python -m visor_rutas.redes.migrar
# KMZ -> red_puntos / red_lineas (poner antes el .kmz en volumenes/datos/kmz/)
docker compose exec app python herramientas/cargar_kmz.py
# Diagramas Visio (poner antes los archivos en volumenes/datos/visio/DIAGRAMAS\ ACTUALIZADOS; tarda ~10 minutos)
docker compose exec app python red_fibra/importador.py --origen "datos/visio/DIAGRAMAS ACTUALIZADOS"
# Migrar la red existente a los proyectos base
docker compose exec app python -m visor_rutas.redes.migrar_visio
```

## Cómo se entra desde afuera (HTTPS)
La app del teléfono exige HTTPS (para el GPS y para instalarse). Dos formas, sin comprar nada:

1. **ngrok dentro del contenedor** (lo más rápido para probar): en el `.env` poner `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` y `CAMPO_URL_PUBLICA=https://<NGROK_DOMAIN>`. El servicio abre el túnel solo. La misma dirección **no puede estar encendida a la vez en la PC de desarrollo y aquí**: apagar primero la PC.
2. **Un subdominio de la empresa** (lo que debe pedirse a Cloud): crear el registro DNS `presupuestos.<dominio-de-la-empresa>` → IP de la VM, abrir los puertos 80 y 443, poner `DOMINIO=presupuestos.<dominio>` y `CAMPO_URL_PUBLICA=https://<DOMINIO>` en el `.env` y encender con `docker compose --profile db --profile https up -d`. Caddy consigue y renueva el certificado solo.

Quien llama (n8n, el visor `.exe`, los teléfonos) usa esa dirección: n8n con el header `X-API-Key`, el visor y los teléfonos con su clave (`VISOR_API_KEYS` / `CAMPO_API_KEYS`).

## Día a día
```bash
docker compose ps                  # estado
docker compose logs -f app         # ver lo que pasa
docker compose restart app         # reiniciar
docker compose exec app bash       # entrar al contenedor
docker compose stop                # apagar todo (los datos quedan)
```
Los datos viven fuera del contenedor: `volumenes/` (presupuestos, fotos de campo, respaldos, logs) y el volumen `pgdata` (base). Borrar o reconstruir el contenedor **no** los toca.

## Actualizar cuando cambie el programa
1. **Cambio de código** (lo normal): en la VM, `git pull` (o copiar los archivos) y
   `docker compose --profile db up -d --build`. Reemplaza el contenedor en unos segundos; hay un corte breve. Para volver atrás se vuelve a la versión anterior del código y se repite. Conviene dar una etiqueta a cada versión: `VERSION=2026-10-23` en el `.env`.
2. **`business_rules.yaml`** (reglas, etiquetas, umbrales): se edita el archivo de la VM; el servicio lo lee en cada petición. No hace falta reiniciar.
3. **Las claves** (`VISOR_API_KEYS`, `CAMPO_API_KEYS`) del `.env`: se leen solas, sin reiniciar. Los demás valores del `.env` sí piden `docker compose up -d`.
4. **La base:** las migraciones nuevas se aplican solas al arrancar la versión nueva (las que cambian datos hacen un respaldo antes en `volumenes/respaldos`).
5. **El visor `.exe`** (Windows) no cambia con el contenedor: si cambian sus pantallas hay que regenerar `VisorRutas.zip` (`herramientas\build_visor.bat` en la PC de desarrollo).
6. **La app del teléfono** se actualiza sola la próxima vez que se abre con señal.

## Respaldos
- El módulo de redes hace sus respaldos (`.json` + `.sql`) en `volumenes/respaldos` y conserva los últimos 20.
- **La base completa** hay que respaldarla desde la VM, por ejemplo cada noche con cron:
  `docker compose exec -T db pg_dump -U postgres -Fc Presupuesto_visio > /ruta/respaldos/presupuesto_visio_$(date +%F).dump` (igual para `Presupuesto_fibra`). Pida a Cloud que además respalde `volumenes/` y que **pruebe una restauración**.

## Reglas que no se deben romper
- **Una sola instancia.** El servicio corre con un proceso (`--workers 1`) porque el índice de tickets (`output/budget_index.json`) y los avisos en tiempo real no admiten varias. No escalar a más réplicas.
- **Nada de datos en la imagen.** El `.env`, las bases, `datos/` y `output/` no se copian a la imagen (ver `.dockerignore`) ni se suben a Git.
- **No publicar el puerto 8000 hacia afuera.** `docker-compose.yml` lo deja solo en `127.0.0.1`: la entrada es ngrok o Caddy.

## Si algo falla
| Síntoma | Qué mirar |
|---|---|
| `docker compose up` dice que falta `.env` o crea una carpeta llamada `.env` | Copiar `docker/env.ejemplo` a `.env` **antes** del primer arranque; si se creó una carpeta, borrarla y crear el archivo. |
| `app` queda `unhealthy` o reinicia | `docker compose logs app`. Lo más común: contraseña o `DB_HOST` mal puestos (con el perfil `db` es `db`), o `db` todavía arrancando. |
| `Permission denied` al escribir en `output` / `datos` / `respaldos` | `sudo chown -R 1000:1000 volumenes` (o poner `APP_UID` y `APP_GID` en el `.env`). |
| El PDF o el Excel salen sin totales | `docker compose exec app soffice --headless --version`: LibreOffice debe responder. |
| `pg_dump: error: aborting because of server version mismatch` (respaldo del módulo) | El servidor de la base es más nuevo que el cliente de la imagen: reconstruir con `--build-arg PG_CLIENT_VERSION=<versión del servidor>`. |
| ngrok dice que la dirección ya está en línea | Está encendida en otro lado (la PC de desarrollo). Apagarla allá. |
| Con `--profile https` Caddy no consigue el certificado | El DNS del subdominio debe apuntar a la VM y los puertos 80 y 443 deben estar abiertos desde internet. |
| El mapa de la app de campo se ve gris | La VM no tiene salida a `server.arcgisonline.com` (la descarga la hace el teléfono, no la VM, pero el mapa de la ruta del Excel sí la usa). |
