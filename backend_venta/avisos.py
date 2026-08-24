# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Avisos al dueño por correo
====================================
Un mail cuando pasa algo que merece que sueltes lo que estás haciendo: alguien
pidió una demo, alguien hizo clic en comprar. El resto del estado del negocio
vive en el panel del dueño y no necesita interrumpirte.

Usa `smtplib` de la biblioteca estándar contra las claves `SMTP_*` que
`plania/config.py` ya declaraba y nadie usaba todavía. Sin dependencias
nuevas: un servidor de venta que sólo manda un puñado de mails por día no
justifica sumar un SDK ni una cuenta más.

**Nunca rompe el pedido que lo disparó.** Si el SMTP está mal configurado,
caído o lento, el cliente igual tiene que poder comprar: el aviso es para vos,
no para él. Todo error se registra y se traga.

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
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from plania import config as pconfig

logger = logging.getLogger("plania.avisos")

# Cuánto tiempo se considera "el mismo aviso". Alguien indeciso que toca
# comprar cinco veces en un rato es UNA intención de compra, no cinco: sin
# esto, el mail deja de leerse a la semana.
VENTANA_REPETIDO = timedelta(minutes=30)

# Idempotencia en memoria y no en la base a propósito. Un reinicio del
# servicio manda un aviso repetido como mucho —molesto y nada más—, mientras
# que meterlo en la base agrega una tabla y una escritura en el camino del
# checkout, que es el momento donde menos conviene sumar cosas que puedan
# fallar. El plan gratuito corre una sola instancia, así que el diccionario
# alcanza.
_ultimos: dict[str, datetime] = {}


def _clave(nombre: str, default: str = "") -> str:
    """Entorno primero, configuración guardada después.

    Es el mismo orden que usa el resto del backend para `MP_ACCESS_TOKEN`: en
    Render los valores viven en el entorno, pero si alguien corre el servidor
    de venta en su propia máquina las credenciales están en el keyring del
    sistema y leer sólo `os.environ` dejaba el correo mudo sin decir por qué.
    """
    valor = os.environ.get(nombre, "")
    if not valor.strip():
        valor = pconfig.leer_extra(nombre, "") or ""
    return valor.strip() or default


def _configurado() -> dict | None:
    """Las credenciales SMTP, o None si falta alguna imprescindible."""
    datos = {
        "host": _clave("SMTP_HOST"),
        "puerto": _clave("SMTP_PORT", "587"),
        "usuario": _clave("SMTP_USER"),
        "clave": _clave("SMTP_PASSWORD"),
    }
    if not all((datos["host"], datos["usuario"], datos["clave"])):
        return None
    datos["desde"] = _clave("SMTP_FROM") or datos["usuario"]
    datos["hasta"] = _clave("PLANIA_AVISOS_A") or datos["usuario"]
    return datos


def _repetido(clave: str) -> bool:
    """¿Ya se avisó esto hace poco? Limpia de paso lo que ya venció."""
    ahora = datetime.now(timezone.utc)
    for k, cuando in list(_ultimos.items()):
        if ahora - cuando > VENTANA_REPETIDO:
            del _ultimos[k]
    if clave in _ultimos:
        return True
    _ultimos[clave] = ahora
    return False


def avisar(asunto: str, cuerpo: str, clave_repetido: str | None = None) -> bool:
    """Manda un aviso. Devuelve si se envió, y nunca lanza.

    `clave_repetido` agrupa avisos que son el mismo hecho: dos clics en
    comprar del mismo email y plan dentro de la ventana cuentan como uno.
    """
    if clave_repetido and _repetido(clave_repetido):
        logger.info("Aviso repetido, no se manda: %s", clave_repetido)
        return False

    try:
        cfg = _configurado()
        if cfg is None:
            # No es un error: es una instalación sin correo configurado. Se
            # deja el hecho en el log para que igual quede registrado en
            # Render.
            logger.info("Sin SMTP configurado. Aviso no enviado: %s | %s",
                        asunto, cuerpo.replace("\n", " ")[:200])
            return False

        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = cfg["desde"]
        mensaje["To"] = cfg["hasta"]
        mensaje.set_content(cuerpo)

        with smtplib.SMTP(cfg["host"], int(cfg["puerto"]), timeout=10) as s:
            s.starttls()
            s.login(cfg["usuario"], cfg["clave"])
            s.send_message(mensaje)
        logger.info("Aviso enviado: %s", asunto)
        return True
    except Exception:
        # El comprador no puede quedarse sin comprar porque el mail del dueño
        # falló. Se registra con traza para poder arreglarlo, y se sigue.
        logger.exception("No se pudo enviar el aviso: %s", asunto)
        return False


def aviso_intencion_de_compra(email: str, plan: str, precio: float,
                              moneda: str = "USD") -> bool:
    """Alguien llegó hasta el link de pago. Todavía no pagó."""
    cuando = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    return avisar(
        asunto=f"Plania · intención de compra: {plan} ({moneda} {precio:,.0f})",
        cuerpo=(f"{email} llegó al pago del plan {plan}.\n\n"
                f"Plan:   {plan}\n"
                f"Monto:  {moneda} {precio:,.2f}\n"
                f"Cuándo: {cuando}\n\n"
                f"OJO: esto es intención, no cobro. Si completa el pago te "
                f"llega el aviso de venta aparte y la licencia se emite sola.\n"
                f"Si no llega ese segundo mail en un rato, abandonó el "
                f"checkout — vale un mensaje preguntándole si le pasó algo."),
        clave_repetido=f"checkout:{email}:{plan}")


def aviso_venta(email: str, plan: str) -> bool:
    """Se cobró de verdad y la licencia ya salió."""
    cuando = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    return avisar(
        asunto=f"Plania · VENTA confirmada: {plan}",
        cuerpo=(f"{email} pagó el plan {plan}.\n\n"
                f"Cuándo: {cuando}\n\n"
                f"La licencia se emitió sola y ya la puede activar."),
        clave_repetido=f"venta:{email}:{plan}")


def aviso_pedido_de_demo(email: str, nombre: str, empresa: str, pais: str,
                         mensaje: str = "") -> bool:
    """Alguien pidió ver el producto."""
    return avisar(
        asunto=f"Plania · pedido de demo: {empresa} ({pais})",
        cuerpo=(f"{nombre}\n{empresa} — {pais}\n{email}\n\n"
                + (f"Dijo: {mensaje}\n\n" if mensaje else "")
                + "La demo no se entrega sola: cuando lo atiendas, habilitala "
                  "desde el panel del dueño."),
        clave_repetido=f"demo:{email}")
