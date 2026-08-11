@echo off
rem ============================================================
rem  Plania Owner - panel del negocio (facturacion, clientes,
rem  modelo financiero, kit de contenido).
rem
rem  ESTE ARCHIVO NO SE ENTREGA A NINGUN CLIENTE. Va solamente
rem  dentro de Plania_Owner.zip, que se arma con
rem  "python packaging\build_release.py --con-owner" y no se
rem  publica ni se sube a la pagina de descargas.
rem
rem  Es la version .BAT del panel, para la misma situacion que la
rem  del producto: una PC donde no se puede ejecutar un .exe. Usa
rem  el Python del sistema, igual que INICIAR_PLANIA.bat.
rem ============================================================
setlocal
cd /d "%~dp0"
title Plania Owner - panel del negocio

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [Owner] No se encontro Python. Instalalo desde https://www.python.org/downloads/
  echo         y marca la casilla "Add Python to PATH" durante la instalacion.
  echo.
  pause
  exit /b 1
)

rem El token es lo unico que separa este panel de cualquiera que abra el
rem archivo. Se pide aca en vez de dejarlo escrito: un .bat con el token
rem adentro es un token publicado en cuanto el archivo se copia a otro lado.
if "%PLANIA_OWNER_TOKEN%"=="" (
  set /p PLANIA_OWNER_TOKEN=Token del panel del dueno:
)
if "%PLANIA_OWNER_TOKEN%"=="" (
  echo [Owner] Sin token no se abre el panel.
  pause
  exit /b 1
)

if not exist .venv (
  echo [Owner] Primera ejecucion: creando entorno e instalando dependencias...
  python -m venv .venv || (echo [Owner] Error creando el entorno & pause & exit /b 1)
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  python -m pip install --no-cache-dir -r requirements.txt > "%TEMP%\plania_owner_pip.log" 2>&1
  if errorlevel 1 (
    type "%TEMP%\plania_owner_pip.log"
    del "%TEMP%\plania_owner_pip.log" >nul 2>nul
    rem Igual que en el lanzador del producto: si la instalacion quedo a
    rem medias hay que borrar .venv, o el proximo arranque se saltea todo
    rem este bloque y falla mas adelante con un error mas confuso.
    rd /s /q .venv >nul 2>nul
    echo [Owner] No se pudieron instalar las dependencias.
    pause
    exit /b 1
  )
  del "%TEMP%\plania_owner_pip.log" >nul 2>nul
) else (
  call .venv\Scripts\activate.bat
)

if not exist data\erp_demo.db (
  echo [Owner] Generando base de datos demo...
  python data\generate_dataset.py --seed 42
)

echo [Owner] Iniciando el panel del negocio...
rem Mismo lanzador que el producto: elige puerto libre, espera a que el
rem servidor responda y recien ahi abre la ventana. PLANIA_PANEL=owner es lo
rem unico que cambia cual de las dos pantallas levanta.
set PLANIA_PANEL=owner
python packaging\plania_launcher.py
if errorlevel 1 (
  echo.
  echo [Owner] El panel termino con error. El detalle esta arriba.
  pause
)
endlocal
