"""Fuel model for ZRE Race Plan.

Keeps observed consumption separate from the conservative strategy value.
Only classified laps are allowed to influence the green-race strategy model.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from statistics import median


GREEN_FULL = "GREEN_FULL"
OUT_LAP = "OUT_LAP"
IN_LAP = "IN_LAP"
PIT_LAP = "PIT_LAP"
CAUTION = "CAUTION"
INVALID = "INVALID"
ANOMALO_EXPLICADO = "ANOMALO_EXPLICADO"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FuelLapSample:
    lap: int
    liters: float | None
    classification: str
    lap_time_seconds: float | None = None
    source: str = "SESSION"
    valid: bool = True
    explanation: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class FuelEstimate:
    observed_lpl: float | None
    strategy_lpl: float | None
    source: str
    confidence: str
    green_samples: int
    historical_samples: int
    margin_laps: float
    margin_source: str

    def to_dict(self):
        return asdict(self)


def classify_fuel_lap(*, valid=True, on_pit=False, entered_pit=False, exited_pit=False,
                      caution=False, anomalous=False, explanation=None):
    if entered_pit or on_pit:
        return IN_LAP if entered_pit else PIT_LAP
    if exited_pit:
        return OUT_LAP
    if caution:
        return CAUTION
    if not valid:
        return INVALID
    if anomalous and explanation:
        return ANOMALO_EXPLICADO
    return GREEN_FULL


def _quantile(values, q):
    values = sorted(float(v) for v in values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(len(values) - 1, lo + 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


class FuelModel:
    def __init__(self, max_current=80, max_historical=200):
        self.max_current = max_current
        self.max_historical = max_historical
        self.current = []
        self.historical = []

    @staticmethod
    def _usable(sample):
        return (
            isinstance(sample, FuelLapSample)
            and sample.classification == GREEN_FULL
            and sample.valid
            and sample.liters is not None
            and 0 < float(sample.liters) < 30
        )

    def add(self, sample, historical=False):
        target = self.historical if historical else self.current
        target.append(sample)
        limit = self.max_historical if historical else self.max_current
        if len(target) > limit:
            del target[:-limit]

    def extend(self, samples, historical=False):
        for sample in samples or []:
            self.add(sample, historical=historical)

    def green_values(self, historical=False):
        source = self.historical if historical else self.current
        return [float(s.liters) for s in source if self._usable(s)]

    def estimate(self, *, margin_laps=0.0, margin_source="ZRE_CONFIG"):
        current = self.green_values(False)
        history = self.green_values(True)
        combined = current if len(current) >= 3 else current + history[-20:]
        if not combined:
            return FuelEstimate(None, None, "SIN DATO", "NONE", len(current), len(history),
                                float(margin_laps or 0), margin_source)
        observed = median(combined)
        # Strategy consumption is robust but conservative: 75th percentile with
        # a small floor above the median. High valid laps remain in the sample;
        # they are not discarded merely for being high.
        q75 = _quantile(combined, .75)
        strategy = max(observed * 1.005, q75)
        if len(current) >= 8:
            confidence = "HIGH"
            source = "CURRENT_SESSION"
        elif len(current) >= 3:
            confidence = "MEDIUM"
            source = "CURRENT_SESSION"
        elif history:
            confidence = "LOW"
            source = "HISTORICAL+CURRENT"
        else:
            confidence = "LOW"
            source = "CURRENT_SESSION"
        return FuelEstimate(round(observed, 4), round(strategy, 4), source, confidence,
                            len(current), len(history), float(margin_laps or 0), margin_source)

    def snapshot(self):
        return {
            "current": [sample.to_dict() for sample in self.current],
            "historical": [sample.to_dict() for sample in self.historical],
        }

    @classmethod
    def restore(cls, payload):
        model = cls()
        for kind in ("current", "historical"):
            for item in (payload or {}).get(kind, []):
                try:
                    sample = FuelLapSample(**item)
                except TypeError:
                    continue
                model.add(sample, historical=(kind == "historical"))
        return model
