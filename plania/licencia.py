"""
Plania · Licencia del lado del cliente (demo 7 días full + licencia paga)
=========================================================================
La primera vez que se abre el programa arranca sola la **demo de 7 días con
todo habilitado** (copiloto, ERP, exportes, rutas) — sin tarjeta, sin
registro. Al vencer, el programa sigue abriendo pero pide activar una
licencia (JWT emitida por `backend_venta`, comprada por MercadoPago).

El estado vive en la config segura de Plania (keyring > archivo cifrado >
texto plano; ver `plania/config.py`), así que reinstalar no reinicia la demo
en la misma máquina de casualidad, pero tampoco hacemos DRM agresivo: esto
es un producto B2B, el candado real es el vencimiento del JWT.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plania import config as pconfig

DIAS_DEMO = 7
FEATURES_DEMO = ["copiloto", "erp", "exportes", "rutas"]

_CLAVE_DEMO = "DEMO_INICIO"
_CLAVE_LICENCIA = "LICENCIA_JWT"

# Aceptación de la EULA (LICENSE-EULA.md). Versionada: si el texto cambia de
# forma sustancial, subir EULA_VERSION vuelve a pedir la aceptación en el
# siguiente arranque en vez de asumir que un "sí" viejo cubre términos nuevos.
EULA_VERSION = "1.0"
_CLAVE_EULA = "EULA_ACEPTADA"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def iniciar_demo_si_corresponde() -> None:
    """Se llama en cada arranque: si nunca corrió, deja registrado el inicio."""
    if not pconfig.leer_extra(_CLAVE_DEMO) and not pconfig.leer_extra(_CLAVE_LICENCIA):
        pconfig.guardar_extra(_CLAVE_DEMO, _ahora().isoformat())


def activar_licencia(jwt_token: str) -> dict:
    """Valida el formato y la vigencia del token y lo guarda. La firma la
    valida el backend en cada consulta de estado online; localmente
    verificamos expiración y claims para el modo offline."""
    import jwt as pyjwt
    try:
        claims = pyjwt.decode(jwt_token, options={"verify_signature": False})
    except Exception as e:
        return {"ok": False, "error": f"token inválido: {e}"}
    if claims.get("exp") and claims["exp"] < _ahora().timestamp():
        return {"ok": False, "error": "la licencia ya está vencida"}
    pconfig.guardar_extra(_CLAVE_LICENCIA, jwt_token)
    return {"ok": True, "claims": claims}


def estado() -> dict:
    """
    Único punto que consulta la app:
      {"modo": "licencia"|"demo"|"vencida", "features": [...],
       "dias_restantes": int, "plan": str|None, "cliente": str|None}
    """
    token = pconfig.leer_extra(_CLAVE_LICENCIA)
    if token:
        import jwt as pyjwt
        try:
            claims = pyjwt.decode(token, options={"verify_signature": False})
            exp = datetime.fromtimestamp(claims.get("exp", 0), tz=timezone.utc)
            if exp > _ahora():
                return {"modo": "licencia",
                        "features": claims.get("features", FEATURES_DEMO),
                        "dias_restantes": (exp - _ahora()).days,
                        "plan": claims.get("plan"), "cliente": claims.get("sub")}
        except Exception:
            pass  # token roto -> cae a demo/vencida

    inicio_txt = pconfig.leer_extra(_CLAVE_DEMO)
    if inicio_txt:
        try:
            inicio = datetime.fromisoformat(inicio_txt)
        except ValueError:
            inicio = _ahora()
        fin = inicio + timedelta(days=DIAS_DEMO)
        if fin > _ahora():
            return {"modo": "demo", "features": FEATURES_DEMO,
                    "dias_restantes": max(0, (fin - _ahora()).days),
                    "horas_restantes": int((fin - _ahora()).total_seconds() // 3600),
                    "plan": "trial", "cliente": None}
        return {"modo": "vencida", "features": [], "dias_restantes": 0,
                "plan": None, "cliente": None}

    # primer arranque sin registro todavía
    iniciar_demo_si_corresponde()
    return {"modo": "demo", "features": FEATURES_DEMO, "dias_restantes": DIAS_DEMO,
            "horas_restantes": DIAS_DEMO * 24, "plan": "trial", "cliente": None}


def tiene(feature: str) -> bool:
    return feature in estado()["features"]


def eula_aceptada() -> bool:
    """Se consulta antes de dejar entrar a cualquier pantalla con datos."""
    return pconfig.leer_extra(_CLAVE_EULA) == EULA_VERSION


def aceptar_eula() -> None:
    pconfig.guardar_extra(_CLAVE_EULA, EULA_VERSION)
