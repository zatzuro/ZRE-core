# ZRE Core — UI payload contract

## v2.2.2 live screen
- Top cards: Reference, Tyres, Fuel, Pit.
- Bottom engineering boards: persistent stint loss map, one selectable Relative/Class Standings table, and lap pace/history.
- Timing columns: `POS/NUM`, `COCHE`, `PILOTO`, `DIF.`, `ÚLT.`, `Δ MEJOR`.
- `standing[]` is class-only and uses class position; `relative[]` remains spatial and may include other classes.
- Lap rows may include `consumption`.
- `coach.trackMap` contains `points`, up to three `markers`, and `source`. After a stint ends, markers remain frozen from that stint until the next stint summary replaces them.
- `appVersion` identifies the running bridge build. The frontend reloads itself when the browser is serving an older build.

## Required payload
- `appVersion`, `connected`, `demo`
- `header.{car,track,driver,position,lap,state}`
- `self.{fuel,lastUse,bestUse,worstUse,lastLap,bestLap,laps,wear,pit,pitWindow,nextStop}`
- `lastLapSummary`
- `relative[]`, `standing[]`
- `coach.trackMap.{points,markers,source}` when a trace is available

- `GET /version` returns `installedVersion` from disk and `runtimeVersion` from the active Python process. The browser checks it every 5 seconds only for update detection and reloads itself when the installed frontend changes.
