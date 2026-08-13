// © 2026 Martín Viera. Todos los derechos reservados.
/*
 * Plania Owner · Pantallas del panel del dueño
 * ============================================
 * Las seis secciones que hoy dibuja app/owner.py en Streamlit, contra los
 * endpoints /owner/* de la API local (plania/api_owner.py).
 *
 * Por qué este archivo NO vive en desktop/renderer/
 * ------------------------------------------------
 * `desktop/package.json` empaqueta `"renderer/**"` sin exclusiones, y ese
 * camino —electron-builder— nunca consulta `fuera_del_producto()`. Un archivo
 * del dueño ahí adentro viajaría en texto plano dentro del instalador de cada
 * cliente, con la facturación, los márgenes y el modelo financiero a la
 * vista. Es la misma razón por la que el panel es un programa aparte del lado
 * de Python (packaging/plania_owner.spec) y no un flag de build: lo que no
 * está en el árbol no se puede filtrar por error.
 *
 * De base.js —que el armador copia acá— salen `e`, `pedir`, `API`, `miles`,
 * `plata`, `porcentaje`, `Tarjeta`, `Tabla`, `Grafico`, `Pestanas`,
 * `Exportar`, `Cargando`, `Error_` y `useDatos`. Acá no se calcula un solo
 * número: todo viene resuelto de la API, por la misma razón que en el
 * producto.
 */

/* Exportes del panel: mismo componente que el producto, otra ruta base. */
function ExportarOwner({ clave, etiqueta }) {
  return e(Exportar, { clave, etiqueta, base: "/owner/exportar" });
}

/* --------------------------------------------------------------------------
 * 1. Estado del negocio
 * ------------------------------------------------------------------------ */
function PantallaEstadoDelNegocio() {
  const { cargando, datos, error, reintentar } =
    useDatos(() => pedir("/owner/negocio"), []);
  if (cargando) return e(Cargando, { que: "el estado del negocio" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const k = datos.kpis;
  const integridad = datos.integridad;
  const sinOperacion = !k.demos_entregadas && !k.clientes_pagos;

  return e("div", null,
    e("h1", null, "Estado del negocio"),
    e("p", { className: "bajada" },
      "Sale de la operación registrada —la base de uso y el log de auditoría—, ",
      "no de una planilla aparte."),

    e("div", { className: "grilla-tarjetas cinco" },
      e(Tarjeta, { titulo: "Demos entregadas", valor: miles(k.demos_entregadas) }),
      e(Tarjeta, { titulo: "Clientes pagos", valor: miles(k.clientes_pagos) }),
      e(Tarjeta, { titulo: "Conversión", valor: porcentaje(k.conversion_pct) }),
      e(Tarjeta, { titulo: "MRR", valor: plata(k.mrr_usd), acento: "#20BF6B" }),
      e(Tarjeta, { titulo: "ARR", valor: plata(k.arr_usd) })),

    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "Costo de IA (mes)", valor: plata(k.costo_ia_mes_usd) }),
      e(Tarjeta, { titulo: "Comisión MercadoPago (mes)",
                   valor: plata(k.comision_mp_mes_usd) }),
      e(Tarjeta, { titulo: "Margen bruto", valor: porcentaje(k.margen_bruto_pct) }),
      e(Tarjeta, { titulo: "Clientes en riesgo",
                   valor: miles(k.clientes_en_riesgo),
                   detalle: "sin actividad hace más de 14 días",
                   acento: k.clientes_en_riesgo > 0 ? "#E74C3C" : null })),

    sinOperacion
      ? e("div", { className: "aviso-demo" },
          e("b", null, "Todavía no hay operación registrada"),
          " — los números aparecen solos cuando se entregue la primera demo o " +
          "se emita la primera licencia.")
      : null,

    // El historial de licencias sale de un log encadenado por hash. Si alguien
    // editó una línea a mano, los números de arriba están mintiendo y el panel
    // tiene que decirlo antes de que se tomen decisiones sobre ellos.
    integridad.ok
      ? e("div", { className: "todo-ok" },
          `Registro íntegro: ${miles(integridad.entradas)} entradas verificadas.`)
      : e("div", { className: "aviso-vencida" },
          e("b", null, "El registro fue alterado"),
          integridad.error
            ? ` — ${integridad.error}`
            : ` — la cadena se corta en la entrada ${miles(integridad.primer_error)}. ` +
              "Las cifras de arriba salen de ese registro, así que no son confiables."),

    e("h2", null, "Informe del negocio"),
    e(ExportarOwner, { clave: "negocio" }));
}

/* --------------------------------------------------------------------------
 * 2. Clientes y licencias
 * ------------------------------------------------------------------------ */
function EmitirLicencia({ planes, alEmitir }) {
  const [cliente, setCliente] = React.useState("");
  const [plan, setPlan] = React.useState(planes[0] || "pro");
  const [estado, setEstado] = React.useState(null);
  const [token, setToken] = React.useState(null);

  async function emitir() {
    setEstado({ ok: true, txt: "Emitiendo…" });
    setToken(null);
    try {
      const r = await pedir("/owner/licencias/emitir", { cliente, plan });
      setToken(r.token);
      setEstado({ ok: true, txt: `Licencia ${r.plan} emitida para ${r.cliente}.` });
      if (alEmitir) alEmitir();
    } catch (err) {
      setEstado({ ok: false, txt: String(err.message) });
    }
  }

  return e("div", null,
    e("p", { className: "pista" },
      "Para una venta directa o un canje. Queda asentada en el log de auditoría, ",
      "así que suma al historial y al MRR de arriba."),
    e("div", { className: "form-linea" },
      e("label", null, "Email o identificador del cliente",
        e("input", {
          type: "text", value: cliente, placeholder: "cliente@empresa.uy",
          onChange: (ev) => setCliente(ev.target.value),
        })),
      e("label", null, "Plan",
        e("select", { value: plan, onChange: (ev) => setPlan(ev.target.value) },
          planes.map((p) => e("option", { key: p, value: p }, p))))),
    e("button", { className: "btn", onClick: emitir }, "Emitir licencia"),
    estado
      ? e("p", { className: estado.ok ? "todo-ok" : "error-detalle" }, estado.txt)
      : null,
    token
      ? e("div", null,
          e("p", { className: "pista" }, "Copiásela al cliente para que la active:"),
          e("pre", { className: "consulta" }, token))
      : null);
}

function PantallaClientesYLicencias() {
  const { cargando, datos, error, reintentar } =
    useDatos(() => pedir("/owner/licencias"), []);
  if (cargando) return e(Cargando, { que: "los clientes y licencias" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const enRiesgo = datos.clientes_en_riesgo || [];

  return e("div", null,
    e("h1", null, "Clientes y licencias"),
    e(Pestanas, { items: [
      { titulo: "Licencias emitidas", cantidad: datos.emitidas.total,
        contenido: e(Tabla, { datos: datos.emitidas,
                              vacio: "Sin licencias emitidas todavía." }) },
      { titulo: "Uso por cliente", cantidad: datos.uso.total,
        contenido: e("div", null,
          enRiesgo.length
            ? e("div", { className: "aviso-demo" },
                e("b", null, `${miles(enRiesgo.length)} sin actividad hace más de 14 días`),
                ` — ${enRiesgo.join(", ")}. El que no lo usa, se va.`)
            : null,
          e(Tabla, { datos: datos.uso,
                     vacio: "Sin consumo registrado todavía." })) },
      { titulo: "Emitir licencia manual",
        contenido: e(EmitirLicencia, { planes: datos.planes, alEmitir: reintentar }) },
    ] }));
}

/* --------------------------------------------------------------------------
 * 3. Proyección de rentabilidad
 * ------------------------------------------------------------------------ */
function PantallaRentabilidad() {
  const [escenario, setEscenario] = React.useState("Base");
  const [ads, setAds] = React.useState(300);
  const [meses, setMeses] = React.useState(18);

  const { cargando, datos, error, reintentar } = useDatos(
    () => pedir(`/owner/rentabilidad?escenario=${encodeURIComponent(escenario)}`
                + `&ads=${ads}&meses=${meses}`),
    [escenario, ads, meses]);

  const controles = e("div", { className: "form-linea" },
    e("label", null, "Escenario",
      e("select", { value: escenario, onChange: (ev) => setEscenario(ev.target.value) },
        ["Conservador", "Base", "Optimista"].map(
          (x) => e("option", { key: x, value: x }, x)))),
    e("label", null, `Inversión en redes: ${plata(ads)}/mes`,
      e("input", { type: "range", min: 0, max: 1500, step: 50, value: ads,
                   onChange: (ev) => setAds(Number(ev.target.value)) })),
    e("label", null, `Meses a simular: ${miles(meses)}`,
      e("input", { type: "range", min: 6, max: 36, step: 6, value: meses,
                   onChange: (ev) => setMeses(Number(ev.target.value)) })));

  if (cargando) {
    return e("div", null, e("h1", null, "Proyección de rentabilidad"), controles,
      e(Cargando, { que: "la proyección" }));
  }
  if (error) {
    return e("div", null, e("h1", null, "Proyección de rentabilidad"), controles,
      e(Error_, { mensaje: error, reintentar }));
  }

  const h = datos.hitos;
  const u = datos.unit_economics;
  const nunca = "no alcanzado";

  return e("div", null,
    e("h1", null, "Proyección de rentabilidad"),
    controles,

    e("div", { className: "grilla-tarjetas cinco" },
      e(Tarjeta, { titulo: "Mes de equilibrio",
                   valor: h.mes_equilibrio === null ? nunca : miles(h.mes_equilibrio),
                   acento: h.mes_equilibrio === null ? "#E74C3C" : "#20BF6B" }),
      e(Tarjeta, { titulo: "Supera un sueldo",
                   valor: h.mes_supera_sueldo === null ? nunca : miles(h.mes_supera_sueldo),
                   detalle: `referencia ${plata(h.sueldo_referencia)}/mes` }),
      e(Tarjeta, { titulo: "Caja mínima", valor: plata(h.caja_minima),
                   acento: h.caja_minima < 0 ? "#E74C3C" : null }),
      e(Tarjeta, { titulo: "LTV / CAC", valor: miles(u.ltv_sobre_cac, 1),
                   detalle: "sano por encima de 3" }),
      e(Tarjeta, { titulo: "Payback", valor: `${miles(u.payback_meses, 1)} meses` })),

    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "ARPU mensual", valor: plata(u.arpu_mensual) }),
      e(Tarjeta, { titulo: "CAC", valor: plata(u.cac) }),
      e(Tarjeta, { titulo: "LTV", valor: plata(u.ltv) }),
      e(Tarjeta, { titulo: "Vida promedio",
                   valor: `${miles(u.vida_promedio_meses, 1)} meses` })),

    h.caja_minima < 0
      ? e("div", { className: "aviso-vencida" },
          e("b", null, "La caja se va abajo de cero"),
          ` — toca ${plata(h.caja_minima)} en el peor mes. Con este escenario ` +
          "hace falta capital de trabajo o menos gasto en redes.")
      : null,

    e("h2", null, "Ingresos por mes"),
    e(Grafico, { tipo: "columna", datos: datos.detalle, x: "mes",
                 y: ["ingreso_suscripcion", "ingreso_implementacion"] }),

    e("h2", null, "Resultado y caja"),
    e(Grafico, { tipo: "linea", datos: datos.detalle, x: "mes",
                 y: ["resultado_neto", "caja_acumulada"], cero: true }),

    e("h2", null, "Por horizonte"),
    e(Tabla, { datos: datos.horizontes }),

    e("h2", null, "Detalle mensual"),
    e(Tabla, { datos: datos.detalle }),

    e(ExportarOwner, { clave: "rentabilidad" }));
}

/* --------------------------------------------------------------------------
 * 4. Mercado y competencia
 * ------------------------------------------------------------------------ */
function PantallaMercado() {
  const { cargando, datos, error, reintentar } =
    useDatos(() => pedir("/owner/mercado"), []);
  if (cargando) return e(Cargando, { que: "el mercado" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  return e("div", null,
    e("h1", null, "Mercado y competencia"),
    e("p", { className: "bajada" },
      "TAM es el mercado entero, SAM el que este producto puede atender, ",
      "y SOM lo que es realista tomar en 18 meses."),

    e(Tabla, { datos: datos.potencial }),

    e("h2", null, "Mercado alcanzable por región"),
    e(Grafico, { tipo: "columna", datos: datos.potencial, x: "mercado",
                 y: ["SAM_usd_anual", "SOM_18m_usd_anual"] }),

    e("h2", null, "Supuestos por mercado"),
    Object.entries(datos.mercados).map(([nombre, m]) =>
      e("details", { key: nombre, className: "resultado-erp" },
        e("summary", null, nombre),
        e("p", null, m.notas),
        e("p", { className: "pista" },
          `${miles(m.empresas_totales)} empresas · TAM ${miles(m.tam_empresas)} · `
          + `SAM ${miles(m.sam_empresas)} · SOM 18m ${miles(m.som_18m_empresas)} · `
          + `ticket ${plata(m.ticket_anual_usd)}/año`))),

    e("h2", null, "Qué mueve la aguja"),
    e("p", { className: "pista" },
      "Sobre el escenario Base. Casi siempre gana bajar el churn o subir la ",
      "conversión antes que subir el precio."),
    e("div", { className: "dos-columnas" },
      datos.sensibilidades.map((s) =>
        e("div", { key: s.variable },
          e("h2", null, etiqueta(s.variable)),
          e(Tabla, { datos: s.tabla })))));
}

/* --------------------------------------------------------------------------
 * 5. Contenido para redes
 * ------------------------------------------------------------------------ */
function PantallaContenido() {
  const [pauta, setPauta] = React.useState(300);
  const { cargando, datos, error, reintentar } =
    useDatos(() => pedir(`/owner/contenido?pauta=${pauta}`), [pauta]);

  if (cargando) return e(Cargando, { que: "el kit de contenido" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  return e("div", null,
    e("h1", null, "Contenido para redes"),

    // Publicar como reales cifras que salen de la base de ejemplo es
    // publicidad engañosa (Ley 17.250). El aviso no es cosmético.
    datos.sobre_datos_demo
      ? e("div", { className: "aviso-demo" }, datos.aviso_demo)
      : e("div", { className: "todo-ok" },
          "Contenido generado sobre datos reales del ERP conectado."),

    e(Pestanas, { items: [
      { titulo: "LinkedIn", cantidad: datos.linkedin.total,
        contenido: e(Tabla, { datos: datos.linkedin }) },
      { titulo: "Video", cantidad: datos.video.total,
        contenido: e(Tabla, { datos: datos.video }) },
      { titulo: "Prospección", cantidad: datos.prospeccion.total,
        contenido: e(Tabla, { datos: datos.prospeccion }) },
      { titulo: "Calendario", cantidad: datos.calendario.total,
        contenido: e(Tabla, { datos: datos.calendario }) },
      { titulo: "Pauta",
        contenido: e("div", null,
          e("div", { className: "form-linea" },
            e("label", null, `Inversión mensual: ${plata(pauta)}`,
              e("input", { type: "range", min: 0, max: 1500, step: 50, value: pauta,
                           onChange: (ev) => setPauta(Number(ev.target.value)) }))),
          e(Tabla, { datos: datos.pauta })) },
    ] }),

    e(ExportarOwner, { clave: "contenido" }));
}

/* --------------------------------------------------------------------------
 * 6. Verificación del producto
 * ------------------------------------------------------------------------ */
const COLOR_ESTADO = { OK: "#20BF6B", ADVERTENCIA: "#F39C12", FALLA: "#E74C3C" };

function PantallaVerificacion() {
  const [estado, setEstado] = React.useState("inicial");
  const [datos, setDatos] = React.useState(null);
  const [error, setError] = React.useState(null);

  async function correr() {
    setEstado("corriendo");
    setError(null);
    try {
      setDatos(await pedir("/owner/verificacion", {}));
      setEstado("listo");
    } catch (err) {
      setError(String(err.message));
      setEstado("inicial");
    }
  }

  const r = datos ? datos.resumen : null;

  return e("div", null,
    e("h1", null, "Verificación del producto"),
    e("p", { className: "bajada" },
      "Corre la cadena completa de punta a punta. No es una consulta: emite ",
      "licencias de prueba, escribe configuración y levanta la aplicación en ",
      "memoria. Se ejecuta cuando lo pedís, no al abrir la pantalla."),

    e("button", {
      className: "btn", onClick: correr, disabled: estado === "corriendo",
    }, estado === "corriendo" ? "Ejecutando…" : "Ejecutar verificación end-to-end"),

    error ? e("p", { className: "error-detalle" }, error) : null,

    r
      ? e("div", null,
          e("div", { className: "grilla-tarjetas" },
            e(Tarjeta, { titulo: "Controles", valor: miles(r.total) }),
            e(Tarjeta, { titulo: "En orden", valor: miles(r.ok), acento: "#20BF6B" }),
            e(Tarjeta, { titulo: "Advertencias", valor: miles(r.advertencias),
                         acento: r.advertencias > 0 ? "#F39C12" : null }),
            e(Tarjeta, { titulo: "Fallas", valor: miles(r.fallas),
                         acento: r.fallas > 0 ? "#E74C3C" : null })),
          r.vendible
            ? e("div", { className: "todo-ok" },
                `Producto vendible — ${miles(r.puntaje_sobre_10, 1)} sobre 10.`)
            : e("div", { className: "aviso-vencida" },
                e("b", null, "Todavía no está para vender"),
                ` — ${miles(r.puntaje_sobre_10, 1)} sobre 10, con ${miles(r.fallas)} fallas.`),
          e(TablaVerificacion, { datos: datos.tabla }),
          e(ExportarOwner, { clave: "verificacion" }))
      : estado === "inicial" && !error
        ? e("p", { className: "vacio" }, "Todavía no se ejecutó ninguna verificación.")
        : null);
}

/* Igual que `Tabla`, pero pinta la fila según el estado del control. En
 * Streamlit esto era un Styler de pandas, que no viaja por JSON: el color se
 * decide acá, con el estado crudo que manda la API. */
function TablaVerificacion({ datos }) {
  if (!datos || !datos.filas.length) return e("p", { className: "vacio" }, "Sin controles.");
  return e("div", { className: "tabla-scroll" },
    e("table", { className: "tabla" },
      e("thead", null, e("tr", null,
        datos.columnas.map((c) => e("th", { key: c }, etiqueta(c))))),
      e("tbody", null,
        datos.filas.map((fila, i) =>
          e("tr", { key: i },
            datos.columnas.map((c) => {
              const v = fila[c];
              const esEstado = c === "estado";
              return e("td", {
                key: c,
                className: typeof v === "number" ? "num" : null,
                style: esEstado ? { color: COLOR_ESTADO[v] || null, fontWeight: 600 } : null,
              }, v === null || v === undefined ? "—"
                 : typeof v === "number" ? miles(v) : String(v));
            }))))));
}
