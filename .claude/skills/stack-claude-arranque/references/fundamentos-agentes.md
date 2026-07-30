# Fundamentos de agentes IA

Base conceptual del arranque. Sirve para dos cosas: entender **por qué** un agente falla, y
**dónde** intervenir (modelo, harness, contexto o entorno).

---

## 1. La ecuación

```
agente = modelo + harness
```

```
        Tu instrucción: "arreglá este bug"
                      │
        ┌─────────────▼──────────────────────────┐
        │                AGENTE                  │
        │  ┌──────────┐   solicita   ┌─────────┐ │
        │  │  MODELO  │─────acción──▶│ HARNESS │ │
        │  │  piensa  │              │ ejecuta │ │
        │  │  analiza │◀──devuelve───│ observa │ │
        │  │  decide  │   resultado  │ permisos│ │
        │  └──────────┘              │ límites │ │
        └────────────────────────────└────┬────┘─┘
                                          │ actúa sobre
                                     ┌────▼─────────────────┐
                                     │       ENTORNO        │
                                     │ archivos · tests     │
                                     │ comandos · estado    │
                                     └──────────────────────┘
```

- **Modelo** — piensa, analiza, decide. No toca nada por sí solo.
- **Harness** — ejecuta, observa el resultado, aplica permisos y límites. Es Claude Code, los
  plug-ins, los MCP, los agentes, los hooks.
- **Entorno** — archivos, tests, comandos, estado del sistema.

**Diagnóstico por capa** cuando algo sale mal:

| Síntoma | Capa culpable | Qué hacer |
|---|---|---|
| Decide bien pero no puede hacerlo | Harness | Sumar tool/MCP/permiso |
| Ejecuta pero decide mal | Contexto | Mejor CLAUDE.md, ejemplos, skill de dominio |
| Se pierde en repos grandes | Contexto | Delegar en subagente `explorer`, compactar |
| Hace de más / rompe cosas | Límites del harness | Permisos más finos, agentes read-only |
| Dice que anduvo y no anduvo | Falta gate de verificación | Agente `verificador`, evidencia obligatoria |

---

## 2. El agent loop

Cuatro pasos que se repiten hasta cumplir el objetivo:

1. **Percepción / input del usuario** — la instrucción y el contexto disponible.
2. **Razonar y planificar** — qué hay que hacer y en qué orden.
3. **Actuar / invocar tools** — la única forma de tocar el mundo.
4. **Observación y reflexión** — leer el resultado real y corregir el plan.

El paso 4 es el que más se saltea, y es el que separa un agente de un generador de texto. Sin
observación real (salida de tests, exit code, log de build) el loop es ciego. Este es exactamente
el motivo del agente `verificador` y de `loop-engine`.

---

## 3. Fundamentos de LLM que cambian decisiones prácticas

### Mecánica del modelo

- **Tokenización** — el texto se parte en tokens; los costos y los límites se miden en tokens, no
  en palabras. Números largos y código tokenizan mal.
- **Ventana de contexto** — todo lo que el modelo "ve" a la vez. Cuando se llena, hay que compactar
  o delegar en subagentes. Un subagente tiene su propia ventana: por eso `explorer` barre 40
  archivos y te devuelve 1 página.
- **Precio por token** — input y output cuestan distinto; el contexto se re-envía en cada turno.
  Leer todo un repo "por las dudas" se paga en cada mensaje siguiente.

### Controles de generación

| Control | Qué hace | Cuándo tocarlo |
|---|---|---|
| Temperature | Aleatoriedad de la salida | Bajá para código/SQL/números; subí para ideación |
| Top-p | Recorte de la masa de probabilidad | Alternativa a temperature, no las muevas juntas |
| Frequency penalty | Castiga repetir tokens | Texto que se repite en bucle |
| Presence penalty | Empuja a temas nuevos | Brainstorming que no sale del mismo lugar |
| Stopping criteria | Dónde corta | Salidas estructuradas |
| Max length | Techo de output | Evitar truncados a mitad de un archivo |

### Otros básicos

- **Streamed vs no-streamed** — streaming mejora la percepción de latencia, no la latencia total.
- **Modelos de razonamiento vs estándar** — los de razonamiento piensan más antes de responder:
  mejores para planificación y debug, más caros y lentos para tareas mecánicas.
- **Fine-tuning vs prompt engineering** — casi siempre empezá por prompt + contexto + tools. El
  fine-tuning se justifica cuando el patrón es estable, masivo y ya lo validaste con prompting.
- **Embeddings y búsqueda vectorial / RAG** — para traer contexto que no entra en la ventana. En un
  repo, `grep` bien usado suele ganarle a un RAG mal armado.
- **Pesos abiertos vs cerrados y licencias** — define dónde podés correr el modelo y con qué datos.

---

## 4. Prompt engineering (lo que sí mueve la aguja)

- **Sé específico en lo que querés** — el resultado esperado, no solo la tarea.
- **Dale contexto adicional** — el porqué, las restricciones, qué ya intentaste.
- **Usá los términos técnicos correctos** — activan el vocabulario correcto del modelo.
- **Chain of Thought (CoT)** — pedile que razone paso a paso en problemas con dependencias.
- **Tree of Thought** — explorar varias ramas y elegir; caro, reservalo para decisiones de diseño.

En Claude Code, la mayor parte del prompt engineering **no se escribe en el chat**: vive en el
`CLAUDE.md`, en las skills y en las descripciones de los agentes. Eso es lo que se reusa; el
mensaje suelto se pierde.

---

## 5. Prerequisitos (si algo de esto falta, el agente rinde menos)

- Desarrollo backend básico
- Git y uso de terminal
- Conocimiento de APIs REST

---

## 6. Casos de uso típicos

Asistente personal · generación de código · análisis de datos · scraping/crawling web · NPC/IA de
juegos.

---

Fuente conceptual: roadmap de AI Agents de roadmap.sh (versión detallada allí), más el modelo
`agente = modelo + harness`. Resumido acá para que el arranque sea autocontenido.
