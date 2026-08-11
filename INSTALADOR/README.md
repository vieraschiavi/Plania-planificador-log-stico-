# INSTALADOR

Acá queda el instalador de Plania listo para publicar, con su `sha256`. Lo
deja la corrida del workflow **Release** — nadie lo sube a mano.

| Archivo | Qué es |
|---|---|
| `Plania_Setup.exe` | Instalador de Windows. Trae Python adentro: el cliente no instala nada más. |
| `Plania_portable.zip` | El mismo programa sin instalar. Para máquinas sin permisos de administrador. |
| `Plania_BAT.zip` | Código + `INICIAR_PLANIA.bat`. Requiere Python instalado. |
| `CHECKSUMS.txt` | `sha256` de cada archivo, para verificar la descarga. |

## Las dos vías, y por qué hacen falta las dos

Es el mismo producto entregado de dos maneras, y ninguna reemplaza a la otra:

| | **EXE** | **BAT** |
|---|---|---|
| Qué abre | ventana propia (Electron + React) | el navegador (Streamlit) |
| Instala | ícono en escritorio, menú Inicio, desinstalador | nada: descomprimir y doble clic |
| Requisitos | ninguno | Python 3.11+ |
| Código de negocio | compilado con Cython | a la vista |
| Para quién | el caso normal | la empresa donde IT no deja ejecutar un `.exe` bajado de internet |

La segunda no es un plan B pobre: es la que salva la venta cuando el cliente
quiere el producto y su política de seguridad no lo deja abrir un ejecutable.
Un `.bat` que llama al Python que la empresa ya aprobó, casi siempre sí pasa.

Las dos salen del mismo build (`packaging/build_release.py`) y las dos
excluyen exactamente lo mismo — el panel del dueño, el servidor de venta, la
documentación interna. Esa lista vive en un solo lugar
(`packaging/proteger_codigo.py`, `fuera_del_producto`) porque cuando estaba
duplicada divergió: el `.exe` sacaba los módulos del dueño y el ZIP del `.bat`
los mandaba en texto plano.

## Esta carpeta NO es el canal de descarga del cliente

Ningún cliente entra acá. Este repositorio es privado y es tu código fuente,
no tu tienda. El instalador se toma de acá y se sube a donde el cliente sí
llega:

1. **`plania.uy`** — el botón de descarga de la web pública.
2. **El link post-pago** — `backend_venta` sirve el instalador en
   `/descargar/{token}` cuando alguien termina de pagar. La ruta se configura
   con `PLANIA_INSTALADOR_PATH`; apuntala al archivo que publicaste.

Que el cliente no descargue de GitHub no es una formalidad: si el repositorio
fuera público para que pudieran, el mismo ZIP les daría el código fuente
completo y cualquier binario que esté acá adentro.

## No hay dos instaladores: demo y versión paga son el mismo archivo

`Plania_Setup.exe` arranca solo con **7 días con todas las funciones**, sin
tarjeta. Cuando el cliente paga, recibe una licencia y la pega en *Planes y
licencia* — el mismo programa que ya tenía instalado se desbloquea.

No hay que construir ni publicar una "versión oficial" aparte. Tener dos
binarios significaría que la demo que probó el prospecto no es exactamente lo
que compró, y que cada arreglo hay que hacerlo dos veces.

## El panel del dueño no está acá, y no puede estar

`Plania Owner` —facturación, clientes, modelo financiero, kit de contenido—
se arma aparte y **nunca entra a este repositorio**:

```powershell
python packaging\build_release.py --con-owner
```

Eso deja `dist\Plania_Owner.zip` (ejecutable) y `dist\Plania_Owner_BAT.zip`
(código + `INICIAR_PLANIA_OWNER.bat`) — las mismas dos vías que el producto,
por la misma razón: si estás en una PC donde no podés abrir un `.exe`, el
panel también tiene que abrir. El `.bat` **pide el token al arrancar**, no lo
lleva escrito: un archivo con el token adentro es un token publicado en cuanto
se copia a otro lado.

Se quedan en tu máquina. El paso del workflow que llena esta carpeta corta con
error si detecta cualquier `Plania_Owner*` acá — porque un archivo en el repo
lo tiene cualquiera que tenga acceso al repo, hoy o el día que sumes a alguien.

Que sólo vos lo tengas no depende de una contraseña ni de que esté escondido:
depende de que sólo vos puedas compilarlo.

## Qué instala el `.exe`

- **Ícono en el escritorio** (opcional, tildado por defecto).
- **Entrada en el menú Inicio**, con su acceso para **desinstalar**.
- **Desinstalador** registrado en *Agregar o quitar programas* de Windows.
- Deja elegir la carpeta de instalación, y valida que la unidad exista, tenga
  espacio y sea escribible antes de copiar nada.
- Al desinstalar **pregunta qué hacer con tus datos** en vez de borrar la
  licencia y la configuración sin avisar.

Todo eso lo controla `packaging/verificar_instalador.py`, que corre en el
workflow **antes** de construir.

## Cómo se llena

Sola, con cada push a `main` que toca `app/`, `plania/`, `packaging/`,
`desktop/`, `data/`, `assets/`, `requirements.txt` o `INICIAR_PLANIA.bat`.
Un job barato en Linux revisa qué cambió antes de prender el de Windows.

Publicar una versión con changelog en *Releases* es aparte: pusheá un tag
(`git tag v1.0.1 && git push --tags`) o usá **Actions → Release → Run
workflow**.

Los binarios se **reemplazan**, no se acumulan. Aun así, cada versión que
pasó por acá queda en el historial de git para siempre y un instalador pesa
cientos de megabytes: clonar el repositorio se va poniendo más lento con cada
release. Si molesta, la salida es dejar acá sólo los checksums y bajar los
archivos desde *Releases*.

## Si la carpeta está vacía

Ya pasó por dos motivos distintos, y conviene distinguirlos antes de tocar
nada:

1. **La corrida murió en segundos, sin logs** (`runner_id 0`): GitHub no
   asignó runner. Se revisa en **Settings → Actions** y en **Billing →
   Spending limits** — es un repositorio privado y los minutos se cobran.
2. **La corrida duró minutos y falló en un paso**: es un problema del build,
   no de la cuenta. Abrí el job y leé el paso rojo. La primera vez que pasó
   fue una línea de `packaging/instalador.iss` que empezaba con `#13#10`: el
   preprocesador de Inno Setup lee el `#` inicial como directiva suya, abortó
   la compilación, y como ese paso corta el job entero tampoco se construyó el
   instalador de Electron. Ahora lo agarra
   `python packaging/verificar_instalador.py`, que corre antes y en Linux.

Mientras tanto se construye en cualquier Windows con Python 3.11:

```powershell
pip install -r requirements.txt pyinstaller cython
python packaging\build_release.py
```

y se copia lo que quede en `dist\` a esta carpeta.
