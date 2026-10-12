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


# CarSetup is garage YAML (not continuous telemetry): LastHotPressure and
# LastTempsOMI/IMO are last inspected values. Left = O/M/I, Right = I/M/O.
# See iRacing SDK CarSetup.TiresAero definitions; no guessed update timestamp.
import re

GARAGE_WHEELS={"LF":("LeftFront","OMI"),"RF":("RightFront","IMO"),
               "LR":("LeftRear","OMI"),"RR":("RightRear","IMO")}


def _metric_number(value,unit=None):
    """Parse SDK YAML text units; report normalized values only if explicit."""
    if isinstance(value,(int,float)) and math.isfinite(float(value)):
        return float(value)
    if not isinstance(value,str):return None
    found=re.search(r"[-+]?\d+(?:[.,]\d+)?",value)
    if not found:return None
    amount=float(found.group(0).replace(",","."))
    text=value.lower()
    if unit=="kPa" and re.search(r"\bpsi\b",text):
        return round(amount*6.894757293,2)
    if unit=="C" and re.search(r"\d\s*°?f\b",text):
        return round((amount-32)*5/9,2)
    return amount if math.isfinite(amount) else None


def _segments(value,orientation,unit):
    if isinstance(value,(list,tuple)):parts=list(value)
    elif isinstance(value,dict):
        # Some SDK wrappers expose named values, others retain a YAML string.
        names=["outside","middle","inside"] if orientation=="OMI" else ["inside","middle","outside"]
        parts=[value.get(x) for x in names]
    elif isinstance(value,str):
        parts=re.findall(r"[-+]?\d+(?:[.,]\d+)?\s*(?:°?[CF]|kPa|psi|%)?",value,re.I)
    else:parts=[]
    if len(parts)!=3:return {}
    order=["outside","middle","inside"] if orientation=="OMI" else ["inside","middle","outside"]
    numbers=[_metric_number(x,unit) for x in parts]
    if any(x is None for x in numbers):return {}
    if unit=="pct":
        if not all(0<=x<=100 for x in numbers):return {}
    elif unit=="C":
        if not all(-50<x<250 for x in numbers):return {}
    return dict(zip(order,numbers))


def capture_garage_tires(car_setup,session_time=None):
    """Inspect *local* CarSetup.TiresAero; not a current racing temperature.

    The snapshot is always PROVISIONAL until SetupEngineer can correlate a
    changed inspection to a finished, authorized stint.
    """
    data=car_setup if isinstance(car_setup,dict) else {}
    aero=data.get("TiresAero") or {}
    if not isinstance(aero,dict):aero={}
    wheels={}
    for wheel,(key,orientation) in GARAGE_WHEELS.items():
        raw=aero.get(key) or {}
        if not isinstance(raw,dict):raw={}
        wheel_data={
            "coldPressureKPa":_metric_number(raw.get("ColdPressure") or raw.get("StartingPressure"),"kPa"),
            "lastHotPressureKPa":_metric_number(raw.get("LastHotPressure"),"kPa"),
            "lastTempsC":_segments(raw.get("LastTemps"+orientation),orientation,"C"),
            "treadRemainingPct":_segments(raw.get("TreadRemaining"),orientation,"pct"),
            "physicalOrder":orientation,
            "measurementSource":"CARSETUP_LAST_INSPECTION"
        }
        wheels[wheel]=wheel_data
    fields=sum(int(d["lastHotPressureKPa"] is not None)+len(d["lastTempsC"])+len(d["treadRemainingPct"]) for d in wheels.values())
    return {"source":"CARSETUP_LAST_INSPECTION","state":"PROVISIONAL",
            "sessionTimeObserved":session_time,
            "updateCount":data.get("UpdateCount"),"wheels":wheels,
            "availableFields":fields,
            "freshness":"NOT_VERIFIED","dynamicPressure":{"value":None,"source":"UNAVAILABLE_LIVE_SDK"}}


def garage_signature(snapshot):
    """Measured values only, without timestamps or setup edits."""
    wheels=(snapshot or {}).get("wheels") or {}
    return tuple((wheel,(wheels.get(wheel) or {}).get("lastHotPressureKPa"),
                  tuple(sorted(((wheels.get(wheel) or {}).get("lastTempsC") or {}).items())),
                  tuple(sorted(((wheels.get(wheel) or {}).get("treadRemainingPct") or {}).items())))
                 for wheel in WHEELS)


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
