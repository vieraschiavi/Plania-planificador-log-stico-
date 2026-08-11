"""
Plania · Control del instalador de Windows
==========================================
Revisa que el instalador esté bien armado sin necesidad de una máquina
Windows ni de Inno Setup.

    python3 packaging/verificar_instalador.py

No reemplaza probar el .exe en Windows: no compila nada ni ejecuta el
instalador. Lo que sí hace es cazar la clase de error que sólo aparece
cuando alguien ya lo descargó — que el instalador apunte a un archivo que no
existe, que le falte la opción de elegir carpeta, que no cree los accesos
directos, o que el ejecutable y el que instala el escritorio no coincidan.
Son errores baratos de cometer al editar y caros de descubrir tarde.

Devuelve código 1 si algo está mal, así sirve en CI y antes de publicar.
"""
from __future__ import annotations

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(RAIZ, "packaging", "instalador.iss")
SPEC = os.path.join(RAIZ, "packaging", "plania.spec")
PKG_ELECTRON = os.path.join(RAIZ, "desktop", "package.json")


def _regla_del_producto():
    """`fuera_del_producto` de packaging/proteger_codigo.py, cargada por ruta.

    Por ruta y no con `import proteger_codigo` para que este control funcione
    igual corriéndolo desde cualquier carpeta, que es como lo llama el
    workflow y como lo llaman los tests.
    """
    import importlib.util
    ruta = os.path.join(RAIZ, "packaging", "proteger_codigo.py")
    spec = importlib.util.spec_from_file_location("_plania_proteger", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.fuera_del_producto


def _leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8", errors="replace") as f:
        return f.read()


def _directivas(iss: str) -> dict:
    """Las directivas de [Setup], en minúscula, sin comentarios."""
    fuera = {}
    dentro = False
    for linea in iss.splitlines():
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == "[setup]"
            continue
        if not dentro or not limpia or limpia.startswith(";"):
            continue
        if "=" in limpia:
            clave, valor = limpia.split("=", 1)
            fuera[clave.strip().lower()] = valor.strip()
    return fuera


def _seccion(iss: str, nombre: str) -> list[str]:
    """Las líneas útiles de una sección, con las continuaciones (\\) unidas."""
    lineas, dentro = [], False
    for linea in iss.splitlines():
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == f"[{nombre.lower()}]"
            continue
        if not dentro or not limpia or limpia.startswith(";"):
            continue
        if lineas and lineas[-1].endswith("\\"):
            lineas[-1] = lineas[-1][:-1].rstrip() + " " + limpia
        else:
            lineas.append(limpia)
    return lineas


# Funciones de la API de Windows que el lenguaje de Inno Setup NO trae: si se
# usan, hay que declararlas con `external`. Olvidarse es un error de compilación
# que sólo aparece al correr `iscc` en Windows — o sea, tarde.
API_WINDOWS = ("GetDriveType", "GetDiskFreeSpaceEx", "SHGetFolderPath",
               "GetVolumeInformation", "GetLogicalDrives", "MoveFileEx")


def _codigo_pascal(iss: str) -> list[tuple[int, str]]:
    """Las líneas de la sección [Code], numeradas, sin comentarios."""
    salida, dentro = [], False
    for n, linea in enumerate(iss.splitlines(), start=1):
        limpia = linea.strip()
        if limpia.startswith("["):
            dentro = limpia.lower() == "[code]"
            continue
        if not dentro or limpia.startswith("//") or not limpia:
            continue
        salida.append((n, limpia))
    return salida


def controles_pascal(iss: str) -> list[tuple[bool, str, str]]:
    """Errores del script Pascal que se pueden ver sin compilar.

    No es un compilador: es una red para los tres tropiezos que de verdad
    pasan al editar este archivo desde fuera de Windows, donde no hay `iscc`
    para avisar.
    """
    lineas = _codigo_pascal(iss)
    r = []

    # 1. Literales de texto pegados sin '+'. En Pascal eso no existe —viene de
    #    la costumbre de Python, donde dos literales seguidos se concatenan
    #    solos— y es un error de compilación.
    pegados = []
    for i in range(len(lineas) - 1):
        actual, siguiente = lineas[i][1], lineas[i + 1][1]
        if actual.endswith("'") and siguiente.startswith("'"):
            pegados.append(lineas[i + 1][0])
    r.append((not pegados, "No hay literales de texto concatenados sin '+'",
              f"líneas {pegados}: en Pascal dos literales seguidos no se unen "
              "solos, hay que poner '+'"))

    # 2. API de Windows usada sin declarar.
    cuerpo = "\n".join(l for _, l in lineas)
    sin_declarar = [f for f in API_WINDOWS
                    if re.search(rf"\b{f}\s*\(", cuerpo)
                    and not re.search(rf"function\s+{f}\b[\s\S]{{0,200}}?external", cuerpo)]
    r.append((not sin_declarar, "Las funciones de la API de Windows están declaradas",
              f"{sin_declarar} se usan sin `external ...@kernel32.dll`: `iscc` "
              "no compila"))

    # 3. begin/end balanceados en el bloque completo.
    palabras = re.findall(r"\b(begin|end)\b", cuerpo, re.IGNORECASE)
    abiertos = sum(1 for p in palabras if p.lower() == "begin")
    cerrados = sum(1 for p in palabras if p.lower() == "end")
    r.append((abiertos == cerrados, "Los begin/end del script están balanceados",
              f"{abiertos} 'begin' contra {cerrados} 'end'"))

    # 4. Paréntesis balanceados fuera de los literales.
    sin_texto = re.sub(r"'[^']*'", "", cuerpo)
    r.append((sin_texto.count("(") == sin_texto.count(")"),
              "Los paréntesis del script están balanceados",
              f"{sin_texto.count('(')} '(' contra {sin_texto.count(')')} ')'"))

    # 5. Ninguna línea puede EMPEZAR con '#' salvo que sea una directiva real
    #    del preprocesador. Para ISPP, el primer carácter no blanco de la línea
    #    manda: si es '#', lo que sigue tiene que ser una directiva suya. Una
    #    continuación de expresión Pascal partida así:
    #
    #        MsgBox('Está abierto.' + #13#10 +
    #               #13#10 + 'Cerralo.', mbError, MB_OK);
    #
    #    compila mentalmente perfecto y es exactamente lo que rompió el build:
    #    "Error on line 180: Unknown preprocessor directive" — porque leyó
    #    `#13` como directiva. El arreglo es no cortar la línea ahí; el
    #    `#13#10` va al final de la línea anterior.
    #
    #    Cuesta 6 minutos de runner de Windows descubrirlo allá y cero acá,
    #    y no lo agarra ningún otro control: el Pascal está bien escrito.
    directivas_ispp = ("define", "undef", "include", "if", "ifdef", "ifndef",
                       "ifexist", "ifnexist", "elif", "else", "endif", "error",
                       "pragma", "expr", "insert", "append", "emit", "file",
                       "for", "sub", "endsub", "dim", "redim")
    mal = []
    for n, linea in enumerate(iss.splitlines(), start=1):
        limpia = linea.strip()
        if not limpia.startswith("#"):
            continue
        palabra = re.match(r"#\s*(\w+)", limpia)
        if not palabra or palabra.group(1).lower() not in directivas_ispp:
            mal.append(n)
    r.append((not mal, "Ninguna línea arranca con '#' que no sea directiva ISPP",
              f"líneas {mal}: el preprocesador de Inno lee el '#' inicial como "
              "directiva suya (típico: cortar la línea justo antes de un "
              "#13#10). Mové ese #13#10 al final de la línea de arriba"))

    return r


def controles() -> list[tuple[bool, str, str]]:
    """(pasa, título, detalle) por cada cosa comprobada."""
    iss = _leer(ISS)
    d = _directivas(iss)
    r: list[tuple[bool, str, str]] = []

    def ok(cond, titulo, detalle):
        r.append((bool(cond), titulo, detalle))

    # --- Elegir carpeta y disco -------------------------------------------
    ok(d.get("disabledirpage", "").lower() == "no",
       "Se puede elegir la carpeta de instalación",
       "DisableDirPage tiene que ser 'no' explícito: si se omite, Inno Setup "
       "decide solo si mostrar esa página y a veces no la muestra")
    ok("defaultdirname" in d,
       "Hay una carpeta propuesta por defecto",
       "sin DefaultDirName el instalador arranca sin ruta sugerida")
    for necesaria in ("NextButtonClick", "wpSelectDir", "GetDriveType",
                      "GetSpaceOnDisk64", "CarpetaEsEscribible"):
        ok(necesaria in iss,
           f"La carpeta elegida se valida ({necesaria})",
           "elegir un disco que no existe, sin espacio, de red o sin permiso "
           "tiene que avisar en el momento, no fallar a mitad de instalación")

    # --- Qué NO le llega al cliente ---------------------------------------
    # El panel del dueño, el modelo financiero y el kit de contenido son del
    # Licenciante. Viajaban en cada instalador y en cada demo descargada:
    # compilarlos con Cython no evitaba que se distribuyeran. Se controla en
    # los dos lugares que arman el paquete, porque cualquiera de los dos
    # alcanza para que se cuelen.
    spec = _leer(SPEC)
    bat = _leer(os.path.join(RAIZ, "packaging", "armar_paquete_bat.py"))

    # Se llama a la regla de verdad en vez de buscar el nombre del archivo como
    # texto en el .spec. El control textual daba verde mientras el nombre
    # apareciera en algún lado —da igual en qué contexto— y daba rojo apenas la
    # regla se movió a una función compartida, que es justo la mejora que hacía
    # falta. Preguntándole a `fuera_del_producto` se comprueba lo que de verdad
    # importa: que ESA ruta no viaje.
    fuera = _regla_del_producto()
    for ruta, donde in (("app/owner.py", "el panel del dueño"),
                        ("plania/owner.py", "los números del panel del dueño"),
                        ("plania/negocio.py", "el modelo financiero"),
                        ("plania/contenido.py", "el kit de contenido"),
                        ("docs/MODELO_COMERCIAL.md", "la documentación interna"),
                        ("assets/capturas/owner_negocio.png",
                         "las capturas del panel del dueño"),
                        ("data/uso_licencias.db",
                         "la base de licencias del backend de venta"),
                        ("data/auditoria.log", "el log de la máquina de build")):
        ok(fuera(ruta), f"El producto no lleva {donde}",
           f"packaging/proteger_codigo.py deja pasar {ruta}, así que viaja en "
           "el .exe y en el ZIP del .bat")

    # Y que las dos vías de entrega usen ESA regla y no una copia propia: la
    # copia es lo que dejó al ZIP del .bat mandando el panel del dueño en texto
    # plano mientras el .exe sí lo sacaba.
    for archivo, contenido in (("plania.spec", spec), ("armar_paquete_bat.py", bat)):
        ok("fuera_del_producto" in contenido,
           f"{archivo} usa la regla compartida de qué no viaja",
           "si vuelve a tener su propia lista, las dos vías de entrega van a "
           "divergir de nuevo")

    # El producto es un solo build. Si el .spec vuelve a mirar una variable de
    # edición, vuelve a existir un Plania del dueño distinto del que se vende:
    # el dueño dejaría de probar lo que reciben sus clientes.
    ok("PLANIA_EDICION" not in spec and "PLANIA_EDICION" not in _leer(
           os.path.join(RAIZ, "packaging", "build_release.py")),
       "El producto se arma una sola vez, sin ediciones",
       "con ediciones, el dueño corre un programa distinto del que descarga "
       "quien le compra, y los problemas que le reportan no le pasan a él")
    owner_spec = _leer(os.path.join(RAIZ, "packaging", "plania_owner.spec"))
    ok("entrada_owner.py" in owner_spec and "Plania Owner" in owner_spec,
       "El panel del dueño se arma como programa aparte",
       "sin un .spec propio, el panel del negocio o viaja adentro del producto "
       "o directamente no se puede armar")

    # --- Elegir qué se instala --------------------------------------------
    # Se cuentan declaraciones reales, no renglones de la sección: una línea
    # sin `Name:` no declara nada, y contar renglones daba por bueno un
    # [Components] lleno de basura.
    tipos = [t for t in _seccion(iss, "Types") if re.match(r'\s*Name:', t)]
    componentes = [c for c in _seccion(iss, "Components") if re.match(r'\s*Name:', c)]
    ok(len(tipos) >= 2,
       "El usuario elige qué tipo de instalación quiere",
       "sin [Types] el instalador vuelca todo sin preguntar")
    ok(any("iscustom" in t.lower() for t in tipos),
       "Hay una instalación personalizada",
       "sin un tipo con el flag iscustom, elegir componentes sueltos no "
       "habilita nada: Inno Setup vuelve al tipo anterior en cuanto se toca "
       "una casilla")
    ok(len(componentes) >= 2,
       "Hay componentes que se pueden sacar",
       "sin [Components] la instalación mínima instalaría lo mismo que la "
       "completa")
    ok(any("fixed" in c.lower() for c in componentes),
       "El programa principal no se puede desmarcar",
       "si se puede sacar el programa, existe una instalación que no instala "
       "nada y falla al abrirse")
    archivos_iss = _seccion(iss, "Files")
    ok(all("Components:" in f for f in archivos_iss),
       "Cada archivo declara a qué componente pertenece",
       "un [Files] sin Components: se instala siempre, aunque el usuario "
       "haya desmarcado su componente — la elección quedaría de adorno")
    componentes_declarados = set()
    for c in componentes:
        m = re.search(r'Name:\s*"([^"]+)"', c)
        if m:
            componentes_declarados.add(m.group(1))
    usados = set()
    for f in archivos_iss:
        m = re.search(r"Components:\s*([\w ]+)", f)
        if m:
            usados.update(m.group(1).split())
    ok(usados <= componentes_declarados,
       "Los archivos no apuntan a componentes que no existen",
       f"declarados: {sorted(componentes_declarados)}; usados: {sorted(usados)} "
       "— un componente mal escrito hace que esos archivos no se instalen nunca")

    # --- Desinstalación ----------------------------------------------------
    ok("CurUninstallStepChanged" in iss,
       "Al desinstalar se pregunta qué hacer con los datos",
       "quien desinstala para irse no tiene forma de pedir que se borren sus "
       "datos, y quedan en el disco sin avisarle")
    ok("DelTree" in iss and "IDNO" in iss,
       "Se pueden borrar los datos si el usuario lo pide",
       "preguntar y no actuar sobre la respuesta es peor que no preguntar")

    # --- Accesos directos --------------------------------------------------
    iconos = _seccion(iss, "Icons")
    ok(any("{autodesktop}" in i for i in iconos),
       "Crea el ícono del escritorio",
       "falta una entrada {autodesktop} en [Icons]")
    ok(any("{group}" in i and "uninstallexe" not in i for i in iconos),
       "Crea la entrada en el menú Inicio",
       "falta una entrada {group} en [Icons]")
    ok(any("uninstallexe" in i for i in iconos),
       "Ofrece desinstalar desde el menú Inicio",
       "falta el acceso directo al desinstalador")
    ok(all("WorkingDir:" in i for i in iconos if "uninstallexe" not in i),
       "Los accesos directos fijan su carpeta de trabajo",
       "sin WorkingDir el programa arranca en la carpeta desde donde se hizo "
       "clic y puede no encontrar sus recursos")
    ok(any("desktopicon" in t for t in _seccion(iss, "Tasks")),
       "El ícono del escritorio es opcional para el usuario",
       "falta la tarea 'desktopicon' en [Tasks]")

    # --- Coherencia con lo que se empaqueta --------------------------------
    exe = re.search(r'#define\s+AppExe\s+"([^"]+)"', iss)
    ok(exe is not None, "El instalador declara qué ejecutable instala", "falta #define AppExe")
    if exe:
        nombre = exe.group(1).replace(".exe", "")
        spec = _leer(SPEC)
        ok(f'name="{nombre}"' in spec or f"name='{nombre}'" in spec,
           f"El ejecutable del instalador ({exe.group(1)}) es el que compila PyInstaller",
           f"packaging/plania.spec no genera '{nombre}': el instalador crearía "
           "accesos directos a un archivo que no existe")

    origen = [i for i in _seccion(iss, "Files") if "Source:" in i]
    ok(bool(origen), "El instalador copia archivos", "la sección [Files] está vacía")
    for linea in origen:
        m = re.search(r'Source:\s*"([^"]+)"', linea)
        if not m:
            continue
        ruta = m.group(1).replace("\\", "/").replace("*", "")
        carpeta = os.path.normpath(os.path.join(RAIZ, "packaging", ruta))
        # dist/ lo genera el build; solo se avisa si la ruta no es la esperada
        ok(ruta.startswith("../dist/"),
           "Lo que se instala sale del build, no de una ruta suelta",
           f"Source apunta a {ruta}, que no viene de dist/")

    # --- Íconos que tienen que existir en el repo --------------------------
    for clave, para in (("setupiconfile", "el ícono del instalador"),
                        ("wizardimagefile", "el panel del asistente"),
                        ("wizardsmallimagefile", "el logo chico del asistente")):
        valor = d.get(clave, "")
        if valor:
            ruta = os.path.normpath(os.path.join(RAIZ, "packaging",
                                                 valor.replace("\\", "/")))
            ok(os.path.exists(ruta), f"Existe {para}", f"falta {valor}")

    # --- Instalador de Electron -------------------------------------------
    pkg = json.loads(_leer(PKG_ELECTRON))
    nsis = pkg.get("build", {}).get("nsis", {})
    ok(nsis.get("oneClick") is False,
       "El instalador Electron no es de un solo clic",
       "con oneClick el usuario no puede elegir carpeta")
    ok(nsis.get("allowToChangeInstallationDirectory") is True,
       "El instalador Electron deja elegir la carpeta",
       "allowToChangeInstallationDirectory tiene que estar en true")
    ok(nsis.get("createDesktopShortcut") is not False,
       "El instalador Electron crea el ícono del escritorio", "")
    ok(nsis.get("createStartMenuShortcut") is not False,
       "El instalador Electron crea la entrada del menú Inicio", "")
    icono = pkg.get("build", {}).get("win", {}).get("icon", "")
    if icono:
        ruta = os.path.normpath(os.path.join(RAIZ, "desktop", icono))
        ok(os.path.exists(ruta), "Existe el ícono del instalador Electron",
           f"falta {icono}")

    # --- Sintaxis del script del instalador --------------------------------
    r.extend(controles_pascal(iss))

    # --- Puertos -----------------------------------------------------------
    lanzador = _leer(os.path.join(RAIZ, "packaging", "plania_launcher.py"))
    main_js = _leer(os.path.join(RAIZ, "desktop", "main.js"))
    ok("PLANIA_PUERTO_ARCHIVO" in lanzador and "PLANIA_PUERTO_ARCHIVO" in main_js,
       "El puerto real se le informa a quien lanzó el programa",
       "sin ese aviso, si el puerto elegido se ocupa el lanzador se muda y la "
       "ventana queda esperando en el puerto viejo para siempre")
    # Sólo líneas ejecutables: el 8501 se nombra a propósito en un comentario
    # que explica por qué NO se usa, y eso no es un defecto.
    codigo = [l for l in lanzador.splitlines() if not l.strip().startswith("#")]
    ok(not any("8501" in l for l in codigo),
       "No se usa el puerto por defecto de Streamlit",
       "el 8501 lo ocupa cualquier otra aplicación Streamlit del usuario")
    ok("_puerto_libre" in lanzador and "_reservar" in lanzador,
       "El puerto se toma de verdad antes de anunciarlo",
       "comprobar que un puerto está libre y recién después dejarlo tomar deja "
       "una ventana en la que otro programa se lo lleva")

    # --- La ventana dibuja su propia interfaz -----------------------------
    # El escritorio dejó de embeber la pantalla Streamlit: tiene interfaz React
    # propia y le pide los datos a la API local. Estas piezas tienen que estar
    # las tres o la ventana arranca y se queda en la pantalla de carga.
    ui = os.path.join(RAIZ, "desktop", "renderer", "ui")
    for archivo in ("index.html", "base.js", "pantallas.js", "app.js", "estilo.css"):
        ok(os.path.exists(os.path.join(ui, archivo)),
           f"Existe la interfaz de escritorio: {archivo}",
           f"falta desktop/renderer/ui/{archivo}")

    ok("PLANIA_MOTOR" in main_js and "PLANIA_MOTOR" in lanzador,
       "La ventana le pide al motor la API, no la pantalla Streamlit",
       "sin ese acuerdo el motor sirve Streamlit y la interfaz React no "
       "encuentra a quién pedirle los datos")
    ok('renderer", "ui", "index.html"' in main_js,
       "La ventana carga su propia interfaz desde el disco",
       "si vuelve a cargar la URL del servidor, se ve Streamlit otra vez")
    # El puerto tiene que llegar por la query: inyectarlo con executeJavaScript
    # obliga a recargar, y la recarga crea un contexto nuevo que borra
    # justamente lo inyectado.
    ok("query: { api: url }" in main_js,
       "El puerto de la API le llega a la interfaz al arrancar",
       "sin esto la interfaz pide siempre al puerto por defecto")

    spec_txt = _leer(SPEC)
    for modulo in ("plania.api", "uvicorn"):
        ok(f'"{modulo}"' in spec_txt,
           f"El ejecutable empaqueta {modulo}",
           f"el lanzador importa {modulo} dentro de una función y PyInstaller "
           "no lo ve solo: el .exe se arma y la ventana no encuentra el motor")

    paquete = os.path.join(RAIZ, "desktop", "package.json")
    if os.path.exists(paquete):
        import json as _json
        pkg = _json.load(open(paquete, encoding="utf-8"))
        archivos = " ".join(pkg.get("build", {}).get("files", []))
        for dep in ("react", "plotly.js-dist-min"):
            ok(dep in pkg.get("dependencies", {}),
               f"{dep} está declarado como dependencia",
               f"sin declararlo, npm ci no lo instala y la interfaz no carga")
            ok(dep in archivos,
               f"electron-builder empaqueta {dep}",
               f"sin esto el instalador se arma igual y la ventana levanta sin "
               f"{dep}: falla que sólo se ve en la máquina del cliente")

    # --- Que parezca un programa y no una página de Streamlit --------------
    # Lo que se vende es un programa instalado. El andamiaje de Streamlit —el
    # menú de hamburguesa con "Rerun" y el enlace a streamlit.io, el botón
    # Deploy, el "Running...", el pie "Made with Streamlit"— delata con qué
    # está hecho y no tiene ninguna función para quien lo compró.
    apariencia = _leer(os.path.join(RAIZ, "plania", "apariencia.py"))
    # Se busca el selector completo con las comillas y no el id suelto: sin
    # las comillas, "stToolbar" lo daba por presente el selector de al lado
    # (stToolbarActions), y el control pasaba aunque la barra del botón
    # Deploy hubiera quedado a la vista.
    for testid, que in (("stToolbar", "la barra con el botón Deploy"),
                        ("stStatusWidget", "el cartelito 'Running...'"),
                        ("stMainMenu", "el menú de hamburguesa"),
                        ("stDecoration", "la barra de colores de arriba")):
        selector = f'[data-testid="{testid}"]'
        ok(selector in apariencia, f"La ventana no muestra {que}",
           f"falta ocultar {selector} en plania/apariencia.py")
    ok("footer" in apariencia,
       "La ventana no muestra el pie 'Made with Streamlit'",
       "falta ocultar footer en plania/apariencia.py")
    for pantalla in ("app.py", "owner.py"):
        cuerpo = _leer(os.path.join(RAIZ, "app", pantalla))
        ok("apariencia.css_programa()" in cuerpo,
           f"app/{pantalla} usa la apariencia de programa",
           "cada pantalla que se olvide de aplicarla vuelve a mostrar el "
           "andamiaje de Streamlit")
        ok("fonts.googleapis.com" not in cuerpo,
           f"app/{pantalla} no depende de internet para su tipografía",
           "un programa instalado tiene que verse igual sin red; además una "
           "llamada a un servidor externo en cada arranque la puede bloquear "
           "el área de sistemas del cliente")

    # --- Todo en el disco que el usuario elige ------------------------------
    config_py = _leer(os.path.join(RAIZ, "plania", "config.py"))
    ok('"frozen"' in config_py and "_carpeta_junto_al_exe" in config_py,
       "La licencia y la configuración quedan en el disco elegido al instalar",
       "sin esto, plania.config vuelve a guardar siempre en ~/.plania (el "
       "perfil de Windows, típicamente C:) sin importar dónde se instaló")
    ok("_migrar_si_hace_falta" in config_py,
       "Quien actualiza desde una versión anterior no pierde su licencia",
       "falta la migración única de ~/.plania a la carpeta junto al .exe")
    ok('"frozen"' in lanzador and "datos" in lanzador,
       "Los logs también quedan en el disco elegido al instalar",
       "el lanzador tiene que intentar 'datos/logs' junto al .exe antes de "
       "caer a LOCALAPPDATA")
    sin_comentarios = "\n".join(
        l for l in "\n".join(_seccion(iss, "UninstallDelete")).splitlines()
        if not l.strip().startswith(";"))
    ok(r"{app}\datos" not in sin_comentarios,
       "Desinstalar no borra la carpeta donde vive la licencia",
       r"si [UninstallDelete] borra {app}\datos, reinstalar pide activar de nuevo")

    return r


def main() -> int:
    resultados = controles()
    fallan = [x for x in resultados if not x[0]]
    for pasa, titulo, detalle in resultados:
        print(f"  [{'OK' if pasa else '!!'}] {titulo}")
        if not pasa and detalle:
            print(f"         {detalle}")
    print(f"\n  {len(resultados) - len(fallan)} de {len(resultados)} controles en verde")
    if fallan:
        print("  El instalador NO está listo para publicar.")
        return 1
    print("  El instalador está coherente con lo que se empaqueta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
