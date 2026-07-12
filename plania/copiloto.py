"""
Plania · Copiloto — chat sobre los datos reales del negocio
===========================================================
Responde en lenguaje natural consultas sobre stock, precios, márgenes,
ofertas, zonas, clientes y reposición **calculando contra los datos
conectados** (no inventa: cada respuesta sale de un DataFrame y la tabla
fuente se devuelve junto con el texto, lista para exportar a PDF/Word).

Funciona en dos niveles:
  1. Motor local de intenciones (siempre disponible, sin internet ni API
     key): detecta qué se pregunta y ejecuta la analítica que corresponde.
  2. Si hay ANTHROPIC_API_KEY configurada, redacta la respuesta con Claude
     usando SOLO los números ya calculados como contexto — la IA mejora la
     redacción, nunca los datos.
"""
from __future__ import annotations

import os
import re
import unicodedata

import pandas as pd

from plania import analitica, sugerencias

MODELO = "claude-haiku-4-5"


def _sin_tildes(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _buscar_producto(texto: str, productos: pd.DataFrame) -> pd.DataFrame:
    """Matchea SKU exacto o palabras del nombre/categoría."""
    t = _sin_tildes(texto)
    skus = re.findall(r"\bp?\d{3,}\b", t)
    if skus:
        m = productos[productos["sku"].str.lower().isin(
            [s if s.startswith("p") else f"p{s}" for s in skus])]
        if len(m):
            return m
    stop = {"cuanto", "cuanta", "stock", "hay", "de", "del", "la", "el", "los",
            "las", "que", "cual", "precio", "margen", "tengo", "queda", "quedan",
            "producto", "productos", "en", "y", "con", "para", "cuales", "mas",
            "menos", "top", "mejor", "peor", "este", "mes", "sobre", "bajo",
            "vendi", "vende", "venta", "ventas", "como"}
    palabras = [w for w in re.findall(r"[a-z]+", t) if w not in stop and len(w) > 3]
    if not palabras:
        return productos.head(0)
    idx = productos["nombre"].apply(_sin_tildes)
    cat = productos["categoria"].apply(_sin_tildes)
    mask = pd.Series(False, index=productos.index)
    for w in palabras:
        mask |= idx.str.contains(w, regex=False) | cat.str.contains(w, regex=False)
    return productos[mask]


def _n(texto: str, default: int = 10) -> int:
    m = re.search(r"\b(\d{1,3})\b", texto)
    return int(m.group(1)) if m else default


def responder(pregunta: str, datos: dict) -> dict:
    """
    Devuelve {"respuesta": str, "tabla": DataFrame|None, "titulo": str}.
    La tabla es la evidencia de la respuesta — exportable tal cual.
    """
    productos, clientes = datos["productos"], datos["clientes"]
    v = analitica.enriquecer_ventas(datos["ventas"], productos, clientes)
    t = _sin_tildes(pregunta)

    r = _responder_local(pregunta, t, productos, clientes, v)
    r["respuesta"] = _redactar_con_ia(pregunta, r) or r["respuesta"]
    return r


def _responder_local(pregunta: str, t: str, productos, clientes, v) -> dict:
    # --- ofertas / sobrestock -------------------------------------------------
    if any(k in t for k in ["oferta", "sobrestock", "sobre stock", "liquidar",
                            "no rota", "no se vende", "inmovilizado"]):
        of = sugerencias.ofertas_por_sobrestock(productos, v)
        if not len(of):
            return _r("No hay productos con sobrestock relevante: el stock está sano.", None,
                      "Ofertas sugeridas")
        cap = of["capital_inmovilizado"].sum()
        return _r(f"Hay {len(of)} productos con sobrestock que inmovilizan "
                  f"${cap:,.0f}. Sugiero ofertas con descuentos de "
                  f"{of['descuento_pct'].min():.0f}% a {of['descuento_pct'].max():.0f}% "
                  f"(siempre sobre el piso de costo+8%). Los 3 más urgentes: "
                  + "; ".join(f"{x['nombre']} ({x['descuento_pct']:.0f}% off)"
                              for _, x in of.head(3).iterrows()) + ".",
                  of, "Ofertas sugeridas por sobrestock")

    # --- reposición / quiebres ------------------------------------------------
    if any(k in t for k in ["repo", "quiebre", "falta", "comprar", "pedir",
                            "reponer", "sin stock", "agotad"]):
        rep = sugerencias.reposicion(productos, v)
        if not len(rep):
            return _r("No hay riesgo de quiebre con la rotación actual.", None, "Reposición")
        return _r(f"Hay {len(rep)} productos en riesgo de quiebre "
                  f"(${rep['venta_en_riesgo'].sum():,.0f}/mes de venta en juego). "
                  f"Inversión sugerida: ${rep['inversion'].sum():,.0f}. "
                  f"El más urgente: {rep.iloc[0]['nombre']} "
                  f"({rep.iloc[0]['dias_stock']:.0f} días de stock, proveedor demora "
                  f"{rep.iloc[0]['lead_time_dias']} días).",
                  rep, "Reposición sugerida")

    # --- precios / márgenes ---------------------------------------------------
    if "margen" in t or "precio" in t or "rentab" in t:
        prods = _buscar_producto(pregunta, productos)
        if len(prods) and len(prods) <= 15 and not any(
                k in t for k in ["bajo", "mejorar", "subir", "suger", "top", "peor"]):
            mp = analitica.margen_por_producto(v)
            m = prods.merge(mp[["sku", "venta", "margen", "margen_pct", "unidades"]],
                            on="sku", how="left")
            x = m.iloc[0]
            return _r(f"{x['nombre']}: precio ${x['precio']:,.2f}, costo ${x['costo']:,.2f} "
                      f"(margen {(x['precio'] / x['costo'] - 1) * 100 if x['costo'] else 0:.1f}%). "
                      f"En el período vendió {x['unidades'] if pd.notna(x['unidades']) else 0:.0f} "
                      f"unidades con margen real {x['margen_pct'] if pd.notna(x['margen_pct']) else 0:.1f}%.",
                      m, "Precio y margen")
        if any(k in t for k in ["mejorar", "subir", "suger", "bajo", "oportunidad"]):
            pr = sugerencias.precios(productos, v)
            if not len(pr):
                return _r("Los márgenes están alineados con su categoría; no hay subas obvias.",
                          None, "Precios")
            return _r(f"Hay {len(pr)} productos con margen por debajo de su categoría. "
                      f"Ajustarlos suma ${pr['margen_extra_mensual'].sum():,.0f}/mes "
                      f"sin tocar volumen. Mayor impacto: {pr.iloc[0]['nombre']} "
                      f"(de ${pr.iloc[0]['precio']:,.2f} a ${pr.iloc[0]['precio_sugerido']:,.2f}).",
                      pr, "Sugerencias de precios")
        mp = analitica.margen_por_producto(v, top=_n(t, 15))
        asc = "peor" in t or "menor" in t or "bajo" in t
        mp = mp.sort_values("margen_pct", ascending=asc)
        return _r(f"Margen promedio ponderado: "
                  f"{v['margen'].sum() / v['venta'].sum() * 100:.1f}%. "
                  f"Te muestro los {len(mp)} productos con "
                  f"{'menor' if asc else 'mayor'} venta/margen.",
                  mp, "Márgenes por producto")

    # --- stock ------------------------------------------------------------------
    if "stock" in t or "cuanto" in t and ("hay" in t or "queda" in t) or "existencia" in t:
        prods = _buscar_producto(pregunta, productos)
        if len(prods) == 0:
            val = (productos["stock"] * productos["costo"]).sum()
            r90 = analitica.rotacion(productos, v)
            return _r(f"Stock total: {productos['stock'].sum():,} unidades en "
                      f"{len(productos)} SKUs, valorizado en ${val:,.0f} al costo. "
                      f"{int((productos['stock'] <= 0).sum())} quiebres y "
                      f"{int((r90['dias_stock'] > 90).sum())} productos con más de 90 días de stock.",
                      r90[["sku", "nombre", "categoria", "stock", "venta_diaria", "dias_stock"]]
                      .sort_values("dias_stock", ascending=False),
                      "Stock general")
        p0 = prods.iloc[0]
        detalle = prods[["sku", "nombre", "categoria", "stock", "stock_min", "precio"]]
        if len(prods) == 1:
            estado = ("QUIEBRE" if p0["stock"] <= 0 else
                      "bajo mínimo" if p0["stock"] < p0["stock_min"] else "ok")
            return _r(f"{p0['nombre']} (SKU {p0['sku']}): {p0['stock']} unidades "
                      f"(mínimo {p0['stock_min']}, estado: {estado}).", detalle, "Stock")
        return _r(f"Encontré {len(prods)} productos que matchean: suman "
                  f"{prods['stock'].sum():,} unidades.", detalle, "Stock")

    # --- zonas / departamentos / tipo de negocio --------------------------------
    if any(k in t for k in ["zona", "departamento", "barrio", "region", "donde"]):
        dim = "departamento" if "departamento" in t else "zona"
        g = analitica.por_dimension(v, dim)
        op = sugerencias.oportunidades_zona(v)
        extra = (f" Detecté {len(op)} oportunidades de venta cruzada por zona "
                 f"(${op['venta_potencial'].sum():,.0f} potenciales)." if len(op) else "")
        if not len(g):
            return _r("Los datos conectados no traen zona/departamento de los clientes.",
                      None, "Zonas")
        return _r(f"La {dim} que más vende es {g.iloc[0][dim]} "
                  f"(${g.iloc[0]['venta']:,.0f}, margen {g.iloc[0]['margen_pct']:.1f}%) "
                  f"y la que menos, {g.iloc[-1][dim]} (${g.iloc[-1]['venta']:,.0f}).{extra}",
                  g if not len(op) else op, f"Análisis por {dim}")

    if any(k in t for k in ["tipo de negocio", "tipo negocio", "giro", "canal",
                            "almacen", "supermercado", "kiosco", "farmacia"]):
        g = analitica.por_dimension(v, "tipo_negocio")
        if not len(g):
            return _r("Los datos conectados no traen el tipo de negocio de los clientes.",
                      None, "Tipo de negocio")
        return _r(f"Por tipo de negocio: lidera {g.iloc[0]['tipo_negocio']} con "
                  f"${g.iloc[0]['venta']:,.0f} ({g.iloc[0]['clientes']} clientes). "
                  f"El mejor margen lo deja "
                  f"{g.sort_values('margen_pct').iloc[-1]['tipo_negocio']} "
                  f"({g['margen_pct'].max():.1f}%).",
                  g, "Ventas por tipo de negocio")

    # --- proveedores --------------------------------------------------------------
    if "proveedor" in t:
        g = analitica.por_dimension(v, "proveedor")
        if not len(g):
            return _r("Los datos conectados no traen proveedor.", None, "Proveedores")
        rep = sugerencias.reposicion(productos, v)
        urgente = ""
        if len(rep):
            top_prov = rep.groupby("proveedor")["venta_en_riesgo"].sum().idxmax()
            urgente = (f" Ojo: el pedido más urgente es a {top_prov} "
                       f"(${rep[rep['proveedor'] == top_prov]['inversion'].sum():,.0f} "
                       "de compra sugerida).")
        return _r(f"Tu proveedor principal es {g.iloc[0]['proveedor']} "
                  f"(${g.iloc[0]['venta']:,.0f} de venta asociada, margen "
                  f"{g.iloc[0]['margen_pct']:.1f}%).{urgente}",
                  g, "Análisis por proveedor")

    # --- venta de un producto puntual ----------------------------------------------
    if any(k in t for k in ["cuanto vendi", "venta de", "ventas de", "como vende",
                            "se vende"]):
        prods = _buscar_producto(pregunta, productos)
        if len(prods):
            mp = analitica.margen_por_producto(v)
            m = (prods[["sku", "nombre", "categoria", "precio", "stock"]]
                 .merge(mp[["sku", "venta", "margen", "margen_pct", "unidades"]],
                        on="sku", how="left").fillna(0)
                 .sort_values("venta", ascending=False))
            tot_v, tot_u = m["venta"].sum(), m["unidades"].sum()
            x = m.iloc[0]
            que = "Ese producto" if len(m) == 1 else f"Esos {len(m)} productos"
            extra = f" El que más mueve: {x['nombre']}." if len(m) > 1 else ""
            return _r(f"{que} vendió {tot_u:,.0f} unidades por ${tot_v:,.0f} "
                      f"en el período.{extra}",
                      m.head(30), "Venta del producto")

    # --- clientes ----------------------------------------------------------------
    if any(k in t for k in ["cliente", "inactivo", "recuperar", "dejo de comprar", "perdi"]):
        if any(k in t for k in ["inactivo", "recuperar", "dejo", "perdi"]):
            rec = sugerencias.recupero_clientes(v, clientes)
            if not len(rec):
                return _r("No hay clientes inactivos relevantes.", None, "Clientes")
            return _r(f"Hay {len(rec)} clientes que dejaron de comprar; valían "
                      f"${rec['venta_historica'].sum():,.0f}. Priorizá: "
                      + "; ".join(f"{x.get('nombre', x['cliente_id'])} "
                                  f"({x['dias_sin_comprar']}d)"
                                  for _, x in rec.head(3).iterrows()) + ".",
                      rec, "Clientes a recuperar")
        tc = analitica.top_clientes(v, _n(t, 15))
        return _r(f"Tus {len(tc)} mejores clientes concentran ${tc['venta'].sum():,.0f}. "
                  f"El primero hace {tc.iloc[0]['pedidos']} pedidos por "
                  f"${tc.iloc[0]['venta']:,.0f}.", tc, "Top clientes")

    # --- ventas / resumen ----------------------------------------------------------
    if any(k in t for k in ["venta", "vendi", "facturacion", "resumen", "como viene",
                            "top", "mas vendido", "tendencia", "mes"]):
        if "tendencia" in t or "mes a mes" in t or "evolucion" in t:
            tm = analitica.tendencia_mensual(v)
            delta = (tm.iloc[-1]["venta"] / tm.iloc[-2]["venta"] - 1) * 100 if len(tm) > 1 else 0
            return _r(f"Último mes: ${tm.iloc[-1]['venta']:,.0f} "
                      f"({delta:+.1f}% vs el anterior), margen {tm.iloc[-1]['margen_pct']:.1f}%.",
                      tm, "Tendencia mensual")
        mp = analitica.margen_por_producto(v, top=_n(t, 10))
        k = analitica.kpis(productos, v)
        return _r(f"Últimos 30 días: ${k['venta_periodo']:,.0f} de venta, margen "
                  f"{k['margen_pct']:.1f}% (${k['margen_periodo']:,.0f}), "
                  f"{k['clientes_activos']} clientes activos. El más vendido: "
                  f"{mp.iloc[0]['nombre']} (${mp.iloc[0]['venta']:,.0f}).",
                  mp, "Top ventas")

    # --- fallback: resumen ejecutivo -------------------------------------------------
    paq = sugerencias.generar_todas({"productos": productos, "clientes": clientes,
                                     "ventas": v})
    res = paq["resumen"]
    return _r("Puedo responder sobre stock, precios, márgenes, ofertas, reposición, "
              "zonas, tipos de negocio y clientes. Mientras tanto, el resumen de hoy: "
              f"${res['capital_liberable']:,.0f} inmovilizados en sobrestock, "
              f"${res['venta_en_riesgo']:,.0f} de venta en riesgo por quiebres, "
              f"${res['margen_extra_mensual']:,.0f}/mes de margen recuperable con "
              "ajustes de precio. Preguntame, por ejemplo: «¿qué ofertas armo esta "
              "semana?», «¿qué repongo ya?», «¿qué zona está floja?».",
              None, "Resumen ejecutivo")


def _r(respuesta: str, tabla, titulo: str) -> dict:
    return {"respuesta": respuesta, "tabla": tabla, "titulo": titulo}


def _redactar_con_ia(pregunta: str, r: dict) -> str | None:
    """Si hay API key, Claude redacta mejor la MISMA información (los números
    calculados van como contexto y son la única fuente permitida)."""
    from plania import config as pconfig
    key = os.environ.get("ANTHROPIC_API_KEY") or pconfig.leer_extra("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import requests
        contexto = r["respuesta"]
        if r["tabla"] is not None and len(r["tabla"]):
            contexto += "\n\nDatos (primeras filas):\n" + r["tabla"].head(12).to_string()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODELO, "max_tokens": 400, "messages": [{
                "role": "user",
                "content": ("Sos el copiloto comercial de Plania. Respondé la pregunta "
                            "del usuario usando EXCLUSIVAMENTE estos datos calculados "
                            "(no inventes números, no agregues datos externos). Español "
                            "rioplatense profesional, directo, máximo 5 frases.\n\n"
                            f"Pregunta: {pregunta}\n\nDatos calculados:\n{contexto}")}]},
            timeout=20)
        if resp.ok:
            return (resp.json().get("content") or [{}])[0].get("text") or None
    except Exception:
        pass
    return None
