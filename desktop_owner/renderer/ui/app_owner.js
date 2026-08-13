// © 2026 Martín Viera. Todos los derechos reservados.
/*
 * Plania Owner · Armazón del panel del dueño
 * ==========================================
 * Mismo armazón que el producto (menú lateral + pantalla activa) con el menú
 * del dueño. Se distingue a simple vista del producto —el lateral va en
 * granate y el título dice "panel del dueño"— porque las dos ventanas se
 * parecen y son la misma marca: abrir una creyendo que es la otra y mostrar
 * la facturación en una demo con un cliente adelante es el error que hay que
 * hacer imposible de cometer por distracción.
 */

// El orden es el del menú de app/owner.py: la migración no reordena nada.
const MENU_OWNER = [
  { id: "negocio", nombre: "Estado del negocio", componente: PantallaEstadoDelNegocio },
  { id: "clientes", nombre: "Clientes y licencias", componente: PantallaClientesYLicencias },
  { id: "rentabilidad", nombre: "Proyección de rentabilidad", componente: PantallaRentabilidad },
  { id: "mercado", nombre: "Mercado y competencia", componente: PantallaMercado },
  { id: "contenido", nombre: "Contenido para redes", componente: PantallaContenido },
  { id: "verificacion", nombre: "Verificación del producto", componente: PantallaVerificacion },
];

function LateralOwner({ actual, ir }) {
  return e("aside", { className: "lateral lateral-owner" },
    e("div", { className: "logo" }, "PLAN", e("span", null, "IA")),
    e("div", { className: "sello-owner" }, "PANEL DEL DUEÑO"),
    e("nav", { className: "menu" },
      MENU_OWNER.map((m) =>
        e("button", {
          key: m.id,
          className: "item" + (m.id === actual ? " activo" : ""),
          onClick: () => ir(m.id),
        }, m.nombre))),
    e("div", { className: "pie-lateral" },
      e("div", null, "Uso interno.", e("br", null), "No se entrega a clientes.")));
}

function AppOwner() {
  const [actual, setActual] = React.useState("negocio");
  const item = MENU_OWNER.find((m) => m.id === actual) || MENU_OWNER[0];
  return e("div", { className: "app" },
    e(LateralOwner, { actual, ir: setActual }),
    // La `key` desmonta la pantalla anterior al cambiar de sección: sin eso,
    // el estado interno (los sliders de la proyección, el resultado de una
    // verificación ya corrida) se filtra de una pantalla a la siguiente.
    e("main", { className: "contenido" },
      e(item.componente, { key: item.id })));
}

ReactDOM.createRoot(document.getElementById("root")).render(e(AppOwner, null));
