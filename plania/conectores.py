"""
Plania · Conector universal a ERPs y bases de datos
===================================================
El diferenciador central: Plania no obliga a migrar nada — se conecta a la
base que el cliente YA tiene (PostgreSQL, MySQL/MariaDB, SQL Server, Oracle,
SQLite vía SQLAlchemy; o CSV/Excel exportados del ERP) y **auto-detecta** el
mapeo de columnas hacia el esquema canónico de Plania.

Esquema canónico (lo que consumen analítica, sugerencias, copiloto y rutas):
  productos: sku, nombre, categoria, proveedor, costo, precio, stock,
             stock_min, lead_time_dias
  clientes:  cliente_id, nombre, tipo_negocio, departamento, zona, lat, lon
  ventas:    venta_id, fecha, cliente_id, sku, cantidad, precio_unit, costo_unit

Solo `sku/nombre/precio` (productos), `cliente_id` (clientes) y
`fecha/sku/cantidad` (ventas) son obligatorios; el resto degrada con
defaults razonables. Los presets cubren los nombres de columna típicos de
los ERPs más usados en Uruguay/LATAM (Zureo, Memory, Tango, Bejerman, Odoo,
SAP Business One) y el autodetector cubre el resto por sinónimos.
"""
from __future__ import annotations

import os
import re
import unicodedata

import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

# ---------------------------------------------------------------------------
# Sinónimos: columna canónica -> nombres con los que aparece en ERPs reales
# ---------------------------------------------------------------------------
SINONIMOS = {
    "productos": {
        "sku": ["sku", "cod_articulo", "codigo", "cod_art", "codart", "id_articulo",
                "articulo_id", "item", "itemcode", "cod_producto", "codigo_articulo",
                "codigo_producto", "id_producto", "default_code"],
        "nombre": ["nombre", "descripcion", "detalle", "articulo", "producto",
                   "desc_articulo", "itemname", "descripcion_articulo", "name"],
        "categoria": ["categoria", "rubro", "familia", "grupo", "linea", "seccion",
                      "categ_id", "itmsgrpnam", "tipo_articulo"],
        "proveedor": ["proveedor", "cod_proveedor", "supplier", "cardname_prov",
                      "fabricante", "marca_proveedor"],
        "costo": ["costo", "costo_unitario", "precio_costo", "costo_reposicion",
                  "avgprice", "standard_price", "costo_promedio", "ultimo_costo"],
        "precio": ["precio", "precio_venta", "pvp", "precio_lista", "precio_publico",
                   "precio_unitario_venta", "list_price", "price", "precio1"],
        "stock": ["stock", "stock_actual", "existencia", "existencias", "onhand",
                  "qty_available", "cantidad_stock", "saldo_stock", "disponible"],
        "stock_min": ["stock_min", "stock_minimo", "minimo", "punto_pedido",
                      "reorder_point", "min_qty", "stock_seguridad"],
        "lead_time_dias": ["lead_time_dias", "lead_time", "dias_entrega",
                           "plazo_entrega", "dias_reposicion"],
    },
    "clientes": {
        "cliente_id": ["cliente_id", "cod_cliente", "codigo_cliente", "id_cliente",
                       "cardcode", "nro_cliente", "cliente", "partner_id", "cuenta"],
        "nombre": ["nombre", "razon_social", "cliente_nombre", "cardname",
                   "denominacion", "name", "razonsocial"],
        "tipo_negocio": ["tipo_negocio", "giro", "rubro_cliente", "canal",
                         "segmento", "tipo_cliente", "actividad", "categoria_cliente"],
        "departamento": ["departamento", "depto", "provincia", "estado", "region",
                         "state", "dpto"],
        "zona": ["zona", "barrio", "localidad", "ciudad", "city", "zona_reparto",
                 "ruta", "distrito"],
        "lat": ["lat", "latitud", "latitude", "coord_lat", "gps_lat"],
        "lon": ["lon", "lng", "longitud", "longitude", "coord_lon", "gps_lon"],
    },
    "ventas": {
        "venta_id": ["venta_id", "nro_comprobante", "comprobante", "factura",
                     "nro_factura", "docentry", "id_venta", "documento", "move_id"],
        "fecha": ["fecha", "fecha_emision", "fecha_venta", "fecha_comprobante",
                  "docdate", "emision", "date", "fecha_factura"],
        "cliente_id": ["cliente_id", "cod_cliente", "cardcode", "id_cliente",
                       "cliente", "nro_cliente", "partner_id"],
        "sku": ["sku", "cod_articulo", "codigo", "itemcode", "id_articulo",
                "articulo", "cod_producto", "product_id"],
        "cantidad": ["cantidad", "unidades", "qty", "quantity", "cant",
                     "cantidad_vendida", "product_uom_qty"],
        "precio_unit": ["precio_unit", "precio_unitario", "precio", "pu",
                        "price_unit", "precio_venta", "importe_unitario"],
        "costo_unit": ["costo_unit", "costo_unitario", "costo", "stockprice",
                       "costo_venta"],
    },
}

OBLIGATORIAS = {
    "productos": ["sku", "nombre", "precio"],
    "clientes": ["cliente_id"],
    "ventas": ["fecha", "sku", "cantidad"],
}

# Nombres de tabla típicos por entidad, para autodescubrir en la base conectada.
TABLAS_CANDIDATAS = {
    "productos": ["productos", "articulos", "items", "oitm", "product_template",
                  "stock", "product_product", "articulo", "producto"],
    "clientes": ["clientes", "ocrd", "res_partner", "cliente", "cuentas",
                 "customers", "socios"],
    "ventas": ["ventas", "inv1", "facturas_detalle", "detalle_ventas",
               "sale_order_line", "account_move_line", "movimientos", "venta",
               "comprobantes_detalle", "lineas_venta"],
}


def _normalizar_nombre(c: str) -> str:
    s = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode()
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def autodetectar_mapeo(df: pd.DataFrame, entidad: str) -> dict:
    """Devuelve {col_origen: col_canonica} por matcheo de sinónimos."""
    sin = SINONIMOS[entidad]
    cols = {_normalizar_nombre(c): c for c in df.columns}
    mapeo, usadas = {}, set()
    for canonica, candidatos in sin.items():
        for cand in candidatos:
            if cand in cols and cols[cand] not in usadas:
                mapeo[cols[cand]] = canonica
                usadas.add(cols[cand])
                break
    return mapeo


def normalizar(df: pd.DataFrame, entidad: str, mapeo: dict | None = None) -> pd.DataFrame:
    """Renombra al esquema canónico, valida obligatorias y completa defaults."""
    mapeo = mapeo or autodetectar_mapeo(df, entidad)
    out = df.rename(columns=mapeo).copy()
    faltan = [c for c in OBLIGATORIAS[entidad] if c not in out.columns]
    if faltan:
        raise ValueError(
            f"No pude mapear columnas obligatorias de {entidad}: {faltan}. "
            f"Columnas disponibles: {list(df.columns)}. "
            "Definí el mapeo manual en la pantalla 'Conectar ERP'.")

    def _col(nombre, default):
        s = out[nombre] if nombre in out.columns else pd.Series(default, index=out.index)
        return s

    if entidad == "productos":
        out["categoria"] = _col("categoria", "Sin categoría").fillna("Sin categoría")
        out["proveedor"] = _col("proveedor", "Sin proveedor").fillna("Sin proveedor")
        out["precio"] = pd.to_numeric(out["precio"], errors="coerce").fillna(0.0)
        out["costo"] = pd.to_numeric(_col("costo", pd.NA),
                                     errors="coerce").fillna(out["precio"] * 0.7)
        out["stock"] = pd.to_numeric(_col("stock", 0), errors="coerce").fillna(0).astype(int)
        out["stock_min"] = pd.to_numeric(_col("stock_min", 0),
                                         errors="coerce").fillna(0).astype(int)
        out["lead_time_dias"] = pd.to_numeric(_col("lead_time_dias", 7),
                                              errors="coerce").fillna(7).astype(int)
    elif entidad == "clientes":
        for c in ["nombre", "tipo_negocio", "departamento", "zona"]:
            out[c] = _col(c, "Sin dato").fillna("Sin dato")
        for c in ["lat", "lon"]:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce")
    elif entidad == "ventas":
        out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
        out = out.dropna(subset=["fecha"])
        out["cantidad"] = pd.to_numeric(out["cantidad"], errors="coerce").fillna(0)
        for c in ["precio_unit", "costo_unit"]:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce")
    canon = list(SINONIMOS[entidad])
    return out[[c for c in canon if c in out.columns]]


# ---------------------------------------------------------------------------
# Fuentes: SQL (cualquier motor vía SQLAlchemy), CSV/Excel, demo
# ---------------------------------------------------------------------------
def conectar_sql(url: str):
    """Crea el engine SQLAlchemy. Soporta postgresql://, mysql+pymysql://,
    mssql+pyodbc://, oracle+oracledb://, sqlite:/// …"""
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True)


def listar_tablas(engine) -> list[str]:
    from sqlalchemy import inspect
    return inspect(engine).get_table_names()


# Nombre de tabla válido: identificador simple, opcionalmente con esquema
# ("dbo.productos"). Entre comillas dobles o corchetes también, porque varios
# ERP de Uruguay usan SQL Server con nombres de tabla que llevan mayúsculas o
# espacios y el usuario los copia tal cual del administrador de su ERP.
_TABLA_VALIDA = re.compile(r'^[\["]?[A-Za-z_][\w ]*[\]"]?(\.[\["]?[A-Za-z_][\w ]*[\]"]?)?$')


def leer_sql(engine, tabla_o_query: str, limite: int | None = None) -> pd.DataFrame:
    """Lee una tabla por nombre, o corre una consulta completa si `tabla_o_query`
    ya empieza con SELECT — es la pantalla "Conectar ERP" > "Elegir tablas
    manualmente", pensada para que el dueño de la base pegue su propia
    consulta cuando el autodescubrimiento no encuentra la tabla.

    Cuando NO es una consulta completa, se trata como nombre de tabla y se
    valida como identificador antes de interpolarlo en el SQL: un nombre de
    tabla no puede llevar punto y coma, comentarios (`--`) ni subconsultas.
    Sin este control, cualquier cosa que llegue a este campo sin pasar por el
    autodescubrimiento —una integración futura, una config compartida entre
    varias instalaciones— podía inyectar SQL arbitrario. El modo "pegá tu
    propia consulta" sigue exactamente igual: eso es a propósito, lo tipea el
    dueño de la base sobre su propia conexión.
    """
    from sqlalchemy import text
    q = tabla_o_query.strip()
    if not q.lower().startswith("select"):
        if not _TABLA_VALIDA.match(q):
            raise ValueError(
                f"'{tabla_o_query}' no es un nombre de tabla válido. Si querés "
                "usar una consulta, tiene que empezar con SELECT.")
        q = f"SELECT * FROM {q}"
    if limite:
        q = f"{q} LIMIT {int(limite)}"
    with engine.connect() as con:
        return pd.read_sql(text(q), con)


def autodescubrir_tabla(engine, entidad: str) -> str | None:
    tablas = {t.lower(): t for t in listar_tablas(engine)}
    for cand in TABLAS_CANDIDATAS[entidad]:
        if cand in tablas:
            return tablas[cand]
    return None


def leer_archivo(ruta, **forzado) -> pd.DataFrame:
    """CSV o Excel exportado del ERP (acepta ruta o file-like de Streamlit).

    Delega en `plania.archivos`, que detecta codificación, separador, filas de
    título y formato de números. Antes esto era un `pd.read_csv(ruta)` pelado
    y fallaba con los tres formatos más comunes de un ERP de acá: latin-1 con
    punto y coma, separado por tabulaciones, y con el encabezado del reporte
    arriba del encabezado real.
    """
    from plania import archivos
    return archivos.leer(ruta, **forzado)


def guardar_como_base(datos: dict[str, pd.DataFrame], ruta_db: str | None = None) -> str:
    """Persiste DataFrames ya normalizados como una base SQLite con los
    nombres canónicos de tabla, y devuelve la URL SQLAlchemy. Es lo que usa
    la pantalla 'Conectar ERP' para que los CSV/Excel subidos queden como
    fuente de datos permanente de toda la app (no solo de esa sesión)."""
    import sqlite3

    from plania import config as pconfig
    if ruta_db is None:
        os.makedirs(pconfig.CONFIG_DIR, exist_ok=True)
        ruta_db = os.path.join(pconfig.CONFIG_DIR, "erp_archivos.db")
    con = sqlite3.connect(ruta_db)
    try:
        for entidad in ("productos", "clientes", "ventas"):
            df = datos.get(entidad)
            if df is None:
                df = pd.DataFrame(columns=list(SINONIMOS[entidad]))
            df = df.copy()
            for c in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].astype(str)
            df.to_sql(entidad, con, if_exists="replace", index=False)
    finally:
        con.close()
    return f"sqlite:///{ruta_db}"


def cargar_datos(url: str | None = None,
                 tablas: dict | None = None,
                 mapeos: dict | None = None) -> dict[str, pd.DataFrame]:
    """
    Punto de entrada único. Devuelve {"productos": df, "clientes": df, "ventas": df}
    ya normalizados al esquema canónico.

      - url: conexión SQLAlchemy al ERP del cliente. Si es None usa la config
        guardada (ERP_DB_URL) y, si tampoco hay, la base demo.
      - tablas: {"productos": "articulos", ...} para forzar tablas/queries.
      - mapeos: {"productos": {col_origen: canonica}, ...} para forzar mapeo.
    """
    from plania import config as pconfig
    url = url or os.environ.get("ERP_DB_URL") or pconfig.leer_extra("ERP_DB_URL")
    if not url:
        demo = os.path.join(RAIZ, "data", "erp_demo.db")
        if not os.path.exists(demo):
            raise FileNotFoundError(
                "No hay ERP conectado ni base demo. Corré "
                "`python3 data/generate_dataset.py` o configurá ERP_DB_URL.")
        url = f"sqlite:///{demo}"

    engine = conectar_sql(url)
    datos = {}
    for entidad in ("productos", "clientes", "ventas"):
        tabla = (tablas or {}).get(entidad) or autodescubrir_tabla(engine, entidad)
        if not tabla:
            if entidad == "clientes":  # opcional: ventas+productos alcanzan
                datos[entidad] = pd.DataFrame(columns=list(SINONIMOS["clientes"]))
                continue
            raise ValueError(
                f"No encontré una tabla de {entidad} en la base conectada. "
                f"Tablas disponibles: {listar_tablas(engine)}. "
                "Elegila manualmente en 'Conectar ERP'.")
        df = leer_sql(engine, tabla)
        datos[entidad] = normalizar(df, entidad, (mapeos or {}).get(entidad))
    return datos
