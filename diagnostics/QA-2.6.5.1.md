# ZRE Core 2.6.5.1 — build de prueba

Handoff: 0aad05192fd6cf54b0efb8171d13f9a5b0053c1d. Canal development conservado; main y release estable intactos.

## Ruta de instalación
Cerrar el puente ZRE. Ejecutar install_test_build.ps1 y seleccionar el start_dashboard.bat existente. El wrapper utiliza su .venv, descarga el updater de GitHub y lo ejecuta con --test-ref develop/2.6.5.1 y --root. No crea otra instalación ni instala dependencias externas de actualización.

El updater resuelve una sola vez el SHA de la rama; manifiesto y archivo ZIP pertenecen a ese mismo SHA. La solicitud es puntual, sin configuración persistente de development. El arranque posterior consulta main como siempre y no hace downgrade. Una futura versión estable superior se instala normalmente. --restore-stable permite el regreso solicitado explícitamente.

Se conservan .venv, data, session_logs, reports y archivos locales no reemplazados por el paquete. Las preferencias visuales v2 usan su propia clave con lectura de las v1; no sobrescriben las preferencias del estable. La sustitución de código tiene rollback si falla la copia y escribe version.json al final.

## Correcciones del editor
Coordenadas enteras normalizadas; nombre desde Ajustes de pantalla sincronizado correctamente; pointercancel cancela la captura de movimiento; no anunciar guardado exitoso si localStorage falla. Se conserva el constructor entregado.

## QA
230 pruebas Python. Regresiones frontend incluidas parrilla/mover/redimensionar/guardar/plegado y ajustes de nombre con fixture DOM. Smoke de servidor real /version, assets y WebSocket.

## Límites
No acceso al PC Windows del usuario ni a iRacing. No afirmar instalación realizada en ese PC. Chromium no disponible en este entorno: pruebas de navegador visual y en pista pendientes. Debe ejecutar el instalador y verificar localhost:8765/version y el marcador v2.6.5.1.
