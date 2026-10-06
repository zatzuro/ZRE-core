# Instalar TEST 2.6.5.1 en la instalación existente de Windows

En PowerShell, ejecuta:

```powershell
$installer = Join-Path $env:TEMP 'zre-install-test.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/zatzuro/ZRE-core/develop/2.6.5.1/install_test_build.ps1' -OutFile $installer -UseBasicParsing
powershell -NoProfile -ExecutionPolicy Bypass -File $installer
```

Si ZRE sigue abierto, el instalador se detiene antes de modificar archivos, muestra PID, ejecutable, comando y root detectado, y recuerda la instalación identificada. Cierra el puente indicado y vuelve a ejecutar el mismo comando. No cierres solamente la pestaña del navegador: el proceso Python debe liberar 8765. No se detiene ningún proceso ajeno automáticamente.

Con ZRE cerrado, utiliza la instalación recordada o identifica una única instalación existente. Si hay varias candidatas, se detiene sin elegir arbitrariamente ni modificar archivos.

El instalador conserva el entorno Python y los datos, descarga un commit exacto de develop/2.6.5.1 y registra TEST. Arranca el mismo start_dashboard.bat y verifica /version y el dueño del puerto. Debe finalizar mostrando:

```text
TEST BUILD ACTIVE
ZRE Core 2.6.5.1
commit: <40 caracteres>
root: <instalación identificada>
runtime verified: 2.6.5.1
```

La interfaz muestra la versión del runtime y el commit recibidos por el WebSocket existente. /version expone installedVersion, runtimeVersion, mode, channel, sourceRef, sourceCommit, root, pid, executable, instanceId y assetsVerified. TEST permanece activo al cerrar y ejecutar otra vez el mismo launcher; no consulta main ni actualiza en segundo plano.

Para regresar al estable, cierra ZRE y ejecuta restore_stable.bat de la instalación identificada. Es la entrada Restore Stable: reinstala main, conserva datos y entorno, registra STABLE y vuelve a habilitar las actualizaciones normales. No basta con borrar el indicador TEST manualmente.

La validación Windows del repositorio prueba una carpeta con espacios, dos arranques del mismo BAT, 125 segundos de updater real, procedencia de assets, procesos/puerto y restauración. No sustituye la verificación del runtime en tu PC, que realiza el instalador al finalizar.
