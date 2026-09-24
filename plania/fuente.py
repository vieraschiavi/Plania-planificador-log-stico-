# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Fuente de datos activa
===============================
UN solo lugar que decide de dónde salen los datos de TODA la aplicación: la
base demo, un ERP por SQL o los archivos CSV/Excel que subió el usuario.

Antes la decisión estaba repartida: la app miraba la sesión y la config, el
motor miraba primero el entorno, el contenido tenía su propio chequeo de
«¿es la demo?», y `config.aplicar()` copiaba la URL al entorno al arrancar y
nunca la actualizaba. Resultado: el usuario elegía su archivo y alguna
pantalla —o el panel del dueño, o la API— seguía leyendo la demo, y volver a
la demo sólo se podía «borrando ERP · URL en Configuración», que ignora los
campos vacíos: no había vuelta.

Reglas:
  - Precedencia: URL elegida en la sesión > variable de entorno puesta a
    propósito > la guardada en la config > base demo.
  - Si hay una fuente del usuario, la demo NO aparece: no hay mezcla ni
    respaldo silencioso. Si la fuente del usuario falla, falla a la vista.
  - `clave` cambia cuando cambia la fuente o su contenido (archivo resubido,
    demo regenerada): es lo que usa la app para invalidar cachés, filtros y
    el historial del copiloto.

No importa Streamlit: se prueba sola (`tests/test_fuente.py`).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLAVE_URL = "ERP_DB_URL"
CLAVE_NOMBRE = "ERP_FUENTE_NOMBRE"
ARCHIVO_SUBIDOS = "erp_archivos.db"


def ruta_demo() -> str:
    return os.path.join(RAIZ, "data", "erp_demo.db")


def url_demo() -> str:
    return f"sqlite:///{ruta_demo()}"


def _ruta_sqlite(url: str) -> str | None:
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return None


def es_url_demo(url: str | None) -> bool:
    if not url:
        return True
    ruta = _ruta_sqlite(url)
    return bool(ruta) and os.path.basename(ruta) == "erp_demo.db"


def _tipo(url: str) -> str:
    if es_url_demo(url):
        return "demo"
    ruta = _ruta_sqlite(url)
    if ruta and os.path.basename(ruta) == ARCHIVO_SUBIDOS:
        return "archivo"
    return "sql"


def _nombre_sql(url: str) -> str:
    """Nombre legible de una conexión, SIN la contraseña."""
    ruta = _ruta_sqlite(url)
    if ruta:
        return os.path.basename(ruta)
    try:
        from sqlalchemy.engine import make_url
        u = make_url(url)
        lugar = "/".join(p for p in (u.host or "", u.database or "") if p)
        return f"{u.get_backend_name()} · {lugar}" if lugar else u.get_backend_name()
    except Exception:
        from plania import config as pconfig
        return pconfig.enmascarar(url)


def _huella(url: str) -> str:
    """Identifica la fuente Y su contenido cuando es un archivo local: si el
    usuario resube archivos, la URL es la misma pero los datos no."""
    partes = [url]
    ruta = _ruta_sqlite(url)
    if ruta and os.path.exists(ruta):
        st = os.stat(ruta)
        partes += [str(st.st_mtime_ns), str(st.st_size)]
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Fuente:
    tipo: str       # "demo" | "sql" | "archivo"
    url: str
    nombre: str     # para mostrar: sin contraseña; "" en la demo
    origen: str     # "demo" | "sesion" | "entorno" | "config"
    clave: str      # cambia si cambia la fuente o su contenido

    @property
    def es_demo(self) -> bool:
        return self.tipo == "demo"

    @property
    def fijada_por_entorno(self) -> bool:
        """La eligió quien instaló (variable de entorno): la app no la cambia."""
        return self.origen == "entorno"


def _nombre_guardado(url: str) -> str:
    from plania import config as pconfig
    guardado = pconfig.leer_extra(CLAVE_NOMBRE)
    if isinstance(guardado, dict) and guardado.get("url") == url:
        return str(guardado.get("nombre") or "")
    return ""


def resolver(url_sesion: str | None = None) -> Fuente:
    """La fuente que TODA la app tiene que usar ahora."""
    from plania import config as pconfig
    url, origen = "", "demo"
    entorno = os.environ.get(CLAVE_URL) or ""
    if url_sesion:
        url, origen = url_sesion, "sesion"
    elif entorno and not pconfig.viene_de_la_config(CLAVE_URL):
        url, origen = entorno, "entorno"
    else:
        guardada = pconfig.leer_extra(CLAVE_URL) or ""
        if isinstance(guardada, str) and guardada:
            url, origen = guardada, "config"

    if es_url_demo(url):
        demo = url_demo()
        return Fuente("demo", demo, "", "demo", _huella(demo))
    tipo = _tipo(url)
    nombre = _nombre_guardado(url) or _nombre_sql(url)
    return Fuente(tipo, url, nombre, origen, _huella(url))


def _sincronizar_entorno(url: str) -> None:
    """Si la URL del entorno era una copia de la config, que la siga."""
    from plania import config as pconfig
    if not pconfig.viene_de_la_config(CLAVE_URL):
        return
    if url:
        os.environ[CLAVE_URL] = url
        pconfig.COPIADAS_AL_ENTORNO[CLAVE_URL] = url
    else:
        os.environ.pop(CLAVE_URL, None)
        pconfig.COPIADAS_AL_ENTORNO.pop(CLAVE_URL, None)


def usar(url: str, nombre: str = "") -> Fuente:
    """Deja `url` como fuente de toda la app (persistida)."""
    from plania import config as pconfig
    pconfig.guardar_extra(CLAVE_URL, url or "")
    pconfig.guardar_extra(CLAVE_NOMBRE, {"url": url, "nombre": nombre} if url and nombre else "")
    _sincronizar_entorno(url or "")
    return resolver()


def volver_a_demo() -> Fuente:
    """Olvida la fuente del usuario y vuelve a la base demo.

    Si la fuente la fijó una variable de entorno puesta a propósito, eso no
    se toca desde la app: el `Fuente` devuelto lo dice (`fijada_por_entorno`).
    """
    return usar("")


def cargar(fuente: Fuente | None = None, tablas: dict | None = None) -> dict:
    """Los datos de `fuente` (por defecto, la activa). Las tablas elegidas a
    mano son de la base del usuario: sobre la demo no se aplican."""
    from plania import conectores
    fuente = fuente or resolver()
    return conectores.cargar_datos(url=fuente.url,
                                   tablas=None if fuente.es_demo else tablas)
