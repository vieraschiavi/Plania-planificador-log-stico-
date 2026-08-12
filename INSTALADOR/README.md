# INSTALADOR

Acá quedan los `sha256` de cada compilación (`CHECKSUMS.txt`). **Los archivos
en sí están en la [página de Releases](../../releases)**, que es de donde se
bajan. Todo lo deja la corrida del workflow **Release** — nadie sube nada a
mano.

| Archivo (en Releases) | Qué es |
|---|---|
| `Plania Setup *.exe` | Instalador de Windows con ventana propia (Electron + React). Deja ícono en el escritorio, entrada en el menú Inicio y desinstalador. |
| `Plania *.exe` | El mismo programa sin instalar. |
| `Plania_Setup_v*.exe` | Instalador liviano, sin Electron: abre en el navegador. También deja accesos directos y desinstalador. |
| `Plania_portable.zip` | Igual que el anterior pero sin instalar. |
| `Plania_BAT.zip` | Código + `INICIAR_PLANIA.bat`. Requiere Python instalado. |

Hay dos clases de entrada en Releases:

- **`ultima-compilacion`** — se rehace sola con cada cambio del producto y se
  pisa a sí misma. Sirve para probar; cambia sin aviso.
- **`v1.0.1`, `v1.0.2`…** — versiones cortadas a mano, con changelog. Son las
  que se le pasan a un cliente.

## Por qué los binarios no están en esta carpeta

Porque GitHub no los deja. Se intentó, y el push terminó así:

```
remote: error: File INSTALADOR/Plania_portable.zip is 138.79 MB;
       this exceeds GitHub's file size limit of 100.00 MB
! [remote rejected] HEAD -> main (pre-receive hook declined)
```

El portable pesa 138 MB y el Setup 99.7 — el segundo pasaba raspando y se iba
a romper solo en cuanto creciera un poco. Y aun si entraran, cada versión
sumaría ~240 MB al historial de git **para siempre**: clonar el repositorio se
iría poniendo más lento con cada release, sin forma de deshacerlo.

En Releases el límite es 2 GB por archivo y no toca el historial. El
`CHECKSUMS.txt` de acá sirve para lo mismo que servía tener el archivo: poder
verificar que lo que bajaste es lo que se compiló.

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

Ningún cliente entra acá. Este repositorio es tu código fuente, no tu tienda.
El instalador se toma de acá y se sube a donde el cliente sí llega:

1. **`plania.uy`** — el botón de descarga de la web pública.
2. **El link post-pago** — `backend_venta` sirve el instalador en
   `/descargar/{token}` cuando alguien termina de pagar. La ruta se configura
   con `PLANIA_INSTALADOR_PATH`; apuntala al archivo que publicaste.

> **El repositorio hoy es PÚBLICO.** Conviene saber qué implica, porque varias
> decisiones de este proyecto se tomaron dando por hecho lo contrario.
>
> Todo lo que `packaging/proteger_codigo.py` saca del instalador para que un
> cliente no lo lea —`plania/negocio.py` con los costos y márgenes,
> `plania/owner.py` y `app/owner.py`, `plania/contenido.py`, `docs/` con el
> modelo comercial— está igual acá, en texto plano, para cualquiera. Lo mismo
> el motor entero (`plania/`), que se compila con Cython justamente para que
> no viaje legible, y `backend_venta/` completo.
>
> Lo que la protección del build sigue logrando, aun así, es que nada de eso
> viaje **dentro del producto instalado**: quien baja el `.exe` no lo obtiene.
> Lo que ya no logra es que no lo obtenga quien abre github.com.
>
> Ser público tiene contrapartida real —minutos de Actions gratis e ilimitados
> y el plan gratuito de Vercel—, así que puede ser lo que querés. Es una
> decisión, no un descuido, y conviene tomarla a propósito.

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

Cada push automático rehace la entrada `ultima-compilacion` y actualiza
`CHECKSUMS.txt` acá. Nada se acumula ni engorda el repositorio.

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
