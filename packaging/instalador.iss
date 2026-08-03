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
; Espacio que ocupa Plania instalado. El bundle de PyInstaller lleva
; Python, Streamlit, pandas y pyarrow adentro, así que no es una
; aplicación chica; se pide un margen para los .pyc del primer arranque.
#define EspacioNecesarioMB 900

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
; Explícito y no heredado del nombre de la aplicación: de acá sale la carpeta
; que el usuario ve en el menú Inicio, y conviene que no cambie sola si algún
; día cambia AppName.
DefaultGroupName={#AppName}
; Lo que Windows muestra en Configuración → Aplicaciones. Sin esto la entrada
; aparece sin tamaño, como si fuera un accesorio suelto.
UninstallDisplaySize=943718400
OutputDir=..\dist
OutputBaseFilename=Plania_Setup_v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Panel de bienvenida/cierre y logo chico de las páginas intermedias — la
; misma marca que el ícono del .exe (assets/brand/plania_icon.png), generados
; con packaging/generar_imagenes_instalador.py y no diseñados a mano, para
; que no se desincronicen si el logo cambia.
WizardImageFile=..\assets\brand\plania_wizard.bmp
WizardSmallImageFile=..\assets\brand\plania_wizard_small.bmp
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
; WorkingDir explícito: el acceso directo del escritorio se puede lanzar desde
; cualquier carpeta, y el programa busca sus recursos relativos a donde corre.
; IconFilename también explícito para que el ícono se vea aunque Windows tenga
; la caché de íconos sucia, que es lo que hace aparecer la hoja en blanco.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
      IconFilename: "{app}\{#AppExe}"; Comment: "Abrir {#AppName}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"; \
      Comment: "Quitar {#AppName} de esta computadora"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
      IconFilename: "{app}\{#AppExe}"; Comment: "Abrir {#AppName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir Plania ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Los .pyc que Python compila al primer arranque no los trae el instalador,
; así que tampoco los borra automáticamente al desinstalar — sin esto quedan
; sueltos en {app}.
;
; A propósito NO hay una entrada acá para "{app}\datos": ahí vive la
; licencia activada y la configuración (plania/config.py), y tienen que
; sobrevivir a un desinstalar + reinstalar en la MISMA carpeta. Inno Setup
; sólo borra lo que él mismo instaló (sección [Files]) más las carpetas que
; queden vacías al terminar; como "datos" la crea el programa en su primer
; arranque —no el instalador— y no queda vacía, Inno Setup la deja tal cual.
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

// --------------------------------------------------------------------------
// Validación de la carpeta de instalación
// --------------------------------------------------------------------------
// El usuario puede elegir carpeta y disco, y tiene que poder — pero hay
// elecciones que instalan bien y fallan después, cuando ya no es obvio por
// qué. Se comprueban acá, con un mensaje que dice qué pasa, en vez de dejar
// que Setup reviente a mitad de copia o que el programa no arranque al día
// siguiente.

// GetDriveType no viene con el lenguaje de scripting de Inno Setup: es de la
// API de Windows y hay que declararla. Sin esta línea, `iscc` no compila.
function GetDriveType(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function LetraDeUnidad(Ruta: String): String;
begin
  Result := '';
  if (Length(Ruta) >= 2) and (Ruta[2] = ':') then
    Result := Uppercase(Copy(Ruta, 1, 1)) + ':\';
end;

function EspacioLibreMB(Ruta: String): Int64;
var
  Libre, Total: Int64;
begin
  Result := -1;
  // División entera: con '/' el resultado es de coma flotante y no entra en
  // un Int64 sin truncar.
  if GetSpaceOnDisk64(LetraDeUnidad(Ruta), Libre, Total) then
    Result := Libre div 1048576;
end;

function CarpetaEsEscribible(Ruta: String): Boolean;
var
  Prueba: String;
begin
  // Se prueba sobre el ancestro más cercano que exista: la carpeta elegida
  // normalmente todavía no está creada.
  while (Ruta <> '') and not DirExists(Ruta) do
    Ruta := ExtractFileDir(Ruta);
  if Ruta = '' then
  begin
    Result := False;
    Exit;
  end;
  Prueba := AddBackslash(Ruta) + 'plania_prueba_escritura.tmp';
  Result := SaveStringToFile(Prueba, 'x', False);
  if Result then
    DeleteFile(Prueba);
end;

function ValidarCarpeta(Ruta: String): Boolean;
var
  Unidad: String;
  Tipo: Integer;
  Libre: Int64;
begin
  Result := False;
  Unidad := LetraDeUnidad(Ruta);

  if Unidad = '' then
  begin
    // Una ruta de red (\\servidor\carpeta) instala, pero el programa deja de
    // abrir en cuanto el usuario no tiene la red — y el error de entonces no
    // se parece en nada a la causa.
    MsgBox('Elegí una carpeta en un disco de esta computadora (por ejemplo ' +
           'C:\ o D:\).' + #13#10 + #13#10 +
           'No se puede instalar en una ruta de red: Plania dejaría de abrir ' +
           'cada vez que la red no esté disponible.', mbError, MB_OK);
    Exit;
  end;

  Tipo := GetDriveType(Unidad);
  // 1 = no existe, 3 = disco fijo, 2 = extraíble, 4 = red, 5 = CD, 6 = RAM
  if Tipo <= 1 then
  begin
    MsgBox('La unidad ' + Unidad + ' no existe o no está lista.' + #13#10 +
           #13#10 + 'Elegí otro disco.', mbError, MB_OK);
    Exit;
  end;
  if Tipo = 5 then
  begin
    MsgBox('No se puede instalar en una unidad de solo lectura (' + Unidad + ').',
           mbError, MB_OK);
    Exit;
  end;
  if (Tipo = 2) or (Tipo = 4) then
  begin
    if MsgBox('La unidad ' + Unidad + ' es extraíble o de red.' + #13#10 + #13#10 +
              'Plania va a dejar de abrir cada vez que esa unidad no esté ' +
              'conectada. ¿Instalar igual?', mbConfirmation, MB_YESNO) = IDNO then
      Exit;
  end;

  Libre := EspacioLibreMB(Ruta);
  if (Libre >= 0) and (Libre < {#EspacioNecesarioMB}) then
  begin
    MsgBox('En la unidad ' + Unidad + ' quedan ' + IntToStr(Libre) +
           ' MB libres, y Plania necesita al menos {#EspacioNecesarioMB} MB.' +
           #13#10 + #13#10 + 'Liberá espacio o elegí otro disco.', mbError, MB_OK);
    Exit;
  end;

  if not CarpetaEsEscribible(Ruta) then
  begin
    MsgBox('No tenés permiso para escribir en:' + #13#10 + Ruta + #13#10 +
           #13#10 + 'Elegí otra carpeta, o volvé atrás y ejecutá el instalador ' +
           'como administrador.', mbError, MB_OK);
    Exit;
  end;

  Result := True;
end;

function NextButtonClick(PaginaActual: Integer): Boolean;
begin
  Result := True;
  if PaginaActual = wpSelectDir then
    Result := ValidarCarpeta(WizardDirValue);
end;

function InitializeSetup(): Boolean;
begin
  Result := CerrarPlaniaSiEstaAbierto();
end;

function InitializeUninstall(): Boolean;
begin
  Result := CerrarPlaniaSiEstaAbierto();
end;
