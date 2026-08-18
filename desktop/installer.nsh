# © 2026 Martín Viera. Todos los derechos reservados.
#
# Plania · Ajustes propios del instalador de Windows (NSIS / electron-builder)
# ===========================================================================
# electron-builder toma este archivo solo: busca "installer.nsh" en la carpeta
# de recursos de build (desktop/build/) y lo inserta en su plantilla. No se
# declara en package.json. Moverlo o renombrarlo lo desactiva EN SILENCIO —el
# instalador se arma igual, sin esto adentro— y por eso
# packaging/verificar_instalador.py comprueba que siga en su lugar.
#
# Qué resuelve
# ------------
# El instalador proponía siempre una carpeta del disco del sistema
# (C:\Program Files\Plania). En una PC con el disco C lleno la instalación
# arranca igual y muere a mitad de la copia, o entra raspando y después Plania
# no tiene lugar para sus datos. Elegir otro disco siempre se pudo —la página
# para cambiar la carpeta está—, pero había que darse cuenta solo.
#
# Acá se propone por defecto el disco fijo con más lugar libre. Sigue siendo
# una PROPUESTA: la página para elegir carpeta se muestra igual
# (allowToChangeInstallationDirectory en package.json), así que quien quiera
# C: lo escribe y listo.

!include "FileFunc.nsh"
!include "LogicLib.nsh"

# Lo que ocupa Plania instalado. El motor lleva Python, pandas y pyarrow
# adentro, así que no es una aplicación chica: es el mismo número que usa
# packaging/instalador.iss para el instalador liviano.
!define PLANIA_MB_NECESARIOS 900

Var PlaniaDisco
Var PlaniaLibre
Var PlaniaLibreDelDisco

# Se llama una vez por disco fijo. ${GetDrives} "HDD" ya filtra: no llegan
# pendrives, unidades de red ni lectoras, que son justo las que instalan bien
# y hacen que Plania deje de abrir el día que no están conectadas.
Function PlaniaMirarDisco
  # $9 = raíz de la unidad, con la barra: "D:\"
  ${DriveSpace} "$9" "/D=F /S=M" $PlaniaLibreDelDisco
  ${If} $PlaniaLibreDelDisco != ""
  ${AndIf} $PlaniaLibreDelDisco >= ${PLANIA_MB_NECESARIOS}
  ${AndIf} $PlaniaLibreDelDisco > $PlaniaLibre
    StrCpy $PlaniaLibre $PlaniaLibreDelDisco
    StrCpy $PlaniaDisco "$9"
  ${EndIf}
  # Se empuja algo distinto de "StopGetDrives" para seguir recorriendo.
  Push "seguir"
FunctionEnd

!macro customInit
  # Este macro se inserta dentro de .onInit, justo DESPUÉS de initMultiUser,
  # así que $INSTDIR ya trae el valor definitivo de electron-builder y nada lo
  # vuelve a tocar después. Eso vale porque perMachine está en true: sin eso
  # queda en el medio la página de "¿para quién instalar?", que fija $INSTDIR
  # de nuevo cuando el usuario elige y pisaría lo que decidamos acá.

  # Si Plania ya está instalado, se respeta la carpeta que eligió el usuario la
  # vez anterior: mudarla sola en una actualización dejaría dos copias y la
  # licencia activada en la vieja.
  ReadRegStr $R0 SHCTX "${INSTALL_REGISTRY_KEY}" "InstallLocation"
  ${If} $R0 == ""
    StrCpy $PlaniaDisco ""
    StrCpy $PlaniaLibre 0
    ${GetDrives} "HDD" "PlaniaMirarDisco"

    ${If} $PlaniaDisco == ""
      # Ningún disco fijo tiene lugar. Se avisa ahora, con el número concreto,
      # en vez de dejar que la copia muera por la mitad sin decir por qué.
      MessageBox MB_OK|MB_ICONEXCLAMATION "Plania necesita al menos ${PLANIA_MB_NECESARIOS} MB libres y ningún disco de esta computadora los tiene.$\r$\n$\r$\nLiberá espacio y volvé a abrir el instalador."
    ${Else}
      # Si el disco con más lugar es el del sistema, se deja la propuesta de
      # electron-builder (C:\Program Files\Plania), que es donde corresponde.
      ${GetRoot} "$INSTDIR" $R1
      ${If} "$R1\" != "$PlaniaDisco"
        StrCpy $INSTDIR "$PlaniaDisco${APP_FILENAME}"
      ${EndIf}
    ${EndIf}
  ${EndIf}
!macroend
