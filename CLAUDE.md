# CLAUDE.md — Plania

Guía para Claude Code al trabajar en este repo. Leela antes de tocar código.

## Qué es

**Plania** es un programa de planificación logística y comercial para distribuidores,
mayoristas y comercios de Uruguay/LATAM. Se conecta al ERP o base de datos que el
negocio ya tiene (PostgreSQL, MySQL, SQL Server, Oracle, SQLite o CSV/Excel, con
auto-mapeo de columnas de ERPs como Zureo, Memory, Tango, Bejerman, Odoo, SAP B1) y
convierte los datos en decisiones: qué ofertar (sobrestock), qué reponer, qué
re-precificar, y por dónde repartir (ruteo con vecino-más-cercano + 2-opt). Incluye
un copiloto en español que responde consultas contra los datos reales (con Claude si
hay `ANTHROPIC_API_KEY`, o motor local si no) y exporta todo a PDF/Word/Excel. Corre
como app PC (Electron o `.exe` con PyInstaller) y como web (Streamlit), con venta
automática vía MercadoPago y licencias JWT (demo de 7 días full).

## Stack

- **Python 3.11+** — motor y app principal:
  - `plania/` : motor (conectores ERP, analítica, sugerencias, rutas, copiloto, exportes, licencias, config, auditoría, contenido, negocio, verificación).
  - `app/app.py` : dashboard **Streamlit** de cara al cliente.
  - `app/owner.py` : dashboard Streamlit separado para el dueño del negocio (token propio, `PLANIA_OWNER_TOKEN`).
  - `backend_venta/` : **FastAPI** — licencias, checkout/webhook MercadoPago, descargas, uso.
  - `data/generate_dataset.py` : genera la base demo sintética (`data/erp_demo.db`, seed fijo).
  - Deps clave: pandas, numpy, pyarrow, plotly, streamlit, sqlalchemy, openpyxl, xlsxwriter, fpdf2, python-docx, fastapi, uvicorn, PyJWT, keyring, cryptography.
- **Node** — `desktop/` (Electron, empaquetado de escritorio) y `web/` (sitio de venta estático ES/EN/PT, se publica en Vercel — ver `vercel.json`, `outputDirectory: web`).
- **Tests**: `pytest` sobre `tests/test_plania.py` (39 tests: dataset, conectores, analítica, sugerencias, copiloto, exportes, rutas, licencias, backend de venta).

## Comandos

| Objetivo | Comando |
|---|---|
| Instalar deps | `pip3 install -r requirements.txt` |
| Generar la base demo (Uruguay, sintética) | `python3 data/generate_dataset.py --seed 42` |
| Correr la app completa (instala + datos + Streamlit) | `./run.sh` |
| Correr solo el dashboard | `./run.sh app` (= `streamlit run app/app.py`) |
| Correr el dashboard owner | `PLANIA_OWNER_TOKEN=tu-token streamlit run app/owner.py --server.port 8600` |
| Correr el backend de venta (licencias + MercadoPago) | `./run.sh backend` (= `uvicorn backend_venta.app:app --reload --port 8100`) |
| Tests | `./run.sh test` (= `python3 -m pytest -q tests/`) |
| Un test puntual | `python3 -m pytest tests/test_plania.py::<nombre> -v` |
| Verificación end-to-end del producto | `python3 -m plania.verificacion` |
| Instalar deps de test | `pip install -r requirements.txt pytest httpx` (ver `.github/workflows/ci.yml`) |

> No hay linter/formatter configurado en el repo. No introduzcas uno sin pedirlo.
> El CI (`.github/workflows/ci.yml`) hoy solo corre manual (`workflow_dispatch`). Se apagaron
> los triggers automáticos porque en su momento la cuenta no asignaba runners; **ya no es el
> caso** — el workflow **Release** corrió en Windows con éxito varias veces (ver
> `INSTALADOR/CHECKSUMS.txt` y la página de Releases), así que la causa original ya no
> aplica. Sigue apagado porque es una decisión que hay que tomar, no porque esté roto — **no
> lo reactivés sin que te lo pidan** (ver el comentario en ese archivo antes de "arreglarlo").
> **El repositorio es público** (no privado, como decía esta nota antes): todo lo que
> `packaging/proteger_codigo.py` saca de los instaladores para que un cliente no lo lea
> —`plania/negocio.py`, `plania/owner.py`, `docs/` interna, `backend_venta/`— está igual acá
> en texto plano, para cualquiera. Ver la nota completa en `INSTALADOR/README.md`.
> `packaging/` (PyInstaller + Inno Setup) y `desktop/` (Electron) son para Windows/build
> de escritorio; no corras esos builds en este entorno Linux salvo que se pida explícitamente.

## Estructura

```
├── app/app.py            ← dashboard Streamlit de cara al cliente
├── app/owner.py          ← dashboard Streamlit del dueño (token propio, otro puerto)
├── plania/                ← motor: conectores, analítica, sugerencias, rutas, copiloto,
│                             exportes, licencia, config, auditoría, contenido, negocio, verificación
├── backend_venta/         ← FastAPI: licencias, MercadoPago, descargas, uso
├── data/                  ← generate_dataset.py (base demo sintética, seed fijo)
├── desktop/               ← empaquetado Electron (escritorio)
├── web/                   ← sitio de venta trilingüe (ES/EN/PT), deploy Vercel
├── sitio/                 ← build del sitio (video demo, i18n, narración)
├── packaging/             ← PyInstaller (plania.spec) + Inno Setup (instalador.iss) — Windows
├── docs/                  ← análisis de negocio, comparativa, modelo comercial, despliegue
├── assets/                ← capturas y recursos estáticos
└── tests/test_plania.py   ← suite pytest (39 tests)
```

## Flujo de trabajo

1. **Plan** — ante un cambio no trivial, planificá primero (`/plan`). Solo lectura hasta aprobar.
2. **Cambio** — editá el mínimo necesario. Respetá la separación motor (`plania/`) vs. UI
   (`app/`) vs. backend de venta (`backend_venta/`).
3. **Test** — `python3 -m pytest -q tests/` (`/test`). No declares éxito sin correrlos.
4. **Ship** — `/ship`: test → commit descriptivo → push → PR draft.

## Convenciones

- **Nunca inventar montos ni forzar ventas por debajo de costo**: `MARGEN_MINIMO_OFERTA`
  en `plania/sugerencias.py` es el piso (costo+8%) para cualquier oferta sugerida; no lo
  bajes ni lo saltees.
- **Datos de demo 100% sintéticos** (`data/generate_dataset.py`, seed fijo `--seed 42`);
  no metas datos reales de clientes ni de ventas.
- **Esquema canónico del conector** (`plania/conectores.py`): productos/clientes/ventas
  con columnas mínimas obligatorias (`sku/nombre/precio`, `cliente_id`, `fecha/sku/cantidad`)
  y auto-detección por sinónimos para ERPs de Uruguay/LATAM — si agregás un ERP nuevo,
  sumá sus sinónimos ahí, no hardcodees el mapeo en otro módulo.
- **Secretos por entorno o `keyring`, nunca hardcodeados**: `ANTHROPIC_API_KEY`,
  `MP_ACCESS_TOKEN`, `PLANIA_LICENSE_SECRET`, `ERP_API_KEY`, etc. se leen de variables de
  entorno o de `plania/config.py` (keyring del SO / archivo cifrado / texto plano como
  último recurso). No hay `.env.example` en el repo — no lo inventes, seguí el patrón de
  `plania/config.py`.
- **Español rioplatense** en textos de usuario, comentarios y mensajes de commit.
- El motor (`plania/`) debe poder importarse y testearse sin levantar Streamlit ni FastAPI.

## Do / Don't

**Do**
- Correr `python3 -m pytest -q tests/` antes de cerrar cualquier cambio de motor.
- Mantener el piso de margen (`costo + 8%`) en cualquier lógica de ofertas/precios.
- Preferir editar el motor en `plania/` y consumirlo desde `app/` y `backend_venta/`.
- Usar `git status`/`git diff` para revisar antes de commitear.

**Don't**
- No commitees `.env`, `config.json`/`config.enc` de `~/.plania`, claves ni tokens de MercadoPago.
- No corras los builds de `packaging/` (PyInstaller/Inno Setup) ni `desktop/` (Electron) en Linux.
- No reactivés los triggers automáticos de `.github/workflows/ci.yml` sin que te lo pidan.
- No introduzcas dependencias pesadas nuevas sin justificarlo.
- No uses `git push --force` ni `rm -rf`.

## Contexto / Compact

- Empezá por este archivo y el `README.md` (tiene el detalle comercial y de producto).
- Para entender el motor logístico/comercial, empezá por `plania/rutas.py` (ruteo) y
  `plania/sugerencias.py` (ofertas/reposición/precios); para el conector de datos,
  `plania/conectores.py`.
- Si el contexto se llena, compactá reteniendo: comandos de esta tabla, el piso de margen
  de ofertas, y qué archivos tocaste.
