"""
Plania · Control del instalador de Windows
==========================================
Revisa que el instalador esté bien armado sin necesidad de una máquina
Windows ni de Inno Setup.

    python3 packaging/verificar_instalador.py

No reemplaza probar el .exe en Windows: no compila nada ni ejecuta el
instalador. Lo que sí hace es cazar la clase de error que sólo aparece
cuando alguien ya lo descargó — que el instalador apunte a un archivo que no
existe, que le falte la opción de elegir carpeta, que no cree los accesos
directos, o que el ejecutable y el que instala el escritorio no coincidan.
Son errores baratos de cometer al editar y caros de descubrir tarde.

Devuelve código 1 si algo está mal, así sirve en CI y antes de publicar.
"""
from __future__ import annotations

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(RAIZ, "packaging", "instalador.iss")
SPEC = os.path.join(RAIZ, "packaging", "plania.spec")
PKG_ELECTRON = os.path.join(RAIZ, "desktop", "package.json")


def _leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8", errors="replace") as f:
        return f.read()


def _directivas(iss: str) -> dict:
    """Las directivas de [Setup], en minúscula, sin comentarios."""
    fuera = {}
    dentro = False
    for linea in iss.splitlines():
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == "[setup]"
            continue
        if not dentro or not limpia or limpia.startswith(";"):
            continue
        if "=" in limpia:
            clave, valor = limpia.split("=", 1)
            fuera[clave.strip().lower()] = valor.strip()
    return fuera


def _seccion(iss: str, nombre: str) -> list[str]:
    """Las líneas útiles de una sección, con las continuaciones (\\) unidas."""
    lineas, dentro = [], False
    for linea in iss.splitlines():
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == f"[{nombre.lower()}]"
            continue
        if not dentro or not limpia or limpia.startswith(";"):
            continue
        if lineas and lineas[-1].endswith("\\"):
            lineas[-1] = lineas[-1][:-1].rstrip() + " " + limpia
        else:
            lineas.append(limpia)
    return lineas


# Funciones de la API de Windows que el lenguaje de Inno Setup NO trae: si se
# usan, hay que declararlas con `external`. Olvidarse es un error de compilación
# que sólo aparece al correr `iscc` en Windows — o sea, tarde.
API_WINDOWS = ("GetDriveType", "GetDiskFreeSpaceEx", "SHGetFolderPath",
               "GetVolumeInformation", "GetLogicalDrives", "MoveFileEx")


def _codigo_pascal(iss: str) -> list[tuple[int, str]]:
    """Las líneas de la sección [Code], numeradas, sin comentarios."""
    salida, dentro = [], False
    for n, linea in enumerate(iss.splitlines(), start=1):
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == "[code]"
            continue
        if not dentro or limpia.startswith("//") or not limpia:
            continue
        salida.append((n, limpia))
    return salida


def controles_pascal(iss: str) -> list[tuple[bool, str, str]]:
    """Errores del script Pascal que se pueden ver sin compilar.

    No es un compilador: es una red para los tres tropiezos que de verdad
    pasan al editar este archivo desde fuera de Windows, donde no hay `iscc`
    para avisar.
    """
    lineas = _codigo_pascal(iss)
    r = []

    # 1. Literales de texto pegados sin '+'. En Pascal eso no existe —viene de
    #    la costumbre de Python, donde dos literales seguidos se concatenan
    #    solos— y es un error de compilación.
    pegados = []
    for i in range(len(lineas) - 1):
        actual, siguiente = lineas[i][1], lineas[i + 1][1]
        if actual.endswith("'") and siguiente.startswith("'"):
            pegados.append(lineas[i + 1][0])
    r.append((not pegados, "No hay literales de texto concatenados sin '+'",
              f"líneas {pegados}: en Pascal dos literales seguidos no se unen "
              "solos, hay que poner '+'"))

    # 2. API de Windows usada sin declarar.
    cuerpo = "\n".join(l for _, l in lineas)
    sin_declarar = [f for f in API_WINDOWS
                    if re.search(rf"\b{f}\s*\(", cuerpo)
                    and not re.search(rf"function\s+{f}\b[\s\S]{{0,200}}?external", cuerpo)]
    r.append((not sin_declarar, "Las funciones de la API de Windows están declaradas",
              f"{sin_declarar} se usan sin `external ...@kernel32.dll`: `iscc` "
              "no compila"))

    # 3. begin/end balanceados en el bloque completo.
    palabras = re.findall(r"\b(begin|end)\b", cuerpo, re.IGNORECASE)
    abiertos = sum(1 for p in palabras if p.lower() == "begin")
    cerrados = sum(1 for p in palabras if p.lower() == "end")
    r.append((abiertos == cerrados, "Los begin/end del script están balanceados",
              f"{abiertos} 'begin' contra {cerrados} 'end'"))

    # 4. Paréntesis balanceados fuera de los literales.
    sin_texto = re.sub(r"'[^']*'", "", cuerpo)
    r.append((sin_texto.count("(") == sin_texto.count(")"),
              "Los paréntesis del script están balanceados",
              f"{sin_texto.count('(')} '(' contra {sin_texto.count(')')} ')'"))

    return r


def controles() -> list[tuple[bool, str, str]]:
    """(pasa, título, detalle) por cada cosa comprobada."""
    iss = _leer(ISS)
    d = _directivas(iss)
    r: list[tuple[bool, str, str]] = []

    def ok(cond, titulo, detalle):
        r.append((bool(cond), titulo, detalle))

    # --- Elegir carpeta y disco -------------------------------------------
    ok(d.get("disabledirpage", "").lower() == "no",
       "Se puede elegir la carpeta de instalación",
       "DisableDirPage tiene que ser 'no' explícito: si se omite, Inno Setup "
       "decide solo si mostrar esa página y a veces no la muestra")
    ok("defaultdirname" in d,
       "Hay una carpeta propuesta por defecto",
       "sin DefaultDirName el instalador arranca sin ruta sugerida")
    for necesaria in ("NextButtonClick", "wpSelectDir", "GetDriveType",
                      "GetSpaceOnDisk64", "CarpetaEsEscribible"):
        ok(necesaria in iss,
           f"La carpeta elegida se valida ({necesaria})",
           "elegir un disco que no existe, sin espacio, de red o sin permiso "
           "tiene que avisar en el momento, no fallar a mitad de instalación")

    # --- Accesos directos --------------------------------------------------
    iconos = _seccion(iss, "Icons")
    ok(any("{autodesktop}" in i for i in iconos),
       "Crea el ícono del escritorio",
       "falta una entrada {autodesktop} en [Icons]")
    ok(any("{group}" in i and "uninstallexe" not in i for i in iconos),
       "Crea la entrada en el menú Inicio",
       "falta una entrada {group} en [Icons]")
    ok(any("uninstallexe" in i for i in iconos),
       "Ofrece desinstalar desde el menú Inicio",
       "falta el acceso directo al desinstalador")
    ok(all("WorkingDir:" in i for i in iconos if "uninstallexe" not in i),
       "Los accesos directos fijan su carpeta de trabajo",
       "sin WorkingDir el programa arranca en la carpeta desde donde se hizo "
       "clic y puede no encontrar sus recursos")
    ok(any("desktopicon" in t for t in _seccion(iss, "Tasks")),
       "El ícono del escritorio es opcional para el usuario",
       "falta la tarea 'desktopicon' en [Tasks]")

    # --- Coherencia con lo que se empaqueta --------------------------------
    exe = re.search(r'#define\s+AppExe\s+"([^"]+)"', iss)
    ok(exe is not None, "El instalador declara qué ejecutable instala", "falta #define AppExe")
    if exe:
        nombre = exe.group(1).replace(".exe", "")
        spec = _leer(SPEC)
        ok(f'name="{nombre}"' in spec or f"name='{nombre}'" in spec,
           f"El ejecutable del instalador ({exe.group(1)}) es el que compila PyInstaller",
           f"packaging/plania.spec no genera '{nombre}': el instalador crearía "
           "accesos directos a un archivo que no existe")

    origen = [i for i in _seccion(iss, "Files") if "Source:" in i]
    ok(bool(origen), "El instalador copia archivos", "la sección [Files] está vacía")
    for linea in origen:
        m = re.search(r'Source:\s*"([^"]+)"', linea)
        if not m:
            continue
        ruta = m.group(1).replace("\\", "/").replace("*", "")
        carpeta = os.path.normpath(os.path.join(RAIZ, "packaging", ruta))
        # dist/ lo genera el build; solo se avisa si la ruta no es la esperada
        ok(ruta.startswith("../dist/"),
           "Lo que se instala sale del build, no de una ruta suelta",
           f"Source apunta a {ruta}, que no viene de dist/")

    # --- Íconos que tienen que existir en el repo --------------------------
    for clave, para in (("setupiconfile", "el ícono del instalador"),
                        ("wizardimagefile", "el panel del asistente"),
                        ("wizardsmallimagefile", "el logo chico del asistente")):
        valor = d.get(clave, "")
        if valor:
            ruta = os.path.normpath(os.path.join(RAIZ, "packaging",
                                                 valor.replace("\\", "/")))
            ok(os.path.exists(ruta), f"Existe {para}", f"falta {valor}")

    # --- Instalador de Electron -------------------------------------------
    pkg = json.loads(_leer(PKG_ELECTRON))
    nsis = pkg.get("build", {}).get("nsis", {})
    ok(nsis.get("oneClick") is False,
       "El instalador Electron no es de un solo clic",
       "con oneClick el usuario no puede elegir carpeta")
    ok(nsis.get("allowToChangeInstallationDirectory") is True,
       "El instalador Electron deja elegir la carpeta",
       "allowToChangeInstallationDirectory tiene que estar en true")
    ok(nsis.get("createDesktopShortcut") is not False,
       "El instalador Electron crea el ícono del escritorio", "")
    ok(nsis.get("createStartMenuShortcut") is not False,
       "El instalador Electron crea la entrada del menú Inicio", "")
    icono = pkg.get("build", {}).get("win", {}).get("icon", "")
    if icono:
        ruta = os.path.normpath(os.path.join(RAIZ, "desktop", icono))
        ok(os.path.exists(ruta), "Existe el ícono del instalador Electron",
           f"falta {icono}")

    # --- Sintaxis del script del instalador --------------------------------
    r.extend(controles_pascal(iss))

    # --- Puertos -----------------------------------------------------------
    lanzador = _leer(os.path.join(RAIZ, "packaging", "plania_launcher.py"))
    main_js = _leer(os.path.join(RAIZ, "desktop", "main.js"))
    ok("PLANIA_PUERTO_ARCHIVO" in lanzador and "PLANIA_PUERTO_ARCHIVO" in main_js,
       "El puerto real se le informa a quien lanzó el programa",
       "sin ese aviso, si el puerto elegido se ocupa el lanzador se muda y la "
       "ventana queda esperando en el puerto viejo para siempre")
    # Sólo líneas ejecutables: el 8501 se nombra a propósito en un comentario
    # que explica por qué NO se usa, y eso no es un defecto.
    codigo = [l for l in lanzador.splitlines() if not l.strip().startswith("#")]
    ok(not any("8501" in l for l in codigo),
       "No se usa el puerto por defecto de Streamlit",
       "el 8501 lo ocupa cualquier otra aplicación Streamlit del usuario")

    # --- Todo en el disco que el usuario elige ------------------------------
    config_py = _leer(os.path.join(RAIZ, "plania", "config.py"))
    ok('"frozen"' in config_py and "_carpeta_junto_al_exe" in config_py,
       "La licencia y la configuración quedan en el disco elegido al instalar",
       "sin esto, plania.config vuelve a guardar siempre en ~/.plania (el "
       "perfil de Windows, típicamente C:) sin importar dónde se instaló")
    ok("_migrar_si_hace_falta" in config_py,
       "Quien actualiza desde una versión anterior no pierde su licencia",
       "falta la migración única de ~/.plania a la carpeta junto al .exe")
    ok('"frozen"' in lanzador and "datos" in lanzador,
       "Los logs también quedan en el disco elegido al instalar",
       "el lanzador tiene que intentar 'datos/logs' junto al .exe antes de "
       "caer a LOCALAPPDATA")
    sin_comentarios = "\n".join(
        l for l in "\n".join(_seccion(iss, "UninstallDelete")).splitlines()
        if not l.strip().startswith(";"))
    ok(r"{app}\datos" not in sin_comentarios,
       "Desinstalar no borra la carpeta donde vive la licencia",
       r"si [UninstallDelete] borra {app}\datos, reinstalar pide activar de nuevo")

    return r


def main() -> int:
    resultados = controles()
    fallan = [x for x in resultados if not x[0]]
    for pasa, titulo, detalle in resultados:
        print(f"  [{'OK' if pasa else '!!'}] {titulo}")
        if not pasa and detalle:
            print(f"         {detalle}")
    print(f"\n  {len(resultados) - len(fallan)} de {len(resultados)} controles en verde")
    if fallan:
        print("  El instalador NO está listo para publicar.")
        return 1
    print("  El instalador está coherente con lo que se empaqueta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
