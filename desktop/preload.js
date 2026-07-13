const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("plania", {
  version: "1.0.0",
});
