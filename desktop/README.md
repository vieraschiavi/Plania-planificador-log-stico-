# Plania · Escritorio (Electron + React)

Ventana nativa de Windows que arranca el servidor de Plania y lo muestra
embebido. El splash de carga está hecho en React (UMD, sin build step de
frontend). Produce `Plania Setup.exe` (instalador NSIS) y un `.exe` portable.

## Construir el .exe (en Windows)

```powershell
# 1. (Recomendado) Empaquetar primero el backend Python autocontenido:
pip install -r ..\requirements.txt pyinstaller
python ..\packaging\build_release.py        # deja ..\dist\Plania\

# 2. Construir el escritorio:
npm install
npm run dist                                 # → dist_electron\Plania Setup 1.0.0.exe (+ portable)
```

Si el paso 1 se salteó, el .exe igual funciona en modo desarrollo usando el
Python del sistema (requiere `pip install -r requirements.txt`); con el
paso 1 hecho, el instalador queda **100% autocontenido**: el cliente no
necesita tener Python.

## Desarrollo

```bash
npm install
npm start        # levanta la ventana contra el repo (usa python del sistema)
```

## Cómo funciona

- `main.js` elige un puerto libre, lanza el backend (bundle PyInstaller si
  está empaquetado; `python -m streamlit run app/app.py` en desarrollo),
  espera a que el servidor responda y carga la app en la ventana.
- `renderer/` es el splash React que se ve mientras levanta (y la pantalla
  de error si no pudo).
- Al cerrar la ventana se mata el proceso del servidor.
