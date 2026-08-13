# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Datos del negocio del dueño (versión owner)
====================================================
Lo que el cliente NUNCA ve: cuántas demos se entregaron, cuántas se
convirtieron en pago, cuánto factura el negocio, qué le cuesta cada cliente
y cuánto margen queda.

La fuente no es una planilla aparte: son los mismos registros que el
producto ya genera al operar — la base de uso y licencias
(`backend_venta/uso.py`) y el log de auditoría encadenado por hash
(`plania/auditoria.py`). Es decir, la contabilidad del negocio sale de la
operación real, no de lo que uno recuerda haber vendido.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from plania import auditoria as pauditoria
from plania import negocio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_USO = os.environ.get("PLANIA_USO_DB", os.path.join(ROOT, "data", "uso_licencias.db"))


def _leer_tabla(tabla: str, db_path: str = DB_USO) -> pd.DataFrame:
    if not os.path.exists(db_path):
        return pd.DataFrame()
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql(f"SELECT * FROM {tabla}", con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()


def trials_entregados() -> pd.DataFrame:
    """Demos de 7 días entregadas (una por email, según la tabla `trials`)."""
    df = _leer_tabla("trials")
    if len(df):
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
    return df


def licencias_emitidas() -> pd.DataFrame:
    """Licencias emitidas, leídas del log de auditoría (trial, manual y pago).

    El log está encadenado por hash: si alguien editara una línea a mano para
    inflar las ventas, `auditoria.verificar_integridad()` lo detecta.
    """
    filas = []
    for ev in pauditoria.leer():
        accion = ev.get("accion", "")
        if not accion.startswith(("licencia_emitida", "trial_emitido")):
            continue
        det = ev.get("detalle", {}) or {}
        filas.append({
            "fecha": ev.get("ts"),
            "tipo": ("Demo 7 días" if accion == "trial_emitido"
                     else "Pago (MercadoPago)" if accion == "licencia_emitida_pago"
                     else "Manual / venta directa"),
            "cliente": det.get("cliente", "—"),
            "plan": det.get("plan", "trial"),
            "payment_id": det.get("payment_id", ""),
        })
    df = pd.DataFrame(filas)
    if len(df):
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
        df = df.sort_values("fecha", ascending=False)
    return df


def uso_por_cliente() -> pd.DataFrame:
    """Consumo real por cliente: es la base para facturar excedentes y para
    detectar quién no está usando el producto (el que no lo usa, se va)."""
    df = _leer_tabla("uso")
    if not len(df):
        return pd.DataFrame()
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
    g = (df.groupby("cliente_id", as_index=False)
           .agg(consultas=("id", "count"),
                tok_in=("tok_in", "sum"), tok_out=("tok_out", "sum"),
                costo_est=("costo_est", "sum"),
                ultima_actividad=("fecha", "max")))
    g["costo_ia_estimado"] = (g["consultas"] * negocio.COSTO_IA_POR_CONSULTA
                              + g["costo_est"]).round(3)
    hoy = pd.Timestamp.now(tz="UTC")
    g["dias_sin_usar"] = (hoy - g["ultima_actividad"]).dt.days
    return g.sort_values("consultas", ascending=False)


def kpis_negocio() -> dict:
    """El tablero del dueño. Todo sale de la operación registrada."""
    from backend_venta import licencias as lic

    emitidas = licencias_emitidas()
    trials = trials_entregados()
    uso = uso_por_cliente()

    if len(emitidas):
        pagas = emitidas[emitidas["tipo"] != "Demo 7 días"]
        clientes_pagos = pagas["cliente"].nunique()
        demos = emitidas[emitidas["tipo"] == "Demo 7 días"]["cliente"].nunique()
    else:
        clientes_pagos, demos = 0, 0
    demos = max(demos, int(trials["email"].nunique()) if len(trials) else 0)

    # MRR real: precio de plan por cada cliente pago vigente
    mrr = 0.0
    if len(emitidas):
        ultimos = (emitidas[emitidas["tipo"] != "Demo 7 días"]
                   .sort_values("fecha").groupby("cliente").last())
        for _, fila in ultimos.iterrows():
            plan = lic.PLANES.get(fila["plan"], {})
            mrr += float(plan.get("precio") or 0.0)

    costo_ia = float(uso["costo_ia_estimado"].sum()) if len(uso) else 0.0
    comision = mrr * negocio.COMISION_MERCADOPAGO
    inactivos = int((uso["dias_sin_usar"] > 14).sum()) if len(uso) else 0

    return {
        "demos_entregadas": demos,
        "clientes_pagos": clientes_pagos,
        "conversion_pct": round(clientes_pagos / demos * 100, 1) if demos else 0.0,
        "mrr_usd": round(mrr, 2),
        "arr_usd": round(mrr * 12, 2),
        "costo_ia_mes_usd": round(costo_ia, 2),
        "comision_mp_mes_usd": round(comision, 2),
        "margen_bruto_pct": round((1 - (costo_ia + comision) / mrr) * 100, 1) if mrr else 0.0,
        "consultas_totales": int(uso["consultas"].sum()) if len(uso) else 0,
        "clientes_en_riesgo": inactivos,
    }


def integridad_registros() -> dict:
    """Verifica que el log de auditoría no haya sido alterado."""
    try:
        return pauditoria.verificar_integridad()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def secciones_para_informe_owner() -> list:
    """Informe del negocio, exportable a PDF/Word/Excel."""
    k = kpis_negocio()
    resumen = (
        f"{k['demos_entregadas']} demos entregadas y {k['clientes_pagos']} "
        f"clientes pagos ({k['conversion_pct']}% de conversión). "
        f"MRR USD {k['mrr_usd']:,.0f} (ARR USD {k['arr_usd']:,.0f}). "
        f"Costo de IA USD {k['costo_ia_mes_usd']:,.2f} y comisión de "
        f"MercadoPago USD {k['comision_mp_mes_usd']:,.2f}, con margen bruto de "
        f"{k['margen_bruto_pct']}%. "
        f"{k['clientes_en_riesgo']} clientes sin actividad hace más de 14 días.")
    secciones = [("Estado del negocio", resumen, None)]

    emitidas = licencias_emitidas()
    if len(emitidas):
        secciones.append(("Licencias emitidas",
                          "Historial completo con su origen (demo, pago o venta "
                          "directa), tomado del log de auditoría encadenado.",
                          emitidas))
    uso = uso_por_cliente()
    if len(uso):
        secciones.append(("Uso y costo por cliente",
                          "Consumo real de cada cliente y su costo de IA. Los "
                          "clientes sin actividad reciente son los que están por "
                          "irse.", uso))
    return secciones
