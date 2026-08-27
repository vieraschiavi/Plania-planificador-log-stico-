# © 2026 Martín Viera. Todos los derechos reservados.
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

Disponible en español, inglés y portugués. El entendimiento de la pregunta
es matching de palabras clave por idioma (`PALABRAS_CLAVE`, más abajo), no
gramatical — cubre cómo se pregunta esto normalmente en cada idioma, no
cualquier forma de decirlo. La redacción de la respuesta sale del mismo
catálogo que usa el resto del producto (`plania/i18n.py`), así que un
concepto se llama igual en el copiloto que en las tarjetas y las tablas.
"""
from __future__ import annotations

import os
import re
import unicodedata

import pandas as pd

from plania import analitica, i18n, sugerencias

MODELO = "claude-haiku-4-5"

# Prompt de la capa Claude, por idioma — pide la respuesta en el idioma
# elegido en vez de "español rioplatense" fijo. `{idioma_nombre}` es el
# nombre del idioma en SU PROPIO idioma (i18n.NOMBRES_IDIOMA), no traducido
# — "respondé en Português" tendría sentido, pero pedirle a Claude que
# entienda una instrucción en español para responder en portugués es una
# vuelta innecesaria.
_PROMPT_IA = {
    "es": ("Sos el copiloto comercial de Plania. Respondé la pregunta del "
           "usuario usando EXCLUSIVAMENTE estos datos calculados (no "
           "inventes números, no agregues datos externos). Español "
           "rioplatense profesional, directo, máximo 5 frases.\n\n"
           "Pregunta: {pregunta}\n\nDatos calculados:\n{contexto}"),
    "en": ("You are Plania's sales copilot. Answer the user's question "
           "using EXCLUSIVELY these calculated figures (don't invent "
           "numbers, don't add external data). Professional, direct "
           "English, at most 5 sentences.\n\n"
           "Question: {pregunta}\n\nCalculated data:\n{contexto}"),
    "pt": ("Você é o copiloto comercial do Plania. Responda a pergunta do "
           "usuário usando EXCLUSIVAMENTE estes dados calculados (não "
           "invente números, não adicione dados externos). Português "
           "profissional, direto, no máximo 5 frases.\n\n"
           "Pergunta: {pregunta}\n\nDados calculados:\n{contexto}"),
}

# ---------------------------------------------------------------------------
# Entendimiento de la pregunta, por idioma
# ---------------------------------------------------------------------------
# Matching por palabra clave, no gramatical — cubre cómo se pregunta esto
# normalmente en cada idioma. Las listas están escritas SIN tildes/acentos
# porque `_sin_tildes()` se los saca también a la pregunta antes de
# comparar: "días" en la lista nunca matchearía contra "dias" ya procesado.
PALABRAS_CLAVE = {
    "ofertas": {
        "es": ["oferta", "sobrestock", "sobre stock", "liquidar", "no rota",
              "no se vende", "inmovilizado"],
        "en": ["offer", "overstock", "excess stock", "liquidate",
              "not selling", "not moving", "tied up", "slow moving",
              "clearance"],
        "pt": ["oferta", "excesso de estoque", "sobra de estoque", "liquidar",
              "nao vende", "parado", "imobilizado", "encalhado"],
    },
    "reposicion": {
        "es": ["repo", "quiebre", "falta", "comprar", "pedir", "reponer",
              "sin stock", "agotad"],
        # "buy" quedó afuera a propósito: como sustantivo suelto matchea
        # "buys"/"buying"/"buyer" en cualquier pregunta sobre COMPRADORES
        # ("which business type buys the most?"), no sólo sobre reponer
        # stock. El español no tenía este choque porque "comprar" (infinitivo)
        # no es substring de "compra" (él/ella compra).
        "en": ["restock", "reorder", "replenish", "running out", "stockout",
              "need to buy", "order", "out of stock", "low stock"],
        "pt": ["repo", "ruptura", "falta", "comprar", "pedir", "repor",
              "sem estoque", "esgotad"],
    },
    "tipo_negocio": {
        "es": ["tipo de negocio", "tipo negocio", "giro", "canal", "almacen",
              "supermercado", "kiosco", "farmacia"],
        "en": ["business type", "type of business", "segment", "channel",
              "grocery", "supermarket", "kiosk", "pharmacy"],
        "pt": ["tipo de negocio", "tipo negocio", "segmento", "canal",
              "mercearia", "supermercado", "quiosque", "farmacia"],
    },
    "zonas": {
        "es": ["zona", "departamento", "barrio", "region", "donde"],
        "en": ["zone", "area", "region", "district", "where"],
        "pt": ["zona", "departamento", "regiao", "bairro", "onde"],
    },
    "venta_puntual": {
        "es": ["cuanto vendi", "venta de", "ventas de", "como vende",
              "se vende"],
        "en": ["how much did i sell", "sales of", "how does it sell",
              "sells", "selling of"],
        "pt": ["quanto vendi", "venda de", "vendas de", "como vende",
              "se vende"],
    },
    "clientes": {
        "es": ["cliente", "inactivo", "recuperar", "dejo de comprar", "perdi"],
        "en": ["customer", "client", "inactive", "win back", "win-back",
              "stopped buying", "lost", "lose", "losing"],
        "pt": ["cliente", "inativo", "recuperar", "parou de comprar", "perdi"],
    },
    "clientes_inactivos": {
        "es": ["inactivo", "recuperar", "dejo", "perdi"],
        # "lost"/"lose"/"losing": cubre "did I lose", "customers I've lost",
        # "customers I'm losing" — el tiempo verbal varía más en inglés que
        # en español, donde "perdí" alcanza para las formas habituales de
        # la pregunta.
        "en": ["inactive", "win back", "win-back", "stopped", "lost", "lose",
              "losing"],
        "pt": ["inativo", "recuperar", "parou", "perdi"],
    },
    "ventas": {
        "es": ["venta", "vendi", "facturacion", "resumen", "como viene",
              "top", "mas vendido", "tendencia", "mes"],
        "en": ["sales", "sold", "revenue", "summary", "how are we doing",
              "top", "best seller", "best selling", "trend", "month"],
        "pt": ["venda", "vendi", "faturamento", "resumo", "como esta indo",
              "top", "mais vendido", "tendencia", "mes"],
    },
    "tendencia": {
        "es": ["tendencia", "mes a mes", "evolucion"],
        "en": ["trend", "month over month", "month-over-month", "evolution"],
        "pt": ["tendencia", "mes a mes", "evolucao"],
    },
}

# `_buscar_producto`: palabras que no aportan al nombre del producto que se
# busca — mismo criterio que las de arriba, sin tildes.
_STOP = {
    "es": {"cuanto", "cuanta", "stock", "hay", "de", "del", "la", "el", "los",
          "las", "que", "cual", "precio", "margen", "tengo", "queda",
          "quedan", "producto", "productos", "en", "y", "con", "para",
          "cuales", "mas", "menos", "top", "mejor", "peor", "este", "mes",
          "sobre", "bajo", "vendi", "vende", "venta", "ventas", "como"},
    "en": {"how", "much", "many", "stock", "is", "there", "the", "of", "a",
          "an", "that", "which", "price", "margin", "have", "left",
          "product", "products", "in", "and", "with", "for", "more", "less",
          "top", "best", "worst", "this", "month", "about", "under", "sold",
          "sell", "sale", "sales", "does", "do", "did"},
    "pt": {"quanto", "quanta", "estoque", "tem", "de", "do", "da", "os",
          "as", "o", "a", "que", "qual", "preco", "margem", "tenho",
          "resta", "restam", "produto", "produtos", "em", "e", "com",
          "para", "quais", "mais", "menos", "top", "melhor", "pior", "este",
          "mes", "sobre", "abaixo", "vendi", "vende", "venda", "vendas",
          "como"},
}


def _sin_tildes(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _tiene(t: str, categoria: str, idioma: str) -> bool:
    return any(k in t for k in PALABRAS_CLAVE[categoria].get(idioma, PALABRAS_CLAVE[categoria]["es"]))


def _buscar_producto(texto: str, productos: pd.DataFrame, idioma: str = "es") -> pd.DataFrame:
    """Matchea SKU exacto o palabras del nombre/categoría."""
    t = _sin_tildes(texto)
    skus = re.findall(r"\bp?\d{3,}\b", t)
    if skus:
        m = productos[productos["sku"].str.lower().isin(
            [s if s.startswith("p") else f"p{s}" for s in skus])]
        if len(m):
            return m
    stop = _STOP.get(idioma, _STOP["es"])
    palabras = [w for w in re.findall(r"[a-z]+", t) if w not in stop and len(w) > 3]
    if not palabras:
        return productos.head(0)
    idx = productos["nombre"].apply(_sin_tildes)
    cat = productos["categoria"].apply(_sin_tildes)
    mask = pd.Series(False, index=productos.index)
    for w in palabras:
        mask |= idx.str.contains(w, regex=False) | cat.str.contains(w, regex=False)
    return productos[mask]


def _m(n, idioma: str = "es", decimales: int = 0) -> str:
    return i18n.miles(n, decimales, idioma)


def _n(texto: str, default: int = 10) -> int:
    m = re.search(r"\b(\d{1,3})\b", texto)
    return int(m.group(1)) if m else default


def responder(pregunta: str, datos: dict, idioma: str = "es") -> dict:
    """
    Devuelve {"respuesta": str, "tabla": DataFrame|None, "titulo": str}.
    La tabla es la evidencia de la respuesta — exportable tal cual.
    """
    productos, clientes = datos["productos"], datos["clientes"]
    v = analitica.enriquecer_ventas(datos["ventas"], productos, clientes)
    t = _sin_tildes(pregunta)

    r = _responder_local(pregunta, t, productos, clientes, v, idioma)
    r["respuesta"] = _redactar_con_ia(pregunta, r, idioma) or r["respuesta"]
    return r


def _responder_local(pregunta: str, t: str, productos, clientes, v,
                     idioma: str = "es") -> dict:
    def tr(clave, **kw):
        return i18n.t(clave, idioma, **kw)

    # --- ofertas / sobrestock -------------------------------------------------
    if _tiene(t, "ofertas", idioma):
        of = sugerencias.ofertas_por_sobrestock(productos, v, idioma)
        if not len(of):
            return _r(tr("copiloto.ofertas_sin_datos"), None, tr("copiloto.ofertas_titulo"))
        cap = of["capital_inmovilizado"].sum()
        lista = "; ".join(tr("copiloto.ofertas_item", nombre=x["nombre"],
                             descuento=_m(x["descuento_pct"], idioma))
                          for _, x in of.head(3).iterrows())
        return _r(tr("copiloto.ofertas_resumen", n=len(of), capital=_m(cap, idioma),
                     min_desc=_m(of["descuento_pct"].min(), idioma),
                     max_desc=_m(of["descuento_pct"].max(), idioma), lista=lista),
                  of, tr("copiloto.ofertas_titulo_lista"))

    # --- reposición / quiebres ------------------------------------------------
    if _tiene(t, "reposicion", idioma):
        rep = sugerencias.reposicion(productos, v, idioma=idioma)
        if not len(rep):
            return _r(tr("copiloto.reposicion_sin_datos"), None, tr("copiloto.reposicion_titulo"))
        p0 = rep.iloc[0]
        return _r(tr("copiloto.reposicion_resumen", n=len(rep),
                     venta_riesgo=_m(rep["venta_en_riesgo"].sum(), idioma),
                     inversion=_m(rep["inversion"].sum(), idioma), nombre=p0["nombre"],
                     dias_stock=f"{p0['dias_stock']:.0f}", lead_time_dias=p0["lead_time_dias"]),
                  rep, tr("copiloto.reposicion_titulo_lista"))

    # --- precios / márgenes ---------------------------------------------------
    if ("margen" in t or "precio" in t or "rentab" in t if idioma == "es" else
        _tiene_precio_margen(t, idioma)):
        prods = _buscar_producto(pregunta, productos, idioma)
        if len(prods) and len(prods) <= 15 and not _tiene_ajuste(t, idioma):
            mp = analitica.margen_por_producto(v)
            m = prods.merge(mp[["sku", "venta", "margen", "margen_pct", "unidades"]],
                            on="sku", how="left")
            x = m.iloc[0]
            return _r(tr("copiloto.precio_producto", nombre=x["nombre"],
                         precio=_m(x["precio"], idioma, 2), costo=_m(x["costo"], idioma, 2),
                         margen=_m((x["precio"] / x["costo"] - 1) * 100 if x["costo"] else 0, idioma, 1),
                         unidades=f"{x['unidades'] if pd.notna(x['unidades']) else 0:.0f}",
                         margen_real=_m(x["margen_pct"] if pd.notna(x["margen_pct"]) else 0, idioma, 1)),
                      m, tr("copiloto.precio_producto_titulo"))
        if _tiene_ajuste(t, idioma):
            pr = sugerencias.precios(productos, v, idioma=idioma)
            if not len(pr):
                return _r(tr("copiloto.precios_sin_subas"), None, tr("copiloto.precios_titulo"))
            p0 = pr.iloc[0]
            return _r(tr("copiloto.precios_resumen", n=len(pr),
                         extra=_m(pr["margen_extra_mensual"].sum(), idioma), nombre=p0["nombre"],
                         precio=_m(p0["precio"], idioma, 2), sugerido=_m(p0["precio_sugerido"], idioma, 2)),
                      pr, tr("copiloto.precios_titulo_lista"))
        mp = analitica.margen_por_producto(v, top=_n(t, 15))
        asc = _es_ascendente(t, idioma)
        mp = mp.sort_values("margen_pct", ascending=asc)
        return _r(tr("copiloto.margenes_resumen",
                     promedio=_m(v["margen"].sum() / v["venta"].sum() * 100, idioma, 1),
                     n=len(mp), orden=tr("copiloto.orden_menor" if asc else "copiloto.orden_mayor")),
                  mp, tr("copiloto.margenes_titulo"))

    # --- stock ------------------------------------------------------------------
    if _tiene_stock(t, idioma):
        prods = _buscar_producto(pregunta, productos, idioma)
        if len(prods) == 0:
            val = (productos["stock"] * productos["costo"]).sum()
            r90 = analitica.rotacion(productos, v)
            return _r(tr("copiloto.stock_general_resumen", total=_m(productos["stock"].sum(), idioma),
                         n=len(productos), valor=_m(val, idioma),
                         quiebres=int((productos["stock"] <= 0).sum()),
                         sobrestock=int((r90["dias_stock"] > 90).sum())),
                      r90[["sku", "nombre", "categoria", "stock", "venta_diaria", "dias_stock"]]
                      .sort_values("dias_stock", ascending=False),
                      tr("copiloto.stock_general_titulo"))
        p0 = prods.iloc[0]
        detalle = prods[["sku", "nombre", "categoria", "stock", "stock_min", "precio"]]
        if len(prods) == 1:
            estado = (tr("copiloto.stock_estado_quiebre") if p0["stock"] <= 0 else
                      tr("copiloto.stock_estado_bajo_minimo") if p0["stock"] < p0["stock_min"] else
                      tr("copiloto.stock_estado_ok"))
            return _r(tr("copiloto.stock_producto_unico", nombre=p0["nombre"], sku=p0["sku"],
                         stock=p0["stock"], minimo=p0["stock_min"], estado=estado),
                      detalle, tr("copiloto.stock_titulo"))
        return _r(tr("copiloto.stock_varios", n=len(prods), total=_m(prods["stock"].sum(), idioma)),
                  detalle, tr("copiloto.stock_titulo"))

    # --- zonas / departamentos / tipo de negocio --------------------------------
    if _tiene(t, "zonas", idioma):
        dim = "departamento" if "departamento" in t else "zona"
        g = analitica.por_dimension(v, dim)
        op = sugerencias.oportunidades_zona(v, idioma)
        extra = (tr("copiloto.zonas_extra_oportunidades", n=len(op),
                    potencial=_m(op["venta_potencial"].sum(), idioma)) if len(op) else "")
        if not len(g):
            return _r(tr("copiloto.zonas_sin_datos"), None, tr("copiloto.zonas_titulo"))
        dim_legible = i18n.t(f"columnas.{dim}", idioma)
        return _r(tr("copiloto.zonas_resumen", dim=dim_legible, top=g.iloc[0][dim],
                     venta_top=_m(g.iloc[0]["venta"], idioma), margen_top=_m(g.iloc[0]["margen_pct"], idioma, 1),
                     bottom=g.iloc[-1][dim], venta_bottom=_m(g.iloc[-1]["venta"], idioma), extra=extra),
                  g if not len(op) else op, tr("copiloto.zonas_titulo_dim", dim=dim_legible))

    if _tiene(t, "tipo_negocio", idioma):
        g = analitica.por_dimension(v, "tipo_negocio")
        if not len(g):
            return _r(tr("copiloto.tipo_negocio_sin_datos"), None, tr("copiloto.tipo_negocio_titulo"))
        return _r(tr("copiloto.tipo_negocio_resumen", tipo=g.iloc[0]["tipo_negocio"],
                     venta=_m(g.iloc[0]["venta"], idioma), n=g.iloc[0]["clientes"],
                     tipo_margen=g.sort_values("margen_pct").iloc[-1]["tipo_negocio"],
                     margen=_m(g["margen_pct"].max(), idioma, 1)),
                  g, tr("copiloto.tipo_negocio_titulo_lista"))

    # --- proveedores --------------------------------------------------------------
    if "proveedor" in t or "fornecedor" in t or "supplier" in t or "vendor" in t:
        g = analitica.por_dimension(v, "proveedor")
        if not len(g):
            return _r(tr("copiloto.proveedores_sin_datos"), None, tr("copiloto.proveedores_titulo"))
        rep = sugerencias.reposicion(productos, v, idioma=idioma)
        urgente = ""
        if len(rep):
            top_prov = rep.groupby("proveedor")["venta_en_riesgo"].sum().idxmax()
            urgente = tr("copiloto.proveedores_urgente", proveedor=top_prov,
                        compra=_m(rep[rep["proveedor"] == top_prov]["inversion"].sum(), idioma))
        return _r(tr("copiloto.proveedores_resumen", proveedor=g.iloc[0]["proveedor"],
                     venta=_m(g.iloc[0]["venta"], idioma), margen=_m(g.iloc[0]["margen_pct"], idioma, 1),
                     urgente=urgente),
                  g, tr("copiloto.proveedores_titulo_lista"))

    # --- venta de un producto puntual ----------------------------------------------
    if _tiene(t, "venta_puntual", idioma):
        prods = _buscar_producto(pregunta, productos, idioma)
        if len(prods):
            mp = analitica.margen_por_producto(v)
            m = (prods[["sku", "nombre", "categoria", "precio", "stock"]]
                 .merge(mp[["sku", "venta", "margen", "margen_pct", "unidades"]],
                        on="sku", how="left").fillna(0)
                 .sort_values("venta", ascending=False))
            tot_v, tot_u = m["venta"].sum(), m["unidades"].sum()
            x = m.iloc[0]
            sujeto = (tr("copiloto.venta_producto_uno") if len(m) == 1
                     else tr("copiloto.venta_producto_varios", n=len(m)))
            extra = tr("copiloto.venta_producto_extra", nombre=x["nombre"]) if len(m) > 1 else ""
            return _r(tr("copiloto.venta_producto_resumen", sujeto=sujeto,
                         unidades=_m(tot_u, idioma), venta=_m(tot_v, idioma), extra=extra),
                      m.head(30), tr("copiloto.venta_producto_titulo"))

    # --- clientes ----------------------------------------------------------------
    if _tiene(t, "clientes", idioma):
        if _tiene(t, "clientes_inactivos", idioma):
            rec = sugerencias.recupero_clientes(v, clientes, idioma)
            if not len(rec):
                return _r(tr("copiloto.clientes_sin_inactivos"), None, tr("copiloto.clientes_titulo"))
            lista = "; ".join(tr("copiloto.clientes_item", nombre=x.get("nombre", x["cliente_id"]),
                                 dias=x["dias_sin_comprar"]) for _, x in rec.head(3).iterrows())
            return _r(tr("copiloto.clientes_resumen", n=len(rec),
                         venta=_m(rec["venta_historica"].sum(), idioma), lista=lista),
                      rec, tr("copiloto.clientes_titulo_recuperar"))
        tc = analitica.top_clientes(v, _n(t, 15))
        return _r(tr("copiloto.clientes_top_resumen", n=len(tc), venta=_m(tc["venta"].sum(), idioma),
                     pedidos=tc.iloc[0]["pedidos"], venta_top=_m(tc.iloc[0]["venta"], idioma)),
                  tc, tr("copiloto.clientes_top_titulo"))

    # --- ventas / resumen ----------------------------------------------------------
    if _tiene(t, "ventas", idioma):
        if _tiene(t, "tendencia", idioma):
            tm = analitica.tendencia_mensual(v)
            delta = (tm.iloc[-1]["venta"] / tm.iloc[-2]["venta"] - 1) * 100 if len(tm) > 1 else 0
            return _r(tr("copiloto.tendencia_resumen", venta=_m(tm.iloc[-1]["venta"], idioma),
                         delta=f"{delta:+.1f}", margen=_m(tm.iloc[-1]["margen_pct"], idioma, 1)),
                      tm, tr("copiloto.tendencia_titulo"))
        mp = analitica.margen_por_producto(v, top=_n(t, 10))
        k = analitica.kpis(productos, v)
        return _r(tr("copiloto.ventas_resumen", venta=_m(k["venta_periodo"], idioma),
                     margen=_m(k["margen_pct"], idioma, 1), margen_monto=_m(k["margen_periodo"], idioma),
                     n=k["clientes_activos"], nombre=mp.iloc[0]["nombre"],
                     venta_top=_m(mp.iloc[0]["venta"], idioma)),
                  mp, tr("copiloto.ventas_titulo"))

    # --- fallback: resumen ejecutivo -------------------------------------------------
    paq = sugerencias.generar_todas({"productos": productos, "clientes": clientes,
                                     "ventas": v}, idioma)
    res = paq["resumen"]
    return _r(tr("copiloto.fallback_resumen", capital=_m(res["capital_liberable"], idioma),
                 riesgo=_m(res["venta_en_riesgo"], idioma), extra=_m(res["margen_extra_mensual"], idioma)),
              None, tr("copiloto.fallback_titulo"))


# ---------------------------------------------------------------------------
# Condiciones compuestas (no una simple lista de palabras) — una por idioma
# porque la gramática de la pregunta cambia, no sólo el vocabulario.
# ---------------------------------------------------------------------------
def _tiene_precio_margen(t: str, idioma: str) -> bool:
    if idioma == "en":
        return "margin" in t or "price" in t or "profit" in t
    if idioma == "pt":
        return "margem" in t or "preco" in t or "rentab" in t
    return "margen" in t or "precio" in t or "rentab" in t


def _tiene_ajuste(t: str, idioma: str) -> bool:
    """¿Pide sugerencias de ajuste ("mejorar", "subir") en vez del precio de
    un producto puntual?"""
    palabras = {
        "es": ["mejorar", "subir", "suger", "bajo", "oportunidad"],
        "en": ["improve", "increase", "suggest", "low", "opportunity", "raise"],
        "pt": ["melhorar", "subir", "aumentar", "suger", "baixo", "oportunidade"],
    }
    return any(k in t for k in palabras.get(idioma, palabras["es"]))


def _es_ascendente(t: str, idioma: str) -> bool:
    """¿Pide los de PEOR margen/venta (ascendente) en vez de los mejores?"""
    palabras = {
        "es": ["peor", "menor", "bajo"],
        "en": ["worst", "lowest", "low"],
        "pt": ["pior", "menor", "baixo"],
    }
    return any(k in t for k in palabras.get(idioma, palabras["es"]))


def _tiene_stock(t: str, idioma: str) -> bool:
    if idioma == "en":
        return ("stock" in t or "inventory" in t
                or ("how much" in t and ("is there" in t or "left" in t)))
    if idioma == "pt":
        return ("estoque" in t
                or ("quanto" in t and ("tem" in t or "sobra" in t or "resta" in t)))
    return ("stock" in t or ("cuanto" in t and ("hay" in t or "queda" in t))
            or "existencia" in t)


def _r(respuesta: str, tabla, titulo: str) -> dict:
    return {"respuesta": respuesta, "tabla": tabla, "titulo": titulo}


def _redactar_con_ia(pregunta: str, r: dict, idioma: str = "es") -> str | None:
    """Si hay API key, Claude redacta mejor la MISMA información (los números
    calculados van como contexto y son la única fuente permitida), en el
    idioma pedido."""
    from plania import config as pconfig
    key = os.environ.get("ANTHROPIC_API_KEY") or pconfig.leer_extra("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import requests
        contexto = r["respuesta"]
        if r["tabla"] is not None and len(r["tabla"]):
            contexto += "\n\nDatos (primeras filas):\n" + r["tabla"].head(12).to_string()
        plantilla = _PROMPT_IA.get(idioma, _PROMPT_IA["es"])
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODELO, "max_tokens": 400, "messages": [{
                "role": "user",
                "content": plantilla.format(pregunta=pregunta, contexto=contexto)}]},
            timeout=20)
        if resp.ok:
            return (resp.json().get("content") or [{}])[0].get("text") or None
    except Exception:
        pass
    return None
