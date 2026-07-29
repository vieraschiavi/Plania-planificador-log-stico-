#!/usr/bin/env bash
# instalar-arranque.sh — deja un proyecto con la estructura .claude/ y los 6 agentes
# predeterminados del skill stack-claude-arranque.
#
# Idempotente y NO destructivo: nunca pisa un agente existente con el mismo nombre.
#
# Uso:
#   ./instalar-arranque.sh [directorio-del-proyecto]   # default: directorio actual
#
# Lo que NO hace (a propósito): no instala plug-ins ni servidores MCP. Eso toca
# credenciales y código de terceros, y va con permiso explícito del usuario.

set -euo pipefail

DESTINO="${1:-$PWD}"
ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTES_ORIGEN="$ORIGEN/templates/agents"

if [ ! -d "$DESTINO" ]; then
  echo "ERROR: el directorio '$DESTINO' no existe." >&2
  exit 1
fi

if [ ! -d "$AGENTES_ORIGEN" ]; then
  echo "ERROR: no encuentro los templates en '$AGENTES_ORIGEN'." >&2
  exit 1
fi

echo "Arranque de Claude en: $DESTINO"
echo

mkdir -p "$DESTINO/.claude/agents" "$DESTINO/.claude/skills"

copiados=0
salteados=0

for archivo in "$AGENTES_ORIGEN"/*.md; do
  nombre="$(basename "$archivo")"
  if [ -e "$DESTINO/.claude/agents/$nombre" ]; then
    echo "  SALTEADO  .claude/agents/$nombre (ya existe, no se pisa)"
    salteados=$((salteados + 1))
  else
    cp "$archivo" "$DESTINO/.claude/agents/$nombre"
    echo "  COPIADO   .claude/agents/$nombre"
    copiados=$((copiados + 1))
  fi
done

echo
echo "Agentes: $copiados copiados, $salteados salteados."
echo

# --- Verificación ---
echo "Verificación:"
total_agentes=$(find "$DESTINO/.claude/agents" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')
echo "  .claude/agents/  → $total_agentes agentes"
total_skills=$(find "$DESTINO/.claude/skills" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
echo "  .claude/skills/  → $total_skills skills"

if [ -f "$DESTINO/CLAUDE.md" ]; then
  echo "  CLAUDE.md        → existe"
else
  echo "  CLAUDE.md        → FALTA"
  echo
  echo "PENDIENTE: generá el CLAUDE.md (skill 'automatizador-proyecto', o partí de"
  echo "           templates/CLAUDE-arranque.md) y verificá que la tabla de comandos"
  echo "           sean los comandos REALES de este repo antes de commitearlo."
fi

echo
echo "Personalizá .claude/agents/especialista.md con el dominio real del proyecto:"
echo "sin eso es solo un worker genérico más."
