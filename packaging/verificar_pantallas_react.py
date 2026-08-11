"""
Plania · Control de las 12 pantallas de la ventana propia (Electron + React)
=============================================================================
El gemelo de `packaging/verificar_pantallas.py`, para la OTRA vía de entrega.

    python3 packaging/verificar_pantallas_react.py

Hay dos formas de usar Plania y hasta ahora solo una tenía control automático:

  · **BAT / Streamlit** — el producto corre en el navegador. Lo revisa
    `verificar_pantallas.py`.
  · **EXE / Electron + React** — el producto abre en su propia ventana y la
    interfaz es React hablando con `plania/api.py`. No lo revisaba nada.

La segunda es justamente la que no se puede probar acá a mano: construir el
`.exe` necesita Windows. Pero la ventana de Electron no hace magia — carga
`desktop/renderer/ui/index.html` desde `file://` pasándole el puerto de la API
por la query string (ver `desktop/main.js`), y eso es exactamente lo que hace
este control: levanta `plania.api`, abre ese mismo HTML en Chromium con el
mismo `?api=`, y recorre las 12 pantallas.

Queda afuera lo que es propio de Electron (el instalador, el ícono, la ventana
nativa). Queda adentro todo lo demás: que React monte, que cada pantalla pida
sus datos, que la API conteste y que no haya un error de JavaScript ni una
pantalla en blanco. Es la parte donde de verdad se rompen las cosas.

Devuelve 1 si algo falla, para poder usarlo antes de publicar.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(RAIZ, "desktop", "renderer", "ui", "index.html")
NODE_MODULES = os.path.join(RAIZ, "desktop", "node_modules")

# Las mismas 12 de desktop/renderer/ui/app.js. Se comparan contra el menú que
# dibuja la aplicación: si alguien agrega una pantalla y no la agrega acá,
# el control avisa en vez de dejarla sin revisar.
PANTALLAS = [
    "Inicio", "Panel ejecutivo", "Stock y reposición", "Precios y márgenes",
    "Zonas y negocios", "Rutas de reparto", "Ofertas y sugerencias",
    "Copiloto IA", "Conectar ERP", "Planes y licencia", "Configuración", "Ayuda",
]


def _puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _esperar(url: str, segundos: int = 90) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturas", action="store_true",
                    help="dejar un PNG de cada pantalla en packaging/capturas_react")
    args = ap.parse_args()

    for ruta, que in ((UI, "la interfaz"),
                      (os.path.join(NODE_MODULES, "react", "umd",
                                    "react.production.min.js"), "React"),
                      (os.path.join(NODE_MODULES, "plotly.js-dist-min",
                                    "plotly.min.js"), "Plotly")):
        if not os.path.exists(ruta):
            print(f"Falta {que}: {ruta}\nCorré antes: cd desktop && npm ci")
            return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Falta playwright. Instalalo con: pip install playwright")
        return 1

    # Configuración limpia: la aplicación arranca como en una instalación
    # nueva (demo de 7 días recién empezada), no con lo que haya en la máquina.
    cfg = tempfile.mkdtemp(prefix="plania_react_")
    puerto = _puerto_libre()
    entorno = dict(os.environ, PLANIA_CONFIG_DIR=cfg, PYTHONPATH=RAIZ)
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "plania.api:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "warning"],
        cwd=RAIZ, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True)

    base = f"http://127.0.0.1:{puerto}"
    fallas: list[str] = []
    try:
        if not _esperar(f"{base}/salud"):
            salida = api.stdout.read() if api.stdout else ""
            print(f"La API no respondió en {base}/salud\n{salida[-2000:]}")
            return 1
        print(f"[react] API local en {base}")

        ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
        with sync_playwright() as p:
            nav = (p.chromium.launch(executable_path=ejecutable)
                   if os.path.exists(ejecutable) else p.chromium.launch())
            ctx = nav.new_context(viewport={"width": 1440, "height": 950})
            pag = ctx.new_page()

            errores_js: list[str] = []
            pag.on("pageerror", lambda e: errores_js.append(str(e)))
            pag.on("console", lambda m: errores_js.append(m.text)
                   if m.type == "error" else None)

            # Igual que desktop/main.js: file:// + el puerto por query string.
            pag.goto(f"file://{UI}?api={base}", wait_until="load")
            pag.wait_for_timeout(2500)

            menu = [t.strip() for t in
                    pag.eval_on_selector_all("nav button, .menu button, aside button",
                                             "els => els.map(e => e.innerText)")
                    if t and t.strip()]
            faltan = [p_ for p_ in PANTALLAS if p_ not in menu]
            if faltan:
                fallas.append(f"el menú no ofrece: {faltan} (ofrece {menu})")

            if args.capturas:
                destino = os.path.join(RAIZ, "packaging", "capturas_react")
                os.makedirs(destino, exist_ok=True)

            for nombre in PANTALLAS:
                if nombre not in menu:
                    continue
                del errores_js[:]
                try:
                    pag.click(f'button:has-text("{nombre}")', timeout=10000)
                except Exception as e:
                    fallas.append(f"{nombre}: no se pudo abrir ({type(e).__name__})")
                    continue
                pag.wait_for_timeout(2200)

                cuerpo = pag.inner_text("body")
                problemas = []
                # Un traceback de Python llegando hasta la pantalla del cliente
                # es lo único que nunca puede pasar.
                for marca in ("Traceback", "AttributeError", "KeyError",
                              "TypeError:", "Internal Server Error"):
                    if marca in cuerpo:
                        problemas.append(marca)
                # Una pantalla en blanco no lanza error y es igual de mala.
                sin_menu = cuerpo
                for m in menu:
                    sin_menu = sin_menu.replace(m, "")
                if len(sin_menu.strip()) < 120:
                    problemas.append("queda casi vacía")
                if errores_js:
                    problemas.append(f"JS: {errores_js[0][:120]}")

                print(f"  {'FALLA' if problemas else 'OK  '} {nombre}"
                      + (f" · {problemas}" if problemas else ""))
                if problemas:
                    fallas.append(f"{nombre}: {problemas}")
                if args.capturas:
                    archivo = nombre.lower().replace(" ", "_").replace("ó", "o")
                    pag.screenshot(path=os.path.join(destino, f"{archivo}.png"),
                                   full_page=True)
            nav.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
        shutil.rmtree(cfg, ignore_errors=True)

    print()
    if fallas:
        print(f"{len(fallas)} problema(s) en la ventana propia:")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print(f"Las {len(PANTALLAS)} pantallas de la ventana propia (Electron + React) "
          f"se dibujan contra la API real, sin errores de JavaScript.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
