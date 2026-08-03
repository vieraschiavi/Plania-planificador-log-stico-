"""
Plania · Backend de venta — FastAPI
===================================
Todo el circuito comercial en un servicio chico y desplegable donde sea
(Render/Fly/EC2): licencias JWT por plan, checkout de MercadoPago, webhook
de pago que emite la licencia sola, gateway medido del Copiloto y descarga
del instalador post-pago.

    uvicorn backend_venta.app:app --reload --port 8100

Para producción falta solo configuración real (no código):
  - MP_ACCESS_TOKEN del vendedor (MercadoPago Uruguay/LATAM) como secreto.
  - ANTHROPIC_API_KEY del gateway como secreto.
  - URL pública del webhook cargada en el panel de MercadoPago.
  - PLANIA_INSTALADOR_PATH apuntando al Setup.exe publicado.
"""
from __future__ import annotations

import os
import secrets

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend_venta import descargas, licencias, pagos, uso
from plania import auditoria as pauditoria
from plania import config as pconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP_API = "https://api.mercadopago.com"

app = FastAPI(title="Plania · Backend de venta", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # la landing estática llama a /checkout

# ---------------------------------------------------------------------------
# Rate limiting: TODO endpoint que acepta un pedido HTTP público lo tiene,
# incluso los que además exigen un token — un token inválido igual gasta CPU
# validándolo, y "/checkout" y "/gateway/copiloto" además disparan una
# llamada de pago a una API externa (MercadoPago, Anthropic) que cuesta plata
# real por golpe. El límite se guarda en memoria del proceso: alcanza porque
# el Procfile levanta un único proceso uvicorn, no varias réplicas — si el
# día de mañana se escala horizontalmente, este Limiter necesita un backend
# compartido (Redis) o cada réplica cuenta aparte y el límite real efectivo
# se multiplica por la cantidad de réplicas.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Autenticación: licencia (clientes) y admin (vos)
# ---------------------------------------------------------------------------
def requerir_licencia(authorization: str = Header(...)) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    r = licencias.licencia_activa(token)
    if not r["ok"]:
        raise HTTPException(401, r["error"])
    return r["claims"]


def _admin_token() -> str:
    t = os.environ.get("PLANIA_BACKEND_ADMIN_TOKEN") or pconfig.leer_extra("BACKEND_ADMIN_TOKEN")
    if not t:
        t = secrets.token_hex(24)
        pconfig.guardar_extra("BACKEND_ADMIN_TOKEN", t)
        print(f"[backend_venta] Token de admin generado (guardalo, no se vuelve a mostrar): {t}")
    return t


def requerir_admin(authorization: str = Header(...)) -> None:
    recibido = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(recibido, _admin_token()):
        raise HTTPException(403, "no autorizado")


def _chequear_cupo(claims: dict) -> None:
    cupo = claims.get("cupo_mensual")
    if cupo is None:
        return  # enterprise / sin tope
    usados = uso.consultas_mes(claims["sub"])
    if usados >= cupo and not licencias.plan_permite_excedente(claims.get("plan", "")):
        raise HTTPException(402, "Cupo mensual agotado para este plan.")


# ---------------------------------------------------------------------------
# 1) Planes y licencias
# ---------------------------------------------------------------------------
@app.get("/planes")
@limiter.limit("60/minute")
async def planes(request: Request):
    """Público: la landing y la app muestran esto (una sola fuente de verdad).
    Catálogo estático sin costo de cómputo real — el límite es generoso, solo
    para frenar un scraper o un bucle roto, no tráfico normal."""
    return {p: {k: v for k, v in d.items()} for p, d in licencias.PLANES_PUBLICOS.items()}


@app.post("/licencias/emitir")
@limiter.limit("10/minute")
async def emitir(request: Request, payload: dict, _admin: None = Depends(requerir_admin)):
    """Emisión manual (venta directa, soporte, partners) — sin MercadoPago.
    Exige token de admin, pero el límite va antes de esa validación: sin él,
    alguien puede probar tokens a fuerza bruta tan rápido como su ancho de
    banda lo permita."""
    cliente_id = str(payload.get("cliente_id") or "").strip()
    plan = str(payload.get("plan") or "starter")
    if not cliente_id:
        raise HTTPException(400, "falta 'cliente_id'")
    if plan not in licencias.PLANES:
        raise HTTPException(400, f"plan inválido: {plan!r}")
    lic = licencias.emitir_licencia(cliente_id, plan)
    pauditoria.registrar("licencia_emitida_manual", {"cliente": cliente_id, "plan": plan})
    return {"licencia": lic, "plan": plan}


@app.post("/licencias/trial")
@limiter.limit("5/minute")
async def trial(request: Request, payload: dict):
    """Demo 7 días full self-service: solo pide un email. Una por email.
    Es el endpoint más expuesto a abuso — nadie necesita credenciales para
    llamarlo — así que el límite es el más estricto de los públicos sin
    auth: alcanza de sobra para un humano probando el formulario y no
    alcanza para generar licencias en cantidad."""
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "email inválido")
    if uso.ya_uso_trial(email):
        raise HTTPException(409, "ese email ya usó la demo — escribinos y la extendemos")
    lic = licencias.emitir_licencia(email, "trial")
    uso.marcar_trial(email)
    pauditoria.registrar("trial_emitido", {"cliente": email})
    return {"licencia": lic, "plan": "trial", "dias": licencias.PLANES["trial"]["dias"]}


@app.get("/licencias/estado")
@limiter.limit("30/minute")
async def estado(request: Request, claims: dict = Depends(requerir_licencia)):
    u = uso.uso_mes(claims["sub"])
    return {
        "cliente": claims["sub"], "plan": claims["plan"],
        "cupo_mensual": claims.get("cupo_mensual"), "usado_este_mes": u["consultas"],
        "features": claims.get("features", []), "expira": claims["exp"],
    }


# ---------------------------------------------------------------------------
# 2) Checkout MercadoPago (preferencia) + webhook que emite la licencia
# ---------------------------------------------------------------------------
def _mp_token() -> str:
    t = os.environ.get("MP_ACCESS_TOKEN") or pconfig.leer_extra("MP_ACCESS_TOKEN")
    if not t:
        raise HTTPException(503, "MP_ACCESS_TOKEN no configurado en el servidor")
    return t


@app.post("/checkout")
@limiter.limit("10/minute")
async def checkout(request: Request, payload: dict):
    """Crea la preferencia de pago y devuelve el link (init_point). La landing
    y la pantalla 'Planes' de la app apuntan acá. Cada llamada golpea la API
    de MercadoPago — sin límite, alguien podría hacer que el servidor le
    generara preferencias de pago sin fin, gratis para el atacante."""
    plan = str(payload.get("plan") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if plan not in licencias.PLANES or not licencias.PLANES[plan]["precio"]:
        raise HTTPException(400, f"plan no comprable online: {plan!r}")
    if "@" not in email:
        raise HTTPException(400, "email inválido")
    p = licencias.PLANES[plan]
    base = os.environ.get("PLANIA_PUBLIC_URL", "https://plania.uy")
    pref = {
        "items": [{
            "title": f"Plania · plan {plan} ({p['dias']} días)",
            "quantity": 1,
            "currency_id": os.environ.get("PLANIA_MONEDA", "USD"),
            "unit_price": float(p["precio"]),
        }],
        "payer": {"email": email},
        "metadata": {"plan": plan, "email": email},
        "back_urls": {"success": f"{base}/gracias", "failure": f"{base}/error",
                      "pending": f"{base}/pendiente"},
        "auto_return": "approved",
        "notification_url": os.environ.get(
            "PLANIA_WEBHOOK_URL", f"{base}/webhooks/mercadopago"),
    }
    r = requests.post(f"{MP_API}/checkout/preferences", json=pref,
                      headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        raise HTTPException(502, f"MercadoPago rechazó la preferencia: {r.text[:300]}")
    data = r.json()
    pauditoria.registrar("checkout_creado", {"plan": plan, "email": email,
                                             "preference_id": data.get("id")})
    return {"ok": True, "init_point": data.get("init_point"),
            "preference_id": data.get("id")}


@app.post("/webhooks/mercadopago")
@limiter.limit("30/minute")
async def webhook_mercadopago(request: Request, payload: dict):
    """Nunca confiar en el cuerpo del webhook: se re-consulta el pago contra
    la API real de MercadoPago con el Access Token del servidor, y recién con
    status=approved se emite la licencia.

    El límite por IP acá es una defensa imperfecta a propósito generosa: el
    llamante real es MercadoPago, no un usuario, y sus notificaciones pueden
    salir de varias IPs y reintentar pagos legítimos. Lo que sí evita es que
    cualquiera en internet — sin ser MercadoPago — haga que el servidor
    dispare cientos de verificaciones contra la API real por minuto (que es
    lo que de verdad cuesta acá: no el guardado local, sino el `requests.get`
    contra MP_API en cada llamada)."""
    if payload.get("type") != "payment":
        return {"ok": True, "ignorado": True}

    payment_id = (payload.get("data") or {}).get("id")
    if not payment_id:
        raise HTTPException(400, "falta data.id en el webhook")

    ya = pagos.buscar(payment_id)
    if ya:
        # MercadoPago reenvía la notificación hasta recibir un 200, así que
        # ver el mismo pago dos veces es lo normal, no un ataque. Lo que no
        # puede pasar es que emita una licencia nueva cada vez: el comprador
        # conoce su propio payment_id —MP se lo devuelve en la URL de
        # retorno— y podría fabricarse licencias pro ilimitadas repitiendo
        # este POST a mano.
        return {"ok": True, "licencia": ya["licencia"],
                "token_descarga": ya["token_descarga"], "plan": ya["plan"],
                "repetido": True}

    r = requests.get(f"{MP_API}/v1/payments/{payment_id}",
                     headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        raise HTTPException(502, "no se pudo verificar el pago contra MercadoPago")
    pago = r.json()
    if pago.get("status") != "approved":
        return {"ok": True, "estado": pago.get("status")}

    emitido = _emitir_por_pago(payment_id, pago)
    return {"ok": True, "licencia": emitido["licencia"],
            "token_descarga": emitido["token_descarga"], "plan": emitido["plan"]}


def _emitir_por_pago(payment_id: str, pago: dict) -> dict:
    """Emite (o recupera) la licencia de un pago aprobado.

    Lo usan el webhook y el rescate del comprador. Los dos pueden llegar
    primero —MercadoPago manda al comprador a la página de gracias y notifica
    por su lado, sin orden garantizado—, así que la operación tiene que dar el
    mismo resultado sin importar quién llegue antes.
    """
    md = pago.get("metadata") or {}
    plan = md.get("plan", "starter")
    cliente_id = md.get("email") or md.get("cliente_id") or str(payment_id)
    if plan not in licencias.PLANES:
        plan = "starter"

    lic = licencias.emitir_licencia(cliente_id, plan)
    token_descarga = descargas.crear_token_descarga(cliente_id)
    guardado = pagos.registrar(payment_id, cliente_id, plan, lic, token_descarga)
    # `registrar` devuelve lo que quedó en la base: si otra llamada ganó la
    # carrera, se usa la suya y la nuestra se descarta.
    if guardado["licencia"] == lic:
        pauditoria.registrar("licencia_emitida_pago",
                             {"cliente": cliente_id, "plan": plan,
                              "payment_id": payment_id})
    return guardado


@app.get("/licencias/por-pago/{payment_id}")
@limiter.limit("20/minute")
async def licencia_por_pago(request: Request, payment_id: str):
    """Le entrega al comprador la licencia de SU pago.

    Existe porque el webhook le responde a MercadoPago, no al comprador: la
    licencia viajaba en un cuerpo que MP descarta. El cliente pagaba y no
    recibía nada.

    Acá el comprador llega desde la página de gracias con el `payment_id` que
    MercadoPago le puso en la URL de retorno. Antes de entregar nada se
    re-consulta el pago contra la API real de MercadoPago: saber un
    `payment_id` no alcanza, tiene que estar aprobado de verdad. Y como
    `_emitir_por_pago` es idempotente, pedirla diez veces devuelve siempre la
    misma licencia, no diez.
    """
    ya = pagos.buscar(payment_id)
    if ya:
        return {"ok": True, "licencia": ya["licencia"],
                "token_descarga": ya["token_descarga"], "plan": ya["plan"]}

    # Todavía no llegó el webhook: se verifica y se emite acá mismo, para que
    # el comprador no tenga que esperar ni reintentar.
    r = requests.get(f"{MP_API}/v1/payments/{payment_id}",
                     headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        raise HTTPException(502, "no se pudo verificar el pago contra MercadoPago")
    pago = r.json()
    if pago.get("status") != "approved":
        raise HTTPException(404, "ese pago todavía no está aprobado")

    emitido = _emitir_por_pago(payment_id, pago)
    return {"ok": True, "licencia": emitido["licencia"],
            "token_descarga": emitido["token_descarga"], "plan": emitido["plan"]}


# ---------------------------------------------------------------------------
# 3) Gateway medido del Copiloto (los clientes no manejan API keys)
# ---------------------------------------------------------------------------
@app.post("/gateway/copiloto")
@limiter.limit("20/minute")
async def gateway_copiloto(request: Request, payload: dict,
                           claims: dict = Depends(requerir_licencia)):
    """El límite por IP es una primera barrera antes de gastar Anthropic; el
    tope real de negocio (cupo_mensual por plan) lo aplica `_chequear_cupo`
    más abajo — son dos cosas distintas: esto frena una ráfaga en segundos,
    aquello frena el consumo a lo largo del mes. Ninguno reemplaza al otro:
    sin este límite, una licencia válida usada desde un script en loop
    quema cupo mensual entero en la primera hora, aunque después el mes
    quede sin servicio para el cliente real."""
    if "copiloto" not in claims.get("features", []):
        raise HTTPException(403, "el plan no incluye el Copiloto IA")
    texto = str(payload.get("texto", ""))[:6000].strip()
    if not texto:
        raise HTTPException(400, "falta 'texto'")
    key = os.environ.get("ANTHROPIC_API_KEY") or pconfig.leer_extra("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(503, "ANTHROPIC_API_KEY no configurada en el gateway")

    with uso.lock_cliente(claims["sub"]):
        _chequear_cupo(claims)
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 600,
                      "messages": [{"role": "user", "content": texto}]},
                timeout=30)
            data = r.json()
            if not r.ok:
                raise HTTPException(502, (data.get("error") or {}).get("message",
                                                                       "error de Anthropic"))
            usage = data.get("usage", {})
            uso.registrar_uso(claims["sub"], canal="copiloto",
                              ref_id=payload.get("ref_id"),
                              tok_in=usage.get("input_tokens", 0),
                              tok_out=usage.get("output_tokens", 0))
            return {"ok": True, "raw": (data.get("content") or [{}])[0].get("text", "")}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"error llamando a Claude: {e}") from e


# ---------------------------------------------------------------------------
# 4) Descarga del instalador post-pago
# ---------------------------------------------------------------------------
@app.get("/descargar/{token}")
@limiter.limit("20/minute")
async def descargar(request: Request, token: str):
    """El token es largo y de un solo uso pensado, pero el límite es defensa
    en profundidad contra que alguien lo intente adivinar a fuerza bruta en
    vez de confiar solo en el espacio de valores del token."""
    r = descargas.validar_token_descarga(token)
    if not r["ok"]:
        raise HTTPException(403, r["error"])
    ruta = os.environ.get("PLANIA_INSTALADOR_PATH",
                          os.path.join(ROOT, "dist", "Plania_Setup.exe"))
    if not os.path.exists(ruta):
        raise HTTPException(503, "El instalador todavía no está publicado en este servidor "
                                 "(configurá PLANIA_INSTALADOR_PATH).")
    return FileResponse(ruta, filename=os.path.basename(ruta))


@app.get("/salud")
@limiter.limit("120/minute")
async def salud(request: Request):
    """No devuelve nada sensible ni cuesta cómputo, pero se limita igual —
    "todo endpoint público" no tiene excepción para el que parece inofensivo
    — con un techo alto para no interferir con un uptime monitor real."""
    return {"ok": True, "servicio": "backend_venta"}
