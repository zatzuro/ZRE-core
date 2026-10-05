"""Unified reusable KPI representation for ZRE Core.

This module never owns telemetry acquisition or strategy logic. It projects
existing SDK / ZRE engine state into stable KPI records for UI consumers.
"""
import math


STATE_AVAILABLE="AVAILABLE"
STATE_WAITING="WAITING"
STATE_NOT_APPLICABLE="NOT_APPLICABLE"
STATE_ESTIMATED="ESTIMATED"
STATE_LAST_VALID="LAST_VALID"
STATE_STALE="STALE"


def finite(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):
        return None


def positive(value):
    value=finite(value)
    return value if value is not None and value>0 else None


def at(values,index):
    return values[index] if isinstance(values,(list,tuple)) and isinstance(index,int) and 0<=index<len(values) else None


def mean(values):
    vals=[finite(v) for v in values]
    vals=[v for v in vals if v is not None]
    return sum(vals)/len(vals) if vals else None


def fmt_lap(value):
    value=positive(value)
    if value is None:return "—"
    return f"{int(value//60)}:{value%60:06.3f}"


def fmt_time(value):
    value=finite(value)
    if value is None or value<0:return "—"
    seconds=int(round(value))
    hours,rest=divmod(seconds,3600);minutes,secs=divmod(rest,60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_num(value,digits=1,suffix=""):
    value=finite(value)
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def kpi(id,label,group,value=None,display=None,unit=None,state=None,source="UNKNOWN",
        semantic="LIVE",description=None,available=None):
    if available is None:available=value is not None
    if state is None:state=STATE_AVAILABLE if available else STATE_WAITING
    return {"id":id,"label":label,"group":group,"value":value,
            "display":display if display is not None else ("—" if value is None else str(value)),
            "unit":unit,"state":state,"source":source,"semantic":semantic,
            "available":bool(available),"description":description or ""}


def _first(get,keys):
    for key in keys:
        value=get(key)
        if value is not None:return value,key
    return None,None


def _control(get,id,label,keys,unit=None):
    value,key=_first(get,keys);value=finite(value)
    if value is None:
        return kpi(id,label,"COCHE",state=STATE_NOT_APPLICABLE,source="SDK",semantic="LIVE",available=False)
    return kpi(id,label,"COCHE",value,fmt_num(value,1),unit,source=f"SDK:{key}")


def _input(get,id,label,key,unit="%",scale=100.0):
    value=finite(get(key))
    if value is None:return kpi(id,label,"INPUTS",state=STATE_NOT_APPLICABLE,source=f"SDK:{key}",available=False)
    shown=value*scale
    return kpi(id,label,"INPUTS",shown,fmt_num(shown,0,"%"),unit,source=f"SDK:{key}")


def _tire_corner(get,corner,prefix):
    items=[]
    pressure,key=_first(get,(f"{prefix}pressure",f"{prefix}coldPressure"))
    pressure=finite(pressure)
    items.append(kpi(f"tire.pressure.{corner.lower()}",f"Presión {corner}","NEUMÁTICOS",
        pressure,fmt_num(pressure,1),source=f"SDK:{key}" if key else "SDK",
        semantic="LAST_VALID",state=STATE_LAST_VALID if pressure is not None else STATE_WAITING,
        available=pressure is not None))
    temps=[finite(get(f"{prefix}temp{zone}")) for zone in ("L","M","R")]
    temp=mean([v for v in temps if v is not None])
    items.append(kpi(f"tire.temp.{corner.lower()}",f"Temperatura {corner}","NEUMÁTICOS",
        temp,fmt_num(temp,1," °C"),"°C",source="SDK:TIRE_TEMP",
        semantic="LAST_VALID",state=STATE_LAST_VALID if temp is not None else STATE_WAITING,
        available=temp is not None))
    wears=[finite(get(f"{prefix}wear{zone}")) for zone in ("L","M","R")]
    wears=[v for v in wears if v is not None]
    wear=mean(wears)
    wear_pct=wear*100 if wear is not None else None
    items.append(kpi(f"tire.wear.{corner.lower()}",f"Desgaste {corner}","NEUMÁTICOS",
        wear_pct,fmt_num(wear_pct,0,"%"),"%",source="SDK:TIRE_WEAR",
        semantic="LAST_VALID",state=STATE_LAST_VALID if wear_pct is not None else STATE_WAITING,
        available=wear_pct is not None))
    brake,key=_first(get,(f"{prefix}brakeTemp",f"{prefix}BrakeTemp"))
    brake=finite(brake)
    items.append(kpi(f"brake.temp.{corner.lower()}",f"Freno {corner}","FRENOS",
        brake,fmt_num(brake,1," °C"),"°C",source=f"SDK:{key}" if key else "SDK",
        semantic="LAST_VALID",state=STATE_LAST_VALID if brake is not None else STATE_NOT_APPLICABLE,
        available=brake is not None))
    return items


def _sof(drivers,class_id=None):
    ratings=[]
    for row in drivers or []:
        if not isinstance(row,dict) or row.get("IsSpectator") or row.get("CarIsPaceCar"):continue
        if class_id is not None and row.get("CarClassID")!=class_id:continue
        rating=positive(row.get("IRating"))
        if rating is not None:ratings.append(rating)
    if len(ratings)<2:return None
    denominator=sum(2**(-rating/1600.0) for rating in ratings)
    if denominator<=0:return None
    return round((1600.0/math.log(2))*math.log(len(ratings)/denominator))


def build_kpi_library(get,payload,*,role,car_idx=None,car=None,result=None,drivers=None,
                      overall_rows=None,class_rows=None,fuel_history=None,lap_history=None,
                      best_sectors=None,completed_laps=None,current_lap=None,fuel_value=None,
                      fuel_source=None,average_lap=None,stint_laps=None,current_driver=None):
    """Project existing telemetry/engines into stable KPI objects."""
    payload=payload or {};car=car or {};result=result or {}
    overall_rows=overall_rows or [];class_rows=class_rows or []
    fuel_history=[v for v in (fuel_history or []) if positive(v) is not None]
    lap_history=lap_history or [];best_sectors=best_sectors or [None,None,None]
    intel=(payload.get("sessionIntelligence") or {})
    session=((intel.get("session") or {}).get("observed") or {})
    env=((intel.get("environment") or {}).get("observed") or {})
    plan_data=payload.get("racePlanVNext") or {}
    plan=plan_data.get("currentPlan") or plan_data.get("plan") or {}
    window=plan.get("window") or {}
    race_director=payload.get("raceDirector") or {}
    endurance=payload.get("enduranceStrategy") or {}
    rival_strategy=payload.get("rivalStrategy") or {}
    coach=payload.get("coach") or {}
    items=[]

    def add(item):items.append(item)
    def row_for(rows):
        return next((r for r in rows if r.get("isPlayer") or r.get("idx")==car_idx),None)

    overall=row_for(overall_rows)
    cls=row_for(class_rows)
    overall_pos=(overall or {}).get("pos")
    if not overall_pos:overall_pos=finite(result.get("Position"))
    class_pos=(cls or {}).get("classPos") or (cls or {}).get("pos")
    if not class_pos:
        raw_class=finite(result.get("ClassPosition"))
        class_pos=(raw_class+1) if raw_class is not None and raw_class>=0 else None
    active_drivers=[r for r in (drivers or []) if isinstance(r,dict) and not r.get("IsSpectator") and not r.get("CarIsPaceCar")]
    participant_count=len([r for r in overall_rows if r.get("pos")]) or len(active_drivers)
    class_id=car.get("CarClassID")
    class_count=len([r for r in class_rows if r.get("pos")]) or len([r for r in active_drivers if class_id is not None and r.get("CarClassID")==class_id])
    add(kpi("session.position.overall","Posición general","SESIÓN",overall_pos,f"P{int(overall_pos)}" if overall_pos else "—",source="RESULTS/CARIDX"))
    add(kpi("session.position.class","Posición de clase","SESIÓN",class_pos,f"P{int(class_pos)}" if class_pos else "—",source="RESULTS/CarIdxClassPosition"))
    add(kpi("session.participants.overall","Participantes","SESIÓN",participant_count,str(participant_count) if participant_count else "—",source="ZRE_TIMING/DRIVER_INFO"))
    add(kpi("session.participants.class","Participantes clase","SESIÓN",class_count,str(class_count) if class_count else "—",source="ZRE_CLASS_STANDINGS/DRIVER_INFO"))
    time_remain=finite(session.get("timeRemain"))
    add(kpi("session.time.remaining","Tiempo restante","SESIÓN",time_remain,fmt_time(time_remain),"s",source="SESSION_INTELLIGENCE"))
    laps_remain=finite(session.get("lapsRemainEx"))
    if laps_remain is None:laps_remain=finite(session.get("lapsRemain"))
    add(kpi("session.laps.remaining","Vueltas restantes","SESIÓN",laps_remain,str(int(laps_remain)) if laps_remain is not None else "—",source="SESSION_INTELLIGENCE"))
    add(kpi("session.lap.current","Vuelta actual","SESIÓN",current_lap,str(int(current_lap)) if finite(current_lap) is not None else "—",source="SDK:Lap/CarIdxLap"))
    add(kpi("session.laps.completed","Vueltas completadas","SESIÓN",completed_laps,str(int(completed_laps)) if finite(completed_laps) is not None else "—",source="SDK:LapCompleted/CarIdxLapCompleted"))
    add(kpi("session.type","Tipo de sesión","SESIÓN",session.get("type") or payload.get("sessionType"),display=str(session.get("type") or payload.get("sessionType") or "—"),source="SESSION_INTELLIGENCE"))
    add(kpi("session.state","Estado sesión","SESIÓN",session.get("state"),display=str(session.get("state") if session.get("state") is not None else "—"),source="SESSION_INTELLIGENCE"))
    flags=session.get("flags")
    add(kpi("session.flags","Bandera / pista","SESIÓN",flags,display=str(flags) if flags is not None else "—",source="SESSION_INTELLIGENCE"))
    add(kpi("session.car.class","Clase","SESIÓN",car.get("CarClassShortName") or car.get("CarClassID"),display=str(car.get("CarClassShortName") or car.get("CarClassID") or "—"),source="DRIVER_INFO"))
    sof=_sof(drivers,car.get("CarClassID"))
    add(kpi("session.sof.class","Strength of Field","SESIÓN",sof,str(sof) if sof is not None else "—",source="ZRE_FROM_IRATING",state=STATE_ESTIMATED if sof is not None else STATE_WAITING))

    last_lap=positive(get("LapLastLapTime")) if role=="driver" else positive((payload.get("self") or {}).get("lastLapValue"))
    best_lap=positive(get("LapBestLapTime")) if role=="driver" else positive(result.get("FastestTime"))
    delta=finite(get("LapDeltaToSessionBestLap")) if role=="driver" else None
    projected=(best_lap+delta) if best_lap is not None and delta is not None else None
    add(kpi("lap.delta.current","Delta vuelta actual","VUELTA",delta,fmt_num(delta,3," s"),"s",source="SDK:LapDeltaToSessionBestLap",state=STATE_ESTIMATED if delta is not None else STATE_WAITING))
    add(kpi("lap.last","Última vuelta","VUELTA",last_lap,fmt_lap(last_lap),"s",source="SDK/RESULTS"))
    add(kpi("lap.best","Mejor vuelta","VUELTA",best_lap,fmt_lap(best_lap),"s",source="SDK/RESULTS"))
    add(kpi("lap.projected","Vuelta proyectada","VUELTA",projected,fmt_lap(projected),"s",source="SDK_DELTA+BEST",state=STATE_ESTIMATED if projected is not None else STATE_WAITING))
    optimal=positive(coach.get("optimalSeconds")) or positive(coach.get("optimal"))
    add(kpi("lap.optimal","Vuelta óptima","VUELTA",optimal,coach.get("optimalLap") or fmt_lap(optimal),"s",source="COACH",state=STATE_ESTIMATED if optimal is not None else STATE_WAITING))
    last_valid=next((r for r in reversed(lap_history) if r.get("valid") and r.get("sectors")),None)
    sectors=(last_valid or {}).get("sectors") or []
    for i in range(3):
        value=positive(sectors[i]) if i<len(sectors) else None
        best=positive(best_sectors[i]) if i<len(best_sectors) else None
        add(kpi(f"lap.sector.s{i+1}",f"S{i+1}","VUELTA",value,fmt_lap(value),"s",source="ZRE_LAP_TRACKER",semantic="LAST_VALID",state=STATE_LAST_VALID if value is not None else STATE_WAITING))
        sec_delta=(value-best) if value is not None and best is not None else None
        add(kpi(f"lap.sector.delta.s{i+1}",f"Delta S{i+1}","VUELTA",sec_delta,fmt_num(sec_delta,3," s"),"s",source="ZRE_LAP_TRACKER",semantic="LAST_VALID",state=STATE_LAST_VALID if sec_delta is not None else STATE_WAITING))

    last_use=fuel_history[-1] if fuel_history else None
    avg=mean(fuel_history)
    add(kpi("fuel.current","Combustible actual","FUEL",fuel_value,fmt_num(fuel_value,1," L"),"L",source=fuel_source or "SIN DATO",state=STATE_ESTIMATED if fuel_source=="ESTIMADO" else None))
    add(kpi("fuel.use.last","Consumo última vuelta","FUEL",last_use,fmt_num(last_use,2," L/v"),"L/v",source="ZRE_FUEL_HISTORY"))
    add(kpi("fuel.use.average","Consumo medio","FUEL",avg,fmt_num(avg,2," L/v"),"L/v",source="ZRE_FUEL_HISTORY"))
    for n in (2,5,10):
        value=mean(fuel_history[-n:]) if len(fuel_history)>=n else None
        add(kpi(f"fuel.use.avg{n}",f"Media últimas {n}","FUEL",value,fmt_num(value,2," L/v"),"L/v",source="ZRE_FUEL_HISTORY"))
    autonomy=(fuel_value/avg) if positive(fuel_value) is not None and positive(avg) is not None else None
    add(kpi("fuel.autonomy.laps","Autonomía","FUEL",autonomy,fmt_num(autonomy,1," v"),"laps",source="ZRE_FUEL_HISTORY",state=STATE_ESTIMATED if autonomy is not None else STATE_WAITING))
    autonomy_time=autonomy*average_lap if autonomy is not None and positive(average_lap) is not None else None
    add(kpi("fuel.autonomy.time","Autonomía tiempo","FUEL",autonomy_time,fmt_time(autonomy_time),"s",source="ZRE_FUEL_HISTORY",state=STATE_ESTIMATED if autonomy_time is not None else STATE_WAITING))
    next_stop=(plan.get("stops") or [{}])[0] if plan.get("stops") else {}
    fuel_add=finite(next_stop.get("fuel_to_add_liters"))
    add(kpi("fuel.next_stop","Fuel próxima parada","FUEL",fuel_add,fmt_num(fuel_add,1," L"),"L",source="RACE_PLAN",state=STATE_ESTIMATED if fuel_add is not None else STATE_WAITING))
    final_required=finite(plan.get("final_fuel_required_liters"))
    add(kpi("fuel.finish.required","Fuel para terminar","FUEL",final_required,fmt_num(final_required,1," L"),"L",source="RACE_PLAN",state=STATE_ESTIMATED if final_required is not None else STATE_WAITING))
    deficit=(final_required-fuel_value) if final_required is not None and finite(fuel_value) is not None else None
    add(kpi("fuel.finish.balance","Déficit / superávit","FUEL",deficit,fmt_num(deficit,1," L"),"L",source="RACE_PLAN",state=STATE_ESTIMATED if deficit is not None else STATE_WAITING))
    margin=finite(((plan_data.get("fuelModel") or {}).get("margin_laps")))
    add(kpi("fuel.margin","Margen Fuel","FUEL",margin,fmt_num(margin,1," v"),"laps",source="RACE_PLAN",state=STATE_ESTIMATED if margin is not None else STATE_WAITING))

    for item in (
        _control(get,"car.brake_bias","Brake Bias",("dcBrakeBias","BrakeBias"),"%"),
        _control(get,"car.tc","TC",("dcTractionControl","TractionControl")),
        _control(get,"car.tc2","TC2",("dcTractionControl2",)),
        _control(get,"car.abs","ABS",("dcABS","ABS")),
        _control(get,"car.engine_map","Engine Map",("dcEnginePower","dcFuelMixture","EngineMap")),
        _control(get,"car.gear","Marcha",("Gear",)),
        _control(get,"car.rpm","RPM",("RPM",),"rpm"),
        _control(get,"car.speed","Velocidad",("Speed",),"m/s"),
    ):add(item)
    add(_input(get,"input.throttle","Throttle","Throttle"))
    add(_input(get,"input.brake","Brake","Brake"))
    add(_input(get,"input.clutch","Clutch","Clutch"))
    steering=finite(get("SteeringWheelAngle"))
    add(kpi("input.steering","Steering","INPUTS",steering,fmt_num(steering,3," rad"),"rad",source="SDK:SteeringWheelAngle",state=STATE_NOT_APPLICABLE if steering is None else STATE_AVAILABLE,available=steering is not None))

    for corner,prefix in (("FL","LF"),("FR","RF"),("RL","LR"),("RR","RR")):
        items.extend(_tire_corner(get,corner,prefix))

    for key,label,unit in (
        ("AirTemp","Temperatura ambiente","°C"),("TrackTemp","Temperatura pista","°C"),
        ("RelativeHumidity","Humedad","%"),("WindVel","Viento","m/s"),
        ("WindDir","Dirección viento","rad"),("Precipitation","Precipitación",""),
    ):
        value=finite(env.get(key))
        add(kpi(f"environment.{key.lower()}",label,"ENTORNO",value,fmt_num(value,1,(" "+unit) if unit else ""),unit,source="SESSION_INTELLIGENCE"))
    wet=(intel.get("environment") or {}).get("wetnessLabel")
    add(kpi("environment.wetness","Estado Wet/Dry","ENTORNO",wet,display=str(wet or "—"),source="SESSION_INTELLIGENCE"))
    sim_time=finite(get("SessionTimeOfDay")) or finite(get("SessionTime"))
    add(kpi("environment.sim_time","Hora simulación","ENTORNO",sim_time,fmt_time(sim_time),"s",source="SDK"))

    add(kpi("driver.name","Piloto","PILOTO",current_driver or car.get("UserName"),display=str(current_driver or car.get("UserName") or "—"),source="TEAM_CONTEXT/DRIVER_INFO"))
    add(kpi("driver.number","Número coche","PILOTO",car.get("CarNumber"),display=str(car.get("CarNumber") or "—"),source="DRIVER_INFO"))
    irating=finite(car.get("IRating"))
    add(kpi("driver.irating","iRating","PILOTO",irating,str(int(irating)) if irating is not None else "—",source="DRIVER_INFO"))
    sr=car.get("LicString") or car.get("LicSubLevel")
    add(kpi("driver.safety_rating","Safety Rating","PILOTO",sr,display=str(sr or "—"),source="DRIVER_INFO"))
    incidents=finite(get("PlayerCarMyIncidentCount")) if role=="driver" else finite(result.get("Incidents"))
    add(kpi("driver.incidents","Incidentes","PILOTO",incidents,str(int(incidents)) if incidents is not None else "—",source="SDK/RESULTS"))
    start=finite(result.get("StartingPosition"));current=finite(result.get("Position"))
    gained=(start+1-current) if start is not None and current is not None else None
    add(kpi("driver.positions_gained","Posiciones ganadas/perdidas","PILOTO",gained,fmt_num(gained,0),source="RESULTS",state=STATE_ESTIMATED if gained is not None else STATE_WAITING))

    target=finite(window.get("target"))
    current_num=finite(current_lap)
    laps_to=(target-current_num) if target is not None and current_num is not None else None
    add(kpi("strategy.next_stop","Próxima parada","ESTRATEGIA",target,f"V{int(target)}" if target is not None else "—",source="RACE_PLAN",state=STATE_ESTIMATED if target is not None else STATE_WAITING))
    range_text="—"
    if finite(window.get("earliest_safe")) is not None and finite(window.get("fuel_limit")) is not None:
        range_text=f"V{int(window['earliest_safe'])}–V{int(window['fuel_limit'])}"
    add(kpi("strategy.pit_window","Ventana parada","ESTRATEGIA",window.get("state"),range_text,source="RACE_PLAN",state=STATE_ESTIMATED if range_text!="—" else STATE_WAITING))
    add(kpi("strategy.laps_to_stop","Vueltas hasta parada","ESTRATEGIA",laps_to,fmt_num(laps_to,0," v"),"laps",source="RACE_PLAN",state=STATE_ESTIMATED if laps_to is not None else STATE_WAITING))
    time_to=laps_to*average_lap if laps_to is not None and positive(average_lap) is not None else None
    add(kpi("strategy.time_to_stop","Tiempo hasta parada","ESTRATEGIA",time_to,fmt_time(time_to),"s",source="RACE_PLAN",state=STATE_ESTIMATED if time_to is not None else STATE_WAITING))
    stops=finite(plan.get("minimum_stops"))
    add(kpi("strategy.stops_remaining","Paradas restantes","ESTRATEGIA",stops,str(int(stops)) if stops is not None else "—",source="RACE_PLAN",state=STATE_ESTIMATED if stops is not None else STATE_WAITING))
    pit_loss=finite((payload.get("strategySettings") or {}).get("pitLossSeconds")) or finite((race_director.get("pitLossSeconds")))
    if pit_loss is None:pit_loss=finite((next_stop or {}).get("pit_loss_seconds"))
    add(kpi("strategy.pit_loss","Pit Loss","ESTRATEGIA",pit_loss,fmt_num(pit_loss,1," s"),"s",source="RACE_PLAN/STRATEGY",state=STATE_ESTIMATED if pit_loss is not None else STATE_WAITING))
    rejoin=((rival_strategy.get("primary") or {}).get("rejoinProjection") or {})
    rejoin_pos=rejoin.get("projectedPosition") or rejoin.get("position")
    add(kpi("strategy.rejoin_position","Posición estimada Rejoin","ESTRATEGIA",rejoin_pos,display=str(rejoin_pos or "—"),source="RIVAL_STRATEGY",state=STATE_ESTIMATED if rejoin_pos is not None else STATE_WAITING))
    rival=race_director.get("rival")
    add(kpi("strategy.rival","Strategic Rival","ESTRATEGIA",rival,display=str(rival or "—"),source="RACE_DIRECTOR"))
    rival_gap=race_director.get("gap")
    add(kpi("strategy.rival_gap","Gap Strategic Rival","ESTRATEGIA",rival_gap,display=str(rival_gap or "—"),source="RACE_DIRECTOR"))
    action=(rival_strategy.get("primary") or {}).get("action")
    add(kpi("strategy.attack_state","Undercut / Overcut","ESTRATEGIA",action,display=str(action or "—"),source="RIVAL_STRATEGY",state=STATE_ESTIMATED if action else STATE_WAITING))
    stint=endurance.get("currentStint")
    add(kpi("strategy.stint.current","Stint actual","ESTRATEGIA",stint,display=str(stint or "—"),source="ENDURANCE_STRATEGY"))
    add(kpi("strategy.stint.laps","Vueltas stint","ESTRATEGIA",stint_laps,str(int(stint_laps)) if finite(stint_laps) is not None else "—",source="TEAM_CONTEXT"))
    add(kpi("strategy.driver.current","Piloto actual","ESTRATEGIA",current_driver,display=str(current_driver or "—"),source="TEAM_CONTEXT"))
    next_driver=next_stop.get("driver") or next_stop.get("autoDriver")
    add(kpi("strategy.driver.next","Próximo piloto","ESTRATEGIA",next_driver,display=str(next_driver or "—"),source="RACE_PLAN"))

    return {"version":1,"role":role,"items":items,
            "byId":{item["id"]:item for item in items},
            "states":[STATE_AVAILABLE,STATE_WAITING,STATE_NOT_APPLICABLE,STATE_ESTIMATED,STATE_LAST_VALID,STATE_STALE]}
