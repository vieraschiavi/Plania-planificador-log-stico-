"""
Plania · Control de que las 12 pantallas se dibujan
====================================================
Levanta el producto de verdad y recorre las 12 pantallas con un navegador,
buscando lo único que un cliente que pagó no puede ver nunca: un traceback de
Python en pantalla.

    python3 packaging/verificar_pantallas.py

Por qué esto no lo cubren los tests: los tests importan módulos y verifican
funciones, pero no levantan la aplicación. Un `KeyError` que solo aparece al
dibujar una pantalla con datos reales pasa la suite entera y explota en la
demo con el cliente. Acá se abre el producto como lo abre él.

Qué se controla en cada pantalla:
  1. Que se pueda abrir desde el menú.
  2. Que no aparezca una excepción de Streamlit (`stException`) ni el texto de
     un traceback.
  3. Que no quede prácticamente vacía — una pantalla en blanco no lanza error
     pero es igual de mala frente a un cliente.
  4. Que no haya errores de JavaScript en la consola del navegador.

Corre contra una carpeta de configuración temporal y limpia, así que también
pasa por el gate de la EULA como un usuario que instala por primera vez.

Devuelve código 1 si algo falla, para poder usarlo antes de publicar.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Las mismas de app/app.py. Se listan acá a propósito en vez de leerlas del
# menú: si alguien borra una pantalla por error, este control tiene que
# fallar, no adaptarse silenciosamente a lo que quedó.
PANTALLAS = [
    "Inicio", "Panel ejecutivo", "Stock y reposición", "Precios y márgenes",
    "Zonas y negocios", "Rutas de reparto", "Ofertas y sugerencias",
    "Copiloto IA", "Conectar ERP", "Planes y licencia", "Configuración", "Ayuda",
]

# Texto que delata que algo se rompió y quedó a la vista.
SEÑALES = ("Traceback (most recent call last)", "KeyError", "AttributeError",
           "ZeroDivisionError", "IndexError", "OperationalError")

MIN_CARACTERES = 300   # menos que esto es una pantalla en blanco


def _levantar(config_dir: str, archivo_puerto: str):
    entorno = dict(os.environ,
                   PLANIA_NO_BROWSER="1",
                   PLANIA_PUERTO_ARCHIVO=archivo_puerto,
                   PLANIA_CONFIG_DIR=config_dir)
    return subprocess.Popen(
        [sys.executable, os.path.join(RAIZ, "packaging", "plania_launcher.py")],
        cwd=RAIZ, env=entorno,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _esperar(archivo_puerto: str, intentos: int = 120) -> str | None:
    """El puerto lo publica el propio lanzador: no se puede asumir cuál es,
    porque si el preferido está ocupado se muda solo."""
    for _ in range(intentos):
        time.sleep(1)
        if not os.path.exists(archivo_puerto):
            continue
        puerto = open(archivo_puerto).read().strip()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{puerto}", timeout=3)
            return puerto
        except Exception:
            continue
    return None


def recorrer(puerto: str) -> list[str]:
    from playwright.sync_api import sync_playwright

    fallas: list[str] = []
    with sync_playwright() as pw:
        ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
        nav = (pw.chromium.launch(executable_path=ejecutable)
               if os.path.exists(ejecutable) else pw.chromium.launch())
        pagina = nav.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errores_js: list[str] = []
        pagina.on("pageerror", lambda e: errores_js.append(str(e)[:200]))

        pagina.goto(f"http://127.0.0.1:{puerto}", wait_until="networkidle")
        time.sleep(8)

        if "Términos de uso" in pagina.inner_text("body"):
            pagina.get_by_text("Leí y acepto", exact=False).first.click()
            time.sleep(1)
            pagina.get_by_role("button", name="Continuar").click()
            time.sleep(8)

        abiertas = 0
        for etiqueta in PANTALLAS:
            try:
                pagina.get_by_text(etiqueta, exact=True).first.click(timeout=10000)
            except Exception as e:
                fallas.append(f"{etiqueta}: no se pudo abrir ({str(e)[:70]})")
                continue
            time.sleep(4)
            abiertas += 1

            if pagina.query_selector('[data-testid="stException"]'):
                detalle = pagina.inner_text('[data-testid="stException"]')[:250]
                fallas.append(f"{etiqueta}: excepción en pantalla -> "
                              f"{detalle.replace(chr(10), ' ')}")
            cuerpo = pagina.inner_text("body")
            for señal in SEÑALES:
                if señal in cuerpo:
                    fallas.append(f"{etiqueta}: '{señal}' visible en pantalla")
            if len(cuerpo.strip()) < MIN_CARACTERES:
                fallas.append(f"{etiqueta}: pantalla casi vacía "
                              f"({len(cuerpo.strip())} caracteres)")
            print(f"  [ok] {etiqueta}")

        nav.close()

    # Sin esto, una sonda rota que no encuentra ninguna pantalla terminaría
    # informando "todo bien". Ya pasó una vez.
    if abiertas < len(PANTALLAS):
        fallas.append(f"solo se abrieron {abiertas} de {len(PANTALLAS)} pantallas")
    if errores_js:
        fallas.append(f"errores de JavaScript en el navegador: {errores_js[:2]}")
    return fallas


def main() -> int:
    ap = argparse.ArgumentParser(description="Control de las pantallas de Plania")
    ap.parse_args()

    config_dir = tempfile.mkdtemp(prefix="plania_pantallas_")
    archivo_puerto = os.path.join(config_dir, "puerto.txt")
    proceso = _levantar(config_dir, archivo_puerto)
    try:
        puerto = _esperar(archivo_puerto)
        if not puerto:
            print("[pantallas] el producto no levantó a tiempo")
            return 1
        print(f"[pantallas] Plania respondiendo en el puerto {puerto}")
        fallas = recorrer(puerto)
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=15)
        except Exception:
            proceso.kill()
        shutil.rmtree(config_dir, ignore_errors=True)

    print()
    if fallas:
        print(f"{len(fallas)} problema(s):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print(f"Las {len(PANTALLAS)} pantallas se dibujan sin excepciones "
          "ni errores de JavaScript.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
