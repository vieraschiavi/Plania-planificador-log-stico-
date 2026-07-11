"""
Plania · Motor de sugerencias accionables
=========================================
Convierte la analítica en decisiones concretas y exportables (PDF/Word/Excel,
ver `plania/exportes.py`): qué ofertar, qué reponer, qué re-precificar, qué
cliente recuperar y dónde hay venta cruzada sin explotar. Cada sugerencia
lleva el "porqué" con los números que la justifican — es lo que el comprador
mira antes de confiar en el programa.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from plania import analitica

MARGEN_MINIMO_OFERTA = 0.08   # nunca sugerir vender por debajo de costo+8%
DIAS_SOBRESTOCK = 90
DIAS_OBJETIVO_OFERTA = 45


def ofertas_por_sobrestock(productos: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    """Productos con más de DIAS_SOBRESTOCK días de stock: sugiere un
    descuento que apure la rotación sin regalar margen (piso costo+8%)."""
    r = analitica.rotacion(productos, v)
    sob = r[(r["dias_stock"] > DIAS_SOBRESTOCK) & (r["stock"] > 0)].copy()
    if not len(sob):
        return pd.DataFrame()
    # elasticidad simple: descuento proporcional al exceso, tope 30%
    exceso = (sob["dias_stock"].clip(upper=365) - DIAS_OBJETIVO_OFERTA) / 365
    desc = (exceso * 0.35).clip(0.05, 0.30)
    precio_oferta = sob["precio"] * (1 - desc)
    piso = sob["costo"] * (1 + MARGEN_MINIMO_OFERTA)
    sob["descuento_pct"] = np.where(precio_oferta < piso,
                                    (1 - piso / sob["precio"]).clip(lower=0),
                                    desc).round(3) * 100
    sob["dias_stock"] = sob["dias_stock"].round(1)
    sob["precio_oferta"] = (sob["precio"] * (1 - sob["descuento_pct"] / 100)).round(2)
    sob["capital_inmovilizado"] = (sob["stock"] * sob["costo"]).round(2)
    sob["motivo"] = sob.apply(
        lambda x: (f"{x['dias_stock']:.0f} días de stock ({x['stock']} un., "
                   f"venta diaria {x['venta_diaria']:.1f}) — "
                   f"${x['capital_inmovilizado']:,.0f} inmovilizados"), axis=1)
    cols = ["sku", "nombre", "categoria", "stock", "dias_stock", "precio",
            "descuento_pct", "precio_oferta", "capital_inmovilizado", "motivo"]
    return (sob[cols].sort_values("capital_inmovilizado", ascending=False)
                     .reset_index(drop=True))


def reposicion(productos: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    """Qué comprar YA: días de stock < lead time + colchón. Cantidad sugerida
    para cubrir 30 días de venta."""
    r = analitica.rotacion(productos, v)
    colchon = 5
    riesgo = r[(r["venta_diaria"] > 0)
               & (r["dias_stock"] < r["lead_time_dias"] + colchon)].copy()
    if not len(riesgo):
        return pd.DataFrame()
    riesgo["cantidad_sugerida"] = np.ceil(
        riesgo["venta_diaria"] * 30 - riesgo["stock"]).clip(lower=0).astype(int)
    riesgo = riesgo[riesgo["cantidad_sugerida"] > 0]
    riesgo["dias_stock"] = riesgo["dias_stock"].round(1)
    riesgo["inversion"] = (riesgo["cantidad_sugerida"] * riesgo["costo"]).round(2)
    riesgo["venta_en_riesgo"] = (riesgo["venta_diaria"] * riesgo["precio"] * 30).round(2)
    riesgo["motivo"] = riesgo.apply(
        lambda x: (f"Quedan {x['dias_stock']:.0f} días de stock y el proveedor "
                   f"demora {x['lead_time_dias']} — riesgo de perder "
                   f"${x['venta_en_riesgo']:,.0f}/mes de venta"), axis=1)
    cols = ["sku", "nombre", "categoria", "proveedor", "stock", "dias_stock",
            "lead_time_dias", "cantidad_sugerida", "inversion", "venta_en_riesgo", "motivo"]
    return (riesgo[cols].sort_values("venta_en_riesgo", ascending=False)
                        .reset_index(drop=True))


def precios(productos: pd.DataFrame, v: pd.DataFrame,
            margen_objetivo_pct: float = 25.0) -> pd.DataFrame:
    """Productos que venden bien pero dejan margen bajo el objetivo de su
    categoría: sugiere precio nuevo con impacto estimado."""
    mp = analitica.margen_por_producto(v)
    obj_cat = (mp.groupby("categoria")["margen_pct"].median()
                 .clip(lower=margen_objetivo_pct).rename("margen_obj"))
    mp = mp.merge(obj_cat, on="categoria")
    bajo = mp[(mp["margen_pct"] < mp["margen_obj"] - 3) & (mp["venta"] > 0)].copy()
    if not len(bajo):
        return pd.DataFrame()
    bajo = bajo.merge(productos[["sku", "precio", "costo"]], on="sku")
    bajo["precio_sugerido"] = (bajo["costo"] / (1 - bajo["margen_obj"] / 100)).round(2)
    bajo["suba_pct"] = ((bajo["precio_sugerido"] / bajo["precio"] - 1) * 100).round(1)
    bajo = bajo[(bajo["suba_pct"] > 0.5) & (bajo["suba_pct"] < 25)]  # subas creíbles
    bajo["margen_extra_mensual"] = (
        (bajo["precio_sugerido"] - bajo["precio"]) * bajo["unidades"] / 12).round(2)
    bajo["motivo"] = bajo.apply(
        lambda x: (f"Margen actual {x['margen_pct']:.1f}% vs {x['margen_obj']:.1f}% "
                   f"de su categoría — subir {x['suba_pct']:.1f}% suma "
                   f"${x['margen_extra_mensual']:,.0f}/mes"), axis=1)
    cols = ["sku", "nombre", "categoria", "precio", "precio_sugerido", "suba_pct",
            "margen_pct", "margen_obj", "margen_extra_mensual", "motivo"]
    return (bajo[cols].sort_values("margen_extra_mensual", ascending=False)
                      .reset_index(drop=True))


def oportunidades_zona(v: pd.DataFrame) -> pd.DataFrame:
    """Venta cruzada por zona y tipo de negocio: categorías que los negocios
    de un mismo giro compran en otras zonas pero acá no — lista concreta
    para el vendedor de esa ruta."""
    if "zona" not in v.columns or v["zona"].isna().all():
        return pd.DataFrame()
    base = v.dropna(subset=["zona", "tipo_negocio"])
    # penetración de cada categoría por (tipo_negocio): % de clientes que la compran
    filas = []
    for tipo, g in base.groupby("tipo_negocio"):
        clientes_tipo = g["cliente_id"].nunique()
        if clientes_tipo < 5:
            continue
        pen_global = g.groupby("categoria")["cliente_id"].nunique() / clientes_tipo
        for zona, gz in g.groupby("zona"):
            cz = gz["cliente_id"].nunique()
            if cz < 3:
                continue
            pen_zona = gz.groupby("categoria")["cliente_id"].nunique() / cz
            for cat, pg in pen_global.items():
                pz = float(pen_zona.get(cat, 0.0))
                if pg >= 0.4 and pz < pg - 0.25:  # brecha real, no ruido
                    venta_prom = (g[g["categoria"] == cat]
                                  .groupby("cliente_id")["venta"].sum().median())
                    filas.append({
                        "zona": zona, "tipo_negocio": tipo, "categoria": cat,
                        "penetracion_zona_pct": round(pz * 100, 1),
                        "penetracion_general_pct": round(pg * 100, 1),
                        "clientes_zona": cz,
                        "venta_potencial": round(float(venta_prom) * cz * (pg - pz), 2),
                        "motivo": (f"En {zona}, solo {pz:.0%} de los {tipo.lower()}s "
                                   f"compra {cat} vs {pg:.0%} general"),
                    })
    if not filas:
        return pd.DataFrame()
    return (pd.DataFrame(filas)
              .sort_values("venta_potencial", ascending=False)
              .reset_index(drop=True))


def recupero_clientes(v: pd.DataFrame, clientes: pd.DataFrame) -> pd.DataFrame:
    """Clientes inactivos ordenados por lo que valían — a quién llamar primero."""
    inact = analitica.clientes_inactivos(v, clientes)
    if not len(inact):
        return pd.DataFrame()
    valor = v.groupby("cliente_id")["venta"].sum().rename("venta_historica")
    inact = inact.merge(valor, on="cliente_id", how="left")
    inact["motivo"] = inact.apply(
        lambda x: (f"Compraba ${x['venta_historica']:,.0f} y lleva "
                   f"{x['dias_sin_comprar']} días sin pedir"), axis=1)
    cols = [c for c in ["cliente_id", "nombre", "tipo_negocio", "departamento",
                        "zona", "dias_sin_comprar", "venta_historica", "motivo"]
            if c in inact.columns]
    return (inact[cols].sort_values("venta_historica", ascending=False)
                       .head(40).reset_index(drop=True))


def generar_todas(datos: dict) -> dict:
    """Corre todos los motores y devuelve {nombre: DataFrame} + resumen
    ejecutivo en pesos — el paquete que se exporta a PDF/Word."""
    productos, clientes = datos["productos"], datos["clientes"]
    v = analitica.enriquecer_ventas(datos["ventas"], productos, clientes)
    paquete = {
        "ofertas": ofertas_por_sobrestock(productos, v),
        "reposicion": reposicion(productos, v),
        "precios": precios(productos, v),
        "zonas": oportunidades_zona(v),
        "recupero": recupero_clientes(v, clientes),
    }
    resumen = {
        "capital_liberable": float(paquete["ofertas"]["capital_inmovilizado"].sum())
            if len(paquete["ofertas"]) else 0.0,
        "venta_en_riesgo": float(paquete["reposicion"]["venta_en_riesgo"].sum())
            if len(paquete["reposicion"]) else 0.0,
        "margen_extra_mensual": float(paquete["precios"]["margen_extra_mensual"].sum())
            if len(paquete["precios"]) else 0.0,
        "venta_potencial_zonas": float(paquete["zonas"]["venta_potencial"].sum())
            if len(paquete["zonas"]) else 0.0,
        "venta_recuperable": float(paquete["recupero"]["venta_historica"].sum())
            if len(paquete["recupero"]) else 0.0,
    }
    paquete["resumen"] = resumen
    return paquete
