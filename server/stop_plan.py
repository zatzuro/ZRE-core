"""Future stop instructions recalculated from current race time and car state.

Overrides are per stop and per field; nothing is projected from race start.
"""
from math import floor, isfinite


def race_plan(*, remaining_seconds, current_lap, lap_seconds, pit_seconds,
              current_fuel=None, consumption=None, tank=None, stops_completed=0,
              current_driver=None, driver_assignments=None, overrides=None,
              completed=None, stint_start_lap=None, base_stint_laps=None,
              extended_stint_laps=None):
    """Forward-only race plan; completed stops are immutable input history."""
    def positive(value):
        try:
            value=float(value)
            return value if isfinite(value) and value>0 else None
        except (TypeError,ValueError):return None
    pace=positive(lap_seconds);use=positive(consumption);capacity=positive(tank)
    remaining=positive(remaining_seconds)
    try:
        fuel=float(current_fuel) if current_fuel is not None else None
        if fuel is not None and (not isfinite(fuel) or fuel<0):fuel=None
    except (ValueError,TypeError):fuel=None
    projected=floor(remaining/pace) if remaining and pace else None
    autonomy=floor(fuel/use) if fuel is not None and use else None
    def scenario(length):
        length=positive(length)
        if projected is None or length is None:return None
        length=max(1,int(length))
        # Configured stint targets are estimates, never telemetry-derived fuel.
        initial=autonomy if autonomy is not None else length
        remaining_laps=max(0,projected-initial)
        stops=(remaining_laps+length-1)//length if remaining_laps else 0
        last=projected-initial-(stops-1)*length if stops else min(projected,initial)
        return {'stintLaps':length,'stops':stops,'lastStintLaps':last,
                'source':'ESTIMADO · OBJETIVO CONFIGURADO' if autonomy is None else 'ESTIMADO · FUEL'}
    base_scenario=scenario(base_stint_laps)
    extended_scenario=scenario(extended_stint_laps)
    missing=[name for name,value in [('TIEMPO RESTANTE',remaining),('RITMO',pace),
        ('FUEL',fuel),('CONSUMO',use),('CAPACIDAD',capacity)] if value is None]
    current_stint=int(stops_completed)+1
    stint_laps=max(0,int(current_lap)-int(stint_start_lap)) if stint_start_lap is not None else None
    base={'available':False,'state':'SIN DATOS SUFICIENTES','missing':missing,
          'stops':[],'stopsRemaining':None,'stintsRemaining':None,
          'finishLap':None,'lastStintLaps':None,'lastStopAvoidable':None,
          'projectedLaps':projected,'autonomyLaps':autonomy,'minimumStops':None,
          'currentStint':current_stint,'stintLaps':stint_laps,
          'completed':list(completed or []),'warnings':[],
          'remainingSeconds':remaining,'currentLap':current_lap,
          'baseScenario':base_scenario,'dynamicScenario':extended_scenario,
          'estimatedStops':extended_scenario['stops'] if extended_scenario else None,
          'estimatedLastStintLaps':extended_scenario['lastStintLaps'] if extended_scenario else None,
          'marginLaps':None,'extensionNeededLaps':None}
    if missing:return base
    try:
        plan=build_stop_plan(remaining_seconds=remaining,current_lap=current_lap,
            lap_seconds=pace,pit_seconds=pit_seconds,stint_laps=floor(capacity/use),
            current_fuel=fuel,consumption=use,tank=capacity,
            stops_completed=stops_completed,current_driver=current_driver,
            driver_assignments=driver_assignments,overrides=overrides)
    except (ValueError,TypeError,OverflowError,ZeroDivisionError):
        return dict(base,state='ERROR DE CÁLCULO',missing=[])
    if not plan['available']:return dict(base,state='ERROR DE CÁLCULO',missing=[])
    stops=plan['stops'];last=stops[-1] if stops else None
    if not last:avoidable='SÍ'
    else:
        # The final stop is only possibly avoidable if its fuel deficit is no
        # greater than a lap; exact pit-loss effects need a race-time margin.
        laps_after=max(0,plan['finishLap']-last['lap'])
        deficit=(laps_after+max(0,float(pit_seconds or 0))/pace)*use-last['fuelBefore']
        avoidable='SÍ' if deficit<=0 else 'POSIBLE' if deficit<=use else 'NO'
    finish_lap=plan['finishLap'];warnings=plan['warnings']
    plan.update(base,available=True,state='PLAN DISPONIBLE',missing=[],
                stops=stops,stopsRemaining=len(stops),stintsRemaining=len(stops)+1,
                finishLap=finish_lap,warnings=warnings,
                projectedLaps=projected,autonomyLaps=autonomy,
                minimumStops=len(stops),lastStopAvoidable=avoidable,
                lastStintLaps=finish_lap-(last['lap'] if last else int(current_lap)))
    if last and fuel is not None and use:
        laps_after=max(0,finish_lap-last['lap'])
        available_laps=last['fuelBefore']/use
        plan['marginLaps']=round(available_laps-laps_after,1)
        plan['extensionNeededLaps']=round(max(0,laps_after+max(0,float(pit_seconds or 0))/pace-available_laps),1)
    else:
        plan['marginLaps']=0 if not last else None
        plan['extensionNeededLaps']=0 if not last else None
    return plan


def build_stop_plan(*,remaining_seconds,current_lap,lap_seconds,pit_seconds,stint_laps,
                    current_fuel=None,consumption=None,tank=None,stops_completed=0,
                    current_driver=None,driver_assignments=None,overrides=None):
    if remaining_seconds is None or remaining_seconds <= 0 or not lap_seconds or lap_seconds <= 0:
        return {'available':False,'stops':[],'stopsRemaining':None,'finishLap':None}
    time_left=float(remaining_seconds);lap=int(current_lap);pit=max(0,float(pit_seconds or 0));
    pace=float(lap_seconds);capacity=max(1,int(stint_laps));fuel=float(current_fuel) if current_fuel is not None else None
    use=float(consumption) if consumption is not None and consumption>0 else None
    tank=float(tank) if tank is not None and tank>0 else None
    driver_assignments=driver_assignments or {};overrides=overrides or {};driver=current_driver
    stops=[];warnings=[]
    for _ in range(64):
        fuel_laps=floor(max(0,fuel)/use+1e-9) if fuel is not None and use else capacity
        auto_length=max(1,min(capacity,fuel_laps))
        stop_number=int(stops_completed)+len(stops)+1
        override=overrides.get(stop_number,overrides.get(str(stop_number),{})) or {}
        auto_lap=lap+auto_length
        manual_lap=override.get('lap')
        chosen_lap=int(manual_lap) if manual_lap is not None else auto_lap
        chosen_lap=max(lap+1,chosen_lap)
        # A timed race finishes before a future scheduled stop is necessary.
        if chosen_lap*0 + (chosen_lap-lap)*pace >= time_left:
            lap+=max(0,floor(time_left/pace+1e-9));break
        length=chosen_lap-lap
        if fuel is not None and use and length*use>fuel+1e-9:
            warnings.append(f'PARADA {stop_number}: combustible insuficiente para V{chosen_lap}')
        if fuel is not None and use:fuel=max(0,fuel-length*use)
        time_left-=length*pace
        lap=chosen_lap
        fuel_before=fuel
        auto_driver=driver_assignments.get(stop_number+1) or driver
        assigned=override.get('driver') or auto_driver
        fuel_action=override.get('fuel') or 'auto';liters=override.get('liters')
        auto_liters=max(0,tank-fuel) if tank is not None and fuel is not None else None
        if fuel_action in ('auto','fill'):
            liters=auto_liters if fuel_action=='auto' else (max(0,tank-fuel) if tank is not None and fuel is not None else None)
            fuel=tank if tank is not None else None
        elif fuel_action=='add':
            liters=float(liters or 0)
            fuel=min(tank,fuel+liters) if fuel is not None and tank is not None else fuel+liters if fuel is not None else None
        elif fuel_action=='none':liters=0
        stops.append({'number':stop_number,'suggestedLap':auto_lap,'manualLap':manual_lap,
                      'lap':lap,'autoDriver':auto_driver,'driver':assigned,'manualDriver':override.get('driver'),
                      'autoFuel':'LLENAR' if tank is not None else 'SIN DATO',
                      'fuelAction':fuel_action,'liters':round(liters,1) if liters is not None else None,
                      'fuelBefore':fuel_before,
                      'manualLiters':override.get('liters'),'status':'pending',
                      'source':'MANUAL' if override else 'AUTO'})
        driver=assigned
        time_left-=pit
        if time_left<=0:break
    else:warnings.append('No se pudo cerrar el plan dentro de 64 paradas')
    return {'available':True,'stops':stops,'stopsRemaining':len(stops),'finishLap':lap,'warnings':warnings}
