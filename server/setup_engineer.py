"""Setup Engineer orchestration for ZRE.

This layer consumes bounded post-lap summaries. It does not poll the SDK and it
does not duplicate raw telemetry capture.
"""
from datetime import datetime
from pathlib import Path
import math

try:
    from server.setup_snapshot import compare_setups
    from server.setup_report import write_setup_report
    from server.stint_store import StintStore, slug
except ModuleNotFoundError:
    from setup_snapshot import compare_setups
    from setup_report import write_setup_report
    from stint_store import StintStore, slug


def measured(value):
    return {"value": value, "source": "MEASURED"} if value is not None else {"value": None, "source": "UNAVAILABLE"}


def inferred(value):
    return {"value": value, "source": "INFERRED"} if value is not None else {"value": None, "source": "UNAVAILABLE"}


def _mean(values):
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(clean) / len(clean) if clean else None


def build_track_profile(engineering):
    zones = (engineering or {}).get("zones") or []
    if not zones:
        return {
            "highSpeed": inferred(None),
            "mediumSpeed": inferred(None),
            "lowSpeed": inferred(None),
            "heavyBraking": inferred(None),
            "tractionDemand": inferred(None),
            "directionChanges": inferred(None),
            "aeroSensitivity": inferred(None),
            "fullThrottleShare": measured(None),
        }

    total = len(zones)
    type_counts = {}
    for zone in zones:
        for kind in zone.get("types") or []:
            type_counts[kind] = type_counts.get(kind, 0) + 1

    def demand(kind):
        ratio = type_counts.get(kind, 0) / total
        return "HIGH" if ratio >= .45 else "MEDIUM" if ratio >= .20 else "LOW"

    throttle_share = _mean([z.get("fullThrottleShare") for z in zones])
    high_speed_ratio = type_counts.get("HIGH SPEED", 0) / total
    lat_peak = _mean([z.get("peakLatAccel") for z in zones])
    aero = None
    if high_speed_ratio >= .35 and lat_peak is not None:
        aero = "HIGH" if lat_peak >= 6.0 else "MEDIUM"
    elif high_speed_ratio >= .20:
        aero = "MEDIUM"
    elif high_speed_ratio >= 0:
        aero = "LOW"

    return {
        "highSpeed": inferred(demand("HIGH SPEED")),
        "mediumSpeed": inferred(demand("MEDIUM SPEED")),
        "lowSpeed": inferred(demand("LOW SPEED")),
        "heavyBraking": inferred(demand("HEAVY BRAKING")),
        "tractionDemand": inferred(demand("TRACTION")),
        "directionChanges": inferred(demand("DIRECTION CHANGE")),
        "aeroSensitivity": inferred(aero),
        "fullThrottleShare": measured(round(throttle_share, 3) if throttle_share is not None else None),
    }


def build_repeated_behavior(engineering):
    repeated = []
    for item in (engineering or {}).get("repeatedBehavior") or []:
        total = item.get("sampleLaps")
        count = item.get("occurrences")
        ratio = item.get("repeatRatio")
        repeated.append({
            "location": item.get("zone"),
            "pattern": item.get("title"),
            "occurrences": count,
            "validLaps": total,
            "repeatRatio": f"{ratio*100:.0f}%" if isinstance(ratio, (int, float)) else ratio,
            "confidence": item.get("confidence"),
            "advice": item.get("advice"),
        })
    return repeated


def build_corner_analysis(engineering):
    rows = []
    for zone in (engineering or {}).get("zones") or []:
        row = {
            "zone": zone.get("corner") or f"Zone {zone.get('zone')}",
            "types": zone.get("types") or [],
            "entrySpeedKph": measured(zone.get("entrySpeedKph")),
            "minSpeedKph": measured(zone.get("minSpeedKph")),
            "exitSpeedKph": measured(zone.get("exitSpeedKph")),
            "brakeStartPct": measured(zone.get("brakeStartPct")),
            "maxBrake": measured(zone.get("maxBrake")),
            "brakeDuration": measured(zone.get("brakeDuration")),
            "brakeReleasePct": measured(zone.get("brakeReleasePct")),
            "maxSteeringDeg": measured(zone.get("maxSteeringDeg")),
            "steeringCorrections": measured(zone.get("steeringCorrections")),
            "throttleReturnPct": measured(zone.get("throttleReturnPct")),
            "throttleRampSeconds": measured(zone.get("throttleRampSeconds")),
            "peakYawRate": measured(zone.get("peakYawRate")),
            "peakLatAccel": measured(zone.get("peakLatAccel")),
            "minGear": measured(zone.get("minGear")),
            "fullThrottleShare": measured(zone.get("fullThrottleShare")),
            "averageZoneTime": measured(zone.get("averageZoneTime")),
        }
        rows.append(row)
    return rows


def compare_stint_performance(previous, current):
    old = (previous or {}).get("stintPerformance") or {}
    new = (current or {}).get("stintPerformance") or {}
    result = {}
    for key in ("bestLap", "representativeAverage", "lapStdDev", "fuelPerLap"):
        before, after = old.get(key), new.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            result[key] = {
                "before": round(before, 4),
                "after": round(after, 4),
                "delta": round(after - before, 4),
            }
    return result


class SetupEngineer:
    def __init__(self, root):
        self.root = Path(root)
        self.store = StintStore(self.root / "data" / "setup_engineer")
        self.current = None
        self.last_saved = None
        self.last_report_path = None
        self.status = "Esperando stint"

    def start_stint(self, session, setup_snapshot, conditions=None, fuel_start=None, session_time=None):
        self.current = {
            "startedAt": datetime.now().isoformat(timespec="seconds"),
            "session": dict(session or {}),
            "conditions": dict(conditions or {}),
            "setup": dict(setup_snapshot or {}),
            "fuelStart": fuel_start,
            "startSessionTime": session_time,
            "driverFeedback": {},
        }
        setup_name=(setup_snapshot or {}).get("metadata",{}).get("setupName")
        self.status=f"Stint en curso · {setup_name or (setup_snapshot or {}).get('fingerprint') or 'setup sin identificar'}"
        return self.current

    def set_feedback(self, entry=None, mid=None, exit=None, comment=None):
        if self.current is None:
            return False
        feedback = self.current.setdefault("driverFeedback", {})
        for key, value in (("entry", entry), ("mid", mid), ("exit", exit)):
            if value in ("SUELTO", "NEUTRO", "SUBVIRA"):
                feedback[key] = value
        if comment is not None:
            feedback["comment"] = str(comment).strip()[:1000]
        return True

    def finish_stint(self, engineering, fuel_end=None, session_time=None, fuel_per_lap=None):
        if self.current is None:
            return None
        base = self.current
        session = base.get("session") or {}
        setup = base.get("setup") or {}
        start_time = base.get("startSessionTime")
        duration = None
        if isinstance(start_time, (int, float)) and isinstance(session_time, (int, float)):
            duration = max(0.0, session_time - start_time)

        valid_laps = int((engineering or {}).get("validLaps") or 0)
        if fuel_per_lap is None and valid_laps>0 and isinstance(base.get("fuelStart"),(int,float)) and isinstance(fuel_end,(int,float)) and base.get("fuelStart")>=fuel_end:
            fuel_per_lap=(base.get("fuelStart")-fuel_end)/valid_laps
        performance = {
            "laps": valid_laps,
            "validLaps": valid_laps,
            "bestLap": (engineering or {}).get("bestLap"),
            "optimalLap": (engineering or {}).get("optimalLap"),
            "representativeAverage": (engineering or {}).get("representativeAverage"),
            "lapStdDev": (engineering or {}).get("lapStdDev"),
            "fuelStart": base.get("fuelStart"),
            "fuelEnd": fuel_end,
            "fuelPerLap": fuel_per_lap,
            "stintDurationSeconds": round(duration, 1) if duration is not None else None,
        }

        record = {
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "session": session,
            "conditions": base.get("conditions") or {},
            "trackProfile": build_track_profile(engineering),
            "setup": setup,
            "stintPerformance": performance,
            "corners": build_corner_analysis(engineering),
            "balancePatterns": {},
            "repeatedBehavior": build_repeated_behavior(engineering),
            "driverFeedback": base.get("driverFeedback") or {},
            "comparison": {},
            "setupEngineerSummary": [],
            "dataQuality": {
                "validLaps": valid_laps,
                "cornerModelCount": len((engineering or {}).get("corners") or []),
                "zonesAnalyzed": len((engineering or {}).get("zones") or []),
                "setupSource": setup.get("source"),
                "setupAvailable": bool(setup.get("parameters")),
                "telemetrySource": "LAP_COACH_SUMMARY",
            },
        }

        previous = self.store.previous_stint(
            session.get("car"), session.get("track"), session.get("layout")
        )
        changes = compare_setups((previous or {}).get("setup"), setup) if previous else []
        record["setupChanges"] = changes
        if previous:
            record["comparison"] = compare_stint_performance(previous, record)

        self.store.save_setup(session.get("car"), session.get("track"), session.get("layout"), setup)
        self.store.save_track_profile(session.get("car"), session.get("track"), session.get("layout"), record["trackProfile"])
        path = self.store.save_stint(record)
        saved = self.store._read_json(path, record)
        self.current = None
        self.last_saved = saved
        self.last_report_path = None
        self.status=f"Stint {saved.get('stintNumber')} guardado · feedback pendiente"
        return saved

    def update_feedback(self, stint, entry=None, mid=None, exit=None, comment=None):
        if not isinstance(stint, dict):
            return None
        feedback = dict(stint.get("driverFeedback") or {})
        for key, value in (("entry", entry), ("mid", mid), ("exit", exit)):
            if value in ("SUELTO", "NEUTRO", "SUBVIRA"):
                feedback[key] = value
        if comment is not None:
            feedback["comment"] = str(comment).strip()[:1000]
        stint["driverFeedback"] = feedback
        session = stint.get("session") or {}
        path = self.store.save_stint(stint)
        self.last_saved = self.store._read_json(path, stint)
        self.status=f"Stint {self.last_saved.get('stintNumber')} · feedback guardado"
        return self.last_saved

    def export_report(self, stint=None):
        record = stint or self.last_saved
        if not record:
            return None
        session = record.get("session") or {}
        number = int(record.get("stintNumber") or 0)
        filename = "ZRE_SETUP_REPORT_{}_{}_Stint{:02d}.md".format(
            slug(session.get("car")),
            slug(session.get("track")),
            number,
        )
        path = self.root / "reports" / filename
        previous = self.store.previous_stint(
            session.get("car"), session.get("track"), session.get("layout"),
            before_number=number,
        )
        result=write_setup_report(path, record, previous, record.get("setupChanges"))
        self.last_report_path=result
        self.status=f"Reporte exportado · {result.name}"
        return result
