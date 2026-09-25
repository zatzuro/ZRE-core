# ZRE Core

**Zatzuro Race Engineering — iRacing Team Engineer**

Current stable baseline: **v2.2.2**

## v2.2.2
- Loss map keeps the last frozen end-of-stint coaching summary, prioritizing recurring problems instead of jumping to the latest lap.
- Timing table separates **COCHE** and **PILOTO** while keeping **POS/NUM** combined.
- The three engineering boards (map, Relative/Standings, pace) are anchored to the bottom of the live screen.
- Top cards are ordered: **Referencia personal → Neumáticos → Combustible → Parada**.
- Browser cache is disabled for the local dashboard; the page checks the installed ZRE build every 5 seconds and reloads itself automatically when a background update installs a newer frontend. No F5 is required.
- Updater v2 uses a unique release branch per version, validates the ZIP and installed version, preserves local data, and checks every two minutes while ZRE is running without restarting a race.

## Protected local data
The updater never replaces `.venv/`, `data/`, `dashboard.log` or `session_replay.jsonl`.
