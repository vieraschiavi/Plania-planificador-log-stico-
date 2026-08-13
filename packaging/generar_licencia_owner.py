# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Licencia sin restricciones para el dueño del producto
================================================================
Emite un JWT con `plan="owner"`: todas las features, sin cupo mensual, y
vigencia de 100 años (en la práctica, no vence). Pegala en la app —
"Planes y licencia" → "Ya tengo mi licencia" — y esa instalación queda
sin las restricciones del trial ni de ningún plan pago.

    python3 packaging/generar_licencia_owner.py vos@tu-dominio.uy

## Por qué esto no es (ni puede ser) un archivo para publicar en GitHub

El token solo sirve si lo firma el mismo secreto que usa tu `backend_venta`
desplegado (`PLANIA_LICENSE_SECRET`, o el que se generó solo la primera vez
que corrió — ver `backend_venta/licencias.py::secreto_firma`): la app nunca
confía en un token porque "dice" plan=owner, lo confía porque al activarlo
consulta `GET /licencias/estado` contra ESE backend y el backend lo valida
con ESE secreto (ver `plania/licencia.py`, sección "Por qué activar_licencia()
llama al backend").

Publicar un token ya generado en un repo público (o en un Release de GitHub)
significaría publicar una licencia completa, gratis, para siempre, para
cualquiera que la descargue — exactamente el agujero que se cerró al dejar
de aceptar licencias sin verificar la firma. Por eso este archivo es un
GENERADOR, no una licencia: lo corrés vos, en tu máquina o donde tengas
acceso al secreto real, y el resultado —el token— es tuyo y no se comitea
ni se sube a ningún lado.

Lo que SÍ es público en GitHub es todo lo demás: el instalador (Releases),
el código de este generador, y el circuito completo — igual que cualquier
cliente que paga, con la diferencia de que tu licencia la generás vos en vez
de comprarla.

## Modo remoto (si el backend ya está desplegado y preferís no tocar su secreto)

Si no tenés (o no querés tener) acceso directo al secreto de firma en esta
máquina, la alternativa es pedírsela al backend ya desplegado, autenticado
con el token de administrador (`PLANIA_BACKEND_ADMIN_TOKEN` — ver
`backend_venta/app.py::requerir_admin`):

    curl -X POST https://api.tu-dominio.uy/licencias/emitir \\
      -H "Authorization: Bearer $PLANIA_BACKEND_ADMIN_TOKEN" \\
      -H "Content-Type: application/json" \\
      -d '{"cliente_id": "vos@tu-dominio.uy", "plan": "owner"}'

Las dos vías emiten exactamente lo mismo — elegí la que tengas más a mano.
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def main() -> int:
    if len(sys.argv) < 2 or "@" not in sys.argv[1]:
        print("Uso: python3 packaging/generar_licencia_owner.py vos@tu-dominio.uy")
        return 1

    from backend_venta import licencias

    email = sys.argv[1].strip().lower()
    token = licencias.emitir_licencia(email, "owner")
    anios = licencias.PLANES["owner"]["dias"] // 365

    print(f"\nLicencia owner para {email} — vigencia {anios} años, sin cupo, "
          f"todas las features:\n")
    print(token)
    print(f"\nActivala en Plania → \"Planes y licencia\" → \"Ya tengo mi "
          f"licencia\", con el backend de esta máquina configurado "
          f"(PLANIA_BACKEND_URL) apuntando a donde vive este mismo secreto de "
          f"firma. No la subas a git ni la compartas: quien la tenga tiene "
          f"acceso total, sin pagar, por 100 años.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
