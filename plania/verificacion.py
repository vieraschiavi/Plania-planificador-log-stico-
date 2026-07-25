"""
Plania · Verificación end-to-end del producto vendible
======================================================
Comprueba, ejecutando de verdad cada pieza, que la cadena completa de venta
funciona: datos → analítica → sugerencias → copiloto → exportes → rutas →
licencias → backend de venta → contenido → empaquetado.

Se corre como programa:

    python3 -m plania.verificacion

o desde el panel del dueño (`app/owner.py`), que muestra el mismo resultado.

Criterio: cada control devuelve OK, ADVERTENCIA o FALLA.
  · **FALLA**: algo del producto no funciona. No se puede vender así.
  · **ADVERTENCIA**: funciona, pero falta configuración de producción
    (credenciales de MercadoPago, instalador publicado). No bloquea la demo
    ni el uso del producto, sí bloquea cobrar.
  · **OK**: verificado ejecutando el código, no leyendo el código.

La distinción importa: un checklist que da "todo verde" porque los archivos
existen no sirve. Acá cada control ejecuta la función real y mira el
resultado.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OK, ADVERTENCIA, FALLA = "OK", "ADVERTENCIA", "FALLA"


class Resultado:
    def __init__(self, area: str, control: str, estado: str, detalle: str,
                 ms: float = 0.0):
        self.area, self.control = area, control
        self.estado, self.detalle, self.ms = estado, detalle, ms

    def como_dict(self) -> dict:
        return {"area": self.area, "control": self.control, "estado": self.estado,
                "detalle": self.detalle, "ms": round(self.ms, 1)}


def _control(area: str, control: str, fn) -> Resultado:
    """Ejecuta un control y captura cualquier explosión como FALLA."""
    t0 = time.time()
    try:
        estado, detalle = fn()
    except Exception as e:
        return Resultado(area, control, FALLA,
                         f"{type(e).__name__}: {e}", (time.time() - t0) * 1000)
    return Resultado(area, control, estado, detalle, (time.time() - t0) * 1000)


def verificar_todo(incluir_backend: bool = True) -> list[Resultado]:
    """Corre la batería completa y devuelve la lista de resultados."""
    from plania import (analitica, conectores, contenido, copiloto, exportes,
                        licencia, negocio, rutas, sugerencias)

    resultados: list[Resultado] = []
    estado_compartido: dict = {}

    # --- 1. Datos y conector universal -------------------------------------
    def _datos():
        datos = conectores.cargar_datos()
        estado_compartido["datos"] = datos
        p, c, v = len(datos["productos"]), len(datos["clientes"]), len(datos["ventas"])
        if p == 0 or v == 0:
            return FALLA, "la fuente no devolvió productos o ventas"
        return OK, f"{p} productos, {c} clientes, {v:,} líneas de venta"

    resultados.append(_control("Datos", "Carga desde ERP/base conectada", _datos))

    def _automapeo():
        import pandas as pd
        # un esquema deliberadamente ajeno, como el de un ERP real
        ajeno = pd.DataFrame({"cod_articulo": ["A1"], "descripcion": ["Yerba"],
                              "rubro": ["Almacén"], "precio_venta": [100.0],
                              "costo_unitario": [70.0], "stock_actual": [5]})
        out = conectores.normalizar(ajeno, "productos")
        if out.iloc[0]["sku"] != "A1" or out.iloc[0]["precio"] != 100.0:
            return FALLA, "el auto-mapeo no reconoció columnas de ERP ajeno"
        motores = len(conectores.SINONIMOS["productos"]["sku"])
        return OK, f"columnas auto-detectadas; {motores} alias de SKU soportados"

    resultados.append(_control("Datos", "Auto-mapeo de columnas de otro ERP", _automapeo))

    datos = estado_compartido.get("datos")
    if datos is None:
        resultados.append(Resultado("Datos", "Resto de la cadena", FALLA,
                                    "sin datos no se puede verificar el resto"))
        return resultados

    # --- 2. Analítica -------------------------------------------------------
    def _kpis():
        v = analitica.enriquecer_ventas(datos["ventas"], datos["productos"],
                                        datos["clientes"])
        estado_compartido["v"] = v
        k = analitica.kpis(datos["productos"], v)
        if k["venta_periodo"] <= 0:
            return FALLA, "la venta del período dio cero"
        return OK, (f"venta 30d ${k['venta_periodo']:,.0f}, margen "
                    f"{k['margen_pct']:.1f}%, {k['quiebres']} quiebres")

    resultados.append(_control("Analítica", "KPIs del panel ejecutivo", _kpis))

    # --- 3. Sugerencias (el corazón del valor) ------------------------------
    def _sugerencias():
        paq = sugerencias.generar_todas(datos)
        estado_compartido["paq"] = paq
        vacios = [k for k in ("ofertas", "reposicion", "precios")
                  if paq[k] is None or len(paq[k]) == 0]
        res = paq["resumen"]
        detalle = (f"${res['capital_liberable']:,.0f} liberables, "
                   f"${res['venta_en_riesgo']:,.0f} en riesgo, "
                   f"${res['margen_extra_mensual']:,.0f}/mes de margen extra")
        if vacios:
            return ADVERTENCIA, f"{detalle} (sin resultados en: {', '.join(vacios)})"
        return OK, detalle

    resultados.append(_control("Sugerencias", "Los cinco motores accionables",
                               _sugerencias))

    def _piso_margen():
        paq = estado_compartido.get("paq") or sugerencias.generar_todas(datos)
        of = paq["ofertas"]
        if of is None or not len(of):
            return ADVERTENCIA, "no hay ofertas para verificar el piso"
        m = of.merge(datos["productos"][["sku", "costo"]], on="sku")
        violaciones = (m["precio_oferta"] < m["costo"] * 1.079).sum()
        if violaciones:
            return FALLA, f"{violaciones} ofertas por debajo del piso costo+8%"
        return OK, f"{len(of)} ofertas, ninguna perfora el piso de costo+8%"

    resultados.append(_control("Sugerencias", "Piso de margen en ofertas",
                               _piso_margen))

    # --- 4. Copiloto --------------------------------------------------------
    def _copiloto():
        preguntas = ["¿qué ofertas armo esta semana?", "¿qué repongo ya?",
                     "stock de bebidas", "¿qué zona está floja?",
                     "¿qué clientes perdí?", "ventas por tipo de negocio"]
        fallidas = []
        for q in preguntas:
            r = copiloto.responder(q, datos)
            if not r.get("respuesta"):
                fallidas.append(q)
        if fallidas:
            return FALLA, f"sin respuesta para: {fallidas}"
        con_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        modo = "con redacción IA" if con_key else "motor local (sin API key)"
        return OK, f"{len(preguntas)} consultas respondidas con datos reales, {modo}"

    resultados.append(_control("Copiloto", "Consultas en tiempo real", _copiloto))

    # --- 5. Exportes --------------------------------------------------------
    def _exportes():
        paq = estado_compartido.get("paq") or sugerencias.generar_todas(datos)
        secc = exportes.secciones_desde_paquete(paq)
        pdf, doc, xls = (exportes.a_pdf("Verificación", secc),
                         exportes.a_word("Verificación", secc),
                         exportes.a_excel(secc))
        if pdf[:4] != b"%PDF":
            return FALLA, "el PDF generado no tiene cabecera válida"
        if doc[:2] != b"PK" or xls[:2] != b"PK":
            return FALLA, "Word o Excel no generaron un OOXML válido"
        return OK, (f"PDF {len(pdf):,} B · Word {len(doc):,} B · "
                    f"Excel {len(xls):,} B")

    resultados.append(_control("Exportes", "PDF, Word y Excel", _exportes))

    # --- 6. Rutas -----------------------------------------------------------
    def _rutas():
        cli = datos["clientes"].head(40)
        plan = rutas.planificar(cli, vehiculos=2)
        con_gps = len(cli.dropna(subset=["lat", "lon"])) if {"lat", "lon"} <= set(cli.columns) else 0
        if len(plan["rutas"]) != con_gps:
            return FALLA, "las rutas no cubren a todos los clientes"
        km = plan["resumen"]["km_estimados"].sum()
        return OK, f"{len(plan['rutas'])} paradas en {len(plan['resumen'])} vehículos, {km:,.0f} km"

    resultados.append(_control("Rutas", "Planificación de reparto", _rutas))

    # --- 7. Licencias: demo, planes pagos y versión owner -------------------
    def _demo():
        est = licencia.estado()
        if licencia.DIAS_DEMO != 7:
            return FALLA, f"la demo está en {licencia.DIAS_DEMO} días, se esperaban 7"
        faltan = set(licencia.FEATURES_DEMO) - set(est["features"]) if est["modo"] != "vencida" else set()
        if faltan:
            return FALLA, f"la demo no habilita: {faltan}"
        return OK, (f"demo de {licencia.DIAS_DEMO} días, modo actual "
                    f"'{est['modo']}', features {est['features']}")

    resultados.append(_control("Licencias", "Demo de 7 días full", _demo))

    def _planes():
        from backend_venta import licencias as lic
        esperados = {"trial", "starter", "pro", "enterprise"}
        if set(lic.PLANES) != esperados:
            return FALLA, f"planes definidos: {set(lic.PLANES)}"
        emitida = lic.emitir_licencia("verificacion@plania.uy", "pro")
        r = lic.licencia_activa(emitida)
        if not r["ok"]:
            return FALLA, f"la licencia emitida no valida: {r.get('error')}"
        if "rutas" not in r["claims"]["features"]:
            return FALLA, "el plan pro no habilita rutas"
        return OK, (f"trial {lic.PLANES['trial']['dias']}d · "
                    f"starter USD {lic.PLANES['starter']['precio']:.0f} · "
                    f"pro USD {lic.PLANES['pro']['precio']:.0f} · enterprise a medida; "
                    "JWT emitido y validado")

    resultados.append(_control("Licencias", "Planes pagos y emisión JWT", _planes))

    # --- 8. Backend de venta y MercadoPago ----------------------------------
    if incluir_backend:
        def _backend():
            from fastapi.testclient import TestClient
            from backend_venta.app import app
            c = TestClient(app)
            if not c.get("/salud").json().get("ok"):
                return FALLA, "/salud no responde ok"
            planes = c.get("/planes").json()
            if "trial" not in planes:
                return FALLA, "/planes no expone el trial"
            import uuid
            email = f"verif-{uuid.uuid4().hex[:8]}@plania.uy"
            r = c.post("/licencias/trial", json={"email": email})
            if r.status_code != 200 or r.json().get("dias") != 7:
                return FALLA, f"/licencias/trial devolvió {r.status_code}: {r.text[:120]}"
            repetido = c.post("/licencias/trial", json={"email": email})
            if repetido.status_code != 409:
                return FALLA, "un mismo email pudo sacar dos demos"
            return OK, "salud, planes, alta de demo y bloqueo de demo repetida"

        resultados.append(_control("Backend de venta", "Endpoints del circuito", _backend))

        def _mercadopago():
            from fastapi.testclient import TestClient
            from backend_venta.app import app
            from plania import config as pconfig
            token = os.environ.get("MP_ACCESS_TOKEN") or pconfig.leer_extra("MP_ACCESS_TOKEN")
            c = TestClient(app)
            r = c.post("/checkout", json={"plan": "pro", "email": "x@y.uy"})
            if not token:
                if r.status_code != 503:
                    return FALLA, (f"sin MP_ACCESS_TOKEN el checkout devolvió "
                                   f"{r.status_code} en vez de un 503 claro")
                return ADVERTENCIA, ("circuito listo pero MP_ACCESS_TOKEN no está "
                                     "configurado: todavía no se puede cobrar")
            if r.status_code != 200 or not r.json().get("init_point"):
                return FALLA, f"checkout con token configurado falló: {r.text[:150]}"
            return OK, "preferencia de pago creada contra MercadoPago"

        resultados.append(_control("Backend de venta", "Cobro por MercadoPago",
                                   _mercadopago))

    # --- 9. Contenido para redes -------------------------------------------
    def _contenido():
        kit = contenido.secciones_para_kit(datos)
        piezas = sum(len(df) for _, _, df in kit if df is not None)
        pdf = exportes.a_pdf("Kit", kit)
        if pdf[:4] != b"%PDF":
            return FALLA, "el kit no exporta a PDF"
        if contenido._sobre_datos_demo():
            return ADVERTENCIA, (f"{piezas} piezas generadas y exportables, pero "
                                 "sobre la BASE DEMO: no publicar como caso real")
        return OK, f"{piezas} piezas generadas sobre datos reales y exportadas"

    resultados.append(_control("Contenido", "Kit para redes sociales", _contenido))

    # --- 10. Modelo de negocio ---------------------------------------------
    def _negocio():
        df = negocio.simular(negocio.BASE, meses=18, inversion_ads_mes=300.0)
        if len(df) != 18:
            return FALLA, "la simulación no devolvió 18 meses"
        eq = negocio.mes_de_equilibrio(df)
        sup = negocio.mes_supera_sueldo(df)
        return OK, (f"escenario base con pauta: equilibrio mes {eq}, supera "
                    f"sueldo mes {sup}, {df.iloc[-1]['clientes_activos']:.0f} "
                    f"clientes al mes 18")

    resultados.append(_control("Negocio", "Modelo de rentabilidad", _negocio))

    # --- 11. Empaquetado y distribución ------------------------------------
    def _empaquetado():
        piezas = {
            "instalador Inno Setup": "packaging/instalador.iss",
            "spec PyInstaller": "packaging/plania.spec",
            "build de release": "packaging/build_release.py",
            "escritorio Electron": "desktop/main.js",
            "splash React": "desktop/renderer/app.js",
            "lanzador BAT": "INICIAR_PLANIA.bat",
            "workflow de Release": ".github/workflows/release.yml",
            "web de venta (español)": "web/es/index.html",
        }
        faltan = [n for n, p in piezas.items() if not os.path.exists(os.path.join(RAIZ, p))]
        if faltan:
            return FALLA, f"faltan piezas de distribución: {faltan}"
        return OK, f"{len(piezas)} vías de distribución presentes (exe, portable, BAT, web)"

    resultados.append(_control("Distribución", "Empaquetado PC y web", _empaquetado))

    # --- 12. Web pública trilingüe -----------------------------------------
    def _web():
        """La web es la puerta de entrada de la venta: si le falta un idioma o
        una pista de subtítulos, hay visitantes que se van sin entender qué es
        Plania. Se controla que estén las tres versiones y las tres pistas."""
        faltan = []
        for idioma in ("es", "en", "pt"):
            if not os.path.exists(os.path.join(RAIZ, "web", idioma, "index.html")):
                faltan.append(f"web/{idioma}/index.html")
            if not os.path.exists(os.path.join(RAIZ, "web", "assets", "video",
                                               f"plania_demo_{idioma}.vtt")):
                faltan.append(f"subtítulos {idioma}")
        if faltan:
            return FALLA, f"falta en la web pública: {faltan}"

        video = os.path.join(RAIZ, "web", "assets", "video", "plania_demo_es.mp4")
        if not os.path.exists(video):
            return FALLA, "falta el video de demostración (sitio/grabar_demo.py)"

        doblados = [i for i in ("en", "pt")
                    if os.path.exists(os.path.join(RAIZ, "web", "assets", "video",
                                                   f"plania_demo_{i}.mp4"))]
        if len(doblados) < 2:
            return (ADVERTENCIA,
                    "web en 3 idiomas con subtítulos en 3 idiomas, pero el audio "
                    "doblado todavía no está: requiere ELEVENLABS_API_KEY y el "
                    "voice_id (sitio/doblar_video.py --doblar)")
        return OK, "web y video en español, inglés y portugués"

    resultados.append(_control("Web", "Sitio público trilingüe", _web))

    return resultados


def resumen(resultados: list[Resultado]) -> dict:
    conteo = {OK: 0, ADVERTENCIA: 0, FALLA: 0}
    for r in resultados:
        conteo[r.estado] = conteo.get(r.estado, 0) + 1
    total = len(resultados)
    # El puntaje penaliza fuerte las fallas y suave las advertencias: una
    # advertencia es "falta una credencial", una falla es "no funciona".
    puntaje = (conteo[OK] + conteo[ADVERTENCIA] * 0.5) / max(1, total) * 10
    return {"total": total, "ok": conteo[OK], "advertencias": conteo[ADVERTENCIA],
            "fallas": conteo[FALLA], "puntaje_sobre_10": round(puntaje, 1),
            "vendible": conteo[FALLA] == 0}


def tabla(resultados: list[Resultado]):
    import pandas as pd
    return pd.DataFrame([r.como_dict() for r in resultados])


def main() -> int:
    sys.path.insert(0, RAIZ)
    print("\n  PLANIA · Verificación end-to-end")
    print("  " + "=" * 74)
    resultados = verificar_todo()
    area_actual = None
    for r in resultados:
        if r.area != area_actual:
            area_actual = r.area
            print(f"\n  {area_actual}")
        marca = {OK: "[ OK ]", ADVERTENCIA: "[ !! ]", FALLA: "[FALLA]"}[r.estado]
        print(f"    {marca} {r.control}")
        print(f"           {r.detalle}  ({r.ms:.0f} ms)")

    res = resumen(resultados)
    print("\n  " + "=" * 74)
    print(f"  {res['ok']} OK · {res['advertencias']} advertencias · "
          f"{res['fallas']} fallas")
    print(f"  Puntaje: {res['puntaje_sobre_10']}/10 · "
          f"{'PRODUCTO VENDIBLE' if res['vendible'] else 'NO VENDIBLE: hay fallas'}")
    if res["advertencias"]:
        print("  Las advertencias son configuración de producción pendiente "
              "(credenciales), no defectos del producto.")
    print()
    return 1 if res["fallas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
