---
name: stack-claude-arranque
description: >
  Arranque estándar de CUALQUIER proyecto nuevo con Claude Code: deja el repo con el stack de
  capacidades completo (plug-ins, skills, servidores MCP/conectores) + el set de AGENTES
  PREDETERMINADOS (explorer, planificador, parallel-worker, especialista, revisor, verificador) +
  el modelo mental agente = modelo + harness. ACTIVAR SIEMPRE al empezar un proyecto o repo nuevo,
  y cuando el usuario diga "arrancar proyecto", "proyecto nuevo", "configurá Claude acá",
  "qué instalo en Claude", "24 cosas que instalar", "plug-ins", "qué skills me convienen",
  "servidores MCP", "conectores", "agentes predeterminados", "dejá esto listo para trabajar",
  "stack de Claude", "estoy usando Claude al 10%". GENÉRICO: cero hardcode de empresa, infra o
  credenciales. NUNCA instalar un plug-in/MCP de terceros sin verificar fuente y sin permiso
  explícito del usuario; NUNCA declarar el arranque completo sin el checklist verificado archivo
  por archivo.
---

# Stack de arranque de Claude — capacidades + agentes predeterminados

Objetivo: que **todo proyecto nuevo arranque al 100% de la capacidad de Claude**, no al 10%. Tres
capas de capacidad + una capa de agentes, siempre en el mismo orden, siempre verificadas.

## Modelo mental (base de todo)

```
agente = modelo + harness
```

- **Modelo**: piensa, analiza, decide. No toca nada.
- **Harness**: ejecuta, observa, aplica permisos y límites. Es lo que convierte texto en acción.
- **Entorno**: archivos, tests, comandos, estado.

Loop: instrucción → el modelo solicita acción → el harness la ejecuta sobre el entorno → devuelve
resultado → el modelo re-decide. **Todo lo que agregás en el arranque (plug-ins, skills, MCP,
agentes) es harness.** Ampliar el harness es lo que sube la capacidad real; el modelo ya está.

Consecuencia práctica: si una tarea falla, preguntá primero *"¿le falta harness o le falta
contexto?"* antes de tocar el prompt. Fundamentos completos en `references/fundamentos-agentes.md`.

## Las 4 capas del arranque

| Capa | Qué es | Dónde vive | Cuándo se toca |
|---|---|---|---|
| 1. **Contexto** | `CLAUDE.md`, permisos, hooks | repo | Siempre, primero |
| 2. **Agentes** | subagentes con rol y tools acotadas | `.claude/agents/*.md` | Siempre (set predeterminado) |
| 3. **Skills** | comandos de una línea que ejecutan flujos completos | `.claude/skills/*/SKILL.md` | Siempre (set base) + los del dominio |
| 4. **Plug-ins / MCP** | equipos completos y conectores a herramientas reales | global (`/plugin`, `claude mcp add`) | Solo con permiso explícito del usuario |

Las capas 1-3 son **del repo y versionadas**. La capa 4 es **global de la máquina** y toca
credenciales: nunca se instala sola.

## Protocolo de arranque (orden fijo)

1. **Detectar** — ¿hay `CLAUDE.md`? ¿`.claude/agents/`? ¿`.claude/skills/`? ¿qué stack es el repo
   (lenguaje, gestor de deps, cómo se corren los tests)? Sin esto no se escribe nada.
2. **Capa 1 — Contexto.** Si no hay `CLAUDE.md`, generarlo (delegá en `automatizador-proyecto` si
   está instalado; si no, usá `templates/CLAUDE-arranque.md` como esqueleto). Debe incluir: qué es,
   stack, tabla de comandos reales del repo, estructura, flujo plan→cambio→test→ship, do/don't.
3. **Capa 2 — Agentes predeterminados.** Copiar los 6 de `templates/agents/` a `.claude/agents/`
   (ver tabla abajo). **No pisar** un agente existente con el mismo nombre: si ya está, dejarlo y
   reportarlo. Personalizar `especialista.md` con el dominio real del repo.
4. **Capa 3 — Skills base.** Instalar el set base (tabla abajo) desde la librería del usuario
   (`claude-skills/skills/`) o desde su fuente. Solo las que aplican al repo.
5. **Capa 4 — Plug-ins y MCP.** **Nunca sin permiso.** Presentar el catálogo priorizado de
   `references/catalogo.md`, marcar cuáles ya están activos, y esperar que el usuario elija.
6. **Verificar** — checklist de abajo, archivo por archivo. Sin esto no se declara terminado.
7. **Reportar** — tabla: capa | qué se creó | evidencia | estado (OK / PARCIAL / OMITIDO + motivo).

## Agentes predeterminados (capa 2)

Los 6 templates de `templates/agents/`. Genéricos, sin hardcode, tools acotadas por rol:

| Agente | Rol | Tools | Cuándo lo llama Claude |
|---|---|---|---|
| `explorer` | Barre el repo a lo ancho y devuelve un mapa, no dumps | Read, Grep, Glob, Bash | Entender el proyecto sin quemar contexto |
| `planificador` | Convierte un pedido en plan de implementación con archivos y riesgos | Read, Grep, Glob | Antes de cualquier cambio no trivial |
| `parallel-worker` | Tarea acotada e independiente, para fan-out | Read, Edit, Write, Bash, Grep, Glob | El mismo cambio en N archivos/módulos |
| `especialista` | Dominio del repo (se personaliza en el paso 3) | Read, Edit, Write, Bash, Grep, Glob | Cambios sensibles del núcleo |
| `revisor` | Code review del diff: bugs, seguridad, regresiones | Read, Grep, Glob, Bash | Antes de commitear/PR |
| `verificador` | Gate de evidencia: corre tests/build y pega la salida real | Read, Bash, Grep, Glob | Antes de declarar algo terminado |

Regla: `revisor` y `verificador` **no editan código** — si pudieran arreglar lo que revisan, dejan
de ser un control independiente.

## Skills base (capa 3)

| Skill | Para qué | Prioridad |
|---|---|---|
| `automatizador-proyecto` | Genera CLAUDE.md, permisos, hooks, comandos del repo | Alta — hace la capa 1 |
| `loop-engine` | Loop cerrado hasta que algo funciona de verdad | Alta — verificación por evidencia |
| `test-driven-development` / `systematic-debugging` | Metodología de dev y debug en 4 fases | Alta si el repo tiene tests |
| `output-qa-validator` | QA de cualquier entregable antes de mostrarlo | Alta si el repo produce reportes |
| `skill-creator` / `fabrica-skills` | Empaquetar un workflow repetido como skill nuevo | Media — cuando aparece el patrón |
| `frontend-design` | Que la UI no parezca template de IA | Media — solo si hay front |

## Verificación (gate, no opcional)

```bash
# Capa 1
test -f CLAUDE.md && echo "CLAUDE.md OK"
# Capa 2 — deben estar los 6
ls .claude/agents/*.md | wc -l
# Capa 3
ls .claude/skills/
# Capa 4 (global, informativo)
claude mcp list
```

Además: **abrir** el `CLAUDE.md` generado y confirmar que la tabla de comandos son los comandos
reales del repo (no plantilla). Un `CLAUDE.md` con comandos inventados es peor que no tenerlo.

## Anti-patrones (rechazar)

- Instalar un plug-in o MCP de terceros **sin permiso del usuario** o sin verificar la fuente: son
  código y credenciales de otro corriendo en tu máquina. Ver el gate de seguridad del catálogo.
- Copiar un `CLAUDE.md` genérico con comandos que el repo no tiene.
- Pisar agentes o skills existentes del proyecto.
- Declarar el arranque completo sin correr el checklist.
- Meter datos de empresa, servidores o credenciales en templates que se van a reusar en otros repos.
- Instalar las 4 capas completas en un repo de 3 archivos: escalá al tamaño real del proyecto.

## Registro en el router maestro

Para que este skill dispare solo en todo proyecto nuevo, agregá esta fila a la tabla de
enrutamiento de `maestro-unificado-es` (ese skill vive solo en `~/.claude/skills`, no se versiona
acá porque referencia infra interna):

```
| `stack-claude-arranque` | Arranque de proyecto nuevo: 4 capas (contexto → agentes predeterminados
→ skills base → plug-ins/MCP) + fundamentos `agente = modelo + harness` | "proyecto nuevo",
"arrancar proyecto", "configurá Claude acá", "qué instalo en Claude", "plug-ins", "servidores MCP",
"conectores", "agentes predeterminados" | **Muy alta — corre PRIMERO en todo repo sin
`.claude/agents/`** |
```

También está enganchado como **Módulo 0** de `all-in-one-tech-team`.

## Referencias

- `references/catalogo.md` — catálogo de plug-ins, skills y servidores MCP (con gate de seguridad).
- `references/fundamentos-agentes.md` — fundamentos de agentes IA: modelo + harness, agent loop,
  controles de generación, prompting, tools.
- `templates/agents/` — los 6 agentes predeterminados, listos para copiar.
- `templates/CLAUDE-arranque.md` — esqueleto de CLAUDE.md.
- `scripts/instalar-arranque.sh` — copia agentes + arma la estructura `.claude/` (idempotente).
