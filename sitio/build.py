"""
Plania · Generador de la web trilingüe
======================================
Toma `sitio/plantilla.html` + `sitio/i18n/{es,en,pt}.json` y escribe la web
lista para Vercel en `web/`:

    web/index.html      redirección al idioma del navegador
    web/es/index.html   español
    web/en/index.html   inglés
    web/pt/index.html   portugués

Por qué generar HTML estático por idioma en vez de traducir con JavaScript
en el navegador (que es lo que hace la landing de Kobra):

  1. **Sin parpadeo**: con i18n por JS el visitante ve medio segundo el texto
     en el idioma equivocado antes de que corra el script. Acá el HTML ya
     llega traducido.
  2. **SEO real**: Google indexa tres páginas con su `hreflang` y su
     `<meta description>` propia. Con i18n por JS indexa una sola.
  3. **Funciona sin JavaScript**: el contenido se lee igual.

El costo es tener que correr este script cuando cambia un texto — barato
comparado con mantener tres HTML a mano y que se desincronicen.

Uso:
    python3 sitio/build.py
"""
from __future__ import annotations

import json
import os
import re
import shutil

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITIO = os.path.join(RAIZ, "sitio")
SALIDA = os.path.join(RAIZ, "web")

IDIOMAS = ["es", "en", "pt"]
IDIOMA_DEFECTO = "es"

# El nombre del producto es "Plania" (PLAN + IA) en los tres idiomas — el
# juego de palabras se conserva igual en inglés (PLAN + AI). Lo que cambia
# entre idiomas es solo cómo lo PRONUNCIA la voz sintética del video (ver
# sitio/doblar_video.py), no el nombre escrito ni el logo.
MARCAS = {
    "es": "PLAN<span>IA</span>",
    "en": "PLAN<span>IA</span>",
    "pt": "PLAN<span>IA</span>",
}

# Configuración del sitio. Vive en sitio/sitio.json para no tener que editar
# código al desplegar; lo de acá abajo son los valores por defecto.
#
# `backend` es el que decide si la web vende o solo informa: con el backend
# puesto, el formulario emite la licencia de 7 días y los botones de plan
# abren MercadoPago; vacío, el formulario muestra la dirección de contacto y
# los planes llevan a "Hablar con ventas". Se deja vacío a propósito: es
# preferible que la web diga la verdad a que simule un checkout que no existe.
DEFECTOS = {
    "dominio": "https://plania.uy",
    "backend": "",
    "releases": "https://github.com/vieraschiavi/Plania-planificador-log-stico-/releases",
    "app": "https://plania.uy/app",
}

# Textos que cambian según haya backend o no.
# ------------------------------------------
# Que el botón se comporte distinto sin backend no alcanza: si el botón sigue
# diciendo "Pagar con MercadoPago" y lo que hace es bajar hasta el formulario
# de contacto (que abre el cliente de correo), la página está prometiendo un
# cobro automático que no existe. Lo mismo con "la licencia llega al
# instante": sin backend no llega nada al instante, la mandamos a mano.
#
# Así que cuando `backend` está vacío se publican estos textos en lugar de los
# de i18n/. No es "suavizar el marketing": es que la página diga exactamente
# lo que el sitio hace hoy. En cuanto se configura `backend`, vuelven solos
# los textos de venta automática — sin tocar código ni acordarse de nada.
#
# La prueba de 7 días NO está acá a propósito: existe de verdad y funciona sin
# backend (plania/licencia.py la arranca sola en el primer arranque del
# programa). Lo único que el backend agrega es emitirla por email al instante.
SIN_BACKEND = {
    "es": {
        "precios_sub": "Sin permanencia mínima: si un mes no te sirve, lo das de baja. "
                       "El alta la coordinamos por mail.",
        "p_cta": "Hablar con ventas",
        "demo_cta": "Pedir la demo completa",
        "demo_nota": "Una demo por email. Te la enviamos a mano, en el día.",
        "foot_legal": "Los importes están expresados en dólares. "
                      "Plania no reemplaza tu ERP: lo lee.",
    },
    "en": {
        "precios_sub": "No lock-in: if a month is not worth it, you cancel. "
                       "We set the subscription up by email.",
        "p_cta": "Talk to sales",
        "demo_cta": "Request the full demo",
        "demo_nota": "One demo per email. We send it by hand, the same day.",
        "foot_legal": "Prices are stated in US dollars. "
                      "Plania does not replace your ERP: it reads it.",
    },
    "pt": {
        "precios_sub": "Sem fidelidade: se um mês não valer a pena, você cancela. "
                       "A assinatura é combinada por e-mail.",
        "p_cta": "Falar com vendas",
        "demo_cta": "Pedir a demo completa",
        "demo_nota": "Uma demo por e-mail. Enviamos manualmente, no mesmo dia.",
        "foot_legal": "Os valores estão em dólares. "
                      "A Plania não substitui o seu ERP: ela o lê.",
    },
}

# Palabras que solo pueden aparecer en la página si el cobro automático existe
# de verdad. Van aparte de SIN_BACKEND porque cubren el caso que el reemplazo
# de textos no cubre: que mañana alguien agregue "Pagá con MercadoPago" en una
# clave nueva de i18n/ y nadie se acuerde de este archivo. El build corta.
PROMESAS_DE_COBRO = ["MercadoPago", "Mercado Pago", "mercadopago.com"]

# Las tres páginas a las que MercadoPago devuelve al comprador después de
# pagar. Los nombres tienen que coincidir con `back_urls` de
# backend_venta/app.py; si cambian de un lado y no del otro, el comprador
# termina en un 404 justo después de pagar.
RETORNOS = ["gracias", "pendiente", "error"]


def config() -> dict:
    """Valores por defecto, pisados por sitio/sitio.json y por el entorno.

    El entorno gana para poder desplegar con `PLANIA_BACKEND=... build.py`
    sin dejar la URL escrita en el repo.
    """
    valores = dict(DEFECTOS)
    archivo = os.path.join(SITIO, "sitio.json")
    if os.path.exists(archivo):
        with open(archivo, encoding="utf-8") as f:
            valores.update({k: v for k, v in json.load(f).items() if k in DEFECTOS})
    for clave in DEFECTOS:
        env = os.environ.get(f"PLANIA_{clave.upper()}")
        if env:
            valores[clave] = env
    return valores


def cargar(idioma: str) -> dict:
    with open(os.path.join(SITIO, "i18n", f"{idioma}.json"), encoding="utf-8") as f:
        return json.load(f)


def textos_del_modo(textos: dict, idioma: str, cfg: dict) -> dict:
    """Los textos de i18n/, con los de SIN_BACKEND encima si no hay backend."""
    if cfg["backend"]:
        return textos
    copia = dict(textos)
    copia.update(SIN_BACKEND[idioma])
    return copia


def verificar_promesas(html: str, idioma: str, cfg: dict, pagina: str,
                       originales: dict) -> None:
    """Corta el build si la página promete algo que sin backend no pasa.

    Se ejecuta sobre el HTML ya renderizado —no sobre los JSON— porque lo que
    le llega al visitante es el HTML: si una promesa entra por la plantilla en
    vez de por i18n/, igual la agarra.
    """
    if cfg["backend"]:
        return
    encontradas = [p for p in PROMESAS_DE_COBRO if p in html]
    # Los textos que SIN_BACKEND tenía que haber reemplazado: si alguno
    # sobrevivió al render, el reemplazo no se aplicó donde correspondía.
    encontradas += [originales[k] for k in SIN_BACKEND[idioma]
                    if k in originales and originales[k] in html]
    if encontradas:
        raise RuntimeError(
            f"web/{idioma}/{pagina} promete cobro automático pero el sitio se "
            f"está generando sin backend, así que el botón termina en el "
            f"formulario de contacto. Sobró: {encontradas[0]!r}.\n"
            f"Arreglo: configurá 'backend' en sitio/sitio.json (o "
            f"PLANIA_BACKEND=...) y volvé a generar, o agregá el texto "
            f"alternativo en SIN_BACKEND['{idioma}'] de sitio/build.py.")


def hreflang(actual: str, dominio: str, ruta: str = "") -> str:
    """Etiquetas que le dicen al buscador que las páginas son la misma en
    distintos idiomas. Sin esto, Google las trata como contenido duplicado.

    `ruta` es el segmento después del idioma (p. ej. "implementadores/"): sin
    esto, el hreflang de /es/implementadores/ apuntaría a /en/ en vez de a
    /en/implementadores/, y Google indexaría cruzado dos páginas distintas.
    """
    lineas = [f'<link rel="alternate" hreflang="{l}" href="{dominio}/{l}/{ruta}">'
              for l in IDIOMAS]
    lineas.append(f'<link rel="alternate" hreflang="x-default" '
                  f'href="{dominio}/{IDIOMA_DEFECTO}/{ruta}">')
    return "\n".join(lineas)


def botones_idioma(actual: str, textos: dict, ruta: str = "") -> str:
    """Selector de idioma: son enlaces reales a /es/<ruta> /en/<ruta> /pt/<ruta>,
    no botones de JavaScript, para que se puedan abrir en otra pestaña y los
    indexe el buscador.

    Lleva `ruta` para que cambiar de idioma en la página de implementadores
    quede en la página de implementadores del otro idioma, no en el inicio.
    """
    partes = []
    for l in IDIOMAS:
        clase = ' class="on"' if l == actual else ""
        etiqueta = {"es": "ES", "en": "EN", "pt": "PT"}[l]
        nombre = cargar(l)["_meta"]["nombre"]
        partes.append(f'<a href="/{l}/{ruta}" hreflang="{l}" lang="{l}" '
                      f'title="{nombre}"{clase}>{etiqueta}</a>')
    return "".join(partes)


def render(plantilla: str, textos: dict, idioma: str, cfg: dict, ruta: str = "",
           extra: dict | None = None) -> str:
    valores = {k: v for k, v in textos.items() if not k.startswith("_")}
    valores["_releases"] = cfg["releases"]
    valores["_app"] = cfg["app"]
    valores["_dominio"] = cfg["dominio"]
    valores["_lang"] = idioma
    valores["_locale"] = textos["_meta"]["locale"]
    valores["_hreflang"] = hreflang(idioma, cfg["dominio"], ruta)
    valores["_langbtns"] = botones_idioma(idioma, textos, ruta)
    valores["_marca"] = MARCAS[idioma]
    # Sin backend no se define la variable: el JavaScript ya distingue ese
    # caso y muestra la vía de contacto en vez de un checkout que fallaría.
    valores["_backend"] = (f'\n<script>window.PLANIA_BACKEND="{cfg["backend"]}";</script>'
                           if cfg["backend"] else "")
    # Lo mismo sin la etiqueta, para las páginas que ya están dentro de un
    # <script> (las de retorno de MercadoPago).
    valores["_backend_js"] = (f'window.PLANIA_BACKEND="{cfg["backend"]}";'
                              if cfg["backend"] else "")
    valores.update(extra or {})

    def sustituir(m):
        clave = m.group(1)
        if clave not in valores:
            raise KeyError(f"falta la clave '{clave}' en i18n/{idioma}.json")
        return str(valores[clave])

    html = re.sub(r"\{\{(\w+)\}\}", sustituir, plantilla)
    sobrantes = re.findall(r"\{\{(\w+)\}\}", html)
    if sobrantes:
        raise RuntimeError(f"quedaron marcadores sin resolver: {sobrantes}")
    return html


REDIRECCION = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Plania</title>
<link rel="canonical" href="{dominio}/es/">
{hreflang}
<meta name="robots" content="noindex">
<script>
// Manda al visitante al idioma de su navegador. El <noscript> de abajo y el
// <meta refresh> cubren el caso de que el JavaScript esté bloqueado: nadie
// queda en una página en blanco.
(function(){{
  var idiomas = {idiomas};
  var pedido = (navigator.language || navigator.userLanguage || "es").slice(0,2).toLowerCase();
  var destino = idiomas.indexOf(pedido) >= 0 ? pedido : "{defecto}";
  window.location.replace("/" + destino + "/" + window.location.hash);
}})();
</script>
<meta http-equiv="refresh" content="1;url=/{defecto}/">
</head>
<body>
<p>Redirigiendo… · Redirecting… · Redirecionando…</p>
<p><a href="/es/">Español</a> · <a href="/en/">English</a> · <a href="/pt/">Português</a></p>
</body>
</html>
"""


def main() -> None:
    cfg = config()
    with open(os.path.join(SITIO, "plantilla.html"), encoding="utf-8") as f:
        plantilla = f.read()
    with open(os.path.join(SITIO, "plantilla_implementador.html"), encoding="utf-8") as f:
        plantilla_impl = f.read()

    for idioma in IDIOMAS:
        originales = cargar(idioma)
        textos = textos_del_modo(originales, idioma, cfg)
        destino = os.path.join(SALIDA, idioma)
        os.makedirs(destino, exist_ok=True)
        html = render(plantilla, textos, idioma, cfg)
        verificar_promesas(html, idioma, cfg, "index.html", originales)
        with open(os.path.join(destino, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[web] /{idioma}/index.html  ({len(html):,} bytes)")

        # Página de implementadores: mismo idioma, misma marca — no traducimos
        # la URL ("implementadores/") para que las tres versiones queden en
        # una sola ruta estable, más fácil de compartir y de indexar.
        destino_impl = os.path.join(destino, "implementadores")
        os.makedirs(destino_impl, exist_ok=True)
        html_impl = render(plantilla_impl, textos, idioma, cfg, ruta="implementadores/")
        verificar_promesas(html_impl, idioma, cfg, "implementadores/index.html", originales)
        with open(os.path.join(destino_impl, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_impl)
        print(f"[web] /{idioma}/implementadores/index.html  ({len(html_impl):,} bytes)")

    # Páginas de retorno de MercadoPago. Las nombra el propio checkout
    # (`back_urls` en backend_venta/app.py): sin ellas, quien paga de verdad
    # cae en un 404 del sitio estático — cobrado y con las manos vacías. Se
    # generan siempre, aunque hoy no haya backend, para que el día que se
    # despliegue no falte nada del lado de la web.
    with open(os.path.join(SITIO, "plantilla_retorno.html"), encoding="utf-8") as f:
        plantilla_retorno = f.read()
    # Estas no pasan por `verificar_promesas` a propósito: nombran MercadoPago
    # ("estamos confirmando el pago con MercadoPago"), pero no le prometen
    # nada a nadie — solo se llega a ellas después de haber pagado, y solo
    # existen si hay backend con qué cobrar.
    for estado in RETORNOS:
        destino_r = os.path.join(SALIDA, estado)
        os.makedirs(destino_r, exist_ok=True)
        html_r = render(plantilla_retorno, cargar(IDIOMA_DEFECTO), IDIOMA_DEFECTO, cfg,
                        extra={"_estado": estado})
        with open(os.path.join(destino_r, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_r)
        print(f"[web] /{estado}/index.html  (retorno de MercadoPago)")

    with open(os.path.join(SALIDA, "index.html"), "w", encoding="utf-8") as f:
        f.write(REDIRECCION.format(hreflang=hreflang(IDIOMA_DEFECTO, cfg["dominio"]),
                                   idiomas=json.dumps(IDIOMAS),
                                   defecto=IDIOMA_DEFECTO,
                                   dominio=cfg["dominio"]))
    print("[web] /index.html (redirección por idioma del navegador)")
    print(f"[web] dominio: {cfg['dominio']} · backend: "
          f"{cfg['backend'] or 'sin configurar'}")
    if not cfg["backend"]:
        print("[web] MODO SIN VENTA: los botones de plan dicen 'Hablar con ventas' y "
              "la demo se envía a mano.\n"
              "      No se menciona MercadoPago en ninguna página porque hoy el "
              "cobro automático no funciona:\n"
              "      el backend de venta no está desplegado. Ver docs/DESPLIEGUE.md §2.")

    # Ícono de marca reutilizado del programa de escritorio.
    icono = os.path.join(RAIZ, "assets", "brand", "plania_icon.png")
    if os.path.exists(icono):
        os.makedirs(os.path.join(SALIDA, "assets"), exist_ok=True)
        shutil.copy(icono, os.path.join(SALIDA, "assets", "plania_icon.png"))
        print("[web] /assets/plania_icon.png")


if __name__ == "__main__":
    main()
