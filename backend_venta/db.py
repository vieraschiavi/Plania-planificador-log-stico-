# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Motor de conexión compartido para el estado del backend de venta
============================================================================
`pagos.py`, `uso.py` y `descargas.py` necesitan que su estado sobreviva a un
reinicio del proceso: qué pagos de MercadoPago ya emitieron licencia (para
que un reintento del webhook no duplique), qué emails ya usaron la demo
gratis, y los tokens de descarga vivos.

El plan gratuito de Render (y de la mayoría de los PaaS) no ofrece disco
persistente: el sistema de archivos del contenedor se borra en cada reinicio
o cada vez que el servicio se duerme por falta de tráfico. Guardar ese
estado en un archivo SQLite ahí significa perderlo todo, todo el tiempo.

Este módulo resuelve eso sin exigir un plan pago: `db_path` (que hoy viene
de `PLANIA_USO_DB`) puede seguir siendo la ruta de un archivo local — el
comportamiento de siempre, el que usan los tests — o puede ser una URL de
conexión (`postgresql://…`) a una base gratuita externa (Neon, Supabase,
etc.), cuyo disco no depende del contenedor que corre el backend.
"""
from __future__ import annotations

import os

import sqlalchemy as sa

_engines: dict[str, sa.engine.Engine] = {}


def url_de(db_path: str) -> str:
    """`db_path` tal cual si ya es una URL de conexión, o un SQLite local si no."""
    return db_path if "://" in db_path else f"sqlite:///{db_path}"


def obtener_engine(db_path: str) -> sa.engine.Engine:
    """Engine cacheado para `db_path` (una ruta de archivo o una URL)."""
    engine = _engines.get(db_path)
    if engine is not None:
        return engine
    url = url_de(db_path)
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        ruta = url[len("sqlite:///"):]
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    _engines[db_path] = engine = sa.create_engine(url, future=True)
    return engine


def insertar_ignorando_duplicados(engine: sa.engine.Engine, tabla: sa.Table, **valores) -> None:
    """`INSERT ... ON CONFLICT DO NOTHING`, portable entre SQLite y Postgres.

    Reemplaza al `INSERT OR IGNORE` de SQLite (no existe en Postgres) sin
    recurrir a try/except IntegrityError: un INSERT fallido dentro de una
    transacción de Postgres la deja abortada para cualquier sentencia
    posterior, así que atrapar la excepción ahí es una trampa. Con
    `on_conflict_do_nothing()` nunca llega a fallar.
    """
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert
    stmt = _insert(tabla).values(**valores).on_conflict_do_nothing()
    with engine.begin() as conn:
        conn.execute(stmt)
