"""Compact Markdown renderer for ZRE Setup Engineer."""
from pathlib import Path


AI_REQUEST = (
    "Analyze this ZRE stint report as a GT3 race engineer. Separate driver "
    "technique from likely setup limitations. Identify the main compromise of "
    "the current setup. Recommend a maximum of 3 setup changes for the next "
    "test stint. For every change explain the expected benefit, possible "
    "downside, and which telemetry signal should improve if the change works. "
    "Avoid changing many variables simultaneously."
)


def _value(value):
    if value is None or value == "":
        return "UNAVAILABLE"
    if isinstance(value, bool):
        return "YES" if value else "NO"
    return str(value)


def _tagged(item):
    if isinstance(item, dict) and "value" in item:
        return f"{_value(item.get('value'))} [{item.get('source') or 'UNSPECIFIED'}]"
    return _value(item)


def _section_map(title, mapping):
    lines = [f"## {title}", ""]
    if not mapping:
        return lines + ["UNAVAILABLE", ""]
    for key, value in mapping.items():
        label = str(key).replace("_", " ").strip().title()
        lines.append(f"- **{label}:** {_tagged(value)}")
    lines.append("")
    return lines


def _comparison_lines(comparison):
    lines=["## COMPARISON VS PREVIOUS STINT",""]
    if not comparison:
        return lines+["No previous comparable stint.",""]
    overall=comparison.get("overall") or {}
    if overall:
        lines.append("### OVERALL")
        for key,item in overall.items():
            delta=item.get("delta")
            lines.append(f"- **{key}:** {item.get('before')} → {item.get('after')} · Δ {delta:+.4f}" if isinstance(delta,(int,float)) else f"- **{key}:** {_value(item)}")
        lines.append("")
    gained=comparison.get("gainedTime") or []
    lost=comparison.get("lostTime") or []
    lines.append("### WHERE TIME WAS GAINED")
    lines.extend([f"- **{row.get('zone')}:** {row.get('averageZoneTimeDelta'):+.3f}s" for row in gained] or ["No clear gain above threshold."])
    lines.append("")
    lines.append("### WHERE TIME WAS LOST")
    lines.extend([f"- **{row.get('zone')}:** +{row.get('averageZoneTimeDelta'):.3f}s" for row in lost] or ["No clear loss above threshold."])
    lines.append("")
    categories=comparison.get("categoryAverageZoneTimeDelta") or {}
    if categories:
        lines.append("### TRACK-DEMAND DELTAS")
        for key,value in categories.items():
            lines.append(f"- **{key}:** {value:+.3f}s average zone-time delta")
        lines.append("")
    changes=comparison.get("zoneChanges") or []
    if changes:
        lines.append("### CORNER DELTAS")
        for row in changes:
            details=[]
            for key,label,unit in (
                ("averageZoneTimeDelta","time","s"),("minSpeedKphDelta","min speed"," km/h"),
                ("exitSpeedKphDelta","exit speed"," km/h"),("brakeDurationDelta","brake duration","s"),
                ("throttleRampSecondsDelta","to full throttle","s"),("steeringCorrectionsDelta","steering corrections",""),
            ):
                value=row.get(key)
                if isinstance(value,(int,float)):details.append(f"{label} {value:+.3f}{unit}")
            if details:lines.append(f"- **{row.get('zone')}:** "+", ".join(details))
        lines.append("")
    return lines


def render_setup_report(stint, previous=None, setup_changes=None):
    stint = stint or {}
    session = stint.get("session") or {}
    performance = stint.get("stintPerformance") or {}
    setup = stint.get("setup") or {}
    profile = stint.get("trackProfile") or {}
    corners = stint.get("corners") or []
    patterns = stint.get("balancePatterns") or {}
    feedback = stint.get("driverFeedback") or {}
    quality = stint.get("dataQuality") or {}
    summary = stint.get("setupEngineerSummary") or []
    comparison = stint.get("comparison") or {}
    setup_changes = setup_changes or stint.get("setupChanges") or []

    lines = ["# ZRE SETUP ENGINEER REPORT", ""]
    lines += _section_map("SESSION", session)
    lines += ["## CONDITIONS", ""]
    conditions=stint.get("conditions") or {}
    for phase in ("start","end"):
        values=conditions.get(phase) or {}
        lines.append(f"### {phase.upper()}")
        if values:
            for key,value in values.items():
                lines.append(f"- **{str(key).replace('_',' ').title()}:** {_value(value)} [MEASURED]" if value is not None else f"- **{str(key).replace('_',' ').title()}:** UNAVAILABLE")
        else:
            lines.append("UNAVAILABLE")
        lines.append("")
    lines += _section_map("TRACK PROFILE", profile)

    lines += ["## CURRENT SETUP", ""]
    meta = setup.get("metadata") or {}
    if meta:
        for key, value in meta.items():
            lines.append(f"- **{key}:** {_value(value)}")
    params = setup.get("flatParameters") or {}
    if params:
        for key in sorted(params, key=str.lower):
            lines.append(f"- **{key}:** {_value(params[key])}")
    else:
        lines.append("UNAVAILABLE")
    lines.append("")

    lines += ["## SETUP CHANGES", ""]
    if setup_changes:
        for change in setup_changes:
            lines.append(f"- **{change.get('parameter')}:** {_value(change.get('before'))} → {_value(change.get('after'))}")
    else:
        lines.append("No previous comparable setup or no detected changes.")
    lines.append("")

    lines += _section_map("STINT PERFORMANCE", performance)

    lines += ["## TIRE SNAPSHOT", ""]
    tires=stint.get("tires") or {}
    for phase in ("start","end"):
        snapshot=tires.get(phase) or {}
        lines.append(f"### {phase.upper()}")
        lines.append("- **Dynamic pressure:** UNAVAILABLE_LIVE_SDK")
        wheels=snapshot.get("wheels") or {}
        if not wheels:
            lines.append("- No live tire snapshot available.")
        for wheel,data in wheels.items():
            temp=data.get("carcassTempC") or {};wear=data.get("wearRemainingPct") or {}
            lines.append(f"- **{wheel}:** cold { _value(data.get('coldPressureKPa')) } kPa · carcass L/M/R { _value(temp.get('left')) }/{ _value(temp.get('middle')) }/{ _value(temp.get('right')) } C · wear remaining L/M/R { _value(wear.get('left')) }/{ _value(wear.get('middle')) }/{ _value(wear.get('right')) }")
        lines.append("")
    delta=tires.get("delta") or {}
    if delta:
        lines.append("### START → END DELTA")
        for wheel,data in delta.items():
            wear=data.get("wearRemainingDelta") or {};temp=data.get("carcassTempCDelta") or {}
            lines.append(f"- **{wheel}:** carcass Δ L/M/R { _value(temp.get('left')) }/{ _value(temp.get('middle')) }/{ _value(temp.get('right')) } C · wear remaining Δ L/M/R { _value(wear.get('left')) }/{ _value(wear.get('middle')) }/{ _value(wear.get('right')) }")
        lines.append("")

    lines += ["## CORNER / ZONE ANALYSIS", ""]
    if corners:
        for corner in corners:
            zone = corner.get("zone") or corner.get("corner") or "Zone"
            types = ", ".join(corner.get("types") or []) or "UNCLASSIFIED"
            lines.append(f"### {zone} · {types}")
            for key, value in corner.items():
                if key in ("zone", "corner", "types"):
                    continue
                lines.append(f"- **{key}:** {_tagged(value)}")
            lines.append("")
    else:
        lines += ["UNAVAILABLE", ""]

    lines += _section_map("BALANCE PATTERNS", patterns)

    lines += ["## REPEATED BEHAVIOR", ""]
    repeated = stint.get("repeatedBehavior") or []
    if repeated:
        for item in repeated:
            lines.append(
                f"- **{item.get('location') or 'Zone'} · {item.get('pattern') or 'Pattern'}:** "
                f"{_value(item.get('occurrences'))}/{_value(item.get('validLaps'))} laps · "
                f"{_value(item.get('repeatRatio'))} · confidence {_value(item.get('confidence'))}"
            )
    else:
        lines.append("No repeated behavior with sufficient evidence.")
    lines.append("")

    lines += _section_map("DRIVER FEEDBACK", feedback)
    lines += _comparison_lines(comparison)

    lines += ["## ZRE SETUP ENGINEER SUMMARY", ""]
    if summary:
        for item in summary[:3]:
            lines.append(f"- {_value(item)}")
    else:
        lines.append("Insufficient evidence for a setup-specific conclusion.")
    lines.append("")

    lines += _section_map("DATA QUALITY", quality)

    lines += ["## REQUEST TO AI SETUP ENGINEER", "", AI_REQUEST, ""]
    return "\n".join(lines)


def write_setup_report(path, stint, previous=None, setup_changes=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_setup_report(stint, previous, setup_changes), encoding="utf-8")
    return path
