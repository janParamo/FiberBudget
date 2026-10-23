@echo off
rem Tunel de Cloudflare de la app de campo: expone http://API_HOST:API_PORT como la direccion HTTPS oficial (ver docs\campo\CLOUDFLARE.md).
rem Necesita herramientas\cloudflared\config.yml (tunel creado con "cloudflared tunnel create") o CLOUDFLARE_TUNNEL_TOKEN en .env (tunel creado en el panel), y cloudflared.exe
rem en la carpeta "herramientas" (no pide permisos de administrador) o en el PATH.
setlocal
cd /d "%~dp0.."

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

set "CLOUDFLARED=%~dp0cloudflared.exe"
if not exist "%CLOUDFLARED%" (
    where cloudflared >nul 2>nul
    if errorlevel 1 (
        echo No se encontro cloudflared.exe. Copielo a la carpeta "herramientas" ^(docs\campo\CLOUDFLARE.md, paso 2^).
        exit /b 2
    )
    set "CLOUDFLARED=cloudflared"
)

rem Con herramientas\cloudflared\config.yml (tunel creado desde la linea de comandos) se usa ese archivo; si no, el token.
if exist "%~dp0cloudflared\config.yml" (
    "%CLOUDFLARED%" tunnel --config "%~dp0cloudflared\config.yml" --no-autoupdate run
    exit /b %errorlevel%
)

rem El token se pasa por variable de entorno ^(TUNNEL_TOKEN^), no en la linea de comandos: asi no se ve en la lista de procesos ni en pantalla.
for /f "usebackq delims=" %%T in (`python -c "import os, config; print(os.getenv('CLOUDFLARE_TUNNEL_TOKEN', ''))"`) do set "TUNNEL_TOKEN=%%T"
if not defined TUNNEL_TOKEN (
    echo Falta CLOUDFLARE_TUNNEL_TOKEN en el archivo .env ^(docs\campo\CLOUDFLARE.md, paso 3^).
    exit /b 3
)

"%CLOUDFLARED%" tunnel --no-autoupdate run