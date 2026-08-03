"""
Plania · Imágenes del asistente de instalación (Inno Setup)
=============================================================
Genera las dos imágenes que Inno Setup muestra en el instalador Windows:

  assets/brand/plania_wizard.bmp        panel grande (bienvenida y cierre)
  assets/brand/plania_wizard_small.bmp  logo chico (esquina de las páginas
                                        intermedias: carpeta, progreso, etc.)

Por qué un script y no dos .bmp sueltos: son la misma family de marca que
`assets/brand/plania_icon.png` (el ícono de la app y de la web) — generarlas
a partir de los mismos colores exactos, en vez de diseñarlas aparte a mano,
es lo que evita que el instalador se vea "de otro producto". Los colores de
abajo salen de leer los píxeles reales de `plania_icon.png`, no de adivinar.

Uso (no requiere Windows ni Inno Setup, solo Pillow):
    python3 packaging/generar_imagenes_instalador.py

Tamaños: Inno Setup con WizardStyle=modern usa como base 192x386 para el panel
grande y 76x80 para el logo chico, y escala solo para pantallas de alto DPI
si no se le da nada mejor — un único archivo por imagen alcanza.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "assets", "brand")

# Los tres colores reales del ícono ya publicado (assets/brand/plania_icon.png),
# leídos con Pillow, no elegidos de nuevo — así el instalador es la misma
# marca que el ícono del .exe y el favicon de la web, no una variación.
NAVY = (31, 61, 122)
AMBER = (243, 156, 18)
BLUE = (46, 134, 222)
BLANCO_TENUE = (255, 255, 255)

PANEL = (192, 386)
LOGO_CHICO = (76, 80)


def _icono_red(draw: ImageDraw.ImageDraw, cx: int, cy: int, escala: float) -> None:
    """Los tres nodos conectados de plania_icon.png, a cualquier escala.

    Mismo trazo que el ícono original: dos líneas azules bajando desde el
    nodo de arriba a los dos de abajo, tres círculos ámbar. Repetir la forma
    exacta es lo que hace que se reconozca como el mismo logo y no como un
    logo parecido.
    """
    radio = int(18 * escala)
    grosor = max(2, int(7 * escala))
    dx, dy = int(46 * escala), int(40 * escala)

    arriba = (cx, cy - dy)
    izq = (cx - dx, cy + dy)
    der = (cx + dx, cy + dy)

    for destino in (izq, der):
        draw.line([arriba, destino], fill=BLUE, width=grosor)
    for nodo in (arriba, izq, der):
        draw.ellipse([nodo[0] - radio, nodo[1] - radio,
                      nodo[0] + radio, nodo[1] + radio], fill=AMBER)


def _pictograma_instalacion(base: Image.Image, cx: int, cy: int) -> None:
    """Flecha bajando a una notebook: "esto se está instalando en tu máquina".

    Un solo trazo tenue en blanco translúcido sobre el navy, para que quede
    subordinado al logo (que es lo que tiene que reconocerse) y no compita
    con él. No es una copia de ningún pictograma existente: es el mínimo
    dibujo que comunica "descarga → instalación" con las formas más simples
    posibles (una flecha y un rectángulo).

    Se dibuja en una capa RGBA aparte y se pega con su propio canal alfa como
    máscara: es la forma de tener un trazo semitransparente prolijo sobre un
    fondo sólido sin depender de que ImageDraw exponga la imagen de base.
    """
    color = (255, 255, 255, 235)
    capa = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(capa)

    # Flecha: vástago + punta triangular.
    tallo_x = 100
    d2.line([(tallo_x, 10), (tallo_x, 78)], fill=color, width=9)
    d2.polygon([(tallo_x - 26, 62), (tallo_x + 26, 62), (tallo_x, 98)], fill=color)

    # Notebook: pantalla + base, en trazo (no relleno) para que se lea
    # "dispositivo" y no un bloque sólido que tape la flecha.
    d2.rounded_rectangle([40, 120, 160, 172], radius=8, outline=color, width=7)
    d2.line([(28, 182), (172, 182)], fill=color, width=10)

    capa = capa.resize((140, 140), Image.LANCZOS)
    base.paste(capa, (cx - 70, cy - 70), capa)


def panel_grande() -> Image.Image:
    ancho, alto = PANEL
    img = Image.new("RGB", (ancho, alto), NAVY)
    draw = ImageDraw.Draw(img)

    _icono_red(draw, ancho // 2, int(alto * 0.30), escala=1.55)
    _pictograma_instalacion(img, ancho // 2, int(alto * 0.66))
    return img


def logo_chico() -> Image.Image:
    ancho, alto = LOGO_CHICO
    img = Image.new("RGB", (ancho, alto), NAVY)
    draw = ImageDraw.Draw(img)
    _icono_red(draw, ancho // 2, alto // 2, escala=0.62)
    return img


def main() -> None:
    os.makedirs(DESTINO, exist_ok=True)

    ruta_panel = os.path.join(DESTINO, "plania_wizard.bmp")
    panel_grande().save(ruta_panel, format="BMP")
    print(f"[instalador] {os.path.relpath(ruta_panel, RAIZ)}  ({PANEL[0]}x{PANEL[1]})")

    ruta_logo = os.path.join(DESTINO, "plania_wizard_small.bmp")
    logo_chico().save(ruta_logo, format="BMP")
    print(f"[instalador] {os.path.relpath(ruta_logo, RAIZ)}  ({LOGO_CHICO[0]}x{LOGO_CHICO[1]})")


if __name__ == "__main__":
    main()
