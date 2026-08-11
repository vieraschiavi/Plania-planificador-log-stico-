"""
Plania · El panel del dueño, sobre el Plania que ya tenés instalado
====================================================================
Arma `dist/Plania_Owner_Junto_Al_Exe.zip`: se descomprime **adentro de la
carpeta donde está instalado Plania**, se hace doble clic en
`ACTIVAR_OWNER.bat`, y esa copia queda con el panel del dueño además del
producto. Sin compilar nada, sin Python aparte, sin clave.

    python3 packaging/armar_owner_junto_al_exe.py

Por qué esto no es "un .bat suelto" y no puede serlo
-----------------------------------------------------
Porque el panel **no está adentro del ejecutable del cliente**. No es que esté
escondido o apagado: `packaging/proteger_codigo.py` saca `app/owner.py`,
`plania/owner.py`, `plania/negocio.py`, `plania/contenido.py` y
`plania/verificacion.py` del build, siempre, sin excepción ni edición. Es a
propósito: si viajaran, la facturación, los clientes y el modelo financiero
estarían en el disco de cada cliente, a un archivo de distancia.

Así que ningún archivo suelto —ni un `.bat`, ni un "sello" de 19 bytes— puede
"desbloquear" el panel en un Plania instalado: no hay nada que desbloquear. Lo
único que puede funcionar es lo que hace este ZIP: **traer el código consigo**
y dejarlo al lado del motor.

Por qué funciona una vez que el código está ahí
------------------------------------------------
El programa instalado ya sabe abrir el panel: `packaging/plania_launcher.py`
levanta `app/owner.py` en vez de `app/app.py` cuando encuentra
`PLANIA_PANEL=owner`. Y resuelve los import contra la carpeta del bundle
(`sys.path.insert(0, base)`), que es la misma donde viven los módulos
compilados. Un `.py` dejado ahí se importa igual que ellos.

O sea: el ejecutable instalado no necesita ningún cambio. Le falta el código
del panel, y esto se lo pone.

Esto NO se publica
------------------
El ZIP lleva adentro el modelo financiero en código fuente. Sale con el
prefijo `Plania_Owner`, que es el que corta la publicación en el workflow y el
que ignora `.gitignore`. Es para vos, para tu máquina.
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "packaging"))

from proteger_codigo import MODULOS_SOLO_OWNER  # noqa: E402

DESTINO = os.path.join(RAIZ, "dist", "Plania_Owner_Junto_Al_Exe.zip")

# El .bat que se ejecuta en la carpeta del programa instalado.
#
# Todo lo que hace es copiar archivos y crear dos accesos directos. No toca el
# ejecutable, no parchea nada, no escribe en el registro: si algo sale mal, se
# borran los archivos que dejó y queda como estaba.
ACTIVAR = r"""@echo off
rem ============================================================
rem  Plania Owner - activar el panel del dueno sobre este Plania
rem
rem  QUE HACE: copia el codigo del panel adentro de esta misma
rem  carpeta y deja dos accesos directos para abrirlo. El Plania
rem  normal sigue funcionando igual, con su propio acceso.
rem
rem  NO LO CORRAS EN LA MAQUINA DE UN CLIENTE: deja el modelo
rem  financiero, la facturacion y los clientes en ese disco.
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Plania Owner - activar

echo.
echo  === Panel del dueno de Plania ===
echo.

rem 1. Comprobar que esto se descomprimio DONDE va.
if not exist "Plania.exe" (
  echo  [X] No encuentro Plania.exe en esta carpeta.
  echo.
  echo      Este archivo va adentro de la carpeta donde instalaste
  echo      Plania. Para encontrarla: boton derecho en el acceso
  echo      directo de Plania ^> Abrir ubicacion del archivo.
  echo.
  pause
  exit /b 1
)
if not exist "_internal\" (
  echo  [X] Encontre Plania.exe pero no la carpeta _internal.
  echo      Esta no parece una instalacion completa de Plania.
  echo.
  pause
  exit /b 1
)
if not exist "owner\" (
  echo  [X] Falta la carpeta owner\ que venia en el ZIP.
  echo      Descomprimi el ZIP entero, no solo este .bat.
  echo.
  pause
  exit /b 1
)

rem 2. Copiar el codigo del panel al lado del motor. /Y para que
rem    volver a correrlo actualice en vez de preguntar por cada uno.
echo  Copiando el panel...
xcopy "owner\app\*"    "_internal\app\"    /Y /Q >nul
if errorlevel 1 goto :fallo
xcopy "owner\plania\*" "_internal\plania\" /Y /Q >nul
if errorlevel 1 goto :fallo

rem 3. Lanzador propio. Es lo unico que cambia respecto de abrir
rem    Plania normal: la variable que le dice al programa cual de
rem    las dos pantallas levantar.
> "Plania Owner.bat" echo @echo off
>>"Plania Owner.bat" echo cd /d "%%~dp0"
>>"Plania Owner.bat" echo set PLANIA_PANEL=owner
>>"Plania Owner.bat" echo start "" "%%~dp0Plania.exe"

rem 4. Accesos directos, con el icono de Plania. Se arman con
rem    PowerShell porque batch no sabe crear un .lnk.
echo  Creando accesos directos...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell;" ^
  "foreach ($d in @($s.SpecialFolders('Desktop'), $s.SpecialFolders('Programs'))) {" ^
  "  $l = $s.CreateShortcut((Join-Path $d 'Plania Owner.lnk'));" ^
  "  $l.TargetPath = (Join-Path '%CD%' 'Plania Owner.bat');" ^
  "  $l.WorkingDirectory = '%CD%';" ^
  "  $l.IconLocation = (Join-Path '%CD%' 'Plania.exe');" ^
  "  $l.Description = 'Panel del dueno: facturacion, clientes y modelo financiero';" ^
  "  $l.Save() }" 2>nul
if errorlevel 1 (
  echo  [!] No pude crear los accesos directos, pero el panel quedo
  echo      activado igual: abrilo con "Plania Owner.bat" de esta carpeta.
)

echo.
echo  [OK] Listo. Tenes dos programas en esta carpeta:
echo.
echo       Plania.exe        el producto, como siempre
echo       Plania Owner.bat  el panel del dueno (sin clave)
echo.
echo  El acceso directo "Plania Owner" quedo en el escritorio y en
echo  el menu Inicio.
echo.
echo  Para volver atras: borra "Plania Owner.bat" y los archivos que
echo  dejo este script (los lista DESACTIVAR_OWNER.bat).
echo.
pause
exit /b 0

:fallo
echo.
echo  [X] No pude copiar los archivos. Suele ser porque Plania esta
echo      abierto o porque esta carpeta necesita permisos de
echo      administrador (boton derecho ^> Ejecutar como administrador).
echo.
pause
exit /b 1
"""

# Y la vuelta atrás. Un script que instala sin traer cómo deshacerlo obliga a
# borrar a mano archivos sueltos adentro de _internal\ — y a esa altura ya
# nadie se acuerda cuáles eran.
DESACTIVAR = r"""@echo off
rem ============================================================
rem  Plania Owner - sacar el panel del dueno de esta instalacion
rem  Deja el Plania normal intacto.
rem ============================================================
setlocal
cd /d "%~dp0"
title Plania Owner - desactivar

echo.
echo  Sacando el panel del dueno de esta carpeta...
echo.

__BORRADOS__

del /q "Plania Owner.bat" 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell;" ^
  "foreach ($d in @($s.SpecialFolders('Desktop'), $s.SpecialFolders('Programs'))) {" ^
  "  Remove-Item (Join-Path $d 'Plania Owner.lnk') -ErrorAction SilentlyContinue }" 2>nul

echo.
echo  [OK] Listo. Plania sigue instalado y funcionando igual.
echo.
pause
"""

LEEME = """Plania Owner · el panel del dueño sobre tu Plania instalado
===========================================================

CÓMO SE USA
-----------
1. Abrí la carpeta donde está instalado Plania.
   (Botón derecho en el acceso directo de Plania → Abrir ubicación del
   archivo. Suele ser C:\\Program Files\\Plania.)
2. Copiá ahí adentro TODO lo que trae este ZIP: `ACTIVAR_OWNER.bat`,
   `DESACTIVAR_OWNER.bat` y la carpeta `owner\\`.
3. Doble clic en `ACTIVAR_OWNER.bat`.

Listo. Te queda un acceso directo "Plania Owner" en el escritorio y en el
menú Inicio. Abre sin pedir ninguna clave.

El Plania normal sigue funcionando igual, con su propio acceso directo. Son
dos pantallas del mismo programa, no dos programas.

PARA VOLVER ATRÁS
-----------------
Doble clic en `DESACTIVAR_OWNER.bat`. Borra el panel y sus accesos directos,
y deja Plania como estaba.

POR QUÉ NO ALCANZABA CON UN .BAT SOLO
--------------------------------------
Porque el panel no está adentro del Plania que instalaste. No está escondido
ni apagado: el código del panel se saca del ejecutable en el momento de
construirlo, siempre. Si viajara adentro, tu facturación, tus clientes y tu
modelo financiero estarían en el disco de cada cliente que instala Plania, a
un archivo de distancia de que alguien los abra.

Por eso este ZIP trae el código consigo. Es lo único que puede funcionar, y
es también la razón por la que este archivo es tuyo y no se publica en
ningún lado.

NO LO CORRAS EN LA MÁQUINA DE UN CLIENTE
-----------------------------------------
Deja el modelo financiero del producto —costos, márgenes, precios— y la
facturación en ese disco, en código fuente legible.
"""


def archivos_del_panel() -> list[str]:
    """Los módulos que el panel necesita y el producto no lleva.

    Sale de MODULOS_SOLO_OWNER, la misma lista que usa proteger_codigo.py para
    sacarlos del build: si algún día se suma un módulo del dueño, entra acá
    solo. Lo contrario —una lista propia— es exactamente lo que hizo que el
    .exe y el ZIP del .bat discreparan.
    """
    rutas = []
    for carpeta, archivos in MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            rel = f"{carpeta}/{archivo}"
            if os.path.exists(os.path.join(RAIZ, rel)):
                rutas.append(rel)
    return sorted(rutas)


def _desactivar(rutas: list[str]) -> str:
    """El .bat de vuelta atrás, con la lista real de archivos a borrar."""
    lineas = [f'del /q "_internal\\{r.replace("/", chr(92))}" 2>nul' for r in rutas]
    return DESACTIVAR.replace("__BORRADOS__", "\n".join(lineas))


def armar(destino: str = DESTINO) -> str:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    rutas = archivos_del_panel()
    if not rutas:
        raise SystemExit("No encontré los módulos del panel del dueño.")

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ACTIVAR_OWNER.bat", ACTIVAR.replace("\n", "\r\n"))
        z.writestr("DESACTIVAR_OWNER.bat", _desactivar(rutas).replace("\n", "\r\n"))
        z.writestr("LEEME.txt", LEEME.replace("\n", "\r\n"))
        for rel in rutas:
            z.write(os.path.join(RAIZ, rel), f"owner/{rel}")

    kb = os.path.getsize(destino) / 1024
    print(f"[owner] {destino}  ({len(rutas) + 3} archivos, {kb:.0f} KB)")
    print(f"[owner] lleva: {', '.join(rutas)}")
    print("[owner] ! Es tuyo: lleva el modelo financiero en código fuente. "
          "No se publica ni se corre en la máquina de un cliente.")
    return destino


def verificar(zip_path: str) -> list[str]:
    """Revisa el ZIP ya armado. Lista vacía = está bien."""
    problemas = []
    if not os.path.exists(zip_path):
        return [f"no existe {zip_path}"]
    with zipfile.ZipFile(zip_path) as z:
        nombres = z.namelist()
        activar = z.read("ACTIVAR_OWNER.bat").decode("utf-8", "replace") \
            if "ACTIVAR_OWNER.bat" in nombres else ""

    for necesario in ("ACTIVAR_OWNER.bat", "DESACTIVAR_OWNER.bat", "LEEME.txt"):
        if necesario not in nombres:
            problemas.append(f"falta {necesario}")

    # Sin los módulos, el .bat copiaría nada y el panel no abriría: el ZIP
    # tiene que traer el código, que es su única razón de ser.
    for rel in archivos_del_panel():
        if f"owner/{rel}" not in nombres:
            problemas.append(f"falta el módulo {rel}: el panel no abriría")

    # El .bat tiene que comprobar dónde se está ejecutando antes de copiar:
    # corrido en la carpeta equivocada, dejaría archivos sueltos en cualquier
    # lado sin decir nada.
    if 'if not exist "Plania.exe"' not in activar:
        problemas.append("el .bat no comprueba que esté en la carpeta de Plania")
    if "PLANIA_PANEL=owner" not in activar:
        problemas.append("el lanzador no fija PLANIA_PANEL=owner: abriría el producto")

    if not problemas:
        print(f"[owner] {zip_path}: trae el panel completo y el .bat comprueba "
              f"dónde se ejecuta.")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description="Panel del dueño sobre un Plania instalado")
    ap.add_argument("--verificar", metavar="ZIP", nargs="?", const=DESTINO)
    ap.add_argument("--destino", default=DESTINO)
    args = ap.parse_args()

    objetivo = args.verificar or armar(args.destino)
    problemas = verificar(objetivo)
    for p in problemas:
        print(f"  [!!] {p}")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
