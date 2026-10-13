@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo No se encontro .venv\Scripts\pythonw.exe en "%~dp0"
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

rem pythonw.exe: sin ventana de consola. Errores en logs\visor.log
start "" ".venv\Scripts\pythonw.exe" -m visor_rutas
