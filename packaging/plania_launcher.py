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


def _puerto_libre() -> int:
    """Elige un puerto libre para no chocar con otros programas (p. ej. otra
    app en 8501). Prueba unos puertos propios de Plania y, si están ocupados,
    pide uno efímero al sistema operativo."""
    for p in (8531, 8542, 8553, 8564, 8575):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
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
    # Puerto: respeta el que el usuario fije en STREAMLIT_SERVER_PORT; si no,
    # elige uno libre para no chocar con otros programas (evita el 8501 típico).
    port = os.environ.get("STREAMLIT_SERVER_PORT") or str(_puerto_libre())
    os.environ["STREAMLIT_SERVER_PORT"] = port
    # Que los import del proyecto (plania, data) resuelvan.
    if base not in sys.path:
        sys.path.insert(0, base)

    threading.Thread(target=_abrir_navegador,
                     args=(f"http://localhost:{port}",), daemon=True).start()

    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", app_path,
                f"--server.port={port}",
                "--server.headless=true",
                "--global.developmentMode=false",
                "--browser.gatherUsageStats=false"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
