# ZRE Core 2.6.7.2 — Hotfix de propiedad de setup local

Fecha: 2026-10-15. Corrección focalizada del falso bloqueo «Coche rival o relación con el equipo no verificable» al visualizar rivales y abrir ZRE Setup Engineer.

## Causa y corrección
El coche elegido para timing, spotter o rival (TeamCarContext.car_idx) podía sustituir al coche local al resolver el propietario de CarSetup. El SDK CarSetup pertenece al piloto local, no al rival seleccionado. El nuevo guard reconoce exclusivamente al propietario que coincida simultáneamente en PlayerCarIdx, DriverInfo.DriverUserID y el UserID del roster SDK para ese PlayerCarIdx, además de la identidad local guardada. Continúa bloqueando datos de oponentes, espectadores sin evidencia, discrepancias de ID y selecciones manuales no corroboradas.

## Alcance
- PR #20: https://github.com/zatzuro/ZRE-core/pull/20
- Solo se modifica server/setup_ownership.py y las pruebas de autorización/feedback propio.
- No se modifica el diseño del dashboard, su transporte WebSocket, la lógica de vueltas, el SDK ni la persistencia de históricos.
- Backup/rollback: tag y rama release-2.6.7.1 existentes se conservan íntegros. Los datos de usuario no están dentro del paquete actualizado.

## QA obligatorio y activación
- Antes de publicar: validate (suite Python completa + regresiones frontend + smoke), practice-visual (Chromium 1366/1920/2560), windows-test-install (propiedad de setup, almacenamiento, integridad de neumáticos y smoke).
- El job release-2672 solo puede avanzar main en fast-forward desde su único padre integrado y crear v2.6.7.2 si todos esos jobs están SUCCESS sobre el mismo SHA. Nunca saltar gates.
- Confirmar release/tag/main/candidato por SHA; permitir que el updater estable descargue release-2.6.7.2 automáticamente.
- Prueba con iRacing real y verificación en el PC del propietario siguen pendientes y no son sustituidas por QA sintético.

## Límites
No inferir autorización por un coche rival seleccionado, por un archivo HTML importado ni por una grabación sin identidad. El hotfix no da permisos offline generales para editar cualquier stint histórico.
Costo adicional autorizado: USD 0 con Actions existente del repositorio público.

## Primer candidato rechazado por CI
SHA a095f85... no publicado: test_recovery.AssetAndUpdaterTests.test_html_contract detectó meta zre-build 2.6.7.1 frente a APP_VERSION 2.6.7.2. Corregido en este candidato actualizando HTML, assets y condición exclusiva del job release-2671. Se exige una nueva ejecución completa sobre el SHA final.
