# © 2026 Martín Viera. Todos los derechos reservados.
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

## Por qué activar_licencia() llama al backend en vez de decodificar local

Versión anterior de este módulo: `pyjwt.decode(token, options={"verify_signature":
False})`, tanto acá como en `estado()`. Eso solo mira que el JWT tenga forma
de JWT y que no esté vencido — la firma, que es lo único que demuestra que
`backend_venta` lo emitió, nunca se comprobaba. Cualquiera podía escribir:

    jwt.encode({"plan": "enterprise", "features": [...], "exp": ...},
               "cualquier-cosa", algorithm="HS256")

y activarse el plan más caro para siempre, sin pagar ni tocar el backend.
No es hipotético: quedó probado corriendo exactamente ese código contra este
módulo antes del arreglo.

El cliente no tiene el secreto de firma (vive solo en `backend_venta`, ver
`backend_venta/licencias.py::secreto_firma`), así que la única verificación
honesta es preguntarle a quien firmó: `GET /licencias/estado` con el token
como Bearer. Si el backend dice que sí, las claims que se guardan localmente
son las que **devolvió el backend**, no las que trae el token sin verificar
— así un token con un campo `features` inflado a mano nunca llega a
importar: lo que cuenta es lo que el servidor calculó a partir del claim
`plan`, que sí verificó firmado.

Consecuencia práctica: activar una licencia por primera vez pide internet.
Es razonable — se acaba de pagar, hay conexión — y así se comporta el
checkout de MercadoPago también. Para seguir funcionando días después sin
red, `estado()` reusa la última confirmación del backend durante
`_TOLERANCIA_SIN_RED_DIAS`; pasado ese margen sin poder re-confirmar, deja
de confiar en la caché en vez de creerle a un token indefinidamente.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from plania import config as pconfig

DIAS_DEMO = 7
FEATURES_DEMO = ["copiloto", "erp", "exportes", "rutas"]

_CLAVE_DEMO = "DEMO_INICIO"
_CLAVE_LICENCIA = "LICENCIA_JWT"
_CLAVE_CLAIMS = "LICENCIA_CLAIMS"
_CLAVE_VERIFICADA_EL = "LICENCIA_VERIFICADA_EL"

# Cada cuánto se vuelve a confirmar contra el backend una licencia ya
# activada (revalidación silenciosa, no vuelve a pedir el token).
_REVALIDAR_CADA_HORAS = 24
# Cuánto seguir confiando en la última confirmación si no hay forma de
# contactar al backend (viaje, oficina sin internet). Pasado esto, una
# licencia que no se puede reconfirmar deja de darse por buena.
_TOLERANCIA_SIN_RED_DIAS = 10

# Aceptación de la EULA (LICENSE-EULA.md). Versionada: si el texto cambia de
# forma sustancial, subir EULA_VERSION vuelve a pedir la aceptación en el
# siguiente arranque en vez de asumir que un "sí" viejo cubre términos nuevos.
EULA_VERSION = "1.0"
_CLAVE_EULA = "EULA_ACEPTADA"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# Valor que queda cuando nadie configuró el backend. Es el puerto donde lo
# levanta el Procfile en desarrollo, así que sigue sirviendo para probar el
# circuito en la máquina propia; lo que NO se puede es tratarlo como si fuera
# un servidor real: en una instalación de cliente ahí no hay nada escuchando.
_BACKEND_SIN_CONFIGURAR = "http://localhost:8100"


def _backend_url() -> str:
    return (os.environ.get("PLANIA_BACKEND_URL")
            or pconfig.leer_extra("BACKEND_URL") or _BACKEND_SIN_CONFIGURAR)


def iniciar_demo_si_corresponde() -> None:
    """Se llama en cada arranque: si nunca corrió, deja registrado el inicio."""
    if not pconfig.leer_extra(_CLAVE_DEMO) and not pconfig.leer_extra(_CLAVE_LICENCIA):
        pconfig.guardar_extra(_CLAVE_DEMO, _ahora().isoformat())


def _guardar_verificada(token: str, claims: dict) -> None:
    pconfig.guardar_extra(_CLAVE_LICENCIA, token)
    pconfig.guardar_extra(_CLAVE_CLAIMS, claims)
    pconfig.guardar_extra(_CLAVE_VERIFICADA_EL, _ahora().isoformat())


def _olvidar_licencia() -> None:
    pconfig.guardar_extra(_CLAVE_LICENCIA, None)
    pconfig.guardar_extra(_CLAVE_CLAIMS, None)
    pconfig.guardar_extra(_CLAVE_VERIFICADA_EL, None)


def activar_licencia(jwt_token: str, backend_url: str | None = None,
                     cliente_http=None) -> dict:
    """Activa un token consultando `/licencias/estado` en `backend_venta` —
    el único que tiene el secreto para saber si la firma es genuina.

    `cliente_http` es inyectable (acepta cualquier objeto con `.get(url,
    headers=..., timeout=...)`, como `requests` o un `TestClient` de
    Starlette) para poder probar el circuito completo sin sockets reales.

    Devuelve `{"ok": bool, "claims": {...}|None, "error": str|None,
    "motivo": "rechazada"|"red"|"sin_backend"|"formato"|None}`. `motivo`
    distingue "el backend dijo que no" de "no se pudo preguntar", porque
    `estado()` reacciona distinto a cada caso: solo `rechazada` borra la
    licencia guardada. `sin_backend` es el caso de que esta instalación no
    tenga backend configurado — se comporta como `red` (tolerancia de días
    sin reconfirmar), pero el mensaje al usuario no lo manda a revisar su
    conexión por un problema que no es suyo.
    """
    jwt_token = (jwt_token or "").strip()
    if jwt_token.count(".") != 2:
        return {"ok": False, "error": "Eso no es un token de licencia válido.",
                "motivo": "formato"}

    backend = backend_url if backend_url is not None else _backend_url()
    cliente = cliente_http
    if cliente is None:
        import requests
        cliente = requests

    try:
        kwargs = {"headers": {"Authorization": f"Bearer {jwt_token}"}}
        # El TestClient de Starlette (usado en los tests) desaconseja pasarle
        # `timeout` — solo se manda cuando el cliente es `requests` de verdad.
        if cliente_http is None:
            kwargs["timeout"] = 15
        r = cliente.get(f"{backend}/licencias/estado", **kwargs)
    except Exception:
        # Distinguir "no hay servidor de licencias configurado" de "no hay
        # internet": mandar a revisar la conexión a alguien cuya conexión
        # anda perfecto lo deja dando vueltas por un problema que no es suyo
        # ni puede resolver. Con el backend sin configurar el problema es del
        # lado de Plania, y el mensaje tiene que decirlo.
        if backend == _BACKEND_SIN_CONFIGURAR:
            return {"ok": False, "motivo": "sin_backend",
                    "error": "Esta instalación todavía no tiene servidor de "
                             "licencias configurado, así que no se puede "
                             "activar. Escribinos a ventas@plania.uy. "
                             "(Mientras tanto la prueba de 7 días funciona "
                             "igual, no necesita activación.)"}
        return {"ok": False, "motivo": "red",
                "error": "No se pudo contactar el servidor de licencias. "
                         "Probá de nuevo con internet."}

    if r.status_code == 200:
        claims = r.json()
        _guardar_verificada(jwt_token, claims)
        return {"ok": True, "claims": claims, "error": None, "motivo": None}

    detalle = None
    try:
        detalle = r.json().get("detail")
    except Exception:
        pass
    return {"ok": False, "claims": None, "motivo": "rechazada",
            "error": detalle or f"el servidor de licencias respondió {r.status_code}"}


def estado() -> dict:
    """
    Único punto que consulta la app:
      {"modo": "licencia"|"demo"|"vencida", "features": [...],
       "dias_restantes": int, "plan": str|None, "cliente": str|None}

    `licencia` sale SIEMPRE de la última confirmación del backend (`claims`
    guardadas por `activar_licencia`), nunca de decodificar el token sin
    verificar — ver el docstring del módulo.
    """
    token = pconfig.leer_extra(_CLAVE_LICENCIA)
    claims = pconfig.leer_extra(_CLAVE_CLAIMS)

    if token and claims:
        verificada_txt = pconfig.leer_extra(_CLAVE_VERIFICADA_EL)
        try:
            verificada = (datetime.fromisoformat(verificada_txt) if verificada_txt
                         else _ahora())
        except ValueError:
            verificada = _ahora()

        vencida_hace = _ahora() - verificada
        if vencida_hace > timedelta(hours=_REVALIDAR_CADA_HORAS):
            r = activar_licencia(token)
            if r["ok"]:
                claims = r["claims"]
            elif r.get("motivo") == "rechazada":
                # El backend dijo explícitamente que ya no vale (vencida,
                # cancelada): no tiene sentido seguir confiando en la caché.
                _olvidar_licencia()
                token, claims = None, None
            elif vencida_hace > timedelta(days=_TOLERANCIA_SIN_RED_DIAS):
                # Demasiado tiempo sin poder reconfirmar por red: se deja de
                # dar por buena en vez de confiar en una caché indefinida.
                _olvidar_licencia()
                token, claims = None, None
            # Si fue un problema de red y todavía está dentro de la
            # tolerancia, se sigue usando la última confirmación (`claims`
            # tal como estaba) sin tocarla.

    if token and claims:
        exp = claims.get("expira")
        if exp and exp > _ahora().timestamp():
            return {"modo": "licencia",
                    "features": claims.get("features", FEATURES_DEMO),
                    "dias_restantes": int((exp - _ahora().timestamp()) // 86400),
                    "plan": claims.get("plan"), "cliente": claims.get("cliente")}

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
