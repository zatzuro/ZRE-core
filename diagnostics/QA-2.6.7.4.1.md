# ZRE Core v2.6.7.4.1 — Corrección del segundo relevo en carrera

**Incidente reportado:** durante una carrera de resistencia ZRE registró correctamente al compañero, actualizó al pasar al usuario local, pero al regresar el compañero al automóvil dejó de añadir vueltas y parecía que el coche seguía en boxes.

## Diagnóstico de código
- `LapDatabase.observe()` dependía exclusivamente de `DriverInfo.Drivers` + `CarIdxLapCompleted`; el roster es de conductor actual y puede variar en cada relevo, y la telemetría por índice puede estar retrasada en el PC que deja de conducir.
- `spotter_payload()` solo acudía a `ResultsPositions.LapsComplete` cuando el contador era `None`, no cuando era válido pero estaba atrasado. Un `CarIdxOnPitRoad` anterior podía quedar mostrado como estado actual.
- Estando el coche ausente temporalmente de `DriverInfo`, `TeamCarContext` perdía la identidad del coche y podía elegir el modo equivocado.

## Corrección
1. Comparar contador por índice y contador observado en **ResultsPositions** para el mismo `CarIdx`, usar la fuente más avanzada; no importar cachés `RECOVERED` como realidad nueva.
2. Si el resultado oficial avanza mientras el SDK por coche está congelado, desestimar los indicadores antiguos de pit lane y registrar la vuelta con fuente `RESULTS_OBSERVED`.
3. Conservar la última identidad de automóvil/equipo durante una ausencia temporal del roster; no adivinar el nombre del piloto mientras está ausente.
4. Conservar un registro por coche/vuelta y persistir huecos como `SDK_MISSING` sin duplicar o inventar tiempos.
5. Añadir pruebas que reproducen **David → Santiago → David**, pérdida del roster, SDK congelado, cambio de box, reinicio y reconexión, así como una regresión Chromium de la tabla actualizada por WebSocket.

## Validaciones de publicación
- Pruebas Python completas + nueva suite de relevo.
- Frontend, WebSocket, tres resoluciones Chromium y regresiones de Práctica, Quali, Carrera, Spotter, administración e Historial.
- Windows launcher/recovery, smoke y versión del manifiesto.
- Exigir CI `SUCCESS` del SHA candidato de release **antes** de mover main y crear tag v2.6.7.4.1.
- Política Transversal V1 y USD 0 adicionales.

## Límites
La fuente `ResultsPositions` solo recupera vueltas que realmente notifica iRacing; la conexión del spotter podría no contener todo el historial previo. Las vueltas no observadas permanecen sin tiempo y una fila puede indicar piloto sin confirmar.
Las pruebas CI reproducen SDK sintético. La validación física del segundo relevo en la carrera en vivo del usuario no puede ejecutarse de forma remota en su PC.

## Evidencia
El resultado real de QA se consulta en la ejecución del SHA final y tag `v2.6.7.4.1`. Los fallos de pruebas bloquean la publicación.
