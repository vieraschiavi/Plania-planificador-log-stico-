# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · API del panel del dueño (versión owner)
=================================================
Traduce a JSON lo que hoy dibuja `app/owner.py` en Streamlit, para que la
ventana de escritorio del dueño (Electron/React) muestre lo mismo sin
depender de Streamlit.

Por qué es un módulo aparte y no rutas dentro de `plania/api.py`
----------------------------------------------------------------
Por la misma razón por la que el panel del dueño es un programa aparte y no
un flag de build (ver `packaging/plania.spec` y `packaging/plania_owner.spec`):
el Plania que usa un cliente y el que usa el dueño tienen que poder ser el
mismo archivo, y la manera de garantizarlo es que el código del dueño **no
esté** en el build del cliente, no que esté escondido detrás de un permiso.

Este archivo está en `MODULOS_SOLO_OWNER` (`packaging/proteger_codigo.py`),
así que `preparar_arbol()` lo borra del árbol antes de compilar el producto.
`plania/api.py` lo monta con un import tolerante a que no exista: en el
build del cliente el import falla, no se monta ningún router y la API local
no tiene una sola ruta `/owner/*`. No hay nada que reventar, porque no hay
nada.

De paso resuelve un problema concreto: emitir una licencia manual necesita
`backend_venta.licencias`, y hay un test que prohíbe que ese nombre aparezca
en el texto de `plania/api.py` (`tests/test_plania.py`, la API local no
puede parecerse al backend de venta). Acá no hay conflicto.

Todo lo pesado se calcula por pedido, no al importar: `secciones_para_informe`
corre `simular()` más de quince veces, y en Streamlit eso pasaba en cada
rerun aunque nadie tocara el botón de exportar.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from plania import auditoria as pauditoria
from plania import conectores, contenido, negocio, owner
from plania.api import _limpiar, tabla_json

router = APIRouter(prefix="/owner", tags=["owner"])

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _escalares(d: dict) -> dict:
    """NaN/Infinity y Timestamps fuera, que JSON no los tiene."""
    return {k: _limpiar(v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# Datos del producto (para el kit de contenido)
# ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {}


def _datos_producto() -> dict:
    """Los datos del ERP conectado, cacheados.

    `contenido._cifras()` corre la analítica completa sobre todo el dataset y
    lo llaman cuatro funciones distintas del kit. Sin caché, abrir la pantalla
    de contenido lo recalculaba ocho veces.
    """
    if "datos" not in _CACHE:
        url = os.environ.get("ERP_DB_URL") or None
        _CACHE["datos"] = conectores.cargar_datos(url=url)
    return _CACHE["datos"]


def invalidar_cache() -> None:
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Estado del negocio
# ---------------------------------------------------------------------------
@router.get("/negocio")
def estado_del_negocio() -> dict:
    """El tablero del dueño: demos, clientes pagos, MRR, costos y margen.

    `integridad` no es decorativo: el historial de licencias sale de un log
    encadenado por hash, y si alguien lo editó a mano para inflar las ventas,
    los números de arriba están mintiendo. La pantalla tiene que poder
    decirlo.
    """
    return {
        "kpis": _escalares(owner.kpis_negocio()),
        "integridad": _escalares(owner.integridad_registros()),
    }


# ---------------------------------------------------------------------------
# Clientes y licencias
# ---------------------------------------------------------------------------
@router.get("/licencias")
def clientes_y_licencias() -> dict:
    """Historial de licencias, consumo por cliente y los planes emitibles."""
    from backend_venta import licencias as blic

    uso = owner.uso_por_cliente()
    en_riesgo = []
    if len(uso) and "dias_sin_usar" in uso.columns:
        en_riesgo = sorted(uso[uso["dias_sin_usar"] > 14]["cliente_id"].tolist())
    return {
        "emitidas": tabla_json(owner.licencias_emitidas()),
        "uso": tabla_json(uso),
        # El selectbox de Streamlit usa PLANES completo, no PLANES_PUBLICOS:
        # el plan `owner` no se vende pero sí se emite a mano.
        "planes": sorted(blic.PLANES),
        "clientes_en_riesgo": en_riesgo,
    }


class EmisionManual(BaseModel):
    cliente: str
    plan: str


@router.post("/licencias/emitir")
def emitir_licencia_manual(p: EmisionManual) -> dict:
    """Emite una licencia a mano (venta directa, canje, prueba extendida).

    Escribe: emite un JWT real y lo deja asentado en el log de auditoría. Que
    quede en el log es el punto — es de ahí de donde sale después el historial
    de la pantalla anterior y el MRR del tablero.
    """
    from backend_venta import licencias as blic

    cliente = p.cliente.strip()
    if not cliente:
        raise HTTPException(400, "Falta el email o identificador del cliente.")
    if p.plan not in blic.PLANES:
        raise HTTPException(400, f"No existe el plan {p.plan!r}.")

    token = blic.emitir_licencia(cliente, p.plan)
    pauditoria.registrar("licencia_emitida_manual",
                         {"cliente": cliente, "plan": p.plan})
    return {"ok": True, "token": token, "cliente": cliente, "plan": p.plan}


# ---------------------------------------------------------------------------
# Proyección de rentabilidad
# ---------------------------------------------------------------------------
@router.get("/rentabilidad")
def rentabilidad(escenario: str = "Base", ads: float = 300.0,
                 meses: int = 18) -> dict:
    """Simulación mes a mes del negocio bajo un escenario.

    Los tres parámetros son los tres controles de la pantalla. `detalle` sirve
    para la tabla y también para los dos gráficos: la interfaz no recalcula
    nada, sólo elige qué columnas dibujar.
    """
    if escenario not in negocio.ESCENARIOS:
        raise HTTPException(
            400, f"Escenario desconocido: {escenario!r}. "
                 f"Los que hay son {', '.join(negocio.ESCENARIOS)}.")
    if not 1 <= meses <= 120:
        raise HTTPException(400, "Los meses a simular van de 1 a 120.")
    if ads < 0:
        raise HTTPException(400, "La inversión en redes no puede ser negativa.")

    esc = negocio.ESCENARIOS[escenario]
    df = negocio.simular(esc, meses=meses, inversion_ads_mes=float(ads))
    # Se calcula una vez: la pantalla de Streamlit la llamaba tres veces por
    # render para mostrar el mismo número.
    caja_min = negocio.caja_minima(df)

    return {
        "escenario": dataclasses.asdict(esc),
        "escenarios": sorted(negocio.ESCENARIOS),
        "hitos": {
            "mes_equilibrio": negocio.mes_de_equilibrio(df),
            "mes_supera_sueldo": negocio.mes_supera_sueldo(df),
            "caja_minima": _limpiar(caja_min),
            "sueldo_referencia": negocio.SUELDO_REFERENCIA_EMPLEADO,
        },
        "unit_economics": _escalares(
            negocio.unit_economics(esc, float(ads), df)),
        "horizontes": tabla_json(negocio.resumen_horizontes(df)),
        "detalle": tabla_json(df),
    }


# ---------------------------------------------------------------------------
# Mercado y competencia
# ---------------------------------------------------------------------------
def _sensibilidad_json(variable: str, valores: list) -> dict:
    """`sensibilidad()` nombra su primera columna como la variable simulada.

    Un nombre de columna que cambia según el parámetro obliga a la interfaz a
    adivinar cuál es; se renombra a `valor` y la variable viaja aparte.
    """
    df = negocio.sensibilidad(variable, valores)
    if len(df) and variable in df.columns:
        df = df.rename(columns={variable: "valor"})
    return {"variable": variable, "tabla": tabla_json(df)}


@router.get("/mercado")
def mercado_y_competencia() -> dict:
    """Tamaño de mercado (TAM/SAM/SOM) y cuánto mueve cada supuesto."""
    return {
        "potencial": tabla_json(negocio.potencial_mercados()),
        "mercados": {n: _escalares(m) for n, m in negocio.MERCADOS.items()},
        "sensibilidades": [
            _sensibilidad_json("churn_mensual", [0.015, 0.02, 0.03, 0.045, 0.06]),
            _sensibilidad_json("conv_demo_cliente", [0.08, 0.12, 0.16, 0.20, 0.28]),
        ],
    }


# ---------------------------------------------------------------------------
# Contenido para redes
# ---------------------------------------------------------------------------
@router.get("/contenido")
def kit_de_contenido(pauta: float = 300.0) -> dict:
    """Posts, guiones, mensajes, calendario y reparto de pauta.

    `sobre_datos_demo` decide si la interfaz muestra el aviso de que las
    cifras salen de la base de ejemplo. Publicar como reales números que no lo
    son es publicidad engañosa (Ley 17.250), así que el aviso no es opcional
    ni cosmético.
    """
    if pauta < 0:
        raise HTTPException(400, "La inversión en pauta no puede ser negativa.")
    datos = _datos_producto()
    return {
        "sobre_datos_demo": contenido._sobre_datos_demo(),
        "aviso_demo": contenido.AVISO_DEMO,
        "linkedin": tabla_json(contenido.posts_linkedin(datos)),
        "video": tabla_json(contenido.guiones_video(datos)),
        "prospeccion": tabla_json(contenido.mensajes_prospeccion(datos)),
        "calendario": tabla_json(contenido.calendario(datos)),
        "pauta": tabla_json(contenido.presupuesto_pauta(float(pauta))),
    }


# ---------------------------------------------------------------------------
# Verificación del producto
# ---------------------------------------------------------------------------
@router.post("/verificacion")
def verificar() -> dict:
    """Corre la cadena completa del producto y devuelve el resultado.

    Es POST y no GET a propósito: esto no consulta, ejecuta. Emite licencias
    de prueba, escribe configuración y levanta la app en memoria. Un GET
    invita a que un navegador o un proxy lo repita solo.
    """
    from plania import verificacion

    resultados = verificacion.verificar_todo()
    return {
        "resumen": _escalares(verificacion.resumen(resultados)),
        "tabla": tabla_json(verificacion.tabla(resultados)),
    }


# ---------------------------------------------------------------------------
# Exportes
# ---------------------------------------------------------------------------
def _secciones(clave: str, meses: int) -> tuple[str, list]:
    if clave == "negocio":
        return "Estado del negocio", owner.secciones_para_informe_owner()
    if clave == "rentabilidad":
        return "Proyección de rentabilidad", negocio.secciones_para_informe(meses=meses)
    if clave == "contenido":
        return "Kit de contenido", contenido.secciones_para_kit(_datos_producto())
    raise HTTPException(404, f"No hay informe {clave!r}.")


@router.get("/exportar/{clave}.{formato}")
def exportar_owner(clave: str, formato: str, meses: int = 18) -> Response:
    """PDF, Word o Excel de un informe del panel.

    Se arma recién cuando alguien lo pide. En Streamlit los tres formatos se
    generaban en cada render aunque nadie tocara un botón, y el de
    rentabilidad corre la simulación más de quince veces.
    """
    from plania import exportes

    if formato not in _MIME:
        raise HTTPException(400, f"Formato no soportado: {formato!r}")
    titulo, secciones = _secciones(clave, meses)
    cuerpo = {"pdf": lambda: exportes.a_pdf(titulo, secciones),
              "docx": lambda: exportes.a_word(titulo, secciones),
              "xlsx": lambda: exportes.a_excel(secciones)}[formato]()
    return Response(
        content=cuerpo, media_type=_MIME[formato],
        headers={"Content-Disposition":
                 f'attachment; filename="plania_owner_{clave}.{formato}"'})

