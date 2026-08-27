#!/usr/bin/env python3
# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Activar la VERSIÓN FULL en esta máquina (edición del dueño)
====================================================================
Deja esta PC con exactamente lo mismo que recibe un cliente que paga el plan
más alto: las ocho features (`copiloto`, `erp`, `exportes`, `rutas`,
`excedente`, `white_label`, `sso`, `multi_sucursal`), sin cupo mensual y sin
vencimiento práctico (100 años).

    python3 INSTALADOR_OWNER/activar_owner.py            # activar
    python3 INSTALADOR_OWNER/activar_owner.py --estado   # ver cómo está
    python3 INSTALADOR_OWNER/activar_owner.py --desactivar

## Por qué acá no hay ninguna licencia guardada, y no puede haberla

El repositorio es **público**. Una licencia `owner` ya emitida es acceso
total, gratis, para siempre, para cualquiera que la copie de acá — que es
justo el agujero que se cerró cuando `plania/licencia.py` dejó de aceptar
tokens sin verificar la firma (ver el docstring de ese módulo).

Por eso este archivo **emite la licencia en el momento, en tu máquina**, y no
la trae escrita. El secreto de firma sale de `backend_venta/licencias.py::
secreto_firma`, que en esta PC se genera solo la primera vez y queda en tu
config (`~/.plania`). Nunca viaja al repositorio. Dos máquinas distintas
generan secretos distintos: el token que sale de acá **no le sirve a nadie
más**, ni siquiera a vos en otra PC.

## Por qué no alcanza con escribir el token en la config y listo

Porque el programa no le cree a un token porque el token "diga" `plan=owner`:
le cree porque `activar_licencia()` se lo pregunta a quien lo firmó
(`GET /licencias/estado`) y guarda **las claims que devolvió el backend**, no
las del token. Saltarse ese paso escribiendo la config a mano dejaría esta
carpeta probando un camino que ningún cliente recorre — y el día que el
circuito real se rompa, acá seguiría "andando".

Así que se recorre el circuito completo, igual que un cliente que paga, con
una sola diferencia: en vez de salir a internet, se le habla al backend
**dentro de este mismo proceso** (el `TestClient` de Starlette, que
`activar_licencia()` acepta por el parámetro `cliente_http` justamente para
esto). No hace falta levantar el servidor, ni abrir un puerto, ni tener
internet.

## Cuánto dura

`plania/licencia.py` re-confirma la licencia contra el backend cada 24 h. Sin
un backend escuchando, tolera `_TOLERANCIA_SIN_RED_DIAS` (10 días) y después
la suelta. Entonces:

- **Sin hacer nada más**: la versión full anda 10 días. Volvés a correr esto
  (doble clic) y se renuevan.
- **Para que no expire nunca**: dejá el backend local corriendo
  (`./run.sh backend`, o `uvicorn backend_venta.app:app --port 8100`). Ahí la
  re-confirmación de cada 24 h encuentra a quién preguntarle y la licencia se
  renueva sola, porque `PLANIA_BACKEND_URL` sin configurar ya apunta a
  `http://localhost:8100`.

## Alcance: esto es el PRODUCTO full, no el panel del dueño

Son dos cosas distintas y conviene no mezclarlas:

- **Lo que activa este archivo** es el programa que usa el cliente
  (`app/app.py`), desbloqueado al máximo. Es lo que pediste: probar la
  versión completa.
- **El panel del dueño** (`app/owner.py` — facturación, clientes, márgenes)
  es otro programa, se arma aparte con `python packaging/build_release.py
  --con-owner` y no se publica en este repositorio. Ver `INSTALADOR/README.md`.
"""
from __future__ import annotations

import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# El titular que queda registrado en la licencia. No se valida contra ningún
# padrón: es una etiqueta para saber de quién es la instalación cuando la
# pantalla "Planes y licencia" muestra el cliente.
EMAIL_POR_DEFECTO = "owner@plania.uy"

FEATURES_FULL = ["copiloto", "erp", "exportes", "rutas",
                 "excedente", "white_label", "sso", "multi_sucursal"]


def _emitir_y_verificar(email: str) -> dict:
    """Emite una licencia `owner` y la activa por el circuito real.

    Devuelve el mismo dict que `plania.licencia.activar_licencia`.
    """
    from starlette.testclient import TestClient

    from backend_venta import licencias
    from backend_venta.app import app
    from plania import licencia as plicencia

    token = licencias.emitir_licencia(email, "owner")
    # backend_url="" para que la URL quede en "/licencias/estado", que es lo
    # que entiende el TestClient; el cliente inyectado hace que no se abra
    # ningún socket.
    return plicencia.activar_licencia(token, backend_url="", cliente_http=TestClient(app))


def activar(email: str = EMAIL_POR_DEFECTO) -> int:
    r = _emitir_y_verificar(email)
    if not r["ok"]:
        print(f"\n  [X] No se pudo activar: {r.get('error')}")
        print(f"      (motivo: {r.get('motivo')})")
        return 1

    claims = r["claims"]
    faltan = [f for f in FEATURES_FULL if f not in claims.get("features", [])]
    if faltan:
        # Si el plan `owner` dejara de traer alguna feature, es mejor enterarse
        # acá que descubrirlo probando la pantalla que no abre.
        print(f"\n  [X] La licencia salió incompleta, le faltan: {', '.join(faltan)}")
        return 1

    print(f"\n  [OK] Versión FULL activada para {claims.get('cliente')}.")
    print(f"       plan .......... {claims.get('plan')}")
    print(f"       features ...... {len(claims['features'])}: "
          f"{', '.join(claims['features'])}")
    print(f"       cupo mensual .. {claims.get('cupo_mensual') or 'sin tope'}")
    _avisar_vigencia()
    print("\n  Abrí el programa:  ./run.sh app     (o INICIAR_PLANIA.bat en Windows)")
    print("  En 'Planes y licencia' tiene que decir plan owner.\n")
    return 0


def _avisar_vigencia() -> None:
    """Decir cuánto dura de verdad, que no es lo mismo que lo que dice el token.

    El JWT vence en 100 años, pero sin un backend al que re-preguntarle la
    licencia se suelta a los 10 días (ver el encabezado de este archivo).
    Prometer "100 años" a secas sería mentir por omisión.
    """
    from plania import licencia as plicencia

    print(f"\n       Dura {plicencia._TOLERANCIA_SIN_RED_DIAS} días sin backend "
          f"corriendo; volvé a correr esto y se renueva.")
    print("       Para que no expire nunca, dejá el backend local levantado:")
    print("         ./run.sh backend")


def desactivar() -> int:
    """Vuelve esta instalación a como estaba (demo o demo vencida)."""
    from plania import licencia as plicencia

    antes = plicencia.estado()
    if antes["modo"] != "licencia":
        print(f"\n  Esta instalación no tiene licencia activa (está en "
              f"'{antes['modo']}'). No hay nada que desactivar.\n")
        return 0

    # `_olvidar_licencia` es privada a propósito: borrar la licencia no es una
    # operación que la app le ofrezca al usuario. Acá se usa porque este
    # archivo es herramienta del dueño, no producto.
    plicencia._olvidar_licencia()
    despues = plicencia.estado()
    print(f"\n  [OK] Licencia borrada. Esta instalación quedó en "
          f"'{despues['modo']}'.\n")
    return 0


def mostrar_estado() -> int:
    from plania import licencia as plicencia

    e = plicencia.estado()
    print(f"\n  modo ........... {e['modo']}")
    print(f"  plan ........... {e['plan']}")
    print(f"  cliente ........ {e['cliente'] or '-'}")
    print(f"  días restantes . {e['dias_restantes']}")
    print(f"  features ....... {len(e['features'])}: "
          f"{', '.join(e['features']) or '-'}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Activa la versión FULL de Plania en esta máquina.")
    p.add_argument("--email", default=EMAIL_POR_DEFECTO,
                   help=f"titular de la licencia (default: {EMAIL_POR_DEFECTO})")
    p.add_argument("--desactivar", action="store_true",
                   help="borra la licencia y vuelve a demo")
    p.add_argument("--estado", action="store_true",
                   help="muestra cómo está esta instalación, sin tocar nada")
    a = p.parse_args(argv)

    if a.desactivar:
        return desactivar()
    if a.estado:
        return mostrar_estado()
    return activar(a.email)


if __name__ == "__main__":
    raise SystemExit(main())
