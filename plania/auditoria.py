"""
Plania · Log de auditoría (append-only, con cadena de hashes)
=============================================================
Registro de **quién hizo qué y cuándo**, separado de los datos de negocio
(datos del ERP conectado). Pensado para que una
auditoría externa (o el propio dueño del negocio) pueda reconstruir la
actividad del dashboard: logins, cambios de configuración/contraseña,
consultas del copiloto, exportes/sincronizaciones al ERP.

Cada entrada encadena un hash SHA-256 de la entrada anterior (estilo
blockchain simplificado, sin red ni consenso): editar o borrar una línea del
archivo rompe la cadena a partir de ahí, así que `verificar_integridad()`
detecta manipulación del log. No reemplaza un SIEM/WORM storage real para un
banco grande, pero es una mejora real y verificable sobre "no hay ningún
registro de quién hizo qué".

Formato: JSON Lines (`data/auditoria.log`), una entrada por línea:
    {"ts", "usuario", "rol", "accion", "detalle", "hash_prev", "hash"}
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from datetime import datetime, timezone

import portalocker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.environ.get("PLANIA_AUDIT_LOG", os.path.join(ROOT, "data", "auditoria.log"))
GENESIS_HASH = "0" * 64


def _usuario_actual() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "desconocido"


def _ultimo_hash(archivo: str) -> str:
    if not os.path.exists(archivo):
        return GENESIS_HASH
    ultimo = GENESIS_HASH
    with open(archivo, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                ultimo = json.loads(linea)["hash"]
            except Exception:
                continue
    return ultimo


def _calcular_hash(ts: str, usuario: str, rol: str, accion: str, detalle: dict, hash_prev: str) -> str:
    payload = json.dumps(
        {"ts": ts, "usuario": usuario, "rol": rol, "accion": accion,
         "detalle": detalle, "hash_prev": hash_prev},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def registrar(accion: str, detalle: dict | None = None, usuario: str | None = None,
             rol: str | None = None, archivo: str = LOG_FILE) -> dict:
    """
    Agrega una entrada al log de auditoría. Devuelve la entrada escrita.

    Encadenar el hash exige leer la última entrada y escribir la nueva como
    una sola operación atómica: con escrituras concurrentes (varias
    sesiones/requests al mismo tiempo, ej. el gateway de `backend_venta`),
    dos threads/procesos podrían leer el mismo "último hash" antes de que
    ninguno escriba, rompiendo la cadena. Se usa un lock de archivo
    (`portalocker`, funciona igual en Windows/macOS/Linux) para serializar
    el read-then-write entre threads y entre procesos distintos.
    """
    detalle = detalle or {}
    usuario = usuario or _usuario_actual()
    rol = rol or "desconocido"
    os.makedirs(os.path.dirname(archivo), exist_ok=True)

    with portalocker.Lock(archivo + ".lock", timeout=10):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        hash_prev = _ultimo_hash(archivo)
        hash_actual = _calcular_hash(ts, usuario, rol, accion, detalle, hash_prev)
        entrada = {"ts": ts, "usuario": usuario, "rol": rol, "accion": accion,
                   "detalle": detalle, "hash_prev": hash_prev, "hash": hash_actual}
        with open(archivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    return entrada


def leer(archivo: str = LOG_FILE, limite: int | None = None) -> list[dict]:
    """Lee las entradas del log, en orden. `limite`: solo las últimas N."""
    if not os.path.exists(archivo):
        return []
    entradas = []
    with open(archivo, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                entradas.append(json.loads(linea))
            except Exception:
                continue
    return entradas[-limite:] if limite else entradas


def verificar_integridad(archivo: str = LOG_FILE) -> dict:
    """
    Recorre la cadena de hashes y confirma que nadie editó/borró/insertó
    líneas por fuera de este módulo. Devuelve:
        {"ok": bool, "entradas": int, "primer_error": int | None}
    """
    entradas = leer(archivo)
    hash_prev = GENESIS_HASH
    for i, e in enumerate(entradas):
        if e.get("hash_prev") != hash_prev:
            return {"ok": False, "entradas": len(entradas), "primer_error": i}
        esperado = _calcular_hash(e["ts"], e["usuario"], e["rol"], e["accion"],
                                  e["detalle"], e["hash_prev"])
        if e.get("hash") != esperado:
            return {"ok": False, "entradas": len(entradas), "primer_error": i}
        hash_prev = e["hash"]
    return {"ok": True, "entradas": len(entradas), "primer_error": None}
