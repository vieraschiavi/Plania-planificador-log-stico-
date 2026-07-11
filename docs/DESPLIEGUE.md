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

## 3. Landing

`landing/index.html` es estática: GitHub Pages, Netlify, Vercel o el mismo
host. Antes de publicar, definí el backend:

```html
<script>window.PLANIA_BACKEND = "https://api.plania.uy";</script>
```

(o editá la constante `BACKEND` al final del archivo).

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
3. [ ] Landing publicada apuntando al backend.
4. [ ] `Plania_Setup.exe` construido y subido.
5. [ ] Compra de prueba end-to-end: landing → MP sandbox → webhook → licencia
       recibida → activada en la app → descarga del instalador.
6. [ ] App web desplegada (para demos sin instalar nada).
