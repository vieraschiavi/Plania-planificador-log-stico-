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
#define AppURL "https://plania.uy"

[Setup]
AppId={{B7E2C1A4-6F3D-4E2A-9C21-3A8F5D2E7B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
; VersionInfo* es lo que Windows muestra en la pestaña "Detalles" del .exe
; (clic derecho → Propiedades) — un instalador sin esto se ve genérico.
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Instalador de {#AppName}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
DefaultDirName={autopf}\Plania
; Explícito a propósito: el usuario tiene que poder elegir dónde instalar.
; Por defecto Inno Setup decide solo si mostrar esta página o no; "no" la
; deja SIEMPRE visible, sin depender de esa heurística.
DisableDirPage=no
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
UninstallDisplayName={#AppName}
; Streamlit/pandas/pyarrow modernos no corren en Windows 7/8: mejor que
; Setup lo diga de entrada que dejar instalar algo que después no arranca.
MinVersion=10.0

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

[UninstallDelete]
; Los .pyc que Python compila al primer arranque no los trae el instalador,
; así que tampoco los borra automáticamente al desinstalar — sin esto quedan
; sueltos en {app}. Los datos del usuario (licencia, config) viven aparte, en
; su carpeta de perfil (ver plania/config.py), y esos si sobreviven adrede:
; que desinstalar y reinstalar no le haga perder la licencia activada.
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Si Plania está corriendo, instalar o desinstalar encima deja archivos
// bloqueados a medio copiar/borrar — el error clásico de "no se puede
// acceder al archivo porque está siendo usado por otro proceso". Se detecta
// por el nombre del proceso y se le pide al usuario que lo cierre antes de
// seguir, en vez de fallar a mitad de camino.
//
// `tasklist.exe` devuelve código de salida 0 tanto si encuentra el proceso
// como si no lo encuentra — el código de salida no sirve para saber si está
// corriendo. Por eso se manda la salida a un archivo temporal (vía cmd.exe,
// que es lo que sabe redirigir con ">") y se busca el nombre del ejecutable
// ahí adentro.
function EstaPlaniaAbierto(): Boolean;
var
  ArchivoTmp: String;
  Salida: AnsiString;  // LoadStringFromFile pide AnsiString, no String
  ResultCode: Integer;
begin
  Result := False;
  ArchivoTmp := ExpandConstant('{tmp}\plania_tasklist.txt');
  if Exec(ExpandConstant('{cmd}'),
          '/C tasklist /FI "IMAGENAME eq {#AppExe}" /NH > "' + ArchivoTmp + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringFromFile(ArchivoTmp, Salida) then
      Result := (Pos('{#AppExe}', String(Salida)) > 0);
  end;
  DeleteFile(ArchivoTmp);
end;

function CerrarPlaniaSiEstaAbierto(): Boolean;
begin
  Result := True;
  while EstaPlaniaAbierto() do
  begin
    if MsgBox('Plania está abierto. Cerralo para continuar.' + #13#10 +
              #13#10 + 'Presioná Reintentar cuando lo hayas cerrado, o ' +
              'Cancelar para salir del instalador.',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := CerrarPlaniaSiEstaAbierto();
end;

function InitializeUninstall(): Boolean;
begin
  Result := CerrarPlaniaSiEstaAbierto();
end;
