# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Una sola fuente de datos para toda la app
==================================================
Caso reportado: «al elegir dataset por archivo o SQL debería aplicarse a todas
las pestañas y desaparecer los datos demo». Estos tests fijan que:

  - con una fuente del usuario elegida, TODAS las bocas que leen datos (motor,
    API, panel del dueño, contenido, la app) leen esa fuente y no la demo;
  - no hay mezcla: ninguna fila de la demo aparece junto a las del usuario;
  - volver a la demo la trae de vuelta, también en el entorno del proceso;
  - la URL que `config.aplicar()` copió al entorno sigue a la config en vez de
    quedarse clavada en la fuente vieja.

Todos los datos son sintéticos, armados acá mismo. La config se simula en
memoria: ningún test toca la config real de la máquina.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app", "app.py")

SKUS_USUARIO = ["USR-001", "USR-002", "USR-003", "USR-004"]


@pytest.fixture
def config_en_memoria(monkeypatch):
    """Config simulada: `leer_extra`/`guardar_extra`/`cargar` sobre un dict."""
    from plania import config as pconfig
    memoria: dict = {}
    monkeypatch.setattr(pconfig, "cargar", lambda: dict(memoria))
    monkeypatch.setattr(pconfig, "leer_extra",
                        lambda clave, default=None: memoria.get(clave, default))
    monkeypatch.setattr(pconfig, "guardar_extra",
                        lambda clave, valor: memoria.__setitem__(clave, valor))
    monkeypatch.setattr(pconfig, "COPIADAS_AL_ENTORNO", {})
    # setenv + delenv: así monkeypatch anota el estado original y lo restaura
    # aunque un test deje ERP_DB_URL puesta por `aplicar()`.
    monkeypatch.setenv("ERP_DB_URL", "")
    monkeypatch.delenv("ERP_DB_URL")
    return memoria


@pytest.fixture
def base_del_usuario(tmp_path):
    """Lo que deja la pantalla Conectar ERP al subir archivos: una SQLite
    `erp_archivos.db` con datos sintéticos que no se parecen a la demo."""
    from plania import conectores
    hoy = pd.Timestamp.today().normalize()
    productos = pd.DataFrame({
        "sku": SKUS_USUARIO,
        "nombre": ["Tornillo 6mm", "Tuerca 6mm", "Arandela", "Taladro"],
        "categoria": ["Bulonería", "Bulonería", "Bulonería", "Herramientas"],
        "precio": [10.0, 8.0, 2.0, 3500.0], "costo": [6.0, 5.0, 1.0, 2500.0],
        "stock": [500, 0, 900, 3], "stock_min": [100, 50, 100, 2],
    })
    clientes = pd.DataFrame({
        "cliente_id": ["C-A", "C-B", "C-C"],
        "nombre": ["Ferretería A", "Ferretería B", "Obra C"],
        "tipo_negocio": ["Ferretería", "Ferretería", "Constructora"],
        "departamento": ["Canelones", "Canelones", "Maldonado"],
        "zona": ["Norte", "Sur", "Este"],
        "lat": [-34.52, -34.55, -34.90], "lon": [-56.28, -56.20, -54.95],
    })
    filas = []
    for i in range(60):
        filas.append({"venta_id": f"V{i}", "fecha": hoy - pd.Timedelta(days=i * 3),
                      "sku": SKUS_USUARIO[i % 4], "cliente_id": ["C-A", "C-B", "C-C"][i % 3],
                      "cantidad": 1 + i % 5})
    ventas = pd.DataFrame(filas)
    datos = {e: conectores.normalizar(df, e) for e, df in
             (("productos", productos), ("clientes", clientes), ("ventas", ventas))}
    return conectores.guardar_como_base(datos, str(tmp_path / "erp_archivos.db"))


def _skus(datos: dict) -> set:
    return set(datos["productos"]["sku"].astype(str))


# ---------------------------------------------------------------------------
# El resolvedor
# ---------------------------------------------------------------------------
def test_sin_fuente_elegida_es_la_demo(config_en_memoria):
    from plania import fuente
    f = fuente.resolver()
    assert f.es_demo and f.origen == "demo"
    assert f.url == fuente.url_demo()


def test_con_archivos_subidos_toda_boca_lee_esos_y_no_la_demo(config_en_memoria,
                                                               base_del_usuario):
    from plania import api, conectores, contenido, fuente

    activa = fuente.usar(base_del_usuario, nombre="productos.csv, ventas.csv")
    assert activa.tipo == "archivo" and not activa.es_demo
    assert activa.nombre == "productos.csv, ventas.csv"

    # Cada consumidor, sin pasarle URL: todos tienen que resolver lo mismo.
    api.invalidar_cache()
    try:
        consumidores = {
            "fuente.cargar": fuente.cargar(),
            "conectores.cargar_datos": conectores.cargar_datos(),
            "api._datos": api._datos(),
        }
    finally:
        api.invalidar_cache()
    for nombre, datos in consumidores.items():
        # Igualdad exacta: ni un SKU de la demo mezclado con los del usuario.
        assert _skus(datos) == set(SKUS_USUARIO), nombre
        assert len(datos["clientes"]) == 3, nombre
    assert contenido._sobre_datos_demo() is False


def test_volver_a_la_demo_la_trae_de_vuelta(config_en_memoria, base_del_usuario):
    from plania import conectores, fuente
    if not os.path.exists(fuente.ruta_demo()):
        pytest.skip("sin data/erp_demo.db")
    demo = conectores.cargar_datos(url=fuente.url_demo())

    fuente.usar(base_del_usuario)
    assert _skus(conectores.cargar_datos()) == set(SKUS_USUARIO)

    activa = fuente.volver_a_demo()
    assert activa.es_demo
    vuelta = conectores.cargar_datos()
    assert _skus(vuelta) == _skus(demo)
    assert not _skus(vuelta) & set(SKUS_USUARIO)


def test_la_copia_de_aplicar_en_el_entorno_sigue_a_la_config(config_en_memoria,
                                                             base_del_usuario,
                                                             monkeypatch):
    """`config.aplicar()` copia ERP_DB_URL al entorno al arrancar. Antes esa
    copia quedaba fija: el motor leía el entorno primero y seguía en la
    fuente vieja aunque el usuario hubiera elegido otra o vuelto a la demo."""
    from plania import config as pconfig
    from plania import fuente
    vieja = "sqlite:////no/existe/erp_vieja.db"
    config_en_memoria["ERP_DB_URL"] = vieja
    pconfig.aplicar()
    assert os.environ["ERP_DB_URL"] == vieja and pconfig.viene_de_la_config("ERP_DB_URL")

    fuente.usar(base_del_usuario)
    assert os.environ["ERP_DB_URL"] == base_del_usuario
    assert fuente.resolver().url == base_del_usuario

    fuente.volver_a_demo()
    assert "ERP_DB_URL" not in os.environ
    assert fuente.resolver().es_demo


def test_una_variable_de_entorno_puesta_a_proposito_manda(config_en_memoria,
                                                          base_del_usuario, monkeypatch):
    from plania import fuente
    monkeypatch.setenv("ERP_DB_URL", base_del_usuario)
    f = fuente.resolver()
    assert f.fijada_por_entorno and not f.es_demo
    # «Volver a la demo» no puede pisar lo que fijó la instalación, y lo dice.
    assert fuente.volver_a_demo().fijada_por_entorno


def test_la_sesion_gana_y_el_nombre_no_muestra_la_contrasena(config_en_memoria):
    from plania import fuente
    f = fuente.resolver("postgresql://ventas:secreto123@db.local:5432/erp")
    assert f.tipo == "sql" and f.origen == "sesion"
    assert "secreto123" not in f.nombre
    assert "db.local" in f.nombre and "erp" in f.nombre


def test_la_clave_cambia_si_se_resuben_los_archivos(config_en_memoria, base_del_usuario):
    """Misma URL, otro contenido: la app tiene que invalidar caché, filtros y
    el historial del copiloto."""
    from plania import conectores, fuente
    antes = fuente.usar(base_del_usuario).clave
    datos = conectores.cargar_datos(url=base_del_usuario)
    datos["productos"] = datos["productos"].head(2)
    ruta = base_del_usuario[len("sqlite:///"):]
    conectores.guardar_como_base(datos, ruta)
    # Por si el sistema de archivos tiene poca resolución de mtime.
    os.utime(ruta, ns=(os.stat(ruta).st_atime_ns, os.stat(ruta).st_mtime_ns + 10**9))
    assert fuente.resolver().clave != antes


# ---------------------------------------------------------------------------
# La app, corrida de verdad
# ---------------------------------------------------------------------------
def test_la_app_muestra_la_fuente_del_usuario_en_todas_las_pestanas(
        config_en_memoria, base_del_usuario, monkeypatch):
    """Con archivos subidos, cada pestaña con datos corre sobre ellos, la
    barra lateral dice cuál es la fuente y ofrece volver a la demo; al
    apretar el botón, la demo vuelve."""
    from streamlit.testing.v1 import AppTest

    from plania import fuente, i18n, licencia
    monkeypatch.setattr(licencia, "eula_aceptada", lambda: True)
    monkeypatch.setattr(licencia, "estado", lambda: {
        "modo": "demo", "dias_restantes": 7, "horas_restantes": 100})
    monkeypatch.setattr(licencia, "tiene", lambda _funcion: True)
    monkeypatch.syspath_prepend(RAIZ)

    fuente.usar(base_del_usuario, nombre="mis_productos.csv")
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    def _texto_sidebar() -> str:
        return " ".join(c.value for c in at.sidebar.caption)

    etiqueta_demo = i18n.t("fuente.base_demo")
    for pagina in ("inicio", "panel_ejecutivo", "stock", "precios", "zonas",
                   "rutas", "ofertas", "copiloto"):
        at.sidebar.radio[0].set_value(i18n.t(f"menu.{pagina}")).run()
        assert not at.exception, (pagina, [e.value for e in at.exception])
        assert "mis_productos.csv" in _texto_sidebar(), pagina
        assert etiqueta_demo not in _texto_sidebar(), pagina

    # En Stock, la tabla completa sólo trae los SKU del usuario.
    at.sidebar.radio[0].set_value(i18n.t("menu.stock")).run()
    tablas = [df.value for df in at.dataframe]
    assert tablas, "Stock no dibujó tablas"
    columna_sku = i18n.t("columnas.sku")
    vistos = set()
    for df in tablas:
        if columna_sku in df.columns:
            vistos |= set(df[columna_sku].astype(str))
    assert vistos and vistos <= set(SKUS_USUARIO), vistos

    volver = [b for b in at.sidebar.button if b.label == i18n.t("fuente.volver_demo")]
    assert volver, "falta el botón para volver a la demo en la barra lateral"
    volver[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert fuente.resolver().es_demo
    assert etiqueta_demo in _texto_sidebar()
