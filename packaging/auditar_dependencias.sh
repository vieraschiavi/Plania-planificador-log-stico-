#!/usr/bin/env bash
# Plania · Auditoría de CVEs en dependencias de terceros
# =======================================================
# No hay carpetas vendor/ ni lib/ en este repo — nada de código de terceros
# vive commiteado — así que "auditar lo vendorizado" acá significa auditar
# los DOS árboles de dependencias reales: el de Python (requirements.txt,
# vía pip-audit) y el de Electron/React (desktop/package-lock.json, vía
# npm audit). Este script deja los dos resultados como evidencia reproducible
# en vez de depender de que alguien lo haya corrido una vez y lo recuerde.
#
#   packaging/auditar_dependencias.sh
#
# El resultado de la última corrida y el análisis de cada hallazgo (por qué
# se corrigió, por qué no, o por qué no aplica) están documentados en
# docs/AUDITORIA_SEGURIDAD.md — este script no reemplaza esa lectura, la
# alimenta.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Python (requirements.txt) =="
pip install -q pip-audit 2>/dev/null || true
pip-audit -r "$RAIZ/requirements.txt" || true

echo
echo "== Electron/React (desktop/) =="
(cd "$RAIZ/desktop" && npm audit) || true
