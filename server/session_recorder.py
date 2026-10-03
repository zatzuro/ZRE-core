"""Local, event-only session journals. Bounded queue and off-thread disk work."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import queue
import re
import shutil
import threading
import time
from uuid import uuid4


class SessionRecorder:
    def __init__(self,path,max_bytes=5_000_000,retention_days=7):
        self.path=Path(path);self.root=self.path.parent/'session_logs';self.max_bytes=max_bytes
        self.retention_days=retention_days;self.session_id=None;self.session_dir=None;self.timeline_path=None
        self.summary={};self.pending=queue.Queue(maxsize=512);self.thread=None;self.lock=threading.Lock()
        self.dropped_events=0;self.errors=0;self._contexts={};self._last_cleanup=0;self._signatures={};self._audits={};self._conditions_at=None

    def _enqueue(self,command):
        with self.lock:
            if command[0]=='event' and self.pending.qsize()>=480:self.dropped_events+=1;return False
            try:self.pending.put_nowait(command)
            except queue.Full:self.dropped_events+=1;return False
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._run,name='zre-session-journal',daemon=True);self.thread.start()
        return True

    def start_session(self,identity,metadata=None):
        if self.session_dir:self.finish_session('session-change')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        key=re.sub(r'[^a-zA-Z0-9_-]+','-',str(identity or 'unknown')).strip('-')[:80]
        folder=self.root/f'{stamp}_{key}_{uuid4().hex[:8]}'
        data={'sessionId':folder.name,'startedAt':datetime.now(timezone.utc).isoformat(),'identity':str(identity),'metadata':deepcopy(metadata or {})}
        if not self._enqueue(('start',folder,data)):return None
        self.session_id=folder.name;self.session_dir=folder;self.timeline_path=folder/'timeline.jsonl'
        self._signatures={};self._audits={};self._conditions_at=None
        return self.session_id

    def write(self,record):
        if not self.session_dir:return
        item=dict(record or {});item.pop('telemetry',None) # Do not duplicate raw lap telemetry.
        item.setdefault('utc',datetime.now(timezone.utc).isoformat())
        item.setdefault('source','SDK_OBSERVED' if item.get('type')=='lap' else 'ZRE_INFERRED')
        self._enqueue(('event',self.session_dir,deepcopy(item)))

    def finish_session(self,reason='session-change',extra=None):
        if not self.session_dir:return None
        folder=self.session_dir
        if not self._enqueue(('finish',folder,{'reason':reason,'extra':deepcopy(extra),'utc':datetime.now(timezone.utc).isoformat()})):
            return None
        self.session_id=None;self.session_dir=None;self.timeline_path=None
        return folder

    def _changed(self,key,signature):
        if self._signatures.get(key)==signature:return False
        self._signatures[key]=signature;return True

    def observe(self,payload,session_time=None):
        if not self.session_dir:return
        intel=payload.get('sessionIntelligence') or {};own=payload.get('self') or {};mode=payload.get('sessionMode')
        env=(intel.get('environment') or {}).get('observed') or {}
        conditions={k:(round(v,1) if isinstance(v,(int,float)) and not isinstance(v,bool) else v) for k,v in env.items()}
        state=(intel.get('session') or {}).get('observed') or {}
        condition_signature=json.dumps([conditions,state.get('flags'),state.get('state'),state.get('pitsOpen')],sort_keys=True)
        state_signature=(state.get('flags'),state.get('state'),state.get('pitsOpen'))
        state_changed=self._changed('session-state',state_signature)
        conditions_due=self._conditions_at is None or (session_time is not None and session_time-self._conditions_at>=30)
        if (state_changed or conditions_due) and self._changed('conditions',condition_signature):
            self._conditions_at=session_time or 0
            self.write({'type':'conditions','sessionTime':session_time,'environment':conditions,'session':state,'source':'SDK_OBSERVED'})
        coach=payload.get('coach') or {}
        coach_signature=(coach.get('bestLap'),coach.get('optimalLap'),str(coach.get('primary')))
        if mode in ('practice','qualifying') and self._changed('coach',coach_signature):self.write({'type':'coach','sessionTime':session_time,'mode':mode,'bestLap':coach.get('bestLap'),'optimalLap':coach.get('optimalLap'),'focus':coach.get('primary'),'source':'ZRE_INFERRED'})
        for lap in (own.get('laps') or [])[-1:]:
            if self._changed('own-lap',lap.get('lap')):self.write({'type':'own_lap_snapshot','lap':lap,'fuelValue':own.get('fuelValue'),'fuelSource':own.get('fuelSource'),'sessionTime':session_time,'source':'SDK_OBSERVED'})
        competitors=(intel.get('competitors') or {}).get('observed') or []
        for row in competitors:
            idx=row['carIdx'];presence=row.get('presence')
            if self._changed(('presence',idx),presence):self.write({'type':'rival_presence','carIdx':idx,'presence':presence,'lastSeenSessionTime':row.get('lastSeenSessionTime'),'lastLap':row.get('lastLap'),'source':'SDK_OBSERVED','sessionTime':session_time})
            for pit in row.get('pitHistory') or []:
                signature=(pit.get('source'),pit.get('status'),pit.get('exitLap'),pit.get('abnormalLapExcess'),str(pit.get('pitRoadDurationObserved')))
                if self._changed(('pit',idx,pit.get('eventId')),signature):self.write({'type':'rival_pit','carIdx':idx,'event':pit,'source':pit.get('source'),'confidence':pit.get('confidence'),'sessionTime':session_time})
            audit=self._audits.get(idx)
            if audit and not audit.get('evaluated'):
                event=next((p for p in row.get('pitHistory') or [] if (p.get('sessionTime') or -1)>audit['loggedAt'] and p.get('lap') is not None),None)
                actual=event.get('lap') if event else None
                missed=presence=='LIVE' and (row.get('lapsComplete') or 0)>audit['toLap']+1
                if actual is not None or missed:
                    hit=actual is not None and audit['fromLap']<=actual<=audit['toLap']
                    error=0 if hit else min(abs(actual-audit['fromLap']),abs(actual-audit['toLap'])) if actual is not None else None
                    self.write({'type':'prediction_outcome','carIdx':idx,'prediction':audit,'actualPitLap':actual,'hit':hit,'errorLaps':error,
                        'resultConfidence':event.get('confidence') if event else 'LOW','resultSource':event.get('source') if event else 'NO_STOP_OBSERVED_IN_WINDOW','source':'ZRE_INFERRED','confidence':audit['confidence'],'sessionTime':session_time})
                    audit['evaluated']=True
            prediction=row.get('nextPitEstimate')
            if prediction and self._changed(('prediction',idx),(prediction['fromLap'],prediction['toLap'],prediction['confidence'])):
                self.write({'type':'strategy_prediction','carIdx':idx,'prediction':prediction,'source':'ZRE_INFERRED','confidence':prediction['confidence'],'sessionTime':session_time})
                self._audits[idx]={**prediction,'loggedAt':session_time or 0,'evaluated':False}
        primary=(payload.get('rivalStrategy') or {}).get('primary')
        if primary and self._changed('strategy',(primary.get('carIdx'),primary.get('action'),primary.get('confidence'),primary.get('reason'))):
            self.write({'type':'strategy_decision','decision':primary,'source':'ZRE_INFERRED','sessionTime':session_time})
        # Signatures are bounded even for many stops in a long session.
        if len(self._signatures)>2048:self._signatures={k:v for k,v in self._signatures.items() if not isinstance(k,tuple) or k[0]!='pit'}

    def _write_json(self,path,data):
        temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');temp.replace(path)

    def _checkpoint(self,folder,context):
        context['droppedEvents']=self.dropped_events;context['loggingErrors']=self.errors
        self._write_json(folder/'summary.json',context)
        lines=[f"# ZRE Session {folder.name}",'',f"- Circuito: {context.get('metadata',{}).get('track','—')}",
            f"- Tipo: {context.get('metadata',{}).get('sessionType','—')}",f"- Eventos: {context['events']}",
            f"- Vueltas: {context['laps']}",f"- Predicciones: {context['predictions']}",f"- Resultados: {context['outcomes']}",
            f"- Estado: {context.get('finishReason','ACTIVE')}",'', 'Bitácora exclusivamente local. SDK_OBSERVED y ZRE_INFERRED identifican fuentes.']
        for result in context.get('predictionResults',[]):
            lines.append(f"- Rival {result['carIdx']}: ventana {result['prediction']['fromLap']}–{result['prediction']['toLap']}, resultado {result['actualPitLap']}, acierto {result['hit']}, error {result['errorLaps']}")
        (folder/'summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        self.summary=dict(context)

    def _run(self):
        while True:
            try:command=self.pending.get(timeout=1)
            except queue.Empty:
                with self.lock:
                    if self.pending.empty():self.thread=None;return
                continue
            kind,folder,data=command
            try:
                if kind=='start':
                    folder.mkdir(parents=True,exist_ok=True)
                    self._write_json(folder/'session.json',data);(folder/'timeline.jsonl').touch()
                    self._contexts[folder]={**data,'events':0,'laps':0,'predictions':0,'outcomes':0,'predictionResults':[]}
                    self._checkpoint(folder,self._contexts[folder]);self.cleanup_old_sessions()
                elif kind=='event' and folder in self._contexts:
                    path=folder/'timeline.jsonl'
                    if path.exists() and path.stat().st_size>=self.max_bytes:
                        previous=path.with_suffix('.jsonl.1');path.replace(previous)
                    with path.open('a',encoding='utf-8') as handle:handle.write(json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
                    ctx=self._contexts[folder];ctx['events']+=1
                    if data.get('type') in ('lap','own_lap_snapshot'):ctx['laps']+=int(data.get('type')=='own_lap_snapshot')
                    if data.get('type')=='strategy_prediction':ctx['predictions']+=1
                    if data.get('type')=='prediction_outcome':
                        ctx['outcomes']+=1;ctx['predictionResults'].append(data);del ctx['predictionResults'][:-128]
                    if ctx['events']%50==0:self._checkpoint(folder,ctx);self.cleanup_old_sessions()
                elif kind=='finish' and folder in self._contexts:
                    ctx=self._contexts.pop(folder);ctx.update(finishedAt=data['utc'],finishReason=data['reason'],final=data.get('extra'))
                    self._checkpoint(folder,ctx);self.cleanup_old_sessions(force=True)
            except (OSError,ValueError,TypeError):self.errors+=1
            finally:self.pending.task_done()

    def cleanup_old_sessions(self,force=False):
        """Off-thread expiry, plus a 256 MB cap; protect active/queued sessions."""
        now=time.time()
        if not force and now-self._last_cleanup<3600:return
        self._last_cleanup=now
        try:
            folders=[];total=0
            for folder in self.root.iterdir():
                if not folder.is_dir() or folder.is_symlink() or folder==self.session_dir or folder in self._contexts:continue
                marker=folder/'summary.json';age=(marker if marker.exists() else folder).stat().st_mtime
                size=sum(x.stat().st_size for x in folder.iterdir() if x.is_file() and not x.is_symlink())
                if now-age>max(1,self.retention_days)*86400:shutil.rmtree(folder);continue
                folders.append((age,size,folder));total+=size
            for _,size,folder in sorted(folders):
                if total<=256_000_000 and len(folders)<=128:break
                shutil.rmtree(folder);total-=size;folders.pop(0)
        except OSError:self.errors+=1

    def flush(self,timeout=5):
        deadline=time.monotonic()+timeout
        while self.pending.unfinished_tasks and time.monotonic()<deadline:time.sleep(.01)
        return not self.pending.unfinished_tasks

    def close(self):
        self.finish_session('shutdown');self.flush()
