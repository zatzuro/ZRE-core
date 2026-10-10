# ZRE Core 2.6.6 — revisión Senior y notas de publicación

Repositorio: zatzuro/ZRE-core. PR acumulativo: #12. Entrega revisada: ce3a85202f7636b55a63da28c44423ef9331dbd4. Base main al recibir: 48f2839dab5279f7ea1db9c629172dabc8928dc1.

Esta revisión incluye Práctica, Quali y Carrera. Las ramas de Práctica/Quali ya están contenidas en el PR acumulativo. El constructor permanece archivado y sus archivos/configuraciones no se borran.

## Evidencia y método

CI de Desarrollo #38062435339 aprobado para el SHA entregado: pruebas Python, frontend y Chromium. Smoke de servidor y Windows estaban omitidos en ese run: no se consideran pruebas ejecutadas. Senior inspeccionó diff y fuentes y amplió las comprobaciones por defectos concretos de veracidad y lectura.

Tres focos: (1) procedencia/validez de datos y estrategia; (2) lectura horizontal e interacciones reales del navegador; (3) versión, runtime y ruta de actualización.

Pruebas adicionales locales: 99 pruebas Python focalizadas aprobadas (Quali, Carrera, propiedad de setup, Coach, Race Plan y exactitud de datos); contratos frontend Quali/Carrera aprobados; Chromium Práctica/Quali/Carrera en 1366×768, 1920×1080 y 2560×1440 aprobado. Recorrido completo mediante mensajes al router real de app.js: Práctica → Quali simulada/oficial → Garage → Carrera → SPOTTER → AUTO, aprobado, sin errores JavaScript. Escalado equivalente a 110% por reducción de viewport comprobado en Carrera. Servidor aiohttp real, /version, assets y WebSocket PILOTO/SPOTTER/AUTO aprobados con modo demo. Todas las fuentes de estos escenarios son simuladas y están identificadas como QA.

La publicación usa el workflow existente ZRE Branch Validation, ampliado para release-2.6.6, y exige validate + Chromium antes de crear v2.6.6. Versiones del manifiesto, HTML y assets coinciden. El SHA de main/release y los runs definitivos se documentan en la entrega final, después de ejecutarlos.

## Práctica

| Componente | Valor para el piloto | Funcionamiento | Legibilidad | Acción tomada |
|---|---|---|---|---|
| Mejor y última válida | Referencia de rendimiento | Historia local validada, no última vuelta inválida | Valores principales grandes | Conservado; diferencia explícita última válida |
| Óptima y delta | Cuantificar margen contra referencia | Óptima calculada por Coach; delta calculado | Lectura rápida y signo/color | Conservado; no equivale a vuelta realmente conseguida |
| Promedio y consistencia | Medir ritmo sostenible | Media/desviación de vueltas válidas del historial disponible | Cifras independientes | Excluir vueltas con caution observada |
| Coach por curva/zona | Decidir qué revisar en frenada/entrada/salida | Inferencias contra referencia propia, confianza y estado sin evidencia | Inventario y diálogo de detalle | Revisado; no inventa causas si faltan datos |
| Mapa interactivo | Localizar la recomendación | Geometría y curvas detectadas por modelo existente | Marcadores seleccionables; muchas curvas requieren detalle | Verificados 8/14/20 marcadores y apertura de detalle |
| Gráfica de ritmo | Ver mejora entre vueltas válidas | Historia de tiempos, no pronóstico | Tendencia clara; tiempo exacto en tooltip | Conservado |
| Combustible/consumo/autonomía | Preparar duración de tanda | Fuel local; consumo válido; autonomía calculada | Fuente visible | Excluir caution de la muestra de consumo |
| Controles y cambio de sesión | Acceder al trabajo sin perder espacio | Plegado, modos existentes, sesiones separadas | Sin superposición en resoluciones objetivo | Probado con router de aplicación |

## Quali

| Componente | Valor para el piloto | Funcionamiento | Legibilidad | Acción tomada |
|---|---|---|---|---|
| Delta en vivo | Saber si mejora durante la vuelta | LapDeltaToBestLap con flag de validez SDK | Hero, signo y color | Conservado |
| Mejor/última/óptima/potencial | Comparar resultado y margen | Mejor SDK, última observada, óptima inferida | Etiquetas de origen | Mejor SDK ahora consume bestPersonalSDK, no un valor local bajo etiqueta SDK |
| Activación oficial/simulada | Entrenar clasificación en práctica | Backend autoritativo; no modifica SessionType | OFICIAL/SIMULADA explícito | Probados selector, transición y prioridad de Quali oficial |
| Tandas/intentos | Separar ejercicios | Deduplicación; legalidad desconocida queda pendiente | Contadores y último estado | Corregido gate de vuelta: ignora la parcial, acepta la siguiente completa |
| Sectores | Localizar ganancia/pérdida | Límites SDK; tiempos reconstruidos; referencia validada | Tabla horizontal | Priorizar sector de vuelta en curso frente al anterior |
| Mapa/prioridades/foco | Orientar próxima vuelta | Coach existente; recomendaciones condicionadas a evidencia | Foco destacado; detalle amplio en Garage | Borrar consejo anterior cuando ya no existe diagnóstico |
| Tráfico/banderas/temperatura | Evitar una vuelta comprometida | Posición observada, flags y temperatura SDK | Bandera legible | Sustituido código numérico por nombre; otros flags no interpretados se identifican como SDK |
| Neumáticos/combustible | Preparar tanda | Neumáticos: última lectura disponible; fuel local | Unidades visibles | Consumo y autonomía usan muestra válida, sin caution |
| Garage/comparación/Setup Engineer | Analizar entre intentos | Dos vueltas validadas con sectores compatibles; propiedad de setup comprobada | Vista especializada | Probadas entrada Garage y comparación; guardas de propiedad conservadas |

## Carrera

| Componente | Valor para el piloto | Funcionamiento | Legibilidad | Acción tomada |
|---|---|---|---|---|
| Posición de clase | Conocer resultado competitivo | ResultsPositions, fallback identificado | P de clase y fuente | Conservado y contrastado con orden oficial |
| Gaps delante/detrás | Controlar tráfico físico | Session Intelligence, posición dinámica, segundos estimados | Identidad y EST. visibles | Sin convertir posición de clase en gap; se vacían al desconectar |
| Última vuelta/mi ritmo | Sostener rendimiento | Hasta 8 observaciones, media de 3–5 comparables | KPIs separados | Caution propia queda visible pero fuera de la media |
| Fuel/consumo/restante | Gestionar stint | SDK local, FuelModel existente y tiempo de sesión | Unidades y muestras | Fuente preservada; autonomía y objetivo se vacían al desconectar |
| Class Standings | Consultar rivales reales de clase | Orden SDK, mejor/última, identidad por CarIdx | Lista cercana y clasificación completa | Probadas 8/18/38 entradas, selección y ampliación |
| Rival AUTO/MANUAL/buscador | Seguir un coche estratégico | AUTO por proximidad en clase; manual por CarIdx, conservado ante ausencia | Identidad, presencia y antigüedad | Verificados nombre/número/posición, tabla, AUTO y rival en boxes |
| Cuatro ritmos | Comparar presión de rivales | Una serie por coche, cuatro roles; media comparable; no unir anomalías | Colores distinguibles, ejes legibles | Corregido SVG diminuto; escala usa todos los tiempos comparables, sin recorte engañoso |
| Race Plan/ventana/litros/paradas | Decidir cuándo y cuánto repostar | Único motor vNext; no estrategia paralela | Próxima parada prioritaria | Detalle probado; neumáticos sin decisión y piloto sin asignar se declaran, no se inventan |
| Combustible y eficiencia | Comparar consumo con modelo estratégico | FuelModel y Race Plan existentes | Observado, objetivo, diferencia, autonomía | Corregida superposición a 1366×768 |
| Sprint/Endurance | Cambiar prioridad visual | Solo presentación | Paneles cambian de proporción | Probados tres énfasis, sin mutar estrategia |
| Conexión/cambios de piloto | Evitar interpretar historia como presente | Ausentes marcados STALE; muestras guardan nombre de piloto | Histórico separado de vecino vivo | Pruebas de dominio revisadas; el ritmo representa al coche, puede contener pilotos anteriores |

## Datos y límites de interpretación

- Oficiales: posiciones de ResultsPositions y mejor personal confirmado por SDK. Un fallback de posición no se presenta como oficial.
- Medidos/observados: fuel local, últimos tiempos, entradas a boxes, temperatura y flags. Ausencia de observación no demuestra ausencia del coche.
- Calculados: media, desviación, delta, sectores reconstruidos, autonomía. Comparar vueltas requiere muestras suficientes.
- Estimados/inferidos: segundos de gap físico, óptima, Coach, ritmo comparable rival, ventana de parada y predicciones de rivales. No equivalen a instrucciones oficiales de iRacing.
- Las curvas son detectadas por el modelo; su numeración necesita contrastarse con la pista real. El mapa no certifica nomenclatura oficial.
- La gráfica compara últimas observaciones por coche, no necesariamente vueltas simultáneas. Las vueltas anómalas no se interpolan. Un rival que también es vecino comparte serie.
- Quali no acredita toda vuelta limpia como oficialmente válida: sin confirmación SDK permanece PENDING VALIDATION. Esto puede limitar comparación de intentos sin mejora del mejor personal.
- La selección manual persiste durante la sesión del puente y reconexiones del navegador; al cambiar de sesión se reinicia para no aplicar CarIdx de otra carrera.
- Neumáticos proceden de la última lectura disponible; no se afirma desgaste en tiempo real. No se ha implementado una decisión nueva de neumáticos bajo el nombre de QA.

## Correcciones Senior

Gráfica Carrera con tamaño legible y rango completo; bloque de combustible sin superposición; limpieza de consejo Quali obsoleto; nombres de banderas; mejor personal desde SDK; prioridad de sectores actuales; primera vuelta completa de tanda ya no descartada; consumo Quali con muestras válidas; exclusión de caution observada durante la vuelta propia; autonomía/objetivo obsoletos retirados tras desconexión. Versión y ruta de release actualizadas a 2.6.6.

## Validación pendiente en PC/iRacing

No se ejecutó iRacing ni un SDK de Windows real en este entorno. Quedan por comprobar físicamente: correspondencia de curvas en pista, utilidad del Coach con conducción real, latencia de gaps, legibilidad a distancia y bajo carga, cambio de piloto endurance, reconexión real del SDK y arranque/autoactualización del launcher habitual en Windows. La publicación de un artefacto no demuestra que ya esté instalado en el PC del usuario.

## Evaluación del producto

Práctica sí aporta herramientas para mejorar: pérdida localizada, referencia propia y tendencia, condicionadas a vueltas comparables; no garantiza bajar tiempos. Quali sí ayuda con delta, sectores y tandas diferenciadas; la validación conservadora limita comparaciones sin evidencia SDK. Carrera sí permite decidir sobre tráfico, ritmo y repostaje usando fuentes existentes; gaps y estrategia siguen siendo estimaciones y requieren la comprobación física indicada.

No hay migración de datos ni cambio de infraestructura. Se conserva el release estable anterior como referencia de rollback; no se crean backups redundantes ni se modifican datos del usuario. La reversión debe considerar que el updater compara versiones: volver a un manifiesto inferior no fuerza downgrade en clientes ya actualizados.
