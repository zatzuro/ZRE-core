"""Pit service estimation for ZRE Race Plan.

The engine refuses to invent concurrency. Unknown rules produce component
estimates but no falsely precise stationary total.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from statistics import median


SIMULTANEOUS = "SIMULTANEOUS"
SEQUENTIAL = "SEQUENTIAL"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PitRulesProfile:
    service_mode: str = UNKNOWN
    refuel_rate_lps: float | None = None
    tyre_time_seconds: float | None = None
    driver_change_seconds: float | None = None
    pit_lane_seconds: float | None = None
    source: str = "UNKNOWN"


@dataclass(frozen=True)
class PitServiceRequest:
    fuel_liters: float = 0.0
    tyres: bool = False
    driver_change: bool = False
    repair_seconds: float = 0.0


@dataclass(frozen=True)
class PitStopEstimate:
    fuel_time: float | None
    tyre_time: float | None
    driver_change_time: float | None
    repair_time: float | None
    stationary_time: float | None
    pit_lane_time: float | None
    total_pit_loss: float | None
    tyre_extra_time: float | None
    source: str
    confidence: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ObservedPitStop:
    pit_lane_seconds: float | None
    stationary_seconds: float | None
    fuel_added_liters: float | None = None
    tyres: bool | None = None
    driver_change: bool | None = None
    repair_seconds: float | None = None


def estimate_pit_stop(profile, request):
    fuel_time = None
    if request.fuel_liters <= 0:
        fuel_time = 0.0
    elif profile.refuel_rate_lps and profile.refuel_rate_lps > 0:
        fuel_time = request.fuel_liters / profile.refuel_rate_lps
    tyre_time = profile.tyre_time_seconds if request.tyres else 0.0
    driver_time = profile.driver_change_seconds if request.driver_change else 0.0
    repair_time = max(0.0, float(request.repair_seconds or 0.0))
    components = [fuel_time, tyre_time, driver_time, repair_time]
    known = all(value is not None for value in components)
    stationary = None
    tyre_extra = None
    if known and profile.service_mode == SIMULTANEOUS:
        stationary = max(components)
        base_without_tyre = max(fuel_time, driver_time, repair_time)
        tyre_extra = max(0.0, stationary - base_without_tyre)
    elif known and profile.service_mode == SEQUENTIAL:
        stationary = sum(components)
        tyre_extra = tyre_time
    pit_lane = profile.pit_lane_seconds
    total = stationary + pit_lane if stationary is not None and pit_lane is not None else None
    confidence = "HIGH" if total is not None and profile.source != "UNKNOWN" else "MEDIUM" if stationary is not None else "LOW"
    return PitStopEstimate(
        round(fuel_time, 3) if fuel_time is not None else None,
        round(tyre_time, 3) if tyre_time is not None else None,
        round(driver_time, 3) if driver_time is not None else None,
        round(repair_time, 3),
        round(stationary, 3) if stationary is not None else None,
        round(pit_lane, 3) if pit_lane is not None else None,
        round(total, 3) if total is not None else None,
        round(tyre_extra, 3) if tyre_extra is not None else None,
        profile.source,
        confidence,
    )


class PitLearningModel:
    def __init__(self, max_samples=30):
        self.max_samples = max_samples
        self.samples = []

    def add(self, stop):
        if isinstance(stop, ObservedPitStop):
            self.samples.append(stop)
            if len(self.samples) > self.max_samples:
                del self.samples[:-self.max_samples]

    def learned_pit_lane_seconds(self):
        values = [s.pit_lane_seconds for s in self.samples if s.pit_lane_seconds is not None and s.pit_lane_seconds > 0]
        return median(values) if len(values) >= 2 else None

    def learned_refuel_rate(self):
        rates = []
        for sample in self.samples:
            if (sample.fuel_added_liters is not None and sample.fuel_added_liters > 0
                    and sample.stationary_seconds is not None and sample.stationary_seconds > 0
                    and not sample.tyres and not sample.driver_change
                    and not (sample.repair_seconds or 0)):
                rates.append(sample.fuel_added_liters / sample.stationary_seconds)
        return median(rates) if len(rates) >= 2 else None
