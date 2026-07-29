"""
Plania · Lanzador del programa standalone (Windows)
=====================================================
Punto de entrada del ejecutable empaquetado con PyInstaller. Arranca el
dashboard Streamlit embebido (sin necesidad de tener Python instalado) y abre
el navegador. Es lo que se ejecuta cuando el usuario hace doble clic en el
acceso directo "Plania" que crea el instalador.

Este lanzador corre en dos contextos distintos, y se comporta distinto en
cada uno (ver `PLANIA_NO_BROWSER` más abajo):

  - **Standalone** (instalador Inno Setup / ZIP portable): el .exe se compila
    CON consola (`console=True` en packaging/plania.spec). Es a propósito:
    esa ventana es hoy la única forma que tiene el usuario de cerrar el
    programa — cerrarla termina el proceso. Ocultarla sin dar otra forma de
    salir (una bandeja del sistema, por ejemplo) cambiaría "cómo cierro
    esto" por "no sé cómo cerrar esto", que es peor que una consola visible.
    Lo que sí se puede mejorar sin ese riesgo: que la consola muestre un
    encabezado con marca en vez del log crudo de Streamlit como primera
    impresión, y que un error fatal se vea antes de que la ventana se
    cierre sola.
  - **Empotrado en Electron** (`desktop/`, con `PLANIA_NO_BROWSER=1`): ahí el
    splash de React ya es la señal visual de que algo está pasando, y
    Electron mata el proceso al cerrar su ventana — no hace falta consola
    propia. `desktop/main.js` lanza este mismo .exe con `windowsHide: true`
    para que, aun compilado con consola, no aparezca una ventana negra
    aparte flotando detrás de la ventana de Electron.

En los dos casos la salida también se duplica a un archivo de log: una
consola que se cerró hace rato no sirve para diagnosticar un problema que el
usuario reporta después.
"""
import datetime
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser


def _base_dir() -> str:
    """Carpeta con los recursos (dentro del bundle PyInstaller o del repo)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Puertos propios de Plania. NO se usa el 8501: es el puerto por defecto de
# Streamlit, así que lo tiene ocupado cualquier otra aplicación hecha con
# Streamlit que el usuario haya dejado abierta — y entonces Plania abriría esa.
PUERTOS = (8531, 8542, 8553, 8564, 8575)


def _ocupado(puerto: int) -> bool:
    """Si hay algo escuchando en el puerto.

    Se comprueba conectándose, no intentando reservarlo. En Windows un bind
    con SO_REUSEADDR tiene éxito aunque otro proceso esté escuchando ahí
    —a diferencia de Linux—, así que la prueba por bind daba puertos ocupados
    por libres y el usuario terminaba viendo el otro programa.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.35)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def _carpeta_logs() -> str:
    """Carpeta de logs, en la zona de datos del usuario (no en Archivos de
    programa, donde el programa instalado no tiene permiso de escritura)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    carpeta = os.path.join(base, "Plania", "logs")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


class _Tee:
    """Escribe en la consola (si hay) y en el archivo de log a la vez.

    `sys.stdout` puede no comportarse como un archivo real en un .exe
    empaquetado (a veces es `None`, sobre todo en variantes sin consola), así
    que cada escritura a la consola va protegida: si falla, igual queda en
    el log, que es lo que importa para poder diagnosticar algo después.
    """

    def __init__(self, consola, archivo):
        self._consola = consola
        self._archivo = archivo

    def write(self, texto):
        if self._consola is not None:
            try:
                self._consola.write(texto)
            except Exception:
                pass
        self._archivo.write(texto)

    def flush(self):
        if self._consola is not None:
            try:
                self._consola.flush()
            except Exception:
                pass
        self._archivo.flush()

    def isatty(self):
        return False


def _iniciar_log() -> str:
    """Duplica stdout/stderr a un archivo. Devuelve la ruta del log."""
    ruta = os.path.join(_carpeta_logs(), "plania.log")
    archivo = open(ruta, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = _Tee(sys.stdout, archivo)
    sys.stderr = _Tee(sys.stderr, archivo)
    print(f"\n=== Plania arrancó · {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")
    return ruta


def _banner(puerto, electron: bool) -> None:
    """Encabezado con marca antes del log de Streamlit. En modo standalone
    también recuerda que cerrar esta ventana cierra el programa — es la
    única forma de salir que hay hoy, así que conviene decirlo."""
    print("=" * 60)
    print("  Plania")
    print(f"  http://localhost:{puerto}")
    if not electron:
        print("  Si el navegador no se abre solo, copiá esa dirección.")
        print("  Para cerrar el programa, cerrá esta ventana.")
    print("=" * 60, flush=True)


def _puerto_libre() -> int:
    """Un puerto donde nadie esté escuchando."""
    for p in PUERTOS:
        if not _ocupado(p):
            return p
    # Todos ocupados: que el sistema operativo asigne uno efímero.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _abrir_navegador(url: str):
    # Espera a que el server levante y abre el navegador una sola vez.
    for _ in range(60):
        time.sleep(0.5)
        try:
            import urllib.request
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            continue
    webbrowser.open(url)


def main():
    base = _base_dir()
    app_path = os.path.join(base, "app", "app.py")
    electron = bool(os.environ.get("PLANIA_NO_BROWSER"))

    # Config de Streamlit para modo "programa" (no dev, no telemetría).
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    # Solo la máquina del usuario. Por defecto Streamlit escucha en 0.0.0.0 y
    # anuncia una "Network URL": en una oficina, cualquiera en la misma red
    # podría abrir el Plania de otro y ver sus ventas, márgenes y clientes.
    # Un programa de escritorio no tiene por qué exponer nada a la red.
    os.environ.setdefault("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")
    # Puerto: respeta el que el usuario fije en STREAMLIT_SERVER_PORT; si no,
    # elige uno libre para no chocar con otros programas (evita el 8501 típico).
    pedido = os.environ.get("STREAMLIT_SERVER_PORT")
    if pedido and pedido.isdigit() and _ocupado(int(pedido)):
        # Seguir adelante con un puerto ocupado termina en que el usuario ve
        # el otro programa y cree que Plania está roto. Mejor avisar y mover.
        libre = _puerto_libre()
        print(f"[Plania] El puerto {pedido} ya está ocupado por otro programa. "
              f"Uso el {libre}.")
        pedido = str(libre)
    port = pedido or str(_puerto_libre())
    os.environ["STREAMLIT_SERVER_PORT"] = port
    # Que los import del proyecto (plania, data) resuelvan.
    if base not in sys.path:
        sys.path.insert(0, base)

    _banner(port, electron)

    # Con PLANIA_NO_BROWSER=1 no se abre navegador: es el modo en que el
    # escritorio Electron (desktop/) embebe este mismo server en su ventana.
    if not electron:
        threading.Thread(target=_abrir_navegador,
                         args=(f"http://localhost:{port}",), daemon=True).start()

    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", app_path,
                f"--server.port={port}",
                f"--server.address={os.environ['STREAMLIT_SERVER_ADDRESS']}",
                "--server.headless=true",
                "--global.developmentMode=false",
                "--browser.gatherUsageStats=false"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    ruta_log = _iniciar_log()
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print(traceback.format_exc())
        # Que la ventana no se cierre sola tapando el error: en modo
        # standalone hay consola para leerlo, pero un .exe frozen que termina
        # con una excepción no capturada suele cerrar la ventana igual de
        # rápido que si hubiera terminado bien.
        if not os.environ.get("PLANIA_NO_BROWSER") and sys.stdin and sys.stdin.isatty():
            try:
                input("\nPlania no pudo iniciarse. El detalle quedó en "
                     f"{ruta_log}\nPresioná Enter para cerrar…")
            except Exception:
                pass
        raise
