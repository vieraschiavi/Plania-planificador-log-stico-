# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Preparación de la base demo para los tests
===================================================
`data/erp_demo.db` no está versionada (`.gitignore`: `data/*.db`): la genera
`data/generate_dataset.py` con semilla fija. Eso hace que el CI y la máquina de
quien programa puedan estar mirando bases distintas, y ahí aparece el peor
resultado posible: verde local, rojo en CI.

Pasó de verdad. Varios tests comparan números del sitio contra lo que hoy
calcula el motor sobre la base demo (por ejemplo
`test_las_cinco_sugerencias_tienen_ejemplo_numerico_real`). El CI genera la
base de cero en cada corrida; local quedaba la de hace semanas, anterior a un
cambio del generador. La suite daba 225 en verde acá y el mismo commit fallaba
en CI — y el PR se mergeó con main quedando en rojo.

Así que la base se regenera sola cuando quedó vieja respecto del generador. No
es una comodidad: es lo que hace que "pasa en mi máquina" signifique algo.
"""
from __future__ import annotations

import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERADOR = os.path.join(RAIZ, "data", "generate_dataset.py")
BASE = os.path.join(RAIZ, "data", "erp_demo.db")
SEMILLA = "42"


def _hay_que_regenerar() -> str:
    """Motivo por el que hay que regenerar, o cadena vacía si está al día."""
    if not os.path.exists(BASE):
        return "no existe"
    if os.path.getmtime(BASE) < os.path.getmtime(GENERADOR):
        # Se compara contra el generador y no contra el motor: el motor puede
        # cambiar cómo CALCULA sin cambiar los datos, y en ese caso la base
        # sigue siendo válida. Lo que la invalida es que cambien los datos.
        return "es anterior al generador"
    return ""


def pytest_configure(config):
    motivo = _hay_que_regenerar()
    if not motivo:
        return
    print(f"\n[plania] La base demo {motivo}: regenerando con semilla {SEMILLA}.")
    r = subprocess.run([sys.executable, GENERADOR, "--seed", SEMILLA],
                       cwd=RAIZ, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            "No se pudo generar data/erp_demo.db, así que los tests que "
            "comparan contra ella medirían cualquier cosa:\n"
            + r.stdout + r.stderr)
