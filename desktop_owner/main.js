// © 2026 Martín Viera. Todos los derechos reservados.
/*
 * Plania Owner · Escritorio (Electron)
 * ====================================
 * Ventana del panel del dueño. Levanta el motor de Plania en modo API y
 * dibuja las seis pantallas del panel contra los endpoints /owner/*.
 *
 * Es un programa aparte del producto, no un modo suyo. La razón está escrita
 * en packaging/plania.spec: el Plania que usa un cliente y el que usa el
 * dueño tienen que poder ser el mismo archivo, así que lo del dueño se
 * construye afuera. Del lado de Python eso ya era así (plania_owner.spec);
 * esto es lo mismo del lado de la ventana.
 *
 * No hay token de acceso acá, y es a propósito: no lo protege una clave, lo
 * protege que este programa no existe en la máquina de nadie más. El panel
 * Streamlit sí lo pide porque `streamlit run` puede quedar escuchando en la
 * red (ver app/owner.py); esto escucha en 127.0.0.1 y se dibuja desde el
 * disco.
 */
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");
const fs = require("fs");

const crypto = require("crypto");

/* Token de esta corrida, generado acá y compartido con el motor.
 *
 * Escuchar en 127.0.0.1 frena a la red, pero no al navegador del propio
 * usuario: una página cualquiera que abra mientras Plania corre puede pedirle
 * a http://127.0.0.1:<puerto>, y los puertos que prueba el lanzador son cinco
 * fijos. Sin esto, esa página leía la venta y el margen del cliente y podía
 * cambiarle la conexión a su base. Se genera nuevo en cada arranque: no hay
 * nada que guardar ni que rotar. */
const TOKEN_API = crypto.randomBytes(32).toString("hex");

let backend = null;
let win = null;

function puertoLibre() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

function archivoPuerto() {
  return path.join(app.getPath("userData"), "puerto.txt");
}

function esperarPuerto(archivo, intentos = 120) {
  return new Promise((resolve, reject) => {
    const probar = (restantes) => {
      let contenido = null;
      try {
        contenido = fs.readFileSync(archivo, "utf8").trim();
      } catch (e) { /* todavía no existe */ }
      const port = parseInt(contenido, 10);
      if (port > 0 && port < 65536) return resolve(port);
      if (restantes <= 0) {
        return reject(new Error("El motor de Plania no informó en qué puerto quedó."));
      }
      setTimeout(() => probar(restantes - 1), 500);
    };
    probar(intentos);
  });
}

function lanzarBackend(port, archivo) {
  const env = {
    ...process.env,
    PLANIA_API_TOKEN: TOKEN_API,
    PLANIA_NO_BROWSER: "1",
    PLANIA_PUERTO_ARCHIVO: archivo,
    // La ventana dibuja React, así que el motor sirve la API local y no la
    // pantalla Streamlit — igual que en el producto. Con el árbol del dueño,
    // esa API monta además las rutas /owner/* (plania/api_owner.py).
    PLANIA_MOTOR: "api",
  };
  if (port) env.STREAMLIT_SERVER_PORT = String(port);

  const empaquetado = path.join(process.resourcesPath || "", "backend",
    process.platform === "win32" ? "Plania Owner.exe" : "Plania Owner");
  if (app.isPackaged) {
    if (!fs.existsSync(empaquetado)) {
      throw new Error(
        "La instalación está incompleta: falta el motor en\n" + empaquetado + "\n\n" +
        "Se arma con `python packaging/build_release.py --con-owner`.");
    }
    return spawn(empaquetado, [], {
      env, cwd: path.dirname(empaquetado), windowsHide: true,
    });
  }

  // Desarrollo: python del sistema contra el repo. Sirve `plania.api:app`
  // directo —no el lanzador— porque acá el puerto lo elige esta ventana.
  const raiz = path.join(__dirname, "..");
  const python = process.platform === "win32" ? "python" : "python3";
  return spawn(python,
    ["-m", "uvicorn", "plania.api:app", "--host", "127.0.0.1",
     `--port=${port}`, "--log-level", "warning"],
    { env, cwd: raiz, windowsHide: true });
}

function esperarServidor(url, intentos = 120) {
  return new Promise((resolve, reject) => {
    const probar = (restantes) => {
      http.get(url, () => resolve()).on("error", () => {
        if (restantes <= 0) return reject(new Error("El servidor no levantó"));
        setTimeout(() => probar(restantes - 1), 500);
      });
    };
    probar(intentos);
  });
}

async function crearVentana() {
  win = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    title: "Plania Owner · panel del dueño",
    // Los assets de marca los copia el armador dentro del árbol, para que
    // estas rutas no dependan de a qué profundidad se armó.
    icon: path.join(__dirname, "assets", "brand", "plania_icon.png"),
    // Granate y no el azul del producto: son dos ventanas parecidas de la
    // misma marca, y confundirlas delante de un cliente muestra la
    // facturación. Que se distingan desde el color de fondo del arranque.
    backgroundColor: "#6B1F3D",
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js") },
  });

  try {
    const archivo = archivoPuerto();
    try { fs.unlinkSync(archivo); } catch (e) { /* no existía */ }

    const puertoFijo = app.isPackaged ? null : await puertoLibre();
    backend = lanzarBackend(puertoFijo, archivo);
    backend.on("error", (err) => mostrarError(err.message));
    backend.on("exit", (code) => {
      if (win && !win.isDestroyed() && code !== 0 && code !== null) {
        mostrarError(`El motor de Plania se cerró con código ${code}.`);
      }
    });

    const port = puertoFijo || await esperarPuerto(archivo);
    const url = `http://127.0.0.1:${port}`;
    await esperarServidor(url + "/salud");

    // El puerto viaja en la query, como en el producto: inyectarlo después
    // obliga a recargar, y la recarga borra lo inyectado.
    if (win && !win.isDestroyed()) {
      await win.loadFile(path.join(__dirname, "renderer", "ui", "index.html"),
        { query: { api: url, token: TOKEN_API } });
    }
  } catch (e) {
    mostrarError(e.message);
  }
}

/* Sin splash propio: el panel lo abre una sola persona, que sabe que tarda
 * unos segundos. Se muestra el error en una página mínima armada acá para no
 * arrastrar el splash del producto sólo por esto. */
function mostrarError(motivo) {
  if (!win || win.isDestroyed()) return;
  const html = `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
    <title>Plania Owner</title></head>
    <body style="font-family:Segoe UI,system-ui,sans-serif;background:#6B1F3D;
                 color:#fff;padding:48px">
      <h1 style="margin:0 0 12px">No se pudo abrir el panel</h1>
      <p style="opacity:.85;white-space:pre-wrap">${String(motivo || "")
        .replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
        .slice(0, 400)}</p>
    </body></html>`;
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
}

app.whenReady().then(crearVentana);

app.on("window-all-closed", () => {
  if (backend) backend.kill();
  app.quit();
});

app.on("before-quit", () => {
  if (backend) backend.kill();
});
