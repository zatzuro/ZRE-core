"""Read-only Carrera V2 view model built from existing official and observed inputs.

NO extra SDK capture, no alternate strategy/fuel/recorder implementation.
Official standings, physical neighbors, lap pace, and strategy are kept
separate. All dynamic gaps are explicitly estimates, never official gaps.
"""
from __future__ import annotations

from math import isfinite


def numeric(value, positive=False):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if isfinite(n) and (not positive or n > 0) else None


def array_value(items, index):
    return items[index] if isinstance(items, (list, tuple)) and isinstance(index, int) and 0 <= index < len(items) else None


def clean_history(raw, clean, *, own=False):
    """Eight source laps, marked comparable only when already accepted by ZRE."""
    records = list(raw or [])[-8:]
    clean_ids = {row.get("lap") for row in (clean or []) if row.get("lap") is not None}
    samples = []
    for row in records:
        elapsed = numeric(row.get("time"), positive=True)
        lap = row.get("lap")
        if elapsed is None or lap is None:
            continue
        comparable = (bool(row.get("valid")) if own else lap in clean_ids)
        reason = ("ZRE_CLEAN_LOCAL" if own else "ZRE_COMPARABLE_FILTER") if comparable else (
            row.get("comparabilityReason") or "NOT_CONFIRMED_COMPARABLE")
        samples.append({"lapNumber": lap, "lapTimeSeconds": round(elapsed, 4),
                        "sessionTime": row.get("sessionTime"),
                        "comparable": comparable, "comparabilityReason": reason,
                        "source": row.get("source") or "SDK_OBSERVED",
                        "observedAt": row.get("sessionTime"),
                        "driverName": row.get("driverName")})
    last_five = [row["lapTimeSeconds"] for row in samples if row["comparable"]][-5:]
    # Fewer than three: samples remain visible, no representative average.
    mean = sum(last_five) / len(last_five) if len(last_five) >= 3 else None
    return {"samples": samples, "recentAverageSeconds": round(mean, 4) if mean is not None else None,
            "sampleCount": len(last_five), "representative": len(last_five) >= 3,
            "source": "ZRE_COMPARABLE_FILTER", "label": "COMPARABLE · NO CONFIRMACIÓN OFICIAL"}


def physical_neighbor(row):
    if not row or row.get("presence") != "LIVE" or row.get("onPitRoad") is True:
        return None
    frac = numeric(row.get("relativeLapFraction"))
    if frac is None or abs(frac) < 1e-9:
        return None
    evidence = row.get("gapEvidence") or {}
    val = numeric(evidence.get("seconds"))
    # Do not produce any seconds from class position or pace difference.
    return {"carIdx": row.get("carIdx"), "carNumber": row.get("number"),
            "driverName": row.get("driver") if row.get("driver") != "—" else None,
            "relativeLapFraction": frac, "gapSeconds": abs(val) if val is not None else None,
            "gapLabel": ("≈ " + f"{abs(val):.2f}" + " s · EST." if val is not None else "EST. SIN DATO"),
            "gapSource": evidence.get("source") if val is not None else "TRACK_FRACTION_ONLY",
            "gapConfidence": evidence.get("confidence") if val is not None else "UNAVAILABLE",
            "observationState": row.get("presence"), "sameClass": row.get("sameClass")}


def race_view(*, session_identity, own_idx, class_rows, results, cars, best_laps, last_laps,
              intelligence, own_history, director, fuel, fuel_history, race_plan,
              session_time=None):
    intel = intelligence or {}
    competitors = (intel.get("competitors") or {}).get("observed") or []
    by_car = {row["carIdx"]: row for row in competitors if row.get("carIdx") is not None}
    official = []
    own_class = None
    for row in class_rows or []:
        idx = row.get("idx")
        if idx is None:
            continue
        obs = by_car.get(idx) or {}
        result = results.get(idx) or {}
        sdk_best = numeric(array_value(best_laps, idx), positive=True) if obs.get("presence") == "LIVE" or idx == own_idx else None
        sdk_last = numeric(array_value(last_laps, idx), positive=True) if obs.get("presence") == "LIVE" or idx == own_idx else None
        best = sdk_best or numeric(result.get("FastestTime"), positive=True) or numeric(obs.get("bestLap"), positive=True)
        last = sdk_last or numeric(result.get("LastTime"), positive=True) or numeric(obs.get("lastLap"), positive=True)
        pos = row.get("classPos")
        position_source = row.get("positionSource") or "RESULTS_POSITIONS"
        raw_position = result.get("ClassPosition")
        if raw_position is not None and isinstance(raw_position, int) and raw_position >= 0:
            position_source = "RESULTS_POSITIONS"
        elif pos is not None:
            position_source = "CARIDX_CLASS_POSITION_FALLBACK"
        else:
            position_source = "UNAVAILABLE"
        entry = {"carIdx": idx, "carNumber": row.get("number"), "driverName": row.get("driver"),
                 "carModel": row.get("car"), "teamName": row.get("team"),
                 "classId": row.get("classId"), "officialClassPosition": pos if position_source == "RESULTS_POSITIONS" else None,
                 "classPosition": pos, "overallPosition": result.get("Position"),
                 "positionSource": position_source, "bestLapSeconds": best, "lastLapSeconds": last,
                 "timingSource": "CARIDX_LIVE" if sdk_last is not None else "RESULTS_OR_LAST_VALID",
                 "lastSeenSessionTime": obs.get("lastSeenSessionTime"),
                 "lastSeenAgo": obs.get("lastSeenAgo"), "presence": obs.get("presence") or "UNKNOWN",
                 "isPlayer": idx == own_idx, "identityAmbiguous": row.get("driver") in (None, "—")}
        official.append(entry)
        if idx == own_idx:
            own_class = entry
    official.sort(key=lambda row: (row["classPosition"] is None,
                                    row["classPosition"] if row["classPosition"] is not None else 99999,
                                    row["carIdx"]))

    traffic = (intel.get("traffic") or {}).get("observed") or {}
    ahead = physical_neighbor(traffic.get("nearestAhead"))
    behind = physical_neighbor(traffic.get("nearestBehind"))
    if ahead and ahead.get("relativeLapFraction", 0) <= 0:
        ahead = None
    if behind and behind.get("relativeLapFraction", 0) >= 0:
        behind = None

    selection = director or {}
    rival_idx = selection.get("requestedCarIdx") if selection.get("selectionMode") == "manual" else selection.get("selectedIdx")
    if rival_idx is None:
        rival_idx = selection.get("selectedIdx")
    car_choices = [r for r in official if not r["isPlayer"]]
    selected_row = next((r for r in official if r["carIdx"] == rival_idx and not r["isPlayer"]), None)
    selected_obs = by_car.get(rival_idx)
    role_ids = {"YOU": own_idx,
                "AHEAD": ahead["carIdx"] if ahead else None,
                "BEHIND": behind["carIdx"] if behind else None,
                "RIVAL": rival_idx if selected_row or selection.get("selectionMode") == "manual" else None}

    series = []
    groups = {}
    for name, idx in role_ids.items():
        if idx is None:
            continue
        groups.setdefault(idx, []).append(name)
    for idx, roles in groups.items():
        if idx == own_idx:
            pace = clean_history(own_history, own_history, own=True)
            state = "LOCAL"
        else:
            car = by_car.get(idx) or {}
            pace = clean_history(car.get("lapTimes"), car.get("cleanLapTimes"))
            state = car.get("presence") or "UNKNOWN"
        label = next((r for r in official if r["carIdx"] == idx), None)
        if label is None:
            label = by_car.get(idx) or {}
        series.append({"carIdx": idx, "carNumber": label.get("carNumber") or label.get("number") or "—",
                       "driverName": label.get("driverName") or label.get("driver"),
                       "roles": roles, "observationState": state, **pace})
    mean = {key: next((s["recentAverageSeconds"] for s in series if s["carIdx"] == idx), None)
            for key, idx in role_ids.items()}
    pace_difference = (round(mean["YOU"] - mean["RIVAL"], 4)
                       if mean["YOU"] is not None and mean["RIVAL"] is not None else None)
    # Reuse the existing Race Plan fuel estimates; never invent a fuel target.
    fm = (race_plan or {}).get("fuelModel") or {}
    observed = numeric(fm.get("observed_lpl"), positive=True)
    target = numeric(fm.get("strategy_lpl"), positive=True)
    # Only the existing FuelModel GREEN_FULL classifier may establish an
    # observed race-consumption value. Raw SDK fuel deltas include pit/caution.
    available_fuel = numeric(fuel)
    autonomy = available_fuel / observed if available_fuel is not None and observed else None
    return {
        "sessionIdentity": str(session_identity),
        "ownCarIdx": own_idx,
        "ownClassPosition": own_class.get("classPosition") if own_class else None,
        "ownPositionSource": own_class.get("positionSource") if own_class else "UNAVAILABLE",
        "ownOverallPosition": own_class.get("overallPosition") if own_class else None,
        "classStandings": official,
        "physical": {"ahead": ahead, "behind": behind, "source": "ZRE_FROM_SDK_DYNAMIC_POSITION"},
        "roles": role_ids, "paceSeries": series, "paceDifferenceToRival": pace_difference,
        "rival": {"selectionMode": selection.get("selectionMode") or selection.get("mode"),
                  "requestedCarIdx": selection.get("requestedCarIdx"),
                  "effectiveCarIdx": selection.get("effectiveCarIdx", selection.get("selectedIdx")),
                  "selectionState": selection.get("selectionState") or "UNKNOWN",
                  "selectedRival": selected_row,
                  "observation": selected_obs,
                  "rivalPace": mean["RIVAL"]},
        "fuel": {"currentLiters": available_fuel, "observedLpl": observed, "targetLpl": target,
                 "deviationLpl": round(observed-target, 4) if observed is not None and target is not None else None,
                 "autonomyLaps": round(autonomy, 2) if autonomy is not None else None,
                 "source": fm.get("source") or ("REAL LOCAL" if available_fuel is not None else "SIN DATO"),
                 "sampleCount": fm.get("green_samples") if observed is not None else 0,
                 "historicalSamples":fm.get("historical_samples")},
        "source": "RESULTS_POSITIONS / SDK_DYNAMIC / SESSION_INTELLIGENCE",
    }
