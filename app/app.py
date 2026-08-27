# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Planificación logística y comercial inteligente — Dashboard
====================================================================
La aplicación que ve el cliente (web y PC: el instalador de Windows levanta
esto mismo embebido). Menú lateral profesional, demo de 7 días full
integrada, copiloto sobre datos reales y exportes PDF/Word/Excel.

Disponible en español, inglés y portugués (`plania/i18n.py` + selector en la
sidebar). El panel del dueño (`app/owner.py`) queda aparte, en español
únicamente: es una herramienta interna que nunca ve un cliente, no el
producto — ver el docstring de ese archivo.

    streamlit run app/app.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

# pandas 3 + pyarrow: los strings Arrow-backed pueden segfaultear al insertar
# columnas dentro del thread del ScriptRunner de Streamlit (reproducido en
# Linux con pandas 3.0/pyarrow 25). Storage "python" lo evita con costo
# marginal para volúmenes de PyME.
pd.set_option("mode.string_storage", "python")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from plania import analitica, apariencia, catalogo, conectores, copiloto, exportes, i18n, licencia, rutas, sugerencias  # noqa: E402
from plania import config as pconfig  # noqa: E402

pconfig.aplicar()

# ---------------------------------------------------------------------------
# Idioma — se resuelve antes que cualquier otra cosa porque `st.set_page_config`
# (el título de la pestaña) tiene que ser el primer comando de Streamlit.
#
# Un `IDIOMA` de nivel de script y no una variable de módulo de `plania/i18n.py`
# a propósito: Streamlit re-ejecuta este archivo entero en cada interacción,
# así que esto se comporta como una variable local de la corrida (igual que
# `lic` o `datos` más abajo), no como estado global que pueda mezclar el
# idioma de una sesión con el de otra si el servidor atiende varias a la vez.
# ---------------------------------------------------------------------------
if "idioma" not in st.session_state:
    st.session_state.idioma = i18n.idioma_guardado()
IDIOMA = st.session_state.idioma


def t(clave: str, **kw) -> str:
    return i18n.t(clave, IDIOMA, **kw)


# ---------------------------------------------------------------------------
# Estilo de marca
# ---------------------------------------------------------------------------
AZUL = "#1F3D7A"
CELESTE = "#2E86DE"
VERDE = "#20BF6B"
NARANJA = "#F39C12"
ROJO = "#E74C3C"

st.set_page_config(page_title=t("app.pagina_titulo"),
                   page_icon=os.path.join(RAIZ, "assets", "brand", "plania_icon.png"), layout="wide",
                   initial_sidebar_state="expanded")

st.markdown(f"""
<style>
  {apariencia.css_programa()}
  .block-container {{ padding-top: 1.4rem; max-width: 1240px; }}
  h1, h2, h3 {{ letter-spacing: -0.015em; }}

  /* ---- Sidebar corporativo ---- */
  section[data-testid="stSidebar"] {{
      background: linear-gradient(180deg, {AZUL} 0%, #14264a 100%);
      border-right: 1px solid rgba(255,255,255,.06);
  }}
  section[data-testid="stSidebar"] * {{ color: #E8EEF9 !important; }}
  .plania-logo {{
      font-weight: 800; font-size: 1.5rem; letter-spacing: .14em;
      color: #FFFFFF; margin: 4px 0 0 0;
  }}
  .plania-logo span {{ color: {CELESTE}; }}
  /* El menú es un st.radio, pero el círculo de "opción marcada" lo hace ver
     como un formulario, no como la navegación de un producto. Se oculta el
     control y se deja solo el texto con su barra de selección. */
  section[data-testid="stSidebar"] .stRadio [data-testid="stWidgetLabel"] {{ display: none; }}
  /* El círculo del radio. La estructura real es
         label[data-testid=stRadioOption] > div > div > [círculo] + [texto]
     y se apunta anclando en el data-testid, que es estable entre versiones,
     en vez de en las clases generadas (st-emotion-cache-…) que cambian. */
  section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div > div:first-child {{
      display: none !important;
  }}
  section[data-testid="stSidebar"] .stRadio label {{
      padding: 8px 14px; border-radius: 8px; width: 100%;
      font-size: .93rem; font-weight: 500; margin-bottom: 1px;
      border-left: 3px solid transparent; transition: background .15s;
  }}
  section[data-testid="stSidebar"] .stRadio label:hover {{
      background: rgba(255,255,255,.07);
  }}
  section[data-testid="stSidebar"] .stRadio label[data-checked="true"],
  section[data-testid="stSidebar"] .stRadio label:has(input:checked) {{
      background: rgba(46,134,222,.18); border-left-color: {CELESTE};
  }}

  /* ---- Componentes ---- */
  .plania-badge {{
      background: {CELESTE}; color: white; border-radius: 6px;
      padding: 3px 12px; font-size: .5em; vertical-align: middle;
      letter-spacing: .1em; font-weight: 600;
  }}
  .plania-demo {{
      background: #FFF6E5; color: #6b4a00; border: 1px solid #F1D18E;
      border-left: 4px solid {NARANJA};
      border-radius: 8px; padding: 12px 16px; font-weight: 500;
      margin-bottom: 12px;
  }}
  /* Altura pareja: sin esto, la tarjeta que trae variación (↑24,1%) queda
     más alta que las otras cuatro y la fila se ve desprolija. */
  div[data-testid="stMetric"] {{
      background: #FFFFFF; border: 1px solid #E3E8F2;
      border-radius: 10px; padding: 14px 16px; height: 100%;
      box-shadow: 0 1px 3px rgba(16,30,60,.06);
  }}
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
      font-size: 1.9rem; font-weight: 700; color: #142848;
  }}
  div[data-testid="stMetric"] > div {{ overflow-wrap: anywhere; }}
  div[data-testid="stMetric"] label {{ color: #5A6B85 !important; font-weight: 500; }}
  .stChatMessage {{ border-radius: 10px; }}
  button[kind="primary"] {{ border-radius: 8px; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# Selector de idioma. Va temprano y suelto (no dentro de `with st.sidebar:`)
# para que aparezca en la sidebar incluso durante la pantalla de la EULA, que
# más abajo corta la ejecución con `st.stop()` antes de llegar al resto de la
# sidebar — sin esto, alguien que no lee español quedaba sin forma de pasar
# la EULA a otro idioma.
_elegido = st.sidebar.selectbox(
    t("app.idioma_label"), i18n.IDIOMAS, index=i18n.IDIOMAS.index(IDIOMA),
    format_func=lambda i: i18n.NOMBRES_IDIOMA[i])
if _elegido != IDIOMA:
    i18n.establecer_idioma(_elegido)
    st.session_state.idioma = _elegido
    st.rerun()

# ---------------------------------------------------------------------------
# Aceptación de la EULA — antes de cualquier pantalla con datos, incluida la
# demo. Se pide una sola vez por instalación (queda guardada en la config
# segura, igual que la licencia) y de nuevo si EULA_VERSION sube.
#
# El TEXTO del acuerdo (`LICENSE-EULA.md`) se muestra siempre en español,
# cualquiera sea el idioma elegido: es un documento legal, y traducir un
# contrato no es lo mismo que traducir una pantalla — necesita revisión
# legal en cada idioma antes de mostrarse como válido, algo que excede este
# cambio. Lo que sí está en el idioma elegido es todo el resto: el título,
# el aviso, el checkbox y el botón.
# ---------------------------------------------------------------------------
if not licencia.eula_aceptada():
    st.markdown("<div class='plania-logo'>PLAN<span>IA</span></div>", unsafe_allow_html=True)
    st.subheader(t("eula.titulo"))
    st.caption(t("eula.subtitulo"))
    _eula_path = os.path.join(RAIZ, "LICENSE-EULA.md")
    with st.container(height=420, border=True):
        if os.path.exists(_eula_path):
            st.markdown(open(_eula_path, encoding="utf-8").read())
        else:
            st.error(t("eula.sin_archivo"))
    aceptar = st.checkbox(t("eula.checkbox"))
    if st.button(t("comun.continuar"), type="primary", disabled=not aceptar):
        licencia.aceptar_eula()
        st.rerun()
    st.stop()


# ---------------------------------------------------------------------------
# Datos: ERP conectado o demo — cacheado
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="…")
def _cargar(url: str | None, tablas_key: str) -> dict:
    tablas = st.session_state.get("tablas_erp") or None
    return conectores.cargar_datos(url=url or None, tablas=tablas)


def cargar_datos() -> dict | None:
    url = st.session_state.get("erp_url") or pconfig.leer_extra("ERP_DB_URL") or ""
    try:
        if not url and not os.path.exists(os.path.join(RAIZ, "data", "erp_demo.db")):
            import data.generate_dataset as gen
            gen.main()
            _cargar.clear()
        return _cargar(url, str(st.session_state.get("tablas_erp")))
    except Exception as e:
        st.error(t("errores.no_pude_leer_datos", error=e))
        return None


def _miles(n: float, decimales: int = 0) -> str:
    return i18n.miles(n, decimales, IDIOMA)


def _fmt(n: float) -> str:
    return i18n.fmt_monto(n, IDIOMA)


# Nombres de columna que ve el cliente, en el idioma activo. Las claves son
# los nombres canónicos internos: mostrar `cliente_id` o `ultima_compra` en
# pantalla es enseñarle al cliente el modelo de datos, no su negocio. Se
# arma desde el catálogo de `plania/i18n.py` — la lista de claves es la unión
# de todo lo que devuelven `sugerencias.py`, `analitica.py` y `rutas.py`.
_COLUMNAS_INTERNAS = (
    "sku", "nombre", "categoria", "proveedor", "costo", "precio", "stock",
    "stock_min", "lead_time_dias", "cliente_id", "tipo_negocio", "departamento",
    "zona", "venta", "margen", "margen_pct", "pedidos", "ultima_compra",
    "unidades", "cantidad", "fecha", "precio_unit", "costo_unit", "rotacion",
    "dias_stock", "capital_inmovilizado", "descuento_sugerido", "precio_oferta",
    "venta_id", "dias_sin_comprar", "motivo", "venta_en_riesgo",
    "cantidad_sugerida", "inversion", "margen_extra_mensual", "venta_potencial",
    "dias_sin_usar", "descuento_pct", "precio_sugerido", "suba_pct",
    "margen_obj", "venta_historica", "penetracion_zona_pct",
    "penetracion_general_pct", "clientes_zona", "vehiculo", "paradas",
    "km_estimados", "horas_estimadas", "orden", "clientes", "venta_diaria",
)
ETIQUETAS = {c: t(f"columnas.{c}") for c in _COLUMNAS_INTERNAS}

# Plotly rotula los ejes con el nombre de la columna: "venta", "margen_pct",
# "categoria". Al cliente hay que mostrarle el nombre de su negocio, no el de
# la columna — se reusan las mismas ETIQUETAS de las tablas para que un
# concepto se llame igual en todos lados.
ETIQUETAS_GRAFICO = dict(ETIQUETAS, mes=t("columnas.mes"), lat=t("columnas.lat"),
                         lon=t("columnas.lon"))


def _ejes(fig):
    """Deja el gráfico con nombres legibles y sin ruido visual."""
    fig.for_each_xaxis(lambda a: a.update(
        title_text=ETIQUETAS_GRAFICO.get(a.title.text, a.title.text or "")))
    fig.for_each_yaxis(lambda a: a.update(
        title_text=ETIQUETAS_GRAFICO.get(a.title.text, a.title.text or "")))
    if fig.layout.coloraxis and fig.layout.coloraxis.colorbar:
        tt = fig.layout.coloraxis.colorbar.title.text
        if tt:
            fig.layout.coloraxis.colorbar.title.text = ETIQUETAS_GRAFICO.get(tt, tt)
    fig.update_layout(
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12,
                  color="#33415C"),
        title_font=dict(size=15, color="#142848"),
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        legend=dict(title_text=""),
    )
    fig.update_xaxes(gridcolor="#EEF2F8", zeroline=False)
    fig.update_yaxes(gridcolor="#EEF2F8", zeroline=False)
    return fig


def _tabla(df: pd.DataFrame, **kw):
    """Muestra una tabla con formato de producto, no de volcado de base.

    Renombra las columnas al idioma activo, muestra los importes con el
    separador de miles de ese idioma y las fechas sin la hora. Es una sola
    función y no formato caso por caso para que ninguna pantalla se olvide y
    quede mostrando `315742.95` junto a otra que muestra `$315.743`.
    """
    if df is None or len(df) == 0:
        st.caption(t("tabla.sin_datos"))
        return

    vista = df.copy()
    for col in vista.columns:
        serie = vista[col]
        if str(serie.dtype).startswith("datetime"):
            vista[col] = serie.dt.strftime("%d/%m/%Y")
        elif serie.dtype.kind == "f":
            # Los porcentajes ya vienen en su escala; el resto son pesos.
            dec = 1 if "pct" in col or "rotacion" in col or "dias" in col else 0
            vista[col] = serie.map(lambda v, d=dec: "" if pd.isna(v) else _miles(v, d))
    vista = vista.rename(columns={c: ETIQUETAS.get(c, c.replace("_", " ").capitalize())
                                  for c in vista.columns})
    st.dataframe(vista, width="stretch", hide_index=True, **kw)


# ---------------------------------------------------------------------------
# Sidebar: marca + menú + estado de licencia
# ---------------------------------------------------------------------------
lic = licencia.estado()

MENU_CLAVES = ["inicio", "panel_ejecutivo", "stock", "precios", "zonas",
              "rutas", "ofertas", "copiloto", "conectar_erp", "planes",
              "configuracion", "ayuda"]
MENU = [t(f"menu.{c}") for c in MENU_CLAVES]
_MENU_POR_ETIQUETA = dict(zip(MENU, MENU_CLAVES))

with st.sidebar:
    st.markdown("<div class='plania-logo'>PLAN<span>IA</span></div>",
                unsafe_allow_html=True)
    st.caption(t("app.eslogan"))
    st.markdown("---")
    pagina_clave = _MENU_POR_ETIQUETA[st.radio(t("menu.label"), MENU,
                                               label_visibility="collapsed")]
    st.markdown("---")
    if lic["modo"] == "demo":
        st.markdown(t("licencia.demo_full",
                      horas=lic.get("horas_restantes", lic["dias_restantes"] * 24)))
        st.progress(min(1.0, lic.get("horas_restantes", licencia.DIAS_DEMO * 24) / (licencia.DIAS_DEMO * 24)))
    elif lic["modo"] == "licencia":
        st.markdown(t("licencia.plan_activo", plan=lic["plan"], dias=lic["dias_restantes"]))
    else:
        st.markdown(t("licencia.demo_vencida_sidebar"))
    fuente = (t("fuente.erp_conectado") if (st.session_state.get("erp_url")
                                            or pconfig.leer_extra("ERP_DB_URL"))
             else t("fuente.base_demo"))
    st.caption(t("fuente.etiqueta", fuente=fuente))

# `pagina` es la clave interna estable (p.ej. "panel_ejecutivo"), no el texto
# traducido — todo el resto del archivo compara contra esta clave, así que
# cambiar de idioma no puede romper la navegación ni los `if pagina == ...`.
pagina = pagina_clave

BLOQUEADA = lic["modo"] == "vencida" and pagina not in (
    "inicio", "planes", "ayuda", "configuracion")
if BLOQUEADA:
    st.warning(t("licencia.demo_terminada"))
    st.stop()

datos = None
if pagina not in ("planes", "configuracion", "ayuda", "conectar_erp"):
    datos = cargar_datos()


# ---------------------------------------------------------------------------
# Filtros por categoría
# ---------------------------------------------------------------------------
# Las categorías NO están escritas acá: salen de los datos del cliente
# (`catalogo.columnas_categoricas` las detecta por cardinalidad). Una lista
# fija de rubros sería adivinar el negocio del cliente; así, un distribuidor
# de bebidas filtra por sus marcas y una ferretería por sus rubros, sin que
# nadie configure nada.
PAGINAS_CON_FILTRO = ("panel_ejecutivo", "stock", "precios", "zonas",
                      "ofertas", "rutas")


def _filtrar(d: dict) -> tuple[dict, list[str]]:
    """Aplica los filtros elegidos en la barra lateral. Devuelve (datos, activos).

    Filtrar productos o clientes arrastra las ventas de esos productos o esos
    clientes. Si no, los KPI quedarían incoherentes: la venta seguiría siendo
    la del negocio entero mientras el stock sería el de una sola categoría, y
    el margen resultante no significaría nada.
    """
    if not d:
        return d, []

    productos, clientes, ventas = d["productos"], d["clientes"], d["ventas"]
    activos: list[str] = []

    with st.sidebar:
        st.markdown(t("filtros.titulo"))
        for entidad, etiqueta in (("productos", t("filtros.producto")),
                                  ("clientes", t("filtros.cliente"))):
            base = d[entidad]
            for col in catalogo.columnas_categoricas(base):
                opciones = catalogo.valores_de(base, col)
                if len(opciones) < 2:
                    continue
                col_legible = ETIQUETAS.get(col, col.replace("_", " "))
                sel = st.multiselect(f"{etiqueta} · {col_legible}",
                                     opciones, default=[], placeholder=t("comun.elegir"),
                                     key=f"filtro_{entidad}_{col}")
                if not sel:
                    continue
                activos.append(f"{col_legible}: {', '.join(str(s) for s in sel[:3])}"
                               + ("…" if len(sel) > 3 else ""))
                if entidad == "productos":
                    productos = productos[productos[col].isin(sel)]
                else:
                    clientes = clientes[clientes[col].isin(sel)]

        if activos:
            if st.button(t("filtros.limpiar"), width="stretch"):
                for k in [k for k in st.session_state if k.startswith("filtro_")]:
                    st.session_state[k] = []
                st.rerun()

    if len(productos) < len(d["productos"]):
        ventas = ventas[ventas["sku"].isin(productos["sku"])]
    if len(clientes) < len(d["clientes"]) and "cliente_id" in ventas.columns:
        ventas = ventas[ventas["cliente_id"].isin(clientes["cliente_id"])]

    return {"productos": productos, "clientes": clientes, "ventas": ventas}, activos


FILTROS_ACTIVOS: list[str] = []
if datos and pagina in PAGINAS_CON_FILTRO:
    datos, FILTROS_ACTIVOS = _filtrar(datos)
    if FILTROS_ACTIVOS and datos["ventas"].empty:
        st.warning(t("filtros.sin_datos"))


def _aviso_filtros() -> None:
    """Deja a la vista que lo de abajo es un recorte, no el negocio entero.

    Un panel filtrado que no lo dice lleva a decisiones equivocadas: el
    encargado ve 'venta 30 días' y cree que es la del negocio.
    """
    if FILTROS_ACTIVOS:
        st.info(t("filtros.info_prefijo", lista=" · ".join(FILTROS_ACTIVOS)))


def _ventas_enriquecidas(d: dict) -> pd.DataFrame:
    return analitica.enriquecer_ventas(d["ventas"], d["productos"], d["clientes"])


def _botones_export(clave: str, secciones: list, etiqueta: str | None = None):
    """Botones de descarga PDF / Word / Excel para cualquier tabla o informe."""
    if not licencia.tiene("exportes"):
        st.caption(t("exportes.solo_pagos"))
        return
    titulo = secciones[0][0] if secciones else t("comun.informe_default")
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    c1.download_button(t("comun.pdf"), exportes.a_pdf(titulo, secciones, IDIOMA),
                       file_name=f"plania_{clave}.pdf", key=f"pdf_{clave}",
                       mime="application/pdf")
    c2.download_button(t("comun.word"), exportes.a_word(titulo, secciones, IDIOMA),
                       file_name=f"plania_{clave}.docx", key=f"docx_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document")
    c3.download_button(t("comun.excel"), exportes.a_excel(secciones, IDIOMA),
                       file_name=f"plania_{clave}.xlsx", key=f"xlsx_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
if pagina == "inicio":
    st.markdown(f"# Plania <span class='plania-badge'>{t('app.badge_inicio')}</span>",
                unsafe_allow_html=True)
    if lic["modo"] == "demo":
        st.markdown(f"<div class='plania-demo'>"
                    + t("inicio.banner_demo",
                        horas=lic.get("horas_restantes", licencia.DIAS_DEMO * 24))
                    + "</div>", unsafe_allow_html=True)
    st.markdown(t("inicio.intro"))
    if datos:
        v = _ventas_enriquecidas(datos)
        k = analitica.kpis(datos["productos"], v)
        paq = sugerencias.generar_todas(datos, idioma=IDIOMA)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(t("inicio.kpi_venta30"), _fmt(k["venta_periodo"]))
        c2.metric(t("inicio.kpi_margen"), f"{k['margen_pct']:.1f}%")
        c3.metric(t("inicio.kpi_capital_liberable"), _fmt(paq["resumen"]["capital_liberable"]))
        c4.metric(t("inicio.kpi_venta_riesgo"), _fmt(paq["resumen"]["venta_en_riesgo"]))
        st.info(t("inicio.ayuda_inicio"))

elif pagina == "panel_ejecutivo":
    st.title(t("menu.panel_ejecutivo"))
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        k = analitica.kpis(datos["productos"], v)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric(t("panel.kpi_venta30"), _fmt(k["venta_periodo"]))
        c2.metric(t("panel.kpi_margen30"), _fmt(k["margen_periodo"]), f"{k['margen_pct']:.1f}%")
        c3.metric(t("panel.kpi_valor_stock"), _fmt(k["valor_stock"]))
        c4.metric(t("panel.kpi_quiebres"), f"{k['quiebres']} / {k['bajo_minimo']}")
        c5.metric(t("panel.kpi_clientes_activos"), k["clientes_activos"])
        st.markdown("---")
        col1, col2 = st.columns([3, 2])
        tm = analitica.tendencia_mensual(v)
        fig = px.area(tm, x="mes", y="venta", title=t("panel.grafico_venta_mensual"),
                      color_discrete_sequence=[CELESTE])
        fig.update_layout(margin=dict(t=40, b=0), height=320)
        col1.plotly_chart(_ejes(fig), width="stretch")
        g = analitica.por_dimension(v, "categoria")
        fig2 = px.bar(g, x="venta", y="categoria", orientation="h",
                      title=t("panel.grafico_venta_categoria"), color="margen_pct",
                      color_continuous_scale=["#E74C3C", "#F39C12", "#20BF6B"])
        fig2.update_layout(margin=dict(t=40, b=0), height=320)
        col2.plotly_chart(_ejes(fig2), width="stretch")
        st.markdown(t("panel.top_clientes"))
        _tabla(analitica.top_clientes(v))

elif pagina == "stock":
    st.title(t("menu.stock"))
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        r = analitica.rotacion(datos["productos"], v)
        c1, c2, c3 = st.columns(3)
        c1.metric(t("stock.kpi_skus"), len(r))
        c2.metric(t("stock.kpi_quiebres"), int((r["stock"] <= 0).sum()))
        c3.metric(t("stock.kpi_sobrestock"), int((r["dias_stock"] > 90).sum()))
        tab1, tab2 = st.tabs([t("stock.tab_reposicion"), t("stock.tab_completo")])
        with tab1:
            rep = sugerencias.reposicion(datos["productos"], v, idioma=IDIOMA)
            if len(rep):
                _tabla(rep)
                _botones_export("reposicion", [(t("menu.stock"),
                                                exportes.titulo_seccion("reposicion", IDIOMA)[1], rep)])
            else:
                st.success(t("stock.sin_riesgo"))
        with tab2:
            filtro = st.multiselect(t("comun.categoria"),
                                    sorted(r["categoria"].dropna().unique()),
                                    placeholder=t("comun.elegir"))
            rr = r[r["categoria"].isin(filtro)] if filtro else r
            _tabla(rr.drop(columns=["venta_diaria"]).assign(
                dias_stock=rr["dias_stock"].replace([float("inf")], 999).round(0)))

elif pagina == "precios":
    st.title(t("menu.precios"))
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        mp = analitica.margen_por_producto(v)
        c1, c2 = st.columns(2)
        c1.metric(t("precios.kpi_margen_prom"),
                  f"{v['margen'].sum() / v['venta'].sum() * 100:.1f}%")
        pr = sugerencias.precios(datos["productos"], v, idioma=IDIOMA)
        c2.metric(t("precios.kpi_margen_extra"),
                  _fmt(pr["margen_extra_mensual"].sum() if len(pr) else 0) + t("comun.sufijo_mes"))
        fig = px.scatter(mp, x="venta", y="margen_pct", color="categoria",
                         hover_name="nombre", title=t("precios.grafico_titulo"),
                         labels={"venta": t("precios.eje_venta"),
                                "margen_pct": t("precios.eje_margen")})
        fig.update_layout(height=380, margin=dict(t=40, b=0))
        st.plotly_chart(_ejes(fig), width="stretch")
        st.markdown(t("precios.subtitulo_sugerencias"))
        if len(pr):
            _tabla(pr)
            _botones_export("precios", [(t("menu.precios"),
                                         exportes.titulo_seccion("precios", IDIOMA)[1], pr)])
        else:
            st.success(t("precios.alineados"))

elif pagina == "zonas":
    st.title(t("zonas.titulo"))
    if datos:
        v = _ventas_enriquecidas(datos)
        # `dim` es la clave interna estable ("zona"/"departamento"/
        # "tipo_negocio"), la misma que el nombre de columna del DataFrame —
        # `format_func` sólo cambia lo que se ve, nunca lo que se compara.
        dim = st.radio(t("zonas.ver_por"), ["zona", "departamento", "tipo_negocio"],
                       format_func=lambda k: ETIQUETAS.get(k, k), horizontal=True)
        g = analitica.por_dimension(v, dim)
        if len(g):
            col1, col2 = st.columns([3, 2])
            fig = px.bar(g.head(15), x="venta", y=dim, orientation="h",
                         color="margen_pct",
                         title=t("zonas.grafico_venta_por", dim=ETIQUETAS.get(dim, dim)),
                         color_continuous_scale=["#E74C3C", "#F39C12", "#20BF6B"])
            fig.update_layout(height=420, margin=dict(t=40, b=0))
            col1.plotly_chart(_ejes(fig), width="stretch")
            col2.dataframe(g.rename(columns=ETIQUETAS), width="stretch", hide_index=True)
        st.markdown(t("zonas.oportunidades_titulo"))
        op = sugerencias.oportunidades_zona(v, idioma=IDIOMA)
        if len(op):
            _tabla(op)
            _botones_export("zonas", [(t("menu.zonas"),
                                       exportes.titulo_seccion("zonas", IDIOMA)[1], op)])
        else:
            st.info(t("zonas.sin_brechas"))

elif pagina == "rutas":
    st.title(t("menu.rutas"))
    _aviso_filtros()
    if not licencia.tiene("rutas"):
        st.warning(t("rutas.no_incluido"))
    elif datos:
        v = _ventas_enriquecidas(datos)
        clientes = datos["clientes"]
        c1, c2, c3 = st.columns(3)
        vehiculos = c1.number_input(t("rutas.vehiculos"), 1, 20, 2)
        paradas = c2.number_input(t("rutas.paradas_max"), 5, 60, 25)
        deptos = c3.multiselect(t("comun.departamento"),
                                sorted(clientes["departamento"].dropna().unique()),
                                placeholder=t("comun.elegir"))
        base = clientes[clientes["departamento"].isin(deptos)] if deptos else clientes
        # Igual que `dim` en Zonas: se navega por una clave interna estable
        # ("activos"/"inactivos"/"todos") y `format_func` traduce sólo lo que
        # se ve. Antes el código comparaba con `"inactivos" in modo` sobre el
        # TEXTO ya traducido — funcionaba de casualidad en español y se
        # rompía en cualquier otro idioma, porque "Inactive customers" no
        # contiene "inactivos".
        modo = st.radio(t("rutas.a_quien_visitar"), ["activos", "inactivos", "todos"],
                        format_func=lambda k: t(f"rutas.modo_{k}"), horizontal=True)
        if modo == "inactivos":
            objetivo = base.merge(
                analitica.clientes_inactivos(v, base)[["cliente_id"]], on="cliente_id")
        elif modo == "activos":
            corte = v["fecha"].max() - pd.Timedelta(days=30)
            act = v[v["fecha"] > corte]["cliente_id"].unique()
            objetivo = base[base["cliente_id"].isin(act)]
        else:
            objetivo = base
        st.caption(t("rutas.contador", n=len(objetivo)))
        if len(objetivo) and st.button(t("rutas.planificar_boton"), type="primary"):
            plan = rutas.planificar(objetivo, vehiculos=int(vehiculos),
                                    paradas_max=int(paradas))
            _tabla(plan["resumen"])
            if {"lat", "lon"}.issubset(plan["rutas"].columns):
                figm = px.scatter_map(plan["rutas"], lat="lat", lon="lon",
                                      color=plan["rutas"]["vehiculo"].astype(str),
                                      hover_name="nombre", zoom=10, height=420,
                                      title=t("rutas.grafico_paradas"))
                figm.update_layout(margin=dict(t=40, b=0))
                st.plotly_chart(figm, width="stretch")
            _tabla(plan["rutas"])
            _botones_export("rutas", [(t("rutas.hoja_titulo"),
                                       t("rutas.hoja_descripcion"), plan["rutas"])])

elif pagina == "ofertas":
    st.title(t("menu.ofertas"))
    _aviso_filtros()
    if datos:
        paq = sugerencias.generar_todas(datos, idioma=IDIOMA)
        res = paq["resumen"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(t("ofertas.kpi_capital_liberable"), _fmt(res["capital_liberable"]))
        c2.metric(t("ofertas.kpi_venta_riesgo"), _fmt(res["venta_en_riesgo"]))
        c3.metric(t("ofertas.kpi_margen_extra_mes"), _fmt(res["margen_extra_mensual"]))
        c4.metric(t("ofertas.kpi_potencial_zonas"), _fmt(res["venta_potencial_zonas"]))
        st.markdown("---")
        secciones = exportes.secciones_desde_paquete(paq, idioma=IDIOMA)
        _botones_export("paquete_completo", secciones,
                        etiqueta=t("ofertas.exportar_completo"))
        tabs_claves = ["ofertas", "reposicion", "precios", "zonas", "recupero"]
        tabs = st.tabs([t(f"ofertas.tab_{c}") for c in tabs_claves])
        for tab, clave in zip(tabs, tabs_claves):
            with tab:
                df = paq[clave]
                if df is not None and len(df):
                    st.caption(exportes.titulo_seccion(clave, IDIOMA)[1])
                    _tabla(df)
                else:
                    st.success(t("ofertas.nada_para_accionar"))

elif pagina == "copiloto":
    st.title(t("copiloto.titulo"))
    if not licencia.tiene("copiloto"):
        st.warning(t("copiloto.no_incluido"))
    elif datos:
        st.caption(t("copiloto.ejemplos"))
        if "chat" not in st.session_state:
            st.session_state.chat = []
        for m in st.session_state.chat:
            with st.chat_message(m["rol"]):
                st.markdown(m["texto"])
                if m.get("tabla") is not None:
                    _tabla(m["tabla"])
        pregunta = st.chat_input(t("copiloto.placeholder"))
        if pregunta:
            st.session_state.chat.append({"rol": "user", "texto": pregunta})
            with st.chat_message("user"):
                st.markdown(pregunta)
            with st.chat_message("assistant"):
                with st.spinner(t("copiloto.calculando")):
                    r = copiloto.responder(pregunta, datos, idioma=IDIOMA)
                st.markdown(r["respuesta"])
                if r["tabla"] is not None and len(r["tabla"]):
                    _tabla(r["tabla"])
                    _botones_export(f"copiloto_{len(st.session_state.chat)}",
                                    [(r["titulo"], r["respuesta"], r["tabla"])])
            st.session_state.chat.append({"rol": "assistant", "texto": r["respuesta"],
                                          "tabla": r["tabla"]})

elif pagina == "conectar_erp":
    st.title(t("conectar.titulo"))
    st.markdown(t("conectar.intro"))
    tab1, tab2 = st.tabs([t("conectar.tab_sql"), t("conectar.tab_archivos")])
    with tab1:
        url = st.text_input(t("conectar.url_conexion"),
                            value=pconfig.leer_extra("ERP_DB_URL") or "",
                            placeholder="postgresql://usuario:clave@servidor:5432/erp")
        c1, c2 = st.columns(2)
        if c1.button(t("conectar.probar_conexion"), type="primary"):
            try:
                eng = conectores.conectar_sql(url)
                tablas = conectores.listar_tablas(eng)
                st.success(t("conectar.conectado", n=len(tablas),
                             lista=", ".join(tablas[:12]),
                             recorte="…" if len(tablas) > 12 else ""))
                auto = {e: conectores.autodescubrir_tabla(eng, e)
                        for e in ("productos", "clientes", "ventas")}
                st.json({t("conectar.mapeo_detectado",
                           entidad=t(f"conectar.entidad_{k}"), mapeo=""): v
                        or "—" for k, v in auto.items()})
                st.session_state.erp_url = url
            except Exception as e:
                st.error(t("conectar.no_conecto", error=e))
        if c2.button(t("conectar.guardar_y_usar")):
            pconfig.guardar_extra("ERP_DB_URL", url)
            st.session_state.erp_url = url
            _cargar.clear()
            st.success(t("conectar.guardado_ok"))
        with st.expander(t("conectar.elegir_tablas")):
            t_p = st.text_input(t("conectar.tabla_productos"), "")
            t_c = st.text_input(t("conectar.tabla_clientes"), "")
            t_v = st.text_input(t("conectar.tabla_ventas"), "")
            if st.button(t("conectar.usar_tablas")):
                st.session_state.tablas_erp = {k: v for k, v in
                                               {"productos": t_p, "clientes": t_c,
                                                "ventas": t_v}.items() if v}
                _cargar.clear()
                st.success(t("conectar.tablas_listo"))
    with tab2:
        st.caption(t("conectar.subir_archivos"))
        arch = {e: st.file_uploader(
                    t("conectar.archivo_de", entidad=t(f"conectar.entidad_{e}")),
                    type=["csv", "xlsx", "xls"], key=f"up_{e}")
                for e in ("productos", "ventas", "clientes")}
        if arch["productos"] and arch["ventas"]:
            try:
                nuevos = {}
                for e, f in arch.items():
                    if f is None:
                        nuevos[e] = pd.DataFrame(
                            columns=list(conectores.SINONIMOS["clientes"]))
                        continue
                    crudo = conectores.leer_archivo(f)
                    mapeo = conectores.autodetectar_mapeo(crudo, e)
                    st.caption(t("conectar.mapeo_detectado",
                                entidad=t(f"conectar.entidad_{e}"), mapeo=mapeo))
                    nuevos[e] = conectores.normalizar(crudo, e, mapeo)
                st.session_state.datos_archivo = nuevos
                st.dataframe(nuevos["productos"].head(), width="stretch")
                if st.button(t("conectar.usar_archivos"), type="primary"):
                    url_archivos = conectores.guardar_como_base(nuevos)
                    pconfig.guardar_extra("ERP_DB_URL", url_archivos)
                    st.session_state.erp_url = url_archivos
                    _cargar.clear()
                    st.success(t("conectar.archivos_listo"))
            except Exception as e:
                st.error(str(e))

elif pagina == "planes":
    st.title(t("planes.titulo"))
    backend = os.environ.get("PLANIA_BACKEND_URL",
                             pconfig.leer_extra("BACKEND_URL") or "http://localhost:8100")
    if lic["modo"] == "demo":
        st.markdown(f"<div class='plania-demo'>"
                    + t("planes.demo_activa",
                        horas=lic.get("horas_restantes", licencia.DIAS_DEMO * 24))
                    + "</div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    for col, (plan, titulo, precio, detalle) in zip((col1, col2, col3), [
        ("starter", t("planes.starter_nombre"), t("planes.starter_precio"),
         t("planes.starter_detalle")),
        ("pro", t("planes.pro_nombre"), t("planes.pro_precio"),
         t("planes.pro_detalle")),
        ("enterprise", t("planes.enterprise_nombre"), t("planes.enterprise_precio"),
         t("planes.enterprise_detalle")),
    ]):
        with col:
            st.markdown(f"### {titulo}")
            st.markdown(f"## {precio}")
            st.caption(detalle)
    st.markdown("---")
    email = st.text_input(t("planes.email_label"))
    plan_sel = st.selectbox(t("planes.plan_label"), ["starter", "pro"])
    if st.button(t("planes.pagar_mercadopago"), type="primary"):
        try:
            import requests
            r = requests.post(f"{backend}/checkout",
                              json={"plan": plan_sel, "email": email}, timeout=15)
            if r.ok:
                st.link_button(t("planes.ir_a_checkout"), r.json()["init_point"])
            else:
                st.error(r.json().get("detail", r.text))
        except Exception as e:
            st.error(t("planes.no_pude_contactar", backend=backend, error=e))
    st.markdown(t("planes.ya_tengo_licencia"))
    tok = st.text_input(t("planes.pegar_token"), type="password")
    if st.button(t("planes.activar_licencia")):
        r = licencia.activar_licencia(tok.strip())
        if r["ok"]:
            st.success(t("planes.licencia_activada", plan=r["claims"].get("plan")))
        else:
            st.error(r["error"])

elif pagina == "configuracion":
    st.title(t("configuracion.titulo"))
    st.caption(t("configuracion.guardado_seguro", backend=pconfig.backend_activo()))
    cfg = pconfig.cargar()
    with st.form("cfg"):
        nuevos = {}
        for clave in pconfig.CLAVES:
            desc = t(f"claves.{clave}")
            actual = cfg.get(clave, "")
            nuevos[clave] = st.text_input(
                desc, value="", placeholder=pconfig.enmascarar(actual) if actual
                else t("configuracion.sin_configurar"), type="password" if "KEY" in clave
                or "TOKEN" in clave or "PASSWORD" in clave else "default")
        if st.form_submit_button(t("comun.guardar"), type="primary"):
            cambios = {k: v for k, v in nuevos.items() if v.strip()}
            if cambios:
                pconfig.guardar(cambios)
                pconfig.aplicar()
                st.success(t("configuracion.guardado_ok", claves=", ".join(cambios)))
            else:
                st.info(t("configuracion.sin_valores_nuevos"))

else:  # ayuda
    st.title(t("ayuda.titulo"))
    st.markdown(t("ayuda.cuerpo"))
