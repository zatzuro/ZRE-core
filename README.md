# ZRE Core

**Zatzuro Race Engineering — iRacing Team Engineer**

Current stable baseline: **v2.2.0**

## v2.2.0
- Permanent loss map in the live screen.
- One selectable timing table: Relative or class-only Standings.
- POS and car number merged into POS/NUM.
- Manufacturer logo treatment in timing rows with offline fallback.
- Fuel/reference/tyres/pit cards moved above timing so race tables sit lower in the driver's sightline.
- Lap pace/history adds fuel consumption per lap.
- Standings are filtered to the player's iRacing car class and use class position.
- Automatic updater checks immediately when the bridge starts and then every 2 minutes while ZRE is running; it installs files in the background but never restarts an active race.
- `.venv/`, `data/`, `dashboard.log` and `session_replay.jsonl` remain protected.
