# Túnel de Cloudflare: la dirección oficial de la app de campo

La app de campo (PWA) **solo funciona por HTTPS**: sin él el teléfono no da el GPS, no instala la app ni guarda los puntos sin señal. El servicio de esta PC escucha solo en
`127.0.0.1:8000`; el túnel de Cloudflare le pone una dirección pública con HTTPS (por ejemplo `https://api.fiberbudget.com`) **sin abrir puertos ni pedir permisos de administrador**,
y no muestra la página de advertencia que ngrok enseña al abrir el enlace por primera vez.

> **Estado actual (21/10/2026): este túnel NO está en uso.** El dominio `fiberbudget.com` todavía no está registrado (se agregó a Cloudflare, pero Cloudflare no lo vende ni lo regala: hay que comprarlo, un `.com` cuesta unos 10 USD al año), así que `api.fiberbudget.com` no existe. **Por ahora la app de campo entra por ngrok** (`CAMPO_URL_PUBLICA` en `.env`), que ya da HTTPS; el único costo es una página de aviso («Visit Site») la primera vez en cada teléfono. `start_service.bat` solo abre este túnel si `.env` tiene `CLOUDFLARE_ACTIVAR=1`.
>
> Esto lo activa quien administra la cuenta de Cloudflare del dominio. Lo que se prepara en el proyecto ya está hecho; abajo van los pasos que faltan.

## Qué trae el proyecto
| Archivo | Para qué |
|---|---|
| `herramientas\iniciar_tunel_cloudflare.bat` | Abre el túnel (lee `CLOUDFLARE_TUNNEL_TOKEN` del `.env`; el token no se escribe en pantalla ni en la línea de comandos) |
| `start_service.bat` | Si `CLOUDFLARE_TUNNEL_TOKEN` está en `.env`, abre el túnel solo (otra ventana, minimizada) antes de arrancar el servicio |
| `herramientas\verificar_campo.py` | Prueba la dirección pública: archivos de la app, manifest, clave, avisos en tiempo real |
| `herramientas\cloudflared\config.yml.ejemplo` | Para la otra forma de crear el túnel (con archivo de configuración) |
| `CAMPO_URL_PUBLICA` (`.env`) | La dirección oficial; solo informativa: sale en el log al arrancar y en `/visor/campo/config` |

## Pasos (con el token del panel: lo más simple)
1. **Crear el túnel.** En <https://one.dash.cloudflare.com> → *Networks* → *Tunnels* → *Create a tunnel* → tipo *Cloudflared* → nombre `fiberbudget`. En la pantalla del instalador no ejecute nada:
   solo **copie el token** (la cadena larga que sigue a `--token`).
2. **Bajar `cloudflared.exe`.** Descargue `cloudflared-windows-amd64.exe` de <https://github.com/cloudflare/cloudflared/releases/latest>, cámbiele el nombre a `cloudflared.exe` y póngalo en la carpeta
   `herramientas\` del proyecto (ya existe). No hace falta instalarlo.
3. **Poner el token y la dirección en `.env`:**
   ```
   CLOUDFLARE_TUNNEL_TOKEN=<el token copiado>
   CAMPO_URL_PUBLICA=https://api.fiberbudget.com
   CLOUDFLARE_ACTIVAR=1
   ```
4. **Apuntar la dirección al servicio.** En el panel, dentro del túnel → *Public Hostname* → *Add*: *Subdomain* `api`, *Domain* `fiberbudget.com`, *Service* tipo `HTTP`, URL `127.0.0.1:8000`
   (el `API_HOST:API_PORT` del `.env`). Cloudflare crea solo el registro DNS.
5. **Encender.** Reinicie `start_service.bat` (abre el túnel por sí solo) o, sin reiniciar el servicio, ejecute `herramientas\iniciar_tunel_cloudflare.bat`. En el panel el túnel debe verse *Healthy*.
6. **Comprobar.**
   ```powershell
   .\.venv\Scripts\python.exe herramientas\verificar_campo.py https://api.fiberbudget.com CLAVE_DE_UN_TECNICO
   ```
   Todas las líneas deben salir `[OK]`. Luego abra `https://api.fiberbudget.com/campo/` en un teléfono.

Para que el túnel quede encendido siempre, deje `start_service.bat` en la carpeta *Inicio* de Windows (`shell:startup`; no pide administrador). Con permisos de administrador también se puede instalar `cloudflared` como servicio de
Windows (`cloudflared.exe service install <token>`), pero no es necesario.

## Otra forma: con archivo de configuración (la que ya está hecha en esta PC)
Si el túnel se crea desde la línea de comandos (`cloudflared tunnel login`, `tunnel create fiber-budget`, `tunnel route dns fiber-budget api.fiberbudget.com`), `herramientas\cloudflared\config.yml` (copia de `config.yml.ejemplo`, fuera de GitHub)
dice cuál túnel y a dónde apunta. **Si ese archivo existe, `herramientas\iniciar_tunel_cloudflare.bat` lo usa** (y no hace falta `CLOUDFLARE_TUNNEL_TOKEN`); `start_service.bat` lo abre solo cuando `.env` tiene `CLOUDFLARE_ACTIVAR=1`. cloudflared puede estar en `herramientas\` o instalado en el PATH
(en esta PC está en `C:\Program Files (x86)\cloudflared\`). **El paso `tunnel route dns` (o el *Public Hostname* del panel) es el que hace que el nombre `api.fiberbudget.com` llegue al túnel**: sin él el túnel está encendido pero nadie lo encuentra.

## Quién entra por esa dirección
Es la misma dirección de toda la API de la PC (la usan también n8n y el visor remoto):
- `/campo/…` (la página de la app) es pública, pero solo contiene HTML, JavaScript e imágenes; no muestra datos.
- `/visor/*` exige la `X-Visor-Key` de una persona de `VISOR_API_KEYS`; `/visor/campo/*` y la app `/campo` aceptan también las claves de técnicos de `CAMPO_API_KEYS`, que **no abren nada más** de `/visor/*`; `/presupuesto` exige `SERVICE_API_KEY`.
- Para limitar quién puede abrir la dirección, Cloudflare ofrece *Access* (Zero Trust → *Access* → *Applications*), pero **no lo active sobre `/visor/*` ni `/presupuesto`**: n8n y el visor remoto no pueden iniciar sesión.
- Si se pasa del ngrok actual a Cloudflare, la URL que lleva el visor remoto (☰ → Configuración) cambia a la nueva; hay que avisarle a cada persona.

## Si algo falla
| Síntoma | Qué mirar |
|---|---|
| `herramientas\iniciar_tunel_cloudflare.bat` dice «No se encontró cloudflared.exe» | El paso 2: el archivo debe llamarse `herramientas\cloudflared.exe` |
| Dice «Falta CLOUDFLARE_TUNNEL_TOKEN» | El paso 3: la línea del `.env`, sin comillas ni espacios |
| El panel muestra el túnel *Down* | La ventana «Tunel Cloudflare» cerrada, sin internet o token mal copiado |
| La dirección da error 502 / 1033 | El servicio no está encendido (`start_service.bat`) o el puerto de *Service* no es el del `.env` |
| `herramientas\verificar_campo.py` da `[FALLA] … ¿página de aviso del túnel?` | Todavía pasa por ngrok u otro intermediario que cambia la respuesta |
| El teléfono dice «dirección no segura» | Está abriendo `http://`; use la dirección que empieza con `https://` |
| «sin el rol de técnico» | En el visor → Usuarios → rol «Técnico de campo» para esa persona |
