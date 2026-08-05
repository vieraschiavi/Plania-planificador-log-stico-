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


def _escribible(carpeta: str) -> bool:
    try:
        os.makedirs(carpeta, exist_ok=True)
        prueba = os.path.join(carpeta, ".prueba_escritura")
        with open(prueba, "w") as f:
            f.write("x")
        os.remove(prueba)
        return True
    except Exception:
        return False


def _carpeta_logs() -> str:
    """Carpeta de logs.

    Primero se intenta `datos/logs` al lado del .exe: así, si el usuario
    instaló Plania en D:, los logs quedan en D: también, en vez de forzarlo a
    tener espacio en el disco del perfil de Windows (típicamente C:) sin
    importar dónde instaló el programa. Es la misma idea y la misma lógica
    que `plania.config._carpeta_junto_al_exe()` — se duplica acá en vez de
    importar el paquete `plania` porque este log arranca ANTES que cualquier
    otra cosa, justamente para poder registrar un error si algo más adelante
    (incluida la importación de `plania`) falla.

    Si esa carpeta no es escribible —instalado en Archivos de programa y
    corriendo sin permisos de escritura ahí, por ejemplo— se cae a
    `%LOCALAPPDATA%`, que sí lo es siempre para el usuario actual.
    """
    if getattr(sys, "frozen", False):
        junto_al_exe = os.path.join(os.path.dirname(sys.executable), "datos", "logs")
        if _escribible(junto_al_exe):
            return junto_al_exe
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


def _reservar(puerto: int):
    """Toma el puerto de verdad y devuelve el socket, o None si está tomado.

    Comprobar que un puerto está libre y después dejar que Streamlit lo tome
    deja una ventana en el medio: entre las dos cosas hay que publicar el
    puerto, importar la configuración e imprimir el encabezado, y en todo ese
    rato otro programa se lo puede llevar. Cuando pasa, Streamlit muere con
    "Port is not available" y el usuario ve un error por algo que no hizo.

    Reservándolo primero, la ventana queda reducida al instante entre cerrar
    este socket y el bind de Streamlit. Lo que pueda pasar igual en ese
    instante lo cubre el reintento de `_servir()`.

    A propósito SIN SO_REUSEADDR: en Windows esa opción permite hacer bind
    aunque otro proceso esté escuchando ahí, que es justo lo que se quiere
    detectar.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", puerto))
        return s
    except OSError:
        s.close()
        return None


def _candidatos():
    """Los puertos a probar, en orden, terminando en uno efímero del sistema.

    El efímero es la red de seguridad: si los cinco propios están ocupados
    —cosa rara, pero pasa con varias instancias abiertas— igual arranca en
    vez de darle al usuario un error que no puede resolver.
    """
    for p in PUERTOS:
        yield p
    yield 0  # 0 = que lo elija el sistema operativo


def _publicar_puerto(puerto: str) -> None:
    """Deja escrito en qué puerto quedó Plania, para quien lo haya lanzado.

    Hace falta porque el puerto no se puede acordar de antemano: entre que
    quien lanza comprueba que un puerto está libre y que Streamlit lo toma,
    otro programa se lo puede llevar, y entonces el lanzador se muda a otro.
    Sin este aviso, quien lanzó se queda esperando en el puerto viejo — que es
    exactamente lo que le pasaba a la ventana de Electron: splash para
    siempre y un "el servidor no levantó" al minuto.

    Se escribe primero en un archivo aparte y después se renombra, para que
    quien lo lea nunca encuentre medio número escrito.
    """
    destino = os.environ.get("PLANIA_PUERTO_ARCHIVO")
    if not destino:
        return
    try:
        os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
        parcial = destino + ".parcial"
        with open(parcial, "w", encoding="utf-8") as f:
            f.write(str(puerto))
        os.replace(parcial, destino)
    except Exception as e:
        # Que no poder avisar no impida arrancar: quien lanzó tiene su propio
        # tiempo de espera y va a mostrar un error entendible.
        print(f"[Plania] No pude escribir {destino}: {e}")


def _abrir_navegador(url: str, cancelar: threading.Event):
    """Espera a que el server levante y abre la ventana del programa.

    `cancelar` existe por el reintento de puerto: si Streamlit no llegó a
    tomar el puerto y hay que mudarse a otro, este hilo ya está esperando en
    la dirección vieja. Sin la señal, abriría el navegador en el puerto que
    se llevó OTRO programa — o sea, le mostraría al usuario esa aplicación
    creyendo que es Plania.

    Se abre una **ventana de aplicación** (ver packaging/ventana.py), no una
    pestaña del navegador: lo que el cliente compró es un programa, y "se me
    abrió el Chrome con una barra de direcciones" se lee como una página web.
    Si en la máquina no hay ningún navegador que soporte el modo ventana, se
    cae al navegador por defecto — peor, pero funciona.

    Cuando el usuario cierra la ventana se termina el programa. Es lo que
    espera de una aplicación de escritorio: sin esto, el server quedaría
    corriendo invisible y el próximo arranque se mudaría de puerto.
    """
    for _ in range(60):
        if cancelar.wait(0.5):
            return
        try:
            import urllib.request
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            continue
    if cancelar.is_set():
        return

    if os.environ.get("PLANIA_NAVEGADOR"):
        webbrowser.open(url)
        return

    try:
        import ventana
    except ImportError:
        from packaging import ventana   # type: ignore[no-redef]

    proceso = ventana.abrir(url)
    if proceso is None:
        print("[Plania] Sin navegador para abrir ventana propia: "
              "se abre el navegador por defecto.")
        webbrowser.open(url)
        return

    ventana.ocultar_consola()
    proceso.wait()
    print("[Plania] Ventana cerrada. Cerrando Plania.")
    # os._exit y no sys.exit: esto corre en un hilo secundario, y sys.exit
    # ahí sólo termina el hilo — el server de Streamlit seguiría corriendo.
    sys.stdout.flush()
    os._exit(0)


def _pantalla(base: str) -> str:
    """Qué pantalla levanta este ejecutable.

    Son dos programas distintos y se empaquetan por separado:

      · **Plania** — el producto. Es el mismo archivo para el dueño y para
        cualquiera que lo compre; no existe una versión "del dueño" del
        producto. Si existiera, el dueño estaría probando algo que ningún
        cliente tiene, y los problemas que reporte un cliente no se
        reproducirían en su máquina.
      · **Plania Owner** — el panel del negocio (facturación, clientes,
        modelo financiero). Se instala solo en la máquina del dueño.

    Comparten este lanzador porque el problema que resuelve —buscar un puerto
    libre de verdad, no exponerse a la red, dejar log— es idéntico en los dos.
    Cuál de las dos pantallas se levanta lo fija el .spec al empaquetar.
    """
    if os.environ.get("PLANIA_PANEL") == "owner":
        return os.path.join(base, "app", "owner.py")
    return os.path.join(base, "app", "app.py")


def main():
    base = _base_dir()
    app_path = _pantalla(base)
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
    # Puerto: se respeta el que el usuario fije en STREAMLIT_SERVER_PORT como
    # PREFERIDO, no como obligatorio. Si está ocupado, `_servir` se muda solo
    # y lo avisa — seguir adelante con un puerto tomado termina en que el
    # usuario ve el otro programa y cree que Plania está roto.
    pedido = os.environ.get("STREAMLIT_SERVER_PORT", "")
    preferido = int(pedido) if pedido.isdigit() else PUERTOS[0]

    # Que los import del proyecto (plania, data) resuelvan.
    if base not in sys.path:
        sys.path.insert(0, base)

    try:
        # Se informa acá, no se decide: la resolución real vive en
        # plania.config._resolver_config_dir(). Esto es sólo para que, si
        # alguien reporta "instalé en D: pero no sé si quedó ahí", la
        # respuesta esté en el log en vez de tener que ir a comprobarlo.
        from plania import config as _pconfig
        print(f"[Plania] Datos (licencia, configuración) en: {_pconfig.CONFIG_DIR}")
    except Exception as e:
        print(f"[Plania] No pude determinar la carpeta de datos: {e}")

    _servir(app_path, preferido, electron)


def _servir(app_path: str, preferido: int, electron: bool) -> None:
    """Levanta Streamlit, cambiando de puerto si otro programa gana la carrera.

    Streamlit no reintenta solo: si el puerto está tomado imprime
    "Port N is not available" y termina con código 1. Para el usuario eso es
    "Plania no abre" por culpa de un programa que ni sabe que tiene abierto.
    Acá se distingue ese caso de cualquier otro error —comprobando si el
    puerto quedó efectivamente ocupado— y sólo en ese caso se prueba el
    siguiente.
    """
    direccion = os.environ["STREAMLIT_SERVER_ADDRESS"]
    intentos = [preferido] + [p for p in _candidatos() if p != preferido]

    for puerto in intentos:
        reserva = _reservar(puerto)
        if reserva is None:
            continue
        # Con 0 el sistema operativo asignó uno real: hay que leerlo.
        puerto = reserva.getsockname()[1]

        os.environ["STREAMLIT_SERVER_PORT"] = str(puerto)
        _publicar_puerto(str(puerto))
        _banner(puerto, electron)

        cancelar = threading.Event()
        # Con PLANIA_NO_BROWSER=1 no se abre navegador: es el modo en que el
        # escritorio Electron (desktop/) embebe este mismo server en su ventana.
        if not electron:
            threading.Thread(target=_abrir_navegador,
                             args=(f"http://localhost:{puerto}", cancelar),
                             daemon=True).start()

        # Se suelta justo antes del bind de Streamlit, no antes.
        reserva.close()
        try:
            from streamlit.web import bootstrap
            from streamlit import config as stconfig
            stconfig.set_option("server.port", puerto)
            stconfig.set_option("server.address", direccion)
            stconfig.set_option("server.headless", True)
            stconfig.set_option("global.developmentMode", False)
            stconfig.set_option("browser.gatherUsageStats", False)
            bootstrap.run(app_path, False, [], {})
            return
        except SystemExit as e:
            cancelar.set()
            if e.code and _ocupado(puerto):
                print(f"[Plania] Otro programa tomó el puerto {puerto} "
                      f"justo al arrancar. Pruebo con otro.")
                continue
            raise

    raise SystemExit("[Plania] No quedó ningún puerto libre para arrancar. "
                     "Cerrá alguna aplicación y volvé a intentar.")


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
