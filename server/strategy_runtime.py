"""Runtime adapter between iRacing snapshots and the pure strategy engine."""
from __future__ import annotations
from server.strategy_engine import StrategyInputs,calculate_strategy

def clock_text(value):
    if value is None:return "—"
    value=max(0,int(round(float(value))));hours,rem=divmod(value,3600);minutes,seconds=divmod(rem,60);return f"{hours}:{minutes:02d}:{seconds:02d}"

def strategy_payload(*,remaining_time_seconds,average_lap_seconds,pit_loss_seconds,current_lap,current_fuel_liters,consumption_liters_per_lap,tank_capacity_liters,base_stint_laps,extended_stint_laps,current_stint_laps_completed,stops_completed,target_total_stops=None,driver_assignments=None,completed_stints=None,current_driver=None):
    if not remaining_time_seconds or remaining_time_seconds<=0 or not average_lap_seconds or average_lap_seconds<=0:
        return {"available":False,"reason":"Falta tiempo restante o ritmo medio fiable.","remainingTime":clock_text(remaining_time_seconds)},target_total_stops
    inputs=StrategyInputs(remaining_time_seconds=remaining_time_seconds,average_lap_seconds=average_lap_seconds,pit_loss_seconds=max(0.0,pit_loss_seconds or 0.0),current_lap=max(0,int(current_lap or 0)),current_fuel_liters=current_fuel_liters,consumption_liters_per_lap=consumption_liters_per_lap,tank_capacity_liters=tank_capacity_liters,base_stint_laps=max(1,int(base_stint_laps)),extended_stint_laps=max(1,int(extended_stint_laps)),current_stint_laps_completed=max(0,int(current_stint_laps_completed or 0)),stops_completed=max(0,int(stops_completed or 0)),target_total_stops=target_total_stops,driver_assignments=driver_assignments or {})
    result=calculate_strategy(inputs)
    if target_total_stops is None:target_total_stops=result.target_total_stops
    objective=result.extended if result.extended.stops_remaining<result.base.stops_remaining else result.base;current_stint_number=inputs.stops_completed+1;total_stints=inputs.stops_completed+objective.stints_remaining;next_stop=objective.stop_estimates[0] if objective.stop_estimates else None;current_target=objective.stints[0].laps if objective.stints else 0;extension=result.extension
    if not extension.avoidable:state,verdict="red","PARADA ADICIONAL"
    elif extension.extra_laps_needed>0:state,verdict="yellow","AHORRO NECESARIO"
    else:state,verdict="green","OBJETIVO CUBIERTO"
    history=list(completed_stints or []);timeline=[]
    for item in history[-5:]:timeline.append({"number":item.get("number"),"laps":item.get("laps"),"driver":item.get("driver"),"double":bool(item.get("double")),"status":"done","endLap":item.get("endLap")})
    for local,stint in enumerate(objective.stints[:8],1):
        global_number=inputs.stops_completed+local;assigned=(driver_assignments or {}).get(global_number) or stint.driver;previous_driver=timeline[-1].get("driver") if timeline else None
        timeline.append({"number":global_number,"laps":stint.laps,"driver":assigned,"double":bool(assigned and previous_driver==assigned),"status":"current" if local==1 else "future","endLap":stint.end_lap})
    base=result.base;extended=result.extended
    payload={"available":True,"state":state,"verdict":verdict,"remainingTime":clock_text(remaining_time_seconds),"averageLap":average_lap_seconds,"currentStint":f"S{current_stint_number} / {total_stints}","currentStintNumber":current_stint_number,"totalStints":total_stints,"currentDriver":current_driver or "—","boxLap":f"VUELTA {next_stop.lap}" if next_stop else "BANDERA","boxEta":clock_text(next_stop.eta_seconds) if next_stop else "—","autonomy":f"{objective.current_autonomy_laps} vueltas","stopsRemaining":objective.stops_remaining,"lastStopAvoidable":bool(extended.stops_remaining<base.stops_remaining),"extensionNeeded":extension.extra_laps_needed,"extensionAvailable":extension.extra_laps_available,"extensionText":extension.distribution_text,"targetThisStint":f"{current_target} vueltas" if current_target else "BANDERA","projectedLaps":objective.projected_laps,"lastStintLaps":objective.last_stint_laps,"fuelNeeded":f"{objective.total_fuel_needed_liters:.1f} L" if objective.total_fuel_needed_liters is not None else "—","fuelMargin":f"{objective.final_stint_fuel_margin_liters:.1f} L" if objective.final_stint_fuel_margin_liters is not None else "—","base":{"stintLaps":base.stint_laps,"stints":base.stints_remaining,"stops":base.stops_remaining,"lastStintLaps":base.last_stint_laps,"projectedLaps":base.projected_laps},"extended":{"stintLaps":extended.stint_laps,"stints":extended.stints_remaining,"stops":extended.stops_remaining,"lastStintLaps":extended.last_stint_laps,"projectedLaps":extended.projected_laps},"timeline":timeline,"settings":{"baseStintLaps":inputs.base_stint_laps,"extendedStintLaps":inputs.extended_stint_laps,"pitLossSeconds":inputs.pit_loss_seconds}}
    return payload,target_total_stops


# ---------------------------------------------------------------------------
# Race Plan vNext runtime adapter. No polling is performed here.
# ---------------------------------------------------------------------------
from configparser import ConfigParser
from pathlib import Path
import math

try:
    from server.fuel_model import (
        FuelLapSample, FuelModel, GREEN_FULL, OUT_LAP, IN_LAP, PIT_LAP, CAUTION,
    )
    from server.pit_stop_engine import PitLearningModel, ObservedPitStop
    from server.race_state import RaceIdentity, RaceState, session_fuel_limit
    from server.strategy_engine import RacePlanInputs, RacePlanEngine
    from server.strategy_store import StrategyStore
except ModuleNotFoundError:
    from fuel_model import FuelLapSample, FuelModel, GREEN_FULL, OUT_LAP, IN_LAP, PIT_LAP, CAUTION
    from pit_stop_engine import PitLearningModel, ObservedPitStop
    from race_state import RaceIdentity, RaceState, session_fuel_limit
    from strategy_engine import RacePlanInputs, RacePlanEngine
    from strategy_store import StrategyStore


CAUTION_FLAGS = 0x0008 | 0x0100 | 0x4000 | 0x8000


def _number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):
        return None


def _positive(value):
    value=_number(value)
    return value if value is not None and value>0 else None


def _valid_remaining(value):
    value=_number(value)
    if value is None or value<0 or value>=604800:
        return None
    return value


def _valid_laps_remaining(value):
    value=_number(value)
    if value is None or value<0 or value>=32767:
        return None
    return int(math.ceil(value))


def fuel_confidence_for_source(source):
    source=str(source or "").upper()
    if source=="REAL LOCAL":
        return "HIGH"
    if source=="SDK OBSERVADO":
        return "MEDIUM"
    if "ESTIMADO" in source or "MANUAL" in source:
        return "LOW"
    return "NONE"


def is_caution_flag(flags):
    try:return bool(int(flags)&CAUTION_FLAGS)
    except (TypeError,ValueError):return False


def leader_from_results(results, car_laps=None, last_laps=None):
    rows=[row for row in (results or {}).values() if isinstance(row,dict)]
    leader=min(rows,key=lambda row:(row.get("Position") is None,row.get("Position") or 999999),default=None)
    if not leader:return None,None,None
    try:idx=int(leader.get("CarIdx"))
    except (TypeError,ValueError):idx=None
    lap=None
    if idx is not None and car_laps is not None and idx<len(car_laps):
        lap=_number(car_laps[idx])
    if lap is None:lap=_number(leader.get("LapsComplete"))
    pace=None
    if idx is not None and last_laps is not None and idx<len(last_laps):
        pace=_positive(last_laps[idx])
    pace=pace or _positive(leader.get("LastTime")) or _positive(leader.get("FastestTime"))
    return idx,int(lap) if lap is not None else None,pace


def read_iracing_auto_fuel_margin(paths=None):
    candidates=list(paths or [])
    if not candidates:
        home=Path.home()
        candidates=[home/"Documents"/"iRacing"/"app.ini"]
    for path in candidates:
        try:
            path=Path(path)
            if not path.is_file():continue
            config=ConfigParser()
            config.read(path,encoding="utf-8")
            for section in ("Pit Service","PitService"):
                if config.has_option(section,"autoFuelDefaultMarginLaps"):
                    value=_number(config.get(section,"autoFuelDefaultMarginLaps"))
                    if value is not None and value>=0:
                        return float(value),"IRACING_APP_INI_DEFAULT"
        except (OSError,ValueError):
            continue
    return 0.0,"UNKNOWN"


class RacePlanRuntime:
    """Frame-driven adapter around the pure Race Plan engine.

    It never opens the SDK, never starts a timer, and never writes per frame.
    """

    def __init__(self, root, margin_paths=None):
        self.root=Path(root)
        self.store=StrategyStore(self.root)
        self.engine=RacePlanEngine()
        self.fuel_model=FuelModel()
        self.pit_learning=PitLearningModel()
        self.identity=None
        self.history_key=None
        self.last_completed_laps=None
        self.lap_start_fuel=None
        self.lap_had_pit=False
        self.lap_had_caution=False
        self.current_lap_out=False
        self.last_on_pit=None
        self.pit_entry_time=None
        self.pit_entry_fuel=None
        self.pit_entry_lap=None
        self.stops_completed=0
        self.stop_history=[]
        self.last_driver=None
        self.last_state=None
        self.last_plan=None
        self.last_signature=None
        self.last_persisted_signature=None
        self.sample_ids=set()
        self.own_pace_samples=[]
        self.leader_pace_samples=[]
        self.last_leader_lap=None
        self.margin_laps,self.margin_source=read_iracing_auto_fuel_margin(margin_paths)
        self.auto_fuel_enabled=None
        self.auto_fuel_active=None
        self.pit_sv_fuel=None

    def detach(self):
        self.identity=None
        self.history_key=None
        self.last_signature=None
        self.last_state=None
        self.last_plan=None

    def _history_identity(self, identity):
        return (
            identity.car_id if identity.car_id not in (None,"") else identity.car_number,
            identity.track_id,
            identity.layout or "default",
        )

    def _load_identity(self, identity):
        if self.identity is not None and self.identity.key==identity.key:
            return
        self.identity=identity
        self.history_key=self._history_identity(identity)
        self.engine=RacePlanEngine()
        self.fuel_model=FuelModel()
        self.pit_learning=PitLearningModel()
        self.last_completed_laps=None
        self.lap_start_fuel=None
        self.lap_had_pit=False
        self.lap_had_caution=False
        self.current_lap_out=False
        self.last_on_pit=None
        self.pit_entry_time=None
        self.pit_entry_fuel=None
        self.pit_entry_lap=None
        self.stops_completed=0
        self.stop_history=[]
        self.last_driver=None
        self.sample_ids=set()
        self.own_pace_samples=[]
        self.leader_pace_samples=[]
        self.last_leader_lap=None
        history=self.store.load_history(*self.history_key) or {}
        for entry in history.get("entries",[]):
            if not isinstance(entry,dict) or entry.get("raceKey")==identity.key:continue
            item=entry.get("sample")
            if not isinstance(item,dict):continue
            try:self.fuel_model.add(FuelLapSample(**item),historical=True)
            except TypeError:continue
        saved=self.store.load(identity.key) or {}
        runtime=saved.get("runtime") if isinstance(saved,dict) else {}
        if isinstance(runtime,dict):
            self.stops_completed=max(0,int(runtime.get("stopsCompleted") or 0))
            self.stop_history=list(runtime.get("stopHistory") or [])[-64:]
            self.last_completed_laps=runtime.get("lastCompletedLaps")
            self.lap_start_fuel=_positive(runtime.get("lapStartFuel"))
            self.last_on_pit=runtime.get("lastOnPit")
            self.last_driver=runtime.get("lastDriver")
            self.sample_ids=set(str(v) for v in runtime.get("sampleIds",[]))
            self.own_pace_samples=[float(v) for v in runtime.get("ownPaceSamples",[]) if _positive(v) is not None][-12:]
            self.leader_pace_samples=[float(v) for v in runtime.get("leaderPaceSamples",[]) if _positive(v) is not None][-12:]
            self.last_leader_lap=runtime.get("lastLeaderLap")
        model=saved.get("fuelModel") if isinstance(saved,dict) else None
        if isinstance(model,dict):
            restored=FuelModel.restore(model)
            # Historical store remains authoritative across races; current data
            # restores only the interrupted race.
            self.fuel_model.current=restored.current
        engine=saved.get("engine") if isinstance(saved,dict) else None
        if isinstance(engine,dict):self.engine.restore_runtime(engine)
        pit_learning=saved.get("pitLearning") if isinstance(saved,dict) else None
        if isinstance(pit_learning,list):self.pit_learning=PitLearningModel.restore(pit_learning)

    def _persist_history_sample(self, sample, sample_id):
        history=self.store.load_history(*self.history_key) or {}
        entries=[e for e in history.get("entries",[]) if isinstance(e,dict) and e.get("id")!=sample_id]
        entries.append({"id":sample_id,"raceKey":self.identity.key,"sample":sample.to_dict()})
        history["entries"]=entries[-400:]
        self.store.save_history(*self.history_key,history)

    def _add_sample(self, sample):
        if self.identity is None:return False
        sample_id=f"{self.identity.key}:{sample.lap}"
        if sample_id in self.sample_ids:return False
        self.sample_ids.add(sample_id)
        self.fuel_model.add(sample)
        if sample.classification==GREEN_FULL and sample.liters is not None and sample.valid:
            self._persist_history_sample(sample,sample_id)
        return True

    def record_local_lap(self, lap, liters, valid, lap_time_seconds, *, on_pit=False, caution=False):
        if self.identity is None:return False
        classification=CAUTION if caution else PIT_LAP if on_pit else GREEN_FULL if valid else "INVALID"
        pace=_positive(lap_time_seconds)
        added=self._add_sample(FuelLapSample(
            int(lap),_number(liters),classification,pace,"REAL LOCAL",bool(valid)
        ))
        if added and classification==GREEN_FULL and pace is not None:
            self.own_pace_samples.append(pace);self.own_pace_samples=self.own_pace_samples[-12:]
        return added

    def _observed_fuel(self, value, source):
        if str(source or "") not in ("REAL LOCAL","SDK OBSERVADO"):
            return None
        return _positive(value)

    def _record_remote_boundary(self, completed, fuel, source, lap_time):
        if self.last_completed_laps is None:
            self.last_completed_laps=completed
            self.lap_start_fuel=self._observed_fuel(fuel,source)
            return False
        if completed is None or completed<=self.last_completed_laps:
            return False
        start=self.lap_start_fuel
        end=self._observed_fuel(fuel,source)
        usage=(start-end) if start is not None and end is not None and start>=end else None
        if self.current_lap_out:
            classification=OUT_LAP
        elif self.lap_had_pit:
            classification=IN_LAP
        elif self.lap_had_caution:
            classification=CAUTION
        else:
            classification=GREEN_FULL
        pace=_positive(lap_time)
        added=self._add_sample(FuelLapSample(
            int(completed),usage,classification,pace,str(source or "SDK"),True
        ))
        if added and classification==GREEN_FULL and pace is not None:
            self.own_pace_samples.append(pace);self.own_pace_samples=self.own_pace_samples[-12:]
        self.last_completed_laps=completed
        self.lap_start_fuel=end
        self.lap_had_pit=bool(self.last_on_pit)
        self.lap_had_caution=False
        self.current_lap_out=False
        return added

    def _observe_pit(self, on_pit, session_time, fuel, source, completed):
        changed=False
        if self.last_on_pit is None:
            self.last_on_pit=bool(on_pit)
            if on_pit:self.lap_had_pit=True
            return changed
        if on_pit:self.lap_had_pit=True
        if bool(on_pit) and not self.last_on_pit:
            self.stops_completed+=1
            self.pit_entry_time=_number(session_time)
            self.pit_entry_fuel=self._observed_fuel(fuel,source)
            self.pit_entry_lap=completed
            plan=self.last_plan
            planned=False
            if plan and plan.window:
                planned=plan.window.earliest_safe<=int(completed or 0)<=plan.window.fuel_limit
            self.stop_history.append({
                "lap":completed,"status":"PLANNED" if planned else "UNPLANNED STOP",
                "driver":self.last_driver,"entryTime":self.pit_entry_time,
            })
            changed=True
        elif not bool(on_pit) and self.last_on_pit:
            exit_time=_number(session_time)
            exit_fuel=self._observed_fuel(fuel,source)
            elapsed=(exit_time-self.pit_entry_time) if exit_time is not None and self.pit_entry_time is not None and exit_time>=self.pit_entry_time else None
            fuel_added=(exit_fuel-self.pit_entry_fuel) if exit_fuel is not None and self.pit_entry_fuel is not None and exit_fuel>=self.pit_entry_fuel else None
            if elapsed is not None:
                self.pit_learning.add(ObservedPitStop(elapsed,None,fuel_added_liters=fuel_added))
            if self.stop_history:
                self.stop_history[-1].update({"exitTime":exit_time,"pitLaneSeconds":elapsed,"fuelAddedLiters":fuel_added})
            self.current_lap_out=True
            self.lap_start_fuel=exit_fuel or self.lap_start_fuel
            changed=True
        self.last_on_pit=bool(on_pit)
        return changed

    def observe_frame(self, *, identity, session_type, remaining_seconds, session_total_seconds,
                      current_lap, completed_laps, own_pace_seconds, leader_lap, leader_pace_seconds,
                      laps_remaining, current_driver, current_fuel_liters, fuel_source,
                      physical_tank_liters, max_fuel_pct, on_pit_road, session_flags,
                      pit_loss_seconds=30.0, mandatory_stops_remaining=0, require_tire_change=False,
                      min_drivers=None, max_drivers=None, session_time=None, last_lap_time=None,
                      auto_fuel_enabled=None, auto_fuel_active=None, pit_sv_fuel=None,
                      margin_laps=None, margin_source=None):
        self._load_identity(identity)
        fuel_confidence=fuel_confidence_for_source(fuel_source)
        session_limit=session_fuel_limit(physical_tank_liters,max_fuel_pct)
        caution=is_caution_flag(session_flags)
        if leader_lap is not None and leader_lap!=self.last_leader_lap and _positive(leader_pace_seconds) is not None:
            self.leader_pace_samples.append(float(leader_pace_seconds));self.leader_pace_samples=self.leader_pace_samples[-12:];self.last_leader_lap=leader_lap
        self.lap_had_caution=self.lap_had_caution or caution
        self.last_driver=current_driver or self.last_driver
        self.auto_fuel_enabled=auto_fuel_enabled
        self.auto_fuel_active=auto_fuel_active
        self.pit_sv_fuel=_number(pit_sv_fuel)
        pit_changed=self._observe_pit(bool(on_pit_road),session_time,current_fuel_liters,fuel_source,completed_laps)
        fuel_changed=self._record_remote_boundary(completed_laps,current_fuel_liters,fuel_source,last_lap_time)
        estimate=self.fuel_model.estimate(
            margin_laps=self.margin_laps if margin_laps is None else margin_laps,
            margin_source=self.margin_source if margin_source is None else margin_source,
        )
        def median_pace(values,fallback):
            clean=sorted(v for v in values[-7:] if _positive(v) is not None)
            return clean[len(clean)//2] if len(clean)>=3 else _positive(fallback)
        stable_own_pace=median_pace(self.own_pace_samples,own_pace_seconds)
        stable_leader_pace=median_pace(self.leader_pace_samples,leader_pace_seconds)
        state=RaceState(
            identity=identity,session_type=str(session_type or ""),
            remaining_seconds=_valid_remaining(remaining_seconds),
            session_total_seconds=_valid_remaining(session_total_seconds),
            current_lap=max(0,int(current_lap or 0)),completed_laps=max(0,int(completed_laps or 0)),
            own_pace_seconds=stable_own_pace,leader_lap=leader_lap,
            leader_pace_seconds=stable_leader_pace,laps_remaining=_valid_laps_remaining(laps_remaining),
            current_driver=current_driver,current_fuel_liters=_positive(current_fuel_liters),
            fuel_source=str(fuel_source or "SIN DATO"),fuel_confidence=fuel_confidence,
            physical_tank_liters=_positive(physical_tank_liters),session_fuel_limit_liters=session_limit,
            on_pit_road=bool(on_pit_road),session_flags=int(session_flags) if _number(session_flags) is not None else None,
            mandatory_stops_remaining=max(0,int(mandatory_stops_remaining or 0)),
            require_tire_change=bool(require_tire_change),min_drivers=min_drivers,max_drivers=max_drivers,
        )
        margin=estimate.margin_laps
        inputs=RacePlanInputs(
            remaining_time_seconds=state.remaining_seconds,current_lap=state.completed_laps,
            own_pace_seconds=state.own_pace_seconds,current_fuel_liters=state.current_fuel_liters,
            fuel_strategy_lpl=estimate.strategy_lpl,session_fuel_limit_liters=state.session_fuel_limit_liters,
            pit_loss_seconds=max(0.0,float(pit_loss_seconds or 0.0)),margin_laps=margin,
            mandatory_stops_remaining=state.mandatory_stops_remaining,laps_remaining=state.laps_remaining,
            leader_lap=state.leader_lap,leader_pace_seconds=state.leader_pace_seconds,
            stops_completed=self.stops_completed,fuel_confidence=estimate.confidence,
        )
        signature=(
            state.identity.key,state.completed_laps,int((state.remaining_seconds or 0)//15),
            round(state.current_fuel_liters,1) if state.current_fuel_liters is not None else None,
            round(estimate.strategy_lpl,3) if estimate.strategy_lpl is not None else None,
            state.leader_lap,round(state.leader_pace_seconds,1) if state.leader_pace_seconds else None,
            state.current_driver,state.on_pit_road,self.stops_completed,
        )
        if signature!=self.last_signature or pit_changed or fuel_changed:
            self.last_plan=self.engine.update(inputs)
            self.last_signature=signature
        self.last_state=state
        self._persist_if_changed(estimate)
        return self.payload(estimate)

    def _persist_if_changed(self, estimate):
        if self.identity is None:return
        payload={
            "identity":self.identity.to_dict(),
            "raceState":self.last_state.to_dict() if self.last_state else None,
            "fuelModel":self.fuel_model.snapshot(),
            "fuelEstimate":estimate.to_dict(),
            "engine":self.engine.snapshot(),
            "pitLearning":self.pit_learning.snapshot(),
            "runtime":{
                "stopsCompleted":self.stops_completed,"stopHistory":self.stop_history[-64:],
                "lastCompletedLaps":self.last_completed_laps,"lapStartFuel":self.lap_start_fuel,
                "lastOnPit":self.last_on_pit,"lastDriver":self.last_driver,
                "sampleIds":sorted(self.sample_ids)[-200:],
                "ownPaceSamples":self.own_pace_samples[-12:],"leaderPaceSamples":self.leader_pace_samples[-12:],
                "lastLeaderLap":self.last_leader_lap,
            },
            "iracingFuelCalculator":{
                "autoFuelEnabled":self.auto_fuel_enabled,"autoFuelActive":self.auto_fuel_active,
                "pitSvFuelLiters":self.pit_sv_fuel,"marginLaps":estimate.margin_laps,
                "marginSource":estimate.margin_source,
            },
        }
        marker=(
            self.last_state.completed_laps if self.last_state else None,self.stops_completed,
            len(self.fuel_model.current),self.engine.stabilizer.stable,self.engine.stabilizer.pending,
            self.engine.committed_target_lap,self.last_driver,
        )
        if marker!=self.last_persisted_signature:
            self.store.save(self.identity.key,payload)
            self.last_persisted_signature=marker

    def payload(self, estimate=None):
        estimate=estimate or self.fuel_model.estimate(margin_laps=self.margin_laps,margin_source=self.margin_source)
        plan=self.last_plan
        return {
            "available":bool(plan and plan.available),
            "raceIdentity":self.identity.to_dict() if self.identity else None,
            "raceState":self.last_state.to_dict() if self.last_state else None,
            "fuelModel":estimate.to_dict(),
            "fuelCalculator":{
                "autoFuelEnabled":self.auto_fuel_enabled,"autoFuelActive":self.auto_fuel_active,
                "pitSvFuelLiters":self.pit_sv_fuel,"marginLaps":estimate.margin_laps,
                "marginSource":estimate.margin_source,
            },
            "plan":plan.to_dict() if plan else None,
            "initialPlan":self.engine.snapshot().get("initialPlan"),
            "currentPlan":self.engine.current_plan.to_dict() if self.engine.current_plan else None,
            "transition":self.engine.last_transition,
            "stopsCompleted":self.stops_completed,
            "stopHistory":self.stop_history[-16:],
            "pitLearning":{"pitLaneSeconds":self.pit_learning.learned_pit_lane_seconds()},
        }
