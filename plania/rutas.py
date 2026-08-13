# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Planificador de rutas de reparto/visita
================================================
El corazón "logístico" de Plania: arma las rutas del día a partir de los
clientes con pedido (o a visitar), respetando capacidad por vehículo y
minimizando kilómetros con vecino-más-cercano + mejora 2-opt. No requiere
servicios externos de mapas: con lat/lon alcanza, y si el ERP no trae
coordenadas se agrupa por zona igual (orden alfabético de calle no, orden
de zona sí — que es como reparten hoy los distribuidores chicos).
"""
from __future__ import annotations

import math

import pandas as pd


def _haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _orden_vecino_mas_cercano(puntos: list[dict], dep_lat: float, dep_lon: float) -> list[dict]:
    pendientes = puntos[:]
    orden, lat, lon = [], dep_lat, dep_lon
    while pendientes:
        i = min(range(len(pendientes)),
                key=lambda j: _haversine_km(lat, lon, pendientes[j]["lat"], pendientes[j]["lon"]))
        p = pendientes.pop(i)
        orden.append(p)
        lat, lon = p["lat"], p["lon"]
    return orden


def _mejora_2opt(orden: list[dict], dep_lat: float, dep_lon: float,
                 max_pasadas: int = 4) -> list[dict]:
    def d(a, b):
        return _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])

    dep = {"lat": dep_lat, "lon": dep_lon}
    for _ in range(max_pasadas):
        mejoro = False
        n = len(orden)
        for i in range(n - 1):
            for j in range(i + 2, n):
                a = orden[i - 1] if i > 0 else dep
                b, c = orden[i], orden[j]
                sig = orden[j + 1] if j + 1 < n else dep
                if d(a, c) + d(b, sig) < d(a, b) + d(c, sig) - 1e-9:
                    orden[i:j + 1] = orden[i:j + 1][::-1]
                    mejoro = True
        if not mejoro:
            break
    return orden


def _km_ruta(orden: list[dict], dep_lat: float, dep_lon: float) -> float:
    km, lat, lon = 0.0, dep_lat, dep_lon
    for p in orden:
        km += _haversine_km(lat, lon, p["lat"], p["lon"])
        lat, lon = p["lat"], p["lon"]
    return km + _haversine_km(lat, lon, dep_lat, dep_lon)  # vuelta al depósito


def planificar(clientes: pd.DataFrame,
               vehiculos: int = 2,
               paradas_max: int = 25,
               deposito: tuple[float, float] | None = None,
               min_por_parada: int = 12,
               velocidad_kmh: float = 28.0) -> dict:
    """
    Arma `vehiculos` rutas balanceadas para los clientes recibidos (filtralos
    antes: los que tienen pedido, los inactivos a visitar, una zona, etc.).

    Devuelve {"rutas": DataFrame (una fila por parada, ordenada),
              "resumen": DataFrame (una fila por vehículo)}.
    """
    c = clientes.dropna(subset=["lat", "lon"]).copy() if \
        {"lat", "lon"}.issubset(clientes.columns) else pd.DataFrame()
    sin_gps = clientes[~clientes.index.isin(c.index)]

    if not len(c):
        # Sin coordenadas: agrupar por zona, repartir round-robin — sigue
        # siendo mejor que la libreta.
        out = clientes.copy()
        zonas = sorted(out.get("zona", pd.Series(["Única"] * len(out))).unique())
        asig = {z: (i % vehiculos) + 1 for i, z in enumerate(zonas)}
        out["vehiculo"] = out.get("zona", "Única").map(asig)
        out["orden"] = out.groupby("vehiculo").cumcount() + 1
        resumen = (out.groupby("vehiculo").size().rename("paradas").reset_index())
        resumen["km_estimados"] = None
        resumen["horas_estimadas"] = None
        return {"rutas": out, "resumen": resumen, "sin_gps": pd.DataFrame()}

    if deposito is None:
        deposito = (float(c["lat"].median()), float(c["lon"].median()))
    dep_lat, dep_lon = deposito

    # Clustering angular alrededor del depósito: barre la ciudad en "gajos"
    # contiguos (así cada vehículo se queda en su sector, como hace un
    # repartidor real), balanceando cantidad de paradas.
    c["_ang"] = c.apply(lambda x: math.atan2(x["lat"] - dep_lat, x["lon"] - dep_lon), axis=1)
    c = c.sort_values("_ang")
    vehiculos = max(vehiculos, math.ceil(len(c) / max(1, paradas_max)))
    grupos = [g for g in
              (c.iloc[i * len(c) // vehiculos:(i + 1) * len(c) // vehiculos]
               for i in range(vehiculos))
              if len(g)]

    filas, resumen = [], []
    for nv, g in enumerate(grupos, start=1):
        puntos = g.to_dict("records")
        orden = _mejora_2opt(_orden_vecino_mas_cercano(puntos, dep_lat, dep_lon),
                             dep_lat, dep_lon)
        km = _km_ruta(orden, dep_lat, dep_lon)
        horas = km / velocidad_kmh + len(orden) * min_por_parada / 60
        for i, p in enumerate(orden, start=1):
            p = dict(p)
            p.pop("_ang", None)
            p["vehiculo"] = nv
            p["orden"] = i
            filas.append(p)
        resumen.append({"vehiculo": nv, "paradas": len(orden),
                        "km_estimados": round(km, 1),
                        "horas_estimadas": round(horas, 1)})

    rutas = pd.DataFrame(filas)
    cols = [x for x in ["vehiculo", "orden", "cliente_id", "nombre", "tipo_negocio",
                        "departamento", "zona", "lat", "lon"] if x in rutas.columns]
    return {"rutas": rutas[cols + [x for x in rutas.columns if x not in cols]],
            "resumen": pd.DataFrame(resumen),
            "sin_gps": sin_gps}
