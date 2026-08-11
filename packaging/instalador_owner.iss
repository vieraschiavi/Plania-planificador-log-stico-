; Plania Owner · Instalador Windows del panel del dueño (Inno Setup 6)
; ======================================================================
; Envuelve el bundle de packaging/plania_owner.spec (dist\Plania Owner) en un
; Plania_Owner_Setup.exe con ícono en el escritorio, entrada en el menú Inicio
; y desinstalador — lo mismo que el instalador del producto, para el panel.
;
; Construir (en Windows, con Inno Setup instalado):
;   python packaging\build_release.py --con-owner
; Requiere que antes exista "dist\Plania Owner\" (salida de PyInstaller).
;
; ESTE ARCHIVO NO SE PUBLICA NUNCA
; --------------------------------
; El resultado se llama Plania_Owner_Setup.exe, y ese prefijo no es
; decorativo: el workflow de Release corta la corrida si aparece cualquier
; "Plania_Owner*" entre lo que va a subir, y .gitignore impide que entre al
; repositorio. Adentro va la facturación, los clientes y el modelo financiero.
;
; POR QUÉ NO PIDE CONTRASEÑA
; --------------------------
; Porque no protegería nada. Este ejecutable no se distribuye: no está en
; INSTALADOR/, no está en ninguna release, y el panel ni siquiera viaja dentro
; del producto (packaging/proteger_codigo.py lo saca del .exe del cliente y
; del ZIP del .bat). Quien tiene este archivo es porque lo compiló él. Pedirle
; además una clave es pedirle una llave para su propia casa: lo único que
; consigue es que la anote en un papel al lado de la puerta.
;
; La contraseña sigue existiendo para el caso en que el panel se sirva por
; red: app/owner.py sólo la saltea si es este ejecutable Y está escuchando
; en loopback. Un despliegue en 0.0.0.0 la vuelve a pedir.

#define AppName "Plania Owner"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "Plania"
#define AppExe "Plania Owner.exe"
#define AppURL "https://plania.uy"
; Mismo orden de magnitud que el producto: lleva Python, Streamlit y pandas
; adentro. Un poco menos porque no incluye los datos de demostración.
#define EspacioNecesarioMB 800

[Setup]
; AppId propio y distinto del producto: si compartieran el mismo, instalar el
; panel desinstalaría Plania encima, o al revés — Windows los trataría como
; el mismo programa en dos versiones.
AppId={{4C9A7E51-2D83-4F16-B0A7-9E51C3D8A742}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Instalador de {#AppName}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
DefaultDirName={autopf}\Plania Owner
DisableDirPage=no
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
UninstallDisplaySize=838860800
OutputDir=..\dist
OutputBaseFilename=Plania_Owner_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=..\assets\brand\plania_wizard.bmp
WizardSmallImageFile=..\assets\brand\plania_wizard_small.bmp
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\assets\brand\plania.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
MinVersion=10.0

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; \
      GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\Plania Owner\*"; DestDir: "{app}"; \
      Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; El nombre del acceso directo dice "panel del dueño" y no sólo "Plania
; Owner": en el menú Inicio va a estar al lado de "Plania", y a un mes de
; instalados los dos, "Owner" no le recuerda a nadie cuál era cuál.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
      IconFilename: "{app}\{#AppExe}"; Comment: "Panel del dueño: facturación, clientes y modelo financiero"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"; \
      Comment: "Quitar {#AppName} de esta computadora"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
      IconFilename: "{app}\{#AppExe}"; \
      Comment: "Panel del dueño: facturación, clientes y modelo financiero"; \
      Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir el panel ahora"; \
      Flags: nowait postinstall skipifsilent
