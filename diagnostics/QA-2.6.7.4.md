# ZRE CORE 2.6.7.4 — Auditoría de regresión integral y estabilización

Fecha: 2026-10-17. Repositorio: zatzuro/ZRE-core.

## Objetivo
Corregir brechas verificadas en los controles de publicación 2.6.7.3 sin reconstruir ZRE. No cambiar el comportamiento de Practice, Quali, Carrera, Spotter, administración, setup engineer, updater y Race Plan fuera del alcance de calidad.

## Evidencia de base reutilizada
- Release previo v2.6.7.3, SHA c3c0def5c829b14a6a54f053d5e4fb7f05b792bd.
- Integración posterior workflow hotfix e9f4796f75737950f3788909f3d6a442c23bf8fa.
- Python 367 casos y front Node, Chromium Historicas y Windows sobre SHA de candidato anterior.
- La rama 2.6.7.3 no ejecutó scripts antiguos Quali, Race V2, menú y regresión funcional en el release: condicional desactualizado observado en `.github/workflows/zre-branch-validation.yml`.

## Cambios
1. Unificar compuertas visuales en el candidato de release 2.6.7.4: Practice, Quali, Race V2, navegación/administración, funcional 2.6.7, historial 2.6.7.3. Chromium a 1366/1920/2560.
2. Agregar pruebas focalizadas de persistencia, varios coches/pilotos, reconexión, tiempos no observados, combustible, edición manual, protección y retención de base SQLite.
3. Limpiar registros de carreras inactivas tras 7 días, sin tocar la carrera actual ni registros protegidos. Nunca aplicar SessionTime como hora UTC; dar periodo de gracia a bases 2.6.7.3 existentes.
4. Impedir que identidad de sesión nula mezcle varias sesiones bajo la misma clave.
5. Si SQLite no está disponible, preservar el funcionamiento de ZRE y desactivar SOLO el historial/edición; persistencia debe fallar cerrada, no bloquear toda la aplicación.
6. Cerrar explícitamente la conexión SQLite al apagar el servicio y rechazar lecturas de combustible inverosímiles.

## Gates de release obligatorios y no opcionales
- Python compileall, unittest discover (incluye suites existentes y nueva integridad).
- Todas las regresiones JavaScript/Node.
- Smoke de servidor y WebSocket con fixtures.
- Chromium Practice / Quali / Carrera / Menú / Funcional / Historial (capturas de referencia).
- Windows instalación/arranque/recuperación y tests focalizados SQLite.
- Solo activar `main` y publicar tag `v2.6.7.4` con candidato de SHA idéntico cuando TODO esté en SUCCESS.
- No duplicar QA por otro commit sin cambio funcional; documentar cualquier test omitido.

## Documentación técnica de referencia
- iRacing SDK telemetry: https://sajax.github.io/irsdkdocs/telemetry/
- iRacing SDK Python: https://github.com/kutu/pyirsdk
- Playwright browser CI: https://playwright.dev/python/docs/ci

## Limitaciones de alcance
La telemetría de los demás coches no garantiza todas las vueltas anteriores a conectar ZRE; los huecos deben quedar SIN TIEMPO. La fuente FuelLevel de un espectador no garantiza litros del coche del equipo: no se ingesta como lectura real en la nueva base. No se puede certificar hardware, resultado en pista, telemetría iRacing en ejecución, conexión de dos PC o actualización concreta en el PC del usuario desde CI sintético.

La publicación de GitHub Pages es independiente de la release Windows y no debe modificarse sin una nueva validación del artefacto Pages.

## Estado al crear
Requerido: integrar pruebas, verificar CI de PR y release, confirmar SHA/versión desplegada; registro de resultados reales solo después de comprobarlos. Política Transversal V1; costos adicionales USD 0.
