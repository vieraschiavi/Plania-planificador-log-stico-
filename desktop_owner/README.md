# Plania Owner · panel del dueño (Electron + React)

**Uso interno. Nada de acá se entrega a un cliente.**

Las seis pantallas del panel del dueño —facturación, clientes y licencias,
proyección de rentabilidad, mercado, kit de contenido y verificación del
producto— como ventana de escritorio propia, contra los endpoints `/owner/*`
de la API local (`plania/api_owner.py`).

## Por qué es una carpeta aparte y no una pantalla más de `desktop/`

Por la misma razón que del lado de Python el panel se compila con
`packaging/plania_owner.spec` y no con un flag de `plania.spec`: **el Plania
que usa un cliente y el que usa el dueño tienen que poder ser el mismo
archivo**, y eso se garantiza con que el código no esté, no con un permiso
que lo esconda.

Del lado de la ventana hay además un motivo concreto. `desktop/package.json`
empaqueta:

```json
"files": ["main.js", "preload.js", "renderer/**", …]
```

`"renderer/**"` no tiene una sola exclusión, y el camino de electron-builder
**nunca consulta `fuera_del_producto()`** — esa regla vive en
`packaging/proteger_codigo.py` y sólo la usan el `.exe` de PyInstaller y el
ZIP del `.bat`. Un archivo del panel bajo `desktop/renderer/` viajaría en
texto plano dentro del instalador de cada cliente, con los márgenes y el
modelo financiero a la vista, y ningún control lo notaría.

Lo custodia `test_la_ventana_del_cliente_no_lleva_nada_del_panel_del_dueno`,
que revisa el árbol del cliente por nombre de archivo **y** por contenido
(una pantalla renombrada sigue pegándole a `/owner/`, y eso la delata).

## Cómo se arma y se abre

El árbol ejecutable se compone: lo propio sale de acá y lo compartido con el
producto (`base.js`, `estilo.css`, `preload.js`) se copia desde `desktop/`,
para que no haya dos copias que diverjan.

```bash
python packaging/armar_desktop_owner.py     # deja build/desktop_owner/
cd build/desktop_owner && npm start
```

Si es la primera vez, corré antes `npm install` en `desktop/`: el armador
reusa ese `node_modules` en vez de bajar las mismas tres dependencias otra
vez.

## El instalador

```bash
python packaging/build_release.py --con-owner
```

Deja `Plania Owner Setup <versión>.exe` en `build/desktop_owner/dist_electron/`,
con ícono en el escritorio, entrada en el menú Inicio, elección de carpeta y
desinstalador propio. El `appId` es distinto del producto (`uy.plania.owner`),
así que instalar uno no desinstala el otro.

Ese mismo comando arma antes el motor con PyInstaller (`dist/Plania Owner`),
que es lo que el instalador mete adentro como recurso y lo que la ventana
levanta al abrirse. **Sólo corre en Windows**, y sólo en tu máquina: el
workflow de Release no lo arma ni lo publica, y tiene una guarda que corta la
corrida si un archivo del panel aparece entre lo que se va a subir.

### Las dos ventanas salen del mismo motor

`Plania Owner.exe` sirve dos cosas según cómo lo lancen:

| Cómo se lanza | Qué levanta |
|---|---|
| a secas, o por el `.bat` | la pantalla Streamlit (`app/owner.py`) |
| desde esta ventana Electron (`PLANIA_MOTOR=api`) | la API local con las rutas `/owner/*` |

Por eso `packaging/plania_owner.spec` declara `plania.api`, `plania.api_owner`
y los módulos que uvicorn resuelve por nombre en tiempo de ejecución
(`uvicorn.loops.auto` y compañía). Sin ellos PyInstaller compila sin quejarse
y el ejecutable muere recién al abrirse en modo API.

## Qué hay en cada archivo

| Archivo | Qué es |
|---|---|
| `main.js` | proceso principal: levanta el motor en modo API y abre la ventana |
| `renderer/ui/pantallas_owner.js` | las seis pantallas |
| `renderer/ui/app_owner.js` | menú lateral y armazón |
| `renderer/ui/index.html` | orden de carga de los scripts (importa: no hay empaquetador) |
| `renderer/ui/estilo_owner.css` | sólo lo propio del panel; el resto sale de `estilo.css` |
| `package.json` | `appId` propio, para que instalar uno no desinstale el otro |

## Detalles que parecen decorativos y no lo son

- **El lateral es granate y no azul**, y dice "PANEL DEL DUEÑO". Las dos
  ventanas son la misma marca y se parecen; abrir la equivocada en una demo
  con un cliente adelante muestra la facturación. Que se distingan desde el
  color de fondo del arranque.
- **No hay token de acceso.** No lo protege una clave: lo protege que este
  programa no está instalado en ninguna otra máquina. El panel Streamlit sí
  lo pide, porque `streamlit run` puede quedar escuchando en la red
  (ver `app/owner.py`); esto escucha en 127.0.0.1 y se dibuja desde el disco.
- **`base.js` no está en esta carpeta.** Si estuviera, serían dos copias, y
  el día que se arregle el formato de un número en una, la otra seguiría
  mostrando lo de antes.
