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
  const horas = licencia.horas_restantes;

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

/* --------------------------------------------------------------------------
 * Exportes
 * El archivo lo arma el servidor con los mismos módulos que usa la pantalla:
 * generarlo en el navegador daría dos versiones del informe, y la que el
 * cliente le manda a su proveedor podría no coincidir con la que vio.
 * ------------------------------------------------------------------------ */
function Exportar({ clave, etiqueta }) {
  const [estado, setEstado] = React.useState(null);

  async function bajar(formato) {
    setEstado("Generando…");
    try {
      const r = await fetch(`${API}/exportar/${clave}.${formato}`);
      if (!r.ok) {
        let d = ""; try { d = (await r.json()).detail || ""; } catch (_) {}
        throw new Error(d || `El servidor respondió ${r.status}`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `plania_${clave}.${formato}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Sin revocar, cada descarga deja el archivo entero retenido en memoria
      // mientras la ventana siga abierta.
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setEstado(null);
    } catch (err) {
      setEstado(String(err.message));
    }
  }

  return e("div", { className: "exportes" },
    e("span", { className: "exportes-txt" }, etiqueta || "Exportar:"),
    ["pdf", "docx", "xlsx"].map((f) =>
      e("button", { key: f, className: "btn btn-chico", onClick: () => bajar(f) },
        f.toUpperCase())),
    estado ? e("span", { className: "exportes-estado" }, estado) : null);
}

/* Pestañas simples: varias tablas en una pantalla sin obligar a hacer scroll
   por todas para llegar a la última. */
function Pestanas({ items }) {
  const [activa, setActiva] = React.useState(0);
  const disponibles = items.filter(Boolean);
  if (!disponibles.length) return null;
  const item = disponibles[Math.min(activa, disponibles.length - 1)];
  return e("div", null,
    e("div", { className: "pestanas" },
      disponibles.map((it, i) =>
        e("button", {
          key: it.titulo, className: "pestana" + (i === activa ? " activa" : ""),
          onClick: () => setActiva(i),
        }, it.titulo, it.cantidad !== undefined
             ? e("span", { className: "conteo" }, miles(it.cantidad)) : null))),
    e("div", { className: "pestana-cuerpo" }, item.contenido));
}

function PantallaStock() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/stock"), []);
  const [categoria, setCategoria] = React.useState("");
  if (cargando) return e(Cargando, { que: "el stock" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const k = datos.kpis;
  // El filtro se aplica acá y no en el servidor porque la tabla ya vino
  // entera: ir y volver al backend para filtrar una lista que está en memoria
  // haría que el selector se sienta lento sin ganar nada.
  const rot = categoria
    ? { ...datos.rotacion,
        filas: datos.rotacion.filas.filter((f) => f.categoria === categoria) }
    : datos.rotacion;

  return e("div", null,
    e("h1", null, "Stock y reposición"),
    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "SKUs", valor: miles(k.skus) }),
      e(Tarjeta, { titulo: "Quiebres", valor: miles(k.quiebres),
                   acento: k.quiebres > 0 ? "#E74C3C" : null }),
      e(Tarjeta, { titulo: "Sobrestock (>90 días)", valor: miles(k.sobrestock),
                   acento: k.sobrestock > 0 ? "#F39C12" : null })),

    e(Pestanas, { items: [
      { titulo: "Reposición urgente", cantidad: datos.reposicion.total,
        contenido: datos.reposicion.total
          ? e("div", null,
              e(Exportar, { clave: "reposicion" }),
              e(Tabla, { datos: datos.reposicion }))
          : e("p", { className: "todo-ok" }, "Sin riesgo de quiebre con la rotación actual.") },
      { titulo: "Stock completo", cantidad: datos.rotacion.total,
        contenido: e("div", null,
          datos.categorias.length
            ? e("div", { className: "filtro" },
                e("label", { htmlFor: "cat" }, "Categoría"),
                e("select", { id: "cat", value: categoria,
                              onChange: (ev) => setCategoria(ev.target.value) },
                  e("option", { value: "" }, "Todas"),
                  datos.categorias.map((c) => e("option", { key: c, value: c }, c))))
            : null,
          e(Tabla, { datos: rot, vacio: "Ningún producto en esa categoría." })) },
    ] }));
}

function PantallaPrecios() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/precios"), []);
  if (cargando) return e(Cargando, { que: "precios y márgenes" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  return e("div", null,
    e("h1", null, "Precios y márgenes"),
    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "Margen promedio ponderado",
                   valor: porcentaje(datos.kpis.margen_ponderado_pct) }),
      e(Tarjeta, { titulo: "Margen extra disponible",
                   valor: plata(datos.kpis.margen_extra_mensual) + "/mes",
                   acento: "#20BF6B" })),

    e("h2", null, "Venta vs margen por producto"),
    e(Dispersion, { datos: datos.margen_por_producto }),

    e("h2", null, "Sugerencias de ajuste de precio"),
    datos.ajustes.total
      ? e("div", null,
          e(Exportar, { clave: "precios" }),
          e(Tabla, { datos: datos.ajustes }))
      : e("p", { className: "todo-ok" }, "Márgenes alineados con su categoría."));
}

/* Dispersión venta vs margen, coloreada por categoría — igual que la actual.
   Se separa de `Grafico` porque necesita una traza por categoría en vez de
   una sola serie. */
function Dispersion({ datos }) {
  const div = React.useRef(null);
  React.useEffect(() => {
    if (!div.current || !datos || !datos.filas.length) return;
    const porCat = {};
    datos.filas.forEach((f) => {
      const c = f.categoria || "(sin categoría)";
      (porCat[c] = porCat[c] || []).push(f);
    });
    const trazas = Object.entries(porCat).map(([cat, filas]) => ({
      x: filas.map((f) => f.venta), y: filas.map((f) => f.margen_pct),
      text: filas.map((f) => f.nombre), name: cat,
      type: "scatter", mode: "markers", marker: { size: 7 },
      hovertemplate: "%{text}<br>Venta %{x:,.0f} · Margen %{y:.1f}%<extra>%{fullData.name}</extra>",
    }));
    Plotly.newPlot(div.current, trazas, {
      paper_bgcolor: "transparent", plot_bgcolor: "transparent",
      font: { color: "#5A6B85", family: "Segoe UI, system-ui, sans-serif" },
      margin: { t: 10, b: 45, l: 60, r: 10 }, height: 380,
      xaxis: { title: "Venta ($)", gridcolor: "#E3E8F2" },
      yaxis: { title: "Margen %", gridcolor: "#E3E8F2" },
      legend: { orientation: "h", y: -0.2 },
    }, { displayModeBar: false, responsive: true });
    return () => { if (div.current) Plotly.purge(div.current); };
  }, [datos]);
  if (!datos || !datos.filas.length) return e("p", { className: "vacio" }, "Sin datos.");
  return e("div", { ref: div, className: "grafico" });
}

function PantallaZonas() {
  const [dim, setDim] = React.useState("zona");
  const { cargando, datos, error, reintentar } = useDatos(
    () => pedir(`/zonas?dim=${encodeURIComponent(dim)}`), [dim]);

  const selector = e("div", { className: "filtro" },
    e("span", null, "Ver por"),
    ["zona", "departamento", "tipo_negocio"].map((d) =>
      e("button", { key: d, className: "chip" + (d === dim ? " on" : ""),
                    onClick: () => setDim(d) }, d.replace("_", " "))));

  if (cargando) return e("div", null, e("h1", null, "Zonas y tipos de negocio"), selector, e(Cargando, {}));
  if (error) return e("div", null, e("h1", null, "Zonas y tipos de negocio"), selector,
                      e(Error_, { mensaje: error, reintentar }));

  return e("div", null,
    e("h1", null, "Zonas y tipos de negocio"),
    selector,
    datos.aviso ? e("p", { className: "todo-ok" }, datos.aviso) : null,
    datos.grupo.total
      ? e("div", { className: "dos-columnas" },
          e(Grafico, { tipo: "barra", datos: { ...datos.grupo, filas: datos.grupo.filas.slice(0, 15) },
                       x: "venta", y: dim }),
          e(Tabla, { datos: datos.grupo }))
      : null,

    e("h2", null, "Oportunidades de venta cruzada por zona"),
    datos.oportunidades.total
      ? e("div", null,
          e(Exportar, { clave: "zonas" }),
          e(Tabla, { datos: datos.oportunidades }))
      : e("p", { className: "todo-ok" },
          "Sin brechas de penetración relevantes (o faltan datos de zona)."));
}

function PantallaOfertas() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/ofertas"), []);
  if (cargando) return e(Cargando, { que: "las sugerencias del día" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  const r = datos.resumen;
  const claves = ["ofertas", "reposicion", "precios", "zonas", "recupero"];
  return e("div", null,
    e("h1", null, "Ofertas y sugerencias"),
    e("div", { className: "grilla-tarjetas" },
      e(Tarjeta, { titulo: "Capital liberable", valor: plata(r.capital_liberable), acento: "#20BF6B" }),
      e(Tarjeta, { titulo: "Venta en riesgo", valor: plata(r.venta_en_riesgo), acento: "#E74C3C" }),
      e(Tarjeta, { titulo: "Margen extra/mes", valor: plata(r.margen_extra_mensual) }),
      e(Tarjeta, { titulo: "Potencial por zonas", valor: plata(r.venta_potencial_zonas) })),

    e("div", { className: "exportar-completo" },
      e(Exportar, { clave: "completo", etiqueta: "Exportar informe completo:" })),

    e(Pestanas, { items: claves.map((clave) => {
      const s = datos.secciones[clave];
      return {
        titulo: s.titulo, cantidad: s.tabla.total,
        contenido: s.tabla.total
          ? e("div", null,
              e("p", { className: "bajada" }, s.descripcion),
              e(Exportar, { clave }),
              e(Tabla, { datos: s.tabla }))
          : e("p", { className: "todo-ok" }, "Nada para accionar acá — todo en orden."),
      };
    }) }));
}

function PantallaRutas() {
  const { datos: opciones, error: errOpciones } = useDatos(() => pedir("/rutas/opciones"), []);
  const [vehiculos, setVehiculos] = React.useState(2);
  const [paradas, setParadas] = React.useState(25);
  const [modo, setModo] = React.useState("todos");
  const [deptos, setDeptos] = React.useState([]);
  const [plan, setPlan] = React.useState(null);
  const [estado, setEstado] = React.useState(null);

  async function planificar() {
    setEstado("Calculando rutas…");
    setPlan(null);
    try {
      const r = await pedir("/rutas", {
        vehiculos: Number(vehiculos), paradas_max: Number(paradas),
        departamentos: deptos, modo,
      });
      setPlan(r);
      setEstado(null);
    } catch (err) {
      setEstado(err.message);
    }
  }

  if (errOpciones) return e(Error_, { mensaje: errOpciones });
  if (opciones && !opciones.habilitado) {
    return e("div", null,
      e("h1", null, "Rutas de reparto"),
      e("div", { className: "aviso-demo" },
        "El plan actual no incluye el planificador de rutas — disponible en ",
        e("b", null, "Pro"), " y ", e("b", null, "Enterprise"), "."));
  }

  return e("div", null,
    e("h1", null, "Rutas de reparto"),
    e("div", { className: "form-linea" },
      e("label", null, "Vehículos",
        e("input", { type: "number", min: 1, max: 20, value: vehiculos,
                     onChange: (ev) => setVehiculos(ev.target.value) })),
      e("label", null, "Paradas máx. por vehículo",
        e("input", { type: "number", min: 5, max: 60, value: paradas,
                     onChange: (ev) => setParadas(ev.target.value) })),
      e("label", null, "Departamento",
        e("select", { multiple: true, value: deptos, size: 4,
          onChange: (ev) => setDeptos([...ev.target.selectedOptions].map((o) => o.value)) },
          (opciones ? opciones.departamentos : []).map((d) =>
            e("option", { key: d, value: d }, d))))),

    e("div", { className: "filtro" },
      e("span", null, "A quién visitar"),
      [["activos", "Clientes activos (30 días)"], ["inactivos", "Inactivos (recupero)"],
       ["todos", "Todos"]].map(([id, txt]) =>
        e("button", { key: id, className: "chip" + (modo === id ? " on" : ""),
                      onClick: () => setModo(id) }, txt))),

    e("button", { className: "btn", onClick: planificar, disabled: estado === "Calculando rutas…" },
      "Planificar rutas"),
    estado ? e("p", { className: estado.startsWith("Calculando") ? "cargando" : "error-detalle" }, estado) : null,

    plan ? e("div", null,
      e("p", { className: "bajada" }, `${miles(plan.clientes_a_rutear)} clientes ruteados.`),
      e("h2", null, "Resumen por vehículo"),
      e(Tabla, { datos: plan.resumen }),
      plan.sin_gps && plan.sin_gps.total
        ? e("p", { className: "aviso-demo" },
            `${miles(plan.sin_gps.total)} clientes quedaron afuera por no tener coordenadas. `
            + "Se rutean los que sí las tienen.")
        : null,
      e("h2", null, "Hoja de ruta"),
      e(Exportar, { clave: "completo", etiqueta: "Exportar informe:" }),
      e(Tabla, { datos: plan.rutas })) : null);
}

function PantallaERP() {
  const [url, setUrl] = React.useState("");
  const [prueba, setPrueba] = React.useState(null);
  const [estado, setEstado] = React.useState(null);
  const { datos: actual, reintentar } = useDatos(() => pedir("/erp/estado"), []);

  async function accion(ruta, alTerminar) {
    setEstado("Probando…");
    setPrueba(null);
    try {
      const r = await pedir(ruta, { url });
      setEstado(null);
      alTerminar(r);
    } catch (err) {
      setEstado(err.message);
    }
  }

  return e("div", null,
    e("h1", null, "Conectar tu ERP o base de datos"),
    e("p", { className: "bajada" },
      "Plania ", e("b", null, "no te hace migrar nada"), ": apunta a la base que ya usás y "
      + "auto-detecta las columnas. PostgreSQL, MySQL/MariaDB, SQL Server, Oracle y SQLite."),

    actual && actual.conectado
      ? e("p", { className: "todo-ok" }, `Hoy lee de: ${actual.url_enmascarada}`)
      : e("p", { className: "bajada" }, "Hoy lee de la base demo incluida."),

    e("label", { className: "campo" }, "URL de conexión SQLAlchemy",
      e("input", { value: url, onChange: (ev) => setUrl(ev.target.value),
                   placeholder: "postgresql://usuario:clave@servidor:5432/erp" })),

    e("div", { className: "botonera" },
      e("button", { className: "btn", disabled: !url.trim(),
                    onClick: () => accion("/erp/probar", setPrueba) }, "Probar conexión"),
      e("button", { className: "btn btn-secundario", disabled: !url.trim(),
        onClick: () => accion("/erp/guardar", () => {
          setPrueba({ guardado: true }); reintentar();
        }) }, "Guardar y usar esta base")),

    estado ? e("p", { className: "error-detalle" }, estado) : null,

    prueba && prueba.guardado
      ? e("p", { className: "todo-ok" },
          "Guardado. Toda la aplicación pasa a leer de tu ERP.")
      : null,

    prueba && prueba.ok ? e("div", { className: "resultado-erp" },
      e("p", { className: "todo-ok" }, `Conectado. ${miles(prueba.tablas.length)} tablas.`),
      (prueba.avisos || []).map((a, i) => e("p", { key: i, className: "aviso-demo" }, a)),
      e("table", { className: "tabla-simple" },
        e("tbody", null,
          Object.entries(prueba.autodetectado).map(([que, tabla]) =>
            e("tr", { key: que },
              e("td", null, `Tabla de ${que}`),
              e("td", null, tabla || e("i", null, "no reconocida")))))),
      prueba.tablas.length
        ? e("details", null,
            e("summary", null, `Ver las ${miles(prueba.tablas.length)} tablas`),
            e("p", { className: "lista-tablas" }, prueba.tablas.join(", ")))
        : null) : null);
}

function PantallaLicencia() {
  const { datos, error, reintentar } = useDatos(
    () => Promise.all([pedir("/planes"), pedir("/licencia")])
      .then(([p, l]) => ({ planes: p.planes, licencia: l })), []);
  const [token, setToken] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [plan, setPlan] = React.useState("starter");
  const [msg, setMsg] = React.useState(null);

  if (error) return e(Error_, { mensaje: error, reintentar });
  if (!datos) return e(Cargando, { que: "los planes" });

  async function activar() {
    setMsg({ txt: "Activando…" });
    try {
      const r = await pedir("/licencia/activar", { token: token.trim() });
      setMsg({ txt: `Licencia activada — plan ${r.claims ? r.claims.plan : ""}.`, ok: true });
      reintentar();
    } catch (err) { setMsg({ txt: err.message }); }
  }

  async function pagar() {
    setMsg({ txt: "Pidiendo el link de pago…" });
    try {
      const r = await pedir("/checkout", { plan, email: email.trim() });
      if (r.init_point) {
        setMsg({ txt: "Link listo.", ok: true, link: r.init_point });
      } else {
        setMsg({ txt: "El backend no devolvió un link de pago." });
      }
    } catch (err) { setMsg({ txt: err.message }); }
  }

  const l = datos.licencia;
  return e("div", null,
    e("h1", null, "Planes y licencia"),
    l.modo === "demo"
      ? e("div", { className: "aviso-demo" },
          `Demo full activa — quedan ${miles(l.horas_restantes)} horas. `
          + "Al comprar, tus datos y configuración quedan tal cual.")
      : l.modo === "licencia"
        ? e("p", { className: "todo-ok" }, `Plan ${l.plan} · vence en ${miles(l.dias_restantes)} días.`)
        : e("div", { className: "aviso-vencida" }, "La demo venció. Activá tu licencia para seguir."),

    e("div", { className: "grilla-planes" },
      datos.planes.map((p) =>
        e("article", { key: p.id, className: "plan" + (p.id === "pro" ? " destacado" : "") },
          e("h3", null, p.titulo),
          e("p", { className: "precio" }, p.precio),
          e("p", { className: "detalle" }, p.detalle)))),

    e("h2", null, "Comprar"),
    e("div", { className: "form-linea" },
      e("label", null, "Tu email",
        e("input", { type: "email", value: email, placeholder: "vos@tuempresa.uy",
                     onChange: (ev) => setEmail(ev.target.value) })),
      e("label", null, "Plan",
        e("select", { value: plan, onChange: (ev) => setPlan(ev.target.value) },
          e("option", { value: "starter" }, "Starter"),
          e("option", { value: "pro" }, "Pro")))),
    e("button", { className: "btn", onClick: pagar, disabled: !email.trim() },
      "Pagar con MercadoPago"),

    e("h2", null, "Ya tengo mi licencia"),
    e("label", { className: "campo" }, "Pegá el token de licencia",
      e("input", { type: "password", value: token,
                   onChange: (ev) => setToken(ev.target.value) })),
    e("button", { className: "btn", onClick: activar, disabled: !token.trim() },
      "Activar licencia"),

    msg ? e("p", { className: msg.ok ? "todo-ok" : "error-detalle" },
      msg.txt,
      msg.link ? e("a", { href: msg.link, target: "_blank", rel: "noreferrer",
                          className: "enlace" }, " Ir al checkout seguro") : null) : null);
}

function PantallaConfig() {
  const { cargando, datos, error, reintentar } = useDatos(() => pedir("/config"), []);
  const [valores, setValores] = React.useState({});
  const [msg, setMsg] = React.useState(null);

  if (cargando) return e(Cargando, { que: "la configuración" });
  if (error) return e(Error_, { mensaje: error, reintentar });

  async function guardar() {
    setMsg({ txt: "Guardando…" });
    try {
      const r = await pedir("/config", { valores });
      setValores({});
      setMsg(r.guardadas.length
        ? { txt: `Guardado: ${r.guardadas.join(", ")}.`, ok: true }
        : { txt: "No ingresaste valores nuevos.", ok: true });
      reintentar();
    } catch (err) { setMsg({ txt: err.message }); }
  }

  return e("div", null,
    e("h1", null, "Configuración"),
    e("p", { className: "bajada" },
      "Guardado seguro: ", e("b", null, datos.backend_activo),
      " (keyring del sistema > archivo cifrado > texto plano)."),

    datos.claves.map((c) =>
      e("label", { key: c.clave, className: "campo" }, c.descripcion,
        e("input", {
          type: c.sensible ? "password" : "text",
          value: valores[c.clave] || "",
          placeholder: c.configurada ? c.enmascarado : "(sin configurar)",
          onChange: (ev) => setValores({ ...valores, [c.clave]: ev.target.value }),
        }))),

    e("p", { className: "nota-tabla" },
      "Los valores ya guardados se muestran enmascarados y no se pueden leer desde acá. "
      + "Dejar un campo vacío lo deja como está."),
    e("button", { className: "btn", onClick: guardar }, "Guardar"),
    msg ? e("p", { className: msg.ok ? "todo-ok" : "error-detalle" }, msg.txt) : null);
}

function PantallaAyuda() {
  return e("div", { className: "ayuda" },
    e("h1", null, "Ayuda"),
    e("h2", null, "¿Qué hace Plania?"),
    e("p", null,
      "Se conecta a tu ERP o base de datos (sin migrar nada), analiza stock, precios, "
      + "márgenes, zonas y clientes, y te devuelve decisiones accionables: ofertas, "
      + "reposición, ajustes de precio, rutas de reparto y clientes a recuperar — todo "
      + "exportable a PDF, Word y Excel y consultable por chat con el Copiloto."),
    e("h2", null, "Primeros pasos"),
    e("ol", null,
      e("li", null, e("b", null, "Conectar ERP"), ": apuntá a tu base (o probá con la demo incluida)."),
      e("li", null, e("b", null, "Ofertas y sugerencias"), ": exportá el informe completo del día."),
      e("li", null, e("b", null, "Copiloto"), ": preguntá en criollo — «¿qué repongo ya?».")),
    e("h2", null, "Demo de 7 días"),
    e("p", null,
      "Todo habilitado, sin tarjeta. Al vencer, tus datos no se tocan: activás la "
      + "licencia y seguís donde estabas."),
    e("h2", null, "Soporte"),
    e("p", null, "soporte@plania.uy · WhatsApp +598 99 000 000"));
}
