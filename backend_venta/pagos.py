# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Registro de pagos ya procesados (idempotencia y rescate)
==================================================================
Guarda, por `payment_id` de MercadoPago, la licencia y el token de descarga
que se emitieron para ese pago. Resuelve dos problemas distintos con la misma
tabla:

**1. Que un pago no emita más de una licencia.**
El webhook de MercadoPago es público y reintentable: MP reenvía la
notificación cuando no recibe 200, así que recibir el mismo `payment_id`
varias veces es normal y esperable. Sin registro, cada reenvío emitía una
licencia nueva y válida. Y como MercadoPago le devuelve el `payment_id` al
comprador en la URL de retorno, el propio comprador podía repetir el webhook
a mano y fabricarse licencias `pro` ilimitadas con un `curl`.

**2. Que el comprador reciba lo que pagó.**
Antes la licencia se devolvía en el cuerpo de la respuesta del webhook — que
lo lee MercadoPago, no el comprador, y lo descarta. El cliente pagaba y no
recibía nada. Guardándola acá, la página de gracias puede pedirla con el
`payment_id` que MercadoPago ya le puso en la URL.

Vive en la misma base que `uso.py` y `descargas.py` (por defecto SQLite;
si `PLANIA_USO_DB` es una URL de Postgres, esa), en tabla aparte, para
sobrevivir a un reinicio del proceso.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from backend_venta.db import insertar_ignorando_duplicados, obtener_engine
from backend_venta.uso import DB_PATH

metadata = sa.MetaData()

pagos_tabla = sa.Table(
    "pagos_procesados", metadata,
    sa.Column("payment_id", sa.String, primary_key=True),
    sa.Column("cliente_id", sa.String, nullable=False),
    sa.Column("plan", sa.String, nullable=False),
    sa.Column("licencia", sa.String, nullable=False),
    sa.Column("token_descarga", sa.String, nullable=False),
    sa.Column("creado", sa.String, nullable=False),
)


def _engine(db_path: str = DB_PATH) -> sa.engine.Engine:
    engine = obtener_engine(db_path)
    metadata.create_all(engine, checkfirst=True)
    return engine


def buscar(payment_id: str, db_path: str = DB_PATH) -> dict | None:
    """Lo emitido para ese pago, o None si todavía no se procesó."""
    engine = _engine(db_path)
    with engine.connect() as conn:
        fila = conn.execute(
            sa.select(pagos_tabla.c.cliente_id, pagos_tabla.c.plan, pagos_tabla.c.licencia,
                      pagos_tabla.c.token_descarga, pagos_tabla.c.creado)
            .where(pagos_tabla.c.payment_id == str(payment_id))
        ).first()
    if not fila:
        return None
    return {"cliente_id": fila[0], "plan": fila[1], "licencia": fila[2],
            "token_descarga": fila[3], "creado": fila[4]}


def registrar(payment_id: str, cliente_id: str, plan: str, licencia: str,
              token_descarga: str, db_path: str = DB_PATH) -> dict:
    """Guarda lo emitido para un pago y lo devuelve.

    Si el pago ya estaba registrado no se pisa nada y se devuelve lo que había:
    dos notificaciones simultáneas del mismo pago tienen que terminar con el
    comprador teniendo UNA licencia, no dos. La condición de carrera la
    resuelve la clave primaria (vía `ON CONFLICT DO NOTHING`), no un chequeo
    previo — entre un `SELECT` y un `INSERT` entra la otra notificación.

    En el resultado agrega `nuevo`: si esta llamada fue la que registró el
    pago. Lo que cuelga de esa respuesta —el asiento en la auditoría, el aviso
    al dueño— tiene que pasar una vez por venta y no una por reintento.
    """
    engine = _engine(db_path)
    inserto = insertar_ignorando_duplicados(
        engine, pagos_tabla,
        payment_id=str(payment_id), cliente_id=cliente_id, plan=plan,
        licencia=licencia, token_descarga=token_descarga,
        creado=datetime.now(timezone.utc).isoformat())
    # Se relee en vez de devolver lo recién armado: si otra notificación ganó
    # la carrera, lo válido es lo suyo, no lo nuestro.
    return dict(buscar(payment_id, db_path), nuevo=inserto)


def total(db_path: str = DB_PATH) -> int:
    engine = _engine(db_path)
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(pagos_tabla)).scalar_one()
