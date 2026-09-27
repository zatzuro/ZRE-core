"""Low-frequency engineering snapshots taken only at stint transitions.

No polling loop is created here. The bridge calls these helpers at stint start
and finish using the SDK getter it already owns.
"""
import math


WHEELS = ("LF", "RF", "LR", "RR")


def _safe(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return value if isinstance(value, (bool, str)) else None


def _metric(getter, name):
    try:
        return _safe(getter(name))
    except Exception:
        return None


def capture_conditions(getter):
    track_temp = _metric(getter, "TrackTempCrew")
    if track_temp is None:
        track_temp = _metric(getter, "TrackTemp")
    return {
        "airTempC": _metric(getter, "AirTemp"),
        "trackTempC": track_temp,
        "relativeHumidity": _metric(getter, "RelativeHumidity"),
        "airPressure": _metric(getter, "AirPressure"),
        "airDensity": _metric(getter, "AirDensity"),
        "windSpeedMps": _metric(getter, "WindVel"),
        "windDirectionRad": _metric(getter, "WindDir"),
        "trackWetness": _metric(getter, "TrackWetness"),
        "weatherDeclaredWet": _metric(getter, "WeatherDeclaredWet"),
        "skies": _metric(getter, "Skies"),
    }


def capture_tires(getter):
    wheels = {}
    for wheel in WHEELS:
        wheels[wheel] = {
            "coldPressureKPa": _metric(getter, f"{wheel}coldPressure"),
            "carcassTempC": {
                "left": _metric(getter, f"{wheel}tempCL"),
                "middle": _metric(getter, f"{wheel}tempCM"),
                "right": _metric(getter, f"{wheel}tempCR"),
            },
            "wearRemainingPct": {
                "left": _metric(getter, f"{wheel}wearL"),
                "middle": _metric(getter, f"{wheel}wearM"),
                "right": _metric(getter, f"{wheel}wearR"),
            },
            "brakeLinePressBar": _metric(getter, f"{wheel}brakeLinePress"),
        }
    return {
        "source": "LIVE_SDK_TRANSITION_SNAPSHOT",
        "dynamicPressure": {"value": None, "source": "UNAVAILABLE_LIVE_SDK"},
        "wheels": wheels,
    }


def _delta(before, after, digits=3):
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return round(after - before, digits)
    return None


def compare_tires(start, end):
    start_wheels = (start or {}).get("wheels") or {}
    end_wheels = (end or {}).get("wheels") or {}
    result = {}
    for wheel in WHEELS:
        before = start_wheels.get(wheel) or {}
        after = end_wheels.get(wheel) or {}
        temp_before = before.get("carcassTempC") or {}
        temp_after = after.get("carcassTempC") or {}
        wear_before = before.get("wearRemainingPct") or {}
        wear_after = after.get("wearRemainingPct") or {}
        result[wheel] = {
            "coldPressureKPaDelta": _delta(before.get("coldPressureKPa"), after.get("coldPressureKPa")),
            "carcassTempCDelta": {
                part: _delta(temp_before.get(part), temp_after.get(part))
                for part in ("left", "middle", "right")
            },
            "wearRemainingDelta": {
                part: _delta(wear_before.get(part), wear_after.get(part), 5)
                for part in ("left", "middle", "right")
            },
        }
    return result


def snapshot_availability(tires):
    wheels = (tires or {}).get("wheels") or {}
    available = 0
    total = 0
    for wheel in WHEELS:
        data = wheels.get(wheel) or {}
        values = [
            data.get("coldPressureKPa"),
            *((data.get("carcassTempC") or {}).values()),
            *((data.get("wearRemainingPct") or {}).values()),
        ]
        for value in values:
            total += 1
            if value is not None:
                available += 1
    return {
        "availableFields": available,
        "expectedFields": total,
        "coverage": round(available / total, 3) if total else 0.0,
        "dynamicPressure": "UNAVAILABLE_LIVE_SDK",
    }
