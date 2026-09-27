"""Race-state primitives for ZRE Race Plan.

Pure data structures only. No SDK polling and no UI dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RaceIdentity:
    session_id: Any
    subsession_id: Any
    track_id: Any
    layout: str
    team_id: Any
    car_number: str
    car_id: Any = None
    session_num: Any = None

    @property
    def key(self) -> str:
        parts = (
            self.subsession_id if self.subsession_id not in (None, "") else self.session_id,
            self.track_id,
            self.layout or "default",
            self.team_id,
            self.car_number or "unknown",
            self.car_id,
            self.session_num,
        )
        return "|".join(str(part) for part in parts)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RaceState:
    identity: RaceIdentity
    session_type: str
    remaining_seconds: float | None
    session_total_seconds: float | None
    current_lap: int
    completed_laps: int
    own_pace_seconds: float | None
    leader_lap: int | None = None
    leader_pace_seconds: float | None = None
    laps_remaining: int | None = None
    current_driver: str | None = None
    current_fuel_liters: float | None = None
    fuel_source: str = "SIN DATO"
    fuel_confidence: str = "NONE"
    physical_tank_liters: float | None = None
    session_fuel_limit_liters: float | None = None
    on_pit_road: bool = False
    session_flags: int | None = None
    mandatory_stops_remaining: int = 0
    require_tire_change: bool = False
    min_drivers: int | None = None
    max_drivers: int | None = None

    @property
    def timed(self) -> bool:
        return self.remaining_seconds is not None and self.remaining_seconds >= 0

    @property
    def lap_limited(self) -> bool:
        return self.laps_remaining is not None and self.laps_remaining >= 0

    def to_dict(self):
        payload = asdict(self)
        payload["identity"]["key"] = self.identity.key
        return payload


def session_fuel_limit(physical_liters, max_fuel_pct):
    """Return the actual race-session fuel capacity when both values exist.

    DriverCarMaxFuelPct is represented by iRacing as a fraction in common SDK
    session data. Values over 1 are accepted as percent for defensive import.
    """
    try:
        physical = float(physical_liters)
    except (TypeError, ValueError):
        return None
    if physical <= 0:
        return None
    if max_fuel_pct is None:
        return physical
    try:
        pct = float(max_fuel_pct)
    except (TypeError, ValueError):
        return physical
    if pct <= 0:
        return None
    if pct > 1:
        pct /= 100.0
    return min(physical, physical * pct)
