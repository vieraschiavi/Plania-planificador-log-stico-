"""
Plania · Tokens de descarga de un solo uso (Edición Venta)
============================================================
Implementación real de la sección 4 de `docs/BACKEND_VENTA.md`: al
confirmarse el pago se crea un token de descarga corto y de un solo uso,
que se manda por email junto con la licencia. `GET /descargar/{token}`
lo consume y sirve el instalador.

Los tokens viven en SQLite (misma base que `uso.py`, tabla separada) para
sobrevivir un reinicio del proceso sin depender de estado en memoria.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from backend_venta.uso import DB_PATH

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS tokens_descarga (
    token TEXT PRIMARY KEY,
    cliente_id TEXT NOT NULL,
    creado TEXT NOT NULL,
    expira TEXT NOT NULL,
    usado INTEGER DEFAULT 0
)
"""


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_ESQUEMA)
    return conn


def crear_token_descarga(cliente_id: str, horas_validez: int = 72,
                         db_path: str = DB_PATH) -> str:
    token = secrets.token_urlsafe(24)
    ahora = datetime.now(timezone.utc)
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO tokens_descarga (token, cliente_id, creado, expira, usado) VALUES (?,?,?,?,0)",
            (token, cliente_id, ahora.isoformat(), (ahora + timedelta(hours=horas_validez)).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def validar_token_descarga(token: str, marcar_usado: bool = True, db_path: str = DB_PATH) -> dict:
    """{"ok": bool, "cliente_id": str|None, "error": str|None}. Un solo uso."""
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT cliente_id, expira, usado FROM tokens_descarga WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return {"ok": False, "cliente_id": None, "error": "token_no_existe"}
        cliente_id, expira, usado = row
        if usado:
            return {"ok": False, "cliente_id": None, "error": "token_ya_usado"}
        if datetime.now(timezone.utc) > datetime.fromisoformat(expira):
            return {"ok": False, "cliente_id": None, "error": "token_expirado"}
        if marcar_usado:
            conn.execute("UPDATE tokens_descarga SET usado=1 WHERE token=?", (token,))
            conn.commit()
        return {"ok": True, "cliente_id": cliente_id, "error": None}
    finally:
        conn.close()
