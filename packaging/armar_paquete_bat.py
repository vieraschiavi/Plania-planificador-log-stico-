"""
Plania · Armado del paquete BAT (la vía sin ejecutable)
=======================================================
Genera `dist/Plania_BAT.zip`: el mismo producto, pero arrancado con
`INICIAR_PLANIA.bat` y el Python del usuario en vez de con un `.exe`.

Existe porque en muchas empresas IT no deja ejecutar un `.exe` bajado de
internet, y ahí el instalador —por bueno que sea— no es una opción. Un `.bat`
que llama al Python que la empresa ya aprobó, casi siempre sí.

    python packaging/armar_paquete_bat.py
    python packaging/armar_paquete_bat.py --verificar dist/Plania_BAT.zip

Por qué esto es un script y no cuatro líneas de PowerShell en el workflow
--------------------------------------------------------------------------
Porque lo que entra a este ZIP se lee, tal cual, en la máquina del cliente:
no está compilado con Cython como el `.exe`. La versión anterior copiaba
`app/` y `plania/` enteros, así que le mandaba a cada cliente el panel del
dueño en texto plano — `plania/negocio.py` (costos y márgenes del producto),
`plania/owner.py` y `app/owner.py` (facturación y clientes). El `.exe` sí los
sacaba (`packaging/proteger_codigo.py`), o sea que las dos vías de entrega
del MISMO producto no coincidían, y la que no coincidía era la que iba en
código abierto.

Siendo un script de Python, la exclusión sale de una sola lista —la de
`proteger_codigo.py`, la misma que usa el `.exe`—, se puede correr en
cualquier sistema operativo y, sobre todo, se puede VERIFICAR: `--verificar`
abre el ZIP ya armado y falla si adentro hay algo que no tenía que estar, o
si falta algo que sí. Que el paso de armado y el de control sean el mismo
archivo evita el modo de falla clásico: cambiar uno y olvidarse del otro.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "packaging"))

from proteger_codigo import (MODULOS_SOLO_OWNER, PREFIJOS_SOLO_OWNER,  # noqa: E402
                             fuera_del_producto)

DESTINO = os.path.join(RAIZ, "dist", "Plania_BAT.zip")

# Lo que el cliente necesita para correr el producto, y nada más.
#
# Carpetas enteras (menos lo que saque EXCLUIDOS) y archivos sueltos:
CARPETAS = ["app", "plania", "data", "assets", ".streamlit"]
ARCHIVOS = [
    "requirements.txt",
    "README.md",
    "LICENSE-EULA.md",
    "INICIAR_PLANIA.bat",
    # El arranque real: elige un puerto libre, espera a que el servidor
    # responda y recién ahí abre la ventana. El .bat solo lo invoca.
    os.path.join("packaging", "plania_launcher.py"),
    os.path.join("packaging", "ventana.py"),
]

# Fuera, con el motivo de cada uno:
#
#   backend_venta/   el servidor de venta del Licenciante: emite licencias y
#                    cobra por MercadoPago. Nunca corre del lado del cliente.
#   docs/            documentación interna — modelo comercial, análisis de
#                    negocio, comparativa de competencia, auditoría.
#   tests/           la suite; no le sirve a quien usa el producto y además
#                    importa los módulos del dueño.
#   web/, sitio/     la web de venta y sus fuentes.
#   packaging/*      el resto de las herramientas de build, incluido lo del
#                    panel del dueño (plania_owner.spec, entrada_owner.py,
#                    generar_licencia_owner.py).
#   Procfile         despliegue del backend de venta.
#
# Y los módulos del dueño, que salen de la MISMA lista que usa el .exe
# (packaging/proteger_codigo.py).
EXCLUIDOS = {
    f"{carpeta}/{archivo}"
    for carpeta, archivos in MODULOS_SOLO_OWNER.items()
    for archivo in archivos
}

# Lo que tiene que estar sí o sí. Sin esto, un ZIP vacío pasaría el control de
# "no lleva nada del dueño" con honores.
IMPRESCINDIBLES = [
    "INICIAR_PLANIA.bat",
    "requirements.txt",
    "LICENSE-EULA.md",
    os.path.join("app", "app.py"),
    os.path.join("plania", "api.py"),
    os.path.join("plania", "licencia.py"),
    os.path.join("plania", "sugerencias.py"),
    os.path.join("packaging", "plania_launcher.py"),
    os.path.join("data", "generate_dataset.py"),
]

# Nombres que no pueden aparecer NUNCA dentro del ZIP, mirando cada ruta
# completa. Es una segunda red, por si algún día alguien agrega una carpeta a
# CARPETAS sin pensar en esto.
PROHIBIDOS = ["backend_venta", "owner", "negocio.py", "contenido.py",
              "verificacion.py", "sitio/", "docs/", "tests/",
              # Artefactos de la máquina donde se armó (ver
              # ARTEFACTOS_DE_LA_MAQUINA en proteger_codigo.py).
              "uso_licencias", "auditoria.log", ".lock"]


def _incluir(rel: str) -> bool:
    """¿Esta ruta relativa al repo entra al paquete?

    `fuera_del_producto` es la MISMA función que usa packaging/plania.spec
    para el .exe: cubre los módulos del dueño, sus capturas, docs/ interna y
    los __pycache__ (que además pueden llevar el bytecode de un .py excluido).
    """
    return not fuera_del_producto(rel)


def archivos_del_paquete() -> list[str]:
    """Rutas relativas al repo que van al ZIP, ya filtradas."""
    salida = []
    for carpeta in CARPETAS:
        base = os.path.join(RAIZ, carpeta)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), RAIZ)
                if _incluir(rel):
                    salida.append(rel)
    for archivo in ARCHIVOS:
        if os.path.exists(os.path.join(RAIZ, archivo)):
            salida.append(archivo)
    return sorted(salida)


DESTINO_OWNER = os.path.join(RAIZ, "dist", "Plania_Owner_BAT.zip")


def archivos_del_paquete_owner() -> list[str]:
    """Igual que el del producto, pero CON el panel del dueño adentro.

    Es la versión .bat de `Plania_Owner.zip`: misma razón de ser que la del
    producto (una PC donde no se puede ejecutar un .exe), solo que este ZIP no
    sale nunca de la máquina del dueño — no va a INSTALADOR/, no se adjunta a
    ninguna release y el workflow corta si aparece publicado.
    """
    rutas = set(archivos_del_paquete())
    for carpeta, archivos in MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            rel = f"{carpeta}/{archivo}"
            if os.path.exists(os.path.join(RAIZ, rel)):
                rutas.add(rel)
    rutas.add("INICIAR_PLANIA_OWNER.bat")
    return sorted(r for r in rutas if os.path.exists(os.path.join(RAIZ, r)))


def armar_owner(destino: str = DESTINO_OWNER) -> str:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    rutas = archivos_del_paquete_owner()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in rutas:
            z.write(os.path.join(RAIZ, rel), os.path.join("Plania Owner", rel))
    mb = os.path.getsize(destino) / (1 << 20)
    print(f"[bat] {destino}  ({len(rutas)} archivos, {mb:.1f} MB)")
    print("[bat] ! Este ZIP lleva el panel del dueño: no se publica ni se "
          "sube a INSTALADOR/.")
    return destino


def armar(destino: str = DESTINO) -> str:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    rutas = archivos_del_paquete()
    # Todo cuelga de una carpeta "Plania/" para que descomprimir en Descargas
    # no desparrame treinta archivos sueltos.
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in rutas:
            z.write(os.path.join(RAIZ, rel), os.path.join("Plania", rel))
    mb = os.path.getsize(destino) / (1 << 20)
    print(f"[bat] {destino}  ({len(rutas)} archivos, {mb:.1f} MB)")
    print(f"[bat] fuera del paquete: {', '.join(sorted(EXCLUIDOS))}, "
          f"{', '.join(PREFIJOS_SOLO_OWNER)} + backend_venta/, tests/, sitio/, web/")
    return destino


def verificar(zip_path: str) -> list[str]:
    """Devuelve la lista de problemas del ZIP ya armado. Vacía = está bien."""
    problemas = []
    if not os.path.exists(zip_path):
        return [f"no existe {zip_path}"]

    with zipfile.ZipFile(zip_path) as z:
        nombres = [n for n in z.namelist() if not n.endswith("/")]

    # Se compara sin el prefijo "Plania/" que agrega el armado.
    internos = [n[len("Plania/"):] if n.startswith("Plania/") else n for n in nombres]

    for rel in sorted(EXCLUIDOS):
        clave = rel.replace("\\", "/")
        if clave in internos:
            problemas.append(f"lleva un módulo del dueño: {clave}")

    for prohibido in PROHIBIDOS:
        colados = [n for n in internos if prohibido in n]
        if colados:
            problemas.append(f"lleva {prohibido!r}: {colados[:3]}")

    for rel in IMPRESCINDIBLES:
        if rel.replace("\\", "/") not in internos:
            problemas.append(f"le falta {rel} — el producto no arrancaría")

    if not problemas:
        print(f"[bat] {zip_path}: {len(internos)} archivos, sin nada del dueño "
              f"y con todo lo que hace falta para arrancar.")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verificar", metavar="ZIP", nargs="?", const=DESTINO,
                    help="revisar un ZIP ya armado en vez de armarlo")
    ap.add_argument("--owner", action="store_true",
                    help="armar además Plania_Owner_BAT.zip (no se publica)")
    ap.add_argument("--destino", default=DESTINO)
    args = ap.parse_args()

    if args.owner and not args.verificar:
        armar_owner()

    objetivo = args.verificar or armar(args.destino)
    problemas = verificar(objetivo)
    for p in problemas:
        print(f"  [!!] {p}")
    if problemas:
        print(f"\n{len(problemas)} problema(s): el paquete BAT no se puede publicar.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
