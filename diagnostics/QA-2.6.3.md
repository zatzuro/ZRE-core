# ZRE Core 2.6.3 — QA y publicación

Base productiva auditada: `4eefa802f5d532b04c0a5647c03a0121bfbb9854`.
Rama preparada: `develop/2.6.3`, once commits hasta `c0eba523fd675407af6b9369afb3e62702fbbdfa`.

## Correcciones de QA

- Historial: confirmación numerada oficial con `ResultsPositions.LastTime/LapsComplete`; espera si `LapLastLapTime` conserva el tiempo anterior; confirmación mediante `LapBestLap/LapBestLapTime`; tiempos cero/negativos excluidos; no depende de disponer de combustible. PISTA/PIT/RESUMEN muestran la vuelta reciente primero sin modificar el historial.
- Race Engineer: seguimiento por CarIdx y vuelta completada para todos los coches de clase, no por hueco delante/detrás. Baseline al entrar/reconectar; cambio de posición sin locución; espera si el tiempo llega tarde; admite tiempos idénticos con confirmación numerada. SPOTTER observa el coche de equipo y mantiene historial sin inventar consumo.
- Audio automático: Practice/Test conserva Coach; Qualify permanece silencioso y no alimenta análisis/stints; Race emite tiempos cortos. Cola limitada de 16 mensajes; alertas estratégicas eliminan locuciones secundarias pendientes. Se evalúa Race Plan del frame antes de emitir tiempos.
- Setup: copia profunda al inicio del stint, identidad SDK/HTML visible al principio del reporte, nombre sanitizado y limitado en el archivo, comparación entre snapshots correspondientes. UpdateCount de CarSetup no altera fingerprint.
- Standings: ResultsPositions conserva todos los coches de clase aunque no estén cargados. Relative conserva orden dinámico e inserta vecinos oficiales ausentes y coche propio sin duplicar. Posiciones de clase coherentes en SPOTTER.
- Gap estático: se elimina la resta de ResultsPositions.Time y la inferencia de vueltas de diferencia a partir de contadores capturados en instantes distintos. Los campos disponibles no garantizan un intervalo relativo vivo. Cuando falta posicionamiento dinámico se muestra `ESTÁTICO · SIN INTERVALO`. Los gaps dinámicos conservan fuente estimada explícita.

## Validación

- 176 pruebas Python: PASS (147 existentes y 29 nuevas).
- Tres suites Node: frontend_recovery, frontend_race_plan, frontend_release_263: PASS.
- Python compileall, node --check y git diff --check: PASS.
- Incluye rutas PILOTO/SPOTTER completas, AUTO/manual y cambios de identidad de equipo, reconexión, cambio de sesión, Race Plan, WebSocket y updater existentes.
- Dos expectativas históricas se actualizan para el audio automático y el nombre del setup en el reporte.

Las pruebas usan fixtures SDK y servidor aiohttp local. No se dispone de iRacing/Windows en este entorno; no se afirma una prueba de conducción real ni escucha de SAPI. Dos vueltas exactamente iguales con SDK retrasado se conservan pendientes hasta recibir confirmación numerada, en lugar de fabricar un tiempo.

## Publicación

La rama inmutable `release-2.6.3` contiene el mismo árbol que el commit aprobado. GitHub Actions repite validación y crea el tag/release `v2.6.3` sobre ese commit. Solo después se adelanta main al mismo commit; version.json anuncia 2.6.3 y descarga release-2.6.3. Los identificadores del frontend y caché coinciden.
