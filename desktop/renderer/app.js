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
  const params = new URLSearchParams(window.location.search);
  const conError = params.has("error");
  // El motivo real viaja en la URL: un mensaje genérico obliga a adivinar si
  // falta el backend, si el puerto está ocupado o si el servidor tardó de más.
  const motivo = params.get("motivo");
  return e("div", { style: estilos.contenedor },
    e("div", { style: estilos.logo }, "PLAN", e("span", { style: estilos.logoAcento }, "IA")),
    e("div", { style: estilos.sub }, "Planificación logística y comercial inteligente"),
    conError
      ? e("div", { style: estilos.error },
          e("b", null, "No se pudo iniciar Plania."),
          e("div", { style: { marginTop: "8px", whiteSpace: "pre-wrap" } },
            motivo || "El servidor no respondió."),
          e("div", { style: { marginTop: "10px", opacity: .8, fontSize: "13px" } },
            "Si el problema sigue, escribinos a ventas@plania.uy con este mensaje."))
      : e("div", { style: estilos.barra }, e("div", { style: estilos.progreso })),
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(e(Splash));
