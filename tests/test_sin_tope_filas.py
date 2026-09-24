"""Carga de datos sin tope de filas por defecto.

Pedido del dueño: «¿Hay límite de filas? ... debe ser sin límite de tamaño
cada módulo». El default es leer la tabla entera; `PLANIA_LIMITE_FILAS>0`
pone un tope explícito, y si recorta se avisa con el total real — nunca un
recorte mudo.
"""
import sqlite3

import pytest

FILAS = 600_000


@pytest.fixture(scope="module")
def erp_600k(tmp_path_factory):
    """ERP sintético: 600.000 ventas (más que el viejo tope de 500.000)."""
    ruta = tmp_path_factory.mktemp("erp") / "erp.db"
    cx = sqlite3.connect(ruta)
    cx.execute("CREATE TABLE productos (sku TEXT, nombre TEXT, precio REAL, costo REAL)")
    cx.executemany("INSERT INTO productos VALUES (?,?,?,?)",
                   [(f"SKU{i}", f"Producto {i}", 100.0 + i, 60.0 + i) for i in range(50)])
    cx.execute("CREATE TABLE clientes (cliente_id TEXT, nombre TEXT)")
    cx.executemany("INSERT INTO clientes VALUES (?,?)",
                   [(f"C{i}", f"Cliente {i}") for i in range(20)])
    cx.execute("CREATE TABLE ventas (fecha TEXT, sku TEXT, cantidad INT, cliente_id TEXT)")
    cx.executemany(
        "INSERT INTO ventas VALUES (?,?,?,?)",
        ((f"2026-01-{(i % 28) + 1:02d}", f"SKU{i % 50}", 1 + i % 7, f"C{i % 20}")
         for i in range(FILAS)))
    cx.commit()
    cx.close()
    return f"sqlite:///{ruta}"


def test_limite_filas_por_defecto_es_ninguno(monkeypatch):
    from plania import conectores
    monkeypatch.delenv("PLANIA_LIMITE_FILAS", raising=False)
    assert conectores.limite_filas() is None
    for vacio in ("", "0", "-5", "abc"):
        monkeypatch.setenv("PLANIA_LIMITE_FILAS", vacio)
        assert conectores.limite_filas() is None
    monkeypatch.setenv("PLANIA_LIMITE_FILAS", "1000")
    assert conectores.limite_filas() == 1000


def test_sin_tope_lee_las_600000_filas_enteras(erp_600k, monkeypatch):
    from plania import conectores
    monkeypatch.delenv("PLANIA_LIMITE_FILAS", raising=False)
    datos = conectores.cargar_datos(erp_600k)
    assert len(datos["ventas"]) == FILAS
    assert not datos["ventas"].attrs["recortada"]
    assert conectores.avisos_de_recorte(datos) == []


def test_con_tope_explicito_recorta_y_avisa_con_el_total_real(erp_600k, monkeypatch):
    from plania import conectores
    monkeypatch.setenv("PLANIA_LIMITE_FILAS", "1000")
    datos = conectores.cargar_datos(erp_600k)
    assert len(datos["ventas"]) == 1000
    assert datos["ventas"].attrs["recortada"]
    assert datos["ventas"].attrs["total_filas"] == FILAS
    avisos = conectores.avisos_de_recorte(datos)
    assert len(avisos) == 1 and avisos[0].startswith("ventas:")
    assert "1,000" in avisos[0] and f"{FILAS:,}" in avisos[0]
    # Las tablas chicas no se recortan ni avisan.
    assert not datos["productos"].attrs["recortada"]


def test_el_tope_de_subida_de_streamlit_es_200000_mb():
    from pathlib import Path
    cfg = (Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text()
    assert "maxUploadSize = 200000" in cfg
