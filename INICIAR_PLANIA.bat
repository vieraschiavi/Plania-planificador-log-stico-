@echo off
rem ============================================================
rem  Plania - lanzador para Windows (version .BAT, sin instalador)
rem  Doble clic: crea el entorno, instala dependencias la primera
rem  vez, genera la base demo y abre Plania en el navegador.
rem  Requiere Python 3.11+ instalado (python.org, casilla "Add to PATH").
rem ============================================================
setlocal
cd /d "%~dp0"
title Plania - Planificacion logistica y comercial inteligente

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [Plania] No se encontro Python. Instalalo desde https://www.python.org/downloads/
  echo          y marca la casilla "Add Python to PATH" durante la instalacion.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo [Plania] Primera ejecucion: creando entorno e instalando dependencias...
  echo          Necesita alrededor de 1 GB libre y unos minutos.
  python -m venv .venv || (echo [Plania] Error creando el entorno & pause & exit /b 1)
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  rem --no-cache-dir: sin esto pip guarda ademas una copia de cada paquete
  rem descargado en su cache, asi que en un disco justo de espacio se termina
  rem necesitando casi el doble de lo que hace falta.
  rem La salida va a un archivo en vez de --quiet: si falla hace falta ver el
  rem error real de pip para saber que paso, y para poder distinguir "el disco
  rem se lleno" de cualquier otro motivo.
  python -m pip install --no-cache-dir -r requirements.txt > "%TEMP%\plania_pip.log" 2>&1
  if errorlevel 1 (
    type "%TEMP%\plania_pip.log"
    echo.
    findstr /c:"No space left on device" /c:"Errno 28" "%TEMP%\plania_pip.log" >nul
    if errorlevel 1 (
      echo [Plania] No se pudieron instalar las dependencias. El detalle del
      echo          error esta arriba. Si necesitas soporte, copialo y
      echo          escribi a ventas@plania.uy
    ) else (
      echo [Plania] Te quedaste sin espacio en disco durante la instalacion.
      echo          Libera espacio en disco y volve a abrir este archivo.
    )
    del "%TEMP%\plania_pip.log" >nul 2>nul
    rem Sin este borrado, la proxima vez ".venv" ya existe —aunque este a
    rem medio instalar— y todo este bloque se saltea: el usuario liberaria
    rem espacio, reintentaria, y se encontraria con un error distinto y mas
    rem confuso (modulos faltantes) en vez de que se reintente la instalacion.
    rd /s /q .venv >nul 2>nul
    pause
    exit /b 1
  )
  del "%TEMP%\plania_pip.log" >nul 2>nul
) else (
  call .venv\Scripts\activate.bat
)

if not exist data\erp_demo.db (
  echo [Plania] Generando base de datos demo...
  python data\generate_dataset.py --seed 42
)

echo [Plania] Iniciando... se abre solo en tu navegador.
rem El arranque lo hace el mismo lanzador que usa el ejecutable instalado.
rem Antes esto abria http://localhost:8501 a mano, y traia dos problemas:
rem el 8501 es el puerto por defecto de cualquier app Streamlit, asi que si
rem el usuario ya tenia otra corriendo se le abria ESA en vez de Plania; y
rem el navegador se abria antes de que el servidor levantara. El lanzador
rem elige un puerto libre, espera a que el servidor responda y recien ahi
rem abre el navegador.
python packaging\plania_launcher.py
if errorlevel 1 (
  echo.
  echo [Plania] El programa termino con error. Copia el mensaje de arriba
  echo          si necesitas soporte: ventas@plania.uy
  pause
)
endlocal
