# CLAUDE.md — <NOMBRE DEL PROYECTO>

<!--
  ESQUELETO. Completar cada <PLACEHOLDER> con datos REALES del repo.
  Un CLAUDE.md con comandos inventados es peor que no tener CLAUDE.md:
  hace que Claude corra cosas que no existen y declare éxitos falsos.
  Verificá cada comando de la tabla ANTES de commitear este archivo.
-->

Guía para Claude Code al trabajar en este repo. Leela antes de tocar código.

## Qué es

<QUÉ HACE EL PROYECTO, EN 3-5 LÍNEAS: para quién, qué resuelve, qué NO es.>

## Stack

- **<LENGUAJE/RUNTIME + VERSIÓN>** — <rol en el proyecto>
- **<FRAMEWORK PRINCIPAL>** — <dónde vive>
- **<DEPS CLAVE>** — <las 5-8 que importan, no el lockfile entero>
- **Tests**: <framework y dónde viven>

## Comandos

| Objetivo | Comando |
|---|---|
| Instalar deps | `<comando real>` |
| Correr la app | `<comando real>` |
| Tests | `<comando real>` |
| Un test puntual | `<comando real>` |
| Lint / format | `<comando real, o "no hay — no introduzcas uno sin pedirlo">` |
| Build | `<comando real>` |

## Estructura

```
<árbol de 1-2 niveles con un comentario por carpeta — solo lo que importa>
```

## Flujo de trabajo

1. **Plan** — ante un cambio no trivial, planificá primero. Solo lectura hasta aprobar.
2. **Cambio** — editá el mínimo necesario. Respetá la separación <capa A> vs <capa B>.
3. **Test** — `<comando de test>`. No declares éxito sin correrlo y pegar la salida.
4. **Ship** — test → commit descriptivo → push a la rama de trabajo → PR draft.

## Convenciones

- <REGLA DE DOMINIO 1 — la que más se rompe si no se sabe>
- <REGLA DE DOMINIO 2>
- <IDIOMA de código, comentarios y textos de usuario>
- Secretos por entorno (`.env`), nunca en el código ni en commits.

## Do / Don't

**Do**
- Correr los tests antes de cerrar cualquier cambio.
- Usar `git status` / `git diff` para revisar antes de commitear.
- <DO específico del proyecto>

**Don't**
- No commitear `.env`, claves, tokens ni artefactos de build.
- No usar `git push --force` ni `rm -rf`.
- <DON'T específico del proyecto — lo que rompería producción>

## Agentes disponibles

`explorer` (mapear el repo) · `planificador` (plan antes de cambiar) · `parallel-worker` (fan-out)
· `especialista` (<dominio>) · `revisor` (review del diff) · `verificador` (gate de evidencia).

## Contexto / Compact

- Empezá por este archivo y el `README.md`.
- Para mapear a lo ancho, delegá en `explorer` en vez de leer todo en el hilo principal.
- Si el contexto se llena, compactá reteniendo: la tabla de comandos, las reglas de dominio, y qué
  archivos tocaste.
