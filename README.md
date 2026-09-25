# ZRE Core

**Zatzuro Race Engineering — iRacing Team Engineer**

Current stable baseline: **v2.3.0**

## v2.3.0 — Endurance Strategy
- Live **Rival Estratégico**: AUTO follows the closest meaningful same-class rival; the driver can pin another class rival.
- Pure-math endurance strategy engine recalculates from remaining race time, live pace, fuel, consumption, current stint and completed stops.
- Base vs extended autonomy comparison (default 37 vs 38), stops remaining, final stint and last-stop elimination.
- Cumulative extension target and remaining stint distribution.
- Stint timeline with manual driver assignment and double-stint indication.
- Relative/Class Standings reserve three rows above and below the player, keeping the player on the middle row.
- Web auto-update fix: assets install first and `version.json` is copied last. The open page reloads only after the complete web build is on disk.

## Strategy inputs
Live iRacing data is preferred. Manual overrides are available for base/extended stint length, effective pit loss, race-duration fallback, pace, consumption, tank capacity and driver names.

## Protected local data
The updater never replaces `.venv/`, `data/`, `dashboard.log` or `session_replay.jsonl`.
