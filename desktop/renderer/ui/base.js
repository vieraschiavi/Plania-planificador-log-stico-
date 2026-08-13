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

async function pedir(ruta, cuerpo) {
  const opciones = cuerpo
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo) }
    : {};
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
