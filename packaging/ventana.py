# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Ventana propia del programa (Windows)
==============================================
Hace que el ejecutable abra **una ventana de aplicación**, no una pestaña
del navegador con la barra de direcciones a la vista. Para el que compró un
programa, "se me abrió el Chrome" es indistinguible de "esto es una página
web" — y lo que compró es un programa.

Cómo, sin agregar dependencias al instalador: los navegadores basados en
Chromium tienen el modo `--app`, que abre una ventana sin barra de
direcciones, sin pestañas, sin menú, con su propio ícono en la barra de
tareas. Es lo mismo que usan las aplicaciones instaladas desde el navegador.

Por qué así y no con una biblioteca de ventana nativa (pywebview y
similares):

  - **No suma nada al instalador.** Edge viene en todo Windows 10 y 11; no
    hay nada que empaquetar ni ningún runtime que pueda faltar en la máquina
    del cliente.
  - **No hay dependencia que pueda no compilar.** Una biblioteca de ventana
    agrega binarios que hay que construir para cada plataforma y que pueden
    fallar en la máquina de quien arma la release.
  - **Degrada bien.** Si no hay ningún Chromium instalado, se abre el
    navegador por defecto como siempre: peor experiencia, pero funciona.

El perfil va aparte, en la carpeta de datos de Plania. Sin `--user-data-dir`
propio la ventana se engancha a la sesión de navegación del usuario: hereda
sus extensiones, y cerrarla puede arrastrar sus otras ventanas.
"""
from __future__ import annotations

import os
import subprocess
import sys

# Rutas donde Windows instala los navegadores basados en Chromium, en orden
# de preferencia. Edge primero porque es el único que está garantizado.
_WINDOWS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
]
# En Linux y macOS esto sirve para desarrollar y para los tests; el programa
# que se vende es el de Windows.
_OTROS = ["microsoft-edge", "google-chrome", "chromium", "chromium-browser",
          "brave-browser"]

VENTANA = (1280, 860)


def buscar_navegador() -> str | None:
    """Ruta de un navegador que soporte `--app`, o None si no hay ninguno."""
    if os.name == "nt":
        for patron in _WINDOWS:
            ruta = os.path.expandvars(patron)
            if "%" not in ruta and os.path.isfile(ruta):
                return ruta
        return None

    from shutil import which
    for nombre in _OTROS:
        ruta = which(nombre)
        if ruta:
            return ruta
    # El contenedor de CI trae Chromium acá, sin estar en el PATH.
    suelto = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
    return suelto if os.path.isfile(suelto) else None


def comando(navegador: str, url: str, perfil: str) -> list[str]:
    """Los argumentos con los que se abre la ventana.

    Se arma aparte de lanzarlo para poder probarlo sin abrir nada.
    """
    ancho, alto = VENTANA
    return [
        navegador,
        f"--app={url}",
        f"--user-data-dir={perfil}",
        f"--window-size={ancho},{alto}",
        # Sin esto la ventana arranca con el globo de "restaurar pestañas" o
        # con el aviso de sesión anterior si el programa se cerró mal.
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        # Nada de esto es un navegador de uso general: no hay por qué dejarlo
        # actualizarse solo ni reportar métricas de uso del cliente.
        "--disable-background-networking",
        "--disable-features=Translate,TranslateUI",
    ]


def carpeta_perfil() -> str:
    """Perfil propio, dentro de la carpeta de datos de Plania."""
    try:
        from plania import config as pconfig
        base = pconfig.CONFIG_DIR
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".plania")
    perfil = os.path.join(base, "ventana")
    os.makedirs(perfil, exist_ok=True)
    return perfil


def ocultar_consola() -> bool:
    """Esconde la ventana negra de consola, si la hay.

    Se hace en tiempo de ejecución y no compilando sin consola, a propósito:
    si la ventana de aplicación no llega a abrirse, la consola queda visible
    y sigue siendo la forma de ver el error y de cerrar el programa. Sin
    consola y sin ventana, el usuario no tendría ni lo uno ni lo otro.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
            return True
    except Exception:
        pass
    return False


def abrir(url: str) -> subprocess.Popen | None:
    """Abre la ventana del programa. Devuelve el proceso, o None si no pudo.

    None no es un error: significa "no hay con qué abrir una ventana acá", y
    quien llama tiene que caer al navegador por defecto.
    """
    navegador = buscar_navegador()
    if not navegador:
        return None
    try:
        return subprocess.Popen(
            comando(navegador, url, carpeta_perfil()),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            # Que cerrar Plania no deje la ventana huérfana ni al revés.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception as e:
        print(f"[Plania] No pude abrir la ventana del programa: {e}")
        return None
