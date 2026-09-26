"""Future stop instructions recalculated from current race time and car state.

Overrides are per stop and per field; nothing is projected from race start.
"""
from math import floor


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
                      'manualLiters':override.get('liters'),'status':'pending',
                      'source':'MANUAL' if override else 'AUTO'})
        driver=assigned
        time_left-=pit
        if time_left<=0:break
    else:warnings.append('No se pudo cerrar el plan dentro de 64 paradas')
    return {'available':True,'stops':stops,'stopsRemaining':len(stops),'finishLap':lap,'warnings':warnings}
