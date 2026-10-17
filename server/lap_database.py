"""Persistent car-lap ledger and conservative fuel projection for ZRE.
Real laps are SDK observations; fuel is independently measured, manual, or estimated.
No predicted consumption is ever fed back into the calibration sample set.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
import time
from pathlib import Path

KINDS = ("Normal", "Entrada box", "Salida box")


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def at(values, idx):
    return values[idx] if isinstance(values, (list, tuple)) and isinstance(idx, int) and 0 <= idx < len(values) else None


class LapDatabase:
    def __init__(self, root):
        target = Path(root) / "data" / "lap_history.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(target), timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS laps (
          race TEXT NOT NULL, car_idx INTEGER NOT NULL, lap INTEGER NOT NULL,
          car_number TEXT, driver TEXT, lap_time REAL, kind TEXT NOT NULL,
          source TEXT NOT NULL, observed_at REAL NOT NULL,
          PRIMARY KEY (race, car_idx, lap)
        );
        CREATE TABLE IF NOT EXISTS fuel_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, race TEXT NOT NULL,
          car_idx INTEGER NOT NULL, lap INTEGER NOT NULL,
          remaining REAL NOT NULL, source TEXT NOT NULL, recorded_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS fuel_latest ON fuel_events(race, car_idx, lap, id);
        CREATE TABLE IF NOT EXISTS race_meta (
          race TEXT PRIMARY KEY, last_seen_utc REAL NOT NULL,
          protected INTEGER NOT NULL DEFAULT 0
        );
        """)
        # Existing rows predate metadata; grant a fresh seven-day grace
        # rather than treating SDK SessionTime as wall-clock time.
        self.db.execute(
            "INSERT OR IGNORE INTO race_meta(race,last_seen_utc) "
            "SELECT DISTINCT race,? FROM laps", (time.time(),))
        self.race = None
        self.car_seen = {}
        self.pit_seen = {}
        self.pit_pending = {}
        self.last_snapshot = {}
        self.snapshot_time = 0
        self.team_idx = None
        self._last_touch = 0.0
        self._last_maintenance = time.time()
        self.cleanup_expired(now=self._last_maintenance)

    def close(self):
        self.db.close()

    def cleanup_expired(self, now=None, retention_days=7):
        """Purge only completed-by-inactivity, unprotected, NON-current races.
        Use wall-clock UTC, never the SDK SessionTime that resets each session.
        Protected historical sessions are not deleted.
        """
        now = time.time() if now is None else float(now)
        cutoff = now - max(1, int(retention_days)) * 86400
        expired = [row[0] for row in self.db.execute(
            "SELECT race FROM race_meta WHERE last_seen_utc<? AND protected=0",
            (cutoff,)) if row[0] != self.race]
        with self.db:
            for race in expired:
                self.db.execute("DELETE FROM fuel_events WHERE race=?", (race,))
                self.db.execute("DELETE FROM laps WHERE race=?", (race,))
                self.db.execute("DELETE FROM race_meta WHERE race=?", (race,))
        return len(expired)

    def protect(self, race, enabled=True):
        self.db.execute(
            "UPDATE race_meta SET protected=? WHERE race=?",
            (1 if enabled else 0, str(race)))

    def _touch(self, now):
        if now - self._last_touch >= 60 or not self._last_touch:
            self.db.execute(
                "INSERT INTO race_meta(race,last_seen_utc) VALUES(?,?) "
                "ON CONFLICT(race) DO UPDATE SET last_seen_utc=excluded.last_seen_utc",
                (self.race, now))
            self._last_touch = now

    def observe(self, race, get, drivers, team_idx, local_driving=False,
                tank=None, consumption=None, pace=None, plan=None, rival_idx=None,
                session_time=None, results=None, team_car_number=None):
        if not race:
            return {"available": False, "reason": "SIN IDENTIDAD DE SESIÓN"}
        if self.race != str(race):
            self.race = str(race)
            self._last_touch = 0
            self.car_seen.clear()
            self.pit_seen.clear()
            self.pit_pending.clear()
            self.last_snapshot = {}
            self.snapshot_time = 0
        now = time.time()
        self._touch(now)
        if now - self._last_maintenance >= 3600:
            self.cleanup_expired(now=now)
            self._last_maintenance = now
        self.team_idx = team_idx
        roster = {d.get("CarIdx"): d for d in drivers or []
                  if isinstance(d, dict) and isinstance(d.get("CarIdx"), int)
                  and not d.get("IsSpectator")}
        # SessionInfo.ResultsPositions tracks car laps even while the local
        # DriverInfo roster / per-car SDK arrays lag during a driver handoff.
        # It is a distinct SDK source, never an extrapolated lap counter.
        valid_results = {idx: row for idx, row in (results or {}).items()
                         if isinstance(idx, int) and idx >= 0 and isinstance(row, dict)}
        if (isinstance(team_idx, int) and team_idx >= 0
                and team_idx not in roster and team_car_number is not None):
            roster[team_idx] = {"CarIdx": team_idx,
                                "CarNumber": str(team_car_number),
                                "UserName": None}
        completed = get("CarIdxLapCompleted", []) or []
        times = get("CarIdxLastLapTime", []) or []
        pits = get("CarIdxOnPitRoad", []) or []
        stamp = number(session_time) if number(session_time) is not None else time.time()
        changed = False
        for idx, car in roster.items():
            sdk_raw = number(at(completed, idx))
            sdk_lap = int(sdk_raw) if sdk_raw is not None and sdk_raw >= 0 else None
            official = valid_results.get(idx) or {}
            result_raw = number(official.get("LapsComplete"))
            result_lap = int(result_raw) if result_raw is not None and result_raw >= 0 else None
            if sdk_lap is None and result_lap is None:
                continue
            use_results = result_lap is not None and (
                sdk_lap is None or result_lap > sdk_lap)
            lap = result_lap if use_results else sdk_lap
            pit = at(pits, idx) if not use_results else None
            # The SDK pit flag may remain frozen at True through the handoff.
            # Clear its pending edge; do not classify an advancing official lap
            # as another pit entry from stale old-driver telemetry.
            if use_results:
                self.pit_pending.pop(idx, None)
                self.pit_seen.pop(idx, None)
            last_pit = self.pit_seen.get(idx)
            if isinstance(pit, bool):
                if last_pit is not None and pit != last_pit:
                    self.pit_pending[idx] = "Entrada box" if pit else "Salida box"
                self.pit_seen[idx] = pit
            previous = self.car_seen.get(idx)
            driver = str(car.get("UserName") or "")[:100] or None
            car_number = str(car.get("CarNumber") or "")[:12] or None
            last_time = (positive(official.get("LastTime")) if use_results
                         else positive(at(times, idx)))
            if previous is None:
                row = self.db.execute(
                    "SELECT MAX(lap) FROM laps WHERE race=? AND car_idx=?",
                    (self.race, idx)).fetchone()
                previous = row[0] if row and row[0] is not None else lap - 1
                # On first connect only the latest lap time is known.
                if previous < lap - 1:
                    previous = lap - 1
            if lap > previous:
                if lap - previous > 1:
                    for missing in range(previous + 1, lap):
                        self._save_lap(idx, missing, car_number, None, None, "Normal",
                                       "SDK_MISSING", stamp)
                kind = self.pit_pending.pop(idx, None) or ("Entrada box" if pit is True else "Normal")
                self._save_lap(idx, lap, car_number, driver, last_time, kind,
                               ("RESULTS_OBSERVED" if last_time is not None else "RESULTS_NO_TIME")
                               if use_results else
                               ("SDK_OBSERVED" if last_time is not None else "SDK_NO_TIME"),
                               stamp)
                changed = True
                if idx == team_idx and local_driving and number(get("FuelLevel")) is not None:
                    fuel = number(get("FuelLevel"))
                    if 0 <= fuel <= 300 and (tank is None or fuel <= float(tank) + 0.5):
                        self._fuel_event(idx, lap, fuel, "REAL_LOCAL")
            self.car_seen[idx] = max(previous, lap)
        if changed or time.monotonic() - self.snapshot_time > 1.5 or not self.last_snapshot:
            self.last_snapshot = self.snapshot(team_idx, rival_idx, tank, consumption, pace, plan)
            self.snapshot_time = time.monotonic()
        return self.last_snapshot

    def _save_lap(self, idx, lap, car, driver, lap_time, kind, source, stamp):
        self.db.execute(
            """INSERT INTO laps (race,car_idx,lap,car_number,driver,lap_time,kind,source,observed_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(race,car_idx,lap) DO UPDATE SET
               car_number=COALESCE(excluded.car_number,laps.car_number),
               driver=COALESCE(excluded.driver,laps.driver),
               lap_time=COALESCE(excluded.lap_time,laps.lap_time),
               kind=CASE WHEN laps.source='SDK_MISSING' THEN excluded.kind ELSE laps.kind END,
               source=CASE WHEN excluded.lap_time IS NOT NULL THEN excluded.source ELSE laps.source END""",
            (self.race, idx, lap, car, driver, lap_time, kind, source, stamp))

    def _fuel_event(self, idx, lap, fuel, source):
        existing = self.db.execute(
            "SELECT remaining,source FROM fuel_events WHERE race=? AND car_idx=? AND lap=? ORDER BY id DESC LIMIT 1",
            (self.race, idx, lap)).fetchone()
        if existing and existing["source"] == "MANUAL" and source != "MANUAL":
            return  # Protect manual correction from SDK refresh; allow manual re-edits.
        if existing and existing["source"] == source and abs(existing["remaining"] - fuel) < 0.02:
            return
        self.db.execute("INSERT INTO fuel_events(race,car_idx,lap,remaining,source,recorded_at) VALUES(?,?,?,?,?,?)",
                        (self.race, idx, lap, round(fuel, 3), source, time.time()))

    def edit_fuel(self, lap, remaining, team_idx, tank=None):
        if self.race is None or team_idx is None or team_idx != self.team_idx:
            return "Coche del equipo no identificado"
        try:
            lap = int(lap)
            fuel = float(remaining)
        except (ValueError, TypeError):
            return "Vuelta o combustible inválido"
        if lap < 0 or not math.isfinite(fuel) or fuel < 0 or fuel > 300:
            return "Cantidad o vuelta fuera de rango"
        if positive(tank) is not None and fuel > float(tank) + .5:
            return "El combustible supera la capacidad del depósito"
        exists = self.db.execute("SELECT 1 FROM laps WHERE race=? AND car_idx=? AND lap=?",
                                 (self.race, team_idx, lap)).fetchone()
        if not exists:
            return "Solo se puede editar una vuelta real registrada"
        self._fuel_event(team_idx, lap, fuel, "MANUAL")
        self.last_snapshot = {}
        return None

    def _rows(self, car_idx):
        if car_idx is None or self.race is None:
            return []
        values = self.db.execute(
            """SELECT lap,car_number,driver,lap_time,kind,source FROM laps
               WHERE race=? AND car_idx=? ORDER BY lap ASC""",
            (self.race, car_idx)).fetchall()
        return [dict(row) for row in values]

    def _anchors(self, idx):
        if idx is None or self.race is None:
            return []
        rows = self.db.execute(
            """SELECT f.lap,f.remaining,f.source FROM fuel_events f
               WHERE f.race=? AND f.car_idx=? AND f.id=(
                 SELECT MAX(x.id) FROM fuel_events x
                 WHERE x.race=f.race AND x.car_idx=f.car_idx AND x.lap=f.lap)
               ORDER BY f.lap""", (self.race, idx)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _models(rows, anchors, baseline):
        by_lap = {r["lap"]: r for r in rows}
        samples = {kind: [] for kind in KINDS}
        # A multi-lap calibration is ONE interval, never N independent fuel readings.
        for a, b in zip(anchors, anchors[1:]):
            distance = b["lap"] - a["lap"]
            if distance <= 0 or a["remaining"] < b["remaining"]:
                continue  # Unknown refuel; no training across a refuel.
            section = [by_lap.get(n) for n in range(a["lap"] + 1, b["lap"] + 1)]
            if any(r is None or r["source"] == "SDK_MISSING" for r in section):
                continue
            kinds = {r["kind"] for r in section}
            if len(kinds) != 1 or (distance > 1 and kinds != {"Normal"}):
                continue
            kind = section[0]["kind"]
            rate = (a["remaining"] - b["remaining"]) / distance
            if 0 < rate < 30:
                samples[kind].append({"endLap": b["lap"], "rate": rate, "laps": distance})
        averages = {}
        for kind in KINDS:
            # Last TEN laps of that same kind, weighted across distinct calibration intervals.
            total = count = 0
            for sample in reversed(samples[kind]):
                take = min(10 - count, sample["laps"])
                total += sample["rate"] * take
                count += take
                if count >= 10:
                    break
            averages[kind] = round(total / count, 4) if count else None
        if averages["Normal"] is None:
            averages["Normal"] = positive(baseline)
        return averages, samples

    def snapshot(self, team_idx, rival_idx, tank=None, consumption=None, pace=None, plan=None):
        own = self._rows(team_idx)
        rival = self._rows(rival_idx) if rival_idx != team_idx else []
        anchors = self._anchors(team_idx)
        averages, evidence = self._models(own, anchors, consumption)
        by_anchor = {a["lap"]: a for a in anchors}
        fuel = None
        last_anchor = None
        # Real rows have historical fuel projections until the next calibration.
        for row in own:
            if row["lap"] in by_anchor:
                last_anchor = by_anchor[row["lap"]]
                fuel = last_anchor["remaining"]
                row["fuelSource"] = last_anchor["source"]
            elif fuel is not None and row["kind"] == "Normal" and averages["Normal"]:
                fuel = max(0, fuel - averages["Normal"])
                row["fuelSource"] = "ESTIMADO"
            else:
                if row["kind"] != "Normal":
                    fuel = None  # Do not carry fuel across an unverified pit.
                row["fuelSource"] = "SIN_DATO"
            row["remaining"] = round(fuel, 2) if fuel is not None else None
            row["avgConsumption"] = averages.get(row["kind"])
            row["state"] = "REAL"
        # Projections are ephemeral; no forecast becomes an observed lap.
        projected = []
        if own and fuel is not None and positive(averages["Normal"]) is not None:
            last_lap = own[-1]["lap"]
            rate = averages["Normal"]
            cap = positive(tank)
            stops = list((plan or {}).get("stops") or [])
            stop_idx = 0
            pace_sec = positive(pace)
            n = last_lap + 1
            while n <= last_lap + 60:
                next_stop = stops[stop_idx] if stop_idx < len(stops) else {}
                target = next_stop.get("lap")
                target = int(target) if isinstance(target, (int, float)) else None
                # A plan must never override a safer fuel-limited entry.
                enter = (target is not None and n >= target) or fuel - rate < 2 * rate
                kind = "Entrada box" if enter else "Normal"
                use = averages.get(kind) or rate
                if fuel < use:
                    break
                fuel = max(0, fuel - use)
                projected.append({
                    "lap": n, "car_number": own[-1]["car_number"],
                    "driver": None, "lap_time": pace_sec,
                    "kind": kind, "source": "ZRE_PROJECTION",
                    "remaining": round(fuel, 2), "avgConsumption": round(use, 4),
                    "fuelSource": "ESTIMADO", "state": "PROYECTADO"})
                if enter:
                    action = str(next_stop.get("fuelAction") or "")
                    liters = number(next_stop.get("liters"))
                    if action in ("auto", "fill") and cap is not None:
                        after = cap
                    elif action == "add" and liters is not None and liters >= 0:
                        after = min(cap, fuel + liters) if cap else fuel + liters
                    elif action == "none":
                        after = fuel
                    else:
                        after = None
                    n += 1
                    out_use = averages["Salida box"] or rate
                    fuel = max(0, after - out_use) if after is not None and after >= out_use else None
                    projected.append({
                        "lap": n, "car_number": own[-1]["car_number"],
                        "driver": None, "lap_time": pace_sec,
                        "kind": "Salida box", "source": "ZRE_PROJECTION",
                        "remaining": round(fuel, 2) if fuel is not None else None,
                        "avgConsumption": round(out_use, 4),
                        "fuelSource": "ESTIMADO" if fuel is not None else "SIN_DATO",
                        "state": "PROYECTADO"})
                    stop_idx += 1
                    if fuel is None or fuel <= 0:
                        break
                n += 1
        return {"available": True, "race": self.race, "teamCarIdx": team_idx,
                "rivalCarIdx": rival_idx, "team": own, "rival": rival,
                "projected": projected, "averages": averages,
                "fuelEvidenceCount": {k: len(v) for k, v in evidence.items()},
                "lastManualLap": max((a["lap"] for a in anchors if a["source"] == "MANUAL"), default=None)}


class UnavailableLapDatabase:
    """Fail-open for dashboard operation, fail-closed for historical fuel edits.

    An unavailable SQLite DB must not prevent the live iRacing dashboard or
    other established screens from starting.
    """
    race = None
    team_idx = None

    def __init__(self, reason="Historial no disponible · almacenamiento local"):
        self.reason = reason

    def observe(self, *args, **kwargs):
        return {"available": False, "reason": self.reason}

    def edit_fuel(self, *args, **kwargs):
        return self.reason

    def close(self):
        return None
