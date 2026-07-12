"""
Plania · Build de release para PC (Windows)
===========================================
Arma el programa instalable a partir del repo:

  1. Genera la base demo (para que el instalador traiga datos de ejemplo).
  2. Corre PyInstaller con `packaging/plania.spec` → dist/Plania/ (onedir).
  3. Si Inno Setup (ISCC.exe) está instalado, compila el instalador
     → dist/Plania_Setup_vX.exe.
  4. Siempre deja también un ZIP portable (dist/Plania_portable.zip) que
     corre con doble clic en Plania.exe, sin instalar nada.

Uso (en Windows, con Python 3.11+ y `pip install -r requirements.txt pyinstaller`):

    python packaging/build_release.py
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


def paso_pyinstaller() -> str:
    _run([sys.executable, "-m", "PyInstaller",
          os.path.join("packaging", "plania.spec"), "--noconfirm"])
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
    for f in os.listdir(DIST):
        if f.startswith("Plania_Setup") and f.endswith(".exe"):
            return os.path.join(DIST, f)
    return None


def paso_zip(carpeta: str) -> str:
    zpath = os.path.join(DIST, "Plania_portable.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(carpeta):
            for f in files:
                ruta = os.path.join(base, f)
                z.write(ruta, os.path.relpath(ruta, os.path.dirname(carpeta)))
    return zpath


def main() -> None:
    paso_datos_demo()
    carpeta = paso_pyinstaller()
    setup = paso_instalador()
    zpath = paso_zip(carpeta)
    print("\n[build] Listo:")
    for p in filter(None, [setup, zpath]):
        print(f"  {p}\n    sha256: {_sha256(p)}")
    print("\nPublicá el Setup.exe donde apunte PLANIA_INSTALADOR_PATH del "
          "backend de venta para habilitar la descarga post-pago.")


if __name__ == "__main__":
    main()
