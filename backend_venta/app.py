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
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend_venta import descargas, licencias, uso
from plania import auditoria as pauditoria
from plania import config as pconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP_API = "https://api.mercadopago.com"

app = FastAPI(title="Plania · Backend de venta", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # la landing estática llama a /checkout


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
async def planes():
    """Público: la landing y la app muestran esto (una sola fuente de verdad)."""
    return {p: {k: v for k, v in d.items()} for p, d in licencias.PLANES.items()}


@app.post("/licencias/emitir")
async def emitir(payload: dict, _admin: None = Depends(requerir_admin)):
    """Emisión manual (venta directa, soporte, partners) — sin MercadoPago."""
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
async def trial(payload: dict):
    """Demo 3 días full self-service: solo pide un email. Una por email."""
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
async def estado(claims: dict = Depends(requerir_licencia)):
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
async def checkout(payload: dict):
    """Crea la preferencia de pago y devuelve el link (init_point). La landing
    y la pantalla 'Planes' de la app apuntan acá."""
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
async def webhook_mercadopago(payload: dict):
    """Nunca confiar en el cuerpo del webhook: se re-consulta el pago contra
    la API real de MercadoPago con el Access Token del servidor, y recién con
    status=approved se emite la licencia."""
    if payload.get("type") != "payment":
        return {"ok": True, "ignorado": True}

    payment_id = (payload.get("data") or {}).get("id")
    if not payment_id:
        raise HTTPException(400, "falta data.id en el webhook")

    r = requests.get(f"{MP_API}/v1/payments/{payment_id}",
                     headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        raise HTTPException(502, "no se pudo verificar el pago contra MercadoPago")
    pago = r.json()
    if pago.get("status") != "approved":
        return {"ok": True, "estado": pago.get("status")}

    md = pago.get("metadata") or {}
    plan = md.get("plan", "starter")
    cliente_id = md.get("email") or md.get("cliente_id") or str(payment_id)
    if plan not in licencias.PLANES:
        plan = "starter"

    lic = licencias.emitir_licencia(cliente_id, plan)
    token_descarga = descargas.crear_token_descarga(cliente_id)
    pauditoria.registrar("licencia_emitida_pago", {"cliente": cliente_id, "plan": plan,
                                                   "payment_id": payment_id})
    return {"ok": True, "licencia": lic, "token_descarga": token_descarga, "plan": plan}


# ---------------------------------------------------------------------------
# 3) Gateway medido del Copiloto (los clientes no manejan API keys)
# ---------------------------------------------------------------------------
@app.post("/gateway/copiloto")
async def gateway_copiloto(payload: dict, claims: dict = Depends(requerir_licencia)):
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
async def descargar(token: str):
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
async def salud():
    return {"ok": True, "servicio": "backend_venta"}
