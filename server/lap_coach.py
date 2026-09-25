"""Bounded distance-based telemetry and post-lap coaching.

Capture is deliberately cheap. Completed-lap analysis only happens when the
validated timing engine calls ``finish``. A lap buffer is snapshotted at the
start/finish wrap so a short SDK delay in LapLastLapTime cannot mix samples from
two different laps.
"""
from collections import deque
import bisect
import math

N = 480
ZONES = 12

def number(value):
    try:
        value=float(value);return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None

class LapCoach:
    def __init__(self):
        self.samples={};self.last_pct=None;self.dirty=False;self.completed_buffers=deque(maxlen=2)
        self.recent=deque(maxlen=8);self.recent_advice=deque(maxlen=8);self.best_segments=[None]*ZONES
        self.lap_segments=deque(maxlen=12);self.best_lap=None;self.advice=[];self.completed=0
        self.last_diagnostics={};self.last_lap_record=None;self.track_map=None
    def _snapshot_at_wrap(self):
        if self.samples:self.completed_buffers.append((self.samples,self.dirty))
        self.samples={};self.dirty=False
    def capture(self,pct,clock,speed,brake,throttle,on_track=True,steering=None,gear=None,yaw_rate=None,lat_accel=None):
        pct,clock=number(pct),number(clock)
        if not on_track or pct is None or clock is None or not 0<=pct<1:
            if self.samples:self.dirty=True
            return
        if self.last_pct is not None and self.last_pct>.90 and pct<.10:self._snapshot_at_wrap()
        elif self.last_pct is not None and pct+.01<self.last_pct:self.dirty=True
        self.last_pct=pct;index=min(N-1,int(pct*N))
        self.samples[index]=(clock,number(speed) or 0,number(brake) or 0,number(throttle) or 0,number(steering) or 0,number(gear),number(yaw_rate) or 0,number(lat_accel) or 0)
    @staticmethod
    def _scaled_time(points,keys,key,duration):
        start_key,end_key=keys[0],keys[-1];start_clock,end_clock=points[start_key][0],points[end_key][0];clock_span=end_clock-start_clock
        if clock_span<=0:return None
        if key<=start_key:raw=start_clock
        elif key>=N:return duration
        elif key>=end_key:raw=end_clock
        elif key in points:raw=points[key][0]
        else:
            pos=bisect.bisect_left(keys,key);lo,hi=keys[pos-1],keys[pos];lo_clock,hi_clock=points[lo][0],points[hi][0];fraction=(key-lo)/(hi-lo);raw=lo_clock+(hi_clock-lo_clock)*fraction
        return (raw-start_clock)/clock_span*duration
    def finish(self,duration,valid):
        if self.completed_buffers:points,capture_dirty=self.completed_buffers.popleft()
        else:
            points,capture_dirty=self.samples,self.dirty;self.samples={};self.last_pct=None;self.dirty=False
        self.completed+=1;duration=number(duration)
        valid=bool(duration and valid and not capture_dirty and len(points)>=N*.50 and points and min(points)<N*.03 and max(points)>N*.97)
        if not valid:
            self.advice=[];self.last_diagnostics={'accepted':False,'reason':'invalid_or_incomplete','sampleBins':len(points)};self.last_lap_record=None;self.recent_advice.append([]);return False
        keys=sorted(points);start=points[keys[0]][0];end=points[keys[-1]][0]
        if end<=start:self.advice=[];self.recent_advice.append([]);return False
        boundaries=[self._scaled_time(points,keys,zone*N//ZONES,duration) for zone in range(ZONES+1)]
        if any(value is None for value in boundaries):self.advice=[];self.recent_advice.append([]);return False
        segments=[]
        for zone in range(ZONES):
            lo,hi=zone*N//ZONES,(zone+1)*N//ZONES;inside=[k for k in keys if lo<=k<hi]
            if len(inside)<8:segments.append(None);continue
            span=max(0.0,boundaries[zone+1]-boundaries[zone]);braking=[k for k in inside if points[k][2]>.15];accelerating=[k for k in inside if points[k][3]>.8];turning=[k for k in inside if abs(points[k][4])>.14];max_steer_key=max(inside,key=lambda k:abs(points[k][4]));tail=inside[max(0,int(len(inside)*.75)):] or inside
            meaningful_steer=[points[k][4] for k in inside if abs(points[k][4])>.14];signed_sum=sum(meaningful_steer);abs_sum=sum(abs(v) for v in meaningful_steer);direction_confidence=abs(signed_sum)/abs_sum if abs_sum else 0.0;dominant_sign=(1 if signed_sum>0 else -1) if direction_confidence>=.58 else 0
            prep_keys=[k for k in keys if max(0,lo-24)<=k<lo];prep_steer=(sum(points[k][4] for k in prep_keys)/len(prep_keys)) if prep_keys else 0.0
            metrics=(braking[0]/N if braking else None,min(points[k][1] for k in inside),accelerating[0]/N if accelerating else None,turning[0]/N if turning else None,abs(points[max_steer_key][4]),braking[-1]/N if braking else None,sum(points[k][1] for k in tail)/len(tail),dominant_sign,max((points[k][2] for k in inside),default=0),direction_confidence,prep_steer)
            segments.append((span,metrics))
        prior=self._competitive_reference();self.advice=compare(segments,prior)
        if not self.advice and self.best_lap is not None and duration>self.best_lap+.25:
            losses=[(i,seg[0]-ref[0]) for i,(seg,ref) in enumerate(zip(segments,prior),1) if seg is not None and ref is not None and seg[0]-ref[0]>.12]
            if losses:
                zone,loss=max(losses,key=lambda item:item[1]);self.advice=[(zone,loss,'Pérdida localizada','Aquí perdiste más tiempo que en tu referencia, pero todavía no hay una causa única con suficiente confianza.')]
        self.last_diagnostics={'accepted':True,'sampleBins':len(points),'duration':round(duration,3),'zonesCompared':sum(1 for a,b in zip(segments,prior) if a is not None and b is not None),'adviceCount':len(self.advice),'advice':[{'zone':item[0],'loss':round(item[1],3),'cause':item[2],'tip':item[3]} for item in self.advice]}
        base_clock=points[keys[0]][0];self.last_lap_record={'duration':round(duration,4),'samples':[[k,round(points[k][0]-base_clock,4),round(points[k][1],3),round(points[k][2],3),round(points[k][3],3),round(points[k][4],4),points[k][5],round(points[k][6],4),round(points[k][7],4)] for k in keys]}
        self.recent.append(segments);self.recent_advice.append(list(self.advice));self.lap_segments.append((duration,segments));self.best_lap=min(self.best_lap,duration) if self.best_lap else duration;self.best_segments=self._competitive_reference(include_all_if_empty=True);return True
    def _competitive_reference(self,include_all_if_empty=False):
        if not self.lap_segments:return [None]*ZONES
        window_best=min(duration for duration,_ in self.lap_segments);eligible=[segments for duration,segments in self.lap_segments if duration<=window_best*1.02]
        if not eligible and include_all_if_empty:eligible=[segments for _,segments in self.lap_segments]
        reference=[]
        for index in range(ZONES):
            candidates=[segments[index] for segments in eligible if segments[index] is not None];reference.append(min(candidates,key=lambda segment:segment[0]) if candidates else None)
        return reference
    def braking_anchors(self):
        anchors=[]
        for _,segments in self.lap_segments:
            for index,segment in enumerate(segments):
                if not segment or segment[1][0] is None:continue
                pos=segment[1][0]
                if not any(abs(pos-known)<.025 for known in anchors):anchors.append(pos)
        return sorted(anchors)
    def location_label(self,zone):
        center=(zone-.5)/ZONES;anchors=self.braking_anchors()
        if anchors:
            nearest_index,nearest=min(enumerate(anchors),key=lambda item:abs(item[1]-center))
            if abs(nearest-center)<=.09:
                names=['Primera frenada','Segunda frenada','Tercera frenada','Cuarta frenada','Quinta frenada','Sexta frenada','Séptima frenada','Octava frenada'];braking_name=names[nearest_index] if nearest_index<len(names) else f'Frenada {nearest_index+1}';segment=self.best_segments[zone-1] if 0<zone<=len(self.best_segments) else None
                if segment:
                    direction=_direction(_metric(segment[1],7)) if (_metric(segment[1],9) or 0)>=.58 else None
                    if direction:return f'{braking_name}, curva a {direction}'
                return braking_name
        segment=self.best_segments[zone-1] if 0<zone<=len(self.best_segments) else None
        if segment:
            direction=_direction(_metric(segment[1],7)) if (_metric(segment[1],9) or 0)>=.58 else None
            if direction:return f'Curva a {direction}'
        return f'Tramo {zone}'
    @property
    def optimal(self):return sum(s[0] for s in self.best_segments) if all(self.best_segments) else None
    def _pattern(self):
        counts={}
        for lap_advice in self.recent_advice:
            for zone,loss,title,tip in lap_advice:
                key=(zone,title,tip);record=counts.setdefault(key,[0,0.0]);record[0]+=1;record[1]+=loss
        if not counts:return '',''
        (zone,title,tip),(count,total_loss)=max(counts.items(),key=lambda item:(item[1][0],item[1][1]))
        if count<2:return '',''
        average=total_loss/count;return f'{self.location_label(zone)} · {count}/{len(self.recent_advice)} vueltas · +{average:.2f}s',f'{title}. {tip}'
    def summary_priorities(self,limit=3):
        totals={}
        for lap_advice in self.recent_advice:
            for zone,loss,title,tip in lap_advice:
                key=(zone,title,tip);record=totals.setdefault(key,[0,0.0]);record[0]+=1;record[1]+=loss
        ranked=sorted(totals.items(),key=lambda item:(item[1][1],item[1][0]),reverse=True)[:limit]
        return [{'zone':self.location_label(zone),'title':title,'advice':f'{tip} · {count}/{len(self.recent_advice)} vueltas · pérdida media +{total/count:.2f}s'} for (zone,title,tip),(count,total) in ranked]
    def _track_map_payload(self):
        record=self.last_lap_record or {};rows=record.get('samples') or []
        if len(rows)<40:return self.track_map
        x=y=heading=0.0;raw=[(0.0,0.0,rows[0][0]/max(1,N-1))];prev_t=rows[0][1]
        for row in rows[1:]:
            t,speed,yaw=row[1],row[2],row[7] if len(row)>7 else 0.0;dt=max(0.0,min(.5,t-prev_t));prev_t=t;heading+=yaw*dt;x+=speed*math.cos(heading)*dt;y+=speed*math.sin(heading)*dt;raw.append((x,y,row[0]/max(1,N-1)))
        if len(raw)<2:return self.track_map
        end_x,end_y=raw[-1][0],raw[-1][1];corrected=[];total=len(raw)-1
        for i,(px,py,pct) in enumerate(raw):
            f=i/total;corrected.append((px-end_x*f,py-end_y*f,pct))
        xs=[a for a,_,_ in corrected];ys=[b for _,b,_ in corrected];dx=max(xs)-min(xs);dy=max(ys)-min(ys)
        if dx<1e-6 or dy<1e-6:return self.track_map
        scale=min(88/dx,88/dy);cx=(max(xs)+min(xs))/2;cy=(max(ys)+min(ys))/2
        points=[{'x':round(50+(px-cx)*scale,2),'y':round(50-(py-cy)*scale,2),'pct':round(pct,4)} for px,py,pct in corrected];step=max(1,len(points)//180);slim=points[::step]
        if slim[-1]!=points[-1]:slim.append(points[-1])
        markers=[]
        for rank,item in enumerate(self.advice[:2],1):
            pct=(item[0]-.5)/ZONES;point=min(points,key=lambda q:abs(q['pct']-pct));markers.append({'rank':rank,'x':point['x'],'y':point['y'],'loss':round(item[1],3),'label':self.location_label(item[0]),'cause':item[2]})
        self.track_map={'points':slim,'markers':markers};return self.track_map
    def payload(self,format_lap):
        best,optimal=self.best_lap,self.optimal
        def priority(item):return {'zone':f'{self.location_label(item[0])} +{item[1]:.2f}','title':item[2],'advice':item[3]}
        primary=priority(self.advice[0]) if self.advice else None;pattern,pattern_advice=self._pattern()
        return {'reference':'ÓPTIMA SESIÓN','bestLap':format_lap(best),'optimalLap':format_lap(optimal),'potential':f'{max(0,best-optimal):.3f}' if best and optimal else '—','lapMessage':f"{primary['zone']}: {primary['advice']}" if primary else '','primary':primary,'secondary':priority(self.advice[1]) if len(self.advice)>1 else None,'pattern':pattern,'patternAdvice':pattern_advice,'diagnostics':self.last_diagnostics,'trackMap':self._track_map_payload()}

def _metric(metrics,index):return metrics[index] if len(metrics)>index else None
def _direction(sign):
    if sign is None or sign==0:return None
    return 'izquierda' if sign>0 else 'derecha'
def _outside_side(sign):
    if sign is None or sign==0:return None
    return 'derecha' if sign>0 else 'izquierda'
def _direction_phrase(metrics):
    sign=_metric(metrics,7);confidence=_metric(metrics,9) or 0;direction=_direction(sign) if confidence>=.58 else None;return f'curva a {direction}' if direction else 'curva'

def compare(segments,reference):
    advice=[]
    for i,(sample,best) in enumerate(zip(segments,reference),1):
        if sample is None or best is None:continue
        loss=sample[0]-best[0]
        if loss<.12:continue
        m,r=sample[1],best[1];brake,minimum,throttle=_metric(m,0),_metric(m,1),_metric(m,2);ref_brake,ref_minimum,ref_throttle=_metric(r,0),_metric(r,1),_metric(r,2);turn,max_steer,release,exit_speed=_metric(m,3),_metric(m,4),_metric(m,5),_metric(m,6);ref_turn,ref_max_steer,ref_release,ref_exit=_metric(r,3),_metric(r,4),_metric(r,5),_metric(r,6);turn_sign,dir_conf=_metric(m,7),(_metric(m,9) or 0);ref_sign,ref_dir_conf=_metric(r,7),(_metric(r,9) or 0);direction=_direction(turn_sign) if dir_conf>=.58 else None;outside=_outside_side(turn_sign) if dir_conf>=.58 else None;same_direction=bool(direction and ref_dir_conf>=.58 and turn_sign==ref_sign);title=tip=None
        if turn is not None and ref_turn is not None and turn<ref_turn-.006:
            if max_steer is not None and ref_max_steer is not None and max_steer>ref_max_steer+.12:
                title='Giro demasiado temprano';extra_deg=math.degrees(max_steer-ref_max_steer);tip=f'Espera un poco antes de girar hacia la {direction}. Prepara una entrada más abierta por la {outside}; estás usando aproximadamente {extra_deg:.0f} grados más de volante que en tu referencia.' if same_direction and outside else f'Espera un poco antes de girar y prepara una entrada más abierta; estás usando aproximadamente {extra_deg:.0f} grados más de volante que en tu referencia.'
            elif minimum<ref_minimum-1.5:
                title='Giro temprano';speed_delta=max(0,(ref_minimum-minimum)*3.6);tip=f'Retrasa ligeramente el giro hacia la {direction} y prepara la entrada más abierta por la {outside}; estás perdiendo aproximadamente {speed_delta:.0f} km/h de velocidad mínima.' if same_direction and outside else f'Retrasa ligeramente el giro y abre la entrada; estás perdiendo aproximadamente {speed_delta:.0f} km/h de velocidad mínima.'
        elif turn is not None and ref_turn is not None and turn>ref_turn+.006:
            title='Giro tardío';tip=f'Empieza a girar hacia la {direction} un poco antes para orientar el coche y volver antes al acelerador.' if throttle is not None and ref_throttle is not None and throttle>ref_throttle+.006 and direction else ('Empieza a girar un poco antes para poder orientar el coche y volver antes al acelerador.' if throttle is not None and ref_throttle is not None and throttle>ref_throttle+.006 else (f'Prueba iniciar el giro hacia la {direction} un poco antes, siguiendo el punto de tu mejor referencia.' if direction else 'Prueba iniciar el giro un poco antes, siguiendo el punto de tu mejor referencia.'))
        if title is None and all(v is not None for v in (turn,release,ref_turn,ref_release)):
            overlap=release-turn;ref_overlap=ref_release-ref_turn
            if ref_overlap>.006 and overlap<ref_overlap-.008:title='Falta giro durante la frenada';tip=f'Empieza a girar hacia la {direction} mientras terminas de soltar el freno; tu mejor referencia mantiene más solapamiento freno-volante.' if direction else 'Empieza a girar mientras terminas de soltar el freno; tu mejor referencia mantiene más solapamiento freno-volante.'
            elif ref_overlap<.002 and overlap>ref_overlap+.010 and minimum<ref_minimum-1.5:title='Demasiado giro con freno';tip='Suelta algo más el freno antes de cargar volante; estás frenando y girando más de lo necesario.'
        if title is None and brake is not None and ref_brake is not None and brake<ref_brake-.008 and abs(minimum-ref_minimum)<2:title,tip='Frenada temprana','Prueba frenar ligeramente más tarde; estás llegando a una velocidad mínima parecida.'
        elif title is None and throttle is not None and ref_throttle is not None and throttle>ref_throttle+.01:
            if exit_speed is not None and ref_exit is not None and exit_speed<ref_exit-1.0:title,tip='Salida comprometida','Vuelves tarde al acelerador y sales más lento. Prioriza orientar antes el coche y acelerar antes.'
            elif abs(minimum-ref_minimum)<2:title,tip='Aceleración tardía','Prioriza volver antes al acelerador en la salida.'
        elif title is None and minimum<ref_minimum-2 and brake is not None and ref_brake is not None and abs(brake-ref_brake)<.012:
            speed_delta=max(0,(ref_minimum-minimum)*3.6)
            if max_steer is not None and ref_max_steer is not None and max_steer>ref_max_steer+.12:
                extra_deg=math.degrees(max_steer-ref_max_steer);title='Exceso de volante';tip=f'Frenas en un punto parecido, pero usas unos {extra_deg:.0f} grados más de volante hacia la {direction} y pierdes cerca de {speed_delta:.0f} km/h. Prepara una entrada más abierta por la {outside} y deja correr más el coche.' if same_direction and outside else (f'Frenas en un punto parecido, pero usas unos {extra_deg:.0f} grados más de volante hacia la {direction} y pierdes cerca de {speed_delta:.0f} km/h. Abre la entrada y deja correr más el coche.' if direction else f'Frenas en un punto parecido, pero usas unos {extra_deg:.0f} grados más de volante y pierdes cerca de {speed_delta:.0f} km/h. Abre la entrada y deja correr más el coche.')
            else:title='Velocidad mínima baja';tip=f'Frenas en un punto parecido, pero llegas aproximadamente {speed_delta:.0f} km/h más lento al centro. Suelta progresivamente el freno y deja correr el coche.'
        if title:advice.append((i,loss,title,tip))
    return sorted(advice,key=lambda item:item[1],reverse=True)[:2]
