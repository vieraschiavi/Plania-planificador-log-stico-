"""
Plania · Genera la imagen social (og:image / twitter:image)
=============================================================
Sin esto, compartir el link de Plania en LinkedIn, WhatsApp o Twitter
mostraba la tarjeta sin imagen — la que menos invita a hacer clic de todas
las variantes posibles. Genera una imagen de 1200x630 por idioma (medida
estándar actual: 630 y no 627, que era una particularidad vieja de
Facebook ya abandonada) reusando el mismo texto del hero y los KPI que ya
están aprobados en `sitio/i18n/*.json` — no se inventa copy nuevo para la
imagen, se reusa el que ya se ve en la página.

    python3 sitio/generar_og.py

Deja `web/assets/og_{es,en,pt}.png`.
"""
from __future__ import annotations

import json
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITIO = os.path.join(RAIZ, "sitio")
SALIDA = os.path.join(RAIZ, "web", "assets")

ANCHO, ALTO = 1200, 630

PLANTILLA = """
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  @import url('data:text/css;charset=utf-8,');
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{width:{ancho}px;height:{alto}px;overflow:hidden;
       font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
       background:radial-gradient(circle at 78% 15%, #123258 0%, #081527 46%, #060f1e 100%);
       display:flex;flex-direction:column;justify-content:center;
       padding:74px 84px;position:relative}}
  .marca{{position:absolute;top:52px;left:84px;font-size:26px;font-weight:800;
         letter-spacing:.14em;color:#fff}}
  .marca span{{color:#2f74c0}}
  .badge{{display:inline-block;background:rgba(242,180,65,.14);color:#f2b441;
         border:1px solid rgba(242,180,65,.4);border-radius:999px;
         padding:7px 18px;font-size:16px;font-weight:700;margin-bottom:26px;
         width:fit-content}}
  h1{{font-size:56px;line-height:1.12;color:#eaf1fb;font-weight:800;
     max-width:920px;letter-spacing:-.01em}}
  h1 .grad{{color:#f2b441}}
  .kpis{{display:flex;gap:46px;margin-top:44px}}
  .kpi b{{display:block;font-size:34px;color:#fff;font-weight:800}}
  .kpi span{{display:block;font-size:16px;color:#9db0c8;margin-top:4px}}
  .franja{{position:absolute;bottom:0;left:0;right:0;height:8px;
          background:linear-gradient(90deg,#f2b441,#2f74c0,#00c896)}}
</style></head><body>
  <div class="marca">PLAN<span>IA</span></div>
  <p class="badge">{badge}</p>
  <h1>{h1a}<br><span class="grad">{h1b}</span></h1>
  <div class="kpis">
    <div class="kpi"><b>{k1n}</b><span>{k1t}</span></div>
    <div class="kpi"><b>{k2n}</b><span>{k2t}</span></div>
    <div class="kpi"><b>{k3n}</b><span>{k3t}</span></div>
  </div>
  <div class="franja"></div>
</body></html>
"""

BADGE = {
    "es": "Para distribuidoras, mayoristas y comercios",
    "en": "For distributors, wholesalers and retailers",
    "pt": "Para distribuidoras, atacadistas e comércios",
}


def _sin_html(texto: str) -> str:
    """El badge/h1 de i18n puede traer <b>; en una imagen no hay HTML real."""
    return re.sub(r"<[^>]+>", "", texto)


def generar() -> None:
    from playwright.sync_api import sync_playwright

    os.makedirs(SALIDA, exist_ok=True)
    with sync_playwright() as p:
        ejecutable = os.environ.get("PLANIA_CHROMIUM", "/opt/pw-browsers/chromium")
        nav = (p.chromium.launch(executable_path=ejecutable)
               if os.path.exists(ejecutable) else p.chromium.launch())
        for idioma in ("es", "en", "pt"):
            with open(os.path.join(SITIO, "i18n", f"{idioma}.json"), encoding="utf-8") as f:
                d = json.load(f)
            html = PLANTILLA.format(
                ancho=ANCHO, alto=ALTO, badge=BADGE[idioma],
                h1a=_sin_html(d["hero_h1_a"]), h1b=_sin_html(d["hero_h1_b"]),
                k1n=d["kpi1_n"], k1t=d["kpi1_t"], k2n=d["kpi2_n"], k2t=d["kpi2_t"],
                k3n=d["kpi3_n"], k3t=d["kpi3_t"])
            pagina = nav.new_page(viewport={"width": ANCHO, "height": ALTO})
            pagina.set_content(html)
            destino = os.path.join(SALIDA, f"og_{idioma}.png")
            pagina.screenshot(path=destino)
            pagina.close()
            print(f"[og] {os.path.relpath(destino, RAIZ)}")
        nav.close()


if __name__ == "__main__":
    generar()
