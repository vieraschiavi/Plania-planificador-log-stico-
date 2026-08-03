"""
Plania · Catálogo de la base del cliente
=========================================
Lee la base que la empresa YA tiene y arma un mapa completo de lo que hay
adentro: tablas, columnas, tipos, claves primarias, claves foráneas
declaradas, relaciones no declaradas, cantidad de filas y una muestra de
valores reales de cada columna de texto.

Para qué sirve un mapa y no solo una lista de tablas
-----------------------------------------------------
Antes, encontrar la tabla de productos era buscar el nombre en una lista fija
("productos", "articulos", "oitm", …). Funciona con los ERP conocidos y falla
con el resto: si la empresa la llama `mercaderia`, `stk_maestro` o
`TBL_ITEMS_01`, no la encuentra, y el cliente ve "no pude mapear columnas
obligatorias" sin saber qué hacer.

Con el catálogo se decide por CONTENIDO además de por nombre: una tabla con
columnas que parecen código, descripción, costo, precio y stock es la de
productos aunque se llame `TBL_ITEMS_01`. El nombre pasa a ser una pista más,
no el único criterio.

Las muestras de valores tienen un propósito concreto además de informar: son
las que alimentan los filtros por categoría del panel (`valores_de`), para
que el cliente filtre por SU rubro real —"Bebidas", "Almacén"— y no por una
lista inventada.

Todo sale del inspector de SQLAlchemy, así que funciona igual en PostgreSQL,
MySQL, SQL Server, Oracle y SQLite sin escribir un SQL distinto por motor.
"""
from __future__ import annotations

import unicodedata

# Cuántos valores distintos se traen por columna de texto. Suficiente para
# entender de qué habla la columna y para poblar un filtro, sin traerse medio
# millón de descripciones de producto.
MAX_MUESTRAS = 25

# Una columna con más valores distintos que esto no es una categoría (es un
# código, un nombre propio o una descripción libre): no sirve para filtrar.
MAX_CARDINALIDAD_CATEGORIA = 60


def _sin_acentos(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return s.strip().lower()


def _contar_filas(con, tabla: str) -> int:
    """Filas de una tabla. Devuelve -1 si no se puede contar.

    Contar puede fallar por permisos o tardar mucho en tablas enormes; que
    falle no puede tumbar la lectura del catálogo entero, así que se aísla.
    """
    from sqlalchemy import text
    try:
        return int(con.execute(text(f'SELECT COUNT(*) FROM "{tabla}"')).scalar())
    except Exception:
        try:
            return int(con.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar())
        except Exception:
            return -1


def _muestras(con, tabla: str, columna: str, limite: int = MAX_MUESTRAS) -> list:
    from sqlalchemy import text
    for expr in (f'SELECT DISTINCT "{columna}" FROM "{tabla}" '
                 f'WHERE "{columna}" IS NOT NULL',
                 f"SELECT DISTINCT {columna} FROM {tabla} "
                 f"WHERE {columna} IS NOT NULL"):
        try:
            filas = con.execute(text(expr)).fetchmany(limite + 1)
            return [f[0] for f in filas]
        except Exception:
            continue
    return []


def extraer(engine, con_muestras: bool = True, max_tablas: int | None = None) -> dict:
    """Mapa completo de la base.

    Devuelve:
        {"tablas": {nombre: {"columnas": [...], "pk": [...], "n_filas": int,
                             "muestras": {col: [valores]}}},
         "fks": [{"tabla_origen","columna_origen","tabla_destino","columna_destino"}],
         "joins_inferidos": {columna: [tablas que la comparten]},
         "errores": [str]}

    `errores` no está para adornar: en una base real siempre hay alguna vista
    rota o alguna tabla sin permiso de lectura. Se registran y se sigue, en
    vez de abortar el catálogo entero por una tabla que ni se iba a usar.
    """
    from sqlalchemy import inspect

    insp = inspect(engine)
    catalogo: dict = {"tablas": {}, "fks": [], "joins_inferidos": {}, "errores": []}

    try:
        nombres = list(insp.get_table_names())
        try:
            nombres += [v for v in insp.get_view_names() if v not in nombres]
        except Exception:
            pass          # no todos los motores exponen vistas
    except Exception as e:
        catalogo["errores"].append(f"no pude listar tablas: {e}")
        return catalogo

    if max_tablas:
        nombres = nombres[:max_tablas]

    columnas_por_tabla: dict[str, list[str]] = {}
    with engine.connect() as con:
        for tabla in nombres:
            try:
                cols = insp.get_columns(tabla)
            except Exception as e:
                catalogo["errores"].append(f"{tabla}: no pude leer columnas ({e})")
                continue

            try:
                pk = list(insp.get_pk_constraint(tabla).get("constrained_columns") or [])
            except Exception:
                pk = []

            detalle = [{"columna": c["name"],
                        "tipo": str(c.get("type", "")),
                        "nullable": bool(c.get("nullable", True)),
                        "pk": c["name"] in pk}
                       for c in cols]
            columnas_por_tabla[tabla] = [c["columna"] for c in detalle]

            muestras: dict[str, list] = {}
            if con_muestras:
                for c in detalle:
                    if c["pk"] or "char" not in c["tipo"].lower() and \
                            "text" not in c["tipo"].lower():
                        continue
                    vals = _muestras(con, tabla, c["columna"])
                    if vals:
                        muestras[c["columna"]] = vals

            catalogo["tablas"][tabla] = {
                "columnas": detalle,
                "pk": pk,
                "n_filas": _contar_filas(con, tabla),
                "muestras": muestras,
            }

            try:
                for fk in insp.get_foreign_keys(tabla):
                    destino = fk.get("referred_table")
                    for i, col in enumerate(fk.get("constrained_columns") or []):
                        refs = fk.get("referred_columns") or []
                        catalogo["fks"].append({
                            "tabla_origen": tabla, "columna_origen": col,
                            "tabla_destino": destino,
                            "columna_destino": refs[i] if i < len(refs) else None,
                        })
            except Exception:
                pass

    # Relaciones que NADIE declaró. En los ERP reales las claves foráneas
    # suelen no existir —se resuelven por convención de nombres— así que sin
    # esto el mapa de una base de verdad queda sin ninguna relación.
    #
    # El criterio es "la misma columna aparece en más de una tabla", sin pedir
    # que se llame `algo_id`: una primera versión exigía ese sufijo y no
    # encontraba NINGUNA relación en una base real donde las claves se llaman
    # `sku` y `nro_cta`. Se descartan solo los nombres tan genéricos que
    # coincidir no significa nada.
    GENERICAS = {"fecha", "fec", "estado", "activo", "nombre", "descripcion",
                 "detalle", "obs", "observaciones", "tipo", "usuario", "empresa"}
    compartidas: dict[str, list[str]] = {}
    for tabla, cols in columnas_por_tabla.items():
        for c in cols:
            if _sin_acentos(c) not in GENERICAS:
                compartidas.setdefault(c, []).append(tabla)
    catalogo["joins_inferidos"] = {c: ts for c, ts in compartidas.items() if len(ts) > 1}

    return catalogo


# ---------------------------------------------------------------------------
# Reconocer una columna cuando NO está en la lista de sinónimos
# ---------------------------------------------------------------------------
def _tokens(nombre: str) -> set[str]:
    return {t for t in _sin_acentos(nombre).replace("-", "_").split("_") if t}


# Tokens que aparecen en medio mundo de columnas y no dicen NADA sobre qué
# contiene la columna: "nro", "cod", "id" significan "esto es un
# identificador", no de qué. Compartirlos no puede alcanzar para declarar que
# dos columnas son lo mismo.
#
# Sin esta lista, `nro_cta` (el cliente) matcheaba con `nro_comprobante` (la
# factura) porque comparten "nro", y las ventas quedaban con el número de
# cliente cargado como número de comprobante. Un mapeo equivocado en silencio
# es peor que uno faltante: el cliente ve totales por comprobante que no
# significan nada y no tiene forma de darse cuenta.
TOKENS_VACIOS = {"nro", "num", "numero", "cod", "codigo", "id", "ide", "no",
                 "n", "de", "del", "la", "el"}


def parecido(columna: str, alias: str) -> float:
    """Cuánto se parecen un nombre de columna y un alias conocido (0 a 1).

    Existe porque una lista de sinónimos nunca alcanza: por más alias que se
    carguen, la próxima empresa va a llamarle `fec` a la fecha y
    `nombre_fantasia` al nombre. Las tres reglas cubren lo que de verdad pasa
    en los ERP:

      - `fec` contra `fecha`     → uno es prefijo del otro
      - `nombre_fantasia` / `nombre` → comparten un token entero
      - `costo_neto` / `costo`   → comparten un token entero

    Deliberadamente NO se usa distancia de edición: `costo` y `casto` se
    parecen mucho por edición y no significan lo mismo, mientras que `cant` y
    `cantidad` se parecen poco y sí. Prefijos y tokens modelan mejor cómo se
    abrevian los nombres de columna.
    """
    c, a = _sin_acentos(columna), _sin_acentos(alias)
    if c == a:
        return 1.0

    tc, ta = _tokens(c), _tokens(a)
    compartidos = (tc & ta) - TOKENS_VACIOS
    if compartidos:
        # Comparten al menos un token con contenido. Vale más cuanto mayor sea
        # la proporción compartida: `costo_neto`/`costo` vale más que
        # `precio_costo_promedio_x`/`costo`.
        return 0.55 + 0.35 * len(compartidos) / max(len(tc), len(ta))

    corto, largo = (c, a) if len(c) <= len(a) else (a, c)
    if len(corto) >= 3 and largo.startswith(corto):
        # Abreviatura por prefijo: `fec` → `fecha`, `cant` → `cantidad`.
        return 0.5 + 0.3 * len(corto) / len(largo)

    return 0.0


def mapeo_por_parecido(columnas: list[str], sinonimos_entidad: dict,
                       ya_usadas: set[str] | None = None,
                       umbral: float = 0.6) -> dict:
    """{columna_origen: canónica} para lo que la lista exacta no reconoció.

    Se resuelve por mejor puntaje global y no columna por columna: si
    `costo_neto` puede ser `costo` y `precio` puede ser `precio`, asignar de a
    una en orden de aparición puede dejar a `precio` sin candidata. Se ordena
    por puntaje descendente y cada columna y cada canónica se usan una sola
    vez.
    """
    usadas = set(ya_usadas or set())
    pares = []
    for col in columnas:
        if col in usadas:
            continue
        for canonica, alias in sinonimos_entidad.items():
            mejor = max((parecido(col, a) for a in alias), default=0.0)
            if mejor >= umbral:
                pares.append((mejor, col, canonica))

    pares.sort(reverse=True)
    mapeo, canonicas_usadas = {}, set()
    for _p, col, canonica in pares:
        if col in usadas or canonica in canonicas_usadas:
            continue
        mapeo[col] = canonica
        usadas.add(col)
        canonicas_usadas.add(canonica)
    return mapeo


def claves_por_estructura(catalogo: dict, tabla: str, tablas_entidad: dict) -> dict:
    """Identifica columnas de enlace usando las relaciones, no los nombres.

    Hay claves a las que no se llega por parecido: si la tabla de clientes es
    `MAESTRO_CTAS` con clave `nro_cta`, y la de ventas tiene una columna
    `nro_cta`, esa columna ES el cliente — aunque no se parezca ni a
    "cliente" ni a "cliente_id". Se deduce de que sea la clave de la tabla de
    clientes y aparezca también acá.

    `tablas_entidad` es {"productos": "TBL_ITEMS_01", "clientes": "MAESTRO_CTAS"}.
    Devuelve {columna_en_esta_tabla: "sku" | "cliente_id"}.
    """
    info = catalogo.get("tablas", {}).get(tabla)
    if not info:
        return {}
    mis_columnas = {c["columna"] for c in info["columnas"]}

    canonica_de = {"productos": "sku", "clientes": "cliente_id"}
    salida = {}

    # 1) Claves foráneas declaradas: la fuente más confiable.
    for fk in catalogo.get("fks", []):
        if fk["tabla_origen"] != tabla:
            continue
        for entidad, tabla_destino in tablas_entidad.items():
            if tabla_destino and fk["tabla_destino"] == tabla_destino:
                salida[fk["columna_origen"]] = canonica_de.get(entidad, entidad)

    # 2) Sin FK declarada —el caso normal en un ERP—: la clave primaria de la
    #    otra tabla que aparece con el mismo nombre en esta.
    for entidad, tabla_destino in tablas_entidad.items():
        if not tabla_destino or entidad not in canonica_de:
            continue
        destino = catalogo["tablas"].get(tabla_destino, {})
        for pk in destino.get("pk", []):
            if pk in mis_columnas and pk not in salida:
                salida[pk] = canonica_de[entidad]

    return salida


# ---------------------------------------------------------------------------
# Elegir la tabla de cada entidad por contenido, no solo por nombre
# ---------------------------------------------------------------------------
def _reconocer(columnas: list[str], sinonimos_entidad: dict) -> dict:
    """{columna: canónica} por nombre exacto y, lo que sobre, por parecido.

    Es el reconocimiento "sin estructura": lo que se puede saber mirando sólo
    los nombres de las columnas de una tabla. Lo comparten `puntuar_tabla`
    (para elegir la tabla) y `sugerir_mapeo` (para armar el mapeo), a
    propósito: si puntuaran distinto, se podría elegir una tabla y después no
    poder mapearla.
    """
    normalizadas = {_sin_acentos(c): c for c in columnas}
    mapeo, usadas = {}, set()
    for canonica, alias in sinonimos_entidad.items():
        for a in alias:
            col = normalizadas.get(_sin_acentos(a))
            if col and col not in usadas:
                mapeo[col] = canonica
                usadas.add(col)
                break

    faltantes = {k: v for k, v in sinonimos_entidad.items() if k not in mapeo.values()}
    if faltantes:
        mapeo.update(mapeo_por_parecido(columnas, faltantes, usadas))
    return mapeo


def puntuar_tabla(info: dict, entidad: str, nombre_tabla: str,
                  sinonimos: dict, candidatas: list[str]) -> float:
    """Qué tan probable es que `nombre_tabla` sea la de `entidad`.

    Tres señales, en este orden de peso:

      1. **Cuántas columnas canónicas se reconocen** (0-10). Es la señal
         fuerte: una tabla con código, descripción, costo, precio y stock es
         la de productos aunque se llame `TBL_ITEMS_01`.
      2. **Cuántas OBLIGATORIAS se reconocen**. Sin ellas la tabla no sirve
         aunque el nombre calce perfecto, así que pesa el doble.
      3. **El nombre** (0-3). Pasa a ser un desempate, no el criterio.

    Se penaliza la tabla vacía: en una base con `articulos` (0 filas, quedó de
    una migración) y `art_maestro` (18.000 filas), la buena es la segunda.
    """
    columnas = [c["columna"] for c in info.get("columnas", [])]
    if not columnas:
        return 0.0

    # Se cuenta con el MISMO reconocimiento que después arma el mapeo (exacto
    # + parecido). Si el puntaje usara solo coincidencia exacta, una tabla
    # perfectamente válida cuyas columnas se llaman `fec` y `cant` puntuaría
    # cero y nunca sería elegida, aunque el mapeo después la resolviera bien.
    reconocidas = len(_reconocer(columnas, sinonimos))
    puntaje = float(reconocidas)

    n = _sin_acentos(nombre_tabla)
    if n in [_sin_acentos(c) for c in candidatas]:
        puntaje += 3
    elif any(_sin_acentos(c) in n for c in candidatas):
        puntaje += 1.5

    filas = info.get("n_filas", -1)
    if filas == 0:
        puntaje -= 4          # existe pero está vacía: casi seguro no es
    elif filas > 0:
        puntaje += 0.5

    return puntaje


def elegir_tablas(catalogo: dict, sinonimos: dict, candidatas: dict,
                  obligatorias: dict) -> dict:
    """{entidad: {"tabla":…, "puntaje":…, "alternativas":[…]}}.

    `alternativas` se devuelve a propósito: cuando la elección no es obvia, la
    pantalla "Conectar ERP" puede ofrecerle al cliente las otras candidatas en
    vez de dejarlo adivinando por qué eligió la que eligió.
    """
    salida: dict = {}
    for entidad in sinonimos:
        puntuadas = []
        for tabla, info in catalogo.get("tablas", {}).items():
            p = puntuar_tabla(info, entidad, tabla, sinonimos[entidad],
                              candidatas.get(entidad, []))
            # Sin las obligatorias no sirve, por más alto que puntúe el resto.
            # Se comprueban con el mismo reconocimiento que arma el mapeo, no
            # con coincidencia exacta: una tabla cuya fecha se llama `fec`
            # tiene la obligatoria, aunque no diga "fecha".
            reconocidas = set(_reconocer([c["columna"] for c in info["columnas"]],
                                         sinonimos[entidad]).values())
            if not set(obligatorias.get(entidad, [])) <= reconocidas:
                continue
            puntuadas.append((p, tabla))

        puntuadas.sort(reverse=True)
        if puntuadas:
            salida[entidad] = {
                "tabla": puntuadas[0][1],
                "puntaje": round(puntuadas[0][0], 1),
                "alternativas": [t for _, t in puntuadas[1:4]],
            }
        else:
            salida[entidad] = {"tabla": None, "puntaje": 0, "alternativas": []}
    return salida


# ---------------------------------------------------------------------------
# Categorías para los filtros del panel
# ---------------------------------------------------------------------------
def columnas_categoricas(df) -> list[str]:
    """Columnas de un DataFrame que sirven para filtrar.

    El criterio es la cardinalidad, no el nombre: una columna con 8 valores
    distintos en 30.000 filas es una categoría; una con 30.000 valores
    distintos es un identificador y no sirve para un filtro.
    """
    salida = []
    for col in df.columns:
        serie = df[col]
        if serie.dtype.kind in "ifc" and serie.nunique(dropna=True) > 12:
            continue          # numérica continua: no es categoría
        n = serie.nunique(dropna=True)
        if 1 < n <= MAX_CARDINALIDAD_CATEGORIA:
            salida.append(col)
    return salida


def valores_de(df, columna: str) -> list:
    """Los valores de una categoría, ordenados, sin nulos — para un filtro."""
    if columna not in df.columns:
        return []
    return sorted(df[columna].dropna().unique().tolist(), key=lambda v: str(v))


def resumen(catalogo: dict) -> str:
    """Una línea por tabla, para mostrarle al cliente qué se encontró."""
    lineas = []
    for tabla, info in sorted(catalogo.get("tablas", {}).items()):
        filas = info.get("n_filas", -1)
        cuantas = f"{filas:,}".replace(",", ".") if filas >= 0 else "?"
        lineas.append(f"{tabla}: {len(info['columnas'])} columnas · {cuantas} filas")
    if catalogo.get("errores"):
        lineas.append(f"({len(catalogo['errores'])} tabla/s no se pudieron leer)")
    return "\n".join(lineas)


def sugerir_mapeo(catalogo: dict, tabla: str, entidad: str, sinonimos: dict,
                  tablas_entidad: dict | None = None) -> dict:
    """El mapeo {columna_origen: canónica} usando todo lo que se sabe.

    Se aplican tres señales en orden de confianza, y cada una sólo llena lo
    que la anterior no pudo:

      1. **Lista de sinónimos** — coincidencia exacta del nombre. Es lo más
         seguro y cubre los ERP conocidos.
      2. **Estructura** — la clave primaria de la tabla de clientes que
         aparece en la de ventas es el cliente, se llame como se llame.
         Va antes que el parecido porque una relación real vale más que una
         coincidencia de letras.
      3. **Parecido** — abreviaturas y variantes (`fec`, `nombre_fantasia`).

    Devuelve solo lo que reconoció: lo que quede sin mapear se lo muestra la
    pantalla "Conectar ERP" al cliente para que lo complete a mano. Adivinar
    de más es peor que no adivinar — un `precio` mapeado a la columna
    equivocada le hace calcular márgenes falsos sin que se entere.
    """
    info = catalogo.get("tablas", {}).get(tabla)
    if not info:
        return {}
    columnas = [c["columna"] for c in info["columnas"]]
    sin = sinonimos[entidad]

    # 1) Exacto
    normalizadas = {_sin_acentos(c): c for c in columnas}
    mapeo, usadas = {}, set()
    for canonica, alias in sin.items():
        for a in alias:
            col = normalizadas.get(_sin_acentos(a))
            if col and col not in usadas:
                mapeo[col] = canonica
                usadas.add(col)
                break

    # 2) Estructura
    if tablas_entidad:
        for col, canonica in claves_por_estructura(catalogo, tabla, tablas_entidad).items():
            if col not in usadas and canonica in sin and canonica not in mapeo.values():
                mapeo[col] = canonica
                usadas.add(col)

    # 3) Parecido
    faltantes = {k: v for k, v in sin.items() if k not in mapeo.values()}
    if faltantes:
        mapeo.update(mapeo_por_parecido(columnas, faltantes, usadas))

    return mapeo


def completar_por_estructura(catalogo: dict, elegidas: dict, sinonimos: dict,
                             obligatorias: dict) -> dict:
    """Encuentra las entidades que ningún criterio de nombre pudo encontrar.

    Hay claves a las que no se llega por parecido de ninguna forma: si la
    tabla de clientes es `MAESTRO_CTAS` con clave `nro_cta`, no se parece ni a
    "cliente" ni a "cuenta" (`cta` no es prefijo de `cuenta`). Lexicalmente es
    imposible, y sin embargo es evidente mirando la estructura: es la tabla
    cuya clave primaria aparece dentro de la de ventas.

    Por eso este paso va DESPUÉS: necesita que ventas ya esté identificada
    para poder mirar desde ahí. Se aplica solo a lo que quedó sin resolver, y
    nunca pisa algo ya elegido por nombre.
    """
    ventas = (elegidas.get("ventas") or {}).get("tabla")
    if not ventas or ventas not in catalogo.get("tablas", {}):
        return elegidas

    cols_ventas = {c["columna"] for c in catalogo["tablas"][ventas]["columnas"]}
    ya_tomadas = {r.get("tabla") for r in elegidas.values() if r.get("tabla")}

    for entidad, r in elegidas.items():
        if r.get("tabla") or entidad == "ventas":
            continue

        candidatas = []
        for tabla, info in catalogo["tablas"].items():
            if tabla in ya_tomadas or not info.get("pk"):
                continue
            # Su clave primaria aparece en ventas => ventas apunta a ella.
            if not set(info["pk"]) & cols_ventas:
                continue
            if info.get("n_filas", -1) == 0:
                continue
            candidatas.append((info.get("n_filas", 0), tabla))

        if not candidatas:
            continue
        # Con varias, la que más filas tiene: la tabla maestra real, no una
        # tabla de parámetros con cuatro registros.
        candidatas.sort(reverse=True)
        tabla = candidatas[0][1]
        elegidas[entidad] = {
            "tabla": tabla,
            "puntaje": 0.0,
            "por_estructura": True,   # para que la UI lo pueda avisar
            "alternativas": [t for _, t in candidatas[1:4]],
        }
        ya_tomadas.add(tabla)
    return elegidas
