# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Generador de contenido para redes sociales
===================================================
Arma el material de marketing a partir de los **datos reales** del negocio
conectado: posts para LinkedIn, guiones de video, mensajes de prospección
en frío, secuencia de emails y un calendario de contenido de 4 semanas.
Todo exportable a PDF/Word/Excel con `plania.exportes`.

Por qué generar el contenido desde los datos y no escribirlo a mano: un post
que dice "optimizá tu stock" no vende nada. Uno que dice "encontramos
$1.430.000 inmovilizados en 78 productos que no rotan" hace que el dueño de
una distribuidora se pregunte cuánto tiene él. Los números son el gancho.

REGLA DE HONESTIDAD (está codificada, no es una recomendación)
--------------------------------------------------------------
Cuando el contenido se genera sobre la **base demo**, cada pieza sale
marcada como ejemplo y el kit incluye una advertencia. Publicar números de
la base demo como si fueran el resultado de un cliente real es fabricar un
testimonio: además de ser mentira, en Uruguay la Ley 17.250 de relaciones
de consumo prohíbe la publicidad engañosa. Con un ERP real conectado, los
números son del negocio y el aviso desaparece.
"""
from __future__ import annotations

import os

import pandas as pd

from plania import analitica, sugerencias

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AVISO_DEMO = ("CONTENIDO DE EJEMPLO — los números salen de la base demo de "
              "Plania, no de un cliente real. Antes de publicar: conectá tu ERP "
              "(o el de un cliente que te haya autorizado por escrito) para que "
              "las cifras sean verdaderas, o presentá las piezas explícitamente "
              "como demostración del producto.")


def _sobre_datos_demo() -> bool:
    """True si estamos trabajando contra la base demo incluida."""
    from plania import config as pconfig
    url = os.environ.get("ERP_DB_URL") or pconfig.leer_extra("ERP_DB_URL") or ""
    return (not url) or url.endswith("erp_demo.db")


def _cifras(datos: dict) -> dict:
    """Los números que dan de comer al contenido."""
    productos, clientes = datos["productos"], datos["clientes"]
    v = analitica.enriquecer_ventas(datos["ventas"], productos, clientes)
    paq = sugerencias.generar_todas(datos)
    k = analitica.kpis(productos, v)
    res = paq["resumen"]

    of, rep = paq["ofertas"], paq["reposicion"]
    zonas = analitica.por_dimension(v, "zona")
    tipos = analitica.por_dimension(v, "tipo_negocio")

    return {
        "capital_inmovilizado": res["capital_liberable"],
        "productos_sobrestock": len(of) if of is not None else 0,
        "venta_en_riesgo": res["venta_en_riesgo"],
        "productos_riesgo": len(rep) if rep is not None else 0,
        "margen_extra": res["margen_extra_mensual"],
        "venta_recuperable": res["venta_recuperable"],
        "clientes_inactivos": len(paq["recupero"]) if paq["recupero"] is not None else 0,
        "margen_actual": k["margen_pct"],
        "quiebres": k["quiebres"],
        "skus": len(productos),
        "zona_top": zonas.iloc[0]["zona"] if len(zonas) else "—",
        "zona_floja": zonas.iloc[-1]["zona"] if len(zonas) else "—",
        # Brecha de MARGEN entre zonas, en puntos porcentuales. Se usa el
        # margen y no la venta a propósito: que una zona venda más que otra
        # se explica por su tamaño y no dice nada. Que deje 6 puntos menos
        # de margen con la misma mercadería sí es un hallazgo accionable.
        "brecha_margen_zonas": (round(zonas["margen_pct"].max() - zonas["margen_pct"].min(), 1)
                                if len(zonas) > 1 else 0),
        "zona_mejor_margen": (zonas.sort_values("margen_pct").iloc[-1]["zona"]
                              if len(zonas) else "—"),
        "zona_peor_margen": (zonas.sort_values("margen_pct").iloc[0]["zona"]
                             if len(zonas) else "—"),
        "tipo_top": tipos.iloc[0]["tipo_negocio"] if len(tipos) else "—",
        "producto_top_oferta": of.iloc[0]["nombre"] if of is not None and len(of) else "—",
        "descuento_top": of.iloc[0]["descuento_pct"] if of is not None and len(of) else 0,
    }


def _m(n: float) -> str:
    """Formato de plata para redes: corto y legible."""
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:,.1f} millones"
    return f"${n:,.0f}"


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------
def posts_linkedin(datos: dict) -> pd.DataFrame:
    """LinkedIn es donde está el dueño y el gerente de una distribuidora.
    Formato: gancho con número, contexto, aprendizaje, cierre suave."""
    c = _cifras(datos)
    posts = [
        {
            "titulo": "El dinero que duerme en el depósito",
            "gancho": f"{_m(c['capital_inmovilizado'])} quietos en un depósito.",
            "texto": (
                f"{_m(c['capital_inmovilizado'])} quietos en un depósito.\n\n"
                f"No es plata perdida. Es plata dormida: {c['productos_sobrestock']} "
                "productos con más de 90 días de stock, comprados con la mejor "
                "intención y que hoy no rotan.\n\n"
                "El problema no es que el encargado compre mal. Es que nadie "
                "tiene tiempo de cruzar 300 SKUs contra su velocidad de venta "
                "todos los lunes a la mañana.\n\n"
                "Cuando ese cruce se hace solo, la conversación cambia: en vez "
                "de \"hay que liquidar algo\", aparece la lista exacta de qué "
                "ofertar, a qué precio, y cuánto se libera.\n\n"
                "¿Cuánto tenés vos durmiendo en el depósito? Es una pregunta "
                "que se responde con datos, no con intuición."),
            "cta": "Comentá \"stock\" y te muestro cómo calcularlo en tu negocio.",
        },
        {
            "titulo": "El quiebre que nadie vio venir",
            "gancho": f"Perder {_m(c['venta_en_riesgo'])} de venta por mes sin enterarte.",
            "texto": (
                f"Perder {_m(c['venta_en_riesgo'])} de venta por mes sin enterarte.\n\n"
                f"Así de caro sale un quiebre de stock. Hoy hay {c['productos_riesgo']} "
                "productos que se van a agotar antes de que llegue la reposición "
                "del proveedor.\n\n"
                "Lo traicionero: el que quiebra no es el producto que menos "
                "vende. Es el que más rota y tiene un proveedor lento. Justo el "
                "que te hace perder al cliente que venía por él.\n\n"
                "Cruzar rotación real contra el plazo de cada proveedor no es "
                "difícil. Es tedioso. Y por eso no se hace.\n\n"
                "La diferencia entre reponer el jueves y reponer el lunes "
                "siguiente se mide en clientes que no vuelven."),
            "cta": "Si vendés con stock propio, esto te está pasando ahora mismo.",
        },
        {
            "titulo": "Margen que se escapa por el precio",
            "gancho": f"{_m(c['margen_extra'])} por mes, sin vender una unidad más.",
            "texto": (
                f"{_m(c['margen_extra'])} por mes, sin vender una unidad más.\n\n"
                "Eso aparece cuando revisás qué productos están vendiendo por "
                f"debajo del margen de su categoría. El margen general parece "
                f"sano ({c['margen_actual']:.1f}%), pero adentro hay productos "
                "que arrastran.\n\n"
                "Pasa siempre por lo mismo: subió el costo, nadie actualizó el "
                "precio, y como el producto igual se vende, nadie lo notó.\n\n"
                "No hablo de aumentar todo. Hablo de encontrar los diez que "
                "están mal y corregirlos.\n\n"
                "El aumento promedio que hace falta suele ser menor al 5%. "
                "Nadie deja de comprarte por eso. Pero la diferencia al año "
                "paga varios sueldos."),
            "cta": "¿Cuándo revisaste por última vez tus precios producto por producto?",
        },
        {
            "titulo": "Los clientes que se fueron sin avisar",
            "gancho": f"{c['clientes_inactivos']} clientes dejaron de comprarte y no te enteraste.",
            "texto": (
                f"{c['clientes_inactivos']} clientes dejaron de comprarte y no te "
                "enteraste.\n\n"
                f"Entre todos valían {_m(c['venta_recuperable'])}.\n\n"
                "Un cliente B2B no se da de baja. Simplemente deja de llamar. "
                "Y como no hay un momento en que \"se va\", nadie lo registra.\n\n"
                "Conseguir un cliente nuevo cuesta varias veces más que "
                "recuperar uno que ya te compró, ya te conoce y ya sabe cómo "
                "trabajás.\n\n"
                "La lista de a quién llamar primero se arma sola: ordenás por "
                "cuánto valían y arrancás por arriba."),
            "cta": "Esta semana llamá a los cinco primeros. Contame cómo te fue.",
        },
        {
            "titulo": "No todas las zonas rinden igual",
            "gancho": (f"La misma camioneta, la misma mercadería, "
                       f"{c['brecha_margen_zonas']} puntos menos de margen."),
            "texto": (
                f"La misma camioneta, la misma mercadería, "
                f"{c['brecha_margen_zonas']} puntos de diferencia de margen "
                "entre una zona y otra.\n\n"
                f"Entre la zona que mejor rinde ({c['zona_mejor_margen']}) y la "
                f"que peor ({c['zona_peor_margen']}) hay una brecha que no se "
                "explica por el tamaño de la zona ni por el vendedor.\n\n"
                "Se explica por el mix: hay categorías que los negocios de un "
                "mismo rubro compran en una zona y no en otra. No porque no las "
                "quieran. Porque nadie se las ofreció.\n\n"
                "Esa lista —qué ofrecerle a quién en qué zona— es la diferencia "
                "entre un repartidor que entrega y un vendedor que vende.\n\n"
                "Y sale de datos que ya tenés en tu sistema."),
            "cta": "¿Sabés cuál es tu zona más floja y por qué?",
        },
        {
            "titulo": "Por qué no reemplazamos tu ERP",
            "gancho": "La peor idea para una PyME: cambiar el sistema de gestión.",
            "texto": (
                "La peor idea para una PyME: cambiar el sistema de gestión.\n\n"
                "Migrar un ERP es meses de trabajo, plata, y un equipo enojado "
                "que tiene que aprender todo de nuevo mientras factura.\n\n"
                "Por eso el enfoque que tomamos fue el opuesto: leer la base "
                "que ya tenés. Postgres, SQL Server, MySQL, o un Excel "
                "exportado. Las columnas se detectan solas, tengan el nombre "
                "que tengan.\n\n"
                "Tu ERP sigue haciendo lo que hace bien: facturar, controlar "
                "stock, cumplir con DGI.\n\n"
                "Lo que agregamos es la capa que ningún ERP trae: qué hacer "
                "con esos datos el lunes a la mañana."),
            "cta": "Si tu sistema guarda ventas y stock, ya alcanza.",
        },
    ]
    df = pd.DataFrame(posts)
    df.insert(0, "canal", "LinkedIn")
    df["caracteres"] = df["texto"].str.len()
    return df


def guiones_video(datos: dict) -> pd.DataFrame:
    """Reels e Instagram/TikTok: 30-45 segundos, gancho en los primeros 3."""
    c = _cifras(datos)
    guiones = [
        {
            "titulo": "El depósito que esconde plata",
            "duracion": "35 s",
            "gancho_3s": f"Tenés {_m(c['capital_inmovilizado'])} en el depósito y no lo sabés.",
            "guion": (
                "[0-3s] Plano del depósito. Texto en pantalla: "
                f"\"{_m(c['capital_inmovilizado'])} inmovilizados\".\n"
                "[3-12s] \"Esto no es stock. Es plata comprada que no se está "
                "moviendo. Y está repartida en productos que parecen normales.\"\n"
                "[12-25s] Pantalla del sistema mostrando la lista ordenada por "
                "capital inmovilizado. \"Acá está cada uno, con cuántos días de "
                "stock tiene y qué descuento necesita para volver a rotar.\"\n"
                "[25-35s] \"Sin regalar margen: el precio sugerido nunca baja "
                "del costo más 8%.\" Cierre con la marca."),
            "texto_en_pantalla": f"{_m(c['capital_inmovilizado'])} dormidos",
        },
        {
            "titulo": "Preguntale al sistema en criollo",
            "duracion": "30 s",
            "gancho_3s": "¿Y si le pudieras preguntar a tu sistema qué hacer?",
            "guion": (
                "[0-3s] Primer plano de alguien escribiendo: \"¿qué ofertas "
                "armo esta semana?\"\n"
                "[3-15s] La respuesta aparece con la tabla debajo. \"No es un "
                "chatbot que inventa. Calcula sobre tus datos y te muestra la "
                "tabla que usó.\"\n"
                "[15-27s] Clic en Exportar. \"Y sale en PDF para mandárselo al "
                "encargado de compras.\"\n"
                "[27-30s] Cierre: \"Tus datos. Tus decisiones. En minutos.\""),
            "texto_en_pantalla": "Preguntá. Te responde con TUS números.",
        },
        {
            "titulo": "Siete días para probarlo con tus datos",
            "duracion": "25 s",
            "gancho_3s": "Siete días con todo habilitado. Sin tarjeta.",
            "guion": (
                "[0-3s] \"Siete días. Todo habilitado. Sin tarjeta.\"\n"
                "[3-14s] \"Conectás tu base, y en la primera pantalla ya ves "
                "cuánta plata tenés inmovilizada y qué se te está por "
                "agotar.\"\n"
                "[14-22s] \"Si no encontrás nada que valga la pena, no pagás "
                "nada. Y tus datos nunca salieron de tu máquina.\"\n"
                "[22-25s] Cierre con la dirección de descarga."),
            "texto_en_pantalla": "7 días full. Sin tarjeta.",
        },
    ]
    df = pd.DataFrame(guiones)
    df.insert(0, "canal", "Instagram / TikTok")
    return df


def mensajes_prospeccion(datos: dict) -> pd.DataFrame:
    """WhatsApp y LinkedIn en frío. Cortos, sin vender en el primer mensaje."""
    c = _cifras(datos)
    return pd.DataFrame([
        {
            "canal": "WhatsApp",
            "momento": "Primer contacto",
            "mensaje": (
                "Hola [nombre], soy [tu nombre]. Trabajo con distribuidoras de "
                "[zona] conectando el sistema que ya usan para detectar stock "
                "que no rota y quiebres antes de que pasen.\n\n"
                "¿Te sirve que te muestre en 15 minutos, con tus propios datos, "
                "cuánta plata tenés inmovilizada hoy? Si no encontramos nada, "
                "te quedás con el análisis igual."),
        },
        {
            "canal": "WhatsApp",
            "momento": "Seguimiento (sin respuesta, 4 días)",
            "mensaje": (
                "[nombre], te dejo un dato concreto por si te sirve: en negocios "
                f"del tamaño del tuyo solemos encontrar entre {_m(c['capital_inmovilizado']*0.5)} "
                f"y {_m(c['capital_inmovilizado'])} en productos con más de 90 "
                "días de stock.\n\n"
                "Si querés lo miramos juntos un rato esta semana. Y si no es el "
                "momento, no te escribo más."),
        },
        {
            "canal": "LinkedIn",
            "momento": "Conexión + nota",
            "mensaje": (
                "Hola [nombre], veo que manejás [empresa]. Estoy trabajando con "
                "distribuidores en Uruguay sobre un problema puntual: el capital "
                "inmovilizado en productos que dejaron de rotar.\n\n"
                "No te voy a vender nada por acá. Si te interesa el tema, te "
                "paso el análisis que hacemos y lo mirás por tu cuenta."),
        },
        {
            "canal": "Email",
            "momento": "Post-demo (día 3 de la prueba)",
            "mensaje": (
                "Asunto: lo que encontró Plania en tus datos\n\n"
                "[nombre], van tres días de la prueba. Un resumen de lo que "
                "apareció:\n\n"
                "· Capital inmovilizado detectado: [monto]\n"
                "· Productos en riesgo de quiebre: [cantidad]\n"
                "· Margen recuperable ajustando precios: [monto]/mes\n\n"
                "Te quedan cuatro días de prueba completa. Si querés, nos "
                "juntamos 20 minutos y armamos el plan de las primeras ofertas "
                "con la lista que ya está generada.\n\n"
                "El informe completo lo podés bajar en PDF desde la pantalla "
                "de Ofertas y sugerencias."),
        },
        {
            "canal": "Email",
            "momento": "Fin de prueba (día 7)",
            "mensaje": (
                "Asunto: hoy vence tu prueba (tus datos quedan intactos)\n\n"
                "[nombre], hoy termina la semana de prueba.\n\n"
                "Tus datos, la conexión al ERP y la configuración quedan como "
                "están: si activás la licencia, seguís exactamente donde "
                "estabas, sin volver a configurar nada.\n\n"
                "Lo que encontramos en estos días: [monto] inmovilizados y "
                "[monto]/mes de margen recuperable. El plan Starter cuesta "
                "USD 59 al mes.\n\n"
                "Si preferís seguir con el ERP solo, sin problema — el análisis "
                "que bajaste es tuyo igual."),
        },
    ])


def calendario(datos: dict, semanas: int = 4) -> pd.DataFrame:
    """Calendario de publicación. Tres piezas por semana es sostenible para
    una persona sola; más que eso se abandona a la tercera semana."""
    posts = posts_linkedin(datos)
    videos = guiones_video(datos)
    plan = []
    dias = ["Martes", "Jueves", "Sábado"]
    canales = ["LinkedIn", "Instagram / TikTok", "LinkedIn"]
    formatos = ["Post con dato", "Reel 30 s", "Caso / aprendizaje"]
    for sem in range(1, semanas + 1):
        for i, (dia, canal, fmt) in enumerate(zip(dias, canales, formatos)):
            idx = (sem - 1) * 2 + i
            if canal == "LinkedIn":
                pieza = posts.iloc[idx % len(posts)]
                tema, cta = pieza["titulo"], pieza["cta"]
            else:
                pieza = videos.iloc[idx % len(videos)]
                tema, cta = pieza["titulo"], "Link a la prueba de 7 días en la bio"
            plan.append({
                "semana": sem,
                "dia": dia,
                "canal": canal,
                "formato": fmt,
                "tema": tema,
                "cta": cta,
                "objetivo": ("Alcance" if sem % 2 else "Conversión"),
            })
    return pd.DataFrame(plan)


def presupuesto_pauta(inversion_mes: float = 300.0) -> pd.DataFrame:
    """Cómo repartir la pauta. La mayoría del presupuesto va a retargeting
    porque el ciclo de venta B2B es largo: la primera impresión casi nunca
    cierra."""
    reparto = [
        ("Meta Ads · alcance frío (Montevideo + Canelones, dueños de comercio)",
         0.35, "Video de 30 s con el dato de capital inmovilizado"),
        ("Meta Ads · retargeting (visitaron la landing, no descargaron)",
         0.30, "Carrusel: qué hace, qué no hace, prueba de 7 días"),
        ("LinkedIn Ads · cargos de dueño, gerente de compras y logística",
         0.25, "Post patrocinado con el caso de margen recuperable"),
        ("Google Search · marcas de ERP locales + \"control de stock\"",
         0.10, "Anuncio de texto a la landing"),
    ]
    return pd.DataFrame([
        {"canal": c, "porcentaje": f"{p:.0%}", "usd_mes": round(inversion_mes * p, 2),
         "pieza": pieza}
        for c, p, pieza in reparto
    ])


def secciones_para_kit(datos: dict) -> list:
    """Kit completo de marketing, listo para exportar a PDF/Word/Excel."""
    c = _cifras(datos)
    demo = _sobre_datos_demo()
    intro = (
        f"Kit de contenido generado sobre los datos conectados: "
        f"{_m(c['capital_inmovilizado'])} de capital inmovilizado en "
        f"{c['productos_sobrestock']} productos, {_m(c['venta_en_riesgo'])} de "
        f"venta mensual en riesgo por quiebres y {_m(c['margen_extra'])} por mes "
        f"de margen recuperable. Estos son los números que se usan como gancho "
        f"en cada pieza.")
    if demo:
        intro = AVISO_DEMO + "\n\n" + intro

    return [
        ("Resumen del kit", intro, None),
        ("Posts para LinkedIn",
         "Seis posts listos para publicar. El gancho es siempre un número; "
         "el cierre nunca pide la venta directa.", posts_linkedin(datos)),
        ("Guiones de video",
         "Tres guiones de 25 a 35 segundos con el detalle segundo a segundo.",
         guiones_video(datos)),
        ("Mensajes de prospección",
         "WhatsApp, LinkedIn y los dos emails que más convierten: el del día 3 "
         "de la prueba y el del vencimiento.", mensajes_prospeccion(datos)),
        ("Calendario de publicación",
         "Cuatro semanas a tres piezas por semana: es el ritmo que una persona "
         "sola sostiene sin abandonar al mes.", calendario(datos)),
        ("Reparto de la pauta",
         "Distribución sugerida de USD 300 mensuales. El grueso va a "
         "retargeting: en B2B la primera impresión casi nunca cierra.",
         presupuesto_pauta()),
    ]
