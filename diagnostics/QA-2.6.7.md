# ZRE Core 2.6.7 — Publicación para validación en iRacing real

**Estado:** RELEASE publicado tras QA automatizado en GitHub Actions. **Primera validación con iRacing real pendiente del usuario.** Este lanzamiento tiene canal `stable` para que el actualizador normal pueda instalarlo; no equivale a una certificación en pista.

## Novedades

- Guardado automático de la información útil del SDK con almacenamiento local, rotación sin sobrescritura y limpieza segura por fecha real de finalización. Retención de 7 días, configurable; sesiones en curso, incompletas y protegidas no se eliminan automáticamente.
- Administración: cantidad de datos, fecha más antigua, historial de sesiones, protección, exportación ZIP y limpieza explícita.
- Recuperación tras reinicio o reconexión: registros locales de vueltas, coches, pilotos y resultados de **la misma sesión oficial**, dando prioridad a lo que entregue el SDK actual. Los snapshots históricos quedan marcados y **no** se presentan como resultados o gaps en directo.
- Quali oficial y Quali simulado activable durante Práctica; persistencia al cambiar pantallas y Coach limitado al rendimiento cronométrico.
- Carrera: posición, gaps, vueltas, combustible, autonomía y alertas destacados; standings centrado en coche propio ±2 y rival estratégico, ampliable, con letra y cantidad de pilotos configurables.
- Prevención de inicios de stint repetitivos ante fluctuaciones transitorias de `IsOnTrack` y del reloj SDK; eventos de reconexión registrados.

## Instalación / actualización

1. Cierra ZRE e iRacing si deseas realizar una instalación sin procesos en uso.
2. Abre el mismo `start_dashboard.bat` de siempre. El actualizador consulta `main/version.json` y descarga el paquete desde `release-2.6.7`. Los datos, `.venv`, configuraciones y reportes se conservan.
3. Comprueba en la pantalla y en `http://127.0.0.1:8765/version` que el runtime indica **2.6.7**.
4. **Importante:** si la instalación local sigue fijada al canal **TEST**, el actualizador estable está suspendido. Usa `Restore Stable` antes de volver a ejecutar el launcher de siempre.

## Validación de campo requerida

- Práctica → Quali simulada → Práctica → Quali (misma tanda), clasificación oficial y cambio en mitad de vuelta.
- Carrera: legibilidad del standings compacto, selección de rival, lectura de gaps y rendimiento del SDK real.
- Reinicio de ZRE durante la **misma** sesión: reconexión y reconstrucción de vueltas/participantes de logs.
- Jornada continua: almacenamiento de sesiones, protección, exportación ZIP y limpieza por retención.
- Revisar logs de cualquier `COACH STINT START` duplicado. La causa histórica no se demostró por ausencia del ZIP original.

## QA y límites

- QA en PR con **324 pruebas Python aprobadas**, frontend, aiohttp/WebSocket y Chromium 1366/1920/2560, 100/110%: [CI PR #38186695680](https://github.com/zatzuro/ZRE-core/actions/runs/38186695680).
- El workflow de release 2.6.7 debe aprobar nuevamente tests Python/frontend, suite Chromium, PowerShell Windows y smoke del servidor antes de crear el tag.
- **No se ha conectado el entorno CI a iRacing real.** Informar cualquier problema descubierto durante la prueba para un hotfix sin perder datos locales.
