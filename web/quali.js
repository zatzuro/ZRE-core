/* Quali UI. All modes and attempts originate from the backend's single authority. */
(()=>{'use strict';
const $=id=>document.getElementById(id), svg=tag=>document.createElementNS('http://www.w3.org/2000/svg',tag);
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const format=n=>{if(!finite(n)||n<=0)return '—';const m=Math.floor(n/60);return m+':'+(n-m*60).toFixed(3).padStart(6,'0')};
const put=(id,v)=>{const x=$(id);if(x){const t=v==null||v===''?'—':String(v);if(x.textContent!==t)x.textContent=t;}};
const signed=n=>finite(n)?(n>0?'+':'')+n.toFixed(3)+' s':'—';
let mapSignature='',sectorSignature='',garageSignature='',attemptSignature='';
let lastSource=null;
function sync(data,role){
  const q=data?.qualifying||{},practice=q.officialSessionType&&String(q.officialSessionType).toLowerCase().includes('practice');
  const controls=$('quali-mode-control'),newRun=$('quali-new-run');
  const canToggle=Boolean(data?.connected&&practice&&role!=='spotter');
  if(controls)controls.hidden=!canToggle;
  if(newRun)newRun.hidden=!(canToggle&&q.qualifyingMode==='simulated');
  const select=$('quali-mode-select');
  if(select&&document.activeElement!==select)select.value=q.qualifyingMode==='simulated'?'simulate':'training';
}
function mode(data,garage){
  const q=data.qualifying||{},run=q.activeRun||{};
  put('q-kind',q.qualifyingMode==='official'?'OFICIAL':q.qualifyingMode==='simulated'?'SIMULADA':'NO ACTIVA');
  put('q-run-id',run.runId?'TANDA '+run.runId:'SIN TANDA');
  put('q-session-source',q.officialSessionType?'iRacing '+q.officialSessionType:'SDK NO DISPONIBLE');
  put('q-lap-state',q.inGarage?'GARAGE':q.onPitRoad?'PIT LANE':q.onTrack?'EN PISTA':'SIN POSICIÓN CONFIRMADA');
  $('quali-view')?.classList.toggle('q-garage-active',Boolean(garage));
  if($('q-garage'))$('q-garage').hidden=!garage;
}
function kpis(data){
 const q=data.qualifying||{},self=data.self||{},coach=data.coach||{};
 const delta=q.deltaReferences?.LapDeltaToBestLap;
 const n=delta?.valid===true?delta.value:null;
 put('q-delta',signed(n));put('q-delta-source',n!=null?'SDK · MEJOR PERSONAL':'SIN DELTA SDK VÁLIDO');
 if($('q-delta'))$('q-delta').dataset.trend=n>0?'loss':n<0?'gain':'neutral';
 put('q-best',self.bestLap);put('q-last',self.lastLap);
 put('q-optimal',coach.optimalLap);put('q-potential',coach.potential);
 put('q-position',q.qualifyingMode==='official'&&q.classPosition!=null?'P'+q.classPosition:'NO OFICIAL');
 put('q-time-left',finite(q.timeRemaining)&&q.timeRemaining>=0?Math.floor(q.timeRemaining/60)+':'+String(Math.floor(q.timeRemaining%60)).padStart(2,'0'):'—');
}
function map(data){
 const tm=data.coach?.trackMap||{},points=tm.points||[],markers=(tm.markers||[]).slice(0,3);
 const sig=JSON.stringify([points,markers]);if(mapSignature===sig)return;mapSignature=sig;
 const line=$('q-map-line'),g=$('q-map-markers'),exists=Array.isArray(points)&&points.length>10;
 if(!line||!g)return;
 line.setAttribute('points',exists?points.filter(x=>finite(x.x)&&finite(x.y)).map(p=>p.x+','+p.y).join(' '):'');
 if($('q-map-empty'))$('q-map-empty').hidden=exists;
 put('q-map-status',exists?(tm.geometrySource||tm.source||'TRAZADO ZRE'):'TRAZADO EN CONSTRUCCIÓN');
 const nodes=exists?markers.filter(p=>finite(p.x)&&finite(p.y)).map((p,i)=>{
    const item=svg('g');item.classList.add('q-map-spot');
    const c=svg('circle');c.setAttribute('cx',p.x);c.setAttribute('cy',p.y);c.setAttribute('r',i===0?'2.5':'1.9');
    const t=svg('text');t.setAttribute('x',p.x+2.4);t.setAttribute('y',p.y-2.1);t.textContent=p.corner||p.label||'ZONA';
    item.append(c,t);return item;
 }):[];
 g.replaceChildren(...nodes);
}
function priorities(data){
 const host=$('q-priorities'),list=(data.coach?.curveRecommendations||[]).slice(0,3);if(!host)return;
 const sig=JSON.stringify(list);if(host.dataset.signature===sig)return;host.dataset.signature=sig;
 if(!list.length){const p=document.createElement('p');p.textContent='Sin recomendaciones contrastadas. Completa vueltas comparables.';host.replaceChildren(p);return}
 host.replaceChildren(...list.map(c=>{
  const d=document.createElement('div');d.className='q-priority';
  const b=document.createElement('b');b.textContent=c.zone||'ZONA';
  const t=document.createElement('span');t.textContent=(c.title||'')+' · '+(c.advice||'');
  t.title=c.advice||'';d.append(b,t);return d;
 }));
 const first=list[0];put('q-focus-zone',first.zone);put('q-focus-advice',first.advice||first.title);
}
function sectors(data){
 const q=data.qualifying||{},starts=q.sectorBoundaries||[],elapsed=q.sectorTimes||[],last=q.lastSectors||[];
 const run=q.activeRun||{},valid=(run.attempts||[]).filter(a=>a.status==='VALID'&&a.sectorTimes?.length===starts.length);
 const reference=valid.sort((a,b)=>a.lapTime-b.lapTime)[0]?.sectorTimes||[];
 const sig=JSON.stringify([starts,elapsed,last,reference]);if(sectorSignature===sig)return;sectorSignature=sig;
 put('q-sector-source',starts.length?'ZRE CALCULADO · LÍMITES SDK':'SIN SECTORES SDK');
 const rows=$('q-sector-rows');if(!rows)return;
 if(!starts.length){const p=document.createElement('p');p.textContent='No hay límites de sectores compatibles disponibles.';rows.replaceChildren(p);return}
 rows.replaceChildren(...starts.map((start,i)=>{
   const self=last[i]??(elapsed[i]??null),ref=reference[i]??null;
   const change=finite(self)&&finite(ref)?self-ref:null;
   const div=document.createElement('div');div.className='q-sector-row'+(elapsed.length===i?' current':'');
   const cols=['S'+(i+1),format(self),format(ref),signed(change)];
   cols.forEach((value,k)=>{const node=document.createElement(k===3?'b':'span');node.textContent=value;if(k===3)node.dataset.trend=change>0?'loss':change<0?'gain':'neutral';div.append(node)});
   return div;
 }));
}
function traffic(data){
 const intel=data.sessionIntelligence||{},env=intel.environment?.observed||{},t=intel.traffic?.observed||{};
 const neighbor=(key,nameId,gapId)=>{
   const value=t[key];const present=value?.presence==='LIVE'&&!value.identityAmbiguous;
   put(nameId,present?(value.driver||'#'+value.number):'—');
   const frac=value?.relativeLapFraction;
   put(gapId,present&&finite(frac)?(Math.abs(frac)*100).toFixed(1)+'% VUELTA · ESTIMADO':'SIN POSICIÓN ACTUAL');
 };
 neighbor('nearestAhead','q-ahead','q-gap-ahead');neighbor('nearestBehind','q-behind','q-gap-behind');
 put('q-flag',intel.session?.observed?.flags==null?'NO DISPONIBLE':'SDK '+intel.session.observed.flags);
 put('q-track-temp',finite(env.TrackTemp)?Number(env.TrackTemp).toFixed(1)+' °C':'NO DISPONIBLE');
}
function car(data){
 const self=data.self||{},q=data.qualifying||{},wear=self.wear||{};
 for(const c of ['FL','FR','RL','RR'])put('q-tyre-'+c.toLowerCase(),wear[c]||'—');
 put('q-fuel',finite(q.fuelValue)?q.fuelValue.toFixed(1)+' L':'—');
 put('q-consumption',finite(q.fuelPerLap)?q.fuelPerLap.toFixed(2)+' L/v':'—');
 put('q-range',finite(q.autonomyLaps)?'≈'+q.autonomyLaps.toFixed(1)+' v':'—');
}
function attempts(q){
 const run=q.activeRun||{},items=run.attempts||[],counts=run.counts||{};
 const sig=JSON.stringify([run.runId,items]);if(attemptSignature===sig)return;attemptSignature=sig;
 put('q-attempt-count',items.length);
 put('q-attempt-valid',counts.VALID||0);
 put('q-attempt-pending',counts['PENDING VALIDATION']||0);
 put('q-run-best',format(run.bestValidLap));
 put('q-attempt-status',items.length?'ÚLTIMO: '+items.at(-1).status:'SIN VUELTAS CLASIFICABLES');
 put('q-attempt-timeline',items.length?items.slice(-6).map(x=>'V'+x.sourceLap+' '+format(x.lapTime)+' · '+x.status).join('   |   '):'La primera vuelta parcial tras activar Quali no se incorpora.');
}
function updateSelection(select,items,prefer){
 if(!select)return;const signature=items.map(x=>x.attemptId).join('|');
 if(select.dataset.signature!==signature){
   const before=select.value;select.replaceChildren(...items.map(x=>new Option('V'+x.sourceLap+' · '+format(x.lapTime),x.attemptId)));
   select.dataset.signature=signature;
   select.value=items.some(x=>x.attemptId===before)?before:(prefer||items[0]?.attemptId||'');
 }
}
function comparison(q){
 const runs=[...(q.previousRuns||[]),q.activeRun].filter(Boolean);
 const arr=runs.flatMap(run=>(run.attempts||[]).map(a=>({...a,runLabel:run.runId})))
  .filter(a=>a.status==='VALID'&&a.sectorTimes?.length===q.sectorBoundaries?.length);
 updateSelection($('q-compare-a'),arr,arr.at(-2)?.attemptId);
 updateSelection($('q-compare-b'),arr,arr.at(-1)?.attemptId);
 const a=arr.find(x=>x.attemptId===$('q-compare-a')?.value),b=arr.find(x=>x.attemptId===$('q-compare-b')?.value);
 if(!a||!b||a===b||a.sectorSource!==b.sectorSource){put('q-comparison','Comparación no disponible: se requieren dos vueltas validadas con sectores y fuentes compatibles.');put('q-comparison-sectors','—');return}
 put('q-comparison','T '+a.runLabel+' V'+a.sourceLap+' '+format(a.lapTime)+' vs T '+b.runLabel+' V'+b.sourceLap+' '+format(b.lapTime)+' · Δ '+signed(b.lapTime-a.lapTime)+' · '+(a.sectorSource||'FUENTE DESCONOCIDA'));
 const sectors=a.sectorTimes.map((n,i)=>'S'+(i+1)+' '+signed(b.sectorTimes[i]-n));
 put('q-comparison-sectors',sectors.join('   |   '));
}
function garage(data){
 const q=data.qualifying||{},run=q.activeRun||{};
 put('q-garage-run',run.runId?'TANDA '+run.runId:'SIN TANDA');
 comparison(q);
 const host=$('q-garage-curves');if(!host)return;
 const rows=data.coach?.allCorners||[];const sig=JSON.stringify(rows);if(garageSignature===sig)return;garageSignature=sig;
 host.replaceChildren(...rows.map(c=>{
   const card=document.createElement('div');card.className='q-garage-curve';card.dataset.valid=String(c.state==='diagnosis');
   const title=document.createElement('strong');title.textContent=(c.zone||'TRAMO')+' · '+(c.title||'Sin diagnóstico');
   const p=document.createElement('p');p.textContent=c.advice||'Completa más vueltas comparables.';card.append(title,p);return card;
 }));
}
function render(data,options={}){
 lastSource=data;const q=data.qualifying||{};
 mode(data,options.garage);kpis(data);map(data);priorities(data);sectors(data);traffic(data);car(data);attempts(q);
 if(options.garage)garage(data);
}
['q-compare-a','q-compare-b'].forEach(id=>$(id)?.addEventListener('change',()=>lastSource&&comparison(lastSource.qualifying||{})));
$('q-setup-engineer')?.addEventListener('click',()=>$('setup-engineer-dialog')?.showModal());
window.ZREQuali={render,sync};
})();