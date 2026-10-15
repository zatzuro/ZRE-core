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

    meta = setup.get("metadata") or {}
    setup_name = meta.get("setupName") or meta.get("filename")
    setup_identity = {
        "name": setup_name or "UNAVAILABLE",
        "source": setup.get("source") or "UNAVAILABLE",
        "fingerprint": setup.get("fingerprint") or "UNAVAILABLE",
        "mechanicalFingerprintV2": setup.get("setupFingerprintV2") or "LEGACY",
        "modified": meta.get("setupModified"),
    }

    lines = ["# ZRE SETUP ENGINEER REPORT", ""]
    lines += _section_map("SETUP IDENTITY", setup_identity)
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

    lines += ["## IN-CAR CONTROL CHANGES", ""]
    controls=stint.get("driverControls") or {}
    start_controls=controls.get("start") or {}
    end_controls=controls.get("end") or {}
    changes=controls.get("changes") or []
    if start_controls or end_controls:
        lines.append(f"- **Start:** {_value(start_controls)}")
        lines.append(f"- **End:** {_value(end_controls)}")
    if changes:
        for change in changes:
            where=[]
            if change.get("lap") is not None:where.append(f"lap {change.get('lap')}")
            if change.get("sessionTime") is not None:where.append(f"t={round(change.get('sessionTime'),1)}s")
            suffix=f" ({' · '.join(where)})" if where else ""
            lines.append(f"- **{change.get('control')}:** {_value(change.get('before'))} → {_value(change.get('after'))}{suffix}")
    elif not start_controls and not end_controls:
        lines.append("UNAVAILABLE")
    else:
        lines.append("No in-car control changes detected during this stint.")
    lines.append("")

    lines += _section_map("STINT PERFORMANCE", performance)

    lines += ["## TIRE SNAPSHOT · MEDICIÓN Y FRESCURA", ""]
    tires=stint.get("tires") or {}
    inspection=tires.get("inspection") or {}
    status=inspection.get("status") or "LEGACY · SIN VERIFICACIÓN TEMPORAL"
    if status=="CONFIRMED" and inspection.get("attribution")!="CONFIRMED_SAME_STINT":
        status="LEGACY_CONFIRMED_UNVERIFIED"
    lines.append(f"- **Inspección final:** {status}")
    for dimension in ("freshness", "attribution", "comparison", "tireSetEvidence"):
        lines.append(f"- **{dimension}:** {inspection.get(dimension) or 'NO VERIFICADO (LEGACY)'}")
    for wheel, evidence in (tires.get("wheelEvidence") or {}).items():
        lines.append(f"- **{wheel} evidencia:** {evidence}")
    lines.append(f"- **Fuente:** {_value(inspection.get('source'))}")
    lines.append(f"- **Última lectura SDK:** {_value(inspection.get('sessionTimeObserved'))} s (SessionTime)")
    if inspection.get("reason"):
        lines.append(f"- **Pendiente:** {inspection['reason']}")
    lines.append(f"- **Comparabilidad:** {tires.get('comparability') or inspection.get('comparison') or 'NO VERIFICADA'}")
    lines.append("- **Aviso:** completar campos no certifica su frescura; presión fría != última presión caliente.")
    lines.append("")
    for phase in ("start","end"):
        snapshot=(tires.get("garageAtEnd") if phase=="end" else None) or tires.get(phase) or {}
        pending=phase=="end" and status not in ("OBSERVED", "CONFIRMED")
        lines.append(f"### {phase.upper()} · "+("PROVISIONAL / NO CONFIRMADO" if pending else
                     ("GARAGE INSPECCIONADO" if phase=="end" else "REFERENCIA AL INICIO")))
        lines.append("- **Presión dinámica:** NO DISPONIBLE EN SDK")
        if snapshot.get("source"):
            lines.append(f"- **Fuente específica:** {snapshot['source']}")
        if phase=="end" and status in ("OBSERVED", "CONFIRMED") and snapshot.get("updateCount") is not None:
            lines.append(f"- **CarSetup.UpdateCount:** {snapshot['updateCount']}")
        wheels=snapshot.get("wheels") or {}
        if not wheels:
            lines.append("- Sin medición disponible.")
        for wheel in ("LF","RF","LR","RR"):
            data=wheels.get(wheel) or {}
            if not data:
                continue
            temp=data.get("lastTempsC") or {}
            wear=data.get("treadRemainingPct") or {}
            if temp or wear or data.get("lastHotPressureKPa") is not None:
                lines.append(f"- **{wheel} · GARAGE** ({data.get('physicalOrder') or 'posición identificada'}): "
                             f"fría {_value(data.get('coldPressureKPa'))} kPa · "
                             f"última caliente {_value(data.get('lastHotPressureKPa'))} kPa · "
                             f"temp exterior/medio/interior {_value(temp.get('outside'))}/"
                             f"{_value(temp.get('middle'))}/{_value(temp.get('inside'))} °C · "
                             f"goma restante exterior/medio/interior {_value(wear.get('outside'))}/"
                             f"{_value(wear.get('middle'))}/{_value(wear.get('inside'))} %")
            else:
                raw=data.get("carcassTempC") or {}
                remaining=data.get("wearRemainingPct") or {}
                lines.append(f"- **{wheel} · TELEMETRÍA SDK** (no inspección vigente): "
                             f"fría {_value(data.get('coldPressureKPa'))} kPa · "
                             f"carcasa L/M/R {_value(raw.get('left'))}/{_value(raw.get('middle'))}/"
                             f"{_value(raw.get('right'))} °C · goma restante L/M/R "
                             f"{_value(remaining.get('left'))}/{_value(remaining.get('middle'))}/"
                             f"{_value(remaining.get('right'))} [fracción SDK 0–1; garage usa % 0–100]")
        lines.append("")
    deltas=tires.get("delta") or {}
    if status not in ("OBSERVED", "CONFIRMED"):
        lines.append("### DELTA INICIO → FINAL")
        observed=tires.get("provisionalDelta") or {}
        if observed:
            lines.append("CAMBIO OBSERVADO EN SDK DE TRANSICIÓN · PROVISIONAL, no es inspección final certificada:")
            for wheel,values in observed.items():
                wear=(values.get("wearRemainingDelta") or {})
                temps=(values.get("carcassTempCDelta") or {})
                lines.append(f"- {wheel} goma restante L/M/R (delta en fracción SDK): "
                             f"{_value(wear.get('left'))}/{_value(wear.get('middle'))}/{_value(wear.get('right'))}; "
                             f"carcasa °C L/M/R: {_value(temps.get('left'))}/"
                             f"{_value(temps.get('middle'))}/{_value(temps.get('right'))}")
        else:
            lines.append("NO DISPONIBLE: falta inspección final confirmada. "
                         "No se interpreta ausencia de desgaste ni se publica Δ=0.")
    elif not deltas:
        lines.append("### DELTA INICIO → FINAL")
        lines.append("NO COMPARABLE: no existe evidencia suficiente de que las "
                     "mediciones se refieran al mismo juego de neumáticos.")
    else:
        lines.append("### DELTA INICIO → FINAL · COMPARABLE")
        for wheel,values in deltas.items():
            lines.append(f"- **{wheel}:** {_value(values)}")
    if status in ("OBSERVED", "CONFIRMED"):
        confirmed=(tires.get("garageAtEnd") or tires.get("end") or {}).get("wheels") or {}
        for label,wheels in (("DELANTEROS",("LF","RF")),("TRASEROS",("LR","RR"))):
            minima=[value for wheel in wheels for value in
                    (((confirmed.get(wheel) or {}).get("treadRemainingPct") or {}).values())
                    if isinstance(value,(int,float))]
            if minima:
                lines.append(f"- **Mínima goma observada {label}:** {min(minima):.1f} % "
                             "(observación; sin diagnóstico causal)")
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
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(render_setup_report(stint, previous, setup_changes), encoding="utf-8")
    temp.replace(path)
    return path
