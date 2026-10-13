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

python -m uvicorn main:app --host "%API_HOST%" --port "%API_PORT%" --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
