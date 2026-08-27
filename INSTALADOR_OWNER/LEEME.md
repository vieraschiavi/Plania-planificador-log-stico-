# INSTALADOR_OWNER — probar la VERSIÓN FULL

Deja esta PC con **exactamente lo mismo que recibe un cliente que paga el
plan más alto**. No es un modo especial ni una pantalla de más: es el mismo
`app/app.py` que se vende, con la licencia desbloqueada al máximo.

## Cómo se usa

**Windows** — doble clic en `ACTIVAR-OWNER.bat`.

**Linux / macOS**:

```bash
./INSTALADOR_OWNER/activar-owner.sh
```

La primera vez arma el entorno e instala dependencias (unos minutos, ~1 GB).
Después tarda segundos. Al terminar te ofrece abrir el programa.

Para ver cómo quedó, o volver atrás:

```bash
./INSTALADOR_OWNER/activar-owner.sh --estado
./INSTALADOR_OWNER/activar-owner.sh --desactivar
```

## Qué queda activado

Verificado corriendo el programa, no sólo leyendo el código — en *Planes y
licencia* dice `Plan owner · vence en 36499 días`:

| | Demo (lo que trae de fábrica) | **Después de activar** |
|---|---|---|
| Features | 4: copiloto, erp, exportes, rutas | **8**: las 4 + `excedente`, `white_label`, `sso`, `multi_sucursal` |
| Cupo mensual de consultas | 300 | **sin tope** |
| Vencimiento | 7 días | **100 años** |
| Plan | `trial` | **`owner`** |

Es el plan `owner` de `backend_venta/licencias.py`, que ya existía y es el
mismo que se emite con `packaging/generar_licencia_owner.py`. Acá no se
inventó ningún plan nuevo.

## Por qué esta carpeta no trae ningún `.exe` adentro

Es la diferencia con `Buscador-Inmobiliario`, donde el
`MV-PC-Instalador-OWNER.exe` sí está commiteado: **ese pesa 29 MB y los de
Plania pesan entre 99,7 y 190,8 MB**. GitHub rechaza cualquier archivo de más
de 100 MB, y ya lo rechazó una vez acá:

```
remote: error: File INSTALADOR/Plania_portable.zip is 138.79 MB;
       this exceeds GitHub's file size limit of 100.00 MB
```

Aun si entraran, cada versión sumaría ~240 MB **permanentes** al historial de
git. Por eso los instaladores viven en la
[página de Releases](../../releases) (límite 2 GB, no toca el historial) y
acá queda sólo lo que pesa kilobytes: el activador.

**No hace falta bajar nada igual.** El activador trabaja sobre el código de
este repositorio, que es el mismo programa que arma el instalador.

## Por qué tampoco trae la licencia adentro

En `Buscador-Inmobiliario` el sello (`MV-OWNER.lic`) está commiteado, y ahí
funciona porque **ese repositorio es privado**. Este es **público**.

Una licencia `owner` ya emitida es acceso total, gratis, para siempre, para
cualquiera que la copie — exactamente el agujero que se cerró cuando
`plania/licencia.py` dejó de aceptar tokens sin verificar la firma. Un
archivo así acá sería publicarlo.

Por eso el activador **emite la licencia en el momento, en tu máquina**. El
secreto de firma sale de `backend_venta/licencias.py::secreto_firma`, que se
genera solo la primera vez y queda en tu config (`~/.plania`); nunca viaja al
repositorio. Dos máquinas generan secretos distintos, así que el token que
sale acá **no le sirve a nadie más**.

> **Sobre el repositorio público.** Que el activador exista no agrega una
> puerta que antes no estuviera: `backend_venta/` completo y
> `packaging/generar_licencia_owner.py` ya están en texto plano acá, así que
> cualquiera que los lea puede hacer esto mismo a mano desde que el repo es
> público. Lo que este archivo agrega es comodidad, no acceso. Si eso
> molesta, lo que lo cierra es hacer el repositorio privado —
> no sacar esta carpeta.

## Cuánto dura, y por qué no son 100 años a secas

El token vence en 100 años, pero `plania/licencia.py` re-confirma la licencia
contra el backend cada 24 h, y sin backend escuchando la tolera 10 días antes
de soltarla (`_TOLERANCIA_SIN_RED_DIAS`). Entonces:

- **Sin hacer nada más**: anda **10 días**. Volvés a correr el activador y se
  renueva. Es un doble clic.
- **Para que no expire nunca**: dejá el backend local corriendo, y la
  re-confirmación de cada 24 h encuentra a quién preguntarle:

  ```bash
  ./run.sh backend
  ```

  No hay que configurar nada: `PLANIA_BACKEND_URL` sin configurar ya apunta a
  `http://localhost:8100`, que es donde levanta.

## Por qué no escribe la config directamente

Porque el programa no le cree a un token porque el token *diga* `plan=owner`:
le cree porque `activar_licencia()` se lo pregunta a quien lo firmó
(`GET /licencias/estado`) y guarda **las claims que devolvió el backend**.

Escribir la config a mano sería un atajo que ningún cliente recorre, y el día
que el circuito real se rompa acá seguiría "andando" — probando algo que no
es el producto. Así que se recorre el circuito completo, con una sola
diferencia: en vez de salir a internet se le habla al backend **dentro del
mismo proceso** (el `TestClient` que `activar_licencia()` acepta por
`cliente_http`, que está ahí justamente para esto). Sin servidor, sin puerto,
sin internet.

## También desbloquea el `.exe` instalado

La licencia se guarda en `~/.plania`, que es por usuario y no por instalación
(ver `plania/config.py`). Así que activar desde acá deja en versión full
**también** al programa instalado con el `.exe` en esa misma PC. No hay que
activarlo dos veces.

## Esto NO es el panel del dueño

Dos cosas distintas que conviene no mezclar:

| | **Esta carpeta** | **Panel del dueño** |
|---|---|---|
| Qué es | el producto que se vende, desbloqueado | otro programa: facturación, clientes, márgenes |
| Archivo | `app/app.py` | `app/owner.py`, `plania/negocio.py` |
| Cómo se arma | el activador de acá | `python packaging/build_release.py --con-owner` |
| Dónde vive | este repositorio (público) | repositorio privado aparte — ver `INSTALADOR/README.md` |

El panel del dueño no puede publicarse acá y hay dos guardas que lo impiden
(`release.yml` falla si aparece un `Plania Owner*`, y `release-owner.yml`
publica en otro repositorio), atadas por
`test_el_panel_del_dueno_no_se_publica_en_el_repo_publico`. Esta carpeta no
las toca.
