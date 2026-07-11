"""
Plania · Analítica comercial y logística
========================================
Todos los cálculos parten del esquema canónico (ver `plania/conectores.py`)
y devuelven DataFrames listos para graficar, exportar o alimentar al
copiloto. Nada de números inventados: todo sale de los datos conectados.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def enriquecer_ventas(ventas: pd.DataFrame, productos: pd.DataFrame,
                      clientes: pd.DataFrame) -> pd.DataFrame:
    """Ventas + datos de producto y cliente en una sola tabla de trabajo.
    Idempotente: si le pasan una tabla ya enriquecida, la devuelve tal cual."""
    if "venta" in ventas.columns and "margen" in ventas.columns:
        return ventas
    v = ventas.copy()
    v["fecha"] = pd.to_datetime(v["fecha"])
    if "precio_unit" not in v.columns or v["precio_unit"].isna().all():
        v = v.merge(productos[["sku", "precio"]], on="sku", how="left")
        v["precio_unit"] = v.pop("precio")
    if "costo_unit" not in v.columns or v["costo_unit"].isna().all():
        v = v.merge(productos[["sku", "costo"]], on="sku", how="left")
        v["costo_unit"] = v.pop("costo")
    v["venta"] = v["cantidad"] * v["precio_unit"].fillna(0)
    v["costo_total"] = v["cantidad"] * v["costo_unit"].fillna(0)
    v["margen"] = v["venta"] - v["costo_total"]
    v = v.merge(productos[["sku", "nombre", "categoria", "proveedor"]], on="sku", how="left")
    if len(clientes):
        v = v.merge(clientes[["cliente_id", "tipo_negocio", "departamento", "zona"]],
                    on="cliente_id", how="left")
    return v


def kpis(productos: pd.DataFrame, v: pd.DataFrame, dias: int = 30) -> dict:
    """Tarjetas del panel ejecutivo. `v` = ventas enriquecidas."""
    corte = v["fecha"].max() - pd.Timedelta(days=dias)
    vp = v[v["fecha"] > corte]
    venta = float(vp["venta"].sum())
    margen = float(vp["margen"].sum())
    valor_stock = float((productos["stock"] * productos["costo"]).sum())
    quiebres = int((productos["stock"] <= 0).sum())
    bajo_min = int((productos["stock"] < productos["stock_min"]).sum())
    rot = rotacion(productos, v)
    sobrestock = int((rot["dias_stock"] > 90).sum())
    return {
        "venta_periodo": venta,
        "margen_periodo": margen,
        "margen_pct": (margen / venta * 100) if venta else 0.0,
        "ticket_promedio": float(vp.groupby("venta_id")["venta"].sum().mean()) if len(vp) else 0.0,
        "valor_stock": valor_stock,
        "quiebres": quiebres,
        "bajo_minimo": bajo_min,
        "sobrestock": sobrestock,
        "clientes_activos": int(vp["cliente_id"].nunique()),
        "dias": dias,
    }


def rotacion(productos: pd.DataFrame, v: pd.DataFrame, ventana_dias: int = 90) -> pd.DataFrame:
    """Venta diaria promedio y días de stock por SKU (la base de reposición
    y de ofertas por sobrestock)."""
    corte = v["fecha"].max() - pd.Timedelta(days=ventana_dias)
    vp = v[v["fecha"] > corte]
    diaria = (vp.groupby("sku")["cantidad"].sum() / ventana_dias).rename("venta_diaria")
    r = productos.merge(diaria, on="sku", how="left")
    r["venta_diaria"] = r["venta_diaria"].fillna(0.0)
    r["dias_stock"] = np.where(r["venta_diaria"] > 0,
                               r["stock"] / r["venta_diaria"], np.inf)
    return r


def margen_por_producto(v: pd.DataFrame, top: int | None = None) -> pd.DataFrame:
    g = (v.groupby(["sku", "nombre", "categoria"], as_index=False)
           .agg(venta=("venta", "sum"), margen=("margen", "sum"),
                unidades=("cantidad", "sum")))
    g["margen_pct"] = np.where(g["venta"] > 0, g["margen"] / g["venta"] * 100, 0)
    g = g.sort_values("venta", ascending=False)
    return g.head(top) if top else g


def por_dimension(v: pd.DataFrame, dim: str) -> pd.DataFrame:
    """Ventas/margen agregados por zona, departamento, tipo_negocio,
    categoria o proveedor."""
    if dim not in v.columns:
        return pd.DataFrame(columns=[dim, "venta", "margen", "clientes"])
    g = (v.dropna(subset=[dim]).groupby(dim, as_index=False)
           .agg(venta=("venta", "sum"), margen=("margen", "sum"),
                unidades=("cantidad", "sum"),
                clientes=("cliente_id", "nunique")))
    g["margen_pct"] = np.where(g["venta"] > 0, g["margen"] / g["venta"] * 100, 0)
    return g.sort_values("venta", ascending=False)


def tendencia_mensual(v: pd.DataFrame) -> pd.DataFrame:
    g = (v.assign(mes=v["fecha"].dt.to_period("M").astype(str))
           .groupby("mes", as_index=False)
           .agg(venta=("venta", "sum"), margen=("margen", "sum")))
    g["margen_pct"] = np.where(g["venta"] > 0, g["margen"] / g["venta"] * 100, 0)
    return g


def top_clientes(v: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    g = (v.groupby("cliente_id", as_index=False)
           .agg(venta=("venta", "sum"), margen=("margen", "sum"),
                pedidos=("venta_id", "nunique"),
                ultima_compra=("fecha", "max")))
    return g.sort_values("venta", ascending=False).head(top)


def clientes_inactivos(v: pd.DataFrame, clientes: pd.DataFrame,
                       dias: int = 45) -> pd.DataFrame:
    """Clientes que compraban y dejaron de comprar — plata sobre la mesa."""
    if not len(clientes):
        return pd.DataFrame()
    ult = v.groupby("cliente_id")["fecha"].max().rename("ultima_compra")
    c = clientes.merge(ult, on="cliente_id", how="left")
    corte = v["fecha"].max() - pd.Timedelta(days=dias)
    inact = c[c["ultima_compra"].notna() & (c["ultima_compra"] < corte)].copy()
    inact["dias_sin_comprar"] = (v["fecha"].max() - inact["ultima_compra"]).dt.days
    return inact.sort_values("dias_sin_comprar", ascending=False)
