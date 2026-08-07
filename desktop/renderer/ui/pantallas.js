/*
 * Plania · Pantallas de la interfaz de escritorio
 * ===============================================
 * Cada pantalla pide sus datos a la API local y los dibuja. El orden y el
 * contenido replican lo que hoy muestra app/app.py: la migración no es una
 * oportunidad para rediseñar el producto — si además cambia lo que se ve,
 * no hay forma de saber si una diferencia es un error de la migración o algo
 * que se cambió a propósito.
 */

function PantallaInicio() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/inicio"), []);
  if (cargando) return e(Cargando, { que: "el resumen" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const { kpis, resumen, licencia } = datos;
  const horas = licencia.horas_restantes ?? (licencia.dias_restantes || 0) * 24;

  return e("div", null,
    e("h1", null, "Plania ", e("span", { className: "insignia" }, "PLANIFICACIÓN INTELIGENTE")),

    licencia.modo === "demo"
      ? e("div", { className: "aviso-demo" },
          e("b", null, "Demo de 7 días con todo habilitado"),
          ` — conectá tu ERP real o explorá con la base demo. Quedan ${miles(horas)} horas.`)
      : null,
    licencia.modo === "vencida"
      ? e("div", { className: "aviso-vencida" },
          e("b", null, "La demo venció"),
          " — activá tu licencia en Planes y licencia para seguir usando Plania.")
      : null,

    e("p", { className: "bajada" },
      "El único planificador que ", e("b", null, "se conecta al ERP que ya tenés"),
      " (PostgreSQL, MySQL, SQL Server, Oracle, SQLite, CSV/Excel), te dice ",
      e("b", null, "qué ofertar, qué reponer, qué re-precificar y por dónde repartir"),
      ", y te deja todo listo en ", e("b", null, "PDF/Word/Excel"),
      " — con un copiloto que responde sobre tus datos reales."),

    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "Venta últimos 30 días", valor: plata(kpis.venta_periodo) }),
      e(Tarjeta, { titulo: "Margen", valor: porcentaje(kpis.margen_pct) }),
      e(Tarjeta, { titulo: "Capital liberable (sobrestock)",
                   valor: plata(resumen.capital_liberable), acento: "#20BF6B" }),
      e(Tarjeta, { titulo: "Venta en riesgo (quiebres)",
                   valor: plata(resumen.venta_en_riesgo), acento: "#E74C3C" })),

    e("div", { className: "pista" },
      "Empezá por ", e("b", null, "Ofertas y sugerencias"), " para ver las decisiones de hoy, ",
      "o preguntale al ", e("b", null, "Copiloto"), ": «¿qué ofertas armo esta semana?»"));
}

function PantallaPanel() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/panel"), []);
  if (cargando) return e(Cargando, { que: "el panel" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const k = datos.kpis;
  return e("div", null,
    e("h1", null, "Panel ejecutivo"),
    e("div", { className: "grilla-tarjetas cinco" },
      e(Tarjeta, { titulo: "Venta 30d", valor: plata(k.venta_periodo) }),
      e(Tarjeta, { titulo: "Margen 30d", valor: plata(k.margen_periodo),
                   detalle: porcentaje(k.margen_pct) }),
      e(Tarjeta, { titulo: "Valor stock (costo)", valor: plata(k.valor_stock) }),
      e(Tarjeta, { titulo: "Quiebres / bajo mín.",
                   valor: `${miles(k.quiebres)} / ${miles(k.bajo_minimo)}`,
                   acento: k.quiebres > 0 ? "#E74C3C" : null }),
      e(Tarjeta, { titulo: "Clientes activos 30d", valor: miles(k.clientes_activos) })),

    e("h2", null, "Venta mensual"),
    e(Grafico, { tipo: "area", datos: datos.tendencia, x: "mes", y: "venta" }),

    e("h2", null, "Venta por categoría"),
    e(Grafico, { tipo: "barra", datos: datos.por_categoria, x: "venta", y: "categoria" }),

    e("h2", null, "Top clientes"),
    e(Tabla, { datos: datos.top_clientes }));
}

/* Gráficos con Plotly, el mismo que usa la versión actual: así las escalas,
 * los ejes y los colores no cambian entre una versión y la otra. */
function Grafico({ tipo, datos, x, y }) {
  const div = React.useRef(null);
  React.useEffect(() => {
    if (!div.current || !datos || !datos.filas.length) return;
    const xs = datos.filas.map((f) => f[x]);
    const ys = datos.filas.map((f) => f[y]);

    // El margen izquierdo se calcula, no se fija: en las barras horizontales
    // las etiquetas son nombres de categoría y con un margen fijo de 60px se
    // cortaban ("erfumería", "ongelados"). Se estima por el nombre más largo,
    // con tope para que una categoría con nombre kilométrico no se coma el
    // gráfico entero.
    const etiquetas = tipo === "barra" ? ys.map((v) => String(v)) : [];
    const masLarga = etiquetas.reduce((m, s) => Math.max(m, s.length), 0);
    const izquierda = tipo === "barra" ? Math.min(180, Math.max(70, masLarga * 7.5 + 14)) : 60;

    const comun = {
      paper_bgcolor: "transparent", plot_bgcolor: "transparent",
      font: { color: "#5A6B85", family: "Segoe UI, system-ui, sans-serif" },
      margin: { t: 10, b: 40, l: izquierda, r: 16 }, height: 300,
      xaxis: { gridcolor: "#E3E8F2" },
      yaxis: { gridcolor: "#E3E8F2", automargin: true },
    };
    const trazo = tipo === "area"
      ? { x: xs, y: ys, type: "scatter", fill: "tozeroy", line: { color: "#2E86DE" } }
      : { x: xs, y: ys, type: "bar", orientation: "h", marker: { color: "#2E86DE" } };
    Plotly.newPlot(div.current, [trazo], comun, { displayModeBar: false, responsive: true });
    return () => { if (div.current) Plotly.purge(div.current); };
  }, [datos, tipo, x, y]);

  if (!datos || !datos.filas.length) return e("p", { className: "vacio" }, "Sin datos.");
  return e("div", { ref: div, className: "grafico" });
}

function PantallaCopiloto() {
  const [pregunta, setPregunta] = React.useState("");
  const [historial, setHistorial] = React.useState([]);
  const [pensando, setPensando] = React.useState(false);

  const SUGERIDAS = [
    "¿qué ofertas armo esta semana?",
    "¿qué tengo que reponer?",
    "¿qué precios están dejando margen?",
  ];

  async function preguntar(texto) {
    const q = (texto !== undefined ? texto : pregunta).trim();
    if (!q || pensando) return;
    setPregunta("");
    setPensando(true);
    // La pregunta entra al historial antes de la respuesta: si el motor tarda,
    // el usuario ve que su consulta se registró en vez de creer que se perdió.
    setHistorial((h) => [...h, { rol: "usuario", texto: q }]);
    try {
      const r = await pedir("/copiloto", { pregunta: q });
      setHistorial((h) => [...h, { rol: "plania", ...r }]);
    } catch (err) {
      setHistorial((h) => [...h, { rol: "error", texto: err.message }]);
    } finally {
      setPensando(false);
    }
  }

  return e("div", { className: "copiloto" },
    e("h1", null, "Copiloto IA"),
    e("p", { className: "bajada" },
      "Preguntá sobre tus datos reales. Debajo de cada respuesta queda la tabla "
      + "con la que se calculó, para que puedas verificarla."),

    historial.length === 0
      ? e("div", { className: "sugeridas" },
          SUGERIDAS.map((s) =>
            e("button", { key: s, className: "chip", onClick: () => preguntar(s) }, s)))
      : null,

    e("div", { className: "hilo" },
      historial.map((m, i) => {
        if (m.rol === "usuario") return e("div", { key: i, className: "msg usuario" }, m.texto);
        if (m.rol === "error") return e("div", { key: i, className: "msg error" }, m.texto);
        return e("div", { key: i, className: "msg plania" },
          e("div", { className: "respuesta" }, m.respuesta),
          m.tabla && m.tabla.filas.length
            ? e("details", { className: "evidencia" },
                e("summary", null, m.titulo || "Ver la tabla que usó para calcularlo"),
                e(Tabla, { datos: m.tabla }))
            : null);
      }),
      pensando ? e("div", { className: "msg plania pensando" }, "Calculando sobre tus datos…") : null),

    e("form", { className: "consulta", onSubmit: (ev) => { ev.preventDefault(); preguntar(); } },
      e("input", {
        value: pregunta, placeholder: "Escribí tu consulta…", "aria-label": "Consulta",
        onChange: (ev) => setPregunta(ev.target.value),
      }),
      e("button", { className: "btn", type: "submit", disabled: pensando || !pregunta.trim() },
        "Preguntar")));
}
