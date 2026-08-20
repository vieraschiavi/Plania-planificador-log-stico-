# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Íconos de la aplicación, a partir de la marca MV
=========================================================
Rasteriza `assets/brand/mv.svg` —la marca MV, la misma del resto de los
productos— a todos los tamaños que necesitan Windows, la ventana de Electron y
el favicon de la web:

  assets/brand/plania_icon.png       256x256  ícono de la ventana y favicon
  assets/brand/plania_icon_128.png   128x128
  assets/brand/plania_icon_64.png     64x64
  assets/brand/plania_icon_32.png     32x32
  assets/brand/plania.ico            16/24/32/48/64/128/256, multi-tamaño

Los nombres siguen diciendo `plania_*` a propósito: los referencian
`desktop/package.json`, `desktop_owner/package.json`, los dos `.iss`, los dos
`main.js`, `armar_desktop_owner.py` y `sitio/build.py`. Cambiar la marca es
cambiar los píxeles; renombrar los archivos sería cambiar además ocho puntos
de enganche, con la chance de que alguno quede apuntando a un archivo que ya
no está y el instalador salga con el ícono en blanco.

El SVG es la fuente de verdad. Está en el repositorio para que este script
pueda volver a correrse: rasterizar de nuevo desde el vector da un resultado
nítido en cada tamaño, mientras que reescalar un PNG chico no.

Uso — sólo hace falta cuando cambia la marca, no en cada build:

    pip install cairosvg     # no está en requirements.txt: no lo necesita
    python3 packaging/generar_iconos.py   # ni la app ni los tests, sólo esto

Después de correrlo, regenerar también las imágenes del instalador, que se
arman a partir del PNG de 256:

    python3 packaging/generar_imagenes_instalador.py
    python3 sitio/build.py                # propaga el favicon a web/assets/
"""
from __future__ import annotations

import io
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARCA = os.path.join(RAIZ, "assets", "brand", "mv.svg")
DESTINO = os.path.join(RAIZ, "assets", "brand")

# Los que Windows realmente usa. El 24 y el 48 no tienen PNG suelto pero sí
# entran en el .ico: son los que muestra el Explorador en las vistas "iconos
# medianos" y en la barra de tareas con escalado, y sin ellos Windows reescala
# el de 32 y se ve sucio justo en los dos lugares más visibles.
TAMANOS_ICO = (16, 24, 32, 48, 64, 128, 256)
TAMANOS_PNG = (32, 64, 128, 256)


def _rasterizar(px: int):
    """El SVG a un PNG cuadrado de `px`, rasterizado desde el vector."""
    try:
        import cairosvg
    except ImportError:
        raise SystemExit(
            "Falta cairosvg (no está en requirements.txt porque sólo hace "
            "falta para regenerar los íconos):\n    pip install cairosvg")
    from PIL import Image

    datos = cairosvg.svg2png(url=MARCA, output_width=px, output_height=px)
    return Image.open(io.BytesIO(datos)).convert("RGBA")


def main() -> None:
    if not os.path.exists(MARCA):
        raise SystemExit(f"No está la marca: {os.path.relpath(MARCA, RAIZ)}")

    grande = None
    for px in TAMANOS_PNG:
        img = _rasterizar(px)
        if px == 256:
            grande = img
            nombre = "plania_icon.png"
        else:
            nombre = f"plania_icon_{px}.png"
        ruta = os.path.join(DESTINO, nombre)
        img.save(ruta, format="PNG")
        print(f"[iconos] {os.path.relpath(ruta, RAIZ)}  ({px}x{px})")

    # Cada tamaño del .ico se rasteriza del vector, no se reescala del de 256:
    # un 16x16 sacado de reducir un 256x256 queda con la M y la V empastadas.
    capas = [_rasterizar(px) for px in TAMANOS_ICO]
    ruta_ico = os.path.join(DESTINO, "plania.ico")
    capas[-1].save(ruta_ico, format="ICO",
                   sizes=[(p, p) for p in TAMANOS_ICO],
                   append_images=capas[:-1])
    print(f"[iconos] {os.path.relpath(ruta_ico, RAIZ)}  "
          f"({'/'.join(str(p) for p in TAMANOS_ICO)})")

    assert grande is not None


if __name__ == "__main__":
    main()
