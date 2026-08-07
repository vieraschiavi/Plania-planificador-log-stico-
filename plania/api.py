"""
Plania · API local que consume la interfaz de escritorio
========================================================
Expone en HTTP lo que hoy dibuja `app/app.py` con Streamlit, para que la
ventana de Electron pueda tener una interfaz React propia y dejar de embeber
una página web hecha con Streamlit.

**Esto no es el backend de venta.** `backend_venta/` es el servidor del
Licenciante (licencias, checkout, webhooks de MercadoPago) y corre en
internet. Esto corre en la máquina del cliente, escucha sólo en 127.0.0.1 y
sirve los datos del propio cliente.

Por qué una API y no que React hable con Python directo: Electron es Node, y
la lógica de negocio de Plania es Python (pandas, scikit-learn). Un proceso
Python que sirve JSON es la forma más simple de que convivan sin duplicar
ni una regla de negocio.

**Acá no vive ninguna regla de negocio.** Cada endpoint llama a los módulos
que ya existen (`analitica`, `sugerencias`, `rutas`, `copiloto`) y traduce el
resultado a JSON. Si una cuenta se hiciera acá, habría dos fuentes de verdad
—una para la pantalla vieja y otra para la nueva— y en algún momento darían
números distintos delante de un cliente.

Levantar a mano, para desarrollo:

    uvicorn plania.api:app --host 127.0.0.1 --port 8777
"""
from __future__ import annotations

import math
import os
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from plania import analitica, conectores, copiloto, exportes, licencia, rutas, sugerencias

app = FastAPI(title="Plania · API local", docs_url="/_docs")

# La ventana de Electron carga la interfaz desde file:// , y ese origen viaja
# como "null". Sin esto, el navegador embebido bloquea cada llamada por CORS y
# la aplicación arranca en blanco sin decir por qué.
#
# Que sea permisivo no abre nada a la red: el servidor escucha únicamente en
# 127.0.0.1 (lo fija quien lo lanza), así que sólo llega tráfico de esta
# máquina. CORS no es lo que protege acá — lo que protege es la interfaz de
# escucha.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Datos: se leen una vez y se reusan
# ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {}


def _datos() -> dict:
    """Los datos del cliente, cacheados en memoria.

    `cargar_datos` lee del ERP conectado o de la base demo, y en una base real
    puede tardar segundos. Sin caché, cada pantalla que el usuario abre
    volvería a leerla entera y la interfaz se sentiría lenta justamente
    mientras alguien la está mirando en una demo.
    """
    if "datos" not in _CACHE:
        url = os.environ.get("ERP_DB_URL") or None
        _CACHE["datos"] = conectores.cargar_datos(url=url)
    return _CACHE["datos"]


def _ventas() -> pd.DataFrame:
    if "ventas" not in _CACHE:
        d = _datos()
        _CACHE["ventas"] = analitica.enriquecer_ventas(
            d["ventas"], d["productos"], d["clientes"])
    return _CACHE["ventas"]


def invalidar_cache() -> None:
    """Se llama cuando cambia la fuente de datos (otro ERP, otro archivo)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Traducción a JSON
# ---------------------------------------------------------------------------
def _limpiar(valor: Any) -> Any:
    """JSON no tiene NaN ni Infinity, y `json.dumps` los escribe igual —
    produciendo un documento que `JSON.parse` rechaza del otro lado. Un
    promedio sobre cero filas alcanza para generarlos, así que no es un caso
    raro: es el primer día de un cliente cuyo período no tiene ventas."""
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if isinstance(valor, (pd.Timestamp,)):
        return valor.isoformat()
    return valor


def tabla_json(df: pd.DataFrame | None, limite: int | None = None) -> dict:
    """Un DataFrame como {columnas, filas, total}.

    Se manda `total` además de las filas: si la tabla se recorta para no
    mandar 50.000 registros a la interfaz, la pantalla tiene que poder decir
    "mostrando 200 de 4.312" en vez de dar a entender que eso es todo.
    """
    if df is None or not len(df):
        return {"columnas": [], "filas": [], "total": 0}
    recorte = df.head(limite) if limite else df
    registros = recorte.to_dict(orient="records")
    filas = [{k: _limpiar(v) for k, v in fila.items()} for fila in registros]
    return {"columnas": list(recorte.columns), "filas": filas, "total": int(len(df))}


# ---------------------------------------------------------------------------
# Estado y licencia
# ---------------------------------------------------------------------------
@app.get("/salud")
def salud() -> dict:
    """Le sirve a la ventana de Electron para saber cuándo el motor levantó."""
    return {"ok": True}


@app.get("/licencia")
def estado_licencia() -> dict:
    return licencia.estado()


class Activacion(BaseModel):
    token: str


@app.post("/licencia/activar")
def activar(a: Activacion) -> dict:
    r = licencia.activar_licencia(a.token)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "Licencia inválida."))
    return r


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@app.get("/panel")
def panel(dias: int = 30) -> dict:
    d, v = _datos(), _ventas()
    return {
        "kpis": {k: _limpiar(x) for k, x in analitica.kpis(d["productos"], v, dias).items()},
        "tendencia": tabla_json(analitica.tendencia_mensual(v)),
        "top_clientes": tabla_json(analitica.top_clientes(v), limite=20),
        "por_categoria": tabla_json(analitica.por_dimension(v, "categoria")),
    }


@app.get("/stock")
def stock() -> dict:
    d, v = _datos(), _ventas()
    return {
        "rotacion": tabla_json(analitica.rotacion(d["productos"], v), limite=500),
        "reposicion": tabla_json(sugerencias.reposicion(d["productos"], v), limite=500),
    }


@app.get("/precios")
def precios() -> dict:
    d, v = _datos(), _ventas()
    return {
        "margen_por_producto": tabla_json(analitica.margen_por_producto(v), limite=500),
        "ajustes": tabla_json(sugerencias.precios(d["productos"], v), limite=500),
    }


@app.get("/zonas")
def zonas() -> dict:
    d, v = _datos(), _ventas()
    return {
        "por_zona": tabla_json(analitica.por_dimension(v, "zona")),
        "por_tipo_negocio": tabla_json(analitica.por_dimension(v, "tipo_negocio")),
        "oportunidades": tabla_json(sugerencias.oportunidades_zona(v), limite=200),
    }


@app.get("/ofertas")
def ofertas() -> dict:
    d, v = _datos(), _ventas()
    return {"ofertas": tabla_json(sugerencias.ofertas_por_sobrestock(d["productos"], v), limite=300)}


@app.get("/clientes/inactivos")
def clientes_inactivos(dias: int = 60) -> dict:
    d, v = _datos(), _ventas()
    return {
        "inactivos": tabla_json(analitica.clientes_inactivos(v, d["clientes"], dias), limite=300),
        "recupero": tabla_json(sugerencias.recupero_clientes(v, d["clientes"]), limite=300),
    }


class PedidoRutas(BaseModel):
    vehiculos: int = 2
    zona: str | None = None


@app.post("/rutas")
def planificar_rutas(p: PedidoRutas) -> dict:
    d = _datos()
    if p.vehiculos < 1:
        raise HTTPException(400, "Hace falta al menos un vehículo.")
    clientes = d["clientes"]
    if p.zona:
        clientes = clientes[clientes["zona"] == p.zona]
        if not len(clientes):
            raise HTTPException(404, f"No hay clientes en la zona {p.zona!r}.")
    # `planificar` devuelve varios DataFrames, no uno: las paradas en orden,
    # el resumen por vehículo, y los clientes que quedaron afuera por no tener
    # GPS. Los tres importan en pantalla — sobre todo `sin_gps`, que explica
    # por qué la ruta tiene menos paradas de las que el usuario esperaba.
    plan = rutas.planificar(clientes, vehiculos=p.vehiculos)
    return {clave: tabla_json(df) for clave, df in plan.items()}


class Consulta(BaseModel):
    pregunta: str


@app.post("/copiloto")
def preguntar(c: Consulta) -> dict:
    if not c.pregunta.strip():
        raise HTTPException(400, "La consulta viene vacía.")
    r = copiloto.responder(c.pregunta, _datos())
    return {
        "respuesta": r.get("respuesta", ""),
        "titulo": r.get("titulo", ""),
        # La tabla es la evidencia del número que dio la respuesta: sin ella
        # el copiloto es una opinión. Va completa, no recortada.
        "tabla": tabla_json(r.get("tabla")),
    }
