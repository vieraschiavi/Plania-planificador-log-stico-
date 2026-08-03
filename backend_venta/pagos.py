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

Vive en la misma base SQLite que `uso.py` y `descargas.py`, en tabla aparte,
para sobrevivir a un reinicio del proceso.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from backend_venta.uso import DB_PATH

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS pagos_procesados (
    payment_id TEXT PRIMARY KEY,
    cliente_id TEXT NOT NULL,
    plan TEXT NOT NULL,
    licencia TEXT NOT NULL,
    token_descarga TEXT NOT NULL,
    creado TEXT NOT NULL
)
"""


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_ESQUEMA)
    return conn


def buscar(payment_id: str, db_path: str = DB_PATH) -> dict | None:
    """Lo emitido para ese pago, o None si todavía no se procesó."""
    conn = _conn(db_path)
    try:
        fila = conn.execute(
            "SELECT cliente_id, plan, licencia, token_descarga, creado "
            "FROM pagos_procesados WHERE payment_id = ?", (str(payment_id),)
        ).fetchone()
    finally:
        conn.close()
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
    resuelve la clave primaria, no un chequeo previo — entre un `SELECT` y un
    `INSERT` entra la otra notificación.
    """
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO pagos_procesados "
            "(payment_id, cliente_id, plan, licencia, token_descarga, creado) "
            "VALUES (?,?,?,?,?,?)",
            (str(payment_id), cliente_id, plan, licencia, token_descarga,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    # Se relee en vez de devolver lo recién armado: si otra notificación ganó
    # la carrera, lo válido es lo suyo, no lo nuestro.
    return buscar(payment_id, db_path)


def total(db_path: str = DB_PATH) -> int:
    conn = _conn(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM pagos_procesados").fetchone()[0]
    finally:
        conn.close()
