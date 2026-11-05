# Crea el acceso directo "Fiber Budget" (con su icono) para abrir el visor de rutas.
#
#   powershell -ExecutionPolicy Bypass -File herramientas\crear_acceso_directo.ps1            -> en el Escritorio
#   powershell -ExecutionPolicy Bypass -File herramientas\crear_acceso_directo.ps1 -MenuInicio -> tambien en el menu Inicio (de ahi se puede anclar a la barra de tareas)
#
# Abre el visor igual que "Visor de rutas.bat" (pythonw del .venv, sin ventana de consola; errores en logs\visor.log), pero con el nombre y el icono de Fiber Budget.
param([switch]$MenuInicio)

$raiz = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$icono = Join-Path $raiz "visor_rutas\web\fiber_budget.ico"
if (-not (Test-Path $pythonw)) { Write-Error "No se encontro $pythonw"; exit 1 }
if (-not (Test-Path $icono)) { Write-Error "No se encontro $icono (generelo con: .venv\Scripts\python.exe herramientas\icono_fiber_budget.py)"; exit 1 }

$carpetas = @([Environment]::GetFolderPath("Desktop"))
if ($MenuInicio) { $carpetas += (Join-Path ([Environment]::GetFolderPath("Programs")) "") }
$shell = New-Object -ComObject WScript.Shell
foreach ($carpeta in $carpetas) {
    $ruta = Join-Path $carpeta "Fiber Budget.lnk"
    $acceso = $shell.CreateShortcut($ruta)
    $acceso.TargetPath = $pythonw
    $acceso.Arguments = "-m visor_rutas"
    $acceso.WorkingDirectory = $raiz
    $acceso.IconLocation = "$icono,0"
    $acceso.Description = "Fiber Budget - Visor de rutas"
    $acceso.WindowStyle = 1
    $acceso.Save()
    Write-Host "Acceso directo creado: $ruta"
}
