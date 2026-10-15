# ZRE Core 2.6.7.1 — QA y notas de release

Corrección Senior de ZRE-20261015-TIRE-SNAPSHOT-STALE. Incluye la navegación/tema del PR #16 y funcionalidad del #17 en una única integración. PR #18 Visual Lab se mantiene separado.

## Integridad y comportamiento
- Inspecciones nuevas son OBSERVED; frescura, atribución y comparabilidad independientes. Sin prueba del mismo juego no se calculan deltas. Lecturas de transición originales conservadas; garageAtEnd contiene la fuente posterior.
- Evidencia por rueda, reemplazo parcial ambiguo; no se certifica un servicio a partir de una firma o UpdateCount.
- SessionNum, propietario/piloto/equipo y stintId controlados. Offline cero requiere generación de runtime idéntica; tras reinicio queda sin atribución automática. Ventana de 300 segundos del SDK; nuevo stint persiste cierre de ventana anterior.
- JSON y Markdown atómicos; inspección recuperable e idempotente, reintento de reporte tras fallo sin duplicar stint.
- setupFingerprintV2 normaliza observaciones de neumáticos; fingerprint legado y ficheros anteriores se conservan. Cambios mecánicos reales siguen diferenciando setups.

## Matriz P1-01 a P1-20

Suite `tests/test_tire_release_2671.py` más los siete casos originales actualizados. P1-20 se complementa con las regresiones funcionales de Quali, Coach, fuel, Race Plan, storage, updater y smoke Windows/Chromium obligatorias del workflow.

| Caso | Test focalizado | Resultado local |
|---|---|---|
| P1-01-repeated | `P1_01_repeated_raw_never_zero_wear_claim` | PASS · datos controlados |
| P1-02-separate | `P1_02_separate_observation_attribution_set` | PASS · datos controlados |
| P1-03-repeated | `P1_03_repeated_garage_remains_pending` | PASS · datos controlados |
| P1-04-preserve | `P1_04_preserve_original_source_samples` | PASS · datos controlados |
| P1-05-revision | `P1_05_revision_alone_not_inspection` | PASS · datos controlados |
| P1-06-pressure | `P1_06_pressure_only_never_certifies_wear` | PASS · datos controlados |
| P1-07-requires | `P1_07_requires_pit_and_matching_session_number` | PASS · datos controlados |
| P1-08-partial | `P1_08_partial_tire_replacement_per_wheel` | PASS · datos controlados |
| P1-09-next | `P1_09_next_stint_closes_window_durably` | PASS · datos controlados |
| P1-10-owner | `P1_10_owner_driver_team_changes_rejected` | PASS · datos controlados |
| P1-11-offline | `P1_11_offline_zero_ids_need_runtime_generation` | PASS · datos controlados |
| P1-12-restart | `P1_12_restart_idempotent_without_duplicate` | PASS · datos controlados |
| P1-13-atomic | `P1_13_atomic_json_failure_preserves_original` | PASS · datos controlados |
| P1-14-partial | `P1_14_partial_fields_never_zero_fill` | PASS · datos controlados |
| P1-15-pressure | `P1_15_pressure_units_orientation` | PASS · datos controlados |
| P1-16-second | `P1_16_second_inspection_no_rewrite` | PASS · datos controlados |
| P1-17-normalized | `P1_17_normalized_fingerprint_inspection_ignored` | PASS · datos controlados |
| P1-18-real | `P1_18_real_settings_still_change_identity` | PASS · datos controlados |
| P1-19-markdown | `P1_19_markdown_atomic_and_honest` | PASS · datos controlados |
| P1-20-time | `P1_20_time_window_rejects_backwards_and_expires` | PASS · datos controlados |
| P1-13b-report | `P1_13b_report_failure_retry_after_durable_amendment` | PASS · datos controlados |

## Evidencia y límites
Regresión local: suites de neumáticos, Setup Engineer/ownership, Quali/stint; suite Python completa y smoke aiohttp/WebSocket. El CI final se consulta por SHA en Actions. Windows CI verifica almacenamiento, neumáticos y arranque demo; Chromium usa fixtures. Ninguna prueba representa una sesión física de iRacing.

**NO VERIFICABLE — PRUEBA FÍSICA DE SDK / WINDOWS DEL USUARIO.** Pendientes: secuencia real de inspección/servicio del McLaren, reloj SDK, reconexión en pista y lectura de Carrera al conducir. La causa histórica de COACH STINT START no se atribuye sin logs.

## Backup, activación y rollback
Estable previo: 2.6.7, main/tag v2.6.7 en 878babe278ef8b4618b88ad500f40d0295ee16a6. El tag/release/branch anterior se conserva y se crea referencia backup antes de integrar.
El candidato release-2.6.7.1 es hijo directo de main integrado. Tras aprobar validate, Chromium y Windows, el job activa el manifiesto estable en main mediante avance rápido y crea v2.6.7.1. No activa actualizaciones antes del QA del candidato.
Updater conserva .venv, data, session_logs, reports, build-state y configuraciones fuera del paquete. Rollback de copia fallida restaura archivos del programa. Ante P0/P1 productivo: detener distribución y crear commit de recuperación del árbol estable anterior en main; mantener release-2.6.7 intacta. Restore Stable permite bajar versión explícitamente. No copiar datos del paquete sobre históricos del usuario.
Costo adicional: USD 0; repositorio público, infraestructura Actions existente, ningún servicio nuevo.
