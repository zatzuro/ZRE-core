# ZRE Core

**Zatzuro Race Engineering — iRacing Team Engineer**

Current stable baseline: **v2.1.6**

ZRE Core is the complete team-engineering dashboard. The Driver Coach is one module alongside timing, relative/standings, fuel and pit strategy, telemetry analysis, lap diagnostics and the loss-map system.

## v2.1.6
- Automatic update watch while ZRE is running.
- Checks the stable channel every 5 minutes, including during an active race.
- Downloads/installs program files in the background without restarting or interrupting the running race.
- The running process keeps its already-loaded code; the downloaded version is fully active on the next normal launch.
- Local runtime data such as `.venv/`, `data/`, `dashboard.log` and `session_replay.jsonl` stays protected.
