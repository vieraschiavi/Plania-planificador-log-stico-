// © 2026 Martín Viera. Todos los derechos reservados.
/*
 * Plania · Interfaz de escritorio — piezas compartidas
 * ====================================================
 * React por UMD y sin paso de compilación, igual que el splash: `npm install`
 * y listo. Meter un empaquetador acá obligaría a que cualquiera que toque la
 * interfaz tenga la cadena de herramientas de frontend armada, y a que el
 * build de release compile el frontend además de Python y Electron.
 *
 * Todo lo que se dibuja sale de la API local (plania/api.py). Ni un número se
 * calcula acá: si se calculara, habría dos fuentes de verdad y el día que
 * difieran, la diferencia se ve delante de un cliente.
 */
const e = React.createElement;

// El puerto lo elige el lanzador —no la ventana— y llega en la query, que
// está disponible desde la primera línea que corre. El valor por defecto es
// para poder abrir la interfaz en un navegador durante el desarrollo.
const API = (new URLSearchParams(location.search).get("api")
             || window.PLANIA_API
             || "http://127.0.0.1:8777").replace(/\/$/, "");

/* El token de esta corrida, por el mismo camino que el puerto.
 *
 * Lo genera la ventana y se lo pasa al motor por entorno; sin él, el motor no
 * contesta. Hace falta porque escuchar en 127.0.0.1 frena a la red pero no al
 * navegador del propio usuario: una página cualquiera que alguien abra
 * mientras Plania corre puede pedirle a http://127.0.0.1:<puerto>, y los
 * puertos que prueba el lanzador son cinco fijos. Sin esto, esa página leía la
 * venta y el margen del cliente, y podía cambiarle la conexión a su base. */
const TOKEN = new URLSearchParams(location.search).get("token") || "";

function cabecerasBase(extra) {
  const h = { ...(extra || {}) };
  if (TOKEN) h["X-Plania-Token"] = TOKEN;
  return h;
}

async function pedir(ruta, cuerpo) {
  const opciones = cuerpo
    ? { method: "POST",
        headers: cabecerasBase({ "Content-Type": "application/json" }),
        body: JSON.stringify(cuerpo) }
    : { headers: cabecerasBase() };
  const r = await fetch(API + ruta, opciones);
  if (!r.ok) {
    // El detalle del backend es más útil que "Error 500": dice qué endpoint y
    // por qué. Si no viene, al menos queda el código.
    let detalle = "";
    try { detalle = (await r.json()).detail || ""; } catch (_) { /* sin cuerpo */ }
    throw new Error(detalle || `${ruta} respondió ${r.status}`);
  }
  return r.json();
}

/* --------------------------------------------------------------------------
 * Formato de números
 * Separadores de acá: 1.234.567,89 — punto para miles, coma para decimales.
 * `toLocaleString("es-UY")` ya lo hace; se fija el locale explícito y no el
 * del sistema porque el mismo programa lo puede correr alguien con Windows
 * en inglés y los importes le saldrían con formato de Estados Unidos.
 * ------------------------------------------------------------------------ */
function miles(n, decimales = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("es-UY", {
    minimumFractionDigits: decimales, maximumFractionDigits: decimales,
  });
}

function plata(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  // Compacto arriba del millón: en una tarjeta angosta "$2.860.000" no entra
  // y se corta, que es peor que perder precisión que nadie mira en un titular.
  if (abs >= 1e6) return "$" + miles(n / 1e6, 2) + " M";
  return "$" + miles(n);
}

function porcentaje(n, decimales = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return miles(n, decimales) + "%";
}

/* --------------------------------------------------------------------------
 * Componentes
 * ------------------------------------------------------------------------ */
function Tarjeta({ titulo, valor, detalle, acento }) {
  return e("div", { className: "tarjeta" },
    e("div", { className: "tarjeta-titulo" }, titulo),
    e("div", { className: "tarjeta-valor", style: acento ? { color: acento } : null }, valor),
    detalle ? e("div", { className: "tarjeta-detalle" }, detalle) : null);
}

/* Una tabla de la API: {columnas, filas, total}.
 *
 * Muestra "200 de 4.312" cuando la API recortó. Sin ese aviso el usuario
 * cree que eso es todo lo que hay y toma decisiones sobre una lista
 * incompleta sin saberlo. */
/* Cómo se llama cada columna en pantalla.
 *
 * Antes el encabezado era el nombre de la columna del DataFrame con los
 * guiones bajos cambiados por espacios, y se notaba: "Sku", "Dias Stock",
 * "Descuento Pct", "Categoria". Sin tildes y con jerga de base de datos a la
 * vista. Para quien pagó un programa, "Pct" no es una palabra.
 *
 * Solo se listan las que hace falta arreglar; cualquier columna nueva cae al
 * comportamiento de antes y se ve razonable, no rota. */
const ETIQUETAS = {
  sku: "SKU", categoria: "Categoría", dias_stock: "Días de stock",
  descuento_pct: "Descuento %", precio_oferta: "Precio oferta",
  capital_inmovilizado: "Capital inmovilizado", lead_time_dias: "Demora proveedor",
  cantidad_sugerida: "Cantidad a pedir", venta_en_riesgo: "Venta en riesgo",
  precio_sugerido: "Precio sugerido", suba_pct: "Suba %", margen_pct: "Margen %",
  margen_obj: "Margen objetivo %", margen_extra_mensual: "Margen extra/mes",
  dias_sin_comprar: "Días sin comprar", venta_historica: "Venta histórica",
  tipo_negocio: "Tipo de negocio", cliente_id: "Cliente", departamento: "Departamento",
  margen_unitario: "Margen unitario", rotacion_dias: "Rotación (días)",
  ticket_promedio: "Ticket promedio", ultima_compra: "Última compra",
};

function etiqueta(col) {
  if (ETIQUETAS[col]) return ETIQUETAS[col];
  const txt = col.replace(/_/g, " ");
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}

/* Cuántos decimales lleva una columna entera.
 *
 * Se decide UNA vez por columna y no celda por celda. Celda por celda,
 * `Number.isInteger(178.0)` da true y `112.8` da false, así que la misma
 * columna de días mostraba "178" en una fila y "112,80" en la de al lado.
 * Leído en una tabla, eso parece que son dos magnitudes distintas. */
function decimalesDe(filas, col) {
  for (const f of filas) {
    const v = f[col];
    if (typeof v === "number" && !Number.isInteger(v)) return 2;
  }
  return 0;
}

function Tabla({ datos, vacio }) {
  if (!datos || !datos.filas.length) {
    return e("p", { className: "vacio" }, vacio || "Sin datos para mostrar.");
  }
  const recortada = datos.total > datos.filas.length;
  const decimales = {};
  datos.columnas.forEach((c) => { decimales[c] = decimalesDe(datos.filas, c); });
  return e("div", null,
    e("div", { className: "tabla-scroll" },
      e("table", { className: "tabla" },
        e("thead", null, e("tr", null,
          datos.columnas.map((c) => e("th", { key: c }, etiqueta(c))))),
        e("tbody", null,
          datos.filas.map((fila, i) =>
            e("tr", { key: i },
              datos.columnas.map((c) => {
                const v = fila[c];
                const numero = typeof v === "number";
                return e("td", { key: c, className: numero ? "num" : null },
                  v === null || v === undefined ? "—"
                    : numero ? miles(v, decimales[c])
                    : String(v));
              })))))),
    recortada
      ? e("p", { className: "nota-tabla" },
          `Mostrando ${miles(datos.filas.length)} de ${miles(datos.total)} filas.`)
      : null);
}

function Cargando({ que }) {
  return e("div", { className: "cargando" }, `Cargando ${que || "datos"}…`);
}

/* El error se muestra completo y con el reintento a mano. Un mensaje genérico
 * obliga al usuario a llamar a soporte para algo que muchas veces se resuelve
 * solo (el motor todavía estaba levantando). */
function Error_({ mensaje, reintentar }) {
  return e("div", { className: "error-caja" },
    e("div", { className: "error-titulo" }, "No se pudieron traer los datos"),
    e("div", { className: "error-detalle" }, String(mensaje)),
    reintentar ? e("button", { className: "btn", onClick: reintentar }, "Reintentar") : null);
}

/* Hook de carga: estados de carga, error y reintento en un solo lugar, para
 * que ninguna pantalla se olvide de manejar el error y quede en blanco. */
function useDatos(cargar, deps) {
  const [estado, setEstado] = React.useState({ cargando: true, datos: null, error: null });
  const [intento, setIntento] = React.useState(0);
  React.useEffect(() => {
    let vivo = true;
    setEstado({ cargando: true, datos: null, error: null });
    cargar()
      .then((d) => { if (vivo) setEstado({ cargando: false, datos: d, error: null }); })
      .catch((err) => { if (vivo) setEstado({ cargando: false, datos: null, error: err.message }); });
    return () => { vivo = false; };
  }, [...(deps || []), intento]);
  return { ...estado, reintentar: () => setIntento((n) => n + 1) };
}

/* --------------------------------------------------------------------------
 * Piezas que usan las dos interfaces
 * Viven acá y no en las pantallas porque hay dos programas que las dibujan:
 * el producto (desktop/) y el panel del dueño (desktop_owner/), que se arma
 * aparte justamente para que su código no viaje en el build del cliente.
 * Tener una sola implementación evita que los gráficos y las descargas se
 * comporten distinto en uno y en otro.
 * ------------------------------------------------------------------------ */

/* Paleta de series, en el orden en que se usan. Son los colores de la marca
 * (estilo.css) escritos acá porque Plotly no lee CSS. */
const COLORES_SERIE = ["#2E86DE", "#20BF6B", "#F39C12", "#E74C3C", "#1F3D7A"];

/* Gráficos con Plotly, el mismo que usa la versión actual: así las escalas,
 * los ejes y los colores no cambian entre una versión y la otra.
 *
 * `y` puede ser una columna o varias: la proyección del panel del dueño
 * superpone resultado y caja en el mismo eje, y separarlos en dos gráficos
 * esconde justamente lo que hay que mirar (el mes en que se cruzan). */
function Grafico({ tipo, datos, x, y, cero }) {
  const div = React.useRef(null);
  React.useEffect(() => {
    if (!div.current || !datos || !datos.filas.length) return;
    const columnas = Array.isArray(y) ? y : [y];
    const xs = datos.filas.map((f) => f[x]);

    // El margen izquierdo se calcula, no se fija: en las barras horizontales
    // las etiquetas son nombres de categoría y con un margen fijo de 60px se
    // cortaban ("erfumería", "ongelados"). Se estima por el nombre más largo,
    // con tope para que una categoría con nombre kilométrico no se coma el
    // gráfico entero.
    const etiquetas = tipo === "barra"
      ? datos.filas.map((f) => String(f[columnas[0]])) : [];
    const masLarga = etiquetas.reduce((m, s) => Math.max(m, s.length), 0);
    const izquierda = tipo === "barra" ? Math.min(180, Math.max(70, masLarga * 7.5 + 14)) : 60;

    const comun = {
      paper_bgcolor: "transparent", plot_bgcolor: "transparent",
      font: { color: "#5A6B85", family: "Segoe UI, system-ui, sans-serif" },
      margin: { t: 10, b: 40, l: izquierda, r: 16 }, height: 300,
      xaxis: { gridcolor: "#E3E8F2" },
      yaxis: { gridcolor: "#E3E8F2", automargin: true },
      showlegend: columnas.length > 1,
      legend: { orientation: "h", y: -0.2 },
      // Con valores negativos (los primeros meses de la proyección dan
      // pérdida) el cero es la referencia que dice si se está arriba o abajo.
      shapes: cero
        ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0,
             line: { color: "#9AA7BD", width: 1, dash: "dot" } }]
        : [],
    };
    const trazos = columnas.map((col, i) => {
      const ys = datos.filas.map((f) => f[col]);
      const color = COLORES_SERIE[i % COLORES_SERIE.length];
      const nombre = etiqueta(col);
      if (tipo === "barra") {
        return { x: xs, y: ys, name: nombre, type: "bar", orientation: "h",
                 marker: { color } };
      }
      if (tipo === "columna") {
        return { x: xs, y: ys, name: nombre, type: "bar", marker: { color } };
      }
      if (tipo === "linea") {
        return { x: xs, y: ys, name: nombre, type: "scatter", mode: "lines",
                 line: { color } };
      }
      return { x: xs, y: ys, name: nombre, type: "scatter", fill: "tozeroy",
               line: { color } };
    });
    if (tipo === "columna" && columnas.length > 1) comun.barmode = "group";
    Plotly.newPlot(div.current, trazos, comun, { displayModeBar: false, responsive: true });
    return () => { if (div.current) Plotly.purge(div.current); };
  }, [datos, tipo, x, y, cero]);

  if (!datos || !datos.filas.length) return e("p", { className: "vacio" }, "Sin datos.");
  return e("div", { ref: div, className: "grafico" });
}

function Exportar({ clave, etiqueta, base }) {
  // `base` existe porque hay dos programas que exportan contra rutas
  // distintas (el producto y el panel del dueño) y el resto del componente
  // —blob, descarga, revocación, manejo de error— es idéntico.
  const raiz = base || "/exportar";
  const [estado, setEstado] = React.useState(null);

  async function bajar(formato) {
    setEstado("Generando…");
    try {
      const r = await fetch(`${API}${raiz}/${clave}.${formato}`,
                            { headers: cabecerasBase() });
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
