# 🚚 Plania · Planificación logística y comercial inteligente

Programa **PC (Windows) + Web** para distribuidores, mayoristas y comercios de
Uruguay/LATAM. Se conecta al ERP o base de datos que el negocio **ya tiene**,
y convierte los datos en decisiones: **qué ofertar, qué reponer, qué
re-precificar, qué zona atacar y por dónde repartir** — con un copiloto IA
que responde consultas sobre los datos reales y exporta todo a
**PDF, Word y Excel**.

## El producto

| | |
|---|---|
| ![Inicio](assets/capturas/inicio.png) | ![Copiloto](assets/capturas/copiloto.png) |
| *Inicio: demo 3 días full + resumen en pesos* | *Copiloto: consultas reales + export PDF/Word/Excel* |
| ![Panel](assets/capturas/panel.png) | ![Ofertas](assets/capturas/ofertas.png) |
| *Panel ejecutivo* | *Ofertas y sugerencias accionables* |

## Probarlo en 60 segundos

```bash
./run.sh            # instala deps, genera la base demo (Uruguay) y abre la app
```

o por partes:

```bash
pip install -r requirements.txt
python3 data/generate_dataset.py     # base demo: 320 productos, 260 clientes, 12 meses de ventas
streamlit run app/app.py             # la aplicación (web / la misma que empaqueta el .exe)
uvicorn backend_venta.app:app --port 8100   # backend de venta (licencias + MercadoPago)
python3 -m pytest tests/             # 24 tests
```

Al primer arranque se activa sola la **demo de 3 días con todo habilitado**.

## Qué lo diferencia

| Diferenciador | Dónde está |
|---|---|
| 🔌 **Conector universal**: PostgreSQL, MySQL, SQL Server, Oracle, SQLite, CSV/Excel con **auto-mapeo de columnas** (Zureo, Memory, Tango, Bejerman, Odoo, SAP B1…) | `plania/conectores.py` |
| 🤖 **Copiloto IA sobre datos reales**: responde en español calculando contra la base conectada; con `ANTHROPIC_API_KEY` redacta con Claude, sin key funciona igual (motor local) | `plania/copiloto.py` |
| 🏷️ **Sugerencias accionables**: ofertas por sobrestock (piso costo+8%), reposición antes del quiebre, ajustes de precio, venta cruzada por zona, recupero de clientes | `plania/sugerencias.py` |
| 📄 **Exportes profesionales** PDF / Word / Excel de cualquier análisis o respuesta del copiloto | `plania/exportes.py` |
| 🚛 **Rutas de reparto** optimizadas (vecino más cercano + 2-opt, con o sin GPS) | `plania/rutas.py` |
| 🎁 **Demo 3 días full** sin tarjeta, autoactivada; licencias JWT por plan | `plania/licencia.py` |
| 💳 **Venta automática con MercadoPago**: checkout + webhook verificado + emisión de licencia + descarga del instalador | `backend_venta/` |
| 💻 **Programa PC**: PyInstaller + Inno Setup → `Plania_Setup.exe` y ZIP portable | `packaging/` |

Más detalle comercial: [`docs/COMPARATIVA_COMPETENCIA.md`](docs/COMPARATIVA_COMPETENCIA.md)
y [`docs/MODELO_COMERCIAL.md`](docs/MODELO_COMERCIAL.md).

## Arquitectura

```
app/app.py            Dashboard Streamlit (12 pantallas, menú profesional) — web y PC
plania/               Núcleo: conectores, analítica, sugerencias, copiloto,
                      exportes, rutas, licencia, config segura, auditoría
backend_venta/        FastAPI: planes, trial 3 días, checkout MercadoPago,
                      webhook de pago, gateway IA medido, descarga instalador
data/                 Generador de base demo + ERP SQLite de ejemplo
packaging/            Launcher, spec PyInstaller, instalador Inno Setup, build
landing/index.html    Landing de venta (demo + checkout MercadoPago)
tests/                24 tests (conectores, analítica, sugerencias, copiloto,
                      exportes, rutas, licencias, backend)
```

## Construir el programa PC (Windows)

```bash
pip install -r requirements.txt pyinstaller
python packaging/build_release.py    # → dist/Plania_Setup_vX.exe + Plania_portable.zip
```

## Configuración (pantalla ⚙️ o variables de entorno)

Las credenciales se guardan con keyring del SO > archivo cifrado > texto
plano (`plania/config.py`). Claves: `ANTHROPIC_API_KEY` (copiloto IA),
`ERP_DB_URL` (base del cliente), `MP_ACCESS_TOKEN` (cobros), SMTP.
