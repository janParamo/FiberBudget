; Instalador del Visor de rutas (modo remoto) con Inno Setup 6. Lo llama empaquetar_visor.py si ISCC esta instalado.
; Instalacion POR USUARIO, sin administrador: C:\Users\<usuario>\AppData\Local\Programs\VisorRutas. Los archivos instalados
; no llevan la marca de "descargado de la web", asi que pythonnet / WebView2 cargan sin problema.
; Uso manual:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" instalador_visor.iss   ->  InstaladorVisorRutas.exe (en esta carpeta)

[Setup]
AppId={{6E1C2B7A-4B1F-4B0E-9C57-5C1F0B7A2D11}
AppName=Visor de rutas
AppVersion=2.0
AppPublisher=IDEAY
DefaultDirName={autopf}\VisorRutas
DefaultGroupName=Visor de rutas
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=.
OutputBaseFilename=InstaladorVisorRutas
SetupIconFile=build\visor\visor.ico
UninstallDisplayIcon={app}\VisorRutas.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
LanguageDetectionMethod=none

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\VisorRutas\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Visor de rutas"; Filename: "{app}\VisorRutas.exe"
Name: "{autodesktop}\Visor de rutas"; Filename: "{app}\VisorRutas.exe"; Tasks: escritorio

[Run]
Filename: "{app}\VisorRutas.exe"; Description: "Abrir el Visor de rutas"; Flags: nowait postinstall skipifsilent
