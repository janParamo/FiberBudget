@echo off
rem Arma el visor (VisorRutas.zip con su version) y lo sube a la VM: las personas lo reciben solas la proxima vez que abran el visor.
rem Pide la contrasena de la VM una vez. Sin armar de nuevo:  herramientas\publicar_visor.bat --sin-empaquetar
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo No se encontro .venv\Scripts\python.exe en "%CD%"
    pause
    exit /b 1
)
".venv\Scripts\python.exe" herramientas\publicar_visor.py %*
if errorlevel 1 (
    echo.
    echo La publicacion fallo. Revise los mensajes de arriba.
)
pause
