# ZRE 2.6.7.4.2 — Hotfix de sincronización de vueltas en resistencia

Incidente reportado el 17 de octubre de 2026: el automóvil del equipo ya estaba en la vuelta 272 y ZRE continuaba mostrando la última vuelta 268 aun después de instalar v2.6.7.4.1.

## Diagnóstico y antecedentes
- v2.6.7.4.1, PR #26, añadió recuperación desde `SessionInfo.Sessions[].ResultsPositions[].LapsComplete`. Sin embargo, iRacing define `SessionInfo` como YAML de baja frecuencia, **no** una transmisión de vueltas en tiempo real. El fallback puede quedar estático junto con `CarIdxLapCompleted`.
- La documentación SDK distingue `CarIdxLap` (vueltas iniciadas) de `CarIdxLapCompleted` (terminadas), así como `CarIdxLapDistPct` (posición fraccionaria en pista). Estas son fuentes adicionales y separadas.
- El historial en SQLite conservaba la última vuelta sin comunicar inequívocamente cuándo todas las fuentes estaban detenidas; el frontend presentaba silencio como sincronización sana.

## Hotfix
1. Comparar `CarIdxLapCompleted`, el contador oficial YAML y `CarIdxLap - 1` para seleccionar la última meta acreditada del automóvil; una inferencia de vueltas iniciadas no concede tiempo ni piloto a las vueltas faltantes.
2. Si los tres contadores se congelan pero el porcentaje de circuito sigue actualizándose, detectar pasos observados por meta bajo condiciones conservadoras: 85→15 %, `SessionTime` monotónico con transición en hasta 12 s, superficie válida y mínimo entre cruces de media vuelta estimada. No inventar meta solo por ausencia de telemetría.
3. Reconciliar cuando llega posteriormente un tiempo de vuelta confirmado, sin duplicar ni atribuir el mismo tiempo a varias vueltas anteriores.
4. Mantener los estados de combustibles y boxes seguros: no usar combustible local o bit de boxes obsoleto para un paso por meta derivado.
5. Mostrar en Historial `ÚLTIMA META`, vuelta iniciada actual, procedencia del avance y alerta `SIN SINCRONIZACIÓN` si la carrera sigue sin emitir progreso por más de 2,5 vueltas típicas.
6. Exponer el último contador reconstruido también a Spotter después de cada actualización, sin asignar valor ficticio de LastTime.

## Nuevos escenarios de QA
- Exactamente 268→272 con Completed y YAML detenidos; `CarIdxLap` avanza a 273.
- Exactamente cuatro cruces por meta observados con `CarIdxLapDistPct` cuando todos los contadores se congelan.
- Sin tiempos inventados, ni falso piloto ni gasolina consumida como lectura real.
- Cruce espurio/teletransporte, salto superior a 12 s, doble cruce imposible y ausencia completa de fuentes.
- Confirmación tardía de `ResultsPositions`/SDK, reinicio, deduplicación y alerta visual de estancamiento.
- Regresiones completas Python, frontend, WebSocket, Chromium en 1366/1920/2560 y Windows.

## Fuentes
- https://sajax.github.io/irsdkdocs/yaml/
- https://sajax.github.io/irsdkdocs/contexts.html
- https://github.com/vipoo/iRacingSDK.Net/blob/master/DataFeed/GeneratedTelemetry.cs
- https://github.com/kutu/pyirsdk
- Histórico ZRE: PR #21, #23, #26; diagnoses y pruebas 2.6.7.3/4/4.1.

## Límite de verificación
Si iRacing deja de emitir **todas** las señales (counters, resultados y progreso en circuito), ningún algoritmo puede certificar vueltas no observadas. ZRE conservará históricos y avisará en lugar de inventar resultados; queda pendiente un QA físico con la sesión de iRacing del usuario. La actualización del ordenador es mediante el actualizador estable; no se asegura que su PC ya la tenga instalada.

## Condición de release
No publicar hasta que CI de `release-2.6.7.4.2` en el SHA final sea SUCCESS en validate, Chromium, Windows y release; no modificar o cancelar los runners vigentes ni pagar más de USD 0.
