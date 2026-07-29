/*
 * Plania · Escritorio (Electron)
 * ==============================
 * Ventana nativa que levanta el servidor de Plania y lo muestra embebido:
 * el usuario hace doble clic en Plania.exe y ve la aplicación, sin saber
 * que abajo corre Python.
 *
 * Orden de arranque del backend:
 *   1. Empaquetado (producción): resources/backend/Plania.exe — el bundle
 *      PyInstaller que genera `python packaging/build_release.py` y que
 *      electron-builder copia vía extraResources.
 *   2. Desarrollo: `python -m streamlit run app/app.py` desde la raíz del repo.
 *
 * Mientras el servidor levanta se muestra un splash en React (renderer/).
 */
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");
const fs = require("fs");

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

function lanzarBackend(port) {
  const env = {
    ...process.env,
    STREAMLIT_SERVER_PORT: String(port),
    STREAMLIT_SERVER_HEADLESS: "true",
    STREAMLIT_BROWSER_GATHER_USAGE_STATS: "false",
    PLANIA_NO_BROWSER: "1", // que el launcher no abra otro navegador
  };

  // 1) bundle PyInstaller embebido (producción)
  const empaquetado = path.join(process.resourcesPath || "", "backend",
    process.platform === "win32" ? "Plania.exe" : "Plania");
  if (app.isPackaged) {
    // En una instalación NO se cae nunca al python del sistema: el cliente no
    // tiene Python, así que ese intento fallaba en silencio y la ventana se
    // quedaba en el splash para siempre — "el instalador no funciona". Si el
    // backend no está, es que el instalador se armó mal, y hay que decirlo.
    if (!fs.existsSync(empaquetado)) {
      throw new Error(
        "La instalación está incompleta: falta el motor de Plania en\n" +
        empaquetado + "\n\n" +
        "Descargá el instalador de nuevo desde la página de Releases.");
    }
    // Plania.exe se compila CON consola (packaging/plania.spec: console=True)
    // porque en el instalador standalone esa ventana es la forma de cerrar
    // el programa. Acá, embebido en Electron, esa consola sería una segunda
    // ventana negra flotando detrás de la nuestra — windowsHide la evita sin
    // tocar el build compartido con el instalador standalone.
    return spawn(empaquetado, [], {
      env, cwd: path.dirname(empaquetado), windowsHide: true,
    });
  }

  // 2) desarrollo: python del sistema contra el repo
  const raiz = path.join(__dirname, "..");
  const python = process.platform === "win32" ? "python" : "python3";
  return spawn(python,
    ["-m", "streamlit", "run", path.join("app", "app.py"),
     `--server.port=${port}`, "--server.headless=true"],
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
    title: "Plania",
    icon: path.join(__dirname, "..", "assets", "brand", "plania_icon.png"),
    backgroundColor: "#1F3D7A",
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js") },
  });

  await win.loadFile(path.join(__dirname, "renderer", "index.html")); // splash React

  try {
    const port = await puertoLibre();
    backend = lanzarBackend(port);
    backend.on("error", (err) => mostrarError(err.message));
    backend.on("exit", (code) => {
      if (win && !win.isDestroyed() && code !== 0 && code !== null) {
        mostrarError(`El motor de Plania se cerró con código ${code}.`);
      }
    });
    const url = `http://127.0.0.1:${port}`;
    await esperarServidor(url);
    if (win && !win.isDestroyed()) await win.loadURL(url);
  } catch (e) {
    mostrarError(e.message);
  }
}

function mostrarError(motivo) {
  if (!win || win.isDestroyed()) return;
  win.loadFile(path.join(__dirname, "renderer", "index.html"),
    { query: { error: "1", motivo: String(motivo || "").slice(0, 400) } });
}

app.whenReady().then(crearVentana);

app.on("window-all-closed", () => {
  if (backend) backend.kill();
  app.quit();
});

app.on("before-quit", () => {
  if (backend) backend.kill();
});
