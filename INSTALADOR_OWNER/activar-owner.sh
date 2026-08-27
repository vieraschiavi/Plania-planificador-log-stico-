#!/usr/bin/env bash
# © 2026 Martín Viera. Todos los derechos reservados.
#
# Plania · Activar la VERSIÓN FULL (edición del dueño) en Linux/macOS.
# El equivalente de ACTIVAR-OWNER.bat, que es el que se usa en Windows.
#
#   ./INSTALADOR_OWNER/activar-owner.sh              # activar
#   ./INSTALADOR_OWNER/activar-owner.sh --estado
#   ./INSTALADOR_OWNER/activar-owner.sh --desactivar
#
# No trae ninguna licencia adentro: la emite en esta máquina. Ver LEEME.md.
set -euo pipefail

# Igual que el .bat: se trabaja desde la raíz del repositorio para reusar el
# mismo entorno que usa run.sh, no un segundo venv que después diverge.
cd "$(dirname "$0")/.."

echo
echo "  ============================================"
echo "   PLANIA - ACTIVAR VERSION FULL"
echo "  ============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "  [X] No se encontró python3. Instalá Python 3.11+ y volvé a correr esto."
  exit 1
fi

# Se comprueba una dependencia de cada lado del circuito (el backend que firma
# y el cliente HTTP que lo consulta) en vez de correr `pip install` siempre:
# reinstalar en cada activación tarda y no hace falta.
if ! python3 -c "import fastapi, jwt, httpx" >/dev/null 2>&1; then
  echo "  [1/2] Faltan dependencias, instalando..."
  python3 -m pip install --quiet -r requirements.txt
else
  echo "  [1/2] Dependencias ya instaladas."
fi

echo "  [2/2] Emitiendo y activando la licencia..."
python3 INSTALADOR_OWNER/activar_owner.py "$@"
