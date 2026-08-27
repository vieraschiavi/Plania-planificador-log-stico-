# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Avisos al dueño por correo
====================================
Un mail cuando pasa algo que merece que sueltes lo que estás haciendo: alguien
pidió una demo, alguien hizo clic en comprar, alguien pagó. El resto del estado
del negocio vive en el panel del dueño y no necesita interrumpirte.

Usa `smtplib` de la biblioteca estándar. Sin dependencias nuevas: un servidor
de venta que sólo manda un puñado de mails por día no justifica sumar un SDK ni
una cuenta más.

**Nunca rompe ni demora el pedido que lo disparó.** El envío sale en un hilo
aparte porque `smtplib` es bloqueante y los tres llamadores son `async def`
sobre un único proceso de uvicorn: esperar el SMTP ahí adentro no frena sólo a
quien disparó el aviso, frena a TODOS —el comprador que está pidiendo su
licencia, el copiloto de otro cliente, el webhook que le tiene que contestar
200 a MercadoPago antes de que reintente—. Un SMTP con el puerto filtrado (lo
habitual en planes gratuitos) son 10 segundos por operación y hasta ~40 en la
cadena entera: suficiente para dejar el servicio inutilizable.

Configurar (una vez, en Render → Environment):

    SMTP_HOST      smtp.gmail.com
    SMTP_PORT      587
    SMTP_USER      tu-cuenta@gmail.com
    SMTP_PASSWORD  clave de aplicación de Google (NO la de tu cuenta)
    SMTP_FROM      tu-cuenta@gmail.com        (opcional, por defecto SMTP_USER)
    PLANIA_AVISOS_A  adónde llegan los avisos (opcional, por defecto SMTP_USER)

La clave de aplicación se saca en https://myaccount.google.com/apppasswords y
requiere tener la verificación en dos pasos activada. Gmail rechaza la
contraseña normal de la cuenta desde 2022.

Se lee SÓLO del entorno, y es a propósito. `plania/config.py` también declara
claves `SMTP_*`, pero son otra cosa: las edita el CLIENTE desde la pestaña
Configuración y describen su correo corporativo ("ventas@tuempresa.com").
Caer a esa configuración mezclaría dos casillas de dos dueños distintos — en
una máquina donde corran la app y el backend juntos, los avisos de venta de
Plania saldrían por el servidor de correo del distribuidor.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

logger = logging.getLogger("plania.avisos")

# Cuánto tiempo se considera "el mismo aviso". Alguien indeciso que toca
# comprar cinco veces en un rato es UNA intención de compra, no cinco: sin
# esto, el mail deja de leerse a la semana.
VENTANA_REPETIDO = timedelta(minutes=30)

# Techo de seguridad. El antirrebote agrupa por clave, así que no frena a quien
# varía el dato: `POST /checkout` acepta 10 por minuto y por IP, y cada uno con
# un email distinto es una clave distinta. Sin este tope, un script desde tres
# IPs quema las 500 entregas diarias de una app password de Gmail en veinte
# minutos y deja la cuenta throttleada — y entonces el aviso que se pierde es
# el de la venta de verdad que entre después.
LIMITE_POR_HORA = 60

# Idempotencia en memoria y no en la base a propósito. Un reinicio del
# servicio manda un aviso repetido como mucho —molesto y nada más—, mientras
# que meterlo en la base agrega una tabla y una escritura en el camino del
# checkout, que es el momento donde menos conviene sumar cosas que puedan
# fallar. El plan gratuito corre una sola instancia, así que el diccionario
# alcanza.
#
# El candado no es decorativo: desde que el envío sale en un hilo, estas dos
# estructuras las tocan varios a la vez.
_ultimos: dict[str, datetime] = {}
_enviados: list[datetime] = []
_candado = threading.Lock()


def _configurado() -> dict | None:
    """Las credenciales SMTP, o None si falta alguna imprescindible."""
    datos = {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "puerto": os.environ.get("SMTP_PORT", "587").strip() or "587",
        "usuario": os.environ.get("SMTP_USER", "").strip(),
        "clave": os.environ.get("SMTP_PASSWORD", "").strip(),
    }
    if not all((datos["host"], datos["usuario"], datos["clave"])):
        return None
    datos["desde"] = os.environ.get("SMTP_FROM", "").strip() or datos["usuario"]
    datos["hasta"] = (os.environ.get("PLANIA_AVISOS_A", "").strip()
                      or datos["usuario"])
    return datos


def _una_linea(texto: str, maximo: int = 200) -> str:
    """Deja un dato en condiciones de ir en el asunto.

    Los datos del formulario llegan tal como los pegó el visitante, y pegar
    desde un PDF o una firma de mail trae saltos de línea en el medio. El
    módulo `email` los rechaza con `ValueError`, así que una empresa escrita
    como "Distribuidora ACME\\nS.R.L." dejaba el pedido guardado y el aviso sin
    salir, en silencio. `split()` sin argumentos colapsa cualquier espacio en
    blanco, saltos incluidos.

    De paso cierra la inyección de cabeceras: sin esto, un "empresa" con un
    `\\nBcc:` adentro sería una forma de mandar mail desde la casilla del
    dueño. Hoy no prospera porque `email` corta antes, pero eso es que el
    accidente tape al ataque, no una defensa.
    """
    return " ".join(str(texto or "").split())[:maximo]


def _hay_cupo(ahora: datetime) -> bool:
    """¿Queda margen en el tope por hora? Limpia de paso lo que ya venció."""
    corte = ahora - timedelta(hours=1)
    _enviados[:] = [c for c in _enviados if c > corte]
    if len(_enviados) >= LIMITE_POR_HORA:
        return False
    _enviados.append(ahora)
    return True


def _tomar_turno(clave: str | None) -> bool:
    """Reserva el derecho a mandar este aviso, o dice que no corresponde.

    Marca la clave ANTES de intentar el envío para que dos clics simultáneos
    no larguen dos hilos; si el envío después falla, `_liberar` la borra y el
    próximo intento vuelve a pasar. Marcarla y darla por buena sin haber
    enviado nada era peor de lo que parece: un SMTP caído veinte segundos se
    comía el aviso de una venta para siempre, porque la guarda `nuevo` de
    `_emitir_por_pago` es de una sola vez y el reintento del webhook ya no
    vuelve a avisar.
    """
    ahora = datetime.now(timezone.utc)
    with _candado:
        for k, cuando in list(_ultimos.items()):
            if ahora - cuando > VENTANA_REPETIDO:
                _ultimos.pop(k, None)
        if clave and clave in _ultimos:
            logger.info("Aviso repetido, no se manda: %s", clave)
            return False
        if not _hay_cupo(ahora):
            logger.warning(
                "Tope de %s avisos por hora alcanzado: este no se manda. "
                "Suele ser tráfico automatizado contra /checkout.",
                LIMITE_POR_HORA)
            return False
        if clave:
            _ultimos[clave] = ahora
    return True


def _liberar(clave: str | None) -> None:
    """Deshace la reserva: el envío falló y hay que poder reintentarlo."""
    if not clave:
        return
    with _candado:
        _ultimos.pop(clave, None)


def _enviar(asunto: str, cuerpo: str, clave: str | None) -> bool:
    """El envío en sí. Corre en un hilo aparte y nunca lanza."""
    try:
        cfg = _configurado()
        if cfg is None:
            # No es un error: es una instalación sin correo configurado. Se
            # deja constancia SIN los datos del interesado — este log va al
            # panel web de Render, que tiene otra retención y otros accesos
            # que la base. Nombre, empresa, país y email ya quedaron
            # guardados donde corresponde.
            logger.info("Sin SMTP configurado: hay un aviso sin enviar. "
                        "El detalle está en el panel del dueño.")
            _liberar(clave)
            return False

        mensaje = EmailMessage()
        mensaje["Subject"] = _una_linea(asunto)
        mensaje["From"] = _una_linea(cfg["desde"], 320)
        mensaje["To"] = _una_linea(cfg["hasta"], 320)
        mensaje.set_content(cuerpo)

        # Con contexto explícito: `starttls()` sin él usa
        # `ssl._create_stdlib_context()`, que cifra pero NO valida el
        # certificado (`check_hostname=False`, `verify_mode=CERT_NONE`).
        # Cualquiera en el camino de red puede responder el STARTTLS con un
        # certificado propio, y la línea siguiente es un `login` que le
        # entrega la clave de aplicación de Gmail.
        contexto = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["puerto"]), timeout=10) as s:
            s.starttls(context=contexto)
            s.login(cfg["usuario"], cfg["clave"])
            s.send_message(mensaje)
        logger.info("Aviso enviado: %s", _una_linea(asunto))
        return True
    except Exception:
        # El comprador no puede quedarse sin comprar porque el mail del dueño
        # falló. Se registra con traza para poder arreglarlo, y se sigue.
        logger.exception("No se pudo enviar el aviso")
        _liberar(clave)
        return False


def avisar(asunto: str, cuerpo: str, clave_repetido: str | None = None,
           bloqueante: bool = False) -> bool:
    """Manda un aviso. Nunca lanza.

    Por defecto larga el envío en un hilo y vuelve enseguida: lo que llama a
    esto le tiene que contestar a un comprador o a MercadoPago, no esperar a
    un servidor de correo. Devuelve si el aviso quedó encaminado, que no es lo
    mismo que entregado — con `bloqueante=True` espera y devuelve si se envió
    de verdad.

    `clave_repetido` agrupa avisos que son el mismo hecho: dos clics en
    comprar del mismo email y plan dentro de la ventana cuentan como uno.
    """
    try:
        if not _tomar_turno(clave_repetido):
            return False
        if bloqueante:
            return _enviar(asunto, cuerpo, clave_repetido)
        threading.Thread(target=_enviar, args=(asunto, cuerpo, clave_repetido),
                         name="plania-aviso", daemon=True).start()
        return True
    except Exception:
        # Cinturón: ni un fallo al crear el hilo puede tumbar un checkout.
        logger.exception("No se pudo encaminar el aviso")
        return False


def _cuando() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def aviso_intencion_de_compra(email: str, plan: str, precio: float,
                              moneda: str = "USD", bloqueante: bool = False) -> bool:
    """Alguien llegó hasta el link de pago. Todavía no pagó."""
    email = _una_linea(email, 320)
    plan = _una_linea(plan, 40)
    return avisar(
        asunto=f"Plania · intención de compra: {plan} ({moneda} {precio:,.0f})",
        cuerpo=(f"{email} llegó al pago del plan {plan}.\n\n"
                f"Plan:   {plan}\n"
                f"Monto:  {moneda} {precio:,.2f}\n"
                f"Cuándo: {_cuando()}\n\n"
                f"OJO: esto es intención, no cobro. Si completa el pago te "
                f"llega el aviso de venta aparte y la licencia se emite sola.\n"
                f"Si no llega ese segundo mail en un rato, abandonó el "
                f"checkout — vale un mensaje preguntándole si le pasó algo."),
        clave_repetido=f"checkout:{email}:{plan}", bloqueante=bloqueante)


def aviso_venta(email: str, plan: str, payment_id: str = "",
                bloqueante: bool = False) -> bool:
    """Se cobró de verdad y la licencia ya salió.

    La clave lleva el `payment_id` y no sólo el email: un distribuidor que
    compra una licencia por sucursal hace dos compras reales del mismo plan
    con el mismo email de facturación, y agrupadas por email la segunda no
    avisaba. Esconder una venta es bastante peor que mandar un mail de más.
    """
    email = _una_linea(email, 320)
    plan = _una_linea(plan, 40)
    return avisar(
        asunto=f"Plania · VENTA confirmada: {plan}",
        cuerpo=(f"{email} pagó el plan {plan}.\n\n"
                f"Cuándo: {_cuando()}\n"
                + (f"Pago:   {payment_id}\n" if payment_id else "")
                + "\nLa licencia se emitió sola y ya la puede activar."),
        clave_repetido=f"venta:{email}:{plan}:{payment_id}",
        bloqueante=bloqueante)


def aviso_pedido_de_demo(email: str, nombre: str, empresa: str, pais: str,
                         mensaje: str = "", bloqueante: bool = False) -> bool:
    """Alguien pidió ver el producto."""
    email = _una_linea(email, 320)
    return avisar(
        asunto=(f"Plania · pedido de demo: {_una_linea(empresa, 80)} "
                f"({_una_linea(pais, 40)})"),
        cuerpo=(f"{nombre}\n{empresa} — {pais}\n{email}\n\n"
                + (f"Dijo: {mensaje}\n\n" if mensaje else "")
                + "La demo no se entrega sola: cuando lo atiendas, habilitala "
                  "desde el panel del dueño."),
        clave_repetido=f"demo:{email}", bloqueante=bloqueante)
