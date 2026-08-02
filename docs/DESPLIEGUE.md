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

Después del deploy: cargar `PLANIA_WEBHOOK_URL` en el panel de MercadoPago
(Tus integraciones → Webhooks → evento `payment`).

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

Dos decisiones del `vercel.json` que conviene no cambiar sin pensarlo:

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

**Con `backend` vacío la web informa pero no vende**: el formulario de demo
muestra la dirección de contacto y los botones de plan llevan a "Hablar con
ventas". Es a propósito — es preferible eso a simular un checkout que
fallaría. El propio `build.py` lo dice en pantalla al terminar.

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

1. [ ] Backend desplegado con los 7 secretos de arriba.
2. [ ] Webhook cargado en MercadoPago y probado con un pago de $1 (modo test).
3. [ ] Web publicada en Vercel apuntando al backend, y `plania.uy` apuntando a
       Vercel. Probar `/es/`, `/en/` y `/pt/`, y que `/` mande al idioma del
       navegador.
4. [ ] `python3 sitio/verificar_layout.py` en verde (nada se solapa).
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
