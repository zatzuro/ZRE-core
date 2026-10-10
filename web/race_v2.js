/* Race V2 read-only renderer. One physical series per CarIdx, four logical roles.
 * No Screen Builder dependency and no independent telemetry/strategy engine. */
(()=>{'use strict';
 const el=id=>document.getElementById(id),svg=tag=>document.createElementNS('http://www.w3.org/2000/svg',tag);
 const good=n=>typeof n==='number'&&Number.isFinite(n);
 const time=n=>{if(!good(n)||n<=0)return'—';const m=Math.floor(n/60);return m+':'+(n-m*60).toFixed(3).padStart(6,'0')};
 const unit=(v,suffix,digits=1)=>good(v)?v.toFixed(digits)+suffix:'—';
 const set=(id,v)=>{const n=el(id);if(n){const value=v==null||v===''?'—':String(v);if(n.textContent!==value)n.textContent=value}};
 const colors={YOU:'#7dcbfc',AHEAD:'#83e6a8',BEHIND:'#ffcb82',RIVAL:'#c7a0fd'};
 const labels={YOU:'TÚ',AHEAD:'ADELANTE',BEHIND:'DETRÁS',RIVAL:'RIVAL'};
 let latest=null,command=null,cache=new Map(),choices=[],pending=null,lastIdentity=null;
 let emphasis='auto';
 try{const stored=localStorage.getItem('zre-race-v2-emphasis');if(['auto','sprint','endurance'].includes(stored))emphasis=stored}catch(_){};
 const signature=rows=>JSON.stringify(rows||[]);
 const card=(key,value)=>{if(cache.get(key)===value)return false;cache.set(key,value);return true};
 function send(choice){
   if(!latest?.connected)return;
   pending=choice;
   command?.('rival',choice);
   // Update selection immediately without touching the other three roles.
   const race=latest.raceDashboard||{},rival=race.rival||{};
   set('rv2-rival-mode',choice==='auto'?'AUTO':'MANUAL · PENDIENTE');
   if(choice!=='auto'){
     const row=(race.classStandings||[]).find(x=>String(x.carIdx)===String(choice));
     if(row)set('rv2-rival-name','#'+row.carNumber+' · '+(row.driverName||'—'));
   }
 }
 function listCandidates(){
   const filter=String(el('rv2-rival-search')?.value||'').trim().toLowerCase().replace(/^#/,'');
   const items=choices.filter(x=>{
     if(!filter)return true;
     return [x.carNumber,x.driverName,'P'+x.classPosition,String(x.classPosition),x.carModel]
       .some(t=>String(t||'').toLowerCase().includes(filter));
   });
   const select=el('rv2-rival-select');if(!select)return;
   const active=latest?.raceDashboard?.rival||{},selected=String(pending!=null?pending:
      active.selectionMode==='manual'?active.requestedCarIdx??active.effectiveCarIdx:'auto');
   const sig=signature(items.map(x=>[x.carIdx,x.carNumber,x.driverName,x.classPosition]))+'|'+selected;
   if(card('candidate-list',sig)){
     const auto=new Option('AUTO · RIVAL DE CLASE','auto');
     const nodes=items.map(x=>new Option('P'+(x.classPosition??'—')+' · #'+x.carNumber+' · '+(x.driverName||'PILOTO NO CONFIRMADO'),String(x.carIdx)));
     if(selected!=='auto'&&!items.some(x=>String(x.carIdx)===selected)){
       nodes.unshift(new Option('SELECCIÓN MANUAL #'+selected+' · FUERA DE FILTRO',selected));
     }
     select.replaceChildren(auto,...nodes);
   }
   if(document.activeElement!==select)select.value=selected;
 }
 function choose(row){
   if(!row||row.isPlayer||row.carIdx==null)return;
   send(String(row.carIdx));
   listCandidates();
 }
 function buildStanding(row,rivalIdx){
   const button=document.createElement('button');button.type='button';button.className='rv2-standing-row';
   button.dataset.player=String(Boolean(row.isPlayer));
   button.dataset.rival=String(row.carIdx===rivalIdx);
   button.dataset.stale=String(row.presence!=='LIVE'&&row.presence!=='UNKNOWN');
   button.dataset.carIdx=String(row.carIdx);
   if(row.isPlayer){button.disabled=true;button.setAttribute('aria-label','Coche propio · no seleccionable como rival');}
   else button.setAttribute('aria-label','Seleccionar rival #'+row.carNumber+' · '+(row.driverName||'sin nombre'));
   const cell=(tag,value)=>{const node=document.createElement(tag);node.textContent=value;return node};
   const position=row.classPosition!=null?'P'+row.classPosition:'P—';
   const source=row.positionSource==='RESULTS_POSITIONS'?'OFICIAL':'FALLBACK';
   const driver=document.createElement('span');driver.className='rv2-driver';
   const name=cell('b',row.driverName||'SIN IDENTIDAD CONFIRMADA');
   const extra=cell('small',(row.carModel||'COCHE')+' · '+(row.presence==='STALE'?'ÚLTIMO REGISTRO':source));
   driver.append(name,extra);
   button.append(cell('strong',position),cell('strong','#'+(row.carNumber||'—')),driver,
                 cell('span',time(row.bestLapSeconds)),cell('span',time(row.lastLapSeconds)));
   button.addEventListener('click',()=>choose(row));
   return button;
 }
 function standings(data){
   const race=data.raceDashboard||{},rows=race.classStandings||[],own=rows.findIndex(x=>x.isPlayer);
   const scope=el('rv2-standing-scope')?.value||'near';
   choices=rows.filter(x=>!x.isPlayer);
   if(lastIdentity!==race.sessionIdentity){
     lastIdentity=race.sessionIdentity;pending=null;cache.clear();
   }
   const center=own>=0?rows.slice(Math.max(0,own-4),Math.min(rows.length,own+5)):rows.slice(0,9);
   const shown=scope==='all'?rows:center;
   const rivalIdx=(pending!=null&&pending!=='auto')?Number(pending):race.rival?.effectiveCarIdx;
   const mainSig=signature(shown.map(x=>[x,rivalIdx]));
   if(card('standings-near',mainSig)){
      const target=el('rv2-standing-rows');
      if(target){const position=target.scrollTop;target.replaceChildren(...shown.map(x=>buildStanding(x,rivalIdx)));target.scrollTop=position;}
   }
   const fullSig=signature(rows.map(x=>[x,rivalIdx]));
   if(card('standings-full',fullSig)){
     const target=el('rv2-standing-all');
     if(target){const position=target.scrollTop;target.replaceChildren(...rows.map(x=>buildStanding(x,rivalIdx)));target.scrollTop=position;}
   }
   set('rv2-standing-summary',data.connected?(rows.length+' COCHES · '+(race.ownPositionSource==='RESULTS_POSITIONS'?'POSICIÓN SDK OFICIAL':'FALLBACK IDENTIFICADO')):'ÚLTIMA CLASIFICACIÓN · SDK DESCONECTADO');
   listCandidates();
 }
 function liveMetrics(data){
   const race=data.raceDashboard||{},phys=race.physical||{},fuel=race.fuel||{},you=(race.paceSeries||[]).find(s=>s.carIdx===race.ownCarIdx);
   set('rv2-position',race.ownClassPosition!=null?'P'+race.ownClassPosition:'—');
   set('rv2-position-source',!data.connected?'ÚLTIMA CLASE · STALE':race.ownPositionSource==='RESULTS_POSITIONS'?'OFICIAL · CLASE':'FALLBACK / SIN DATO');
   for(const side of ['ahead','behind']){
     const row=phys[side];
     set('rv2-gap-'+side,row?.gapLabel||'SIN DATO');
     set('rv2-car-'+side,row?'#'+(row.carNumber||'—')+' · '+(row.driverName||'SIN IDENTIDAD'):'SIN REFERENCIA FÍSICA');
   }
   set('rv2-last-lap',data.self?.lastLap||'—');
   set('rv2-my-pace',time(you?.recentAverageSeconds));
   set('rv2-my-count',!data.connected?'HISTÓRICO · SDK SIN SEÑAL':you?.representative?you.sampleCount+' V. COMPARABLES':'MUESTRAS INSUFICIENTES · '+(you?.sampleCount||0)+'/3');
   set('rv2-fuel',unit(fuel.currentLiters,' L',1));
   set('rv2-fuel-source',data.self?.fuelSource||fuel.source||'SIN DATO');
   set('rv2-consumption',unit(fuel.observedLpl,' L/v',2));
   set('rv2-use-source',fuel.sampleCount?fuel.sampleCount+' LECTURAS':'SIN MUESTRAS');
   const remain=data.sessionIntelligence?.session?.observed?.timeRemain;
   set('rv2-remaining',!data.connected?'SIN SEÑAL':good(remain)&&remain>=0?Math.floor(remain/3600)+':'+String(Math.floor((remain%3600)/60)).padStart(2,'0')+':'+String(Math.floor(remain%60)).padStart(2,'0'):(data.teamContext?.remainingTime||'—'));
 }
 function plan(data){
   const v=data.racePlanVNext||{},plan=v.currentPlan||v.plan||{},state=v.raceState||{},fuel=v.fuelModel||{},window=plan.window||{},stops=plan.stops||[],next=stops[0]||{};
   const has=Boolean(plan.available),current=state.current_lap??state.completed_laps,goal=window.target??next.lap;
   const countdown=goal!=null&&current!=null?Math.max(0,Number(goal)-Number(current)):null;
   const status=!has?'PLAN NO DISPONIBLE':state.on_pit_road?'EN BOXES':window.state||'PLAN ESTABLE';
   const root=el('rv2-plan-card');if(root)root.dataset.state=String(status).toLowerCase().replaceAll(' ','-');
   set('rv2-box-lap',!has?'—':goal!=null?'V'+goal:plan.minimum_stops===0?'META':'—');
   set('rv2-box-countdown',!has?'SIN PLAN':countdown==null?'—':countdown===0?'AHORA':countdown+' VUELTAS');
   set('rv2-plan-status',status);
   for(const [id,key] of [['rv2-earliest','earliest_safe'],['rv2-target','target'],['rv2-fuel-limit','fuel_limit']])
      set(id,has&&window[key]!=null?'V'+window[key]:'—');
   const bar=el('rv2-window-marker');
   if(bar){
      const e=window.earliest_safe,f=window.fuel_limit;
      const ready=has&&good(e)&&good(f)&&f>e&&good(current);
      bar.hidden=!ready;if(ready)bar.style.left=Math.max(0,Math.min(100,(current-e)/(f-e)*100))+'%';
   }
   set('rv2-add-fuel',has&&good(next.fuel_to_add_liters)?'+'+next.fuel_to_add_liters.toFixed(1)+' L':'—');
   set('rv2-stops-left',has&&Number.isFinite(Number(plan.minimum_stops))?plan.minimum_stops:'—');
   set('rv2-tyres',state.require_tire_change===true?'REGLA ACTIVA · SIN DECISIÓN':'NO DEFINIDO');
   const future=(data.enduranceStrategy?.timeline||[]).find(x=>x.status==='future'&&x.driver);
   set('rv2-next-driver',next.driver||future?.driver||'SIN ASIGNAR');
   set('rv2-plan-source','RACE PLAN VNEXT · '+(fuel.confidence||'SIN CONFIANZA')+' · '+(fuel.source||'SIN FUENTE'));
 }
 function rival(data){
   const race=data.raceDashboard||{},selected=race.rival||{},row=selected.selectedRival,obs=selected.observation||{},director=data.raceDirector||{};
   if(pending!=null){
     const expected=pending==='auto'?'auto':'manual';
     if(selected.selectionMode===expected&&(pending==='auto'||String(selected.requestedCarIdx)===String(pending)))pending=null;
   }
   const current=pending!=null&&pending!=='auto'?race.classStandings?.find(x=>String(x.carIdx)===String(pending)):row;
   const effective=current||row;
   set('rv2-rival-name',effective?'#'+effective.carNumber+' · '+(effective.driverName||'SIN NOMBRE'):director.rival||'SIN RIVAL');
   set('rv2-rival-mode',pending!=null?'CAMBIANDO…':selected.selectionMode==='manual'?'MANUAL':'AUTO');
   set('rv2-rival-pos',effective?.classPosition!=null?'P'+effective.classPosition:'—');
   set('rv2-rival-presence',obs.presence||selected.selectionState||'SIN DATO');
   set('rv2-rival-best',time(effective?.bestLapSeconds));
   set('rv2-rival-last',time(effective?.lastLapSeconds));
   set('rv2-rival-pace',time(selected.rivalPace));
   const role=Object.entries(race.roles||{}).find(([k,idx])=>idx===effective?.carIdx&&['AHEAD','BEHIND'].includes(k));
   const neighbor=role&&race.physical?(role[0]==='AHEAD'?race.physical.ahead:race.physical.behind):null;
   const evidence=obs.presence==='LIVE'?(obs.gapEvidence||{}):{};
   const observedGap=good(evidence.seconds)?'≈ '+Math.abs(evidence.seconds).toFixed(2)+' s · EST.':'SIN GAP FÍSICO';
   set('rv2-rival-gap',neighbor?.gapLabel||observedGap);
   const age=obs.lastSeenAgo;
   set('rv2-rival-age',obs.presence==='STALE'?'ÚLTIMA OBS. HACE '+(good(age)?Math.round(age)+' s':'TIEMPO DESCONOCIDO'):
        obs.presence==='LIVE'?'OBSERVADO · SDK':selected.selectionState==='TEMPORARILY_UNAVAILABLE'?'MANUAL CONSERVADO · SIN DATOS':'SIN POSICIÓN OBSERVABLE');
   set('rv2-rival-car',effective?.carModel||'—');
 }
 function pace(data){
   const race=data.raceDashboard||{},series=race.paceSeries||[],roles=race.roles||{},one=new Map(series.map(s=>[s.carIdx,s]));
   const legend=el('rv2-pace-legend');if(legend){
     const str=signature([roles,series.map(x=>[x.carIdx,x.roles,x.recentAverageSeconds,x.sampleCount,x.observationState,x.carNumber])]);
     if(card('legend',str))legend.replaceChildren(...['YOU','AHEAD','BEHIND','RIVAL'].map(role=>{
        const node=document.createElement('div');const b=document.createElement('b');const idx=roles[role],row=one.get(idx);
        b.style.color=colors[role];b.textContent=labels[role]+' · '+(row?'#'+row.carNumber:'SIN COCHE');
        const sub=document.createElement('span');
        const shared=row&&row.roles.length>1?' · '+row.roles.map(x=>labels[x]).join(' + '):'';
        sub.textContent=row?.representative?time(row.recentAverageSeconds)+' · '+row.sampleCount+' V'+shared:
             (row?row.sampleCount+'/3 V · NO REPRESENTATIVO'+shared:'SIN MUESTRAS');
        node.append(b,sub);return node;
     }));
   }
   const delta=race.paceDifferenceToRival;set('rv2-pace-difference',good(delta)?'Δ RITMO TÚ − RIVAL: '+(delta>0?'+':'')+delta.toFixed(3)+' s ('+(delta>0?'SOY MÁS LENTO':delta<0?'SOY MÁS RÁPIDO':'IGUAL')+')':'Δ RITMO VS RIVAL: SIN DATOS COMPARABLES');
   const sig=signature(series.map(s=>[s.carIdx,s.roles,s.samples]));
   if(!card('chart',sig))return;
   const g=el('rv2-pace-series'),grid=el('rv2-pace-grid');if(!g||!grid)return;
   const comparable=series.flatMap(s=>(s.samples||[]).filter(x=>x.comparable&&good(x.lapTimeSeconds)).map(x=>x.lapTimeSeconds));
   if(!comparable.length){g.replaceChildren();grid.replaceChildren();return;}
   const ordered=[...comparable].sort((a,b)=>a-b),median=ordered[Math.floor(ordered.length/2)];
   const rangeLimit=Math.max(2,median*.06);
   let lo=Math.min(...comparable.filter(x=>x>=median-rangeLimit)),hi=Math.max(...comparable.filter(x=>x<=median+rangeLimit));
   if(!good(lo)||!good(hi)){lo=median-1;hi=median+1}
   const padding=Math.max(.65,(hi-lo)*.22);lo-=padding;hi+=padding;
   const plot={left:60,right:882,top:16,bottom:180};
   const coordY=value=>plot.bottom-(value-lo)/(hi-lo)*(plot.bottom-plot.top);
   const x=slot=>plot.left+(plot.right-plot.left)*slot/7;
   const axes=[];
   for(let i=0;i<5;i++){
      const value=lo+(hi-lo)*i/4,y=coordY(value);
      const line=svg('line');line.classList.add('rv2-chart-grid-line');
      line.setAttribute('x1',plot.left);line.setAttribute('y1',y);line.setAttribute('x2',plot.right);line.setAttribute('y2',y);axes.push(line);
      const label=svg('text');label.classList.add('rv2-chart-label');label.setAttribute('x',3);label.setAttribute('y',y+4);label.textContent=time(value);axes.push(label);
   }
   for(let i=0;i<8;i++){
      const t=svg('text');t.classList.add('rv2-chart-label');
      t.setAttribute('x',x(i));t.setAttribute('y',205);t.setAttribute('text-anchor','middle');
      t.textContent=i===7?'ACTUAL':String(i-7);axes.push(t);
   }
   grid.replaceChildren(...axes);
   const nodes=[];
   for(const entry of series){
      const code=entry.roles?.[0]||'RIVAL',color=colors[code],samples=(entry.samples||[]).slice(-8);
      const realLaps=samples.map(s=>Number(s.lapNumber)).filter(Number.isFinite);
      if(!realLaps.length)continue;
      const last=Math.max(...realLaps),points=new Map(samples.map(item=>[7+Number(item.lapNumber)-last,item]));
      let segment=[];
      const endSegment=()=>{if(segment.length>1){const path=svg('polyline');path.classList.add('rv2-pace-series-path');path.setAttribute('stroke',color);path.setAttribute('points',segment.join(' '));nodes.push(path)}segment=[]};
      for(let slot=0;slot<8;slot++){
         const point=points.get(slot);
         if(!point||!good(point.lapTimeSeconds)||!point.comparable){endSegment();if(point&&good(point.lapTimeSeconds)){
            const out=svg('circle');out.classList.add('rv2-outlier');out.setAttribute('cx',x(slot));
            out.setAttribute('cy',Math.max(plot.top,Math.min(plot.bottom,coordY(point.lapTimeSeconds))));
            out.setAttribute('r',4);out.setAttribute('stroke',color);
            const title=svg('title');title.textContent='#'+entry.carNumber+' · V'+point.lapNumber+' · '+time(point.lapTimeSeconds)+' · NO COMPARABLE · '+point.comparabilityReason;out.append(title);nodes.push(out);
         }continue;}
         const yy=Math.max(plot.top,Math.min(plot.bottom,coordY(point.lapTimeSeconds)));
         segment.push(x(slot)+','+yy);
         const dot=svg('circle');dot.classList.add('rv2-point');dot.setAttribute('cx',x(slot));dot.setAttribute('cy',yy);dot.setAttribute('r',3.6);dot.setAttribute('fill',color);
         const title=svg('title');title.textContent='#'+entry.carNumber+' · '+entry.roles.map(v=>labels[v]).join(' + ')+' · V'+point.lapNumber+' · '+time(point.lapTimeSeconds)+' · '+(point.driverName||'Piloto no confirmado');dot.append(title);nodes.push(dot);
      }
      endSegment();
   }
   g.replaceChildren(...nodes);
 }
 function fuel(data){
    const f=data.raceDashboard?.fuel||{},vnext=data.racePlanVNext||{};
    set('rv2-fuel-quality',f.source||'SIN DATO');
    set('rv2-fuel-observed',unit(f.observedLpl,' L/v',2));
    set('rv2-fuel-target',good(f.targetLpl)?unit(f.targetLpl,' L/v',2):'OBJETIVO NO DEFINIDO');
    set('rv2-fuel-deviation',good(f.deviationLpl)?(f.deviationLpl>0?'+':'')+f.deviationLpl.toFixed(2)+' L/v':'—');
    if(el('rv2-fuel-deviation'))el('rv2-fuel-deviation').dataset.trend=f.deviationLpl>0?'over':f.deviationLpl<0?'under':'equal';
    set('rv2-fuel-autonomy',good(f.autonomyLaps)?'≈'+f.autonomyLaps.toFixed(1)+' V':'—');
    const window=vnext.currentPlan?.window||{};
    set('rv2-fuel-context',vnext.available?'PRÓXIMA PARADA: '+(window.target!=null?'V'+window.target:'NO DEFINIDA')+' · '+(vnext.fuelModel?.confidence||'SIN CONFIANZA'):'PLAN NO DISPONIBLE · no asumir que se evita una parada');
    const official=data.enduranceStrategy?.raceFormat;
    set('rv2-race-emphasis',emphasis==='auto'?(official?'FORMATO '+official+' · SDK / MODELO':'FORMATO: NO CONFIRMADO · VISTA GENERAL'):
        'ÉNFASIS VISUAL '+emphasis.toUpperCase()+' · NO ALTERA ESTRATEGIA');
 }
 function render(data){
    latest=data;const race=data.raceDashboard;
    if(!race){for(const id of ['rv2-position','rv2-gap-ahead','rv2-gap-behind','rv2-last-lap','rv2-my-pace','rv2-fuel','rv2-consumption','rv2-remaining'])set(id,'—');
       el('rv2-standing-rows')?.replaceChildren();el('rv2-standing-all')?.replaceChildren();el('rv2-pace-series')?.replaceChildren();
       cache.clear();return;}
    liveMetrics(data);standings(data);plan(data);rival(data);pace(data);fuel(data);
 }
 function init(sendSetting){
    command=sendSetting;
    document.body.dataset.raceEmphasis=emphasis;
    if(el('rv2-emphasis-select')){
      el('rv2-emphasis-select').value=emphasis;
      el('rv2-emphasis-select').addEventListener('change',event=>{
        emphasis=['auto','sprint','endurance'].includes(event.target.value)?event.target.value:'auto';
        document.body.dataset.raceEmphasis=emphasis;
        try{localStorage.setItem('zre-race-v2-emphasis',emphasis)}catch(_){}
        if(latest)fuel(latest);
      });
    }
    el('rv2-rival-auto')?.addEventListener('click',()=>{send('auto');listCandidates()});
    el('rv2-rival-search')?.addEventListener('input',()=>{cache.delete('candidate-list');listCandidates()});
    el('rv2-rival-select')?.addEventListener('change',e=>send(e.target.value));
    el('rv2-standing-scope')?.addEventListener('change',()=>{cache.delete('standings-near');if(latest)standings(latest)});
    el('rv2-standings-expand')?.addEventListener('click',()=>{el('rv2-standings-dialog')?.showModal();if(latest)standings(latest)});
    el('rv2-plan-expand')?.addEventListener('click',()=>{el('race-plan-dialog')?.showModal()});
 }
 window.ZRERaceV2={render,init};
})();