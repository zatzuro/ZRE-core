# iRacing Dashboard v2.0 — UI payload contract

The frontend is split into three automatic screens: live, pit and summary.

## v2.2 live additions
- The live screen keeps a permanent coach loss map.
- One timing table switches between Relative and class-only Standings.
- Timing rows use POS/NUM, manufacturer identity, driver, gap, last lap and delta to best.
- Lap history rows may include `consumption` in addition to lap/time/delta.
- `standing[]` is expected to contain only the player's car class; `relative[]` may contain nearby cars from other classes.

## Screen selection
- `live`: default when `self.pit == "EN PISTA"`.
- `pit`: automatic when `self.pit != "EN PISTA"`.
- `summary`: when `sessionSummary.active == true`.

## Required payload
- `connected`, `demo`
- `header.{car,track,driver,position,lap,state}`
- `self.{fuel,lastUse,bestUse,worstUse,lastLap,bestLap,laps,wear,pit,pitWindow,nextStop}`
- `lastLapSummary`
- `relative[]`
- `standing[]`
- `coach.trackMap.{points,markers}` when a trace is available

Timing rows can include `brand`, `classId`, `className`, and `classPos`.
Lap rows can include `consumption`.

## Performance
Unchanged DOM text is not rewritten; timing/lap rows are rebuilt only when their data changes; hidden screens are not rendered every WebSocket tick; no UI framework is used.
