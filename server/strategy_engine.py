"""Pure time-based endurance strategy mathematics. No iRacing dependency."""
from __future__ import annotations
from dataclasses import dataclass,field
from math import ceil,floor
from typing import Mapping

@dataclass(frozen=True)
class StrategyInputs:
    remaining_time_seconds:float;average_lap_seconds:float;pit_loss_seconds:float;current_lap:int=0
    current_fuel_liters:float|None=None;consumption_liters_per_lap:float|None=None;tank_capacity_liters:float|None=None
    base_stint_laps:int=37;extended_stint_laps:int=38;current_stint_laps_completed:int=0;stops_completed:int=0
    target_total_stops:int|None=None;driver_assignments:Mapping[int,str]=field(default_factory=dict)
@dataclass(frozen=True)
class StopEstimate:number:int;lap:int;eta_seconds:float;complete_eta_seconds:float
@dataclass(frozen=True)
class StintEstimate:number:int;laps:int;start_lap:int;end_lap:int;duration_seconds:float;driver:str|None=None;double_stint:bool=False
@dataclass(frozen=True)
class StrategyScenario:
    stint_laps:int;projected_laps:int;stops_remaining:int;stints_remaining:int;last_stint_laps:int;last_stint_seconds:float
    current_autonomy_laps:int;stop_estimates:tuple[StopEstimate,...];stints:tuple[StintEstimate,...]
    total_fuel_needed_liters:float|None;final_stint_fuel_margin_liters:float|None;finish_time_margin_seconds:float
@dataclass(frozen=True)
class ExtensionPlan:
    target_stops_remaining:int;target_projected_laps:int;extra_laps_needed:int;extra_laps_available:int;avoidable:bool
    current_stint_extra:int;future_extended_stints_needed:int;future_base_stints:int;distribution_text:str
@dataclass(frozen=True)
class StrategyResult:base:StrategyScenario;extended:StrategyScenario;extension:ExtensionPlan;target_total_stops:int

def _positive(v,name):
    v=float(v)
    if v<=0:raise ValueError(f"{name} must be > 0")
    return v
def _non_negative(v,name):
    v=float(v)
    if v<0:raise ValueError(f"{name} must be >= 0")
    return v
def _fuel_autonomy(i):
    if i.current_fuel_liters is None or i.consumption_liters_per_lap is None:return None
    return max(0,floor(max(0.0,float(i.current_fuel_liters))/_positive(i.consumption_liters_per_lap,"consumption_liters_per_lap")+1e-9))
def _current_remaining(i,target):
    planned=max(0,int(target)-max(0,int(i.current_stint_laps_completed)));fuel=_fuel_autonomy(i)
    return planned if fuel is None else min(planned,fuel)
def _future_capacity(i,target):
    if i.tank_capacity_liters is None or i.consumption_liters_per_lap is None:return target
    return min(target,max(0,floor(float(i.tank_capacity_liters)/_positive(i.consumption_liters_per_lap,"consumption_liters_per_lap")+1e-9)))
def _minimal_stops_plan(remaining,lap_time,pit_loss,current_remaining,future_stint):
    candidates=[]
    for stops in range(max(0,ceil(remaining/lap_time))+2):
        time_capacity=max(0,floor((remaining-stops*pit_loss)/lap_time+1e-9));fuel_capacity=current_remaining+stops*future_stint;laps=min(time_capacity,fuel_capacity)
        needed=0 if laps<=current_remaining else ceil((laps-current_remaining)/future_stint)
        if needed==stops:candidates.append((laps,stops))
    return max(candidates,key=lambda x:(x[0],-x[1])) if candidates else (0,0)
def _build_stints(i,projected,stops,current_remaining,future_stint,lap_time,pit_loss):
    if projected<=0:return (),()
    lengths=[];remaining=projected;first=min(current_remaining,remaining);lengths.append(first);remaining-=first
    while remaining>0:
        length=min(future_stint,remaining);lengths.append(length);remaining-=length
    assignments=dict(i.driver_assignments or {});stints=[];cursor=int(i.current_lap)
    for n,laps in enumerate(lengths,1):
        driver=assignments.get(n);double=bool(driver and (driver==assignments.get(n-1) or driver==assignments.get(n+1)))
        stints.append(StintEstimate(n,laps,cursor+1,cursor+laps,laps*lap_time,driver,double));cursor+=laps
    estimates=[];laps_before=0
    for n in range(1,min(stops,len(lengths)-1)+1):
        laps_before+=lengths[n-1];eta=laps_before*lap_time+(n-1)*pit_loss;estimates.append(StopEstimate(n,int(i.current_lap)+laps_before,eta,eta+pit_loss))
    return tuple(estimates),tuple(stints)
def _scenario(i,stint_laps):
    remaining=_non_negative(i.remaining_time_seconds,"remaining_time_seconds");lap_time=_positive(i.average_lap_seconds,"average_lap_seconds");pit=_non_negative(i.pit_loss_seconds,"pit_loss_seconds");stint_laps=max(1,int(stint_laps));current=_current_remaining(i,stint_laps);stint_laps=_future_capacity(i,stint_laps)
    projected,stops=_minimal_stops_plan(remaining,lap_time,pit,current,stint_laps);stop_estimates,stints=_build_stints(i,projected,stops,current,stint_laps,lap_time,pit);last=stints[-1].laps if stints else 0;cons=i.consumption_liters_per_lap;total=projected*float(cons) if cons is not None and cons>0 else None;margin=None
    if cons is not None and cons>0 and stints:
        capacity=current if len(stints)==1 else stint_laps;margin=max(0.0,(capacity-last)*float(cons))
    used=projected*lap_time+stops*pit
    return StrategyScenario(stint_laps,projected,stops,len(stints),last,last*lap_time,current,stop_estimates,stints,total,margin,max(0.0,remaining-used))
def _extension_plan(i,base,extended):
    lap=_positive(i.average_lap_seconds,"average_lap_seconds");pit=_non_negative(i.pit_loss_seconds,"pit_loss_seconds");remaining=_non_negative(i.remaining_time_seconds,"remaining_time_seconds")
    target_total=max(i.stops_completed,i.stops_completed+base.stops_remaining-(1 if extended.stops_remaining<base.stops_remaining else 0)) if i.target_total_stops is None else max(i.stops_completed,int(i.target_total_stops));target_remaining=max(0,target_total-int(i.stops_completed));target_laps=max(0,floor((remaining-target_remaining*pit)/lap+1e-9))
    base_current=_current_remaining(i,i.base_stint_laps);ext_current=_current_remaining(i,i.extended_stint_laps);base_future=_future_capacity(i,max(1,int(i.base_stint_laps)));ext_future=_future_capacity(i,max(1,int(i.extended_stint_laps)));base_capacity=base_current+target_remaining*base_future;ext_capacity=ext_current+target_remaining*ext_future;needed=max(0,target_laps-base_capacity);available=max(0,ext_capacity-base_capacity);avoidable=needed<=available;current_extra=min(needed,max(0,ext_current-base_current));remaining_extra=max(0,needed-current_extra);per_future=max(0,ext_future-base_future);future_extended=0 if remaining_extra==0 else (ceil(remaining_extra/per_future) if per_future else 0);future_extended=min(target_remaining,future_extended);future_base=max(0,target_remaining-future_extended)
    if needed==0:text="Objetivo ya alcanzado: no faltan vueltas extra."
    elif not avoidable:text=f"Faltan +{needed} vueltas; la extensión configurada sólo aporta +{available}."
    else:
        parts=[]
        if current_extra:parts.append(f"stint actual +{current_extra}")
        if future_extended:parts.append(f"{future_extended} stint{'s' if future_extended!=1 else ''} de {i.extended_stint_laps}")
        if future_base:parts.append(f"{future_base} stint{'s' if future_base!=1 else ''} de {i.base_stint_laps}")
        text=" · ".join(parts)
    return ExtensionPlan(target_remaining,target_laps,needed,available,avoidable,current_extra,future_extended,future_base,text),target_total
def calculate_strategy(i):
    if i.extended_stint_laps<i.base_stint_laps:raise ValueError("extended_stint_laps must be >= base_stint_laps")
    base=_scenario(i,i.base_stint_laps);extended=_scenario(i,i.extended_stint_laps);extension,target=_extension_plan(i,base,extended)
    return StrategyResult(base,extended,extension,target)


# ---------------------------------------------------------------------------
# Race Plan vNext — pure strategy core. The legacy API above remains intact
# while callers migrate to this stricter time/fuel/rules model.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RacePlanInputs:
    remaining_time_seconds: float | None
    current_lap: int
    own_pace_seconds: float | None
    current_fuel_liters: float | None
    fuel_strategy_lpl: float | None
    session_fuel_limit_liters: float | None
    pit_loss_seconds: float = 0.0
    margin_laps: float = 0.0
    mandatory_stops_remaining: int = 0
    laps_remaining: int | None = None
    leader_lap: int | None = None
    leader_pace_seconds: float | None = None
    stops_completed: int = 0
    fuel_confidence: str = "NONE"


@dataclass(frozen=True)
class FinishLapRange:
    low: int
    expected: int
    high: int


@dataclass(frozen=True)
class PitWindow:
    earliest_safe: int
    target: int
    fuel_limit: int
    state: str


@dataclass(frozen=True)
class PlannedStop:
    number: int
    lap: int
    earliest_safe: int
    fuel_limit: int
    fuel_to_add_liters: float | None
    final_fill: bool


@dataclass(frozen=True)
class RacePlanCalculation:
    available: bool
    reason: str | None
    candidate_minimum_stops: int | None
    minimum_stops: int | None
    stints_remaining: int | None
    finish: FinishLapRange | None
    current_autonomy_laps: int | None
    future_stint_capacity_laps: int | None
    window: PitWindow | None
    stops: tuple[PlannedStop, ...]
    final_fuel_required_liters: float | None
    safety_margin_laps: float | None
    confidence: str

    def to_dict(self):
        def convert(value):
            if hasattr(value, "__dataclass_fields__"):
                return {key: convert(getattr(value, key)) for key in value.__dataclass_fields__}
            if isinstance(value, tuple):
                return [convert(item) for item in value]
            return value
        return convert(self)


def _finite_positive(value):
    try:
        value=float(value)
        return value if value>0 and value<1e12 else None
    except (TypeError,ValueError):
        return None


def _finish_range_vnext(inputs, pit_stops=0):
    current=max(0,int(inputs.current_lap or 0))
    if inputs.laps_remaining is not None:
        try:
            remain=max(0,int(inputs.laps_remaining))
        except (TypeError,ValueError):
            remain=0
        finish=current+remain
        return FinishLapRange(finish,finish,finish)
    remaining=_finite_positive(inputs.remaining_time_seconds)
    own=_finite_positive(inputs.own_pace_seconds)
    if remaining is None or own is None:
        return None
    pit=max(0.0,float(inputs.pit_loss_seconds or 0.0))*max(0,int(pit_stops))
    low_time=max(0.0,remaining-pit)
    leader=_finite_positive(inputs.leader_pace_seconds) or own
    # Without leader lap-phase telemetry the exact checkered crossing is not
    # knowable. Bound it by up to one leader lap after session time expires.
    high_time=max(0.0,remaining+leader-pit)
    low_extra=max(0,floor(low_time/own+1e-9))
    high_extra=max(low_extra,ceil(high_time/own-1e-9))
    expected_extra=int(round((low_extra+high_extra)/2))
    return FinishLapRange(current+low_extra,current+expected_extra,current+high_extra)


def _capacity_laps(liters, use):
    liters=_finite_positive(liters);use=_finite_positive(use)
    if liters is None or use is None:
        return None
    return max(0,floor(liters/use+1e-9))


def _candidate_minimum_stops(inputs):
    current_capacity=_capacity_laps(inputs.current_fuel_liters,inputs.fuel_strategy_lpl)
    future_capacity=_capacity_laps(inputs.session_fuel_limit_liters,inputs.fuel_strategy_lpl)
    if current_capacity is None or future_capacity in (None,0):
        return None,None,None,None
    mandatory=max(0,int(inputs.mandatory_stops_remaining or 0))
    margin=max(0.0,float(inputs.margin_laps or 0.0))
    for stops in range(mandatory,65):
        finish=_finish_range_vnext(inputs,stops)
        if finish is None:
            return None,current_capacity,future_capacity,None
        required=max(0.0,finish.high-int(inputs.current_lap))+margin
        capacity=current_capacity+stops*future_capacity
        if capacity+1e-9>=required:
            safety=capacity-required
            return stops,current_capacity,future_capacity,safety
    return None,current_capacity,future_capacity,None


def _window_state(current_lap, earliest, target, fuel_limit):
    current=int(current_lap)
    if current >= target and current <= fuel_limit:
        return "BOX THIS LAP"
    if current == target-1:
        return "BOX NEXT LAP"
    if current < earliest:
        return "WINDOW CLOSED"
    if current <= fuel_limit:
        return "WINDOW OPEN"
    return "FUEL LIMIT PASSED"


def _build_windows_and_stops(inputs, stop_count, finish, current_capacity, future_capacity, first_target_override=None):
    if stop_count<=0:
        return None,(),None
    current=int(inputs.current_lap)
    use=_finite_positive(inputs.fuel_strategy_lpl)
    limit=_finite_positive(inputs.session_fuel_limit_liters)
    current_fuel=_finite_positive(inputs.current_fuel_liters)
    margin=max(0.0,float(inputs.margin_laps or 0.0))
    required_finish=finish.high+margin
    stops=[]
    previous_lap=current
    fuel_before_start=current_fuel
    for local_index in range(stop_count):
        remaining_stops=stop_count-local_index
        stint_capacity=current_capacity if local_index==0 else future_capacity
        fuel_limit=previous_lap+max(1,stint_capacity)
        earliest=max(previous_lap+1,ceil(required_finish-remaining_stops*future_capacity-1e-9))
        if earliest>fuel_limit:
            earliest=fuel_limit
        target=max(earliest,fuel_limit-1)
        target=min(target,fuel_limit)
        if local_index==0 and first_target_override is not None:
            try:forced=int(first_target_override)
            except (TypeError,ValueError):forced=None
            if forced is not None and earliest<=forced<=fuel_limit:
                target=forced

        laps_run=max(0,target-previous_lap)
        if local_index==0 and fuel_before_start is not None and use is not None:
            fuel_before=max(0.0,fuel_before_start-laps_run*use)
        elif limit is not None and use is not None:
            fuel_before=max(0.0,limit-laps_run*use)
        else:
            fuel_before=None

        final_fill=(local_index==stop_count-1)
        if final_fill and use is not None:
            required_after=max(0.0,required_finish-target)*use
            target_fuel=min(limit,required_after) if limit is not None else required_after
            add=max(0.0,target_fuel-fuel_before) if fuel_before is not None else target_fuel
            final_required=target_fuel
        else:
            add=max(0.0,limit-fuel_before) if limit is not None and fuel_before is not None else None
            final_required=None

        stops.append(PlannedStop(
            number=int(inputs.stops_completed)+local_index+1,
            lap=int(target),
            earliest_safe=int(earliest),
            fuel_limit=int(fuel_limit),
            fuel_to_add_liters=round(add,2) if add is not None else None,
            final_fill=final_fill,
        ))
        previous_lap=target
        current_capacity=future_capacity
        fuel_before_start=limit

    first=stops[0]
    window=PitWindow(
        first.earliest_safe,
        first.lap,
        first.fuel_limit,
        _window_state(inputs.current_lap,first.earliest_safe,first.lap,first.fuel_limit),
    )
    final_required=None
    if stops and stops[-1].final_fill and use is not None:
        final_required=max(0.0,required_finish-stops[-1].lap)*use
        if limit is not None:
            final_required=min(limit,final_required)
        final_required=round(final_required,2)
    return window,tuple(stops),final_required


def calculate_race_plan(inputs, *, forced_minimum_stops=None, first_target_override=None):
    candidate,current_capacity,future_capacity,safety=_candidate_minimum_stops(inputs)
    missing=[]
    if _finite_positive(inputs.own_pace_seconds) is None and inputs.laps_remaining is None:
        missing.append("PACE")
    if _finite_positive(inputs.current_fuel_liters) is None:
        missing.append("FUEL")
    if _finite_positive(inputs.fuel_strategy_lpl) is None:
        missing.append("FUEL_MODEL")
    if _finite_positive(inputs.session_fuel_limit_liters) is None:
        missing.append("FUEL_LIMIT")
    if candidate is None:
        return RacePlanCalculation(False,", ".join(missing) or "NO FEASIBLE PLAN",None,None,None,
                                   _finish_range_vnext(inputs,0),current_capacity,future_capacity,None,(),None,None,
                                   inputs.fuel_confidence or "NONE")
    minimum=candidate
    if forced_minimum_stops is not None:
        minimum=max(candidate,int(forced_minimum_stops))
    finish=_finish_range_vnext(inputs,minimum)
    window,stops,final_required=_build_windows_and_stops(
        inputs,minimum,finish,current_capacity,future_capacity,first_target_override
    )
    return RacePlanCalculation(
        True,None,candidate,minimum,minimum+1,finish,current_capacity,future_capacity,
        window,stops,final_required,round(float(safety),3) if safety is not None else None,
        inputs.fuel_confidence or "NONE"
    )


def simulate_stop_lap(inputs, candidate_lap, minimum_stops):
    """Answer whether pitting on a candidate lap preserves the chosen stop count."""
    try:
        candidate=int(candidate_lap);minimum=int(minimum_stops)
    except (TypeError,ValueError):
        return {"valid":False,"reason":"INVALID LAP"}
    if candidate<=int(inputs.current_lap):
        return {"valid":False,"reason":"PAST LAP"}
    use=_finite_positive(inputs.fuel_strategy_lpl)
    current_fuel=_finite_positive(inputs.current_fuel_liters)
    if use is None or current_fuel is None:
        return {"valid":False,"reason":"SIN DATO DE COMBUSTIBLE"}
    needed_to_candidate=(candidate-int(inputs.current_lap))*use
    if needed_to_candidate>current_fuel+1e-9:
        return {"valid":False,"reason":"FUEL LIMIT"}
    pace=_finite_positive(inputs.own_pace_seconds)
    if pace is None and inputs.laps_remaining is None:
        return {"valid":False,"reason":"SIN RITMO"}
    elapsed=(candidate-int(inputs.current_lap))*(pace or 0.0)
    remaining=None if inputs.remaining_time_seconds is None else max(0.0,float(inputs.remaining_time_seconds)-elapsed-float(inputs.pit_loss_seconds or 0.0))
    laps_remaining=None
    if inputs.laps_remaining is not None:
        laps_remaining=max(0,int(inputs.laps_remaining)-(candidate-int(inputs.current_lap)))
    post=RacePlanInputs(
        remaining_time_seconds=remaining,current_lap=candidate,own_pace_seconds=inputs.own_pace_seconds,
        current_fuel_liters=inputs.session_fuel_limit_liters,fuel_strategy_lpl=inputs.fuel_strategy_lpl,
        session_fuel_limit_liters=inputs.session_fuel_limit_liters,pit_loss_seconds=inputs.pit_loss_seconds,
        margin_laps=inputs.margin_laps,mandatory_stops_remaining=max(0,int(inputs.mandatory_stops_remaining)-1),
        laps_remaining=laps_remaining,leader_lap=inputs.leader_lap,leader_pace_seconds=inputs.leader_pace_seconds,
        stops_completed=int(inputs.stops_completed)+1,fuel_confidence=inputs.fuel_confidence,
    )
    after=calculate_race_plan(post)
    if not after.available:
        return {"valid":False,"reason":after.reason}
    total=1+int(after.candidate_minimum_stops)
    return {
        "valid":True,
        "candidateLap":candidate,
        "totalStopsFromNow":total,
        "preservesMinimum":total<=minimum,
        "addsStop":total>minimum,
    }


class StopCountStabilizer:
    """Hysteresis for stop-count changes; safety increases confirm faster."""
    def __init__(self, initial=None, removal_confirmations=3, addition_confirmations=2):
        self.stable=initial
        self.pending=None
        self.count=0
        self.removal_confirmations=max(1,int(removal_confirmations))
        self.addition_confirmations=max(1,int(addition_confirmations))

    def update(self, candidate, *, confidence="NONE", safety_margin_laps=None):
        if candidate is None:
            return self.stable,"INSUFFICIENT DATA"
        candidate=int(candidate)
        if self.stable is None:
            self.stable=candidate;self.pending=None;self.count=0
            return self.stable,"INITIAL PLAN"
        if candidate==self.stable:
            self.pending=None;self.count=0
            return self.stable,"STABLE"
        if self.pending!=candidate:
            self.pending=candidate;self.count=1
        else:
            self.count+=1
        removing=candidate<self.stable
        threshold=self.removal_confirmations if removing else self.addition_confirmations
        confidence_ok=confidence in ("MEDIUM","HIGH")
        margin_ok=(safety_margin_laps is not None and safety_margin_laps>=.5)
        if removing and (not confidence_ok or not margin_ok):
            return self.stable,"STOP REMOVAL POSSIBLE"
        if self.count>=threshold:
            self.stable=candidate;self.pending=None;self.count=0
            return self.stable,"STOP REMOVAL CONFIRMED" if removing else "STOP ADDITION CONFIRMED"
        return self.stable,"STOP REMOVAL POSSIBLE" if removing else "STOP ADDITION POSSIBLE"


class RacePlanEngine:
    """Stateful wrapper preserving initialPlan while currentPlan evolves."""
    def __init__(self):
        self.initial_plan=None
        self.current_plan=None
        self.stabilizer=StopCountStabilizer()
        self.last_transition=""
        self.committed_target_lap=None

    def update(self, inputs):
        candidate=calculate_race_plan(inputs)
        if not candidate.available:
            self.current_plan=candidate
            return candidate
        previous_stable=self.stabilizer.stable
        stable,state=self.stabilizer.update(
            candidate.candidate_minimum_stops,
            confidence=inputs.fuel_confidence,
            safety_margin_laps=candidate.safety_margin_laps,
        )
        if stable!=previous_stable:
            self.committed_target_lap=None
        target=self.committed_target_lap
        if target is not None and candidate.window is not None:
            if not (candidate.window.earliest_safe<=target<=candidate.window.fuel_limit):
                target=None
        plan=calculate_race_plan(inputs,forced_minimum_stops=stable,first_target_override=target)
        if plan.window is not None:
            if target is None:
                self.committed_target_lap=plan.window.target
            elif plan.window.earliest_safe<=target<=plan.window.fuel_limit:
                self.committed_target_lap=target
        self.last_transition=state
        if self.initial_plan is None and plan.available:
            self.initial_plan=plan
        self.current_plan=plan
        return plan

    def snapshot(self):
        return {
            "initialPlan":self.initial_plan.to_dict() if self.initial_plan else None,
            "currentPlan":self.current_plan.to_dict() if self.current_plan else None,
            "stableMinimumStops":self.stabilizer.stable,
            "pendingMinimumStops":self.stabilizer.pending,
            "pendingCount":self.stabilizer.count,
            "committedTargetLap":self.committed_target_lap,
            "transition":self.last_transition,
        }

    def restore_runtime(self, payload):
        """Restore hysteresis state without pretending serialized plans are live dataclasses."""
        payload=payload or {}
        self.stabilizer.stable=payload.get("stableMinimumStops")
        self.stabilizer.pending=payload.get("pendingMinimumStops")
        try:self.stabilizer.count=max(0,int(payload.get("pendingCount") or 0))
        except (TypeError,ValueError):self.stabilizer.count=0
        try:self.committed_target_lap=int(payload.get("committedTargetLap")) if payload.get("committedTargetLap") is not None else None
        except (TypeError,ValueError):self.committed_target_lap=None
        self.last_transition=str(payload.get("transition") or "")
        return self
