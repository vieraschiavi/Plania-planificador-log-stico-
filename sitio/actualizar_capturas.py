# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Regenera las capturas de pantalla del producto
=========================================================
Deja `assets/capturas/*.png` sacadas de la app REAL corriendo, con
`page.screenshot(full_page=True)`: la altura de la captura la decide el
contenido de la página, así que un título o una tabla no pueden quedar
cortados por un marco fijo. Es la misma idea que ya usa
`sitio/grabar_demo.py` para el video, aplicada a capturas fijas.

    python3 sitio/actualizar_capturas.py

Por qué hacía falta un script y no bastaba con sacarlas a mano una vez: las
diez capturas de `assets/capturas/` se habían tomado el 13/07 y quedaron sin
tocar. El 03/08 se corrigió `_fmt()` en `app/app.py` —los montos se
abreviaban a K/M porque Streamlit los cortaba con "…" en una fila de cinco
tarjetas— pero nadie volvió a sacar las capturas: seguían mostrando el
`$689,…` que el propio código ya no produce. Sin un script que las
regenere, cualquier cambio de la interfaz vuelve a desincronizarlas en
silencio.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "assets", "capturas")
ANCHO = 1440

PUERTO_APP = int(os.environ.get("PLANIA_PUERTO_CAPTURAS", "8711"))
PUERTO_OWNER = int(os.environ.get("PLANIA_PUERTO_CAPTURAS_OWNER", "8601"))
TOKEN_OWNER = "captura-" + os.urandom(4).hex()

# (etiqueta del menú, archivo de salida, acción extra opcional)
PAGINAS_APP = [
    ("Inicio", "inicio.png", None),
    ("Panel ejecutivo", "panel.png", None),
    ("Stock y reposición", "stock.png", None),
    ("Zonas y negocios", "zonas.png", None),
    ("Ofertas y sugerencias", "ofertas.png", None),
    ("Copiloto IA", "copiloto.png", "consulta"),
    ("Planes y licencia", "planes.png", None),
]
CONSULTA = "¿qué ofertas armo esta semana?"

PAGINAS_OWNER = [
    ("Estado del negocio", "owner_negocio.png", None),
    ("Proyección de rentabilidad", "owner_rentabilidad.png", None),
    ("Verificación del producto", "owner_verificacion.png", "verificar"),
]


def _esperar(url: str, intentos: int = 90) -> bool:
    import urllib.request
    for _ in range(intentos):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(1)
    return False


def _levantar(script: str, puerto: int, env_extra: dict) -> subprocess.Popen:
    env = dict(os.environ, **env_extra)
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", script,
         "--server.port", str(puerto), "--server.headless", "true"],
        cwd=RAIZ, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _capturar(pagina, etiqueta: str, archivo: str, extra: str | None) -> None:
    try:
        pagina.get_by_text(etiqueta, exact=True).first.click()
    except Exception as e:
        print(f"  ! no pude abrir '{etiqueta}': {e}")
        return
    time.sleep(2.5)

    if extra == "consulta":
        try:
            caja = pagina.get_by_placeholder("Escribí tu consulta…")
            caja.click()
            caja.fill(CONSULTA)
            pagina.keyboard.press("Enter")
            time.sleep(6)   # el copiloto local responde solo, sin red
        except Exception as e:
            print(f"  ! consulta del copiloto: {e}")
    elif extra == "verificar":
        try:
            pagina.get_by_text("Ejecutar verificación end-to-end", exact=True).click()
            # Corre 13+ controles reales contra el motor (carga de datos,
            # sugerencias, copiloto, exportes, rutas): más lento que un
            # simple re-render, y un tiempo fijo corto dejaba la tabla de
            # resultados vacía en la captura. "detalle" es la cabecera de esa
            # tabla — sólo existe una vez que el resultado ya se dibujó.
            # state="attached" y no "visible": la grilla la pinta un canvas
            # (glide-data-grid), así que la cabecera real vive en una capa de
            # accesibilidad que Playwright considera oculta a propósito.
            pagina.get_by_text("detalle", exact=True).wait_for(
                state="attached", timeout=20000)
            time.sleep(2)
        except Exception as e:
            print(f"  ! no se pudo ejecutar la verificación: {e}")

    # full_page=True: la captura sigue al contenido real, no a un marco de
    # alto fijo — así un título no puede quedar cortado en el borde.
    destino = os.path.join(SALIDA, archivo)
    pagina.screenshot(path=destino, full_page=True)
    print(f"  -> {os.path.relpath(destino, RAIZ)}")


def _aceptar_eula(pagina) -> None:
    """Tilda y confirma el EULA si la instancia todavía no lo tiene aceptado.

    Se acepta una sola vez por corrida del script: `EULA_ACEPTADA` queda en
    la configuración persistida del servidor (no en la sesión del navegador),
    así que sesiones siguientes contra el mismo proceso ya no la muestran.
    """
    try:
        casilla = pagina.get_by_text("Leí y acepto los términos de uso de Plania.")
        casilla.wait_for(timeout=4000)
    except Exception:
        return   # ya estaba aceptado: el menú se ve directo
    casilla.click()
    pagina.get_by_text("Continuar", exact=True).click()
    time.sleep(2)


def _sesion(navegador, puerto: int, ancho: int):
    contexto = navegador.new_context(viewport={"width": ancho, "height": 900})
    pagina = contexto.new_page()
    pagina.goto(f"http://localhost:{puerto}", wait_until="networkidle")
    time.sleep(4)
    _aceptar_eula(pagina)
    time.sleep(2)   # que termine de cargar los datos y dibujar los primeros gráficos
    return contexto, pagina


def _refrescar_demo() -> None:
    """Reinicia la demo de 7 días de esta instancia si ya venció.

    Las capturas son la cara del producto en el README: tienen que mostrar
    el panel funcionando, no el cartel de "demo vencida" que deja cualquier
    corrida vieja de la app o de la suite de tests en esta misma máquina.
    """
    sys.path.insert(0, RAIZ)
    from datetime import datetime, timezone

    from plania import config as pconfig
    pconfig.guardar_extra("DEMO_INICIO", datetime.now(timezone.utc).isoformat())


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SALIDA, exist_ok=True)
    if not os.path.exists(os.path.join(RAIZ, "data", "erp_demo.db")):
        print("Falta data/erp_demo.db. Corré antes: python3 data/generate_dataset.py --seed 42")
        return 1
    _refrescar_demo()

    print(f"[app] levantando en :{PUERTO_APP}…")
    proc_app = _levantar("app/app.py", PUERTO_APP, {})
    print(f"[owner] levantando en :{PUERTO_OWNER}…")
    proc_owner = _levantar("app/owner.py", PUERTO_OWNER, {"PLANIA_OWNER_TOKEN": TOKEN_OWNER})

    try:
        if not _esperar(f"http://localhost:{PUERTO_APP}"):
            print("[app] no arrancó a tiempo.")
            return 1
        if not _esperar(f"http://localhost:{PUERTO_OWNER}"):
            print("[owner] no arrancó a tiempo.")
            return 1

        with sync_playwright() as p:
            ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
            navegador = (p.chromium.launch(executable_path=ejecutable)
                         if os.path.exists(ejecutable) else p.chromium.launch())

            print("\n[capturas] app del cliente")
            ctx, pag = _sesion(navegador, PUERTO_APP, ANCHO)
            for etiqueta, archivo, extra in PAGINAS_APP:
                _capturar(pag, etiqueta, archivo, extra)
            ctx.close()

            print("\n[capturas] panel del dueño")
            ctx, pag = _sesion(navegador, PUERTO_OWNER, ANCHO)
            campo = pag.get_by_label("Token de acceso")
            campo.fill(TOKEN_OWNER)
            pag.get_by_text("Entrar", exact=True).click()
            time.sleep(2)
            for etiqueta, archivo, extra in PAGINAS_OWNER:
                _capturar(pag, etiqueta, archivo, extra)
            ctx.close()

            navegador.close()
    finally:
        proc_app.terminate()
        proc_owner.terminate()
        proc_app.wait(timeout=10)
        proc_owner.wait(timeout=10)

    print("\nListo. Revisá assets/capturas/ antes de commitear —"
          " son las que se ven en README.md.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
