# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Imágenes del asistente de instalación (Inno Setup)
=============================================================
Genera las dos imágenes que Inno Setup muestra en el instalador Windows:

  assets/brand/plania_wizard.bmp        panel grande (bienvenida y cierre)
  assets/brand/plania_wizard_small.bmp  logo chico (esquina de las páginas
                                        intermedias: carpeta, progreso, etc.)

Por qué un script y no dos .bmp sueltos: son la misma marca que
`assets/brand/plania_icon.png` (el ícono de la app y de la web) — generarlas
del mismo archivo, en vez de diseñarlas aparte a mano, es lo que evita que el
instalador se vea "de otro producto".

Y por qué se PEGA el ícono en vez de redibujarlo: antes este script dibujaba
el logo a mano con primitivas de Pillow, replicando la forma. Funcionaba
mientras la marca no cambiara; el día que cambió, el ícono de la app quedó
actualizado y el instalador siguió mostrando el logo viejo, porque eran dos
dibujos distintos que sólo se parecían por disciplina. Ahora hay un único
original y esto lo escala.

Uso (no requiere Windows ni Inno Setup, solo Pillow):
    python3 packaging/generar_imagenes_instalador.py

Si cambió la marca, correr antes `packaging/generar_iconos.py`, que es quien
rasteriza `assets/brand/mv.svg` al PNG que esto consume.

Tamaños: Inno Setup con WizardStyle=modern usa como base 192x386 para el panel
grande y 76x80 para el logo chico, y escala solo para pantallas de alto DPI
si no se le da nada mejor — un único archivo por imagen alcanza.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "assets", "brand")

ICONO = os.path.join(RAIZ, "assets", "brand", "plania_icon.png")

PANEL = (192, 386)
LOGO_CHICO = (76, 80)


def _navy() -> tuple[int, int, int]:
    """El azul del fondo, leído del ícono real y no elegido de nuevo.

    Se muestrea arriba al centro: ahí el ícono es fondo puro, lejos de las
    esquinas redondeadas (que son transparentes) y de las letras. Si algún día
    cambia el color de la marca, el panel del instalador lo sigue solo.
    """
    with Image.open(ICONO) as img:
        rgba = img.convert("RGBA")
        r, g, b, _a = rgba.getpixel((rgba.width // 2, rgba.height // 8))
    return (r, g, b)


def _pegar_icono(base: Image.Image, cx: int, cy: int, lado: int) -> None:
    """El ícono de la app, centrado en (cx, cy) y escalado a `lado` píxeles.

    Se pega con su propio canal alfa como máscara: el ícono tiene las esquinas
    redondeadas y transparentes, así que sin la máscara aparecería un cuadrado
    negro alrededor.
    """
    with Image.open(ICONO) as img:
        icono = img.convert("RGBA").resize((lado, lado), Image.LANCZOS)
    base.paste(icono, (cx - lado // 2, cy - lado // 2), icono)


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
    img = Image.new("RGB", (ancho, alto), _navy())
    _pegar_icono(img, ancho // 2, int(alto * 0.30), lado=112)
    _pictograma_instalacion(img, ancho // 2, int(alto * 0.66))
    return img


def logo_chico() -> Image.Image:
    ancho, alto = LOGO_CHICO
    img = Image.new("RGB", (ancho, alto), _navy())
    # Con margen: pegado al borde, Inno Setup lo recorta contra el borde de la
    # página y se ve como si estuviera mal alineado.
    _pegar_icono(img, ancho // 2, alto // 2, lado=min(ancho, alto) - 14)
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
