"""
Plania · Medición de uso por licencia (Edición Venta)
======================================================
Cada llamada al gateway del Copiloto queda registrada acá — es la base para
saber si un cliente superó su cupo mensual y para facturar el excedente.
También registra qué emails ya consumieron la demo de 7 días (una por email).

Por defecto vive en un archivo SQLite (alcanza para un solo servidor). Si
`PLANIA_USO_DB` es una URL de conexión (por ejemplo una Postgres gratuita de
Neon o Supabase) usa esa base en su lugar — ver `backend_venta/db.py`.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from datetime import datetime, timezone

import portalocker
import sqlalchemy as sa

from backend_venta.db import insertar_ignorando_duplicados, obtener_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("PLANIA_USO_DB", os.path.join(ROOT, "data", "uso_licencias.db"))

_LOCK_DIR = os.environ.get("PLANIA_LOCK_DIR", tempfile.gettempdir())

metadata = sa.MetaData()

uso_tabla = sa.Table(
    "uso", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("cliente_id", sa.String, nullable=False),
    sa.Column("fecha", sa.String, nullable=False),
    sa.Column("canal", sa.String, nullable=False),
    sa.Column("ref_id", sa.String),
    sa.Column("tok_in", sa.Integer, default=0),
    sa.Column("tok_out", sa.Integer, default=0),
    sa.Column("unidades", sa.Float, default=0),
    sa.Column("costo_est", sa.Float, default=0),
)

trials_tabla = sa.Table(
    "trials", metadata,
    sa.Column("email", sa.String, primary_key=True),
    sa.Column("fecha", sa.String, nullable=False),
)


def _engine(db_path: str = DB_PATH) -> sa.engine.Engine:
    engine = obtener_engine(db_path)
    metadata.create_all(engine, checkfirst=True)
    return engine


def registrar_uso(cliente_id: str, canal: str, ref_id: str | None = None,
                  tok_in: int = 0, tok_out: int = 0, unidades: float = 0,
                  costo_est: float = 0.0, db_path: str = DB_PATH) -> None:
    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(uso_tabla.insert().values(
            cliente_id=cliente_id, fecha=datetime.now(timezone.utc).isoformat(),
            canal=canal, ref_id=ref_id, tok_in=tok_in, tok_out=tok_out,
            unidades=unidades, costo_est=costo_est))


def uso_mes(cliente_id: str, mes: str | None = None, db_path: str = DB_PATH) -> dict:
    """Resumen de uso del cliente en el mes (`YYYY-MM`, default el actual)."""
    mes = mes or datetime.now(timezone.utc).strftime("%Y-%m")
    engine = _engine(db_path)
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(uso_tabla.c.tok_in), 0),
                sa.func.coalesce(sa.func.sum(uso_tabla.c.tok_out), 0),
                sa.func.coalesce(sa.func.sum(uso_tabla.c.unidades), 0),
                sa.func.coalesce(sa.func.sum(uso_tabla.c.costo_est), 0),
            ).where(uso_tabla.c.cliente_id == cliente_id, uso_tabla.c.fecha.like(mes + "%"))
        ).one()
    return {"mes": mes, "consultas": row[0], "tok_in": row[1], "tok_out": row[2],
            "unidades": row[3], "costo_est": row[4]}


def consultas_mes(cliente_id: str, mes: str | None = None, db_path: str = DB_PATH) -> int:
    """Cuántas 'consultas' (unidad de cupo: consultas del copiloto y exportes) consumió el cliente este mes."""
    return uso_mes(cliente_id, mes, db_path)["consultas"]


def ya_uso_trial(email: str, db_path: str = DB_PATH) -> bool:
    engine = _engine(db_path)
    with engine.connect() as conn:
        fila = conn.execute(
            sa.select(trials_tabla.c.email).where(trials_tabla.c.email == email.lower())
        ).first()
    return fila is not None


def marcar_trial(email: str, db_path: str = DB_PATH) -> None:
    engine = _engine(db_path)
    insertar_ignorando_duplicados(
        engine, trials_tabla,
        email=email.lower(), fecha=datetime.now(timezone.utc).isoformat())


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

    El lock es un archivo local (coordina pedidos dentro del mismo proceso,
    que es lo único que hace falta con una sola instancia del backend) — no
    depende de que `db_path` sea una ruta de archivo, así que sigue
    funcionando igual con una base Postgres externa.
    """
    os.makedirs(_LOCK_DIR, exist_ok=True)
    clave = hashlib.sha256(f"{db_path}|{cliente_id}".encode("utf-8")).hexdigest()[:16]
    ruta_lock = os.path.join(_LOCK_DIR, f"plania-cliente-{clave}.lock")
    with portalocker.Lock(ruta_lock, timeout=timeout):
        yield
