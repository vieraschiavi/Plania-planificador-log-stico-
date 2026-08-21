# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Planificación logística y comercial inteligente — Dashboard
====================================================================
La aplicación que ve el cliente (web y PC: el instalador de Windows levanta
esto mismo embebido). Menú lateral profesional, demo de 7 días full
integrada, copiloto sobre datos reales y exportes PDF/Word/Excel.

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

from plania import analitica, apariencia, catalogo, conectores, copiloto, exportes, licencia, rutas, sugerencias  # noqa: E402
from plania import config as pconfig  # noqa: E402

pconfig.aplicar()

# ---------------------------------------------------------------------------
# Estilo de marca
# ---------------------------------------------------------------------------
AZUL = "#1F3D7A"
CELESTE = "#2E86DE"
VERDE = "#20BF6B"
NARANJA = "#F39C12"
ROJO = "#E74C3C"

st.set_page_config(page_title="Plania · Planificación Inteligente",
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

# ---------------------------------------------------------------------------
# Aceptación de la EULA — antes de cualquier pantalla con datos, incluida la
# demo. Se pide una sola vez por instalación (queda guardada en la config
# segura, igual que la licencia) y de nuevo si EULA_VERSION sube.
# ---------------------------------------------------------------------------
if not licencia.eula_aceptada():
    st.markdown("<div class='plania-logo'>PLAN<span>IA</span></div>", unsafe_allow_html=True)
    st.subheader("Términos de uso")
    st.caption("Hay que aceptarlos para continuar — es una sola vez.")
    _eula_path = os.path.join(RAIZ, "LICENSE-EULA.md")
    with st.container(height=420, border=True):
        if os.path.exists(_eula_path):
            st.markdown(open(_eula_path, encoding="utf-8").read())
        else:
            st.error("No se encontró LICENSE-EULA.md. Contactá a soporte antes de continuar.")
    aceptar = st.checkbox("Leí y acepto los términos de uso de Plania.")
    if st.button("Continuar", type="primary", disabled=not aceptar):
        licencia.aceptar_eula()
        st.rerun()
    st.stop()


# ---------------------------------------------------------------------------
# Datos: ERP conectado o demo — cacheado
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Leyendo datos del negocio…")
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
        st.error(f"No pude leer los datos: {e}")
        return None


def _miles(n: float, decimales: int = 0) -> str:
    """Número con separadores de acá: 1.234.567,89 — punto para miles, coma
    para decimales. Python los escribe al revés, así que se dan vuelta."""
    s = f"{n:,.{decimales}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt(n: float) -> str:
    """Montos compactos para las tarjetas del panel.

    Dos cosas que estaban mal y se ven en cualquier demo:

    - El separador. `$2.86 M` con punto decimal es formato de Estados Unidos;
      acá eso se lee "dos punto ochenta y seis". Va `$2,86 M`.
    - El ancho. Con cinco tarjetas en fila, `$689.234` no entra y Streamlit lo
      cortaba a `$689,…`. Un número cortado en la pantalla principal de un
      producto que se vende es lo peor que puede pasar en una demo. Por eso
      los miles también se abrevian.
    """
    if abs(n) >= 1_000_000:
        return f"${_miles(n / 1_000_000, 2)} M"
    if abs(n) >= 100_000:
        return f"${_miles(n / 1_000)} K"
    return f"${_miles(n)}"


# Nombres de columna que ve el cliente. Las claves son los nombres canónicos
# internos: mostrar `cliente_id` o `ultima_compra` en pantalla es enseñarle al
# cliente el modelo de datos, no su negocio.
ETIQUETAS = {
    "sku": "Código", "nombre": "Producto", "categoria": "Categoría",
    "proveedor": "Proveedor", "costo": "Costo", "precio": "Precio",
    "stock": "Stock", "stock_min": "Stock mínimo",
    "lead_time_dias": "Días de reposición",
    "cliente_id": "Cliente", "tipo_negocio": "Tipo de negocio",
    "departamento": "Departamento", "zona": "Zona",
    "venta": "Venta", "margen": "Margen", "margen_pct": "Margen %",
    "pedidos": "Pedidos", "ultima_compra": "Última compra",
    "unidades": "Unidades", "cantidad": "Cantidad", "fecha": "Fecha",
    "precio_unit": "Precio unitario", "costo_unit": "Costo unitario",
    "rotacion": "Rotación", "dias_stock": "Días de stock",
    "capital_inmovilizado": "Capital inmovilizado",
    "descuento_sugerido": "Descuento sugerido", "precio_oferta": "Precio con oferta",
    "venta_id": "Comprobante", "dias_sin_comprar": "Días sin comprar",
}


# Plotly rotula los ejes con el nombre de la columna: "venta", "margen_pct",
# "categoria". Al cliente hay que mostrarle el nombre de su negocio, no el de
# la columna — se reusan las mismas ETIQUETAS de las tablas para que un
# concepto se llame igual en todos lados.
ETIQUETAS_GRAFICO = dict(ETIQUETAS, mes="Mes", lat="Latitud", lon="Longitud")


def _ejes(fig):
    """Deja el gráfico con nombres legibles y sin ruido visual."""
    fig.for_each_xaxis(lambda a: a.update(
        title_text=ETIQUETAS_GRAFICO.get(a.title.text, a.title.text or "")))
    fig.for_each_yaxis(lambda a: a.update(
        title_text=ETIQUETAS_GRAFICO.get(a.title.text, a.title.text or "")))
    if fig.layout.coloraxis and fig.layout.coloraxis.colorbar:
        t = fig.layout.coloraxis.colorbar.title.text
        if t:
            fig.layout.coloraxis.colorbar.title.text = ETIQUETAS_GRAFICO.get(t, t)
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

    Renombra las columnas a castellano, muestra los importes con separador de
    miles y las fechas sin la hora. Es una sola función y no formato caso por
    caso para que ninguna pantalla se olvide y quede mostrando `315742.95`
    junto a otra que muestra `$315.743`.
    """
    if df is None or len(df) == 0:
        st.caption("No hay datos para mostrar con los filtros actuales.")
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

with st.sidebar:
    st.markdown("<div class='plania-logo'>PLAN<span>IA</span></div>",
                unsafe_allow_html=True)
    st.caption("Planificación logística y comercial inteligente")
    st.markdown("---")
    MENU = ["Inicio",
            "Panel ejecutivo",
            "Stock y reposición",
            "Precios y márgenes",
            "Zonas y negocios",
            "Rutas de reparto",
            "Ofertas y sugerencias",
            "Copiloto IA",
            "Conectar ERP",
            "Planes y licencia",
            "Configuración",
            "Ayuda"]
    pagina = st.radio("Menú", MENU, label_visibility="collapsed")
    st.markdown("---")
    if lic["modo"] == "demo":
        st.markdown(f"**Demo full:** quedan "
                    f"{lic.get('horas_restantes', lic['dias_restantes'] * 24)} h")
        st.progress(min(1.0, lic.get("horas_restantes", licencia.DIAS_DEMO * 24) / (licencia.DIAS_DEMO * 24)))
    elif lic["modo"] == "licencia":
        st.markdown(f"**Plan {lic['plan']}** · vence en {lic['dias_restantes']} días")
    else:
        st.markdown("**Demo vencida** — activá tu licencia en *Planes y licencia*")
    fuente = "ERP conectado" if (st.session_state.get("erp_url")
                                 or pconfig.leer_extra("ERP_DB_URL")) else "Base demo (Uruguay)"
    st.caption(f"Fuente de datos: {fuente}")

BLOQUEADA = lic["modo"] == "vencida" and pagina not in (
    "Inicio", "Planes y licencia", "Ayuda", "Configuración")
if BLOQUEADA:
    st.warning("La demo de 7 días terminó. Activá tu licencia en **Planes y licencia** "
               "para seguir usando Plania con todos tus datos intactos.")
    st.stop()

datos = None
if pagina not in ("Planes y licencia", "Configuración", "Ayuda", "Conectar ERP"):
    datos = cargar_datos()


# ---------------------------------------------------------------------------
# Filtros por categoría
# ---------------------------------------------------------------------------
# Las categorías NO están escritas acá: salen de los datos del cliente
# (`catalogo.columnas_categoricas` las detecta por cardinalidad). Una lista
# fija de rubros sería adivinar el negocio del cliente; así, un distribuidor
# de bebidas filtra por sus marcas y una ferretería por sus rubros, sin que
# nadie configure nada.
PAGINAS_CON_FILTRO = ("Panel ejecutivo", "Stock y reposición", "Precios y márgenes",
                      "Zonas y negocios", "Ofertas y sugerencias", "Rutas de reparto")


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
        st.markdown("**Filtros**")
        for entidad, etiqueta in (("productos", "Producto"), ("clientes", "Cliente")):
            base = d[entidad]
            for col in catalogo.columnas_categoricas(base):
                opciones = catalogo.valores_de(base, col)
                if len(opciones) < 2:
                    continue
                sel = st.multiselect(f"{etiqueta} · {col.replace('_', ' ')}",
                                     opciones, default=[],
                                     key=f"filtro_{entidad}_{col}")
                if not sel:
                    continue
                activos.append(f"{col}: {', '.join(str(s) for s in sel[:3])}"
                               + ("…" if len(sel) > 3 else ""))
                if entidad == "productos":
                    productos = productos[productos[col].isin(sel)]
                else:
                    clientes = clientes[clientes[col].isin(sel)]

        if activos:
            if st.button("Limpiar filtros", width="stretch"):
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
        st.warning("Con esos filtros no queda ninguna venta. "
                   "Sacá alguno para volver a ver datos.")


def _aviso_filtros() -> None:
    """Deja a la vista que lo de abajo es un recorte, no el negocio entero.

    Un panel filtrado que no lo dice lleva a decisiones equivocadas: el
    encargado ve 'venta 30 días' y cree que es la del negocio.
    """
    if FILTROS_ACTIVOS:
        st.info("Filtrado por — " + " · ".join(FILTROS_ACTIVOS))


def _ventas_enriquecidas(d: dict) -> pd.DataFrame:
    return analitica.enriquecer_ventas(d["ventas"], d["productos"], d["clientes"])


def _botones_export(clave: str, secciones: list, etiqueta: str = "Exportar"):
    """Botones de descarga PDF / Word / Excel para cualquier tabla o informe."""
    if not licencia.tiene("exportes"):
        st.caption("Exportes disponibles en planes pagos y demo.")
        return
    titulo = secciones[0][0] if secciones else "Informe"
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    c1.download_button("PDF", exportes.a_pdf(titulo, secciones),
                       file_name=f"plania_{clave}.pdf", key=f"pdf_{clave}",
                       mime="application/pdf")
    c2.download_button("Word", exportes.a_word(titulo, secciones),
                       file_name=f"plania_{clave}.docx", key=f"docx_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document")
    c3.download_button("Excel", exportes.a_excel(secciones),
                       file_name=f"plania_{clave}.xlsx", key=f"xlsx_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
if pagina == "Inicio":
    st.markdown(f"# Plania <span class='plania-badge'>PLANIFICACIÓN INTELIGENTE</span>",
                unsafe_allow_html=True)
    if lic["modo"] == "demo":
        st.markdown(f"<div class='plania-demo'>Estás en la <b>demo de 7 días con TODO "
                    f"habilitado</b> — conectá tu ERP real o explorá con la base demo. "
                    f"Quedan {lic.get('horas_restantes', licencia.DIAS_DEMO * 24)} horas.</div>",
                    unsafe_allow_html=True)
    st.markdown(
        "El único planificador que **se conecta al ERP que ya tenés** (PostgreSQL, "
        "MySQL, SQL Server, Oracle, SQLite, CSV/Excel), te dice **qué ofertar, qué "
        "reponer, qué re-precificar y por dónde repartir**, y te deja todo listo en "
        "**PDF/Word/Excel** — con un copiloto que responde sobre tus datos reales.")
    if datos:
        v = _ventas_enriquecidas(datos)
        k = analitica.kpis(datos["productos"], v)
        paq = sugerencias.generar_todas(datos)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Venta últimos 30 días", _fmt(k["venta_periodo"]))
        c2.metric("Margen", f"{k['margen_pct']:.1f}%")
        c3.metric("Capital liberable (sobrestock)", _fmt(paq["resumen"]["capital_liberable"]))
        c4.metric("Venta en riesgo (quiebres)", _fmt(paq["resumen"]["venta_en_riesgo"]))
        st.info("Empezá por **Ofertas y sugerencias** para ver las decisiones de hoy, "
                "o preguntale al **Copiloto**: *«¿qué ofertas armo esta semana?»*")

elif pagina == "Panel ejecutivo":
    st.title("Panel ejecutivo")
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        k = analitica.kpis(datos["productos"], v)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Venta 30d", _fmt(k["venta_periodo"]))
        c2.metric("Margen 30d", _fmt(k["margen_periodo"]), f"{k['margen_pct']:.1f}%")
        c3.metric("Valor stock (costo)", _fmt(k["valor_stock"]))
        c4.metric("Quiebres / bajo mín.", f"{k['quiebres']} / {k['bajo_minimo']}")
        c5.metric("Clientes activos 30d", k["clientes_activos"])
        st.markdown("---")
        col1, col2 = st.columns([3, 2])
        tm = analitica.tendencia_mensual(v)
        fig = px.area(tm, x="mes", y="venta", title="Venta mensual",
                      color_discrete_sequence=[CELESTE])
        fig.update_layout(margin=dict(t=40, b=0), height=320)
        col1.plotly_chart(_ejes(fig), width="stretch")
        g = analitica.por_dimension(v, "categoria")
        fig2 = px.bar(g, x="venta", y="categoria", orientation="h",
                      title="Venta por categoría", color="margen_pct",
                      color_continuous_scale=["#E74C3C", "#F39C12", "#20BF6B"])
        fig2.update_layout(margin=dict(t=40, b=0), height=320)
        col2.plotly_chart(_ejes(fig2), width="stretch")
        st.markdown("#### Top clientes")
        _tabla(analitica.top_clientes(v))

elif pagina == "Stock y reposición":
    st.title("Stock y reposición")
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        r = analitica.rotacion(datos["productos"], v)
        c1, c2, c3 = st.columns(3)
        c1.metric("SKUs", len(r))
        c2.metric("Quiebres", int((r["stock"] <= 0).sum()))
        c3.metric("Sobrestock (>90 días)", int((r["dias_stock"] > 90).sum()))
        tab1, tab2 = st.tabs(["Reposición urgente", "Stock completo"])
        with tab1:
            rep = sugerencias.reposicion(datos["productos"], v)
            if len(rep):
                _tabla(rep)
                _botones_export("reposicion", [("Reposición urgente",
                                                exportes.TITULOS["reposicion"][1], rep)])
            else:
                st.success("Sin riesgo de quiebre con la rotación actual.")
        with tab2:
            filtro = st.multiselect("Categoría",
                                    sorted(r["categoria"].dropna().unique()))
            rr = r[r["categoria"].isin(filtro)] if filtro else r
            st.dataframe(rr.drop(columns=["venta_diaria"]).assign(
                dias_stock=rr["dias_stock"].replace([float("inf")], 999).round(0)),
                width="stretch", hide_index=True)

elif pagina == "Precios y márgenes":
    st.title("Precios y márgenes")
    _aviso_filtros()
    if datos:
        v = _ventas_enriquecidas(datos)
        mp = analitica.margen_por_producto(v)
        c1, c2 = st.columns(2)
        c1.metric("Margen promedio ponderado",
                  f"{v['margen'].sum() / v['venta'].sum() * 100:.1f}%")
        pr = sugerencias.precios(datos["productos"], v)
        c2.metric("Margen extra disponible",
                  _fmt(pr["margen_extra_mensual"].sum() if len(pr) else 0) + "/mes")
        fig = px.scatter(mp, x="venta", y="margen_pct", color="categoria",
                         hover_name="nombre", title="Venta vs margen por producto",
                         labels={"venta": "Venta ($)", "margen_pct": "Margen %"})
        fig.update_layout(height=380, margin=dict(t=40, b=0))
        st.plotly_chart(_ejes(fig), width="stretch")
        st.markdown("#### Sugerencias de ajuste de precio")
        if len(pr):
            _tabla(pr)
            _botones_export("precios", [("Ajustes de precio",
                                         exportes.TITULOS["precios"][1], pr)])
        else:
            st.success("Márgenes alineados con su categoría.")

elif pagina == "Zonas y negocios":
    st.title(" Zonas & tipos de negocio")
    if datos:
        v = _ventas_enriquecidas(datos)
        dim = st.radio("Ver por", ["zona", "departamento", "tipo_negocio"],
                       horizontal=True)
        g = analitica.por_dimension(v, dim)
        if len(g):
            col1, col2 = st.columns([3, 2])
            fig = px.bar(g.head(15), x="venta", y=dim, orientation="h",
                         color="margen_pct", title=f"Venta por {dim}",
                         color_continuous_scale=["#E74C3C", "#F39C12", "#20BF6B"])
            fig.update_layout(height=420, margin=dict(t=40, b=0))
            col1.plotly_chart(_ejes(fig), width="stretch")
            col2.dataframe(g, width="stretch", hide_index=True)
        st.markdown("#### Oportunidades de venta cruzada por zona")
        op = sugerencias.oportunidades_zona(v)
        if len(op):
            _tabla(op)
            _botones_export("zonas", [("Oportunidades por zona",
                                       exportes.TITULOS["zonas"][1], op)])
        else:
            st.info("Sin brechas de penetración relevantes (o faltan datos de zona).")

elif pagina == "Rutas de reparto":
    st.title("Rutas de reparto")
    _aviso_filtros()
    if not licencia.tiene("rutas"):
        st.warning("El plan actual no incluye el planificador de rutas — "
                   "disponible en **Pro** y **Enterprise**.")
    elif datos:
        v = _ventas_enriquecidas(datos)
        clientes = datos["clientes"]
        c1, c2, c3 = st.columns(3)
        vehiculos = c1.number_input("Vehículos", 1, 20, 2)
        paradas = c2.number_input("Paradas máx. por vehículo", 5, 60, 25)
        deptos = c3.multiselect("Departamento",
                                sorted(clientes["departamento"].dropna().unique()))
        base = clientes[clientes["departamento"].isin(deptos)] if deptos else clientes
        modo = st.radio("A quién visitar", ["Clientes activos (últimos 30 días)",
                                            "Clientes inactivos (recupero)", "Todos"],
                        horizontal=True)
        if "inactivos" in modo:
            objetivo = base.merge(
                analitica.clientes_inactivos(v, base)[["cliente_id"]], on="cliente_id")
        elif "activos" in modo:
            corte = v["fecha"].max() - pd.Timedelta(days=30)
            act = v[v["fecha"] > corte]["cliente_id"].unique()
            objetivo = base[base["cliente_id"].isin(act)]
        else:
            objetivo = base
        st.caption(f"{len(objetivo)} clientes a rutear")
        if len(objetivo) and st.button("Planificar rutas", type="primary"):
            plan = rutas.planificar(objetivo, vehiculos=int(vehiculos),
                                    paradas_max=int(paradas))
            _tabla(plan["resumen"])
            if {"lat", "lon"}.issubset(plan["rutas"].columns):
                figm = px.scatter_map(plan["rutas"], lat="lat", lon="lon",
                                      color=plan["rutas"]["vehiculo"].astype(str),
                                      hover_name="nombre", zoom=10, height=420,
                                      title="Paradas por vehículo")
                figm.update_layout(margin=dict(t=40, b=0))
                st.plotly_chart(figm, width="stretch")
            _tabla(plan["rutas"])
            _botones_export("rutas", [("Hoja de ruta",
                                       "Orden de visita optimizado por vehículo "
                                       "(vecino más cercano + 2-opt).", plan["rutas"])])

elif pagina == "Ofertas y sugerencias":
    st.title("Ofertas y sugerencias")
    _aviso_filtros()
    if datos:
        paq = sugerencias.generar_todas(datos)
        res = paq["resumen"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Capital liberable", _fmt(res["capital_liberable"]))
        c2.metric("Venta en riesgo", _fmt(res["venta_en_riesgo"]))
        c3.metric("Margen extra/mes", _fmt(res["margen_extra_mensual"]))
        c4.metric("Potencial por zonas", _fmt(res["venta_potencial_zonas"]))
        st.markdown("---")
        secciones = exportes.secciones_desde_paquete(paq)
        _botones_export("paquete_completo", secciones,
                        etiqueta="Exportar informe completo")
        tabs = st.tabs(["Ofertas", "Reposición", "Precios", "Zonas", "Recupero"])
        for tab, clave in zip(tabs, ["ofertas", "reposicion", "precios",
                                     "zonas", "recupero"]):
            with tab:
                df = paq[clave]
                if df is not None and len(df):
                    st.caption(exportes.TITULOS[clave][1])
                    _tabla(df)
                else:
                    st.success("Nada para accionar acá — todo en orden.")

elif pagina == "Copiloto IA":
    st.title("Copiloto — preguntale a tus datos")
    if not licencia.tiene("copiloto"):
        st.warning("El plan actual no incluye el Copiloto.")
    elif datos:
        st.caption("Responde con datos reales del negocio conectado. Ejemplos: "
                   "*¿qué ofertas armo esta semana?* · *¿cuánto stock hay de bebidas?* · "
                   "*¿qué zona está floja?* · *¿qué repongo ya?* · "
                   "*¿qué clientes perdí?*")
        if "chat" not in st.session_state:
            st.session_state.chat = []
        for m in st.session_state.chat:
            with st.chat_message(m["rol"]):
                st.markdown(m["texto"])
                if m.get("tabla") is not None:
                    _tabla(m["tabla"])
        pregunta = st.chat_input("Escribí tu consulta…")
        if pregunta:
            st.session_state.chat.append({"rol": "user", "texto": pregunta})
            with st.chat_message("user"):
                st.markdown(pregunta)
            with st.chat_message("assistant"):
                with st.spinner("Calculando sobre tus datos…"):
                    r = copiloto.responder(pregunta, datos)
                st.markdown(r["respuesta"])
                if r["tabla"] is not None and len(r["tabla"]):
                    _tabla(r["tabla"])
                    _botones_export(f"copiloto_{len(st.session_state.chat)}",
                                    [(r["titulo"], r["respuesta"], r["tabla"])])
            st.session_state.chat.append({"rol": "assistant", "texto": r["respuesta"],
                                          "tabla": r["tabla"]})

elif pagina == "Conectar ERP":
    st.title(" Conectar tu ERP o base de datos")
    st.markdown(
        "Plania **no te hace migrar nada**: apunta a la base que ya usás y "
        "auto-detecta las columnas. Motores soportados: PostgreSQL, MySQL/MariaDB, "
        "SQL Server, Oracle y SQLite — o subí un CSV/Excel exportado del ERP "
        "(Zureo, Memory, Tango, Bejerman, Odoo, SAP B1 y similares).")
    tab1, tab2 = st.tabs(["Base de datos (SQL)", "Archivos CSV/Excel"])
    with tab1:
        url = st.text_input("URL de conexión SQLAlchemy",
                            value=pconfig.leer_extra("ERP_DB_URL") or "",
                            placeholder="postgresql://usuario:clave@servidor:5432/erp")
        c1, c2 = st.columns(2)
        if c1.button("Probar conexión", type="primary"):
            try:
                eng = conectores.conectar_sql(url)
                tablas = conectores.listar_tablas(eng)
                st.success(f" Conectado. {len(tablas)} tablas: "
                           f"{', '.join(tablas[:12])}{'…' if len(tablas) > 12 else ''}")
                auto = {e: conectores.autodescubrir_tabla(eng, e)
                        for e in ("productos", "clientes", "ventas")}
                st.json({f"tabla de {k}": v or "(elegir manualmente)"
                         for k, v in auto.items()})
                st.session_state.erp_url = url
            except Exception as e:
                st.error(f"No conectó: {e}")
        if c2.button("Guardar y usar esta base"):
            pconfig.guardar_extra("ERP_DB_URL", url)
            st.session_state.erp_url = url
            _cargar.clear()
            st.success("Guardado. Toda la app pasa a leer de tu ERP.")
        with st.expander("Elegir tablas manualmente (si el autodescubrimiento no acierta)"):
            t_p = st.text_input("Tabla/consulta de productos", "")
            t_c = st.text_input("Tabla/consulta de clientes", "")
            t_v = st.text_input("Tabla/consulta de ventas", "")
            if st.button("Usar estas tablas"):
                st.session_state.tablas_erp = {k: v for k, v in
                                               {"productos": t_p, "clientes": t_c,
                                                "ventas": t_v}.items() if v}
                _cargar.clear()
                st.success("Listo — se usan esas tablas/consultas.")
    with tab2:
        st.caption("Subí los tres archivos (clientes es opcional). Las columnas se "
                   "auto-mapean; abajo ves cómo quedó.")
        arch = {e: st.file_uploader(f"Archivo de {e}", type=["csv", "xlsx", "xls"],
                                    key=f"up_{e}")
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
                    st.caption(f"**{e}**: mapeo detectado {mapeo}")
                    nuevos[e] = conectores.normalizar(crudo, e, mapeo)
                st.session_state.datos_archivo = nuevos
                st.dataframe(nuevos["productos"].head(), width="stretch")
                if st.button("Usar estos archivos en toda la app", type="primary"):
                    url_archivos = conectores.guardar_como_base(nuevos)
                    pconfig.guardar_extra("ERP_DB_URL", url_archivos)
                    st.session_state.erp_url = url_archivos
                    _cargar.clear()
                    st.success("Listo: los archivos quedaron guardados como base "
                               "de datos y toda la app pasa a leer de ahí (panel, "
                               "sugerencias, copiloto, rutas). Podés volver a la "
                               "base demo borrando ERP · URL en Configuración.")
            except Exception as e:
                st.error(str(e))

elif pagina == "Planes y licencia":
    st.title("Planes y licencia")
    backend = os.environ.get("PLANIA_BACKEND_URL",
                             pconfig.leer_extra("BACKEND_URL") or "http://localhost:8100")
    if lic["modo"] == "demo":
        st.markdown(f"<div class='plania-demo'>Demo full activa — quedan "
                    f"{lic.get('horas_restantes', licencia.DIAS_DEMO * 24)} horas. Al comprar, tus datos y "
                    f"configuración quedan tal cual.</div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    for col, (plan, titulo, precio, detalle) in zip((col1, col2, col3), [
        ("starter", "Starter", "USD 59/mes",
         "Copiloto + ERP + rutas + exportes · 500 consultas/mes"),
        ("pro", "Pro — recomendado", "USD 129/mes",
         "Todo Starter · 2.000 consultas/mes, y seguís aunque te pases"),
        ("enterprise", "Enterprise", "a medida",
         "Multi-sucursal, white label, SSO, SLA"),
    ]):
        with col:
            st.markdown(f"### {titulo}")
            st.markdown(f"## {precio}")
            st.caption(detalle)
    st.markdown("---")
    email = st.text_input("Tu email (para emitir la licencia)")
    plan_sel = st.selectbox("Plan", ["starter", "pro"])
    if st.button("Pagar con MercadoPago", type="primary"):
        try:
            import requests
            r = requests.post(f"{backend}/checkout",
                              json={"plan": plan_sel, "email": email}, timeout=15)
            if r.ok:
                st.link_button("Ir al checkout seguro de MercadoPago",
                               r.json()["init_point"])
            else:
                st.error(r.json().get("detail", r.text))
        except Exception as e:
            st.error(f"No pude contactar el backend de venta ({backend}): {e}")
    st.markdown("#### Ya tengo mi licencia")
    tok = st.text_input("Pegá el token de licencia", type="password")
    if st.button("Activar licencia"):
        r = licencia.activar_licencia(tok.strip())
        if r["ok"]:
            st.success(f" Licencia activada — plan {r['claims'].get('plan')}. "
                       "Recargá la página.")
        else:
            st.error(r["error"])

elif pagina == "Configuración":
    st.title("Configuración")
    st.caption(f"Guardado seguro: **{pconfig.backend_activo()}** "
               "(keyring del sistema > archivo cifrado > texto plano)")
    cfg = pconfig.cargar()
    with st.form("cfg"):
        nuevos = {}
        for clave, desc in pconfig.CLAVES.items():
            actual = cfg.get(clave, "")
            nuevos[clave] = st.text_input(
                desc, value="", placeholder=pconfig.enmascarar(actual) if actual
                else "(sin configurar)", type="password" if "KEY" in clave
                or "TOKEN" in clave or "PASSWORD" in clave else "default")
        if st.form_submit_button("Guardar", type="primary"):
            cambios = {k: v for k, v in nuevos.items() if v.strip()}
            if cambios:
                pconfig.guardar(cambios)
                pconfig.aplicar()
                st.success(f"Guardado: {', '.join(cambios)}.")
            else:
                st.info("No ingresaste valores nuevos.")

else:  # Ayuda
    st.title("Ayuda")
    st.markdown("""
**¿Qué hace Plania?** Se conecta a tu ERP o base de datos (sin migrar nada),
analiza stock, precios, márgenes, zonas y clientes, y te devuelve decisiones
accionables: ofertas, reposición, ajustes de precio, rutas de reparto y
clientes a recuperar — todo exportable a **PDF, Word y Excel** y consultable
por chat con el **Copiloto**.

**Primeros pasos**
1.  *Conectar ERP / Base*: apuntá a tu base (o probá con la demo incluida).
2.  *Ofertas & Sugerencias*: exportá el informe completo del día.
3.  *Copiloto*: preguntá en criollo — «¿qué repongo ya?».

**Demo de 7 días** — todo habilitado, sin tarjeta. Al vencer, tus datos no
se tocan: activás la licencia y seguís donde estabas.

**Soporte** — soporte@plania.uy · WhatsApp +598 99 000 000
""")
