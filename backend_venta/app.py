# © 2026 Martín Viera. Todos los derechos reservados.
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

import logging
import os
import secrets

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend_venta import descargas, licencias, pagos, uso
from plania import auditoria as pauditoria
from plania import config as pconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP_API = "https://api.mercadopago.com"

# Solo para los 5xx — un fallo de ESTE servidor, no un pedido mal formado del
# cliente. `pauditoria.registrar` ya deja constancia de cada licencia emitida
# con éxito; lo que faltaba era el camino inverso: cuando MercadoPago o
# Anthropic no contestan bien, o falta un secreto, la respuesta al llamante
# ya lo dice (HTTPException viaja igual), pero nada quedaba de este lado. Con
# reintentos automáticos de MercadoPago hasta recibir 200, una falla
# sistémica (token rotado, por ejemplo) fallaría cada webhook en silencio: el
# primer síntoma visible sería un cliente que pagó y no recibió licencia,
# días después, sin ningún registro que explique por qué. Nunca se loguea el
# secreto en sí, solo que la llamada que lo usa falló.
logger = logging.getLogger("backend_venta")

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


@app.post("/demo/solicitar")
@limiter.limit("5/minute")
async def solicitar_demo(request: Request, payload: dict):
    """Un pedido de demo. NO entrega licencia: la habilita el dueño después.

    Reemplaza al autoservicio que había acá antes, donde cualquiera con un
    email recibía al instante una licencia de 7 días con todo habilitado. Eso
    le regalaba el producto entero —incluido el ejecutable— a quien pasara,
    sin dejar rastro de quién era ni forma de distinguir un prospecto de un
    competidor mirando cómo está hecho.

    Por eso se piden nombre, empresa y país además del email: son los datos
    que hacen que el pedido sirva para decidir a quién le mostrás y para
    llamarlo. Quedan guardados y se ven en el panel del dueño.

    El límite por IP sigue siendo el más estricto de los públicos sin
    credenciales: alcanza para una persona completando el formulario y no
    para llenar la base de pedidos falsos.
    """
    def _campo(clave: str, maximo: int = 120) -> str:
        return str(payload.get(clave) or "").strip()[:maximo]

    email = _campo("email").lower()
    nombre, empresa, pais = _campo("nombre"), _campo("empresa"), _campo("pais", 60)

    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Escribí un email de contacto válido.")
    faltan = [n for n, v in (("nombre", nombre), ("empresa", empresa), ("país", pais))
              if len(v) < 2]
    if faltan:
        raise HTTPException(400, f"Falta completar: {', '.join(faltan)}.")

    uso.registrar_solicitud_demo(email, nombre, empresa, pais,
                                 _campo("mensaje", 600))
    pauditoria.registrar("demo_solicitada",
                         {"cliente": email, "empresa": empresa, "pais": pais})
    return {"ok": True,
            "mensaje": "Recibimos tu pedido. Te escribimos para coordinar una "
                       "demo en vivo con tus propios datos."}


@app.post("/licencias/trial")
@limiter.limit("5/minute")
async def trial(request: Request, payload: dict,
                _admin: None = Depends(requerir_admin)):
    """Emite la demo de 7 días. Sólo el dueño, después de atender el pedido.

    Antes era autoservicio: bastaba mandar un email para llevarse una licencia
    full. Ahora exige el token de administrador, así que la demo se entrega
    cuando vos decidís, sobre el pedido que llegó por `/demo/solicitar`.

    Se mantiene el control de una demo por email: que la habilites vos no
    quita que alguien pueda pedirla dos veces con la misma dirección.
    """
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
        logger.error("MP_ACCESS_TOKEN no configurado: ningún checkout ni "
                     "webhook puede procesarse hasta que se cargue.")
        raise HTTPException(503, "MP_ACCESS_TOKEN no configurado en el servidor")
    return t


def _url_propia(request: Request) -> str:
    """URL pública de ESTE servicio, deducida del pedido entrante.

    Se fuerza `https` salvo en localhost: detrás del proxy de Render/Fly la
    conexión interna llega en claro, así que `request.base_url` diría `http://`
    — y MercadoPago rechaza un `notification_url` que no sea HTTPS.
    """
    url = str(request.base_url).rstrip("/")
    if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
        url = "https://" + url[len("http://"):]
    return url


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
        # El webhook lo atiende ESTE servicio, no la landing. Antes el valor
        # por defecto se armaba sobre `base` (plania.uy), que es un sitio
        # estático en Vercel: MercadoPago notificaba a una URL que devuelve
        # 404, así que un pago aprobado no emitía licencia salvo que el
        # comprador entrara a /gracias y la rescatara a mano. Ahora sale de la
        # URL por la que llegó este mismo pedido.
        "notification_url": os.environ.get(
            "PLANIA_WEBHOOK_URL", f"{_url_propia(request)}/webhooks/mercadopago"),
    }
    r = requests.post(f"{MP_API}/checkout/preferences", json=pref,
                      headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        logger.error("MercadoPago rechazó la preferencia (plan=%s, status=%s): %s",
                     plan, r.status_code, r.text[:300])
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
        # MercadoPago reintenta este webhook hasta recibir un 200 — si esto
        # falla siempre (token rotado, por ejemplo), el síntoma que ve el
        # dueño del negocio es "un cliente pagó y no le llegó la licencia",
        # sin ninguna pista de por qué. Esto es la pista.
        logger.error("Webhook: no se pudo verificar payment_id=%s contra "
                     "MercadoPago (status=%s): %s", payment_id, r.status_code, r.text[:300])
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


def _es_el_comprador(email: str, cliente_id: str) -> bool:
    """¿El que pregunta es el que pagó?

    Se compara en tiempo constante y sin distinguir mayúsculas: el comprador
    escribe su email a mano en la página de gracias y puede tipearlo distinto
    de como lo puso en MercadoPago.
    """
    return secrets.compare_digest(email.strip().lower(), (cliente_id or "").strip().lower())


@app.get("/licencias/por-pago/{payment_id}")
@limiter.limit("20/minute")
async def licencia_por_pago(request: Request, payment_id: str, email: str = ""):
    """Le entrega al comprador la licencia de SU pago.

    Existe porque el webhook le responde a MercadoPago, no al comprador: la
    licencia viajaba en un cuerpo que MP descarta. El cliente pagaba y no
    recibía nada.

    Pide el email además del `payment_id`, y no es burocracia: el `payment_id`
    viaja a la vista en la URL de retorno y los de MercadoPago son numéricos,
    o sea enumerables. Sin el email, cualquiera que probara identificadores se
    llevaba la licencia y el token de descarga de OTRO comprador — probado:
    con el pago ya registrado, un tercero que sólo sabía el número recibía las
    dos cosas. El docstring anterior decía que el pago se re-verificaba contra
    MercadoPago antes de entregar nada, y era cierto sólo en el camino de
    rescate: cuando el pago ya estaba en la base —el caso normal— devolvía sin
    comprobar nada.

    El email lo sabe el comprador (lo acaba de escribir para pagar) y no lo
    sabe quien enumera. `_emitir_por_pago` sigue siendo idempotente: pedirla
    diez veces devuelve la misma licencia, no diez.
    """
    if not email.strip():
        raise HTTPException(
            400, "Falta el email con el que se hizo la compra.")

    ya = pagos.buscar(payment_id)
    if ya:
        if not _es_el_comprador(email, ya["cliente_id"]):
            # Mismo texto que "no existe": distinguirlos le confirma a quien
            # enumera que ese pago existe y sólo le falta el email.
            raise HTTPException(404, "No encontramos una compra con esos datos.")
        return {"ok": True, "licencia": ya["licencia"],
                "token_descarga": ya["token_descarga"], "plan": ya["plan"]}

    # Todavía no llegó el webhook: se verifica y se emite acá mismo, para que
    # el comprador no tenga que esperar ni reintentar.
    r = requests.get(f"{MP_API}/v1/payments/{payment_id}",
                     headers={"Authorization": f"Bearer {_mp_token()}"}, timeout=15)
    if not r.ok:
        logger.error("Rescate: no se pudo verificar payment_id=%s contra "
                     "MercadoPago (status=%s): %s", payment_id, r.status_code, r.text[:300])
        raise HTTPException(502, "no se pudo verificar el pago contra MercadoPago")
    pago = r.json()
    if pago.get("status") != "approved":
        raise HTTPException(404, "ese pago todavía no está aprobado")

    # El mismo control que arriba, antes de emitir. Sin esto el rescate era la
    # puerta de atrás del control: alcanzaba con enumerar pagos que el webhook
    # todavía no hubiera procesado para hacerse emitir la licencia de otro.
    md = pago.get("metadata") or {}
    del_pago = md.get("email") or md.get("cliente_id") or ""
    if not _es_el_comprador(email, del_pago):
        raise HTTPException(404, "No encontramos una compra con esos datos.")

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
        logger.error("ANTHROPIC_API_KEY no configurada: el Copiloto no responde "
                     "a ningún cliente hasta que se cargue.")
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
                # Nunca la key ni el texto de la consulta (puede llevar datos
                # del negocio del cliente): sólo lo que Anthropic contestó.
                logger.error("Copiloto: Anthropic devolvió %s para cliente=%s: %s",
                             r.status_code, claims.get("sub"), data.get("error"))
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
            logger.exception("Copiloto: fallo inesperado llamando a Claude "
                             "para cliente=%s", claims.get("sub"))
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
    # Se mira el token SIN consumirlo, porque abajo puede no haber nada que
    # entregar. Consumirlo primero —como estaba— significaba que un servidor
    # sin el instalador publicado le quemaba al comprador su única descarga:
    # devolvía 503, y cuando el instalador aparecía, el mismo token ya daba
    # 403 "ya usado". Pagó, no bajó nada, y encima perdió el derecho a bajarlo.
    r = descargas.validar_token_descarga(token, marcar_usado=False)
    if not r["ok"]:
        raise HTTPException(403, r["error"])

    # Dos formas de tener el instalador, y el orden importa.
    #
    # PLANIA_INSTALADOR_URL es la que funciona en un PaaS: el instalador pesa
    # ~200 MB y se publica en la página de Releases, no viaja en el repo ni
    # entra en el disco efímero de un plan free. Sin esto, el circuito
    # terminaba en 503 justo después de cobrar — el comprador pagaba, recibía
    # su token, hacía clic y no bajaba nada.
    #
    # Que el archivo de Releases sea público no debilita esto: el instalador
    # ya se descarga sin pagar (la demo de 7 días es gratis y no necesita
    # licencia). Lo que se paga es la licencia, y eso lo sigue gobernando la
    # firma del JWT, no quién puede bajar el .exe.
    url = os.environ.get("PLANIA_INSTALADOR_URL", "").strip()
    ruta = os.environ.get("PLANIA_INSTALADOR_PATH",
                          os.path.join(ROOT, "dist", "Plania_Setup.exe"))
    if not url and not os.path.exists(ruta):
        # Quien llega hasta acá ya pagó y tiene un token válido de un solo uso
        # — este 503 es "pagaste bien y no hay nada que darte", el peor
        # momento posible para que quede sin rastro.
        logger.error("Token de descarga válido pero no hay instalador: "
                     "PLANIA_INSTALADOR_URL vacía y no existe %s", ruta)
        raise HTTPException(503, "El instalador todavía no está publicado en este servidor "
                                 "(configurá PLANIA_INSTALADOR_URL o PLANIA_INSTALADOR_PATH).")

    # Recién con algo que entregar en la mano se gasta el token. Entre este
    # chequeo y el consumo hay una ventana en la que dos pedidos simultáneos
    # podrían pasar los dos, pero el resultado de eso es que alguien que pagó
    # baje dos veces el mismo instalador — mucho menos grave que no poder
    # bajarlo.
    consumido = descargas.validar_token_descarga(token)
    if not consumido["ok"]:
        raise HTTPException(403, consumido["error"])
    if url:
        return RedirectResponse(url, status_code=302)
    return FileResponse(ruta, filename=os.path.basename(ruta))


@app.get("/salud")
@limiter.limit("120/minute")
async def salud(request: Request):
    """No devuelve nada sensible ni cuesta cómputo, pero se limita igual —
    "todo endpoint público" no tiene excepción para el que parece inofensivo
    — con un techo alto para no interferir con un uptime monitor real."""
    return {"ok": True, "servicio": "backend_venta"}
