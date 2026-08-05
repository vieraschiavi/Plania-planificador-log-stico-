# Descargas de Plania

Acá quedan los instaladores listos para entregar. Los deja la corrida del
workflow **Release** — nadie los sube a mano — y arriba de cada uno queda su
`sha256`, para que quien descargue pueda comprobar que el archivo que le
llegó es el que salió de acá.

| Archivo | Qué es | Para quién |
|---|---|---|
| `Plania_Setup.exe` | Instalador de Windows. Trae Python adentro: el cliente no instala nada más. | Compradores y demo de 7 días |
| `Plania_portable.zip` | El mismo programa sin instalar. Se descomprime y se ejecuta. | Máquinas sin permisos de administrador |
| `Plania_BAT.zip` | Código fuente + `INICIAR_PLANIA.bat`. Requiere Python instalado. | Quien prefiera correrlo desde el código |
| `CHECKSUMS.txt` | `sha256` de cada archivo de arriba. | Verificar la descarga |

## El programa es uno solo

`Plania_Setup.exe` es **el mismo archivo** que usa el dueño del producto y que
descarga cualquiera que lo compre. No hay una versión especial para adentro.

Eso no es un detalle de organización: si el dueño corriera una versión propia,
estaría probando un programa que ningún cliente tiene, y un problema reportado
por un cliente podría no reproducírsele nunca.

El panel del negocio —facturación, clientes, modelo financiero, kit de
contenido— es un **programa aparte**, `Plania Owner`, que se arma con
`python packaging/build_release.py --con-owner` y se instala solo en la máquina
del dueño. No se publica acá ni se sube a ningún lado: lleva adentro cómo se
gana plata con esto.

## Cómo se llena esta carpeta

Pestaña **Actions → Release → Run workflow**. La corrida compila en Windows
—PyInstaller, Inno Setup y electron-builder solo funcionan ahí—, escribe los
archivos en esta carpeta con sus checksums y los adjunta además a la página de
*Releases*.

Los binarios se **reemplazan**, no se acumulan: cada versión pisa a la
anterior, así la carpeta tiene siempre una sola copia de cada cosa.

Conviene saber el costo, porque no es gratis: aunque el archivo se reemplace,
cada versión que pasó por acá queda guardada en el historial de git para
siempre. Un instalador pesa cientos de megabytes, así que clonar el
repositorio se va poniendo más lento con cada release, y no hay forma de
achicarlo sin reescribir el historial.

Por eso los mismos archivos se publican además en la página de *Releases*,
que es donde GitHub guarda binarios sin que engorden el repositorio. Si en
algún momento clonar se vuelve molesto, la salida es dejar acá solo los
checksums y los enlaces, y bajar los archivos desde ahí.

## Si la corrida no arranca

Si al lanzar el workflow los trabajos quedan en cola y mueren sin log, no es un
problema del código: es que la cuenta no tiene runners de GitHub Actions
habilitados para este repositorio. Se revisa en **Settings → Actions** y en
**Billing → Spending limits**. Mientras tanto, el build se puede hacer en
cualquier máquina Windows con Python 3.11:

```powershell
pip install -r requirements.txt pyinstaller
python packaging\build_release.py
```

y copiar lo que quede en `dist\` a esta carpeta.
