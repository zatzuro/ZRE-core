# ZRE Core 2.6.6.1 — selector de las tres pantallas y Quali durante Práctica

## Problema confirmado en 2.6.6
La vista Quali simulada sí existía, pero se activaba desde el selector «SESIÓN ZRE» y no existía un menú visible que reuniera Práctica, Quali y Carrera. `desiredView()` forzaba Quali al detectar `qualifyingMode`, incluso cuando un usuario quería volver temporalmente a Práctica. Esa dependencia mezclaba la navegación visual con el estado autoritativo de clasificación.

## Funcionalidad de 2.6.6.1
- Selector horizontal «PANTALLA» con AUTO · SESIÓN, PRÁCTICA, QUALI y CARRERA.
- Activación de Quali desde Práctica envía exactamente el comando existente `quali_mode:simulate` al backend, que abre una tanda real de ZRE con datos SDK de práctica. La pantalla Quali completa (delta, sectores, Coach, tráfico, Garage) se muestra sin reconstruir sus métricas.
- Volver a Práctica cambia **solo la vista** y **no cierra** la tanda Quali en curso. Regresar a Quali muestra la misma tanda y no la reinicia. Terminar la simulación se hace explícitamente con «SESIÓN ZRE → ENTRENAMIENTO».
- AUTO respeta el estado actual del SDK y de `QualiRuns`; las sesiones oficiales de Quali y Carrera mantienen prioridad automática.
- Carrera se habilita solo cuando `raceDashboard` está disponible: no se fabrica clasificación, gaps o estrategia en una sesión de práctica.
- Práctica como vista de consulta durante Quali oficial o Carrera conserva la telemetría verdadera y etiqueta «SOLO CONSULTA»; no cambia el SessionType.
- Selector oculto en SPOTTER; menú se restaura al volver al modo PILOTO. Cambio de sesión SDK reinicia la preferencia visual para evitar contextos cruzados.
- Menú con opciones deshabilitadas cuando faltan los datos, estado legible de sesión real («iRacing: PRÁCTICA» vs «SIMULACIÓN QUALI ACTIVA») y controles existentes sin cambios.
- Corregido atributo `hidden` de acciones Quali/énfasis cuando las reglas CSS asignaban `display:flex`.

## Validación
CI valida el código Python existente, frontend y smoke WebSocket. QA Chromium dedicado prueba el enrutador real y el protocolo de mensajes desde la vista: Práctica → Quali sim → Práctica (tanda intacta) → Quali → AUTO, salida de simulación, Quali oficial, Carrera, SPOTTER, cambios de sesión, tres resoluciones horizontales 1366×768, 1920×1080 y 2560×1440 y equivalente a zoom 110%, sin scroll lateral ni solapamiento de menú. Capturas y resultados en el pipeline.

**Límite de evidencia:** estas pruebas usan paquetes de telemetría SIMULADOS. La latencia y visibilidad en el PC del usuario con un SDK real de iRacing deben validarse físicamente. La publicación de GitHub tampoco prueba la instalación automática hasta lanzar ZRE localmente.
