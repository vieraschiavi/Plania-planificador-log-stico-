/*
 * Plania · Armazón de la interfaz de escritorio
 * =============================================
 * Menú lateral + pantalla activa. El menú replica el de la versión actual,
 * incluidas las pantallas que todavía no están migradas: se listan y avisan
 * que siguen en la versión anterior, en vez de desaparecer del menú. Un menú
 * que se achica entre versiones parece un producto al que le sacaron
 * funciones.
 */

// El orden es el de app/app.py. `listo: false` = todavía en Streamlit.
const MENU = [
  { id: "inicio", nombre: "Inicio", listo: true, componente: PantallaInicio },
  { id: "panel", nombre: "Panel ejecutivo", listo: true, componente: PantallaPanel },
  { id: "stock", nombre: "Stock y reposición", listo: false },
  { id: "precios", nombre: "Precios y márgenes", listo: false },
  { id: "zonas", nombre: "Zonas y negocios", listo: false },
  { id: "rutas", nombre: "Rutas de reparto", listo: false },
  { id: "ofertas", nombre: "Ofertas y sugerencias", listo: false },
  { id: "copiloto", nombre: "Copiloto IA", listo: true, componente: PantallaCopiloto },
  { id: "erp", nombre: "Conectar ERP", listo: false },
  { id: "licencia", nombre: "Planes y licencia", listo: false },
  { id: "config", nombre: "Configuración", listo: false },
];

function PantallaPendiente({ nombre }) {
  return e("div", null,
    e("h1", null, nombre),
    e("div", { className: "pendiente" },
      e("p", null, "Esta pantalla todavía se muestra en la versión anterior de la interfaz."),
      e("p", { className: "chico" },
        "Está migrándose una por una para que ninguna cambie los números al pasar. "
        + "Mientras tanto se usa normalmente desde la versión instalada.")));
}

function Lateral({ actual, ir, licencia }) {
  return e("aside", { className: "lateral" },
    e("div", { className: "logo" }, "PLAN", e("span", null, "IA")),
    e("nav", { className: "menu" },
      MENU.map((m) =>
        e("button", {
          key: m.id,
          className: "item" + (m.id === actual ? " activo" : "") + (m.listo ? "" : " pendiente-item"),
          onClick: () => ir(m.id),
          title: m.listo ? m.nombre : `${m.nombre} — todavía en la versión anterior`,
        }, m.nombre))),
    e("div", { className: "pie-lateral" },
      licencia
        ? (licencia.modo === "demo"
            ? e("div", null,
                e("b", null, "Demo full"), e("br", null),
                `quedan ${miles(licencia.horas_restantes ?? (licencia.dias_restantes || 0) * 24)} h`)
            : licencia.modo === "licencia"
              ? e("div", null, e("b", null, `Plan ${licencia.plan}`), e("br", null),
                  `vence en ${miles(licencia.dias_restantes)} días`)
              : e("div", { className: "vencida" }, "Demo vencida"))
        : null));
}

function App() {
  const [actual, setActual] = React.useState("inicio");
  const { datos: licencia } = useDatos(() => pedir("/licencia"), []);

  const item = MENU.find((m) => m.id === actual) || MENU[0];
  return e("div", { className: "app" },
    e(Lateral, { actual, ir: setActual, licencia }),
    e("main", { className: "contenido" },
      item.listo && item.componente
        ? e(item.componente, null)
        : e(PantallaPendiente, { nombre: item.nombre })));
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App, null));
