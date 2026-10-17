# ZRE Core 2.6.7.3 — Historial de vueltas, comparación y Fuel Remaining

## Alcance
- Pantalla horizontal independiente HISTORIAL DE VUELTAS, accesible durante Piloto o Spotter, sin cambiar el SDK SessionType.
- Una tabla que compara vueltas reales del equipo contra un coche rival seleccionado, más filas proyectadas del equipo.
- KPIs: ritmo 5/10, mejor vuelta, consistencia, vueltas, entradas a boxes y delta de vueltas normales comparables.
- SQLite local protegido en data/lap_history.sqlite3: una vuelta por sesión+coche+contador. Cambios de piloto asociados al coche. No inventar tiempos en saltos SDK.
- Lectura Fuel Remaining editable por vuelta real. Fuente y correcciones auditables; proyección derivada, nunca una medición.
- Consumo de las últimas 10 vueltas comparables por tipo, con intervalos calibrados y clasificación de entrada/salida a boxes.
- Referencia de combustible remota no validada no desplaza lecturas propias/manuales del spotter; plan de repostaje sigue siendo estimativo.

## Gates obligatorios
1. Python compileall y unittest discover del SHA candidato.
2. Node frontend regression, incluida frontend_lap_history_2673.cjs.
3. Chromium de Práctica, Quali, Carrera, navegación (reutilizar scripts existentes) para el SHA de release.
4. Pruebas Windows de launcher, recuperación, smoke y versión 2.6.7.3.
5. Revisión Senior de riesgos P0/P1 y confirmación del SHA de CI antes de integrar.
6. Publicación solo mediante release-2.6.7.3 después de los gates, con main apuntando al SHA validado.

## Verificación física todavía necesaria
- Sesión real iRacing con relevo piloto/spotter, contador de vueltas de cada coche, nombre del rival, clasificación real de boxes, combustible reportado.
- Comparar Remaining del spotter con F4 en ambos ordenadores; garantizar seguridad en la estrategia.
- Registros de vuelta nunca observados permanecen sin tiempo; no prometer reconstrucción total durante desconexión.

## Riesgos
- La ventana SDK de los rivales puede omitir vueltas si el capturador no está activo; se conservan huecos SIN TIEMPO.
- El gasto de una vuelta con boxes sin lectura validada es estimado; una entrada/salida observada no significa que haya repostaje confirmado.
- Si se desconoce cuánto se repostará, la proyección posterior debe quedar SIN DATO.
- Rendimiento de SQLite y retención del histórico nuevo se deben vigilar durante una carrera larga.

## Política
Costo adicional objetivo: USD 0. No relajar CI ni publicar fuera de sus gates. Los resultados finales de QA, PR, SHA y publicación se consignan únicamente después de comprobarlos.
