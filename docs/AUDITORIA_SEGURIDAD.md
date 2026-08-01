# Plania · Auditoría de seguridad

Registro de lo que se revisó, lo que se encontró y lo que se hizo con cada
hallazgo — no una promesa de "está todo bien", sino la evidencia de cómo se
llegó a esa conclusión. Reproducible con:

```bash
python3 -m pytest tests/ -q -W error::DeprecationWarning
packaging/auditar_dependencias.sh
```

## 1. Escape en el DOM

**Regla:** todo dato que llega de una API externa, del usuario o del backend
y termina insertado con `innerHTML` pasa por `escaparHtml()`
(`web/assets/plania.js`) — nunca concatenado a mano.

**Se encontró:** un caso real que no la cumplía. El alta de la demo de 7 días
insertaba la licencia devuelta por `/licencias/trial` con
`String(res.d.licencia).replace(/</g, "&lt;")` — un escape hecho a mano que
solo cubría `<`, dejaba pasar `&`, `>`, `"` y `'`.

**Se corrigió:** se agregó `escaparHtml()` (escapa las cinco entidades:
`& < > " '`) y se la usó en ese punto. Se comprobó que la corrección importa
de verdad reintroduciendo el código viejo a propósito y confirmando que el
test de abajo lo detecta — no alcanza con que el test pase, tiene que fallar
cuando el bug vuelve.

**Verificación permanente (2 tests):**
- `test_escaparHtml_neutraliza_los_payloads_de_xss_conocidos` — corre la
  función real en Node (no una reimplementación en Python que se podría
  desincronizar) contra 8 payloads de XSS típicos y confirma que ninguno deja
  un `< > " '` sin escapar en la salida.
- `test_ningun_innerHTML_con_variable_sin_pasar_por_escaparHtml` — recorre
  TODO el JavaScript propio (no `node_modules/`, `vendor/`, `lib/`) buscando
  asignaciones a `.innerHTML`, y falla si algo que no sea un literal fijo o
  el objeto de traducciones queda sin pasar por `escaparHtml(...)`. Blinda
  contra el próximo `innerHTML` que alguien agregue sin escapar, no solo
  contra el que ya se corrigió.

**Grep de control** (0 casos fuera de `escaparHtml`, `node_modules`, `vendor`,
`lib`):

```bash
$ grep -rn "innerHTML" --include="*.js" --include="*.html" . | grep -v "/node_modules/\|/\.git/"
web/assets/plania.js:161:          msg.innerHTML = t.demoOk + '<br><textarea readonly rows="3" style="width:100%;margin-top:8px">' +
web/assets/plania.js:162:            escaparHtml(res.d.licencia) + "</textarea>";
```

El único `innerHTML` del sitio, y la parte dinámica ya pasa por la función.

**Streamlit (`app/app.py`, `app/owner.py`):** hay 10 usos de
`unsafe_allow_html=True`. Se revisó cada uno — todos son bloques `<style>`
fijos o interpolan solo números calculados localmente (`horas_restantes`),
nunca texto de una base de datos externa, una consulta del copiloto o un
formulario. Ninguno necesita escape porque ninguno inserta dato externo.

## 2. Rate limiting

**Regla:** todo endpoint de `backend_venta/app.py` que acepta una request
HTTP pública tiene `@limiter.limit(...)` (slowapi), incluidos los que además
exigen un token — un token inválido igual gasta CPU validándolo, y algunos
endpoints disparan una llamada a una API externa que cuesta plata real por
golpe (MercadoPago, Anthropic).

| Endpoint | Límite | Por qué |
|---|---|---|
| `POST /licencias/trial` | 5/min | El más expuesto: sin credenciales, autoservicio. |
| `POST /checkout` | 10/min | Cada llamada crea una preferencia en la API de MercadoPago. |
| `POST /licencias/emitir` | 10/min | Requiere token admin, pero el límite frena la fuerza bruta del token antes de validarlo. |
| `POST /gateway/copiloto` | 20/min | Requiere licencia válida; el límite es la barrera de ráfaga — el cupo mensual del plan es la barrera de consumo total, son dos cosas distintas. |
| `GET /descargar/{token}` | 20/min | Defensa en profundidad contra adivinar el token. |
| `GET /licencias/estado` | 30/min | Consulta de estado, requiere licencia. |
| `POST /webhooks/mercadopago` | 30/min | Lo llama MercadoPago, no un usuario — el límite es deliberadamente holgado para no cortar notificaciones legítimas, pero igual acota que cualquiera en internet dispare verificaciones contra la API real de MP. |
| `GET /planes` | 60/min | Catálogo estático, sin costo de cómputo. |
| `GET /salud` | 120/min | Sin dato sensible ni costo, pero "todo endpoint" no tiene excepción para el que parece inofensivo. |

**Verificación (2 tests):**
- `test_todo_endpoint_publico_tiene_rate_limit` — chequeo de cobertura contra
  el registro real de slowapi (`limiter._route_limits`), no un atributo
  adivinado del wrapper. Confirmado que detecta el gap sacando el decorador
  de `/salud` a propósito y viendo fallar el test antes de dejarlo puesto.
- `test_rate_limit_corta_una_rafaga_de_altas_de_demo` — golpea
  `/licencias/trial` 6 veces desde una IP de prueba propia (bloque
  TEST-NET-3, `203.0.113.0/24`, reservado para documentación — nunca una IP
  real) y confirma que las primeras 5 pasan y la 6ta corta con 429. Confirma
  además que una IP distinta no queda afectada por la ráfaga de la otra.

**Limitación conocida:** el límite se guarda en memoria del proceso porque el
`Procfile` levanta un único proceso uvicorn. Si el día de mañana se escala a
varias réplicas, hace falta un backend compartido (Redis) — cada réplica
contando aparte multiplica el límite real.

## 3. Dependencias de terceros (nada vendorizado, pero sí instalado)

No hay `vendor/` ni `lib/` en el repo — nada de código de terceros vive
commiteado. La auditoría equivalente es sobre los dos árboles de
dependencias reales, con `packaging/auditar_dependencias.sh`.

### Python (`pip-audit -r requirements.txt`)

Un hallazgo, y no requiere acción:

**`pyarrow` 19.x — CVE-2026-25087 / PYSEC-2026-113** (use-after-free,
Arrow C++, corregido en 23.0.1). El propio texto del advisory dice:
*"Pre-buffering is disabled by default but can be enabled using a specific
C++ API call (`RecordBatchFileReader::PreBufferMetadata`). The functionality
is **not exposed in language bindings (Python, Ruby, C GLib)**"* — el
binding de Python que usamos no puede activar la ruta vulnerable. Se
verificó además que el código propio no lee archivos Arrow IPC en ningún
lado (`grep -rn "read_ipc\|RecordBatchFileReader\|feather" plania/ app/
backend_venta/` → sin resultados): pyarrow entra acá solo como backend de
pandas/Streamlit, no se usa su API de IPC.

Además, `requirements.txt` fija `pyarrow>=14,<20` **a propósito**, por una
razón de estabilidad ya diagnosticada y documentada ahí mismo: pyarrow≥20
segfaultea al convertir DataFrames en threads de Streamlit (se lo rastreó
con `faulthandler` antes de fijar el techo). Subir a 23.0.1 para "resolver"
un CVE que no aplica a nuestro uso reintroduciría un crash real. Se lo deja
así, con esta nota — que es la otra mitad de "no se ignora": no se sube a
ciegas, pero tampoco se pretende no saberlo.

Las 80 dependencias restantes (81 en total con `pyarrow`; `pandas`,
`streamlit`, `fastapi`, `requests`, `cryptography`, `PyJWT`, etc., en las
versiones resueltas contra los pisos de `requirements.txt` al momento de
esta auditoría) no tienen vulnerabilidades conocidas en la base de datos de
PyPI Advisory que usa `pip-audit`.

### Electron / React (`npm audit` en `desktop/`)

Antes de tocar nada: **13 vulnerabilidades** (1 crítica, 12 altas), todas en
el árbol de `electron-builder` 25.x (herramienta de build, no algo que se le
envía al usuario) salvo una.

**Se corrigió:** `electron-builder` `^25.0.0` → `^26.15.3` (`desktop/package.json`,
lockfile regenerado con `npm install --package-lock-only`, reinstalación
limpia verificada con `npm ci`). Resolvió **12 de las 13**, entre ellas la
crítica (`tar`, CVSS 8.2, hardlink path traversal) y once altas en
`@electron/rebuild`, `app-builder-lib`, `builder-util*`, `cacache`,
`dmg-builder`, `electron-publish`, `make-fetch-happen`, `node-gyp`.

**Queda pendiente, declarado y no escondido:** `electron` en sí,
resuelto en `33.4.11`, con una vulnerabilidad "alta" que cubre versiones
`<=39.8.4` (18 CVEs de Electron acumulados en ese rango, el más severo un
use-after-free CVSS 8.1). A diferencia de `electron-builder`, este paquete
**sí** es lo que termina empaquetado y corriendo en la máquina del cliente
— por eso importa más, no menos, que el resto.

No se lo subió a ciegas. La corrección requiere saltar de la versión 33 a
la 43 (diez versiones mayores), con cambios de compatibilidad reales entre
medio (APIs de Electron, versión de Chromium/Node embebida) que no se
pueden validar en este entorno: no hay pantalla para correr la app de
escritorio ni una máquina Windows para generar y probar el instalador NSIS.
Subir la versión sin poder abrir la aplicación después y confirmar que
sigue funcionando sería peor que dejar el hallazgo documentado — cambiar
código a ciegas por un audit no es más seguro que no cambiarlo.

**Queda como tarea explícita, no implícita:** actualizar `electron` a una
versión ≥40.x en una máquina donde se pueda compilar y correr el instalador
de Windows de punta a punta antes de publicar el próximo release del
programa de escritorio.

## 4. Cobertura de test en los módulos que tocan dinero

**Regla:** licencias, checkout y suscripción cubiertos igual o mejor que el
resto del código — no menos, que es donde suele estar el punto ciego (se
prueba mucho el copiloto porque es la demo vistosa, poco el webhook de pago
porque "ya está, MercadoPago lo llama y listo").

**Antes de esta auditoría** (`coverage run -m pytest && coverage report`):

```
backend_venta/app.py            162     82    49%
backend_venta/descargas.py       37     27    27%
backend_venta/licencias.py       41      7    83%
backend_venta/uso.py             48     11    77%
```

El webhook de MercadoPago completo (`/webhooks/mercadopago`), el éxito de
`/checkout`, `/gateway/copiloto` entero y `/descargar/{token}` no tenían
NINGÚN test — exactamente los caminos donde un bug significa "el cliente
pagó y no le llegó ni la licencia ni el instalador", sin que nada lo avise
hasta que se queje.

**Se agregaron 25 tests nuevos** (de los 29 que suma esta auditoría en
total, sumando también los de escape y rate limiting de las secciones 1 y
2) cubriendo, con mocks de MercadoPago/Anthropic para
no golpear las APIs reales: los cuatro desenlaces del webhook (ignorado,
sin `data.id`, verificación fallida, aprobado → emite licencia + token de
descarga, con fallback de plan desconocido a `starter`); éxito y rechazo de
`/checkout`; el gateway del copiloto completo incluido el corte real por
cupo mensual agotado (`_chequear_cupo`, antes sin ningún test); y el ciclo
completo de `/descargar/{token}` (inválido, instalador no publicado, éxito
con consumo de un solo uso).

**Después:**

```
backend_venta/app.py            162      5    97%
backend_venta/descargas.py       37      0   100%
backend_venta/licencias.py       41      5    88%
backend_venta/uso.py             48      0   100%
plania/licencia.py               97     13    87%
```

Cobertura ponderada de los 5 módulos de dinero: **94.0%**
((385−23)/385 líneas). Cobertura ponderada del resto de `plania/` (10
módulos, sin tocar en esta ronda): **79.3%** ((1489−309)/1489 líneas). Los
módulos de dinero quedan por encima, no empatados por casualidad.

## 5. Regresión de licencia forjable (contexto, no nuevo en esta auditoría)

Ya existía y se la corrió como parte de esta revisión:
`test_un_token_forjado_no_activa_ninguna_licencia` prueba que
`activar_licencia()` rechaza un JWT firmado con un secreto cualquiera — la
regresión de una falla real donde se decodificaba con
`verify_signature=False`.
