"""Bounded SDK observations and explicitly separate, conservative race inference.

SDK variable contracts: kutu/pyirsdk vars.txt and irsdk.py. CarIdxEstTime is
estimated elapsed lap time at the current track location, not time to finish.
ResultsPositions.ClassPosition is zero-based; CarIdxClassPosition is live
race placement (1 = leader, 0 = unplaced). Official standings retain priority.
"""
import math
from statistics import median

CAUTION_MASK=0x4000|0x8000|0x0008|0x0100|0x0010
WETNESS={0:'UNKNOWN',1:'DRY',2:'MOSTLY_DRY',3:'VERY_LIGHTLY_WET',4:'LIGHTLY_WET',5:'MODERATELY_WET',6:'VERY_WET',7:'EXTREMELY_WET'}
UNITS={'AirTemp':'°C','TrackTemp':'°C','TrackTempCrew':'°C','AirPressure':'Pa','AirDensity':'kg/m³',
       'RelativeHumidity':'fraction','FogLevel':'fraction','WindVel':'m/s','WindDir':'rad','Skies':'enum',
       'TrackWetness':'enum','Precipitation':'fraction','WeatherDeclaredWet':'bool'}


def finite(v):
    if isinstance(v,bool):return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None


def at(values,idx):
    return values[idx] if isinstance(values,(list,tuple)) and isinstance(idx,int) and 0<=idx<len(values) else None


def positive(v):
    n=finite(v)
    return n if n is not None and n>0 else None


def predict_next(stops,current_lap=None):
    laps=[p.get('entryLap',p.get('lap')) for p in stops if positive(p.get('entryLap',p.get('lap'))) is not None]
    lengths=[b-a for a,b in zip(laps,laps[1:]) if 2<=b-a<=300]
    if not lengths:return None,lengths
    recent=lengths[-4:];typical=median(recent);spread=max(1,math.ceil(max(abs(x-typical) for x in recent)))
    conf='HIGH' if len(recent)>=3 and spread<=2 else 'MEDIUM' if len(recent)>=2 and spread<=3 else 'LOW'
    lo=max(1,math.floor(laps[-1]+typical-spread));hi=math.ceil(laps[-1]+typical+spread)
    if current_lap is not None and current_lap>hi+1:return None,lengths[-5:]
    return {'lap':round(laps[-1]+typical),'fromLap':lo,'toLap':hi,'confidence':conf,'source':'ZRE_INFERRED',
            'method':'OBSERVED_STINT_PATTERN','typicalStintLaps':typical,'samples':len(recent)},lengths[-5:]


def reconcile_stop(stops,event,baseline):
    """Upgrade a near inferred event; two SDK entries remain two actual events."""
    for old in reversed(stops[-3:]):
        if old.get('source')==event.get('source')=='SDK_OBSERVED':continue
        lap_a=finite(old.get('lap'));lap_b=finite(event.get('lap'))
        t_a=finite(old.get('sessionTime'));t_b=finite(event.get('sessionTime'))
        exit_a=finite(old.get('exitLap'));exit_b=finite(event.get('exitLap'))
        near_lap=lap_a is not None and lap_b is not None and (abs(lap_a-lap_b)<=2 or (exit_a is not None and abs(exit_a-lap_b)<=1) or (exit_b is not None and abs(exit_b-lap_a)<=1))
        near_time=t_a is not None and t_b is not None and abs(t_a-t_b)<=max(30,2*(baseline or 90))
        if near_lap and near_time:
            if event.get('source')=='SDK_OBSERVED':
                old.update(event)
                old['reconciled']=True
            return old
    event['eventId']=f"pit-{event.get('lap')}-{event.get('sessionTime')}"
    stops.append(event);del stops[:-10]
    return event


def temporal_gap(get,player_idx,idx,own_pct,pct,baseline,other_best):
    if own_pct is None or pct is None or not 0<=own_pct<=1 or not 0<=pct<=1:return None
    delta=(pct-own_pct+.5)%1-.5
    own_ref=positive(get('LapBestLapTime')) or positive(get('LapLastLapTime'))
    best=get('CarIdxBestLapTime',[]) or []
    own_ref=positive(at(best,player_idx)) or own_ref
    other_ref=positive(other_best) or baseline
    times=get('CarIdxEstTime',[]) or []
    own_t=finite(at(times,player_idx));other_t=finite(at(times,idx))
    if own_ref and other_ref and abs(other_ref/own_ref-1)<.15 and own_t is not None and other_t is not None and 0<=own_t<=own_ref*1.05 and 0<=other_t<=other_ref*1.05:
        gap=((other_t/other_ref-own_t/own_ref+.5)%1-.5)*own_ref
        if abs(gap)<.5 or gap*delta>=0:
            return {'seconds':gap,'source':'ZRE_INFERRED','inputSource':'SDK_OBSERVED','method':'CarIdxEstTime_NORMALIZED','confidence':'MEDIUM','estimatedBySDK':True}
    if own_ref:
        return {'seconds':delta*own_ref,'source':'ZRE_INFERRED','method':'TRACK_FRACTION_ESTIMATE','confidence':'LOW'}
    return None


def build_intelligence(get,weekend,session,cars,results,player_idx,player_class_id,lap_pct,track_surface,history=None,car_label=None,units=None):
    history=history if isinstance(history,dict) else {}
    now=finite(get('SessionTime')) or 0
    env={k:get(k) for k in UNITS if get(k) is not None}
    env={k:v for k,v in env.items() if isinstance(v,(bool,str,int,float)) and (not isinstance(v,float) or math.isfinite(v))}
    fields={k:{'value':v,'unit':(units or {}).get(k,UNITS[k]),'source':'SDK_OBSERVED','sdkField':k} for k,v in env.items()}
    session_data={'type':session.get('SessionType'),'name':session.get('SessionName'),'timeRemain':finite(get('SessionTimeRemain')),
        'lapsRemain':finite(get('SessionLapsRemain')),'lapsRemainEx':finite(get('SessionLapsRemainEx')),
        'flags':get('SessionFlags'),'state':get('SessionState'),'pitsOpen':get('PitsOpen'),
        'incidentLimit':weekend.get('WeekendOptions',{}).get('IncidentLimit'),'standingStart':weekend.get('WeekendOptions',{}).get('StandingStart'),
        'teamRacing':weekend.get('TeamRacing'),'numCarClasses':weekend.get('NumCarClasses')}
    for key in ('lapsRemain','lapsRemainEx'):
        if session_data[key] is not None and not 0<=session_data[key]<32767:session_data[key]=None
    if session_data['timeRemain'] is not None and session_data['timeRemain']<0:session_data['timeRemain']=None
    caution=bool(int(finite(session_data['flags']) or 0)&CAUTION_MASK)
    arrays={key:get(key,[]) or [] for key in ('CarIdxLap','CarIdxLapCompleted','CarIdxLastLapTime','CarIdxOnPitRoad','CarIdxBestLapTime')}
    own_pct=finite(at(lap_pct,player_idx))
    race=str(session.get('SessionType','')).lower()=='race'
    # Detect broad class slowdown before adding any new sample to its baseline.
    class_slow={}
    for idx,car in (cars or {}).items():
        previous=history.get(idx,{})
        clean=previous.get('cleanLapTimes') or []
        base=median([x['time'] for x in clean[-8:]]) if len(clean)>=3 else None
        value=positive(at(arrays['CarIdxLastLapTime'],idx))
        if base and value and not at(arrays['CarIdxOnPitRoad'],idx):
            class_slow.setdefault(car.get('CarClassID'),[]).append(value>base*1.18 and value-base>12)
    slow_classes={cid for cid,values in class_slow.items() if len(values)>=2 and sum(values)>=2 and sum(values)/len(values)>=.6}
    competitors=[]
    roster={idx:car for idx,car in (cars or {}).items() if isinstance(idx,int) and 0<=idx<64}
    for idx,previous in list(history.items()):
        if idx not in roster and 0<=idx<64:roster[idx]=previous.get('_car',{})
    for idx,car in roster.items():
        if idx==player_idx or car.get('CarIsPaceCar') or car.get('IsSpectator'):continue
        previous=history.get(idx,{})
        pct=finite(at(lap_pct,idx));surface=finite(at(track_surface,idx))
        if pct is not None and not 0<=pct<=1:pct=None
        live=idx in cars and ((surface is not None and surface>=0) or (surface is None and pct is not None))
        result=results.get(idx,{})
        state=previous.get('_state') or {'completed':None,'time':None,'pending':None,'cycle':None,'pit':None,'incidents':result.get('Incidents')}
        raw=list(previous.get('lapTimes') or []);clean=list(previous.get('cleanLapTimes') or []);stops=list(previous.get('pitHistory') or [])
        baseline=median([x['time'] for x in clean[-8:]]) if len(clean)>=3 else None
        pit_raw=at(arrays['CarIdxOnPitRoad'],idx)
        pit=pit_raw if isinstance(pit_raw,bool) else None
        completed=finite(at(arrays['CarIdxLapCompleted'],idx))
        if completed is None or completed<0:completed=finite(result.get('LapsComplete'))
        if completed is None or completed<0:
            lap=positive(at(arrays['CarIdxLap'],idx));completed=max(0,lap-1) if lap is not None else None
        current_last=positive(at(arrays['CarIdxLastLapTime'],idx))
        incidents=result.get('Incidents');incident_changed=incidents is not None and state.get('incidents') is not None and incidents>state['incidents']
        if incidents is not None:state['incidents']=incidents
        blocked=caution or car.get('CarClassID') in slow_classes or incident_changed
        if blocked:state['cycle']=None
        if race and pit is True and not state.get('pit'):
            event=reconcile_stop(stops,{'lap':completed+1 if completed is not None else None,'entryLap':completed+1 if completed is not None else None,
                'entrySessionTime':now,'sessionTime':now,'source':'SDK_OBSERVED','method':'CarIdxOnPitRoad','confidence':'CONFIRMED','status':'IN_PIT'},baseline)
            state['pit']=event['eventId'];state['cycle']=None
        if state.get('pit') and not live:
            event=next((p for p in stops if p.get('eventId')==state['pit']),None)
            if event:event['observationInterrupted']=True
        if race and live and pit is False and state.get('pit'):
            event=next((p for p in stops if p.get('eventId')==state['pit']),None)
            if event:
                event.update(exitSessionTime=now,exitLap=completed+1 if completed is not None else None,status='COMPLETE')
                entry=finite(event.get('entrySessionTime'))
                if entry is not None:event['pitRoadDurationObserved']={'seconds':max(0,now-entry),'source':'SDK_OBSERVED','confidence':'LOW' if event.get('observationInterrupted') else 'HIGH','sampledTransitions':True}
            state['pit']=None
        sample=None
        if live and completed is not None:
            if state['completed'] is None:
                state.update(completed=completed,time=current_last)
            elif completed>state['completed']:
                state['pending']=(completed,state.get('time'));state['completed']=completed
            pending=state.get('pending')
            official=positive(result.get('LastTime'))
            official_match=result.get('LapsComplete')==completed and official is not None
            candidate=official if official_match else current_last
            if pending and candidate and (official_match or candidate!=pending[1]):
                sample={'lap':completed,'time':candidate,'sessionTime':now,'source':'SDK_OBSERVED'}
                raw.append(sample);del raw[:-24];state['pending']=None
                baseline=median([x['time'] for x in clean[-8:]]) if len(clean)>=3 else None
                # One slow lap never establishes a stop. The baseline is frozen
                # across the entire anomalous pair and recovery.
                anomaly=bool(baseline and candidate>baseline*1.18 and candidate-baseline>12)
                nearby=any(positive(p.get('entryLap',p.get('lap'))) is not None and abs(completed-p.get('exitLap',p.get('entryLap',p.get('lap'))))<=1 for p in stops if p.get('source')=='SDK_OBSERVED')
                if race and not blocked and not pit and not nearby:
                    cycle=state.get('cycle')
                    if anomaly:
                        if cycle is None:state['cycle']={'state':'FIRST_ANOMALY','baseline':baseline,'samples':[sample]}
                        else:
                            cycle['samples'].append(sample);cycle['samples']=cycle['samples'][-3:];cycle['state']='CORROBORATED'
                    elif cycle:
                        if cycle['state']=='CORROBORATED' and candidate<=cycle['baseline']*1.12 and max(x['time'] for x in cycle['samples'])>cycle['baseline']*1.35:
                            first=cycle['samples'][0]
                            event=reconcile_stop(stops,{'lap':first['lap'],'entryLap':first['lap'],'exitLap':completed,'sessionTime':first['sessionTime'],
                                'recoverySessionTime':now,'source':'ZRE_INFERRED','method':'ANOMALOUS_PAIR_RECOVERY','confidence':'MEDIUM','status':'PROBABLE',
                                'abnormalLapExcess':sum(max(0,x['time']-cycle['baseline']) for x in cycle['samples'])},baseline)
                        state['cycle']=None
                if not anomaly and not blocked and not pit and not nearby:
                    clean.append(sample);del clean[:-12]
            if current_last:state['time']=current_last
        # Net pit loss is an estimate from clean pace deviations. Road duration
        # remains a separate SDK observation and is never relabelled as net loss.
        for event in stops:
            if baseline and not blocked and event.get('exitLap') is not None :
                lo=event.get('entryLap');hi=event.get('exitLap')
                if lo is not None and hi is not None:
                    excess=sum(max(0,x['time']-baseline) for x in raw if lo-1<=x['lap']<=hi+1 and x['time']>baseline+8)
                    if excess>0:event['abnormalLapExcess']=max(excess,event.get('abnormalLapExcess') or 0)
        losses=[p['abnormalLapExcess'] for p in stops if positive(p.get('abnormalLapExcess')) and p.get('status')=='COMPLETE' and p.get('source')=='SDK_OBSERVED' and not p.get('observationInterrupted')]
        loss=None
        if losses:
            values=losses[-3:];average=median(values)
            loss={'seconds':round(average,2),'samples':len(values),'confidence':'MEDIUM' if len(values)>=2 else 'LOW','source':'ZRE_INFERRED',
                'method':'CLEAN_PACE_ABNORMAL_EXCESS','uncertaintySeconds':max(5,max(values)-min(values))}
        next_stop,lengths=predict_next(stops,completed)
        last_seen=now if live else previous.get('lastSeenSessionTime')
        delta=(pct-own_pct+.5)%1-.5 if live and pct is not None and own_pct is not None and 0<=own_pct<=1 else None
        gap=temporal_gap(get,player_idx,idx,own_pct,pct,baseline,at(arrays['CarIdxBestLapTime'],idx)) if live and not pit else None
        rejoin=None
        if loss and gap:
            projected=gap['seconds']-loss['seconds']
            rejoin={'currentGapEstimate':round(gap['seconds'],2),'projectedGapAfterPit':round(projected,2),'position':'AHEAD' if projected>0 else 'BEHIND',
                'source':'ZRE_INFERRED','confidence':'MEDIUM' if gap['confidence']=='MEDIUM' and loss['confidence']=='MEDIUM' else 'LOW',
                'gapEvidence':gap,'pitLossEvidence':loss,'uncertaintySeconds':loss['uncertaintySeconds']+2}
        row={'carIdx':idx,'number':str(car.get('CarNumber',previous.get('number','—'))),'driver':('—' if car.get('identityAmbiguous') else car.get('UserName') or previous.get('driver') or '—'),
            'team':car.get('TeamName') or '—','car':car_label(car) if car_label else car.get('CarScreenName','—'),'classId':car.get('CarClassID'),
            'sameClass':car.get('CarClassID')==player_class_id,'presence':'LIVE' if live else 'STALE','source':'SDK_OBSERVED',
            'lastSeenSessionTime':last_seen,'lastSeenAgo':max(0,now-last_seen) if last_seen is not None else None,
            'lapDistPct':pct if live else None,'lastKnownLapDistPct':pct if live else previous.get('lastKnownLapDistPct'),
            'relativeLapFraction':delta,'surface':surface,'onPitRoad':pit if live else previous.get('onPitRoad'),
            'lap':at(arrays['CarIdxLap'],idx) if live else previous.get('lap'),'lapsComplete':completed if live else previous.get('lapsComplete'),
            'lastLap':current_last if live else previous.get('lastLap'),'bestLap':positive(at(arrays['CarIdxBestLapTime'],idx)) if live else previous.get('bestLap'),
            'position':result.get('Position',previous.get('position')),'classPosition':(result.get('ClassPosition')+1 if isinstance(result.get('ClassPosition'),int) and result['ClassPosition']>=0 else previous.get('classPosition')),
            'lastLapMarkerSessionTime':sample['sessionTime'] if sample else previous.get('lastLapMarkerSessionTime'),
            'pitHistory':stops,'lastPit':stops[-1] if stops else None,'lapTimes':raw,'cleanLapTimes':clean,'cleanPace':baseline,
            'stintLengths':lengths,'nextPitEstimate':next_stop,'pitLossEstimate':loss,'rejoinProjection':rejoin,'gapEvidence':gap,
            'anomalyState':(state.get('cycle') or {}).get('state','BASELINE'),'caution':caution,'classSlowdown':car.get('CarClassID') in slow_classes,
            'trendSeconds':(median([x['time'] for x in clean[-3:]])-median([x['time'] for x in clean[-6:-3]])) if len(clean)>=6 else None}
        marker=row['lastLapMarkerSessionTime'];row['lastLapMarkerAgo']=max(0,now-marker) if marker is not None else None
        history[idx]={**row,'_state':state,'_car':car}
        competitors.append(row)
    competitors.sort(key=lambda x:(x['presence']!='LIVE',x['relativeLapFraction'] is None,abs(x['relativeLapFraction'] or 0)))
    traffic=[x for x in competitors if x['presence']=='LIVE' and x['relativeLapFraction'] is not None and not x['onPitRoad']]
    ahead=[x for x in traffic if x['relativeLapFraction']>0];behind=[x for x in traffic if x['relativeLapFraction']<0]
    return {'environment':{'observed':env,'fields':fields,'source':'SDK_OBSERVED','wetnessLabel':WETNESS.get(env.get('TrackWetness'),'UNKNOWN')},
        'session':{'observed':session_data,'source':'SDK_OBSERVED'},
        'traffic':{'observed':{'carsInWorld':sum(x['presence']=='LIVE' for x in competitors)+(1 if own_pct is not None and 0<=own_pct<=1 else 0),
            'nearestAhead':min(ahead,key=lambda x:x['relativeLapFraction'],default=None),'nearestBehind':max(behind,key=lambda x:x['relativeLapFraction'],default=None)},'source':'SDK_OBSERVED'},
        'competitors':{'observed':competitors,'source':'SDK_OBSERVED','inferenceSource':'ZRE_INFERRED'},
        'caution':caution,'source':'SDK_OBSERVED'}


def strategy_intelligence(competitors,player_lap,player_fuel,fuel_per_lap,player_pit_window=None,evidence=None):
    evidence=evidence or {};window=player_pit_window or {}
    samples=[positive(x) for x in (fuel_per_lap or [])];samples=[x for x in samples if x]
    consumption=median(samples[-5:]) if len(samples)>=3 else None
    fuel=positive(player_fuel);fuel_laps=fuel/consumption if fuel and consumption else None
    own_pace=positive(evidence.get('cleanPace'));rows=[]
    for rival in competitors or []:
        if not rival.get('sameClass') or rival.get('presence')!='LIVE':continue
        nxt=rival.get('nextPitEstimate') or {};loss=rival.get('pitLossEstimate') or {};rejoin=rival.get('rejoinProjection') or {}
        if not nxt:continue
        action='NO RECOMMENDATION';confidence='LOW';reason='Evidencia insuficiente: se requieren ritmo, ventana, rejoin y autonomía propios fiables.'
        target=finite(window.get('target'));lo=finite(nxt.get('fromLap'));hi=finite(nxt.get('toLap'));lap=finite(player_lap)
        projected=finite(rejoin.get('projectedGapAfterPit'));rival_pace=positive(rival.get('cleanPace'))
        enough=bool(evidence.get('planAvailable') and evidence.get('fuelSource')=='REAL LOCAL' and own_pace and rival_pace and
            len(rival.get('cleanLapTimes') or [])>=3 and len(evidence.get('cleanLaps') or [])>=3 and fuel_laps and
            target is not None and lo is not None and hi is not None and lap is not None and lo>=lap and
            nxt.get('confidence') in ('MEDIUM','HIGH') and loss.get('confidence') in ('MEDIUM','HIGH') and
            rejoin.get('confidence') in ('MEDIUM','HIGH') and projected is not None and
            not rival.get('caution') and not rival.get('classSlowdown') and not evidence.get('caution') and
            evidence.get('pitsOpen') is True and evidence.get('trafficClear') is True)
        if enough:
            action='HOLD';confidence='MEDIUM';reason='Datos suficientes; la ganancia esperada no supera la incertidumbre.'
            horizon=max(1,hi-lap);gain=(rival_pace-own_pace)*horizon;uncertainty=max(5,finite(rejoin.get('uncertaintySeconds')) or 5)
            if gain>uncertainty and abs(projected)<=5 and fuel_laps>=max(1,target-lap)+1:
                if target<=lo:
                    action='UNDERCUT';reason='Ventana propia anterior y ritmo limpio favorable; ganancia estimada supera la incertidumbre.'
                elif target>=hi+1 and fuel_laps>=target-lap+1 and (rival.get('trendSeconds') or 0)>0:
                    action='OVERCUT';reason='Autonomía para extender, ritmo favorable y degradación rival observada.'
        rows.append({'carIdx':rival['carIdx'],'number':rival['number'],'driver':rival.get('driver'),'action':action,'confidence':confidence,'reason':reason,
            'ownFuelLaps':round(fuel_laps,1) if fuel_laps else None,'rivalPitWindow':nxt,'rivalPitLoss':loss,'rejoinProjection':rejoin,'source':'ZRE_INFERRED'})
    rows.sort(key=lambda r:(r['action']=='NO RECOMMENDATION',r['action']=='HOLD'))
    return {'available':any(r['action']!='NO RECOMMENDATION' for r in rows),'recommendations':rows[:5],'primary':rows[0] if rows else None,
            'source':'ZRE_INFERRED','own':{'fuelLaps':fuel_laps,'consumption':consumption,'pitWindow':window}}
