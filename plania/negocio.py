"""
Plania · Modelo de negocio ejecutable (rentabilidad, escenarios, mercados)
=========================================================================
Simula mes a mes el negocio REAL de vender Plania en Uruguay empezando como
**un especialista solo** que implementa el producto contra la base/ERP de
cada empresa, y escalando a equipo cuando la capacidad se satura.

Por qué un modelo ejecutable y no una planilla en un documento: los números
de un doc envejecen y nadie los puede auditar. Acá cada supuesto es una
constante con nombre, la simulación es determinista y los resultados se
recalculan (y se exportan a PDF/Excel) cuando cambiás un supuesto.

Lo que el modelo respeta y una proyección optimista suele ignorar:

  1. **Capacidad horaria**: un solo implementador tiene ~160 h/mes, y cada
     implementación de ERP consume 12-20 h. Eso —no la demanda— es el techo
     real de los primeros meses.
  2. **Régimen tributario uruguayo**: se arranca en Monotributo (cuota fija)
     y al superar el tope de facturación se pasa a régimen general con IRAE
     sobre la utilidad. El salto es un escalón, no una curva.
  3. **Churn**: los clientes se van. Sin churn toda proyección SaaS miente.
  4. **Costo de contratar**: en Uruguay el costo empresa es ~1,55x el sueldo
     nominal por aportes y cargas.
  5. **Caja vs. resultado**: la implementación se cobra una vez y la
     suscripción es recurrente; el mes 1 de un cliente no se parece al mes 12.

TODOS LOS IMPORTES ESTÁN EN USD salvo aclaración. Los supuestos tributarios
y de costo laboral están marcados con [VERIFICAR] donde corresponde
confirmarlos con un contador antes de tomar decisiones de plata.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Precios del producto (fuente de verdad: backend_venta/licencias.py)
# ---------------------------------------------------------------------------
PRECIO_STARTER = 59.0
PRECIO_PRO = 129.0
PRECIO_ENTERPRISE = 420.0   # promedio de contratos "a medida" cerrados

# ---------------------------------------------------------------------------
# Parámetros de Uruguay [VERIFICAR con contador antes de decisiones de plata]
# ---------------------------------------------------------------------------
# Fuentes consultadas (julio 2026) — ver docs/ANALISIS_NEGOCIO.md:
#   · Monotributo: tope unipersonal $U 1.175.537/año; cuota BPS + FONASA.
#   · MercadoPago UY: comisión 1,8%-4,99% + IVA según medio y plazo.
#   · INE/ANDE: 148.500 micro + 21.000 pequeñas + 5.000 medianas + 850 grandes.
#   · Sueldos UY: programador semi-senior $U 71.000-105.000 nominales/mes.
TIPO_CAMBIO_UYU = 40.0          # UYU por USD (referencia de trabajo)
MONOTRIBUTO_CUOTA_MES = 155.0   # cuota BPS + FONASA (~$U 6.200) [VERIFICAR categoría]
MONOTRIBUTO_TOPE_ANUAL = 29_400.0   # $U 1.175.537 al tipo de cambio de trabajo
IRAE_TASA = 0.25                # impuesto a la renta empresarial
COSTO_EMPRESA_SOBRE_SUELDO = 1.55   # cargas sociales y aportes patronales
# Se toma el extremo alto del rango de MercadoPago: la suscripción mensual se
# cobra con tarjeta de crédito, que es el medio más caro. Con débito o
# transferencia baja a ~2,5% y el margen mejora.
COMISION_MERCADOPAGO = 0.055

# Costo marginal de IA por consulta del copiloto (Haiku: ~1.5k tok in,
# ~0.3k tok out). Es deliberadamente bajo: el motor local resuelve la mayoría
# de las consultas sin llamar a la API.
COSTO_IA_POR_CONSULTA = 0.003
CONSULTAS_PROMEDIO_MES = 220    # consumo real observado por cliente activo


@dataclass
class Costos:
    """Estructura de costos del negocio, en USD/mes salvo indicación."""
    servidor_y_dominio: float = 35.0
    contador: float = 90.0
    herramientas: float = 40.0          # GitHub, correo, diseño, misc
    contador_regimen_general: float = 180.0   # el contador se encarece al salir de monotributo
    sueldo_implementador: float = 1_950.0     # nominal mensual de un implementador semi-senior
    sueldo_vendedor: float = 1_500.0          # nominal mensual de un comercial

    def fijos_base(self) -> float:
        return self.servidor_y_dominio + self.herramientas


@dataclass
class Escenario:
    """Un escenario de demanda y ejecución comercial.

    Los tres escenarios de fábrica (conservador / base / optimista) no son
    "malo, medio, bueno" arbitrarios: se diferencian en las tres variables
    que de verdad mueven la aguja — cuántos leads llegan, qué porcentaje
    cierra, y cuánto duran los clientes.
    """
    nombre: str

    # --- demanda ---
    leads_organicos_mes: float          # prospección propia, referidos iniciales, redes orgánicas
    leads_por_100_usd_ads: float        # eficiencia de la pauta (inversa del CPL)
    conv_lead_demo: float               # % de leads que instalan la demo de 7 días
    conv_demo_cliente: float            # % de demos que se convierten en cliente pago
    referidos_por_cliente_mes: float    # leads extra que genera cada cliente activo

    # --- precios y mix ---
    precio_implementacion: float        # cobro único por conectar el ERP y capacitar
    mix_planes: dict                    # participación de cada plan en los clientes nuevos

    # --- retención ---
    churn_mensual: float                # % de clientes activos que se dan de baja cada mes

    # --- ejecución (capacidad) ---
    horas_implementacion: float         # horas por implementación de ERP
    horas_soporte_cliente_mes: float    # horas mensuales de soporte por cliente activo
    horas_venta_mes: float              # horas del fundador dedicadas a vender y administrar

    # --- ciclo comercial ---
    # Meses entre que el lead entra y firma. Vender software de gestión a una
    # PyME no es un checkout: hay demo, hay que convencer al dueño y al
    # encargado de depósito, y suele haber un "hablemos el mes que viene".
    # Ignorar este retraso es el error más común de las proyecciones SaaS.
    ciclo_venta_meses: int = 2

    def arpu(self) -> float:
        """Ingreso mensual promedio por cliente, según el mix de planes."""
        precios = {"starter": PRECIO_STARTER, "pro": PRECIO_PRO,
                   "enterprise": PRECIO_ENTERPRISE}
        return sum(precios[p] * peso for p, peso in self.mix_planes.items())


# ---------------------------------------------------------------------------
# Los tres escenarios
# ---------------------------------------------------------------------------
CONSERVADOR = Escenario(
    nombre="Conservador",
    leads_organicos_mes=6,
    leads_por_100_usd_ads=6,        # CPL ~USD 16
    conv_lead_demo=0.30,
    conv_demo_cliente=0.10,
    referidos_por_cliente_mes=0.05,
    precio_implementacion=450.0,
    mix_planes={"starter": 0.65, "pro": 0.30, "enterprise": 0.05},
    churn_mensual=0.045,
    horas_implementacion=20,
    horas_soporte_cliente_mes=1.5,
    horas_venta_mes=50,
    ciclo_venta_meses=3,
)

BASE = Escenario(
    nombre="Base",
    leads_organicos_mes=10,
    leads_por_100_usd_ads=9,        # CPL ~USD 11
    conv_lead_demo=0.40,
    conv_demo_cliente=0.16,
    referidos_por_cliente_mes=0.10,
    precio_implementacion=700.0,
    mix_planes={"starter": 0.50, "pro": 0.40, "enterprise": 0.10},
    churn_mensual=0.030,
    horas_implementacion=15,
    horas_soporte_cliente_mes=1.0,
    horas_venta_mes=45,
    ciclo_venta_meses=2,
)

OPTIMISTA = Escenario(
    nombre="Optimista",
    leads_organicos_mes=16,
    leads_por_100_usd_ads=13,       # CPL ~USD 8
    conv_lead_demo=0.50,
    conv_demo_cliente=0.24,
    referidos_por_cliente_mes=0.18,
    precio_implementacion=950.0,
    mix_planes={"starter": 0.35, "pro": 0.45, "enterprise": 0.20},
    churn_mensual=0.020,
    horas_implementacion=12,
    horas_soporte_cliente_mes=0.8,
    horas_venta_mes=40,
    ciclo_venta_meses=1,
)

ESCENARIOS = {e.nombre: e for e in (CONSERVADOR, BASE, OPTIMISTA)}

# Lo que este mismo perfil (implementador de ERP con experiencia) gana
# empleado en Uruguay. Es la vara real: el negocio recién "conviene" cuando
# el retiro del fundador supera esto de forma sostenida. [VERIFICAR]
SUELDO_REFERENCIA_EMPLEADO = 2_200.0

# Los primeros meses no se arranca con la agenda llena: la red de contactos
# tarda en activarse y la pauta necesita aprendizaje.
RAMPA_ORGANICA = (0.4, 0.7, 0.9)   # multiplicador de leads orgánicos, meses 1-3

HORAS_MES_FUNDADOR = 160.0
HORAS_MES_EMPLEADO = 160.0
EFICIENCIA_EMPLEADO = 0.85     # un empleado factura ~85% de sus horas


def simular(escenario: Escenario,
            meses: int = 18,
            inversion_ads_mes: float = 0.0,
            costos: Costos | None = None,
            contratar: bool = True) -> pd.DataFrame:
    """
    Simula el negocio mes a mes y devuelve una fila por mes.

    El orden de la simulación importa y es el de la vida real:
      1. Llegan leads (orgánicos + pauta + referidos de la base instalada),
         con rampa los primeros meses.
      2. Los leads hacen la demo de 7 días y **cierran recién unos meses
         después** (`ciclo_venta_meses`); al firmar se implementan hasta
         donde da la capacidad horaria y lo que no entra queda en backlog.
      3. Los clientes activos pagan suscripción y consumen soporte.
      4. Se pierden clientes por churn.
      5. Se pagan costos, se decide contratar y se liquidan impuestos.
    """
    costos = costos or Costos()
    filas = []

    clientes = 0.0
    backlog = 0.0            # clientes vendidos que esperan implementación
    empleados = 0
    caja = 0.0
    historial_ingresos: list[float] = []
    # Pipeline: las ventas de un mes son las demos de hace `ciclo_venta_meses`.
    cierres_programados = [0.0] * (meses + escenario.ciclo_venta_meses + 2)

    for mes in range(1, meses + 1):
        # --- 1. demanda -----------------------------------------------------
        rampa = RAMPA_ORGANICA[mes - 1] if mes <= len(RAMPA_ORGANICA) else 1.0
        leads = (escenario.leads_organicos_mes * rampa
                 + inversion_ads_mes / 100.0 * escenario.leads_por_100_usd_ads * rampa
                 + clientes * escenario.referidos_por_cliente_mes)
        demos = leads * escenario.conv_lead_demo
        # estas demos recién cierran cuando termina el ciclo de venta
        cierres_programados[mes + escenario.ciclo_venta_meses] += (
            demos * escenario.conv_demo_cliente)
        vendidos = cierres_programados[mes] + backlog

        # --- 2. capacidad ---------------------------------------------------
        horas_totales = (HORAS_MES_FUNDADOR - escenario.horas_venta_mes
                         + empleados * HORAS_MES_EMPLEADO * EFICIENCIA_EMPLEADO)
        horas_soporte = clientes * escenario.horas_soporte_cliente_mes
        horas_libres = max(0.0, horas_totales - horas_soporte)
        implementables = horas_libres / escenario.horas_implementacion
        nuevos = min(vendidos, implementables)
        backlog = max(0.0, vendidos - nuevos)

        # --- 3. ingresos ----------------------------------------------------
        ingreso_impl = nuevos * escenario.precio_implementacion
        # los clientes nuevos pagan su primera mensualidad prorrateada a medio mes
        clientes_facturables = clientes + nuevos * 0.5
        ingreso_susc = clientes_facturables * escenario.arpu()
        ingreso_total = ingreso_impl + ingreso_susc

        # --- 4. churn -------------------------------------------------------
        bajas = clientes * escenario.churn_mensual
        clientes = clientes + nuevos - bajas

        # --- 5. costos ------------------------------------------------------
        costo_ia = clientes * CONSULTAS_PROMEDIO_MES * COSTO_IA_POR_CONSULTA
        comision = ingreso_total * COMISION_MERCADOPAGO
        sueldos = empleados * costos.sueldo_implementador * COSTO_EMPRESA_SOBRE_SUELDO

        historial_ingresos.append(ingreso_total)
        ingresos_12m = sum(historial_ingresos[-12:])
        regimen_general = ingresos_12m > MONOTRIBUTO_TOPE_ANUAL or empleados > 0

        contador = (costos.contador_regimen_general if regimen_general
                    else costos.contador)
        fijos = costos.fijos_base() + contador
        cuota_fija = 0.0 if regimen_general else MONOTRIBUTO_CUOTA_MES

        antes_de_impuestos = (ingreso_total - costo_ia - comision - sueldos
                              - fijos - cuota_fija - inversion_ads_mes)
        impuesto_renta = (max(0.0, antes_de_impuestos) * IRAE_TASA
                          if regimen_general else 0.0)
        neto = antes_de_impuestos - impuesto_renta
        caja += neto

        # --- 6. contratación (se decide con el mes ya cerrado) --------------
        horas_necesarias_prox = ((clientes * escenario.horas_soporte_cliente_mes)
                                 + (vendidos * escenario.horas_implementacion))
        capacidad_actual = (HORAS_MES_FUNDADOR - escenario.horas_venta_mes
                            + empleados * HORAS_MES_EMPLEADO * EFICIENCIA_EMPLEADO)
        costo_nuevo_empleado = costos.sueldo_implementador * COSTO_EMPRESA_SOBRE_SUELDO
        if (contratar and horas_necesarias_prox > capacidad_actual
                and neto > costo_nuevo_empleado * 1.3):
            # solo se contrata si el mes paga el sueldo con 30% de colchón
            empleados += 1

        filas.append({
            "mes": mes,
            "leads": round(leads, 1),
            "demos": round(demos, 1),
            "clientes_nuevos": round(nuevos, 2),
            "backlog": round(backlog, 2),
            "clientes_activos": round(clientes, 1),
            "mrr": round(clientes * escenario.arpu(), 2),
            "ingreso_implementacion": round(ingreso_impl, 2),
            "ingreso_suscripcion": round(ingreso_susc, 2),
            "ingreso_total": round(ingreso_total, 2),
            "costos_operativos": round(costo_ia + comision + fijos + cuota_fija, 2),
            "marketing": round(inversion_ads_mes, 2),
            "sueldos": round(sueldos, 2),
            "impuesto_renta": round(impuesto_renta, 2),
            "resultado_neto": round(neto, 2),
            "vs_sueldo_empleado": round(neto - SUELDO_REFERENCIA_EMPLEADO, 2),
            "caja_acumulada": round(caja, 2),
            "empleados": empleados,
            "regimen": "General (IRAE)" if regimen_general else "Monotributo",
            "horas_ocupadas_pct": round(
                min(999, (horas_soporte + nuevos * escenario.horas_implementacion)
                    / max(1e-9, horas_totales) * 100), 1),
        })

    return pd.DataFrame(filas)


HORIZONTES = (1, 3, 6, 12, 18)


def resumen_horizontes(df: pd.DataFrame,
                       horizontes: tuple = HORIZONTES) -> pd.DataFrame:
    """Corta la simulación en los cortes que se miran para decidir."""
    filas = []
    for h in horizontes:
        if h > len(df):
            continue
        p = df.head(h)
        ultimo = p.iloc[-1]
        filas.append({
            "horizonte_meses": h,
            "clientes_activos": ultimo["clientes_activos"],
            "mrr_usd": ultimo["mrr"],
            "ingreso_acumulado": round(p["ingreso_total"].sum(), 2),
            "costo_acumulado": round((p["costos_operativos"] + p["marketing"]
                                      + p["sueldos"] + p["impuesto_renta"]).sum(), 2),
            "resultado_neto_acumulado": round(p["resultado_neto"].sum(), 2),
            "margen_neto_pct": round(
                p["resultado_neto"].sum() / max(1e-9, p["ingreso_total"].sum()) * 100, 1),
            "caja_final": ultimo["caja_acumulada"],
            "empleados": int(ultimo["empleados"]),
        })
    return pd.DataFrame(filas)


def mes_de_equilibrio(df: pd.DataFrame) -> int | None:
    """Primer mes con resultado neto positivo sostenido (no un pico aislado)."""
    for i in range(len(df) - 1):
        if df.iloc[i]["resultado_neto"] > 0 and df.iloc[i + 1]["resultado_neto"] > 0:
            return int(df.iloc[i]["mes"])
    return None


def mes_supera_sueldo(df: pd.DataFrame) -> int | None:
    """Primer mes en que el negocio le deja al fundador, de forma sostenida,
    más de lo que ganaría empleado. Es la pregunta que de verdad importa
    antes de dejar un trabajo: no "¿da ganancia?" sino "¿me da de vivir?"."""
    for i in range(len(df) - 1):
        if (df.iloc[i]["resultado_neto"] > SUELDO_REFERENCIA_EMPLEADO
                and df.iloc[i + 1]["resultado_neto"] > SUELDO_REFERENCIA_EMPLEADO):
            return int(df.iloc[i]["mes"])
    return None


def caja_minima(df: pd.DataFrame) -> float:
    """Peor punto de caja acumulada: cuánto capital hay que tener guardado
    para llegar sin ahogarse."""
    return round(float(df["caja_acumulada"].min()), 2)


def unit_economics(escenario: Escenario, inversion_ads_mes: float,
                   df: pd.DataFrame) -> dict:
    """CAC, LTV y payback — las tres cifras que definen si el negocio escala."""
    nuevos_total = df["clientes_nuevos"].sum()
    ads_total = df["marketing"].sum()
    # el tiempo de venta del fundador se valoriza a su costo de oportunidad
    costo_hora_fundador = 25.0
    costo_venta = ads_total + escenario.horas_venta_mes * costo_hora_fundador * len(df)
    cac = costo_venta / max(1e-9, nuevos_total)

    arpu = escenario.arpu()
    margen_bruto = 1 - COMISION_MERCADOPAGO - (
        CONSULTAS_PROMEDIO_MES * COSTO_IA_POR_CONSULTA / max(1e-9, arpu))
    vida_meses = 1 / escenario.churn_mensual
    ltv = arpu * margen_bruto * vida_meses + escenario.precio_implementacion * 0.6

    return {
        "arpu_mensual": round(arpu, 2),
        "margen_bruto_pct": round(margen_bruto * 100, 1),
        "vida_promedio_meses": round(vida_meses, 1),
        "cac": round(cac, 2),
        "ltv": round(ltv, 2),
        "ltv_sobre_cac": round(ltv / max(1e-9, cac), 2),
        "payback_meses": round(cac / max(1e-9, arpu * margen_bruto), 1),
        "clientes_captados": round(nuevos_total, 1),
    }


def comparativa_escenarios(meses: int = 18,
                           inversiones: tuple = (0.0, 300.0)) -> pd.DataFrame:
    """La tabla que responde la pregunta central: con y sin inversión en
    redes, en los tres escenarios, a 1/3/6/12/18 meses."""
    filas = []
    for nombre, esc in ESCENARIOS.items():
        for ads in inversiones:
            df = simular(esc, meses=meses, inversion_ads_mes=ads)
            res = resumen_horizontes(df)
            equilibrio = mes_de_equilibrio(df)
            supera = mes_supera_sueldo(df)
            for _, r in res.iterrows():
                filas.append({
                    "escenario": nombre,
                    "inversion_redes_mes": ads,
                    "horizonte_meses": int(r["horizonte_meses"]),
                    "clientes_activos": r["clientes_activos"],
                    "mrr_usd": r["mrr_usd"],
                    "ingreso_acumulado": r["ingreso_acumulado"],
                    "resultado_neto_acumulado": r["resultado_neto_acumulado"],
                    "margen_neto_pct": r["margen_neto_pct"],
                    "empleados": r["empleados"],
                    "mes_equilibrio": equilibrio if equilibrio else "no alcanzado",
                    "mes_supera_sueldo": supera if supera else "no alcanzado",
                    "caja_minima": caja_minima(df),
                })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Mercado potencial
# ---------------------------------------------------------------------------
# TAM  = universo teórico de empresas que podrían usar Plania
# SAM  = las que además tienen ERP/base y volumen que justifica el gasto
# SOM  = las que este equipo puede realmente alcanzar y atender en 18 meses
#
# Las cantidades de empresas son estimaciones de orden de magnitud a partir
# de estadísticas públicas de PyMEs (INE/DINAPYME en Uruguay, censos
# equivalentes en la región). Sirven para dimensionar la oportunidad, no
# como padrón: [VERIFICAR] antes de usarlas en una presentación a inversores.
MERCADOS = {
    "Uruguay": {
        # INE/ANDE: 148.500 micro + 21.000 pequeñas + 5.000 medianas + 850 grandes.
        "empresas_totales": 175_350,
        # TAM = pequeñas (5-19 empleados) y medianas del sector comercio, que es
        # el 33,3% del padrón. Las microempresas de hasta 4 personas quedan
        # fuera a propósito: no pagan USD 59/mes por un software adicional.
        "tam_empresas": 8_700,
        "sam_empresas": 3_200,      # de esas, con ERP/base digitalizada y stock relevante
        "som_18m_empresas": 45,     # alcance real de un equipo de 1-3 personas
        "ticket_anual_usd": 1_650,  # suscripción anual + implementación amortizada
        "notas": "Mercado chico pero alcanzable a pie: el boca a boca y una "
                 "reunión presencial cierran ventas que en otros países exigen "
                 "pauta. Contra: es un gasto ADICIONAL al ERP que ya pagan "
                 "($U 1.500-5.000/mes), así que la venta se gana mostrando "
                 "retorno, no funcionalidades.",
    },
    "LATAM": {
        "empresas_totales": 27_000_000,
        "tam_empresas": 850_000,
        "sam_empresas": 190_000,
        "som_18m_empresas": 120,    # requiere partners locales y pauta sostenida
        "ticket_anual_usd": 1_450,  # precio promedio menor por competencia regional
        "notas": "Argentina, Chile, Paraguay y Perú comparten idioma, ERPs "
                 "similares y MercadoPago. El límite no es la demanda sino la "
                 "capacidad de implementar a distancia.",
    },
    "Mundo": {
        "empresas_totales": 330_000_000,
        "tam_empresas": 9_500_000,
        "sam_empresas": 1_400_000,
        "som_18m_empresas": 25,     # sin equipo en destino, es marginal
        "ticket_anual_usd": 2_400,
        "notas": "Solo tiene sentido en modo self-service puro (sin "
                 "implementación asistida) y en inglés. Es una apuesta de "
                 "año 2-3, no del plan inicial.",
    },
}


def potencial_mercados() -> pd.DataFrame:
    filas = []
    for nombre, m in MERCADOS.items():
        filas.append({
            "mercado": nombre,
            "empresas_totales": m["empresas_totales"],
            "TAM_empresas": m["tam_empresas"],
            "TAM_usd_anual": m["tam_empresas"] * m["ticket_anual_usd"],
            "SAM_empresas": m["sam_empresas"],
            "SAM_usd_anual": m["sam_empresas"] * m["ticket_anual_usd"],
            "SOM_18m_empresas": m["som_18m_empresas"],
            "SOM_18m_usd_anual": m["som_18m_empresas"] * m["ticket_anual_usd"],
            "penetracion_SOM_sobre_SAM_pct": round(
                m["som_18m_empresas"] / m["sam_empresas"] * 100, 3),
        })
    return pd.DataFrame(filas)


def sensibilidad(variable: str, valores: list, escenario: Escenario | None = None,
                 meses: int = 12, inversion_ads_mes: float = 300.0) -> pd.DataFrame:
    """Cuánto mueve la aguja cada supuesto. Sirve para saber dónde poner el
    esfuerzo: casi siempre gana bajar el churn o subir la conversión antes
    que subir el precio."""
    escenario = escenario or BASE
    filas = []
    for v in valores:
        esc = replace(escenario, **{variable: v})
        df = simular(esc, meses=meses, inversion_ads_mes=inversion_ads_mes)
        filas.append({
            variable: v,
            "clientes_mes_12": df.iloc[-1]["clientes_activos"],
            "mrr_mes_12": df.iloc[-1]["mrr"],
            "neto_acumulado": round(df["resultado_neto"].sum(), 2),
        })
    return pd.DataFrame(filas)


def secciones_para_informe(meses: int = 18) -> list:
    """Arma el informe completo listo para exportar a PDF/Word/Excel con
    `plania.exportes` — el material que se lleva a una reunión."""
    comp = comparativa_escenarios(meses=meses)
    resumen_txt = []
    for nombre, esc in ESCENARIOS.items():
        for ads in (0.0, 300.0):
            df = simular(esc, meses=meses, inversion_ads_mes=ads)
            eq = mes_de_equilibrio(df)
            sup = mes_supera_sueldo(df)
            ue = unit_economics(esc, ads, df)
            etiqueta = "con" if ads else "sin"
            resumen_txt.append(
                f"{nombre} ({etiqueta} inversión en redes): "
                f"{df.iloc[-1]['clientes_activos']:.0f} clientes y "
                f"USD {df.iloc[-1]['mrr']:,.0f} de MRR al mes {meses}; "
                f"equilibrio en mes {eq if eq else 'no alcanzado'}; "
                f"supera el sueldo de empleado en mes "
                f"{sup if sup else 'no alcanzado'}; "
                f"caja mínima USD {caja_minima(df):,.0f}; "
                f"LTV/CAC {ue['ltv_sobre_cac']}.")

    secciones = [
        ("Resumen ejecutivo",
         " · ".join(resumen_txt),
         None),
        ("Comparativa de escenarios",
         "Los tres escenarios a 1, 3, 6, 12 y 18 meses, con y sin inversión "
         "mensual de USD 300 en redes. El resultado neto ya descuenta "
         "comisión de MercadoPago, costo de IA, servidor, contador, "
         "monotributo o IRAE según corresponda, sueldos y pauta.",
         comp),
        ("Mercado potencial",
         "TAM, SAM y SOM por mercado. El SOM a 18 meses está limitado por la "
         "capacidad de implementación del equipo, no por la demanda.",
         potencial_mercados()),
        ("Sensibilidad al churn",
         "Qué pasa si los clientes duran más o menos. Es la variable que más "
         "mueve el resultado a 12 meses.",
         sensibilidad("churn_mensual", [0.015, 0.02, 0.03, 0.045, 0.06])),
        ("Sensibilidad a la conversión demo a cliente",
         "El segundo factor de mayor impacto: cuántas demos de 7 días "
         "terminan en una venta.",
         sensibilidad("conv_demo_cliente", [0.08, 0.12, 0.16, 0.20, 0.28])),
    ]
    for nombre, esc in ESCENARIOS.items():
        df = simular(esc, meses=meses, inversion_ads_mes=300.0)
        secciones.append((f"Detalle mensual · {nombre} (con redes)",
                          f"Simulación mes a mes del escenario {nombre.lower()} "
                          "con USD 300/mes de pauta.", df))
    return secciones
