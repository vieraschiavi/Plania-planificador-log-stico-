"""
Plania · Verificación de que la web no se solapa
================================================
Abre las tres versiones de idioma en tres anchos reales y comprueba, con
mediciones del navegador y no a ojo, que nada se pisa.

    python3 sitio/verificar_layout.py            # informe
    python3 sitio/verificar_layout.py --capturas # además deja los PNG

Por qué hace falta un control automático y no alcanza con mirar:
el sitio se genera en tres idiomas desde la misma plantilla, y el mismo
texto ocupa distinto: en inglés y en portugués los títulos y botones de
Plania corren entre 15% y 35% más largos que en español. Un botón que en
español entra justo, en portugués se sale de la tarjeta. Revisar eso a ojo
en 3 idiomas x 3 anchos son 9 pantallas por cada cambio de texto; medirlo
tarda tres segundos y no se olvida de ninguna.

Qué se controla:

  1. **Scroll horizontal**: la página nunca puede ser más ancha que la
     pantalla. Es el síntoma más visible de un desborde.
  2. **Desborde de la ventana**: ningún elemento puede terminar a la derecha
     del borde.
  3. **Texto cortado**: ningún elemento con `overflow:hidden` puede tener más
     contenido del que muestra (texto comido con "…" o directamente tapado).
  4. **Hermanos superpuestos**: dentro de cada grilla o fila, dos elementos
     no pueden compartir píxeles. Esta es la comprobación literal de "sin
     solapamientos".
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "web")
CAPTURAS = os.path.join(RAIZ, "sitio", "capturas")

IDIOMAS = ["es", "en", "pt"]
# Celular chico, tablet y escritorio. 360 es el ancho real más angosto que
# todavía tiene tráfico; si entra ahí, entra en todo lo de arriba.
ANCHOS = [(360, 780, "celular"), (768, 1024, "tablet"), (1440, 900, "escritorio")]

# Contenedores cuyos hijos comparten fila o grilla: son los que pueden
# pisarse si un texto crece.
CONTENEDORES = [
    ".top-in", ".nav", ".top-acc", ".lang", ".kpis", ".cta-row",
    ".grid-f", ".grid-p", ".grid-d", ".vid-lang", ".f2", ".pie-in",
]

# Medición dentro del navegador. Devuelve la lista de problemas encontrados.
SONDA = r"""
(sel) => {
  const W = window.innerWidth, fallas = [];
  const visible = (r, el) => {
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const nombre = el => el.tagName.toLowerCase() +
    (el.id ? "#" + el.id : "") +
    (el.className && typeof el.className === "string"
      ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : "");

  // Etiquetas que existen solo para el lector de pantalla: están recortadas a
  // un píxel a propósito, no son texto tapado.
  const soloLector = el => {
    const r = el.getBoundingClientRect();
    return r.width <= 2 || r.height <= 2;
  };

  // Un elemento ancho dentro de un contenedor que scrollea de costado no es
  // un desborde: es exactamente el recurso que se usa para que la tabla
  // comparativa se pueda leer en un celular sin romper la página. Lo que sí
  // sería un problema —que la página entera scrollee— lo cubre el control 1.
  const enScrollable = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
    return false;
  };

  // 1. scroll horizontal de la página
  if (document.documentElement.scrollWidth > W + 1) {
    fallas.push({tipo: "scroll-horizontal",
                 detalle: document.documentElement.scrollWidth + "px > " + W + "px"});
  }

  // 2. elementos que terminan fuera de la ventana
  document.querySelectorAll("body *").forEach(el => {
    const r = el.getBoundingClientRect();
    if (!visible(r, el)) return;
    if (getComputedStyle(el).position === "fixed") return;
    if (enScrollable(el)) return;
    if (r.right > W + 1) {
      fallas.push({tipo: "fuera-de-pantalla", el: nombre(el),
                   detalle: "termina en " + Math.round(r.right) + "px"});
    }
  });

  // 3. texto recortado por el contenedor
  document.querySelectorAll("body *").forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.overflowX === "auto" || cs.overflowX === "scroll") return;
    if (cs.overflow === "visible" || soloLector(el)) return;
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      fallas.push({tipo: "texto-cortado", el: nombre(el),
                   detalle: el.scrollWidth + "px de contenido en " + el.clientWidth + "px"});
    }
  });

  // 4. hijos que se pisan entre sí, o que se salen de su contenedor.
  // A propósito NO se excluye lo posicionado en absoluto: un elemento sacado
  // del flujo es justamente la forma más común de terminar pisando a otro.
  sel.forEach(s => {
    document.querySelectorAll(s).forEach(cont => {
      const rc = cont.getBoundingClientRect();
      const hijos = [...cont.children].filter(h => visible(h.getBoundingClientRect(), h));

      hijos.forEach(h => {
        const r = h.getBoundingClientRect();
        if (enScrollable(h)) return;
        if (r.right > rc.right + 2 || r.left < rc.left - 2) {
          fallas.push({tipo: "se-sale-del-contenedor", el: s,
                       detalle: nombre(h) + " ocupa " + Math.round(r.left) + "-" +
                                Math.round(r.right) + "px dentro de " +
                                Math.round(rc.left) + "-" + Math.round(rc.right) + "px"});
        }
      });

      for (let i = 0; i < hijos.length; i++) {
        for (let j = i + 1; j < hijos.length; j++) {
          const a = hijos[i].getBoundingClientRect(), b = hijos[j].getBoundingClientRect();
          const ancho = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const alto = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (ancho > 1 && alto > 1) {
            fallas.push({tipo: "superpuestos", el: s,
                         detalle: nombre(hijos[i]) + " pisa " + nombre(hijos[j]) +
                                  " en " + Math.round(ancho) + "x" + Math.round(alto) + "px"});
          }
        }
      }
    });
  });
  return fallas;
}
"""


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # el servidor de prueba no ensucia el informe
        pass

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)


def servir() -> tuple[socketserver.TCPServer, int]:
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Silencioso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturas", action="store_true", help="guardar los PNG en sitio/capturas")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(WEB, "es", "index.html")):
        print("Falta la web generada. Corré antes: python3 sitio/build.py")
        return 1

    from playwright.sync_api import sync_playwright

    srv, puerto = servir()
    if args.capturas:
        os.makedirs(CAPTURAS, exist_ok=True)

    total = 0
    try:
        with sync_playwright() as p:
            ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
            nav = (p.chromium.launch(executable_path=ejecutable)
                   if os.path.exists(ejecutable) else p.chromium.launch())
            for idioma in IDIOMAS:
                for ancho, alto, etiqueta in ANCHOS:
                    ctx = nav.new_context(viewport={"width": ancho, "height": alto},
                                          locale=idioma, device_scale_factor=1)
                    pag = ctx.new_page()
                    pag.goto(f"http://127.0.0.1:{puerto}/{idioma}/", wait_until="load")
                    pag.wait_for_timeout(700)

                    fallas = pag.evaluate(SONDA, CONTENEDORES)
                    marca = "OK  " if not fallas else "FALLA"
                    print(f"  {marca} {idioma} · {etiqueta} ({ancho}px)"
                          + ("" if not fallas else f" · {len(fallas)} problema(s)"))
                    vistos = set()
                    for f in fallas:
                        clave = (f["tipo"], f.get("el", ""), f["detalle"])
                        if clave in vistos:
                            continue
                        vistos.add(clave)
                        print(f"        [{f['tipo']}] {f.get('el', '')} — {f['detalle']}")
                    total += len(fallas)

                    if args.capturas:
                        destino = os.path.join(CAPTURAS, f"{idioma}_{ancho}.png")
                        pag.screenshot(path=destino, full_page=True)
                    ctx.close()
            nav.close()
    finally:
        srv.shutdown()

    print()
    if total:
        print(f"{total} problema(s) de maquetación. La web NO está lista para publicar.")
        return 1
    print("Sin solapamientos ni desbordes en 3 idiomas x 3 anchos.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
