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


# ---------------------------------------------------------------------------
# Web pública trilingüe y video
# ---------------------------------------------------------------------------
def _guion():
    import sys, os
    sys.path.insert(0, os.path.join(RAIZ, "sitio"))
    import doblar_video
    return doblar_video, doblar_video.cargar_guion()


def test_vercel_publica_la_carpeta_correcta():
    """El vercel.json de la raíz es lo que hace que importar el repo en Vercel
    no requiera configurar nada. Si apunta a otro lado, el deploy sale vacío."""
    import json, os
    cfg = json.load(open(os.path.join(RAIZ, "vercel.json"), encoding="utf-8"))
    assert cfg["outputDirectory"] == "web"
    assert cfg["buildCommand"] is None, "el sitio ya viene generado, no se construye"
    assert not os.path.exists(os.path.join(RAIZ, "web", "vercel.json")), \
        "dos vercel.json se desincronizan; va uno solo, en la raíz"


def test_la_web_no_finge_vender_sin_backend():
    """Sin backend configurado, la web no puede declarar PLANIA_BACKEND: el
    JavaScript mostraría un checkout que fallaría en vez de la vía de
    contacto."""
    import os, subprocess, sys
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("PLANIA_")}
    entorno["PATH"] = os.environ["PATH"]
    subprocess.run([sys.executable, os.path.join(RAIZ, "sitio", "build.py")],
                   check=True, capture_output=True, env=entorno, cwd=RAIZ)
    html = open(os.path.join(RAIZ, "web", "es", "index.html"), encoding="utf-8").read()
    assert "PLANIA_BACKEND" not in html

    entorno["PLANIA_BACKEND"] = "https://api.ejemplo.uy"
    subprocess.run([sys.executable, os.path.join(RAIZ, "sitio", "build.py")],
                   check=True, capture_output=True, env=entorno, cwd=RAIZ)
    html = open(os.path.join(RAIZ, "web", "es", "index.html"), encoding="utf-8").read()
    assert 'PLANIA_BACKEND="https://api.ejemplo.uy"' in html

    # Se deja como estaba para no ensuciar el árbol de trabajo.
    del entorno["PLANIA_BACKEND"]
    subprocess.run([sys.executable, os.path.join(RAIZ, "sitio", "build.py")],
                   check=True, capture_output=True, env=entorno, cwd=RAIZ)


def test_web_generada_en_los_tres_idiomas():
    """Los tres HTML existen, están en su idioma y se enlazan entre sí."""
    import os
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "web", idioma, "index.html")
        assert os.path.exists(ruta), f"falta {ruta}"
        html = open(ruta, encoding="utf-8").read()
        assert f'<html lang="{idioma}">' in html
        # hreflang de los tres, para que el buscador no los tome como duplicados
        for otro in ("es", "en", "pt"):
            assert f'hreflang="{otro}"' in html
        assert 'rel="canonical"' in html
        assert "{{" not in html, "quedaron marcadores de plantilla sin resolver"


def test_textos_traducidos_no_quedaron_en_espanol():
    """Una traducción a medias es peor que no traducir: se controla que las
    tres versiones tengan realmente las mismas claves y textos distintos."""
    import json, os
    cargar = lambda l: json.load(open(os.path.join(RAIZ, "sitio", "i18n", f"{l}.json"),
                                      encoding="utf-8"))
    es, en, pt = cargar("es"), cargar("en"), cargar("pt")
    assert set(es) == set(en) == set(pt), "las tres traducciones no tienen las mismas claves"

    claves = [k for k in es if not k.startswith("_")]
    # Los precios y las siglas son iguales a propósito; el resto no puede serlo.
    iguales = [k for k in claves
               if es[k] == en[k] and len(str(es[k])) > 14 and not any(
                   s in str(es[k]) for s in ("USD", "MercadoPago", "Plania"))]
    assert not iguales, f"sin traducir al inglés: {iguales}"


def test_subtitulos_en_tres_idiomas_legibles():
    """Cada pista existe, es WebVTT válido, y ningún subtítulo tapa la pantalla
    ni aparece y desaparece antes de poder leerlo."""
    import os, re
    doblar, guion = _guion()
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "web", "assets", "video", f"plania_demo_{idioma}.vtt")
        assert os.path.exists(ruta), f"falta la pista {idioma}"
        texto = open(ruta, encoding="utf-8").read()
        assert texto.startswith("WEBVTT")

        cues = [b for b in texto.split("\n\n") if "-->" in b]
        assert len(cues) >= len(guion["segmentos"])
        seg = lambda t: sum(float(x) * f for x, f in zip(t.split(":"), (3600, 60, 1)))
        anterior = 0.0
        for c in cues:
            lineas = c.strip().split("\n")
            ini, fin = [seg(x) for x in lineas[1].split(" --> ")]
            cuerpo = lineas[2:]
            assert fin > ini, f"cue sin duración en {idioma}"
            assert fin - ini >= doblar.SUB_MIN_SEG - 0.01, f"cue ilegible de {fin-ini:.1f}s en {idioma}"
            assert ini >= anterior - 0.01, f"subtítulos solapados en {idioma}"
            assert len(cuerpo) <= 2, f"cue de {len(cuerpo)} renglones en {idioma}"
            anterior = fin


def test_narracion_entra_en_su_hueco_en_los_tres_idiomas():
    """El control de solapamiento del doblaje: si el texto de un segmento no
    entra en su hueco, la voz pisaría al segmento siguiente y el doblaje se
    iría de sincronía con la imagen."""
    doblar, guion = _guion()
    segs = guion["segmentos"]
    fin_video = float(guion["duracion_seg"])
    pasados = []
    for i, s in enumerate(segs):
        hueco = doblar.hueco(s, segs[i + 1] if i + 1 < len(segs) else None, fin_video)
        for idioma in ("es", "en", "pt"):
            if doblar.estimar(s[idioma]) > hueco:
                pasados.append((s["id"], idioma))
    assert not pasados, f"narración que se pasa de su hueco: {pasados}"


def test_los_segmentos_del_guion_no_se_pisan_entre_si():
    doblar, guion = _guion()
    segs = guion["segmentos"]
    for a, b in zip(segs, segs[1:]):
        assert a["fin"] <= b["inicio"], f"'{a['id']}' se superpone con '{b['id']}'"
    assert segs[-1]["fin"] <= float(guion["duracion_seg"])


def test_cliente_de_voz_habla_el_contrato_de_voicebox():
    """Prueba el cliente de doblaje contra un servidor que imita VoiceBox.

    No se puede levantar VoiceBox en CI, pero sí fijar que el cliente pide lo
    que corresponde (/generate con text, profile_id e idioma) y que sabe
    guardar la respuesta. Si mañana alguien cambia el cliente y rompe el
    contrato, esto lo detecta sin necesidad de instalar nada.
    """
    import http.server, json, os, socketserver, sys, tempfile, threading

    pedidos = []

    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            cuerpo = json.dumps({"profiles": [{"id": "pl-01", "name": "Plania"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            pedidos.append((self.path, json.loads(self.rfile.read(n))))
            audio = b"RIFF" + b"\0" * 200          # audio de mentira, alcanza
            self.send_response(200)
            self.send_header("content-type", "audio/wav")
            self.send_header("content-length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    puerto = srv.server_address[1]

    sys.path.insert(0, os.path.join(RAIZ, "sitio"))
    import importlib
    os.environ["PLANIA_VOICEBOX_URL"] = f"http://127.0.0.1:{puerto}"
    doblar = importlib.reload(importlib.import_module("doblar_video"))
    try:
        assert doblar.voicebox_perfiles()[0]["id"] == "pl-01"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            destino = f.name
        assert doblar.sintetizar_voicebox("Hola", "pl-01", "pt", destino) is True
        assert open(destino, "rb").read().startswith(b"RIFF")
        os.unlink(destino)

        ruta, cuerpo = pedidos[-1]
        assert ruta == "/generate"
        assert cuerpo == {"text": "Hola", "profile_id": "pl-01", "language": "pt"}
    finally:
        srv.shutdown()
        os.environ.pop("PLANIA_VOICEBOX_URL", None)


def test_hay_muestra_de_voz_para_clonar():
    """Sin la muestra no se puede reproducir la misma voz del video original."""
    import os
    ruta = os.path.join(RAIZ, "sitio", "narracion", "voz_referencia.wav")
    assert os.path.exists(ruta), "falta sitio/narracion/voz_referencia.wav"
    # VoiceBox clona desde 3 segundos; menos que eso da un timbre pobre.
    doblar, _ = _guion()
    assert doblar.duracion(ruta) >= 3.0


def test_los_subtitulos_no_muestran_la_escritura_para_la_voz():
    """El guion se escribe para que lo lea una voz sintética: la marca va
    separada y el dominio deletreado. Eso nunca puede llegar al subtítulo.

    Este control existe porque ya pasó: se cambió la forma de escribir la marca
    en el guion sin agregarla al mapeo, y el cierre del video pasó a subtitular
    "Plania punto u y." en vez de "plania.uy".
    """
    import os
    doblar, guion = _guion()
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "web", "assets", "video", f"plania_demo_{idioma}.vtt")
        texto = open(ruta, encoding="utf-8").read()
        for hablado in doblar.PARA_LEER:
            assert hablado not in texto, \
                f"'{hablado}' es escritura para la voz y quedó en el subtítulo {idioma}"
        # Y al revés: si el guion nombra el dominio, el subtítulo lo muestra escrito.
        if any("uy" in s[idioma] for s in guion["segmentos"]):
            assert "plania.uy" in texto
