"""Tests de Plania: dataset, conectores, analítica, sugerencias, copiloto,
exportes, rutas, licencias y backend de venta."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

os.environ["PLANIA_CONFIG_DIR"] = "/tmp/plania_test_config"
os.environ["PLANIA_USO_DB"] = "/tmp/plania_test_uso.db"
for _f in ("/tmp/plania_test_uso.db",):
    if os.path.exists(_f):
        os.remove(_f)

from data import generate_dataset  # noqa: E402
from plania import analitica, conectores, copiloto, exportes, rutas, sugerencias  # noqa: E402


@pytest.fixture(scope="session")
def datos():
    if not os.path.exists(os.path.join(RAIZ, "data", "erp_demo.db")):
        generate_dataset.main(seed=42)
    return conectores.cargar_datos()


@pytest.fixture(scope="session")
def v(datos):
    return analitica.enriquecer_ventas(datos["ventas"], datos["productos"],
                                       datos["clientes"])


# ---------------------------------------------------------------------------
# Conectores: el diferenciador "cualquier ERP/BD"
# ---------------------------------------------------------------------------
def test_autodetecta_columnas_de_erp_ajeno():
    df = pd.DataFrame({"cod_articulo": ["A1"], "descripcion": ["Yerba"],
                       "rubro": ["Almacén"], "precio_venta": [100.0],
                       "costo_unitario": [70.0], "stock_actual": [5]})
    out = conectores.normalizar(df, "productos")
    assert list(out["sku"]) == ["A1"]
    assert out.iloc[0]["precio"] == 100.0
    assert out.iloc[0]["stock"] == 5


def test_autodetecta_esquema_odoo_y_sap():
    odoo = pd.DataFrame({"default_code": ["X"], "name": ["Prod"],
                         "list_price": [10], "standard_price": [6],
                         "qty_available": [3]})
    assert conectores.normalizar(odoo, "productos").iloc[0]["sku"] == "X"
    sap = pd.DataFrame({"ItemCode": ["Y"], "ItemName": ["Prod"],
                        "Price": [10], "OnHand": [2]})
    assert conectores.normalizar(sap, "productos").iloc[0]["sku"] == "Y"


def test_falla_claro_si_faltan_obligatorias():
    with pytest.raises(ValueError, match="obligatorias"):
        conectores.normalizar(pd.DataFrame({"x": [1]}), "productos")


def test_carga_completa_desde_sqlite(datos):
    assert set(datos) == {"productos", "clientes", "ventas"}
    assert len(datos["productos"]) > 100
    assert "sku" in datos["productos"].columns
    assert pd.api.types.is_datetime64_any_dtype(
        pd.to_datetime(datos["ventas"]["fecha"]))


# ---------------------------------------------------------------------------
# Analítica
# ---------------------------------------------------------------------------
def test_kpis_consistentes(datos, v):
    k = analitica.kpis(datos["productos"], v)
    assert k["venta_periodo"] > 0
    assert 0 < k["margen_pct"] < 100
    assert k["valor_stock"] == pytest.approx(
        float((datos["productos"]["stock"] * datos["productos"]["costo"]).sum()))


def test_enriquecer_es_idempotente(datos, v):
    v2 = analitica.enriquecer_ventas(v, datos["productos"], datos["clientes"])
    assert v2 is v


def test_rotacion_dias_stock(datos, v):
    r = analitica.rotacion(datos["productos"], v)
    con_venta = r[r["venta_diaria"] > 0]
    assert (con_venta["dias_stock"] >= 0).all()
    assert np.isinf(r[r["venta_diaria"] == 0]["dias_stock"]).all()


# ---------------------------------------------------------------------------
# Sugerencias
# ---------------------------------------------------------------------------
def test_ofertas_nunca_debajo_del_piso(datos, v):
    of = sugerencias.ofertas_por_sobrestock(datos["productos"], v)
    assert len(of) > 0
    piso = of.merge(datos["productos"][["sku", "costo"]], on="sku")
    assert (piso["precio_oferta"] >= piso["costo"] * 1.079).all()  # costo+8% (redondeo)
    assert (of["descuento_pct"] <= 30.001).all()


def test_reposicion_solo_lo_que_rota(datos, v):
    rep = sugerencias.reposicion(datos["productos"], v)
    assert (rep["cantidad_sugerida"] > 0).all()
    assert (rep["venta_en_riesgo"] > 0).all()


def test_precios_subas_acotadas(datos, v):
    pr = sugerencias.precios(datos["productos"], v)
    if len(pr):
        assert (pr["suba_pct"] > 0).all()
        assert (pr["suba_pct"] < 25).all()


def test_paquete_completo(datos):
    paq = sugerencias.generar_todas(datos)
    assert {"ofertas", "reposicion", "precios", "zonas", "recupero",
            "resumen"} <= set(paq)
    assert paq["resumen"]["capital_liberable"] >= 0


# ---------------------------------------------------------------------------
# Copiloto: responde con datos reales
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pregunta,clave", [
    ("¿qué ofertas armo esta semana?", "sobrestock"),
    ("¿qué repongo ya?", "riesgo"),
    ("stock de bebidas", "unidades"),
    ("ventas por tipo de negocio", "lidera"),
    ("¿qué clientes perdí?", "dejaron"),
])
def test_copiloto_intenciones(datos, pregunta, clave):
    r = copiloto.responder(pregunta, datos)
    assert clave.lower() in r["respuesta"].lower()
    assert r["titulo"]


def test_copiloto_fallback_no_rompe(datos):
    r = copiloto.responder("hola", datos)
    assert "resumen" in r["respuesta"].lower() or "stock" in r["respuesta"].lower()


# ---------------------------------------------------------------------------
# Exportes: PDF/Word/Excel válidos
# ---------------------------------------------------------------------------
def test_exportes_formatos(datos):
    paq = sugerencias.generar_todas(datos)
    secc = exportes.secciones_desde_paquete(paq)
    pdf = exportes.a_pdf("Informe", secc)
    assert pdf[:4] == b"%PDF"
    docx = exportes.a_word("Informe", secc)
    assert docx[:2] == b"PK"  # zip (OOXML)
    xlsx = exportes.a_excel(secc)
    assert xlsx[:2] == b"PK"


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
def test_rutas_cubren_todos_los_clientes(datos):
    cli = datos["clientes"].head(40)
    plan = rutas.planificar(cli, vehiculos=2)
    assert len(plan["rutas"]) == len(cli.dropna(subset=["lat", "lon"]))
    assert plan["resumen"]["paradas"].sum() == len(plan["rutas"])
    assert (plan["resumen"]["km_estimados"] > 0).all()


def test_rutas_sin_gps_agrupa_por_zona(datos):
    cli = datos["clientes"].head(20).drop(columns=["lat", "lon"])
    plan = rutas.planificar(cli, vehiculos=2)
    assert len(plan["rutas"]) == 20
    assert set(plan["rutas"]["vehiculo"]) <= {1, 2}


# ---------------------------------------------------------------------------
# Licencias y backend de venta
# ---------------------------------------------------------------------------
def test_licencia_jwt_ciclo_completo():
    from backend_venta import licencias
    lic = licencias.emitir_licencia("test@plania.uy", "trial")
    r = licencias.licencia_activa(lic)
    assert r["ok"]
    assert r["claims"]["plan"] == "trial"
    assert set(r["claims"]["features"]) == {"copiloto", "erp", "exportes", "rutas"}


def test_trial_es_7_dias():
    from backend_venta import licencias
    assert licencias.PLANES["trial"]["dias"] == 7
    assert licencias.PLANES["trial"]["precio"] == 0.0


def test_backend_endpoints():
    from fastapi.testclient import TestClient
    from backend_venta.app import app
    c = TestClient(app)
    assert c.get("/salud").json()["ok"]
    planes = c.get("/planes").json()
    assert "trial" in planes and "pro" in planes
    r = c.post("/licencias/trial", json={"email": "demo1@test.uy"})
    assert r.status_code == 200 and r.json()["dias"] == 7
    # segunda demo con el mismo email: rechazada
    assert c.post("/licencias/trial", json={"email": "demo1@test.uy"}).status_code == 409
    # checkout sin MP_ACCESS_TOKEN: 503 claro, no un 500 críptico
    os.environ.pop("MP_ACCESS_TOKEN", None)
    r = c.post("/checkout", json={"plan": "pro", "email": "x@y.uy"})
    assert r.status_code == 503


def test_licencia_cliente_demo_local():
    from plania import licencia
    est = licencia.estado()
    assert est["modo"] in ("demo", "licencia")
    assert "copiloto" in est["features"]


def test_e2e_demo_a_licencia_paga():
    """Circuito completo del cliente: demo local → compra → activación.
    (El pago real lo simula la emisión directa: el webhook de MP termina
    llamando exactamente a licencias.emitir_licencia.)"""
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from backend_venta import licencias
    from backend_venta.app import app
    from plania import config as pconfig
    from plania import licencia

    # 1) demo local vencida (instalada hace 10 días, más que los 7 de demo)
    pconfig.guardar_extra("LICENCIA_JWT", "")
    inicio_viejo = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    pconfig.guardar_extra("DEMO_INICIO", inicio_viejo)
    est = licencia.estado()
    assert est["modo"] == "vencida"
    assert est["features"] == []

    # 2) el cliente pide la demo por la landing y la activa en la app
    c = TestClient(app)
    r = c.post("/licencias/trial", json={"email": "e2e@plania.uy"})
    assert r.status_code == 200
    act = licencia.activar_licencia(r.json()["licencia"])
    assert act["ok"]
    est = licencia.estado()
    assert est["modo"] == "licencia" and est["plan"] == "trial"
    assert "rutas" in est["features"]

    # 3) paga → webhook emite plan pro → activa y desbloquea todo
    lic_pro = licencias.emitir_licencia("e2e@plania.uy", "pro")
    assert licencia.activar_licencia(lic_pro)["ok"]
    est = licencia.estado()
    assert est["plan"] == "pro" and licencia.tiene("rutas") and licencia.tiene("copiloto")

    # 4) contra el backend, esa licencia consulta su estado/cupo
    r = c.get("/licencias/estado", headers={"Authorization": f"Bearer {lic_pro}"})
    assert r.status_code == 200 and r.json()["cupo_mensual"] == 2000

    # limpiar para no afectar otros tests
    pconfig.guardar_extra("LICENCIA_JWT", "")
    pconfig.guardar_extra("DEMO_INICIO", "")


def test_archivos_subidos_quedan_como_fuente(datos, tmp_path):
    """CSV/Excel del ERP subidos por la UI → base SQLite → cargar_datos
    los lee igual que a cualquier ERP conectado."""
    ruta = str(tmp_path / "erp_archivos.db")
    url = conectores.guardar_como_base(
        {"productos": datos["productos"], "clientes": datos["clientes"],
         "ventas": datos["ventas"]}, ruta_db=ruta)
    releidos = conectores.cargar_datos(url=url)
    assert len(releidos["productos"]) == len(datos["productos"])
    assert len(releidos["ventas"]) == len(datos["ventas"])
    # y la analítica corre sobre lo releído sin fricción
    v = analitica.enriquecer_ventas(releidos["ventas"], releidos["productos"],
                                    releidos["clientes"])
    assert analitica.kpis(releidos["productos"], v)["venta_periodo"] > 0


@pytest.mark.parametrize("pregunta,clave", [
    ("¿cómo viene cada proveedor?", "proveedor principal"),
    ("¿cuánto vendí de congelados?", "unidades"),
])
def test_copiloto_intents_nuevos(datos, pregunta, clave):
    r = copiloto.responder(pregunta, datos)
    assert clave.lower() in r["respuesta"].lower()
    assert r["tabla"] is not None and len(r["tabla"])


# ---------------------------------------------------------------------------
# Modelo de negocio: la plata proyectada tiene que ser aritmética, no deseo
# ---------------------------------------------------------------------------
def test_simulacion_respeta_ciclo_de_venta():
    """Con ciclo de venta de N meses, no puede haber clientes antes del mes N+1.
    Es el error clásico de las proyecciones: cerrar ventas el mes uno."""
    from plania import negocio
    df = negocio.simular(negocio.BASE, meses=12, inversion_ads_mes=300.0)
    ciclo = negocio.BASE.ciclo_venta_meses
    assert df.head(ciclo)["clientes_nuevos"].sum() == 0
    assert df["clientes_activos"].iloc[-1] > 0


def test_simulacion_respeta_capacidad_horaria():
    """Nunca se pueden implementar más clientes que las horas disponibles."""
    from plania import negocio
    esc = negocio.OPTIMISTA
    df = negocio.simular(esc, meses=18, inversion_ads_mes=1500.0, contratar=False)
    horas_disp = negocio.HORAS_MES_FUNDADOR - esc.horas_venta_mes
    max_implementaciones = horas_disp / esc.horas_implementacion
    assert (df["clientes_nuevos"] <= max_implementaciones + 1e-6).all()
    # y la demanda excedente tiene que quedar registrada como backlog
    assert df["backlog"].max() > 0


def test_regimen_tributario_cambia_al_superar_el_tope():
    from plania import negocio
    df = negocio.simular(negocio.OPTIMISTA, meses=18, inversion_ads_mes=300.0)
    assert df.iloc[0]["regimen"] == "Monotributo"
    assert (df["regimen"] == "General (IRAE)").any()
    # en régimen general se paga IRAE sobre utilidad positiva
    general = df[(df["regimen"] == "General (IRAE)") & (df["resultado_neto"] > 0)]
    assert (general["impuesto_renta"] > 0).all()


def test_escenario_conservador_no_se_maquilla():
    """El conservador debe dar pérdida a 18 meses. Si algún cambio lo vuelve
    rentable, es que se aflojaron los supuestos sin querer."""
    from plania import negocio
    df = negocio.simular(negocio.CONSERVADOR, meses=18, inversion_ads_mes=0.0)
    assert df["resultado_neto"].sum() < 0
    assert negocio.mes_supera_sueldo(df) is None


def test_comparativa_cubre_todos_los_cortes():
    from plania import negocio
    comp = negocio.comparativa_escenarios(meses=18)
    assert set(comp["escenario"]) == set(negocio.ESCENARIOS)
    assert set(comp["horizonte_meses"]) == set(negocio.HORIZONTES)
    assert set(comp["inversion_redes_mes"]) == {0.0, 300.0}


def test_mercados_son_coherentes():
    """SOM <= SAM <= TAM <= total. Un mercado mal anidado invalida el análisis."""
    from plania import negocio
    for _, m in negocio.potencial_mercados().iterrows():
        assert m["SOM_18m_empresas"] <= m["SAM_empresas"] <= m["TAM_empresas"] <= m["empresas_totales"]


# ---------------------------------------------------------------------------
# Contenido para redes
# ---------------------------------------------------------------------------
def test_kit_de_contenido_usa_numeros_reales(datos):
    from plania import contenido
    posts = contenido.posts_linkedin(datos)
    assert len(posts) >= 5
    # La mayoría de los ganchos tiene que apoyarse en un número real: es lo
    # que diferencia un post que vende de uno genérico. No se exige el 100%
    # a propósito — un par de piezas de posicionamiento sin cifra le dan
    # variedad al feed y evitan que todo suene a la misma plantilla.
    con_numero = sum(any(ch.isdigit() for ch in g) for g in posts["gancho"])
    assert con_numero >= len(posts) * 0.8, (
        f"solo {con_numero}/{len(posts)} ganchos usan un dato concreto")
    assert len(contenido.calendario(datos)) == 12
    assert contenido.presupuesto_pauta(300.0)["usd_mes"].sum() == pytest.approx(300.0)


def test_contenido_avisa_cuando_son_datos_demo(datos):
    """Publicar números de la base demo como caso real sería fabricar un
    testimonio: el kit tiene que advertirlo solo."""
    from plania import contenido
    kit = contenido.secciones_para_kit(datos)
    if contenido._sobre_datos_demo():
        assert "EJEMPLO" in kit[0][1]


def test_kit_exporta_a_los_tres_formatos(datos):
    from plania import contenido, exportes
    kit = contenido.secciones_para_kit(datos)
    assert exportes.a_pdf("Kit", kit)[:4] == b"%PDF"
    assert exportes.a_word("Kit", kit)[:2] == b"PK"
    assert exportes.a_excel(kit)[:2] == b"PK"


# ---------------------------------------------------------------------------
# Verificación end-to-end y panel del dueño
# ---------------------------------------------------------------------------
def test_verificacion_end_to_end_sin_fallas():
    """El control maestro: si esto falla, el producto no se puede vender."""
    from plania import verificacion
    resultados = verificacion.verificar_todo()
    res = verificacion.resumen(resultados)
    fallas = [r.control for r in resultados if r.estado == verificacion.FALLA]
    assert not fallas, f"controles en falla: {fallas}"
    assert res["vendible"] is True
    assert res["puntaje_sobre_10"] >= 9.0


def test_owner_lee_el_negocio_sin_romperse():
    from plania import owner
    k = owner.kpis_negocio()
    for clave in ("demos_entregadas", "clientes_pagos", "mrr_usd", "conversion_pct"):
        assert clave in k
    assert owner.integridad_registros().get("ok") is True
