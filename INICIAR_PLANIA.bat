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
  python -m venv .venv || (echo [Plania] Error creando el entorno & pause & exit /b 1)
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt || (echo [Plania] Error instalando dependencias & pause & exit /b 1)
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
