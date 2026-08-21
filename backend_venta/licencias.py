# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Licencias firmadas (JWT) — Edición Venta
=================================================
Implementación real de la sección 2 de `docs/BACKEND_VENTA.md` (que hasta
ahora era solo un esbozo de diseño). Emite y valida tokens JWT (HS256)
atados a plan, cupo mensual y features habilitadas.

El secreto de firma se persiste con el mismo backend seguro que las demás
claves de Plania (`plania/config.py`: keyring del SO > archivo cifrado > texto
plano) — se genera solo la primera vez que hace falta, y no se hardcodea
en ningún lado. También se puede fijar explícitamente con la variable de
entorno `PLANIA_LICENSE_SECRET` (recomendado en producción, para poder
rotarlo sin depender del archivo local).
"""
from __future__ import annotations

import os
import secrets
import time

import jwt

from plania import config as kconfig

_CLAVE_SECRETO = "LICENSE_SECRET"

# Nota sobre el trial: es la "demo 7 días full" del modelo comercial — TODAS
# las features habilitadas (copiloto, ERP, exportes, rutas) con cupo real,
# para que el prospecto pruebe el producto completo contra SUS datos antes de
# pagar. Vence solo a los 7 días; convertir = pagar por MercadoPago (webhook
# emite la licencia definitiva sin intervención manual).
PLANES = {
    "trial":      {"cupo_mensual": 300,  "precio": 0.0,   "dias": 7,
                   "features": ["copiloto", "erp", "exportes", "rutas"]},
    # `rutas` está acá porque la demo ya las trae: sin esto, quien probaba 7
    # días y pagaba el plan más barato PERDÍA una función que ya estaba
    # usando. Un downgrade al momento de cobrar es la forma más cara de
    # arrancar una relación con un cliente — el reclamo llega el primer día y
    # el reembolso también.
    #
    # Pro sigue diferenciándose por lo que de verdad escala con el uso: cuatro
    # veces el cupo de consultas (2000 contra 500) y `excedente`, que es poder
    # pasarse de ese cupo en vez de quedar cortado.
    "starter":    {"cupo_mensual": 500,  "precio": 59.0,  "dias": 30,
                   "features": ["copiloto", "erp", "exportes", "rutas"]},
    "pro":        {"cupo_mensual": 2000, "precio": 129.0, "dias": 30,
                   "features": ["copiloto", "erp", "exportes", "rutas", "excedente"]},
    "enterprise": {"cupo_mensual": None, "precio": None,  "dias": 30,
                   "features": ["copiloto", "erp", "exportes", "rutas", "excedente",
                                "white_label", "sso", "multi_sucursal"]},
    # Para el dueño del producto: todas las features, sin cupo, sin poder
    # comprarse (precio=None → /checkout la rechaza igual que a enterprise) y
    # sin poder emitirse por autoservicio: solo sale de
    # packaging/generar_licencia_owner.py o de /licencias/emitir con el
    # token de admin — las dos vías requieren tener el secreto de firma real,
    # así que no es un bypass público, es la misma licencia paga de siempre
    # con otro titular. 36500 días (100 años) en vez de omitir `exp`: que
    # nunca venza en la práctica sin dejar el claim ausente, que otros
    # lugares del código (p. ej. GET /licencias/estado) asumen presente.
    "owner":      {"cupo_mensual": None, "precio": None,  "dias": 36500,
                   "features": ["copiloto", "erp", "exportes", "rutas", "excedente",
                                "white_label", "sso", "multi_sucursal"]},
}

# Planes que se listan en /planes (la landing y la pantalla "Planes y
# licencia"). "owner" existe y es válido para emitir/validar, pero no es un
# plan de catálogo: no tiene sentido mostrarlo en una página pública.
PLANES_PUBLICOS = {p: d for p, d in PLANES.items() if p != "owner"}


def secreto_firma() -> str:
    """Secreto HS256 activo: env var > guardado > generado una sola vez."""
    s = os.environ.get("PLANIA_LICENSE_SECRET")
    if s:
        return s
    s = kconfig.leer_extra(_CLAVE_SECRETO)
    if s:
        return s
    s = secrets.token_hex(32)
    kconfig.guardar_extra(_CLAVE_SECRETO, s)
    return s


def plan_permite_excedente(plan: str) -> bool:
    return "excedente" in PLANES.get(plan, {}).get("features", [])


def emitir_licencia(cliente_id: str, plan: str, edicion: str = "venta",
                    cupo_mensual: int | None = None, features: list[str] | None = None,
                    dias: int | None = None, secreto: str | None = None) -> str:
    """
    Emite un JWT de licencia. Si `cupo_mensual`/`features`/`dias` no se pasan,
    se toman del plan (`PLANES`). `plan="enterprise"` sin cupo explícito
    significa "sin tope" — lo valida el gateway, no la librería.
    """
    if plan not in PLANES:
        raise ValueError(f"plan desconocido: {plan!r} (válidos: {list(PLANES)})")
    cfg = PLANES[plan]
    cupo = cupo_mensual if cupo_mensual is not None else cfg["cupo_mensual"]
    feats = features if features is not None else cfg["features"]
    dias_val = dias if dias is not None else cfg["dias"]
    ahora = int(time.time())
    payload = {
        "sub": cliente_id, "plan": plan, "edition": edicion,
        "cupo_mensual": cupo, "features": feats,
        "iat": ahora, "exp": ahora + dias_val * 24 * 3600,
    }
    return jwt.encode(payload, secreto or secreto_firma(), algorithm="HS256")


def validar_licencia(token: str, secreto: str | None = None) -> dict:
    """Decodifica y valida la licencia. Lanza jwt.PyJWTError si es inválida/expirada."""
    return jwt.decode(token, secreto or secreto_firma(), algorithms=["HS256"])


def licencia_activa(token: str, secreto: str | None = None) -> dict:
    """Igual que validar_licencia, pero devuelve un dict con {ok, error, claims}
    en vez de lanzar — más cómodo para endpoints HTTP."""
    try:
        claims = validar_licencia(token, secreto)
        return {"ok": True, "claims": claims, "error": None}
    except jwt.ExpiredSignatureError:
        return {"ok": False, "claims": None, "error": "licencia_expirada"}
    except jwt.PyJWTError as e:
        return {"ok": False, "claims": None, "error": f"licencia_invalida: {e}"}
