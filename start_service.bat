@echo off
setlocal
cd /d "%~dp0"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

for /f "tokens=1,2" %%A in ('python -c "from config import get_settings; s = get_settings(); print(s.api_host, s.api_port)"') do (
    set "API_HOST=%%A"
    set "API_PORT=%%B"
)
if not defined API_HOST exit /b 1
if not defined API_PORT exit /b 1

rem Tunel de Cloudflare de la app de campo (solo si CLOUDFLARE_ACTIVAR=1 esta en .env; por ahora la direccion de entrada es la de ngrok, que abre el propio servicio): se abre en otra ventana minimizada.
for /f "usebackq" %%C in (`python -c "import os, config; print(1 if os.getenv('CLOUDFLARE_ACTIVAR') == '1' else 0)"`) do set "CF_TUNEL=%%C"
if "%CF_TUNEL%"=="1" start "Tunel Cloudflare" /min "%~dp0iniciar_tunel_cloudflare.bat"

python -m uvicorn main:app --host "%API_HOST%" --port "%API_PORT%" --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
