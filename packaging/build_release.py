"""
Plania · Build de release para PC (Windows)
===========================================
Arma el programa instalable a partir del repo:

  1. Genera la base demo (para que el instalador traiga datos de ejemplo).
  2. Protege el código de negocio: compila plania/ con Cython a extensiones
     nativas (ver packaging/proteger_codigo.py) para que el ejecutable no
     lleve el .py legible. Se puede saltear con --sin-proteger para
     iterar rápido en una máquina de desarrollo.
  3. Corre PyInstaller con `packaging/plania.spec` → dist/Plania/ (onedir),
     apuntado a la copia protegida.
  4. Si Inno Setup (ISCC.exe) está instalado, compila el instalador
     → dist/Plania_Setup_vX.exe, y deja una copia sin versión en el nombre
     en dist/Plania_Setup.exe (es la ruta por defecto que sirve
     backend_venta/app.py en la descarga post-pago).
  5. Siempre deja también un ZIP portable (dist/Plania_portable.zip) que
     corre con doble clic en Plania.exe, sin instalar nada.

Uso (en Windows, con Python 3.11+ y
`pip install -r requirements.txt pyinstaller cython`):

    python packaging/build_release.py
    python packaging/build_release.py --sin-proteger   # build rápido, sin Cython
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SIN_PROTEGER = "--sin-proteger" in sys.argv

# El producto NO tiene ediciones: se arma una sola vez y ese archivo es el que
# usan tanto el dueño como cualquiera que lo compre. Antes había una edición
# "owner" del producto, con el panel del negocio adentro, y eso significaba que
# el dueño probaba un programa distinto del que recibían sus clientes.
#
# El panel del negocio se arma aparte, como programa propio, con --con-owner.
CON_OWNER = "--con-owner" in sys.argv


def _run(cmd: list[str]) -> None:
    print(f"[build] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paso_datos_demo() -> None:
    _run([sys.executable, os.path.join("data", "generate_dataset.py"), "--seed", "42"])


def paso_proteger_codigo() -> str | None:
    """Compila plania/ con Cython. Devuelve la carpeta protegida, o None si
    se pidió --sin-proteger (build de desarrollo, sin la protección)."""
    if SIN_PROTEGER:
        print("[build] --sin-proteger: el ejecutable va a llevar plania/ como "
              ".py legible. No usar este build para distribuir.")
        return None
    import proteger_codigo  # packaging/ ya está en sys.path por __file__
    return proteger_codigo.main()


def paso_pyinstaller(fuente: str | None) -> str:
    env = dict(os.environ)
    if fuente:
        env["PLANIA_BUILD_FUENTE"] = fuente
    print(f"[build] $ pyinstaller packaging/plania.spec  "
          f"(fuente: {os.path.relpath(fuente, ROOT) if fuente else ROOT})")
    subprocess.run([sys.executable, "-m", "PyInstaller",
                    os.path.join("packaging", "plania.spec"), "--noconfirm"],
                   check=True, cwd=ROOT, env=env)
    salida = os.path.join(DIST, "Plania")
    if not os.path.isdir(salida):
        raise SystemExit("PyInstaller no dejó dist/Plania — revisá el log de arriba.")
    return salida


def paso_instalador() -> str | None:
    iscc = shutil.which("ISCC") or shutil.which("iscc") or \
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not (shutil.which("ISCC") or shutil.which("iscc") or os.path.exists(iscc)):
        print("[build] Inno Setup no encontrado — salteo el Setup.exe "
              "(el ZIP portable igual se genera).")
        return None
    _run([iscc, os.path.join("packaging", "instalador.iss")])
    versionado = next((os.path.join(DIST, f) for f in os.listdir(DIST)
                       if f.startswith("Plania_Setup_v") and f.endswith(".exe")), None)
    if not versionado:
        return None
    # backend_venta/app.py sirve PLANIA_INSTALADOR_PATH, y si no está seteada
    # cae a dist/Plania_Setup.exe (sin versión) — sin esta copia esa ruta por
    # defecto nunca existe y la descarga post-pago queda rota hasta que
    # alguien setee la variable a mano. Con la copia, funciona apenas se
    # corre este script, y ANTES ya queda el .exe versionado para archivar.
    estable = os.path.join(DIST, "Plania_Setup.exe")
    shutil.copy2(versionado, estable)
    return versionado


def paso_zip(carpeta: str) -> str:
    zpath = os.path.join(DIST, "Plania_portable.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(carpeta):
            for f in files:
                ruta = os.path.join(base, f)
                z.write(ruta, os.path.relpath(ruta, os.path.dirname(carpeta)))
    return zpath


def paso_owner() -> str | None:
    """Arma "Plania Owner", el panel del negocio, como programa aparte.

    No pasa por proteger_codigo.py: ese paso existe para que el código de
    negocio no viaje en texto plano a máquinas ajenas, y este ejecutable no
    sale de la máquina del dueño.
    """
    print("[build] $ pyinstaller packaging/plania_owner.spec")
    subprocess.run([sys.executable, "-m", "PyInstaller",
                    os.path.join("packaging", "plania_owner.spec"), "--noconfirm"],
                   check=True, cwd=ROOT)
    carpeta = os.path.join(DIST, "Plania Owner")
    if not os.path.isdir(carpeta):
        raise SystemExit("PyInstaller no dejó 'dist/Plania Owner'.")
    zpath = os.path.join(DIST, "Plania_Owner.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(carpeta):
            for f in files:
                ruta = os.path.join(base, f)
                z.write(ruta, os.path.relpath(ruta, os.path.dirname(carpeta)))
    return zpath


def paso_paquete_bat() -> str:
    """La segunda vía de entrega: mismo producto, arrancado con un .bat.

    Existe para las empresas donde IT no deja ejecutar un .exe bajado de
    internet. Se arma acá y no sólo en el workflow para que un build local
    deje las DOS formas de entregar el producto, no una.
    """
    import armar_paquete_bat  # packaging/ ya está en sys.path por __file__
    if CON_OWNER:
        armar_paquete_bat.armar_owner()
    zpath = armar_paquete_bat.armar()
    problemas = armar_paquete_bat.verificar(zpath)
    if problemas:
        for p in problemas:
            print(f"  [!!] {p}")
        raise SystemExit("El paquete BAT no se puede publicar.")
    return zpath


def main() -> None:
    print("[build] producto: un solo build, idéntico para el dueño y para "
          "quien lo compre (sin el panel del negocio adentro)")
    paso_datos_demo()
    fuente_protegida = paso_proteger_codigo()
    carpeta = paso_pyinstaller(fuente_protegida)
    setup = paso_instalador()
    zpath = paso_zip(carpeta)
    bat_zip = paso_paquete_bat()
    owner_zip = paso_owner() if CON_OWNER else None
    print("\n[build] Listo:")
    for p in filter(None, [setup, zpath, bat_zip, owner_zip]):
        print(f"  {p}\n    sha256: {_sha256(p)}")
    if owner_zip:
        print("  ! Plania_Owner.zip y Plania_Owner_BAT.zip son tuyos: no se "
              "publican ni se suben a la página de descargas.")
    if setup:
        print(f"  {os.path.join(DIST, 'Plania_Setup.exe')}  (copia sin versión "
              f"en el nombre — es la que sirve PLANIA_INSTALADOR_PATH por defecto)")
    if SIN_PROTEGER:
        print("\n! Build SIN proteger (--sin-proteger): no distribuir este .exe/.zip.")
    print("\nEl backend de venta sirve dist/Plania_Setup.exe por defecto para "
          "la descarga post-pago (/descargar/{token}); para publicar desde "
          "otra ruta, seteá PLANIA_INSTALADOR_PATH.")


if __name__ == "__main__":
    main()
