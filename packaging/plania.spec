# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para el programa standalone de Plania (Windows, onedir).
Empaqueta el intérprete Python, todas las dependencias (Streamlit, scikit-learn,
plotly, pandas, FastAPI…) y el código/datos de Plania en dist/Plania/, que
luego el instalador Inno Setup convierte en Plania_Setup.exe.

Construir (en Windows):
    pyinstaller packaging/plania.spec --noconfirm
"""
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.getcwd())

# --- Dependencias que necesitan recolección completa (datos + submódulos) ---
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

# Metadata que algunas libs leen en runtime (importlib.metadata)
for _pkg in ["streamlit", "altair", "plotly", "pandas", "numpy", "pyarrow"]:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

# --- Código y recursos propios de Plania ---
def _dir(nombre):
    ruta = os.path.join(ROOT, nombre)
    return (ruta, nombre) if os.path.isdir(ruta) else None

for _n in ["app", "plania", "backend_venta", "data", "assets", "docs"]:
    par = _dir(_n)
    if par:
        datas.append(par)

# README.md suelto: documentación embebida en la pantalla de Ayuda
_readme = os.path.join(ROOT, "README.md")
if os.path.isfile(_readme):
    datas.append((_readme, "."))

hiddenimports += [
    "plania", "plania.analitica", "plania.auditoria", "plania.conectores",
    "plania.config", "plania.copiloto", "plania.exportes", "plania.licencia",
    "plania.rutas", "plania.sugerencias",
    "data.generate_dataset",
]

_ICON = os.path.join(ROOT, "assets", "brand", "plania.ico")
_icon = _ICON if os.path.exists(_ICON) else None

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "packaging", "plania_launcher.py")],
    pathex=[ROOT],
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
    name="Plania",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # muestra una consola con el log del server
    icon=_icon,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="Plania",
)
