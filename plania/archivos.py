"""
Plania · Lectura de CSV/Excel exportados de cualquier sistema
==============================================================
Lee el archivo que el cliente exportó de SU sistema, sin pedirle que lo
arregle antes y sin límite de tamaño.

Por qué hace falta esto y no alcanza `pd.read_csv`
---------------------------------------------------
Un ERP uruguayo real exporta cosas así, y las tres fallaban:

  - `Código;Descripción;Costo` en **latin-1**, separador **;**, decimal con
    **coma** y miles con **punto** (`1.234,50`) → `UnicodeDecodeError`.
  - Separado por **tabulaciones** con BOM → se leía como una sola columna.
  - Con el **título del reporte** en las primeras líneas antes del encabezado
    real → `ParserError`.

El cliente no tiene por qué saber qué es una codificación. Si el archivo se
abre bien en Excel, tiene que entrar en Plania.

Sin límite de tamaño
--------------------
`leer()` trae el archivo a memoria y sirve para lo normal. Para un archivo
que no entra en RAM está `importar_a_sqlite()`, que lo lee de a pedazos y lo
va escribiendo en la base: el pico de memoria depende del tamaño del pedazo,
no del archivo. Un CSV de 5 GB entra en una máquina de 8 GB.
"""
from __future__ import annotations

import csv
import io
import os

import pandas as pd

# Orden de prueba. utf-8-sig primero porque también lee utf-8 y además se come
# el BOM que mete Excel al guardar como CSV; latin-1 último porque nunca
# falla —decodifica cualquier byte— y taparía a las otras si fuera antes.
CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

SEPARADORES = (";", ",", "\t", "|")

# Cuántas filas se leen para adivinar el formato. Con 200 alcanza para ver la
# forma del archivo sin cargar 5 GB solo para decidir el separador.
FILAS_MUESTRA = 200

# Tamaño del pedazo al importar sin límite. 50.000 filas de un CSV ancho son
# unas pocas decenas de MB: entra cómodo y no hace miles de INSERT chicos.
FILAS_POR_PEDAZO = 50_000


def _es_excel(nombre: str) -> bool:
    return str(nombre).lower().endswith((".xlsx", ".xls", ".xlsm", ".ods"))


def _bytes_de(origen) -> bytes:
    """Los primeros bytes, venga una ruta o un archivo subido por el navegador."""
    if hasattr(origen, "read"):
        pos = origen.tell() if hasattr(origen, "tell") else None
        datos = origen.read(1_000_000)
        if pos is not None:
            origen.seek(pos)
        return datos if isinstance(datos, bytes) else str(datos).encode()
    with open(origen, "rb") as f:
        return f.read(1_000_000)


def detectar_codificacion(origen) -> str:
    """La primera codificación que lee la muestra sin romperse."""
    crudo = _bytes_de(origen)
    for cod in CODIFICACIONES:
        try:
            crudo.decode(cod)
            return cod
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 decodifica cualquier byte: es el último recurso que siempre sirve.
    return "latin-1"


def detectar_separador(texto: str) -> str:
    """El separador del CSV.

    Se prueba primero el Sniffer de la biblioteca estándar y, si no se decide
    —le pasa seguido con archivos que tienen texto libre con comas—, se elige
    el candidato que parta las primeras líneas en la MISMA cantidad de campos.
    La consistencia entre líneas es mejor señal que la frecuencia: una
    descripción con muchas comas gana por frecuencia y parte mal el archivo.
    """
    muestra = "\n".join(texto.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(muestra, delimiters="".join(SEPARADORES)).delimiter
    except Exception:
        pass

    lineas = [l for l in texto.splitlines()[:20] if l.strip()]
    mejor, mejor_puntaje = ",", -1.0
    for sep in SEPARADORES:
        conteos = [l.count(sep) for l in lineas]
        if not conteos or max(conteos) == 0:
            continue
        iguales = sum(1 for c in conteos if c == conteos[0]) / len(conteos)
        puntaje = iguales * 10 + min(conteos[0], 20) * 0.1
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = sep, puntaje
    return mejor


def detectar_fila_encabezado(texto: str, sep: str) -> int:
    """Cuántas líneas hay que saltear hasta el encabezado real.

    Los reportes de ERP suelen traer el nombre de la empresa y la fecha de
    emisión arriba de todo. El encabezado es la primera línea que tiene la
    misma cantidad de campos que las que la siguen — un título suelto no.
    """
    # Se guarda el número de línea ORIGINAL, no la posición dentro de la lista
    # filtrada: `skiprows` de pandas cuenta las líneas del archivo, y los
    # reportes suelen traer una línea en blanco entre el título y el
    # encabezado. Contando sobre la lista filtrada, se saltea de menos y el
    # encabezado se lee como si fuera un dato.
    numeradas = [(n, l) for n, l in enumerate(texto.splitlines()[:60]) if l.strip()]
    for pos, (n_original, linea) in enumerate(numeradas):
        campos = linea.count(sep) + 1
        if campos < 2:
            continue
        siguientes = [l.count(sep) + 1 for _, l in numeradas[pos + 1:pos + 4]]
        if siguientes and all(c == campos for c in siguientes):
            return n_original
    return 0


def _decimal_y_miles(texto: str, sep: str) -> tuple[str | None, str | None]:
    """Detecta `1.234,50` (formato de acá) contra `1,234.50` (formato de EEUU).

    Se mira si aparece una coma seguida de exactamente dos dígitos al final de
    un campo: eso es un decimal con coma. Sin esto, `1.234,50` se lee como
    texto y todos los cálculos de plata quedan en cero — el cliente ve un
    panel vacío sin ningún error.
    """
    import re
    muestra = "\n".join(texto.splitlines()[:FILAS_MUESTRA])
    campos = re.split(f"[{re.escape(sep)}\n]", muestra)
    con_coma_decimal = sum(1 for c in campos if re.fullmatch(r"-?[\d.]*\d,\d{1,2}", c.strip()))
    con_punto_decimal = sum(1 for c in campos if re.fullmatch(r"-?[\d,]*\d\.\d{1,2}", c.strip()))
    if con_coma_decimal > con_punto_decimal:
        return ",", "."
    return None, None


def describir(origen) -> dict:
    """Qué formato se detectó. Para mostrárselo al cliente antes de importar.

    Es a propósito una función aparte: la pantalla puede enseñar "detecté
    punto y coma, latin-1, decimal con coma" y dejar corregirlo, en vez de
    adivinar en silencio y que el cliente descubra el error tres pantallas
    después.
    """
    nombre = getattr(origen, "name", str(origen))
    if _es_excel(nombre):
        return {"tipo": "excel", "hojas": _hojas(origen)}

    cod = detectar_codificacion(origen)
    texto = _bytes_de(origen).decode(cod, errors="replace")
    sep = detectar_separador(texto)
    dec, miles = _decimal_y_miles(texto, sep)
    return {"tipo": "csv", "codificacion": cod, "separador": sep,
            "saltar_filas": detectar_fila_encabezado(texto, sep),
            "decimal": dec or ".", "miles": miles or ""}


def _hojas(origen) -> list[str]:
    try:
        return list(pd.ExcelFile(origen).sheet_names)
    except Exception:
        return []


def _rebobinar(origen):
    if hasattr(origen, "seek"):
        try:
            origen.seek(0)
        except Exception:
            pass


def leer(origen, hoja=None, **forzado) -> pd.DataFrame:
    """El archivo como DataFrame, detectando el formato solo.

    `forzado` permite pisar lo detectado (`separador=";"`, `codificacion=...`)
    para cuando el cliente corrige a mano desde la pantalla.
    """
    nombre = getattr(origen, "name", str(origen))
    _rebobinar(origen)

    if _es_excel(nombre):
        # Una sola hoja: se usa esa. Varias y sin elegir: la primera con
        # datos, no la primera a secas — muchos reportes traen una hoja
        # "Portada" vacía adelante.
        if hoja is None:
            for h in _hojas(origen) or [0]:
                _rebobinar(origen)
                df = pd.read_excel(origen, sheet_name=h)
                if not df.empty:
                    return df
            _rebobinar(origen)
            return pd.read_excel(origen)
        _rebobinar(origen)
        return pd.read_excel(origen, sheet_name=hoja)

    fmt = describir(origen)
    fmt.update(forzado)
    _rebobinar(origen)
    return pd.read_csv(
        origen,
        sep=fmt["separador"],
        encoding=fmt["codificacion"],
        skiprows=fmt["saltar_filas"],
        decimal=fmt["decimal"],
        thousands=fmt["miles"] or None,
        engine="python",         # tolera separadores raros y líneas irregulares
        on_bad_lines="skip",     # una fila rota no puede tirar la importación
    )


def importar_a_sqlite(origen, tabla: str, ruta_db: str,
                      filas_por_pedazo: int = FILAS_POR_PEDAZO,
                      hoja=None, **forzado) -> int:
    """Importa un archivo grande sin cargarlo entero en memoria.

    Devuelve la cantidad de filas escritas. El pico de memoria depende del
    tamaño del pedazo, no del archivo: un CSV de varios GB entra en una
    máquina común, que es lo que hace falta para no ponerle un techo al
    cliente.

    Excel no se puede leer de a pedazos —el formato obliga a abrir todo el
    libro— así que ahí se carga completo. Es una limitación del formato, no
    de esto: un Excel de más de un millón de filas no existe, el propio Excel
    no lo abre.
    """
    import sqlite3

    nombre = getattr(origen, "name", str(origen))
    os.makedirs(os.path.dirname(ruta_db) or ".", exist_ok=True)
    con = sqlite3.connect(ruta_db)
    total = 0
    try:
        if _es_excel(nombre):
            df = leer(origen, hoja=hoja)
            df.to_sql(tabla, con, if_exists="replace", index=False)
            return len(df)

        fmt = describir(origen)
        fmt.update(forzado)
        _rebobinar(origen)
        lector = pd.read_csv(
            origen,
            sep=fmt["separador"],
            encoding=fmt["codificacion"],
            skiprows=fmt["saltar_filas"],
            decimal=fmt["decimal"],
            thousands=fmt["miles"] or None,
            engine="python",
            on_bad_lines="skip",
            chunksize=filas_por_pedazo,
        )
        for i, pedazo in enumerate(lector):
            pedazo.to_sql(tabla, con, if_exists="replace" if i == 0 else "append",
                          index=False)
            total += len(pedazo)
        con.commit()
    finally:
        con.close()
    return total
