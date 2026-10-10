"""Setup Engineer orchestration for ZRE.

This layer consumes bounded post-lap summaries. It does not poll the SDK and it
does not duplicate raw telemetry capture.
"""
from datetime import datetime
from copy import deepcopy
from pathlib import Path
import math

try:
    from server.setup_snapshot import compare_setups, snapshot_from_html
    from server.setup_ownership import same_confirmed_owner
    from server.setup_report import write_setup_report
    from server.stint_store import StintStore, slug
    from server.stint_engineering_snapshot import compare_tires, snapshot_availability
except ModuleNotFoundError:
    from setup_snapshot import compare_setups, snapshot_from_html
    from setup_ownership import same_confirmed_owner
    from setup_report import write_setup_report
    from stint_store import StintStore, slug
    from stint_engineering_snapshot import compare_tires, snapshot_availability


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
            "phase": item.get("phase"),
            "averageLoss": item.get("averageLoss"),
            "advice": item.get("advice"),
        })
    return repeated


def build_balance_patterns(repeated, feedback=None):
    feedback=feedback or {};grouped={"ENTRY":[],"MID":[],"EXIT":[]}
    for item in repeated or []:
        phase=item.get("phase")
        if phase not in grouped:continue
        confidence=item.get("confidence") or "BAJA"
        count=item.get("occurrences");total=item.get("validLaps")
        driver_value=feedback.get(phase.lower())
        aligned=driver_value in ("SUELTO","SUBVIRA") and confidence in ("MEDIA","ALTA")
        prefix="POSSIBLE SETUP-RELATED LIMITATION" if aligned else "DETECTED PATTERN"
        evidence=f"{item.get('pattern') or 'Pattern'} · {count}/{total} valid laps · confidence {confidence}"
        if driver_value:
            evidence+=f" · driver feedback {driver_value}"
        grouped[phase].append((confidence=="ALTA",confidence=="MEDIA",item.get("averageLoss") or 0,f"{prefix}: {evidence}"))
    result={}
    for phase,items in grouped.items():
        if not items:result[phase]="No repeated pattern with sufficient evidence."
        else:
            items.sort(reverse=True)
            result[phase]=" | ".join(item[3] for item in items[:2])
    return result


def build_setup_summary(repeated, feedback=None):
    feedback=feedback or {};ranked=[]
    for item in repeated or []:
        confidence=item.get("confidence") or "BAJA"
        if confidence=="BAJA":continue
        phase=item.get("phase")
        driver_value=feedback.get(str(phase or "").lower())
        aligned=driver_value in ("SUELTO","SUBVIRA")
        priority=(2 if confidence=="ALTA" else 1)+(1 if aligned else 0)
        prefix="Possible setup-related limitation" if aligned else "Detected pattern"
        text=f"{prefix}: {item.get('location') or 'Zone'} · {item.get('pattern') or 'Pattern'} · {item.get('occurrences')}/{item.get('validLaps')} valid laps · confidence {confidence}"
        if aligned:text+=f" · driver reports {driver_value}"
        ranked.append((priority,item.get("averageLoss") or 0,text))
    ranked.sort(reverse=True)
    return [item[2] for item in ranked[:3]]


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


def _tag_value(item):
    return item.get("value") if isinstance(item,dict) and "value" in item else item


def compare_stint_performance(previous, current):
    old_perf = (previous or {}).get("stintPerformance") or {}
    new_perf = (current or {}).get("stintPerformance") or {}
    overall = {}
    for key in ("bestLap", "representativeAverage", "lapStdDev", "fuelPerLap"):
        before, after = old_perf.get(key), new_perf.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            overall[key] = {
                "before": round(before, 4),
                "after": round(after, 4),
                "delta": round(after - before, 4),
            }

    old_corners={row.get("zone"):row for row in (previous or {}).get("corners") or [] if row.get("zone")}
    new_corners={row.get("zone"):row for row in (current or {}).get("corners") or [] if row.get("zone")}
    zone_changes=[]
    for zone in sorted(set(old_corners)&set(new_corners)):
        before,after=old_corners[zone],new_corners[zone]
        change={"zone":zone,"types":after.get("types") or []}
        for key in ("averageZoneTime","minSpeedKph","exitSpeedKph","brakeDuration","throttleRampSeconds","steeringCorrections"):
            old_value,new_value=_tag_value(before.get(key)),_tag_value(after.get(key))
            if isinstance(old_value,(int,float)) and isinstance(new_value,(int,float)):
                change[key+"Delta"]=round(new_value-old_value,4)
        if len(change)>2:zone_changes.append(change)

    gained=sorted([row for row in zone_changes if row.get("averageZoneTimeDelta",0)<-.03],key=lambda row:row["averageZoneTimeDelta"])[:3]
    lost=sorted([row for row in zone_changes if row.get("averageZoneTimeDelta",0)>.03],key=lambda row:row["averageZoneTimeDelta"],reverse=True)[:3]

    category_changes={}
    categories=sorted({kind for row in zone_changes for kind in row.get("types") or []})
    for kind in categories:
        rows=[row for row in zone_changes if kind in (row.get("types") or []) and "averageZoneTimeDelta" in row]
        if rows:
            category_changes[kind]=round(sum(row["averageZoneTimeDelta"] for row in rows)/len(rows),4)

    return {
        "overall":overall,
        "gainedTime":gained,
        "lostTime":lost,
        "zoneChanges":zone_changes,
        "categoryAverageZoneTimeDelta":category_changes,
    }


class SetupEngineer:
    def __init__(self, root):
        self.root = Path(root)
        self.store = StintStore(self.root / "data" / "setup_engineer")
        self.current = None
        self.last_saved = None
        self.last_report_path = None
        self.imported_setup = None
        self.setup_source_preference = "auto"
        self.status = "Esperando stint"
        self.owner = {"authorized": False, "reason": "Identidad aún no confirmada"}
        self.owner_location = {}
        recovered = self.store.latest_stint()
        if recovered:
            self.last_saved = recovered
            try:
                # Historical records stay readable but are never auto-exported
                # without reliable ownership metadata and fresh authorization.
                self.status = "Último stint recuperado · exportación sujeta a identidad"
            except OSError:
                self.last_report_path = None
                self.status = f"Último stint recuperado · reporte pendiente"

    def set_owner(self, owner, location=None):
        self.owner = dict(owner or {"authorized": False, "reason": "SDK desconectado"})
        self.owner_location = dict(location or {})
        if self.current is not None:
            original = (self.current.get("session") or {}).get("setupOwner")
            # Disallow a stale/mismatched stint reaching the disk on role/car changes.
            if not same_confirmed_owner(original, self.owner):
                self.current["ownershipRevoked"] = True

    def _can_write(self, record):
        original = (record.get("session") or {}).get("setupOwner")
        return (not record.get("ownershipRevoked")
                and same_confirmed_owner(original, self.owner))

    def _deny(self):
        self.status = "Setup bloqueado · " + str(self.owner.get("reason") or "propiedad no confirmada")
        return None

    def import_html_setup(self, html_text, filename=None):
        if not self.owner.get("authorized"):
            return self._deny()
        text=str(html_text or "")
        if not text or len(text)>500_000:
            self.status="HTML de setup inválido o demasiado grande"
            return None
        snapshot=snapshot_from_html(text, filename)
        if not snapshot.get("parameters"):
            self.status="No se encontraron parámetros de setup en el HTML"
            return None
        snapshot["ownership"] = dict(self.owner)
        location=self.owner_location
        if not all(location.get(key) for key in ("car","track","layout")):
            self.status="Importación bloqueada · coche o circuito sin confirmar"
            return None
        self.store.save_setup(location["car"],location["track"],location["layout"],snapshot)
        self.imported_setup=snapshot
        self.status=f"Setup HTML importado · {filename or snapshot.get('fingerprint')}"
        return snapshot

    def set_setup_source(self, value):
        value=str(value or "auto").lower()
        if value not in ("auto","html"):
            return False
        self.setup_source_preference=value
        if value=="html" and not self.imported_setup:
            self.status="HTML seleccionado · importa un setup antes del próximo stint"
        elif value=="html":
            self.status="HTML IMPORTADO será usado en el próximo stint"
        else:
            self.status="AUTO · SDK prioritario, HTML como respaldo"
        return True

    def resolve_setup(self, sdk_snapshot):
        sdk=sdk_snapshot or {}
        html=self.imported_setup or {}
        if html and not same_confirmed_owner(html.get("ownership"), self.owner):
            html={}
            self.status="HTML asociado a otro coche; importación no reutilizable"
        if self.setup_source_preference=="html":
            if html.get("parameters"):
                return html
            self.status="HTML no disponible · usando SDK"
        if sdk.get("parameters"):
            return sdk
        if html.get("parameters"):
            return html
        return sdk

    def start_stint(self, session, setup_snapshot, conditions=None, fuel_start=None, session_time=None, tires_start=None, controls_start=None):
        if not self.owner.get("authorized") or self.owner.get("scope") != "own":
            return self._deny()  # CarSetup SDK is always local, never a spectator's observed car.
        session = {**dict(session or {}), "setupOwner": dict(self.owner)}
        self.current = {
            "startedAt": datetime.now().isoformat(timespec="seconds"),
            "session": dict(session or {}),
            "conditions": dict(conditions or {}),
            "setup": {**deepcopy(setup_snapshot or {}), "ownership": dict(self.owner)},
            "fuelStart": fuel_start,
            "startSessionTime": session_time,
            "tiresStart": tires_start or {},
            "controlsStart": dict(controls_start or {}),
            "controlsLast": dict(controls_start or {}),
            "controlChanges": [],
            "driverFeedback": {},
        }
        setup_name=(setup_snapshot or {}).get("metadata",{}).get("setupName")
        self.status=f"Stint en curso · {setup_name or (setup_snapshot or {}).get('fingerprint') or 'setup sin identificar'}"
        return self.current

    def observe_controls(self, controls, session_time=None, lap=None):
        if self.current is None or not isinstance(controls,dict):
            return False
        last=self.current.setdefault("controlsLast",{})
        changes=self.current.setdefault("controlChanges",[])
        for key,value in controls.items():
            if value is None:
                continue
            previous=last.get(key)
            if previous is not None and previous!=value:
                changes.append({"control":key,"before":previous,"after":value,"sessionTime":session_time,"lap":lap})
                del changes[:-50]
            last[key]=value
        return True

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

    def finish_stint(self, engineering, fuel_end=None, session_time=None, fuel_per_lap=None, tires_end=None, conditions_end=None):
        if self.current is None:
            return None
        base = self.current
        if not self._can_write(base):
            self.current = None
            return self._deny()
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

        repeated=build_repeated_behavior(engineering);feedback=base.get("driverFeedback") or {}
        record = {
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "session": session,
            "conditions": {"start":base.get("conditions") or {},"end":conditions_end or {}},
            "trackProfile": build_track_profile(engineering),
            "setup": setup,
            "stintPerformance": performance,
            "corners": build_corner_analysis(engineering),
            "tires": {"start":base.get("tiresStart") or {},"end":tires_end or {},"delta":compare_tires(base.get("tiresStart") or {},tires_end or {})},
            "driverControls": {"start":base.get("controlsStart") or {},"end":base.get("controlsLast") or {},"changes":base.get("controlChanges") or []},
            "balancePatterns": build_balance_patterns(repeated,feedback),
            "repeatedBehavior": repeated,
            "driverFeedback": feedback,
            "comparison": {},
            "setupEngineerSummary": build_setup_summary(repeated,feedback),
            "dataQuality": {
                "validLaps": valid_laps,
                "cornerModelCount": len((engineering or {}).get("corners") or []),
                "zonesAnalyzed": len((engineering or {}).get("zones") or []),
                "setupSource": setup.get("source"),
                "setupAvailable": bool(setup.get("parameters")),
                "tireStart": snapshot_availability(base.get("tiresStart") or {}),
                "tireEnd": snapshot_availability(tires_end or {}),
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
        report=self.export_report(saved)
        if report:
            self.status=f"Stint {saved.get('stintNumber')} guardado · reporte automático · {report.name}"
        else:
            self.status=f"Stint {saved.get('stintNumber')} guardado · reporte no disponible"
        return saved

    def update_feedback(self, stint, entry=None, mid=None, exit=None, comment=None):
        if not isinstance(stint, dict) or not self._can_write(stint):
            return None
        feedback = dict(stint.get("driverFeedback") or {})
        for key, value in (("entry", entry), ("mid", mid), ("exit", exit)):
            if value in ("SUELTO", "NEUTRO", "SUBVIRA"):
                feedback[key] = value
        if comment is not None:
            feedback["comment"] = str(comment).strip()[:1000]
        stint["driverFeedback"] = feedback
        stint["balancePatterns"]=build_balance_patterns(stint.get("repeatedBehavior") or [],feedback)
        stint["setupEngineerSummary"]=build_setup_summary(stint.get("repeatedBehavior") or [],feedback)
        session = stint.get("session") or {}
        path = self.store.save_stint(stint)
        self.last_saved = self.store._read_json(path, stint)
        report=self.export_report(self.last_saved)
        self.status=(f"Stint {self.last_saved.get('stintNumber')} · feedback guardado · reporte actualizado · {report.name}"
                     if report else f"Stint {self.last_saved.get('stintNumber')} · feedback guardado")
        return self.last_saved

    def export_report(self, stint=None):
        record = stint or self.last_saved
        if not record or not self._can_write(record):
            return self._deny()
        session = record.get("session") or {}
        number = int(record.get("stintNumber") or 0)
        setup = record.get("setup") or {}
        meta = setup.get("metadata") or {}
        setup_name = meta.get("setupName") or meta.get("filename")
        setup_label = slug(setup_name, "setup-unidentified")[:60]
        filename = "ZRE_SETUP_REPORT_{}_{}_{}_{}_Stint{:02d}.md".format(
            slug(session.get("car")),
            slug(session.get("track")),
            slug(session.get("layout"), "default"),
            setup_label,
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
