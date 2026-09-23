# © 2026 Martín Viera. Todos los derechos reservados.
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
                "codigo_producto", "id_producto", "producto_id", "productoid",
                "default_code"],
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
                   "denominacion", "name", "razonsocial", "nombremedico",
                   "nombre_medico", "nombrecliente", "nombre_cliente"],
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
                "articulo", "cod_producto", "product_id", "producto_id", "productoid"],
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


#: Nombres de hoja (o de archivo) que dicen de qué entidad es la tabla. Con
#: eso, una columna que se llama sólo «ID» se puede tomar como la clave: en
#: la hoja «Producto» el ID es el del producto; en «Visitas», no.
_HOJAS_ENTIDAD = {
    "productos": ("producto", "productos", "articulo", "articulos", "item", "items",
                  "sku", "skus", "catalogo"),
    "clientes": ("cliente", "clientes", "medico", "medicos", "customer",
                 "customers", "cuenta", "cuentas", "socio", "socios"),
}
_CLAVE_ENTIDAD = {"productos": "sku", "clientes": "cliente_id"}


def _hoja_es_de(df: pd.DataFrame, entidad: str) -> bool:
    hoja = _normalizar_nombre(df.attrs.get("hoja") or "")
    return bool(hoja) and hoja in _HOJAS_ENTIDAD.get(entidad, ())


def autodetectar_mapeo(df: pd.DataFrame, entidad: str) -> dict:
    """Devuelve {col_origen: col_canonica} por matcheo de sinónimos.

    Si la clave de la entidad no aparece por sinónimo pero hay una columna
    llamada «ID» y la hoja se llama como la entidad («Producto», «Medico»),
    esa columna es la clave. Reportado con `Bases y diccionario.xlsx`: su
    hoja «Producto» trae `ID, Producto, Molecula…` y la de «Medico» `ID,
    NombreMedico…`, y Plania pedía mapear a mano algo que el nombre de la
    hoja ya decía. En una hoja cualquiera un «ID» NO se toma: puede ser el
    número de fila.
    """
    sin = SINONIMOS[entidad]
    cols = {_normalizar_nombre(c): c for c in df.columns}
    mapeo, usadas = {}, set()
    for canonica, candidatos in sin.items():
        for cand in candidatos:
            if cand in cols and cols[cand] not in usadas:
                mapeo[cols[cand]] = canonica
                usadas.add(cols[cand])
                break
    clave = _CLAVE_ENTIDAD.get(entidad)
    if (clave and clave not in mapeo.values() and clave not in df.columns
            and "id" in cols and cols["id"] not in usadas and _hoja_es_de(df, entidad)):
        mapeo[cols["id"]] = clave
    return mapeo


def faltan_obligatorias(df: pd.DataFrame, entidad: str,
                        mapeo: dict | None = None) -> list:
    """Qué columnas obligatorias de `entidad` quedan SIN origen con `mapeo`.

    Es la misma cuenta que hace `normalizar()` antes de levantar, pero sin
    levantar: la pantalla «Conectar ERP» la necesita para saber si tiene
    que abrir el ajuste manual ANTES de que el archivo falle. Sin esto la
    app sólo podía enterarse por la excepción, o sea cuando ya no quedaba
    nada que ofrecerle al usuario más que el texto del error.

    Cuenta dos orígenes, igual que `rename`: la columna que el mapeo
    renombra, y la que ya venía llamándose como la canónica.
    """
    mapeo = autodetectar_mapeo(df, entidad) if mapeo is None else mapeo
    resueltas = set(mapeo.values()) | (set(df.columns) - set(mapeo))
    return [c for c in OBLIGATORIAS[entidad] if c not in resueltas]


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
# ("dbo.productos"), o entre comillas dobles o corchetes para el caso de
# nombres con espacios ("[Mi Tabla]") — varios ERP de Uruguay usan SQL Server
# y el usuario copia el nombre tal cual del administrador de su ERP.
#
# A propósito NO se permite un espacio suelto en el identificador simple: en
# SQL válido, un identificador sin delimitar nunca lleva espacios — si los
# lleva, va entre corchetes o comillas. La primera versión de este patrón sí
# los permitía (`[\w ]*` sin exigir delimitador), y con eso "productos union
# select sql from sqlite_master" pasaba la validación entera: ninguna letra
# ni espacio es un carácter "especial", así que una inyección por palabras
# clave —sin punto y coma, sin comillas, sin "="— la esquivaba limpio. Se
# probó de verdad contra una base real: leyó sqlite_master. El delimitador
# entre comillas/corchetes cierra el identificador donde corresponde — lo que
# venga después del cierre y no sea `$` o un `.esquema` rompe el match.
_IDENT_SIMPLE = r"[A-Za-z_][A-Za-z0-9_]*"
_IDENT_ENTRECOMILLADO = r'"[^"]+"|\[[^\]]+\]'
_IDENT = rf"(?:{_IDENT_SIMPLE}|{_IDENT_ENTRECOMILLADO})"
_TABLA_VALIDA = re.compile(rf"^{_IDENT}(\.{_IDENT})?$")


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
        return _leer_acotado(engine, q, int(limite))
    with engine.connect() as con:
        return pd.read_sql(text(q), con)


#: Tope por defecto al leer una tabla del ERP del cliente.
#:
#: Antes no había ninguno: `cargar_desde_sql` llamaba a `leer_sql(engine,
#: tabla)` sin `limite`, o sea `SELECT * FROM ventas` completo dentro de un
#: `pd.read_sql`. En la base demo son miles de filas y no se nota; en el ERP
#: de un distribuidor con diez años de historia son millones, y el programa
#: se los trae todos a memoria antes de mostrar nada.
#:
#: 500.000 y no 50.000 porque acá el tope no es para perfilar: la analítica
#: de Plania agrega ventas por período y por SKU, así que recortar de más
#: cambia los números que el cliente va a mirar. Con 500.000 filas entran
#: varios años de un distribuidor mediano y el costo de memoria queda en el
#: orden de los cientos de MB, no de los gigas.
LIMITE_FILAS = int(os.environ.get("PLANIA_LIMITE_FILAS") or 500_000)


def avisos_de_recorte(datos: dict) -> list[str]:
    """Qué entidades se leyeron recortadas, para decirlo en pantalla.

    El tope existía y estaba razonado, pero era MUDO: `LIMITE_FILAS` no se
    leía en ningún otro archivo del repo —ni la app ni la API lo miraban—,
    así que con el ERP de un distribuidor de diez años las ventas se
    cortaban en 500.000 filas y la analítica entera (períodos, sobrestock,
    reposición, re-precificación, ruteo, copiloto) salía de ese pedazo
    presentada como el total del negocio. Un número parcial con cara de
    total es peor que no tener el número.
    """
    fuera = []
    for entidad, df in (datos or {}).items():
        if getattr(df, "attrs", {}).get("recortada"):
            fuera.append(
                f"{entidad}: se leyeron {len(df):,} filas, que es el tope "
                f"actual. La tabla tiene más, y todo lo que se calcule sale "
                f"de ese recorte. Subí PLANIA_LIMITE_FILAS si necesitás la "
                f"tabla entera.")
    return fuera


def _leer_acotado(engine, sql: str, limite: int):
    """Trae como mucho `limite` filas, en cualquiera de los cinco motores.

    NO se arma `f"{sql} LIMIT n"`: esa es sintaxis de PostgreSQL, MySQL y
    SQLite. SQL Server quiere `TOP` y Oracle `FETCH FIRST`, así que pegarle
    `LIMIT` al final a la consulta de un cliente con SQL Server o con Oracle
    —dos de los cinco motores que este mismo archivo dice soportar— es un
    error de sintaxis, no un recorte.

    `chunksize` lo resuelve del lado del driver y sin dialecto: abre un
    cursor del lado del servidor y se corta apenas se juntan las filas
    pedidas. Es el mismo camino que ya usa MV Data Governance por la misma
    razón.
    """
    import pandas as pd
    from sqlalchemy import text
    trozos, total = [], 0
    with engine.connect() as con:
        for trozo in pd.read_sql(text(sql), con,
                                 chunksize=min(limite, 50_000)):
            trozos.append(trozo)
            total += len(trozo)
            if total >= limite:
                break
        if not trozos:
            return pd.read_sql(text(sql), con).head(0)   # vacío CON columnas
    return pd.concat(trozos, ignore_index=True).head(limite)


def autodescubrir_tabla(engine, entidad: str) -> str | None:
    tablas = {t.lower(): t for t in listar_tablas(engine)}
    for cand in TABLAS_CANDIDATAS[entidad]:
        if cand in tablas:
            return tablas[cand]
    return None


# Columnas que delatan un DICCIONARIO de datos (`Tabla | Campo | Tipo |
# Descripción`): filas de metadatos, no de productos. Sin descartarlas, el
# diccionario empata con la hoja buena —su «Descripción» mapea a `nombre`
# igual que la «Producto» de la hoja de productos— y gana por venir primero.
_COLUMNAS_DE_DICCIONARIO = {"campo", "columna", "field", "column_name"}
_COLUMNAS_DE_DICCIONARIO_2 = {"tabla", "tipo", "tipo_dato", "table", "data_type",
                              "descripcion", "description"}


def parece_diccionario(df: pd.DataFrame) -> bool:
    cols = {_normalizar_nombre(c) for c in df.columns}
    return bool(cols & _COLUMNAS_DE_DICCIONARIO) and bool(cols & _COLUMNAS_DE_DICCIONARIO_2)


def hojas_de(ruta) -> list[str]:
    """Las hojas de un Excel, o `[]` si `ruta` no es un Excel."""
    from plania import archivos
    nombre = getattr(ruta, "name", str(ruta))
    if not archivos._es_excel(nombre):
        return []
    archivos._rebobinar(ruta)
    hojas = archivos._hojas(ruta)
    archivos._rebobinar(ruta)
    return hojas


def evaluar_hojas(ruta, entidad: str) -> list[dict]:
    """Cuánto sirve cada hoja de un Excel para `entidad`, en orden de libro.

    Cada item: `hoja`, `filas`, `faltan` (obligatorias sin origen, con el
    MISMO `autodetectar_mapeo` que después usa `normalizar` —si se eligiera
    con una regla y se validara con otra, habría libros donde la elegida es
    justo la rechazada—), `mapeadas` (cuántas canónicas resuelve) y
    `diccionario`. Es lo que la pantalla usa para preseleccionar la hoja y
    lo que el error lista cuando ninguna sirve.
    """
    from plania import archivos
    out = []
    for h in hojas_de(ruta):
        archivos._rebobinar(ruta)
        df = pd.read_excel(ruta, sheet_name=h)
        df.attrs["hoja"] = h
        mapeo = autodetectar_mapeo(df, entidad)
        out.append({
            "hoja": h,
            "filas": len(df),
            "faltan": faltan_obligatorias(df, entidad, mapeo),
            "mapeadas": len(set(mapeo.values()) | (set(df.columns) & set(SINONIMOS[entidad]))),
            "diccionario": parece_diccionario(df),
        })
    archivos._rebobinar(ruta)
    return out


def mejor_hoja(evaluacion: list[dict]) -> str | None:
    """La hoja que mejor mapea: menos obligatorias faltantes, después más
    columnas reconocidas; a igualdad, la que viene antes en el libro. Las
    vacías y los diccionarios de datos quedan últimos."""
    if not evaluacion:
        return None

    def _clave(par):
        i, e = par
        return (e["filas"] == 0, e["diccionario"], len(e["faltan"]), -e["mapeadas"], i)

    return min(enumerate(evaluacion), key=_clave)[1]["hoja"]


def explicar_hojas(evaluacion: list[dict], entidad: str, idioma: str = "es") -> str:
    """Qué hojas se probaron y qué le falta a cada una, en una línea por hoja.

    El error de antes nombraba sólo UNA hoja (la primera) aunque el libro
    tuviera ocho; el usuario no sabía si el problema era el archivo entero
    o esa hoja.
    """
    from plania import i18n
    lineas = [i18n.t("conectar.hojas_probadas", idioma, entidad=entidad)]
    for e in evaluacion:
        if e["filas"] == 0:
            motivo = i18n.t("conectar.hoja_vacia", idioma)
        elif e["diccionario"]:
            motivo = i18n.t("conectar.hoja_diccionario", idioma)
        elif e["faltan"]:
            motivo = i18n.t("conectar.hoja_falta", idioma, columnas=", ".join(e["faltan"]))
        else:
            motivo = i18n.t("conectar.hoja_completa", idioma)
        lineas.append(f"- {e['hoja']}: {motivo}")
    return "\n".join(lineas)


def leer_archivo(ruta, entidad: str | None = None, hoja=None, **forzado) -> pd.DataFrame:
    """CSV o Excel exportado del ERP (acepta ruta o file-like de Streamlit).

    Delega en `plania.archivos`, que detecta codificación, separador, filas de
    título y formato de números. Antes esto era un `pd.read_csv(ruta)` pelado
    y fallaba con los tres formatos más comunes de un ERP de acá: latin-1 con
    punto y coma, separado por tabulaciones, y con el encabezado del reporte
    arriba del encabezado real.

    `hoja` fuerza una hoja (el selector de la pantalla). Sin ella y con
    `entidad`, un Excel de varias hojas usa la que MEJOR mapea las columnas
    de esa entidad (`mejor_hoja`), no la primera. Reportado con un
    `Bases y diccionario.xlsx` de ocho hojas, donde la primera era el
    diccionario —48 filas de `Tabla | Campo | Tipo | Descripción`— y la
    pantalla contestaba «No pude mapear columnas obligatorias de productos:
    ['sku', 'precio']» con los productos en otra hoja del mismo archivo.
    """
    from plania import archivos
    if hoja is None and entidad in OBLIGATORIAS and len(hojas_de(ruta)) > 1:
        hoja = mejor_hoja(evaluar_hojas(ruta, entidad))
    df = archivos.leer(ruta, hoja=hoja, **forzado)
    # De qué hoja salió (o, en un CSV, el nombre del archivo sin extensión):
    # `autodetectar_mapeo` lo usa para saber si un «ID» suelto es la clave.
    nombre = hoja if isinstance(hoja, str) else os.path.splitext(
        os.path.basename(str(getattr(ruta, "name", ruta))))[0]
    df.attrs["hoja"] = nombre
    return df


# ---------------------------------------------------------------------------
# Precio derivado de ventas: SÓLO a pedido explícito
# ---------------------------------------------------------------------------
_MONTO = ("ventas", "ventasusd", "ventas_usd", "venta", "importe", "importe_total",
          "monto", "monto_total", "total", "facturacion", "sales", "revenue", "valor")
_UNIDADES = ("unidades", "cantidad", "cant", "qty", "quantity", "units",
             "cantidad_vendida")


def candidatas_precio_derivado(df: pd.DataFrame) -> tuple[list, list]:
    """(columnas de monto, columnas de unidades) presentes en `df`.

    Sirve para OFRECER precio = monto / unidades cuando falta `precio`. Nunca
    se aplica sola: un precio promedio calculado no es el precio de lista, y
    el piso de margen de las ofertas se calcula sobre él.
    """
    montos, unidades = [], []
    for c in df.columns:
        n = _normalizar_nombre(c)
        if n in _MONTO or n.startswith(("ventas_", "importe_", "monto_")):
            montos.append(c)
        elif n in _UNIDADES:
            unidades.append(c)
    return montos, unidades


def derivar_precio(df: pd.DataFrame, col_monto, col_unidades,
                   col_clave=None, idioma: str = "es") -> tuple[pd.DataFrame, str]:
    """Agrega `precio` = suma(monto) / suma(unidades), por `col_clave` si viene.

    Devuelve (df, nota). La nota es obligatoria de mostrar: dice de dónde
    salió el precio, para que nadie lo lea como el de lista. Las filas con
    unidades en cero quedan con precio vacío en vez de un infinito.
    """
    from plania import i18n
    d = df.copy()
    d["_m"] = pd.to_numeric(d[col_monto], errors="coerce")
    d["_u"] = pd.to_numeric(d[col_unidades], errors="coerce")
    if col_clave is not None and col_clave in d.columns:
        sumas = d.groupby(col_clave, sort=False)[["_m", "_u"]].sum()
        d = d.drop_duplicates(subset=[col_clave]).set_index(col_clave)
        d[["_m", "_u"]] = sumas
        d = d.reset_index()
    u = d["_u"].where(d["_u"] != 0)
    d["precio"] = (d["_m"] / u).round(2)
    d = d.drop(columns=["_m", "_u"])
    nota = i18n.t("conectar.precio_derivado_nota", idioma,
                  monto=col_monto, unidades=col_unidades)
    return d, nota


def precio_desde_ventas(ventas_crudo: pd.DataFrame, idioma: str = "es"):
    """Precio promedio REALIZADO por sku, sacado del archivo de ventas.

    Para cuando el maestro de productos no trae precio pero las ventas sí
    traen monto y unidades (la hoja «Mercado» de `Bases y diccionario`:
    `ProductoID, Unidades, VentasUSD`). Devuelve `(serie sku→precio, nota)`
    o `(None, "")` si las ventas no alcanzan para calcularlo.

    No es el precio de lista y la nota lo dice: se muestra siempre que se
    use. Sin monto en las ventas no se inventa nada.
    """
    from plania import i18n
    montos, unidades = candidatas_precio_derivado(ventas_crudo)
    mapeo = autodetectar_mapeo(ventas_crudo, "ventas")
    col_sku = next((o for o, c in mapeo.items() if c == "sku"), None)
    if not (montos and unidades and col_sku):
        return None, ""
    d = pd.DataFrame({
        "sku": ventas_crudo[col_sku].astype(str).str.strip(),
        "_m": pd.to_numeric(ventas_crudo[montos[0]], errors="coerce"),
        "_u": pd.to_numeric(ventas_crudo[unidades[0]], errors="coerce"),
    }).groupby("sku")[["_m", "_u"]].sum()
    precio = (d["_m"] / d["_u"].where(d["_u"] != 0)).round(2).dropna()
    if precio.empty:
        return None, ""
    nota = i18n.t("conectar.precio_derivado_nota", idioma,
                  monto=montos[0], unidades=unidades[0])
    return precio, nota


def completar_precio(productos_crudo: pd.DataFrame, mapeo: dict,
                     precio_por_sku: pd.Series) -> pd.DataFrame:
    """Agrega la columna `precio` a los productos cruzando por sku."""
    col_sku = next((o for o, c in mapeo.items() if c == "sku"),
                   "sku" if "sku" in productos_crudo.columns else None)
    if col_sku is None:
        return productos_crudo
    d = productos_crudo.copy()
    d["precio"] = d[col_sku].astype(str).str.strip().map(precio_por_sku)
    return d


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
        # `limite + 1`: que vuelva la de más es la prueba de que la tabla
        # tiene más. Sin esa fila no hay forma de distinguir «entró justo»
        # de «se cortó», y era exactamente eso lo que dejaba el recorte mudo.
        df = leer_sql(engine, tabla, limite=LIMITE_FILAS + 1)
        recortada = len(df) > LIMITE_FILAS
        if recortada:
            df = df.head(LIMITE_FILAS)
        norm = normalizar(df, entidad, (mapeos or {}).get(entidad))
        # Después de `normalizar`, no antes: esa función devuelve un frame
        # nuevo y se llevaría puesto el `attrs`.
        norm.attrs["recortada"] = recortada
        norm.attrs["limite"] = LIMITE_FILAS
        datos[entidad] = norm
    return datos
