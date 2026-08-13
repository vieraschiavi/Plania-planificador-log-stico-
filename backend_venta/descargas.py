# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Tokens de descarga de un solo uso (Edición Venta)
============================================================
Implementación real de la sección 4 de `docs/BACKEND_VENTA.md`: al
confirmarse el pago se crea un token de descarga corto y de un solo uso,
que se manda por email junto con la licencia. `GET /descargar/{token}`
lo consume y sirve el instalador.

Los tokens viven en la misma base que `uso.py` (por defecto SQLite; si
`PLANIA_USO_DB` es una URL de Postgres, esa), tabla separada, para
sobrevivir un reinicio del proceso sin depender de estado en memoria.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from backend_venta.db import obtener_engine
from backend_venta.uso import DB_PATH

metadata = sa.MetaData()

tokens_tabla = sa.Table(
    "tokens_descarga", metadata,
    sa.Column("token", sa.String, primary_key=True),
    sa.Column("cliente_id", sa.String, nullable=False),
    sa.Column("creado", sa.String, nullable=False),
    sa.Column("expira", sa.String, nullable=False),
    sa.Column("usado", sa.Integer, default=0),
)


def _engine(db_path: str = DB_PATH) -> sa.engine.Engine:
    engine = obtener_engine(db_path)
    metadata.create_all(engine, checkfirst=True)
    return engine


def crear_token_descarga(cliente_id: str, horas_validez: int = 72,
                         db_path: str = DB_PATH) -> str:
    token = secrets.token_urlsafe(24)
    ahora = datetime.now(timezone.utc)
    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(tokens_tabla.insert().values(
            token=token, cliente_id=cliente_id, creado=ahora.isoformat(),
            expira=(ahora + timedelta(hours=horas_validez)).isoformat(), usado=0))
    return token


def validar_token_descarga(token: str, marcar_usado: bool = True, db_path: str = DB_PATH) -> dict:
    """{"ok": bool, "cliente_id": str|None, "error": str|None}. Un solo uso."""
    engine = _engine(db_path)
    with engine.begin() as conn:
        fila = conn.execute(
            sa.select(tokens_tabla.c.cliente_id, tokens_tabla.c.expira, tokens_tabla.c.usado)
            .where(tokens_tabla.c.token == token)
        ).first()
        if not fila:
            return {"ok": False, "cliente_id": None, "error": "token_no_existe"}
        cliente_id, expira, usado = fila
        if usado:
            return {"ok": False, "cliente_id": None, "error": "token_ya_usado"}
        if datetime.now(timezone.utc) > datetime.fromisoformat(expira):
            return {"ok": False, "cliente_id": None, "error": "token_expirado"}
        if marcar_usado:
            conn.execute(tokens_tabla.update().where(tokens_tabla.c.token == token).values(usado=1))
    return {"ok": True, "cliente_id": cliente_id, "error": None}
