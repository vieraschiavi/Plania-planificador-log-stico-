# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec de "Plania Owner": el panel del negocio, como programa
aparte del producto.

    pyinstaller packaging/plania_owner.spec --noconfirm

Este ejecutable NO se distribuye. Se instala solo en la máquina del dueño y
es lo único que lleva `app/owner.py`, `plania/owner.py`, `plania/negocio.py`,
`plania/contenido.py` y `plania/verificacion.py` — o sea, la facturación, los
clientes, el modelo financiero y el motor de contenido.

Que sea un programa separado es lo que permite que el Plania del dueño y el
Plania de un comprador sean el mismo archivo: no hay una "edición del dueño"
del producto que probar aparte.

A diferencia de `plania.spec`, acá no se pasa por `proteger_codigo.py`: ese
paso existe para que el código de negocio no viaje en texto plano hacia
máquinas ajenas, y este ejecutable no sale de la máquina del dueño.
"""
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

REPO = os.path.abspath(os.getcwd())
ROOT = REPO   # sin árbol protegido: este .exe no se distribuye

_PAQUETES = [
    "streamlit", "plotly", "altair", "pandas", "numpy",
    "pyarrow", "xlsxwriter", "openpyxl", "sqlalchemy",
    "fastapi", "starlette", "uvicorn", "fpdf", "docx",
]
datas, binaries, hiddenimports = [], [], []
for _pkg in _PAQUETES:
    try:
        d, b, h = collect_all(_pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

for _pkg in ["streamlit", "altair", "plotly", "pandas", "numpy", "pyarrow"]:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass


def _dir(nombre):
    ruta = os.path.join(ROOT, nombre)
    return (ruta, nombre) if os.path.isdir(ruta) else None


# Acá va TODO, incluido lo del dueño: es el único build que lo lleva.
for _n in ["app", "plania", "data", "assets", "docs"]:
    par = _dir(_n)
    if par:
        datas.append(par)

for _archivo in ["README.md", "LICENSE-EULA.md"]:
    _ruta = os.path.join(ROOT, _archivo)
    if os.path.isfile(_ruta):
        datas.append((_ruta, "."))

hiddenimports += [
    "plania", "plania.analitica", "plania.apariencia", "plania.auditoria",
    "plania.conectores", "plania.config", "plania.contenido", "plania.copiloto",
    "plania.exportes", "plania.licencia", "plania.negocio", "plania.owner",
    "plania.rutas", "plania.sugerencias", "plania.verificacion",
    "data.generate_dataset",
    "ventana",
]

_PATHEX_EXTRA = [os.path.join(REPO, "packaging")]
_ICON = os.path.join(ROOT, "assets", "brand", "plania.ico")
_icon = _ICON if os.path.exists(_ICON) else None

block_cipher = None

a = Analysis(
    [os.path.join(REPO, "packaging", "entrada_owner.py")],
    pathex=[REPO] + _PATHEX_EXTRA,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "referencia_R"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Plania Owner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=_icon,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="Plania Owner",
)
