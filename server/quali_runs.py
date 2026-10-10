"""Lightweight qualifying runs linked to existing SDK laps and SessionRecorder.

Never changes SessionType, Coach data, or the SDK. One backend authority serves
all web clients. Unknown lap legality is never promoted to an official valid lap.
"""
from datetime import datetime, timezone
from uuid import uuid4
import math


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


class QualiRuns:
    def __init__(self, recorder=None):
        self.recorder = recorder
        self.identity = None
        self.official_type = None
        self.mode = None
        self.runs = []
        self.current = None
        self.lap = None
        self.pct = None
        self.clock = None
        self.generation = 0
        self.last_error = None

    @staticmethod
    def classify(official_type):
        value = str(official_type or "").strip().lower()
        if "qual" in value:
            return "qualifying"
        if "practice" in value:
            return "practice"
        if "race" in value:
            return "race"
        return "other"

    def _event(self, event, **fields):
        if self.recorder is not None:
            self.recorder.write({"type": "quali_" + event, "sessionTime": self.clock,
                                 "sessionIdentity": self.identity, **fields})

    def _close(self, reason):
        if not self.current or self.current["status"] != "ACTIVE":
            return
        self.current["status"] = "CLOSED"
        self.current["endedAt"] = datetime.now(timezone.utc).isoformat()
        self.current["endLap"] = self.lap
        self._event("run_end", runId=self.current["runId"], reason=reason)
        self.current = None

    def close_session(self, reason="session-change"):
        self._close(reason)
        self.mode = None
        self.last_error = None

    def observe(self, identity, official_type, lap, pct, clock):
        key = str(identity)
        new_kind = self.classify(official_type)
        self.lap = int(float(lap)) if finite(lap) is not None and float(lap) >= 0 else None
        self.pct = finite(pct)
        self.clock = finite(clock)
        if key != self.identity or new_kind != self.official_type:
            self.close_session("sdk-session-change")
            self.identity = key
            self.official_type = new_kind
            if new_kind == "qualifying":
                self.mode = "official"
                self._start("official")
        if new_kind in ("race", "other"):
            self.close_session("official-mode-priority")
        return self.snapshot()

    def _start(self, kind):
        self.generation += 1
        run_id = "Q" + uuid4().hex[:12]
        # Mid-lap activation: first complete source lap may have begun earlier.
        # Require NEXT full SDK lap after arming to count.
        gate = self.lap + 1 if self.lap is not None else 1
        run = {"runId": run_id, "officialSessionIdentity": self.identity,
               "kind": kind, "startedAt": datetime.now(timezone.utc).isoformat(),
               "endedAt": None, "startLap": gate, "endLap": None,
               "status": "ACTIVE", "attempts": [], "bestValidLap": None,
               "gateLap": gate, "generation": self.generation}
        self.runs.append(run)
        self.runs = self.runs[-100:]
        self.current = run
        self._event("run_start", runId=run_id, kind=kind, gateLap=gate)
        return run

    def command(self, action):
        self.last_error = None
        if self.official_type != "practice":
            self.last_error = "Alternancia exclusiva de Practice oficial"
            return False
        if action == "training":
            self._close("manual-training")
            self.mode = None
            return True
        if action == "simulate":
            if self.mode == "simulated" and self.current:
                return True
            self._close("new-manual-mode")
            self.mode = "simulated"
            self._start("simulated")
            return True
        if action == "new_run" and self.mode == "simulated":
            self._close("new-run")
            self._start("simulated")
            return True
        self.last_error = "Acción no permitida en el modo actual"
        return False

    def note_lap(self, lap, seconds, *, clean=None, sdk_best=False,
                 sectors=None, sector_source=None, in_pit=False, source="SDK_OBSERVED"):
        run = self.current
        lap = int(float(lap)) if finite(lap) is not None else None
        measured = finite(seconds)
        if not run or lap is None or measured is None or measured <= 0:
            return None
        if lap <= run["gateLap"] or any(a["sourceLap"] == lap for a in run["attempts"]):
            return None
        # Prioritize direct SDK fastest-lap confirmation. A clean ZRE estimate
        # alone is not proof of official iRacing lap legality.
        status = "VALID" if sdk_best else "IN LAP" if in_pit else "PENDING VALIDATION"
        evidence = "SDK_BEST_CONFIRMED" if sdk_best else "ZRE_CLEAN_ESTIMATE" if clean is True else "ZRE_DIRTY_OBSERVED" if clean is False else "UNKNOWN"
        sector_times = [float(v) for v in (sectors or []) if finite(v) is not None and v > 0]
        attempt = {"attemptId": run["runId"] + "-L" + str(lap), "runId": run["runId"],
                   "sourceLap": lap, "status": status, "lapTime": round(measured, 4),
                   "validity": evidence, "sectorTimes": sector_times,
                   "sectorSource": sector_source if sector_times else "UNAVAILABLE",
                   "source": source, "confidence": "HIGH" if sdk_best else "LOW"}
        run["attempts"].append(attempt)
        del run["attempts"][:-2000]
        if status == "VALID" and (run["bestValidLap"] is None or measured < run["bestValidLap"]):
            run["bestValidLap"] = round(measured, 4)
        self._event("attempt", **attempt)
        return attempt

    def snapshot(self):
        active = self.current
        previous = [r for r in self.runs if r is not active and
                    r["officialSessionIdentity"] == self.identity]
        attempts = active["attempts"] if active else []
        return {"officialSessionIdentity": self.identity,
                "officialSessionType": self.official_type,
                "qualifyingMode": self.mode,
                "effectiveDashboard": ("quali" if self.mode else self.official_type),
                "manualOverrideActive": self.mode == "simulated",
                "activeRunId": active["runId"] if active else None,
                "activeAttemptId": attempts[-1]["attemptId"] if attempts else None,
                "activeRun": self._public(active) if active else None,
                "previousRuns": [self._public(r) for r in previous[-12:]],
                "lastError": self.last_error}

    @staticmethod
    def _public(run):
        if not run:
            return None
        items = run["attempts"]
        return {k: v for k, v in run.items() if k not in ("gateLap", "generation", "attempts")} | {
            "attemptIds": [a["attemptId"] for a in items],
            "attempts": [dict(a) for a in items[-120:]],
            "counts": {key: sum(a["status"] == key for a in items) for key in
                       ("VALID", "INVALID", "PENDING VALIDATION", "OUT LAP", "IN LAP", "INCOMPLETE")}}
