# ZRE Core — UI payload contract

## v2.3.0 live screen
- Top: Reference, Tyres, Fuel, Pit.
- Middle: Strategic Rival + Endurance Strategy/Stints.
- Bottom: persistent stint loss map, selectable Relative/Class Standings, pace history.
- Timing renders seven visual slots with the player in slot 4 when present.

## raceDirector
`mode`, `selectedIdx`, `candidates[]`, `rival`, `position`, `gap`, `lastLap`, `pit`, `lap`, `status`.
AUTO is class-only; the UI may send `settings:rival` with a CarIdx.

## enduranceStrategy
`available`, `state`, `verdict`, `remainingTime`, `currentStint`, `currentDriver`, `boxLap`, `autonomy`, `stopsRemaining`, `lastStopAvoidable`, `extensionNeeded`, `extensionAvailable`, `extensionText`, `targetThisStint`.
Also includes `base`, `extended`, `timeline[]` and `settings`.

## Web update
`appVersion` is read dynamically from installed `version.json`. The page also checks `GET /version` every five seconds. The updater writes `version.json` last, so a browser reload cannot observe a half-installed HTML/JS/CSS build.
