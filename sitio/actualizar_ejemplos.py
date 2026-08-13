# © 2026 Martín Viera. Todos los derechos reservados.
"""
Plania · Regenerar los ejemplos numéricos de la web
====================================================
Los cinco motores de la landing (`s1_d`…`s5_d` en `sitio/i18n/*.json`) no
prometen en abstracto: cada uno muestra un hallazgo REAL corrido sobre la base
de demostración. Este script vuelve a correr el motor y reescribe esas frases
con lo que devuelve hoy.

    python3 sitio/actualizar_ejemplos.py            # muestra qué cambiaría
    python3 sitio/actualizar_ejemplos.py --escribir # lo aplica

Por qué hace falta un generador y no alcanza con escribirlos a mano
--------------------------------------------------------------------
Porque se desactualizan solos. Los números salen de correr el motor sobre
`data/erp_demo.db`, que se regenera en cada máquina con la semilla 42 — pero
el resultado depende también de las versiones de pandas y numpy instaladas.
Un producto que está a 0,05 pp del corte `margen_obj - 3` entra o sale según
el redondeo, y el total se mueve.

Pasó: la web decía `$96.146/mes` y el motor devolvía `$96.373`. El test
`test_las_cinco_sugerencias_tienen_ejemplo_numerico_real` lo agarró, pero
como corta en el primer número que no coincide, tapó otros tres:
`$5.757` → `$5.765`, `$201.362` → `$207.288` y `$893.688` → `$885.661`.
Corregirlos a mano en tres idiomas es exactamente el trabajo que hace que la
próxima vez nadie lo haga.

Acá las frases se GENERAN: los textos fijos son plantillas y todo lo que es
número, nombre de producto o porcentaje sale del motor. No pueden discrepar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

CLAVES = ("s1_d", "s2_d", "s3_d", "s5_d")


# --------------------------------------------------------------------------
# Formato de número por idioma. Uruguay y Brasil usan punto de miles y coma
# decimal; inglés al revés. Escribir "1.430.318" en la versión inglesa no es
# un detalle estético: se lee como mil cuatrocientos treinta coma trescientos
# dieciocho.
# --------------------------------------------------------------------------
def _miles(n: float, idioma: str) -> str:
    entero = f"{round(n):,}"
    return entero if idioma == "en" else entero.replace(",", ".")


def _dec(n: float, idioma: str, cifras: int = 1) -> str:
    txt = f"{n:.{cifras}f}"
    return txt if idioma == "en" else txt.replace(".", ",")


def _plata(n: float, idioma: str) -> str:
    """Cómo se escribe un monto en cada idioma, tal como estaba en los textos."""
    return f"${_miles(n, idioma)} UYU" if idioma == "es" else f"UYU {_miles(n, idioma)}"


# --------------------------------------------------------------------------
# Las frases. Lo único fijo es la redacción; todo dato viene de `d`.
# --------------------------------------------------------------------------
PLANTILLAS = {
    "es": {
        "s1_d": ("Detecta el stock que dejó de rotar y calcula el descuento, con piso "
                 "de costo más 8%. Ejemplo real: “{producto}” lleva {stock} unidades y "
                 "{dias} días sin moverse — <b>{inmovilizado}</b> inmovilizados en ese "
                 "producto. En toda la base, libera <b>{total}</b>."),
        "s2_d": ("Cruza la rotación real con el plazo de cada proveedor. Ejemplo real: "
                 "a “{producto}” le quedan {dias} días de stock y el proveedor demora "
                 "{lead} — <b>{riesgo}/mes</b> de venta en riesgo si no se repone hoy. "
                 "En toda la base, hay <b>{total}</b> en riesgo."),
        "s3_d": ("Encuentra los productos que venden por debajo del margen de su "
                 "categoría. Ejemplo real: “{producto}” vende con {margen}% de margen "
                 "contra {objetivo}% de su categoría — subir el precio {suba}% suma "
                 "<b>{extra}/mes</b>. En toda la base, son <b>{total}/mes</b>."),
        "s5_d": ("Cruza la frecuencia habitual de cada cliente contra cuánto hace que "
                 "no pide. Ejemplo real: “{cliente}” compraba <b>{historico}</b> y lleva "
                 "{dias} días sin pedir. En toda la base, hay <b>{total}</b> en clientes "
                 "para recuperar."),
    },
    "en": {
        "s1_d": ("It spots the stock that stopped moving and works out the discount, "
                 "never below cost plus 8%. Real example: “{producto}” has {stock} units "
                 "sitting for {dias} days — <b>{inmovilizado}</b> tied up in that product "
                 "alone. Across the full dataset, it frees up <b>{total}</b>."),
        "s2_d": ("It cross-checks real turnover against each supplier's lead time. Real "
                 "example: “{producto}” has {dias} days of stock left and the supplier "
                 "takes {lead} — <b>{riesgo}/month</b> of revenue at risk if it is not "
                 "reordered today. Across the dataset, {total} is at risk."),
        "s3_d": ("It finds products selling below their category's margin. Real example: "
                 "“{producto}” sells at a {margen}% margin against a {objetivo}% category "
                 "average — raising the price {suba}% adds <b>{extra}/month</b>. Across "
                 "the dataset, that is <b>{total}/month</b>."),
        "s5_d": ("It compares each customer's usual buying rhythm against how long it has "
                 "been since their last order. Real example: “{cliente}” used to buy "
                 "<b>{historico}</b> and has gone {dias} days without ordering. Across the "
                 "dataset, {total} sits in customers worth calling back."),
    },
    "pt": {
        "s1_d": ("Identifica o estoque que parou de girar e calcula o desconto, com piso "
                 "de custo mais 8%. Exemplo real: “{producto}” tem {stock} unidades "
                 "paradas há {dias} dias — <b>{inmovilizado}</b> parados só nesse produto. "
                 "Em toda a base, libera <b>{total}</b>."),
        "s2_d": ("Cruza o giro real com o prazo de cada fornecedor. Exemplo real: "
                 "“{producto}” tem {dias} dias de estoque e o fornecedor demora {lead} — "
                 "<b>{riesgo}/mês</b> de venda em risco se não repuser hoje. Em toda a "
                 "base, são {total} em risco."),
        "s3_d": ("Encontra os produtos que vendem abaixo da margem da categoria. Exemplo "
                 "real: “{producto}” vende com {margen}% de margem contra {objetivo}% da "
                 "categoria — subir o preço {suba}% soma <b>{extra}/mês</b>. Em toda a "
                 "base, são <b>{total}/mês</b>."),
        "s5_d": ("Cruza a frequência habitual de cada cliente com há quanto tempo ele não "
                 "pede. Exemplo real: “{cliente}” comprava <b>{historico}</b> e está há "
                 "{dias} dias sem pedir. Em toda a base, há <b>{total}</b> em clientes "
                 "para recuperar."),
    },
}


def hallazgos() -> dict:
    """Corre el motor sobre la base de demostración y saca el caso de cada tabla."""
    from plania import conectores, sugerencias

    base = os.path.join(RAIZ, "data", "erp_demo.db")
    if not os.path.exists(base):
        raise SystemExit("Falta data/erp_demo.db. Corré antes: "
                         "python3 data/generate_dataset.py --seed 42")
    datos = conectores.cargar_datos(f"sqlite:///{base}")
    p = sugerencias.generar_todas(datos)
    r = p["resumen"]

    def primero(clave):
        df = p.get(clave)
        if df is None or not len(df):
            raise SystemExit(f"El motor no devolvió ninguna sugerencia de '{clave}' — "
                             "la landing no puede mostrar un ejemplo que no existe.")
        return df.iloc[0]

    o, rep, pre, rec = (primero("ofertas"), primero("reposicion"),
                        primero("precios"), primero("recupero"))
    return {
        "s1_d": {"producto": o["nombre"], "stock": int(o["stock"]),
                 "dias": round(o["dias_stock"]), "_inmovilizado": o["capital_inmovilizado"],
                 "_total": r["capital_liberable"]},
        "s2_d": {"producto": rep["nombre"], "dias": round(rep["dias_stock"]),
                 "lead": int(rep["lead_time_dias"]), "_riesgo": rep["venta_en_riesgo"],
                 "_total": r["venta_en_riesgo"]},
        "s3_d": {"producto": pre["nombre"], "_margen": pre["margen_pct"],
                 "_objetivo": pre["margen_obj"], "_suba": pre["suba_pct"],
                 "_extra": pre["margen_extra_mensual"], "_total": r["margen_extra_mensual"]},
        "s5_d": {"cliente": rec["nombre"], "dias": int(rec["dias_sin_comprar"]),
                 "_historico": rec["venta_historica"], "_total": r["venta_recuperable"]},
    }


def redactar(clave: str, idioma: str, h: dict) -> str:
    """La frase final: plantilla del idioma + valores formateados como ese idioma."""
    v = {k: val for k, val in h.items() if not k.startswith("_")}
    for bruto, formato in (("_inmovilizado", "inmovilizado"), ("_total", "total"),
                           ("_riesgo", "riesgo"), ("_extra", "extra"),
                           ("_historico", "historico")):
        if bruto in h:
            v[formato] = _plata(h[bruto], idioma)
    for bruto, formato, cifras in (("_margen", "margen", 0), ("_objetivo", "objetivo", 0),
                                   ("_suba", "suba", 1)):
        if bruto in h:
            v[formato] = _dec(h[bruto], idioma, cifras)
    if "stock" in v:
        v["stock"] = _miles(v["stock"], idioma)
    return PLANTILLAS[idioma][clave].format(**v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--escribir", action="store_true",
                    help="aplicar los cambios (sin esto solo los muestra)")
    args = ap.parse_args()

    h = hallazgos()
    cambios = 0
    for idioma in ("es", "en", "pt"):
        ruta = os.path.join(RAIZ, "sitio", "i18n", f"{idioma}.json")
        with open(ruta, encoding="utf-8") as f:
            textos = json.load(f)

        for clave in CLAVES:
            nuevo = redactar(clave, idioma, h[clave])
            if textos.get(clave) == nuevo:
                continue
            cambios += 1
            print(f"\n[{idioma}] {clave}")
            print(f"  antes: {textos.get(clave, '(no existía)')}")
            print(f"  ahora: {nuevo}")
            textos[clave] = nuevo

        if args.escribir:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(textos, f, ensure_ascii=False, indent=2)
                f.write("\n")

    print()
    if not cambios:
        print("Los ejemplos de la web coinciden con lo que devuelve el motor hoy.")
        return 0
    if args.escribir:
        print(f"{cambios} texto(s) actualizados. Volvé a generar la web: "
              f"python3 sitio/build.py")
        return 0
    print(f"{cambios} texto(s) quedaron desactualizados. Para aplicarlo: "
          f"python3 sitio/actualizar_ejemplos.py --escribir")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
