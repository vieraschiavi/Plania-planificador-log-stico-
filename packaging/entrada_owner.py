# © 2026 Martín Viera. Todos los derechos reservados.
"""
Punto de entrada de "Plania Owner" — el panel del dueño como programa aparte.

Es una línea de código y un archivo entero porque PyInstaller empaqueta *un
script*: para que el mismo lanzador levante una pantalla distinta hace falta
un script distinto que fije la variable antes de llamarlo.

Por qué el panel del dueño es un programa separado y no una opción dentro de
Plania: el producto tiene que ser el mismo archivo para el dueño y para quien
lo compra. Si el panel viviera adentro protegido por un token, el modelo
financiero, los márgenes, la facturación y el motor de contenido estarían en
el disco de cada cliente, a un token de distancia. Separado, no viajan.
"""
import os
import sys

os.environ["PLANIA_PANEL"] = "owner"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plania_launcher import main  # noqa: E402

if __name__ == "__main__":
    main()
