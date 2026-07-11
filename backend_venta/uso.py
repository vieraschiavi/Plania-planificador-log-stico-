"""
Plania · Medición de uso por licencia (Edición Venta)
======================================================
Cada llamada al gateway del Copiloto queda registrada acá — es la base para
saber si un cliente superó su cupo mensual y para facturar el excedente.
También registra qué emails ya consumieron la demo de 3 días (una por email).

SQLite por simplicidad: alcanza para este servicio corriendo en un solo
servidor; migrar a Postgres es cambiar la URL de conexión si hace falta
escalar.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

import portalocker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("PLANIA_USO_DB", os.path.join(ROOT, "data", "uso_licencias.db"))

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS uso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id TEXT NOT NULL,
    fecha TEXT NOT NULL,
    canal TEXT NOT NULL,
    ref_id TEXT,
    tok_in INTEGER DEFAULT 0,
    tok_out INTEGER DEFAULT 0,
    unidades REAL DEFAULT 0,
    costo_est REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trials (
    email TEXT PRIMARY KEY,
    fecha TEXT NOT NULL
);
"""


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_ESQUEMA)
    return conn


def registrar_uso(cliente_id: str, canal: str, ref_id: str | None = None,
                  tok_in: int = 0, tok_out: int = 0, unidades: float = 0,
                  costo_est: float = 0.0, db_path: str = DB_PATH) -> None:
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO uso (cliente_id, fecha, canal, ref_id, tok_in, tok_out, unidades, costo_est) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cliente_id, datetime.now(timezone.utc).isoformat(), canal, ref_id,
             tok_in, tok_out, unidades, costo_est),
        )
        conn.commit()
    finally:
        conn.close()


def uso_mes(cliente_id: str, mes: str | None = None, db_path: str = DB_PATH) -> dict:
    """Resumen de uso del cliente en el mes (`YYYY-MM`, default el actual)."""
    mes = mes or datetime.now(timezone.utc).strftime("%Y-%m")
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(tok_in),0), COALESCE(SUM(tok_out),0), "
            "COALESCE(SUM(unidades),0), COALESCE(SUM(costo_est),0) "
            "FROM uso WHERE cliente_id=? AND fecha LIKE ?",
            (cliente_id, mes + "%"),
        ).fetchone()
    finally:
        conn.close()
    return {"mes": mes, "consultas": row[0], "tok_in": row[1], "tok_out": row[2],
            "unidades": row[3], "costo_est": row[4]}


def consultas_mes(cliente_id: str, mes: str | None = None, db_path: str = DB_PATH) -> int:
    """Cuántas 'consultas' (unidad de cupo: consultas del copiloto y exportes) consumió el cliente este mes."""
    return uso_mes(cliente_id, mes, db_path)["consultas"]


def ya_uso_trial(email: str, db_path: str = DB_PATH) -> bool:
    conn = _conn(db_path)
    try:
        return conn.execute("SELECT 1 FROM trials WHERE email=?",
                            (email.lower(),)).fetchone() is not None
    finally:
        conn.close()


def marcar_trial(email: str, db_path: str = DB_PATH) -> None:
    conn = _conn(db_path)
    try:
        conn.execute("INSERT OR IGNORE INTO trials (email, fecha) VALUES (?,?)",
                     (email.lower(), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def lock_cliente(cliente_id: str, db_path: str = DB_PATH, timeout: int = 10):
    """
    Lock exclusivo por cliente (no por servicio entero, para no serializar
    a clientes distintos entre sí). Usar para que "leer cuánto usó este mes"
    + "llamar al proveedor" + "registrar el uso" sea una sola operación
    atómica — sin esto, dos pedidos concurrentes del mismo cliente pueden
    leer el mismo cupo-restante antes de que ninguno registre uso, y ambos
    pasan aunque en conjunto superen el cupo (comprobado con un test de
    concurrencia real: sin lock, un cupo de 10 dejaba pasar 22 de 30
    pedidos simultáneos).
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    clave = hashlib.sha256(cliente_id.encode("utf-8")).hexdigest()[:16]
    ruta_lock = db_path + f".cliente-{clave}.lock"
    with portalocker.Lock(ruta_lock, timeout=timeout):
        yield
