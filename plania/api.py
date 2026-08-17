# © 2026 Martín Viera. Todos los derechos reservados.
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

import importlib.util
import math
import os
import secrets
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from plania import (analitica, conectores, copiloto, exportes, licencia, rutas,
                    sugerencias)
from plania import config as pconfig

app = FastAPI(title="Plania · API local", docs_url="/_docs")

# Escuchar sólo en 127.0.0.1 impide que llegue tráfico de la red, pero NO
# impide que llegue del navegador del propio usuario: si mientras Plania corre
# alguien abre una página cualquiera, el JavaScript de esa página puede pedirle
# a http://127.0.0.1:<puerto> igual que a cualquier servidor.
#
# Con `allow_origins=["*"]` —como estaba— el navegador además le dejaba LEER la
# respuesta, y los puertos que prueba el lanzador son cinco fijos, o sea
# triviales de escanear. Comprobado: con un Origin de un sitio cualquiera,
# `/inicio` devolvía la venta y el margen del cliente, y `/erp/guardar` le
# cambiaba la conexión a su base. En el build del dueño, además,
# `/owner/negocio` entrega la facturación y `/owner/licencias/emitir` fabrica
# licencias.
#
# Dos capas, porque ninguna sola alcanza:
#
#   1. El origen. La interfaz se carga desde file://, cuyo origen viaja como
#      "null": es el único que se acepta. Un sitio real (https://…) ya no puede
#      leer nada. No alcanza solo, porque un <iframe sandbox> también manda
#      "null" — por eso está la segunda.
#   2. El token. Lo genera la ventana, se lo pasa al motor por entorno y a la
#      interfaz por la query. Una página ajena no lo puede adivinar.
ORIGEN_VENTANA = "null"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGEN_VENTANA],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas que se responden sin token. `/salud` es lo que la ventana consulta para
# saber cuándo levantó el motor, antes de tener nada cargado, y no dice más que
# "sí, estoy". Dejarla abierta no filtra nada y evita que un error de token se
# vea como "el servidor no levantó", que manda a buscar el problema al lugar
# equivocado.
SIN_TOKEN = {"/salud"}


def _token_esperado() -> str | None:
    """El token de esta corrida, o None si nadie lo fijó.

    Se lee en cada pedido y no una vez al importar: los tests y el arranque a
    mano lo ponen y lo sacan del entorno, y cachearlo haría que el primer
    import decidiera para siempre.
    """
    return os.environ.get("PLANIA_API_TOKEN") or None


@app.middleware("http")
async def exigir_token(request, call_next):
    """Sin el token de esta corrida, no se contesta.

    Si nadie fijó `PLANIA_API_TOKEN` no se exige nada: es el arranque a mano
    para desarrollo (`uvicorn plania.api:app`), donde no hay ventana que lo
    genere. Ahí la única capa es el origen, que ya bloquea a cualquier sitio
    real. En el producto instalado siempre está, porque lo pone la ventana.
    """
    esperado = _token_esperado()
    if esperado and request.url.path not in SIN_TOKEN:
        recibido = (request.headers.get("x-plania-token")
                    or request.query_params.get("token"))
        # Comparación en tiempo constante: comparar con `!=` filtra, por lo que
        # tarda, cuántos caracteres del principio acertó quien prueba.
        if not recibido or not secrets.compare_digest(recibido, esperado):
            return JSONResponse({"detail": "Token de acceso inválido."}, status_code=403)
    return await call_next(request)


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
MENSAJE_DEMO_VENCIDA = ('La demo de 7 días terminó. Activá tu licencia en '
                        '"Planes y licencia" para seguir usando Plania con tus datos intactos.')


def _exigir_licencia_vigente() -> None:
    """Corta acá, con los datos reales del cliente todavía sin tocar.

    Sin esto, la ventana de Electron seguía mostrando Stock, Precios, Panel
    ejecutivo, Zonas, Ofertas y Clientes inactivos —con la analítica
    completa— indefinidamente después de que la demo de 7 días vence.
    Comprobado pidiéndolos de verdad con una demo vencida: los seis
    devolvían 200 con el paquete entero. `app/app.py` sí lo bloquea
    (`BLOQUEADA`, línea ~299); esta API no lo hacía — dos superficies del
    mismo producto con dos reglas de negocio distintas, y la que de verdad
    importa (¿el cliente pagó?) era la que fallaba.

    `/inicio` no llama a esto a propósito: `app/app.py` deja ver esa página
    —un teaser de 4 números, no la analítica completa— aun con la demo
    vencida, y esta API hace lo mismo por coherencia con el producto que ya
    existe.
    """
    if licencia.estado()["modo"] == "vencida":
        raise HTTPException(402, MENSAJE_DEMO_VENCIDA)


@app.get("/inicio")
def inicio() -> dict:
    """Lo primero que ve el usuario: cuánto vendió, con qué margen, y las dos
    cifras que justifican el producto — plata inmovilizada que puede liberar y
    venta que está por perder.

    El resumen sale de `generar_todas`, el mismo paquete que se exporta a
    PDF: así el número de la pantalla y el del informe que el cliente le pasa
    a su jefe son el mismo.
    """
    d, v = _datos(), _ventas()
    resumen = sugerencias.generar_todas(d)["resumen"]
    return {
        "kpis": {k: _limpiar(x) for k, x in analitica.kpis(d["productos"], v).items()},
        "resumen": {k: _limpiar(x) for k, x in resumen.items()},
        "licencia": licencia.estado(),
    }


@app.get("/panel")
def panel(dias: int = 30) -> dict:
    _exigir_licencia_vigente()
    d, v = _datos(), _ventas()
    return {
        "kpis": {k: _limpiar(x) for k, x in analitica.kpis(d["productos"], v, dias).items()},
        "tendencia": tabla_json(analitica.tendencia_mensual(v)),
        "top_clientes": tabla_json(analitica.top_clientes(v), limite=20),
        "por_categoria": tabla_json(analitica.por_dimension(v, "categoria")),
    }




@app.get("/stock")
def stock() -> dict:
    _exigir_licencia_vigente()
    d, v = _datos(), _ventas()
    rot = analitica.rotacion(d["productos"], v)
    return {
        "kpis": {
            "skus": int(len(rot)),
            "quiebres": int((rot["stock"] <= 0).sum()),
            "sobrestock": int((rot["dias_stock"] > 90).sum()),
        },
        "rotacion": tabla_json(rot, limite=500),
        "reposicion": tabla_json(sugerencias.reposicion(d["productos"], v), limite=500),
        # Para el filtro por categoría de la pantalla: sale de los datos, no
        # de una lista fija, porque las categorías las pone el ERP del cliente.
        "categorias": sorted(rot["categoria"].dropna().unique().tolist())
        if "categoria" in rot.columns else [],
    }


@app.get("/precios")
def precios() -> dict:
    _exigir_licencia_vigente()
    d, v = _datos(), _ventas()
    pr = sugerencias.precios(d["productos"], v)
    venta = float(v["venta"].sum())
    return {
        "kpis": {
            "margen_ponderado_pct": _limpiar(
                float(v["margen"].sum()) / venta * 100 if venta else 0.0),
            "margen_extra_mensual": _limpiar(
                float(pr["margen_extra_mensual"].sum()) if len(pr) else 0.0),
        },
        "margen_por_producto": tabla_json(analitica.margen_por_producto(v), limite=500),
        "ajustes": tabla_json(pr, limite=500),
    }


@app.get("/zonas")
def zonas(dim: str = "zona") -> dict:
    """La dimensión es un parámetro y no tres endpoints porque la pantalla la
    cambia con un selector. Se valida contra una lista blanca: `por_dimension`
    agrupa por el nombre de columna que reciba, así que sin esta comprobación
    la pantalla podría pedir cualquier columna de la base del cliente."""
    _exigir_licencia_vigente()
    if dim not in ("zona", "departamento", "tipo_negocio"):
        raise HTTPException(400, f"Dimensión no válida: {dim!r}")
    v = _ventas()
    if dim not in v.columns:
        return {"dim": dim, "grupo": tabla_json(None), "oportunidades": tabla_json(None),
                "aviso": f"Los datos conectados no traen {dim} de los clientes."}
    return {
        "dim": dim,
        "grupo": tabla_json(analitica.por_dimension(v, dim)),
        "oportunidades": tabla_json(sugerencias.oportunidades_zona(v), limite=200),
    }


@app.get("/ofertas")
def ofertas() -> dict:
    """El paquete completo, igual que la pantalla: los cinco motores más el
    resumen en pesos. Es el mismo `generar_todas` que alimenta el informe
    exportado, así que la pantalla y el PDF no pueden dar distinto."""
    _exigir_licencia_vigente()
    d = _datos()
    paq = sugerencias.generar_todas(d)
    return {
        "resumen": {k: _limpiar(x) for k, x in paq["resumen"].items()},
        "secciones": {
            clave: {
                "titulo": exportes.TITULOS.get(clave, (clave, ""))[0],
                "descripcion": exportes.TITULOS.get(clave, ("", ""))[1],
                "tabla": tabla_json(paq[clave], limite=400),
            }
            for clave in ("ofertas", "reposicion", "precios", "zonas", "recupero")
        },
    }


@app.get("/clientes/inactivos")
def clientes_inactivos(dias: int = 60) -> dict:
    _exigir_licencia_vigente()
    d, v = _datos(), _ventas()
    return {
        "inactivos": tabla_json(analitica.clientes_inactivos(v, d["clientes"], dias), limite=300),
        "recupero": tabla_json(sugerencias.recupero_clientes(v, d["clientes"]), limite=300),
    }


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@app.get("/rutas/opciones")
def opciones_rutas() -> dict:
    """Lo que la pantalla necesita para armar los filtros antes de planificar."""
    _exigir_licencia_vigente()
    d = _datos()
    deptos = (sorted(d["clientes"]["departamento"].dropna().unique().tolist())
              if "departamento" in d["clientes"].columns else [])
    return {"departamentos": deptos, "habilitado": licencia.tiene("rutas")}


class PedidoRutas(BaseModel):
    vehiculos: int = 2
    paradas_max: int = 25
    departamentos: list[str] = []
    modo: str = "todos"          # activos | inactivos | todos


@app.post("/rutas")
def planificar_rutas(p: PedidoRutas) -> dict:
    # El plan sin rutas no incluye el planificador. Se controla en el servidor
    # y no sólo escondiendo el botón: una pantalla se puede saltear, un
    # endpoint abierto no.
    if not licencia.tiene("rutas"):
        raise HTTPException(403, "El plan actual no incluye el planificador de rutas "
                                 "— disponible en Pro y Enterprise.")
    if p.vehiculos < 1:
        raise HTTPException(400, "Hace falta al menos un vehículo.")

    d, v = _datos(), _ventas()
    base = d["clientes"]
    if p.departamentos and "departamento" in base.columns:
        base = base[base["departamento"].isin(p.departamentos)]

    if p.modo == "inactivos":
        inact = analitica.clientes_inactivos(v, base)[["cliente_id"]]
        objetivo = base.merge(inact, on="cliente_id")
    elif p.modo == "activos":
        corte = v["fecha"].max() - pd.Timedelta(days=30)
        activos = v[v["fecha"] > corte]["cliente_id"].unique()
        objetivo = base[base["cliente_id"].isin(activos)]
    else:
        objetivo = base

    if not len(objetivo):
        raise HTTPException(404, "No hay clientes que cumplan ese filtro.")

    plan = rutas.planificar(objetivo, vehiculos=p.vehiculos, paradas_max=p.paradas_max)
    salida = {clave: tabla_json(df) for clave, df in plan.items()}
    salida["clientes_a_rutear"] = int(len(objetivo))
    return salida


# ---------------------------------------------------------------------------
# Copiloto
# ---------------------------------------------------------------------------
class Consulta(BaseModel):
    pregunta: str


@app.post("/copiloto")
def preguntar(c: Consulta) -> dict:
    if not licencia.tiene("copiloto"):
        raise HTTPException(403, "El plan actual no incluye el Copiloto.")
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


# ---------------------------------------------------------------------------
# Exportes
# ---------------------------------------------------------------------------
_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.get("/exportar/{clave}.{formato}")
def exportar(clave: str, formato: str) -> Response:
    """Descarga de un informe en PDF, Word o Excel.

    El archivo se arma en el servidor con los mismos módulos que ya usa la
    pantalla actual: si se generara en el navegador habría dos versiones del
    informe, y la que el cliente le manda a su proveedor podría no coincidir
    con la que vio en pantalla.
    """
    if formato not in _MIME:
        raise HTTPException(400, f"Formato no soportado: {formato!r}")
    if not licencia.tiene("exportes"):
        raise HTTPException(403, "El plan actual no incluye los exportes.")

    d = _datos()
    paq = sugerencias.generar_todas(d)
    if clave == "completo":
        secciones = exportes.secciones_desde_paquete(paq)
        titulo = "Informe de Plania"
    elif clave in ("ofertas", "reposicion", "precios", "zonas", "recupero"):
        if paq[clave] is None or not len(paq[clave]):
            raise HTTPException(404, "No hay nada para exportar en esa sección.")
        secciones = exportes.secciones_desde_paquete(paq, incluir=[clave])
        titulo = exportes.TITULOS.get(clave, (clave, ""))[0]
    else:
        raise HTTPException(404, f"No hay informe {clave!r}.")

    cuerpo = {"pdf": lambda: exportes.a_pdf(titulo, secciones),
              "docx": lambda: exportes.a_word(titulo, secciones),
              "xlsx": lambda: exportes.a_excel(secciones)}[formato]()
    return Response(
        content=cuerpo, media_type=_MIME[formato],
        headers={"Content-Disposition": f'attachment; filename="plania_{clave}.{formato}"'})


# ---------------------------------------------------------------------------
# Conectar ERP
# ---------------------------------------------------------------------------
class Conexion(BaseModel):
    url: str


@app.post("/erp/probar")
def probar_erp(c: Conexion) -> dict:
    """Prueba la conexión sin guardarla: el usuario tiene que poder verificar
    antes de que toda la aplicación pase a leer de ahí."""
    _exigir_licencia_vigente()
    try:
        eng = conectores.conectar_sql(c.url)
        tablas = conectores.listar_tablas(eng)
        auto = {e: conectores.autodescubrir_tabla(eng, e)
                for e in ("productos", "clientes", "ventas")}
    except Exception as ex:
        raise HTTPException(400, f"No conectó: {ex}")

    # Conectar no alcanza. SQLite crea el archivo si no existe, así que una
    # ruta mal escrita "conecta" contra una base vacía y el usuario lee
    # "Conectado" cuando en realidad apuntó a la nada. Y aunque haya tablas,
    # si no se reconoce ninguna como productos/clientes/ventas, guardar esa
    # conexión deja la aplicación sin datos.
    avisos = []
    if not tablas:
        avisos.append("La conexión abrió pero la base no tiene ninguna tabla. "
                      "Si es SQLite, puede que la ruta esté mal y se haya creado "
                      "un archivo vacío.")
    faltan = [e for e, t in auto.items() if not t]
    if faltan and tablas:
        avisos.append("No se reconocieron las tablas de: " + ", ".join(faltan)
                      + ". Se pueden elegir a mano antes de guardar.")
    return {"ok": True, "tablas": tablas, "autodetectado": auto, "avisos": avisos}


@app.post("/erp/guardar")
def guardar_erp(c: Conexion) -> dict:
    _exigir_licencia_vigente()
    try:
        conectores.conectar_sql(c.url)
    except Exception as ex:
        # Guardar una URL que no conecta deja la aplicación sin datos en el
        # próximo arranque, y el usuario no relaciona una cosa con la otra.
        raise HTTPException(400, f"No se guardó porque no conecta: {ex}")
    pconfig.guardar_extra("ERP_DB_URL", c.url)
    invalidar_cache()
    return {"ok": True}


@app.get("/erp/estado")
def estado_erp() -> dict:
    _exigir_licencia_vigente()
    url = pconfig.leer_extra("ERP_DB_URL") or ""
    return {"conectado": bool(url), "url_enmascarada": pconfig.enmascarar(url) if url else ""}


# ---------------------------------------------------------------------------
# Planes, licencia y configuración
# ---------------------------------------------------------------------------
@app.get("/planes")
def planes() -> dict:
    """Catálogo para la pantalla de compra. Los precios están acá y no en el
    frontend para que no haya dos listas de precios que se desincronicen."""
    return {"planes": [
        {"id": "starter", "titulo": "Starter", "precio": "USD 59/mes",
         "detalle": "Copiloto + ERP + exportes · 500 consultas/mes"},
        {"id": "pro", "titulo": "Pro — recomendado", "precio": "USD 129/mes",
         "detalle": "Todo Starter + rutas + excedente · 2.000 consultas/mes"},
        {"id": "enterprise", "titulo": "Enterprise", "precio": "a medida",
         "detalle": "Multi-sucursal, white label, SSO, SLA"},
    ]}


class Checkout(BaseModel):
    plan: str
    email: str


@app.post("/checkout")
def checkout(c: Checkout) -> dict:
    """Le pide el link de pago al backend de venta y lo devuelve.

    La API local NO emite licencias ni cobra: sólo reenvía. Si emitiera, cada
    cliente tendría en su propia máquina el mecanismo para darse licencias.
    """
    import requests

    backend = os.environ.get("PLANIA_BACKEND_URL") or pconfig.leer_extra("BACKEND_URL")
    if not backend:
        raise HTTPException(503, "No hay backend de venta configurado "
                                 "(PLANIA_BACKEND_URL).")
    try:
        r = requests.post(f"{backend.rstrip('/')}/checkout",
                          json={"plan": c.plan, "email": c.email}, timeout=15)
    except Exception as ex:
        raise HTTPException(502, f"No pude contactar el backend de venta: {ex}")
    if not r.ok:
        try:
            detalle = r.json().get("detail", r.text)
        except Exception:
            detalle = r.text
        raise HTTPException(r.status_code, detalle)
    return r.json()


@app.get("/config")
def leer_config() -> dict:
    """Las claves configurables y si están puestas — nunca su valor.

    Se devuelve el valor enmascarado y no el real: esta respuesta viaja por
    HTTP y queda en el historial de red de la ventana. Que la interfaz no
    pueda mostrar una clave que ya está guardada es a propósito.
    """
    cfg = pconfig.cargar()
    return {
        "backend_activo": pconfig.backend_activo(),
        "claves": [
            {"clave": clave, "descripcion": desc,
             "configurada": bool(cfg.get(clave)),
             "enmascarado": pconfig.enmascarar(cfg.get(clave, "")) if cfg.get(clave) else "",
             "sensible": any(x in clave for x in ("KEY", "TOKEN", "PASSWORD"))}
            for clave, desc in pconfig.CLAVES.items()
        ],
    }


class CambioConfig(BaseModel):
    valores: dict[str, str]


@app.post("/config")
def guardar_config(c: CambioConfig) -> dict:
    # Sólo lo que trae valor: un campo vacío significa "dejalo como está", no
    # "borralo". Guardar los vacíos borraría claves que el usuario ni tocó.
    cambios = {k: v for k, v in c.valores.items()
               if v.strip() and k in pconfig.CLAVES}
    if not cambios:
        return {"ok": True, "guardadas": []}
    pconfig.guardar(cambios)
    pconfig.aplicar()
    invalidar_cache()
    return {"ok": True, "guardadas": sorted(cambios)}


# ---------------------------------------------------------------------------
# Panel del dueño (sólo existe en el build del dueño)
# ---------------------------------------------------------------------------
# `plania/api_owner.py` está en MODULOS_SOLO_OWNER: `preparar_arbol()` lo borra
# antes de compilar el producto, así que en la instalación de un cliente este
# import falla y no se monta nada. No es un permiso que se pueda saltear ni una
# ruta que devuelva 403 — las rutas /owner/* directamente no existen ahí,
# porque el código no está.
#
# Se pregunta si el módulo existe en vez de envolver el import en un
# try/except ImportError: ese except no distingue "el archivo no está" (lo
# normal en el build del cliente) de "el archivo está pero uno de sus imports
# falla" (un bug), y se tragaría el segundo en silencio dejando el panel del
# dueño sin explicación. Con find_spec, si el módulo está y está roto, el
# import de abajo revienta y se ve.
if importlib.util.find_spec("plania.api_owner") is not None:
    from plania import api_owner

    app.include_router(api_owner.router)
