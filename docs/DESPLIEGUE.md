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
| `PLANIA_BACKEND_URL` | URL del backend de venta para la pantalla Planes |

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

En Vercel: **New Project → Import** el repo, y

| Campo | Valor |
|---|---|
| Framework Preset | Other |
| Root Directory | `web` |
| Build Command | *(vacío — el sitio ya está generado)* |
| Output Directory | *(vacío)* |

`web/vercel.json` ya trae las cabeceras. Dos decisiones que conviene no
cambiar sin pensarlo:

- El video y el póster se cachean un año (`immutable`) porque cambian de
  nombre cuando cambian.
- `plania.css` y `plania.js` **no** llevan hash en el nombre, así que van con
  `must-revalidate`: si se cachearan un año, un arreglo de maquetación
  tardaría un año en llegarle a quien ya visitó el sitio.

Antes de publicar, definí a qué backend apunta el alta de la demo y el
checkout, agregando esto en `sitio/plantilla.html` antes de `plania.js`:

```html
<script>window.PLANIA_BACKEND = "https://api.plania.uy";</script>
```

Sin esa variable la web no simula nada: el formulario de demo muestra la
dirección de contacto y los botones de plan llevan a "Hablar con ventas".

### Dominio

`plania.uy` en Vercel → Settings → Domains. Las URLs canónicas y los
`hreflang` ya apuntan ahí (`sitio/build.py`); si el dominio final es otro,
cambialo en ese archivo y volvé a generar.

## 3b. Video de demostración en tres idiomas

```bash
streamlit run app/app.py --server.port 8710 --server.headless true &
python3 sitio/grabar_demo.py        # graba el producto real, sin narrar
python3 sitio/doblar_video.py       # subtítulos + informe de calce
```

Eso ya deja el video entendible en los tres idiomas. Para el **audio
doblado con la misma voz** en los tres, con [VoiceBox](https://voicebox.sh/)
levantado (es local, gratis y no pide clave):

```bash
python3 sitio/doblar_video.py --crear-voz "Plania"   # clona la voz, una sola vez
python3 sitio/doblar_video.py --listar-voces         # para ver el id
python3 sitio/doblar_video.py --doblar --voz <id>
```

La muestra que se clona es `sitio/narracion/voz_referencia.wav`: quince
segundos de la narración del video original. Clonada una vez, ese perfil
habla español, inglés y portugués — no son tres locutores, es la misma voz.

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
pip install -r requirements.txt pyinstaller
python packaging\build_release.py
```

Deja `dist\Plania_Setup_v1.0.0.exe` (si Inno Setup 6 está instalado) y
`dist\Plania_portable.zip` (siempre). Publicá el Setup donde apunte
`PLANIA_INSTALADOR_PATH` del backend para habilitar la descarga post-pago.

## Checklist de salida a producción

1. [ ] Backend desplegado con los 7 secretos de arriba.
2. [ ] Webhook cargado en MercadoPago y probado con un pago de $1 (modo test).
3. [ ] Web publicada en Vercel apuntando al backend, y `plania.uy` apuntando a
       Vercel. Probar `/es/`, `/en/` y `/pt/`, y que `/` mande al idioma del
       navegador.
4. [ ] `python3 sitio/verificar_layout.py` en verde (nada se solapa).
5. [ ] Video grabado, con las tres pistas de subtítulos, y doblado con
       VoiceBox (`--doblar` sin avisos de solapamiento).
6. [ ] `Plania_Setup.exe` construido y subido.
7. [ ] Compra de prueba end-to-end: web → MP sandbox → webhook → licencia
       recibida → activada en la app → descarga del instalador.
8. [ ] App web desplegada (para demos sin instalar nada).
