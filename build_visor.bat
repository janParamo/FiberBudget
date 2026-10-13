@echo off
rem Genera dist\VisorRutas\VisorRutas.exe (visor en modo remoto, para otras computadoras)
rem y VisorRutas.zip listo para compartir. No incluye .env, claves, bases ni plantillas.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro .venv\Scripts\python.exe en "%~dp0"
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller en el .venv ^(sin permisos de administrador^)...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 (
        echo No se pudo instalar PyInstaller.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" empaquetar_visor.py
if errorlevel 1 (
    echo.
    echo El empaquetado fallo. Revise los mensajes de arriba.
    pause
    exit /b 1
)
echo.
echo Comparta VisorRutas.zip (en esta carpeta). Instrucciones en dist\VisorRutas\LEEME.txt
pause
