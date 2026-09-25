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
