# ZRE Core

**Zatzuro Race Engineering — iRacing Team Engineer**

Current stable baseline: **v2.1.5**

ZRE Core is the complete team-engineering dashboard. The Driver Coach is one module alongside timing, relative/standings, fuel and pit strategy, telemetry analysis, lap diagnostics and the loss-map system.

## v2.1.5
- Product identity updated to ZRE Core / Team Engineer.
- Automatic update bootstrap added at startup.
- Updates are checked only before the dashboard starts; an active session is never interrupted.
- Local runtime data such as `.venv/`, `data/`, `dashboard.log` and `session_replay.jsonl` is protected.
- If the update channel cannot be reached, the installed version starts normally.

The complete v2.1.5 runtime package is the validated baseline for the next update.
