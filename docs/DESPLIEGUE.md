# Plania · Guía de despliegue (web + backend + PC)

Tres piezas, cada una desplegable por separado. Todo el código está en el
repo; lo único que falta en producción son secretos y URLs reales.

## 1. App web (la que usan los clientes en el navegador)

Cualquier host que corra Python sirve (Render, Railway, Fly.io, una VM):

```bash
pip install -r requirements.txt
python data/generate_dataset.py            # solo si querés la base demo a mano
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```

El `Procfile` ya trae el proceso `web` configurado (Render/Railway lo
detectan solos). Variables opcionales:

| Variable | Para qué |
|---|---|
| `PLANIA_CONFIG_DIR` | dónde persiste la config cifrada (default `~/.plania`) |
| `ERP_DB_URL` | conexión fija al ERP del cliente (si no, se configura en la UI) |
| `ANTHROPIC_API_KEY` | redacción del copiloto con Claude (opcional) |
| `PLANIA_BACKEND_URL` | backend de venta — **obligatoria en producción**, no solo para el botón de pago |

`PLANIA_BACKEND_URL` dejó de ser solo cosmética: activar cualquier licencia
(trial, paga, o la propia del dueño) consulta `GET {backend}/licencias/estado`
contra esa URL para confirmar la firma — es la única forma honesta de saber
que el token lo emitió `backend_venta` y no cualquiera con una librería de
JWT. Sin esa variable apuntando al backend real, nadie puede activar nada
(ni siquiera una licencia genuina), así que en producción no es opcional.

## 2. Backend de venta (licencias + MercadoPago)

> **Mientras esto no esté desplegado, Plania no cobra y nadie puede activar
> una licencia** — ni una paga: activar consulta `GET
> {backend}/licencias/estado`. No es una limitación del código, es que el
> servicio no está corriendo en ningún lado. Todo lo demás de esta guía
> depende de este paso.

### La vía corta: blueprint de Render

`render.yaml` en la raíz deja el servicio desplegable sin decidir nada:

1. render.com → **New → Blueprint** → conectar este repositorio.
2. Render lee `render.yaml` y pide los dos secretos que no puede inventar
   (`MP_ACCESS_TOKEN` y `ANTHROPIC_API_KEY`).
3. Deploy. Queda una URL tipo `https://plania-backend.onrender.com`.

Ese archivo ya resuelve las dos cosas que se rompen en silencio si se
despliega a mano: el secreto de firma queda fijo (`generateValue`) en vez de
regenerarse en cada reinicio e invalidar todas las licencias emitidas; y se
instala `requirements-backend.txt` —unos 20 MB— en lugar del
`requirements.txt` completo con pandas, pyarrow y streamlit, que el backend
no usa. Usa el plan **`free`** de Render, sin costo.

Lo que no se puede saltear, se despliegue donde se despliegue, es dónde
queda la base de `uso.py`/`pagos.py`/`descargas.py` (qué pagos ya emitieron
licencia, qué emails ya usaron la demo, los tokens de descarga vivos). Por
defecto es un archivo SQLite local, y el plan `free` de Render (como el de
casi cualquier PaaS) no tiene disco persistente: ese archivo se borra en
cada reinicio o cada vez que el servicio se duerme por falta de tráfico —
en la práctica, un reintento del webhook de MercadoPago después de un
reinicio duplicaría la licencia de un pago ya procesado.

La solución sin pagar un plan con disco: apuntar `PLANIA_USO_DB` a una base
Postgres externa gratuita —Neon o Supabase tienen free tier permanente—:

1. Crear un proyecto gratis en [neon.tech](https://neon.tech) o
   [supabase.com](https://supabase.com) y copiar su connection string
   (`postgresql://usuario:clave@host/basededatos`).
2. Cargarla como `PLANIA_USO_DB` en las variables de entorno del servicio.
3. Listo — `backend_venta/db.py` detecta que es una URL (no una ruta de
   archivo) y usa esa base en vez de SQLite. El plan `free` de Render
   alcanza porque el estado que importa ya no vive en su disco.

Si se deja `PLANIA_USO_DB` sin setear, el backend igual arranca (cae a
SQLite local), pero pierde ese registro en cada reinicio — aceptable solo
para probar, no para cobrar en serio.

### A mano

```bash
uvicorn backend_venta.app:app --host 0.0.0.0 --port $PORT
```

(`Procfile`, proceso `backend`.) Secretos **obligatorios** en producción:

| Variable | Para qué |
|---|---|
| `MP_ACCESS_TOKEN` | Access Token del vendedor MercadoPago (checkout + verificación webhook) |
| `PLANIA_LICENSE_SECRET` | secreto HS256 fijo para firmar licencias (rotable) |
| `PLANIA_BACKEND_ADMIN_TOKEN` | token admin para `/licencias/emitir` manual |
| `ANTHROPIC_API_KEY` | gateway IA medido (los clientes nunca ven la key) |
| `PLANIA_PUBLIC_URL` | URL pública de la landing (back_urls del checkout) |
| `PLANIA_WEBHOOK_URL` | URL pública de `/webhooks/mercadopago` |
| `PLANIA_INSTALADOR_PATH` | ruta del `Plania_Setup.exe` publicado para `/descargar/{token}` |
| `PLANIA_USO_DB` | URL de Postgres externa (recomendado sin disco persistente) o ruta de archivo SQLite — default un SQLite local |

Después del deploy: cargar la URL del webhook en el panel de MercadoPago
(Tus integraciones → Webhooks → evento `payment`), y ponerla también en
`PLANIA_WEBHOOK_URL` para que las dos digan exactamente lo mismo.

Si no se setea, el checkout la deduce de la URL por la que le llegó el
pedido (`https://<este-servicio>/webhooks/mercadopago`), que es lo correcto.
Antes la deducía de `PLANIA_PUBLIC_URL` —la landing— y eso mandaba las
notificaciones de pago contra un 404 de Vercel: el pago se cobraba y la
licencia no se emitía sola.

### Tu propia licencia, sin restricciones

Con el backend ya desplegado (y `PLANIA_LICENSE_SECRET` fijado — si no, cada
reinicio del proceso podría regenerar el secreto y las licencias emitidas
antes dejarían de validar):

```bash
python3 packaging/generar_licencia_owner.py vos@tu-dominio.uy
```

Activala en tu instalación como cualquier licencia paga. El plan `owner` no
figura en `/planes` (no es de catálogo) ni se puede comprar (no tiene
precio) — solo sale de este script o de `POST /licencias/emitir` con el
token de admin.

## 3. Web pública en Vercel (español, inglés y portugués)

La web se **genera**, no se edita a mano: los textos viven en
`sitio/i18n/{es,en,pt}.json` y la maqueta en `sitio/plantilla.html`.

```bash
python3 sitio/build.py              # escribe web/{es,en,pt}/index.html
python3 sitio/doblar_video.py       # subtítulos de las tres pistas
python3 sitio/verificar_layout.py   # nada se solapa en 3 idiomas x 3 anchos
```

Se generan tres HTML estáticos en vez de traducir con JavaScript en el
navegador porque así no hay medio segundo de texto en el idioma equivocado,
y porque Google indexa tres páginas con su `hreflang` en vez de una sola.

### Deploy

En Vercel: **New Project → Import** el repo → **Deploy**. No hay nada que
configurar: el `vercel.json` de la raíz ya declara que el sitio está en
`web/` y que no hay build. Cada push a `main` vuelve a publicar solo.

**`vercel.json` no admite comentarios, ni siquiera con el truco de la clave
`"//"`.** Valida contra un esquema estricto y una propiedad de más corta el
deploy entero:

```
The `vercel.json` schema validation failed with the following message:
should NOT have additional property `//ignoreCommand`
```

Por eso lo que hay que explicar de ese archivo se explica acá.

**`ignoreCommand`** existe porque Vercel despliega en cada push de cualquier
rama, y este repositorio recibe muchos que no tocan la web —`packaging/`,
`tests/`, workflows—. Cada uno gastaba un deploy hasta llegar al techo del
plan gratuito:

```
Resource is limited - try again in 24 hours
(more than 100, code: api-deployments-free-per-day)
```

Y ahí deja de desplegarse también lo que sí cambió la web. El comando sale 0
—saltear— cuando el commit no tocó `web/` ni `vercel.json`, y 1 —construir—
cuando sí. Si `HEAD^` no existe (primer deploy, clon sin historia) falla con
otro código y Vercel construye igual: el default seguro.

Otras dos decisiones del `vercel.json` que conviene no cambiar sin pensarlo:

- El video y el póster se cachean un año (`immutable`) porque cambian de
  nombre cuando cambian.
- `plania.css` y `plania.js` **no** llevan hash en el nombre, así que van con
  `must-revalidate`: si se cachearan un año, un arreglo de maquetación
  tardaría un año en llegarle a quien ya visitó el sitio.

### Apuntar la web al backend

El alta de la demo y el checkout necesitan saber dónde está el backend. Se
configura en `sitio/sitio.json` (o por entorno) y se vuelve a generar:

```json
{
  "dominio": "https://plania.uy",
  "backend": "https://api.plania.uy"
}
```

```bash
python3 sitio/build.py
```

Equivalente sin tocar archivos, útil en un pipeline:

```bash
PLANIA_BACKEND=https://api.plania.uy PLANIA_DOMINIO=https://plania.uy \
  python3 sitio/build.py
```

`dominio` no es cosmético: de ahí salen las URLs canónicas y los `hreflang`.
Si el sitio queda en `plania-xxxx.vercel.app` y `dominio` sigue diciendo
`plania.uy`, Google va a indexar mal.

**Con `backend` vacío la web informa pero no vende**, y además *lo dice*: los
botones de plan pasan a "Hablar con ventas", la nota de la demo pasa de "la
licencia llega al instante" a "te la enviamos a mano, en el día", y no se
nombra MercadoPago en ninguna página. Los textos alternativos están en
`SIN_BACKEND`, en `sitio/build.py`.

Esto no era así: el botón decía "Pagar con MercadoPago" y, sin backend, lo
que hacía era bajar hasta el formulario de contacto (que abre el cliente de
correo). Que el JavaScript se comporte distinto no alcanza — el visitante lee
el botón, no el JavaScript. Un botón que promete cobro automático y entrega un
mailto es publicidad de algo que no existe.

Para que no vuelva a pasar por descuido, `build.py` **corta el build** si una
página generada sin backend nombra MercadoPago, venga el texto de `i18n/` o de
la plantilla. En cuanto `backend` se configura, los textos de venta vuelven
solos: ahí la promesa es cierta.

### Páginas de retorno del pago

`sitio/build.py` genera también `/gracias/`, `/pendiente/` y `/error/` (una
sola plantilla, `sitio/plantilla_retorno.html`, que elige idioma en el
navegador). Son las direcciones que el checkout le pasa a MercadoPago en
`back_urls`: sin ellas, quien paga de verdad vuelve a un 404 del sitio
estático, cobrado y con las manos vacías.

`/gracias/` no se limita a agradecer: toma el `payment_id` que MercadoPago
deja en la URL, pide `GET {backend}/licencias/por-pago/{payment_id}` y le
muestra al comprador su licencia y el link de descarga del instalador. Ese
endpoint verifica el pago contra la API real de MercadoPago y es idempotente,
así que sirve igual si el webhook todavía no llegó.

### Dominio

`plania.uy` en Vercel → Settings → Domains. Las URLs canónicas y los
`hreflang` ya apuntan ahí (`sitio/build.py`); si el dominio final es otro,
cambialo en ese archivo y volvé a generar.

## 3b. Video de demostración en tres idiomas

```bash
pip install -r sitio/requirements.txt && playwright install chromium   # una vez
streamlit run app/app.py --server.port 8710 --server.headless true &
python3 sitio/grabar_demo.py        # graba el producto real, sin narrar
python3 sitio/doblar_video.py       # subtítulos + informe de calce
```

Eso ya deja el video entendible en los tres idiomas. Para el **audio
doblado con la misma voz** en los tres, sin cuenta ni clave (`chatterbox-tts`
ya quedó instalado en el paso de arriba):

```bash
python3 sitio/doblar_video.py --doblar
```

La muestra que se clona es `sitio/narracion/voz_referencia.wav`: quince
segundos de la narración del video original. Esa misma voz habla español,
inglés y portugués — no son tres locutores.

La primera corrida descarga el modelo (unos 3 GB) y en CPU tarda bastante;
después queda en caché. Con GPU lo usa solo. Alternativas: `--motor voicebox`
si ya se usa esa aplicación, o `--motor elevenlabs` (pago).

El script sintetiza segmento por segmento y lo coloca en su marca de tiempo
exacta, así el doblaje no se va corriendo de la imagen. Si un segmento no
entra en su hueco avisa cuál y cuánto se pasa, y **no publica ese video**:
lo deja como `plania_demo_<idioma>.REVISAR.mp4` para escucharlo, sin tocar
el que está publicado. `--ajustar` intenta encogerlo hasta 1.15x antes de
darlo por perdido.

Si VoiceBox corre en otra máquina o en otro puerto: `PLANIA_VOICEBOX_URL`.
Alternativa paga: `--motor elevenlabs` con `ELEVENLABS_API_KEY`.

## 4. Programa PC (Windows)

En una máquina Windows con Python 3.11+:

```powershell
pip install -r requirements.txt pyinstaller cython
python packaging\build_release.py
```

Deja, si Inno Setup 6 está instalado:
- `dist\Plania_Setup_v1.0.0.exe` — el instalador, con versión en el nombre.
- `dist\Plania_Setup.exe` — copia idéntica sin versión en el nombre: es la
  ruta que `backend_venta/app.py` sirve por defecto en `/descargar/{token}`
  (la descarga post-pago). Si preferís servir otra ruta, seteá
  `PLANIA_INSTALADOR_PATH` y listo — no hace falta renombrar nada.

Y siempre, tenga o no Inno Setup: `dist\Plania_portable.zip`.

### Dos formas de entregarlo, un solo build

`build_release.py` deja las dos vías, y las dos son necesarias:

- **EXE** — `Plania Setup *.exe` (Electron + React, ventana propia) y
  `Plania_Setup_v*.exe` (liviano, abre en el navegador). Los dos dejan ícono
  en el escritorio, entrada en el menú Inicio y desinstalador.
- **BAT** — `Plania_BAT.zip`: se descomprime y se hace doble clic en
  `INICIAR_PLANIA.bat`. Para las empresas donde IT no deja ejecutar un `.exe`
  bajado de internet, que no es un caso raro. Necesita Python 3.11+ y prepara
  el entorno solo la primera vez.

Lo que el cliente NO recibe por ninguna de las dos vías está en una sola
lista, `fuera_del_producto()` de `packaging/proteger_codigo.py`: el panel del
dueño y lo que lo alimenta, `docs/` interna, el servidor de venta, y los
archivos que aparecen en `data/` al usar el programa en la máquina donde se
arma (el log de auditoría y la base de licencias del backend). Estaba
duplicada entre el `.spec` y el armado del ZIP, y divergió: el `.exe` sacaba
los módulos del dueño y el ZIP los mandaba en texto plano.

`python packaging/armar_paquete_bat.py --verificar dist/Plania_BAT.zip` abre
el ZIP terminado y falla si adentro hay algo que no tenía que estar, o si
falta algo sin lo cual el producto no arrancaría. Corre en el workflow.

### Un solo producto, y el panel del dueño aparte

`build_release.py` arma **un** Plania, sin ediciones. Ese archivo es el que
usa el dueño y el que descarga quien lo compra: es la única forma de que el
dueño esté probando lo mismo que reciben sus clientes.

El panel del negocio —facturación, clientes, modelo financiero, kit de
contenido— se arma por separado y no se publica:

```powershell
python packaging\build_release.py --con-owner
```

Eso deja tres archivos, todos tuyos:

| Archivo | Qué es | Pide clave |
|---|---|---|
| `Plania_Owner_Junto_Al_Exe.zip` | Se descomprime **adentro de la carpeta donde ya está instalado Plania** y se hace doble clic en `ACTIVAR_OWNER.bat`. Deja el panel al lado del producto, con su acceso directo. 37 KB. | **no** |
| `Plania_Owner_Setup.exe` | Instalador aparte, con ícono en el escritorio, menú Inicio y desinstalador | **no** |
| `Plania_Owner.zip` | El mismo programa sin instalar | **no** |
| `Plania_Owner_BAT.zip` | Código + `INICIAR_PLANIA_OWNER.bat`, para una PC donde no podés abrir un `.exe` | sí |

El primero es el camino corto si ya tenés Plania instalado: no instala un
segundo programa, le agrega la pantalla al que ya está. `DESACTIVAR_OWNER.bat`
lo saca y deja Plania como estaba.

**Por qué ese ZIP tiene que traer el código y no puede ser un `.bat` solo.**
Porque el panel no está adentro del ejecutable del cliente: no está escondido
ni apagado, `proteger_codigo.py` lo saca del build siempre. Ningún archivo
suelto puede "desbloquearlo" — no hay nada que desbloquear. Lo que sí funciona
es dejar los cinco módulos al lado del motor: el lanzador ya sabe abrir
`app/owner.py` cuando encuentra `PLANIA_PANEL=owner`, y resuelve los import
contra la carpeta del bundle, que es la misma donde viven los compilados.
Probado contra un árbol compilado con Cython de verdad: los `.py` del panel se
importan al lado de los `.so`, y los compilados siguen resolviendo a `.so`.

Ninguno va a `INSTALADOR/`, ninguno se adjunta a la release y el workflow
corta si aparece cualquier `Plania_Owner*` ahí.

**Por qué el ejecutable no pide clave.** Porque el token no protegía nada en
ese escenario. Este panel no se distribuye: no está en `INSTALADOR/`, no está
en ninguna release, y ni siquiera viaja adentro del producto
(`packaging/proteger_codigo.py` lo saca del `.exe` del cliente y del ZIP del
`.bat`). Quien tiene ese archivo es porque lo compiló. Pedirle además una
contraseña es pedirle una llave para su propia casa: lo único que consigue es
que la anote en un papel al lado del teclado.

`app/owner.py` la saltea **sólo** si se dan las dos cosas: es el ejecutable
congelado Y está escuchando en loopback. Corriendo desde el repo con
`streamlit run` sigue pidiéndola, y un despliegue en `0.0.0.0` también — ahí
sí hay red del otro lado. La versión `.bat` la pide siempre, porque es código
suelto y no prueba nada sobre quién lo corre.

### Dónde quedan los instaladores

La carpeta [`INSTALADOR/`](../INSTALADOR/) del repositorio, con sus `sha256`.
Se llena sola: el workflow **Release** se dispara con cada push a `main` que
toca `app/`, `plania/`, `packaging/`, `desktop/`, `data/`, `assets/`,
`requirements.txt` o `INICIAR_PLANIA.bat` (un job en Linux revisa esto antes
de prender `windows-latest`, que es lo caro — si el push no tocó nada de esa
lista, no arranca nada). Compila en Windows y commitea el resultado sin
intervención.

Eso mantiene `INSTALADOR/` al día, pero no publica en *Releases* por cada
commit: cortar una versión con changelog sigue siendo pushear un tag `v*` o
usar **Actions → Release → Run workflow** — ahí sí construye y además
publica, toque lo que toque el commit.

Este instalador **permite elegir dónde instalar** (`DisableDirPage=no` en
`packaging/instalador.iss`, explícito), valida la carpeta elegida antes de
copiar nada (unidad lista, con espacio, escribible; avisa si es de red o
extraíble), y no se rompe si Plania está abierto al instalar o desinstalar
encima: detecta el proceso y pide cerrarlo antes de seguir, en vez de fallar
a mitad de camino con archivos bloqueados.

**Todo lo que Plania guarda queda en el mismo disco donde se instaló** —no
sólo el programa. La licencia, la configuración del ERP y la caché de
archivos subidos se guardan en una carpeta `datos\` al lado del `.exe`
(`plania/config.py`, `_carpeta_junto_al_exe`), y los logs en `datos\logs`
(`packaging/plania_launcher.py`). Antes quedaban siempre en `~/.plania` y
`%LOCALAPPDATA%` —el perfil de Windows, casi siempre en C:— sin importar en
qué disco se hubiera instalado el programa. Quien actualiza desde una
versión anterior no pierde la licencia activada: se migra una sola vez, la
primera vez que arranca la versión nueva. `python3 packaging/verificar_instalador.py`
comprueba las dos cosas (elegir disco y guardar ahí) sin necesitar Windows.

En el workflow de Release (`.github/workflows/release.yml`) hay que instalar
Inno Setup a mano antes de construir: la imagen `windows-latest` actual
(Windows Server 2025) no lo trae preinstalado — sí lo traía la 2022. El
workflow ya tiene el paso (`choco install innosetup`); si algún día GitHub
lo agrega a la imagen por defecto, ese paso queda siendo un no-op inofensivo.

Antes de armar el ejecutable, el build compila `plania/` con Cython
(`packaging/proteger_codigo.py`) a extensiones nativas — el .exe y el
portable no llevan el código de negocio como `.py` legible. `--sin-proteger`
salta ese paso para iterar rápido; no sirve para distribuir. Esto NO aplica
a `Plania_BAT.zip` (release.yml): esa vía es a propósito "código a la
vista" — corre con el Python del usuario, sin compilar nada — así que quien
la baja ve el código de la app (nunca el de `backend_venta`, que no viaja
ahí tampoco). Ver la comparativa completa en el cuerpo de cada release.

## 5. Licencia de uso (EULA)

`LICENSE-EULA.md` en la raíz del repo. Se distribuye con las cuatro vías
(exe, portable, BAT, y como archivo en el propio repo para la web) y la app
pide aceptarla una vez por instalación antes de dejar entrar a cualquier
pantalla con datos (`plania/licencia.py`). Si el texto de la EULA cambia
de forma sustancial, subir `EULA_VERSION` en ese módulo para que se vuelva
a pedir la aceptación.

## Checklist de salida a producción

1. [ ] Backend desplegado con los 7 secretos de arriba (blueprint de Render o
       el host que sea). **Hasta acá el producto no cobra ni activa
       licencias**: todo lo de abajo depende de este punto.
2. [ ] Webhook cargado en MercadoPago y probado con un pago de $1 (modo test).
       Verificar que la URL cargada en MP sea la del backend, no la de la
       landing.
3. [ ] Web publicada en Vercel apuntando al backend, y `plania.uy` apuntando a
       Vercel. Probar `/es/`, `/en/` y `/pt/`, que `/` mande al idioma del
       navegador, y que `/gracias/`, `/pendiente/` y `/error/` abran (son el
       retorno del pago).
3b. [ ] Con el backend puesto, confirmar que el botón de plan volvió a decir
       "Pagar con MercadoPago". Si sigue diciendo "Hablar con ventas", el
       `build.py` corrió sin `backend` configurado.
4. [ ] `python3 sitio/verificar_layout.py` en verde (nada se solapa).
4b. [ ] `python3 packaging/verificar_pantallas.py` en verde: las 12 pantallas
       se dibujan sin un traceback a la vista. Tarda unos minutos porque abre
       el producto de verdad — es el control que los tests no pueden hacer.
4c. [ ] `python3 packaging/verificar_pantallas_react.py` en verde: lo mismo
       para la ventana propia (Electron + React contra `plania/api.py`).
       Necesita `cd desktop && npm ci` una vez. No prueba el instalador de
       Electron —eso necesita Windows— pero sí todo lo que corre adentro de
       la ventana, que es donde se rompen las cosas.
5. [ ] Video grabado, con las tres pistas de subtítulos, y doblado con
       VoiceBox (`--doblar` sin avisos de solapamiento).
6. [ ] `Plania_Setup.exe` construido y subido — sin `--sin-proteger`, con
       `plania/` compilado (confirmar que `dist/Plania/_internal/plania/`
       tiene `.pyd`, no `.py`, y que no aparece `backend_venta` en ningún
       lado del bundle).
7. [ ] Compra de prueba end-to-end: web → MP sandbox → webhook → licencia
       recibida → activada en la app → descarga del instalador.
8. [ ] App web desplegada (para demos sin instalar nada).
9. [ ] `PLANIA_BACKEND_URL` configurada en el build/deploy de la app cliente
       (sin esto nadie puede activar ninguna licencia, ni siquiera una real).
10. [ ] `PLANIA_LICENSE_SECRET` fijado en el backend (no dejado a
        autogenerarse): si el proceso se reinicia y regenera el secreto,
        las licencias ya emitidas dejan de validar.
11. [ ] Tu propia licencia `owner` generada y activada
        (`packaging/generar_licencia_owner.py`).
