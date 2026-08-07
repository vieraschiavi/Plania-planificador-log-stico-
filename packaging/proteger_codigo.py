"""
Plania · Protección del código fuente antes de empaquetar
===========================================================
Compila el motor de negocio de `plania/` (los algoritmos de sugerencias,
el copiloto, el modelo financiero, el licenciamiento, el ruteo) a
extensiones nativas con Cython, y deja una copia del repo lista para
PyInstaller donde esos módulos ya NO son archivos `.py` legibles.

Por qué hace falta esto y no alcanza con "armar el exe":
--------------------------------------------------------
`packaging/plania.spec` empaquetaba `plania/` y `backend_venta/` enteros
como carpetas de datos, sin tocar nada más. PyInstaller normalmente
compila el código a bytecode `.pyc` dentro de un archivo — ya de por sí
descompilable con herramientas como `decompyle3`, pero al menos no es
texto plano — pero acá el mecanismo era otro: como el lanzador
(`plania_launcher.py`) necesita el archivo real de `app/app.py` en disco
para que Streamlit lo ejecute (`streamlit run <ruta>`), y ese script hace
`sys.path.insert(0, base)`, el resultado era que **`plania/*.py` y
`backend_venta/*.py` quedaban sentados como texto plano dentro de cada
instalador, cada versión portable y cada demo descargada**. Bajar el
instalador y abrir la carpeta alcanzaba para leer el motor completo del
producto — el diferenciador real, no la interfaz.

Este script corrige las dos partes del problema:

  1. **`backend_venta/` deja de viajar** al cliente — nunca lo necesitó
     (ver `packaging/plania.spec`): es el servidor de venta del
     Licenciante, no algo que el comprador de una licencia deba recibir.
  2. **`plania/` se compila.** Cada módulo pasa de `.py` a una extensión
     nativa (`.pyd` en Windows, `.so` en Linux/Mac) vía Cython. Python
     importa una extensión compilada exactamente igual que un `.py` — no
     hace falta tocar un solo `import` en el resto del código — pero ya
     no hay código fuente Python para extraer: hay que reversear binario
     nativo, un problema de otra categoría.

Qué NO es esto — para no vender humo:
--------------------------------------
Cython compila a C y de ahí a nativo: no es ofuscación de texto, es
ausencia total de fuente Python. Pero **no es inviolable**. Alguien con
tiempo, un desensamblador y experiencia en ingeniería inversa de binarios
puede reconstruir la lógica igual, más lento y con más esfuerzo que
copiar y pegar un `.py`. La protección real y la que de verdad importa
para el negocio es otra: la licencia JWT que valida `backend_venta`, que
vive en el servidor del Licenciante y nunca sale de ahí. Esto sube el
costo de clonar el cliente; no lo vuelve imposible, y no reemplaza al
EULA (`LICENSE-EULA.md`) ni al circuito de licencia.

Uso:
    pip install cython
    python packaging/proteger_codigo.py
    # deja la copia protegida en build/protegido/

`packaging/build_release.py` ya lo llama solo antes de correr PyInstaller.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DESTINO = os.path.join(REPO, "build", "protegido")

# Todo lo que un cliente puede llegar a necesitar en su máquina. backend_venta
# queda afuera a propósito: es el servidor de venta, nunca corre del lado
# del cliente (ver la nota de arriba y packaging/plania.spec).
CARPETAS_A_COPIAR = ["app", "plania", "data", "assets", "docs"]
ARCHIVOS_A_COPIAR = ["README.md", "LICENSE-EULA.md"]

# El motor de negocio: lo que hace que Plania sea Plania y no un dashboard
# genérico. __init__.py y config.py quedan afuera — ver el porqué en el
# docstring del módulo.
MODULOS_PROTEGIDOS = [
    "analitica.py", "auditoria.py", "conectores.py", "contenido.py",
    "copiloto.py", "exportes.py", "licencia.py", "negocio.py",
    "owner.py", "rutas.py", "sugerencias.py", "verificacion.py",
]

# Lo que es del Licenciante y no del cliente. Es la misma idea que dejó
# `backend_venta` afuera, aplicada a lo que quedaba adentro:
#
#   app/owner.py           el panel del dueño (MRR, conversión, clientes)
#   plania/owner.py        de dónde salen esos números
#   plania/negocio.py      el modelo financiero del producto: costos,
#                          escenarios, precios, cuándo conviene contratar
#   plania/contenido.py    el kit de contenido para redes
#   plania/verificacion.py el control end-to-end, herramienta de desarrollo
#
# Compilarlos con Cython no alcanzaba: seguían viajando en cada instalador y
# en cada demo descargada. Un cliente no los necesita para nada —`app/app.py`
# no importa ninguno— y son, literalmente, cómo se gana plata con esto.
#
# Se sacan SIEMPRE, sin excepción ni edición: el producto es un solo build y
# ese archivo es el que corre el dueño y el que descarga un comprador. El
# panel del dueño se arma como programa aparte (packaging/plania_owner.spec),
# que no pasa por acá porque no sale de su máquina.
MODULOS_SOLO_OWNER = {
    "app": ["owner.py"],
    "plania": ["owner.py", "negocio.py", "contenido.py", "verificacion.py"],
}

_SETUP_PY = """\
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        {modulos!r},
        # language_level=3: si no se fija, Cython asume Python 2 y algunas
        # construcciones (división, strings) cambian de comportamiento.
        # always_allow_keywords=True: SIN esto, Cython optimiza las
        # funciones compiladas para que solo acepten argumentos posicionales
        # — rompería en silencio cualquier llamada del resto del código que
        # use argumentos con nombre, que en este proyecto son la mayoría.
        compiler_directives={{"language_level": "3", "always_allow_keywords": True}},
        build_dir="_build_c",
    ),
    script_args=["build_ext", "--inplace"],
)
"""


def _correr(cmd: list[str], cwd: str) -> None:
    print(f"[proteger] $ {' '.join(cmd)}  (en {os.path.relpath(cwd, REPO)})")
    subprocess.run(cmd, check=True, cwd=cwd)


def _verificar_cython() -> None:
    try:
        import Cython  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Falta Cython. Es una dependencia de build, no de runtime:\n"
            "  pip install cython"
        )


def quitar_lo_del_dueno(destino: str) -> list[str]:
    """Saca de la copia lo que solo usa el dueño del producto.

    Devuelve lo que sacó, para poder informarlo: un build que dice que no
    lleva el panel del dueño y no lo dice en pantalla es un build en el que
    hay que confiar a ciegas.
    """
    quitados = []
    for carpeta, archivos in MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            ruta = os.path.join(destino, carpeta, archivo)
            if os.path.exists(ruta):
                os.remove(ruta)
                quitados.append(f"{carpeta}/{archivo}")
    return quitados


def preparar_arbol(destino: str) -> str:
    """Copia lo que hace falta para armar el ejecutable a una carpeta
    aparte, y deja `destino/plania/` lista para compilarse ahí sin tocar
    el repo real."""
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino)

    # __pycache__ queda afuera de la copia. Si alguna vez se corrieron los
    # tests o la app desde el repo real, ahí quedan .pyc de los módulos que
    # se están por proteger — bytecode que se descompila con herramientas
    # comunes (decompyle3 y similares) casi al nivel del .py original.
    # Copiarlos de arrastre haría inútil todo lo demás sin que se note: el
    # binario compilado quedaría al lado del .pyc de la versión real.
    def _ignorar(_dir, nombres):
        return [n for n in nombres if n == "__pycache__" or n.endswith(".pyc")]

    for carpeta in CARPETAS_A_COPIAR:
        origen = os.path.join(REPO, carpeta)
        if os.path.isdir(origen):
            shutil.copytree(origen, os.path.join(destino, carpeta), ignore=_ignorar)
    for archivo in ARCHIVOS_A_COPIAR:
        origen = os.path.join(REPO, archivo)
        if os.path.isfile(origen):
            shutil.copy(origen, os.path.join(destino, archivo))

    quitados = quitar_lo_del_dueno(destino)
    if quitados:
        print(f"[proteger] fuera del producto: {', '.join(quitados)}")

    print(f"[proteger] árbol preparado en {os.path.relpath(destino, REPO)}")
    return destino


def compilar_plania(destino: str) -> None:
    """Cythoniza cada módulo de MODULOS_PROTEGIDOS dentro de la copia y
    borra el .py de origen — si un módulo falla en compilar, se corta acá
    (nunca se sigue dejando el .py sin proteger de contrabando: eso
    volvería inútil todo lo demás sin que se note)."""
    carpeta_plania = os.path.join(destino, "plania")

    # Los módulos del dueño ya no están: no es que falten, es que se sacaron
    # a propósito unas líneas más arriba. Se los descuenta de lo esperado para
    # que el control de abajo siga sirviendo para lo que sirve — avisar si
    # falta algo que SÍ tenía que estar.
    esperados = [m for m in MODULOS_PROTEGIDOS
                 if m not in MODULOS_SOLO_OWNER["plania"]]

    presentes = [m for m in esperados
                 if os.path.isfile(os.path.join(carpeta_plania, m))]
    faltantes = set(esperados) - set(presentes)
    if faltantes:
        raise SystemExit(f"[proteger] no están en plania/: {sorted(faltantes)} "
                         "— revisá MODULOS_PROTEGIDOS")

    # El setup corre desde `destino`, no desde `destino/plania`: cythonize
    # detecta que plania/ es un paquete (tiene __init__.py) y nombra las
    # extensiones "plania.analitica", etc. — el nombre completo, con
    # paquete. build_ext las escribe en la ruta que ese nombre implica
    # (plania/analitica...so) RELATIVA al directorio desde donde se corre;
    # si se corriera ya parado en plania/, terminaría buscando una carpeta
    # plania/plania/ que no existe.
    rutas_modulos = [os.path.join("plania", m) for m in presentes]
    setup_path = os.path.join(destino, "_setup_proteger.py")
    with open(setup_path, "w", encoding="utf-8") as f:
        f.write(_SETUP_PY.format(modulos=rutas_modulos))

    _correr([sys.executable, "_setup_proteger.py"], cwd=destino)

    compilados, faltaron = [], []
    for modulo in presentes:
        base = modulo[:-3]  # sin ".py"
        binario = [f for f in os.listdir(carpeta_plania)
                  if f.startswith(base + ".") and not f.endswith(".py")
                  and (f.endswith(".pyd") or f.endswith(".so"))]
        if binario:
            compilados.append(binario[0])
        else:
            faltaron.append(modulo)

    if faltaron:
        raise SystemExit(f"[proteger] Cython no dejó binario para: {faltaron}. "
                         "No se borra ningún .py — revisá el log de arriba.")

    # Recién ahora, con los binarios confirmados en disco, se borran los
    # fuentes. El orden importa: comprobar antes de borrar, no al revés.
    for modulo in presentes:
        os.remove(os.path.join(carpeta_plania, modulo))

    # Limpieza de lo que Cython/setuptools dejan de paso (.c intermedios,
    # carpeta build, el setup temporal): no aportan nada al ejecutable y
    # los .c SÍ son legibles como el propio .py, así que si quedaran
    # adentro del bundle habría que protegerlos igual que los .py. Todo
    # esto queda a nivel de `destino`, no de `destino/plania`, porque el
    # setup corrió desde ahí (ver el comentario más arriba).
    shutil.rmtree(os.path.join(destino, "_build_c"), ignore_errors=True)
    shutil.rmtree(os.path.join(destino, "build"), ignore_errors=True)
    os.remove(setup_path)
    for f in os.listdir(carpeta_plania):
        if f.endswith(".c"):
            os.remove(os.path.join(carpeta_plania, f))

    print(f"[proteger] {len(compilados)} módulo(s) compilados y su .py borrado: "
         f"{sorted(compilados)}")


def _barrer_pycache(destino: str) -> None:
    """Última pasada: nada de __pycache__ tiene que llegar al bundle. No
    protege nada por sí sola (cualquier .pyc que quede acá sería de módulos
    NO protegidos), pero un .pyc de un módulo protegido acá sería la señal
    de que algo en el proceso lo volvió a importar sin querer después de
    compilarlo — y por eso el control de abajo, además de barrer, falla
    fuerte si encuentra justamente eso."""
    protegidos_con_pyc = []
    for base, dirs, files in os.walk(destino):
        if "__pycache__" in dirs:
            cache = os.path.join(base, "__pycache__")
            if os.path.basename(base) == "plania":
                for f in os.listdir(cache):
                    nombre = f.split(".cpython")[0]
                    if f"{nombre}.py" in MODULOS_PROTEGIDOS:
                        protegidos_con_pyc.append(f)
            shutil.rmtree(cache)
            dirs.remove("__pycache__")
    if protegidos_con_pyc:
        raise SystemExit(
            f"[proteger] había bytecode (.pyc) de módulos protegidos en "
            f"__pycache__: {protegidos_con_pyc}. Se descompila casi como el "
            f".py original — no se puede dejar pasar. Revisá de dónde salió "
            f"(¿algo importó plania/ antes de terminar de compilar?) antes "
            f"de volver a correr esto.")


def main() -> str:
    _verificar_cython()
    destino = os.environ.get("PLANIA_BUILD_FUENTE", DEFAULT_DESTINO)
    preparar_arbol(destino)
    compilar_plania(destino)
    _barrer_pycache(destino)

    # Control final: que no haya quedado ningún .py de los protegidos, sea
    # por lo que sea. Es la última barrera antes de que esto se distribuya.
    carpeta_plania = os.path.join(destino, "plania")
    filtrados = [m for m in MODULOS_PROTEGIDOS
                if os.path.exists(os.path.join(carpeta_plania, m))]
    if filtrados:
        raise SystemExit(f"[proteger] quedaron sin proteger: {filtrados}")

    # Y que lo del dueño no se haya colado en el producto, ni como .py ni ya
    # compilado: compilar no sirve de nada si igual se distribuye.
    colados = []
    for carpeta, archivos in MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            base = os.path.splitext(archivo)[0]
            dir_ = os.path.join(destino, carpeta)
            if not os.path.isdir(dir_):
                continue
            colados += [f"{carpeta}/{n}" for n in os.listdir(dir_)
                        if n == archivo or n.startswith(base + ".")]
    if colados:
        raise SystemExit(f"[proteger] esto es del dueño y quedó en el "
                         f"producto: {colados}")

    print(f"\n[proteger] listo: {os.path.relpath(destino, REPO)}")
    print("  Para usarlo: PLANIA_BUILD_FUENTE=<esta carpeta> "
         "pyinstaller packaging/plania.spec --noconfirm")
    return destino


if __name__ == "__main__":
    main()
