# Catálogo de capacidades — plug-ins, skills y servidores MCP

Fuente: recopilación pública de comunidad ("24 cosas que instalar en Claude": 8 plug-ins,
8 skills, 8 servidores MCP). **Los nombres, las descripciones y los contadores de instalación
son de esa recopilación, no verificados uno por uno.** Antes de instalar cualquier ítem, aplicar
el gate de seguridad de abajo.

---

## Gate de seguridad (antes de instalar CUALQUIER cosa de esta lista)

Un plug-in o un servidor MCP **es código de un tercero corriendo con tus permisos**, y varios MCP
además piden tokens de cuentas reales (Slack, Notion, LinkedIn, mail). No es lo mismo que una skill,
que es texto.

Checklist obligatorio, por ítem:

1. **Fuente identificada** — repo/marketplace concreto, autor, licencia. Si no se puede
   identificar, **no se instala**. Un nombre en una captura no es una fuente.
2. **Permiso explícito del usuario** — decir qué hace, qué permisos pide y qué datos toca. Esperar
   el sí. Nunca instalar "de paso" durante otra tarea.
3. **Alcance de credenciales** — preferir tokens de solo-lectura y del scope mínimo. Nunca pegar
   una credencial en el repo ni en un archivo de skill.
4. **Solape** — si ya tenés algo que hace lo mismo (ver columna "¿Ya lo tenés?"), no sumes una
   segunda fuente de verdad para el mismo dominio: elegí una.
5. **Verificación post-instalación** — `/plugin` o `claude mcp list` y una llamada real de prueba.
   Sin salida real, el ítem queda **PARCIAL**, no instalado.

Comandos (Claude Code):

```bash
/plugin                       # explorar / instalar / desinstalar plug-ins
/plugin marketplace add <owner/repo>   # agregar el marketplace de origen
claude mcp add <nombre> ...   # agregar un servidor MCP
claude mcp list               # verificar qué quedó activo
```

> El marketplace exacto de cada plug-in de abajo **no está en la fuente original** — pedíselo al
> usuario o buscalo antes de correr `marketplace add`. No adivines la URL.

---

## 1. Plug-ins — equipos completos de especialistas

Una instalación agrega un equipo entero (varias skills + comandos + agentes).

| # | Plug-in | Qué aporta | ¿Ya lo tenés? | Prioridad |
|---|---|---|---|---|
| 01 | `gstack` | 23 herramientas: equipo de desarrollo completo | Parcial — QA/TDD ya cubierto por `ml-ds-superpowers` y `superpowers` | Media |
| 02 | `superpoderes` (superpowers) | Metodología de desarrollo completa, 14 skills (brainstorm → plan → TDD → review → verify) | **Sí** — las 14 ya están en `claude-skills/skills/` | Ya cubierto |
| 03 | `codex-plugin-cc` | Plug-in de Codex (OpenAI) dentro de Claude Code | No | Baja — solo si querés segunda opinión de otro modelo |
| 04 | `servicios-financieros` | Banca de inversión, equity research, capital privado, patrimonio | No | **Alta** si trabajás en `M-Inversiones-IA` |
| 05 | `claude-para-legal` | Flujos de trabajo legales por área de práctica | No | Baja |
| 06 | `skills-de-claude` | Catálogo de 263+ skills de todas las plataformas | No (tenés tu propia librería) | Media — como fuente de ideas |
| 07 | `skills-de-marketing` | 40 herramientas de operaciones de crecimiento | No | Media |
| 08 | `skills-de-redes-sociales` | Sistema operativo de contenido: publicaciones, reels, captions | Parcial — `motor-contenido-mv` + suite social-media | Baja — pisa a lo tuyo |

**Regla de convivencia:** para tu marca manda `motor-contenido-mv`. Un plug-in de contenido entra
como complemento (formatos, hooks), nunca como dueño del dominio.

---

## 2. Skills — un comando, un flujo completo

| # | Skill | Qué hace | ¿Ya lo tenés? | Prioridad |
|---|---|---|---|---|
| 01 | `frontend-design` | Elimina el look genérico de IA en interfaces | **Sí** (global + librería) | Ya cubierto |
| 02 | `hyperframes` | Escribe HTML y renderiza video; nativo de agentes | No | Media — útil para demos/landings |
| 03 | `ai-second-brain` | Wiki estilo Karpathy a partir de tu historial de IA | Parcial — `contra-loop-vault` hace algo más agresivo sobre Obsidian | Media |
| 04 | `notebooklm-skill` | Claude consulta tu investigación y tus playbooks | No | Media |
| 05 | `humanizer` | Saca el tono de escritura de IA de cualquier borrador | No | **Alta** — se combina bien con `motor-contenido-mv` |
| 06 | `claude-seo` | SEO con enfoque GEO (posicionamiento en respuestas de IA) | No | Media |
| 07 | `skills` (Vue/Vite) | Colección del equipo Vue + Vite | No | Baja — solo si el repo es Vue |
| 08 | `caveman` | Reduce ~65% los tokens hablando telegráfico | No | Baja — cuidado: ahorra tokens a costa de precisión; **no usar** en tareas con números, SQL o modelos |

---

## 3. Servidores MCP — conectores a herramientas reales

Convierten a Claude de ventana de chat en capa operativa: lee y escribe en tus herramientas.

| # | MCP | Qué hace | ¿Ya lo tenés? | Prioridad |
|---|---|---|---|---|
| 01 | Granola | Alimenta a Claude con las notas de todas tus reuniones | No — pero `reuniones-minutas` procesa transcripts a mano | **Alta** si tenés muchas reuniones |
| 02 | Slack | Publica y lee historial de canales | No | Alta si el equipo vive en Slack |
| 03 | Notion | Lee y escribe en bases de datos y documentos | No | Media |
| 04 | Kondo | Detecta qué DMs de LinkedIn necesitan respuesta | No | Media — encaja con marca personal |
| 05 | Zapier | 9.000+ apps, 40.000+ acciones, una sola conexión | **Sí — activo en tu sesión** | Ya cubierto |
| 06 | Higgsfield | Videos cinematográficos desde un prompt | No | Media — contenido |
| 07 | Perplexity | Búsqueda web en tiempo real dentro de Claude | Parcial — ya tenés `WebSearch`/`WebFetch` nativos | Baja |
| 08 | Agent Browser | Automatización de navegador optimizada para gastar menos tokens | Parcial — Playwright + Chromium ya instalados | Media |

**Conectores que ya tenés activos y no están en la lista original:** Gmail, Google Calendar,
Google Drive, Vercel, GitHub, Canva, Gamma, Twilio, Supermetrics, Unstructured. Antes de sumar un
MCP nuevo, chequeá si uno de estos ya cubre el caso.

---

## Cómo priorizar (regla práctica)

No instales por FOMO. Un ítem entra solo si:

1. Resuelve un cuello de botella que **te pasó esta semana**, y
2. no hay nada instalado que ya lo resuelva, y
3. pasa el gate de seguridad de arriba.

Orden de rendimiento por esfuerzo, para el perfil de este usuario (datos/ML/cobranzas + contenido
+ producto propio):

1. **MCP de reuniones** (Granola o equivalente) — elimina la transcripción manual.
2. **`humanizer`** — mejora directa sobre todo el contenido que ya generás.
3. **`servicios-financieros`** — dominio real de uno de tus repos activos.
4. Todo lo demás: cuando aparezca la necesidad concreta.
