# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Grabación del video de demostración
============================================
Graba un recorrido REAL del producto (no una animación ni un mockup):
levanta la aplicación, la maneja con un navegador de verdad y captura la
pantalla, igual que el `Demo_Real` de la landing de Kobra.

    python3 sitio/grabar_demo.py

Deja `web/assets/video/plania_demo_es.mp4` y el póster. La narración en tres
idiomas se agrega después con `sitio/doblar_video.py`.

El guion de escenas de abajo está sincronizado con `sitio/narracion/*.json`:
si cambiás los tiempos acá, hay que ajustar los subtítulos allá (el propio
`doblar_video.py` avisa si se desfasan).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "web", "assets", "video")
PUERTO = int(os.environ.get("PLANIA_PUERTO_DEMO", "8710"))
ANCHO, ALTO = 1280, 800

# (etiqueta del menú, segundos que se queda, acción extra opcional)
ESCENAS = [
    ("Inicio", 8, None),
    ("Panel ejecutivo", 12, None),
    ("Ofertas y sugerencias", 14, None),
    ("Copiloto IA", 22, "consulta"),
    ("Rutas de reparto", 8, None),
    ("Conectar ERP", 8, None),
]
CONSULTA = "¿qué ofertas armo esta semana?"


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _esperar(url: str, intentos: int = 90) -> bool:
    import urllib.request
    for _ in range(intentos):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(1)
    return False


def grabar() -> str:
    from playwright.sync_api import sync_playwright

    os.makedirs(SALIDA, exist_ok=True)
    tmp = os.path.join(SALIDA, "_crudo")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    with sync_playwright() as p:
        ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
        navegador = (p.chromium.launch(executable_path=ejecutable)
                     if os.path.exists(ejecutable) else p.chromium.launch())
        contexto = navegador.new_context(
            viewport={"width": ANCHO, "height": ALTO},
            record_video_dir=tmp,
            record_video_size={"width": ANCHO, "height": ALTO},
        )
        pagina = contexto.new_page()
        pagina.goto(f"http://localhost:{PUERTO}", wait_until="networkidle")
        time.sleep(6)   # que termine de cargar los datos y dibujar

        for etiqueta, segundos, extra in ESCENAS:
            try:
                pagina.get_by_text(etiqueta, exact=True).first.click()
            except Exception as e:
                print(f"[demo] no pude abrir '{etiqueta}': {e}")
                continue
            time.sleep(3)

            if extra == "consulta":
                try:
                    caja = pagina.get_by_placeholder("Escribí tu consulta…")
                    caja.click()
                    # Se escribe carácter por carácter: en un video de venta
                    # ver escribir la pregunta explica el producto mejor que
                    # que aparezca la respuesta de la nada.
                    caja.type(CONSULTA, delay=55)
                    time.sleep(1)
                    pagina.keyboard.press("Enter")
                    time.sleep(9)
                    pagina.mouse.wheel(0, 420)
                except Exception as e:
                    print(f"[demo] consulta del copiloto: {e}")

            # Un scroll suave dentro de cada pantalla para mostrar el contenido
            # de abajo sin que el video quede estático.
            restante = max(0, segundos - 3)
            pasos = max(1, restante // 2)
            for _ in range(pasos):
                pagina.mouse.wheel(0, 260)
                time.sleep(2)
            pagina.mouse.wheel(0, -2000)
            print(f"[demo] escena '{etiqueta}' ({segundos}s)")

        contexto.close()
        navegador.close()

    webm = next((os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".webm")), None)
    if not webm:
        raise SystemExit("Playwright no dejó ningún .webm")
    return webm


def convertir(webm: str) -> str:
    """A MP4 H.264 + póster. H.264 porque es el único códec que reproducen
    todos los navegadores y todos los celulares sin excepción."""
    mp4 = os.path.join(SALIDA, "plania_demo_es.mp4")
    poster = os.path.join(SALIDA, "poster.jpg")
    ff = _ffmpeg()

    subprocess.run([ff, "-y", "-i", webm, "-c:v", "libx264", "-preset", "slow",
                    "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-an", mp4], check=True, capture_output=True)
    subprocess.run([ff, "-y", "-ss", "3", "-i", mp4, "-frames:v", "1",
                    "-q:v", "3", poster], check=True, capture_output=True)
    shutil.rmtree(os.path.dirname(webm), ignore_errors=True)
    return mp4


def main() -> int:
    if not _esperar(f"http://localhost:{PUERTO}"):
        print(f"[demo] no hay nada escuchando en el puerto {PUERTO}.\n"
              f"       Levantá la app primero:\n"
              f"       streamlit run app/app.py --server.port {PUERTO} --server.headless true")
        return 1
    mp4 = convertir(grabar())
    tam = os.path.getsize(mp4) / 1_048_576
    print(f"\n[demo] {mp4}  ({tam:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
