# © 2026 Martín Viera. Todos los derechos reservados.
"""Tests de Plania: dataset, conectores, analítica, sugerencias, copiloto,
exportes, rutas, licencias y backend de venta."""
import os
import uuid
import re
import sys
import zipfile

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
from plania import config as pconfig  # noqa: E402

# Los tests de licencia van "limpiando lo que ensucian" al final de cada uno,
# pero eso no alcanza: si una corrida anterior se interrumpió a mitad de un
# test (pasa con Ctrl-C, o si el proceso se corta), la limpieza final nunca
# corre y el estado queda pisado en /tmp/plania_test_config para la PRÓXIMA
# corrida — un test de demo puede fallar sin que nadie haya tocado su código.
# Se arranca cada corrida desde cero en vez de confiar en que la anterior
# haya terminado prolijo.
for _clave in ("DEMO_INICIO", "LICENCIA_JWT", "LICENCIA_CLAIMS", "LICENCIA_VERIFICADA_EL"):
    pconfig.guardar_extra(_clave, None)


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


def test_eula_no_se_acepta_sola():
    """La EULA (LICENSE-EULA.md) tiene que aceptarse una vez por instalación
    antes de que la app deje pasar a cualquier pantalla con datos."""
    from plania import config as pconfig
    from plania import licencia

    pconfig.guardar_extra("EULA_ACEPTADA", "")
    assert licencia.eula_aceptada() is False

    licencia.aceptar_eula()
    assert licencia.eula_aceptada() is True

    # queda guardada la versión, no un booleano — si el texto cambia y
    # EULA_VERSION sube, una aceptación vieja no puede seguir contando.
    pconfig.guardar_extra("EULA_ACEPTADA", "0.1-version-vieja")
    assert licencia.eula_aceptada() is False

    pconfig.guardar_extra("EULA_ACEPTADA", "")  # no afectar otros tests


def test_existe_el_archivo_de_la_eula():
    ruta = os.path.join(RAIZ, "LICENSE-EULA.md")
    assert os.path.exists(ruta)
    texto = open(ruta, encoding="utf-8").read()
    # que sea la EULA de verdad y no un archivo vacío o un placeholder
    assert "ingeniería inversa" in texto.lower()
    assert "descompilar" in texto.lower()


def test_backend_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from backend_venta.app import app
    c = TestClient(app)
    assert c.get("/salud").json()["ok"]
    planes = c.get("/planes").json()
    assert "trial" in planes and "pro" in planes

    # La demo la habilita el dueño, no el visitante: el endpoint pide su token.
    monkeypatch.setenv("PLANIA_BACKEND_ADMIN_TOKEN", "token-smoke")
    del_dueno = {"Authorization": "Bearer token-smoke"}
    correo = f"demo-{uuid.uuid4().hex[:8]}@test.uy"

    r = c.post("/licencias/trial", json={"email": correo}, headers=del_dueno)
    assert r.status_code == 200 and r.json()["dias"] == 7
    # segunda demo con el mismo email: rechazada
    assert c.post("/licencias/trial", json={"email": correo},
                  headers=del_dueno).status_code == 409
    # checkout sin MP_ACCESS_TOKEN: 503 claro, no un 500 críptico
    os.environ.pop("MP_ACCESS_TOKEN", None)
    r = c.post("/checkout", json={"plan": "pro", "email": "x@y.uy"})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Backend de venta: cobertura de los caminos que tocan dinero
# ---------------------------------------------------------------------------
# `test_backend_endpoints` de arriba prueba el camino feliz de trial y el 503
# de checkout sin token — pero dejaba sin probar el webhook completo (el que
# de verdad emite la licencia cuando MercadoPago confirma un pago), el éxito
# de checkout, el gateway del copiloto entero (incluido el corte por cupo
# mensual agotado) y la descarga del instalador. Eran, literalmente, los
# caminos donde un bug significa "el cliente pagó y no le llegó nada" — y
# eran los que menos cobertura tenían de todo el repo.
#
# Cada test usa una IP de prueba propia (bloque TEST-NET-3, 203.0.113.0/24,
# reservado para documentación — nunca una IP real) para no compartir balde
# de rate limit con otros tests ni entre sí.
class _RespuestaFalsa:
    """Sustituto mínimo de requests.Response para no golpear APIs reales
    (MercadoPago, Anthropic) desde los tests."""

    def __init__(self, ok=True, json_data=None, text=""):
        self.ok = ok
        self.status_code = 200 if ok else 502
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def test_pagos_registrar_no_duplica_licencia_en_reintento_de_webhook(tmp_path):
    """MercadoPago reintenta el webhook hasta recibir 200 — el mismo
    payment_id puede llegar varias veces. Sin deduplicación real (la que
    reemplazó al INSERT OR IGNORE de SQLite al migrar a SQLAlchemy Core),
    cada reintento emitiría una licencia nueva."""
    from backend_venta import pagos

    db = str(tmp_path / "pagos.db")
    primero = pagos.registrar("pago-1", "cliente@plania.uy", "pro",
                              "licencia-original", "token-original", db_path=db)
    segundo = pagos.registrar("pago-1", "cliente@plania.uy", "pro",
                              "licencia-DISTINTA", "token-DISTINTO", db_path=db)

    # Lo guardado es lo mismo las dos veces. `nuevo` es la única diferencia y
    # es a propósito: dice cuál de las dos llamadas registró el pago, para que
    # lo que cuelga de eso (auditoría, aviso al dueño) pase una vez por venta.
    guardado = lambda d: {k: v for k, v in d.items() if k != "nuevo"}
    assert guardado(primero) == guardado(segundo)
    assert (primero["nuevo"], segundo["nuevo"]) == (True, False)
    assert segundo["licencia"] == "licencia-original"
    assert segundo["token_descarga"] == "token-original"
    assert pagos.total(db_path=db) == 1


def test_pagos_buscar_pago_no_registrado_devuelve_none(tmp_path):
    from backend_venta import pagos

    db = str(tmp_path / "pagos.db")
    assert pagos.buscar("pago-que-no-existe", db_path=db) is None


def test_marcar_trial_dos_veces_no_falla_y_sigue_marcado(tmp_path):
    """`marcar_trial` puede recibir el mismo email más de una vez (dos
    pedidos concurrentes del trial) — no tiene que tirar un error de
    restricción única, y el email tiene que seguir marcado como usado."""
    from backend_venta import uso

    db = str(tmp_path / "uso.db")
    assert not uso.ya_uso_trial("cliente@plania.uy", db_path=db)
    uso.marcar_trial("cliente@plania.uy", db_path=db)
    uso.marcar_trial("cliente@plania.uy", db_path=db)
    assert uso.ya_uso_trial("cliente@plania.uy", db_path=db)


def test_token_de_descarga_es_de_un_solo_uso(tmp_path):
    from backend_venta import descargas

    db = str(tmp_path / "descargas.db")
    token = descargas.crear_token_descarga("cliente@plania.uy", db_path=db)

    primero = descargas.validar_token_descarga(token, db_path=db)
    assert primero == {"ok": True, "cliente_id": "cliente@plania.uy", "error": None}

    segundo = descargas.validar_token_descarga(token, db_path=db)
    assert segundo["ok"] is False and segundo["error"] == "token_ya_usado"


def test_token_de_descarga_inexistente_y_vencido(tmp_path):
    from backend_venta import descargas

    db = str(tmp_path / "descargas.db")
    r = descargas.validar_token_descarga("no-existe", db_path=db)
    assert r == {"ok": False, "cliente_id": None, "error": "token_no_existe"}

    vencido = descargas.crear_token_descarga("cliente@plania.uy", horas_validez=-1, db_path=db)
    r = descargas.validar_token_descarga(vencido, db_path=db)
    assert r["ok"] is False and r["error"] == "token_expirado"


def test_token_de_descarga_se_puede_espiar_sin_consumir(tmp_path):
    from backend_venta import descargas

    db = str(tmp_path / "descargas.db")
    token = descargas.crear_token_descarga("cliente@plania.uy", db_path=db)
    assert descargas.validar_token_descarga(token, marcar_usado=False, db_path=db)["ok"]
    assert descargas.validar_token_descarga(token, marcar_usado=False, db_path=db)["ok"]
    assert descargas.validar_token_descarga(token, db_path=db)["ok"]
    assert descargas.validar_token_descarga(token, db_path=db)["ok"] is False


def test_chequear_cupo_sin_tope_no_bloquea():
    from backend_venta.app import _chequear_cupo

    # cupo_mensual=None es "sin tope" (enterprise/owner): no debe lanzar nada.
    _chequear_cupo({"cupo_mensual": None, "sub": "x@y.uy", "plan": "enterprise"})


def test_licencias_emitir_requiere_admin_y_valida_entrada():
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["PLANIA_BACKEND_ADMIN_TOKEN"] = "admin-de-prueba-para-tests"
    try:
        c = TestClient(app, client=("203.0.113.60", 51000))
        # Header(...) es obligatorio para FastAPI: sin Authorization ni
        # siquiera llega a requerir_admin, corta antes con 422.
        assert c.post("/licencias/emitir", json={"cliente_id": "x"}).status_code == 422

        equivocado = {"Authorization": "Bearer lo-que-sea"}
        assert c.post("/licencias/emitir", json={"cliente_id": "x"},
                      headers=equivocado).status_code == 403

        correcto = {"Authorization": "Bearer admin-de-prueba-para-tests"}
        assert c.post("/licencias/emitir", json={}, headers=correcto).status_code == 400
        r = c.post("/licencias/emitir", json={"cliente_id": "x", "plan": "no-existe"},
                   headers=correcto)
        assert r.status_code == 400

        r = c.post("/licencias/emitir",
                   json={"cliente_id": "partner@plania.uy", "plan": "pro"}, headers=correcto)
        assert r.status_code == 200
        from backend_venta import licencias as lic
        val = lic.licencia_activa(r.json()["licencia"])
        assert val["ok"] and val["claims"]["plan"] == "pro"
        assert val["claims"]["sub"] == "partner@plania.uy"
    finally:
        os.environ.pop("PLANIA_BACKEND_ADMIN_TOKEN", None)


def test_checkout_exito_crea_preferencia_con_el_token_correcto():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token-de-prueba"
    try:
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(
                ok=True, json_data={"id": "pref-123",
                                    "init_point": "https://mp.example/pay/pref-123"})
            c = TestClient(app, client=("203.0.113.61", 51000))
            r = c.post("/checkout", json={"plan": "pro", "email": "comprador@plania.uy"})
            assert r.status_code == 200
            assert r.json()["init_point"] == "https://mp.example/pay/pref-123"
            _, kwargs = mock_post.call_args
            assert kwargs["headers"]["Authorization"] == "Bearer TEST-token-de-prueba"
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def _armador_bat():
    import importlib.util
    ruta = os.path.join(RAIZ, "packaging", "armar_paquete_bat.py")
    spec = importlib.util.spec_from_file_location("_plania_bat", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_gitignore_de_graft_no_desversiona_el_skill():
    """`graft/` sin anclar en .gitignore matchea CUALQUIER carpeta llamada así
    en el árbol — incluida `.claude/skills/graft/`, el skill que sí se
    versiona.

    Se probó anclarla ("/graft/") para evitar la colisión, y no aguantó: es un
    bug real de la herramienta, no un descuido propio. `ensureGitignored()` en
    @nanonets/graft/dist/context/node-file.js sólo reconoce como "ya ignorado"
    las formas literales "graft/" o "graft" — nunca "/graft/". Con la versión
    anclada sola, cada `graft build` (lo dispara el hook Stop, solo, al final
    de cada turno) volvía a agregar su propia línea sin anclar, duplicada.
    Pasó tres veces seguidas antes de entender la causa.

    La forma que aguanta: dejar la línea EXACTA que el chequeo de graft espera
    (para que dé por hecho que ya está y no reescriba más) y agregar una
    negación aparte que re-incluya el skill. El síntoma si esto se rompe es
    silencioso: `git status` no marca nada raro hasta que a esa carpeta le
    entra un archivo nuevo.
    """
    lineas = [l.strip() for l in
             open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8").read().splitlines()]
    assert lineas.count("graft/") == 1, (
        "tiene que haber EXACTAMENTE una línea 'graft/' literal — es la forma "
        "que el chequeo interno de graft reconoce como 'ya ignorado'. Sin "
        "ella (o anclada con '/'), graft build vuelve a agregar la suya.")
    assert lineas.count("!/.claude/skills/graft/") == 1, (
        "falta (o está duplicada) la negación que re-incluye el skill después "
        "de la línea 'graft/' — sin ella, 'graft/' se lleva puesto el skill.")
    assert lineas.index("graft/") < lineas.index("!/.claude/skills/graft/"), (
        "la negación tiene que ir DESPUÉS de 'graft/': en .gitignore gana el "
        "último patrón que matchea una ruta.")

    import subprocess
    ignorado = subprocess.run(
        ["git", "check-ignore", ".claude/skills/graft/SKILL.md"],
        cwd=RAIZ, capture_output=True, text=True)
    assert ignorado.returncode != 0, \
        ".claude/skills/graft/SKILL.md quedó ignorado — el skill no se versiona"


def test_no_hay_configuracion_ni_claves_versionadas():
    """La configuración de Plania nunca va al repositorio, y menos su clave.

    Había `cfg_ui/.config.key` y `cfg_ui/config.enc` commiteados: la caja
    fuerte y la llave en el mismo commit, o sea cifrado que no cifra. Lo que
    tenían adentro era inofensivo —la aceptación de la EULA y la fecha de
    inicio de la demo— pero ESE es el archivo donde `plania/config.py` guarda
    ANTHROPIC_API_KEY, la licencia activada y la cadena de conexión al ERP
    cuando no hay keyring del sistema. Y el repositorio es público.
    """
    import subprocess
    versionados = subprocess.run(["git", "ls-files"], cwd=RAIZ,
                                 capture_output=True, text=True).stdout.split("\n")
    prohibidos = [f for f in versionados
                  if os.path.basename(f) in (".config.key", "config.enc",
                                             "config.json")
                  or f.endswith(".pem") or f.endswith(".key")]
    assert not prohibidos, (
        f"hay configuración o claves versionadas: {prohibidos}. "
        "Sacalas con `git rm --cached` — y si tuvieron algo real adentro, "
        "rotá esa credencial: el historial de git no se borra solo.")


def test_las_tablas_de_la_ventana_no_muestran_jerga_de_base_de_datos():
    """Los encabezados de las tablas eran el nombre crudo de la columna del
    DataFrame con los guiones bajos cambiados por espacios: "Sku", "Dias
    Stock", "Descuento Pct", "Categoria". Sin tildes y con jerga de base de
    datos a la vista. Para quien pagó un programa, "Pct" no es una palabra.
    """
    base = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "base.js"),
                encoding="utf-8").read()

    for col, esperado in (("sku", "SKU"), ("categoria", "Categoría"),
                          ("dias_stock", "Días de stock"),
                          ("descuento_pct", "Descuento %"),
                          ("capital_inmovilizado", "Capital inmovilizado")):
        assert f'"{esperado}"' in base or f"{col}: \"{esperado}\"" in base, \
            f"la columna {col} no tiene una etiqueta legible"

    # Y el CSS no puede volver a capitalizar encima: con las etiquetas ya bien
    # escritas, `capitalize` las rompe ("Días De Stock", "Margen Objetivo %").
    css = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "estilo.css"),
               encoding="utf-8").read()
    # Solo el cuerpo de la regla, hasta su llave de cierre: el comentario que
    # explica por qué se sacó nombra la propiedad, y una ventana de N
    # caracteres lo agarraba y daba falso positivo.
    inicio = css.index(".tabla th {")
    bloque_th = css[inicio:css.index("}", inicio)]
    assert "text-transform: capitalize" not in bloque_th, \
        "capitalize sobre etiquetas ya escritas las rompe"


def test_una_columna_de_numeros_no_mezcla_formatos():
    """`Number.isInteger(178.0)` da true y `112.8` da false, así que decidir
    los decimales celda por celda mostraba "178" y "112,80" en la MISMA
    columna de días. Leído en una tabla, parecen dos magnitudes distintas.

    Se decide por columna: si algún valor tiene decimales, los llevan todos.
    """
    base = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "base.js"),
                encoding="utf-8").read()
    assert "function decimalesDe(" in base, "falta el cálculo por columna"
    assert "miles(v, decimales[c])" in base, \
        "el formato sigue decidiéndose por celda"
    assert "Number.isInteger(v) ? 0 : 2" not in base, \
        "quedó la decisión celda por celda, que es la que mezcla formatos"


def test_un_indicador_en_cero_explica_por_que():
    """Un cero grande y sin explicación se lee como "algo se rompió".

    "Potencial por zonas" es el único de los cuatro que da cero con datos
    buenos —cuando ninguna zona vende bastante por debajo de sus comparables—
    así que ese caso tiene que decir eso y no un $0 pelado.
    """
    pantallas = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "pantallas.js"),
                     encoding="utf-8").read()
    i = pantallas.index("Potencial por zonas")
    bloque = pantallas[i:i + 500]
    assert "Sin brechas" in bloque, "el cero se muestra como $0 pelado"
    assert "detalle:" in bloque, "el cero no explica por qué es cero"


def test_el_paquete_bat_no_le_manda_al_cliente_nada_del_dueno(tmp_path):
    """La vía .bat entrega el código a la vista, así que lo que entre al ZIP se
    lee en la máquina del cliente.

    Armaba el paquete copiando `app/` y `plania/` enteros, o sea que mandaba
    `plania/negocio.py` (costos y márgenes del producto), `plania/owner.py` y
    `app/owner.py` — los mismos archivos que el .exe sí sacaba. Las dos vías de
    entrega del mismo producto no coincidían, y la que no coincidía era la que
    va en texto plano.

    Se arma el ZIP de verdad y se lo revisa por dentro, no se leen listas.
    """
    bat = _armador_bat()
    destino = str(tmp_path / "Plania_BAT.zip")
    bat.armar(destino)

    with zipfile.ZipFile(destino) as z:
        dentro = [n[len("Plania/"):] for n in z.namelist() if n.startswith("Plania/")]

    for prohibido in ("app/owner.py", "plania/owner.py", "plania/negocio.py",
                      "plania/contenido.py"):
        assert prohibido not in dentro, f"el ZIP del .bat lleva {prohibido}"
    assert not [n for n in dentro if n.startswith("backend_venta")], \
        "el servidor de venta no corre nunca del lado del cliente"
    assert not [n for n in dentro if n.startswith("docs/")], \
        "docs/ es interna: modelo comercial, costos y márgenes"
    assert not [n for n in dentro if "owner" in n], \
        "tampoco las capturas del panel del dueño"

    # Y que siga siendo un producto que arranca: un ZIP vacío pasaría todo lo
    # de arriba con honores.
    for necesario in ("INICIAR_PLANIA.bat", "app/app.py", "plania/sugerencias.py",
                      "packaging/plania_launcher.py"):
        assert necesario in dentro, f"sin {necesario} el producto no abre"


def test_el_paquete_bat_no_se_lleva_artefactos_de_la_maquina(tmp_path, monkeypatch):
    """`data/` se copiaba entera. En el runner de GitHub eso es inofensivo —se
    arma en limpio— pero armando la release desde la máquina del dueño, que es
    donde también se prueba el backend, `data/` tiene la base de licencias
    emitidas y el log de auditoría de esa máquina. Se iban adentro del paquete.
    """
    bat = _armador_bat()
    inventados = [os.path.join(RAIZ, "data", "uso_licencias.db"),
                  os.path.join(RAIZ, "data", "auditoria.log")]
    creados = [p for p in inventados if not os.path.exists(p)]
    for p in creados:
        open(p, "w").close()
    try:
        destino = str(tmp_path / "Plania_BAT.zip")
        bat.armar(destino)
        with zipfile.ZipFile(destino) as z:
            dentro = z.namelist()
        for feo in ("uso_licencias", "auditoria.log", ".lock"):
            assert not [n for n in dentro if feo in n], \
                f"el paquete lleva {feo}, que es de la máquina donde se armó"
    finally:
        for p in creados:
            os.remove(p)


def test_el_paquete_del_dueno_si_lleva_su_panel_y_su_lanzador(tmp_path):
    """El espejo del control anterior: el ZIP del dueño tiene que llevar lo que
    al del cliente se le saca, y su propio .bat. Sin esto, "no lleva nada del
    dueño" se podría cumplir sacándoselo también a él."""
    bat = _armador_bat()
    destino = str(tmp_path / "Plania_Owner_BAT.zip")
    bat.armar_owner(destino)
    with zipfile.ZipFile(destino) as z:
        dentro = [n[len("Plania Owner/"):] for n in z.namelist()
                  if n.startswith("Plania Owner/")]
    for necesario in ("app/owner.py", "plania/owner.py", "plania/negocio.py",
                      "INICIAR_PLANIA_OWNER.bat", "app/app.py"):
        assert necesario in dentro, f"al paquete del dueño le falta {necesario}"


def test_el_lanzador_del_dueno_no_trae_el_token_escrito():
    """Un .bat con el token adentro es un token publicado en cuanto el archivo
    se copia a otro lado. Se pide al arrancar."""
    bat = open(os.path.join(RAIZ, "INICIAR_PLANIA_OWNER.bat"), encoding="utf-8").read()
    assert "set /p PLANIA_OWNER_TOKEN=" in bat, "el token tiene que pedirse"
    assert not re.search(r"set\s+PLANIA_OWNER_TOKEN=\S", bat), \
        "hay un token escrito en el .bat"
    assert "PLANIA_PANEL=owner" in bat, "sin esto levanta el producto, no el panel"


def test_ninguna_linea_del_instalador_arranca_con_almohadilla():
    """Para el preprocesador de Inno Setup, el primer carácter no blanco de la
    línea manda: si es '#', lo que sigue tiene que ser una directiva SUYA.

    Cortar una expresión Pascal justo antes de un `#13#10` —cosa que se lee
    perfecta— aborta la compilación con "Unknown preprocessor directive", y el
    build de Windows muere ahí: sin instalador liviano y, porque el paso corta
    el job entero, tampoco el de Electron. Pasó de verdad, en la línea 180.
    """
    iss = open(os.path.join(RAIZ, "packaging", "instalador.iss"),
               encoding="utf-8").read()
    directivas = ("define", "undef", "include", "if", "ifdef", "ifndef",
                  "ifexist", "ifnexist", "elif", "else", "endif", "error",
                  "pragma", "expr", "insert", "append", "emit", "file",
                  "for", "sub", "endsub", "dim", "redim")
    malas = []
    for n, linea in enumerate(iss.splitlines(), start=1):
        limpia = linea.strip()
        if not limpia.startswith("#"):
            continue
        m = re.match(r"#\s*(\w+)", limpia)
        if not m or m.group(1).lower() not in directivas:
            malas.append((n, limpia[:60]))
    assert not malas, (
        f"líneas que ISPP va a leer como directiva suya: {malas}. "
        "Mové el #13#10 al final de la línea de arriba.")


def test_el_blueprint_de_despliegue_no_pierde_las_licencias_en_cada_deploy():
    """`render.yaml` tiene que dejar el backend desplegable en el plan
    gratuito sin pisar ninguna de las dos minas del despliegue a mano.

    Las dos son silenciosas —el servicio arranca igual y se ve sano— y las
    dos se pagan con licencias de clientes:

      1. Secreto de firma autogenerado: si `PLANIA_LICENSE_SECRET` no está
         fijo, cada reinicio puede generar uno nuevo y TODAS las licencias ya
         emitidas dejan de validar de golpe.
      2. Base efímera: la SQLite por defecto de `uso.py` (quién consumió su
         prueba, qué pagos ya se procesaron, qué tokens de descarga siguen
         vivos) vive en el disco del contenedor, que el plan free no
         persiste — por eso `PLANIA_USO_DB` tiene que poder apuntar a una
         base externa (ver `backend_venta/db.py`) en vez de exigir un plan
         pago con disco montado.
    """
    import yaml

    cfg = yaml.safe_load(open(os.path.join(RAIZ, "render.yaml"), encoding="utf-8"))
    servicio = cfg["services"][0]
    envs = {e["key"]: e for e in servicio["envVars"]}

    assert envs["PLANIA_LICENSE_SECRET"].get("generateValue") is True, \
        "el secreto de firma tiene que quedar fijo, no autogenerarse en cada arranque"

    # Ningún disco montado: el plan free no los soporta, y este blueprint no
    # depende de uno (la persistencia la resuelve PLANIA_USO_DB apuntando a
    # una base externa, no un mountPath).
    assert "disk" not in servicio, \
        "un disco montado exige un plan pago; PLANIA_USO_DB reemplaza esa necesidad"
    assert servicio["plan"] == "free", "el blueprint tiene que poder correr sin pagar"
    assert servicio["healthCheckPath"] == "/salud"
    assert "backend_venta.app:app" in servicio["startCommand"]
    assert "requirements-backend.txt" in servicio["buildCommand"]

    # PLANIA_USO_DB no se hardcodea a un archivo: lo carga quien despliega
    # (una URL de Postgres externa, o lo deja vacío y cae a SQLite local).
    assert envs["PLANIA_USO_DB"].get("sync") is False, \
        "PLANIA_USO_DB tiene que poder cargarse con una base externa, no venir fija a un archivo"

    # Los secretos que no se pueden inventar por defecto se piden, no se
    # hardcodean.
    for clave in ("MP_ACCESS_TOKEN", "ANTHROPIC_API_KEY"):
        assert envs[clave].get("sync") is False, f"{clave} tiene que pedirse al desplegar"
        assert "value" not in envs[clave], f"{clave} no puede venir escrito en el repo"


def test_los_requisitos_del_backend_cubren_lo_que_el_backend_importa():
    """`requirements-backend.txt` existe para no subir pandas ni streamlit al
    servidor. El riesgo de esa poda es quedarse corto: el deploy construye
    bien y el servicio muere en el primer import."""
    import re

    declarados = set()
    for linea in open(os.path.join(RAIZ, "requirements-backend.txt"), encoding="utf-8"):
        linea = linea.split("#")[0].strip()
        if linea:
            declarados.add(re.split(r"[><=\[]", linea)[0].strip().lower())

    # Módulos de terceros que importa el backend y todo lo que el backend
    # importa de plania/ (config y auditoria).
    fuentes = [os.path.join(RAIZ, "backend_venta", f)
               for f in os.listdir(os.path.join(RAIZ, "backend_venta")) if f.endswith(".py")]
    fuentes += [os.path.join(RAIZ, "plania", "config.py"),
                os.path.join(RAIZ, "plania", "auditoria.py")]

    paquete = {"jwt": "pyjwt", "fastapi": "fastapi", "uvicorn": "uvicorn",
               "requests": "requests", "slowapi": "slowapi",
               "portalocker": "portalocker", "cryptography": "cryptography"}
    estandar_o_propio = {"os", "sys", "json", "re", "time", "secrets", "sqlite3",
                         "hashlib", "getpass", "shutil", "contextlib", "datetime",
                         "typing", "__future__", "backend_venta", "plania", "keyring",
                         "logging", "tempfile", "smtplib", "email", "ssl",
                         "threading"}

    faltan = set()
    for ruta in fuentes:
        for m in re.finditer(r"^\s*(?:import|from)\s+([\w.]+)", open(ruta, encoding="utf-8").read(),
                             re.MULTILINE):
            raiz_mod = m.group(1).split(".")[0]
            if raiz_mod in estandar_o_propio:
                continue
            esperado = paquete.get(raiz_mod, raiz_mod).lower()
            if esperado not in declarados:
                faltan.add(f"{raiz_mod} (en {os.path.basename(ruta)})")
    assert not faltan, f"requirements-backend.txt no declara: {sorted(faltan)}"


def test_el_webhook_de_mercadopago_no_apunta_a_la_landing_estatica():
    """`notification_url` tiene que apuntar a ESTE backend, no a plania.uy.

    plania.uy es un sitio estático en Vercel: no existe
    `/webhooks/mercadopago` ahí. Si el checkout le da esa dirección a
    MercadoPago, un pago aprobado notifica contra un 404 y la licencia no se
    emite sola — el cliente paga y no recibe nada hasta que alguien lo
    resuelve a mano. El default salía de PLANIA_PUBLIC_URL, que es justamente
    la landing.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    os.environ["PLANIA_PUBLIC_URL"] = "https://plania.uy"
    os.environ.pop("PLANIA_WEBHOOK_URL", None)
    try:
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(
                ok=True, json_data={"id": "pref-1", "init_point": "https://mp.example/x"})
            c = TestClient(app, base_url="https://api.plania.uy",
                           client=("203.0.113.64", 51000))
            assert c.post("/checkout",
                          json={"plan": "pro", "email": "x@y.uy"}).status_code == 200
            pref = mock_post.call_args.kwargs["json"]
            assert pref["notification_url"] == "https://api.plania.uy/webhooks/mercadopago"
            # Las back_urls SÍ van a la landing: ahí vuelve el comprador.
            assert pref["back_urls"]["success"] == "https://plania.uy/gracias"
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)
        os.environ.pop("PLANIA_PUBLIC_URL", None)


def test_las_paginas_de_retorno_de_mercadopago_existen_en_la_web():
    """Las tres direcciones a las que el checkout devuelve al comprador tienen
    que existir en el sitio publicado. Si `back_urls` nombra `/gracias` y en
    `web/` no hay `gracias/index.html`, quien paga termina en un 404."""
    import re

    fuente = open(os.path.join(RAIZ, "backend_venta", "app.py"), encoding="utf-8").read()
    nombradas = set(re.findall(r'\{base\}/(\w+)"', fuente))
    assert nombradas == {"gracias", "error", "pendiente"}, \
        f"cambiaron las back_urls del checkout: {nombradas}"

    for pagina in nombradas:
        ruta = os.path.join(RAIZ, "web", pagina, "index.html")
        assert os.path.exists(ruta), \
            f"el checkout manda a /{pagina}/ y no existe {ruta} — correr sitio/build.py"

    # La de gracias es la única que tiene que entregar algo: rescata la
    # licencia del pago con el payment_id que MercadoPago deja en la URL.
    gracias = open(os.path.join(RAIZ, "web", "gracias", "index.html"), encoding="utf-8").read()
    assert "payment_id" in gracias
    assert "/licencias/por-pago/" in gracias
    assert "noindex" in gracias, "una página de retorno de pago no se indexa"


def test_checkout_plan_no_comprable_y_email_invalido():
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.62", 51000))
    # "owner" no tiene precio: no es un plan que se pueda pagar online.
    assert c.post("/checkout", json={"plan": "owner", "email": "x@y.uy"}).status_code == 400
    assert c.post("/checkout", json={"plan": "pro", "email": "no-es-un-email"}).status_code == 400


def test_checkout_mercadopago_rechaza_la_preferencia():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(ok=False, text="credenciales inválidas")
            c = TestClient(app, client=("203.0.113.63", 51000))
            r = c.post("/checkout", json={"plan": "pro", "email": "x@y.uy"})
            assert r.status_code == 502
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_los_fallos_5xx_del_backend_de_venta_quedan_en_el_log(caplog):
    """MercadoPago reintenta un webhook hasta recibir 200. Si el que falla es
    ESTE servidor —token rotado, servicio caído del otro lado— cada reintento
    fallaba con 502 sin dejar ningún rastro server-side: el primer síntoma
    visible era un cliente que pagó y no recibió la licencia, descubierto
    días después por un reclamo, sin log que explicara por qué. Se agregó
    logging en los 8 puntos que responden 5xx (fallo propio del servidor);
    los 4xx (pedido mal formado del cliente) se dejan afuera a propósito —
    son esperados y de alto volumen, loguearlos como error sería ruido.

    Este test no vuelve a probar cada código de estado (ya lo hacen los tests
    de arriba) — prueba específicamente que la respuesta al llamante venga
    acompañada de algo en el log, para el caso más crítico: el webhook.
    """
    import logging
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.get") as mock_get:
            mock_get.return_value = _RespuestaFalsa(ok=False, text="MercadoPago caído")
            c = TestClient(app, client=("203.0.113.90", 51000))
            with caplog.at_level(logging.ERROR, logger="backend_venta"):
                r = c.post("/webhooks/mercadopago",
                          json={"type": "payment", "data": {"id": "PAGO-LOG-1"}})
            assert r.status_code == 502
            assert any("PAGO-LOG-1" in reg.message for reg in caplog.records), (
                "el 502 del webhook no dejó nada en el log — sin esto, un fallo "
                "sistémico de MercadoPago se descubre por un reclamo del cliente, "
                "días después, sin pista de qué pasó")
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_webhook_mercadopago_ignora_lo_que_no_es_pago():
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.64", 51000))
    r = c.post("/webhooks/mercadopago", json={"type": "merchant_order"})
    assert r.status_code == 200 and r.json()["ignorado"] is True


def test_webhook_mercadopago_sin_data_id_400():
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.65", 51000))
    r = c.post("/webhooks/mercadopago", json={"type": "payment", "data": {}})
    assert r.status_code == 400


def test_webhook_mercadopago_verificacion_fallida_502():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.get") as mock_get:
            mock_get.return_value = _RespuestaFalsa(ok=False)
            c = TestClient(app, client=("203.0.113.66", 51000))
            r = c.post("/webhooks/mercadopago", json={"type": "payment", "data": {"id": "999"}})
            assert r.status_code == 502
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_webhook_mercadopago_pago_no_aprobado_no_emite_licencia():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.get") as mock_get:
            mock_get.return_value = _RespuestaFalsa(ok=True, json_data={"status": "pending"})
            c = TestClient(app, client=("203.0.113.67", 51000))
            r = c.post("/webhooks/mercadopago", json={"type": "payment", "data": {"id": "1000"}})
            assert r.status_code == 200
            assert r.json() == {"ok": True, "estado": "pending"}
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_la_licencia_de_un_pago_no_se_le_entrega_a_cualquiera(tmp_path, monkeypatch):
    """Saber el número de pago no puede alcanzar para llevarse la licencia.

    El `payment_id` viaja a la vista en la URL de retorno de MercadoPago y los
    de MP son numéricos, o sea enumerables: con 20 pedidos por minuto son casi
    30.000 por día. Antes, si el pago ya estaba registrado —el caso normal, ni
    bien pasó el webhook— el endpoint devolvía la licencia y el token de
    descarga sin comprobar nada. El docstring decía que el pago se
    re-verificaba contra MercadoPago, y era cierto sólo en el camino de
    rescate; el camino normal entregaba de una.
    """
    import importlib

    monkeypatch.setenv("PLANIA_USO_DB", str(tmp_path / "uso.db"))
    from backend_venta import descargas, pagos, uso
    for m in (uso, pagos, descargas):
        importlib.reload(m)
    from fastapi.testclient import TestClient

    from backend_venta import app as bapp
    importlib.reload(bapp)

    pagos.registrar("112233445566", "comprador@empresa.uy", "pro",
                    "JWT-DEL-COMPRADOR", "token-del-comprador",
                    db_path=str(tmp_path / "uso.db"))
    c = TestClient(bapp.app, client=("203.0.113.210", 50000))

    # Un tercero que sólo conoce el número no se lleva nada.
    r = c.get("/licencias/por-pago/112233445566")
    assert r.status_code == 400
    assert "JWT-DEL-COMPRADOR" not in r.text

    r = c.get("/licencias/por-pago/112233445566?email=otro@ajeno.com")
    assert r.status_code == 404, "entregó la licencia a quien no compró"
    assert "JWT-DEL-COMPRADOR" not in r.text
    assert "token-del-comprador" not in r.text
    # El texto no puede delatar que ese pago existe: si dijera "email
    # incorrecto" en vez de "no encontramos la compra", quien enumera sabría
    # que acertó el número y sólo le falta el email.
    assert "existe" not in r.json()["detail"].lower()

    # Y el comprador sí, escriba el email como lo escriba.
    for como_lo_escriba in ("comprador@empresa.uy", "Comprador@Empresa.UY",
                            "  comprador@empresa.uy  "):
        r = c.get("/licencias/por-pago/112233445566",
                  params={"email": como_lo_escriba})
        assert r.status_code == 200, f"le negó su licencia al comprador ({como_lo_escriba!r})"
        assert r.json()["licencia"] == "JWT-DEL-COMPRADOR"
        assert r.json()["token_descarga"] == "token-del-comprador"


def test_el_rescate_de_un_pago_tampoco_emite_para_cualquiera(tmp_path, monkeypatch):
    """El camino de rescate —cuando el webhook todavía no llegó— no puede ser
    la puerta de atrás del control de arriba: sin esto alcanzaba con enumerar
    pagos sin procesar para hacerse emitir la licencia de otro."""
    import importlib
    from unittest.mock import patch

    monkeypatch.setenv("PLANIA_USO_DB", str(tmp_path / "uso.db"))
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    from backend_venta import descargas, pagos, uso
    for m in (uso, pagos, descargas):
        importlib.reload(m)
    from fastapi.testclient import TestClient

    from backend_venta import app as bapp
    importlib.reload(bapp)

    aprobado = _RespuestaFalsa(
        ok=True, json_data={"status": "approved",
                            "metadata": {"plan": "pro", "email": "quien-pago@empresa.uy"}})
    c = TestClient(bapp.app, client=("203.0.113.211", 50000))

    with patch("backend_venta.app.requests.get", return_value=aprobado):
        r = c.get("/licencias/por-pago/999888777?email=ajeno@otro.com")
        assert r.status_code == 404, "el rescate emitió la licencia para un tercero"
        assert pagos.buscar("999888777", db_path=str(tmp_path / "uso.db")) is None, \
            "el rescate llegó a emitir antes de comprobar quién preguntaba"

        r = c.get("/licencias/por-pago/999888777?email=quien-pago@empresa.uy")
        assert r.status_code == 200 and r.json()["licencia"]


def test_webhook_mercadopago_pago_aprobado_emite_licencia_y_token_de_descarga():
    """El camino que de verdad mueve plata: sin esto probado, un bug acá
    significa clientes que pagaron y no reciben ni licencia ni instalador,
    sin que nadie se entere hasta que se quejen."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta import descargas
    from backend_venta import licencias as lic
    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.get") as mock_get:
            mock_get.return_value = _RespuestaFalsa(
                ok=True,
                json_data={"status": "approved",
                          "metadata": {"plan": "pro", "email": "pagador@plania.uy"}})
            c = TestClient(app, client=("203.0.113.68", 51000))
            r = c.post("/webhooks/mercadopago", json={"type": "payment", "data": {"id": "555"}})
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True and body["plan"] == "pro"
            assert body["token_descarga"]

        val = lic.licencia_activa(body["licencia"])
        assert val["ok"]
        assert val["claims"]["sub"] == "pagador@plania.uy"
        assert val["claims"]["plan"] == "pro"

        r2 = descargas.validar_token_descarga(body["token_descarga"])
        assert r2["ok"] and r2["cliente_id"] == "pagador@plania.uy"
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_webhook_mercadopago_plan_desconocido_cae_a_starter():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta.app import app

    os.environ["MP_ACCESS_TOKEN"] = "TEST-token"
    try:
        with patch("backend_venta.app.requests.get") as mock_get:
            mock_get.return_value = _RespuestaFalsa(
                ok=True, json_data={"status": "approved", "metadata": {"plan": "no-existe"}})
            c = TestClient(app, client=("203.0.113.69", 51000))
            r = c.post("/webhooks/mercadopago", json={"type": "payment", "data": {"id": "777"}})
            assert r.json()["plan"] == "starter"
    finally:
        os.environ.pop("MP_ACCESS_TOKEN", None)


def test_trial_email_invalido_400(monkeypatch):
    """Ya autenticado como dueño, un email mal escrito sigue siendo un 400.

    El token de admin da permiso para emitir, no para emitir cualquier cosa:
    una licencia atada a una dirección inválida no se la puede activar nadie.
    """
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    monkeypatch.setenv("PLANIA_BACKEND_ADMIN_TOKEN", "token-invalido-400")
    c = TestClient(app, client=("203.0.113.78", 51000))
    r = c.post("/licencias/trial", json={"email": "no-es-un-email"},
               headers={"Authorization": "Bearer token-invalido-400"})
    assert r.status_code == 400


def test_emitir_licencia_plan_desconocido_lanza_valueerror():
    from backend_venta import licencias as lic

    with pytest.raises(ValueError, match="desconocido"):
        lic.emitir_licencia("x@y.uy", "plan-que-no-existe")


def test_gateway_copiloto_error_de_anthropic_502():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta.app import app

    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-de-prueba"
    try:
        token = lic.emitir_licencia("copiloto-error@plania.uy", "pro")
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(
                ok=False, json_data={"error": {"message": "modelo sobrecargado"}})
            c = TestClient(app, client=("203.0.113.79", 51000))
            r = c.post("/gateway/copiloto", json={"texto": "hola"},
                      headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 502
            assert "sobrecargado" in r.json()["detail"]
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_gateway_copiloto_feature_no_incluida_403():
    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta.app import app

    token = lic.emitir_licencia("sinfeature@plania.uy", "starter", features=[])
    c = TestClient(app, client=("203.0.113.70", 51000))
    r = c.post("/gateway/copiloto", json={"texto": "hola"},
              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_gateway_copiloto_sin_texto_400():
    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta.app import app

    token = lic.emitir_licencia("copiloto1@plania.uy", "pro")
    c = TestClient(app, client=("203.0.113.71", 51000))
    r = c.post("/gateway/copiloto", json={"texto": "   "},
              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_gateway_copiloto_sin_api_key_503():
    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta.app import app

    os.environ.pop("ANTHROPIC_API_KEY", None)
    token = lic.emitir_licencia("copiloto2@plania.uy", "pro")
    c = TestClient(app, client=("203.0.113.72", 51000))
    r = c.post("/gateway/copiloto", json={"texto": "hola"},
              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503


def test_gateway_copiloto_exito_registra_uso():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta import uso
    from backend_venta.app import app

    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-de-prueba"
    try:
        cliente = "copiloto3@plania.uy"
        token = lic.emitir_licencia(cliente, "pro")
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(
                ok=True,
                json_data={"content": [{"text": "la respuesta de Claude"}],
                          "usage": {"input_tokens": 10, "output_tokens": 20}})
            c = TestClient(app, client=("203.0.113.73", 51000))
            r = c.post("/gateway/copiloto",
                      json={"texto": "¿qué ofertas armo?", "ref_id": "abc"},
                      headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json()["raw"] == "la respuesta de Claude"

        u = uso.uso_mes(cliente)
        assert u["consultas"] == 1 and u["tok_in"] == 10 and u["tok_out"] == 20
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_gateway_copiloto_corta_al_agotar_el_cupo():
    """El chequeo de negocio que de verdad limita lo que un cliente puede
    gastar en un mes: sin este test, un bug en _chequear_cupo deja pasar
    consultas ilimitadas sobre un plan pago sin que nada lo note."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend_venta import licencias as lic
    from backend_venta.app import app

    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-de-prueba"
    try:
        cliente = "copiloto-cupo@plania.uy"
        # Cupo bajo a propósito: no hace falta llamar 500 veces (el cupo real
        # de "starter") para probar el corte, alcanza con uno chico.
        token = lic.emitir_licencia(cliente, "starter", cupo_mensual=2)
        c = TestClient(app, client=("203.0.113.74", 51000))
        with patch("backend_venta.app.requests.post") as mock_post:
            mock_post.return_value = _RespuestaFalsa(
                ok=True, json_data={"content": [{"text": "ok"}], "usage": {}})
            for _ in range(2):
                r = c.post("/gateway/copiloto", json={"texto": "consulta"},
                          headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200
            r = c.post("/gateway/copiloto", json={"texto": "consulta de más"},
                      headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 402
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_descargar_token_invalido_403():
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.75", 51000))
    assert c.get("/descargar/token-que-no-existe").status_code == 403


def test_el_comprador_baja_el_instalador_publicado_en_releases(tmp_path, monkeypatch):
    """En un PaaS el instalador no está en el disco del servidor, y sin esto
    el circuito terminaba en 503 justo después de cobrar.

    El .exe pesa ~200 MB: no viaja en el repositorio ni entra en el disco
    efímero de un plan free, se publica en la página de Releases. El endpoint
    sólo sabía servir un archivo local, así que el comprador pagaba, recibía
    su token, hacía clic en descargar y no bajaba nada — el peor momento
    posible para fallar.

    Con PLANIA_INSTALADOR_URL redirige a donde el instalador sí está, y el
    token se sigue gastando una sola vez.
    """
    from fastapi.testclient import TestClient

    from backend_venta import descargas
    from backend_venta.app import app

    url = ("https://github.com/ejemplo/repo/releases/download/"
           "ultima-compilacion/Plania.Setup.1.0.0.exe")
    monkeypatch.setenv("PLANIA_INSTALADOR_URL", url)
    # Apunta a un archivo que NO existe: se comprueba que la URL alcanza sola,
    # que es exactamente la situación del servidor desplegado.
    monkeypatch.setenv("PLANIA_INSTALADOR_PATH", str(tmp_path / "no-esta.exe"))

    token = descargas.crear_token_descarga("comprador-releases@plania.uy")
    c = TestClient(app, client=("203.0.113.231", 51100))

    r = c.get(f"/descargar/{token}", follow_redirects=False)
    assert r.status_code == 302, f"no redirigió al instalador: {r.status_code}"
    assert r.headers["location"] == url

    # De un solo uso, igual que cuando sirve un archivo local.
    assert c.get(f"/descargar/{token}", follow_redirects=False).status_code == 403


def test_un_servidor_sin_instalador_no_le_quema_la_descarga_al_comprador(tmp_path):
    """El token de descarga es de un solo uso, así que el orden importa.

    Se consumía ANTES de mirar si había instalador que entregar: en un
    servidor recién desplegado, sin `PLANIA_INSTALADOR_PATH` apuntando a nada,
    el comprador recibía un 503 y su única descarga quedaba gastada. Cuando el
    dueño publicaba el instalador, ese mismo token ya devolvía 403 "ya usado".
    Pagó, no bajó nada y encima perdió el derecho a bajarlo.
    """
    from fastapi.testclient import TestClient

    from backend_venta import descargas
    from backend_venta.app import app

    instalador = tmp_path / "Plania_Setup.exe"
    token = descargas.crear_token_descarga("comprador-503@plania.uy")
    os.environ["PLANIA_INSTALADOR_PATH"] = str(instalador)
    try:
        c = TestClient(app, client=("203.0.113.222", 51000))
        assert c.get(f"/descargar/{token}").status_code == 503

        # El dueño publica el instalador: el token de ese comprador tiene que
        # seguir sirviendo.
        instalador.write_bytes(b"instalador-publicado")
        r = c.get(f"/descargar/{token}")
        assert r.status_code == 200, "el 503 le había quemado la descarga"
        assert r.content == b"instalador-publicado"

        # Y sigue siendo de un solo uso: el arreglo no puede haber convertido
        # el token en reutilizable.
        assert c.get(f"/descargar/{token}").status_code == 403
    finally:
        os.environ.pop("PLANIA_INSTALADOR_PATH", None)


def test_descargar_instalador_no_publicado_503(tmp_path):
    from fastapi.testclient import TestClient

    from backend_venta import descargas
    from backend_venta.app import app

    token = descargas.crear_token_descarga("cliente-desc@plania.uy")
    os.environ["PLANIA_INSTALADOR_PATH"] = str(tmp_path / "no-existe.exe")
    try:
        c = TestClient(app, client=("203.0.113.76", 51000))
        assert c.get(f"/descargar/{token}").status_code == 503
    finally:
        os.environ.pop("PLANIA_INSTALADOR_PATH", None)


def test_descargar_instalador_exito_sirve_el_archivo_y_consume_el_token(tmp_path):
    from fastapi.testclient import TestClient

    from backend_venta import descargas
    from backend_venta.app import app

    instalador = tmp_path / "Plania_Setup.exe"
    instalador.write_bytes(b"contenido-de-mentira-del-instalador")
    token = descargas.crear_token_descarga("cliente-desc2@plania.uy")
    os.environ["PLANIA_INSTALADOR_PATH"] = str(instalador)
    try:
        c = TestClient(app, client=("203.0.113.77", 51000))
        r = c.get(f"/descargar/{token}")
        assert r.status_code == 200
        assert r.content == b"contenido-de-mentira-del-instalador"
        # de un solo uso: la segunda descarga con el mismo token, 403
        assert c.get(f"/descargar/{token}").status_code == 403
    finally:
        os.environ.pop("PLANIA_INSTALADOR_PATH", None)


def test_todo_endpoint_publico_tiene_rate_limit():
    """Chequeo de cobertura: cada ruta pública de backend_venta/app.py tiene
    un decorador @limiter.limit(...). No prueba que el límite funcione (eso
    lo hace el test siguiente) — prueba que a nadie se le olvidó ponerlo en
    un endpoint nuevo, que es exactamente el tipo de gap que un audit de
    "rate limiting en TODO endpoint" está pensado para encontrar."""
    from backend_venta.app import app

    rutas_publicas = [r for r in app.routes if getattr(r, "path", "").startswith("/")
                      and r.path not in ("/openapi.json", "/docs", "/docs/oauth2-redirect",
                                        "/redoc")]
    assert len(rutas_publicas) >= 9, "se esperaban al menos las 9 rutas conocidas del backend"

    # slowapi registra cada ruta decorada en limiter._route_limits, con clave
    # "módulo.nombre_de_función" — se usa ese registro real (no un atributo
    # adivinado del wrapper, que cambió entre versiones de la librería y
    # daba falsos negativos) para saber qué SÍ quedó decorado.
    registradas = set(app.state.limiter._route_limits) | set(
        app.state.limiter._dynamic_route_limits)

    sin_limite = [r.path for r in rutas_publicas
                  if f"{r.endpoint.__module__}.{r.endpoint.__name__}" not in registradas]

    assert not sin_limite, f"rutas sin @limiter.limit(...): {sin_limite}"


def test_rate_limit_corta_una_rafaga_de_altas_de_demo():
    """La regresión en vivo: /licencias/trial tiene @limiter.limit("5/minute").
    Se golpea 6 veces seguidas desde una IP de prueba propia (203.0.113.*, el
    bloque TEST-NET-3 reservado para documentación — nunca una IP real) y se
    comprueba que la sexta se corta con 429, no que el negocio la deje pasar
    y falle recién en otro lado.

    La IP es exclusiva de este test (no la usa ningún otro) justamente para
    no compartir balde de conteo con `test_backend_endpoints` ni con el resto
    de la suite — si lo compartiera, el orden en que corren los tests podría
    hacer que este test falle o pase por casualidad según cuántas llamadas
    hicieron los demás antes."""
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.50", 51000))

    def pedido(n):
        return {"email": f"rafaga{n}-{uuid.uuid4().hex[:6]}@ratelimit-test.uy",
                "nombre": "Ráfaga", "empresa": "Prueba", "pais": "Uruguay"}

    respuestas = []
    for i in range(6):
        respuestas.append(c.post("/demo/solicitar", json=pedido(i)).status_code)

    assert respuestas[:5] == [200] * 5, f"las primeras 5 deberían pasar: {respuestas}"
    assert respuestas[5] == 429, f"la 6ta tiene que cortarse por límite: {respuestas}"

    # Y una IP distinta no está afectada por la ráfaga de la otra: el límite
    # es por origen, no un semáforo global que deja a todo el mundo afuera.
    otra = TestClient(app, client=("203.0.113.51", 51000))
    assert otra.post("/demo/solicitar", json=pedido("otra-ip")).status_code == 200


def test_licencia_cliente_demo_local():
    from plania import licencia
    est = licencia.estado()
    assert est["modo"] in ("demo", "licencia")
    assert "copiloto" in est["features"]


def test_e2e_demo_a_licencia_paga(monkeypatch):
    """Circuito completo del cliente: pide demo → el dueño se la habilita →
    compra → activación.

    El pedido de demo y la emisión son dos pasos distintos a propósito: la
    demo dejó de ser autoservicio para no regalarle el producto a cualquiera
    que deje un email. Acá se recorren los dos.

    (El pago real lo simula la emisión directa: el webhook de MP termina
    llamando exactamente a licencias.emitir_licencia.)

    Todo lo que toca la configuración local va dentro de un try/finally. Sin
    eso, cuando este test falla en el medio deja la demo vencida en el disco y
    arrastra a media suite con él — que es exactamente lo que pasó cuando la
    demo dejó de ser autoservicio: una falla acá se convirtió en cinco.
    """
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from backend_venta import licencias
    from backend_venta.app import app
    from plania import config as pconfig
    from plania import licencia

    monkeypatch.setenv("PLANIA_BACKEND_ADMIN_TOKEN", "token-e2e")
    del_dueno = {"Authorization": "Bearer token-e2e"}
    correo = f"e2e-{uuid.uuid4().hex[:8]}@plania.uy"

    try:
        # 1) demo local vencida (instalada hace 10 días, más que los 7 de demo)
        pconfig.guardar_extra("LICENCIA_JWT", "")
        pconfig.guardar_extra("LICENCIA_CLAIMS", None)
        inicio_viejo = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        pconfig.guardar_extra("DEMO_INICIO", inicio_viejo)
        est = licencia.estado()
        assert est["modo"] == "vencida"
        assert est["features"] == []

        c = TestClient(app)

        # 2) el interesado pide la demo por la landing: queda registrado, y
        #    NO se lleva ninguna licencia.
        r = c.post("/demo/solicitar", json={
            "email": correo, "nombre": "Ana Prospecto",
            "empresa": "Mayorista del Sur", "pais": "Uruguay"})
        assert r.status_code == 200, r.text
        assert "licencia" not in r.json()

        # 3) el dueño lo atiende y recién ahí le habilita la demo.
        #    `activar_licencia` consulta al backend (no le cree al token sin
        #    verificar) — se le inyecta el mismo TestClient así la activación
        #    golpea al backend de este test en vez de a una URL real.
        r = c.post("/licencias/trial", json={"email": correo}, headers=del_dueno)
        assert r.status_code == 200, r.text
        act = licencia.activar_licencia(r.json()["licencia"], backend_url="",
                                        cliente_http=c)
        assert act["ok"], act
        est = licencia.estado()
        assert est["modo"] == "licencia" and est["plan"] == "trial"
        assert "rutas" in est["features"]

        # 4) paga → webhook emite plan pro → activa y desbloquea todo
        lic_pro = licencias.emitir_licencia(correo, "pro")
        assert licencia.activar_licencia(lic_pro, backend_url="", cliente_http=c)["ok"]
        est = licencia.estado()
        assert est["plan"] == "pro" and licencia.tiene("rutas") and licencia.tiene("copiloto")

        # 5) contra el backend, esa licencia consulta su estado/cupo
        r = c.get("/licencias/estado", headers={"Authorization": f"Bearer {lic_pro}"})
        assert r.status_code == 200 and r.json()["cupo_mensual"] == 2000
    finally:
        pconfig.guardar_extra("LICENCIA_JWT", "")
        pconfig.guardar_extra("LICENCIA_CLAIMS", None)
        pconfig.guardar_extra("LICENCIA_VERIFICADA_EL", None)
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

    # Vercel valida este archivo contra un esquema estricto: una propiedad que
    # no conozca corta el deploy entero, no la ignora. El truco de documentar
    # en JSON con una clave "//" —que en otros archivos es inofensivo— acá
    # rompe la publicación:
    #
    #   The `vercel.json` schema validation failed with the following message:
    #   should NOT have additional property `//ignoreCommand`
    #
    # Lo que haya que explicar de este archivo va en docs/DESPLIEGUE.md.
    CONOCIDAS = {
        "$schema", "buildCommand", "installCommand", "outputDirectory",
        "framework", "cleanUrls", "trailingSlash", "redirects", "rewrites",
        "headers", "ignoreCommand", "devCommand", "public", "regions",
        "functions", "crons", "git", "images", "redirects",
    }
    de_mas = sorted(set(cfg) - CONOCIDAS)
    assert not de_mas, (
        f"vercel.json tiene propiedades que su esquema no admite: {de_mas}. "
        "Vercel corta el deploy en vez de ignorarlas.")


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


def test_la_web_no_promete_mercadopago_si_no_hay_con_que_cobrar():
    """Sin backend, el botón de plan no puede seguir diciendo «Pagar con
    MercadoPago».

    Que el JavaScript ya se comporte distinto (baja al formulario de contacto,
    que abre el cliente de correo) no arregla nada por sí solo: el visitante
    lee el botón, no el JavaScript. Un botón que promete un cobro automático y
    entrega un mailto es publicidad de algo que no existe. Con el backend
    configurado la promesa vuelve sola, porque ahí sí es cierta.
    """
    import os, subprocess, sys
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("PLANIA_")}
    entorno["PATH"] = os.environ["PATH"]

    def generar():
        subprocess.run([sys.executable, os.path.join(RAIZ, "sitio", "build.py")],
                       check=True, capture_output=True, env=entorno, cwd=RAIZ)

    generar()
    for idioma in ("es", "en", "pt"):
        for pagina in ("index.html", os.path.join("implementadores", "index.html")):
            html = open(os.path.join(RAIZ, "web", idioma, pagina), encoding="utf-8").read()
            assert "MercadoPago" not in html, \
                f"web/{idioma}/{pagina} nombra MercadoPago sin backend que cobre"
    es = open(os.path.join(RAIZ, "web", "es", "index.html"), encoding="utf-8").read()
    assert "Hablar con ventas" in es
    assert "coordinamos día y hora" in es, \
        "sin backend la demo se coordina por mail, no se promete automática"

    entorno["PLANIA_BACKEND"] = "https://api.ejemplo.uy"
    try:
        generar()
        es = open(os.path.join(RAIZ, "web", "es", "index.html"), encoding="utf-8").read()
        assert "Pagar con MercadoPago" in es, \
            "con backend configurado el botón vuelve a ser el de pago"
        assert "Te escribimos para coordinar" in es, \
            "con backend el formulario registra el pedido y avisa que lo van a contactar"
    finally:
        del entorno["PLANIA_BACKEND"]
        generar()


def test_el_guardarrail_de_promesas_corta_de_verdad():
    """El control del párrafo anterior no sirve si no puede fallar.

    `verificar_promesas` mira el HTML ya renderizado justamente para agarrar
    una promesa que entre por un texto nuevo de i18n/ o por la plantilla, sin
    que nadie se acuerde de actualizar SIN_BACKEND. Acá se comprueba que ese
    caso corta el build en vez de publicarse.
    """
    import sys
    sys.path.insert(0, os.path.join(RAIZ, "sitio"))
    import build as sitio_build

    sin_backend = {"backend": ""}
    con_backend = {"backend": "https://api.ejemplo.uy"}
    originales = {"p_cta": "Pagar con MercadoPago"}

    with pytest.raises(RuntimeError, match="cobro automático"):
        sitio_build.verificar_promesas("<p>Pagá con MercadoPago</p>", "es",
                                       sin_backend, "index.html", {})

    # También si el texto original sobrevivió al reemplazo, aunque no nombre
    # la marca de la pasarela.
    with pytest.raises(RuntimeError, match="cobro automático"):
        sitio_build.verificar_promesas("<button>Pagar con MercadoPago</button>", "es",
                                       sin_backend, "index.html", originales)

    # Con backend no corta: ahí la promesa es cierta.
    sitio_build.verificar_promesas("<p>Pagá con MercadoPago</p>", "es",
                                   con_backend, "index.html", originales)
    # Y sin promesas tampoco.
    sitio_build.verificar_promesas("<button>Hablar con ventas</button>", "es",
                                   sin_backend, "index.html", originales)


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


def test_los_tres_idiomas_tienen_el_mismo_juego_de_meta_tags():
    """No alcanza con que cada idioma tenga SUS meta tags — tienen que ser
    el MISMO conjunto de etiquetas en los tres, solo con el contenido
    traducido. Si a una versión le falta og:image o twitter:card, esa es la
    que se comparte peor en LinkedIn/WhatsApp sin que nadie lo note hasta
    mirar el link compartido.
    """
    import os
    import re

    juegos = {}
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "web", idioma, "index.html")
        html = open(ruta, encoding="utf-8").read()
        cabeza = html.split("</head>")[0]
        # El "nombre" del tag: la property/name, no el content (que cambia
        # con el idioma a propósito).
        nombres = re.findall(r'<meta\s+(?:property|name)="([^"]+)"', cabeza)
        otros = re.findall(r"<(link|title)\b", cabeza)
        juegos[idioma] = sorted(nombres) + sorted(otros)

    es, en, pt = juegos["es"], juegos["en"], juegos["pt"]
    assert es == en == pt, f"meta tags distintos entre idiomas: es={es} en={en} pt={pt}"

    # Y las imágenes que esos tags declaran existen de verdad, para las tres.
    for idioma in ("es", "en", "pt"):
        ruta_imagen = os.path.join(RAIZ, "web", "assets", f"og_{idioma}.png")
        assert os.path.exists(ruta_imagen), f"falta {ruta_imagen} (sitio/generar_og.py)"


def test_landing_promete_erps_que_el_conector_soporta_de_verdad():
    """La landing nombra ERPs concretos (Zureo, Memory, Tango, Bejerman, Odoo,
    SAP Business One) en vez de 'se adapta a cualquier ERP' sin más — pero
    un nombre propio en el marketing que el código no cumple es peor que no
    decir nada. Se comprueba texto Y código: el texto nombra los seis, y el
    autodetector reconoce de verdad los nombres de columna DISTINTIVOS y
    documentados públicamente de Odoo y de SAP Business One (los dos ERPs
    de la lista con esquemas públicos verificables; Zureo/Memory/Tango/
    Bejerman no publican su esquema, por eso no se los puede chequear igual
    de literal)."""
    import json

    ERPS = ["Zureo", "Memory", "Tango", "Bejerman", "Odoo", "SAP Business One"]
    for idioma in ("es", "en", "pt"):
        with open(os.path.join(RAIZ, "sitio", "i18n", f"{idioma}.json"), encoding="utf-8") as f:
            texto = json.load(f)["f1_d"]
        for erp in ERPS:
            assert erp in texto, f"'{erp}' no aparece en f1_d de {idioma}.json"

    todos = {c for tabla in conectores.SINONIMOS.values()
            for cols in tabla.values() for c in cols}
    de_odoo = {"default_code", "list_price", "standard_price", "partner_id",
              "product_uom_qty"}
    de_sap_b1 = {"cardcode", "cardname", "itemcode", "itemname", "docentry",
                "docdate", "stockprice", "itmsgrpnam"}
    assert de_odoo <= todos, f"faltan sinónimos de columnas de Odoo: {de_odoo - todos}"
    assert de_sap_b1 <= todos, f"faltan sinónimos de columnas de SAP B1: {de_sap_b1 - todos}"


def test_cada_erp_nombrado_tiene_su_propia_seccion():
    """No alcanza con que los cuatro nombres aparezcan en una sola frase
    genérica (eso ya lo cubre test_landing_promete_erps...): un dueño de
    distribuidora tiene que ver SU sistema con su propio párrafo, no una
    enumeración de seis nombres dentro de la tarjeta de otra cosa.

    Se comprueba sobre el i18n (la fuente) y sobre el HTML ya generado (lo
    que de verdad se publica), para que un build viejo sin rehacer no
    esconda una regresión.
    """
    import json
    NOMBRES = ["Zureo", "Memory", "Tango", "Bejerman"]
    for idioma in ("es", "en", "pt"):
        with open(os.path.join(RAIZ, "sitio", "i18n", f"{idioma}.json"), encoding="utf-8") as f:
            textos = json.load(f)
        for i, nombre in enumerate(NOMBRES, start=1):
            titulo = textos.get(f"erp{i}_t", "")
            cuerpo = textos.get(f"erp{i}_d", "")
            assert titulo == nombre, f"erp{i}_t de {idioma}.json es '{titulo}', esperaba '{nombre}'"
            assert len(cuerpo) > 60, f"erp{i}_d de {idioma}.json es demasiado corto para ser propio"

        ruta_html = os.path.join(RAIZ, "web", idioma, "index.html")
        assert os.path.exists(ruta_html), f"falta {ruta_html} — correr sitio/build.py"
        html = open(ruta_html, encoding="utf-8").read()
        assert 'id="erps"' in html
        for nombre in NOMBRES:
            # Como <h3>, no como palabra suelta en un párrafo compartido.
            assert f"<h3>{nombre}</h3>" in html, \
                f"'{nombre}' no tiene su propio <h3> en web/{idioma}/index.html"


def test_las_cinco_sugerencias_tienen_ejemplo_numerico_real(datos):
    """Los cinco motores de sitio/i18n/*.json no pueden ser una promesa
    genérica: para sobrestock, reposición, precios y recupero se vuelve a
    correr el motor real sobre la base de demostración y se comprueba que el
    número que muestra la landing sea el que el motor devuelve. Si alguien
    publica un número inventado, o regenera la demo con otra semilla y no
    actualiza el texto, esto lo agarra.

    Por qué con tolerancia y no con el número exacto
    ------------------------------------------------
    `data/erp_demo.db` NO está versionada (`.gitignore`: `data/*.db`) y
    `data/generate_dataset.py` la arma con `hoy = date.today()`: la ventana
    de ventas se corre un día por día. Con la misma semilla y el mismo
    código, el total de margen recuperable dio 96.402 un martes y 96.384 el
    jueves siguiente.

    Comparar el número exacto convertía eso en un CI que se ponía rojo solo,
    sin que nadie hubiera tocado nada — que es peor que no tener control:
    enseña a ignorarlo. La tolerancia deja pasar la deriva normal del
    calendario y sigue cazando lo que importa, que es un número inventado o
    de otra base (esos no fallan por 1%, fallan por un orden de magnitud).

    Venta cruzada no tiene ejemplo en esa base (la semilla 42 no genera una
    brecha de zona accionable — se comprobó a mano probando semillas), así
    que ahí solo se controla que el ejemplo tenga la forma de un hallazgo
    real (dos porcentajes distintos y una zona), no un número recalculado.
    """
    import json
    import re
    paquete = sugerencias.generar_todas(datos)

    # 3%: la deriva medida es del orden del 2% mensual en el peor de los
    # cuatro (venta_recuperable). Da meses de margen antes de pedir un
    # refresco, y un número de otra base o inventado queda afuera igual.
    TOLERANCIA = 0.03

    esperado = {
        "s1_d": paquete["resumen"]["capital_liberable"],
        "s2_d": paquete["resumen"]["venta_en_riesgo"],
        "s3_d": paquete["resumen"]["margen_extra_mensual"],
        "s5_d": paquete["resumen"]["venta_recuperable"],
    }
    for idioma in ("es", "en", "pt"):
        with open(os.path.join(RAIZ, "sitio", "i18n", f"{idioma}.json"), encoding="utf-8") as f:
            textos = json.load(f)
        for clave, valor in esperado.items():
            # Los miles se separan con "." en es/pt y con "," en en; se
            # normaliza y se sacan todos los números del texto, porque cada
            # párrafo trae además el del ejemplo puntual y algún porcentaje.
            texto = textos[clave].replace(",", ".")
            candidatos = [float(n.replace(".", ""))
                          for n in re.findall(r"\d[\d.]*\d|\d", texto)]
            cerca = [n for n in candidatos
                     if valor and abs(n - valor) / valor <= TOLERANCIA]
            assert cerca, (
                f"{clave} de {idioma}.json no menciona ningún número parecido "
                f"al que devuelve hoy sugerencias.generar_todas(): "
                f"{round(valor):,}".replace(",", ".") + ".\n"
                f"Los números del texto son {[round(c) for c in candidatos]}.\n"
                f"Si es sólo deriva del calendario (la base demo se genera con "
                f"la fecha de hoy), refrescalos — NO los corrijas a mano, son "
                f"4 números x 3 idiomas y este control corta en el primero:\n"
                f"    python3 sitio/actualizar_ejemplos.py            # ver qué cambió\n"
                f"    python3 sitio/actualizar_ejemplos.py --escribir # aplicarlo\n"
                f"    python3 sitio/build.py                          # regenerar la web")
        # Venta cruzada: forma de hallazgo real, no un párrafo genérico.
        assert re.search(r"\d+%.*\d+%", textos["s4_d"]), \
            f"s4_d de {idioma}.json no trae dos porcentajes (el hallazgo real de zona)"


def test_pagina_de_implementadores_existe_con_comision():
    """Criterio de aceptación explícito: tiene que existir una página con
    'implementador' en la URL o el título, en los tres idiomas, y tiene que
    decir en números qué comisión se paga — no un "contactanos y vemos"."""
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "web", idioma, "implementadores", "index.html")
        assert os.path.exists(ruta), f"falta {ruta} — correr sitio/build.py"
        html = open(ruta, encoding="utf-8").read()
        assert "implementador" in html.lower() or "implementer" in html.lower()
        assert "{{" not in html, "quedaron marcadores de plantilla sin resolver"
        # El % de comisión recurrente tiene que estar en números, visible.
        assert re.search(r"20\s*%", html), \
            f"web/{idioma}/implementadores/index.html no muestra el % de comisión"


def test_video_arranca_sin_autoplay_ni_sonido_forzado():
    """Un video que arranca solo y con sonido es el tipo de cosa que hace
    que alguien cierre la pestaña. El control es sobre el HTML publicado,
    no sobre la intención: si algún día alguien agrega autoplay al <video>,
    esto tiene que fallar."""
    for idioma in ("es", "en", "pt"):
        html = open(os.path.join(RAIZ, "web", idioma, "index.html"), encoding="utf-8").read()
        etiqueta = re.search(r"<video\b[^>]*>", html)
        assert etiqueta, f"no hay <video> en web/{idioma}/index.html"
        assert "autoplay" not in etiqueta.group(0)
        assert "controls" in etiqueta.group(0)


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
    # VoiceBox clona desde 3 segundos; menos que eso da un timbre pobre. Mide
    # la duración real con ffmpeg — imageio_ffmpeg es de sitio/requirements.txt
    # (herramientas de contenido), no del producto, así que en una máquina
    # limpia que solo instaló requirements-dev.txt este test se saltea en vez
    # de fallar por una dependencia que no tiene por qué tener.
    pytest.importorskip("imageio_ffmpeg")
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

        # La voz ya no dice el dominio —el motor no lo pronuncia bien en ningún
        # idioma— pero el subtítulo tiene que mostrarlo igual: es el llamado a
        # la acción del video. Se controla contra el subtítulo y no contra el
        # texto hablado, porque justamente ya no coinciden.
        assert "plania.uy" in texto, f"el subtítulo {idioma} perdió el dominio"
        assert "Plania" in texto, f"el subtítulo {idioma} no nombra la marca"

        # Y ninguna forma dictada de la marca puede haberse colado.
        for dictada in ("Planía", "Plan ay eye", "Plan I A"):
            assert dictada not in texto, \
                f"'{dictada}' se escribe así solo para la voz, no para el subtítulo {idioma}"


# ---------------------------------------------------------------------------
# Arranque del programa PC: puertos e instalador
# ---------------------------------------------------------------------------
def _lanzador():
    import sys, os
    sys.path.insert(0, os.path.join(RAIZ, "packaging"))
    import plania_launcher
    return plania_launcher


def test_nunca_se_elige_un_puerto_ocupado():
    """El bug que reportó el usuario: Plania abría otro programa que ya tenía
    corriendo. Pasaba porque el lanzador daba por libre un puerto ocupado —en
    Windows un bind con SO_REUSEADDR tiene éxito aunque otro proceso esté
    escuchando ahí.

    El test no toca los puertos reales de Plania: se ocupan puertos que el
    propio test reserva. Si usara los reales, fallaría cada vez que quien
    corre los tests tenga Plania abierto, que es justo cuando no hay ningún
    problema.
    """
    import http.server, socketserver, threading

    L = _lanzador()

    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()

    servidores = []
    ocupados = []
    try:
        for _ in range(3):
            s = socketserver.TCPServer(("127.0.0.1", 0), _H)   # puerto efímero
            threading.Thread(target=s.serve_forever, daemon=True).start()
            servidores.append(s)
            ocupados.append(s.server_address[1])

        for p in ocupados:
            assert L._ocupado(p) is True, f"no detectó que {p} está ocupado"

        original = L.PUERTOS
        try:
            L.PUERTOS = tuple(ocupados)          # todos los candidatos ocupados
            elegido = L._puerto_libre()
        finally:
            L.PUERTOS = original

        assert elegido not in ocupados, f"eligió un puerto ocupado: {elegido}"
        assert L._ocupado(elegido) is False
    finally:
        for s in servidores:
            s.shutdown()


def test_no_se_usa_el_puerto_por_defecto_de_streamlit():
    """8501 es el puerto de cualquier app Streamlit. Usarlo garantiza chocar
    con otra que el usuario tenga abierta — y que vea esa en vez de Plania."""
    import os
    L = _lanzador()
    assert 8501 not in L.PUERTOS

    bat = open(os.path.join(RAIZ, "INICIAR_PLANIA.bat"), encoding="utf-8",
               errors="replace").read()
    ejecutables = [l for l in bat.splitlines()
                   if not l.strip().lower().startswith("rem")]
    assert not any("8501" in l for l in ejecutables), \
        "el lanzador .bat volvió a fijar el puerto 8501"
    assert "plania_launcher.py" in bat, \
        "el .bat tiene que arrancar por el lanzador, que elige puerto libre"


def test_la_app_instalada_no_depende_del_python_del_usuario():
    """Si el instalador quedó sin motor, la app tiene que decirlo. Antes caía
    al python del sistema —que el cliente no tiene— y se quedaba para siempre
    en la pantalla de carga: eso es 'el instalador no funciona'."""
    import os
    main = open(os.path.join(RAIZ, "desktop", "main.js"), encoding="utf-8").read()
    empaquetado = main.split("if (app.isPackaged)")[1].split("// 2)")[0]
    assert "throw new Error" in empaquetado, \
        "empaquetado sin motor tiene que fallar con mensaje, no caer al python del sistema"
    assert "spawn(python" not in empaquetado


def test_el_release_no_publica_un_instalador_sin_motor():
    import os
    wf = open(os.path.join(RAIZ, ".github", "workflows", "release.yml"),
              encoding="utf-8").read()
    publicar = wf.index("Publicar release")
    assert "dist/Plania/Plania.exe" in wf[:publicar], \
        "falta verificar que PyInstaller dejó el motor antes de publicar"
    assert "electron-builder no dejo ningun .exe" in wf[:publicar]


def test_el_programa_no_se_publica_en_la_red_local():
    """Streamlit escucha en 0.0.0.0 por defecto y anuncia una 'Network URL':
    en una oficina, cualquiera en la misma red podría abrir el Plania de otro
    y ver sus ventas, márgenes y clientes. Un programa de escritorio tiene que
    escuchar solo en la máquina del usuario."""
    import inspect
    L = _lanzador()
    assert '"STREAMLIT_SERVER_ADDRESS", "127.0.0.1"' in inspect.getsource(L.main)
    # La dirección se le pasa a Streamlit en _servir, que es quien lo arranca.
    servir = inspect.getsource(L._servir)
    assert 'os.environ["STREAMLIT_SERVER_ADDRESS"]' in servir, \
        "la dirección tiene que salir del entorno, no estar fija en el arranque"
    assert 'set_option("server.address", direccion)' in servir, \
        "sin esto Streamlit vuelve a su default 0.0.0.0 y se expone a la red"


def test_lanzador_elige_puerto_libre_valido():
    pl = _lanzador()
    p = pl._puerto_libre()
    assert 0 < p < 65536
    # tiene que poder bindearse de verdad, no solo devolver un número
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", p))


def test_lanzador_tee_no_pierde_el_log_si_la_consola_falla():
    """El .exe empaquetado a veces tiene una consola que no se comporta como
    un archivo real. Si escribir ahí falla, el log en disco —que es lo que
    de verdad sirve para diagnosticar un problema reportado después— no se
    puede perder por eso."""
    import tempfile

    pl = _lanzador()

    class ConsolaRota:
        def write(self, t):
            raise OSError("sin consola")

        def flush(self):
            raise OSError("sin consola")

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as buf:
        tee = pl._Tee(ConsolaRota(), buf)
        tee.write("hola\n")
        tee.flush()
        buf.seek(0)
        assert buf.read() == "hola\n"
    assert tee.isatty() is False


def test_lanzador_carpeta_de_logs_en_datos_de_usuario():
    """Los logs van a la carpeta de datos del usuario, no a Archivos de
    programa: ahí un programa instalado no tiene permiso de escritura."""
    import tempfile

    pl = _lanzador()
    tmp = tempfile.mkdtemp()
    viejo = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = tmp
    try:
        carpeta = pl._carpeta_logs()
        assert carpeta.startswith(tmp)
        assert os.path.isdir(carpeta)
    finally:
        if viejo is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = viejo


# ---------------------------------------------------------------------------
# Empaquetado del instalador Windows (packaging/)
# ---------------------------------------------------------------------------
def test_build_release_deja_una_copia_del_setup_sin_version_en_el_nombre(tmp_path, monkeypatch):
    """backend_venta/app.py sirve dist/Plania_Setup.exe por defecto para la
    descarga post-pago, pero Inno Setup compila con la versión en el nombre
    (Plania_Setup_v1.0.0.exe). Sin la copia, esa ruta por defecto nunca
    existe y /descargar/{token} queda roto hasta setear PLANIA_INSTALADOR_PATH
    a mano — bug real que este test fija.
    """
    import importlib
    sys.path.insert(0, os.path.join(RAIZ, "packaging"))
    br = importlib.import_module("build_release")

    monkeypatch.setattr(br, "DIST", str(tmp_path))
    monkeypatch.setattr(br.shutil, "which", lambda _n: "/usr/bin/iscc-fake")

    def _run_falso(cmd):
        # Simula lo que hace ISCC de verdad: dejar el .exe compilado en DIST.
        (tmp_path / "Plania_Setup_v1.0.0.exe").write_bytes(b"exe de mentira")

    monkeypatch.setattr(br, "_run", _run_falso)

    versionado = br.paso_instalador()
    assert versionado == str(tmp_path / "Plania_Setup_v1.0.0.exe")

    estable = tmp_path / "Plania_Setup.exe"
    assert estable.exists(), "falta la copia sin versión que espera el backend"
    assert estable.read_bytes() == (tmp_path / "Plania_Setup_v1.0.0.exe").read_bytes()


def test_backend_venta_busca_el_setup_en_la_ruta_que_build_release_genera():
    """La ruta por defecto de /descargar/{token} y el nombre de archivo que
    build_release.py deja como copia estable tienen que coincidir. Si alguien
    cambia uno sin el otro, la descarga post-pago se rompe en silencio."""
    with open(os.path.join(RAIZ, "backend_venta", "app.py"), encoding="utf-8") as f:
        backend = f.read()
    with open(os.path.join(RAIZ, "packaging", "build_release.py"), encoding="utf-8") as f:
        build = f.read()
    assert '"Plania_Setup.exe"' in backend
    assert '"Plania_Setup.exe"' in build


def test_instalador_deja_elegir_carpeta_y_no_rompe_con_plania_abierto():
    """Control de sanidad del .iss: no se puede compilar con ISCC en Linux,
    así que se valida por texto que las propiedades que pidió el usuario
    —elegir dónde instalar, y no romperse por archivos bloqueados— están."""
    with open(os.path.join(RAIZ, "packaging", "instalador.iss"), encoding="utf-8") as f:
        iss = f.read()
    assert "DisableDirPage=no" in iss
    assert "InitializeSetup" in iss and "InitializeUninstall" in iss
    assert "MinVersion=" in iss
    assert "AppPublisherURL=" in iss


def test_lanzador_pc_console_true_documentado_y_electron_lo_oculta():
    """console=True es intencional (ver docstring del lanzador) — un cambio
    accidental a False rompería la única forma de cerrar la versión
    standalone sin agregar antes una bandeja del sistema. Y del lado de
    Electron, windowsHide tiene que estar para no mostrar esa consola
    igual como una ventana suelta."""
    with open(os.path.join(RAIZ, "packaging", "plania.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "console=True" in spec

    with open(os.path.join(RAIZ, "desktop", "main.js"), encoding="utf-8") as f:
        main_js = f.read()
    assert "windowsHide: true" in main_js


def test_la_marca_es_plania_en_los_tres_idiomas():
    """El nombre del producto es "Plania" en español, inglés y portugués —
    el juego de palabras PLAN + IA / PLAN + AI se conserva igual en los
    tres. Lo único que cambia entre idiomas es cómo lo PRONUNCIA la voz del
    video (ver PARA_LEER en doblar_video.py), nunca el nombre escrito."""
    import os
    for idioma in ("es", "en", "pt"):
        html = open(os.path.join(RAIZ, "web", idioma, "index.html"), encoding="utf-8").read()
        assert "PLAN<span>IA</span>" in html
        assert "Schedule" not in html


def test_narracion_en_ingles_dice_plania():
    doblar, guion = _guion()
    intro_en = guion["segmentos"][0]["en"]
    assert "Schedule" not in intro_en
    # Se escribe deletreada para que la voz pronuncie el juego de palabras
    # PLAN + AI en vez de leer "Plania" como una palabra inventada; el
    # subtítulo (doblar.texto_subtitulo) la vuelve a mostrar como "Plania".
    assert doblar.texto_subtitulo(intro_en).startswith("This is Plania.")


# ---------------------------------------------------------------------------
# Protección del código de negocio (Cython) para la distribución
# ---------------------------------------------------------------------------
def test_proteger_codigo_compila_y_se_comporta_igual(tmp_path):
    """Prueba real de packaging/proteger_codigo.py — no que "compile sin
    tirar error", sino que lo compilado se comporte igual que el .py
    original. Corre en un subproceso aparte, contra una carpeta temporal
    propia, para no tocar ni el repo ni el estado de los demás tests.

    Se salta si no hay Cython instalado: es una dependencia de build, no de
    runtime, y no todos los entornos de test la tienen.
    """
    import shutil
    import subprocess
    import textwrap

    pytest.importorskip("Cython")
    if not shutil.which("gcc") and not shutil.which("cc"):
        pytest.skip("no hay compilador de C disponible en este entorno")

    destino = str(tmp_path / "protegido")
    env = dict(os.environ, PLANIA_BUILD_FUENTE=destino)

    r = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "packaging", "proteger_codigo.py")],
        cwd=RAIZ, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"proteger_codigo.py falló:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"

    carpeta_plania = os.path.join(destino, "plania")
    # No se puede hacer "from packaging import proteger_codigo": packaging/
    # no tiene __init__.py (no es un paquete de Python, es la carpeta de
    # empaquetado) y encima "packaging" es también el nombre de una
    # biblioteca de PyPI instalada — el import ambiguo termina resolviendo
    # a esa, no a este script. Se importa por ruta de archivo.
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "proteger_codigo", os.path.join(RAIZ, "packaging", "proteger_codigo.py"))
    proteger_codigo = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(proteger_codigo)
    for modulo in proteger_codigo.MODULOS_PROTEGIDOS:
        assert not os.path.exists(os.path.join(carpeta_plania, modulo)), \
            f"{modulo} debería haberse borrado tras compilar"

    # La edición por defecto es la de CLIENTE, y a esa se le sacan los módulos
    # que son solo del dueño (panel owner, modelo de negocio, kit de
    # contenido, verificación). Así que lo esperado no son los 12 protegidos
    # sino los 12 menos esos: contarlos contra los 12 daba un falso error.
    solo_owner = proteger_codigo.MODULOS_SOLO_OWNER["plania"]
    esperados = [m for m in proteger_codigo.MODULOS_PROTEGIDOS if m not in solo_owner]
    binarios = [f for f in os.listdir(carpeta_plania) if f.endswith((".so", ".pyd"))]
    assert sorted(b.split(".")[0] for b in binarios) == sorted(m[:-3] for m in esperados)

    # Lo que de verdad importa de esa cuenta: que un build de cliente no se
    # vaya incompleto. Si un módulo declarado se perdiera en el camino —sin
    # .so y sin .py— el producto instalado no arrancaría, y el script tiene
    # que haber cortado antes de llegar acá.
    import ast
    disponibles = {f.split(".")[0] for f in os.listdir(carpeta_plania)}
    for base, _dirs, files in os.walk(destino):
        if "_build_c" in base or os.sep + "build" in base:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            try:
                arbol = ast.parse(open(os.path.join(base, f), encoding="utf-8").read())
            except SyntaxError:
                continue

            def _pedidos(n):
                if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("plania"):
                    partes = (n.module or "").split(".")
                    return [partes[1]] if len(partes) > 1 else [a.name for a in n.names]
                if isinstance(n, ast.Import):
                    return [a.name.split(".")[1] for a in n.names
                            if a.name.startswith("plania.")]
                return []

            # Un import adentro de `if find_spec("plania.X"):` es opcional a
            # propósito: el módulo puede no estar y el código ya lo previó.
            # Es el caso de plania/api.py con el panel del dueño, que se saca
            # del build del cliente. Se reconoce el patrón en vez de listar
            # excepciones por nombre: para quedar exento hay que escribir la
            # guarda de verdad, no figurar en una lista. Que además funcione
            # lo comprueba, importando el árbol podado,
            # test_la_api_del_build_de_cliente_no_expone_ninguna_ruta_del_dueno.
            opcionales = set()
            for n in ast.walk(arbol):
                if isinstance(n, ast.If) and "find_spec" in ast.dump(n.test):
                    for sub in ast.walk(n):
                        opcionales.update(_pedidos(sub))

            for n in ast.walk(arbol):
                for p in _pedidos(n):
                    if p in opcionales:
                        continue
                    assert p in disponibles, \
                        f"{os.path.relpath(os.path.join(base, f), destino)} importa " \
                        f"plania.{p}, que no está en el build: el cliente no podría abrirlo"

    # __init__.py y config.py SÍ tienen que seguir siendo .py — no son el
    # diferenciador del producto (ver el porqué en proteger_codigo.py).
    assert os.path.exists(os.path.join(carpeta_plania, "__init__.py"))
    assert os.path.exists(os.path.join(carpeta_plania, "config.py"))

    # Nada de bytecode legible de un módulo protegido en ningún __pycache__
    # del árbol protegido.
    for base, _dirs, files in os.walk(destino):
        if os.path.basename(base) == "__pycache__":
            for f in files:
                nombre = f.split(".cpython")[0]
                assert f"{nombre}.py" not in proteger_codigo.MODULOS_PROTEGIDOS, \
                    f"quedó bytecode legible de un módulo protegido: {base}/{f}"

    # Comportamiento: en un intérprete nuevo, con `destino` primero en el
    # sys.path, ¿la versión compilada hace lo mismo que hace el .py? Se
    # repite la misma aserción que test_ofertas_nunca_debajo_del_piso corre
    # contra el código fuente.
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {RAIZ!r})
        sys.path.insert(0, {destino!r})   # se inserta último -> queda primero -> gana
        from plania import conectores, analitica, sugerencias
        assert sugerencias.__file__.endswith((".so", ".pyd")), sugerencias.__file__

        from data import generate_dataset
        import os
        if not os.path.exists(os.path.join({RAIZ!r}, "data", "erp_demo.db")):
            generate_dataset.main(seed=42)
        datos = conectores.cargar_datos()
        v = analitica.enriquecer_ventas(datos["ventas"], datos["productos"], datos["clientes"])
        of = sugerencias.ofertas_por_sobrestock(datos["productos"], v)
        piso = of.merge(datos["productos"][["sku", "costo"]], on="sku")
        assert len(of) > 0
        assert (piso["precio_oferta"] >= piso["costo"] * 1.079).all()
        print("OK: el binario compilado ofrece lo mismo que el .py original")
    """)
    r2 = subprocess.run([sys.executable, "-c", script], cwd=RAIZ,
                        capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, f"{r2.stdout}\n{r2.stderr}"
    assert "OK:" in r2.stdout


# ---------------------------------------------------------------------------
# Licencias: activación no forjable, plan owner
# ---------------------------------------------------------------------------
def _limpiar_licencia_local():
    from plania import config as pconfig
    for clave in ("LICENCIA_JWT", "LICENCIA_CLAIMS", "LICENCIA_VERIFICADA_EL"):
        pconfig.guardar_extra(clave, None)


def test_activar_sin_backend_configurado_no_le_echa_la_culpa_a_la_conexion(monkeypatch):
    """Sin backend desplegado no se puede activar NINGUNA licencia, ni siquiera
    una paga: activar consulta `GET {backend}/licencias/estado`. Eso hoy es así
    y el código no lo puede arreglar solo — lo que sí puede es no mentir sobre
    la causa.

    El mensaje viejo era «Probá de nuevo con internet», que manda a revisar la
    conexión a alguien cuya conexión anda bien, por un problema que además no
    es suyo. Cuando el backend quedó en el valor sin configurar, el mensaje lo
    dice y apunta a dónde escribir.
    """
    import jwt as pyjwt

    from plania import config as pconfig
    from plania import licencia

    monkeypatch.delenv("PLANIA_BACKEND_URL", raising=False)
    monkeypatch.setattr(pconfig, "leer_extra", lambda *a, **kw: None)
    token = pyjwt.encode({"sub": "x", "plan": "pro"}, "cualquiera", algorithm="HS256")

    class _SinNadieEscuchando:
        def get(self, *a, **kw):
            raise OSError("connection refused")

    r = licencia.activar_licencia(token, cliente_http=_SinNadieEscuchando())
    assert r["ok"] is False
    assert r["motivo"] == "sin_backend"
    assert "internet" not in r["error"].lower()
    assert "ventas@plania.uy" in r["error"]

    # Con un backend real configurado y caído, sí es un problema de red y el
    # mensaje vuelve a ser el de siempre.
    monkeypatch.setenv("PLANIA_BACKEND_URL", "https://api.plania.uy")
    r = licencia.activar_licencia(token, cliente_http=_SinNadieEscuchando())
    assert r["motivo"] == "red"


def test_un_token_forjado_no_activa_ninguna_licencia():
    """La regresión central: hasta esta versión, activar_licencia() decodificaba
    el JWT con verify_signature=False y solo miraba el vencimiento — cualquiera
    podía fabricarse un token con jwt.encode(payload, "lo que sea") y activarse
    el plan que quisiera, gratis y para siempre. Se probó ejecutándolo contra
    el código real antes de arreglarlo; esto lo deja como test permanente."""
    import time

    import jwt as pyjwt
    from fastapi.testclient import TestClient

    from backend_venta.app import app
    from backend_venta import licencias as lic
    from plania import licencia

    _limpiar_licencia_local()
    try:
        c = TestClient(app)
        forjado = pyjwt.encode(
            {"sub": "nadie@nada.com", "plan": "enterprise",
             "features": lic.PLANES["enterprise"]["features"],
             "exp": int(time.time()) + 999999999},
            # 32+ bytes a propósito: nada que ver con el secreto real (que el
            # atacante no conoce), es solo para no disparar el
            # InsecureKeyLengthWarning de PyJWT por longitud de clave y que
            # tape con ruido las advertencias que sí importan.
            "un-secreto-que-me-invento-yo-y-que-nadie-mas-conoce", algorithm="HS256")

        r = licencia.activar_licencia(forjado, backend_url="", cliente_http=c)
        assert r["ok"] is False
        assert r["motivo"] == "rechazada"

        # y no debe haber quedado activada ninguna licencia como efecto colateral
        est = licencia.estado()
        assert est["modo"] != "licencia"
    finally:
        _limpiar_licencia_local()


def test_activar_licencia_sin_red_no_se_confunde_con_rechazada():
    """Si el backend no se puede contactar, la activación tiene que fallar
    igual (nunca se acepta sin verificar), pero el motivo tiene que ser
    distinguible de un rechazo explícito — estado() usa esa diferencia para
    decidir si sigue confiando en la última licencia verificada o la
    descarta (ver plania/licencia.py)."""
    from plania import licencia

    class _SiempreFalla:
        def get(self, *a, **k):
            raise ConnectionError("simulado: no hay red")

    r = licencia.activar_licencia("a.b.c", backend_url="https://api.plania.uy",
                                  cliente_http=_SiempreFalla())
    assert r["ok"] is False
    assert r["motivo"] == "red"

    # La instalación sin backend configurado también falla sin ser un rechazo
    # —`estado()` la trata igual que a la caída de red, con su tolerancia de
    # días— pero se distingue para poder explicarle al usuario que el problema
    # no es su conexión (ver el test de más abajo).
    r = licencia.activar_licencia("a.b.c", backend_url=licencia._BACKEND_SIN_CONFIGURAR,
                                  cliente_http=_SiempreFalla())
    assert r["motivo"] == "sin_backend"
    assert r["motivo"] != "rechazada"


def test_estado_revalida_y_descarta_si_el_backend_rechaza(monkeypatch):
    """Una licencia activada hace tiempo se revalida sola contra el backend.
    Si el backend dice explícitamente que ya no vale (plan cancelado, etc.),
    estado() tiene que dejar de confiar en la caché en el momento, no seguir
    usándola hasta que expire la tolerancia de "sin red"."""
    from datetime import datetime, timedelta, timezone

    from plania import config as pconfig
    from plania import licencia

    _limpiar_licencia_local()
    try:
        pconfig.guardar_extra("LICENCIA_JWT", "a.b.c")
        pconfig.guardar_extra("LICENCIA_CLAIMS", {
            "cliente": "x@y.uy", "plan": "pro", "cupo_mensual": 2000,
            "features": ["copiloto", "erp"],
            "expira": (datetime.now(timezone.utc) + timedelta(days=20)).timestamp(),
        })
        vieja = (datetime.now(timezone.utc)
                - timedelta(hours=licencia._REVALIDAR_CADA_HORAS + 1)).isoformat()
        pconfig.guardar_extra("LICENCIA_VERIFICADA_EL", vieja)

        monkeypatch.setattr(licencia, "activar_licencia",
                            lambda *a, **k: {"ok": False, "motivo": "rechazada",
                                             "error": "revocada"})
        est = licencia.estado()
        assert est["modo"] != "licencia"
    finally:
        _limpiar_licencia_local()


def test_estado_tolera_no_tener_red_por_un_tiempo_sin_perder_la_licencia():
    """Mismo escenario, pero el backend no se pudo contactar (no dijo que no,
    simplemente no se sabe). Recién activada, dentro de la tolerancia, sigue
    confiando en la última confirmación en vez de bajar a demo/vencida."""
    from datetime import datetime, timedelta, timezone

    from plania import config as pconfig
    from plania import licencia

    _limpiar_licencia_local()
    try:
        pconfig.guardar_extra("LICENCIA_JWT", "a.b.c")
        pconfig.guardar_extra("LICENCIA_CLAIMS", {
            "cliente": "x@y.uy", "plan": "pro", "cupo_mensual": 2000,
            "features": ["copiloto", "erp"],
            "expira": (datetime.now(timezone.utc) + timedelta(days=20)).timestamp(),
        })
        vieja = (datetime.now(timezone.utc)
                - timedelta(hours=licencia._REVALIDAR_CADA_HORAS + 1)).isoformat()
        pconfig.guardar_extra("LICENCIA_VERIFICADA_EL", vieja)

        # Se reemplaza activar_licencia por una que "no puede" confirmar
        # (motivo red), simulando que estado() la invoca internamente para
        # revalidar y la red falla.
        import plania.licencia as mod
        original = mod.activar_licencia

        def _falla_de_red(token, *a, **k):
            return {"ok": False, "motivo": "red", "error": "sin internet"}

        mod.activar_licencia = _falla_de_red
        try:
            est = licencia.estado()
        finally:
            mod.activar_licencia = original

        assert est["modo"] == "licencia" and est["plan"] == "pro"
    finally:
        _limpiar_licencia_local()


def test_plan_owner_no_tiene_restricciones_y_no_es_publico():
    """El plan del dueño: todas las features, sin cupo, sin fecha de
    vencimiento real (100 años), y NO listado en /planes — no es un plan de
    catálogo, solo se emite con packaging/generar_licencia_owner.py o con el
    token de admin."""
    from fastapi.testclient import TestClient

    from backend_venta.app import app
    from backend_venta import licencias as lic

    assert lic.PLANES["owner"]["cupo_mensual"] is None
    assert lic.PLANES["owner"]["precio"] is None  # no se puede comprar
    assert set(lic.PLANES["owner"]["features"]) == set(lic.PLANES["enterprise"]["features"])
    assert lic.PLANES["owner"]["dias"] >= 36500

    assert "owner" not in lic.PLANES_PUBLICOS
    c = TestClient(app)
    assert "owner" not in c.get("/planes").json()

    # y sí activa de punta a punta, igual que cualquier plan pago
    from plania import licencia
    _limpiar_licencia_local()
    try:
        token = lic.emitir_licencia("dueno@plania.uy", "owner")
        r = licencia.activar_licencia(token, backend_url="", cliente_http=c)
        assert r["ok"] and r["claims"]["plan"] == "owner"
        assert licencia.tiene("white_label") and licencia.tiene("sso")
    finally:
        _limpiar_licencia_local()


def test_generador_de_licencia_owner_produce_un_token_valido():
    """packaging/generar_licencia_owner.py es lo que documenta y ejecuta el
    dueño para su propia licencia sin restricciones — se corre de verdad,
    no se lee el código y se asume."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "packaging", "generar_licencia_owner.py"),
         "dueno-de-prueba@plania.uy"],
        cwd=RAIZ, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PLANIA_CONFIG_DIR": os.environ["PLANIA_CONFIG_DIR"]})
    assert r.returncode == 0, r.stderr
    lineas = [l for l in r.stdout.splitlines() if l.count(".") == 2 and len(l) > 100]
    assert lineas, f"no se encontró un token en la salida:\n{r.stdout}"

    from backend_venta import licencias as lic
    validado = lic.licencia_activa(lineas[0].strip())
    assert validado["ok"] and validado["claims"]["plan"] == "owner"


# ---------------------------------------------------------------------------
# Seguridad web: escape explícito en toda inserción al DOM
# ---------------------------------------------------------------------------
def _node_disponible():
    import shutil
    return shutil.which("node")


PAYLOADS_XSS = [
    "<script>alert(1)</script>",
    "</textarea><script>alert(document.cookie)</script>",
    "\"><img src=x onerror=alert(1)>",
    "'><svg onload=alert(1)>",
    "<img src=x onerror=alert(1)>",
    "&lt;ya escapado&gt;",             # no se debe doble-escapar mal
    "comillas \" y ' simples y dobles",
    "<a href=\"javascript:alert(1)\">click</a>",
]


@pytest.mark.skipif(not _node_disponible(), reason="hace falta node para correr el JS real")
def test_la_web_no_inserta_html_dinamico_en_ningun_lado():
    """La forma más segura de escapar datos externos es no interpretarlos.

    Antes, el formulario de demo devolvía la licencia y la pintaba con
    `innerHTML`, así que hacía falta `escaparHtml()` y un test que lo
    bombardeara con payloads de XSS. Cuando la demo dejó de entregarse sola,
    esa inserción desapareció y con ella la función.

    Este control reemplaza a aquel y es más fuerte: en vez de comprobar que la
    única vía de escape funcione, exige que no haya ninguna vía de inserción
    de HTML. Todo lo que venga del backend tiene que ir por `textContent`, que
    no interpreta etiquetas — no hay nada que escapar porque no hay nada que
    se parsee.

    Si alguien vuelve a necesitar `innerHTML`, este test se pone rojo y ahí sí
    corresponde volver a introducir un escape y su batería de payloads.
    """
    import glob

    riesgosas = re.compile(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write")
    hallazgos = []
    for ruta in glob.glob(os.path.join(RAIZ, "web", "assets", "*.js")):
        for n, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if riesgosas.search(linea):
                hallazgos.append(f"{os.path.basename(ruta)}:{n}: {linea.strip()[:90]}")

    assert not hallazgos, (
        "el sitio volvió a insertar HTML dinámico; si es a propósito hay que "
        "reintroducir un escape y probarlo con payloads de XSS:\n  "
        + "\n  ".join(hallazgos))


def test_ningun_innerHTML_con_variable_sin_pasar_por_escaparHtml():
    """Chequeo estático (no hace falta Node): recorre todo el JavaScript
    propio del sitio buscando asignaciones a `.innerHTML` y exige que, si se
    concatena algo que no es un literal de texto fijo, ese algo esté envuelto
    en escaparHtml(...). Es la regla que impide que el próximo desarrollador
    —humano o IA— agregue un innerHTML nuevo y se olvide de escapar.
    """
    def _statement_hasta_punto_y_coma(fuente, inicio):
        """Devuelve fuente[inicio:fin] hasta el ';' que termina la sentencia,
        SIN cortar en un ';' que esté dentro de un string.

        La primera versión de este chequeo usaba `re.finditer(r"...(.+?);")`
        y cortaba en el primer ';' del texto — que acá cae dentro de
        'style="width:100%;margin-top:8px"', mucho antes de llegar al dato
        realmente peligroso. Con eso el chequeo pasaba siempre, incluso
        reintroduciendo a mano el innerHTML sin escapar que motivó este test:
        el checker nunca llegaba a mirar esa parte de la línea. Se lo
        verificó así — reinsertando el bug original y confirmando que este
        test lo detecta — antes de confiar en él.
        """
        i, comilla, escapando = inicio, None, False
        while i < len(fuente):
            c = fuente[i]
            if comilla:
                if escapando:
                    escapando = False
                elif c == "\\":
                    escapando = True
                elif c == comilla:
                    comilla = None
            elif c in ("'", '"', "`"):
                comilla = c
            elif c == ";":
                return fuente[inicio:i]
            i += 1
        return fuente[inicio:i]

    def _dividir_top_level(expresion, separador):
        """Como str.split, pero sin partir dentro de comillas ni paréntesis."""
        partes, actual, profundidad, comilla, escapando = [], "", 0, None, False
        i = 0
        while i < len(expresion):
            c = expresion[i]
            if comilla:
                actual += c
                if escapando:
                    escapando = False
                elif c == "\\":
                    escapando = True
                elif c == comilla:
                    comilla = None
                i += 1
                continue
            if c in ("'", '"', "`"):
                comilla = c
                actual += c
            elif c in "([":
                profundidad += 1
                actual += c
            elif c in ")]":
                profundidad -= 1
                actual += c
            elif profundidad == 0 and expresion[i:i + len(separador)] == separador:
                partes.append(actual)
                actual = ""
                i += len(separador) - 1
            else:
                actual += c
            i += 1
        partes.append(actual)
        return partes

    archivos_propios = []
    for base, dirs, files in os.walk(os.path.join(RAIZ, "web")):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "vendor", "lib")]
        for f in files:
            if f.endswith(".js"):
                archivos_propios.append(os.path.join(base, f))
    assert archivos_propios, "no se encontró JavaScript propio para revisar"

    problemas = []
    for ruta in archivos_propios:
        fuente = open(ruta, encoding="utf-8").read()
        for m in re.finditer(r"\.innerHTML\s*=\s*", fuente):
            expresion = _statement_hasta_punto_y_coma(fuente, m.end())
            for t in _dividir_top_level(expresion, "+"):
                t = t.strip()
                if not t:
                    continue
                es_literal = t.startswith(("'", '"', "`"))
                es_escapado = t.startswith("escaparHtml(")
                # "t.algo" es el objeto TXT de traducciones: un objeto
                # literal fijo en el propio archivo, sin claves dinámicas —
                # no es dato externo, es texto que escribimos nosotros. Todo
                # lo demás (respuestas de fetch, valores de formularios,
                # window.location, etc.) sí tiene que pasar por escaparHtml.
                es_traduccion_confiable = re.fullmatch(r"t\.[A-Za-z_]\w*", t)
                if not es_literal and not es_escapado and not es_traduccion_confiable:
                    problemas.append((os.path.relpath(ruta, RAIZ), t))

    assert not problemas, (
        "innerHTML con datos sin pasar por escaparHtml(): " +
        "; ".join(f"{f}: {t}" for f, t in problemas))


def test_el_lanzador_avisa_en_que_puerto_quedo():
    """El bug que dejaba la ventana de Electron en el splash para siempre.

    Electron elegía el puerto, el lanzador comprobaba y —si justo se había
    ocupado— se mudaba a otro sin avisar. Electron seguía esperando en el
    viejo: splash eterno y 'el servidor no levantó' al minuto.

    Ahora el lanzador escribe el puerto real donde le indiquen.
    """
    import os, tempfile
    L = _lanzador()
    with tempfile.TemporaryDirectory() as d:
        archivo = os.path.join(d, "sub", "puerto.txt")   # subcarpeta inexistente
        os.environ["PLANIA_PUERTO_ARCHIVO"] = archivo
        try:
            L._publicar_puerto("8531")
            assert open(archivo, encoding="utf-8").read() == "8531"
            # y no queda el archivo parcial de la escritura atómica
            assert not os.path.exists(archivo + ".parcial")
        finally:
            os.environ.pop("PLANIA_PUERTO_ARCHIVO", None)


def test_el_puerto_publicado_es_el_que_se_usa_cuando_el_pedido_esta_ocupado():
    """La situación exacta que rompía: alguien pide un puerto que ya está
    ocupado. El lanzador tiene que mudarse Y avisar del nuevo."""
    import os, socketserver, tempfile, threading, http.server

    L = _lanzador()

    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ocupado = srv.server_address[1]
    try:
        assert L._ocupado(ocupado) is True
        with tempfile.TemporaryDirectory() as d:
            archivo = os.path.join(d, "puerto.txt")
            # Se reproduce la decisión de main() sin levantar Streamlit.
            pedido = str(ocupado)
            if L._ocupado(int(pedido)):
                pedido = str(L._puerto_libre())
            os.environ["PLANIA_PUERTO_ARCHIVO"] = archivo
            try:
                L._publicar_puerto(pedido)
            finally:
                os.environ.pop("PLANIA_PUERTO_ARCHIVO", None)

            publicado = int(open(archivo, encoding="utf-8").read())
            assert publicado != ocupado, "publicó el puerto ocupado"
            assert L._ocupado(publicado) is False
    finally:
        srv.shutdown()


def test_electron_no_impone_el_puerto_en_produccion():
    """Si Electron vuelve a fijar el puerto en producción, vuelve el bug: el
    lanzador podría mudarse y la ventana quedaría esperando en el viejo."""
    import os
    main = open(os.path.join(RAIZ, "desktop", "main.js"), encoding="utf-8").read()
    assert "app.isPackaged ? null :" in main, \
        "en producción el puerto lo tiene que elegir el lanzador, no Electron"
    assert "esperarPuerto" in main, "Electron tiene que leer el puerto publicado"
    assert "unlinkSync" in main, \
        "hay que borrar el puerto de la corrida anterior: si no, se espera al " \
        "servidor equivocado"


def test_el_instalador_esta_coherente():
    """Corre el control completo del instalador (packaging/verificar_instalador.py)."""
    import subprocess, sys, os
    r = subprocess.run([sys.executable,
                        os.path.join(RAIZ, "packaging", "verificar_instalador.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_el_panel_del_dueno_no_se_publica_en_el_repo_publico():
    """El panel del dueño no puede terminar en las Releases de este repo.

    El repositorio es público. El panel lleva `plania/negocio.py` (modelo
    financiero, costos, márgenes), `plania/owner.py` y `app/owner.py`
    (facturación y clientes). Un archivo que estuvo en una Release pública,
    estuvo: no hay forma de saber quién lo bajó.

    Hay dos piezas que lo evitan y las dos son fáciles de sacar sin querer:
    la guarda de release.yml, que falla si entre lo que va a publicar aparece
    un `Plania Owner*`, y el destino de release-owner.yml, que tiene que ser
    otro repositorio. Este control las mira a las dos.
    """
    import os
    import yaml

    wf = os.path.join(RAIZ, ".github", "workflows")

    publico = open(os.path.join(wf, "release.yml"), encoding="utf-8").read()
    assert "Plania[ _]Owner" in publico, (
        "release.yml perdió la guarda que corta si se va a publicar el panel "
        "del dueño en este repositorio público")
    assert "no puede publicarse" in publico, (
        "la guarda de release.yml tiene que FALLAR, no sólo avisar")

    owner_txt = open(os.path.join(wf, "release-owner.yml"), encoding="utf-8").read()
    owner = yaml.safe_load(owner_txt)
    # `on:` lo lee PyYAML como True (booleano de YAML 1.1), no como la cadena.
    disparadores = owner.get("on", owner.get(True, {}))
    assert set(disparadores) == {"workflow_dispatch"}, (
        f"release-owner.yml tiene que ser sólo manual, y hoy corre con "
        f"{sorted(disparadores)}: el panel no se construye ni se publica solo")

    destino = disparadores["workflow_dispatch"]["inputs"]["repo_destino"]["default"]
    assert destino != "vieraschiavi/Plania-planificador-log-stico-", (
        "release-owner.yml apunta al repositorio público")
    assert "github.repository" in owner_txt and "es público" in owner_txt, (
        "release-owner.yml tiene que comparar el destino contra el repositorio "
        "actual en tiempo de ejecución: el default correcto no sirve de nada "
        "si alguien escribe otra cosa al lanzarlo a mano")


def test_el_servidor_de_licencias_se_puede_configurar_desde_el_programa():
    """Sin esto, NADIE puede activar una licencia — ni un cliente que pagó.

    `licencia.activar_licencia()` consulta `GET {BACKEND_URL}/licencias/estado`
    y ese valor sale de `PLANIA_BACKEND_URL` o de `config.leer_extra`. Estuvo
    sólo como variable de entorno, y `BACKEND_URL` no estaba en `CLAVES`: la
    pantalla Configuración no lo ofrecía, así que quien instalaba el .exe se
    quedaba con la demo vencida y un token que no había forma de activar.

    Se controla que esté en `CLAVES` —que es lo que dibuja las dos pantallas
    de Configuración, la de Streamlit y la de la ventana— y que no se muestre
    enmascarado, porque una URL escondida detrás de "htt…com" no deja ver lo
    único que hace falta mirar cuando una activación falla: a dónde apunta.
    """
    from plania import config as pconfig
    from plania import api

    assert "BACKEND_URL" in pconfig.CLAVES, (
        "BACKEND_URL no está en CLAVES: la pantalla Configuración no lo "
        "ofrece y no hay forma de activar una licencia desde el programa "
        "instalado")

    assert not api._es_sensible("BACKEND_URL"), (
        "BACKEND_URL se está tratando como secreto; es una URL pública y "
        "esconderla sólo impide verificar a dónde apunta")
    for credencial in ("ANTHROPIC_API_KEY", "MP_ACCESS_TOKEN", "SMTP_PASSWORD"):
        assert api._es_sensible(credencial), f"{credencial} tiene que ocultarse"


def test_el_tablero_del_dueno_lee_la_base_del_backend_desplegado(tmp_path, monkeypatch):
    """Un tablero que muestra cero mientras el negocio vende es peor que no tenerlo.

    `plania/owner.py` abría la base con `sqlite3.connect()` detrás de un
    `os.path.exists(db_path)`. Con el backend desplegado de verdad,
    `PLANIA_USO_DB` es una URL (`postgresql://…`): `os.path.exists` de una URL
    da False, así que devolvía DataFrames vacíos y el dueño veía CERO demos,
    CERO clientes y CERO facturación con el negocio andando.

    Se prueba la rama de URL con `sqlite:///`, que recorre exactamente el
    mismo camino que una URL de Postgres sin necesitar un Postgres levantado.
    """
    import importlib

    ruta = str(tmp_path / "uso.db")
    monkeypatch.setenv("PLANIA_USO_DB", ruta)

    from backend_venta import uso
    importlib.reload(uso)
    for email in ("a@ejemplo.uy", "b@ejemplo.uy", "c@ejemplo.uy"):
        uso.marcar_trial(email)

    import plania.owner as owner
    importlib.reload(owner)

    # Por ruta de archivo: el comportamiento de siempre no se puede haber roto.
    assert len(owner._leer_tabla("trials", ruta)) == 3

    # Por URL de conexión: lo que hace falta con el backend desplegado.
    assert not os.path.exists(f"sqlite:///{ruta}"), (
        "si esto existiera como archivo, la prueba no estaría comprobando nada")
    assert len(owner._leer_tabla("trials", f"sqlite:///{ruta}")) == 3, (
        "el tablero no lee cuando PLANIA_USO_DB es una URL de conexión")

    # Una base inalcanzable muestra vacío, no rompe la pantalla del dueño.
    assert owner._leer_tabla(
        "trials", "postgresql://nadie:nada@127.0.0.1:1/nada").empty


def test_ningun_plan_pago_le_saca_algo_que_la_demo_ya_daba():
    """Pagar nunca puede darte menos que probar gratis.

    La demo traía `rutas` y Starter no: quien probaba 7 días y compraba el plan
    más barato PERDÍA una función que ya estaba usando. Un downgrade en el
    momento exacto de cobrar es la forma más cara de arrancar con un cliente —
    el reclamo llega el primer día y el reembolso también.

    Se controla como invariante y no como caso puntual de `rutas`: cualquier
    función que se agregue mañana a la demo tiene que estar en todos los planes
    pagos, o el mismo problema vuelve con otro nombre.
    """
    from backend_venta import licencias

    demo = set(licencias.PLANES["trial"]["features"])
    pagos = {p: d for p, d in licencias.PLANES.items()
             if p != "trial" and d.get("dias")}

    for plan, datos in pagos.items():
        faltantes = demo - set(datos["features"])
        assert not faltantes, (
            f"el plan '{plan}' no tiene {sorted(faltantes)}, que la demo SÍ da: "
            f"un cliente que prueba y compra pierde esa función justo al pagar")


def test_lo_que_dice_cada_plan_es_lo_que_ese_plan_hace():
    """Los textos de venta no pueden prometer lo que el plan no habilita.

    Hay tres lugares que describen los planes —la pantalla de Streamlit, la de
    la ventana y el sitio— y las funciones reales viven en un cuarto
    (`backend_venta/licencias.py`). Cuando cambió qué incluye Starter, el sitio
    siguió vendiendo las rutas como el diferencial de Pro: texto y producto
    dejaron de coincidir sin que nada se pusiera rojo.
    """
    import json
    import os

    from backend_venta import licencias

    starter = set(licencias.PLANES["starter"]["features"])
    pro = set(licencias.PLANES["pro"]["features"])

    # Si Starter ya trae rutas, ningún texto puede seguir vendiéndolas como lo
    # que distingue a Pro.
    if "rutas" in starter:
        for idioma in ("es", "en", "pt"):
            ruta = os.path.join(RAIZ, "sitio", "i18n", f"{idioma}.json")
            with open(ruta, encoding="utf-8") as f:
                textos = json.load(f)
            bullets_pro = " ".join(textos.get(f"p2_{n}", "") for n in (1, 2, 3, 4)).lower()
            for palabra in ("rutas de reparto", "delivery routes", "rotas de entrega"):
                assert palabra not in bullets_pro, (
                    f"{idioma}.json vende '{palabra}' como diferencial de Pro, "
                    f"pero Starter ya las incluye")

        for archivo in ("app/app.py", "plania/api.py"):
            with open(os.path.join(RAIZ, archivo), encoding="utf-8") as f:
                cuerpo = f.read()
            assert "Copiloto + ERP + exportes ·" not in cuerpo, (
                f"{archivo} describe Starter sin rutas, pero el plan las tiene")

    # Y lo que sí distingue a Pro tiene que seguir siendo cierto.
    assert "excedente" in pro and "excedente" not in starter, (
        "si Starter y Pro habilitan lo mismo, no queda motivo para pagar Pro")


def test_la_demo_ya_no_se_entrega_sola_a_quien_la_pida(tmp_path, monkeypatch):
    """La demo dejó de ser autoservicio, y esto lo comprueba de verdad.

    Antes, `POST /licencias/trial` con un email cualquiera devolvía al instante
    una licencia de 7 días con TODO habilitado, sin credenciales de por medio.
    Eso le entregaba el producto entero a cualquiera que pasara —incluido un
    competidor— sin dejar rastro de quién era.

    Ahora ese endpoint exige el token de administrador: la demo la habilita el
    dueño, después de atender el pedido.
    """
    from fastapi.testclient import TestClient

    from backend_venta.app import app

    # Sólo el token de admin, que `_admin_token()` lee en cada llamada. No se
    # recargan módulos: `uso.DB_PATH` se fija al importar, así que un reload
    # acá le deja la base de prueba a todos los tests que corren después.
    monkeypatch.setenv("PLANIA_BACKEND_ADMIN_TOKEN", "token-de-prueba")

    c = TestClient(app, client=("203.0.113.240", 52000))
    email_nuevo = f"prospecto-{uuid.uuid4().hex[:10]}@empresa.uy"

    # Sin credenciales: no se lleva nada.
    r = c.post("/licencias/trial", json={"email": "curioso@competencia.uy"})
    assert r.status_code in (401, 403, 422), (
        f"la demo sigue siendo autoservicio: devolvió {r.status_code}")
    assert "licencia" not in r.json(), "entregó una licencia sin credenciales"

    # Con el token del dueño: sí, porque es él quien decide a quién mostrarle.
    r = c.post("/licencias/trial", json={"email": email_nuevo},
               headers={"Authorization": "Bearer token-de-prueba"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "trial"


def test_el_pedido_de_demo_queda_registrado_con_quien_lo_pidio():
    """El formulario tiene que dejar rastro, que es medio motivo de existir.

    Guardar sólo el email no alcanza para decidir a quién le mostrás el
    producto ni para llamarlo: por eso nombre, empresa y país son obligatorios
    y el endpoint los rechaza si faltan.
    """
    from fastapi.testclient import TestClient

    from backend_venta import uso
    from backend_venta.app import app

    c = TestClient(app, client=("203.0.113.241", 52100))
    # Email único: la suite comparte la base, así que un valor fijo haría que
    # el test dependa de si ya corrió antes.
    email = f"juan-{uuid.uuid4().hex[:10]}@distribuidora.uy"
    completo = {"email": email, "nombre": "Juan Pérez",
                "empresa": "Distribuidora del Este", "pais": "Uruguay",
                "mensaje": "Tenemos Zureo y 12 camiones."}

    r = c.post("/demo/solicitar", json=completo)
    assert r.status_code == 200, r.text
    # Lo que NO tiene que pasar: que el formulario entregue el producto.
    assert "licencia" not in r.json(), "el formulario entregó una licencia"

    guardadas = {s["email"]: s for s in uso.solicitudes_demo()}
    assert email in guardadas, "el pedido no quedó registrado"
    fila = guardadas[email]
    assert fila["nombre"] == "Juan Pérez"
    assert fila["empresa"] == "Distribuidora del Este"
    assert fila["pais"] == "Uruguay"

    # Insistir no ensucia la lista con la misma persona repetida.
    c.post("/demo/solicitar", json=completo)
    repetidos = [s for s in uso.solicitudes_demo() if s["email"] == email]
    assert len(repetidos) == 1, "el mismo interesado quedó cargado dos veces"

    # Y un pedido sin datos no entra: un email suelto no sirve para nada.
    for falta in ("nombre", "empresa", "pais"):
        incompleto = dict(completo, email=f"otro-{falta}-{uuid.uuid4().hex[:8]}@x.uy")
        incompleto[falta] = ""
        r = c.post("/demo/solicitar", json=incompleto)
        assert r.status_code == 400, f"aceptó un pedido sin {falta}"


def test_el_producto_no_usa_emojis_decorativos():
    """Un emoji colgado de cada título delata que lo escribió un modelo.

    Lo que se vende es software de gestión para un distribuidor: la cara del
    producto —las pantallas, el README, los exportes que el cliente le muestra
    a su contador— tiene que leerse como la de un programa, no como la de un
    chat. El README llegó a tener un emoji por fila en la tabla de funciones.

    Ojo con el alcance: NO entra el sitio de venta, que usa ✓ y ✗ en la tabla
    comparativa. Esos son signos tipográficos con significado (y con clase CSS
    propia, .si/.no), no decoración, y sacarlos empeoraría la tabla.
    """
    import os, re
    # Pictogramas y símbolos misceláneos. El rango 2600-27BF incluye ✓/✗, por
    # eso mismo el sitio queda fuera de lo que se recorre.
    emoji = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
    superficies = [
        os.path.join(RAIZ, "README.md"),
        os.path.join(RAIZ, "app"),
        os.path.join(RAIZ, "plania"),
        os.path.join(RAIZ, "desktop", "renderer"),
    ]

    encontrados = []
    for superficie in superficies:
        archivos = [superficie] if os.path.isfile(superficie) else [
            os.path.join(raiz, f)
            for raiz, _dirs, fs in os.walk(superficie) for f in fs
            if f.endswith((".py", ".js", ".html", ".css", ".md"))
        ]
        for ruta in archivos:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                for n, linea in enumerate(f, 1):
                    for m in emoji.finditer(linea):
                        rel = os.path.relpath(ruta, RAIZ)
                        encontrados.append(f"{rel}:{n}: {m.group()}")

    assert not encontrados, (
        "hay emojis decorativos en la cara del producto:\n  "
        + "\n  ".join(encontrados))


def test_el_script_del_instalador_compila():
    """desktop/build/installer.nsh tiene que COMPILAR, no sólo parecer correcto.

    Es un script NSIS que nadie ejecuta hasta que alguien baja el instalador:
    un error de sintaxis o un macro mal cerrado no lo agarra ningún control de
    texto, y en el runner de Windows aparece recién después de los veinte
    minutos de PyInstaller. `makensis` compila igual en Linux, así que se
    compila acá contra un envoltorio mínimo que le pasa las constantes que
    normalmente pone electron-builder.
    """
    import shutil, subprocess, os, tempfile
    if shutil.which("makensis") is None:
        import pytest
        pytest.skip("makensis no está instalado en este entorno")

    incluido = os.path.join(RAIZ, "desktop", "installer.nsh")
    envoltorio = f'''
OutFile "prueba.exe"
InstallDir "$PROGRAMFILES64\\Plania"
!define APP_FILENAME "Plania"
!define INSTALL_REGISTRY_KEY "Software\\PlaniaPrueba"
!include "{incluido}"
Section "x"
SectionEnd
Function .onInit
  !insertmacro customInit
FunctionEnd
'''
    with tempfile.TemporaryDirectory() as tmp:
        guion = os.path.join(tmp, "prueba.nsi")
        with open(guion, "w", encoding="utf-8") as f:
            f.write(envoltorio)
        r = subprocess.run(["makensis", guion], capture_output=True, text=True,
                           cwd=tmp)
        assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# Todo en el disco elegido: config/licencia y logs junto al .exe, no en C:
# ---------------------------------------------------------------------------
def test_config_dir_usa_la_carpeta_junto_al_exe_si_esta_empaquetado(tmp_path, monkeypatch):
    """El pedido explícito: instalar en D: tiene que dejar TODO en D:, no sólo
    el programa. Antes, la licencia y la config de plania.config quedaban
    siempre en ~/.plania —el perfil de Windows, típicamente C:— sin importar
    en qué disco se hubiera instalado Plania.
    """
    import importlib
    import plania.config as pconfig

    falso_exe = tmp_path / "D_simulado" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")

    monkeypatch.delenv("PLANIA_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(falso_exe))
    try:
        importlib.reload(pconfig)
        esperado = str(falso_exe.parent / "datos")
        assert pconfig.CONFIG_DIR == esperado
        assert os.path.isdir(esperado), "tiene que dejar la carpeta creada"
    finally:
        importlib.reload(pconfig)   # vuelve al PLANIA_CONFIG_DIR real de los tests


def test_config_dir_no_cambia_fuera_del_exe_empaquetado(monkeypatch):
    """En desarrollo (sys.frozen no existe) el comportamiento no cambia: nadie
    quiere que correr `streamlit run app/app.py` desde el repo se ponga a
    crear carpetas raras al lado del intérprete de Python."""
    import importlib
    import plania.config as pconfig

    monkeypatch.delenv("PLANIA_CONFIG_DIR", raising=False)
    try:
        importlib.reload(pconfig)
        assert pconfig.CONFIG_DIR == os.path.expanduser("~/.plania")
    finally:
        importlib.reload(pconfig)


def test_variable_de_entorno_explicita_sigue_ganando(tmp_path, monkeypatch):
    """PLANIA_CONFIG_DIR es una elección explícita (Docker, tests, soporte
    técnico): tiene que ganarle incluso a la detección automática."""
    import importlib
    import plania.config as pconfig

    falso_exe = tmp_path / "app" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")
    elegida = str(tmp_path / "donde_yo_diga")

    monkeypatch.setenv("PLANIA_CONFIG_DIR", elegida)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(falso_exe))
    try:
        importlib.reload(pconfig)
        assert pconfig.CONFIG_DIR == elegida
    finally:
        importlib.reload(pconfig)


def test_licencia_vieja_se_migra_a_la_carpeta_nueva(tmp_path, monkeypatch):
    """Quien ya tenía Plania instalado (versión anterior a este cambio) con la
    licencia activada en ~/.plania no puede perderla al actualizar: se migra
    una sola vez a la carpeta nueva, sin pisar datos nuevos."""
    import importlib
    import plania.config as pconfig

    home_viejo = tmp_path / "home"
    home_viejo.mkdir()
    (home_viejo / ".plania").mkdir()
    (home_viejo / ".plania" / "config.enc").write_bytes(b"licencia-vieja-cifrada")

    falso_exe = tmp_path / "D_simulado" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")

    monkeypatch.delenv("PLANIA_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(falso_exe))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(home_viejo)))
    try:
        importlib.reload(pconfig)
        migrado = os.path.join(pconfig.CONFIG_DIR, "config.enc")
        assert os.path.exists(migrado)
        assert open(migrado, "rb").read() == b"licencia-vieja-cifrada"
        # y el original sigue existiendo: se copia, no se mueve
        assert (home_viejo / ".plania" / "config.enc").exists()
    finally:
        importlib.reload(pconfig)


def test_migracion_no_pisa_datos_que_ya_existen_en_la_carpeta_nueva(tmp_path, monkeypatch):
    """Si la carpeta nueva ya tiene algo (una activación posterior a la
    migración, por ejemplo), no se sobreescribe con lo viejo."""
    import importlib
    import plania.config as pconfig

    home_viejo = tmp_path / "home"
    (home_viejo / ".plania").mkdir(parents=True)
    (home_viejo / ".plania" / "config.enc").write_bytes(b"viejo")

    falso_exe = tmp_path / "D_simulado" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")
    (falso_exe.parent / "datos").mkdir()
    (falso_exe.parent / "datos" / "config.enc").write_bytes(b"nuevo")

    monkeypatch.delenv("PLANIA_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(falso_exe))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(home_viejo)))
    try:
        importlib.reload(pconfig)
        assert open(os.path.join(pconfig.CONFIG_DIR, "config.enc"), "rb").read() == b"nuevo"
    finally:
        importlib.reload(pconfig)


def test_logs_del_lanzador_van_junto_al_exe_si_esta_empaquetado(tmp_path, monkeypatch):
    L = _lanzador()
    falso_exe = tmp_path / "D_simulado" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")

    monkeypatch.setattr(L.sys, "frozen", True, raising=False)
    monkeypatch.setattr(L.sys, "executable", str(falso_exe))
    try:
        carpeta = L._carpeta_logs()
        assert carpeta == str(falso_exe.parent / "datos" / "logs")
        assert os.path.isdir(carpeta)
    finally:
        monkeypatch.delattr(L.sys, "frozen", raising=False)


def test_logs_caen_a_localappdata_si_la_carpeta_junto_al_exe_no_es_escribible(
        tmp_path, monkeypatch):
    """Instalado en Archivos de programa y corriendo sin permiso de escritura
    ahí: no puede fallar en silencio ni perder el log, tiene que caer a
    LOCALAPPDATA como antes."""
    L = _lanzador()
    falso_exe = tmp_path / "Program Files" / "Plania" / "Plania.exe"
    falso_exe.parent.mkdir(parents=True)
    falso_exe.write_text("")

    monkeypatch.setattr(L.sys, "frozen", True, raising=False)
    monkeypatch.setattr(L.sys, "executable", str(falso_exe))
    monkeypatch.setattr(L, "_escribible", lambda carpeta: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData_simulado"))
    try:
        carpeta = L._carpeta_logs()
        assert carpeta == str(tmp_path / "AppData_simulado" / "Plania" / "logs")
    finally:
        monkeypatch.delattr(L.sys, "frozen", raising=False)


def test_el_instalador_no_borra_la_carpeta_de_datos_al_desinstalar():
    """Regresión directa del pedido: la licencia tiene que sobrevivir a un
    desinstalar + reinstalar en la misma carpeta."""
    import os
    iss = open(os.path.join(RAIZ, "packaging", "instalador.iss"),
              encoding="utf-8").read()
    seccion = iss.split("[UninstallDelete]")[1].split("[Code]")[0]
    # Sólo las líneas de código (Type:/Name:), no los comentarios que
    # explican por qué "datos" no está acá — esos sí la nombran a propósito.
    codigo = "\n".join(l for l in seccion.splitlines()
                       if l.strip() and not l.strip().startswith(";"))
    assert r"{app}\datos" not in codigo, \
        "[UninstallDelete] no puede borrar la carpeta donde vive la licencia"


# ---------------------------------------------------------------------------
# Imágenes del asistente de instalación
# ---------------------------------------------------------------------------
def test_imagenes_del_asistente_son_reproducibles_y_de_la_misma_marca():
    """Las BMP del panel de Inno Setup salen de un script, no de un archivo
    subido a mano: correrlo dos veces tiene que dar el mismo resultado, y las
    que están commiteadas tienen que ser de la MISMA marca que el ícono de la
    app en este momento.

    Lo segundo es lo que importa y es lo que falló de verdad: al cambiar la
    marca a MV, el ícono quedó actualizado y las imágenes del instalador
    siguieron mostrando el logo anterior, porque son archivos aparte que hay
    que regenerar. Un instalador con el logo viejo y una app con el nuevo se ve
    como dos productos distintos, y no lo nota nadie hasta que un cliente lo
    instala.

    No se comparan bytes contra una corrida nueva: el rango de Pillow que
    admite requirements.txt es amplio y dos versiones pueden codificar el BMP
    o interpolar el resize distinto sin que la marca haya cambiado. Se
    comparan los colores, que es lo que se mira con los ojos.
    """
    import importlib
    import io
    import os
    import sys

    from PIL import Image

    sys.path.insert(0, os.path.join(RAIZ, "packaging"))
    gen = importlib.import_module("generar_imagenes_instalador")

    # El color que el generador sacaría HOY del ícono de la app. Comparar el
    # BMP commiteado contra esto es lo que detecta que la marca cambió y las
    # imágenes del instalador quedaron sin regenerar: seguirían teniendo el
    # navy anterior.
    navy_actual = gen._navy()

    for nombre in ("plania_wizard.bmp", "plania_wizard_small.bmp"):
        ruta = os.path.join(RAIZ, "assets", "brand", nombre)
        assert os.path.exists(ruta), f"falta {nombre} — correr generar_imagenes_instalador.py"
        with Image.open(ruta) as bmp:
            rgb = bmp.convert("RGB")
            # La esquina: en las dos imágenes el ícono va centrado y con
            # margen, así que ahí siempre hay fondo del panel. Arriba al
            # centro no sirve — en el logo chico cae adentro del ícono.
            fondo_bmp = rgb.getpixel((2, 2))
            colores = {c for _n, c in rgb.getcolors(maxcolors=100000)}

        assert fondo_bmp == navy_actual, (
            f"{nombre} tiene fondo {fondo_bmp} y el ícono de la app da hoy "
            f"{navy_actual}: son de marcas distintas. Corré "
            f"python3 packaging/generar_imagenes_instalador.py")

        # Y que el ícono esté REALMENTE adentro, no sólo el fondo del color
        # correcto: se busca el verde de la V, que no aparece en ningún otro
        # elemento del panel.
        verde = [c for c in colores
                 if c[1] > 110 and c[1] > c[0] + 40 and c[1] > c[2] + 40]
        assert verde, (
            f"{nombre} no contiene el verde de la marca: la imagen tiene el "
            f"fondo bien pero el logo no está adentro")

    def _bytes(img):
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        return buf.getvalue()

    assert _bytes(gen.panel_grande()) == _bytes(gen.panel_grande())
    assert _bytes(gen.logo_chico()) == _bytes(gen.logo_chico())

    for ruta, tam in ((os.path.join(RAIZ, "assets", "brand", "plania_wizard.bmp"), gen.PANEL),
                      (os.path.join(RAIZ, "assets", "brand", "plania_wizard_small.bmp"), gen.LOGO_CHICO)):
        assert os.path.exists(ruta), f"falta {ruta} — correr generar_imagenes_instalador.py"
        with Image.open(ruta) as im:
            assert im.size == tam
            assert im.format == "BMP"


def test_instalador_referencia_las_imagenes_del_asistente():
    iss = open(os.path.join(RAIZ, "packaging", "instalador.iss"), encoding="utf-8").read()
    assert "WizardImageFile=" in iss
    assert "WizardSmallImageFile=" in iss


# ---------------------------------------------------------------------------
# El puerto no puede hacer fallar el arranque
# ---------------------------------------------------------------------------
def test_reservar_devuelve_none_si_el_puerto_esta_tomado():
    """La reserva cierra la ventana entre 'comprobé que estaba libre' y
    'Streamlit lo tomó'. Si no distinguiera ocupado de libre, no serviría."""
    import socket

    L = _lanzador()
    ocupado = socket.socket()
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen(1)
    puerto = ocupado.getsockname()[1]
    try:
        assert L._reservar(puerto) is None, "dio por libre un puerto tomado"
    finally:
        ocupado.close()

    reserva = L._reservar(puerto)
    assert reserva is not None, "no pudo reservar un puerto que quedó libre"
    # Mientras la tenemos, nadie más puede: eso es lo que evita la carrera.
    assert L._reservar(puerto) is None
    reserva.close()


def test_si_otro_programa_gana_la_carrera_se_prueba_el_siguiente_puerto():
    """El caso que el usuario pidió que no diera error: entre que se suelta la
    reserva y Streamlit hace su bind, otro programa se lleva el puerto.
    Streamlit no reintenta —muere con "Port N is not available" y código 1—,
    así que el lanzador tiene que mudarse solo.

    La carrera real dura microsegundos y no se puede provocar por tiempo, así
    que se inyecta: el primer intento falla como falla Streamlit, y el puerto
    queda ocupado de verdad para que el lanzador lo verifique.
    """
    import socket

    import streamlit.web as sweb
    from streamlit.web import bootstrap as _bs_real   # fuerza la carga del submodulo

    L = _lanzador()
    intentos = []

    intruso = socket.socket()
    intruso.bind(("127.0.0.1", 0))
    intruso.listen(1)
    puerto_robado = intruso.getsockname()[1]

    def _run(*a, **k):
        if intentos[-1] == puerto_robado:
            raise SystemExit(1)          # así muere Streamlit con el puerto tomado
        return None                      # arrancó bien

    original_reservar = L._reservar

    def _reservar(puerto):
        # El intruso tiene el puerto tomado, así que hay que soltarlo un
        # instante para que el lanzador pueda reservarlo — que es exactamente
        # la ventana que se está simulando.
        if puerto == puerto_robado:
            intruso.close()
        s = original_reservar(puerto)
        if s is not None:
            intentos.append(s.getsockname()[1])
        return s

    original_bootstrap = sweb.bootstrap
    original_ocupado = L._ocupado
    L._reservar = _reservar
    # Tras el fallo, el puerto tiene que verse ocupado para que el lanzador
    # sepa que fue la carrera y no otro error.
    L._ocupado = lambda p: p == puerto_robado
    sweb.bootstrap = type(sweb.bootstrap)("bootstrap")
    sweb.bootstrap.run = _run
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    try:
        L._servir("/tmp/no-importa.py", puerto_robado, electron=True)
    finally:
        L._reservar = original_reservar
        L._ocupado = original_ocupado
        sweb.bootstrap = original_bootstrap
        try:
            intruso.close()
        except Exception:
            pass

    assert len(intentos) >= 2, f"no reintentó en otro puerto: {intentos}"
    assert intentos[0] == puerto_robado
    assert intentos[-1] != puerto_robado, "se quedó en el puerto que perdió"


def test_un_error_que_no_es_de_puerto_no_se_reintenta_en_bucle():
    """Si Streamlit falla por otra cosa, reintentar en otro puerto solo
    esconde el error real y lo repite cinco veces. Tiene que propagarse."""
    import streamlit.web as sweb
    from streamlit.web import bootstrap as _bs_real   # fuerza la carga del submodulo

    L = _lanzador()
    llamadas = []

    def _run(*a, **k):
        llamadas.append(1)
        raise SystemExit(1)

    original_bootstrap = sweb.bootstrap
    original_ocupado = L._ocupado
    L._ocupado = lambda p: False          # el puerto quedó libre => no fue la carrera
    sweb.bootstrap = type(sweb.bootstrap)("bootstrap")
    sweb.bootstrap.run = _run
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    try:
        with pytest.raises(SystemExit):
            L._servir("/tmp/no-importa.py", 0, electron=True)
    finally:
        L._ocupado = original_ocupado
        sweb.bootstrap = original_bootstrap

    assert len(llamadas) == 1, f"reintentó un error que no era de puerto ({len(llamadas)} veces)"


def test_el_bat_se_limpia_si_falla_la_instalacion():
    """Lo que le pasó al usuario: pip murió sin espacio en disco DESPUÉS de
    crear .venv. Sin borrar ese entorno a medias, el próximo doble clic ve
    que .venv existe, se saltea la instalación y falla más adelante con un
    error distinto y más confuso."""
    bat = open(os.path.join(RAIZ, "INICIAR_PLANIA.bat"), encoding="utf-8",
               errors="replace").read()
    ejecutables = "\n".join(l for l in bat.splitlines()
                            if not l.strip().lower().startswith("rem"))
    assert "rd /s /q .venv" in ejecutables, \
        "un entorno a medio instalar tiene que borrarse para que el reintento sirva"
    assert "--no-cache-dir" in ejecutables, \
        "sin esto pip guarda otra copia de cada paquete y necesita casi el doble de disco"
    assert "No space left on device" in bat, \
        "el .bat tiene que reconocer el error de disco lleno y explicarlo"
    # La consola de Windows rompe los acentos segun la codepage.
    assert not any(c in bat for c in "áéíóúñÁÉÍÓÚÑ"), \
        "el .bat no puede tener acentos: se ven mal en la consola de Windows"


# ---------------------------------------------------------------------------
# Que el que paga reciba su licencia, y una sola
# ---------------------------------------------------------------------------
def test_un_pago_no_puede_emitir_dos_licencias(tmp_path, monkeypatch):
    """MercadoPago reenvía la notificación hasta recibir 200, y además le da
    el payment_id al comprador en la URL de retorno. Sin idempotencia,
    repetir ese POST fabricaba licencias pro ilimitadas con un curl."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MP_ACCESS_TOKEN", "token-de-prueba")
    from backend_venta.app import app

    class _Aprobado:
        ok = True

        @staticmethod
        def json():
            return {"status": "approved",
                    "metadata": {"plan": "pro", "email": "cliente@pago.uy"}}

    c = TestClient(app)
    with patch("backend_venta.app.requests.get", return_value=_Aprobado):
        r = [c.post("/webhooks/mercadopago",
                    json={"type": "payment", "data": {"id": "777"}}).json()
             for _ in range(3)]

    assert len({x["licencia"] for x in r}) == 1, "un pago emitió más de una licencia"
    assert len({x["token_descarga"] for x in r}) == 1, "emitió más de un token de descarga"
    assert r[1].get("repetido") is True


def test_el_comprador_puede_recuperar_la_licencia_que_pago(tmp_path, monkeypatch):
    """El webhook le responde a MercadoPago, no al comprador: la licencia
    viajaba en un cuerpo que MP descarta, así que el cliente pagaba y no
    recibía nada. Tiene que poder pedirla con su payment_id."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MP_ACCESS_TOKEN", "token-de-prueba")
    from backend_venta.app import app
    from backend_venta import licencias

    class _Aprobado:
        ok = True

        @staticmethod
        def json():
            return {"status": "approved",
                    "metadata": {"plan": "starter", "email": "compro@uy"}}

    class _Pendiente:
        ok = True

        @staticmethod
        def json():
            return {"status": "pending", "metadata": {}}

    c = TestClient(app)
    # Llega primero el comprador, antes que el webhook: igual la recibe. Pide
    # con su email, que es lo que prueba que la compra es suya — el payment_id
    # solo viaja a la vista en la URL y se puede enumerar.
    suyo = {"email": "compro@uy"}
    with patch("backend_venta.app.requests.get", return_value=_Aprobado):
        g = c.get("/licencias/por-pago/888", params=suyo).json()
        assert licencias.validar_licencia(g["licencia"])["plan"] == "starter"
        # Y el webhook posterior no emite otra distinta.
        w = c.post("/webhooks/mercadopago",
                   json={"type": "payment", "data": {"id": "888"}}).json()
        assert w["licencia"] == g["licencia"]

    # Saber un payment_id no alcanza: tiene que estar aprobado de verdad.
    with patch("backend_venta.app.requests.get", return_value=_Pendiente):
        assert c.get("/licencias/por-pago/000", params=suyo).status_code == 404


def test_activar_una_licencia_no_rompe_el_arranque(tmp_path, monkeypatch):
    """El bug más caro que tuvo el producto: activar una licencia paga
    guardaba las claims (un dict) en el mismo almacén que las credenciales, y
    al siguiente arranque `config.aplicar()` moría con TypeError. O sea: todo
    cliente que pagaba dejaba de poder abrir la aplicación."""
    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    import importlib

    from plania import config as pconfig
    importlib.reload(pconfig)

    try:
        pconfig.guardar_extra("LICENCIA_CLAIMS", {"cliente": "x@y.uy", "plan": "pro"})
        pconfig.guardar_extra("ANTHROPIC_API_KEY", "sk-ant-de-prueba")

        pconfig.aplicar()      # esto es lo que corre app/app.py al arrancar

        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-de-prueba", \
            "dejó de exportar las credenciales que sí van al entorno"
        assert "LICENCIA_CLAIMS" not in os.environ, \
            "las claims no son una variable de entorno"
    finally:
        # `CONFIG_DIR` se resuelve al importar el módulo, así que recargarlo
        # con la carpeta temporal puesta lo deja apuntando ahí para el resto
        # de la sesión: todo test posterior que lea configuración leía de una
        # carpeta de otro test. Se veía como un fallo ajeno y difícil de
        # explicar — el gateway devolvía 502 en vez de 503 porque "encontraba"
        # una ANTHROPIC_API_KEY que este test había guardado.
        #
        # `monkeypatch` deshace la variable recién al terminar la función, así
        # que hay que deshacerla a mano antes de recargar.
        monkeypatch.undo()
        importlib.reload(pconfig)
        # `aplicar()` exporta al entorno, y eso monkeypatch no lo revierte.
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Catálogo: entender la base de CUALQUIER empresa, no solo las conocidas
# ---------------------------------------------------------------------------
def _base_con_nombres_inventados(tmp_path):
    """Una base como la de una empresa real: nombres que no están en ninguna
    lista, una tabla trampa vacía que sí tiene el nombre esperado, y ninguna
    clave foránea declarada (lo normal en un ERP viejo)."""
    import sqlite3
    ruta = tmp_path / "rara.db"
    c = sqlite3.connect(ruta)
    c.execute("""CREATE TABLE TBL_ITEMS_01 (sku TEXT PRIMARY KEY, detalle TEXT,
                 familia TEXT, marca TEXT, costo_neto REAL, pvp REAL,
                 existencia INTEGER)""")
    c.execute("""CREATE TABLE MAESTRO_CTAS (nro_cta TEXT PRIMARY KEY,
                 nombre_fantasia TEXT, actividad TEXT, zona_reparto TEXT)""")
    c.execute("""CREATE TABLE MOV_FACT_DET (doc TEXT, fec TEXT, nro_cta TEXT,
                 sku TEXT, cant REAL, importe_unit REAL, costo_neto REAL)""")
    # Trampa: se llama "articulos" pero quedó vacía de una migración vieja.
    c.execute("""CREATE TABLE articulos (cod_articulo TEXT, descripcion TEXT,
                 costo_unitario REAL, precio_venta REAL, stock_actual INTEGER)""")
    for i in range(40):
        c.execute("INSERT INTO TBL_ITEMS_01 VALUES (?,?,?,?,?,?,?)",
                  (f"SKU{i:03d}", f"Producto {i}", "Bebidas", "M1", 10.0, 20.0, 5))
        c.execute("INSERT INTO MAESTRO_CTAS VALUES (?,?,?,?)",
                  (f"CTA{i:03d}", f"Comercio {i}", "Almacen", "Centro"))
        c.execute("INSERT INTO MOV_FACT_DET VALUES (?,?,?,?,?,?,?)",
                  (f"A{i}", "2026-03-01", f"CTA{i:03d}", f"SKU{i:03d}", 3, 20.0, 10.0))
    c.commit()
    c.close()
    return ruta


def test_leer_sql_rechaza_nombres_de_tabla_que_no_son_identificadores(tmp_path):
    """'Conectar ERP' > 'Elegir tablas manualmente' es un `st.text_input` libre
    (app/app.py): el dueño de la base tipea un nombre de tabla, o pega una
    consulta completa si el autodescubrimiento no la encuentra. Lo segundo es
    a propósito — pero lo primero se interpolaba tal cual en
    `f"SELECT * FROM {q}"` sin comprobar que fuera un nombre de tabla y no
    cualquier otra cosa.

    Hoy el único que llena ese campo es el dueño de su propia conexión, así
    que el riesgo inmediato es bajo. Pero es la clase de atajo que se vuelve
    peligroso en cuanto ese valor deje de venir de un tipeo manual —una
    integración, una config compartida entre instalaciones— y nadie se
    acuerde de revisarlo. El modo "pegá tu consulta" sigue igual: eso ya
    ejecuta lo que el usuario escriba, por diseño.
    """
    from plania import conectores

    ruta = str(tmp_path / "t.db")
    import sqlite3
    c = sqlite3.connect(ruta)
    c.execute("CREATE TABLE productos (id INTEGER, nombre TEXT)")
    c.execute("INSERT INTO productos VALUES (1, 'x')")
    c.commit()
    c.close()
    eng = conectores.conectar_sql(f"sqlite:///{ruta}")

    # Nombres de tabla legítimos: pasan.
    assert len(conectores.leer_sql(eng, "productos")) == 1
    assert len(conectores.leer_sql(eng, '"productos"')) == 1

    # Consulta completa: sigue funcionando igual que siempre.
    assert len(conectores.leer_sql(eng, "SELECT * FROM productos")) == 1

    # Lo que NO es un nombre de tabla ni una consulta que empiece con SELECT:
    # rechazado antes de tocar la base.
    for malicioso in (
        "productos; DROP TABLE productos; --",
        "productos WHERE 1=1 UNION SELECT sql FROM sqlite_master",
        "productos -- comentario",
        # La primera versión de este arreglo permitía espacios sueltos en el
        # identificador ("varios ERP usan nombres con espacios"), y con eso
        # ESTA línea pasaba la validación entera y leía sqlite_master de
        # verdad — se comprobó ejecutándola contra una base real antes de
        # corregir. Ninguna letra ni espacio es "especial", así que una
        # inyección armada sólo con palabras clave (sin `;`, sin `=`, sin
        # `--`) esquivaba limpio cualquier filtro que sólo mire símbolos.
        # El caso de arriba con "WHERE 1=1" NO prueba esto: lo rechaza el
        # `=`, no el UNION. Este caso rechaza por el espacio sin delimitar.
        "productos union select sql from sqlite_master",
        "productos join sqlite_master",
        "productos order by 1",
        # Delimitador que cierra temprano y deja una cola: el cierre de
        # comillas/corchete no puede ser el fin de la validación si sobra
        # texto después.
        '"productos" union select 1',
        "[productos] union select 1",
    ):
        with pytest.raises(ValueError):
            conectores.leer_sql(eng, malicioso)

    # La tabla sigue intacta: el intento de DROP nunca llegó a ejecutarse.
    assert len(conectores.leer_sql(eng, "productos")) == 1


def test_encuentra_las_tablas_aunque_se_llamen_cualquier_cosa(tmp_path):
    """El caso que antes fallaba: la empresa no llama a sus tablas como el
    ERP del manual. Si Plania solo busca por nombre, no encuentra nada y el
    cliente ve 'no pude mapear columnas obligatorias' sin saber qué hacer."""
    from plania import catalogo as cm
    from plania import conectores

    ruta = _base_con_nombres_inventados(tmp_path)
    eng = conectores.conectar_sql(f"sqlite:///{ruta}")
    cat = cm.extraer(eng)
    elegidas = cm.elegir_tablas(cat, conectores.SINONIMOS,
                                conectores.TABLAS_CANDIDATAS, conectores.OBLIGATORIAS)
    elegidas = cm.completar_por_estructura(cat, elegidas, conectores.SINONIMOS,
                                           conectores.OBLIGATORIAS)

    assert elegidas["productos"]["tabla"] == "TBL_ITEMS_01"
    assert elegidas["ventas"]["tabla"] == "MOV_FACT_DET"
    # A esta no se llega por ningún parecido de nombre: 'cta' no se parece a
    # 'cuenta' ni a 'cliente'. Sale de ver que su clave está dentro de ventas.
    assert elegidas["clientes"]["tabla"] == "MAESTRO_CTAS"
    assert elegidas["clientes"].get("por_estructura") is True


def test_no_elige_la_tabla_vacia_aunque_tenga_el_nombre_esperado(tmp_path):
    """Una migración vieja deja `articulos` vacía y los datos en otro lado.
    Elegir por nombre agarra la vacía y el cliente ve un panel en cero."""
    from plania import catalogo as cm
    from plania import conectores

    ruta = _base_con_nombres_inventados(tmp_path)
    eng = conectores.conectar_sql(f"sqlite:///{ruta}")
    cat = cm.extraer(eng)
    elegidas = cm.elegir_tablas(cat, conectores.SINONIMOS,
                                conectores.TABLAS_CANDIDATAS, conectores.OBLIGATORIAS)
    assert elegidas["productos"]["tabla"] != "articulos"
    assert cat["tablas"]["articulos"]["n_filas"] == 0


def test_mapea_las_columnas_abreviadas_y_las_de_enlace(tmp_path):
    from plania import catalogo as cm
    from plania import conectores

    ruta = _base_con_nombres_inventados(tmp_path)
    eng = conectores.conectar_sql(f"sqlite:///{ruta}")
    cat = cm.extraer(eng)
    elegidas = cm.completar_por_estructura(
        cat, cm.elegir_tablas(cat, conectores.SINONIMOS,
                              conectores.TABLAS_CANDIDATAS, conectores.OBLIGATORIAS),
        conectores.SINONIMOS, conectores.OBLIGATORIAS)
    tablas = {e: r["tabla"] for e, r in elegidas.items()}

    for entidad in ("productos", "clientes", "ventas"):
        mapeo = cm.sugerir_mapeo(cat, tablas[entidad], entidad,
                                 conectores.SINONIMOS, tablas)
        faltan = [o for o in conectores.OBLIGATORIAS[entidad]
                  if o not in mapeo.values()]
        assert not faltan, f"{entidad}: quedaron sin mapear {faltan}"

    ventas = cm.sugerir_mapeo(cat, tablas["ventas"], "ventas",
                              conectores.SINONIMOS, tablas)
    assert ventas.get("fec") == "fecha", "no reconoció la abreviatura fec->fecha"
    assert ventas.get("nro_cta") == "cliente_id", "no siguió el enlace a clientes"
    # El error que tuvo la primera versión: 'nro_cta' cargado como número de
    # comprobante porque comparte el token vacío 'nro' con 'nro_comprobante'.
    assert ventas.get("nro_cta") != "venta_id"
    assert ventas.get("doc") == "venta_id"


def test_un_token_generico_no_alcanza_para_dar_dos_columnas_por_iguales():
    """`nro_cta` y `nro_comprobante` comparten 'nro' y no son lo mismo. Un
    mapeo equivocado en silencio es peor que uno faltante: el cliente ve
    números que no significan nada y no tiene cómo notarlo."""
    from plania import catalogo as cm

    assert cm.parecido("nro_cta", "nro_comprobante") == 0.0
    assert cm.parecido("cod_x", "cod_y") == 0.0
    # Y lo que sí tiene que reconocer:
    assert cm.parecido("fec", "fecha") > 0.6
    assert cm.parecido("nombre_fantasia", "nombre") > 0.6
    assert cm.parecido("costo_neto", "costo") > 0.6


def test_las_categorias_para_filtrar_salen_de_los_datos_reales():
    """Los filtros del panel tienen que ofrecer los rubros que el cliente
    tiene de verdad, no una lista fija inventada."""
    from plania import catalogo as cm
    from plania import conectores

    datos = conectores.cargar_datos()
    cats = cm.columnas_categoricas(datos["productos"])
    assert "categoria" in cats
    # El código de producto es único por fila: no es una categoría.
    assert "sku" not in cats
    valores = cm.valores_de(datos["productos"], "categoria")
    assert len(valores) > 1 and all(v is not None for v in valores)


# ---------------------------------------------------------------------------
# Archivos: que entre lo que el cliente exporta de SU sistema
# ---------------------------------------------------------------------------
def test_lee_el_csv_como_lo_exporta_un_erp_de_aca(tmp_path):
    """Formato real: latin-1, separador punto y coma, decimal con coma y
    miles con punto. Antes tiraba UnicodeDecodeError y el cliente no tenía
    forma de saber que el problema era la codificación."""
    from plania import archivos

    ruta = tmp_path / "zureo.csv"
    ruta.write_bytes(
        "Código;Descripción;Rubro;Costo;Precio Venta;Stock\n"
        "A001;Café Águila 500g;Almacén;123,45;1.234,50;12\n"
        "A002;Té Hornimans;Almacén;98,70;150,00;5\n".encode("latin-1"))

    df = archivos.leer(ruta)
    assert list(df.columns) == ["Código", "Descripción", "Rubro", "Costo",
                                "Precio Venta", "Stock"]
    assert len(df) == 2
    # Lo que de verdad importa: que los importes queden como NÚMERO. Si
    # "1.234,50" se lee como texto, todos los cálculos de plata dan cero y el
    # cliente ve un panel vacío sin ningún mensaje de error.
    assert df["Precio Venta"].dtype.kind in "if"
    assert abs(df["Precio Venta"].iloc[0] - 1234.50) < 0.01
    assert abs(df["Costo"].iloc[0] - 123.45) < 0.01
    assert df["Descripción"].iloc[0] == "Café Águila 500g"


def test_lee_csv_separado_por_tabulaciones_con_bom(tmp_path):
    from plania import archivos

    ruta = tmp_path / "tango.csv"
    ruta.write_bytes("cod_art\tdetalle\tcosto\tprecio\n"
                     "B1\tYerba Canarias\t80.5\t120.0\n".encode("utf-8-sig"))
    df = archivos.leer(ruta)
    assert list(df.columns) == ["cod_art", "detalle", "costo", "precio"]
    assert df["costo"].iloc[0] == 80.5


def test_saltea_el_titulo_del_reporte_antes_del_encabezado(tmp_path):
    """Los reportes traen el nombre de la empresa y la fecha arriba de todo.
    Antes eso era un ParserError."""
    from plania import archivos

    ruta = tmp_path / "con_titulo.csv"
    ruta.write_text("REPORTE DE ARTICULOS\nEmpresa Ejemplo SA\n"
                    "Emitido: 03/08/2026\n\n"
                    "codigo,descripcion,costo,precio\nC1,Fideos,20,35\n",
                    encoding="utf-8")
    df = archivos.leer(ruta)
    assert list(df.columns) == ["codigo", "descripcion", "costo", "precio"]
    assert len(df) == 1
    assert df["codigo"].iloc[0] == "C1"


def test_la_linea_en_blanco_no_desfasa_el_encabezado(tmp_path):
    """`skiprows` cuenta líneas del archivo, no líneas con contenido. Contar
    sobre la lista ya filtrada saltea de menos y el encabezado se lee como si
    fuera un dato."""
    from plania import archivos

    ruta = tmp_path / "blancos.csv"
    ruta.write_text("TITULO\n\n\ncodigo,precio\nX1,10\nX2,20\n", encoding="utf-8")
    df = archivos.leer(ruta)
    assert list(df.columns) == ["codigo", "precio"]
    assert len(df) == 2


def test_importa_un_archivo_grande_sin_cargarlo_entero_en_memoria(tmp_path):
    """'Sin límite de datos' quiere decir que el pico de memoria dependa del
    pedazo, no del archivo. Se comprueba importando de a 500 filas: si
    cargara todo, el número de filas escritas seguiría siendo correcto pero
    el diseño no serviría para un archivo que no entra en RAM."""
    import sqlite3

    from plania import archivos

    ruta = tmp_path / "grande.csv"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("codigo;descripcion;costo;precio\n")
        for i in range(5000):
            f.write(f"SKU{i};Producto {i};{i},50;{i * 2},75\n")

    db = tmp_path / "salida.db"
    n = archivos.importar_a_sqlite(ruta, "articulos", str(db), filas_por_pedazo=500)
    assert n == 5000

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0] == 5000
        # El decimal con coma tiene que haber quedado numérico también acá.
        assert con.execute("SELECT typeof(costo) FROM articulos LIMIT 1").fetchone()[0] == "real"
        assert con.execute("SELECT costo FROM articulos WHERE codigo='SKU10'").fetchone()[0] == 10.5
    finally:
        con.close()


def test_el_conector_usa_el_lector_adaptable(tmp_path):
    """La app entra por conectores.leer_archivo: si eso no delega en el lector
    nuevo, todo lo anterior no le sirve a nadie."""
    from plania import conectores

    ruta = tmp_path / "raro.csv"
    ruta.write_bytes("Código;Precio\nA1;1.234,50\n".encode("latin-1"))
    df = conectores.leer_archivo(ruta)
    assert abs(df["Precio"].iloc[0] - 1234.50) < 0.01


def test_filtrar_por_categoria_arrastra_las_ventas():
    """Filtrar productos tiene que filtrar también sus ventas. Si no, los KPI
    quedan incoherentes: la venta sigue siendo la del negocio entero mientras
    el stock es el de una categoría, y el margen que sale de cruzarlos no
    significa nada."""
    from plania import catalogo as cm
    from plania import conectores

    datos = conectores.cargar_datos()
    categoria = cm.valores_de(datos["productos"], "categoria")[0]

    productos = datos["productos"][datos["productos"]["categoria"] == categoria]
    ventas = datos["ventas"][datos["ventas"]["sku"].isin(productos["sku"])]

    assert 0 < len(productos) < len(datos["productos"])
    assert 0 < len(ventas) < len(datos["ventas"]), \
        "el filtro de productos no redujo las ventas"
    # Ninguna venta puede quedar apuntando a un producto que se filtró.
    assert set(ventas["sku"]) <= set(productos["sku"])


def test_la_app_ofrece_filtros_y_avisa_cuando_estan_puestos():
    """Un panel filtrado que no lo dice lleva a decisiones equivocadas: el
    encargado ve 'venta 30 días' y cree que es la del negocio entero."""
    app = open(os.path.join(RAIZ, "app", "app.py"), encoding="utf-8").read()
    assert "catalogo.columnas_categoricas" in app, \
        "las categorías tienen que salir de los datos del cliente, no de una lista fija"
    assert "_aviso_filtros" in app
    assert app.count("_aviso_filtros()") >= 5, \
        "el aviso tiene que estar en todas las pantallas que filtran"
    assert "Limpiar filtros" in app


# ---------------------------------------------------------------------------
# Presentación: es un producto que se vende, no un volcado de la base
# ---------------------------------------------------------------------------
def test_los_montos_usan_el_formato_de_aca():
    """`$2.86 M` con punto decimal es formato de Estados Unidos; en Uruguay
    eso se lee "dos punto ochenta y seis". Y un número cortado en la pantalla
    principal es lo peor que puede pasar en una demo."""
    import importlib.util
    import sys

    ruta = os.path.join(RAIZ, "app", "app.py")
    fuente = open(ruta, encoding="utf-8").read()
    # Se ejecutan solo las dos funciones de formato, sin levantar Streamlit.
    ns: dict = {}
    inicio = fuente.index("def _miles(")
    fin = fuente.index("# Nombres de columna que ve el cliente")
    exec(compile(fuente[inicio:fin], ruta, "exec"), ns)

    assert ns["_miles"](1234567.89, 2) == "1.234.567,89"
    assert ns["_fmt"](2856128) == "$2,86 M"
    # El caso que se veía cortado como "$689,…" en la tarjeta:
    assert ns["_fmt"](689234) == "$689 K"
    assert ns["_fmt"](1500) == "$1.500"


def test_no_se_le_muestran_al_cliente_los_nombres_internos():
    """`cliente_id`, `ultima_compra` y `margen_pct` son nombres del modelo de
    datos. El cliente tiene que ver el nombre de su negocio."""
    app = open(os.path.join(RAIZ, "app", "app.py"), encoding="utf-8").read()

    assert "ETIQUETAS = {" in app
    for interno in ("cliente_id", "ultima_compra", "margen_pct", "stock_min"):
        assert f'"{interno}"' in app.split("ETIQUETAS = {")[1].split("}")[0], \
            f"falta la etiqueta en castellano para {interno}"

    # Todas las tablas pasan por el mismo formateador: si alguna usa
    # st.dataframe directo, queda mostrando 315742.95 al lado de otra que
    # muestra 315.743.
    cuerpo = app.split("def _tabla(")[1]
    directas = [l for l in cuerpo.splitlines()
                if "st.dataframe(" in l and "vista" not in l]
    assert len(directas) <= 2, f"tablas sin formatear: {directas}"


def test_el_menu_no_parece_un_formulario():
    """El menú es un st.radio: sin ocultar el círculo de "opción marcada" se
    ve como un formulario y no como la navegación de un producto."""
    app = open(os.path.join(RAIZ, "app", "app.py"), encoding="utf-8").read()
    assert 'label[data-testid="stRadioOption"]' in app, \
        "el selector tiene que anclarse en el data-testid, que es estable; " \
        "las clases st-emotion-cache-… cambian entre versiones"
    assert "display: none !important" in app


# ---------------------------------------------------------------------------
# Ediciones del instalador: qué le llega al cliente y qué no
# ---------------------------------------------------------------------------
def _proteger():
    import importlib, os, sys
    sys.path.insert(0, os.path.join(RAIZ, "packaging"))
    return importlib.import_module("proteger_codigo")


def test_el_build_de_cliente_no_lleva_el_panel_del_dueno(tmp_path):
    """El panel del dueño, el modelo financiero y el kit de contenido son del
    Licenciante: viajaban en cada instalador y en cada demo descargada.

    Compilarlos con Cython no alcanzaba — seguían distribuyéndose. Es la
    misma razón por la que backend_venta quedó afuera.
    """
    import os
    proteger = _proteger()
    destino = str(tmp_path / "cliente")
    proteger.preparar_arbol(destino)

    for carpeta, archivos in proteger.MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            assert not os.path.exists(os.path.join(destino, carpeta, archivo)), \
                f"{carpeta}/{archivo} es del dueño y quedó en el build de cliente"

    # Y lo que el cliente sí necesita tiene que seguir estando: sacar de más
    # rompe el producto de una forma que no se ve hasta que alguien lo abre.
    for imprescindible in ("app/app.py", "plania/analitica.py", "plania/copiloto.py",
                           "plania/sugerencias.py", "plania/licencia.py"):
        carpeta, archivo = imprescindible.split("/")
        assert os.path.exists(os.path.join(destino, carpeta, archivo)), \
            f"falta {imprescindible} en el build de cliente"


def test_la_api_del_build_de_cliente_no_expone_ninguna_ruta_del_dueno(tmp_path):
    """Que el archivo no esté es la mitad; la otra es que la API arranque igual.

    `plania/api.py` monta las rutas /owner/* sólo si `plania/api_owner.py`
    existe. En el build del cliente no existe, así que no tiene que haber
    ninguna — y sobre todo, la API no puede morir en el import por buscar un
    módulo que se sacó a propósito. Se comprueba importando de verdad el árbol
    ya podado, en un proceso aparte para que no lo contamine el del repo, que
    sí tiene el módulo.
    """
    import json
    import subprocess
    import sys

    proteger = _proteger()
    destino = str(tmp_path / "cliente")
    proteger.preparar_arbol(destino)

    guion = ("import sys, json;"
             "sys.path.insert(0, sys.argv[1]);"
             "from plania import api;"
             "print(json.dumps(sorted(api.app.openapi()['paths'])))")
    r = subprocess.run([sys.executable, "-c", guion, destino],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, f"la API del cliente no arranca sin el panel:\n{r.stderr}"

    rutas = json.loads(r.stdout.strip().splitlines()[-1])
    del_dueno = [x for x in rutas if "owner" in x]
    assert not del_dueno, f"el build del cliente expone rutas del dueño: {del_dueno}"
    # Y las suyas siguen ahí: sacar de más rompe el producto en silencio.
    for suya in ("/salud", "/inicio", "/config"):
        assert suya in rutas, f"al podar el panel del dueño se llevó puesta {suya}"


def test_el_producto_es_uno_solo_para_el_dueno_y_para_quien_lo_compra(tmp_path):
    """No hay una versión del producto para adentro y otra para vender.

    Si la hubiera, el dueño estaría probando un programa que ningún cliente
    tiene: un problema reportado por un comprador podría no reproducírsele
    nunca, y la demo que le muestra a un prospecto no sería la que ese
    prospecto se descarga.
    """
    import inspect
    import os
    proteger = _proteger()

    # Preparar el árbol no admite variantes: no se le puede pedir "la del dueño".
    firma = inspect.signature(proteger.preparar_arbol)
    assert list(firma.parameters) == ["destino"], \
        "preparar_arbol volvió a aceptar una edición: el producto se bifurcó"

    # Y lo del dueño se saca siempre, sin importar el entorno.
    os.environ["PLANIA_EDICION"] = "owner"      # aunque alguien la reviva
    try:
        destino = str(tmp_path / "producto")
        proteger.preparar_arbol(destino)
        for carpeta, archivos in proteger.MODULOS_SOLO_OWNER.items():
            for archivo in archivos:
                assert not os.path.exists(os.path.join(destino, carpeta, archivo)), \
                    f"{carpeta}/{archivo} es del dueño y quedó en el producto"
    finally:
        os.environ.pop("PLANIA_EDICION", None)


def test_el_panel_del_dueno_no_pide_clave_en_su_propio_ejecutable(monkeypatch):
    """El dueño no tiene que ponerle contraseña a su propia máquina.

    Y no es un atajo: el token no protegía nada en ese escenario. Este panel
    se distribuye en un ejecutable que no se publica, no va a INSTALADOR/, no
    se adjunta a ninguna release, y el panel ni siquiera viaja dentro del
    producto. Quien tiene ese archivo es porque lo compiló. Lo que protege el
    panel es eso, no una clave que termina anotada al lado del teclado.

    Pero SOLO en ese escenario: se comprueban las dos condiciones por
    separado, porque cada una sola alcanzaría para dejar el panel abierto
    donde sí importa.
    """
    import importlib.util
    ruta = os.path.join(RAIZ, "app", "owner.py")
    fuente = open(ruta, encoding="utf-8").read()

    # Se extrae la función sola: importar app/owner.py entero levanta Streamlit
    # y dibuja el panel.
    inicio = fuente.index("def _es_el_programa_instalado")
    fin = fuente.index("esperado = _token_esperado()")
    ambito: dict = {"os": os, "sys": sys}
    exec(compile(fuente[inicio:fin], ruta, "exec"), ambito)
    es_instalado = ambito["_es_el_programa_instalado"]

    # 1. Corriendo desde el repo (sin congelar), pide token aunque escuche en
    #    loopback: así se lo prueba en desarrollo, y así puede quedar levantado
    #    sin querer en una máquina compartida.
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")
    assert es_instalado() is False, "sin congelar tiene que seguir pidiendo token"

    # 2. Congelado pero escuchando en toda la red —un despliegue en un
    #    servidor, un contenedor— también pide token: ahí hay red del otro
    #    lado, y el ejecutable ya no es prueba de nada.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    assert es_instalado() is False, "servido por red tiene que pedir token"

    # 3. Las dos juntas: es el programa instalado en la máquina del dueño.
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")
    assert es_instalado() is True

    # El lanzador es el que fija esa dirección, y tiene que seguir siendo
    # loopback: si algún día pasa a 0.0.0.0, este panel dejaría de abrirse solo
    # (molesto) — pero lo que importa es lo otro, que no quede escuchando en la
    # red con la facturación adentro.
    lanzador = open(os.path.join(RAIZ, "packaging", "plania_launcher.py"),
                    encoding="utf-8").read()
    assert 'setdefault("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")' in lanzador


def test_el_panel_junto_al_exe_trae_el_codigo_porque_el_producto_no_lo_lleva(tmp_path):
    """El ZIP que se descomprime adentro de la carpeta de Plania instalado.

    Existe porque un `.bat` suelto NO puede activar el panel: el código del
    panel no está adentro del ejecutable del cliente. No está escondido ni
    apagado — `proteger_codigo.py` lo saca del build, siempre. Un archivo que
    prometa "desbloquearlo" no puede funcionar: no hay nada que desbloquear.

    Así que lo que este ZIP tiene que traer es el CÓDIGO. Si algún día se
    arma sin él, el .bat copiaría nada y el panel no abriría, en silencio.
    """
    import importlib.util
    ruta = os.path.join(RAIZ, "packaging", "armar_owner_junto_al_exe.py")
    spec = importlib.util.spec_from_file_location("_plania_junto", ruta)
    junto = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(junto)

    destino = str(tmp_path / "Plania_Owner_Junto_Al_Exe.zip")
    junto.armar(destino)
    assert junto.verificar(destino) == []

    with zipfile.ZipFile(destino) as z:
        nombres = z.namelist()
        activar = z.read("ACTIVAR_OWNER.bat").decode("utf-8")

    # Los cinco módulos que el producto NO lleva tienen que viajar acá.
    proteger = _proteger()
    for carpeta, archivos in proteger.MODULOS_SOLO_OWNER.items():
        for archivo in archivos:
            assert f"owner/{carpeta}/{archivo}" in nombres, \
                f"falta {carpeta}/{archivo}: sin eso el panel no abre"

    # El .bat no puede copiar a ciegas: corrido en la carpeta equivocada
    # dejaría archivos sueltos en cualquier lado sin decir nada. (Qué
    # instalaciones reconoce lo cubre el test de más abajo.)
    assert "if not defined MOTOR (" in activar
    # Y tiene que existir la vuelta atrás: un instalador que no trae cómo
    # deshacerse obliga a borrar a mano archivos adentro de _internal\.
    assert "DESACTIVAR_OWNER.bat" in nombres

    # El nombre cae bajo la guarda que corta la publicación.
    assert os.path.basename(junto.DESTINO).startswith("Plania_Owner")


def test_el_bat_del_owner_sirve_para_las_dos_instalaciones(tmp_path):
    """Hay DOS instalaciones de Plania y no tienen la misma estructura:

        liviano/portable   <c>\\Plania.exe  +  <c>\\_internal\\
        Electron           <c>\\Plania.exe                    <- la ventana
                           <c>\\resources\\backend\\Plania.exe  <- el motor
                           <c>\\resources\\backend\\_internal\\

    El panel es una pantalla del MOTOR, así que el código va al lado del
    motor. La primera versión de este .bat buscaba `_internal\\` al lado del
    .exe y nada más: en la instalación de Electron —justamente la del
    instalador con ícono, la que más se va a usar— no encontraba nada y
    abortaba con "esta no parece una instalación completa".

    Y el lanzador tiene que llamar al motor, nunca a la ventana de Electron:
    esa dibuja la interfaz React, que no tiene las pantallas del panel.
    """
    import importlib.util
    ruta = os.path.join(RAIZ, "packaging", "armar_owner_junto_al_exe.py")
    spec = importlib.util.spec_from_file_location("_plania_junto2", ruta)
    junto = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(junto)

    destino = str(tmp_path / "z.zip")
    junto.armar(destino)
    with zipfile.ZipFile(destino) as z:
        activar = z.read("ACTIVAR_OWNER.bat").decode("utf-8")
        desactivar = z.read("DESACTIVAR_OWNER.bat").decode("utf-8")

    # Las dos rutas de detección, cada una con su condición.
    assert 'if exist "_internal\\" if exist "Plania.exe" set "MOTOR=."' in activar, \
        "falta detectar la instalación liviana/portable"
    assert 'if exist "resources\\backend\\_internal\\" set "MOTOR=resources\\backend"' \
        in activar, "falta detectar la instalación de Electron"

    # Se copia y se borra usando el motor detectado, no una ruta fija.
    for guion, que in ((activar, "copia"), (desactivar, "borrado")):
        assert "%MOTOR%\\_internal\\" in guion, \
            f"el {que} usa una ruta fija: falla en una de las dos instalaciones"

    # El lanzador arranca el motor, con la pantalla del panel y sin el modo
    # API (que levantaría la interfaz de Electron y no se vería nada).
    lanzador = activar[activar.index('> "Plania Owner.bat"'):]
    assert "PLANIA_PANEL=owner" in lanzador
    assert "PLANIA_MOTOR=" in lanzador, \
        "sin limpiar PLANIA_MOTOR, una corrida anterior en modo API deja el panel en blanco"
    assert "%MOTOR%\\Plania.exe" in lanzador, \
        "el lanzador apunta a la ventana de Electron en vez de al motor"


def test_el_instalador_del_panel_del_dueno_no_se_puede_publicar():
    """El panel ahora tiene su propio instalador, con ícono y desinstalador.
    Ese archivo lleva adentro la facturación y los clientes, así que el nombre
    tiene que caer bajo la misma guarda que ya corta la publicación."""
    iss = open(os.path.join(RAIZ, "packaging", "instalador_owner.iss"),
               encoding="utf-8").read()

    m = re.search(r"OutputBaseFilename=(\S+)", iss)
    assert m, "el instalador del panel no declara nombre de salida"
    assert m.group(1).startswith("Plania_Owner"), \
        f"'{m.group(1)}' no matchea la guarda Plania_Owner* del workflow"

    # AppId propio: con el del producto, instalar uno desinstalaría el otro.
    id_owner = re.search(r"AppId=\{\{([0-9A-F-]+)", iss, re.I)
    id_producto = re.search(r"AppId=\{\{([0-9A-F-]+)",
                            open(os.path.join(RAIZ, "packaging", "instalador.iss"),
                                 encoding="utf-8").read(), re.I)
    assert id_owner and id_producto and id_owner.group(1) != id_producto.group(1), \
        ("el panel y el producto no pueden compartir AppId: Windows los toma "
         "como el mismo programa y uno pisa al otro")

    # Ícono en el escritorio, menú Inicio y desinstalador — lo mismo que se le
    # exige al instalador del producto.
    assert "{autodesktop}" in iss, "falta el acceso directo del escritorio"
    assert "{group}" in iss, "falta la entrada del menú Inicio"
    assert "{uninstallexe}" in iss, "falta el acceso a desinstalar"

    # Y que .gitignore lo mantenga fuera del repositorio.
    ignore = open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8").read()
    assert "INSTALADOR/*.exe" in ignore


def test_el_panel_del_dueno_se_arma_como_programa_aparte():
    """El panel del dueño existe, pero como ejecutable propio.

    Es la contracara del test de arriba: sacarlo del producto no puede
    significar que el dueño se quede sin él.
    """
    import os
    spec = open(os.path.join(RAIZ, "packaging", "plania_owner.spec"),
                encoding="utf-8").read()
    assert "entrada_owner.py" in spec
    assert 'name="Plania Owner"' in spec

    entrada = open(os.path.join(RAIZ, "packaging", "entrada_owner.py"),
                   encoding="utf-8").read()
    assert 'PLANIA_PANEL"] = "owner"' in entrada

    lanzador = open(os.path.join(RAIZ, "packaging", "plania_launcher.py"),
                    encoding="utf-8").read()
    assert "owner.py" in lanzador, \
        "el lanzador no sabe levantar el panel del dueño"

    # Y el .spec del producto no puede nombrar ese entry point.
    producto = open(os.path.join(RAIZ, "packaging", "plania.spec"),
                    encoding="utf-8").read()
    assert "entrada_owner" not in producto


def test_la_ventana_del_cliente_no_lleva_nada_del_panel_del_dueno():
    """La interfaz del dueño tampoco puede viajar en el instalador del cliente.

    Del lado de Python esto ya estaba cubierto por `fuera_del_producto()`,
    pero esa regla no llega hasta acá por dos motivos independientes: sólo
    mira rutas de profundidad 2 dentro de `app/` y `plania/`, y sobre todo
    el camino de electron-builder no la consulta nunca — `desktop/package.json`
    empaqueta `"renderer/**"` sin una sola exclusión. Un `.js` del panel bajo
    `desktop/` se distribuiría en texto plano dentro del `.exe` de cada
    cliente, con la facturación y el modelo financiero a la vista.

    Por eso el panel se arma como programa aparte (`desktop_owner/`), igual
    que del lado de Python. Este control es el que nota si alguien lo mueve
    de vuelta adentro.
    """
    import json
    import os

    raiz_cliente = os.path.join(RAIZ, "desktop")
    for base, dirs, files in os.walk(raiz_cliente):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist_electron")]
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), RAIZ)
            assert "owner" not in f.lower(), \
                f"{rel} parece del panel del dueño y está en el árbol del cliente"

    # Y el contenido: una pantalla del dueño renombrada seguiría pegándole a
    # /owner/*, que es lo que de verdad la delata.
    for base, dirs, files in os.walk(os.path.join(raiz_cliente, "renderer")):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in files:
            if not f.endswith((".js", ".html", ".css")):
                continue
            ruta = os.path.join(base, f)
            texto = open(ruta, encoding="utf-8").read()
            assert "/owner/" not in texto, \
                f"{os.path.relpath(ruta, RAIZ)} le pega a la API del dueño"

    # El empaquetado del cliente no puede alcanzar el árbol del dueño.
    cfg = json.load(open(os.path.join(raiz_cliente, "package.json"), encoding="utf-8"))
    incluidos = json.dumps(cfg["build"])
    assert "desktop_owner" not in incluidos, \
        "el build del cliente incluye el árbol del panel del dueño"


def test_el_panel_del_dueno_tiene_su_propia_ventana_completa():
    """Contracara del control anterior: sacarlo del producto no puede dejar al
    dueño sin panel. Se arma el árbol de verdad y se comprueba que quede
    ejecutable — con las seis pantallas y las piezas que comparte con el
    producto ya copiadas."""
    import importlib
    import json
    import os
    import sys
    import tempfile

    sys.path.insert(0, os.path.join(RAIZ, "packaging"))
    armador = importlib.import_module("armar_desktop_owner")

    with tempfile.TemporaryDirectory() as tmp:
        destino = os.path.join(tmp, "desktop_owner")
        # Sin node_modules: son 100 MB y no hacen falta para este control.
        armador.armar(destino, node_modules=False)

        for imprescindible in armador.IMPRESCINDIBLES:
            assert os.path.exists(os.path.join(destino, imprescindible.replace("/", os.sep))), \
                f"el árbol del panel quedó sin {imprescindible}"

        # Las seis secciones del menú de app/owner.py, ni una menos.
        menu = open(os.path.join(destino, "renderer", "ui", "app_owner.js"),
                    encoding="utf-8").read()
        for seccion in ("Estado del negocio", "Clientes y licencias",
                        "Proyección de rentabilidad", "Mercado y competencia",
                        "Contenido para redes", "Verificación del producto"):
            assert seccion in menu, f"al panel le falta la sección {seccion!r}"

        # base.js se copia, no se duplica: dos copias divergen y el panel
        # termina mostrando los números con otro formato que el producto.
        copiado = open(os.path.join(destino, "renderer", "ui", "base.js"),
                       encoding="utf-8").read()
        original = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "base.js"),
                        encoding="utf-8").read()
        assert copiado == original, "base.js del panel no es el mismo que el del producto"
        assert not os.path.exists(os.path.join(RAIZ, "desktop_owner", "renderer",
                                               "ui", "base.js")), \
            "base.js está duplicado en desktop_owner/: tiene que salir de desktop/"

        cfg = json.load(open(os.path.join(destino, "package.json"), encoding="utf-8"))
        assert cfg["build"]["appId"] != "uy.plania.desktop", \
            "mismo appId que el producto: instalar uno desinstalaría el otro"
        assert cfg["build"]["nsis"]["createDesktopShortcut"] is True
        assert cfg["build"]["nsis"]["uninstallDisplayName"] == "Plania Owner"


def test_la_interfaz_distingue_la_demo_vencida_de_un_error_de_verdad():
    """El 402 de `_exigir_licencia_vigente` (plania/api.py) tiene que llegar
    marcado hasta `Error_`, o cae en el mensaje genérico "No se pudieron
    traer los datos" — que en Stock, Precios o Panel ejecutivo se lee como un
    bug del programa cuando en realidad es exactamente lo que tiene que
    pasar cuando vence la demo."""
    import os
    base = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "base.js"),
               encoding="utf-8").read()

    assert "err.status = r.status" in base, \
        "pedir() no le pega el status HTTP al error: Error_ no puede distinguir 402"
    assert 'error: err' in base and 'error: err.message' not in base, \
        "useDatos sigue guardando sólo err.message: se perdió el status en el camino"

    i = base.index("function Error_")
    bloque = base[i:i + 800]
    assert "mensaje.status === 402" in bloque, \
        "Error_ no distingue la demo vencida de un error real"
    assert "aviso-vencida" in bloque


def test_el_ejecutable_del_panel_puede_servir_su_api():
    """El `.exe` del panel tiene que saber levantar la API, no sólo Streamlit.

    Son dos ventanas sobre el mismo ejecutable: `Plania Owner.exe` a secas
    abre Streamlit, y lanzado por la ventana Electron del panel abre la API
    local con las rutas /owner/*. Lo segundo es nuevo, y falla de la forma más
    cara: PyInstaller compila sin quejarse y el ejecutable muere recién al
    arrancar en modo API, porque uvicorn resuelve estos módulos por nombre en
    tiempo de ejecución y nada los alcanza siguiendo imports.
    """
    import os
    spec = open(os.path.join(RAIZ, "packaging", "plania_owner.spec"),
                encoding="utf-8").read()
    for modulo in ("plania.api", "plania.api_owner", "uvicorn.loops.auto",
                   "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"):
        assert f'"{modulo}"' in spec, \
            f"plania_owner.spec no declara {modulo}: el panel no abre en modo API"

    # El lanzador no puede ignorar el pedido de API cuando la pantalla es la
    # del dueño: si lo ignorara, la ventana Electron esperaría para siempre
    # una API que nunca levanta.
    lanzador = open(os.path.join(RAIZ, "packaging", "plania_launcher.py"),
                    encoding="utf-8").read()
    i = lanzador.index("if _modo_api():")
    assert "PLANIA_PANEL" not in lanzador[i:i + 200], \
        "el modo API se decide mirando la pantalla, y no tiene que hacerlo"

    # Y el entry point del panel no puede limpiar PLANIA_MOTOR: eso forzaría
    # Streamlit siempre y dejaría la ventana Electron sin API.
    entrada = open(os.path.join(RAIZ, "packaging", "entrada_owner.py"),
                   encoding="utf-8").read()
    assert 'PLANIA_MOTOR"] = ""' not in entrada and "PLANIA_MOTOR\"]=\"\"" not in entrada, \
        "entrada_owner.py limpia PLANIA_MOTOR: la ventana Electron del panel no abriría"


def test_la_ventana_del_panel_se_arma_pero_no_se_publica():
    """El instalador del panel se arma con --con-owner, en la máquina del
    dueño, y nunca en el workflow que publica. Es la misma regla que ya rige
    para el ZIP y para su instalador de Inno Setup, aplicada a la ventana
    Electron."""
    import os
    build = open(os.path.join(RAIZ, "packaging", "build_release.py"),
                 encoding="utf-8").read()
    assert "paso_owner_electron" in build, \
        "--con-owner no arma la ventana Electron del panel"
    i = build.index("def paso_owner_electron")
    assert "armar_desktop_owner" in build[i:i + 1200], \
        "la ventana del panel se armaría sin componer su árbol"

    # El workflow de Release no puede armarla: publica lo que deja en disco.
    wf = _release_yml()
    for prohibido in ("desktop_owner", "--con-owner", "armar_desktop_owner"):
        assert prohibido not in wf, \
            f"el workflow que publica nombra {prohibido!r}: el panel no se publica"


def test_la_app_del_cliente_no_importa_nada_del_dueno():
    """Lo que decide si se puede sacar un módulo del build es quién lo importa.

    Si mañana app/app.py importara plania/negocio.py, sacarlo dejaría al
    cliente con una app que no abre — y el test de arriba seguiría en verde.
    """
    import os
    import re
    proteger = _proteger()
    prohibidos = {os.path.splitext(a)[0] for a in proteger.MODULOS_SOLO_OWNER["plania"]}

    pendientes = ["app/app.py"]
    vistos = set()
    while pendientes:
        actual = pendientes.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        ruta = os.path.join(RAIZ, actual)
        if not os.path.exists(ruta):
            continue
        codigo = open(ruta, encoding="utf-8").read()
        importados = set()
        for m in re.finditer(r"from plania import ([^\n#]+)", codigo):
            importados.update(x.strip() for x in m.group(1).split(","))
        for m in re.finditer(r"import plania\.(\w+)", codigo):
            importados.add(m.group(1))

        colision = importados & prohibidos
        assert not colision, f"{actual} importa {colision}, que no va al cliente"
        pendientes += [f"plania/{i}.py" for i in importados if i not in vistos]


def test_el_instalador_deja_elegir_que_instalar():
    """El pedido explícito: instalación a elegir. Sin [Types] con un tipo
    personalizado, marcar componentes sueltos no habilita nada."""
    import os
    import re
    iss = open(os.path.join(RAIZ, "packaging", "instalador.iss"),
               encoding="utf-8", errors="replace").read()
    # Inno Setup parte las líneas largas con "\\": se juntan antes de buscar,
    # o una declaración perfectamente válida no matchea por dónde se cortó.
    iss = re.sub(r"\\\s*\n\s*", " ", iss)
    assert "[Types]" in iss and "[Components]" in iss
    assert "iscustom" in iss.lower()
    assert re.search(r'Name:\s*"programa".*Flags:\s*fixed', iss), \
        "el programa principal tiene que ser obligatorio"
    assert "CurUninstallStepChanged" in iss and "DelTree" in iss, \
        "al desinstalar se pregunta qué hacer con los datos"


def test_el_control_del_instalador_pasa_entero():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "packaging/verificar_instalador.py"],
                       cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


# ---------------------------------------------------------------------------
# Ventana propia del programa (que el .exe no se abra como una página web)
# ---------------------------------------------------------------------------
def _ventana():
    import importlib.util
    ruta = os.path.join(RAIZ, "packaging", "ventana.py")
    spec = importlib.util.spec_from_file_location("ventana", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_el_programa_pide_ventana_propia_y_no_una_pestana():
    """Lo que se vende es un programa. Si abre una pestaña con la barra de
    direcciones a la vista, el cliente lee "esto es una página web"."""
    v = _ventana()
    cmd = v.comando("/ruta/al/navegador", "http://localhost:8531", "/tmp/perfil")

    modo_app = [a for a in cmd if a.startswith("--app=")]
    assert modo_app == ["--app=http://localhost:8531"], \
        "sin --app se abre una pestaña común, con barra de direcciones y pestañas"

    # Perfil propio: sin esto la ventana se cuelga de la sesión de navegación
    # del usuario, hereda sus extensiones y cerrarla puede arrastrarle otras
    # ventanas abiertas.
    assert any(a.startswith("--user-data-dir=") for a in cmd)


def test_sin_navegador_no_se_rompe_se_avisa():
    """Sin ningún navegador con modo ventana, `abrir` devuelve None para que
    el lanzador caiga al navegador por defecto. Nunca puede quedar peor que
    antes de existir la ventana."""
    v = _ventana()
    v.buscar_navegador = lambda: None
    assert v.abrir("http://localhost:1") is None

    v.buscar_navegador = lambda: "/no/existe"
    assert v.abrir("http://localhost:1") is None


def test_el_lanzador_abre_ventana_antes_que_navegador():
    """El lanzador tiene que intentar la ventana primero y dejar el navegador
    como reserva — no al revés."""
    fuente = open(os.path.join(RAIZ, "packaging", "plania_launcher.py"),
                  encoding="utf-8").read()
    assert "ventana.abrir(url)" in fuente
    i_ventana = fuente.index("ventana.abrir(url)")
    i_reserva = fuente.index("webbrowser.open(url)", i_ventana)
    assert i_ventana < i_reserva, "el navegador tiene que ser la reserva, no lo primero"
    # Y cerrar la ventana tiene que terminar el programa: si no, el server
    # queda corriendo invisible y el próximo arranque se muda de puerto.
    assert "proceso.wait()" in fuente and "os._exit(0)" in fuente


def test_el_ejecutable_empaqueta_el_modulo_de_la_ventana():
    """El lanzador importa `ventana` dentro de un try/except, así que
    PyInstaller no lo ve solo. Si falta esta declaración el .exe compila
    igual y se abre en el navegador — el error se descubre recién cuando un
    cliente lo descarga."""
    spec = open(os.path.join(RAIZ, "packaging", "plania.spec"), encoding="utf-8").read()
    assert '"ventana"' in spec, "falta 'ventana' en hiddenimports de plania.spec"
    assert "_PATHEX_EXTRA" in spec and "pathex=[REPO] + _PATHEX_EXTRA" in spec, \
        "packaging/ tiene que estar en el pathex para que `import ventana` resuelva"


# ---------------------------------------------------------------------------
# Release automático: el job "gate" decide si hace falta prender windows-latest
# ---------------------------------------------------------------------------
def _release_yml() -> str:
    return open(os.path.join(RAIZ, ".github", "workflows", "release.yml"),
                encoding="utf-8").read()


def _extraer_script_gate(fuente: str) -> str:
    """El cuerpo JS de `jobs.gate.steps[0].script`, tal cual corre en GitHub.

    Se extrae con texto y no con un parser de YAML (que no es dependencia
    declarada del proyecto — ver README, "no hace falta preguntarle a nadie
    qué más hace falta") buscando el marcador `script: |` y juntando las
    líneas indentadas que siguen, igual que ya se hace en este archivo para
    aislar `escaparHtml()` de plania.js.
    """
    i = fuente.index("script: |")
    resto = fuente[i:].splitlines()[1:]
    lineas = []
    for l in resto:
        if l.strip() and not l.startswith(" " * 12):
            break
        lineas.append(l[12:] if len(l) >= 12 else "")
    return "\n".join(lineas)


def test_el_gate_solo_construye_cuando_hace_falta():
    """Prueba el JS del gate DE VERDAD (con Node), no una reimplementación en
    Python que se podría desincronizar del archivo real. Cubre el caso que
    motivó separar esto en un job aparte: un tag siempre construye aunque el
    filtro de rutas del push automático lo hubiera descartado."""
    import json
    import subprocess

    assert _node_disponible(), "hace falta node para este test"
    script = _extraer_script_gate(_release_yml())
    assert "tocaProducto" in script and "core.setOutput" in script, \
        "no se pudo aislar el script del gate — revisá la indentación en release.yml"

    CASOS = [
        ("push a main, toca plania/",
         {"eventName": "push", "ref": "refs/heads/main",
          "payload": {"commits": [{"added": [], "removed": [], "modified": ["plania/analitica.py"]}]}},
         "si"),
        ("push a main, solo docs/ y README (no van al binario)",
         {"eventName": "push", "ref": "refs/heads/main",
          "payload": {"commits": [{"added": [], "removed": [], "modified": ["docs/x.md", "README.md"]}]}},
         "no"),
        ("push a main, solo la web de venta (sitio/, web/)",
         {"eventName": "push", "ref": "refs/heads/main",
          "payload": {"commits": [{"added": [], "removed": [], "modified": ["sitio/build.py", "web/es/index.html"]}]}},
         "no"),
        ("push a main tocando SOLO INSTALADOR/: el propio commit del bot no "
         "se tiene que disparar a sí mismo",
         {"eventName": "push", "ref": "refs/heads/main",
          "payload": {"commits": [{"added": ["INSTALADOR/Plania_Setup.exe"], "removed": [],
                                   "modified": ["INSTALADOR/CHECKSUMS.txt"]}]}},
         "no"),
        ("tag v1.0.0 que solo tocó documentación: SIEMPRE construye, un tag "
         "es una decisión humana explícita",
         {"eventName": "push", "ref": "refs/tags/v1.0.0",
          "payload": {"commits": [{"added": [], "removed": [], "modified": ["README.md"]}]}},
         "si"),
        ("workflow_dispatch manual",
         {"eventName": "workflow_dispatch", "ref": "refs/heads/main", "payload": {}},
         "si"),
        ("push sin lista de commits en el payload: no se puede afirmar que "
         "no tocó el producto, así que construye",
         {"eventName": "push", "ref": "refs/heads/main", "payload": {}},
         "si"),
    ]

    for descripcion, ctx, esperado in CASOS:
        # github-script corre el `script:` adentro de una función async (así
        # es como puede usar `await`); por eso el propio código del gate
        # tiene un `return` "suelto" en el caso de tag/dispatch — válido ahí,
        # un SyntaxError si se evalúa top-level. Se envuelve en una IIFE para
        # correr el texto real tal cual, y `context`/`core` quedan AFUERA de
        # esa IIFE (visibles por clausura) para poder leer `core._out` una
        # vez que la promesa resuelve — leerlo desde adentro, después del
        # script, se salteaba en los casos que retornan temprano.
        arnes = f"""
        const context = {json.dumps(ctx)};
        const core = {{
          _out: {{}},
          setOutput(k, v) {{ this._out[k] = v; }},
          info() {{}}, notice() {{}},
        }};
        (async () => {{
          {script}
        }})().then(() => {{
          console.log(JSON.stringify(core._out));
        }});
        """
        r = subprocess.run(["node", "-e", arnes], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"[{descripcion}] el gate no corrió:\n{r.stderr}"
        assert r.stdout.strip(), f"[{descripcion}] stdout vacío. stderr={r.stderr!r}"
        salida = json.loads(r.stdout.strip().splitlines()[-1])
        assert salida.get("build") == esperado, \
            f"[{descripcion}] build={salida.get('build')!r}, esperaba {esperado!r}"


def test_el_workflow_no_intenta_commitear_binarios_al_repositorio():
    """GitHub rechaza cualquier archivo de más de 100 MB, y el ZIP portable
    pesa 138.

    El workflow copiaba los instaladores a INSTALADOR/ y los commiteaba. La
    primera corrida que llegó hasta ese paso —después de arreglar el
    instalador— construyó todo bien y murió empujando:

        remote: error: File INSTALADOR/Plania_portable.zip is 138.79 MB;
               this exceeds GitHub's file size limit of 100.00 MB
        ! [remote rejected] HEAD -> main (pre-receive hook declined)

    El Setup pesaba 99.7 MB: pasaba raspando y se iba a romper solo en cuanto
    creciera. Los binarios van a la página de Releases (hasta 2 GB por
    archivo, y sin tocar el historial de git); al repo va sólo el .txt con los
    sha256.
    """
    import yaml
    wf = yaml.safe_load(_release_yml())
    pasos = wf["jobs"]["ejecutables-windows"]["steps"]
    commit = next(p for p in pasos if p.get("name") == "Commitear los checksums")
    guion = commit["run"]

    assert "git add INSTALADOR/CHECKSUMS.txt" in guion, \
        "hay que agregar el archivo puntual, no la carpeta"
    assert "git add -f INSTALADOR/" not in guion, \
        "agregar la carpeta entera vuelve a meter los binarios y el push se rechaza"
    for binario in (".exe", ".zip"):
        assert binario not in guion, \
            f"el paso que commitea menciona {binario}: los binarios no van al repo"

    # Y que exista el paso que sí los publica, donde no hay límite de 100 MB.
    publica = [p for p in pasos if p.get("uses", "").startswith("softprops/action-gh-release")]
    assert publica, "sin este paso los instaladores no llegan a ningún lado"
    assert any("Plania_portable.zip" in p.get("with", {}).get("files", "")
               for p in publica), "el portable tiene que publicarse como asset"

    # El .txt es lo ÚNICO que quedó en el repositorio en lugar de los
    # binarios, así que tiene que poder casarse con la descarga. GitHub
    # reemplaza los espacios del nombre al publicar el asset ("Plania Setup
    # 1.0.0.exe" se baja como "Plania.Setup.1.0.0.exe"): anotado con espacios,
    # quien verifica su descarga no encuentra la línea.
    checksums = next(p for p in pasos
                     if p.get("name") == "Calcular checksums e índice de descargas")
    assert "-replace ' ', '.'" in checksums["run"], \
        "los checksums tienen que usar el nombre con el que GitHub publica el asset"


def test_el_release_automatico_no_corta_una_version_nueva():
    """El push automático a main publica, pero sobre una entrada rodante que se
    pisa sola (`ultima-compilacion`, marcada como prerelease). Cortar una
    VERSIÓN —con su número y su changelog— sigue siendo una decisión humana:
    un tag o un "Run workflow" manual."""
    import yaml
    wf = yaml.safe_load(_release_yml())
    pasos = wf["jobs"]["ejecutables-windows"]["steps"]

    rodante = next(p for p in pasos
                   if p.get("name", "").startswith("Publicar la última compilación"))
    assert rodante["with"]["tag_name"] == "ultima-compilacion", \
        "un tag distinto por commit llenaría Releases de entradas"
    assert rodante["with"]["prerelease"] is True, \
        "no puede figurar como la versión estable: cambia sin aviso"
    assert "github.event_name == 'push'" in rodante["if"]


def test_el_release_versionado_no_sale_en_un_push_automatico():
    """La entrada versionada de Releases (la que se le pasa a un cliente) no
    puede crearse sola en cada commit."""
    # La condición se lee del YAML ya parseado y no como líneas de texto: pasó
    # a ser multilínea (`if: >-`) al agregar el modo "solo verificar", y el
    # control anterior —que miraba la primera línea que contuviera "if:"— se
    # rompió sin que hubiera nada mal.
    import yaml
    wf = yaml.safe_load(_release_yml())
    pasos = wf["jobs"]["ejecutables-windows"]["steps"]
    publicar = next(p for p in pasos
                    if p.get("name") == "Publicar release con las descargas")
    condicion = publicar.get("if", "")
    assert condicion, "el paso que publica en Releases tiene que estar condicionado"
    assert "github.ref_type == 'tag'" in condicion and "workflow_dispatch" in condicion, \
        "el paso de Releases tiene que saltearse en un push automático a main"

    # Y una corrida manual con "solo verificar" no puede publicar: existe para
    # poder construir sobre una rama y ver si compila —por ejemplo después de
    # arreglar el instalador— sin dejar binarios en la rama por defecto ni
    # crear una entrada de Release.
    # Todo paso que deje algo afuera —los dos que publican y el que commitea—
    # tiene que respetarlo.
    dejan_algo_afuera = [p for p in pasos
                         if p.get("name", "").startswith("Publicar")
                         or p.get("name") == "Commitear los checksums"]
    assert len(dejan_algo_afuera) == 3, \
        f"cambiaron los pasos que publican: {[p.get('name') for p in dejan_algo_afuera]}"
    for paso in dejan_algo_afuera:
        assert "solo_verificar" in paso.get("if", ""), \
            f"'{paso['name']}' corre igual con solo_verificar activado"
    # YAML 1.1 lee `on:` como el booleano True, no como la cadena "on".
    disparadores = wf.get("on", wf.get(True))
    assert "solo_verificar" in disparadores["workflow_dispatch"]["inputs"], \
        "el modo solo verificar tiene que ser una opción del Run workflow"


def test_el_job_caro_de_windows_esta_gateado_por_el_de_linux():
    """El job de windows-latest (caro: Cython + PyInstaller + Electron) no
    arranca si el gate, que corre en Linux, dijo que no hace falta."""
    wf = _release_yml()
    assert "runs-on: ubuntu-latest" in wf, "falta el job barato que decide"
    i_gate = wf.index("gate:")
    i_windows = wf.index("ejecutables-windows:")
    assert i_gate < i_windows
    bloque_windows = wf[i_windows:i_windows + 1500]
    assert "needs: gate" in bloque_windows


def test_el_gate_falla_hacia_construir_y_no_hacia_no_construir():
    """Si el gate no llega a decidir, se construye igual.

    Esto pasó de verdad: en la corrida que disparó el merge del PR #25 el
    gate murió sin ejecutarse (GitHub no le asignó runner). Con la condición
    original —`== 'si'`— el job de Windows quedó en "skipped": gris, idéntico
    a "no había nada que construir". Resultado: ningún instalador y ningún
    error que lo explicara.

    La condición correcta es negativa: construir salvo que el gate haya dicho
    explícitamente que no. Es la misma regla que el gate ya aplica por dentro
    cuando no puede leer la lista de archivos del push.
    """
    wf = _release_yml()
    i = wf.index("ejecutables-windows:")
    bloque = wf[i:i + 1500]
    linea_if = [l for l in bloque.splitlines() if l.strip().startswith("if:")][0]

    assert "!= 'no'" in linea_if, \
        "la condición tiene que ser negativa (fail-open): un gate que no pudo " \
        "correr no puede dejar la release en silencio"
    assert "== 'si'" not in linea_if, \
        "condición positiva: si el gate no llega a emitir su salida, no se construye nada"
    # Pero una corrida cancelada por `concurrency` sí tiene que cortar: llegó
    # un push más nuevo y este build ya no interesa.
    assert "!cancelled()" in linea_if, \
        "sin !cancelled(), una corrida cancelada por concurrency igual construiría"
    assert "always()" not in linea_if, \
        "always() incluye las canceladas — usar !cancelled()"


def test_release_tiene_concurrencia_para_no_amontonar_builds_caros():
    """Sin esto, dos push seguidos a main dejan dos corridas de windows-latest
    compitiendo por minutos pagos cuando solo el resultado del último push
    importa."""
    wf = _release_yml()
    assert "concurrency:" in wf
    bloque = wf[wf.index("concurrency:"):wf.index("concurrency:") + 200]
    assert "cancel-in-progress: true" in bloque


def test_el_trigger_automatico_no_filtra_los_tags():
    """`paths:` a nivel de trigger se aplicaría también a los push de tags —
    y un tag sobre un commit que no tocó código se saltearía sin avisar justo
    cuando alguien decidió a propósito cortar una versión. El filtro tiene
    que vivir en el gate (evaluado con el listado real de archivos), no en
    `on.push.paths`."""
    wf = _release_yml()
    trigger = wf[wf.index("\non:"):wf.index("permissions:")]
    assert "paths:" not in trigger, \
        "un filtro de rutas acá también aplicaría a los tags — usar el gate"
    assert 'tags: ["v*"]' in trigger.replace("'", '"')
    assert 'branches: ["main"]' in trigger.replace("'", '"')


def test_el_panel_del_dueno_nunca_se_publica_en_el_repo():
    """La carpeta INSTALADOR/ es lo que se sube a plania.uy. El ejecutable del
    dueño lleva adentro la facturación, los clientes y el modelo financiero:
    si alguna vez cae ahí, deja de ser tuyo y pasa a ser de cualquiera que
    tenga acceso al repositorio — hoy, o el día que sumes a alguien.

    Se controla en dos planos: que el archivo no esté, y que el workflow corte
    si aparece (porque el archivo puede no estar hoy y aparecer mañana).
    """
    import os
    for nombre in os.listdir(os.path.join(RAIZ, "INSTALADOR")):
        assert "Owner" not in nombre and "owner" not in nombre, \
            f"INSTALADOR/{nombre} parece ser el build del dueño"

    # Se busca la comprobación que HACE el trabajo, no una mención del nombre.
    # La primera versión de este control buscaba "Plania_Owner.zip" suelto, y
    # el texto del mensaje de error ya la satisfacía: al sacar el `Test-Path`
    # el control seguía en verde con la guarda borrada.
    #
    # No se fija el texto del patrón sino LO QUE ATRAPA, con los nombres
    # reales de las tres formas en que hoy se arma el panel. Fijar la cadena
    # obliga a actualizar el test cada vez que se toca la guarda, y ese
    # trámite invita a copiar el patrón nuevo sin comprobar si sigue
    # cubriendo todo — que es justo cómo se pierde una guarda.
    import re
    wf = _release_yml()
    m = re.search(r"\$archivos \| Where-Object \{ \$_\.Name -match '([^']+)' \}", wf)
    assert m, "falta la guarda que impide publicar el build del dueño"

    patron = re.compile(m.group(1))
    for nombre in ("Plania_Owner.zip",              # bundle de PyInstaller
                   "Plania_Owner_BAT.zip",          # el código con su .bat
                   "Plania Owner Setup 1.0.0.exe"): # la ventana Electron
        assert patron.search(nombre), \
            f"la guarda deja pasar {nombre!r}, que es el panel del dueño"
    # Y no puede llevarse puesto el producto.
    for nombre in ("Plania_Setup_v1.0.0.exe", "Plania.Setup.1.0.0.exe",
                   "Plania_portable.zip", "Plania_BAT.zip"):
        assert not patron.search(nombre), \
            f"la guarda bloquea {nombre!r}, que sí se publica"

    bloque = wf[m.start():m.start() + 300]
    assert "exit 1" in bloque, \
        "detectar el build del dueño en INSTALADOR/ tiene que cortar la corrida"


def test_el_cliente_no_descarga_del_repositorio():
    """Decisión de distribución: el repo es privado y es el código fuente, no
    la tienda. El cliente descarga de plania.uy y del link post-pago. Si
    alguien documenta lo contrario, el repo tendría que hacerse público — y
    ahí el mismo ZIP entrega el código fuente completo."""
    import os
    readme = open(os.path.join(RAIZ, "INSTALADOR", "README.md"), encoding="utf-8").read()
    assert "/descargar/{token}" in readme, \
        "falta documentar el canal real de descarga post-pago"
    assert "plania.uy" in readme

    # Y el canal post-pago tiene que existir de verdad en el backend, no solo
    # en la documentación.
    backend = open(os.path.join(RAIZ, "backend_venta", "app.py"), encoding="utf-8").read()
    assert "/descargar/{token}" in backend
    assert "PLANIA_INSTALADOR_PATH" in backend, \
        "el backend tiene que poder apuntar al instalador publicado"


# ---------------------------------------------------------------------------
# API local: la capa que va a consumir la interfaz React de escritorio
# ---------------------------------------------------------------------------
def _cliente_api():
    from fastapi.testclient import TestClient
    from plania import api
    api.invalidar_cache()
    return TestClient(api.app)


def _rutas_de(app) -> set:
    """Todas las rutas de una app FastAPI, incluidas las de routers montados.

    No se recorre `app.routes` a mano: desde que la API monta el router del
    panel del dueño con `include_router`, esa lista trae un objeto envoltorio
    sin atributo `.path`, y las rutas de adentro no se ven. Eso importa sobre
    todo para los controles que verifican que algo NO esté: leer `.path` con
    un `getattr(r, "path", "")` los dejaría pasando sin mirar justamente las
    rutas montadas. El esquema OpenAPI las lista todas, sin importar cómo se
    registraron.
    """
    return set(app.openapi()["paths"])


def test_la_api_local_responde_todas_las_pantallas():
    """Cada pantalla del producto tiene que poder alimentarse de la API. Si un
    endpoint devuelve 500 con la base demo, con una base real va a fallar
    igual: la demo es el caso fácil."""
    c = _cliente_api()
    for metodo, ruta, cuerpo in [
        ("GET", "/salud", None), ("GET", "/licencia", None),
        ("GET", "/panel", None), ("GET", "/stock", None),
        ("GET", "/precios", None), ("GET", "/zonas", None),
        ("GET", "/ofertas", None), ("GET", "/clientes/inactivos", None),
        ("POST", "/rutas", {"vehiculos": 2}),
        ("POST", "/copiloto", {"pregunta": "¿qué ofertas armo esta semana?"}),
    ]:
        r = c.request(metodo, ruta, json=cuerpo)
        assert r.status_code == 200, f"{metodo} {ruta} -> {r.status_code}: {r.text[:200]}"


def test_la_api_da_los_mismos_numeros_que_la_pantalla_actual():
    """El control central de la migración a React.

    La API no puede recalcular nada por su cuenta: tiene que devolver lo que
    devuelven los módulos que ya usa `app/app.py`. Si acá apareciera una
    cuenta propia habría dos fuentes de verdad, y el día que difieran, la
    diferencia se ve delante de un cliente.
    """
    from plania import analitica, conectores, sugerencias

    d = conectores.cargar_datos()
    v = analitica.enriquecer_ventas(d["ventas"], d["productos"], d["clientes"])
    c = _cliente_api()

    esperados = analitica.kpis(d["productos"], v, 30)
    obtenidos = c.get("/panel").json()["kpis"]
    for clave, valor in esperados.items():
        if isinstance(valor, float):
            assert abs(obtenidos[clave] - valor) < 1e-6, f"kpi {clave} difiere"
        else:
            assert obtenidos[clave] == valor, f"kpi {clave} difiere"

    # Y las tablas: mismo total de filas que la función que las produce.
    secciones = c.get("/ofertas").json()["secciones"]
    assert (secciones["ofertas"]["tabla"]["total"]
            == len(sugerencias.ofertas_por_sobrestock(d["productos"], v)))
    assert (c.get("/stock").json()["reposicion"]["total"]
            == len(sugerencias.reposicion(d["productos"], v)))


def test_la_api_no_emite_json_invalido_con_datos_vacios():
    """NaN e Infinity no existen en JSON: `json.dumps` los escribe igual y del
    otro lado `JSON.parse` rechaza el documento entero — la pantalla queda en
    blanco sin explicación. Un promedio sobre cero filas alcanza para
    producirlos, así que no es un caso raro: es un cliente cuyo período no
    tiene ventas."""
    import json
    import math

    import pandas as pd
    from plania import api

    vacio = pd.DataFrame({"a": [float("nan")], "b": [float("inf")], "c": [1.0]})
    salida = api.tabla_json(vacio)
    texto = json.dumps(salida)          # falla si quedó un NaN suelto
    assert "NaN" not in texto and "Infinity" not in texto
    assert salida["filas"][0]["a"] is None and salida["filas"][0]["b"] is None
    assert salida["filas"][0]["c"] == 1.0

    # Y el caso de verdad: KPIs sobre un período sin ventas.
    assert api._limpiar(float("nan")) is None
    assert api._limpiar(math.inf) is None


def test_la_api_recorta_pero_dice_cuanto_recorto():
    """Mandar 50.000 filas a la interfaz la cuelga; recortarlas sin avisar
    hace que el usuario crea que eso es todo lo que hay."""
    import pandas as pd
    from plania import api

    df = pd.DataFrame({"n": range(1000)})
    salida = api.tabla_json(df, limite=200)
    assert len(salida["filas"]) == 200
    assert salida["total"] == 1000, "sin el total, la pantalla no puede avisar que recortó"


def test_una_pagina_cualquiera_no_puede_leer_los_datos_del_cliente():
    """Escuchar sólo en 127.0.0.1 frena a la red, no al navegador del usuario.

    Si mientras Plania corre alguien abre una página cualquiera, el JavaScript
    de esa página puede pedirle a http://127.0.0.1:<puerto> igual que a
    cualquier servidor, y los puertos que prueba el lanzador son cinco fijos:
    escanearlos es trivial. Lo único que decide si esa página puede LEER la
    respuesta es el encabezado CORS.

    Con `allow_origins=["*"]`, que era lo que había, se comprobó que `/inicio`
    le entregaba la venta y el margen del cliente a un origen cualquiera, y que
    `/erp/guardar` le cambiaba la conexión a su base — de hecho la cambió al
    probarlo. El único origen que se acepta es el de la ventana (file://, que
    viaja como "null").
    """
    from fastapi.testclient import TestClient
    from plania import api

    c = TestClient(api.app)
    hostil = "https://sitio-cualquiera.example"

    r = c.get("/salud", headers={"Origin": hostil})
    assert r.headers.get("access-control-allow-origin") is None, \
        "la API le deja leer la respuesta a un sitio cualquiera"

    # Y la ventana, que carga desde file://, tiene que seguir entrando.
    r = c.get("/salud", headers={"Origin": "null"})
    assert r.headers.get("access-control-allow-origin") == "null", \
        "la ventana no puede leer su propia API: arrancaría en blanco"


def test_sin_el_token_de_la_corrida_la_api_no_contesta(monkeypatch):
    """Segunda capa, porque el origen solo no alcanza: un <iframe sandbox>
    también manda Origin "null". El token lo genera la ventana en cada
    arranque y una página ajena no lo puede adivinar."""
    from fastapi.testclient import TestClient
    from plania import api

    monkeypatch.setenv("PLANIA_API_TOKEN", "el-token-de-esta-corrida")
    c = TestClient(api.app)

    assert c.get("/inicio").status_code == 403, "contestó sin token"
    assert c.get("/inicio", headers={"X-Plania-Token": "otro"}).status_code == 403, \
        "aceptó un token equivocado"
    # Lo que de verdad duele: escribir. Cambiar el ERP apunta los datos del
    # cliente a donde quiera el atacante.
    assert c.post("/erp/guardar", json={"url": "sqlite:///robado.db"}).status_code == 403

    # La ventana, con el suyo, entra normal.
    bien = {"X-Plania-Token": "el-token-de-esta-corrida"}
    assert c.get("/inicio", headers=bien).status_code == 200

    # `/salud` queda abierta a propósito: es lo que la ventana consulta para
    # saber cuándo levantó el motor y no dice más que "sí, estoy". Si pidiera
    # token, un token mal pasado se vería como "el servidor no levantó".
    assert c.get("/salud").status_code == 200


def test_sin_token_configurado_la_api_sigue_abriendo(monkeypatch):
    """El arranque a mano para desarrollo (`uvicorn plania.api:app`) no tiene
    ventana que genere el token. Ahí no se exige, y la capa que queda es el
    origen — que ya bloquea a cualquier sitio real."""
    from fastapi.testclient import TestClient
    from plania import api

    monkeypatch.delenv("PLANIA_API_TOKEN", raising=False)
    assert TestClient(api.app).get("/salud").status_code == 200


def test_la_ventana_le_pasa_el_token_al_motor_y_a_la_interfaz():
    """El token sirve si las tres piezas están de acuerdo: la ventana lo
    genera, el motor lo espera y la interfaz lo manda. Si una se olvida, o no
    protege nada o la aplicación no abre."""
    import os

    for ventana in ("desktop/main.js", "desktop_owner/main.js"):
        main = open(os.path.join(RAIZ, *ventana.split("/")), encoding="utf-8").read()
        assert "crypto.randomBytes" in main, \
            f"{ventana} no genera un token nuevo por arranque"
        assert "PLANIA_API_TOKEN: TOKEN_API" in main, \
            f"{ventana} no le pasa el token al motor"
        assert "token: TOKEN_API" in main, \
            f"{ventana} no le pasa el token a la interfaz"

    base = open(os.path.join(RAIZ, "desktop", "renderer", "ui", "base.js"),
                encoding="utf-8").read()
    assert 'get("token")' in base, "la interfaz no lee el token de la query"
    assert "X-Plania-Token" in base, "la interfaz no manda el token"
    # Los exportes bajan con `fetch` aparte de `pedir`: si ese olvida el
    # token, los tres botones de descarga devuelven 403 y no se nota hasta
    # que alguien intenta bajar un informe.
    i = base.index("function Exportar")
    assert "cabecerasBase()" in base[i:i + 1200], \
        "la descarga de informes no manda el token: daría 403"


def test_la_api_local_no_es_el_backend_de_venta():
    """Son dos servidores distintos: éste corre en la máquina del cliente con
    SUS datos; `backend_venta` corre en internet con las licencias y el cobro.

    Lo que la API local no puede tener es la capacidad de **emitir** licencias
    ni de procesar pagos: eso le daría a cada cliente, en su propia máquina, el
    mecanismo para darse licencias solo.

    `/checkout` sí está, y es a propósito: no emite ni cobra nada, sólo le pide
    el link de pago al backend de venta y lo devuelve. Es un reenvío — el
    cliente podría llamar a ese backend por su cuenta igual, así que no agrega
    ninguna capacidad. Lo que importa es que la emisión siga estando del otro
    lado.
    """
    from plania import api

    rutas_api = _rutas_de(api.app)
    for prohibida in ("/webhooks/mercadopago", "/licencias/emitir",
                      "/licencias/trial", "/gateway/copiloto"):
        assert prohibida not in rutas_api, \
            f"{prohibida} es del backend de venta y no puede estar en la API local"

    # Y el reenvío tiene que ser eso: reenviar. Si algún día calculara precios
    # o firmara algo, deja de ser un reenvío.
    fuente = open(os.path.join(RAIZ, "plania", "api.py"), encoding="utf-8").read()
    for prohibido in ("jwt.encode", "PLANIA_LICENSE_SECRET", "mercadopago"):
        assert prohibido not in fuente, \
            f"la API local no puede usar {prohibido}: eso es del backend de venta"

    fuente = open(os.path.join(RAIZ, "plania", "api.py"), encoding="utf-8").read()
    assert "backend_venta" not in fuente.replace("`backend_venta`", "").replace(
        "backend_venta/", ""), "la API local no puede importar el backend de venta"


def test_el_copiloto_usa_el_formato_de_numeros_de_aca():
    """1.234.567,89 — punto para los miles, coma para los decimales.

    Python escribe al revés con `:,` y `:.1f`, así que las respuestas salían
    con formato de Estados Unidos ($1,430,318 · 24.5%) mientras la tabla de
    evidencia que va justo debajo, y todas las tarjetas del panel, usan el de
    acá. Dos formatos para el mismo importe en la misma pantalla, delante de
    un cliente.

    Se recorre el motor completo de intenciones, no una respuesta: cada rama
    arma su texto por su cuenta y alcanza con que una se olvide.
    """
    import re
    from plania import conectores, copiloto

    datos = conectores.cargar_datos()
    preguntas = [
        "¿qué ofertas armo esta semana?", "¿qué tengo que reponer?",
        "¿qué precios están dejando margen?", "¿cómo está el stock?",
        "¿qué zona vende más?", "¿quiénes son mis mejores clientes?",
        "¿qué clientes perdí?", "¿qué proveedor me conviene?",
        "¿cómo viene la venta?", "¿qué tipo de negocio compra más?",
    ]
    # Miles separados por coma (1,430,318) o decimales con punto (24.5%).
    miles_us = re.compile(r"\d{1,3}(?:,\d{3})+")
    decimal_us = re.compile(r"\d+\.\d+\s*%")

    problemas = []
    for pregunta in preguntas:
        texto = copiloto.responder(pregunta, datos)["respuesta"]
        hallados = miles_us.findall(texto) + decimal_us.findall(texto)
        if hallados:
            problemas.append((pregunta, hallados[:3]))
    assert not problemas, f"respuestas con formato de Estados Unidos: {problemas}"


def test_el_formateador_del_copiloto_da_vuelta_los_separadores():
    from plania import copiloto
    assert copiloto._m(1430318) == "1.430.318"
    assert copiloto._m(1430318.5, 2) == "1.430.318,50"
    assert copiloto._m(24.5, 1) == "24,5"
    assert copiloto._m(0) == "0"


def test_la_api_cubre_las_doce_pantallas():
    """Toda pantalla de la interfaz de escritorio tiene su endpoint. Si falta
    uno, esa pantalla queda en blanco en la máquina del cliente."""
    from plania import api
    rutas = _rutas_de(api.app)
    for ruta in ("/inicio", "/panel", "/stock", "/precios", "/zonas", "/ofertas",
                 "/clientes/inactivos", "/rutas", "/rutas/opciones", "/copiloto",
                 "/licencia", "/licencia/activar", "/planes", "/checkout",
                 "/config", "/erp/probar", "/erp/guardar", "/erp/estado",
                 "/exportar/{clave}.{formato}", "/salud"):
        assert ruta in rutas, f"falta el endpoint {ruta}"


def test_la_api_del_dueno_cubre_sus_seis_pantallas():
    """Las seis secciones del panel del dueño tienen endpoint propio.

    Es el equivalente del control de arriba para el otro programa: si falta
    uno, esa pantalla queda en blanco cuando el dueño abre su panel.
    """
    from plania import api
    rutas = _rutas_de(api.app)
    for ruta in ("/owner/negocio", "/owner/licencias", "/owner/licencias/emitir",
                 "/owner/rentabilidad", "/owner/mercado", "/owner/contenido",
                 "/owner/verificacion", "/owner/exportar/{clave}.{formato}"):
        assert ruta in rutas, f"falta el endpoint del panel del dueño {ruta}"


def test_el_tablero_del_dueno_responde_con_sus_numeros():
    c = _cliente_api()
    r = c.get("/owner/negocio")
    assert r.status_code == 200
    cuerpo = r.json()
    # Las cifras que justifican el panel: sin operación registrada dan cero,
    # pero tienen que estar todas.
    for clave in ("demos_entregadas", "clientes_pagos", "conversion_pct",
                  "mrr_usd", "arr_usd", "margen_bruto_pct", "clientes_en_riesgo"):
        assert clave in cuerpo["kpis"], f"falta el KPI {clave}"
    assert "ok" in cuerpo["integridad"]


def test_la_proyeccion_del_dueno_respeta_los_tres_controles():
    """Escenario, pauta y meses son los tres controles de esa pantalla: si la
    API los ignorara, mover un slider no cambiaría nada y no se notaría."""
    c = _cliente_api()
    r = c.get("/owner/rentabilidad?escenario=Base&ads=300&meses=6")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["escenario"]["nombre"] == "Base"
    assert cuerpo["detalle"]["total"] == 6, "el parámetro meses no llegó a la simulación"

    optimista = c.get("/owner/rentabilidad?escenario=Optimista&ads=300&meses=6").json()
    assert optimista["detalle"]["filas"] != cuerpo["detalle"]["filas"], \
        "cambiar de escenario devolvió la misma simulación"

    sin_pauta = c.get("/owner/rentabilidad?escenario=Base&ads=0&meses=6").json()
    assert sin_pauta["detalle"]["filas"] != cuerpo["detalle"]["filas"], \
        "la inversión en redes no movió la simulación"


def test_la_proyeccion_del_dueno_rechaza_un_escenario_que_no_existe():
    c = _cliente_api()
    r = c.get("/owner/rentabilidad?escenario=Fantasia")
    assert r.status_code == 400
    # El texto del detalle se muestra tal cual en pantalla: tiene que decir
    # cuáles son los escenarios válidos, no sólo que falló.
    assert "Base" in r.json()["detail"]


def test_la_sensibilidad_no_manda_una_columna_de_nombre_cambiante():
    """`negocio.sensibilidad` nombra su primera columna como la variable que
    simula. Si eso viaja tal cual, la interfaz tiene que adivinar cuál de las
    columnas es el valor simulado, y cambia según la tabla."""
    c = _cliente_api()
    cuerpo = c.get("/owner/mercado").json()
    for s in cuerpo["sensibilidades"]:
        assert s["variable"] in ("churn_mensual", "conv_demo_cliente")
        assert "valor" in s["tabla"]["columnas"], \
            f"la tabla de {s['variable']} no expone su valor con un nombre fijo"
        assert s["variable"] not in s["tabla"]["columnas"]


def test_emitir_una_licencia_a_mano_queda_asentada_en_el_log(tmp_path, monkeypatch):
    """Emitir de más y no acordarse es cómo se pierde de vista el MRR: el
    historial y el tablero salen del log, así que la emisión tiene que
    escribirlo. Si no, la licencia existe y el panel no la cuenta."""
    from plania import auditoria as pauditoria

    # `LOG_FILE` queda fijado en los defaults de registrar()/leer() al
    # importar, así que cambiar la variable del módulo no desvía nada: se
    # atan las dos funciones a un log de prueba para no escribir el real.
    log = str(tmp_path / "auditoria.log")
    real_registrar = pauditoria.registrar
    monkeypatch.setattr(pauditoria, "registrar",
                        lambda accion, detalle=None, **kw:
                        real_registrar(accion, detalle, archivo=log, **kw))

    c = _cliente_api()
    r = c.post("/owner/licencias/emitir",
               json={"cliente": "directa@plania.uy", "plan": "pro"})
    assert r.status_code == 200
    assert r.json()["token"], "no devolvió la licencia para copiar"

    asentado = pauditoria.leer(archivo=log)
    assert [e["accion"] for e in asentado] == ["licencia_emitida_manual"]
    assert asentado[0]["detalle"]["cliente"] == "directa@plania.uy"
    assert asentado[0]["detalle"]["plan"] == "pro"


def test_emitir_una_licencia_a_mano_valida_lo_que_recibe():
    c = _cliente_api()
    assert c.post("/owner/licencias/emitir",
                  json={"cliente": "   ", "plan": "pro"}).status_code == 400
    assert c.post("/owner/licencias/emitir",
                  json={"cliente": "x@y.uy", "plan": "inexistente"}).status_code == 400


def test_las_funciones_de_pago_se_controlan_en_el_servidor(monkeypatch):
    """Esconder el botón no alcanza: un endpoint abierto se llama igual.

    Rutas, copiloto y exportes son features de plan. El control tiene que
    estar en la API, no sólo en la pantalla — si no, cualquiera con la
    ventana abierta y la consola del navegador los usa gratis.
    """
    from fastapi.testclient import TestClient
    from plania import api, licencia

    monkeypatch.setattr(licencia, "tiene", lambda feature: False)
    c = TestClient(api.app)
    for metodo, ruta, cuerpo in [
        ("POST", "/rutas", {"vehiculos": 2}),
        ("POST", "/copiloto", {"pregunta": "hola"}),
        ("GET", "/exportar/completo.pdf", None),
    ]:
        r = c.request(metodo, ruta, json=cuerpo)
        assert r.status_code == 403, \
            f"{metodo} {ruta} devolvió {r.status_code} con la feature apagada"


def test_la_demo_vencida_bloquea_los_datos_reales_no_solo_rutas_copiloto_y_exportes(
        tmp_path, monkeypatch):
    """La API entera tiene que exigir licencia, no sólo las tres features de
    plan (rutas/copiloto/exportes).

    Comprobado ejecutando el pedido de verdad con una demo vencida: `/panel`,
    `/stock`, `/precios`, `/zonas`, `/ofertas`, `/clientes/inactivos`,
    `/rutas/opciones`, `/erp/probar`, `/erp/guardar` y `/erp/estado`
    devolvían 200 con la analítica y los datos completos del cliente,
    indefinidamente, sin ninguna licencia activa — la ventana Electron/React
    no tiene ningún bloqueo del lado cliente (a diferencia de `app/app.py`,
    que sí corta con `BLOQUEADA`). Un cliente podía dejar vencer la demo y
    seguir usando casi todo el producto gratis para siempre.

    `/inicio` queda afuera a propósito: sigue mostrando el mismo teaser de 4
    números que `app/app.py` deja ver en su página "Inicio" aun vencida.
    """
    import importlib
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    from plania import config as pconfig
    from plania import licencia
    importlib.reload(licencia)

    pconfig.guardar_extra(
        "DEMO_INICIO", (datetime.now(timezone.utc) - timedelta(days=10)).isoformat())
    assert licencia.estado()["modo"] == "vencida"

    from fastapi.testclient import TestClient
    from plania import api
    importlib.reload(api)
    api.invalidar_cache()
    c = TestClient(api.app)

    bloqueadas = [
        ("GET", "/panel", None), ("GET", "/stock", None), ("GET", "/precios", None),
        ("GET", "/zonas", None), ("GET", "/ofertas", None),
        ("GET", "/clientes/inactivos", None), ("GET", "/rutas/opciones", None),
        ("GET", "/erp/estado", None),
        ("POST", "/erp/probar", {"url": "sqlite:///nada.db"}),
        ("POST", "/erp/guardar", {"url": "sqlite:///nada.db"}),
    ]
    for metodo, ruta, cuerpo in bloqueadas:
        r = c.request(metodo, ruta, json=cuerpo)
        assert r.status_code == 402, \
            f"{metodo} {ruta} devolvió {r.status_code} con la demo vencida"
        assert "licencia" in r.json()["detail"].lower()

    # Lo que sigue andando: el teaser, y lo que hace falta para pagar.
    for libre in ("/salud", "/licencia", "/planes", "/inicio"):
        assert c.get(libre).status_code == 200, f"{libre} no tendría que bloquearse"


def test_una_licencia_activa_no_bloquea_nada(tmp_path, monkeypatch):
    """Contracara del test de arriba: el chequeo nuevo no puede bloquear a
    quien sí pagó."""
    import importlib
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    from plania import config as pconfig
    from plania import licencia
    importlib.reload(licencia)

    pconfig.guardar_extra("LICENCIA_JWT", "x.y.z")
    pconfig.guardar_extra("LICENCIA_CLAIMS", {
        "plan": "pro", "features": ["copiloto", "erp", "exportes", "rutas"],
        "expira": (datetime.now(timezone.utc) + timedelta(days=25)).timestamp(),
        "cliente": "cliente@empresa.uy"})
    pconfig.guardar_extra("LICENCIA_VERIFICADA_EL", datetime.now(timezone.utc).isoformat())
    assert licencia.estado()["modo"] == "licencia"

    from fastapi.testclient import TestClient
    from plania import api
    importlib.reload(api)
    api.invalidar_cache()
    c = TestClient(api.app)

    for ruta in ("/panel", "/stock", "/precios", "/zonas", "/ofertas",
                "/clientes/inactivos", "/rutas/opciones", "/erp/estado"):
        assert c.get(ruta).status_code == 200, f"{ruta} bloqueó a un cliente con licencia"


def test_la_api_no_deja_agrupar_por_una_columna_cualquiera():
    """`por_dimension` agrupa por el nombre de columna que reciba. Sin lista
    blanca, la pantalla —o cualquiera que llame al endpoint— podría pedir
    agrupar por una columna arbitraria de la base del cliente."""
    from fastapi.testclient import TestClient
    from plania import api

    c = TestClient(api.app)
    assert c.get("/zonas?dim=zona").status_code == 200
    for malicioso in ("costo", "cliente_id", "../etc", ""):
        assert c.get(f"/zonas?dim={malicioso}").status_code == 400, \
            f"dim={malicioso!r} tendría que rechazarse"


def test_la_configuracion_nunca_devuelve_el_valor_de_una_clave(tmp_path, monkeypatch):
    """La respuesta viaja por HTTP y queda en el historial de red de la
    ventana. Que la interfaz no pueda mostrar una clave guardada es a
    propósito.

    Corre contra una carpeta de configuración propia, no la compartida. La
    primera versión guardaba el secreto en la real y lo "borraba" con una
    cadena vacía — que `guardar` ignora, porque vacío significa "dejalo como
    está". El secreto quedaba en disco y hacía fallar, mil líneas más
    adelante, un test del gateway que encontraba una ANTHROPIC_API_KEY donde
    no tenía que haber ninguna. El síntoma (502 en vez de 503) no se parecía
    en nada a la causa.
    """
    import importlib

    from fastapi.testclient import TestClient
    from plania import config as pconfig

    monkeypatch.setenv("PLANIA_CONFIG_DIR", str(tmp_path))
    importlib.reload(pconfig)
    try:
        from plania import api
        importlib.reload(api)
        secreto = "sk-secretisimo-1234567890"
        pconfig.guardar({"ANTHROPIC_API_KEY": secreto})
        cuerpo = TestClient(api.app).get("/config").text
        assert secreto not in cuerpo, "la API devolvió una clave en texto plano"
    finally:
        # `CONFIG_DIR` se fija al importar: sin volver a cargar el módulo con
        # la variable ya deshecha, el resto de la sesión sigue leyendo de esta
        # carpeta temporal.
        monkeypatch.undo()
        importlib.reload(pconfig)
        from plania import api as _api
        importlib.reload(_api)
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_la_interfaz_de_escritorio_no_calcula_numeros_por_su_cuenta():
    """Las pantallas dibujan lo que devuelve la API. Si el JavaScript sumara,
    promediara o aplicara un descuento, habría dos fuentes de verdad y el día
    que difieran la diferencia se ve delante de un cliente.

    Se permite formatear (miles, plata, porcentaje) y recortar listas para
    mostrar; lo que no se permite es aritmética sobre los datos.

    Mira TODOS los archivos de interfaz, no sólo `pantallas.js`: cuando eran
    uno solo alcanzaba con nombrarlo, pero desde que hay piezas compartidas en
    `base.js` y un segundo programa con las suyas (`desktop_owner/`, el panel
    del dueño), un archivo fijo dejaba fuera de la red justamente al código
    nuevo — y mover una función de un archivo a otro la habría eximido sin
    que nadie lo notara.
    """
    import glob
    import os
    import re

    archivos = sorted(
        glob.glob(os.path.join(RAIZ, "desktop", "renderer", "**", "*.js"), recursive=True)
        + glob.glob(os.path.join(RAIZ, "desktop_owner", "renderer", "**", "*.js"),
                    recursive=True))
    assert len(archivos) >= 4, f"se esperaban más archivos de interfaz: {archivos}"
    fuente = "\n".join(open(a, encoding="utf-8").read() for a in archivos)

    # Multiplicar o dividir un campo que vino de la API: `r.capital * 1.21`.
    # Se mira `*` y `/` y no `+`, porque `+` es concatenación de texto en casi
    # todo el archivo y marcaría cada mensaje que arma la pantalla.
    #
    # La primera versión sólo miraba `f.<campo>` —el nombre que usan las filas
    # de tabla— y no detectaba un IVA inyectado en `r.capital_liberable`, que
    # es otra variable con datos de la API. Ahora cubre cualquier acceso a
    # propiedad.
    sospechosas = [x.strip() for x in
                   re.findall(r"\b[a-z]\w*\.\w+\s*[*/]\s*[\w.]", fuente)]

    # Acumuladores. Se exceptúan los que sólo miran `.length`: medir el texto
    # más largo para calcular el margen de un gráfico es maquetación, no una
    # cuenta sobre los datos del cliente. La primera versión de este control
    # no hacía la distinción y marcaba ese caso como si fuera un cálculo.
    for reduccion in re.findall(r"\.reduce\(\s*\(.{0,120}", fuente, re.S):
        if ".length" not in reduccion:
            sospechosas.append(reduccion.strip()[:60])

    assert not sospechosas, \
        f"la interfaz parece calcular en vez de mostrar: {sospechosas[:5]}"


# ---------------------------------------------------------------------------
# Avisos por correo al dueño
# ---------------------------------------------------------------------------
def _esperar_avisos(timeout=5.0):
    """Espera a que terminen los envíos en curso.

    Los avisos salen en un hilo para no retener el pedido que los disparó, así
    que un test que quiera mirar el resultado tiene que esperarlos. Y hay que
    esperarlos también ANTES de empezar otro test: un hilo que quedó corriendo
    escribe en el buzón del test siguiente, que es el que esté parcheado en
    ese momento.
    """
    import threading

    for h in threading.enumerate():
        if h.name == "plania-aviso":
            h.join(timeout)


def _correo_de_prueba(monkeypatch, romper=False):
    """Deja el SMTP configurado y devuelve la lista de mails que se enviaron.

    `romper=True` simula el servidor caído: es el caso que de verdad importa,
    porque ahí es donde un aviso mal hecho se lleva puesta una venta.
    """
    from backend_venta import avisos

    _esperar_avisos()

    for clave, valor in (("SMTP_HOST", "smtp.prueba.uy"),
                         ("SMTP_PORT", "587"),
                         ("SMTP_USER", "duenio@prueba.uy"),
                         ("SMTP_PASSWORD", "clave-de-aplicacion"),
                         ("SMTP_FROM", "duenio@prueba.uy"),
                         ("PLANIA_AVISOS_A", "duenio@prueba.uy")):
        monkeypatch.setenv(clave, valor)

    enviados = []

    class SmtpFalso:
        def __init__(self, host, puerto, timeout=None):
            if romper:
                raise OSError("conexión rechazada")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self, context=None):
            # Con la misma firma que el real: sin `context` el certificado del
            # servidor no se valida, y este doble tiene que poder notarlo.
            assert context is not None, "starttls sin contexto TLS"

        def login(self, usuario, clave):
            pass

        def send_message(self, mensaje):
            enviados.append(mensaje)

    monkeypatch.setattr(avisos.smtplib, "SMTP", SmtpFalso)
    avisos._ultimos.clear()
    avisos._enviados.clear()
    return enviados


def test_un_cliente_indeciso_no_manda_cinco_mails(monkeypatch):
    """Cinco clics en comprar son UNA intención de compra.

    Sin la ventana de repetidos el aviso se vuelve ruido en una semana, y un
    aviso que no se lee es lo mismo que no tenerlo. Lo que sí tiene que
    distinguir es a dos personas distintas, o a la misma cambiando de plan:
    agrupar de más sería peor que no agrupar, porque escondería una venta.
    """
    from backend_venta import avisos

    enviados = _correo_de_prueba(monkeypatch)

    for _ in range(5):
        avisos.aviso_intencion_de_compra("indeciso@empresa.uy", "pro", 590, bloqueante=True)
    assert len(enviados) == 1, \
        f"un solo cliente generó {len(enviados)} mails de intención"

    # El aviso tiene que servir para actuar: plan y monto, en el asunto.
    assert "pro" in enviados[0]["Subject"].lower()
    assert "590" in enviados[0]["Subject"]
    assert "indeciso@empresa.uy" in enviados[0].get_content()

    # Mismo interesado, otro plan: es información nueva.
    avisos.aviso_intencion_de_compra("indeciso@empresa.uy", "enterprise", 1490, bloqueante=True)
    assert len(enviados) == 2, "cambiar de plan no avisó"

    # Otra persona: no se puede agrupar con la anterior.
    avisos.aviso_intencion_de_compra("otro@empresa.uy", "pro", 590, bloqueante=True)
    assert len(enviados) == 3, "agrupó a dos interesados distintos en uno"

    # Y pasada la ventana vuelve a avisar: es una intención nueva, no la
    # misma. Se envejecen las marcas en vez de esperar media hora.
    from datetime import timedelta
    for clave in list(avisos._ultimos):
        avisos._ultimos[clave] -= avisos.VENTANA_REPETIDO + timedelta(minutes=1)
    avisos.aviso_intencion_de_compra("indeciso@empresa.uy", "pro", 590, bloqueante=True)
    assert len(enviados) == 4, "pasada la ventana siguió callado"


def test_un_correo_roto_no_puede_impedir_una_compra(monkeypatch):
    """El aviso es para el dueño, no para el comprador.

    Si el SMTP está caído, mal configurado o lento, el que paga tiene que
    poder comprar igual. Un `raise` acá significa un cliente que pagó y se
    quedó sin licencia por un problema del correo del dueño.
    """
    from backend_venta import avisos

    _correo_de_prueba(monkeypatch, romper=True)
    assert avisos.aviso_venta("cliente@empresa.uy", "pro", bloqueante=True) is False

    # Y tampoco si lo que falla es leer la configuración: `_configurado`
    # consulta el keyring del sistema, que puede no existir en el servidor.
    def explota():
        raise RuntimeError("keyring no disponible")

    monkeypatch.setattr(avisos, "_configurado", explota)
    avisos._ultimos.clear()
    avisos._enviados.clear()
    assert avisos.aviso_venta("cliente@empresa.uy", "pro", bloqueante=True) is False


def test_sin_smtp_configurado_el_aviso_se_calla_y_sigue(monkeypatch):
    """Una instalación sin correo configurado es lo normal, no un error."""
    from backend_venta import avisos

    for clave in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
                  "SMTP_FROM", "PLANIA_AVISOS_A"):
        monkeypatch.delenv(clave, raising=False)
    avisos._ultimos.clear()
    avisos._enviados.clear()

    assert avisos._configurado() is None
    assert avisos.aviso_pedido_de_demo("x@y.uy", "X", "Y", "Uruguay",
                                       bloqueante=True) is False


def test_una_venta_avisa_una_sola_vez_aunque_el_webhook_reintente(monkeypatch):
    """MercadoPago reintenta el webhook y el comprador además pide su licencia
    desde la página de gracias. Los dos caminos pasan por `_emitir_por_pago`.

    Sin la guarda, una sola venta manda varios mails y el aviso deja de
    significar "vendiste": pasa a significar "algo pasó". Se comprueba contra
    la función real, no contra el aviso suelto, porque el que decide si es la
    primera vez es el registro del pago, no el correo.
    """
    from backend_venta import avisos
    from backend_venta.app import _emitir_por_pago

    enviados = _correo_de_prueba(monkeypatch)

    payment_id = f"MP-{uuid.uuid4().hex[:12]}"
    pago = {"status": "approved",
            "metadata": {"plan": "pro", "email": "compro@distribuidora.uy"}}

    primera = _emitir_por_pago(payment_id, pago)
    assert primera["licencia"], "no emitió la licencia"
    _esperar_avisos()
    assert len(enviados) == 1, "la venta no avisó"
    assert "VENTA" in enviados[0]["Subject"]

    # El webhook reintenta y el comprador pregunta: misma licencia, sin
    # mail nuevo. Se vacía la ventana de repetidos a propósito, para que lo
    # que frene el segundo mail sea el registro del pago y no el antirrebote.
    avisos._ultimos.clear()
    segunda = _emitir_por_pago(payment_id, pago)
    assert segunda["licencia"] == primera["licencia"], \
        "un reintento emitió una licencia distinta"
    _esperar_avisos()
    assert len(enviados) == 1, \
        f"una sola venta mandó {len(enviados)} mails de venta"


def test_la_licencia_sale_aunque_el_aviso_falle(monkeypatch):
    """El orden importa: primero se emite, después se avisa.

    Si el correo se cuelga o revienta, el comprador ya tiene su licencia
    guardada. Es la contracara del test de arriba, mirada desde la venta.
    """
    from backend_venta import pagos
    from backend_venta.app import _emitir_por_pago

    _correo_de_prueba(monkeypatch, romper=True)

    payment_id = f"MP-{uuid.uuid4().hex[:12]}"
    emitido = _emitir_por_pago(
        payment_id, {"status": "approved",
                     "metadata": {"plan": "starter",
                                  "email": "paga@almacen.uy"}})
    assert emitido["licencia"], "el correo roto se llevó puesta la licencia"
    assert pagos.buscar(payment_id)["licencia"] == emitido["licencia"], \
        "la venta no quedó registrada"


def test_el_aviso_no_deja_la_clave_del_correo_en_el_log(monkeypatch, caplog):
    """El fallo del SMTP se registra con traza, y la traza no puede llevarse
    la contraseña de aplicación al log de Render, que es un panel web."""
    import logging

    from backend_venta import avisos

    _correo_de_prueba(monkeypatch, romper=True)
    with caplog.at_level(logging.DEBUG):
        avisos.aviso_venta("cliente@empresa.uy", "pro", bloqueante=True)
    assert "clave-de-aplicacion" not in caplog.text


def test_registrar_un_pago_dice_quien_lo_registro_de_verdad(tmp_path):
    """"¿Es la primera vez?" lo tiene que contestar la base, no una comparación.

    El código comparaba la licencia recién emitida contra la guardada para
    saber si el pago era nuevo. Falla justo cuando importa: el JWT se firma
    sobre `iat` en SEGUNDOS, así que dos llamadas del mismo pago dentro del
    mismo segundo —un reintento del webhook de MercadoPago, que llega
    enseguida— generan el mismo token byte a byte y las dos se creen la
    primera. Lo que cuelga de esa respuesta (el asiento en la auditoría, el
    aviso de venta) se duplicaba.
    """
    from backend_venta import licencias as lic
    from backend_venta import pagos

    db = str(tmp_path / "pagos.db")
    payment_id = f"MP-{uuid.uuid4().hex[:12]}"

    # El escenario exacto que rompía: la MISMA licencia, emitida dos veces
    # dentro del mismo segundo, para el mismo pago.
    token = lic.emitir_licencia("compro@empresa.uy", "pro")
    assert token == lic.emitir_licencia("compro@empresa.uy", "pro"), \
        "el JWT dejó de ser determinista; este test ya no prueba el caso"

    primera = pagos.registrar(payment_id, "compro@empresa.uy", "pro",
                              token, "token-descarga", db_path=db)
    assert primera["nuevo"] is True, "no reconoció el alta como nueva"

    segunda = pagos.registrar(payment_id, "compro@empresa.uy", "pro",
                              token, "token-descarga", db_path=db)
    assert segunda["nuevo"] is False, \
        "el reintento se creyó la primera notificación del pago"
    assert segunda["licencia"] == primera["licencia"]
    assert pagos.total(db_path=db) == 1, "el reintento duplicó el pago"


def test_el_aviso_no_bloquea_el_pedido_que_lo_dispara(monkeypatch):
    """`smtplib` es bloqueante y los tres llamadores son `async def` sobre un
    único proceso de uvicorn. Esperar al SMTP ahí adentro no frena sólo a quien
    disparó el aviso: frena a todos, incluido el webhook que le tiene que
    contestar 200 a MercadoPago antes de que reintente.

    El caso real es un SMTP con el puerto de salida filtrado —lo habitual en
    planes gratuitos—, donde cada operación se come el timeout entero.
    """
    import threading
    import time

    from backend_venta import avisos

    _correo_de_prueba(monkeypatch)
    colgado = threading.Event()

    class SmtpColgado:
        def __init__(self, host, puerto, timeout=None):
            colgado.wait(30)      # el servidor que nunca contesta

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(avisos.smtplib, "SMTP", SmtpColgado)
    try:
        arranque = time.monotonic()
        avisos.aviso_venta("compro@empresa.uy", "pro", "MP-1")
        demora = time.monotonic() - arranque
        assert demora < 1.0, \
            f"el aviso retuvo el pedido {demora:.1f}s esperando al SMTP"
    finally:
        colgado.set()


def test_un_smtp_caido_un_rato_no_se_come_el_aviso_para_siempre(monkeypatch):
    """La marca de repetido se pone antes de enviar para que dos clics no
    larguen dos hilos, pero si el envío falla hay que poder reintentar.

    Dándola por buena sin haber enviado nada, un SMTP caído veinte segundos se
    comía el aviso de una venta para SIEMPRE: la guarda `nuevo` de
    `_emitir_por_pago` es de una sola vez, así que el reintento del webhook ya
    no vuelve a llamar al aviso.
    """
    from backend_venta import avisos

    _correo_de_prueba(monkeypatch, romper=True)
    assert avisos.aviso_venta("compro@empresa.uy", "pro", "MP-9",
                              bloqueante=True) is False
    assert not avisos._ultimos, \
        "el envío falló y la clave quedó marcada: el aviso se perdió"

    # Con el servidor sano de nuevo, el mismo aviso sale.
    enviados = _correo_de_prueba(monkeypatch)
    assert avisos.aviso_venta("compro@empresa.uy", "pro", "MP-9",
                              bloqueante=True) is True
    assert len(enviados) == 1


def test_dos_compras_del_mismo_cliente_avisan_las_dos(monkeypatch):
    """Un distribuidor que compra una licencia por sucursal hace dos compras
    reales del mismo plan con el mismo email de facturación.

    Agrupando sólo por email y plan, la segunda venta se descartaba como si
    fuera un reintento. Esconder una venta es peor que mandar un mail de más,
    que es justo lo que el antirrebote dice querer evitar.
    """
    from backend_venta import avisos

    enviados = _correo_de_prueba(monkeypatch)
    avisos.aviso_venta("central@distribuidora.uy", "pro", "MP-111",
                       bloqueante=True)
    avisos.aviso_venta("central@distribuidora.uy", "pro", "MP-222",
                       bloqueante=True)
    assert len(enviados) == 2, "la segunda sucursal no avisó"

    # Y el reintento de la MISMA compra sigue agrupado.
    avisos.aviso_venta("central@distribuidora.uy", "pro", "MP-222",
                       bloqueante=True)
    assert len(enviados) == 2, "un reintento del mismo pago avisó dos veces"


def test_un_salto_de_linea_en_el_formulario_no_mata_el_aviso(monkeypatch):
    """Pegar la razón social desde un PDF o una firma de mail trae saltos de
    línea en el medio, y el módulo `email` los rechaza con ValueError.

    Sin sanear, el pedido quedaba guardado y el aviso no salía nunca, en
    silencio. De paso cierra la inyección de cabeceras.
    """
    from backend_venta import avisos

    enviados = _correo_de_prueba(monkeypatch)
    assert avisos.aviso_pedido_de_demo(
        "juan@acme.uy", "Juan Pérez", "Distribuidora ACME\nS.R.L.",
        "Uruguay\nSur", bloqueante=True) is True, \
        "un salto de línea en el formulario dejó al dueño sin aviso"

    asunto = enviados[0]["Subject"]
    assert "\n" not in asunto and "\r" not in asunto
    assert "ACME" in asunto and "S.R.L." in asunto

    # Inyección de cabeceras: no puede aparecer un destinatario nuevo.
    avisos._ultimos.clear()
    avisos.aviso_pedido_de_demo(
        "otro@acme.uy", "X", "ACME\nBcc: atacante@ajeno.com", "Uruguay",
        bloqueante=True)
    assert enviados[1].get_all("Bcc") is None, "se coló un Bcc por el asunto"
    assert enviados[1]["To"] == "duenio@prueba.uy"


def test_el_aviso_valida_el_certificado_del_servidor_de_correo(monkeypatch):
    """`starttls()` sin contexto usa `ssl._create_stdlib_context()`, que cifra
    pero NO valida el certificado (`check_hostname=False`, `verify_mode=0`).

    Quien esté en el camino de red responde el STARTTLS con un certificado
    propio y la línea siguiente le entrega la clave de aplicación de Gmail.
    """
    import ssl

    from backend_venta import avisos

    _correo_de_prueba(monkeypatch)
    contextos = []

    class SmtpQueMiraElContexto:
        def __init__(self, host, puerto, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self, context=None):
            contextos.append(context)

        def login(self, usuario, clave):
            pass

        def send_message(self, mensaje):
            pass

    monkeypatch.setattr(avisos.smtplib, "SMTP", SmtpQueMiraElContexto)
    avisos.aviso_venta("x@y.uy", "pro", "MP-tls", bloqueante=True)

    assert contextos and contextos[0] is not None, \
        "starttls sin contexto: el certificado del servidor no se valida"
    ctx = contextos[0]
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_sin_correo_configurado_no_van_los_datos_del_prospecto_al_log(monkeypatch, caplog):
    """Hoy nadie tiene SMTP cargado, así que ESTA es la rama que corre siempre.

    El log va al panel web de Render, con otra retención y otros accesos que
    la base. Nombre, empresa, país, email y el mensaje libre ya quedaron
    guardados donde corresponde; no tienen por qué estar además ahí.
    """
    import logging

    from backend_venta import avisos

    for clave in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
                  "SMTP_FROM", "PLANIA_AVISOS_A"):
        monkeypatch.delenv(clave, raising=False)
    avisos._ultimos.clear()
    avisos._enviados.clear()

    with caplog.at_level(logging.DEBUG):
        avisos.aviso_pedido_de_demo(
            "juan@distribuidora.uy", "Juan Pérez", "Distribuidora del Este",
            "Uruguay", "Tenemos Zureo y 12 camiones.", bloqueante=True)

    for dato in ("juan@distribuidora.uy", "Juan Pérez",
                 "Distribuidora del Este", "Zureo"):
        assert dato not in caplog.text, \
            f"los datos del prospecto quedaron en el log de Render: {dato!r}"


def test_el_aviso_no_lee_el_correo_corporativo_del_cliente(monkeypatch):
    """Las claves SMTP_* de `plania/config.py` son OTRA cosa: las edita el
    cliente desde la pestaña Configuración y describen su correo corporativo
    ("ventas@tuempresa.com").

    Cayendo a esa configuración, en una máquina donde corran la app y el
    backend juntos —los dos comandos están documentados— los avisos de venta
    de Plania saldrían por el servidor de correo del distribuidor, con el
    email del prospecto adentro.
    """
    from backend_venta import avisos

    for clave in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
                  "SMTP_FROM", "PLANIA_AVISOS_A"):
        monkeypatch.delenv(clave, raising=False)

    monkeypatch.setattr(
        avisos, "_configurado",
        lambda: (_ for _ in ()).throw(AssertionError("no debería llamarse")),
        raising=False)
    # Con el entorno vacío no hay configuración posible: si el módulo mirara
    # el almacén del cliente, acá encontraría credenciales.
    monkeypatch.undo()
    for clave in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(clave, raising=False)
    pconfig.guardar_extra("SMTP_HOST", "smtp.sudistribuidora.com")
    pconfig.guardar_extra("SMTP_USER", "ventas@sudistribuidora.com")
    pconfig.guardar_extra("SMTP_PASSWORD", "clave-del-cliente")
    try:
        assert avisos._configurado() is None, \
            "el backend de venta tomó las credenciales de correo del cliente"
    finally:
        for clave in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
            pconfig.guardar_extra(clave, "")

    # Y el módulo no importa la configuración del cliente en absoluto.
    fuente = open(os.path.join(RAIZ, "backend_venta", "avisos.py"),
                  encoding="utf-8").read()
    importa = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", fuente, re.MULTILINE)
    assert not [m for m in importa if m.split(".")[0] == "plania"], \
        f"avisos.py volvió a depender de la configuración del cliente: {importa}"


def test_un_script_contra_checkout_no_quema_la_cuota_diaria_de_gmail(monkeypatch):
    """El antirrebote agrupa por clave, así que no frena a quien varía el dato:
    cada email distinto es una clave distinta.

    Sin tope, un script contra `/checkout` quema las 500 entregas diarias de
    una app password en veinte minutos, y el aviso que se pierde después es el
    de la venta de verdad.
    """
    from backend_venta import avisos

    enviados = _correo_de_prueba(monkeypatch)
    for i in range(avisos.LIMITE_POR_HORA + 25):
        avisos.aviso_intencion_de_compra(f"bot{i}@ajeno.com", "pro", 590,
                                         bloqueante=True)

    assert len(enviados) == avisos.LIMITE_POR_HORA, \
        f"se mandaron {len(enviados)} mails: el tope por hora no frenó nada"
