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
