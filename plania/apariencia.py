"""
Plania · Apariencia de programa instalado
=========================================
Plania se instala y se abre en su propia ventana. Streamlit, en cambio, está
pensado para verse en una pestaña del navegador y trae su propio andamiaje:
el menú de hamburguesa (con "Rerun", "Clear cache" y un enlace a
streamlit.io), el botón *Deploy*, la barra de colores de arriba, el cartelito
"Running..." y el pie "Made with Streamlit".

Nada de eso tiene sentido en un programa que alguien compró e instaló, y
además delata con qué está hecho — que es justo lo contrario de lo que
transmite un producto que se vende a una empresa.

Este módulo devuelve el CSS que lo oculta. Está acá y no copiado en cada
pantalla porque el panel del cliente y el del dueño tienen que verse igual:
duplicado, uno de los dos se iba a quedar atrás.
"""
from __future__ import annotations

# Se apunta por `data-testid`, que Streamlit mantiene estable entre versiones,
# y también por los selectores viejos (`#MainMenu`, `footer`) para que siga
# funcionando si la máquina tiene una versión anterior instalada. Sobra
# cobertura a propósito: que se cuele el menú de Streamlit en una demo con un
# cliente cuesta más que estas líneas de más.
CROMO_STREAMLIT = """
  #MainMenu, header [data-testid="stMainMenu"],
  [data-testid="stToolbar"], [data-testid="stActionButtonIcon"],
  [data-testid="stAppDeployButton"], [data-testid="stDecoration"],
  [data-testid="stStatusWidget"], [data-testid="stToolbarActions"],
  footer, .viewerBadge_container__1QSob, .stDeployButton {
      display: none !important;
      visibility: hidden !important;
  }
  header[data-testid="stHeader"] { height: 0; background: transparent; }
"""

# La tipografía NO se trae de Google Fonts: el programa tiene que verse igual
# sin internet — un depósito o una oficina con la red caída no es un caso raro
# — y además una llamada a un servidor externo en cada arranque es algo que un
# área de sistemas puede bloquear. Segoe UI ya viene con Windows, que es donde
# corre el instalador; Inter queda como segunda opción por si está instalada.
TIPOGRAFIA = """
  html, body, [class*="css"], .stMarkdown, button, input, textarea {
      font-family: 'Segoe UI', 'Inter', system-ui, -apple-system, sans-serif;
  }
"""


def css_programa() -> str:
    """CSS que hace que la ventana parezca un programa y no una página web."""
    return CROMO_STREAMLIT + TIPOGRAFIA
