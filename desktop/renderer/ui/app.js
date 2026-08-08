/*
 * Plania · Armazón de la interfaz de escritorio
 * =============================================
 * Menú lateral + pantalla activa. El menú replica el de la versión actual,
 * incluidas las pantallas que todavía no están migradas: se listan y avisan
 * que siguen en la versión anterior, en vez de desaparecer del menú. Un menú
 * que se achica entre versiones parece un producto al que le sacaron
 * funciones.
 */

// El orden es el de app/app.py: la migración no reordena el producto.
const MENU = [
  { id: "inicio", nombre: "Inicio", componente: PantallaInicio },
  { id: "panel", nombre: "Panel ejecutivo", componente: PantallaPanel },
  { id: "stock", nombre: "Stock y reposición", componente: PantallaStock },
  { id: "precios", nombre: "Precios y márgenes", componente: PantallaPrecios },
  { id: "zonas", nombre: "Zonas y negocios", componente: PantallaZonas },
  { id: "rutas", nombre: "Rutas de reparto", componente: PantallaRutas },
  { id: "ofertas", nombre: "Ofertas y sugerencias", componente: PantallaOfertas },
  { id: "copiloto", nombre: "Copiloto IA", componente: PantallaCopiloto },
  { id: "erp", nombre: "Conectar ERP", componente: PantallaERP },
  { id: "licencia", nombre: "Planes y licencia", componente: PantallaLicencia },
  { id: "config", nombre: "Configuración", componente: PantallaConfig },
  { id: "ayuda", nombre: "Ayuda", componente: PantallaAyuda },
];

function Lateral({ actual, ir, licencia }) {
  return e("aside", { className: "lateral" },
    e("div", { className: "logo" }, "PLAN", e("span", null, "IA")),
    e("nav", { className: "menu" },
      MENU.map((m) =>
        e("button", {
          key: m.id,
          className: "item" + (m.id === actual ? " activo" : ""),
          onClick: () => ir(m.id),
        }, m.nombre))),
    e("div", { className: "pie-lateral" },
      licencia
        ? (licencia.modo === "demo"
            ? e("div", null,
                e("b", null, "Demo full"), e("br", null),
                `quedan ${miles(licencia.horas_restantes)} h`)
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
    // La `key` fuerza a React a desmontar la pantalla anterior al cambiar de
    // sección. Sin eso, el estado interno (filtros, hilo del copiloto, un plan
    // de rutas ya calculado) se filtraba de una pantalla a la siguiente.
    e("main", { className: "contenido" },
      e(item.componente, { key: item.id })));
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App, null));
