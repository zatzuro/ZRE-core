/* ZRE Lap History: one comparative table; never promote projected values to observations. */
(()=>{'use strict';
 const $=id=>document.getElementById(id);
 const numeric=v=>typeof v==='number'&&Number.isFinite(v);
 const seconds=v=>numeric(v)&&v>0?Math.floor(v/60)+':'+(v%60).toFixed(3).padStart(6,'0'):'—';
 const average=values=>values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
 const deviation=values=>{const mean=average(values);return mean===null?null:Math.sqrt(average(values.map(n=>(n-mean)**2)))};
 const clean=rows=>(rows||[]).filter(r=>r.kind==='Normal'&&numeric(r.lap_time)&&r.lap_time>0&&r.source!=='SDK_MISSING');
 const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value==null?'—':String(value);if(cls)node.className=cls;return node};
 const decimal=(v,n=2)=>numeric(v)?v.toFixed(n):'—';
 const sameLap=(a,b)=>a&&b&&a.kind==='Normal'&&b.kind==='Normal'&&numeric(a.lap_time)&&numeric(b.lap_time);
 let lastSig=null;
 let send=null;
 let current=null;
 const compare=(a,b)=>a===null||b===null?'—':(b-a>0?'+':'')+(b-a).toFixed(3)+'s';
 const assign=(id,value)=>{const node=$(id);if(node)node.textContent=value};
 const rowCell=(row,tag,value,cls)=>{row.append(text(tag,value,cls))};
 function metric(data){
  const ours=clean(data.team),theirs=clean(data.rival),byLap=new Map(theirs.map(x=>[x.lap,x]));
  const pair=ours.filter(x=>sameLap(x,byLap.get(x.lap))).slice(-10);
  const a5=average(ours.slice(-5).map(x=>x.lap_time)),b5=average(theirs.slice(-5).map(x=>x.lap_time));
  const a10=average(ours.slice(-10).map(x=>x.lap_time)),b10=average(theirs.slice(-10).map(x=>x.lap_time));
  const bestA=ours.length?Math.min(...ours.map(x=>x.lap_time)):null;
  const bestB=theirs.length?Math.min(...theirs.map(x=>x.lap_time)):null;
  assign('lh-kpi-five',compare(a5,b5));
  assign('lh-kpi-ten',compare(a10,b10));
  assign('lh-kpi-best',compare(bestA,bestB));
  assign('lh-kpi-consistency',decimal(deviation(ours.slice(-10).map(x=>x.lap_time)))+'s / '+decimal(deviation(theirs.slice(-10).map(x=>x.lap_time)))+'s');
  assign('lh-kpi-laps',(data.team?.at(-1)?.lap??'—')+' / '+(data.rival?.at(-1)?.lap??'—'));
  assign('lh-kpi-pits',data.team.filter(x=>x.kind==='Entrada box').length+' / '+data.rival.filter(x=>x.kind==='Entrada box').length);
  assign('lh-kpi-trend',pair.length?compare(average(pair.slice(-5).map(x=>x.lap_time)),average(pair.slice(-5).map(x=>byLap.get(x.lap).lap_time))):'—');
  assign('lh-kpi-fuel',decimal(data.team?.at(-1)?.remaining,1)+' L');
 }
 function options(data){
  const select=$('lh-rival'),candidates=(current?.raceDirector?.candidates||[]),legacy=current?.raceDashboard?.classStandings||[];
  const list=candidates.length?candidates.map(c=>({idx:c.idx,label:c.label})):
    legacy.filter(r=>!r.isPlayer).map(r=>({idx:r.carIdx,label:'#'+r.carNumber+' · '+(r.driverName||'SIN IDENTIFICAR')}));
  const selected=current?.raceDirector?.selectedIdx ?? current?.raceDirector?.effectiveCarIdx ?? current?.raceDashboard?.rival?.effectiveCarIdx;
  const fingerprint=JSON.stringify([list,selected]);
  if(select.dataset.signature!==fingerprint){
    select.dataset.signature=fingerprint;
    select.replaceChildren(new Option('RIVAL ESTRATÉGICO / AUTO','auto'),
      ...list.filter(r=>r.idx!=null).map(r=>new Option(r.label,String(r.idx))));
    select.value=selected==null?'auto':String(selected);
    if(![...select.options].some(o=>o.value===select.value))select.value='auto';
  }
 }
 function draw(data){
  const filter=$('lh-filter')?.value||'all';
  const team=(data.team||[]).concat(data.projected||[]);
  const rivalMap=new Map((data.rival||[]).map(x=>[x.lap,x]));
  const all=new Set([...team.map(x=>x.lap),...(data.rival||[]).map(x=>x.lap)]);
  const teamMap=new Map(team.map(x=>[x.lap,x]));
  const numbers=[...all].sort((a,b)=>a-b).filter(n=>{
    if(filter==='all')return true;
    const a=teamMap.get(n),b=rivalMap.get(n);
    return (a?.kind==='Normal'||b?.kind==='Normal');
  });
  const sig=JSON.stringify([data.race,data.teamCarIdx,data.rivalCarIdx,team,data.rival,filter]);
  if(lastSig===sig)return;lastSig=sig;
  const rows=numbers.map(n=>{
    const ours=teamMap.get(n),rival=rivalMap.get(n);
    const tr=document.createElement('tr');
    tr.dataset.state=ours?.state||'RIVAL';
    rowCell(tr,'td',n,'lh-lap');
    rowCell(tr,'td',ours?.car_number?'#'+ours.car_number:'—');
    rowCell(tr,'td',ours?.driver|| (ours?.state==='PROYECTADO'?'PENDIENTE':'—'),'lh-driver');
    rowCell(tr,'td',ours?.state==='PROYECTADO'?'≈'+seconds(ours.lap_time):seconds(ours?.lap_time));
    const fuel=document.createElement('td');
    fuel.className='lh-fuel';
    if(ours?.remaining!=null){
      const prefix=ours.fuelSource==='ESTIMADO'?'≈':'';
      const label=text('span',prefix+decimal(ours.remaining,1)+' L');
      label.title='Fuente: '+(ours.fuelSource||'SIN DATO');
      fuel.append(label);
    } else fuel.append(text('span','—'));
    if(ours?.state==='REAL'){
      const btn=text('button','✎','lh-edit-button');
      btn.type='button';btn.title='Editar Remaining de V'+n;
      btn.addEventListener('click',()=>{
        $('lh-manual-lap').value=String(n);
        $('lh-manual-fuel').value=ours.remaining==null?'':String(ours.remaining);
        $('lh-manual-fuel').focus();
        $('lh-edit-status').textContent='Editando V'+n+' · los litros corresponden al paso por meta.';
      });
      fuel.append(btn);
    }
    tr.append(fuel);
    rowCell(tr,'td',decimal(ours?.avgConsumption,2),'lh-value');
    rowCell(tr,'td',ours?.kind||'—');
    rowCell(tr,'td',rival?.car_number?'#'+rival.car_number:'—');
    rowCell(tr,'td',rival?.driver||'—','lh-driver');
    rowCell(tr,'td',seconds(rival?.lap_time));
    rowCell(tr,'td',rival?.kind||'—');
    const delta=sameLap(ours,rival)?rival.lap_time-ours.lap_time:null;
    const d=text('td',delta==null?'—':(delta>0?'+':'')+delta.toFixed(3)+' s',delta==null?'':delta>=0?'lh-positive':'lh-negative');
    tr.append(d);
    return tr;
  });
  const body=$('lh-rows');if(body){const y=body.parentElement.scrollTop;body.replaceChildren(...rows);body.parentElement.scrollTop=y;}
  assign('lh-row-count',numbers.length+' VUELTAS · REAL Y PROYECTADO');
  metric(data);
  if(!$('lh-manual-lap').value&&data.team?.length)$('lh-manual-lap').value=String(data.team.at(-1).lap);
 }
 function render(packet,sendCommand){
  current=packet;send=sendCommand;
  const data=packet.lapDatabase||{available:false};
  const message=data.available?data.error||'REAL = vuelta terminada; el Remaining puede ser estimado. Δ positivo favorece a nuestro equipo.':data.reason||'Esperando historial SDK.';
  assign('lh-status',message);
  if(!data.available)return;
  options(data);
  draw(data);
 }
 function init(){
  $('lh-rival')?.addEventListener('change',e=>{send?.({type:'settings',key:'rival',value:e.target.value});lastSig=null;});
  $('lh-filter')?.addEventListener('change',()=>{lastSig=null;if(current)render(current,send);});
  $('lh-manual-form')?.addEventListener('submit',e=>{
    e.preventDefault();
    if(!current?.connected){assign('lh-edit-status','Sin conexión al SDK: edición no enviada');return;}
    const lap=Number($('lh-manual-lap').value),remaining=Number($('lh-manual-fuel').value);
    const data=current.lapDatabase||{},last=data.team?.at(-1)?.lap;
    if(!Number.isInteger(lap)||last==null||lap>last||!data.team?.some(r=>r.lap===lap)){
      assign('lh-edit-status','La vuelta debe estar registrada como real.');return;
    }
    if($('lh-manual-fuel').value.trim()===''||!numeric(remaining)||remaining<0||remaining>300){
      assign('lh-edit-status','Introduce litros válidos.');return;
    }
    if(!send){assign('lh-edit-status','ZRE sin conexión.');return;}
    send({type:'lapFuelEdit',lap,remaining});
    assign('lh-edit-status','Lectura enviada para V'+lap+' · esperando confirmación.');
  });
 }
 window.ZRELapHistory={init,render};
})();
