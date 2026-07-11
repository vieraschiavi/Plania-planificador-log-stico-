; Plania · Instalador Windows (Inno Setup 6)
; Envuelve el bundle standalone de PyInstaller (dist\Plania) en un instalador
; Plania_Setup_vX.exe con accesos directos en el menú Inicio y el escritorio.
;
; Construir (en Windows, con Inno Setup instalado):
;   iscc packaging\instalador.iss
; Requiere que antes exista dist\Plania\ (salida de PyInstaller).

#define AppName "Plania"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "Plania"
#define AppExe "Plania.exe"

[Setup]
AppId={{B7E2C1A4-6F3D-4E2A-9C21-3A8F5D2E7B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Plania
DefaultGroupName=Plania
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Plania_Setup_v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\assets\brand\plania.ico
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\Plania\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Plania"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar Plania"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Plania"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir Plania ahora"; Flags: nowait postinstall skipifsilent
