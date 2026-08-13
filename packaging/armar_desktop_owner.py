# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Arma el árbol ejecutable del panel del dueño (Electron)
=================================================================
Junta en `build/desktop_owner/` lo propio del panel (`desktop_owner/`) con
las piezas que comparte con el producto (`desktop/`), y deja una carpeta
lista para `npm start` o `electron-builder`.

Por qué se compone en vez de tener todo junto en una carpeta
------------------------------------------------------------
Las dos mitades tienen que vivir separadas por motivos opuestos:

  - Lo del dueño NO puede estar bajo `desktop/`. Ese árbol se empaqueta con
    `"renderer/**"` sin exclusiones y ese camino nunca consulta
    `fuera_del_producto()`, así que un archivo del panel ahí adentro viaja en
    texto plano dentro del instalador de cada cliente — con la facturación,
    los márgenes y el modelo financiero a la vista.
  - Lo compartido (`base.js`, `estilo.css`, `preload.js`) NO puede estar
    duplicado en `desktop_owner/`. Dos copias divergen: el día que se arregle
    un gráfico o el formato de un número en una, la otra sigue mostrando lo
    de antes, y la diferencia aparece comparando el panel con el producto.

Componer al armar deja una sola fuente para cada archivo y ningún archivo
del dueño dentro del árbol que se empaqueta para clientes.

Uso:
    python packaging/armar_desktop_owner.py
    cd build/desktop_owner && npm start
"""
from __future__ import annotations

import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN_OWNER = os.path.join(REPO, "desktop_owner")
ORIGEN_PRODUCTO = os.path.join(REPO, "desktop")
DESTINO = os.path.join(REPO, "build", "desktop_owner")

# Piezas del producto que el panel reusa tal cual. La ruta de la izquierda es
# relativa a `desktop/`; la de la derecha, al árbol armado.
COMPARTIDOS = [
    ("renderer/ui/base.js", "renderer/ui/base.js"),
    ("renderer/ui/estilo.css", "renderer/ui/estilo.css"),
    ("preload.js", "preload.js"),
]

# Marca: se copia adentro del árbol para que las rutas de main.js y de
# package.json no dependan de a qué profundidad quedó armado.
ASSETS = ["brand/plania_icon.png", "brand/plania.ico"]

# Lo que el árbol armado tiene que tener sí o sí para abrir. Si falta uno, la
# ventana arranca y queda en blanco sin decir por qué, que es la falla más
# cara de diagnosticar.
IMPRESCINDIBLES = [
    "main.js", "preload.js", "package.json",
    "renderer/ui/index.html", "renderer/ui/base.js",
    "renderer/ui/pantallas_owner.js", "renderer/ui/app_owner.js",
    "renderer/ui/estilo.css", "renderer/ui/estilo_owner.css",
]


def armar(destino: str = DESTINO, node_modules: bool = True) -> str:
    """Deja el árbol del panel del dueño listo en `destino` y lo devuelve."""
    if os.path.exists(destino):
        shutil.rmtree(destino)
    shutil.copytree(ORIGEN_OWNER, destino,
                    ignore=shutil.ignore_patterns("node_modules", "dist_electron"))

    for rel_origen, rel_destino in COMPARTIDOS:
        src = os.path.join(ORIGEN_PRODUCTO, rel_origen)
        if not os.path.exists(src):
            raise SystemExit(f"[owner] falta la pieza compartida {rel_origen} en desktop/")
        dst = os.path.join(destino, rel_destino)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    for rel in ASSETS:
        src = os.path.join(REPO, "assets", rel)
        if not os.path.exists(src):
            continue  # la marca es opcional para correrlo en desarrollo
        dst = os.path.join(destino, "assets", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    # node_modules: se reusa el del producto en vez de instalar de nuevo. Son
    # las mismas tres dependencias y bajarlas dos veces sólo agrega minutos y
    # la chance de que las versiones queden distintas entre las dos ventanas.
    origen_modulos = os.path.join(ORIGEN_PRODUCTO, "node_modules")
    if node_modules and os.path.isdir(origen_modulos):
        shutil.copytree(origen_modulos, os.path.join(destino, "node_modules"),
                        symlinks=True, dirs_exist_ok=True)

    faltan = [r for r in IMPRESCINDIBLES
              if not os.path.exists(os.path.join(destino, r.replace("/", os.sep)))]
    if faltan:
        raise SystemExit(f"[owner] el árbol quedó incompleto, falta: {', '.join(faltan)}")

    return destino


def main() -> None:
    destino = armar()
    hay_modulos = os.path.isdir(os.path.join(destino, "node_modules"))
    print(f"[owner] árbol armado en {os.path.relpath(destino, REPO)}")
    if not hay_modulos:
        print("[owner] sin node_modules: corré `npm install` en desktop/ y volvé a armar")
    print("[owner] para abrirlo:  cd build/desktop_owner && npm start")


if __name__ == "__main__":
    sys.exit(main())
