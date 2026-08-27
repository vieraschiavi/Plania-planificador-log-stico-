# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Traducción de la interfaz (español / inglés / portugués)
===================================================================
Un punto único para traducir texto de producto: `t("clave", idioma)`.

**Por qué no es un simple diccionario clave→string como el de `sitio/i18n/`.**
El sitio web es copy de marketing, fijo. Acá el texto lleva montos, fechas y
cantidades que cambian en cada pantalla ("Quedan 20 horas", "$1,43 M"), así
que cada clave es una plantilla de `str.format()` con placeholders con
nombre (`"Quedan {horas} horas"`), no un string suelto. `t()` interpola con
los `**kw` que le pasen.

**Por qué el idioma se pasa como argumento y no se lee de una variable
global.** `plania/` tiene que poder importarse y testearse sin Streamlit
(ver CLAUDE.md), y Streamlit puede correr varias sesiones de usuario en el
mismo proceso — una variable de módulo mutable filtraría el idioma de una
sesión a otra. Quien llama (`app/app.py`) lee el idioma una vez de
`st.session_state` al principio de cada corrida y lo pasa explícito de ahí
en adelante. Todas las funciones default a `IDIOMA_POR_DEFECTO` para que el
código existente que todavía no pasa idioma siga andando en español.

**Por qué el catálogo vive en JSON y no en el código.** Así se puede sumar o
corregir una traducción sin tocar Python, y `test_los_catalogos_de_idioma_
tienen_las_mismas_claves` puede leerlo sin importar nada más que `json`.
"""
from __future__ import annotations

import functools
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA_LOCALES = os.path.join(RAIZ, "plania", "locales")

IDIOMAS = ("es", "en", "pt")
IDIOMA_POR_DEFECTO = "es"
NOMBRES_IDIOMA = {"es": "Español", "en": "English", "pt": "Português"}

# plania/config.py::CLAVES es para credenciales (keyring/cifrado/plano) — el
# idioma no es un secreto, así que usa el mismo mecanismo que EULA_ACEPTADA o
# DEMO_INICIO: `leer_extra`/`guardar_extra`, en texto plano, sin pasar por el
# backend de cifrado que existe para proteger API keys.
_CLAVE_CONFIG = "IDIOMA"


class ClaveDeTraduccionFaltante(KeyError):
    """La clave no existe en NINGÚN catálogo — error de programación, no de
    traducción incompleta (para eso está el test de completitud)."""


@functools.lru_cache(maxsize=None)
def _catalogo(idioma: str) -> dict:
    ruta = os.path.join(CARPETA_LOCALES, f"{idioma}.json")
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def idiomas_disponibles() -> tuple[str, ...]:
    return IDIOMAS


def idioma_guardado() -> str:
    """El idioma persistido para esta instalación, o el default si no hay
    ninguno guardado todavía o lo guardado ya no es válido."""
    from plania import config as pconfig
    valor = pconfig.leer_extra(_CLAVE_CONFIG)
    return valor if valor in IDIOMAS else IDIOMA_POR_DEFECTO


def establecer_idioma(idioma: str) -> None:
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma desconocido: {idioma!r} (válidos: {IDIOMAS})")
    from plania import config as pconfig
    pconfig.guardar_extra(_CLAVE_CONFIG, idioma)


def t(clave: str, idioma: str = IDIOMA_POR_DEFECTO, **kw) -> str:
    """Traduce `clave` al `idioma` pedido, interpolando `**kw`.

    Si al `idioma` pedido le falta la clave, cae a español antes que romper
    la pantalla — pero eso sólo puede pasar si el catálogo quedó
    desincronizado, y el test de completitud existe para que nunca llegue a
    producción así. Si la clave no existe en NINGÚN idioma, es un error de
    programación (una clave mal escrita) y se avisa fuerte en vez de mostrar
    la clave cruda en pantalla.
    """
    cat = _catalogo(idioma if idioma in IDIOMAS else IDIOMA_POR_DEFECTO)
    plantilla = cat.get(clave)
    if plantilla is None:
        plantilla = _catalogo(IDIOMA_POR_DEFECTO).get(clave)
    if plantilla is None:
        raise ClaveDeTraduccionFaltante(
            f"{clave!r} no está en ningún catálogo de plania/locales/")
    try:
        return plantilla.format(**kw)
    except (KeyError, IndexError) as e:
        raise ValueError(
            f"faltó un valor para {clave!r} en idioma={idioma!r}: {e}") from e


# ---------------------------------------------------------------------------
# Números y montos por locale
# ---------------------------------------------------------------------------
# es/pt (rioplatense y pt-BR/pt-PT) comparten formato: punto de miles, coma
# decimal. en usa el de EE.UU.: coma de miles, punto decimal. No hay un
# tercer formato — dos alcanzan para los tres idiomas del producto.
_DECIMAL_COMA = ("es", "pt")


def miles(n: float, decimales: int = 0, idioma: str = IDIOMA_POR_DEFECTO) -> str:
    """`1234567.89` -> `"1.234.567,89"` (es/pt) o `"1,234,567.89"` (en)."""
    s = f"{n:,.{decimales}f}"
    if idioma in _DECIMAL_COMA:
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s


def fmt_monto(n: float, idioma: str = IDIOMA_POR_DEFECTO, moneda: str = "$") -> str:
    """Monto compacto para tarjetas: abrevia a K/M para que nunca se corte.

    Streamlit trunca con "…" el valor de una `st.metric` que no entra en su
    ancho — con cinco tarjetas en fila un monto de seis cifras no entra
    escrito entero. Abreviar no es cosmético acá: es lo que evita ese corte.
    """
    if abs(n) >= 1_000_000:
        return f"{moneda}{miles(n / 1_000_000, 2, idioma)} M"
    if abs(n) >= 100_000:
        return f"{moneda}{miles(n / 1_000, 0, idioma)} K"
    return f"{moneda}{miles(n, 0, idioma)}"
