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
5. **El visor `.exe`** (Windows) no cambia con el contenedor, pero se actualiza solo en cada persona: ver «Actualización automática del visor».
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
| `db` reinicia y su log dice `in 18+, these Docker images are configured to store database data...` | El volumen debe montarse en `/var/lib/postgresql` (no en `.../data`), como está en `docker-compose.yml`. Si quedó un volumen viejo vacío: `docker compose down` y `docker volume rm presupuestos_pgdata`. |
| `app` reinicia y el log dice `endpoint ... is already online` (ERR_NGROK_334) | La dirección de ngrok sigue encendida en otro lado (la PC de desarrollo): apagar `start_service.bat` allá, o dejar vacíos `NGROK_AUTHTOKEN` y `NGROK_DOMAIN` en la VM. |
| `app` queda `unhealthy` o reinicia | `docker compose logs app`. Lo más común: contraseña o `DB_HOST` mal puestos (con el perfil `db` es `db`), o `db` todavía arrancando. |
| `Permission denied` al escribir en `output` / `datos` / `respaldos` | `sudo chown -R 1000:1000 volumenes` (o poner `APP_UID` y `APP_GID` en el `.env`). |
| El PDF sale con `#NAME?` en los códigos, sin precios y con el total mal (el Excel abierto en Excel se ve bien) | LibreOffice demasiado viejo: la plantilla usa `XLOOKUP`, que entiende desde la 24.8. La imagen usa Debian «trixie» (LibreOffice 25.2) y al construirse corre `herramientas/comprobar_libreoffice.py`; si falla, la imagen no se crea. En la VM: `docker compose --profile db exec app soffice --headless --version` y `docker compose --profile db exec app python herramientas/comprobar_libreoffice.py`. Los presupuestos ya generados con el LibreOffice viejo hay que generarlos de nuevo. |
| El PDF o el Excel salen sin totales | `docker compose exec app soffice --headless --version`: LibreOffice debe responder. |
| `pg_dump: error: aborting because of server version mismatch` (respaldo del módulo) | El servidor de la base es más nuevo que el cliente de la imagen: reconstruir con `--build-arg PG_CLIENT_VERSION=<versión del servidor>`. |
| ngrok dice que la dirección ya está en línea | Está encendida en otro lado (la PC de desarrollo). Apagarla allá. |
| Con `--profile https` Caddy no consigue el certificado | El DNS del subdominio debe apuntar a la VM y los puertos 80 y 443 deben estar abiertos desde internet. |
| El mapa de la app de campo se ve gris | La VM no tiene salida a `server.arcgisonline.com` (la descarga la hace el teléfono, no la VM, pero el mapa de la ruta del Excel sí la usa). |

## Actualización automática del visor
El visor `.exe` se actualiza solo: al abrirse pregunta al servidor qué versión hay; si es más nueva, avisa, la descarga, la verifica y se reemplaza y vuelve a abrir. La URL y la clave de cada persona (`%APPDATA%\VisorRutas`) no se tocan.

**Preparar la VM (una sola vez, antes de `docker compose up`, con el usuario de la VM y sin `sudo`):**
```bash
mkdir -p ~/fiber_budget/actualizaciones
docker compose --profile db up -d        # ahora monta esa carpeta (docker-compose.yml)
```
Si Docker ya había creado la carpeta con `root`, se arregla con `sudo chown $USER ~/fiber_budget/actualizaciones`.

**Publicar una versión nueva (en la PC de desarrollo, cada vez que cambie el visor):**
```powershell
herramientas\publicar_visor.bat          # arma el paquete (como build_visor.bat) y lo sube a la VM; pide la contraseña de la VM una vez
```
Con `--sin-empaquetar` sube el `VisorRutas.zip` que ya existe. El destino (`jparamo@10.0.40.154`, puerto `5730`, carpeta `~/fiber_budget/actualizaciones`) se cambia con `--destino`, `--puerto` y `--carpeta`.
Lo que sube: `VisorRutas.zip` y `version.json` (versión, tamaño y SHA-256). El servicio solo ofrece la versión cuando el paquete llegó completo; no hace falta reiniciar nada en la VM.

**Qué ve cada persona:** al abrir el visor sale «Hay una versión nueva del visor… Se va a actualizar ahora», pulsa Aceptar, espera unos segundos y el visor se abre solo con la versión nueva.

**Límites:**
- Cada persona necesita recibir **una vez** el `VisorRutas.zip` o el instalador de la primera versión que trae esta función (las anteriores no saben actualizarse). Desde esa en adelante, solas.
- Se actualiza si la carpeta del programa se puede escribir (la del instalador o la del `.zip` en la carpeta del usuario). Si no, el visor avisa que pida el instalador.
- Si una actualización falla en una PC, ese visor se abre como estaba y no la reintenta en un día.
- Registro: `%LOCALAPPDATA%\VisorRutas\visor.log`. Aviso de fallo: `%LOCALAPPDATA%\VisorRutas\actualizacion_fallida.json`.
- Con el servidor apagado o sin conexión el visor abre normal; no se actualiza hasta la próxima vez.

## Roles y claves de los usuarios
Dos cosas distintas: la **clave** (quién puede entrar) y el **rol** (qué puede hacer). Las dos viven en la VM: las claves en su `.env` (`VISOR_API_KEYS=nombre:clave,…`, se lee en cada petición) y los roles en la base (vista **Usuarios**). El nombre de la clave es la persona del visor y debe coincidir con la persona del usuario.

| Rol | Qué puede hacer |
|---|---|
| `super_administrador` | Todo, y es el único que crea, cambia de rol o desactiva a los administradores. Nadie más lo modifica. Siempre debe quedar uno activo. |
| `administrador` | Todo, incluida la gestión de usuarios (lector, editor, técnico, guest, prueba), pero no toca a los administradores. |
| `editor` / `lector` / `tecnico` | Como antes (proyectos asignados, solo ver, app de campo). |
| `guest` | El mapa, generar rutas y presupuestos y editar la ruta que genera el generador. Sin Tickets, Redes, Campo, Planificación, Usuarios, Mis lugares ni cambios del KMZ. |
| `prueba` | Solo lectura en todo, más calcular rutas y presupuestos: para probar los endpoints sin riesgo. |

Mientras no haya ningún super administrador (instalación nueva) los administradores conservan todo el poder, para que nadie quede fuera.

**Dejar los usuarios con la estructura vigente** (jan super administrador, marlon y javier administradores, guest, prueba) en la VM:
```bash
cd ~/fiber_budget
docker compose --profile db exec app python herramientas/configurar_usuarios.py --desactivar-otros      # simula: muestra qué cambiaría
docker compose --profile db exec app python herramientas/configurar_usuarios.py --aplicar --desactivar-otros
```
`--desactivar-otros` desactiva (borrado lógico, reversible desde Usuarios) a los usuarios que no están en la lista. Sin `--aplicar` no cambia nada.

**Agregar o quitar a alguien:** poner su clave en `VISOR_API_KEYS` del `.env` de la VM (`nano ~/fiber_budget/.env`; no hace falta reiniciar), que entre una vez con esa clave (queda como lector) y que un administrador le asigne el rol en Usuarios. Para quitarle el acceso se borra su clave del `.env`.

**Cambiar una clave:** se reemplaza en el `.env` de la VM y se le entrega la nueva a la persona (Configuración del visor). La anterior deja de servir en el acto.

El servidor aplica estos límites en cada petición (un guest que llame a un endpoint que no le toca recibe 403); la pantalla además oculta lo que no le corresponde. El rol se consulta cada 30 segundos, así que un cambio de rol llega a la persona en menos de un minuto.
