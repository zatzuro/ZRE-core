# ZRE Core 2.6.4

Finalización del desarrollo acumulado en develop/2.6.4, basado en main
692a4d79b60feacb762c23e4c4fead3f26011928. No requiere credenciales para bitácoras.

## Cambios y correcciones
- Corregido SyntaxError que impedía iniciar el servidor.
- Practice, Quali y Race muestran herramientas propias; Quali analiza sus propias
  vueltas válidas, conserva el silencio y reinicia referencias al cambiar sesión.
- Session Intelligence distingue SDK_OBSERVED y ZRE_INFERRED, unidades SDK,
  estado seco real, banderas, disponibilidad y contexto del piloto para PitsOpen.
- Rivales LIVE/STALE conservan última observación; también al desconectar SDK.
- FSM de pit con baseline limpio, dos anomalías y recuperación; suppressión por
  caution, incidentes y ralentización de clase. Reconciliación SDK/inferencia.
- Ventanas de próxima parada basadas exclusivamente en stints observados.
- Duración observada en pit road separada de exceso de vuelta y pit-loss estimado;
  rejoin utiliza CarIdxEstTime cuando es válido. Fuentes y confianza explícitas.
- UNDERCUT/OVERCUT/HOLD sólo con evidencia suficiente; en su ausencia, NO
  RECOMMENDATION. No se inventa combustible/neumáticos rivales ni audio agresivo.
- Bitácoras locales en session_logs: session.json, timeline.jsonl, summary.json y
  summary.md; eventos, auditoría de predicciones y resultados. Uploader eliminado.
- Retención 7 días, sesión activa protegida, cola acotada y disco fuera del hilo SDK;
  rotación 5 MB + un respaldo, máximo 128 sesiones / 256 MB terminados.
- Posición SDK live 1-based, ClassPosition oficial 0-based; identidad por CarIdx,
  conflictos de nombres sin atribución. Corregidos audio propio Race y override demo.
- Updater preserva bitácoras/reportes y elimina el uploader obsoleto instalado.

## Validación
- 212 pruebas Python, incluidas 35 dirigidas a 2.6.4.
- compileall y node --check; cuatro suites JavaScript de regresión.
- Servidor real local: HTTP, assets sin caché, /version, WebSocket y demo
  PILOTO/SPOTTER/AUTO. SDK de iRacing simulado, no prueba dentro de iRacing real.
- Secuencia 78/78/79/97/144/80, falso positivo aislado, pit false/true/false,
  reconciliación, STALE/reaparición, aislamiento Practice/Quali/Race y logger.
- Benchmark sintético: 64 coches, 500 frames; mediana 0.49 ms / p95 0.54 ms
  para Session Intelligence en el entorno de QA (no garantía en otro equipo).

## Límites que requieren iRacing real
Confirmar visibilidad y latencia de variables con sesiones reales multiclase/team,
transiciones SDK, lluvia/caution, tiempo de pit road y precisión de ventanas/rejoin.
Las paradas por vueltas lentas siguen siendo PROBABLE, y pit-loss/rejoin son
estimaciones con incertidumbre; la estrategia puede abstenerse por falta de datos.

Contratos SDK revisados contra https://github.com/kutu/pyirsdk/blob/master/vars.txt
 y https://github.com/kutu/pyirsdk/blob/master/irsdk.py.
