"""
Plania · Panel del dueño (versión owner)
========================================
La aplicación que usa el VENDEDOR, no el cliente. Corre aparte del producto
y en otro puerto, para que nunca quede expuesta por accidente en la misma
instancia que ve un cliente:

    PLANIA_OWNER_TOKEN=elegí-un-token streamlit run app/owner.py --server.port 8600

Qué resuelve, en un solo lugar:
  · Estado real del negocio (demos, conversión, MRR, costos, margen).
  · Emisión manual de licencias para ventas cerradas fuera de MercadoPago.
  · Proyección de rentabilidad con los tres escenarios, en vivo.
  · Mercado potencial en Uruguay, LATAM y el mundo.
  · Kit de contenido para redes, generado sobre datos reales y exportable.
  · Verificación end-to-end del producto antes de salir a vender.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

pd.set_option("mode.string_storage", "python")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from plania import apariencia, conectores, contenido, exportes, negocio, owner, verificacion  # noqa: E402
from plania import config as pconfig  # noqa: E402

pconfig.aplicar()

AZUL = "#1F3D7A"
CELESTE = "#2E86DE"
VERDE = "#20BF6B"
ROJO = "#E74C3C"

st.set_page_config(page_title="Plania · Panel del dueño", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown(f"""
<style>
  {apariencia.css_programa()}
  .block-container {{ padding-top: 1.4rem; max-width: 1320px; }}
  section[data-testid="stSidebar"] {{
      background: linear-gradient(180deg, #101C33 0%, #0a1122 100%);
  }}
  section[data-testid="stSidebar"] * {{ color: #E8EEF9 !important; }}
  .owner-logo {{ font-weight: 800; font-size: 1.4rem; letter-spacing: .14em; }}
  .owner-logo span {{ color: {CELESTE}; }}
  .owner-tag {{
      background: #2b3a55; color: #cfe0ff; border-radius: 6px;
      padding: 2px 10px; font-size: .7rem; letter-spacing: .08em;
  }}
  div[data-testid="stMetric"] {{
      background: #FFFFFF; border: 1px solid #E3E8F2; border-radius: 10px;
      padding: 14px 16px; box-shadow: 0 1px 3px rgba(16,30,60,.06);
  }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Acceso: este panel expone datos del negocio, no puede quedar abierto
# ---------------------------------------------------------------------------
def _token_esperado() -> str | None:
    return os.environ.get("PLANIA_OWNER_TOKEN") or pconfig.leer_extra("OWNER_TOKEN")


def _es_el_programa_instalado() -> bool:
    """¿Esto es "Plania Owner" corriendo en la máquina del dueño?

    Si lo es, no se pide token, y no es un atajo: es que el token no protege
    nada acá. Este panel se distribuye en UN solo ejecutable
    (`packaging/plania_owner.spec`), que no se publica, no va a INSTALADOR/,
    no se adjunta a ninguna release y el workflow corta si aparece. Quien
    tiene ese archivo es porque lo compiló. Pedirle además una contraseña es
    pedirle una llave para su propia casa: lo único que consigue es que la
    anote en un papel al lado de la puerta.

    Lo que sí protege está en otro lado y no cambia: que el panel no viaje
    adentro del producto (`proteger_codigo.py` lo saca del .exe y del ZIP) y
    que sólo el dueño pueda compilarlo.

    Las DOS condiciones tienen que darse:

      · ejecutable congelado (PyInstaller). Corriendo desde el repo con
        `streamlit run` sigue pidiendo token, que es como se lo prueba en
        desarrollo y como podría quedar levantado sin querer.
      · escuchando SOLO en loopback. Si alguien despliega esto en un servidor
        —`--server.address 0.0.0.0`, un Procfile, un contenedor—, el token
        vuelve a ser obligatorio: ahí sí hay red del otro lado.
    """
    if not getattr(sys, "frozen", False):
        return False
    direccion = os.environ.get("STREAMLIT_SERVER_ADDRESS", "")
    return direccion in ("127.0.0.1", "localhost", "::1")


esperado = _token_esperado()
if "owner_ok" not in st.session_state:
    st.session_state.owner_ok = _es_el_programa_instalado()

if not st.session_state.owner_ok:
    st.markdown("<div class='owner-logo'>PLAN<span>IA</span> · panel del dueño</div>",
                unsafe_allow_html=True)
    if not esperado:
        st.error(
            "No hay token de acceso configurado. Este panel muestra la "
            "facturación y los clientes del negocio, así que no se abre sin "
            "token.\n\nDefinilo antes de levantarlo:\n\n"
            "`PLANIA_OWNER_TOKEN=tu-token-secreto streamlit run app/owner.py "
            "--server.port 8600`")
        st.stop()
    ingresado = st.text_input("Token de acceso", type="password")
    if st.button("Entrar", type="primary"):
        import secrets
        if secrets.compare_digest(ingresado.strip(), esperado):
            st.session_state.owner_ok = True
            st.rerun()
        else:
            st.error("Token incorrecto.")
    st.stop()


@st.cache_data(show_spinner="Leyendo datos del negocio…")
def _datos_producto():
    return conectores.cargar_datos()


def _fmt(n: float) -> str:
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:,.2f} M"
    return f"${n:,.0f}"


def _export(clave: str, secciones: list):
    c1, c2, c3, _ = st.columns([1, 1, 1, 4])
    titulo = secciones[0][0] if secciones else "Informe"
    c1.download_button("PDF", exportes.a_pdf(titulo, secciones),
                       file_name=f"plania_owner_{clave}.pdf", key=f"pdf_{clave}",
                       mime="application/pdf")
    c2.download_button("Word", exportes.a_word(titulo, secciones),
                       file_name=f"plania_owner_{clave}.docx", key=f"doc_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document")
    c3.download_button("Excel", exportes.a_excel(secciones),
                       file_name=f"plania_owner_{clave}.xlsx", key=f"xls_{clave}",
                       mime="application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet")


with st.sidebar:
    st.markdown("<div class='owner-logo'>PLAN<span>IA</span></div>",
                unsafe_allow_html=True)
    st.markdown("<span class='owner-tag'>PANEL DEL DUEÑO</span>",
                unsafe_allow_html=True)
    st.markdown("---")
    seccion = st.radio("Menú", [
        "Estado del negocio",
        "Clientes y licencias",
        "Proyección de rentabilidad",
        "Mercado y competencia",
        "Contenido para redes",
        "Verificación del producto",
    ], label_visibility="collapsed")
    st.markdown("---")
    st.caption("Este panel no debe exponerse al cliente. Corre en un puerto "
               "aparte y exige token.")


# ---------------------------------------------------------------------------
if seccion == "Estado del negocio":
    st.title("Estado del negocio")
    k = owner.kpis_negocio()

    c = st.columns(5)
    c[0].metric("Demos entregadas", k["demos_entregadas"])
    c[1].metric("Clientes pagos", k["clientes_pagos"])
    c[2].metric("Conversión", f"{k['conversion_pct']}%")
    c[3].metric("MRR", _fmt(k["mrr_usd"]))
    c[4].metric("ARR", _fmt(k["arr_usd"]))

    c = st.columns(4)
    c[0].metric("Costo de IA (mes)", f"${k['costo_ia_mes_usd']:,.2f}")
    c[1].metric("Comisión MercadoPago", f"${k['comision_mp_mes_usd']:,.2f}")
    c[2].metric("Margen bruto", f"{k['margen_bruto_pct']}%")
    c[3].metric("Clientes en riesgo", k["clientes_en_riesgo"],
                help="Sin actividad hace más de 14 días: son los que se van primero.")

    if k["demos_entregadas"] == 0 and k["clientes_pagos"] == 0:
        st.info(
            "Todavía no hay operación registrada. Los números de este panel se "
            "llenan solos a medida que se entregan demos y se emiten licencias: "
            "salen del log de auditoría y de la base de uso, no se cargan a mano.")

    integridad = owner.integridad_registros()
    if integridad.get("ok"):
        st.success("Log de auditoría íntegro: la cadena de hashes verifica. "
                   "Ningún registro de venta fue alterado.")
    else:
        st.warning(f"Verificación de integridad del log: {integridad}")

    st.markdown("---")
    st.markdown("#### Informe del negocio")
    _export("negocio", owner.secciones_para_informe_owner())


# ---------------------------------------------------------------------------
elif seccion == "Clientes y licencias":
    st.title("Clientes y licencias")

    tab1, tab2, tab3 = st.tabs(["Licencias emitidas", "Uso por cliente",
                                "Emitir licencia manual"])
    with tab1:
        emitidas = owner.licencias_emitidas()
        if len(emitidas):
            st.dataframe(emitidas, width="stretch", hide_index=True)
        else:
            st.info("Sin licencias emitidas todavía.")

    with tab2:
        uso = owner.uso_por_cliente()
        if len(uso):
            st.dataframe(uso, width="stretch", hide_index=True)
            riesgo = uso[uso["dias_sin_usar"] > 14]
            if len(riesgo):
                st.warning(
                    f"{len(riesgo)} clientes sin usar el producto hace más de "
                    "14 días. En SaaS de PyME el que deja de entrar cancela al "
                    "mes siguiente: conviene llamarlos antes de que pidan la baja.")
        else:
            st.info("Sin consumo registrado todavía.")

    with tab3:
        st.caption("Para ventas cerradas fuera de MercadoPago (transferencia, "
                   "efectivo, partner). Emite el mismo JWT que el circuito de pago.")
        from backend_venta import licencias as blic
        col1, col2 = st.columns(2)
        cliente = col1.text_input("Email o identificador del cliente")
        plan = col2.selectbox("Plan", list(blic.PLANES))
        if st.button("Emitir licencia", type="primary"):
            if not cliente.strip():
                st.error("Falta el identificador del cliente.")
            else:
                from plania import auditoria as pauditoria
                token = blic.emitir_licencia(cliente.strip(), plan)
                pauditoria.registrar("licencia_emitida_manual",
                                     {"cliente": cliente.strip(), "plan": plan})
                st.success(f"Licencia {plan} emitida para {cliente.strip()}.")
                st.code(token, language=None)
                st.caption("El cliente la pega en Planes y licencia dentro de la "
                           "aplicación.")


# ---------------------------------------------------------------------------
elif seccion == "Proyección de rentabilidad":
    st.title("Proyección de rentabilidad")
    st.caption("Simulación mes a mes con capacidad horaria, ciclo de venta, "
               "churn, régimen tributario uruguayo y contratación. Todos los "
               "supuestos están en plania/negocio.py.")

    c1, c2, c3 = st.columns(3)
    nombre = c1.selectbox("Escenario", list(negocio.ESCENARIOS))
    ads = c2.slider("Inversión en redes (USD/mes)", 0, 1500, 300, 50)
    meses = c3.slider("Meses a simular", 6, 36, 18, 6)

    esc = negocio.ESCENARIOS[nombre]
    df = negocio.simular(esc, meses=meses, inversion_ads_mes=float(ads))
    eq = negocio.mes_de_equilibrio(df)
    sup = negocio.mes_supera_sueldo(df)
    ue = negocio.unit_economics(esc, float(ads), df)
    ultimo = df.iloc[-1]

    c = st.columns(5)
    c[0].metric(f"Clientes al mes {meses}", f"{ultimo['clientes_activos']:.0f}")
    c[1].metric("MRR final", _fmt(ultimo["mrr"]))
    c[2].metric("Caja acumulada", _fmt(ultimo["caja_acumulada"]))
    c[3].metric("Mes de equilibrio", eq if eq else "no llega")
    c[4].metric("Supera un sueldo", f"mes {sup}" if sup else "no llega",
                help=f"Referencia: USD {negocio.SUELDO_REFERENCIA_EMPLEADO:,.0f}/mes "
                     "es lo que este perfil gana empleado en Uruguay.")

    c = st.columns(4)
    c[0].metric("LTV / CAC", ue["ltv_sobre_cac"],
                help="Por debajo de 3 el negocio no escala con pauta.")
    c[1].metric("CAC", _fmt(ue["cac"]))
    c[2].metric("LTV", _fmt(ue["ltv"]))
    c[3].metric("Caja mínima", _fmt(negocio.caja_minima(df)),
                help="El pozo más hondo: es el capital que hay que tener guardado.")

    if negocio.caja_minima(df) < 0:
        st.warning(
            f"La caja toca {_fmt(negocio.caja_minima(df))} antes de recuperarse. "
            "Hay que arrancar con ese colchón o el negocio se ahoga aunque el "
            "modelo cierre a 18 meses.")

    fig = px.bar(df, x="mes", y=["ingreso_suscripcion", "ingreso_implementacion"],
                 title="Composición del ingreso",
                 color_discrete_sequence=[CELESTE, "#8FC4F5"])
    fig.update_layout(height=300, margin=dict(t=40, b=0), legend_title="")
    st.plotly_chart(fig, width="stretch")

    fig2 = px.line(df, x="mes", y=["resultado_neto", "caja_acumulada"],
                   title="Resultado mensual y caja acumulada",
                   color_discrete_sequence=[VERDE, AZUL])
    fig2.add_hline(y=negocio.SUELDO_REFERENCIA_EMPLEADO, line_dash="dot",
                   annotation_text="sueldo de referencia", line_color=ROJO)
    fig2.update_layout(height=320, margin=dict(t=40, b=0), legend_title="")
    st.plotly_chart(fig2, width="stretch")

    st.markdown("#### Cortes de decisión")
    st.dataframe(negocio.resumen_horizontes(df), width="stretch", hide_index=True)
    st.markdown("#### Detalle mensual")
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("#### Informe completo (los tres escenarios, con y sin pauta)")
    _export("rentabilidad", negocio.secciones_para_informe(meses=meses))


# ---------------------------------------------------------------------------
elif seccion == "Mercado y competencia":
    st.title("Mercado y competencia")

    pot = negocio.potencial_mercados()
    st.markdown("#### Mercado potencial por región")
    st.dataframe(pot, width="stretch", hide_index=True)

    fig = px.bar(pot, x="mercado", y=["SAM_usd_anual", "SOM_18m_usd_anual"],
                 barmode="group", log_y=True,
                 title="Mercado alcanzable (SAM) vs. lo que se puede tomar en 18 meses (SOM)",
                 color_discrete_sequence=[CELESTE, VERDE])
    fig.update_layout(height=330, margin=dict(t=40, b=0), legend_title="")
    st.plotly_chart(fig, width="stretch")

    for nombre, m in negocio.MERCADOS.items():
        with st.expander(f"{nombre} — lectura del mercado"):
            st.write(m["notas"])
            st.caption(f"TAM {m['tam_empresas']:,} empresas · "
                       f"SAM {m['sam_empresas']:,} · "
                       f"SOM 18 meses {m['som_18m_empresas']:,} · "
                       f"ticket anual USD {m['ticket_anual_usd']:,}")

    st.markdown("---")
    st.markdown("#### Sensibilidad: dónde conviene poner el esfuerzo")
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Si los clientes duran más (menos churn)")
        st.dataframe(negocio.sensibilidad("churn_mensual",
                                          [0.015, 0.02, 0.03, 0.045, 0.06]),
                     width="stretch", hide_index=True)
    with c2:
        st.caption("Si cierran más demos")
        st.dataframe(negocio.sensibilidad("conv_demo_cliente",
                                          [0.08, 0.12, 0.16, 0.20, 0.28]),
                     width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
elif seccion == "Contenido para redes":
    st.title("Contenido para redes")
    datos = _datos_producto()

    if contenido._sobre_datos_demo():
        st.warning(contenido.AVISO_DEMO)
    else:
        st.success("Contenido generado sobre datos reales del ERP conectado.")

    tabs = st.tabs(["LinkedIn", "Video", "Prospección", "Calendario", "Pauta"])
    with tabs[0]:
        posts = contenido.posts_linkedin(datos)
        for _, p in posts.iterrows():
            with st.expander(f"{p['titulo']}  ·  {p['caracteres']} caracteres"):
                st.text_area("Texto", p["texto"], height=260,
                             key=f"li_{p['titulo']}")
                st.caption(f"Cierre sugerido: {p['cta']}")
    with tabs[1]:
        for _, g in contenido.guiones_video(datos).iterrows():
            with st.expander(f"{g['titulo']}  ·  {g['duracion']}"):
                st.write(f"**Gancho (primeros 3 s):** {g['gancho_3s']}")
                st.text_area("Guion", g["guion"], height=200,
                             key=f"vid_{g['titulo']}")
                st.caption(f"Texto en pantalla: {g['texto_en_pantalla']}")
    with tabs[2]:
        for _, m in contenido.mensajes_prospeccion(datos).iterrows():
            with st.expander(f"{m['canal']} · {m['momento']}"):
                st.text_area("Mensaje", m["mensaje"], height=180,
                             key=f"pros_{m['canal']}_{m['momento']}")
    with tabs[3]:
        st.dataframe(contenido.calendario(datos), width="stretch", hide_index=True)
    with tabs[4]:
        inv = st.slider("Inversión mensual (USD)", 0, 1500, 300, 50, key="pauta")
        st.dataframe(contenido.presupuesto_pauta(float(inv)), width="stretch",
                     hide_index=True)

    st.markdown("---")
    st.markdown("#### Kit completo")
    _export("contenido", contenido.secciones_para_kit(datos))


# ---------------------------------------------------------------------------
else:  # Verificación del producto
    st.title("Verificación del producto")
    st.caption("Ejecuta de verdad cada pieza de la cadena de venta y reporta "
               "el resultado. Conviene correrlo antes de cada demo con un "
               "cliente.")

    if st.button("Ejecutar verificación end-to-end", type="primary"):
        with st.spinner("Ejecutando la cadena completa…"):
            resultados = verificacion.verificar_todo()
            res = verificacion.resumen(resultados)
        st.session_state.verif = (verificacion.tabla(resultados), res)

    if "verif" in st.session_state:
        tabla, res = st.session_state.verif
        c = st.columns(4)
        c[0].metric("Controles OK", res["ok"])
        c[1].metric("Advertencias", res["advertencias"])
        c[2].metric("Fallas", res["fallas"])
        c[3].metric("Puntaje", f"{res['puntaje_sobre_10']}/10")

        if res["vendible"]:
            st.success("Producto vendible: no hay fallas. Las advertencias son "
                       "configuración de producción pendiente, no defectos.")
        else:
            st.error("Hay fallas: no salir a vender hasta resolverlas.")

        def _color(fila):
            c = {"OK": "background-color:#E8F8EF", "ADVERTENCIA": "background-color:#FFF6E5",
                 "FALLA": "background-color:#FDEBEA"}.get(fila["estado"], "")
            return [c] * len(fila)

        st.dataframe(tabla.style.apply(_color, axis=1), width="stretch",
                     hide_index=True)
        _export("verificacion",
                [("Verificación end-to-end",
                  f"{res['ok']} OK, {res['advertencias']} advertencias, "
                  f"{res['fallas']} fallas. Puntaje {res['puntaje_sobre_10']}/10.",
                  tabla)])
    else:
        st.info("Todavía no se ejecutó. También se puede correr desde la "
                "terminal con `python3 -m plania.verificacion`.")
