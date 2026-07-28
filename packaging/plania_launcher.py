"""
Plania · Lanzador del programa standalone (Windows)
=====================================================
Punto de entrada del ejecutable empaquetado con PyInstaller. Arranca el
dashboard Streamlit embebido (sin necesidad de tener Python instalado) y abre
el navegador. Es lo que se ejecuta cuando el usuario hace doble clic en el
acceso directo "Plania" que crea el instalador.
"""
import os
import socket
import sys
import threading
import time
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
    print(f"[Plania] Servidor en http://localhost:{port}  "
          f"(si el navegador no se abre solo, copiá esa dirección)")
    # Que los import del proyecto (plania, data) resuelvan.
    if base not in sys.path:
        sys.path.insert(0, base)

    # Con PLANIA_NO_BROWSER=1 no se abre navegador: es el modo en que el
    # escritorio Electron (desktop/) embebe este mismo server en su ventana.
    if not os.environ.get("PLANIA_NO_BROWSER"):
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
    main()
