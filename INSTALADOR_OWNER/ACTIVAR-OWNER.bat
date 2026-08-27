@echo off
rem ============================================================
rem  Plania - ACTIVAR LA VERSION FULL (edicion del dueno)
rem
rem  Doble clic. Deja esta PC con lo mismo que recibe un cliente
rem  que paga el plan mas alto: las ocho features, sin cupo y sin
rem  vencimiento practico.
rem
rem  No trae ninguna licencia adentro: la emite en esta maquina,
rem  con el secreto de firma de esta maquina. Ver LEEME.md.
rem
rem  Requiere Python 3.11+ (python.org, casilla "Add to PATH").
rem ============================================================
setlocal
rem El .bat vive en INSTALADOR_OWNER\ pero todo lo demas (requirements.txt,
rem el venv, el codigo) cuelga de la raiz del repositorio: se trabaja desde
rem ahi para reusar el MISMO entorno que usa INICIAR_PLANIA.bat en vez de
rem armar un segundo venv que despues queda desincronizado.
cd /d "%~dp0.."
title Plania - activar version FULL

echo.
echo  ============================================
echo   PLANIA - ACTIVAR VERSION FULL
echo  ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  [X] No se encontro Python. Instalalo desde
  echo      https://www.python.org/downloads/ y marca la casilla
  echo      "Add Python to PATH" durante la instalacion.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo  [1/2] Primera ejecucion: creando entorno e instalando dependencias.
  echo        Necesita alrededor de 1 GB libre y unos minutos.
  python -m venv .venv || (echo  [X] Error creando el entorno & pause & exit /b 1)
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  python -m pip install --no-cache-dir -r requirements.txt > "%TEMP%\plania_pip.log" 2>&1
  if errorlevel 1 (
    type "%TEMP%\plania_pip.log"
    echo.
    echo  [X] No se pudieron instalar las dependencias. El detalle esta arriba.
    del "%TEMP%\plania_pip.log" >nul 2>nul
    rem Igual que en INICIAR_PLANIA.bat: sin borrar el venv a medio armar, el
    rem proximo intento se saltea todo este bloque y falla mas adelante con un
    rem error de modulo faltante, que no dice nada de lo que paso de verdad.
    rd /s /q .venv >nul 2>nul
    pause
    exit /b 1
  )
  del "%TEMP%\plania_pip.log" >nul 2>nul
) else (
  echo  [1/2] Usando el entorno que ya estaba.
  call .venv\Scripts\activate.bat
)

echo  [2/2] Emitiendo y activando la licencia...
python INSTALADOR_OWNER\activar_owner.py
if errorlevel 1 (
  echo.
  echo  [X] La activacion fallo. Copia el mensaje de arriba si necesitas
  echo      soporte: ventas@plania.uy
  pause
  exit /b 1
)

if not exist data\erp_demo.db (
  echo  Generando la base demo para poder probar con datos...
  python data\generate_dataset.py --seed 42
)

echo.
choice /c SN /n /m "  Abrir Plania ahora? [S/N] "
if errorlevel 2 goto :fin
python packaging\plania_launcher.py

:fin
echo.
pause
endlocal
