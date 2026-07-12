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


def test_trial_es_3_dias():
    from backend_venta import licencias
    assert licencias.PLANES["trial"]["dias"] == 3
    assert licencias.PLANES["trial"]["precio"] == 0.0


def test_backend_endpoints():
    from fastapi.testclient import TestClient
    from backend_venta.app import app
    c = TestClient(app)
    assert c.get("/salud").json()["ok"]
    planes = c.get("/planes").json()
    assert "trial" in planes and "pro" in planes
    r = c.post("/licencias/trial", json={"email": "demo1@test.uy"})
    assert r.status_code == 200 and r.json()["dias"] == 3
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

    # 1) demo local vencida (instalada hace 5 días)
    pconfig.guardar_extra("LICENCIA_JWT", "")
    inicio_viejo = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
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
