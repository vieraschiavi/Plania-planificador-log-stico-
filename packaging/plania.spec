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

# REPO es siempre el repositorio real: de ahí salen packaging/plania_launcher.py
# y el ícono, y ahí corre pyinstaller (cwd).
#
# FUENTE es de dónde se toman app/, plania/, data/, assets/, docs/ para
# empaquetar. Normalmente es el mismo REPO (build local, sin proteger). Para
# la release oficial, packaging/build_release.py apunta FUENTE a la copia
# "protegida" que deja packaging/proteger_codigo.py — donde el código de
# negocio de plania/ ya no son archivos .py legibles sino extensiones
# compiladas (.pyd), así el ejecutable que se distribuye no trae el código
# fuente en texto plano. Ver packaging/proteger_codigo.py para el porqué.
REPO = os.path.abspath(os.getcwd())
ROOT = os.environ.get("PLANIA_BUILD_FUENTE", REPO)

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

# backend_venta NO va acá a propósito: es el servidor de venta del
# Licenciante (licencias, checkout de MercadoPago), no algo que el cliente
# necesite ni deba recibir. Antes se empaquetaba sin razón — cada instalador
# y cada demo descargada llevaba el código fuente del backend de venta
# adentro. Ver proteger_codigo.py para el resto de lo que esto corrige.
# Lo que solo usa el dueño del producto no viaja en un build de cliente.
# Normalmente esto ya lo sacó proteger_codigo.py del árbol de origen; el
# filtro está igual acá porque el .spec también se corre solo, con
# --sin-proteger o a mano, y en ese caso el árbol es el repo entero.
# Tiene que estar en los dos lados o hay un camino por el que se cuela.
_EDICION = os.environ.get("PLANIA_EDICION", "cliente")
_SOLO_OWNER = {
    "app": {"owner.py"},
    "plania": {"owner.py", "negocio.py", "contenido.py", "verificacion.py"},
}


def _sin_lo_del_dueno(carpeta, ruta):
    """(origen, destino) de cada archivo de la carpeta, salteando lo del dueño."""
    prohibidos = _SOLO_OWNER.get(carpeta, set())
    pares = []
    for base, _dirs, archivos in os.walk(ruta):
        rel = os.path.relpath(base, ruta)
        for archivo in archivos:
            if rel == "." and archivo in prohibidos:
                continue
            destino = carpeta if rel == "." else os.path.join(carpeta, rel)
            pares.append((os.path.join(base, archivo), destino))
    return pares


for _n in ["app", "plania", "data", "assets", "docs"]:
    par = _dir(_n)
    if not par:
        continue
    if _EDICION != "owner" and _n in _SOLO_OWNER:
        datas += _sin_lo_del_dueno(_n, par[0])
    else:
        datas.append(par)

# README.md y la EULA sueltos: documentación embebida en la pantalla de Ayuda
# y en la pantalla de aceptación de términos.
for _archivo in ["README.md", "LICENSE-EULA.md"]:
    _ruta = os.path.join(ROOT, _archivo)
    if os.path.isfile(_ruta):
        datas.append((_ruta, "."))

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
    [os.path.join(REPO, "packaging", "plania_launcher.py")],
    pathex=[REPO],
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
    # Con consola a propósito: hoy es la única forma que tiene el usuario de
    # cerrar el programa (cerrar la ventana termina el proceso). Ver el
    # docstring de packaging/plania_launcher.py — ahí además se duplica todo
    # a un archivo de log, y el modo embebido en Electron (desktop/) oculta
    # esta misma consola con `windowsHide` al lanzarla como subproceso.
    console=True,
    icon=_icon,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="Plania",
)
