/*
 * Splash de arranque de Plania — React sin build step (UMD + createElement),
 * para que el escritorio no necesite toolchain de frontend: npm install y listo.
 */
const e = React.createElement;

const estilos = {
  contenedor: {
    height: "100%", display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center", gap: "18px",
  },
  logo: { fontSize: "44px", fontWeight: 800, letterSpacing: ".18em" },
  logoAcento: { color: "#7EB3F0" },
  sub: { fontSize: "15px", opacity: 0.85 },
  barra: {
    width: "260px", height: "4px", borderRadius: "2px",
    background: "rgba(255,255,255,.15)", overflow: "hidden",
  },
  progreso: {
    width: "40%", height: "100%", background: "#2E86DE",
    borderRadius: "2px", animation: "plania-barrido 1.2s ease-in-out infinite",
  },
  error: {
    maxWidth: "460px", textAlign: "center", fontSize: "14px",
    background: "rgba(231,76,60,.15)", border: "1px solid rgba(231,76,60,.4)",
    borderRadius: "10px", padding: "14px 18px", lineHeight: 1.5,
  },
};

const hoja = document.createElement("style");
hoja.textContent = `@keyframes plania-barrido {
  0% { transform: translateX(-100%); } 100% { transform: translateX(350%); }
}`;
document.head.appendChild(hoja);

function Splash() {
  const conError = new URLSearchParams(window.location.search).has("error");
  return e("div", { style: estilos.contenedor },
    e("div", { style: estilos.logo }, "PLAN", e("span", { style: estilos.logoAcento }, "IA")),
    e("div", { style: estilos.sub }, "Planificación logística y comercial inteligente"),
    conError
      ? e("div", { style: estilos.error },
          "No se pudo iniciar el servidor de Plania. Verificá que la instalación esté completa ",
          "(o, en modo desarrollo, que Python y las dependencias estén instaladas: ",
          "pip install -r requirements.txt) y volvé a abrir el programa.")
      : e("div", { style: estilos.barra }, e("div", { style: estilos.progreso })),
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(e(Splash));
