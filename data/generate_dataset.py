# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Generador de dataset demo (Uruguay)
============================================
Genera un negocio de distribución/comercio sintético pero realista para la
demo comercial de 7 días: productos, clientes (con zona y tipo de negocio) y
12 meses de ventas. Además arma una base SQLite (`data/erp_demo.db`) que
simula el ERP del cliente — así el conector universal, el copiloto y las
sugerencias se demuestran contra una "base real" sin depender de nadie.

Uso:
    python3 data/generate_dataset.py --seed 42
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))

CATEGORIAS = {
    "Bebidas":      {"costo": (25, 220),  "margen": (0.22, 0.38), "rotacion": 1.6},
    "Almacén":      {"costo": (18, 160),  "margen": (0.18, 0.35), "rotacion": 1.4},
    "Lácteos":      {"costo": (30, 190),  "margen": (0.15, 0.28), "rotacion": 1.8},
    "Limpieza":     {"costo": (40, 260),  "margen": (0.25, 0.45), "rotacion": 1.0},
    "Perfumería":   {"costo": (60, 480),  "margen": (0.30, 0.55), "rotacion": 0.7},
    "Snacks":       {"costo": (15, 120),  "margen": (0.28, 0.50), "rotacion": 1.5},
    "Congelados":   {"costo": (80, 420),  "margen": (0.20, 0.38), "rotacion": 0.9},
    "Ferretería":   {"costo": (35, 900),  "margen": (0.35, 0.60), "rotacion": 0.5},
}

PROVEEDORES = ["Distribuidora Oriental", "CAMPIGLIA S.A.", "Norte Import",
               "Del Plata Mayorista", "Rionegrina", "ImportPack UY", "Global Andina"]

# Departamento -> (zonas, lat base, lon base, peso comercial)
GEOGRAFIA = {
    "Montevideo": (["Centro", "Cordón", "Pocitos", "Carrasco", "Cerro", "Sayago",
                    "Unión", "Malvín", "Prado", "La Teja"], -34.90, -56.16, 0.42),
    "Canelones":  (["Las Piedras", "Pando", "Ciudad de la Costa", "Santa Lucía",
                    "Canelones"], -34.72, -56.02, 0.18),
    "Maldonado":  (["Maldonado", "Punta del Este", "San Carlos"], -34.90, -54.95, 0.10),
    "Colonia":    (["Colonia", "Carmelo", "Nueva Helvecia"], -34.46, -57.84, 0.06),
    "Salto":      (["Salto Centro", "Salto Norte"], -31.38, -57.96, 0.06),
    "Paysandú":   (["Paysandú Centro", "Paysandú Este"], -32.32, -58.08, 0.05),
    "Rivera":     (["Rivera Centro", "Mandubí"], -30.90, -55.55, 0.04),
    "Tacuarembó": (["Tacuarembó Centro"], -31.71, -55.98, 0.03),
    "San José":   (["San José de Mayo", "Libertad"], -34.34, -56.71, 0.03),
    "Rocha":      (["Rocha", "Chuy", "La Paloma"], -34.48, -54.33, 0.03),
}

TIPOS_NEGOCIO = {
    "Almacén":          0.30,
    "Supermercado":     0.14,
    "Autoservicio":     0.16,
    "Kiosco":           0.12,
    "Bar/Restaurante":  0.10,
    "Farmacia":         0.06,
    "Ferretería":       0.06,
    "Panadería":        0.06,
}


def generar_productos(rng: np.random.Generator, n: int = 320) -> pd.DataFrame:
    filas = []
    for i in range(n):
        cat = rng.choice(list(CATEGORIAS), p=_pesos(len(CATEGORIAS)))
        c = CATEGORIAS[cat]
        costo = round(float(rng.uniform(*c["costo"])), 2)
        margen = float(rng.uniform(*c["margen"]))
        precio = round(costo * (1 + margen), 2)
        base_rot = c["rotacion"] * float(rng.lognormal(0, 0.6))
        filas.append({
            "sku": f"P{i + 1:04d}",
            "nombre": f"{cat} {_nombre_producto(rng, cat)} {rng.integers(100, 999)}",
            "categoria": cat,
            "proveedor": str(rng.choice(PROVEEDORES)),
            "costo": costo,
            "precio": precio,
            # stock actual: mezcla de sanos, sobrestock y quiebres
            "stock": int(max(0, rng.normal(base_rot * 45, base_rot * 40))),
            "stock_min": int(max(2, base_rot * 12)),
            "lead_time_dias": int(rng.integers(3, 21)),
            "_rot": base_rot,  # interno, no se exporta
        })
    return pd.DataFrame(filas)


def generar_clientes(rng: np.random.Generator, n: int = 260) -> pd.DataFrame:
    deptos = list(GEOGRAFIA)
    pesos = np.array([GEOGRAFIA[d][3] for d in deptos])
    pesos = pesos / pesos.sum()
    tipos = list(TIPOS_NEGOCIO)
    ptipos = np.array(list(TIPOS_NEGOCIO.values()))
    filas = []
    for i in range(n):
        depto = str(rng.choice(deptos, p=pesos))
        zonas, lat0, lon0, _ = GEOGRAFIA[depto]
        tipo = str(rng.choice(tipos, p=ptipos))
        filas.append({
            "cliente_id": f"C{i + 1:04d}",
            "nombre": f"{tipo} {_apellido(rng)}",
            "tipo_negocio": tipo,
            "departamento": depto,
            "zona": str(rng.choice(zonas)),
            "lat": round(lat0 + float(rng.normal(0, 0.05)), 5),
            "lon": round(lon0 + float(rng.normal(0, 0.05)), 5),
            "dias_visita": int(rng.choice([7, 14, 30], p=[0.5, 0.3, 0.2])),
        })
    return pd.DataFrame(filas)


def generar_ventas(rng: np.random.Generator, productos: pd.DataFrame,
                   clientes: pd.DataFrame, meses: int = 12) -> pd.DataFrame:
    """12 meses de líneas de venta con estacionalidad (verano sube bebidas)."""
    hoy = date.today()
    ini = hoy - timedelta(days=meses * 30)
    filas = []
    vid = 0
    # afinidad tipo de negocio -> categorías (para que "zonas/tipo negocio"
    # tengan señal real que el copiloto pueda encontrar)
    afinidad = {
        "Almacén": ["Almacén", "Bebidas", "Lácteos", "Snacks", "Limpieza"],
        "Supermercado": list(CATEGORIAS),
        "Autoservicio": ["Almacén", "Bebidas", "Lácteos", "Snacks", "Limpieza", "Congelados"],
        "Kiosco": ["Snacks", "Bebidas"],
        "Bar/Restaurante": ["Bebidas", "Congelados", "Almacén"],
        "Farmacia": ["Perfumería", "Limpieza"],
        "Ferretería": ["Ferretería", "Limpieza"],
        "Panadería": ["Almacén", "Lácteos", "Bebidas"],
    }
    por_cat = {c: g for c, g in productos.groupby("categoria")}
    for _, cli in clientes.iterrows():
        cats = afinidad[cli["tipo_negocio"]]
        n_pedidos = max(3, int(rng.poisson(meses * 30 / cli["dias_visita"])))
        for _ in range(n_pedidos):
            f = ini + timedelta(days=int(rng.integers(0, meses * 30)))
            estacional = 1.0
            if f.month in (12, 1, 2):
                estacional = 1.35  # verano
            n_lineas = int(rng.integers(1, 7))
            for _ in range(n_lineas):
                cat = str(rng.choice(cats))
                g = por_cat[cat]
                prod = g.iloc[int(rng.integers(0, len(g)))]
                mult = 1.5 if cat == "Bebidas" else 1.0
                cant = max(1, int(rng.lognormal(1.2, 0.7) * prod["_rot"] * estacional * mult))
                vid += 1
                filas.append({
                    "venta_id": f"V{vid:06d}",
                    "fecha": f.isoformat(),
                    "cliente_id": cli["cliente_id"],
                    "sku": prod["sku"],
                    "cantidad": cant,
                    "precio_unit": prod["precio"],
                    "costo_unit": prod["costo"],
                })
    return pd.DataFrame(filas)


def _pesos(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


def _nombre_producto(rng, cat: str) -> str:
    marcas = ["Premium", "Clásico", "Familiar", "Light", "Max", "Eco", "Oro", "Sur"]
    return str(rng.choice(marcas))


def _apellido(rng) -> str:
    return str(rng.choice(["Rodríguez", "Pérez", "García", "Silva", "Fernández",
                           "Martínez", "Sosa", "Díaz", "Núñez", "Cabrera", "Techera",
                           "Olivera", "Acosta", "Machado", "Suárez"]))


def crear_erp_demo(productos: pd.DataFrame, clientes: pd.DataFrame,
                   ventas: pd.DataFrame, ruta_db: str) -> None:
    """Base SQLite con NOMBRES DE COLUMNA DISTINTOS a los canónicos, a
    propósito: demuestra que el conector universal mapea cualquier esquema."""
    con = sqlite3.connect(ruta_db)
    try:
        productos.rename(columns={
            "sku": "cod_articulo", "nombre": "descripcion", "categoria": "rubro",
            "costo": "costo_unitario", "precio": "precio_venta",
            "stock": "stock_actual", "stock_min": "stock_minimo",
        }).to_sql("articulos", con, if_exists="replace", index=False)
        clientes.rename(columns={
            "cliente_id": "cod_cliente", "nombre": "razon_social",
            "tipo_negocio": "giro", "zona": "barrio",
        }).to_sql("clientes", con, if_exists="replace", index=False)
        ventas.rename(columns={
            "venta_id": "nro_comprobante", "fecha": "fecha_emision",
            "sku": "cod_articulo", "cliente_id": "cod_cliente",
            "cantidad": "unidades", "precio_unit": "precio_unitario",
            "costo_unit": "costo_unitario",
        }).to_sql("ventas", con, if_exists="replace", index=False)
    finally:
        con.close()


def main(seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    productos = generar_productos(rng)
    clientes = generar_clientes(rng)
    ventas = generar_ventas(rng, productos, clientes)
    productos = productos.drop(columns=["_rot"])

    os.makedirs(AQUI, exist_ok=True)
    productos.to_csv(os.path.join(AQUI, "productos.csv"), index=False)
    clientes.to_csv(os.path.join(AQUI, "clientes.csv"), index=False)
    ventas.to_csv(os.path.join(AQUI, "ventas.csv"), index=False)
    crear_erp_demo(productos, clientes, ventas, os.path.join(AQUI, "erp_demo.db"))
    print(f"[plania] dataset demo: {len(productos)} productos, {len(clientes)} clientes, "
          f"{len(ventas)} líneas de venta · data/erp_demo.db listo")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    main(**vars(ap.parse_args()))
